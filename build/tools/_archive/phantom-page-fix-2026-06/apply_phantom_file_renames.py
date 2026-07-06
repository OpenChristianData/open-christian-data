"""
apply_phantom_file_renames.py -- Apply phantom file deletes + renames for vol_01/02/05/06/08.

execute_renames() in fix_phantom_files.py was run in an earlier session for vol_10 and
vol_11 but not for vol_01, 02, 05, 06, 08. This script applies the known rename plan
directly, using the phantom structure verified by the reconcile_manifest_pages.py dry-run.

Phantom structure (derived from manifest pages array analysis before reconciliation):

  vol_01: leaf 0064 at pages [28, 96, 97] -> remove pages 96,97; shift 98-500 down by 2
  vol_02: 2 phantom pairs -> remove pages 254,255; shift 256-499 down by 2
  vol_05: 4 phantom pairs -> remove pages 451-454; shift 455-508 down by 4
  vol_06: 4 phantom pairs -> remove pages 451-454; shift 455-505 down by 4
  vol_08: inversion -> remove pages 96,97 (wrong content); shift 98-500 down by 2

The ascending rename order prevents overwrite conflicts:
  Delete phantoms first, then rename from lowest old_pn to highest.
"""

import pathlib
import sys

OCD = pathlib.Path(__file__).parents[2]
PAGES_DIR = OCD / "raw" / "internet-archive" / "schaff-herzog-pages"

# Plan: (vol_id, pages_to_delete, old_pn_range_start, old_pn_range_end, first_new_pn)
# For each volume:
#   1. Delete files at pages_to_delete
#   2. For old_pn in range(old_pn_range_start, old_pn_range_end+1): rename to sequential from first_new_pn
#      (skipping pages_to_delete positions)

PLANS = [
    # vol_01: remove [96,97], rename 98-500 -> 96-498
    ("vol_01", {96, 97}, 98, 500, 96),
    # vol_02: remove [254,255], rename 256-499 -> 254-497
    ("vol_02", {254, 255}, 256, 499, 254),
    # vol_05: remove [451,452,453,454], rename 455-508 -> 451-504
    ("vol_05", {451, 452, 453, 454}, 455, 508, 451),
    # vol_06: remove [451,452,453,454], rename 455-505 -> 451-501
    ("vol_06", {451, 452, 453, 454}, 455, 505, 451),
    # vol_08: remove [96,97] (inversion -- wrong content), rename 98-500 -> 96-498
    ("vol_08", {96, 97}, 98, 500, 96),
]


def apply_plan(
    vol_id: str,
    pages_to_delete: set,
    rename_start: int,
    rename_end: int,
    first_new_pn: int,
    dry_run: bool = True,
) -> None:
    vol_dir = PAGES_DIR / vol_id
    print(f"\n{vol_id}: deletes={sorted(pages_to_delete)}, rename {rename_start}-{rename_end} -> "
          f"{first_new_pn}-{first_new_pn + (rename_end - rename_start)}")

    # Step 1: delete phantom files
    for pn in sorted(pages_to_delete):
        f = vol_dir / f"page_{pn:04d}.jpg"
        if f.exists():
            if dry_run:
                print(f"  [DRY] DELETE {f.name}")
            else:
                f.unlink()
                print(f"  DELETE {f.name}")
        else:
            print(f"  SKIP (already absent): {f.name}")

    # Step 2: rename remaining files ascending
    new_pn = first_new_pn
    renamed = 0
    for old_pn in range(rename_start, rename_end + 1):
        old_path = vol_dir / f"page_{old_pn:04d}.jpg"
        new_path = vol_dir / f"page_{new_pn:04d}.jpg"
        if not old_path.exists():
            print(f"  MISSING (expected): {old_path.name}")
            new_pn += 1
            continue
        if old_path == new_path:
            new_pn += 1
            continue
        if dry_run:
            if renamed < 4:
                print(f"  [DRY] RENAME {old_path.name} -> {new_path.name}")
            elif renamed == 4:
                print(f"  [DRY] ... (remaining renames suppressed)")
        else:
            old_path.rename(new_path)
        renamed += 1
        new_pn += 1

    print(f"  -> {renamed} renames, {len(pages_to_delete)} deletes")

    if not dry_run:
        # Verify
        present = sorted(int(f.stem.split("_")[1]) for f in vol_dir.glob("page_*.jpg"))
        expected_max = first_new_pn + (rename_end - rename_start)
        still_phantom = [p for p in pages_to_delete if p in present]
        print(f"  Verified: count={len(present)}, max={max(present) if present else 0}, "
              f"phantom_still_present={still_phantom}")


def main() -> None:
    dry_run = "--execute" not in sys.argv
    mode = "DRY RUN" if dry_run else "EXECUTE"
    print(f"Phantom file renames [{mode}]")
    print("=" * 60)

    for plan in PLANS:
        apply_plan(*plan, dry_run=dry_run)

    print()
    if dry_run:
        print("DRY RUN complete. Re-run with --execute to apply.")
    else:
        print("Done.")


if __name__ == "__main__":
    main()
