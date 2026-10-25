"""Build one faithful TEI catechism for each retained WSC provider edition."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping

from lxml import etree, html

from build.tei.westminster_shorter_catechism_reconstruction import (
    _reference,
    _segments,
)


TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
WORK_ID = "westminster-shorter-catechism"
ROUTES: dict[str, dict[str, str]] = {
    "creeds-json": {
        "form_id": "westminster-shorter-catechism-creeds-json-en",
        "edition_id": "westminster-shorter-catechism-creeds-json-retained",
        "acquisition_id": "westminster-shorter-catechism-01-westminster-shorter-catechism-acquired",
        "source_path": "raw/Creeds.json/creeds/westminster_shorter_catechism.json",
        "source_sha256": "0a569c527fb4332448b5b853ff0dd6c3d6b5dd6abb8c5a746d58d9172886ffc6",
        "source_bytes": "32442",
        "source_url": "https://github.com/NonlinearFruit/Creeds.json",
        "source_scope": "Complete retained Creeds.json provider Q&A rendering; print edition unresolved.",
    },
    "theologai-json": {
        "form_id": "westminster-shorter-catechism-theologai-json-en",
        "edition_id": "westminster-shorter-catechism-theologai-json-retained",
        "acquisition_id": "westminster-shorter-catechism-02-westminster-shorter-catechism-acquired",
        "source_path": "raw/TheologAI/data/historical-documents/westminster-shorter-catechism.json",
        "source_sha256": "89547581ed26576d2ab595894d7b21ac12e78a66d96e251b419ed023856283de",
        "source_bytes": "31139",
        "source_url": "https://theologai.xyz",
        "source_scope": "Complete retained TheologAI historical-document rendering; exact upstream file URL unrecorded, rights unresolved.",
    },
    "westminster-standard-html": {
        "form_id": "westminster-shorter-catechism-westminster-standard-html-en",
        "edition_id": "westminster-shorter-catechism-westminster-standard-html-retained",
        "acquisition_id": "westminster-shorter-catechism-03-westminster-shorter-catechism-acquired",
        "source_path": "raw/westminster-standard-org/westminster-shorter-catechism.html",
        "source_sha256": "8ffe7e7ae54c16066cce41456a8260d21e5dc3948568507ffbfc83658d10615a",
        "source_bytes": "98505",
        "source_url": "https://thewestminsterstandard.org/westminster-shorter-catechism/",
        "source_scope": "Complete retained Westminster Standard HTML page; Q&A and proof apparatus plus outer carrier, rights unresolved.",
    },
}


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def normalize(value: str) -> str:
    return " ".join(value.split())


def read_rows(root: Path, route_name: str) -> list[dict[str, Any]]:
    route = ROUTES[route_name]
    raw = (root / route["source_path"]).read_bytes()
    if len(raw) != int(route["source_bytes"]) or digest(raw) != route["source_sha256"]:
        raise ValueError(f"retained source binding changed for {route_name}")
    if route_name == "creeds-json":
        value = json.loads(raw.decode("utf-8"))
        if value.get("Metadata", {}).get("Title") != "Westminster Shorter Catechism":
            raise ValueError("Creeds source title contradicts canonical work")
        rows = [
            {"number": int(item["Number"]), "question": str(item["Question"]), "answer": str(item["Answer"]), "proofs": []}
            for item in value["Data"]
        ]
    elif route_name == "theologai-json":
        value = json.loads(raw.decode("utf-8"))
        if value.get("title") != "Westminster Shorter Catechism":
            raise ValueError("TheologAI source title contradicts canonical work")
        rows = [
            {"number": int(item["question"]), "question": str(item["q"]), "answer": str(item["a"]), "proofs": []}
            for item in value["sections"]
        ]
    else:
        document = html.fromstring(raw)
        title = normalize("".join(document.xpath("//title[1]//text()")))
        headings = [normalize("".join(node.itertext())) for node in document.xpath("//h1")]
        if "Westminster Shorter Catechism" not in title or "Shorter Catechism" not in headings:
            raise ValueError("Westminster Standard source title contradicts canonical work")
        rows = []
        for paragraph in document.xpath("//p"):
            bold = paragraph.xpath("./b")
            if not bold or not normalize("".join(bold[0].itertext())).startswith("Q."):
                continue
            match = re.match(r"^Q\.\s*(\d+)\.\s*(.*?)\s+A\.\s*(.*)$", normalize(paragraph.text_content()))
            if match is None:
                raise ValueError("unsupported Westminster HTML question structure")
            proof = paragraph.getnext()
            if proof is None or etree.QName(proof).localname != "p":
                raise ValueError(f"missing proof group for question {match.group(1)}")
            emphasized = [normalize("".join(node.itertext())) for node in proof.xpath("./em")]
            if not emphasized:
                raise ValueError(f"missing proof references for question {match.group(1)}")
            inherited = None
            proofs = []
            for occurrence, citation in enumerate(_segments(" ".join(emphasized)), 1):
                parsed, inherited = _reference(citation, inherited)
                proofs.append({"number": occurrence, "raw": parsed["raw"], "cRef": " ".join(parsed["osis"])})
            rows.append({"number": int(match.group(1)), "question": match.group(2), "answer": match.group(3), "proofs": proofs})
    if [item["number"] for item in rows] != list(range(1, 108)):
        raise ValueError(f"{route_name} does not contain ordered Q1-Q107")
    if route_name == "westminster-standard-html" and sum(len(item["proofs"]) for item in rows) != 401:
        raise ValueError("Westminster Standard proof-reference census changed")
    return rows


def node(parent: etree._Element, name: str, attrs: Mapping[str, str] | None = None, text: str | None = None) -> etree._Element:
    result = etree.SubElement(parent, f"{{{TEI}}}{name}")
    for key, value in (attrs or {}).items():
        result.set(XML_ID if key == "xml:id" else key, value)
    result.text = text
    return result


def build_tei(root: Path, route_name: str) -> bytes:
    route = ROUTES[route_name]
    rows = read_rows(root, route_name)
    tei = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    tei.set(XML_ID, f"{route['edition_id']}-master")
    header = node(tei, "teiHeader")
    file_desc = node(header, "fileDesc")
    title_stmt = node(file_desc, "titleStmt")
    node(title_stmt, "title", text="Westminster Shorter Catechism")
    publication = node(file_desc, "publicationStmt")
    node(publication, "publisher", text="Open Christian Data")
    availability = node(publication, "availability", {"status": "restricted"})
    node(availability, "p", text="Technical accepted master; rights clearance and publication authorization remain separate.")
    source_desc = node(file_desc, "sourceDesc")
    bibl = node(source_desc, "bibl")
    node(bibl, "title", text="Westminster Shorter Catechism")
    node(bibl, "idno", {"type": "work_id"}, WORK_ID)
    node(bibl, "idno", {"type": "textual_form_id"}, route["form_id"])
    node(bibl, "idno", {"type": "edition_id"}, route["edition_id"])
    node(bibl, "idno", {"type": "acquisition_id"}, route["acquisition_id"])
    node(bibl, "idno", {"type": "source_sha256"}, route["source_sha256"])
    node(bibl, "idno", {"type": "retained_sha256"}, route["source_sha256"])
    node(bibl, "idno", {"type": "sha256"}, route["source_sha256"])
    node(bibl, "idno", {"type": "source_bytes"}, route["source_bytes"])
    node(bibl, "idno", {"type": "representation_revision"}, "wsc-provider-edition-direct-v1")
    node(bibl, "ptr", {"target": route["source_url"]})
    node(bibl, "note", {"type": "source-location"}, route["source_path"])
    node(bibl, "note", {"type": "source-scope"}, route["source_scope"])
    encoding = node(header, "encodingDesc")
    node(encoding, "p", text=f"Direct transcription of the {route_name} retained provider rendering; no cross-witness selection or normalization.")
    revision = node(header, "revisionDesc")
    node(revision, "change", {"xml:id": "wsc-provider-edition-direct-v1", "when": "2026-09-30"}, "Direct source-specific reconstruction of one retained provider rendering without cross-witness selection.")
    text = node(tei, "text")
    body = node(text, "body")
    catechism = node(body, "div", {"type": "catechism", "xml:id": f"{route_name}-catechism"})
    for row in rows:
        number = row["number"]
        unit = node(catechism, "div", {"type": "question-unit", "n": str(number), "xml:id": f"{route_name}-q{number}"})
        node(unit, "head", {"type": "question"}, row["question"])
        node(unit, "ab", {"type": "answer"}, row["answer"])
        if row["proofs"]:
            proofs = node(unit, "list", {"type": "proofs"})
            for proof in row["proofs"]:
                item = node(proofs, "item", {"n": str(proof["number"])})
                node(item, "ref", {"type": "scripture", "cRef": proof["cRef"]}, proof["raw"])
    return etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False)


__all__ = ["ROUTES", "WORK_ID", "build_tei", "read_rows"]
