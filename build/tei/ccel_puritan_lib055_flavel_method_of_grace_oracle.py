"""Independent retained-byte checker for LIB-055 / 37c-174."""

from __future__ import annotations

from collections import Counter
from io import BytesIO
import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


ORACLE_ID = "flavel-method-of-grace-lib055-independent-retained-byte-oracle"
ORACLE_VERSION = "1"
WORK_ID = "flavel-method-of-grace"
TICKET_ID = "37c-174"
OWNER_ROUTE = "LIB-055"
SOURCE_PATH = "raw/ccel/flavel/grace.xml"
SOURCE_SHA256 = "c044cad334d574b0cf52c936d6179a978c5c9a86bf7d8f51c4b3246a617f40cf"
SOURCE_BYTES = 1_796_532
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI_NS}

_SOURCE_ATTRIBUTES = {
    "DC": set(),
    "DC.Creator": {"scheme", "sub"},
    "DC.Date": {"sub"},
    "DC.Format": {"scheme"},
    "DC.Identifier": {"scheme"},
    "DC.Language": {"scheme"},
    "DC.Publisher": set(),
    "DC.Rights": set(),
    "DC.Source": {"scheme"},
    "DC.Subject": {"scheme"},
    "DC.Title": set(),
    "DC.Type": set(),
    "ThML": set(),
    "ThML.body": set(),
    "ThML.head": set(),
    "a": {"class", "href"},
    "authorID": set(),
    "bkgID": set(),
    "bookID": set(),
    "br": set(),
    "comments": set(),
    "description": set(),
    "div": {"class"},
    "div1": {"id", "next", "prev", "title"},
    "div2": {"id", "next", "prev", "title"},
    "electronicEdInfo": set(),
    "generalInfo": set(),
    "h1": {"id"},
    "h2": {"id"},
    "h3": {"id"},
    "h6": {"id"},
    "insertIndex": {"id", "type"},
    "p": {"class", "id"},
    "printSourceInfo": set(),
    "property": {"name", "value"},
    "pubHistory": set(),
    "published": set(),
    "publisherID": set(),
    "scripCom": {"id", "osisRef", "parsed", "passage", "type"},
    "scripRef": {"id", "osisRef", "parsed", "passage"},
    "selector": {"element"},
    "series": set(),
    "style": {"type"},
    "version": set(),
    "workID": set(),
}
_BODY_NAMES = {
    "div1": "div",
    "div2": "div",
    "div": "div",
    "h1": "head",
    "h2": "head",
    "h3": "head",
    "h6": "head",
    "p": "p",
    "a": "ref",
    "scripRef": "ref",
    "scripCom": "anchor",
    "insertIndex": "anchor",
}


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(value: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        record: dict[str, object] = {}
        for key, item in pairs:
            if key in record:
                raise ValueError(f"{label} has duplicate key {key!r}")
            record[key] = item
        return record

    try:
        result = json.loads(value.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(result, dict):
        raise ValueError(f"{label} must be a JSON object")
    return result


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _authority(source_manifest: SourceManifest, name: str) -> Mapping[str, object]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("source manifest authority inventory is invalid")
    found = [item for item in authorities if item.get("name") == name]
    if len(found) != 1:
        raise ValueError(f"source manifest must bind one {name!r} authority")
    return found[0]


def _authority_bytes(source_manifest: SourceManifest, name: str) -> bytes:
    return source_manifest.authority_path(name).read_bytes()


def _local_name(node: etree._Element) -> str:
    if not isinstance(node.tag, str):
        raise ValueError("source inventory encountered a non-element")
    return etree.QName(node).localname


def _read_source(raw: bytes) -> etree._ElementTree:
    parser = etree.XMLParser(
        load_dtd=False,
        no_network=True,
        resolve_entities=False,
        remove_comments=False,
        remove_pis=False,
        remove_blank_text=False,
        huge_tree=True,
    )
    document = etree.parse(BytesIO(raw), parser)
    if any(entry.level >= etree.ErrorLevels.ERROR for entry in parser.error_log):
        raise ValueError("independent source parser reported an XML error")
    return document


def _measure_source(document: etree._ElementTree) -> dict[str, object]:
    root = document.getroot()
    element_nodes = [node for node in root.iter() if isinstance(node.tag, str)]
    children = [node for node in root if isinstance(node.tag, str)]
    if _local_name(root) != "ThML" or [_local_name(node) for node in children] != [
        "ThML.head",
        "ThML.body",
    ]:
        raise ValueError("independent source reader found a changed ThML envelope")
    head, body = children
    head_nodes = [node for node in head.iter() if isinstance(node.tag, str)]
    body_nodes = [node for node in body.iter() if isinstance(node.tag, str)]
    names = Counter(_local_name(node) for node in element_nodes)
    if set(names) != set(_SOURCE_ATTRIBUTES):
        raise ValueError("independent source reader found an unknown element class")
    attribute_counts: dict[str, dict[str, int]] = {}
    for tag in sorted(names):
        counts = Counter(
            attribute
            for node in element_nodes
            if _local_name(node) == tag
            for attribute in node.attrib
        )
        observed_names = set(counts)
        if observed_names != _SOURCE_ATTRIBUTES[tag]:
            raise ValueError(f"independent source reader found changed attributes on {tag}")
        attribute_counts[tag] = dict(sorted(counts.items()))
    ids = [node.get("id") for node in element_nodes if node.get("id") is not None]
    id_set = set(ids)
    hrefs = [
        node.get("href", "")
        for node in body.iter()
        if isinstance(node.tag, str) and _local_name(node) == "a"
    ]
    fragments = [href.rsplit("#", 1)[-1] for href in hrefs if "#" in href]
    divisions = [
        node
        for node in body
        if isinstance(node.tag, str) and _local_name(node) == "div1"
    ]
    sermon_roots = [
        node for node in divisions if (node.get("title") or "").startswith("Sermon ")
    ]
    if (
        len(ids) != 5_991
        or len(id_set) != len(ids)
        or len(hrefs) != 2_625
        or len(fragments) != len(hrefs)
        or any("?" not in href.split("#", 1)[0] for href in hrefs)
        or any(fragment not in id_set for fragment in fragments)
        or len(divisions) != 39
        or len(sermon_roots) != 35
        or any(sum(1 for _ in node.iter("scripCom")) != 1 for node in sermon_roots)
    ):
        raise ValueError("independent source counts or link relationships do not reconcile")
    body_comments = [node for node in body if isinstance(node, etree._Comment)]
    comments = document.xpath("//comment()")
    instructions = document.xpath("//processing-instruction()")
    body_tags = Counter(_local_name(node) for node in body_nodes if node is not body)
    return {
        "root": _local_name(root),
        "ordered_root_elements": [_local_name(node) for node in children],
        "doctype": {
            "name": _local_name(root),
            "public_id": document.docinfo.public_id,
            "system_url": document.docinfo.system_url,
        },
        "element_count": len(element_nodes),
        "attribute_count": sum(len(node.attrib) for node in element_nodes),
        "head_element_count_including_wrapper": len(head_nodes),
        "body_element_count_including_wrapper": len(body_nodes),
        "element_text_node_count": sum(node.text is not None for node in element_nodes),
        "element_tail_node_count": sum(node.tail is not None for node in element_nodes),
        "comment_count": len(comments),
        "stylesheet_processing_instruction_count": sum(
            node.target == "xml-stylesheet" for node in instructions
        ),
        "body_direct_child_node_count": len(body),
        "body_direct_element_count": sum(isinstance(node.tag, str) for node in body),
        "body_direct_comment_count": len(body_comments),
        "source_id_count": len(ids),
        "unique_source_id_count": len(id_set),
        "source_tag_counts": dict(sorted(names.items())),
        "body_tag_counts_excluding_wrapper": dict(sorted(body_tags.items())),
        "body_top_level_div1_ids": [node.get("id") for node in divisions],
        "source_attribute_counts_by_element": attribute_counts,
        "link_count": len(hrefs),
        "query_and_fragment_link_count": sum(
            "?" in href.split("#", 1)[0] and "#" in href for href in hrefs
        ),
        "resolved_link_fragment_count": sum(fragment in id_set for fragment in fragments),
    }


def _shell_inventory(document: etree._ElementTree) -> list[dict[str, object]]:
    root = document.getroot()
    head = root.find("ThML.head")
    body = root.find("ThML.body")
    if head is None or body is None:
        raise ValueError("independent source shell reader found a missing wrapper")
    preceding = []
    sibling = root.getprevious()
    while sibling is not None:
        preceding.append(sibling)
        sibling = sibling.getprevious()
    preceding.reverse()
    output = []
    for node in document.xpath("//comment() | //processing-instruction()"):
        parent = node.getparent()
        if parent is None:
            location = "document-prolog" if node in preceding else "document-shell"
        elif parent is head or head in parent.iterancestors():
            location = "ThML.head"
        elif parent is body or body in parent.iterancestors():
            location = "ThML.body"
        else:
            location = "ThML"
        if isinstance(node, etree._Comment):
            item = {
                "kind": "comment",
                "location": location,
                "source_path": document.getpath(node),
                "text": node.text or "",
            }
        elif isinstance(node, etree._ProcessingInstruction):
            item = {
                "kind": "processing-instruction",
                "location": location,
                "source_path": document.getpath(node),
                "target": node.target,
                "text": node.text or "",
            }
        else:
            raise ValueError("independent source shell reader found an unsupported node")
        item["tail"] = node.tail or ""
        output.append(item)
    return output


def _body_target(tag: str, *, first_element: bool = False) -> str:
    if tag in {"h1", "h2", "h3", "h6"}:
        return "head" if first_element else "p"
    try:
        return _BODY_NAMES[tag]
    except KeyError as exc:
        raise ValueError(f"independent reader cannot account for source element {tag!r}") from exc


def _element_inventory(document: etree._ElementTree) -> list[dict[str, object]]:
    root = document.getroot()
    head = root.find("ThML.head")
    body = root.find("ThML.body")
    if head is None or body is None:
        raise ValueError("independent source inventory found a missing wrapper")
    head_paths = {
        document.getpath(node) for node in head.iter() if isinstance(node.tag, str)
    }
    body_paths = {
        document.getpath(node) for node in body.iter() if isinstance(node.tag, str)
    }
    result = []
    for order, node in enumerate(
        item for item in root.iter() if isinstance(item.tag, str)
    ):
        path = document.getpath(node)
        tag = _local_name(node)
        parent = node.getparent()
        first_element = parent is not None and next(
            (child for child in parent if isinstance(child.tag, str)), None
        ) is node
        if node is root:
            disposition, target = "document-root-mapped-to-tei", "TEI"
        elif node is head:
            disposition, target = "header-wrapper-mapped-to-tei", "teiHeader"
        elif path in head_paths and tag == "style":
            disposition, target = "source-formatting-not-reproduced", None
        elif path in head_paths:
            disposition, target = "header-field-mapped-or-explicitly-disposed", None
        elif node is body:
            disposition, target = "body-wrapper-mapped-to-tei", "body"
        elif path in body_paths:
            disposition, target = "body-element-mapped-to-tei", _body_target(
                tag, first_element=first_element
            )
        else:
            raise ValueError(f"independent source reader found an out-of-envelope node {path}")
        direct = node.text or ""
        tail = node.tail or ""
        result.append(
            {
                "order": order,
                "source_path": path,
                "parent_source_path": (
                    document.getpath(node.getparent())
                    if node.getparent() is not None
                    else None
                ),
                "tag": tag,
                "attributes": dict(sorted(node.attrib.items())),
                "direct_text_present": node.text is not None,
                "direct_text_chars": len(direct),
                "direct_text_sha256": _sha(direct.encode("utf-8")),
                "tail_present": node.tail is not None,
                "tail_text_chars": len(tail),
                "tail_text_sha256": _sha(tail.encode("utf-8")),
                "disposition": disposition,
                "tei_element": target,
            }
        )
    return result


def _accountability(
    source_manifest: SourceManifest,
    document: etree._ElementTree,
    source_bytes: bytes,
    profile_record: Mapping[str, object],
    policy_bytes: bytes,
    profile_bytes: bytes,
) -> bytes:
    root = document.getroot()
    doc_profile = profile_record.get("document")
    observed = _measure_source(document)
    for inventory_field in (
        "source_tag_counts",
        "body_tag_counts_excluding_wrapper",
        "body_top_level_div1_ids",
    ):
        observed.pop(inventory_field)
    if not isinstance(doc_profile, Mapping) or _plain(doc_profile) != observed:
        raise ValueError("independent source inventory differs from the bound feature profile")
    carriers = [
        {
            "order": index,
            "source_path": document.getpath(node),
            "id": node.get("id"),
            "title": node.get("title"),
            "prev": node.get("prev"),
            "next": node.get("next"),
        }
        for index, node in enumerate(
            (
                child
                for child in root.find("ThML.body")
                if isinstance(child.tag, str) and _local_name(child) == "div1"
            ),
            start=1,
        )
    ]
    record = {
        "contract": "ocd-source-accountability-v1",
        "ticket": TICKET_ID,
        "owner_route": OWNER_ROUTE,
        "work_id": WORK_ID,
        "source_member": {
            "path": SOURCE_PATH,
            "bytes": len(source_bytes),
            "sha256": _sha(source_bytes),
        },
        "scope": _plain(source_manifest.record["scope"]),
        "source_envelope": {
            "xml_declaration": {
                "version": document.docinfo.xml_version,
                "encoding": document.docinfo.encoding,
                "standalone": document.docinfo.standalone,
            },
            "doctype": {
                "name": _local_name(root),
                "public_id": document.docinfo.public_id,
                "system_url": document.docinfo.system_url,
                "declaration_sha256": _sha(document.docinfo.doctype.encode("utf-8")),
            },
            "shell_nodes": _shell_inventory(document),
            "profile": dict(doc_profile),
        },
        "body_carriers": carriers,
        "elements": _element_inventory(document),
        "mapping_policy_sha256": _sha(policy_bytes),
        "source_feature_profile_sha256": _sha(profile_bytes),
    }
    return _canonical(record)


def _source_attributes(node: etree._Element, target_name: str) -> dict[str, str]:
    tag = _local_name(node)
    actual = set(node.attrib)
    allowed = _SOURCE_ATTRIBUTES.get(tag)
    required = {
        "div1": {"id", "next", "prev", "title"},
        "div2": {"id", "next", "prev", "title"},
        "div": {"class"},
        "h1": {"id"},
        "h2": {"id"},
        "h3": {"id"},
        "h6": {"id"},
        "p": set(),
        "a": {"class", "href"},
        "scripRef": {"id", "osisRef", "parsed", "passage"},
        "scripCom": {"id", "type"},
        "insertIndex": {"id", "type"},
    }.get(tag)
    if (
        allowed is None
        or required is None
        or not required <= actual
        or not actual <= allowed
        or (tag == "p" and actual not in ({"id"}, {"class"}))
    ):
        raise ValueError(f"independent reader found unsupported source attributes on {tag!r}")
    attrs: dict[str, str] = {}
    if "id" in node.attrib:
        attrs[f"{{{XML_NS}}}id"] = node.get("id", "")
    if tag in {"div1", "div2"}:
        attrs["type"] = f"source-{tag}"
        if "title" in node.attrib:
            attrs["n"] = node.get("title", "")
        for key in ("prev", "next"):
            if key in node.attrib:
                attrs[key] = node.get(key, "")
    elif tag == "div" and "class" in node.attrib:
        attrs["type"] = node.get("class", "")
    elif tag in {"h1", "h2", "h3", "h6"}:
        if target_name == "head":
            attrs["type"] = f"source-{tag}"
        elif target_name == "p":
            attrs["rend"] = f"source-heading-{tag}"
        else:
            raise ValueError(f"independent reader cannot map heading {tag!r} to {target_name!r}")
    elif tag == "p":
        if "class" in node.attrib:
            attrs["rend"] = node.get("class", "")
    elif tag == "a":
        if "class" in node.attrib:
            attrs["type"] = node.get("class", "")
        attrs["target"] = node.get("href", "")
    elif tag == "scripRef":
        attrs["type"] = "scripture"
        if "osisRef" in node.attrib:
            attrs["target"] = node.get("osisRef", "")
        if "passage" in node.attrib:
            attrs["n"] = node.get("passage", "")
    elif tag == "scripCom":
        attrs["type"] = "scripture-commentary-marker"
        if "type" in node.attrib:
            attrs["subtype"] = node.get("type", "")
        if "osisRef" in node.attrib:
            attrs["corresp"] = node.get("osisRef", "")
        if "passage" in node.attrib:
            attrs["n"] = node.get("passage", "")
    elif tag == "insertIndex":
        attrs["type"] = "index-insertion"
        if "type" in node.attrib:
            attrs["subtype"] = node.get("type", "")
    else:
        raise ValueError(f"independent reader has no mapping for {tag!r} to {target_name!r}")
    return attrs


def _copy_body_independently(source: etree._Element, target: etree._Element) -> None:
    target.text = source.text
    first_element = next(
        (child for child in source if isinstance(child.tag, str)), None
    )
    for child in source:
        if isinstance(child, etree._Comment):
            mapped = etree.Comment(child.text or "")
        elif isinstance(child.tag, str):
            mapped_name = _body_target(
                _local_name(child), first_element=child is first_element
            )
            mapped = etree.Element(f"{{{TEI_NS}}}{mapped_name}")
            for key, value in _source_attributes(child, mapped_name).items():
                mapped.set(key, value)
            _copy_body_independently(child, mapped)
        else:
            raise ValueError("independent reader found an unsupported body node")
        mapped.tail = child.tail
        target.append(mapped)


def _required_one(parent: etree._Element, path: str) -> etree._Element:
    matches = parent.findall(path)
    if len(matches) != 1:
        raise ValueError(f"source metadata path {path!r} must occur exactly once")
    return matches[0]


def _expected_tei(document: etree._ElementTree, source_bytes: bytes) -> etree._Element:
    root = document.getroot()
    head = root.find("ThML.head")
    source_body = root.find("ThML.body")
    if head is None or source_body is None:
        raise ValueError("independent metadata reader found a missing source wrapper")
    title = _required_one(head, ".//DC.Title")
    creator_matches = [
        item
        for item in head.findall(".//DC.Creator")
        if item.get("sub") == "Author" and item.get("scheme") is None
    ]
    file_as_matches = [
        item for item in head.findall(".//DC.Creator") if item.get("scheme") == "file-as"
    ]
    publisher = _required_one(head, ".//DC.Publisher")
    created = [item for item in head.findall(".//DC.Date") if item.get("sub") == "Created"]
    identifier = _required_one(head, ".//DC.Identifier")
    language = _required_one(head, ".//DC.Language")
    description = _required_one(head, ".//description")
    if len(creator_matches) != 1 or len(file_as_matches) != 1 or len(created) != 1:
        raise ValueError("independent metadata reader found ambiguous creator or date fields")
    creator = creator_matches[0]
    file_as = file_as_matches[0]
    date = created[0]

    tei = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    header = etree.SubElement(tei, f"{{{TEI_NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}title", type="source-record-title").text = title.text or ""
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}author").text = creator.text or ""
    publication = etree.SubElement(file_desc, f"{{{TEI_NS}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI_NS}}}p").text = (
        "Nonaccepted technical candidate; publication is not authorized."
    )
    notes = etree.SubElement(file_desc, f"{{{TEI_NS}}}notesStmt")
    etree.SubElement(notes, f"{{{TEI_NS}}}note", type="source-metadata-status").text = (
        "Source-record metadata is transcribed as observation. It does not establish a print edition, original-publication date, part map, or physical witness."
    )
    etree.SubElement(notes, f"{{{TEI_NS}}}note", type="source-file-as").text = file_as.text or ""
    description_note = etree.SubElement(notes, f"{{{TEI_NS}}}note", type="source-record-description")
    description_note.text = description.text
    for line_break in description:
        if not isinstance(line_break.tag, str) or _local_name(line_break) != "br":
            raise ValueError("retained source description has an unsupported inline node")
        newline = etree.Element(f"{{{TEI_NS}}}lb")
        newline.tail = line_break.tail
        description_note.append(newline)
    for node in head.findall(".//DC.Type"):
        etree.SubElement(notes, f"{{{TEI_NS}}}note", type="source-record-field", subtype="DC.Type").text = node.text or ""
    for node in head.findall(".//DC.Format"):
        etree.SubElement(notes, f"{{{TEI_NS}}}note", type="source-record-field", subtype="DC.Format", n=node.get("scheme", "")).text = node.text or ""
    for node in head.findall(".//DC.Date"):
        etree.SubElement(notes, f"{{{TEI_NS}}}note", type="source-record-field", subtype="DC.Date", n=node.get("sub", "")).text = node.text or ""
    for node in head.findall(".//DC.Source"):
        etree.SubElement(notes, f"{{{TEI_NS}}}note", type="source-record-field", subtype="DC.Source", n=node.get("scheme", "")).text = node.text or ""
    rights = _required_one(head, ".//DC.Rights")
    if rights.text not in (None, ""):
        raise ValueError("source rights field is no longer empty; review is required")
    etree.SubElement(notes, f"{{{TEI_NS}}}note", type="source-rights-field").text = ""
    etree.SubElement(notes, f"{{{TEI_NS}}}note", type="rights-clearance-status").text = (
        "The source DC.Rights field is empty. Project permission to parse is not rights clearance for publication."
    )
    source_desc = etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{TEI_NS}}}bibl", type="retained-source-record")
    etree.SubElement(bibl, f"{{{TEI_NS}}}title", type="source-record-title").text = title.text or ""
    etree.SubElement(bibl, f"{{{TEI_NS}}}author").text = creator.text or ""
    etree.SubElement(bibl, f"{{{TEI_NS}}}name", type="source-file-as").text = file_as.text or ""
    etree.SubElement(bibl, f"{{{TEI_NS}}}publisher").text = publisher.text or ""
    etree.SubElement(bibl, f"{{{TEI_NS}}}idno", type="source-record-uri").text = identifier.text or ""
    etree.SubElement(bibl, f"{{{TEI_NS}}}idno", type="ocd-work-id").text = WORK_ID
    etree.SubElement(bibl, f"{{{TEI_NS}}}date", type="source-record-created", n=date.get("sub", "")).text = date.text or ""
    for tag, value in (
        ("publisherID", "ccel"),
        ("authorID", "flavel"),
        ("bookID", "grace"),
        ("workID", "grace"),
        ("bkgID", "method_of_grace_in_the_gospel_redemption_(flavel)"),
    ):
        node = _required_one(head, f".//{tag}")
        if (node.text or "") != value:
            raise ValueError(f"retained source identifier {tag!r} changed")
        etree.SubElement(bibl, f"{{{TEI_NS}}}idno", type=f"ccel-{tag}").text = value
    source_note = etree.SubElement(bibl, f"{{{TEI_NS}}}note", type="retained-member-binding")
    source_note.text = (
        f"Complete retained XML document envelope at {SOURCE_PATH}; {len(source_bytes):,} bytes; "
        f"SHA-256 {_sha(source_bytes)}. This source-member scope does not establish the complete catalog-work boundary."
    )
    encoding = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
    project = etree.SubElement(encoding, f"{{{TEI_NS}}}projectDesc")
    etree.SubElement(project, f"{{{TEI_NS}}}p").text = (
        "This nonaccepted TEI maps the complete retained ThML body in source order. "
        "CCEL CSS/XCSS is accounted for but not reproduced."
    )
    profile = etree.SubElement(header, f"{{{TEI_NS}}}profileDesc")
    usage = etree.SubElement(profile, f"{{{TEI_NS}}}langUsage")
    etree.SubElement(usage, f"{{{TEI_NS}}}language", ident=language.text or "").text = language.text or ""
    classification = etree.SubElement(profile, f"{{{TEI_NS}}}textClass")
    keywords = etree.SubElement(classification, f"{{{TEI_NS}}}keywords", scheme="CCEL-DC.Subject")
    for node in head.findall(".//DC.Subject"):
        etree.SubElement(keywords, f"{{{TEI_NS}}}term", type=node.get("scheme", "")).text = node.text or ""
    text = etree.SubElement(tei, f"{{{TEI_NS}}}text", {f"{{{XML_NS}}}lang": language.text or ""})
    target_body = etree.SubElement(text, f"{{{TEI_NS}}}body")
    _copy_body_independently(source_body, target_body)
    return tei


def _assert_same_tree(actual: etree._Element, expected: etree._Element, path: str) -> None:
    if isinstance(actual, etree._Comment) or isinstance(expected, etree._Comment):
        if not isinstance(actual, etree._Comment) or not isinstance(expected, etree._Comment):
            raise ValueError(f"TEI comment/element mismatch at {path}")
    if actual.tag != expected.tag:
        raise ValueError(f"TEI element name mismatch at {path}")
    if dict(actual.attrib) != dict(expected.attrib):
        raise ValueError(f"TEI attribute mismatch at {path}")
    if (actual.text or "") != (expected.text or "") or (actual.tail or "") != (expected.tail or ""):
        raise ValueError(f"TEI text or mixed-content tail mismatch at {path}")
    actual_children = list(actual)
    expected_children = list(expected)
    if len(actual_children) != len(expected_children):
        raise ValueError(f"TEI child count mismatch at {path}")
    for index, (actual_child, expected_child) in enumerate(
        zip(actual_children, expected_children, strict=True),
        start=1,
    ):
        _assert_same_tree(actual_child, expected_child, f"{path}/{index}")


def _expected_unresolved(identity: Mapping[str, object]) -> bytes:
    unresolved = identity.get("unresolved")
    if not isinstance(unresolved, Mapping) or not unresolved:
        raise ValueError("source work identity has no unresolved-question ledger")
    records = []
    for name, explanation in unresolved.items():
        if not isinstance(explanation, str) or not explanation:
            raise ValueError(f"unresolved identity question {name!r} has no explanation")
        records.append(
            _canonical(
                {
                    "claim": name,
                    "status": "unresolved",
                    "work_id": WORK_ID,
                    "statement": explanation,
                }
            )
        )
    return b"".join(records)


def _expected_provenance(
    source_manifest: SourceManifest,
    source_bytes: bytes,
    profile_bytes: bytes,
    policy_bytes: bytes,
) -> bytes:
    scope = source_manifest.record["scope"]
    return _canonical(
        {
            "contract": "ocd-source-to-tei-provenance-v1",
            "ticket": TICKET_ID,
            "owner_route": OWNER_ROUTE,
            "work_id": WORK_ID,
            "source_member": {
                "path": SOURCE_PATH,
                "bytes": len(source_bytes),
                "sha256": _sha(source_bytes),
            },
            "source_manifest": {
                "path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(),
                "sha256": source_manifest.sha256,
            },
            "converter": _plain(source_manifest.record["converter"]),
            "feature_profile_sha256": _sha(profile_bytes),
            "policy_sha256": _sha(policy_bytes),
            "scope_selector": scope["selector"],
            "candidate_status": "nonaccepted",
            "human_acceptance": "not-assessed",
            "publication_status": "not-authorized",
            "notes": "Exact source-member reconstruction; no edition, part, print-witness, or rights-clearance claim is adopted.",
        }
    )


def _import_closure_sha256(repository_root: Path) -> str:
    logical_files = (
        "build/tei/ccel_puritan_lib055_flavel_method_of_grace_oracle.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/verifier.py",
    )
    file_records = [
        {"path": name, "sha256": _sha((repository_root / name).read_bytes())}
        for name in logical_files
    ]
    runtime = {
        "lxml": list(etree.LXML_VERSION),
        "libxml2_compiled": list(etree.LIBXML_COMPILED_VERSION),
        "libxml2_runtime": list(etree.LIBXML_VERSION),
        "jsonschema": importlib.metadata.version("jsonschema"),
    }
    return _sha(_canonical({"contract": "ocd-validator-import-closure-v1", "files": file_records, "runtime": runtime}))


def validate(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
) -> Mapping[str, object]:
    """Independently reconcile source bytes, accounting, TEI, and schema."""

    source_manifest.verify()
    candidate.verify_integrity()
    manifest = source_manifest.record
    expected_manifest = {
        "source_id": "flavel-method-of-grace-lib055-retained-xml",
        "ticket": TICKET_ID,
        "owner_route": OWNER_ROUTE,
        "work_id": WORK_ID,
    }
    if any(manifest.get(key) != value for key, value in expected_manifest.items()):
        raise ValueError("oracle received a different work or owner route")
    expected_roles = {
        "source-member": "primary-source",
        "work-identity": "work-config",
        "feature-profile": "complete-source-feature-profile",
        "policy": "independent-validation-policy",
        "source-readme": "source-attribution-readme",
        "ccel-permission": "exact-source-permission",
        "tei-schema": "tei-validation-schema",
        "package-schema": "candidate-package-schema",
    }
    authorities = manifest.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("oracle found an invalid manifest authority inventory")
    if {item.get("name"): item.get("role") for item in authorities} != expected_roles:
        raise ValueError("oracle found missing, extra, or misclassified source authorities")
    source_binding = _authority(source_manifest, "source-member")
    if (
        source_binding.get("path") != SOURCE_PATH
        or source_binding.get("bytes") != SOURCE_BYTES
        or source_binding.get("sha256") != SOURCE_SHA256
    ):
        raise ValueError("oracle source binding is not the exact retained Flavel member")
    source_bytes = _authority_bytes(source_manifest, "source-member")
    if len(source_bytes) != SOURCE_BYTES or _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("oracle retained source bytes do not match the current source identity")
    profile_bytes = _authority_bytes(source_manifest, "feature-profile")
    policy_bytes = _authority_bytes(source_manifest, "policy")
    identity_bytes = _authority_bytes(source_manifest, "work-identity")
    profile = _strict_json(profile_bytes, "source feature profile")
    policy = _strict_json(policy_bytes, "validation policy")
    identity = _strict_json(identity_bytes, "work identity")
    if (
        profile.get("work_id") != WORK_ID
        or policy.get("work_id") != WORK_ID
        or identity.get("work_id") != WORK_ID
        or identity.get("status") != "observed-only"
    ):
        raise ValueError("oracle found a work-local authority misbinding")
    profile_member = profile.get("source_member")
    if not isinstance(profile_member, Mapping) or any(
        profile_member.get(field) != expected
        for field, expected in (("path", SOURCE_PATH), ("bytes", SOURCE_BYTES), ("sha256", SOURCE_SHA256))
    ):
        raise ValueError("oracle feature profile is not bound to the retained member")
    policy_scope = policy.get("scope")
    if not isinstance(policy_scope, Mapping) or (
        tuple(policy_scope.get("member_order", ())) != (SOURCE_PATH,)
        or policy_scope.get("selector") != "ThML[1] (complete retained document envelope)"
        or tuple(policy_scope.get("exclusions", ()))
    ):
        raise ValueError("oracle policy does not cover the exact complete member")
    attribute_policy = policy.get("attribute_policy")
    expected_names = {
        tag: sorted(names) for tag, names in _SOURCE_ATTRIBUTES.items() if names
    }
    if not isinstance(attribute_policy, Mapping) or (
        attribute_policy.get("names_by_source_element") != expected_names
    ):
        raise ValueError("oracle policy does not declare the observed source attributes")
    permission = _authority_bytes(source_manifest, "ccel-permission").decode("utf-8")
    readme = _authority_bytes(source_manifest, "source-readme")
    if (
        "parsing ThML/XML files for text is explicitly permitted" not in permission
        or "do not sell CCEL files or derivatives of their formatting" not in permission
        or b"sourced via CCEL.org" not in readme
    ):
        raise ValueError("oracle permission/attribution evidence is incomplete")

    source_document = _read_source(source_bytes)
    measured = _measure_source(source_document)
    measured_document = dict(measured)
    for inventory_field in (
        "source_tag_counts",
        "body_tag_counts_excluding_wrapper",
        "body_top_level_div1_ids",
    ):
        measured_document.pop(inventory_field)
    if (
        profile.get("document") != measured_document
        or profile.get("source_tag_counts") != measured["source_tag_counts"]
        or profile.get("body_tag_counts_excluding_wrapper") != measured["body_tag_counts_excluding_wrapper"]
        or profile.get("body_top_level_div1_ids") != measured["body_top_level_div1_ids"]
    ):
        raise ValueError("oracle source census differs from the pinned complete-source profile")
    accountability = _accountability(
        source_manifest,
        source_document,
        source_bytes,
        profile,
        policy_bytes,
        profile_bytes,
    )
    if candidate.member_bytes("source-accountability.json") != accountability:
        raise ValueError("candidate source-accountability inventory differs from independent enumeration")
    if candidate.member_bytes("README.source.md") != readme:
        raise ValueError("candidate source README differs from the bound attribution authority")
    if candidate.member_bytes("provenance.json") != _expected_provenance(
        source_manifest, source_bytes, profile_bytes, policy_bytes
    ):
        raise ValueError("candidate provenance does not bind the exact source and policy")
    if candidate.member_bytes("unresolved.jsonl") != _expected_unresolved(identity):
        raise ValueError("candidate does not preserve all unresolved identity and rights questions")
    if set(candidate.member_names) != {
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }:
        raise ValueError("candidate member inventory is not complete")
    package_manifest = _plain(candidate.manifest)
    if not isinstance(package_manifest, dict) or (
        package_manifest.get("status") != "nonaccepted"
        or package_manifest.get("source_id") != manifest.get("source_id")
        or package_manifest.get("source_manifest")
        != {
            "path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(),
            "sha256": source_manifest.sha256,
        }
        or package_manifest.get("converter") != _plain(manifest.get("converter"))
        or package_manifest.get("package_schema") != _plain(manifest.get("package_schema"))
    ):
        raise ValueError("candidate package manifest is not bound to this work route")

    candidate_bytes = candidate.member_bytes("content.tei.xml")
    parser = etree.XMLParser(
        load_dtd=False,
        no_network=True,
        resolve_entities=False,
        remove_comments=False,
        remove_pis=False,
        remove_blank_text=False,
        huge_tree=True,
    )
    try:
        candidate_tree = etree.parse(BytesIO(candidate_bytes), parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("candidate TEI is malformed or contains duplicate XML IDs") from exc
    if (
        candidate_tree.docinfo.doctype
        or candidate_tree.getroot().getprevious() is not None
        or candidate_tree.getroot().getnext() is not None
        or candidate_tree.xpath("//processing-instruction()")
    ):
        raise ValueError("candidate copied a source DTD, processing instruction, or document-shell node")
    expected_tree = _expected_tei(source_document, source_bytes)
    _assert_same_tree(candidate_tree.getroot(), expected_tree, "/TEI")
    schema_path = source_manifest.authority_path("tei-schema")
    schema_parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)
    schema = etree.XMLSchema(etree.parse(str(schema_path), schema_parser))
    if not schema.validate(candidate_tree):
        last = schema.error_log.last_error
        raise ValueError(f"candidate TEI fails the bound TEI schema: {last}")

    validator = manifest.get("validator")
    if not isinstance(validator, Mapping):
        raise ValueError("source manifest validator binding is invalid")
    facts = MechanicalFacts(
        validator_implementation_sha256=str(validator.get("implementation_sha256", "")),
        validator_import_closure_sha256=_import_closure_sha256(source_manifest.repository_root),
        source_sha256=str(source_binding.get("sha256", "")),
        profile_sha256=str(_authority(source_manifest, "feature-profile").get("sha256", "")),
        package_schema_sha256=str(_authority(source_manifest, "package-schema").get("sha256", "")),
        xsd_sha256=str(_authority(source_manifest, "tei-schema").get("sha256", "")),
        policy_sha256=str(_authority(source_manifest, "policy").get("sha256", "")),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


validate.oracle_id = ORACLE_ID
validate.oracle_version = ORACLE_VERSION
