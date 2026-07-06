"""apply_approved_corrections.py -- apply reviewer-approved OCR corrections.

Reads a scan report JSON and an approved.json (reviewer output), then writes
approved corrections to build/tools/ocr_scanner/corrections/<source_id>.json.

Rejected candidates with whitelist notes are printed to stdout for manual
action (copy them into the per-source config whitelist_terms).

Never auto-corrects corpus data. Only writes to the corrections table.

Usage:
    py -3 build/tools/ocr_scanner/apply_approved_corrections.py \
        --scan-report path/to/schaff-herzog_2026-04-15.json \
        --approved path/to/schaff-herzog_2026-04-15_approved.json \
        [--apply]    # omit for dry-run (default)

Import-safe: no I/O at module level (PY-06).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# API-01: DRY_RUN = True at module level; appears in if DRY_RUN: conditional in main()
DRY_RUN = True

# ---------------------------------------------------------------------------
# Core logic (testable without CLI)
# ---------------------------------------------------------------------------

def apply(
    scan_report_path: Path,
    approved_path: Path,
    corrections_dir: Path,
    dry_run: bool = True,
) -> None:
    """Apply approvals from approved_path to the corrections table.

    Args:
        scan_report_path: Path to the <source>_<date>.json scan report.
        approved_path:    Path to the <source>_<date>_approved.json file.
        corrections_dir:  Directory for corrections/<source_id>.json output.
        dry_run:          If True, print what would be done but write nothing.

    Raises:
        FileNotFoundError: if either input file does not exist.
        ValueError: if an approved candidate ID is not in the scan report,
                    or if a collision with an existing correction is detected.
    """
    # Load inputs
    if not scan_report_path.exists():
        raise FileNotFoundError(f"Scan report not found: {scan_report_path}")
    if not approved_path.exists():
        raise FileNotFoundError(f"Approved file not found: {approved_path}")

    with open(scan_report_path, encoding="utf-8") as f:
        scan_report = json.load(f)
    with open(approved_path, encoding="utf-8") as f:
        approved_data = json.load(f)

    source_id: str = scan_report["source_id"]
    cand_by_id = {c["id"]: c for c in scan_report.get("candidates", [])}

    approved_ids: list[str] = approved_data.get("approved", [])
    rejected_ids: list[str] = approved_data.get("rejected", [])
    notes: dict[str, str] = approved_data.get("notes", {})
    reviewed_by: str = approved_data.get("reviewed_by", "unknown")
    reviewed_at: str = approved_data.get("reviewed_at", "")

    # Validate: all approved IDs must exist in the scan report
    for cid in approved_ids:
        if cid not in cand_by_id:
            raise ValueError(
                f"Approved candidate '{cid}' not found in scan report "
                f"'{scan_report_path.name}'. Aborting -- nothing written."
            )

    # Build new correction entries from approved candidates
    new_corrections = []
    for cid in approved_ids:
        c = cand_by_id[cid]
        new_corrections.append({
            "bad": c["value"],
            "good": c["suggestion"],
            "reason": c["reason"],
            "approved_by": reviewed_by,
            "approved_at": reviewed_at,
            "candidate_id": cid,
        })

    # Load existing corrections (if any)
    corrections_dir = Path(corrections_dir)
    corr_file = corrections_dir / f"{source_id}.json"
    existing_corrections: list[dict] = []
    if corr_file.exists():
        with open(corr_file, encoding="utf-8") as f:
            existing_data = json.load(f)
        existing_corrections = existing_data.get("corrections", [])

    # Build lookup structures for collision and idempotency checks
    existing_cand_ids = {e.get("candidate_id") for e in existing_corrections}
    # Map: bad_value -> (candidate_id, good_value)
    existing_bad_lookup: dict[str, tuple[str, str]] = {
        e["bad"]: (e.get("candidate_id", ""), e.get("good", ""))
        for e in existing_corrections
    }

    # Collision / idempotency check (per candidate):
    #   - bad value not present                           -> new entry, include
    #   - bad value exists AND candidate_id matches       -> idempotent duplicate, skip silently
    #   - bad value exists AND same fix (bad+good match)  -> same-fix duplicate, skip silently
    #   - bad value exists, different fix                 -> true collision, raise ValueError
    deduped = []
    for nc in new_corrections:
        existing = existing_bad_lookup.get(nc["bad"])
        if existing is not None:
            existing_cid, existing_good = existing
            if existing_cid == nc["candidate_id"]:
                # Exact duplicate from a previous run — skip silently
                continue
            elif existing_good == nc["good"]:
                # Same bad→good fix from a different candidate (e.g. bootstrap vs LLM run)
                # Idempotent: the correction is already correct — skip silently
                continue
            else:
                raise ValueError(
                    f"Collision: correction for '{nc['bad']}' already exists in "
                    f"{corr_file} (candidate '{existing_cid}', fix '{existing_good}'). "
                    f"New approval wants '{nc['good']}' (candidate '{nc['candidate_id']}'). "
                    "Aborting -- nothing written. "
                    "Review the existing entry and the approval before re-running."
                )
        deduped.append(nc)

    # Print whitelist notes from rejected candidates
    whitelist_hints = []
    for cid, note in notes.items():
        if cid in rejected_ids and "whitelist" in note.lower():
            c = cand_by_id.get(cid, {})
            whitelist_hints.append((c.get("value", cid), note))

    if whitelist_hints:
        print("Whitelist suggestions from rejected candidates (add manually to config):")
        for val, note in whitelist_hints:
            print(f"  {val}: {note}")

    # Dry-run: print summary and exit without writing
    if dry_run:
        print(f"DRY RUN -- would add {len(deduped)} correction(s) to {corr_file}")
        for nc in deduped:
            print(f"  {nc['bad']} -> {nc['good']}  ({nc['reason']})")
        print("Re-run with --apply to write.")
        return

    # Write
    corrections_dir.mkdir(parents=True, exist_ok=True)
    all_corrections = existing_corrections + deduped
    output = {
        "source_id": source_id,
        "corrections": all_corrections,
    }
    with open(corr_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=True)
        f.write("\n")
    print(f"Wrote {len(deduped)} new correction(s) to {corr_file}")
    print(f"Total corrections in table: {len(all_corrections)}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point. DRY_RUN by default; use --apply to write."""
    parser = argparse.ArgumentParser(
        description="Apply reviewer-approved OCR corrections to the corrections table."
    )
    parser.add_argument("--scan-report", required=True,
                        help="Path to the scan report JSON file.")
    parser.add_argument("--approved", required=True,
                        help="Path to the _approved.json file.")
    parser.add_argument(
        "--apply", action="store_true",
        help="Write corrections to disk. Omit for dry-run (default: dry-run).",
    )
    args = parser.parse_args()

    scan_path = Path(args.scan_report)
    approved_path = Path(args.approved)
    corrections_dir = Path(__file__).resolve().parent / "corrections"

    # API-01: DRY_RUN appears in if DRY_RUN: conditional
    if DRY_RUN and not args.apply:
        print("DRY RUN mode. Use --apply to write changes.")

    dry = not args.apply

    try:
        apply(scan_path, approved_path, corrections_dir, dry_run=dry)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
