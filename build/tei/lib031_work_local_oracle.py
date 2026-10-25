"""Independent source-envelope and semantic checks for one LIB-031 work."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
TEI_NS = "http://www.tei-c.org/ns/1.0"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _kind(node: etree._Element) -> str:
    return node.tag if isinstance(node.tag, str) else "#comment"


def _selector(node: etree._Element, body: etree._Element) -> str:
    parts: list[str] = []
    current = node
    while current is not body:
        parent = current.getparent()
        if parent is None:
            raise ValueError("source node escaped body")
        tag = _kind(current)
        ordinal = sum(_kind(peer) == tag for peer in parent[: parent.index(current) + 1])
        parts.append(f"{tag}[{ordinal}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _one_primary(manifest: SourceManifest) -> Mapping[str, object]:
    sources = [item for item in manifest.record["authorities"] if item["role"] == "primary-source"]
    if len(sources) != 1:
        raise ValueError("one primary source required")
    return sources[0]


ORACLE_ID = "ocd-lib031-work-local-source-oracle"
ORACLE_VERSION = "1"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _import_closure_sha256(repository_root: Path) -> str:
    paths = [
        "build/tei/lib031_work_local_oracle.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/verifier.py",
        "ocd_kernel/tei/validate.py",
    ]
    return _sha(_canonical([{"path": path, "sha256": _sha((repository_root / path).read_bytes())} for path in paths]))


def _verify(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    primary = _one_primary(source_manifest)
    source_bytes = source_manifest.authority_path(str(primary["name"])).read_bytes()
    if _sha(source_bytes) != primary["sha256"]:
        raise ValueError("retained source changed")
    work_id = source_manifest.record["source_id"].removeprefix("ccel-lib031-work-")
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    matches = [item for item in profile["works"] if item["work_id"] == work_id]
    if len(matches) != 1 or primary["name"] != work_id + "-source":
        raise ValueError("work identity changed")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True)
    source = etree.fromstring(source_bytes, parser)
    head, body = source.find("ThML.head"), source.find("ThML.body")
    if source.tag != "ThML" or head is None or body is None:
        raise ValueError("complete retained ThML envelope required")
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    if (accounting.get("work_id") != work_id or accounting.get("source_path") != primary["path"]
            or accounting.get("source_sha256") != _sha(source_bytes)):
        raise ValueError("source accounting identity changed")
    header_nodes = list(head.iter())
    header_rows = accounting.get("source_header")
    if not isinstance(header_rows, list) or len(header_rows) != len(header_nodes):
        raise ValueError("source header inventory incomplete")
    for node, row in zip(header_nodes, header_rows, strict=True):
        if (row.get("tag"), row.get("attributes"), row.get("text"), row.get("tail")) != (_kind(node), dict(node.attrib), node.text or "", node.tail or ""):
            raise ValueError("source header inventory changed")
    if (accounting.get("source_body_boundary") != {"text": body.text or "", "tail": body.tail or "", "disposition": "excluded formatting whitespace"}
            or (body.text or "").strip() or (body.tail or "").strip()):
        raise ValueError("source body boundary changed")
    nodes = list(body.iter())[1:]
    rows = accounting.get("body_crosswalk")
    if not isinstance(rows, list) or len(rows) != len(nodes):
        raise ValueError("source body crosswalk incomplete")
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"), parser)
    if tei.tag != f"{{{TEI_NS}}}TEI" or not compiled_schema().validate(etree.ElementTree(tei)):
        raise ValueError("work-local TEI fails P5 XSD")
    ns = {"tei": TEI_NS}
    divisions = tei.xpath("./tei:text/tei:body/tei:div", namespaces=ns)
    if len(divisions) != 1 or divisions[0].get(XML_ID) != work_id:
        raise ValueError("work-local TEI boundary changed")
    title = tei.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=ns)
    source_hash = tei.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc//tei:idno[@type='sha256']", namespaces=ns)
    if len(title) != 1 or title[0].text != matches[0]["title"] or len(source_hash) != 1 or source_hash[0].text != _sha(source_bytes):
        raise ValueError("work-local TEI header identity changed")
    source_publisher = (head.findtext(".//DC.Publisher") or "").strip()
    publishers = tei.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:publisher", namespaces=ns)
    references = tei.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:ref", namespaces=ns)
    if ([node.text for node in publishers] != ([source_publisher] if source_publisher else [])
            or len(references) != 1 or references[0].get("target") != matches[0]["source_url"]
            or references[0].text != primary["path"]):
        raise ValueError("work-local source attribution changed")
    by_id: dict[str, etree._Element] = {}
    for node in divisions[0].iter():
        if isinstance(node.tag, str) and node.get(XML_ID):
            if node.get(XML_ID) in by_id:
                raise ValueError("duplicate TEI ID")
            by_id[str(node.get(XML_ID))] = node
    expected_ids = {work_id}
    source_ids: dict[str, str] = {}
    for node, row in zip(nodes, rows, strict=True):
        if row.get("work_id") != work_id or row.get("source_tag") != _kind(node) or row.get("source_selector") != _selector(node, body):
            raise ValueError("source selector or work binding changed")
        if (row.get("attributes"), row.get("direct_text"), row.get("tail_text")) != (dict(node.attrib), node.text or "", node.tail or ""):
            raise ValueError("retained source content changed")
        selector = row.get("tei_selector")
        if not isinstance(selector, str) or not selector.startswith("#"):
            raise ValueError("mapped TEI selector missing")
        target_id = selector[1:]
        expected_ids.add(target_id)
        source_id = node.get("id")
        if source_id:
            if source_id in source_ids:
                raise ValueError("duplicate retained source ID")
            source_ids[source_id] = target_id
    if set(by_id) != expected_ids:
        raise ValueError("unaccounted mapped TEI feature")
    semantic_heads = 0
    source_headings = 0
    localized = 0
    strong_tags = {"div1": "div", "div2": "div", "div3": "div", "div4": "div", "p": "p", "note": "note", "table": "table", "tr": "row", "td": "cell", "th": "cell", "verse": "lg", "l": "l", "a": "ref", "scripRef": "ref", "pb": "pb", "br": "lb", "i": "hi"}
    for node, row in zip(nodes, rows, strict=True):
        target = by_id[str(row["tei_selector"])[1:]]
        parent = node.getparent()
        is_source_heading = isinstance(node.tag, str) and node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}
        if is_source_heading:
            source_headings += 1
            leading_division_heading = (parent is not None and parent.tag in {"div1", "div2", "div3", "div4"}
                                        and all(isinstance(previous.tag, str) and previous.tag in {"h1", "h2", "h3", "h4", "h5", "h6"} for previous in parent[:parent.index(node)]))
            if leading_division_heading:
                if etree.QName(target).localname != "head":
                    raise ValueError("source division heading lost")
                if parent.index(node) == 0:
                    semantic_heads += 1
            elif target.get("rend") != "heading-level-" + node.tag[1:]:
                raise ValueError("nested source heading role lost")
        elif node.tag in strong_tags and etree.QName(target).localname != strong_tags[node.tag]:
            raise ValueError(f"source semantic carrier changed: {node.tag}")
        if node.tag == "a":
            fragment = node.get("href", "").partition("#")[2]
            if not fragment or fragment not in source_ids or target.get("target") != "#" + source_ids[fragment]:
                raise ValueError("source link target changed")
            localized += 1
        if node.tag == "i" and target.get("rend") != "italic":
            raise ValueError("source italic role changed")
        expected_attrs = row.get("tei_attributes")
        actual_attrs = {"xml:id" if key == XML_ID else "xml:lang" if key == XML_LANG else key: value for key, value in target.attrib.items()}
        if expected_attrs != actual_attrs:
            raise ValueError("mapped TEI attribute changed")
        target_parent = target.getparent()
        direct_text = node.text or ""
        title_head = row.get("source_title_head")
        source_has_heading_child = any(isinstance(child.tag, str) and child.tag in {"h1", "h2", "h3", "h4", "h5", "h6"} for child in node)
        if title_head and not source_has_heading_child:
            generated = target[0] if len(target) else None
            if generated is None or etree.QName(generated).localname != "head" or generated.text != title_head or generated.get(XML_ID):
                raise ValueError("source title head changed")
            target_text_ok = (target.text or "") == "" and (generated.tail or "") == direct_text
        else:
            target_text_ok = (target.text or "") == direct_text
        if (target_parent is None or target_parent.get(XML_ID) != row.get("tei_parent_id")
                or target_parent.index(target) + 1 != row.get("tei_child_ordinal")
                or (target.tail or "") != (node.tail or "") or not target_text_ok
                or etree.QName(target).localname != row.get("tei_tag")):
            raise ValueError("mapped TEI content or order changed")
    if (semantic_heads != accounting.get("first_child_division_heads")
            or source_headings != accounting.get("source_headings")
            or localized != accounting.get("localized_source_links")):
        raise ValueError("semantic heading/link accounting changed")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if provenance.get("work_id") != work_id or provenance.get("source_sha256") != _sha(source_bytes) or provenance.get("status") != "nonaccepted":
        raise ValueError("candidate provenance changed")
    return {"work_id": work_id, "source_body_nodes": len(nodes), "source_header_nodes": len(header_nodes), "source_headings": source_headings, "first_child_division_heads": semantic_heads, "localized_source_links": localized}


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    _verify(source_manifest, candidate)
    root = source_manifest.repository_root
    primary = _one_primary(source_manifest)
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=_import_closure_sha256(root),
        source_sha256=str(primary["sha256"]),
        profile_sha256=_sha(source_manifest.authority_path("reconstruction-profile").read_bytes()),
        package_schema_sha256=_sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        xsd_sha256=_sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        policy_sha256=_sha(source_manifest.authority_path("validation-policy").read_bytes()),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
