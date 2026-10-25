"""Independent retained-JSON to TEI label and Q&A crosswalk for two LIB-062 works.

This read-only oracle does not promote a native catechism row or bypass its
public-row schema. It keeps source labels as strings, including punctuation and
trailing spaces, and binds every nested item to its parent and source position.
"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from lxml import etree


TEI = "http://www.tei-c.org/ns/1.0"
NS = {"t": TEI}
SOURCES = {
    "exposition-of-the-assemblies-catechism": {
        "sha256": "a03860854485eb0e14ce647272357ed5e66ebb1ab6c53cc633dcacc53d1869c2",
        "rows": 125, "subquestions": 1244, "question_marks": 23,
        "spaced_labels": (("41", 2, "2 "), ("45", 4, "4 ")),
    },
    "shorter-catechism-explained": {
        "sha256": "90aea411d973c7c43af89df2520f8f08c57d97643f33a135c5473aa931479b7d",
        "rows": 107, "subquestions": 3831, "question_marks": 0,
        "spaced_labels": (),
    },
}


def _strict_json(content: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate retained JSON key: {key}")
            result[key] = value
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("retained catechism must be a JSON object")
    return value


def _plain(node: etree._Element, tag: str, attribute: tuple[str, str]) -> str:
    if (node.tag != f"{{{TEI}}}{tag}" or node.get(*attribute) != attribute[1]
            or len(node) or node.text is None):
        raise ValueError(f"LIB-062 {tag} source carrier differs")
    return node.text


def crosswalk(work_id: str, source_bytes: bytes, tei_bytes: bytes) -> dict[str, Any]:
    """Return exact positional rows only when every source label/text matches TEI."""
    expected = SOURCES.get(work_id)
    if expected is None or sha256(source_bytes).hexdigest() != expected["sha256"]:
        raise ValueError("LIB-062 retained JSON authority differs")
    document = _strict_json(source_bytes)
    data = document.get("Data")
    metadata = document.get("Metadata")
    if (not isinstance(metadata, dict) or metadata.get("CreedFormat") != "HenrysCatechism"
            or metadata.get("OriginalLanguage") != "English"
            or not isinstance(data, list) or len(data) != expected["rows"]):
        raise ValueError("LIB-062 numeric-label source envelope differs")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    root = etree.fromstring(tei_bytes, parser)
    if root.getroottree().docinfo.doctype or root.xpath("//comment() | //processing-instruction()"):
        raise ValueError("LIB-062 candidate contains unsupported markup")
    units = root.xpath("./t:text/t:body/t:div[@type='catechism']/t:div[@type='question-unit']", namespaces=NS)
    if root.tag != f"{{{TEI}}}TEI" or len(units) != len(data):
        raise ValueError("LIB-062 candidate main Q&A census differs")
    rows: list[dict[str, Any]] = []
    spaced: list[tuple[str, int, str]] = []
    question_marks = 0
    sub_count = 0
    for position, (record, unit) in enumerate(zip(data, units, strict=True), 1):
        if not isinstance(record, dict) or set(record) != {"Number", "Question", "Answer", "SubQuestions"}:
            raise ValueError(f"LIB-062 source main row {position} differs")
        raw = record["Number"]
        if not isinstance(raw, str) or (not raw.isdecimal() and raw != "?"):
            raise ValueError(f"LIB-062 source main label {position} differs")
        question_marks += raw == "?"
        if (unit.get("n") != raw or not unit.get("{http://www.w3.org/XML/1998/namespace}id")
                or len(unit) != 4):
            raise ValueError(f"LIB-062 candidate main label or child count {position} differs")
        if (_plain(unit[0], "label", ("type", "source-number")) != raw
                or _plain(unit[1], "p", ("ana", "#question")) != record["Question"]
                or _plain(unit[2], "p", ("ana", "#answer")) != record["Answer"]
                or not isinstance(record["Question"], str) or not record["Question"]
                or not isinstance(record["Answer"], str) or not record["Answer"]):
            raise ValueError(f"LIB-062 candidate main text {position} differs")
        source_subs = record["SubQuestions"]
        if not isinstance(source_subs, list):
            raise ValueError(f"LIB-062 source nested array {position} differs")
        carrier = unit[3]
        if not source_subs:
            if (carrier.tag != f"{{{TEI}}}note" or carrier.attrib.get("type") != "source-empty-array"
                    or carrier.get("n") != "SubQuestions" or carrier.text or len(carrier)):
                raise ValueError(f"LIB-062 empty nested array {position} differs")
        elif carrier.tag != f"{{{TEI}}}list" or carrier.get("type") != "subquestions" or len(carrier) != len(source_subs):
            raise ValueError(f"LIB-062 nested carrier {position} differs")
        subs: list[dict[str, Any]] = []
        for nested_position, (sub, item) in enumerate(zip(source_subs, carrier, strict=True), 1):
            if not isinstance(sub, dict) or set(sub) != {"Number", "Question", "Answer"}:
                raise ValueError(f"LIB-062 source nested row {position}:{nested_position} differs")
            label = sub["Number"]
            if not isinstance(label, str) or not label.strip().isdecimal() or label != label.strip():
                spaced.append((raw, nested_position, label))
            if (not isinstance(label, str) or not label.strip().isdecimal()
                    or item.tag != f"{{{TEI}}}item" or item.get("n") != label or len(item) != 3
                    or _plain(item[0], "label", ("type", "subquestion-number")) != label
                    or _plain(item[1], "p", ("ana", "#subquestion-question")) != sub["Question"]
                    or _plain(item[2], "p", ("ana", "#subquestion-answer")) != sub["Answer"]
                    or not isinstance(sub["Question"], str) or not sub["Question"]
                    or not isinstance(sub["Answer"], str) or not sub["Answer"]):
                raise ValueError(f"LIB-062 nested label or text {position}:{nested_position} differs")
            subs.append({"source_position": nested_position, "item_id": label,
                         "question": sub["Question"], "answer": sub["Answer"]})
            sub_count += 1
        rows.append({"source_position": position, "item_id": raw, "sort_key": position,
                     "question": record["Question"], "answer": record["Answer"],
                     "sub_questions": subs})
    if (question_marks != expected["question_marks"] or sub_count != expected["subquestions"]
            or tuple(spaced) != expected["spaced_labels"]):
        raise ValueError("LIB-062 source label census differs")
    return {"work_id": work_id, "source_sha256": expected["sha256"], "rows": rows,
            "main_question_mark_count": question_marks, "subquestion_count": sub_count,
            "spaced_labels": spaced}
