"""Independent source and candidate verifier for Murray / Absolute Surrender."""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import quote

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-murray-absolute-surrender-independent-thml-oracle"
ORACLE_VERSION = "1"
WORK_ID = "murray-absolute-surrender"
SOURCE_ID = "murray-absolute-surrender-retained-thml"
SOURCE_PATH = "raw/ccel/murray/surrender.xml"
SOURCE_SHA256 = "3b8a474258f452b6d43ce14735c2594da52cd583a0271e8a650969aad97aff7d"
PROFILE_ID = "murray-absolute-surrender-whole-thml-v1"
PROFILE_CONTRACT = "ocd-murray-absolute-surrender-profile-v1"
ACCOUNTABILITY_CONTRACT = "ocd-murray-absolute-surrender-source-accountability-v1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
DOCTYPE_RE = re.compile(r"<!DOCTYPE\s[^[>]*(?:\[[^]]*\])?>", re.IGNORECASE | re.DOTALL)
ENTITY_RE = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")
XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
BODY_ELEMENTS = {
    "div1",
    "div2",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "p",
    "scripRef",
    "a",
    "i",
    "br",
    "l",
    "verse",
    "insertIndex",
}
NON_ELEMENT_RE = re.compile(
    r"(?P<doctype><!DOCTYPE\s[^[>]*(?:\[[^]]*\])?>)"
    r"|(?P<comment><!--[\s\S]*?-->)"
    r"|(?P<pi><\?(?!xml(?:\s|\?>))[\s\S]*?\?>)",
    re.IGNORECASE,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_object(data: bytes, label: str) -> dict[str, Any]:
    def build(pairs: list[tuple[str, object]]) -> dict[str, object]:
        record: dict[str, object] = {}
        for name, value in pairs:
            if name in record:
                raise ValueError(f"{label} repeats JSON key {name!r}")
            record[name] = value
        return record

    value = json.loads(data.decode("utf-8"), object_pairs_hook=build)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _parse_retained_xml(data: bytes) -> etree._Element:
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("independent reader requires UTF-8 retained ThML") from error
    without_doctype = DOCTYPE_RE.sub("", decoded)
    declared_names = set(ENTITY_RE.findall(without_doctype))
    if declared_names - XML_ENTITIES:
        raise ValueError("independent reader encountered a non-XML named entity")
    parser = etree.XMLParser(
        no_network=True,
        resolve_entities=False,
        load_dtd=False,
        huge_tree=True,
        remove_comments=False,
        strip_cdata=False,
    )
    try:
        doc = etree.fromstring(without_doctype.encode("utf-8"), parser)
    except etree.XMLSyntaxError as error:
        raise ValueError("independent source parse failed after DOCTYPE isolation") from error
    if doc.tag != "ThML":
        raise ValueError("independent reader found an unexpected source root")
    return doc


def _name(node: etree._Element) -> str:
    return etree.QName(node).localname


def _absolute_selector(node: etree._Element) -> str:
    # Count same-QName predecessors directly instead of sharing producer traversal.
    fragments: list[str] = []
    cursor: etree._Element | None = node
    while cursor is not None:
        prior_count = 0
        parent = cursor.getparent()
        if parent is not None:
            for sibling in parent:
                if sibling is cursor:
                    break
                if isinstance(sibling.tag, str) and sibling.tag == cursor.tag:
                    prior_count += 1
        fragments.append(f"{_name(cursor)}[{prior_count + 1}]")
        cursor = parent
    fragments.reverse()
    return "/" + "/".join(fragments)


def _header_element_id(node: etree._Element) -> str | None:
    selector = _absolute_selector(node)
    # These exact source carriers have a matching explicit TEI-header record.
    selected_ids = {
        "/ThML[1]/ThML.head[1]": "murray-absolute-surrender-source-header",
        "/ThML[1]/ThML.head[1]/electronicEdInfo[1]/DC[1]/DC.Title[1]": "murray-absolute-surrender-header-title",
        "/ThML[1]/ThML.head[1]/electronicEdInfo[1]/DC[1]/DC.Creator[3]": "murray-absolute-surrender-header-author",
        "/ThML[1]/ThML.head[1]/electronicEdInfo[1]/DC[1]/DC.Contributor[1]": "murray-absolute-surrender-header-transcriber",
        "/ThML[1]/ThML.head[1]/printSourceInfo[1]/published[1]": "murray-absolute-surrender-header-print-claim",
        "/ThML[1]/ThML.head[1]/electronicEdInfo[1]/editorialComments[1]": "murray-absolute-surrender-header-editorial-note",
        "/ThML[1]/ThML.head[1]/electronicEdInfo[1]/DC[1]/DC.Subject[1]": "murray-absolute-surrender-header-subjects",
        "/ThML[1]/ThML.head[1]/electronicEdInfo[1]/DC[1]/DC.Publisher[1]": "murray-absolute-surrender-header-provider",
        "/ThML[1]/ThML.head[1]/electronicEdInfo[1]/DC[1]/DC.Rights[1]": "murray-absolute-surrender-header-rights-claim",
        "/ThML[1]/ThML.head[1]/electronicEdInfo[1]/DC[1]/DC.Language[1]": "murray-absolute-surrender-header-language",
    }
    return selected_ids.get(selector)


def _tei_id_for(
    node: etree._Element,
    ordinal: int,
    document: etree._Element,
    body: etree._Element,
    body_nodes: set[etree._Element],
) -> str | None:
    if node is document:
        return WORK_ID
    if node is body:
        return f"{WORK_ID}-text"
    if node in body_nodes:
        original_id = node.get("id")
        if original_id:
            return original_id
        return f"{WORK_ID}-node-{ordinal:05d}"
    return _header_element_id(node)


def _independent_source_features(
    document: etree._Element,
    body: etree._Element,
) -> list[dict[str, object]]:
    ordered: list[etree._Element] = [
        item for item in document.iter() if isinstance(item.tag, str)
    ]
    ordinals = {id(item): i for i, item in enumerate(ordered, start=1)}
    body_nodes = {item for item in body.iter() if isinstance(item.tag, str)}
    rows: list[dict[str, object]] = []
    for position, current in enumerate(ordered, start=1):
        parent = current.getparent()
        element_siblings = (
            [part for part in parent if isinstance(part.tag, str)]
            if parent is not None
            else [current]
        )
        mapped_id = _tei_id_for(
            current, position, document, body, body_nodes
        )
        if current is document:
            disposition = "represented-by-tei-root"
        elif current is body:
            disposition = "represented-by-tei-text"
        elif current in body_nodes:
            disposition = "represented-in-tei-body"
        elif mapped_id is not None:
            disposition = "represented-in-tei-header"
        elif _name(current) in ("style", "selector"):
            disposition = "presentation-metadata-accountability-only"
        else:
            disposition = "source-header-accountability-only"
        rows.append(
            {
                "feature_id": f"{WORK_ID}-feature-{position:05d}",
                "source_ordinal": position,
                "source_selector": _absolute_selector(current),
                "source_qname": str(current.tag),
                "source_attributes": [
                    {"qname": key, "value": current.attrib[key]}
                    for key in sorted(current.attrib)
                ],
                "source_direct_text": current.text or "",
                "source_tail_text": current.tail or "",
                "source_parent_ordinal": ordinals[id(parent)]
                if parent is not None
                else None,
                "source_child_ordinal": element_siblings.index(current) + 1,
                "disposition": disposition,
                "target_xml_id": mapped_id,
            }
        )
    return rows


def _independent_non_element_events(data: bytes) -> list[dict[str, object]]:
    decoded = data.decode("utf-8")
    records: list[dict[str, object]] = []
    for index, event in enumerate(NON_ELEMENT_RE.finditer(decoded), start=1):
        fragment = event.group(0)
        records.append(
            {
                "source_event_ordinal": index,
                "kind": event.lastgroup,
                "lexical": fragment,
                "sha256": _sha(fragment.encode("utf-8")),
                "disposition": "non-element-event-byte-bound-only",
            }
        )
    return records


def _flat_source_metadata(document: etree._Element) -> dict[str, str]:
    # Independent, source-specific metadata selection from the retained header.
    queries = {
        "title": "string(/ThML/ThML.head/electronicEdInfo/DC/DC.Title)",
        "author": "string(/ThML/ThML.head/electronicEdInfo/DC/DC.Creator[@scheme='short-form'])",
        "transcriber": "string(/ThML/ThML.head/electronicEdInfo/DC/DC.Contributor[@sub='Transcriber'])",
        "language": "string(/ThML/ThML.head/electronicEdInfo/DC/DC.Language)",
        "language_scheme": "string(/ThML/ThML.head/electronicEdInfo/DC/DC.Language/@scheme)",
        "print_claim": "string(/ThML/ThML.head/printSourceInfo/published)",
        "editorial_comment": "string(/ThML/ThML.head/electronicEdInfo/editorialComments)",
        "subjects": "string(/ThML/ThML.head/electronicEdInfo/DC/DC.Subject[@scheme='ccel'])",
        "provider": "string(/ThML/ThML.head/electronicEdInfo/DC/DC.Publisher)",
        "rights_claim": "string(/ThML/ThML.head/electronicEdInfo/DC/DC.Rights)",
    }
    extracted = {key: document.xpath(path) for key, path in queries.items()}
    if any(not isinstance(value, str) or not value.strip() for value in extracted.values()):
        raise ValueError("independent source header is missing a required observed claim")
    return {key: " ".join(value.split()) for key, value in extracted.items()}


def _verify_profile(
    profile: dict[str, Any],
    source: bytes,
    document: etree._Element,
    body: etree._Element,
    rows: list[dict[str, object]],
    events: list[dict[str, object]],
) -> None:
    if profile.get("contract") != PROFILE_CONTRACT or profile.get("profile_id") != PROFILE_ID:
        raise ValueError("independent reader rejects the reconstruction-profile identity")
    source_scope = profile.get("source_scope")
    if not isinstance(source_scope, Mapping) or (
        source_scope.get("member_count") != 1
        or source_scope.get("member_path") != SOURCE_PATH
        or source_scope.get("member_bytes") != len(source)
        or source_scope.get("member_sha256") != _sha(source)
        or source_scope.get("selector") != "/ThML[1]"
        or source_scope.get("body_selector") != "/ThML[1]/ThML.body[1]"
        or source_scope.get("disposition") != "complete-whole-retained-member"
    ):
        raise ValueError("independent reader rejects the retained source scope profile")
    all_nodes = [item for item in document.iter() if isinstance(item.tag, str)]
    body_nodes = [item for item in body.iter() if isinstance(item.tag, str)]
    actual_all = Counter(_name(item) for item in all_nodes)
    actual_body = Counter(_name(item) for item in body_nodes)
    carrier_profile = profile.get("source_carriers")
    if not isinstance(carrier_profile, Mapping):
        raise ValueError("independent reader requires source carrier profile")
    actual_ids = [item.get("id") for item in all_nodes if item.get("id")]
    actual_attribute_count = sum(len(item.attrib) for item in all_nodes)
    if (
        len(rows) != 954
        or len(all_nodes) != carrier_profile.get("element_count")
        or len(body_nodes) != carrier_profile.get("body_element_count")
        or actual_attribute_count != carrier_profile.get("attribute_count")
        or len(actual_ids) != carrier_profile.get("unique_id_attribute_count")
        or len(set(actual_ids)) != len(actual_ids)
        or dict(sorted(actual_all.items())) != carrier_profile.get("element_counts")
        or dict(sorted(actual_body.items())) != carrier_profile.get("body_element_counts")
        or len(re.findall(rb"&(?:amp|lt|gt|quot|apos);", source))
        != carrier_profile.get("entity_reference_count")
        or source.count(b"\xef\xbf\xbd")
        != carrier_profile.get("replacement_character_count")
    ):
        raise ValueError("independent source carrier census differs from the pinned profile")
    division_rows = [
        {"id": item.get("id"), "title": item.get("title")}
        for item in body
        if isinstance(item.tag, str) and _name(item) == "div1"
    ]
    expected_divisions = [
        {"id": item.get("id"), "title": item.get("title")}
        for item in profile.get("ordered_divisions", [])
    ]
    if division_rows != expected_divisions or len(division_rows) != 11:
        raise ValueError("independent reader rejects top-level division order or boundary")
    event_counts = Counter(str(item["kind"]) for item in events)
    event_profile = profile.get("non_element_events")
    if not isinstance(event_profile, Mapping) or event_counts != Counter(
        {
            "comment": event_profile.get("comment_count", -1),
            "pi": event_profile.get("processing_instruction_count", -1),
            "doctype": event_profile.get("doctype_declaration_count", -1),
        }
    ):
        raise ValueError("independent reader rejects the non-element event census")
    if any(_name(item) not in BODY_ELEMENTS | {"ThML.body"} for item in body_nodes):
        raise ValueError("independent reader found an unsupported body element")


def _element(name: str, attrs: Mapping[str, str] | None = None, text: str | None = None) -> etree._Element:
    tag = f"{{{TEI_NS}}}{name}"
    node = etree.Element(tag, nsmap={None: TEI_NS} if name == "TEI" else None)
    for attr, value in (attrs or {}).items():
        node.set(f"{{{XML_NS}}}id" if attr == "xml:id" else attr, str(value))
    node.text = text
    return node


def _encoded_source_pointer(selector: str) -> str:
    return "urn:ocd:source-xpath:" + quote(selector, safe="")


def _html_to_tei(node: etree._Element, ordinal: int) -> etree._Element:
    source_name = _name(node)
    source_selector = _absolute_selector(node)
    source_id = node.get("id")
    tei_id = source_id or f"{WORK_ID}-node-{ordinal:05d}"
    if source_id and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9._-]*", source_id):
        raise ValueError(f"independent reader rejects unsafe source ID {source_id!r}")
    attrs: dict[str, str] = {
        "xml:id": tei_id,
        "corresp": _encoded_source_pointer(source_selector),
    }

    mapping = {
        "h1": ("head", "ThML-h1"),
        "h2": ("head", "ThML-h2"),
        "h3": ("head", "ThML-h3"),
        "h4": ("ab", "source-heading"),
        "verse": ("lg", "verse"),
        "i": ("hi", "italic"),
        "l": ("l", None),
        "br": ("lb", None),
        "insertIndex": ("anchor", "source-index-marker"),
        "p": ("p", None),
        "a": ("ref", None),
        "scripRef": ("ref", "scripture"),
    }
    if source_name in {"div1", "div2", "div"}:
        if source_name == "div1":
            kind = "title-page" if source_id == "i" else "indexes" if source_id == "xi" else "address"
        elif source_name == "div2":
            kind = "index"
        else:
            kind = (node.get("class") or "section").lower()
        attrs["type"] = kind
        if node.get("n"):
            attrs["n"] = node.get("n", "")
        result = _element("div", attrs)
    elif source_name in mapping:
        target_name, value = mapping[source_name]
        if value is not None:
            attribute = "rend" if source_name == "i" else "type"
            attrs[attribute] = value
        if source_name == "h4":
            attrs["subtype"] = "ThML-h4"
        if source_name == "p" and node.get("class"):
            attrs["rend"] = node.get("class", "")
        if source_name == "a":
            href = node.get("href")
            if not href:
                raise ValueError("independent reader rejects a source link without href")
            attrs["target"] = href
            if node.get("class"):
                attrs["type"] = node.get("class", "")
        if source_name == "scripRef":
            passage = node.get("passage")
            if passage:
                attrs["n"] = passage
            c_refs = [
                re.sub(r"^Bible(?:\.[A-Za-z0-9_-]+)?:", "", value)
                for value in (node.get("osisRef") or "").split()
            ]
            c_refs = [value for value in c_refs if value]
            if not c_refs:
                raise ValueError("independent reader rejects a source scripture link without cRef")
            attrs["cRef"] = " ".join(c_refs)
        result = _element(target_name, attrs)
    else:
        raise ValueError(f"independent reader rejects source element <{source_name}>")

    if source_name != "br":
        result.text = node.text
        for child in node:
            if not isinstance(child.tag, str):
                raise ValueError("independent reader rejects a non-element child in ThML.body")
            generated = _html_to_tei(child, _source_ordinal(child))
            generated.tail = child.tail
            result.append(generated)
    return result


def _source_ordinal(node: etree._Element) -> int:
    # Count element nodes in document order without consulting producer inventory.
    root = node.getroottree().getroot()
    for current_ordinal, current in enumerate(
        (item for item in root.iter() if isinstance(item.tag, str)), start=1
    ):
        if current is node:
            return current_ordinal
    raise ValueError("independent reader could not locate a source element ordinal")


def _tei_header(metadata: Mapping[str, str], source_sha: str) -> etree._Element:
    header = _element("teiHeader", {"xml:id": f"{WORK_ID}-source-header"})
    file_desc = _element("fileDesc")
    title_stmt = _element("titleStmt")
    title_stmt.append(
        _element(
            "title",
            {"xml:id": "murray-absolute-surrender-header-title"},
            metadata["title"],
        )
    )
    title_stmt.append(
        _element(
            "author",
            {"xml:id": "murray-absolute-surrender-header-author"},
            metadata["author"],
        )
    )
    responsibilities = _element("respStmt")
    responsibilities.append(_element("resp", text="Transcriber of the retained CCEL ThML"))
    responsibilities.append(
        _element(
            "name",
            {"xml:id": "murray-absolute-surrender-header-transcriber"},
            metadata["transcriber"],
        )
    )
    title_stmt.append(responsibilities)
    file_desc.append(title_stmt)

    publication = _element("publicationStmt")
    publication.append(_element("publisher", text="Open Christian Data"))
    status = _element("availability", {"status": "restricted"})
    status.append(
        _element(
            "p",
            text="Nonaccepted technical reconstruction. Human textual acceptance, rights clearance, and publication authorization are not claimed.",
        )
    )
    publication.append(status)
    file_desc.append(publication)

    source_desc = _element("sourceDesc")
    citation = _element("bibl", {"type": "retained-ccel-thml-witness"})
    citation.append(_element("title", text=metadata["title"]))
    citation.append(_element("author", text=metadata["author"]))
    citation.append(
        _element(
            "ref",
            {"target": "https://www.ccel.org/ccel/murray/surrender.xml"},
            SOURCE_PATH,
        )
    )
    citation.append(_element("idno", {"type": "source-sha256"}, source_sha))
    note_data = (
        ("source-print-claim", "murray-absolute-surrender-header-print-claim", metadata["print_claim"]),
        ("source-editorial-comment", "murray-absolute-surrender-header-editorial-note", metadata["editorial_comment"]),
        ("source-proofing-subjects", "murray-absolute-surrender-header-subjects", metadata["subjects"]),
        ("source-provider-claim", "murray-absolute-surrender-header-provider", metadata["provider"]),
        ("source-rights-claim", "murray-absolute-surrender-header-rights-claim", metadata["rights_claim"]),
        ("source-language-claim", "murray-absolute-surrender-header-language", f"{metadata['language']} ({metadata['language_scheme']})"),
    )
    for kind, xml_id, value in note_data:
        citation.append(_element("note", {"type": kind, "xml:id": xml_id}, value))
    source_desc.append(citation)
    file_desc.append(source_desc)
    header.append(file_desc)

    encoding = _element("encodingDesc")
    encoding.append(
        _element(
            "p",
            text="The complete retained ThML header and body carriers, source attributes, direct text, tails, and non-element events are enumerated in the candidate source-accountability file. Header-only CSS and selector directives are recorded there and are not presented as book text.",
        )
    )
    header.append(encoding)
    return header


def _expected_tei(document: etree._Element, body: etree._Element, metadata: Mapping[str, str], source_sha: str) -> bytes:
    tei = _element("TEI", {"xml:id": WORK_ID})
    tei.append(_tei_header(metadata, source_sha))
    text = _element("text", {"xml:id": f"{WORK_ID}-text"})
    front = _element("front")
    main = _element("body")
    back = _element("back")
    for section in body:
        if not isinstance(section.tag, str) or _name(section) != "div1":
            raise ValueError("independent reader requires only source div1 at body top level")
        converted = _html_to_tei(section, _source_ordinal(section))
        converted.tail = section.tail
        if section.get("id") == "i":
            front.append(converted)
        elif section.get("id") == "xi":
            back.append(converted)
        else:
            main.append(converted)
    if len(front) != 1 or len(main) != 9 or len(back) != 1:
        raise ValueError("independent TEI projection rejects incomplete division groups")
    text.text = body.text
    text.append(front)
    text.append(main)
    text.append(back)
    text.tail = body.tail
    tei.append(text)
    ids = [item.get(f"{{{XML_NS}}}id") for item in tei.iter() if item.get(f"{{{XML_NS}}}id")]
    if len(ids) != len(set(ids)):
        raise ValueError("independent TEI projection produced duplicate xml:id values")
    return etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _expected_accountability(
    source: bytes,
    profile: dict[str, Any],
    rows: list[dict[str, object]],
    events: list[dict[str, object]],
    body: etree._Element,
) -> dict[str, object]:
    ids = [
        value
        for row in rows
        for value in row["source_attributes"]
        if value["qname"] == "id"
    ]
    disposition_counts = Counter(str(row["disposition"]) for row in rows)
    return {
        "contract": ACCOUNTABILITY_CONTRACT,
        "work_id": WORK_ID,
        "source_id": SOURCE_ID,
        "profile_id": PROFILE_ID,
        "member_census": [
            {
                "path": SOURCE_PATH,
                "bytes": len(source),
                "sha256": _sha(source),
                "scope": "whole ThML document including complete header and body",
                "disposition": "included",
            }
        ],
        "counts": {
            "source_elements": len(rows),
            "body_elements": sum(1 for item in body.iter() if isinstance(item.tag, str)),
            "source_attributes": sum(len(row["source_attributes"]) for row in rows),
            "unique_id_attributes": len(ids),
            "comment_events": sum(event["kind"] == "comment" for event in events),
            "processing_instruction_events": sum(event["kind"] == "pi" for event in events),
            "doctype_events": sum(event["kind"] == "doctype" for event in events),
            "unmapped_features": 0,
            "duplicate_features": 0,
            "dispositions": dict(sorted(disposition_counts.items())),
        },
        "crosswalk": rows,
        "non_element_events": events,
        "unmapped_features": [],
        "duplicate_features": [],
    }


def _expected_provenance(
    source_manifest: SourceManifest,
    source: bytes,
    config_bytes: bytes,
    metadata_bytes: bytes,
    attribution: bytes,
    profile: dict[str, Any],
    metadata: Mapping[str, str],
) -> dict[str, object]:
    manifest_authorities = {
        str(value["name"]): dict(value)
        for value in source_manifest.record["authorities"]
    }
    config = _strict_object(config_bytes, "source work config")
    return {
        "contract": "ocd-murray-absolute-surrender-provenance-v1",
        "status": "nonaccepted",
        "publication_status": "not-authorized",
        "ticket": "37c-256",
        "owner_route": "LIB-055",
        "work_id": WORK_ID,
        "source_id": SOURCE_ID,
        "source": {
            "path": SOURCE_PATH,
            "bytes": len(source),
            "sha256": _sha(source),
            "scope": "complete ThML document, including the full source header and ThML.body",
            "member_count": 1,
            "profile_id": profile["profile_id"],
        },
        "work_binding": {
            "path": manifest_authorities["work-identity-config"]["path"],
            "sha256": _sha(config_bytes),
            "legacy_parser_output": "data/structured-text/murray-absolute-surrender.json",
            "legacy_output_used_as_reconstruction_authority": False,
        },
        "metadata_evidence": {
            "path": manifest_authorities["source-metadata-sidecar"]["path"],
            "sha256": _sha(metadata_bytes),
            "contract": "source-metadata-sidecar-v1",
            "subject": {"kind": "catalog", "id": WORK_ID},
            "adoption_scope": "existing inspected META-002/003 source-evidence projection; no config, generated-data, or index mutation",
        },
        "data_attribution": {
            "path": manifest_authorities["data-attribution-readme"]["path"],
            "sha256": _sha(attribution),
            "delivered_notice": True,
        },
        "source_quality": {
            "classification": "human-correction-explicitly-attested-for-exact-retained-source",
            "transcriber": metadata["transcriber"],
            "proofed_subject": "Proofed",
            "title_page_attestation": "Scanned and corrected by Claude King, September 1999.",
            "editorial_comment": metadata["editorial_comment"],
            "limits": list(profile["human_correction_attestation"]["limits"]),
        },
        "identity": {
            "status": "retained-witness-bound; canonical work and edition questions remain unresolved",
            "title": metadata["title"],
            "author": metadata["author"],
            "source_print_claim": metadata["print_claim"],
            "legacy_config_edition_claim": config.get("source_edition"),
            "print_collation": "not performed",
        },
        "rights": {
            "status": "unreviewed",
            "source_claim": metadata["rights_claim"],
            "ccel_terms_notice": manifest_authorities["data-attribution-readme"]["path"],
            "publication_authorized": False,
        },
        "human_acceptance": {"status": "not-recorded"},
        "producer": {
            "id": "ocd-murray-absolute-surrender-retained-thml-to-tei",
            "version": "1",
            "callable": "_convert",
            "path": "build/tei/murray_absolute_surrender_reconstruction.py",
        },
        "independent_verifier": {
            "id": ORACLE_ID,
            "version": ORACLE_VERSION,
            "path": "build/tei/murray_absolute_surrender_oracle.py",
            "source_reader_independent_of_producer": True,
        },
    }


def _local_module(root: Path, dotted_name: str) -> Path | None:
    choices = (
        root.joinpath(*dotted_name.split(".")).with_suffix(".py"),
        root.joinpath(*dotted_name.split("."), "__init__.py"),
    )
    for path in choices:
        if path.is_file():
            resolved = path.resolve(strict=True)
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            return resolved
    return None


def _module_name(root: Path, path: Path) -> str:
    parts = list(path.resolve(strict=True).relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported_names(root: Path, path: Path, node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if not isinstance(node, ast.ImportFrom):
        return ()
    if node.level == 0:
        base = node.module or ""
    else:
        package = _module_name(root, path).split(".")
        if path.name != "__init__.py":
            package.pop()
        if node.level > len(package):
            raise ValueError("independent-oracle relative import leaves repository root")
        parent = ".".join(package[: len(package) - node.level + 1])
        base = f"{parent}.{node.module}" if parent and node.module else parent or (node.module or "")
    if not base:
        return ()
    return (base, *(f"{base}.{alias.name}" for alias in node.names))


def _validator_closure(root: Path, policy: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    forbidden = tuple(str(prefix) for prefix in policy.get("forbidden_import_prefixes", []))
    entry = (root / "build/tei/murray_absolute_surrender_oracle.py").resolve(strict=True)
    pending = [entry]
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in set(policy.get("dynamic_execution_names", []))
            ):
                raise ValueError("independent-oracle closure contains dynamic code execution")
            for imported in _imported_names(root, path, node):
                if any(imported == prefix or imported.startswith(prefix + ".") for prefix in forbidden):
                    raise ValueError(f"independent-oracle closure imports forbidden producer code: {imported}")
                local = _local_module(root, imported)
                if local is not None and local not in visited:
                    pending.append(local)
    return tuple(
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha(path.read_bytes()),
        }
        for path in sorted(visited, key=lambda item: item.relative_to(root).as_posix())
    )


def _closure_digest(root: Path, policy: Mapping[str, Any]) -> str:
    return _sha(_canonical(_validator_closure(root, policy)))


def _read_authority(
    manifest: SourceManifest,
    name: str,
    *,
    expected_role: str | None = None,
) -> bytes:
    authority = next(
        (row for row in manifest.record["authorities"] if row.get("name") == name),
        None,
    )
    if authority is None:
        raise ValueError(f"source manifest is missing authority {name!r}")
    if expected_role and authority.get("role") != expected_role:
        raise ValueError(f"source authority {name!r} has the wrong role")
    return manifest.authority_path(name).read_bytes()


def _validate_metadata_evidence(sidecar: dict[str, Any]) -> None:
    if (
        sidecar.get("schema_version") != "source-metadata-sidecar-v1"
        or sidecar.get("subject") != {"kind": "catalog", "id": WORK_ID}
        or sidecar.get("writer") != "ocd-source-metadata-v1"
    ):
        raise ValueError("independent reader rejects the current metadata sidecar identity")
    dimensions = sidecar.get("dimensions")
    if not isinstance(dimensions, Mapping):
        raise ValueError("independent reader requires source metadata dimensions")
    expected = {
        "work": {"observed.author": "supported", "observed.title": "supported"},
        "witnesses": {"observed.source_hash": "supported"},
    }
    for dimension, predicates in expected.items():
        record = dimensions.get(dimension)
        if not isinstance(record, Mapping) or record.get("status") != "inspected":
            raise ValueError(f"metadata dimension {dimension!r} is not inspected")
        fields = record.get("fields")
        if not isinstance(fields, list):
            raise ValueError(f"metadata dimension {dimension!r} has no field list")
        by_predicate = {
            item.get("scope", {}).get("predicate"): item
            for item in fields
            if isinstance(item, Mapping) and isinstance(item.get("scope"), Mapping)
        }
        for predicate, classification in predicates.items():
            field = by_predicate.get(predicate)
            if not isinstance(field, Mapping):
                raise ValueError(f"metadata sidecar lacks the adopted {predicate} claim")
            evidence = field.get("evidence")
            adoption = field.get("adoption")
            if (
                not isinstance(evidence, Mapping)
                or evidence.get("classification") != classification
                or not isinstance(adoption, Mapping)
                or adoption.get("classification") != "adopted"
                or adoption.get("destination") != "source_evidence_only"
            ):
                raise ValueError(f"metadata source-evidence adoption is stale for {predicate}")


def _candidate_readme_bytes() -> bytes:
    return (
        "# Murray — Absolute Surrender source note\n\n"
        "This is a nonaccepted, source-bound technical reconstruction for the whole retained ThML document `raw/ccel/murray/surrender.xml` (SHA-256 `"
        + SOURCE_SHA256
        + "`). It represents the title page, nine address divisions, and indexes. The retained header names Claude King as transcriber and labels the CCEL subject `Proofed`; the title page says the text was scanned and corrected by Claude King in September 1999.\n\n"
        "The exact source carrier inventory and explicit dispositions are in `source-accountability.json`. The source describes light editorial changes to language and scripture references. No original-print collation or textual acceptance is claimed.\n\n"
        "The source claims Public Domain, and its CCEL attribution and formatting terms are recorded in `data/structured-text/README.md`. This candidate does not make a rights determination, establish edition identity, or authorize publication. Human acceptance, rights clearance, canonical IR acceptance, and publication remain separate.\n"
    ).encode("utf-8")


def _expected_candidate_manifest(
    manifest: SourceManifest,
    candidate: CandidatePackage,
) -> dict[str, object]:
    converter = dict(manifest.record["converter"])
    package_schema = dict(manifest.record["package_schema"])
    logical_path = manifest.path.relative_to(manifest.repository_root).as_posix()
    members = []
    for name in sorted(candidate.member_names):
        if name == "manifest.json":
            continue
        content = candidate.member_bytes(name)
        members.append({"name": name, "bytes": len(content), "sha256": _sha(content)})
    return {
        "contract": "ocd-candidate-package-v1",
        "status": "nonaccepted",
        "source_id": SOURCE_ID,
        "source_manifest": {"path": logical_path, "sha256": manifest.sha256},
        "converter": converter,
        "package_schema": package_schema,
        "members": members,
    }


def _oracle(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    repository_root = source_manifest.repository_root
    source_bytes = _read_authority(source_manifest, "retained-source", expected_role="primary-source")
    config_bytes = _read_authority(source_manifest, "work-identity-config", expected_role="work-identity-config")
    profile_bytes = _read_authority(source_manifest, "reconstruction-profile", expected_role="complete-source-feature-profile")
    policy_bytes = _read_authority(source_manifest, "validation-policy", expected_role="independent-validation-policy")
    account_schema_bytes = _read_authority(source_manifest, "source-accountability-schema", expected_role="complete-source-accountability-schema")
    metadata_bytes = _read_authority(source_manifest, "source-metadata-sidecar", expected_role="source-metadata-evidence")
    attribution_bytes = _read_authority(source_manifest, "data-attribution-readme", expected_role="source-attribution-readme")
    package_schema_bytes = _read_authority(source_manifest, "candidate-package-schema", expected_role="candidate-package-schema")
    xsd_bytes = _read_authority(source_manifest, "tei-p5-xsd", expected_role="tei-validation-schema")
    closure_policy_bytes = _read_authority(source_manifest, "oracle-closure-policy", expected_role="validator-import-closure-policy")

    profile = _strict_object(profile_bytes, "Murray source profile")
    policy = _strict_object(policy_bytes, "Murray validation policy")
    config = _strict_object(config_bytes, "Murray work config")
    metadata_sidecar = _strict_object(metadata_bytes, "Murray source metadata evidence")
    package_schema = _strict_object(package_schema_bytes, "candidate package schema")
    account_schema = _strict_object(account_schema_bytes, "source-accountability schema")
    closure_policy = _strict_object(closure_policy_bytes, "oracle import-closure policy")

    if len(source_bytes) != 217645 or _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("independent reader rejects retained source bytes or SHA-256")
    if (
        source_manifest.record.get("source_id") != SOURCE_ID
        or source_manifest.record.get("work_id") != WORK_ID
        or candidate.manifest.get("source_id") != SOURCE_ID
    ):
        raise ValueError("independent reader rejects source/work identity binding")
    if (
        config.get("resource_id") != WORK_ID
        or config.get("source_file", "").replace("\\", "/") != SOURCE_PATH
        or config.get("source_hash") != f"sha256:{SOURCE_SHA256}"
    ):
        raise ValueError("independent reader rejects work-config source binding")
    policy_provenance = policy.get("provenance")
    if (
        policy.get("contract") != "ocd-murray-absolute-surrender-validation-policy-v1"
        or policy.get("policy_id") != "murray-absolute-surrender-independent-thml-policy-v1"
        or policy.get("work_id") != WORK_ID
        or policy.get("source_id") != SOURCE_ID
        or not isinstance(policy_provenance, Mapping)
        or policy_provenance.get("identity")
        != {"title": "Absolute Surrender", "author": "Andrew Murray"}
        or policy_provenance.get("source")
        != {"bytes": 217645, "sha256": SOURCE_SHA256}
    ):
        raise ValueError("independent reader rejects validation policy contract")
    if (
        closure_policy.get("contract") != "ocd-validator-import-closure-policy-v1"
        or closure_policy.get("validator_id") != ORACLE_ID
        or set(closure_policy.get("forbidden_import_prefixes", []))
        != {"build.tei.murray_absolute_surrender_reconstruction", "build.tei.thml_to_tei"}
    ):
        raise ValueError("independent reader rejects import-closure policy identity")
    _validate_metadata_evidence(metadata_sidecar)
    if (
        b"Christian Classics Ethereal Library (CCEL)" not in attribution_bytes
        or b"Do not sell CCEL files" not in attribution_bytes
    ):
        raise ValueError("independent reader rejects missing CCEL data attribution notice")

    document = _parse_retained_xml(source_bytes)
    body_nodes = [
        child
        for child in document
        if isinstance(child.tag, str) and _name(child) == "ThML.body"
    ]
    if len(body_nodes) != 1:
        raise ValueError("independent reader rejects a non-singleton retained ThML body")
    source_body = body_nodes[0]
    features = _independent_source_features(document, source_body)
    events = _independent_non_element_events(source_bytes)
    _verify_profile(profile, source_bytes, document, source_body, features, events)
    metadata = _flat_source_metadata(document)
    expected_accountability = _expected_accountability(
        source_bytes, profile, features, events, source_body
    )
    observed_accountability = _strict_object(
        candidate.member_bytes("source-accountability.json"),
        "candidate source-accountability",
    )
    if observed_accountability != expected_accountability:
        raise ValueError("independent source enumeration rejects accountability omission, duplication, order, or content drift")
    account_errors = sorted(
        Draft202012Validator(account_schema).iter_errors(observed_accountability),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if account_errors:
        raise ValueError(f"source-accountability schema rejects candidate: {account_errors[0].message}")

    expected_tei = _expected_tei(document, source_body, metadata, _sha(source_bytes))
    observed_tei = candidate.member_bytes("content.tei.xml")
    if observed_tei != expected_tei:
        raise ValueError("independent ThML-to-TEI re-read rejects omission, duplication, reordering, invention, or metadata drift")
    try:
        tei_root = etree.fromstring(
            observed_tei,
            etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
        )
    except etree.XMLSyntaxError as error:
        raise ValueError("candidate TEI is not parseable") from error
    schema_file = source_manifest.authority_path("tei-p5-xsd")
    expected_schema = repository_root / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
    if not schema_file.samefile(expected_schema):
        raise ValueError("source manifest TEI P5 schema authority is unexpected")
    if not compiled_schema().validate(etree.ElementTree(tei_root)):
        schema_error = compiled_schema().error_log.last_error
        detail = schema_error.message if schema_error is not None else "unknown TEI P5 error"
        raise ValueError(f"candidate TEI fails the pinned TEI P5 schema: {detail}")

    expected_provenance = _expected_provenance(
        source_manifest,
        source_bytes,
        config_bytes,
        metadata_bytes,
        attribution_bytes,
        profile,
        metadata,
    )
    if _strict_object(candidate.member_bytes("provenance.json"), "candidate provenance") != expected_provenance:
        raise ValueError("independent metadata and provenance check rejects drift")
    expected_unresolved = b"".join(
        _canonical(row) for row in profile.get("unresolved", [])
    )
    if candidate.member_bytes("unresolved.jsonl") != expected_unresolved:
        raise ValueError("candidate unresolved-evidence ledger differs from pinned scope")
    if candidate.member_bytes("README.source.md") != _candidate_readme_bytes():
        raise ValueError("candidate source README differs from the pinned attribution handoff")

    candidate_manifest = _strict_object(candidate.member_bytes("manifest.json"), "candidate manifest")
    expected_candidate_manifest = _expected_candidate_manifest(source_manifest, candidate)
    if candidate_manifest != expected_candidate_manifest:
        raise ValueError("candidate manifest does not bind the exact route and five candidate members")
    package_schema_errors = sorted(
        Draft202012Validator(package_schema).iter_errors(candidate_manifest),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if package_schema_errors:
        raise ValueError(f"candidate-package schema rejects candidate: {package_schema_errors[0].message}")
    if _sha(xsd_bytes) != _sha(schema_file.read_bytes()):
        raise ValueError("TEI schema authority changed during verification")

    validator = source_manifest.record.get("validator")
    if not isinstance(validator, Mapping):
        raise ValueError("source manifest independent verifier identity is missing")
    if (
        validator.get("id") != ORACLE_ID
        or validator.get("version") != ORACLE_VERSION
        or validator.get("implementation_path") != "build/tei/murray_absolute_surrender_oracle.py"
        or validator.get("callable") != "_oracle"
    ):
        raise ValueError("source manifest independent verifier binding is stale")
    computed_closure = _closure_digest(repository_root, closure_policy)
    if computed_closure != validator.get("import_closure_sha256"):
        raise ValueError("independent verifier import closure differs from the source manifest")

    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=computed_closure,
        source_sha256=SOURCE_SHA256,
        profile_sha256=_sha(profile_bytes),
        package_schema_sha256=_sha(package_schema_bytes),
        xsd_sha256=_sha(xsd_bytes),
        policy_sha256=_sha(policy_bytes),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
