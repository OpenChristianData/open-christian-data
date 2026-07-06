"""TDD contract for the consensus-geometry layout detector.

The detector replaces Surya as the WCT "layout authority" for regular pages:
it finds columns from the pooled word boxes of multiple engines, separates
header/footnote furniture, and -- critically -- ESCALATES (flags for review /
layout-model fallback) any page it cannot resolve confidently. The escalation
behaviour is the load-bearing safety property (Codex review condition 3): a hard
page must flag itself, never silently produce a wrong column/reading-order.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from build.lib.consensus_layout import detect_columns  # noqa: E402

W, H = 5034, 6959
HEADER_Y = int(0.04 * H)   # inside the stripped header band
FOOTER_Y = int(0.92 * H)   # inside the stripped footnote band
BODY_Y0, BODY_Y1 = int(0.15 * H), int(0.80 * H)


def _box(x, y, w=180, h=55):
    return {"x": x, "y": y, "w": w, "h": h}


def _column(x_center, n=60, y0=BODY_Y0, y1=BODY_Y1):
    step = (y1 - y0) // n
    return [_box(x_center - 90, y0 + i * step) for i in range(n)]


def _two_column_engine():
    return _column(int(0.25 * W)) + _column(int(0.75 * W))


def _realistic_two_column_engine():
    """Two columns whose words have real WIDTH spread across each column (not a
    single x per column). Catches detectors that model a column as a point and so
    flag the column's own edge words as a third cluster / spanning line."""
    boxes = []
    n_lines = 30
    step = (BODY_Y1 - BODY_Y0) // n_lines
    for li in range(n_lines):
        y = BODY_Y0 + li * step
        for f in (0.10, 0.16, 0.22, 0.28, 0.34, 0.40):   # left column band
            boxes.append(_box(int(f * W), y, w=140, h=50))
        for f in (0.56, 0.62, 0.68, 0.74, 0.80, 0.86):   # right column band
            boxes.append(_box(int(f * W), y, w=140, h=50))
    return boxes


def test_realistic_two_column_no_false_flags():
    boxes = {"azure": _realistic_two_column_engine(),
             "tesseract": _realistic_two_column_engine()}
    r = detect_columns(boxes, W, H)
    assert r.n_columns == 2
    assert "third_cluster" not in r.flags
    assert "spanning_lines" not in r.flags
    assert r.escalate is False


def test_clean_two_column_no_escalation():
    boxes = {"azure": _two_column_engine(), "tesseract": _two_column_engine()}
    r = detect_columns(boxes, W, H)
    assert r.n_columns == 2
    assert r.escalate is False
    assert r.provider_count == 2
    assert r.gutter_x is not None and 0.40 * W <= r.gutter_x <= 0.60 * W


def test_single_column_detected():
    # One centred cluster -> one column, no false gutter.
    single = _column(int(0.5 * W), n=80)
    r = detect_columns({"azure": single, "tesseract": single}, W, H)
    assert r.n_columns == 1


def test_zero_providers_escalates():
    r = detect_columns({}, W, H)
    assert r.escalate is True
    assert "zero_geometry" in r.flags


def test_single_provider_flags():
    r = detect_columns({"azure": _two_column_engine()}, W, H)
    assert r.provider_count == 1
    assert "single_provider" in r.flags


def test_engine_disagreement_escalates():
    # One engine sees the gutter near 0.5, the other near 0.35 -> disagreement.
    eng_a = _column(int(0.25 * W)) + _column(int(0.75 * W))
    eng_b = _column(int(0.20 * W)) + _column(int(0.50 * W))
    r = detect_columns({"azure": eng_a, "tesseract": eng_b}, W, H)
    assert r.escalate is True
    assert "engine_disagreement" in r.flags


def test_imbalanced_columns_flags():
    # Left column full, right column almost empty.
    boxes_one = _column(int(0.25 * W), n=60) + _column(int(0.75 * W), n=3)
    r = detect_columns({"azure": boxes_one, "tesseract": boxes_one}, W, H)
    assert "imbalanced_columns" in r.flags


def test_gutter_spanning_line_escalates():
    # A 2-column body plus one line of words marching continuously across the
    # gutter (a full-width rule / table row / spanning inset). Reading order is
    # ambiguous -> must escalate (Codex review condition: discourse order).
    base = _two_column_engine()
    span_y = int(0.50 * H)
    # A full-width element captured as a wide token whose box physically crosses
    # the gutter (centred heading / rule / OCR column-merge).
    spanning = [_box(int(0.42 * W), span_y, w=int(0.16 * W), h=55)]
    boxes = {"azure": base + spanning, "tesseract": base + spanning}
    r = detect_columns(boxes, W, H)
    assert r.escalate is True
    assert "spanning_lines" in r.flags


def test_header_footer_excluded_from_columns():
    # Header/footer band words must not create phantom columns or fill the gutter.
    base = _two_column_engine()
    furniture = [_box(int(0.5 * W), HEADER_Y, w=900, h=70),   # wide running header
                 _box(int(0.5 * W), FOOTER_Y, w=300, h=40)]   # page number
    r = detect_columns({"azure": base + furniture, "tesseract": base + furniture}, W, H)
    assert r.n_columns == 2
    assert r.escalate is False


def test_column_assignment_splits_left_right():
    boxes = {"azure": _two_column_engine(), "tesseract": _two_column_engine()}
    r = detect_columns(boxes, W, H)
    left = r.column_of(_box(int(0.25 * W), BODY_Y0))
    right = r.column_of(_box(int(0.75 * W), BODY_Y0))
    assert left != right
    assert left < right  # left column index precedes right


# --- Real-data anchors (skip on clean checkout; raw/ is gitignored) -----------

_RAW = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages" / "vol_01"


def _azure_boxes(page: int):
    p = _RAW / f"page_{page:04d}.azure.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    size = d["image_size"]
    boxes = [w["bbox"] for b in d.get("blocks", []) for ln in b.get("lines", [])
             for w in ln.get("words", []) if w.get("bbox")]
    return boxes, size[0], size[1]


def _abbyy_boxes(page: int):
    p = _RAW / f"page_{page:04d}.ia-abbyy.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    return [w["bbox"] for b in d.get("blocks", []) for ln in b.get("lines", [])
            for w in ln.get("words", []) if w.get("bbox")]


@pytest.mark.skipif(not (_RAW / "page_0010.azure.json").exists(),
                    reason="raw/ not downloaded")
def test_real_page0010_is_clean_two_column():
    boxes, w, h = _azure_boxes(10)
    r = detect_columns({"azure": boxes}, w, h)
    assert r.n_columns == 2
    # single provider flags but the body geometry itself is clean -> no escalate
    assert 0.45 * w <= r.gutter_x <= 0.58 * w
    assert r.escalate is False


@pytest.mark.skipif(not (_RAW / "page_0381.azure.json").exists(),
                    reason="raw/ not downloaded")
def test_real_page0381_table_escalates():
    # The sideways statistical table -- a single engine can mistake its vertical
    # rules for a clean 2-column split, so the catch is multi-engine disagreement.
    boxes, w, h = _azure_boxes(381)
    r = detect_columns({"azure": boxes, "abbyy": _abbyy_boxes(381)}, w, h)
    assert r.escalate is True
