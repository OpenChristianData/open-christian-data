"""Create browser-friendly scan derivatives for the review UI."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def derive_page(src: Path, dst: Path) -> Path:
    """Convert one source scan page to a lossless WebP derivative."""
    src = Path(src)
    dst = Path(dst)
    if not src.exists():
        raise FileNotFoundError(src)

    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as image:
        image.convert("RGB").save(dst, format="WEBP", lossless=True)
    return dst
