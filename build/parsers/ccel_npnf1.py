"""ccel_npnf1.py
Parser for NPNF Series 1 works from CCEL ThML XML.

BATCH A: Augustine of Hippo, NPNF1-01 through NPNF1-08 (committed 2026-04-23).
BATCH B: John Chrysostom, NPNF1-09 through NPNF1-14 (added 2026-04-28).

Source: Nicene and Post-Nicene Fathers, Series 1. Philip Schaff (ed.).
New York: Christian Literature Publishing Co., 1886-1889.
CCEL confirmed OK to parse (Quincy, 2026-04-01).
robots.txt: crawl-delay 10 for all agents (confirmed 2026-04-23).

XML structure (censused 2026-04-23 from full downloads of npnf101-npnf108):
  Root: <ThML> with no namespaces; DOCTYPE stripped before parsing.
  Header: <ThML.head> (metadata, skipped).
  Body: <ThML.body> containing div1 elements.

  Work demarcation varies by volume:
    npnf101: div1 'vi' = Confessions (Books at div2); div1 'vii' = Letters (Division at div2)
    npnf102: div1 'iv' = City of God (22 Books at div2); div1 'v' = On Christian Doctrine (4 Books)
    npnf103: div1 'iv' groups Doctrinal Treatises; each div2 = separate work, div3 = sections
    npnf103: div1 'v' groups Moral Treatises; same div2/div3 pattern
    npnf104: div1 'iv' groups Anti-Manichaean; div1 'v' groups Anti-Donatist; works at div2
    npnf105: Anti-Pelagian; each work has its OWN div1 (div1 'x' through 'xxi'); sections at div2
    npnf106: div1 'v' = Sermon on Mount; div1 'vi' = Harmony; div1 'vii' = Sermons (99 at div2)
    npnf107: div1 'iii' = Tractates on John (125 Tractates at div2); div1 'iv' = 1 John Homilies;
             div1 'v' = Soliloquies
    npnf108: div1 'ii' = Psalms (150 Psalms at div2, bundled into one output file)

  When div2_id is set in work config: the parser drills into that specific div2 and treats
  its div3 children as the top-level sections. Used for works at div2 level (npnf103, npnf104).
  When div2_id is None: the div1 is the work root and div2 children are the sections.

  New div2 type= values found in NPNF1 (beyond what church_history.py handles):
    type='Tractate'  -> section_type='chapter'  (npnf107 John tractates)
    type='Homily'    -> section_type='chapter'  (npnf107 1 John homilies)
    type='Sermon'    -> section_type='chapter'  (npnf106 selected lessons)
    type='Division'  -> section_type='book'     (npnf101 letters division)

  Editorial content skipped: Title Pages, Prefaces, Indexes, Introductory Essays,
  Retractations extracts, Advertisements, Arguments, Credits, Dedications.

  Q1 provenance fields added to every record:
    source_type: "ccel_thml"
    source_file: relative path to cached raw XML
    translator: "Philip Schaff (ed.), 1886"
    (source_url and source_hash already present from church_history pattern)

  Note: the prompt swapped descriptions for npnf104 and npnf105. Census confirmed:
    npnf104 = Anti-Manichaean + Anti-Donatist (not Anti-Pelagian as the prompt said)
    npnf105 = Anti-Pelagian (not Anti-Manichaean/Donatist as the prompt said)

  npnf108 (Psalms, 6MB) bundled into one output file per-psalm structure decision.

  Batch B census (2026-04-28, npnf109-npnf114):
    npnf109: 16 div1 content works (one file per div1; iii Prolegomena and
      indexes skipped). Includes On the Priesthood (treatise), shorter ascetic
      treatises, occasional homilies, Letters to Olympias, Letters to Rome,
      Homilies on the Statues.
    npnf110: 1 work, div1 'iii' = Homilies on Matthew (86 Homily div2s; some
      ids carry '_1' suffix from CCEL dedup; Title Page / Preface to the Oxford
      Edition / Introductory Essay filtered as editorial).
    npnf111: 2 works, div1 'vi' = Homilies on Acts (55 untyped div2s, all titled
      'Homily X on Acts ...'); div1 'vii' = Homilies on Romans (32 actual
      homilies + 'Preface to Homilies on Romans' + 'The Argument' filtered).
    npnf112: 2 works, div1 'iv' = Homilies on 1 Corinthians (44 Homily + 1
      'Argument' filtered); div1 'v' = Homilies on 2 Corinthians (30 Homily).
    npnf113: 10 separate per-epistle output files, each pointing at a div2 inside
      its container div1 (Galatians, Ephesians, Philippians, Colossians,
      1 & 2 Thessalonians, 1 & 2 Timothy, Titus, Philemon). Galatians is
      Commentary (6 Chapter div3s); the rest are Homily div3s. Per-epistle
      'Argument' / 'Introductory Discourse' div3s filtered as editorial.
    npnf114: 2 works, div1 'iv' = Homilies on John (88 Homily div2s; Title Page
      and Preface filtered); div1 'v' = Homilies on Hebrews (34 Homily div2s;
      4 prefatory div2s filtered).

  Batch B parser fix (in is_editorial_div): when div2 type is a known content
  type (Homily, Sermon, Tractate, Letter, Chapter, Book, Demonstration,
  Dialogue, Division), the title-based editorial filter is bypassed. NPNF1-14's
  Homily I on John is titled 'Preface.' which would otherwise be swallowed.

  Note: NPNF1-10 publishes 86 Homilies on Matthew (Greek MS tradition), not the
  90 sometimes cited from PG numbering. Expected counts in tests reflect the
  actual XML, not external catalogues.

  Author: John Chrysostom (author_id 'john-chrysostom' per registry; the prompt
  used 'chrysostom-john' but the registry was already populated with
  'john-chrysostom' from prior church_fathers data — primary source wins).

Usage:
    py -3 build/parsers/ccel_npnf1.py --volume npnf101 --download --dry-run
    py -3 build/parsers/ccel_npnf1.py --work augustine-confessions --parse
    py -3 build/parsers/ccel_npnf1.py --batch a --download --parse
    py -3 build/parsers/ccel_npnf1.py --batch a --parse
    py -3 build/parsers/ccel_npnf1.py --dry-run
"""

import argparse
import hashlib
import json
import re
import sys
import time
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
    STRUCTURED_TEXT__DATA__WORK_KIND,
    STRUCTURED_TEXT__META__AUDIENCE,
    STRUCTURED_TEXT__META__COMPLETENESS,
    STRUCTURED_TEXT__META__ERA,
    STRUCTURED_TEXT__META__TRADITION,
)
from build.lib.contributors import normalize_contributors  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

RAW_DIR = REPO_ROOT / "raw" / "ccel" / "npnf1"
OUTPUT_DIR = REPO_ROOT / "data" / "structured-text"
LOG_FILE = Path(__file__).resolve().parent / "ccel_npnf1.log"

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.1.0"
CRAWL_DELAY = 10
UA = "OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)"

_NPNF1_SOURCE_EDITION = (
    "Nicene and Post-Nicene Fathers, Series 1. "
    "Philip Schaff (ed.). New York: Christian Literature Publishing Co., 1886-1889."
)

_AUGUSTINE = {
    "author": "Augustine of Hippo",
    "author_id": "augustine-of-hippo",
    "author_birth_year": 354,
    "author_death_year": 430,
    "original_language": "la",
    "tradition": ["patristic", "ecumenical"],
    "era": "patristic",
    "audience": "scholarly",
}

_CHRYSOSTOM = {
    "author": "John Chrysostom",
    "author_id": "john-chrysostom",
    "author_birth_year": 347,
    "author_death_year": 407,
    "original_language": "grc",
    "tradition": ["patristic", "ecumenical"],
    "era": "patristic",
    "audience": "scholarly",
}

_CHRYSOSTOM_TRANSLATORS = {
    "npnf109": "W.R.W. Stephens, T.P. Brandram (translators); Philip Schaff (ed.), 1889",
    "npnf110": "George Prevost (translator, rev. M.B. Riddle); Philip Schaff (ed.), 1888",
    "npnf111": "J. Walker, J. Sheppard, H. Browne (translators, rev. George B. Stevens); Philip Schaff (ed.), 1889",
    "npnf112": "Talbot W. Chambers (translator, rev. of Oxford ed.); Philip Schaff (ed.), 1889",
    "npnf113": "Gross Alexander, John A. Broadus, Philip Schaff (translators, eds.); Philip Schaff (ed.), 1889",
    "npnf114": "G.T. Stupart, F. Gardiner (translators, rev. Frederic Gardiner); Philip Schaff (ed.), 1889",
}

# ---------------------------------------------------------------------------
# VOLUME_CONFIG
# ---------------------------------------------------------------------------
# Each work entry may include:
#   div1_id  (str)  - id= attribute of the div1 containing this work
#   div2_id  (str|None) - if set, parse from this specific div2 within div1
#   All other keys are metadata.

VOLUME_CONFIG = {
    # ------------------------------------------------------------------
    # NPNF1-01: Prolegomena; Confessions; Letters (Part 1)
    # ------------------------------------------------------------------
    "npnf101": {
        "url": "https://www.ccel.org/ccel/schaff/npnf101.xml",
        "raw_file": RAW_DIR / "npnf101.xml",
        "source_edition": _NPNF1_SOURCE_EDITION,
        "translator": "Philip Schaff (ed.), 1886",
        "works": [
            {
                "slug": "augustine-confessions",
                "div1_id": "vi",
                "div2_id": None,
                "title": "The Confessions of St. Augustin",
                "work_kind": "devotional-classic",
                "original_publication_year": 397,
                "completeness": "full",
                "contributors": [
                    "J.G. Pilkington (translator, 1876)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-letters-part-1",
                "div1_id": "vii",
                "div2_id": None,
                "title": "Letters of St. Augustin (Part 1)",
                "work_kind": "theological-work",
                "original_publication_year": None,
                "completeness": "partial",
                "contributors": [
                    "J.G. Cunningham (translator, 1853)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
        ],
    },
    # ------------------------------------------------------------------
    # NPNF1-02: City of God; On Christian Doctrine
    # ------------------------------------------------------------------
    "npnf102": {
        "url": "https://www.ccel.org/ccel/schaff/npnf102.xml",
        "raw_file": RAW_DIR / "npnf102.xml",
        "source_edition": _NPNF1_SOURCE_EDITION,
        "translator": "Philip Schaff (ed.), 1886",
        "works": [
            {
                "slug": "augustine-city-of-god",
                "div1_id": "iv",
                "div2_id": None,
                "title": "The City of God",
                "work_kind": "theological-work",
                "original_publication_year": 413,
                "completeness": "full",
                "contributors": [
                    "Marcus Dods (translator, 1871)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-on-christian-doctrine",
                "div1_id": "v",
                "div2_id": None,
                "title": "On Christian Doctrine",
                "work_kind": "treatise",
                "original_publication_year": 397,
                "completeness": "full",
                "contributors": [
                    "J.F. Shaw (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
        ],
    },
    # ------------------------------------------------------------------
    # NPNF1-03: Doctrinal & Moral Treatises
    # Works are at div2 level within group div1s; div2_id is set for each.
    # ------------------------------------------------------------------
    "npnf103": {
        "url": "https://www.ccel.org/ccel/schaff/npnf103.xml",
        "raw_file": RAW_DIR / "npnf103.xml",
        "source_edition": _NPNF1_SOURCE_EDITION,
        "translator": "Philip Schaff (ed.), 1886",
        "works": [
            {
                "slug": "augustine-on-the-trinity",
                "div1_id": "iv",
                "div2_id": "iv.i",
                "title": "On the Holy Trinity",
                "work_kind": "theological-work",
                "original_publication_year": 399,
                "completeness": "full",
                "contributors": [
                    "Arthur West Haddan (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-enchiridion",
                "div1_id": "iv",
                "div2_id": "iv.ii",
                "title": "The Enchiridion",
                "work_kind": "treatise",
                "original_publication_year": 420,
                "completeness": "full",
                "contributors": [
                    "J.F. Shaw (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-catechising-uninstructed",
                "div1_id": "iv",
                "div2_id": "iv.iii",
                "title": "On the Catechising of the Uninstructed",
                "work_kind": "treatise",
                "original_publication_year": 400,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-faith-and-creed",
                "div1_id": "iv",
                "div2_id": "iv.iv",
                "title": "A Treatise on Faith and the Creed",
                "work_kind": "treatise",
                "original_publication_year": 393,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-faith-things-not-seen",
                "div1_id": "iv",
                "div2_id": "iv.v",
                "title": "Concerning Faith of Things Not Seen",
                "work_kind": "treatise",
                "original_publication_year": None,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-profit-of-believing",
                "div1_id": "iv",
                "div2_id": "iv.vi",
                "title": "On the Profit of Believing",
                "work_kind": "treatise",
                "original_publication_year": 391,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-on-the-creed",
                "div1_id": "iv",
                "div2_id": "iv.vii",
                "title": "On the Creed: A Sermon to the Competentes",
                "work_kind": "treatise",
                "original_publication_year": None,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-on-continence",
                "div1_id": "v",
                "div2_id": "v.i",
                "title": "On Continence",
                "work_kind": "treatise",
                "original_publication_year": None,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-good-of-marriage",
                "div1_id": "v",
                "div2_id": "v.ii",
                "title": "On the Good of Marriage",
                "work_kind": "treatise",
                "original_publication_year": 401,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-holy-virginity",
                "div1_id": "v",
                "div2_id": "v.iii",
                "title": "Of Holy Virginity",
                "work_kind": "treatise",
                "original_publication_year": 401,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-good-of-widowhood",
                "div1_id": "v",
                "div2_id": "v.iv",
                "title": "On the Good of Widowhood",
                "work_kind": "treatise",
                "original_publication_year": 414,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-on-lying",
                "div1_id": "v",
                "div2_id": "v.v",
                "title": "On Lying",
                "work_kind": "treatise",
                "original_publication_year": 395,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-against-lying",
                "div1_id": "v",
                "div2_id": "v.vi",
                "title": "Against Lying",
                "work_kind": "treatise",
                "original_publication_year": 420,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-work-of-monks",
                "div1_id": "v",
                "div2_id": "v.vii",
                "title": "Of the Work of Monks",
                "work_kind": "treatise",
                "original_publication_year": 401,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-on-patience",
                "div1_id": "v",
                "div2_id": "v.viii",
                "title": "On Patience",
                "work_kind": "treatise",
                "original_publication_year": None,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-care-for-dead",
                "div1_id": "v",
                "div2_id": "v.ix",
                "title": "On Care to Be Had for the Dead",
                "work_kind": "treatise",
                "original_publication_year": None,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
        ],
    },
    # ------------------------------------------------------------------
    # NPNF1-04: Anti-Manichaean & Anti-Donatist Writings
    # (Prompt description was swapped -- census confirms 104 = Mani+Donat)
    # Works at div2 level within group div1s.
    # ------------------------------------------------------------------
    "npnf104": {
        "url": "https://www.ccel.org/ccel/schaff/npnf104.xml",
        "raw_file": RAW_DIR / "npnf104.xml",
        "source_edition": _NPNF1_SOURCE_EDITION,
        "translator": "Philip Schaff (ed.), 1886",
        "works": [
            {
                "slug": "augustine-morals-catholic-church",
                "div1_id": "iv",
                "div2_id": "iv.iv",
                "title": "On the Morals of the Catholic Church",
                "work_kind": "treatise",
                "original_publication_year": 388,
                "completeness": "full",
                "contributors": [
                    "Richard Stothert (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-morals-manichaeans",
                "div1_id": "iv",
                "div2_id": "iv.v",
                "title": "On the Morals of the Manichaeans",
                "work_kind": "treatise",
                "original_publication_year": 388,
                "completeness": "full",
                "contributors": [
                    "Richard Stothert (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-on-two-souls",
                "div1_id": "iv",
                "div2_id": "iv.vi",
                "title": "On Two Souls, Against the Manichaeans",
                "work_kind": "treatise",
                "original_publication_year": 391,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-against-fortunatus",
                "div1_id": "iv",
                "div2_id": "iv.vii",
                "title": "Acts or Disputation Against Fortunatus the Manichaean",
                "work_kind": "treatise",
                "original_publication_year": 392,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-against-epistle-of-manichaeus",
                "div1_id": "iv",
                "div2_id": "iv.viii",
                "title": "Against the Epistle of Manichaeus Called Fundamental",
                "work_kind": "treatise",
                "original_publication_year": 397,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-reply-to-faustus",
                "div1_id": "iv",
                "div2_id": "iv.ix",
                "title": "Reply to Faustus the Manichaean",
                "work_kind": "treatise",
                "original_publication_year": 400,
                "completeness": "full",
                "contributors": [
                    "Richard Stothert (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-nature-of-good",
                "div1_id": "iv",
                "div2_id": "iv.x",
                "title": "Concerning the Nature of Good, Against the Manichaeans",
                "work_kind": "treatise",
                "original_publication_year": 405,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-on-baptism",
                "div1_id": "v",
                "div2_id": "v.iv",
                "title": "On Baptism, Against the Donatists",
                "work_kind": "treatise",
                "original_publication_year": 400,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-answer-to-petilian",
                "div1_id": "v",
                "div2_id": "v.v",
                "title": "Answer to the Letters of Petilian, the Donatist",
                "work_kind": "treatise",
                "original_publication_year": 400,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-correction-of-donatists",
                "div1_id": "v",
                "div2_id": "v.vi",
                "title": "The Correction of the Donatists",
                "work_kind": "treatise",
                "original_publication_year": 417,
                "completeness": "full",
                "contributors": ["Philip Schaff (series editor)"],
                **_AUGUSTINE,
            },
        ],
    },
    # ------------------------------------------------------------------
    # NPNF1-05: Anti-Pelagian Works
    # (Prompt called this Anti-Manichaean -- census confirms it is Anti-Pelagian)
    # Each work has its OWN div1 (x through xxi); div2_id is None for all.
    # ------------------------------------------------------------------
    "npnf105": {
        "url": "https://www.ccel.org/ccel/schaff/npnf105.xml",
        "raw_file": RAW_DIR / "npnf105.xml",
        "source_edition": _NPNF1_SOURCE_EDITION,
        "translator": "Philip Schaff (ed.), 1886",
        "works": [
            {
                "slug": "augustine-merits-forgiveness-sins",
                "div1_id": "x",
                "div2_id": None,
                "title": "A Treatise on the Merits and Forgiveness of Sins, and on the Baptism of Infants",
                "work_kind": "treatise",
                "original_publication_year": 412,
                "completeness": "full",
                "contributors": [
                    "Peter Holmes (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-spirit-and-letter",
                "div1_id": "xi",
                "div2_id": None,
                "title": "A Treatise on the Spirit and the Letter",
                "work_kind": "treatise",
                "original_publication_year": 412,
                "completeness": "full",
                "contributors": [
                    "Peter Holmes (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-nature-and-grace",
                "div1_id": "xii",
                "div2_id": None,
                "title": "A Treatise on Nature and Grace",
                "work_kind": "treatise",
                "original_publication_year": 415,
                "completeness": "full",
                "contributors": [
                    "Peter Holmes (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-perfection-in-righteousness",
                "div1_id": "xiii",
                "div2_id": None,
                "title": "A Treatise Concerning Man's Perfection in Righteousness",
                "work_kind": "treatise",
                "original_publication_year": 415,
                "completeness": "full",
                "contributors": [
                    "Robert Ernest Wallis (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-proceedings-of-pelagius",
                "div1_id": "xiv",
                "div2_id": None,
                "title": "A Work on the Proceedings of Pelagius",
                "work_kind": "treatise",
                "original_publication_year": 417,
                "completeness": "full",
                "contributors": [
                    "Peter Holmes (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-grace-of-christ-original-sin",
                "div1_id": "xv",
                "div2_id": None,
                "title": "A Treatise on the Grace of Christ, and on Original Sin",
                "work_kind": "treatise",
                "original_publication_year": 418,
                "completeness": "full",
                "contributors": [
                    "Peter Holmes (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-marriage-and-concupiscence",
                "div1_id": "xvi",
                "div2_id": None,
                "title": "On Marriage and Concupiscence",
                "work_kind": "treatise",
                "original_publication_year": 419,
                "completeness": "full",
                "contributors": [
                    "Peter Holmes (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-soul-and-its-origin",
                "div1_id": "xvii",
                "div2_id": None,
                "title": "A Treatise on the Soul and Its Origin",
                "work_kind": "treatise",
                "original_publication_year": 420,
                "completeness": "full",
                "contributors": [
                    "Robert Ernest Wallis (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-against-two-letters-pelagians",
                "div1_id": "xviii",
                "div2_id": None,
                "title": "A Treatise Against Two Letters of the Pelagians",
                "work_kind": "treatise",
                "original_publication_year": 420,
                "completeness": "full",
                "contributors": [
                    "Peter Holmes (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-grace-and-free-will",
                "div1_id": "xix",
                "div2_id": "xix.iv",
                "title": "A Treatise on Grace and Free Will",
                "work_kind": "treatise",
                "original_publication_year": 426,
                "completeness": "full",
                "contributors": [
                    "Peter Holmes (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-rebuke-and-grace",
                "div1_id": "xx",
                "div2_id": None,
                "title": "A Treatise on Rebuke and Grace",
                "work_kind": "treatise",
                "original_publication_year": 427,
                "completeness": "full",
                "contributors": [
                    "Robert Ernest Wallis (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-predestination-of-saints",
                "div1_id": "xxi",
                "div2_id": None,
                "title": "A Treatise on the Predestination of the Saints",
                "work_kind": "treatise",
                "original_publication_year": 428,
                "completeness": "full",
                "contributors": [
                    "Robert Ernest Wallis (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
        ],
    },
    # ------------------------------------------------------------------
    # NPNF1-06: Sermon on the Mount; Harmony of Gospels; Selected Sermons
    # ------------------------------------------------------------------
    "npnf106": {
        "url": "https://www.ccel.org/ccel/schaff/npnf106.xml",
        "raw_file": RAW_DIR / "npnf106.xml",
        "source_edition": _NPNF1_SOURCE_EDITION,
        "translator": "Philip Schaff (ed.), 1886",
        "works": [
            {
                "slug": "augustine-sermon-on-the-mount",
                "div1_id": "v",
                "div2_id": None,
                "title": "Our Lord's Sermon on the Mount",
                "work_kind": "treatise",
                "original_publication_year": 393,
                "completeness": "full",
                "contributors": [
                    "W. Findlay (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-harmony-of-gospels",
                "div1_id": "vi",
                "div2_id": None,
                "title": "The Harmony of the Gospels",
                "work_kind": "treatise",
                "original_publication_year": 400,
                "completeness": "full",
                "contributors": [
                    "S.D.F. Salmond (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-sermons-selected-lessons",
                "div1_id": "vii",
                "div2_id": None,
                "title": "Sermons on Selected Lessons of the New Testament",
                "work_kind": "theological-work",
                "original_publication_year": None,
                "completeness": "partial",
                "contributors": [
                    "R.G. MacMullen (translator, 1844)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
        ],
    },
    # ------------------------------------------------------------------
    # NPNF1-07: Tractates on John; Homilies on 1 John; Soliloquies
    # ------------------------------------------------------------------
    "npnf107": {
        "url": "https://www.ccel.org/ccel/schaff/npnf107.xml",
        "raw_file": RAW_DIR / "npnf107.xml",
        "source_edition": _NPNF1_SOURCE_EDITION,
        "translator": "Philip Schaff (ed.), 1886",
        "works": [
            {
                "slug": "augustine-tractates-on-john",
                "div1_id": "iii",
                "div2_id": None,
                "title": "Lectures or Tractates on the Gospel According to St. John",
                "work_kind": "theological-work",
                "original_publication_year": 406,
                "completeness": "full",
                "contributors": [
                    "John Gibb (translator, 1873)",
                    "James Innes (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-homilies-on-first-john",
                "div1_id": "iv",
                "div2_id": None,
                "title": "Ten Homilies on the First Epistle of John",
                "work_kind": "theological-work",
                "original_publication_year": 415,
                "completeness": "full",
                "contributors": [
                    "H. Browne (translator, 1873)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
            {
                "slug": "augustine-soliloquies",
                "div1_id": "v",
                "div2_id": None,
                "title": "The Soliloquies of St. Augustin",
                "work_kind": "devotional-classic",
                "original_publication_year": 386,
                "completeness": "full",
                "contributors": [
                    "C.C. Starbuck (translator, 1888)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
        ],
    },
    # ------------------------------------------------------------------
    # NPNF1-08: Expositions on the Book of Psalms
    # Bundled into one output file: 150 Psalms as sections within one work.
    # Census: div1 'ii' has 150 Psalm div2s (ii.I_1 through ii.CL or similar).
    # ------------------------------------------------------------------
    "npnf108": {
        "url": "https://www.ccel.org/ccel/schaff/npnf108.xml",
        "raw_file": RAW_DIR / "npnf108.xml",
        "source_edition": _NPNF1_SOURCE_EDITION,
        "translator": "Philip Schaff (ed.), 1886",
        "works": [
            {
                "slug": "augustine-expositions-on-psalms",
                "div1_id": "ii",
                "div2_id": None,
                "title": "Expositions on the Book of Psalms",
                "work_kind": "theological-work",
                "original_publication_year": 391,
                "completeness": "full",
                "contributors": [
                    "A. Cleveland Coxe (editor, 1847)",
                    "Philip Schaff (series editor)",
                ],
                **_AUGUSTINE,
            },
        ],
    },
    # ------------------------------------------------------------------
    # NPNF1-09: On the Priesthood; Ascetic Treatises; Select Homilies & Letters
    # 16 separate output files, one per content div1 (iii Prolegomena and the
    # two trailing Indexes div1s are skipped as editorial).
    # ------------------------------------------------------------------
    "npnf109": {
        "url": "https://www.ccel.org/ccel/schaff/npnf109.xml",
        "raw_file": RAW_DIR / "npnf109.xml",
        "source_edition": _NPNF1_SOURCE_EDITION,
        "translator": _CHRYSOSTOM_TRANSLATORS["npnf109"],
        "works": [
            {
                "slug": "chrysostom-on-the-priesthood",
                "div1_id": "iv",
                "div2_id": None,
                "title": "Treatise Concerning the Christian Priesthood",
                "work_kind": "treatise",
                "original_publication_year": 388,
                "completeness": "full",
                "strip_lead_intro": True,  # first section = Stephens/Schaff translator intro
                "contributors": [
                    "W.R.W. Stephens (translator, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-exhortation-to-theodore",
                "div1_id": "v",
                "div2_id": None,
                "title": "An Exhortation to Theodore After His Fall",
                "work_kind": "theological-work",
                "original_publication_year": 369,
                "completeness": "full",
                "strip_lead_intro": True,  # first section = translator intro
                "contributors": [
                    "W.R.W. Stephens (translator, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-letter-to-young-widow",
                "div1_id": "vi",
                "div2_id": None,
                "title": "Letter to a Young Widow",
                "work_kind": "theological-work",
                "original_publication_year": 380,
                "completeness": "full",
                "strip_lead_intro": True,  # first section = translator intro
                "contributors": [
                    "W.R.W. Stephens (translator, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homilies-ignatius-and-babylas",
                "div1_id": "vii",
                "div2_id": None,
                "title": "Homilies on S. Ignatius and S. Babylas",
                "work_kind": "theological-work",
                "original_publication_year": 387,
                "completeness": "full",
                "strip_lead_intro": True,  # first section = translator intro
                "contributors": [
                    "T.P. Brandram (translator, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homily-on-lowliness-of-mind",
                "div1_id": "viii",
                "div2_id": None,
                "title": "Homily Concerning Lowliness of Mind",
                "work_kind": "theological-work",
                "original_publication_year": None,
                "completeness": "full",
                "strip_lead_intro": True,  # first section = translator intro
                "contributors": [
                    "T.P. Brandram (translator, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-instructions-to-catechumens",
                "div1_id": "ix",
                "div2_id": None,
                "title": "Instructions to Catechumens",
                "work_kind": "treatise",
                "original_publication_year": 388,
                "completeness": "full",
                "contributors": [
                    "T.P. Brandram (translator, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-three-homilies-on-power-of-demons",
                "div1_id": "x",
                "div2_id": None,
                "title": "Three Homilies Concerning the Power of Demons",
                "work_kind": "theological-work",
                "original_publication_year": 388,
                "completeness": "full",
                "strip_lead_intro": True,  # first section = translator intro
                "contributors": [
                    "T.P. Brandram (translator, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homily-on-father-if-it-be-possible",
                "div1_id": "xi",
                "div2_id": None,
                "title": "Homily on the Passage 'Father, If It Be Possible...'",
                "work_kind": "theological-work",
                "original_publication_year": None,
                "completeness": "full",
                "contributors": [
                    "T.P. Brandram (translator, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homily-on-the-paralytic",
                "div1_id": "xii",
                "div2_id": None,
                "title": "Homily on the Paralytic Let Down Through the Roof",
                "work_kind": "theological-work",
                "original_publication_year": None,
                "completeness": "full",
                "contributors": [
                    "T.P. Brandram (translator, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homily-to-those-not-attended-assembly",
                "div1_id": "xiii",
                "div2_id": None,
                "title": "Homily to Those Who Had Not Attended the Assembly",
                "work_kind": "theological-work",
                "original_publication_year": None,
                "completeness": "full",
                "contributors": [
                    "T.P. Brandram (translator, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homily-against-publishing-errors",
                "div1_id": "xiv",
                "div2_id": None,
                "title": "Homily Against Publishing the Errors of the Brethren",
                "work_kind": "theological-work",
                "original_publication_year": None,
                "completeness": "full",
                "contributors": [
                    "T.P. Brandram (translator, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-two-homilies-on-eutropius",
                "div1_id": "xv",
                "div2_id": None,
                "title": "Two Homilies on Eutropius",
                "work_kind": "theological-work",
                "original_publication_year": 399,
                "completeness": "full",
                "strip_lead_intro": True,  # first section = translator intro
                "contributors": [
                    "T.P. Brandram (translator, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-no-one-can-be-harmed",
                "div1_id": "xvi",
                "div2_id": None,
                "title": "Treatise to Prove That No One Can Harm the Man Who Does Not Injure Himself",
                "work_kind": "treatise",
                "original_publication_year": 406,
                "completeness": "full",
                "strip_lead_intro": True,  # first section = translator intro
                "contributors": [
                    "W.R.W. Stephens (translator, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-letters-to-olympias",
                "div1_id": "xvii",
                "div2_id": None,
                "title": "Letters of St. Chrysostom to Olympias",
                "work_kind": "theological-work",
                "original_publication_year": 404,
                "completeness": "partial",
                "strip_lead_intro": True,  # first section = translator intro
                "contributors": [
                    "W.R.W. Stephens (translator, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-correspondence-with-rome",
                "div1_id": "xviii",
                "div2_id": None,
                "title": "Correspondence of St. Chrysostom with the Bishop of Rome",
                "work_kind": "theological-work",
                "original_publication_year": 404,
                "completeness": "full",
                "strip_lead_intro": True,  # first section = translator intro
                "contributors": [
                    "W.R.W. Stephens (translator, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homilies-on-the-statues",
                "div1_id": "xix",
                "div2_id": None,
                "title": "The Homilies on the Statues to the People of Antioch",
                "work_kind": "theological-work",
                "original_publication_year": 387,
                "completeness": "full",
                "contributors": [
                    "W.R.W. Stephens (translator, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
        ],
    },
    # ------------------------------------------------------------------
    # NPNF1-10: Homilies on the Gospel of Matthew (86 homilies)
    # Single work; div1 'iii' contains 86 Homily div2s plus 3 prefatory
    # (Title Page, Preface to Oxford Edition, Introductory Essay) which the
    # editorial filter handles via title regex.
    # ------------------------------------------------------------------
    "npnf110": {
        "url": "https://www.ccel.org/ccel/schaff/npnf110.xml",
        "raw_file": RAW_DIR / "npnf110.xml",
        "source_edition": _NPNF1_SOURCE_EDITION,
        "translator": _CHRYSOSTOM_TRANSLATORS["npnf110"],
        "works": [
            {
                "slug": "chrysostom-homilies-on-matthew",
                "div1_id": "iii",
                "div2_id": None,
                "title": "Homilies on the Gospel of Matthew",
                "work_kind": "theological-work",
                "original_publication_year": 390,
                "completeness": "full",
                "strip_ccel_title_blocks": 5,  # drops 4 title frags + 1 Greek-char noise block
                "contributors": [
                    "George Prevost (translator, 1843)",
                    "M.B. Riddle (reviser, 1888)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
        ],
    },
    # ------------------------------------------------------------------
    # NPNF1-11: Homilies on Acts (55) and Romans (32)
    # Acts div2s are untyped but every title begins 'Homily X on Acts ...'.
    # Romans has 'Preface to Homilies on Romans' + 'The Argument' as untyped
    # editorial div2s ahead of 32 untyped homily div2s.
    # ------------------------------------------------------------------
    "npnf111": {
        "url": "https://www.ccel.org/ccel/schaff/npnf111.xml",
        "raw_file": RAW_DIR / "npnf111.xml",
        "source_edition": _NPNF1_SOURCE_EDITION,
        "translator": _CHRYSOSTOM_TRANSLATORS["npnf111"],
        "works": [
            {
                "slug": "chrysostom-homilies-on-acts",
                "div1_id": "vi",
                "div2_id": None,
                "title": "Homilies on the Acts of the Apostles",
                "work_kind": "theological-work",
                "original_publication_year": 400,
                "completeness": "full",
                "contributors": [
                    "J. Walker (translator, 1851)",
                    "J. Sheppard (translator, 1851)",
                    "H. Browne (translator, 1851)",
                    "George B. Stevens (reviser, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homilies-on-romans",
                "div1_id": "vii",
                "div2_id": None,
                "title": "Homilies on the Epistle of Paul to the Romans",
                "work_kind": "theological-work",
                "original_publication_year": 391,
                "completeness": "full",
                "contributors": [
                    "J.B. Morris (translator, 1841)",
                    "W.H. Simcox (translator, 1841)",
                    "George B. Stevens (reviser, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
        ],
    },
    # ------------------------------------------------------------------
    # NPNF1-12: Homilies on 1 Corinthians (44) and 2 Corinthians (30)
    # 1 Cor has a leading 'Argument.' div2 (untyped) filtered as editorial.
    # ------------------------------------------------------------------
    "npnf112": {
        "url": "https://www.ccel.org/ccel/schaff/npnf112.xml",
        "raw_file": RAW_DIR / "npnf112.xml",
        "source_edition": _NPNF1_SOURCE_EDITION,
        "translator": _CHRYSOSTOM_TRANSLATORS["npnf112"],
        "works": [
            {
                "slug": "chrysostom-homilies-on-1-corinthians",
                "div1_id": "iv",
                "div2_id": None,
                "title": "Homilies on the First Epistle of Paul to the Corinthians",
                "work_kind": "theological-work",
                "original_publication_year": 392,
                "completeness": "full",
                "contributors": [
                    "Talbot W. Chambers (translator, 1889; rev. of Oxford ed.)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homilies-on-2-corinthians",
                "div1_id": "v",
                "div2_id": None,
                "title": "Homilies on the Second Epistle of Paul to the Corinthians",
                "work_kind": "theological-work",
                "original_publication_year": 392,
                "completeness": "full",
                "contributors": [
                    "Talbot W. Chambers (translator, 1889; rev. of Oxford ed.)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
        ],
    },
    # ------------------------------------------------------------------
    # NPNF1-13: Galatians, Ephesians, Philippians, Colossians, 1-2 Thess,
    # 1-2 Tim, Titus, Philemon — split into 10 per-epistle output files via
    # div2_id. Each per-epistle div2 may have a leading 'Argument' /
    # 'Introductory Discourse' div3 which the editorial filter handles.
    # ------------------------------------------------------------------
    "npnf113": {
        "url": "https://www.ccel.org/ccel/schaff/npnf113.xml",
        "raw_file": RAW_DIR / "npnf113.xml",
        "source_edition": _NPNF1_SOURCE_EDITION,
        "translator": _CHRYSOSTOM_TRANSLATORS["npnf113"],
        "works": [
            {
                "slug": "chrysostom-commentary-on-galatians",
                "div1_id": "iii",
                "div2_id": "iii.iii",
                "title": "Commentary on the Epistle to the Galatians",
                "work_kind": "theological-work",
                "original_publication_year": 395,
                "completeness": "full",
                "strip_ccel_title_blocks": 7,  # drops 6 title frags + 1 Greek-char noise block
                "contributors": [_CHRYSOSTOM_TRANSLATORS["npnf113"]],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homilies-on-ephesians",
                "div1_id": "iii",
                "div2_id": "iii.iv",
                "title": "Homilies on the Epistle to the Ephesians",
                "work_kind": "theological-work",
                "original_publication_year": 395,
                "completeness": "full",
                "contributors": [_CHRYSOSTOM_TRANSLATORS["npnf113"]],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homilies-on-philippians",
                "div1_id": "iv",
                "div2_id": "iv.iii",
                "title": "Homilies on the Epistle to the Philippians",
                "work_kind": "theological-work",
                "original_publication_year": 399,
                "completeness": "full",
                "contributors": [_CHRYSOSTOM_TRANSLATORS["npnf113"]],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homilies-on-colossians",
                "div1_id": "iv",
                "div2_id": "iv.iv",
                "title": "Homilies on the Epistle to the Colossians",
                "work_kind": "theological-work",
                "original_publication_year": 399,
                "completeness": "full",
                "contributors": [_CHRYSOSTOM_TRANSLATORS["npnf113"]],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homilies-on-1-thessalonians",
                "div1_id": "iv",
                "div2_id": "iv.v",
                "title": "Homilies on the First Epistle to the Thessalonians",
                "work_kind": "theological-work",
                "original_publication_year": 399,
                "completeness": "full",
                "contributors": [_CHRYSOSTOM_TRANSLATORS["npnf113"]],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homilies-on-2-thessalonians",
                "div1_id": "iv",
                "div2_id": "iv.vi",
                "title": "Homilies on the Second Epistle to the Thessalonians",
                "work_kind": "theological-work",
                "original_publication_year": 399,
                "completeness": "full",
                "contributors": [_CHRYSOSTOM_TRANSLATORS["npnf113"]],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homilies-on-1-timothy",
                "div1_id": "v",
                "div2_id": "v.iii",
                "title": "Homilies on the First Epistle to Timothy",
                "work_kind": "theological-work",
                "original_publication_year": 393,
                "completeness": "full",
                "contributors": [_CHRYSOSTOM_TRANSLATORS["npnf113"]],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homilies-on-2-timothy",
                "div1_id": "v",
                "div2_id": "v.iv",
                "title": "Homilies on the Second Epistle to Timothy",
                "work_kind": "theological-work",
                "original_publication_year": 393,
                "completeness": "full",
                "contributors": [_CHRYSOSTOM_TRANSLATORS["npnf113"]],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homilies-on-titus",
                "div1_id": "v",
                "div2_id": "v.v",
                "title": "Homilies on the Epistle to Titus",
                "work_kind": "theological-work",
                "original_publication_year": 393,
                "completeness": "full",
                "contributors": [_CHRYSOSTOM_TRANSLATORS["npnf113"]],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homilies-on-philemon",
                "div1_id": "v",
                "div2_id": "v.vi",
                "title": "Homilies on the Epistle to Philemon",
                "work_kind": "theological-work",
                "original_publication_year": 393,
                "completeness": "full",
                "contributors": [_CHRYSOSTOM_TRANSLATORS["npnf113"]],
                **_CHRYSOSTOM,
            },
        ],
    },
    # ------------------------------------------------------------------
    # NPNF1-14: Homilies on John (88) and Hebrews (34)
    # John's Homily I is titled 'Preface.' which would be eaten by the
    # editorial title filter — content-typed div guard in is_editorial_div
    # protects it.
    # ------------------------------------------------------------------
    "npnf114": {
        "url": "https://www.ccel.org/ccel/schaff/npnf114.xml",
        "raw_file": RAW_DIR / "npnf114.xml",
        "source_edition": _NPNF1_SOURCE_EDITION,
        "translator": _CHRYSOSTOM_TRANSLATORS["npnf114"],
        "works": [
            {
                "slug": "chrysostom-homilies-on-john",
                "div1_id": "iv",
                "div2_id": None,
                "title": "Homilies on the Gospel of St. John",
                "work_kind": "theological-work",
                "original_publication_year": 391,
                "completeness": "full",
                "strip_ccel_title_blocks": 6,  # drops 5 title frags + 1 Greek-char noise block
                "contributors": [
                    "G.T. Stupart (translator, 1848)",
                    "Frederic Gardiner (reviser, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
            {
                "slug": "chrysostom-homilies-on-hebrews",
                "div1_id": "v",
                "div2_id": None,
                "title": "Homilies on the Epistle to the Hebrews",
                "work_kind": "theological-work",
                "original_publication_year": 403,
                "completeness": "full",
                "contributors": [
                    "Frederic Gardiner (translator, 1889)",
                    "Philip Schaff (series editor)",
                ],
                **_CHRYSOSTOM,
            },
        ],
    },
}


def _validate_work_configs() -> None:
    for volume_id, volume_cfg in VOLUME_CONFIG.items():
        for cfg in volume_cfg.get("works", []):
            slug = cfg.get("slug", volume_id)
            for t in cfg.get("tradition", []):
                assert t in STRUCTURED_TEXT__META__TRADITION, f"{slug}: invalid tradition {t!r}"
            if wk := cfg.get("work_kind"):
                assert wk in STRUCTURED_TEXT__DATA__WORK_KIND, f"{slug}: invalid work_kind {wk!r}"
            if era := cfg.get("era"):
                assert era in STRUCTURED_TEXT__META__ERA, f"{slug}: invalid era {era!r}"
            if aud := cfg.get("audience"):
                assert aud in STRUCTURED_TEXT__META__AUDIENCE, f"{slug}: invalid audience {aud!r}"
            if comp := cfg.get("completeness"):
                assert comp in STRUCTURED_TEXT__META__COMPLETENESS, f"{slug}: invalid completeness {comp!r}"


_validate_work_configs()

# ---------------------------------------------------------------------------
# Batch definitions
# ---------------------------------------------------------------------------

BATCH_A_VOLS = ["npnf101", "npnf102", "npnf103", "npnf104", "npnf105", "npnf106", "npnf107", "npnf108"]
BATCH_B_VOLS = ["npnf109", "npnf110", "npnf111", "npnf112", "npnf113", "npnf114"]

# ---------------------------------------------------------------------------
# ThML entity map (same as Owen/Hodge/church_history parsers)
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
# Editorial skip patterns (NPNF1 extended from church_history.py)
# ---------------------------------------------------------------------------

_EDITORIAL_TITLE_PATTERNS = re.compile(
    r"^(title page|preface|prefatory|testimonies? of|supplementary notes|"
    r"manuscripts and editions|chronological tables|translator|memoir of|"
    r"address to the|general indexes?|subject index|index of|indexes?|"
    r"introductory|extract from|retractations?|advertisement|argument|"
    r"abstract|note on the following|a select bibliography|two letters written|"
    r"dedication of|chief events|credits|editor)\b",
    re.IGNORECASE,
)

_EDITORIAL_DIV2_TYPES = frozenset(["Preface", "Table of Contents"])

# Div types that always carry author content. When a div has one of these
# types, the title-based editorial filter is skipped — needed for NPNF1-14
# where Chrysostom's Homily I on John is titled 'Preface.' and would otherwise
# be swallowed by the _EDITORIAL_TITLE_PATTERNS regex.
_CONTENT_DIV_TYPES = frozenset([
    "Homily", "Sermon", "Tractate", "Letter", "Chapter", "Book",
    "Demonstration", "Dialogue", "Division",
])

_SKIP_DIV1_TITLE_RE = re.compile(
    r"^(title page|index|indexes|general index|subject index|table of contents)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Tag sets and div type mapping (NPNF1 extended)
# ---------------------------------------------------------------------------

_HEADING_TAGS = frozenset(["h1", "h2", "h3", "h4", "title"])
_SKIP_TAGS = frozenset(["note", "pb", "insertIndex", "style", "selector", "scripContext"])
_DIV_TAG_RE = re.compile(r"^div\d?$")

_DIV_TYPE_MAP = {
    "Book": "book",
    "Chapter": "chapter",
    "Section": "section",
    "Letter": "letter",
    "Dialogue": "chapter",
    "Demonstration": "chapter",
    "Sermon": "chapter",
    "Tractate": "chapter",
    "Homily": "chapter",
    "Division": "book",
    "Note": None,
    "Table": None,
}

# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_volume(vol_id: str, force: bool = False) -> None:
    """Download a NPNF1 volume XML from CCEL if not already cached."""
    cfg = VOLUME_CONFIG[vol_id]
    dest = cfg["raw_file"]
    if dest.exists() and not force:
        size_kb = dest.stat().st_size // 1024
        print(f"  Cached: {dest.name} ({size_kb} KB)")
        return
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    url = cfg["url"]
    print(f"  Downloading {url} ...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = resp.read()
        with open(dest, "wb") as fh:
            fh.write(data)
        download_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cfg["download_date"] = download_date
        print(f"  Downloaded {len(data) // 1024} KB -> {dest.name}")
    except Exception as exc:
        raise RuntimeError(
            f"Download failed for {vol_id}: {exc}. "
            "Check network access and CCEL availability."
        ) from exc


# ---------------------------------------------------------------------------
# XML preprocessing
# ---------------------------------------------------------------------------


def _replace_entity(match: re.Match) -> str:
    ent = match.group(0)
    if ent in XML_SAFE_ENTITIES:
        return ent
    replacement = THML_ENTITY_MAP.get(ent)
    return replacement if replacement is not None else ""


def preprocess_thml(raw_bytes: bytes) -> str:
    """Decode, strip DOCTYPE, replace HTML entities."""
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
    """Recursively collect text content, skipping footnote/metadata tags."""
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
    return re.sub(r"\s+", " ", text).strip()


def get_scriptrefs(elem) -> list:
    """Collect scripture references from <scripRef> elements."""
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
    return sum(len(b.split()) for b in blocks)


# ---------------------------------------------------------------------------
# Structural helpers
# ---------------------------------------------------------------------------


def is_editorial_div(elem) -> bool:
    """Return True if a div element is editorial front/back matter to skip."""
    div_type = elem.get("type", "")
    if div_type in _EDITORIAL_DIV2_TYPES:
        return True
    if div_type in _CONTENT_DIV_TYPES:
        # Author-content div — never filter on title text. (NPNF1-14 Homily I
        # on John is titled 'Preface.'; we keep it.)
        return False
    title = clean_text(elem.get("title", ""))
    if title and _EDITORIAL_TITLE_PATTERNS.match(title):
        # Warn when filtering an untyped div whose title matches "argument",
        # since some CCEL volumes contain author-written argumentative prefaces
        # in untyped divs. If content is unexpectedly missing, check these warnings.
        if re.match(r"^argument\b", title, re.IGNORECASE) and not div_type:
            print(
                f"  WARNING: Filtering untyped div id={elem.get('id', '')!r} "
                f"title={title!r} as editorial (matched 'argument' pattern). "
                "If this is author content, add a type= attribute to the CCEL XML "
                "or note the slug in UPSTREAM_BUGS.md."
            )
        return True
    if title.lower() in (
        "title page.", "title page",
        "preface.", "preface",
        "the argument", "the argument.",
        "argument", "argument.",
        "introductory discourse.", "introductory discourse",
    ):
        return True
    return False


def get_div_label_title(elem) -> tuple:
    """Extract (label, title) from a div element using title= attr or h* children."""
    n = elem.get("n", "")
    div_type = elem.get("type", "")
    title_attr = clean_text(elem.get("title", ""))

    if div_type and n:
        label = f"{div_type} {n}"
    elif n:
        label = n
    else:
        label = ""

    title = title_attr
    if title and label and title.lower().startswith(label.lower()):
        title = title[len(label):].strip().lstrip(".").strip()

    if not title:
        for child in elem:
            if child.tag in _HEADING_TAGS:
                child_text = clean_text(get_all_text(child))
                if child_text:
                    title = child_text
                    break

    return label or None, title or None


def collect_content_blocks(elem) -> list:
    """Collect direct <p> and <argument> children as content_blocks."""
    blocks = []
    for child in elem:
        if child.tag in _HEADING_TAGS or child.tag in _SKIP_TAGS:
            continue
        if _DIV_TAG_RE.match(child.tag):
            continue
        if child.tag in ("p", "argument", "q"):
            text = clean_text(get_all_text(child))
            if text:
                blocks.append(text)
        elif child.tag in ("ul", "ol"):
            items = []
            for li in child.findall("li"):
                t = clean_text(get_all_text(li))
                if t:
                    items.append(t)
            if items:
                blocks.append("; ".join(items))
    return blocks


# ---------------------------------------------------------------------------
# Parse engine
# ---------------------------------------------------------------------------


def parse_div_recursive(elem, max_depth: int = 4, depth: int = 0) -> dict | None:
    """
    Recursively parse a div element into a section dict.

    Returns None for editorial divs or divs with no content or children.
    """
    if is_editorial_div(elem):
        return None

    div_type = elem.get("type", "")
    section_type = _DIV_TYPE_MAP.get(div_type)

    if div_type and section_type is None and div_type in ("Note", "Table"):
        return None
    if section_type is None:
        section_type = "section" if depth > 0 else "book"

    label, title = get_div_label_title(elem)
    content_blocks = collect_content_blocks(elem)

    children = []
    if depth < max_depth:
        for child in elem:
            if not _DIV_TAG_RE.match(child.tag):
                continue
            result = parse_div_recursive(child, max_depth, depth + 1)
            if result is not None:
                children.append(result)

    if not content_blocks and not children:
        return None

    scripture_refs = get_scriptrefs(elem)
    word_count = count_words(content_blocks)

    return {
        "section_type": section_type,
        "label": label,
        "title": title,
        "content_blocks": content_blocks,
        "scripture_references": scripture_refs,
        "word_count": word_count,
        "children": children,
    }


def parse_work_from_container(container_elem, work_cfg: dict) -> list:
    """
    Extract sections from a container element (div1 or div2) for a single work.

    Iterates direct div children of container, skipping editorial front/back matter,
    and recursively parses included content divs.
    """
    sections = []
    for child in container_elem:
        if not _DIV_TAG_RE.match(child.tag):
            continue
        if is_editorial_div(child):
            continue
        result = parse_div_recursive(child, max_depth=4, depth=0)
        if result is not None:
            sections.append(result)
    return sections


def parse_volume_work(vol_id: str, work_cfg: dict, raw_bytes: bytes) -> dict:
    """Parse one work from a NPNF1 volume XML."""
    source_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    xml_text = preprocess_thml(raw_bytes)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(
            f"XML parse failed for {vol_id}: {exc}. Try re-downloading."
        ) from exc

    body = root.find("ThML.body")
    if body is None:
        raise RuntimeError(f"No <ThML.body> in {vol_id}. Unexpected structure.")

    target_div1_id = work_cfg["div1_id"]
    div1_elem = None
    for div1 in body:
        if not _DIV_TAG_RE.match(div1.tag):
            continue
        if div1.get("id") == target_div1_id:
            div1_elem = div1
            break

    if div1_elem is None:
        raise RuntimeError(
            f"div1 id={target_div1_id!r} not found in {vol_id}. "
            "Check census -- volume structure may have changed."
        )

    target_div2_id = work_cfg.get("div2_id")
    if target_div2_id:
        container_elem = None
        for div2 in div1_elem:
            if not _DIV_TAG_RE.match(div2.tag):
                continue
            if div2.get("id") == target_div2_id:
                container_elem = div2
                break
        if container_elem is None:
            raise RuntimeError(
                f"div2 id={target_div2_id!r} not found in div1 {target_div1_id!r} "
                f"of {vol_id}. Check census."
            )
    else:
        container_elem = div1_elem

    sections = parse_work_from_container(container_elem, work_cfg)

    # Fix #4 — strip leading translator 'Introduction.' from npnf109 works whose
    # first section is an editorial introduction by Stephens or Schaff, not by
    # Chrysostom.  Set strip_lead_intro: True in a work config to enable.
    if work_cfg.get("strip_lead_intro") and sections:
        first_title = (sections[0].get("title") or "").strip().lower()
        if first_title in ("introduction.", "introduction"):
            sections = sections[1:]

    # Fix #3 — strip leading CCEL volume-title fragment blocks from the first
    # section.  These short <p> elements (e.g. "Homilies of St. John Chrysostom,"
    # / "archbishop of constantinople,") appear in the XML before the first
    # homily's actual text.  Set strip_ccel_title_blocks: N in a work config to
    # drop the first N content_blocks from sections[0].
    strip_n = work_cfg.get("strip_ccel_title_blocks", 0)
    if strip_n > 0 and sections:
        blocks = sections[0].get("content_blocks", [])
        if len(blocks) > strip_n:
            sections[0]["content_blocks"] = blocks[strip_n:]
            sections[0]["word_count"] = count_words(sections[0]["content_blocks"])

    return {
        "work_id": work_cfg["slug"],
        "sections": sections,
        "_source_hash": source_hash,
    }


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------


def build_meta(vol_id: str, work_cfg: dict, source_hash: str) -> dict:
    cfg = VOLUME_CONFIG[vol_id]
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw_file = cfg["raw_file"]
    download_date = cfg.get("download_date", "")
    if not download_date and raw_file.exists():
        mtime = raw_file.stat().st_mtime
        download_date = datetime.fromtimestamp(
            mtime, tz=timezone.utc
        ).strftime("%Y-%m-%d")

    return {
        "id": work_cfg["slug"],
        "title": work_cfg["title"],
        "author": work_cfg["author"],
        "author_id": work_cfg.get("author_id"),
        "author_birth_year": work_cfg.get("author_birth_year"),
        "author_death_year": work_cfg.get("author_death_year"),
        "contributors": normalize_contributors(work_cfg.get("contributors", [])),
        "original_publication_year": work_cfg.get("original_publication_year"),
        "language": "en",
        "original_language": work_cfg.get("original_language"),
        "tradition": work_cfg.get("tradition", []),
        "tradition_notes": "",
        "era": work_cfg.get("era"),
        "audience": work_cfg.get("audience", "scholarly"),
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": work_cfg.get("completeness", "full"),
        "provenance": {
            "source_url": cfg["url"],
            "source_format": "ThML XML",
            "source_edition": cfg["source_edition"],
            "download_date": download_date,
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/ccel_npnf1.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": (
                "ThML HTML entities replaced with Unicode equivalents. "
                "DOCTYPE stripped before parsing. "
                "Footnotes (<note>) and page breaks (<pb>) excluded from content. "
                "Editorial front matter (title pages, prefaces, arguments, "
                "introductory essays, indexes, retractations extracts) excluded. "
                "robots.txt crawl-delay 10s honoured."
            ),
            "source_type": "ccel_thml",
            "source_file": str(raw_file.relative_to(REPO_ROOT)).replace("\\", "/"),
            "translator": cfg.get("translator", "Philip Schaff (ed.), 1886"),
        },
    }


# ---------------------------------------------------------------------------
# Quality reporting
# ---------------------------------------------------------------------------


def _sum_tree(sections: list, key: str) -> int:
    total = 0
    for s in sections:
        total += s.get(key, 0)
        total += _sum_tree(s.get("children", []), key)
    return total


def _count_nodes(sections: list) -> int:
    count = len(sections)
    for s in sections:
        count += _count_nodes(s.get("children", []))
    return count


def _walk_nodes(sections: list):
    for s in sections:
        yield s
        yield from _walk_nodes(s.get("children", []))


def report_quality(work_cfg: dict, sections: list) -> None:
    top_n = len(sections)
    total_n = _count_nodes(sections)
    total_words = _sum_tree(sections, "word_count")
    top_titles = [s.get("title") or s.get("label") or "(untitled)" for s in sections[:6]]
    print(
        f"  {work_cfg['slug']}: {top_n} top sections, "
        f"{total_n} total nodes, ~{total_words // 1000}k words"
    )
    print(f"  Top sections: {top_titles}")
    null_titles = sum(1 for s in sections if not s.get("title") and not s.get("label"))
    if null_titles:
        print(f"  WARNING: {null_titles} top sections with no title or label")
    all_nodes = list(_walk_nodes(sections))
    empty_content = sum(
        1 for n in all_nodes
        if not n.get("children") and not n.get("content_blocks")
    )
    if empty_content:
        print(f"  WARNING: {empty_content}/{total_n} leaf nodes with empty content_blocks")


# ---------------------------------------------------------------------------
# Source config writer
# ---------------------------------------------------------------------------


def write_source_config(vol_id: str, work_cfg: dict, source_hash: str) -> None:
    cfg = VOLUME_CONFIG[vol_id]
    config_dir = REPO_ROOT / "sources" / "structured-text" / work_cfg["slug"]
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"

    raw_file = cfg["raw_file"]
    download_date = cfg.get("download_date", "")
    if not download_date and raw_file.exists():
        mtime = raw_file.stat().st_mtime
        download_date = datetime.fromtimestamp(
            mtime, tz=timezone.utc
        ).strftime("%Y-%m-%d")

    config = {
        "resource_id": work_cfg["slug"],
        "title": work_cfg["title"],
        "author": work_cfg["author"],
        "author_id": work_cfg.get("author_id"),
        "author_birth_year": work_cfg.get("author_birth_year"),
        "author_death_year": work_cfg.get("author_death_year"),
        "contributors": normalize_contributors(work_cfg.get("contributors", [])),
        "original_publication_year": work_cfg.get("original_publication_year"),
        "language": "en",
        "original_language": work_cfg.get("original_language"),
        "tradition": work_cfg.get("tradition", []),
        "era": work_cfg.get("era"),
        "audience": work_cfg.get("audience", "scholarly"),
        "license": "public-domain",
        "schema_type": "structured_text",
        "work_kind": work_cfg["work_kind"],
        "source_url": cfg["url"],
        "source_format": "ThML XML",
        "source_edition": cfg["source_edition"],
        "source_hash": source_hash,
        "source_type": "ccel_thml",
        "translator": cfg.get("translator", "Philip Schaff (ed.), 1886"),
        "download_date": download_date,
        "output_file": f"data/structured-text/{work_cfg['slug']}.json",
        "clearance_date": "2026-04-01",
        "notes": (
            "CCEL confirmed OK to parse (Quincy, 2026-04-01). "
            "Crawl-delay 10s per robots.txt. "
            "ThML entities replaced; DOCTYPE stripped; footnotes excluded. "
            "License: Public Domain (pre-1927 translation)."
        ),
    }
    with open(config_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"  Config written -> {config_path}")


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse NPNF Series 1 works from CCEL ThML XML"
    )
    parser.add_argument(
        "--volume",
        choices=list(VOLUME_CONFIG.keys()),
        default=None,
        help="Process only this volume (default: all volumes in selected batch)",
    )
    parser.add_argument(
        "--work",
        default=None,
        metavar="SLUG",
        help="Process only this work slug",
    )
    parser.add_argument(
        "--batch",
        choices=["a", "b"],
        default=None,
        help="Process all volumes in batch a (Augustine) or b (Chrysostom)",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download volume XML from CCEL (respects 10s crawl-delay)",
    )
    parser.add_argument(
        "--parse",
        action="store_true",
        help="Parse cached XML and write JSON output",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if already cached",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse but do not write output files; print quality stats only",
    )
    args = parser.parse_args()

    if not args.download and not args.parse and not args.dry_run:
        parser.print_help()
        sys.exit(0)

    if args.dry_run:
        args.parse = True

    # Determine which volumes to process
    if args.volume:
        vol_ids = [args.volume]
    elif args.batch == "a":
        vol_ids = [v for v in BATCH_A_VOLS if v in VOLUME_CONFIG]
    elif args.batch == "b":
        vol_ids = [v for v in BATCH_B_VOLS if v in VOLUME_CONFIG]
    else:
        vol_ids = list(VOLUME_CONFIG.keys())

    # When a specific work slug is given, restrict to volumes that contain it.
    if args.work and not args.volume:
        vol_ids = [
            v for v in vol_ids
            if any(w["slug"] == args.work for w in VOLUME_CONFIG[v]["works"])
        ]
        if not vol_ids:
            print(f"ERROR: work {args.work!r} not found in any configured volume.")
            sys.exit(1)

    start_time = time.time()
    log_lines = []

    def log(msg: str) -> None:
        safe = msg.encode("ascii", errors="replace").decode("ascii")
        print(safe)
        log_lines.append(msg)

    errors = 0
    files_written = 0
    works_done = 0

    try:
        log(f"NPNF1 parser {SCRIPT_VERSION}")
        log(f"Volumes: {vol_ids}  download={args.download}  parse={args.parse}  dry_run={args.dry_run}")
        log("")

        # --- Download phase ---
        if args.download:
            log("=== Download phase ===")
            for i, vol_id in enumerate(vol_ids):
                if i > 0:
                    log(f"  Waiting {CRAWL_DELAY}s (robots.txt crawl-delay) ...")
                    time.sleep(CRAWL_DELAY)
                log(f"  [{i + 1}/{len(vol_ids)}] {vol_id} ...")
                try:
                    download_volume(vol_id, force=args.force)
                except RuntimeError as exc:
                    log(f"  ERROR (download): {exc}")
                    errors += 1
            log("")

        # --- Parse phase ---
        if args.parse:
            log("=== Parse phase ===")
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

            for vol_id in vol_ids:
                cfg = VOLUME_CONFIG[vol_id]
                raw_file = cfg["raw_file"]

                if not raw_file.exists():
                    log(f"  ERROR: raw file missing: {raw_file}. Run --download first.")
                    errors += 1
                    continue

                log(f"  Loading {raw_file.name} ({raw_file.stat().st_size // 1024} KB) ...")
                raw_bytes = raw_file.read_bytes()

                works = cfg["works"]
                if args.work:
                    works = [w for w in works if w["slug"] == args.work]
                    if not works:
                        log(f"  ERROR: work {args.work!r} not found in {vol_id}")
                        errors += 1
                        continue

                for work_cfg in works:
                    div2_note = f" div2={work_cfg['div2_id']!r}" if work_cfg.get("div2_id") else ""
                    log(
                        f"  Parsing {work_cfg['slug']} "
                        f"(div1={work_cfg['div1_id']!r}{div2_note}) ..."
                    )
                    try:
                        result = parse_volume_work(vol_id, work_cfg, raw_bytes)
                    except Exception as exc:
                        log(f"  ERROR (parse): {exc}")
                        errors += 1
                        continue

                    report_quality(work_cfg, result["sections"])

                    total_words = _sum_tree(result["sections"], "word_count")
                    if not result["sections"] or total_words == 0:
                        log(
                            f"  ERROR: empty output for {work_cfg['slug']} "
                            f"({len(result['sections'])} sections, {total_words} words) "
                            f"— check div1_id/div2_id config and editorial filters"
                        )
                        errors += 1
                        continue

                    if args.dry_run:
                        log(f"  DRY RUN: skipping file write for {work_cfg['slug']}")
                        log("")
                        continue

                    try:
                        meta = build_meta(vol_id, work_cfg, result["_source_hash"])
                    except Exception as exc:
                        log(f"  ERROR (build_meta): {exc}")
                        errors += 1
                        continue

                    out_path = OUTPUT_DIR / f"{work_cfg['slug']}.json"
                    data = {
                        "work_id": result["work_id"],
                        "work_kind": work_cfg["work_kind"],
                        "sections": result["sections"],
                    }
                    output = {"meta": meta, "data": data}
                    try:
                        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
                            json.dump(output, fh, ensure_ascii=False, indent=2)
                            fh.write("\n")
                    except Exception as exc:
                        if out_path.exists():
                            out_path.rename(out_path.with_suffix(".json.failed"))
                        log(f"  ERROR (file write): {exc}")
                        errors += 1
                        continue

                    size_kb = out_path.stat().st_size // 1024
                    log(f"  Wrote {size_kb} KB -> {out_path.name}")
                    files_written += 1
                    works_done += 1

                    try:
                        write_source_config(vol_id, work_cfg, result["_source_hash"])
                    except Exception as exc:
                        log(f"  WARNING: source config write failed: {exc}")

                    log("")

    finally:
        elapsed = time.time() - start_time
        summary = (
            f"Done in {elapsed:.1f}s. "
            f"Works parsed: {works_done}. "
            f"Files written: {files_written}. "
            f"Errors: {errors}."
        )
        log(summary)
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(log_lines) + "\n")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
