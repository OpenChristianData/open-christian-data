"""Closed projection for the accepted Daily Light SWORD electronic witness."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import jsonschema
from lxml import etree
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from ocd_kernel.library._common import PipelineError

ROOT = Path(__file__).resolve().parents[3]
MASTER_SHA = "70b2c9e06920fe39a9b3b72ef001404d22569d47c813c75829336e535a7e3bb3"
PROFILE = "ocd-daily-light-sword-366-days-732-periods-v1"
NAMESPACE = "http://www.tei-c.org/ns/1.0"
TEI = "{" + NAMESPACE + "}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SEPARATOR = "\u001f"
SCHEMA = ROOT / "schemas/v2/categories/devotionals.schema.json"
COMMON = ROOT / "schemas/v2/public-row.schema.json"
IDENTITY = {"work_id": "daily-light", "textual_form_id": "daily-light-retained-electronic",
            "edition_id": "daily-light-retained-electronic-witness"}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _validate_rows(rows: list[dict]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    common = json.loads(COMMON.read_text(encoding="utf-8"))
    registry = Registry().with_resource(common["$id"], Resource.from_contents(common, default_specification=DRAFT202012))
    validator = jsonschema.Draft202012Validator(schema, registry=registry)
    for row in rows:
        problems = list(validator.iter_errors(row))
        if problems:
            raise PipelineError(f"Daily Light invalid period {row['sequence']}: {problems[0].message}")


def _render_et(node: ET.Element) -> str:
    parts: list[str] = []

    def visit(current: ET.Element) -> None:
        if current.text:
            parts.append(current.text)
        for child in current:
            if child.tag == TEI + "lb":
                if child.text or list(child):
                    raise PipelineError("Daily Light line-break carrier contains text")
                parts.append(SEPARATOR)
            elif child.tag in (TEI + "hi", TEI + "ref"):
                visit(child)
            else:
                raise PipelineError(f"Daily Light unsupported inline element: {child.tag}")
            if child.tail:
                parts.append(child.tail)

    visit(node)
    return "\n".join(" ".join(part.split()) for part in "".join(parts).split(SEPARATOR)).strip("\n")


def _periods_et(body: ET.Element) -> tuple[list[tuple[str, str, ET.Element]], dict[str, int]]:
    result: list[tuple[str, str, ET.Element]] = []
    days: list[str] = []
    for day in body:
        key = day.get("n")
        if (day.tag != TEI + "div" or day.attrib != {"type": "day", "n": key,
                                                         XML_ID: f"daily-light-day-{key}"}
                or not isinstance(key, str) or not re.fullmatch(r"\d\d\.\d\d", key)):
            raise PipelineError("Daily Light day identity or attributes differ")
        days.append(key)
        if len(day) != 2:
            raise PipelineError(f"Daily Light day {key} lacks two periods")
        for expected, period in zip(("morning", "evening"), day, strict=True):
            if period.tag != TEI + "div" or period.attrib != {
                "type": "period", "n": expected, XML_ID: f"daily-light-{key}-{expected}",
            }:
                raise PipelineError(f"Daily Light period attachment differs: {key}/{expected}")
            if len(period) != 1 or period[0].tag != TEI + "p":
                raise PipelineError(f"Daily Light period paragraph differs: {key}/{expected}")
            marker = period[0].find(TEI + "hi")
            if (marker is None or period[0][0] is not marker or marker.get("rend") != "italic"
                    or _render_et(marker) != expected.title()):
                raise PipelineError(f"Daily Light source period marker differs: {key}/{expected}")
            carriers = [node for node in period[0].iter() if node is not period[0]]
            for ordinal, carrier in enumerate(carriers, 1):
                target = f"daily-{key}-{expected}-element-{ordinal:05d}"
                pointer = f"daily:{key}-{expected}:source-element-{ordinal:05d}"
                if carrier.tag not in (TEI + "hi", TEI + "lb", TEI + "ref") or carrier.get(XML_ID) != target or carrier.get("corresp") != pointer:
                    raise PipelineError(f"Daily Light source-element attachment differs: {key}/{expected}/{ordinal}")
                if carrier.tag == TEI + "hi" and carrier.attrib != {"rend": "italic", XML_ID: target, "corresp": pointer}:
                    raise PipelineError(f"Daily Light source marker attributes differ: {key}/{expected}")
                if carrier.tag == TEI + "lb" and carrier.attrib != {XML_ID: target, "corresp": pointer}:
                    raise PipelineError(f"Daily Light line-break attributes differ: {key}/{expected}")
                if carrier.tag == TEI + "ref" and (set(carrier.attrib) != {"type", "cRef", XML_ID, "corresp"}
                                                      or carrier.get("type") != "scripture" or not carrier.get("cRef")):
                    raise PipelineError(f"Daily Light scripture carrier attributes differ: {key}/{expected}")
            result.append((key, expected, period[0]))
    if (len(days) != 366 or days != sorted(set(days)) or days[0] != "01.01"
            or days[-1] != "12.31" or "02.29" not in days or len(result) != 732):
        raise PipelineError("Daily Light complete ordered leap-day scope differs")
    counts = Counter(node.tag.removeprefix(TEI) for node in body.iter())
    if counts["lb"] != 20313 or counts["ref"] != 1218 or counts["hi"] != 732:
        raise PipelineError("Daily Light body source-element census differs")
    return result, dict(counts)


def project_document(path: Path, *, identity: dict, language: str,
                     representation_revision: str, edition_title: str) -> dict:
    raw = Path(path).read_bytes()
    if identity != IDENTITY or language != "en" or _sha(raw) != MASTER_SHA:
        raise PipelineError("Daily Light exact accepted identity or master differs")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper() or b"<!--" in raw:
        raise PipelineError("Daily Light unsupported XML declaration")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise PipelineError(f"Daily Light invalid TEI: {exc}") from exc
    if root.tag != TEI + "TEI" or root.attrib != {XML_ID: "daily-light-candidate"}:
        raise PipelineError("Daily Light TEI root differs")
    text = root.find(TEI + "text")
    if text is None or [node.tag for node in text] != [TEI + "front", TEI + "body"]:
        raise PipelineError("Daily Light front/body envelope differs")
    front, body = list(text)
    units, counts = _periods_et(body)
    rows = []
    anchors = []
    for sequence, (day, period, paragraph) in enumerate(units, 1):
        visible = _render_et(paragraph)
        references = []
        for ref in paragraph.iter(TEI + "ref"):
            if ref.get("type") != "scripture" or not ref.get("cRef") or not ref.get(XML_ID) or not ref.get("corresp"):
                raise PipelineError(f"Daily Light source ref differs: {day}/{period}")
            references.append({"raw": _render_et(ref), "cRef": ref.get("cRef")})
        if not references or not visible:
            raise PipelineError(f"Daily Light period text/ref missing: {day}/{period}")
        identifier = f"daily-light-{day}-{period}"
        row = {**identity, "record_id": identity["edition_id"] + ":devotionals:" + _sha(identifier.encode())[:20],
               "sequence": sequence, "category": "devotionals", "language": language,
               "representation_revision": representation_revision, "provenance": {"edition_title": edition_title},
               "locator": {"kind": "devotional", "number": day, "heading": period.title()},
               "date": day, "readings": [{"text": visible, "locus": None}],
               "divisions": [{"kind": "paragraph", "text": visible, "references": references}],
               "text": visible}
        rows.append(row)
        anchors.append({"day": day, "period": period, "source_id": identifier,
                        "record_id": row["record_id"], "text_sha256": _sha(visible.encode()),
                        "reference_count": len(references)})
    _validate_rows(rows)
    receipt = {"scope": "tei-document; context supplied by caller", "mapping_version": PROFILE,
               "master_sha256": MASTER_SHA, "output_sha256": _sha(_canonical(rows)),
               "row_count": 732, "anchors": anchors, "body_counts": counts,
               "front_text_sha256": _sha("".join(front.itertext()).encode("utf-8")),
               "front_counts": {"lb": sum(1 for node in front.iter(TEI + "lb")),
                                "hi": sum(1 for node in front.iter(TEI + "hi"))},
               "front_disposition": "private source header; excluded from public rows",
               "source_reference_policy": "raw text and cRef retained; no inferred OSIS",
               "typography_disposition": "source hi attributes retained in accepted TEI; public text warns of typography flattening"}
    return {"rows": rows, "receipt": receipt}


def _render_lxml(node: etree._Element) -> str:
    fragments: list[str] = []
    for action, element in etree.iterwalk(node, events=("start", "end")):
        tag = etree.QName(element).localname
        if action == "start":
            if tag == "lb":
                fragments.append(SEPARATOR)
            elif element.text:
                fragments.append(element.text)
        elif element is not node and element.tail:
            fragments.append(element.tail)
    return "\n".join(" ".join(part.split()) for part in "".join(fragments).split(SEPARATOR)).strip("\n")


def verify_document(path: Path, rows: list[dict], receipt: dict, *, identity: dict, language: str,
                    representation_revision: str, edition_title: str) -> list[str]:
    try:
        if set(receipt) != {"scope", "mapping_version", "master_sha256", "output_sha256",
                            "row_count", "anchors", "body_counts", "front_text_sha256",
                            "front_counts", "front_disposition", "source_reference_policy",
                            "typography_disposition"}:
            raise ValueError("Daily Light independent receipt fields differ")
        raw = Path(path).read_bytes()
        if identity != IDENTITY or language != "en" or _sha(raw) != MASTER_SHA:
            raise ValueError("Daily Light independent identity or master differs")
        root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        if root.getroottree().docinfo.doctype or root.xpath("//comment() | //processing-instruction()"):
            raise ValueError("Daily Light independent XML envelope differs")
        ns = {"t": NAMESPACE}
        front = root.xpath("./t:text/t:front", namespaces=ns)
        if len(front) != 1:
            raise ValueError("Daily Light independent private front differs")
        front_counts = {"lb": len(front[0].xpath(".//t:lb", namespaces=ns)),
                        "hi": len(front[0].xpath(".//t:hi", namespaces=ns))}
        if (receipt.get("front_text_sha256") != _sha("".join(front[0].itertext()).encode("utf-8"))
                or receipt.get("front_counts") != front_counts or front_counts != {"lb": 33, "hi": 2}
                or receipt.get("front_disposition") != "private source header; excluded from public rows"
                or receipt.get("source_reference_policy") != "raw text and cRef retained; no inferred OSIS"
                or receipt.get("typography_disposition") != "source hi attributes retained in accepted TEI; public text warns of typography flattening"):
            raise ValueError("Daily Light independent private front or source policy differs")
        days = root.xpath("./t:text/t:body/t:div", namespaces=ns)
        if len(days) != 366 or len(rows) != 732:
            raise ValueError("Daily Light independent day or period count differs")
        expected = []
        anchors = []
        for day in days:
            key = day.get("n")
            if day.get(XML_ID) != f"daily-light-day-{key}" or day.get("type") != "day":
                raise ValueError("Daily Light independent day identity differs")
            periods = day.xpath("./t:div", namespaces=ns)
            if [p.get("n") for p in periods] != ["morning", "evening"]:
                raise ValueError("Daily Light independent period order differs")
            for period in periods:
                role = period.get("n")
                if period.get(XML_ID) != f"daily-light-{key}-{role}" or period.get("type") != "period":
                    raise ValueError("Daily Light independent period attachment differs")
                paragraph = period.xpath("./t:p", namespaces=ns)
                if len(paragraph) != 1 or len(period) != 1:
                    raise ValueError("Daily Light independent paragraph differs")
                marker = paragraph[0].xpath("./t:hi[1]", namespaces=ns)
                if (len(marker) != 1 or paragraph[0][0] is not marker[0]
                        or marker[0].get("rend") != "italic" or _render_lxml(marker[0]) != role.title()):
                    raise ValueError("Daily Light independent marker differs")
                carriers = paragraph[0].xpath("descendant::*")
                for ordinal, carrier in enumerate(carriers, 1):
                    target = f"daily-{key}-{role}-element-{ordinal:05d}"
                    pointer = f"daily:{key}-{role}:source-element-{ordinal:05d}"
                    kind = etree.QName(carrier).localname
                    if (etree.QName(carrier).namespace != NAMESPACE or kind not in {"hi", "lb", "ref"}
                            or carrier.get(XML_ID) != target or carrier.get("corresp") != pointer):
                        raise ValueError("Daily Light independent source-element attachment differs")
                    expected_keys = {XML_ID, "corresp"} | ({"rend"} if kind == "hi" else {"type", "cRef"} if kind == "ref" else set())
                    if set(carrier.attrib) != expected_keys:
                        raise ValueError("Daily Light independent source-element attributes differ")
                    if kind == "hi" and carrier.get("rend") != "italic":
                        raise ValueError("Daily Light independent marker rendition differs")
                    if kind == "ref" and (carrier.get("type") != "scripture" or not carrier.get("cRef")):
                        raise ValueError("Daily Light independent source reference differs")
                visible = _render_lxml(paragraph[0])
                refs = paragraph[0].xpath(".//t:ref", namespaces=ns)
                references = [{"raw": _render_lxml(ref), "cRef": ref.get("cRef")} for ref in refs]
                sequence = len(expected) + 1
                identifier = f"daily-light-{key}-{role}"
                record_id = identity["edition_id"] + ":devotionals:" + _sha(identifier.encode())[:20]
                expected.append({**identity, "record_id": record_id, "sequence": sequence,
                    "category": "devotionals", "language": language,
                    "representation_revision": representation_revision, "provenance": {"edition_title": edition_title},
                    "locator": {"kind": "devotional", "number": key, "heading": role.title()}, "date": key,
                    "readings": [{"text": visible, "locus": None}],
                    "divisions": [{"kind": "paragraph", "text": visible, "references": references}], "text": visible})
                anchors.append({"day": key, "period": role, "source_id": identifier,
                    "record_id": record_id, "text_sha256": _sha(visible.encode()), "reference_count": len(refs)})
        if expected != rows or anchors != receipt.get("anchors"):
            raise ValueError("Daily Light independent period rows or anchors differ")
        counts = Counter(etree.QName(node).localname for node in root.xpath("./t:text/t:body/descendant-or-self::*", namespaces=ns))
        if counts["lb"] != 20313 or counts["ref"] != 1218 or counts["hi"] != 732:
            raise ValueError("Daily Light independent body source census differs")
        if (receipt.get("scope") != "tei-document; context supplied by caller"
                or receipt.get("mapping_version") != PROFILE or receipt.get("master_sha256") != MASTER_SHA
                or receipt.get("output_sha256") != _sha(_canonical(rows)) or receipt.get("body_counts") != dict(counts)
                or receipt.get("row_count") != 732):
            raise ValueError("Daily Light independent receipt differs")
        return []
    except (OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        return [str(exc)]

