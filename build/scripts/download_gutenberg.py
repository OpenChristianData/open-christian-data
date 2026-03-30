"""download_gutenberg.py
Download Project Gutenberg public domain texts for the Open Christian Data project.

Follows respectful downloading standards:
  - Checks robots.txt first (done: /ebooks/search disallowed; cache URLs are fine)
  - 2-second minimum delay between requests
  - Custom User-Agent identifying the project
  - SHA-256 hash of every downloaded file
  - Skips already-cached files (never re-downloads)
  - Logs all requests

Texts downloaded:
  Catechisms:
    1670  Luther's Small Catechism (Bente/Dau 1921)
    1722  Luther's Large Catechism (Bente/Dau 1921)
    14552 Baltimore Catechism No. 2 (1885)
    14551 Baltimore Catechism No. 1 (1885)
    14553 Baltimore Catechism No. 3 (1885)

  Theological works:
    45001 Calvin's Institutes Vol. 1 (Beveridge 1845)
    64392 Calvin's Institutes Vol. 2 (Beveridge 1845)
    3296  Augustine's Confessions (Pusey translation)

City of God (45304, 45305) is SKIPPED -- already covered by Standard Ebooks T1-4.
Imitation of Christ (26222) is SKIPPED -- covered by Standard Ebooks T1-4.

Usage:
    py -3 build/scripts/download_gutenberg.py
    py -3 build/scripts/download_gutenberg.py --dry-run
"""

import argparse
import hashlib
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = REPO_ROOT / "raw" / "gutenberg"
LOG_FILE = Path(__file__).resolve().parent / "download_gutenberg.log"

USER_AGENT = (
    "OpenChristianData/1.0 "
    "(research; open-source data project; contact: openchristiandata@gmail.com)"
)

# Cache URL format (avoids the ebooks/ redirect hop)
CACHE_URL = "http://www.gutenberg.org/cache/epub/{pg_id}/pg{pg_id}.txt"

# 2-second minimum delay between requests (PG courtesy policy)
REQUEST_DELAY = 2.0

# Texts to download: (pg_id, description, notes)
TEXTS = [
    (1670,  "Luther's Small Catechism",    "Bente/Dau 1921 translation; catechism Q&A"),
    (1722,  "Luther's Large Catechism",    "Bente/Dau 1921 translation; structured prose"),
    (14552, "Baltimore Catechism No. 2",   "Original 1885; numbered Q&A"),
    (14551, "Baltimore Catechism No. 1",   "Original 1885; first communion edition"),
    (14553, "Baltimore Catechism No. 3",   "Original 1885; post-confirmation edition"),
    (45001, "Calvin's Institutes Vol. 1",  "Beveridge 1845 translation; Books I-II"),
    (64392, "Calvin's Institutes Vol. 2",  "Beveridge 1845 translation; Books III-IV"),
    (3296,  "Augustine's Confessions",     "Pusey translation; 13 books"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(message: str, log_lines: list) -> None:
    """Print to console (ASCII only) and append to log list."""
    print(message)
    log_lines.append(message)


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def download_text(url: str, timeout: int = 60) -> bytes:
    """Download URL with OCD User-Agent. Returns raw bytes."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Download PG texts for Open Christian Data")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be downloaded without fetching")
    args = parser.parse_args()

    log_lines = []
    run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_time = time.time()

    log(f"[{run_timestamp}] Gutenberg downloader -- {'DRY RUN' if args.dry_run else 'LIVE RUN'}", log_lines)
    log(f"Output dir: {OUTPUT_DIR}", log_lines)
    log(f"Texts to process: {len(TEXTS)}", log_lines)
    log("", log_lines)

    if not args.dry_run:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    skipped = 0
    errors = 0

    for i, (pg_id, title, notes) in enumerate(TEXTS):
        out_path = OUTPUT_DIR / f"pg{pg_id}.txt"
        url = CACHE_URL.format(pg_id=pg_id)

        log(f"[{i+1}/{len(TEXTS)}] PG#{pg_id}: {title}", log_lines)
        log(f"  URL: {url}", log_lines)

        # Skip if already cached
        if out_path.exists():
            cached_hash = sha256_file(out_path)
            size_kb = out_path.stat().st_size // 1024
            log(f"  SKIP -- already cached ({size_kb} KB, {cached_hash})", log_lines)
            skipped += 1
            continue

        if args.dry_run:
            log(f"  DRY RUN -- would download to {out_path}", log_lines)
            skipped += 1
            continue

        # Enforce delay between live requests (skip before first attempt)
        if downloaded + errors > 0:
            log(f"  Waiting {REQUEST_DELAY}s...", log_lines)
            time.sleep(REQUEST_DELAY)

        # Download
        try:
            data = download_text(url)
            file_hash = sha256_bytes(data)
            out_path.write_bytes(data)
            size_kb = len(data) // 1024
            log(f"  Downloaded: {size_kb} KB, {file_hash}", log_lines)
            log(f"  Saved: {out_path}", log_lines)
            downloaded += 1
        except Exception as exc:
            log(f"  ERROR: PG#{pg_id} ({url}) -- {exc}. Retry manually.", log_lines)
            errors += 1

        log("", log_lines)

    elapsed = time.time() - start_time
    log("", log_lines)
    log(f"Done -- {downloaded} downloaded, {skipped} skipped, {errors} errors, {elapsed:.1f}s", log_lines)

    # Write log
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n\n")

    if errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
