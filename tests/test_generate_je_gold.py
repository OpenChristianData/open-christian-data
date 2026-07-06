"""Tests for build/tools/ocr_pipeline/generate_je_gold.py.

Covers the core logic that bridges the JE aligner's per-article `gold.json`
output (`je-wct-alignment` shape) to the per-page `<page_id>.gold.json` files
the M13 surrogate harness reads:

  - position-id -> page-id extraction,
  - regrouping aligned pairs by page with summary counts,
  - first-occurrence-wins on position-id reuse across articles,
  - the M13 output shape emitted by `write_gold_files`.

All fixtures are synthesised under tmp_path; nothing reads from `reports/` or
the quarantine.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from build.tools.ocr_pipeline.generate_je_gold import (
    _page_id_from_position,
    build_gold_by_page,
    write_gold_files,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_article(align_root: Path, slug: str, aligned_pairs: list[dict]) -> None:
    """Write one per-article `<slug>/gold.json` in `je-wct-alignment` shape.

    `n_aligned` mirrors the aligner's own field: the count of aligned pairs.
    """
    article_dir = align_root / slug
    article_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_type": "je-wct-alignment",
        "slug": slug,
        "n_aligned": len(aligned_pairs),
        "aligned_pairs": aligned_pairs,
    }
    (article_dir / "gold.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _pair(position_id: str, reference_token: str) -> dict:
    return {"position_id": position_id, "reference_token": reference_token}


# ---------------------------------------------------------------------------
# _page_id_from_position
# ---------------------------------------------------------------------------


def test_page_id_from_position_extracts_second_field():
    assert (
        _page_id_from_position("vol_02:page_0010:body:c1:l000:p000") == "page_0010"
    )


def test_page_id_from_position_raises_without_colon():
    with pytest.raises(ValueError):
        _page_id_from_position("page_0010")


# ---------------------------------------------------------------------------
# build_gold_by_page
# ---------------------------------------------------------------------------


def test_build_gold_by_page_groups_by_page_and_counts(tmp_path):
    align_root = tmp_path / "align"
    # Article A: two pairs on page_0010, one on page_0011.
    _write_article(
        align_root,
        "aaron",
        [
            _pair("vol_02:page_0010:body:c1:l000:p000", "Aaron"),
            _pair("vol_02:page_0010:body:c1:l000:p001", "the"),
            _pair("vol_02:page_0011:body:c1:l000:p000", "priest"),
        ],
    )
    # Article B: one pair on page_0012 (distinct positions, no overlap).
    _write_article(
        align_root,
        "abba",
        [
            _pair("vol_02:page_0012:body:c1:l000:p000", "Abba"),
        ],
    )

    gold_by_page, summary = build_gold_by_page(align_root)

    # gold_text grouped by page id.
    assert set(gold_by_page) == {"page_0010", "page_0011", "page_0012"}
    assert gold_by_page["page_0010"] == {
        "vol_02:page_0010:body:c1:l000:p000": "Aaron",
        "vol_02:page_0010:body:c1:l000:p001": "the",
    }
    assert gold_by_page["page_0011"] == {
        "vol_02:page_0011:body:c1:l000:p000": "priest"
    }
    assert gold_by_page["page_0012"] == {
        "vol_02:page_0012:body:c1:l000:p000": "Abba"
    }

    # Summary counts.
    assert summary["articles_read"] == 2
    assert summary["articles_zero_aligned"] == 0
    assert summary["aligned_pairs"] == 4
    assert summary["distinct_positions"] == 4
    assert summary["position_conflicts"] == 0
    assert summary["position_conflicts_divergent"] == 0
    assert summary["pages_with_gold"] == 3


def test_build_gold_by_page_counts_zero_aligned_article(tmp_path):
    align_root = tmp_path / "align"
    _write_article(
        align_root,
        "has-pairs",
        [_pair("vol_02:page_0010:body:c1:l000:p000", "Aaron")],
    )
    _write_article(align_root, "empty", [])  # n_aligned == 0

    _gold_by_page, summary = build_gold_by_page(align_root)

    assert summary["articles_read"] == 2
    assert summary["articles_zero_aligned"] == 1


def test_build_gold_by_page_raises_when_no_articles(tmp_path):
    empty_root = tmp_path / "align"
    empty_root.mkdir()
    with pytest.raises(FileNotFoundError):
        build_gold_by_page(empty_root)


# ---------------------------------------------------------------------------
# First-occurrence-wins on position-id reuse
# ---------------------------------------------------------------------------


def test_build_gold_by_page_first_occurrence_wins_on_divergent_conflict(tmp_path):
    align_root = tmp_path / "align"
    shared = "vol_02:page_0010:body:c1:l000:p000"
    # Two articles claim the SAME position with DIFFERENT reference_token.
    # sorted() over "*/gold.json" means "article-a" sorts before "article-b",
    # so article-a's value is the first occurrence and must win.
    _write_article(align_root, "article-a", [_pair(shared, "FIRST")])
    _write_article(align_root, "article-b", [_pair(shared, "SECOND")])

    gold_by_page, summary = build_gold_by_page(align_root)

    # First article's value kept.
    assert gold_by_page["page_0010"][shared] == "FIRST"
    # Conflict counted, and counted as divergent since the tokens differ.
    assert summary["position_conflicts"] == 1
    assert summary["position_conflicts_divergent"] == 1
    assert summary["distinct_positions"] == 1


def test_build_gold_by_page_identical_reuse_counts_conflict_not_divergent(tmp_path):
    align_root = tmp_path / "align"
    shared = "vol_02:page_0010:body:c1:l000:p000"
    # Same position, SAME reference_token in both articles: still a conflict
    # (second occurrence dropped) but not a divergent one.
    _write_article(align_root, "article-a", [_pair(shared, "SAME")])
    _write_article(align_root, "article-b", [_pair(shared, "SAME")])

    gold_by_page, summary = build_gold_by_page(align_root)

    assert gold_by_page["page_0010"][shared] == "SAME"
    assert summary["position_conflicts"] == 1
    assert summary["position_conflicts_divergent"] == 0


# ---------------------------------------------------------------------------
# write_gold_files
# ---------------------------------------------------------------------------


def test_write_gold_files_emits_m13_shape(tmp_path):
    out_dir = tmp_path / "out"
    gold_by_page = {
        "page_0010": {
            "vol_02:page_0010:body:c1:l000:p000": "Aaron",
            "vol_02:page_0010:body:c1:l000:p001": "the",
        },
        "page_0011": {
            "vol_02:page_0011:body:c1:l000:p000": "priest",
        },
    }

    written = write_gold_files(gold_by_page, out_dir)

    assert written == 2

    # One <page_id>.gold.json per page, in {"positions": {pos: {"gold_text": str}}} shape.
    p10 = json.loads((out_dir / "page_0010.gold.json").read_text(encoding="utf-8"))
    assert p10 == {
        "positions": {
            "vol_02:page_0010:body:c1:l000:p000": {"gold_text": "Aaron"},
            "vol_02:page_0010:body:c1:l000:p001": {"gold_text": "the"},
        }
    }

    p11 = json.loads((out_dir / "page_0011.gold.json").read_text(encoding="utf-8"))
    assert p11 == {
        "positions": {
            "vol_02:page_0011:body:c1:l000:p000": {"gold_text": "priest"},
        }
    }

    # No stray temp files left behind by the atomic write.
    assert list(out_dir.glob("*.tmp")) == []


def test_build_then_write_round_trip(tmp_path):
    """End-to-end: aligner-shaped input -> build -> write -> M13-shaped output."""
    align_root = tmp_path / "align"
    out_dir = tmp_path / "out"
    _write_article(
        align_root,
        "aaron",
        [
            _pair("vol_02:page_0010:body:c1:l000:p000", "Aaron"),
            _pair("vol_02:page_0010:body:c1:l000:p001", "ben"),
        ],
    )

    gold_by_page, _summary = build_gold_by_page(align_root)
    written = write_gold_files(gold_by_page, out_dir)

    assert written == 1
    out = json.loads((out_dir / "page_0010.gold.json").read_text(encoding="utf-8"))
    assert out["positions"]["vol_02:page_0010:body:c1:l000:p000"]["gold_text"] == "Aaron"
    assert out["positions"]["vol_02:page_0010:body:c1:l000:p001"]["gold_text"] == "ben"
