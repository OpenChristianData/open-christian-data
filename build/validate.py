"""validate.py
Validate commentary JSON files against the schema and run structural checks.

Checks:
  1. JSON Schema conformance
  2. Entry ID uniqueness within a file
  3. OSIS verse reference format (basic pattern check)
  4. Word count sanity (> 0)
  5. verse_range parses correctly (start <= end)
  6. book_number matches book_osis

Usage:
    py -3 build/validate.py data/commentaries/matthew-henry/ezekiel.json
    py -3 build/validate.py --all
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"

# OSIS reference pattern: Book.Chapter.Verse[-Book.Chapter.Verse]
OSIS_REF_PATTERN = re.compile(
    r"^[A-Z][a-zA-Z0-9]+\.\d+\.\d+(-[A-Z][a-zA-Z0-9]+\.\d+\.\d+)?$"
)

KNOWN_BOOK_NUMBERS = {
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

VALID_SUMMARY_STATUSES = {
    "withheld",
    "ai-generated-unreviewed",
    "ai-generated-spot-checked",
    "ai-generated-seminary-reviewed",
    "human-written",
}


def check_osis_ref(ref: str) -> bool:
    return bool(OSIS_REF_PATTERN.match(ref))


def parse_verse_range(verse_range: str) -> tuple:
    """Parse '1', '1-3' etc. Returns (start, end) or raises ValueError."""
    if "-" in verse_range:
        parts = verse_range.split("-", 1)
        return int(parts[0]), int(parts[1])
    return int(verse_range), int(verse_range)


def validate_file(path: Path) -> tuple:
    """Validate a single commentary JSON file. Returns (errors, warnings)."""
    errors = []
    warnings = []

    # Try JSON Schema validation if jsonschema is available
    schema_path = SCHEMA_DIR / "commentary.schema.json"
    jsonschema_available = False
    try:
        import jsonschema  # type: ignore
        jsonschema_available = True
    except ImportError:
        warnings.append("jsonschema not installed — skipping schema validation. Run: pip install jsonschema")

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        errors.append(f"Invalid JSON: {exc}")
        return errors, warnings
    except OSError as exc:
        errors.append(f"Cannot read file: {exc}")
        return errors, warnings

    # JSON Schema check
    if jsonschema_available and schema_path.exists():
        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)
        try:
            validator = jsonschema.Draft202012Validator(schema)
            for error in validator.iter_errors(data):
                errors.append(f"Schema: {error.json_path} — {error.message}")
        except Exception as exc:
            warnings.append(f"Schema validation error: {exc}")

    # Structural checks (run even without jsonschema)
    if not isinstance(data, dict):
        errors.append("Root must be an object")
        return errors, warnings

    if "meta" not in data:
        errors.append("Missing 'meta' key")
    if "data" not in data:
        errors.append("Missing 'data' key")
        return errors, warnings

    entries = data.get("data", [])
    if not isinstance(entries, list):
        errors.append("'data' must be an array")
        return errors, warnings

    if len(entries) == 0:
        errors.append("'data' array is empty")

    # Entry-level checks
    seen_ids = set()
    for i, entry in enumerate(entries):
        loc = f"data[{i}]"

        # entry_id uniqueness
        eid = entry.get("entry_id")
        if eid in seen_ids:
            errors.append(f"{loc}: duplicate entry_id '{eid}'")
        elif eid:
            seen_ids.add(eid)

        # verse_range parse
        vr = entry.get("verse_range", "")
        try:
            start, end = parse_verse_range(vr)
            if start > end:
                errors.append(f"{loc} ({eid}): verse_range start > end: '{vr}'")
        except ValueError:
            errors.append(f"{loc} ({eid}): unparseable verse_range: '{vr}'")
            start, end = 0, 0

        # verse_range_osis format
        vro = entry.get("verse_range_osis", "")
        if vro and not OSIS_REF_PATTERN.match(vro):
            errors.append(f"{loc} ({eid}): invalid verse_range_osis format: '{vro}'")

        # cross_references OSIS format
        for ref in entry.get("cross_references", []):
            if not check_osis_ref(ref):
                errors.append(f"{loc} ({eid}): invalid cross_reference OSIS: '{ref}'")

        # word_count > 0
        wc = entry.get("word_count", 0)
        if not isinstance(wc, int) or wc <= 0:
            errors.append(f"{loc} ({eid}): word_count must be a positive integer, got {wc!r}")

        # commentary_text non-empty
        ct = entry.get("commentary_text", "")
        if not ct or not ct.strip():
            errors.append(f"{loc} ({eid}): commentary_text is empty")

        # summary_review_status valid
        srs = entry.get("summary_review_status", "")
        if srs not in VALID_SUMMARY_STATUSES:
            errors.append(f"{loc} ({eid}): invalid summary_review_status: '{srs}'")

        # If summary is present, status should not be withheld
        if entry.get("summary") and entry.get("summary_review_status") == "withheld":
            warnings.append(
                f"{loc} ({eid}): summary is present but status is 'withheld'"
            )

        # book_number matches book_osis
        book_osis = entry.get("book_osis", "")
        book_num = entry.get("book_number", 0)
        expected_num = KNOWN_BOOK_NUMBERS.get(book_osis)
        if expected_num is not None and book_num != expected_num:
            errors.append(
                f"{loc} ({eid}): book_number {book_num} does not match {book_osis} (expected {expected_num})"
            )

    return errors, warnings


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate commentary JSON files")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("files", nargs="*", metavar="FILE", help="Files to validate")
    group.add_argument("--all", action="store_true", help="Validate all files under data/")
    args = parser.parse_args()

    if args.all:
        files = list(DATA_DIR.rglob("*.json"))
        # Exclude manifest files
        files = [f for f in files if not f.name.startswith("_")]
    else:
        files = [Path(f).resolve() for f in args.files]

    if not files:
        print("No files to validate.")
        sys.exit(0)

    total_errors = 0
    total_warnings = 0

    for path in sorted(files):
        errors, warnings = validate_file(path)
        status = "PASS" if not errors else "FAIL"
        print(f"[{status}] {path.relative_to(REPO_ROOT)} — {len(errors)} errors, {len(warnings)} warnings")
        for err in errors:
            print(f"  ERROR: {err}")
        for warn in warnings:
            print(f"  WARN:  {warn}")
        total_errors += len(errors)
        total_warnings += len(warnings)

    print()
    print(f"Validated {len(files)} file(s): {total_errors} total errors, {total_warnings} total warnings")

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
