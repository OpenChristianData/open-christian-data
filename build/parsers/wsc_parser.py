"""wsc_parser.py
Parse the Westminster Shorter Catechism from Creeds.json into catechism_qa schema.

Source: raw/Creeds.json/creeds/westminster_shorter_catechism.json
Output: data/catechisms/westminster-shorter-catechism.json

Usage:
    py -3 build/parsers/wsc_parser.py
    py -3 build/parsers/wsc_parser.py --dry-run
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

SOURCE_FILE = REPO_ROOT / "raw" / "Creeds.json" / "creeds" / "westminster_shorter_catechism.json"
OUTPUT_DIR = REPO_ROOT / "data" / "catechisms"
OUTPUT_FILE = OUTPUT_DIR / "westminster-shorter-catechism.json"
LOG_FILE = Path(__file__).resolve().parent / "wsc_parser.log"

DOCUMENT_ID = "westminster-shorter-catechism"
SCHEMA_VERSION = "2.1.0"
PROCESSING_SCRIPT_VERSION = "build/parsers/wsc_parser.py@v1.0.0"
DOWNLOAD_DATE = "2026-03-27"  # Date Creeds.json data was downloaded locally

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(message: str, log_lines: list) -> None:
    """Print to console (ASCII only) and append to log list."""
    print(message)
    log_lines.append(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{h}"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_wsc(source: dict, log_lines: list) -> tuple:
    """Map Creeds.json WSC records to catechism_qa data entries.

    Returns (entries, parse_errors) where parse_errors is a list of error strings.
    On per-item errors, logs the error and skips that item rather than crashing.
    """
    entries = []
    parse_errors = []
    raw_data = source.get("Data", [])

    for idx, item in enumerate(raw_data):
        try:
            number = item["Number"]
            question = item["Question"].strip()
            answer = item["Answer"].strip()
        except KeyError as exc:
            msg = f"ERROR: item[{idx}] missing field {exc} -- skipping"
            log(msg, log_lines)
            parse_errors.append(msg)
            continue

        entry = {
            "document_id": DOCUMENT_ID,
            "item_id": str(number),
            "sort_key": number,
            "question": question,
            "answer": answer,
            "answer_with_proofs": None,
            # WSC data in Creeds.json does not include scripture proofs
            "proofs": [],
            "group": None,
            "sub_questions": None,
        }
        entries.append(entry)

    return entries, parse_errors


def build_output(source: dict, entries: list, source_hash: str) -> dict:
    """Wrap parsed entries in the meta envelope."""
    meta = source.get("Metadata", {})
    processing_date = datetime.today().strftime("%Y-%m-%d")

    return {
        "meta": {
            "id": DOCUMENT_ID,
            "title": meta.get("Title", "Westminster Shorter Catechism"),
            "author": "Westminster Assembly",
            "author_birth_year": None,
            "author_death_year": None,
            "contributors": [],
            "original_publication_year": int(meta.get("Year", 1647)),
            "language": "en",
            "original_language": "en",
            "tradition": ["reformed", "presbyterian"],
            "tradition_notes": (
                "Produced by the Westminster Assembly (1643-1652) under the authority of the "
                "English Parliament. Adopted by the Church of Scotland and most Presbyterian "
                "denominations as their primary catechism."
            ),
            "era": "post-reformation",
            "audience": "lay",
            "license": "cc0-1.0",
            "schema_type": "catechism_qa",
            "schema_version": SCHEMA_VERSION,
            "completeness": "full",
            "provenance": {
                "source_url": meta.get("SourceUrl", ""),
                "source_format": "JSON",
                "source_edition": "NonlinearFruit/Creeds.json digitization",
                "download_date": DOWNLOAD_DATE,
                "source_hash": source_hash,
                "processing_method": "automated",
                "processing_script_version": PROCESSING_SCRIPT_VERSION,
                "processing_date": processing_date,
                "notes": (
                    "Creeds.json WSC data contains Q&A only -- no scripture proof texts. "
                    "proofs arrays are empty. Source attribution: Public Domain."
                ),
            },
        },
        "data": entries,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse WSC from Creeds.json")
    parser.add_argument("--dry-run", action="store_true", help="Parse and print stats without writing output")
    args = parser.parse_args()

    log_lines = []
    warning_count = 0
    start_time = time.time()
    run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log(f"[{run_timestamp}] WSC parser -- {'DRY RUN' if args.dry_run else 'LIVE RUN'}", log_lines)
    log(f"Source: {SOURCE_FILE}", log_lines)
    log(f"Output: {OUTPUT_FILE}", log_lines)
    log("", log_lines)

    # Load source
    if not SOURCE_FILE.exists():
        log(f"ERROR: Source file not found: {SOURCE_FILE}", log_lines)
        log(f"  -> Check that raw/Creeds.json has been extracted to {REPO_ROOT / 'raw' / 'Creeds.json'}", log_lines)
        _write_log(log_lines)
        sys.exit(1)

    with open(SOURCE_FILE, encoding="utf-8") as f:
        source = json.load(f)

    source_hash = sha256_file(SOURCE_FILE)
    log(f"Loaded source -- {len(source.get('Data', []))} Q&A items", log_lines)
    log(f"Source hash: {source_hash}", log_lines)

    # Parse -- errors are logged and counted but do not crash
    entries, parse_errors = parse_wsc(source, log_lines)
    warning_count += len(parse_errors)
    log(f"Parsed {len(entries)} entries ({len(parse_errors)} parse errors)", log_lines)

    # Post-parse validation: check for empty questions/answers
    empty_q = [e for e in entries if not e["question"].strip()]
    empty_a = [e for e in entries if not e["answer"].strip()]
    if empty_q:
        log(f"WARNING: {len(empty_q)} entries have empty questions", log_lines)
        warning_count += len(empty_q)
    if empty_a:
        log(f"WARNING: {len(empty_a)} entries have empty answers", log_lines)
        warning_count += len(empty_a)

    # Build full output document
    output = build_output(source, entries, source_hash)

    # Stats
    total_words = sum(
        len(e["question"].split()) + len(e["answer"].split()) for e in entries
    )
    log(f"Total words (questions + answers): {total_words}", log_lines)

    if args.dry_run:
        log("", log_lines)
        log("DRY RUN -- first 3 entries:", log_lines)
        for entry in entries[:3]:
            log(f"  Q{entry['item_id']}: {entry['question'][:60]}...", log_lines)
            log(f"       {entry['answer'][:60]}...", log_lines)
        log("", log_lines)
        log("DRY RUN complete -- no files written", log_lines)
    else:
        # Create output directory if needed
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        log(f"Written: {OUTPUT_FILE}", log_lines)

    elapsed = time.time() - start_time
    log("", log_lines)
    log(f"Done -- {len(entries)} entries, {warning_count} warnings, {elapsed:.1f}s", log_lines)

    _write_log(log_lines)


def _write_log(log_lines: list) -> None:
    """Append this run's log lines to the log file (one run per append block)."""
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n\n")


if __name__ == "__main__":
    main()
