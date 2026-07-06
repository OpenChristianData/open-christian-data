"""Ablate Surya layout authority against consensus word-box geometry."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.consensus_layout import LayoutResult, detect_columns  # noqa: E402
from build.lib.ocr_store_paths import S1_SIDECARS_ROOT  # noqa: E402
from build.lib.wct_builder import _cluster_body_columns  # noqa: E402

RAW_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages" / "vol_01"
TESSERACT_DIR = S1_SIDECARS_ROOT / "tesseract-py314-v1" / "vol_01" / "pages"
SURYA_DIR = S1_SIDECARS_ROOT / "surya-py312-v1" / "vol_01" / "pages"
REPORT_PATH = REPO_ROOT / "reports" / "measurement" / "vol_01" / "layout_ablation.json"

KNOWN_STRATA = {
    37: "footnote",
    82: "greek",
    90: "greek",
    136: "greek",
    137: "greek",
    241: "greek",
    256: "greek",
    381: "table",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _valid_box(box: object) -> bool:
    if not isinstance(box, dict):
        return False
    return all(key in box for key in ("x", "y", "w", "h"))


def _rect(box: dict) -> dict:
    return {
        "x": float(box["x"]),
        "y": float(box["y"]),
        "w": float(box["w"]),
        "h": float(box["h"]),
    }


def _word_boxes_from_blocks(blocks: Iterable[dict], bbox_key: str) -> list[dict]:
    boxes: list[dict] = []
    for block in blocks:
        for line in block.get("lines", []):
            for word in line.get("words", []):
                bbox = word.get(bbox_key)
                if _valid_box(bbox):
                    boxes.append(_rect(bbox))
    return boxes


def _load_azure(page: int) -> tuple[list[dict], tuple[int, int] | None]:
    path = RAW_DIR / f"page_{page:04d}.azure.json"
    if not path.exists():
        return [], None
    data = _load_json(path)
    if data.get("partial") is True:
        return [], None
    size = data.get("image_size")
    dims = (int(size[0]), int(size[1])) if isinstance(size, list) and len(size) == 2 else None
    return _word_boxes_from_blocks(data.get("blocks", []), "bbox"), dims


def _load_abbyy(page: int) -> tuple[list[dict], tuple[int, int] | None]:
    path = RAW_DIR / f"page_{page:04d}.ia-abbyy.json"
    if not path.exists():
        return [], None
    data = _load_json(path)
    size = data.get("page_size", {})
    dims = (
        int(size["width"]),
        int(size["height"]),
    ) if "width" in size and "height" in size else None
    return _word_boxes_from_blocks(data.get("blocks", []), "bbox"), dims


def _load_tesseract(page: int) -> tuple[list[dict], tuple[int, int] | None]:
    path = TESSERACT_DIR / f"page_{page:04d}.json"
    if not path.exists():
        return [], None
    data = _load_json(path)
    size = data.get("page_dimensions_native", {})
    dims = (
        int(size["width"]),
        int(size["height"]),
    ) if "width" in size and "height" in size else None
    return _word_boxes_from_blocks(data.get("blocks", []), "bbox_native"), dims


def _load_surya(page: int) -> tuple[list[dict], tuple[int, int]]:
    path = SURYA_DIR / f"page_{page:04d}.json"
    data = _load_json(path)
    size = data["page_dimensions_native"]
    dims = (int(size["width"]), int(size["height"]))
    rects = [
        _rect(block["bbox_native"])
        for block in data.get("blocks", [])
        if _valid_box(block.get("bbox_native"))
    ]
    return rects, dims


def _choose_dims(*dims: tuple[int, int] | None) -> tuple[int, int]:
    for item in dims:
        if item is not None:
            return item
    raise ValueError("no page dimensions available")


def _surya_columns(page: int) -> tuple[list[dict], tuple[int, int]]:
    rects, dims = _load_surya(page)
    columns = _cluster_body_columns(rects, float(dims[0]))
    columns = sorted(columns, key=lambda col: (float(col["assign_x"]), float(col["x"])))
    return columns, dims


def _surya_column_of(box: dict, columns: list[dict]) -> int:
    if len(columns) <= 1:
        return 0
    center_x = float(box["x"]) + float(box["w"]) / 2
    nearest_index = min(
        range(len(columns)),
        key=lambda index: (
            abs(center_x - float(columns[index]["assign_x"])),
            float(columns[index]["assign_x"]),
            index,
        ),
    )
    return 0 if nearest_index == 0 else 1


def _agreement(reference_boxes: list[dict], layout: LayoutResult, surya_columns: list[dict]) -> float:
    if not reference_boxes:
        return 0.0
    agree = 0
    for box in reference_boxes:
        if layout.column_of(box) == _surya_column_of(box, surya_columns):
            agree += 1
    return agree / len(reference_boxes)


def _stratum(page: int) -> str:
    return KNOWN_STRATA.get(page, "body")


def _classify(layout: LayoutResult, agreement: float) -> str:
    if layout.escalate:
        return "escalated"
    if agreement >= 0.98:
        return "agree"
    return "silent_wrong"


def _page_numbers_from_surya() -> list[int]:
    pages: list[int] = []
    for path in sorted(SURYA_DIR.glob("page_*.json")):
        stem = path.stem
        try:
            pages.append(int(stem.removeprefix("page_")))
        except ValueError:
            continue
    return pages


def _parse_pages(values: list[str] | None) -> list[int] | None:
    if not values:
        return None
    pages: list[int] = []
    for value in values:
        for part in value.split(","):
            stripped = part.strip()
            if stripped:
                pages.append(int(stripped))
    return sorted(set(pages))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _summaries(rows: list[dict]) -> tuple[dict, dict]:
    by_stratum: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_stratum[row["stratum"]].append(row)

    strata = {}
    for stratum in sorted(by_stratum):
        items = by_stratum[stratum]
        strata[stratum] = {
            "n": len(items),
            "escalated": sum(1 for item in items if item["classification"] == "escalated"),
            "agree": sum(1 for item in items if item["classification"] == "agree"),
            "silent_wrong": sum(1 for item in items if item["classification"] == "silent_wrong"),
            "mean_agreement": _mean([item["agreement"] for item in items]),
        }

    total = len(rows)
    escalated = sum(1 for row in rows if row["classification"] == "escalated")
    silent_wrong = sum(1 for row in rows if row["classification"] == "silent_wrong")
    overall = {
        "total_pages": total,
        "flagged_pages": escalated,
        "flagged_fraction": escalated / total if total else 0.0,
        "silent_wrong_count": silent_wrong,
        "silent_wrong_fraction": silent_wrong / total if total else 0.0,
        "mean_agreement": _mean([row["agreement"] for row in rows]),
    }
    return strata, overall


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    tmp.write_text(text + "\n", encoding="utf-8")
    os.replace(tmp, path)


def analyse_page(page: int) -> dict:
    azure_boxes, azure_dims = _load_azure(page)
    abbyy_boxes, abbyy_dims = _load_abbyy(page)
    tesseract_boxes, tesseract_dims = _load_tesseract(page)
    surya_columns, surya_dims = _surya_columns(page)
    page_width, page_height = _choose_dims(azure_dims, tesseract_dims, abbyy_dims, surya_dims)

    engine_boxes = {
        "azure": azure_boxes,
        "tesseract": tesseract_boxes,
        "abbyy": abbyy_boxes,
    }
    engine_boxes = {engine: boxes for engine, boxes in engine_boxes.items() if boxes}
    layout = detect_columns(engine_boxes, page_width, page_height)
    reference_boxes = tesseract_boxes if tesseract_boxes else azure_boxes
    agreement = _agreement(reference_boxes, layout, surya_columns)
    classification = _classify(layout, agreement)
    return {
        "page": page,
        "stratum": _stratum(page),
        "classification": classification,
        "agreement": agreement,
        "reference_word_count": len(reference_boxes),
        "provider_count": layout.provider_count,
        "consensus": {
            "n_columns": layout.n_columns,
            "gutter_x": layout.gutter_x,
            "separation": layout.separation,
            "per_engine_gutter": layout.per_engine_gutter,
            "flags": layout.flags,
            "escalate": layout.escalate,
        },
        "surya": {
            "n_columns": len(surya_columns),
            "assign_x": [column.get("assign_x") for column in surya_columns],
        },
    }


def _print_table(strata: dict, overall: dict) -> None:
    print("stratum n escalated agree silent_wrong mean_agreement")
    for stratum, row in strata.items():
        print(
            f"{stratum} {row['n']} {row['escalated']} {row['agree']} "
            f"{row['silent_wrong']} {row['mean_agreement']:.4f}"
        )
    total = overall["total_pages"]
    print(
        f"overall N={total} flagged={overall['flagged_pages']} "
        f"flagged_fraction={overall['flagged_fraction']:.4f} "
        f"silent_wrong={overall['silent_wrong_count']} "
        f"silent_wrong_fraction={overall['silent_wrong_fraction']:.4f} "
        f"mean_agreement={overall['mean_agreement']:.4f}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare consensus geometry column layout against Surya sidecars."
    )
    parser.add_argument(
        "--pages",
        nargs="*",
        default=None,
        help="Optional page numbers, space-separated or comma-separated. Defaults to all Surya vol_01 pages.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPORT_PATH,
        help="JSON report path. Defaults to reports/measurement/vol_01/layout_ablation.json.",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    pages = _parse_pages(args.pages) or _page_numbers_from_surya()
    rows = [analyse_page(page) for page in pages if (SURYA_DIR / f"page_{page:04d}.json").exists()]
    strata, overall = _summaries(rows)
    report = {
        "generated_at": _utc_now(),
        "volume_id": "vol_01",
        "reference": "Surya sidecar body-column clustering proxy; silent_wrong is agreement < 0.98 without escalation",
        "pages_requested": pages,
        "pages_measured": len(rows),
        "strata": strata,
        "overall": overall,
        "pages": rows,
    }
    _write_json_atomic(args.output, report)
    _print_table(strata, overall)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
