"""Run Kraken OCR for one page image and emit one JSON result line.

Discovers installed models automatically (prefers Latin historical models).
Pass --model to override; the chosen model id is included in the JSON output.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _emit(payload: dict[str, Any]) -> None:
    # Write to stdout.buffer (bytes) with UTF-8 encoding to avoid cp1252
    # codec errors when OCR text contains combining or non-Latin characters.
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.buffer.write(line.encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def _failure(failure_class: str, exc: BaseException) -> dict[str, Any]:
    return {
        "ok": False,
        "failure_class": failure_class,
        "error": f"{type(exc).__name__}: {str(exc)[:200]}",
    }


def _json_safe(value: Any, depth: int = 0) -> Any:
    """Best-effort conversion of Kraken result objects into JSON-safe data."""
    if depth > 8:
        return repr(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, depth + 1) for item in value]
    attrs = getattr(value, "__dict__", None)
    if isinstance(attrs, dict):
        return {
            str(k): _json_safe(v, depth + 1)
            for k, v in attrs.items()
            if not str(k).startswith("_")
        }
    return repr(value)


def _write_raw_result(
    raw_output: Path,
    *,
    image_path: Path,
    model_id: str,
    engine_version: str,
    page_width: int,
    page_height: int,
    segmentation: Any,
    records: list[Any],
) -> None:
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "engine_family": "kraken",
        "engine_version": engine_version,
        "model_id": model_id,
        "image_path": str(image_path),
        "page_width": page_width,
        "page_height": page_height,
        "segmentation": _json_safe(segmentation),
        "records": _json_safe(records),
    }
    with raw_output.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)


def _find_best_model() -> str | None:
    """Return the best available Kraken model path for historical Latin print.

    Search order:
    1. ~/ocr-engines/kraken-models/ -- locally downloaded .mlmodel files.
       Prefer names matching hist/catmus/latin/print keywords.
    2. htrmopo registry via `kraken list` (may fail on Windows due to cp1252
       encoding in htrmopo; treated as optional fallback).
    """
    import os

    # --- 1. Local model directory (primary) ---
    local_dir = Path(os.path.expanduser("~")) / "ocr-engines" / "kraken-models"
    if local_dir.is_dir():
        prefer_kw = ("catmus", "hist", "latin", "print", "gt4", "mediev", "1900", "early")
        all_models = sorted(local_dir.glob("*.mlmodel")) + sorted(local_dir.glob("*.safetensors"))
        # Prefer keyword-matching models
        for model_path in all_models:
            lower = model_path.stem.lower()
            if any(kw in lower for kw in prefer_kw):
                return str(model_path)
        # Fall back to first available local model
        if all_models:
            return str(all_models[0])

    # --- 2. htrmopo registry (fallback; may fail on Windows/cp1252) ---
    try:
        result = subprocess.run(
            [sys.executable, "-m", "kraken", "list"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        models_found: list[str] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("[") or "No models" in line:
                continue
            model_id = line.split()[0] if line.split() else ""
            if not model_id:
                continue
            lower = model_id.lower()
            if any(kw in lower for kw in ("hist", "gt4", "latin", "mediev", "print", "1900", "early")):
                return model_id
            models_found.append(model_id)
        return models_found[0] if models_found else None
    except Exception:
        return None


def _polygon_from_record(record: Any) -> list[list[float]] | None:
    """Extract the line boundary polygon from a Kraken segmentation record."""
    line_obj = getattr(record, "line", None)
    if line_obj is None:
        return None
    for attr in ("boundary", "polygon", "envelope"):
        val = getattr(line_obj, attr, None)
        if val is None:
            continue
        try:
            pts = [[float(x), float(y)] for x, y in val]
            if len(pts) >= 3:
                return pts
        except (TypeError, ValueError):
            pass
    return None


def _bbox_from_record(record: Any) -> dict[str, float] | None:
    """Extract bbox from a kraken record across API versions."""
    for obj in (getattr(record, "line", None), getattr(record, "baseline", None), record):
        if obj is None:
            continue
        for attr in ("bbox", "bounding_box", "boundingBox"):
            val = getattr(obj, attr, None)
            if val is None:
                continue
            try:
                coords = list(val)
                if len(coords) >= 4:
                    x0, y0, x1, y1 = float(coords[0]), float(coords[1]), float(coords[2]), float(coords[3])
                    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
            except (TypeError, ValueError):
                pass
    return None


def _text_conf_from_record(record: Any) -> tuple[str, float | None]:
    """Extract text and mean confidence from a kraken record across API versions.

    Kraken 7.x: record.prediction is the text string directly; confidences is
    a list of per-character probabilities on record itself.
    Legacy API: prediction is an object with .text/.sentence attributes.
    """
    # Kraken 7.x -- prediction is the text string directly
    pred = getattr(record, "prediction", None)
    if isinstance(pred, str):
        text = pred.strip()
        if text:
            confs = getattr(record, "confidences", None)
            conf: float | None = None
            if isinstance(confs, list) and confs:
                conf = sum(confs) / len(confs)
            return text, conf

    # Legacy API fallback -- prediction is an object
    for obj in (pred, record):
        if obj is None:
            continue
        for text_attr in ("text", "sentence"):
            text = getattr(obj, text_attr, None)
            if text is not None:
                text = str(text).strip()
                if not text:
                    continue
                legacy_confs = getattr(obj, "confidences", None) or getattr(obj, "avg_char_probability", None)
                legacy_conf: float | None = None
                if isinstance(legacy_confs, list) and legacy_confs:
                    legacy_conf = sum(legacy_confs) / len(legacy_confs)
                elif isinstance(legacy_confs, (int, float)):
                    legacy_conf = float(legacy_confs)
                return text, legacy_conf
    return "", None


def _blocks_from_records(
    records: list[Any],
    _side_channel: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    char_confs: dict[str, list[float]] = {}
    line_polys: dict[str, list[list[float]]] = {}
    for block_index, record in enumerate(records, start=1):
        text, confidence = _text_conf_from_record(record)
        if not text:
            continue
        bbox = _bbox_from_record(record)
        words = [
            {
                "word_id": f"w-{block_index:04d}-0001-{wi:04d}",
                "source_raw": word,
                "confidence": confidence,
                "bbox_native": None,
            }
            for wi, word in enumerate(text.split(), start=1)
            if word
        ]
        if not words:
            continue
        line_id = f"l-{block_index:04d}-0001"
        blocks.append(
            {
                "block_id": f"b-{block_index:04d}",
                "block_type": "text",
                "bbox_native": bbox,
                "lines": [
                    {
                        "line_id": line_id,
                        "source_raw": text,
                        "confidence": confidence,
                        "bbox_native": bbox,
                        "words": words,
                    }
                ],
            }
        )
        # Side-channel: preserve per-character confidence list (averaged to mean above)
        raw_confs = getattr(record, "confidences", None)
        if isinstance(raw_confs, list) and raw_confs:
            char_confs[line_id] = [float(c) for c in raw_confs]
        # Side-channel: line boundary polygon from segmenter
        poly = _polygon_from_record(record)
        if poly is not None:
            line_polys[line_id] = poly
    if _side_channel is not None:
        if char_confs:
            _side_channel["kraken_char_confidences"] = char_confs
        if line_polys:
            _side_channel["kraken_line_polygons"] = line_polys
    return blocks


def _downscale_image(im: Any, max_width: int) -> tuple[Any, float]:
    """Return (possibly resized image, coord_scale).

    coord_scale > 1.0 means divide model-space coords by coord_scale to get
    native coords; or multiply native coords by coord_scale to get model space.
    Here we return 1/scale so callers multiply model coords to get native.
    """
    from PIL import Image
    w, h = im.size
    if max_width <= 0 or w <= max_width:
        return im, 1.0
    scale = max_width / w
    new_w = max_width
    new_h = int(h * scale)
    return im.resize((new_w, new_h), Image.LANCZOS), 1.0 / scale


def _scale_bbox(bbox: dict[str, float] | None, factor: float) -> dict[str, float] | None:
    if bbox is None or factor == 1.0:
        return bbox
    return {
        "x": bbox["x"] * factor,
        "y": bbox["y"] * factor,
        "w": bbox["w"] * factor,
        "h": bbox["h"] * factor,
    }


def _scale_polygon(poly: list[list[float]] | None, factor: float) -> list[list[float]] | None:
    if poly is None or factor == 1.0:
        return poly
    return [[x * factor, y * factor] for x, y in poly]


def _run_one_image(
    *,
    image_path: Path,
    nn: Any,
    kraken_mod: Any,
    blla_mod: Any,
    rpred_mod: Any,
    max_width: int,
    raw_output: Path | None,
    model_id: str,
) -> dict[str, Any]:
    """Process one image. Returns the payload dict (ok=True or ok=False)."""
    from PIL import Image

    try:
        with Image.open(image_path) as raw:
            im = raw.convert("RGB")
            native_w, native_h = im.size
    except OSError as exc:
        return _failure("image_open_error", exc)
    except Exception as exc:
        return _failure("kraken_runtime_error", exc)

    im_proc, coord_scale = _downscale_image(im, max_width)

    try:
        seg = blla_mod.segment(im_proc)
        records = list(rpred_mod.rpred(nn, im_proc, seg))
    except Exception as exc:
        return _failure("kraken_runtime_error", exc)

    engine_version = str(getattr(kraken_mod, "__version__", "unknown"))

    if raw_output is not None:
        try:
            _write_raw_result(
                raw_output,
                image_path=image_path,
                model_id=model_id,
                engine_version=engine_version,
                page_width=native_w,
                page_height=native_h,
                segmentation=seg,
                records=records,
            )
        except OSError as exc:
            return _failure("raw_artifact_write_error", exc)

    side_channel: dict[str, Any] = {}
    blocks = _blocks_from_records(records, _side_channel=side_channel)

    # Scale coordinates back to native space when image was downscaled.
    if coord_scale != 1.0:
        for block in blocks:
            block["bbox_native"] = _scale_bbox(block.get("bbox_native"), coord_scale)
            for line in block.get("lines", []):
                line["bbox_native"] = _scale_bbox(line.get("bbox_native"), coord_scale)
                for word in line.get("words", []):
                    word["bbox_native"] = _scale_bbox(word.get("bbox_native"), coord_scale)
        if "kraken_line_polygons" in side_channel:
            side_channel["kraken_line_polygons"] = {
                lid: _scale_polygon(poly, coord_scale)
                for lid, poly in side_channel["kraken_line_polygons"].items()
            }

    payload: dict[str, Any] = {
        "ok": True,
        "engine_version": engine_version,
        "model_id": model_id,
        "page_width": native_w,
        "page_height": native_h,
        "blocks": blocks,
    }
    payload.update(side_channel)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, default=None)
    parser.add_argument("--model", type=str, default="", help="Kraken model id or path (auto-discovered if empty)")
    parser.add_argument(
        "--raw-output",
        type=Path,
        default=None,
        help="Optional path for the raw Kraken segmentation/recognition JSON.",
    )
    parser.add_argument(
        "--max-width",
        type=int,
        default=0,
        dest="max_width",
        metavar="PX",
        help=(
            "Downscale images wider than PX before inference; bboxes are scaled back "
            "to native coordinates. 0 = no limit (default). 1800 is recommended for "
            "NSH scans (5034px wide) -- halves recognition time with negligible quality loss."
        ),
    )
    parser.add_argument(
        "--batch-manifest-file",
        type=Path,
        default=None,
        dest="batch_manifest_file",
        metavar="PATH",
        help=(
            "JSON file listing [{image, raw_output}] entries. When provided, the model "
            "is loaded once and all images are processed sequentially; one result line "
            "is emitted per entry. Overrides --image."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        import kraken
        from kraken import blla, rpred
        from kraken.lib import models
    except Exception as exc:
        _emit(_failure("kraken_import_error", exc))
        return 1

    model_id = args.model.strip() or _find_best_model()
    if not model_id:
        _emit(_failure("kraken_no_model", ValueError(
            "No kraken model found. Run 'python -m kraken list' to see installed models. "
            "Download a historical Latin model with 'python -m kraken get <model-id>'."
        )))
        return 1

    try:
        nn = models.load_any(model_id)
    except Exception as exc:
        _emit(_failure("kraken_model_load_error", exc))
        return 1

    if args.batch_manifest_file is not None:
        # Batch mode: process all entries with model loaded once.
        try:
            manifest = json.loads(args.batch_manifest_file.read_text(encoding="utf-8"))
        except Exception as exc:
            _emit(_failure("batch_manifest_read_error", exc))
            return 1
        for entry in manifest:
            img_path = Path(entry["image"])
            raw_out = Path(entry["raw_output"]) if entry.get("raw_output") else None
            payload = _run_one_image(
                image_path=img_path,
                nn=nn,
                kraken_mod=kraken,
                blla_mod=blla,
                rpred_mod=rpred,
                max_width=args.max_width,
                raw_output=raw_out,
                model_id=model_id,
            )
            _emit(payload)
        return 0

    # Single-image mode.
    if args.image is None:
        _emit(_failure("missing_argument", ValueError("--image or --batch-manifest-file required")))
        return 1

    payload = _run_one_image(
        image_path=args.image,
        nn=nn,
        kraken_mod=kraken,
        blla_mod=blla,
        rpred_mod=rpred,
        max_width=args.max_width,
        raw_output=args.raw_output,
        model_id=model_id,
    )
    _emit(payload)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
