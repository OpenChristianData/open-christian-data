"""
reconcile_manifest_pages.py -- Fix manifest pages arrays after phantom file renames.

When fix_phantom_files.py renames/deletes files, it clears phantom gap entries from
the manifest but leaves the pages array stale:
  - Phantom duplicate entries (removed files) are still listed
  - Page_num values for renamed pages still show pre-fix numbers

This script updates the pages array for the 7 phantom-affected volumes:
  1. Removes entries for phantom pages that were deleted
  2. Renumbers remaining pages >= first_phantom sequentially

Idempotent: volumes with no duplicate leaf IDs in their pages array are skipped.

Usage:
    py -3 build/tools/reconcile_manifest_pages.py           # dry run
    py -3 build/tools/reconcile_manifest_pages.py --execute # write changes
    py -3 build/tools/reconcile_manifest_pages.py --vol 2   # single volume
"""

import argparse
import json
import os
import pathlib
import sys

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT = pathlib.Path(__file__).parents[2]
MANIFEST_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"

# Vol_08 is the only inversion case where the LOWER-numbered phantom pages
# are deleted (not the higher). The leaf at the lower phantom page (96) jumps
# 11 positions from the preceding non-phantom page (95: leaf 0117 -> 96: leaf 0128),
# confirming the lower pages contain out-of-order content. Hardcode to avoid
# misclassifying this as a standard case.
VOL_08_PAGES_TO_REMOVE = {96, 97}


def _find_duplicate_leaf_pages(manifest: dict) -> dict[str, list[int]]:
    """Return {leaf_id: sorted [page_nums]} for leaves appearing more than once."""
    leaf_to_pages: dict[str, list[int]] = {}
    for p in manifest.get("pages", []):
        leaf = p.get("ia_leaf_id")
        if leaf:
            leaf_to_pages.setdefault(leaf, []).append(p["page_num"])
    return {
        leaf: sorted(pns)
        for leaf, pns in leaf_to_pages.items()
        if len(pns) > 1
    }


def _compute_pages_to_remove(vol_num: int, duplicate_leafs: dict[str, list[int]]) -> set[int]:
    """Determine which manifest page entries to remove.

    Standard case (all volumes except vol_08): for each duplicate leaf, the
    LOWEST page_num is the real copy; remove all higher-numbered duplicates.

    Vol_08 exception: hardcoded inversion pages 96-97 are the phantom entries
    to remove (the higher-numbered pages 108-109 have the correct content).
    """
    if vol_num == 8:
        return set(VOL_08_PAGES_TO_REMOVE)

    pages_to_remove: set[int] = set()
    for pns in duplicate_leafs.values():
        # pns is sorted ascending; pns[0] is the real copy, pns[1:] are phantom duplicates
        for phantom_pn in pns[1:]:
            pages_to_remove.add(phantom_pn)
    return pages_to_remove


def reconcile_volume(vol_num: int, dry_run: bool = True) -> None:
    """Update the manifest pages array for one volume."""
    vol_id = f"vol_{vol_num:02d}"
    manifest_path = MANIFEST_DIR / f"{vol_id}.manifest.json"
    manifest = json.loads(manifest_path.read_bytes())

    pages = manifest.get("pages", [])
    if not pages:
        print(f"{vol_id}: no pages array -- skip")
        return

    # Step 1: find duplicate leaf IDs
    duplicate_leafs = _find_duplicate_leaf_pages(manifest)

    if not duplicate_leafs:
        print(f"{vol_id}: no duplicate leaf IDs in pages array -- already clean")
        return

    all_phantom_page_nums = sorted(
        pn for pns in duplicate_leafs.values() for pn in pns
    )
    first_phantom = min(all_phantom_page_nums)

    # Step 2: determine which entries to remove
    pages_to_remove = _compute_pages_to_remove(vol_num, duplicate_leafs)

    print(f"{vol_id}: {len(duplicate_leafs)} duplicate leaf(s), all phantom pages: {all_phantom_page_nums}")
    print(f"  first_phantom={first_phantom}, pages to remove: {sorted(pages_to_remove)}")

    # Step 3: build the sequential renumber plan for remaining entries >= first_phantom
    # Sort all manifest page_nums that are kept and >= first_phantom; assign consecutive
    # positions starting at first_phantom. Pages below first_phantom are unchanged.
    manifest_page_nums = {p["page_num"] for p in pages}
    remaining_from_first = sorted(
        pn for pn in manifest_page_nums
        if pn >= first_phantom and pn not in pages_to_remove
    )

    old_to_new: dict[int, int] = {}
    for k, old_pn in enumerate(remaining_from_first):
        new_pn = first_phantom + k
        if new_pn != old_pn:
            old_to_new[old_pn] = new_pn

    if old_to_new:
        sample_items = list(old_to_new.items())
        show = sample_items[:4] + (sample_items[-2:] if len(sample_items) > 6 else [])
        print(f"  Renumber {len(old_to_new)} entries (sample):")
        for old, new in show:
            print(f"    {old} -> {new}")
        if len(old_to_new) > 6:
            print(f"    ... ({len(old_to_new) - 6} more)")
    else:
        print(f"  No page_num updates needed (entries already at correct positions)")

    # Step 4: build updated pages array
    new_pages = []
    removed_count = 0
    updated_count = 0
    kept_count = 0

    for p in sorted(pages, key=lambda p: p["page_num"]):
        pn = p["page_num"]
        if pn in pages_to_remove:
            removed_count += 1
            continue
        p_copy = dict(p)
        if pn in old_to_new:
            p_copy["page_num"] = old_to_new[pn]
            updated_count += 1
        else:
            kept_count += 1
        new_pages.append(p_copy)

    # Sort by new page_num for clean JSON
    new_pages.sort(key=lambda p: p["page_num"])

    print(
        f"  Result: {len(new_pages)} entries "
        f"(removed {removed_count}, renumbered {updated_count}, unchanged {kept_count})"
    )

    if dry_run:
        print(f"  DRY RUN -- no changes written")
        return

    manifest["pages"] = new_pages
    tmp = manifest_path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(tmp, manifest_path)
    print(f"  Saved {manifest_path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix manifest pages arrays after phantom file renames"
    )
    parser.add_argument("--vol", type=int, help="Single volume (1-13). Default: all phantom volumes")
    parser.add_argument("--execute", action="store_true", help="Write changes (default is dry run)")
    args = parser.parse_args()

    if args.vol:
        vols = [args.vol]
    else:
        vols = [1, 2, 5, 6, 8, 10, 11]

    mode = "EXECUTE" if args.execute else "DRY RUN"
    print(f"Manifest pages array reconciliation [{mode}]")
    print("=" * 60)

    for vol_num in vols:
        print()
        reconcile_volume(vol_num, dry_run=not args.execute)

    print()
    print("=" * 60)
    if not args.execute:
        print("DRY RUN complete -- no files changed.")
        print("Review output above, then re-run with --execute to apply.")
        print()
        print("After executing, regenerate page_orders:")
        print("  py -3 build/tools/generate_page_order.py")
        print("  py -3 build/tools/generate_vol01_page_order.py")
    else:
        print("Done. Regenerate page_orders:")
        print("  py -3 build/tools/generate_page_order.py")
        print("  py -3 build/tools/generate_vol01_page_order.py")


if __name__ == "__main__":
    main()
