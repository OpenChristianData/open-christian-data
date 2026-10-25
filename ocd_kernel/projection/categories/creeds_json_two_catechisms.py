"""Exact source Q&A rows for two complete Creeds.json catechism witnesses.

This module is intentionally separate from the shared catechism projector.
It maps retained JSON and checks the candidate TEI's source-defined units;
accepted-authority routing is added only after the existing install window.
"""

from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.catechisms import _validate_rows


ROOT = Path(__file__).resolve().parents[3]
ROUTES = json.loads((ROOT / "build/tools/creeds_json_two_catechisms_routes.json").read_text(encoding="utf-8"))
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def shape(work_id: str, document: dict[str, object]) -> dict[str, object]:
    route = ROUTES.get(work_id)
    if route is None:
        raise PipelineError(f"catechism work is outside the two declared complete members: {work_id}")
    metadata = document.get("Metadata")
    units = document.get("Data")
    if (not isinstance(metadata, dict) or metadata.get("CreedFormat") != "Catechism"
            or not isinstance(units, list) or len(units) != route["row_count"]):
        raise PipelineError("catechism retained source envelope differs")
    has_proofs = work_id == "westminster-larger-catechism"
    proof_count = 0
    reference_count = 0
    for index, unit in enumerate(units, 1):
        keys = {"Number", "Question", "Answer", "AnswerWithProofs", "Proofs"} if has_proofs else {"Number", "Question", "Answer"}
        if (not isinstance(unit, dict) or set(unit) != keys or unit["Number"] != index
                or not isinstance(unit["Question"], str) or not unit["Question"]
                or not isinstance(unit["Answer"], str) or not unit["Answer"]):
            raise PipelineError(f"catechism source question {index} differs")
        if has_proofs:
            if (not isinstance(unit["AnswerWithProofs"], str) or not unit["AnswerWithProofs"]
                    or not isinstance(unit["Proofs"], list)):
                raise PipelineError(f"catechism source proof envelope {index} differs")
            for proof in unit["Proofs"]:
                if (not isinstance(proof, dict) or set(proof) != {"Id", "References"}
                        or not isinstance(proof["Id"], int) or isinstance(proof["Id"], bool) or proof["Id"] < 1
                        or not isinstance(proof["References"], list) or not proof["References"]
                        or any(not isinstance(ref, str) or not ref for ref in proof["References"])):
                    raise PipelineError(f"catechism source proof at question {index} differs")
                proof_count += 1
                reference_count += len(proof["References"])
    if proof_count != route["proof_count"] or reference_count != route["reference_count"]:
        raise PipelineError("catechism source proof/reference census differs")
    return route


def _producer_units(tei_bytes: bytes, count: int) -> list[ET.Element]:
    if b"<!DOCTYPE" in tei_bytes.upper() or b"<!ENTITY" in tei_bytes.upper():
        raise PipelineError("catechism TEI declarations are unsupported")
    root = ET.fromstring(tei_bytes, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
    body = root.find(f"{TEI}text/{TEI}body")
    if (root.tag != TEI + "TEI" or body is None or len(body) != 1
            or body[0].tag != TEI + "div" or body[0].get("type") != "catechism"):
        raise PipelineError("catechism TEI body envelope differs")
    units = list(body[0])
    if len(units) != count or any(unit.tag != TEI + "div" or unit.get("type") != "question-unit" for unit in units):
        raise PipelineError("catechism TEI question-unit census differs")
    return units


def _proof_rows(proofs: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {"id": proof["Id"], "references": [{"raw": ref, "osis": [ref]} for ref in proof["References"]]}
        for proof in proofs
    ]


def project_rows(context: dict[str, object], document: dict[str, object], tei_bytes: bytes) -> list[dict[str, object]]:
    """Produce public Q&A rows after checking each exact TEI question unit."""
    route = shape(context["work_id"], document)
    tei_units = _producer_units(tei_bytes, route["row_count"])
    identity = context["identity"]
    rows = []
    for sequence, (source, carrier) in enumerate(zip(document["Data"], tei_units, strict=True), 1):
        question = carrier.find(f"{TEI}p[@ana='#question']")
        answer = carrier.find(f"{TEI}p[@ana='#answer']")
        proof_text = carrier.find(f"{TEI}p[@ana='#answer-with-proofs']")
        anchor = carrier.get(XML_ID)
        if (carrier.get("n") != str(sequence) or not anchor
                or question is None or question.text != source["Question"]
                or answer is None or answer.text != source["Answer"]
                or (proof_text.text if proof_text is not None else None) != source.get("AnswerWithProofs")):
            raise PipelineError(f"catechism TEI question {sequence} differs from retained source")
        rows.append({
            "work_id": identity["work_id"], "textual_form_id": identity["textual_form_id"],
            "edition_id": identity["edition_id"],
            "record_id": f"{identity['edition_id']}:question-{sequence}", "sequence": sequence,
            "category": "catechisms", "language": "en",
            "text": f"Q: {source['Question']} A: {source['Answer']}",
            "representation_revision": context["representation_revision"],
            "provenance": {"edition_title": context["edition_title"]},
            "item_id": str(source["Number"]), "sort_key": source["Number"],
            "question": source["Question"], "answer": source["Answer"],
            "answer_with_proofs": source.get("AnswerWithProofs"),
            "proofs": _proof_rows(source.get("Proofs", [])),
            "group": None, "sub_questions": None,
            "locator": {"kind": "question", "text_part": "body", "part_titles": [],
                        "divisions": [], "question": anchor, "source_order": sequence},
        })
    _validate_rows(rows)
    return rows


def verify_rows(context: dict[str, object], rows: list[dict[str, object]], tei_bytes: bytes) -> list[str]:
    """Independently read lxml question/proof carriers and rederive source rows."""
    try:
        source = context["document"]
        route = shape(context["work_id"], source)
        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
        root = etree.fromstring(tei_bytes, parser)
        if root.getroottree().docinfo.doctype or root.xpath("//comment() | //processing-instruction()"):
            raise PipelineError("checker: catechism TEI declarations/comments differ")
        ns = {"t": TEI[1:-1]}
        units = root.xpath("./t:text/t:body/t:div[@type='catechism']/t:div[@type='question-unit']", namespaces=ns)
        if len(units) != route["row_count"] or len(rows) != route["row_count"]:
            return ["checker: catechism unit/row census differs"]
        identity = context["identity"]
        for index, (unit, original, row) in enumerate(zip(units, source["Data"], rows, strict=True), 1):
            anchor = unit.get(XML_ID)
            question = unit.xpath("./t:p[@ana='#question']/text()", namespaces=ns)
            answer = unit.xpath("./t:p[@ana='#answer']/text()", namespaces=ns)
            proof_text = unit.xpath("./t:p[@ana='#answer-with-proofs']/text()", namespaces=ns)
            proof_items = unit.xpath("./t:list[@type='proofs']/t:item", namespaces=ns)
            if (unit.get("n") != str(original["Number"]) or not anchor
                    or question != [original["Question"]] or answer != [original["Answer"]]
                    or proof_text != ([original["AnswerWithProofs"]] if "AnswerWithProofs" in original else [])
                    or len(proof_items) != len(original.get("Proofs", []))):
                return [f"checker: catechism TEI unit {index} differs from retained source"]
            for proof_node, proof in zip(proof_items, original.get("Proofs", []), strict=True):
                refs = proof_node.xpath("./t:listBibl[@type='source-references']/t:bibl/t:ref[@type='scripture']/text()", namespaces=ns)
                if proof_node.get("n") != str(proof["Id"]) or refs != proof["References"]:
                    return [f"checker: catechism TEI proof at question {index} differs"]
            expected = {
                "work_id": identity["work_id"], "textual_form_id": identity["textual_form_id"],
                "edition_id": identity["edition_id"],
                "record_id": f"{identity['edition_id']}:question-{index}", "sequence": index,
                "category": "catechisms", "language": "en",
                "text": f"Q: {original['Question']} A: {original['Answer']}",
                "representation_revision": context["representation_revision"],
                "provenance": {"edition_title": context["edition_title"]},
                "item_id": str(original["Number"]), "sort_key": original["Number"],
                "question": original["Question"], "answer": original["Answer"],
                "answer_with_proofs": original.get("AnswerWithProofs"),
                "proofs": [
                    {"id": proof["Id"], "references": [
                        {"raw": citation, "osis": [citation]} for citation in proof["References"]
                    ]}
                    for proof in original.get("Proofs", [])
                ],
                "group": None, "sub_questions": None,
                "locator": {"kind": "question", "text_part": "body", "part_titles": [],
                            "divisions": [], "question": anchor, "source_order": index},
            }
            if row != expected:
                return [f"checker: catechism row {index} differs from retained source and TEI"]
        _validate_rows(rows)
        return []
    except (PipelineError, ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        return [str(exc)]
