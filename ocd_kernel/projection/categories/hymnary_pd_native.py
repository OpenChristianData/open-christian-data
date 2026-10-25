"""Exact retained-CSV Hymnary row profile; proposal until reviewed integration."""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

from lxml import etree

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.native_content import project_content
from ocd_kernel.projection.native_content_check import observe_content


NS = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
IDENTITY = {
    "work_id": "hymnary-pd",
    "textual_form_id": "hymnary-pd-multilingual",
    "edition_id": "hymnary-pd-retained-electronic-witness",
}
PROFILE = "ocd-hymns-hymnary-retained-csv-source-record-v1"
ASSEMBLER = "ocd-hymns-assembler-provisional-v1"
SOURCE_SHA = "09ab6edd41a96c205e1d171e36173cc9c28c32aa6809156c6bd10eeeba24a18b"
BOUND_MASTER_SHA = "5245ac29ce755bec9c6acffb3c18afbeff013c23b34b567abbb845460d95ff7f"
BODY_SHA = "41bc0c1a346a6ca029452c7a56d79fbaa9961084f68e1bf69a35a5b4c8cff17a"
SOURCE_MEMBER = "oldest_pd_instances.csv"
LABELS = (
    "Title", "Full text", "Author name", "Author birth", "Author death",
    "Year written", "Hymnal title", "Hymnal publication year",
)
CONTROLS = {
    "#hymnary-control-0008": "[source control U+0008]",
    "#hymnary-control-000f": "[source control U+000F]",
    "#hymnary-control-0010": "[source control U+0010]",
}
SPAN = re.compile(r"oldest_pd_instances\.csv#bytes-([0-9]+)-([0-9]+)\Z")
ENDING = {"CRLF": "\r\n", "LF": "\n", "CR": "\r"}


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _guard(data: bytes, identity: Mapping[str, str], language: str, source_url: str,
           source_sha256: str, retained_sha256: str, retained_path: Path) -> None:
    if dict(identity) != IDENTITY or language != "mul":
        raise PipelineError("Hymnary accepted identity or collection language differs")
    if source_url != "https://hymnary.org" or source_sha256 != SOURCE_SHA or retained_sha256 != SOURCE_SHA:
        raise PipelineError("Hymnary accepted retained source binding differs")
    if not retained_path.as_posix().replace("\\", "/").endswith("/raw/hymnary-pd/oldest_pd_instances.csv"):
        raise PipelineError("Hymnary accepted retained source path differs")
    if hashlib.sha256(data).hexdigest() != BOUND_MASTER_SHA:
        raise PipelineError("Hymnary exact accepted master differs")
    parts = data.split(b"</ns0:teiHeader>", 1)
    if len(parts) != 2 or hashlib.sha256(parts[1]).hexdigest() != BODY_SHA:
        raise PipelineError("Hymnary exact source-bound text subtree differs")


def _span(node: Any) -> str:
    value = node.get("corresp")
    match = SPAN.fullmatch(value or "")
    if match is None or int(match.group(1)) > int(match.group(2)):
        raise PipelineError("Hymnary original CSV field span differs")
    return value


def _literal_et(node: ET.Element) -> str:
    parts = [node.text or ""]
    for child in node:
        if child.tag == NS + "lb" and not list(child) and not (child.text or "").strip():
            value = ENDING.get(child.get("n"))
            if value is None or set(child.attrib) != {"n"}:
                raise PipelineError("Hymnary literal source line ending differs")
            parts.append(value)
        elif child.tag == NS + "g" and not list(child):
            value = CONTROLS.get(child.get("ref"))
            if value is None or child.text != value or set(child.attrib) != {"ref"}:
                raise PipelineError("Hymnary source control glyph differs")
            parts.append(value)
        else:
            raise PipelineError("Hymnary source field has unsupported nested content")
        parts.append(child.tail or "")
    return "".join(parts)


def _literal_lxml(node: etree._Element) -> str:
    text = node.text or ""
    for child in node:
        name = etree.QName(child).localname
        if name == "lb" and len(child) == 0 and not (child.text or "").strip():
            if dict(child.attrib) != {"n": child.get("n")} or child.get("n") not in ENDING:
                raise ValueError("Hymnary observed line-ending carrier differs")
            text += ENDING[child.get("n")]
        elif name == "g" and len(child) == 0:
            if dict(child.attrib) != {"ref": child.get("ref")} or child.text != CONTROLS.get(child.get("ref")):
                raise ValueError("Hymnary observed control-glyph carrier differs")
            text += child.text
        else:
            raise ValueError("Hymnary observed source field shape differs")
        text += child.tail or ""
    return text


def _fields_et(unit: ET.Element, sequence: int) -> tuple[list[dict[str, object]], list[str]]:
    if (unit.tag != NS + "div" or unit.get("type") != "hymn-record"
            or unit.get("n") != str(sequence) or unit.get(XML_ID) != f"hymnary-row-{sequence:05d}"
            or len(unit) != 3 or [child.tag for child in unit] != [NS + "head", NS + "ab", NS + "list"]):
        raise PipelineError("Hymnary source record boundary, order or identity differs")
    head, body, metadata = list(unit)
    if (head.get("n") != "1" or body.get("n") != "2" or body.get("type") != "hymn-text"
            or metadata.get("type") != "source-metadata" or len(metadata) != 6):
        raise PipelineError("Hymnary title, full text or metadata carriers differ")
    values = [_literal_et(head), _literal_et(body)]
    spans = [_span(head), _span(body)]
    for position, item in enumerate(metadata, 3):
        if item.tag != NS + "item" or item.get("n") != str(position) or len(item) != 2:
            raise PipelineError("Hymnary source metadata item differs")
        label, segment = list(item)
        if (label.tag != NS + "label" or (label.text or "") != LABELS[position - 1] + ": "
                or segment.tag != NS + "seg" or segment.get("type") != "source-field"
                or segment.get("n") != str(position)):
            raise PipelineError("Hymnary source metadata label or field differs")
        values.append(_literal_et(segment))
        spans.append(_span(segment))
    return [
        {"position": position, "label": label, "value": value}
        for position, (label, value) in enumerate(zip(LABELS, values, strict=True), 1)
    ], spans


def _fields_lxml(unit: etree._Element, sequence: int) -> tuple[list[dict[str, object]], list[str]]:
    children = list(unit)
    if (etree.QName(unit).localname != "div" or unit.get("type") != "hymn-record"
            or unit.get("n") != str(sequence) or unit.get(XML_ID) != f"hymnary-row-{sequence:05d}"
            or [etree.QName(child).localname for child in children] != ["head", "ab", "list"]):
        raise ValueError("Hymnary independently observed record shape differs")
    head, body, metadata = children
    if (head.get("n") != "1" or body.get("n") != "2" or body.get("type") != "hymn-text"
            or metadata.get("type") != "source-metadata" or len(metadata) != 6):
        raise ValueError("Hymnary independently observed source field carriers differ")
    values = [_literal_lxml(head), _literal_lxml(body)]
    spans = [_span(head), _span(body)]
    for position, item in enumerate(metadata, 3):
        item_children = list(item)
        if etree.QName(item).localname != "item" or item.get("n") != str(position) or len(item_children) != 2:
            raise ValueError("Hymnary independently observed item differs")
        label, segment = item_children
        if (etree.QName(label).localname != "label" or (label.text or "") != LABELS[position - 1] + ": "
                or etree.QName(segment).localname != "seg" or segment.get("type") != "source-field"
                or segment.get("n") != str(position)):
            raise ValueError("Hymnary independently observed label or field differs")
        values.append(_literal_lxml(segment))
        spans.append(_span(segment))
    fields = [{"position": index, "label": LABELS[index - 1], "value": values[index - 1]}
              for index in range(1, 9)]
    return fields, spans


def _row(unit: Any, fields: list[dict[str, object]], structure: dict[str, object], sequence: int,
         identity: Mapping[str, str], revision: str, title: str) -> dict[str, object]:
    text = fields[1]["value"]
    if not isinstance(text, str) or not text:
        raise PipelineError("Hymnary source Full text field is empty")
    return {
        **identity,
        "record_id": f"{IDENTITY['edition_id']}:csv:{sequence:05d}",
        "sequence": sequence,
        "category": "hymns",
        "language": "mul",
        "text": text,
        "representation_revision": revision,
        "locator": {"kind": "retained-csv-row", "row": sequence, "source_member": SOURCE_MEMBER},
        "provenance": {"edition_title": title},
        "notes": [],
        "references": [],
        "source_record_number": sequence,
        "source_fields": fields,
        "content_format": "ocd-native-content-v1",
        "structure": [structure],
    }


def _receipt(path: Path, rows: list[dict[str, object]], anchors: list[dict[str, object]]) -> dict[str, object]:
    from ocd_kernel.projection.categories.hymns import COMMON_SCHEMA_PATH, NATIVE_SCHEMA_PATH, SCHEMA_PATH

    return {
        "mapping_version": PROFILE,
        "assembler_version": ASSEMBLER,
        "master_sha256": hashlib.sha256(io_path(path).read_bytes()).hexdigest(),
        "source_binding": {"source_url": "https://hymnary.org", "source_sha256": SOURCE_SHA,
                           "retained_sha256": SOURCE_SHA},
        "policy_sha256": hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest(),
        "common_schema_sha256": hashlib.sha256(COMMON_SCHEMA_PATH.read_bytes()).hexdigest(),
        "native_schema_sha256": hashlib.sha256(NATIVE_SCHEMA_PATH.read_bytes()).hexdigest(),
        "output_sha256": _digest(rows),
        "row_count": len(rows),
        "anchors": anchors,
        "inventory": [{"kind": "retained-csv-witness", "record_count": 34895,
                       "field_count": 279160, "source_sha256": SOURCE_SHA,
                       "body_suffix_sha256": BODY_SHA}],
        "warnings": [
            {"kind": "source-claim", "message": "Provider public-domain selection is not per-row rights clearance."},
            {"kind": "source-structure", "message": "The full-text field has no asserted stanza divisions."},
            {"kind": "source-controls", "message": "Fifteen XML-forbidden control codepoints use visible placeholders."},
        ],
        "exclusions": [],
        "unsupported": [],
        "independent_check": {"status": "pending"},
    }


def project_hymnary_document(
    tei_path: Path, *, identity: Mapping[str, str], language: str,
    representation_revision: str, edition_title: str, source_url: str,
    source_sha256: str, retained_sha256: str, retained_path: Path,
) -> dict[str, object]:
    path = Path(tei_path)
    data = io_path(path).read_bytes()
    _guard(data, identity, language, source_url, source_sha256, retained_sha256, retained_path)
    root = ET.fromstring(data)
    body = root.find(f"./{NS}text/{NS}body")
    if body is None or len(body) != 34895:
        raise PipelineError("Hymnary complete source-record count differs")
    rows: list[dict[str, object]] = []
    anchors: list[dict[str, object]] = []
    for sequence, unit in enumerate(body, 1):
        fields, spans = _fields_et(unit, sequence)
        structure = project_content(unit, source_profile=PROFILE)
        row = _row(unit, fields, structure, sequence, identity, representation_revision, edition_title)
        rows.append(row)
        anchors.append({"record_id": row["record_id"], "source_xml_id": unit.get(XML_ID),
                        "source_order": sequence, "original_field_spans": spans,
                        "text_sha256": hashlib.sha256(row["text"].encode("utf-8")).hexdigest(),
                        "text_length": len(row["text"])})
    receipt = _receipt(path, rows, anchors)
    return {"rows": rows, "receipt": receipt, "mapping_version": PROFILE,
            "assembler_version": ASSEMBLER, "master_sha256": receipt["master_sha256"],
            "anchors": anchors, "inventory": receipt["inventory"], "warnings": receipt["warnings"],
            "exclusions": [], "unsupported": [], "independent_check": receipt["independent_check"]}


def verify_hymnary_document(
    tei_path: Path, rows: list[dict[str, object]], receipt: Mapping[str, object], *,
    identity: Mapping[str, str], language: str, representation_revision: str,
    edition_title: str, source_url: str, source_sha256: str,
    retained_sha256: str, retained_path: Path,
) -> list[str]:
    try:
        path = Path(tei_path)
        data = io_path(path).read_bytes()
        _guard(data, identity, language, source_url, source_sha256, retained_sha256, retained_path)
        root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        body = root.find(f"./{NS}text/{NS}body")
        if body is None or len(body) != 34895:
            raise ValueError("Hymnary observed complete source-record count differs")
        expected: list[dict[str, object]] = []
        anchors: list[dict[str, object]] = []
        for sequence, unit in enumerate(body, 1):
            fields, spans = _fields_lxml(unit, sequence)
            structure, _ = observe_content(etree.tostring(unit), source_profile=PROFILE)
            row = _row(unit, fields, structure, sequence, identity, representation_revision, edition_title)
            expected.append(row)
            anchors.append({"record_id": row["record_id"], "source_xml_id": unit.get(XML_ID),
                            "source_order": sequence, "original_field_spans": spans,
                            "text_sha256": hashlib.sha256(row["text"].encode("utf-8")).hexdigest(),
                            "text_length": len(row["text"])})
        errors = []
        if rows != expected:
            errors.append("Hymnary independent source-record rows differ")
        if dict(receipt) != _receipt(path, expected, anchors):
            errors.append("Hymnary independent source-record receipt differs")
        from ocd_kernel.projection.categories.hymns import _validator
        validator = _validator()
        for sequence, row in enumerate(rows, 1):
            for problem in validator.iter_errors(row):
                errors.append(f"Hymnary schema row {sequence}: {problem.message}")
        return errors
    except (OSError, ValueError, TypeError, KeyError, PipelineError, etree.XMLSyntaxError) as exc:
        return [str(exc)]
