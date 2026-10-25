"""Report short commentary rows from a verified selected v2 release.

Pass --root, --release and --selection. Historical directory scanning requires
--legacy-data as the first argument and retains its old --commentary option.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "commentaries"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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


def legacy_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report short commentary entries")
    parser.add_argument("--threshold", type=int, default=20, help="Word count threshold (default: 20)")
    parser.add_argument("--commentary", help="Scan only this commentary ID")
    args = parser.parse_args(argv)

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


    return 0


def short_release_entries(root: Path, release: Path, selection: dict, threshold: int, work_id: str | None = None) -> dict:
    from build.tools.report_release_stats import release_statistics
    from ocd_kernel.library._common import PipelineError

    if threshold < 0:
        raise ValueError("threshold must be nonnegative")
    report_path = release / "internal" / "release-report.json"
    report_bytes = report_path.read_bytes()
    release_statistics(root, release, selection)
    if report_path.read_bytes() != report_bytes:
        raise PipelineError("release report changed during verification")
    report = json.loads(report_bytes)
    configurations = [item for item in report["configurations"] if item["category"] == "commentary"]
    if not configurations:
        raise PipelineError("selected release contains no commentary configuration")
    short = []
    total = 0
    for config in configurations:
        content = (release / config["path"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != config["sha256"]:
            raise PipelineError("commentary rows changed after verification")
        for line in content.decode("utf-8").splitlines():
            row = json.loads(line)
            if work_id is not None and row["work_id"] != work_id:
                continue
            total += 1
            count = len(row["text"].split())
            if count < threshold:
                short.append({"work_id": row["work_id"], "record_id": row["record_id"],
                              "word_count": count, "preview": ascii_safe(row["text"])})
    if work_id is not None and total == 0:
        raise PipelineError(f"selected release contains no commentary rows for work {work_id!r}")
    return {"status": "pass", "release_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "category": "commentary", "threshold": threshold, "total_records": total,
            "short_records": short, "counting_rule": "Unicode whitespace-delimited tokens in verified public text"}


def main(argv: list[str] | None = None) -> int:
    from ocd_kernel.library._common import PipelineError
    from ocd_kernel.release.selection import load_release_selection

    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "--legacy-data":
        return legacy_main(arguments[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--threshold", type=int, default=20)
    parser.add_argument("--work-id")
    args = parser.parse_args(arguments)
    try:
        result = short_release_entries(args.root, args.release, load_release_selection(args.selection), args.threshold, args.work_id)
    except (PipelineError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
