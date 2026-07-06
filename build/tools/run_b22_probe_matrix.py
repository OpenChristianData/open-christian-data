"""B2.2 Probe matrix — Tesseract + cloud OCR on 8 probe pages.

Runs all required Tesseract preprocessing x PSM combinations and cloud OCR runs.
Writes per-page sidecars to the gitignored raw/ directory.
Prints a results table and decision lock summary.

Usage:
    py -3 build/tools/run_b22_probe_matrix.py
    py -3 build/tools/run_b22_probe_matrix.py --tesseract-only
    py -3 build/tools/run_b22_probe_matrix.py --cloud-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent
RAW_PAGES = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
QUOTA_STATE = REPO_ROOT / "build" / "tools" / "quota_state.json"
QUOTA_POLICY = REPO_ROOT / "build" / "tools" / "quota_policy.json"
SECRETS = REPO_ROOT / "secrets"
DJVU_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog"

TESSERACT_CMD = os.environ.get(
    "TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

PROBE_PAGES = [
    {"vol": 3, "page": 75,  "label": "random-seed42"},
    {"vol": 3, "page": 100, "label": "entry-dense"},
    {"vol": 3, "page": 164, "label": "random-seed42"},
    {"vol": 3, "page": 300, "label": "random-seed42"},
    {"vol": 3, "page": 331, "label": "random-seed42"},
    {"vol": 4, "page": 480, "label": "bibliography-heavy"},  # D3: substituted 600->480
    {"vol": 5, "page": 350, "label": "column-edge"},
    {"vol": 7, "page": 200, "label": "greek-latin-heavy"},
]

PREPROCESSING_VARIANTS = ["raw", "deskew", "deskew+sauvola", "deskew+denoise"]
PSM_MODES = [1, 3, "split+4"]
LANGS = ["eng", "eng+lat"]

# WER biblio sample: vol 4 page 480 (substituted for page 600 per D3 deviation)
WER_VOL = 4
WER_PAGE = 480
WER_DJVU = DJVU_DIR / "04.NewSchaffHerzogEncycReligKnowl.BibliogApend.v1-4.v4.Jackson.Sherman.Gilmore.1909._djvu.txt"


# ---------------------------------------------------------------------------
# Preprocessing helpers
# ---------------------------------------------------------------------------

def deskew(img_gray: np.ndarray) -> np.ndarray:
    """Detect and correct skew using Hough line transform. Max correction +-3 degrees."""
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
    corrected = cv2.warpAffine(img_gray, M, (w, h), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_REPLICATE)
    return corrected


def sauvola_threshold(img_gray: np.ndarray, window: int = 25, k: float = 0.2) -> np.ndarray:
    """Sauvola adaptive threshold. Returns binary uint8 array (0=background, 255=ink)."""
    from skimage.filters import threshold_sauvola
    thresh = threshold_sauvola(img_gray, window_size=window, k=k)
    binary = (img_gray < thresh).astype(np.uint8) * 255
    return binary


def apply_preprocessing(jpeg_path: Path, variant: str) -> Path:
    """Apply preprocessing variant to a JPEG. Returns path to temp file.

    The returned file must be deleted by the caller when done.
    variant: "raw" | "deskew" | "deskew+sauvola" | "deskew+denoise"
    """
    if variant == "raw":
        return jpeg_path  # no temp file needed

    import cv2

    img = cv2.imread(str(jpeg_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"Could not read image: {jpeg_path}")

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


def split_image_halves(jpeg_path: Path) -> tuple[Path, Path]:
    """Split image at vertical midpoint. Returns (left_tmp, right_tmp)."""
    import cv2
    img = cv2.imread(str(jpeg_path), cv2.IMREAD_GRAYSCALE)
    h, w = img.shape
    mid = w // 2
    left = img[:, :mid]
    right = img[:, mid:]
    lt = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    lt.close()
    rt = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    rt.close()
    cv2.imwrite(lt.name, left)
    cv2.imwrite(rt.name, right)
    return Path(lt.name), Path(rt.name)


# ---------------------------------------------------------------------------
# Tesseract runner
# ---------------------------------------------------------------------------

def run_tesseract_tsv(img_path: Path, lang: str, psm: int) -> list[dict]:
    """Run Tesseract in TSV mode. Returns list of word dicts with conf, text."""
    with tempfile.NamedTemporaryFile(suffix="", delete=False) as t:
        base = t.name
    try:
        cmd = [
            TESSERACT_CMD,
            str(img_path),
            base,
            "-l", lang,
            f"--psm", str(psm),
            "tsv",
        ]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        tsv_path = Path(base + ".tsv")
        rows = []
        if tsv_path.exists():
            lines = tsv_path.read_text(encoding="utf-8").splitlines()
            if len(lines) > 1:
                headers = lines[0].split("\t")
                for line in lines[1:]:
                    parts = line.split("\t")
                    if len(parts) == len(headers):
                        d = dict(zip(headers, parts))
                        rows.append(d)
            tsv_path.unlink(missing_ok=True)
        return rows
    finally:
        for ext in [".tsv", ".txt", ""]:
            p = Path(base + ext)
            p.unlink(missing_ok=True)


def run_tesseract_text(img_path: Path, lang: str, psm: int) -> str:
    """Run Tesseract, return plain text output."""
    with tempfile.NamedTemporaryFile(suffix="", delete=False) as t:
        base = t.name
    try:
        cmd = [
            TESSERACT_CMD,
            str(img_path),
            base,
            "-l", lang,
            f"--psm", str(psm),
            "txt",
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
        txt_path = Path(base + ".txt")
        text = txt_path.read_text(encoding="utf-8", errors="replace") if txt_path.exists() else ""
        txt_path.unlink(missing_ok=True)
        return text
    finally:
        for ext in [".txt", ""]:
            p = Path(base + ext)
            p.unlink(missing_ok=True)


def tesseract_confidence(tsv_rows: list[dict]) -> tuple[float, list[dict]]:
    """Compute mean word confidence from TSV rows. Returns (mean, word_list)."""
    words = []
    confs = []
    for row in tsv_rows:
        try:
            conf = float(row.get("conf", -1))
        except (ValueError, TypeError):
            continue
        text = row.get("text", "").strip()
        if conf >= 0 and text:
            confs.append(conf)
            words.append({"text": text, "conf": round(conf, 1),
                          "low_confidence": conf < 50})
    mean = float(np.mean(confs)) if confs else 0.0
    return mean, words


# ---------------------------------------------------------------------------
# Reading order check (heuristic)
# ---------------------------------------------------------------------------

def check_reading_order(text: str) -> str:
    """Heuristic check for two-column reading order.

    Looks for ALL-CAPS headword tokens which should be alphabetically ordered
    if column reading order is correct (left-then-right in an alphabetical encyclopedia).

    Returns: "correct" | "incorrect" | "N/A" (insufficient headwords)
    """
    lines = text.splitlines()
    headwords = []
    for line in lines:
        stripped = line.strip()
        # Look for lines that are all-caps with >= 4 alpha chars (article headings)
        if len(stripped) >= 4 and stripped == stripped.upper():
            alpha = sum(1 for c in stripped if c.isalpha())
            if alpha >= 4 and not re.match(r"^\d", stripped):
                # Extract first word as headword
                first_word = stripped.split()[0] if stripped.split() else ""
                if len(first_word) >= 3:
                    headwords.append(first_word.rstrip(",:;"))
    if len(headwords) < 3:
        return "N/A"
    # Check alphabetical order - should be monotonically non-decreasing
    out_of_order = 0
    for i in range(1, len(headwords)):
        if headwords[i] < headwords[i - 1]:
            out_of_order += 1
    # Allow one or two inversions (OCR artifacts, running headers)
    order_ok = out_of_order <= 1
    return "correct" if order_ok else "incorrect"


# ---------------------------------------------------------------------------
# IA OCR text extraction for WER
# ---------------------------------------------------------------------------

def extract_ia_ocr_page(djvu_path: Path, target_page: int) -> str:
    """Extract approximately 200 words from the target page of a DjVu text file.

    DjVu text files use form-feed characters (0x0C) between pages.
    """
    if not djvu_path.exists():
        return ""
    content = djvu_path.read_text(encoding="utf-8", errors="replace")
    pages = content.split("\x0c")
    # DjVu pages are 0-indexed; vol 4 leaf IDs start from page 1 but the
    # form-feed split produces one entry per "page chunk". Use target_page - 1.
    idx = target_page - 1
    if idx < 0 or idx >= len(pages):
        # Try nearby pages
        idx = min(idx, len(pages) - 1)
    page_text = pages[idx] if idx < len(pages) else ""
    # Return first 200 words
    words = page_text.split()
    return " ".join(words[:200])


def compute_wer(ref: str, hyp: str) -> float:
    """Compute word error rate: insertions+deletions+substitutions / ref_word_count."""
    ref_words = ref.lower().split()
    hyp_words = hyp.lower().split()
    if not ref_words:
        return 0.0
    # Simple Levenshtein at word level (DP)
    n, m = len(ref_words), len(hyp_words)
    dp = list(range(m + 1))
    for i in range(1, n + 1):
        prev = dp[:]
        dp[0] = i
        for j in range(1, m + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                dp[j] = prev[j - 1]
            else:
                dp[j] = 1 + min(prev[j], dp[j - 1], prev[j - 1])
    return dp[m] / n


# ---------------------------------------------------------------------------
# Sidecar writer
# ---------------------------------------------------------------------------

def write_sidecar(sidecar_path: Path, data: dict) -> None:
    """Write sidecar JSON atomically."""
    import os as _os
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = sidecar_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _os.replace(tmp, sidecar_path)


# ---------------------------------------------------------------------------
# Cloud OCR
# ---------------------------------------------------------------------------

def load_quota_state() -> dict:
    if QUOTA_STATE.exists():
        return json.loads(QUOTA_STATE.read_text(encoding="utf-8"))
    return {}


def save_quota_state(state: dict) -> None:
    import os as _os
    QUOTA_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUOTA_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    _os.replace(tmp, QUOTA_STATE)


def load_quota_policy() -> dict:
    return json.loads(QUOTA_POLICY.read_text(encoding="utf-8"))


def quota_ok(state: dict, policy: dict, provider: str) -> bool:
    """Return True if the provider has remaining quota for this month."""
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    pstate = state.get(provider, {})
    if pstate.get("month") != current_month:
        return True  # New month, reset
    used = pstate.get("pages_used_this_month", 0)
    ppolicy = policy.get("providers", {}).get(provider, {})
    cap = ppolicy.get("monthly_soft_cap", 0)
    return used < cap


def increment_quota(state: dict, provider: str, count: int = 1) -> dict:
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    pstate = state.setdefault(provider, {})
    if pstate.get("month") != current_month:
        pstate["pages_used_this_month"] = 0
        pstate["month"] = current_month
    pstate["pages_used_this_month"] = pstate.get("pages_used_this_month", 0) + count
    return state


def gcv_ocr(jpeg_path: Path, state: dict, policy: dict) -> dict | None:
    """Run Google Cloud Vision on a JPEG. Returns text or None on quota/error."""
    import json as json_mod
    provider = "google_cloud_vision"
    if not quota_ok(state, policy, provider):
        print(f"  [GCV] quota cap reached, skipping {jpeg_path.name}")
        return None
    sa_path = SECRETS / "gcp-vision-sa.json"
    if not sa_path.exists():
        print("  [GCV] service account JSON not found")
        return None
    try:
        from google.cloud import vision
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(
            str(sa_path),
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        client = vision.ImageAnnotatorClient(credentials=creds)
        with open(jpeg_path, "rb") as f:
            content = f.read()
        image = vision.Image(content=content)
        # Increment quota BEFORE the call
        increment_quota(state, provider)
        save_quota_state(state)
        response = client.document_text_detection(image=image)
        if response.error.message:
            print(f"  [GCV] API error: {response.error.message}")
            return None
        full_text = response.full_text_annotation.text
        # Compute mean confidence (per word)
        word_confs = []
        for page in response.full_text_annotation.pages:
            for block in page.blocks:
                for para in block.paragraphs:
                    for word in para.words:
                        conf = getattr(word, "confidence", None)
                        if conf is not None:
                            word_confs.append(conf * 100)
        mean_conf = float(np.mean(word_confs)) if word_confs else 0.0
        return {
            "engine": "google-cloud-vision",
            "engine_version": "v1",
            "text": full_text,
            "confidence_mean": round(mean_conf, 1),
        }
    except Exception as e:
        print(f"  [GCV] error: {e}")
        return None


def textract_ocr(jpeg_path: Path, state: dict, policy: dict) -> dict | None:
    """Run AWS Textract on a JPEG."""
    import base64
    provider = "aws_textract"
    if not quota_ok(state, policy, provider):
        print(f"  [Textract] quota cap reached, skipping {jpeg_path.name}")
        return None
    # Check 90-day free-tier expiry
    pstate = state.get(provider, {})
    first_used = pstate.get("first_used_date")
    if first_used:
        from datetime import date
        first_dt = date.fromisoformat(first_used)
        if (date.today() - first_dt).days > 90:
            print(f"  [Textract] 90-day free tier expired since {first_used}")
            return None
    env_path = SECRETS / "aws-textract.env"
    if not env_path.exists():
        print("  [Textract] env file not found")
        return None
    try:
        # Load env vars from file
        env_vars = {}
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_vars[k.strip()] = v.strip().strip('"')
        import boto3
        client = boto3.client(
            "textract",
            region_name=env_vars.get("AWS_DEFAULT_REGION", "us-east-1"),
            aws_access_key_id=env_vars.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=env_vars.get("AWS_SECRET_ACCESS_KEY"),
        )
        with open(jpeg_path, "rb") as f:
            image_bytes = f.read()
        # Increment quota BEFORE the call
        increment_quota(state, provider)
        save_quota_state(state)
        response = client.detect_document_text(
            Document={"Bytes": image_bytes}
        )
        blocks = response.get("Blocks", [])
        lines = [b["Text"] for b in blocks if b["BlockType"] == "LINE"]
        word_confs = [b.get("Confidence", 0) for b in blocks if b["BlockType"] == "WORD"]
        mean_conf = float(np.mean(word_confs)) if word_confs else 0.0
        return {
            "engine": "aws-textract",
            "engine_version": "detect-document-text-v1",
            "text": "\n".join(lines),
            "confidence_mean": round(mean_conf, 1),
        }
    except Exception as e:
        print(f"  [Textract] error: {e}")
        return None


def azure_ocr(jpeg_path: Path, state: dict, policy: dict) -> dict | None:
    """Run Azure AI Vision Read on a JPEG."""
    provider = "azure_ai_vision"
    if not quota_ok(state, policy, provider):
        print(f"  [Azure] quota cap reached, skipping {jpeg_path.name}")
        return None
    env_path = SECRETS / "azure-vision.env"
    if not env_path.exists():
        print("  [Azure] env file not found")
        return None
    try:
        env_vars = {}
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_vars[k.strip()] = v.strip().strip('"')
        endpoint = env_vars.get("AZURE_VISION_ENDPOINT", "")
        key = env_vars.get("AZURE_VISION_KEY", "")
        if not endpoint or not key:
            print("  [Azure] missing endpoint/key in env file")
            return None
        # Use Read API v3.2
        import urllib.request
        import urllib.error
        with open(jpeg_path, "rb") as f:
            img_bytes = f.read()
        url = endpoint.rstrip("/") + "/vision/v3.2/read/syncAnalyze"
        req = urllib.request.Request(
            url,
            data=img_bytes,
            headers={
                "Ocp-Apim-Subscription-Key": key,
                "Content-Type": "application/octet-stream",
            },
            method="POST",
        )
        # Increment quota BEFORE the call
        increment_quota(state, provider)
        save_quota_state(state)
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        # Extract text and confidence
        lines = []
        word_confs = []
        for read_result in result.get("analyzeResult", {}).get("readResults", []):
            for line in read_result.get("lines", []):
                lines.append(line.get("text", ""))
                for word in line.get("words", []):
                    conf = word.get("confidence", None)
                    if conf is not None:
                        word_confs.append(float(conf) * 100)
        mean_conf = float(np.mean(word_confs)) if word_confs else 0.0
        api_version = result.get("modelVersion", "2024-02-01")
        return {
            "engine": "azure-ai-vision",
            "engine_version": api_version,
            "text": "\n".join(lines),
            "confidence_mean": round(mean_conf, 1),
        }
    except Exception as e:
        print(f"  [Azure] error: {e}")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="B2.2 Probe Matrix")
    parser.add_argument("--tesseract-only", action="store_true")
    parser.add_argument("--cloud-only", action="store_true")
    parser.add_argument("--skip-eng-lat", action="store_true",
                        help="Skip the eng+lat WER comparison run")
    args = parser.parse_args()

    run_tesseract = not args.cloud_only
    run_cloud = not args.tesseract_only

    print("=== B2.2 Probe Matrix ===")
    print(f"Tesseract: {TESSERACT_CMD}")
    print(f"Pages: {len(PROBE_PAGES)}")
    print()

    # IA OCR reference text for WER
    ia_ref_text = extract_ia_ocr_page(WER_DJVU, WER_PAGE)
    if ia_ref_text:
        print(f"IA OCR reference: {len(ia_ref_text.split())} words from vol {WER_VOL} page {WER_PAGE}")
    else:
        print(f"WARNING: Could not extract IA OCR reference text from {WER_DJVU}")

    # -------------------------------------------------------------------------
    # Tesseract probe matrix
    # -------------------------------------------------------------------------
    # Results: keyed by (preprocessing, psm, lang) -> {"mean_conf": float, "order": [...], "wer": float}
    tess_results: dict[tuple, dict[str, Any]] = {}

    if run_tesseract:
        print("\n--- Tesseract Probe Matrix ---")
        print("All pages are mode L -> all 4 preprocessing variants apply")
        print()

        total_runs = len(PREPROCESSING_VARIANTS) * len(PSM_MODES) * len(PROBE_PAGES)
        run_num = 0

        for prep in PREPROCESSING_VARIANTS:
            for psm in PSM_MODES:
                key = (prep, psm, "eng")
                page_confs: list[float] = []
                page_orders: list[str] = []
                page_wer_hyp = ""

                for probe in PROBE_PAGES:
                    vol = probe["vol"]
                    page = probe["page"]
                    vol_dir = RAW_PAGES / f"vol_{vol:02d}"
                    jpeg = vol_dir / f"page_{page:04d}.jpg"
                    if not jpeg.exists():
                        print(f"  MISSING: {jpeg}")
                        continue

                    run_num += 1
                    print(f"  [{run_num}/{total_runs}] prep={prep} psm={psm} lang=eng vol{vol:02d} p{page:04d}...",
                          end="", flush=True)
                    t0 = time.time()

                    # Determine sidecar path
                    psm_str = str(psm).replace("+", "p")
                    sidecar = vol_dir / f"page_{page:04d}.{prep}.psm{psm_str}.eng.tess.json"

                    if sidecar.exists():
                        # Load cached result
                        cached = json.loads(sidecar.read_text(encoding="utf-8"))
                        mean_c = cached["confidence_mean"]
                        text = cached["raw_text"]
                        elapsed = time.time() - t0
                        print(f" [cached] conf={mean_c:.1f}")
                    else:
                        # Apply preprocessing
                        prep_temps = []
                        try:
                            if psm == "split+4":
                                # For split+4: apply preprocessing to full image, then split
                                processed = apply_preprocessing(jpeg, prep)
                                if processed != jpeg:
                                    prep_temps.append(processed)
                                left_tmp, right_tmp = split_image_halves(processed)
                                prep_temps += [left_tmp, right_tmp]
                                # Run PSM 4 on each half
                                left_rows = run_tesseract_tsv(left_tmp, "eng", 4)
                                right_rows = run_tesseract_tsv(right_tmp, "eng", 4)
                                left_text = run_tesseract_text(left_tmp, "eng", 4)
                                right_text = run_tesseract_text(right_tmp, "eng", 4)
                                combined_rows = left_rows + right_rows
                                text = left_text + "\n" + right_text
                                mean_c, words = tesseract_confidence(combined_rows)
                            else:
                                processed = apply_preprocessing(jpeg, prep)
                                if processed != jpeg:
                                    prep_temps.append(processed)
                                rows = run_tesseract_tsv(processed, "eng", psm)
                                text = run_tesseract_text(processed, "eng", psm)
                                mean_c, words = tesseract_confidence(rows)
                        finally:
                            for tmp in prep_temps:
                                try:
                                    tmp.unlink(missing_ok=True)
                                except Exception:
                                    pass

                        elapsed = time.time() - t0
                        print(f" {elapsed:.1f}s conf={mean_c:.1f}")

                        # Write sidecar
                        sidecar_data = {
                            "engine_alias": "oss-tesseract",
                            "engine_version": "5.5.0.20241111",
                            "language_packs": ["eng"],
                            "psm_mode": psm,
                            "preprocessing": prep,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "confidence_mean": round(mean_c, 1),
                            "raw_text": text,
                            "words": words if isinstance(words, list) else [],
                        }
                        write_sidecar(sidecar, sidecar_data)

                    page_confs.append(mean_c)
                    order = check_reading_order(text)
                    page_orders.append(order)

                    # Collect WER hypothesis from bibliography page
                    if vol == WER_VOL and page == WER_PAGE:
                        words_200 = " ".join(text.split()[:200])
                        page_wer_hyp = words_200

                # Compute WER for this combination
                wer = compute_wer(ia_ref_text, page_wer_hyp) if ia_ref_text else 0.0
                mean_conf = float(np.mean(page_confs)) if page_confs else 0.0
                correct_count = page_orders.count("correct")
                na_count = page_orders.count("N/A")

                tess_results[key] = {
                    "mean_conf": round(mean_conf, 1),
                    "order_results": page_orders,
                    "correct_count": correct_count,
                    "na_count": na_count,
                    "wer": round(wer * 100, 2),
                }

        print()
        print("--- Tesseract Results Table ---")
        print(f"{'Prep':<22} {'PSM':<8} {'Lang':<8} {'MeanConf':>9} {'Order':>10} {'WER%':>7}")
        print("-" * 70)
        for (prep, psm, lang), r in sorted(tess_results.items(),
                                            key=lambda kv: (kv[0][0], str(kv[0][1]), kv[0][2])):
            order_str = f"{r['correct_count']}/{len(PROBE_PAGES) - r['na_count']}+{r['na_count']}N/A"
            print(f"{prep:<22} {str(psm):<8} {lang:<8} {r['mean_conf']:>9.1f} {order_str:>10} {r['wer']:>7.2f}")

        # -----------------------------------------------------------------------
        # Apply Decision rules
        # -----------------------------------------------------------------------
        print()
        print("--- Decision Rule Application ---")

        # Decision 2: PSM lock - find best PSM using correct reading order >= 7/8
        # For PSM 1, check across all preprocessing variants
        def best_order_for_psm(psm_val):
            best = 0
            best_prep = None
            for (prep, psm, lang), r in tess_results.items():
                if psm == psm_val and lang == "eng":
                    effective_denom = len(PROBE_PAGES) - r["na_count"]
                    if effective_denom > 0 and r["correct_count"] >= best:
                        best = r["correct_count"]
                        best_prep = prep
            return best, best_prep

        psm1_correct, psm1_prep = best_order_for_psm(1)
        psm3_correct, psm3_prep = best_order_for_psm(3)
        psm_split4_correct, psm_split4_prep = best_order_for_psm("split+4")

        print(f"D2 PSM check:")
        print(f"  PSM 1 best: {psm1_correct}/8 correct order (with {psm1_prep})")
        print(f"  PSM 3 best: {psm3_correct}/8 correct order")
        print(f"  PSM split+4 best: {psm_split4_correct}/8 correct order")

        if psm1_correct >= 7:
            locked_psm = 1
            print(f"  LOCK: PSM 1 (>= 7/8 pages correct)")
        elif psm_split4_correct >= 7:
            locked_psm = "split+4"
            print(f"  LOCK: split+4 (PSM 1 failed, split+4 meets threshold)")
        else:
            locked_psm = 1  # Default; escalation would be needed
            print(f"  WARNING: Neither PSM option meets 7/8 threshold. Using PSM 1. ESCALATE.")

        # Decision 4: Preprocessing - find variant with highest mean confidence at locked PSM
        prep_confs = {}
        for (prep, psm, lang), r in tess_results.items():
            if psm == locked_psm and lang == "eng":
                prep_confs[prep] = r["mean_conf"]

        print(f"\nD4 Preprocessing check (PSM={locked_psm}):")
        for prep, c in sorted(prep_confs.items(), key=lambda x: -x[1]):
            print(f"  {prep:<22} conf={c:.1f}")

        best_prep_conf = max(prep_confs.values()) if prep_confs else 0.0
        # Prefer simpler within 2 confidence points
        PREP_ORDER = {"raw": 0, "deskew": 1, "deskew+sauvola": 2, "deskew+denoise": 3}
        candidates = [(p, c) for p, c in prep_confs.items()
                      if best_prep_conf - c <= 2.0]
        candidates.sort(key=lambda x: PREP_ORDER.get(x[0], 99))
        locked_prep = candidates[0][0] if candidates else "raw"

        print(f"  LOCK: {locked_prep} (highest conf or simpler within 2pt)")

        if best_prep_conf < 70.0:
            print(f"  WARNING: Best conf {best_prep_conf:.1f} < 70 threshold. ESCALATE.")

        # Decision 3: Language model - run eng+lat on best (prep, psm) combo
        print()
        if not args.skip_eng_lat:
            print("--- Decision 3: eng vs eng+lat WER comparison ---")
            eng_wer = tess_results.get((locked_prep, locked_psm, "eng"), {}).get("wer", 0.0)

            # Run eng+lat
            engl_page_confs = []
            engl_hyp = ""
            engl_orders = []
            for probe in PROBE_PAGES:
                vol, page = probe["vol"], probe["page"]
                vol_dir = RAW_PAGES / f"vol_{vol:02d}"
                jpeg = vol_dir / f"page_{page:04d}.jpg"
                if not jpeg.exists():
                    continue
                psm_str = str(locked_psm).replace("+", "p")
                sidecar = vol_dir / f"page_{page:04d}.{locked_prep}.psm{psm_str}.eng+lat.tess.json"
                print(f"  eng+lat vol{vol:02d} p{page:04d}...", end="", flush=True)
                t0 = time.time()
                if sidecar.exists():
                    cached = json.loads(sidecar.read_text(encoding="utf-8"))
                    mean_c = cached["confidence_mean"]
                    text = cached["raw_text"]
                    print(f" [cached] conf={mean_c:.1f}")
                else:
                    prep_temps = []
                    try:
                        if locked_psm == "split+4":
                            processed = apply_preprocessing(jpeg, locked_prep)
                            if processed != jpeg:
                                prep_temps.append(processed)
                            lt, rt = split_image_halves(processed)
                            prep_temps += [lt, rt]
                            lr = run_tesseract_tsv(lt, "eng+lat", 4)
                            rr = run_tesseract_tsv(rt, "eng+lat", 4)
                            lt2 = run_tesseract_text(lt, "eng+lat", 4)
                            rt2 = run_tesseract_text(rt, "eng+lat", 4)
                            text = lt2 + "\n" + rt2
                            mean_c, words = tesseract_confidence(lr + rr)
                        else:
                            processed = apply_preprocessing(jpeg, locked_prep)
                            if processed != jpeg:
                                prep_temps.append(processed)
                            rows = run_tesseract_tsv(processed, "eng+lat", locked_psm)
                            text = run_tesseract_text(processed, "eng+lat", locked_psm)
                            mean_c, words = tesseract_confidence(rows)
                    finally:
                        for tmp in prep_temps:
                            tmp.unlink(missing_ok=True)
                    elapsed = time.time() - t0
                    print(f" {elapsed:.1f}s conf={mean_c:.1f}")
                    sidecar_data = {
                        "engine_alias": "oss-tesseract",
                        "engine_version": "5.5.0.20241111",
                        "language_packs": ["eng", "lat"],
                        "psm_mode": locked_psm,
                        "preprocessing": locked_prep,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "confidence_mean": round(mean_c, 1),
                        "raw_text": text,
                        "words": words if isinstance(words, list) else [],
                    }
                    write_sidecar(sidecar, sidecar_data)
                engl_page_confs.append(mean_c)
                if vol == WER_VOL and page == WER_PAGE:
                    engl_hyp = " ".join(text.split()[:200])
                order = check_reading_order(text)
                engl_orders.append(order)

            engl_wer = compute_wer(ia_ref_text, engl_hyp) * 100 if ia_ref_text else 0.0
            wer_delta = eng_wer - engl_wer
            print(f"\n  eng WER: {eng_wer:.2f}%")
            print(f"  eng+lat WER: {engl_wer:.2f}%")
            print(f"  Delta: {wer_delta:.2f} pp")
            if wer_delta >= 0.5:
                locked_lang = ["eng", "lat"]
                print(f"  LOCK: eng+lat (delta >= 0.5 pp)")
            else:
                locked_lang = ["eng"]
                print(f"  LOCK: eng (delta < 0.5 pp threshold)")
        else:
            locked_lang = ["eng"]
            print("  Skipped eng+lat run (--skip-eng-lat flag)")
            engl_wer = 0.0
            wer_delta = 0.0
            eng_wer = tess_results.get((locked_prep, locked_psm, "eng"), {}).get("wer", 0.0)

        # -----------------------------------------------------------------------
        # Config hash
        # -----------------------------------------------------------------------
        print()
        print("--- Config Hash ---")
        tess_version_str = "tesseract v5.5.0.20241111"
        config = {
            "engine_version": tess_version_str,
            "language_packs": locked_lang,
            "psm_mode": locked_psm if locked_psm != "split+4" else "split+4",
            "preprocessing": locked_prep,
        }
        canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
        config_hash = hashlib.sha256(canonical.encode()).hexdigest()
        print(f"  Canonical JSON: {canonical}")
        print(f"  sha256: {config_hash}")

        # D4 spot-check summary (reading order serves as a proxy spot-check)
        locked_key = (locked_prep, locked_psm, "eng")
        locked_result = tess_results.get(locked_key, {})
        locked_orders = locked_result.get("order_results", [])
        locked_conf = locked_result.get("mean_conf", 0.0)

        print()
        print("--- Summary ---")
        print(f"  Locked PSM: {locked_psm}")
        print(f"  Locked preprocessing: {locked_prep}")
        print(f"  Locked language: {locked_lang}")
        print(f"  Mean confidence (locked config, 8 pages): {locked_conf:.1f}")
        print(f"  Reading order (locked config): {locked_orders}")
        print(f"  Config hash: {config_hash}")
        print()
        print("TESSERACT_LOCKS_DONE")

        # Store locks for use in cloud section and session notes
        locks = {
            "psm": locked_psm,
            "preprocessing": locked_prep,
            "language_packs": locked_lang,
            "engine_version": tess_version_str,
            "config_hash": config_hash,
            "canonical_json": canonical,
            "mean_conf": locked_conf,
            "order_results": locked_orders,
            "eng_wer": eng_wer if ia_ref_text else None,
            "engl_wer": engl_wer if (ia_ref_text and not args.skip_eng_lat) else None,
        }

    # -------------------------------------------------------------------------
    # Cloud OCR
    # -------------------------------------------------------------------------
    if run_cloud:
        print()
        print("--- Cloud OCR on 8 probe pages ---")
        state = load_quota_state()
        policy = load_quota_policy()

        cloud_results: dict[str, list[dict]] = {
            "gcv": [],
            "textract": [],
            "azure": [],
        }

        for probe in PROBE_PAGES:
            vol, page = probe["vol"], probe["page"]
            vol_dir = RAW_PAGES / f"vol_{vol:02d}"
            jpeg = vol_dir / f"page_{page:04d}.jpg"
            if not jpeg.exists():
                print(f"  MISSING: {jpeg}")
                continue

            print(f"\n  vol{vol:02d} p{page:04d}:")

            for engine_name, runner, provider in [
                ("gcv", gcv_ocr, "google_cloud_vision"),
                ("textract", textract_ocr, "aws_textract"),
                ("azure", azure_ocr, "azure_ai_vision"),
            ]:
                sidecar = vol_dir / f"page_{page:04d}.{engine_name}.json"
                if sidecar.exists():
                    cached = json.loads(sidecar.read_text(encoding="utf-8"))
                    conf = cached.get("confidence_mean", 0.0)
                    print(f"    [{engine_name}] [cached] conf={conf:.1f}")
                    cloud_results[engine_name].append({
                        "vol": vol, "page": page,
                        "conf": conf,
                        "text": cached.get("text", ""),
                        "engine_version": cached.get("engine_version", ""),
                    })
                    continue

                print(f"    [{engine_name}]...", end="", flush=True)
                t0 = time.time()
                state = load_quota_state()  # re-load for freshness
                result = runner(jpeg, state, policy)
                elapsed = time.time() - t0
                if result:
                    print(f" {elapsed:.1f}s conf={result['confidence_mean']:.1f}")
                    sidecar_data = {
                        "engine": result["engine"],
                        "engine_version": result["engine_version"],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "confidence_mean": result["confidence_mean"],
                        "text": result["text"],
                    }
                    write_sidecar(sidecar, sidecar_data)
                    cloud_results[engine_name].append({
                        "vol": vol, "page": page,
                        "conf": result["confidence_mean"],
                        "text": result["text"],
                        "engine_version": result["engine_version"],
                    })
                    # Polite delay
                    time.sleep(2)
                else:
                    print(f" SKIPPED")
                    cloud_results[engine_name].append({
                        "vol": vol, "page": page,
                        "conf": 0.0,
                        "text": "",
                        "engine_version": "",
                        "skipped": True,
                    })

        # Cloud summary
        print()
        print("--- Cloud Results Summary ---")
        for engine_name in ["gcv", "textract", "azure"]:
            results = cloud_results[engine_name]
            done = [r for r in results if not r.get("skipped")]
            skip = [r for r in results if r.get("skipped")]
            mean_c = float(np.mean([r["conf"] for r in done])) if done else 0.0
            versions = list({r["engine_version"] for r in done if r["engine_version"]})
            print(f"  {engine_name}: {len(done)}/{len(PROBE_PAGES)} pages"
                  f" (skipped={len(skip)}) mean_conf={mean_c:.1f}"
                  f" version={versions}")

        # Final quota state
        final_state = load_quota_state()
        print()
        print("--- Quota State After Cloud Runs ---")
        for provider, pstate in final_state.items():
            print(f"  {provider}: {pstate.get('pages_used_this_month', 0)} used this month")

    print()
    print("=== B2.2 Probe Matrix Complete ===")


if __name__ == "__main__":
    main()
