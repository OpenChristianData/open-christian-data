"""validate.py
Validate data JSON files against schemas and run structural checks.

Dispatches on meta.schema_type:
  - bible_text: verse-level Bible text (one file per book)
  - commentary: verse-keyed commentary entries
  - catechism_qa: question-and-answer catechism entries
  - doctrinal_document: hierarchical confession/creed/canon
  - devotional: date-keyed daily reading entries

Bible text checks:
  1. JSON Schema conformance
  2. OSIS uniqueness within a file
  3. OSIS format (Book.Chapter.Verse)
  4. chapter/verse consistency with OSIS
  5. text non-empty
  6. scope.book_osis matches record OSIS prefixes

Commentary checks:
  1. JSON Schema conformance
  2. Entry ID uniqueness within a file
  3. OSIS verse reference format (basic pattern check)
  4. Word count sanity (> 0)
  5. verse_range parses correctly (start <= end)
  6. book_number matches book_osis
  7. cross_references osis arrays valid (Reference objects: {"raw":..., "osis":[...]})

Catechism Q&A checks:
  1. JSON Schema conformance
  2. item_id uniqueness within a file
  3. sort_key uniqueness and ascending order
  4. question and answer non-empty
  5. Proof reference OSIS format (if any proofs present)
  6. Proof reference OSIS existence against verse index (warnings only)

Devotional checks:
  1. JSON Schema conformance
  2. entry_id uniqueness within a file
  3. entry_id format matches MM-DD[-period]
  4. month/day/period consistency with entry_id
  5. content_blocks non-empty per entry
  6. word_count > 0 per entry
  7. primary_reference OSIS format (if present)

Usage:
    py -3 build/validate.py data/bible-text/bsb/genesis.json
    py -3 build/validate.py data/commentaries/matthew-henry/ezekiel.json
    py -3 build/validate.py data/catechisms/westminster-shorter-catechism.json
    py -3 build/validate.py data/doctrinal-documents/westminster-confession-of-faith.json
    py -3 build/validate.py data/devotionals/spurgeons-morning-evening/morning-evening.json
    py -3 build/validate.py --all
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Devotional entry_id pattern: MM-DD or MM-DD-period
DEVOTIONAL_ENTRY_ID_PATTERN = re.compile(r"^(\d{2})-(\d{2})(?:-(\w+))?$")

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"

# Path to the canonical verse index -- used to check OSIS existence in --all mode
_VERSE_INDEX_PATH = REPO_ROOT / "build" / "bible_data" / "verse_index.json"

# Lazy-loaded reference to validate_osis_array from build.scripts.validate_osis.
# Loaded once on first call; degrades to None if the module or index is unavailable.
_osis_validator_fn = None
_osis_validator_loaded = False


def _get_osis_validator():
    """Return validate_osis_array function, or None if unavailable."""
    global _osis_validator_fn, _osis_validator_loaded
    if _osis_validator_loaded:
        return _osis_validator_fn
    _osis_validator_loaded = True
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from build.scripts.validate_osis import validate_osis_array  # noqa: E402
        _osis_validator_fn = validate_osis_array
    except ImportError as exc:
        print(f"WARN: Could not import validate_osis -- OSIS existence checks disabled: {exc}", file=sys.stderr)
    return _osis_validator_fn

# Strict OSIS: Book.Chapter.Verse[-Book.Chapter.Verse]
# Used for commentary verse_range_osis and cross_references (verse-level required).
# Book codes may have a leading digit (e.g. 1Chr, 2Sam, 1John, 1Pet).
OSIS_REF_PATTERN = re.compile(
    r"^[0-9]?[A-Z][a-zA-Z0-9]+\.\d+\.\d+(-[0-9]?[A-Z][a-zA-Z0-9]+\.\d+\.\d+)?$"
)

# Permissive OSIS: allows numbered book prefixes (1Cor, 2Pet) and chapter-level refs (Gen.1, Rev.2-Rev.3).
# Used for proof text osis arrays in doctrinal_document and catechism_qa files.
OSIS_PROOF_REF_PATTERN = re.compile(
    r"^(\d?[A-Z][a-zA-Z0-9]*)(\.\d+(\.\d+)?)?(-\d?[A-Z][a-zA-Z0-9]*(\.\d+(\.\d+)?)?)?$"
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


def _load_json(path: Path) -> tuple:
    """Load a JSON file. Returns (data, errors)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), []
    except json.JSONDecodeError as exc:
        return None, [f"Invalid JSON: {exc}"]
    except OSError as exc:
        return None, [f"Cannot read file: {exc}"]


def _run_json_schema(data: dict, schema_path: Path, warnings: list, errors: list) -> None:
    """Run JSON Schema validation if jsonschema is available."""
    try:
        import jsonschema  # type: ignore
    except ImportError:
        warnings.append("jsonschema not installed -- skipping schema validation. Run: pip install jsonschema")
        return

    if not schema_path.exists():
        warnings.append(f"Schema file not found: {schema_path}")
        return

    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    try:
        validator = jsonschema.Draft202012Validator(schema)
        for error in validator.iter_errors(data):
            errors.append(f"Schema: {error.json_path} -- {error.message}")
    except Exception as exc:
        warnings.append(f"Schema validation error: {exc}")


def _check_envelope(data: dict, errors: list) -> list:
    """Check meta/data envelope. Returns entries list (may be empty)."""
    if not isinstance(data, dict):
        errors.append("Root must be an object")
        return []
    if "meta" not in data:
        errors.append("Missing 'meta' key")
    if "data" not in data:
        errors.append("Missing 'data' key")
        return []
    entries = data.get("data", [])
    if not isinstance(entries, list):
        errors.append("'data' must be an array")
        return []
    if len(entries) == 0:
        errors.append("'data' array is empty")
    return entries


def validate_commentary_file(path: Path, data: dict) -> tuple:
    """Structural checks for schema_type=commentary. Returns (errors, warnings)."""
    errors = []
    warnings = []

    _run_json_schema(data, SCHEMA_DIR / "commentary.schema.json", warnings, errors)

    entries = _check_envelope(data, errors)

    # Accumulate format-valid OSIS strings for existence check at end
    osis_to_check = []

    seen_ids = set()
    for i, entry in enumerate(entries):
        loc = f"data[{i}]"
        eid = entry.get("entry_id")

        if eid in seen_ids:
            errors.append(f"{loc}: duplicate entry_id '{eid}'")
        elif eid:
            seen_ids.add(eid)

        vr = entry.get("verse_range", "")
        try:
            start, end = parse_verse_range(vr)
            if start > end:
                errors.append(f"{loc} ({eid}): verse_range start > end: '{vr}'")
        except ValueError:
            errors.append(f"{loc} ({eid}): unparseable verse_range: '{vr}'")

        vro = entry.get("verse_range_osis", "")
        if vro and not OSIS_REF_PATTERN.match(vro):
            errors.append(f"{loc} ({eid}): invalid verse_range_osis format: '{vro}'")

        # cross_references: schema defines these as Reference objects {"raw": ..., "osis": [...]}.
        # Plain-string refs are handled defensively for forward compat but are not expected.
        for j, ref in enumerate(entry.get("cross_references", [])):
            if isinstance(ref, dict):
                for osis_str in ref.get("osis", []):
                    if osis_str and not OSIS_REF_PATTERN.match(osis_str):
                        errors.append(
                            f"{loc} ({eid}): cross_references[{j}] invalid OSIS: '{osis_str}'"
                        )
                    elif osis_str:
                        osis_to_check.append(osis_str)
            elif isinstance(ref, str):
                if not check_osis_ref(ref):
                    errors.append(f"{loc} ({eid}): invalid cross_reference OSIS: '{ref}'")

        wc = entry.get("word_count", 0)
        if not isinstance(wc, int) or wc <= 0:
            errors.append(f"{loc} ({eid}): word_count must be a positive integer, got {wc!r}")

        ct = entry.get("commentary_text", "")
        if not ct or not ct.strip():
            errors.append(f"{loc} ({eid}): commentary_text is empty")

        srs = entry.get("summary_review_status", "")
        if srs not in VALID_SUMMARY_STATUSES:
            errors.append(f"{loc} ({eid}): invalid summary_review_status: '{srs}'")

        if entry.get("summary") and entry.get("summary_review_status") == "withheld":
            warnings.append(f"{loc} ({eid}): summary is present but status is 'withheld'")

        book_osis = entry.get("book_osis", "")
        book_num = entry.get("book_number", 0)
        expected_num = KNOWN_BOOK_NUMBERS.get(book_osis)
        if expected_num is not None and book_num != expected_num:
            errors.append(
                f"{loc} ({eid}): book_number {book_num} does not match {book_osis} (expected {expected_num})"
            )

    # Data completeness checks -- catch issues that structural validation misses.
    # A file can be structurally valid but still have widespread null fields.
    if entries:
        total = len(entries)
        null_verse_text = sum(1 for e in entries if not e.get("verse_text"))
        if null_verse_text > 0:
            pct = null_verse_text * 100 / total
            # >5% missing verse_text is a warning; >50% is an error (likely a parser bug)
            msg = f"{null_verse_text}/{total} entries ({pct:.1f}%) missing verse_text"
            if pct > 50:
                errors.append(f"Completeness: {msg}")
            else:
                warnings.append(f"Completeness: {msg}")

    # OSIS existence check -- warnings only (source data may have valid edge cases)
    if osis_to_check:
        validator = _get_osis_validator()
        if validator:
            valid_count, invalid_items = validator(osis_to_check)
            if invalid_items:
                detail_parts = [f"{s} ({r})" for s, r in invalid_items[:5]]
                detail = "; ".join(detail_parts)
                if len(invalid_items) > 5:
                    detail += f" ... and {len(invalid_items) - 5} more"
                warnings.append(
                    f"OSIS existence: {valid_count}/{len(osis_to_check)} valid, "
                    f"{len(invalid_items)} invalid: {detail}"
                )

    return errors, warnings


def validate_catechism_qa_file(path: Path, data: dict) -> tuple:
    """Structural checks for schema_type=catechism_qa. Returns (errors, warnings)."""
    errors = []
    warnings = []

    _run_json_schema(data, SCHEMA_DIR / "catechism_qa.schema.json", warnings, errors)

    entries = _check_envelope(data, errors)

    seen_item_ids = set()
    seen_sort_keys = set()
    prev_sort_key = 0
    is_partial = data.get("meta", {}).get("completeness") == "partial"

    # Accumulate format-valid OSIS strings for existence check at end
    osis_to_check = []

    for i, entry in enumerate(entries):
        loc = f"data[{i}]"
        item_id = entry.get("item_id", "")
        sort_key = entry.get("sort_key")

        # item_id uniqueness
        if item_id in seen_item_ids:
            errors.append(f"{loc}: duplicate item_id '{item_id}'")
        elif item_id:
            seen_item_ids.add(item_id)

        # sort_key uniqueness
        if sort_key in seen_sort_keys:
            errors.append(f"{loc}: duplicate sort_key {sort_key}")
        elif sort_key is not None:
            seen_sort_keys.add(sort_key)

        # sort_key ascending
        if isinstance(sort_key, int):
            if sort_key < prev_sort_key:
                errors.append(f"{loc}: sort_key {sort_key} is not ascending (prev was {prev_sort_key})")
            prev_sort_key = sort_key

        # question and answer non-empty
        # empty/null answers are warnings (not errors) for completeness='partial' files
        if not entry.get("question", "").strip():
            errors.append(f"{loc} (item_id={item_id!r}): question is empty")
        if not (entry.get("answer") or "").strip():
            if is_partial:
                warnings.append(f"{loc} (item_id={item_id!r}): answer is empty (completeness=partial)")
            else:
                errors.append(f"{loc} (item_id={item_id!r}): answer is empty")

        # proof references OSIS format -- use permissive pattern (numbered books + chapter-level refs)
        for j, proof in enumerate(entry.get("proofs", [])):
            for k, ref in enumerate(proof.get("references", [])):
                for osis_str in ref.get("osis", []):
                    if osis_str and not OSIS_PROOF_REF_PATTERN.match(osis_str):
                        errors.append(
                            f"{loc} proof[{j}] ref[{k}]: invalid OSIS: '{osis_str}'"
                        )
                    elif osis_str:
                        # Pattern OK -- queue for verse existence check
                        osis_to_check.append(osis_str)

    # OSIS existence check -- warnings only (source data may have valid edge cases)
    if osis_to_check:
        validator = _get_osis_validator()
        if validator:
            valid_count, invalid_items = validator(osis_to_check)
            if invalid_items:
                detail_parts = [f"{s} ({r})" for s, r in invalid_items[:5]]
                detail = "; ".join(detail_parts)
                if len(invalid_items) > 5:
                    detail += f" ... and {len(invalid_items) - 5} more"
                warnings.append(
                    f"OSIS existence: {valid_count}/{len(osis_to_check)} valid, "
                    f"{len(invalid_items)} invalid: {detail}"
                )

    return errors, warnings


def _check_units(units: list, path_prefix: str, errors: list, osis_to_check: list = None) -> None:
    """Recursively check that all units in a doctrinal_document have required fields.

    osis_to_check: if provided, format-valid OSIS strings are appended for
    downstream existence checking. Pass an empty list from the caller.
    """
    if osis_to_check is None:
        osis_to_check = []
    for i, unit in enumerate(units):
        loc = f"{path_prefix}[{i}]"
        if not isinstance(unit, dict):
            errors.append(f"{loc}: unit must be an object")
            continue
        if not unit.get("unit_type"):
            errors.append(f"{loc}: missing unit_type")
        # Recurse into children
        if unit.get("children"):
            _check_units(unit["children"], f"{loc}.children", errors, osis_to_check)
        # Check OSIS refs in proofs -- use permissive pattern (numbered books + chapter-level refs)
        for j, proof in enumerate(unit.get("proofs", [])):
            for k, ref in enumerate(proof.get("references", [])):
                for osis_str in ref.get("osis", []):
                    if osis_str and not OSIS_PROOF_REF_PATTERN.match(osis_str):
                        errors.append(
                            f"{loc} proof[{j}] ref[{k}]: invalid OSIS: '{osis_str}'"
                        )
                    elif osis_str:
                        # Pattern OK -- queue for verse existence check
                        osis_to_check.append(osis_str)


def validate_doctrinal_document_file(path: Path, data: dict) -> tuple:
    """Structural checks for schema_type=doctrinal_document. Returns (errors, warnings)."""
    errors = []
    warnings = []

    _run_json_schema(data, SCHEMA_DIR / "doctrinal_document.schema.json", warnings, errors)

    if not isinstance(data, dict):
        errors.append("Root must be an object")
        return errors, warnings
    if "meta" not in data:
        errors.append("Missing 'meta' key")
    if "data" not in data:
        errors.append("Missing 'data' key")
        return errors, warnings

    doc = data["data"]
    if not isinstance(doc, dict):
        errors.append("'data' must be an object for doctrinal_document")
        return errors, warnings

    if not doc.get("document_id"):
        errors.append("data.document_id is missing or empty")
    if not doc.get("document_kind"):
        errors.append("data.document_kind is missing or empty")

    osis_to_check = []

    units = doc.get("units")
    if not units:
        errors.append("data.units is missing or empty")
    elif not isinstance(units, list):
        errors.append("data.units must be an array")
    else:
        _check_units(units, "data.units", errors, osis_to_check)

    # OSIS existence check -- warnings only (source data may have valid edge cases)
    if osis_to_check:
        validator = _get_osis_validator()
        if validator:
            valid_count, invalid_items = validator(osis_to_check)
            if invalid_items:
                detail_parts = [f"{s} ({r})" for s, r in invalid_items[:5]]
                detail = "; ".join(detail_parts)
                if len(invalid_items) > 5:
                    detail += f" ... and {len(invalid_items) - 5} more"
                warnings.append(
                    f"OSIS existence: {valid_count}/{len(osis_to_check)} valid, "
                    f"{len(invalid_items)} invalid: {detail}"
                )

    return errors, warnings


def validate_bible_text_file(path: Path, data: dict) -> tuple:
    """Structural checks for schema_type=bible_text. Returns (errors, warnings)."""
    errors = []
    warnings = []

    _run_json_schema(data, SCHEMA_DIR / "bible_text.schema.json", warnings, errors)

    entries = _check_envelope(data, errors)

    # Scope consistency: all records must belong to the book declared in meta.scope
    scope = data.get("meta", {}).get("scope", {})
    scope_osis = scope.get("book_osis", "")

    seen_osis = set()
    for i, entry in enumerate(entries):
        loc = f"data[{i}]"
        osis = entry.get("osis", "")

        # OSIS uniqueness
        if osis in seen_osis:
            errors.append(f"{loc}: duplicate osis '{osis}'")
        elif osis:
            seen_osis.add(osis)

        # OSIS format: Book.Chapter.Verse
        if not OSIS_REF_PATTERN.match(osis):
            errors.append(f"{loc}: invalid osis format: '{osis}'")
        elif scope_osis:
            # Book prefix must match scope
            osis_book = osis.split(".")[0] if "." in osis else ""
            if osis_book != scope_osis:
                errors.append(
                    f"{loc}: osis book '{osis_book}' does not match "
                    f"meta.scope.book_osis '{scope_osis}'"
                )

        # chapter/verse consistency with osis
        parts = osis.split(".")
        if len(parts) == 3:
            try:
                osis_chapter = int(parts[1])
                osis_verse = int(parts[2])
                if entry.get("chapter") != osis_chapter:
                    errors.append(
                        f"{loc} ({osis}): chapter={entry.get('chapter')} "
                        f"does not match osis chapter {osis_chapter}"
                    )
                if entry.get("verse") != osis_verse:
                    errors.append(
                        f"{loc} ({osis}): verse={entry.get('verse')} "
                        f"does not match osis verse {osis_verse}"
                    )
            except ValueError:
                pass  # already caught by OSIS format check above

        # text must be non-empty (BSB omits textual-critical verses -- these
        # should be skipped by the parser, not stored as empty strings)
        text = entry.get("text", "")
        if not text or not text.strip():
            warnings.append(f"{loc} ({osis}): text is empty")

    # Completeness
    if entries:
        total = len(entries)
        empty_text = sum(1 for e in entries if not (e.get("text") or "").strip())
        if empty_text > 0:
            pct = empty_text * 100 / total
            msg = f"{empty_text}/{total} entries ({pct:.1f}%) have empty text"
            if pct > 1:
                errors.append(f"Completeness: {msg}")
            else:
                warnings.append(f"Completeness: {msg}")

    return errors, warnings


def validate_devotional_file(path: Path, data: dict) -> tuple:
    """Structural checks for schema_type=devotional. Returns (errors, warnings)."""
    errors = []
    warnings = []

    _run_json_schema(data, SCHEMA_DIR / "devotional.schema.json", warnings, errors)

    entries = _check_envelope(data, errors)

    seen_ids = set()
    for i, entry in enumerate(entries):
        loc = f"data[{i}]"
        eid = entry.get("entry_id", "")

        # entry_id uniqueness
        if eid in seen_ids:
            errors.append(f"{loc}: duplicate entry_id '{eid}'")
        elif eid:
            seen_ids.add(eid)

        # entry_id format and consistency with month/day/period
        m = DEVOTIONAL_ENTRY_ID_PATTERN.match(eid)
        if not m:
            errors.append(f"{loc} ({eid}): entry_id does not match MM-DD[-period] format")
        else:
            id_month = int(m.group(1))
            id_day = int(m.group(2))
            id_period = m.group(3)  # None if no period segment

            if entry.get("month") != id_month:
                errors.append(
                    f"{loc} ({eid}): month={entry.get('month')} does not match entry_id month {id_month}"
                )
            if entry.get("day") != id_day:
                errors.append(
                    f"{loc} ({eid}): day={entry.get('day')} does not match entry_id day {id_day}"
                )
            period_field = entry.get("period")
            if id_period and period_field and id_period != period_field:
                errors.append(
                    f"{loc} ({eid}): period='{period_field}' does not match entry_id segment '{id_period}'"
                )

        # content_blocks non-empty
        blocks = entry.get("content_blocks", [])
        if not blocks:
            errors.append(f"{loc} ({eid}): content_blocks is empty")
        else:
            empty_blocks = sum(1 for b in blocks if not b.strip())
            if empty_blocks:
                warnings.append(f"{loc} ({eid}): {empty_blocks} empty string(s) in content_blocks")

        # word_count > 0
        wc = entry.get("word_count", 0)
        if not isinstance(wc, int) or wc <= 0:
            errors.append(f"{loc} ({eid}): word_count must be a positive integer, got {wc!r}")

        # primary_reference OSIS format (permissive -- devotional refs are not always verse-level)
        ref = entry.get("primary_reference")
        if ref and isinstance(ref, dict):
            for osis_str in ref.get("osis", []):
                if osis_str and not OSIS_PROOF_REF_PATTERN.match(osis_str):
                    errors.append(f"{loc} ({eid}): invalid primary_reference OSIS: '{osis_str}'")

    # Completeness check
    if entries:
        total = len(entries)
        no_ref = sum(1 for e in entries if not e.get("primary_reference"))
        if no_ref > 0:
            pct = no_ref * 100 / total
            msg = f"{no_ref}/{total} entries ({pct:.1f}%) missing primary_reference"
            if pct > 20:
                errors.append(f"Completeness: {msg}")
            else:
                warnings.append(f"Completeness: {msg}")

        # 730 = without Feb 29; 732 = with Feb 29 (leap year reading)
        if total not in (730, 732):
            warnings.append(
                f"Completeness: {total} entries (expected 730 or 732 for a full-year devotional)"
            )

    return errors, warnings


def validate_church_fathers_file(path: Path, data: dict) -> tuple:
    """Structural checks for schema_type=church_fathers. Returns (errors, warnings)."""
    errors = []
    warnings = []

    _run_json_schema(data, SCHEMA_DIR / "church_fathers.schema.json", warnings, errors)

    entries = _check_envelope(data, errors)

    seen_ids = set()
    for i, entry in enumerate(entries):
        loc = f"data[{i}]"
        eid = entry.get("entry_id", "")

        # entry_id uniqueness
        if eid in seen_ids:
            errors.append(f"{loc}: duplicate entry_id '{eid}'")
        elif eid:
            seen_ids.add(eid)

        # quote non-empty
        quote = entry.get("quote", "")
        if not quote or not quote.strip():
            errors.append(f"{loc} ({eid}): quote is empty")

        # word_count positive
        wc = entry.get("word_count", 0)
        if not isinstance(wc, int) or wc < 0:
            errors.append(f"{loc} ({eid}): word_count must be a non-negative integer, got {wc!r}")

        # anchor_ref structure
        ref = entry.get("anchor_ref", {})
        if not isinstance(ref, dict):
            errors.append(f"{loc} ({eid}): anchor_ref must be an object")
        else:
            if not ref.get("raw"):
                errors.append(f"{loc} ({eid}): anchor_ref.raw is empty")
            osis_list = ref.get("osis", [])
            if not isinstance(osis_list, list):
                errors.append(f"{loc} ({eid}): anchor_ref.osis must be an array")
            else:
                for osis_str in osis_list:
                    # Use permissive pattern -- church_fathers refs include ranges
                    if osis_str and not OSIS_PROOF_REF_PATTERN.match(osis_str):
                        errors.append(
                            f"{loc} ({eid}): anchor_ref.osis invalid format: '{osis_str}'"
                        )

    # Completeness checks
    if entries:
        total = len(entries)
        no_osis = sum(1 for e in entries if not e.get("anchor_ref", {}).get("osis"))
        empty_source = sum(1 for e in entries if not e.get("source_title", "").strip())
        if no_osis > 0:
            pct = no_osis * 100 / total
            msg = f"{no_osis}/{total} entries ({pct:.1f}%) have empty anchor_ref.osis (non-canonical book)"
            # >50% no-OSIS is unexpected for a standard Church Father
            if pct > 50:
                warnings.append(f"Completeness: {msg}")
            else:
                warnings.append(f"Completeness: {msg}")
        if empty_source > 0:
            pct = empty_source * 100 / total
            warnings.append(
                f"Completeness: {empty_source}/{total} entries ({pct:.1f}%) missing source_title"
            )

    return errors, warnings


def validate_file(path: Path) -> tuple:
    """Load a data file, detect schema_type, and run appropriate validation."""
    data, load_errors = _load_json(path)
    if load_errors:
        return load_errors, []

    schema_type = data.get("meta", {}).get("schema_type", "")

    if schema_type == "commentary":
        return validate_commentary_file(path, data)
    elif schema_type == "catechism_qa":
        return validate_catechism_qa_file(path, data)
    elif schema_type == "doctrinal_document":
        return validate_doctrinal_document_file(path, data)
    elif schema_type == "devotional":
        return validate_devotional_file(path, data)
    elif schema_type == "bible_text":
        return validate_bible_text_file(path, data)
    elif schema_type == "church_fathers":
        return validate_church_fathers_file(path, data)
    else:
        # Unknown type -- run envelope check only
        errors = []
        warnings = [f"Unknown schema_type '{schema_type}' -- only envelope checked"]
        _check_envelope(data, errors)
        return errors, warnings


def check_author_registry() -> tuple:
    """Check authors in data files against the author registry.

    Loads data/authors/registry.json and collects every author string from
    metadata envelopes across all data files.  Warns on any author string that
    does not match a display_name or alias in the registry.

    Returns (errors, warnings).  Author mismatches are warnings, not errors,
    because the registry is expected to be populated incrementally.
    """
    errors = []
    warnings = []

    registry_path = DATA_DIR / "authors" / "registry.json"
    if not registry_path.exists():
        warnings.append(
            "Author registry not found at data/authors/registry.json -- "
            "author cross-check skipped"
        )
        return errors, warnings

    try:
        with open(registry_path, encoding="utf-8") as f:
            registry_data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"Author registry could not be loaded: {exc}")
        return errors, warnings

    # Validate registry against its own schema
    registry_schema_path = REPO_ROOT / "schemas" / "v1" / "author_registry.schema.json"
    if registry_schema_path.exists():
        _run_json_schema(registry_data, registry_schema_path, warnings, errors)
        if errors:
            # Stop early -- a broken registry produces unreliable cross-checks
            return errors, warnings

    # Build lookup: display_name and every alias -> author_id
    known_name_forms = {}  # lowercased name form -> author_id
    author_ids = []
    for entry in registry_data.get("authors", []):
        aid = entry.get("author_id", "")
        author_ids.append(aid)
        dn = entry.get("display_name", "")
        if dn:
            known_name_forms[dn.lower()] = aid
        for alias in entry.get("aliases", []):
            if alias:
                known_name_forms[alias.lower()] = aid

    # Check for duplicate author_ids
    seen_ids = set()
    for aid in author_ids:
        if aid in seen_ids:
            errors.append(f"Author registry: duplicate author_id '{aid}'")
        else:
            seen_ids.add(aid)

    # Scan all data files for author strings in meta envelopes
    data_files = [
        f for f in DATA_DIR.rglob("*.json")
        if not f.name.startswith("_")
    ]

    unmatched = {}  # author string -> list of file paths
    for path in sorted(data_files):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue  # parse errors are caught by validate_file() elsewhere

        author_val = data.get("meta", {}).get("author")
        if not author_val:
            continue  # null/missing author is valid (e.g. Apostles' Creed)

        if author_val.lower() not in known_name_forms:
            rel = str(path.relative_to(REPO_ROOT))
            unmatched.setdefault(author_val, []).append(rel)

    for author_str, file_list in sorted(unmatched.items()):
        files_str = ", ".join(file_list[:3])
        if len(file_list) > 3:
            files_str += f" ... and {len(file_list) - 3} more"
        warnings.append(
            f"Author not in registry: '{author_str}' "
            f"(appears in: {files_str})"
        )

    return errors, warnings


def check_schema_consistency() -> tuple:
    """Check that shared enum values (tradition, license) are identical across all schemas.

    Returns (errors, warnings).
    """
    errors = []
    warnings = []

    schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
    if len(schema_files) < 2:
        return errors, warnings

    # Extract enum values by field name from each schema's meta.properties
    enum_sets = {}  # {field_name: {schema_name: set_of_values}}

    for sf in schema_files:
        with open(sf, encoding="utf-8") as f:
            schema = json.load(f)
        name = sf.stem  # e.g. "commentary.schema"
        meta_props = schema.get("properties", {}).get("meta", {}).get("properties", {})

        for field_name in ("tradition", "license"):
            field_def = meta_props.get(field_name, {})
            values = None

            # Direct enum on the field
            if "enum" in field_def:
                values = set(field_def["enum"])
            # Enum on items (for array fields like tradition)
            items = field_def.get("items", {})
            if "enum" in items:
                values = set(items["enum"])

            if values is not None:
                enum_sets.setdefault(field_name, {})[name] = values

    # Compare: all schemas should have the same enum values for each shared field
    for field_name, by_schema in enum_sets.items():
        all_values = set()
        for vals in by_schema.values():
            all_values |= vals

        for schema_name, vals in by_schema.items():
            missing = all_values - vals
            if missing:
                errors.append(
                    f"Schema drift: {schema_name} '{field_name}' is missing: "
                    f"{sorted(missing)}. Add to match other schemas."
                )

    return errors, warnings


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate data JSON files against schemas")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("files", nargs="*", metavar="FILE", help="Files to validate")
    group.add_argument("--all", action="store_true", help="Validate all files under data/")
    args = parser.parse_args()

    if args.all:
        files = list(DATA_DIR.rglob("*.json"))
        # Exclude manifest files and the authors registry (validated separately via check_author_registry)
        files = [
            f for f in files
            if not f.name.startswith("_") and f.parent != DATA_DIR / "authors"
        ]
    else:
        files = [Path(f).resolve() for f in args.files]

    if not files:
        print("No files to validate.")
        sys.exit(0)

    total_errors = 0
    total_warnings = 0

    # Verse index availability warning -- shown once at top of --all run
    if args.all and not _VERSE_INDEX_PATH.exists():
        print("WARN: build/bible_data/verse_index.json not found -- OSIS existence checks skipped")
        print("  Run: py -3 build/scripts/build_verse_index.py")
        print()
        total_warnings += 1

    # Schema consistency check runs automatically with --all
    if args.all:
        sc_errors, sc_warnings = check_schema_consistency()
        if sc_errors or sc_warnings:
            print("[SCHEMA CONSISTENCY]")
            for err in sc_errors:
                print(f"  ERROR: {err}")
            for warn in sc_warnings:
                print(f"  WARN:  {warn}")
            print()
            total_errors += len(sc_errors)
            total_warnings += len(sc_warnings)

    # Author registry cross-check runs automatically with --all
    if args.all:
        ar_errors, ar_warnings = check_author_registry()
        if ar_errors or ar_warnings:
            print("[AUTHOR REGISTRY]")
            for err in ar_errors:
                print(f"  ERROR: {err}")
            for warn in ar_warnings:
                print(f"  WARN:  {warn}")
            print()
            total_errors += len(ar_errors)
            total_warnings += len(ar_warnings)

    for path in sorted(files):
        errors, warnings = validate_file(path)
        status = "PASS" if not errors else "FAIL"
        print(f"[{status}] {path.relative_to(REPO_ROOT)} -- {len(errors)} errors, {len(warnings)} warnings")
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
