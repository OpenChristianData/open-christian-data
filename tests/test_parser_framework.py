"""Tests for build/parsers/_framework.py and the tests/conftest.py plugin."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.parsers._framework import (  # noqa: E402
    assert_evidence_for_synthetic_boundaries,
    assert_source_evidence,
)


# ---------------------------------------------------------------------------
# assert_source_evidence
# ---------------------------------------------------------------------------


def test_source_evidence_passes_when_all_strings_present():
    cfg = {"slug": "x", "expected_source_evidence": ["HENRY COLE", "MDCCCXXIII"]}
    assert_source_evidence(cfg, "...HENRY COLE... London, March, MDCCCXXIII...")


def test_source_evidence_raises_when_string_missing():
    cfg = {"slug": "x", "expected_source_evidence": ["Cole", "MDCCCXXIII"]}
    with pytest.raises(ValueError) as exc:
        assert_source_evidence(cfg, "Cole only, no roman numeral here")
    assert "MDCCCXXIII" in str(exc.value)
    assert "x" in str(exc.value)


def test_source_evidence_passes_when_field_absent():
    # cfg without expected_source_evidence: silently passes (opt-in)
    assert_source_evidence({"slug": "x"}, "any text")


def test_source_evidence_uses_work_id_when_slug_missing():
    cfg = {"work_id": "wid", "expected_source_evidence": ["missing"]}
    with pytest.raises(ValueError) as exc:
        assert_source_evidence(cfg, "no match")
    assert "wid" in str(exc.value)


# ---------------------------------------------------------------------------
# assert_evidence_for_synthetic_boundaries
# ---------------------------------------------------------------------------


def test_synthetic_boundary_guard_passes_when_not_declared():
    assert_evidence_for_synthetic_boundaries({"slug": "x"})


def test_synthetic_boundary_guard_passes_when_evidence_present():
    cfg = {
        "slug": "x",
        "has_synthetic_boundaries": True,
        "expected_source_evidence": ["Cole"],
    }
    assert_evidence_for_synthetic_boundaries(cfg)


def test_synthetic_boundary_guard_raises_when_evidence_missing():
    cfg = {"slug": "x", "has_synthetic_boundaries": True}
    with pytest.raises(ValueError) as exc:
        assert_evidence_for_synthetic_boundaries(cfg)
    assert "has_synthetic_boundaries" in str(exc.value)
    assert "expected_source_evidence" in str(exc.value)
    assert "parser-source-evidence.md" in str(exc.value)


def test_synthetic_boundary_guard_raises_on_empty_evidence_list():
    cfg = {
        "slug": "x",
        "has_synthetic_boundaries": True,
        "expected_source_evidence": [],
    }
    with pytest.raises(ValueError):
        assert_evidence_for_synthetic_boundaries(cfg)


# ---------------------------------------------------------------------------
# raw_required marker + skip_if_missing_data helper
# ---------------------------------------------------------------------------


@pytest.mark.raw_required(REPO_ROOT / "this-path-does-not-exist-on-disk.json")
def test_raw_required_skips_when_missing():
    pytest.fail("should have been skipped by the raw_required marker")


@pytest.mark.raw_required(__file__)
def test_raw_required_runs_when_path_exists():
    # __file__ exists -- the marker must not skip this test
    pass


def test_skip_if_missing_data_skips_for_absent_path():
    from build.lib.pytest_skips import skip_if_missing_data

    with pytest.raises(pytest.skip.Exception):
        skip_if_missing_data(REPO_ROOT / "also-not-on-disk.json")


def test_skip_if_missing_data_returns_for_present_path():
    from build.lib.pytest_skips import skip_if_missing_data

    # __file__ exists -- helper must return without skipping
    skip_if_missing_data(__file__)
