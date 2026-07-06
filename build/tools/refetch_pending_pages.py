"""build/tools/refetch_pending_pages.py
Re-fetch body pages whose manifest entry has a known ia_filename but whose
JPEG has not yet been downloaded (scan_status='download_pending').

These are the pages that failed during the original bulk download due to
Internet Archive rate-limiting or transient network errors and were never
retried.

After all fetches for a volume complete, the volume's page_order.json is
regenerated so scan_status values reflect the updated disk state.

CLI:
    py -3 build/tools/refetch_pending_pages.py            # all vols 02-12
    py -3 build/tools/refetch_pending_pages.py --vol 7    # single volume
    py -3 build/tools/refetch_pending_pages.py --dry-run  # show plan only
    py -3 build/tools/refetch_pending_pages.py --workers 4
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_PAGES = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
LOG_FILE = REPO_ROOT / "logs" / "refetch_pending_pages.log"

# Add build/tools to sys.path so we can import sibling scripts.
sys.path.insert(0, str(Path(__file__).parent))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.nsh_leaf_model import body_pages  # noqa: E402
from fetch_ia_pages import (  # noqa: E402
    CRAWL_DELAY,
    IA_ITEM_ID,
    fetch_page,
    load_manifest,
)
from generate_page_order import generate_volume  # noqa: E402

DRY_RUN = False  # set from --dry-run arg; used in if DRY_RUN: guards (API-01)

logger = logging.getLogger("refetch_pending_pages")


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


def _pending_pages(manifest: dict) -> list[dict]:
    """Return page entries that have ia_filename but have not yet been downloaded.

    Read-only over the body leaves (the caller fetches via fetch_page, which
    writes through manifest_lock -- it never mutates these returned records), so
    the accessor's copies are safe here."""
    page_count = manifest.get("page_count") or 0
    result = []
    for entry in body_pages(manifest):
        page_num = entry.get("page_num")
        if not isinstance(page_num, int):
            continue
        if page_num > page_count:
            continue
        if entry.get("ia_filename") and not entry.get("local_path"):
            result.append(entry)
    return sorted(result, key=lambda e: e["page_num"])


def refetch_volume(
    vol_num: int,
    *,
    dry_run: bool,
    workers: int,
) -> tuple[int, int, int]:
    """Fetch all pending pages for one volume. Returns (fetched, skipped, errors)."""
    vol_id = f"vol_{vol_num:02d}"
    manifest_path = RAW_PAGES / f"{vol_id}.manifest.json"
    out_dir = RAW_PAGES / vol_id

    if not manifest_path.exists():
        logger.warning("[%s] manifest not found -- skip", vol_id)
        return 0, 0, 0

    manifest = load_manifest(manifest_path)
    pending = _pending_pages(manifest)

    if not pending:
        logger.info("[%s] no pending pages", vol_id)
        return 0, 0, 0

    logger.info("[%s] %d pending pages to fetch", vol_id, len(pending))

    if dry_run:
        for entry in pending:
            logger.info(
                "[%s] DRY RUN page %04d: %s",
                vol_id, entry["page_num"], entry.get("ia_filename", "?"),
            )
        return 0, len(pending), 0

    manifest_lock = threading.Lock()

    def fetch_worker(worker_entries: list[dict]) -> tuple[int, int, int]:
        fetched = skipped = errors = 0
        for i, entry in enumerate(worker_entries):
            page_num = entry["page_num"]
            ia_filename = entry.get("ia_filename", "")
            leaf_id = entry.get("ia_leaf_id", "")
            zip_name = ia_filename.split("/")[0] if "/" in ia_filename else ""

            try:
                leaf_num = int(leaf_id)
            except (ValueError, TypeError):
                logger.error(
                    "[%s] page %04d -- bad ia_leaf_id %r; skip",
                    vol_id, page_num, leaf_id,
                )
                errors += 1
                continue

            if not zip_name.endswith("_jp2.zip"):
                logger.error(
                    "[%s] page %04d -- bad ia_filename %r; skip",
                    vol_id, page_num, ia_filename,
                )
                errors += 1
                continue

            result = None
            try:
                result = fetch_page(
                    volume=vol_num,
                    page_num=page_num,
                    leaf_num=leaf_num,
                    zip_name=zip_name,
                    out_dir=out_dir,
                    manifest_path=manifest_path,
                    dry_run=False,
                    force=False,
                    item_id=IA_ITEM_ID,
                    manifest_lock=manifest_lock,
                )
                if result is None:
                    skipped += 1
                else:
                    fetched += 1
            except RuntimeError as exc:
                logger.error("[%s] page %04d -- %s", vol_id, page_num, exc)
                errors += 1
            except Exception as exc:  # noqa: BLE001 -- per-page errors must not abort the run
                logger.error(
                    "[%s] page %04d -- unexpected: %s", vol_id, page_num, exc
                )
                errors += 1

            # Crawl delay between this worker's own fetches (not between workers).
            if result is not None and i < len(worker_entries) - 1:
                time.sleep(CRAWL_DELAY)

        return fetched, skipped, errors

    # Distribute pages round-robin across workers so each worker fetches a
    # spread of page numbers rather than a contiguous block.
    slices = [pending[i::workers] for i in range(workers)]
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

    # Regenerate page_order.json so scan_status reflects what is now on disk.
    logger.info("[%s] regenerating page_order.json", vol_id)
    generate_volume(vol_num)

    return total_fetched, total_skipped, total_errors


def main() -> int:
    global DRY_RUN
    parser = argparse.ArgumentParser(
        description="Re-fetch download_pending NSH pages from Internet Archive."
    )
    parser.add_argument(
        "--vol",
        type=int,
        metavar="N",
        help="Single volume number (2-12); default: all",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the fetch plan without downloading anything",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Parallel download workers per volume (default: 2)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be at least 1")

    DRY_RUN = args.dry_run
    _setup_logging(args.verbose)

    volumes = [args.vol] if args.vol else list(range(2, 13))

    if DRY_RUN:
        logger.info("=== refetch_pending_pages DRY RUN ===")
        logger.info("Volumes: %s", volumes)
        for vol_num in volumes:
            refetch_volume(vol_num, dry_run=True, workers=args.workers)
        return 0

    logger.info("=== refetch_pending_pages -- volumes: %s ===", volumes)
    grand_fetched = grand_skipped = grand_errors = 0
    t0 = time.monotonic()

    for vol_num in volumes:
        f, s, e = refetch_volume(vol_num, dry_run=False, workers=args.workers)
        grand_fetched += f
        grand_skipped += s
        grand_errors += e

    elapsed = time.monotonic() - t0
    logger.info(
        "=== Done in %.0fs: fetched=%d skipped=%d errors=%d ===",
        elapsed, grand_fetched, grand_skipped, grand_errors,
    )
    return 0 if grand_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
