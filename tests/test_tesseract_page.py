"""Tests for tesseract_page.py config constants and CLI args.

Covers the PY-03 fix: LANGUAGES, PSM, OEM moved to module-level constants
and exposed as overridable CLI arguments.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from build.tools.ocr_runners import tesseract_page  # noqa: E402


# ---------------------------------------------------------------------------
# Module-level constants (PY-03)
# ---------------------------------------------------------------------------


def test_languages_constant_exists_with_nsh_languages() -> None:
    """LANGUAGES is at module level and includes the NSH multilingual set."""
    langs = tesseract_page.LANGUAGES
    assert isinstance(langs, str)
    for lang in ("eng", "grc", "heb", "lat"):
        assert lang in langs, f"Expected language {lang!r} in LANGUAGES"


def test_psm_constant_is_string_three() -> None:
    """PSM is '3' (auto without OSD) — NSH pages are consistently oriented so OSD is skipped."""
    assert tesseract_page.PSM == "3"


def test_oem_constant_exists_at_module_level() -> None:
    """OEM constant is present at module level (None = use Tesseract default)."""
    assert hasattr(tesseract_page, "OEM")
    # Default is None -- do not force OEM, preserving prior behavior.
    assert tesseract_page.OEM is None


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def test_parse_args_default_languages() -> None:
    """--languages defaults to the module-level LANGUAGES constant."""
    args = tesseract_page.parse_args(["--image", "page.jpg"])
    assert args.languages == tesseract_page.LANGUAGES


def test_parse_args_custom_languages() -> None:
    """--languages overrides the default for a single run."""
    args = tesseract_page.parse_args(["--image", "page.jpg", "--languages", "eng+fra"])
    assert args.languages == "eng+fra"


def test_parse_args_default_psm() -> None:
    """--psm defaults to the module-level PSM constant."""
    args = tesseract_page.parse_args(["--image", "page.jpg"])
    assert args.psm == tesseract_page.PSM


def test_parse_args_custom_psm() -> None:
    """--psm overrides the default for a single run."""
    args = tesseract_page.parse_args(["--image", "page.jpg", "--psm", "3"])
    assert args.psm == "3"


def test_parse_args_default_oem_is_none() -> None:
    """--oem defaults to None (Tesseract picks its own engine mode)."""
    args = tesseract_page.parse_args(["--image", "page.jpg"])
    assert args.oem is None


def test_parse_args_custom_oem() -> None:
    """--oem overrides the default for a single run."""
    args = tesseract_page.parse_args(["--image", "page.jpg", "--oem", "1"])
    assert args.oem == "1"
