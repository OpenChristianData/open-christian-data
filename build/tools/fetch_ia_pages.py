"""
Fetch individual pages from Internet Archive JP2 ZIPs as JPEG cache files.

Produces per-volume manifests and a gitignored JPEG cache per Decision 7/8.

CLI usage:
  py -3 build/tools/fetch_ia_pages.py --volume 3 --pages 75,100,164,300,331
  py -3 build/tools/fetch_ia_pages.py --volume 3 --pages 42-49
  py -3 build/tools/fetch_ia_pages.py --volume 1 --pages all
  py -3 build/tools/fetch_ia_pages.py --volume 3 --pages 100 --dry-run
  py -3 build/tools/fetch_ia_pages.py --volume 1 --pages 10 --include-unnumbered
  py -3 build/tools/fetch_ia_pages.py --volume 1 --from-alternate-item ITEM --leaf-page-spec 64:96:left
"""

import argparse
from dataclasses import dataclass
import hashlib
import io
import json
import logging
import os
import sys
import threading
import time
import urllib.error
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
IA_ITEM_ID = "NewSchaffHerzogEncyclopediaOfReligious"
_IA_BASE_URL = "https://archive.org/download/{item_id}"
CRAWL_DELAY = 10        # seconds between page fetches
JPEG_QUALITY = 95
TWO_UP_GUTTER_MARGIN = 30
USER_AGENT = "OCD-fetcher/1.0 (research; non-commercial)"

REPO_ROOT = Path(__file__).parents[2]
DEFAULT_OUT_BASE = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
LOG_FILE = REPO_ROOT / "logs" / "fetch_ia_pages.log"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.ia_fetch import (  # noqa: E402
    MAX_RETRY_AFTER,
    MAX_RETRIES,
    _download_jp2,
    _open_remote_zip,
    fetch_url_bytes,
    find_jp2_zip,
)

logger = logging.getLogger("fetch_ia_pages")


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# XML parsing helpers
# ---------------------------------------------------------------------------
# find_jp2_zip lives in build.lib.ia_fetch and is imported above.

def load_scandata_pages(scandata_root: ET.Element) -> dict:
    """Parse scandata XML root into structured printed-page -> leaf information.

    The scandata ``pageNumber`` is the TRUE printed page number (verified against
    OCR running headers on the clean control volumes). Two pathologies must be
    surfaced rather than silently collapsed (see
    ``docs/NSH_FETCHER_MECHANISM_DIAGNOSIS.md``):

    * **Scan gaps** -- printed pages inside [min, max] with no leaf at all. These
      are genuinely missing from the scan and must become recorded holes, never
      squeezed out (squeezing slides every later file's content ahead of its
      name = the positive-offset corruption).
    * **Duplicate pageNumbers** -- the same printed page tagged on two leaves
      (e.g. vol_11 p478 on leaves 505/506; vol_06 pp462-468 on two runs). The
      old ``mapping[pnum] = leaf`` silently kept the last leaf and dropped the
      first with no record. The correct leaf is volume-specific, so we keep a
      deterministic default in ``page_to_leaf`` but expose ALL leaves per page in
      ``duplicates`` for OCR/visual adjudication.

    Returns a dict with keys:
      ``page_to_leaf``  {printed_page: leaf}     -- one leaf per page (last-wins
                                                    default, behaviour-stable)
      ``duplicates``    {printed_page: [leaf,..]} -- pages tagged on >1 leaf
      ``numbered_range`` (min_page, max_page) | None
      ``missing_pages`` [int]                     -- in-range printed pages w/ no leaf
    """
    ns = "http://www.archive.org/scandata"
    pages = (
        scandata_root.findall(f".//{{{ns}}}page")
        or scandata_root.findall(".//page")
    )
    mapping: dict[int, int] = {}
    all_leaves: dict[int, list[int]] = {}
    for page in pages:
        leaf_str = page.get("leafNum", "")
        pnum_el = page.find(f"{{{ns}}}pageNumber") or page.find("pageNumber")
        pnum = (pnum_el.text or "").strip() if pnum_el is not None else ""
        if pnum.isdigit() and leaf_str.isdigit():
            p, leaf = int(pnum), int(leaf_str)
            mapping[p] = leaf  # last-wins default, unchanged for back-compat
            all_leaves.setdefault(p, []).append(leaf)
    duplicates = {p: leaves for p, leaves in all_leaves.items() if len(leaves) > 1}
    numbered = sorted(all_leaves)
    numbered_range = (numbered[0], numbered[-1]) if numbered else None
    missing_pages = (
        [p for p in range(numbered_range[0], numbered_range[1] + 1) if p not in all_leaves]
        if numbered_range
        else []
    )
    return {
        "page_to_leaf": mapping,
        "duplicates": duplicates,
        "numbered_range": numbered_range,
        "missing_pages": missing_pages,
    }


def load_page_to_leaf(scandata_root: ET.Element) -> dict:
    """Parse scandata XML root; return {page_number (int): leaf_number (int)}.

    Back-compat wrapper over :func:`load_scandata_pages` for callers that only
    need the page->leaf map. Duplicate-page detection lives in the structured
    function; use it when you must not silently drop a duplicate leaf.
    """
    return load_scandata_pages(scandata_root)["page_to_leaf"]


def load_unnumbered_leaves(scandata_root: ET.Element) -> list[dict]:
    """Return front- and back-matter leaves without printed page numbers."""
    ns = "http://www.archive.org/scandata"
    pages = (
        scandata_root.findall(f".//{{{ns}}}page")
        or scandata_root.findall(".//page")
    )
    numbered_positions = []
    for index, page in enumerate(pages):
        pnum_el = page.find(f"{{{ns}}}pageNumber") or page.find("pageNumber")
        pnum = (pnum_el.text or "").strip() if pnum_el is not None else ""
        if pnum.isdigit():
            numbered_positions.append(index)
    if not numbered_positions:
        return []

    first_numbered = min(numbered_positions)
    last_numbered = max(numbered_positions)
    leaves = []
    for index, page in enumerate(pages):
        leaf_str = page.get("leafNum", "")
        pnum_el = page.find(f"{{{ns}}}pageNumber") or page.find("pageNumber")
        pnum = (pnum_el.text or "").strip() if pnum_el is not None else ""
        if pnum.isdigit() or not leaf_str.isdigit():
            continue
        if index < first_numbered:
            section = "front_matter"
        elif index > last_numbered:
            section = "back_matter"
        else:
            continue
        page_type_el = page.find(f"{{{ns}}}pageType") or page.find("pageType")
        leaves.append(
            {
                "leaf_num": int(leaf_str),
                "page_type": (
                    (page_type_el.text or "").strip()
                    if page_type_el is not None
                    else "Normal"
                ),
                "section": section,
            }
        )
    return leaves


# ---------------------------------------------------------------------------
# Page argument parser
# ---------------------------------------------------------------------------
def parse_pages_arg(pages_str: str, total_pages: int) -> list:
    """Parse --pages value: 'all', '42-49' range, or '75,100,164' comma-list."""
    pages_str = pages_str.strip()
    if pages_str == "all":
        return list(range(1, total_pages + 1))

    pages: list[int] = []
    for token in pages_str.split(","):
        token = token.strip()
        if not token:
            raise ValueError(f"invalid page token in {pages_str!r}")
        if "-" in token:
            lo, _, hi = token.partition("-")
            try:
                start = int(lo.strip())
                end = int(hi.strip())
            except ValueError as exc:
                raise ValueError(f"invalid page range {token!r}") from exc
            pages.extend(range(start, end + 1))
        else:
            try:
                pages.append(int(token))
            except ValueError as exc:
                raise ValueError(f"invalid page number {token!r}") from exc
    return pages


def parse_leaf_page_spec(spec: str) -> list[tuple[int, int, str | None]]:
    """Parse LEAF:PAGE[:CROP] entries for alternate-source page recovery."""
    rows = []
    for item in spec.split(","):
        parts = [part.strip() for part in item.split(":")]
        if len(parts) not in (2, 3) or not parts[0].isdigit() or not parts[1].isdigit():
            raise ValueError(
                "--leaf-page-spec entries must be LEAF:PAGE[:left|right]"
            )
        crop = parts[2] if len(parts) == 3 else None
        if crop not in (None, "left", "right"):
            raise ValueError("--leaf-page-spec crop must be left or right")
        rows.append((int(parts[0]), int(parts[1]), crop))
    return rows


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------
def load_manifest(manifest_path: Path) -> dict:
    """Load manifest JSON or return an empty skeleton."""
    if Path(manifest_path).exists():
        with Path(manifest_path).open(encoding="utf-8") as fh:
            return json.load(fh)
    return {
        "ia_item_id": IA_ITEM_ID,
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "page_count": None,
        "pages": [],
    }


def _parse_manifest_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def validate_manifest(manifest: dict) -> tuple[list[str], list[str]]:
    """Return errors and warnings for numbered-page mappings.

    Leaf numbers are namespaced per source item: an alternate-sourced page
    carries the alternate item's leaf id (recorded in ``ia_item_id``), which can
    legitimately collide with a primary leaf number or break the primary leaf
    sequence. The duplicate-leaf and leaf-gap checks therefore group by source
    item so a cross-item collision is not mistaken for the within-scan phantom
    bug those checks exist to catch. Duplicate ``page_num`` is always a real bug
    regardless of source, so it stays global.
    """
    errors: list[str] = []
    warnings: list[str] = []
    pages = manifest.get("pages", [])
    PRIMARY = "<primary>"
    leaf_pages: dict[tuple[str, int | str], list[int | str]] = {}
    numbered_by_item: dict[str, list[tuple[int, int, str]]] = {}
    page_leaves: dict[int, list[str]] = {}

    for entry in pages:
        # Primary pages have no ia_item_id; alternate pages set it to their item.
        item = str(entry.get("ia_item_id") or PRIMARY)
        page_num = _parse_manifest_int(entry.get("page_num"))
        raw_leaf = str(entry.get("ia_leaf_id", ""))
        leaf_num = _parse_manifest_int(entry.get("ia_leaf_id"))
        leaf_key: int | str = leaf_num if leaf_num is not None else raw_leaf
        leaf_pages.setdefault((item, leaf_key), []).append(
            page_num if page_num is not None else entry.get("page_num", "")
        )
        if page_num is not None:
            page_leaves.setdefault(page_num, []).append(raw_leaf)
        if page_num is not None and leaf_num is not None:
            numbered_by_item.setdefault(item, []).append((page_num, leaf_num, raw_leaf))

    for (item, leaf_key), mapped_pages in leaf_pages.items():
        if len(mapped_pages) > 1:
            leaf_label = f"{leaf_key:04d}" if isinstance(leaf_key, int) else str(leaf_key)
            warnings.append(
                f"duplicate ia_leaf_id {leaf_label}: mapped to page_num values {mapped_pages}"
            )

    for page_num, mapped_leaves in page_leaves.items():
        if len(mapped_leaves) > 1:
            errors.append(
                f"duplicate page_num {page_num}: mapped to ia_leaf_id values {mapped_leaves}"
            )

    # Leaf contiguity is only meaningful within the primary scan's own sequence.
    numbered_leaves = numbered_by_item.get(PRIMARY, [])
    if numbered_leaves:
        first_page, first_leaf, _ = min(numbered_leaves)
        if first_page > 2:
            warnings.append(
                f"lowest page_num is {first_page} at ia_leaf_id {first_leaf:04d}; "
                "expected 1 or 2, so preceding numbered leaves may be missing"
            )
        ordered = sorted(numbered_leaves, key=lambda row: row[0])
        for (previous_page, previous_leaf, _), (page_num, leaf_num, _) in zip(
            ordered, ordered[1:]
        ):
            if leaf_num != previous_leaf + 1:
                warnings.append(
                    "leaf gap in page order: "
                    f"page_num {previous_page} has ia_leaf_id {previous_leaf:04d}, "
                    f"page_num {page_num} has ia_leaf_id {leaf_num:04d}"
                )

    return errors, warnings


_RETRY_WINERRORS = {
    5,   # ERROR_ACCESS_DENIED - Sync.com file-lock
    32,  # ERROR_SHARING_VIOLATION - file open by another process
    33,  # ERROR_LOCK_VIOLATION - lock range held by scanner/antivirus
}


def _replace_with_retry(src: str, dst: str, retries: int = 5, base_delay: float = 0.3) -> None:
    """os.replace with exponential backoff on transient Windows file locks."""
    for attempt in range(retries):
        try:
            os.replace(src, dst)
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) in _RETRY_WINERRORS and attempt < retries - 1:
                time.sleep(base_delay * (attempt + 1))
            else:
                raise


# Gap statuses that denote a body printed page which exists in the edition but is
# absent from the present file set (so it still counts toward the body total).
# "unresolved"/"resolved"/back-matter statuses are NOT body-missing and must not
# inflate page_count.
BODY_MISSING_GAP_STATUSES = {"permanently_missing", "absent_from_primary_scan"}


@dataclass
class _JpegResult:
    jpeg_bytes: bytes
    sha256: str
    image_mode: str
    image_size: list
    elapsed: float


def _fetch_and_encode_jpeg(
    zip_url: str,
    internal_path: str,
    headers: dict,
    jpeg_path: Path,
    crop: str | None = None,
) -> tuple["_JpegResult", dict | None]:
    """Download one JP2, optionally crop, encode to JPEG, and write it."""
    t0 = time.monotonic()
    jp2_bytes = _download_jp2(zip_url, internal_path, headers, MAX_RETRIES)
    img = Image.open(io.BytesIO(jp2_bytes))
    image_mode = img.mode

    crop_box = None
    if crop is not None:
        width, height = img.size
        midpoint = width // 2
        if crop == "left":
            box = (0, 0, midpoint - TWO_UP_GUTTER_MARGIN, height)
        else:
            box = (midpoint + TWO_UP_GUTTER_MARGIN, 0, width, height)
        if box[2] <= box[0]:
            raise ValueError("Image is too narrow for a two-up crop")
        img = img.crop(box)
        crop_box = {"l": box[0], "t": box[1], "r": box[2], "b": box[3]}

    image_size = list(img.size)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
    jpeg_bytes = buf.getvalue()
    jpeg_path.write_bytes(jpeg_bytes)

    sha256 = "sha256:" + hashlib.sha256(jpeg_bytes).hexdigest()
    elapsed = time.monotonic() - t0
    return _JpegResult(
        jpeg_bytes=jpeg_bytes,
        sha256=sha256,
        image_mode=image_mode,
        image_size=image_size,
        elapsed=elapsed,
    ), crop_box


def _compute_page_count(data: dict) -> int:
    """page_count = highest TRUE printed body page (present or permanently-missing).

    Model B (see docs/NSH_FETCHER_MECHANISM_DIAGNOSIS.md sec 3): page_num is the
    real printed page number, gaps are preserved as holes, and the body total is
    the highest body page that exists in the edition -- which equals
    present_body_pages + permanently_missing_body_pages. For every complete-tail
    volume this is simply max(present page_num); only a volume whose final body
    pages are missing (vol_13 pp209-211) needs the gap union to reach the true
    body max. Replaces the old len(pages), which under-counts gapped volumes.
    """
    pages = data.get("pages", [])
    nums = [
        p["page_num"]
        for p in pages
        if isinstance(p, dict) and isinstance(p.get("page_num"), int)
    ]
    gap_nums = [
        g["page_num"]
        for g in data.get("gaps", [])
        if isinstance(g, dict)
        and isinstance(g.get("page_num"), int)
        and g.get("status") in BODY_MISSING_GAP_STATUSES
    ]
    candidates = nums + gap_nums
    return max(candidates) if candidates else 0


def write_manifest_atomic(manifest_path: Path, data: dict) -> None:
    """Write manifest via temp file then os.replace (atomic per OUT-02).

    Legacy (pages[]) manifests only. Raises if passed a v4 (leaves[]) manifest
    so callers don't silently corrupt page_count or bypass validate_manifest on
    a format it wasn't written for. Use _write_manifest_preserving-style writers
    for v4 manifests.
    """
    if data.get("leaves") and not data.get("pages"):
        raise ValueError(
            "write_manifest_atomic does not support v4 (leaves[]) manifests — "
            "use a v4-aware writer (e.g. reclassify_out_of_range_gaps._write_manifest_preserving) instead"
        )
    data["page_count"] = _compute_page_count(data)
    errors, warnings = validate_manifest(data)
    if errors:
        raise ValueError(f"manifest validation errors: {'; '.join(errors)}")
    data["manifest_warnings"] = warnings
    for warning in warnings:
        logger.warning("Manifest validation: %s", warning)
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_name(
        f"{manifest_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        _replace_with_retry(str(tmp), str(manifest_path))
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _true_page_count(manifest_path: Path) -> int | None:
    """Volume's true printed-page count from ABBYY coverage, or None.

    ``pages_parsed`` in ``vol_NN/coverage.ia-abbyy.json`` is the count of numbered
    body pages the independent ABBYY scan parsed -- the authoritative book length.
    Returns None when no coverage exists; the caller then does not cap, so a
    possibly-real missing page is never silently dropped on an unverifiable count.
    """
    name = Path(manifest_path).name  # e.g. vol_03.manifest.json
    if not (name.startswith("vol_") and name.endswith(".manifest.json")):
        return None
    vol_token = name[: -len(".manifest.json")]  # vol_03
    coverage = Path(manifest_path).parent / vol_token / "coverage.ia-abbyy.json"
    if not coverage.exists():
        return None
    try:
        with coverage.open("r", encoding="utf-8") as handle:
            parsed = json.load(handle).get("pages_parsed")
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, int) else None


def record_unresolved_gaps(manifest_path: Path, requested_pages: list[int]) -> None:
    """Record requested numbered pages that remain absent after a fetch run.

    Guard (2026-06): a page number beyond the volume's true printed-page count
    (ABBYY ``pages_parsed``) is never recorded. An over-broad requested range that
    ran to the physical LEAF count instead of the printed PAGE count previously
    created phantom ``unresolved`` gaps for non-existent pages past the end of the
    book (vol_03 pp501-531, etc.). A page is skipped only when coverage PROVES it
    is out of range; with no coverage the page is recorded as before. Fetched pages
    are read from BOTH the v4 ``leaves`` body pages and the legacy ``pages`` list,
    so a page already captured in either shape is never re-recorded as a gap.
    """
    manifest = load_manifest(Path(manifest_path))
    fetched_pages = {entry.get("page_num") for entry in manifest.get("pages", [])}
    fetched_pages |= {
        leaf.get("page_num")
        for leaf in manifest.get("leaves", [])
        if isinstance(leaf, dict) and leaf.get("kind") == "body"
    }
    true_count = _true_page_count(Path(manifest_path))
    gaps_by_page = {
        entry["page_num"]: entry
        for entry in manifest.get("gaps", [])
    }
    changed = False
    for page_num in sorted(set(requested_pages)):
        if true_count is not None and page_num > true_count:
            logger.info(
                "skip out-of-range gap p%d (beyond true page count %d)",
                page_num,
                true_count,
            )
            continue
        if page_num not in fetched_pages and page_num not in gaps_by_page:
            gaps_by_page[page_num] = {
                "page_num": page_num,
                "status": "unresolved",
                "investigation_note": (
                    "no leaf mapping or fetched page image found for requested page"
                ),
            }
            changed = True
    if changed:
        manifest["gaps"] = [
            gaps_by_page[page_num] for page_num in sorted(gaps_by_page)
        ]
        write_manifest_atomic(Path(manifest_path), manifest)


# ---------------------------------------------------------------------------
# Download helpers (patched in tests)
# ---------------------------------------------------------------------------
# _open_remote_zip and _download_jp2 live in build.lib.ia_fetch and are
# imported above. They are re-exported here so existing callers that import
# from this module by name continue to work.

# ---------------------------------------------------------------------------
# Core fetch function
# ---------------------------------------------------------------------------
def fetch_page(
    *,
    volume: int,
    page_num: int,
    leaf_num: int,
    zip_name: str,
    out_dir: Path,
    manifest_path: Path,
    dry_run: bool,
    force: bool,
    item_id: str = IA_ITEM_ID,
    manifest_lock: Any | None = None,
    crop: str | None = None,
    alternate_source_leaf: int | None = None,
    validation_status: str | None = None,
    primary_image_size: list[int] | None = None,
    replacement_reason: str | None = None,
) -> dict | None:
    """Fetch one page: download JP2, convert to JPEG, update manifest.

    Returns the manifest entry dict, or None if the page was skipped. When
    parallel callers share a manifest lock, manifest updates are merged safely.
    """
    out_dir = Path(out_dir)
    manifest_path = Path(manifest_path)
    jpeg_path = out_dir / f"page_{page_num:04d}.jpg"

    if dry_run:
        logger.info("[vol_%02d] page %04d -- dry-run, skipping", volume, page_num)
        return None

    with manifest_lock if manifest_lock is not None else nullcontext():
        manifest = load_manifest(manifest_path)
        existing = next(
            (e for e in manifest.get("pages", []) if e.get("page_num") == page_num),
            None,
        )

    # Idempotency check: skip if cached JPEG sha256 matches manifest (REL-04)
    if not force and existing and jpeg_path.exists():
        cached_sha256 = "sha256:" + hashlib.sha256(jpeg_path.read_bytes()).hexdigest()
        if cached_sha256 == existing.get("sha256", ""):
            logger.info(
                "[vol_%02d] page %04d -- skipped (cached, sha256 match)",
                volume, page_num,
            )
            return None

    # Derive internal ZIP path: {prefix}_jp2/{prefix}_{leaf:04d}.jp2
    prefix = zip_name.replace("_jp2.zip", "")
    internal_path = f"{prefix}_jp2/{prefix}_{leaf_num:04d}.jp2"
    zip_url = f"{_IA_BASE_URL.format(item_id=item_id)}/{zip_name}"
    headers = {"User-Agent": USER_AGENT}

    out_dir.mkdir(parents=True, exist_ok=True)
    jpeg_result, crop_box = _fetch_and_encode_jpeg(
        zip_url,
        internal_path,
        headers,
        jpeg_path,
        crop,
    )
    fetched_at = datetime.now(timezone.utc).isoformat()

    entry = {
        "page_num": page_num,
        "ia_leaf_id": f"{leaf_num:04d}",
        "ia_filename": f"{zip_name}/{internal_path}",
        "local_path": (jpeg_path.relative_to(REPO_ROOT) if jpeg_path.is_relative_to(REPO_ROOT) else jpeg_path).as_posix(),
        "sha256": jpeg_result.sha256,
        "fetched_at": fetched_at,
        "image_mode": jpeg_result.image_mode,
        "image_size": jpeg_result.image_size,
    }
    if alternate_source_leaf is not None:
        entry["ia_item_id"] = item_id
        entry["provenance"] = {
            "source_item_id": item_id,
            "source_leaf": alternate_source_leaf,
            "derivation": "direct" if crop is None else f"crop_2up_{crop}",
            "crop_box": crop_box,
            "replacement_reason": (
                replacement_reason
                or "missing from primary scan; fetched from alternate Internet Archive item"
            ),
            "validation_status": validation_status or "visual_header_only",
            "dimension_variance": (
                primary_image_size is not None
                and jpeg_result.image_size != primary_image_size
            ),
        }

    with manifest_lock if manifest_lock is not None else nullcontext():
        if manifest_lock is not None:
            manifest = load_manifest(manifest_path)
        pages = [e for e in manifest.get("pages", []) if e.get("page_num") != page_num]
        pages.append(entry)
        pages.sort(key=lambda e: e["page_num"])
        manifest["pages"] = pages
        if manifest.get("volume") is None:
            manifest["volume"] = volume

        write_manifest_atomic(manifest_path, manifest)
    logger.info(
        "[vol_%02d] page %04d -- %.1fs -- fetched (mode=%s size=%dx%d)",
        volume,
        page_num,
        jpeg_result.elapsed,
        jpeg_result.image_mode,
        jpeg_result.image_size[0],
        jpeg_result.image_size[1],
    )
    return entry


def fetch_alternate_page(
    *,
    volume: int,
    page_num: int,
    leaf_num: int,
    crop: str | None,
    zip_name: str,
    out_dir: Path,
    manifest_path: Path,
    dry_run: bool,
    force: bool,
    item_id: str,
    validation_status: str,
    primary_image_size: list[int] | None,
    manifest_lock: Any | None = None,
) -> dict | None:
    """Fetch a numbered page from an alternate IA item with provenance."""
    return fetch_page(
        volume=volume,
        page_num=page_num,
        leaf_num=leaf_num,
        zip_name=zip_name,
        out_dir=out_dir,
        manifest_path=manifest_path,
        dry_run=dry_run,
        force=force,
        item_id=item_id,
        manifest_lock=manifest_lock,
        crop=crop,
        alternate_source_leaf=leaf_num,
        validation_status=validation_status,
        primary_image_size=primary_image_size,
    )


def fetch_unnumbered_leaf(
    *,
    volume: int,
    leaf_num: int,
    page_type: str,
    section: str,
    zip_name: str,
    out_dir: Path,
    manifest_path: Path,
    dry_run: bool,
    force: bool,
    item_id: str = IA_ITEM_ID,
    manifest_lock: Any | None = None,
) -> dict | None:
    """Fetch one unnumbered front- or back-matter leaf."""
    out_dir = Path(out_dir)
    manifest_path = Path(manifest_path)
    jpeg_path = out_dir / f"leaf_{leaf_num:04d}.jpg"
    if dry_run:
        logger.info("[vol_%02d] leaf %04d -- dry-run, skipping", volume, leaf_num)
        return None

    with manifest_lock if manifest_lock is not None else nullcontext():
        manifest = load_manifest(manifest_path)
        existing = next(
            (
                entry for entry in manifest.get("unnumbered_leaves", [])
                if entry.get("leaf_num") == leaf_num
            ),
            None,
        )
    if not force and existing and jpeg_path.exists():
        cached_sha256 = "sha256:" + hashlib.sha256(jpeg_path.read_bytes()).hexdigest()
        if cached_sha256 == existing.get("sha256", ""):
            logger.info(
                "[vol_%02d] leaf %04d -- skipped (cached, sha256 match)",
                volume,
                leaf_num,
            )
            return None

    prefix = zip_name.replace("_jp2.zip", "")
    internal_path = f"{prefix}_jp2/{prefix}_{leaf_num:04d}.jp2"
    zip_url = f"{_IA_BASE_URL.format(item_id=item_id)}/{zip_name}"
    out_dir.mkdir(parents=True, exist_ok=True)
    jpeg_result, _ = _fetch_and_encode_jpeg(
        zip_url,
        internal_path,
        {"User-Agent": USER_AGENT},
        jpeg_path,
    )
    entry = {
        "leaf_num": leaf_num,
        "page_num": None,
        "page_type": page_type,
        "section": section,
        "ia_leaf_id": f"{leaf_num:04d}",
        "ia_filename": f"{zip_name}/{internal_path}",
        "ia_item_id": item_id,
        "local_path": (
            jpeg_path.relative_to(REPO_ROOT)
            if jpeg_path.is_relative_to(REPO_ROOT)
            else jpeg_path
        ).as_posix(),
        "sha256": jpeg_result.sha256,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "image_mode": jpeg_result.image_mode,
        "image_size": jpeg_result.image_size,
    }
    with manifest_lock if manifest_lock is not None else nullcontext():
        if manifest_lock is not None:
            manifest = load_manifest(manifest_path)
        leaves = [
            row for row in manifest.get("unnumbered_leaves", [])
            if row.get("leaf_num") != leaf_num
        ]
        leaves.append(entry)
        leaves.sort(key=lambda row: row["leaf_num"])
        manifest["unnumbered_leaves"] = leaves
        if manifest.get("volume") is None:
            manifest["volume"] = volume
        write_manifest_atomic(manifest_path, manifest)
    logger.info(
        "[vol_%02d] leaf %04d -- %.1fs -- fetched (mode=%s size=%dx%d)",
        volume,
        leaf_num,
        jpeg_result.elapsed,
        jpeg_result.image_mode,
        jpeg_result.image_size[0],
        jpeg_result.image_size[1],
    )
    return entry


# ---------------------------------------------------------------------------
# Network helpers for CLI (not used in unit tests)
# ---------------------------------------------------------------------------
def _fetch_xml(url: str) -> ET.Element:
    """Fetch and parse an XML file from IA with retry."""
    data = fetch_url_bytes(url, headers={"User-Agent": USER_AGENT})
    return ET.fromstring(data)


def _fetch_metadata(item_id: str) -> dict:
    """Fetch IA metadata JSON for bibliographic comparison."""
    url = f"https://archive.org/metadata/{item_id}"
    data = fetch_url_bytes(url, headers={"User-Agent": USER_AGENT})
    return json.loads(data)


def _bibliographic_signature(payload: dict) -> tuple[str, str, str]:
    metadata = payload.get("metadata", payload)

    def normalize(value: object) -> str:
        if isinstance(value, list):
            value = "; ".join(str(item) for item in value)
        return " ".join(str(value or "").lower().split())

    return (
        normalize(metadata.get("publisher")),
        normalize(metadata.get("year") or metadata.get("date")),
        normalize(metadata.get("editor") or metadata.get("creator")),
    )


def bibliographic_validation_status(primary: dict, alternate: dict) -> str:
    """Compare publisher, year and editor metadata for an alternate item."""
    if _bibliographic_signature(primary) == _bibliographic_signature(alternate):
        return "bibliographic_matched"
    logger.warning(
        "Alternate-item bibliographic metadata does not match the primary item; "
        "recording visual_header_only validation status"
    )
    return "visual_header_only"


def _resolve_volume(item_id: str, volume: int) -> tuple:
    """Return (zip_name, page_to_leaf_map, total_pages, scandata_info) for a volume.

    ``scandata_info`` is the structured dict from :func:`load_scandata_pages`
    (page_to_leaf, duplicates, numbered_range, missing_pages) so callers can
    record scan gaps and flag duplicate leaves rather than silently dropping
    them.
    """
    files_url = f"{_IA_BASE_URL.format(item_id=item_id)}/{item_id}_files.xml"
    files_root = _fetch_xml(files_url)
    zip_name = find_jp2_zip(files_root, volume)

    prefix = zip_name.replace("_jp2.zip", "")
    scandata_name = f"{prefix}_scandata.xml"
    scandata_url = f"{_IA_BASE_URL.format(item_id=item_id)}/{scandata_name}"
    scandata_root = _fetch_xml(scandata_url)
    scandata_info = load_scandata_pages(scandata_root)
    page_to_leaf = scandata_info["page_to_leaf"]
    total_pages = len(
        scandata_root.findall(".//{http://www.archive.org/scandata}page")
        or scandata_root.findall(".//page")
    )
    return zip_name, page_to_leaf, total_pages, scandata_info


def record_scandata_gaps(
    manifest_path: Path,
    missing_pages: list[int],
    duplicates: dict[int, list[int]],
) -> None:
    """Record in-scan body gaps and duplicate-leaf flags in the manifest.

    ``missing_pages`` (printed pages with no leaf in the scan) become gap entries
    with status ``absent_from_primary_scan`` -- preserved holes, never squeezed.
    ``duplicates`` (printed page tagged on >1 leaf) are recorded with status
    ``duplicate_needs_adjudication`` so a human/OCR pass can pick the clean leaf;
    they are NOT body-missing (the page is present) so they do not change
    page_count. Idempotent: an existing entry for a page is left as-is unless its
    status is the generic ``unresolved`` placeholder.
    """
    manifest = load_manifest(Path(manifest_path))
    gaps_by_page = {
        g["page_num"]: g
        for g in manifest.get("gaps", [])
        if isinstance(g.get("page_num"), int)
    }
    changed = False
    for page_num in sorted(set(missing_pages)):
        existing = gaps_by_page.get(page_num)
        if existing is None or existing.get("status") == "unresolved":
            gaps_by_page[page_num] = {
                "page_num": page_num,
                "status": "absent_from_primary_scan",
                "investigation_note": (
                    "printed page has no leaf in the IA scandata; genuine scan gap"
                ),
            }
            changed = True
    for page_num, leaves in sorted(duplicates.items()):
        existing = gaps_by_page.get(page_num)
        if existing is None or existing.get("status") == "unresolved":
            gaps_by_page[page_num] = {
                "page_num": page_num,
                "status": "duplicate_needs_adjudication",
                "duplicate_leaves": sorted(leaves),
                "investigation_note": (
                    "printed page tagged on multiple scandata leaves; OCR/visual "
                    "adjudication needed to pick the clean leaf"
                ),
            }
            changed = True
    if changed:
        manifest["gaps"] = [gaps_by_page[p] for p in sorted(gaps_by_page)]
        write_manifest_atomic(Path(manifest_path), manifest)


def _resolve_unnumbered_leaves(item_id: str, zip_name: str) -> list[dict]:
    """Load unnumbered front- and back-matter leaves for a primary volume."""
    prefix = zip_name.replace("_jp2.zip", "")
    scandata_name = f"{prefix}_scandata.xml"
    scandata_url = f"{_IA_BASE_URL.format(item_id=item_id)}/{scandata_name}"
    return load_unnumbered_leaves(_fetch_xml(scandata_url))


def _primary_image_size(manifest_path: Path) -> list[int] | None:
    manifest = load_manifest(manifest_path)
    primary_id = manifest.get("ia_item_id", IA_ITEM_ID)
    for entry in manifest.get("pages", []):
        if entry.get("ia_item_id", primary_id) == primary_id:
            return entry.get("image_size")
    return None


def _run_fetch_worker(
    specs: list,
    fetch_fn,
    error_label: str,
) -> tuple[int, int, int]:
    """Run fetch_fn over specs, counting fetched/skipped/errors."""
    fetched = skipped = errors = 0
    for index, spec in enumerate(specs):
        result = None
        try:
            result = fetch_fn(spec)
            if result is None:
                skipped += 1
            else:
                fetched += 1
        except (RuntimeError, ValueError) as exc:
            logger.error("%s -- %s", error_label, exc)
            errors += 1
        if result is not None and index < len(specs) - 1:
            time.sleep(CRAWL_DELAY)
    return fetched, skipped, errors


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch IA JP2 pages as JPEG cache files with per-volume manifest."
    )
    parser.add_argument("--item-id", default=IA_ITEM_ID)
    parser.add_argument("--volume", type=int, required=True, help="Volume number (1-13)")
    parser.add_argument(
        "--pages",
        help="Pages to fetch: 'all', '42-49' range, or '75,100,164' comma-list",
    )
    parser.add_argument("--out-dir", default=None, help="JPEG output directory")
    parser.add_argument("--manifest", default=None, help="Manifest JSON path")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if sha256 matches")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel download workers")
    parser.add_argument(
        "--include-unnumbered",
        action="store_true",
        help="Also fetch front- and back-matter leaves without printed page numbers",
    )
    parser.add_argument(
        "--from-alternate-item",
        metavar="ITEM",
        help="Fetch replacement numbered pages from an alternate IA item",
    )
    parser.add_argument(
        "--leaf-page-spec",
        metavar="SPEC",
        help="Alternate item mappings as LEAF:PAGE[:left|right], comma-separated",
    )
    parser.add_argument(
        "--primary-leaf-page-spec",
        metavar="SPEC",
        help=(
            "Fetch explicit PRIMARY-item leaves under printed-page names as "
            "LEAF:PAGE[:left|right], comma-separated. For front body pages that "
            "carry no scandata pageNumber (mapped by a constant leaf offset); "
            "unlike --leaf-page-spec these carry NO alternate-provenance block."
        ),
    )
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if not args.pages and not args.from_alternate_item and not args.primary_leaf_page_spec:
        parser.error(
            "--pages is required unless --from-alternate-item or "
            "--primary-leaf-page-spec is used"
        )
    if bool(args.from_alternate_item) != bool(args.leaf_page_spec):
        parser.error("--from-alternate-item and --leaf-page-spec must be used together")

    _setup_logging(args.verbose)

    vol_str = f"vol_{args.volume:02d}"
    out_dir = Path(args.out_dir) if args.out_dir else DEFAULT_OUT_BASE / vol_str
    manifest_path = (
        Path(args.manifest) if args.manifest
        else DEFAULT_OUT_BASE / f"{vol_str}.manifest.json"
    )

    logger.info("Resolving volume %d from IA...", args.volume)
    zip_name, page_to_leaf, total_pages, scandata_info = _resolve_volume(
        args.item_id, args.volume
    )
    logger.info("ZIP: %s  |  %d pages with leaf mapping", zip_name, len(page_to_leaf))
    if scandata_info["missing_pages"]:
        logger.warning(
            "Scan gaps (printed pages with no leaf): %s", scandata_info["missing_pages"]
        )
    if scandata_info["duplicates"]:
        logger.warning(
            "Duplicate pageNumbers (need adjudication): %s",
            {p: leaves for p, leaves in sorted(scandata_info["duplicates"].items())},
        )

    if args.pages and args.pages.strip() == "all":
        # "all" means every TRUE printed page in the scandata, not a 1..leafcount
        # range. Enumerating the real numbered keys preserves gaps as holes and
        # avoids the contiguous-range assumption that fed the squeeze corruption.
        page_nums = sorted(page_to_leaf)
    else:
        page_nums = parse_pages_arg(args.pages, total_pages) if args.pages else []
    logger.info("Pages to fetch: %d page(s)", len(page_nums))

    manifest_lock = threading.Lock()

    def fetch_worker(worker_pages: list[int]) -> tuple[int, int, int]:
        def fetch_numbered_page(page_num: int) -> dict | None:
            if page_num not in page_to_leaf:
                raise ValueError(f"page {page_num:04d} has no leaf mapping")
            return fetch_page(
                volume=args.volume,
                page_num=page_num,
                leaf_num=page_to_leaf[page_num],
                zip_name=zip_name,
                out_dir=out_dir,
                manifest_path=manifest_path,
                dry_run=args.dry_run,
                force=args.force,
                item_id=args.item_id,
                manifest_lock=manifest_lock,
            )

        return _run_fetch_worker(
            worker_pages,
            fetch_numbered_page,
            f"[vol_{args.volume:02d}]",
        )

    worker_slices = [page_nums[i::args.workers] for i in range(args.workers)]
    fetched = skipped = errors = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for worker_fetched, worker_skipped, worker_errors in executor.map(fetch_worker, worker_slices):
            fetched += worker_fetched
            skipped += worker_skipped
            errors += worker_errors

    primary_leaf_page_nums = []
    if args.primary_leaf_page_spec:
        try:
            primary_leaf_specs = parse_leaf_page_spec(args.primary_leaf_page_spec)
        except ValueError as exc:
            parser.error(str(exc))
        primary_leaf_page_nums = [page_num for _, page_num, _ in primary_leaf_specs]

        def fetch_primary_leaf_worker(
            worker_specs: list[tuple[int, int, str | None]],
        ) -> tuple[int, int, int]:
            def fetch_primary_leaf(spec: tuple[int, int, str | None]) -> dict | None:
                leaf_num, page_num, crop = spec
                # No alternate_source_leaf -> a plain primary page entry with
                # no provenance block (front body pages are primary leaves).
                return fetch_page(
                    volume=args.volume,
                    page_num=page_num,
                    leaf_num=leaf_num,
                    zip_name=zip_name,
                    out_dir=out_dir,
                    manifest_path=manifest_path,
                    dry_run=args.dry_run,
                    force=args.force,
                    item_id=args.item_id,
                    manifest_lock=manifest_lock,
                    crop=crop,
                )

            return _run_fetch_worker(
                worker_specs,
                fetch_primary_leaf,
                f"[vol_{args.volume:02d}] primary leaf",
            )

        primary_leaf_slices = [
            primary_leaf_specs[index::args.workers] for index in range(args.workers)
        ]
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            for run_counts in executor.map(
                fetch_primary_leaf_worker, primary_leaf_slices
            ):
                fetched += run_counts[0]
                skipped += run_counts[1]
                errors += run_counts[2]

    alternate_page_nums = []
    if args.from_alternate_item:
        try:
            alternate_specs = parse_leaf_page_spec(args.leaf_page_spec)
        except ValueError as exc:
            parser.error(str(exc))
        alternate_page_nums = [page_num for _, page_num, _ in alternate_specs]
        alternate_zip_name, _, _, _ = _resolve_volume(
            args.from_alternate_item,
            args.volume,
        )
        validation_status = bibliographic_validation_status(
            _fetch_metadata(args.item_id),
            _fetch_metadata(args.from_alternate_item),
        )
        primary_image_size = _primary_image_size(manifest_path)

        def fetch_alternate_worker(
            worker_specs: list[tuple[int, int, str | None]],
        ) -> tuple[int, int, int]:
            def fetch_alternate_spec(spec: tuple[int, int, str | None]) -> dict | None:
                leaf_num, page_num, crop = spec
                return fetch_alternate_page(
                    volume=args.volume,
                    page_num=page_num,
                    leaf_num=leaf_num,
                    crop=crop,
                    zip_name=alternate_zip_name,
                    out_dir=out_dir,
                    manifest_path=manifest_path,
                    dry_run=args.dry_run,
                    force=args.force,
                    item_id=args.from_alternate_item,
                    validation_status=validation_status,
                    primary_image_size=primary_image_size,
                    manifest_lock=manifest_lock,
                )

            return _run_fetch_worker(
                worker_specs,
                fetch_alternate_spec,
                f"[vol_{args.volume:02d}] alternate",
            )

        alternate_slices = [
            alternate_specs[index::args.workers] for index in range(args.workers)
        ]
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            for run_counts in executor.map(fetch_alternate_worker, alternate_slices):
                fetched += run_counts[0]
                skipped += run_counts[1]
                errors += run_counts[2]

    if args.include_unnumbered:
        unnumbered_leaves = _resolve_unnumbered_leaves(args.item_id, zip_name)
        logger.info("Unnumbered leaves to fetch: %d", len(unnumbered_leaves))

        def fetch_unnumbered_worker(worker_leaves: list[dict]) -> tuple[int, int, int]:
            return _run_fetch_worker(
                worker_leaves,
                lambda leaf: fetch_unnumbered_leaf(
                    volume=args.volume,
                    leaf_num=leaf["leaf_num"],
                    page_type=leaf["page_type"],
                    section=leaf["section"],
                    zip_name=zip_name,
                    out_dir=out_dir,
                    manifest_path=manifest_path,
                    dry_run=args.dry_run,
                    force=args.force,
                    item_id=args.item_id,
                    manifest_lock=manifest_lock,
                ),
                f"[vol_{args.volume:02d}] unnumbered",
            )

        leaf_slices = [
            unnumbered_leaves[index::args.workers] for index in range(args.workers)
        ]
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            for run_counts in executor.map(fetch_unnumbered_worker, leaf_slices):
                fetched += run_counts[0]
                skipped += run_counts[1]
                errors += run_counts[2]

    if not args.dry_run:
        # Record genuine scan gaps and duplicate-leaf flags from the scandata
        # (only meaningful for a full-volume "all" fetch of the primary item).
        if args.pages and args.pages.strip() == "all" and not args.from_alternate_item:
            record_scandata_gaps(
                manifest_path,
                scandata_info["missing_pages"],
                scandata_info["duplicates"],
            )
        record_unresolved_gaps(
            manifest_path,
            page_nums + primary_leaf_page_nums + alternate_page_nums,
        )

    logger.info(
        "Done. fetched=%d skipped=%d errors=%d (volume %d)",
        fetched, skipped, errors, args.volume,
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
