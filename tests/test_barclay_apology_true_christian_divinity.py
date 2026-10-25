"""Focused contract tests for the Wave 2 Barclay Gutenberg candidate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei.barclay_apology_true_christian_divinity import (
    EXPECTED_SOURCE_COUNTS,
    EXPECTED_SOURCE_SHA256,
    SourceMismatchError,
    audit_source,
    build_candidate,
    resolve_source_path,
    sha256_file,
    write_determinism_report,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
NS = {"tei": "http://www.tei-c.org/ns/1.0"}
CONFIG_PATH = (
    REPO_ROOT
    / "sources"
    / "structured-text"
    / "barclay-apology-true-christian-divinity"
    / "config.json"
)


def test_source_config_binds_exact_released_witness_once() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    assert config["resource_id"] == "barclay-apology-true-christian-divinity"
    assert config["gutenberg_id"] == 56487
    assert config["source_hash"] == f"sha256:{EXPECTED_SOURCE_SHA256}"
    assert config["source_edition"].startswith(
        "Eighth English edition, Birmingham: John Baskerville, 1765"
    )
    assert config["license"] == "public-domain"
    assert "acquired once only" in config["notes"]
    assert config["output_file"].startswith(
        "reports/clean-ready-acquisition-to-tei/master-4/28/"
    )


def test_retained_source_matches_identity_and_structural_contract() -> None:
    audit = audit_source(resolve_source_path(REPO_ROOT))

    assert audit["source_sha256"] == EXPECTED_SOURCE_SHA256
    assert audit["source_counts"] == EXPECTED_SOURCE_COUNTS
    assert audit["proposition_labels"] == [
        "PROPOSITION I",
        "PROPOSITION II",
        "PROPOSITION III",
        "PROPOSITION IV",
        "PROPOSITIONS V. & VI",
        "PROPOSITION VII",
        "PROPOSITION VIII",
        "PROPOSITION IX",
        "PROPOSITION X",
        "PROPOSITION XI",
        "PROPOSITION XII",
        "PROPOSITION XIII",
        "PROPOSITION XIV",
        "PROPOSITION XV",
    ]
    assert audit["logical_text_characters"] > 1_000_000
    assert audit["gutenberg_wrapper_excluded_from_candidate_text"] is True


def test_candidate_preserves_text_structure_notes_pages_and_corrections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = resolve_source_path(REPO_ROOT)
    candidate_a = tmp_path / "a" / "barclay.tei.xml"
    report_a = tmp_path / "a" / "validation.json"
    candidate_b = tmp_path / "b" / "barclay.tei.xml"
    report_b = tmp_path / "b" / "validation.json"

    result_a = build_candidate(
        source, candidate_a, report_a, repository_root=REPO_ROOT
    )
    result_b = build_candidate(
        source, candidate_b, report_b, repository_root=REPO_ROOT
    )
    assert result_a == result_b
    assert candidate_a.read_bytes() == candidate_b.read_bytes()
    assert report_a.read_bytes() == report_b.read_bytes()
    assert result_a["logical_text_parity"] is True
    assert result_a["tei_p5_relaxng_valid"] is True
    assert result_a["candidate_counts"]["propositions"] == 15
    assert result_a["candidate_counts"]["footnotes"] == 171
    assert result_a["candidate_counts"]["margin_notes"] == 1361
    assert result_a["candidate_counts"]["page_milestones"] == 516
    assert result_a["candidate_counts"]["correction_choices"] == 139
    assert result_a["candidate_counts"]["tables"] == 3
    assert result_a["candidate_counts"]["unresolved_internal_ref_targets"] == []
    assert result_a["acceptance_status"] == "nonaccepted"
    assert result_a["publication_status"] == "not-authorized"

    tree = etree.parse(str(candidate_a))
    assert [
        div.get("n")
        for div in tree.xpath("//tei:div[@type='proposition']", namespaces=NS)
    ] == [
        "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
        "XI", "XII", "XIII", "XIV", "XV",
    ]
    assert tree.xpath("count(//tei:div[@type='conclusion'])", namespaces=NS) == 1
    assert tree.xpath("count(//tei:div[@type='author_index'])", namespaces=NS) == 1
    assert tree.xpath("count(//tei:div[@type='subject_index'])", namespaces=NS) == 1
    assert tree.xpath("count(//tei:div[@type='errata'])", namespaces=NS) == 1
    assert tree.xpath("count(//tei:div[@type='transcribers_note'])", namespaces=NS) == 1

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
    mutated = tmp_path / "mutated.htm"
    mutated.write_bytes(
        source.read_bytes().replace(
            b"JOHN BASKERVILLE",
            b"JOAN BASKERVILLE",
            1,
        )
    )
    candidate = tmp_path / "candidate.xml"
    report = tmp_path / "validation.json"

    with pytest.raises(SourceMismatchError, match="source SHA-256"):
        build_candidate(
            mutated, candidate, report, repository_root=REPO_ROOT
        )
    assert not candidate.exists()
    assert not report.exists()


def test_candidate_hash_is_stable_across_two_builds(tmp_path: Path) -> None:
    source = resolve_source_path(REPO_ROOT)
    candidate_a = tmp_path / "one.xml"
    report_a = tmp_path / "one.json"
    candidate_b = tmp_path / "two.xml"
    report_b = tmp_path / "two.json"
    build_candidate(source, candidate_a, report_a, repository_root=REPO_ROOT)
    build_candidate(source, candidate_b, report_b, repository_root=REPO_ROOT)

    assert sha256_file(candidate_a) == sha256_file(candidate_b)
