"""Tests for build/tools/rebuild_nsh_pages — the idempotent disk-as-ground-truth
page-count reconciler from the 2026-06-09 phantom-page post-mortem.

Covers the pure helpers and the reconcile contract on a synthetic volume:
disk is ground truth, page_count = present + permanently_missing, the run is
idempotent (TEST-05), dry-run writes nothing, and pages[] provenance is never
fabricated (the deliberately-narrow contract in the module docstring).
"""
import importlib.util
import json
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "build" / "tools" / "rebuild_nsh_pages.py"
_spec = importlib.util.spec_from_file_location("rebuild_nsh_pages", _MOD_PATH)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_disk_page_count_counts_only_page_jpgs(tmp_path):
    (tmp_path / "page_0001.jpg").write_bytes(b"x")
    (tmp_path / "page_0002.jpg").write_bytes(b"x")
    (tmp_path / "leaf_0000.jpg").write_bytes(b"x")  # not a body page
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")

    assert mod._disk_page_count(tmp_path) == 2


def test_perm_missing_counts_only_permanently_missing():
    manifest = {
        "gaps": [
            {"page_num": 5, "status": "permanently_missing"},
            {"page_num": 6, "status": "absent_from_primary_scan"},
            {"page_num": 7, "status": "duplicate_needs_adjudication"},
        ]
    }
    # Only "permanently_missing" counts toward page_count here (the verifier
    # independently asserts the broader body-missing set).
    assert mod._perm_missing_from_manifest(manifest) == 1


def test_write_manifest_atomic_writes_valid_json_and_leaves_no_tmp(tmp_path):
    path = tmp_path / "vol_01.manifest.json"
    manifest = {"page_count": 3, "pages": [{"page_num": 1}], "gaps": []}

    mod._write_manifest_atomic(path, manifest)

    assert json.loads(path.read_text(encoding="utf-8")) == manifest
    assert not list(tmp_path.glob("*.tmp"))


def _setup_volume(base: Path, *, disk_pages, page_count, gaps=None, pages=None):
    vol_dir = base / "vol_01"
    vol_dir.mkdir(parents=True, exist_ok=True)
    for pn in disk_pages:
        (vol_dir / f"page_{pn:04d}.jpg").write_bytes(b"\xff\xd8\xff")
    manifest = {
        "page_count": page_count,
        "pages": pages if pages is not None else [{"page_num": pn, "ia_leaf_id": str(20 + pn)} for pn in disk_pages],
        "gaps": gaps or [],
    }
    manifest_path = base / "vol_01.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def test_reconcile_dry_run_reports_change_but_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "PAGES_DIR", tmp_path)
    monkeypatch.setattr(mod, "VOLUMES", [1])
    # Manifest says 5, disk has 3, no perm-missing -> correct count is 3.
    manifest_path = _setup_volume(tmp_path, disk_pages=[1, 2, 3], page_count=5)
    before = manifest_path.read_text(encoding="utf-8")

    changed = mod.reconcile_page_counts(dry_run=True)

    assert changed == 1
    assert manifest_path.read_text(encoding="utf-8") == before  # untouched


def test_reconcile_sets_count_from_disk_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "PAGES_DIR", tmp_path)
    monkeypatch.setattr(mod, "VOLUMES", [1])
    # Disk has 4 present + 1 permanently-missing hole -> page_count should be 5.
    manifest_path = _setup_volume(
        tmp_path,
        disk_pages=[1, 2, 3, 4],
        page_count=99,
        gaps=[{"page_num": 5, "status": "permanently_missing"}],
    )

    first = mod.reconcile_page_counts(dry_run=False)
    assert first == 1
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["page_count"] == 5

    # TEST-05: a second run on the now-correct corpus is a no-op.
    second = mod.reconcile_page_counts(dry_run=False)
    assert second == 0


def test_reconcile_never_fabricates_pages_array(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "PAGES_DIR", tmp_path)
    monkeypatch.setattr(mod, "VOLUMES", [1])
    pages = [{"page_num": pn, "ia_leaf_id": str(20 + pn), "sha256": f"deadbeef{pn}"} for pn in (1, 2, 3)]
    manifest_path = _setup_volume(tmp_path, disk_pages=[1, 2, 3], page_count=42, pages=pages)

    mod.reconcile_page_counts(dry_run=False)

    # page_count fixed; provenance-bearing pages[] left exactly as-is.
    written = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert written["page_count"] == 3
    assert written["pages"] == pages
