"""Independent source reader and candidate oracle for 37c-267 / LIB-055."""

from __future__ import annotations

from collections import Counter
import hashlib
import io
import json
from pathlib import Path
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import _canonical, _validation_authority_bindings
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "rutherford-letters-lib055-independent-source-oracle"
ORACLE_VERSION = "1"
WORK_ID = "rutherford-letters"
TICKET_ID = "37c-267"
SOURCE_PATH = "raw/ccel/rutherford/letters.xml"
SOURCE_BYTES = 285570
SOURCE_SHA256 = "33fda0ccc68d7e35aec2dbe6abd366ca55e81c8a116973c9ed69e3becede6ebf"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
SUPPORTED = {
    "div1": "div", "div2": "div", "div": "div", "p": "p",
    "h1": "head", "h2": "head", "a": "ref", "scripRef": "ref",
    "i": "hi", "span": "hi", "br": "lb", "insertIndex": "anchor",
    "table": "table", "tr": "row", "td": "cell", "th": "cell",
}
EXCLUDED = {"colgroup", "col"}
CLOSURE = (
    "build/tei/ccel_puritan_lib055_rutherford_letters_oracle.py",
    "ocd_kernel/reconstruction/contract.py",
    "ocd_kernel/reconstruction/verifier.py",
    "ocd_kernel/tei/validate.py",
)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _read_json(value: bytes, label: str) -> dict[str, object]:
    try:
        result = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(result, dict):
        raise ValueError(f"{label} must be an object")
    return result


def _local(node: etree._Element) -> str:
    if not isinstance(node.tag, str):
        raise ValueError("expected XML element")
    return etree.QName(node).localname


def _tree(raw: bytes) -> etree._ElementTree:
    return etree.parse(io.BytesIO(raw), etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False, remove_comments=False, remove_pis=False, remove_blank_text=False, huge_tree=True))


def _profile(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot(); head = root.find("ThML.head"); body = root.find("ThML.body")
    if _local(root) != "ThML" or head is None or body is None:
        raise ValueError("retained source envelope is not complete ThML")
    all_elements = [n for n in root.iter() if isinstance(n.tag, str)]
    head_elements = [n for n in head.iter() if isinstance(n.tag, str)]
    body_elements = [n for n in body.iter() if isinstance(n.tag, str)]
    return {"root": "ThML", "xml_version": tree.docinfo.xml_version, "encoding": tree.docinfo.encoding,
            "doctype": {"name": "ThML", "public_id": tree.docinfo.public_id, "system_url": tree.docinfo.system_url},
            "element_count": len(all_elements), "head_element_count_including_wrapper": len(head_elements),
            "body_element_count_including_wrapper": len(body_elements), "prolog_comment_count": 0,
            "in_root_comment_count": 0, "post_root_comment_count": 0,
            "stylesheet_processing_instruction_count": 0, "post_root_processing_instruction_count": 0,
            "source_tag_counts": dict(sorted(Counter(_local(n) for n in all_elements).items())),
            "body_tag_counts_excluding_wrapper": dict(sorted(Counter(_local(n) for n in body_elements[1:]).items())),
            "top_level_div1_ids": [n.get("id") for n in body if isinstance(n.tag, str) and _local(n) == "div1"],
            "top_level_div1_source_titles": [n.get("title") for n in body if isinstance(n.tag, str) and _local(n) == "div1"]}


def _attrs(source: etree._Element, tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    if source.get("id"):
        attrs[f"{{{XML_NS}}}id"] = source.get("id", "")
    if tag in {"div1", "div2", "div"}:
        attrs["type"] = f"source-{tag}"
        if source.get("title"):
            attrs["n"] = source.get("title", "")
    if tag in {"h1", "h2"}:
        attrs["type"] = f"source-{tag}"
    if tag == "p":
        values = [source.get(name) for name in ("class", "style") if source.get(name)]
        if values: attrs["rend"] = " ; ".join(values)
    if tag == "a" and source.get("href"): attrs["target"] = source.get("href", "")
    if tag == "scripRef":
        attrs["type"] = "scripture"
        if source.get("osisRef"): attrs["target"] = source.get("osisRef", "")
        if source.get("passage"): attrs["n"] = source.get("passage", "")
    if tag == "i": attrs["rend"] = "italic"
    if tag == "span" and source.get("style"): attrs["rend"] = source.get("style", "")
    if tag == "insertIndex":
        attrs["type"] = "index-insertion"
        if source.get("type"): attrs["subtype"] = source.get("type", "")
    if tag == "table" and source.get("style"): attrs["rend"] = source.get("style", "")
    if tag in {"td", "th"} and source.get("colspan"): attrs["cols"] = source.get("colspan", "")
    if tag == "th": attrs["role"] = "label"
    return attrs


def _expected_node(source: etree._Element) -> tuple:
    tag = _local(source)
    if tag in EXCLUDED:
        raise ValueError("excluded presentation node cannot be expected as TEI")
    children = []
    if tag in {"div1", "div2", "div"} and source.get("title"):
        title = " ".join(source.get("title", "").split()).casefold()
        direct_heading = any(_local(item) in {"h1", "h2"} and " ".join("".join(item.itertext()).split()).casefold() == title for item in source if isinstance(item.tag, str))
        if not direct_heading:
            children.append(("head", (("type", "source-title"),), source.get("title", ""), (), ""))
    for child in source:
        if not isinstance(child.tag, str):
            continue
        if _local(child) in EXCLUDED:
            continue
        children.append(_expected_node(child))
    return (SUPPORTED[tag], tuple(sorted(_attrs(source, tag).items())), source.text or "", tuple(children), source.tail or "")


def _actual_node(node: etree._Element) -> tuple:
    return (etree.QName(node).localname, tuple(sorted(node.attrib.items())), node.text or "", tuple(_actual_node(child) for child in node if isinstance(child.tag, str)), node.tail or "")


def _rows(tree: etree._ElementTree) -> list[dict[str, object]]:
    root = tree.getroot(); head = root.find("ThML.head"); body = root.find("ThML.body")
    assert head is not None and body is not None
    rows = []
    for ordinal, node in enumerate((n for n in root.iter() if isinstance(n.tag, str)), 1):
        tag = _local(node)
        if node is root: disposition, tei_tag = "document-root-mapped", "TEI"
        elif tag in EXCLUDED: disposition, tei_tag = "excluded-presentation-only", None
        elif node is head: disposition, tei_tag = "header-accounted", None
        elif node is body: disposition, tei_tag = "body-wrapper-mapped", "body"
        elif tag in SUPPORTED: disposition, tei_tag = "body-element-mapped", SUPPORTED[tag]
        else: disposition, tei_tag = "header-accounted", None
        rows.append({"ordinal": ordinal, "source_path": tree.getpath(node), "parent_source_path": tree.getpath(node.getparent()) if node.getparent() is not None else None,
                     "tag": tag, "attributes": dict(sorted(node.attrib.items())), "direct_text": node.text or "", "tail_text": node.tail or "",
                     "direct_text_sha256": _sha((node.text or "").encode("utf-8")), "tail_text_sha256": _sha((node.tail or "").encode("utf-8")),
                     "disposition": disposition, "tei_element": tei_tag})
    return rows


def _accountability(manifest, tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot(); body = root.find("ThML.body"); head = root.find("ThML.head")
    assert body is not None and head is not None
    carriers = [{"position": i, "native_id": node.get("id"), "source_tag": _local(node), "source_title": node.get("title"), "disposition": "selected-complete-envelope"} for i, node in enumerate(body) if isinstance(node.tag, str)]
    shell = {"xml_declaration": '<?xml version="1.0" encoding="UTF-8"?>', "doctype": tree.docinfo.doctype, "root_name": "ThML", "prolog": [], "epilog": [], "comments_and_processing_instructions": [], "head_children": [{"position": i, "tag": _local(node), "attributes": dict(node.attrib), "text_sha256": _sha("".join(node.itertext()).encode("utf-8")), "disposition": "accounted-source-header"} for i, node in enumerate(head) if isinstance(node.tag, str)]}
    rows = _rows(tree)
    return {"contract": "rutherford-letters-source-accountability-v1", "schema": "source-accountability.schema.json", "work_id": WORK_ID,
            "source_member": {"path": SOURCE_PATH, "bytes": SOURCE_BYTES, "sha256": SOURCE_SHA256}, "scope": _plain(manifest.record["scope"]),
            "document": _profile(tree), "carrier_inventory": carriers, "body_node_sequence": carriers, "document_shell": shell,
            "elements": rows, "exclusions": [{"source_path": row["source_path"], "tag": row["tag"], "reason": "presentation-only column declaration; no reading content"} for row in rows if row["tag"] in EXCLUDED]}


def _closure_digest(root: Path) -> str:
    return _sha(_canonical([{"path": path, "sha256": _sha((root / path).read_bytes())} for path in CLOSURE]))


def _oracle(manifest, candidate) -> Mapping[str, object]:
    manifest.verify()
    if manifest.record.get("ticket") != TICKET_ID or manifest.record.get("work_id") != WORK_ID:
        raise ValueError("oracle received a different route")
    raw = manifest.authority_path("retained-source").read_bytes()
    if len(raw) != SOURCE_BYTES or _sha(raw) != SOURCE_SHA256:
        raise ValueError("retained source identity drifted")
    source_tree = _tree(raw)
    profile = _read_json(manifest.authority_path("profile").read_bytes(), "feature profile")
    if profile.get("document") != _profile(source_tree):
        raise ValueError("independent source census differs from the bound profile")
    candidate_tei = candidate.member_bytes("content.tei.xml")
    tei_tree = etree.fromstring(candidate_tei, etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False, remove_comments=False, remove_pis=False, huge_tree=True))
    schema = compiled_schema()
    if not schema.validate(tei_tree):
        raise ValueError(f"candidate TEI fails TEI schema: {schema.error_log.last_error}")
    root = source_tree.getroot(); source_title = root.findtext("ThML.head/electronicEdInfo/DC/DC.Title")
    source_creator = next((x.text or "" for x in root.findall("ThML.head/electronicEdInfo/DC/DC.Creator") if x.get("sub") == "Author" and x.get("scheme") == "short-form"), None)
    if tei_tree.findtext(f".//{{{TEI_NS}}}titleStmt/{{{TEI_NS}}}title") != source_title or tei_tree.findtext(f".//{{{TEI_NS}}}titleStmt/{{{TEI_NS}}}author") != source_creator:
        raise ValueError("candidate source metadata title or author drifted")
    work_id = tei_tree.find(f".//{{{TEI_NS}}}idno[@type='ocd-work-id']")
    binding = tei_tree.find(f".//{{{TEI_NS}}}bibl[@type='retained-source-member']")
    if work_id is None or work_id.text != WORK_ID or binding is None or binding.findtext(f"{{{TEI_NS}}}idno[@type='source-member-path']") != SOURCE_PATH:
        raise ValueError("candidate source binding is incomplete")
    body = tei_tree.find(f".//{{{TEI_NS}}}text/{{{TEI_NS}}}body")
    source_body = root.find("ThML.body")
    assert body is not None and source_body is not None
    expected = [ _expected_node(node) for node in source_body if isinstance(node.tag, str) and _local(node) not in EXCLUDED ]
    actual = [_actual_node(node) for node in body if isinstance(node.tag, str)]
    if actual != expected:
        raise ValueError("candidate TEI differs in source order, wording, structure, attributes, or tails")
    account = _read_json(candidate.member_bytes("source-accountability.json"), "candidate source accountability")
    schema_record = _read_json(manifest.authority_path("source-accountability-schema").read_bytes(), "source-accountability schema")
    errors = sorted(Draft202012Validator(schema_record).iter_errors(account), key=str)
    if errors:
        raise ValueError(f"source-accountability schema failure: {errors[0].message}")
    expected_account = _accountability(manifest, source_tree)
    if account != expected_account:
        raise ValueError("candidate source-accountability differs from independent source enumeration")
    policy = _read_json(manifest.authority_path("policy").read_bytes(), "validation policy")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_json(row) for row in policy["unresolved_records"]):
        raise ValueError("candidate unresolved claims differ from the bound policy")
    if candidate.member_bytes("README.source.md") != manifest.authority_path("source-readme").read_bytes():
        raise ValueError("candidate source attribution deliverable differs")
    expected_provenance = {"contract": "ocd-source-to-tei-provenance-v1", "ticket": TICKET_ID, "owner_route": "LIB-055", "work_id": WORK_ID,
        "source_member": {"path": SOURCE_PATH, "bytes": SOURCE_BYTES, "sha256": SOURCE_SHA256},
        "source_manifest": {"path": manifest.path.relative_to(manifest.repository_root).as_posix(), "sha256": manifest.sha256},
        "converter": _plain(manifest.record["converter"]), "profile_sha256": _sha(manifest.authority_path("profile").read_bytes()),
        "policy_sha256": _sha(manifest.authority_path("policy").read_bytes()), "candidate_status": "nonaccepted", "human_acceptance": "not-assessed", "publication_status": "not-authorized"}
    if _read_json(candidate.member_bytes("provenance.json"), "candidate provenance") != expected_provenance:
        raise ValueError("candidate provenance is stale or misbound")
    bindings = _validation_authority_bindings(manifest)
    facts = MechanicalFacts(validator_implementation_sha256=_sha(Path(__file__).read_bytes()), validator_import_closure_sha256=_closure_digest(manifest.repository_root),
                            source_sha256=SOURCE_SHA256, profile_sha256=bindings["profile_sha256"], package_schema_sha256=bindings["package_schema_sha256"], xsd_sha256=bindings["xsd_sha256"], policy_sha256=bindings["policy_sha256"], findings=())
    return verify_mechanical_facts(manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
