"""gutenberg_anglican.py
Parse Anglican classics from Project Gutenberg and CCEL into OCD schemas.

Sources:
  PG #23772  -- Donne, Devotions Upon Emergent Occasions (structured_text)
  PG #22088  -- Newman, Apologia Pro Vita Sua (structured_text)
  CCEL       -- Taylor, The Rule and Exercises of Holy Living (structured_text)
  CCEL       -- Taylor, The Rule and Exercises of Holy Dying (structured_text)
  CCEL       -- Andrewes, The Devotions of Bishop Andrewes / Preces Privatae (prayer)

Outputs:
  data/structured-text/donne-devotions-upon-emergent-occasions.json
  data/structured-text/newman-apologia-pro-vita-sua.json
  data/structured-text/taylor-holy-living.json
  data/structured-text/taylor-holy-dying.json
  data/prayers/andrewes-private-devotions/prayers.json

Source notes:
  - Taylor Holy Living/Dying: PG not confirmed; CCEL used (1860 Philadelphia ed.).
    CORPUS_PRIORITY.md lists "PG / IA" for Taylor; CCEL provides cleaner text.
  - Andrewes: PG not confirmed; CCEL used (Newman 1840 translation from Tract for
    the Times lxxviii, reprinted in H. B. Swete 1892 S.P.C.K. edition).
  - Hooker, Laws of Ecclesiastical Polity: DEFERRED -- not confirmed on PG; see
    LAST_SESSION.md for follow-up notes.
  - Donne schema: task listed as 'devotional' but OCD devotional schema requires
    month/day integers; Donne's Stations are illness-stage-keyed, not calendar-keyed.
    Mapped to structured_text with work_kind='devotional-classic'.

Usage:
    py -3 build/parsers/gutenberg_anglican.py --download --parse
    py -3 build/parsers/gutenberg_anglican.py --download --parse --dry-run
    py -3 build/parsers/gutenberg_anglican.py --parse
    py -3 build/parsers/gutenberg_anglican.py --work donne --parse
    py -3 build/parsers/gutenberg_anglican.py --all
"""

import argparse
import json
import re
import sys
import time
import urllib.request  # standards: download only
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from build.lib.contributors import normalize_contributors  # noqa: E402
from build.lib._generated_enums import (  # noqa: E402
    STRUCTURED_TEXT__DATA__WORK_KIND,
    STRUCTURED_TEXT__META__AUDIENCE,
    STRUCTURED_TEXT__META__COMPLETENESS,
    STRUCTURED_TEXT__META__ERA,
    STRUCTURED_TEXT__META__TRADITION,
)
from build.lib.text_utils import compute_source_hash, smart_title  # noqa: E402
from build.lib.pg_inline_markup import (  # noqa: E402
    append_pg_inline_markup_note,
    decode_pg_inline_markup,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RAW_PG_DIR = REPO_ROOT / "raw" / "gutenberg"
RAW_CCEL_DIR = REPO_ROOT / "raw" / "ccel"
ST_OUTPUT_DIR = REPO_ROOT / "data" / "structured-text"
PRAYER_OUTPUT_DIR = REPO_ROOT / "data" / "prayers" / "andrewes-private-devotions"
SOURCES_ST_DIR = REPO_ROOT / "sources" / "structured-text"
SOURCES_PRAYER_DIR = REPO_ROOT / "sources" / "prayers"
LOG_FILE = Path(__file__).resolve().parent / "gutenberg_anglican.log"

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "build/parsers/gutenberg_anglican.py@v1.0.0"
DOWNLOAD_DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")

USER_AGENT = (
    "OpenChristianData/1.0 "
    "(research; open-source data project; contact: openchristiandata@gmail.com)"
)
PG_DELAY = 2
CCEL_DELAY = 10

# PG markers
_PG_START_RE = re.compile(r"\*\*\*\s*START OF", re.IGNORECASE)
_PG_END_RE = re.compile(r"\*\*\*\s*END OF", re.IGNORECASE)

# Roman numeral pattern
_ROMAN_RE = re.compile(r"^(M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}))$")


def _is_roman(s: str) -> bool:
    s = s.strip().rstrip(".")
    return bool(s) and bool(_ROMAN_RE.match(s.upper()))


# ---------------------------------------------------------------------------
# Work config
# ---------------------------------------------------------------------------

WORK_CONFIG = [
    {
        "slug": "donne-devotions-upon-emergent-occasions",
        "title": "Devotions Upon Emergent Occasions",
        "author": "John Donne",
        "author_id": "donne-john",
        "birth": 1572,
        "death": 1631,
        "pub_year": 1624,
        "tradition": ["anglican"],
        "tradition_notes": (
            "John Donne (1572–1631), Dean of St Paul's Cathedral, wrote the Devotions "
            "during a severe illness in 1623. The work's 23 Stations trace his sickness, "
            "recovery, and spiritual reflection — each in three movements: Meditation, "
            "Expostulation, and Prayer. The seventeenth Meditation contains the famous "
            "'No man is an island' passage."
        ),
        "era": "post-reformation",
        "audience": "lay",
        "original_lang": "en",
        "schema": "structured_text",
        "work_kind": "devotional-classic",
        "source_type": "pg",
        "pg_id": 23772,
        "source_url": "http://www.gutenberg.org/cache/epub/23772/pg23772.txt",
        "source_edition": (
            "Devotions Upon Emergent Occasions; Together with Death's Duel, "
            "Project Gutenberg PG#23772"
        ),
        "output_file": "data/structured-text/donne-devotions-upon-emergent-occasions.json",
        "completeness": "full",
        "notes": (
            "Contains all 23 Stations plus Death's Duel sermon appended. Each Station "
            "parsed as a section with three child sub-sections (Meditation, Expostulation, "
            "Prayer). OCD devotional schema was considered but requires month/day integer "
            "fields; these Stations are illness-stage-keyed, so structured_text used instead."
        ),
    },
    {
        "slug": "newman-apologia-pro-vita-sua",
        "title": "Apologia Pro Vita Sua",
        "author": "John Henry Newman",
        "author_id": "newman-john-henry",
        "birth": 1801,
        "death": 1890,
        "pub_year": 1864,
        "tradition": ["anglican", "catholic"],
        "tradition_notes": (
            "John Henry Newman (1801–1890) wrote the Apologia in 1864 as a defense of his "
            "religious integrity after Charles Kingsley's public attack. It traces his "
            "theological development from his evangelical Anglican upbringing through the "
            "Oxford Movement to his 1845 conversion to Roman Catholicism. Regarded as one "
            "of the greatest spiritual autobiographies in the English language."
        ),
        "era": "modern",
        "audience": "lay",
        "original_lang": "en",
        "schema": "structured_text",
        "work_kind": "theological-work",
        "source_type": "pg",
        "pg_id": 22088,
        "source_url": "http://www.gutenberg.org/cache/epub/22088/pg22088.txt",
        "source_edition": (
            "Apologia pro vita sua: being a history of his religious opinions. "
            "London: Longmans, Green, and Co., 1890. Project Gutenberg PG#22088."
        ),
        "output_file": "data/structured-text/newman-apologia-pro-vita-sua.json",
        "completeness": "full",
        "notes": (
            "Five chapters tracing Newman's religious opinions by period (1833–1845), "
            "plus supplementary Notes A–G and additional numbered notes. "
            "PG edition is the 1890 Longmans edition."
        ),
    },
    {
        "slug": "taylor-holy-living",
        "title": "The Rule and Exercises of Holy Living",
        "author": "Jeremy Taylor",
        "author_id": "taylor-jeremy",
        "birth": 1613,
        "death": 1667,
        "pub_year": 1650,
        "tradition": ["anglican"],
        "tradition_notes": (
            "Jeremy Taylor (1613–1667), Anglican bishop and chaplain to King Charles I, "
            "wrote Holy Living (1650) as a comprehensive guide to practical piety during "
            "the Interregnum. With Holy Dying (1651), these two works constitute the "
            "classic Anglican treatment of holy life and Christian death."
        ),
        "era": "post-reformation",
        "audience": "lay",
        "original_lang": "en",
        "schema": "structured_text",
        "work_kind": "devotional-classic",
        "source_type": "ccel",
        "ccel_url": "https://www.ccel.org/ccel/t/taylor/holy_living/cache/holy_living.txt",
        "source_edition": (
            "The Rule and Exercises of Holy Living. Philadelphia: J. W. Bradley, 1860. "
            "CCEL edition."
        ),
        "output_file": "data/structured-text/taylor-holy-living.json",
        "completeness": "full",
        "notes": (
            "Not found on PG despite CORPUS_PRIORITY.md listing 'PG / IA'. CCEL text "
            "used (1860 Philadelphia edition, manually prepared). Chapter-level parse; "
            "biographical sketch by Dr. Croly excluded."
        ),
    },
    {
        "slug": "taylor-holy-dying",
        "title": "The Rule and Exercises of Holy Dying",
        "author": "Jeremy Taylor",
        "author_id": "taylor-jeremy",
        "birth": 1613,
        "death": 1667,
        "pub_year": 1651,
        "tradition": ["anglican"],
        "tradition_notes": (
            "Jeremy Taylor's Holy Dying (1651) is the companion to Holy Living. Written "
            "during the grief of Taylor's patron's wife, it is the definitive Anglican "
            "treatment of Christian preparation for death. Widely regarded as one of the "
            "finest works of 17th-century English prose."
        ),
        "era": "post-reformation",
        "audience": "lay",
        "original_lang": "en",
        "schema": "structured_text",
        "work_kind": "devotional-classic",
        "source_type": "ccel",
        "ccel_url": "https://www.ccel.org/ccel/t/taylor/holy_dying/cache/holy_dying.txt",
        "source_edition": (
            "The Rule and Exercises of Holy Dying. CCEL edition."
        ),
        "output_file": "data/structured-text/taylor-holy-dying.json",
        "completeness": "full",
        "notes": (
            "Not found on PG; CCEL text used. Chapter-level parse; dedication and "
            "introductory material included as a preface section."
        ),
    },
    {
        "slug": "andrewes-private-devotions",
        "title": "The Devotions of Bishop Andrewes (Preces Privatae)",
        "author": "Lancelot Andrewes",
        "author_id": "andrewes-lancelot",
        "birth": 1555,
        "death": 1626,
        "pub_year": 1648,
        "contributors": ["John Henry Newman (translator, 1840)"],
        "tradition": ["anglican"],
        "tradition_notes": (
            "Lancelot Andrewes (1555–1626), Bishop of Winchester, wrote the Preces Privatae "
            "as a personal devotion book in Greek, Latin, and Hebrew. The Newman 1840 "
            "translation (Tract for the Times lxxviii) is the most accessible English "
            "version. Andrewes is the father of Caroline Anglicanism and one of the "
            "principal translators of the King James Bible."
        ),
        "era": "post-reformation",
        "audience": "pastoral",
        "original_lang": "grc",
        "schema": "prayer",
        "source_type": "ccel",
        "ccel_url": "https://www.ccel.org/ccel/a/andrewes/devotions1/cache/devotions1.txt",
        "source_edition": (
            "The Devotions of Bishop Andrewes. Vol. I. Translated by John Henry Newman "
            "(1840, Tract for the Times lxxviii). Edited by H. B. Swete. "
            "London: S.P.C.K., 1892."
        ),
        "output_file": "data/prayers/andrewes-private-devotions/prayers.json",
        "completeness": "partial",
        "notes": (
            "Newman's 1840 translation confirmed via preface signature 'J.H.N.' and "
            "Swete's introduction. Newman died 1890 (PD); Swete died 1917 (PD); "
            "1892 edition pre-1928 (US PD). PG not confirmed; CCEL used for text quality. "
            "Vol. I only; CCEL does not appear to have Vol. II (Latin/Greek daily offices)."
        ),
    },
]


def _validate_configs() -> None:
    for cfg in WORK_CONFIG:
        if cfg.get("schema") != "structured_text":
            continue
        slug = cfg["slug"]
        for tradition in cfg.get("tradition", []):
            assert tradition in STRUCTURED_TEXT__META__TRADITION, f"{slug}: invalid tradition value {tradition!r}"
        assert (era := cfg["era"]) in STRUCTURED_TEXT__META__ERA, f"{slug}: invalid era value {era!r}"
        assert (audience := cfg["audience"]) in STRUCTURED_TEXT__META__AUDIENCE, (
            f"{slug}: invalid audience value {audience!r}"
        )
        assert (work_kind := cfg["work_kind"]) in STRUCTURED_TEXT__DATA__WORK_KIND, (
            f"{slug}: invalid work_kind value {work_kind!r}"
        )
        assert (completeness := cfg["completeness"]) in STRUCTURED_TEXT__META__COMPLETENESS, (
            f"{slug}: invalid completeness value {completeness!r}"
        )


_validate_configs()

SLUG_TO_CONFIG = {c["slug"]: c for c in WORK_CONFIG}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(msg: str, log_lines: list) -> None:
    safe = msg.encode("ascii", errors="replace").decode("ascii")
    print(safe)
    log_lines.append(msg)




def word_count(blocks: list) -> int:
    return sum(len(b.split()) for b in blocks)


def make_incipit(text: str, n: int = 10) -> str:
    words = text.split()
    if len(words) <= n:
        return text
    return " ".join(words[:n]) + "..."


_CONTENT_SEP_RE = re.compile(r"^_{5,}$")


def gather_paragraphs(lines: list, start: int, stop: int) -> list:
    paragraphs = []
    current = []
    for i in range(start, min(stop, len(lines))):
        stripped = lines[i].rstrip()
        content = stripped.strip()
        # Blank lines and CCEL separator lines (____) both flush the current paragraph
        if not content or _CONTENT_SEP_RE.match(content):
            if current:
                text = " ".join(current)
                text = " ".join(text.split())
                if text:
                    paragraphs.append(decode_pg_inline_markup(text))
                current = []
        else:
            current.append(content)
    if current:
        text = " ".join(current)
        text = " ".join(text.split())
        if text:
            paragraphs.append(decode_pg_inline_markup(text))
    return paragraphs


def strip_pg_wrapper(text: str) -> list:
    lines = text.splitlines()
    start_idx = end_idx = None
    for i, line in enumerate(lines):
        if _PG_START_RE.search(line) and start_idx is None:
            start_idx = i
        if _PG_END_RE.search(line):
            end_idx = i
            break
    if start_idx is None or end_idx is None:
        raise ValueError("Could not find PG start/end markers")
    return lines[start_idx + 1 : end_idx]


_PG_PRODUCED_RE = re.compile(r"^Produced by\s+(.+)$", re.IGNORECASE)
_URL_RE = re.compile(r"^https?://")


def strip_pg_contributors(body: list) -> tuple[list, list]:
    """Remove the 'Produced by' transcriber credit block from PG body lines.

    Scans the first 15 lines, collects the block through the next blank line,
    and returns (cleaned_body, contributors) where contributors are
    {"name": str, "role": "transcriber"} dicts for normalize_contributors().
    """
    start_idx = None
    for i, line in enumerate(body[:15]):
        m = _PG_PRODUCED_RE.match(line.strip())
        if m:
            start_idx = i
            raw_names = m.group(1)
            produced_names = [n.strip() for n in raw_names.split(",") if n.strip()]
            break

    if start_idx is None:
        return body, []

    # Collect continuation lines until the next blank line
    end_idx = start_idx + 1
    continuation = []
    while end_idx < len(body) and body[end_idx].strip():
        continuation.append(body[end_idx].strip())
        end_idx += 1

    # Build contributor list from named individuals on the "Produced by" line
    contributors: list[dict] = [
        {"name": n, "role": "transcriber"} for n in produced_names
    ]

    # Parse continuation lines: "and the TEAM at" → team contributor; URL → attach
    pending_url: str | None = None
    for cline in continuation:
        if _URL_RE.match(cline):
            pending_url = cline
        else:
            # "and the Online Distributed Proofreading Team at"
            tm = re.match(r"^(?:and\s+)?the\s+(.+?)(?:\s+at)?\s*$", cline, re.IGNORECASE)
            if tm:
                entry: dict = {"name": tm.group(1).strip(), "role": "transcriber"}
                if pending_url:
                    entry["url"] = pending_url
                    pending_url = None
                contributors.append(entry)

    # Attach any trailing URL to the last contributor
    if pending_url and contributors:
        contributors[-1]["url"] = pending_url

    cleaned = body[:start_idx] + body[end_idx:]
    return cleaned, contributors


def strip_ccel_header(lines: list) -> list:
    """Strip the CCEL metadata block (leading ___-lines + catalog metadata).

    The CCEL header is confined to the first ~30 lines; separators appearing
    later in the file are section dividers, not header markers.
    """
    last_sep = -1
    sep_re = re.compile(r"^\s*_{5,}\s*$")
    for i, line in enumerate(lines[:30]):
        if sep_re.match(line):
            last_sep = i
    if last_sep == -1:
        return lines
    # Start from the first non-empty line after the last header separator
    start = last_sep + 1
    while start < len(lines) and not lines[start].strip():
        start += 1
    return lines[start:]


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def _fetch_url(url: str, dest: Path, label: str, log_lines: list) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        log(f"  Saved {len(data):,} bytes -> {dest.name}", log_lines)
        return True
    except Exception as exc:
        log(f"  ERROR fetching {label}: {exc}", log_lines)
        return False


def download_work(config: dict, force: bool, log_lines: list) -> bool:
    slug = config["slug"]
    source_type = config["source_type"]

    if source_type == "pg":
        pg_id = config["pg_id"]
        dest = RAW_PG_DIR / f"pg{pg_id}.txt"
        if dest.exists() and not force:
            log(f"  Cached: {dest.name}", log_lines)
            return True
        url = f"http://www.gutenberg.org/cache/epub/{pg_id}/pg{pg_id}.txt"
        log(f"  Downloading PG#{pg_id}: {url}", log_lines)
        ok = _fetch_url(url, dest, f"PG#{pg_id}", log_lines)
        if ok:
            time.sleep(PG_DELAY)
        return ok

    elif source_type == "ccel":
        dest = RAW_CCEL_DIR / f"{slug}.txt"
        if dest.exists() and not force:
            log(f"  Cached: {dest.name}", log_lines)
            return True
        url = config["ccel_url"]
        log(f"  Downloading CCEL: {url}", log_lines)
        ok = _fetch_url(url, dest, f"CCEL/{slug}", log_lines)
        if ok:
            time.sleep(CCEL_DELAY)
        return ok

    log(f"  ERROR: unknown source_type={source_type!r} for {slug}", log_lines)
    return False


def get_raw_path(config: dict) -> Path:
    if config["source_type"] == "pg":
        return RAW_PG_DIR / f"pg{config['pg_id']}.txt"
    return RAW_CCEL_DIR / f"{config['slug']}.txt"


def load_body(config: dict, log_lines: list) -> list | None:
    path = get_raw_path(config)
    if not path.exists():
        log(f"  ERROR: raw file not found: {path}", log_lines)
        log("  Run with --download first.", log_lines)
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if config["source_type"] == "pg":
        try:
            body = strip_pg_wrapper(text)
        except ValueError as exc:
            log(f"  ERROR stripping PG wrapper: {exc}", log_lines)
            return None
    else:
        body = strip_ccel_header(lines)
    log(f"  Body lines: {len(body)}", log_lines)
    return body


# ---------------------------------------------------------------------------
# Meta builders
# ---------------------------------------------------------------------------


def build_structured_text_meta(config: dict, source_hash: str) -> dict:
    return {
        "id": config["slug"],
        "title": config["title"],
        "author": config["author"],
        "author_id": config["author_id"],
        "author_birth_year": config["birth"],
        "author_death_year": config["death"],
        "contributors": normalize_contributors(config.get("contributors", [])),
        "original_publication_year": config["pub_year"],
        "language": "en",
        "original_language": config["original_lang"],
        "tradition": config["tradition"],
        "tradition_notes": config["tradition_notes"],
        "era": config["era"],
        "audience": config["audience"],
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": config.get("completeness", "full"),
        "provenance": {
            "source_url": config["source_url"] if config["source_type"] == "pg"
                          else config["ccel_url"],
            "source_format": "plain text (UTF-8)",
            "source_edition": config["source_edition"],
            "download_date": DOWNLOAD_DATE,
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": SCRIPT_VERSION,
            "processing_date": DOWNLOAD_DATE,
            "notes": append_pg_inline_markup_note(config.get("notes")),
        },
    }


def build_prayer_meta(config: dict, source_hash: str) -> dict:
    return {
        "id": config["slug"],
        "title": config["title"],
        "author": config["author"],
        "author_birth_year": config["birth"],
        "author_death_year": config["death"],
        "contributors": normalize_contributors(config.get("contributors", [])),
        "original_publication_year": config["pub_year"],
        "language": "en",
        "original_language": config["original_lang"],
        "tradition": config["tradition"],
        "tradition_notes": config["tradition_notes"],
        "era": config["era"],
        "audience": config["audience"],
        "license": "public-domain",
        "schema_type": "prayer",
        "schema_version": SCHEMA_VERSION,
        "completeness": config.get("completeness", "full"),
        "provenance": {
            "source_url": config["ccel_url"],
            "source_format": "plain text (UTF-8)",
            "source_edition": config["source_edition"],
            "download_date": DOWNLOAD_DATE,
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": SCRIPT_VERSION,
            "processing_date": DOWNLOAD_DATE,
            "notes": append_pg_inline_markup_note(config.get("notes")),
        },
    }


# ---------------------------------------------------------------------------
# Parser: Donne — Devotions Upon Emergent Occasions (structured_text)
#
# PG text structure:
#   Station heading:   Roman numeral alone   e.g.  I
#                      Latin title line:            INSULTUS MORBI PRIMUS.
#                      English title (italics):     _The first Alteration..._
#   Sub-section:       "[Roman]. MEDITATION."
#                      "[Roman]. EXPOSTULATION."
#                      "[Roman]. PRAYER."
# ---------------------------------------------------------------------------

_DONNE_STATION_RE = re.compile(r"^([IVX]+)\s*$")
_DONNE_STATION_TITLED_RE = re.compile(r"^([IVX]+)\.\s+(.+)$")
_DONNE_SUBSECTION_RE = re.compile(
    r"^([IVX]+)\.\s+(MEDITATION|EXPOSTULATION|PRAYER)\.\s*$", re.IGNORECASE
)
_ITALIC_UNDERLINE_RE = re.compile(r"^_(.+)_$")


def _donne_find_english_title(lines: list, from_idx: int) -> str:
    """Scan forward from from_idx for the first _italic_ English subtitle."""
    for k in range(from_idx, min(from_idx + 12, len(lines))):
        kline = lines[k].strip()
        if kline:
            m = _ITALIC_UNDERLINE_RE.match(kline)
            if m:
                return m.group(1)
    return ""


def parse_donne_devotions(lines: list, log_lines: list) -> dict:
    """Parse Donne's Devotions Upon Emergent Occasions.

    Each Station → section with 3 child sub-sections (Meditation, Expostulation, Prayer).

    Heading formats in the PG text:
      Station I:      lone Roman numeral 'I'  (unique to first station)
      Stations II-XXIII:  'II. POST ACTIO LAESA.'  (Roman + ALL CAPS Latin title)
      Sub-sections:   'I. MEDITATION.' / 'I. EXPOSTULATION.' / 'I. PRAYER.'
    """
    events = []  # (line_idx, type, roman, en_title[, latin_title])

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        # Sub-section heading (checked first to avoid station-headed false matches)
        m2 = _DONNE_SUBSECTION_RE.match(stripped)
        if m2:
            roman = m2.group(1)
            sub_type = m2.group(2).capitalize()
            events.append((i, "subsection", roman, sub_type))
            i += 1
            continue

        # Station I: lone Roman numeral
        m = _DONNE_STATION_RE.match(stripped)
        if m and len(stripped) <= 7:
            roman = m.group(1)
            # Latin subtitle on next non-blank line
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            latin_title = lines[j].strip() if j < len(lines) else ""
            en_title = _donne_find_english_title(lines, j + 1)
            events.append((i, "station", roman, en_title, latin_title))
            i += 1
            continue

        # Stations II-XXIII: 'II. POST ACTIO LAESA.' (Roman + ALL CAPS or dashed Latin)
        m3 = _DONNE_STATION_TITLED_RE.match(stripped)
        if m3:
            roman = m3.group(1)
            latin_raw = m3.group(2).strip()
            # Require ALL CAPS Latin title or dashes (station heading, not prose)
            is_all_caps = latin_raw.upper() == latin_raw
            has_dashes = "--" in latin_raw or latin_raw.startswith("-")
            if is_all_caps or has_dashes:
                en_title = _donne_find_english_title(lines, i + 1)
                events.append((i, "station", roman, en_title, latin_raw))
                i += 1
                continue

        i += 1

    # Filter events: only station and subsection types
    station_events = [e for e in events if e[1] == "station"]
    log(f"  Found {len(station_events)} station headings", log_lines)

    sections = []
    for s_idx, station_evt in enumerate(station_events):
        s_line = station_evt[0]
        s_roman = station_evt[2]
        s_title = station_evt[3]
        s_label = f"Station {s_roman}"
        next_station_line = station_events[s_idx + 1][0] if s_idx + 1 < len(station_events) else len(lines)

        # Sub-sections within this station
        sub_evts = [
            e for e in events
            if e[1] == "subsection" and e[2] == s_roman
            and s_line < e[0] < next_station_line
        ]

        children = []
        for ss_idx, sub_evt in enumerate(sub_evts):
            ss_line = sub_evt[0]
            ss_type = sub_evt[3]  # Meditation / Expostulation / Prayer
            next_ss_line = sub_evts[ss_idx + 1][0] if ss_idx + 1 < len(sub_evts) else next_station_line
            paras = gather_paragraphs(lines, ss_line + 1, next_ss_line)
            wc = word_count(paras)
            children.append(
                {
                    "section_type": "subsection",
                    "label": ss_type,
                    "title": None,
                    "content_blocks": paras,
                    "scripture_references": [],
                    "word_count": wc,
                    "children": [],
                }
            )

        # If no sub-sections found, collect all content as a single child
        if not children:
            paras = gather_paragraphs(lines, s_line + 1, next_station_line)
            if paras:
                children.append(
                    {
                        "section_type": "subsection",
                        "label": "Content",
                        "title": None,
                        "content_blocks": paras,
                        "scripture_references": [],
                        "word_count": word_count(paras),
                        "children": [],
                    }
                )

        section_wc = sum(c["word_count"] for c in children)
        sections.append(
            {
                "section_type": "chapter",
                "label": s_label,
                "title": s_title,
                "content_blocks": [],
                "scripture_references": [],
                "word_count": section_wc,
                "children": children,
            }
        )

    total_words = sum(s["word_count"] for s in sections)
    log(f"  Donne: {len(sections)} stations, {total_words} total words", log_lines)

    return {
        "work_id": "donne-devotions-upon-emergent-occasions",
        "work_kind": "devotional-classic",
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Parser: Newman — Apologia Pro Vita Sua (structured_text)
#
# PG text structure:
#   Chapter: "Chapter I" (title case, Roman numeral)
#   Notes:   "NOTE A" / "Note A." / "A." (supplementary notes)
# ---------------------------------------------------------------------------

_NEWMAN_CHAPTER_RE = re.compile(r"^\s*CHAPTER\s+([IVX]+)\.", re.IGNORECASE)
# NOTE A. ON PAGE 14. — all-caps in the body; TOC has 'Note A. On page...' (mixed case)
_NEWMAN_NOTE_RE = re.compile(r"^\s*NOTE\s+([A-G])\.")  # no IGNORECASE: requires caps


def _newman_is_toc_chapter(lines: list, i: int) -> bool:
    """Return True when CHAPTER at line i is a table-of-contents entry.

    TOC entries have a mixed-case description on the next non-blank line;
    real chapter headings are followed by an ALL-CAPS subtitle.
    """
    j = i + 1
    while j < min(i + 5, len(lines)) and not lines[j].strip():
        j += 1
    if j >= len(lines):
        return False
    next_line = lines[j].strip()
    return bool(next_line) and any(c.islower() for c in next_line)


def parse_newman_apologia(lines: list, log_lines: list) -> dict:
    """Parse Newman's Apologia Pro Vita Sua into structured_text sections."""
    events = []  # (line_idx, type, label)

    for i, line in enumerate(lines):
        stripped = line.strip()
        m = _NEWMAN_CHAPTER_RE.match(stripped)
        if m:
            if not _newman_is_toc_chapter(lines, i):
                events.append((i, "chapter", f"Chapter {m.group(1).upper()}"))
            continue
        m2 = _NEWMAN_NOTE_RE.match(stripped)
        if m2:
            events.append((i, "note", f"Note {m2.group(1).upper()}"))
            continue

    chapter_events = [e for e in events if e[1] == "chapter"]
    note_events = [e for e in events if e[1] == "note"]
    log(f"  Found {len(chapter_events)} chapter headings, {len(note_events)} note headings", log_lines)

    all_events = sorted(events, key=lambda x: x[0])
    sections = []

    # Preface: content before first chapter
    first_event_line = all_events[0][0] if all_events else len(lines)
    preface_paras = gather_paragraphs(lines, 0, first_event_line)
    if preface_paras:
        sections.append(
            {
                "section_type": "preface",
                "label": "Preface",
                "title": None,
                "content_blocks": preface_paras,
                "scripture_references": [],
                "word_count": word_count(preface_paras),
                "children": [],
            }
        )

    for e_idx, evt in enumerate(all_events):
        e_line = evt[0]
        e_label = evt[2]
        e_type = evt[1]
        next_line = all_events[e_idx + 1][0] if e_idx + 1 < len(all_events) else len(lines)

        # Title: next non-empty line after heading
        title = None
        j = e_line + 1
        while j < min(e_line + 5, len(lines)) and not lines[j].strip():
            j += 1
        if j < len(lines):
            cand = lines[j].strip()
            if cand and not _NEWMAN_CHAPTER_RE.match(cand) and not _NEWMAN_NOTE_RE.match(cand):
                # Accept multi-line titles (caps or title case)
                if len(cand) < 200:
                    title = cand

        paras = gather_paragraphs(lines, e_line + 1, next_line)
        sec_type = "chapter" if e_type == "chapter" else "section"
        sections.append(
            {
                "section_type": sec_type,
                "label": e_label,
                "title": title,
                "content_blocks": paras,
                "scripture_references": [],
                "word_count": word_count(paras),
                "children": [],
            }
        )

    total_words = sum(s["word_count"] for s in sections)
    log(f"  Newman: {len(sections)} sections, {total_words} words", log_lines)

    return {
        "work_id": "newman-apologia-pro-vita-sua",
        "work_kind": "theological-work",
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Parser: Taylor — Holy Living / Holy Dying (structured_text)
#
# CCEL text structure (1860 Philadelphia edition):
#   CHAPTER [ROMAN]  (ALL CAPS line)
#   [ALL CAPS title on next lines]
#   Content paragraphs (prose)
#   Numbered items: "1. They that..." "2. In using..."
#   Section sub-headings: "SECT. I." or "SECTION I." (ALL CAPS, if present)
# ---------------------------------------------------------------------------

_TAYLOR_CHAPTER_RE = re.compile(r"^\s*CHAPTER\s+([IVX]+)\.?\s*$")
_TAYLOR_SECTION_RE = re.compile(r"^\s*(?:SECT(?:ION)?\.?\s+)([IVX]+)\.?\s*$", re.IGNORECASE)


def parse_taylor(lines: list, work_id: str, log_lines: list) -> dict:
    """Parse a Taylor work (Holy Living or Holy Dying) from CCEL text.

    Structure: Chapters, each with content_blocks.
    Optional: Section sub-headings within chapters (if present in the text).
    Preamble before Chapter I is captured as a 'preface' section.
    """
    events = []  # (line_idx, type, roman, title)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        m = _TAYLOR_CHAPTER_RE.match(stripped)
        if m:
            events.append((i, "chapter", m.group(1), None))
            continue
        m2 = _TAYLOR_SECTION_RE.match(stripped)
        if m2:
            events.append((i, "section", m2.group(1), None))

    chapter_events = [(e[0], e[2]) for e in events if e[1] == "chapter"]
    log(f"  Found {len(chapter_events)} chapter headings", log_lines)

    if not chapter_events:
        log("  WARNING: no chapter headings found — outputting as single preface section", log_lines)
        paras = gather_paragraphs(lines, 0, len(lines))
        return {
            "work_id": work_id,
            "work_kind": "devotional-classic",
            "sections": [
                {
                    "section_type": "preface",
                    "label": "Full Text",
                    "title": None,
                    "content_blocks": paras,
                    "scripture_references": [],
                    "word_count": word_count(paras),
                    "children": [],
                }
            ],
        }

    sections = []

    # Preamble before first chapter (dedication, biography stub)
    first_ch_line = chapter_events[0][0]
    pre_paras = gather_paragraphs(lines, 0, first_ch_line)
    if pre_paras:
        sections.append(
            {
                "section_type": "preface",
                "label": "Preface",
                "title": None,
                "content_blocks": pre_paras,
                "scripture_references": [],
                "word_count": word_count(pre_paras),
                "children": [],
            }
        )

    for ch_idx, (ch_line, roman) in enumerate(chapter_events):
        next_ch_line = chapter_events[ch_idx + 1][0] if ch_idx + 1 < len(chapter_events) else len(lines)
        label = f"Chapter {roman}"

        # Chapter title: ALL CAPS line(s) immediately following the chapter heading
        title_lines = []
        j = ch_line + 1
        while j < min(ch_line + 8, len(lines)):
            cand = lines[j].strip()
            if not cand:
                j += 1
                # Stop if we hit a blank line after collecting title lines
                if title_lines:
                    break
                continue
            if cand.upper() == cand and not _TAYLOR_CHAPTER_RE.match(cand):
                title_lines.append(cand)
                j += 1
            else:
                break
        chapter_title = " ".join(title_lines).strip() if title_lines else None

        # Section events within this chapter
        sec_evts = [
            (e[0], e[2])
            for e in events
            if e[1] == "section" and ch_line < e[0] < next_ch_line
        ]

        if sec_evts:
            # Parse into section children
            children = []
            for ss_idx, (ss_line, ss_roman) in enumerate(sec_evts):
                next_ss = sec_evts[ss_idx + 1][0] if ss_idx + 1 < len(sec_evts) else next_ch_line
                # Section title: next ALL CAPS line
                ss_title = None
                tj = ss_line + 1
                while tj < min(ss_line + 6, len(lines)):
                    tc = lines[tj].strip()
                    if not tc:
                        tj += 1
                        continue
                    if tc.upper() == tc and len(tc) < 200:
                        ss_title = tc
                    break
                paras = gather_paragraphs(lines, ss_line + 1, next_ss)
                children.append(
                    {
                        "section_type": "section",
                        "label": f"Section {ss_roman}",
                        "title": ss_title,
                        "content_blocks": paras,
                        "scripture_references": [],
                        "word_count": word_count(paras),
                        "children": [],
                    }
                )
            ch_wc = sum(c["word_count"] for c in children)
            sections.append(
                {
                    "section_type": "chapter",
                    "label": label,
                    "title": chapter_title,
                    "content_blocks": [],
                    "scripture_references": [],
                    "word_count": ch_wc,
                    "children": children,
                }
            )
        else:
            # No sub-sections: all content goes directly into chapter content_blocks
            # Start after the chapter title block
            content_start = ch_line + 1
            if title_lines:
                # Skip past the title lines we already read
                content_start = j
            paras = gather_paragraphs(lines, content_start, next_ch_line)
            ch_wc = word_count(paras)
            sections.append(
                {
                    "section_type": "chapter",
                    "label": label,
                    "title": chapter_title,
                    "content_blocks": paras,
                    "scripture_references": [],
                    "word_count": ch_wc,
                    "children": [],
                }
            )

        log(
            f"  {label}: {len(sec_evts)} subsections, "
            f"{sections[-1]['word_count']} words",
            log_lines,
        )

    total_words = sum(s["word_count"] for s in sections)
    log(f"  Total: {len(sections)} sections, {total_words} words", log_lines)

    return {
        "work_id": work_id,
        "work_kind": "devotional-classic",
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Parser: Andrewes — Private Devotions / Preces Privatae (prayer)
#
# CCEL text structure (Swete 1892 / Newman translation):
#   All-caps section headings:
#     DAILY PRAYERS PREPARATION
#     ORDER OF MATIN PRAYER
#     ORDER OF EVENING PRAYER
#     COURSE OF PRAYERS FOR THE WEEK
#     THE FIRST DAY  ..  THE SEVENTH DAY
#     ADDITIONAL EXERCISES
#     FORMS OF INTERCESSION
#     MEDITATIONS
#     A PREPARATION FOR HOLY COMMUNION
# ---------------------------------------------------------------------------

_ANDREWES_FOOTNOTE_RE = re.compile(r"\[\d+\]")


def _andrewes_normalize(line: str) -> str:
    """Strip footnote refs [n], trailing colon, and surrounding whitespace."""
    s = line.strip()
    s = _ANDREWES_FOOTNOTE_RE.sub("", s).strip()
    s = s.rstrip(":").strip()
    return s


# Known major prayer section headings (matched against _andrewes_normalize output)
_ANDREWES_SECTION_PATTERNS = [
    re.compile(r"^DAILY PRAYERS?\s+PREPARATION$"),
    re.compile(r"^ORDER OF MATIN PRAYER$"),
    re.compile(r"^ORDER OF EVENING PRAYER$"),
    re.compile(r"^COURSE OF PRAYERS? FOR THE WEEK$"),  # combined from two lines
    re.compile(r"^THE (FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH) DAY$"),
    re.compile(r"^ADDITIONAL EXERCISES?$"),
    re.compile(r"^FORMS? OF INTERCESSION$"),
    re.compile(r"^MEDITATIONS$"),  # plural only — singular is a sub-heading within Evening Prayer
    re.compile(r"^FOR HOLY COMMUNION$"),  # normalized from "A PREPARATION FOR HOLY COMMUNION"
    re.compile(r"^ORIGINAL PREFACE$"),
    re.compile(r"^INTRODUCTION\.?$"),
]

# Map normalized headings to canonical IDs
_ANDREWES_SLUG_MAP = {
    "DAILY PRAYERS PREPARATION": "daily-prayers-preparation",
    "DAILY PRAYER PREPARATION": "daily-prayers-preparation",
    "ORDER OF MATIN PRAYER": "order-of-matin-prayer",
    "ORDER OF EVENING PRAYER": "order-of-evening-prayer",
    "COURSE OF PRAYERS FOR THE WEEK": "course-of-prayers-for-the-week",
    "COURSE OF PRAYER FOR THE WEEK": "course-of-prayers-for-the-week",
    "THE FIRST DAY": "first-day",
    "THE SECOND DAY": "second-day",
    "THE THIRD DAY": "third-day",
    "THE FOURTH DAY": "fourth-day",
    "THE FIFTH DAY": "fifth-day",
    "THE SIXTH DAY": "sixth-day",
    "THE SEVENTH DAY": "seventh-day",
    "ADDITIONAL EXERCISES": "additional-exercises",
    "ADDITIONAL EXERCISE": "additional-exercises",
    "FORMS OF INTERCESSION": "forms-of-intercession",
    "FORM OF INTERCESSION": "forms-of-intercession",
    "MEDITATIONS": "meditations",
    "MEDITATION": "meditations",
    "FOR HOLY COMMUNION": "preparation-for-holy-communion",
    "A PREPARATION FOR HOLY COMMUNION": "preparation-for-holy-communion",
}

_ANDREWES_TITLE_OVERRIDES = {
    "FOR HOLY COMMUNION": "A Preparation for Holy Communion",
}

# Occasion labels for known sections
_ANDREWES_OCCASION_MAP = {
    "daily-prayers-preparation": "Personal Prayer",
    "order-of-matin-prayer": "Morning Prayer",
    "order-of-evening-prayer": "Evening Prayer",
    "course-of-prayers-for-the-week": "Weekly Devotion",
    "first-day": "Weekly Devotion",
    "second-day": "Weekly Devotion",
    "third-day": "Weekly Devotion",
    "fourth-day": "Weekly Devotion",
    "fifth-day": "Weekly Devotion",
    "sixth-day": "Weekly Devotion",
    "seventh-day": "Weekly Devotion",
    "additional-exercises": "Personal Prayer",
    "forms-of-intercession": "Intercession",
    "meditations": "Meditation",
    "preparation-for-holy-communion": "Holy Communion",
}


def _is_andrewes_heading(line: str) -> bool:
    s = _andrewes_normalize(line)
    if not s or s != s.upper():
        return False
    for pat in _ANDREWES_SECTION_PATTERNS:
        if pat.match(s):
            return True
    return False


def _andrewes_slug(heading: str) -> str:
    s = _andrewes_normalize(heading).upper()
    if s in _ANDREWES_SLUG_MAP:
        return _ANDREWES_SLUG_MAP[s]
    slug = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return slug


def _andrewes_title(heading: str) -> str:
    n = _andrewes_normalize(heading)
    if n in _ANDREWES_TITLE_OVERRIDES:
        return _ANDREWES_TITLE_OVERRIDES[n]
    return smart_title(n.strip()).replace("Of", "of").replace("For", "for")


_ANDREWES_COURSE_PARTIAL_RE = re.compile(r"^COURSE OF PRAYERS?$")
_ANDREWES_COURSE_SECOND_RE = re.compile(r"^FOR THE WEEK$")


def parse_andrewes_prayers(lines: list, log_lines: list) -> list:
    """Parse Andrewes' Preces Privatae into prayer records.

    Each major ALL-CAPS section heading → one prayer record.
    Handles: footnote refs ([n]), trailing colons, and the two-line
    'COURSE OF PRAYERS / FOR THE WEEK' heading.
    Preface, Introduction, and the container 'COURSE OF PRAYERS FOR THE WEEK'
    are skipped (no prayer content of their own).
    """
    events = []  # (line_idx, normalized_heading)
    i = 0
    while i < len(lines):
        line = lines[i]
        s = _andrewes_normalize(line)

        # Two-line heading: 'COURSE OF PRAYERS' / 'FOR THE WEEK'
        if s and s == s.upper() and _ANDREWES_COURSE_PARTIAL_RE.match(s):
            j = i + 1
            while j < min(i + 4, len(lines)) and not _andrewes_normalize(lines[j]):
                j += 1
            if j < len(lines):
                next_s = _andrewes_normalize(lines[j])
                if _ANDREWES_COURSE_SECOND_RE.match(next_s):
                    events.append((i, s + " " + next_s))
                    i = j + 1
                    continue

        if _is_andrewes_heading(line):
            events.append((i, s))
        i += 1

    log(f"  Found {len(events)} section headings", log_lines)
    for e_line, e_heading in events:
        log(f"    Line {e_line}: {e_heading}", log_lines)

    # Skip preface, introduction, and the empty container heading
    skip_slugs = {"original-preface", "introduction", "course-of-prayers-for-the-week"}
    filtered = [(li, h) for li, h in events if _andrewes_slug(h) not in skip_slugs]

    records = []
    for e_idx, (e_line, heading) in enumerate(filtered):
        next_line = filtered[e_idx + 1][0] if e_idx + 1 < len(filtered) else len(lines)
        paras = gather_paragraphs(lines, e_line + 1, next_line)

        if not paras:
            log(f"  WARNING: no content for section '{heading}' -- skipping", log_lines)
            continue

        slug = _andrewes_slug(heading)
        title = _andrewes_title(heading)
        occasion = _ANDREWES_OCCASION_MAP.get(slug, "Personal Prayer")
        incipit = make_incipit(paras[0])
        wc = word_count(paras)

        records.append(
            {
                "collection_id": "andrewes-private-devotions",
                "prayer_id": slug,
                "title": title,
                "incipit": incipit,
                "author": "Lancelot Andrewes",
                "year": 1648,
                "occasion": occasion,
                "content_blocks": paras,
                "scripture_references": [],
                "context": {
                    "work": "The Devotions of Bishop Andrewes (Preces Privatae)",
                    "location": smart_title(heading),
                },
                "word_count": wc,
            }
        )

    log(f"  Andrewes: {len(records)} prayer records", log_lines)
    return records


# ---------------------------------------------------------------------------
# Source config writers
# ---------------------------------------------------------------------------


def write_source_config(config: dict, source_hash: str, log_lines: list) -> None:
    if config["schema"] == "prayer":
        config_dir = SOURCES_PRAYER_DIR / config["slug"]
    else:
        config_dir = SOURCES_ST_DIR / config["slug"]

    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"

    source_url = config["source_url"] if config["source_type"] == "pg" else config["ccel_url"]
    source_format = "plain text (UTF-8)"

    cfg = {
        "resource_id": config["slug"],
        "title": config["title"],
        "author": config["author"],
        "author_birth_year": config["birth"],
        "author_death_year": config["death"],
        "contributors": config.get("contributors", []),
        "original_publication_year": config["pub_year"],
        "language": "en",
        "original_language": config["original_lang"],
        "tradition": config["tradition"],
        "tradition_notes": config["tradition_notes"],
        "era": config["era"],
        "audience": config["audience"],
        "license": "public-domain",
        "schema_type": config["schema"],
        "work_kind": config.get("work_kind"),
        "source_url": source_url,
        "source_format": source_format,
        "source_edition": config["source_edition"],
        "source_hash": source_hash,
        "download_date": DOWNLOAD_DATE,
        "output_file": config["output_file"],
        "notes": config.get("notes"),
    }

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
    log(f"  Source config: {config_path}", log_lines)


# ---------------------------------------------------------------------------
# Work runners
# ---------------------------------------------------------------------------


def run_work(config: dict, dry_run: bool, log_lines: list) -> bool:
    slug = config["slug"]
    schema = config["schema"]
    log(f"\n--- {slug} ---", log_lines)

    body = load_body(config, log_lines)
    if body is None:
        return False

    # Strip PG transcriber credits and add them to meta.contributors
    if config.get("source_type") == "pg":
        body, pg_contributors = strip_pg_contributors(body)
        if pg_contributors:
            existing = config.get("contributors", [])
            config = {**config, "contributors": existing + pg_contributors}
            log(f"  PG contributors: {[c['name'] for c in pg_contributors]}", log_lines)

    source_hash = compute_source_hash(get_raw_path(config))
    log(f"  Hash: {source_hash}", log_lines)

    if schema == "structured_text":
        if slug == "donne-devotions-upon-emergent-occasions":
            data = parse_donne_devotions(body, log_lines)
        elif slug.startswith("taylor-"):
            data = parse_taylor(body, slug, log_lines)
        elif slug == "newman-apologia-pro-vita-sua":
            data = parse_newman_apologia(body, log_lines)
        else:
            log(f"  ERROR: no parser for {slug}", log_lines)
            return False

        if not data.get("sections"):
            log(f"  ERROR: parse produced no sections", log_lines)
            return False

        # Quality check
        leaf_empty = 0
        leaf_zero_wc = 0
        def _check(secs: list) -> None:
            nonlocal leaf_empty, leaf_zero_wc
            for s in secs:
                if not s.get("children") and not s.get("content_blocks"):
                    leaf_empty += 1
                if s.get("content_blocks") and not s.get("children") and s.get("word_count", 0) == 0:
                    leaf_zero_wc += 1
                _check(s.get("children", []))
        _check(data["sections"])
        if leaf_empty:
            log(f"  WARNING: {leaf_empty} leaf sections with no content_blocks", log_lines)
        if leaf_zero_wc:
            log(f"  WARNING: {leaf_zero_wc} leaf sections with zero word_count", log_lines)

        if dry_run:
            top = data["sections"][0] if data["sections"] else {}
            log(
                f"  DRY RUN -- first section: {top.get('label')!r} "
                f"({top.get('word_count', 0)} words), "
                f"{len(data['sections'])} top-level sections",
                log_lines,
            )
            log("  DRY RUN -- no files written", log_lines)
            return True

        meta = build_structured_text_meta(config, source_hash)
        output = {"meta": meta, "data": data}
        out_path = REPO_ROOT / config["output_file"]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
            f.write("\n")
        log(f"  Written: {out_path}", log_lines)
        write_source_config(config, source_hash, log_lines)

    elif schema == "prayer":
        records = parse_andrewes_prayers(body, log_lines)

        if not records:
            log("  ERROR: parse produced no prayer records", log_lines)
            return False

        if dry_run:
            log(f"  DRY RUN -- {len(records)} prayer records", log_lines)
            if records:
                log(f"  DRY RUN -- first: {records[0]['prayer_id']!r} ({records[0]['word_count']} words)", log_lines)
            log("  DRY RUN -- no files written", log_lines)
            return True

        meta = build_prayer_meta(config, source_hash)
        output = {"meta": meta, "data": records}
        out_path = REPO_ROOT / config["output_file"]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
            f.write("\n")
        log(f"  Written: {out_path}", log_lines)
        write_source_config(config, source_hash, log_lines)

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Anglican classics (PG + CCEL) to OCD structured_text / prayer JSON"
    )
    parser.add_argument("--download", action="store_true", help="Download source files")
    parser.add_argument("--parse", action="store_true", help="Parse and write output")
    parser.add_argument("--all", action="store_true", help="Download and parse all works")
    parser.add_argument("--dry-run", action="store_true", help="Parse without writing files")
    parser.add_argument("--force", action="store_true", help="Force re-download cached files")
    parser.add_argument(
        "--work",
        choices=list(SLUG_TO_CONFIG.keys()),
        help="Process one work only",
    )
    args = parser.parse_args()

    do_download = args.download or args.all
    do_parse = args.parse or args.all

    if not do_download and not do_parse:
        parser.print_help()
        sys.exit(0)

    log_lines = []
    import time as _time
    start = _time.time()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    log(
        f"[{ts}] gutenberg_anglican -- "
        f"{'DOWNLOAD ' if do_download else ''}"
        f"{'PARSE ' if do_parse else ''}"
        f"{'DRY-RUN' if args.dry_run else 'LIVE'}",
        log_lines,
    )

    works = [SLUG_TO_CONFIG[args.work]] if args.work else WORK_CONFIG

    if do_download:
        log("\n=== DOWNLOAD ===", log_lines)
        for config in works:
            log(f"\n  {config['slug']}:", log_lines)
            download_work(config, args.force, log_lines)

    if do_parse:
        log("\n=== PARSE ===", log_lines)
        successes = failures = 0
        for config in works:
            ok = run_work(config, args.dry_run, log_lines)
            if ok:
                successes += 1
            else:
                failures += 1
        elapsed = _time.time() - start
        log(
            f"\nDone -- {successes} succeeded, {failures} failed, {elapsed:.1f}s",
            log_lines,
        )

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n\n")

    if do_parse:
        failed = sum(
            1 for config in works
            if not (REPO_ROOT / config["output_file"]).exists()
        ) if not args.dry_run else 0
        if failed > 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
