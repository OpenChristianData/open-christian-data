"""Source-first checker for readable LIB-054 work-local ThML candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TEI_NS = "http://www.tei-c.org/ns/1.0"
ORACLE_ID = "ocd-lib054-work-local-source-oracle"
ORACLE_VERSION = "1"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _import_closure_sha256(root: Path) -> str:
    paths = [
        "build/tei/lib054_work_local_oracle.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/verifier.py",
        "ocd_kernel/tei/validate.py",
    ]
    return _sha(_json([{"path": path, "sha256": _sha((root / path).read_bytes())} for path in paths]))


def _kind(node: etree._Element) -> str:
    return node.tag if isinstance(node.tag, str) else "#comment"


def _selector(node: etree._Element, body: etree._Element) -> str:
    parts: list[str] = []
    current = node
    while current is not body:
        parent = current.getparent()
        if parent is None:
            raise ValueError("source node escaped retained body")
        tag = _kind(current)
        ordinal = sum(_kind(peer) == tag for peer in parent[: parent.index(current) + 1])
        parts.append(f"{tag}[{ordinal}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _verify(manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    manifest.verify()
    candidate.verify_integrity()
    work_id = str(manifest.record["work_id"])
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    matches = [item for item in profile["works"] if item["work_id"] == work_id]
    primary = [item for item in manifest.record["authorities"] if item["role"] == "primary-source"]
    if len(matches) != 1 or len(primary) != 1:
        raise ValueError("work-local LIB-054 identity is ambiguous")
    work, binding = matches[0], primary[0]
    content = manifest.authority_path(str(binding["name"])).read_bytes()
    if (binding["path"], binding["sha256"], binding["bytes"]) != (work["source_path"], _sha(content), len(content)):
        raise ValueError("retained work source differs from family profile")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False, huge_tree=True)
    source = etree.fromstring(content, parser)
    heads, bodies = source.findall("ThML.head"), source.findall("ThML.body")
    if source.tag != "ThML" or len(heads) > 1 or len(bodies) != 1 or len(source) != len(heads) + 1:
        raise ValueError("retained ThML envelope changed")
    head, body = heads[0] if heads else None, bodies[0]
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    if accounting.get("work_id") != work_id or accounting.get("source_path") != binding["path"] or accounting.get("source_sha256") != _sha(content):
        raise ValueError("work-local source accounting identity changed")
    expected_header = ([{"tag": _kind(node), "attributes": dict(node.attrib), "text": node.text or "", "tail": node.tail or ""} for node in head.iter()] if head is not None else [])
    if accounting.get("source_header") != expected_header:
        raise ValueError("source header inventory changed")
    if accounting.get("source_body_boundary") != {"text": body.text or "", "tail": body.tail or ""} or (body.text or "").strip() or (body.tail or "").strip():
        raise ValueError("source body boundary changed")

    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"), parser)
    if tei.tag != f"{{{TEI_NS}}}TEI" or not compiled_schema().validate(etree.ElementTree(tei)):
        raise ValueError("work-local TEI fails P5 XSD")
    ns = {"tei": TEI_NS}
    divisions = tei.xpath("./tei:text/tei:body/tei:div", namespaces=ns)
    if len(divisions) != 1 or divisions[0].get(XML_ID) != work_id:
        raise ValueError("work-local TEI boundary changed")
    titles = tei.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=ns)
    authors = tei.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author", namespaces=ns)
    hashes = tei.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc//tei:idno[@type='sha256']", namespaces=ns)
    refs = tei.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc//tei:ref", namespaces=ns)
    publishers = tei.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc//tei:publisher", namespaces=ns)
    source_publisher = (head.findtext(".//DC.Publisher") or "").strip() if head is not None else ""
    if (len(titles), len(authors), len(hashes), len(refs)) != (1, 1, 1, 1) or (titles[0].text, authors[0].text, hashes[0].text, refs[0].get("target"), refs[0].text) != (work["title"], work["author"], _sha(content), work["source_url"], binding["path"]):
        raise ValueError("work-local TEI header identity changed")
    if [node.text for node in publishers] != ([source_publisher] if source_publisher else []):
        raise ValueError("retained source publisher attribution changed")

    nodes = list(body.iter())[1:]
    rows = accounting.get("body_crosswalk")
    if not isinstance(rows, list) or len(rows) != len(nodes):
        raise ValueError("source body crosswalk incomplete")
    mapped: dict[str, etree._Element] = {}
    for node in divisions[0].iter():
        if isinstance(node.tag, str) and node.get(XML_ID):
            key = str(node.get(XML_ID))
            if key in mapped:
                raise ValueError("duplicate TEI ID")
            mapped[key] = node
    source_to_tei: dict[str, str] = {}
    for node, row in zip(nodes, rows, strict=True):
        if row.get("work_id") != work_id or row.get("source_tag") != _kind(node) or row.get("source_selector") != _selector(node, body):
            raise ValueError("source node identity or order changed")
        if (row.get("attributes"), row.get("direct_text"), row.get("tail_text")) != (dict(node.attrib), node.text or "", node.tail or ""):
            raise ValueError("source node content changed")
        selector = row.get("tei_selector")
        if not isinstance(selector, str) or not selector.startswith("#") or selector[1:] not in mapped:
            raise ValueError("source node TEI target missing")
        source_id = node.get("id") if isinstance(node.tag, str) else None
        if source_id:
            if source_id in source_to_tei:
                raise ValueError("duplicate source ID")
            source_to_tei[source_id] = selector[1:]
    if set(mapped) != {work_id, *(str(row["tei_selector"])[1:] for row in rows)}:
        raise ValueError("unaccounted readable TEI carrier")

    local_links = 0
    semantic_tags = {"div1": "div", "div2": "div", "div3": "div", "div4": "div", "blockquote": "quote", "p": "p", "note": "note", "table": "table", "tr": "row", "td": "cell", "th": "cell", "verse": "lg", "l": "l", "a": "ref", "scripRef": "ref", "pb": "pb", "br": "lb", "i": "hi", "b": "hi", "ul": "list", "ol": "list", "li": "item"}
    for node, row in zip(nodes, rows, strict=True):
        target = mapped[str(row["tei_selector"])[1:]]
        tag = etree.QName(target).localname
        source_tag = _kind(node)
        if source_tag in semantic_tags and tag != semantic_tags[source_tag]:
            raise ValueError(f"source semantic carrier changed: {source_tag}")
        if source_tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            parent = node.getparent()
            leading = (parent is not None and isinstance(parent.tag, str) and parent.tag in {"div1", "div2", "div3", "div4"}
                       and all(isinstance(previous.tag, str) and previous.tag in {"h1", "h2", "h3", "h4", "h5", "h6"} for previous in parent[:parent.index(node)]))
            if leading and tag != "head":
                raise ValueError("source division heading lost")
            if not leading and tag not in {"head", "p", "seg"}:
                raise ValueError("source heading role lost")
        if source_tag == "i" and target.get("rend") != "italic":
            raise ValueError("source italic role changed")
        if source_tag == "b" and target.get("rend") != "bold":
            raise ValueError("source bold role changed")
        if source_tag == "a":
            href = node.get("href", "")
            expected = "#" + source_to_tei[href[1:]] if href.startswith("#") and href[1:] in source_to_tei else href
            if href.startswith("#") and href[1:] not in source_to_tei:
                raise ValueError("unresolved source-local link")
            if target.get("target", "") != expected:
                raise ValueError("source link target changed")
            local_links += href.startswith("#")
        parent = node.getparent()
        parent_id = work_id if parent is body else str(rows[nodes.index(parent)]["tei_selector"])[1:]
        if target.getparent() is None or target.getparent().get(XML_ID) != parent_id:
            raise ValueError("source nesting changed")
        siblings = [child for child in target.getparent() if isinstance(child.tag, str) and child.get(XML_ID)]
        source_siblings = [child for child in parent if child in nodes]
        if siblings.index(target) != source_siblings.index(node):
            raise ValueError("source sibling order changed")
        generated_head = row.get("source_title_head") and not any(isinstance(child.tag, str) and child.tag in {"h1", "h2", "h3", "h4", "h5", "h6"} for child in node)
        if generated_head:
            generated = target[0] if len(target) else None
            if generated is None or etree.QName(generated).localname != "head" or generated.text != row["source_title_head"] or generated.get(XML_ID):
                raise ValueError("source division title lost")
            text_ok = (target.text or "") == "" and (generated.tail or "") == (node.text or "")
        else:
            text_ok = (target.text or "") == (node.text or "")
        if not text_ok or (target.tail or "") != (node.tail or ""):
            raise ValueError("source text or tail changed")
    if local_links != accounting.get("localized_source_links"):
        raise ValueError("local link inventory changed")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if provenance.get("work_id") != work_id or provenance.get("source_sha256") != _sha(content) or provenance.get("status") != "nonaccepted":
        raise ValueError("work-local provenance changed")
    return {"work_id": work_id, "body_nodes": len(nodes), "header_nodes": len(expected_header), "local_links": local_links, "paragraphs": len(tei.xpath(".//tei:text//tei:p", namespaces=ns))}


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    _verify(manifest, candidate)
    root = manifest.repository_root
    primary = [item for item in manifest.record["authorities"] if item["role"] == "primary-source"][0]
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=_import_closure_sha256(root),
        source_sha256=str(primary["sha256"]),
        profile_sha256=_sha(manifest.authority_path("reconstruction-profile").read_bytes()),
        package_schema_sha256=_sha(manifest.authority_path("candidate-package-schema").read_bytes()),
        xsd_sha256=_sha(manifest.authority_path("tei-p5-xsd").read_bytes()),
        policy_sha256=_sha(manifest.authority_path("validation-policy").read_bytes()),
        findings=(),
    )
    return verify_mechanical_facts(manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
