"""backfill_maclaren_osis.py
One-shot patch script: backfill primary_reference.osis for all 1,263 Maclaren entries.

Maclaren's Expositions of Holy Scripture was parsed from 15 PG volumes and has
primary_reference.raw populated for every entry, but primary_reference.osis was
left empty.  This script runs parse_maclaren_ref() on every raw string and writes
the result back into the JSON file.

REL-03 exception: one-shot patch script -- prints summary to stdout, no log file.
TEST-05: run twice to verify idempotency before declaring done.

Usage:
    py -3 build/scripts/backfill_maclaren_osis.py
"""

import json
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = REPO_ROOT / "data" / "sermons" / "maclaren-expositions.json"

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ocd_kernel.lib.bible_ref_normalizer import parse_maclaren_ref  # noqa: E402


def main() -> None:
    start = time.time()

    # --- Load ---
    print(f"Loading {DATA_FILE} ...")
    with open(DATA_FILE, encoding="utf-8") as fh:
        doc = json.load(fh)

    entries = doc["data"]
    total = len(entries)
    print(f"  {total} entries")

    # --- Process ---
    n_empty_raw = 0        # raw was empty or missing -- skip
    n_already_done = 0     # osis already populated (idempotency check)
    n_success = 0          # parsed successfully (non-empty osis result)
    n_unparseable = 0      # raw present but parse returned []
    unparseable: list[tuple[int, str]] = []  # (index, raw) for failed entries

    for idx, entry in enumerate(entries):
        ref = entry.get("primary_reference") or {}
        raw = (ref.get("raw") or "").strip()

        if not raw:
            n_empty_raw += 1
            continue

        existing_osis = ref.get("osis") or []
        if existing_osis:
            # Already backfilled -- skip to keep script idempotent.
            n_already_done += 1
            continue

        osis = parse_maclaren_ref(raw)

        if osis:
            entry["primary_reference"]["osis"] = osis
            n_success += 1
        else:
            n_unparseable += 1
            unparseable.append((idx, raw))

    # --- Report unparseable entries ---
    if unparseable:
        print(f"\n  WARNING: {len(unparseable)} entries could not be parsed:")
        for idx, raw in unparseable:
            entry_id = entries[idx].get("entry_id", f"[{idx}]")
            print(f"    [{idx}] {entry_id!r}: raw={raw!r}")

    # --- Write back ---
    print(f"\nWriting {DATA_FILE} ...")
    with open(DATA_FILE, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    print("  Done.")

    # --- Verify population (PIPE-09) ---
    with open(DATA_FILE, encoding="utf-8") as fh:
        verify_doc = json.load(fh)
    verify_entries = verify_doc["data"]
    populated = sum(
        1 for e in verify_entries
        if e.get("primary_reference", {}).get("osis")
    )
    print(f"\n  Verification: {populated} / {total} entries have non-empty osis")

    # --- Summary ---
    elapsed = time.time() - start
    print(f"\nSummary:")
    print(f"  Total entries:      {total}")
    print(f"  Empty raw (skip):   {n_empty_raw}")
    print(f"  Already backfilled: {n_already_done}")
    print(f"  Newly parsed:       {n_success}")
    print(f"  Unparseable:        {n_unparseable}")
    print(f"  Elapsed:            {elapsed:.1f}s")

    if n_unparseable > 0:
        print(f"\n  ACTION REQUIRED: {n_unparseable} entries returned empty osis.")
        print("  See unparseable list above. Extend parse_maclaren_ref() in")
        print("  build/lib/bible_ref_normalizer.py, or document the reason")
        print("  these entries cannot be normalised.")
        sys.exit(1)


if __name__ == "__main__":
    main()
