"""Tests for build.lib.ocr_coordinates: hOCR parser + bbox lookup + JSON sidecar reader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.lib.ocr_coordinates import (
    ThinSidecarError,
    lookup_bbox,
    lookup_word_bbox,
    read_hocr,
    read_json_sidecar,
)


HOCR_FIXTURE = """\
<!DOCTYPE html>
<html>
<head><title>hOCR fixture</title></head>
<body>
  <div class="ocr_page" id="page_1" title="image fixture.jpg; bbox 0 0 1000 1500; ppageno 0">
    <span class="ocr_line" id="line_1_1" title="bbox 100 200 900 240">
      <span class="ocrx_word" id="word_1_1" title="bbox 100 200 300 240; x_wconf 92">AARON</span>
      <span class="ocrx_word" id="word_1_2" title="bbox 320 200 500 240; x_wconf 88">was</span>
      <span class="ocrx_word" id="word_1_3" title="bbox 520 200 900 240; x_wconf 90">prophet</span>
    </span>
    <span class="ocr_line" id="line_1_2" title="bbox 100 260 900 300">
      <span class="ocrx_word" id="word_1_4" title="bbox 100 260 600 300; x_wconf 85">brother of</span>
      <span class="ocrx_word" id="word_1_5" title="bbox 620 260 900 300; x_wconf 95">Moses</span>
    </span>
  </div>
  <div class="ocr_page" id="page_2" title="image fixture.jpg; bbox 0 0 1000 1500; ppageno 1">
    <span class="ocr_line" id="line_2_1" title="bbox 100 200 900 240">
      <span class="ocrx_word" id="word_2_1" title="bbox 100 200 900 240; x_wconf 70">THEOLOGY</span>
    </span>
  </div>
</body>
</html>
"""


def test_read_hocr_extracts_lines_with_bbox_and_text(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture_hocr.html"
    fixture.write_text(HOCR_FIXTURE, encoding="utf-8")

    coords = read_hocr(fixture)

    # 2 pages, 2+1 lines
    assert len(coords) == 3
    page1_line1 = coords[(1, "line_1_1")]
    assert page1_line1["bbox"] == (100, 200, 800, 40)  # x, y, w, h
    assert "AARON" in page1_line1["text"]
    assert page1_line1["confidence"] == pytest.approx((92 + 88 + 90) / 3, rel=1e-3)


def test_lookup_bbox_exact_substring(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture_hocr.html"
    fixture.write_text(HOCR_FIXTURE, encoding="utf-8")
    coords = read_hocr(fixture)

    bbox = lookup_bbox(coords, page=1, text_snippet="AARON")

    assert bbox == (100, 200, 800, 40)


def test_lookup_bbox_fuzzy_within_threshold(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture_hocr.html"
    fixture.write_text(HOCR_FIXTURE, encoding="utf-8")
    coords = read_hocr(fixture)

    # OCR misread: AAR0N (zero for O) -- 1 Levenshtein away from line text
    bbox = lookup_bbox(
        coords, page=1, text_snippet="AAR0N was prophet", max_levenshtein=3
    )

    assert bbox == (100, 200, 800, 40)


def test_lookup_bbox_short_snippet_inside_long_line_returns_bbox() -> None:
    coords = {
        (1, "line_1"): {
            "bbox": (10, 20, 300, 40),
            "text": "the quick brown fox jumps over the lazy dog",
            "confidence": 90.0,
        }
    }

    bbox = lookup_bbox(coords, page=1, text_snippet="qu1ck brown")

    assert bbox == (10, 20, 300, 40)


def test_lookup_bbox_exact_substring_still_wins() -> None:
    coords = {
        (1, "line_1"): {
            "bbox": (10, 20, 300, 40),
            "text": "the qu1ck brown fox jumps over the lazy dog",
            "confidence": 90.0,
        },
        (1, "line_2"): {
            "bbox": (50, 60, 120, 20),
            "text": "quick brown",
            "confidence": 95.0,
        },
    }

    bbox = lookup_bbox(coords, page=1, text_snippet="quick brown")

    assert bbox == (50, 60, 120, 20)


def test_lookup_bbox_returns_none_for_unrelated_snippet() -> None:
    coords = {
        (1, "line_1"): {
            "bbox": (10, 20, 300, 40),
            "text": "the quick brown fox jumps over the lazy dog",
            "confidence": 90.0,
        }
    }

    bbox = lookup_bbox(coords, page=1, text_snippet="ZZZZZZZZ")

    assert bbox is None


def test_lookup_bbox_returns_none_when_no_match(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture_hocr.html"
    fixture.write_text(HOCR_FIXTURE, encoding="utf-8")
    coords = read_hocr(fixture)

    bbox = lookup_bbox(coords, page=1, text_snippet="nothing like this text")

    assert bbox is None


def test_lookup_bbox_respects_page_boundary(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture_hocr.html"
    fixture.write_text(HOCR_FIXTURE, encoding="utf-8")
    coords = read_hocr(fixture)

    # THEOLOGY is on page 2 only
    assert lookup_bbox(coords, page=1, text_snippet="THEOLOGY") is None
    assert lookup_bbox(coords, page=2, text_snippet="THEOLOGY") == (100, 200, 800, 40)


# ---------------------------------------------------------------------------
# JSON sidecar reader (read_json_sidecar + lookup_word_bbox)
# ---------------------------------------------------------------------------

_SIDECAR_WORDS = [
    {"text": "AARON,", "confidence": 98.0,
     "bbox": {"x": 100, "y": 200, "w": 150, "h": 28},
     "bbox_polygon": [{"x": 100, "y": 200}, {"x": 250, "y": 200},
                      {"x": 250, "y": 228}, {"x": 100, "y": 228}],
     "low_confidence": False},
    {"text": "the", "confidence": 95.0,
     "bbox": {"x": 260, "y": 200, "w": 60, "h": 28},
     "low_confidence": False},
]

_SIDECAR_DATA = {
    "engine": "azure-ai-vision",
    "blocks": [{"bbox": {"x": 100, "y": 200, "w": 220, "h": 28},
                "lines": [{"text": "AARON, the",
                            "bbox": {"x": 100, "y": 200, "w": 220, "h": 28},
                            "words": _SIDECAR_WORDS}]}],
}


def _write_sidecar(path: Path, data: dict | None = None) -> None:
    path.write_text(json.dumps(data or _SIDECAR_DATA), encoding="utf-8")


def test_read_json_sidecar_returns_word_list(tmp_path: Path) -> None:
    sidecar = tmp_path / "page_0010.azure.json"
    _write_sidecar(sidecar)

    words = read_json_sidecar(sidecar)

    assert len(words) == 2
    assert words[0]["text"] == "AARON,"
    assert words[0]["bbox"] == (100, 200, 150, 28)
    assert words[0]["block_idx"] == 0
    assert words[0]["line_idx"] == 0
    assert words[0]["word_idx"] == 0


def test_read_json_sidecar_preserves_polygon(tmp_path: Path) -> None:
    sidecar = tmp_path / "page_0010.azure.json"
    _write_sidecar(sidecar)

    words = read_json_sidecar(sidecar)

    assert "bbox_polygon" in words[0]
    assert words[0]["bbox_polygon"][0] == {"x": 100, "y": 200}


def test_read_json_sidecar_no_polygon_key_when_absent(tmp_path: Path) -> None:
    sidecar = tmp_path / "page_0010.azure.json"
    _write_sidecar(sidecar)

    words = read_json_sidecar(sidecar)

    # Second word in fixture has no bbox_polygon field
    assert "bbox_polygon" not in words[1]


def test_read_json_sidecar_skips_words_without_bbox(tmp_path: Path) -> None:
    sidecar = tmp_path / "page_0010.azure.json"
    data = {"blocks": [{"lines": [{"words": [
        {"text": "no-bbox", "confidence": 90.0},
        {"text": "has-bbox", "confidence": 90.0,
         "bbox": {"x": 0, "y": 0, "w": 50, "h": 20}},
    ]}]}]}
    _write_sidecar(sidecar, data)

    words = read_json_sidecar(sidecar)

    assert len(words) == 1
    assert words[0]["text"] == "has-bbox"


def test_read_json_sidecar_empty_blocks(tmp_path: Path) -> None:
    sidecar = tmp_path / "page_0010.azure.json"
    _write_sidecar(sidecar, {"blocks": []})

    assert read_json_sidecar(sidecar) == []


def test_lookup_word_bbox_exact(tmp_path: Path) -> None:
    sidecar = tmp_path / "page_0010.azure.json"
    _write_sidecar(sidecar)
    words = read_json_sidecar(sidecar)

    assert lookup_word_bbox(words, "AARON,") == (100, 200, 150, 28)


def test_lookup_word_bbox_substring(tmp_path: Path) -> None:
    sidecar = tmp_path / "page_0010.azure.json"
    _write_sidecar(sidecar)
    words = read_json_sidecar(sidecar)

    # "AARON" (5 chars >= min_substring_len=4) is a substring of "AARON,"
    assert lookup_word_bbox(words, "AARON") == (100, 200, 150, 28)


def test_lookup_word_bbox_fuzzy(tmp_path: Path) -> None:
    sidecar = tmp_path / "page_0010.azure.json"
    _write_sidecar(sidecar)
    words = read_json_sidecar(sidecar)

    # "ARON," is 1 edit away from "AARON," (5 chars >= min_fuzzy_len=4)
    assert lookup_word_bbox(words, "ARON,") == (100, 200, 150, 28)


def test_lookup_word_bbox_short_snippet_no_substring_match() -> None:
    """Codex Attack 4: 'in' must NOT match 'within' via substring."""
    words = [
        {"text": "within", "bbox": (10, 20, 80, 25), "confidence": 90.0,
         "block_idx": 0, "line_idx": 0, "word_idx": 0},
        {"text": "in", "bbox": (200, 20, 30, 25), "confidence": 95.0,
         "block_idx": 0, "line_idx": 0, "word_idx": 1},
    ]

    # Exact match wins for "in" — must return the (200, 20, ...) bbox, not within's
    assert lookup_word_bbox(words, "in") == (200, 20, 30, 25)


def test_lookup_word_bbox_short_snippet_exact_only() -> None:
    """Codex Attack 4: short tokens disable substring/fuzzy; only exact matches."""
    words = [
        {"text": "within", "bbox": (10, 20, 80, 25), "confidence": 90.0,
         "block_idx": 0, "line_idx": 0, "word_idx": 0},
        {"text": "De", "bbox": (300, 20, 25, 25), "confidence": 95.0,
         "block_idx": 0, "line_idx": 0, "word_idx": 1},
    ]

    # "in" has no exact match, and len < min_substring_len; must return None
    assert lookup_word_bbox(words, "in") is None
    # Fuzzy: "in" vs "De" is 2 edits — but len 2 < min_fuzzy_len, must NOT match
    assert lookup_word_bbox(words, "ip") is None


def test_lookup_word_bbox_no_match_returns_none(tmp_path: Path) -> None:
    sidecar = tmp_path / "page_0010.azure.json"
    _write_sidecar(sidecar)
    words = read_json_sidecar(sidecar)

    assert lookup_word_bbox(words, "ZZZZZZZ") is None


def test_lookup_word_bbox_empty_snippet_returns_none(tmp_path: Path) -> None:
    sidecar = tmp_path / "page_0010.azure.json"
    _write_sidecar(sidecar)
    words = read_json_sidecar(sidecar)

    assert lookup_word_bbox(words, "") is None


def test_read_json_sidecar_raises_on_thin_sidecar(tmp_path: Path) -> None:
    """Codex Rec #6: thin/legacy sidecars (text but no blocks) raise rather than
    returning [] (which is indistinguishable from a page with no recognised words)."""
    sidecar = tmp_path / "page_0010.azure.json"
    # Legacy thin format — has raw_text but no blocks
    sidecar.write_text(json.dumps({
        "engine": "azure-ai-vision",
        "raw_text": "AARON, the brother of Moses",
        "confidence_mean": 92.0,
    }), encoding="utf-8")

    with pytest.raises(ThinSidecarError):
        read_json_sidecar(sidecar)


def test_read_json_sidecar_empty_blocks_returns_empty_list(tmp_path: Path) -> None:
    """Legitimate empty page (blocks=[]) is distinct from thin sidecar (blocks missing)."""
    sidecar = tmp_path / "page_0010.azure.json"
    sidecar.write_text(json.dumps({
        "engine": "azure-ai-vision",
        "raw_text": "",
        "blocks": [],
    }), encoding="utf-8")

    # blocks key is present, so this is valid — just no words detected
    assert read_json_sidecar(sidecar) == []
