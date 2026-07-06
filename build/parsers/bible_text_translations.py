"""bible_text_translations.py
Parse public-domain Bible translations from the scrollmapper bible_databases
JSON (same shape as BSB.json) into OCD bible_text schema files -- one JSON per
book, under data/bible-text/<translation>/.

The book-name/OSIS maps and verse-processing logic are shared with
bsb_bible_text.py (the scrollmapper translations use identical book names, e.g.
"I Samuel", "Revelation of John"). Only public-domain translations belong in
the TRANSLATIONS registry -- copyrighted versions must not be added.

Usage:
    py -3 build/parsers/bible_text_translations.py --translation kjv --dry-run
    py -3 build/parsers/bible_text_translations.py --translation kjv
    py -3 build/parsers/bible_text_translations.py --translation asv --book Gen
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.paths import REPO_ROOT  # noqa: E402
# Reuse the proven BSB maps + helpers (scrollmapper translations share book names).
from build.parsers.bsb_bible_text import (  # noqa: E402
    BSB_NAME_TO_OSIS as NAME_TO_OSIS,
    OSIS_BOOK_NUMBER,
    OSIS_TO_NAME,
    sha256_file,
)

log = logging.getLogger("bible_text_translations")

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"

JSON_DIR = REPO_ROOT / "raw" / "bible_databases" / "formats" / "json"
SOURCE_REPO = "https://github.com/scrollmapper/bible_databases"
MARKUP_RE = re.compile(r"\{[HG]?\d+\}|<[^>]+>")
COLLAPSED_GOD_RE = re.compile(r"(?<=[A-Za-z,.;:])God\b")
COLLAPSED_GOD_POSSESSIVE_RE = re.compile(r"\b(God[’']s)(?=[A-Za-z])")

APOCRYPHA_NAME_TO_OSIS = {
    "I Esdras": "1Esd",
    "II Esdras": "2Esd",
    "Tobit": "Tob",
    "Judith": "Jdt",
    "Additions to Esther": "AddEsth",
    "Wisdom": "Wis",
    "Sirach": "Sir",
    "Baruch": "Bar",
    "Prayer of Azariah": "PrAzar",
    "Susanna": "Sus",
    "Bel and the Dragon": "Bel",
    "Prayer of Manasses": "PrMan",
    "I Maccabees": "1Macc",
    "II Maccabees": "2Macc",
    "Additional Psalm": "AddPs",
    "Laodiceans": "EpLao",
}

APOCRYPHA_OSIS_TO_NAME = {
    "1Esd": "1 Esdras",
    "2Esd": "2 Esdras",
    "Tob": "Tobit",
    "Jdt": "Judith",
    "AddEsth": "Additions to Esther",
    "Wis": "Wisdom",
    "Sir": "Sirach",
    "Bar": "Baruch",
    "PrAzar": "Prayer of Azariah",
    "Sus": "Susanna",
    "Bel": "Bel and the Dragon",
    "PrMan": "Prayer of Manasses",
    "1Macc": "1 Maccabees",
    "2Macc": "2 Maccabees",
    "AddPs": "Additional Psalm",
    "EpLao": "Laodiceans",
}

NAME_TO_OSIS = {**NAME_TO_OSIS, **APOCRYPHA_NAME_TO_OSIS}
OSIS_TO_NAME = {**OSIS_TO_NAME, **APOCRYPHA_OSIS_TO_NAME}
OSIS_BOOK_NUMBER = {
    **OSIS_BOOK_NUMBER,
    "1Esd": 67,
    "2Esd": 68,
    "Tob": 69,
    "Jdt": 70,
    "AddEsth": 71,
    "Wis": 72,
    "Sir": 73,
    "Bar": 74,
    "PrAzar": 75,
    "Sus": 76,
    "Bel": 77,
    "PrMan": 78,
    "1Macc": 79,
    "2Macc": 80,
    "AddPs": 81,
    "EpLao": 82,
}


def book_slug(osis_code: str) -> str:
    """Return the output filename stem for a given OSIS code."""
    return OSIS_TO_NAME.get(osis_code, osis_code).lower().replace(" ", "-")


# Registry of public-domain translations. license MUST be "public-domain".
TRANSLATIONS: dict[str, dict] = {
    "kjv": {
        "source_file": "KJV.json",
        "resource_id": "kjv",
        "title": "King James Version",
        "license": "public-domain",
        "tradition": ["anglican"],
        "tradition_notes": (
            "The Authorized (King James) Version, commissioned by King James I "
            "for the Church of England and first published in 1611; the 1769 "
            "Blayney standardized text is the basis of this edition. Long the "
            "standard English Bible across Protestant traditions."
        ),
        "original_publication_year": 1611,
        "source_edition": (
            "King James Version, 1769 Blayney standard text (original 1611); "
            "public domain. Verse text from the scrollmapper bible_databases "
            "KJV dataset (Strong's/morphology data not ingested)."
        ),
        "notes": "Public domain. Book names normalized from source to canonical OSIS names.",
    },
    "asv": {
        "source_file": "ASV.json",
        "resource_id": "asv",
        "title": "American Standard Version",
        "license": "public-domain",
        "tradition": ["ecumenical"],
        "tradition_notes": (
            "The American Standard Version was published in 1901 by the American Revision "
            "Committee as an English revision in the King James tradition."
        ),
        "original_publication_year": 1901,
        "source_edition": (
            "American Standard Version (1901); public domain. Verse text from the "
            "scrollmapper bible_databases ASV dataset."
        ),
        "notes": "Public domain. Source metadata: ASV: American Standard Version (1901).",
    },
    "ylt": {
        "source_file": "YLT.json",
        "resource_id": "ylt",
        "title": "Young's Literal Translation",
        "license": "public-domain",
        "tradition": ["presbyterian"],
        "tradition_notes": (
            "Robert Young's Literal Translation was published in 1898 and reflects a "
            "literal English rendering by the Scottish publisher and biblical scholar."
        ),
        "original_publication_year": 1898,
        "source_edition": (
            "Young's Literal Translation (1898); public domain. Verse text from the "
            "scrollmapper bible_databases YLT dataset."
        ),
        "notes": "Public domain. Source metadata: YLT: Young's Literal Translation (1898).",
    },
    "darby": {
        "source_file": "Darby.json",
        "resource_id": "darby",
        "title": "Darby Bible",
        "license": "public-domain",
        "tradition": ["brethren"],
        "tradition_notes": (
            "John Nelson Darby's English Bible translation was published in the 19th "
            "century and is associated with the Plymouth Brethren tradition."
        ),
        "original_publication_year": 1889,
        "source_edition": (
            "Darby Bible (1889); public domain. Verse text from the scrollmapper "
            "bible_databases Darby dataset."
        ),
        "notes": "Public domain. Source metadata: Darby: Darby Bible (1889).",
    },
    "webster": {
        "source_file": "Webster.json",
        "resource_id": "webster",
        "title": "Webster Bible",
        "license": "public-domain",
        "tradition": ["ecumenical"],
        "tradition_notes": (
            "Noah Webster's revision of the King James Bible was first published in 1833."
        ),
        "original_publication_year": 1833,
        "source_edition": (
            "Webster Bible (1833); public domain. Verse text from the scrollmapper "
            "bible_databases Webster dataset."
        ),
        "notes": "Public domain. Source metadata: Webster: Webster Bible.",
    },
    "kjva": {
        "source_file": "KJVA.json",
        "resource_id": "kjva",
        "title": "King James Version with Apocrypha",
        "license": "public-domain",
        "tradition": ["anglican"],
        "tradition_notes": (
            "The King James Version with Apocrypha follows the 1769 KJV text and includes "
            "the apocryphal books preserved in the source dataset."
        ),
        "original_publication_year": 1611,
        "source_edition": (
            "King James Version (1769) with Apocrypha; public domain. Verse text from the "
            "scrollmapper bible_databases KJVA dataset."
        ),
        "notes": "Public domain. Source metadata: KJVA: King James Version (1769) with Apocrypha.",
    },
    "jps": {
        "source_file": "JPS.json",
        "resource_id": "jps",
        "title": "Jewish Publication Society Old Testament",
        "license": "public-domain",
        "tradition": ["ecumenical"],
        "tradition_notes": (
            "The Jewish Publication Society 1917 Tanakh is an English Jewish translation "
            "of the Hebrew Bible."
        ),
        "original_publication_year": 1917,
        "source_edition": (
            "Jewish Publication Society Old Testament (1917); public domain. Verse text "
            "from the scrollmapper bible_databases JPS dataset."
        ),
        "notes": "Public domain. Source metadata: JPS: Jewish Publication Society Old Testament.",
    },
    "drc": {
        "source_file": "DRC.json",
        "resource_id": "drc",
        "title": "Douay-Rheims Bible, Challoner Revision",
        "license": "public-domain",
        "tradition": ["catholic"],
        "tradition_notes": (
            "The Douay-Rheims Bible in the Challoner revision is a Catholic English Bible "
            "traditionally printed with deuterocanonical books."
        ),
        "original_publication_year": 1752,
        "source_edition": (
            "Douay-Rheims Bible, Challoner Revision; public domain. Verse text from the "
            "scrollmapper bible_databases DRC dataset."
        ),
        "notes": "Public domain. Source metadata: DRC: Douay-Rheims Bible, Challoner Revision.",
    },
}


def source_path(tid: str) -> Path:
    return JSON_DIR / TRANSLATIONS[tid]["source_file"]


def output_dir(tid: str) -> Path:
    return REPO_ROOT / "data" / "bible-text" / tid


def load_translation_books(tid: str) -> list:
    return load_source_payload(tid)["books"]


def load_source_payload(tid: str) -> dict:
    path = source_path(tid)
    if not path.exists():
        raise FileNotFoundError(f"{tid} source not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_verse_entries(book_data: dict, osis_code: str) -> list[dict]:
    """Pure verse extraction for one book -> list of bible_text data entries.

    Empty-text verses (textual-critical omissions present in some versifications)
    are skipped, matching bsb_bible_text behaviour.
    """
    entries: list[dict] = []
    for ch_data in book_data.get("chapters", []):
        ch_num = ch_data["chapter"]
        for v_data in ch_data.get("verses", []):
            text = normalize_verse_text(v_data.get("text") or "")
            if not text:
                continue
            entries.append({
                "osis": f"{osis_code}.{ch_num}.{v_data['verse']}",
                "chapter": ch_num,
                "verse": v_data["verse"],
                "text": text,
                "word_count": len(text.split()),
            })
    return entries


def normalize_verse_text(text: str) -> str:
    """Strip scrollmapper inline markers that do not belong in OCD verse text."""
    text = MARKUP_RE.sub("", text)
    text = COLLAPSED_GOD_RE.sub(" God", text)
    text = COLLAPSED_GOD_POSSESSIVE_RE.sub(r"\1 ", text)
    return " ".join(text.split())


def build_meta(tid: str, osis_code: str, today: str, source_hash: str) -> dict:
    cfg = TRANSLATIONS[tid]
    return {
        "id": cfg["resource_id"],
        "title": cfg["title"],
        "language": "en",
        "original_language": "en",
        "tradition": cfg["tradition"],
        "tradition_notes": cfg["tradition_notes"],
        "license": "public-domain",
        "schema_type": "bible_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
        "provenance": {
            "source_url": SOURCE_REPO,
            "source_format": "JSON",
            "source_edition": cfg["source_edition"],
            "download_date": today,
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": f"build/parsers/bible_text_translations.py@{SCRIPT_VERSION}",
            "processing_date": today,
            "notes": cfg.get("notes"),
        },
        "scope": {
            "book": OSIS_TO_NAME.get(osis_code, osis_code),
            "book_osis": osis_code,
            "book_number": OSIS_BOOK_NUMBER[osis_code],
        },
    }


def write_source_config(tid: str, source_hash: str) -> Path:
    cfg = TRANSLATIONS[tid]
    config_dir = REPO_ROOT / "sources" / "bible-text" / tid
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"
    config = {
        "resource_id": cfg["resource_id"],
        "title": cfg["title"],
        "language": "en",
        "tradition": cfg["tradition"],
        "tradition_notes": cfg["tradition_notes"],
        "license": "public-domain",
        "original_publication_year": cfg["original_publication_year"],
        "source_url": SOURCE_REPO,
        "source_format": "JSON",
        "source_file": f"raw/bible_databases/formats/json/{cfg['source_file']}",
        "source_edition": cfg["source_edition"],
        "source_repository": SOURCE_REPO,
        "notes": cfg.get("notes"),
    }
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return config_path


def parse_translation(tid: str, only_osis: str | None = None, dry_run: bool = False) -> dict:
    """Parse one translation into per-book bible_text files. Returns a summary."""
    if tid not in TRANSLATIONS:
        raise ValueError(f"Unknown translation {tid!r}; known: {sorted(TRANSLATIONS)}")

    src = source_path(tid)
    source_hash = sha256_file(src)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    books = load_translation_books(tid)
    out_dir = output_dir(tid)

    total_verses = 0
    books_written = 0
    books_seen = 0
    for book_data in books:
        osis = NAME_TO_OSIS.get(book_data["name"])
        if osis is None:
            raise RuntimeError(f"{tid}: unmapped book name {book_data['name']!r}")
        if only_osis and osis != only_osis:
            continue
        entries = build_verse_entries(book_data, osis)
        if not entries:
            log.info("  [%s] %s %s: 0 verses; skipped empty source book",
                     "dry-run" if dry_run else "write", tid, osis)
            continue
        books_seen += 1
        total_verses += len(entries)
        if dry_run:
            log.info("  [dry-run] %s %s: %d verses", tid, osis, len(entries))
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        envelope = {"meta": build_meta(tid, osis, today, source_hash), "data": entries}
        out_file = out_dir / f"{book_slug(osis)}.json"
        tmp = out_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(out_file)
        books_written += 1

    if not dry_run and not only_osis:
        write_source_config(tid, source_hash)

    log.info("  %s: %d verses across %d books (%s)",
             tid, total_verses, books_written if not dry_run else books_seen,
             "dry-run" if dry_run else "written")
    return {"translation": tid, "total_verses": total_verses, "books_written": books_written}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--translation", required=True, choices=sorted(TRANSLATIONS),
                        help="Translation id to parse.")
    parser.add_argument("--book", metavar="OSIS", help="Single book OSIS code (e.g. Gen).")
    parser.add_argument("--dry-run", action="store_true", help="Parse but do not write.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = parse_translation(args.translation, only_osis=args.book, dry_run=args.dry_run)
    print(f"Done: {args.translation} -> {result['total_verses']} verses, "
          f"{result['books_written']} books written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
