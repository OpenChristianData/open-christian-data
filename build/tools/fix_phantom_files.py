"""
fix_phantom_files.py -- Fix file naming for phantom-duplicate IA scan pages.

When IA scandata assigns the same leaf to two body page numbers, the fetcher
downloads the leaf image to BOTH page_NNNN.jpg files. This leaves a block of
consecutive pages with wrong content (shifted by N pages) and N phantom files
that are duplicates of earlier pages.

This script:
  1. Identifies the phantom blocks from the manifest gaps array
  2. Renames files to close the numbering gap (highest page first to avoid collisions)
  3. Reports which new terminal pages need to be fetched from IA

Default mode: DRY RUN -- shows what would change without touching files.
Use --execute to apply renames.

NOTE: Run fix_manifest_gaps.py FIRST so phantom pages are correctly tagged
in the manifest. Then run this script. Then run generate_page_order.py to
regenerate page_order.json with correct file names.

After renaming, fetch the new terminal pages:
    py -3 build/tools/fetch_ia_pages.py --volume N --pages X,Y,...

Usage:
    py -3 build/tools/fix_phantom_files.py [--vol N] [--execute]
"""

import argparse
import collections
import json
import os
import pathlib
import sys

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT = pathlib.Path(__file__).parents[2]
MANIFEST_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _phantom_blocks_from_manifest(vol_num: int) -> list[tuple[int, int]]:
    """Return list of (first_phantom, last_phantom) tuples from manifest gaps."""
    vol_id = f"vol_{vol_num:02d}"
    manifest_path = MANIFEST_DIR / f"{vol_id}.manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    page_count = manifest["page_count"]

    phantom_pages = sorted(
        g["page_num"]
        for g in manifest.get("gaps", [])
        if isinstance(g.get("page_num"), int)
        and g["page_num"] <= page_count
        and g.get("status") in ("phantom_duplicate", "phantom_inversion")
    )

    if not phantom_pages:
        return []

    # Group consecutive phantoms into blocks
    blocks: list[tuple[int, int]] = []
    start = phantom_pages[0]
    prev = phantom_pages[0]
    for pn in phantom_pages[1:]:
        if pn != prev + 1:
            blocks.append((start, prev))
            start = pn
        prev = pn
    blocks.append((start, prev))
    return blocks


def _get_last_page_and_leaf(vol_num: int) -> tuple[int, int]:
    """Return (last_page_num, last_leaf_id) from manifest pages array."""
    vol_id = f"vol_{vol_num:02d}"
    manifest = json.loads((MANIFEST_DIR / f"{vol_id}.manifest.json").read_bytes())
    pages = sorted(manifest["pages"], key=lambda p: p["page_num"])
    last = pages[-1]
    return last["page_num"], int(last["ia_leaf_id"])


def _get_offset(vol_num: int) -> int:
    """Return the leaf-to-page offset from the first body page entry."""
    vol_id = f"vol_{vol_num:02d}"
    manifest = json.loads((MANIFEST_DIR / f"{vol_id}.manifest.json").read_bytes())
    pages = sorted(manifest["pages"], key=lambda p: p["page_num"])
    p1 = pages[0]
    return int(p1["ia_leaf_id"]) - p1["page_num"]


def _phantom_gap_status(vol_num: int) -> dict[int, str]:
    """Return {page_num: gap_status} for phantom-type gaps only."""
    vol_id = f"vol_{vol_num:02d}"
    manifest = json.loads((MANIFEST_DIR / f"{vol_id}.manifest.json").read_bytes())
    page_count = manifest["page_count"]
    return {
        g["page_num"]: g["status"]
        for g in manifest.get("gaps", [])
        if isinstance(g.get("page_num"), int)
        and g["page_num"] <= page_count
        and g.get("status") in ("phantom_duplicate", "phantom_inversion")
    }


def _phantom_map_from_manifest(vol_num: int) -> dict[int, int]:
    """Return {phantom_pn: real_pn} mapping from manifest pages array."""
    vol_id = f"vol_{vol_num:02d}"
    manifest = json.loads((MANIFEST_DIR / f"{vol_id}.manifest.json").read_bytes())
    leaf_to_pages: dict[str, list[int]] = {}
    for p in manifest.get("pages", []):
        leaf = p.get("ia_leaf_id")
        if leaf:
            leaf_to_pages.setdefault(leaf, []).append(p["page_num"])
    result: dict[int, int] = {}
    for leaf, pnums in leaf_to_pages.items():
        if len(pnums) > 1:
            pnums_sorted = sorted(pnums)
            for phantom in pnums_sorted[1:]:
                result[phantom] = pnums_sorted[0]
    return result


def plan_volume(vol_num: int) -> dict:
    """Compute the rename plan for one volume. Returns a dict with the plan."""
    vol_id = f"vol_{vol_num:02d}"
    vol_dir = MANIFEST_DIR / vol_id

    blocks = _phantom_blocks_from_manifest(vol_num)
    if not blocks:
        return {"vol": vol_id, "renames": [], "fetch_needed": [], "phantom_count": 0}

    gap_status = _phantom_gap_status(vol_num)   # {page_num: status}
    phantom_map = _phantom_map_from_manifest(vol_num)  # {phantom: real}

    # All page_*.jpg files on disk, sorted numerically
    on_disk_set: set[int] = set()
    for f in vol_dir.glob("page_*.jpg"):
        try:
            on_disk_set.add(int(f.stem.split("_")[1]))
        except (ValueError, IndexError):
            pass
    on_disk = sorted(on_disk_set)

    # Phantom set = all pages with phantom status in gaps
    phantom_set: set[int] = set(gap_status.keys())

    # Determine which phantom files to DELETE vs RENAME.
    #
    # Standard case (most volumes): phantom_duplicate files contain the same leaf
    # as a lower-numbered "real" page. That real page is NOT being deleted, so
    # the phantom_duplicate is a true extra copy -- DELETE it.
    #
    # Vol_08 inversion case: phantom_inversion pages (96-97) come BEFORE the
    # real content (98-107) and duplicate leaves 128-129. The phantom_duplicate
    # pages (108-109) also point to leaves 128-129 and are the only surviving
    # copy once the phantom_inversions are deleted. They must be RENAMED instead.
    #
    # General rule:
    #   - phantom_inversion -> DELETE
    #   - phantom_duplicate whose "real" (lower-numbered) page is itself being
    #     deleted (is phantom_inversion) -> RENAME (it is the only surviving copy)
    #   - phantom_duplicate whose "real" page is NOT being deleted -> DELETE

    inversion_set = {pn for pn, st in gap_status.items() if st == "phantom_inversion"}
    delete_set: set[int] = set(inversion_set)

    for pn, st in gap_status.items():
        if st == "phantom_duplicate":
            real_pn = phantom_map.get(pn)
            if real_pn is not None and real_pn in inversion_set:
                # Real copy is being deleted -- keep this one (will be renamed)
                pass
            else:
                # Real copy exists and is not being deleted -- this is extra, delete it
                delete_set.add(pn)

    # Files to include in rename: all on-disk files >= first_phantom, NOT in delete_set
    first_phantom = blocks[0][0]
    files_to_rename_sorted = sorted(
        pn for pn in on_disk_set if pn >= first_phantom and pn not in delete_set
    )

    # Build rename plan: each file is assigned a new sequential number starting from first_phantom
    rename_plan: list[tuple[int, int]] = []
    for rank, old_pn in enumerate(files_to_rename_sorted):
        new_pn = first_phantom + rank
        if new_pn != old_pn:
            rename_plan.append((old_pn, new_pn))

    # Pages to delete (phantom files on disk that are in delete_set)
    phantoms_to_delete = sorted(delete_set & on_disk_set)

    # After deleting and renaming, the new last page number =
    # (total files kept and renamed) - 1 + first_phantom
    # = len(files_to_rename_sorted) - 1 + first_phantom
    new_last = first_phantom + len(files_to_rename_sorted) - 1

    manifest = json.loads((MANIFEST_DIR / f"{vol_id}.manifest.json").read_bytes())
    page_count = manifest["page_count"]

    # Leaves that need fetching: pages from (new_last+1) to page_count
    # Leaf = page + offset (from the pre-phantom section)
    offset = _get_offset(vol_num)
    fetch_pages = list(range(new_last + 1, page_count + 1))
    fetch_leaves = [pn + offset for pn in fetch_pages]

    return {
        "vol": vol_id,
        "phantom_blocks": blocks,
        "phantom_count": len(phantom_set),
        "deleted_count": len(phantoms_to_delete),
        "phantoms_to_delete": phantoms_to_delete,
        "rename_count": len(rename_plan),
        "rename_plan": rename_plan,  # [(old, new), ...]
        "new_last_page": new_last,
        "page_count": page_count,
        "fetch_pages": fetch_pages,
        "fetch_leaves": fetch_leaves,
        "offset": offset,
    }


def execute_renames(plan: dict) -> None:
    """Apply file renames and deletions for one volume."""
    vol_id = plan["vol"]
    vol_dir = MANIFEST_DIR / vol_id

    # Step 1: delete phantom files first to free their slots for the renames below.
    # All renames are downward shifts (new_pn < old_pn), so the lowest target slot
    # (occupied by the phantom file) must be freed before any rename can land there.
    deleted = 0
    for pn in plan["phantoms_to_delete"]:
        path = vol_dir / f"page_{pn:04d}.jpg"
        if path.exists():
            path.unlink()
            deleted += 1
        else:
            print(f"  NOTE: phantom file already gone: {path.name}")

    # Step 2: rename in ASCENDING order (lowest -> highest) for downward shifts.
    # After deleting the phantom at position N, renaming N+2->N frees N+2 for the
    # next rename (N+3->N+1), and so on without collisions.
    rename_plan = sorted(plan["rename_plan"], key=lambda x: x[0])
    renamed = 0
    for old_pn, new_pn in rename_plan:
        old_path = vol_dir / f"page_{old_pn:04d}.jpg"
        new_path = vol_dir / f"page_{new_pn:04d}.jpg"
        if not old_path.exists():
            print(f"  WARNING: expected file missing: {old_path.name}", file=sys.stderr)
            continue
        if new_path.exists():
            print(f"  WARNING: target already exists: {new_path.name}", file=sys.stderr)
            continue
        old_path.rename(new_path)
        renamed += 1

    print(f"  {vol_id}: renamed {renamed} files, deleted {deleted} phantom files")
    _clear_phantom_gaps(vol_id, vol_dir)


def _clear_phantom_gaps(vol_id: str, vol_dir: "pathlib.Path") -> None:
    """Remove phantom gap entries from the manifest now that files are corrected.

    After execute_renames, phantom_duplicate/phantom_inversion pages that existed
    as wrong-content files are either deleted or replaced by correctly-renamed files.
    Keeping the phantom gap entries would cause generate_page_order.py to mark those
    pages as 'phantom_duplicate' in page_order.json even though the files are now
    correct. Remove them so those pages are correctly assessed as 'present'.

    Permanently-missing gap entries are NOT touched.
    """
    manifest_path = MANIFEST_DIR / f"{vol_id}.manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    gaps = manifest.get("gaps", [])

    # Keep only non-phantom gap entries (permanently_missing, unresolved, resolved)
    kept = [
        g for g in gaps
        if g.get("status") not in ("phantom_duplicate", "phantom_inversion")
    ]
    removed = len(gaps) - len(kept)
    if removed == 0:
        return

    manifest["gaps"] = kept
    tmp = manifest_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, manifest_path)
    print(f"  {vol_id}: cleared {removed} phantom gap entries from manifest")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan or execute file renames to fix phantom IA scan pages"
    )
    parser.add_argument("--vol", type=int, help="Single volume (1-13). Default: all affected")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually rename files (default is dry-run)",
    )
    args = parser.parse_args()

    if args.vol:
        vols = [args.vol]
    else:
        # All volumes with phantom_duplicate gaps
        vols = [1, 2, 5, 6, 8, 10, 11]

    mode = "EXECUTE" if args.execute else "DRY RUN"
    print(f"Phantom file fix plan [{mode}]")
    print("=" * 60)

    all_fetch_cmds: list[str] = []

    for vol_num in vols:
        plan = plan_volume(vol_num)
        vol_id = plan["vol"]

        if plan["phantom_count"] == 0:
            print(f"\n{vol_id}: no phantom pages -- skip")
            continue

        print(f"\n{vol_id}:")
        print(f"  Phantom blocks: {plan['phantom_blocks']}")
        print(f"  Phantom files to delete: {plan['phantoms_to_delete']}")
        print(f"  Files to rename: {plan['rename_count']}")

        if plan["rename_count"] <= 20:
            for old, new in plan["rename_plan"]:
                print(f"    page_{old:04d}.jpg -> page_{new:04d}.jpg")
        else:
            first5 = plan["rename_plan"][:5]
            last5 = plan["rename_plan"][-5:]
            for old, new in first5:
                print(f"    page_{old:04d}.jpg -> page_{new:04d}.jpg")
            print(f"    ... ({plan['rename_count'] - 10} more) ...")
            for old, new in last5:
                print(f"    page_{old:04d}.jpg -> page_{new:04d}.jpg")

        if plan["fetch_pages"]:
            pages_str = ",".join(str(p) for p in plan["fetch_pages"])
            cmd = (
                f"py -3 build/tools/fetch_ia_pages.py "
                f"--volume {vol_num} --pages {pages_str}"
            )
            print(f"  After renames, fetch {len(plan['fetch_pages'])} new pages:")
            print(f"    {cmd}")
            print(f"    (leaves {plan['fetch_leaves']}, offset={plan['offset']})")
            all_fetch_cmds.append(cmd)
        else:
            print(f"  No new pages to fetch (last page {plan['new_last_page']} == page_count {plan['page_count']})")

        if args.execute:
            execute_renames(plan)

    if not args.execute:
        print("\n" + "=" * 60)
        print("DRY RUN complete -- no files changed.")
        print("Review the plan above, then re-run with --execute to apply.")
        if all_fetch_cmds:
            print("\nAfter executing renames, run these fetch commands:")
            for cmd in all_fetch_cmds:
                print(f"  {cmd}")
        print("\nAfter fetching, regenerate page_orders:")
        print("  py -3 build/tools/generate_page_order.py")
        print("  py -3 build/tools/generate_vol01_page_order.py")
    else:
        print("\n" + "=" * 60)
        print("Renames complete. Next steps:")
        if all_fetch_cmds:
            print("1. Fetch new terminal pages:")
            for cmd in all_fetch_cmds:
                print(f"   {cmd}")
            print("2. Regenerate page_orders:")
        else:
            print("1. Regenerate page_orders:")
        print("   py -3 build/tools/generate_page_order.py")
        print("   py -3 build/tools/generate_vol01_page_order.py")
        print("3. Commit manifests + page_orders:")
        print("   git add -f raw/internet-archive/schaff-herzog-pages/*.manifest.json")
        print("   git add raw/internet-archive/schaff-herzog-pages/*/page_order.json")


if __name__ == "__main__":
    main()
