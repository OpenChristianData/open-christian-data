"""Run Kraken OCR (Greek specialist) for one page image and emit one JSON result line.

Uses the Ciaconna / Pogretra model family for polytonic Greek + Latin historical
scholarly print. Model discovery prefers filenames containing Greek-specialist
keywords (ciaconna, greek, grc, pogretra, polytonic, ancient).

Called by s1_kraken_greek_runner.py as a subprocess inside the kraken-py312 venv.
Output format is identical to kraken_page.py so the same S1 normalisation
path applies downstream.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _emit(payload: dict[str, Any]) -> None:
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
        "engine_variant": "greek",
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


# Greek-specialist model discovery keywords, in priority order.
_GREEK_PREFER_KW = ("ciaconna", "greek", "grc", "pogretra", "polytonic", "ancient")
# Fallback to general historical models if no Greek-specialist model is present.
_LATIN_FALLBACK_KW = ("catmus", "hist", "latin", "print", "gt4", "mediev", "1900", "early")


def _find_best_model() -> str | None:
    """Return the best available Kraken model path, preferring Greek-specialist weights.

    Search order:
    1. ~/ocr-engines/kraken-models/ -- prefer Greek keywords; fall back to Latin.
    2. htrmopo registry via `kraken list` (optional fallback; may fail on Windows).
    """
    import os

    local_dir = Path(os.path.expanduser("~")) / "ocr-engines" / "kraken-models"
    if local_dir.is_dir():
        all_models = sorted(local_dir.glob("*.mlmodel")) + sorted(local_dir.glob("*.safetensors"))
        # 1a. Greek-specialist first
        for model_path in all_models:
            lower = model_path.stem.lower()
            if any(kw in lower for kw in _GREEK_PREFER_KW):
                return str(model_path)
        # 1b. Latin historical fallback (better than nothing for Latin-dense pages)
        for model_path in all_models:
            lower = model_path.stem.lower()
            if any(kw in lower for kw in _LATIN_FALLBACK_KW):
                return str(model_path)
        if all_models:
            return str(all_models[0])

    # 2. htrmopo registry fallback
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
            if any(kw in lower for kw in _GREEK_PREFER_KW):
                return model_id
            models_found.append(model_id)
        # No Greek-specialist found in registry; fall back to first available
        return models_found[0] if models_found else None
    except Exception:
        return None


def _polygon_from_record(record: Any) -> list[list[float]] | None:
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
    pred = getattr(record, "prediction", None)
    if isinstance(pred, str):
        text = pred.strip()
        if text:
            confs = getattr(record, "confidences", None)
            conf: float | None = None
            if isinstance(confs, list) and confs:
                conf = sum(confs) / len(confs)
            return text, conf
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
        raw_confs = getattr(record, "confidences", None)
        if isinstance(raw_confs, list) and raw_confs:
            # Use kraken_greek_ prefix to distinguish from standard kraken lane
            char_confs[line_id] = [float(c) for c in raw_confs]
        poly = _polygon_from_record(record)
        if poly is not None:
            line_polys[line_id] = poly
    if _side_channel is not None:
        if char_confs:
            _side_channel["kraken_greek_char_confidences"] = char_confs
        if line_polys:
            _side_channel["kraken_greek_line_polygons"] = line_polys
    return blocks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--model", type=str, default="", help="Kraken model id or path (auto-discovered if empty)")
    parser.add_argument(
        "--raw-output",
        type=Path,
        default=None,
        help="Optional path for the raw Kraken Greek segmentation/recognition JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        import kraken
        from kraken import blla, rpred
        from kraken.lib import models
        from PIL import Image
    except Exception as exc:
        _emit(_failure("kraken_import_error", exc))
        return 1

    model_id = args.model.strip() or _find_best_model()
    if not model_id:
        _emit(_failure("kraken_no_model", ValueError(
            "No Kraken Greek-specialist model found. "
            "Download the Ciaconna model: see plans/2026-05-31-ocr-research-integration-A.md Task 1."
        )))
        return 1

    try:
        nn = models.load_any(model_id)
    except Exception as exc:
        _emit(_failure("kraken_model_load_error", exc))
        return 1

    try:
        with Image.open(args.image) as raw:
            im = raw.convert("RGB")
            width, height = im.size
        seg = blla.segment(im)
        records = list(rpred.rpred(nn, im, seg))
    except OSError as exc:
        _emit(_failure("image_open_error", exc))
        return 1
    except Exception as exc:
        _emit(_failure("kraken_runtime_error", exc))
        return 0

    engine_version = str(getattr(kraken, "__version__", "unknown"))
    if args.raw_output is not None:
        try:
            _write_raw_result(
                args.raw_output,
                image_path=args.image,
                model_id=model_id,
                engine_version=engine_version,
                page_width=width,
                page_height=height,
                segmentation=seg,
                records=records,
            )
        except OSError as exc:
            _emit(_failure("raw_artifact_write_error", exc))
            return 1

    side_channel: dict[str, Any] = {}
    blocks = _blocks_from_records(records, _side_channel=side_channel)
    payload: dict[str, Any] = {
        "ok": True,
        "engine_version": engine_version,
        "model_id": model_id,
        "page_width": width,
        "page_height": height,
        "blocks": blocks,
    }
    payload.update(side_channel)
    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
