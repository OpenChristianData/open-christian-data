"""Patch B2.2 sidecar files: recompute confidence using float() TSV parsing.

The initial probe run used int() to parse Tesseract TSV confidence values,
which silently returned 0 for float strings like '93.625252'.
This script re-runs Tesseract TSV on the preprocessed images for each sidecar
and updates confidence_mean and words in-place.

Usage:
    py -3 build/tools/fix_b22_confidence.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).parent.parent.parent
RAW_PAGES = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
TESSERACT_CMD = os.environ.get(
    "TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

PROBE_VOLS_PAGES = [
    (3, 75), (3, 100), (3, 164), (3, 300), (3, 331),
    (4, 480), (5, 350), (7, 200),
]

PREPROCESSING_VARIANTS = ["raw", "deskew", "deskew+sauvola", "deskew+denoise"]
PSM_MODES = [1, 3, "split+4"]


def deskew(img_gray: "np.ndarray") -> "np.ndarray":
    import cv2
    edges = cv2.Canny(img_gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)
    if lines is None:
        return img_gray
    angles = []
    for line in lines[:100]:
        rho, theta = line[0]
        angle_deg = np.degrees(theta) - 90
        if abs(angle_deg) < 3.0:
            angles.append(angle_deg)
    if not angles:
        return img_gray
    skew = float(np.median(angles))
    if abs(skew) < 0.1:
        return img_gray
    h, w = img_gray.shape
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, -skew, 1.0)
    corrected = cv2.warpAffine(
        img_gray, M, (w, h), flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )
    return corrected


def sauvola_threshold(img_gray: "np.ndarray", window: int = 25, k: float = 0.2) -> "np.ndarray":
    from skimage.filters import threshold_sauvola
    thresh = threshold_sauvola(img_gray, window_size=window, k=k)
    binary = (img_gray < thresh).astype(np.uint8) * 255
    return binary


def apply_preprocessing(jpeg_path: Path, variant: str) -> Path:
    if variant == "raw":
        return jpeg_path
    import cv2
    img = cv2.imread(str(jpeg_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"Could not read: {jpeg_path}")
    if variant in ("deskew", "deskew+sauvola", "deskew+denoise"):
        img = deskew(img)
    if variant == "deskew+sauvola":
        img = sauvola_threshold(img)
    elif variant == "deskew+denoise":
        img = cv2.medianBlur(img, 3)
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.close()
    cv2.imwrite(tmp.name, img)
    return Path(tmp.name)


def split_image_halves(jpeg_path: Path):
    import cv2
    img = cv2.imread(str(jpeg_path), cv2.IMREAD_GRAYSCALE)
    h, w = img.shape
    mid = w // 2
    left, right = img[:, :mid], img[:, mid:]
    lt = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    lt.close()
    rt = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    rt.close()
    import cv2 as _cv2
    _cv2.imwrite(lt.name, left)
    _cv2.imwrite(rt.name, right)
    return Path(lt.name), Path(rt.name)


def tsv_confidence(img_path: Path, lang: str, psm: int) -> tuple[float, list[dict]]:
    with tempfile.NamedTemporaryFile(suffix="", delete=False) as t:
        base = t.name
    try:
        cmd = [
            TESSERACT_CMD, str(img_path), base,
            "-l", lang, f"--psm", str(psm), "tsv",
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
        tsv_path = Path(base + ".tsv")
        if not tsv_path.exists():
            return 0.0, []
        lines = tsv_path.read_text(encoding="utf-8").splitlines()
        tsv_path.unlink(missing_ok=True)
        if len(lines) < 2:
            return 0.0, []
        headers = lines[0].split("\t")
        words = []
        confs = []
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) < len(headers):
                continue
            d = dict(zip(headers, parts))
            try:
                conf = float(d.get("conf", -1))
            except (ValueError, TypeError):
                continue
            text = d.get("text", "").strip()
            if conf >= 0 and text:
                confs.append(conf)
                words.append({"text": text, "conf": round(conf, 1),
                              "low_confidence": conf < 50})
        mean = float(np.mean(confs)) if confs else 0.0
        return round(mean, 1), words
    finally:
        for ext in [".tsv", ".txt", ""]:
            p = Path(base + ext)
            p.unlink(missing_ok=True)


def patch_sidecar(sidecar: Path, jpeg: Path, prep: str, psm, lang: str,
                  dry_run: bool) -> float | None:
    if not sidecar.exists():
        return None
    cached = json.loads(sidecar.read_text(encoding="utf-8"))
    if cached.get("confidence_mean", 0.0) > 0.0:
        return cached["confidence_mean"]  # Already correct

    print(f"  Patching: {sidecar.name}...", end="", flush=True)
    t0 = time.time()

    prep_temps = []
    try:
        if psm == "split+4":
            processed = apply_preprocessing(jpeg, prep)
            if processed != jpeg:
                prep_temps.append(processed)
            lt, rt = split_image_halves(processed)
            prep_temps += [lt, rt]
            lc, lw = tsv_confidence(lt, lang, 4)
            rc, rw = tsv_confidence(rt, lang, 4)
            all_confs = [lc, rc]
            all_words = lw + rw
            mean_c = round(float(np.mean([c for c in all_confs if c > 0]
                                         or [0])), 1)
            words = all_words
        else:
            processed = apply_preprocessing(jpeg, prep)
            if processed != jpeg:
                prep_temps.append(processed)
            mean_c, words = tsv_confidence(processed, lang, psm)
    finally:
        for tmp in prep_temps:
            tmp.unlink(missing_ok=True)

    elapsed = time.time() - t0
    print(f" conf={mean_c:.1f} ({len(words)} words) {elapsed:.1f}s")

    if not dry_run:
        cached["confidence_mean"] = mean_c
        cached["words"] = words
        tmp_path = sidecar.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(cached, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        import os as _os
        _os.replace(tmp_path, sidecar)

    return mean_c


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"=== Confidence Patch (dry_run={args.dry_run}) ===")

    patched = 0
    skipped = 0

    for prep in PREPROCESSING_VARIANTS:
        for psm in PSM_MODES:
            for lang in ["eng", "eng+lat"]:
                for vol, page in PROBE_VOLS_PAGES:
                    vol_dir = RAW_PAGES / f"vol_{vol:02d}"
                    jpeg = vol_dir / f"page_{page:04d}.jpg"
                    if not jpeg.exists():
                        continue
                    psm_str = str(psm).replace("+", "p")
                    lang_str = lang.replace("+", "+")
                    sidecar = vol_dir / f"page_{page:04d}.{prep}.psm{psm_str}.{lang}.tess.json"
                    if not sidecar.exists():
                        continue
                    result = patch_sidecar(sidecar, jpeg, prep, psm, lang, args.dry_run)
                    if result is not None and result > 0.0:
                        skipped += 1
                    elif result == 0.0:
                        patched += 1

    print(f"\nDone. Patched: {patched}, already-correct: {skipped}")


if __name__ == "__main__":
    main()
