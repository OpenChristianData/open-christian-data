from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from build.tools.ocr_pipeline.nsh_gold_crops import (
    emit_crop,
    emit_crops_for_worksheet,
)


def test_emit_crop_writes_png_and_skips_existing_output(tmp_path: Path) -> None:
    page_path = tmp_path / "page.jpg"
    out_path = tmp_path / "crops" / "word.png"
    Image.new("RGB", (20, 12), "white").save(page_path)

    emit_crop(page_path, {"x": 2, "y": 3, "w": 7, "h": 5}, out_path)

    assert out_path.exists()
    with Image.open(out_path) as crop:
        assert crop.size == (7, 5)

    old_mtime = 1_700_000_000
    os.utime(out_path, (old_mtime, old_mtime))
    emit_crop(page_path, {"x": 2, "y": 3, "w": 7, "h": 5}, out_path)

    assert int(out_path.stat().st_mtime) == old_mtime


def test_emit_crop_rejects_out_of_bounds_bbox(tmp_path: Path) -> None:
    page_path = tmp_path / "page.jpg"
    Image.new("RGB", (20, 12), "white").save(page_path)

    with pytest.raises(ValueError, match="outside image bounds"):
        emit_crop(page_path, {"x": 15, "y": 3, "w": 7, "h": 5}, tmp_path / "bad.png")


def test_emit_crops_for_worksheet_continues_after_per_record_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    page_path = tmp_path / "page.jpg"
    out_root = tmp_path / "out"
    Image.new("RGB", (20, 12), "white").save(page_path)
    records = [
        {"bbox": {"x": 1, "y": 1, "w": 4, "h": 3}, "crop_ref": "crops/a.png"},
        {"bbox": {"x": 18, "y": 1, "w": 4, "h": 3}, "crop_ref": "crops/b.png"},
    ]

    summary = emit_crops_for_worksheet(records, page_path, out_root)

    assert summary == {"emitted": 1, "skipped": 0, "failed": 1}
    assert (out_root / "crops" / "a.png").exists()
    assert not (out_root / "crops" / "b.png").exists()
    assert "crops/b.png" in capsys.readouterr().err
