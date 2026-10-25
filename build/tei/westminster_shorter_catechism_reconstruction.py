"""Direct, nonaccepting three-witness Westminster Shorter Catechism reconstruction."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Mapping

from lxml import etree, html

from build.tei.westminster_shorter_catechism_carrier_census import (
    verify_html_carrier_census,
)
from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-westminster-shorter-catechism-three-witnesses-to-tei"
CONVERTER_VERSION = "2"
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
_BOOKS = {
    "1 chr": "1Chr",
    "1 cor": "1Cor",
    "1 john": "1John",
    "1 kings": "1Kgs",
    "1 pet": "1Pet",
    "1 sam": "1Sam",
    "1 thess": "1Thess",
    "1 tim": "1Tim",
    "2 cor": "2Cor",
    "2 sam": "2Sam",
    "2 thess": "2Thess",
    "2 tim": "2Tim",
    "3 john": "3John",
    "acts": "Acts",
    "amos": "Amos",
    "col": "Col",
    "dan": "Dan",
    "deut": "Deut",
    "ecc": "Eccl",
    "eph": "Eph",
    "esther": "Esth",
    "ex": "Exod",
    "ezek": "Ezek",
    "gal": "Gal",
    "gen": "Gen",
    "heb": "Heb",
    "isa": "Isa",
    "jas": "Jas",
    "jer": "Jer",
    "job": "Job",
    "joel": "Joel",
    "john": "John",
    "lam": "Lam",
    "lev": "Lev",
    "luke": "Luke",
    "mal": "Mal",
    "mark": "Mark",
    "matt": "Matt",
    "mic": "Mic",
    "neh": "Neh",
    "phil": "Phil",
    "prov": "Prov",
    "ps": "Ps",
    "rev": "Rev",
    "rom": "Rom",
    "titus": "Titus",
    "zech": "Zech",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _authority(manifest: SourceManifest, name: str) -> Mapping[str, object]:
    for item in manifest.record["authorities"]:
        if isinstance(item, Mapping) and item.get("name") == name:
            return item
    raise ValueError(f"missing Westminster authority {name}")


def _normalize(value: str) -> str:
    return " ".join(value.split())


def _book_prefix(value: str) -> tuple[str, int] | None:
    lowered = value.strip().lower()
    for alias in sorted(_BOOKS, key=len, reverse=True):
        match = re.match(rf"^{re.escape(alias)}\.?(?=\s)", lowered)
        if match:
            return _BOOKS[alias], match.end()
    return None


def _segments(citation: str) -> list[str]:
    normalized = re.sub(
        r"\s+with\s+", "; ", citation.strip().rstrip("."), flags=re.IGNORECASE
    )
    result: list[str] = []
    for semicolon_part in normalized.split(";"):
        accumulated = ""
        for comma_part in (part.strip() for part in semicolon_part.split(",")):
            if not comma_part:
                continue
            if accumulated and _book_prefix(comma_part):
                result.append(accumulated)
                accumulated = comma_part
            elif accumulated:
                accumulated = f"{accumulated}, {comma_part}"
            else:
                accumulated = comma_part
        if accumulated:
            result.append(accumulated)
    return [
        re.sub(r"\s+title\b", "", item, flags=re.IGNORECASE).strip() for item in result
    ]


def _reference(raw: str, inherited_book: str | None) -> tuple[dict[str, object], str]:
    prefix = _book_prefix(raw)
    if prefix:
        book, length = prefix
        remainder = raw.strip()[length:].strip()
    else:
        if inherited_book is None or not re.match(r"^\d+:\d", raw):
            raise ValueError(f"unknown or orphan Westminster citation {raw!r}")
        book = inherited_book
        remainder = raw.strip()
    if ":" in remainder:
        chapter, verses = (part.strip() for part in remainder.split(":", 1))
    else:
        chapter, verses = remainder, ""
    if not chapter.isdigit():
        raise ValueError(f"invalid Westminster citation chapter {raw!r}")
    osis: list[str] = []
    if not verses:
        osis.append(f"{book}.{chapter}")
    else:
        if not re.fullmatch(r"\d+(?:-\d+)?(?:,\s*\d+(?:-\d+)?)*", verses):
            raise ValueError(f"invalid Westminster citation verses {raw!r}")
        for value in (item.strip() for item in verses.split(",")):
            if "-" in value:
                start, end = (item.strip() for item in value.split("-", 1))
                osis.append(f"{book}.{chapter}.{start}-{book}.{chapter}.{end}")
            else:
                osis.append(f"{book}.{chapter}.{value}")
    return {"raw": raw, "osis": osis}, book


def _source_model(manifest: SourceManifest) -> dict[str, object]:
    creeds = _strict(
        manifest.authority_path("creeds-wsc").read_bytes(), "Creeds WSC witness"
    )
    theologai = _strict(
        manifest.authority_path("theologai-wsc").read_bytes(),
        "TheologAI WSC witness",
    )
    creeds_rows = creeds.get("Data")
    theologai_rows = theologai.get("sections")
    if not isinstance(creeds_rows, list) or not isinstance(theologai_rows, list):
        raise ValueError("Westminster JSON witness rows must be arrays")
    readings: dict[str, list[dict[str, object]]] = {
        "creeds-json": [
            {
                "number": int(row["Number"]),
                "question": str(row["Question"]),
                "answer": str(row["Answer"]),
            }
            for row in creeds_rows
        ],
        "theologai-json": [
            {
                "number": int(row["question"]),
                "question": str(row["q"]),
                "answer": str(row["a"]),
            }
            for row in theologai_rows
        ],
    }
    html_bytes = manifest.authority_path("westminster-standard-wsc").read_bytes()
    outer_profile = _strict(
        manifest.authority_path("outer-html-profile").read_bytes(),
        "Westminster outer HTML profile",
    )
    outer_census = verify_html_carrier_census(
        html_bytes,
        outer_profile["census"],
    )
    document = html.fromstring(html_bytes)
    html_rows: list[dict[str, object]] = []
    relationships: list[dict[str, object]] = []
    for paragraph in document.xpath("//p"):
        bold = paragraph.xpath("./b")
        if not bold or not _normalize("".join(bold[0].itertext())).startswith("Q."):
            continue
        match = re.match(
            r"^Q\.\s*(\d+)\.\s*(.*?)\s+A\.\s*(.*)$",
            _normalize(paragraph.text_content()),
        )
        if match is None:
            raise ValueError("unsupported Westminster HTML question structure")
        number = int(match.group(1))
        proof = paragraph.getnext()
        if proof is None or etree.QName(proof).localname != "p":
            raise ValueError(f"missing Westminster proof group Q{number}")
        proof_text = _normalize(proof.text_content())
        emphasis = [
            _normalize("".join(node.itertext())) for node in proof.xpath("./em")
        ]
        if not emphasis:
            raise ValueError(f"missing Westminster emphasized proof text Q{number}")
        inherited: str | None = None
        references = []
        for occurrence, raw in enumerate(_segments(" ".join(emphasis)), start=1):
            parsed, inherited = _reference(raw, inherited)
            references.append(parsed)
            relationships.append(
                {
                    "id": f"wsc-proof-q{number}-{occurrence}",
                    "question_number": number,
                    "occurrence": occurrence,
                    "raw": parsed["raw"],
                    "osis": parsed["osis"],
                    "source": "westminster-standard-html",
                    "proof_group": f"#wsc-westminster-standard-html-q{number}-proof-group",
                    "target": f"#wsc-westminster-standard-html-q{number}-proof-{occurrence}",
                }
            )
        html_rows.append(
            {
                "number": number,
                "question": match.group(2),
                "answer": match.group(3),
                "proof_group": proof_text,
                "references": references,
            }
        )
    readings["westminster-standard-html"] = html_rows
    expected = list(range(1, 108))
    if any(
        [int(row["number"]) for row in rows] != expected for rows in readings.values()
    ):
        raise ValueError("every Westminster witness must contain ordered Q1-Q107")
    metadata = creeds.get("Metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Creeds WSC metadata must be an object")
    metadata_records = [
        {"source": "creeds-json", "key": key, "value": value}
        for key, value in metadata.items()
    ] + [
        {"source": "theologai-json", "key": key, "value": theologai[key]}
        for key in ("title", "type", "date")
    ]
    if len(metadata_records) != 13 or len(relationships) != 401:
        raise ValueError("Westminster metadata or proof-reference census drift")
    by_source = {
        source: {int(row["number"]): row for row in rows}
        for source, rows in readings.items()
    }
    question_agreements = sum(
        len({str(by_source[source][number]["question"]) for source in by_source}) == 1
        for number in expected
    )
    answer_agreements = sum(
        len({str(by_source[source][number]["answer"]) for source in by_source}) == 1
        for number in expected
    )
    return {
        "metadata": metadata_records,
        "readings": readings,
        "relationships": relationships,
        "question_exact_agreements": question_agreements,
        "answer_exact_agreements": answer_agreements,
        "outer_html_census": outer_census,
    }


def _node(
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


def _build_tei(model: Mapping[str, object], manifest: SourceManifest) -> bytes:
    tei = etree.Element(f"{{{_TEI}}}TEI", nsmap={None: _TEI})
    tei.set(_XML_ID, "westminster-shorter-catechism-three-witness-candidate")
    header = _node(tei, "teiHeader")
    file_desc = _node(header, "fileDesc")
    title_stmt = _node(file_desc, "titleStmt")
    _node(
        title_stmt,
        "title",
        text="Westminster Shorter Catechism — three retained provider renderings",
    )
    _node(
        title_stmt,
        "author",
        {"ana": "#source-claim"},
        "Westminster Assembly (Creeds.json metadata and local-config claim)",
    )
    for provider in ("Creeds.json", "TheologAI", "The Westminster Standard"):
        resp = _node(title_stmt, "respStmt")
        _node(resp, "resp", text="Retained source witness provider")
        _node(resp, "name", text=provider)
    publication = _node(file_desc, "publicationStmt")
    _node(publication, "publisher", text="Open Christian Data")
    availability = _node(publication, "availability", {"status": "restricted"})
    _node(
        availability,
        "p",
        text="Nonaccepted reconstruction candidate. Publication is not authorized; edition identity and acquisition-specific rights require human review.",
    )
    source_desc = _node(file_desc, "sourceDesc")
    source_list = _node(source_desc, "listBibl", {"type": "retained-witnesses"})
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
        bibl = _node(source_list, "bibl", {"xml:id": f"source-{witness_id}"})
        _node(bibl, "title", text=witness_id)
        _node(bibl, "ptr", {"target": str(authority["path"])})
        _node(bibl, "idno", {"type": "sha256"}, str(authority["sha256"]))
        _node(bibl, "note", {"type": "rights-status"}, rights)
        _node(
            bibl,
            "note",
            {"type": "edition-status"},
            "Provider rendering only; no selected-reading or edition authority.",
        )
    metadata_list = _node(source_desc, "list", {"type": "source-metadata-claims"})
    for index, item in enumerate(model["metadata"], start=1):
        _node(
            metadata_list,
            "item",
            {"xml:id": f"wsc-metadata-{index:03d}", "n": str(index)},
            f"{item['source']}:{item['key']}={json.dumps(item['value'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))}",
        )
    encoding = _node(header, "encodingDesc")
    _node(
        encoding,
        "p",
        text="All three ordered witness renderings are represented separately. No reading is normalized, selected, or conflated.",
    )
    text = _node(tei, "text")
    group = _node(text, "group", {"xml:id": "wsc-retained-witnesses"})
    for witness_id in ("creeds-json", "theologai-json", "westminster-standard-html"):
        witness_text = _node(
            group, "text", {"xml:id": f"wsc-witness-{witness_id}", "n": witness_id}
        )
        body = _node(witness_text, "body")
        for row in model["readings"][witness_id]:
            number = int(row["number"])
            unit = _node(
                body,
                "div",
                {
                    "type": "question-unit",
                    "n": str(number),
                    "xml:id": f"wsc-{witness_id}-q{number}",
                },
            )
            _node(
                unit,
                "label",
                {"type": "number", "xml:id": f"wsc-{witness_id}-q{number}-number"},
                str(number),
            )
            _node(
                unit,
                "p",
                {"ana": "#question", "xml:id": f"wsc-{witness_id}-q{number}-question"},
                str(row["question"]),
            )
            _node(
                unit,
                "p",
                {"ana": "#answer", "xml:id": f"wsc-{witness_id}-q{number}-answer"},
                str(row["answer"]),
            )
            if witness_id == "westminster-standard-html":
                proofs = _node(
                    unit,
                    "listBibl",
                    {
                        "type": "proof-group",
                        "xml:id": f"wsc-{witness_id}-q{number}-proof-group",
                    },
                )
                for occurrence, reference in enumerate(row["references"], start=1):
                    bibl = _node(
                        proofs,
                        "bibl",
                        {"xml:id": f"wsc-{witness_id}-q{number}-proof-{occurrence}"},
                    )
                    _node(
                        bibl,
                        "ref",
                        {"type": "scripture", "cRef": " ".join(reference["osis"])},
                        str(reference["raw"]),
                    )
    return etree.tostring(
        tei, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )


def _accountability(model: Mapping[str, object]) -> dict[str, object]:
    crosswalk: list[dict[str, object]] = []
    for index, item in enumerate(model["metadata"], start=1):
        crosswalk.append(
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
    for witness_id in ("creeds-json", "theologai-json", "westminster-standard-html"):
        for row in model["readings"][witness_id]:
            number = int(row["number"])
            for kind in ("number", "question", "answer"):
                value = number if kind == "number" else row[kind]
                crosswalk.append(
                    {
                        "id": f"wsc-observation-{witness_id}-q{number}-{kind}",
                        "source": witness_id,
                        "kind": kind,
                        "source_location": f"/questions/{number}/{kind}",
                        "value": value,
                        "status": "represented",
                        "target": f"#wsc-{witness_id}-q{number}-{kind}",
                    }
                )
    for row in model["readings"]["westminster-standard-html"]:
        number = int(row["number"])
        crosswalk.append(
            {
                "id": f"wsc-observation-westminster-standard-html-q{number}-proof-group",
                "source": "westminster-standard-html",
                "kind": "proof-group",
                "source_location": f"/questions/{number}/proof-group",
                "value": row["proof_group"],
                "status": "represented",
                "target": f"#wsc-westminster-standard-html-q{number}-proof-group",
            }
        )
    if len(crosswalk) != 1083:
        raise ValueError("Westminster observation crosswalk drift")
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
        "proof_reference_count": len(model["relationships"]),
        "question_exact_agreements": model["question_exact_agreements"],
        "answer_exact_agreements": model["answer_exact_agreements"],
        "outer_html_census": model["outer_html_census"],
        "crosswalk": crosswalk,
        "proof_relationships": model["relationships"],
    }


def _provenance(manifest: SourceManifest) -> dict[str, object]:
    config = _strict(
        manifest.authority_path("local-source-config").read_bytes(),
        "Westminster local source config",
    )
    names = ("creeds-wsc", "theologai-wsc", "westminster-standard-wsc")
    rights_names = ("creeds-readme", "theologai-readme", "theologai-license")
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
            for name in names
        ],
        "rights_evidence": [
            {
                key: _authority(manifest, name)[key]
                for key in ("name", "path", "bytes", "sha256")
            }
            for name in rights_names
        ],
        "outer_html_profile": {
            key: _authority(manifest, "outer-html-profile")[key]
            for key in ("name", "path", "bytes", "sha256")
        },
        "reading_policy": "three exact provider renderings represented separately; no selected reading",
        "rights": _RIGHTS,
    }


def _unresolved() -> bytes:
    records = (
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
    return b"".join(_canonical(record) for record in records)


def _readme() -> bytes:
    return (
        "# Westminster Shorter Catechism source accountability\n\n"
        "This reconstruction candidate has six package members and preserves three exact retained provider renderings: Creeds.json, TheologAI, and The Westminster Standard. Each contains Q1-Q107. All 1,083 source observations and all 401 ordered proof-reference occurrences are bound without selecting or normalizing an edition reading. The retained HTML's complete parsed carrier stream is independently classified: the 214 question/proof paragraphs support assigned content, while every other element, attribute, nonempty text carrier, and comment remains bound as outer evidence only. The Q37 occurrence `Job 19:26-27` is retained; the older 400-reference JSON projection is not authority.\n\n"
        "The candidate is explicitly nonaccepted and publication is not authorized. Creeds.json supplies Unlicense evidence and does not list this work among its named exceptions. TheologAI's ISC license covers software, not historical-document redistribution. The cached Westminster Standard page carries a 2016 copyright footer and no retained text or proof-apparatus license. Edition genealogy and worldwide rights remain unresolved and require human review.\n"
    ).encode("utf-8")


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = _strict(
        source_manifest.authority_path("reconstruction-profile").read_bytes(),
        "Westminster profile",
    )
    policy = _strict(
        source_manifest.authority_path("validation-policy").read_bytes(),
        "Westminster validation policy",
    )
    outer_profile = _strict(
        source_manifest.authority_path("outer-html-profile").read_bytes(),
        "Westminster outer HTML profile",
    )
    if profile.get("profile_id") != _PROFILE_ID or profile.get("rights") != _RIGHTS:
        raise ValueError("Westminster profile identity or rights drift")
    if policy.get("rights_statement") != _RIGHTS:
        raise ValueError("Westminster validation rights drift")
    if outer_profile.get("boundaries") != {
        "textual_and_edition_acceptance": "unresolved; no retained authority selects or reconciles a provider reading",
        "rights_clearance": False,
        "human_acceptance": False,
        "canonical_promotion_authorized": False,
        "publication_authorized": False,
    }:
        raise ValueError("Westminster outer HTML acceptance boundary drift")
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
        raise ValueError("Westminster reconstruction profile outer HTML binding drift")
    model = _source_model(source_manifest)
    expected_counts = policy.get("required_counts")
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
    if expected_counts != observed_counts:
        raise ValueError("Westminster governed source census drift")
    return {
        "content.tei.xml": _build_tei(model, source_manifest),
        "source-accountability.json": _canonical(_accountability(model)),
        "provenance.json": _canonical(_provenance(source_manifest)),
        "unresolved.jsonl": _unresolved(),
        "README.source.md": _readme(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
