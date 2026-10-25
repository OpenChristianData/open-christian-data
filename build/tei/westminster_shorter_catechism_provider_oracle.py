"""Independent retained-source checker for the three WSC provider masters."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from lxml import etree, html


TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
WORK = "westminster-shorter-catechism"
ROUTES = {
    "creeds-json": ("westminster-shorter-catechism-creeds-json-en", "westminster-shorter-catechism-creeds-json-retained", "raw/Creeds.json/creeds/westminster_shorter_catechism.json", "0a569c527fb4332448b5b853ff0dd6c3d6b5dd6abb8c5a746d58d9172886ffc6"),
    "theologai-json": ("westminster-shorter-catechism-theologai-json-en", "westminster-shorter-catechism-theologai-json-retained", "raw/TheologAI/data/historical-documents/westminster-shorter-catechism.json", "89547581ed26576d2ab595894d7b21ac12e78a66d96e251b419ed023856283de"),
    "westminster-standard-html": ("westminster-shorter-catechism-westminster-standard-html-en", "westminster-shorter-catechism-westminster-standard-html-retained", "raw/westminster-standard-org/westminster-shorter-catechism.html", "8ffe7e7ae54c16066cce41456a8260d21e5dc3948568507ffbfc83658d10615a"),
}


def _norm(value: str) -> str:
    return " ".join(value.split())


def _html_citations(value: str) -> list[str]:
    value = re.sub(r"\s+with\s+", "; ", value.strip().rstrip("."), flags=re.I)
    result: list[str] = []
    book = re.compile(r"^(?:[123]\s+)?[A-Za-z]+\.?(?=\s)")
    for semicolon in value.split(";"):
        current = ""
        for part in (item.strip() for item in semicolon.split(",")):
            if not part:
                continue
            if current and book.match(part):
                result.append(current)
                current = part
            elif current:
                current += ", " + part
            else:
                current = part
        if current:
            result.append(current)
    return [re.sub(r"\s+title\b", "", item, flags=re.I).strip() for item in result]


def _source_rows(root: Path, route_name: str) -> tuple[list[dict[str, Any]], bytes]:
    form_id, edition_id, relative, expected_sha = ROUTES[route_name]
    raw = (root / relative).read_bytes()
    if sha256(raw).hexdigest() != expected_sha:
        raise ValueError(f"oracle retained hash mismatch: {route_name}")
    if route_name == "creeds-json":
        value = json.loads(raw.decode("utf-8"))
        if value["Metadata"]["Title"] != "Westminster Shorter Catechism":
            raise ValueError("oracle Creeds title mismatch")
        rows = [{"n": int(x["Number"]), "q": str(x["Question"]), "a": str(x["Answer"]), "proofs": []} for x in value["Data"]]
    elif route_name == "theologai-json":
        value = json.loads(raw.decode("utf-8"))
        if value["title"] != "Westminster Shorter Catechism":
            raise ValueError("oracle TheologAI title mismatch")
        rows = [{"n": int(x["question"]), "q": str(x["q"]), "a": str(x["a"]), "proofs": []} for x in value["sections"]]
    else:
        document = html.fromstring(raw)
        if "Westminster Shorter Catechism" not in _norm("".join(document.xpath("//title[1]//text()"))):
            raise ValueError("oracle HTML title mismatch")
        rows = []
        for paragraph in document.xpath("//p"):
            bold = paragraph.xpath("./b")
            if not bold or not _norm("".join(bold[0].itertext())).startswith("Q."):
                continue
            match = re.match(r"^Q\.\s*(\d+)\.\s*(.*?)\s+A\.\s*(.*)$", _norm(paragraph.text_content()))
            if match is None:
                raise ValueError("oracle HTML Q/A parse failed")
            proof = paragraph.getnext()
            emphasized = [] if proof is None else [_norm("".join(x.itertext())) for x in proof.xpath("./em")]
            citations = _html_citations(" ".join(emphasized))
            rows.append({"n": int(match.group(1)), "q": match.group(2), "a": match.group(3), "proofs": citations})
    if [row["n"] for row in rows] != list(range(1, 108)):
        raise ValueError(f"oracle source scope mismatch: {route_name}")
    if route_name == "westminster-standard-html" and sum(len(row["proofs"]) for row in rows) != 401:
        raise ValueError("oracle HTML proof census mismatch")
    return rows, raw


def verify_candidate(root: Path, route_name: str, candidate: Path) -> dict[str, Any]:
    form_id, edition_id, relative, source_sha = ROUTES[route_name]
    expected, raw = _source_rows(root, route_name)
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False, remove_pis=False)
    document = etree.fromstring(candidate.read_bytes(), parser=parser)
    if document.tag != f"{{{TEI}}}TEI" or document.getroottree().docinfo.doctype:
        raise ValueError("oracle candidate envelope mismatch")
    ns = {"t": TEI}
    values = {}
    for node in document.xpath("./t:teiHeader/t:fileDesc/t:sourceDesc//t:idno", namespaces=ns):
        values[node.get("type")] = _norm("".join(node.itertext()))
    required = {"work_id": WORK, "textual_form_id": form_id, "edition_id": edition_id, "source_sha256": source_sha, "retained_sha256": source_sha}
    if any(values.get(key) != value for key, value in required.items()):
        raise ValueError("oracle candidate source identity mismatch")
    paths = document.xpath("./t:teiHeader/t:fileDesc/t:sourceDesc//t:note[@type='source-location']", namespaces=ns)
    if len(paths) != 1 or _norm("".join(paths[0].itertext())) != relative:
        raise ValueError("oracle candidate retained path mismatch")
    units = document.xpath("./t:text/t:body/t:div[@type='catechism']/t:div[@type='question-unit']", namespaces=ns)
    if len(units) != 107:
        raise ValueError("oracle candidate question census mismatch")
    observed = []
    proof_count = 0
    for number, unit in enumerate(units, 1):
        questions = unit.xpath("./t:head[@type='question']", namespaces=ns)
        answers = unit.xpath("./t:ab[@type='answer']", namespaces=ns)
        if unit.get("n") != str(number) or len(questions) != 1 or len(answers) != 1:
            raise ValueError(f"oracle candidate Q{number} structure mismatch")
        proof_nodes = unit.xpath("./t:list[@type='proofs']/t:item/t:ref", namespaces=ns)
        proofs = []
        for index, ref in enumerate(proof_nodes, 1):
            if ref.getparent().get("n") != str(index) or not ref.get("cRef"):
                raise ValueError(f"oracle candidate Q{number} proof structure mismatch")
            proofs.append(_norm("".join(ref.itertext())))
        proof_count += len(proofs)
        observed.append({"n": number, "q": "".join(questions[0].itertext()), "a": "".join(answers[0].itertext()), "proofs": proofs})
    if observed != expected:
        for index, (actual, wanted) in enumerate(zip(observed, expected), 1):
            if actual != wanted:
                raise ValueError(f"oracle source fidelity mismatch at Q{index}")
        raise ValueError("oracle source fidelity mismatch")
    return {
        "status": "pass",
        "route": route_name,
        "source_path": relative,
        "source_sha256": sha256(raw).hexdigest(),
        "candidate_sha256": sha256(candidate.read_bytes()).hexdigest(),
        "question_count": 107,
        "proof_reference_count": proof_count,
        "method": "Independent source parse and complete Q/A/proof comparison; no producer import.",
    }


__all__ = ["verify_candidate"]
