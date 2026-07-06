"""Tests for surya_page.py internal helper functions.

These test the pure-Python helpers (no Surya install required) that are
added for the three throughput changes:
  1. Resolution cap + bbox scaling back to native coords.
  2. Batch output parsing.
  3. Env-var constant names verified against surya-ocr 0.17.1.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from build.tools.ocr_runners import surya_page  # noqa: E402


# ---------------------------------------------------------------------------
# PIL available?
# ---------------------------------------------------------------------------

try:
    from PIL import Image as PILImage

    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

_skip_no_pil = pytest.mark.skipif(not _PIL_AVAILABLE, reason="PIL not installed")


def _make_image(width: int, height: int):
    """Return a minimal PIL RGBA image for testing."""
    img = PILImage.new("RGB", (width, height), color=(128, 128, 128))
    return img


# ---------------------------------------------------------------------------
# Change 1: _maybe_downscale
# ---------------------------------------------------------------------------


@_skip_no_pil
def test_maybe_downscale_no_cap_returns_same_object_and_unit_scale() -> None:
    """max_width=None → same image, scale_to_native=1.0."""
    img = _make_image(5000, 7000)
    out_img, scale = surya_page._maybe_downscale(img, max_width=None)
    assert out_img is img
    assert scale == 1.0


@_skip_no_pil
def test_maybe_downscale_narrow_image_unchanged() -> None:
    """Image already fits within cap → unchanged."""
    img = _make_image(1000, 1400)
    out_img, scale = surya_page._maybe_downscale(img, max_width=2000)
    assert out_img is img
    assert scale == 1.0


@_skip_no_pil
def test_maybe_downscale_wide_image_resized_and_scale_above_one() -> None:
    """Image wider than cap → resized, scale_to_native > 1."""
    img = _make_image(4000, 6000)
    out_img, scale = surya_page._maybe_downscale(img, max_width=2000)
    assert out_img is not img
    assert out_img.size[0] == 2000
    # Height preserves aspect ratio: 6000 * (2000/4000) = 3000
    assert out_img.size[1] == 3000
    # scale_to_native must undo the downscale: 4000/2000 = 2.0
    assert abs(scale - 2.0) < 1e-9


@_skip_no_pil
def test_maybe_downscale_native_coords_recovered() -> None:
    """A bbox at inference-res multiplied by scale_to_native gives native coords."""
    img = _make_image(4000, 6000)
    out_img, scale = surya_page._maybe_downscale(img, max_width=2000)
    # Inference bbox (in 2000px space): x=100, y=200
    # After scaling back: x=200, y=400 (because scale=2.0)
    assert abs(100 * scale - 200.0) < 1e-6
    assert abs(200 * scale - 400.0) < 1e-6


# ---------------------------------------------------------------------------
# Change 1: _scale_blocks
# ---------------------------------------------------------------------------


def test_scale_blocks_identity_when_factor_is_one() -> None:
    """factor=1.0 → returned list is unchanged."""
    blocks = [
        {
            "block_id": "b-0001",
            "block_type": "text",
            "bbox_native": {"x": 10.0, "y": 20.0, "w": 50.0, "h": 15.0},
            "lines": [],
        }
    ]
    result = surya_page._scale_blocks(blocks, 1.0)
    assert result is blocks


def test_scale_blocks_scales_block_bbox() -> None:
    """Block bbox multiplied by factor."""
    blocks = [
        {
            "block_id": "b-0001",
            "block_type": "text",
            "bbox_native": {"x": 10.0, "y": 20.0, "w": 50.0, "h": 15.0},
            "lines": [],
        }
    ]
    result = surya_page._scale_blocks(blocks, 2.0)
    bb = result[0]["bbox_native"]
    assert bb == {"x": 20.0, "y": 40.0, "w": 100.0, "h": 30.0}


def test_scale_blocks_scales_line_and_word_bboxes() -> None:
    """All nested bbox_native dicts are scaled."""
    blocks = [
        {
            "block_id": "b-0001",
            "block_type": "text",
            "bbox_native": {"x": 0.0, "y": 0.0, "w": 100.0, "h": 20.0},
            "lines": [
                {
                    "line_id": "l-0001-0001",
                    "source_raw": "hello",
                    "confidence": 0.9,
                    "bbox_native": {"x": 5.0, "y": 5.0, "w": 90.0, "h": 10.0},
                    "words": [
                        {
                            "word_id": "w-0001-0001-0001",
                            "source_raw": "hello",
                            "confidence": 0.9,
                            "bbox_native": {"x": 5.0, "y": 5.0, "w": 40.0, "h": 10.0},
                        }
                    ],
                }
            ],
        }
    ]
    result = surya_page._scale_blocks(blocks, 2.5)
    line_bb = result[0]["lines"][0]["bbox_native"]
    word_bb = result[0]["lines"][0]["words"][0]["bbox_native"]
    assert abs(line_bb["x"] - 12.5) < 1e-9
    assert abs(line_bb["w"] - 225.0) < 1e-9
    assert abs(word_bb["x"] - 12.5) < 1e-9
    assert abs(word_bb["w"] - 100.0) < 1e-9


def test_scale_blocks_none_bboxes_pass_through() -> None:
    """None bbox_native values are left as None (not crashed)."""
    blocks = [
        {
            "block_id": "b-0001",
            "block_type": "text",
            "bbox_native": None,
            "lines": [
                {
                    "line_id": "l-0001-0001",
                    "source_raw": "x",
                    "confidence": None,
                    "bbox_native": None,
                    "words": [],
                }
            ],
        }
    ]
    result = surya_page._scale_blocks(blocks, 3.0)
    assert result[0]["bbox_native"] is None
    assert result[0]["lines"][0]["bbox_native"] is None


# ---------------------------------------------------------------------------
# Change 3: env-var constant names (verified against surya-ocr 0.17.1)
# ---------------------------------------------------------------------------


def test_surya_env_recognition_batch_size_constant_name() -> None:
    """RECOGNITION_BATCH_SIZE is the setting name in surya 0.17.1 settings.py."""
    assert surya_page.SURYA_ENV_RECOGNITION_BATCH_SIZE == "RECOGNITION_BATCH_SIZE"


def test_surya_env_detector_batch_size_constant_name() -> None:
    """DETECTOR_BATCH_SIZE is the setting name in surya 0.17.1 settings.py."""
    assert surya_page.SURYA_ENV_DETECTOR_BATCH_SIZE == "DETECTOR_BATCH_SIZE"


def test_surya_env_foundation_chunk_size_constant_name() -> None:
    """FOUNDATION_CHUNK_SIZE is the setting name in surya 0.17.1 settings.py."""
    assert surya_page.SURYA_ENV_FOUNDATION_CHUNK_SIZE == "FOUNDATION_CHUNK_SIZE"
