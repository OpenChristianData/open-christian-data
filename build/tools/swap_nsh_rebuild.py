"""Swap a freshly-rebuilt NSH volume's IMAGES into the live path -- jpg-only.

The live vol_NN/ dir holds ~7k correctly-true-page-named OCR sidecars
(*.ia-abbyy*.raw.xml / *.json / *.azure.json / coverage.*) alongside the
page_*.jpg images. Only the IMAGES were corrupted by the squeeze; the sidecars
are correct and must be preserved. So this swap replaces ONLY the image files
-- body page_*.jpg, front/back-matter leaf_*.jpg, and plate_*.jpg (plus the
per-volume manifest) -- leaving every sidecar in place.

Reversible by construction (non-destructive): the current live images + manifest
are MOVED to a timestamped quarantine (never deleted), then the rebuild images +
manifest take the live names. Restore by reversing the moves.

Run ONLY after the running-header OCR audit passes on the rebuild dir:
  py -3 build/tools/verify_nsh_running_headers.py --volume 8 --pages all \
      --volume-dir raw/internet-archive/schaff-herzog-pages/vol_08_rebuild

Default is --dry-run (prints the plan). Pass --swap to perform the moves.

  py -3 build/tools/swap_nsh_rebuild.py --volume 8            # dry run
  py -3 build/tools/swap_nsh_rebuild.py --volume 8 --swap     # do it
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# Image filename prefixes the swap moves: body (page_*), front/back matter
# (leaf_*), and illustration plates (plate_*). page_* alone would leave vol_11's
# plates and any front/back-matter images behind in the staging dir.
_SWAP_IMAGE_GLOBS = ("page_*.jpg", "leaf_*.jpg", "plate_*.jpg")

# Primary OCR sidecars the --rekeyed-sidecars swap replaces: numbered body
# (page_NNNN.*) + illustration plates (plate_*.*) for ia-abbyy and azure. The
# four-digit / plate_ prefixes EXCLUDE the leaf-indexed alternates that share
# the dir -- page_leaf*.ia-abbyy.* (different scan), *-dli* / *haucgoog*
# (alternate items, named coverage.ia-abbyy-dli.json etc.) -- which must be
# preserved. Used ONLY for re-keyed volumes (vol_11): the squeeze mis-keyed the
# sidecars too, so the live ones are wrong and the rebuild's re-keyed ones win.
_SWAP_SIDECAR_GLOBS = (
    "page_[0-9][0-9][0-9][0-9].ia-abbyy.json",
    "page_[0-9][0-9][0-9][0-9].ia-abbyy.raw.xml",
    "page_[0-9][0-9][0-9][0-9].azure.json",
    "page_[0-9][0-9][0-9][0-9].azure.raw.json",
    "plate_*.ia-abbyy.json",
    "plate_*.ia-abbyy.raw.xml",
)


def _volume_swap_images(directory: Path) -> list[Path]:
    """Every image the swap must move from / quarantine in a volume dir.

    Body page_*.jpg + front/back-matter leaf_*.jpg + plate_*.jpg. OCR sidecars
    (*.json / *.raw.xml / coverage.*) are NOT images and are never selected.
    """
    images: list[Path] = []
    for pattern in _SWAP_IMAGE_GLOBS:
        images.extend(directory.glob(pattern))
    return sorted(images)


def _volume_swap_sidecars(directory: Path) -> list[Path]:
    """Primary ia-abbyy + azure sidecars the re-keyed swap moves / quarantines.

    Numbered body (page_NNNN.*) and plate (plate_*.*) primary sidecars only. The
    leaf-indexed alternates (page_leaf*, *-dli*, *haucgoog* under coverage.*) and
    the images are NEVER selected -- they are preserved in place. Returns [] for
    an image-only volume.
    """
    sidecars: list[Path] = []
    for pattern in _SWAP_SIDECAR_GLOBS:
        sidecars.extend(directory.glob(pattern))
    return sorted(sidecars)


def rewrite_manifest_local_paths(manifest: dict, vol_id: str) -> int:
    """Repoint local_path values from the staging dir to the live dir.

    The fetcher writes local_path against the rebuild ``--out-dir``
    (``{vol_id}_rebuild/``), but the swap moves the images into the live
    ``{vol_id}/`` dir. Without this rewrite the promoted manifest's local_path
    dangles at the now-empty staging dir. Returns the number of entries changed.

    Handles both manifest shapes: the new unified ``leaves[]`` and the legacy
    ``pages[]`` + ``unnumbered_leaves[]``. (A v4 manifest carries only ``leaves``;
    a legacy one only the two arrays -- iterating all three is safe either way.)
    """
    old = f"{vol_id}_rebuild/"
    new = f"{vol_id}/"
    changed = 0
    for key in ("leaves", "pages", "unnumbered_leaves"):
        for entry in manifest.get(key, []):
            local = entry.get("local_path")
            if local and old in local:
                entry["local_path"] = local.replace(old, new)
                changed += 1
    return changed


def _repoint_manifest(manifest_path: Path, vol_id: str) -> int:
    """Load, repoint local_path to the live dir, and atomically rewrite."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed = rewrite_manifest_local_paths(manifest, vol_id)
    if changed:
        tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
        tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")  # match write_manifest_atomic
        os.replace(tmp, manifest_path)
    return changed


def swap_volume(volume: int, *, do_swap: bool, swap_sidecars: bool = False) -> int:
    vol_id = f"vol_{volume:02d}"
    live_dir = BASE / vol_id
    live_manifest = BASE / f"{vol_id}.manifest.json"
    rebuild_dir = BASE / f"{vol_id}_rebuild"
    rebuild_manifest = BASE / f"{vol_id}_rebuild.manifest.json"

    if not rebuild_dir.is_dir():
        print(f"ERROR: rebuild dir missing: {rebuild_dir}", file=sys.stderr)
        return 2
    if not rebuild_manifest.is_file():
        print(f"ERROR: rebuild manifest missing: {rebuild_manifest}", file=sys.stderr)
        return 2
    if not live_dir.is_dir():
        print(f"ERROR: live dir missing: {live_dir}", file=sys.stderr)
        return 2

    new_jpgs = _volume_swap_images(rebuild_dir)
    old_jpgs = _volume_swap_images(live_dir)
    # When re-keying sidecars too, the primary OCR sidecars also move; with the
    # default (image-only) swap they stay in place.
    new_sidecars = _volume_swap_sidecars(rebuild_dir) if swap_sidecars else []
    old_sidecars = _volume_swap_sidecars(live_dir) if swap_sidecars else []
    moved_names = {p.name for p in old_jpgs} | {p.name for p in old_sidecars}
    n_kept = sum(1 for p in live_dir.iterdir() if p.name not in moved_names)

    # Collision guard: every rebuild file we move in must have a free destination
    # name in live (the matching live primaries are quarantined first below).
    incoming = new_jpgs + new_sidecars
    quarantined_names = moved_names
    collisions = [p.name for p in incoming
                  if (live_dir / p.name).exists() and p.name not in quarantined_names]
    if collisions:
        print(f"ERROR: {len(collisions)} rebuild file(s) would collide with preserved "
              f"live files, e.g. {collisions[:5]}", file=sys.stderr)
        return 2

    stamp = _utc_stamp()
    quarantine_dir = BASE / f"{vol_id}_preswap_jpgs_{stamp}"
    sidecar_quarantine_dir = BASE / f"{vol_id}_preswap_sidecars_{stamp}"
    quarantine_manifest = BASE / f"{vol_id}.manifest.preswap_{stamp}.json"

    print(f"{vol_id}: rebuild has {len(new_jpgs)} new images"
          + (f" + {len(new_sidecars)} re-keyed primary sidecars" if swap_sidecars else "")
          + f"; live has {len(old_jpgs)} old images"
          + (f" + {len(old_sidecars)} squeeze-keyed primary sidecars" if swap_sidecars else "")
          + f" + {n_kept} preserved files (alternates / coverage / page_order).")
    print(f"  old images    -> {quarantine_dir.name}/  (moved, reversible)")
    if swap_sidecars:
        print(f"  old sidecars  -> {sidecar_quarantine_dir.name}/  (moved, reversible)")
    print(f"  new images    -> {live_dir.name}/  (page_*.jpg / leaf_*.jpg / plate_*.jpg)")
    if swap_sidecars:
        print(f"  new sidecars  -> {live_dir.name}/  (page_NNNN.* + plate_*.ia-abbyy.*)")
    print(f"  live manifest -> {quarantine_manifest.name}")
    print(f"  rebuild mfest -> {live_manifest.name}")
    if swap_sidecars:
        print("  PRESERVED: leaf-indexed alternates (page_leaf* / *-dli* / *haucgoog*), "
              "coverage.*, page_order.json -- untouched.")
    else:
        print("  ALL sidecars (*.raw.xml / *.json / coverage.*) stay in place, untouched.")

    if not do_swap:
        print("DRY RUN -- pass --swap to perform the moves.")
        return 0

    # 1. Move old images aside into a fresh quarantine dir (reversible).
    quarantine_dir.mkdir(parents=False, exist_ok=False)
    for p in old_jpgs:
        os.rename(p, quarantine_dir / p.name)
    # 1b. Move old (squeeze-keyed) primary sidecars aside (re-keyed swap only).
    if swap_sidecars and old_sidecars:
        sidecar_quarantine_dir.mkdir(parents=False, exist_ok=False)
        for p in old_sidecars:
            os.rename(p, sidecar_quarantine_dir / p.name)
    # 2. Move the live manifest aside.
    if live_manifest.is_file():
        os.rename(live_manifest, quarantine_manifest)
    # 3. Move new images (and re-keyed sidecars) into the live dir.
    for p in new_jpgs:
        os.rename(p, live_dir / p.name)
    for p in new_sidecars:
        os.rename(p, live_dir / p.name)
    # 4. Promote the rebuild manifest, repointing local_path from the staging
    #    dir to the live dir (the images just moved there).
    os.rename(rebuild_manifest, live_manifest)
    repointed = _repoint_manifest(live_manifest, vol_id)
    print(f"  repointed {repointed} local_path entries -> {vol_id}/")

    remaining = sorted(rebuild_dir.glob("*"))
    print(f"SWAPPED {len(new_jpgs)} images"
          + (f" + {len(new_sidecars)} primary sidecars" if swap_sidecars else "")
          + f". Old images quarantined at {quarantine_dir.name}/"
          + (f", old sidecars at {sidecar_quarantine_dir.name}/" if swap_sidecars and old_sidecars else "")
          + f" (+ {quarantine_manifest.name}).")
    if remaining:
        print(f"  note: rebuild dir still has {len(remaining)} non-swapped file(s).")
    else:
        print(f"  rebuild dir {rebuild_dir.name}/ is now empty.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Swap vol_NN_rebuild IMAGES into the live NSH path.")
    parser.add_argument("--volume", type=int, required=True)
    parser.add_argument("--swap", action="store_true", help="Perform the moves (default: dry run).")
    parser.add_argument("--rekeyed-sidecars", action="store_true",
                        help="Also replace the live primary ia-abbyy + azure sidecars with the "
                             "rebuild's re-keyed ones (for volumes whose sidecars were squeeze-keyed, "
                             "e.g. vol_11). Leaf-indexed alternates are preserved.")
    args = parser.parse_args(argv)
    return swap_volume(args.volume, do_swap=args.swap, swap_sidecars=args.rekeyed_sidecars)


if __name__ == "__main__":
    raise SystemExit(main())
