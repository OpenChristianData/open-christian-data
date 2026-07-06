"""test_versification_map.py
Smoke tests for translate_hebrew_to_english() in build/scripts/validate_osis.py.

Comprehensive regression coverage for all versification systems in the corpus.
See also TestTranslateHebrewToEnglish in test_bible_ref_normalizer.py for
additional cases built up during parser development.

Retro finding 2026-04-14: new parsers shipped without automated tests.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.scripts.validate_osis import translate_hebrew_to_english  # noqa: E402


# ---------------------------------------------------------------------------
# Joel: Hebrew has 4 chapters, English has 3 (ch.4 -> ch.3)
# ---------------------------------------------------------------------------

def test_joel_ch4_v1_maps_to_ch3_v1():
    assert translate_hebrew_to_english("Joel.4.1") == "Joel.3.1"


def test_joel_ch4_v21_maps_to_ch3_v21():
    assert translate_hebrew_to_english("Joel.4.21") == "Joel.3.21"


# ---------------------------------------------------------------------------
# Malachi: Hebrew has no ch.4; KJV splits Heb 3:19-24 into Eng ch.4
# ---------------------------------------------------------------------------

def test_malachi_3_19_maps_to_4_1():
    assert translate_hebrew_to_english("Mal.3.19") == "Mal.4.1"


def test_malachi_3_24_maps_to_4_6():
    assert translate_hebrew_to_english("Mal.3.24") == "Mal.4.6"


# ---------------------------------------------------------------------------
# Hosea: ch.14 verse-count difference and ch.2 boundary
# ---------------------------------------------------------------------------

def test_hosea_14_10_maps_to_14_9():
    """Hebrew Hos 14 has 10 verses; English has 9."""
    assert translate_hebrew_to_english("Hos.14.10") == "Hos.14.9"


def test_hosea_2_1_returns_none():
    """Hos.2.1-2 map across chapter boundary to English Hos 1:10-11.
    The function only translates verse >= 3 (body start); cross-chapter
    cases return None since the caller handles valid refs natively."""
    assert translate_hebrew_to_english("Hos.2.1") is None


# ---------------------------------------------------------------------------
# Isaiah: Hebrew Isa 8:23 = English Isa 9:1 (chapter boundary split)
# ---------------------------------------------------------------------------

def test_isaiah_8_23_maps_to_9_1():
    assert translate_hebrew_to_english("Isa.8.23") == "Isa.9.1"


# ---------------------------------------------------------------------------
# Job: ch.40 Keil-Delitzsch / Luther Bible chapter boundary
# ---------------------------------------------------------------------------

def test_job_40_26_maps_to_41_2():
    """Expositor's Bible case: KD/Luther Bible Job 40:26 = English Job 41:2."""
    assert translate_hebrew_to_english("Job.40.26") == "Job.41.2"


# ---------------------------------------------------------------------------
# Psalm superscription offsets
# ---------------------------------------------------------------------------

def test_psalm_double_superscription_51_body_start():
    """Ps.51.3 (Hebrew, double-super Psalm) -> Ps.51.1 (English body start)."""
    assert translate_hebrew_to_english("Ps.51.3") == "Ps.51.1"


def test_psalm_double_superscription_52_body_start():
    assert translate_hebrew_to_english("Ps.52.3") == "Ps.52.1"


def test_psalm_double_superscription_60_body_start():
    assert translate_hebrew_to_english("Ps.60.3") == "Ps.60.1"


def test_psalm_single_superscription_3_body_start():
    """Ps.3.2 (Hebrew body start, single-super Psalm) -> Ps.3.1 (English)."""
    assert translate_hebrew_to_english("Ps.3.2") == "Ps.3.1"


# ---------------------------------------------------------------------------
# LXX additions: Esther (continuous numbering)
# ---------------------------------------------------------------------------

def test_esther_14_1_maps_to_addEsth():
    """LXX continuous numbering: Esth ch.14+ is an addition."""
    assert translate_hebrew_to_english("Esth.14.1") == "AddEsth.14.1"


def test_esther_16_24_maps_to_addEsth():
    assert translate_hebrew_to_english("Esth.16.24") == "AddEsth.16.24"


# ---------------------------------------------------------------------------
# LXX additions: Daniel (Prayer of Azariah insertion)
# ---------------------------------------------------------------------------

def test_daniel_3_24_maps_to_prazar_1_1():
    """Dan.3.24 = PrAzar.1.1 (first verse of the insertion, offset 23)."""
    assert translate_hebrew_to_english("Dan.3.24") == "PrAzar.1.1"


def test_daniel_3_90_maps_to_prazar_1_67():
    """Dan.3.90 = PrAzar.1.67 (verse 90 - offset 23 = verse 67)."""
    assert translate_hebrew_to_english("Dan.3.90") == "PrAzar.1.67"


# ---------------------------------------------------------------------------
# Pass-through: no mapping applies, returns None
# ---------------------------------------------------------------------------

def test_genesis_1_1_returns_none():
    """OT book with no versification shift -> None."""
    assert translate_hebrew_to_english("Gen.1.1") is None


def test_matthew_5_3_returns_none():
    """NT refs never need Hebrew-to-English translation -> None."""
    assert translate_hebrew_to_english("Matt.5.3") is None


# ---------------------------------------------------------------------------
# Run directly for quick feedback
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
