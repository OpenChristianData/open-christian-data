"""generate_tess_fixtures.py -- Generate fixture text files for test_local_schaff_tesseract.

Runs Tesseract with the B2.2 locked config (PSM=1, eng, raw preprocessing)
on the 8 probe pages and writes stdout text to tests/fixtures/local_schaff_tesseract/.

Usage:
    py -3 build/tools/generate_tess_fixtures.py [--dry-run]

Requires:
    - Probe pages downloaded to raw/internet-archive/schaff-herzog-pages/
    - Tesseract at TESSERACT_CMD (default: C:\\Program Files\\Tesseract-OCR\\tesseract.exe)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_PAGES = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "local_schaff_tesseract"
TESSERACT_CMD = os.environ.get("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")

PROBE_PAGES = [
    (3, 75, "random"),
    (3, 100, "entry-dense"),
    (3, 164, "random"),
    (3, 300, "random"),
    (3, 331, "random"),
    (4, 480, "bibliography-heavy"),
    (5, 350, "column-edge"),
    (7, 200, "greek-latin-heavy"),
]


def run_tesseract_text(jpeg_path: Path) -> str:
    with tempfile.NamedTemporaryFile(suffix="", delete=False) as t:
        base = t.name
    try:
        cmd = [TESSERACT_CMD, str(jpeg_path), base, "-l", "eng", "--psm", "1"]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        _ = result
        txt = Path(base + ".txt")
        return txt.read_text(encoding="utf-8") if txt.exists() else ""
    finally:
        for ext in [".txt", ""]:
            p = Path(base + ext)
            p.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"=== Fixture generation (dry_run={args.dry_run}) ===")
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    ok = skipped = failed = 0
    for vol, page, label in PROBE_PAGES:
        jpeg = RAW_PAGES / f"vol_{vol:02d}" / f"page_{page:04d}.jpg"
        fixture = FIXTURE_DIR / f"vol_{vol:02d}_page_{page:04d}.txt"

        if not jpeg.exists():
            print(f"  SKIP vol_{vol:02d}/page_{page:04d}.jpg -- not downloaded")
            skipped += 1
            continue

        if fixture.exists():
            print(f"  SKIP {fixture.name} -- already exists")
            skipped += 1
            continue

        print(f"  {label}: vol_{vol:02d}/page_{page:04d}.jpg -> {fixture.name}...", end="", flush=True)
        if args.dry_run:
            print(" (dry-run)")
            continue

        try:
            text = run_tesseract_text(jpeg)
            fixture.write_text(text, encoding="utf-8")
            word_count = len([w for w in text.split() if w])
            print(f" {word_count} words")
            ok += 1
        except Exception as exc:
            print(f" ERROR: {exc}")
            failed += 1

    print(f"\nDone. Written: {ok}, skipped: {skipped}, failed: {failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
