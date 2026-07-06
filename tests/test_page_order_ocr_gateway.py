"""Regression tests for the OCR-gateway fix (R-ocr-glob, design SS3 / SS6).

build/lib/page_order.py::volume_image_paths is the interface between the source
manifest and the six S1 OCR engines. Its old fallback globbed every *.jpg in the
volume dir, so once P3 lands leaf_*.jpg / plate_*.jpg on disk, illustration
plates and front/back matter would be swept into the OCR set. The fix selects
OCR input by kind (ocr_input(manifest) -> body only) and, with no manifest, falls
back to the body namespace page_*.jpg -- never leaf_* / plate_*.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.page_order import volume_image_paths  # noqa: E402


def _touch(path: Path) -> None:
    path.write_text("img", encoding="utf-8")


def _make_vol_dir(tmp_path: Path, vol: int = 7) -> Path:
    base = tmp_path / "schaff-herzog-pages"
    vol_dir = base / f"vol_{vol:02d}"
    vol_dir.mkdir(parents=True)
    # Body images + a future front-matter leaf image + a plate image on disk.
    _touch(vol_dir / "page_0001.jpg")
    _touch(vol_dir / "page_0002.jpg")
    _touch(vol_dir / "leaf_0005.jpg")
    _touch(vol_dir / "plate_0001_01.jpg")
    return vol_dir


def test_no_manifest_fallback_excludes_leaf_and_plate(tmp_path: Path) -> None:
    # Neither page_order.json nor a manifest: last-resort fallback must still
    # be page_*-scoped, never the broad *.jpg glob.
    vol_dir = _make_vol_dir(tmp_path)
    names = [p.name for p in volume_image_paths(vol_dir)]
    assert names == ["page_0001.jpg", "page_0002.jpg"]
    assert "leaf_0005.jpg" not in names
    assert "plate_0001_01.jpg" not in names


def test_legacy_manifest_ocr_input_excludes_leaf_and_plate(tmp_path: Path) -> None:
    vol_dir = _make_vol_dir(tmp_path)
    manifest = {
        "ia_item_id": "primary",
        "ia_derivative_type": "jp2",
        "volume": 7,
        "created_at": "2026-06-11T00:00:00+00:00",
        "page_count": 2,
        "pages": [
            {"page_num": 1, "ia_leaf_id": "0023", "ia_filename": "x_0023.jp2",
             "local_path": "raw/.../vol_07/page_0001.jpg"},
            {"page_num": 2, "ia_leaf_id": "0024", "ia_filename": "x_0024.jp2",
             "local_path": "raw/.../vol_07/page_0002.jpg"},
        ],
        "unnumbered_leaves": [
            {"leaf_num": 5, "page_num": None, "page_type": "Normal",
             "section": "front_matter", "ia_leaf_id": "0005",
             "ia_filename": "x_0005.jp2", "ia_item_id": "primary",
             "local_path": "raw/.../vol_07/leaf_0005.jpg",
             "sha256": "sha256:" + "0" * 64, "fetched_at": "2026-06-11T00:00:00+00:00",
             "image_mode": "L", "image_size": [10, 20]},
        ],
    }
    (vol_dir.parent / "vol_07.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    names = [p.name for p in volume_image_paths(vol_dir)]
    # Body only: the front-matter leaf_0005.jpg and plate are NOT OCR input.
    assert names == ["page_0001.jpg", "page_0002.jpg"]


def test_v4_manifest_ocr_input_excludes_plate(tmp_path: Path) -> None:
    vol_dir = _make_vol_dir(tmp_path)
    manifest = {
        "ia_item_id": "primary",
        "ia_derivative_type": "jp2",
        "volume": 7,
        "created_at": "2026-06-11T00:00:00+00:00",
        "leaves": [
            {"leaf_num": 5, "page_num": None, "kind": "front_matter", "image_state": "present",
             "local_path": "raw/.../vol_07/leaf_0005.jpg", "ia_leaf_id": "0005",
             "ia_filename": "x.jp2", "ia_item_id": "primary", "sha256": "sha256:" + "a" * 64,
             "fetched_at": "2026-06-11T00:00:00+00:00", "image_mode": "L", "image_size": [10, 20]},
            {"leaf_num": 23, "page_num": 1, "kind": "body", "image_state": "present",
             "local_path": "raw/.../vol_07/page_0001.jpg", "ia_leaf_id": "0023",
             "ia_filename": "x.jp2", "ia_item_id": "primary", "sha256": "sha256:" + "b" * 64,
             "fetched_at": "2026-06-11T00:00:00+00:00", "image_mode": "L", "image_size": [10, 20]},
            {"leaf_num": 24, "page_num": None, "kind": "plate", "after_page_num": 1,
             "image_state": "present", "local_path": "raw/.../vol_07/plate_0001_01.jpg",
             "ia_leaf_id": "0024", "ia_filename": "x.jp2", "ia_item_id": "primary",
             "sha256": "sha256:" + "c" * 64, "fetched_at": "2026-06-11T00:00:00+00:00",
             "image_mode": "RGB", "image_size": [10, 20]},
            {"leaf_num": 25, "page_num": 2, "kind": "body", "image_state": "present",
             "local_path": "raw/.../vol_07/page_0002.jpg", "ia_leaf_id": "0025",
             "ia_filename": "x.jp2", "ia_item_id": "primary", "sha256": "sha256:" + "d" * 64,
             "fetched_at": "2026-06-11T00:00:00+00:00", "image_mode": "L", "image_size": [10, 20]},
        ],
    }
    (vol_dir.parent / "vol_07.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    names = [p.name for p in volume_image_paths(vol_dir)]
    assert names == ["page_0001.jpg", "page_0002.jpg"]
    assert "plate_0001_01.jpg" not in names


def test_v4_manifest_include_front_back_adds_only_kept_leaf_images(tmp_path: Path) -> None:
    vol_dir = _make_vol_dir(tmp_path)
    _touch(vol_dir / "leaf_0006.jpg")
    _touch(vol_dir / "leaf_0007.jpg")
    _touch(vol_dir / "leaf_0008.jpg")
    _touch(vol_dir / "leaf_0009.jpg")
    manifest = {
        "ia_item_id": "primary",
        "ia_derivative_type": "jp2",
        "volume": 7,
        "created_at": "2026-06-11T00:00:00+00:00",
        "leaves": [
            {"leaf_num": 5, "page_num": None, "kind": "front_matter", "image_state": "present",
             "local_path": "raw/.../vol_07/leaf_0005.jpg", "sha256": "sha256:" + "a" * 64},
            {"leaf_num": 6, "page_num": None, "kind": "back_matter", "image_state": "present",
             "local_path": "raw/.../vol_07/leaf_0006.jpg", "sha256": "sha256:" + "b" * 64},
            {"leaf_num": 7, "page_num": None, "kind": "front_matter", "image_state": "present",
             "blank": True, "local_path": "raw/.../vol_07/leaf_0007.jpg", "sha256": "sha256:" + "c" * 64},
            {"leaf_num": 8, "page_num": None, "kind": "front_matter", "image_state": "not_imaged",
             "local_path": "raw/.../vol_07/leaf_0008.jpg", "sha256": "sha256:" + "d" * 64},
            {"leaf_num": 9, "page_num": None, "kind": "discarded", "image_state": "discarded",
             "local_path": "raw/.../vol_07/leaf_0009.jpg", "sha256": "sha256:" + "e" * 64},
            {"leaf_num": 10, "page_num": None, "kind": "front_matter", "image_state": "present",
             "local_path": "raw/.../vol_07/leaf_0010.jpg", "sha256": "sha256:" + "f" * 64},
            {"leaf_num": 23, "page_num": 1, "kind": "body", "image_state": "present",
             "local_path": "raw/.../vol_07/page_0001.jpg", "sha256": "sha256:" + "1" * 64},
            {"leaf_num": 24, "page_num": 2, "kind": "body", "image_state": "present",
             "local_path": "raw/.../vol_07/page_0002.jpg", "sha256": "sha256:" + "2" * 64},
        ],
    }
    (vol_dir.parent / "vol_07.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    names = [p.name for p in volume_image_paths(vol_dir, include_front_back=True)]

    assert names == ["page_0001.jpg", "page_0002.jpg", "leaf_0005.jpg", "leaf_0006.jpg"]


def test_include_front_back_without_source_manifest_returns_body_only(tmp_path: Path) -> None:
    vol_dir = _make_vol_dir(tmp_path)

    names = [p.name for p in volume_image_paths(vol_dir, include_front_back=True)]

    assert names == ["page_0001.jpg", "page_0002.jpg"]


def test_page_order_json_path_unchanged(tmp_path: Path) -> None:
    # When page_order.json is present (vol_01-style), the existing selection path
    # is used unchanged -- body entries by file, duplicate-role excluded.
    vol_dir = _make_vol_dir(tmp_path)
    page_order = {
        "schema": "page-order-v1",
        "pages": [
            {"seq": 1, "file": "page_0001.jpg", "corpus_role": "body"},
            {"seq": 2, "file": "page_0002.jpg", "corpus_role": "body"},
            {"seq": 3, "file": "leaf_0005.jpg", "corpus_role": "front-matter"},
        ],
    }
    (vol_dir / "page_order.json").write_text(json.dumps(page_order), encoding="utf-8")
    names = [p.name for p in volume_image_paths(vol_dir)]
    # page_order.json lists all three files, including the front-matter leaf, so
    # this path returns them as-is (P2 regenerates page_order from leaves[]).
    assert "page_0001.jpg" in names
    assert "page_0002.jpg" in names


def test_page_order_json_include_front_back_uses_source_manifest_supplement(tmp_path: Path) -> None:
    vol_dir = _make_vol_dir(tmp_path)
    page_order = {
        "schema": "page-order-v1",
        "pages": [
            {"seq": 1, "file": "page_0001.jpg", "corpus_role": "body"},
            {"seq": 2, "file": "page_0002.jpg", "corpus_role": "body"},
            {"seq": 3, "file": None, "corpus_role": "front-matter"},
        ],
    }
    manifest = {
        "volume": 7,
        "page_count": 2,
        "leaves": [
            {"leaf_num": 5, "page_num": None, "kind": "front_matter", "image_state": "present",
             "local_path": "raw/.../vol_07/leaf_0005.jpg", "sha256": "sha256:" + "a" * 64},
            {"leaf_num": 23, "page_num": 1, "kind": "body", "image_state": "present",
             "local_path": "raw/.../vol_07/page_0001.jpg", "sha256": "sha256:" + "1" * 64},
            {"leaf_num": 24, "page_num": 2, "kind": "body", "image_state": "present",
             "local_path": "raw/.../vol_07/page_0002.jpg", "sha256": "sha256:" + "2" * 64},
        ],
    }
    (vol_dir / "page_order.json").write_text(json.dumps(page_order), encoding="utf-8")
    (vol_dir.parent / "vol_07.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    default_names = [p.name for p in volume_image_paths(vol_dir)]
    opt_in_names = [p.name for p in volume_image_paths(vol_dir, include_front_back=True)]

    assert default_names == ["page_0001.jpg", "page_0002.jpg"]
    assert opt_in_names == ["page_0001.jpg", "page_0002.jpg", "leaf_0005.jpg"]
