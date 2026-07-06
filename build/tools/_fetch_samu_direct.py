"""Fetch vol_10 page 501 from newschaffherzoge0010samu using direct US datanode URL.

Bypasses the archive.org/download/ redirect that routes to a dead EU node.
Uses ia801402.us.archive.org/32/items/ directly (from metadata d1/d2 + dir).

One-shot script -- not wired into the pipeline, just for this fetch.
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_PAGES = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(REPO_ROOT))

import io

from PIL import Image

from fetch_ia_pages import (  # noqa: E402
    JPEG_QUALITY,
    USER_AGENT,
    _download_jp2,
    load_manifest,
    write_manifest_atomic,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

ITEM_ID = "newschaffherzoge0010samu"
ZIP_NAME = "newschaffherzoge0010samu_jp2.zip"
SCANDATA_NAME = "newschaffherzoge0010samu_scandata.xml"
VOL_NUM = 10
TARGET_PAGE = 501

# Direct US datanodes from archive.org/metadata/newschaffherzoge0010samu
# server=ia801402.us.archive.org, d1=ia601402.us.archive.org, dir=/32/items/...
DIRECT_BASE_URLS = [
    "https://ia801402.us.archive.org/32/items/newschaffherzoge0010samu",
    "https://ia601402.us.archive.org/32/items/newschaffherzoge0010samu",
]


def _fetch_url(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _get_scandata() -> ET.Element:
    for base in DIRECT_BASE_URLS:
        url = f"{base}/{SCANDATA_NAME}"
        try:
            logger.info("Fetching scandata from %s", url)
            data = _fetch_url(url)
            return ET.fromstring(data)
        except Exception as exc:
            logger.warning("  failed: %s", exc)
    raise RuntimeError("Could not fetch scandata from any direct server")


def _find_leaf_for_page(root: ET.Element, page_num: int) -> int | None:
    """Return the leafNum for a given printed page number from scandata XML."""
    for ns_prefix in ["{http://www.archive.org/scandata}", ""]:
        for page_el in root.findall(f".//{ns_prefix}page"):
            pn_el = page_el.find(f"{ns_prefix}pageNumber")
            if pn_el is None or not pn_el.text:
                continue
            if pn_el.text.strip() == str(page_num):
                ln_el = page_el.find(f"{ns_prefix}leafNum")
                if ln_el is not None and ln_el.text:
                    return int(ln_el.text)
                # Some scandata uses the 'n' attribute on <page>
                order = page_el.get("leafNum") or page_el.get("n")
                if order is not None:
                    return int(order)
    return None


def main() -> None:
    out_dir = RAW_PAGES / f"vol_{VOL_NUM:02d}"
    manifest_path = RAW_PAGES / f"vol_{VOL_NUM:02d}.manifest.json"
    out_path = out_dir / f"page_{TARGET_PAGE:04d}.jpg"

    if out_path.exists():
        logger.info("Already exists: %s", out_path)
        return

    # Step 1: find the leaf number from scandata
    root = _get_scandata()
    leaf_num = _find_leaf_for_page(root, TARGET_PAGE)
    if leaf_num is None:
        raise RuntimeError(f"Page {TARGET_PAGE} not found in scandata")
    logger.info("Page %d => leaf %d", TARGET_PAGE, leaf_num)

    # Step 2: download the JP2 via range request using the direct US node URL
    internal_path = f"{ITEM_ID}_jp2/{ITEM_ID}_{leaf_num:04d}.jp2"
    headers = {"User-Agent": USER_AGENT}
    last_err: Exception | None = None
    jp2_bytes: bytes | None = None
    for base in DIRECT_BASE_URLS:
        zip_url = f"{base}/{ZIP_NAME}"
        logger.info("Trying zip range request: %s  internal: %s", zip_url, internal_path)
        try:
            jp2_bytes = _download_jp2(zip_url, internal_path, headers)
            logger.info("Downloaded JP2: %d bytes", len(jp2_bytes))
            break
        except Exception as exc:
            logger.warning("  failed: %s", exc)
            last_err = exc

    if jp2_bytes is None:
        raise RuntimeError(f"Could not download JP2 from any direct server") from last_err

    # Step 3: convert to JPEG
    img = Image.open(io.BytesIO(jp2_bytes))
    mode = img.mode
    size = list(img.size)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
    jpeg_bytes = buf.getvalue()
    logger.info("Converted to JPEG: mode=%s size=%dx%d bytes=%d", mode, size[0], size[1], len(jpeg_bytes))

    # Step 4: write to disk
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(jpeg_bytes)
    logger.info("Written: %s", out_path)

    # Step 5: add entry to manifest (mimicking fetch_alternate_page's manifest entry format)
    manifest = load_manifest(manifest_path)
    manifest_lock = threading.Lock()
    with manifest_lock:
        pages = manifest.setdefault("pages", [])
        # Remove any stale entry for this page+item combo
        manifest["pages"] = [
            p for p in pages
            if not (p.get("page") == TARGET_PAGE and p.get("ia_item_id") == ITEM_ID)
        ]
        rel_path = out_path.relative_to(REPO_ROOT)
        manifest["pages"].append({
            "page": TARGET_PAGE,
            "leaf_num": leaf_num,
            "ia_item_id": ITEM_ID,
            "local_path": str(rel_path).replace("\\", "/"),
            "image_size": size,
            "validation_status": "visual_header_only",
        })
        write_manifest_atomic(manifest_path, manifest)
    logger.info("Manifest updated: %s", manifest_path)


if __name__ == "__main__":
    main()
