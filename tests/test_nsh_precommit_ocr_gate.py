"""Tests for build/tools/nsh_precommit_ocr_gate.py -- the fast NSH OCR tripwire."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "nsh_precommit_ocr_gate",
    REPO_ROOT / "build" / "tools" / "nsh_precommit_ocr_gate.py",
)
_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gate)


class _FakeVH:
    """Stub for verify_nsh_running_headers: returns canned scan records."""

    def __init__(self, records):
        self._records = records

    def resolve_tesseract(self):
        return "tesseract"

    def scan_volume(self, volume, pages, workers=8):
        return self._records


def _ok(records, monkeypatch):
    monkeypatch.setattr(_gate, "sample_pages", lambda volume: list(range(1, len(records) + 1)))
    ok, _ = _gate.gate_volume(_FakeVH(records), 1)
    return ok


def test_selftest_passes():
    assert _gate._selftest() == 0


def test_sustained_offset_is_flagged(monkeypatch):
    # Every readable sample shows +4 -> rename signature -> FAIL.
    recs = [{"file": f"page_{p:04d}.jpg", "delta": 4} for p in (100, 200, 300, 400)]
    assert _ok(recs, monkeypatch) is False


def test_noise_floor_is_tolerated(monkeypatch):
    # delta-0 dominant with two isolated, non-agreeing misreads -> PASS.
    recs = [{"file": f"page_{p:04d}.jpg", "delta": 0} for p in (1, 2, 3, 4, 5)] + [
        {"file": "page_0250.jpg", "delta": 7},
        {"file": "page_0350.jpg", "delta": -2},
    ]
    assert _ok(recs, monkeypatch) is True


def test_too_few_readable_does_not_fail(monkeypatch):
    # Only 2 readable samples -> cannot judge -> not a failure (full audit covers it).
    recs = [
        {"file": "page_0100.jpg", "delta": 5},
        {"file": "page_0200.jpg", "delta": 5},
        {"file": "page_0300.jpg", "delta": None},
    ]
    assert _ok(recs, monkeypatch) is True


def test_two_agreeing_below_threshold_passes(monkeypatch):
    # Exactly 2 agreeing non-zero deltas is below MIN_OFFSET_RUN (3) -> PASS.
    recs = [
        {"file": "page_0100.jpg", "delta": 4},
        {"file": "page_0200.jpg", "delta": 4},
        {"file": "page_0300.jpg", "delta": 0},
        {"file": "page_0400.jpg", "delta": 0},
    ]
    assert _ok(recs, monkeypatch) is True


def test_staged_regex_matches_manifest_and_page_order_only():
    rx = _gate._STAGED_RE
    assert rx.match("raw/internet-archive/schaff-herzog-pages/vol_08.manifest.json")
    assert rx.match("raw/internet-archive/schaff-herzog-pages/vol_11/page_order.json")
    # A page image or unrelated path must NOT trigger the gate.
    assert not rx.match("raw/internet-archive/schaff-herzog-pages/vol_08/page_0100.jpg")
    assert not rx.match("build/tools/fetch_ia_pages.py")
