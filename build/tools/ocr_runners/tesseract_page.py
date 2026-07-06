"""Run Tesseract OCR for one page image and emit one JSON result line.

Uses hOCR output to capture per-line structural attributes (x_size, baseline,
x_descenders, x_ascenders) alongside the standard word-level text and bboxes.
Line attributes are emitted in tesseract_line_attrs, keyed by line_native_id,
and land in page_extras_carried via the runner's standard side-channel path.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config (PY-03) -- set at module level so they're visible without reading main().
# ---------------------------------------------------------------------------

# Language pack for Tesseract.  NSH entries use Greek headwords, Hebrew
# references, Syriac sources, plus Latin/German/French footnotes.
LANGUAGES = "eng+grc+heb+lat+deu+fra+syr"

# Page segmentation mode: 3 = fully automatic without OSD.  NSH pages have
# consistent orientation so OSD (PSM 1) adds ~4s per page with no quality gain.
# x_size bimodal distribution for heading detection is preserved by PSM 3.
PSM = "3"

# OCR engine mode: None = let Tesseract choose (OEM 3, resolves to LSTM on
# Tesseract 5.x).  Set to "1" to force LSTM-only explicitly if needed.
OEM: str | None = None


def _emit(payload: dict[str, Any]) -> None:
    # Write to stdout.buffer (bytes) with UTF-8 for consistency and robustness.
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.buffer.write(line.encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def _failure(failure_class: str, exc: BaseException) -> dict[str, Any]:
    return {
        "ok": False,
        "failure_class": failure_class,
        "error": f"{type(exc).__name__}: {str(exc)[:200]}",
    }


def _tesseract_binary() -> str:
    found = shutil.which("tesseract")
    if found:
        return found
    program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    return str(program_files / "Tesseract-OCR" / "tesseract.exe")


def _bbox_union(boxes: list[dict[str, int]]) -> dict[str, int] | None:
    if not boxes:
        return None
    x0 = min(box["x"] for box in boxes)
    y0 = min(box["y"] for box in boxes)
    x1 = max(box["x"] + box["w"] for box in boxes)
    y1 = max(box["y"] + box["h"] for box in boxes)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def _mean(values: list[float | None]) -> float | None:
    numeric = [value for value in values if value is not None]
    if not numeric:
        return None
    return sum(numeric) / len(numeric)


def _parse_hocr_title(title: str) -> dict[str, str]:
    """Parse a hOCR title attribute into a key->value dict.

    Example: 'bbox 10 5 200 50; x_size 36; baseline 0.001 -4'
    Result:  {'bbox': '10 5 200 50', 'x_size': '36', 'baseline': '0.001 -4'}
    """
    result: dict[str, str] = {}
    for part in title.split(";"):
        part = part.strip()
        if not part:
            continue
        key, _, val = part.partition(" ")
        result[key.strip()] = val.strip()
    return result


def _hocr_bbox(title: dict[str, str]) -> dict[str, int] | None:
    parts = title.get("bbox", "").split()
    if len(parts) < 4:
        return None
    try:
        x0, y0, x1, y1 = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
    except (ValueError, TypeError):
        return None


def _hocr_float(title: dict[str, str], key: str) -> float | None:
    try:
        return float(title[key])
    except (KeyError, TypeError, ValueError):
        return None


def _hocr_baseline(title: dict[str, str]) -> list[float] | None:
    """Parse 'baseline p1 p0' into [slope, intercept]."""
    parts = title.get("baseline", "").split()
    if len(parts) < 2:
        return None
    try:
        return [float(p) for p in parts]
    except (TypeError, ValueError):
        return None


class _HocrParser(HTMLParser):
    """SAX-style hOCR parser. Tracks blocks/lines/words via an element stack.

    pytesseract hOCR structure:
        div.ocr_page > div.ocr_carea > p.ocr_par > span.ocr_line > span.ocrx_word
    """

    def __init__(self) -> None:
        super().__init__()
        # Stack entries: (tag_name, class_string, parsed_title_dict)
        self._stack: list[tuple[str, str, dict[str, str]]] = []

        self._current_block_id: int = 0
        self._current_line_words: list[dict[str, Any]] = []
        self._current_line_title: dict[str, str] = {}
        self._current_line_block_id: int = 0
        self._current_word_title: dict[str, str] = {}
        self._current_word_chars: list[str] = []
        self._in_word: bool = False

        # Collected output: flat list of lines, each with their block context
        self.all_lines: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = dict(attrs)
        cls = d.get("class") or ""
        title = _parse_hocr_title(d.get("title") or "")
        self._stack.append((tag, cls, title))

        if "ocr_carea" in cls:
            self._current_block_id += 1
        elif "ocr_line" in cls:
            self._current_line_words = []
            self._current_line_title = title
            self._current_line_block_id = self._current_block_id
        elif "ocrx_word" in cls:
            self._current_word_chars = []
            self._current_word_title = title
            self._in_word = True

    def handle_data(self, data: str) -> None:
        if self._in_word:
            self._current_word_chars.append(data)

    def handle_endtag(self, tag: str) -> None:
        # Pop the innermost matching element (correct for properly nested hOCR)
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                _, cls, _ = self._stack.pop(i)
                break
        else:
            return

        if "ocrx_word" in cls:
            self._in_word = False
            text = "".join(self._current_word_chars).strip()
            if text:
                wconf_str = self._current_word_title.get("x_wconf")
                try:
                    conf: float | None = float(wconf_str) / 100.0 if wconf_str else None
                except (TypeError, ValueError):
                    conf = None
                self._current_line_words.append(
                    {
                        "text": text,
                        "confidence": conf,
                        "bbox": _hocr_bbox(self._current_word_title),
                    }
                )

        elif "ocr_line" in cls:
            if self._current_line_words:
                self.all_lines.append(
                    {
                        "words": list(self._current_line_words),
                        "title": self._current_line_title,
                        "block_id": self._current_line_block_id,
                    }
                )
            self._current_line_words = []


def _blocks_from_hocr(
    hocr_bytes: bytes,
    _side_channel: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Parse hOCR bytes into the sidecar block structure.

    Lines with structural attributes (x_size, baseline, x_descenders,
    x_ascenders) are collected in _side_channel['tesseract_line_attrs'],
    keyed by line_native_id, when _side_channel is provided.
    """
    parser = _HocrParser()
    parser.feed(hocr_bytes.decode("utf-8", errors="replace"))

    # Group lines by block_id (preserving order)
    block_lines: dict[int, list[dict[str, Any]]] = {}
    for line in parser.all_lines:
        block_id = line["block_id"] or 1  # fallback if no ocr_carea found
        block_lines.setdefault(block_id, []).append(line)

    line_attrs: dict[str, dict[str, Any]] = {}
    blocks: list[dict[str, Any]] = []
    for block_index, block_id in enumerate(sorted(block_lines), start=1):
        lines_out: list[dict[str, Any]] = []
        for line_index, line_data in enumerate(block_lines[block_id], start=1):
            title = line_data["title"]
            words_data = line_data["words"]

            line_id = f"l-{block_index:04d}-{line_index:04d}"
            words_out: list[dict[str, Any]] = []
            line_boxes: list[dict[str, int]] = []
            for word_index, word in enumerate(words_data, start=1):
                bbox = word["bbox"]
                if bbox:
                    line_boxes.append(bbox)
                words_out.append(
                    {
                        "word_id": f"w-{block_index:04d}-{line_index:04d}-{word_index:04d}",
                        "source_raw": word["text"],
                        "confidence": word["confidence"],
                        "bbox_native": bbox,
                    }
                )

            if not words_out:
                continue

            line_text = " ".join(w["source_raw"] for w in words_out)
            line_conf = _mean([w["confidence"] for w in words_out])
            line_bbox = _bbox_union(line_boxes) if line_boxes else None
            lines_out.append(
                {
                    "line_id": line_id,
                    "source_raw": line_text,
                    "confidence": line_conf,
                    "bbox_native": line_bbox,
                    "words": words_out,
                }
            )

            # Collect per-line structural attributes for side-channel
            attrs: dict[str, Any] = {}
            x_size = _hocr_float(title, "x_size")
            if x_size is not None:
                attrs["x_size"] = x_size
            baseline = _hocr_baseline(title)
            if baseline is not None:
                attrs["baseline"] = baseline
            x_desc = _hocr_float(title, "x_descenders")
            if x_desc is not None:
                attrs["x_descenders"] = x_desc
            x_asc = _hocr_float(title, "x_ascenders")
            if x_asc is not None:
                attrs["x_ascenders"] = x_asc
            if attrs:
                line_attrs[line_id] = attrs

        if not lines_out:
            continue

        block_boxes: list[dict[str, int]] = [
            w["bbox_native"]
            for line in lines_out
            for w in line["words"]
            if w["bbox_native"] is not None
        ]
        blocks.append(
            {
                "block_id": f"b-{block_index:04d}",
                "block_type": "text",
                "bbox_native": _bbox_union(block_boxes) if block_boxes else None,
                "lines": lines_out,
            }
        )

    if _side_channel is not None and line_attrs:
        _side_channel["tesseract_line_attrs"] = line_attrs

    return blocks


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, default=None)
    parser.add_argument(
        "--languages", default=LANGUAGES,
        help=f"Tesseract language pack (default: {LANGUAGES!r}).",
    )
    parser.add_argument(
        "--psm", default=PSM,
        help=f"Tesseract page segmentation mode (default: {PSM}).",
    )
    parser.add_argument(
        "--oem", default=OEM,
        help="Tesseract OCR engine mode (default: None = let Tesseract choose).",
    )
    parser.add_argument(
        "--raw-output",
        type=Path,
        default=None,
        help="Optional path for the raw hOCR bytes produced by Tesseract.",
    )
    parser.add_argument(
        "--batch-manifest-file",
        type=Path,
        default=None,
        dest="batch_manifest_file",
        metavar="PATH",
        help=(
            "JSON file listing [{image, raw_output}] entries. When provided, the "
            "Python process is reused across all images; one result line is emitted "
            "per entry. Overrides --image."
        ),
    )
    return parser.parse_args(argv)


def _build_tesseract_config(psm: str, oem: str | None) -> str:
    """Assemble the Tesseract --config string from PSM and optional OEM."""
    parts = [f"--psm {psm}"]
    if oem is not None:
        parts.append(f"--oem {oem}")
    return " ".join(parts)


def _run_one_image(
    *,
    image_path: Path,
    pytesseract: Any,
    config: str,
    languages: str,
    engine_version: str,
    raw_output: Path | None,
) -> dict[str, Any]:
    """Process one image. Returns payload dict (ok=True or ok=False)."""
    from PIL import Image
    try:
        with Image.open(image_path) as image:
            width, height = image.size
            hocr_bytes = pytesseract.image_to_pdf_or_hocr(
                image,
                lang=languages,
                config=config,
                extension="hocr",
            )
    except OSError as exc:
        return _failure("image_open_error", exc)
    except Exception as exc:
        return _failure("tesseract_runtime_error", exc)

    if raw_output is not None:
        try:
            raw_output.parent.mkdir(parents=True, exist_ok=True)
            raw_output.write_bytes(hocr_bytes)
        except OSError as exc:
            return _failure("raw_artifact_write_error", exc)

    side_channel: dict[str, Any] = {}
    blocks = _blocks_from_hocr(hocr_bytes, _side_channel=side_channel)
    payload: dict[str, Any] = {
        "ok": True,
        "engine_version": engine_version,
        "page_width": width,
        "page_height": height,
        "blocks": blocks,
    }
    payload.update(side_channel)
    return payload


def main() -> int:
    args = parse_args()
    try:
        import pytesseract
    except Exception as exc:
        _emit(_failure("tesseract_import_error", exc))
        return 1

    pytesseract.pytesseract.tesseract_cmd = _tesseract_binary()
    config = _build_tesseract_config(args.psm, args.oem)
    engine_version = str(pytesseract.get_tesseract_version())

    if args.batch_manifest_file is not None:
        # Batch mode: reuse this Python process for all entries.
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
                pytesseract=pytesseract,
                config=config,
                languages=args.languages,
                engine_version=engine_version,
                raw_output=raw_out,
            )
            _emit(payload)
        return 0

    # Single-image mode.
    if args.image is None:
        _emit(_failure("missing_argument", ValueError("--image or --batch-manifest-file required")))
        return 1

    payload = _run_one_image(
        image_path=args.image,
        pytesseract=pytesseract,
        config=config,
        languages=args.languages,
        engine_version=engine_version,
        raw_output=args.raw_output,
    )
    _emit(payload)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
