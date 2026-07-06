"""Tests for build/tools/verify_nsh_running_headers.py path resolution.

Covers the --volume-dir override that lets the running-header OCR audit point at
a fresh rebuild directory (vol_NN_rebuild) BEFORE it is swapped to the live path,
so the live disk stays untouched until the gate passes (NSH rebuild procedure).
OCR itself is not exercised here -- only directory resolution and "all" globbing,
which are deterministic.
"""
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "verify_nsh_running_headers",
    REPO_ROOT / "build" / "tools" / "verify_nsh_running_headers.py",
)
_vh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_vh)


def _touch_page(d: Path, page_num: int) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / f"page_{page_num:04d}.jpg").write_bytes(b"\xff\xd8\xff\xe0stub")


def test_page_path_uses_volume_dir_override(tmp_path):
    """When set_volume_dir_override is active, _page_path resolves into it."""
    rebuild = tmp_path / "vol_08_rebuild"
    try:
        _vh.set_volume_dir_override(rebuild)
        p = _vh._page_path(8, 42)
        assert p == rebuild / "page_0042.jpg"
    finally:
        _vh.set_volume_dir_override(None)


def test_page_path_default_without_override():
    """With no override, _page_path uses the live PAGES_BASE/vol_NN path."""
    _vh.set_volume_dir_override(None)
    p = _vh._page_path(8, 42)
    assert p == _vh.PAGES_BASE / "vol_08" / "page_0042.jpg"


def test_parse_pages_spec_all_globs_override_dir(tmp_path):
    """'all' enumerates the override dir's page_*.jpg, not the live volume dir."""
    rebuild = tmp_path / "vol_08_rebuild"
    for pn in (1, 2, 5, 500):
        _touch_page(rebuild, pn)
    try:
        _vh.set_volume_dir_override(rebuild)
        nums = _vh.parse_pages_spec("all", 8)
        assert nums == [1, 2, 5, 500]
    finally:
        _vh.set_volume_dir_override(None)


def test_parse_pages_spec_all_skips_permanent_missing_in_override(tmp_path):
    """Permanent-missing pages are excluded from a range spec even on an override dir."""
    rebuild = tmp_path / "vol_13_rebuild"
    try:
        _vh.set_volume_dir_override(rebuild)
        # vol_13 perm-missing 209..211; a 207-212 range keeps only 207,208,212.
        # (vol_10's old 497..508 entry was removed -- it was a +8-corruption
        # artifact; vol_10 is complete at 499 after the 2026-06-12 image repair.)
        nums = _vh.parse_pages_spec("207-212", 13)
        assert nums == [207, 208, 212]
    finally:
        _vh.set_volume_dir_override(None)
