"""Exact PG76498 hymnal source units, including historical apparatus.

The accepted TEI master is authoritative. Native rows preserve its source-labeled
hymns (including paragraph chants) and historical non-hymn carriers in order.
Project Gutenberg's electronic header/license carriers stay in private source
accounting and the paired notices. No stanza, contributor, or title is inferred.
"""

from __future__ import annotations
from ocd_kernel.projection.native_content_check import projection_validator

import copy
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Mapping

import jsonschema
from lxml import etree
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.native_content import project_content, readable_content
from ocd_kernel.projection.native_content_check import observe_content

from . import hymns


IDENTITY = {
    "work_id": "evangelical-lutheran-hymn-book-abridged",
    "textual_form_id": "evangelical-lutheran-hymn-book-abridged-gutenberg-retained",
    "edition_id": "evangelical-lutheran-hymn-book-abridged-gutenberg-electronic",
}
REVISION = "l742-complete-electronic-v1"
MASTER_SHA256 = "cb59db6ff508dac7c289727e26fdb4cdd420568d5fc87df69d6dc8bb0eb8aa26"
SOURCE_SHA256 = "c13e936c8b681c23ca402237581d9d9208ad0b8a34465315ea8c9138da5b6d3b"
SOURCE_URL = "https://www.gutenberg.org/cache/epub/76498/pg76498-h.zip"
IMAGE_SHA256 = "089ff870cdf7c780fb50540f4b53da8aac0d8dcf47e188566f13b7b462002ad2"
PROFILE = "ocd-pg76498-complete-hymnal-native-source-units-v1"
SCHEMA = hymns.SCHEMA_PATH.with_name("lutheran-hymnbook-native.schema.json")
NS = f"{{{hymns.TEI_NS}}}"
XML_ID = hymns.XML_ID
_STYLE_REWRITE = {
    "source-style:margin-top:0": None,
    "source-style:padding-left: 7.5ex": None,
    "source-style:text-align:center": None,
    "class:figcenter class:titlepage class:illowp68 source-style:max-width: 6.25em;":
        "class:figcenter class:titlepage class:illowp68",
}
_IMAGE_ATTRIBUTES = {
    "url": "images/concordia.jpg",
    XML_ID: "img_images_concordia.jpg",
    "n": "img_images_concordia.jpg",
    "rend": "class:w100",
}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _local(node: Any) -> str:
    return node.tag.rsplit("}", 1)[-1]


def _guard(
    tei_path: Path, *, identity: Mapping[str, str], language: str,
    representation_revision: str, source_url: str, source_sha256: str,
    retained_sha256: str, retained_path: Path,
) -> bytes:
    if (dict(identity) != IDENTITY or language != "en" or representation_revision != REVISION
            or source_url != SOURCE_URL or source_sha256 != SOURCE_SHA256
            or retained_sha256 != SOURCE_SHA256):
        raise PipelineError("PG76498 accepted identity, revision, or source binding differs")
    raw = io_path(tei_path).read_bytes()
    if _digest(raw) != MASTER_SHA256:
        raise PipelineError("PG76498 accepted master bytes differ")
    if _digest(io_path(retained_path).read_bytes()) != SOURCE_SHA256:
        raise PipelineError("PG76498 retained HTML bytes differ")
    image = tei_path.parent / "images/concordia.jpg"
    retained_image = retained_path.parent / "images/concordia.jpg"
    if (_digest(io_path(image).read_bytes()) != IMAGE_SHA256
            or _digest(io_path(retained_image).read_bytes()) != IMAGE_SHA256):
        raise PipelineError("PG76498 retained Concordia support image bytes differ")
    return raw


def _parse_et(data: bytes) -> ET.Element:
    if any(token in data.upper() for token in (b"<!DOCTYPE", b"<!ENTITY", b"<!--")):
        raise PipelineError("PG76498 declarations or comments differ")
    if re.search(rb"<\?(?!xml(?:\s|\?>))", data, flags=re.I):
        raise PipelineError("PG76498 processing instruction differs")
    return ET.fromstring(data)


def _parse_lxml(data: bytes) -> etree._Element:
    return etree.fromstring(data, etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True,
        remove_comments=False, remove_pis=False,
    ))


def _ordered_units(root: Any) -> list[tuple[int, Any, int | None, int, Any, str]]:
    if root.tag != NS + "TEI" or [child.tag for child in root] != [NS + "teiHeader", NS + "text"]:
        raise PipelineError("PG76498 TEI envelope differs")
    text = root[1]
    if len(text) != 1 or text[0].tag != NS + "body" or len(text[0]) != 1:
        raise PipelineError("PG76498 text/body envelope differs")
    container = text[0][0]
    if container.tag != NS + "div" or container.get("type") != "source-html-body":
        raise PipelineError("PG76498 complete source body differs")
    groups = list(container)
    if len(groups) != 55:
        raise PipelineError("PG76498 55 source groups differ")
    result: list[tuple[int, Any, int | None, int, Any, str]] = []
    hymn_numbers: list[int] = []
    order = 0
    for group_index, group in enumerate(groups):
        expected_type = "front-matter" if group_index == 0 else (
            "provider-footer" if group_index == 54 else "source-section"
        )
        number = group_index if 1 <= group_index <= 53 else None
        if (group.tag != NS + "div" or group.get("type") != expected_type
                or group.get("n") != (str(number) if number is not None else None)):
            raise PipelineError(f"PG76498 source group {group_index} differs")
        for within, unit in enumerate(group, 1):
            order += 1
            if unit.tag != NS + "div" or unit.get("type") not in {"hymn", "source-block-carrier"}:
                raise PipelineError(f"PG76498 source unit {order} shape differs")
            if unit.get("type") == "hymn":
                if number is None or not (unit.get("n") or "").isdecimal():
                    raise PipelineError(f"PG76498 source hymn {order} numbering differs")
                hymn_numbers.append(int(unit.get("n")))
            kind = "source-labeled-hymn" if unit.get("type") == "hymn" else "historical-apparatus"
            if group_index == 0 and within == 1:
                if len(unit) != 1 or unit[0].get("type") != "provider-header":
                    raise PipelineError("PG76498 provider header boundary differs")
                kind = "provider-wrapper"
            elif group_index == 54:
                if within != 1 or len(unit) != 1 or unit[0].get("type") != "provider-license":
                    raise PipelineError("PG76498 provider footer boundary differs")
                kind = "provider-wrapper"
            result.append((order, group, number, within, unit, kind))
    if (order != 1141 or hymn_numbers != list(range(1, 595))
            or sum(kind == "historical-apparatus" for *_, kind in result) != 545
            or sum(kind == "provider-wrapper" for *_, kind in result) != 2):
        raise PipelineError("PG76498 complete numbered and apparatus source-unit scope differs")
    return result


def _paths(root: Any) -> dict[Any, str]:
    paths = {root: "/TEI[1]"}
    for parent in root.iter():
        counts: dict[str, int] = {}
        for child in parent:
            tag = _local(child)
            counts[tag] = counts.get(tag, 0) + 1
            paths[child] = f"{paths[parent]}/{tag}[{counts[tag]}]"
    return paths


def _private_accounting(root: Any, paths: Mapping[Any, str], units: list[tuple]) -> tuple[list[dict], list[dict], list[dict]]:
    unit_order: dict[Any, int] = {}
    source_units: list[dict] = []
    exclusions: list[dict] = []
    for order, group, number, within, unit, kind in units:
        descendants = list(unit.iter())
        for node in descendants:
            if node in unit_order:
                raise PipelineError("PG76498 source units overlap")
            unit_order[node] = order
        item = {
            "source_order": order, "group_type": group.get("type"),
            "section_number": number, "within_group": within,
            "kind": kind, "tei_path": paths[unit],
            "element_count": len(descendants),
            "literal_text_sha256": _digest("".join(unit.itertext()).encode("utf-8")),
        }
        source_units.append(item)
        if kind == "provider-wrapper":
            exclusions.append({
                "source_order": order, "tei_path": paths[unit],
                "reason": "Project Gutenberg electronic wrapper retained with source notices, not projected as historical hymnal text",
            })
    inventory: list[dict] = []
    for node in root.iter():
        tag = _local(node)
        in_header = "/teiHeader[1]" in paths[node]
        order = unit_order.get(node)
        kind = source_units[order - 1]["kind"] if order is not None else None
        role = ("header-metadata" if in_header else
                "provider-wrapper-private" if kind == "provider-wrapper" else
                "public-source-unit" if kind else "structural-container")
        inventory.append({
            "tei_path": paths[node], "tag": tag, "role": role,
            "source_order": order,
            "attributes": {hymns._attribute_name(key): value for key, value in sorted(node.attrib.items())},
            "text_sha256": _digest((node.text or "").encode("utf-8")),
            "tail_sha256": _digest((node.tail or "").encode("utf-8")),
        })
    if len(inventory) != 37379 or len(unit_order) < 30000:
        raise PipelineError("PG76498 complete header/body node accounting differs")
    return inventory, source_units, exclusions


def _public_clone(unit: Any) -> tuple[Any, int, int]:
    public = copy.deepcopy(unit)
    styles = 0
    graphics = 0
    for node in public.iter():
        value = node.get("rend")
        if value in _STYLE_REWRITE:
            replacement = _STYLE_REWRITE[value]
            if replacement is None:
                node.attrib.pop("rend")
            else:
                node.set("rend", replacement)
            styles += 1
        elif value and "source-style:" in value:
            raise PipelineError("PG76498 unexpected source layout declaration")
        if node.tag == NS + "graphic":
            if dict(node.attrib) != _IMAGE_ATTRIBUTES:
                raise PipelineError("PG76498 Concordia graphic carrier differs")
            node.attrib.pop("rend")
            graphics += 1
    return public, styles, graphics


def _row(order: int, group: Any, number: int | None, within: int, unit: Any,
         kind: str, structure: dict, text: str, *, sequence: int,
         language: str, revision: str, edition_title: str) -> dict[str, Any]:
    if kind == "source-labeled-hymn":
        locator = {"kind": kind, "source_order": order,
                   "source_number": int(unit.get("n")), "section_number": number}
    else:
        locator = {"kind": kind, "source_order": order,
                   "source_group": group.get("type"), "section_number": number,
                   "within_group": within}
    return {
        **IDENTITY,
        "record_id": f"{IDENTITY['edition_id']}:source-unit:{order:04d}",
        "sequence": sequence, "category": "hymns", "language": language,
        "text": text, "representation_revision": revision,
        "locator": locator, "provenance": {"edition_title": edition_title},
        "notes": [], "references": [], "source_unit_kind": kind,
        "content_format": "ocd-native-content-v1", "structure": [structure],
    }


def _validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    common = json.loads(hymns.COMMON_SCHEMA_PATH.read_text(encoding="utf-8"))
    native = json.loads(hymns.NATIVE_SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = Registry().with_resources([
        (common["$id"], Resource.from_contents(common, default_specification=DRAFT202012)),
        (native["$id"], Resource.from_contents(native, default_specification=DRAFT202012)),
    ])
    jsonschema.Draft202012Validator.check_schema(schema)
    return projection_validator(schema, registry=registry)


def _validate_rows(rows: list[dict]) -> None:
    validator = _validator()
    for index, row in enumerate(rows, 1):
        errors = sorted(validator.iter_errors(row), key=lambda error: list(error.path))
        if errors:
            raise PipelineError(f"PG76498 source unit row {index} schema: {errors[0].message}")


def _projected(
    root: Any, *, language: str, revision: str, edition_title: str,
    observe: Callable[[Any], dict[str, Any]],
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], dict]:
    units = _ordered_units(root)
    paths = _paths(root)
    inventory, source_units, exclusions = _private_accounting(root, paths, units)
    rows: list[dict] = []
    anchors: list[dict] = []
    styles = 0
    graphics = 0
    for order, group, number, within, unit, kind in units:
        if kind == "provider-wrapper":
            continue
        public, removed_styles, removed_graphics = _public_clone(unit)
        styles += removed_styles
        graphics += removed_graphics
        structure = observe(public)
        text = readable_content(structure)
        row = _row(order, group, number, within, unit, kind, structure, text,
                   sequence=len(rows) + 1, language=language,
                   revision=revision, edition_title=edition_title)
        rows.append(row)
        anchors.append({
            "record_id": row["record_id"], "source_order": order,
            "tei_path": paths[unit], "source_unit_kind": kind,
            "source_number": int(unit.get("n")) if kind == "source-labeled-hymn" else None,
            "text_sha256": _digest(text.encode("utf-8")),
            "structure_sha256": _digest(hymns._canonical(structure)),
        })
    counts = {
        "source_units": len(units), "public_rows": len(rows),
        "source_labeled_hymns": sum(row["source_unit_kind"] == "source-labeled-hymn" for row in rows),
        "historical_apparatus": sum(row["source_unit_kind"] == "historical-apparatus" for row in rows),
        "empty_readable_apparatus": sum(row["source_unit_kind"] == "historical-apparatus" and not row["text"] for row in rows),
        "excluded_provider_wrappers": len(exclusions),
        "removed_layout_declarations": styles,
        "removed_graphic_class": graphics,
    }
    if counts != {
        "source_units": 1141, "public_rows": 1139,
        "source_labeled_hymns": 594, "historical_apparatus": 545,
        "empty_readable_apparatus": 42, "excluded_provider_wrappers": 2,
        "removed_layout_declarations": 3, "removed_graphic_class": 1,
    }:
        raise PipelineError(f"PG76498 source-unit disposition differs: {counts}")
    binding = {
        "source_url": SOURCE_URL, "source_sha256": SOURCE_SHA256,
        "retained_sha256": SOURCE_SHA256, "support_image_sha256": IMAGE_SHA256,
        "source_unit_counts": counts,
    }
    return rows, anchors, inventory, source_units, exclusions, binding


def _producer_structure(unit: ET.Element) -> dict[str, Any]:
    return project_content(unit)


def _checker_structure(unit: etree._Element) -> dict[str, Any]:
    structure, _ = observe_content(etree.tostring(unit, with_tail=False))
    return structure


def _receipt(path: Path, rows: list[dict], anchors: list[dict], inventory: list[dict],
             source_units: list[dict], exclusions: list[dict], binding: dict) -> dict[str, Any]:
    return {
        "mapping_version": PROFILE,
        "assembler_version": hymns.ASSEMBLER_VERSION,
        "master_sha256": MASTER_SHA256,
        "source_binding": binding,
        "policy_sha256": _digest(SCHEMA.read_bytes()),
        "common_schema_sha256": _digest(hymns.COMMON_SCHEMA_PATH.read_bytes()),
        "native_schema_sha256": _digest(hymns.NATIVE_SCHEMA_PATH.read_bytes()),
        "output_sha256": _digest(hymns._canonical(rows)),
        "row_count": len(rows), "anchors": anchors,
        "inventory": inventory, "source_units": source_units,
        "warnings": [
            {"reason": "594 numbered source-labeled pieces include ten paragraph chants; stanza boundaries are not inferred"},
            {"reason": "42 historical apparatus carriers have no readable text but retain native page/structural content"},
            {"reason": "three historical-carrier layout declarations and one graphic class remain in private master accounting only; two other layout declarations are in the excluded provider wrapper"},
            {"reason": "Concordia support-image bytes are source-bound but not included in public data"},
        ],
        "exclusions": exclusions, "unsupported": [],
        "independent_check": {"status": "pending"},
    }


def project_lutheran_document(
    tei_path: Path, *, identity: Mapping[str, str], language: str,
    representation_revision: str, edition_title: str, source_url: str,
    source_sha256: str, retained_sha256: str, retained_path: Path,
) -> dict[str, Any]:
    path = Path(tei_path)
    raw = _guard(path, identity=identity, language=language,
                 representation_revision=representation_revision,
                 source_url=source_url, source_sha256=source_sha256,
                 retained_sha256=retained_sha256, retained_path=retained_path)
    root = _parse_et(raw)
    rows, anchors, inventory, source_units, exclusions, binding = _projected(
        root, language=language, revision=representation_revision,
        edition_title=edition_title, observe=_producer_structure,
    )
    _validate_rows(rows)
    receipt = _receipt(path, rows, anchors, inventory, source_units, exclusions, binding)
    return {
        "rows": rows, "receipt": receipt,
        "mapping_version": PROFILE, "assembler_version": hymns.ASSEMBLER_VERSION,
        "master_sha256": MASTER_SHA256, "source_binding": binding,
        "anchors": anchors, "inventory": inventory,
        "warnings": receipt["warnings"], "exclusions": exclusions,
        "unsupported": [], "independent_check": receipt["independent_check"],
    }


def verify_lutheran_document(
    tei_path: Path, rows: list[dict[str, Any]], receipt: Mapping[str, Any], *,
    identity: Mapping[str, str], language: str, representation_revision: str,
    edition_title: str, source_url: str, source_sha256: str,
    retained_sha256: str, retained_path: Path,
) -> list[str]:
    try:
        path = Path(tei_path)
        raw = _guard(path, identity=identity, language=language,
                     representation_revision=representation_revision,
                     source_url=source_url, source_sha256=source_sha256,
                     retained_sha256=retained_sha256, retained_path=retained_path)
        root = _parse_lxml(raw)
        expected, anchors, inventory, source_units, exclusions, binding = _projected(
            root, language=language, revision=representation_revision,
            edition_title=edition_title, observe=_checker_structure,
        )
        errors = []
        if rows != expected:
            errors.append("PG76498 independently observed source-unit rows differ")
        if dict(receipt) != _receipt(path, expected, anchors, inventory, source_units, exclusions, binding):
            errors.append("PG76498 independently observed source-unit receipt differs")
        _validate_rows(rows)
        return errors
    except (PipelineError, OSError, ValueError, TypeError, KeyError,
            ET.ParseError, etree.XMLSyntaxError, jsonschema.ValidationError) as exc:
        return [str(exc)]
