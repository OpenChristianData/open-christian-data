"""puritan_census.py
Structural census for T6-1 Puritan batch sources.

Downloads one file per author (if not cached) and prints:
  - First 30 non-blank lines of body
  - All lines matching likely heading patterns (ALL CAPS, Chapter/CHAPTER, Volume/VOLUME, DEVICE/REMEDY)

Run:
    py -3 build/tools/puritan_census.py
"""

import re
import time
import urllib.error
import urllib.request  # standards: download only
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_PG_DIR = REPO_ROOT / "raw" / "gutenberg"
RAW_IA_DIR = REPO_ROOT / "raw" / "ia"

USER_AGENT = (
    "OpenChristianData/1.0 "
    "(research; open-source data project; contact: openchristiandata@gmail.com)"
)
REQUEST_DELAY = 2.0

# PG markers
PG_START_RE = re.compile(r"\*\*\*\s*START OF", re.IGNORECASE)
PG_END_RE = re.compile(r"\*\*\*\s*END OF", re.IGNORECASE)

SOURCES = [
    {
        "slug": "charnock",
        "label": "Charnock -- Existence and Attributes of God",
        "type": "pg",
        "url": "http://www.gutenberg.org/cache/epub/53527/pg53527.txt",
        "raw_file": RAW_PG_DIR / "pg53527.txt",
    },
    {
        "slug": "gurnall",
        "label": "Gurnall -- Christian in Complete Armour",
        "type": "ia",
        "url": "https://archive.org/download/christianincom00gurn/christianincom00gurn_djvu.txt",
        "raw_file": RAW_IA_DIR / "gurnall_complete_armour.txt",
    },
    {
        "slug": "brooks",
        "label": "Brooks -- Precious Remedies",
        "type": "ia",
        "url": "https://archive.org/download/preciousremedies00broo/preciousremedies00broo_djvu.txt",
        "raw_file": RAW_IA_DIR / "brooks_precious_remedies.txt",
    },
    {
        "slug": "burroughs",
        "label": "Burroughs -- Rare Jewel of Christian Contentment",
        "type": "ia",
        "url": (
            "https://archive.org/download/"
            "JerimiahBurroughsTheRareJewelOfChristianContentment/"
            "Jerimiah%20Burroughs%20The%20Rare%20Jewel%20of%20Christian%20Contentment_djvu.txt"
        ),
        "raw_file": RAW_IA_DIR / "burroughs_rare_jewel.txt",
    },
    {
        "slug": "sibbes",
        "label": "Sibbes -- The Bruised Reed",
        "type": "ia",
        "url": "https://archive.org/download/bruisedreedands00sibbgoog/bruisedreedands00sibbgoog_djvu.txt",
        "raw_file": RAW_IA_DIR / "sibbes_bruised_reed.txt",
    },
]

# Heading candidates: ALL CAPS standalone lines, or lines starting with Chapter/Volume/DEVICE/REMEDY
HEADING_RE = re.compile(
    r"^\s*("
    r"VOLUME\s+[IVX\d]+"
    r"|Volume\s+[IVX\d]+"
    r"|CHAPTER\s+[IVX\d\w]+"
    r"|Chapter\s+[IVX\d\w\.]+"
    r"|DISCOURSE\s+[IVX\d]+"
    r"|Discourse\s+[IVX\d]+"
    r"|DEVICE\s+[IVX\d]+"
    r"|Device\s+[IVX\d\.]+"
    r"|REMEDY\s+[IVX\d]+"
    r"|Remedy\s+[IVX\d\.]+"
    r"|PART\s+[IVX\d]+"
    r"|Part\s+[IVX\d]+"
    r")\b",
    re.IGNORECASE,
)

# Bare ALL CAPS line (at least 3 words, not too long, not a URL)
ALL_CAPS_RE = re.compile(r"^[A-Z][A-Z\s\.,;:'\-]{10,80}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_RETRY_STATUSES = {429, 500, 502, 503}
_RETRY_DELAYS = [2.0, 4.0, 8.0]


def download_file(url: str, out_path: Path) -> None:
    """Download URL to out_path. Follows redirects. Retries on transient errors."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt, delay in enumerate([0.0] + _RETRY_DELAYS, start=1):
        if delay:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            out_path.write_bytes(data)
            print(f"  Downloaded: {len(data)//1024} KB -> {out_path.name}")
            return
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code not in _RETRY_STATUSES:
                raise
            print(f"  HTTP {exc.code} on attempt {attempt}/4 -- retrying")
        except urllib.error.URLError as exc:
            last_exc = exc
            print(f"  URLError: {exc.reason} -- retrying")
    raise last_exc


def strip_pg(text: str) -> list:
    lines = text.splitlines()
    start_idx = end_idx = None
    for i, l in enumerate(lines):
        if PG_START_RE.search(l) and start_idx is None:
            start_idx = i
        if PG_END_RE.search(l):
            end_idx = i
            break
    if start_idx is None or end_idx is None:
        raise ValueError("PG markers not found")
    return lines[start_idx + 1 : end_idx]


def strip_ia_header(lines: list) -> list:
    """Strip common IA/DjVu OCR header lines.

    IA djvu.txt files often start with blank lines then the actual text.
    There is no standard marker like PG's *** START OF ***.
    Strategy: skip leading blank lines plus any lines that look like
    scan/metadata headers (short, all-caps, or contain 'digitized by').
    """
    i = 0
    # Skip leading blank lines
    while i < len(lines) and not lines[i].strip():
        i += 1
    # Look for telltale IA header lines (usually first 5-10 non-blank lines)
    # Common patterns: "Digitized by", "Google", page numbers like "1\n"
    header_re = re.compile(
        r"(?i)(digitized\s+by|google|internet\s+archive|project\s+gutenberg"
        r"|^[0-9]+\s*$|transcribed\s+by|this\s+is\s+a\s+digital)"
    )
    end_header = i
    for j in range(i, min(i + 30, len(lines))):
        stripped = lines[j].strip()
        if stripped and header_re.search(stripped):
            end_header = j + 1
    return lines[end_header:]


def safe_print(line: str, max_len: int = 120) -> None:
    """Print line safely on Windows cp1252 console (PY-05: ASCII only)."""
    s = line[:max_len]
    safe = s.encode("ascii", errors="replace").decode("ascii")
    print(safe)


def census_file(source: dict) -> None:
    """Download (if needed), strip header, print census."""
    raw_path = source["raw_file"]
    print(f"\n{'='*60}")
    print(f"CENSUS: {source['label']}")
    print(f"{'='*60}")

    # Download if not cached
    if not raw_path.exists():
        print(f"  Downloading from {source['url'][:80]}...")
        download_file(source["url"], raw_path)
        time.sleep(REQUEST_DELAY)
    else:
        print(f"  Using cached: {raw_path.name} ({raw_path.stat().st_size // 1024} KB)")

    # Read and decode
    try:
        text = raw_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        print(f"  ERROR reading file: {exc}")
        return

    lines = text.splitlines()
    print(f"  Total lines: {len(lines)}")

    # Strip header
    if source["type"] == "pg":
        try:
            body = strip_pg(text)
            print(f"  PG body lines: {len(body)}")
        except ValueError as exc:
            print(f"  WARNING: {exc} -- using all lines as body")
            body = lines
    else:
        body = strip_ia_header(lines)
        print(f"  IA body lines (after header strip): {len(body)}")

    # First 30 non-blank lines
    print("\n--- First 30 non-blank body lines ---")
    shown = 0
    for i, l in enumerate(body):
        if l.strip():
            safe_print(f"  L{i:05d}: {l.rstrip()}")
            shown += 1
            if shown >= 30:
                break

    # All heading candidates
    print("\n--- Heading candidates (first 100) ---")
    heading_count = 0
    for i, l in enumerate(body):
        stripped = l.strip()
        if not stripped:
            continue
        is_heading = HEADING_RE.match(stripped) or (
            ALL_CAPS_RE.match(stripped) and len(stripped.split()) >= 2
        )
        if is_heading:
            safe_print(f"  L{i:05d}: {stripped}")
            heading_count += 1
            if heading_count >= 100:
                print("  [truncated at 100 headings]")
                break

    print(f"  Total heading candidates found: {heading_count}")

    # VOLUME markers specifically (for Charnock)
    print("\n--- VOLUME markers ---")
    vol_count = 0
    for i, l in enumerate(body):
        stripped = l.strip()
        if re.match(r"(?i)volume\s+[IVX\d]+", stripped):
            safe_print(f"  L{i:05d}: {stripped}")
            vol_count += 1
    if vol_count == 0:
        print("  None found")


def main() -> None:
    print("T6-1 Puritan Structural Census")
    print(f"Raw PG dir: {RAW_PG_DIR}")
    print(f"Raw IA dir: {RAW_IA_DIR}")

    for source in SOURCES:
        census_file(source)

    print("\n\nCensus complete.")


if __name__ == "__main__":
    main()
