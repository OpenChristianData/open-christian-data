"""Work-local TEI producer for LIB-055 / 37c-174."""

from __future__ import annotations

from collections import Counter
from io import BytesIO
import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree


CONVERTER_ID = "flavel-method-of-grace-lib055-source-to-tei"
CONVERTER_VERSION = "1"
WORK_ID = "flavel-method-of-grace"
TICKET_ID = "37c-174"
OWNER_ROUTE = "LIB-055"
SOURCE_PATH = "raw/ccel/flavel/grace.xml"
SOURCE_BYTES = 1_796_532
SOURCE_SHA256 = "c044cad334d574b0cf52c936d6179a978c5c9a86bf7d8f51c4b3246a617f40cf"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"

_AUTHORITY_ROLES = {
    "source-member": "primary-source",
    "work-identity": "work-config",
    "feature-profile": "complete-source-feature-profile",
    "policy": "independent-validation-policy",
    "source-readme": "source-attribution-readme",
    "ccel-permission": "exact-source-permission",
    "tei-schema": "tei-validation-schema",
    "package-schema": "candidate-package-schema",
}
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


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(value: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = item
        return result

    try:
        record = json.loads(value.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(record, dict):
        raise ValueError(f"{label} must be a JSON object")
    return record


def _authority_record(source_manifest, name: str) -> Mapping[str, object]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("source-manifest authorities are invalid")
    matches = [item for item in authorities if item.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"source manifest must bind exactly one {name!r} authority")
    return matches[0]


def _authority_bytes(source_manifest, name: str) -> bytes:
    return source_manifest.authority_path(name).read_bytes()


def _tag(node: etree._Element) -> str:
    if not isinstance(node.tag, str):
        raise ValueError("expected an XML element")
    return etree.QName(node).localname


def _parse_source(raw: bytes) -> etree._ElementTree:
    parser = etree.XMLParser(
        load_dtd=False,
        no_network=True,
        resolve_entities=False,
        remove_comments=False,
        remove_pis=False,
        remove_blank_text=False,
        huge_tree=True,
    )
    tree = etree.parse(BytesIO(raw), parser)
    if any(item.level >= etree.ErrorLevels.ERROR for item in parser.error_log):
        raise ValueError("retained XML parser reported an error")
    return tree


def _document_profile(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()
    root_elements = [child for child in root if isinstance(child.tag, str)]
    if _tag(root) != "ThML" or [_tag(child) for child in root_elements] != [
        "ThML.head",
        "ThML.body",
    ]:
        raise ValueError("source root is not the expected ordered ThML head/body envelope")
    head, body = root_elements
    elements = [node for node in root.iter() if isinstance(node.tag, str)]
    head_elements = [node for node in head.iter() if isinstance(node.tag, str)]
    body_elements = [node for node in body.iter() if isinstance(node.tag, str)]
    ids = [node.get("id") for node in elements if node.get("id") is not None]
    links = [node.get("href", "") for node in body.iter("a")]
    fragments = [value.rsplit("#", 1)[-1] for value in links if "#" in value]
    id_set = set(ids)
    direct_divisions = [
        node
        for node in body
        if isinstance(node.tag, str) and _tag(node) == "div1"
    ]
    body_comments = [node for node in body if isinstance(node, etree._Comment)]
    all_comments = tree.xpath("//comment()")
    processing_instructions = tree.xpath("//processing-instruction()")
    body_tail_count = sum(node.tail is not None for node in elements)
    all_tag_counts = Counter(_tag(node) for node in elements)
    attribute_counts: dict[str, dict[str, int]] = {}
    for name in sorted(all_tag_counts):
        counts = Counter(
            attribute
            for node in elements
            if _tag(node) == name
            for attribute in node.attrib
        )
        attribute_counts[name] = dict(sorted(counts.items()))
    if set(attribute_counts) != set(_SOURCE_ATTRIBUTES):
        raise ValueError("source element inventory has an unknown or missing element class")
    for name, allowed in _SOURCE_ATTRIBUTES.items():
        observed = {
            attribute
            for node in elements
            if _tag(node) == name
            for attribute in node.attrib
        }
        if observed != allowed:
            raise ValueError(f"source attribute class changed for {name!r}")
    body_tag_counts = Counter(
        _tag(node) for node in body_elements if node is not body
    )
    sermon_divisions = [
        node for node in direct_divisions if (node.get("title") or "").startswith("Sermon ")
    ]
    if len(links) != 2_625 or len(fragments) != 2_625 or any(
        fragment not in id_set for fragment in fragments
    ) or any("?" not in value.split("#", 1)[0] for value in links):
        raise ValueError("source links do not resolve to the exact retained ID inventory")
    if len(sermon_divisions) != 35 or any(
        sum(1 for _ in node.iter("scripCom")) != 1 for node in sermon_divisions
    ):
        raise ValueError("source sermon divisions and commentary markers do not reconcile")
    return {
        "root": _tag(root),
        "ordered_root_elements": [_tag(node) for node in root_elements],
        "doctype": {
            "name": _tag(root),
            "public_id": tree.docinfo.public_id,
            "system_url": tree.docinfo.system_url,
        },
        "element_count": len(elements),
        "attribute_count": sum(len(node.attrib) for node in elements),
        "head_element_count_including_wrapper": len(head_elements),
        "body_element_count_including_wrapper": len(body_elements),
        "element_text_node_count": sum(node.text is not None for node in elements),
        "element_tail_node_count": body_tail_count,
        "comment_count": len(all_comments),
        "stylesheet_processing_instruction_count": sum(
            node.target == "xml-stylesheet" for node in processing_instructions
        ),
        "body_direct_child_node_count": len(body),
        "body_direct_element_count": sum(isinstance(node.tag, str) for node in body),
        "body_direct_comment_count": len(body_comments),
        "source_id_count": len(ids),
        "unique_source_id_count": len(id_set),
        "source_tag_counts": dict(sorted(all_tag_counts.items())),
        "body_tag_counts_excluding_wrapper": dict(sorted(body_tag_counts.items())),
        "body_top_level_div1_ids": [node.get("id") for node in direct_divisions],
        "source_attribute_counts_by_element": attribute_counts,
        "link_count": len(links),
        "query_and_fragment_link_count": sum(
            "?" in value.split("#", 1)[0] and "#" in value for value in links
        ),
        "resolved_link_fragment_count": sum(fragment in id_set for fragment in fragments),
    }


def _verify_route(source_manifest, raw: bytes) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    record = source_manifest.record
    if (
        record.get("ticket") != TICKET_ID
        or record.get("owner_route") != OWNER_ROUTE
        or record.get("work_id") != WORK_ID
        or record.get("source_id") != "flavel-method-of-grace-lib055-retained-xml"
    ):
        raise ValueError("manifest is not the exact LIB-055 / 37c-174 route")
    identity_binding = record.get("identity")
    if not isinstance(identity_binding, Mapping) or identity_binding.get("work_id") != WORK_ID:
        raise ValueError("manifest work identity does not bind the assigned catalog ID")
    for unresolved in (
        "textual_form",
        "edition",
        "parts",
        "witness_claim",
        "translator",
        "original_publication_year",
    ):
        if identity_binding.get(unresolved) is not None:
            raise ValueError(f"manifest invents unresolved identity field {unresolved}")
    scope = record.get("scope")
    if not isinstance(scope, Mapping) or (
        scope.get("member_count") != 1
        or tuple(scope.get("member_order", ())) != (SOURCE_PATH,)
        or scope.get("selector") != "ThML[1] (complete retained document envelope)"
        or scope.get("selected_source_path") != "ThML[1]"
    ):
        raise ValueError("manifest scope is not the exact complete retained ThML member")
    source = _authority_record(source_manifest, "source-member")
    if (
        source.get("path") != SOURCE_PATH
        or source.get("bytes") != SOURCE_BYTES
        or source.get("sha256") != SOURCE_SHA256
        or _sha(raw) != SOURCE_SHA256
        or len(raw) != SOURCE_BYTES
    ):
        raise ValueError("retained source bytes differ from the assigned current claim")
    roles = {item.get("name"): item.get("role") for item in record["authorities"]}
    if any(roles.get(name) != role for name, role in _AUTHORITY_ROLES.items()):
        raise ValueError("source manifest authority roles do not match the LIB-055 contract")
    profile = _strict_json(_authority_bytes(source_manifest, "feature-profile"), "feature profile")
    policy = _strict_json(_authority_bytes(source_manifest, "policy"), "validation policy")
    identity = _strict_json(_authority_bytes(source_manifest, "work-identity"), "work identity")
    if (
        profile.get("work_id") != WORK_ID
        or policy.get("work_id") != WORK_ID
        or identity.get("contract") != "ocd-reconstruction-work-identity-v1"
        or identity.get("work_id") != WORK_ID
        or identity.get("status") != "observed-only"
    ):
        raise ValueError("work-specific profile, policy, or identity authority is misbound")
    profile_member = profile.get("source_member")
    if not isinstance(profile_member, Mapping) or any(
        profile_member.get(key) != expected
        for key, expected in (
            ("path", SOURCE_PATH),
            ("bytes", SOURCE_BYTES),
            ("sha256", SOURCE_SHA256),
        )
    ):
        raise ValueError("feature profile does not bind the exact retained source member")
    attribute_policy = policy.get("attribute_policy")
    names_by_element = (
        attribute_policy.get("names_by_source_element")
        if isinstance(attribute_policy, Mapping)
        else None
    )
    expected_names = {
        name: sorted(attributes)
        for name, attributes in _SOURCE_ATTRIBUTES.items()
        if attributes
    }
    if names_by_element != expected_names:
        raise ValueError("validation policy does not bind the complete source attribute inventory")
    policy_scope = policy.get("scope")
    if not isinstance(policy_scope, Mapping) or (
        tuple(policy_scope.get("member_order", ())) != (SOURCE_PATH,)
        or policy_scope.get("selector") != "ThML[1] (complete retained document envelope)"
        or tuple(policy_scope.get("exclusions", ())) != ()
    ):
        raise ValueError("validation policy does not bind the complete retained envelope")
    identity_record = identity.get("source_record")
    identity_metadata = identity_binding.get("source_record_metadata")
    if not isinstance(identity_record, Mapping) or not isinstance(identity_metadata, Mapping):
        raise ValueError("work identity source-record metadata is incomplete")
    for manifest_key, identity_key in (
        ("title", "DC.Title"),
        ("creator", "DC.Creator"),
        ("language", "DC.Language"),
    ):
        record_value = identity_record.get(identity_key)
        if manifest_key == "creator":
            if not isinstance(record_value, list) or not record_value:
                raise ValueError("work identity has no observed creator")
            observed_value = record_value[0].get("value") if isinstance(record_value[0], Mapping) else None
        elif manifest_key == "language":
            observed_value = record_value.get("value") if isinstance(record_value, Mapping) else None
        else:
            observed_value = record_value
        if identity_metadata.get(manifest_key) != observed_value:
            raise ValueError(f"manifest source-record {manifest_key} differs from work identity")
    permission = _authority_bytes(source_manifest, "ccel-permission").decode("utf-8")
    if (
        "parsing ThML/XML files for text is explicitly permitted" not in permission
        or "do not sell CCEL files or derivatives of their formatting" not in permission
        or "sourced via CCEL.org" not in _authority_bytes(source_manifest, "source-readme").decode("utf-8")
    ):
        raise ValueError("CCEL permission or candidate attribution binding is absent")
    return profile, policy, identity


def _division_records(tree: etree._ElementTree) -> list[dict[str, object]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("ThML body is absent")
    return [
        {
            "order": index,
            "source_path": tree.getpath(node),
            "id": node.get("id"),
            "title": node.get("title"),
            "prev": node.get("prev"),
            "next": node.get("next"),
        }
        for index, node in enumerate(
            (child for child in body if isinstance(child.tag, str) and _tag(child) == "div1"),
            start=1,
        )
    ]


def _element_records(tree: etree._ElementTree) -> list[dict[str, object]]:
    root = tree.getroot()
    head = root.find("ThML.head")
    body = root.find("ThML.body")
    if head is None or body is None:
        raise ValueError("ThML head or body is absent")
    head_paths = {tree.getpath(node) for node in head.iter() if isinstance(node.tag, str)}
    body_paths = {tree.getpath(node) for node in body.iter() if isinstance(node.tag, str)}
    rows: list[dict[str, object]] = []
    for order, node in enumerate(item for item in root.iter() if isinstance(item.tag, str)):
        path = tree.getpath(node)
        tag = _tag(node)
        parent = node.getparent()
        first_element = parent is not None and next(
            (child for child in parent if isinstance(child.tag, str)), None
        ) is node
        if node is root:
            disposition, target = "document-root-mapped-to-tei", "TEI"
        elif path == tree.getpath(head):
            disposition, target = "header-wrapper-mapped-to-tei", "teiHeader"
        elif path in head_paths and tag == "style":
            disposition, target = "source-formatting-not-reproduced", None
        elif path in head_paths:
            disposition, target = "header-field-mapped-or-explicitly-disposed", None
        elif path == tree.getpath(body):
            disposition, target = "body-wrapper-mapped-to-tei", "body"
        elif path in body_paths:
            disposition, target = "body-element-mapped-to-tei", _body_target_name(
                tag, first_element=first_element
            )
        else:
            raise ValueError(f"source element is outside the declared envelope: {path}")
        direct = node.text or ""
        tail = node.tail or ""
        rows.append(
            {
                "order": order,
                "source_path": path,
                "parent_source_path": tree.getpath(node.getparent()) if node.getparent() is not None else None,
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
    return rows


def _shell_records(tree: etree._ElementTree) -> list[dict[str, object]]:
    root = tree.getroot()
    head = root.find("ThML.head")
    body = root.find("ThML.body")
    records: list[dict[str, object]] = []
    for node in tree.xpath("//comment() | //processing-instruction()"):
        parent = node.getparent()
        if parent is None:
            location = "document-prolog" if node.getnext() is not None or node is root.getprevious() else "document-shell"
        elif head is not None and (parent is head or head in parent.iterancestors()):
            location = "ThML.head"
        elif body is not None and (parent is body or body in parent.iterancestors()):
            location = "ThML.body"
        else:
            location = "ThML"
        if isinstance(node, etree._Comment):
            record = {"kind": "comment", "location": location, "source_path": tree.getpath(node), "text": node.text or ""}
        elif isinstance(node, etree._ProcessingInstruction):
            record = {
                "kind": "processing-instruction",
                "location": location,
                "source_path": tree.getpath(node),
                "target": node.target,
                "text": node.text or "",
            }
        else:
            raise ValueError("unsupported non-element in source document shell")
        record["tail"] = node.tail or ""
        records.append(record)
    return records


def _body_target_name(source_name: str, *, first_element: bool = False) -> str:
    if source_name in {"div1", "div2", "div"}:
        return "div"
    if source_name in {"h1", "h2", "h3", "h6"}:
        return "head" if first_element else "p"
    if source_name == "p":
        return "p"
    if source_name in {"a", "scripRef"}:
        return "ref"
    if source_name in {"scripCom", "insertIndex"}:
        return "anchor"
    raise ValueError(f"unsupported Flavel body element {source_name!r}")


def _body_attributes(source: etree._Element, target_name: str) -> dict[str, str]:
    tag = _tag(source)
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
    allowed = _SOURCE_ATTRIBUTES.get(tag)
    observed = set(source.attrib)
    if (
        allowed is None
        or required is None
        or not required <= observed
        or not observed <= allowed
        or (tag == "p" and observed not in ({"id"}, {"class"}))
    ):
        raise ValueError(f"source attributes are unsupported or incomplete for {tag!r}")
    attrs: dict[str, str] = {}
    if source.get("id") is not None:
        attrs[f"{{{XML_NS}}}id"] = source.get("id", "")
    if tag in {"div1", "div2"}:
        attrs["type"] = f"source-{tag}"
        if source.get("title") is not None:
            attrs["n"] = source.get("title", "")
        for navigation in ("prev", "next"):
            if source.get(navigation) is not None:
                attrs[navigation] = source.get(navigation, "")
    elif tag == "div" and source.get("class") is not None:
        attrs["type"] = source.get("class", "")
    elif tag in {"h1", "h2", "h3", "h6"}:
        if target_name == "head":
            attrs["type"] = f"source-{tag}"
        elif target_name == "p":
            attrs["rend"] = f"source-heading-{tag}"
        else:
            raise ValueError(f"heading source {tag!r} has unsupported TEI target {target_name!r}")
    elif tag == "p":
        if source.get("class") is not None:
            attrs["rend"] = source.get("class", "")
    elif tag == "a":
        if source.get("class") is not None:
            attrs["type"] = source.get("class", "")
        if source.get("href") is None:
            raise ValueError("source link has no href")
        attrs["target"] = source.get("href", "")
    elif tag == "scripRef":
        attrs["type"] = "scripture"
        if source.get("osisRef") is not None:
            attrs["target"] = source.get("osisRef", "")
        if source.get("passage") is not None:
            attrs["n"] = source.get("passage", "")
    elif tag == "scripCom":
        attrs["type"] = "scripture-commentary-marker"
        if source.get("type") is not None:
            attrs["subtype"] = source.get("type", "")
        if source.get("osisRef") is not None:
            attrs["corresp"] = source.get("osisRef", "")
        if source.get("passage") is not None:
            attrs["n"] = source.get("passage", "")
    elif tag == "insertIndex":
        attrs["type"] = "index-insertion"
        if source.get("type") is not None:
            attrs["subtype"] = source.get("type", "")
    else:
        raise ValueError(f"no attribute mapping for source {tag!r} to TEI {target_name!r}")
    return attrs


def _append_body(source: etree._Element, target: etree._Element) -> None:
    target.text = source.text
    first_element = next(
        (child for child in source if isinstance(child.tag, str)), None
    )
    for child in source:
        if isinstance(child, etree._Comment):
            projected = etree.Comment(child.text or "")
        elif isinstance(child.tag, str):
            target_name = _body_target_name(
                _tag(child), first_element=child is first_element
            )
            projected = etree.Element(f"{{{TEI_NS}}}{target_name}")
            for name, value in _body_attributes(child, target_name).items():
                projected.set(name, value)
            _append_body(child, projected)
        else:
            raise ValueError(f"unsupported body node under {_tag(source)!r}")
        projected.tail = child.tail
        target.append(projected)


def _append_description(source: etree._Element, target: etree._Element) -> None:
    target.text = source.text
    for child in source:
        if not isinstance(child.tag, str) or _tag(child) != "br":
            raise ValueError("provider description contains an unsupported inline element")
        linebreak = etree.Element(f"{{{TEI_NS}}}lb")
        linebreak.tail = child.tail
        target.append(linebreak)


def _build_tei(tree: etree._ElementTree, raw: bytes) -> bytes:
    root = tree.getroot()
    head = root.find("ThML.head")
    body_source = root.find("ThML.body")
    if head is None or body_source is None:
        raise ValueError("ThML header or body is absent")
    title = head.find(".//DC.Title")
    creators = head.findall(".//DC.Creator")
    creator = next((node for node in creators if node.get("sub") == "Author" and node.get("scheme") is None), None)
    file_as = next((node for node in creators if node.get("scheme") == "file-as"), None)
    publisher = head.find(".//DC.Publisher")
    date = head.find(".//DC.Date")
    identifier = head.find(".//DC.Identifier")
    language = head.find(".//DC.Language")
    description = head.find(".//description")
    if any(node is None for node in (title, creator, file_as, publisher, date, identifier, language, description)):
        raise ValueError("required provider source-record metadata is absent")

    tei = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    header = etree.SubElement(tei, f"{{{TEI_NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}title", type="source-record-title").text = title.text or ""
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}author").text = creator.text or ""
    publication_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}publicationStmt")
    etree.SubElement(publication_stmt, f"{{{TEI_NS}}}p").text = (
        "Nonaccepted technical candidate; publication is not authorized."
    )
    notes = etree.SubElement(file_desc, f"{{{TEI_NS}}}notesStmt")
    etree.SubElement(notes, f"{{{TEI_NS}}}note", type="source-metadata-status").text = (
        "Source-record metadata is transcribed as observation. It does not establish a print edition, original-publication date, part map, or physical witness."
    )
    etree.SubElement(notes, f"{{{TEI_NS}}}note", type="source-file-as").text = file_as.text or ""
    source_description = etree.SubElement(notes, f"{{{TEI_NS}}}note", type="source-record-description")
    _append_description(description, source_description)
    for node in head.findall(".//DC.Type"):
        etree.SubElement(notes, f"{{{TEI_NS}}}note", type="source-record-field", subtype="DC.Type").text = node.text or ""
    for node in head.findall(".//DC.Format"):
        etree.SubElement(notes, f"{{{TEI_NS}}}note", type="source-record-field", subtype="DC.Format", n=node.get("scheme", "")).text = node.text or ""
    for node in head.findall(".//DC.Date"):
        etree.SubElement(notes, f"{{{TEI_NS}}}note", type="source-record-field", subtype="DC.Date", n=node.get("sub", "")).text = node.text or ""
    for node in head.findall(".//DC.Source"):
        etree.SubElement(
            notes,
            f"{{{TEI_NS}}}note",
            type="source-record-field",
            subtype="DC.Source",
            n=node.get("scheme", ""),
        ).text = node.text or ""
    rights = head.find(".//DC.Rights")
    if rights is None or (rights.text or "") != "":
        raise ValueError("source rights field changed; review required")
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
        node = head.find(f".//{tag}")
        if node is None or (node.text or "") != value:
            raise ValueError(f"source header identifier {tag} drifted")
        etree.SubElement(bibl, f"{{{TEI_NS}}}idno", type=f"ccel-{tag}").text = value
    source_note = etree.SubElement(bibl, f"{{{TEI_NS}}}note", type="retained-member-binding")
    source_note.text = (
        f"Complete retained XML document envelope at {SOURCE_PATH}; {len(raw):,} bytes; "
        f"SHA-256 {_sha(raw)}. This source-member scope does not establish the complete catalog-work boundary."
    )
    encoding_desc = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
    project_desc = etree.SubElement(encoding_desc, f"{{{TEI_NS}}}projectDesc")
    etree.SubElement(project_desc, f"{{{TEI_NS}}}p").text = (
        "This nonaccepted TEI maps the complete retained ThML body in source order. "
        "CCEL CSS/XCSS is accounted for but not reproduced."
    )
    profile_desc = etree.SubElement(header, f"{{{TEI_NS}}}profileDesc")
    lang_usage = etree.SubElement(profile_desc, f"{{{TEI_NS}}}langUsage")
    etree.SubElement(lang_usage, f"{{{TEI_NS}}}language", ident=language.text or "").text = language.text or ""
    text_class = etree.SubElement(profile_desc, f"{{{TEI_NS}}}textClass")
    keywords = etree.SubElement(text_class, f"{{{TEI_NS}}}keywords", scheme="CCEL-DC.Subject")
    for node in head.findall(".//DC.Subject"):
        etree.SubElement(keywords, f"{{{TEI_NS}}}term", type=node.get("scheme", "")).text = node.text or ""

    text = etree.SubElement(tei, f"{{{TEI_NS}}}text", {f"{{{XML_NS}}}lang": language.text or ""})
    body = etree.SubElement(text, f"{{{TEI_NS}}}body")
    _append_body(body_source, body)
    return etree.tostring(tei, encoding="UTF-8", xml_declaration=True)


def _accountability_bytes(
    source_manifest,
    tree: etree._ElementTree,
    raw: bytes,
    profile: Mapping[str, object],
) -> bytes:
    root = tree.getroot()
    document = profile.get("document")
    observed_document = _document_profile(tree)
    for inventory_field in (
        "source_tag_counts",
        "body_tag_counts_excluding_wrapper",
        "body_top_level_div1_ids",
    ):
        observed_document.pop(inventory_field)
    if not isinstance(document, Mapping) or dict(document) != observed_document:
        raise ValueError("retained document no longer matches the bound source profile")
    source_record = {
        "contract": "ocd-source-accountability-v1",
        "ticket": TICKET_ID,
        "owner_route": OWNER_ROUTE,
        "work_id": WORK_ID,
        "source_member": {
            "path": SOURCE_PATH,
            "bytes": len(raw),
            "sha256": _sha(raw),
        },
        "scope": dict(source_manifest.record["scope"]),
        "source_envelope": {
            "xml_declaration": {
                "version": tree.docinfo.xml_version,
                "encoding": tree.docinfo.encoding,
                "standalone": tree.docinfo.standalone,
            },
            "doctype": {
                "name": _tag(root),
                "public_id": tree.docinfo.public_id,
                "system_url": tree.docinfo.system_url,
                "declaration_sha256": _sha(tree.docinfo.doctype.encode("utf-8")),
            },
            "shell_nodes": _shell_records(tree),
            "profile": dict(document),
        },
        "body_carriers": _division_records(tree),
        "elements": _element_records(tree),
        "mapping_policy_sha256": _sha(_authority_bytes(source_manifest, "policy")),
        "source_feature_profile_sha256": _sha(_authority_bytes(source_manifest, "feature-profile")),
    }
    return _canonical(source_record)


def _unresolved_bytes(identity: Mapping[str, object]) -> bytes:
    unresolved = identity.get("unresolved")
    if not isinstance(unresolved, Mapping) or not unresolved:
        raise ValueError("work identity must preserve open identity and rights questions")
    lines = []
    for claim, statement in unresolved.items():
        if not isinstance(statement, str) or not statement:
            raise ValueError(f"unresolved claim {claim!r} has no explanation")
        lines.append(
            _canonical(
                {
                    "claim": claim,
                    "status": "unresolved",
                    "work_id": WORK_ID,
                    "statement": statement,
                }
            )
        )
    return b"".join(lines)


def _provenance_bytes(source_manifest, raw: bytes, profile: Mapping[str, object], policy: Mapping[str, object]) -> bytes:
    converter = dict(source_manifest.record["converter"])
    return _canonical(
        {
            "contract": "ocd-source-to-tei-provenance-v1",
            "ticket": TICKET_ID,
            "owner_route": OWNER_ROUTE,
            "work_id": WORK_ID,
            "source_member": {"path": SOURCE_PATH, "bytes": len(raw), "sha256": _sha(raw)},
            "source_manifest": {
                "path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(),
                "sha256": source_manifest.sha256,
            },
            "converter": converter,
            "feature_profile_sha256": _sha(_authority_bytes(source_manifest, "feature-profile")),
            "policy_sha256": _sha(_authority_bytes(source_manifest, "policy")),
            "scope_selector": source_manifest.record["scope"]["selector"],
            "candidate_status": "nonaccepted",
            "human_acceptance": "not-assessed",
            "publication_status": "not-authorized",
            "notes": "Exact source-member reconstruction; no edition, part, print-witness, or rights-clearance claim is adopted.",
        }
    )


def _convert(source_manifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    raw = _authority_bytes(source_manifest, "source-member")
    profile, policy, identity = _verify_route(source_manifest, raw)
    tree = _parse_source(raw)
    observed = _document_profile(tree)
    observed_document = dict(observed)
    for inventory_field in (
        "source_tag_counts",
        "body_tag_counts_excluding_wrapper",
        "body_top_level_div1_ids",
    ):
        observed_document.pop(inventory_field)
    if profile.get("document") != observed_document:
        raise ValueError("source bytes do not match the bound complete-source feature profile")
    if profile.get("source_tag_counts") != observed["source_tag_counts"]:
        raise ValueError("source element census differs from the bound feature profile")
    if profile.get("body_tag_counts_excluding_wrapper") != observed["body_tag_counts_excluding_wrapper"]:
        raise ValueError("source body census differs from the bound feature profile")
    if tuple(profile.get("body_top_level_div1_ids", ())) != tuple(observed["body_top_level_div1_ids"]):
        raise ValueError("source body carrier order differs from the bound profile")
    if policy.get("scope", {}).get("exclusions") != []:
        raise ValueError("Flavel work policy must account for the complete retained member")
    readme = _authority_bytes(source_manifest, "source-readme")
    return {
        "README.source.md": readme,
        "content.tei.xml": _build_tei(tree, raw),
        "provenance.json": _provenance_bytes(source_manifest, raw, profile, policy),
        "source-accountability.json": _accountability_bytes(source_manifest, tree, raw, profile),
        "unresolved.jsonl": _unresolved_bytes(identity),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
