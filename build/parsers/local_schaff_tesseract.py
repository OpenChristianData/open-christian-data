"""local_schaff_tesseract.py -- Tesseract OCR parser for Schaff-Herzog IA pages.

Locked configuration (B2.2 probe matrix):
  PSM=1, lang=eng, preprocessing=raw
  config_hash: 69f7a4887aedad0e7158706cb3cf9ff212eff7bf5cc55f194ab65b484adc45ab

Usage:
  py -3 build/parsers/local_schaff_tesseract.py --volume 1 [--dry-run] [--force]

Output:
  Per-page sidecar: raw/internet-archive/schaff-herzog-pages/vol_NN/page_NNNN.oss-tesseract.json
  Per-volume JSON:  data/reference/schaff/encyclopedia/1908-1914/oss-tesseract-v1/vol_NN.json
  Log:              logs/local_schaff_tesseract.log
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from bs4 import BeautifulSoup

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from build.lib.page_order import volume_assembly_records, volume_image_paths  # noqa: E402

def is_running_header(norm: str) -> bool:
    """True if line is a structural header to skip (running page headers, section headers).

    Uses fragment matching (not exact strings) to handle OCR digit-substitution
    and truncation across all 9 IA volumes.  Fragments tested:

      - SCHAFF|CHAFF + HERZ: left-side running header 'THE NEW SCHAFF-HERZOG'
        and variants like '8CHAFF-HERZ0G' (digits sub for letters).
      - TH[A-Z] prefix + SCHAFF|CHAFF or HERZ: covers 'THE' OCR'd to 'THB',
        'TH?' etc. when only one name fragment survives.
      - ENCY|NCYCL + RELIG or short line: right-side header 'RELIGIOUS ENCYCLOPEDIA'
        and variants like 'ENCYCLOPEDU', 'BNCYCLOFEDIA'.
      - RELIG + KNOWLEDGE: right-side header 'RELIGIOUS KNOWLEDGE' (8 of 9 volumes).
      - Lines starting with 'THE ': no legitimate article begins this way.

    Article headings always contain ':'; these structural headers never do.
    """
    if ":" in norm:
        return False
    if norm.upper().startswith("THE "):
        return True

    alpha_only = re.sub(r"[^A-Z ]", "", norm.upper())
    alpha_only = re.sub(r"\s+", " ", alpha_only).strip()

    schaff_frag = bool(re.search(r"SCHAFF|CHAFF", alpha_only))
    herz_frag = "HERZ" in alpha_only
    if schaff_frag and herz_frag:
        return True
    if re.match(r"^TH[A-Z] ", alpha_only) and (schaff_frag or herz_frag):
        return True

    has_encycl = bool(re.search(r"ENCY|NCYCL", alpha_only))
    has_relig = "RELIG" in alpha_only
    if has_encycl and (has_relig or len(alpha_only) < 30):
        return True

    if has_relig and "KNOWLEDGE" in alpha_only:
        return True

    return False


def is_article_heading(norm: str) -> bool:
    """True if normalized line is an article heading.

    Three valid forms:
      Form 1 (inline):       CAPS_TERM: body text starts on same line
      Form 2 (standalone+:): CAPS_TERM: (entire line, colon at end; body on next lines)
      Form 3 (standalone):   CAPS_TERM  (entire line ALL CAPS, no colon; long article names)

    Detection rules:
      - Starts with 2+ consecutive uppercase letters
      - Is NOT a running page header (excluded before this check)
      - Is NOT a Roman-numeral section header (I., II., etc.)
      - Form 1/2: contains ':'
      - Form 3: entire stripped line is ALL CAPS with >= 4 alpha chars
      - Form 4: 'HEADWORD. See TARGET.' cross-reference article
      - Form 5: 'HEADWORD, phonetic.' where phonetic is lowercase with stress markers

    Notes:
      - Running headers ('THE NEW SCHAFF-HERZOG', 'RELIGIOUS ENCYCLOPEDIA', section
        header 'ENCYCLOPEDIA OF RELIGIOUS KNOWLEDGE') are excluded by is_running_header.
      - Body lines starting with 'See AARON: ...' fail because 'S' then 'e' is not 2+
        consecutive uppercase letters.
      - Multi-line headings (e.g. 'CHANDIEU, ... DE LA / ROCHE:' split across two OCR
        lines) will be incorrectly split; this is an inherent OCR limitation.
    """
    if not re.match(r"^[A-Z]{2}", norm):
        return False
    if re.match(r"^END\s+OF\s+(VOL[\.,]?|VOLUME)\b", norm, re.IGNORECASE):
        return False
    if is_running_header(norm):
        return False
    if re.match(r"^[IVXLCDM]+\.?\s", norm):
        return False
    if ":" in norm:
        return True
    stripped = norm.strip()
    if stripped == stripped.upper():
        alpha_count = sum(1 for c in stripped if c.isalpha())
        if alpha_count >= 4:
            return True
    # Form 4: cross-reference article -- "HEADWORD. See TARGET."
    if re.match(r"^[A-Z][A-Z ,\-]*\.\s+See\b", norm):
        return True
    # Form 5: pronunciation-guide -- "HEADWORD, phonetic." where phonetic is a
    # single lowercase token ending with a period, e.g. "GEZER, gi'zer."
    # Single-token check (no spaces) discriminates from body text ("PAUL, the apostle").
    # Apostrophe-agnostic: OCR may produce U+2019 or straight quote.
    m = re.match(r"^([A-Z][A-Z ,\-]*),\s+([a-z].*)$", norm)
    if m and re.match(r"^[a-z][^\s.]+\.$", m.group(2)):
        return True
    return False

# ---------------------------------------------------------------------------
# Config (B2.2 locked values -- do not modify without bumping config_hash)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_PAGES = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
OUTPUT_DIR = REPO_ROOT / "data" / "reference" / "schaff" / "encyclopedia" / "1908-1914" / "oss-tesseract-v1"
LOG_PATH = REPO_ROOT / "logs" / "local_schaff_tesseract.log"

TESSERACT_CMD = os.environ.get("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")

LOCKED_PSM: int = 1
LOCKED_LANG: str = "eng"
LOCKED_PREPROCESSING: str = "raw"
ENGINE_VERSION: str = "tesseract v5.5.0.20241111"
ENGINE_ALIAS: str = "oss-tesseract"
CONFIG_HASH: str = "69f7a4887aedad0e7158706cb3cf9ff212eff7bf5cc55f194ab65b484adc45ab"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sidecar I/O
# ---------------------------------------------------------------------------

def write_sidecar(sidecar_path: Path, data: dict) -> None:
    """Write sidecar JSON atomically (os.replace avoids WinError 183)."""
    tmp = sidecar_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, sidecar_path)


def should_skip_page(sidecar_path: Path) -> bool:
    """True if sidecar exists and contains a valid (conf > 0) prior OCR run."""
    if not sidecar_path.exists():
        return False
    try:
        cached = json.loads(sidecar_path.read_text(encoding="utf-8"))
        return float(cached.get("confidence_mean", 0.0)) > 0.0
    except (json.JSONDecodeError, ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Tesseract OCR — hOCR single-pass (replaces separate TSV + text passes)
# ---------------------------------------------------------------------------

def _parse_bbox(title: str) -> dict | None:
    """Extract axis-aligned bbox from a Tesseract hOCR title attribute."""
    m = re.search(r'\bbbox (\d+) (\d+) (\d+) (\d+)', title)
    if not m:
        return None
    x0, y0, x1, y1 = int(m[1]), int(m[2]), int(m[3]), int(m[4])
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def _parse_wconf(title: str) -> float | None:
    """Extract word confidence (0-100) from a Tesseract hOCR title attribute."""
    m = re.search(r'\bx_wconf (\d+)', title)
    return float(m[1]) if m else None


def _run_tesseract_hocr(jpeg_path: Path) -> str:
    """Single Tesseract hOCR pass; returns raw HTML string."""
    with tempfile.NamedTemporaryFile(suffix="", delete=False) as t:
        base = t.name
    try:
        cmd = [
            TESSERACT_CMD, str(jpeg_path), base,
            "-l", LOCKED_LANG, "--psm", str(LOCKED_PSM), "hocr",
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
        hocr_path = Path(base + ".hocr")
        return hocr_path.read_text(encoding="utf-8") if hocr_path.exists() else ""
    finally:
        for ext in [".hocr", ""]:
            Path(base + ext).unlink(missing_ok=True)


def _parse_line_metrics(title: str) -> dict:
    """Extract Tesseract line-level metrics from the hOCR title attribute.

    Tesseract emits per-line: bbox, baseline (slope + intercept), x_size,
    x_descenders, x_ascenders. baseline a b is a polynomial: y = a*x + b
    relative to the bbox bottom — captures per-line skew. x_size is the
    measured x-height in pixels, which discriminates Schaff-Herzog small-caps
    headwords (~55px) from body text (~70px) on this corpus.
    """
    metrics: dict = {}
    m = re.search(r'baseline ([-\d.]+) ([-\d.]+)', title)
    if m:
        metrics["baseline"] = [float(m[1]), float(m[2])]
    for key in ("x_size", "x_descenders", "x_ascenders"):
        m = re.search(rf'\b{key} ([\d.]+)', title)
        if m:
            metrics[key] = float(m[1])
    return metrics


def _parse_hocr(html: str) -> tuple[float, list[dict], list[int]]:
    """Parse Tesseract hOCR HTML into the normalized sidecar block structure.

    Returns (confidence_mean, blocks, image_size).
    image_size: [width, height] from the ocr_page title attribute.
    Each block: {"bbox": {...}, "lines": [...]}.
    Each line:  {"text": "...", "bbox": {...}, "words": [...]}.
    Each word:  {"text": "...", "confidence": N, "bbox": {...}, "low_confidence": bool}.
    """
    soup = BeautifulSoup(html, "html.parser")

    image_size: list[int] = [0, 0]
    page_div = soup.find(class_="ocr_page")
    if page_div:
        m = re.search(r'\bbbox 0 0 (\d+) (\d+)', page_div.get("title", ""))
        if m:
            image_size = [int(m[1]), int(m[2])]

    blocks: list[dict] = []
    all_confs: list[float] = []

    # ocr_carea is the standard block class; some Tesseract builds use ocr_block
    for carea in soup.find_all(
        lambda tag: tag.name in ("div", "span") and any(
            c in ("ocr_carea", "ocr_block") for c in (tag.get("class") or [])
        )
    ):
        block_bbox = _parse_bbox(carea.get("title", ""))
        lines: list[dict] = []

        for line_span in carea.find_all(class_="ocr_line"):
            line_title = line_span.get("title", "")
            line_bbox = _parse_bbox(line_title)
            line_metrics = _parse_line_metrics(line_title)
            words: list[dict] = []
            line_texts: list[str] = []

            for word_span in line_span.find_all(class_="ocrx_word"):
                conf = _parse_wconf(word_span.get("title", "")) or 0.0
                word_bbox = _parse_bbox(word_span.get("title", ""))
                text = word_span.get_text(strip=True)
                if not text:
                    continue
                all_confs.append(conf)
                words.append({
                    "text": text,
                    "confidence": round(conf, 1),
                    "bbox": word_bbox,
                    "low_confidence": conf < 50,
                })
                line_texts.append(text)

            if words:
                line_record: dict = {
                    "text": " ".join(line_texts),
                    "bbox": line_bbox,
                    "words": words,
                }
                # Spread Tesseract line metrics in — x_size, baseline, descenders/ascenders
                line_record.update(line_metrics)
                lines.append(line_record)

        if lines:
            blocks.append({"bbox": block_bbox, "lines": lines})

    mean_conf = round(float(np.mean(all_confs)), 1) if all_confs else 0.0
    return mean_conf, blocks, image_size


def ocr_page(jpeg_path: Path, *, force: bool = False) -> dict | None:
    """OCR one page with locked config; return sidecar dict (or None if skipped).

    Writes sidecar alongside jpeg_path as page_NNNN.oss-tesseract.json.
    Returns None if sidecar already valid and force=False.
    """
    sidecar_path = jpeg_path.with_name(jpeg_path.stem + ".oss-tesseract.json")
    if not force and should_skip_page(sidecar_path):
        return None

    t0 = time.time()
    html = _run_tesseract_hocr(jpeg_path)
    confidence_mean, blocks, image_size = _parse_hocr(html)
    elapsed = time.time() - t0

    # Persist the raw hOCR alongside the parsed JSON. Costs ~1-2 MB per page
    # but preserves every field Tesseract emits — line metrics, paragraph
    # structure, ocr_textfloat / ocr_separator regions — so a future enrichment
    # can re-parse from disk without re-OCRing.
    hocr_path = jpeg_path.with_name(jpeg_path.stem + ".oss-tesseract.hocr")
    hocr_tmp = hocr_path.with_suffix(".hocr.tmp")
    hocr_tmp.write_text(html, encoding="utf-8")
    os.replace(hocr_tmp, hocr_path)

    raw_lines: list[str] = []
    for block in blocks:
        for line in block["lines"]:
            raw_lines.append(line["text"])
        raw_lines.append("")
    raw_text = "\n".join(raw_lines).rstrip()

    data = {
        "format_version": 1,
        "coordinate_unit": "pixel",
        "coordinate_frame": "source_image",
        "page": int(jpeg_path.stem.split("_")[-1]),
        "engine": ENGINE_ALIAS,
        "engine_version": ENGINE_VERSION,
        "language_packs": [LOCKED_LANG],
        "psm_mode": LOCKED_PSM,
        "preprocessing": LOCKED_PREPROCESSING,
        "config_hash": CONFIG_HASH,
        "run_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "image_size": image_size,
        "page_rotation": 0.0,  # Tesseract PSM=1 path does not run OSD; use --psm 0 to capture
        "confidence_mean": confidence_mean,
        "processing_time_seconds": round(elapsed, 2),
        "raw_text": raw_text,
        "blocks": blocks,
    }
    write_sidecar(sidecar_path, data)
    return data


# ---------------------------------------------------------------------------
# Volume run
# ---------------------------------------------------------------------------

def ocr_volume(volume_num: int, *, dry_run: bool = False, force: bool = False) -> dict:
    """OCR all pages in a volume; return summary dict."""
    vol_dir = RAW_PAGES / f"vol_{volume_num:02d}"
    if not vol_dir.exists():
        raise FileNotFoundError(f"Vol dir not found: {vol_dir}")

    pages = volume_image_paths(vol_dir, include_front_back=True)
    total = len(pages)
    processed = skipped = failed = 0

    for i, jpeg in enumerate(pages, 1):
        page_num = int(jpeg.stem.split("_")[-1])
        sidecar = jpeg.with_suffix("").with_name(jpeg.stem + ".oss-tesseract.json")

        if not force and should_skip_page(sidecar):
            skipped += 1
            logger.info("[vol_%02d][tesseract] page %04d/%04d -- skipped (sidecar ok)",
                        volume_num, page_num, total)
            continue

        if dry_run:
            logger.info("[vol_%02d][tesseract] page %04d/%04d -- dry-run",
                        volume_num, page_num, total)
            continue

        try:
            t0 = time.time()
            result = ocr_page(jpeg, force=force)
            elapsed = time.time() - t0
            conf = result["confidence_mean"] if result else 0.0
            logger.info("[vol_%02d][tesseract] page %04d/%04d -- %.1fs -- confidence mean: %.1f",
                        volume_num, page_num, total, elapsed, conf)
            processed += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("[vol_%02d][tesseract] page %04d/%04d -- ERROR: %s",
                         volume_num, page_num, total, exc)
            failed += 1

    return {
        "volume": volume_num,
        "total_pages": total,
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
    }


# ---------------------------------------------------------------------------
# Volume assembly
# ---------------------------------------------------------------------------

def assemble_volume_json(
    volume_num: int,
    *,
    vol_dir: Path | None = None,
    out_dir: Path | None = None,
) -> Path:
    """Read per-page sidecars and write assembled per-volume JSON.

    Output: <out_dir>/vol_NN.json (default out_dir = OUTPUT_DIR).
    Caller must satisfy the writer-manifest gate before committing the output.
    """
    if vol_dir is None:
        vol_dir = RAW_PAGES / f"vol_{volume_num:02d}"
    if out_dir is None:
        out_dir = OUTPUT_DIR

    if not vol_dir.exists():
        raise FileNotFoundError(f"Vol dir not found: {vol_dir}")

    assembly = volume_assembly_records(vol_dir, "oss-tesseract.json")
    if not assembly:
        raise ValueError(f"No oss-tesseract sidecar files found in {vol_dir}")

    pages = []
    all_confs: list[float] = []
    for page_native_id, sidecar, canonical_page in assembly:
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping corrupt sidecar %s: %s", sidecar.name, exc)
            continue
        conf = float(data.get("confidence_mean", 0.0))
        if conf > 0.0:
            all_confs.append(conf)
        # raw_text (new format) or text (old thin sidecars / test fixtures)
        text = data.get("raw_text") or data.get("text", "")
        pages.append({
            "page": canonical_page,
            "page_native_id": page_native_id,
            "confidence_mean": conf,
            "word_count": len(text.split()) if text else 0,
            "text": text,
        })

    volume_conf = round(float(np.mean(all_confs)), 1) if all_confs else 0.0
    output = {
        "rendering_id": "oss-tesseract/schaff/encyclopedia/1908-1914/v1",
        "volume": volume_num,
        "assembled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "engine_alias": ENGINE_ALIAS,
        "engine_version": ENGINE_VERSION,
        "language_packs": [LOCKED_LANG],
        "psm_mode": LOCKED_PSM,
        "preprocessing": LOCKED_PREPROCESSING,
        "config_hash": CONFIG_HASH,
        "page_count": len(pages),
        "pages_with_data": len(all_confs),
        "confidence_mean": volume_conf,
        "pages": pages,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"vol_{volume_num:02d}.json"
    write_sidecar(out_path, output)
    logger.info(
        "Assembled vol %02d: %d pages (%d with data), mean conf %.1f -> %s",
        volume_num, len(pages), len(all_confs), volume_conf, out_path,
    )
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Tesseract OCR on Schaff-Herzog IA pages (locked config)."
    )
    parser.add_argument("--volume", type=int, required=True, help="Volume number (1-12)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print planned operations; do not write any files")
    parser.add_argument("--force", action="store_true",
                        help="Re-OCR pages even when valid sidecar already exists")
    parser.add_argument("--assemble", action="store_true",
                        help="Assemble per-page sidecars into per-volume JSON (run after OCR completes)")
    args = parser.parse_args()

    _setup_logging()
    logger.info("local_schaff_tesseract: vol=%d dry_run=%s force=%s assemble=%s",
                args.volume, args.dry_run, args.force, args.assemble)

    if args.assemble:
        out_path = assemble_volume_json(args.volume)
        logger.info("Assembly complete: %s", out_path)
    else:
        summary = ocr_volume(args.volume, dry_run=args.dry_run, force=args.force)
        logger.info("Done: %s", summary)


if __name__ == "__main__":
    main()
