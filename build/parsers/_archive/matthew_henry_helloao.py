"""matthew_henry_helloao.py
Fetch Matthew Henry commentary from HelloAO Bible API and map to our commentary schema.
Also fetches BSB verse text from HelloAO for verse injection in the same pass.

Usage:
    py -3 build/parsers/matthew_henry_helloao.py --book EZK
    py -3 build/parsers/matthew_henry_helloao.py --book EZK --dry-run
    py -3 build/parsers/matthew_henry_helloao.py --all-books
    py -3 build/parsers/matthew_henry_helloao.py --all-books --local
    py -3 build/parsers/matthew_henry_helloao.py --book EZK --local
"""

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "commentaries" / "matthew-henry"
SOURCES_DIR = REPO_ROOT / "sources" / "commentaries" / "matthew-henry"
CONFIG_FILE = SOURCES_DIR / "config.json"
LOCAL_RAW_DIR = REPO_ROOT / "raw" / "helloao_local" / "api"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HELLOAO_BASE = "https://bible.helloao.org/api"
COMMENTARY_ID = "matthew-henry"
BSB_ID = "BSB"
RESOURCE_ID = "matthew-henry-complete"
SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.1.0"
USER_AGENT = "open-christian-data/1.0 (+https://github.com/openchristiandata)"
REQUEST_DELAY = 0.4  # seconds between API calls

# ---------------------------------------------------------------------------
# Book code mappings
# ---------------------------------------------------------------------------

USFM_TO_OSIS = {
    "GEN": "Gen", "EXO": "Exod", "LEV": "Lev", "NUM": "Num", "DEU": "Deut",
    "JOS": "Josh", "JDG": "Judg", "RUT": "Ruth", "1SA": "1Sam", "2SA": "2Sam",
    "1KI": "1Kgs", "2KI": "2Kgs", "1CH": "1Chr", "2CH": "2Chr", "EZR": "Ezra",
    "NEH": "Neh", "EST": "Esth", "JOB": "Job", "PSA": "Ps", "PRO": "Prov",
    "ECC": "Eccl", "SNG": "Song", "ISA": "Isa", "JER": "Jer", "LAM": "Lam",
    "EZK": "Ezek", "DAN": "Dan", "HOS": "Hos", "JOL": "Joel", "AMO": "Amos",
    "OBA": "Obad", "JON": "Jonah", "MIC": "Mic", "NAM": "Nah", "HAB": "Hab",
    "ZEP": "Zeph", "HAG": "Hag", "ZEC": "Zech", "MAL": "Mal",
    "MAT": "Matt", "MRK": "Mark", "LUK": "Luke", "JHN": "John", "ACT": "Acts",
    "ROM": "Rom", "1CO": "1Cor", "2CO": "2Cor", "GAL": "Gal", "EPH": "Eph",
    "PHP": "Phil", "COL": "Col", "1TH": "1Thess", "2TH": "2Thess",
    "1TI": "1Tim", "2TI": "2Tim", "TIT": "Titus", "PHM": "Phlm",
    "HEB": "Heb", "JAS": "Jas", "1PE": "1Pet", "2PE": "2Pet",
    "1JN": "1John", "2JN": "2John", "3JN": "3John", "JUD": "Jude", "REV": "Rev",
}

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
    "Hag": 37, "Zech": 38, "Mal": 39, "Matt": 40, "Mark": 41, "Luke": 42,
    "John": 43, "Acts": 44, "Rom": 45, "1Cor": 46, "2Cor": 47, "Gal": 48,
    "Eph": 49, "Phil": 50, "Col": 51, "1Thess": 52, "2Thess": 53, "1Tim": 54,
    "2Tim": 55, "Titus": 56, "Phlm": 57, "Heb": 58, "Jas": 59, "1Pet": 60,
    "2Pet": 61, "1John": 62, "2John": 63, "3John": 64, "Jude": 65, "Rev": 66,
}

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} fetching {url}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error fetching {url}: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# Local file helpers
# ---------------------------------------------------------------------------


def load_local_json(path: Path) -> dict:
    """Load a JSON file from the local raw data cache."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_local_chapter_numbers(usfm_code: str) -> list:
    """Return sorted list of available chapter numbers from local commentary files."""
    commentary_dir = LOCAL_RAW_DIR / "c" / COMMENTARY_ID / usfm_code
    if not commentary_dir.exists():
        return []
    # Filenames are "{chapter}.json" — extract the numeric part
    chapters = []
    for p in commentary_dir.iterdir():
        if p.suffix == ".json":
            try:
                chapters.append(int(p.stem))
            except ValueError:
                pass
    return sorted(chapters)


# ---------------------------------------------------------------------------
# BSB verse text helpers
# ---------------------------------------------------------------------------


def extract_bsb_verses(bsb_data: dict) -> dict:
    """Return {verse_number: text} from a BSB chapter response.

    BSB content items can be:
      - plain strings (most prose books)
      - {"text": "...", "poem": N} objects (poetic books like Psalms, Proverbs)
      - formatting objects like {"lineBreak": True}, {"footnote": "..."} (skipped)
    """
    verses = {}
    for item in bsb_data["chapter"].get("content", []):
        if item.get("type") == "verse" and item.get("number") is not None:
            parts = item.get("content", [])
            if isinstance(parts, list):
                text_parts = []
                for p in parts:
                    if isinstance(p, str):
                        text_parts.append(p)
                    elif isinstance(p, dict) and "text" in p:
                        text_parts.append(p["text"])
                    # Skip formatting objects (lineBreak, footnote, etc.)
                text = " ".join(p.strip() for p in text_parts if p.strip())
            else:
                text = str(parts).strip() if isinstance(parts, str) else ""
            verses[item["number"]] = text
    return verses


def get_verse_text(verse_map: dict, start: int, end: int) -> str:
    parts = [verse_map[v] for v in range(start, end + 1) if v in verse_map]
    return " ".join(parts)


# ---------------------------------------------------------------------------
# OSIS reference builders
# ---------------------------------------------------------------------------


def osis_range(book_osis: str, chapter: int, start: int, end: int) -> str:
    if start == end:
        return f"{book_osis}.{chapter}.{start}"
    return f"{book_osis}.{chapter}.{start}-{book_osis}.{chapter}.{end}"


def entry_id(book_osis: str, chapter: int, start: int, end: int) -> str:
    if start == end:
        return f"{RESOURCE_ID}.{book_osis}.{chapter}.{start}"
    return f"{RESOURCE_ID}.{book_osis}.{chapter}.{start}-{end}"


# ---------------------------------------------------------------------------
# Entry builder
# ---------------------------------------------------------------------------


def make_entry(
    book_osis: str,
    chapter: int,
    start: int,
    end: int,
    commentary_text: str,
    verse_map: dict,
) -> dict:
    verse_range = str(start) if start == end else f"{start}-{end}"
    return {
        "entry_id": entry_id(book_osis, chapter, start, end),
        "book": OSIS_TO_NAME.get(book_osis, book_osis),
        "book_osis": book_osis,
        "book_number": OSIS_BOOK_NUMBER.get(book_osis, 0),
        "chapter": chapter,
        "verse_range": verse_range,
        "verse_range_osis": osis_range(book_osis, chapter, start, end),
        "verse_text": get_verse_text(verse_map, start, end) or None,
        "commentary_text": commentary_text,
        "summary": None,
        "summary_review_status": "withheld",
        "summary_source_span": None,
        "summary_reviewer": None,
        "key_quote": None,
        "key_quote_source_span": None,
        "key_quote_selection_criteria": None,
        "cross_references": [],
        "word_count": len(commentary_text.split()),
    }


# ---------------------------------------------------------------------------
# Chapter processing
# ---------------------------------------------------------------------------


def process_chapter(
    usfm_code: str,
    book_osis: str,
    chapter_num: int,
    local: bool = False,
) -> list:
    """Fetch/load one chapter and return commentary entries."""
    if local:
        commentary_path = (
            LOCAL_RAW_DIR / "c" / COMMENTARY_ID / usfm_code / f"{chapter_num}.json"
        )
        bsb_path = LOCAL_RAW_DIR / "BSB" / usfm_code / f"{chapter_num}.json"

        commentary_data = load_local_json(commentary_path)

        if bsb_path.exists():
            bsb_data = load_local_json(bsb_path)
        else:
            print(
                f"    WARNING: no BSB file for {usfm_code} ch{chapter_num} "
                f"-- verse text will be empty"
            )
            bsb_data = {"chapter": {"content": []}, "numberOfVerses": 0}
    else:
        commentary_url = (
            f"{HELLOAO_BASE}/c/{COMMENTARY_ID}/{usfm_code}/{chapter_num}.json"
        )
        bsb_url = f"{HELLOAO_BASE}/{BSB_ID}/{usfm_code}/{chapter_num}.json"

        commentary_data = fetch_json(commentary_url)
        time.sleep(REQUEST_DELAY)
        bsb_data = fetch_json(bsb_url)
        time.sleep(REQUEST_DELAY)

    verse_map = extract_bsb_verses(bsb_data)
    total_verses = bsb_data.get("numberOfVerses", 0)
    if not total_verses and verse_map:
        total_verses = max(verse_map.keys())

    ch = commentary_data["chapter"]
    # Filter to verse-type sections and sort by starting verse.
    # HelloAO occasionally has out-of-order entries (e.g. Ezek 40 has a stray
    # number=1 section appended after number=39). Sorting and deduplicating
    # produces the correct structure.
    raw_sections = [s for s in ch.get("content", []) if s.get("type") == "verse"]
    raw_sections.sort(key=lambda s: s.get("number", 0))
    # Merge sections that share the same starting verse number
    sections: list = []
    for s in raw_sections:
        if sections and sections[-1]["number"] == s["number"]:
            # Merge content into the previous section
            prev_content = sections[-1].get("content", [])
            new_content = s.get("content", [])
            if isinstance(prev_content, list) and isinstance(new_content, list):
                sections[-1]["content"] = prev_content + new_content
            # else: keep previous as-is
        else:
            sections.append(s)
    introduction = (ch.get("introduction") or "").strip()

    entries = []

    # Introduction text handling:
    # - If first section starts AFTER verse 1: intro gets its own entry (verses 1..N-1).
    # - If first section starts AT verse 1: prepend intro to that section's content
    #   so no data is lost (MH's chapter overview belongs with the verse 1 discussion).
    # - If no sections at all: intro is the entire chapter commentary.
    if introduction and sections:
        first_section_start = sections[0]["number"]
        if first_section_start > 1:
            entries.append(
                make_entry(
                    book_osis, chapter_num,
                    1, first_section_start - 1,
                    introduction, verse_map,
                )
            )
        else:
            # Prepend intro to the verse-1 section so the text is preserved.
            existing = sections[0].get("content", [])
            if isinstance(existing, list):
                sections[0]["content"] = [introduction] + existing
            else:
                sections[0]["content"] = [introduction, existing]
    elif introduction and not sections:
        # Entire chapter commentary is in the intro — only emit if we know the verse count.
        # Guard against data artifacts where total_verses = 0 (e.g. ISA ch68 in HelloAO).
        if total_verses > 0:
            entries.append(
                make_entry(
                    book_osis, chapter_num,
                    1, total_verses,
                    introduction, verse_map,
                )
            )
        else:
            print(
                f"    WARNING: ch{chapter_num} has intro text but total_verses=0 "
                f"-- skipping (data artifact)"
            )

    # Verse sections
    for i, section in enumerate(sections):
        start_verse = section["number"]
        end_verse = sections[i + 1]["number"] - 1 if i + 1 < len(sections) else total_verses

        content_parts = section.get("content", [])
        if isinstance(content_parts, list):
            text = "\n\n".join(str(p) for p in content_parts).strip()
        else:
            text = str(content_parts).strip()

        if not text:
            continue

        if end_verse < start_verse:
            print(
                f"    WARNING: skipping bad verse range {start_verse}-{end_verse} "
                f"in chapter {chapter_num}"
            )
            continue

        entries.append(
            make_entry(book_osis, chapter_num, start_verse, end_verse, text, verse_map)
        )

    return entries


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------


def build_meta(
    book_osis: str,
    usfm_code: str,
    fetch_date: str,
    data_hash: str,
    chapter_count: int,
    local: bool = False,
) -> dict:
    book_name = OSIS_TO_NAME.get(book_osis, book_osis)
    # Always use the canonical HelloAO URL as source_url — the data is the same
    # regardless of whether it was fetched live or read from a local copy.
    source_url = f"{HELLOAO_BASE}/c/{COMMENTARY_ID}/{usfm_code}"
    if local:
        source_format = "JSON (local copy of HelloAO API)"
        source_edition = (
            "HelloAO Bible API local download - Matthew Henry Bible Commentary "
            "(Public Domain Mark 1.0)"
        )
        notes = (
            f"Sourced from local copy of HelloAO Bible API data. Commentary licensed "
            f"PDM 1.0 (public domain -- Henry died 1714). BSB verse text from HelloAO "
            f"BSB translation (CC0). Processed {chapter_count} chapters of {book_name}."
        )
    else:
        source_format = "JSON"
        source_edition = (
            "HelloAO Bible API - Matthew Henry Bible Commentary "
            "(Public Domain Mark 1.0)"
        )
        notes = (
            f"Sourced from HelloAO Bible API. Commentary licensed PDM 1.0 "
            f"(public domain -- Henry died 1714). BSB verse text from HelloAO "
            f"BSB translation API (CC0). "
            f"Processed {chapter_count} chapters of {book_name}."
        )
    return {
        "id": RESOURCE_ID,
        "title": "Matthew Henry's Complete Commentary on the Whole Bible",
        "author": "Matthew Henry",
        "author_birth_year": 1662,
        "author_death_year": 1714,
        "contributors": [
            "Matthew Henry (died 1714, completed Genesis through Acts)",
            "13 nonconformist ministers (completed Romans through Revelation, published 1714)",
        ],
        "original_publication_year": 1706,
        "language": "en",
        "tradition": ["reformed", "puritan", "nonconformist"],
        "tradition_notes": (
            "Henry was a Nonconformist minister shaped by Puritan covenant theology. "
            "Often classified broadly as Reformed, but his pastoral and practical emphasis "
            "distinguishes him from more strictly scholastic Reformed writers."
        ),
        "license": "cc0-1.0",
        "schema_type": "commentary",
        "schema_version": SCHEMA_VERSION,
        "verse_text_source": "BSB",
        "verse_reference_standard": "OSIS",
        "completeness": "partial",
        "provenance": {
            "source_url": source_url,
            "source_format": source_format,
            "source_edition": source_edition,
            "download_date": fetch_date,
            "source_hash": f"sha256:{data_hash}",
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/matthew_henry_helloao.py@{SCRIPT_VERSION}"
            ),
            "processing_date": fetch_date,
            "notes": notes,
        },
        "summary_metadata": None,
    }


# ---------------------------------------------------------------------------
# Book processor
# ---------------------------------------------------------------------------


def process_book(
    usfm_code: str,
    chapter_count: int,
    dry_run: bool = False,
    local: bool = False,
) -> dict:
    """Process one book. Returns a stats dict for manifest building."""
    if usfm_code not in USFM_TO_OSIS:
        print(f"ERROR: Unknown USFM code '{usfm_code}'")
        return {}

    book_osis = USFM_TO_OSIS[usfm_code]
    book_name = OSIS_TO_NAME.get(book_osis, book_osis)
    file_stem = book_name.lower().replace(" ", "-")
    out_file = DATA_DIR / f"{file_stem}.json"

    mode_label = "local" if local else "API"
    print(
        f"Processing {book_name} ({usfm_code} -> {book_osis}), "
        f"{chapter_count} chapters [{mode_label}]"
    )

    if dry_run:
        if local:
            # In local dry-run, load chapter 1 from disk
            chapters = get_local_chapter_numbers(usfm_code)
            ch1 = chapters[0] if chapters else 1
            print(f"  [dry-run] Loading local chapter {ch1}...")
        else:
            ch1 = 1
            print(f"  [dry-run] Fetching chapter {ch1} to verify API connectivity...")
        try:
            entries = process_chapter(usfm_code, book_osis, ch1, local=local)
            print(f"  [dry-run] Chapter {ch1}: {len(entries)} entries. OK.")
            if entries:
                print(f"  [dry-run] First entry_id: {entries[0]['entry_id']}")
                print(f"  [dry-run] verse_range: {entries[0]['verse_range']}")
                print(f"  [dry-run] word_count: {entries[0]['word_count']} words")
        except Exception as exc:
            print(f"  [dry-run] ERROR on chapter {ch1}: {exc}")
        print(f"  [dry-run] Would write to: {out_file}")
        return {}

    all_entries = []
    failed_chapters = []

    # In local mode, enumerate actual files on disk to handle gaps and partial books.
    # In API mode, iterate sequentially using the configured chapter count.
    if local:
        chapters_to_process = get_local_chapter_numbers(usfm_code)
        if not chapters_to_process:
            print(f"  ERROR: no local files found for {usfm_code}")
            return {}
        actual_chapter_count = len(chapters_to_process)
    else:
        chapters_to_process = list(range(1, chapter_count + 1))
        actual_chapter_count = chapter_count

    for idx, ch_num in enumerate(chapters_to_process, 1):
        print(
            f"  Chapter {ch_num} ({idx}/{actual_chapter_count})", end="", flush=True
        )
        try:
            entries = process_chapter(usfm_code, book_osis, ch_num, local=local)
            all_entries.extend(entries)
            print(f" -> {len(entries)} entries")
        except Exception as exc:
            print(f" -> ERROR: {exc}")
            failed_chapters.append(ch_num)

    if failed_chapters:
        print(f"WARNING: {len(failed_chapters)} chapters failed: {failed_chapters}")

    fetch_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data_bytes = json.dumps(all_entries, ensure_ascii=False, sort_keys=True).encode("utf-8")
    data_hash = hashlib.sha256(data_bytes).hexdigest()

    output = {
        "meta": build_meta(
            book_osis, usfm_code, fetch_date, data_hash,
            actual_chapter_count, local=local,
        ),
        "data": all_entries,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8", newline="\n") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    size_kb = out_file.stat().st_size / 1024
    print(f"Wrote {len(all_entries)} entries -> {out_file.name}")
    print(f"File size: {size_kb:.0f} KB")

    # Quality stats -- always printed so data issues surface during processing,
    # not later during a separate review step.
    if all_entries:
        words = [e["word_count"] for e in all_entries]
        null_vt = sum(1 for e in all_entries if not e.get("verse_text"))
        null_ct = sum(1 for e in all_entries if not (e.get("commentary_text") or "").strip())
        short = sum(1 for e in all_entries if e["word_count"] < 20)
        total = len(all_entries)
        print(
            f"  Quality: words min={min(words)} med={sorted(words)[total//2]} "
            f"max={max(words)}"
        )
        if null_vt:
            pct = null_vt * 100 / total
            print(f"  WARNING: {null_vt}/{total} entries ({pct:.1f}%) missing verse_text")
        if null_ct:
            print(f"  WARNING: {null_ct}/{total} entries missing commentary_text")
        if short:
            print(f"  WARNING: {short}/{total} entries under 20 words")

    if failed_chapters:
        print(
            f"WARNING: Missing chapters: {failed_chapters} -- re-run or check coverage"
        )

    return {
        "usfm_code": usfm_code,
        "osis_code": book_osis,
        "name": book_name,
        "file": f"{file_stem}.json",
        "chapter_count": actual_chapter_count,
        "entry_count": len(all_entries),
        "status": "complete" if not failed_chapters else "partial",
        "summary_status": "withheld",
    }


# ---------------------------------------------------------------------------
# Manifest update
# ---------------------------------------------------------------------------


def update_manifest(book_stats: list) -> None:
    """Write _manifest.json from a list of book stats dicts."""
    manifest_path = DATA_DIR / "_manifest.json"

    # Load existing manifest to preserve entries not in this run
    existing_by_usfm = {}
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            existing = json.load(f)
        for b in existing.get("books", []):
            existing_by_usfm[b["usfm_code"]] = b

    # Merge: new stats override existing entries
    for stats in book_stats:
        if stats:
            existing_by_usfm[stats["usfm_code"]] = stats

    # Sort by OSIS book number
    all_books = sorted(
        existing_by_usfm.values(),
        key=lambda b: OSIS_BOOK_NUMBER.get(USFM_TO_OSIS.get(b["usfm_code"], ""), 999),
    )

    total_entries = sum(b.get("entry_count", 0) for b in all_books)
    books_with_summaries = sum(
        1 for b in all_books if b.get("summary_status") not in ("withheld", None)
    )

    manifest = {
        "resource_id": RESOURCE_ID,
        "title": "Matthew Henry's Complete Commentary on the Whole Bible",
        "schema_type": "commentary",
        "schema_version": SCHEMA_VERSION,
        "books": all_books,
        "stats": {
            "total_books": len(all_books),
            "total_entries": total_entries,
            "books_with_summaries": books_with_summaries,
        },
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Manifest updated: {len(all_books)} books, {total_entries} total entries")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Matthew Henry from HelloAO")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--book", metavar="USFM", help="Process one book, e.g. EZK")
    group.add_argument("--all-books", action="store_true", help="Process all books in config")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load/fetch chapter 1 only to verify; do not write output files",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Read from local raw files instead of HelloAO API",
    )
    args = parser.parse_args()

    with open(CONFIG_FILE, encoding="utf-8") as f:
        config = json.load(f)

    books = {b["usfm_code"]: b for b in config["books"]}

    if args.all_books:
        book_stats = []
        start_time = time.time()
        for usfm_code, book_cfg in books.items():
            stats = process_book(
                usfm_code,
                book_cfg["chapter_count"],
                dry_run=args.dry_run,
                local=args.local,
            )
            book_stats.append(stats)
        if not args.dry_run:
            update_manifest(book_stats)
        # Grand summary (CODING_DEFAULTS Rule 7)
        elapsed = time.time() - start_time
        valid_stats = [s for s in book_stats if s]
        total_entries = sum(s.get("entry_count", 0) for s in valid_stats)
        failed = [s["usfm_code"] for s in valid_stats if s.get("status") == "partial"]
        print()
        print(f"=== DONE: {len(valid_stats)} books, {total_entries} entries, {elapsed:.1f}s ===")
        if failed:
            print(f"  Partial books (had chapter failures): {failed}")
    else:
        usfm_code = args.book.upper()
        if usfm_code not in books:
            print(f"ERROR: '{usfm_code}' not in config. Available: {list(books.keys())}")
            return
        book_cfg = books[usfm_code]
        stats = process_book(
            usfm_code,
            book_cfg["chapter_count"],
            dry_run=args.dry_run,
            local=args.local,
        )
        if not args.dry_run and stats:
            update_manifest([stats])


if __name__ == "__main__":
    main()
