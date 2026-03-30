"""gutenberg_catechisms.py
Parse Project Gutenberg catechism texts into catechism_qa schema.

Sources (raw/gutenberg/):
  pg1670.txt  -- Luther's Small Catechism (R. E. Smith / Project Wittenberg 2004)
  pg14551.txt -- Baltimore Catechism No. 1 (Third Plenary Council 1885)
  pg14552.txt -- Baltimore Catechism No. 2 (Third Plenary Council 1885)
  pg14553.txt -- Baltimore Catechism No. 3 (Third Plenary Council 1885)

Outputs (data/catechisms/):
  luthers-small-catechism.json
  baltimore-catechism-no-1.json
  baltimore-catechism-no-2.json
  baltimore-catechism-no-3.json

Schema: catechism_qa (schemas/v1/catechism_qa.schema.json)

Usage:
    py -3 build/parsers/gutenberg_catechisms.py
    py -3 build/parsers/gutenberg_catechisms.py --dry-run
    py -3 build/parsers/gutenberg_catechisms.py --catechism luther_small
    py -3 build/parsers/gutenberg_catechisms.py --catechism baltimore_1
"""

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

RAW_DIR = REPO_ROOT / "raw" / "gutenberg"
OUTPUT_DIR = REPO_ROOT / "data" / "catechisms"
LOG_FILE = Path(__file__).resolve().parent / "gutenberg_catechisms.log"

SCHEMA_VERSION = "2.1.0"
PROCESSING_SCRIPT_VERSION = "build/parsers/gutenberg_catechisms.py@v1.0.0"
DOWNLOAD_DATE = "2026-03-30"

# PG header/footer markers
PG_START_RE = re.compile(r'\*\*\*\s*START OF', re.IGNORECASE)
PG_END_RE = re.compile(r'\*\*\*\s*END OF', re.IGNORECASE)

# Catechism configs: (pg_id, output_filename, document_id, metadata_dict)
CATECHISM_CONFIGS = {
    "luther_small": {
        "pg_id": 1670,
        "output_file": "luthers-small-catechism.json",
        "document_id": "luthers-small-catechism",
        "meta": {
            "id": "luthers-small-catechism",
            "title": "Luther's Small Catechism",
            "author": "Martin Luther",
            "author_birth_year": 1483,
            "author_death_year": 1546,
            "contributors": ["Robert E. Smith (translator, 1994; revised 2002, 2004)"],
            "original_publication_year": 1529,
            "language": "en",
            "original_language": "de",
            "tradition": ["lutheran", "confessional"],
            "tradition_notes": (
                "Luther's Small Catechism (1529) was composed as a brief instructional guide "
                "for pastors to teach the laity. This Project Gutenberg edition uses the "
                "Robert E. Smith translation (Project Wittenberg, 2004), derived from the "
                "Triglot Concordia (Concordia Publishing House, 1921). The original CPH 1921 "
                "Triglot text is public domain; this Project Wittenberg translation was "
                "explicitly placed in the public domain by Smith."
            ),
            "era": "reformation",
            "audience": "lay",
            "license": "public-domain",
            "schema_type": "catechism_qa",
            "schema_version": SCHEMA_VERSION,
            "completeness": "full",  # overridden to "partial" at runtime if any entries have null answers
        },
        "source_url": "http://www.gutenberg.org/cache/epub/1670/pg1670.txt",
        "source_edition": "Project Wittenberg / Project Gutenberg digitization (R. E. Smith trans., 2004)",
    },
    "baltimore_1": {
        "pg_id": 14551,
        "output_file": "baltimore-catechism-no-1.json",
        "document_id": "baltimore-catechism-no-1",
        "catechism_num": "1",
        "meta": {
            "id": "baltimore-catechism-no-1",
            "title": "Baltimore Catechism No. 1",
            "author": "Third Plenary Council of Baltimore",
            "author_birth_year": None,
            "author_death_year": None,
            "contributors": [],
            "original_publication_year": 1885,
            "language": "en",
            "original_language": "en",
            "tradition": ["catholic"],
            "tradition_notes": (
                "Issued by the Third Plenary Council of Baltimore (1884, published 1885). "
                "No. 1 is the first communion edition for children. The Baltimore Catechisms "
                "were the standard Catholic catechism in the United States until the 1960s."
            ),
            "era": "modern",
            "audience": "children",
            "license": "public-domain",
            "schema_type": "catechism_qa",
            "schema_version": SCHEMA_VERSION,
            "completeness": "full",  # overridden to "partial" at runtime if any entries have null answers
        },
        "source_url": "http://www.gutenberg.org/cache/epub/14551/pg14551.txt",
        "source_edition": "Project Gutenberg digitization of the 1885 edition",
    },
    "baltimore_2": {
        "pg_id": 14552,
        "output_file": "baltimore-catechism-no-2.json",
        "document_id": "baltimore-catechism-no-2",
        "catechism_num": "2",
        "meta": {
            "id": "baltimore-catechism-no-2",
            "title": "Baltimore Catechism No. 2",
            "author": "Third Plenary Council of Baltimore",
            "author_birth_year": None,
            "author_death_year": None,
            "contributors": [],
            "original_publication_year": 1885,
            "language": "en",
            "original_language": "en",
            "tradition": ["catholic"],
            "tradition_notes": (
                "Issued by the Third Plenary Council of Baltimore (1884, published 1885). "
                "No. 2 is the confirmation edition. Questions are numbered to agree with "
                "Kinkead's Explanation of the Baltimore Catechism."
            ),
            "era": "modern",
            "audience": "lay",
            "license": "public-domain",
            "schema_type": "catechism_qa",
            "schema_version": SCHEMA_VERSION,
            "completeness": "full",  # overridden to "partial" at runtime if any entries have null answers
        },
        "source_url": "http://www.gutenberg.org/cache/epub/14552/pg14552.txt",
        "source_edition": "Project Gutenberg digitization of the 1885 edition",
    },
    "baltimore_3": {
        "pg_id": 14553,
        "output_file": "baltimore-catechism-no-3.json",
        "document_id": "baltimore-catechism-no-3",
        "catechism_num": "3",
        "meta": {
            "id": "baltimore-catechism-no-3",
            "title": "Baltimore Catechism No. 3",
            "author": "Third Plenary Council of Baltimore",
            "author_birth_year": None,
            "author_death_year": None,
            "contributors": ["Rev. Thomas L. Kinkead (supplementer)"],
            "original_publication_year": 1885,
            "language": "en",
            "original_language": "en",
            "tradition": ["catholic"],
            "tradition_notes": (
                "Issued by the Third Plenary Council of Baltimore (1884, published 1885). "
                "No. 3 is the post-confirmation edition, supplemented by Rev. Thomas L. "
                "Kinkead. In accordance with the new canon law."
            ),
            "era": "modern",
            "audience": "lay",
            "license": "public-domain",
            "schema_type": "catechism_qa",
            "schema_version": SCHEMA_VERSION,
            "completeness": "full",  # overridden to "partial" at runtime if any entries have null answers
        },
        "source_url": "http://www.gutenberg.org/cache/epub/14553/pg14553.txt",
        "source_edition": "Project Gutenberg digitization of the 1885 edition (Kinkead supplement)",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(message: str, log_lines: list) -> None:
    """Print to console (ASCII only) and append to log list."""
    # Replace non-ASCII characters to avoid cp1252 crash on Windows console
    safe = message.encode("ascii", errors="replace").decode("ascii")
    print(safe)
    log_lines.append(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{h}"


def strip_pg_wrapper(text: str) -> list:
    """Strip Project Gutenberg header and footer. Returns body lines."""
    lines = text.splitlines()
    start_idx = None
    end_idx = None
    for i, l in enumerate(lines):
        if PG_START_RE.search(l) and start_idx is None:
            start_idx = i
        if PG_END_RE.search(l):
            end_idx = i
            break
    if start_idx is None or end_idx is None:
        raise ValueError("Could not find PG start/end markers")
    return lines[start_idx + 1 : end_idx]


def normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces and strip leading/trailing whitespace."""
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Luther Small Catechism parser
# ---------------------------------------------------------------------------

# Part headings: "I. The Ten Commandments", "II. The Creed", etc.
_LSC_PART_RE = re.compile(r"^(I{1,3}|IV|V|VI)\.\s+(.+)$")

# Section headings within parts
_LSC_SECTION_RES = [
    re.compile(r"^The\s+(First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth)\s+(Commandment|Article|Request|Petition)\.?$"),
    re.compile(r"^(Introduction|The Conclusion to the Commandments|The Conclusion)$"),
    re.compile(r"^Appendix\s+(I{1,3}|IV|V)"),
    re.compile(r"^(Morning Devotions|Evening Devotions|The Blessing|Thanking God)$"),
    re.compile(r"^The Simple Way a Father Should"),
]

# Question-like lines: lines ending with "?" that are not answers
# We'll check structurally: questions come before answers in the pattern.
_LSC_QUESTION_RE = re.compile(r".+\?$")

# Lines that always mark the start of a new structural unit (not content)
_LSC_SKIP_PREFIXES = [
    "Translation by",
    "Note: This version",
    "St. Louis: Concordia",
    "Triglot Concordia:",
    "Fort Wayne, Indiana",
    "This text was translated",
    "Please direct any comments",
    "Surface Mail:",
    "USA Phone:",
    "Email:",
    "________",
]


def _is_lsc_section_heading(line: str) -> bool:
    stripped = line.strip()
    return any(p.match(stripped) for p in _LSC_SECTION_RES)


def _is_lsc_skip_line(line: str) -> bool:
    stripped = line.strip()
    return any(stripped.startswith(prefix) for prefix in _LSC_SKIP_PREFIXES)


def parse_luther_small(body_lines: list, doc_id: str, log_lines: list) -> tuple:
    """Parse Luther's Small Catechism into catechism_qa entries.

    The structure is:
      Part (I-VI) -> Section (e.g., The First Commandment) -> Q&A pairs

    Q&A pairs have a leading 'article text' (the commandment, creed article, etc.)
    followed by one or more question-answer exchanges.

    Returns (entries, parse_errors).
    """
    entries = []
    parse_errors = []
    sort_key = 0

    current_part = None
    current_section = None
    # Article text context: the scripture/creed text preceding a question
    article_lines = []

    # Remove blank lines for sequential processing; track original position
    non_empty = [(i, l.rstrip()) for i, l in enumerate(body_lines) if l.strip()]

    idx = 0

    # Skip translator intro before Part I
    while idx < len(non_empty):
        _, l = non_empty[idx]
        if _LSC_PART_RE.match(l.strip()):
            break
        idx += 1

    while idx < len(non_empty):
        _, l = non_empty[idx]
        stripped = l.strip()

        # Skip known boilerplate lines
        if _is_lsc_skip_line(stripped):
            idx += 1
            continue

        # Part heading
        if _LSC_PART_RE.match(stripped):
            current_part = stripped
            current_section = None
            article_lines = []
            idx += 1
            continue

        # Section heading
        if _is_lsc_section_heading(stripped):
            current_section = stripped
            article_lines = []
            idx += 1
            continue

        # Subtitle under part/section (e.g., "The Simple Way a Father Should...")
        # -- already caught by _LSC_SECTION_RES

        # Question
        if _LSC_QUESTION_RE.match(stripped) and stripped.endswith("?"):
            question = stripped

            # Collect answer lines (everything up to next question, section, or part)
            answer_parts = []
            idx += 1
            while idx < len(non_empty):
                _, next_l = non_empty[idx]
                next_stripped = next_l.strip()

                # Stop conditions
                if (
                    _LSC_PART_RE.match(next_stripped)
                    or _is_lsc_section_heading(next_stripped)
                    or (
                        _LSC_QUESTION_RE.match(next_stripped)
                        and next_stripped.endswith("?")
                        and len(next_stripped) < 200
                    )
                    or _is_lsc_skip_line(next_stripped)
                ):
                    break
                if next_stripped:
                    answer_parts.append(next_stripped)
                idx += 1

            answer = normalize_whitespace(" ".join(answer_parts))

            if not answer:
                msg = f"WARNING: empty answer for question '{question[:60]}'"
                log(msg, log_lines)
                parse_errors.append(msg)

            # Build group string from part + section + article context
            group_parts = []
            if current_part:
                group_parts.append(current_part)
            if current_section:
                group_parts.append(current_section)
            article_ctx = normalize_whitespace(" ".join(article_lines))
            if article_ctx and len(article_ctx) < 200:
                group_parts.append(article_ctx)

            sort_key += 1
            entries.append(
                {
                    "document_id": doc_id,
                    "item_id": str(sort_key),
                    "sort_key": sort_key,
                    "question": question,
                    "answer": answer,
                    "answer_with_proofs": None,
                    "proofs": [],
                    "group": " -- ".join(group_parts) if group_parts else None,
                    "sub_questions": None,
                }
            )
            # Reset article context after consuming a Q&A
            article_lines = []
            continue

        # Not a question, not a heading: article/scripture text
        if stripped:
            article_lines.append(stripped)
        idx += 1

    return entries, parse_errors


# ---------------------------------------------------------------------------
# Baltimore Catechism parser
# ---------------------------------------------------------------------------

# "LESSON FIRST", "LESSON FIRST." -- Baltimore #3 uses trailing period
_BALT_LESSON_RE = re.compile(
    r"^LESSON\s+(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|"
    r"ELEVENTH|TWELFTH|THIRTEENTH|FOURTEENTH|FIFTEENTH|SIXTEENTH|SEVENTEENTH|"
    r"EIGHTEENTH|NINETEENTH|TWENTIETH|TWENTY[\w\s-]*)\.?$",
    re.IGNORECASE,
)

# Format A (Baltimore #1, #2): "N. Q. Question text"
_BALT_Q_A_RE = re.compile(r"^(\d+)\.\s+Q\.\s+(.+)$")
# Format B (Baltimore #3): "Q. N. Question text"
_BALT_Q_B_RE = re.compile(r"^Q\.\s+(\d+)\.\s+(.+)$")


def _match_balt_q(line: str):
    """Try both Q formats. Returns (num_str, text) or None."""
    m = _BALT_Q_A_RE.match(line)
    if m:
        return m.group(1), m.group(2)
    m = _BALT_Q_B_RE.match(line)
    if m:
        return m.group(1), m.group(2)
    return None


# Keep backward-compat alias used in the parser body
_BALT_Q_RE = _BALT_Q_A_RE  # used only for stop-condition checks below (handles both via _match_balt_q)

# "A. Answer text"
_BALT_A_RE = re.compile(r"^A\.\s+(.+)$")

# Lines in the preamble/prayers section to skip before LESSON FIRST
# We skip everything before the first LESSON heading


def parse_baltimore(body_lines: list, catechism_num: str, doc_id: str, log_lines: list) -> tuple:
    """Parse a Baltimore Catechism (any number) into catechism_qa entries.

    Format:
      LESSON FIRST
      ON THE END OF MAN
      1. Q. Who made the world?
      A. God made the world.

    Multi-line questions and answers are handled by collecting continuation lines.

    Returns (entries, parse_errors).
    """
    entries = []
    parse_errors = []
    doc_sort_key = 0  # Monotonically incrementing; Q numbers can be out of order in source

    current_lesson = None
    reached_catechism_section = False  # True once we hit first LESSON heading

    # Work on stripped, non-empty lines to simplify look-ahead
    lines = body_lines

    i = 0
    # Find the start of the catechism proper (first LESSON heading)
    while i < len(lines):
        ls = lines[i].strip()
        if _BALT_LESSON_RE.match(ls):
            reached_catechism_section = True
            break
        i += 1

    if not reached_catechism_section:
        msg = f"ERROR: No LESSON heading found in Baltimore #{catechism_num}"
        log(msg, log_lines)
        return [], [msg]

    while i < len(lines):
        ls = lines[i].strip()

        # Skip blank lines
        if not ls:
            i += 1
            continue

        # LESSON heading (e.g., "LESSON FIRST")
        if _BALT_LESSON_RE.match(ls):
            lesson_name = ls
            # Next non-empty line is the topic title (e.g., "ON THE END OF MAN")
            # unless it's another question or lesson
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                topic_candidate = lines[j].strip()
                if (
                    topic_candidate
                    and not _BALT_Q_RE.match(topic_candidate)
                    and not _BALT_LESSON_RE.match(topic_candidate)
                    and topic_candidate.isupper()
                    and len(topic_candidate) < 100
                ):
                    lesson_name = lesson_name + ": " + topic_candidate
                    i = j + 1
                else:
                    i += 1
            else:
                i += 1
            current_lesson = lesson_name
            continue

        # Question line: "N. Q. text" (formats A or B)
        q_match = _match_balt_q(ls)
        if q_match:
            q_num_str, q_text = q_match
            q_text = q_text.strip()
            i += 1

            # Collect question continuation lines (before "A. ...")
            while i < len(lines):
                next_ls = lines[i].strip()
                if not next_ls:
                    # blank line ends question continuation
                    break
                if _BALT_A_RE.match(next_ls) or _match_balt_q(next_ls) or _BALT_LESSON_RE.match(next_ls):
                    break
                q_text += " " + next_ls
                i += 1

            q_text = normalize_whitespace(q_text)

            # Answer line: "A. text"
            a_text = ""
            if i < len(lines) and _BALT_A_RE.match(lines[i].strip()):
                a_text = _BALT_A_RE.match(lines[i].strip()).group(1).strip()
                i += 1
                # Collect answer continuation lines
                while i < len(lines):
                    next_ls = lines[i].strip()
                    if not next_ls:
                        break
                    if _match_balt_q(next_ls) or _BALT_LESSON_RE.match(next_ls):
                        break
                    # Second A. line (some editions repeat A.) -- unlikely but guard
                    if _BALT_A_RE.match(next_ls):
                        break
                    a_text += " " + next_ls
                    i += 1
                a_text = normalize_whitespace(a_text)
            else:
                msg = f"WARNING: Q.{q_num_str} has no answer in Baltimore #{catechism_num}"
                log(msg, log_lines)
                parse_errors.append(msg)
                a_text = None  # Schema requires null (not "") for source gaps

            doc_sort_key += 1
            entries.append(
                {
                    "document_id": doc_id,
                    "item_id": q_num_str,
                    "sort_key": doc_sort_key,
                    "question": q_text,
                    "answer": a_text,
                    "answer_with_proofs": None,
                    "proofs": [],
                    "group": current_lesson,
                    "sub_questions": None,
                }
            )
            continue

        # Non-heading, non-Q line -- could be section text, hymn, prayer, etc.
        # Skip silently (these are the prayers/liturgical texts between catechism sections)
        i += 1

    return entries, parse_errors


# ---------------------------------------------------------------------------
# Output builder
# ---------------------------------------------------------------------------


def build_output(cfg: dict, entries: list, source_hash: str, has_gaps: bool = False) -> dict:
    """Wrap parsed entries in the meta envelope."""
    processing_date = datetime.today().strftime("%Y-%m-%d")
    meta = dict(cfg["meta"])  # shallow copy
    if has_gaps:
        meta["completeness"] = "partial"

    meta["provenance"] = {
        "source_url": cfg["source_url"],
        "source_format": "plain text (UTF-8)",
        "source_edition": cfg["source_edition"],
        "download_date": DOWNLOAD_DATE,
        "source_hash": source_hash,
        "processing_method": "automated",
        "processing_script_version": PROCESSING_SCRIPT_VERSION,
        "processing_date": processing_date,
        "notes": None,
    }

    return {"meta": meta, "data": entries}


# ---------------------------------------------------------------------------
# Quality stats
# ---------------------------------------------------------------------------


def print_quality_stats(entries: list, label: str, log_lines: list) -> None:
    """Report completeness metrics per CODING_DEFAULTS.md Rule 43."""
    total = len(entries)
    if total == 0:
        log(f"  {label}: 0 entries", log_lines)
        return

    empty_q = sum(1 for e in entries if not (e.get("question") or "").strip())
    empty_a = sum(1 for e in entries if not (e.get("answer") or "").strip())
    with_group = sum(1 for e in entries if e.get("group"))

    q_words = [len(e["question"].split()) for e in entries if e.get("question")]
    a_words = [len(e["answer"].split()) for e in entries if e.get("answer")]

    q_words.sort()
    a_words.sort()

    def median(lst):
        if not lst:
            return 0
        mid = len(lst) // 2
        return lst[mid] if len(lst) % 2 else (lst[mid - 1] + lst[mid]) // 2

    log(f"  {label}: {total} entries", log_lines)
    log(f"    Empty questions: {empty_q} ({100*empty_q//total}%)", log_lines)
    log(f"    Empty answers:   {empty_a} ({100*empty_a//total}%)", log_lines)
    log(f"    With group:      {with_group} ({100*with_group//total}%)", log_lines)
    if q_words:
        log(f"    Q words: min={q_words[0]}, median={median(q_words)}, max={q_words[-1]}", log_lines)
    if a_words:
        log(f"    A words: min={a_words[0]}, median={median(a_words)}, max={a_words[-1]}", log_lines)


# ---------------------------------------------------------------------------
# Per-catechism runner
# ---------------------------------------------------------------------------


def run_catechism(key: str, dry_run: bool, log_lines: list) -> bool:
    """Parse one catechism and write output. Returns True on success."""
    cfg = CATECHISM_CONFIGS[key]
    pg_id = cfg["pg_id"]
    source_path = RAW_DIR / f"pg{pg_id}.txt"
    output_path = OUTPUT_DIR / cfg["output_file"]
    doc_id = cfg["document_id"]

    log(f"\n--- {doc_id} (PG#{pg_id}) ---", log_lines)
    log(f"  Source: {source_path}", log_lines)
    log(f"  Output: {output_path}", log_lines)

    if not source_path.exists():
        log(f"  ERROR: Source file not found. Run download_gutenberg.py first.", log_lines)
        return False

    source_hash = sha256_file(source_path)
    log(f"  Source hash: {source_hash}", log_lines)

    text = source_path.read_text(encoding="utf-8")
    try:
        body_lines = strip_pg_wrapper(text)
    except ValueError as exc:
        log(f"  ERROR: {exc}", log_lines)
        return False

    log(f"  Body lines (after PG strip): {len(body_lines)}", log_lines)

    # Parse
    if key == "luther_small":
        entries, parse_errors = parse_luther_small(body_lines, doc_id, log_lines)
    else:
        catechism_num = cfg["catechism_num"]
        entries, parse_errors = parse_baltimore(body_lines, catechism_num, doc_id, log_lines)

    log(f"  Parsed {len(entries)} Q&A entries ({len(parse_errors)} parse errors)", log_lines)
    print_quality_stats(entries, doc_id, log_lines)

    if parse_errors:
        for err in parse_errors[:5]:
            log(f"  {err}", log_lines)
        if len(parse_errors) > 5:
            log(f"  ... and {len(parse_errors) - 5} more parse errors", log_lines)

    if not entries:
        log("  ERROR: No entries parsed -- aborting output", log_lines)
        return False

    # Build output document
    has_gaps = any(e.get("answer") is None for e in entries)
    output = build_output(cfg, entries, source_hash, has_gaps=has_gaps)

    if dry_run:
        log("  DRY RUN -- first 3 entries:", log_lines)
        for entry in entries[:3]:
            q_preview = entry["question"][:70]
            a_preview = (entry["answer"] or "")[:70]
            log(f"    [{entry['item_id']}] Q: {q_preview}...", log_lines)
            log(f"         A: {a_preview}...", log_lines)
        log("  DRY RUN -- no files written", log_lines)
        return True

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log(f"  Written: {output_path}", log_lines)
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse PG catechism texts to catechism_qa JSON")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report without writing output")
    parser.add_argument(
        "--catechism",
        choices=list(CATECHISM_CONFIGS.keys()),
        help="Parse one catechism only (default: all)",
    )
    args = parser.parse_args()

    log_lines = []
    start_time = time.time()
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log(f"[{run_ts}] gutenberg_catechisms -- {'DRY RUN' if args.dry_run else 'LIVE RUN'}", log_lines)

    keys_to_run = [args.catechism] if args.catechism else list(CATECHISM_CONFIGS.keys())
    log(f"Catechisms to parse: {', '.join(keys_to_run)}", log_lines)

    successes = 0
    failures = 0
    for key in keys_to_run:
        ok = run_catechism(key, args.dry_run, log_lines)
        if ok:
            successes += 1
        else:
            failures += 1

    elapsed = time.time() - start_time
    log(f"\nDone -- {successes} succeeded, {failures} failed, {elapsed:.1f}s", log_lines)

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n\n")

    if failures > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
