"""Focused contract tests for the Lightfoot Gutenberg candidate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.tei.lightfoot_essays_supernatural_religion_1893 import (
    EXPECTED_SOURCE_SHA256, EXPECTED_SOURCE_TEXT_SHA256, SourceMismatchError,
    audit_source, build_candidate, resolve_source_path, write_determinism_report,
)

REPO_ROOT=Path(__file__).resolve().parents[1]
CONFIG=REPO_ROOT/"sources"/"structured-text"/"lightfoot-essays-supernatural-religion-1893"/"config.json"


def test_source_config_binds_exact_second_edition() -> None:
    config=json.loads(CONFIG.read_text(encoding="utf-8"))
    assert config["resource_id"]=="lightfoot-essays-supernatural-religion-1893"
    assert config["gutenberg_id"]==18191
    assert config["original_publication_year"]==1893
    assert config["source_hash"]==f"sha256:{EXPECTED_SOURCE_SHA256}"
    assert config["license"]=="public-domain"
    assert "Second edition" in config["source_edition"]


def test_retained_package_and_containers_are_exact() -> None:
    audit=audit_source(resolve_source_path(REPO_ROOT),repository_root=REPO_ROOT)
    assert audit["source_sha256"]==EXPECTED_SOURCE_SHA256
    assert len(audit["package_hashes"])==9
    assert all(item["match"] for item in audit["container_comparisons"])
    assert audit["cover_sha256"]=="02399ab360764c798a299b549950ca32a935fcaf0db91a7d6742bd639ec43fbc"


def test_source_census_preserves_structure_notes_and_terminal_matter() -> None:
    audit=audit_source(resolve_source_path(REPO_ROOT),repository_root=REPO_ROOT)
    assert audit["source_text_characters"]==740377
    assert audit["source_text_sha256"]==EXPECTED_SOURCE_TEXT_SHA256
    assert audit["source_ids"]==1880 and audit["ids_unique"]
    assert audit["relocated_footnote_paragraphs"]==708
    assert len(audit["section_heads"])==10
    assert "Inconsistent hyphenations" in audit["transcribers_note"]
    assert "*** END OF THE PROJECT GUTENBERG EBOOK" in audit["project_gutenberg_end_and_license"]


def test_candidate_valid_complete_and_fresh_cwd_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source=resolve_source_path(REPO_ROOT); a=tmp_path/"a"/"candidate.xml"; av=tmp_path/"a"/"validation.json"; b=tmp_path/"b"/"candidate.xml"; bv=tmp_path/"b"/"validation.json"
    ra=build_candidate(source,a,av,repository_root=REPO_ROOT); rb=build_candidate(source,b,bv,repository_root=REPO_ROOT)
    assert ra==rb and a.read_bytes()==b.read_bytes() and av.read_bytes()==bv.read_bytes()
    assert ra["tei_p5_relaxng_valid"] and ra["source_candidate_text_match"]
    assert ra["source_text_sha256"]==EXPECTED_SOURCE_TEXT_SHA256==ra["candidate_text_sha256"]
    assert ra["section_divisions"]==10 and ra["candidate_tag_counts"]["note"]==708
    assert ra["unresolved_internal_targets"]==[]
    monkeypatch.chdir(tmp_path); result=write_determinism_report(a,av,b,bv,tmp_path/"determinism.json",repository_root=REPO_ROOT)
    assert result["candidate_bytes_equal"] and result["validation_bytes_equal"] and result["different_working_directory"]


def test_mutated_source_rejected_before_write(tmp_path: Path) -> None:
    source=resolve_source_path(REPO_ROOT); mutated=tmp_path/"mutated.html"; mutated.write_bytes(source.read_bytes().replace(b"Second Edition",b"Second Edition!",1)); candidate=tmp_path/"candidate.xml"; validation=tmp_path/"validation.json"
    with pytest.raises(SourceMismatchError,match="source SHA-256"): build_candidate(mutated,candidate,validation,repository_root=REPO_ROOT)
    assert not candidate.exists() and not validation.exists()
