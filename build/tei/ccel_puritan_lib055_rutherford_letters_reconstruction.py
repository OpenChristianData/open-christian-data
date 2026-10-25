"""Ticket-local LIB-055 producer for the retained Rutherford ThML envelope."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree


CONVERTER_ID = "rutherford-letters-lib055-source-to-tei"
CONVERTER_VERSION = "1"
WORK_ID = "rutherford-letters"
TICKET_ID = "37c-267"
OWNER_ROUTE = "LIB-055"
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


def _authority(manifest, name: str) -> Mapping[str, object]:
    matches = [item for item in manifest.record["authorities"] if item.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"manifest must bind exactly one {name!r} authority")
    return matches[0]


def _bytes(manifest, name: str) -> bytes:
    return manifest.authority_path(name).read_bytes()


def _parse(raw: bytes) -> etree._ElementTree:
    return etree.parse(
        __import__("io").BytesIO(raw),
        etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False,
                        remove_comments=False, remove_pis=False, remove_blank_text=False,
                        huge_tree=True),
    )


def _local(node: etree._Element) -> str:
    if not isinstance(node.tag, str):
        raise ValueError("expected an XML element")
    return etree.QName(node).localname


def _document_profile(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()
    head = root.find("ThML.head")
    body = root.find("ThML.body")
    if _local(root) != "ThML" or head is None or body is None:
        raise ValueError("retained source must contain ThML head and body")
    all_elements = [n for n in root.iter() if isinstance(n.tag, str)]
    head_elements = [n for n in head.iter() if isinstance(n.tag, str)]
    body_elements = [n for n in body.iter() if isinstance(n.tag, str)]
    return {
        "root": "ThML", "xml_version": tree.docinfo.xml_version,
        "encoding": tree.docinfo.encoding,
        "doctype": {"name": "ThML", "public_id": tree.docinfo.public_id, "system_url": tree.docinfo.system_url},
        "element_count": len(all_elements),
        "head_element_count_including_wrapper": len(head_elements),
        "body_element_count_including_wrapper": len(body_elements),
        "prolog_comment_count": 0, "in_root_comment_count": 0,
        "post_root_comment_count": 0, "stylesheet_processing_instruction_count": 0,
        "post_root_processing_instruction_count": 0,
        "source_tag_counts": dict(sorted(Counter(_local(n) for n in all_elements).items())),
        "body_tag_counts_excluding_wrapper": dict(sorted(Counter(_local(n) for n in body_elements[1:]).items())),
        "top_level_div1_ids": [n.get("id") for n in body if isinstance(n.tag, str) and _local(n) == "div1"],
        "top_level_div1_source_titles": [n.get("title") for n in body if isinstance(n.tag, str) and _local(n) == "div1"],
    }


def _mapped_attributes(source: etree._Element, tag: str) -> dict[str, str]:
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
        parts = [source.get(name) for name in ("class", "style") if source.get(name)]
        if parts:
            attrs["rend"] = " ; ".join(parts)
    if tag == "a" and source.get("href"):
        attrs["target"] = source.get("href", "")
    if tag == "scripRef":
        attrs["type"] = "scripture"
        if source.get("osisRef"):
            attrs["target"] = source.get("osisRef", "")
        if source.get("passage"):
            attrs["n"] = source.get("passage", "")
    if tag == "i":
        attrs["rend"] = "italic"
    if tag == "span" and source.get("style"):
        attrs["rend"] = source.get("style", "")
    if tag == "insertIndex":
        attrs["type"] = "index-insertion"
        if source.get("type"):
            attrs["subtype"] = source.get("type", "")
    if tag == "table" and source.get("style"):
        attrs["rend"] = source.get("style", "")
    if tag in {"td", "th"} and source.get("colspan"):
        attrs["cols"] = source.get("colspan", "")
    if tag == "th":
        attrs["role"] = "label"
    return attrs


def _append_children(source: etree._Element, target: etree._Element, tree: etree._ElementTree) -> None:
    target.text = source.text
    for child in source:
        if isinstance(child, etree._Comment):
            made = etree.Comment(child.text or "")
            made.tail = child.tail
            target.append(made)
            continue
        if not isinstance(child.tag, str):
            raise ValueError(f"unsupported source node at {tree.getpath(child)}")
        tag = _local(child)
        if tag in EXCLUDED:
            continue
        if tag not in SUPPORTED:
            raise ValueError(f"unsupported retained body element {tag!r} at {tree.getpath(child)}")
        made = etree.Element(f"{{{TEI_NS}}}{SUPPORTED[tag]}", nsmap=None)
        for key, value in _mapped_attributes(child, tag).items():
            made.set(key, value)
        if tag in {"div1", "div2", "div"} and child.get("title"):
            title = " ".join(child.get("title", "").split()).casefold()
            direct_heading = any(
                _local(item) in {"h1", "h2"}
                and " ".join("".join(item.itertext()).split()).casefold() == title
                for item in child if isinstance(item.tag, str)
            )
            if not direct_heading:
                synthetic = etree.SubElement(made, f"{{{TEI_NS}}}head", type="source-title")
                synthetic.text = child.get("title", "")
        _append_children(child, made, tree)
        made.tail = child.tail
        target.append(made)


def _provider_values(root: etree._Element) -> dict[str, object]:
    head = root.find("ThML.head")
    assert head is not None
    title = head.find(".//DC.Title")
    creator = next((x for x in head.findall(".//DC.Creator") if x.get("sub") == "Author" and x.get("scheme") == "short-form"), None)
    publisher = head.find(".//DC.Publisher")
    date = head.find(".//DC.Date")
    identifier = head.find(".//DC.Identifier")
    language = head.find(".//DC.Language")
    description = head.find(".//description")
    required = (title, creator, publisher, date, identifier, language, description)
    if any(value is None for value in required):
        raise ValueError("retained provider metadata is incomplete")
    return {
        "title": title.text or "", "creator": creator.text or "", "publisher": publisher.text or "",
        "date": date.text or "", "identifier": identifier.text or "", "language": language.text or "",
        "description": description.text or "", "subjects": [x.text or "" for x in head.findall(".//DC.Subject")],
    }


def _build_tei(tree: etree._ElementTree, raw: bytes) -> bytes:
    root = tree.getroot()
    values = _provider_values(root)
    tei = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    header = etree.SubElement(tei, f"{{{TEI_NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}title", type="source-record-title").text = values["title"]
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}author").text = values["creator"]
    publication = etree.SubElement(file_desc, f"{{{TEI_NS}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI_NS}}}publisher").text = values["publisher"]
    etree.SubElement(publication, f"{{{TEI_NS}}}date", type="source-record-created", when=values["date"]).text = values["date"]
    etree.SubElement(publication, f"{{{TEI_NS}}}idno", type="source-record-uri").text = values["identifier"]
    etree.SubElement(publication, f"{{{TEI_NS}}}idno", type="ocd-work-id").text = WORK_ID
    notes = etree.SubElement(file_desc, f"{{{TEI_NS}}}notesStmt")
    etree.SubElement(notes, f"{{{TEI_NS}}}note", type="technical-status").text = "Nonaccepted technical candidate; human acceptance, rights clearance, accepted IR, and publication are not authorized."
    etree.SubElement(notes, f"{{{TEI_NS}}}note", type="identity-boundary").text = "The retained source and catalog route labels are preserved without resolving work boundary, textual form, edition, constituent parts, or witness lineage."
    etree.SubElement(notes, f"{{{TEI_NS}}}note", type="source-record-description").text = values["description"]
    source_desc = etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{TEI_NS}}}bibl", type="retained-source-member")
    etree.SubElement(bibl, f"{{{TEI_NS}}}title").text = values["title"]
    etree.SubElement(bibl, f"{{{TEI_NS}}}author").text = values["creator"]
    etree.SubElement(bibl, f"{{{TEI_NS}}}idno", type="source-member-path").text = SOURCE_PATH
    etree.SubElement(bibl, f"{{{TEI_NS}}}idno", type="ocd-work-id").text = WORK_ID
    etree.SubElement(bibl, f"{{{TEI_NS}}}note", type="source-member-binding").text = f"{len(raw)} bytes; SHA-256 {SOURCE_SHA256}."
    encoding = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
    etree.SubElement(etree.SubElement(encoding, f"{{{TEI_NS}}}projectDesc"), f"{{{TEI_NS}}}p").text = "All six ThML.body/div1 carriers and every supported descendant are represented in source order; colgroup/col are recorded as presentation-only exclusions."
    profile = etree.SubElement(header, f"{{{TEI_NS}}}profileDesc")
    usage = etree.SubElement(profile, f"{{{TEI_NS}}}langUsage")
    etree.SubElement(usage, f"{{{TEI_NS}}}language", ident=values["language"]).text = values["language"]
    keywords = etree.SubElement(etree.SubElement(profile, f"{{{TEI_NS}}}textClass"), f"{{{TEI_NS}}}keywords", scheme="CCEL-DC.Subject")
    for subject in values["subjects"]:
        etree.SubElement(keywords, f"{{{TEI_NS}}}term").text = subject
    text = etree.SubElement(tei, f"{{{TEI_NS}}}text")
    body = etree.SubElement(text, f"{{{TEI_NS}}}body")
    source_body = root.find("ThML.body")
    assert source_body is not None
    _append_children(source_body, body, tree)
    return etree.tostring(tei, encoding="UTF-8", xml_declaration=True)


def _element_rows(tree: etree._ElementTree) -> list[dict[str, object]]:
    root = tree.getroot()
    rows = []
    for ordinal, node in enumerate((n for n in root.iter() if isinstance(n.tag, str)), 1):
        tag = _local(node)
        if node is root:
            disposition, tei_tag = "document-root-mapped", "TEI"
        elif tag in EXCLUDED:
            disposition, tei_tag = "excluded-presentation-only", None
        elif node is root.find("ThML.head"):
            disposition, tei_tag = "header-accounted", None
        elif node is root.find("ThML.body"):
            disposition, tei_tag = "body-wrapper-mapped", "body"
        elif tag in SUPPORTED:
            disposition, tei_tag = "body-element-mapped", SUPPORTED[tag]
        else:
            disposition, tei_tag = "header-accounted", None
        rows.append({
            "ordinal": ordinal, "source_path": tree.getpath(node),
            "parent_source_path": tree.getpath(node.getparent()) if node.getparent() is not None else None,
            "tag": tag, "attributes": dict(sorted(node.attrib.items())),
            "direct_text": node.text or "", "tail_text": node.tail or "",
            "direct_text_sha256": _sha((node.text or "").encode("utf-8")),
            "tail_text_sha256": _sha((node.tail or "").encode("utf-8")),
            "disposition": disposition, "tei_element": tei_tag,
        })
    return rows


def _source_accountability(manifest, tree: etree._ElementTree, profile: Mapping[str, object]) -> bytes:
    observed = _document_profile(tree)
    if profile.get("document") != observed:
        raise ValueError("source feature profile does not match retained bytes")
    body = tree.getroot().find("ThML.body")
    assert body is not None
    carriers = [{"position": i, "native_id": node.get("id"), "source_tag": _local(node), "source_title": node.get("title"), "disposition": "selected-complete-envelope"} for i, node in enumerate(body) if isinstance(node.tag, str)]
    shell = {"xml_declaration": '<?xml version="1.0" encoding="UTF-8"?>', "doctype": tree.docinfo.doctype, "root_name": "ThML", "prolog": [], "epilog": [], "comments_and_processing_instructions": [], "head_children": [{"position": i, "tag": _local(node), "attributes": dict(node.attrib), "text_sha256": _sha("".join(node.itertext()).encode("utf-8")), "disposition": "accounted-source-header"} for i, node in enumerate(tree.getroot().find("ThML.head")) if isinstance(node.tag, str)]}
    return _json({
        "contract": "rutherford-letters-source-accountability-v1", "schema": "source-accountability.schema.json", "work_id": WORK_ID,
        "source_member": {"path": SOURCE_PATH, "bytes": len(_bytes(manifest, "retained-source")), "sha256": SOURCE_SHA256},
        "scope": _plain(manifest.record["scope"]), "document": observed, "carrier_inventory": carriers,
        "body_node_sequence": carriers, "document_shell": shell, "elements": _element_rows(tree),
        "exclusions": [{"source_path": row["source_path"], "tag": row["tag"], "reason": "presentation-only column declaration; no reading content"} for row in _element_rows(tree) if row["tag"] in EXCLUDED],
    })


def _convert(source_manifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    if source_manifest.record.get("ticket") != TICKET_ID or source_manifest.record.get("owner_route") != OWNER_ROUTE or source_manifest.record.get("work_id") != WORK_ID:
        raise ValueError("manifest is not the exact 37c-267 LIB-055 Rutherford route")
    raw = _bytes(source_manifest, "retained-source")
    if len(raw) != SOURCE_BYTES or _sha(raw) != SOURCE_SHA256:
        raise ValueError("retained Rutherford source bytes drifted")
    profile = _read_json(_bytes(source_manifest, "profile"), "feature profile")
    policy = _read_json(_bytes(source_manifest, "policy"), "validation policy")
    identity = _read_json(_bytes(source_manifest, "identity"), "work identity")
    if profile.get("work_id") != WORK_ID or policy.get("work_id") != WORK_ID or identity.get("work_id") != WORK_ID:
        raise ValueError("Rutherford route authority work IDs differ")
    tree = _parse(raw)
    produced = {
        "content.tei.xml": _build_tei(tree, raw),
        "source-accountability.json": _source_accountability(source_manifest, tree, profile),
        "provenance.json": _json({
            "contract": "ocd-source-to-tei-provenance-v1", "ticket": TICKET_ID, "owner_route": OWNER_ROUTE, "work_id": WORK_ID,
            "source_member": {"path": SOURCE_PATH, "bytes": len(raw), "sha256": SOURCE_SHA256},
            "source_manifest": {"path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(), "sha256": source_manifest.sha256},
            "converter": _plain(source_manifest.record["converter"]), "profile_sha256": _sha(_bytes(source_manifest, "profile")),
            "policy_sha256": _sha(_bytes(source_manifest, "policy")), "candidate_status": "nonaccepted", "human_acceptance": "not-assessed", "publication_status": "not-authorized"
        }),
        "unresolved.jsonl": b"".join(_json(row) for row in policy["unresolved_records"]),
        "README.source.md": _bytes(source_manifest, "source-readme"),
    }
    return produced


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
