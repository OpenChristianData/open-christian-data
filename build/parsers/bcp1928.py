"""bcp1928.py
Parser for Book of Common Prayer (1928, USA) Collects.

Downloads 100 HTML pages from episcopalnet.org/1928bcp/propers/ (with a
2-second courtesy delay between requests) to raw/bcp-1928/, then extracts
the Collect for each Sunday, Feast Day, and special occasion into a single
OCD prayer JSON file.

Source: https://www.episcopalnet.org/1928bcp/
License: Public domain -- 1928 BCP text (US Episcopal Church). Text published
1928; all authors long deceased. No robots.txt on source site.

Pre-coding HTML inspection (2026-03-31, 5 pages sampled):

Variant 1 -- Standard (used on ~99/100 pages):
  - Occasion heading: <center><b><i><font color="#7f0000|#ff0000">TITLE.</font></i></b>...</center>
    The font color varies by season (#7f0000 dark red = seasonal propers,
    #ff0000 red = holy days). Both are handled by [^>]* in the regex.
  - Collect marker: "The Collect." appears as plain text inside a <center> block
    (after an optional YouTube iframe and tracking scripts).
  - Collect text: bare <p> immediately following that </center>, optionally
    prefixed by <a name="anchor..."> (e.g. ashwednesday.html).
  - Rubric: optional <h6> with rubric note follows the collect paragraph.
  - Epistle boundary: <center> containing "The Epistle." or "For the Epistle."

Variant 2 -- Good Friday (1 page, 3 collects):
  - Collect marker: "The Collects." (plural) inside <p><font color="#000000">
    inside <center> (no YouTube iframe on this page).
  - Collect text: single <p><font color="#000000">...</font></p> containing
    all three collects separated by "Amen.<br><br>" sequences.
  - Each collect ends with "Amen." followed by <br> or end-of-block.

Additional observations:
  - All pages embed <script>...</script> tracking blocks inside <center> after
    the collect marker. These must be stripped before text extraction.
  - Some pages include editorial "QUESTIONS...RESOLVE" blocks in <strong><em>
    in the Epistle/Gospel text. These never appear in the collect paragraph.
  - No page has a collect inside the epistle or gospel text blocks.

100 source pages:
  advent1.html through nextbeforeadvent.html (seasonal Sundays)
  standrew.html through thanksgiving.html (saints days and holy days)
  marriage.html, ataburial.html (sacramental occasions)
  (full list in SOURCE_PAGES constant below)

Usage:
    py -3 build/parsers/bcp1928.py --dry-run        (parse first 3 pages, no write)
    py -3 build/parsers/bcp1928.py                   (full run)
    py -3 build/parsers/bcp1928.py --force-download  (re-download cached files)
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "raw" / "bcp-1928"
OUTPUT_DIR = REPO_ROOT / "data" / "prayers" / "bcp-1928"
CONFIG_PATH = REPO_ROOT / "sources" / "prayers" / "bcp-1928-collects" / "config.json"

OUTPUT_FILE = OUTPUT_DIR / "collects.json"

BASE_URL = "https://www.episcopalnet.org/1928bcp/propers/"

# All 100 propers pages from the episcopalnet.org 1928 BCP index (inspected 2026-03-31).
SOURCE_PAGES = [
    "advent1.html",
    "advent2.html",
    "advent3.html",
    "advent4.html",
    "christmas.html",
    "stephen.html",
    "stjohn.html",
    "holyinnocents.html",
    "christmas1.html",
    "circumcision.html",
    "christmas2.html",
    "epiphany.html",
    "epiphany1.html",
    "epiphany2.html",
    "epiphany3.html",
    "epiphany4.html",
    "epiphany5.html",
    "epiphany6.html",
    "septuagesima.html",
    "sexagesima.html",
    "quinquagesima.html",
    "ashwednesday.html",
    "lent1.html",
    "lent2.html",
    "lent3.html",
    "lent4.html",
    "passionsunday.html",
    "palmsunday.html",
    "mondaybfreaster.html",
    "tuesdaybfreaster.html",
    "wednesdaybfreaster.html",
    "maundythursday.html",
    "goodfriday.html",
    "eastereven.html",
    "Easter.html",
    "Eastermonday.html",
    "Eastertuesday.html",
    "Easter1.html",
    "Easter2.html",
    "Easter3.html",
    "Easter4.html",
    "Easter5rogation.html",
    "Ascensionday.html",
    "Ascensionsundayafter.html",
    "whitsunday.html",
    "whitsunmonday.html",
    "whitsuntuesday.html",
    "Trinity.html",
    "Trinity1.html",
    "Trinity2.html",
    "Trinity3.html",
    "Trinity4.html",
    "Trinity5.html",
    "Trinity6.html",
    "Trinity7.html",
    "Trinity8.html",
    "Trinity9.html",
    "Trinity10.html",
    "Trinity11.html",
    "Trinity12.html",
    "Trinity13.html",
    "Trinity14.html",
    "Trinity15.html",
    "Trinity16.html",
    "Trinity17.html",
    "Trinity18.html",
    "Trinity19.html",
    "Trinity20.html",
    "Trinity21.html",
    "Trinity22.html",
    "Trinity23.html",
    "Trinity24.html",
    "nextbeforeadvent.html",
    "standrew.html",
    "stthomas.html",
    "conversion.html",
    "purification.html",
    "stmatthias.html",
    "annunciation.html",
    "stmark.html",
    "stphilipstjames.html",
    "stbarnabas.html",
    "stjohnbaptist.html",
    "stpeter.html",
    "stjames.html",
    "transfiguration.html",
    "stbartholomew.html",
    "stmatthew.html",
    "stmichaelangels.html",
    "stluke.html",
    "stsimonjude.html",
    "allsaints.html",
    "asaints.html",
    "dedication.html",
    "emberdays.html",
    "rogationdays.html",
    "independenceday.html",
    "thanksgivingday.html",
    "marriage.html",
    "ataburial.html",
]

USER_AGENT = (
    "OpenChristianData/1.0 "
    "(research; open-source data project; contact: openchristiandata@gmail.com)"
)
CRAWL_DELAY_SECONDS = 2

COLLECTION_ID = "bcp-1928-collects"
SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_page(filename: str, force: bool = False) -> None:
    """Download one HTML page from episcopalnet.org to raw/bcp-1928/."""
    dest = RAW_DIR / filename
    if dest.exists() and not force:
        print(f"  Cached: {filename}")
        return
    url = BASE_URL + filename
    print(f"  Fetching {url} ...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        print(f"  Saved {len(data):,} bytes -> {dest.name}")
    except Exception as exc:
        raise RuntimeError(
            f"Download failed for {filename}: {exc}. "
            "Check network access or retry with --force-download."
        ) from exc


def download_all_pages(force: bool = False) -> None:
    """Download all source pages with crawl-delay between requests."""
    print(f"Downloading {len(SOURCE_PAGES)} HTML pages ...")
    for i, filename in enumerate(SOURCE_PAGES):
        if i > 0:
            already_cached = (RAW_DIR / filename).exists() and not force
            if not already_cached:
                time.sleep(CRAWL_DELAY_SECONDS)
        download_page(filename, force=force)
    print()


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------

def strip_scripts(html: str) -> str:
    """Remove <script>, <noscript>, and HTML comment blocks from page text.

    Some pages contain nested <noscript> blocks (tracking code wraps another
    noscript fallback). Non-greedy regex only removes the innermost match in
    one pass, leaving an orphaned </noscript> closing tag. We therefore run
    the noscript strip twice and also clean up any remaining orphaned tags.
    """
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    # Two passes to handle nested noscript blocks
    html = re.sub(r"<noscript[^>]*>.*?</noscript>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<noscript[^>]*>.*?</noscript>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.DOTALL)
    # Clean up any orphaned closing tags that survived nested stripping
    html = re.sub(r"</(?:noscript|script)>", " ", html, flags=re.IGNORECASE)
    return html


def strip_tags(html: str) -> str:
    """Remove all HTML tags from a string."""
    return re.sub(r"<[^>]+>", " ", html)


def normalize_ws(text: str) -> str:
    """Collapse internal whitespace, decode &nbsp;, and strip edges."""
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def decode_html_entities(text: str) -> str:
    """Decode common HTML character entities."""
    entities = {
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&#39;": "'",
        "&apos;": "'",
        "&#8216;": "\u2018",
        "&#8217;": "\u2019",
        "&#8220;": "\u201c",
        "&#8221;": "\u201d",
        "&#8212;": "\u2014",
        "&#8211;": "\u2013",
        "&#167;": "\u00a7",
    }
    for entity, char in entities.items():
        text = text.replace(entity, char)
    return text


def slugify(text: str) -> str:
    """
    Convert a mixed-case filename stem to a URL-safe kebab-case slug.

    Examples:
      advent1         -> advent1
      christmas       -> christmas
      Eastermonday    -> eastermonday
      Trinity1        -> trinity1
      goodfriday      -> goodfriday
      stphilipstjames -> stphilipstjames
    """
    # Insert hyphen between a lowercase letter (or digit) and an uppercase letter
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", text)
    # Insert hyphen between consecutive uppercase runs followed by lowercase
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", text)
    # Lowercase everything
    text = text.lower()
    # Replace non-alphanumeric runs with a single hyphen
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def make_incipit(text: str, word_count: int = 10) -> str:
    """Return the first N words followed by '...'."""
    words = text.split()
    if len(words) <= word_count:
        return text
    return " ".join(words[:word_count]) + "..."


def word_count(text: str) -> int:
    """Count whitespace-delimited words."""
    return len(text.split()) if text.strip() else 0


# ---------------------------------------------------------------------------
# Title extraction
# ---------------------------------------------------------------------------

def extract_title(html: str) -> str:
    """
    Extract the occasion title from the page.

    The title appears in a <b> block immediately after the <h2> season
    heading and before the 'The Collect.' marker. Observed variants:

    1. Standard:  <b><i><font color="#7f0000|#ff0000">TITLE.</font></i></b>
    2. Uppercase: <B><I>TITLE. <FONT COLOR="#7f0000"><BR />[date]</FONT></I></B>
    3. em+b:      <em><b><font color="#7f0000">TITLE.</font></b></em>
    4. br inside: <b><i><font color="#7f0000"><br />TITLE.</font></i></b>

    Strategy: find the first <b>...</b> block between </h2> and 'The Collect.',
    strip all HTML tags from its content, remove [bracketed] date annotations,
    and normalize whitespace.
    """
    # Find </h2> to skip the season heading
    h2_end = re.search(r"</h2\s*>", html, re.IGNORECASE)
    if not h2_end:
        return ""

    # Find 'The Collect' marker as upper bound. If absent (e.g. eastereven),
    # use a fixed 600-char window — the title heading is always within
    # a few hundred chars of </h2>.
    collect_m = re.search(r"The\s+Collect", html[h2_end.end():], re.IGNORECASE)
    if collect_m:
        region_end = h2_end.end() + collect_m.start()
    else:
        region_end = h2_end.end() + 600

    search_region = html[h2_end.end() : region_end]

    # Find the first <b>, <strong>, or <em> block in this region, whichever
    # appears first.
    # Observed variants:
    # - <b><i><font>TITLE</font></i></b>  (most pages)
    # - <strong><em>TITLE</em></strong>   (stbarnabas, stpeter)
    # - <em>TITLE</em>                   (stmatthias — bare em, no b/strong)
    candidates = []
    for pattern in [
        r"<b[^>]*>(.*?)</b\s*>",
        r"<strong[^>]*>(.*?)</strong\s*>",
        r"<em[^>]*>(.*?)</em\s*>",
    ]:
        m = re.search(pattern, search_region, re.DOTALL | re.IGNORECASE)
        if m:
            candidates.append(m)

    if not candidates:
        return ""

    first_match = min(candidates, key=lambda m: m.start())
    title_html = first_match.group(1)

    # Strip all HTML tags (including <br />)
    title_text = re.sub(r"<[^>]+>", " ", title_html)
    # Decode entities
    title_text = title_text.replace("&nbsp;", " ").replace("\xa0", " ")
    # Remove [bracketed] date annotations like [November 30.]
    title_text = re.sub(r"\[[^\]]*\]", "", title_text)
    # Remove stray punctuation artifacts (e.g. "[)" on standrew)
    title_text = re.sub(r"[\[\]()]+", " ", title_text)
    return normalize_ws(title_text).rstrip(".")


# ---------------------------------------------------------------------------
# Collect extraction
# ---------------------------------------------------------------------------

def extract_collect_html_block(html: str) -> str:
    """
    Locate and return the raw HTML containing just the collect text(s).

    Strategy:
      1. Find "The Collect[s]." in a <center> block (both singular and plural).
      2. After that </center>, find the first non-empty <p>...</p> tag.
      3. That <p> is the collect (or all three collects for Good Friday).
      4. Strip HTML tags and return the text.

    Returns empty string if no collect marker is found.
    """
    # Find the collect marker inside a center block.
    # Matches: The Collect. OR The Collects. (with optional whitespace)
    # Some pages (eastereven) have the collect text directly after the title
    # heading with no "The Collect." label. In that case we fall back to
    # scanning for the first paragraph ending with "Amen." after </h2>.
    marker_match = re.search(
        r"The\s+Collects?\s*\.",
        html,
        re.IGNORECASE,
    )
    if not marker_match:
        # Fallback: look for first paragraph ending with "Amen." after </h2>
        h2_end = re.search(r"</h2\s*>", html, re.IGNORECASE)
        if not h2_end:
            return ""
        for p_match in re.finditer(
            r"<p[^>]*>((?:(?!</p>).)+)</p>",
            html[h2_end.end():],
            re.DOTALL | re.IGNORECASE,
        ):
            raw_content = p_match.group(1)
            plain = re.sub(r"<[^>]+>", "", raw_content)
            plain = plain.replace("&nbsp;", " ").replace("\xa0", " ").strip()
            if plain and "Amen." in plain and word_count(plain) >= 10:
                return raw_content
        return ""

    # Find the end of the enclosing block after the marker. The collect marker
    # is usually inside <center>...</center>, but some pages use
    # <p align="center">...<br>The Collect.</p>. We search for the FIRST
    # occurrence of either </center> or </p> after the marker.
    close_match = re.search(r"</(?:center|p)\s*>", html[marker_match.end():], re.IGNORECASE)
    if not close_match:
        return ""
    search_start = marker_match.end() + close_match.end()

    # Find the first non-whitespace-only <p>...</p> after the marker's </center>.
    # Skip empty paragraphs (<p></p>) and whitespace-only ones (<p>&nbsp;</p>).
    # Some pages (e.g. Trinity12) have a <p>&nbsp;</p> spacer before the
    # collect text, which must be skipped or the result is empty.
    for p_match in re.finditer(
        r"<p[^>]*>((?:(?!</p>).)+)</p>",
        html[search_start:],
        re.DOTALL | re.IGNORECASE,
    ):
        raw_content = p_match.group(1)
        # Check if the paragraph has any real text after stripping tags/whitespace
        plain = re.sub(r"<[^>]+>", "", raw_content)
        plain = plain.replace("&nbsp;", " ").replace("\xa0", " ").strip()
        if plain:
            return raw_content

    return ""


def clean_collect_text(html_fragment: str) -> str:
    """
    Strip HTML tags from a collect fragment and return clean prose text.

    Handles:
    - <a name="anchor..."> prefixes (anchors before the first word)
    - <font color="..."> wrappers
    - <br> within multi-collect blocks (Good Friday)
    - Decoded HTML entities
    """
    # Remove anchor tags (keep their text, but they're usually empty)
    cleaned = re.sub(r"<a\s[^>]*>\s*</a>", "", html_fragment, flags=re.IGNORECASE)
    # Strip remaining tags
    cleaned = strip_tags(cleaned)
    cleaned = decode_html_entities(cleaned)
    return normalize_ws(cleaned)


def split_multiple_collects(raw_html: str) -> list:
    """
    Split a multi-collect HTML block (Good Friday) into individual collect texts.

    The three Good Friday collects are in one <p><font>...</font></p> block
    separated by "Amen.<br>" sequences. We split on that boundary.

    Returns a list of cleaned text strings (one per collect).
    """
    # Replace <br> tags with newlines to ease splitting
    text = re.sub(r"<br\s*/?>", "\n", raw_html, flags=re.IGNORECASE)
    # Strip remaining tags
    text = strip_tags(text)
    text = decode_html_entities(text)
    # Split on "Amen." followed by whitespace/newlines before the next collect
    parts = re.split(r"Amen\.\s*\n+\s*(?=[A-Z])", text)
    results = []
    for part in parts:
        cleaned = normalize_ws(part)
        # Ensure "Amen." is present at the end of each collect
        if cleaned and not cleaned.endswith("Amen."):
            cleaned = cleaned.rstrip(".") + "."
            if "Amen" not in cleaned:
                cleaned += " Amen."
        if cleaned and word_count(cleaned) >= 10:
            results.append(cleaned)
    return results


def is_multi_collect(html: str) -> bool:
    """Return True if this page has 'The Collects.' (plural marker)."""
    return bool(re.search(r"The\s+Collects\s*\.", html, re.IGNORECASE))


# ---------------------------------------------------------------------------
# Prayer record builder
# ---------------------------------------------------------------------------

def build_prayer_record(
    base_id: str,
    title: str,
    text: str,
    suffix: str = "",
) -> dict:
    """Build an OCD prayer schema record from parsed collect data."""
    prayer_id = base_id + suffix
    wc = word_count(text)
    return {
        "collection_id": COLLECTION_ID,
        "prayer_id": prayer_id,
        "title": title,
        "incipit": make_incipit(text),
        "author": None,
        "year": None,
        "occasion": None,
        "content_blocks": [text],
        "scripture_references": [],
        "context": {
            "work": "Book of Common Prayer (1928)",
            "location": "Collects, Epistles, and Gospels",
        },
        "word_count": wc,
    }


# ---------------------------------------------------------------------------
# Extract collects from one page
# ---------------------------------------------------------------------------

def extract_collects_from_html(html_bytes: bytes, filename: str) -> tuple:
    """
    Parse one HTML page and return (list_of_records, error_count).

    Each record dict is ready for build_prayer_record.
    """
    records = []
    errors = 0

    # Decode: try UTF-8 first, fall back to latin-1
    try:
        html = html_bytes.decode("utf-8")
    except UnicodeDecodeError:
        html = html_bytes.decode("latin-1", errors="replace")

    # Strip scripts and comments before any other processing
    html = strip_scripts(html)

    # --- Title ---
    title = extract_title(html)
    if not title:
        # Fallback: use the HTML <title> tag, strip " Propers (1928 BCP)" suffix.
        # Some pages (lent2, Trinity22) have empty/link-only heading blocks.
        page_title_m = re.search(r"<title[^>]*>(.*?)</title>", html_bytes.decode("latin-1", errors="replace"), re.IGNORECASE | re.DOTALL)
        if page_title_m:
            raw_title = page_title_m.group(1).strip()
            # Strip common suffix patterns
            raw_title = re.sub(r"\s*Propers?\s*\(1928\s*BCP\)\s*", "", raw_title, flags=re.IGNORECASE)
            raw_title = re.sub(r"\s*\(1928\s*BCP\)\s*", "", raw_title, flags=re.IGNORECASE)
            title = normalize_ws(raw_title)
        if not title:
            print(f"    WARNING: No title found in {filename} -- skipping")
            return [], 1
        print(f"    INFO: Using <title> tag fallback for {filename}: {repr(title)}")

    # --- Base prayer_id from filename stem ---
    stem = Path(filename).stem
    base_id = slugify(stem)

    # --- Check for plural collect marker (Good Friday variant) ---
    multi = is_multi_collect(html)

    # --- Extract collect HTML block ---
    collect_block = extract_collect_html_block(html)
    if not collect_block:
        # Some pages (Trinity21-24, asaints, ataburial, marriage, etc.) do not
        # include a collect in the HTML. This is not an error — not every page
        # in the propers index has all three elements.
        # Additionally, some pages with a fallback title but no collect (e.g.
        # Trinity22) should be silently skipped — no error, no record.
        print(f"    INFO: No collect found in {filename} -- page may not have one")
        return [], 0

    try:
        if multi:
            # Good Friday: split three collects and suffix IDs with -2, -3
            texts = split_multiple_collects(collect_block)
            if not texts:
                print(f"    WARNING: Multi-collect split produced no results in {filename}")
                return [], 1
            suffixes = ["", "-2", "-3", "-4", "-5"]  # enough for any future additions
            for i, text in enumerate(texts):
                suffix = suffixes[i]
                records.append(build_prayer_record(base_id, title, text, suffix))
        else:
            # Standard: single collect
            text = clean_collect_text(collect_block)
            if not text or word_count(text) < 10:
                print(f"    WARNING: Collect text too short in {filename}: {repr(text[:60])}")
                return [], 1
            records.append(build_prayer_record(base_id, title, text))

    except Exception as exc:
        print(f"    ERROR parsing collect in {filename}: {exc}")
        return [], 1

    return records, errors


# ---------------------------------------------------------------------------
# Content plausibility check
# ---------------------------------------------------------------------------

# First words that identify Epistle or Gospel text, not collect text.
# If any record begins with these, the boundary regex fetched the wrong block.
_WRONG_BLOCK_OPENERS = {
    # Good Friday epistle
    "THE LAW",
    # Good Friday gospel
    "PILATE THEREFORE",
    # Advent 1 epistle
    "OWE NO",
    # Common gospel opener
    "AT THAT TIME",
    "IN THOSE DAYS",
    # Rubric-style openers (not collect text)
    "FOR THE EPISTLE",
    "THE EPISTLE",
    "THE GOSPEL",
}


def spot_check_content(records: list) -> int:
    """
    Check that no record's text begins with known Epistle/Gospel openers.

    Returns the number of suspect records found (0 = all clear).
    Any non-zero result means the boundary regex fetched the wrong HTML block
    for those pages -- investigate before shipping.
    """
    suspect = 0
    for r in records:
        text = r.get("content_blocks", [""])[0]
        # Normalise: uppercase, first 4 words
        first_words = " ".join(text.upper().split()[:4])
        for opener in _WRONG_BLOCK_OPENERS:
            if first_words.startswith(opener):
                print(
                    f"  WARNING: '{r['prayer_id']}' may be Epistle/Gospel text "
                    f"(starts: {repr(text[:60])})"
                )
                suspect += 1
                break
    return suspect


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------

def report_quality(records: list) -> None:
    """Print quality statistics for the parsed collect records."""
    total = len(records)
    if total == 0:
        print("  WARNING: No records produced")
        return

    word_counts = [r["word_count"] for r in records]
    sorted_wc = sorted(word_counts)
    short = sum(1 for wc in word_counts if wc < 20)
    no_incipit = sum(1 for r in records if not r["incipit"])
    no_title = sum(1 for r in records if not r["title"])

    # Detect duplicate prayer_ids
    seen_ids: dict = {}
    for r in records:
        pid = r["prayer_id"]
        seen_ids[pid] = seen_ids.get(pid, 0) + 1
    duplicates = {pid: cnt for pid, cnt in seen_ids.items() if cnt > 1}

    # BCP 1928 collects are roughly the same length as 1662 (~50-80 words).
    # Anything over 150 words suggests the boundary regex failed.
    WORD_COUNT_ALARM = 150
    long_records = [r for r in records if r["word_count"] > WORD_COUNT_ALARM]

    print(f"  Record count: {total}")
    print(
        f"  Word count:   min={min(word_counts)} "
        f"median={sorted_wc[total // 2]} "
        f"max={max(word_counts)}"
    )
    if long_records:
        print(
            f"  WARNING: {len(long_records)}/{total} records exceed {WORD_COUNT_ALARM} words "
            "(boundary regex may have failed -- check these):"
        )
        for r in sorted(long_records, key=lambda x: x["word_count"], reverse=True):
            print(f"    {r['prayer_id']}: {r['word_count']} words")
    if short:
        print(f"  WARNING: {short}/{total} records under 20 words (suspiciously short)")
    if no_incipit:
        print(f"  WARNING: {no_incipit}/{total} records missing incipit")
    if no_title:
        print(f"  WARNING: {no_title}/{total} records missing title")
    if duplicates:
        for pid, cnt in sorted(duplicates.items()):
            print(f"  WARNING: Duplicate prayer_id '{pid}' appears {cnt} times")


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------

def build_meta(config: dict, source_hash: str, processing_date: str) -> dict:
    """Build the OCD metadata envelope from source config."""
    return {
        "id": config["resource_id"],
        "title": config["title"],
        "author": config.get("author"),
        "author_birth_year": config.get("author_birth_year"),
        "author_death_year": config.get("author_death_year"),
        "contributors": config.get("contributors", []),
        "original_publication_year": config.get("original_publication_year"),
        "language": config["language"],
        "original_language": config.get("original_language"),
        "tradition": config["tradition"],
        "tradition_notes": config.get("tradition_notes"),
        "era": config.get("era"),
        "audience": config.get("audience"),
        "license": config["license"],
        "schema_type": "prayer",
        "schema_version": SCHEMA_VERSION,
        "completeness": "partial",
        "provenance": {
            "source_url": config["source_url"],
            "source_format": config["source_format"],
            "source_edition": config["source_edition"],
            "download_date": processing_date,
            "source_hash": f"sha256:{source_hash}",
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/bcp1928.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": config.get("notes"),
        },
    }


# ---------------------------------------------------------------------------
# Combined hash helper
# ---------------------------------------------------------------------------

def compute_combined_hash(filenames: list) -> str:
    """SHA-256 of concatenated raw bytes of all source files (in list order)."""
    hasher = hashlib.sha256()
    for filename in filenames:
        path = RAW_DIR / filename
        if path.exists():
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Main parse loop
# ---------------------------------------------------------------------------

def parse_all_pages(dry_run: bool = False) -> tuple:
    """
    Parse all source pages and return (records, total_errors).
    If dry_run=True, parse only the first 3 pages.
    """
    all_records = []
    total_errors = 0

    pages_to_process = SOURCE_PAGES[:3] if dry_run else SOURCE_PAGES

    for filename in pages_to_process:
        path = RAW_DIR / filename
        if not path.exists():
            print(f"  ERROR: Raw file not found: {path}")
            print("  Run without --dry-run to download first.")
            total_errors += 1
            continue

        print(f"  Parsing {filename} ...")
        html_bytes = path.read_bytes()
        items, page_errors = extract_collects_from_html(html_bytes, filename)
        total_errors += page_errors

        if items:
            print(f"    {len(items)} collect(s) extracted")
        all_records.extend(items)

    return all_records, total_errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    arg_parser = argparse.ArgumentParser(
        description="Parse BCP 1928 Collects into OCD prayer schema"
    )
    arg_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse first 3 pages only, print samples, do not write output",
    )
    arg_parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download source HTML even if already cached",
    )
    args = arg_parser.parse_args()

    start_time = time.time()

    # Load source config
    if not CONFIG_PATH.exists():
        print(f"ERROR: Config not found: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        config = json.load(fh)

    print(f"Source:  {config['title']}")
    print(f"Output:  {OUTPUT_FILE}")
    if args.dry_run:
        print("Mode:    dry-run (first 3 pages only, no write)")
    print()

    # Download
    if not args.dry_run or args.force_download:
        download_all_pages(force=args.force_download)
    else:
        # Dry-run: download only the first 3 pages if missing
        any_missing = False
        for filename in SOURCE_PAGES[:3]:
            if not (RAW_DIR / filename).exists():
                any_missing = True
                print(f"Dry-run: downloading {filename} (not cached) ...")
                download_page(filename, force=False)
                time.sleep(CRAWL_DELAY_SECONDS)
        if any_missing:
            print()
        # If after attempting downloads the first page still doesn't exist, abort
        if not (RAW_DIR / SOURCE_PAGES[0]).exists():
            print("Dry-run: download failed. Check network access.")
            sys.exit(1)

    # Parse
    print("Parsing ...")
    records, total_errors = parse_all_pages(dry_run=args.dry_run)
    print()

    # Quality report
    print("Quality report:")
    report_quality(records)
    print()

    if args.dry_run:
        elapsed = time.time() - start_time
        print("--- Sample records (first 2) ---")
        for r in records[:2]:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        print()
        print(
            f"Dry-run complete -- {len(records)} sample records, "
            f"{total_errors} errors. ({elapsed:.1f}s)"
        )
        return

    if total_errors > 0:
        print(f"WARNING: {total_errors} parse errors encountered")

    # Build output
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_hash = compute_combined_hash(SOURCE_PAGES)
    meta = build_meta(config, source_hash, processing_date)
    output = {"meta": meta, "data": records}

    # Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    size_kb = OUTPUT_FILE.stat().st_size / 1024
    print(f"Wrote {len(records)} records -> {OUTPUT_FILE}")
    print(f"File size: {size_kb:.0f} KB")

    # Content plausibility check -- verify no record contains Epistle/Gospel text
    print()
    print("Content plausibility check:")
    suspect_count = spot_check_content(records)
    if suspect_count == 0:
        print("  OK -- no records start with known Epistle/Gospel openers")
    else:
        print(
            f"  WARNING: {suspect_count} record(s) flagged -- inspect before shipping"
        )
        total_errors += suspect_count

    elapsed = time.time() - start_time
    print()
    print(f"Done in {elapsed:.1f}s")

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
