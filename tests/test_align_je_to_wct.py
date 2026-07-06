"""Tests for build/tools/align_je_to_wct.py -- JE article-to-WCT aligner.

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

from build.tools.align_je_to_wct import (
    _collect_wct_sequence,
    _load_pages_json,
    align_article,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

PAGES_TWO_VOL2 = [
    [2, 13, "https://example.com/p13.jpg"],
    [2, 14, "https://example.com/p14.jpg"],
]

PAGES_MIXED_VOLS = [
    [1, 5, "https://example.com/vol1p5.jpg"],
    [2, 13, "https://example.com/p13.jpg"],
]

# Minimal WCT page with 2 positions that have candidates + 1 with empty set.
WCT_PAGE_13 = {
    "schema_type": "wct-page-v1",
    "work_id": "jewish-encyclopedia.vol_02",
    "volume_id": "vol_02",
    "page_id": "vol_02:page_0013",
    "source_image": None,
    "coordinate_unit": "pixel",
    "coordinate_frame": "image",
    "image_size": {"width": 2000, "height": 3000},
    "layout_authority": "geometric",
    "available_engines": ["ia-abbyy-v1", "tesseract-py314-v1"],
    "zones": [],
    "reading_order": [
        "vol_02:page_0013:body:c1:l000:p000",
        "vol_02:page_0013:body:c1:l000:p001",
        "vol_02:page_0013:body:c1:l000:p002",
    ],
    "positions": [
        {
            "position_id": "vol_02:page_0013:body:c1:l000:p000",
            "zone": "body",
            "reference_bbox": None,
            "reference_bbox_source": None,
            "hyphenation": None,
            "script": {"text_level": {"label": "latin"}},
            "candidate_set": [
                {
                    "candidate_id": "cand_001",
                    "raw_reading": "Hello",
                    "candidate_key": "hello",
                    "normalisation_applied": [],
                    "attesting_engines": ["ia-abbyy-v1", "tesseract-py314-v1"],
                    "attesting_families": ["abbyy", "tesseract"],
                }
            ],
            "span_records": [],
            "available_engines": ["ia-abbyy-v1", "tesseract-py314-v1"],
            "comparable_engines": ["ia-abbyy-v1", "tesseract-py314-v1"],
            "unassigned_engines": [],
            "alignment_confidence": "high",
        },
        {
            "position_id": "vol_02:page_0013:body:c1:l000:p001",
            "zone": "body",
            "reference_bbox": None,
            "reference_bbox_source": None,
            "hyphenation": None,
            "script": {"text_level": {"label": "latin"}},
            "candidate_set": [
                {
                    "candidate_id": "cand_001",
                    "raw_reading": "world",
                    "candidate_key": "world",
                    "normalisation_applied": [],
                    "attesting_engines": ["ia-abbyy-v1"],
                    "attesting_families": ["abbyy"],
                }
            ],
            "span_records": [],
            "available_engines": ["ia-abbyy-v1", "tesseract-py314-v1"],
            "comparable_engines": ["ia-abbyy-v1", "tesseract-py314-v1"],
            "unassigned_engines": [],
            "alignment_confidence": "medium",
        },
        {
            "position_id": "vol_02:page_0013:body:c1:l000:p002",
            "zone": "body",
            "reference_bbox": None,
            "reference_bbox_source": None,
            "hyphenation": None,
            "script": {"text_level": {"label": "latin"}},
            "candidate_set": [],  # empty -- should be skipped
            "span_records": [],
            "available_engines": ["ia-abbyy-v1"],
            "comparable_engines": ["ia-abbyy-v1"],
            "unassigned_engines": [],
            "alignment_confidence": "low",
        },
    ],
    "layer1_ops": [],
}


def _mk_article_dir(tmp: Path, pages: list, text: str) -> Path:
    d = tmp / "articles" / "1654-test"
    d.mkdir(parents=True)
    (d / "pages.json").write_text(json.dumps(pages), encoding="utf-8")
    (d / "text.txt").write_text(text, encoding="utf-8")
    return d


def _mk_wct_page(wct_dir: Path, page_num: int, page_data: dict) -> None:
    (wct_dir / f"page_{page_num:04d}.json").write_text(
        json.dumps(page_data), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# _load_pages_json
# ---------------------------------------------------------------------------


class TestLoadPagesJson:
    def test_extracts_vol02_page_numbers(self, tmp_path):
        d = tmp_path / "art"
        d.mkdir()
        (d / "pages.json").write_text(json.dumps(PAGES_TWO_VOL2), encoding="utf-8")
        assert _load_pages_json(d) == [13, 14]

    def test_filters_out_non_vol02_entries(self, tmp_path):
        d = tmp_path / "art"
        d.mkdir()
        (d / "pages.json").write_text(
            json.dumps(PAGES_MIXED_VOLS), encoding="utf-8"
        )
        assert _load_pages_json(d) == [13]

    def test_raises_file_not_found_when_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _load_pages_json(tmp_path)

    def test_returns_sorted_page_numbers(self, tmp_path):
        d = tmp_path / "art"
        d.mkdir()
        unsorted = [
            [2, 15, "https://example.com/p15.jpg"],
            [2, 13, "https://example.com/p13.jpg"],
        ]
        (d / "pages.json").write_text(json.dumps(unsorted), encoding="utf-8")
        assert _load_pages_json(d) == [13, 15]


# ---------------------------------------------------------------------------
# _collect_wct_sequence
# ---------------------------------------------------------------------------


class TestCollectWctSequence:
    def test_returns_position_id_and_raw_reading_pairs(self):
        seq = _collect_wct_sequence([WCT_PAGE_13])
        assert len(seq) == 2
        pos_ids = [item[0] for item in seq]
        assert "vol_02:page_0013:body:c1:l000:p000" in pos_ids
        assert "vol_02:page_0013:body:c1:l000:p001" in pos_ids

    def test_skips_positions_with_empty_candidate_set(self):
        seq = _collect_wct_sequence([WCT_PAGE_13])
        pos_ids = [item[0] for item in seq]
        assert "vol_02:page_0013:body:c1:l000:p002" not in pos_ids

    def test_consensus_is_most_attested_candidate(self):
        seq = _collect_wct_sequence([WCT_PAGE_13])
        pair = next(p for p in seq if p[0] == "vol_02:page_0013:body:c1:l000:p000")
        assert pair[1] == "Hello"

    def test_empty_page_list_returns_empty(self):
        assert _collect_wct_sequence([]) == []

    def test_concatenates_pages_in_order(self):
        wct_page_14 = {
            **WCT_PAGE_13,
            "page_id": "vol_02:page_0014",
            "reading_order": ["vol_02:page_0014:body:c1:l000:p000"],
            "positions": [
                {
                    **WCT_PAGE_13["positions"][0],
                    "position_id": "vol_02:page_0014:body:c1:l000:p000",
                }
            ],
        }
        seq = _collect_wct_sequence([WCT_PAGE_13, wct_page_14])
        pos_ids = [item[0] for item in seq]
        last_p13 = max(i for i, pid in enumerate(pos_ids) if "page_0013" in pid)
        first_p14 = min(i for i, pid in enumerate(pos_ids) if "page_0014" in pid)
        assert last_p13 < first_p14


# ---------------------------------------------------------------------------
# align_article
# ---------------------------------------------------------------------------


class TestAlignArticle:
    def test_produces_output_json_file(self, tmp_path):
        art = _mk_article_dir(tmp_path, PAGES_TWO_VOL2[:1], "Hello world")
        wct = tmp_path / "wct"
        wct.mkdir()
        out = tmp_path / "gold"
        out.mkdir()
        _mk_wct_page(wct, 13, WCT_PAGE_13)

        align_article("1654-test", art, wct, out)

        assert (out / "1654-test" / "gold.json").exists()

    def test_output_has_required_schema_fields(self, tmp_path):
        art = _mk_article_dir(tmp_path, PAGES_TWO_VOL2[:1], "Hello world")
        wct = tmp_path / "wct"
        wct.mkdir()
        out = tmp_path / "gold"
        out.mkdir()
        _mk_wct_page(wct, 13, WCT_PAGE_13)

        result = align_article("1654-test", art, wct, out)

        assert result["schema_type"] == "je-wct-alignment"
        assert result["article_slug"] == "1654-test"
        assert "pages_spanned" in result
        assert "pages_with_wct" in result
        assert "pages_missing_wct" in result
        assert "aligned_pairs" in result
        assert "n_aligned" in result

    def test_aligned_pairs_have_required_fields(self, tmp_path):
        art = _mk_article_dir(tmp_path, PAGES_TWO_VOL2[:1], "Hello world")
        wct = tmp_path / "wct"
        wct.mkdir()
        out = tmp_path / "gold"
        out.mkdir()
        _mk_wct_page(wct, 13, WCT_PAGE_13)

        result = align_article("1654-test", art, wct, out)

        for pair in result["aligned_pairs"]:
            assert "position_id" in pair
            assert "reference_token" in pair
            assert "ocr_consensus" in pair
            assert "match" in pair
            assert "confusion_dist" in pair

    def test_match_true_when_tokens_identical(self, tmp_path):
        art = _mk_article_dir(tmp_path, PAGES_TWO_VOL2[:1], "Hello world")
        wct = tmp_path / "wct"
        wct.mkdir()
        out = tmp_path / "gold"
        out.mkdir()
        _mk_wct_page(wct, 13, WCT_PAGE_13)

        result = align_article("1654-test", art, wct, out)

        # "Hello" in reference should align to "Hello" in WCT => match True
        hello = [p for p in result["aligned_pairs"] if p["reference_token"] == "Hello"]
        assert len(hello) > 0
        assert hello[0]["match"] is True

    def test_skips_missing_wct_pages_gracefully(self, tmp_path):
        # Page 12 has no WCT file; page 13 does.
        art = _mk_article_dir(tmp_path, [
            [2, 12, "https://example.com/p12.jpg"],
            [2, 13, "https://example.com/p13.jpg"],
        ], "Hello world")
        wct = tmp_path / "wct"
        wct.mkdir()
        out = tmp_path / "gold"
        out.mkdir()
        _mk_wct_page(wct, 13, WCT_PAGE_13)

        result = align_article("1654-test", art, wct, out)

        assert 12 in result["pages_missing_wct"]
        assert 13 in result["pages_with_wct"]

    def test_dry_run_does_not_write_output_file(self, tmp_path):
        art = _mk_article_dir(tmp_path, PAGES_TWO_VOL2[:1], "Hello world")
        wct = tmp_path / "wct"
        wct.mkdir()
        out = tmp_path / "gold"
        out.mkdir()
        _mk_wct_page(wct, 13, WCT_PAGE_13)

        align_article("1654-test", art, wct, out, dry_run=True)

        assert not (out / "1654-test" / "gold.json").exists()

    def test_pages_spanned_lists_all_article_pages(self, tmp_path):
        art = _mk_article_dir(tmp_path, [
            [2, 13, "https://example.com/p13.jpg"],
            [2, 14, "https://example.com/p14.jpg"],
        ], "Hello world")
        wct = tmp_path / "wct"
        wct.mkdir()
        out = tmp_path / "gold"
        out.mkdir()
        _mk_wct_page(wct, 13, WCT_PAGE_13)
        # page 14 missing intentionally

        result = align_article("1654-test", art, wct, out)

        assert result["pages_spanned"] == [13, 14]


# ---------------------------------------------------------------------------
# Numpy path and chunking
# ---------------------------------------------------------------------------


def _mk_wct_page_with_n_positions(n: int, page_num: int) -> dict:
    """Generate a WCT page dict with n positions, each with candidate_set."""
    positions = []
    reading_order = []
    for i in range(n):
        pid = f"vol_02:page_{page_num:04d}:body:c1:l000:p{i:03d}"
        reading_order.append(pid)
        positions.append(
            {
                "position_id": pid,
                "zone": "body",
                "reference_bbox": None,
                "reference_bbox_source": None,
                "hyphenation": None,
                "script": {"text_level": {"label": "latin"}},
                "candidate_set": [
                    {
                        "candidate_id": f"cand_{page_num}_{i:03d}",
                        "raw_reading": f"word{i}",
                        "candidate_key": f"word{i}",
                        "normalisation_applied": [],
                        "attesting_engines": ["ia-abbyy-v1"],
                        "attesting_families": ["abbyy"],
                    }
                ],
                "span_records": [],
                "available_engines": ["ia-abbyy-v1"],
                "comparable_engines": ["ia-abbyy-v1"],
                "unassigned_engines": [],
                "alignment_confidence": 0.75,
            }
        )
    return {
        "schema_type": "wct-page-v1",
        "work_id": "jewish-encyclopedia.vol_02",
        "volume_id": "vol_02",
        "page_id": f"vol_02:page_{page_num:04d}",
        "source_image": None,
        "coordinate_unit": "pixel",
        "coordinate_frame": "image",
        "image_size": {"width": 2000, "height": 3000},
        "layout_authority": "geometric",
        "available_engines": ["ia-abbyy-v1"],
        "zones": [],
        "reading_order": reading_order,
        "positions": positions,
        "layer1_ops": [],
    }


class TestNumpyPathAndChunking:
    """Tests for _nw_align_numpy and the proportional page-chunking split."""

    def test_numpy_path_aligns_multipage_article(self, tmp_path):
        """Two-page article: numpy path produces aligned pairs from both pages."""
        pytest.importorskip("numpy")
        # 6-token reference; two pages, 3 positions each
        art = _mk_article_dir(tmp_path, PAGES_TWO_VOL2, "word0 word1 word2 word3 word4 word5")
        wct = tmp_path / "wct"
        wct.mkdir()
        out = tmp_path / "gold"
        out.mkdir()
        _mk_wct_page(wct, 13, _mk_wct_page_with_n_positions(3, 13))
        _mk_wct_page(wct, 14, _mk_wct_page_with_n_positions(3, 14))

        result = align_article("1654-test", art, wct, out)

        assert result["n_aligned"] > 0
        # Both pages contributed WCT positions
        assert 13 in result["pages_with_wct"]
        assert 14 in result["pages_with_wct"]

    def test_chunk_boundary_covers_all_ref_tokens(self, tmp_path):
        """Proportional split must assign every ref token to exactly one chunk.

        Cumulative split last chunk_end must equal n_ref (no trailing tokens
        dropped due to rounding).
        """
        pytest.importorskip("numpy")
        # 7 ref tokens, 2 pages with 3+4 positions -> chunk_end values must sum to 7
        ref_text = "a b c d e f g"
        art = _mk_article_dir(tmp_path, PAGES_TWO_VOL2, ref_text)
        wct = tmp_path / "wct"
        wct.mkdir()
        out = tmp_path / "gold"
        out.mkdir()
        _mk_wct_page(wct, 13, _mk_wct_page_with_n_positions(3, 13))
        _mk_wct_page(wct, 14, _mk_wct_page_with_n_positions(4, 14))

        result = align_article("1654-test", art, wct, out)

        # aligned + unaligned_ref must account for ALL 7 ref tokens
        n_aligned = len(result["aligned_pairs"])
        n_ref_unaligned = result.get("n_reference_unaligned", 0)
        assert n_aligned + n_ref_unaligned == 7, (
            f"Chunk boundary must cover all 7 ref tokens; "
            f"got {n_aligned} aligned + {n_ref_unaligned} unaligned = {n_aligned + n_ref_unaligned}"
        )

    def test_sparse_page_zero_chunk_routes_positions_unaligned(self, tmp_path):
        """A page that gets n_chunk==0 ref tokens must route its WCT positions to unaligned."""
        pytest.importorskip("numpy")
        # 1 ref token, 3 pages (2+5+3 positions):
        # round(1 * 2/10)=0, round(1 * 7/10)=1, round(1 * 10/10)=1
        # -> page 13 gets 0 ref tokens, page 14 gets 1, page 15 gets 0
        art = _mk_article_dir(tmp_path, [
            [2, 13, "https://example.com/p13.jpg"],
            [2, 14, "https://example.com/p14.jpg"],
            [2, 15, "https://example.com/p15.jpg"],
        ], "hello")
        wct = tmp_path / "wct"
        wct.mkdir()
        out = tmp_path / "gold"
        out.mkdir()
        _mk_wct_page(wct, 13, _mk_wct_page_with_n_positions(2, 13))
        _mk_wct_page(wct, 14, _mk_wct_page_with_n_positions(5, 14))
        _mk_wct_page(wct, 15, _mk_wct_page_with_n_positions(3, 15))

        result = align_article("1654-test", art, wct, out)

        # Must not crash; sparse-page positions land in unaligned
        assert "n_positions_unaligned" in result
        # At most 1 aligned pair (the one ref token "hello")
        assert len(result["aligned_pairs"]) <= 1

    def test_numpy_and_python_paths_produce_same_aligned_count(self, tmp_path):
        """numpy path and pure-Python fallback must agree on the number of aligned pairs."""
        numpy = pytest.importorskip("numpy")
        from build.tools import align_je_to_wct as _mod

        # Force numpy path by keeping _HAS_NUMPY True (already the case).
        # Then monkey-patch to force pure-Python path and compare.
        art = _mk_article_dir(tmp_path, PAGES_TWO_VOL2[:1], "Hello world")
        wct = tmp_path / "wct"
        wct.mkdir()
        out_np = tmp_path / "gold_np"
        out_np.mkdir()
        out_py = tmp_path / "gold_py"
        out_py.mkdir()
        _mk_wct_page(wct, 13, WCT_PAGE_13)

        # Numpy path (normal)
        res_np = align_article("1654-test", art, wct, out_np)

        # Pure-Python fallback: temporarily hide numpy
        orig = _mod._HAS_NUMPY
        try:
            _mod._HAS_NUMPY = False
            res_py = align_article("1654-test", art, wct, out_py)
        finally:
            _mod._HAS_NUMPY = orig

        assert len(res_np["aligned_pairs"]) == len(res_py["aligned_pairs"]), (
            f"Numpy path: {len(res_np['aligned_pairs'])} aligned; "
            f"Python path: {len(res_py['aligned_pairs'])} aligned"
        )
