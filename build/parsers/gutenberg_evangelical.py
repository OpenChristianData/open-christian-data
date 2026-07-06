"""gutenberg_evangelical.py
Parse Evangelical, Holiness, and Mission Classics from PG and IA
into structured_text and topical_reference schemas.

Sources (PG cache or IA download):
  PG #57121      -- Murray, Humility (1895)
  PG #16739      -- Drummond, The Greatest Thing in the World (1891/1898)
  PG #23334      -- Drummond, Natural Law in the Spiritual World (1883)
  PG #11449      -- Carey, An Enquiry into the Obligations... (1792)
  PG #25709      -- Wilberforce, A Practical View... (1797)
  IA abideinchristtho00murr        -- Murray, Abide in Christ (1882)
  IA in.ernet.dli.2015.268687      -- Murray, With Christ in School of Prayer (1885)
  IA whatbibleteaches00torr        -- Torrey, What the Bible Teaches (1898)
  IA howtopray00torr               -- Torrey, How to Pray (1900)
  IA christianitylibe0000mach      -- Machen, Christianity and Liberalism (1923)
  IA MN41619ucmf_6                 -- Machen, What is Faith? (1925)
  NOTE: Origin of Paul's Religion (cu31924029293275) BLOCKED -- Cornell scan
        has systematic duplicate CHAPTER headings; generic_chapter produces
        16 broken sections (8 ghost sections with 0-5 words). Needs custom parser.
  IA sovereigntyofgod00pink_0      -- Pink, The Sovereignty of God 1918 ed. (1918)
  IA allofgraceearnes00spur        -- Spurgeon, All of Grace (1886)
  IA lecturestomystu00spuruoft     -- Spurgeon, Lectures to My Students Series 1 (1875)
  IA 1877secondseries00spur        -- Spurgeon, Lectures to My Students Series 2 (1877)
  IA christianssecret00smitrich    -- H. W. Smith, The Christian's Secret... (1875)

Outputs:
  data/structured-text/{slug}.json
  data/topical-reference/{slug}.json  (Torrey only, if topical structure confirmed)

Notes:
  - Whitefield Journals skipped: no standard 7-volume edition identified on PG/IA.
    See research/prompts/t6-3-pg-url-census.md for details.
  - Torrey "What the Bible Teaches": parsed as structured_text (topic headings as
    sections). Full topical_reference parsing deferred pending structure confirmation.
  - Pink 1918 edition: IA identifier sovereigntyofgod00pink_0 confirmed as 1918 ed.
    DO NOT use sovereigntyofgod00pink (1961 reprint, copyrighted).
  - Murray works: written in English by South African author; no translator credit.
  - Spurgeon Lectures: Series 1 (1875) + Series 2 (1877) combined into one output.

Usage:
    py -3 build/parsers/gutenberg_evangelical.py --dry-run
    py -3 build/parsers/gutenberg_evangelical.py --download
    py -3 build/parsers/gutenberg_evangelical.py --parse
    py -3 build/parsers/gutenberg_evangelical.py --download --parse
    py -3 build/parsers/gutenberg_evangelical.py --work murray-humility --parse --dry-run
    py -3 build/parsers/gutenberg_evangelical.py --all
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

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from build.lib.contributors import normalize_contributors  # noqa: E402
from build.lib._generated_enums import (  # noqa: E402
    STRUCTURED_TEXT__DATA__WORK_KIND,
    STRUCTURED_TEXT__META__AUDIENCE,
    STRUCTURED_TEXT__META__COMPLETENESS,
    STRUCTURED_TEXT__META__ERA,
    STRUCTURED_TEXT__META__PROVENANCE__PROCESSING_METHOD,
)
from build.lib.schema_enums import get_enum  # noqa: E402
from build.lib.text_utils import compute_source_hash, smart_title  # noqa: E402
from build.lib.pg_inline_markup import (  # noqa: E402
    append_pg_inline_markup_note,
    decode_pg_inline_markup,
)

RAW_PG_DIR = REPO_ROOT / "raw" / "gutenberg"
RAW_IA_DIR = REPO_ROOT / "raw" / "ia"
OUTPUT_ST_DIR = REPO_ROOT / "data" / "structured-text"
OUTPUT_TR_DIR = REPO_ROOT / "data" / "topical-reference"
SOURCES_ST_DIR = REPO_ROOT / "sources" / "structured-text"
SOURCES_TR_DIR = REPO_ROOT / "sources" / "topical-reference"
LOG_FILE = Path(__file__).resolve().parent / "gutenberg_evangelical.log"

SCHEMA_VERSION = "2.1.0"
PROCESSING_SCRIPT_VERSION = "build/parsers/gutenberg_evangelical.py@v1.0.0"
DOWNLOAD_DATE = "2026-04-24"

USER_AGENT = (
    "OpenChristianData/1.0 "
    "(research; open-source data project; contact: openchristiandata@gmail.com)"
)
REQUEST_DELAY = 2.0

# PG wrapper markers
PG_START_RE = re.compile(r"\*\*\*\s*START OF", re.IGNORECASE)
PG_END_RE = re.compile(r"\*\*\*\s*END OF", re.IGNORECASE)

# Running page-header marker in PG (anchor tags like {a1}, {b5})
PG_ANCHOR_RE = re.compile(r"\{[ab]\d+\}")

# Valid tradition values — read directly from schemas/v1/structured_text.schema.json.
# Schema is the single source of truth; no manual copy needed.
_VALID_TRADITIONS: frozenset = get_enum("structured_text", "meta", "tradition")

# ---------------------------------------------------------------------------
# Work config
# ---------------------------------------------------------------------------

WORK_CONFIG = [
    # --- Andrew Murray ---
    {
        "slug": "murray-abide-in-christ",
        "source_type": "ia",
        "ia_id": "abideinchristtho00murr",
        "raw_file": RAW_IA_DIR / "murray_abide_in_christ.txt",
        "source_url": (
            "https://archive.org/download/abideinchristtho00murr/"
            "abideinchristtho00murr_djvu.txt"
        ),
        "parser": "murray_abide",
        "schema": "structured_text",
        "title": "Abide in Christ",
        "author": "Andrew Murray",
        "author_id": "murray-andrew",
        "author_birth_year": 1828,
        "author_death_year": 1917,
        "contributors": [],
        "original_publication_year": 1882,
        "tradition": ["reformed", "dutch-reformed", "holiness"],
        "tradition_notes": (
            "Andrew Murray (1828-1917) was a South African Dutch Reformed minister and prolific "
            "devotional author. Abide in Christ (1882) meditates on John 15:1-11, calling believers "
            "to continual union with Christ. Written in English by Murray."
        ),
        "era": "modern",
        "audience": "lay",
        "original_lang": "en",
        "work_kind": "devotional-classic",
        "source_edition": (
            "Fleming H. Revell Company, 1895 edition. "
            "Princeton Theological Seminary scan via Internet Archive (abideinchristtho00murr)."
        ),
        "completeness": "full",
        "processing_method": "ocr",
        "notes": (
            "IA DjVu OCR scan of the 1895 Fleming H. Revell edition. "
            "Murray wrote in English; no translator. "
            "Chapter headings detected by CHAPTER [roman] pattern."
        ),
    },
    {
        "slug": "murray-with-christ-in-prayer",
        "source_type": "ia",
        "ia_id": "in.ernet.dli.2015.268687",
        "raw_file": RAW_IA_DIR / "murray_with_christ_in_prayer.txt",
        "source_url": (
            "https://archive.org/download/in.ernet.dli.2015.268687/"
            "2015.268687.With-Christ_djvu.txt"
        ),
        "parser": "murray_prayer",
        "schema": "structured_text",
        "title": "With Christ in the School of Prayer",
        "author": "Andrew Murray",
        "author_id": "murray-andrew",
        "author_birth_year": 1828,
        "author_death_year": 1917,
        "contributors": [],
        "original_publication_year": 1885,
        "tradition": ["reformed", "dutch-reformed", "holiness"],
        "tradition_notes": (
            "Andrew Murray's classic on prayer (1885), structured as 31 meditations on "
            "the Lord's Prayer and Christ's teachings on prayer. Written in English by Murray."
        ),
        "era": "modern",
        "audience": "lay",
        "original_lang": "en",
        "work_kind": "devotional-classic",
        "source_edition": (
            "Fleming H. Revell Company, 1885 edition. "
            "Digital Library of India scan via Internet Archive (in.ernet.dli.2015.268687)."
        ),
        "completeness": "full",
        "processing_method": "ocr",
        "notes": (
            "DLI (Digital Library of India) OCR scan. Quality may be lower than Princeton scans. "
            "Murray wrote in English; no translator."
        ),
    },
    {
        "slug": "murray-humility",
        "source_type": "pg",
        "pg_id": 57121,
        "raw_file": RAW_PG_DIR / "pg57121.txt",
        "source_url": "http://www.gutenberg.org/cache/epub/57121/pg57121.txt",
        "parser": "murray_humility",
        "schema": "structured_text",
        "title": "Humility: The Beauty of Holiness",
        "author": "Andrew Murray",
        "author_id": "murray-andrew",
        "author_birth_year": 1828,
        "author_death_year": 1917,
        "contributors": [],
        "original_publication_year": 1895,
        "tradition": ["reformed", "dutch-reformed", "holiness"],
        "tradition_notes": (
            "Compact devotional treatise on humility as the foundation of Christian character. "
            "Written in English by Murray."
        ),
        "era": "modern",
        "audience": "lay",
        "original_lang": "en",
        "work_kind": "devotional-classic",
        "source_edition": (
            "Fleming H. Revell Company edition. "
            "Project Gutenberg PG#57121."
        ),
        "completeness": "full",
        "processing_method": "automated",
        "notes": (
            "12 chapters. Chapter headings are Roman numerals alone (I., II., ...) "
            "with title on the following line. No OCR artifacts (modern PG transcription)."
        ),
    },
    # --- R. A. Torrey ---
    {
        "slug": "torrey-what-the-bible-teaches",
        "source_type": "ia",
        "ia_id": "whatbibleteaches00torr",
        "raw_file": RAW_IA_DIR / "torrey_what_the_bible_teaches.txt",
        "source_url": (
            "https://archive.org/download/whatbibleteaches00torr/"
            "whatbibleteaches00torr_djvu.txt"
        ),
        "parser": "generic_chapter",
        "schema": "structured_text",
        "title": "What the Bible Teaches",
        "author": "R. A. Torrey",
        "author_id": "reuben-archer-torrey",
        "author_birth_year": 1856,
        "author_death_year": 1928,
        "contributors": [],
        "original_publication_year": 1898,
        "tradition": ["fundamentalist", "evangelical"],
        "tradition_notes": (
            "Reuben Archer Torrey (1856-1928) was an American evangelist and Bible teacher, "
            "superintendent of Moody Bible Institute. What the Bible Teaches (1898) is a "
            "systematic doctrinal reference organized by topic with scripture citations. "
            "Parsed as structured_text with doctrinal topics as chapters. Full topical_reference "
            "parsing (with per-verse indexing) requires cleaner OCR and is deferred."
        ),
        "era": "modern",
        "audience": "pastoral",
        "original_lang": "en",
        "work_kind": "theological-work",
        "source_edition": (
            "Fleming H. Revell Company, 1898 first edition. "
            "Princeton Theological Seminary scan via Internet Archive (whatbibleteaches00torr)."
        ),
        "completeness": "full",
        "processing_method": "ocr",
        "notes": (
            "Structured as doctrinal topic headings with scripture references. "
            "Parsed as structured_text (topics as chapters). "
            "Full topical_reference schema with verse-level indexing deferred."
        ),
    },
    {
        "slug": "torrey-how-to-pray",
        "source_type": "ia",
        "ia_id": "howtopray00torr",
        "raw_file": RAW_IA_DIR / "torrey_how_to_pray.txt",
        "source_url": (
            "https://archive.org/download/howtopray00torr/"
            "howtopray00torr_djvu.txt"
        ),
        "parser": "generic_chapter",
        "schema": "structured_text",
        "title": "How to Pray",
        "author": "R. A. Torrey",
        "author_id": "reuben-archer-torrey",
        "author_birth_year": 1856,
        "author_death_year": 1928,
        "contributors": [],
        "original_publication_year": 1900,
        "tradition": ["fundamentalist", "evangelical"],
        "tradition_notes": (
            "Compact prayer manual by Torrey, Moody Bible Institute superintendent. "
            "Twelve chapters on the conditions and practice of prevailing prayer."
        ),
        "era": "modern",
        "audience": "lay",
        "original_lang": "en",
        "work_kind": "treatise",
        "source_edition": (
            "Fleming H. Revell Company, 1900 first edition. "
            "Princeton Theological Seminary scan via Internet Archive (howtopray00torr)."
        ),
        "completeness": "full",
        "processing_method": "ocr",
        "notes": (
            "12 chapters. Chapter headings: 'CHAPTER   I' (with OCR extra spaces) "
            "followed by chapter title on next line."
        ),
    },
    # --- J. G. Machen ---
    {
        "slug": "machen-christianity-and-liberalism",
        "source_type": "ia",
        "ia_id": "christianitylibe0000mach",
        "raw_file": RAW_IA_DIR / "machen_christianity_liberalism.txt",
        "source_url": (
            "https://archive.org/download/christianitylibe0000mach/"
            "christianitylibe0000mach_djvu.txt"
        ),
        "parser": "generic_chapter",
        "schema": "structured_text",
        "title": "Christianity and Liberalism",
        "author": "J. Gresham Machen",
        "author_id": "machen-j-g",
        "author_birth_year": 1881,
        "author_death_year": 1937,
        "contributors": [],
        "original_publication_year": 1923,
        "tradition": ["reformed", "presbyterian"],
        "tradition_notes": (
            "J. Gresham Machen (1881-1937) was an American New Testament scholar at Princeton. "
            "Christianity and Liberalism (1923) argues that historic Christianity and Protestant "
            "theological liberalism are two different religions, defending Reformed orthodoxy "
            "against modernism. Partly reprinted from the Princeton Theological Review."
        ),
        "era": "modern",
        "audience": "scholarly",
        "original_lang": "en",
        "work_kind": "theological-work",
        "source_edition": (
            "The Macmillan Company, New York, 1923 first edition. "
            "Princeton Theological Seminary scan via Internet Archive (christianitylibe0000mach)."
        ),
        "completeness": "full",
        "processing_method": "ocr",
        "notes": (
            "7 chapters (CHAPTER I through CHAPTER VII). Chapter title on next line. "
            "Macmillan 1923 first edition."
        ),
    },
    {
        "slug": "machen-what-is-faith",
        "source_type": "ia",
        "ia_id": "MN41619ucmf_6",
        "raw_file": RAW_IA_DIR / "machen_what_is_faith.txt",
        "source_url": (
            "https://archive.org/download/MN41619ucmf_6/"
            "MN41619ucmf_6_djvu.txt"
        ),
        "parser": "generic_chapter",
        "schema": "structured_text",
        "title": "What is Faith?",
        "author": "J. Gresham Machen",
        "author_id": "machen-j-g",
        "author_birth_year": 1881,
        "author_death_year": 1937,
        "contributors": [],
        "original_publication_year": 1925,
        "tradition": ["reformed", "presbyterian"],
        "tradition_notes": (
            "J. Gresham Machen (1881-1937) was an American New Testament scholar at Princeton "
            "Theological Seminary. What is Faith? (1925) is a popular apologetic study analyzing "
            "the nature of saving faith against modernist reductions of faith to mere feeling or "
            "vague trust. Originally delivered as lectures."
        ),
        "era": "modern",
        "audience": "lay",
        "original_lang": "en",
        "work_kind": "theological-work",
        "source_edition": (
            "The Macmillan Company, New York, 1925 first edition. "
            "Internet Archive microform scan (MN41619ucmf_6)."
        ),
        "completeness": "full",
        "processing_method": "ocr",
        "line_corrections": {
            # OCR corruption: 'j' is a misread of the Roman numeral 'I' (Chapter V heading).
            # 'CHAPTER VI' is detected correctly later; this line is the Chapter V boundary.
            "CHAPTER Vj": "CHAPTER V",
        },
        "notes": "8 chapters (CHAPTER I through CHAPTER VIII).",
    },
    # --- A. W. Pink ---
    {
        "slug": "pink-sovereignty-of-god",
        "source_type": "ia",
        "ia_id": "sovereigntyofgod00pink_0",
        "raw_file": RAW_IA_DIR / "pink_sovereignty_of_god.txt",
        "source_url": (
            "https://archive.org/download/sovereigntyofgod00pink_0/"
            "sovereigntyofgod00pink_0_djvu.txt"
        ),
        "parser": "pink_sovereignty",
        "schema": "structured_text",
        "title": "The Sovereignty of God",
        "author": "A. W. Pink",
        "author_id": "pink-a-w",
        "author_birth_year": 1886,
        "author_death_year": 1952,
        "contributors": [],
        "original_publication_year": 1918,
        "tradition": ["reformed", "calvinist"],
        "tradition_notes": (
            "Arthur Walkington Pink (1886-1952) was a British-born Reformed theologian. "
            "The Sovereignty of God (1918 first edition) defends Calvinist soteriology. "
            "CRITICAL: Only the 1918 first edition is public domain. Later revised editions "
            "(1945, 1961) are copyrighted. IA source sovereigntyofgod00pink_0 confirmed as 1918."
        ),
        "era": "modern",
        "audience": "pastoral",
        "original_lang": "en",
        "work_kind": "theological-work",
        "source_edition": (
            "Bible Truth Depot, Swengel, Pennsylvania, 1918 FIRST EDITION. "
            "Princeton Theological Seminary scan via Internet Archive (sovereigntyofgod00pink_0). "
            "276 pages. DO NOT confuse with the 1945 or 1961 revised editions."
        ),
        "completeness": "full",
        "processing_method": "ocr",
        "notes": (
            "1918 first edition confirmed from IA metadata and file header. "
            "Chapter headings use CHAPTER [roman] pattern."
        ),
    },
    # --- C. H. Spurgeon ---
    {
        "slug": "spurgeon-all-of-grace",
        "source_type": "ia",
        "ia_id": "allofgraceearnes00spur",
        "raw_file": RAW_IA_DIR / "spurgeon_all_of_grace.txt",
        "source_url": (
            "https://archive.org/download/allofgraceearnes00spur/"
            "allofgraceearnes00spur_djvu.txt"
        ),
        "parser": "spurgeon_all_of_grace",
        "schema": "structured_text",
        "title": "All of Grace",
        "author": "Charles Haddon Spurgeon",
        "author_id": "charles-spurgeon",
        "author_birth_year": 1834,
        "author_death_year": 1892,
        "contributors": [],
        "original_publication_year": 1886,
        "tradition": ["reformed", "baptist"],
        "tradition_notes": (
            "Spurgeon's most widely read evangelistic book, aimed at unbelievers. "
            "All of Grace (1886) presents the doctrines of grace in accessible language, "
            "covering justification, faith, repentance, and conversion."
        ),
        "era": "modern",
        "audience": "lay",
        "original_lang": "en",
        "work_kind": "devotional-classic",
        "source_edition": (
            "Robert Carter & Brothers, New York, 1886 edition. "
            "Princeton Theological Seminary scan via Internet Archive (allofgraceearnes00spur)."
        ),
        "completeness": "full",
        "processing_method": "ocr",
        "notes": (
            "OCR quality is moderate (old Princeton Library copy with ornate typography). "
            "Chapter headings are ALL-CAPS titles; running page headers filtered by "
            "trailing page-number pattern. 'F' -> 'J' OCR substitution common in this scan."
        ),
    },
    {
        "slug": "spurgeon-lectures-to-my-students",
        "source_type": "ia_multi",
        "volumes": [
            {
                "ia_id": "lecturestomystu00spuruoft",
                "raw_file": RAW_IA_DIR / "spurgeon_lectures_series_1.txt",
                "source_url": (
                    "https://archive.org/download/lecturestomystu00spuruoft/"
                    "lecturestomystu00spuruoft_djvu.txt"
                ),
                "part_label": "Series I",
            },
            {
                "ia_id": "1877secondseries00spur",
                "raw_file": RAW_IA_DIR / "spurgeon_lectures_series_2.txt",
                "source_url": (
                    "https://archive.org/download/1877secondseries00spur/"
                    "1877secondseries00spur_djvu.txt"
                ),
                "part_label": "Series II",
            },
        ],
        "parser": "spurgeon_lectures",
        "schema": "structured_text",
        "title": "Lectures to My Students",
        "author": "Charles Haddon Spurgeon",
        "author_id": "charles-spurgeon",
        "author_birth_year": 1834,
        "author_death_year": 1892,
        "contributors": [],
        "original_publication_year": 1875,
        "tradition": ["reformed", "baptist"],
        "tradition_notes": (
            "Homiletics handbook from Spurgeon's Pastor's College. Series I (1875) covers "
            "the preacher's personal character and ministerial work. "
            "Series II (1877) covers the art of illustration, sermon structure, and delivery. "
            "Combined from two separate published volumes."
        ),
        "era": "modern",
        "audience": "pastoral",
        "original_lang": "en",
        "work_kind": "treatise",
        "source_edition": (
            "Passmore & Alabaster, London: Series I (1875), Series II (1877). "
            "Combined from two IA scans: lecturestomystu00spuruoft (Series I) "
            "and 1877secondseries00spur (Series II)."
        ),
        "completeness": "full",
        "processing_method": "ocr",
        "notes": (
            "Two series combined into one output file with Part-level sections. "
            "Lecture headings detected by LECTURE [roman/number] pattern."
        ),
    },
    # --- Henry Drummond ---
    {
        "slug": "drummond-greatest-thing",
        "source_type": "pg",
        "pg_id": 16739,
        "raw_file": RAW_PG_DIR / "pg16739.txt",
        "source_url": "http://www.gutenberg.org/cache/epub/16739/pg16739.txt",
        "parser": "drummond_greatest",
        "schema": "structured_text",
        "title": "The Greatest Thing in the World and Other Addresses",
        "author": "Henry Drummond",
        "author_id": "drummond-henry",
        "author_birth_year": 1851,
        "author_death_year": 1897,
        "contributors": [],
        "original_publication_year": 1884,
        "tradition": ["evangelical", "free-church"],
        "tradition_notes": (
            "Henry Drummond (1851-1897) was a Scottish Free Church minister and scientist. "
            "The title essay (on 1 Corinthians 13) was first delivered c.1884 and became one "
            "of the most widely circulated Christian pamphlets of the 19th century. "
            "This PG edition includes the main essay plus five additional addresses."
        ),
        "era": "modern",
        "audience": "lay",
        "original_lang": "en",
        "work_kind": "devotional-classic",
        "source_edition": (
            "Fleming H. Revell Company edition, copyrighted 1891 and 1898. "
            "Project Gutenberg PG#16739."
        ),
        "completeness": "full",
        "processing_method": "automated",
        "notes": (
            "Collection of 6 essays/addresses. Detected by known essay title patterns from TOC. "
            "Main essay 'Love, The Greatest Thing' has sub-sections (I., II., III.) "
            "not separately parsed."
        ),
    },
    {
        "slug": "drummond-natural-law",
        "source_type": "pg",
        "pg_id": 23334,
        "raw_file": RAW_PG_DIR / "pg23334.txt",
        "source_url": "http://www.gutenberg.org/cache/epub/23334/pg23334.txt",
        "parser": "drummond_natural_law",
        "schema": "structured_text",
        "title": "Natural Law in the Spiritual World",
        "author": "Henry Drummond",
        "author_id": "drummond-henry",
        "author_birth_year": 1851,
        "author_death_year": 1897,
        "contributors": [],
        "original_publication_year": 1883,
        "tradition": ["evangelical", "free-church"],
        "tradition_notes": (
            "Drummond's major theological-scientific work (1883) arguing that the same natural "
            "laws governing biology also govern the spiritual life. Structured around biological "
            "concepts: Biogenesis, Degeneration, Growth, Death, Mortification, Eternal Life, etc."
        ),
        "era": "modern",
        "audience": "scholarly",
        "original_lang": "en",
        "work_kind": "theological-work",
        "source_edition": (
            "Hurst & Co., New York. Project Gutenberg PG#23334."
        ),
        "completeness": "full",
        "processing_method": "automated",
        "notes": (
            "Chapter headings are short ALL-CAPS single-word or short-phrase names "
            "(BIOGENESIS, DEATH, GROWTH, etc.). INTRODUCTION precedes first chapter. "
            "PART I/II markers within Introduction are not body structure."
        ),
    },
    # --- Hannah Whitall Smith ---
    {
        "slug": "smith-christians-secret-happy-life",
        "source_type": "ia",
        "ia_id": "christianssecret00smitrich",
        "raw_file": RAW_IA_DIR / "smith_christians_secret.txt",
        "source_url": (
            "https://archive.org/download/christianssecret00smitrich/"
            "christianssecret00smitrich_djvu.txt"
        ),
        "parser": "smith_christians_secret",
        "schema": "structured_text",
        "title": "The Christian's Secret of a Happy Life",
        "author": "Hannah Whitall Smith",
        "author_id": "smith-h-w",
        "author_birth_year": 1832,
        "author_death_year": 1911,
        "contributors": [],
        "original_publication_year": 1875,
        "tradition": ["holiness", "quaker"],
        "tradition_notes": (
            "Hannah Whitall Smith (1832-1911) was an American Quaker lay preacher and leader "
            "of the Higher Life / Keswick holiness movement. The Christian's Secret of a Happy "
            "Life (1875) became the defining text of the Keswick Convention's spirituality of "
            "consecration and surrender."
        ),
        "era": "modern",
        "audience": "lay",
        "original_lang": "en",
        "work_kind": "devotional-classic",
        "source_edition": (
            "Fleming H. Revell Company, c.1883 edition (Chicago/New York). "
            "Princeton Theological Seminary scan via Internet Archive (christianssecret00smitrich)."
        ),
        "completeness": "full",
        "processing_method": "ocr",
        "notes": (
            "Chapter headings use CHAPTER [roman] pattern. "
            "1883 edition (earliest full-text scan of this work)."
        ),
    },
    # --- William Carey ---
    {
        "slug": "carey-enquiry",
        "source_type": "pg",
        "pg_id": 11449,
        "raw_file": RAW_PG_DIR / "pg11449.txt",
        "source_url": "http://www.gutenberg.org/cache/epub/11449/pg11449.txt",
        "parser": "carey_enquiry",
        "schema": "structured_text",
        "title": "An Enquiry into the Obligations of Christians to Use Means for the Conversion of the Heathens",
        "author": "William Carey",
        "author_id": "carey-william",
        "author_birth_year": 1761,
        "author_death_year": 1834,
        "contributors": [],
        "original_publication_year": 1792,
        "tradition": ["particular-baptist", "evangelical"],
        "tradition_notes": (
            "William Carey (1761-1834) was an English Particular Baptist minister who became "
            "the founder of modern Protestant missions. This pamphlet (1792) argued systematically "
            "that the Great Commission applies to all Christians in all ages, catalysing the "
            "formation of the Baptist Missionary Society. Foundational document of Protestant missiology."
        ),
        "era": "post-reformation",
        "audience": "lay",
        "original_lang": "en",
        "work_kind": "treatise",
        "source_edition": (
            "Leicester: Ann Ireland, MDCCXCII (1792). Original first edition. "
            "Project Gutenberg PG#11449."
        ),
        "completeness": "full",
        "processing_method": "automated",
        "notes": (
            "5 sections (SECT. I. through SECT. V.) + INTRODUCTION. "
            "Compact pamphlet (~20k words). SECT. III includes a world survey table (many countries)."
        ),
    },
    # --- William Wilberforce ---
    {
        "slug": "wilberforce-practical-view",
        "source_type": "pg",
        "pg_id": 25709,
        "raw_file": RAW_PG_DIR / "pg25709.txt",
        "source_url": "http://www.gutenberg.org/cache/epub/25709/pg25709.txt",
        "parser": "wilberforce_practical",
        "schema": "structured_text",
        "title": "A Practical View of the Prevailing Religious System of Professed Christians",
        "author": "William Wilberforce",
        "author_id": "wilberforce-william",
        "author_birth_year": 1759,
        "author_death_year": 1833,
        "contributors": [],
        "original_publication_year": 1797,
        "tradition": ["anglican", "evangelical"],
        "tradition_notes": (
            "William Wilberforce (1759-1833) was an English politician and evangelical reformer, "
            "best known for the abolition of the British slave trade. A Practical View (1797) is "
            "his manifesto of Evangelical Anglicanism, contrasting nominal Christianity with "
            "genuine conversion. A bestseller across the English-speaking world."
        ),
        "era": "post-reformation",
        "audience": "lay",
        "original_lang": "en",
        "work_kind": "theological-work",
        "source_edition": (
            "Original Dublin 1797 edition. Project Gutenberg PG#25709."
        ),
        "completeness": "full",
        "processing_method": "automated",
        "notes": (
            "7 chapters (CHAPTER I. through CHAPTER VII.) with SECTION sub-divisions. "
            "Structure: Chapter -> Section hierarchy."
        ),
    },
]


def _validate_work_configs() -> None:
    for cfg in WORK_CONFIG:
        slug = cfg["slug"]
        for tradition in cfg.get("tradition", []):
            assert tradition in _VALID_TRADITIONS, f"{slug}: invalid tradition value {tradition!r}"
        assert (work_kind := cfg["work_kind"]) in STRUCTURED_TEXT__DATA__WORK_KIND, (
            f"{slug}: invalid work_kind value {work_kind!r}"
        )
        assert (era := cfg["era"]) in STRUCTURED_TEXT__META__ERA, f"{slug}: invalid era value {era!r}"
        assert (audience := cfg["audience"]) in STRUCTURED_TEXT__META__AUDIENCE, (
            f"{slug}: invalid audience value {audience!r}"
        )
        assert (completeness := cfg["completeness"]) in STRUCTURED_TEXT__META__COMPLETENESS, (
            f"{slug}: invalid completeness value {completeness!r}"
        )
        assert (
            processing_method := cfg["processing_method"]
        ) in STRUCTURED_TEXT__META__PROVENANCE__PROCESSING_METHOD, (
            f"{slug}: invalid processing_method value {processing_method!r}"
        )


_validate_work_configs()

# Build lookup by slug
_WORK_BY_SLUG = {w["slug"]: w for w in WORK_CONFIG}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def log(message: str, log_lines: list) -> None:
    """Print to console (ASCII only per PY-05) and append to log list."""
    safe = message.encode("ascii", errors="replace").decode("ascii")
    print(safe)
    log_lines.append(message)


# ---------------------------------------------------------------------------
# File hashing
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

_RETRY_STATUSES = {429, 500, 502, 503}
_RETRY_DELAYS = [2.0, 4.0, 8.0]


def download_url(url: str, out_path: Path, log_lines: list) -> None:
    """Download URL to out_path with OCD User-Agent, retries on transient errors."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt, delay in enumerate([0.0] + _RETRY_DELAYS, start=1):
        if delay:
            log(f"  Retry delay {delay:.0f}s...", log_lines)
            time.sleep(delay)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            out_path.write_bytes(data)
            size_kb = len(data) // 1024
            log(f"  Downloaded: {size_kb} KB -> {out_path.name}", log_lines)
            return
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code not in _RETRY_STATUSES:
                raise
            log(f"  HTTP {exc.code} attempt {attempt}/4", log_lines)
        except urllib.error.URLError as exc:
            last_exc = exc
            log(f"  URLError attempt {attempt}/4: {exc.reason}", log_lines)
    raise last_exc


def ensure_downloaded(cfg: dict, log_lines: list) -> bool:
    """Download raw source file(s) if not already cached. Returns True on success."""
    if cfg.get("source_type") == "ia_multi":
        ok = True
        for vol in cfg["volumes"]:
            raw_path = vol["raw_file"]
            if raw_path.exists():
                log(f"  Cached: {raw_path.name} ({raw_path.stat().st_size // 1024} KB)", log_lines)
                continue
            log(f"  Downloading: {vol['source_url'][:80]}...", log_lines)
            try:
                download_url(vol["source_url"], raw_path, log_lines)
                time.sleep(REQUEST_DELAY)
            except Exception as exc:
                log(f"  ERROR downloading {vol['ia_id']}: {type(exc).__name__}: {exc}", log_lines)
                ok = False
        return ok
    raw_path = cfg["raw_file"]
    if raw_path.exists():
        size_kb = raw_path.stat().st_size // 1024
        log(f"  Cached: {raw_path.name} ({size_kb} KB)", log_lines)
        return True
    log(f"  Downloading: {cfg['source_url'][:80]}...", log_lines)
    try:
        download_url(cfg["source_url"], raw_path, log_lines)
        time.sleep(REQUEST_DELAY)
        return True
    except Exception as exc:
        log(f"  ERROR downloading {cfg['slug']}: {type(exc).__name__}: {exc}", log_lines)
        return False


# ---------------------------------------------------------------------------
# Text extraction helpers (exported for tests)
# ---------------------------------------------------------------------------


def strip_pg_wrapper(text: str) -> list:
    """Strip PG header/footer markers. Returns body lines."""
    lines = text.splitlines()
    start_idx = end_idx = None
    for i, l in enumerate(lines):
        if PG_START_RE.search(l) and start_idx is None:
            start_idx = i
        if PG_END_RE.search(l):
            end_idx = i
            break
    if start_idx is None or end_idx is None:
        raise ValueError(
            "Could not find PG start/end markers — re-run --download to refresh the file, "
            "or verify the source has standard *** START/END OF markers."
        )
    return lines[start_idx + 1 : end_idx]


def strip_ia_header(lines: list) -> list:
    """Strip common IA/Google Books OCR header lines.

    Scans the first 25 lines for known header patterns and returns
    everything from the first non-header line onwards.
    """
    header_re = re.compile(
        r"(?i)("
        r"digitized\s+by|google\s+book|books\.google|internet\s+archive"
        r"|public\s+domain|copyright\s+infringement|maintain\s+attribution"
        r"|keep\s+it\s+legal|about\s+google\s+book"
        r")"
    )
    cutoff = 0
    for i, l in enumerate(lines[:25]):
        if l.strip() and header_re.search(l):
            cutoff = i + 1
    return lines[cutoff:]


def _normalize_ws(s: str) -> str:
    """Collapse multiple spaces to single space."""
    return re.sub(r" {2,}", " ", s).strip()


def gather_paragraphs(lines: list, start: int, stop: int) -> list:
    """Collect blank-line-separated paragraphs from lines[start:stop]."""
    paragraphs = []
    current_block: list = []
    for i in range(start, min(stop, len(lines))):
        stripped = lines[i].rstrip()
        text = stripped.strip()
        if not text:
            if current_block:
                joined = " ".join(current_block)
                joined = re.sub(r"\s+", " ", joined).strip()
                if joined:
                    paragraphs.append(decode_pg_inline_markup(joined))
                current_block = []
        else:
            clean = PG_ANCHOR_RE.sub("", text).strip()
            if clean:
                current_block.append(clean)
    if current_block:
        joined = " ".join(current_block)
        joined = re.sub(r"\s+", " ", joined).strip()
        if joined:
            paragraphs.append(decode_pg_inline_markup(joined))
    return paragraphs


def word_count_blocks(blocks: list) -> int:
    """Count total words across all content_blocks."""
    return sum(len(b.split()) for b in blocks)


# ---------------------------------------------------------------------------
# Heading detection predicates (exported for tests)
# ---------------------------------------------------------------------------


def _is_chapter_heading(line: str) -> bool:
    """Return True if line is a CHAPTER [I/II/1/2] heading (standalone)."""
    s = _normalize_ws(line.strip())
    if not s:
        return False
    return bool(re.match(
        r"^(CHAPTER|CHAP\.?)\s+([IVXLCDM]+|\d+)\.?$",
        s, re.IGNORECASE
    ))


def _is_roman_numeral_alone(line: str) -> bool:
    """Return True if line is a standalone Roman numeral like 'I.' or 'XII.'

    Used for Murray Humility chapter detection.
    Must end with a period to be unambiguous. Must have nothing else on the line.
    """
    s = line.strip()
    return bool(re.match(r"^[IVX]+\.$", s))


def _is_allcaps_heading(line: str) -> bool:
    """Return True if line is an ALL-CAPS chapter name (Drummond Natural Law style).

    Excludes:
    - Lines longer than 60 chars (likely running headers)
    - Lines ending with a digit (running headers with page numbers)
    - Lines containing only digits or punctuation
    """
    s = line.strip()
    if not s or len(s) > 60:
        return False
    if re.search(r"\d+\s*$", s):
        return False
    if s != s.upper():
        return False
    if not re.search(r"[A-Z]", s):
        return False
    return True


def _is_sect_heading(line: str) -> bool:
    """Return True if line is a SECT. [I-V]. heading (Carey Enquiry style)."""
    s = _normalize_ws(line.strip())
    return bool(re.match(r"^SECT\.\s*[IVX]+\.", s))


def _is_wilberforce_chapter(line: str) -> bool:
    """Return True if line is a CHAPTER I. or SECTION II. heading (Wilberforce)."""
    s = _normalize_ws(line.strip())
    return bool(re.match(r"^(CHAPTER|SECTION)\s+[IVXLCDM]+\.$", s))


def _is_spurgeon_grace_chapter(line: str) -> bool:
    """Return True if line is an ALL-CAPS Spurgeon All-of-Grace chapter heading.

    Excludes running page headers which have a trailing page number.
    """
    s = line.strip()
    if not s or s != s.upper():
        return False
    if len(s) < 3 or len(s) > 80:
        return False
    if re.search(r"\d+\s*$", s):
        return False
    if not re.search(r"[A-Z]", s):
        return False
    return True


# ---------------------------------------------------------------------------
# TOC context detection
# ---------------------------------------------------------------------------


def _looks_like_toc_entry(line: str) -> bool:
    """Return True if line looks like a TOC title+page, not body text.

    TOC entries typically end with a page number (sometimes with OCR noise after it),
    or a trailing dash/dots (OCR'd away page number), or just digits.
    """
    s = line.strip()
    if not s:
        return False
    if re.match(r"^\d+\W*\s*$", s):
        return True
    # "Title text ... 42" or "Title - 42" or "Title 42^" (non-word after digit)
    if len(s) < 120 and re.search(r"[\s\-\.]+\d+\W*\s*$", s):
        return True
    # "Title -" (page number OCR'd away, trailing separator remains)
    if len(s) < 120 and re.search(r"\s+-\s*$", s):
        return True
    # TOC dot-leaders: "Title........"
    if re.search(r"\.{3,}", s):
        return True
    return False


# ---------------------------------------------------------------------------
# TOC skip helpers
# ---------------------------------------------------------------------------


def _find_pg_body_start(lines: list, toc_marker: str = "CONTENTS") -> int:
    """Return the line index where the body text begins, skipping TOC.

    Strategy: find the last TOC-like cluster (lines with page numbers or
    short titles), then return the next non-empty line after it.
    Falls back to 0 if no clear TOC is found.
    """
    toc_end = 0
    for i, l in enumerate(lines[:300]):
        s = l.strip()
        if toc_marker.upper() in s.upper():
            toc_end = i
        if re.search(r"\.\s{3,}\d+$", s) or re.search(r"\s{5,}\d+$", s):
            toc_end = i
    return toc_end


def _find_ia_body_start(lines: list) -> int:
    """Skip IA OCR headers and title pages to find the first body chapter.

    Returns the line index of the first chapter heading.
    Scans the first 300 lines; returns 0 if not found.
    """
    for i, l in enumerate(lines[:400]):
        s = _normalize_ws(l.strip())
        if _is_chapter_heading(s):
            return i
    return 0


# ---------------------------------------------------------------------------
# Generic structured_text parser for CHAPTER-headed works
# ---------------------------------------------------------------------------


_GENERIC_CHAPTER_RE = re.compile(
    r"^(CHAPTER|CHAP\.?)\s+([IVXLCDM]+|\d+)\.?$",
    re.IGNORECASE
)


def parse_generic_chapter(lines: list, label: str, log_lines: list) -> list:
    """Parse lines into sections using CHAPTER [roman/digit] headings.

    Chapter title expected on the next non-empty line after the heading marker.
    Returns a list of section dicts.
    """
    events = []  # (line_idx, chapter_label, chapter_title)

    i = 0
    while i < len(lines):
        s = _normalize_ws(lines[i].strip())
        m = _GENERIC_CHAPTER_RE.match(s)
        if m:
            ch_label = f"Chapter {m.group(2).strip()}"
            # Title: next non-empty line (if it doesn't look like another heading)
            title = None
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                cand = _normalize_ws(lines[j].strip())
                if cand and not _GENERIC_CHAPTER_RE.match(cand) and len(cand) < 200:
                    title = cand
            # Skip TOC entries: next line ends with a page number
            if j < len(lines) and _looks_like_toc_entry(lines[j].strip()):
                i += 1
                continue
            events.append((i, ch_label, title))
        i += 1

    if not events:
        log(f"  WARNING: {label} -- no CHAPTER headings found in {len(lines)} lines", log_lines)
        # Fallback: treat entire text as one section
        paragraphs = gather_paragraphs(lines, 0, len(lines))
        wc = word_count_blocks(paragraphs)
        return [{
            "section_type": "section",
            "label": "Full Text",
            "title": None,
            "content_blocks": paragraphs,
            "scripture_references": [],
            "word_count": wc,
            "children": [],
        }]

    log(f"  {label}: {len(events)} chapters found", log_lines)
    sections = []
    for idx, (ch_line, ch_label, ch_title) in enumerate(events):
        title_consumed = 1 if ch_title else 0
        body_start = ch_line + 1 + title_consumed
        # Skip the actual title line
        if ch_title:
            j = ch_line + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            body_start = j + 1

        next_ch_line = events[idx + 1][0] if idx + 1 < len(events) else len(lines)
        paragraphs = gather_paragraphs(lines, body_start, next_ch_line)
        wc = word_count_blocks(paragraphs)
        sections.append({
            "section_type": "chapter",
            "label": ch_label,
            "title": ch_title,
            "content_blocks": paragraphs,
            "scripture_references": [],
            "word_count": wc,
            "children": [],
        })
        log(f"    {ch_label}: {len(paragraphs)} blocks, {wc} words", log_lines)

    return sections


# ---------------------------------------------------------------------------
# Murray Humility parser (Roman numeral alone, title on next line)
# ---------------------------------------------------------------------------


def parse_murray_humility(lines: list, log_lines: list) -> list:
    """Parse Murray Humility: chapters are standalone Roman numerals (I., II., ...)
    with the chapter title on the following line.
    """
    events = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if _is_roman_numeral_alone(s):
            roman = s.rstrip(".")
            # Get title from next non-empty line
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            title = None
            if j < len(lines):
                cand = lines[j].strip()
                if cand and not _is_roman_numeral_alone(cand) and len(cand) < 150:
                    title = cand
            events.append((i, roman, title, j if title else i + 1))
        i += 1

    if not events:
        log("  WARNING: murray-humility -- no Roman numeral headings found", log_lines)
        paragraphs = gather_paragraphs(lines, 0, len(lines))
        wc = word_count_blocks(paragraphs)
        return [{"section_type": "section", "label": "Full Text", "title": None,
                 "content_blocks": paragraphs, "scripture_references": [],
                 "word_count": wc, "children": []}]

    log(f"  murray-humility: {len(events)} chapters", log_lines)
    sections = []
    for idx, (ch_line, roman, title, title_line) in enumerate(events):
        body_start = title_line + 1 if title else ch_line + 1
        next_ch_line = events[idx + 1][0] if idx + 1 < len(events) else len(lines)
        paragraphs = gather_paragraphs(lines, body_start, next_ch_line)
        wc = word_count_blocks(paragraphs)
        label = f"Chapter {roman}"
        sections.append({
            "section_type": "chapter",
            "label": label,
            "title": title,
            "content_blocks": paragraphs,
            "scripture_references": [],
            "word_count": wc,
            "children": [],
        })
        log(f"    {label}: {title or '(no title)'} -- {wc} words", log_lines)

    return sections


# ---------------------------------------------------------------------------
# Murray Abide in Christ / With Christ in Prayer parsers
# (ordinal day/lesson headings: "First Day.", "Second Lesson.", etc.)
# ---------------------------------------------------------------------------

_ORDINAL_HEADING_RE = re.compile(
    r"^(First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth"
    r"|Eleventh|Twelfth|Thirteenth|Fourteenth|Fifteenth|Sixteenth"
    r"|Seventeenth|Eighteenth|Nineteenth|Twentieth"
    r"|Twenty-First|Twenty-Second|Twenty-Third|Twenty-Fourth|Twenty-Fifth"
    r"|Twenty-Sixth|Twenty-Seventh|Twenty-Eighth|Twenty-Ninth|Thirtieth"
    r"|Thirty-First"
    r")\s+(Day|Lesson|Meditation)\.?$",
    re.IGNORECASE,
)


def parse_ordinal_headings(lines: list, unit: str, label: str, log_lines: list) -> list:
    """Parse lines using ordinal headings: 'First Day.', 'Second Lesson.', etc.

    Used for Murray devotional works where each section is a numbered day or lesson.
    OCR variants (e.g. '8ixth Day') are skipped silently; missing days merge into adjacent.
    """
    events = []
    for i, l in enumerate(lines):
        s = _normalize_ws(l.strip())
        if _ORDINAL_HEADING_RE.match(s):
            # Title: next non-empty line
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            title = None
            if j < len(lines):
                cand = _normalize_ws(lines[j].strip())
                if cand and not _ORDINAL_HEADING_RE.match(cand) and len(cand) < 200:
                    title = cand
            events.append((i, s.rstrip("."), title, j if title else i + 1))

    if not events:
        log(f"  WARNING: {label} -- no ordinal {unit} headings found", log_lines)
        paragraphs = gather_paragraphs(lines, 0, len(lines))
        wc = word_count_blocks(paragraphs)
        return [{"section_type": "section", "label": "Full Text", "title": None,
                 "content_blocks": paragraphs, "scripture_references": [],
                 "word_count": wc, "children": []}]

    log(f"  {label}: {len(events)} {unit}s", log_lines)
    sections = []
    for idx, (ch_line, ch_label, ch_title, title_line) in enumerate(events):
        body_start = title_line + 1 if ch_title else ch_line + 1
        next_ch_line = events[idx + 1][0] if idx + 1 < len(events) else len(lines)
        paragraphs = gather_paragraphs(lines, body_start, next_ch_line)
        wc = word_count_blocks(paragraphs)
        sections.append({
            "section_type": "chapter",
            "label": ch_label,
            "title": ch_title,
            "content_blocks": paragraphs,
            "scripture_references": [],
            "word_count": wc,
            "children": [],
        })
        log(f"    {ch_label}: {wc} words", log_lines)

    return sections


# ---------------------------------------------------------------------------
# Pink "Sovereignty of God" parser (hardcoded chapter titles, poor OCR)
# ---------------------------------------------------------------------------

# Known chapter titles from the 1918 edition (stripping trailing period, normalized)
_PINK_SOVEREIGNTY_CHAPTERS = [
    "GOD'S SOVEREIGNTY DEFINED",
    "THE SOVEREIGNTY OF GOD IN CREATION",
    "THE SOVEREIGNTY OF GOD IN ADMINISTRATION",
    "THE SOVEREIGNTY OF GOD IN SALVATION",
    "THE SOVEREIGNTY OF GOD IN REPROBATION",
    "THE SOVEREIGNTY OF GOD IN OPERATION",
    "GOD'S SOVEREIGNTY AND THE HUMAN WILL",
    "GOD'S SOVEREIGNTY AND HUMAN RESPONSIBILITY",
    "GOD'S SOVEREIGNTY AND PRAYER",
    "OUR ATTITUDE TOWARD GOD'S SOVEREIGNTY",
    "DIFFICULTIES AND OBJECTIONS",
]


def _normalize_pink_apostrophe(s: str) -> str:
    """Replace curly/special apostrophes with ASCII for matching."""
    return re.sub(r"[\u2018\u2019\u201a\u201b\xb4\u02bc\u0060\ufffd]", "'", s)


def parse_pink_sovereignty(lines: list, log_lines: list) -> list:
    """Parse Pink Sovereignty of God: hardcoded chapter titles to handle poor OCR.

    The 1918 edition scan has inconsistent 'CHAPTER ONE/TWO...' headings
    (several OCR'd into noise), so chapters are identified by their title lines,
    which appear more consistently.
    """
    chapter_map = {
        re.sub(r"['\u2019\u2018]", "'", c).upper(): smart_title(c)
        for c in _PINK_SOVEREIGNTY_CHAPTERS
    }

    events = []
    seen: set = set()
    for i, l in enumerate(lines):
        raw = _normalize_pink_apostrophe(l.strip())
        s = raw.rstrip(".").rstrip(":").strip().upper()
        if s in chapter_map and s not in seen:
            # Exclude running headers (trailing digits) and TOC dot-leaders
            if re.search(r"\d+\s*$", raw) or re.search(r"\.{3,}", raw):
                continue
            seen.add(s)
            events.append((i, chapter_map[s]))

    if not events:
        log("  WARNING: pink-sovereignty -- no chapter headings found", log_lines)
        paragraphs = gather_paragraphs(lines, 0, len(lines))
        wc = word_count_blocks(paragraphs)
        return [{"section_type": "section", "label": "Full Text", "title": None,
                 "content_blocks": paragraphs, "scripture_references": [],
                 "word_count": wc, "children": []}]

    log(f"  pink-sovereignty: {len(events)} chapters", log_lines)
    sections = []
    for idx, (ch_line, ch_title) in enumerate(events):
        body_start = ch_line + 1
        next_ch_line = events[idx + 1][0] if idx + 1 < len(events) else len(lines)
        paragraphs = gather_paragraphs(lines, body_start, next_ch_line)
        wc = word_count_blocks(paragraphs)
        sections.append({
            "section_type": "chapter",
            "label": f"Chapter {idx + 1}",
            "title": ch_title,
            "content_blocks": paragraphs,
            "scripture_references": [],
            "word_count": wc,
            "children": [],
        })
        log(f"    Chapter {idx + 1}: {ch_title} -- {wc} words", log_lines)

    return sections


# ---------------------------------------------------------------------------
# Drummond "Greatest Thing" parser (multi-essay, essay title detection)
# ---------------------------------------------------------------------------

# Body heading prefixes for Drummond Greatest Thing essays.
# Key = first 14+ chars that uniquely identify each essay in the body (not TOC).
# The body headings differ slightly from TOC (e.g. "LOVE:" vs "LOVE, THE GREATEST...").
_DRUMMOND_GREATEST_BODY = [
    ("LOVE:", "Love, The Greatest Thing In The World"),
    ("THE GREATEST THING IN THE WORLD", "Love, The Greatest Thing In The World"),
    ("LESSONS FROM THE ANG", "Lessons From The Angelus"),
    ("PAX VOBISCUM", "Pax Vobiscum"),
    ("FIRST! AN ADDRESS", "First! An Address To Boys"),
    ("THE CHANGED LIFE", "The Changed Life, The Greatest Need Of The World"),
    ("DEALING WITH DOUBT", "Dealing With Doubt"),
]


def parse_drummond_greatest(lines: list, log_lines: list) -> list:
    """Parse Drummond Greatest Thing: detect essay headings by body prefix matching.

    Skips the TOC area (first 80 lines) to avoid matching TOC entries.
    """
    events = []
    seen_titles: set = set()
    for i, l in enumerate(lines):
        if i < 80:  # skip TOC/front-matter
            continue
        s = _normalize_ws(l.strip()).upper()
        for prefix, essay_title in _DRUMMOND_GREATEST_BODY:
            if s.startswith(prefix) and len(s) < len(prefix) + 60:
                if essay_title not in seen_titles:
                    seen_titles.add(essay_title)
                    events.append((i, essay_title))
                break

    if not events:
        log("  WARNING: drummond-greatest -- no essay headings found", log_lines)
        paragraphs = gather_paragraphs(lines, 0, len(lines))
        wc = word_count_blocks(paragraphs)
        return [{"section_type": "section", "label": "Full Text", "title": None,
                 "content_blocks": paragraphs, "scripture_references": [],
                 "word_count": wc, "children": []}]

    log(f"  drummond-greatest: {len(events)} essays", log_lines)
    sections = []
    for idx, (essay_line, essay_title) in enumerate(events):
        body_start = essay_line + 1
        next_essay_line = events[idx + 1][0] if idx + 1 < len(events) else len(lines)
        paragraphs = gather_paragraphs(lines, body_start, next_essay_line)
        wc = word_count_blocks(paragraphs)
        sections.append({
            "section_type": "section",
            "label": f"Essay {idx + 1}",
            "title": essay_title,
            "content_blocks": paragraphs,
            "scripture_references": [],
            "word_count": wc,
            "children": [],
        })
        log(f"    Essay {idx + 1}: {essay_title[:50]} -- {wc} words", log_lines)

    return sections


# ---------------------------------------------------------------------------
# Drummond Natural Law parser (ALL-CAPS chapter names)
# ---------------------------------------------------------------------------

# Known Natural Law chapter names in order
_DRUMMOND_NAT_LAW_CHAPTERS = [
    "INTRODUCTION",
    "BIOGENESIS",
    "DEGENERATION",
    "GROWTH",
    "DEATH",
    "MORTIFICATION",
    "ETERNAL LIFE",
    "ENVIRONMENT",
    "CONFORMITY TO TYPE",
    "SEMI-PARASITISM",
    "PARASITISM",
    "CLASSIFICATION",
]


def parse_drummond_natural_law(lines: list, log_lines: list) -> list:
    """Parse Drummond Natural Law: ALL-CAPS chapter names as headings.

    Uses a known chapter list to distinguish body headings from running headers.
    """
    chapter_set = {c.upper() for c in _DRUMMOND_NAT_LAW_CHAPTERS}

    events = []
    for i, l in enumerate(lines):
        s = l.strip().upper().rstrip(".")
        if s in chapter_set:
            events.append((i, smart_title(s)))

    if not events:
        log("  WARNING: drummond-natural-law -- no chapter headings found", log_lines)
        paragraphs = gather_paragraphs(lines, 0, len(lines))
        wc = word_count_blocks(paragraphs)
        return [{"section_type": "section", "label": "Full Text", "title": None,
                 "content_blocks": paragraphs, "scripture_references": [],
                 "word_count": wc, "children": []}]

    log(f"  drummond-natural-law: {len(events)} chapters", log_lines)
    sections = []
    for idx, (ch_line, ch_title) in enumerate(events):
        body_start = ch_line + 1
        next_ch_line = events[idx + 1][0] if idx + 1 < len(events) else len(lines)
        paragraphs = gather_paragraphs(lines, body_start, next_ch_line)
        wc = word_count_blocks(paragraphs)
        sec_type = "introduction" if ch_title.lower() == "introduction" else "chapter"
        sections.append({
            "section_type": sec_type,
            "label": ch_title,
            "title": ch_title,
            "content_blocks": paragraphs,
            "scripture_references": [],
            "word_count": wc,
            "children": [],
        })
        log(f"    {ch_title}: {wc} words", log_lines)

    return sections


# ---------------------------------------------------------------------------
# Smith "Christian's Secret" parser (handles OCR-corrupted CHAPTER headings)
# ---------------------------------------------------------------------------

# Matches CHAPTER / CHAPTEE / CHAPTEK / CHAPIER etc. (OCR variants of "CHAPTER")
_SMITH_CHAPTER_RE = re.compile(
    r"^CHAPT(?:ER|[A-Z]{2})\s+[A-Z0-9IVXLCDMivxlcdmYy]+\.?\s*$",
    re.IGNORECASE,
)


def parse_smith_christians_secret(lines: list, log_lines: list) -> list:
    """Parse Smith: detect OCR-corrupted CHAPTER headings, label chapters sequentially."""
    events = []
    for i, l in enumerate(lines):
        s = _normalize_ws(l.strip())
        if not _SMITH_CHAPTER_RE.match(s):
            continue
        # Next non-empty line is the chapter title (ALL-CAPS body title)
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        title = None
        if j < len(lines):
            cand = _normalize_ws(lines[j].strip())
            if cand and len(cand) < 150 and not _SMITH_CHAPTER_RE.match(cand):
                # Skip TOC context (next line ends with page number)
                if not _looks_like_toc_entry(cand):
                    title = cand
        if title is not None:
            events.append((i, title))

    if not events:
        log("  WARNING: smith-christians-secret -- no chapter headings found", log_lines)
        paragraphs = gather_paragraphs(lines, 0, len(lines))
        wc = word_count_blocks(paragraphs)
        return [{"section_type": "section", "label": "Full Text", "title": None,
                 "content_blocks": paragraphs, "scripture_references": [],
                 "word_count": wc, "children": []}]

    log(f"  smith-christians-secret: {len(events)} chapters", log_lines)
    sections = []
    for idx, (ch_line, ch_title) in enumerate(events):
        body_start = ch_line + 2  # skip heading + title line
        next_ch_line = events[idx + 1][0] if idx + 1 < len(events) else len(lines)
        paragraphs = gather_paragraphs(lines, body_start, next_ch_line)
        wc = word_count_blocks(paragraphs)
        label = f"Chapter {idx + 1}"
        sections.append({
            "section_type": "chapter",
            "label": label,
            "title": ch_title,
            "content_blocks": paragraphs,
            "scripture_references": [],
            "word_count": wc,
            "children": [],
        })
        log(f"    {label}: {ch_title[:50]} -- {wc} words", log_lines)

    return sections


# ---------------------------------------------------------------------------
# Carey Enquiry parser (SECT. I. through SECT. V. + INTRODUCTION)
# ---------------------------------------------------------------------------

_CAREY_SECT_RE = re.compile(r"^SECT\.\s*([IVX]+)\.$")
_CAREY_INTRO_RE = re.compile(r"^INTRODUCTION$", re.IGNORECASE)


def parse_carey_enquiry(lines: list, log_lines: list) -> list:
    """Parse Carey Enquiry: INTRODUCTION + SECT. I. through SECT. V."""
    events = []
    for i, l in enumerate(lines):
        s = _normalize_ws(l.strip())
        if _CAREY_INTRO_RE.match(s):
            events.append((i, "Introduction", None))
        else:
            m = _CAREY_SECT_RE.match(s)
            if m:
                roman = m.group(1)
                events.append((i, f"Section {roman}", None))

    if not events:
        log("  WARNING: carey-enquiry -- no SECT. headings found", log_lines)
        paragraphs = gather_paragraphs(lines, 0, len(lines))
        wc = word_count_blocks(paragraphs)
        return [{"section_type": "section", "label": "Full Text", "title": None,
                 "content_blocks": paragraphs, "scripture_references": [],
                 "word_count": wc, "children": []}]

    log(f"  carey-enquiry: {len(events)} sections", log_lines)
    sections = []
    for idx, (sec_line, sec_label, _) in enumerate(events):
        body_start = sec_line + 1
        next_sec_line = events[idx + 1][0] if idx + 1 < len(events) else len(lines)
        paragraphs = gather_paragraphs(lines, body_start, next_sec_line)
        wc = word_count_blocks(paragraphs)
        sec_type = "introduction" if sec_label == "Introduction" else "section"
        sections.append({
            "section_type": sec_type,
            "label": sec_label,
            "title": None,
            "content_blocks": paragraphs,
            "scripture_references": [],
            "word_count": wc,
            "children": [],
        })
        log(f"    {sec_label}: {wc} words", log_lines)

    return sections


# ---------------------------------------------------------------------------
# Wilberforce parser (CHAPTER I. -> SECTION II. hierarchy)
# ---------------------------------------------------------------------------

_WILB_CHAPTER_RE = re.compile(r"^CHAPTER\s+([IVXLCDM]+)\.$")
_WILB_SECTION_RE = re.compile(r"^SECTION\s+([IVXLCDM]+)\.$")


def parse_wilberforce(lines: list, log_lines: list) -> list:
    """Parse Wilberforce Practical View: CHAPTER/SECTION hierarchy."""
    events = []
    for i, l in enumerate(lines):
        s = _normalize_ws(l.strip())
        mc = _WILB_CHAPTER_RE.match(s)
        if mc:
            events.append((i, "chapter", f"Chapter {mc.group(1)}"))
            continue
        ms = _WILB_SECTION_RE.match(s)
        if ms:
            events.append((i, "section", f"Section {ms.group(1)}"))

    if not events:
        log("  WARNING: wilberforce-practical-view -- no CHAPTER headings found", log_lines)
        paragraphs = gather_paragraphs(lines, 0, len(lines))
        wc = word_count_blocks(paragraphs)
        return [{"section_type": "section", "label": "Full Text", "title": None,
                 "content_blocks": paragraphs, "scripture_references": [],
                 "word_count": wc, "children": []}]

    log(f"  wilberforce: {len(events)} events (chapters + sections)", log_lines)

    # Build chapter -> children hierarchy
    chapters = []
    current_chapter = None

    for idx, (ev_line, ev_type, ev_label) in enumerate(events):
        next_ev_line = events[idx + 1][0] if idx + 1 < len(events) else len(lines)

        if ev_type == "chapter":
            if current_chapter:
                chapters.append(current_chapter)
            current_chapter = {
                "section_type": "chapter",
                "label": ev_label,
                "title": None,
                "content_blocks": [],
                "scripture_references": [],
                "word_count": 0,
                "children": [],
                "_line": ev_line,
            }
        elif ev_type == "section" and current_chapter is not None:
            paragraphs = gather_paragraphs(lines, ev_line + 1, next_ev_line)
            wc = word_count_blocks(paragraphs)
            current_chapter["children"].append({
                "section_type": "section",
                "label": ev_label,
                "title": None,
                "content_blocks": paragraphs,
                "scripture_references": [],
                "word_count": wc,
                "children": [],
            })
            current_chapter["word_count"] += wc

    if current_chapter:
        chapters.append(current_chapter)

    # For chapters with no sub-sections, gather their body directly.
    # Must NOT pop _line until all chapters are processed (needed for next-chapter lookup).
    for ch in chapters:
        if not ch["children"]:
            next_ch = next(
                (c["_line"] for c in chapters if c["_line"] > ch["_line"]), len(lines)
            )
            paragraphs = gather_paragraphs(lines, ch["_line"] + 1, next_ch)
            ch["content_blocks"] = paragraphs
            ch["word_count"] = word_count_blocks(paragraphs)

    # Pop _line and report after all body paragraphs are assigned
    for ch in chapters:
        ch.pop("_line", None)
        total_wc = ch["word_count"] + sum(s["word_count"] for s in ch["children"])
        ch["word_count"] = total_wc
        log(f"    {ch['label']}: {len(ch['children'])} sections, {total_wc} words", log_lines)

    return chapters


# ---------------------------------------------------------------------------
# Spurgeon "All of Grace" parser (ALL-CAPS chapter titles)
# ---------------------------------------------------------------------------

# Known chapter titles for "All of Grace" (normalized, for matching)
_SPURGEON_GRACE_CHAPTERS = [
    "TO YOU!",
    "WHAT ARE WE AT?",
    "GOD JUSTIFIETH THE UNGODLY",
    "CONCERNING DELIVERANCE FROM SINNING",
    "BY GRACE THROUGH FAITH",
    "FAITH, WHAT IS IT?",
    "HOW MAY FAITH BE ILLUSTRATED?",
    "HOW CAN I OBTAIN FAITH?",
    "MISTAKES ABOUT FAITH",
    "WHY ARE MEN NOT SAVED BY THEIR DOINGS?",
    "REPENTANCE MUST GO WITH FAITH",
    "A FINAL WORD OF EXHORTATION",
    "JUST AND THE JUSTIFIER",
    "HIM HATH EVERLASTING LIFE",
    "HOW MAY FAITH BE ILLUSTRATED",
]

# OCR substitution patterns: F->J, $ -> S, FU -> JU etc.
_SPURGEON_GRACE_OCR_NORM = [
    (re.compile(r"\bFUSTIFIETH\b"), "JUSTIFIETH"),
    (re.compile(r"\bFUST\b"), "JUST"),
    (re.compile(r"\bFUSTIFIER\b"), "JUSTIFIER"),
    (re.compile(r"\b\$\b"), "S"),
    (re.compile(r"FOHN"), "JOHN"),
    (re.compile(r"FAITAH"), "FAITH"),
]


def _normalize_spurgeon_ocr(s: str) -> str:
    """Normalize common F->J OCR substitutions in Spurgeon All of Grace."""
    for pat, repl in _SPURGEON_GRACE_OCR_NORM:
        s = pat.sub(repl, s)
    return s


def parse_spurgeon_all_of_grace(lines: list, log_lines: list) -> list:
    """Parse Spurgeon All of Grace: ALL-CAPS chapter titles, filter running headers."""
    chapter_set = {c.upper() for c in _SPURGEON_GRACE_CHAPTERS}
    events = []

    for i, l in enumerate(lines):
        s = l.strip()
        if not s or s != s.upper():
            continue
        if len(s) > 80 or len(s) < 3:
            continue
        if re.search(r"\d+\s*$", s):
            continue  # running header with page number
        # Normalize OCR artifacts
        s_norm = _normalize_spurgeon_ocr(s).rstrip(".")
        if s_norm in chapter_set or s in chapter_set:
            events.append((i, smart_title(s_norm)))

    if not events:
        log("  WARNING: spurgeon-all-of-grace -- no chapter headings found", log_lines)
        paragraphs = gather_paragraphs(lines, 0, len(lines))
        wc = word_count_blocks(paragraphs)
        return [{"section_type": "section", "label": "Full Text", "title": None,
                 "content_blocks": paragraphs, "scripture_references": [],
                 "word_count": wc, "children": []}]

    # Deduplicate consecutive events at same heading (OCR artifacts)
    deduped = [events[0]]
    for ev in events[1:]:
        if ev[1] != deduped[-1][1]:
            deduped.append(ev)
    events = deduped

    log(f"  spurgeon-all-of-grace: {len(events)} chapters", log_lines)
    sections = []
    for idx, (ch_line, ch_title) in enumerate(events):
        body_start = ch_line + 1
        next_ch_line = events[idx + 1][0] if idx + 1 < len(events) else len(lines)
        paragraphs = gather_paragraphs(lines, body_start, next_ch_line)
        wc = word_count_blocks(paragraphs)
        sec_type = "preface" if idx == 0 and "YOU" in ch_title.upper() else "chapter"
        sections.append({
            "section_type": sec_type,
            "label": ch_title,
            "title": ch_title,
            "content_blocks": paragraphs,
            "scripture_references": [],
            "word_count": wc,
            "children": [],
        })
        log(f"    {ch_title}: {wc} words", log_lines)

    return sections


# ---------------------------------------------------------------------------
# Spurgeon "Lectures to My Students" multi-part parser
# ---------------------------------------------------------------------------

_LECTURES_HEADING_RE = re.compile(
    r"^(LECTURE|CHAP\.|CHAPTER)\s+([IVXLCDM]+|\d+)\.?$",
    re.IGNORECASE
)


def parse_spurgeon_lectures_volume(lines: list, part_label: str, log_lines: list) -> list:
    """Parse one series of Lectures to My Students. Returns section list.

    Skips the first 200 lines to avoid the TOC cluster (which appears in lines 0-100
    of both IA volumes). The body starts at LECTURE I, always after line 200.
    """
    # Find body start: TOC omits LECTURE I; the first "LECTURE I." is the body start.
    body_start = 0
    for idx, l in enumerate(lines[:500]):
        s = _normalize_ws(l.strip())
        if re.match(r"^(LECTURE|CHAPTER)\s+I\.?$", s, re.IGNORECASE):
            body_start = idx
            break

    events = []
    for i, l in enumerate(lines):
        if i < body_start:
            continue
        s = _normalize_ws(l.strip())
        m = _LECTURES_HEADING_RE.match(s)
        if m:
            kind = m.group(1).upper()
            num = m.group(2)
            lbl = f"Lecture {num}" if kind == "LECTURE" else f"Chapter {num}"
            # Title on next non-empty line
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            title = None
            if j < len(lines):
                cand = _normalize_ws(lines[j].strip())
                if cand and not _LECTURES_HEADING_RE.match(cand) and len(cand) < 200:
                    title = cand
            # Skip TOC entries: next line ends with a page number
            if j < len(lines) and _looks_like_toc_entry(lines[j].strip()):
                i += 1
                continue
            events.append((i, lbl, title, j if title else i + 1))

    if not events:
        log(f"  WARNING: lectures {part_label} -- no headings found", log_lines)
        paragraphs = gather_paragraphs(lines, 0, len(lines))
        wc = word_count_blocks(paragraphs)
        return [{"section_type": "chapter", "label": part_label, "title": None,
                 "content_blocks": paragraphs, "scripture_references": [],
                 "word_count": wc, "children": []}]

    log(f"  {part_label}: {len(events)} lectures", log_lines)
    sections = []
    for idx, (ch_line, ch_label, ch_title, title_line) in enumerate(events):
        body_start = title_line + 1 if ch_title else ch_line + 1
        next_ch_line = events[idx + 1][0] if idx + 1 < len(events) else len(lines)
        paragraphs = gather_paragraphs(lines, body_start, next_ch_line)
        wc = word_count_blocks(paragraphs)
        sections.append({
            "section_type": "chapter",
            "label": ch_label,
            "title": ch_title,
            "content_blocks": paragraphs,
            "scripture_references": [],
            "word_count": wc,
            "children": [],
        })
        log(f"    {ch_label}: {wc} words", log_lines)

    return sections


def parse_spurgeon_lectures_combined(
    lines_s1: list, lines_s2: list, log_lines: list
) -> list:
    """Combine Series I and Series II into one structured_text with Part sections."""
    log("  Parsing Series I...", log_lines)
    s1_sections = parse_spurgeon_lectures_volume(lines_s1, "Series I", log_lines)
    log("  Parsing Series II...", log_lines)
    s2_sections = parse_spurgeon_lectures_volume(lines_s2, "Series II", log_lines)

    parts = []
    for part_label, children, pub_year in [
        ("Series I (1875)", s1_sections, None),
        ("Series II (1877)", s2_sections, None),
    ]:
        wc = sum(c["word_count"] for c in children)
        parts.append({
            "section_type": "part",
            "label": part_label,
            "title": None,
            "content_blocks": [],
            "scripture_references": [],
            "word_count": wc,
            "children": children,
        })
        log(f"  {part_label}: {len(children)} lectures, {wc} words", log_lines)

    return parts


# ---------------------------------------------------------------------------
# Quality stats
# ---------------------------------------------------------------------------


def print_quality_stats(sections: list, label: str, log_lines: list) -> None:
    """Report completeness metrics for a structured_text section list."""
    total_secs = 0
    total_blocks = 0
    empty_secs = 0
    all_wcs: list = []

    def traverse(sec_list: list) -> None:
        nonlocal total_secs, total_blocks, empty_secs
        for sec in sec_list:
            total_secs += 1
            blocks = sec.get("content_blocks", [])
            total_blocks += len(blocks)
            wc = sec.get("word_count", 0)
            if wc == 0:
                empty_secs += 1
            all_wcs.append(wc)
            traverse(sec.get("children", []))

    traverse(sections)
    all_wcs.sort()
    log(f"  {label}: {total_secs} sections, {total_blocks} content blocks", log_lines)
    if empty_secs:
        log(f"    WARNING: {empty_secs} sections with 0 words", log_lines)
    if all_wcs:
        mid = len(all_wcs) // 2
        log(f"    Word counts: min={all_wcs[0]}, median={all_wcs[mid]}, max={all_wcs[-1]}", log_lines)


# ---------------------------------------------------------------------------
# Meta envelope builder
# ---------------------------------------------------------------------------


def build_meta(cfg: dict, source_hash: str) -> dict:
    """Build the structured_text meta envelope from work config."""
    contribs = cfg.get("contributors", [])
    invalid = [t for t in cfg["tradition"] if t not in _VALID_TRADITIONS]
    if invalid:
        raise ValueError(
            f"{cfg['slug']}: invalid tradition value(s) {invalid!r}. "
            f"Allowed: {sorted(_VALID_TRADITIONS)}"
        )
    return {
        "id": cfg["slug"],
        "title": cfg["title"],
        "author": cfg["author"],
        "author_id": cfg.get("author_id"),
        "author_birth_year": cfg["author_birth_year"],
        "author_death_year": cfg["author_death_year"],
        "contributors": normalize_contributors(contribs),
        "original_publication_year": cfg["original_publication_year"],
        "language": "en",
        "original_language": cfg["original_lang"],
        "tradition": cfg["tradition"],
        "tradition_notes": cfg["tradition_notes"],
        "era": cfg["era"],
        "audience": cfg["audience"],
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": cfg.get("completeness", "full"),
        "provenance": {
            "source_url": (
                cfg.get("source_url")
                or "; ".join(v["source_url"] for v in cfg.get("volumes", []))
            ),
            "source_format": "plain text (UTF-8)",
            "source_edition": cfg.get("source_edition", ""),
            "download_date": DOWNLOAD_DATE,
            "source_hash": source_hash,
            "processing_method": cfg.get("processing_method", "automated"),
            "processing_script_version": PROCESSING_SCRIPT_VERSION,
            "processing_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "notes": append_pg_inline_markup_note(cfg.get("notes")),
        },
    }


def write_source_config(cfg: dict, source_hash: str, out_dir: Path) -> None:
    """Write the source config JSON for a work."""
    slug = cfg["slug"]
    config_dir = out_dir / slug
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"

    source_type = cfg.get("source_type", "pg")
    if source_type == "ia_multi":
        source_id_info = {
            "source_type": "ia_multi",
            "volumes": [
                {"ia_id": v["ia_id"], "source_url": v["source_url"]}
                for v in cfg["volumes"]
            ],
        }
    elif source_type == "ia":
        source_id_info = {"source_type": "ia", "ia_id": cfg["ia_id"]}
    else:
        source_id_info = {"source_type": "pg", "pg_id": cfg["pg_id"]}

    config = {
        "slug": slug,
        "schema": cfg["schema"],
        **source_id_info,
        "source_url": (
            cfg.get("source_url")
            or "; ".join(v["source_url"] for v in cfg.get("volumes", []))
        ),
        "source_hash": source_hash,
        "download_date": DOWNLOAD_DATE,
        "processing_script": PROCESSING_SCRIPT_VERSION,
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Per-work runner
# ---------------------------------------------------------------------------


def _read_ia_file(raw_path: Path) -> list:
    """Read and strip IA header from an IA text file. Returns body lines."""
    text = raw_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    return strip_ia_header(lines)


def _read_pg_file(raw_path: Path) -> list:
    """Read and strip PG wrapper from a PG text file. Returns body lines."""
    text = raw_path.read_text(encoding="utf-8", errors="replace")
    try:
        return strip_pg_wrapper(text)
    except ValueError as exc:
        raise ValueError(f"{raw_path}: {exc}") from exc


def run_work(cfg: dict, dry_run: bool, log_lines: list) -> bool:
    """Parse one work and optionally write output. Returns True on success."""
    slug = cfg["slug"]
    schema = cfg["schema"]
    parser_key = cfg["parser"]
    source_type = cfg.get("source_type", "pg")

    log(f"\n--- {slug} ({source_type}) ---", log_lines)

    # Determine output dir and source config dir
    if schema == "structured_text":
        out_dir = OUTPUT_ST_DIR
        src_dir = SOURCES_ST_DIR
    else:
        out_dir = OUTPUT_TR_DIR
        src_dir = SOURCES_TR_DIR

    out_path = out_dir / f"{slug}.json"

    # Check raw file(s) exist
    if source_type == "ia_multi":
        for vol in cfg["volumes"]:
            if not vol["raw_file"].exists():
                log(f"  ERROR: {vol['raw_file'].name} not found. Run --download first.", log_lines)
                return False
        # Hash of concatenated hashes
        hashes = [compute_source_hash(v["raw_file"]) for v in cfg["volumes"]]
        source_hash = "sha256:" + hashlib.sha256("".join(hashes).encode()).hexdigest()
    else:
        raw_path = cfg["raw_file"]
        if not raw_path.exists():
            log(f"  ERROR: {raw_path.name} not found. Run --download first.", log_lines)
            return False
        source_hash = compute_source_hash(raw_path)

    log(f"  Hash: {source_hash[:32]}...", log_lines)

    # Parse
    try:
        if parser_key == "murray_humility":
            lines = _read_pg_file(cfg["raw_file"])
            # Find body start (after TOC)
            start = 100  # Murray Humility body starts after preface ~line 100
            sections = parse_murray_humility(lines[start:], log_lines)

        elif parser_key == "murray_abide":
            lines = _read_ia_file(cfg["raw_file"])
            sections = parse_ordinal_headings(lines, "Day", slug, log_lines)

        elif parser_key == "murray_prayer":
            lines = _read_ia_file(cfg["raw_file"])
            sections = parse_ordinal_headings(lines, "Lesson", slug, log_lines)

        elif parser_key == "pink_sovereignty":
            lines = _read_ia_file(cfg["raw_file"])
            sections = parse_pink_sovereignty(lines, log_lines)

        elif parser_key == "drummond_greatest":
            lines = _read_pg_file(cfg["raw_file"])
            sections = parse_drummond_greatest(lines, log_lines)

        elif parser_key == "drummond_natural_law":
            lines = _read_pg_file(cfg["raw_file"])
            sections = parse_drummond_natural_law(lines, log_lines)

        elif parser_key == "smith_christians_secret":
            lines = _read_ia_file(cfg["raw_file"])
            sections = parse_smith_christians_secret(lines, log_lines)

        elif parser_key == "carey_enquiry":
            lines = _read_pg_file(cfg["raw_file"])
            sections = parse_carey_enquiry(lines, log_lines)

        elif parser_key == "wilberforce_practical":
            lines = _read_pg_file(cfg["raw_file"])
            # Skip TOC (CHAPTER headings appear twice: TOC and body)
            # TOC ends around line 180 based on census
            sections = parse_wilberforce(lines, log_lines)

        elif parser_key == "spurgeon_all_of_grace":
            lines = _read_ia_file(cfg["raw_file"])
            sections = parse_spurgeon_all_of_grace(lines, log_lines)

        elif parser_key == "spurgeon_lectures":
            lines_s1 = _read_ia_file(cfg["volumes"][0]["raw_file"])
            lines_s2 = _read_ia_file(cfg["volumes"][1]["raw_file"])
            sections = parse_spurgeon_lectures_combined(lines_s1, lines_s2, log_lines)

        elif parser_key == "generic_chapter":
            if source_type == "pg":
                lines = _read_pg_file(cfg["raw_file"])
            else:
                lines = _read_ia_file(cfg["raw_file"])
            corrections = cfg.get("line_corrections", {})
            if corrections:
                lines = [corrections.get(ln.strip(), ln) for ln in lines]
            sections = parse_generic_chapter(lines, slug, log_lines)

        else:
            log(f"  ERROR: unknown parser key '{parser_key}'", log_lines)
            return False

    except Exception as exc:
        log(f"  ERROR: parse failed: {type(exc).__name__}: {exc}", log_lines)
        return False

    print_quality_stats(sections, slug, log_lines)

    # Validate: fail if 0 sections
    if not sections:
        log(f"  ERROR: {slug} -- 0 sections produced", log_lines)
        return False

    # Check for empty sections (warn but continue)
    empty_count = sum(1 for s in sections if s.get("word_count", 0) == 0)
    if empty_count > 0:
        log(f"  WARNING: {slug} -- {empty_count} empty sections", log_lines)

    if dry_run:
        first = sections[0]
        log(f"  DRY RUN -- first section: {first.get('label')} ({first.get('word_count', 0)} words)", log_lines)
        log("  DRY RUN -- no files written", log_lines)
        return True

    # Build and write output
    meta = build_meta(cfg, source_hash)
    data = {
        "work_id": slug,
        "work_kind": cfg.get("work_kind", "theological-work"),
        "sections": sections,
    }
    output = {"meta": meta, "data": data}

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log(f"  Written: {out_path}", log_lines)

    # Write source config
    write_source_config(cfg, source_hash, src_dir)
    log(f"  Source config: {src_dir / slug / 'config.json'}", log_lines)

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Evangelical & Mission Classics (PG/IA) to structured_text JSON"
    )
    parser.add_argument("--download", action="store_true", help="Download source files")
    parser.add_argument("--parse", action="store_true", help="Parse and write output")
    parser.add_argument("--all", action="store_true", help="Download + parse all works")
    parser.add_argument("--dry-run", action="store_true", help="Parse without writing output")
    parser.add_argument(
        "--work",
        choices=list(_WORK_BY_SLUG.keys()),
        help="Process one work only (default: all)",
    )
    args = parser.parse_args()

    # --all implies download + parse
    if args.all:
        args.download = True
        args.parse = True

    if not args.download and not args.parse and not args.dry_run:
        parser.print_help()
        sys.exit(0)

    log_lines: list = []
    start_time = time.time()
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    mode = "DRY RUN" if args.dry_run else ("LIVE RUN" if args.parse else "DOWNLOAD ONLY")
    log(f"[{run_ts}] gutenberg_evangelical -- {mode}", log_lines)

    works_to_run = [_WORK_BY_SLUG[args.work]] if args.work else WORK_CONFIG

    log(f"Works to process: {len(works_to_run)}", log_lines)

    dl_successes = dl_failures = 0
    parse_successes = parse_failures = 0

    for idx, cfg in enumerate(works_to_run, start=1):
        slug = cfg["slug"]
        log(f"\n[{idx}/{len(works_to_run)}] {slug}", log_lines)

        # Download phase
        if args.download:
            log(f"\n[DL] {slug}", log_lines)
            ok = ensure_downloaded(cfg, log_lines)
            if ok:
                dl_successes += 1
            else:
                dl_failures += 1
                if not args.parse:
                    continue

        # Parse phase
        if args.parse or args.dry_run:
            ok = run_work(cfg, args.dry_run, log_lines)
            if ok:
                parse_successes += 1
            else:
                parse_failures += 1

    elapsed = time.time() - start_time
    log("\n=== SUMMARY ===", log_lines)
    if args.download:
        log(f"Downloads: {dl_successes} OK, {dl_failures} failed", log_lines)
    if args.parse or args.dry_run:
        log(f"Parses: {parse_successes} OK, {parse_failures} failed", log_lines)
    log(f"Elapsed: {elapsed:.1f}s", log_lines)

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n\n")

    if parse_failures > 0 or dl_failures > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
