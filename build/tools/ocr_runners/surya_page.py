"""Run Surya OCR on one or more page images; emit one JSON result line per image."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config (PY-03) -- verified against surya-ocr 0.17.1 (surya/settings.py).
# Surya's pydantic Settings class reads these names from the process
# environment before model initialization; set them in the caller's env.
# CPU defaults (0.17.1 dynamic): RECOGNITION_BATCH_SIZE=32, DETECTOR_BATCH_SIZE=8.
# (The older comment citing 8/2 was inaccurate; these are the get_batch_size()
# return values measured on a no-GPU machine running 0.17.1 in June 2026.)
# Reducing to 8/2 slows inference by ~36% on CPU; the higher defaults are optimal.
# ---------------------------------------------------------------------------

SURYA_ENV_RECOGNITION_BATCH_SIZE = "RECOGNITION_BATCH_SIZE"
SURYA_ENV_DETECTOR_BATCH_SIZE = "DETECTOR_BATCH_SIZE"
SURYA_ENV_FOUNDATION_CHUNK_SIZE = "FOUNDATION_CHUNK_SIZE"

# Optional resolution cap: images wider than this are downscaled before
# inference and bboxes are scaled back to original native-pixel coordinates
# afterwards.  None = no cap (current behavior).  ~2000 is a practical
# starting point for no-GPU machines.
#
# NOTE: steady-state seconds/page to be measured on an idle machine across
# ~3 consecutive pages (model load paid once).
MAX_WIDTH_PX: int | None = None


# ---------------------------------------------------------------------------
# Helpers shared by single-image and batch paths
# ---------------------------------------------------------------------------


def _emit(payload: dict[str, Any]) -> None:
    # Write to stdout.buffer (bytes) with UTF-8 to avoid cp1252 codec errors
    # when OCR text contains non-Latin characters.
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.buffer.write(line.encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def _failure(exc: BaseException) -> dict[str, Any]:
    return {
        "ok": False,
        "failure_class": "surya_runtime_error",
        "error": f"{type(exc).__name__}: {str(exc)[:200]}",
    }


def _bbox(value: Any) -> dict[str, float] | None:
    if value is None:
        return None
    try:
        x0, y0, x1, y1 = value
    except (TypeError, ValueError):
        return None
    return {"x": float(x0), "y": float(y0), "w": float(x1) - float(x0), "h": float(y1) - float(y0)}


def _confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_safe(value: Any, depth: int = 0) -> Any:
    """Best-effort conversion of Surya result objects into JSON-safe data."""
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
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _json_safe(model_dump(mode="json"), depth + 1)
        except (TypeError, ValueError):
            return _json_safe(model_dump(), depth + 1)
    dict_method = getattr(value, "dict", None)
    if callable(dict_method):
        try:
            return _json_safe(dict_method(), depth + 1)
        except (TypeError, ValueError):
            pass
    attrs = getattr(value, "__dict__", None)
    if isinstance(attrs, dict):
        return {
            str(k): _json_safe(v, depth + 1)
            for k, v in attrs.items()
            if not str(k).startswith("_")
        }
    return repr(value)


def _write_raw_prediction(
    raw_output: Path,
    *,
    image_path: Path,
    prediction: Any,
    api_used: str,
    engine_version: str,
    orig_w: int,
    orig_h: int,
    scale_to_native: float,
) -> None:
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "engine_family": "surya",
        "engine_version": engine_version,
        "api_used": api_used,
        "image_path": str(image_path),
        "page_width": orig_w,
        "page_height": orig_h,
        "scale_to_native": scale_to_native,
        "prediction": _json_safe(prediction),
    }
    with raw_output.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)


def _maybe_downscale(image: Any, max_width: int | None) -> tuple[Any, float]:
    """Return (inference_image, scale_to_native).

    scale_to_native multiplies inference-space coordinates to get back to
    original native-pixel coordinates.  Returns (image, 1.0) when no
    downscale is needed (max_width=None or image fits within cap).
    """
    if max_width is None:
        return image, 1.0
    w, h = image.size
    if w <= max_width:
        return image, 1.0
    scale_to_inference = max_width / w
    new_h = round(h * scale_to_inference)
    return image.resize((max_width, new_h)), 1.0 / scale_to_inference


def _scale_bbox_dict(
    bbox: dict[str, float] | None, factor: float
) -> dict[str, float] | None:
    if bbox is None or factor == 1.0:
        return bbox
    return {
        "x": bbox["x"] * factor,
        "y": bbox["y"] * factor,
        "w": bbox["w"] * factor,
        "h": bbox["h"] * factor,
    }


def _scale_blocks(
    blocks: list[dict[str, Any]], factor: float
) -> list[dict[str, Any]]:
    """Return a new blocks list with all bbox_native coords multiplied by factor."""
    if factor == 1.0:
        return blocks
    scaled = []
    for block in blocks:
        new_block = dict(block)
        new_block["bbox_native"] = _scale_bbox_dict(block.get("bbox_native"), factor)
        new_lines = []
        for line in block.get("lines", []):
            new_line = dict(line)
            new_line["bbox_native"] = _scale_bbox_dict(line.get("bbox_native"), factor)
            new_words = []
            for word in line.get("words", []):
                new_word = dict(word)
                new_word["bbox_native"] = _scale_bbox_dict(word.get("bbox_native"), factor)
                new_words.append(new_word)
            new_line["words"] = new_words
            new_lines.append(new_line)
        new_block["lines"] = new_lines
        scaled.append(new_block)
    return scaled


def _line_words(line: Any, block_index: int, line_index: int) -> list[dict[str, Any]]:
    raw_words = getattr(line, "words", None) or []
    words = []
    for word_index, word in enumerate(raw_words, start=1):
        words.append(
            {
                "word_id": f"w-{block_index:04d}-{line_index:04d}-{word_index:04d}",
                "source_raw": str(getattr(word, "text", "")).strip(),
                "confidence": _confidence(getattr(word, "confidence", None)),
                "bbox_native": _bbox(getattr(word, "bbox", None)),
            }
        )
    words = [word for word in words if word["source_raw"]]
    if words:
        return words

    text = str(getattr(line, "text", "")).strip()
    line_confidence = _confidence(getattr(line, "confidence", None))
    return [
        {
            "word_id": f"w-{block_index:04d}-{line_index:04d}-{word_index:04d}",
            "source_raw": word,
            "confidence": line_confidence,
            "bbox_native": None,
        }
        for word_index, word in enumerate(text.split(), start=1)
    ]


def _text_lines(prediction: Any) -> list[Any]:
    for attr in ("text_lines", "lines"):
        value = getattr(prediction, attr, None)
        if value is not None:
            return list(value)
    if isinstance(prediction, dict):
        for key in ("text_lines", "lines"):
            value = prediction.get(key)
            if value is not None:
                return list(value)
    return []


def _line_block(line: Any, block_index: int, line_index: int) -> dict[str, Any] | None:
    text = str(getattr(line, "text", "")).strip()
    if not text:
        return None
    words = _line_words(line, block_index, line_index)
    return {
        "block_id": f"b-{block_index:04d}",
        "block_type": "text",
        "bbox_native": _bbox(getattr(line, "bbox", None)),
        "lines": [
            {
                "line_id": f"l-{block_index:04d}-{line_index:04d}",
                "source_raw": text,
                "confidence": _confidence(getattr(line, "confidence", None)),
                "bbox_native": _bbox(getattr(line, "bbox", None)),
                "words": words,
            }
        ],
    }


def _run_recognition(images: list[Any]) -> tuple[list[Any], str]:
    """Run Surya recognition on a list of PIL images.

    Returns (predictions, api_name) where predictions[i] is the OCRResult
    for images[i].  Accepts one or many images in a single predictor call
    so model-load cost is paid once.
    """
    # Surya 0.8+ API: detection + recognition share a FoundationPredictor.
    try:
        from surya.detection import DetectionPredictor
        from surya.foundation import FoundationPredictor
        from surya.recognition import RecognitionPredictor

        foundation = FoundationPredictor()
        det_predictor = DetectionPredictor()
        rec_predictor = RecognitionPredictor(foundation)
        return (
            rec_predictor(images, det_predictor=det_predictor),
            "surya.recognition.RecognitionPredictor",
        )
    except (ImportError, AttributeError):
        pass

    # Older surya.ocr.run_recognition API (pre-0.8).
    try:
        from surya.ocr import run_recognition
        from surya.model.recognition.model import load_model
        from surya.model.recognition.processor import load_processor

        rec_model = load_model()
        rec_processor = load_processor()
        return (
            run_recognition(images, [["en"]] * len(images), rec_model, rec_processor),
            "surya.ocr.run_recognition",
        )
    except (ImportError, AttributeError):
        pass

    raise RuntimeError(
        "Cannot find a compatible Surya OCR API. "
        "Tried: surya.recognition.RecognitionPredictor (0.8+), surya.ocr.run_recognition (pre-0.8)."
    )


def _build_page_payload(
    prediction: Any,
    api_used: str,
    engine_version: str,
    orig_w: int,
    orig_h: int,
    scale_to_native: float,
) -> dict[str, Any]:
    """Convert one OCR prediction into the page payload dict."""
    lines = _text_lines(prediction) if prediction is not None else []
    blocks: list[dict[str, Any]] = []
    original_text_good: dict[str, bool] = {}
    for block_index, line in enumerate(lines, start=1):
        block = _line_block(line, block_index, 1)
        if block is None:
            continue
        blocks.append(block)
        flag = getattr(line, "original_text_good", None)
        if flag is not None:
            original_text_good[f"l-{block_index:04d}-0001"] = bool(flag)

    # Scale bboxes back to original native-pixel coordinates when a resolution
    # cap was applied before inference.
    blocks = _scale_blocks(blocks, scale_to_native)

    payload: dict[str, Any] = {
        "ok": True,
        "api_used": api_used,
        "engine_version": engine_version,
        "page_width": orig_w,
        "page_height": orig_h,
        "blocks": blocks,
    }
    if scale_to_native != 1.0:
        # Record that inference ran on a downscaled image so the sidecar is
        # self-describing.  inference_width is what was fed to the model;
        # page_width/page_height are always native coordinates.
        payload["surya_inference_width"] = round(orig_w / scale_to_native)
        payload["surya_scale_to_native"] = round(scale_to_native, 6)
    if original_text_good:
        payload["surya_original_text_good"] = original_text_good
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--image", type=Path,
        help="Single image path (backward-compatible single-page mode).",
    )
    group.add_argument(
        "--images", type=Path, nargs="+", metavar="PATH",
        help="One or more image paths; emits one JSON line per image in a single predictor call.",
    )
    parser.add_argument(
        "--max-width", type=int, default=None, dest="max_width",
        help=(
            "Downscale images wider than this (px) before inference; "
            "bboxes are scaled back to original native-pixel coordinates. "
            f"Default: {MAX_WIDTH_PX} (no cap)."
        ),
    )
    parser.add_argument(
        "--raw-output",
        type=Path,
        default=None,
        help="Optional raw JSON output path for single-image mode.",
    )
    parser.add_argument(
        "--raw-outputs",
        type=Path,
        nargs="+",
        default=None,
        help="Optional raw JSON output paths matching --images order.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    max_width: int | None = args.max_width if args.max_width is not None else MAX_WIDTH_PX
    image_paths: list[Path] = args.images if args.images else [args.image]
    raw_outputs: list[Path | None]
    if args.raw_outputs is not None:
        if len(args.raw_outputs) != len(image_paths):
            fail = _failure(ValueError("--raw-outputs must match the number of input images"))
            for _ in image_paths:
                _emit(fail)
            return 1
        raw_outputs = list(args.raw_outputs)
    elif args.raw_output is not None:
        raw_outputs = [args.raw_output]
    else:
        raw_outputs = [None] * len(image_paths)

    # Lazy import so tests that call helper functions don't need Surya installed.
    try:
        import surya
        from PIL import Image
    except Exception as exc:
        fail = _failure(exc)
        for _ in image_paths:
            _emit(fail)
        return 0

    # Open and downscale all images before batch inference.
    images_data: list[dict[str, Any]] = []
    try:
        for img_path in image_paths:
            img = Image.open(img_path).convert("RGB")
            orig_w, orig_h = img.size
            inf_img, scale_to_native = _maybe_downscale(img, max_width)
            images_data.append({
                "orig_w": orig_w,
                "orig_h": orig_h,
                "inf_img": inf_img,
                "scale": scale_to_native,
                "image_path": img_path,
            })
        inf_images = [d["inf_img"] for d in images_data]
        all_predictions, api_used = _run_recognition(inf_images)
        engine_version = str(getattr(surya, "__version__", "unknown"))
    except Exception as exc:
        fail = _failure(exc)
        for _ in image_paths:
            _emit(fail)
        return 0

    # Emit one JSON line per image.
    for img_data, prediction, raw_output in zip(images_data, all_predictions, raw_outputs):
        try:
            if raw_output is not None:
                _write_raw_prediction(
                    raw_output,
                    image_path=img_data["image_path"],
                    prediction=prediction,
                    api_used=api_used,
                    engine_version=engine_version,
                    orig_w=img_data["orig_w"],
                    orig_h=img_data["orig_h"],
                    scale_to_native=img_data["scale"],
                )
            payload = _build_page_payload(
                prediction,
                api_used=api_used,
                engine_version=engine_version,
                orig_w=img_data["orig_w"],
                orig_h=img_data["orig_h"],
                scale_to_native=img_data["scale"],
            )
            _emit(payload)
        except Exception as exc:
            _emit(_failure(exc))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
