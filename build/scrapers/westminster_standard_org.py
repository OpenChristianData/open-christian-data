"""build/scrapers/westminster_standard_org.py
Fetches and caches HTML pages from thewestminsterstandard.org.

Usage:
    py -3 build/scrapers/westminster_standard_org.py --all
    py -3 build/scrapers/westminster_standard_org.py --slug westminster-shorter-catechism
    py -3 build/scrapers/westminster_standard_org.py --all --force
"""

import argparse
import datetime
import sys
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "raw" / "westminster-standard-org"
LOG_FILE = Path(__file__).resolve().parent / "westminster_standard_org.log"

BASE_URL = "https://thewestminsterstandard.org"

PAGES = {
    "westminster-shorter-catechism": "/westminster-shorter-catechism/",
    "directory-for-publick-worship": "/directory-for-the-publick-worship-of-god/",
    "directory-for-family-worship": "/directory-for-family-worship",
    "form-of-church-government": "/form-of-presbyterial-church-government/",
    "solemn-league-and-covenant": "/the-solemn-league-and-covenant/",
    "sum-of-saving-knowledge": "/the-sum-of-saving-knowledge/",
}

USER_AGENT = "Mozilla/5.0 (compatible; OCD-scraper/1.0)"


def _log(message: str) -> None:
    """Write a timestamped entry to the log file and print to stdout."""
    timestamp = datetime.datetime.now(ZoneInfo("Australia/Melbourne")).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    print(entry)
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(entry + "\n")


def fetch_page(slug: str, force: bool = False) -> str:
    """Fetch a single page by slug.

    Returns:
        "fetched", "skipped", or "failed"
    """
    output_path = OUTPUT_DIR / f"{slug}.html"

    if output_path.exists() and not force:
        _log(f"Skipped (cached): {slug}")
        return "skipped"

    url = BASE_URL + PAGES[slug]
    _log(f"Fetching: {slug} from {url}")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as response:
            html_bytes = response.read()

        output_path.write_bytes(html_bytes)
        size = len(html_bytes)
        _log(f"Fetched: {slug} ({size} bytes)")
        return "fetched"

    except urllib.error.HTTPError as exc:
        _log(f"ERROR fetching {slug}: HTTP {exc.code} {exc.reason}")
        return "failed"
    except urllib.error.URLError as exc:
        _log(f"ERROR fetching {slug}: {exc.reason}")
        return "failed"
    except Exception as exc:  # noqa: BLE001
        _log(f"ERROR fetching {slug}: {exc}")
        return "failed"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch and cache HTML pages from thewestminsterstandard.org"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--slug", metavar="NAME", help="Fetch one page by slug")
    group.add_argument("--all", action="store_true", help="Fetch all 6 pages")
    parser.add_argument(
        "--force", action="store_true", help="Re-fetch even if cached HTML exists"
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.slug:
        if args.slug not in PAGES:
            print(f"Unknown slug: {args.slug!r}")
            print("Available slugs:")
            for s in PAGES:
                print(f"  {s}")
            sys.exit(1)
        slugs = [args.slug]
    else:
        slugs = list(PAGES.keys())

    total = len(slugs)
    fetched = 0
    skipped = 0
    failed = 0

    for i, slug in enumerate(slugs, start=1):
        if total > 1:
            print(f"Fetching page {i} of {total}: {slug}...")
        result = fetch_page(slug, force=args.force)
        if result == "fetched":
            fetched += 1
        elif result == "skipped":
            skipped += 1
        else:
            failed += 1

    summary = f"Done. Fetched {fetched} page(s), skipped {skipped} cached, {failed} failed."
    _log(summary)


if __name__ == "__main__":
    main()
