"""
fix_manifest_gaps.py -- Correct gap status fields in all NSH volume manifests.

Resolves four gap classes found during scan-coverage analysis:

  resolved           -- Page had a gap note but the file is confirmed present on disk.
                        (Stale investigation artifact -- the image was later downloaded.)
  phantom_duplicate  -- Manifest entry points to a leaf_id also assigned to another page.
                        File on disk has body-page content for a DIFFERENT page number.
  phantom_inversion  -- Vol_08 specific: leaves 128-129 appear out of sequence in
                        IA scandata (scanner inversion). Pages 96-97 in the manifest
                        carry leaf content that belongs to body pages 106-107.
  permanently_missing -- No file on disk and no alternate IA source exists.
                        Vol_10 pp505-516 (12 pages) and vol_13 pp209-211 (3 pages).

Phantom pages absent from the gaps array are added.
Vol_01 pp1-9 stale gaps are cleared (those pages exist as leaf_*.jpg files, not
page_*.jpg, so the standard page_NNNN.jpg disk probe never found them).

Usage:
    py -3 build/tools/fix_manifest_gaps.py [--dry-run]

Outputs updated manifests atomically (write to .tmp then os.replace).
"""

import argparse
import collections
import json
import os
import pathlib

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT = pathlib.Path(__file__).parents[2]
MANIFEST_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"

# Vol_10 and vol_13 permanently-missing page ranges (no JP2 found in any IA source)
_PERMANENTLY_MISSING: dict[int, list[int]] = {
    10: list(range(505, 517)),   # pp505-516 (12 pages)
    13: list(range(209, 212)),   # pp209-211 (3 pages)
}

# Vol_08 phantom-inversion page pairs: (page_num, ia_leaf_id, real_body_page)
# Leaves 128-129 appear BEFORE their correct position in the scan sequence.
# Pages 96-97 in the manifest have leaf content that belongs to body pages 106-107.
_VOL08_INVERSION = [
    (96, "0128", 106),
    (97, "0129", 107),
]

# Vol_13 pp209-211 investigation note
_VOL13_MISSING_NOTE = (
    "No JP2 found in primary IA scan (NewSchaffHerzogEncyclopediaOfReligious) "
    "or alternate item (newschaffherzog03jackgoog). ABBYY text IS present -- "
    "ia-abbyy coverage.json confirms 211 pages_parsed. Image permanently absent."
)

# Vol_10 pp505-516 investigation note
_VOL10_MISSING_NOTE = (
    "No JP2 found in primary IA scan or known alternate sources "
    "(newschaffherzoge0010samu, newschaffherzoge0010unse, "
    "newschaffherzoge0010samu_i3n8, haucgoog). 12 pages absent from IA entirely. "
    "ABBYY text availability unconfirmed for this range."
)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _build_phantom_map(pages: list[dict]) -> dict[int, int]:
    """Return {phantom_page_num: real_page_num} for all duplicate-leaf entries.

    The real page is the lowest page_num that holds a given leaf_id.
    All higher-numbered pages for that leaf are phantoms.
    """
    leaf_to_pages: dict[str, list[int]] = collections.defaultdict(list)
    for p in pages:
        leaf = p.get("ia_leaf_id")
        if leaf:
            leaf_to_pages[leaf].append(p["page_num"])

    phantom_map: dict[int, int] = {}
    for leaf, pnums in leaf_to_pages.items():
        if len(pnums) > 1:
            pnums_sorted = sorted(pnums)
            real_page = pnums_sorted[0]
            for phantom in pnums_sorted[1:]:
                phantom_map[phantom] = real_page
    return phantom_map


def _get_leaf_for_page(pages: list[dict], page_num: int) -> str | None:
    for p in pages:
        if p["page_num"] == page_num:
            return p.get("ia_leaf_id")
    return None


def fix_volume(
    vol_num: int, *, dry_run: bool = False, verbose: bool = False
) -> dict:
    """Fix gaps array for one volume. Returns a change summary dict."""
    vol_id = f"vol_{vol_num:02d}"
    manifest_path = MANIFEST_DIR / f"{vol_id}.manifest.json"

    if not manifest_path.exists():
        return {"vol": vol_id, "error": "manifest missing"}

    manifest = json.loads(manifest_path.read_bytes())
    pages: list[dict] = manifest.get("pages", [])
    gaps: list[dict] = manifest.get("gaps", [])
    page_count: int = manifest.get("page_count", 0)

    vol_dir = MANIFEST_DIR / vol_id
    on_disk: set[int] = set()
    if vol_dir.exists():
        for f in vol_dir.glob("page_*.jpg"):
            try:
                on_disk.add(int(f.stem.split("_")[1]))
            except (ValueError, IndexError):
                pass

    phantom_map = _build_phantom_map(pages)  # {phantom: real}
    pages_by_num = {p["page_num"]: p for p in pages}

    changes: list[str] = []

    # ------------------------------------------------------------------
    # Step 1: Update existing gap entries
    # ------------------------------------------------------------------
    new_gaps: list[dict] = []
    for gap in gaps:
        pn = gap.get("page_num")
        if not isinstance(pn, int):
            new_gaps.append(gap)
            continue

        beyond_count = pn > page_count

        if beyond_count:
            # Beyond page_count -- these are scandata artifacts, leave as-is
            new_gaps.append(gap)
            continue

        old_status = gap.get("status", "")
        page_entry = pages_by_num.get(pn)
        has_path = bool(page_entry and page_entry.get("local_path"))

        # Determine new status
        if pn in _PERMANENTLY_MISSING.get(vol_num, []):
            new_status = "permanently_missing"
            note = _VOL10_MISSING_NOTE if vol_num == 10 else _VOL13_MISSING_NOTE
        elif vol_num == 8 and any(pn == row[0] for row in _VOL08_INVERSION):
            inv_row = next(r for r in _VOL08_INVERSION if r[0] == pn)
            new_status = "phantom_inversion"
            note = (
                f"ia_leaf_id {inv_row[1]} is assigned here due to a scanner "
                f"inversion in vol_08 scandata. ABBYY running header confirms "
                f"leaf {inv_row[1]} = body page {inv_row[2]}. "
                f"File page_{pn:04d}.jpg contains body page {inv_row[2]} content, "
                f"not page {pn}. Real body page {pn} content is in page_{pn + 2:04d}.jpg."
            )
        elif pn in phantom_map:
            new_status = "phantom_duplicate"
            real_page = phantom_map[pn]
            leaf = _get_leaf_for_page(pages, pn) or "?"
            note = (
                f"ia_leaf_id {leaf} is also assigned to page {real_page}. "
                f"File page_{pn:04d}.jpg contains body page {real_page} content, "
                f"not page {pn}. Correct content for page {pn} will require "
                f"renaming subsequent files to close the scandata offset drift."
            )
        elif has_path or pn in on_disk:
            new_status = "resolved"
            note = "File confirmed present on disk. Gap note was stale."
        else:
            # No file found -- keep as unresolved (shouldn't happen except for known-missing)
            new_status = "unresolved"
            note = gap.get("investigation_note", "")

        updated_gap = dict(gap)
        updated_gap["status"] = new_status
        if note:
            updated_gap["investigation_note"] = note

        if old_status != new_status:
            changes.append(f"  p{pn}: {old_status!r} -> {new_status!r}")
            if verbose:
                print(f"  {vol_id} p{pn}: {old_status!r} -> {new_status!r}")

        new_gaps.append(updated_gap)

    # ------------------------------------------------------------------
    # Step 2: Add phantom pages not yet in the gaps array
    # ------------------------------------------------------------------
    existing_gap_pages: set[int] = {g["page_num"] for g in new_gaps if isinstance(g.get("page_num"), int)}

    # Phantoms identified by duplicate-leaf analysis
    for phantom_pn, real_pn in sorted(phantom_map.items()):
        if phantom_pn > page_count:
            continue
        if phantom_pn in existing_gap_pages:
            continue
        leaf = _get_leaf_for_page(pages, phantom_pn) or "?"
        note = (
            f"ia_leaf_id {leaf} is also assigned to page {real_pn}. "
            f"File page_{phantom_pn:04d}.jpg contains body page {real_pn} content, "
            f"not page {phantom_pn}. Correct content for page {phantom_pn} will require "
            f"renaming subsequent files to close the scandata offset drift."
        )
        new_gaps.append({
            "page_num": phantom_pn,
            "status": "phantom_duplicate",
            "investigation_note": note,
        })
        changes.append(f"  p{phantom_pn}: (new) phantom_duplicate")
        if verbose:
            print(f"  {vol_id} p{phantom_pn}: (new) phantom_duplicate")

    # Vol_08: pages 108-109 are already in phantom_map (they're duplicate of leaves
    # shared with pages 96-97) so they are handled by Step 2 above. No extra block
    # needed here -- the phantom_map loop covers them.

    # ------------------------------------------------------------------
    # Step 3: Sort gaps array by page_num for readability
    # ------------------------------------------------------------------
    new_gaps.sort(key=lambda g: g.get("page_num", 999999))

    # ------------------------------------------------------------------
    # Step 4: Write updated manifest
    # ------------------------------------------------------------------
    if not changes:
        return {"vol": vol_id, "changes": 0}

    manifest["gaps"] = new_gaps
    if not dry_run:
        tmp = manifest_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, manifest_path)

    return {"vol": vol_id, "changes": len(changes), "details": changes}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Fix NSH manifest gap statuses")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without writing")
    parser.add_argument("--vol", type=int, help="Single volume to fix (1-13)")
    parser.add_argument("--verbose", action="store_true", help="Print per-page changes")
    args = parser.parse_args()

    vols = range(1, 14) if args.vol is None else [args.vol]
    total_changes = 0

    for vol_num in vols:
        result = fix_volume(vol_num, dry_run=args.dry_run, verbose=args.verbose)
        vol_id = result["vol"]
        if "error" in result:
            print(f"{vol_id}: ERROR -- {result['error']}")
        elif result["changes"] == 0:
            print(f"{vol_id}: no changes")
        else:
            mode = "[DRY RUN] " if args.dry_run else ""
            print(f"{mode}{vol_id}: {result['changes']} gap status changes")
            for detail in result.get("details", []):
                print(detail)
            total_changes += result["changes"]

    print(f"\nTotal gap records updated: {total_changes}" + (" (dry run)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
