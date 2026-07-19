"""gutenberg_systematics.py
Parse 19th-century systematic theology texts into structured_text (and one catechism_qa) schema.

Sources and output files:

  Strong -- Systematic Theology (1907), Project Gutenberg
    PG#44035 -> data/structured-text/strong-systematic-theology-vol-1.json
    PG#44555 -> data/structured-text/strong-systematic-theology-vol-2.json
    PG#45283 -> data/structured-text/strong-systematic-theology-vol-3.json

  Dabney -- Systematic Theology (1871), Internet Archive DjVuTXT
    IA:syllabusnotesof00dabn -> data/structured-text/dabney-systematic-theology.json

  Shedd -- Dogmatic Theology (1888-1894, 3 vols), Internet Archive DjVuTXT
    IA:dogmatictheology01sheduoft -> data/structured-text/shedd-dogmatic-theology-vol-1.json
    IA:dogmatictheology02sheduoft -> data/structured-text/shedd-dogmatic-theology-vol-2.json
    IA:dogmatictheology03shed_0   -> data/structured-text/shedd-dogmatic-theology-vol-3.json

  Miley -- Systematic Theology (1892, 2 vols), Internet Archive DjVuTXT
    IA:systematictheolo01mile -> data/structured-text/miley-systematic-theology-vol-1.json
    IA:systematictheolo02mile -> data/structured-text/miley-systematic-theology-vol-2.json

  A. A. Hodge -- Outlines of Theology (1879), Internet Archive DjVuTXT
    IA:outlinesoftheolo1879hodg -> data/catechisms/aa-hodge-outlines.json
    Schema: catechism_qa (Q&A format confirmed throughout)

Usage:
    py -3 build/parsers/gutenberg_systematics.py --dry-run
    py -3 build/parsers/gutenberg_systematics.py --download
    py -3 build/parsers/gutenberg_systematics.py --parse
    py -3 build/parsers/gutenberg_systematics.py --download --parse
    py -3 build/parsers/gutenberg_systematics.py --work strong-systematic-theology-vol-1
    py -3 build/parsers/gutenberg_systematics.py --all

Parser quirks (for extending this file):
  CHAP[A-Z]+ headings: OCR corrupts "CHAPTER" to "CHAPTLR" etc. Shedd and Miley both use
    this pattern. Regex _SHEDD_CHAPTER_RE / _MILEY_CHAPTER_RE absorbs the corruption.
  LECT[A-Z]+ headings: same OCR-corruption pattern for lecture-format works.
  Two-signal TOC filtering: headings that appear in both TOC and body are disambiguated
    by a second signal (subheading on the following line). See _is_toc_heading().
  Shedd vol-3 supplementary: uses topic section headings, not chapter headings --
    handled separately by parse_shedd_vol3().
  Miley next-line title: the chapter title appears on the line AFTER the CHAP... heading
    line, requiring a two-line lookahead in _parse_miley().
"""

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import traceback
import urllib.request  # standards: download only
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from ocd_kernel.lib.schema_enums import get_enum  # noqa: E402
from build.lib.text_utils import compute_source_hash, smart_title  # noqa: E402
from build.lib.pg_inline_markup import (  # noqa: E402
    append_pg_inline_markup_note,
    decode_pg_inline_markup,
)
from build.parsers._framework import (  # noqa: E402
    assert_source_evidence,
    assert_evidence_for_synthetic_boundaries,
)

RAW_DIR = REPO_ROOT / "raw" / "gutenberg"
OUTPUT_DIR_ST = REPO_ROOT / "data" / "structured-text"
OUTPUT_DIR_CAT = REPO_ROOT / "data" / "catechisms"
LOG_FILE = Path(__file__).resolve().parent / "gutenberg_systematics.log"

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "build/parsers/gutenberg_systematics.py@v1.0.0"

# User-Agent for downloading (both PG and IA)
UA = "OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)"
DOWNLOAD_DELAY_SECONDS = 10

STRUCTURED_TEXT__META__TRADITION = get_enum("structured_text", "meta", "tradition")
STRUCTURED_TEXT__DATA__WORK_KIND = get_enum("structured_text", "data", "work_kind")
STRUCTURED_TEXT__META__ERA = get_enum("structured_text", "meta", "era")
STRUCTURED_TEXT__META__AUDIENCE = get_enum("structured_text", "meta", "audience")
STRUCTURED_TEXT__META__COMPLETENESS = get_enum("structured_text", "meta", "completeness")

# PG body markers
PG_START_RE = re.compile(r"\*\*\*\s*START OF", re.IGNORECASE)
PG_END_RE = re.compile(r"\*\*\*\s*END OF", re.IGNORECASE)


def local_now() -> datetime:
    return datetime.now(timezone.utc)

# ---------------------------------------------------------------------------
# Work config
# ---------------------------------------------------------------------------

WORK_CONFIG = [
    # --- Strong ---
    {
        "slug": "strong-systematic-theology-vol-1",
        "source_type": "pg",
        "pg_id": 44035,
        "volume": 1,
        "title": "Systematic Theology, Vol. 1",
        "author": "Augustus H. Strong",
        "author_id": "strong-augustus",
        "author_birth_year": 1836,
        "author_death_year": 1921,
        "pub_year": 1907,
        "work_kind": "systematic-theology",
        "tradition": ["baptist", "evangelical"],
        "tradition_notes": (
            "Strong's Systematic Theology (1907) is the defining 19th-century Baptist "
            "systematic. Published by Judson Press in a revised and enlarged one-volume "
            "compendium; Project Gutenberg presents this as three files."
        ),
        "era": "modern",
        "audience": "scholarly",
        "original_lang": "en",
        "source_edition": "Revised and enlarged edition (Judson Press, 1907), PG#44035 (Vol. 1 of 3 files)",
    },
    {
        "slug": "strong-systematic-theology-vol-2",
        "source_type": "pg",
        "pg_id": 44555,
        "volume": 2,
        "title": "Systematic Theology, Vol. 2",
        "author": "Augustus H. Strong",
        "author_id": "strong-augustus",
        "author_birth_year": 1836,
        "author_death_year": 1921,
        "pub_year": 1907,
        "work_kind": "systematic-theology",
        "tradition": ["baptist", "evangelical"],
        "tradition_notes": (
            "Strong's Systematic Theology (1907) is the defining 19th-century Baptist "
            "systematic. Published by Judson Press in a revised and enlarged one-volume "
            "compendium; Project Gutenberg presents this as three files."
        ),
        "era": "modern",
        "audience": "scholarly",
        "original_lang": "en",
        "source_edition": "Revised and enlarged edition (Judson Press, 1907), PG#44555 (Vol. 2 of 3 files)",
    },
    {
        "slug": "strong-systematic-theology-vol-3",
        "source_type": "pg",
        "pg_id": 45283,
        "volume": 3,
        "title": "Systematic Theology, Vol. 3",
        "author": "Augustus H. Strong",
        "author_id": "strong-augustus",
        "author_birth_year": 1836,
        "author_death_year": 1921,
        "pub_year": 1907,
        "work_kind": "systematic-theology",
        "tradition": ["baptist", "evangelical"],
        "tradition_notes": (
            "Strong's Systematic Theology (1907) is the defining 19th-century Baptist "
            "systematic. Published by Judson Press in a revised and enlarged one-volume "
            "compendium; Project Gutenberg presents this as three files."
        ),
        "era": "modern",
        "audience": "scholarly",
        "original_lang": "en",
        "source_edition": "Revised and enlarged edition (Judson Press, 1907), PG#45283 (Vol. 3 of 3 files)",
    },
    # --- Dabney ---
    {
        "slug": "dabney-systematic-theology",
        "source_type": "ia",
        "ia_id": "syllabusnotesof00dabn",
        "volume": None,
        "title": "Systematic Theology",
        "author": "R. L. Dabney",
        "author_id": "dabney-r-l",
        "author_birth_year": 1820,
        "author_death_year": 1898,
        "pub_year": 1871,
        "work_kind": "systematic-theology",
        "tradition": ["reformed", "presbyterian"],
        "tradition_notes": (
            "Dabney's Systematic Theology (1871), originally titled 'Syllabus and Notes of "
            "the Course of Systematic and Polemic Theology,' is the defining Southern "
            "Presbyterian systematic theology. Source: Internet Archive DjVuTXT "
            "(OCR from 1871 Union Theological Seminary edition)."
        ),
        "era": "modern",
        "audience": "scholarly",
        "original_lang": "en",
        "source_edition": "Union Theological Seminary, Virginia, 1871. Internet Archive item syllabusnotesof00dabn.",
        "has_synthetic_boundaries": True,
        "expected_source_evidence": [
            "SYLLABUS  AND  NOTES",
            "1871",
        ],
    },
    # --- Shedd ---
    {
        "slug": "shedd-dogmatic-theology-vol-1",
        "source_type": "ia",
        "ia_id": "dogmatictheology01sheduoft",
        "volume": 1,
        "title": "Dogmatic Theology, Vol. 1",
        "author": "W. G. T. Shedd",
        "author_id": "shedd-w-g-t",
        "author_birth_year": 1820,
        "author_death_year": 1894,
        "pub_year": 1888,
        "work_kind": "systematic-theology",
        "tradition": ["reformed", "presbyterian"],
        "tradition_notes": (
            "Shedd's Dogmatic Theology (1888-1894) is considered the most philosophically "
            "rigorous Reformed systematic. Source: Internet Archive DjVuTXT "
            "(University of Toronto scan, 1888 C. Scribner's Sons edition)."
        ),
        "era": "modern",
        "audience": "scholarly",
        "original_lang": "en",
        "source_edition": "C. Scribner's Sons, New York, 1888 (Vol. 1). IA:dogmatictheology01sheduoft.",
        "has_synthetic_boundaries": True,
        "expected_source_evidence": [
            "VOLUME  I.",
            "COPYRIGHT,  1888",
        ],
    },
    {
        "slug": "shedd-dogmatic-theology-vol-2",
        "source_type": "ia",
        "ia_id": "dogmatictheology02sheduoft",
        "volume": 2,
        "title": "Dogmatic Theology, Vol. 2",
        "author": "W. G. T. Shedd",
        "author_id": "shedd-w-g-t",
        "author_birth_year": 1820,
        "author_death_year": 1894,
        "pub_year": 1889,
        "work_kind": "systematic-theology",
        "tradition": ["reformed", "presbyterian"],
        "tradition_notes": (
            "Shedd's Dogmatic Theology (1888-1894) is considered the most philosophically "
            "rigorous Reformed systematic. Source: Internet Archive DjVuTXT "
            "(University of Toronto scan, 1889 C. Scribner's Sons edition)."
        ),
        "era": "modern",
        "audience": "scholarly",
        "original_lang": "en",
        "source_edition": "C. Scribner's Sons, New York, 1889 (Vol. 2). IA:dogmatictheology02sheduoft.",
        "has_synthetic_boundaries": True,
        "expected_source_evidence": [
            "VOLUME  II.",
            "ANTHROPOLOGY",
        ],
    },
    {
        "slug": "shedd-dogmatic-theology-vol-3",
        "source_type": "ia",
        "ia_id": "dogmatictheology03shed_0",
        "volume": 3,
        "title": "Dogmatic Theology, Vol. 3",
        "author": "W. G. T. Shedd",
        "author_id": "shedd-w-g-t",
        "author_birth_year": 1820,
        "author_death_year": 1894,
        "pub_year": 1894,
        "work_kind": "systematic-theology",
        "tradition": ["reformed", "presbyterian"],
        "tradition_notes": (
            "Shedd's Dogmatic Theology (1888-1894) is considered the most philosophically "
            "rigorous Reformed systematic. Vol. 3 contains History of Doctrine and supplementary "
            "essays. Source: Internet Archive DjVuTXT (1894 C. Scribner's Sons edition)."
        ),
        "era": "modern",
        "audience": "scholarly",
        "original_lang": "en",
        "source_edition": "C. Scribner's Sons, New York, 1894 (Vol. 3). IA:dogmatictheology03shed_0.",
        "has_synthetic_boundaries": True,
        "expected_source_evidence": [
            "COPYRIGHT, 1894",
            "September, 1894",
        ],
    },
    # --- Miley ---
    {
        "slug": "miley-systematic-theology-vol-1",
        "source_type": "ia",
        "ia_id": "systematictheolo01mile",
        "volume": 1,
        "title": "Systematic Theology, Vol. 1",
        "author": "John Miley",
        "author_id": "miley-john",
        "author_birth_year": 1813,
        "author_death_year": 1895,
        "pub_year": 1892,
        "work_kind": "systematic-theology",
        "tradition": ["wesleyan", "methodist"],
        "tradition_notes": (
            "Miley's Systematic Theology (1892-1894) is the defining Wesleyan systematic. "
            "Critical for non-Reformed perspectives. Arminian soteriology. "
            "Source: Internet Archive DjVuTXT (Hunt & Eaton, 1892 edition)."
        ),
        "era": "modern",
        "audience": "scholarly",
        "original_lang": "en",
        "source_edition": "Hunt & Eaton, New York / Cranston & Stowe, Cincinnati, 1892 (Vol. 1). IA:systematictheolo01mile.",
        "has_synthetic_boundaries": True,
        "expected_source_evidence": [
            "HUNT  &  EATON",
            "1892",
        ],
    },
    {
        "slug": "miley-systematic-theology-vol-2",
        "source_type": "ia",
        "ia_id": "systematictheolo02mile",
        "volume": 2,
        "title": "Systematic Theology, Vol. 2",
        "author": "John Miley",
        "author_id": "miley-john",
        "author_birth_year": 1813,
        "author_death_year": 1895,
        "pub_year": 1894,
        "work_kind": "systematic-theology",
        "tradition": ["wesleyan", "methodist"],
        "tradition_notes": (
            "Miley's Systematic Theology (1892-1894) is the defining Wesleyan systematic. "
            "Critical for non-Reformed perspectives. Arminian soteriology. "
            "Source: Internet Archive DjVuTXT (Eaton & Mains, 1894 edition; publisher "
            "renamed from Hunt & Eaton in 1894)."
        ),
        "era": "modern",
        "audience": "scholarly",
        "original_lang": "en",
        "source_edition": "Eaton & Mains, New York / Curts & Jennings, Cincinnati, 1894 (Vol. 2). IA:systematictheolo02mile.",
        "has_synthetic_boundaries": True,
        "expected_source_evidence": [
            "EATON   &  MAINS",
            "Copyright,  1894",
        ],
    },
    # --- A. A. Hodge (catechism_qa) ---
    {
        "slug": "aa-hodge-outlines",
        "source_type": "ia",
        "ia_id": "outlinesoftheolo1879hodg",
        "volume": None,
        "title": "Outlines of Theology",
        "author": "A. A. Hodge",
        "author_id": "hodge-a-a",
        "author_birth_year": 1823,
        "author_death_year": 1886,
        "pub_year": 1879,
        "work_kind": "catechism_qa",  # schema key, not structured_text work_kind
        "tradition": ["reformed", "presbyterian"],
        "tradition_notes": (
            "A. A. Hodge's Outlines of Theology (1879) is a Q&A companion to Charles Hodge's "
            "Systematic Theology. Uses question-and-answer format throughout. Old Princeton / "
            "Reformed tradition. Source: Internet Archive DjVuTXT (Robert Carter & Bros., 1879)."
        ),
        "era": "modern",
        "audience": "scholarly",
        "original_lang": "en",
        "source_edition": "Robert Carter & Bros., New York, 1879. IA:outlinesoftheolo1879hodg.",
    },
    # --- Richard Hooker ---
    {
        "slug": "hooker-ecclesiastical-polity",
        "source_type": "ia_multi",
        "ia_volumes": [
            {"volume": 1, "ia_id": "worksofrichardho0001hook"},
            {"volume": 2, "ia_id": "worksofrichardho0002hook"},
            {"volume": 3, "ia_id": "worksofrichardho0003hook_pt1"},
        ],
        "volume": None,
        "title": "Of the Laws of Ecclesiastical Polity",
        "author": "Richard Hooker",
        "author_id": "hooker-richard",
        "author_birth_year": 1554,
        "author_death_year": 1600,
        "pub_year": 1597,
        "work_kind": "treatise",
        "tradition": ["anglican"],
        "tradition_notes": (
            "Hooker's Laws is a foundational Anglican theological and ecclesiological "
            "treatise. This acquisition uses John Keble's 1836 Oxford edition."
        ),
        "era": "reformation",
        "audience": "scholarly",
        "original_lang": "en",
        "source_edition": (
            "John Keble, ed., The Works of Richard Hooker, Oxford University Press, "
            "1836, vols. 1-3. Internet Archive DjVuTXT scans."
        ),
        "processing_notes": (
            "Parser strategy: extend gutenberg_systematics.py rather than fork. Hooker "
            "matches the existing multi-volume structured_text parser shape; its extra "
            "Keble apparatus is handled by work-specific book ranges and cleanup. The "
            "plain-text OCR does not expose stable chapter title lines, so numbered "
            "Roman divisions and running-header chapter signals are normalised into "
            "chapter nodes. Keble editorial footnotes and marginal notes remain inline "
            "where OCR interleaves them; sermons and the tractate on Justification are "
            "outside this Polity-only output."
        ),
    },
    # --- Martin Luther ---
    # Census decision: both Luther works fit this parser's structured_text
    # surface but need dedicated functions. Galatians has clean PG CHAPTER
    # markers; Bondage is IA OCR with stable top-level PART boundaries and
    # noisy running heads, so parsing it through generic WORK_CONFIG heading
    # detection would over-count page headers as sections.
    {
        "slug": "luther-bondage-of-the-will",
        "source_type": "web",
        "raw_filename": "luther-bondage-of-the-will-cole-covenanter.txt",
        "source_url": "https://www.covenanter.org/reformed/2015/7/8/martin-luthers-book-concerning-the-bondage-of-the-will",
        "provenance_source_type": "web_transcription",
        "source_format": "HTML transcription cached as extracted UTF-8 text",
        "processing_method": "automated-with-review",
        "volume": None,
        "title": "The Bondage of the Will",
        "author": "Martin Luther",
        "author_id": "luther-martin",
        "author_birth_year": 1483,
        "author_death_year": 1546,
        "pub_year": 1823,
        "work_kind": "treatise",
        "tradition": ["lutheran"],
        "tradition_notes": (
            "Luther's 1525 reply to Erasmus is a major Reformation treatise on "
            "human will, grace, and divine sovereignty. This dataset uses the "
            "public-domain 1823 English translation."
        ),
        "era": "reformation",
        "audience": "scholarly",
        "original_lang": "la",
        "translator": "Henry Cole",
        "expected_source_evidence": [
            "HENRY COLE.",
            "London, March, 1823.",
            "Conclusion (Sections 167-168)",
        ],
        "source_edition": (
            "Henry Cole, trans., Martin Luther on the Bondage of the Will, "
            "London: T. Bensley for W. Simpkin and R. Marshall, 1823. "
            "Covenanter web transcription of the public-domain Cole translation."
        ),
        "processing_notes": (
            "Covenanter HTML transcription of the 1823 Henry Cole translation. "
            "Parsed by page-level section groups matching the source index."
        ),
    },
    {
        "slug": "luther-commentary-on-galatians",
        "source_type": "pg",
        "pg_id": 1549,
        "source_url": "https://www.gutenberg.org/ebooks/1549",
        "provenance_source_type": "project_gutenberg",
        "volume": None,
        "title": "Commentary on the Epistle to the Galatians",
        "author": "Martin Luther",
        "author_id": "luther-martin",
        "author_birth_year": 1483,
        "author_death_year": 1546,
        "pub_year": 1937,
        "work_kind": "treatise",
        "tradition": ["lutheran"],
        "tradition_notes": (
            "Luther's 1535 Galatians commentary is a central Reformation text on "
            "justification by faith. This public-domain English edition is an "
            "abridged translation by Theodore Graebner."
        ),
        "era": "reformation",
        "audience": "lay",
        "original_lang": "la",
        "translator": "Theodore Graebner",
        "expected_source_evidence": [
            "Translator: Theodore Graebner",
            "Translated by Theodore Graebner",
            "CHAPTER 6",
        ],
        "source_edition": (
            "Theodore Graebner, trans., Commentary on the Epistle to the Galatians "
            "(1535), public-domain English edition. PG#1549."
        ),
        "processing_notes": (
            "PG plain-text edition. Wrapper stripped; Preface, Luther's Introduction, "
            "and six chapter headings parsed into top-level section nodes."
        ),
    },
]


def _validate_configs() -> None:
    for cfg in WORK_CONFIG:
        if cfg["slug"] == "aa-hodge-outlines":
            continue
        slug = cfg["slug"]
        for tradition in cfg.get("tradition", []):
            assert tradition in STRUCTURED_TEXT__META__TRADITION, f"{slug}: invalid tradition value {tradition!r}"
        assert (work_kind := cfg["work_kind"]) in STRUCTURED_TEXT__DATA__WORK_KIND, (
            f"{slug}: invalid work_kind value {work_kind!r}"
        )
        assert (era := cfg["era"]) in STRUCTURED_TEXT__META__ERA, f"{slug}: invalid era value {era!r}"
        assert (audience := cfg["audience"]) in STRUCTURED_TEXT__META__AUDIENCE, (
            f"{slug}: invalid audience value {audience!r}"
        )
        if completeness := cfg.get("completeness"):
            assert completeness in STRUCTURED_TEXT__META__COMPLETENESS, (
                f"{slug}: invalid completeness value {completeness!r}"
            )


_validate_configs()

# Slug -> config lookup
_WORK_BY_SLUG = {w["slug"]: w for w in WORK_CONFIG}


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------


def pg_cache_url(pg_id: int) -> str:
    return f"http://www.gutenberg.org/cache/epub/{pg_id}/pg{pg_id}.txt"


def ia_djvutxt_url(ia_id: str) -> str:
    return f"https://archive.org/download/{ia_id}/{ia_id}_djvu.txt"


def raw_path(cfg: dict) -> Path:
    if cfg.get("raw_filename"):
        return RAW_DIR / cfg["raw_filename"]
    if cfg["source_type"] == "ia_multi":
        raise ValueError("ia_multi works have multiple raw paths; use raw_paths(cfg)")
    if cfg["source_type"] == "pg":
        return RAW_DIR / f"pg{cfg['pg_id']}.txt"
    return RAW_DIR / f"{cfg['ia_id']}_djvu.txt"


def raw_paths(cfg: dict) -> list[Path]:
    if cfg["source_type"] == "ia_multi":
        return [RAW_DIR / f"{vol['ia_id']}_djvu.txt" for vol in cfg["ia_volumes"]]
    return [raw_path(cfg)]


def source_urls(cfg: dict) -> list[str]:
    if cfg.get("source_url"):
        return [cfg["source_url"]]
    if cfg["source_type"] == "ia_multi":
        return [ia_djvutxt_url(vol["ia_id"]) for vol in cfg["ia_volumes"]]
    if cfg["source_type"] == "pg":
        return [pg_cache_url(cfg["pg_id"])]
    return [ia_djvutxt_url(cfg["ia_id"])]


def download_file(url: str, dest: Path, log_lines: list) -> bool:
    """Download url to dest with UA header. Follow redirects. 10s delay. Returns True on success."""
    if dest.exists():
        log(f"  Cached: {dest.name}", log_lines)
        return True
    log(f"  Downloading {url} -> {dest.name}", log_lines)
    time.sleep(DOWNLOAD_DELAY_SECONDS)
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as resp:
                dest.write_bytes(resp.read())
            log(f"  Saved {dest.stat().st_size:,} bytes", log_lines)
            return True
        except Exception as exc:
            if attempt < 3:
                wait = 2 ** attempt
                log(f"  Attempt {attempt} failed ({exc}); retrying in {wait}s", log_lines)
                time.sleep(wait)
            else:
                log(f"  ERROR downloading {url}: {exc}", log_lines)
    return False


def download_work(cfg: dict, log_lines: list) -> bool:
    """Download the raw file for a work. Returns True on success."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if cfg["source_type"] == "web":
        log(f"  Web source requires pre-cached file: {raw_path(cfg).name}", log_lines)
        return raw_path(cfg).exists()
    if cfg["source_type"] == "ia_multi":
        ok = True
        for vol in cfg["ia_volumes"]:
            dest = RAW_DIR / f"{vol['ia_id']}_djvu.txt"
            ok = download_file(ia_djvutxt_url(vol["ia_id"]), dest, log_lines) and ok
        return ok
    dest = raw_path(cfg)
    if cfg["source_type"] == "pg":
        return download_file(pg_cache_url(cfg["pg_id"]), dest, log_lines)
    return download_file(ia_djvutxt_url(cfg["ia_id"]), dest, log_lines)


# ---------------------------------------------------------------------------
# Text preparation
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
            "Could not find PG start/end markers — verify the raw file is a valid "
            "Project Gutenberg plain-text download (check raw/ cache or re-run --download)"
        )
    return lines[start_idx + 1 : end_idx]


def prepare_ia_lines(text: str) -> list:
    """Prepare Internet Archive DjVuTXT lines: replace form-feeds, split."""
    cleaned = text.replace("\f", "\n\n")
    return cleaned.splitlines()


def source_format(cfg: dict) -> str:
    if cfg.get("source_format"):
        return cfg["source_format"]
    return "plain text (UTF-8)" if cfg["source_type"] == "pg" else "DjVuTXT (OCR)"


def processing_method(cfg: dict) -> str:
    if cfg.get("processing_method"):
        return cfg["processing_method"]
    return "automated" if cfg["source_type"] == "pg" else "ocr-with-review"


def gather_paragraphs(lines: list, start: int, stop: int) -> list:
    """Collect blank-line-separated paragraph blocks from lines[start:stop]."""
    paragraphs = []
    current_block = []
    for i in range(start, min(stop, len(lines))):
        stripped = lines[i].strip()
        if not stripped:
            if current_block:
                text = " ".join(current_block)
                text = " ".join(text.split())
                if text:
                    paragraphs.append(decode_pg_inline_markup(text))
                current_block = []
        else:
            current_block.append(stripped)
    if current_block:
        text = " ".join(current_block)
        text = " ".join(text.split())
        if text:
            paragraphs.append(decode_pg_inline_markup(text))
    return paragraphs


def word_count(blocks: list) -> int:
    return sum(len(b.split()) for b in blocks)


_ROMAN_VALUES = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
    "D": 500,
    "M": 1000,
}


def roman_to_int(value: str) -> int | None:
    value = value.upper().replace("J", "I").replace("1", "I")
    if value in {"VL", "VI.", "VIL"}:
        return 6
    if value in {"VIIL", "VII."}:
        return 7
    if value in {"VIIIL", "VIII."}:
        return 8
    total = 0
    prev = 0
    for char in reversed(value):
        current = _ROMAN_VALUES.get(char)
        if current is None:
            return None
        if current < prev:
            total -= current
        else:
            total += current
            prev = current
    return total or None


def int_to_roman(value: int) -> str:
    parts = []
    for numeral, amount in (
        ("C", 100),
        ("XC", 90),
        ("L", 50),
        ("XL", 40),
        ("X", 10),
        ("IX", 9),
        ("V", 5),
        ("IV", 4),
        ("I", 1),
    ):
        while value >= amount:
            parts.append(numeral)
            value -= amount
    return "".join(parts)


# ---------------------------------------------------------------------------
# Quality stats
# ---------------------------------------------------------------------------


def print_quality_stats(sections: list, label: str, log_lines: list) -> None:
    total_sections = total_blocks = empty_sections = 0
    all_wc = []

    def traverse(sec_list: list) -> None:
        nonlocal total_sections, total_blocks, empty_sections
        for sec in sec_list:
            total_sections += 1
            blocks = sec.get("content_blocks", [])
            total_blocks += len(blocks)
            if not blocks and not sec.get("children"):
                empty_sections += 1
            all_wc.append(sec.get("word_count", 0))
            traverse(sec.get("children", []))

    traverse(sections)
    all_wc.sort()
    log(f"  {label}: {total_sections} sections, {total_blocks} blocks, "
        f"{empty_sections} empty leaf sections", log_lines)
    if all_wc:
        mid = len(all_wc) // 2
        log(f"    word_count: min={all_wc[0]}, median={all_wc[mid]}, max={all_wc[-1]}",
            log_lines)


# ---------------------------------------------------------------------------
# Strong parser (PG, Part -> Chapter)
# ---------------------------------------------------------------------------

_STRONG_PART_RE = re.compile(r"^PART\s+([IVX]+)\.\s+(.+)$")
_STRONG_CHAPTER_RE = re.compile(r"^Chapter\s+([IVX]+)\.\s+(.+)$")


def parse_strong(body_lines: list, log_lines: list) -> list:
    """Parse Strong's Systematic Theology body into sections (Part -> Chapter).

    Returns a list of section dicts (the 'sections' array).
    """
    events = []
    for i, line in enumerate(body_lines):
        s = line.strip()
        if not s:
            continue
        m = _STRONG_PART_RE.match(s)
        if m:
            events.append((i, "part", m.group(1), m.group(2).rstrip(".")))
            continue
        m = _STRONG_CHAPTER_RE.match(s)
        if m:
            events.append((i, "chapter", m.group(1), m.group(2).rstrip(".")))

    log(f"  Strong events: {sum(1 for e in events if e[1]=='part')} parts, "
        f"{sum(1 for e in events if e[1]=='chapter')} chapters", log_lines)

    sections = []
    part_events = [(e[0], e[2], e[3]) for e in events if e[1] == "part"]
    all_ch_events = [(e[0], e[2], e[3]) for e in events if e[1] == "chapter"]

    for p_idx, (p_line, p_roman, p_title) in enumerate(part_events):
        next_p_line = part_events[p_idx + 1][0] if p_idx + 1 < len(part_events) else len(body_lines)
        ch_events = [(l, r, t) for l, r, t in all_ch_events if p_line < l < next_p_line]

        children = []
        for c_idx, (c_line, c_roman, c_title) in enumerate(ch_events):
            next_c_line = ch_events[c_idx + 1][0] if c_idx + 1 < len(ch_events) else next_p_line
            blocks = gather_paragraphs(body_lines, c_line + 1, next_c_line)
            children.append({
                "section_type": "chapter",
                "label": f"Chapter {c_roman}",
                "title": c_title or None,
                "content_blocks": blocks,
                "scripture_references": [],
                "word_count": word_count(blocks),
                "children": [],
            })

        if not children:
            log(f"  Part {p_roman}: 0 chapters (skipped — no content)", log_lines)
            continue
        part_sec = {
            "section_type": "part",
            "label": f"Part {p_roman}",
            "title": p_title or None,
            "content_blocks": [],
            "scripture_references": [],
            "word_count": sum(c["word_count"] for c in children),
            "children": children,
        }
        sections.append(part_sec)
        log(f"  Part {p_roman}: {len(children)} chapters, {part_sec['word_count']} words",
            log_lines)

    # Collect any content before the first Part as a preface
    first_event_line = events[0][0] if events else len(body_lines)
    pre_blocks = gather_paragraphs(body_lines, 0, first_event_line)
    if pre_blocks:
        sections.insert(0, {
            "section_type": "preface",
            "label": "Front Matter",
            "title": None,
            "content_blocks": pre_blocks,
            "scripture_references": [],
            "word_count": word_count(pre_blocks),
            "children": [],
        })

    return sections


# ---------------------------------------------------------------------------
# Dabney parser (IA, Part -> Lecture)
# ---------------------------------------------------------------------------

# OCR-tolerant: LECTURE may appear as LECTUEB, LECTUBE, LECTUKE, LECTXJKE, LECTITEE, etc.
# Roman numerals may be OCR-corrupted (IY for IV, XXYIIL for XXVIII, etc.) — capture raw.
_DABNEY_LECTURE_RE = re.compile(r"^LECT[A-Z]+\s+(.+?)\.?\s*$")
_DABNEY_PART_RE = re.compile(r"^PART\s+([IVX]+)\.?\s*$")

# ALL CAPS lines < 50 chars that are not LECT or PART headings treated as division titles
_DABNEY_DIVISION_RE = re.compile(r"^[A-Z][A-Z\s,\.\(\)]{4,49}$")


def _find_first_structural_line_dabney(lines: list) -> int:
    """Return index of first LECT or PART heading in body (skips TOC/front-matter ~600 lines)."""
    for i, line in enumerate(lines):
        if i < 600:
            continue
        s = line.strip()
        if _DABNEY_LECTURE_RE.match(s) or _DABNEY_PART_RE.match(s):
            return i
    return 0


def parse_dabney(body_lines: list, log_lines: list) -> list:
    """Parse Dabney's Systematic Theology body into sections (Part -> Lecture).

    Dabney uses LECTURE headings (OCR-tolerant) rather than CHAPTER.
    Returns a list of section dicts.
    """
    first_line = _find_first_structural_line_dabney(body_lines)
    lines = body_lines[first_line:]

    events = []
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        m = _DABNEY_PART_RE.match(s)
        if m:
            events.append((i, "part", m.group(1), None))
            continue
        m = _DABNEY_LECTURE_RE.match(s)
        if m:
            events.append((i, "lecture", m.group(1), None))

    log(f"  Dabney events: {sum(1 for e in events if e[1]=='part')} parts, "
        f"{sum(1 for e in events if e[1]=='lecture')} lectures", log_lines)

    sections = []
    part_events = [(e[0], e[2], e[3]) for e in events if e[1] == "part"]
    all_lect_events = [(e[0], e[2], e[3]) for e in events if e[1] == "lecture"]

    # Add synthetic PART I when lectures precede the first explicit PART marker
    if part_events and all_lect_events and all_lect_events[0][0] < part_events[0][0]:
        part_events = [(-1, "I", None)] + part_events

    if part_events:
        for p_idx, (p_line, p_roman, _) in enumerate(part_events):
            next_p_line = part_events[p_idx + 1][0] if p_idx + 1 < len(part_events) else len(lines)
            lect_events = [(l, r, t) for l, r, t in all_lect_events if p_line < l < next_p_line]

            children = []
            for l_idx, (l_line, l_roman, _) in enumerate(lect_events):
                next_l_line = lect_events[l_idx + 1][0] if l_idx + 1 < len(lect_events) else next_p_line
                blocks = gather_paragraphs(lines, l_line + 1, next_l_line)
                children.append({
                    "section_type": "chapter",
                    "label": f"Lecture {l_roman}",
                    "title": None,
                    "content_blocks": blocks,
                    "scripture_references": [],
                    "word_count": word_count(blocks),
                    "children": [],
                })

            part_sec = {
                "section_type": "part",
                "label": f"Part {p_roman}",
                "title": None,
                "content_blocks": [],
                "scripture_references": [],
                "word_count": sum(c["word_count"] for c in children),
                "children": children,
            }
            sections.append(part_sec)
            log(f"  Part {p_roman}: {len(children)} lectures, {part_sec['word_count']} words",
                log_lines)
    else:
        # No explicit PART markers: emit lectures at top level
        for l_idx, (l_line, l_roman, _) in enumerate(all_lect_events):
            next_l_line = all_lect_events[l_idx + 1][0] if l_idx + 1 < len(all_lect_events) else len(lines)
            blocks = gather_paragraphs(lines, l_line + 1, next_l_line)
            sections.append({
                "section_type": "chapter",
                "label": f"Lecture {l_roman}",
                "title": None,
                "content_blocks": blocks,
                "scripture_references": [],
                "word_count": word_count(blocks),
                "children": [],
            })
        log(f"  Dabney (no PART markers): {len(all_lect_events)} lectures", log_lines)

    # If no structural headings found at all, emit whole text as one section
    if not sections:
        log("  WARNING: no PART or LECTURE headings found -- emitting as single chapter", log_lines)
        blocks = gather_paragraphs(lines, 0, len(lines))
        sections.append({
            "section_type": "chapter",
            "label": "Full Text",
            "title": None,
            "content_blocks": blocks,
            "scripture_references": [],
            "word_count": word_count(blocks),
            "children": [],
        })

    return sections


# ---------------------------------------------------------------------------
# Shedd parser (IA, Chapter -> content_blocks)
# ---------------------------------------------------------------------------

# OCR-tolerant: CHAPTER may appear as CHAPTEK, CHAPTEE, etc.
_SHEDD_CHAPTER_RE = re.compile(r"^CHAP[A-Z]+\s+([IVX]+)\.\s*(.*)$")

# Vol 3 is a supplementary volume organised by topic division, not CHAPTER headings.
_SHEDD_VOL3_SECTION_RE = re.compile(
    r"^(THEOLOGICAL INTRODUCTION|BIBLIOLOGY"
    r"|THEOLOGY \(DOCTRINE OF GOD\)|ANTHROPOLOGY"
    r"|CHRISTOLOGY|SOTERIOLOGY\.?|ESCHATOLOGY)$"
)

_SHEDD_DIVISION_RE = re.compile(r"^[A-Z][A-Z\s\-]{4,59}$")
_SHEDD_CHAPTER_PREFIX = re.compile(r"^CHAP[A-Z]+\s")


# Matches TOC page-number entries: "TITLE .....  53" or bare digit line
_SHEDD_TOC_PAGE_RE = re.compile(r"[\.\s]{3,}\d+\s*$|^\d+\s*$")


def _is_shedd_toc_chapter(lines: list, idx: int) -> bool:
    """True if this CHAPTER line is a TOC entry.

    Signals: next non-empty line is a TOC page entry (dots/spaces then digits),
    or another CHAPTER heading appears within 20 lines (tight cluster = TOC).
    """
    for j in range(idx + 1, min(len(lines), idx + 20)):
        s = lines[j].strip()
        if not s:
            continue
        if s == "PAGE" or _SHEDD_TOC_PAGE_RE.search(s):
            return True
        if _SHEDD_CHAPTER_RE.match(s):
            return True
    return False


def _find_first_structural_line_shedd(lines: list) -> int:
    """Return index of first body CHAPTER heading (skipping TOC entries) or vol-3 section."""
    for i, line in enumerate(lines):
        s = line.strip()
        if _SHEDD_CHAPTER_RE.match(s) and not _is_shedd_toc_chapter(lines, i):
            return i
        if _SHEDD_VOL3_SECTION_RE.match(s):
            return i
    return 0


def _parse_shedd_vol3(body_lines: list, log_lines: list) -> list:
    """Parse Shedd vol 3 (supplementary) using topic section headings."""
    seen: set = set()
    events = []
    for i, line in enumerate(body_lines):
        s = line.strip()
        if _SHEDD_VOL3_SECTION_RE.match(s):
            label = s.rstrip(".")
            if label not in seen:
                seen.add(label)
                events.append((i, label))

    log(f"  Shedd vol3 sections: {len(events)}", log_lines)
    if not events:
        blocks = gather_paragraphs(body_lines, 0, len(body_lines))
        return [{"section_type": "chapter", "label": "Full Text", "title": None,
                 "content_blocks": blocks, "scripture_references": [],
                 "word_count": word_count(blocks), "children": []}]

    sections = []
    for s_idx, (s_line, s_label) in enumerate(events):
        next_s = events[s_idx + 1][0] if s_idx + 1 < len(events) else len(body_lines)
        blocks = gather_paragraphs(body_lines, s_line + 1, next_s)
        sections.append({
            "section_type": "part",
            "label": smart_title(s_label),
            "title": None,
            "content_blocks": blocks,
            "scripture_references": [],
            "word_count": word_count(blocks),
            "children": [],
        })
        log(f"  Shedd vol3 {s_label}: {word_count(blocks)} words", log_lines)
    return sections


def parse_shedd(body_lines: list, log_lines: list, slug: str = "") -> list:
    """Parse Shedd's Dogmatic Theology (vols 1-2: chapters; vol 3: topic sections)."""
    if slug.endswith("-vol-3"):
        return _parse_shedd_vol3(body_lines, log_lines)

    first_line = _find_first_structural_line_shedd(body_lines)
    lines = body_lines[first_line:]

    events = []
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        m = _SHEDD_CHAPTER_RE.match(s)
        if m and not _is_shedd_toc_chapter(lines, i):
            title_inline = m.group(2).strip().rstrip(".") or None
            if title_inline is None:
                for j in range(i + 1, min(len(lines), i + 5)):
                    ns = lines[j].strip()
                    if ns and not re.search(r"\d", ns):
                        title_inline = ns.rstrip(".")
                        break
            events.append((i, "chapter", m.group(1), title_inline))

    log(f"  Shedd events: {len(events)} chapters", log_lines)

    if not events:
        log("  WARNING: no CHAPTER headings found -- emitting as single section", log_lines)
        blocks = gather_paragraphs(lines, 0, len(lines))
        return [{
            "section_type": "chapter",
            "label": "Full Text",
            "title": None,
            "content_blocks": blocks,
            "scripture_references": [],
            "word_count": word_count(blocks),
            "children": [],
        }]

    sections = []
    intro_blocks = gather_paragraphs(lines, 0, events[0][0])
    if intro_blocks and word_count(intro_blocks) > 50:
        sections.append({
            "section_type": "introduction",
            "label": "Introduction",
            "title": None,
            "content_blocks": intro_blocks,
            "scripture_references": [],
            "word_count": word_count(intro_blocks),
            "children": [],
        })

    for c_idx, (c_line, _, c_roman, c_title) in enumerate(events):
        next_c_line = events[c_idx + 1][0] if c_idx + 1 < len(events) else len(lines)
        blocks = gather_paragraphs(lines, c_line + 1, next_c_line)
        sections.append({
            "section_type": "chapter",
            "label": f"Chapter {c_roman}",
            "title": c_title,
            "content_blocks": blocks,
            "scripture_references": [],
            "word_count": word_count(blocks),
            "children": [],
        })
        log(f"  Chapter {c_roman}: {len(blocks)} blocks, {word_count(blocks)} words", log_lines)

    return sections


# ---------------------------------------------------------------------------
# Miley parser (IA, Part -> Chapter)
# ---------------------------------------------------------------------------

# "PART I.-- THEISM:" or "PART I.- THEISM:" (OCR variants of em-dash)
_MILEY_PART_RE = re.compile(r"^PART\s+([IVX]+)\.\s*[-\-]+\s*(.+)$")
_MILEY_PART_SIMPLE_RE = re.compile(r"^PART\s+([IVX]+)\.\s*$")
# OCR-tolerant: CHAPTER may appear as CHAPTEE, CHAPTEX, etc.
# Roman numeral may be corrupted (IY for IV, Vn for VII, Vin for VIII); title on next line.
_MILEY_CHAPTER_RE = re.compile(r"^CHAP[A-Z]+\s+(\S+)\.?\s*$")


def _find_first_structural_line_miley(lines: list) -> int:
    """Return index of first PART heading in Miley body (skips TOC which has no PART markers)."""
    for i, line in enumerate(lines):
        s = line.strip()
        if _MILEY_PART_RE.match(s) or _MILEY_PART_SIMPLE_RE.match(s):
            return i
    return 0


def parse_miley(body_lines: list, log_lines: list) -> list:
    """Parse Miley's Systematic Theology body into sections (Part -> Chapter).

    Returns a list of section dicts.
    """
    first_line = _find_first_structural_line_miley(body_lines)
    lines = body_lines[first_line:]

    events = []
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        m = _MILEY_PART_RE.match(s)
        if m:
            events.append((i, "part", m.group(1), m.group(2).rstrip(":.")))
            continue
        m = _MILEY_PART_SIMPLE_RE.match(s)
        if m:
            p_title = None
            for j in range(i + 1, min(len(lines), i + 5)):
                ns = lines[j].strip()
                if ns:
                    if ns.isupper() and not re.search(r"\d", ns):
                        p_title = ns.rstrip(".")
                    break
            events.append((i, "part", m.group(1), p_title))
            continue
        m = _MILEY_CHAPTER_RE.match(s)
        if m:
            ch_title = None
            for j in range(i + 1, min(len(lines), i + 5)):
                ns = lines[j].strip()
                if ns:
                    if not re.search(r"\d", ns):
                        ch_title = ns.rstrip(".")
                    break
            events.append((i, "chapter", m.group(1), ch_title))

    log(f"  Miley events: {sum(1 for e in events if e[1]=='part')} parts, "
        f"{sum(1 for e in events if e[1]=='chapter')} chapters", log_lines)

    sections = []
    part_events = [(e[0], e[2], e[3]) for e in events if e[1] == "part"]
    all_ch_events = [(e[0], e[2], e[3]) for e in events if e[1] == "chapter"]

    if part_events:
        for p_idx, (p_line, p_roman, p_title) in enumerate(part_events):
            next_p_line = part_events[p_idx + 1][0] if p_idx + 1 < len(part_events) else len(lines)
            ch_events = [(l, r, t) for l, r, t in all_ch_events if p_line < l < next_p_line]

            children = []
            for c_idx, (c_line, c_roman, c_title) in enumerate(ch_events):
                next_c_line = ch_events[c_idx + 1][0] if c_idx + 1 < len(ch_events) else next_p_line
                blocks = gather_paragraphs(lines, c_line + 1, next_c_line)
                children.append({
                    "section_type": "chapter",
                    "label": f"Chapter {c_roman}",
                    "title": c_title or None,
                    "content_blocks": blocks,
                    "scripture_references": [],
                    "word_count": word_count(blocks),
                    "children": [],
                })

            part_sec = {
                "section_type": "part",
                "label": f"Part {p_roman}",
                "title": p_title or None,
                "content_blocks": [],
                "scripture_references": [],
                "word_count": sum(c["word_count"] for c in children),
                "children": children,
            }
            sections.append(part_sec)
            log(f"  Part {p_roman}: {len(children)} chapters, {part_sec['word_count']} words",
                log_lines)
    else:
        # No explicit PART markers: emit chapters at top level
        for c_idx, (c_line, c_roman, c_title) in enumerate(all_ch_events):
            next_c_line = all_ch_events[c_idx + 1][0] if c_idx + 1 < len(all_ch_events) else len(lines)
            blocks = gather_paragraphs(lines, c_line + 1, next_c_line)
            sections.append({
                "section_type": "chapter",
                "label": f"Chapter {c_roman}",
                "title": c_title or None,
                "content_blocks": blocks,
                "scripture_references": [],
                "word_count": word_count(blocks),
                "children": [],
            })
        log(f"  Miley (no PART markers): {len(all_ch_events)} chapters", log_lines)

    if not sections:
        log("  WARNING: no structural headings found -- emitting as single chapter", log_lines)
        blocks = gather_paragraphs(lines, 0, len(lines))
        sections.append({
            "section_type": "chapter",
            "label": "Full Text",
            "title": None,
            "content_blocks": blocks,
            "scripture_references": [],
            "word_count": word_count(blocks),
            "children": [],
        })

    return sections


# ---------------------------------------------------------------------------
# Richard Hooker parser (IA, Keble 1836, 3 vols -> 8 books)
# ---------------------------------------------------------------------------

_HOOKER_BOOK_RE = re.compile(
    r"^\s*(?:THE\s+)?(?:(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH)\s+BOOK|BOOK\s+([IVXLC]+))\.?\s*$",
    re.IGNORECASE,
)
_HOOKER_CHAPTER_RE = re.compile(
    r"^\s*(?:CH(?:AP(?:TER)?)?[.,]?\s*([IVXLC]+)|([IVXLC]+)\.)\b",
    re.IGNORECASE,
)
_HOOKER_RUNNING_HEADER_RE = re.compile(r"^\s*Ch[.,]\s*([ivxlcdmIVXLCDM]+)\.?", re.IGNORECASE)

_HOOKER_BOOK_WORDS = {
    "FIRST": 1,
    "SECOND": 2,
    "THIRD": 3,
    "FOURTH": 4,
    "FIFTH": 5,
    "SIXTH": 6,
    "SEVENTH": 7,
    "EIGHTH": 8,
}
_HOOKER_EXPECTED_CHAPTERS = {1: 16, 2: 8, 3: 11, 4: 14, 5: 81, 6: 6, 7: 24, 8: 9}


def _normalise_hooker_line(line: str) -> str:
    line = line.strip()
    line = line.replace("’", "'").replace("“", '"').replace("”", '"')
    line = re.sub(r"\s+", " ", line)
    return line


def _hooker_book_number(line: str) -> int | None:
    if line and line[0].islower():
        return None
    match = _HOOKER_BOOK_RE.match(line)
    if not match:
        return None
    if match.group(1):
        return _HOOKER_BOOK_WORDS[match.group(1).upper()]
    return roman_to_int(match.group(2) or "")


def _hooker_chapter_number(line: str) -> int | None:
    match = _HOOKER_CHAPTER_RE.match(line)
    if not match:
        return None
    return roman_to_int(match.group(1) or match.group(2) or "")


def _is_hooker_noise(line: str) -> bool:
    if not line:
        return False
    upper = line.upper()
    if upper in {
        "OF THE",
        "LAWS",
        "OF",
        "ECCLESIASTICAL POLITY |.",
        "ECCLESIASTICAL POLITY.",
        "OF THE LAWS OF ECCLESIASTICAL POLITY.",
    }:
        return True
    if re.fullmatch(r"(HOOKER,\s+VOL\.\s+[IVXLC]+\.?|[A-Z] ?[0-9]+|[A-Z]\s*)", upper):
        return True
    if re.fullmatch(r"(BOOK|BOOX|BOO?K)\s*[IVXLC1L., ]*", upper):
        return True
    if re.fullmatch(r"CH[.,]?\s*[IVXLC1L., ]+", upper):
        return True
    if re.fullmatch(r"\d+\s+.+", line) and len(line) < 90:
        return True
    if upper.startswith("THE MATTER CONTAINED IN THIS"):
        return True
    if upper.startswith("MATTER CONTAINED IN THIS"):
        return True
    if upper.startswith("CONTENTS OF THE"):
        return True
    if upper in {"ENDNOTES", "NOTES"}:
        return True
    return False


def _find_hooker_book_events(lines: list[str]) -> list[tuple[int, int]]:
    events: list[tuple[int, int]] = []
    for idx, line in enumerate(lines):
        number = _hooker_book_number(_normalise_hooker_line(line))
        if number is None or number < 1 or number > 8:
            continue
        if not events and number != 1:
            continue
        if events and events[-1][1] == number:
            continue
        if number in {7, 8} and idx < 10000:
            continue
        if events and number <= events[-1][1]:
            continue
        events.append((idx, number))
    return events


def _first_meaningful_line(lines: list[str], start: int, stop: int) -> int:
    for idx in range(start, min(stop, len(lines))):
        line = _normalise_hooker_line(lines[idx])
        if not line or _is_hooker_noise(line):
            continue
        if _HOOKER_CHAPTER_RE.match(line) or _HOOKER_BOOK_RE.match(line):
            continue
        return idx
    return start


def _nearest_hooker_non_noise_line(lines: list[str], target: int, start: int, stop: int) -> int:
    target = max(start, min(target, max(start, stop - 1)))
    for offset in range(0, max(target - start, stop - target) + 1):
        for idx in (target - offset, target + offset):
            if idx < start or idx >= stop:
                continue
            line = _normalise_hooker_line(lines[idx])
            if line and not _is_hooker_noise(line):
                return idx
    return target


def _hooker_toc_chapters(lines: list[str], start: int, body_start: int) -> dict[int, str]:
    chapters: dict[int, str] = {}
    for idx in range(start + 1, min(body_start, len(lines))):
        line = _normalise_hooker_line(lines[idx])
        number = _hooker_chapter_number(line)
        if number is not None and number not in chapters:
            chapters[number] = line
    return chapters


def _build_hooker_locator_table(lines: list[str]) -> dict[tuple[int, int], dict]:
    locators: dict[tuple[int, int], dict] = {}
    book_events = _find_hooker_book_events(lines)
    for book_idx, (book_start, book_number) in enumerate(book_events):
        book_stop = book_events[book_idx + 1][0] if book_idx + 1 < len(book_events) else len(lines)
        body_start = _first_meaningful_line(lines, book_start + 1, book_stop)
        if len(lines) > 1000:
            expected = _HOOKER_EXPECTED_CHAPTERS.get(book_number, 0)
        else:
            detected = [
                _hooker_chapter_number(_normalise_hooker_line(lines[idx]))
                for idx in range(body_start, book_stop)
            ]
            expected = max([number for number in detected if number] or [1])
        body_line = _normalise_hooker_line(lines[body_start])
        locators[(book_number, 1)] = {
            "line_idx": body_start,
            "matched_text": body_line,
            "locator_type": "manual_review",
            "confidence": "low",
        }

        last_confirmed = 1
        for idx in range(body_start + 1, book_stop):
            line = _normalise_hooker_line(lines[idx])
            number = _hooker_chapter_number(line)
            if number is None or number < 2 or number > expected:
                continue
            if number <= last_confirmed or number > last_confirmed + 2:
                continue
            if (book_number, number) in locators:
                continue
            locators[(book_number, number)] = {
                "line_idx": idx,
                "matched_text": line,
                "locator_type": "inline_heading",
                "confidence": "high",
            }
            last_confirmed = number

        running_headers: dict[int, list[tuple[int, str]]] = {}
        for idx in range(body_start + 1, book_stop):
            line = _normalise_hooker_line(lines[idx])
            match = _HOOKER_RUNNING_HEADER_RE.match(line)
            if not match:
                continue
            roman = match.group(1).upper()
            number = roman_to_int(roman)
            if not number or int_to_roman(number) != roman:
                continue
            if 1 <= number <= expected:
                running_headers.setdefault(number, []).append((idx, line))

        for chapter_number in range(2, expected + 1):
            key = (book_number, chapter_number)
            if key in locators:
                continue
            previous_idx = locators.get((book_number, chapter_number - 1), {}).get("line_idx", body_start)
            next_idx = book_stop
            for later in range(chapter_number + 1, expected + 1):
                later_idx = locators.get((book_number, later), {}).get("line_idx")
                if later_idx and later_idx > previous_idx:
                    next_idx = later_idx
                    break
            for idx, line in running_headers.get(chapter_number, []):
                if previous_idx < idx < next_idx:
                    locators[key] = {
                        "line_idx": idx,
                        "matched_text": line,
                        "locator_type": "running_header",
                        "confidence": "medium",
                    }
                    break

        toc_chapters = _hooker_toc_chapters(lines, book_start, body_start)
        for chapter_number in range(2, expected + 1):
            key = (book_number, chapter_number)
            if key in locators or chapter_number not in toc_chapters:
                continue
            target = body_start + ((chapter_number - 1) * max(book_stop - body_start, expected) // expected)
            idx = _nearest_hooker_non_noise_line(lines, target, body_start, book_stop)
            locators[key] = {
                "line_idx": idx,
                "matched_text": toc_chapters[chapter_number],
                "locator_type": "toc_derived",
                "confidence": "low",
            }

        for chapter_number in range(2, expected + 1):
            key = (book_number, chapter_number)
            if key in locators:
                continue
            target = body_start + ((chapter_number - 1) * max(book_stop - body_start, expected) // expected)
            idx = _nearest_hooker_non_noise_line(lines, target, body_start, book_stop)
            locators[key] = {
                "line_idx": idx,
                "matched_text": _normalise_hooker_line(lines[idx]),
                "locator_type": "manual_review",
                "confidence": "low",
            }

    return locators


def _hooker_chapter_events(lines: list[str], start: int, stop: int) -> list[tuple[int, int]]:
    book_number = None
    for idx, number in _find_hooker_book_events(lines):
        if idx == start:
            book_number = number
            break
    if book_number is None:
        return []
    locators = _build_hooker_locator_table(lines)
    if len(lines) > 1000:
        expected = _HOOKER_EXPECTED_CHAPTERS.get(book_number, 0)
    else:
        expected = max(
            [chapter for candidate_book, chapter in locators if candidate_book == book_number]
            or [0]
        )
    events = [
        (locators[(book_number, chapter_number)]["line_idx"], chapter_number)
        for chapter_number in range(1, expected + 1)
        if (book_number, chapter_number) in locators
    ]
    return events


def _hooker_blocks(lines: list[str], start: int, stop: int) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for idx in range(start, min(stop, len(lines))):
        line = _normalise_hooker_line(lines[idx])
        if line.upper() == "ENDNOTES":
            break
        if _HOOKER_BOOK_RE.match(line) or _HOOKER_CHAPTER_RE.match(line) or _is_hooker_noise(line):
            line = ""
        if not line:
            if current:
                block = " ".join(current)
                block = " ".join(block.split())
                if block and len(block) > 1:
                    blocks.append(decode_pg_inline_markup(block))
                current = []
            continue
        current.append(line)
    if current:
        block = " ".join(current)
        block = " ".join(block.split())
        if block and len(block) > 1:
            blocks.append(decode_pg_inline_markup(block))
    return blocks


def parse_hooker(body_lines: list, log_lines: list) -> list:
    """Parse Hooker's Laws from Keble's 1836 IA OCR.

    This extends the existing systematic-theology parser rather than forking a
    new parser: the target shape is the same structured_text section tree, but
    Hooker needs work-specific book-range handling and OCR cleanup. Keble's
    marginal apparatus is interleaved in DjVuTXT, so this parser preserves it
    inline instead of attempting lossy note extraction. The output is Polity
    only; sermons and the separate tractate on Justification are deferred.
    """
    lines = list(body_lines)
    book_events = _find_hooker_book_events(lines)
    if not book_events:
        raise ValueError("No Hooker book boundaries detected")

    locators = _build_hooker_locator_table(lines)
    sections = []
    for idx, (book_start, book_number) in enumerate(book_events):
        book_stop = book_events[idx + 1][0] if idx + 1 < len(book_events) else len(lines)
        chapter_events = _hooker_chapter_events(lines, book_start, book_stop)
        expected = _HOOKER_EXPECTED_CHAPTERS.get(book_number)
        if expected and len(lines) > 1000 and len(chapter_events) != expected:
            raise ValueError(
                f"Hooker Book {int_to_roman(book_number)} expected {expected} chapter locators, "
                f"got {len(chapter_events)}"
            )

        children = []
        for c_idx, (chapter_start, chapter_number) in enumerate(chapter_events):
            later_starts = [
                later_start
                for later_start, _later_number in chapter_events[c_idx + 1:]
                if later_start > chapter_start
            ]
            next_start = min(later_starts) if later_starts else book_stop
            blocks = _hooker_blocks(lines, chapter_start, next_start)
            children.append({
                "section_type": "chapter",
                "label": f"Chapter {int_to_roman(chapter_number)}",
                "title": None,
                "content_blocks": blocks,
                "scripture_references": [],
                "word_count": word_count(blocks),
                "boundary_confidence": locators[(book_number, chapter_number)]["confidence"],
                "children": [],
            })

        section = {
            "section_type": "book",
            "label": f"Book {int_to_roman(book_number)}",
            "title": None,
            "content_blocks": [],
            "scripture_references": [],
            "word_count": sum(child["word_count"] for child in children),
            "children": children,
        }
        sections.append(section)
        log(f"  Hooker Book {int_to_roman(book_number)}: {len(children)} chapters, {section['word_count']} words", log_lines)
    return sections


# ---------------------------------------------------------------------------
# Martin Luther parsers (PG/IA, treatise)
# ---------------------------------------------------------------------------

_LUTHER_GALATIANS_CHAPTER_RE = re.compile(r"^CHAPTER\s+([1-6])\s*$")
_LUTHER_BONDAGE_PART_TITLE = {
    "I": "ERASMUS'S PREFACE REVIEWED.",
    "II": "LUTHER COMMENTS UPON ERASMUS'S PROEM.",
    "III": "LUTHER CONFUTES ERASMUS'S TESTIMONIES IN SUPPORT OF FREEWILL.",
    "IV": "LUTHER DEFENDS CERTAIN TESTIMONIES AGAINST FREEWILL.",
    "V": "FREEWILL PROVED TO BE A LIE.",
}
_LUTHER_BONDAGE_COLE_SECTIONS = {
    "translator-preface": ("preface", "Preface by the Translator", None),
    "introduction": ("introduction", "Introduction", None),
    "section-1": ("section", "Section 1", "Erasmus' Preface Reviewed"),
    "sections-2-6": ("section", "Sections 2-6", "Erasmus' Scepticism"),
    "sections-7-8": ("section", "Sections 7-8", "The Necessity of Knowing God and His Power"),
    "sections-9-27": ("section", "Sections 9-27", "The Sovereignty of God"),
    "sections-28-40": ("section", "Sections 28-40", "Exordium"),
    "sections-41-75": ("section", "Sections 41-75", "Discussion: First Part"),
    "sections-76-134": ("section", "Sections 76-134", "Discussion: Second Part"),
    "sections-135-166": ("section", "Sections 135-166", "Discussion: Third Part"),
    "sections-167-168": ("conclusion", "Conclusion", "Sections 167-168"),
    "appendix-judgment": ("appendix", "Appendix", "Martin Luther's Judgment of Erasmus of Rotterdam"),
    "appendix-armsdoff": ("appendix", "Appendix", "Martin Luther to Nicolas Armsdoff Concerning Erasmus of Rotterdam"),
}


def _normalise_luther_ocr_line(line: str) -> str:
    line = line.strip().replace("—", "--")
    line = line.replace("“", '"').replace("”", '"').replace("’", "'")
    line = re.sub(r"\s+", " ", line)
    return line


def _make_leaf_section(section_type: str, label: str | None, title: str | None, blocks: list[str]) -> dict:
    return {
        "section_type": section_type,
        "label": label,
        "title": title,
        "content_blocks": blocks,
        "scripture_references": [],
        "word_count": word_count(blocks),
        "children": [],
    }


def _luther_blocks(lines: list[str], start: int, stop: int, skip_re: re.Pattern | None = None) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for idx in range(start, min(stop, len(lines))):
        line = _normalise_luther_ocr_line(lines[idx])
        upper = line.upper()
        if skip_re and skip_re.match(line):
            line = ""
        if upper in {"", "CONTENTS.", "TABLE OF CONTENTS.", "MARTIN LUTHER,", "ON THE", "BONDAGE OF THE WILL;"}:
            line = ""
        if re.fullmatch(r"[ivxlcdmIVXLCDM]{1,8}", line) or re.fullmatch(r"\d+", line):
            line = ""
        if not line:
            if current:
                block = " ".join(current)
                block = " ".join(block.split())
                if block:
                    blocks.append(decode_pg_inline_markup(block))
                current = []
            continue
        current.append(line)
    if current:
        block = " ".join(current)
        block = " ".join(block.split())
        if block:
            blocks.append(decode_pg_inline_markup(block))
    return blocks


def _find_line_matching(lines: list[str], pattern: re.Pattern, start: int = 0) -> int:
    for idx in range(start, len(lines)):
        if pattern.match(_normalise_luther_ocr_line(lines[idx])):
            return idx
    raise ValueError(f"Could not find Luther boundary matching {pattern.pattern!r}")


def _find_bondage_part_start(lines: list[str], part: str, start_at: int) -> int:
    title = _LUTHER_BONDAGE_PART_TITLE[part]
    compact_title = re.sub(r"\s+", " ", title.upper())
    for idx in range(start_at, len(lines)):
        raw_line = lines[idx]
        line = _normalise_luther_ocr_line(raw_line).upper()
        if line == compact_title or compact_title.startswith(line):
            for scan in range(idx - 1, max(-1, idx - 8), -1):
                candidate = _normalise_luther_ocr_line(lines[scan]).upper()
                if re.fullmatch(rf"PART {part}\.", candidate):
                    return scan
    raise ValueError(f"Could not find Bondage Part {part}")


def parse_luther_galatians(body_lines: list, log_lines: list) -> list:
    """Parse Luther's PG Galatians commentary into Preface, Introduction, and chapters."""
    lines = list(body_lines)
    events: list[tuple[int, str, str | None, str | None]] = []

    preface_idx = _find_line_matching(lines, re.compile(r"^PREFACE$"))
    intro_idx = _find_line_matching(lines, re.compile(r"^FROM LUTHER'S INTRODUCTION, 1538$"), preface_idx + 1)
    events.append((preface_idx, "preface", "Preface", None))
    events.append((intro_idx, "introduction", "From Luther's Introduction, 1538", None))

    for idx, line in enumerate(lines):
        match = _LUTHER_GALATIANS_CHAPTER_RE.match(_normalise_luther_ocr_line(line))
        if match:
            number = int(match.group(1))
            events.append((idx, "chapter", f"Chapter {number}", None))

    events.sort(key=lambda event: event[0])
    sections = []
    skip_re = re.compile(r"^(PREFACE|FROM LUTHER'S INTRODUCTION, 1538|CHAPTER [1-6])$")
    for event_idx, (start, section_type, label, title) in enumerate(events):
        stop = events[event_idx + 1][0] if event_idx + 1 < len(events) else len(lines)
        blocks = _luther_blocks(lines, start + 1, stop, skip_re=skip_re)
        sections.append(_make_leaf_section(section_type, label, title, blocks))
        log(f"  Luther Galatians {label}: {len(blocks)} blocks", log_lines)
    return sections


def parse_luther_bondage(body_lines: list, log_lines: list) -> list:
    """Parse the 1823 IA OCR Bondage text at stable top-level boundaries."""
    lines = list(body_lines)
    intro_idx = _find_line_matching(lines, re.compile(r"^INTRODUCTION\.$"), 4100)
    events: list[tuple[int, str, str | None, str | None]] = [
        (intro_idx, "introduction", "Introduction", "Reasons for the Work")
    ]
    for part in ("I", "II", "III", "IV", "V"):
        events.append((
            _find_bondage_part_start(lines, part, intro_idx + 1),
            "part",
            f"Part {part}",
            _LUTHER_BONDAGE_PART_TITLE[part].rstrip("."),
        ))
    conclusion_idx = _find_line_matching(lines, re.compile(r"^CONCLUSION\.$"), events[-1][0] + 1)
    events.append((conclusion_idx, "conclusion", "Conclusion", None))
    events.sort(key=lambda event: event[0])

    skip_re = re.compile(r"^(INTRODUCTION\.|PART [IVXLC]+\.|SECTION [IVXLC]+\.|CONCLUSION\.)$")
    sections = []
    for event_idx, (start, section_type, label, title) in enumerate(events):
        stop = events[event_idx + 1][0] if event_idx + 1 < len(events) else len(lines)
        blocks = _luther_blocks(lines, start + 1, stop, skip_re=skip_re)
        sections.append(_make_leaf_section(section_type, label, title, blocks))
        log(f"  Luther Bondage {label}: {len(blocks)} blocks", log_lines)
    return sections


def parse_luther_bondage_cole(body_lines: list, log_lines: list) -> list:
    """Parse the cached Covenanter transcription of Cole's 1823 translation."""
    groups: list[tuple[str, list[str]]] = []
    current_slug: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_slug, current_lines
        if current_slug is not None:
            groups.append((current_slug, current_lines))
        current_slug = None
        current_lines = []

    for line in body_lines:
        match = re.match(r"^=== PAGE ([^=]+) ===$", line.strip())
        if match:
            flush()
            current_slug = match.group(1).strip()
            continue
        if current_slug is None:
            continue
        if line.startswith("URL: ") or line.startswith("TITLE: "):
            continue
        current_lines.append(line)
    flush()

    sections = []
    for slug, lines in groups:
        if slug not in _LUTHER_BONDAGE_COLE_SECTIONS:
            continue
        section_type, label, title = _LUTHER_BONDAGE_COLE_SECTIONS[slug]
        blocks = _luther_blocks(lines, 0, len(lines))
        sections.append(_make_leaf_section(section_type, label, title, blocks))
        log(f"  Luther Bondage Cole {label}: {len(blocks)} blocks", log_lines)

    if len(sections) != len(_LUTHER_BONDAGE_COLE_SECTIONS):
        raise ValueError(
            f"Expected {len(_LUTHER_BONDAGE_COLE_SECTIONS)} Cole sections, got {len(sections)}"
        )
    return sections


# ---------------------------------------------------------------------------
# A. A. Hodge parser (IA, catechism_qa)
# ---------------------------------------------------------------------------

_HODGE_CHAPTER_RE = re.compile(r"^CHAPTER\s+([IVX]+)\b[.,\s]*(.*)$", re.IGNORECASE)
# Questions: line starts with digit(s), period, space, then text ending with ?
_HODGE_Q_RE = re.compile(r"^(\d+)\.\s+(.+\?)\s*$")


def _find_first_structural_line_hodge(lines: list) -> int:
    """Return index of first CHAPTER heading in A.A. Hodge text."""
    for i, line in enumerate(lines):
        if _HODGE_CHAPTER_RE.match(line.strip()):
            return i
    return 0


def parse_aa_hodge(body_lines: list, doc_id: str, log_lines: list) -> list:
    """Parse A. A. Hodge's Outlines of Theology into catechism_qa entries.

    Structure: CHAPTER headings group the Q&A entries.
    Each question line ("N. What...?") starts a new entry; following paragraphs are the answer.

    Returns list of catechism_qa entry dicts.
    """
    first_line = _find_first_structural_line_hodge(body_lines)
    lines = body_lines[first_line:]

    entries = []
    sort_key = 0
    current_chapter = "Chapter I"
    # Accumulate Q and A buffers
    current_q_num = None
    current_q_text = None
    answer_blocks = []

    def flush_entry() -> None:
        """Flush current Q&A pair into entries list."""
        nonlocal sort_key
        if current_q_num is None:
            return
        answer = " ".join(answer_blocks).strip() if answer_blocks else None
        answer = decode_pg_inline_markup(" ".join(answer.split())) if answer else None
        sort_key += 1
        entries.append({
            "document_id": doc_id,
            "item_id": str(sort_key),  # global; Hodge numbers reset per chapter
            "sort_key": sort_key,
            "group": current_chapter,
            "question": decode_pg_inline_markup(current_q_text),
            "answer": answer,
            "answer_with_proofs": None,
            "proofs": [],
            "sub_questions": None,
        })

    # Accumulate answer text across blank lines
    answer_accumulate = []

    for i, line in enumerate(lines):
        s = line.strip()

        # Chapter heading
        m = _HODGE_CHAPTER_RE.match(s)
        if m:
            flush_entry()
            current_q_num = None
            current_q_text = None
            answer_blocks = []
            answer_accumulate = []
            roman = m.group(1).upper()
            title_rest = m.group(2).strip().rstrip(".")
            current_chapter = f"Chapter {roman}"
            if title_rest:
                current_chapter = f"Chapter {roman}. {title_rest}"
            continue

        # Question line
        q_m = _HODGE_Q_RE.match(s)
        if q_m:
            flush_entry()
            current_q_num = int(q_m.group(1))
            current_q_text = q_m.group(2).strip()
            answer_blocks = []
            answer_accumulate = []
            continue

        # Blank line — flush accumulated answer lines as a paragraph
        if not s:
            if answer_accumulate and current_q_num is not None:
                para = " ".join(answer_accumulate)
                para = " ".join(para.split())
                if para:
                    answer_blocks.append(para)
                answer_accumulate = []
            continue

        # Non-blank non-heading line: part of the answer
        if current_q_num is not None:
            answer_accumulate.append(s)

    # Flush final paragraph and final entry
    if answer_accumulate and current_q_num is not None:
        para = " ".join(answer_accumulate)
        para = " ".join(para.split())
        if para:
            answer_blocks.append(para)
    flush_entry()

    log(f"  A.A. Hodge: {len(entries)} Q&A entries", log_lines)
    return entries


# ---------------------------------------------------------------------------
# Meta builders
# ---------------------------------------------------------------------------


def build_structured_text_meta(cfg: dict, source_hash: str) -> dict:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from build.lib.contributors import normalize_contributors  # noqa: E402
    source_type = cfg.get(
        "provenance_source_type",
        "gutenberg_txt" if cfg["source_type"] == "pg" else "ia_djvutxt",
    )
    return {
        "id": cfg["slug"],
        "title": cfg["title"],
        "author": cfg["author"],
        "author_id": cfg["author_id"],
        "author_birth_year": cfg["author_birth_year"],
        "author_death_year": cfg["author_death_year"],
        "contributors": normalize_contributors([]),
        "original_publication_year": cfg["pub_year"],
        "language": "en",
        "original_language": cfg["original_lang"],
        "tradition": cfg["tradition"],
        "tradition_notes": cfg["tradition_notes"],
        "era": cfg["era"],
        "audience": cfg["audience"],
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
        "provenance": {
            "source_url": "; ".join(source_urls(cfg)),
            "source_format": source_format(cfg),
            "source_edition": cfg["source_edition"],
            "download_date": local_now().strftime("%Y-%m-%d"),
            "source_hash": source_hash,
            "processing_method": processing_method(cfg),
            "processing_script_version": SCRIPT_VERSION,
            "processing_date": local_now().strftime("%Y-%m-%d"),
            "source_type": source_type,
            "source_file": "; ".join(str(path.relative_to(REPO_ROOT)).replace("\\", "/") for path in raw_paths(cfg)),
            "translator": cfg.get("translator") or (
                "John Keble (ed.), 1836" if cfg["slug"] == "hooker-ecclesiastical-polity" else None
            ),
            "notes": append_pg_inline_markup_note(cfg.get("processing_notes") or (
                "Project Gutenberg plain-text edition. PG header/footer stripped."
                if cfg["source_type"] == "pg"
                else "Internet Archive DjVuTXT OCR. Form-feeds replaced with blank lines. "
                     "Front matter skipped. Heading patterns matched via regex."
            )),
        },
    }


def build_catechism_qa_meta(cfg: dict, source_hash: str) -> dict:
    return {
        "id": cfg["slug"],
        "title": cfg["title"],
        "author": cfg["author"],
        "author_birth_year": cfg["author_birth_year"],
        "author_death_year": cfg["author_death_year"],
        "contributors": [],
        "original_publication_year": cfg["pub_year"],
        "language": "en",
        "original_language": cfg["original_lang"],
        "tradition": cfg["tradition"],
        "tradition_notes": cfg["tradition_notes"],
        "era": cfg["era"],
        "audience": cfg["audience"],
        "license": "public-domain",
        "schema_type": "catechism_qa",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
        "provenance": {
            "source_url": ia_djvutxt_url(cfg["ia_id"]),
            "source_format": "DjVuTXT (OCR)",
            "source_edition": cfg["source_edition"],
            "download_date": local_now().strftime("%Y-%m-%d"),
            "source_hash": source_hash,
            "processing_method": "ocr",
            "processing_script_version": SCRIPT_VERSION,
            "processing_date": local_now().strftime("%Y-%m-%d"),
            "notes": append_pg_inline_markup_note(
                "Internet Archive DjVuTXT OCR. Q&A format. Questions matched by numbered lines ending '?'."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Source config writers
# ---------------------------------------------------------------------------


def write_source_config(cfg: dict, source_hash: str) -> None:
    """Write a source config JSON for this work."""
    if cfg["work_kind"] == "catechism_qa":
        config_dir = REPO_ROOT / "sources" / "catechisms" / cfg["slug"]
        out_rel = f"data/catechisms/{cfg['slug']}.json"
    else:
        config_dir = REPO_ROOT / "sources" / "structured-text" / cfg["slug"]
        out_rel = f"data/structured-text/{cfg['slug']}.json"

    config_dir.mkdir(parents=True, exist_ok=True)
    source_type = cfg.get(
        "provenance_source_type",
        "gutenberg_txt" if cfg["source_type"] == "pg" else "ia_djvutxt",
    )
    config = {
        "resource_id": cfg["slug"],
        "title": cfg["title"],
        "author": cfg["author"],
        "author_id": cfg["author_id"],
        "author_birth_year": cfg["author_birth_year"],
        "author_death_year": cfg["author_death_year"],
        "contributors": [],
        "original_publication_year": cfg["pub_year"],
        "language": "en",
        "original_language": cfg["original_lang"],
        "tradition": cfg["tradition"],
        "era": cfg["era"],
        "audience": cfg["audience"],
        "license": "public-domain",
        "schema_type": "catechism_qa" if cfg["work_kind"] == "catechism_qa" else "structured_text",
        "work_kind": cfg["work_kind"],
        "source_url": "; ".join(source_urls(cfg)),
        "source_format": source_format(cfg),
        "source_edition": cfg["source_edition"],
        "source_hash": source_hash,
        "source_type": source_type,
        "source_file": "; ".join(str(path.relative_to(REPO_ROOT)).replace("\\", "/") for path in raw_paths(cfg)),
        "editor": "John Keble" if cfg["slug"] == "hooker-ecclesiastical-polity" else None,
        "editor_year": 1836 if cfg["slug"] == "hooker-ecclesiastical-polity" else None,
        "translator": cfg.get("translator"),
        "download_date": local_now().strftime("%Y-%m-%d"),
        "output_file": out_rel,
        "notes": append_pg_inline_markup_note(cfg.get("processing_notes") or (
            "Project Gutenberg public domain text. 10-second download delay honoured."
            if cfg["source_type"] == "pg"
            else "Internet Archive DjVuTXT OCR. Public domain (pre-1928 US publication)."
        )),
    }
    config_path = config_dir / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Work runner
# ---------------------------------------------------------------------------


def _hooker_body_lines_from_raw() -> list[str]:
    cfg = _WORK_BY_SLUG["hooker-ecclesiastical-polity"]
    text = "\n\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in raw_paths(cfg)
    )
    return prepare_ia_lines(text)


def write_hooker_locator_csv() -> Path:
    lines = _hooker_body_lines_from_raw()
    locators = _build_hooker_locator_table(lines)
    out_path = REPO_ROOT / "research" / "hooker-chapter-locators.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["book", "chapter", "line_idx", "matched_text", "locator_type", "confidence"],
        )
        writer.writeheader()
        for book_number, expected in _HOOKER_EXPECTED_CHAPTERS.items():
            for chapter_number in range(1, expected + 1):
                locator = locators[(book_number, chapter_number)]
                writer.writerow({
                    "book": book_number,
                    "chapter": chapter_number,
                    "line_idx": locator["line_idx"],
                    "matched_text": locator["matched_text"],
                    "locator_type": locator["locator_type"],
                    "confidence": locator["confidence"],
                })
    return out_path


def run_work(cfg: dict, dry_run: bool, log_lines: list) -> bool:
    """Parse and (optionally) write one work. Returns True on success."""
    slug = cfg["slug"]
    log(f"\n--- {slug} ---", log_lines)

    try:
        assert_evidence_for_synthetic_boundaries(cfg)
    except ValueError as exc:
        log(f"  ERROR config: {exc}", log_lines)
        return False

    paths = raw_paths(cfg)
    missing = [path for path in paths if not path.exists()]
    if missing:
        log(f"  ERROR: missing raw files -- run with --download first: {', '.join(str(p) for p in missing)}", log_lines)
        return False

    if len(paths) == 1:
        source_hash = compute_source_hash(paths[0])
    else:
        digest = hashlib.sha256()
        for path in paths:
            digest.update(compute_source_hash(path).encode("utf-8"))
        source_hash = f"sha256:{digest.hexdigest()}"
    log(f"  Source: {', '.join(path.name for path in paths)} ({source_hash[:20]}...)", log_lines)

    text = "\n\n".join(path.read_text(encoding="utf-8", errors="replace") for path in paths)
    try:
        assert_source_evidence(cfg, text)
    except ValueError as exc:
        log(f"  ERROR checking source evidence: {exc}", log_lines)
        return False

    # Prepare body lines
    try:
        if cfg["source_type"] == "pg":
            body_lines = strip_pg_wrapper(text)
        elif cfg["source_type"] == "web":
            body_lines = text.splitlines()
        else:
            body_lines = prepare_ia_lines(text)
    except ValueError as exc:
        log(f"  ERROR preparing body lines: {exc}", log_lines)
        return False
    log(f"  Body lines: {len(body_lines)}", log_lines)

    # Dispatch to per-work parser
    is_catechism = cfg["work_kind"] == "catechism_qa"

    try:
        if slug.startswith("strong-"):
            sections = parse_strong(body_lines, log_lines)
            data = {"work_id": slug, "work_kind": "systematic-theology", "sections": sections}
        elif slug.startswith("dabney-"):
            sections = parse_dabney(body_lines, log_lines)
            data = {"work_id": slug, "work_kind": "systematic-theology", "sections": sections}
        elif slug.startswith("shedd-"):
            sections = parse_shedd(body_lines, log_lines, slug)
            data = {"work_id": slug, "work_kind": "systematic-theology", "sections": sections}
        elif slug.startswith("miley-"):
            sections = parse_miley(body_lines, log_lines)
            data = {"work_id": slug, "work_kind": "systematic-theology", "sections": sections}
        elif slug == "aa-hodge-outlines":
            entries = parse_aa_hodge(body_lines, slug, log_lines)
            data = entries  # flat list for catechism_qa
        elif slug == "hooker-ecclesiastical-polity":
            sections = parse_hooker(body_lines, log_lines)
            data = {"work_id": slug, "work_kind": "treatise", "sections": sections}
        elif slug == "luther-bondage-of-the-will":
            sections = parse_luther_bondage_cole(body_lines, log_lines)
            data = {"work_id": slug, "work_kind": "treatise", "sections": sections}
        elif slug == "luther-commentary-on-galatians":
            sections = parse_luther_galatians(body_lines, log_lines)
            data = {"work_id": slug, "work_kind": "treatise", "sections": sections}
        else:
            log(f"  ERROR: no parser for slug '{slug}'", log_lines)
            return False
    except Exception as exc:
        log(f"  ERROR parsing {slug}: {exc}", log_lines)
        log(traceback.format_exc(), log_lines)
        return False

    # Quality stats
    if not is_catechism:
        print_quality_stats(data.get("sections", []), slug, log_lines)
        section_count = sum(
            1 for _ in _iter_sections(data.get("sections", []))
        )
        log(f"  Total sections (all levels): {section_count}", log_lines)
        if section_count == 0:
            log(f"  ERROR: 0 sections produced -- skipping write", log_lines)
            return False
    else:
        log(f"  catechism_qa entries: {len(data)}", log_lines)
        if not data:
            log(f"  ERROR: 0 entries produced -- skipping write", log_lines)
            return False

    if dry_run:
        log(f"  DRY RUN -- no files written", log_lines)
        return True

    # Build output
    if is_catechism:
        meta = build_catechism_qa_meta(cfg, source_hash)
        output = {"meta": meta, "data": data}
        OUTPUT_DIR_CAT.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR_CAT / f"{slug}.json"
    else:
        meta = build_structured_text_meta(cfg, source_hash)
        output = {"meta": meta, "data": data}
        OUTPUT_DIR_ST.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR_ST / f"{slug}.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log(f"  Written: {out_path}", log_lines)

    # Source config
    write_source_config(cfg, source_hash)
    log(f"  Source config written", log_lines)

    return True


def _iter_sections(sections: list):
    """Flatten all sections recursively."""
    for sec in sections:
        yield sec
        yield from _iter_sections(sec.get("children", []))


# ---------------------------------------------------------------------------
# Log helper
# ---------------------------------------------------------------------------


def log(message: str, log_lines: list) -> None:
    """Print to console (ASCII-safe) and append to log buffer."""
    safe = message.encode("ascii", errors="replace").decode("ascii")
    print(safe)
    log_lines.append(message)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse 19th-century systematic theology texts to OCD JSON"
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse without writing files")
    parser.add_argument("--download", action="store_true", help="Download raw source files")
    parser.add_argument("--parse", action="store_true", help="Parse and write output files")
    parser.add_argument("--locators", action="store_true", help="Write Hooker chapter locator CSV")
    parser.add_argument("--all", action="store_true", help="Process all works")
    parser.add_argument(
        "--work",
        metavar="SLUG",
        help="Process one work by slug (e.g. strong-systematic-theology-vol-1)",
    )
    args = parser.parse_args()

    if args.locators:
        out_path = write_hooker_locator_csv()
        print(f"Hooker locators written: {out_path}")
        if not (args.download or args.parse or args.dry_run):
            return

    # Determine what to do: explicit flags win; no flags = download + parse
    any_explicit = args.download or args.parse or args.dry_run or args.locators
    do_download = args.download or not any_explicit
    do_parse = args.parse or args.dry_run or not any_explicit

    log_lines: list = []
    start_time = time.time()
    run_ts = local_now().strftime("%Y-%m-%d %H:%M:%S")
    log(f"[{run_ts}] gutenberg_systematics -- "
        f"{'DRY RUN' if args.dry_run else 'LIVE RUN'}", log_lines)

    # Determine works to process
    if args.work:
        if args.work not in _WORK_BY_SLUG:
            valid = ", ".join(_WORK_BY_SLUG.keys())
            log(f"ERROR: unknown work '{args.work}'. Valid slugs: {valid}", log_lines)
            sys.exit(1)
        works = [_WORK_BY_SLUG[args.work]]
    else:
        works = list(WORK_CONFIG)

    log(f"Works: {', '.join(w['slug'] for w in works)}", log_lines)

    successes = 0
    failures = 0

    total = len(works)
    for work_num, cfg in enumerate(works, 1):
        slug = cfg["slug"]
        log(f"\n[Work {work_num}/{total}] {slug}", log_lines)
        ok = True

        if do_download:
            ok = download_work(cfg, log_lines)
            if not ok:
                failures += 1
                continue

        if do_parse and ok:
            ok = run_work(cfg, args.dry_run, log_lines)

        if ok:
            successes += 1
        else:
            failures += 1

    elapsed = time.time() - start_time
    summary = f"\nDone -- {successes} succeeded, {failures} failed, {elapsed:.1f}s"
    log(summary, log_lines)

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n\n")

    if failures > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
