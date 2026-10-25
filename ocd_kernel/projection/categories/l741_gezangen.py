"""Bounded text-only hymn rows for the DBNL 1806 Evangelische Gezangen witness."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from lxml import etree

from ocd_kernel.library._common import PipelineError


WORK_ID = "evangelische-gezangen-1806"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_SHA256 = "d8132943dd20b1053d1d77bda57cab2b69c9dc567e38ea4450baab914925abb9"
MAPPING_VERSION = "ocd-l741-gezangen-text-only-v1"
ASSEMBLER_VERSION = "ocd-hymns-assembler-provisional-v1"
HYMNS = 192
POEM_GROUPS = 197
SCORE_FIGURES = 68
INDEX_TABLES = 26
DIVISION_IDS_SHA256 = "137f1385160f2cca59b0787a6092535c538d8dd4f22c751ffa32009519adf879"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _parse(path: Path) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False)
    return etree.fromstring(path.read_bytes(), parser)


def _name(node: etree._Element) -> str:
    return etree.QName(node).localname


def _text(node: etree._Element) -> str:
    return "".join(node.itertext()).strip()


def _poem_stanzas(group: etree._Element) -> list[dict[str, Any]]:
    stanzas: list[dict[str, Any]] = []
    lines: list[str] = []
    number: int | None = None

    def finish() -> None:
        nonlocal lines, number
        if lines:
            stanzas.append({"number": number if number is not None else len(stanzas) + 1, "lines": lines})
            lines = []
            number = None

    for child in group:
        tag = _name(child)
        if tag in {"head", "pb"}:
            continue
        if tag != "l":
            raise PipelineError(f"L741 poem contains unsupported {tag}")
        value = _text(child)
        if not value:
            finish()
        elif re.fullmatch(r"[0-9]+\.", value) and child.get("rend") == "; 4tab":
            finish()
            number = int(value[:-1])
        else:
            lines.append(value)
    finish()
    if not stanzas or any(not stanza["lines"] for stanza in stanzas):
        raise PipelineError("L741 poem has no readable stanza")
    return stanzas


def _rows(tree: etree._Element, *, identity: Mapping[str, str], language: str,
          representation_revision: str, edition_title: str, source: bool) -> list[dict[str, Any]]:
    if source:
        if _name(tree) != "TEI.2":
            raise PipelineError("L741 retained source must be DBNL TEI.2")
        all_divisions = tree.xpath("/TEI.2/text/body/div")
        if len(all_divisions) != 198:
            raise PipelineError("L741 retained-source front, hymn, or back divisions changed")
        divisions = all_divisions[2:194]
    else:
        if tree.tag != f"{{{TEI_NS}}}TEI":
            raise PipelineError("L741 master must be TEI P5")
        divisions = tree.xpath("/t:TEI/t:text/t:body/t:div", namespaces={"t": TEI_NS})
        ids = [division.get(XML_ID) for division in divisions]
        if any(not value for value in ids) or _sha("|".join(ids).encode("utf-8")) != DIVISION_IDS_SHA256:
            raise PipelineError("L741 source-bound hymn division IDs or order changed")
    if len(divisions) != HYMNS:
        raise PipelineError(f"L741 requires {HYMNS} ordered source hymn divisions")
    result: list[dict[str, Any]] = []
    part_title: str | None = None
    poem_total = 0
    for sequence, division in enumerate(divisions, 1):
        if _name(division) != "div":
            raise PipelineError("L741 hymn boundary differs")
        if any(_name(child) not in {"head", "lg", "interpGrp", "pb"} for child in division):
            raise PipelineError(f"L741 hymn {sequence} contains unaccounted content")
        heads = [node for node in division if _name(node) == "head"]
        part = [node for node in heads if node.get("rend") == "h2"]
        titles = [node for node in heads if node.get("rend") == "h3"]
        if len(part) > 1 or len(titles) != 1 or len(heads) != len(part) + 1:
            raise PipelineError(f"L741 hymn {sequence} heading ownership differs")
        if part:
            part_title = _text(part[0])
        title = _text(titles[0])
        groups = [node for node in division if _name(node) == "lg" and node.get("type") == "poem"]
        if any(_name(node) == "lg" and node.get("type") != "poem" for node in division):
            raise PipelineError(f"L741 hymn {sequence} has another text group")
        expected_groups = 6 if sequence == 46 else 1
        if len(groups) != expected_groups:
            raise PipelineError(f"L741 hymn {sequence} has {len(groups)} poem groups, expected {expected_groups}")
        poem_total += len(groups)
        sections: list[dict[str, Any]] = []
        stanzas: list[dict[str, Any]] = []
        for group in groups:
            section_heads = [node for node in group if _name(node) == "head"]
            if len(section_heads) != (1 if sequence == 46 else 0):
                raise PipelineError(f"L741 hymn {sequence} section labels differ")
            label = _text(section_heads[0]) if section_heads else None
            section_stanzas = _poem_stanzas(group)
            sections.append({"label": label, "stanzas": section_stanzas})
            stanzas.extend(section_stanzas)
        readable = "\n\n".join("\n".join(stanza["lines"]) for stanza in stanzas)
        text_id = "text-" + _sha((title + "\n" + readable).encode("utf-8"))[:20]
        row = {
            **{key: identity[key] for key in ("work_id", "textual_form_id", "edition_id")},
            "record_id": f"{identity['edition_id']}:hymn:{sequence:03d}",
            "sequence": sequence,
            "category": "hymns",
            "language": language,
            "text": readable,
            "representation_revision": representation_revision,
            "locator": {"kind": "hymn-occurrence", "text_part": "body",
                        "part_titles": [part_title] if part_title else [],
                        "divisions": [{"order": sequence, "type": "hymn", "titles": [title]}],
                        "occurrence": sequence},
            "provenance": {"edition_title": edition_title},
            "notes": [],
            "references": [],
            "occurrence_id": f"l741-{sequence:03d}",
            "hymn_text_id": text_id,
            "title": title,
            "first_line": stanzas[0]["lines"][0],
            "stanzas": stanzas,
            "segments": [{"kind": "stanza", **stanza} for stanza in stanzas],
            "sections": sections,
        }
        result.append(row)
    if poem_total != POEM_GROUPS or len(result[45]["sections"]) != 6:
        raise PipelineError("L741 hymn and poem-group accounting differs")
    return result


def _disposition(tree: etree._Element) -> dict[str, Any]:
    ns = {"t": TEI_NS}
    front = tree.xpath("/t:TEI/t:text/t:front/*", namespaces=ns)
    back = tree.xpath("/t:TEI/t:text/t:back/t:div", namespaces=ns)
    body = tree.xpath("/t:TEI/t:text/t:body/t:div", namespaces=ns)
    if (len(front) != 3 or len(back) != 4 or len(body) != HYMNS
            or len(tree.xpath("/t:TEI/t:text/t:back//t:graphic", namespaces=ns)) != SCORE_FIGURES
            or len(tree.xpath("/t:TEI/t:text/t:back//t:table", namespaces=ns)) != INDEX_TABLES
            or len(tree.xpath("/t:TEI/t:text/t:back//t:lg[@type='poem']", namespaces=ns)) != 68):
        raise PipelineError("L741 excluded front/back or score inventory differs")
    return {
        "included_hymn_divisions": HYMNS,
        "included_hymn_poem_groups": POEM_GROUPS,
        "excluded_front_children": 3,
        "excluded_back_divisions": 4,
        "excluded_back_poem_groups": 68,
        "excluded_score_gifs": SCORE_FIGURES,
        "excluded_index_tables": INDEX_TABLES,
        "excluded_areas": [
            "front title matter and two prefatory divisions",
            "back hymn lists and alphabetical register",
            "back tune register with 68 score GIFs and 68 poem groups",
            "back index tables and final errata division",
            "source typography and page-break display (the full TEI retains both)",
        ],
    }


def _receipt(tei_path: Path, rows: list[dict[str, Any]], disposition: dict[str, Any],
             source_sha256: str) -> dict[str, Any]:
    schema = Path(__file__).resolve().parents[3] / "schemas/v2/categories/hymns.schema.json"
    common = schema.parents[1] / "public-row.schema.json"
    return {
        "mapping_version": MAPPING_VERSION,
        "assembler_version": ASSEMBLER_VERSION,
        "master_sha256": _sha(tei_path.read_bytes()),
        "source_sha256": source_sha256,
        "source_credit": {
            "provider": "DBNL (KB, nationale bibliotheek)",
            "recommended_credit": "geraadpleegd via DBNL (KB, nationale bibliotheek)",
            "title_terms": "https://www.dbnl.org/titels/gebruiksvoorwaarden.php?id=_eva005evan01",
            "rights_clearance": "not-determined",
        },
        "policy_sha256": _sha(schema.read_bytes()),
        "common_schema_sha256": _sha(common.read_bytes()),
        "output_sha256": _sha(_canonical(rows)),
        "row_count": len(rows),
        "anchors": [{"record_id": row["record_id"], "source_order": row["sequence"],
                     "text_sha256": _sha(row["text"].encode("utf-8")),
                     "section_count": len(row["sections"])} for row in rows],
        "inventory": [{"hymn": row["sequence"], "section_count": len(row["sections"]),
                       "stanza_count": len(row["stanzas"])} for row in rows],
        "references": [],
        "warnings": ["Text-only L741 selection excludes the named front and back matter and 68 score GIFs; consult the source notice."],
        "exclusions": [
            {"scope": "TEI/text/front/*", "count": 3,
             "reason": "title matter and two prefatory divisions are outside the 192 source hymn texts"},
            {"scope": "TEI/text/back/div", "count": 4,
             "reason": "hymn lists, tune and alphabetical registers, indexes, and errata are outside the text-only selection"},
            {"scope": "TEI/text/back//graphic", "count": 68,
             "reason": "the first release does not package the 68 score GIF resources"},
            {"scope": "TEI/text/back//lg[@type='poem']", "count": 68,
             "reason": "tune/register material is outside the 192 body hymn texts"},
            {"scope": "TEI/text/back//table", "count": 26,
             "reason": "back indexes and registers are outside the text-only selection"},
            {"scope": "TEI/text/body//pb and source formatting", "count": None,
             "reason": "public text rows omit display/page markers while the full TEI retains them"},
        ],
        "source_disposition": disposition,
        "unsupported": [],
        "independent_check": {"status": "pending", "errors": []},
    }


def project_l741_document(tei_path: Path, *, retained_path: Path, identity: Mapping[str, str],
                          language: str, representation_revision: str, edition_title: str) -> dict[str, Any]:
    if identity.get("work_id") != WORK_ID or language != "nl":
        raise PipelineError("L741 projection identity or language differs")
    if _sha(retained_path.read_bytes()) != SOURCE_SHA256:
        raise PipelineError("L741 retained source changed")
    tree = _parse(tei_path)
    rows = _rows(tree, identity=identity, language=language,
                 representation_revision=representation_revision, edition_title=edition_title, source=False)
    disposition = _disposition(tree)
    receipt = _receipt(tei_path, rows, disposition, SOURCE_SHA256)
    from .hymns import _validator
    validator = _validator()
    for row in rows:
        errors = list(validator.iter_errors(row))
        if errors:
            raise PipelineError(f"L741 public row schema error: {errors[0].message}")
    return {"rows": rows, "receipt": receipt}


def verify_l741_document(tei_path: Path, rows: list[dict[str, Any]], receipt: Mapping[str, Any], *,
                         retained_path: Path, identity: Mapping[str, str], language: str,
                         representation_revision: str, edition_title: str) -> list[str]:
    """Compare rows with retained TEI.2, using the producer's row/stanza mapping helpers."""
    errors: list[str] = []
    try:
        if _sha(retained_path.read_bytes()) != SOURCE_SHA256:
            raise PipelineError("L741 retained source changed")
        source = _parse(retained_path)
        expected_rows = _rows(source, identity=identity, language=language,
                              representation_revision=representation_revision, edition_title=edition_title,
                              source=True)
        if rows != expected_rows:
            errors.append("L741 rows differ from 192 ordered source hymn divisions or six-part hymn XLVI")
        tree = _parse(tei_path)
        disposition = _disposition(tree)
        expected = _receipt(tei_path, expected_rows, disposition, SOURCE_SHA256)
        if dict(receipt) != expected:
            errors.append("L741 projection receipt or exclusions differ")
        from .hymns import _validator
        validator = _validator()
        for index, row in enumerate(rows, 1):
            for finding in validator.iter_errors(row):
                errors.append(f"L741 row {index} schema: {finding.message}")
    except (OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError, PipelineError) as exc:
        errors.append(str(exc))
    return errors
