"""B2.2 Decision analysis — reads existing sidecar files and applies D2/D4/D3 rules.

Reads confidence_mean and raw_text from sidecars written by run_b22_probe_matrix.py.
Run AFTER fix_b22_confidence.py has patched all sidecars.

D2: PSM lock (>=7/8 pages correct reading order)
D4: preprocessing lock (highest mean confidence across pages, prefer simpler within 2pt, must be >=70)
D3: language lock (eng vs eng+lat WER delta >=0.5pp on 200-word bibliography sample)

Usage:
    py -3 build/tools/analyze_b22_decisions.py [--skip-d3]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).parent.parent.parent
RAW_PAGES = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

PROBE_VOLS_PAGES = [
    (3, 75), (3, 100), (3, 164), (3, 300), (3, 331),
    (4, 480), (5, 350), (7, 200),
]

PREPROCESSING_VARIANTS = ["raw", "deskew", "deskew+sauvola", "deskew+denoise"]
PSM_MODES = [1, 3, "split+4"]

# WER reference: vol 4, page 480
WER_VOL = 4
WER_PAGE = 480
IA_DJVU_PATH = (
    REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog" /
    "04.NewSchaffHerzogEncycReligKnowl.BibliogApend.v1-4.v4.Jackson.Sherman.Gilmore.1909._djvu.txt"
)

# Simpler variants listed first (for D4 tiebreak — prefer simpler within 2pt)
PREPROCESSING_SIMPLICITY = {
    "raw": 0,
    "deskew": 1,
    "deskew+denoise": 2,
    "deskew+sauvola": 3,
}


def check_reading_order(text: str) -> str:
    """Return 'correct', 'incorrect', or 'N/A' based on headword order."""
    lines = text.splitlines()
    headwords = []
    for line in lines:
        stripped = line.strip()
        if len(stripped) >= 4 and stripped == stripped.upper():
            alpha = sum(1 for c in stripped if c.isalpha())
            if alpha >= 4 and not re.match(r"^\d", stripped):
                first_word = stripped.split()[0] if stripped.split() else ""
                if len(first_word) >= 3:
                    headwords.append(first_word.rstrip(",:;"))
    if len(headwords) < 3:
        return "N/A"
    out_of_order = 0
    for i in range(1, len(headwords)):
        if headwords[i] < headwords[i - 1]:
            out_of_order += 1
    return "correct" if out_of_order <= 1 else "incorrect"


def extract_ia_ocr_page(target_page: int) -> str:
    """Extract ~200 words from the target page of the DjVu text file."""
    if not IA_DJVU_PATH.exists():
        return ""
    content = IA_DJVU_PATH.read_text(encoding="utf-8", errors="replace")
    pages = content.split("\x0c")
    idx = target_page - 1
    if idx < 0 or idx >= len(pages):
        idx = min(max(idx, 0), len(pages) - 1)
    page_text = pages[idx] if idx < len(pages) else ""
    return " ".join(page_text.split()[:200])


def compute_wer(ref: str, hyp: str) -> float:
    """Word error rate (edit distance at word level)."""
    ref_words = ref.lower().split()
    hyp_words = hyp.lower().split()
    if not ref_words:
        return 0.0
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


def _apply_preprocessing(jpeg_path: Path, variant: str) -> Path:
    """Apply image preprocessing variant; returns path to processed image."""
    if variant == "raw":
        return jpeg_path
    import cv2
    img = cv2.imread(str(jpeg_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"Could not read: {jpeg_path}")
    if variant in ("deskew", "deskew+sauvola", "deskew+denoise"):
        edges = cv2.Canny(img, 50, 150, apertureSize=3)
        lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)
        if lines is not None:
            angles = []
            for line in lines[:100]:
                rho, theta = line[0]
                angle_deg = np.degrees(theta) - 90
                if abs(angle_deg) < 3.0:
                    angles.append(angle_deg)
            if angles:
                skew = float(np.median(angles))
                if abs(skew) >= 0.1:
                    h, w = img.shape
                    M = cv2.getRotationMatrix2D((w // 2, h // 2), -skew, 1.0)
                    img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC,
                                        borderMode=cv2.BORDER_REPLICATE)
    if variant == "deskew+sauvola":
        from skimage.filters import threshold_sauvola
        thresh = threshold_sauvola(img, window_size=25, k=0.2)
        img = (img < thresh).astype(np.uint8) * 255
    elif variant == "deskew+denoise":
        img = cv2.medianBlur(img, 3)
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.close()
    cv2.imwrite(tmp.name, img)
    return Path(tmp.name)


def _split_image_halves(jpeg_path: Path) -> tuple[Path, Path]:
    """Split image into left and right halves."""
    import cv2
    import tempfile
    img = cv2.imread(str(jpeg_path), cv2.IMREAD_GRAYSCALE)
    h, w = img.shape
    mid = w // 2
    lt = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    lt.close()
    rt = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    rt.close()
    cv2.imwrite(lt.name, img[:, :mid])
    cv2.imwrite(rt.name, img[:, mid:])
    return Path(lt.name), Path(rt.name)


def run_tesseract_tsv(img_path: Path, lang: str, psm: int) -> tuple[float, int]:
    """Run Tesseract TSV and return (mean_conf, word_count)."""
    with tempfile.NamedTemporaryFile(suffix="", delete=False) as t:
        base = t.name
    try:
        cmd = [TESSERACT_CMD, str(img_path), base, "-l", lang, "--psm", str(psm), "tsv"]
        subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
        tsv_path = Path(base + ".tsv")
        if not tsv_path.exists():
            return 0.0, 0
        lines = tsv_path.read_text(encoding="utf-8").splitlines()
        tsv_path.unlink(missing_ok=True)
        if len(lines) < 2:
            return 0.0, 0
        headers = lines[0].split("\t")
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
        mean = float(np.mean(confs)) if confs else 0.0
        return round(mean, 1), len(confs)
    finally:
        for ext in [".tsv", ".txt", ""]:
            p = Path(base + ext)
            p.unlink(missing_ok=True)


def run_tesseract_text(img_path: Path, lang: str, psm: int) -> str:
    """Run Tesseract text mode and return the text."""
    with tempfile.NamedTemporaryFile(suffix="", delete=False) as t:
        base = t.name
    try:
        cmd = [TESSERACT_CMD, str(img_path), base, "-l", lang, "--psm", str(psm)]
        subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
        txt_path = Path(base + ".txt")
        if not txt_path.exists():
            return ""
        text = txt_path.read_text(encoding="utf-8", errors="replace")
        txt_path.unlink(missing_ok=True)
        return text
    finally:
        for ext in [".txt", ""]:
            p = Path(base + ext)
            p.unlink(missing_ok=True)


def load_sidecars() -> dict:
    """Load all eng sidecars into a dict keyed by (prep, psm, vol, page)."""
    sidecars = {}
    for vol, page in PROBE_VOLS_PAGES:
        vol_dir = RAW_PAGES / f"vol_{vol:02d}"
        for prep in PREPROCESSING_VARIANTS:
            for psm in PSM_MODES:
                psm_str = str(psm).replace("+", "p")
                sidecar = vol_dir / f"page_{page:04d}.{prep}.psm{psm_str}.eng.tess.json"
                if sidecar.exists():
                    d = json.loads(sidecar.read_text(encoding="utf-8"))
                    sidecars[(prep, psm, vol, page)] = d
    return sidecars


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-d3", action="store_true", help="Skip D3 eng+lat WER comparison")
    args = parser.parse_args()

    print("=== B2.2 Decision Analysis ===")

    # Load IA OCR reference text
    ia_ref = extract_ia_ocr_page(WER_PAGE)
    print(f"IA OCR reference: {len(ia_ref.split())} words from vol {WER_VOL} p{WER_PAGE}")
    if not ia_ref:
        print("  WARNING: IA OCR reference not found")

    # Load sidecars
    sidecars = load_sidecars()
    print(f"Loaded {len(sidecars)} sidecars")

    # Aggregate per (prep, psm)
    # Results: (prep, psm) -> {mean_conf, correct_count, na_count, wer, pages_seen}
    results: dict[tuple, dict] = {}
    for prep in PREPROCESSING_VARIANTS:
        for psm in PSM_MODES:
            page_confs = []
            page_orders = []
            wer_hyp = ""
            pages_seen = 0
            for vol, page in PROBE_VOLS_PAGES:
                key = (prep, psm, vol, page)
                if key not in sidecars:
                    continue
                pages_seen += 1
                d = sidecars[key]
                conf = d.get("confidence_mean", 0.0)
                page_confs.append(conf)
                text = d.get("raw_text", "")
                order = check_reading_order(text)
                page_orders.append(order)
                if vol == WER_VOL and page == WER_PAGE:
                    wer_hyp = " ".join(text.split()[:200])

            correct = page_orders.count("correct")
            na = page_orders.count("N/A")
            effective = pages_seen - na
            mean_conf = float(np.mean(page_confs)) if page_confs else 0.0
            wer = compute_wer(ia_ref, wer_hyp) * 100 if ia_ref and wer_hyp else 0.0
            results[(prep, psm)] = {
                "mean_conf": round(mean_conf, 1),
                "correct": correct,
                "na": na,
                "effective": effective,
                "wer": round(wer, 2),
                "pages_seen": pages_seen,
            }

    # Print results table
    print()
    print("--- Results Table (lang=eng) ---")
    print(f"{'Prep':<22} {'PSM':<8} {'MeanConf':>9} {'Order':>10} {'WER%':>7}")
    print("-" * 65)
    for prep in PREPROCESSING_VARIANTS:
        for psm in PSM_MODES:
            r = results.get((prep, psm), {})
            if not r:
                continue
            order_str = f"{r['correct']}/{r['effective']}+{r['na']}NA"
            conf_str = f"{r['mean_conf']:>9.1f}" if r['mean_conf'] > 0 else "     (0.0)"
            print(f"{prep:<22} {str(psm):<8} {conf_str} {order_str:>10} {r['wer']:>7.2f}")

    # -----------------------------------------------------------------------
    # D2: PSM lock (reading order)
    # -----------------------------------------------------------------------
    print()
    print("--- D2: PSM Lock (reading order >=7/8) ---")
    psm_order: dict = {}
    for psm in PSM_MODES:
        best_correct = 0
        for prep in PREPROCESSING_VARIANTS:
            r = results.get((prep, psm), {})
            best_correct = max(best_correct, r.get("correct", 0))
        psm_order[psm] = best_correct
        print(f"  PSM {psm}: best={best_correct}/8 pages correct")

    locked_psm = None
    for psm in [1, "split+4", 3]:  # preference order per spec
        if psm_order.get(psm, 0) >= 7:
            locked_psm = psm
            print(f"  LOCK: PSM={locked_psm} (>= 7/8 pages)")
            break
    if locked_psm is None:
        best_psm = max(psm_order, key=lambda p: psm_order[p])
        locked_psm = best_psm
        print(f"  WARN: No PSM meets >=7/8. Locking best: PSM={locked_psm} ({psm_order[best_psm]}/8)")

    # -----------------------------------------------------------------------
    # D4: preprocessing lock (highest mean confidence, prefer simpler within 2pt)
    # -----------------------------------------------------------------------
    print()
    print("--- D4: Preprocessing Lock (highest conf, prefer simpler within 2pt, must be >=70) ---")
    prep_confs: dict[str, float] = {}
    for prep in PREPROCESSING_VARIANTS:
        r = results.get((prep, locked_psm), {})
        prep_confs[prep] = r.get("mean_conf", 0.0)
        print(f"  {prep:<22}: conf={prep_confs[prep]:.1f}")

    # Check if confidence values are available (non-zero)
    has_conf = any(v > 0 for v in prep_confs.values())
    if not has_conf:
        print("  WARN: All confidence values are 0.0 -- fix_b22_confidence.py may still be running.")
        print("  Cannot apply D4 until confidence is patched. Re-run after patch completes.")
        locked_prep = None
    else:
        best_conf = max(prep_confs.values())
        # Candidates within 2pt of best, pick simplest
        candidates = [(prep, conf) for prep, conf in prep_confs.items()
                      if conf >= best_conf - 2.0 and conf > 0]
        candidates.sort(key=lambda x: PREPROCESSING_SIMPLICITY[x[0]])
        locked_prep, locked_conf = candidates[0]
        print(f"  LOCK: prep={locked_prep} (conf={locked_conf:.1f})")
        if locked_conf < 70:
            print(f"  WARN: Confidence {locked_conf:.1f} < 70 threshold -- review manually")

    # -----------------------------------------------------------------------
    # D3: language lock (eng vs eng+lat WER delta on locked PSM+prep)
    # -----------------------------------------------------------------------
    if locked_psm is None or locked_prep is None:
        print()
        print("--- D3: Language Lock SKIPPED (D2/D4 not yet locked) ---")
    elif args.skip_d3:
        print()
        print("--- D3: Language Lock SKIPPED (--skip-d3 flag) ---")
    else:
        print()
        print(f"--- D3: Language Lock (eng vs eng+lat WER on vol{WER_VOL}/p{WER_PAGE}, prep={locked_prep}, psm={locked_psm}) ---")
        # Get eng WER from results
        r_eng = results.get((locked_prep, locked_psm), {})
        wer_eng = r_eng.get("wer", 0.0)
        print(f"  eng WER: {wer_eng:.2f}%")

        # Run eng+lat on the bibliography page
        vol_dir = RAW_PAGES / f"vol_{WER_VOL:02d}"
        jpeg = vol_dir / f"page_{WER_PAGE:04d}.jpg"
        psm_str = str(locked_psm).replace("+", "p")
        englatSidecar = vol_dir / f"page_{WER_PAGE:04d}.{locked_prep}.psm{psm_str}.eng+lat.tess.json"

        if englatSidecar.exists():
            d = json.loads(englatSidecar.read_text(encoding="utf-8"))
            text_lat = d.get("raw_text", "")
            mean_conf_lat = d.get("confidence_mean", 0.0)
        else:
            print(f"  Running Tesseract with eng+lat on {jpeg.name}...")
            t0 = time.time()
            prep_temps = []
            try:
                processed = _apply_preprocessing(jpeg, locked_prep)
                if processed != jpeg:
                    prep_temps.append(processed)
                if locked_psm == "split+4":
                    lt, rt = _split_image_halves(processed)
                    prep_temps += [lt, rt]
                    lt_text = run_tesseract_text(lt, "eng+lat", 4)
                    rt_text = run_tesseract_text(rt, "eng+lat", 4)
                    text_lat = lt_text + "\n" + rt_text
                    lt_conf, _ = run_tesseract_tsv(lt, "eng+lat", 4)
                    rt_conf, _ = run_tesseract_tsv(rt, "eng+lat", 4)
                    mean_conf_lat = round((lt_conf + rt_conf) / 2, 1) if lt_conf > 0 or rt_conf > 0 else 0.0
                else:
                    text_lat = run_tesseract_text(processed, "eng+lat", locked_psm)
                    mean_conf_lat, _ = run_tesseract_tsv(processed, "eng+lat", locked_psm)
            finally:
                for tmp in prep_temps:
                    tmp.unlink(missing_ok=True)
            elapsed = time.time() - t0
            print(f"  Done: {elapsed:.1f}s, conf={mean_conf_lat:.1f}")
            # Write sidecar
            from datetime import datetime, timezone
            sidecar_data = {
                "engine_alias": "oss-tesseract",
                "engine_version": "5.5.0.20241111",
                "language_packs": ["eng", "lat"],
                "psm_mode": locked_psm,
                "preprocessing": locked_prep,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "confidence_mean": mean_conf_lat,
                "raw_text": text_lat,
                "words": [],
            }
            tmp_path = englatSidecar.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(sidecar_data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp_path, englatSidecar)

        wer_hyp_lat = " ".join(text_lat.split()[:200])
        wer_lat = compute_wer(ia_ref, wer_hyp_lat) * 100 if ia_ref else 0.0
        delta = wer_lat - wer_eng
        print(f"  eng+lat WER: {wer_lat:.2f}%")
        print(f"  Delta (lat-eng): {delta:+.2f}pp (threshold: +-0.5pp to prefer eng+lat)")

        if delta < -0.5:
            locked_lang = "eng+lat"
            print(f"  LOCK: lang=eng+lat (lat improves WER by {-delta:.2f}pp > 0.5pp)")
        else:
            locked_lang = "eng"
            print(f"  LOCK: lang=eng (eng+lat does not improve WER by >0.5pp)")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print()
    print("=== B2.2 Decision Summary ===")
    print(f"  D2 PSM lock:           psm={locked_psm}")
    if locked_prep:
        print(f"  D4 Preprocessing lock: prep={locked_prep} (conf={prep_confs.get(locked_prep, 0):.1f})")
    else:
        print("  D4 Preprocessing lock: PENDING (confidence patch still running)")
    if not args.skip_d3 and locked_psm and locked_prep:
        pass  # D3 lock printed above in D3 block


if __name__ == "__main__":
    main()
