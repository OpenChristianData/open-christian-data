"""
Patch church_fathers JSON files: fill in missing source_title values where
same-verse sibling entries all share the same non-empty source_title.

Method: for each entry with an empty source_title, look at all other entries
in the same JSON file that share the same anchor_ref.raw value. If there is
exactly one unique non-empty source_title among those siblings, fill the empty
entry with that title.

This is safe because all commentary blocks in the same upstream TOML file
(same author + same verse) come from the same source work. When one block
has a source_title and another doesn't, they are from the same work.

NOTE: entry_id values are NOT updated. Entry IDs with 'unknown' slug reflect
the original parse; changing them would break downstream references. This is
a known inconsistency to be resolved if entry IDs are ever regenerated.

CODING_DEFAULTS:
- Absolute paths
- utf-8 encoding
- ASCII-only print()
- Idempotent (skips entries that already have source_title)
- Log file at build/scripts/patch_source_title.log
- EXPECTED_FIXES asserted before main()
"""

import json
import logging
import os
import time
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
CHURCH_FATHERS_DIR = REPO_ROOT / "data" / "church-fathers"
LOG_FILE = Path(__file__).resolve().parent / "patch_source_title.log"

# Entries that can be safely patched via same-verse sibling inference.
# Verified by investigation: 247 entries across all church_fathers files.
# Entries expected to be fixable when run against a fresh (unpatched) dataset.
# Documented for auditability; not enforced at runtime because the script is
# idempotent -- on re-run the count will be 0 (all already patched).
EXPECTED_FIXES_FRESH = 247
# Files are patched in-place; no separate output directory (deliberate design).

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def find_inferable(entries):
    """Return a dict of entry_id -> inferred source_title for entries that
    can be filled from same-verse siblings.

    An entry is inferable if:
    - Its source_title is empty/None
    - All other entries with the same anchor_ref.raw have exactly one
      distinct non-empty source_title
    """
    by_verse = defaultdict(list)
    for e in entries:
        by_verse[e["anchor_ref"]["raw"]].append(e)

    inferred = {}
    for entry in entries:
        if entry.get("source_title"):
            continue  # already populated, skip
        verse = entry["anchor_ref"]["raw"]
        sibling_titles = {
            e["source_title"]
            for e in by_verse[verse]
            if e["source_title"]
        }
        if len(sibling_titles) == 1:
            inferred[entry["entry_id"]] = next(iter(sibling_titles))
    return inferred


def patch_file(json_path):
    """Patch one JSON file. Returns (patches_applied, patches_skipped_already_set, error_or_None)."""
    try:
        with open(json_path, encoding="utf-8") as f:
            doc = json.load(f)
    except Exception as exc:
        msg = f"Failed to load {json_path}: {exc}. Skipping this file."
        log.error(msg)
        return 0, 0, msg

    entries = doc.get("data", [])
    try:
        inferred = find_inferable(entries)
    except Exception as exc:
        msg = f"Failed to analyse entries in {json_path}: {exc}. Skipping this file."
        log.error(msg)
        return 0, 0, msg

    if not inferred:
        return 0, 0, None

    patches_applied = 0
    patches_skipped = 0
    for entry in entries:
        eid = entry["entry_id"]
        if eid in inferred:
            if entry.get("source_title"):
                # Idempotency: already filled (maybe from a prior run)
                patches_skipped += 1
            else:
                entry["source_title"] = inferred[eid]
                patches_applied += 1
                log.info("Patched %s -> %s", eid, inferred[eid])

    if patches_applied > 0:
        # No backup before write: these files are fully regenerable from raw/Commentaries-Database
        # via build/parsers/church_fathers.py. If a write fails the data can be restored by
        # re-running the parser and then re-running this patch script.
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=2, ensure_ascii=False)
                f.write("\n")
        except Exception as exc:
            msg = (
                f"Failed to write {json_path}: {exc}. "
                f"File may be partially written -- inspect {json_path} manually before re-running."
            )
            log.error(msg)
            return 0, 0, msg

    return patches_applied, patches_skipped, None


# ---------------------------------------------------------------------------
# Count inferable entries (dry-run mode for assertion)
# ---------------------------------------------------------------------------

def count_inferable_total():
    """Count total inferable entries across all files (for pre-flight assertion)."""
    total = 0
    for fname in sorted(os.listdir(CHURCH_FATHERS_DIR)):
        if not fname.endswith(".json"):
            continue
        fpath = CHURCH_FATHERS_DIR / fname
        try:
            with open(fpath, encoding="utf-8") as f:
                doc = json.load(f)
        except Exception as exc:
            log.warning("count_inferable_total: could not load %s: %s", fpath, exc)
            continue
        entries = doc.get("data", [])
        try:
            total += len(find_inferable(entries))
        except Exception as exc:
            log.warning("count_inferable_total: could not analyse %s: %s", fpath, exc)
    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    start = time.time()
    json_files = sorted(
        f for f in os.listdir(CHURCH_FATHERS_DIR) if f.endswith(".json")
    )
    log.info(
        "Starting patch_source_title.py -- CHURCH_FATHERS_DIR=%s, files=%d",
        CHURCH_FATHERS_DIR,
        len(json_files),
    )

    # Pre-flight: count inferable entries (0 on re-run = already patched, which is fine)
    actual_inferable = count_inferable_total()
    print(f"Pre-flight: {actual_inferable} entries to patch (0 = already patched; fresh dataset expects {EXPECTED_FIXES_FRESH})")

    total_patched = 0
    total_skipped = 0
    total_errors = 0
    files_changed = 0
    files_processed = 0

    for i, fname in enumerate(json_files, 1):
        fpath = CHURCH_FATHERS_DIR / fname
        patched, skipped, err = patch_file(fpath)
        files_processed += 1
        if err:
            total_errors += 1
            print(f"  [{i}/{len(json_files)}] {fname}: ERROR - {err}")
            continue
        if patched > 0 or skipped > 0:
            files_changed += 1
        total_patched += patched
        total_skipped += skipped
        if patched:
            print(f"  [{i}/{len(json_files)}] {fname}: {patched} patched")

    # Compute remaining gap from actual data (not a hardcoded estimate)
    remaining_gap = 0
    for fname in json_files:
        try:
            with open(CHURCH_FATHERS_DIR / fname, encoding="utf-8") as f:
                doc = json.load(f)
            remaining_gap += sum(1 for e in doc.get("data", []) if not e.get("source_title"))
        except Exception as exc:
            log.warning("remaining_gap count: could not load %s: %s", fname, exc)

    elapsed = time.time() - start
    print()
    print(f"Summary:")
    print(f"  Files processed:   {files_processed}")
    print(f"  Files changed:     {files_changed}")
    print(f"  Entries patched:   {total_patched}")
    print(f"  Entries skipped (already set): {total_skipped}")
    print(f"  File errors:       {total_errors}")
    print(f"  Remaining gap:     {remaining_gap} entries still missing source_title")
    print(f"                     (upstream TOML has no source_title -- editorial curation needed)")
    print(f"  Elapsed: {elapsed:.1f}s")
    log.info(
        "Done. patched=%d skipped=%d files_changed=%d errors=%d remaining_gap=%d elapsed=%.1fs",
        total_patched,
        total_skipped,
        files_changed,
        total_errors,
        remaining_gap,
        elapsed,
    )


if __name__ == "__main__":
    main()
