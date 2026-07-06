"""Tests for build/tools/swap_nsh_rebuild.rewrite_manifest_local_paths.

The swap promotes the rebuild manifest (whose local_path values point at the
``vol_NN_rebuild`` staging dir) and moves the images into the live ``vol_NN``
dir. Without rewriting local_path, every committed manifest references the
now-empty staging dir (the 5-volume bug). This function performs that rewrite.
"""
import importlib.util
from pathlib import Path

_MOD = Path(__file__).resolve().parents[1] / "build" / "tools" / "swap_nsh_rebuild.py"
_spec = importlib.util.spec_from_file_location("swap_nsh_rebuild", _MOD)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

_BASE = "raw/internet-archive/schaff-herzog-pages"


def test_rewrites_pages_local_path_from_staging_to_live():
    manifest = {"pages": [{"page_num": 1, "local_path": f"{_BASE}/vol_01_rebuild/page_0001.jpg"}]}
    changed = mod.rewrite_manifest_local_paths(manifest, "vol_01")
    assert changed == 1
    assert manifest["pages"][0]["local_path"] == f"{_BASE}/vol_01/page_0001.jpg"


def test_rewrites_unnumbered_leaves_local_path_too():
    manifest = {
        "pages": [],
        "unnumbered_leaves": [{"leaf_num": 0, "local_path": f"{_BASE}/vol_08_rebuild/leaf_0000.jpg"}],
    }
    changed = mod.rewrite_manifest_local_paths(manifest, "vol_08")
    assert changed == 1
    assert manifest["unnumbered_leaves"][0]["local_path"] == f"{_BASE}/vol_08/leaf_0000.jpg"


def test_leaves_already_live_paths_unchanged():
    manifest = {"pages": [{"page_num": 1, "local_path": f"{_BASE}/vol_05/page_0001.jpg"}]}
    changed = mod.rewrite_manifest_local_paths(manifest, "vol_05")
    assert changed == 0
    assert manifest["pages"][0]["local_path"] == f"{_BASE}/vol_05/page_0001.jpg"


def test_returns_zero_when_no_pages():
    assert mod.rewrite_manifest_local_paths({"pages": []}, "vol_02") == 0


# --- P0.5: v4 leaves[] repoint + plate/leaf image move ---------------------


def test_rewrites_leaves_local_path_v4_shape():
    # The vol_11 swap (P1) promotes a v4 manifest carrying leaves[].local_path;
    # those must be repointed from the staging dir too, not just the legacy arrays.
    manifest = {
        "leaves": [
            {"leaf_num": 23, "page_num": 1, "kind": "body",
             "local_path": f"{_BASE}/vol_11_rebuild/page_0001.jpg"},
            {"leaf_num": 288, "page_num": None, "kind": "plate",
             "local_path": f"{_BASE}/vol_11_rebuild/plate_0260_01.jpg"},
            {"leaf_num": 5, "page_num": None, "kind": "front_matter",
             "local_path": f"{_BASE}/vol_11_rebuild/leaf_0005.jpg"},
        ]
    }
    changed = mod.rewrite_manifest_local_paths(manifest, "vol_11")
    assert changed == 3
    assert manifest["leaves"][0]["local_path"] == f"{_BASE}/vol_11/page_0001.jpg"
    assert manifest["leaves"][1]["local_path"] == f"{_BASE}/vol_11/plate_0260_01.jpg"
    assert manifest["leaves"][2]["local_path"] == f"{_BASE}/vol_11/leaf_0005.jpg"


def test_leaves_without_local_path_skipped():
    manifest = {"leaves": [{"leaf_num": 6, "page_num": None, "kind": "front_matter",
                            "image_state": "not_imaged", "blank": True}]}
    assert mod.rewrite_manifest_local_paths(manifest, "vol_11") == 0


def test_volume_swap_images_includes_page_leaf_and_plate(tmp_path):
    # The swap must move plate_*.jpg + leaf_*.jpg, not just page_*.jpg, or
    # vol_11's plates are left behind in the staging dir.
    d = tmp_path / "vol_11_rebuild"
    d.mkdir()
    for name in ("page_0001.jpg", "page_0002.jpg", "leaf_0005.jpg",
                 "plate_0260_01.jpg", "plate_0260_02.jpg"):
        (d / name).write_text("img", encoding="utf-8")
    # Non-image sidecars must NOT be selected as images to move.
    (d / "page_0001.ia-abbyy.json").write_text("{}", encoding="utf-8")
    (d / "coverage.json").write_text("{}", encoding="utf-8")

    names = sorted(p.name for p in mod._volume_swap_images(d))
    assert names == [
        "leaf_0005.jpg", "page_0001.jpg", "page_0002.jpg",
        "plate_0260_01.jpg", "plate_0260_02.jpg",
    ]


def test_volume_swap_images_page_only_volume(tmp_path):
    # A legacy volume with only page_*.jpg is unchanged (no plate/leaf to move).
    d = tmp_path / "vol_07_rebuild"
    d.mkdir()
    (d / "page_0001.jpg").write_text("img", encoding="utf-8")
    (d / "page_0002.jpg").write_text("img", encoding="utf-8")
    names = sorted(p.name for p in mod._volume_swap_images(d))
    assert names == ["page_0001.jpg", "page_0002.jpg"]


# --- P1 (vol_11): primary-sidecar swap for a re-keyed volume ----------------
# vol_11's LIVE primary sidecars are scan-position-keyed (squeezed); the rebuild
# re-keyed them to true page. So the vol_11 swap must replace the primary
# ia-abbyy + azure (+ plate) sidecars too -- while PRESERVING the leaf-indexed
# alternates (page_leaf*, *-dli*, *haucgoog*) that share the dir.


def _make_rekey_dir(root: Path) -> Path:
    d = root
    d.mkdir(parents=True, exist_ok=True)
    # numbered primary sidecars (must be selected)
    for name in (
        "page_0001.ia-abbyy.json", "page_0001.ia-abbyy.raw.xml",
        "page_0476.azure.json", "page_0476.azure.raw.json",
        "plate_0260_01.ia-abbyy.json", "plate_0260_01.ia-abbyy.raw.xml",
    ):
        (d / name).write_text("{}", encoding="utf-8")
    # alternates + images + coverage (must NOT be selected)
    for name in (
        "page_leaf0000.ia-abbyy.json", "page_leaf0000.ia-abbyy.raw.xml",
        "coverage.ia-abbyy-dli.json", "coverage.ia-abbyy-haucgoog-c1.json",
        "page_0001.jpg", "plate_0260_01.jpg", "page_order.json", "coverage.json",
    ):
        (d / name).write_text("x", encoding="utf-8")
    return d


def test_volume_swap_sidecars_selects_numbered_and_plate_primary(tmp_path):
    d = _make_rekey_dir(tmp_path / "vol_11_rebuild")
    names = sorted(p.name for p in mod._volume_swap_sidecars(d))
    assert names == [
        "page_0001.ia-abbyy.json", "page_0001.ia-abbyy.raw.xml",
        "page_0476.azure.json", "page_0476.azure.raw.json",
        "plate_0260_01.ia-abbyy.json", "plate_0260_01.ia-abbyy.raw.xml",
    ]


def test_volume_swap_sidecars_excludes_alternates_images_and_coverage(tmp_path):
    d = _make_rekey_dir(tmp_path / "vol_11_rebuild")
    names = {p.name for p in mod._volume_swap_sidecars(d)}
    for excluded in (
        "page_leaf0000.ia-abbyy.json", "page_leaf0000.ia-abbyy.raw.xml",
        "coverage.ia-abbyy-dli.json", "coverage.ia-abbyy-haucgoog-c1.json",
        "page_0001.jpg", "plate_0260_01.jpg", "page_order.json", "coverage.json",
    ):
        assert excluded not in names, f"{excluded} must not be swapped"


def test_volume_swap_sidecars_empty_for_image_only_dir(tmp_path):
    d = tmp_path / "vol_07_rebuild"
    d.mkdir()
    (d / "page_0001.jpg").write_text("img", encoding="utf-8")
    assert mod._volume_swap_sidecars(d) == []
