"""Tests for build/tools/tune_je_gap_penalty.py -- GAP_PENALTY sweep tool.

TDD: tests written before implementation. Each test targets one behaviour.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from build.tools.tune_je_gap_penalty import sweep_gap_penalty


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mk_article(article_dir: Path, words: list[str], page_num: int = 10) -> None:
    """Create a minimal article directory (text.txt + pages.json)."""
    article_dir.mkdir(parents=True, exist_ok=True)
    (article_dir / "text.txt").write_text(" ".join(words), encoding="utf-8")
    # pages.json: list of [vol, page_num, url] triplets; vol must be 2
    (article_dir / "pages.json").write_text(
        json.dumps([[2, page_num, f"http://example.com/{page_num}"]]),
        encoding="utf-8",
    )


def _mk_wct_page(wct_dir: Path, page_num: int, readings: list[str]) -> None:
    """Create a minimal WCT page JSON with the given readings in reading order."""
    wct_dir.mkdir(parents=True, exist_ok=True)
    positions = [
        {
            "position_id": f"p{i}",
            "zone": "body",
            "reference_bbox": None,
            "reference_bbox_source": None,
            "hyphenation": None,
            "script": {"text_level": {"label": "latin"}},
            "candidate_set": [
                {
                    "candidate_id": f"cand_{i:03d}",
                    "raw_reading": reading,
                    "candidate_key": reading.lower(),
                    "normalisation_applied": [],
                    "attesting_engines": ["engine-a"],
                    "attesting_families": ["family-a"],
                }
            ],
            "span_records": [],
            "available_engines": ["engine-a"],
            "comparable_engines": ["engine-a"],
            "unassigned_engines": [],
            "alignment_confidence": "medium",
        }
        for i, reading in enumerate(readings)
    ]
    reading_order = [p["position_id"] for p in positions]
    page = {
        "schema_type": "wct-page-v1",
        "work_id": "jewish-encyclopedia.vol_02",
        "volume_id": "vol_02",
        "page_id": f"vol_02:page_{page_num:04d}",
        "source_image": None,
        "coordinate_unit": "pixel",
        "coordinate_frame": "image",
        "image_size": {"width": 2000, "height": 3000},
        "layout_authority": "geometric",
        "available_engines": ["engine-a"],
        "zones": [],
        "reading_order": reading_order,
        "positions": positions,
        "layer1_ops": [],
    }
    (wct_dir / f"page_{page_num:04d}.json").write_text(
        json.dumps(page), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Test: sweep returns the correct dict structure
# ---------------------------------------------------------------------------


class TestSweepStructure:
    """sweep_gap_penalty returns a dict keyed by GAP_PENALTY with expected fields."""

    def test_returns_dict_keyed_by_gap_values(self, tmp_path):
        # 2 ref tokens, 3 WCT positions (one natural unaligned WCT position)
        article_dir = tmp_path / "articles" / "test-slug"
        _mk_article(article_dir, ["hello", "world"], page_num=10)
        wct_dir = tmp_path / "wct"
        _mk_wct_page(wct_dir, 10, ["hello", "world", "extra"])

        gap_values = [0.3, 1.0]
        results = sweep_gap_penalty(
            tmp_path / "articles",
            wct_dir,
            tmp_path / "output",
            gap_values=gap_values,
        )

        assert set(results.keys()) == {0.3, 1.0}

    def test_each_entry_has_required_metric_keys(self, tmp_path):
        article_dir = tmp_path / "articles" / "test-slug"
        _mk_article(article_dir, ["hello", "world"], page_num=10)
        wct_dir = tmp_path / "wct"
        _mk_wct_page(wct_dir, 10, ["hello", "world", "extra"])

        results = sweep_gap_penalty(
            tmp_path / "articles",
            wct_dir,
            tmp_path / "output",
            gap_values=[0.5],
        )

        entry = results[0.5]
        assert "m0" in entry
        assert "ref_coverage" in entry
        assert "wct_coverage" in entry
        assert "mean_confusion_dist" in entry

    def test_metric_values_are_in_valid_range(self, tmp_path):
        article_dir = tmp_path / "articles" / "test-slug"
        _mk_article(article_dir, ["hello", "world"], page_num=10)
        wct_dir = tmp_path / "wct"
        _mk_wct_page(wct_dir, 10, ["hello", "world", "extra"])

        results = sweep_gap_penalty(
            tmp_path / "articles",
            wct_dir,
            tmp_path / "output",
            gap_values=[0.6],
        )

        entry = results[0.6]
        assert 0.0 <= entry["m0"] <= 1.0
        assert 0.0 <= entry["ref_coverage"] <= 1.0
        assert 0.0 <= entry["wct_coverage"] <= 1.0
        assert entry["mean_confusion_dist"] >= 0.0


# ---------------------------------------------------------------------------
# Test: GAP_PENALTY affects aligned-pair counts on a mismatch case
# ---------------------------------------------------------------------------


class TestGapPenaltyEffect:
    """Lower GAP_PENALTY reduces coverage when a mismatch is cheaper to skip."""

    def test_low_gap_reduces_ref_coverage_on_mismatch(self, tmp_path):
        # ref = ["hello", "xyz", "world"], wct = ["hello", "abc", "world"]
        # "xyz" vs "abc": normalized Levenshtein = 1.0 (no common characters)
        #
        # GAP_PENALTY=0.3 < 1.0 => gap is cheaper than mismatch
        #   => aligner inserts gap rather than force-(hello,hello),(xyz,abc),(world,world)
        #   => ref_coverage = 2/3
        #
        # GAP_PENALTY=1.0 = 1.0 => mismatch ties with gap; diagonal preferred (<=)
        #   => aligner forces (hello,hello),(xyz,abc),(world,world)
        #   => ref_coverage = 3/3 = 1.0
        article_dir = tmp_path / "articles" / "mismatch-slug"
        _mk_article(article_dir, ["hello", "xyz", "world"], page_num=10)
        wct_dir = tmp_path / "wct"
        _mk_wct_page(wct_dir, 10, ["hello", "abc", "world"])

        results = sweep_gap_penalty(
            tmp_path / "articles",
            wct_dir,
            tmp_path / "output",
            gap_values=[0.3, 1.0],
        )

        # Lower gap penalty => aligner avoids the mismatch => fewer aligned pairs
        assert results[0.3]["ref_coverage"] < results[1.0]["ref_coverage"], (
            f"Expected low gap (0.3) to produce lower ref_coverage than high gap (1.0); "
            f"got 0.3={results[0.3]['ref_coverage']:.3f}, 1.0={results[1.0]['ref_coverage']:.3f}"
        )
