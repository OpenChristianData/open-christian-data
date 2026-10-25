"""Check Satyrus, including exact Book II source heading ownership."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import sys

from lxml import etree

from build.tei.npnf_ambrose_oracle import (
    ASSIGNED,
    SOURCE_SHA256,
    _expected_dispositions,
    _expected_tei_attributes,
    _selector,
    _source_tree,
    _structure,
    _target_tag,
)
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-npnf210-satyrus-title-v3-source-oracle"
ORACLE_VERSION = "3"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
MEMBERS = {"README.source.md", "content.tei.xml", "manifest.json", "provenance.json", "source-accountability.json", "unresolved.jsonl"}


def _repeated_title(source: etree._Element) -> bool:
    title = source.get("title")
    if title is None or not str(source.tag).startswith("div"):
        return False
    expected = " ".join(title.split())
    children = [child for child in source if isinstance(child.tag, str)]
    if source.get("id") == "iv.iii.iii":
        visible = [child for child in children if child.tag not in ("pb", "hr")]
        if len(visible) < 2 or [visible[0].tag, visible[1].tag] != ["h3", "h4"]:
            raise ValueError("Satyrus Book II source heading structure changed")
        if " ".join("".join(node.itertext()) for node in visible[:2]).replace("\n", " ").split() != expected.split():
            raise ValueError("Satyrus Book II source title differs from its two headings")
        return True
    for index, child in enumerate(children):
        if child.tag not in ("h1", "h2", "h3", "h4"):
            continue
        heading = " ".join("".join(child.itertext()).split())
        if heading == expected:
            return True
        later = [other for other in children[index + 1:] if other.tag not in ("pb", "hr")]
        if later and later[0].tag == "p" and f"{heading} {' '.join(''.join(later[0].itertext()).split())}" == expected:
            return True
    return False


def _attrs(source: etree._Element, number: int) -> dict[str, str]:
    expected = _expected_tei_attributes(source, number)
    if source.tag in ("h1", "h2", "h3", "h4"):
        expected["type"] = "source-heading"
        expected["n"] = source.tag[1]
    if source.tag == "hr":
        expected["unit"] = "horizontal-rule"
    return expected


def _dispositions(source: etree._Element) -> list[dict[str, str]]:
    result = _expected_dispositions(source)
    if _repeated_title(source):
        for item in result:
            if item["source_attribute"] == "title":
                item["destination"] = "source-accountability"
                item["method"] = "redundant-explicit-content"
    return result


def _verify_work_node(source: etree._Element, target: etree._Element, number: list[int]) -> None:
    number[0] += 1
    if target.tag != f"{{{TEI_NS}}}{_target_tag(source)}":
        raise ValueError("work-local TEI source-kind drift")
    attributes = {(f"xml:{key.rpartition('}')[2]}" if key.startswith("{http://www.w3.org/XML/1998/namespace}") else key): value for key, value in target.attrib.items()}
    if attributes != _attrs(source, number[0]):
        raise ValueError("work-local TEI semantic attribute drift")
    if (target.text or "") != (source.text or "") or (target.tail or "") != (source.tail or ""):
        raise ValueError("work-local TEI direct text or tail drift")
    children = [child for child in target if isinstance(child.tag, str)]
    title = source.get("title") if str(source.tag).startswith("div") and not _repeated_title(source) else None
    offset = int(title is not None)
    if title is not None and (not children or children[0].tag != f"{{{TEI_NS}}}head" or children[0].text != title or children[0].attrib):
        raise ValueError("work-local TEI division title drift")
    source_children = [child for child in source if isinstance(child.tag, str)]
    if len(children) != len(source_children) + offset:
        raise ValueError("work-local TEI omission duplication or invention")
    for left, right in zip(source_children, children[offset:], strict=True):
        _verify_work_node(left, right, number)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _closure(root: Path) -> str:
    paths = (
        "build/tei/npnf_ambrose_satyrus_title_v3_oracle.py",
        "build/tei/npnf_ambrose_oracle.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/tei/validate.py",
    )
    return _sha(_canonical([{"path": path, "sha256": _sha((root / path).read_bytes())} for path in paths]))


def _expected_work_rows(source_div: etree._Element, work_id: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    def visit(node: etree._Element, parent_feature_id: str | None, parent_id: str, ordinal: int) -> None:
        number = len(rows) + 1
        feature_id = f"npnf-ambrose-feature-{number:05d}"
        attrs = _attrs(node, number)
        row: dict[str, object] = {
            "feature_id": feature_id,
            "source_selector": _selector(node),
            "source_tag": node.tag,
            "source_xml_id": node.get("id"),
            "attributes": dict(node.attrib),
            "direct_text": node.text or "",
            "tail_text": node.tail or "",
            "direct_text_sha256": _sha((node.text or "").encode("utf-8")),
            "tail_text_sha256": _sha((node.tail or "").encode("utf-8")),
            "tei_tag": _target_tag(node),
            "tei_xml_id": attrs["xml:id"],
            "tei_parent_id": parent_id,
            "tei_child_ordinal": ordinal,
            "tei_attributes": attrs,
            "attribute_dispositions": _dispositions(node),
            "disposition": "represented",
            "tei_selector": f"#{attrs['xml:id']}",
            "parent_feature_id": parent_feature_id,
            "source_title_head": node.get("title") if str(node.tag).startswith("div") and not _repeated_title(node) else None,
        }
        rows.append(row)
        offset = int(node.get("title") is not None and str(node.tag).startswith("div") and not _repeated_title(node))
        for child_ordinal, child in enumerate(node, start=1):
            if not isinstance(child.tag, str):
                raise ValueError("assigned work contains comment or processing instruction")
            visit(child, feature_id, str(attrs["xml:id"]), offset + child_ordinal)

    visit(source_div, None, f"{work_id}-body", 1)
    rows[0]["work_id"] = work_id
    return rows


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    if set(candidate.member_names) != MEMBERS or candidate.manifest["status"] != "nonaccepted":
        raise ValueError("work-local package member set or status changed")
    root = source_manifest.repository_root
    work_id = str(source_manifest.record["work_id"])
    work = json.loads(source_manifest.authority_path("work-identity").read_bytes())
    edition = work["textual_forms"][0]["editions"][0]
    acquisition = json.loads(source_manifest.authority_path("acquisition").read_bytes())
    if work["work_id"] != work_id or acquisition["acquisition_id"] != edition["acquisition_ids"][0]:
        raise ValueError("work, edition, acquisition identity mismatch")
    source_bytes = source_manifest.authority_path("retained-thml").read_bytes()
    if len(source_bytes) != 3_837_030 or _sha(source_bytes) != SOURCE_SHA256 or acquisition["source_sha256"] != SOURCE_SHA256:
        raise ValueError("retained source authority changed")
    source_tree = _source_tree(source_bytes)
    _top, selected = _structure(source_tree)
    assigned = dict(ASSIGNED)
    locator = edition["containing_source"]["locator"]
    scope = locator.rpartition("#")[2]
    if assigned.get(scope) != work_id or locator != f"raw/ccel/npnf2/npnf210.xml#{scope}":
        raise ValueError("work locator is not an assigned child boundary")
    matches = [node for node in selected if node.get("id") == scope]
    if len(matches) != 1:
        raise ValueError("source child selection is ambiguous")
    source_div = matches[0]
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    if (accounting.get("work_id") != work_id or accounting.get("edition_id") != edition["edition_id"]
            or accounting.get("acquisition_id") != acquisition["acquisition_id"]
            or accounting.get("source_sha256") != SOURCE_SHA256
            or accounting.get("source_locator") != locator
            or accounting.get("source_root_id") != scope):
        raise ValueError("work-local source accounting identity changed")
    expected_rows = _expected_work_rows(source_div, work_id)
    if accounting.get("crosswalk") != expected_rows:
        raise ValueError("source-to-TEI feature crosswalk differs from independent source walk")
    nodes = [node for node in source_div.iter() if isinstance(node.tag, str)]
    census = {
        "source_feature_count": len(nodes),
        "source_attribute_count": sum(len(node.attrib) for node in nodes),
        "source_text_node_count": sum(node.text is not None for node in nodes),
        "source_tail_node_count": sum(node.tail is not None for node in nodes),
        "source_character_count": sum(len((node.text or "") + (node.tail or "")) for node in nodes),
    }
    if any(accounting.get(key) != value for key, value in census.items()) or accounting.get("omitted_feature_count") != 0 or accounting.get("duplicate_feature_count") != 0:
        raise ValueError("source conservation census changed")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False, huge_tree=True)
    tei_tree = etree.ElementTree(etree.fromstring(candidate.member_bytes("content.tei.xml"), parser))
    compiled_schema().assertValid(tei_tree)
    tei = tei_tree.getroot()
    ns = {"tei": TEI_NS}
    if tei.tag != f"{{{TEI_NS}}}TEI" or tei.get(XML_ID) != work_id:
        raise ValueError("work-local TEI root identity changed")
    if [etree.QName(child).localname for child in tei] != ["teiHeader", "text"]:
        raise ValueError("work-local TEI envelope changed")
    titles = tei.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=ns)
    authors = tei.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author", namespaces=ns)
    references = tei.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:ref", namespaces=ns)
    hashes = tei.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='sha256']", namespaces=ns)
    if ([n.text for n in titles] != [work["title"]] or [n.text for n in authors] != ["Ambrose of Milan"]
            or len(references) != 1 or references[0].get("target") != acquisition["url"] or references[0].text != locator
            or [n.text for n in hashes] != [SOURCE_SHA256]):
        raise ValueError("work-local TEI header source or work identity changed")
    bodies = tei.xpath("./tei:text/tei:body", namespaces=ns)
    if len(bodies) != 1 or bodies[0].get(XML_ID) != f"{work_id}-body" or len(bodies[0]) != 1:
        raise ValueError("work-local TEI body boundary changed")
    count = [0]
    _verify_work_node(source_div, bodies[0][0], count)
    if count[0] != len(nodes):
        raise ValueError("work-local TEI node count changed")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if (provenance.get("status") != "nonaccepted" or provenance.get("work_id") != work_id
            or provenance.get("source_locator") != locator or provenance.get("source_sha256") != SOURCE_SHA256
            or provenance.get("publication") != "not-ready"):
        raise ValueError("work-local candidate provenance changed")
    result = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _closure(root),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(source_manifest.authority_path("reconstruction-profile").read_bytes()),
        "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": SOURCE_SHA256,
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(source_manifest.authority_path("validation-policy").read_bytes()),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
