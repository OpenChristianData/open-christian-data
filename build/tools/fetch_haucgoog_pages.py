"""build/tools/fetch_haucgoog_pages.py
Fetch the 44 unresolved body pages from haucgoog alternate IA items.

Body pages absent from the primary NSH scan (NewSchaffHerzogEncyclopediaOfReligious)
but whose text was confirmed by ABBYY OCR of Harvard/Google Books copies on IA.
For each volume in {2, 5, 6, 8, 10}, reads page_order.json for entries with
scan_status='unresolved', probes each haucgoog item's scandata to find the
page->leaf mapping, and downloads from the first item that covers the page.

After all fetches for a volume complete the volume's page_order.json is
regenerated so scan_status values reflect the updated disk state.

CLI:
    py -3 build/tools/fetch_haucgoog_pages.py            # all haucgoog target vols
    py -3 build/tools/fetch_haucgoog_pages.py --vol 10   # single volume
    py -3 build/tools/fetch_haucgoog_pages.py --dry-run  # show plan, no downloads
    py -3 build/tools/fetch_haucgoog_pages.py --workers 2
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_PAGES = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
LOG_FILE = REPO_ROOT / "logs" / "fetch_haucgoog_pages.log"

# Add build/tools dir and repo root so sibling imports and package imports work.
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(REPO_ROOT))

from fetch_ia_pages import (  # noqa: E402
    CRAWL_DELAY,
    _resolve_volume,
    fetch_alternate_page,
    load_manifest,
)
from generate_page_order import generate_volume  # noqa: E402
from build.lib.nsh_leaf_model import body_pages  # noqa: E402
from build.parsers.ia_abbyy import HAUCGOOG_VOLUMES, JACKGOOG_VOLUMES  # noqa: E402

DRY_RUN = False  # API-01: set from --dry-run arg; must appear in if DRY_RUN: blocks

# Items confirmed to carry JP2 images for specific volumes but NOT registered in
# HAUCGOOG_VOLUMES (and therefore invisible to the ia_abbyy ABBYY OCR pipeline).
# These are supplemental scans discovered during gap resolution — typically different
# library copies.  Checked in _find_item_for_page AFTER haucgoog and jackgoog fallbacks.
_SUPPLEMENTAL_JP2_VOLUMES: dict[int, list[str]] = {
    # Three library scans covering vol 10 pp. 2-505; not added to HAUCGOOG_VOLUMES to
    # avoid polluting the _SOURCE_VOLUMES / ABBYY source dict in ia_abbyy.py (line 192).
    10: [
        # samu: pages 2-504; accessible (returns occasional 500s but not auth-blocked)
        "newschaffherzoge0010samu",
        # unse: pages 2-505; returns 403 Forbidden (access-restricted item)
        "newschaffherzoge0010unse",
        # samu_i3n8: pages 2-505; returns 401 Unauthorized (access-restricted item)
        "newschaffherzoge0010samu_i3n8",
    ],
}

logger = logging.getLogger("fetch_haucgoog_pages")

# Volumes that have unresolved pages with confirmed haucgoog alternates.
_HAUCGOOG_TARGET_VOLS = {2, 5, 6, 8, 10}

# Thread-safe cache of (zip_name, page_to_leaf) per item_id.
_resolve_cache: dict[str, tuple[str, dict[int, int]]] = {}
_resolve_cache_lock = threading.Lock()


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(
        level=level,
        format=fmt,
        handlers=[
            logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def _get_item_map(item_id: str, vol_num: int) -> tuple[str, dict[int, int]]:
    """Return (zip_name, page_to_leaf) for a haucgoog IA item, cached per item_id.

    Calls _resolve_volume which fetches _files.xml and _scandata.xml from IA.
    Returns ("", {}) on network or parse failure.
    """
    with _resolve_cache_lock:
        if item_id in _resolve_cache:
            return _resolve_cache[item_id]

    # Resolve outside the lock to avoid blocking other threads during HTTP fetch.
    try:
        zip_name, page_to_leaf, _, _ = _resolve_volume(item_id, vol_num)
        result: tuple[str, dict[int, int]] = (zip_name, page_to_leaf)
        logger.debug("  item %s: resolved %d pages", item_id, len(page_to_leaf))
    except Exception as exc:
        logger.warning("  item %s: resolve failed -- %s", item_id, exc)
        result = ("", {})

    with _resolve_cache_lock:
        _resolve_cache[item_id] = result
    return result


def _find_item_for_page(
    vol_num: int, page_num: int
) -> tuple[str, str, int] | None:
    """Return (item_id, zip_name, leaf_num) from the first item covering page_num.

    Checks haucgoog items first, then jackgoog as a fallback.
    Returns None if no item has the page as a JP2.
    """
    for item_id in HAUCGOOG_VOLUMES.get(vol_num, []):
        zip_name, page_to_leaf = _get_item_map(item_id, vol_num)
        if page_num in page_to_leaf:
            return item_id, zip_name, page_to_leaf[page_num]
    # Jackgoog fallback (covers pages absent from all haucgoog JP2 copies).
    for item_id in JACKGOOG_VOLUMES.get(vol_num, []):
        zip_name, page_to_leaf = _get_item_map(item_id, vol_num)
        if page_num in page_to_leaf:
            return item_id, zip_name, page_to_leaf[page_num]
    # Supplemental JP2 sources — alternate library scans not in the ABBYY pipeline.
    for item_id in _SUPPLEMENTAL_JP2_VOLUMES.get(vol_num, []):
        zip_name, page_to_leaf = _get_item_map(item_id, vol_num)
        if page_num in page_to_leaf:
            return item_id, zip_name, page_to_leaf[page_num]
    return None


def _unresolved_pages(vol_num: int) -> list[int]:
    """Return sorted page numbers with scan_status='unresolved' from page_order.json."""
    po_path = RAW_PAGES / f"vol_{vol_num:02d}" / "page_order.json"
    if not po_path.exists():
        logger.warning("[vol_%02d] page_order.json not found -- skip", vol_num)
        return []
    data = json.loads(po_path.read_text(encoding="utf-8"))
    return sorted(
        int(p["book_page"])
        for p in data.get("pages", [])
        if p.get("scan_status") == "unresolved"
        and str(p.get("book_page", "")).isdigit()
    )


def fetch_haucgoog_volume(
    vol_num: int,
    *,
    dry_run: bool,
    workers: int,
) -> tuple[int, int, int]:
    """Fetch all unresolved pages for one volume. Returns (fetched, skipped, errors)."""
    vol_id = f"vol_{vol_num:02d}"
    manifest_path = RAW_PAGES / f"{vol_id}.manifest.json"
    out_dir = RAW_PAGES / vol_id

    unresolved = _unresolved_pages(vol_num)
    if not unresolved:
        logger.info("[%s] no unresolved pages -- skip", vol_id)
        return 0, 0, 0

    logger.info("[%s] %d unresolved pages to fetch", vol_id, len(unresolved))

    # Pre-resolve all haucgoog + jackgoog + supplemental items before spawning workers.
    # This ensures _find_item_for_page is cache-warm and avoids duplicate HTTP fetches.
    items = (
        HAUCGOOG_VOLUMES.get(vol_num, [])
        + JACKGOOG_VOLUMES.get(vol_num, [])
        + _SUPPLEMENTAL_JP2_VOLUMES.get(vol_num, [])
    )
    logger.info("[%s] probing %d alternate item(s)", vol_id, len(items))
    for item_id in items:
        _get_item_map(item_id, vol_num)

    if dry_run:
        if DRY_RUN:
            for page_num in unresolved:
                found = _find_item_for_page(vol_num, page_num)
                if found:
                    item_id_found, _, leaf_num = found
                    logger.info(
                        "[%s] DRY RUN page %04d: leaf %04d from %s",
                        vol_id, page_num, leaf_num, item_id_found,
                    )
                else:
                    logger.warning(
                        "[%s] DRY RUN page %04d: NOT FOUND in any haucgoog item",
                        vol_id, page_num,
                    )
        return 0, len(unresolved), 0

    manifest = load_manifest(manifest_path)
    # Use image_size from an existing body entry for dimension_variance tracking.
    primary_size: list[int] | None = None
    for entry in body_pages(manifest):
        if "image_size" in entry:
            primary_size = entry["image_size"]
            break

    manifest_lock = threading.Lock()

    def fetch_worker(worker_pages: list[int]) -> tuple[int, int, int]:
        fetched = skipped = errors = 0
        for i, page_num in enumerate(worker_pages):
            found = _find_item_for_page(vol_num, page_num)
            if found is None:
                logger.error(
                    "[%s] page %04d -- NOT FOUND in any haucgoog item", vol_id, page_num
                )
                errors += 1
                continue

            item_id_found, zip_name, leaf_num = found
            result = None
            try:
                result = fetch_alternate_page(
                    volume=vol_num,
                    page_num=page_num,
                    leaf_num=leaf_num,
                    crop=None,
                    zip_name=zip_name,
                    out_dir=out_dir,
                    manifest_path=manifest_path,
                    dry_run=False,
                    force=False,
                    item_id=item_id_found,
                    validation_status="visual_header_only",
                    primary_image_size=primary_size,
                    manifest_lock=manifest_lock,
                )
                if result is None:
                    skipped += 1
                else:
                    fetched += 1
            except RuntimeError as exc:
                logger.error("[%s] page %04d -- %s", vol_id, page_num, exc)
                errors += 1
            except Exception as exc:  # noqa: BLE001 -- per-page errors must not abort run
                logger.error("[%s] page %04d -- unexpected: %s", vol_id, page_num, exc)
                errors += 1

            # Crawl delay between this worker's own fetches (not between workers).
            if result is not None and i < len(worker_pages) - 1:
                time.sleep(CRAWL_DELAY)

        return fetched, skipped, errors

    # Distribute pages round-robin across workers so each fetches a spread of pages.
    slices = [unresolved[i::workers] for i in range(workers)]
    total_fetched = total_skipped = total_errors = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for worker_fetched, worker_skipped, worker_errors in executor.map(
            fetch_worker, slices
        ):
            total_fetched += worker_fetched
            total_skipped += worker_skipped
            total_errors += worker_errors

    logger.info(
        "[%s] fetch complete: fetched=%d skipped=%d errors=%d",
        vol_id, total_fetched, total_skipped, total_errors,
    )
    logger.info("[%s] regenerating page_order.json", vol_id)
    generate_volume(vol_num)
    return total_fetched, total_skipped, total_errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch unresolved NSH body pages from haucgoog alternate IA items."
    )
    parser.add_argument(
        "--vol",
        type=int,
        choices=sorted(_HAUCGOOG_TARGET_VOLS),
        help="Fetch a single volume (default: all haucgoog target vols)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Parallel download workers per volume (default: 2)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    global DRY_RUN
    DRY_RUN = args.dry_run  # API-01

    _setup_logging(args.verbose)

    if DRY_RUN:
        logger.info("=== fetch_haucgoog_pages -- DRY RUN ===")
    else:
        logger.info(
            "=== fetch_haucgoog_pages -- volumes: %s ===",
            sorted([args.vol] if args.vol else _HAUCGOOG_TARGET_VOLS),
        )

    vols = [args.vol] if args.vol else sorted(_HAUCGOOG_TARGET_VOLS)
    grand_fetched = grand_skipped = grand_errors = 0
    for vol_num in vols:
        f, s, e = fetch_haucgoog_volume(
            vol_num, dry_run=args.dry_run, workers=args.workers
        )
        grand_fetched += f
        grand_skipped += s
        grand_errors += e

    logger.info(
        "=== done: fetched=%d skipped=%d errors=%d ===",
        grand_fetched, grand_skipped, grand_errors,
    )
    return 1 if grand_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
