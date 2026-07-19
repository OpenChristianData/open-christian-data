"""ccel_expositors_bible.py
Parser for The Expositor's Bible (49 vols, 1887-1905, ed. W. Robertson Nicoll) from CCEL ThML XML.

Downloads each volume's XML from the Christian Classics Ethereal Library once (cached in
raw/ccel/expositors-bible/), parses passage-keyed commentary sections, and writes one JSON
file per Bible book to data/commentaries/expositors-bible/{book_slug}.json following the
OCD commentary schema v1 (same as calvin-commentaries).

Source permission: CCEL confirmed OK (Quincy, 2026-04-01).
robots.txt: crawl-delay 10 for all agents (checked 2026-04-13).

XML structure (inspected 2026-04-13 across 5 pilot volumes):

  Root: <ThML> with no XML namespaces; DOCTYPE references external DTD (stripped before
        parsing to avoid external fetch and entity errors).

  Header: <ThML.head> -- contains electronicEdInfo with authorID, workID (skipped).

  Body: <ThML.body>
    Each volume has a sequence of <div1> elements.

    Skip list (front matter / back matter):
      - title attribute in: "Title Page", "Preface", "Epigraph", "Chronological Table",
        "Introduction", "Indexes", "Index of Passages and Texts"
      - Also skip any div1 whose title is "Title Page" or whose id is "i" (title page)
      - Fallback: skip if h2 text is "PREFACE" / "INDEXES" / "INTRODUCTION"

    Three structural patterns (all reducible to the same entry schema):

    Pattern A -- "passage in body text" (most volumes, e.g. Moule/Romans, Blaikie/1Sam):
      <div1 id="v" title="Chapter II">
        <h2>CHAPTER II</h2>
        <p>... THE WRITER AND HIS READERS ...</p>
        <p>Romans i. 1-7</p>     <!-- passage ref in first ~500 chars of text -->
        <p> ... commentary prose ... </p>
        <scripRef osisRef="Bible:Gal.2.20" passage="Gal. ii. 20">Gal. ii. 20</scripRef>
      </div1>
      Entry: one entry per div1, passage extracted from text.

    Pattern B -- "passage in div1.title" (Gibson/Matthew):
      <div1 id="iii" title="II. His Reception (Matt. II.)">
        passage extracted from title attribute.

    Pattern C -- "Psalms" (Maclaren/Psalms):
      <div1 id="iii" title="Psalm I.">
        One div per Psalm. Passage = "Psalms 1" = Ps.1.1-Ps.1.6 (KJV verse counts).

    Pattern D -- "multi-book volume" (Smith/Twelve Prophets):
      <div1 id="v" title="Amos">
        <div2 id="v.i" title="Chapter V. The Book of Amos">  -- introductory, no verse range
        <div2 id="v.ii" title="Chapter VI. The Man and the Prophet">  -- introductory
        <div2 id="v.vii" title="Chapter XI. ...">
          <p>Amos iii. 3-8; iv. 6-13; ...</p>  -- passage in div2 body text
        </div2>
      </div1>
      Each div2 becomes one entry; Bible book detected from div1.title ("Amos", "Hosea", etc.).
      Note: smith_ga/expositorprophets1 on CCEL only contains Amos, Hosea, Micah (not all 6
      minor prophets listed in the print edition).

  Scripture references:
    <scripRef osisRef="Bible:Rom.15.23" passage="Rom. xv. 23">...</scripRef>
    Both osisRef (strip "Bible:" prefix) and passage attribute are available.
    Some volumes use only passage=. Extract all osisRef attrs first; supplement with
    extract_refs_from_text() on the plain text body for broader coverage.

  footnotes: <note> elements -- excluded from commentary_text but not from cross_ref search
  page breaks: <pb> elements -- ignored
  scripture quotes: included as-is in commentary_text (they are part of the prose)

Usage:
    py -3 build/parsers/ccel_expositors_bible.py --volume moule/expositorromans --dry-run
    py -3 build/parsers/ccel_expositors_bible.py --volume moule/expositorromans
    py -3 build/parsers/ccel_expositors_bible.py --all
    py -3 build/parsers/ccel_expositors_bible.py --all --dry-run
"""

import argparse
import hashlib
import json
import logging
import re
import sys
import time
import urllib.request  # standards: download only
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))
from build.lib.paths import REPO_ROOT  # noqa: E402
RAW_DIR = REPO_ROOT / "raw" / "ccel" / "expositors-bible"
OUTPUT_DIR = REPO_ROOT / "data" / "commentaries" / "expositors-bible"
LOG_FILE = Path(__file__).with_suffix(".log")

SCHEMA_VERSION = "1.0.0"
SCRIPT_VERSION = "v1.1.0"
RESOURCE_ID = "expositors-bible"
SERIES_EDITOR = "W. Robertson Nicoll"

UA = "OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)"
CRAWL_DELAY = 10  # seconds -- CCEL robots.txt crawl-delay

# Import normalizer from build/lib
from ocd_kernel.lib.bible_ref_normalizer import extract_refs_from_text  # noqa: E402
from build.lib._generated_enums import COMMENTARY__META__TRADITION  # noqa: E402
from build.lib.contributors import normalize_contributors  # noqa: E402

# ---------------------------------------------------------------------------
# Volume registry
# All 48 volumes confirmed on CCEL (2026-04-13).
# Format: "ccel_author/ccel_work" -> {title, author, author_death_year, tradition,
#                                      books, pattern}
# tradition: list of values from the OCD schema enum
# struct_pattern:
#   "passage_in_text"  -- verse ref extracted from body text (most volumes)
#   "passage_in_title" -- verse ref extracted from div1.title attribute (Matthew)
#   "psalms"           -- div1 per Psalm, chapter-level (Psalms vols)
#   "multi_book"       -- div1 per OT book, div2 per section (Twelve Prophets)
# ---------------------------------------------------------------------------

VOLUMES = {
    "dods/expositor1":         {"title": "The Book of Genesis",                       "author": "Marcus Dods",               "author_death_year": 1909, "tradition": ["presbyterian"],                  "books": ["Gen"],                              "pattern": "passage_in_text"},
    "chadwick/expositor2":     {"title": "The Book of Exodus",                        "author": "G.A. Chadwick",             "author_death_year": 1923, "tradition": ["wesleyan"],                      "books": ["Exod"],                             "pattern": "passage_in_text"},
    "kellogg/expositor3":      {"title": "The Book of Leviticus",                     "author": "Samuel H. Kellogg",         "author_death_year": 1899, "tradition": ["presbyterian"],                  "books": ["Lev"],                              "pattern": "passage_in_text"},
    "watson_ra/expositornum":  {"title": "The Book of Numbers",                       "author": "R.A. Watson",               "author_death_year": 1921, "tradition": ["presbyterian"],                  "books": ["Num"],                              "pattern": "passage_in_text"},
    "harper/expositordeut":    {"title": "The Book of Deuteronomy",                   "author": "Andrew Harper",             "author_death_year": 1924, "tradition": ["presbyterian"],                  "books": ["Deut"],                             "pattern": "passage_in_text"},
    "blaikie/expositorjosh":   {"title": "The Book of Joshua",                        "author": "William G. Blaikie",        "author_death_year": 1899, "tradition": ["presbyterian"],                  "books": ["Josh"],                             "pattern": "passage_in_text"},
    "watson_ra/expositor7":    {"title": "Judges and Ruth",                           "author": "R.A. Watson",               "author_death_year": 1921, "tradition": ["presbyterian"],                  "books": ["Judg", "Ruth"],                     "pattern": "multi_book"},
    # Note: Blaikie cites scripture as "1 Samuel i 1—18" (roman numeral, no dot) — not tagged
    # as <scripRef> in the early chapters. Cross-ref coverage ~53% is a source characteristic.
    "blaikie/expositor8":      {"title": "The First Book of Samuel",                  "author": "William G. Blaikie",        "author_death_year": 1899, "tradition": ["presbyterian"],                  "books": ["1Sam"],                             "pattern": "passage_in_text"},
    "blaikie/expositor2sam":   {"title": "The Second Book of Samuel",                 "author": "William G. Blaikie",        "author_death_year": 1899, "tradition": ["presbyterian"],                  "books": ["2Sam"],                             "pattern": "passage_in_text"},
    "farrar/expositor1kings":  {"title": "The First Book of Kings",                   "author": "Frederic W. Farrar",        "author_death_year": 1903, "tradition": ["anglican"],                      "books": ["1Kgs"],                             "pattern": "passage_in_text"},
    "farrar/expositor2kings":  {"title": "The Second Book of Kings",                  "author": "Frederic W. Farrar",        "author_death_year": 1903, "tradition": ["anglican"],                      "books": ["2Kgs"],                             "pattern": "passage_in_text"},
    "bennett/expositor10":     {"title": "The Books of Chronicles",                   "author": "W.H. Bennett",              "author_death_year": 1920, "tradition": ["nonconformist"],                 "books": ["1Chr", "2Chr"],                     "pattern": "passage_in_text"},
    # adeney/expositoreznehes: div1 elements are lecture-chapters (I-XXXV), NOT per-book
    # divisions. Chapter ranges map to books: I-XIV=Ezra, XV-XXX=Neh, XXXI-XXXV=Esth.
    "adeney/expositoreznehes": {"title": "Ezra, Nehemiah, and Esther",               "author": "Walter F. Adeney",          "author_death_year": 1920, "tradition": ["nonconformist"],                 "books": ["Ezra", "Neh", "Esth"],              "pattern": "chapter_range_book", "chapter_book_ranges": [("Ezra", 1, 14), ("Neh", 15, 30), ("Esth", 31, 35)]},
    "watson_ra/expositorjob":  {"title": "The Book of Job",                           "author": "R.A. Watson",               "author_death_year": 1921, "tradition": ["presbyterian"],                  "books": ["Job"],                              "pattern": "passage_in_text"},
    "maclaren/expositorpsalms1": {"title": "The Psalms, Volume I (Ps 1-72)",         "author": "Alexander Maclaren",        "author_death_year": 1910, "tradition": ["baptist"],                       "books": ["Ps"],                               "pattern": "psalms"},
    "maclaren/expositorpsalms2": {"title": "The Psalms, Volume II (Ps 73-119)",      "author": "Alexander Maclaren",        "author_death_year": 1910, "tradition": ["baptist"],                       "books": ["Ps"],                               "pattern": "psalms"},
    "maclaren/expositorpsalms3": {"title": "The Psalms, Volume III (Ps 120-150)",    "author": "Alexander Maclaren",        "author_death_year": 1910, "tradition": ["baptist"],                       "books": ["Ps"],                               "pattern": "psalms"},
    "horton/expositorprov":    {"title": "The Book of Proverbs",                      "author": "Robert F. Horton",          "author_death_year": 1934, "tradition": ["nonconformist"],                 "books": ["Prov"],                             "pattern": "passage_in_text"},
    "cox_s/expositoreccl":     {"title": "The Book of Ecclesiastes",                  "author": "Samuel Cox",                "author_death_year": 1893, "tradition": ["baptist"],                       "books": ["Eccl"],                             "pattern": "passage_in_text"},
    "adeney/expositorsonglament": {"title": "The Song of Solomon and Lamentations",   "author": "Walter F. Adeney",          "author_death_year": 1920, "tradition": ["nonconformist"],                 "books": ["Song", "Lam"],                      "pattern": "multi_book"},
    "smith_ga/expositorisa1":  {"title": "Isaiah, Volume I (Isa 1-39)",               "author": "George Adam Smith",         "author_death_year": 1942, "tradition": ["presbyterian"],                  "books": ["Isa"],                              "pattern": "passage_in_text"},
    "smith_ga/expositorisa2":  {"title": "Isaiah, Volume II (Isa 40-66)",             "author": "George Adam Smith",         "author_death_year": 1942, "tradition": ["presbyterian"],                  "books": ["Isa"],                              "pattern": "passage_in_text"},
    "ball/expositorjer1":      {"title": "The Book of Jeremiah, Volume I",            "author": "C.J. Ball",                 "author_death_year": 1924, "tradition": ["anglican"],                      "books": ["Jer"],                              "pattern": "passage_in_text"},
    "bennett/expositorjer2":   {"title": "The Book of Jeremiah, Volume II",           "author": "W.H. Bennett",              "author_death_year": 1920, "tradition": ["nonconformist"],                 "books": ["Jer"],                              "pattern": "passage_in_text"},
    "skinner/expositorezek":   {"title": "The Book of Ezekiel",                       "author": "John Skinner",              "author_death_year": 1925, "tradition": ["presbyterian"],                  "books": ["Ezek"],                             "pattern": "passage_in_text"},
    "farrar/expositordan":     {"title": "The Book of Daniel",                        "author": "Frederic W. Farrar",        "author_death_year": 1903, "tradition": ["anglican"],                      "books": ["Dan"],                              "pattern": "passage_in_text"},
    # Note: CCEL digitization of expositorprophets1 contains only Amos, Hosea, Micah
    # (not Joel, Jonah, Obadiah as in the print edition)
    "smith_ga/expositorprophets1": {"title": "The Twelve Prophets, Volume I",         "author": "George Adam Smith",         "author_death_year": 1942, "tradition": ["presbyterian"],                  "books": ["Amos", "Hos", "Mic"],               "pattern": "multi_book"},
    "gibson/expositormatt":    {"title": "The Gospel of St. Matthew",                 "author": "J. Monro Gibson",           "author_death_year": 1921, "tradition": ["presbyterian"],                  "books": ["Matt"],                             "pattern": "passage_in_title"},
    "chadwick/mark":           {"title": "The Gospel of St. Mark",                    "author": "G.A. Chadwick",             "author_death_year": 1923, "tradition": ["wesleyan"],                      "books": ["Mark"],                             "pattern": "passage_in_section_title"},
    "burton/expositorluke":    {"title": "The Gospel of St. Luke",                    "author": "Henry Burton",              "author_death_year": 1898, "tradition": ["baptist"],                       "books": ["Luke"],                             "pattern": "passage_in_text"},
    "dods/expositorjohn1":     {"title": "The Gospel of St. John, Volume I",          "author": "Marcus Dods",               "author_death_year": 1909, "tradition": ["presbyterian"],                  "books": ["John"],                             "pattern": "passage_in_text"},
    "dods/expositorjohn2":     {"title": "The Gospel of St. John, Volume II",         "author": "Marcus Dods",               "author_death_year": 1909, "tradition": ["presbyterian"],                  "books": ["John"],                             "pattern": "passage_in_text"},
    "stokes/expositoracts1":   {"title": "The Acts of the Apostles, Volume I",        "author": "G.T. Stokes",               "author_death_year": 1898, "tradition": ["anglican"],                      "books": ["Acts"],                             "pattern": "passage_in_text"},
    "stokes/expositoracts2":   {"title": "The Acts of the Apostles, Volume II",       "author": "G.T. Stokes",               "author_death_year": 1898, "tradition": ["anglican"],                      "books": ["Acts"],                             "pattern": "passage_in_text"},
    "moule/expositorromans":   {"title": "The Epistle to the Romans",                 "author": "H.C.G. Moule",              "author_death_year": 1920, "tradition": ["evangelical"],                   "books": ["Rom"],                              "pattern": "passage_in_text"},
    "dods/expositor1cor":      {"title": "The First Epistle to the Corinthians",      "author": "Marcus Dods",               "author_death_year": 1909, "tradition": ["presbyterian"],                  "books": ["1Cor"],                             "pattern": "passage_in_text"},
    "denney/expositor2cor":    {"title": "The Second Epistle to the Corinthians",     "author": "James Denney",              "author_death_year": 1917, "tradition": ["presbyterian"],                  "books": ["2Cor"],                             "pattern": "passage_in_text"},
    "findlay/expositorgal":    {"title": "The Epistle to the Galatians",              "author": "G.G. Findlay",              "author_death_year": 1919, "tradition": ["wesleyan"],                      "books": ["Gal"],                              "pattern": "passage_in_div1_title"},
    "findlay/expositoreph":    {"title": "The Epistle to the Ephesians",              "author": "G.G. Findlay",              "author_death_year": 1919, "tradition": ["wesleyan"],                      "books": ["Eph"],                              "pattern": "passage_in_text"},
    "rainy/expositorphil":     {"title": "The Epistle to the Philippians",            "author": "Robert Rainy",              "author_death_year": 1906, "tradition": ["presbyterian"],                  "books": ["Phil"],                             "pattern": "passage_in_text"},
    "maclaren/expositorcolphm": {"title": "The Epistles to the Colossians and Philemon", "author": "Alexander Maclaren",    "author_death_year": 1910, "tradition": ["baptist"],                       "books": ["Col", "Phlm"],                      "pattern": "multi_book"},
    "denney/expositorthess":   {"title": "The Epistles to the Thessalonians",         "author": "James Denney",              "author_death_year": 1917, "tradition": ["presbyterian"],                  "books": ["1Thess", "2Thess"],                 "pattern": "multi_book"},
    "plummer/expositorpastoral": {"title": "The Pastoral Epistles",                   "author": "Alfred Plummer",            "author_death_year": 1926, "tradition": ["anglican"],                      "books": ["1Tim", "2Tim", "Titus"],            "pattern": "multi_book"},
    "edwards_tc/expositorheb": {"title": "The Epistle to the Hebrews",               "author": "Thomas Charles Edwards",    "author_death_year": 1900, "tradition": ["calvinist-methodist"],            "books": ["Heb"],                              "pattern": "passage_in_text"},
    "plummer/expositorjamesjude": {"title": "The General Epistles of St. James and St. Jude", "author": "Alfred Plummer",  "author_death_year": 1926, "tradition": ["anglican"],                      "books": ["Jas", "Jude"],                      "pattern": "multi_book"},
    "lumby/expositorpeter":    {"title": "The Epistles of St. Peter",                 "author": "J. Rawson Lumby",           "author_death_year": 1895, "tradition": ["anglican"],                      "books": ["1Pet", "2Pet"],                     "pattern": "multi_book"},
    "milligan/expositorrev":   {"title": "The Book of Revelation",                    "author": "William Milligan",          "author_death_year": 1893, "tradition": ["presbyterian"],                  "books": ["Rev"],                              "pattern": "passage_in_text"},
}


def _validate_work_configs() -> None:
    for volume_key, cfg in VOLUMES.items():
        for t in cfg.get("tradition", []):
            assert t in COMMENTARY__META__TRADITION, f"{volume_key}: invalid tradition {t!r}"


_validate_work_configs()

# ---------------------------------------------------------------------------
# Book reference tables (OSIS codes -> canonical names and numbers)
# ---------------------------------------------------------------------------

OSIS_TO_NAME = {
    "Gen": "Genesis", "Exod": "Exodus", "Lev": "Leviticus", "Num": "Numbers",
    "Deut": "Deuteronomy", "Josh": "Joshua", "Judg": "Judges", "Ruth": "Ruth",
    "1Sam": "1 Samuel", "2Sam": "2 Samuel", "1Kgs": "1 Kings", "2Kgs": "2 Kings",
    "1Chr": "1 Chronicles", "2Chr": "2 Chronicles", "Ezra": "Ezra", "Neh": "Nehemiah",
    "Esth": "Esther", "Job": "Job", "Ps": "Psalms", "Prov": "Proverbs",
    "Eccl": "Ecclesiastes", "Song": "Song of Solomon", "Isa": "Isaiah",
    "Jer": "Jeremiah", "Lam": "Lamentations", "Ezek": "Ezekiel", "Dan": "Daniel",
    "Hos": "Hosea", "Joel": "Joel", "Amos": "Amos", "Obad": "Obadiah",
    "Jonah": "Jonah", "Mic": "Micah", "Nah": "Nahum", "Hab": "Habakkuk",
    "Zeph": "Zephaniah", "Hag": "Haggai", "Zech": "Zechariah", "Mal": "Malachi",
    "Matt": "Matthew", "Mark": "Mark", "Luke": "Luke", "John": "John",
    "Acts": "Acts", "Rom": "Romans", "1Cor": "1 Corinthians", "2Cor": "2 Corinthians",
    "Gal": "Galatians", "Eph": "Ephesians", "Phil": "Philippians", "Col": "Colossians",
    "1Thess": "1 Thessalonians", "2Thess": "2 Thessalonians", "1Tim": "1 Timothy",
    "2Tim": "2 Timothy", "Titus": "Titus", "Phlm": "Philemon", "Heb": "Hebrews",
    "Jas": "James", "1Pet": "1 Peter", "2Pet": "2 Peter", "1John": "1 John",
    "2John": "2 John", "3John": "3 John", "Jude": "Jude", "Rev": "Revelation",
}

OSIS_BOOK_NUMBER = {
    "Gen": 1, "Exod": 2, "Lev": 3, "Num": 4, "Deut": 5, "Josh": 6,
    "Judg": 7, "Ruth": 8, "1Sam": 9, "2Sam": 10, "1Kgs": 11, "2Kgs": 12,
    "1Chr": 13, "2Chr": 14, "Ezra": 15, "Neh": 16, "Esth": 17, "Job": 18,
    "Ps": 19, "Prov": 20, "Eccl": 21, "Song": 22, "Isa": 23, "Jer": 24,
    "Lam": 25, "Ezek": 26, "Dan": 27, "Hos": 28, "Joel": 29, "Amos": 30,
    "Obad": 31, "Jonah": 32, "Mic": 33, "Nah": 34, "Hab": 35, "Zeph": 36,
    "Hag": 37, "Zech": 38, "Mal": 39,
    "Matt": 40, "Mark": 41, "Luke": 42, "John": 43, "Acts": 44, "Rom": 45,
    "1Cor": 46, "2Cor": 47, "Gal": 48, "Eph": 49, "Phil": 50, "Col": 51,
    "1Thess": 52, "2Thess": 53, "1Tim": 54, "2Tim": 55, "Titus": 56,
    "Phlm": 57, "Heb": 58, "Jas": 59, "1Pet": 60, "2Pet": 61, "1John": 62,
    "2John": 63, "3John": 64, "Jude": 65, "Rev": 66,
}

# KJV verse counts per Psalm (used to build verse_range_osis for Psalms pattern)
PSALM_VERSE_COUNTS = [
    6, 12, 8, 8, 12, 10, 17, 9, 20, 18, 7, 8, 6, 7, 5, 11, 15, 50, 14, 9,
    13, 31, 6, 10, 22, 12, 14, 9, 11, 12, 24, 11, 22, 22, 28, 12, 40, 22,
    13, 17, 13, 11, 5, 26, 17, 11, 9, 14, 20, 23, 19, 9, 6, 7, 23, 13, 11,
    11, 17, 12, 8, 12, 11, 10, 13, 20, 7, 35, 36, 5, 24, 20, 28, 23, 10, 12,
    20, 72, 13, 19, 16, 8, 18, 12, 13, 17, 7, 18, 52, 17, 16, 15, 5, 23, 11,
    13, 12, 9, 9, 5, 8, 28, 22, 35, 45, 48, 43, 13, 31, 7, 10, 10, 9, 8, 18,
    19, 2, 29, 176, 7, 8, 9, 4, 8, 5, 6, 5, 6, 8, 8, 3, 18, 3, 3, 21, 26, 9,
    8, 24, 14, 10, 8, 12, 15, 21, 10, 20, 14, 9, 6,
]  # 150 entries

# ---------------------------------------------------------------------------
# ThML HTML entity preprocessing
# ---------------------------------------------------------------------------

THML_ENTITY_MAP = {
    "&mdash;": "\u2014", "&ndash;": "\u2013", "&lsquo;": "\u2018",
    "&rsquo;": "\u2019", "&ldquo;": "\u201C", "&rdquo;": "\u201D",
    "&nbsp;": "\u00A0", "&hellip;": "\u2026", "&emdash;": "\u2014",
    "&copy;": "\u00A9", "&reg;": "\u00AE", "&trade;": "\u2122",
    "&deg;": "\u00B0", "&para;": "\u00B6", "&sect;": "\u00A7",
    "&dagger;": "\u2020", "&Dagger;": "\u2021", "&bull;": "\u2022",
    "&prime;": "\u2032", "&Prime;": "\u2033", "&oline;": "\u203E",
    "&frasl;": "\u2044", "&spades;": "\u2660", "&clubs;": "\u2663",
    "&hearts;": "\u2665", "&diams;": "\u2666",
    "&aelig;": "\u00E6", "&AElig;": "\u00C6",
    "&oslash;": "\u00F8", "&Oslash;": "\u00D8",
    "&agrave;": "\u00E0", "&aacute;": "\u00E1", "&acirc;": "\u00E2",
    "&atilde;": "\u00E3", "&auml;": "\u00E4", "&aring;": "\u00E5",
    "&egrave;": "\u00E8", "&eacute;": "\u00E9", "&ecirc;": "\u00EA",
    "&euml;": "\u00EB", "&igrave;": "\u00EC", "&iacute;": "\u00ED",
    "&icirc;": "\u00EE", "&iuml;": "\u00EF", "&ograve;": "\u00F2",
    "&oacute;": "\u00F3", "&ocirc;": "\u00F4", "&otilde;": "\u00F5",
    "&ouml;": "\u00F6", "&ugrave;": "\u00F9", "&uacute;": "\u00FA",
    "&ucirc;": "\u00FB", "&uuml;": "\u00FC", "&yacute;": "\u00FD",
    "&yuml;": "\u00FF", "&Agrave;": "\u00C0", "&Aacute;": "\u00C1",
    "&Acirc;": "\u00C2", "&Atilde;": "\u00C3", "&Auml;": "\u00C4",
    "&Aring;": "\u00C5", "&Egrave;": "\u00C8", "&Eacute;": "\u00C9",
    "&Ecirc;": "\u00CA", "&Euml;": "\u00CB", "&Igrave;": "\u00CC",
    "&Iacute;": "\u00CD", "&Icirc;": "\u00CE", "&Iuml;": "\u00CF",
    "&Ograve;": "\u00D2", "&Oacute;": "\u00D3", "&Ocirc;": "\u00D4",
    "&Otilde;": "\u00D5", "&Ouml;": "\u00D6", "&Ugrave;": "\u00D9",
    "&Uacute;": "\u00DA", "&Ucirc;": "\u00DB", "&Uuml;": "\u00DC",
    "&Yacute;": "\u00DD", "&ntilde;": "\u00F1", "&Ntilde;": "\u00D1",
    "&ccedil;": "\u00E7", "&Ccedil;": "\u00C7",
    "&szlig;": "\u00DF", "&thorn;": "\u00FE", "&Thorn;": "\u00DE",
    "&eth;": "\u00F0", "&ETH;": "\u00D0",
    "&acute;": "\u00B4", "&cedil;": "\u00B8", "&uml;": "\u00A8",
    "&macr;": "\u00AF", "&sup1;": "\u00B9", "&sup2;": "\u00B2",
    "&sup3;": "\u00B3", "&frac14;": "\u00BC", "&frac12;": "\u00BD",
    "&frac34;": "\u00BE", "&ordm;": "\u00BA", "&ordf;": "\u00AA",
    "&laquo;": "\u00AB", "&raquo;": "\u00BB", "&not;": "\u00AC",
    "&shy;": "\u00AD", "&plusmn;": "\u00B1", "&times;": "\u00D7",
    "&divide;": "\u00F7", "&micro;": "\u00B5", "&middot;": "\u00B7",
    "&pound;": "\u00A3", "&yen;": "\u00A5", "&euro;": "\u20AC",
    "&cent;": "\u00A2", "&curren;": "\u00A4",
    "&alpha;": "\u03B1", "&beta;": "\u03B2", "&gamma;": "\u03B3",
    "&delta;": "\u03B4", "&epsilon;": "\u03B5", "&zeta;": "\u03B6",
    "&eta;": "\u03B7", "&theta;": "\u03B8", "&iota;": "\u03B9",
    "&kappa;": "\u03BA", "&lambda;": "\u03BB", "&mu;": "\u03BC",
    "&nu;": "\u03BD", "&xi;": "\u03BE", "&omicron;": "\u03BF",
    "&pi;": "\u03C0", "&rho;": "\u03C1", "&sigma;": "\u03C3",
    "&tau;": "\u03C4", "&upsilon;": "\u03C5", "&phi;": "\u03C6",
    "&chi;": "\u03C7", "&psi;": "\u03C8", "&omega;": "\u03C9",
    "&Alpha;": "\u0391", "&Beta;": "\u0392", "&Gamma;": "\u0393",
    "&Delta;": "\u0394", "&Epsilon;": "\u0395", "&Zeta;": "\u0396",
    "&Eta;": "\u0397", "&Theta;": "\u0398", "&Iota;": "\u0399",
    "&Kappa;": "\u039A", "&Lambda;": "\u039B", "&Mu;": "\u039C",
    "&Nu;": "\u039D", "&Xi;": "\u039E", "&Omicron;": "\u039F",
    "&Pi;": "\u03A0", "&Rho;": "\u03A1", "&Sigma;": "\u03A3",
    "&Tau;": "\u03A4", "&Upsilon;": "\u03A5", "&Phi;": "\u03A6",
    "&Chi;": "\u03A7", "&Psi;": "\u03A8", "&Omega;": "\u03A9",
}


def preprocess_thml(raw_bytes: bytes) -> str:
    """
    Strip DOCTYPE declaration, replace HTML entities with Unicode equivalents,
    and return a clean XML string suitable for ElementTree.fromstring().
    """
    text = raw_bytes.decode("utf-8", errors="replace")
    # Strip DOCTYPE to avoid external DTD fetch
    text = re.sub(r"<!DOCTYPE[^>]*>", "", text, flags=re.IGNORECASE | re.DOTALL)
    # Replace HTML entities
    for entity, char in THML_ENTITY_MAP.items():
        text = text.replace(entity, char)
    # Remove remaining unresolved HTML entities (safety net)
    text = re.sub(r"&[a-zA-Z][a-zA-Z0-9]*;", "", text)
    return text


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def get_all_text(elem) -> str:
    """Recursively collect all text from an element, skipping <note> footnotes and <pb> page breaks."""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if child.tag in ("note", "pb"):
            # footnotes and page breaks -- skip content but keep tail
            if child.tail:
                parts.append(child.tail)
            continue
        parts.append(get_all_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def clean_text(text: str) -> str:
    """Collapse whitespace and strip."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Front/back matter detection
# ---------------------------------------------------------------------------

_SKIP_TITLES = frozenset([
    "title page", "preface", "epigraph", "chronological table",
    "introduction", "indexes", "index of passages and texts",
    "index", "contents", "table of contents", "bibliography",
    "general introduction",
])

_SKIP_H2_TEXTS = frozenset([
    "preface", "introduction", "indexes", "index", "contents",
    "chronological table",
])


def _is_front_back_matter(div: ET.Element) -> bool:
    """Return True if this div should be skipped (front/back matter)."""
    title = div.get("title", "").strip().lower()
    if title in _SKIP_TITLES:
        return True
    # Check first h2 element
    for child in div:
        if child.tag in ("h1", "h2"):
            h_text = "".join(child.itertext()).strip().lower()
            if h_text in _SKIP_H2_TEXTS:
                return True
            break  # only check first heading
    return False


# ---------------------------------------------------------------------------
# Verse reference extraction
# ---------------------------------------------------------------------------

# Roman numeral pattern for chapter numbers (i, ii, iii, iv, ... lxxx etc.)
_ROMAN_RE = r"(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})"

# Book name patterns commonly found in Expositor's Bible text
# Covers: "Romans", "Rom.", "1 Samuel", "1 Sam.", "Amos", "Hos.", etc.
# Also handles roman-numeral chapters: "Romans i. 1-7", "1 Samuel iii."
_VERSE_HEAD_RE = re.compile(
    r"\b"
    r"(?:(?:[123]\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)"  # book name (optional digit prefix)
    r"(?:\s+of\s+[A-Z][a-z]+)?"                          # "Song of Solomon"
    r"\s+"
    r"(?:"
        r"(?:" + _ROMAN_RE + r")"                         # roman numeral chapter
        r"|(?:[0-9]+)"                                    # or arabic chapter
    r")"
    r"(?:"
        r"[.\s]+\d+"                                      # verse (after dot or space)
        r"(?:\s*[-\u2013\u2014]\s*"                       # optional range
            r"(?:" + _ROMAN_RE + r"|[0-9]+)"              # end chapter
            r"(?:[.\s]+\d+)?"                             # end verse
        r")?"
    r")?",
    re.IGNORECASE,
)

# Pattern B: extract passage from Matthew-style div1.title "(Matt. III. 1-12.)"
_TITLE_PASSAGE_RE = re.compile(
    r"\(([A-Z][a-z]+\.?\s+(?:[IVXLC]+|[0-9]+)[.\s\-0-9IVXLC,;]*)\)",
    re.IGNORECASE,
)

# Psalm title: "Psalm I." or "Psalm 23."
_PSALM_TITLE_RE = re.compile(r"Psalm(?:s)?\s+([IVXLC]+|[0-9]+)\.?", re.IGNORECASE)

# Multi-book div1 title to OSIS map (Twelve Prophets, Judges+Ruth, Chronicles, etc.)
_BOOK_TITLE_TO_OSIS = {
    "amos": "Amos", "hosea": "Hos", "micah": "Mic", "joel": "Joel",
    "jonah": "Jonah", "obadiah": "Obad",
    "nahum": "Nah", "zephaniah": "Zeph", "habakkuk": "Hab",
    "haggai": "Hag", "zechariah": "Zech", "malachi": "Mal",
    # Ruth / Judges in watson_ra/expositor7 (div1 titles include "The Book of ..." prefix)
    "ruth": "Ruth", "judges": "Judg",
    "the book of judges": "Judg", "the book of ruth": "Ruth",
    # Chronicles in bennett/expositor10
    "1 chronicles": "1Chr", "2 chronicles": "2Chr",
    "first chronicles": "1Chr", "second chronicles": "2Chr",
    # Ezra/Neh/Esther in adeney/expositoreznehes
    "ezra": "Ezra", "nehemiah": "Neh", "esther": "Esth",
    # Song/Lamentations in adeney/expositorsonglament (div1 titles use "The ... of ..." form)
    "song of solomon": "Song", "song": "Song",
    "the song of solomon": "Song",
    "lamentations": "Lam",
    "the lamentations of jeremiah": "Lam",
    # Colossians/Philemon in maclaren/expositorcolphm
    "colossians": "Col", "philemon": "Phlm",
    # 1 Thess / 2 Thess in denney/expositorthess (div1 titles include "The ... Epistle" prefix)
    "1 thessalonians": "1Thess", "2 thessalonians": "2Thess",
    "first thessalonians": "1Thess", "second thessalonians": "2Thess",
    "the first epistle to the thessalonians.": "1Thess",
    "the second epistle to the thessalonians.": "2Thess",
    # Pastoral Epistles — div1 titles in plummer/expositorpastoral include trailing dot
    "1 timothy": "1Tim", "1 timothy.": "1Tim",
    "2 timothy": "2Tim", "2 timothy.": "2Tim",
    "titus": "Titus", "titus.": "Titus",
    # James / Jude — div1 titles in plummer/expositorjamesjude use full "Epistle of" form
    "james": "Jas", "the epistle of st. james.": "Jas",
    "jude": "Jude", "the general epistle of st. jude.": "Jude",
    # Peter (div1 titles use "The First/Second Epistle of St. Peter." format)
    "1 peter": "1Pet", "2 peter": "2Pet",
    "first peter": "1Pet", "second peter": "2Pet",
    "the first epistle of st. peter.": "1Pet",
    "the second epistle of st. peter.": "2Pet",
}


def _roman_to_int(s: str) -> int:
    """Convert a roman numeral string to integer. Returns 0 on failure."""
    s = s.lower().strip()
    vals = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    result = 0
    prev = 0
    for ch in reversed(s):
        if ch not in vals:
            return 0
        v = vals[ch]
        if v < prev:
            result -= v
        else:
            result += v
            prev = v
    return result


def _book_from_chapter_ranges(
    chapter_num: int,
    chapter_book_ranges: list[tuple[str, int, int]],
) -> str | None:
    """Return the OSIS book code for a commentary chapter number, using the
    volume's chapter_book_ranges config (list of (osis, start_ch, end_ch) tuples).
    Returns None if chapter_num falls outside all defined ranges.
    """
    for osis, start, end in chapter_book_ranges:
        if start <= chapter_num <= end:
            return osis
    return None


def extract_passage_from_text(text: str) -> str | None:
    """
    Extract the first passage heading from the first 600 chars of a div's text content.
    Returns the raw passage string (e.g. "Romans i. 1-7") or None if not found.
    """
    m = _VERSE_HEAD_RE.search(text[:600])
    if m:
        return m.group(0).strip()
    return None


def extract_passage_from_title(title: str) -> str | None:
    """
    Extract passage from Matthew-style div1.title like 'III. His Herald (Matt. III. 1-12.)'.
    Returns the raw passage string inside the parentheses, or None.
    """
    m = _TITLE_PASSAGE_RE.search(title)
    if m:
        return m.group(1).strip()
    return None


def passage_to_osis(raw_passage: str, default_osis: str) -> tuple[int, str, str]:
    """
    Parse a raw passage string (e.g. "Romans i. 1-7", "1 Samuel iii.", "Matt. III. 1-12.")
    into (chapter, verse_range, verse_range_osis).

    default_osis: the volume's primary book OSIS code (used if book name not in passage)

    Cross-chapter ranges (e.g. "xxvii. 57-xxviii. 15") are stored as the full OSIS range
    "Matt.27.57-Matt.28.15". Same-chapter ranges where end < start are truncated to the
    start verse (indicates a parse error).

    Returns (chapter, verse_range, verse_range_osis).
    If parsing fails, returns (0, "1", f"{default_osis}.1.1").
    """
    # Normalise: replace en/em dash with hyphen, remove trailing dots
    raw = raw_passage.strip().rstrip(".")
    raw = re.sub(r"[\u2013\u2014]", "-", raw)

    # Try to extract: START_CHAP.START_VERSE[-END_CHAP.END_VERSE]
    # Groups: (1)=start_chap  (2)=start_verse  (3)=end_chap+sep or None  (4)=end_verse or None
    chap_match = re.search(
        r"(?:^|\s)(" + _ROMAN_RE + r"|[0-9]+)[.\s]+(\d+)"
        r"\s*(?:-\s*((?:" + _ROMAN_RE + r"|[0-9]+)[.\s]+)?(\d+))?",
        raw,
        re.IGNORECASE,
    )
    if not chap_match:
        # Try chapter-only (no explicit verse): "1 Samuel iii."
        chap_only = re.search(r"(?:^|\s)(" + _ROMAN_RE + r"|[0-9]+)\s*$", raw, re.IGNORECASE)
        if chap_only:
            raw_ch = chap_only.group(1)
            ch = _roman_to_int(raw_ch) if not raw_ch.isdigit() else int(raw_ch)
            if ch > 0:
                return ch, "1", f"{default_osis}.{ch}.1"
        return 0, "1", f"{default_osis}.1.1"

    raw_ch = chap_match.group(1)
    raw_v1 = chap_match.group(2)
    raw_ch2_part = chap_match.group(3)  # e.g. "xxviii. " or None (same-chapter range)
    raw_v2 = chap_match.group(4)        # end verse or None

    ch = _roman_to_int(raw_ch) if not raw_ch.isdigit() else int(raw_ch)
    v1 = int(raw_v1) if raw_v1 else 1

    if ch == 0:
        return 0, "1", f"{default_osis}.1.1"

    if raw_v2 is None:
        # Single verse reference
        verse_range = str(v1)
        verse_range_osis = f"{default_osis}.{ch}.{v1}"
        return ch, verse_range, verse_range_osis

    v2 = int(raw_v2)

    if raw_ch2_part:
        # Cross-chapter range: extract the end chapter number
        m2 = re.search(r"(" + _ROMAN_RE + r"|[0-9]+)", raw_ch2_part, re.IGNORECASE)
        if m2:
            raw_ch2 = m2.group(1)
            ch2 = _roman_to_int(raw_ch2) if not raw_ch2.isdigit() else int(raw_ch2)
        else:
            ch2 = ch
    else:
        ch2 = ch

    if ch2 > ch:
        # Valid cross-chapter range -- verse_range uses start verse only to avoid
        # start > end validation failure (full range is in verse_range_osis)
        verse_range = str(v1)
        verse_range_osis = f"{default_osis}.{ch}.{v1}-{default_osis}.{ch2}.{v2}"
    elif ch2 == ch and v2 >= v1:
        # Valid same-chapter range
        verse_range = f"{v1}-{v2}"
        verse_range_osis = f"{default_osis}.{ch}.{v1}-{default_osis}.{ch}.{v2}"
    else:
        # v2 < v1 with same chapter -- likely a parse artefact; use single start verse
        verse_range = str(v1)
        verse_range_osis = f"{default_osis}.{ch}.{v1}"

    return ch, verse_range, verse_range_osis


# ---------------------------------------------------------------------------
# Section-title passage pattern
# ---------------------------------------------------------------------------
# Chadwick's Gospel of Mark keys each section's passage in the div2 section
# *title* ("The Temptation. Vss. 12,13", "At the Jordan. 7-11") rather than in
# inline <scripRef> tags, with the Bible chapter coming from the enclosing div1
# ("Chapter I"). The four existing patterns (A-D) miss this entirely, which is
# why the volume parsed to zero entries before this pattern was added.

# A single verse reference inside a section-title spec: optional "chap:" prefix,
# a start verse, and an optional "-[chap:]verse" range end.
_SECTION_REF_RE = re.compile(r"(?:(\d+):)?(\d+)(?:\s*-\s*(?:(\d+):)?(\d+))?")

# The trailing verse spec of a section title, after an optional "Vss."/"Vs." marker.
# Anchored at end-of-string; the character class stops the match from crossing
# back into topical prose words.
_SECTION_SPEC_RE = re.compile(r"(?:Vss?\.?\s*)?(\d[\d:,\s-]*\d|\d)\s*\.?\s*$")


def _div1_chapter_number(title: str) -> int | None:
    """Bible chapter from an Expositor div1 title like 'Chapter I' / 'Chapter II.'."""
    m = re.search(r"chapter\s+([ivxlcdm]+|\d+)", title or "", re.IGNORECASE)
    if not m:
        return None
    tok = m.group(1)
    n = int(tok) if tok.isdigit() else _roman_to_int(tok.lower())
    return n if n > 0 else None


def section_title_to_osis(
    title: str, default_chapter: int, vol_osis: str
) -> tuple[int, str, str] | None:
    """Parse a div2 section title's verse spec into (chapter, verse_range,
    verse_range_osis), using ``default_chapter`` (the enclosing div1's Bible
    chapter) when the title states no explicit chapter.

    Returns None when the title carries no verse spec (chapter intro or
    continuation sections), so the caller can merge or skip rather than mis-key.
    Multiple disjoint refs collapse to a bounding span (first start .. last end);
    the original title is preserved on the entry so the precise refs aren't lost.
    """
    if not title:
        return None
    norm = re.sub(r"[–—]", "-", title)
    # Drop a trailing editorial parenthetical like "(R.V.)" that follows the spec.
    norm = re.sub(r"\s*\([^)]*\)\s*$", "", norm).strip()

    spec_m = _SECTION_SPEC_RE.search(norm)
    if not spec_m:
        return None
    spec = spec_m.group(1)

    points: list[tuple[int, int]] = []
    current = default_chapter
    for m in _SECTION_REF_RE.finditer(spec):
        sc, sv, ec, ev = m.group(1), m.group(2), m.group(3), m.group(4)
        if sv is None:
            continue
        if sc:
            current = int(sc)
        points.append((current, int(sv)))
        if ev is not None:
            if ec:
                current = int(ec)
            points.append((current, int(ev)))

    if not points:
        return None

    sch, sv = points[0]
    ech, ev = points[-1]
    if sch == ech and sv == ev:
        return sch, str(sv), f"{vol_osis}.{sch}.{sv}"
    if sch == ech:
        return sch, f"{sv}-{ev}", f"{vol_osis}.{sch}.{sv}-{vol_osis}.{sch}.{ev}"
    # Cross-chapter span: verse_range carries the start verse only (mirrors
    # passage_to_osis) to avoid start>end validation failures.
    return sch, str(sv), f"{vol_osis}.{sch}.{sv}-{vol_osis}.{ech}.{ev}"


# ---------------------------------------------------------------------------
# Cross-reference extraction
# ---------------------------------------------------------------------------

# Known CCEL osisRef encoding errors.  Maps bad ref → corrected ref (or None = drop).
# Each entry is documented with the source evidence.
#
# NOTE on propagation: corrections here apply during extraction (new parse runs).
# The merge logic in _write_output() skips entries whose entry_id already exists in
# the output file.  To apply corrections to an already-written file you must either:
#   (a) delete the output file and re-run the volume, OR
#   (b) patch the JSON directly (see post-pilot fix session, 2026-04-14).
_CCEL_OSISREF_CORRECTIONS: dict[str, str | None] = {
    # smith_ga/expositorprophets1 (Amos 3):
    #   Source text: "Job xl. 26 (Heb.), xli. 2 (Eng.)"  — CCEL used Hebrew verse number.
    #   Hebrew Job 40:26 = English Job 41:2 (chapter/verse boundary differs in MT vs English).
    "Job.40.26": "Job.41.2",
    # smith_ga/expositorprophets1 (Amos 4):
    #   Source text: "2 Sam. ix. 45" — comma dropped from "ix. 4, 5" during CCEL encoding.
    #   Lo-Debar is mentioned in 2 Sam 9:4 and 9:5; keep the first verse (9:4 is valid).
    "2Sam.9.45": "2Sam.9.4",
    # smith_ga/expositorprophets1 (Hosea 1):
    #   Source text: "Psalm xxviii. 13" — Ps.28 has only 9 verses; source error unverifiable.
    #   Context about God's compassion, but correct ref cannot be determined without the original.
    "Ps.28.13": None,
    # maclaren/expositorpsalms1 (Ps 37):
    #   Source text: "Deut. xii. 44" — Deut.12 has only 32 verses; source error unverifiable.
    "Deut.12.44": None,
    # --- Errors from full-corpus run (2026-04-14); all dropped as source errors unverifiable ---
    # farrar/expositor2kings: Ezek.17 has 24 verses; source likely "Ezek. xvii. 25" → off by 1.
    "Ezek.17.25": None,
    # blaikie/expositor2sam: 1Sam.29 has 11 verses; "1 Sam. xxix. 12" → overshoot by 1.
    "1Sam.29.12": None,
    # harper/expositordeut: Exod.24 has 18 verses; "Exod. xxiv. 20" → 2 over end of chapter.
    "Exod.24.20": None,
    # edwards_tc/expositorheb: Ps.24 has 10 verses; "Ps. xxiv. 14" → source error.
    "Ps.24.14": None,
    # smith_ga/expositorisa1: Ps.131 has 3 verses; "Ps. cxxxi. 7" → major overshoot.
    "Ps.131.7": None,
    # ball/expositorjer1: Ps.21 has 13 verses; "Ps. xxi. 14" → overshoot by 1.
    "Ps.21.14": None,
    # bennett/expositorjer2: Isa.50 has 11 verses; "Isa. l. 13" → overshoot by 2.
    "Isa.50.13": None,
    # blaikie/expositorjosh: 1Sam.9 has 27 verses; "1 Sam. ix. 31" → major overshoot.
    "1Sam.9.31": None,
    # kellogg/expositor3: Exod.30 has 38 verses; refs 39 and 40 overshoot end by 1-2.
    "Exod.30.39": None,
    "Exod.30.40": None,
    # maclaren/expositorpsalms2: Hab has 3 chapters; "Hab. v. 10" → no chapter 5.
    "Hab.5.10": None,
    # chadwick/mark (Mark 2, "The Son of Man"): osisRef "Bible:Mark.19.62" — Mark has
    # only 16 chapters. Context (Acts 7:56, Dan 7:13, Matt 26:64 parallels) points to
    # the trial saying Mark 14:62, but the 19->14 encoding error is not certain; drop.
    "Mark.19.62": None,
    # milligan/expositorrev: Ps.14 has 7 verses; range Ps.14.9-Ps.14.15 overshots start.
    "Ps.14.9-Ps.14.15": None,
    # plummer/expositorjamesjude (James): Matt has 28 chapters; "Matt. xlii. 31" → no chapter 42.
    # Likely a typographic error for "Matt. xii. 31" (Matt 12:31, blasphemy of the Holy Spirit).
    "Matt.42.31": None,
    # plummer/expositorjamesjude (Jude): Ps.30 has 12 verses; "Ps. xxx. 28" → overshoot.
    # Correct ref unverifiable without the original 1891 edition.
    "Ps.30.28": None,
}


def extract_cross_refs(div: ET.Element) -> list[str]:
    """
    Extract OSIS cross-references from a div element.
    Priority: osisRef attributes on <scripRef> elements.
    Supplement: extract_refs_from_text() on the plain text body.
    Returns deduplicated list of OSIS ref strings.
    """
    refs: list[str] = []
    seen: set[str] = set()

    # 1. osisRef attributes on scripRef elements
    for sr in div.iter("scripRef"):
        osis_ref = sr.get("osisRef", "")
        for token in osis_ref.split():
            clean = token.replace("Bible:", "").strip()
            if not clean or clean.count(".") < 2:
                continue
            # Apply known CCEL encoding corrections before dedup
            if clean in _CCEL_OSISREF_CORRECTIONS:
                corrected = _CCEL_OSISREF_CORRECTIONS[clean]
                if corrected is None or corrected in seen:
                    continue  # drop or already present
                clean = corrected
            if clean not in seen:
                seen.add(clean)
                refs.append(clean)

    # 2. passage attributes on scripRef (fallback for vols without osisRef)
    for sr in div.iter("scripRef"):
        if not sr.get("osisRef"):
            passage = sr.get("passage", "")
            if passage:
                for osis in extract_refs_from_text(passage):
                    if osis not in seen:
                        seen.add(osis)
                        refs.append(osis)

    # 3. Plain text fallback (catches inline refs not wrapped in scripRef)
    if not refs:
        full_text = get_all_text(div)
        for osis in extract_refs_from_text(full_text):
            if osis not in seen:
                seen.add(osis)
                refs.append(osis)

    return refs


# ---------------------------------------------------------------------------
# Entry builders (one per structural pattern)
# ---------------------------------------------------------------------------

def _make_entry(
    book_osis: str,
    chapter: int,
    verse_range: str,
    verse_range_osis: str,
    raw_passage: str,
    commentary_text: str,
    cross_refs: list[str],
    volume_key: str,
) -> dict:
    """Construct a single OCD commentary entry dict."""
    # Slug: use verse_range_osis with dots replaced by hyphens
    passage_slug = verse_range_osis.replace(".", "-")
    entry_id = f"{RESOURCE_ID}.{passage_slug}"
    return {
        "entry_id": entry_id,
        "book": OSIS_TO_NAME.get(book_osis, book_osis),
        "book_osis": book_osis,
        "book_number": OSIS_BOOK_NUMBER.get(book_osis, 0),
        "chapter": chapter,
        "verse_range": verse_range,
        "verse_range_osis": verse_range_osis,
        "verse_text": None,
        "commentary_text": commentary_text,
        "summary": None,
        "summary_review_status": "withheld",
        "cross_references": cross_refs,
        "word_count": len(commentary_text.split()) if commentary_text.strip() else 0,
    }


def parse_passage_in_text(
    div: ET.Element, vol_osis: str, volume_key: str
) -> dict | None:
    """Pattern A: extract passage from body text. Returns entry dict or None."""
    full_text = get_all_text(div)
    commentary_text = clean_text(full_text)
    if not commentary_text:
        return None

    raw_passage = extract_passage_from_text(full_text)
    if raw_passage is None:
        logging.debug(
            "  Pattern A: no passage in div id=%r title=%r",
            div.get("id"), div.get("title"),
        )
        return None

    chapter, verse_range, verse_range_osis = passage_to_osis(raw_passage, vol_osis)
    if chapter == 0:
        return None

    cross_refs = extract_cross_refs(div)
    return _make_entry(vol_osis, chapter, verse_range, verse_range_osis,
                       raw_passage, commentary_text, cross_refs, volume_key)


def parse_passage_in_title(
    div: ET.Element, vol_osis: str, volume_key: str
) -> dict | None:
    """Pattern B: extract passage from div1.title attribute. Returns entry dict or None."""
    title = div.get("title", "")
    full_text = get_all_text(div)
    commentary_text = clean_text(full_text)
    if not commentary_text:
        return None

    raw_passage = extract_passage_from_title(title)
    if raw_passage is None:
        logging.debug(
            "  Pattern B: no passage in title %r", title,
        )
        return None

    chapter, verse_range, verse_range_osis = passage_to_osis(raw_passage, vol_osis)
    if chapter == 0:
        return None

    cross_refs = extract_cross_refs(div)
    return _make_entry(vol_osis, chapter, verse_range, verse_range_osis,
                       raw_passage, commentary_text, cross_refs, volume_key)


def parse_passage_in_div1_title(
    div: ET.Element, vol_osis: str, volume_key: str
) -> dict | None:
    """Pattern F: passage range stated directly in the div1 title, e.g. Findlay's
    Galatians "The Prologue. Chapter i. 1-10." — one entry per major expository
    division, body = all text under the division. Distinct from Pattern B, whose
    Matthew-style extractor expects a parenthesised "(Matt. III. 1-12.)".
    """
    title = div.get("title", "")
    commentary_text = clean_text(get_all_text(div))
    if not commentary_text:
        return None

    chapter, verse_range, verse_range_osis = passage_to_osis(title, vol_osis)
    if chapter == 0:
        return None

    cross_refs = extract_cross_refs(div)
    return _make_entry(vol_osis, chapter, verse_range, verse_range_osis,
                       title, commentary_text, cross_refs, volume_key)


def parse_psalm_div(div: ET.Element, volume_key: str) -> dict | None:
    """
    Pattern C: Psalms volumes. div1.title = "Psalm I." or "Psalm 23.".
    Verse range = whole psalm (Ps.N.1-Ps.N.last_verse).
    """
    title = div.get("title", "")
    m = _PSALM_TITLE_RE.search(title)
    if not m:
        return None

    raw_num = m.group(1)
    psalm_num = _roman_to_int(raw_num) if not raw_num.isdigit() else int(raw_num)
    if psalm_num < 1 or psalm_num > 150:
        return None

    last_verse = PSALM_VERSE_COUNTS[psalm_num - 1]
    chapter = psalm_num
    verse_range = f"1-{last_verse}"
    verse_range_osis = f"Ps.{psalm_num}.1-Ps.{psalm_num}.{last_verse}"

    full_text = get_all_text(div)
    commentary_text = clean_text(full_text)
    if not commentary_text:
        return None

    cross_refs = extract_cross_refs(div)
    return _make_entry("Ps", chapter, verse_range, verse_range_osis,
                       title, commentary_text, cross_refs, volume_key)


def parse_multi_book_div1(
    div1: ET.Element, volume_key: str
) -> list[dict]:
    """
    Pattern D: multi-book volumes (Twelve Prophets, Judges+Ruth, Chronicles, etc.).
    div1.title gives the Bible book; div2 children are the sections.
    Returns a list of entry dicts (one per div2 with a parseable passage).
    """
    book_title = div1.get("title", "").strip().lower()
    book_osis = _BOOK_TITLE_TO_OSIS.get(book_title)
    if book_osis is None:
        return []

    entries = []
    for div2 in div1:
        if div2.tag != "div2":
            continue
        if _is_front_back_matter(div2):
            continue
        full_text = get_all_text(div2)
        commentary_text = clean_text(full_text)
        if not commentary_text:
            continue

        raw_passage = extract_passage_from_text(full_text)
        if raw_passage is None:
            logging.debug(
                "  Pattern D: no passage in div2 id=%r title=%r",
                div2.get("id"), div2.get("title"),
            )
            continue

        chapter, verse_range, verse_range_osis = passage_to_osis(raw_passage, book_osis)
        if chapter == 0:
            continue

        cross_refs = extract_cross_refs(div2)
        entry = _make_entry(book_osis, chapter, verse_range, verse_range_osis,
                            raw_passage, commentary_text, cross_refs, volume_key)
        entries.append(entry)

    return entries


def parse_section_title_div1(
    div1: ET.Element, vol_osis: str, volume_key: str
) -> list[dict]:
    """Pattern E: div1 = Bible chapter ("Chapter I"); each div2 child is a section
    whose title states the verse range ("The Temptation. Vss. 12,13"). Used for
    Chadwick's Gospel of Mark.

    Sections whose titles carry no verse spec (chapter intros, "... cont."
    continuations) are merged into the preceding section so their commentary is
    retained rather than dropped by entry-id dedup or mis-keyed.
    """
    chapter = _div1_chapter_number(div1.get("title", ""))
    if chapter is None:
        return []

    entries: list[dict] = []
    for div2 in div1.findall("div2"):
        title = div2.get("title", "")
        commentary_text = clean_text(get_all_text(div2))
        if not commentary_text:
            continue

        triple = section_title_to_osis(title, chapter, vol_osis)
        if triple is None:
            if entries:
                prev = entries[-1]
                prev["commentary_text"] = (
                    prev["commentary_text"] + "\n\n" + commentary_text
                ).strip()
                prev["word_count"] = len(prev["commentary_text"].split())
                continue
            # No prior section to merge into: key conservatively to the chapter open.
            triple = (chapter, "1", f"{vol_osis}.{chapter}.1")

        ch, verse_range, verse_range_osis = triple
        cross_refs = extract_cross_refs(div2)
        entries.append(
            _make_entry(vol_osis, ch, verse_range, verse_range_osis,
                        title, commentary_text, cross_refs, volume_key)
        )
    return entries


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_volume(ccel_author: str, ccel_work: str, force: bool = False) -> Path:
    """Download a CCEL ThML XML file to raw/ccel/expositors-bible/. Returns path."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / f"{ccel_author}_{ccel_work}.xml"
    if dest.exists() and not force:
        logging.info("  Cached: %s (%d KB)", dest.name, dest.stat().st_size // 1024)
        return dest
    url = f"https://www.ccel.org/ccel/{ccel_author}/{ccel_work}.xml"
    logging.info("  Downloading %s ...", url)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    sha256 = hashlib.sha256(data).hexdigest()
    dest.write_bytes(data)
    logging.info("  -> %s (%d KB) sha256:%s...", dest.name, len(data) // 1024, sha256[:16])
    return dest


# ---------------------------------------------------------------------------
# Volume parser
# ---------------------------------------------------------------------------

def parse_volume(volume_key: str, dry_run: bool = False, force_download: bool = False) -> tuple[list[dict], str]:
    """
    Parse one Expositor's Bible volume. Downloads XML if not cached.
    Returns (entries, source_hash).

    Entries are deduplicated by entry_id within the parse run (first occurrence kept).
    """
    if volume_key not in VOLUMES:
        raise ValueError(f"Unknown volume: {volume_key!r}")

    vol = VOLUMES[volume_key]
    ccel_author, ccel_work = volume_key.split("/")
    pattern = vol["pattern"]
    books = vol["books"]
    # Primary OSIS book (used as default when passage parsing can't identify book)
    primary_osis = books[0] if books else "Gen"

    logging.info("Parsing %s (%s / %s) ...", vol["title"], ccel_author, ccel_work)
    logging.info("  Author: %s  Pattern: %s", vol["author"], pattern)

    xml_path = download_volume(ccel_author, ccel_work, force=force_download)
    logging.info("  Preprocessing ThML ...")

    raw_bytes = xml_path.read_bytes()
    xml_text = preprocess_thml(raw_bytes)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(f"XML parse failed for {volume_key}: {exc}") from exc

    body = root.find("ThML.body")
    if body is None:
        raise RuntimeError(f"No <ThML.body> found in {volume_key}")

    # Compute source hash
    source_hash = hashlib.sha256(raw_bytes).hexdigest()

    entries: list[dict] = []
    skipped = 0
    limit = 6 if dry_run else None  # dry-run: first 6 entries max

    if pattern in ("multi_book", "passage_in_section_title"):
        # Pattern D: div1 per Bible book, div2 per section.
        # Pattern E: div1 per Bible chapter, div2 per verse-keyed section.
        for div1 in body:
            if _is_front_back_matter(div1):
                skipped += 1
                continue
            if pattern == "multi_book":
                book_entries = parse_multi_book_div1(div1, volume_key)
            else:
                book_entries = parse_section_title_div1(div1, primary_osis, volume_key)
            for e in book_entries:
                entries.append(e)
                if limit and len(entries) >= limit:
                    break
            if limit and len(entries) >= limit:
                break
    elif pattern == "chapter_range_book":
        # Pattern G: div1 elements are lecture-chapters (not per-book).
        # Commentary chapter number (from Roman numeral in div1.title) determines
        # the Bible book via the volume's chapter_book_ranges config.
        chapter_book_ranges = vol.get("chapter_book_ranges", [])
        for div1 in body:
            if limit and len(entries) >= limit:
                break
            if _is_front_back_matter(div1):
                skipped += 1
                continue
            chapter_num = _div1_chapter_number(div1.get("title", ""))
            if chapter_num is None:
                skipped += 1
                continue
            book_osis = _book_from_chapter_ranges(chapter_num, chapter_book_ranges)
            if book_osis is None:
                skipped += 1
                continue
            entry = parse_passage_in_text(div1, book_osis, volume_key)
            if entry:
                entries.append(entry)
            else:
                skipped += 1
    else:
        for div1 in body:
            if limit and len(entries) >= limit:
                break
            if _is_front_back_matter(div1):
                skipped += 1
                continue

            if pattern == "passage_in_text":
                entry = parse_passage_in_text(div1, primary_osis, volume_key)
                if entry:
                    entries.append(entry)
                else:
                    skipped += 1
            elif pattern == "passage_in_title":
                entry = parse_passage_in_title(div1, primary_osis, volume_key)
                if entry:
                    entries.append(entry)
                else:
                    skipped += 1
            elif pattern == "passage_in_div1_title":
                entry = parse_passage_in_div1_title(div1, primary_osis, volume_key)
                if entry:
                    entries.append(entry)
                else:
                    skipped += 1
            elif pattern == "psalms":
                entry = parse_psalm_div(div1, volume_key)
                if entry:
                    entries.append(entry)
                else:
                    skipped += 1

    # Deduplicate by entry_id within this parse run (keep first occurrence)
    seen_ids: set[str] = set()
    unique_entries: list[dict] = []
    for e in entries:
        if e["entry_id"] not in seen_ids:
            seen_ids.add(e["entry_id"])
            unique_entries.append(e)
        else:
            logging.debug("  Dedup: dropping duplicate entry_id %s", e["entry_id"])

    dupes = len(entries) - len(unique_entries)
    if dupes:
        logging.info("  Deduped %d duplicate entry_ids within parse run", dupes)

    logging.info(
        "  Parsed %d entries, %d skipped/no-passage",
        len(unique_entries), skipped,
    )
    return unique_entries, source_hash


# ---------------------------------------------------------------------------
# Output grouping by Bible book
# ---------------------------------------------------------------------------

def group_by_book(entries: list[dict]) -> dict[str, list[dict]]:
    """Group entries by book_osis. Returns {osis: [entry, ...]} dict."""
    groups: dict[str, list[dict]] = {}
    for e in entries:
        osis = e["book_osis"]
        groups.setdefault(osis, []).append(e)
    return groups


def build_meta(vol: dict, volume_key: str, source_hash: str, processing_date: str) -> dict:
    """Build OCD meta envelope for one output file."""
    ccel_author, ccel_work = volume_key.split("/")
    return {
        "id": RESOURCE_ID,
        "title": "The Expositor's Bible",
        "author": vol["author"],
        "author_death_year": vol["author_death_year"],
        "contributors": normalize_contributors([f"{SERIES_EDITOR} (series editor)"]),
        "original_publication_year": 1887,
        "language": "en",
        "tradition": vol["tradition"],
        "license": "public-domain",
        "schema_type": "commentary",
        "schema_version": SCHEMA_VERSION,
        "verse_text_source": "none",
        "verse_reference_standard": "OSIS",
        "completeness": "partial",
        "provenance": {
            "source_url": f"https://www.ccel.org/ccel/{ccel_author}/{ccel_work}.xml",
            "source_format": "CCEL ThML XML",
            "source_edition": vol["title"],
            "download_date": processing_date,
            "source_hash": f"sha256:{source_hash}",
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/ccel_expositors_bible.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": (
                f"Parsed from CCEL ThML XML. Source permission granted by CCEL (Quincy, 2026-04-01). "
                f"CCEL robots.txt: crawl-delay 10 (checked 2026-04-13)."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Write output
# ---------------------------------------------------------------------------

def write_output(
    vol: dict,
    volume_key: str,
    entries: list[dict],
    source_hash: str,
    processing_date: str,
    dry_run: bool = False,
) -> dict[str, Path]:
    """
    Write one JSON file per Bible book to data/commentaries/expositors-bible/.
    Returns {book_slug: output_path} dict.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    groups = group_by_book(entries)
    written: dict[str, Path] = {}
    meta = build_meta(vol, volume_key, source_hash, processing_date)

    for osis, book_entries in groups.items():
        book_slug = osis.lower()
        output_path = OUTPUT_DIR / f"{book_slug}.json"
        output = {"meta": meta, "data": book_entries}

        if dry_run:
            logging.info(
                "  [dry-run] Would write %d entries for %s -> %s",
                len(book_entries), osis, output_path,
            )
        else:
            # If file exists (multi-volume book like Isaiah or Psalms), merge entries
            if output_path.exists():
                existing = json.loads(output_path.read_text(encoding="utf-8"))
                existing_ids = {e["entry_id"] for e in existing.get("data", [])}
                new_entries = [e for e in book_entries if e["entry_id"] not in existing_ids]
                all_entries = existing.get("data", []) + new_entries
                # Sort by chapter, then verse_range start
                all_entries.sort(key=lambda e: (e["chapter"], int(re.match(r"\d+", e["verse_range"]).group())))
                output = {"meta": meta, "data": all_entries}
                logging.info(
                    "  Merged %d new entries into existing %s (%d total)",
                    len(new_entries), output_path.name, len(all_entries),
                )
            else:
                logging.info(
                    "  Writing %d entries -> %s",
                    len(book_entries), output_path,
                )
            with open(output_path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
                f.write("\n")
        written[book_slug] = output_path

    return written


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------

def report_quality(entries: list[dict], volume_key: str) -> dict:
    """Print quality stats; return {entries_with_refs: int, pct: float}."""
    total = len(entries)
    if total == 0:
        logging.warning("  WARNING: 0 entries parsed for %s", volume_key)
        return {"entries_with_refs": 0, "pct": 0.0}

    no_passage = sum(1 for e in entries if e["chapter"] == 0)
    with_refs = sum(1 for e in entries if e["cross_references"])
    empty_text = sum(1 for e in entries if not e["commentary_text"].strip())
    short = sum(1 for e in entries if e["word_count"] < 30)
    wc_list = sorted(e["word_count"] for e in entries)
    median_wc = wc_list[total // 2]

    logging.info("  Quality report (%s):", volume_key)
    logging.info("    Total entries: %d", total)
    logging.info("    Entries with cross_references: %d/%d (%.0f%%)", with_refs, total, 100 * with_refs / total)
    logging.info("    Median word count: %d  Min: %d  Max: %d", median_wc, wc_list[0], wc_list[-1])
    if no_passage:
        logging.warning("    WARNING: %d entries with chapter=0 (passage parse failed)", no_passage)
    if empty_text:
        logging.warning("    WARNING: %d entries with empty commentary_text", empty_text)
    if short:
        logging.info("    NOTE: %d entries under 30 words (may be stubs)", short)

    return {"entries_with_refs": with_refs, "pct": 100 * with_refs / total}


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    logging.basicConfig(
        level=logging.DEBUG, handlers=[fh, sh], format="%(levelname)s: %(message)s"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Parse Expositor's Bible volumes from CCEL ThML XML into OCD commentary JSON"
    )
    parser.add_argument(
        "--volume",
        metavar="AUTHOR/WORK",
        help='Volume key, e.g. "moule/expositorromans". Repeatable.',
        action="append",
        dest="volumes",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all 48 volumes in the registry",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse first 6 entries per volume, print sample, do not write files",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download XML even if cached",
    )
    args = parser.parse_args()

    # Ensure stdout can handle Unicode (Windows cp1252 default fails on Greek/smart-quotes)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not args.volumes and not args.all:
        parser.print_help()
        sys.exit(1)

    volume_keys = list(VOLUMES.keys()) if args.all else args.volumes

    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = time.time()
    total_entries = 0
    total_files = 0
    cross_ref_stats: list[dict] = []

    for i, vkey in enumerate(volume_keys):
        if vkey not in VOLUMES:
            logging.error("Unknown volume key: %r (skipping)", vkey)
            continue

        vol = VOLUMES[vkey]
        logging.info("")
        logging.info("=== Volume %d/%d: %s ===", i + 1, len(volume_keys), vkey)

        if i > 0 and not args.dry_run:
            logging.info("  Sleeping %ds (CCEL crawl-delay) ...", CRAWL_DELAY)
            time.sleep(CRAWL_DELAY)

        try:
            entries, source_hash = parse_volume(vkey, dry_run=args.dry_run, force_download=args.force_download)
        except Exception as exc:
            logging.error("  FAILED: %s", exc)
            continue

        stats = report_quality(entries, vkey)
        cross_ref_stats.append({"volume": vkey, **stats})

        if args.dry_run:
            logging.info("  --- Sample entries (first 2) ---")
            for e in entries[:2]:
                print(json.dumps(e, ensure_ascii=False, indent=2))
        else:
            written = write_output(vol, vkey, entries, source_hash, processing_date, dry_run=False)
            total_files += len(written)

        total_entries += len(entries)

    elapsed = time.time() - start
    logging.info("")
    logging.info("=== Summary ===")
    logging.info("  Volumes processed: %d", len(volume_keys))
    logging.info("  Total entries: %d", total_entries)
    if not args.dry_run:
        logging.info("  Output files written/merged: %d", total_files)
    logging.info("  Elapsed: %.1fs", elapsed)

    # Cross-reference coverage report
    if cross_ref_stats:
        logging.info("")
        logging.info("=== Cross-reference coverage ===")
        for s in cross_ref_stats:
            logging.info("  %s: %d/%d (%.0f%%)", s["volume"], s["entries_with_refs"],
                         s["entries_with_refs"] + (0 if s["pct"] == 100 else 1), s["pct"])


if __name__ == "__main__":
    main()
