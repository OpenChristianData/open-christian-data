"""Focused raw-witness census, TEI conversion, and projection checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei.check_ledger import check_receipt
from build.tei.ia_fisher_marrow_to_tei import (
    RAW_PATH,
    _convert,
    census_fisher_marrow,
)
from build.tei.project_hf import project_file

REPO_ROOT = Path(__file__).resolve().parents[1]
TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS}

pytestmark = pytest.mark.requires_local_artifacts


def test_fisher_raw_census_records_ocr_evidence() -> None:
    census = census_fisher_marrow(RAW_PATH)
    structure = census["structure"]

    assert structure["body_start_line"] == 1285
    assert structure["form_feed_page_breaks"] == 0
    assert structure["chapter_headings"]["count"] == 4
    assert structure["parts"]["count"] == 2
    assert structure["commandment_headings"]["count"] == 8
    assert structure["section_markers"]["all_sect_prefixed_lines"] == 47
    assert structure["section_markers"]["structural_count"] == 41
    assert structure["section_markers"]["synopsis_count"] == 6
    assert structure["speaker_labels"]["high_confidence_count"] == 455
    assert structure["speaker_labels"]["ambiguous_unconverted_count"] == 123
    assert census["ocr_quality"]["greek_codepoints"] == 0
    assert census["ocr_quality"]["hebrew_codepoints"] == 0
    assert structure["inline_marker_counts"]["*"] == {"characters": 2039, "lines": 1758}
    assert structure["inline_marker_counts"]["†"] == {"characters": 0, "lines": 0}
    assert structure["inline_marker_counts"]["‡"] == {"characters": 0, "lines": 0}
    assert structure["inline_marker_counts"]["§"] == {"characters": 44, "lines": 44}


def test_fisher_conversion_is_stable_schema_valid_and_projects_with_receipt(tmp_path: Path) -> None:
    tei_path = tmp_path / "ir" / "fisher" / "fisher-marrow-of-modern-divinity.ia-ocr.tei.xml"
    second_tei_path = tmp_path / "ir" / "fisher" / "second.tei.xml"
    output_path = tmp_path / "ir" / "fisher" / "hf" / "fisher-marrow-of-modern-divinity.ia-ocr.jsonl"
    receipt_path = output_path.with_suffix(output_path.suffix + ".loss.json")

    _convert(RAW_PATH, tei_path)
    _convert(RAW_PATH, second_tei_path)
    assert tei_path.read_bytes() == second_tei_path.read_bytes()

    tree = etree.parse(str(tei_path))
    relaxng = etree.RelaxNG(
        etree.parse(str(REPO_ROOT / "ocd_kernel" / "tei" / "vendor" / "relaxng" / "tei_all.rng"))
    )
    assert relaxng.validate(tree), str(relaxng.error_log)

    census = census_fisher_marrow(RAW_PATH)
    expected = census["features"]
    observed = {
        "parts": len(tree.xpath('.//tei:div[@type="part"]', namespaces=NS)),
        "chapters": len(tree.xpath('.//tei:div[@type="chapter"]', namespaces=NS)),
        "commandments": len(tree.xpath('.//tei:div[@type="commandment"]', namespaces=NS)),
        "sections": len(tree.xpath('.//tei:div[@type="section"]', namespaces=NS)),
        "section_synopses": len(tree.xpath('.//tei:p[@rend="section-synopsis"]', namespaces=NS)),
        "page_breaks": len(tree.xpath('.//tei:pb', namespaces=NS)),
        "speaker_labels": len(tree.xpath('.//tei:speaker', namespaces=NS)),
    }
    assert {key: value["count"] for key, value in expected.items()} == observed

    tei_text = "".join(tree.getroot().itertext())
    assert "CHAPTER TL" in tei_text
    assert "CHAP. LV." in tei_text
    assert "COMMANDMENT VHI." in tei_text
    speaker_values = {"".join(node.itertext()) for node in tree.xpath('.//tei:speaker', namespaces=NS)}
    assert "Evan." in speaker_values
    assert "Norn." in speaker_values
    assert "iVeo." in speaker_values

    receipt = project_file(tei_path, output_path, receipt_path=receipt_path, repo_root=tmp_path)
    assert check_receipt(receipt_path, repo_root=tmp_path) == []
    records = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    projected_text = "\n".join(record["text"] for record in records)
    assert all(label in projected_text for label in speaker_values)
    assert receipt["classes"]["sp"]["delivered"] == expected["speaker_labels"]["count"]
    assert receipt["classes"]["speaker"]["delivered"] == expected["speaker_labels"]["count"]
