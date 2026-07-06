"""Fetch and record front/back-matter and plate images for NSH v4 manifests (P3).

For each volume, reads the v4 ``leaves[]`` manifest and downloads one JP2 image
per ``pending`` front/back/plate leaf from the IA primary scan. Performs blank
detection from the fetched pixels, updates the leaf record in-place, and writes
the manifest atomically.

Usage:
  py -3 build/tools/fetch_nsh_pending_leaves.py --volume 2
  py -3 build/tools/fetch_nsh_pending_leaves.py --volume 2 --dry-run
  py -3 build/tools/fetch_nsh_pending_leaves.py --all-volumes

GOTCHA: Never writes ``unnumbered_leaves[]`` -- only updates ``leaves[]`` in-place.
Running with --dry-run enumerates the worklist without fetching or writing.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.ia_fetch import _download_jp2, fetch_url_bytes, find_jp2_zip  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
INK_THRESHOLD = 0.01       # ink fraction below this -> blank leaf
CRAWL_DELAY = 10           # seconds between IA fetches (rate-limit courtesy)
JPEG_QUALITY = 95

BASE_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
IA_ITEM_ID = "NewSchaffHerzogEncyclopediaOfReligious"
_USER_AGENT = "open-christian-data/nsh-p3 (contact via project repo)"

_P3_VOLUMES = list(range(2, 14))   # vols 2-13; vol 01 skipped (all images present)
_P3_KINDS = frozenset({"front_matter", "back_matter", "plate"})
_JP2_LEAF_RE = re.compile(r"_(\d+)\.jp2$")

logger = logging.getLogger("fetch_nsh_pending_leaves")

# Image provenance fields required by the v4 schema when local_path is present.
_PROVENANCE_FIELDS = (
    "local_path", "ia_leaf_id", "ia_filename", "ia_item_id",
    "sha256", "fetched_at", "image_mode", "image_size",
)


# ---------------------------------------------------------------------------
# Pure helpers (tested in isolation)
# ---------------------------------------------------------------------------

def _is_blank(img: Image.Image) -> bool:
    """True when the image's ink fraction is below INK_THRESHOLD.

    Converts to grayscale; dark pixels (value < 128) are counted as ink.
    This reliably distinguishes scan-artifact blank versos (< 0.5%) from
    real text pages (3-15%) for 19th-century book scans.
    """
    gray = img.convert("L")
    raw = gray.tobytes()   # bytes, one byte per pixel (0=black, 255=white)
    dark = sum(1 for b in raw if b < 128)
    return (dark / len(raw)) < INK_THRESHOLD


def _derive_output_filename(leaf: dict, all_leaves: list[dict]) -> str:
    """Derive the on-disk filename for a pending front/back/plate leaf.

    front_matter / back_matter -> ``leaf_{leaf_num:04d}.jpg`` (design SS1.6).
    plate -> ``plate_{after_page_num:04d}_{seq:02d}.jpg`` where seq is the
    1-based ordinal of this plate among plates sharing the same after_page_num,
    sorted by leaf_num (vol_11 precedent: plate_0260_01.jpg, plate_0260_02.jpg).
    """
    kind = leaf["kind"]
    leaf_num = leaf["leaf_num"]
    if kind in ("front_matter", "back_matter"):
        return f"leaf_{leaf_num:04d}.jpg"
    if kind == "plate":
        after_page = leaf["after_page_num"]
        # Collect all plates with the same after_page_num, in leaf order.
        siblings = sorted(
            [l for l in all_leaves if l.get("kind") == "plate"
             and l.get("after_page_num") == after_page],
            key=lambda l: l["leaf_num"],
        )
        seq = next(i + 1 for i, s in enumerate(siblings) if s["leaf_num"] == leaf_num)
        return f"plate_{after_page:04d}_{seq:02d}.jpg"
    raise ValueError(f"leaf {leaf_num}: unexpected kind {kind!r} for filename derivation")


def _ia_filename_for_leaf_v4(manifest: dict, leaf_num: int) -> str | None:
    """Derive the IA jp2 ia_filename for leaf_num from the v4 manifest's body leaves.

    Substitutes the trailing ``_NNNN.jp2`` index in the first primary (non-provenance)
    body leaf's ia_filename. Returns None if no suitable body leaf is found.
    """
    for leaf in manifest.get("leaves", []):
        if leaf.get("kind") != "body":
            continue
        if leaf.get("provenance") is not None:
            continue   # alternate-source leaf -- its filename belongs to a different item
        ia_filename = leaf.get("ia_filename")
        if isinstance(ia_filename, str) and _JP2_LEAF_RE.search(ia_filename):
            return _JP2_LEAF_RE.sub(f"_{leaf_num:04d}.jp2", ia_filename)
    return None


def _update_leaf_record(manifest: dict, leaf_num: int, updates: dict) -> None:
    """Update a specific leaf record in the v4 manifest in-place.

    Only permitted on non-body, non-unresolved leaves (P3 only moves
    front/back/plate pending leaves to present or not_imaged).

    When ``image_state == "not_imaged"``, strips ``local_path`` and all
    provenance fields from the updates before applying (schema guard:
    local_path presence triggers required provenance fields).
    """
    leaves = manifest.get("leaves", [])
    idx = next((i for i, l in enumerate(leaves) if l["leaf_num"] == leaf_num), None)
    if idx is None:
        raise KeyError(f"leaf_num {leaf_num} not found in manifest")
    leaf = leaves[idx]
    if leaf.get("kind") == "body":
        raise ValueError(
            f"leaf {leaf_num}: refusing to update a body leaf (kind=body); "
            "P3 only touches pending front/back/plate leaves"
        )
    if leaf.get("image_state") == "unresolved":
        raise ValueError(
            f"leaf {leaf_num}: refusing to update an unresolved leaf; "
            "unresolved leaves are Part-B body holes, not P3 work"
        )
    applied = dict(updates)
    if applied.get("image_state") == "not_imaged":
        # A blank/not-imaged leaf must carry no local_path or provenance fields.
        for field in _PROVENANCE_FIELDS:
            applied.pop(field, None)
        leaf.pop("local_path", None)  # remove any pre-existing path
    leaf.update(applied)


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def _rel_to_repo(path: Path) -> str:
    """Repo-root-relative POSIX path (OUT-03)."""
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _img_facts(jpg: Path) -> tuple[str, str, list[int]]:
    """(sha256-hex, PIL mode, [w, h]) — pixels are primary (PIPE-29)."""
    data = jpg.read_bytes()
    sha = "sha256:" + hashlib.sha256(data).hexdigest()
    with Image.open(jpg) as im:
        return sha, im.mode, [im.width, im.height]


def _atomic_write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Per-leaf fetch
# ---------------------------------------------------------------------------

def fetch_one_leaf(
    *,
    leaf: dict,
    all_leaves: list[dict],
    manifest: dict,
    zip_name: str,
    out_dir: Path,
    item_id: str = IA_ITEM_ID,
) -> dict:
    """Download, blank-detect, and return the provenance dict for one leaf.

    Returns a dict suitable for passing to ``_update_leaf_record`` as ``updates``:
    - ``image_state: present`` + provenance fields for a non-blank leaf
    - ``image_state: not_imaged`` + ``blank: True`` for a blank leaf (no local_path)

    Raises RuntimeError on Retry-After cap exceeded (caller logs and continues).
    """
    leaf_num = leaf["leaf_num"]
    ia_filename = _ia_filename_for_leaf_v4(manifest, leaf_num)
    if not ia_filename:
        raise RuntimeError(
            f"leaf {leaf_num}: cannot derive ia_filename (no primary body leaf with pattern)"
        )
    prefix = zip_name.replace("_jp2.zip", "")
    internal_path = f"{prefix}_jp2/{prefix}_{leaf_num:04d}.jp2"
    zip_url = (
        f"https://archive.org/download/{item_id}/{zip_name}"
    )
    headers = {"User-Agent": _USER_AGENT}
    jp2_bytes = _download_jp2(zip_url, internal_path, headers)

    img = Image.open(io.BytesIO(jp2_bytes))
    image_mode_orig = img.mode

    filename = _derive_output_filename(leaf, all_leaves)
    jpeg_path = out_dir / filename

    if _is_blank(img):
        return {"image_state": "not_imaged", "blank": True}

    out_dir.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
    jpeg_bytes = buf.getvalue()
    jpeg_path.write_bytes(jpeg_bytes)
    # Verify against pixels (PIPE-29): reopen and confirm non-blank.
    with Image.open(jpeg_path) as saved:
        if _is_blank(saved):
            jpeg_path.unlink(missing_ok=True)
            return {"image_state": "not_imaged", "blank": True}

    sha256, saved_mode, saved_size = _img_facts(jpeg_path)
    return {
        "image_state": "present",
        "local_path": _rel_to_repo(jpeg_path),
        "ia_leaf_id": f"{leaf_num:04d}",
        "ia_filename": f"{zip_name}/{internal_path}",
        "ia_item_id": item_id,
        "sha256": sha256,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "image_mode": image_mode_orig,
        "image_size": saved_size,
    }


# ---------------------------------------------------------------------------
# Per-volume processing
# ---------------------------------------------------------------------------

def process_volume(
    volume: int,
    *,
    base_dir: Path = BASE_DIR,
    dry_run: bool = False,
) -> dict:
    """Fetch all pending front/back/plate leaves for one volume.

    Returns a summary dict:
        fetched_present, confirmed_blank, unresolved (with reason), errors
    """
    manifest_path = base_dir / f"vol_{volume:02d}.manifest.json"
    vol_dir = base_dir / f"vol_{volume:02d}"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "leaves" not in manifest:
        raise ValueError(f"vol_{volume:02d}: not a v4 manifest (no leaves[])")

    all_leaves = manifest["leaves"]
    worklist = [
        l for l in all_leaves
        if l.get("image_state") == "pending" and l.get("kind") in _P3_KINDS
    ]

    files_url = (
        f"https://archive.org/download/{IA_ITEM_ID}/{IA_ITEM_ID}_files.xml"
    )
    import xml.etree.ElementTree as ET
    files_root = ET.fromstring(
        fetch_url_bytes(files_url, headers={"User-Agent": _USER_AGENT})
    )
    zip_name = find_jp2_zip(files_root, volume)

    summary: dict = {
        "volume": volume,
        "pending": len(worklist),
        "fetched_present": 0,
        "confirmed_blank": 0,
        "unresolved": [],
        "errors": [],
    }

    for i, leaf in enumerate(worklist):
        leaf_num = leaf["leaf_num"]
        if dry_run:
            logger.info("[vol_%02d] leaf %04d (%s) -- dry-run", volume, leaf_num, leaf["kind"])
            continue
        try:
            updates = fetch_one_leaf(
                leaf=leaf,
                all_leaves=all_leaves,
                manifest=manifest,
                zip_name=zip_name,
                out_dir=vol_dir,
            )
            _update_leaf_record(manifest, leaf_num, updates)
            if updates["image_state"] == "present":
                summary["fetched_present"] += 1
                logger.info(
                    "[vol_%02d] leaf %04d (%s) -> present",
                    volume, leaf_num, leaf["kind"],
                )
            else:
                summary["confirmed_blank"] += 1
                logger.info(
                    "[vol_%02d] leaf %04d (%s) -> not_imaged (blank)",
                    volume, leaf_num, leaf["kind"],
                )
        except RuntimeError as exc:
            reason = str(exc)
            summary["unresolved"].append({"leaf_num": leaf_num, "reason": reason})
            logger.error("[vol_%02d] leaf %04d -- %s", volume, leaf_num, reason)
        except Exception as exc:  # noqa: BLE001 -- log-and-continue per REL-08
            reason = f"unexpected: {exc}"
            summary["unresolved"].append({"leaf_num": leaf_num, "reason": reason})
            logger.error("[vol_%02d] leaf %04d -- %s", volume, leaf_num, reason)

        # Crawl-delay between fetches (IA rate-limit courtesy).
        if i < len(worklist) - 1:
            time.sleep(CRAWL_DELAY)

    if not dry_run:
        _atomic_write_json(manifest_path, manifest)

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--volume", type=int, action="append", dest="volumes",
                   help="volume number (repeatable); or use --all-volumes")
    p.add_argument("--all-volumes", action="store_true",
                   help=f"process all P3 volumes ({_P3_VOLUMES})")
    p.add_argument("--dry-run", action="store_true",
                   help="enumerate worklist without fetching or writing")
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.DEBUG if "--verbose" in (argv or sys.argv)
                        else logging.INFO, format="%(levelname)s %(message)s")
    args = _build_arg_parser().parse_args(argv)
    if not args.volumes and not args.all_volumes:
        _build_arg_parser().error("specify --volume N or --all-volumes")
    volumes = _P3_VOLUMES if args.all_volumes else args.volumes

    results = []
    for vol in volumes:
        try:
            result = process_volume(vol, dry_run=args.dry_run)
            results.append(result)
            logger.info(
                "vol_%02d done: %d present, %d blank, %d unresolved",
                vol, result["fetched_present"], result["confirmed_blank"],
                len(result["unresolved"]),
            )
        except (FileNotFoundError, ValueError) as exc:
            logger.error("vol_%02d: %s", vol, exc)
            results.append({"volume": vol, "error": str(exc)})

    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
