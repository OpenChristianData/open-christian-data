"""Run Calamari OCR for one page image and emit one JSON result line.

Calamari is a line-level recognizer. This script segments the page into
horizontal text bands using a simple projection profile, then runs Calamari
on each band and assembles the output into a blocks structure.

Pass --model as a path to a Calamari checkpoint file or checkpoint directory.
"""

# RETIRED 2026-05-31: Calamari tested on NSH scans; insufficient quality.
# Non-white background (~128 gray) required custom normalisation that still
# underperformed Kraken and Surya. File kept for audit trail; not invoked.

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _emit(payload: dict[str, Any]) -> None:
    # Write to stdout.buffer (bytes) with UTF-8 to avoid cp1252 codec errors
    # when OCR text contains non-Latin characters.
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.buffer.write(line.encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def _failure(failure_class: str, exc: BaseException) -> dict[str, Any]:
    return {
        "ok": False,
        "failure_class": failure_class,
        "error": f"{type(exc).__name__}: {str(exc)[:200]}",
    }


def _segment_rows(im_gray: Any, min_gap: int = 2, min_height: int = 4) -> list[tuple[int, int]]:
    """Return (y_start, y_end) row bands in original image coordinates.

    Strategy:
    1. Downsample to ~1000px wide so text lines have distinct gaps regardless
       of the original scan resolution (Schaff-Herzog pages are 4925x6992).
    2. Use a low fixed threshold (< 20 in the downsampled image) to detect
       ink pixels — these scans have background ~128 and ink ~0-1, so Otsu
       gives a threshold of ~9 which misses antialiased edges; a fixed 20
       captures them without pulling in grey background.
    3. Treat a row as 'has ink' only when it exceeds min_ink_count pixels,
       filtering out single-pixel JPEG artifact rows that bridge true gaps.
    4. Map detected band coordinates back to original image space.
    """
    import numpy as np
    from PIL import Image as _Image

    # Downsample for segmentation: target ~1000px wide
    orig_w, orig_h = im_gray.size
    seg_w = min(1000, orig_w)
    seg_h = int(orig_h * seg_w / orig_w)
    im_small = im_gray.resize((seg_w, seg_h), _Image.LANCZOS)
    arr = np.array(im_small)

    # Ink pixels darker than 20 in the downsampled image
    ink_pixel_threshold = 20
    row_ink = np.sum(arr < ink_pixel_threshold, axis=1)

    # A row counts as 'text' only when it has a meaningful number of ink pixels
    # (filters out 1-3 px JPEG artifact rows that bridge inter-line gaps)
    min_ink_count = max(5, seg_w // 100)

    # Scale factor from small back to original
    scale_inv = orig_h / seg_h

    bands: list[tuple[int, int]] = []
    in_band = False
    band_start = 0
    blank_run = 0

    for y in range(seg_h):
        has_ink = row_ink[y] > min_ink_count
        if has_ink:
            if not in_band:
                band_start = y
                in_band = True
            blank_run = 0
        else:
            if in_band:
                blank_run += 1
                if blank_run >= min_gap:
                    band_end = y - blank_run
                    if band_end - band_start >= min_height:
                        # Map back to original coordinates
                        bands.append((int(band_start * scale_inv), int(band_end * scale_inv)))
                    in_band = False
                    blank_run = 0

    if in_band and seg_h - band_start >= min_height:
        bands.append((int(band_start * scale_inv), orig_h))

    return bands


def _build_blocks_from_predictions(
    predictions: list[tuple[tuple[int, int], str, float | None]],
    page_width: int = 0,
) -> list[dict[str, Any]]:
    """Build sidecar blocks from (bbox_row, text, confidence) triples."""
    blocks: list[dict[str, Any]] = []
    for block_index, (row_band, text, confidence) in enumerate(predictions, start=1):
        text = text.strip()
        if not text:
            continue
        y0, y1 = row_band
        bbox: dict[str, Any] | None = (
            {"x": 0, "y": float(y0), "w": float(page_width), "h": float(y1 - y0)}
            if page_width > 0
            else None
        )
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
        blocks.append(
            {
                "block_id": f"b-{block_index:04d}",
                "block_type": "text",
                "bbox_native": bbox,
                "lines": [
                    {
                        "line_id": f"l-{block_index:04d}-0001",
                        "source_raw": text,
                        "confidence": confidence,
                        "bbox_native": bbox,
                        "words": words,
                    }
                ],
            }
        )
    return blocks


def _resolve_checkpoints(model_path: str, max_n: int = 0) -> list[str]:
    """Resolve a model path to a list of checkpoint paths.

    Accepts either:
    - A directory containing *.ckpt.json files (ensemble) -- returns all of them sorted.
    - A single checkpoint file path -- returns it wrapped in a list.
    """
    p = Path(model_path)
    if p.is_dir():
        ckpts = sorted(p.glob("*.ckpt.json"))
        if not ckpts:
            # Also try .ckpt files without .json suffix
            ckpts = sorted(p.glob("*.ckpt"))
        if max_n > 0:
            ckpts = ckpts[:max_n]
        if ckpts:
            return [str(c) for c in ckpts]
    return [model_path]


def _predict_with_calamari(
    model_path: str,
    line_arrays: list[Any],
    max_checkpoints: int = 0,
) -> list[tuple[str, float | None]]:
    """Run calamari prediction on a list of numpy line arrays.

    Tries the v2 MultiPredictor API first, then falls back to v1 patterns.
    Accepts a directory of checkpoint files (ensemble) or a single checkpoint.
    Returns list of (text, confidence) for each input line.
    """
    import numpy as np

    checkpoints = _resolve_checkpoints(model_path, max_n=max_checkpoints)
    results: list[tuple[str, float | None]] = []

    try:
        # calamari_ocr v2 API.
        # predict_raw() yields Sample objects (NOT tuples).
        # sample.outputs = (list_of_PredictionResult, raw_tensors).
        # outputs[0] is a list; take outputs[0][0] for the voted ensemble result.
        # PredictionResult has .sentence (str) and .avg_char_probability (float).
        from calamari_ocr.ocr.predict.predictor import MultiPredictor, PredictorParams  # type: ignore

        params = PredictorParams()
        predictor = MultiPredictor.from_paths(
            checkpoints=checkpoints,
            predictor_params=params,
        )
        # Batch ALL lines in a single predict_raw call. Calling predict_raw
        # once per line triggers repeated TF graph compilation; batching amortises
        # the compilation cost across all lines in the page.
        # outputs[1] is the voted ensemble Prediction (.sentence, .avg_char_probability).
        for sample in predictor.predict_raw(line_arrays):
            text = ""
            conf: float | None = None
            try:
                outs = getattr(sample, "outputs", None) or ()
                pred = outs[1] if len(outs) > 1 else (outs[0] if outs else None)
                if pred is not None:
                    text = str(getattr(pred, "sentence", None) or "")
                    avg_conf = getattr(pred, "avg_char_probability", None)
                    if avg_conf is not None:
                        conf = float(avg_conf)
            except Exception as _line_exc:  # noqa: BLE001
                text = ""
                conf = None
                # API shape mismatch -- leave text empty so caller detects all-empty result.
            results.append((text.strip(), conf))
        return results
    except (ImportError, AttributeError):
        pass

    try:
        # calamari_ocr v1 / alternative API
        from calamari_ocr.ocr import Predictor as V1Predictor  # type: ignore

        predictor = V1Predictor(checkpoint=model_path)
        for line_arr in line_arrays:
            text = ""
            conf = None
            try:
                raw_preds = predictor.predict_raw([line_arr], progress_bar=False)
                if raw_preds:
                    pred = raw_preds[0]
                    text = str(getattr(pred, "sentence", "") or "")
                    conf_val = getattr(pred, "avg_char_probability", None)
                    if conf_val is not None:
                        conf = float(conf_val)
            except Exception as _line_exc:  # noqa: BLE001
                text = ""
                conf = None
            results.append((text.strip(), conf))
        return results
    except (ImportError, AttributeError):
        pass

    raise RuntimeError("Cannot import calamari_ocr predictor (tried v2 MultiPredictor and v1 Predictor)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--model", type=str, default="", help="Calamari checkpoint path or directory")
    parser.add_argument(
        "--max-checkpoints",
        type=int,
        default=0,
        help=(
            "Max checkpoints to use from ensemble (0 = all, default). "
            "Use 1 or 2 for faster runs at some accuracy cost."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        import calamari_ocr
        import numpy as np
        from PIL import Image
    except Exception as exc:
        _emit(_failure("calamari_import_error", exc))
        return 1

    if not args.model:
        _emit(_failure("calamari_no_model", ValueError(
            "--model is required; specify a Calamari checkpoint file or directory"
        )))
        return 1

    try:
        with Image.open(args.image) as raw:
            width, height = raw.size
            im_gray = raw.convert("L")
            im_arr = np.array(im_gray)
    except OSError as exc:
        _emit(_failure("image_open_error", exc))
        return 1

    try:
        row_bands = _segment_rows(im_gray)
        if not row_bands:
            # No text rows found -- emit empty but valid result
            _emit({
                "ok": True,
                "engine_version": str(getattr(calamari_ocr, "__version__", "unknown")),
                "model_id": args.model,
                "page_width": width,
                "page_height": height,
                "blocks": [],
            })
            return 0

        # Normalize to standard [0-255] range before passing to Calamari.
        # These JPEG scans have background ~128 and ink ~0 rather than the
        # standard white (255) background, so we scale up so background ->
        # 255 and ink stays at 0. Without this Calamari sees "gray" background
        # and produces empty predictions.
        max_val = int(im_arr.max())
        if max_val > 0 and max_val < 200:
            scale = 255.0 / max_val
            im_arr_norm = np.clip(im_arr.astype(np.float32) * scale, 0, 255).astype(np.uint8)
        else:
            im_arr_norm = im_arr
        raw_lines = [im_arr_norm[y0:y1, :] for y0, y1 in row_bands]

        # Cap line width to reduce TF inference time. Calamari models are
        # trained on line-normalized images; the full 4925-pixel scan width
        # is ~2.5x wider than needed and slows inference proportionally.
        MAX_LINE_WIDTH = 2000
        line_arrays = []
        for arr in raw_lines:
            h, w = arr.shape
            if w > MAX_LINE_WIDTH:
                from PIL import Image as _Image
                resized = _Image.fromarray(arr).resize(
                    (MAX_LINE_WIDTH, max(1, int(h * MAX_LINE_WIDTH / w))),
                    _Image.LANCZOS,
                )
                arr = np.array(resized)
            line_arrays.append(arr)

        text_conf = _predict_with_calamari(
            args.model,
            line_arrays,
            max_checkpoints=args.max_checkpoints,
        )
    except Exception as exc:
        _emit(_failure("calamari_runtime_error", exc))
        return 0

    predictions = [
        (band, text, conf)
        for band, (text, conf) in zip(row_bands, text_conf)
    ]
    blocks = _build_blocks_from_predictions(predictions, page_width=width)

    _emit(
        {
            "ok": True,
            "engine_version": str(getattr(calamari_ocr, "__version__", "unknown")),
            "model_id": args.model,
            "page_width": width,
            "page_height": height,
            "blocks": blocks,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
