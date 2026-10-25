"""Deterministic retained-ThML to six-member Mark candidate conversion."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import quote

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.writer import TEI_NS, stamp_header, tei_el


CONVERTER_ID = "ocd-mark-thml-to-tei"
CONVERTER_VERSION = "1"
_PROFILE_ID = "mark-rich-tei-v1"
_EDITION_ID = "expositors-bible-mark-ccel-english-1896-rendering-v1"
_EXPRESSION_ID = "expositors-bible-mark-english-1896"
_WORK_ID = "expositors-bible-gospel-according-to-st-mark"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_SAFE_ENTITIES = {"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"}
_EXTRA_ENTITIES = {
    "&emdash;": "-",
    "&mdash;": "-",
    "&ndash;": "-",
    "&lsquo;": "'",
    "&rsquo;": "'",
    "&ldquo;": '"',
    "&rdquo;": '"',
    "&nbsp;": " ",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(record: object) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _replace_entity(match: re.Match[str]) -> str:
    entity = match.group(0)
    if entity in _SAFE_ENTITIES:
        return entity
    if entity in _EXTRA_ENTITIES:
        return _EXTRA_ENTITIES[entity]
    replacement = html.unescape(entity)
    return "" if replacement == entity else replacement


def _prepared_thml(content: bytes) -> bytes:
    try:
        text = content.decode("utf-8")
        if "\ufffd" in text:
            raise UnicodeDecodeError("utf-8", content, 0, 1, "replacement found")
    except UnicodeDecodeError:
        text = content.decode("cp1252", errors="replace")
    text = re.sub(r"<!DOCTYPE\s[^[>]*(?:\[[^\]]*\])?>", "", text, flags=re.DOTALL)
    return re.sub(r"&[A-Za-z][A-Za-z0-9]*;", _replace_entity, text).encode("utf-8")


def _parse_source(content: bytes) -> tuple[etree._Element, etree._Element]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    try:
        root = etree.fromstring(_prepared_thml(content), parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("retained Mark ThML is not parseable") from exc
    bodies = [
        child
        for child in root
        if isinstance(child.tag, str)
        and etree.QName(child).localname == "ThML.body"
    ]
    if len(bodies) != 1:
        raise ValueError("retained Mark ThML must have exactly one body")
    return root, bodies[0]


def _selector(element: etree._Element, body: etree._Element) -> str:
    parts: list[str] = []
    current = element
    while current is not body:
        parent = current.getparent()
        if parent is None:
            raise ValueError("source element escaped ThML.body")
        tag = etree.QName(current).localname
        peers = [
            child
            for child in parent
            if isinstance(child.tag, str) and etree.QName(child).localname == tag
        ]
        parts.append(f"{tag}[{peers.index(current) + 1}]")
        current = parent
    result = "/ThML/ThML.body[1]/" + "/".join(reversed(parts))
    return result + (
        f"[@id={json.dumps(element.get('id'))}]" if element.get("id") else ""
    )


def _profile_mapping(profile: Mapping[str, object]) -> dict[str, dict[str, str]]:
    if (
        profile.get("contract") != "ocd-mark-rich-tei-profile-v2"
        or profile.get("profile_id") != _PROFILE_ID
        or profile.get("version") != 2
    ):
        raise ValueError("Mark reconstruction profile identity mismatch")
    dispositions = profile.get("feature_dispositions")
    if not isinstance(dispositions, dict) or not dispositions:
        raise ValueError("Mark reconstruction profile has no feature dispositions")
    result: dict[str, dict[str, str]] = {}
    for source_tag, disposition in dispositions.items():
        if (
            not isinstance(source_tag, str)
            or not isinstance(disposition, dict)
            or not isinstance(disposition.get("tei"), str)
            or set(disposition) - {"tei", "type"}
            or ("type" in disposition and not isinstance(disposition["type"], str))
        ):
            raise ValueError("Mark reconstruction profile feature mapping is invalid")
        result[source_tag] = {str(key): str(value) for key, value in disposition.items()}
    return result


def _inventory(
    source_bytes: bytes, profile_mapping: Mapping[str, Mapping[str, str]]
) -> tuple[dict[str, object], ...]:
    _, body = _parse_source(source_bytes)
    elements = [item for item in body.iterdescendants() if isinstance(item.tag, str)]
    records: list[dict[str, object]] = []
    for ordinal, element in enumerate(elements, start=1):
        tag = etree.QName(element).localname
        if tag not in profile_mapping:
            raise ValueError(f"unmapped Mark source tag: {tag}")
        direct = element.text or ""
        tail = element.tail or ""
        records.append(
            {
                "feature_id": f"mark-feature-{ordinal:05d}",
                "source_selector": _selector(element, body),
                "source_tag": tag,
                "source_xml_id": element.get("id"),
                "attributes": {
                    etree.QName(name).localname: value
                    for name, value in sorted(element.attrib.items())
                },
                "direct_text": direct,
                "tail_text": tail,
                "direct_text_sha256": _sha(direct.encode("utf-8")),
                "tail_text_sha256": _sha(tail.encode("utf-8")),
                "tei_tag": profile_mapping[tag]["tei"],
            }
        )
    source_ids = [
        str(record["source_xml_id"])
        for record in records
        if record["source_xml_id"] is not None
    ]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("retained Mark source IDs are not unique")
    assigned = set(source_ids) | {"mark-whole-body"}
    for ordinal, record in enumerate(records, start=1):
        source_id = record["source_xml_id"]
        if source_id is not None:
            target_id = str(source_id)
        else:
            stem = f"mark-generated-{ordinal:05d}"
            target_id = stem
            suffix = 1
            while target_id in assigned:
                target_id = f"{stem}-{suffix}"
                suffix += 1
            assigned.add(target_id)
        record["tei_xml_id"] = target_id
    by_element = {
        id(element): record
        for element, record in zip(elements, records, strict=True)
    }
    for element, record in zip(elements, records, strict=True):
        parent = element.getparent()
        if parent is body:
            parent_id = "mark-whole-body"
        elif parent is None or id(parent) not in by_element:
            raise ValueError("retained Mark hierarchy escaped ThML.body")
        else:
            parent_id = str(by_element[id(parent)]["tei_xml_id"])
        siblings = [child for child in parent if isinstance(child.tag, str)]
        record["tei_parent_id"] = parent_id
        record["tei_child_ordinal"] = siblings.index(element) + 1
    return tuple(records)


def _rend(attributes: Mapping[str, object], tag: str) -> str | None:
    values = [
        f"source-{name}:{attributes[name]}"
        for name in ("class", "style", "progress", "type")
        if attributes.get(name)
    ]
    if tag == "i":
        values.insert(0, "italic")
    return "; ".join(values) or None


def _projection(
    feature: Mapping[str, object],
    source_id_map: Mapping[str, str],
    profile_mapping: Mapping[str, Mapping[str, str]],
) -> dict[str, object]:
    tag = str(feature["source_tag"])
    source = feature["attributes"]
    assert isinstance(source, Mapping)
    attrs: dict[str, str] = {"xml:id": str(feature["tei_xml_id"])}
    rend = _rend(source, tag)
    if rend:
        attrs["rend"] = rend
    if tag in {"div", "div1", "div2"}:
        if tag == "div1":
            attrs["type"] = {
                "i": "title-page",
                "ii": "contents",
                "xix": "indexes",
            }.get(feature["source_xml_id"], "chapter")
        else:
            attrs["type"] = "commentary-section" if tag == "div2" else "source-division"
    elif tag == "a":
        attrs["type"] = "source-navigation"
    elif tag in {"scripRef", "scripCom"}:
        attrs["type"] = "scripture" if tag == "scripRef" else "scripture-commentary"
        if source.get("osisRef"):
            attrs["corresp"] = "urn:osis:" + quote(str(source["osisRef"]), safe=":.-")
            if tag == "scripRef":
                attrs["cRef"] = str(source["osisRef"]).replace("Bible:", "")
        if source.get("passage"):
            attrs["n"] = str(source["passage"])
        if source.get("parsed"):
            attrs["source"] = "urn:ccel-thml-parsed:" + quote(
                str(source["parsed"]), safe=""
            )
    elif tag == "note" and source.get("n"):
        attrs["n"] = str(source["n"])
    elif tag == "insertIndex":
        attrs["unit"] = "source-index"
    elif tag == "blockquote":
        attrs["type"] = "block"
    elif tag == "verse":
        attrs["type"] = "verse"
    elif tag in {"h1", "h2", "h3", "h4"}:
        attrs["type"] = "heading"
    declared_type = profile_mapping[tag].get("type")
    if declared_type is not None and attrs.get("type") != declared_type:
        raise ValueError(f"Mark profile type mapping is not honored for {tag}")
    dispositions: list[dict[str, object]] = []
    for name, value in source.items():
        item: dict[str, object] = {
            "source_name": name,
            "source_value": value,
            "disposition": "represented",
        }
        if name == "id":
            item.update(target_name="xml:id", target_value=attrs["xml:id"])
        elif name in {"class", "style", "progress", "type"}:
            item.update(target_name="rend", target_value=attrs["rend"])
        elif name in {"prev", "next"}:
            target_id = source_id_map.get(str(value))
            if target_id is None:
                item.update(
                    disposition="excluded",
                    reason_code="unresolved-source-pointer",
                    reason="source pointer names no element in the retained ThML body",
                )
            else:
                attrs[name] = f"#{target_id}"
                item.update(target_name=name, target_value=attrs[name])
        elif name == "href":
            base, separator, fragment = str(value).rpartition("#")
            if not separator or fragment not in source_id_map:
                raise ValueError("Mark navigation href has an unresolved fragment")
            attrs["target"] = base + "#" + source_id_map[fragment]
            item.update(target_name="target", target_value=attrs["target"])
        elif name == "title":
            item.update(
                target_name="child::head[@type='source-title']", target_value=value
            )
        elif name == "n":
            item.update(target_name="n", target_value=attrs["n"])
        elif name == "osisRef":
            item.update(target_name="corresp", target_value=attrs["corresp"])
        elif name == "parsed":
            item.update(target_name="source", target_value=attrs["source"])
        elif name == "passage":
            item.update(target_name="n", target_value=attrs["n"])
        else:
            raise ValueError(f"unmapped Mark source attribute: {name}")
        dispositions.append(item)
    return {"tei_attributes": attrs, "attribute_dispositions": dispositions}


def _convert_element(
    source: etree._Element,
    features: Mapping[int, Mapping[str, object]],
    projections: Mapping[int, Mapping[str, object]],
) -> etree._Element:
    feature = features[id(source)]
    projection = projections[id(source)]
    attributes = projection["tei_attributes"]
    assert isinstance(attributes, dict)
    target = tei_el(str(feature["tei_tag"]), attributes)
    source_attributes = feature["attributes"]
    assert isinstance(source_attributes, Mapping)
    if source_attributes.get("title"):
        target.append(
            tei_el(
                "head",
                {"type": "source-title"},
                str(source_attributes["title"]),
            )
        )
    target.text = (target.text or "") + (source.text or "")
    for child in source:
        if not isinstance(child.tag, str):
            continue
        converted = _convert_element(child, features, projections)
        target.append(converted)
        converted.tail = child.tail or ""
    return target


def _tei(
    source_bytes: bytes,
    inventory: tuple[dict[str, object], ...],
    profile_mapping: Mapping[str, Mapping[str, str]],
) -> tuple[bytes, tuple[dict[str, object], ...]]:
    _, source_body = _parse_source(source_bytes)
    elements = [
        item for item in source_body.iterdescendants() if isinstance(item.tag, str)
    ]
    if len(elements) != len(inventory):
        raise ValueError("Mark inventory changed during conversion")
    source_id_map = {
        str(item["source_xml_id"]): str(item["tei_xml_id"])
        for item in inventory
        if item["source_xml_id"] is not None
    }
    projected = tuple(
        _projection(item, source_id_map, profile_mapping) for item in inventory
    )
    features_by_element = {
        id(element): item for element, item in zip(elements, inventory, strict=True)
    }
    projections_by_element = {
        id(element): item for element, item in zip(elements, projected, strict=True)
    }
    tei = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    tei.append(
        stamp_header(
            title="The Expositor's Bible: The Gospel According to St. Mark",
            author="G. A. Chadwick",
            contributors=["William Robertson Nicoll (series editor)"],
            source_url="https://www.ccel.org/ccel/chadwick/mark.html",
            source_sha256=_sha(source_bytes),
            print_source=(
                "London: Hodder & Stoughton, 1896 (as stated by the retained "
                "CCEL rendering; no print collation)"
            ),
            rights_statement=(
                "Underlying text is public domain. CCEL permits parsing this ThML; "
                "do not sell CCEL files or derivatives of their formatting. "
                "Attribution to CCEL is included in README.source.md."
            ),
        )
    )
    text = tei_el("text")
    body = tei_el("body", {"xml:id": "mark-whole-body"})
    for child in source_body:
        if not isinstance(child.tag, str):
            continue
        converted = _convert_element(
            child, features_by_element, projections_by_element
        )
        body.append(converted)
        converted.tail = child.tail or ""
    text.append(body)
    tei.append(text)
    return (
        etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=True),
        projected,
    )


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    """Return the exact five non-manifest members for the generic seam."""

    source_manifest.verify()
    source_bytes = source_manifest.authority_path("retained-thml").read_bytes()
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    profile = json.loads(profile_bytes)
    profile_mapping = _profile_mapping(profile)
    inventory = _inventory(source_bytes, profile_mapping)
    if len(inventory) != 2405:
        raise ValueError("Mark source feature count is not 2,405")
    tei_bytes, projections = _tei(source_bytes, inventory, profile_mapping)
    crosswalk = []
    for ordinal, (feature, projection) in enumerate(
        zip(inventory, projections, strict=True), start=1
    ):
        crosswalk.append(
            {
                **feature,
                **projection,
                "disposition": "represented",
                "tei_selector": f"#{feature['tei_xml_id']}",
                "assertion": {
                    "id": f"mark-account-{ordinal:05d}",
                    "profile": _PROFILE_ID,
                    "role": "source-feature-accountability",
                    "layer": "witness-evidence",
                    "status": "represented",
                    "asserted_by": CONVERTER_ID,
                    "method": "exact-source-feature-crosswalk",
                    "evidence": [
                        {
                            "type": "source-selector",
                            "value": feature["source_selector"],
                        }
                    ],
                    "subject": {
                        "type": "tei-xml-id",
                        "value": feature["tei_xml_id"],
                    },
                    "destination": {
                        "type": "tei-xml-id",
                        "value": feature["tei_xml_id"],
                    },
                },
            }
        )
    accountability = {
        "contract": "ocd-mark-source-accountability-v1",
        "schema": "mark.source-accountability.schema.json",
        "profile_id": _PROFILE_ID,
        "source_scope": "complete ThML.body",
        "source_sha256": _sha(source_bytes),
        "feature_count": len(inventory),
        "attribute_disposition_count": sum(
            len(item["attribute_dispositions"]) for item in projections
        ),
        "deliberately_excluded_attribute_count": sum(
            disposition["disposition"] == "excluded"
            for item in projections
            for disposition in item["attribute_dispositions"]
        ),
        "omitted_feature_count": 0,
        "unresolved_feature_count": 0,
        "crosswalk": crosswalk,
    }
    authority_bindings = {
        str(item["name"]): {
            "path": item["path"],
            "sha256": item["sha256"],
            "bytes": item["bytes"],
            "role": item["role"],
        }
        for item in source_manifest.record["authorities"]
    }
    provenance = {
        "contract": "ocd-mark-candidate-provenance-v1",
        "status": "nonaccepted",
        "bounded_scope": "all content-bearing material in the exact retained ThML witness",
        "identity": {
            "work_id": _WORK_ID,
            "work": "The Expositor's Bible: The Gospel According to St. Mark",
            "expression_id": _EXPRESSION_ID,
            "expression": "G. A. Chadwick English text",
            "edition_id": _EDITION_ID,
            "identifier_scope": (
                "case-local noncanonical reconstruction identifiers; not promoted "
                "canonical IDs"
            ),
            "edition_evidence": (
                "CCEL rendering states London, Hodder & Stoughton, 1896"
            ),
            "acceptance_status": "not-accepted",
            "print_collation": "not performed",
        },
        "authorities": authority_bindings,
        "rights": {
            "status": "human-review-required-for-acceptance",
            "permission_authority": "ccel-permission",
            "license": (
                "public-domain text with CCEL derivative-formatting non-sale condition"
            ),
            "obligations": [
                "attribution-deliverable",
                "do-not-sell-ccel-formatting-derivatives",
            ],
            "attribution_deliverable": (
                "README.source.md contains sourced via CCEL.org"
            ),
        },
    }
    unresolved = [
        {
            "id": "mark-print-collation-not-performed",
            "profile": _PROFILE_ID,
            "subject": {"type": "edition-id", "value": _EDITION_ID},
            "question": (
                "Does a separately collated print copy support identity beyond the "
                "CCEL rendering's stated 1896 source?"
            ),
            "blocking_scope": "canonical-edition-identity-and-acceptance",
            "escalation": "human-review",
            "consequence": "candidate remains nonaccepted",
            "evidence": [{"type": "candidate-member", "value": "provenance.json"}],
        },
        {
            "id": "mark-rights-acceptance-review",
            "profile": _PROFILE_ID,
            "subject": {
                "type": "source-id",
                "value": "ccel-chadwick-mark-whole-thml",
            },
            "question": (
                "Are the exact CCEL permission distinctions and attribution "
                "deliverable sufficient for acceptance?"
            ),
            "blocking_scope": "rights-acceptance",
            "escalation": "human-review",
            "consequence": "candidate remains nonaccepted",
            "evidence": [
                {"type": "external-authority", "value": "ccel-permission"},
                {"type": "candidate-member", "value": "README.source.md"},
            ],
        },
    ]
    readme = (
        "# Source accountability\n\n"
        "This nonaccepted richer-TEI reconstruction is sourced via CCEL.org from "
        "the exact retained ThML witness. CCEL permits parsing the text, asks "
        "that derivatives of its formatting not be sold, and "
        "appreciates attribution. The stated 1896 print source has not been "
        "independently collated.\n"
    ).encode("utf-8")
    return {
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _json(accountability),
        "provenance.json": _json(provenance),
        "unresolved.jsonl": b"".join(_json(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
