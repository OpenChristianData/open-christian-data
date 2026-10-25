"""Focused contract tests for the released Locke EEBO-TCP candidate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.tei.locke_reasonableness_christianity import (
    EXPECTED_SOURCE_SHA256,
    EXPECTED_TCP_CHARS_SHA256,
    SourceMismatchError,
    audit_source,
    build_candidate,
    resolve_source_path,
    sha256_file,
    write_determinism_report,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    REPO_ROOT
    / "sources"
    / "structured-text"
    / "locke-reasonableness-christianity"
    / "config.json"
)


def test_source_config_binds_exact_released_witness() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    assert config["resource_id"] == "locke-reasonableness-christianity"
    assert config["tcp_id"] == "A48888.0001.001"
    assert config["source_commit"] == "2b9bb07853966920667b99de3fb9b7ce4c64dcf8"
    assert config["source_hash"] == f"sha256:{EXPECTED_SOURCE_SHA256}"
    assert config["license"] == "cc0-1.0"
    assert config["output_file"].startswith(
        "reports/clean-ready-acquisition-to-tei/master-4/28/"
    )


def test_retained_source_matches_tei_and_tcp_structure_contract() -> None:
    source = resolve_source_path(REPO_ROOT)
    audit = audit_source(source, repository_root=REPO_ROOT)

    assert audit["source_sha256"] == EXPECTED_SOURCE_SHA256
    assert audit["tei_p5_relaxng_valid"] is True
    assert audit["title"] == (
        "The reasonableness of Christianity as delivered in the Scriptures"
    )
    assert audit["author"] == "Locke, John, 1632-1704."
    assert audit["tcp_identifier"] == "A48888"
    assert audit["edition_date"] == "1695"
    assert audit["cc0_reference_present"] is True
    assert audit["tcp_chars_sha256"] == EXPECTED_TCP_CHARS_SHA256
    assert audit["tcp_character_references"] == 1565
    assert audit["unique_tcp_character_references"] == 2
    assert audit["unresolved_tcp_character_references"] == []
    assert audit["tag_counts"]["div"] == 5
    assert audit["tag_counts"]["pb"] == 314
    assert audit["tag_counts"]["note"] == 9
    assert audit["tag_counts"]["gap"] == 36
    assert audit["tag_counts"]["g"] == 1565
    assert audit["tag_counts"]["hi"] == 2590
    assert audit["tag_counts"]["p"] == 275
    assert audit["div_types"] == {
        "advertisement": 1,
        "errata": 1,
        "preface": 1,
        "text": 1,
        "title_page": 1,
    }
    assert audit["gap_reasons"] == {
        "duplicate": 4,
        "foreign": 27,
        "illegible: bleedthrough": 5,
    }
    assert audit["marginal_notes"] == 1
    assert audit["unique_page_facsimiles"] == 157
    assert audit["first_page_facsimile"] == "tcp:60354:1"
    assert audit["last_page_facsimile"] == "tcp:60354:157"
    assert audit["front_divisions"] == ["title_page", "preface", "errata"]
    assert audit["body_divisions"] == ["text"]
    assert audit["back_divisions"] == ["advertisement"]
    assert audit["ending"] == "FINIS."


def test_candidate_is_exact_source_bytes_with_deterministic_accounting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = resolve_source_path(REPO_ROOT)
    candidate_a = tmp_path / "a" / "locke-reasonableness-christianity.tei.xml"
    report_a = tmp_path / "a" / "validation.json"
    candidate_b = tmp_path / "b" / "locke-reasonableness-christianity.tei.xml"
    report_b = tmp_path / "b" / "validation.json"

    result_a = build_candidate(source, candidate_a, report_a, repository_root=REPO_ROOT)
    result_b = build_candidate(source, candidate_b, report_b, repository_root=REPO_ROOT)

    assert candidate_a.read_bytes() == source.read_bytes()
    assert candidate_b.read_bytes() == source.read_bytes()
    assert sha256_file(candidate_a) == EXPECTED_SOURCE_SHA256
    assert result_a == result_b
    assert report_a.read_bytes() == report_b.read_bytes()
    assert result_a["byte_identity"] is True
    assert result_a["unresolved_source_gaps"] == 36
    assert result_a["acceptance_status"] == "nonaccepted"
    assert result_a["publication_status"] == "not-authorized"

    monkeypatch.chdir(tmp_path)
    determinism_path = tmp_path / "determinism.json"
    determinism = write_determinism_report(
        candidate_a,
        report_a,
        candidate_b,
        report_b,
        determinism_path,
        repository_root=REPO_ROOT,
    )
    assert determinism["candidate_bytes_equal"] is True
    assert determinism["validation_bytes_equal"] is True
    assert determinism["different_working_directory"] is True
    assert json.loads(determinism_path.read_text(encoding="utf-8")) == determinism

    with pytest.raises(FileExistsError, match="already exists"):
        build_candidate(source, candidate_a, report_a, repository_root=REPO_ROOT)


def test_mutated_source_is_rejected_before_candidate_write(tmp_path: Path) -> None:
    source = resolve_source_path(REPO_ROOT)
    mutated = tmp_path / "mutated.xml"
    mutated.write_bytes(source.read_bytes().replace(b"FINIS.", b"FINIS?", 1))
    candidate = tmp_path / "candidate.xml"
    report = tmp_path / "validation.json"

    with pytest.raises(SourceMismatchError, match="source SHA-256"):
        build_candidate(mutated, candidate, report, repository_root=REPO_ROOT)

    assert not candidate.exists()
    assert not report.exists()
