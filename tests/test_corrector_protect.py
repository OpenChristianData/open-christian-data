from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.gold_free_corrector.protect import (  # noqa: E402
    build_consensus_capitalized_gazetteer,
    protected_class_for_position,
    protected_signal_for_position,
)


# The live vol_01 WCT is gitignored and was quarantined in R-final.3 (stale
# pre-phantom-rename content); the full WCT rebuild restores it. Tests that read
# the real page skip when it is absent (mirrors test_align_ccel_to_wct).
_WCT_PAGE = REPO_ROOT / "reports" / "wct" / "vol_01" / "page_0010.json"


def _load_wct_page() -> dict:
    if not _WCT_PAGE.exists():
        pytest.skip("vol_01 WCT quarantined (R-final.3); restored by the full WCT rebuild")
    return json.loads(_WCT_PAGE.read_text(encoding="utf-8"))


def _position(position_id: str) -> dict:
    page = _load_wct_page()
    return next(position for position in page["positions"] if position["position_id"] == position_id)


def test_abelard_real_wct_position_is_proper_name() -> None:
    page = _load_wct_page()
    gazetteer = build_consensus_capitalized_gazetteer(page["positions"])

    position = _position("vol_01:page_0010:body:c1:l000:p000")

    assert protected_class_for_position(position, gazetteer=gazetteer) == "proper_name"


def test_number_and_date_tokens_are_separate_classes() -> None:
    number_position = {
        "script": {"text_level": {"label": "latin"}},
        "candidate_set": [{"raw_reading": "42", "candidate_key": "42"}],
    }
    date_position = _position("vol_01:page_0010:body:c1:l018:p004")

    assert protected_class_for_position(number_position) == "number"
    assert protected_class_for_position(date_position) == "date"


def test_scripture_reference_reuses_existing_parser_shape() -> None:
    position = {
        "script": {"text_level": {"label": "latin"}},
        "candidate_set": [{"raw_reading": "John 3:16", "candidate_key": "John 3:16"}],
    }

    signal = protected_signal_for_position(position)

    assert signal.protected_class == "scripture_ref"
    assert signal.source == "bible_ref_normalizer.extract_refs_from_text"


def test_plain_lowercase_body_word_is_not_protected() -> None:
    position = _position("vol_01:page_0010:body:c1:l002:p000")

    assert protected_class_for_position(position) is None


def test_greek_and_hebrew_use_existing_script_signal() -> None:
    greek_position = {
        "script": {"text_level": {"label": "greek"}},
        "candidate_set": [{"raw_reading": "λόγος", "candidate_key": "λόγος"}],
    }
    hebrew_position = {
        "script": {"text_level": {"label": "hebrew"}},
        "candidate_set": [{"raw_reading": "דבר", "candidate_key": "דבר"}],
    }

    assert protected_signal_for_position(greek_position).protected_class == "greek"
    assert protected_signal_for_position(greek_position).source == "script.text_level.label"
    assert protected_signal_for_position(hebrew_position).protected_class == "hebrew"
