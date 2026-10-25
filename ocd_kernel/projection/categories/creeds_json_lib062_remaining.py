"""Source-bound native rows for remaining representable LIB062 JSON catechisms."""

from __future__ import annotations

import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.catechisms import _validate_rows


ROOT = Path(__file__).resolve().parents[3]
ROUTES = json.loads((ROOT / "build/tools/creeds_json_four_catechisms_routes.json").read_text(encoding="utf-8"))
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
STAGEABLE = frozenset({"keachs-catechism", "matthew-henrys-scripture-catechism", "puritan-catechism",
                      "shorter-catechism-explained", "exposition-of-the-assemblies-catechism",
                      "heidelberg-catechism"})


def shape(work_id: str, document: dict[str, object]) -> dict[str, object]:
    route = ROUTES.get(work_id)
    if route is None:
        raise PipelineError(f"LIB062 catechism is outside exact routes: {work_id}")
    metadata, units = document.get("Metadata"), document.get("Data")
    if (not isinstance(metadata, dict) or metadata.get("CreedFormat") != route["source_format"]
            or metadata.get("OriginalLanguage") != route.get("original_language", "English")
            or not isinstance(units, list) or len(units) != route["row_count"]):
        raise PipelineError("LIB062 catechism source envelope differs")
    proofs = references = subquestions = 0
    question_with_proofs_numbers = []
    for index, unit in enumerate(units, 1):
        if not isinstance(unit, dict):
            raise PipelineError(f"LIB062 catechism Number {index} differs")
        number = unit.get("Number")
        if work_id == "exposition-of-the-assemblies-catechism":
            if not isinstance(number, str) or not re.fullmatch(r"(?:[0-9]+|\?)", number):
                raise PipelineError(f"LIB062 catechism source label {index} differs")
            if ((number == "?") != (unit.get("Question") == "?" and unit.get("Answer") == "?")):
                raise PipelineError(f"LIB062 catechism placeholder row {index} differs")
            if number != "?" and (unit.get("Question") == "?" or unit.get("Answer") == "?"):
                raise PipelineError(f"LIB062 catechism partial placeholder row {index} differs")
        else:
            expected = str(index) if work_id in {
                "matthew-henrys-scripture-catechism", "shorter-catechism-explained"} else index
            if number != expected:
                raise PipelineError(f"LIB062 catechism Number {index} differs")
        keys = {"Number", "Question", "Answer"}
        if work_id in {"1695-baptist-catechism", "keachs-catechism"}:
            keys |= {"AnswerWithProofs", "Proofs"}
        elif work_id in {"matthew-henrys-scripture-catechism", "shorter-catechism-explained",
                         "exposition-of-the-assemblies-catechism"}:
            keys.add("SubQuestions")
        elif "Proofs" in unit or "AnswerWithProofs" in unit:
            keys |= {"AnswerWithProofs", "Proofs"}
        if "QuestionWithProofs" in unit:
            keys.add("QuestionWithProofs")
        if (set(unit) != keys or not isinstance(unit["Question"], str) or not unit["Question"]
                or not isinstance(unit["Answer"], str)):
            raise PipelineError(f"LIB062 catechism fields at question {index} differ")
        if "QuestionWithProofs" in unit:
            if (work_id != "heidelberg-catechism" or not isinstance(unit["QuestionWithProofs"], str)
                    or not unit["QuestionWithProofs"]):
                raise PipelineError(f"LIB062 catechism proof-bearing question {index} differs")
            question_with_proofs_numbers.append(index)
        if not unit["Answer"]:
            raise PipelineError(f"LIB062 catechism question {index} has empty source Answer; native schema requires nonempty text")
        if "Proofs" in unit:
            if not isinstance(unit["AnswerWithProofs"], str) or not isinstance(unit["Proofs"], list):
                raise PipelineError(f"LIB062 catechism proof fields at question {index} differ")
            for proof in unit["Proofs"]:
                if (not isinstance(proof, dict) or set(proof) != {"Id", "References"}
                        or type(proof["Id"]) is not int or proof["Id"] < 1
                        or not isinstance(proof["References"], list) or not proof["References"]
                        or any(not isinstance(ref, str) or not ref for ref in proof["References"])):
                    raise PipelineError(f"LIB062 catechism proof at question {index} differs")
                proofs += 1
                references += len(proof["References"])
        if "SubQuestions" in unit:
            if (not isinstance(unit["SubQuestions"], list)
                    or (not unit["SubQuestions"] and work_id not in {
                        "shorter-catechism-explained", "exposition-of-the-assemblies-catechism"})):
                raise PipelineError(f"LIB062 catechism subquestions at question {index} differ")
            for sub in unit["SubQuestions"]:
                if work_id == "exposition-of-the-assemblies-catechism":
                    number_pattern = r"[0-9]+ ?"
                elif work_id == "shorter-catechism-explained":
                    number_pattern = r"[0-9]+"
                else:
                    number_pattern = r"[0-9]+[A-Za-z]+"
                if (not isinstance(sub, dict) or set(sub) != {"Number", "Question", "Answer"}
                        or not isinstance(sub["Number"], str)
                        or not re.fullmatch(number_pattern, sub["Number"])
                        or not isinstance(sub["Question"], str) or not sub["Question"]
                        or not isinstance(sub["Answer"], str) or not sub["Answer"]):
                    raise PipelineError(f"LIB062 catechism subquestion at question {index} differs")
                subquestions += 1
    if (proofs != route["proof_count"] or references != route["reference_count"]
            or subquestions != route["subquestion_count"]
            or question_with_proofs_numbers != route.get("question_with_proofs_numbers", [])):
        raise PipelineError("LIB062 catechism source census differs")
    return route


def _proofs(value: list[dict[str, object]]) -> list[dict[str, object]]:
    return [{"id": proof["Id"], "references": [{"raw": ref, "osis": [ref]} for ref in proof["References"]]}
            for proof in value]


def _row(context: dict[str, object], source: dict[str, object], anchor: str, index: int) -> dict[str, object]:
    identity = context["identity"]
    row = {
        "work_id": identity["work_id"], "textual_form_id": identity["textual_form_id"],
        "edition_id": identity["edition_id"], "record_id": f"{identity['edition_id']}:question-{index}",
        "sequence": index, "category": "catechisms", "language": "en",
        "text": f"Q: {source['Question']} A: {source['Answer']}",
        "representation_revision": context["representation_revision"],
        "provenance": {"edition_title": context["edition_title"]},
        "item_id": str(source["Number"]), "sort_key": index,
        "question": source["Question"], "answer": source["Answer"],
        "answer_with_proofs": source.get("AnswerWithProofs"), "proofs": _proofs(source.get("Proofs", [])),
        "group": None,
        "sub_questions": ([{"item_id": sub["Number"], "question": sub["Question"],
                            "answer": sub["Answer"], "proofs": []} for sub in source["SubQuestions"]]
                          if "SubQuestions" in source else None),
        "locator": {"kind": "question", "text_part": "body", "part_titles": [],
                    "divisions": [], "question": anchor, "source_order": index},
    }
    if "QuestionWithProofs" in source:
        row["question_with_proofs"] = source["QuestionWithProofs"]
    return row


def _check_unit(unit: object, source: dict[str, object], index: int, *, parser: str) -> str:
    """Compare all native content-bearing TEI carriers to the retained row."""
    if parser == "etree":
        def get(path: str) -> list[object]:
            return unit.findall(path)

        def content(node: object) -> str:
            return node.text or ""
    else:
        ns = {"t": TEI[1:-1]}

        def get(path: str) -> list[object]:
            return unit.xpath(path.replace(TEI, "t:"), namespaces=ns)

        def content(node: object) -> str:
            return "".join(node.itertext())
    anchor = unit.get(XML_ID)
    if unit.get("n") != str(source["Number"]) or not anchor:
        raise PipelineError(f"checker: LIB062 question {index} anchor/number differs")
    for path, value in ((f"{TEI}label[@type='source-number']", str(source["Number"])),
                        (f"{TEI}p[@ana='#question']", source["Question"]),
                        (f"{TEI}p[@ana='#answer']", source["Answer"])):
        nodes = get(path)
        if len(nodes) != 1 or content(nodes[0]) != value:
            raise PipelineError(f"checker: LIB062 question {index} text differs")
    extra = get(f"{TEI}p[@ana='#answer-with-proofs']")
    if len(extra) != (1 if "AnswerWithProofs" in source else 0) or (extra and content(extra[0]) != source["AnswerWithProofs"]):
        raise PipelineError(f"checker: LIB062 question {index} proof-bearing answer differs")
    question_extra = get(f"{TEI}p[@ana='#question-with-proofs']")
    if (len(question_extra) != (1 if "QuestionWithProofs" in source else 0)
            or (question_extra and content(question_extra[0]) != source["QuestionWithProofs"])):
        raise PipelineError(f"checker: LIB062 question {index} proof-bearing question differs")
    proof_items = get(f"{TEI}list[@type='proofs']/{TEI}item")
    if len(proof_items) != len(source.get("Proofs", [])):
        raise PipelineError(f"checker: LIB062 question {index} proof count differs")
    for carrier, proof in zip(proof_items, source.get("Proofs", []), strict=True):
        refs = carrier.findall(f"{TEI}listBibl[@type='source-references']/{TEI}bibl/{TEI}ref") if parser == "etree" else carrier.xpath("./t:listBibl[@type='source-references']/t:bibl/t:ref", namespaces={"t": TEI[1:-1]})
        if carrier.get("n") != str(proof["Id"]) or [content(ref) for ref in refs] != proof["References"]:
            raise PipelineError(f"checker: LIB062 question {index} proof values differ")
    sub_items = get(f"{TEI}list[@type='subquestions']/{TEI}item")
    if len(sub_items) != len(source.get("SubQuestions", [])):
        raise PipelineError(f"checker: LIB062 question {index} subquestion count differs")
    for carrier, sub in zip(sub_items, source.get("SubQuestions", []), strict=True):
        label = carrier.find(f"{TEI}label[@type='subquestion-number']") if parser == "etree" else carrier.xpath("./t:label[@type='subquestion-number']", namespaces={"t": TEI[1:-1]})
        q = carrier.find(f"{TEI}p[@ana='#subquestion-question']") if parser == "etree" else carrier.xpath("./t:p[@ana='#subquestion-question']", namespaces={"t": TEI[1:-1]})
        a = carrier.find(f"{TEI}p[@ana='#subquestion-answer']") if parser == "etree" else carrier.xpath("./t:p[@ana='#subquestion-answer']", namespaces={"t": TEI[1:-1]})
        if parser != "etree":
            label, q, a = (nodes[0] if len(nodes) == 1 else None for nodes in (label, q, a))
        if (carrier.get("n") != sub["Number"] or label is None or content(label) != sub["Number"]
                or q is None or content(q) != sub["Question"]
                or a is None or content(a) != sub["Answer"]):
            raise PipelineError(f"checker: LIB062 question {index} subquestion differs")
    return anchor


def project_rows(context: dict[str, object], document: dict[str, object], tei_bytes: bytes) -> list[dict[str, object]]:
    route = shape(context["work_id"], document)
    if b"<!DOCTYPE" in tei_bytes.upper() or b"<!ENTITY" in tei_bytes.upper():
        raise PipelineError("LIB062 catechism TEI declarations are unsupported")
    root = ET.fromstring(tei_bytes, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
    body = root.find(f"{TEI}text/{TEI}body")
    if root.tag != TEI + "TEI" or body is None or len(body) != 1 or body[0].get("type") != "catechism":
        raise PipelineError("LIB062 catechism TEI body envelope differs")
    units = list(body[0])
    if len(units) != route["row_count"] or any(unit.tag != TEI + "div" or unit.get("type") != "question-unit" for unit in units):
        raise PipelineError("LIB062 catechism TEI unit census differs")
    rows = [_row(context, source, _check_unit(unit, source, index, parser="etree"), index)
            for index, (source, unit) in enumerate(zip(document["Data"], units, strict=True), 1)]
    _validate_rows(rows)
    return rows


def verify_rows(context: dict[str, object], rows: object, tei_bytes: bytes) -> list[str]:
    try:
        route = shape(context["work_id"], context["document"])
        if not isinstance(rows, list) or len(rows) != route["row_count"]:
            return ["checker: LIB062 row census differs"]
        root = etree.fromstring(tei_bytes, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        if root.getroottree().docinfo.doctype or root.xpath("//comment() | //processing-instruction()"):
            return ["checker: LIB062 TEI declaration/comment differs"]
        ns = {"t": TEI[1:-1]}
        units = root.xpath("./t:text/t:body/t:div[@type='catechism']/t:div[@type='question-unit']", namespaces=ns)
        if len(units) != route["row_count"]:
            return ["checker: LIB062 TEI unit census differs"]
        for index, (source, unit, row) in enumerate(zip(context["document"]["Data"], units, rows, strict=True), 1):
            anchor = _check_unit(unit, source, index, parser="lxml")
            if ("question_with_proofs" in row) != ("QuestionWithProofs" in source):
                return [f"checker: LIB062 row {index} proof-bearing question presence differs"]
            if "QuestionWithProofs" in source and row["question_with_proofs"] != source["QuestionWithProofs"]:
                return [f"checker: LIB062 row {index} proof-bearing question differs"]
            if row != _row(context, source, anchor, index):
                return [f"checker: LIB062 row {index} differs from retained source"]
        _validate_rows(rows)
        return []
    except (PipelineError, ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        return [str(exc)]
