from pathlib import Path

import pytest
from PIL import Image


def test_derive_scan_jpegs_writes_lossless_webp(tmp_path: Path):
    from build.tools.derive_scan_jpegs import derive_page

    src = tmp_path / "p001.jp2"
    dst = tmp_path / "p001.webp"
    source_pixels = [(255, 255, 255)] * 16
    Image.new("RGB", (4, 4), (255, 255, 255)).save(src, format="JPEG2000", quality_mode="lossless")

    derive_page(src, dst)

    assert dst.exists()
    with Image.open(dst) as img:
        assert img.mode == "RGB"
        assert list(img.getdata()) == source_pixels

    with pytest.raises(FileNotFoundError):
        derive_page(Path("nonexistent.jp2"), dst)
