"""Focused contract tests for the released Greenleaf Gutenberg candidate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.tei.greenleaf_testimony_four_evangelists_1847 import (
    EXPECTED_SOURCE_SHA256,
    EXPECTED_SOURCE_TEXT_SHA256,
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
    / "greenleaf-testimony-four-evangelists-1847"
    / "config.json"
)


def test_source_config_binds_exact_released_witness() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    assert config["resource_id"] == "greenleaf-testimony-four-evangelists-1847"
    assert config["gutenberg_id"] == 34989
    assert config["original_publication_year"] == 1847
    assert config["source_hash"] == f"sha256:{EXPECTED_SOURCE_SHA256}"
    assert config["source_type"] == "gutenberg_tei_p4"
    assert config["license"] == "public-domain"
    assert config["output_file"].startswith(
        "reports/clean-ready-acquisition-to-tei/master-4/28/"
    )


def test_retained_package_members_are_exact_and_containers_match() -> None:
    source = resolve_source_path(REPO_ROOT)
    audit = audit_source(source, repository_root=REPO_ROOT)

    assert audit["source_sha256"] == EXPECTED_SOURCE_SHA256
    assert audit["package_hashes"]["pg34989-images.html"] == (
        "ea456f2330a312b08602363c389ca4fa3268cbc010aefbaeb417ccfadae4c49f"
    )
    assert audit["package_hashes"]["34989-h.html"] == (
        "285360911bff3b232cc0f4ca7f0090c16e6e82c9ab4f32e04af78dff8754a2b4"
    )
    assert audit["package_hashes"]["34989-0.txt"] == (
        "fef7b6da48fd155c34cb1858bc7681f66a7238d4998bdbe94b100d36596595d2"
    )
    assert audit["package_hashes"]["34989-pdf.pdf"] == (
        "803b58e4f334f5b6a61354926cf8256000785c7154ce4f137758c1012fe18d81"
    )
    assert audit["package_hashes"]["34989-cover.png"] == (
        "a5239e6a594e3db7e937db1662c5d837487dd8da51bb84c6763fe04d9c3789b6"
    )
    assert audit["zip_member_mismatches"] == []
    assert audit["current_html_zip_members"] == [
        "34989-cover.png",
        "pg34989-images.html",
    ]


def test_source_structure_and_complete_trial_contract() -> None:
    source = resolve_source_path(REPO_ROOT)
    audit = audit_source(source, repository_root=REPO_ROOT)

    assert audit["source_root"] == "TEI.2"
    assert audit["title"] == "An Examination of the Testimony of the Four Evangelists"
    assert audit["author"] == "Simon Greenleaf, LL.D."
    assert audit["edition_number"] == "2"
    assert audit["gutenberg_id"] == "34989"
    assert audit["source_text_characters"] == 893769
    assert audit["source_text_sha256"] == EXPECTED_SOURCE_TEXT_SHA256
    assert audit["entity_references"] == {"mdash": 155}
    assert audit["tag_counts"]["div"] == 206
    assert audit["tag_counts"]["table"] == 249
    assert audit["tag_counts"]["row"] == 4312
    assert audit["tag_counts"]["cell"] == 10138
    assert audit["tag_counts"]["note"] == 416
    assert audit["tag_counts"]["pb"] == 291
    assert audit["tag_counts"]["anchor"] == 295
    assert audit["tag_counts"]["foreign"] == 53
    assert audit["tag_counts"]["hi"] == 2177
    assert audit["source_ids_unique"] is True
    assert audit["unresolved_internal_targets"] == []
    assert audit["harmony"] == {
        "divisions": 183,
        "parts": 9,
        "sections": 173,
        "tables": 244,
        "rows": 3674,
        "cells": 7308,
        "notes": 230,
    }
    assert audit["trial_appendix_heads"] == [
        "An Account Of The Trial Of Jesus.",
        "The Jewish Account Of The Trial Of Jesus. By Mr. Salvador.",
        "The Trial Of Jesus Before Caiaphas And Pilate.",
        "Preface.",
        "Analysis Of The Chapter Of Mr. Salvador, Entitled The Administration Of Justice Among The Jews.This Analysis first appeared in the Gazette des Tribunaux.",
        "Trial Of Jesus.",
    ]
    assert audit["trial_appendix_characters"] == 130245
    assert audit["trial_appendix_notes"] == 93
    assert audit["production_credit_present"] is True
    assert audit["explicit_transcriber_repair_list_present"] is False


def test_candidate_is_complete_valid_p5_and_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = resolve_source_path(REPO_ROOT)
    candidate_a = tmp_path / "a" / "greenleaf.tei.xml"
    report_a = tmp_path / "a" / "validation.json"
    candidate_b = tmp_path / "b" / "greenleaf.tei.xml"
    report_b = tmp_path / "b" / "validation.json"

    result_a = build_candidate(source, candidate_a, report_a, repository_root=REPO_ROOT)
    result_b = build_candidate(source, candidate_b, report_b, repository_root=REPO_ROOT)

    assert result_a == result_b
    assert candidate_a.read_bytes() == candidate_b.read_bytes()
    assert report_a.read_bytes() == report_b.read_bytes()
    assert result_a["tei_p5_relaxng_valid"] is True
    assert result_a["source_candidate_text_match"] is True
    assert result_a["source_text_sha256"] == EXPECTED_SOURCE_TEXT_SHA256
    assert result_a["candidate_text_sha256"] == EXPECTED_SOURCE_TEXT_SHA256
    assert result_a["structural_counts_match"] is True
    assert result_a["candidate_tag_counts"]["table"] == 249
    assert result_a["candidate_tag_counts"]["row"] == 4312
    assert result_a["candidate_tag_counts"]["cell"] == 10138
    assert result_a["candidate_tag_counts"]["note"] == 416
    assert result_a["candidate_tag_counts"]["g"] == 155
    assert result_a["unresolved_internal_targets"] == []
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


def test_mutated_source_is_rejected_before_candidate_write(tmp_path: Path) -> None:
    source = resolve_source_path(REPO_ROOT)
    mutated = tmp_path / "mutated.tei"
    mutated.write_bytes(source.read_bytes().replace(b"Second Edition", b"Third Edition", 1))
    candidate = tmp_path / "candidate.xml"
    report = tmp_path / "validation.json"

    with pytest.raises(SourceMismatchError, match="source SHA-256"):
        build_candidate(mutated, candidate, report, repository_root=REPO_ROOT)

    assert not candidate.exists()
    assert not report.exists()
