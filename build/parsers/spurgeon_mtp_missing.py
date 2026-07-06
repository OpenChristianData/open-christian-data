"""spurgeon_mtp_missing.py
Supplementary loader for 3 Spurgeon MTP sermons absent from The Kingdom Collective.

These sermon numbers are genuine sermons that were not transcribed by Emmett O'Donnell
at SpurgeonGems and therefore never appeared in The Kingdom Collective's HTML collection:
  708 — The Blood Of Abel And The Blood Of Jesus (Gen 4:10)
  1698 — The Star And The Wise Men (Matt 2:1-2, 9-10)
  3032 — The Fashion Of This World (1 Cor 7:31)

Sources used:
  708, 3032 : Answers in Genesis (answersingenesis.org/education/spurgeon-sermons/)
  1698      : archive.spurgeon.org/sermons/

HTML structure notes:
  AiG (708, 3032):
    - Title: <h1 id="ipaNodeName">
    - Body: <div id="ipaNodeBody"> — parsed as text with double-newline splitting
    - Scripture section: first non-delivery block before "1. " numbered body paragraphs
    - Noise to skip: delivery line, citation parens, {curly-brace} cross-refs, footnotes

  archive.spurgeon.org (1698):
    - Title: <H1> (uppercase tag, only H1 on page)
    - Scripture: <BLOCKQUOTE> — citation appended after em-dash
    - Body: first <P> after blockquote, split on <BR> (get_text separator)
    - Noise to skip: footer text ("Collection administered by...")

Usage:
    py -3 build/parsers/spurgeon_mtp_missing.py --dry-run   # fetch + parse, print, no write
    py -3 build/parsers/spurgeon_mtp_missing.py             # fetch, parse, patch JSON
    py -3 build/parsers/spurgeon_mtp_missing.py --verify    # re-read JSON and verify entries

Required:
    pip install beautifulsoup4==4.14.3
"""

import argparse
import json
import re
import sys
import urllib.request  # standards: download only
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore -- checked in main()

from build.lib.paths import REPO_ROOT  # noqa: E402
MISSING_DIR = REPO_ROOT / "raw" / "spurgeon_sermons" / "missing"
OUTPUT_FILE = REPO_ROOT / "data" / "sermons" / "spurgeon-mtp.json"

COLLECTION_ID = "spurgeon-metropolitan-tabernacle-pulpit"
LOCATION_DEFAULT = "Metropolitan Tabernacle, London"

USER_AGENT = (
    "OpenChristianData/1.0 (research; open-source data project; "
    "contact: openchristiandata@gmail.com)"
)

# ---------------------------------------------------------------------------
# Source configs
# ---------------------------------------------------------------------------
# ref_osis for "Matthew 2:1-2, 9-10" is hardcoded — the multi-verse compound form
# is not handled by the standard text_to_osis function.

SOURCES = {
    708: {
        "url": (
            "https://answersingenesis.org/education/spurgeon-sermons/"
            "708-the-blood-of-abel-and-the-blood-of-jesus/"
        ),
        "format": "aig",
        "title": "The Blood Of Abel And The Blood Of Jesus",
        "ref_raw": "Genesis 4:10",
        "ref_osis": ["Gen.4.10"],
        "date_preached": "1866-09-02",
        "source_url": (
            "https://answersingenesis.org/education/spurgeon-sermons/"
            "708-the-blood-of-abel-and-the-blood-of-jesus/"
        ),
        "source_credit": "Answers in Genesis (answersingenesis.org)",
    },
    1698: {
        "url": "https://archive.spurgeon.org/sermons/1698.php",
        "format": "archive_spurgeon",
        "title": "The Star And The Wise Men",
        "ref_raw": "Matthew 2:1-2, 9-10",
        "ref_osis": ["Matt.2.1-Matt.2.2", "Matt.2.9", "Matt.2.10"],
        "date_preached": "1882-12-24",
        "source_url": "https://archive.spurgeon.org/sermons/1698.php",
        "source_credit": "archive.spurgeon.org",
    },
    3032: {
        "url": (
            "https://answersingenesis.org/education/spurgeon-sermons/"
            "3032-form-of-this-world/"
        ),
        "format": "aig",
        "title": "The Fashion Of This World",
        "ref_raw": "1 Corinthians 7:31",
        "ref_osis": ["1Cor.7.31"],
        "date_preached": "1869-08-12",
        "source_url": (
            "https://answersingenesis.org/education/spurgeon-sermons/"
            "3032-form-of-this-world/"
        ),
        "source_credit": "Answers in Genesis (answersingenesis.org)",
    },
}

# ---------------------------------------------------------------------------
# Fetch helper
# ---------------------------------------------------------------------------


def fetch_and_cache(sermon_n: int, url: str) -> bytes:
    """Download URL and cache to raw/spurgeon_sermons/missing/{n}.html. Returns bytes."""
    MISSING_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = MISSING_DIR / f"{sermon_n}.html"

    if cache_file.exists():
        print(f"  [{sermon_n}] Using cached HTML: {cache_file}")
        return cache_file.read_bytes()

    print(f"  [{sermon_n}] Fetching: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()

    cache_file.write_bytes(data)
    print(f"  [{sermon_n}] Cached {len(data):,} bytes -> {cache_file}")
    return data


# ---------------------------------------------------------------------------
# AiG parser (sermons 708 and 3032)
# ---------------------------------------------------------------------------

# Noise-block patterns for AiG pages. Applied to individual double-newline blocks.
_AIG_DELIVERY_RE = re.compile(r"^A Sermon (?:Delivered|Published)")
_AIG_CITATION_RE = re.compile(
    r"^\(?\s*[A-Z1-9][A-Za-z ]+\s+\d+:\d+",  # "( Genesis 4:10. )" or "(Hebrews 12:24)"
)
_AIG_CROSSREF_RE = re.compile(r"^\{")          # {See Spurgeon_Sermons...} or {1Co 7:31}
_AIG_NAV_RE = re.compile(r"^For other sermons")
_AIG_FOOTNOTE_RE = re.compile(r"^\([a-z]\)")   # footnote markers "(a)" and defs "(a) Text..."


def _is_aig_noise(block: str) -> bool:
    if _AIG_DELIVERY_RE.match(block):
        return True
    # Citation: short block that is a parenthesised reference
    if _AIG_CITATION_RE.match(block) and len(block) < 70:
        return True
    if _AIG_CROSSREF_RE.match(block):
        return True
    if _AIG_NAV_RE.match(block):
        return True
    if _AIG_FOOTNOTE_RE.match(block):
        return True
    return False


def parse_aig(html_bytes: bytes, source: dict) -> tuple:
    """
    Parse an Answers in Genesis Spurgeon sermon page.

    Strategy: extract raw text from #ipaNodeBody, split on double-newlines,
    filter noise, capture first real block as scripture quote, collect body
    from the first numbered-paragraph block ("1. ...") onward.

    Returns (scripture_quote_text, content_blocks).
    """
    try:
        html = html_bytes.decode("utf-8")
    except UnicodeDecodeError:
        html = html_bytes.decode("cp1252", errors="replace")

    soup = BeautifulSoup(html, "html.parser")
    body_div = soup.find(id="ipaNodeBody")
    if body_div is None:
        raise ValueError("Could not find #ipaNodeBody on AiG page")

    # Remove the outro/disclaimer section before extracting text
    outro = body_div.find(id="ipaNodeOutro")
    if outro:
        outro.decompose()

    raw = body_div.get_text(separator="\n")
    raw_blocks = [
        re.sub(r"\s+", " ", b).strip()
        for b in re.split(r"\n\s*\n", raw)
    ]

    scripture_quote = None
    content_blocks = []
    body_started = False
    skip_next = False  # True after a standalone footnote marker: "(a)" or "{c}"

    for block in raw_blocks:
        if not block:
            continue

        # Skip footnote definition that follows a standalone marker
        if skip_next:
            skip_next = False
            continue

        # Detect body start (two forms):
        #  "1." alone on a block (708 style: number and text in separate blocks)
        #  "1. Text..." combined (3032 style: number and text in same block)
        if re.match(r"^1\.?\s*$", block) or re.match(r"^1\.\s+", block):
            body_started = True
            if re.match(r"^1\.?\s*$", block):
                continue  # standalone "1." — skip, the text follows as next block

        if not body_started:
            # Pre-body: capture scripture quote from first non-noise block
            if not _is_aig_noise(block) and scripture_quote is None:
                scripture_quote = block
        else:
            # Body: skip noise and standalone paragraph-number blocks
            if _is_aig_noise(block):
                # Standalone footnote markers (like "{c}") trigger skip of next block
                if _AIG_CROSSREF_RE.match(block) or _AIG_FOOTNOTE_RE.match(block):
                    skip_next = True
                continue
            # Standalone section-number labels: "2.", "3, 4.", "6-9.", "37, 38." etc.
            if re.match(r"^[\d,\s\-]+\.?\s*$", block) and len(block) < 20:
                continue
            # Strip leading paragraph numbers "N. " to match Kingdom Collective style
            cleaned = re.sub(r"^\d+\.\s+", "", block)
            # Strip inline footnote references like "{c}" or "{a}"
            cleaned = re.sub(r"\s*\{[a-z]\}\s*", " ", cleaned).strip()
            if cleaned:
                content_blocks.append(cleaned)

    return scripture_quote, content_blocks


# ---------------------------------------------------------------------------
# archive.spurgeon.org parser (sermon 1698)
# ---------------------------------------------------------------------------

_ARCHIVE_FOOTER_RE = re.compile(r"Collection administered|WPEngine|help and support", re.I)


def parse_archive_spurgeon(html_bytes: bytes, source: dict) -> tuple:
    """
    Parse an archive.spurgeon.org sermon page.

    Structure: table-layout HTML, no CSS classes.
    - First <TABLE> is the navigation bar — ignored.
    - <H1> is the title (already in source config).
    - <BLOCKQUOTE> contains scripture text; citation is after em-dash at end.
    - First <P> after blockquote is the sermon body (uses <BR> for paragraph breaks).
    - Remaining <P> elements are a second sermon and footer text — skipped.

    Returns (scripture_quote_text, content_blocks).
    """
    try:
        html = html_bytes.decode("utf-8")
    except UnicodeDecodeError:
        html = html_bytes.decode("cp1252", errors="replace")

    soup = BeautifulSoup(html, "html.parser")

    # Extract scripture quote from blockquote (split off citation at end)
    scripture_quote = None
    bq = soup.find("blockquote")
    if bq:
        bq_text = bq.get_text(separator="\n")
        bq_text = re.sub(r"\s+", " ", bq_text).strip()
        # Citation follows em-dash: "...text.—Matthew 2:1-2, 9-10."
        em_pos = bq_text.rfind("\u2014")  # em dash
        if em_pos == -1:
            em_pos = bq_text.rfind("--")
        if em_pos > 0:
            scripture_quote = re.sub(r"\s+", " ", bq_text[:em_pos]).strip()
        else:
            scripture_quote = bq_text

    # Collect body: first <P> after blockquote is the sermon body
    elements = soup.find_all(["blockquote", "p"])
    bq_pos = next((i for i, e in enumerate(elements) if e.name == "blockquote"), None)
    if bq_pos is None:
        raise ValueError("No blockquote found on archive.spurgeon.org page")

    # Use only the first <P> after blockquote (subsequent <P> are a different sermon + footer)
    after_bq = [e for e in elements[bq_pos + 1:] if e.name == "p"]
    if not after_bq:
        raise ValueError("No <P> after blockquote on archive.spurgeon.org page")

    first_p = after_bq[0]
    raw = first_p.get_text(separator="\n")

    content_blocks = []
    for line in raw.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        # Skip footer text
        if _ARCHIVE_FOOTER_RE.search(line):
            continue
        # Skip very short lines (likely spacers or stray characters)
        if len(line) < 20:
            continue
        content_blocks.append(line)

    # Fix drop-capital artifact in first block: "EE, DEAR..." → "SEE, DEAR..."
    # The "S" in "SEE" was a large drop capital in the Victorian original and is
    # absent from the extracted text.
    if content_blocks and content_blocks[0].startswith("EE, "):
        content_blocks[0] = "S" + content_blocks[0]

    return scripture_quote, content_blocks


# ---------------------------------------------------------------------------
# Entry builder
# ---------------------------------------------------------------------------


def build_entry(sermon_n: int, source: dict, scripture_quote: str, content_blocks: list) -> dict:
    """Assemble one OCD sermon entry dict."""
    all_text = " ".join(content_blocks)
    word_count = len(all_text.split()) if all_text.strip() else 0

    return {
        "collection_id": COLLECTION_ID,
        "sermon_id": f"spurgeon-mtp.{sermon_n}",
        "series": None,
        "title": source["title"],
        "primary_reference": {
            "raw": source["ref_raw"],
            "osis": source["ref_osis"],
        },
        "primary_reference_text": scripture_quote,
        "content_blocks": content_blocks,
        "date_preached": source["date_preached"],
        "location": LOCATION_DEFAULT,
        "word_count": word_count,
        "provenance": {
            "source_url": source["source_url"],
            "source_credit": source["source_credit"],
            "notes": (
                "Not present in The Kingdom Collective source used for the main collection; "
                "fetched from supplementary source by spurgeon_mtp_missing.py"
            ),
        },
    }


# ---------------------------------------------------------------------------
# JSON patch helper
# ---------------------------------------------------------------------------


def patch_json(new_entries: list) -> None:
    """Upsert new_entries into spurgeon-mtp.json at the correct sorted positions.

    If an entry's sermon_id already exists, it is replaced (upsert). This allows
    re-running the script to update existing entries after source fixes.
    """
    with open(OUTPUT_FILE, encoding="utf-8") as f:
        root = json.load(f)

    data = root["data"]
    new_by_id = {e["sermon_id"]: e for e in new_entries}

    updated = 0
    added = 0
    for i, existing in enumerate(data):
        if existing["sermon_id"] in new_by_id:
            data[i] = new_by_id.pop(existing["sermon_id"])
            updated += 1

    for entry in new_by_id.values():
        data.append(entry)
        added += 1

    # Sort by sermon number extracted from sermon_id "spurgeon-mtp.N"
    def sermon_num(e):
        try:
            return int(e["sermon_id"].split(".")[-1])
        except (ValueError, IndexError):
            return 0

    data.sort(key=sermon_num)
    root["data"] = data

    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(root, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(
        f"  Patched {OUTPUT_FILE.name}: "
        f"{added} added, {updated} updated, total now {len(data)}"
    )


def verify_json(sermon_numbers: list) -> bool:
    """Re-read OUTPUT_FILE and confirm each sermon_id is present and well-formed.

    Checks: entry exists, content_blocks non-empty, word_count > 1000, provenance present.
    Returns True if all checks pass, False otherwise.
    """
    with open(OUTPUT_FILE, encoding="utf-8") as f:
        root = json.load(f)

    data_by_id = {e["sermon_id"]: e for e in root["data"]}
    all_ok = True

    for n in sermon_numbers:
        sid = f"spurgeon-mtp.{n}"
        entry = data_by_id.get(sid)
        if entry is None:
            print(f"  FAIL [{n}] -- entry not found in data")
            all_ok = False
            continue

        issues = []
        if not entry.get("content_blocks"):
            issues.append("content_blocks empty")
        if entry.get("word_count", 0) < 1000:
            issues.append(f"word_count suspiciously low ({entry.get('word_count')})")
        if not entry.get("provenance"):
            issues.append("provenance missing")
        if not entry.get("primary_reference"):
            issues.append("primary_reference missing")
        cb = entry.get("content_blocks", [])
        if cb and len(cb[0]) < 30:
            issues.append(f"first block suspiciously short ({cb[0]!r})")

        if issues:
            print(f"  FAIL [{n}] {entry['title']}: {'; '.join(issues)}")
            all_ok = False
        else:
            print(
                f"  OK   [{n}] {entry['title']} -- "
                f"{len(cb)} blocks, {entry['word_count']:,} words"
            )

    return all_ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    if BeautifulSoup is None:
        print("ERROR: beautifulsoup4 is required. Run: pip install beautifulsoup4==4.14.3")
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Fetch and patch 3 missing Spurgeon MTP sermons into OCD data."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and parse, but print entries instead of patching the JSON file.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Re-read the JSON file and verify the 3 entries are present and well-formed.",
    )
    args = parser.parse_args()

    print("spurgeon_mtp_missing.py -- supplementary loader for sermons 708, 1698, 3032")
    print(f"  Output: {OUTPUT_FILE}")
    print(f"  Raw cache: {MISSING_DIR}")
    if args.dry_run:
        print("  DRY RUN: no files will be modified")
    print()

    # --verify: read-only check, no fetch/parse needed
    if args.verify:
        print("Verifying entries in spurgeon-mtp.json ...")
        ok = verify_json(list(SOURCES.keys()))
        sys.exit(0 if ok else 1)

    failures = []
    entries = []

    for sermon_n, source in SOURCES.items():
        cache_path = MISSING_DIR / f"{sermon_n}.html"
        print(f"Sermon {sermon_n}: {source['title']}")
        try:
            html_bytes = fetch_and_cache(sermon_n, source["url"])
        except Exception as exc:
            print(
                f"  ERROR fetching {source['url']}: {exc}\n"
                f"  Recovery: check connectivity, or delete {cache_path} to force re-fetch"
            )
            failures.append(sermon_n)
            continue

        try:
            if source["format"] == "aig":
                scripture_quote, content_blocks = parse_aig(html_bytes, source)
            elif source["format"] == "archive_spurgeon":
                scripture_quote, content_blocks = parse_archive_spurgeon(html_bytes, source)
            else:
                raise ValueError(f"Unknown format: {source['format']!r}")
        except Exception as exc:
            print(
                f"  ERROR parsing sermon {sermon_n}: {exc}\n"
                f"  HTML cached at {cache_path} -- inspect for unusual page structure"
            )
            failures.append(sermon_n)
            continue

        if scripture_quote is None:
            print(f"  WARNING: scripture_quote is None for sermon {sermon_n}")
        if not content_blocks:
            print(f"  WARNING: no content_blocks parsed for sermon {sermon_n}")
        else:
            print(
                f"  Parsed {len(content_blocks)} blocks, "
                f"{sum(len(b.split()) for b in content_blocks):,} words"
            )

        entry = build_entry(sermon_n, source, scripture_quote, content_blocks)
        entries.append(entry)

        if args.dry_run:
            print(f"  Scripture quote: {(scripture_quote or '')[:120]!r}")
            print(f"  First block:     {(content_blocks[0] if content_blocks else '')[:120]!r}")
            print(f"  Last block:      {(content_blocks[-1] if content_blocks else '')[:120]!r}")
        print()

    if failures:
        print(f"ERROR: {len(failures)} sermon(s) failed to fetch/parse: {failures}")
        sys.exit(1)

    if args.dry_run:
        print("--- Sample entry (sermon 708, content_blocks truncated): ---")
        sample = dict(entries[0])
        sample["content_blocks"] = sample["content_blocks"][:3] + ["..."]
        print(json.dumps(sample, ensure_ascii=False, indent=2))
        return

    print("Patching spurgeon-mtp.json ...")
    patch_json(entries)

    print()
    print("Verifying ...")
    ok = verify_json(list(SOURCES.keys()))
    if not ok:
        print("WARNING: verification failed -- check entries above")
        sys.exit(1)
    print("Done.")


if __name__ == "__main__":
    main()
