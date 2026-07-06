"""ccel_puritan_works.py
Parser for Puritan & Reformed works (19 titles, 7 authors) from CCEL ThML XML.

Downloads {ccel_id}.xml from CCEL once per work, then parses the full section
tree into OCD structured_text JSON files (one per work).

Source permission: CCEL confirmed OK to parse (Quincy, 2026-04-01). Copyright is on
CCEL's files/formatting only, not the PD texts. Attribution: "sourced via CCEL.org".
robots.txt: crawl-delay 10 for all agents (confirmed 2026-04-22).

Works covered: Watson x5, Baxter x3, Flavel x2, Bunyan x2, Law x1, Ryle x2, Edwards x5

XML structure (census across 7 pilot works, 2026-04-22):

  Flavel/fountain (uses div type= like Owen):
    type=Sermon (42 divs) -> section_type='chapter'
    No editorial types in census.
    Headings: h1, h2, h3.

  Flavel/grace (heading-only, no div type=):
    div1 count 39; 35 sermon div1s retained as section_type='chapter'.
    Editorial div1s filtered: Title Page, The Epistle Dedicatory,
    The Epistle To The Reader, Indexes.
    Headings: h1 plus h2 subtitles for most sermon divs.

  Watson, Baxter, Bunyan, Law, Ryle, Edwards (heading-only -- no div type=):
    div elements have type='' (absent). Section type inferred from:
      a) HEADING_RE match on h* or title= text (Part/Chapter/Section/Sermon -> mapped)
      b) Structural heuristic: no-content div with children -> 'part';
         content div with no children -> 'chapter'; both -> 'section'.

  Watson/divinity: div1/h2 groups (parts), div2/h3 articles (chapters).
    e.g. div1 "3. God and his creation" -> part containing div2 "1. The Being Of God".
    First div1 (title-only, p=0, no children) -> filtered by orphan check.
    "Brief Memoir" div1 -> filtered by is_editorial_div.

  Baxter/pastor, Law/serious_call, Bunyan/holy_war: flat div1 chapters.
    All content divs at div1 level; title= attribute carries the heading.
    Bunyan: "To The Reader" and "An Advertisement to the Reader" -> editorial.
    Law: "Title Page" -> editorial.

  Ryle/holiness: div1 groupings (Prefatory Material, Holiness) containing
    div2 chapters labeled "I. Sin", "II. Sanctification", etc.
    div2/title= carries full descriptive title; h2 element carries Roman numeral only.

  Edwards/affections: div1 parts (Part I, Part II, Part III.) and div2 sections.
    All structure via title= attribute; only 3 h* elements in entire work.
    Part II has div2 subsections (12 signs); Part I is a large flat leaf (95 p).
    "I. Affections that are truly spiritual..." is a div1 containing div2 subsections
    (signs II-XII), creating an asymmetric hierarchy in the XML.

  Editorial patterns (all authors):
    type=Titlepage / Back / Index / Indexes (Owen-style)
    title='Title Page', 'Acknowledgements', 'Contents', 'Indexes' (heading-only)
    h* text matching /^brief\\s+memoir/i, /^to\\s+the\\s+reader$/i,
      /advertisement\\s+to\\s+the\\s+reader/i, /^indexes?$/i

  Heading extraction:
    1. Collect ALL h1/h2/h3/h4/title direct children.
    2. Scan each h* for HEADING_RE match (first match wins). Scanning all
       h* (not just first) handles Law pattern: decorative book-title h2s
       precede the actual chapter h3.
    3. HEADING_RE matched with non-empty title -> (label, title).
    4. HEADING_RE matched, title empty (e.g. 'CHAPTER I') -> also check
       div title= attr for the descriptive subtitle.
    5. No h* matched -> try div title= attribute with HEADING_RE.
    6. title= no HEADING_RE match -> ("", title_attr).
    7. Fallback -> ("", first_h_text) for numbered headings ('1. Man's Chief End').

  scripRef/@osisRef prefix variants:
    Same as Owen: 'Bible:Book.ch.v' and 'Bible.kjv:Book.ch.v'.

Usage:
    py -3 build/parsers/ccel_puritan_works.py --dry-run
    py -3 build/parsers/ccel_puritan_works.py --author watson --download
    py -3 build/parsers/ccel_puritan_works.py --work watson-body-of-divinity --download --parse
    py -3 build/parsers/ccel_puritan_works.py --download
    py -3 build/parsers/ccel_puritan_works.py --parse
    py -3 build/parsers/ccel_puritan_works.py --download --parse
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request  # standards: download only
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))
from build.lib._generated_enums import (  # noqa: E402
    STRUCTURED_TEXT__META__AUDIENCE,
    STRUCTURED_TEXT__META__COMPLETENESS,
    STRUCTURED_TEXT__META__ERA,
    STRUCTURED_TEXT__META__TRADITION,
)
from build.lib.contributors import normalize_contributors  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

OUTPUT_DIR = REPO_ROOT / "data" / "structured-text"
SOURCES_DIR = REPO_ROOT / "sources" / "structured-text"
LOG_FILE = Path(__file__).resolve().parent / "ccel_puritan_works.log"

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.1"
CRAWL_DELAY = 10
UA = "OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)"
CCEL_BASE = "https://www.ccel.org/ccel"

# ---------------------------------------------------------------------------
# Author metadata
# ---------------------------------------------------------------------------

AUTHOR_CONFIG = {
    "watson": {
        "author": "Thomas Watson",
        "author_id": "thomas-watson",
        "author_birth_year": 1620,
        "author_death_year": 1686,
        "tradition": ["reformed", "puritan", "nonconformist"],
        "tradition_notes": (
            "Watson was a leading Puritan ejected from St. Stephen Walbrook in 1662."
            " Best known for his catechetical expositions of the Westminster Shorter Catechism."
        ),
        "era": "post-reformation",
        "audience": "lay",
        "language": "en",
        "original_language": "en",
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
    },
    "baxter": {
        "author": "Richard Baxter",
        "author_id": "richard-baxter",
        "author_birth_year": 1615,
        "author_death_year": 1691,
        "tradition": ["reformed", "puritan", "nonconformist"],
        "tradition_notes": (
            "Baxter was a Nonconformist minister and prolific Puritan author."
            " His practical divinity writings exercised enormous influence across denominations."
        ),
        "era": "post-reformation",
        "audience": "lay",
        "language": "en",
        "original_language": "en",
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
    },
    "flavel": {
        "author": "John Flavel",
        "author_id": "john-flavel",
        "author_birth_year": 1627,
        "author_death_year": 1691,
        "tradition": ["reformed", "puritan", "nonconformist"],
        "tradition_notes": (
            "Flavel was a Nonconformist minister in Dartmouth, ejected in 1662."
            " Known for his experimental Calvinist piety and christocentric sermons."
        ),
        "era": "post-reformation",
        "audience": "lay",
        "language": "en",
        "original_language": "en",
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
    },
    "bunyan": {
        "author": "John Bunyan",
        "author_id": "john-bunyan",
        "author_birth_year": 1628,
        "author_death_year": 1688,
        "tradition": ["puritan", "particular-baptist"],
        "tradition_notes": (
            "Bunyan was a Particular Baptist minister who wrote Pilgrim's Progress"
            " while imprisoned in Bedford Gaol."
        ),
        "era": "post-reformation",
        "audience": "lay",
        "language": "en",
        "original_language": "en",
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
    },
    "law": {
        "author": "William Law",
        "author_id": "william-law",
        "author_birth_year": 1686,
        "author_death_year": 1761,
        "tradition": ["anglican"],
        "tradition_notes": (
            "Law was a Non-Juror Anglican clergyman whose Serious Call shaped the"
            " devotional life of John Wesley, George Whitefield, and Samuel Johnson."
        ),
        "era": "modern",
        "audience": "lay",
        "language": "en",
        "original_language": "en",
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
    },
    "ryle": {
        "author": "J.C. Ryle",
        "author_id": "j-c-ryle",
        "author_birth_year": 1816,
        "author_death_year": 1900,
        "tradition": ["anglican", "evangelical"],
        "tradition_notes": (
            "Ryle was the first Bishop of Liverpool, a Calvinist Anglican and"
            " prolific evangelical writer known for plain, direct prose."
        ),
        "era": "modern",
        "audience": "lay",
        "language": "en",
        "original_language": "en",
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
    },
    "edwards": {
        "author": "Jonathan Edwards",
        "author_id": "jonathan-edwards",
        "author_birth_year": 1703,
        "author_death_year": 1758,
        "tradition": ["reformed", "calvinist", "evangelical"],
        "tradition_notes": (
            "Edwards was America's preeminent Reformed theologian and philosopher."
            " President of the College of New Jersey; architect of the First Great Awakening."
        ),
        "era": "modern",
        "audience": "scholarly",
        "language": "en",
        "original_language": "en",
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
    },
    "rutherford": {
        "author": "Samuel Rutherford",
        "author_id": "samuel-rutherford",
        "author_birth_year": 1600,
        "author_death_year": 1661,
        "tradition": ["reformed", "presbyterian"],
        "tradition_notes": (
            "Rutherford was a Scottish Presbyterian minister and theologian, professor"
            " at the University of St Andrews, and a principal drafter of the Westminster"
            " Confession (1646). His letters are celebrated for their fervent experimental"
            " Calvinism and vivid expressions of union with Christ."
        ),
        "era": "post-reformation",
        "audience": "lay",
        "language": "en",
        "original_language": "en",
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
    },
    "boston": {
        "author": "Thomas Boston",
        "author_id": "thomas-boston",
        "author_birth_year": 1676,
        "author_death_year": 1732,
        "tradition": ["reformed", "presbyterian"],
        "tradition_notes": (
            "Boston was a Scottish Presbyterian minister at Ettrick, associated with"
            " the Marrow controversy and the evangelical wing of the Church of Scotland."
            " Known for his plain-English practical divinity and covenant theology."
        ),
        "era": "post-reformation",
        "audience": "lay",
        "language": "en",
        "original_language": "en",
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
    },
    "butler": {
        "author": "Joseph Butler",
        "author_id": "joseph-butler",
        "author_birth_year": 1692,
        "author_death_year": 1752,
        "tradition": ["anglican"],
        "tradition_notes": (
            "Butler was Bishop of Durham and the leading Anglican apologist of the 18th century."
            " The Analogy of Religion (1736) defended Christianity against Deism by analogical argument"
            " from natural religion."
        ),
        "era": "post-reformation",
        "audience": "scholarly",
        "language": "en",
        "original_language": "en",
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
    },
    "murray": {
        "author": "Andrew Murray",
        "author_id": "murray-andrew",
        "author_birth_year": 1828,
        "author_death_year": 1917,
        "tradition": ["reformed", "calvinist"],
        "tradition_notes": (
            "Murray was a South African Dutch Reformed minister and prolific devotional writer."
            " Influenced by the Keswick holiness movement, his works emphasize consecration,"
            " abiding in Christ, and dependence on the Holy Spirit."
        ),
        "era": "modern",
        "audience": "lay",
        "language": "en",
        "original_language": "en",
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
    },
}


def _validate_work_configs() -> None:
    for author_id, cfg in AUTHOR_CONFIG.items():
        for t in cfg.get("tradition", []):
            assert t in STRUCTURED_TEXT__META__TRADITION, f"{author_id}: invalid tradition {t!r}"
        if era := cfg.get("era"):
            assert era in STRUCTURED_TEXT__META__ERA, f"{author_id}: invalid era {era!r}"
        if aud := cfg.get("audience"):
            assert aud in STRUCTURED_TEXT__META__AUDIENCE, f"{author_id}: invalid audience {aud!r}"
        if comp := cfg.get("completeness"):
            assert comp in STRUCTURED_TEXT__META__COMPLETENESS, f"{author_id}: invalid completeness {comp!r}"


_validate_work_configs()

# ---------------------------------------------------------------------------
# Work registry
# ---------------------------------------------------------------------------

WORK_CONFIG = [
    # Thomas Watson -- 5 works
    {
        "author_id": "watson",
        "slug": "watson-body-of-divinity",
        "ccel_id": "divinity",
        "author_ccel_path": "watson",
        "title": "A Body of Divinity",
        "work_kind": "systematic-theology",
        "pub_year": 1692,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org). Original: London, 1692.",
    },
    {
        "author_id": "watson",
        "slug": "watson-beatitudes",
        "ccel_id": "beatitudes",
        "author_ccel_path": "watson",
        "title": "The Beatitudes",
        "work_kind": "treatise",
        "pub_year": 1660,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org).",
    },
    {
        "author_id": "watson",
        "slug": "watson-divine-contentment",
        "ccel_id": "contentment",
        "author_ccel_path": "watson",
        "title": "The Art of Divine Contentment",
        "work_kind": "treatise",
        "pub_year": 1653,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org).",
    },
    {
        "author_id": "watson",
        "slug": "watson-ten-commandments",
        "ccel_id": "commandments",
        "author_ccel_path": "watson",
        "title": "The Ten Commandments",
        "work_kind": "treatise",
        "pub_year": 1692,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org).",
    },
    {
        "author_id": "watson",
        "slug": "watson-lords-prayer",
        "ccel_id": "prayer",
        "author_ccel_path": "watson",
        "title": "The Lord's Prayer",
        "work_kind": "treatise",
        "pub_year": 1692,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org).",
    },
    # Richard Baxter -- 3 works
    {
        "author_id": "baxter",
        "slug": "baxter-saints-rest",
        "ccel_id": "saints_rest",
        "author_ccel_path": "baxter",
        "title": "The Saints' Everlasting Rest",
        "work_kind": "devotional-classic",
        "pub_year": 1650,
        "completeness": "abridged",
        "contributors": [],
        "source_edition": (
            "CCEL ThML edition (sourced via CCEL.org)."
            " Note: CCEL hosts an abridged edition (American Tract Society, New York);"
            " full original (4 parts) may differ."
        ),
    },
    {
        "author_id": "baxter",
        "slug": "baxter-reformed-pastor",
        "ccel_id": "pastor",
        "author_ccel_path": "baxter",
        "title": "The Reformed Pastor",
        "work_kind": "treatise",
        "pub_year": 1656,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org).",
    },
    {
        "author_id": "baxter",
        "slug": "baxter-call-to-unconverted",
        "ccel_id": "unconverted",
        "author_ccel_path": "baxter",
        "title": "A Call to the Unconverted",
        "work_kind": "treatise",
        "pub_year": 1658,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org).",
    },
    # John Flavel -- 2 works
    {
        "author_id": "flavel",
        "slug": "flavel-fountain-of-life",
        "ccel_id": "fountain",
        "author_ccel_path": "flavel",
        "title": "The Fountain of Life Opened Up",
        "work_kind": "treatise",
        "pub_year": 1671,
        "contributors": [],
        "source_edition": (
            "CCEL ThML edition (sourced via CCEL.org)."
            " Original: London, 1671. This edition based on Banner of Truth reprint, 1968."
        ),
    },
    {
        "author_id": "flavel",
        "slug": "flavel-method-of-grace",
        "ccel_id": "grace",
        "author_ccel_path": "flavel",
        "title": "The Method of Grace in the Gospel Redemption",
        "work_kind": "treatise",
        "pub_year": 2000,
        "contributors": [],
        "source_edition": (
            "CCEL ThML edition (sourced via CCEL.org). DC.Date header: 2000-07-09."
            " Title page notes W. Barnes and Son first publication, 1820, and"
            " Banner of Truth reprints in 1968 and 1982."
        ),
    },
    # John Bunyan -- 2 works
    {
        "author_id": "bunyan",
        "slug": "bunyan-grace-abounding",
        "ccel_id": "grace",
        "author_ccel_path": "bunyan",
        "title": "Grace Abounding to the Chief of Sinners",
        "work_kind": "treatise",
        "pub_year": 1666,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org).",
    },
    {
        "author_id": "bunyan",
        "slug": "bunyan-holy-war",
        "ccel_id": "holy_war",
        "author_ccel_path": "bunyan",
        "title": "The Holy War",
        "work_kind": "treatise",
        "pub_year": 1682,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org).",
    },
    # William Law -- 1 work
    {
        "author_id": "law",
        "slug": "law-serious-call",
        "ccel_id": "serious_call",
        "author_ccel_path": "law",
        "title": "A Serious Call to a Devout and Holy Life",
        "work_kind": "devotional-classic",
        "pub_year": 1729,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org).",
    },
    # J.C. Ryle -- 2 works
    {
        "author_id": "ryle",
        "slug": "ryle-holiness",
        "ccel_id": "holiness",
        "author_ccel_path": "ryle",
        "title": "Holiness",
        "work_kind": "treatise",
        "pub_year": 1879,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org).",
    },
    {
        "author_id": "ryle",
        "slug": "ryle-expository-thoughts-matthew",
        "ccel_id": "matthew",
        "author_ccel_path": "ryle",
        "title": "Expository Thoughts on the Gospels: Matthew",
        "work_kind": "treatise",
        "pub_year": 1856,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org).",
    },
    # Jonathan Edwards -- 3 works (CCEL author path: edwards, not edwards_j)
    {
        "author_id": "edwards",
        "slug": "edwards-religious-affections",
        "ccel_id": "affections",
        "author_ccel_path": "edwards",
        "title": "Religious Affections",
        "work_kind": "treatise",
        "pub_year": 1746,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org).",
    },
    {
        "author_id": "edwards",
        "slug": "edwards-freedom-of-the-will",
        "ccel_id": "will",
        "author_ccel_path": "edwards",
        "title": "Freedom of the Will",
        "work_kind": "treatise",
        "pub_year": 1754,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org).",
    },
    {
        "author_id": "edwards",
        "slug": "edwards-select-sermons",
        "ccel_id": "sermons",
        "author_ccel_path": "edwards",
        "title": "Select Sermons",
        "work_kind": "treatise",
        "pub_year": None,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org).",
    },
    {
        "author_id": "edwards",
        "slug": "edwards-history-of-redemption",
        "ccel_id": "history_of_redemption",
        "author_ccel_path": "edwards",
        "volume_xml": "works1",
        "volume_div_id": "xii",
        "title": "A History of the Work of Redemption",
        "work_kind": "treatise",
        "pub_year": 1774,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org). Extracted from works1 volume.",
    },
    {
        "author_id": "edwards",
        "slug": "edwards-distinguishing-marks",
        "ccel_id": "distinguishing_marks",
        "author_ccel_path": "edwards",
        "volume_xml": "works2",
        "volume_div_id": "vii",
        "title": "The Distinguishing Marks of a Work of the Spirit of God",
        "work_kind": "treatise",
        "pub_year": 1741,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org). Extracted from works2 volume.",
    },
    {
        "author_id": "edwards",
        "slug": "edwards-life-of-brainerd",
        "ccel_id": "brainerd",
        "author_ccel_path": "edwards",
        "volume_xml": "works2",
        "volume_div_id": "ix",
        "title": "The Life of David Brainerd",
        "work_kind": "devotional-classic",
        "pub_year": 1749,
        "contributors": [],
        "source_edition": (
            "CCEL ThML edition (sourced via CCEL.org). Extracted from works2 volume."
            " Edwards' memoir of the missionary David Brainerd (1718-1747)."
        ),
    },
    # Joseph Butler -- 1 work
    {
        "author_id": "butler",
        "slug": "butler-analogy-of-religion",
        "ccel_id": "analogy",
        "author_ccel_path": "butler",
        "title": "The Analogy of Religion",
        "work_kind": "theological-work",
        "pub_year": 1736,
        "contributors": [],
        "source_edition": (
            "CCEL ThML edition (sourced via CCEL.org)."
            " Original: London, 1736. A landmark defence of Christianity against 18th-century Deism."
        ),
    },
    # Samuel Rutherford -- 1 work
    {
        "author_id": "rutherford",
        "slug": "rutherford-letters",
        "ccel_id": "letters",
        "author_ccel_path": "rutherford",
        "title": "Letters of Samuel Rutherford",
        "work_kind": "devotional-classic",
        "pub_year": 1664,
        "contributors": [],
        "source_edition": (
            "CCEL ThML edition (sourced via CCEL.org)."
            " First published posthumously: Edinburgh, 1664."
            " This edition ed. Andrew Bonar (Oliphant, Edinburgh, 1891)."
        ),
    },
    # Thomas Boston -- 1 work
    {
        "author_id": "boston",
        "slug": "boston-crook-in-the-lot",
        "ccel_id": "crook",
        "author_ccel_path": "boston",
        "title": "The Crook in the Lot",
        "work_kind": "treatise",
        "pub_year": 1737,
        "contributors": [],
        "source_edition": (
            "CCEL ThML edition (sourced via CCEL.org)."
            " Original: Edinburgh, 1737. A treatise on divine sovereignty in affliction."
        ),
    },
    # Andrew Murray -- 1 work (CCEL ThML source; other Murray works via gutenberg_evangelical.py)
    {
        "author_id": "murray",
        "slug": "murray-absolute-surrender",
        "ccel_id": "surrender",
        "author_ccel_path": "murray",
        "title": "Absolute Surrender",
        "work_kind": "devotional-classic",
        "pub_year": 1895,
        "contributors": [],
        "source_edition": (
            "CCEL ThML edition (sourced via CCEL.org)."
            " Original: Marshall Brothers, London, 1895."
            " A series of addresses on full consecration to God."
        ),
    },
]

# ---------------------------------------------------------------------------
# ThML entity map (HTML entities not valid XML without the external DTD)
# Copied from ccel_owen_works.py -- shared infrastructure
# ---------------------------------------------------------------------------

THML_ENTITY_MAP = {
    "&mdash;": "\u2014",
    "&ndash;": "\u2013",
    "&lsquo;": "\u2018",
    "&rsquo;": "\u2019",
    "&ldquo;": "\u201c",
    "&rdquo;": "\u201d",
    "&nbsp;": "\u00a0",
    "&hellip;": "\u2026",
    "&emdash;": "\u2014",
    "&copy;": "\u00a9",
    "&reg;": "\u00ae",
    "&trade;": "\u2122",
    "&deg;": "\u00b0",
    "&para;": "\u00b6",
    "&sect;": "\u00a7",
    "&dagger;": "\u2020",
    "&Dagger;": "\u2021",
    "&bull;": "\u2022",
    "&prime;": "\u2032",
    "&Prime;": "\u2033",
    "&oline;": "\u203e",
    "&frasl;": "\u2044",
    "&spades;": "\u2660",
    "&clubs;": "\u2663",
    "&hearts;": "\u2665",
    "&diams;": "\u2666",
    "&agrave;": "\u00e0",
    "&aacute;": "\u00e1",
    "&egrave;": "\u00e8",
    "&eacute;": "\u00e9",
    "&iacute;": "\u00ed",
    "&oacute;": "\u00f3",
    "&uacute;": "\u00fa",
    "&Agrave;": "\u00c0",
    "&Aacute;": "\u00c1",
    "&Egrave;": "\u00c8",
    "&Eacute;": "\u00c9",
    "&Iacute;": "\u00cd",
    "&Oacute;": "\u00d3",
    "&Uacute;": "\u00da",
    "&auml;": "\u00e4",
    "&euml;": "\u00eb",
    "&iuml;": "\u00ef",
    "&ouml;": "\u00f6",
    "&uuml;": "\u00fc",
    "&Auml;": "\u00c4",
    "&Euml;": "\u00cb",
    "&Iuml;": "\u00cf",
    "&Ouml;": "\u00d6",
    "&Uuml;": "\u00dc",
    "&aelig;": "\u00e6",
    "&AElig;": "\u00c6",
    "&ccedil;": "\u00e7",
    "&Ccedil;": "\u00c7",
    "&ntilde;": "\u00f1",
    "&Ntilde;": "\u00d1",
    "&thorn;": "\u00fe",
    "&THORN;": "\u00de",
    "&eth;": "\u00f0",
    "&ETH;": "\u00d0",
    "&oslash;": "\u00f8",
    "&Oslash;": "\u00d8",
    "&aring;": "\u00e5",
    "&Aring;": "\u00c5",
    "&szlig;": "\u00df",
    "&laquo;": "\u00ab",
    "&raquo;": "\u00bb",
    "&iexcl;": "\u00a1",
    "&iquest;": "\u00bf",
    "&pound;": "\u00a3",
    "&euro;": "\u20ac",
    "&yen;": "\u00a5",
    "&cent;": "\u00a2",
    "&alpha;": "\u03b1",
    "&beta;": "\u03b2",
    "&gamma;": "\u03b3",
    "&delta;": "\u03b4",
    "&epsilon;": "\u03b5",
    "&zeta;": "\u03b6",
    "&eta;": "\u03b7",
    "&theta;": "\u03b8",
    "&iota;": "\u03b9",
    "&kappa;": "\u03ba",
    "&lambda;": "\u03bb",
    "&mu;": "\u03bc",
    "&nu;": "\u03bd",
    "&xi;": "\u03be",
    "&omicron;": "\u03bf",
    "&pi;": "\u03c0",
    "&rho;": "\u03c1",
    "&sigma;": "\u03c3",
    "&tau;": "\u03c4",
    "&upsilon;": "\u03c5",
    "&phi;": "\u03c6",
    "&chi;": "\u03c7",
    "&psi;": "\u03c8",
    "&omega;": "\u03c9",
    "&Alpha;": "\u0391",
    "&Beta;": "\u0392",
    "&Gamma;": "\u0393",
    "&Delta;": "\u0394",
    "&Epsilon;": "\u0395",
    "&Zeta;": "\u0396",
    "&Eta;": "\u0397",
    "&Theta;": "\u0398",
    "&Iota;": "\u0399",
    "&Kappa;": "\u039a",
    "&Lambda;": "\u039b",
    "&Mu;": "\u039c",
    "&Nu;": "\u039d",
    "&Xi;": "\u039e",
    "&Omicron;": "\u039f",
    "&Pi;": "\u03a0",
    "&Rho;": "\u03a1",
    "&Sigma;": "\u03a3",
    "&Tau;": "\u03a4",
    "&Upsilon;": "\u03a5",
    "&Phi;": "\u03a6",
    "&Chi;": "\u03a7",
    "&Psi;": "\u03a8",
    "&Omega;": "\u03a9",
}

XML_SAFE_ENTITIES = {"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"}

# ---------------------------------------------------------------------------
# Parsing constants
# ---------------------------------------------------------------------------

_HEADING_TAGS = frozenset(["h1", "h2", "h3", "h4", "title"])

# Matches "Book I.", "Part I. Title text", "Chapter III.", "Sermon V. Title" etc.
HEADING_RE = re.compile(
    r"^((?:Book|Part|Chapter|Sermon|Section|Discourse|Treatise)\s+[IVXLC\d]+\.?)\s*(.*)",
    re.IGNORECASE,
)

# Maps HEADING_RE first-word to section_type
_HEADING_WORD_TO_TYPE = {
    "book": "book",
    "part": "part",
    "chapter": "chapter",
    "sermon": "chapter",
    "section": "section",
    "discourse": "chapter",
    "treatise": "chapter",
}

# Tags skipped entirely when collecting text content
_SKIP_TAGS = frozenset(["note", "pb", "insertIndex", "style", "selector", "scripContext"])

# Regex matching a div* tag: div, div1, div2, div3, div4, div5
_DIV_TAG_RE = re.compile(r"^div\d?$")

# Module-level list for warnings collected during parse_div; reset per work in parse_work
_parse_warnings: list = []


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _raw_path(work_cfg: dict) -> Path:
    return REPO_ROOT / "raw" / "ccel" / work_cfg["author_ccel_path"] / f"{work_cfg['ccel_id']}.xml"


def _extract_from_volume(work_cfg: dict, force: bool = False, log_fn=None) -> None:
    """Download a CCEL Works volume, extract one div1, save as standalone ThML."""
    if log_fn is None:
        log_fn = lambda m: print(m.encode("ascii", errors="replace").decode("ascii"))

    vol_id   = work_cfg["volume_xml"]          # e.g. "works1"
    div_id   = work_cfg.get("volume_div_id")   # id= attribute value on div1, or None
    div_head = work_cfg.get("volume_div_head") # <head> text to match, or None
    if not div_id and not div_head:
        raise ValueError(f"{work_cfg['slug']}: need volume_div_id or volume_div_head")

    # Cache the raw volume separately from the extracted work file
    vol_cache = REPO_ROOT / "raw" / "ccel" / work_cfg["author_ccel_path"] / f"{vol_id}.xml"
    if not vol_cache.exists() or force:
        url = f"{CCEL_BASE}/{work_cfg['author_ccel_path']}/{vol_id}.xml"
        log_fn(f"  Downloading volume {url} ...")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        data = urllib.request.urlopen(req, timeout=300).read()
        vol_cache.parent.mkdir(parents=True, exist_ok=True)
        vol_cache.write_bytes(data)
        log_fn(f"  Downloaded {len(data) // 1024} KB -> {vol_cache.name}")
    else:
        log_fn(f"  Volume cached: {vol_cache.name}")

    # Parse and locate the target div1 (ThML volumes use div1/div2/div3, not bare div)
    tree = ET.parse(str(vol_cache))
    root = tree.getroot()
    target = None
    for div in root.iter("div1"):
        if div_id and div.get("id") == div_id:
            target = div
            break
        if div_head:
            head_el = div.find("head")
            if head_el is not None and (head_el.text or "").strip() == div_head:
                target = div
                break
    if target is None:
        raise RuntimeError(
            f"{work_cfg['slug']}: div1 not found in {vol_id}.xml "
            f"(id={div_id!r}, head={div_head!r}). Re-run the census."
        )

    # Wrap in a minimal ThML shell so parse_work sees a normal single-work file
    shell = ET.fromstring("<ThML><ThML.body></ThML.body></ThML>")
    body = shell.find("ThML.body")
    if body is None:
        raise RuntimeError("Could not find ThML.body in shell")
    body.append(target)

    dest = _raw_path(work_cfg)
    dest.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(shell).write(str(dest), encoding="unicode", xml_declaration=True)
    dl_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    work_cfg["download_date"] = dl_date
    log_fn(f"  Extracted {work_cfg['slug']} -> {dest.name}")


def download_work(work_cfg: dict, force: bool = False, log_fn=None) -> None:
    """Download a single work XML from CCEL if not already cached.

    Retries up to 3 times with exponential backoff on transient HTTP errors
    (429, 5xx) and network errors.
    """
    if log_fn is None:
        log_fn = lambda m: print(m.encode("ascii", errors="replace").decode("ascii"))
    if "volume_xml" in work_cfg:
        _extract_from_volume(work_cfg, force=force, log_fn=log_fn)
        return
    dest = _raw_path(work_cfg)
    if dest.exists() and not force:
        size_kb = dest.stat().st_size // 1024
        log_fn(f"  Cached: {dest.name} ({size_kb} KB)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"{CCEL_BASE}/{work_cfg['author_ccel_path']}/{work_cfg['ccel_id']}.xml"
    log_fn(f"  Downloading {url} ...")
    _TRANSIENT_STATUS = frozenset([429, 500, 502, 503, 504])
    last_exc = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            with open(dest, "wb") as fh:
                fh.write(data)
            dl_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            work_cfg["download_date"] = dl_date
            log_fn(f"  Downloaded {len(data) // 1024} KB -> {dest.name}")
            return
        except urllib.error.HTTPError as exc:
            if exc.code in _TRANSIENT_STATUS:
                last_exc = exc
                wait = 2 ** attempt
                log_fn(f"  Transient HTTP {exc.code}; retrying in {wait}s (attempt {attempt}/3) ...")
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"Download failed for {work_cfg['ccel_id']}: HTTP {exc.code}. "
                    "Check the CCEL URL in WORK_CONFIG."
                ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            wait = 2 ** attempt
            log_fn(f"  Network error ({exc}); retrying in {wait}s (attempt {attempt}/3) ...")
            time.sleep(wait)
    raise RuntimeError(
        f"Download failed after 3 attempts for {work_cfg['ccel_id']}: {last_exc}. "
        "Check network access and CCEL availability."
    ) from last_exc


# ---------------------------------------------------------------------------
# XML preprocessing
# ---------------------------------------------------------------------------

def _replace_entity(match: re.Match) -> str:
    """Replace a named HTML entity if known; drop unknown ones silently."""
    ent = match.group(0)
    if ent in XML_SAFE_ENTITIES:
        return ent
    replacement = THML_ENTITY_MAP.get(ent)
    if replacement is not None:
        return replacement
    return ""


def preprocess_thml(raw_bytes: bytes) -> str:
    """
    Prepare raw ThML bytes for ElementTree:
    1. Decode -- UTF-8 with cp1252 fallback.
    2. Strip DOCTYPE declaration (prevents external DTD fetch attempt).
    3. Replace HTML entities with Unicode equivalents.
    """
    try:
        text = raw_bytes.decode("utf-8")
        if "\ufffd" in text:
            raise UnicodeDecodeError("utf-8", raw_bytes, 0, 1, "replacement chars found")
    except UnicodeDecodeError:
        text = raw_bytes.decode("cp1252", errors="replace")
    text = re.sub(r"<!DOCTYPE\s[^[>]*(?:\[[^\]]*\])?>", "", text, flags=re.DOTALL)
    text = re.sub(r"&[A-Za-z][A-Za-z0-9]*;", _replace_entity, text)
    return text


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def get_all_text(elem) -> str:
    """Recursively collect all text content, skipping footnote/metadata tags."""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if child.tag in _SKIP_TAGS:
            if child.tail:
                parts.append(child.tail)
            continue
        parts.append(get_all_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def clean_text(text: str) -> str:
    """Collapse internal whitespace and strip."""
    return re.sub(r"\s+", " ", text).strip()


def get_scriptrefs(elem) -> list:
    """
    Collect scripture references from <scripRef> elements within elem.
    Handles both 'Bible:Book.ch.v' and 'Bible.kjv:Book.ch.v' prefix forms.
    """
    refs = []
    for sr in elem.iter("scripRef"):
        osis_raw = sr.get("osisRef", "")
        raw_text = clean_text(get_all_text(sr))
        osis_list = []
        for part in osis_raw.split():
            cleaned = re.sub(r"^Bible(?:\.[a-z]+)?:", "", part).strip()
            if cleaned:
                osis_list.append(cleaned)
        if raw_text or osis_list:
            refs.append({"raw": raw_text, "osis": osis_list})
    return refs


def count_words(blocks: list) -> int:
    """Count words across a list of text strings."""
    return sum(len(b.split()) for b in blocks)


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------

def _first_heading_text(div_elem) -> str:
    """Return text of first h1/h2/h3/h4/title direct child, or ''."""
    for child in div_elem:
        if child.tag in _HEADING_TAGS:
            return clean_text(get_all_text(child))
    return ""


def is_editorial_div(div_elem, is_top_level: bool) -> bool:
    """
    Return True if this div should be excluded as editorial apparatus.

    Owen-style type= checks (same as ccel_owen_works.py):
      1. is_top_level AND type='Preface' (all top-level Prefaces are collection prefaces)
      2. type in ('Titlepage', 'Back', 'Index', 'Indexes')
      3. type='Preface' AND first heading matches /prefatory note/i
      4. first heading matches /^indexes?$/i

    Extended checks for heading-only works (no div type=):
      5. title= attribute matches 'Title Page', 'Acknowledgements', 'Contents'
      6. title= attribute starts with 'Index' or 'Index of'
      7. h* heading text matches /^brief\\s+memoir/i (Watson editorial bio)
      8. h* heading text matches /^to\\s+the\\s+reader$/i (Bunyan)
      9. h* heading text matches /advertisement\\s+to\\s+the\\s+reader/i (Bunyan)
      10. h* heading text matches /^the\\s+epistle\\s+(dedicatory|to\\s+the\\s+reader)$/i
    """
    div_type = div_elem.get("type", "")

    # --- Owen-style type= checks ---
    if is_top_level and div_type == "Preface":
        return True
    if div_type in ("Titlepage", "Back", "Index", "Indexes"):
        return True
    heading = _first_heading_text(div_elem)
    if div_type == "Preface" and re.search(r"prefatory note", heading, re.IGNORECASE):
        return True
    if re.match(r"^indexes?$", heading, re.IGNORECASE):
        return True

    # --- Heading-only works: title= attribute ---
    title_attr = (div_elem.get("title") or "").strip()
    if re.match(r"^title\s*page$", title_attr, re.IGNORECASE):
        return True
    if re.match(r"^acknowledg", title_attr, re.IGNORECASE):
        return True
    if re.match(r"^contents?$", title_attr, re.IGNORECASE):
        return True
    if re.match(r"^indexes?", title_attr, re.IGNORECASE):
        return True
    if re.match(r"^index\s+of", title_attr, re.IGNORECASE):
        return True
    if re.match(r"^fore?word$", title_attr, re.IGNORECASE):
        return True
    if re.match(r"^glossary$", title_attr, re.IGNORECASE):
        return True

    # --- Heading-only works: h* heading text patterns ---
    if re.search(r"^brief\s+memoir", heading, re.IGNORECASE):
        return True
    if re.match(r"^to\s+the\s+reader$", heading, re.IGNORECASE):
        return True
    if re.search(r"advertisement\s+to\s+the\s+reader", heading, re.IGNORECASE):
        return True
    if re.match(r"^the\s+epistle\s+(dedicatory|to\s+the\s+reader)$", heading, re.IGNORECASE):
        return True
    if re.match(r"^fore?word$", heading, re.IGNORECASE):
        return True
    if re.match(r"^glossary$", heading, re.IGNORECASE):
        return True

    return False


def extract_heading(div_elem) -> tuple:
    """
    Extract (label, title) from a div element.

    Algorithm:
      1. Collect all h1/h2/h3/h4/title direct children.
      2. Scan each h* for HEADING_RE match (first match wins).
         Scanning all h* (not just first) handles the Law pattern where
         decorative book-title h2s precede the actual chapter h3.
      3. If HEADING_RE matched and title part is non-empty: return (label, title).
      4. If HEADING_RE matched but title part is empty (e.g. 'CHAPTER I'):
         also check div's title= attribute for the descriptive subtitle.
      5. No h* matched HEADING_RE:
         a. Try div's title= attribute — HEADING_RE match: return (label, title).
         b. title= exists but no match: return ('', title_attr).
         c. Fall back to first h* raw text: return ('', first_h_text).
      6. Nothing: return ('', '').
    """
    h_texts = []
    for child in div_elem:
        if child.tag in _HEADING_TAGS:
            h_texts.append(clean_text(get_all_text(child)))

    # Scan all h* for HEADING_RE match
    for h_text in h_texts:
        if not h_text:
            continue
        m = HEADING_RE.match(h_text)
        if m:
            label = m.group(1).rstrip(".").strip()
            title = m.group(2).rstrip(".").strip()
            if not title:
                # Label only (e.g. 'CHAPTER I') — check title= for description
                title_attr = (div_elem.get("title") or "").strip()
                if title_attr:
                    m2 = HEADING_RE.match(title_attr)
                    if m2:
                        title = m2.group(2).rstrip(".").strip()
            return label, title

    # No h* matched HEADING_RE — try title= attribute
    title_attr = (div_elem.get("title") or "").strip()
    if title_attr:
        m = HEADING_RE.match(title_attr)
        if m:
            return m.group(1).rstrip(".").strip(), m.group(2).rstrip(".").strip()
        return "", title_attr.rstrip(".").strip()

    # Fall back to first h* raw text (numbered headings: '1. Man's Chief End', 'I. Sin')
    if h_texts:
        return "", (h_texts[0] or "").rstrip(".").strip()

    return "", ""


# ---------------------------------------------------------------------------
# Parse engine
# ---------------------------------------------------------------------------

def _infer_section_type_from_heading(heading_text: str) -> str:
    """
    Infer section_type from heading text using HEADING_RE.
    Returns '' if no match (caller should use structural heuristic fallback).
    """
    if not heading_text:
        return ""
    m = HEADING_RE.match(heading_text)
    if m:
        first_word = m.group(1).lower().split()[0]
        return _HEADING_WORD_TO_TYPE.get(first_word, "section")
    return ""


def parse_div(div_elem, depth: int = 0):
    """
    Recursively parse a div element into a section dict (or list of dicts).

    Returns:
      None        -- editorial div, skip it
      list[dict]  -- Work/Appendices container (type= based); returns its children
      dict        -- a single section node
    """
    global _parse_warnings

    # Step 1: editorial check
    if is_editorial_div(div_elem, is_top_level=(depth == 0)):
        return None

    div_type = div_elem.get("type", "")

    # Step 2: Owen-style type= container divs (Work, Appendices)
    if div_type in ("Work", "Appendices"):
        children = []
        for ch in div_elem:
            if not _DIV_TAG_RE.match(ch.tag):
                continue
            result = parse_div(ch, depth + 1)
            if result is None:
                continue
            if isinstance(result, list):
                children.extend(result)
            else:
                children.append(result)
        return children

    # Step 3: determine section_type
    # For type= works (Owen-style), map directly.
    # For heading-only works (type=''), infer from heading text (finalized below
    # after content_blocks and children are collected).
    _type_map = {
        "Part": "part",
        "Chapter": "chapter",
        "Section": "section",
        "Sermon": "chapter",
        "Preface": "preface",
        "Appendix": "appendix",
    }
    if div_type:
        section_type = _type_map.get(div_type, "section")
    else:
        # Placeholder -- finalized after content + children collected (step 9)
        section_type = ""

    # Step 4: extract label and title
    label, title = extract_heading(div_elem)

    # Step 5: prayer content warning
    heading_for_warn = label or title or ""
    if re.match(r"^a prayer", heading_for_warn, re.IGNORECASE):
        _parse_warnings.append(
            f"Prayer content at {div_elem.get('id', '?')}: {heading_for_warn}"
        )

    # Step 6: collect content_blocks from direct <p> and <argument> children
    content_blocks = []
    for child in div_elem:
        if child.tag in _HEADING_TAGS or child.tag in _SKIP_TAGS:
            continue
        if child.tag in ("p", "argument"):
            text = clean_text(get_all_text(child))
            if text:
                content_blocks.append(text)

    # Step 7: collect child sections recursively
    children = []
    for child in div_elem:
        if not _DIV_TAG_RE.match(child.tag):
            continue
        result = parse_div(child, depth + 1)
        if result is None:
            continue
        if isinstance(result, list):
            children.extend(result)
        else:
            children.append(result)

    # Step 8: filter orphan leaf nodes (no content, no children)
    if not content_blocks and not children:
        _parse_warnings.append(
            f"Skipping orphan leaf {div_elem.get('id', '?')} type={div_type!r}"
            f" title={div_elem.get('title', '')!r} (no content)"
        )
        return None

    # Step 9: finalize section_type for heading-only works
    if not section_type:
        # Try to infer from extracted label+title
        heading_text = (label + " " + title).strip() if label else title
        inferred = _infer_section_type_from_heading(heading_text)
        if inferred:
            section_type = inferred
        elif children and not content_blocks:
            section_type = "part"
        elif content_blocks:
            section_type = "chapter"
        else:
            section_type = "section"

    # Steps 10-11: scripture refs and word count
    scripture_refs = get_scriptrefs(div_elem)
    word_count = count_words(content_blocks)

    return {
        "section_type": section_type,
        "label": label or None,
        "title": title or None,
        "content_blocks": content_blocks,
        "scripture_references": scripture_refs,
        "word_count": word_count,
        "children": children,
    }


def parse_work(work_cfg: dict, raw_bytes: bytes) -> dict:
    """
    Parse a single work's raw XML bytes into a structured_text data dict.

    Returns a dict with work_id, work_kind, sections, _source_hash,
    _download_date, and _warnings keys.
    """
    global _parse_warnings
    _parse_warnings = []

    source_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()

    # Backfill download_date from file mtime for pre-cached files
    if not work_cfg.get("download_date"):
        raw_path = _raw_path(work_cfg)
        if raw_path.exists():
            mtime = raw_path.stat().st_mtime
            work_cfg["download_date"] = datetime.fromtimestamp(
                mtime, tz=timezone.utc
            ).strftime("%Y-%m-%d")

    xml_text = preprocess_thml(raw_bytes)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(
            f"XML parse failed for {work_cfg['ccel_id']}: {exc}. "
            "Try re-downloading the file."
        ) from exc

    body = root.find("ThML.body")
    if body is None:
        raise RuntimeError(
            f"No <ThML.body> found in {work_cfg['ccel_id']}. "
            "Unexpected XML structure."
        )

    sections = []
    for div in body:
        if not _DIV_TAG_RE.match(div.tag):
            continue
        result = parse_div(div, depth=0)
        if result is None:
            continue
        if isinstance(result, list):
            sections.extend(result)
        else:
            sections.append(result)

    if not sections:
        _parse_warnings.append(
            f"WARNING: 0 sections after editorial filtering for {work_cfg['ccel_id']}"
        )

    return {
        "work_id": work_cfg["slug"],
        "work_kind": work_cfg["work_kind"],
        "sections": sections,
        "_source_hash": source_hash,
        "_download_date": work_cfg.get("download_date", ""),
        "_warnings": list(_parse_warnings),
    }


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------

def build_meta(work_cfg: dict, parse_result: dict) -> dict:
    """Build the meta envelope for a single work."""
    author_cfg = AUTHOR_CONFIG[work_cfg["author_id"]]
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if "volume_xml" in work_cfg:
        source_url = f"{CCEL_BASE}/{work_cfg['author_ccel_path']}/{work_cfg['volume_xml']}.xml"
    else:
        source_url = f"{CCEL_BASE}/{work_cfg['author_ccel_path']}/{work_cfg['ccel_id']}.xml"

    notes_parts = [
        "ThML HTML entities replaced with Unicode equivalents.",
        "DOCTYPE stripped before parsing.",
        "Footnotes (<note>) and page breaks (<pb>) excluded from content.",
        "robots.txt crawl-delay 10s honoured.",
        "Sourced via CCEL.org.",
    ]
    if "volume_xml" in work_cfg:
        notes_parts.append(
            f"Extracted from {work_cfg['volume_xml']}.xml"
            + (f" div1 id='{work_cfg['volume_div_id']}'" if work_cfg.get("volume_div_id") else "")
            + "."
        )

    return {
        "id": work_cfg["slug"],
        "title": work_cfg["title"],
        "author": author_cfg["author"],
        "author_id": author_cfg["author_id"],
        "author_birth_year": author_cfg["author_birth_year"],
        "author_death_year": author_cfg["author_death_year"],
        "contributors": normalize_contributors(work_cfg.get("contributors", [])),
        "original_publication_year": work_cfg.get("pub_year"),
        "language": author_cfg["language"],
        "original_language": author_cfg["original_language"],
        "tradition": author_cfg["tradition"],
        "tradition_notes": author_cfg["tradition_notes"],
        "era": author_cfg["era"],
        "audience": author_cfg["audience"],
        "license": author_cfg["license"],
        "schema_type": author_cfg["schema_type"],
        "schema_version": author_cfg["schema_version"],
        "completeness": work_cfg.get("completeness") or author_cfg["completeness"],
        "provenance": {
            "source_url": source_url,
            "source_format": "ThML XML",
            "source_edition": work_cfg.get("source_edition", "CCEL ThML edition (sourced via CCEL.org)."),
            "download_date": parse_result.get("_download_date", ""),
            "source_hash": parse_result["_source_hash"],
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/ccel_puritan_works.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": " ".join(notes_parts),
            "source_type": "ccel_thml",
            "source_file": str(_raw_path(work_cfg).relative_to(REPO_ROOT)),
            "translator": None,
        },
    }


# ---------------------------------------------------------------------------
# Source config writer
# ---------------------------------------------------------------------------

def write_source_config(work_cfg: dict, parse_result: dict) -> None:
    """Write sources/structured-text/{slug}/config.json for this work."""
    author_cfg = AUTHOR_CONFIG[work_cfg["author_id"]]
    if "volume_xml" in work_cfg:
        source_url = f"{CCEL_BASE}/{work_cfg['author_ccel_path']}/{work_cfg['volume_xml']}.xml"
    else:
        source_url = f"{CCEL_BASE}/{work_cfg['author_ccel_path']}/{work_cfg['ccel_id']}.xml"
    slug = work_cfg["slug"]
    cfg_dir = SOURCES_DIR / slug
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "resource_id": slug,
        "title": work_cfg["title"],
        "author": author_cfg["author"],
        "author_id": author_cfg["author_id"],
        "author_birth_year": author_cfg["author_birth_year"],
        "author_death_year": author_cfg["author_death_year"],
        "contributors": normalize_contributors(work_cfg.get("contributors", [])),
        "original_publication_year": work_cfg.get("pub_year"),
        "language": author_cfg["language"],
        "original_language": author_cfg["original_language"],
        "tradition": author_cfg["tradition"],
        "tradition_notes": author_cfg["tradition_notes"],
        "era": author_cfg["era"],
        "audience": author_cfg["audience"],
        "license": author_cfg["license"],
        "schema_type": "structured_text",
        "work_kind": work_cfg["work_kind"],
        "source_url": source_url,
        "source_format": "ThML XML",
        "source_edition": work_cfg.get("source_edition", "CCEL ThML edition (sourced via CCEL.org)."),
        "source_hash": parse_result["_source_hash"],
        "source_type": "ccel_thml",
        "source_file": str(_raw_path(work_cfg).relative_to(REPO_ROOT)),
        "translator": None,
        "download_date": parse_result.get("_download_date", ""),
        "output_file": f"data/structured-text/{slug}.json",
        "notes": (
            "CCEL confirmed OK to parse (Quincy, 2026-04-01)."
            " Crawl-delay 10s per robots.txt."
            " ThML entities replaced; DOCTYPE stripped; footnotes excluded."
            + (
                f" Extracted from {work_cfg['volume_xml']}.xml"
                + (f" div1 id='{work_cfg['volume_div_id']}'" if work_cfg.get("volume_div_id") else "")
                + "."
                if "volume_xml" in work_cfg else ""
            )
        ),
    }
    cfg_path = cfg_dir / "config.json"
    with open(cfg_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# ---------------------------------------------------------------------------
# Quality reporting
# ---------------------------------------------------------------------------

def _sum_tree_words(sections: list) -> int:
    """Recursively sum word_count across all section nodes."""
    total = 0
    for s in sections:
        total += s.get("word_count", 0)
        total += _sum_tree_words(s.get("children", []))
    return total


def _count_tree_sections(sections: list) -> int:
    """Recursively count all section nodes."""
    count = len(sections)
    for s in sections:
        count += _count_tree_sections(s.get("children", []))
    return count


def _count_chapters(sections: list) -> int:
    """Recursively count nodes with section_type='chapter'."""
    count = 0
    for s in sections:
        if s.get("section_type") == "chapter":
            count += 1
        count += _count_chapters(s.get("children", []))
    return count


def _find_orphans(sections: list) -> int:
    """Count nodes with 0 content_blocks AND 0 children."""
    count = 0
    for s in sections:
        if not s.get("content_blocks") and not s.get("children"):
            count += 1
        count += _find_orphans(s.get("children", []))
    return count


def report_work_quality(work_cfg: dict, parse_result: dict, log_fn=None) -> None:
    """Print per-work quality stats."""
    if log_fn is None:
        log_fn = lambda m: print(m.encode("ascii", errors="replace").decode("ascii"))
    sections = parse_result["sections"]
    top_count = len(sections)
    chapter_count = _count_chapters(sections)
    total_words = _sum_tree_words(sections)
    total_sec = _count_tree_sections(sections)
    orphans = _find_orphans(sections)

    slug = work_cfg["slug"]
    log_fn(
        f"  {slug}: {top_count} top-level sections,"
        f" {chapter_count} chapters, ~{total_words // 1000}k words"
    )
    if total_sec > 0:
        log_fn(f"  Quality: {total_sec} total nodes, {orphans} orphans")
    for w in parse_result.get("_warnings", []):
        safe_w = w.encode("ascii", errors="replace").decode("ascii")
        log_fn(f"  WARN: {safe_w}")


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Puritan & Reformed works (16 titles, 7 authors) from CCEL ThML XML"
    )
    parser.add_argument(
        "--author",
        metavar="AUTHOR_ID",
        help="Process all works for one author (e.g. watson)",
    )
    parser.add_argument(
        "--work",
        metavar="SLUG",
        help="Process a single work by slug (e.g. watson-body-of-divinity)",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download work(s) from CCEL",
    )
    parser.add_argument(
        "--parse",
        action="store_true",
        help="Parse cached raw files and write JSON output",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if already cached",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Parse first work per author, print to stdout, no file writes",
    )
    args = parser.parse_args()

    if not args.download and not args.parse and not args.dry_run:
        parser.print_help()
        sys.exit(0)

    # Resolve which works to process
    if args.work:
        works = [w for w in WORK_CONFIG if w["slug"] == args.work]
        if not works:
            print(f"ERROR: unknown slug '{args.work}'")
            print(f"Valid slugs: {[w['slug'] for w in WORK_CONFIG]}")
            sys.exit(1)
    elif args.author:
        works = [w for w in WORK_CONFIG if w["author_id"] == args.author]
        if not works:
            print(f"ERROR: unknown author_id '{args.author}'")
            print(f"Valid IDs: {sorted({w['author_id'] for w in WORK_CONFIG})}")
            sys.exit(1)
    else:
        works = list(WORK_CONFIG)

    start_time = time.time()
    log_lines = []

    def log(msg: str) -> None:
        safe = msg.encode("ascii", errors="replace").decode("ascii")
        print(safe)
        log_lines.append(msg)

    errors = 0
    files_written = 0
    works_parsed = 0
    total_sections = 0
    total_words = 0

    try:
        log(f"Puritan & Reformed works parser {SCRIPT_VERSION}")
        log(
            f"Works: {len(works)}"
            f"  download={args.download}"
            f"  parse={args.parse}"
            f"  dry-run={args.dry_run}"
        )
        log("")

        # --- Dry-run mode: first work per author, parse only ---
        if args.dry_run:
            log("=== Dry-run mode (first work per author) ===")
            seen_authors: set = set()
            for work in works:
                aid = work["author_id"]
                if aid in seen_authors:
                    continue
                seen_authors.add(aid)
                raw_path = _raw_path(work)
                if not raw_path.exists():
                    log(f"  SKIP (not cached): {work['slug']} -- run --download first")
                    continue
                log(f"  Parsing {work['slug']} ...")
                try:
                    raw_bytes = raw_path.read_bytes()
                    parse_result = parse_work(work, raw_bytes)
                except RuntimeError as exc:
                    log(f"  ERROR: {exc}")
                    errors += 1
                    continue
                report_work_quality(work, parse_result, log_fn=log)
                # Print first 3 sections to stdout
                for i, sec in enumerate(parse_result["sections"][:3]):
                    safe_title = (sec.get("title") or "").encode("ascii", errors="replace").decode("ascii")
                    safe_blocks = " | ".join(
                        b[:80].encode("ascii", errors="replace").decode("ascii")
                        for b in sec.get("content_blocks", [])[:1]
                    )
                    log(
                        f"    [{i}] type={sec['section_type']!r}"
                        f" label={sec.get('label')!r}"
                        f" title={safe_title!r}"
                        f" blocks={len(sec.get('content_blocks', []))}"
                        f" children={len(sec.get('children', []))}"
                    )
                    if safe_blocks:
                        log(f"         sample: {safe_blocks[:120]}")
                log("")
            log("=== Dry-run complete ===")
            return

        # --- Download phase ---
        if args.download:
            log("=== Download phase ===")
            for i, work in enumerate(works):
                raw_path = _raw_path(work)
                if raw_path.exists() and not args.force:
                    log(f"  [{i+1}/{len(works)}] {work['ccel_id']}: cached, skipping")
                    continue
                if i > 0:
                    log(f"  Waiting {CRAWL_DELAY}s (robots.txt crawl-delay) ...")
                    time.sleep(CRAWL_DELAY)
                log(f"  [{i+1}/{len(works)}] {work['slug']} ...")
                try:
                    download_work(work, force=args.force, log_fn=log)
                except RuntimeError as exc:
                    log(f"  ERROR (download): {exc}")
                    errors += 1
            log("")

        # --- Parse phase ---
        if args.parse:
            log("=== Parse phase ===")
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            for i, work in enumerate(works):
                raw_path = _raw_path(work)
                if not raw_path.exists():
                    log(
                        f"  ERROR: raw file missing for {work['ccel_id']}."
                        " Run --download first."
                    )
                    errors += 1
                    continue

                log(f"  [{i+1}/{len(works)}] Parsing {work['slug']} ...")
                try:
                    raw_bytes = raw_path.read_bytes()
                    parse_result = parse_work(work, raw_bytes)
                except RuntimeError as exc:
                    log(f"  ERROR (parse): {exc}")
                    errors += 1
                    continue

                report_work_quality(work, parse_result, log_fn=log)

                # Build and write output JSON
                out_path = OUTPUT_DIR / f"{work['slug']}.json"
                try:
                    meta = build_meta(work, parse_result)
                    data = {
                        "work_id": parse_result["work_id"],
                        "work_kind": parse_result["work_kind"],
                        "sections": parse_result["sections"],
                    }
                    output = {"meta": meta, "data": data}
                    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
                        json.dump(output, fh, ensure_ascii=False, indent=2)
                        fh.write("\n")
                except Exception as exc:
                    if out_path.exists():
                        out_path.unlink()  # standards: log/temp rotation
                    log(f"  ERROR (write JSON): {work['slug']}: {exc}")
                    errors += 1
                    continue
                # Write source config separately -- failure here does not invalidate the JSON
                try:
                    write_source_config(work, parse_result)
                except Exception as exc:
                    log(f"  WARN (source config): {work['slug']}: {exc}")

                size_kb = out_path.stat().st_size // 1024
                log(f"  Wrote {size_kb} KB -> {out_path.name}")
                files_written += 1
                works_parsed += 1
                total_sections += _count_tree_sections(parse_result["sections"])
                total_words += _sum_tree_words(parse_result["sections"])
                log("")

            # Summary
            total_words_m = total_words / 1_000_000
            log(
                f"TOTAL: {works_parsed} works parsed,"
                f" {total_sections} total sections,"
                f" ~{total_words_m:.1f}M words"
            )

    finally:
        elapsed = time.time() - start_time
        summary = (
            f"Done in {elapsed:.1f}s. "
            f"Works parsed: {works_parsed}/{len(works)}. "
            f"Files written: {files_written}. "
            f"Errors: {errors}."
        )
        log(summary)
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(log_lines) + "\n")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
