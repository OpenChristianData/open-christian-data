"""
add_token_counts.py
-------------------
Post-processing script: computes token_count (cl100k_base) for all JSON records
in data/ that have tokenizable text. Idempotent -- safe to re-run after new data
is added.

Supported schema types and text extraction rules:
  commentary        -- tokenize commentary_text
  catechism_qa      -- tokenize "Q: {question} A: {answer}"
  doctrinal_document -- tokenize all content/content_with_proofs fields in units tree (recursive)
  devotional        -- tokenize concatenated content_blocks
  bible_text        -- tokenize verse text field

Usage:
  py -3 build/scripts/add_token_counts.py [--dry-run]
"""

import argparse
import glob
import json
import logging
import os
import sys
import time

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
LOG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "add_token_counts.log"
)

ENCODING_NAME = "cl100k_base"

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# tiktoken setup
# ---------------------------------------------------------------------------

try:
    import tiktoken
except ImportError:
    log.error("tiktoken is not installed. Run: py -3 -m pip install tiktoken")
    sys.exit(1)

ENCODER = tiktoken.get_encoding(ENCODING_NAME)


def count_tokens(text):
    """Return token count for the given text string using cl100k_base."""
    if not text:
        return 0
    return len(ENCODER.encode(text))


# ---------------------------------------------------------------------------
# Text extraction per schema type
# ---------------------------------------------------------------------------


def extract_text_commentary(record):
    """Return the text to tokenize for a commentary record."""
    return record.get("commentary_text") or ""


def extract_text_catechism_qa(record):
    """Return the text to tokenize for a catechism Q&A record."""
    question = record.get("question") or ""
    answer = record.get("answer") or ""
    return "Q: {} A: {}".format(question, answer)


def extract_text_devotional(record):
    """Return the text to tokenize for a devotional record (joined content_blocks)."""
    blocks = record.get("content_blocks") or []
    return " ".join(blocks)


def extract_text_bible_text(record):
    """Return the text to tokenize for a bible_text record."""
    return record.get("text") or ""


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------


def process_records_list(records, extract_fn, dry_run):
    """
    Walk a list of record dicts, add token_count where missing or verify
    where present. Returns (added, mismatches, skipped_no_text) counts.
    """
    added = 0
    mismatches = 0
    skipped_no_text = 0

    for record in records:
        text = extract_fn(record)
        if not text.strip():
            skipped_no_text += 1
            continue

        expected = count_tokens(text)

        if "token_count" not in record:
            if not dry_run:
                record["token_count"] = expected
            added += 1
        else:
            existing = record["token_count"]
            if existing != expected:
                mismatches += 1
                log.warning(
                    "Mismatch: existing token_count=%d, computed=%d",
                    existing,
                    expected,
                )

    return added, mismatches, skipped_no_text


def process_doctrinal_units(units, dry_run):
    """
    Walk the recursive units tree for a doctrinal_document. Each leaf unit that
    has content (but no token_count) gets a token_count added. Returns
    (added, mismatches) counts.
    """
    added = 0
    mismatches = 0

    for unit in units:
        texts = []
        content = unit.get("content")
        content_with_proofs = unit.get("content_with_proofs")
        if content:
            texts.append(content)
        if content_with_proofs and content_with_proofs != content:
            texts.append(content_with_proofs)

        if texts:
            # Tokenize the primary content field (use content, fallback content_with_proofs)
            primary_text = content or content_with_proofs or ""
            expected = count_tokens(primary_text)
            if "token_count" not in unit:
                if not dry_run:
                    unit["token_count"] = expected
                added += 1
            else:
                existing = unit["token_count"]
                if existing != expected:
                    mismatches += 1
                    log.warning(
                        "Unit mismatch: existing=%d, computed=%d",
                        existing,
                        expected,
                    )

        # Recurse into children
        children = unit.get("children") or []
        if children:
            child_added, child_mismatches = process_doctrinal_units(children, dry_run)
            added += child_added
            mismatches += child_mismatches

    return added, mismatches


def process_file(path, dry_run):
    """
    Load a JSON file, process it, write it back (unless dry_run).
    Returns (added, mismatches, skipped_no_text) for this file, or (0, 0, 0) if skipped.
    """
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)

    schema_type = doc.get("meta", {}).get("schema_type")
    if schema_type is None:
        # _manifest.json or other non-record files -- skip silently
        return 0, 0, 0

    data = doc.get("data")
    added = 0
    mismatches = 0
    skipped = 0

    if schema_type == "commentary":
        if not isinstance(data, list):
            log.warning("Unexpected data format in %s (commentary not a list)", path)
            return 0, 0, 0
        added, mismatches, skipped = process_records_list(data, extract_text_commentary, dry_run)

    elif schema_type == "catechism_qa":
        if not isinstance(data, list):
            log.warning("Unexpected data format in %s (catechism_qa not a list)", path)
            return 0, 0, 0
        added, mismatches, skipped = process_records_list(data, extract_text_catechism_qa, dry_run)

    elif schema_type == "devotional":
        if not isinstance(data, list):
            log.warning("Unexpected data format in %s (devotional not a list)", path)
            return 0, 0, 0
        added, mismatches, skipped = process_records_list(data, extract_text_devotional, dry_run)

    elif schema_type == "bible_text":
        if not isinstance(data, list):
            log.warning("Unexpected data format in %s (bible_text not a list)", path)
            return 0, 0, 0
        added, mismatches, skipped = process_records_list(data, extract_text_bible_text, dry_run)

    elif schema_type == "doctrinal_document":
        if not isinstance(data, dict):
            log.warning("Unexpected data format in %s (doctrinal_document not a dict)", path)
            return 0, 0, 0
        units = data.get("units") or []
        added, mismatches = process_doctrinal_units(units, dry_run)

    else:
        log.debug("Skipping unknown schema_type=%s in %s", schema_type, path)
        return 0, 0, 0

    if added > 0 and not dry_run:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        log.info("  Wrote %s (+%d token_count fields)", os.path.basename(path), added)

    return added, mismatches, skipped


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Add token_count fields to Open Christian Data JSON records."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without modifying any files.",
    )
    args = parser.parse_args()

    if args.dry_run:
        log.info("=== DRY RUN -- no files will be modified ===")
    else:
        log.info("=== LIVE RUN -- files will be modified ===")

    start = time.time()

    json_files = sorted(
        glob.glob(os.path.join(DATA_DIR, "**", "*.json"), recursive=True)
    )
    log.info("Found %d JSON files in %s", len(json_files), DATA_DIR)

    total_added = 0
    total_mismatches = 0
    total_skipped = 0
    files_touched = 0
    files_processed = 0
    errors = 0

    for i, path in enumerate(json_files, 1):
        if i % 50 == 0:
            log.info("Processing file %d of %d...", i, len(json_files))
        try:
            added, mismatches, skipped = process_file(path, args.dry_run)
            files_processed += 1
            if added > 0:
                files_touched += 1
                total_added += added
            if mismatches > 0:
                total_mismatches += mismatches
            total_skipped += skipped
        except Exception as exc:
            errors += 1
            log.error("Error processing %s: %s", path, exc)

    elapsed = time.time() - start

    # Summary
    mode = "DRY RUN" if args.dry_run else "LIVE"
    log.info("---")
    log.info("[%s] Processed %d files in %.1fs", mode, files_processed, elapsed)
    log.info(
        "[%s] Added token_count to %d records across %d files",
        mode,
        total_added,
        files_touched,
    )
    if total_mismatches:
        log.warning(
            "[%s] Mismatches found: %d records had token_count that differed from computed value",
            mode,
            total_mismatches,
        )
    if errors:
        log.error("[%s] Errors: %d files failed to process", mode, errors)
    if total_skipped:
        log.info(
            "[%s] Skipped %d records with no tokenizable text (null/empty text fields)",
            mode,
            total_skipped,
        )
    if not total_mismatches and not errors:
        log.info("[%s] No mismatches or errors.", mode)


if __name__ == "__main__":
    main()
