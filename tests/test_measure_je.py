"""Tests for build/tools/measure_je.py -- JE surrogate oracle metric tool.

TDD: tests written to drive the fixes identified in the adversarial review.
Each test names the fix it covers (A4/A8, A13, A10, etc.).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from build.tools.measure_je import MetricAccum, _compute_article_metrics, measure_all

# ---------------------------------------------------------------------------
# Minimal fixtures
# ---------------------------------------------------------------------------

# WCT position: conf=0.99, single candidate, 2 families -> M2 + M3h + M3t qualify
_POS_99_TWOFAM_ONECAND = {
    "position_id": "vol_02:p0001:c1:l0:p0",
    "zone": "body",
    "alignment_confidence": 0.99,
    "candidate_set": [
        {
            "candidate_id": "cand_g01",
            "raw_reading": "grace",
            "candidate_key": "grace",
            "attesting_engines": ["ia-abbyy-v1", "tesseract-py314-v1"],
            "attesting_families": ["abbyy", "tesseract"],
        }
    ],
}

# WCT position: conf=0.99, TWO candidates (engines disagree on reading)
_POS_99_TWOCAND = {
    "position_id": "vol_02:p0001:c1:l0:p1",
    "zone": "body",
    "alignment_confidence": 0.99,
    "candidate_set": [
        {
            "candidate_id": "cand_w01",
            "raw_reading": "world",
            "candidate_key": "world",
            "attesting_engines": ["ia-abbyy-v1", "tesseract-py314-v1"],
            "attesting_families": ["abbyy", "tesseract"],
        },
        {
            "candidate_id": "cand_w02",
            "raw_reading": "w0rld",
            "candidate_key": "w0rld",
            "attesting_engines": ["kraken-py312-v1"],
            "attesting_families": ["kraken"],
        },
    ],
}

# WCT position: conf=0.875, single candidate, 1 family -> M3h qualifies, not M3t or M2
_POS_875_ONEFAM = {
    "position_id": "vol_02:p0001:c1:l0:p2",
    "zone": "body",
    "alignment_confidence": 0.875,
    "candidate_set": [
        {
            "candidate_id": "cand_f01",
            "raw_reading": "faith",
            "candidate_key": "faith",
            "attesting_engines": ["ia-abbyy-v1"],
            "attesting_families": ["abbyy"],
        }
    ],
}

# WCT position: conf=0.9 -> counts for M3h (>=0.875), not M3t
_POS_90_ONEFAM = {
    "position_id": "vol_02:p0001:c1:l0:p3",
    "zone": "body",
    "alignment_confidence": 0.9,
    "candidate_set": [
        {
            "candidate_id": "cand_h01",
            "raw_reading": "hope",
            "candidate_key": "hope",
            "attesting_engines": ["ia-abbyy-v1"],
            "attesting_families": ["abbyy"],
        }
    ],
}

# WCT position: same-family two attesters (both kraken) -> does NOT qualify for M2
_POS_99_SAMEFAM = {
    "position_id": "vol_02:p0001:c1:l0:p4",
    "zone": "body",
    "alignment_confidence": 0.99,
    "candidate_set": [
        {
            "candidate_id": "cand_l01",
            "raw_reading": "love",
            "candidate_key": "love",
            "attesting_engines": ["kraken-py312-v1", "kraken-greek-py312-v1"],
            "attesting_families": ["kraken", "kraken"],
        }
    ],
}

_WCT_PAGE = {
    "schema_type": "wct-page-v1",
    "work_id": "jewish-encyclopedia.vol_02",
    "volume_id": "vol_02",
    "page_id": "vol_02:page_0001",
    "positions": [
        _POS_99_TWOFAM_ONECAND,
        _POS_99_TWOCAND,
        _POS_875_ONEFAM,
        _POS_90_ONEFAM,
        _POS_99_SAMEFAM,
    ],
}


def _mk_gold(tmp: Path, slug: str, pairs: list, pages_missing: list = None) -> dict:
    """Write a minimal gold.json and return the dict."""
    gold_dir = tmp / slug
    gold_dir.mkdir(parents=True, exist_ok=True)
    pages_missing = pages_missing or []
    data = {
        "article_slug": slug,
        "n_aligned": len([p for p in pairs if p.get("reference_norm")]),
        "n_reference_tokens": len(pairs),
        "n_wct_positions": len(pairs),
        "n_reference_unaligned": 0,
        "n_positions_unaligned": 0,
        "pages_spanned": [1],
        "pages_with_wct": [] if not pages_missing else [1],
        "pages_missing_wct": pages_missing,
        "aligned_pairs": pairs,
    }
    (gold_dir / "gold.json").write_text(json.dumps(data), encoding="utf-8")
    return data


def _mk_wct_dir(tmp: Path) -> Path:
    wct_dir = tmp / "wct"
    wct_dir.mkdir(exist_ok=True)
    (wct_dir / "page_0001.json").write_text(json.dumps(_WCT_PAGE), encoding="utf-8")
    return wct_dir


# ---------------------------------------------------------------------------
# MetricAccum
# ---------------------------------------------------------------------------


class TestMetricAccum:
    def test_rate_returns_na_when_denominator_zero(self):
        acc = MetricAccum()
        assert acc.rate(0, 0) == "N/A (n=0)"

    def test_merge_accumulates_numerators(self):
        a = MetricAccum(m0_num=3, m0_den=5)
        b = MetricAccum(m0_num=2, m0_den=4)
        a.merge(b)
        assert a.m0_num == 5
        assert a.m0_den == 9


# ---------------------------------------------------------------------------
# Empty-norm skip (A3) -- skip happens BEFORE m0_den increment
# ---------------------------------------------------------------------------


class TestEmptyNormSkip:
    def test_empty_ref_norm_excluded_from_m0_denominator(self, tmp_path):
        # A pair with reference_norm=="" must not increment m0_den even if match=True
        gold = {
            "article_slug": "test",
            "n_aligned": 1,
            "pages_with_wct": [1],
            "pages_missing_wct": [],
            "aligned_pairs": [
                {
                    "position_id": _POS_99_TWOFAM_ONECAND["position_id"],
                    "reference_token": ":",
                    "reference_norm": "",  # empty -- punctuation-only
                    "ocr_consensus": "grace",
                    "ocr_norm": "grace",
                    "match": True,  # would be a phantom hit
                    "confusion_dist": 0.0,
                }
            ],
        }
        wct_dir = _mk_wct_dir(tmp_path)
        acc = _compute_article_metrics(gold, wct_dir)
        assert acc.m0_den == 0, "Empty ref_norm must not increment m0_den"
        assert acc.m0_num == 0


# ---------------------------------------------------------------------------
# M2 family independence (A11)
# ---------------------------------------------------------------------------


class TestM2FamilyIndependence:
    def test_two_different_families_qualify_for_m2(self, tmp_path):
        # _POS_99_TWOFAM_ONECAND has abbyy + tesseract -> qualifies
        gold = {
            "article_slug": "test",
            "n_aligned": 1,
            "pages_with_wct": [1],
            "pages_missing_wct": [],
            "aligned_pairs": [
                {
                    "position_id": _POS_99_TWOFAM_ONECAND["position_id"],
                    "reference_token": "grace",
                    "reference_norm": "grace",
                    "ocr_consensus": "grace",
                    "ocr_norm": "grace",
                    "match": True,
                    "confusion_dist": 0.0,
                }
            ],
        }
        wct_dir = _mk_wct_dir(tmp_path)
        acc = _compute_article_metrics(gold, wct_dir)
        assert acc.m2_den == 1
        assert acc.m2_num == 1

    def test_same_family_two_engines_do_not_qualify_for_m2(self, tmp_path):
        # _POS_99_SAMEFAM has kraken + kraken-greek, both family="kraken" -> no M2
        gold = {
            "article_slug": "test",
            "n_aligned": 1,
            "pages_with_wct": [1],
            "pages_missing_wct": [],
            "aligned_pairs": [
                {
                    "position_id": _POS_99_SAMEFAM["position_id"],
                    "reference_token": "love",
                    "reference_norm": "love",
                    "ocr_consensus": "love",
                    "ocr_norm": "love",
                    "match": True,
                    "confusion_dist": 0.0,
                }
            ],
        }
        wct_dir = _mk_wct_dir(tmp_path)
        acc = _compute_article_metrics(gold, wct_dir)
        assert acc.m2_den == 0, "Same-family engines must not qualify for M2"


# ---------------------------------------------------------------------------
# M3 float thresholds (A13 fix)
# ---------------------------------------------------------------------------


class TestM3FloatThresholds:
    def test_conf_099_counts_for_both_m3h_and_m3t(self, tmp_path):
        gold = {
            "article_slug": "test",
            "n_aligned": 1,
            "pages_with_wct": [1],
            "pages_missing_wct": [],
            "aligned_pairs": [
                {
                    "position_id": _POS_99_TWOFAM_ONECAND["position_id"],
                    "reference_token": "grace",
                    "reference_norm": "grace",
                    "ocr_consensus": "grace",
                    "ocr_norm": "grace",
                    "match": True,
                    "confusion_dist": 0.0,
                }
            ],
        }
        wct_dir = _mk_wct_dir(tmp_path)
        acc = _compute_article_metrics(gold, wct_dir)
        assert acc.m3_high_den == 1
        assert acc.m3_top_den == 1

    def test_conf_090_counts_for_m3h_only(self, tmp_path):
        gold = {
            "article_slug": "test",
            "n_aligned": 1,
            "pages_with_wct": [1],
            "pages_missing_wct": [],
            "aligned_pairs": [
                {
                    "position_id": _POS_90_ONEFAM["position_id"],
                    "reference_token": "hope",
                    "reference_norm": "hope",
                    "ocr_consensus": "hope",
                    "ocr_norm": "hope",
                    "match": True,
                    "confusion_dist": 0.0,
                }
            ],
        }
        wct_dir = _mk_wct_dir(tmp_path)
        acc = _compute_article_metrics(gold, wct_dir)
        assert acc.m3_high_den == 1, "conf=0.9 should count for M3h (>=0.875)"
        assert acc.m3_top_den == 0, "conf=0.9 should NOT count for M3t (>=0.99)"

    def test_conf_075_counts_for_neither_m3h_nor_m3t(self, tmp_path):
        pos_075 = {
            "position_id": "vol_02:p0001:c1:l0:p99",
            "zone": "body",
            "alignment_confidence": 0.75,
            "candidate_set": [
                {
                    "candidate_id": "cand_f75",
                    "raw_reading": "faith",
                    "candidate_key": "faith",
                    "attesting_engines": ["ia-abbyy-v1"],
                    "attesting_families": ["abbyy"],
                }
            ],
        }
        wct_page = {**_WCT_PAGE, "positions": _WCT_PAGE["positions"] + [pos_075]}
        wct_dir = tmp_path / "wct"
        wct_dir.mkdir()
        (wct_dir / "page_0001.json").write_text(json.dumps(wct_page), encoding="utf-8")

        gold = {
            "article_slug": "test",
            "n_aligned": 1,
            "pages_with_wct": [1],
            "pages_missing_wct": [],
            "aligned_pairs": [
                {
                    "position_id": pos_075["position_id"],
                    "reference_token": "faith",
                    "reference_norm": "faith",
                    "ocr_consensus": "faith",
                    "ocr_norm": "faith",
                    "match": True,
                    "confusion_dist": 0.0,
                }
            ],
        }
        acc = _compute_article_metrics(gold, wct_dir)
        assert acc.m3_high_den == 0, "conf=0.75 must not count for M3h"
        assert acc.m3_top_den == 0


# ---------------------------------------------------------------------------
# M3-agree metric (A13 new metric)
# ---------------------------------------------------------------------------


class TestM3Agree:
    """M3-agree: conf>=0.99 AND len(candidate_set)==1 (engines agree on reading)."""

    def test_single_candidate_at_099_counts_for_m3_agree(self, tmp_path):
        gold = {
            "article_slug": "test",
            "n_aligned": 1,
            "pages_with_wct": [1],
            "pages_missing_wct": [],
            "aligned_pairs": [
                {
                    "position_id": _POS_99_TWOFAM_ONECAND["position_id"],
                    "reference_token": "grace",
                    "reference_norm": "grace",
                    "ocr_consensus": "grace",
                    "ocr_norm": "grace",
                    "match": True,
                    "confusion_dist": 0.0,
                }
            ],
        }
        wct_dir = _mk_wct_dir(tmp_path)
        acc = _compute_article_metrics(gold, wct_dir)
        assert hasattr(acc, "m3_agree_num"), "MetricAccum must have m3_agree_num"
        assert hasattr(acc, "m3_agree_den"), "MetricAccum must have m3_agree_den"
        assert acc.m3_agree_den == 1
        assert acc.m3_agree_num == 1

    def test_two_candidates_at_099_does_not_count_for_m3_agree(self, tmp_path):
        # _POS_99_TWOCAND has 2 candidates -> engines disagree on reading
        gold = {
            "article_slug": "test",
            "n_aligned": 1,
            "pages_with_wct": [1],
            "pages_missing_wct": [],
            "aligned_pairs": [
                {
                    "position_id": _POS_99_TWOCAND["position_id"],
                    "reference_token": "world",
                    "reference_norm": "world",
                    "ocr_consensus": "world",
                    "ocr_norm": "world",
                    "match": True,
                    "confusion_dist": 0.0,
                }
            ],
        }
        wct_dir = _mk_wct_dir(tmp_path)
        acc = _compute_article_metrics(gold, wct_dir)
        assert acc.m3_agree_den == 0, "Two-candidate position must not count for M3-agree"


# ---------------------------------------------------------------------------
# A4/A8 default exclusion: complete_only now defaults to True
# ---------------------------------------------------------------------------


class TestCompleteOnlyDefault:
    def test_partial_article_excluded_from_default_aggregate(self, tmp_path):
        """Articles with pages_missing_wct must be excluded from the default run."""
        gold_root = tmp_path / "gold"
        pairs = [
            {
                "position_id": _POS_99_TWOFAM_ONECAND["position_id"],
                "reference_token": "grace",
                "reference_norm": "grace",
                "ocr_consensus": "grace",
                "ocr_norm": "grace",
                "match": True,
                "confusion_dist": 0.0,
            }
        ]
        _mk_gold(gold_root, "partial-article", pairs, pages_missing=[42])
        wct_dir = _mk_wct_dir(tmp_path)

        # Default run (no explicit complete_only argument)
        results = measure_all(gold_root=gold_root, wct_dir=wct_dir)
        assert "partial-article" in results["partial_excluded"], (
            "Articles with pages_missing_wct must be excluded from the default aggregate"
        )
        assert results["aggregate"].m0_den == 0

    def test_include_partial_includes_partial_articles(self, tmp_path):
        """complete_only=False must include partial articles in aggregate."""
        gold_root = tmp_path / "gold"
        pairs = [
            {
                "position_id": _POS_99_TWOFAM_ONECAND["position_id"],
                "reference_token": "grace",
                "reference_norm": "grace",
                "ocr_consensus": "grace",
                "ocr_norm": "grace",
                "match": True,
                "confusion_dist": 0.0,
            }
        ]
        _mk_gold(gold_root, "partial-article", pairs, pages_missing=[42])
        wct_dir = _mk_wct_dir(tmp_path)

        results = measure_all(gold_root=gold_root, wct_dir=wct_dir, complete_only=False)
        assert "partial-article" not in results["partial_excluded"]
        assert results["aggregate"].m0_den == 1

    def test_complete_article_always_included(self, tmp_path):
        """Articles with no missing pages must appear in the default aggregate."""
        gold_root = tmp_path / "gold"
        pairs = [
            {
                "position_id": _POS_99_TWOFAM_ONECAND["position_id"],
                "reference_token": "grace",
                "reference_norm": "grace",
                "ocr_consensus": "grace",
                "ocr_norm": "grace",
                "match": True,
                "confusion_dist": 0.0,
            }
        ]
        _mk_gold(gold_root, "complete-article", pairs, pages_missing=[])
        wct_dir = _mk_wct_dir(tmp_path)

        results = measure_all(gold_root=gold_root, wct_dir=wct_dir)
        assert "complete-article" not in results["partial_excluded"]
        assert results["aggregate"].m0_den == 1


# ---------------------------------------------------------------------------
# A10: Position dedup counting
# ---------------------------------------------------------------------------


class TestPositionDedup:
    def test_n_pos_duplicate_counts_reused_position_ids(self, tmp_path):
        """Two articles that both align to the same position_id must be counted."""
        gold_root = tmp_path / "gold"
        pair = {
            "position_id": _POS_99_TWOFAM_ONECAND["position_id"],
            "reference_token": "grace",
            "reference_norm": "grace",
            "ocr_consensus": "grace",
            "ocr_norm": "grace",
            "match": True,
            "confusion_dist": 0.0,
        }
        # Two articles, same position_id in both
        _mk_gold(gold_root, "article-one", [pair], pages_missing=[])
        _mk_gold(gold_root, "article-two", [pair], pages_missing=[])
        wct_dir = _mk_wct_dir(tmp_path)

        results = measure_all(gold_root=gold_root, wct_dir=wct_dir)
        # The second occurrence is a duplicate
        assert results["n_pos_duplicate"] == 1
