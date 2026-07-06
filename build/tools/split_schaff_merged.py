"""split_schaff_merged.py
Bridge between the legacy merged output and the per-volume source layout that
migrate_schaff_herzog.py expects.

The merged schaff-herzog-encyclopedia.json has no volume field, so we cannot
split it mechanically.  Instead we re-parse each cached source file (CCEL XML
or IA _djvu.txt) to obtain the article terms for each volume, reconstruct the
entry_ids using the same slugify + collision-suffix logic the parsers use, and
look each id up in the merged file.  This gives a guaranteed match between the
per-volume splits and the actual merged entries.

Writes:
    data/reference/schaff/encyclopedia/1908-1914/source/vol_NN.json
    (one file per volume that has parseable content)

Usage:
    py -3 build/tools/split_schaff_merged.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MERGED_FILE = REPO_ROOT / "data" / "reference" / "schaff-herzog-encyclopedia.json"
SOURCE_DIR = REPO_ROOT / "data" / "reference" / "schaff" / "encyclopedia" / "1908-1914" / "source"

# Only volumes where the CCEL parser extracts real articles (others are image-only stubs)
CCEL_VOLUMES: dict[int, str] = {
    1: "encyc01",
    2: "encyc02",
    9: "encyc09",
}

# IA volumes cover the image-only CCEL volumes; vol 13 is the index (0 usable entries)
IA_VOLUMES: list[int] = [3, 4, 5, 6, 7, 8, 10, 11, 12]

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_entry(base_id: str, entries_by_id: dict, assigned: set) -> str | None:
    """Return the entry_id in entries_by_id that matches base_id, skipping already-assigned ids.

    Tries base_id first, then base_id-2, base_id-3, ... to handle cross-volume
    term collisions resolved by make_unique_id in the parsers.
    """
    if base_id in entries_by_id and base_id not in assigned:
        return base_id
    counter = 2
    while True:
        candidate = f"{base_id}-{counter}"
        if candidate not in entries_by_id:
            return None  # no more suffixes exist
        if candidate not in assigned:
            return candidate
        counter += 1


def _write_vol(vol_num: int, entries: list, meta: dict, dry_run: bool) -> None:
    out_path = SOURCE_DIR / f"vol_{vol_num:02d}.json"
    payload = json.dumps({"meta": meta, "data": entries}, ensure_ascii=False, indent=2)
    if dry_run:
        logger.info("[dry-run] would write %s (%d entries)", out_path.name, len(entries))
        return
    tmp = out_path.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(out_path)
    logger.info("Wrote %s (%d entries)", out_path.name, len(entries))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def split(dry_run: bool = False) -> None:
    if not MERGED_FILE.exists():
        raise FileNotFoundError(f"Merged file not found: {MERGED_FILE}")

    merged = json.loads(MERGED_FILE.read_text(encoding="utf-8"))
    entries_by_id: dict[str, dict] = {e["entry_id"]: e for e in merged["data"]}
    meta: dict = merged["meta"]
    logger.info("Loaded merged file: %d entries", len(entries_by_id))

    if not dry_run:
        SOURCE_DIR.mkdir(parents=True, exist_ok=True)

    # Import parsers here (after sys.path is set) to avoid module-level side effects
    # at import time from interfering with the path setup above.
    from build.parsers.ccel_schaff_herzog import parse_volume as parse_ccel
    from build.parsers.ccel_schaff_herzog import slugify as slugify_ccel
    from build.parsers.ia_schaff_herzog import parse_volume as parse_ia
    from build.parsers.ia_schaff_herzog import slugify as slugify_ia

    assigned: set[str] = set()
    vol_counts: dict[int, int] = {}
    unmatched_total = 0

    # CCEL volumes first (lower numbers = earlier entries, sets base ids before IA runs)
    for vol_num, vol_id in sorted(CCEL_VOLUMES.items()):
        logger.info("--- CCEL vol %d (%s) ---", vol_num, vol_id)
        raw_articles = parse_ccel(vol_id)
        vol_entries: list[dict] = []
        unmatched = 0
        for article in raw_articles:
            term = article["term"]
            base_id = f"schaff-herzog.{slugify_ccel(term)}"
            eid = _find_entry(base_id, entries_by_id, assigned)
            if eid is None:
                logger.warning("  no match for %r (base_id=%s)", term, base_id)
                unmatched += 1
                continue
            vol_entries.append(entries_by_id[eid])
            assigned.add(eid)
        unmatched_total += unmatched
        vol_counts[vol_num] = len(vol_entries)
        logger.info("  %d entries assigned, %d unmatched", len(vol_entries), unmatched)
        _write_vol(vol_num, vol_entries, meta, dry_run)

    # IA volumes
    for vol_num in IA_VOLUMES:
        logger.info("--- IA vol %d ---", vol_num)
        raw_articles = parse_ia(vol_num)
        vol_entries = []
        unmatched = 0
        for article in raw_articles:
            term = article["term"]
            base_id = f"schaff-herzog.{slugify_ia(term)}"
            eid = _find_entry(base_id, entries_by_id, assigned)
            if eid is None:
                logger.warning("  no match for %r (base_id=%s)", term, base_id)
                unmatched += 1
                continue
            vol_entries.append(entries_by_id[eid])
            assigned.add(eid)
        unmatched_total += unmatched
        vol_counts[vol_num] = len(vol_entries)
        logger.info("  %d entries assigned, %d unmatched", len(vol_entries), unmatched)
        _write_vol(vol_num, vol_entries, meta, dry_run)

    total_assigned = len(assigned)
    total_in_merged = len(entries_by_id)
    unaccounted = total_in_merged - total_assigned

    print("=== SUMMARY ===")
    for vn in sorted(vol_counts):
        print(f"  vol_{vn:02d}.json: {vol_counts[vn]} entries")
    print(f"  Total assigned: {total_assigned} / {total_in_merged}")
    print(f"  Unaccounted (in merged but not matched to any volume): {unaccounted}")
    print(f"  Unmatched raw articles (in parsers but not in merged): {unmatched_total}")
    if not dry_run:
        print(f"  Output: {SOURCE_DIR}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report without writing files.")
    args = parser.parse_args(argv)
    split(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
