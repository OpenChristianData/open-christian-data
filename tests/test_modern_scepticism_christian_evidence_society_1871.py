"""Focused contract tests for the Modern Scepticism Gutenberg candidate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei.modern_scepticism_christian_evidence_society_1871 import (
    EXPECTED_SOURCE_SHA256,
    EXPECTED_SOURCE_TEXT_SHA256,
    SourceMismatchError,
    audit_source,
    build_candidate,
    resolve_source_path,
    write_determinism_report,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    REPO_ROOT
    / "sources"
    / "structured-text"
    / "modern-scepticism-christian-evidence-society-1871"
    / "config.json"
)


def test_source_config_binds_exact_1871_witness() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["resource_id"] == "modern-scepticism-christian-evidence-society-1871"
    assert config["gutenberg_id"] == 42957
    assert config["original_publication_year"] == 1871
    assert config["source_hash"] == f"sha256:{EXPECTED_SOURCE_SHA256}"
    assert config["source_type"] == "gutenberg_xhtml"
    assert config["license"] == "public-domain"
    assert config["output_file"].startswith(
        "reports/clean-ready-acquisition-to-tei/master-4/28/"
    )


def test_retained_package_hashes_and_current_html_container() -> None:
    audit = audit_source(resolve_source_path(REPO_ROOT), repository_root=REPO_ROOT)
    assert audit["source_sha256"] == EXPECTED_SOURCE_SHA256
    assert audit["package_hashes"] == {
        "42957-0.txt": "7f05726c0d5f5a80905312d94a12edd05b9bed3de2d041cf53a37fcc42b802dd",
        "42957-h.htm": "e8130d330cc70a9f1169ef888869dbd7b146ff78b5b1bef0e8d56cc5995206e8",
        "files-index.html": "ae6ba79ab0cdb72da34b7eb1d521176818f292d0714d3c67d0b7c7f144bd23ac",
        "landing.html": "d9f84e1ceb6d4f4bed1875ec02401a5a0218eeb6a9b2fe8778b61112b55b2619",
        "legacy-html-index.html": "4bde71582359f61d88e708e6ad300b14152126572a70dd157e643db2246ad636",
        "pg42957-h.zip": "693e834f22a0ea8b2ca941b3b97a9db2f04f3db6cf965c67f8a9649be290ef82",
        "pg42957-images.html": "bde59500adb52ce884499f9ecc82cb6531c77535bf4aab0646653ca6425c5bf9",
        "pg42957.txt": "d0e8650863bbf193b9fe74a8549edda9ac405d3bf41ac652dd471f1921c599a2",
    }
    assert audit["zip_member_mismatches"] == []
    assert audit["current_html_zip_members"] == [
        "images/cover.jpg",
        "pg42957-images.html",
    ]
    assert audit["cover_sha256"] == (
        "03aa3bb12343e85f60c9b3b0379a4dc6115378c0128cb62a7f57fbad06f4f884"
    )


def test_source_census_preserves_lectures_notes_typography_and_terminal_matter() -> None:
    audit = audit_source(resolve_source_path(REPO_ROOT), repository_root=REPO_ROOT)
    assert audit["source_text_characters"] == 731071
    assert audit["source_text_sha256"] == EXPECTED_SOURCE_TEXT_SHA256
    assert audit["ids_unique"] is True
    assert audit["unresolved_internal_targets"] == []
    assert audit["tag_counts"]["p"] == 818
    assert audit["tag_counts"]["table"] == 1
    assert audit["tag_counts"]["tr"] == 26
    assert audit["tag_counts"]["td"] == 40
    assert audit["footnotes"] == 181
    assert audit["footnote_references"] == 362
    assert audit["page_markers"] == 526
    assert audit["poetry_containers"] == 22
    assert audit["lecture_heads"] == [
        "DESIGN IN NATURE.",
        "PANTHEISM.",
        "POSITIVISM.",
        "SCIENCE AND REVELATION.",
        "THE NATURE AND VALUE OF THE MIRACULOUS TESTIMONY TO CHRISTIANITY.",
        "THE GRADUAL DEVELOPMENT OF REVELATION.",
        "THE ALLEGED HISTORICAL DIFFICULTIES OF THE OLD AND NEW TESTAMENTS, AND THE LIGHT THROWN ON THEM BY MODERN DISCOVERIES.",
        "MYTHICAL THEORIES OF CHRISTIANITY.",
        "THE EVIDENTIAL VALUE OF ST. PAUL'S EPISTLES.",
        "CHRIST'S TEACHING AND INFLUENCE ON THE WORLD.",
        "THE COMPLETENESS AND ADEQUACY OF THE EVIDENCES OF CHRISTIANITY.",
        "EXPLANATORY PAPER",
    ]
    assert audit["transcribers_notes_present"] is True
    assert audit["printer_line"] == "Watson & Hazell, Printers, London and Aylesbury."
    assert audit["project_gutenberg_end_marker"] == (
        "*** END OF THE PROJECT GUTENBERG EBOOK 42957 ***"
    )


def test_candidate_is_valid_complete_and_fresh_run_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = resolve_source_path(REPO_ROOT)
    candidate_a = tmp_path / "a" / "modern-scepticism.tei.xml"
    validation_a = tmp_path / "a" / "validation.json"
    candidate_b = tmp_path / "b" / "modern-scepticism.tei.xml"
    validation_b = tmp_path / "b" / "validation.json"

    result_a = build_candidate(source, candidate_a, validation_a, repository_root=REPO_ROOT)
    result_b = build_candidate(source, candidate_b, validation_b, repository_root=REPO_ROOT)
    assert result_a == result_b
    assert candidate_a.read_bytes() == candidate_b.read_bytes()
    assert validation_a.read_bytes() == validation_b.read_bytes()
    assert result_a["tei_p5_relaxng_valid"] is True
    assert result_a["source_candidate_text_match"] is True
    assert result_a["source_text_sha256"] == EXPECTED_SOURCE_TEXT_SHA256
    assert result_a["candidate_text_sha256"] == EXPECTED_SOURCE_TEXT_SHA256
    assert result_a["lecture_divisions"] == 12
    assert result_a["candidate_tag_counts"]["note"] == 181
    assert result_a["candidate_tag_counts"]["table"] == 1
    assert result_a["candidate_tag_counts"]["row"] == 26
    assert result_a["candidate_tag_counts"]["cell"] == 40
    assert result_a["unresolved_internal_targets"] == []
    title_statement = etree.fromstring(candidate_a.read_bytes()).find(
        "tei:teiHeader/tei:fileDesc/tei:titleStmt",
        namespaces={"tei": "http://www.tei-c.org/ns/1.0"},
    )
    assert title_statement is not None
    assert title_statement.find(
        "tei:author", namespaces={"tei": "http://www.tei-c.org/ns/1.0"}
    ) is None
    contributors = title_statement.find(
        "tei:respStmt/tei:name", namespaces={"tei": "http://www.tei-c.org/ns/1.0"}
    )
    assert contributors is not None
    assert contributors.text.startswith("William Thomson;")
    assert contributors.text.endswith("Charles J. Ellicott")
    assert result_a["acceptance_status"] == "nonaccepted"
    assert result_a["publication_status"] == "not-authorized"

    monkeypatch.chdir(tmp_path)
    determinism_path = tmp_path / "determinism.json"
    determinism = write_determinism_report(
        candidate_a,
        validation_a,
        candidate_b,
        validation_b,
        determinism_path,
        repository_root=REPO_ROOT,
    )
    assert determinism["candidate_bytes_equal"] is True
    assert determinism["validation_bytes_equal"] is True
    assert determinism["different_working_directory"] is True


def test_mutated_source_is_rejected_before_write(tmp_path: Path) -> None:
    source = resolve_source_path(REPO_ROOT)
    mutated = tmp_path / "mutated.htm"
    mutated.write_bytes(source.read_bytes().replace(b"MDCCCLXXI", b"MDCCCLXXII", 1))
    candidate = tmp_path / "candidate.xml"
    validation = tmp_path / "validation.json"
    with pytest.raises(SourceMismatchError, match="source SHA-256"):
        build_candidate(mutated, candidate, validation, repository_root=REPO_ROOT)
    assert not candidate.exists()
    assert not validation.exists()
