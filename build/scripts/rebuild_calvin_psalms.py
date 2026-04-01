"""
rebuild_calvin_psalms.py
========================
Fix the Calvin Psalms misindexing in data/commentaries/calvin/psalms.json.

The SWORD module packed entries from multiple Calvin psalms into single OSIS
chapter slots (e.g. Ps.22.* contains commentary for Calvin's Psalms 20, 21, 22).
Calvin's commentary text contains "PSALM N" headers that give the correct psalm.

Fix: re-key every entry using Calvin's stated psalm number as the chapter, keeping
the verse number unchanged. Entries without a header inherit from the previous one.

Usage:
    py -3 build/scripts/rebuild_calvin_psalms.py [--dry-run]
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from build.scripts.validate_osis import validate_osis_ref as _validate_osis_ref
    _OSIS_VALIDATOR_AVAILABLE = True
except Exception:
    _OSIS_VALIDATOR_AVAILABLE = False


def _filter_cross_refs(refs: list) -> list:
    """Strip cross_references that are not valid OSIS refs (e.g. Calvin section numbers)."""
    if not _OSIS_VALIDATOR_AVAILABLE or not refs:
        return refs
    return [r for r in refs if isinstance(r, str) and _validate_osis_ref(r)[0]]

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INPUT_FILE = REPO_ROOT / "data" / "commentaries" / "calvin" / "psalms.json"
OUTPUT_FILE = INPUT_FILE  # overwrite in-place (git tracks history)
DRY_RUN = "--dry-run" in sys.argv

# Regex to find "PSALM N" header in the first 120 chars of commentary text.
# Matches "PSALM 20", "PSALM 20.", "Psalm 20 " etc.
PSALM_HEADER_RE = re.compile(r'PSALM\s+(\d+)', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def rebuild() -> None:
    print(f"Reading {INPUT_FILE}")
    raw = INPUT_FILE.read_text(encoding="utf-8")
    data = json.loads(raw)

    entries = data["data"]
    print(f"  {len(entries)} entries to process")

    # Sort by OSIS chapter then verse BEFORE processing so that header carry-forward
    # is deterministic: entries within each misaligned chapter slot are processed in
    # verse order, and the first "PSALM N" header in each slot sets context for all
    # subsequent no-header entries in that same slot.
    def _input_sort_key(e: dict) -> tuple:
        parts = e.get("verse_range_osis", "Ps.0.0").split(".")
        ch = int(re.sub(r'\D', '', parts[1])) if len(parts) > 1 else 0
        vs = int(re.sub(r'\D', '', parts[2])) if len(parts) > 2 else 0
        return (ch, vs)

    entries = sorted(entries, key=_input_sort_key)

    fixed = 0
    unchanged = 0
    no_header_inherited = 0

    current_psalm: int | None = None
    new_entries = []

    for entry in entries:
        osis = entry["verse_range_osis"]
        parts = osis.split(".")
        if len(parts) != 3 or parts[0] != "Ps":
            new_entries.append(entry)
            unchanged += 1
            continue

        orig_chapter = int(parts[1])
        verse = int(re.sub(r'\D', '', parts[2]))

        # Extract "PSALM N" from the start of the commentary text.
        text = entry.get("commentary_text", "")
        m = PSALM_HEADER_RE.search(text[:120])
        if m:
            current_psalm = int(m.group(1))
        elif current_psalm is None:
            # No header seen yet — skip (shouldn't happen in well-formed data)
            new_entries.append(entry)
            unchanged += 1
            continue

        if current_psalm == orig_chapter:
            clean = dict(entry)
            clean["cross_references"] = _filter_cross_refs(entry.get("cross_references", []))
            new_entries.append(clean)
            unchanged += 1
        else:
            # Re-key to the correct psalm chapter.
            new_chapter = current_psalm
            new_osis = f"Ps.{new_chapter}.{verse}"
            new_entry = dict(entry)
            new_entry["verse_range_osis"] = new_osis
            new_entry["verse_range"] = str(verse)
            new_entry["chapter"] = new_chapter
            # Rebuild entry_id: resource_id.Ps.chapter.verse
            old_id = entry.get("entry_id", "")
            # entry_id format: calvin.psalms.Ps.CHAPTER.VERSE
            new_entry["entry_id"] = re.sub(
                r'Ps\.\d+\.' + str(verse), f'Ps.{new_chapter}.{verse}', old_id
            )
            new_entry["cross_references"] = _filter_cross_refs(entry.get("cross_references", []))
            if m:
                fixed += 1
            else:
                no_header_inherited += 1
                fixed += 1
            new_entries.append(new_entry)

    print(f"  Unchanged (already correct): {unchanged}")
    print(f"  Re-keyed (chapter corrected): {fixed}")

    # Sanity check: are there duplicate verse_range_osis values?
    seen_osis = {}
    dupes = []
    for e in new_entries:
        o = e["verse_range_osis"]
        if o in seen_osis:
            dupes.append(o)
        seen_osis[o] = True

    if dupes:
        print(f"\nWARNING: {len(dupes)} duplicate verse_range_osis values after rebuild:")
        for d in dupes[:10]:
            print(f"  {d}")
        if len(dupes) > 10:
            print(f"  ... and {len(dupes) - 10} more")
        print("\nThis means multiple Calvin psalms share the same verse position.")
        print("The verse numbers from the SWORD module are not strictly per-psalm.")
        print("Duplicates will be disambiguated by appending 'b', 'c' etc.")
        print("Half-verse letter suffixes (e.g. Ps.2.1b) are valid OSIS notation.")
        # Disambiguate duplicates using half-verse suffix on verse_range_osis.
        # e.g. two entries for Ps.2.1 -> Ps.2.1 (first) and Ps.2.1b (second).
        # This is standard scholarly half-verse notation accepted by the validator.
        osis_count: dict[str, int] = {}
        final_entries = []
        for e in new_entries:
            o = e["verse_range_osis"]
            if osis_count.get(o, 0) == 0:
                osis_count[o] = 1
                final_entries.append(e)
            else:
                suffix = chr(ord('a') + osis_count[o])
                osis_count[o] += 1
                parts = o.split(".")
                new_o = f"{parts[0]}.{parts[1]}.{parts[2]}{suffix}"
                e2 = dict(e)
                e2["verse_range_osis"] = new_o
                e2["entry_id"] = e2["entry_id"] + suffix
                final_entries.append(e2)
                print(f"  Disambiguated: {o} -> {new_o}")
        new_entries = final_entries
    else:
        print("  No duplicate verse_range_osis values.")

    # Sort by (chapter, verse) so output is ordered.
    def sort_key(e):
        osis = e["verse_range_osis"]
        parts = osis.split(".")
        ch = int(re.sub(r'\D', '', parts[1])) if len(parts) > 1 else 0
        vs_str = re.sub(r'\D', '', parts[2]) if len(parts) > 2 else '0'
        vs = int(vs_str) if vs_str else 0
        return (ch, vs)

    new_entries.sort(key=sort_key)

    # Update provenance.notes with rebuild note.
    data["data"] = new_entries
    meta = data.get("meta", {})
    provenance = meta.get("provenance", {})
    provenance["notes"] = (
        f"Calvin Psalms rebuilt {date.today()} by rebuild_calvin_psalms.py: "
        f"re-keyed {fixed} entries to correct OSIS chapters using 'PSALM N' headers. "
        "The SWORD module had packed entries from multiple psalms into single chapter slots. "
        "Known limitation: ~6 no-header Psalm 55 commentary entries are misassigned to "
        "Psalm 54 because they lack a 'PSALM N' header and follow Psalm 54 content in "
        "the SWORD module's chapter slot — cannot be corrected by header detection alone."
    )
    meta["provenance"] = provenance
    data["meta"] = meta

    if DRY_RUN:
        print(f"\nDRY RUN — would write {len(new_entries)} entries to {OUTPUT_FILE}")
        # Show sample corrections
        print("\nSample corrections:")
        shown = 0
        for orig, new in zip(entries, new_entries):
            if orig.get("verse_range_osis") != new.get("verse_range_osis"):
                print(f"  {orig['verse_range_osis']:15} -> {new['verse_range_osis']}")
                shown += 1
                if shown >= 10:
                    print("  ...")
                    break
    else:
        out = json.dumps(data, ensure_ascii=False, indent=2)
        OUTPUT_FILE.write_text(out, encoding="utf-8")
        print(f"\nWritten: {OUTPUT_FILE}")
        print(f"  {len(new_entries)} entries")


if __name__ == "__main__":
    rebuild()
