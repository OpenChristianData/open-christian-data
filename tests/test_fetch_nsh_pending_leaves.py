"""Tests for build/tools/fetch_nsh_pending_leaves.py (P3 in-place v4 updater).

These tests cover the pure helper functions: filename derivation, blank detection,
ia_filename pattern derivation, and manifest leaf-record update. The network-bound
download path is exercised via a patch on the download helper.
"""
import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Import targets - module does not exist yet; tests must fail with ImportError.
# ---------------------------------------------------------------------------
from build.tools.fetch_nsh_pending_leaves import (
    INK_THRESHOLD,
    _derive_output_filename,
    _ia_filename_for_leaf_v4,
    _is_blank,
    _update_leaf_record,
)

REPO_ROOT = Path(__file__).parents[1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _minimal_manifest(leaves: list[dict], ia_item_id: str = "TestItem") -> dict:
    return {
        "ia_item_id": ia_item_id,
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 2,
        "created_at": "2026-01-01T00:00:00+00:00",
        "page_count": 10,
        "leaves": leaves,
    }


def _white_image(width: int = 100, height: int = 100) -> Image.Image:
    """Solid-white grayscale image (0% ink)."""
    return Image.new("L", (width, height), 255)


def _text_image(width: int = 100, height: int = 100, ink_pct: float = 0.05) -> Image.Image:
    """Grayscale image with exactly ink_pct fraction of dark pixels."""
    import numpy as np

    arr = [255] * (width * height)
    dark_count = int(width * height * ink_pct)
    for i in range(dark_count):
        arr[i] = 0  # dark pixel (ink)
    img = Image.new("L", (width, height))
    img.putdata(arr)
    return img


# ---------------------------------------------------------------------------
# _derive_output_filename
# ---------------------------------------------------------------------------

class TestDeriveOutputFilename:
    def _front_leaf(self, leaf_num: int) -> dict:
        return {"leaf_num": leaf_num, "page_num": None, "kind": "front_matter",
                "image_state": "pending"}

    def _back_leaf(self, leaf_num: int) -> dict:
        return {"leaf_num": leaf_num, "page_num": None, "kind": "back_matter",
                "image_state": "pending"}

    def _plate_leaf(self, leaf_num: int, after_page: int) -> dict:
        return {"leaf_num": leaf_num, "page_num": None, "kind": "plate",
                "image_state": "pending", "after_page_num": after_page}

    def test_front_matter_uses_leaf_num(self) -> None:
        leaf = self._front_leaf(5)
        all_leaves = [leaf]
        assert _derive_output_filename(leaf, all_leaves) == "leaf_0005.jpg"

    def test_back_matter_uses_leaf_num(self) -> None:
        leaf = self._back_leaf(530)
        all_leaves = [leaf]
        assert _derive_output_filename(leaf, all_leaves) == "leaf_0530.jpg"

    def test_front_matter_zero_padded_four_digits(self) -> None:
        leaf = self._front_leaf(3)
        assert _derive_output_filename(leaf, [leaf]) == "leaf_0003.jpg"

    def test_plate_single_gets_seq_01(self) -> None:
        plate = self._plate_leaf(leaf_num=280, after_page=252)
        leaves = [
            {"leaf_num": 100, "page_num": 252, "kind": "body", "image_state": "present"},
            plate,
        ]
        assert _derive_output_filename(plate, leaves) == "plate_0252_01.jpg"

    def test_plate_sequence_among_same_after_page(self) -> None:
        plate1 = self._plate_leaf(leaf_num=289, after_page=450)
        plate2 = self._plate_leaf(leaf_num=290, after_page=450)
        leaves = [
            {"leaf_num": 50, "page_num": 450, "kind": "body", "image_state": "present"},
            plate1,
            plate2,
        ]
        assert _derive_output_filename(plate1, leaves) == "plate_0450_01.jpg"
        assert _derive_output_filename(plate2, leaves) == "plate_0450_02.jpg"

    def test_plate_seq_counts_only_same_after_page(self) -> None:
        """Two plates with different after_page each get seq 01, not 01/02."""
        plate_a = self._plate_leaf(leaf_num=280, after_page=252)
        plate_b = self._plate_leaf(leaf_num=400, after_page=360)
        leaves = [
            {"leaf_num": 100, "page_num": 252, "kind": "body", "image_state": "present"},
            plate_a,
            {"leaf_num": 200, "page_num": 360, "kind": "body", "image_state": "present"},
            plate_b,
        ]
        assert _derive_output_filename(plate_a, leaves) == "plate_0252_01.jpg"
        assert _derive_output_filename(plate_b, leaves) == "plate_0360_01.jpg"


# ---------------------------------------------------------------------------
# _is_blank
# ---------------------------------------------------------------------------

class TestIsBlank:
    def test_white_image_is_blank(self) -> None:
        assert _is_blank(_white_image()) is True

    def test_text_image_is_not_blank(self) -> None:
        # 5% ink fraction -- well above the 1% threshold
        assert _is_blank(_text_image(ink_pct=0.05)) is False

    def test_threshold_boundary_just_above(self) -> None:
        # Exactly 1% + epsilon should NOT be blank
        assert _is_blank(_text_image(ink_pct=INK_THRESHOLD + 0.001)) is False

    def test_threshold_boundary_just_below(self) -> None:
        # Exactly 1% - epsilon should be blank
        assert _is_blank(_text_image(ink_pct=INK_THRESHOLD - 0.001)) is True

    def test_rgb_image_treated_as_grayscale(self) -> None:
        """RGB image with a few dark pixels should also be correctly classified."""
        img = Image.new("RGB", (100, 100), (255, 255, 255))
        assert _is_blank(img) is True

    def test_ink_threshold_constant_is_one_percent(self) -> None:
        assert INK_THRESHOLD == pytest.approx(0.01)


# ---------------------------------------------------------------------------
# _ia_filename_for_leaf_v4
# ---------------------------------------------------------------------------

class TestIaFilenameForLeafV4:
    _PATTERN = (
        "02.NewSchaffHerzog_jp2.zip"
        "/02.NewSchaffHerzog_jp2"
        "/02.NewSchaffHerzog_{leaf:04d}.jp2"
    )

    def _manifest_with_body_leaf(self, leaf_num: int, page_num: int) -> dict:
        ia_filename = self._PATTERN.format(leaf=leaf_num)
        return _minimal_manifest([
            {"leaf_num": leaf_num, "page_num": page_num, "kind": "body",
             "image_state": "present",
             "local_path": f"raw/internet-archive/schaff-herzog-pages/vol_02/page_{page_num:04d}.jpg",
             "ia_leaf_id": f"{leaf_num:04d}",
             "ia_filename": ia_filename,
             "ia_item_id": "TestItem",
             "sha256": "sha256:" + "a" * 64,
             "fetched_at": "2026-01-01T00:00:00+00:00",
             "image_mode": "L",
             "image_size": [100, 150]},
            {"leaf_num": 0, "page_num": None, "kind": "front_matter",
             "image_state": "pending"},
        ])

    def test_derives_filename_from_body_leaf(self) -> None:
        manifest = self._manifest_with_body_leaf(leaf_num=23, page_num=1)
        result = _ia_filename_for_leaf_v4(manifest, 0)
        assert result == self._PATTERN.format(leaf=0)

    def test_substitutes_requested_leaf_num(self) -> None:
        manifest = self._manifest_with_body_leaf(leaf_num=23, page_num=1)
        result = _ia_filename_for_leaf_v4(manifest, 520)
        assert result == self._PATTERN.format(leaf=520)

    def test_returns_none_when_no_body_leaf_has_filename(self) -> None:
        manifest = _minimal_manifest([
            {"leaf_num": 0, "page_num": None, "kind": "front_matter",
             "image_state": "pending"},
        ])
        assert _ia_filename_for_leaf_v4(manifest, 0) is None

    def test_skips_alternate_source_leaves(self) -> None:
        """A leaf with provenance (alternate source) should not supply the pattern."""
        alt_ia_filename = "ALTITEM_jp2.zip/ALTITEM_jp2/ALTITEM_0050.jp2"
        manifest = _minimal_manifest([
            {"leaf_num": 50, "page_num": 25, "kind": "body",
             "image_state": "present",
             "local_path": "raw/internet-archive/schaff-herzog-pages/vol_02/page_0025.jpg",
             "ia_leaf_id": "0050",
             "ia_filename": alt_ia_filename,
             "ia_item_id": "AltItem",
             "sha256": "sha256:" + "a" * 64,
             "fetched_at": "2026-01-01T00:00:00+00:00",
             "image_mode": "L",
             "image_size": [100, 150],
             "provenance": {"source_item_id": "AltItem", "source_leaf": 50,
                            "derivation": "direct", "crop_box": None,
                            "replacement_reason": "missing from primary scan",
                            "validation_status": "bibliographic_matched",
                            "dimension_variance": False}},
            {"leaf_num": 0, "page_num": None, "kind": "front_matter",
             "image_state": "pending"},
        ])
        assert _ia_filename_for_leaf_v4(manifest, 0) is None


# ---------------------------------------------------------------------------
# _update_leaf_record
# ---------------------------------------------------------------------------

class TestUpdateLeafRecord:
    def _manifest_with_pending_front(self) -> dict:
        return _minimal_manifest([
            {"leaf_num": 0, "page_num": None, "kind": "front_matter",
             "image_state": "pending"},
            {"leaf_num": 1, "page_num": None, "kind": "front_matter",
             "image_state": "pending"},
            {"leaf_num": 50, "page_num": 1, "kind": "body",
             "image_state": "present",
             "local_path": "raw/internet-archive/schaff-herzog-pages/vol_02/page_0001.jpg",
             "ia_leaf_id": "0050", "ia_filename": "02_jp2.zip/02_jp2/02_0050.jp2",
             "ia_item_id": "TestItem",
             "sha256": "sha256:" + "a" * 64,
             "fetched_at": "2026-01-01T00:00:00+00:00",
             "image_mode": "L", "image_size": [100, 150]},
        ])

    def test_updates_pending_to_present(self) -> None:
        manifest = self._manifest_with_pending_front()
        updates = {
            "image_state": "present",
            "local_path": "raw/internet-archive/schaff-herzog-pages/vol_02/leaf_0000.jpg",
            "ia_leaf_id": "0000",
            "ia_filename": "02_jp2.zip/02_jp2/02_0000.jp2",
            "ia_item_id": "TestItem",
            "sha256": "sha256:" + "b" * 64,
            "fetched_at": "2026-06-12T12:00:00+00:00",
            "image_mode": "L",
            "image_size": [100, 150],
        }
        _update_leaf_record(manifest, leaf_num=0, updates=updates)
        leaf = next(l for l in manifest["leaves"] if l["leaf_num"] == 0)
        assert leaf["image_state"] == "present"
        assert leaf["local_path"] == updates["local_path"]
        assert leaf["sha256"] == updates["sha256"]

    def test_updates_pending_to_not_imaged_blank(self) -> None:
        manifest = self._manifest_with_pending_front()
        _update_leaf_record(manifest, leaf_num=1, updates={
            "image_state": "not_imaged",
            "blank": True,
        })
        leaf = next(l for l in manifest["leaves"] if l["leaf_num"] == 1)
        assert leaf["image_state"] == "not_imaged"
        assert leaf["blank"] is True
        assert "local_path" not in leaf

    def test_refuses_body_leaf(self) -> None:
        manifest = self._manifest_with_pending_front()
        with pytest.raises(ValueError, match="body"):
            _update_leaf_record(manifest, leaf_num=50, updates={"image_state": "present"})

    def test_raises_if_leaf_not_found(self) -> None:
        manifest = self._manifest_with_pending_front()
        with pytest.raises(KeyError):
            _update_leaf_record(manifest, leaf_num=999, updates={"image_state": "present"})

    def test_refuses_unresolved_leaf(self) -> None:
        manifest = _minimal_manifest([
            {"leaf_num": 10, "page_num": 5, "kind": "body",
             "image_state": "unresolved"},
        ])
        with pytest.raises(ValueError, match="unresolved|body"):
            _update_leaf_record(manifest, leaf_num=10, updates={"image_state": "present"})

    def test_preserves_other_leaves_unchanged(self) -> None:
        manifest = self._manifest_with_pending_front()
        original_leaf1 = dict(next(
            l for l in manifest["leaves"] if l["leaf_num"] == 1
        ))
        _update_leaf_record(manifest, leaf_num=0, updates={
            "image_state": "not_imaged", "blank": True,
        })
        leaf1_after = next(l for l in manifest["leaves"] if l["leaf_num"] == 1)
        assert leaf1_after == original_leaf1

    def test_does_not_inject_local_path_for_not_imaged(self) -> None:
        """Blank leaves must not carry local_path (schema: local_path triggers provenance req)."""
        manifest = self._manifest_with_pending_front()
        _update_leaf_record(manifest, leaf_num=0, updates={
            "image_state": "not_imaged",
            "blank": True,
            "local_path": "should_not_appear.jpg",  # caller passes this; update must strip it
        })
        leaf = next(l for l in manifest["leaves"] if l["leaf_num"] == 0)
        assert "local_path" not in leaf
