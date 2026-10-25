"""Independent source oracle for the three-witness Westminster candidate."""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree, html

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-westminster-shorter-catechism-independent-oracle"
ORACLE_VERSION = "2"
_ROOT = Path(__file__).resolve().parents[2]
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_PROFILE_ID = "westminster-shorter-catechism-three-witnesses-v1"
_RIGHTS = {
    "candidate": "nonaccepted; publication is not authorized",
    "creeds": "Creeds.json README supplies Unlicense evidence and does not name the WSC among its eight exceptions",
    "theologai": "TheologAI ISC license covers software and does not establish historical-document redistribution rights",
    "westminster_standard": "The cached page carries a 2016 copyright footer and no retained text or proof-apparatus license",
    "worldwide_status": "unresolved; human rights review is required before acceptance or publication",
}
_BOOK_ALIASES = (
    ("1 thess", "1Thess"),
    ("2 thess", "2Thess"),
    ("1 kings", "1Kgs"),
    ("1 john", "1John"),
    ("3 john", "3John"),
    ("1 chr", "1Chr"),
    ("1 cor", "1Cor"),
    ("1 pet", "1Pet"),
    ("1 sam", "1Sam"),
    ("1 tim", "1Tim"),
    ("2 cor", "2Cor"),
    ("2 sam", "2Sam"),
    ("2 tim", "2Tim"),
    ("acts", "Acts"),
    ("amos", "Amos"),
    ("col", "Col"),
    ("dan", "Dan"),
    ("deut", "Deut"),
    ("ecc", "Eccl"),
    ("eph", "Eph"),
    ("esther", "Esth"),
    ("ex", "Exod"),
    ("ezek", "Ezek"),
    ("gal", "Gal"),
    ("gen", "Gen"),
    ("heb", "Heb"),
    ("isa", "Isa"),
    ("jas", "Jas"),
    ("jer", "Jer"),
    ("job", "Job"),
    ("joel", "Joel"),
    ("john", "John"),
    ("lam", "Lam"),
    ("lev", "Lev"),
    ("luke", "Luke"),
    ("mal", "Mal"),
    ("mark", "Mark"),
    ("matt", "Matt"),
    ("mic", "Mic"),
    ("neh", "Neh"),
    ("phil", "Phil"),
    ("prov", "Prov"),
    ("ps", "Ps"),
    ("rev", "Rev"),
    ("rom", "Rom"),
    ("titus", "Titus"),
    ("zech", "Zech"),
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _digest(value: object) -> str:
    return _sha(_canonical(value))


def _strict(content: bytes, label: str, *, canonical: bool = True) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    if canonical and content != _canonical(value):
        raise ValueError(f"{label} is not canonical JSON")
    return value


def _authority(manifest: SourceManifest, name: str) -> Mapping[str, object]:
    authorities = manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("Westminster authority inventory is invalid")
    matches = [
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Westminster authority cardinality mismatch: {name}")
    return matches[0]


def _display(value: str) -> str:
    return " ".join(value.split())


def _split_book(raw: str) -> tuple[str, str] | None:
    candidate = raw.strip()
    lowered = candidate.casefold()
    for alias, osis in sorted(
        _BOOK_ALIASES, key=lambda item: len(item[0]), reverse=True
    ):
        match = re.match(rf"^{re.escape(alias)}\.?(?=\s)", lowered)
        if match:
            return osis, candidate[match.end() :].strip()
    return None


def _citation_parts(value: str) -> list[str]:
    value = re.sub(r"\s+with\s+", ";", value.strip().rstrip("."), flags=re.I)
    result: list[str] = []
    for major in value.split(";"):
        pieces = [item.strip() for item in major.split(",") if item.strip()]
        current: list[str] = []
        for piece in pieces:
            if current and _split_book(piece) is not None:
                result.append(", ".join(current))
                current = [piece]
            else:
                current.append(piece)
        if current:
            result.append(", ".join(current))
    return [re.sub(r"\s+title\b", "", item, flags=re.I).strip() for item in result]


def _parse_reference(raw: str, previous: str | None) -> tuple[dict[str, object], str]:
    split = _split_book(raw)
    if split is None:
        if previous is None or re.match(r"^\d+:\d", raw) is None:
            raise ValueError(f"independent oracle found unknown citation {raw!r}")
        book, coordinate = previous, raw.strip()
    else:
        book, coordinate = split
    chapter, separator, verses = coordinate.partition(":")
    if not chapter.isdigit() or (separator and not verses):
        raise ValueError(f"independent oracle found invalid citation {raw!r}")
    osis: list[str] = []
    if not separator:
        osis = [f"{book}.{chapter}"]
    else:
        for verse in (item.strip() for item in verses.split(",")):
            if re.fullmatch(r"\d+-\d+", verse):
                start, end = verse.split("-", 1)
                osis.append(f"{book}.{chapter}.{start}-{book}.{chapter}.{end}")
            elif verse.isdigit():
                osis.append(f"{book}.{chapter}.{verse}")
            else:
                raise ValueError(f"independent oracle found invalid verses {raw!r}")
    return {"raw": raw, "osis": osis}, book


def _independent_outer_html_census(content: bytes) -> dict[str, object]:
    """Recover every parsed HTML carrier without calling producer code."""

    tree = html.fromstring(content)
    paragraph_nodes = tree.xpath("//p")
    assigned_nodes: set[etree._Element] = set()
    question_nodes = [
        node
        for node in paragraph_nodes
        if node.xpath("./b")
        and _display("".join(node.xpath("./b")[0].itertext())).startswith("Q.")
    ]
    for ordinal, question in enumerate(question_nodes, start=1):
        assigned_nodes.add(question)
        proof = question.getnext()
        if proof is None or etree.QName(proof).localname != "p":
            raise ValueError(
                f"independent outer census found no proof paragraph for Q{ordinal}"
            )
        assigned_nodes.add(proof)
    if len(question_nodes) != 107 or len(assigned_nodes) != 214:
        raise ValueError(
            "independent outer census did not recover 107 question/proof pairs"
        )

    def classify(node: etree._Element) -> str:
        if node in assigned_nodes or any(
            parent in assigned_nodes for parent in node.iterancestors()
        ):
            return "assigned-content"
        return "outer-evidence-only"

    elements: list[dict[str, object]] = []
    attributes: list[dict[str, object]] = []
    text_carriers: list[dict[str, object]] = []
    comments: list[dict[str, object]] = []
    tags: Counter[str] = Counter()
    element_classes: Counter[str] = Counter()
    attribute_classes: Counter[str] = Counter()
    text_classes: Counter[str] = Counter()
    comment_classes: Counter[str] = Counter()
    for node in tree.iter():
        if isinstance(node, etree._Comment):
            node_class = classify(node)
            comment_classes[node_class] += 1
            comments.append(
                {
                    "ordinal": len(comments) + 1,
                    "disposition": node_class,
                    "value": node.text or "",
                }
            )
            continue
        if not isinstance(node.tag, str):
            continue
        owner = len(elements) + 1
        tag = etree.QName(node).localname
        node_class = classify(node)
        tags[tag] += 1
        element_classes[node_class] += 1
        elements.append({"ordinal": owner, "tag": tag, "disposition": node_class})
        for name, value in sorted(node.attrib.items()):
            attribute_classes[node_class] += 1
            attributes.append(
                {
                    "owner": owner,
                    "name": name,
                    "value": value,
                    "disposition": node_class,
                }
            )
        if _display(node.text or ""):
            text_classes[node_class] += 1
            text_carriers.append(
                {
                    "owner": owner,
                    "slot": "text",
                    "value": node.text,
                    "disposition": node_class,
                }
            )
        if _display(node.tail or ""):
            parent = node.getparent()
            tail_class = (
                classify(parent) if parent is not None else "outer-evidence-only"
            )
            text_classes[tail_class] += 1
            text_carriers.append(
                {
                    "owner": owner,
                    "slot": "tail",
                    "value": node.tail,
                    "disposition": tail_class,
                }
            )
    return {
        "parser": "lxml.html.fromstring",
        "paragraph_classes": {
            "assigned_questions": len(question_nodes),
            "assigned_proof_groups": len(assigned_nodes) - len(question_nodes),
            "outer_evidence_only": len(paragraph_nodes) - len(assigned_nodes),
        },
        "elements": {
            "total": len(elements),
            "by_disposition": dict(sorted(element_classes.items())),
            "by_tag": dict(sorted(tags.items())),
            "stream_sha256": _digest(elements),
        },
        "attributes": {
            "total": len(attributes),
            "by_disposition": dict(sorted(attribute_classes.items())),
            "stream_sha256": _digest(attributes),
        },
        "nonempty_text_carriers": {
            "total": len(text_carriers),
            "by_disposition": dict(sorted(text_classes.items())),
            "stream_sha256": _digest(text_carriers),
        },
        "comments": {
            "total": len(comments),
            "by_disposition": dict(sorted(comment_classes.items())),
            "stream_sha256": _digest(comments),
        },
    }


def _independent_source_model(manifest: SourceManifest) -> dict[str, object]:
    creeds = _strict(
        manifest.authority_path("creeds-wsc").read_bytes(),
        "Creeds source",
        canonical=False,
    )
    theologai = _strict(
        manifest.authority_path("theologai-wsc").read_bytes(),
        "TheologAI source",
        canonical=False,
    )
    creeds_rows = creeds.get("Data")
    theologai_rows = theologai.get("sections")
    if not isinstance(creeds_rows, list) or not isinstance(theologai_rows, list):
        raise ValueError("independent oracle did not recover the JSON witness arrays")
    sources: dict[str, list[dict[str, object]]] = {
        "creeds-json": [
            {
                "number": int(item["Number"]),
                "question": str(item["Question"]),
                "answer": str(item["Answer"]),
            }
            for item in creeds_rows
        ],
        "theologai-json": [
            {
                "number": int(item["question"]),
                "question": str(item["q"]),
                "answer": str(item["a"]),
            }
            for item in theologai_rows
        ],
    }
    html_bytes = manifest.authority_path("westminster-standard-wsc").read_bytes()
    outer_profile = _strict(
        manifest.authority_path("outer-html-profile").read_bytes(),
        "Westminster outer HTML profile",
        canonical=False,
    )
    outer_census = _independent_outer_html_census(html_bytes)
    if outer_census != outer_profile.get("census"):
        raise ValueError("independent Westminster outer HTML carrier census mutation")
    raw_authority = _authority(manifest, "westminster-standard-wsc")
    expected_authority = {
        key: raw_authority[key] for key in ("path", "bytes", "sha256")
    }
    if outer_profile.get("authority") != expected_authority:
        raise ValueError("Westminster outer HTML profile authority mutation")
    tree = html.fromstring(html_bytes)
    html_rows: list[dict[str, object]] = []
    relationships: list[dict[str, object]] = []
    candidates = [
        node
        for node in tree.xpath("//p")
        if node.xpath("./b")
        and _display("".join(node.xpath("./b")[0].itertext())).startswith("Q.")
    ]
    for ordinal, question_node in enumerate(candidates, start=1):
        displayed = _display(question_node.text_content())
        match = re.fullmatch(r"Q\.\s*(\d+)\.\s*(.*?)\s+A\.\s*(.*)", displayed)
        if match is None or int(match.group(1)) != ordinal:
            raise ValueError(
                "independent oracle found missing, duplicated, or reordered HTML questions"
            )
        proof_node = question_node.getnext()
        if proof_node is None or etree.QName(proof_node).localname != "p":
            raise ValueError(
                f"independent oracle found no proof paragraph for Q{ordinal}"
            )
        emphasized = [
            _display("".join(item.itertext())) for item in proof_node.xpath("./em")
        ]
        if not emphasized:
            raise ValueError(
                f"independent oracle found no emphasized proof for Q{ordinal}"
            )
        previous: str | None = None
        parsed_references: list[dict[str, object]] = []
        for occurrence, raw in enumerate(
            _citation_parts(" ".join(emphasized)), start=1
        ):
            parsed, previous = _parse_reference(raw, previous)
            parsed_references.append(parsed)
            relationships.append(
                {
                    "id": f"wsc-proof-q{ordinal}-{occurrence}",
                    "question_number": ordinal,
                    "occurrence": occurrence,
                    "raw": parsed["raw"],
                    "osis": parsed["osis"],
                    "source": "westminster-standard-html",
                    "proof_group": f"#wsc-westminster-standard-html-q{ordinal}-proof-group",
                    "target": f"#wsc-westminster-standard-html-q{ordinal}-proof-{occurrence}",
                }
            )
        html_rows.append(
            {
                "number": ordinal,
                "question": match.group(2),
                "answer": match.group(3),
                "proof_group": _display(proof_node.text_content()),
                "references": parsed_references,
            }
        )
    sources["westminster-standard-html"] = html_rows
    expected_numbers = list(range(1, 108))
    if any(
        [int(item["number"]) for item in rows] != expected_numbers
        for rows in sources.values()
    ):
        raise ValueError(
            "independent oracle did not recover Q1-Q107 from every witness"
        )
    metadata = creeds.get("Metadata")
    if not isinstance(metadata, dict):
        raise ValueError("independent oracle found invalid Creeds metadata")
    metadata_rows = [
        {"source": "creeds-json", "key": key, "value": value}
        for key, value in metadata.items()
    ]
    for key in ("title", "type", "date"):
        metadata_rows.append(
            {"source": "theologai-json", "key": key, "value": theologai[key]}
        )
    lookup = {
        source: {int(item["number"]): item for item in rows}
        for source, rows in sources.items()
    }
    q_equal = sum(
        len({str(rows[number]["question"]) for rows in lookup.values()}) == 1
        for number in expected_numbers
    )
    a_equal = sum(
        len({str(rows[number]["answer"]) for rows in lookup.values()}) == 1
        for number in expected_numbers
    )
    if (
        len(metadata_rows) != 13
        or len(relationships) != 401
        or q_equal != 79
        or a_equal != 22
    ):
        raise ValueError(
            "independent Westminster observation/reference/disagreement census mismatch"
        )
    return {
        "metadata": metadata_rows,
        "readings": sources,
        "relationships": relationships,
        "question_exact_agreements": q_equal,
        "answer_exact_agreements": a_equal,
        "outer_html_census": outer_census,
    }


def _crosswalk(model: Mapping[str, object]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for index, item in enumerate(model["metadata"], start=1):
        result.append(
            {
                "id": f"wsc-observation-metadata-{index:03d}",
                "source": item["source"],
                "kind": "metadata",
                "source_location": f"/{item['key']}",
                "value": item["value"],
                "status": "represented",
                "target": f"#wsc-metadata-{index:03d}",
            }
        )
    for source in ("creeds-json", "theologai-json", "westminster-standard-html"):
        for item in model["readings"][source]:
            number = int(item["number"])
            for kind in ("number", "question", "answer"):
                result.append(
                    {
                        "id": f"wsc-observation-{source}-q{number}-{kind}",
                        "source": source,
                        "kind": kind,
                        "source_location": f"/questions/{number}/{kind}",
                        "value": number if kind == "number" else item[kind],
                        "status": "represented",
                        "target": f"#wsc-{source}-q{number}-{kind}",
                    }
                )
    for item in model["readings"]["westminster-standard-html"]:
        number = int(item["number"])
        result.append(
            {
                "id": f"wsc-observation-westminster-standard-html-q{number}-proof-group",
                "source": "westminster-standard-html",
                "kind": "proof-group",
                "source_location": f"/questions/{number}/proof-group",
                "value": item["proof_group"],
                "status": "represented",
                "target": f"#wsc-westminster-standard-html-q{number}-proof-group",
            }
        )
    return result


def _expected_accountability(model: Mapping[str, object]) -> dict[str, object]:
    return {
        "contract": "ocd-westminster-shorter-catechism-source-accountability-v1",
        "profile_id": _PROFILE_ID,
        "observation_counts": {
            "total": 1083,
            "represented": 1083,
            "evidence_only": 0,
            "omitted": 0,
            "duplicate": 0,
        },
        "proof_reference_count": 401,
        "question_exact_agreements": model["question_exact_agreements"],
        "answer_exact_agreements": model["answer_exact_agreements"],
        "outer_html_census": model["outer_html_census"],
        "crosswalk": _crosswalk(model),
        "proof_relationships": model["relationships"],
    }


def _expected_provenance(manifest: SourceManifest) -> dict[str, object]:
    config = _strict(
        manifest.authority_path("local-source-config").read_bytes(),
        "local config",
        canonical=False,
    )
    return {
        "contract": "ocd-westminster-shorter-catechism-provenance-v1",
        "status": "nonaccepted",
        "source_manifest_sha256": manifest.sha256,
        "profile_id": _PROFILE_ID,
        "work_id": "westminster-shorter-catechism",
        "local_source_config_claims": config,
        "witnesses": [
            {
                key: _authority(manifest, name)[key]
                for key in ("name", "path", "bytes", "sha256")
            }
            for name in ("creeds-wsc", "theologai-wsc", "westminster-standard-wsc")
        ],
        "rights_evidence": [
            {
                key: _authority(manifest, name)[key]
                for key in ("name", "path", "bytes", "sha256")
            }
            for name in ("creeds-readme", "theologai-readme", "theologai-license")
        ],
        "outer_html_profile": {
            key: _authority(manifest, "outer-html-profile")[key]
            for key in ("name", "path", "bytes", "sha256")
        },
        "reading_policy": "three exact provider renderings represented separately; no selected reading",
        "rights": _RIGHTS,
    }


def _expected_unresolved() -> bytes:
    rows = (
        {
            "id": "wsc-unresolved-edition",
            "kind": "edition-identity",
            "status": "unresolved",
            "detail": "No retained authority supplies witness genealogy or selects a governing reading.",
        },
        {
            "id": "wsc-unresolved-theologai-rights",
            "kind": "rights",
            "status": "unresolved",
            "detail": _RIGHTS["theologai"],
        },
        {
            "id": "wsc-unresolved-westminster-standard-rights",
            "kind": "rights",
            "status": "unresolved",
            "detail": _RIGHTS["westminster_standard"],
        },
        {
            "id": "wsc-unresolved-acceptance",
            "kind": "acceptance",
            "status": "required",
            "detail": "Human textual and rights review is required before acceptance or publication.",
        },
    )
    return b"".join(_canonical(row) for row in rows)


def _expected_readme() -> bytes:
    return (
        "# Westminster Shorter Catechism source accountability\n\n"
        "This reconstruction candidate has six package members and preserves three exact retained provider renderings: Creeds.json, TheologAI, and The Westminster Standard. Each contains Q1-Q107. All 1,083 source observations and all 401 ordered proof-reference occurrences are bound without selecting or normalizing an edition reading. The retained HTML's complete parsed carrier stream is independently classified: the 214 question/proof paragraphs support assigned content, while every other element, attribute, nonempty text carrier, and comment remains bound as outer evidence only. The Q37 occurrence `Job 19:26-27` is retained; the older 400-reference JSON projection is not authority.\n\n"
        "The candidate is explicitly nonaccepted and publication is not authorized. Creeds.json supplies Unlicense evidence and does not list this work among its named exceptions. TheologAI's ISC license covers software, not historical-document redistribution. The cached Westminster Standard page carries a 2016 copyright footer and no retained text or proof-apparatus license. Edition genealogy and worldwide rights remain unresolved and require human review.\n"
    ).encode("utf-8")


def _projection(node: etree._Element) -> dict[str, object]:
    return {
        "name": etree.QName(node).localname,
        "attributes": {
            ("xml:id" if key == _XML_ID else etree.QName(key).localname): value
            for key, value in sorted(node.attrib.items())
        },
        "text": node.text or "",
        "tail": node.tail or "",
        "children": [_projection(child) for child in node],
    }


def _expected_node(
    parent: etree._Element,
    name: str,
    attributes: Mapping[str, str] | None = None,
    text: str | None = None,
) -> etree._Element:
    element = etree.SubElement(parent, f"{{{_TEI}}}{name}")
    for key, value in (attributes or {}).items():
        element.set(_XML_ID if key == "xml:id" else key, value)
    element.text = text
    return element


def _expected_tei_projection(
    model: Mapping[str, object], manifest: SourceManifest
) -> dict[str, object]:
    """Build the complete allowed TEI projection from retained authorities."""

    tei = etree.Element(f"{{{_TEI}}}TEI", nsmap={None: _TEI})
    tei.set(_XML_ID, "westminster-shorter-catechism-three-witness-candidate")
    header = _expected_node(tei, "teiHeader")
    file_desc = _expected_node(header, "fileDesc")
    title_stmt = _expected_node(file_desc, "titleStmt")
    _expected_node(
        title_stmt,
        "title",
        text="Westminster Shorter Catechism — three retained provider renderings",
    )
    _expected_node(
        title_stmt,
        "author",
        {"ana": "#source-claim"},
        "Westminster Assembly (Creeds.json metadata and local-config claim)",
    )
    for provider in ("Creeds.json", "TheologAI", "The Westminster Standard"):
        responsibility = _expected_node(title_stmt, "respStmt")
        _expected_node(responsibility, "resp", text="Retained source witness provider")
        _expected_node(responsibility, "name", text=provider)
    publication = _expected_node(file_desc, "publicationStmt")
    _expected_node(publication, "publisher", text="Open Christian Data")
    availability = _expected_node(publication, "availability", {"status": "restricted"})
    _expected_node(
        availability,
        "p",
        text=(
            "Nonaccepted reconstruction candidate. Publication is not authorized; "
            "edition identity and acquisition-specific rights require human review."
        ),
    )
    source_desc = _expected_node(file_desc, "sourceDesc")
    source_list = _expected_node(
        source_desc, "listBibl", {"type": "retained-witnesses"}
    )
    witnesses = (
        ("creeds-json", "creeds-wsc", _RIGHTS["creeds"]),
        ("theologai-json", "theologai-wsc", _RIGHTS["theologai"]),
        (
            "westminster-standard-html",
            "westminster-standard-wsc",
            _RIGHTS["westminster_standard"],
        ),
    )
    for witness_id, authority_name, rights in witnesses:
        authority = _authority(manifest, authority_name)
        bibl = _expected_node(source_list, "bibl", {"xml:id": f"source-{witness_id}"})
        _expected_node(bibl, "title", text=witness_id)
        _expected_node(bibl, "ptr", {"target": str(authority["path"])})
        _expected_node(bibl, "idno", {"type": "sha256"}, str(authority["sha256"]))
        _expected_node(bibl, "note", {"type": "rights-status"}, rights)
        _expected_node(
            bibl,
            "note",
            {"type": "edition-status"},
            "Provider rendering only; no selected-reading or edition authority.",
        )
    metadata_list = _expected_node(
        source_desc, "list", {"type": "source-metadata-claims"}
    )
    for index, item in enumerate(model["metadata"], start=1):
        _expected_node(
            metadata_list,
            "item",
            {"xml:id": f"wsc-metadata-{index:03d}", "n": str(index)},
            (
                f"{item['source']}:{item['key']}="
                f"{json.dumps(item['value'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
            ),
        )
    encoding = _expected_node(header, "encodingDesc")
    _expected_node(
        encoding,
        "p",
        text=(
            "All three ordered witness renderings are represented separately. "
            "No reading is normalized, selected, or conflated."
        ),
    )
    text = _expected_node(tei, "text")
    group = _expected_node(text, "group", {"xml:id": "wsc-retained-witnesses"})
    for witness_id in (
        "creeds-json",
        "theologai-json",
        "westminster-standard-html",
    ):
        witness_text = _expected_node(
            group,
            "text",
            {"xml:id": f"wsc-witness-{witness_id}", "n": witness_id},
        )
        body = _expected_node(witness_text, "body")
        for row in model["readings"][witness_id]:
            number = int(row["number"])
            unit = _expected_node(
                body,
                "div",
                {
                    "type": "question-unit",
                    "n": str(number),
                    "xml:id": f"wsc-{witness_id}-q{number}",
                },
            )
            _expected_node(
                unit,
                "label",
                {
                    "type": "number",
                    "xml:id": f"wsc-{witness_id}-q{number}-number",
                },
                str(number),
            )
            _expected_node(
                unit,
                "p",
                {
                    "ana": "#question",
                    "xml:id": f"wsc-{witness_id}-q{number}-question",
                },
                str(row["question"]),
            )
            _expected_node(
                unit,
                "p",
                {
                    "ana": "#answer",
                    "xml:id": f"wsc-{witness_id}-q{number}-answer",
                },
                str(row["answer"]),
            )
            if witness_id == "westminster-standard-html":
                proofs = _expected_node(
                    unit,
                    "listBibl",
                    {
                        "type": "proof-group",
                        "xml:id": f"wsc-{witness_id}-q{number}-proof-group",
                    },
                )
                for occurrence, reference in enumerate(row["references"], start=1):
                    bibl = _expected_node(
                        proofs,
                        "bibl",
                        {"xml:id": (f"wsc-{witness_id}-q{number}-proof-{occurrence}")},
                    )
                    _expected_node(
                        bibl,
                        "ref",
                        {
                            "type": "scripture",
                            "cRef": " ".join(reference["osis"]),
                        },
                        str(reference["raw"]),
                    )
    return _projection(tei)


def _verify_header(
    tei: etree._Element, model: Mapping[str, object], manifest: SourceManifest
) -> None:
    ns = {"tei": _TEI}
    headers = tei.xpath("./tei:teiHeader", namespaces=ns)
    if len(headers) != 1:
        raise ValueError("Westminster TEI header cardinality mutation")
    header = headers[0]
    titles = header.xpath("./tei:fileDesc/tei:titleStmt/tei:title", namespaces=ns)
    authors = header.xpath("./tei:fileDesc/tei:titleStmt/tei:author", namespaces=ns)
    providers = header.xpath(
        "./tei:fileDesc/tei:titleStmt/tei:respStmt/tei:name/text()", namespaces=ns
    )
    availability = header.xpath(
        "./tei:fileDesc/tei:publicationStmt/tei:availability", namespaces=ns
    )
    if (
        len(titles) != 1
        or titles[0].text
        != "Westminster Shorter Catechism — three retained provider renderings"
        or len(authors) != 1
        or authors[0].text
        != "Westminster Assembly (Creeds.json metadata and local-config claim)"
        or dict(authors[0].attrib) != {"ana": "#source-claim"}
        or providers != ["Creeds.json", "TheologAI", "The Westminster Standard"]
        or len(availability) != 1
        or availability[0].get("status") != "restricted"
        or "Publication is not authorized" not in "".join(availability[0].itertext())
    ):
        raise ValueError(
            "Westminster exact localized header metadata or rights mutation"
        )
    bibls = header.xpath(
        "./tei:fileDesc/tei:sourceDesc/tei:listBibl[@type='retained-witnesses']/tei:bibl",
        namespaces=ns,
    )
    expected_sources = (
        ("creeds-json", "creeds-wsc", _RIGHTS["creeds"]),
        ("theologai-json", "theologai-wsc", _RIGHTS["theologai"]),
        (
            "westminster-standard-html",
            "westminster-standard-wsc",
            _RIGHTS["westminster_standard"],
        ),
    )
    observed = []
    for node in bibls:
        observed.append(
            (
                node.get(_XML_ID),
                node.xpath("string(tei:title)", namespaces=ns),
                node.xpath("string(tei:ptr/@target)", namespaces=ns),
                node.xpath("string(tei:idno[@type='sha256'])", namespaces=ns),
                node.xpath("string(tei:note[@type='rights-status'])", namespaces=ns),
                node.xpath("string(tei:note[@type='edition-status'])", namespaces=ns),
            )
        )
    expected = []
    for source, authority_name, rights in expected_sources:
        authority = _authority(manifest, authority_name)
        expected.append(
            (
                f"source-{source}",
                source,
                authority["path"],
                authority["sha256"],
                rights,
                "Provider rendering only; no selected-reading or edition authority.",
            )
        )
    if observed != expected:
        raise ValueError(
            "Westminster source-description witness, identity, or rights mutation"
        )
    items = header.xpath(
        "./tei:fileDesc/tei:sourceDesc/tei:list[@type='source-metadata-claims']/tei:item",
        namespaces=ns,
    )
    expected_items = [
        (
            f"wsc-metadata-{index:03d}",
            str(index),
            f"{item['source']}:{item['key']}={json.dumps(item['value'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))}",
        )
        for index, item in enumerate(model["metadata"], start=1)
    ]
    if [
        (item.get(_XML_ID), item.get("n"), item.text) for item in items
    ] != expected_items:
        raise ValueError(
            "Westminster source metadata occurrence, order, value, or attachment mutation"
        )
    encoding = header.xpath("string(./tei:encodingDesc/tei:p)", namespaces=ns)
    if (
        encoding
        != "All three ordered witness renderings are represented separately. No reading is normalized, selected, or conflated."
    ):
        raise ValueError(
            "Westminster selected-reading or normalization policy mutation"
        )


def _verify_body(tei: etree._Element, model: Mapping[str, object]) -> None:
    ns = {"tei": _TEI}
    texts = tei.xpath(
        "./tei:text/tei:group[@xml:id='wsc-retained-witnesses']/tei:text",
        namespaces={**ns, "xml": "http://www.w3.org/XML/1998/namespace"},
    )
    sources = ("creeds-json", "theologai-json", "westminster-standard-html")
    if [(node.get(_XML_ID), node.get("n")) for node in texts] != [
        (f"wsc-witness-{source}", source) for source in sources
    ]:
        raise ValueError(
            "Westminster witness wrapper identity, order, or attachment mutation"
        )
    for text_node, source in zip(texts, sources, strict=True):
        units = text_node.xpath(
            "./tei:body/tei:div[@type='question-unit']", namespaces=ns
        )
        if len(units) != 107:
            raise ValueError(
                f"Westminster {source} group omission, invention, or duplication"
            )
        for unit, expected in zip(units, model["readings"][source], strict=True):
            number = int(expected["number"])
            if dict(unit.attrib) != {
                "type": "question-unit",
                "n": str(number),
                _XML_ID: f"wsc-{source}-q{number}",
            }:
                raise ValueError(
                    "Westminster question group identity, number, or position mutation"
                )
            children = list(unit)
            expected_count = 4 if source == "westminster-standard-html" else 3
            if len(children) != expected_count:
                raise ValueError(
                    "Westminster question carrier omission, invention, or outside content"
                )
            leaves = (
                ("label", "number", str(number), f"wsc-{source}-q{number}-number"),
                (
                    "p",
                    "question",
                    str(expected["question"]),
                    f"wsc-{source}-q{number}-question",
                ),
                (
                    "p",
                    "answer",
                    str(expected["answer"]),
                    f"wsc-{source}-q{number}-answer",
                ),
            )
            for node, (name, kind, value, identity) in zip(
                children[:3], leaves, strict=True
            ):
                expected_attributes = (
                    {"type": kind, _XML_ID: identity}
                    if name == "label"
                    else {"ana": f"#{kind}", _XML_ID: identity}
                )
                if (
                    etree.QName(node).localname != name
                    or dict(node.attrib) != expected_attributes
                    or len(node)
                    or node.text != value
                ):
                    raise ValueError(
                        "Westminster witness reading text, kind, identity, or attachment mutation"
                    )
            if source == "westminster-standard-html":
                proof_group = children[3]
                if etree.QName(proof_group).localname != "listBibl" or dict(
                    proof_group.attrib
                ) != {
                    "type": "proof-group",
                    _XML_ID: f"wsc-{source}-q{number}-proof-group",
                }:
                    raise ValueError(
                        "Westminster proof-group identity or attachment mutation"
                    )
                references = list(proof_group)
                if len(references) != len(expected["references"]):
                    raise ValueError(
                        "Westminster proof occurrence omission, invention, or obsolete 400 substitution"
                    )
                for occurrence, (bibl, reference) in enumerate(
                    zip(references, expected["references"], strict=True), start=1
                ):
                    if (
                        etree.QName(bibl).localname != "bibl"
                        or dict(bibl.attrib)
                        != {_XML_ID: f"wsc-{source}-q{number}-proof-{occurrence}"}
                        or len(bibl) != 1
                    ):
                        raise ValueError(
                            "Westminster proof occurrence identity, order, or attachment mutation"
                        )
                    ref = bibl[0]
                    if (
                        etree.QName(ref).localname != "ref"
                        or dict(ref.attrib)
                        != {"type": "scripture", "cRef": " ".join(reference["osis"])}
                        or ref.text != reference["raw"]
                        or len(ref)
                    ):
                        raise ValueError(
                            "Westminster proof raw text, OSIS, or occurrence mutation"
                        )


def _verify_tei(
    candidate: CandidatePackage, model: Mapping[str, object], manifest: SourceManifest
) -> None:
    content = candidate.member_bytes("content.tei.xml")
    try:
        tei = etree.fromstring(content)
    except etree.XMLSyntaxError as exc:
        raise ValueError("Westminster TEI is not well formed") from exc
    schema = compiled_schema()
    if not schema.validate(etree.ElementTree(tei)):
        raise ValueError(
            f"Westminster TEI P5 validation failure: {schema.error_log.last_error}"
        )
    if (
        etree.QName(tei).text != f"{{{_TEI}}}TEI"
        or tei.get(_XML_ID) != "westminster-shorter-catechism-three-witness-candidate"
    ):
        raise ValueError("Westminster TEI root identity mutation")
    if [etree.QName(child).localname for child in tei] != ["teiHeader", "text"]:
        raise ValueError("Westminster TEI root content mutation")
    _verify_header(tei, model, manifest)
    _verify_body(tei, model)
    if _projection(tei) != _expected_tei_projection(model, manifest):
        raise ValueError("Westminster complete TEI projection mutation")
    expected_ids = [
        value
        for value in tei.xpath(
            "//@xml:id", namespaces={"xml": "http://www.w3.org/XML/1998/namespace"}
        )
    ]
    if len(expected_ids) != len(set(expected_ids)):
        raise ValueError("Westminster duplicate TEI identity mutation")


def _module_path(root: Path, module: str) -> Path | None:
    candidate = root.joinpath(*module.split("."))
    file_path = candidate.with_suffix(".py")
    if file_path.is_file():
        return file_path.resolve(strict=True)
    init_path = candidate / "__init__.py"
    return init_path.resolve(strict=True) if init_path.is_file() else None


def _initializers(root: Path, path: Path) -> tuple[Path, ...]:
    relative = path.relative_to(root)
    return tuple(
        candidate.resolve(strict=True)
        for depth in range(1, len(relative.parts))
        if (
            candidate := root.joinpath(*relative.parts[:depth], "__init__.py")
        ).is_file()
    )


def _repository_import_closure(
    root: Path, entry: Path, forbidden: tuple[str, ...]
) -> tuple[dict[str, str], ...]:
    root = root.resolve(strict=True)
    entry = entry.resolve(strict=True)
    entry.relative_to(root)
    pending = [entry, *_initializers(root, entry)]
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise ValueError("Westminster oracle closure escaped repository") from exc
        visited.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        package_parts = list(relative.with_suffix("").parts[:-1])
        if relative.name == "__init__.py":
            package_parts = list(relative.parent.parts)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (
                isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "eval", "exec"}
                or isinstance(node.func, ast.Attribute)
                and node.func.attr in {"import_module", "exec_module"}
            ):
                raise ValueError(
                    "Westminster closure contains dynamic import or execution"
                )
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    prefix = package_parts[: len(package_parts) - node.level + 1]
                    base = ".".join([*prefix, *([base] if base else [])])
                modules.append(base)
                modules.extend(
                    f"{base}.{alias.name}"
                    for alias in node.names
                    if base and alias.name != "*"
                )
            for module in modules:
                if any(
                    module == item or module.startswith(f"{item}.")
                    for item in forbidden
                ):
                    raise ValueError(
                        f"Westminster oracle closure imports forbidden dependency {module}"
                    )
                local = _module_path(root, module)
                if local is not None and local not in visited:
                    pending.extend((local, *_initializers(root, local)))
    return tuple(
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in sorted(visited, key=lambda item: item.relative_to(root).as_posix())
    )


def _closure_digest(
    root: Path, policy: Mapping[str, object], entry: Path | None = None
) -> str:
    forbidden = tuple(str(item) for item in policy.get("forbidden_import_prefixes", []))
    return _digest(_repository_import_closure(root, entry or Path(__file__), forbidden))


def _source_set_sha256(manifest: SourceManifest) -> str:
    members = sorted(
        (
            {key: item.get(key) for key in ("name", "path", "bytes", "sha256")}
            for item in manifest.record["authorities"]
            if isinstance(item, Mapping) and item.get("role") == "primary-source"
        ),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    if len(members) == 1:
        return str(members[0]["sha256"])
    return _digest({"contract": "ocd-source-member-set-v1", "members": members})


def _runtime() -> str:
    return f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})"


def _module_name(path: str) -> str:
    parts = list(Path(path).parts)
    if parts[-1] == "__init__.py":
        parts.pop()
    else:
        parts[-1] = Path(parts[-1]).stem
    return ".".join(parts)


def _assert_runtime_paths(
    root: Path,
    *closures: tuple[dict[str, str], ...],
) -> None:
    for record in {
        item["path"]: item for closure in closures for item in closure
    }.values():
        module_name = _module_name(record["path"])
        expected_path = (root / record["path"]).resolve(strict=True)
        canonical_module = sys.modules.get(module_name)
        if canonical_module is None:
            continue
        canonical_path = getattr(canonical_module, "__file__", None)
        if canonical_path is not None:
            if Path(canonical_path).resolve() == expected_path:
                continue
            raise ValueError(
                f"Westminster runtime module path shadow detected: {module_name}"
            )
        if Path(record["path"]).name != "__init__.py":
            raise ValueError(
                f"Westminster runtime module path shadow detected: {module_name}"
            )
        namespace_paths = []
        for value in getattr(canonical_module, "__path__", ()):
            try:
                namespace_paths.append(Path(value).resolve(strict=True))
            except OSError:
                raise ValueError(
                    f"Westminster runtime module path shadow detected: {module_name}"
                ) from None
        if namespace_paths != [expected_path.parent]:
            raise ValueError(
                f"Westminster runtime module path shadow detected: {module_name}"
            )


def _assert_rights_evidence(manifest: SourceManifest) -> None:
    creeds = manifest.authority_path("creeds-readme").read_text(encoding="utf-8")
    theologai = manifest.authority_path("theologai-readme").read_text(encoding="utf-8")
    license_text = manifest.authority_path("theologai-license").read_text(
        encoding="utf-8"
    )
    html_text = manifest.authority_path("westminster-standard-wsc").read_text(
        encoding="utf-8"
    )
    exceptions = creeds.split("## Creeds Included", 1)[0]
    if (
        "Unlicense" not in exceptions
        or "westminster_shorter_catechism" in exceptions.casefold()
    ):
        raise ValueError("Westminster Creeds rights evidence mutation")
    if (
        "no document bodies, provenance URLs, source hashes, or rights instruments"
        not in theologai
        or "ISC License" not in license_text
    ):
        raise ValueError("Westminster TheologAI rights boundary evidence mutation")
    if "© 2016 The Westminster Standard" not in html_text:
        raise ValueError("Westminster Standard copyright evidence mutation")


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict(profile_bytes, "Westminster profile", canonical=False)
    policy = _strict(policy_bytes, "Westminster validation policy", canonical=False)
    if profile.get("profile_id") != _PROFILE_ID or profile.get("rights") != _RIGHTS:
        raise ValueError("Westminster exact profile identity or rights mutation")
    if (
        policy.get("oracle_id") != ORACLE_ID
        or policy.get("oracle_version") != ORACLE_VERSION
        or policy.get("rights_statement") != _RIGHTS
    ):
        raise ValueError("Westminster validation-policy identity or rights mutation")
    outer_profile = _strict(
        source_manifest.authority_path("outer-html-profile").read_bytes(),
        "Westminster outer HTML profile",
        canonical=False,
    )
    if outer_profile.get("boundaries") != {
        "textual_and_edition_acceptance": "unresolved; no retained authority selects or reconciles a provider reading",
        "rights_clearance": False,
        "human_acceptance": False,
        "canonical_promotion_authorized": False,
        "publication_authorized": False,
    }:
        raise ValueError("Westminster outer HTML acceptance boundary mutation")
    outer_authority = _authority(source_manifest, "outer-html-profile")
    expected_outer_binding = {
        "profile_path": outer_authority["path"],
        "profile_bytes": outer_authority["bytes"],
        "profile_sha256": outer_authority["sha256"],
        "assigned_paragraphs": 214,
        "outer_evidence_only_paragraphs": 26,
        "elements": 1044,
        "attributes": 1038,
        "nonempty_text_carriers": 645,
        "comments": 22,
        "policy": "Bind the complete parsed carrier stream. Only the 107 question paragraphs and 107 following proof paragraphs support assigned work content; every other carrier remains exact outer evidence only.",
    }
    source_scope = profile.get("source_scope")
    if (
        not isinstance(source_scope, Mapping)
        or source_scope.get("outer_html_accountability") != expected_outer_binding
    ):
        raise ValueError(
            "Westminster reconstruction profile outer HTML binding mutation"
        )
    forbidden = tuple(str(item) for item in policy.get("forbidden_import_prefixes", []))
    oracle_closure = _repository_import_closure(root, Path(__file__), forbidden)
    producer_path = (
        root / "build/tei/westminster_shorter_catechism_reconstruction.py"
    ).resolve(strict=True)
    producer_closure = _repository_import_closure(root, producer_path, forbidden)
    _assert_runtime_paths(root, oracle_closure, producer_closure)
    forbidden_answer_paths = tuple(
        str(item) for item in policy.get("forbidden_answer_paths", [])
    )
    if any(
        answer_path in (root / item["path"]).read_text(encoding="utf-8")
        for item in (*oracle_closure, *producer_closure)
        for answer_path in forbidden_answer_paths
    ):
        raise ValueError(
            "Westminster closure contains a forbidden campaign or legacy answer path"
        )
    oracle_closure_digest = _digest(oracle_closure)
    producer_closure_digest = _digest(producer_closure)
    if (
        profile.get("producer_import_closure_sha256") != producer_closure_digest
        or source_manifest.record.get("producer_import_closure_sha256")
        != producer_closure_digest
    ):
        raise ValueError("Westminster producer recursive import closure drift")
    _assert_rights_evidence(source_manifest)
    model = _independent_source_model(source_manifest)
    observed_counts = {
        "witnesses": 3,
        "groups_per_witness": 107,
        "metadata": 13,
        "number_labels": 321,
        "questions": 321,
        "answers": 321,
        "proof_groups": 107,
        "observations": 1083,
        "proof_reference_occurrences": len(model["relationships"]),
        "question_exact_agreements": model["question_exact_agreements"],
        "answer_exact_agreements": model["answer_exact_agreements"],
        "html_elements": model["outer_html_census"]["elements"]["total"],
        "html_attributes": model["outer_html_census"]["attributes"]["total"],
        "html_nonempty_text_carriers": model["outer_html_census"][
            "nonempty_text_carriers"
        ]["total"],
        "html_comments": model["outer_html_census"]["comments"]["total"],
        "html_outer_evidence_paragraphs": model["outer_html_census"][
            "paragraph_classes"
        ]["outer_evidence_only"],
    }
    if policy.get("required_counts") != observed_counts:
        raise ValueError("Westminster independent governed source census mutation")
    accountability_bytes = candidate.member_bytes("source-accountability.json")
    accountability = _strict(accountability_bytes, "Westminster accountability")
    expected_accountability = _expected_accountability(model)
    if accountability != expected_accountability or accountability_bytes != _canonical(
        expected_accountability
    ):
        raise ValueError(
            "Westminster exact observation or proof-relationship accountability mutation"
        )
    schema_bytes = source_manifest.authority_path(
        "source-accountability-schema"
    ).read_bytes()
    schema = _strict(schema_bytes, "Westminster accountability schema", canonical=False)
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(
            f"Westminster accountability schema failure: {errors[0].message}"
        )
    _verify_tei(candidate, model, source_manifest)
    expected_provenance = _expected_provenance(source_manifest)
    if candidate.member_bytes("provenance.json") != _canonical(expected_provenance):
        raise ValueError(
            "Westminster localized provenance, metadata, or rights mutation"
        )
    if candidate.member_bytes("unresolved.jsonl") != _expected_unresolved():
        raise ValueError(
            "Westminster unresolved edition, rights, or acceptance mutation"
        )
    if candidate.member_bytes("README.source.md") != _expected_readme():
        raise ValueError("Westminster source README or nonacceptance mutation")
    closure = oracle_closure_digest
    validator = source_manifest.record["validator"]
    if closure != validator["import_closure_sha256"]:
        raise ValueError("Westminster oracle recursive import closure drift")
    oracle_bytes = Path(__file__).read_bytes()
    xsd = _authority(source_manifest, "tei-p5-xsd")
    package_schema = _authority(source_manifest, "candidate-package-schema")
    validation_policy = _authority(source_manifest, "validation-policy")
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(oracle_bytes),
        "import_closure_sha256": closure,
        "runtime": _runtime(),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": str(package_schema["sha256"]),
        "source_sha256": _source_set_sha256(source_manifest),
        "xsd_sha256": str(xsd["sha256"]),
        "policy_sha256": str(validation_policy["sha256"]),
        "findings": [],
    }
    result["result_sha256"] = _digest(result)
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
