from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

from PIL import Image


def emit_crop(page_image_path: Path, bbox: dict, out_path: Path) -> None:
    if out_path.exists():
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(page_image_path) as image:
        width, height = image.size
        left = bbox["x"]
        top = bbox["y"]
        right = left + bbox["w"]
        bottom = top + bbox["h"]
        if left < 0 or top < 0 or right > width or bottom > height:
            raise ValueError(
                f"bbox outside image bounds: bbox={bbox!r} image_size={(width, height)!r}"
            )

        tmp_path = out_path.with_name(f".{out_path.name}.{uuid4().hex}.tmp")
        try:
            crop = image.crop((left, top, right, bottom))
            crop.save(tmp_path, format="PNG")
            os.replace(tmp_path, out_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()  # standards: log/temp rotation


def emit_crops_for_worksheet(
    records: list[dict],
    page_image_path: Path,
    out_root: Path,
) -> dict:
    summary = {"emitted": 0, "skipped": 0, "failed": 0}
    total = len(records)

    for index, record in enumerate(records, start=1):
        if total > 100 and (index == 1 or index % 100 == 0 or index == total):
            print(f"nsh gold crops: {index}/{total}", file=sys.stderr)

        out_path = out_root / record["crop_ref"]
        existed = out_path.exists()
        try:
            emit_crop(page_image_path, record["bbox"], out_path)
        except Exception as exc:
            summary["failed"] += 1
            print(f"failed crop {record.get('crop_ref')}: {exc}", file=sys.stderr)
            continue

        if existed:
            summary["skipped"] += 1
        else:
            summary["emitted"] += 1

    return summary
