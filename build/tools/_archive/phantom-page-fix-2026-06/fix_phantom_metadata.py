"""
fix_phantom_metadata.py -- Post-reconciliation metadata cleanup for phantom volumes.

After reconcile_manifest_pages.py updates the pages arrays, three metadata fields
still carry pre-fix state:

  1. page_count   -- was the IA scan's claimed page count (includes phantom duplicates).
                     Update to page_count - n_phantoms_removed so that generate_page_order.py
                     iterates the correct range.

  2. manifest_warnings -- "duplicate ia_leaf_id" entries are now stale (phantoms removed
                          from pages array). Remove them; keep other warning types.

  3. gaps (vol_10 only) -- the old permanently_missing and unresolved entries reference
                           pre-fix page numbers. Update to post-fix numbering:
                           - old pp343-367 resolved: keep as-is (position unchanged)
                           - old pp500-504 permanently_missing: REMOVE (now present at
                             new pp492-496 from alternate IA source)
                           - old pp505-516 permanently_missing: rename to new pp497-508
                           - old pp517-529 unresolved: REMOVE (beyond new body of 508)

     gaps (vol_11 only) -- old p509 permanently_missing was the phantom page itself;
                           old pp510-545 unresolved are beyond new body of 505 pages.
                           Remove all of these gap entries.
"""

import json
import os
import pathlib

REPO_ROOT = pathlib.Path(__file__).parents[2]
MANIFEST_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"

# Phantom pages removed per volume: {vol_num: n_phantoms}
PHANTOM_REMOVED = {1: 2, 2: 2, 5: 4, 6: 4, 8: 2, 10: 8, 11: 4}

# Vol_10 gaps remap: (old_start, old_end_inclusive) -> action
# old pp343-367: unchanged (not in gap range affected by phantom shift)
# old pp500-504: remove (now present as alternate-source pages at new 492-496)
# old pp505-516: rename -> new pp497-508 (shift = -8)
# old pp517-529: remove (beyond new body of 508)
VOL_10_GAPS_REMOVE = set(range(500, 505)) | set(range(517, 530))
VOL_10_GAPS_SHIFT_RANGE = range(505, 517)  # -> new pp497-508 (shift of -8)
VOL_10_GAPS_SHIFT = -8

# Vol_11 gaps: remove all stale entries (p509 was the phantom, pp510-545 are beyond body)
VOL_11_GAPS_REMOVE = set(range(509, 546))


def _save(manifest_path: pathlib.Path, manifest: dict) -> None:
    tmp = manifest_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, manifest_path)


def fix_all() -> None:
    for vol_num, n_phantom in PHANTOM_REMOVED.items():
        vol_id = f"vol_{vol_num:02d}"
        path = MANIFEST_DIR / f"{vol_id}.manifest.json"
        manifest = json.loads(path.read_bytes())

        changed = False

        # 1. Update page_count
        old_count = manifest["page_count"]
        new_count = old_count - n_phantom
        if old_count != new_count:
            manifest["page_count"] = new_count
            print(f"{vol_id}: page_count {old_count} -> {new_count}")
            changed = True

        # 2. Remove stale "duplicate ia_leaf_id" warnings from manifest_warnings
        warnings = manifest.get("manifest_warnings", [])
        new_warnings = [w for w in warnings if not w.startswith("duplicate ia_leaf_id")]
        if len(new_warnings) != len(warnings):
            print(f"{vol_id}: removed {len(warnings) - len(new_warnings)} stale duplicate-leaf warnings")
            manifest["manifest_warnings"] = new_warnings
            changed = True

        # 3. Fix gaps for vol_10 and vol_11
        if vol_num == 10:
            gaps = manifest.get("gaps", [])
            new_gaps = []
            removed = 0
            shifted = 0
            for g in gaps:
                pn = g.get("page_num")
                if pn in VOL_10_GAPS_REMOVE:
                    removed += 1
                    continue
                if pn in VOL_10_GAPS_SHIFT_RANGE:
                    g = dict(g)
                    g["page_num"] = pn + VOL_10_GAPS_SHIFT
                    shifted += 1
                new_gaps.append(g)
            new_gaps.sort(key=lambda g: g.get("page_num", 0))
            if removed or shifted:
                print(f"{vol_id}: gaps -- removed {removed}, shifted {shifted} entries")
                manifest["gaps"] = new_gaps
                changed = True

        elif vol_num == 11:
            gaps = manifest.get("gaps", [])
            new_gaps = [g for g in gaps if g.get("page_num") not in VOL_11_GAPS_REMOVE]
            removed = len(gaps) - len(new_gaps)
            if removed:
                print(f"{vol_id}: gaps -- removed {removed} stale entries")
                manifest["gaps"] = new_gaps
                changed = True

        if changed:
            _save(path, manifest)
            print(f"  Saved {path.name}")
        else:
            print(f"{vol_id}: no changes needed")

    print()
    print("Done.")


if __name__ == "__main__":
    fix_all()
