"""Verify every NSH ``page_NNNN.jpg`` shows printed page N, via running-header OCR.

PRIMARY GROUND TRUTH is the printed page number in the running header of the
*current* ``page_NNNN.jpg`` image, OCR'd directly. This is deliberately
independent of every manifest, leaf->page map, and OCR sidecar: those encode
the leaf<->page bookkeeping that is itself under test (the phantom-page rename
shifted filenames; a rename off-by-one would silently mis-name a run of pages
while all the counts still reconcile). The image pixels are the only source
that cannot have been corrupted by a rename-logic bug.

Header layout, New Schaff-Herzog (1908-1914):
  recto / odd printed page :  "<N>  RELIGIOUS ENCYCLOPEDIA  <article>"   (N top-left)
  verso / even printed page:  "<article>  THE NEW SCHAFF-HERZOG  <N>"    (N top-right)

The page number is isolated by anchoring on the fixed header words
(RELIGIOUS/ENCYCLOPEDIA => recto, HERZOG/SCHAFF => verso), then taking the
plausible integer nearest the outer margin. Body numbers (dates, verse refs)
are excluded by a 1..560 / <=3-digit plausibility cap and by edge selection.

DETECTION MODEL. A rename off-by-one shifts every page from the first renamed
page to the end of the volume by a single CONSTANT. So the rename signature is
a *sustained constant non-zero* (header - N) delta across a contiguous run of
pages. Isolated single-digit OCR misreads (e.g. 123 read as 128) produce
random, non-repeating deltas and never form a sustained run. Calibration on a
known-clean control volume establishes the misread/unreadable noise floor;
the gate fires only on a sustained run.

Usage:
  py -3 build/tools/verify_nsh_running_headers.py --volume 3 --pages all --json out.json
  py -3 build/tools/verify_nsh_running_headers.py --volume 5 --pages 451-504
  py -3 build/tools/verify_nsh_running_headers.py --volume 1 --pages 90-100,498

Exit code is non-zero when a sustained non-zero-delta run (the rename
signature) is detected, so the tool can gate a future commit / CI step.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image
import pytesseract

# Resolve relative to this file so no machine-specific path is baked in (OUT-03).
REPO_ROOT = Path(__file__).resolve().parents[2]
PAGES_BASE = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"

# --- Tuning constants (PY-03: config at the top) ---------------------------
STRIP_FRAC = 0.20          # top fraction of the image that holds the header band
# 0.20 covers both NSH scan geometries: the smaller ~5000x6959 leaves (header at
# ~0.13) and the larger ~6050x7701 leaves (header at ~0.18). A strip tuned to the
# small geometry (0.13) misses the header on the large-geometry volumes entirely
# (vol_04 read 95% unreadable at 0.13, 9% at 0.20). The extra body text the wider
# strip pulls in is filtered by the anchor + edge + <=3-digit/<=560 plausibility cap.
MAX_PAGE_NUM = 560         # largest plausible printed page (vols run to ~516)
SUSTAINED_RUN_MIN = 3      # consecutive identical non-zero deltas => rename signature
HEADER_PSM = "--psm 6"     # assume a uniform block of text

# Permanently-missing printed pages (absent from IA upstream) -- skipped, not failures.
# vol_10 carries NO permanent gap: it is complete at 499 pages. The earlier
# {497..508} entry was an artifact of the +8 back-body image corruption (the
# corrupted frame made the terminal read as missing). After the 2026-06-12
# image repair, printed 497-499 are present from primary leaves 517-519, and the
# four pages absent only from the PRIMARY scan (356, 359, 366, 369) are all
# present on disk via haucgoog substitutes -- so none are "missing" page images.
PERMANENT_MISSING = {
    13: {209, 210, 211},        # vol_13 pp209-211 (3 pages)
}

_RECTO_ANCHORS = ("RELIGIOUS", "ENCYCLOPED")
_VERSO_ANCHORS = ("HERZOG", "SCHAFF")

# Optional override: audit a fresh rebuild dir (vol_NN_rebuild) before it is
# swapped to the live PAGES_BASE/vol_NN path, so the live disk stays untouched
# until the OCR gate passes. None => use the live per-volume directory.
_VOLUME_DIR_OVERRIDE: Path | None = None


def set_volume_dir_override(path: Path | None) -> None:
    """Point page-path resolution at an explicit directory (or None for live)."""
    global _VOLUME_DIR_OVERRIDE
    _VOLUME_DIR_OVERRIDE = Path(path) if path is not None else None


def _volume_dir(volume: int) -> Path:
    if _VOLUME_DIR_OVERRIDE is not None:
        return _VOLUME_DIR_OVERRIDE
    return PAGES_BASE / f"vol_{volume:02d}"


def resolve_tesseract() -> str:
    """tesseract.exe path: PATH first, then the standard Windows install dir.

    Mirrors build/lib/engine_inventory.tesseract_binary so this tool has no
    import-time dependency on the build package. PROGRAMFILES is an OS path,
    not a personal identifier, so it is safe to commit.
    """
    found = shutil.which("tesseract")
    if found:
        return found
    program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    return str(program_files / "Tesseract-OCR" / "tesseract.exe")


def _page_path(volume: int, page_num: int) -> Path:
    return _volume_dir(volume) / f"page_{page_num:04d}.jpg"


def read_header_number(img_path: Path) -> dict:
    """OCR the header band of one image and isolate the printed page number.

    Returns a dict with: header_num (int|None), side (recto/verso/unknown),
    raw (the OCR'd header text). header_num is None when no plausible page
    number could be read.
    """
    with Image.open(img_path) as im:
        width, height = im.size
        strip = im.crop((0, 0, width, int(height * STRIP_FRAC)))
        data = pytesseract.image_to_data(
            strip, config=HEADER_PSM, output_type=pytesseract.Output.DICT
        )

    words: list[tuple[str, float]] = []
    for i, raw_tok in enumerate(data["text"]):
        tok = raw_tok.strip()
        if not tok:
            continue
        x_centroid = data["left"][i] + data["width"][i] / 2.0
        words.append((tok, x_centroid))

    joined_upper = " ".join(w for w, _ in words).upper()
    if any(a in joined_upper for a in _RECTO_ANCHORS):
        side = "recto"
    elif any(a in joined_upper for a in _VERSO_ANCHORS):
        side = "verso"
    else:
        side = "unknown"

    # Page numbers are 1-3 digits (<=516); the <=3-digit + range cap excludes
    # 4-digit body dates (1115, 1740) outright.
    candidates = [
        (int(tok), xc)
        for tok, xc in words
        if re.fullmatch(r"\d{1,3}", tok) and 1 <= int(tok) <= MAX_PAGE_NUM
    ]
    header_num: int | None
    if not candidates:
        header_num = None
    elif side == "verso":
        header_num = max(candidates, key=lambda e: e[1])[0]   # far right
    else:
        header_num = min(candidates, key=lambda e: e[1])[0]   # far left (recto / unknown)

    return {
        "header_num": header_num,
        "side": side,
        "raw": " ".join(w for w, _ in words)[:120],
    }


def _check_one(volume: int, page_num: int) -> dict:
    path = _page_path(volume, page_num)
    rec: dict = {"page_num": page_num, "file": path.name}
    if not path.exists():
        rec.update(status="missing-file", header_num=None, delta=None, side=None, raw="")
        return rec
    info = read_header_number(path)
    header_num = info["header_num"]
    if header_num is None:
        status = "unreadable"
        delta = None
    elif header_num == page_num:
        status = "match"
        delta = 0
    else:
        status = "mismatch"
        delta = header_num - page_num
    rec.update(
        status=status,
        header_num=header_num,
        delta=delta,
        side=info["side"],
        raw=info["raw"],
    )
    return rec


def scan_volume(volume: int, pages: list[int], workers: int = 8) -> list[dict]:
    """OCR the header of every requested page in a volume, in parallel.

    pytesseract shells out to tesseract.exe, which releases the GIL, so a
    thread pool gives real multi-core speedup without process-spawn overhead.
    """
    results: list[dict | None] = [None] * len(pages)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_check_one, volume, p): i for i, p in enumerate(pages)}
        done = 0
        total = len(futs)
        for fut in as_completed(futs):
            idx = futs[fut]
            results[idx] = fut.result()
            done += 1
            if done % 25 == 0 or done == total:
                print(f"  ... {done}/{total} pages OCR'd", file=sys.stderr)
    return [r for r in results if r is not None]


def detect_sustained_runs(records: list[dict], min_run: int = SUSTAINED_RUN_MIN) -> list[dict]:
    """Find contiguous runs (by page_num) of identical non-zero delta, and
    classify each as 'recovering' or 'persistent-to-tail'.

    Only 'match'/'mismatch' records carry a delta; 'unreadable' and
    'missing-file' break a run (a run is only credited across consecutive
    readable pages sharing a delta).

    Classification is the rename/OCR discriminator. A rename off-by-one shifts
    every page from its start to the END of the volume, so its delta-run never
    recovers to 0 before the last readable page. A consistent OCR misread (e.g.
    a degraded gathering where every '5' reads as '4') produces an island that
    RECOVERS to delta 0 afterward. Calibration on the clean vol_03 control
    surfaced exactly such an island (pp250-253 read 240-243, recovered at 254),
    proving the discriminator is necessary.
    """
    ordered = sorted(records, key=lambda r: r["page_num"])
    readable = [r for r in ordered if r.get("delta") is not None]
    last_readable_page = readable[-1]["page_num"] if readable else None

    def recovers_after(end_page: int) -> bool:
        """True if any readable page after end_page returns to delta 0."""
        return any(r["page_num"] > end_page and r["delta"] == 0 for r in readable)

    runs: list[dict] = []
    cur: list[dict] = []

    def flush() -> None:
        if len(cur) >= min_run and cur[0]["delta"] not in (0, None):
            end_page = cur[-1]["page_num"]
            recovering = recovers_after(end_page)
            runs.append(
                {
                    "delta": cur[0]["delta"],
                    "start_page": cur[0]["page_num"],
                    "end_page": end_page,
                    "length": len(cur),
                    # A run is the rename signature only if it does NOT recover
                    # and reaches the tail of the checked range.
                    "recovers": recovering,
                    "classification": "recovering-ocr-cluster" if recovering
                    else "persistent-to-tail",
                    "reaches_last_readable": end_page == last_readable_page,
                }
            )

    prev_page: int | None = None
    for rec in ordered:
        d = rec.get("delta")
        if d is None:
            flush()
            cur = []
            prev_page = None
            continue
        contiguous = prev_page is not None and rec["page_num"] == prev_page + 1
        if cur and contiguous and d == cur[-1]["delta"]:
            cur.append(rec)
        else:
            flush()
            cur = [rec]
        prev_page = rec["page_num"]
    flush()
    return runs


def summarize(volume: int, records: list[dict]) -> dict:
    readable = [r for r in records if r["status"] in ("match", "mismatch")]
    matched = [r for r in readable if r["status"] == "match"]
    mism = [r for r in readable if r["status"] == "mismatch"]
    unread = [r for r in records if r["status"] == "unreadable"]
    missing = [r for r in records if r["status"] == "missing-file"]
    runs = detect_sustained_runs(records)

    # Tail check: a rename off-by-one propagates to the volume end, so the
    # highest-numbered readable pages are the strongest single signal.
    readable_sorted = sorted(readable, key=lambda r: r["page_num"])
    tail = readable_sorted[-10:]
    tail_matched = sum(1 for r in tail if r["delta"] == 0)
    last_page = readable_sorted[-1] if readable_sorted else None

    # The rename signature: a non-recovering (persistent-to-tail) delta run.
    rename_runs = [r for r in runs if not r["recovers"]]

    return {
        "volume": volume,
        "pages_requested": len(records),
        "pages_on_disk": len(records) - len(missing),
        "readable": len(readable),
        "matched": len(matched),
        "mismatched": len(mism),
        "unreadable": len(unread),
        "missing_files": len(missing),
        "match_rate": round(len(matched) / len(readable), 4) if readable else None,
        "unreadable_rate": round(len(unread) / (len(readable) + len(unread)), 4)
        if (readable or unread)
        else None,
        "tail_check": {
            "tail_pages_checked": len(tail),
            "tail_matched": tail_matched,
            "last_readable_page": last_page["page_num"] if last_page else None,
            "last_readable_delta": last_page["delta"] if last_page else None,
        },
        "rename_signature_runs": rename_runs,
        "sustained_runs": runs,
        "mismatch_pages": [
            {"page_num": r["page_num"], "header_num": r["header_num"], "delta": r["delta"],
             "side": r["side"], "raw": r["raw"]}
            for r in sorted(mism, key=lambda r: r["page_num"])
        ],
        "unreadable_pages": [r["page_num"] for r in sorted(unread, key=lambda r: r["page_num"])],
        "missing_pages": [r["page_num"] for r in sorted(missing, key=lambda r: r["page_num"])],
    }


def parse_pages_spec(spec: str, volume: int) -> list[int]:
    """Expand a --pages spec into a sorted page list, skipping permanent gaps.

    'all'         -> every page_*.jpg present on disk
    '451-504'     -> inclusive range
    '90-100,498'  -> union of ranges / singletons
    """
    vdir = _volume_dir(volume)
    perm_missing = PERMANENT_MISSING.get(volume, set())
    if spec == "all":
        nums = sorted(
            int(p.stem.split("_")[1]) for p in vdir.glob("page_*.jpg")
        )
        return nums
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.update(range(int(lo), int(hi) + 1))
        else:
            out.add(int(part))
    return sorted(p for p in out if p not in perm_missing)


def _selftest() -> int:
    """Adversarial self-test of the rename discriminator (TEST-09).

    Builds synthetic record sets and asserts that the persistent-to-tail run
    (rename signature) is flagged while a recovering OCR-cluster island is not.
    """

    def rec(pn: int, delta):  # delta None -> unreadable
        if delta is None:
            return {"page_num": pn, "status": "unreadable", "header_num": None,
                    "delta": None, "side": None, "raw": ""}
        return {"page_num": pn, "status": "match" if delta == 0 else "mismatch",
                "header_num": pn + delta, "delta": delta, "side": "recto", "raw": ""}

    # TRUE NEGATIVE 1: all clean -> no runs.
    clean = [rec(p, 0) for p in range(1, 21)]
    s = summarize(99, clean)
    assert not s["rename_signature_runs"], "clean volume must have no rename run"
    assert s["tail_check"]["last_readable_delta"] == 0

    # TRUE NEGATIVE 2: recovering OCR island (like vol_03 pp250-253) -> not a rename.
    island = [rec(p, 0) for p in range(1, 10)] + \
             [rec(p, -10) for p in range(10, 14)] + \
             [rec(p, 0) for p in range(14, 21)]
    s = summarize(99, island)
    assert not s["rename_signature_runs"], "recovering island must NOT be a rename signature"
    assert any(r["classification"] == "recovering-ocr-cluster" for r in s["sustained_runs"])

    # TRUE POSITIVE: off-by-one that persists to the last page -> rename signature.
    shifted = [rec(p, 0) for p in range(1, 10)] + [rec(p, 1) for p in range(10, 21)]
    s = summarize(99, shifted)
    assert s["rename_signature_runs"], "persistent-to-tail shift must be flagged"
    assert s["rename_signature_runs"][0]["delta"] == 1
    assert s["tail_check"]["last_readable_delta"] == 1

    # Isolated single misreads must not reach the min-run threshold.
    noisy = [rec(p, 0) for p in range(1, 21)]
    noisy[4]["delta"], noisy[4]["status"] = 5, "mismatch"
    noisy[11]["delta"], noisy[11]["status"] = -3, "mismatch"
    s = summarize(99, noisy)
    assert not s["sustained_runs"], "isolated misreads must not form a run"

    print("selftest OK: rename discriminator true-positive + true-negatives pass")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true",
                        help="Run the rename-discriminator self-test and exit.")
    parser.add_argument("--volume", type=int)
    parser.add_argument(
        "--pages",
        default="all",
        help="'all', a range '451-504', or a list '90-100,498'.",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--json", type=Path, default=None, help="Write full results JSON here.")
    parser.add_argument(
        "--volume-dir",
        type=Path,
        default=None,
        help="Audit this directory's page_*.jpg instead of the live "
             "PAGES_BASE/vol_NN path (e.g. a vol_NN_rebuild dir before swap).",
    )
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.volume is None:
        parser.error("--volume is required unless --selftest is given")

    if args.volume_dir is not None:
        set_volume_dir_override(args.volume_dir)

    pytesseract.pytesseract.tesseract_cmd = resolve_tesseract()

    pages = parse_pages_spec(args.pages, args.volume)
    print(f"vol_{args.volume:02d}: OCR header check on {len(pages)} pages "
          f"({args.pages})", file=sys.stderr)
    records = scan_volume(args.volume, pages, workers=args.workers)
    summary = summarize(args.volume, records)

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.json.with_suffix(args.json.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"summary": summary, "records": records}, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, args.json)

    print(json.dumps(summary, indent=2))

    rename_runs = summary["rename_signature_runs"]
    recovering = [r for r in summary["sustained_runs"] if r["recovers"]]
    if recovering:
        print(f"\nNote: {len(recovering)} recovering OCR-cluster island(s) "
              f"(consistent misread, NOT a rename) -- adjudicate, not a failure.")
    if rename_runs:
        print(f"\n*** RENAME SIGNATURE: {len(rename_runs)} persistent-to-tail "
              f"non-zero-delta run(s) in vol_{args.volume:02d} ***")
        return 1
    print(f"\nvol_{args.volume:02d}: no rename signature "
          f"(match_rate={summary['match_rate']}, unreadable_rate={summary['unreadable_rate']}, "
          f"tail_matched={summary['tail_check']['tail_matched']}/"
          f"{summary['tail_check']['tail_pages_checked']})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
