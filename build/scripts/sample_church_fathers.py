"""sample_church_fathers.py
Post-build sanity check for data/church-fathers/.

Samples N random authors and prints key fields for one random entry each.
Also checks for non-ASCII filenames (indicates a slug normalization bug).

Usage:
    py -3 build/scripts/sample_church_fathers.py          # 5 authors
    py -3 build/scripts/sample_church_fathers.py --n 10   # 10 authors
    py -3 build/scripts/sample_church_fathers.py --author john-chrysostom
"""

import argparse
import json
import random
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "church-fathers"
QUOTE_PREVIEW_LEN = 100


def _ascii_safe(s: str) -> str:
    normalized = unicodedata.normalize("NFKD", s)
    return normalized.encode("ascii", "ignore").decode("ascii")


def check_filenames(files: list) -> int:
    """Report any non-ASCII filenames. Returns count of bad files."""
    bad = [f for f in files if f.name != f.name.encode("ascii", "ignore").decode("ascii")]
    if bad:
        print(f"[FAIL] Non-ASCII filenames found ({len(bad)}):")
        for f in bad:
            print(f"  {f.name}")
    return len(bad)


def sample_file(path: Path) -> None:
    """Print a one-entry sample from a church-fathers JSON file."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("meta", {})
    entries = data.get("data", [])

    if not entries:
        print(f"  [WARN] {path.name}: 0 entries")
        return

    entry = random.choice(entries)
    osis = entry.get("anchor_ref", {}).get("osis", [])
    raw_ref = entry.get("anchor_ref", {}).get("raw", "")
    quote = entry.get("quote", "")
    preview = quote[:QUOTE_PREVIEW_LEN].replace("\n", " ")
    if len(quote) > QUOTE_PREVIEW_LEN:
        preview += "..."

    print(f"  author:       {_ascii_safe(meta.get('author', '?'))}")
    print(f"  total entries:{len(entries)}")
    print(f"  entry_id:     {entry.get('entry_id', '?')}")
    print(f"  anchor_ref:   {_ascii_safe(raw_ref)} -> {osis}")
    print(f"  source_title: {_ascii_safe(entry.get('source_title', ''))}")
    print(f"  word_count:   {entry.get('word_count', '?')}")
    print(f"  quote:        {_ascii_safe(preview)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sample church-fathers output files for a quick sanity check."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--n", type=int, default=5, help="Number of random authors to sample (default: 5)")
    group.add_argument("--author", metavar="SLUG", help="Sample a specific author by slug, e.g. john-chrysostom")
    args = parser.parse_args()

    if not DATA_DIR.exists():
        print(f"ERROR: Data directory not found: {DATA_DIR}")
        print("Run: py -3 build/parsers/church_fathers.py --all-authors")
        return

    all_files = sorted(DATA_DIR.glob("*.json"))
    if not all_files:
        print(f"ERROR: No JSON files in {DATA_DIR}")
        return

    print(f"Church Fathers sanity check")
    print(f"Data dir: {DATA_DIR}")
    print(f"Total files: {len(all_files)}")
    print()

    # Filename check (catches non-ASCII slug bugs)
    bad_count = check_filenames(all_files)
    if bad_count:
        print()
    else:
        print(f"[OK] All {len(all_files)} filenames are ASCII-safe")
    print()

    # Select files to sample
    if args.author:
        target = DATA_DIR / f"{args.author}.json"
        if not target.exists():
            print(f"ERROR: File not found: {target}")
            matches = [f for f in all_files if args.author in f.stem]
            if matches:
                print(f"  Possible matches: {[f.stem for f in matches[:5]]}")
            return
        sample_files = [target]
    else:
        n = min(args.n, len(all_files))
        sample_files = random.sample(all_files, n)
        sample_files.sort()

    # Print samples
    for i, path in enumerate(sample_files, 1):
        print(f"--- Sample {i}: {path.stem} ---")
        sample_file(path)
        print()

    print(f"Done. Sampled {len(sample_files)} of {len(all_files)} author files.")


if __name__ == "__main__":
    main()
