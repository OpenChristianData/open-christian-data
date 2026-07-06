"""audit_data_accuracy.py
Runs automated accuracy checks across all OCD data files and writes a structured report.

This script only reads data -- it never modifies any data file.

Usage:
    py -3 build/tools/audit_data_accuracy.py
    py -3 build/tools/audit_data_accuracy.py --category bible-text
    py -3 build/tools/audit_data_accuracy.py --category commentaries

Output:
    build/tools/data_accuracy_report.md   (human-readable)
    build/tools/data_accuracy_report.json (machine-readable)
    build/tools/audit_data_accuracy.log   (run log)

Exit code: always 0 (reporting tool, not a gate).
"""

import argparse
import hashlib
import json
import logging
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from statistics import median

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

from build.lib.paths import REPO_ROOT  # noqa: E402
DATA_DIR = REPO_ROOT / "data"
BUILD_DIR = REPO_ROOT / "build"
VERSE_INDEX_PATH = BUILD_DIR / "bible_data" / "verse_index.json"
DISPUTED_VERSES_PATH = BUILD_DIR / "bible_data" / "disputed_verses.json"
OUTPUT_DIR = BUILD_DIR / "tools"
REPORT_MD_PATH = OUTPUT_DIR / "data_accuracy_report.md"
REPORT_JSON_PATH = OUTPUT_DIR / "data_accuracy_report.json"
LOG_PATH = OUTPUT_DIR / "audit_data_accuracy.log"

# All auditable data categories (excludes 'authors' which has no schema)
ALL_CATEGORIES = [
    "bible-text",
    "catechisms",
    "church-fathers",
    "commentaries",
    "devotionals",
    "doctrinal-documents",
    "prayers",
    "reference",
    "sermons",
    "structured-text",
    "topical-reference",
]

# Unique ID field name per schema_type (None = complex/no simple id)
ID_FIELD = {
    "bible_text": "osis",
    "commentary": "entry_id",
    "catechism_qa": "item_id",
    "devotional": "entry_id",
    "prayer": "prayer_id",
    "church_fathers": "entry_id",
    "sermon": "sermon_id",
    "reference_entry": "entry_id",
    "topical_reference": "entry_id",
    "structured_text": None,
    "doctrinal_document": None,
}

# Main text field per schema_type (None = extracted via get_entry_text())
TEXT_FIELD = {
    "bible_text": "text",
    "commentary": "commentary_text",
    "catechism_qa": "answer",
    "church_fathers": "quote",
    "reference_entry": None,    # definition_blocks list
    "topical_reference": None,  # subtopics list
    "devotional": None,         # content_blocks list
    "prayer": None,             # content_blocks list
    "sermon": None,             # content_blocks list
    "structured_text": None,
    "doctrinal_document": None,
}

# Word count outlier thresholds: (min_words, max_words) -- None = no limit
WORD_COUNT_THRESHOLDS = {
    "commentary": (5, 3000),
    "catechism_qa": (3, None),
    "devotional": (20, None),
    "prayer": (5, None),
    "church_fathers": (3, None),
    "reference_entry": (5, None),
}

# Expected item counts for catechisms (hardcoded fallback only)
CATECHISM_EXPECTED = {
    "westminster-shorter-catechism": 107,
    "westminster-larger-catechism": 196,
    "heidelberg-catechism": 129,   # may have more due to sub-questions
    "baltimore-catechism-no-1": 206,
    "baltimore-catechism-no-2": 421,
    "baltimore-catechism-no-3": 1400,
}

# OCR artifact patterns: (compiled_regex, description)
OCR_PATTERNS = [
    (re.compile(r"^[*\-=.]{3,}\s*$", re.MULTILINE), "Line of repeated punctuation"),
    (re.compile(r"@ \w"), "SWORD footnote marker '@ '"),
    (re.compile(r"\[Page \d+\]"), "Gutenberg page marker"),
    (re.compile(r"\n{3,}"), "Three or more consecutive blank lines"),
    (re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]"), "Non-printable control character"),
    # 3+ identical punctuation (excluding . to avoid flagging ellipsis)
    (re.compile(r"([^\w\s.])\1\1+"), "Run of 3+ identical punctuation"),
]

# Mojibake: UTF-8 bytes misread as Windows-1252
_MOJIBAKE_SEQS = [
    "\u00e2\u20ac\u2122",  # â€™  U+2019 RIGHT SINGLE QUOTATION MARK
    "\u00e2\u20ac\u201d",  # â€"  U+201D RIGHT DOUBLE QUOTATION MARK
    "\u00e2\u20ac\u0153",  # â€œ  U+201C LEFT DOUBLE QUOTATION MARK
    "\u00c3\u00a9",        # Ã©   U+00E9 e-acute
    "\u00c3\u00a8",        # Ã¨   U+00E8 e-grave
    "\u00c3\u00bc",        # Ã¼   U+00FC u-umlaut
    "\u00e2\u20ac\u201c",  # â€"  U+2013 EN DASH
    "\u00e2\u20ac\u201e",  # â€"  U+2014 EM DASH variant
]
MOJIBAKE_RE = re.compile("|".join(re.escape(s) for s in _MOJIBAKE_SEQS))

MAX_OCR_MATCHES_PER_PATTERN = 50


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------

class Finding:
    """One audit finding with severity, check name, location, and message."""

    def __init__(self, severity, check, category, file_path, entry_id, message, detail=""):
        self.severity = severity    # "P1", "P2", "P3"
        self.check = check          # task / check name
        self.category = category
        self.file_path = file_path  # relative path from REPO_ROOT
        self.entry_id = str(entry_id) if entry_id is not None else ""
        self.message = message
        self.detail = detail

    def to_dict(self):
        return {
            "severity": self.severity,
            "check": self.check,
            "category": self.category,
            "file_path": self.file_path,
            "entry_id": self.entry_id,
            "message": self.message,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# File loading helpers
# ---------------------------------------------------------------------------

def load_all_files(categories=None):
    """Load all data JSON files.

    Returns dict: category -> list of (rel_path_str, parsed_doc_dict).
    """
    result = {}
    scan_cats = categories if categories else ALL_CATEGORIES
    for cat in scan_cats:
        cat_dir = DATA_DIR / cat
        if not cat_dir.exists():
            logging.warning("Category directory not found: %s", cat_dir)
            result[cat] = []
            continue
        files = sorted(cat_dir.rglob("*.json"))
        entries = []
        for fp in files:
            # Skip manifest / index files (start with _)
            if fp.name.startswith("_"):
                logging.info("Skipping manifest file: %s", fp.name)
                continue
            try:
                with open(fp, encoding="utf-8") as fh:
                    doc = json.load(fh)
                rel = str(fp.relative_to(REPO_ROOT))
                entries.append((rel, doc))
            except Exception as exc:
                logging.error("Failed to load %s: %s", fp, exc)
        result[cat] = entries
        logging.info("Loaded %d file(s) from category '%s'", len(entries), cat)
    return result


def get_data_entries(doc):
    """Return the entries list from a loaded document, or [] if not a list.

    All OCD data files have the structure: {"meta": {...}, "data": [...]}.
    Never iterate over `doc` directly -- doc is a dict, not the entries list.
    """
    data = doc.get("data")
    if isinstance(data, list):
        return data
    return []


def get_entry_id(entry, schema_type):
    """Extract the unique identifier from an entry."""
    field = ID_FIELD.get(schema_type)
    if field:
        val = entry.get(field)
        return str(val) if val is not None else ""
    return ""


def get_entry_text(entry, schema_type):
    """Extract the main text content from an entry as a single string."""
    # catechism_qa: token_count is stored using "Q: {question} A: {answer}" format.
    # This must match add_token_counts.py::extract_text_catechism_qa() exactly.
    # Using q + " " + a is wrong -- it's 4 tokens short due to missing "Q: " and "A: " labels.
    if schema_type == "catechism_qa":
        q = entry.get("question") or ""
        a = entry.get("answer") or ""
        return "Q: {} A: {}".format(q, a)

    # Direct field
    direct = TEXT_FIELD.get(schema_type)
    if direct is not None:
        return entry.get(direct) or ""

    # content_blocks types (devotional, prayer, sermon)
    if schema_type in ("devotional", "prayer", "sermon"):
        blocks = entry.get("content_blocks", [])
        parts = []
        for b in blocks:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict):
                parts.append(b.get("text") or b.get("content") or "")
        return " ".join(p for p in parts if p)

    # reference_entry: definition_blocks
    if schema_type == "reference_entry":
        blocks = entry.get("definition_blocks", [])
        parts = []
        for b in blocks:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict):
                parts.append(b.get("text") or b.get("content") or "")
        return " ".join(p for p in parts if p)

    # topical_reference: subtopics (list of strings or dicts)
    if schema_type == "topical_reference":
        subtopics = entry.get("subtopics", [])
        parts = []
        for s in subtopics:
            if isinstance(s, str):
                parts.append(s)
            elif isinstance(s, dict):
                parts.append(s.get("heading") or "")
                refs = s.get("references", [])
                if isinstance(refs, list):
                    parts.extend(str(r) for r in refs if r)
        return " ".join(p for p in parts if p)

    return ""


def get_entry_word_count(entry, schema_type):
    """Get word count for an entry.

    For catechism_qa, computes from the answer text (as specified in the prompt).
    Otherwise uses the pre-computed word_count field, falling back to text computation.
    """
    if schema_type == "catechism_qa":
        text = entry.get("answer") or ""
        return len(text.split()) if text else 0

    wc = entry.get("word_count")
    if isinstance(wc, int) and wc >= 0:
        return wc

    # Fall back to computing from extracted text
    text = get_entry_text(entry, schema_type)
    return len(text.split()) if text else 0


# ---------------------------------------------------------------------------
# Task 2 -- Entry count verification
# ---------------------------------------------------------------------------

def run_task_2_entry_counts(all_files, verse_index, disputed_verses):
    """Verify entry counts against canonical on-disk references."""
    findings = []
    vi_books = verse_index.get("books", {})
    vi_total = verse_index.get("total_verses", 0)

    # Count manuscript omissions (verses in KJV/TR but not BSB)
    ms_omissions = sum(
        1
        for book_data in disputed_verses.get("books", {}).values()
        for ch_data in book_data.values()
        for item in ch_data
        if item.get("type") == "manuscript_omission"
    )
    kjv_expected = vi_total + ms_omissions

    # --- Bible-text: total and per-book ---
    bsb_files = all_files.get("bible-text", [])
    total_bsb_verses = sum(len(get_data_entries(doc)) for _, doc in bsb_files)

    if total_bsb_verses != vi_total:
        findings.append(Finding(
            "P1", "entry_count", "bible-text",
            "build/bible_data/verse_index.json", "TOTAL",
            f"BSB total {total_bsb_verses} != verse_index total {vi_total}",
            f"Discrepancy: {abs(total_bsb_verses - vi_total)} verses",
        ))
    else:
        findings.append(Finding(
            "P3", "entry_count", "bible-text",
            "build/bible_data/verse_index.json", "TOTAL",
            (
                f"BSB total: {total_bsb_verses} verses. "
                f"Manuscript omissions: {ms_omissions}. "
                f"KJV expected: {kjv_expected}."
            ),
        ))

    for rel_path, doc in bsb_files:
        if doc.get("meta", {}).get("schema_type") != "bible_text":
            continue
        entries = get_data_entries(doc)
        if not entries:
            findings.append(Finding(
                "P1", "entry_count", "bible-text", rel_path, "ALL",
                "Bible-text file has 0 entries",
            ))
            continue
        book_osis = entries[0].get("osis", "").split(".")[0]
        if not book_osis or book_osis not in vi_books:
            findings.append(Finding(
                "P2", "entry_count", "bible-text", rel_path, "ALL",
                f"Cannot match book_osis '{book_osis}' in verse_index",
            ))
            continue
        book_info = vi_books[book_osis]
        expected = sum(len(v) for v in book_info["verses"].values())
        actual = len(entries)
        if actual != expected:
            findings.append(Finding(
                "P1", "entry_count", "bible-text", rel_path, book_osis,
                f"Verse count {actual} != expected {expected}",
                f"Difference: {actual - expected}",
            ))

    # --- Catechisms ---
    for rel_path, doc in all_files.get("catechisms", []):
        entries = get_data_entries(doc)
        doc_id = Path(rel_path).stem
        actual = len(entries)
        prov_notes = doc.get("meta", {}).get("provenance", {}).get("notes", "") or ""

        # Try parsing expected count from provenance notes
        m = re.search(r"(\d+)\s+(?:questions?|Q&A|items?)", prov_notes, re.I)
        expected = int(m.group(1)) if m else CATECHISM_EXPECTED.get(doc_id)

        if expected is not None:
            if actual != expected:
                # Heidelberg may legitimately have more items due to sub-questions
                sev = "P2" if (doc_id == "heidelberg-catechism" and actual >= expected) else "P1"
                findings.append(Finding(
                    sev, "entry_count", "catechisms", rel_path, doc_id,
                    f"Item count {actual} != expected {expected}",
                    f"Source: {'provenance notes' if m else 'hardcoded fallback'}",
                ))
            else:
                findings.append(Finding(
                    "P3", "entry_count", "catechisms", rel_path, doc_id,
                    f"Item count {actual} matches expected {expected}",
                ))
        else:
            findings.append(Finding(
                "P3", "entry_count", "catechisms", rel_path, doc_id,
                f"Actual item count: {actual} (no expected count discoverable)",
            ))

    # --- Church-fathers: flag any file with 0 entries ---
    for rel_path, doc in all_files.get("church-fathers", []):
        entries = get_data_entries(doc)
        if len(entries) == 0:
            findings.append(Finding(
                "P1", "entry_count", "church-fathers", rel_path, "ALL",
                "Church-fathers file has 0 entries -- possible parsing failure",
            ))

    # --- Commentaries: flag any file with 0 entries ---
    for rel_path, doc in all_files.get("commentaries", []):
        entries = get_data_entries(doc)
        if len(entries) == 0:
            findings.append(Finding(
                "P1", "entry_count", "commentaries", rel_path, "ALL",
                "Commentary file has 0 entries -- possible parsing failure",
            ))

    # --- All other categories: report actual count as P3 ---
    skip_cats = {"bible-text", "catechisms", "church-fathers", "commentaries"}
    for cat in all_files:
        if cat in skip_cats:
            continue
        for rel_path, doc in all_files[cat]:
            entries = get_data_entries(doc)
            prov_notes = doc.get("meta", {}).get("provenance", {}).get("notes", "") or ""
            m = re.search(r"(\d+)\s+(?:entries|items?|records?|prayers?|sermons?)", prov_notes, re.I)
            if m:
                expected = int(m.group(1))
                if len(entries) != expected:
                    findings.append(Finding(
                        "P2", "entry_count", cat, rel_path, "ALL",
                        f"Entry count {len(entries)} != provenance note expected {expected}",
                        f"Notes excerpt: {prov_notes[:100]}",
                    ))
                else:
                    findings.append(Finding(
                        "P3", "entry_count", cat, rel_path, "ALL",
                        f"Entry count {len(entries)} matches provenance notes",
                    ))
            else:
                findings.append(Finding(
                    "P3", "entry_count", cat, rel_path, "ALL",
                    f"Actual entry count: {len(entries)} (no expected count discoverable)",
                ))

    return findings


# ---------------------------------------------------------------------------
# Task 3 -- Duplicate entry_id detection
# ---------------------------------------------------------------------------

def run_task_3_duplicate_ids(all_files):
    """Check for duplicate IDs within files; cross-file uniqueness for commentaries."""
    findings = []
    # Track global IDs per commentary author
    commentary_ids_by_author = defaultdict(set)

    for cat, file_list in all_files.items():
        for rel_path, doc in file_list:
            schema_type = doc.get("meta", {}).get("schema_type")
            if schema_type is None or schema_type in ("structured_text", "doctrinal_document"):
                continue
            id_field = ID_FIELD.get(schema_type)
            if not id_field:
                continue
            entries = get_data_entries(doc)
            if not entries:
                continue

            # Within-file duplicate check
            seen = {}  # id_str -> first index
            for i, entry in enumerate(entries):
                raw_id = entry.get(id_field)
                if raw_id is None:
                    continue
                eid = str(raw_id)
                if eid in seen:
                    findings.append(Finding(
                        "P1", "duplicate_ids", cat, rel_path, eid,
                        f"Duplicate {id_field} at positions {seen[eid]} and {i}",
                    ))
                else:
                    seen[eid] = i

            # Commentary: cross-file global uniqueness per author
            if schema_type == "commentary":
                parts = Path(rel_path).parts
                author_slug = parts[2] if len(parts) >= 3 else Path(rel_path).parent.name
                for eid in seen:
                    if eid in commentary_ids_by_author[author_slug]:
                        findings.append(Finding(
                            "P1", "duplicate_ids", cat, rel_path, eid,
                            f"entry_id duplicated across files for author '{author_slug}'",
                        ))
                    else:
                        commentary_ids_by_author[author_slug].add(eid)

    return findings


# ---------------------------------------------------------------------------
# Task 4 -- Word count outlier detection
# ---------------------------------------------------------------------------

def run_task_4_word_count_outliers(all_files):
    """Flag word count outliers and report per-schema-type distribution stats."""
    findings = []
    # schema_type -> list of (word_count, rel_path, entry_id, text_snippet)
    wc_by_type = defaultdict(list)

    for cat, file_list in all_files.items():
        for rel_path, doc in file_list:
            schema_type = doc.get("meta", {}).get("schema_type")
            if schema_type is None or schema_type in ("structured_text", "doctrinal_document"):
                continue
            entries = get_data_entries(doc)
            for entry in entries:
                wc = get_entry_word_count(entry, schema_type)
                eid = get_entry_id(entry, schema_type)
                text = get_entry_text(entry, schema_type)
                snippet = text[:100] if text else ""
                wc_by_type[schema_type].append((wc, rel_path, eid, snippet))

    for schema_type, items in sorted(wc_by_type.items()):
        if not items:
            continue
        wcs = sorted(wc for wc, _, _, _ in items)
        n = len(wcs)
        p5 = wcs[max(0, int(n * 0.05))]
        p95 = wcs[min(n - 1, int(n * 0.95))]
        med = median(wcs)

        findings.append(Finding(
            "P3", "word_count_distribution", schema_type, "(all files)", "",
            (
                f"Word count distribution for {schema_type} (n={n}): "
                f"min={wcs[0]}, p5={p5}, median={med:.0f}, p95={p95}, max={wcs[-1]}"
            ),
        ))

        thresholds = WORD_COUNT_THRESHOLDS.get(schema_type)
        if not thresholds:
            continue
        min_thresh, max_thresh = thresholds

        for wc, rel_path, eid, snippet in items:
            if min_thresh is not None and wc < min_thresh:
                findings.append(Finding(
                    "P2", "word_count_outlier", schema_type, rel_path, eid,
                    f"Word count {wc} below minimum {min_thresh} for {schema_type}",
                    f"Text: {snippet}",
                ))
            if max_thresh is not None and wc > max_thresh:
                findings.append(Finding(
                    "P2", "word_count_outlier", schema_type, rel_path, eid,
                    f"Word count {wc} above maximum {max_thresh} for {schema_type}",
                    f"Text: {snippet}",
                ))

    return findings


# ---------------------------------------------------------------------------
# Task 5a -- OCR artifact and formatting residue detection
# ---------------------------------------------------------------------------

def _scan_ocr_artifacts(text):
    """Return list of (pattern_name, context_str) for matches in text."""
    results = []
    for pattern, name in OCR_PATTERNS:
        for m in pattern.finditer(text):
            start = max(0, m.start() - 40)
            end = min(len(text), m.end() + 40)
            ctx = text[start:end].replace("\n", " ")
            results.append((name, ctx))

    # Non-ASCII sequences that don't form valid Unicode word characters
    non_ascii_run = re.compile(r"[^\x00-\x7f]{3,}")
    for m in non_ascii_run.finditer(text):
        chunk = m.group(0)
        if not all(unicodedata.category(c)[0] in ("L", "N", "M") for c in chunk):
            ctx = text[max(0, m.start() - 30): m.end() + 30].replace("\n", " ")
            results.append(("Possible encoding corruption (non-ASCII non-word run)", ctx))

    return results


def run_task_5a_ocr_artifacts(all_files):
    """Scan all entries for OCR artifacts and formatting residue."""
    findings = []
    pattern_counts = Counter()

    for cat, file_list in all_files.items():
        for rel_path, doc in file_list:
            schema_type = doc.get("meta", {}).get("schema_type")
            if schema_type is None or schema_type in ("structured_text", "doctrinal_document"):
                continue
            entries = get_data_entries(doc)
            for entry in entries:
                text = get_entry_text(entry, schema_type)
                if not text:
                    continue
                eid = get_entry_id(entry, schema_type)
                for name, ctx in _scan_ocr_artifacts(text):
                    if pattern_counts[name] >= MAX_OCR_MATCHES_PER_PATTERN:
                        continue
                    pattern_counts[name] += 1
                    findings.append(Finding(
                        "P2", "ocr_artifacts", cat, rel_path, eid,
                        f"OCR/format artifact: {name}",
                        f"Context: ...{ctx}...",
                    ))

    # Report suppressed match counts
    for name, total in pattern_counts.items():
        if total >= MAX_OCR_MATCHES_PER_PATTERN:
            findings.append(Finding(
                "P3", "ocr_artifacts", "(all)", "(all)", "",
                f"Pattern '{name}': {total}+ matches (capped at {MAX_OCR_MATCHES_PER_PATTERN} per pattern)",
            ))

    return findings


# ---------------------------------------------------------------------------
# Task 5b -- Encoding / Unicode consistency
# ---------------------------------------------------------------------------

def run_task_5b_encoding(all_files):
    """Check UTF-8 validity, BOM presence, mojibake, and NFC normalization."""
    findings = []

    for cat, file_list in all_files.items():
        for rel_path, doc in file_list:
            schema_type = doc.get("meta", {}).get("schema_type")
            full_path = REPO_ROOT / rel_path

            # File-level checks
            try:
                raw = full_path.read_bytes()
            except Exception as exc:
                logging.warning("Could not read bytes for %s: %s", rel_path, exc)
                continue

            if raw.startswith(b"\xef\xbb\xbf"):
                findings.append(Finding(
                    "P2", "encoding", cat, rel_path, "FILE",
                    "File contains UTF-8 BOM -- may break strict JSON parsers",
                ))

            try:
                text_content = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                findings.append(Finding(
                    "P1", "encoding", cat, rel_path, "FILE",
                    f"File is not valid UTF-8: {exc}",
                ))
                continue

            m = MOJIBAKE_RE.search(text_content)
            if m:
                ctx = text_content[max(0, m.start() - 20): m.end() + 20]
                findings.append(Finding(
                    "P1", "encoding", cat, rel_path, "FILE",
                    f"Mojibake detected: '{m.group(0)}' (UTF-8 bytes read as Latin-1/Windows-1252)",
                    f"Context: ...{ctx}...",
                ))

            # Entry-level NFC check
            if schema_type is None or schema_type in ("structured_text", "doctrinal_document"):
                continue
            entries = get_data_entries(doc)
            for entry in entries:
                text = get_entry_text(entry, schema_type)
                if text and not unicodedata.is_normalized("NFC", text):
                    eid = get_entry_id(entry, schema_type)
                    findings.append(Finding(
                        "P2", "encoding", cat, rel_path, eid,
                        "Entry text is not NFC-normalized",
                    ))

    return findings


# ---------------------------------------------------------------------------
# Task 6 -- Bible text verse continuity
# ---------------------------------------------------------------------------

def run_task_6_verse_continuity(all_files, verse_index):
    """Check each of the 66 bible-text files for completeness vs verse_index."""
    findings = []
    vi_books = verse_index.get("books", {})

    for rel_path, doc in all_files.get("bible-text", []):
        entries = get_data_entries(doc)
        if not entries:
            continue
        book_osis = entries[0].get("osis", "").split(".")[0]
        if not book_osis or book_osis not in vi_books:
            continue

        book_info = vi_books[book_osis]
        # Build expected set: {(chapter_str, verse_int)}
        expected_pairs = {
            (ch_str, v)
            for ch_str, verse_list in book_info["verses"].items()
            for v in verse_list
        }

        # Build actual set from data entries
        data_pairs = set()
        empty_osis = []
        for entry in entries:
            ch = entry.get("chapter")
            vs = entry.get("verse")
            text = entry.get("text", "")
            if ch is not None and vs is not None:
                data_pairs.add((str(ch), vs))
                if not text or not text.strip():
                    empty_osis.append(entry.get("osis", f"{book_osis}.{ch}.{vs}"))

        # Missing (in index but not in data)
        for ch_str, vs in sorted(expected_pairs - data_pairs, key=lambda x: (int(x[0]), x[1])):
            findings.append(Finding(
                "P1", "verse_continuity", "bible-text", rel_path,
                f"{book_osis}.{ch_str}.{vs}",
                f"Verse present in verse_index but missing from data file",
            ))

        # Extra (in data but not in index)
        for ch_str, vs in sorted(data_pairs - expected_pairs, key=lambda x: (int(x[0]), x[1])):
            findings.append(Finding(
                "P1", "verse_continuity", "bible-text", rel_path,
                f"{book_osis}.{ch_str}.{vs}",
                f"Verse present in data file but not in verse_index",
            ))

        # Empty verse text
        for oid in empty_osis:
            findings.append(Finding(
                "P2", "verse_continuity", "bible-text", rel_path, oid,
                "Verse has empty or whitespace-only text",
            ))

    return findings


# ---------------------------------------------------------------------------
# Task 7 -- Sequence continuity
# ---------------------------------------------------------------------------

def run_task_7_sequence_continuity(all_files, verse_index):
    """Check catechism item sequences, devotional date coverage, commentary coverage %."""
    findings = []
    vi_books = verse_index.get("books", {})

    # --- Catechisms: item_id must form a complete integer sequence ---
    for rel_path, doc in all_files.get("catechisms", []):
        if doc.get("meta", {}).get("schema_type") != "catechism_qa":
            continue
        entries = get_data_entries(doc)
        if not entries:
            continue

        numbers = []
        for entry in entries:
            try:
                numbers.append(int(entry.get("item_id", "")))
            except (ValueError, TypeError):
                pass

        if not numbers:
            continue

        doc_id = Path(rel_path).stem
        numbers_set = Counter(numbers)
        duplicates = [n for n, c in numbers_set.items() if c > 1]
        for n in sorted(duplicates):
            findings.append(Finding(
                "P1", "sequence_continuity", "catechisms", rel_path, str(n),
                f"Duplicate item_id {n} in catechism sequence",
            ))

        expected = set(range(min(numbers), max(numbers) + 1))
        gaps = sorted(expected - set(numbers))
        if gaps:
            # Known false-positive cases:
            #   Baltimore No.1 (206 entries) reuses Baltimore No.2's question numbers as item_ids,
            #   so only ~half the range is present. >50% gap ratio = intentional numbering scheme.
            #   Exposition of Assemblies Catechism (125 entries) has 5 upstream gaps where the
            #   source has "Number": "?" (unnumbered sub-questions) -- small gap count (<=10).
            if len(gaps) > len(numbers) * 0.5:
                findings.append(Finding(
                    "P3", "sequence_continuity", "catechisms", rel_path, doc_id,
                    (
                        f"Non-sequential item_id numbering scheme detected "
                        f"({len(numbers)} entries span {max(numbers) - min(numbers) + 1} range, "
                        f"{len(gaps)} gaps)"
                    ),
                    "item_ids are intentional subset of a larger numbering scheme -- not a data error",
                ))
            elif len(gaps) <= 10:
                # Small gaps are typically upstream unnumbered sub-questions
                # or legitimate source omissions -- suspicious but not necessarily wrong.
                findings.append(Finding(
                    "P2", "sequence_continuity", "catechisms", rel_path, doc_id,
                    f"Small gap(s) in item_id sequence: {gaps} -- may be upstream unnumbered entries",
                    f"Total gaps: {len(gaps)}",
                ))
            else:
                findings.append(Finding(
                    "P1", "sequence_continuity", "catechisms", rel_path, doc_id,
                    f"Gap(s) in item_id sequence: {gaps[:20]}{'...' if len(gaps) > 20 else ''}",
                    f"Total gaps: {len(gaps)}",
                ))

    # --- Devotionals: 365 (or 366) unique MM-DD dates required ---
    for rel_path, doc in all_files.get("devotionals", []):
        if doc.get("meta", {}).get("schema_type") != "devotional":
            continue
        entries = get_data_entries(doc)
        if not entries:
            continue

        prov_notes = doc.get("meta", {}).get("provenance", {}).get("notes", "") or ""
        has_leap = "leap" in prov_notes.lower() or "366" in prov_notes
        expected_days = 366 if has_leap else 365

        unique_dates = set()
        for entry in entries:
            eid = entry.get("entry_id", "")
            parts = eid.split("-")
            if len(parts) >= 2:
                unique_dates.add(f"{parts[0]}-{parts[1]}")

        if len(unique_dates) < expected_days:
            findings.append(Finding(
                "P1", "sequence_continuity", "devotionals", rel_path,
                Path(rel_path).stem,
                (
                    f"Only {len(unique_dates)} unique dates found; "
                    f"expected {expected_days} ({expected_days - len(unique_dates)} missing)"
                ),
            ))
        else:
            findings.append(Finding(
                "P3", "sequence_continuity", "devotionals", rel_path,
                Path(rel_path).stem,
                f"Found {len(unique_dates)} unique dates (expected {expected_days}) -- OK",
            ))

    # --- Commentary: coverage % per book file ---
    for rel_path, doc in all_files.get("commentaries", []):
        if doc.get("meta", {}).get("schema_type") != "commentary":
            continue
        entries = get_data_entries(doc)
        if not entries:
            continue

        book_osis = entries[0].get("book_osis", "")
        if not book_osis or book_osis not in vi_books:
            continue

        book_info = vi_books[book_osis]
        total_verses = sum(len(v) for v in book_info["verses"].values())

        covered = set()
        for entry in entries:
            vr_osis = entry.get("verse_range_osis", "")
            if vr_osis:
                # Use the start verse as coverage proxy
                covered.add(vr_osis.split("-")[0].strip())

        coverage_pct = (len(covered) / total_verses * 100) if total_verses > 0 else 0.0
        sev = "P2" if coverage_pct < 50 else "P3"
        findings.append(Finding(
            sev, "commentary_coverage", "commentaries", rel_path, book_osis,
            f"Commentary coverage: {coverage_pct:.1f}% ({len(covered)}/{total_verses} verses)",
        ))

    return findings


# ---------------------------------------------------------------------------
# Task 8 -- Provenance hash verification
# ---------------------------------------------------------------------------

def run_task_8_provenance_hash(all_files):
    """Verify source_hash for all files that have one."""
    findings = []

    # Pre-build index of raw source files for fast lookup
    raw_files_by_name = defaultdict(list)
    for fp in list(REPO_ROOT.glob("raw/**/*")) + list(REPO_ROOT.glob("sources/**/*")):
        if fp.is_file():
            raw_files_by_name[fp.name].append(fp)

    for cat, file_list in all_files.items():
        for rel_path, doc in file_list:
            prov = doc.get("meta", {}).get("provenance", {})
            stored_hash = prov.get("source_hash", "")
            if not stored_hash:
                continue

            if not stored_hash.startswith("sha256:"):
                findings.append(Finding(
                    "P2", "provenance_hash", cat, rel_path, "PROVENANCE",
                    f"Unrecognised hash format: {stored_hash[:60]}",
                ))
                continue

            expected_hex = stored_hash[7:]
            source_url = prov.get("source_url", "")
            url_filename = source_url.rstrip("/").split("/")[-1].split("?")[0] if source_url else ""

            candidates = raw_files_by_name.get(url_filename, [])
            if not candidates:
                findings.append(Finding(
                    "P3", "provenance_hash", cat, rel_path, "PROVENANCE",
                    f"Raw source file '{url_filename}' not found on disk -- cannot verify hash",
                ))
                continue

            match_path = candidates[0]
            try:
                sha256 = hashlib.sha256()
                with open(match_path, "rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        sha256.update(chunk)
                computed = sha256.hexdigest()
                if computed != expected_hex:
                    findings.append(Finding(
                        "P2", "provenance_hash", cat, rel_path, "PROVENANCE",
                        "Source hash mismatch -- source file may have been updated since parsing",
                        f"Stored: {expected_hex[:16]}...  Computed: {computed[:16]}...",
                    ))
                else:
                    findings.append(Finding(
                        "P3", "provenance_hash", cat, rel_path, "PROVENANCE",
                        f"Source hash verified OK: {match_path.name}",
                    ))
            except Exception as exc:
                logging.warning("Hash verification failed for %s: %s", match_path, exc)

    return findings


# ---------------------------------------------------------------------------
# Task 9 -- Sentinel spot-checks
# ---------------------------------------------------------------------------

def run_task_9_sentinel_checks(all_files):
    """Verify known-good entries against expected content."""
    findings = []

    # --- Westminster Shorter Catechism Q1 ---
    wsc_found = False
    for rel_path, doc in all_files.get("catechisms", []):
        if "westminster-shorter-catechism" not in rel_path:
            continue
        for entry in get_data_entries(doc):
            if str(entry.get("item_id", "")) != "1":
                continue
            wsc_found = True
            q = entry.get("question", "")
            a = entry.get("answer", "")
            issues = []
            if "chief end of man" not in q.lower():
                issues.append(f"Question wrong: '{q[:80]}'")
            if "glorify god" not in a.lower():
                issues.append("Answer missing 'glorify God'")
            if "enjoy him forever" not in a.lower() and "enjoy him for ever" not in a.lower():
                issues.append("Answer missing 'enjoy him forever'")
            if issues:
                findings.append(Finding(
                    "P1", "sentinel", "catechisms", rel_path, "WSC-Q1",
                    "WSC Q1 content wrong: " + "; ".join(issues),
                    f"Q: {q[:100]}  A: {a[:150]}",
                ))
            else:
                findings.append(Finding(
                    "P3", "sentinel", "catechisms", rel_path, "WSC-Q1",
                    "WSC Q1 verified OK",
                ))
            break
    if not wsc_found:
        findings.append(Finding("P1", "sentinel", "catechisms", "N/A", "WSC-Q1",
                                "Westminster Shorter Catechism Q1 not found"))

    # --- Heidelberg Catechism Q1 ---
    hei_found = False
    for rel_path, doc in all_files.get("catechisms", []):
        if "heidelberg" not in rel_path:
            continue
        for entry in get_data_entries(doc):
            if str(entry.get("item_id", "")) != "1":
                continue
            hei_found = True
            q = entry.get("question", "")
            a = entry.get("answer", "")
            issues = []
            if "only comfort" not in q.lower():
                issues.append(f"Question wrong: '{q[:80]}'")
            if "not my own" not in a.lower():
                issues.append("Answer missing 'not my own'")
            if issues:
                findings.append(Finding(
                    "P1", "sentinel", "catechisms", rel_path, "HC-Q1",
                    "Heidelberg Q1 content wrong: " + "; ".join(issues),
                    f"Q: {q[:100]}  A: {a[:150]}",
                ))
            else:
                findings.append(Finding(
                    "P3", "sentinel", "catechisms", rel_path, "HC-Q1",
                    "Heidelberg Catechism Q1 verified OK",
                ))
            break
    if not hei_found:
        findings.append(Finding("P1", "sentinel", "catechisms", "N/A", "HC-Q1",
                                "Heidelberg Catechism Q1 not found"))

    # --- Apostles' Creed ---
    creed_found = False
    for rel_path, doc in all_files.get("doctrinal-documents", []):
        if "apostles-creed" not in rel_path:
            continue
        creed_found = True
        data = doc.get("data", {})
        all_text = " ".join(
            unit.get("content", "")
            for unit in data.get("units", [])
            if isinstance(unit.get("content"), str)
        )
        required = [
            "I believe in God, the Father almighty",
            "the communion of saints",
            "the forgiveness of sins",
        ]
        for phrase in required:
            if phrase.lower() in all_text.lower():
                findings.append(Finding(
                    "P3", "sentinel", "doctrinal-documents", rel_path, "APOSTLES-CREED",
                    f"Apostles' Creed phrase verified: '{phrase}'",
                ))
            else:
                findings.append(Finding(
                    "P1", "sentinel", "doctrinal-documents", rel_path, "APOSTLES-CREED",
                    f"Apostles' Creed missing expected phrase: '{phrase}'",
                ))
        break
    if not creed_found:
        findings.append(Finding("P1", "sentinel", "doctrinal-documents", "N/A", "APOSTLES-CREED",
                                "Apostles' Creed file (apostles-creed.json) not found"))

    # --- Barnes on John 3:16 ---
    # Use the Barnes john.json file (Gospel of John, not 1 John / 2 John)
    barnes_found = False
    for rel_path, doc in all_files.get("commentaries", []):
        # Match data\commentaries\barnes\john.json specifically
        parts = Path(rel_path).parts
        if len(parts) < 4:
            continue
        if parts[2] != "barnes" or Path(rel_path).stem != "john":
            continue
        for entry in get_data_entries(doc):
            vr_osis = entry.get("verse_range_osis", "")
            # Exact match for John.3.16 -- avoid matching 1John.3.16
            if vr_osis != "John.3.16" and not vr_osis.startswith("John.3.16-"):
                continue
            barnes_found = True
            text = entry.get("commentary_text", "")
            wc = len(text.split()) if text else 0
            eid = entry.get("entry_id", "Barnes-John-3.16")
            if wc < 100:
                findings.append(Finding(
                    "P1", "sentinel", "commentaries", rel_path, eid,
                    f"Barnes John 3:16 has only {wc} words (expected >100)",
                ))
            elif "god so loved" not in text.lower():
                findings.append(Finding(
                    "P2", "sentinel", "commentaries", rel_path, eid,
                    "Barnes John 3:16 does not mention 'God so loved the world'",
                    f"First 200 chars: {text[:200]}",
                ))
            else:
                findings.append(Finding(
                    "P3", "sentinel", "commentaries", rel_path, eid,
                    f"Barnes John 3:16 verified OK ({wc} words, key phrase present)",
                ))
            break
    if not barnes_found:
        findings.append(Finding("P1", "sentinel", "commentaries", "N/A", "BARNES-JOHN-3.16",
                                "Barnes John 3:16 entry not found in barnes/john.json"))

    return findings


# ---------------------------------------------------------------------------
# Task 10 -- Token count consistency spot-check
# ---------------------------------------------------------------------------

def run_task_10_token_counts(all_files):
    """Spot-check stored token_count values against tiktoken recomputation."""
    findings = []

    try:
        import tiktoken  # noqa: PLC0415
        enc = tiktoken.get_encoding("cl100k_base")
    except ImportError:
        findings.append(Finding(
            "P3", "token_count", "(all)", "(all)", "SKIPPED",
            "Task 10 SKIPPED: tiktoken not installed. Run: pip install tiktoken",
        ))
        return findings

    # Collect all entries with an integer token_count field
    candidates = []
    for cat, file_list in all_files.items():
        for rel_path, doc in file_list:
            schema_type = doc.get("meta", {}).get("schema_type")
            if schema_type is None or schema_type in ("structured_text", "doctrinal_document"):
                continue
            for entry in get_data_entries(doc):
                if isinstance(entry.get("token_count"), int):
                    candidates.append((cat, rel_path, schema_type, entry))

    if not candidates:
        findings.append(Finding("P3", "token_count", "(all)", "(all)", "SKIPPED",
                                "No entries with integer token_count field found"))
        return findings

    # Sample every Nth entry to get approximately 50 samples
    step = max(1, len(candidates) // 50)
    sample = candidates[::step][:50]

    checked = 0
    for cat, rel_path, schema_type, entry in sample:
        text = get_entry_text(entry, schema_type)
        if not text:
            continue
        stored = entry.get("token_count", 0)
        if not stored:
            continue
        try:
            computed = len(enc.encode(text))
        except Exception as exc:
            logging.warning("tiktoken encode failed: %s", exc)
            continue

        checked += 1
        discrepancy_pct = abs(computed - stored) / stored * 100 if stored > 0 else 0.0
        eid = get_entry_id(entry, schema_type)

        if discrepancy_pct > 10:
            findings.append(Finding(
                "P1", "token_count", cat, rel_path, eid,
                (
                    f"Token count discrepancy >{10}%: "
                    f"stored={stored}, computed={computed} ({discrepancy_pct:.1f}%)"
                ),
                f"Text snippet: {text[:80]}",
            ))
        elif discrepancy_pct > 2:
            findings.append(Finding(
                "P2", "token_count", cat, rel_path, eid,
                (
                    f"Token count discrepancy >{2}%: "
                    f"stored={stored}, computed={computed} ({discrepancy_pct:.1f}%)"
                ),
                f"Text snippet: {text[:80]}",
            ))

    findings.append(Finding(
        "P3", "token_count", "(all)", "(all)", "SUMMARY",
        (
            f"Token count spot-check complete: {checked}/{len(sample)} entries checked "
            f"(sample of {len(candidates)} total candidates, 1-in-{step} rate)"
        ),
    ))

    return findings


# ---------------------------------------------------------------------------
# Report writing
# ---------------------------------------------------------------------------

def write_markdown_report(findings, files_scanned, entries_scanned, generated_at):
    """Write the human-readable Markdown report to REPORT_MD_PATH."""
    p1 = [f for f in findings if f.severity == "P1"]
    p2 = [f for f in findings if f.severity == "P2"]
    p3 = [f for f in findings if f.severity == "P3"]

    lines = [
        "# Data Accuracy Report",
        f"Generated: {generated_at}",
        "Script: build/tools/audit_data_accuracy.py",
        f"Files scanned: {files_scanned}",
        f"Entries scanned: {entries_scanned}",
        "",
        "## Summary",
        "| Severity | Count |",
        "|---|---|",
        f"| P1 -- Data wrong or missing | {len(p1)} |",
        f"| P2 -- Suspicious, needs review | {len(p2)} |",
        f"| P3 -- Informational | {len(p3)} |",
        "",
    ]

    def section(title, finding_list):
        if not finding_list:
            return [f"## {title}", "", "No findings.", ""]
        out = [f"## {title}", ""]
        by_check = defaultdict(lambda: defaultdict(list))
        for fnd in finding_list:
            by_check[fnd.check][fnd.category].append(fnd)
        for check in sorted(by_check):
            out.append(f"### {check}")
            for cat in sorted(by_check[check]):
                out.append(f"**{cat}**")
                for fnd in by_check[check][cat]:
                    out.append(f"- `{fnd.file_path}` | `{fnd.entry_id}` | {fnd.message}")
                    if fnd.detail:
                        out.append(f"  - {fnd.detail}")
            out.append("")
        return out

    lines.extend(section("P1 Findings", p1))
    lines.extend(section("P2 Findings", p2))
    lines.extend(section("P3 / Informational", p3))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(REPORT_MD_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    logging.info("Markdown report written: %s", REPORT_MD_PATH)


def write_json_report(findings, files_scanned, entries_scanned, generated_at):
    """Write the machine-readable JSON report to REPORT_JSON_PATH."""
    p1 = [f for f in findings if f.severity == "P1"]
    p2 = [f for f in findings if f.severity == "P2"]
    p3 = [f for f in findings if f.severity == "P3"]

    report = {
        "generated": generated_at,
        "script": "build/tools/audit_data_accuracy.py",
        "files_scanned": files_scanned,
        "entries_scanned": entries_scanned,
        "counts": {
            "P1": len(p1),
            "P2": len(p2),
            "P3": len(p3),
            "total": len(findings),
        },
        "findings": {
            "P1": [f.to_dict() for f in p1],
            "P2": [f.to_dict() for f in p2],
            "P3": [f.to_dict() for f in p3],
        },
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(REPORT_JSON_PATH, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    logging.info("JSON report written: %s", REPORT_JSON_PATH)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run data accuracy checks across OCD data files."
    )
    parser.add_argument(
        "--category",
        metavar="NAME",
        help="Audit one category only (e.g. bible-text, commentaries, catechisms)",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(str(LOG_PATH), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    start_time = datetime.now()  # standards: local timing
    generated_at = start_time.strftime("%Y-%m-%d %H:%M:%S")
    logging.info("=== audit_data_accuracy.py starting ===")
    logging.info("REPO_ROOT: %s", REPO_ROOT)

    categories = [args.category] if args.category else None

    # --- Load all files ---
    print("Loading files...")
    all_files = load_all_files(categories)
    files_scanned = sum(len(v) for v in all_files.values())
    entries_scanned = sum(
        len(get_data_entries(doc))
        for file_list in all_files.values()
        for _, doc in file_list
    )
    print(f"Loaded {files_scanned} file(s) covering {entries_scanned} entries.")

    # --- Load canonical references ---
    print("Loading canonical references...")
    try:
        with open(VERSE_INDEX_PATH, encoding="utf-8") as fh:
            verse_index = json.load(fh)
        logging.info("Loaded verse_index.json (%d books)", len(verse_index.get("books", {})))
    except Exception as exc:
        logging.error(
            "Failed to load verse_index.json: %s -- "
            "Run 'py -3 build/scripts/build_kjv_verse_index.py' to rebuild it. "
            "Bible-text entry count and verse continuity checks will be skipped.",
            exc,
        )
        verse_index = {}

    try:
        with open(DISPUTED_VERSES_PATH, encoding="utf-8") as fh:
            disputed_verses = json.load(fh)
        logging.info("Loaded disputed_verses.json (%d total)", disputed_verses.get("total_count", 0))
    except Exception as exc:
        logging.error(
            "Failed to load disputed_verses.json: %s -- "
            "Run 'py -3 build/scripts/generate_disputed_verses.py' to rebuild it. "
            "BSB vs KJV cross-check will use 0 manuscript omissions.",
            exc,
        )
        disputed_verses = {}

    # --- Run checks (task 6 is last as it's the most expensive) ---
    all_findings = []

    print("Task 2: Entry count verification...")
    all_findings.extend(run_task_2_entry_counts(all_files, verse_index, disputed_verses))

    print("Task 3: Duplicate entry_id detection...")
    all_findings.extend(run_task_3_duplicate_ids(all_files))

    print("Task 4: Word count outlier detection...")
    all_findings.extend(run_task_4_word_count_outliers(all_files))

    print("Task 5a: OCR artifact detection...")
    all_findings.extend(run_task_5a_ocr_artifacts(all_files))

    print("Task 5b: Encoding and Unicode consistency...")
    all_findings.extend(run_task_5b_encoding(all_files))

    print("Task 7: Sequence continuity (catechisms, devotionals, commentary coverage)...")
    all_findings.extend(run_task_7_sequence_continuity(all_files, verse_index))

    print("Task 8: Provenance hash verification...")
    all_findings.extend(run_task_8_provenance_hash(all_files))

    print("Task 9: Sentinel spot-checks...")
    all_findings.extend(run_task_9_sentinel_checks(all_files))

    print("Task 10: Token count consistency spot-check...")
    all_findings.extend(run_task_10_token_counts(all_files))

    print("Task 6: Bible text verse continuity (running last -- most expensive)...")
    all_findings.extend(run_task_6_verse_continuity(all_files, verse_index))

    # --- Summary ---
    p1_count = sum(1 for f in all_findings if f.severity == "P1")
    p2_count = sum(1 for f in all_findings if f.severity == "P2")
    p3_count = sum(1 for f in all_findings if f.severity == "P3")
    elapsed = (datetime.now() - start_time).total_seconds()  # standards: local timing

    print(f"\n=== Audit complete ({elapsed:.1f}s) ===")
    print(f"Files scanned:      {files_scanned}")
    print(f"Entries scanned:    {entries_scanned}")
    print(f"P1 (wrong/missing): {p1_count}")
    print(f"P2 (suspicious):    {p2_count}")
    print(f"P3 (informational): {p3_count}")
    print(f"Total findings:     {len(all_findings)}")

    # --- Write reports ---
    print(f"\nWriting reports to {OUTPUT_DIR}...")
    write_markdown_report(all_findings, files_scanned, entries_scanned, generated_at)
    write_json_report(all_findings, files_scanned, entries_scanned, generated_at)
    print(f"MD  report: {REPORT_MD_PATH}")
    print(f"JSON report: {REPORT_JSON_PATH}")

    logging.info("=== audit_data_accuracy.py done ===")
    sys.exit(0)


if __name__ == "__main__":
    main()
