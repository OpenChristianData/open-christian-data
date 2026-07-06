"""Apply a verified NSH true-printed-page map: rename each source leaf (jpg +
its co-indexed primary-scan sidecars) to its true page into a FRESH dir,
rename plate leaves to a position-tied label, and quarantine the rest.

NON-DESTRUCTIVE: copies source -> fresh dir; never mutates or deletes source.
The pure planner ``build_copy_plan`` is the high-blast-radius core (tested);
the I/O wrapper just executes the plan and is verified by the running-header
pixel gate afterward.

Co-indexed primary-scan sidecars (renamed with the jpg): ``.ia-abbyy.json``,
``.ia-abbyy.raw.xml``, ``.azure.json``, ``.azure.raw.json``. The leaf-indexed
ALTERNATE families (``.ia-abbyy-dli.*``, ``.ia-abbyy-haucgoog*.*``) are
DIFFERENT physical scans and are never passed in / never renamed.
"""
from __future__ import annotations

import shutil
from pathlib import Path

# Suffixes that are co-indexed with page_NNNN.jpg (same primary scan) and so
# move with it under the true-page rename. Order is display-only.
COINDEXED_SUFFIXES = (
    ".jpg",
    ".ia-abbyy.json",
    ".ia-abbyy.raw.xml",
    ".azure.json",
    ".azure.raw.json",
)


def _target_stem(fn: int, page_map: dict, plate_map: dict) -> str:
    if fn in page_map:
        return f"page_{page_map[fn]:04d}"
    if fn in plate_map:
        return f"page_{plate_map[fn]}"
    raise ValueError(f"leaf {fn} is neither mapped, plated, nor quarantined")


def build_copy_plan(page_map, plate_map, quarantine, present_suffixes_by_fn):
    """Return (operations, quarantined_fns).

    operations: list of (src_basename, dst_basename) copies into the fresh dir.
    Raises ValueError on a destination-name collision (two leaves -> one name).

    page_map:  {fn:int -> true_page:int}
    plate_map: {fn:int -> label:str}   e.g. {262: "0260_plate01"}
    quarantine: iterable of fn to exclude (recorded, not copied)
    present_suffixes_by_fn: {fn -> [suffixes present on disk for that leaf]}
    """
    quarantine = set(quarantine)
    operations: list[tuple[str, str]] = []
    quarantined: list[int] = []
    seen_dst: dict[str, str] = {}

    for fn in sorted(present_suffixes_by_fn):
        if fn in quarantine:
            quarantined.append(fn)
            continue
        stem = _target_stem(fn, page_map, plate_map)
        for suffix in present_suffixes_by_fn[fn]:
            src = f"page_{fn:04d}{suffix}"
            dst = f"{stem}{suffix}"
            if dst in seen_dst:
                raise ValueError(
                    f"target collision: {dst} from {src} and {seen_dst[dst]}"
                )
            seen_dst[dst] = src
            operations.append((src, dst))
    return operations, quarantined


def execute_copy_plan(operations, src_dir, dst_dir):
    """Copy each (src_basename, dst_basename) from src_dir into dst_dir.

    NON-DESTRUCTIVE: copies (shutil.copy2), never moves/deletes the source.
    Returns (copied_count, missing_srcs). A src that is absent is recorded in
    missing_srcs and skipped (it is never an error to skip -- the caller's
    census determines which suffixes exist).
    """
    src_dir = Path(src_dir)
    dst_dir = Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    missing: list[str] = []
    for src, dst in operations:
        src_path = src_dir / src
        if not src_path.exists():
            missing.append(src)
            continue
        shutil.copy2(src_path, dst_dir / dst)
        copied += 1
    return copied, missing
