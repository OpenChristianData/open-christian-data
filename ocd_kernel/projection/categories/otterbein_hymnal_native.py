"""Exact PG16455 hymn and historical apparatus source units.

The accepted TEI retains 548 numbered hymns, surrounding historical units,
and Project Gutenberg's electronic wrapper. Public rows follow the source
units in order. The wrapper stays privately inventoried and credited in the
paired notices. No hymn, stanza, or contributor assignment is inferred.
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
    "work_id": "otterbein-hymnal",
    "textual_form_id": "otterbein-hymnal-gutenberg-retained",
    "edition_id": "otterbein-hymnal-gutenberg-electronic",
}
REVISION = "otterbein-pg16455-electronic-accepted-v1"
MASTER_SHA256 = "7bc0ac5b438cfb41e3b06b072d33639e0f4c667d930a13d598e87de3415ec9d0"
SOURCE_SHA256 = "49221d85bf34139c6ddad71dcd31076da47236042cf346fd93da39da1a2d7362"
SOURCE_URL = "https://www.gutenberg.org/cache/epub/16455/pg16455-h.zip"
PROFILE = "ocd-pg16455-complete-hymnal-native-source-units-v1"
SCHEMA = hymns.SCHEMA_PATH.with_name("otterbein-hymnal-native.schema.json")
NS = f"{{{hymns.TEI_NS}}}"
XML_ID = hymns.XML_ID


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
        raise PipelineError("PG16455 accepted identity, revision, or source binding differs")
    raw = io_path(tei_path).read_bytes()
    if _digest(raw) != MASTER_SHA256:
        raise PipelineError("PG16455 accepted master bytes differ")
    if _digest(io_path(retained_path).read_bytes()) != SOURCE_SHA256:
        raise PipelineError("PG16455 retained HTML bytes differ")
    return raw


def _parse_et(data: bytes) -> ET.Element:
    if any(token in data.upper() for token in (b"<!DOCTYPE", b"<!ENTITY", b"<!--")):
        raise PipelineError("PG16455 declarations or comments differ")
    if re.search(rb"<\?(?!xml(?:\s|\?>))", data, flags=re.I):
        raise PipelineError("PG16455 processing instruction differs")
    return ET.fromstring(data)


def _parse_lxml(data: bytes) -> etree._Element:
    return etree.fromstring(data, etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True,
        remove_comments=False, remove_pis=False,
    ))


def _ordered_units(root: Any) -> list[tuple[int, Any, str]]:
    if root.tag != NS + "TEI" or [child.tag for child in root] != [NS + "teiHeader", NS + "text"]:
        raise PipelineError("PG16455 TEI envelope differs")
    text = root[1]
    if len(text) != 1 or text[0].tag != NS + "body" or len(text[0]) != 1:
        raise PipelineError("PG16455 text/body envelope differs")
    container = text[0][0]
    if (container.tag != NS + "div" or container.get("type") != "complete-source-work"
            or container.get(XML_ID) != "otterbein-hymnal-complete-source-work"):
        raise PipelineError("PG16455 complete source body differs")
    units = list(container)
    if len(units) != 592:
        raise PipelineError("PG16455 592 direct source units differ")
    result: list[tuple[int, Any, str]] = []
    hymn_numbers: list[int] = []
    for order, unit in enumerate(units, 1):
        if unit.tag != NS + "div" or unit.get("type") != "source-unit" or len(unit) != 1:
            raise PipelineError(f"PG16455 source unit {order} shape differs")
        child = unit[0]
        if order == 1:
            if (unit.get(XML_ID) != "otterbein-unit-ob-pg-header"
                    or child.tag != NS + "div" or child.get("type") != "gutenberg-header"
                    or child.get(XML_ID) != "ob-pg-header"):
                raise PipelineError("PG16455 provider header differs")
            kind = "provider-wrapper"
        elif order == 592:
            if (unit.get(XML_ID) != "otterbein-unit-ob-pg-footer"
                    or child.tag != NS + "div" or child.get("type") != "gutenberg-footer"
                    or child.get(XML_ID) != "ob-pg-footer"):
                raise PipelineError("PG16455 provider footer differs")
            kind = "provider-wrapper"
        elif child.tag == NS + "div" and child.get("type") == "hymn":
            number = child.get("n") or ""
            if (not number.isdecimal() or child.get(XML_ID) != f"ob-h{number}"
                    or unit.get(XML_ID) != f"otterbein-unit-ob-h{number}"):
                raise PipelineError(f"PG16455 source hymn {order} number or identity differs")
            hymn_numbers.append(int(number))
            kind = "source-labeled-hymn"
        else:
            kind = "historical-apparatus"
        result.append((order, unit, kind))
    if (hymn_numbers != list(range(1, 549))
            or sum(kind == "historical-apparatus" for _, _, kind in result) != 42):
        raise PipelineError("PG16455 numbered hymn or apparatus scope differs")
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
    for order, unit, kind in units:
        descendants = list(unit.iter())
        for node in descendants:
            if node in unit_order:
                raise PipelineError("PG16455 source units overlap")
            unit_order[node] = order
        source_units.append({
            "source_order": order, "kind": kind, "tei_path": paths[unit],
            "element_count": len(descendants),
            "literal_text_sha256": _digest("".join(unit.itertext()).encode("utf-8")),
        })
        if kind == "provider-wrapper":
            exclusions.append({
                "source_order": order, "tei_path": paths[unit],
                "reason": "Project Gutenberg electronic wrapper retained with source notices, not projected as historical hymnal text",
            })
    inventory: list[dict] = []
    for node in root.iter():
        in_header = "/teiHeader[1]" in paths[node]
        order = unit_order.get(node)
        kind = source_units[order - 1]["kind"] if order is not None else None
        role = ("header-metadata" if in_header else
                "provider-wrapper-private" if kind == "provider-wrapper" else
                "public-source-unit" if kind else "structural-container")
        inventory.append({
            "tei_path": paths[node], "tag": _local(node), "role": role,
            "source_order": order,
            "attributes": {hymns._attribute_name(key): value for key, value in sorted(node.attrib.items())},
            "text_sha256": _digest((node.text or "").encode("utf-8")),
            "tail_sha256": _digest((node.tail or "").encode("utf-8")),
        })
    if len(inventory) != 24891:
        raise PipelineError("PG16455 complete header/body node accounting differs")
    return inventory, source_units, exclusions


def _public_clone(unit: Any) -> tuple[Any, int, int]:
    public = copy.deepcopy(unit)
    numbers = 0
    pages = 0
    for node in public.iter():
        if node.tag == NS + "num":
            if dict(node.attrib) not in ({"type": "hymn-number"}, {"type": "source-reference-number"}):
                raise PipelineError("PG16455 source number shape differs")
            node.tag = NS + "seg"
            node.set("subtype", "source-element:num")
            numbers += 1
        elif node.tag == NS + "pb":
            if node.get("type") != "source-comment":
                raise PipelineError("PG16455 source page-comment shape differs")
            node.attrib.pop("type")
            pages += 1
    return public, numbers, pages


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
            raise PipelineError(f"PG16455 source unit row {index} schema: {errors[0].message}")


def _projected(root: Any, *, language: str, revision: str, edition_title: str,
               observe: Callable[[Any], dict[str, Any]]) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], dict]:
    units = _ordered_units(root)
    paths = _paths(root)
    inventory, source_units, exclusions = _private_accounting(root, paths, units)
    rows: list[dict] = []
    anchors: list[dict] = []
    number_count = 0
    page_count = 0
    for order, unit, kind in units:
        if kind == "provider-wrapper":
            continue
        public, numbers, pages = _public_clone(unit)
        number_count += numbers
        page_count += pages
        structure = observe(public)
        readable = readable_content(structure)
        locator = {"kind": kind, "source_order": order}
        if kind == "source-labeled-hymn":
            locator["source_number"] = int(unit[0].get("n"))
        row = {
            **IDENTITY,
            "record_id": f"{IDENTITY['edition_id']}:source-unit:{order:04d}",
            "sequence": len(rows) + 1, "category": "hymns", "language": language,
            "text": readable, "representation_revision": revision,
            "locator": locator, "provenance": {"edition_title": edition_title},
            "notes": [], "references": [], "source_unit_kind": kind,
            "content_format": "ocd-native-content-v1", "structure": [structure],
        }
        rows.append(row)
        anchors.append({
            "record_id": row["record_id"], "source_order": order,
            "tei_path": paths[unit], "source_unit_kind": kind,
            "source_number": locator.get("source_number"),
            "text_sha256": _digest(readable.encode("utf-8")),
            "structure_sha256": _digest(hymns._canonical(structure)),
        })
    counts = {
        "source_units": len(units), "public_rows": len(rows),
        "source_labeled_hymns": sum(row["source_unit_kind"] == "source-labeled-hymn" for row in rows),
        "historical_apparatus": sum(row["source_unit_kind"] == "historical-apparatus" for row in rows),
        "empty_readable_apparatus": sum(row["source_unit_kind"] == "historical-apparatus" and not row["text"] for row in rows),
        "excluded_provider_wrappers": len(exclusions),
        "retained_source_number_tags": number_count,
        "retained_source_page_comments": page_count,
    }
    if counts != {
        "source_units": 592, "public_rows": 590,
        "source_labeled_hymns": 548, "historical_apparatus": 42,
        "empty_readable_apparatus": 13,
        "excluded_provider_wrappers": 2,
        "retained_source_number_tags": 927,
        "retained_source_page_comments": 394,
    }:
        raise PipelineError(f"PG16455 source-unit disposition differs: {counts}")
    binding = {
        "source_url": SOURCE_URL, "source_sha256": SOURCE_SHA256,
        "retained_sha256": SOURCE_SHA256, "source_unit_counts": counts,
    }
    return rows, anchors, inventory, source_units, exclusions, binding


def _producer_structure(unit: ET.Element) -> dict[str, Any]:
    return project_content(unit)


def _checker_structure(unit: etree._Element) -> dict[str, Any]:
    structure, _ = observe_content(etree.tostring(unit, with_tail=False))
    return structure


def _receipt(rows: list[dict], anchors: list[dict], inventory: list[dict],
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
            {"reason": "548 numbered hymns and 42 historical apparatus units follow the retained source in order; the byline outside hymn 186 remains unassigned"},
            {"reason": "source number elements and page-comment markers are represented by native segments and page breaks with original TEI semantics inventoried privately"},
            {"reason": "source CSS class identifiers remain opaque; no CSS declarations or source layout definitions are included"},
        ],
        "exclusions": exclusions, "unsupported": [],
        "independent_check": {"status": "pending"},
    }


def project_otterbein_document(
    tei_path: Path, *, identity: Mapping[str, str], language: str,
    representation_revision: str, edition_title: str, source_url: str,
    source_sha256: str, retained_sha256: str, retained_path: Path,
) -> dict[str, Any]:
    raw = _guard(Path(tei_path), identity=identity, language=language,
                 representation_revision=representation_revision,
                 source_url=source_url, source_sha256=source_sha256,
                 retained_sha256=retained_sha256, retained_path=retained_path)
    root = _parse_et(raw)
    rows, anchors, inventory, source_units, exclusions, binding = _projected(
        root, language=language, revision=representation_revision,
        edition_title=edition_title, observe=_producer_structure,
    )
    _validate_rows(rows)
    receipt = _receipt(rows, anchors, inventory, source_units, exclusions, binding)
    return {
        "rows": rows, "receipt": receipt,
        "mapping_version": PROFILE, "assembler_version": hymns.ASSEMBLER_VERSION,
        "master_sha256": MASTER_SHA256, "source_binding": binding,
        "anchors": anchors, "inventory": inventory,
        "warnings": receipt["warnings"], "exclusions": exclusions,
        "unsupported": [], "independent_check": receipt["independent_check"],
    }


def verify_otterbein_document(
    tei_path: Path, rows: list[dict[str, Any]], receipt: Mapping[str, Any], *,
    identity: Mapping[str, str], language: str, representation_revision: str,
    edition_title: str, source_url: str, source_sha256: str,
    retained_sha256: str, retained_path: Path,
) -> list[str]:
    try:
        raw = _guard(Path(tei_path), identity=identity, language=language,
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
            errors.append("PG16455 independently observed source-unit rows differ")
        if dict(receipt) != _receipt(expected, anchors, inventory, source_units, exclusions, binding):
            errors.append("PG16455 independently observed source-unit receipt differs")
        _validate_rows(rows)
        return errors
    except (PipelineError, OSError, ValueError, TypeError, KeyError,
            ET.ParseError, etree.XMLSyntaxError, jsonschema.ValidationError) as exc:
        return [str(exc)]
