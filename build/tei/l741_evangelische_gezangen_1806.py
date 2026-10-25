"""Convert the retained DBNL TEI.2 witness for L741 to one direct TEI P5 root."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import SourceManifest

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XMLID = f"{{{XML_NS}}}id"
XMLBASE = f"{{{XML_NS}}}base"
SCORE_IMAGE_BASE = "https://www.dbnl.org/tekst/_eva005evan01_01/"
SOURCE_SHA256 = "d8132943dd20b1053d1d77bda57cab2b69c9dc567e38ea4450baab914925abb9"
SOURCE_BYTES = 574306
SOURCE_LOGICAL = "raw/dbnl/evangelische-gezangen-1806/evangelische-gezangen-1806.xml"
SOURCE_ID = "dbnl-eva005evan01-1806"
SOURCE_WITNESS_ID = "dbnl-eva005evan01-1806-witness"
WORK_ID = "evangelische-gezangen-1806"
TEXTUAL_FORM_ID = "evangelische-gezangen-1806-dbnl-retained"
EDITION_ID = "evangelische-gezangen-1806-dbnl-electronic"
ACQUISITION_ID = "evangelische-gezangen-1806-dbnl-acquired"
WORK_CATALOG_LINK = {
    "contract": "ocd-workcatalog-link-v1",
    "work_id": WORK_ID,
    "textual_form_id": TEXTUAL_FORM_ID,
    "edition_id": EDITION_ID,
    "acquisition_id": ACQUISITION_ID,
    "work_record": {
        "path": "library/works/evangelische-gezangen-1806/work.json",
        "snapshot_path": "sources/manifest-acquisitions/l741-evangelische-gezangen-1806/work-catalog-work-record.json",
        "sha256": "a2cf66e3e7c5c7916669fd6c098f21d448a63029de311f55ff580b604d2d8e13",
    },
    "state_record": {
        "path": "library/works/evangelische-gezangen-1806/state.json",
        "snapshot_path": "sources/manifest-acquisitions/l741-evangelische-gezangen-1806/work-catalog-state-record.json",
        "sha256": "4e07ee042dbea86f90f3644e04e88f8a2e887706b94a4874c52a15ae1aca9be6",
    },
    "acquisition_record": {
        "path": "library/works/evangelische-gezangen-1806/forms/evangelische-gezangen-1806-dbnl-retained/editions/evangelische-gezangen-1806-dbnl-electronic/acquisitions/evangelische-gezangen-1806-dbnl-acquired.json",
        "snapshot_path": "sources/manifest-acquisitions/l741-evangelische-gezangen-1806/work-catalog-acquisition-record.json",
        "sha256": "b694e97b4560799b8e8027e5d53ed7dee9341e01319f20ac5f3a72f90a634e29",
    },
}
TITLE = "Evangelische Gezangen, om nevens het Boek der Psalmen bij den openbaren godsdienst in de Nederlandsche Hervormde Gemeenten gebruikt te worden"
CONVERTER_ID = "ocd-l741-dbnl-evangelische-gezangen-1806-to-direct-tei"
CONVERTER_VERSION = "3"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _verify_work_catalog_link(source_manifest: SourceManifest, profile: dict[str, Any]) -> dict[str, Any]:
    expected_ids = {
        "work_id": WORK_ID,
        "textual_form_id": TEXTUAL_FORM_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
    }
    if any(source_manifest.record.get(key) != value for key, value in expected_ids.items()):
        raise ValueError("L741 source manifest does not bind the existing WorkCatalog identity chain")
    if any(profile.get(key) != value for key, value in expected_ids.items()):
        raise ValueError("L741 profile does not bind the existing WorkCatalog identity chain")
    link = profile.get("work_catalog_link")
    if link != WORK_CATALOG_LINK:
        raise ValueError("L741 profile WorkCatalog link differs from the pinned sidecar records")

    work_raw = source_manifest.authority_path("registered-work-identity").read_bytes()
    state_raw = source_manifest.authority_path("registered-work-state").read_bytes()
    acquisition_raw = source_manifest.authority_path("registered-work-acquisition").read_bytes()
    for raw, field in (
        (work_raw, "work_record"),
        (state_raw, "state_record"),
        (acquisition_raw, "acquisition_record"),
    ):
        if _sha(raw) != link[field]["sha256"]:
            raise ValueError(f"L741 WorkCatalog {field} snapshot digest differs")

    work = json.loads(work_raw)
    state = json.loads(state_raw)
    acquisition = json.loads(acquisition_raw)
    forms = [item for item in work.get("textual_forms", []) if item.get("textual_form_id") == TEXTUAL_FORM_ID]
    editions = [item for item in forms[0].get("editions", []) if item.get("edition_id") == EDITION_ID] if len(forms) == 1 else []
    if work.get("work_id") != WORK_ID or work.get("title") != TITLE or len(forms) != 1 or len(editions) != 1 or ACQUISITION_ID not in editions[0].get("acquisition_ids", []):
        raise ValueError("L741 WorkCatalog work sidecar does not identify the retained title and nested edition")
    if state.get("work_id") != WORK_ID:
        raise ValueError("L741 WorkCatalog state sidecar identifies a different work")
    current_targets = [
        target for target in state.get("targets", [])
        if target.get("target_id") in (EDITION_ID, ACQUISITION_ID)
    ]
    target_stages = {target.get("target_id"): target.get("stage") for target in current_targets}
    if target_stages != {EDITION_ID: "acquired", ACQUISITION_ID: "acquired"}:
        raise ValueError("L741 WorkCatalog lifecycle sidecar no longer records only the acquired edition and acquisition")
    if acquisition.get("acquisition_id") != ACQUISITION_ID or acquisition.get("edition_id") != EDITION_ID:
        raise ValueError("L741 WorkCatalog acquisition sidecar identifies a different acquisition")
    if acquisition.get("source_path") != SOURCE_LOGICAL or acquisition.get("source_sha256") != SOURCE_SHA256 or acquisition.get("source_bytes") != SOURCE_BYTES:
        raise ValueError("L741 WorkCatalog acquisition sidecar does not bind the exact retained XML")
    return dict(link)


def _tag(name: str) -> str:
    return f"{{{TEI_NS}}}{name}"


def _text(node: etree._Element) -> str:
    return (node.text or "") + "".join(_text(child) + (child.tail or "") for child in node)


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _profile(source_manifest: SourceManifest) -> dict[str, Any]:
    return json.loads(source_manifest.authority_path("complete-source-feature-profile").read_bytes())


def _policy(source_manifest: SourceManifest) -> dict[str, Any]:
    return json.loads(source_manifest.authority_path("independent-validation-policy").read_bytes())


def _parse_source(source_manifest: SourceManifest, profile: dict[str, Any]) -> tuple[bytes, etree._Element, str, list[dict[str, Any]]]:
    path = source_manifest.authority_path("retained-dbnl-tei2-xml")
    raw = path.read_bytes()
    if len(raw) != SOURCE_BYTES or _sha(raw) != SOURCE_SHA256 or raw != resolve_repo_path(source_manifest.repository_root, SOURCE_LOGICAL).read_bytes():
        raise ValueError("retained L741 DBNL TEI.2 bytes differ from the assigned exact source")
    source_manifest.verify()
    _verify_work_catalog_link(source_manifest, profile)
    members = profile["retained_bundle_members"]
    folder = resolve_repo_path(source_manifest.repository_root, profile["retained_bundle_root"]).resolve(strict=True)
    actual = {member.name: member for member in folder.iterdir() if member.is_file()}
    expected = {item["name"]: item for item in members}
    if set(actual) != set(expected) or len(members) != profile.get("retained_bundle_member_count") or len(members) != 5:
        raise ValueError("current five-file L741 retained source bundle differs from the source profile")
    for name, item in expected.items():
        content = actual[name].read_bytes()
        if len(content) != item["bytes"] or _sha(content) != item["sha256"]:
            raise ValueError(f"retained L741 bundle member differs: {name}")
    receipt = json.loads(source_manifest.authority_path("retained-dbNL-acquisition-receipt").read_bytes())
    if receipt.get("manifest_row") != "L741" or receipt.get("source_id") != "DBNL-_eva005evan01" or receipt.get("member", {}).get("sha256") != SOURCE_SHA256:
        raise ValueError("L741 acquisition receipt does not identify the exact retained source")
    asset_receipt = json.loads(source_manifest.authority_path("l741-score-image-acquisition-receipt").read_bytes())
    if asset_receipt.get("manifest_row") != "L741" or asset_receipt.get("source_id") != "DBNL-_eva005evan01" or asset_receipt.get("retained_primary_source", {}).get("sha256") != SOURCE_SHA256 or asset_receipt.get("source_target_base") != SCORE_IMAGE_BASE or asset_receipt.get("member_count") != 68:
        raise ValueError("L741 score-image receipt does not bind the exact DBNL source and targets")
    receipt_assets = {item["name"]: item for item in asset_receipt["members"]}
    authorities = {item["name"]: item for item in source_manifest.record["authorities"]}
    profile_pointers = profile["source_body"]["external_score_image_pointers"]
    if profile["source_body"].get("score_image_target_base") != SCORE_IMAGE_BASE or len(profile_pointers) != 68:
        raise ValueError("L741 score-image target profile is incomplete")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False, remove_pis=False)
    tree = etree.ElementTree(etree.fromstring(raw, parser, base_url=str(path)))
    root = tree.getroot()
    if root.tag != "TEI.2" or tree.docinfo.doctype != profile["document_envelope"]["doctype"]:
        raise ValueError("retained source document envelope is not the profiled DBNL TEI.2 witness")
    title_nodes = root.xpath("/TEI.2/teiHeader/fileDesc/titleStmt/title[@type='main']")
    editions = root.xpath("/TEI.2/teiHeader/fileDesc/editionStmt/edition")
    code = root.xpath("/TEI.2/teiHeader/fileDesc/publicationStmt/idno[@type='titelcode']")
    if len(title_nodes) != 1 or _text(title_nodes[0]).strip() != TITLE or len(editions) != 1 or "eerste druk uit 1806" not in " ".join(_text(editions[0]).split()) or len(code) != 1 or _text(code[0]).strip() != "_eva005evan01_01":
        raise ValueError("retained source title, first-edition statement, or DBNL title code differs")
    source_body = root.find("text/body")
    if source_body is None:
        raise ValueError("retained L741 source has no text/body")
    header_start = raw.find(b"<teiHeader>")
    header_end_marker = b"</teiHeader>"
    header_end = raw.find(header_end_marker, header_start)
    if header_start < 0 or header_end < 0 or raw.find(b"<teiHeader>", header_start + 1) >= 0:
        raise ValueError("retained L741 source does not have one exact teiHeader byte slice")
    header_xml = raw[header_start : header_end + len(header_end_marker)].decode("utf-8", errors="strict")
    source_pointers = [
        {"source_order": index, "to": node.get("to"), "source_element_path": tree.getpath(node)}
        for index, node in enumerate(root.xpath("/TEI.2/text/body//xptr"), 1)
    ]
    if len(source_pointers) != 68 or any(not item["to"] for item in source_pointers):
        raise ValueError("retained L741 external score-image pointer inventory differs")
    pointers: list[dict[str, Any]] = []
    for source_pointer, profiled in zip(source_pointers, profile_pointers, strict=True):
        if any(profiled.get(key) != source_pointer[key] for key in ("source_order", "to", "source_element_path")):
            raise ValueError("L741 score-image target order or source path differs from the profile")
        target = source_pointer["to"]
        receipt_item = receipt_assets.get(target)
        authority = authorities.get(profiled.get("asset_authority"))
        if receipt_item is None or authority is None:
            raise ValueError(f"L741 score-image target has no retained source resource: {target}")
        if authority.get("role") != "source-resource" or authority.get("path") != profiled.get("asset_logical_path") or authority.get("bytes") != profiled.get("asset_bytes") or authority.get("sha256") != profiled.get("asset_sha256"):
            raise ValueError(f"L741 score-image manifest authority differs: {target}")
        if receipt_item.get("logical_path") != profiled["asset_logical_path"] or receipt_item.get("source_url") != SCORE_IMAGE_BASE + target or receipt_item.get("bytes") != profiled["asset_bytes"] or receipt_item.get("sha256") != profiled["asset_sha256"] or receipt_item.get("content_type") != "image/gif" or profiled.get("asset_url") != receipt_item.get("source_url"):
            raise ValueError(f"L741 score-image receipt or profile target binding differs: {target}")
        image_path = source_manifest.authority_path(profiled["asset_authority"])
        expected_image_path = resolve_repo_path(source_manifest.repository_root, profiled["asset_logical_path"]).resolve(strict=True)
        if image_path != expected_image_path:
            raise ValueError(f"L741 score-image authority resolves outside its declared logical path: {target}")
        image_bytes = image_path.read_bytes()
        if len(image_bytes) != profiled["asset_bytes"] or _sha(image_bytes) != profiled["asset_sha256"] or image_bytes[:6] not in (b"GIF87a", b"GIF89a"):
            raise ValueError(f"L741 retained score-image bytes differ: {target}")
        pointers.append(dict(profiled))
    return raw, source_body, header_xml, pointers


def _append(parent: etree._Element, name: str, text: str | None = None, **attrs: str) -> etree._Element:
    child = etree.SubElement(parent, _tag(name))
    for key, value in attrs.items():
        child.set(key, value)
    child.text = text
    return child


def _build_header(root: etree._Element, profile: dict[str, Any], header_xml: str) -> None:
    header = _append(root, "teiHeader")
    file_desc = _append(header, "fileDesc")
    title_stmt = _append(file_desc, "titleStmt")
    _append(title_stmt, "title", TITLE, type="main")
    edition_stmt = _append(file_desc, "editionStmt")
    _append(edition_stmt, "edition", "DBNL TEI.2 transcription of the first edition (1806).")
    publication = _append(file_desc, "publicationStmt")
    _append(publication, "publisher", "DBNL")
    _append(publication, "idno", SOURCE_ID, type="source-id")
    _append(publication, "idno", "_eva005evan01", type="dbnl-title-id")
    availability = _append(publication, "availability")
    _append(availability, "p", "DBNL labels the 1806 edition Auteursrechtvrij. This records the provider statement only; it is not broader rights clearance.")
    notes = _append(file_desc, "notesStmt")
    header_note = _append(notes, "note", header_xml, type="dbnl-tei2-header-xml")
    header_note.set(XMLID, SOURCE_WITNESS_ID)
    header_note.set(f"{{{XML_NS}}}space", "preserve")
    doctype_note = _append(notes, "note", profile["document_envelope"]["doctype"], type="source-doctype")
    doctype_note.set(f"{{{XML_NS}}}space", "preserve")
    source_desc = _append(file_desc, "sourceDesc")
    bibl = _append(source_desc, "biblStruct")
    monogr = _append(bibl, "monogr")
    _append(monogr, "title", TITLE)
    _append(monogr, "edition", "1ste druk, 1806")
    imprint = _append(monogr, "imprint")
    _append(imprint, "pubPlace", "Amsterdam")
    _append(imprint, "publisher", "Johannes Allart")
    _append(imprint, "date", "1806", when="1806")

    encoding = _append(header, "encodingDesc")
    project = _append(encoding, "projectDesc")
    _append(project, "p", "Direct P5 mapping of the exact retained DBNL TEI.2 source member; see source-accountability.json for source-node linkage and feature accounting.")
    editorial = _append(encoding, "editorialDecl")
    correction = _append(editorial, "correction")
    for index, statement in enumerate(profile["editorial_interventions"], 1):
        _append(correction, "p", statement, n=str(index))
    profile_desc = _append(header, "profileDesc")
    language_usage = _append(profile_desc, "langUsage")
    _append(language_usage, "language", "Nederlands", ident="nl")
    revision = _append(header, "revisionDesc")
    change = _append(revision, "change", when="2013-09-19")
    _append(change, "name", "MdK", type="person")
    _append(change, "p", "colofon toegevoegd")


def _mapped_tag(source: etree._Element) -> str:
    name = _local(source)
    if name == "cf":
        return "div"
    if name == "xptr":
        return "graphic"
    return name


def _copy_source_node(
    source: etree._Element,
    parent: etree._Element,
    counter: list[int],
    score_image_uris: dict[str, str],
) -> etree._Element:
    if not isinstance(source.tag, str):
        raise ValueError("L741 source body contains a comment or processing instruction outside the captured header")
    counter[0] += 1
    name = _mapped_tag(source)
    target = etree.SubElement(parent, _tag(name))
    for key, value in source.attrib.items():
        if _local(source) == "xptr" and key == "to":
            target.set("url", score_image_uris[value])
        elif _local(source) == "interp" and key == "value":
            target.set("n", value)
        else:
            target.set(key, value)
    if _local(source) == "cf":
        if "type" in target.attrib:
            raise ValueError("source cf already has a type attribute")
        target.set("type", "source-title-matter")
    target.set(XMLID, f"l741-source-element-{counter[0]:06d}")
    target.set("corresp", f"#{SOURCE_WITNESS_ID}")
    target.text = source.text
    target.tail = source.tail
    for child in source:
        _copy_source_node(child, target, counter, score_image_uris)
    return target


def _accountability(
    source_manifest: SourceManifest,
    profile: dict[str, Any],
    raw: bytes,
    source_body: etree._Element,
    document_bytes: bytes,
    pointers: list[dict[str, Any]],
    counter: int,
) -> bytes:
    records: list[dict[str, Any]] = []
    source_tree = source_body.getroottree()
    for order, node in enumerate(source_body.iterdescendants(), 1):
        if not isinstance(node.tag, str):
            raise ValueError("L741 source body contains an unaccounted non-element node")
        name = _local(node)
        candidate_name = _mapped_tag(node)
        node_id = f"l741-source-element-{order:06d}"
        records.append(
            {
                "source_order": order,
                "source_path": source_tree.getpath(node),
                "source_element": name,
                "candidate_element": candidate_name,
                "candidate_xml_id": node_id,
                "source_attributes": dict(sorted(node.attrib.items())),
                "source_text_bytes": len((node.text or "").encode("utf-8")),
                "source_text_sha256": _sha((node.text or "").encode("utf-8")),
                "source_tail_bytes": len((node.tail or "").encode("utf-8")),
                "source_tail_sha256": _sha((node.tail or "").encode("utf-8")),
                "candidate_corresp": f"#{SOURCE_WITNESS_ID}",
            }
        )
    if len(records) != counter:
        raise ValueError("L741 source-to-candidate element map is not one-to-one")
    candidate = etree.fromstring(document_bytes)
    mapped = candidate.xpath("/t:TEI/t:text/t:front//*[@xml:id[starts-with(., 'l741-source-element-')]] | /t:TEI/t:text/t:body//*[@xml:id[starts-with(., 'l741-source-element-')]] | /t:TEI/t:text/t:back//*[@xml:id[starts-with(., 'l741-source-element-')]]", namespaces={"t": TEI_NS})
    page_labels = [node.get("n") for node in source_body.xpath(".//pb")]
    interps = [{"type": node.get("type"), "value": node.get("value")} for node in source_body.xpath(".//interp")]
    body_text = _text(source_body)
    result = {
        "contract": "ocd-source-accountability-v1",
        "ticket_id": "L741",
        "work_id": WORK_ID,
        "textual_form_id": TEXTUAL_FORM_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
        "work_catalog_link": profile["work_catalog_link"],
        "source_id": SOURCE_ID,
        "source_manifest": {
            "path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(),
            "sha256": source_manifest.sha256,
        },
        "primary_source": profile["primary_source"],
        "retained_bundle_members": profile["retained_bundle_members"],
        "retained_bundle_member_count": profile["retained_bundle_member_count"],
        "document_envelope": profile["document_envelope"],
        "source_element_counts": profile["source_element_counts"],
        "source_comment_count": profile["source_comment_count"],
        "source_header_capture": {
            "source_byte_start": raw.find(b"<teiHeader>"),
            "source_byte_end_exclusive": raw.find(b"</teiHeader>", raw.find(b"<teiHeader>")) + len(b"</teiHeader>"),
            "bytes": len(raw[raw.find(b"<teiHeader>") : raw.find(b"</teiHeader>", raw.find(b"<teiHeader>")) + len(b"</teiHeader>")]),
            "sha256": _sha(raw[raw.find(b"<teiHeader>") : raw.find(b"</teiHeader>", raw.find(b"<teiHeader>")) + len(b"</teiHeader>")]),
            "retained_as_escaped_source_text": True,
            "external_dtd_loaded": False,
        },
        "source_body": {
            "source_path": "/TEI.2/text/body",
            "source_container_partition": {"front": ["cf", "div[1]", "div[2]"], "body": ["div[3] through div[194]"], "back": ["div[195] through div[198]"]},
            "source_body_direct_child_count": profile["source_body"]["direct_child_count"],
            "source_body_element_count": len(records),
            "one_to_one_source_element_map": records,
            "source_text_character_count": len(body_text),
            "source_text_stream_sha256": _sha(body_text.encode("utf-8")),
            "candidate_text_stream_sha256": _sha(_text(candidate.find(f"{{{TEI_NS}}}text")).encode("utf-8")),
            "candidate_text_stream_matches_source": _text(candidate.find(f"{{{TEI_NS}}}text")) == body_text,
            "page_break_count": len(page_labels),
            "page_break_labels": page_labels,
            "poem_group_count": len(source_body.xpath('.//lg[@type="poem"]')),
            "interp_group_count": len(source_body.xpath(".//interpGrp")),
            "interp_count": len(interps),
            "interp_values": interps,
            "table_count": len(source_body.xpath(".//table")),
            "table_row_count": len(source_body.xpath(".//row")),
            "table_cell_count": len(source_body.xpath(".//cell")),
            "figure_count": len(source_body.xpath(".//figure")),
            "external_score_image_pointers": pointers,
            "candidate_score_image_links": [
                {"uri": source_manifest.authority_path(item["asset_authority"]).resolve(strict=True).as_uri(), "source_path": item["asset_logical_path"], "bytes": item["asset_bytes"], "sha256": item["asset_sha256"]}
                for item in pointers
            ],
        },
        "candidate_tei": {
            "member": "content.tei.xml",
            "bytes": len(document_bytes),
            "sha256": _sha(document_bytes),
            "direct_root_qname": candidate.tag,
            "root_type": "TEI",
            "root_count": 1,
            "descendant_tei_count": len(candidate.xpath(".//t:TEI", namespaces={"t": TEI_NS})),
            "mapped_source_element_count": len(mapped),
            "source_mapped_elements_one_to_one": len(mapped) == len(records),
            "text_children": [etree.QName(child).localname for child in candidate.find(f"{{{TEI_NS}}}text")],
        },
        "editorial_interventions": profile["editorial_interventions"],
        "limitations": profile["limitations"],
        "complete_source_accounting": True,
        "status": "nonaccepted",
    }
    return _canonical(result)


def _unresolved(profile: dict[str, Any], policy: dict[str, Any], pointers: list[dict[str, Any]]) -> bytes:
    if len(pointers) != 68 or any(not pointer.get("asset_sha256") for pointer in pointers):
        raise ValueError("L741 unresolved sidecar cannot omit an unbound score-image target")
    return b"".join(_canonical(item) for item in policy["unresolved"])


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    profile = _profile(source_manifest)
    policy = _policy(source_manifest)
    raw, source_body, header_xml, pointers = _parse_source(source_manifest, profile)
    body_children = list(source_body)
    if len(body_children) != 199 or _local(body_children[0]) != "cf" or any(_local(item) != "div" for item in body_children[1:]):
        raise ValueError("L741 source top-level body sequence differs from cf plus 198 divisions")
    divs = body_children[1:]
    if len(divs) != 198:
        raise ValueError("L741 source division count differs from the profiled 198 divisions")
    source_doc = etree.Element(_tag("TEI"), nsmap={None: TEI_NS})
    source_doc.set(XMLID, WORK_ID)
    _build_header(source_doc, profile, header_xml)
    text = _append(source_doc, "text")
    front = _append(text, "front", corresp="/TEI.2/text/body")
    front.set(XMLID, "l741-front")
    front.text = source_body.text
    body = _append(text, "body", corresp="/TEI.2/text/body")
    body.set(XMLID, "l741-body")
    back = _append(text, "back", corresp="/TEI.2/text/body")
    back.set(XMLID, "l741-back")
    counter = [0]
    score_image_uris = {
        item["to"]: source_manifest.authority_path(item["asset_authority"]).resolve(strict=True).as_uri()
        for item in pointers
    }
    if len(score_image_uris) != 68:
        raise ValueError("L741 candidate score-image targets are not unique")
    _copy_source_node(body_children[0], front, counter, score_image_uris)
    for node in divs[:2]:
        _copy_source_node(node, front, counter, score_image_uris)
    for node in divs[2:194]:
        _copy_source_node(node, body, counter, score_image_uris)
    for node in divs[194:]:
        _copy_source_node(node, back, counter, score_image_uris)
    document_bytes = etree.tostring(source_doc, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    source_text = _text(source_body)
    document = etree.fromstring(document_bytes, etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False))
    candidate_text = _text(document.find(f"{{{TEI_NS}}}text"))
    if candidate_text != source_text:
        raise ValueError("L741 candidate changed source body text or character-data order")
    if len(document.xpath("/t:TEI", namespaces={"t": TEI_NS})) != 1 or document.xpath(".//t:TEI", namespaces={"t": TEI_NS}):
        raise ValueError("L741 converter must emit one root TEI and no descendant TEI")
    account = _accountability(source_manifest, profile, raw, source_body, document_bytes, pointers, counter[0])
    provenance = _canonical(policy["provenance"])
    readme = source_manifest.authority_path("source-attribution-readme").read_bytes()
    return {
        "content.tei.xml": document_bytes,
        "source-accountability.json": account,
        "provenance.json": provenance,
        "unresolved.jsonl": _unresolved(profile, policy, pointers),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
