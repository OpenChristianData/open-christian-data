"""Tests for the R6a pre-run reuse summary line."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.ocr_prerun_log import (  # noqa: E402
    format_prerun_summary,
    format_unresolved_leaf_note,
)


def test_all_reused_shows_zero_to_ocr():
    # The redo-regression tripwire: everything reused must read "0 to OCR".
    line = format_prerun_summary("tesseract-py314-v1", 1, 500, 500)
    assert line == "    tesseract-py314-v1 vol_01: 500 leaves | 500 reused | 0 to OCR"


def test_nothing_reused_shows_all_to_ocr():
    line = format_prerun_summary("kraken-py312-v1", 11, 497, 0)
    assert line == "    kraken-py312-v1 vol_11: 497 leaves | 0 reused | 497 to OCR"


def test_partial_reuse_subtracts():
    line = format_prerun_summary("surya-py312-v1", 7, 100, 88)
    assert "100 leaves | 88 reused | 12 to OCR" in line


_SHA = "sha256:e11717a6560b40bc179dccf650d529527e7b4c578609dcdd54fa636724119840"


def test_unresolved_leaf_note_is_silent_when_edition_keyed():
    # A recovered-gap / front-back page has no body-leaf coordinate by design
    # (clid_exempt) but carries an edition_page_key, so it joins the
    # reconciliation chain normally -- not a defect, must NOT warn.
    note = format_unresolved_leaf_note(
        lineage="tesseract-py314-v1",
        volume=1,
        sha=_SHA,
        reason="sha resolved to 0 leaves",
        edition_key={"section": "body", "anchor": 96, "ordinal": 0},
    )
    assert note is None


def test_unresolved_leaf_note_warns_when_no_edition_key():
    # NEITHER a canonical_leaf_id NOR an edition_page_key resolves: a genuine
    # defect (also fails sidecar-page-v1 validation, which requires
    # edition_page_key), flagged loudly.
    note = format_unresolved_leaf_note(
        lineage="tesseract-py314-v1",
        volume=1,
        sha=_SHA,
        reason="sha resolved to 0 leaves",
        edition_key=None,
    )
    assert note is not None
    assert "vol_01" in note
    assert _SHA[:18] in note
    # The new wording must reference edition_page_key (the real missing key),
    # not imply a normal gap page was broken.
    assert "edition_page_key" in note
