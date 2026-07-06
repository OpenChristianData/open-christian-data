"""Parser for Philip Schaff, *The Creeds of Christendom*, Vol. I: The History
of Creeds (CCEL ThML), into one OCD ``structured_text`` JSON file.

Schaff's Vol. I is a prose history of the creeds organised as div1 (chapter) >
div2 (section) > div3 (subsection). This parser recurses all three levels into
the structured_text section tree, skipping front/back matter (Title Page,
Prefatory, Indexes) and footnotes (<note>, excluded by get_all_text).

ThML preprocessing, text extraction, and scripture-ref helpers are reused from
ccel_schaff_hcc (same author, same CCEL ThML conventions) to keep behaviour
consistent across the two Schaff parsers.

Usage:
    py -3 build/parsers/ccel_creeds_of_christendom.py --dry-run
    py -3 build/parsers/ccel_creeds_of_christendom.py --parse
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.contributors import normalize_contributors  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402
# Reuse the stable ThML machinery from the sibling Schaff parser.
from build.parsers.ccel_schaff_hcc import (  # noqa: E402
    _DIV_TAG_RE,
    _HEADING_TAGS,
    _SKIP_TAGS,
    clean_text,
    count_words,
    get_all_text,
    get_scriptrefs,
    preprocess_thml,
)

log = logging.getLogger("ccel_creeds_of_christendom")

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"
WORK_KIND = "church-history"

RAW_FILE = REPO_ROOT / "raw" / "ccel" / "schaff" / "creeds1.xml"
OUTPUT_DIR = REPO_ROOT / "data" / "structured-text"
OUTPUT_FILE = OUTPUT_DIR / "creeds-of-christendom-vol-1.json"
SOURCE_URL = "https://www.ccel.org/ccel/schaff/creeds1.xml"

WORK_ID = "creeds-of-christendom-vol-1"

WORK_META = {
    "title": "The Creeds of Christendom, Vol. I: The History of Creeds",
    "author": "Philip Schaff",
    "author_birth_year": 1819,
    "author_death_year": 1893,
    "contributors": ["Christian Classics Ethereal Library (digital edition)"],
    "original_publication_year": 1877,
    "language": "en",
    "original_language": "en",
    "tradition": ["ecumenical"],
    "tradition_notes": (
        "Schaff was a Swiss-American Reformed theologian and church historian. "
        "Volume I surveys the creeds and confessions of all major Christian "
        "traditions -- Greek, Roman, Lutheran, Reformed, and modern evangelical "
        "-- and is the standard 19th-century English reference on the subject."
    ),
    "era": "modern",
    "audience": "scholarly",
    "license": "public-domain",
    "completeness": "full",
}

# div1 content chapters are titled "Chapter N. ..."; front/back matter (Title
# Page, Prefatory, Index to Volume I, Indexes) is everything else.
_CHAPTER_DIV1_RE = re.compile(r"^\s*Chapter\s", re.IGNORECASE)
_CHAPTER_PREFIX_RE = re.compile(r"^\s*(Chapter\s+\w+)\.?\s*(.*)$", re.IGNORECASE)

_SECTION_TYPE_BY_DEPTH = {0: "chapter", 1: "section", 2: "subsection"}


def _label_title(div: ET.Element, depth: int) -> tuple[str | None, str | None]:
    """Derive (label, title) for a div at the given nesting depth."""
    n = div.get("n", "")
    title_attr = clean_text(div.get("title", ""))

    if depth == 0:
        m = _CHAPTER_PREFIX_RE.match(title_attr)
        if m:
            rest = m.group(2).strip().rstrip(".").strip()
            return m.group(1), (rest or None)
        label = f"Chapter {n}" if n else None
        return label, (title_attr or None)

    label = f"§ {n}" if n else None
    return label, (title_attr or None)


def parse_div(div: ET.Element, depth: int) -> dict | None:
    """Recursively parse a div element into a structured_text section dict.

    Own paragraphs (<p>/<q>/<argument>/lists) become content_blocks; nested divs
    become children one level deeper. Returns None when the div has neither.
    """
    section_type = _SECTION_TYPE_BY_DEPTH.get(depth, "subsection")
    label, title = _label_title(div, depth)

    content_blocks: list[str] = []
    children: list[dict] = []
    for child in div:
        if _DIV_TAG_RE.match(child.tag):
            sub = parse_div(child, depth + 1)
            if sub is not None:
                children.append(sub)
            continue
        if child.tag in _SKIP_TAGS or child.tag in _HEADING_TAGS:
            continue
        if child.tag in ("p", "argument", "q"):
            text = clean_text(get_all_text(child))
            if text:
                content_blocks.append(text)
        elif child.tag in ("ul", "ol"):
            items = [
                clean_text(get_all_text(li))
                for li in child.findall("li")
                if clean_text(get_all_text(li))
            ]
            if items:
                content_blocks.append("; ".join(items))

    if not content_blocks and not children:
        return None

    own_wc = count_words(content_blocks)
    total_wc = own_wc + sum(c["word_count"] for c in children)
    return {
        "section_type": section_type,
        "label": label,
        "title": title,
        "content_blocks": content_blocks,
        "scripture_references": get_scriptrefs(div),
        "word_count": total_wc,
        "children": children,
    }


def parse_creeds_volume(dry_run: bool = False) -> dict:
    """Parse creeds1.xml into a structured_text data dict (8 content chapters)."""
    if not RAW_FILE.exists():
        raise FileNotFoundError(f"missing source: {RAW_FILE}")

    raw_bytes = RAW_FILE.read_bytes()
    source_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    root = ET.fromstring(preprocess_thml(raw_bytes))

    body = root.find("ThML.body")
    if body is None:
        raise RuntimeError("No <ThML.body> in creeds1.xml")

    sections: list[dict] = []
    for div1 in body:
        if not _DIV_TAG_RE.match(div1.tag):
            continue
        title_attr = clean_text(div1.get("title", ""))
        if not _CHAPTER_DIV1_RE.match(title_attr):
            continue  # skip Title Page / Prefatory / Index div1s
        ch = parse_div(div1, depth=0)
        if ch is not None:
            sections.append(ch)
        if dry_run and len(sections) >= 2:
            break

    if not sections:
        raise RuntimeError("No content chapters found in creeds1.xml")

    return {
        "work_id": WORK_ID,
        "work_kind": WORK_KIND,
        "sections": sections,
        "_source_hash": source_hash,
    }


def build_meta(source_hash: str) -> dict:
    process_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    download_date = process_date
    if RAW_FILE.exists():
        mtime = RAW_FILE.stat().st_mtime
        download_date = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")

    return {
        "id": WORK_ID,
        "title": WORK_META["title"],
        "author": WORK_META["author"],
        "author_birth_year": WORK_META["author_birth_year"],
        "author_death_year": WORK_META["author_death_year"],
        "contributors": normalize_contributors(WORK_META["contributors"]),
        "original_publication_year": WORK_META["original_publication_year"],
        "language": WORK_META["language"],
        "original_language": WORK_META["original_language"],
        "tradition": WORK_META["tradition"],
        "tradition_notes": WORK_META["tradition_notes"],
        "era": WORK_META["era"],
        "audience": WORK_META["audience"],
        "license": WORK_META["license"],
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": WORK_META["completeness"],
        "provenance": {
            "source_url": SOURCE_URL,
            "source_format": "ThML XML",
            "source_edition": (
                "Christian Classics Ethereal Library (CCEL) ThML edition. "
                "Original edition: Philip Schaff, The Creeds of Christendom, "
                "Vol. I, New York: Harper & Brothers, 1877 (rev. David S. Schaff)."
            ),
            "download_date": download_date,
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/ccel_creeds_of_christendom.py@{SCRIPT_VERSION}"
            ),
            "processing_date": process_date,
            "notes": (
                "ThML HTML entities replaced with Unicode equivalents; DOCTYPE "
                "stripped before parsing. Footnotes (<note>) and page breaks "
                "(<pb>) excluded from content. Front/back matter (Title Page, "
                "Prefatory, Indexes) excluded; only the eight history chapters "
                "(div1) are ingested, recursed div1>div2>div3."
            ),
        },
    }


def _report_quality(data: dict) -> None:
    chapters = data["sections"]

    def _walk(secs):
        for s in secs:
            yield s
            yield from _walk(s.get("children", []))

    all_secs = list(_walk(chapters))
    total_words = sum(ch["word_count"] for ch in chapters)
    wcs = [s["word_count"] for s in all_secs if s["word_count"] > 0]
    log.info("  %d chapters, %d total sections, %d words", len(chapters), len(all_secs), total_words)
    if wcs:
        log.info("  section wc min/med/max: %d/%d/%d", min(wcs), sorted(wcs)[len(wcs) // 2], max(wcs))
    empty = sum(1 for s in all_secs if not s["content_blocks"])
    if empty:
        log.info("  %d sections with no own content_blocks (container-only)", empty)


def write_source_config(source_hash: str) -> Path:
    config_dir = REPO_ROOT / "sources" / "structured-text" / WORK_ID
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"
    config = {
        "resource_id": WORK_ID,
        "title": WORK_META["title"],
        "author": WORK_META["author"],
        "author_birth_year": WORK_META["author_birth_year"],
        "author_death_year": WORK_META["author_death_year"],
        "contributors": normalize_contributors(WORK_META["contributors"]),
        "original_publication_year": WORK_META["original_publication_year"],
        "language": WORK_META["language"],
        "original_language": WORK_META["original_language"],
        "tradition": WORK_META["tradition"],
        "era": WORK_META["era"],
        "audience": WORK_META["audience"],
        "license": WORK_META["license"],
        "schema_type": "structured_text",
        "work_kind": WORK_KIND,
        "source_url": SOURCE_URL,
        "source_format": "ThML XML",
        "source_edition": (
            "Christian Classics Ethereal Library (CCEL) ThML edition; "
            "original New York: Harper & Brothers, 1877."
        ),
        "source_hash": source_hash,
    }
    config_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return config_path


def write_output(data: dict) -> None:
    source_hash = data.pop("_source_hash")
    meta = build_meta(source_hash)
    envelope = {"meta": meta, "data": data}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(OUTPUT_FILE)

    # PIPE-19: verify written tree matches in-memory.
    reread = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    assert len(reread["data"]["sections"]) == len(data["sections"]), "write verification failed"
    log.info("  wrote %s (%d chapters)", OUTPUT_FILE, len(data["sections"]))
    write_source_config(source_hash)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Parse 2 chapters, do not write.")
    parser.add_argument("--parse", action="store_true", help="Parse and write the output file.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    data = parse_creeds_volume(dry_run=args.dry_run)
    _report_quality(data)

    if args.dry_run or not args.parse:
        print(f"Parsed {len(data['sections'])} chapters (dry-run; no file written).")
        return 0

    write_output(data)
    print(f"Done: {len(data['sections'])} chapters -> {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
