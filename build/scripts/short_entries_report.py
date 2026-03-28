"""short_entries_report.py
Scan all commentary JSON files and report entries under a word count threshold.
Outputs ASCII-safe text suitable for Windows console.

Usage:
    py -3 build/scripts/short_entries_report.py
    py -3 build/scripts/short_entries_report.py --threshold 10
    py -3 build/scripts/short_entries_report.py --commentary adam-clarke
"""

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "commentaries"


def ascii_safe(text, max_len=120):
    """Return ASCII-only preview of text, truncated to max_len."""
    clean = text.encode("ascii", "replace").decode("ascii")
    clean = " ".join(clean.split())  # collapse whitespace
    if len(clean) > max_len:
        return clean[:max_len] + "..."
    return clean


def scan_commentary(commentary_dir, threshold):
    """Scan one commentary directory. Returns list of (entry_id, word_count, preview)."""
    results = []
    for json_file in sorted(commentary_dir.glob("*.json")):
        if json_file.name.startswith("_"):
            continue
        with open(json_file, encoding="utf-8") as f:
            data = json.load(f)
        for entry in data.get("data", []):
            wc = entry.get("word_count", 0)
            if wc < threshold:
                preview = ascii_safe(entry.get("commentary_text", ""))
                results.append((entry["entry_id"], wc, preview))
    return results


def main():
    parser = argparse.ArgumentParser(description="Report short commentary entries")
    parser.add_argument("--threshold", type=int, default=20, help="Word count threshold (default: 20)")
    parser.add_argument("--commentary", help="Scan only this commentary ID")
    args = parser.parse_args()

    if args.commentary:
        dirs = [DATA_DIR / args.commentary]
    else:
        dirs = sorted(d for d in DATA_DIR.iterdir() if d.is_dir())

    grand_total = 0
    grand_short = 0

    for cdir in dirs:
        if not cdir.is_dir():
            print("WARNING: %s not found -- skipping" % cdir.name)
            continue

        results = scan_commentary(cdir, args.threshold)
        # Count total entries for percentage
        total = 0
        for json_file in cdir.glob("*.json"):
            if json_file.name.startswith("_"):
                continue
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)
            total += len(data.get("data", []))

        grand_total += total
        grand_short += len(results)

        pct = (len(results) * 100 / total) if total else 0
        print("=" * 70)
        print("%s: %d/%d entries under %d words (%.1f%%)" % (
            cdir.name, len(results), total, args.threshold, pct))
        print("=" * 70)

        if not results:
            print("  (none)")
            print()
            continue

        # Group by word count for easier review
        by_wc = {}
        for entry_id, wc, preview in results:
            by_wc.setdefault(wc, []).append((entry_id, preview))

        for wc in sorted(by_wc.keys()):
            entries = by_wc[wc]
            print("  --- %d words (%d entries) ---" % (wc, len(entries)))
            for entry_id, preview in entries[:10]:
                print("    %s" % entry_id)
                print("      %s" % preview)
            if len(entries) > 10:
                print("    ... and %d more at this word count" % (len(entries) - 10))
        print()

    print("=" * 70)
    pct = (grand_short * 100 / grand_total) if grand_total else 0
    print("TOTAL: %d/%d entries under %d words (%.1f%%)" % (
        grand_short, grand_total, args.threshold, pct))


if __name__ == "__main__":
    main()
