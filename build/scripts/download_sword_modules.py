"""download_sword_modules.py
Download SWORD module ZIPs from CrossWire for the Open Christian Data project.

Respects CrossWire robots.txt:
  - Crawl-delay: 30 seconds between requests
  - Uses servlet endpoint (NOT /ftpmirror/pub/sword/raw/modules/ which is Disallowed)
  - User-Agent identifies the project

Usage:
    py -3 build/scripts/download_sword_modules.py           (download all modules)
    py -3 build/scripts/download_sword_modules.py --dry-run (log what would be downloaded)

Downloads to: raw/sword_modules/{module_name}.zip
Logs to:      build/scripts/download_sword_modules.log
"""

import argparse
import hashlib
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "raw" / "sword_modules"
LOG_FILE = Path(__file__).parent / "download_sword_modules.log"
MANIFEST_FILE = RAW_DIR / "manifest.json"

# CrossWire direct package URL for per-module ZIPs.
# The servlet (SwordMod.Verify?modName=X&pkgType=raw) returns an HTML meta-refresh
# pointing here -- /ftpmirror/pub/sword/packages/rawzip/ is NOT in robots.txt Disallow.
# Confirmed allowed: only /ftpmirror/pub/sword/raw/modules/ and /ftpmirror/pub/sword/iso/
# are disallowed per robots.txt checked 2026-03-28.
SWORD_URL_TEMPLATE = (
    "https://www.crosswire.org/ftpmirror/pub/sword/packages/rawzip/{name}.zip"
)

USER_AGENT = (
    "OpenChristianData/1.0 "
    "(research; open-source data project; "
    "contact: openchristiandata@gmail.com)"
)

CRAWL_DELAY_SECONDS = 30  # per robots.txt

# Modules to download (name -> description)
MODULES = [
    {"name": "Barnes",             "description": "Barnes' Notes on the NT"},
    {"name": "CalvinCommentaries", "description": "Calvin's Commentaries (47 books)"},
    {"name": "Wesley",             "description": "Wesley's Notes on the Bible"},
    {"name": "Daily",              "description": "Daily Light on the Daily Path (devotional)"},
]


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_valid_zip(path: Path) -> bool:
    """Return True if file starts with the ZIP magic bytes (PK\\x03\\x04)."""
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
        return magic == b"PK\x03\x04"
    except OSError:
        return False


def download_module(name: str, dest: Path, dry_run: bool) -> dict:
    """
    Download a single SWORD module ZIP.
    Returns a dict with download metadata.
    Skips if already cached AND the file is a valid ZIP.
    Re-downloads if the cached file is not a valid ZIP (e.g., HTML redirect stub).
    """
    url = SWORD_URL_TEMPLATE.format(name=name)
    result = {
        "name": name,
        "url": url,
        "dest": str(dest),
        "status": None,
        "size_bytes": None,
        "sha256": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if dest.exists():
        if is_valid_zip(dest):
            sha = sha256_file(dest)
            size = dest.stat().st_size
            logging.info("CACHED %s -> %s (%d bytes, sha256:%s)", name, dest.name, size, sha[:16] + "...")
            result.update(status="cached", size_bytes=size, sha256=sha)
            return result
        else:
            size = dest.stat().st_size
            logging.warning("INVALID CACHE %s (%d bytes, not a ZIP) -- will re-download", dest.name, size)

    if dry_run:
        logging.info("DRY-RUN would download: %s -> %s", url, dest.name)
        result["status"] = "dry-run"
        return result

    logging.info("Downloading %s ...", name)
    logging.info("  URL: %s", url)

    # Retry on transient HTTP failures (Rule 21): 3 attempts, 2/4/8s backoff.
    # Don't retry 4xx client errors (except 429 rate limit).
    TRANSIENT_CODES = {429, 500, 502, 503}
    MAX_RETRIES = 3
    data = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            break  # success
        except urllib.error.HTTPError as exc:
            if exc.code in TRANSIENT_CODES and attempt < MAX_RETRIES:
                delay = 2 ** attempt  # 2s, 4s, 8s
                logging.warning("  HTTP %d on attempt %d -- retrying in %ds ...", exc.code, attempt, delay)
                time.sleep(delay)
            else:
                logging.error("  FAILED to download %s: HTTP %d", name, exc.code)
                result["status"] = f"error: HTTP {exc.code}"
                return result
        except Exception as exc:
            if attempt < MAX_RETRIES:
                delay = 2 ** attempt
                logging.warning("  Error on attempt %d (%s) -- retrying in %ds ...", attempt, exc, delay)
                time.sleep(delay)
            else:
                logging.error("  FAILED to download %s: %s", name, exc)
                result["status"] = f"error: {exc}"
                return result

    try:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)

        # Verify the download is a valid ZIP -- CrossWire can return an HTML error
        # page with HTTP 200 (e.g. module not found, CDN error). Without this check
        # the manifest would record a corrupt file as successfully downloaded.
        if not is_valid_zip(dest):
            size = len(data)
            logging.error(
                "  FAILED %s: downloaded %d bytes but file is not a valid ZIP "
                "(possible HTML error page from CrossWire). File left on disk for inspection: %s",
                name, size, dest,
            )
            result["status"] = "error: not a valid ZIP after download"
            return result

        sha = sha256_file(dest)
        size = len(data)
        logging.info("  Downloaded %d bytes -> %s", size, dest.name)
        logging.info("  SHA-256: %s", sha)
        result.update(status="downloaded", size_bytes=size, sha256=sha)
    except Exception as exc:
        logging.error("  FAILED to write %s: %s", name, exc)
        result["status"] = f"error: {exc}"

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Download SWORD module ZIPs from CrossWire"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be downloaded without making requests",
    )
    args = parser.parse_args()

    start_time = time.time()
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    logging.info("=== SWORD Module Download ===")
    logging.info("Output dir: %s", RAW_DIR)
    logging.info("Modules: %s", ", ".join(m["name"] for m in MODULES))
    if args.dry_run:
        logging.info("Mode: DRY-RUN")
    logging.info("")

    results = []
    for i, module in enumerate(MODULES):
        name = module["name"]
        dest = RAW_DIR / f"{name}.zip"

        result = download_module(name, dest, dry_run=args.dry_run)
        results.append(result)

        # Apply crawl delay between requests (not after last, not for cached files)
        is_last = i == len(MODULES) - 1
        needs_delay = not is_last and result["status"] not in ("cached", "dry-run")
        if needs_delay:
            logging.info("  Waiting %ds (robots.txt crawl-delay) ...", CRAWL_DELAY_SECONDS)
            time.sleep(CRAWL_DELAY_SECONDS)

    # Save manifest
    if not args.dry_run:
        with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
            f.write("\n")
        logging.info("")
        logging.info("Manifest saved: %s", MANIFEST_FILE)

    # Summary
    elapsed = time.time() - start_time
    downloaded = sum(1 for r in results if r["status"] == "downloaded")
    cached = sum(1 for r in results if r["status"] == "cached")
    failed = sum(1 for r in results if r["status"] and r["status"].startswith("error"))
    skipped = sum(1 for r in results if r["status"] == "dry-run")

    logging.info("")
    logging.info("=== Summary ===")
    logging.info("Downloaded: %d  Cached: %d  Failed: %d  Dry-run: %d", downloaded, cached, failed, skipped)
    logging.info("Elapsed: %.1fs", elapsed)

    if failed:
        logging.error("%d module(s) failed to download", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
