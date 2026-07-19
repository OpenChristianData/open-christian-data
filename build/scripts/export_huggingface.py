"""
export_huggingface.py -- Export OCD data to JSONL for HuggingFace upload.

Reads each schema type directory under data/, extracts records, inlines key
meta fields into each record, and writes one JSONL file per schema_type to
exports/huggingface/.

Usage:
    py -3 build/scripts/export_huggingface.py

Output:
    exports/huggingface/<schema_type>.jsonl  -- one file per schema type
    build/scripts/export_huggingface.log     -- run log

Schema type handling:
    - Most types (flat list): each item in data[] becomes one JSONL line.
    - structured_text: data is a nested dict; each content_block (leaf text)
      within sections/children becomes one JSONL line, with section context.
      This matches the block counts in the GitHub README (1,790 for Pilgrim's
      Progress, 7,430 for Calvin's Institutes, etc.).
    - doctrinal_document: data is a nested dict; each leaf unit (clause/section)
      with a 'content' field becomes one JSONL line, with parent chapter context.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Derive project root from this script's location (build/scripts/ -> project root)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "exports" / "huggingface"
LOG_FILE = Path(__file__).parent / "export_huggingface.log"
DATASET_CARD = PROJECT_ROOT / "docs" / "HUGGINGFACE_DATASET_CARD.md"
NSH_REFERENCE_PREFIX = ("reference", "schaff", "encyclopedia", "1908-1914")

# Directories under data/ that contain no exportable data records
SKIP_DATA_DIRS = {"authors"}

# Individual filenames to skip (manifest / registry files)
SKIP_FILENAMES = {"_manifest.json", "registry.json"}

# Primary content field to check for each schema type (PIPE-02 quality stats).
# The first field found non-empty on a record counts as "content present".
PRIMARY_CONTENT_FIELDS = {
    "bible_text": ["text", "verse_text"],
    "catechism_qa": ["answer"],
    "church_fathers": ["quote"],
    "commentary": ["commentary_text"],
    "devotional": ["content_blocks"],
    "doctrinal_document": ["content"],
    "prayer": ["content_blocks"],
    "reference_entry": ["definition_blocks", "definition"],
    "sermon": ["content", "text", "content_blocks"],
    "structured_text": ["text"],
    "topical_reference": ["subtopics"],
}


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ---------------------------------------------------------------------------
# Meta field extraction helpers
# ---------------------------------------------------------------------------

def extract_meta_fields(meta):
    """Pull the seven inline fields from a file's meta block."""
    provenance = meta.get("provenance") or {}
    return {
        "_source_id": meta.get("id"),
        "_source_title": meta.get("title"),
        "_author": meta.get("author"),
        "_contributors": meta.get("contributors") or [],
        "_schema_type": meta.get("schema_type"),
        "_license": meta.get("license"),
        "_source_url": provenance.get("source_url"),
    }


# ---------------------------------------------------------------------------
# Record extractors per schema type
# ---------------------------------------------------------------------------

def records_from_flat_list(data, meta_fields):
    """data is a list -- yield each item with meta fields inlined."""
    for item in data:
        record = {}
        record.update(meta_fields)
        record.update(item)
        yield record


def records_from_structured_text(data, meta_fields):
    """
    data is a dict: {work_id, work_kind, sections}
    sections is a list of nested nodes; each node may have:
      - content_blocks: list of text strings (the leaf records)
      - children: list of child nodes

    Yields one record per content_block, with the section path inlined.
    """
    work_id = data.get("work_id", "")
    work_kind = data.get("work_kind", "")

    def walk(section, ancestor_labels):
        label = section.get("label") or ""
        title = section.get("title") or ""
        section_type = section.get("section_type") or ""
        scripture_refs = section.get("scripture_references") or []

        # Build a human-readable path, e.g. ["Book I", "Chapter 3"]
        path = ancestor_labels + ([label] if label else [])

        # Emit one record per content block (leaf text strings)
        blocks = section.get("content_blocks") or []
        for i, block_text in enumerate(blocks):
            record = {}
            record.update(meta_fields)
            record.update(
                {
                    "work_id": work_id,
                    "work_kind": work_kind,
                    "section_type": section_type,
                    "section_label": label,
                    "section_title": title,
                    "section_path": path,
                    "block_index": i,
                    "text": block_text,
                    "scripture_references": scripture_refs,
                }
            )
            yield record

        for child in section.get("children") or []:
            yield from walk(child, path)

    for section in data.get("sections") or []:
        yield from walk(section, [])


def records_from_doctrinal_document(data, meta_fields):
    """
    data is a dict: {document_id, document_kind, revision_history, units}
    units is a list of chapters; each chapter has children (clauses/sections).
    Leaf children have a 'content' field.

    Yields one record per leaf unit, with parent chapter context inlined.
    """
    doc_id = data.get("document_id", "")
    doc_kind = data.get("document_kind", "")

    def walk(unit, parent_number, parent_title):
        children = unit.get("children") or []
        if children:
            chapter_number = unit.get("number", "")
            chapter_title = unit.get("title") or ""
            for child in children:
                yield from walk(child, chapter_number, chapter_title)
        else:
            record = {}
            record.update(meta_fields)
            record.update(
                {
                    "document_id": doc_id,
                    "document_kind": doc_kind,
                    "unit_type": unit.get("unit_type", ""),
                    "number": unit.get("number", ""),
                    "title": unit.get("title") or "",
                    "parent_number": parent_number,
                    "parent_title": parent_title,
                    "content": unit.get("content") or "",
                    "token_count": unit.get("token_count"),
                    "proofs": unit.get("proofs") or [],
                }
            )
            yield record

    for unit in data.get("units") or []:
        yield from walk(unit, "", "")


def extract_records(meta, data, filepath):
    """
    Dispatch to the correct extractor based on schema_type.
    Returns a generator of record dicts.
    """
    schema_type = meta.get("schema_type", "unknown")
    meta_fields = extract_meta_fields(meta)

    if isinstance(data, list):
        return records_from_flat_list(data, meta_fields)
    elif isinstance(data, dict):
        if schema_type == "structured_text":
            return records_from_structured_text(data, meta_fields)
        elif schema_type == "doctrinal_document":
            return records_from_doctrinal_document(data, meta_fields)
        else:
            logging.warning(
                "Unexpected dict data for schema_type=%s in %s -- emitting as one record",
                schema_type,
                filepath,
            )
            record = {}
            record.update(meta_fields)
            record.update(data)
            return iter([record])
    else:
        logging.warning(
            "Unexpected data type %s for schema_type=%s in %s -- skipping",
            type(data).__name__,
            schema_type,
            filepath,
        )
        return iter([])


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_json_files(data_dir, skip_dirs, skip_filenames):
    """Walk data_dir recursively, yielding paths to exportable JSON files."""
    for root, dirs, files in os.walk(data_dir):
        root_path = Path(root)
        # Skip top-level dirs that contain no exportable records
        top_subdir = root_path.relative_to(data_dir).parts
        if top_subdir and top_subdir[0] in skip_dirs:
            dirs.clear()
            continue
        if top_subdir[: len(NSH_REFERENCE_PREFIX)] == NSH_REFERENCE_PREFIX:
            dirs.clear()
            continue

        for filename in sorted(files):
            if not filename.endswith(".json"):
                continue
            if filename in skip_filenames:
                continue
            yield root_path / filename


# ---------------------------------------------------------------------------
# Quality stats helpers (PIPE-02)
# ---------------------------------------------------------------------------

def has_content(record, schema_type):
    """Return True if the record's primary content field is non-empty."""
    fields = PRIMARY_CONTENT_FIELDS.get(schema_type, [])
    for field in fields:
        val = record.get(field)
        if val is not None and val != "" and val != [] and val != {}:
            return True
    return False


def compute_quality_stats(records, schema_type):
    """
    Return a dict with:
      - empty_content: count of records missing primary content
      - token_counts: list of numeric token_count values (for min/median/max)
      - word_counts: list of numeric word_count values
    """
    empty_content = 0
    token_counts = []
    word_counts = []
    for r in records:
        if not has_content(r, schema_type):
            empty_content += 1
        tc = r.get("token_count")
        if isinstance(tc, (int, float)):
            token_counts.append(tc)
        wc = r.get("word_count")
        if isinstance(wc, (int, float)):
            word_counts.append(wc)
    return {
        "empty_content": empty_content,
        "token_counts": token_counts,
        "word_counts": word_counts,
    }


def median(values):
    """Return integer median of a sorted list, or None if empty."""
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return int(s[mid]) if n % 2 else int((s[mid - 1] + s[mid]) / 2)


# ---------------------------------------------------------------------------
# Main export logic
# ---------------------------------------------------------------------------

def run_export():
    setup_logging()
    start = time.time()

    logging.info("Starting HuggingFace export")
    logging.info("  DATA_DIR   : %s", DATA_DIR)
    logging.info("  OUTPUT_DIR : %s", OUTPUT_DIR)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if DATASET_CARD.exists():
        (OUTPUT_DIR / "README.md").write_text(DATASET_CARD.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        logging.warning("Dataset card not found at %s -- README.md not refreshed", DATASET_CARD)

    # Collect all records grouped by schema_type
    all_records = {}   # schema_type -> list of record dicts
    file_count = 0
    error_count = 0

    json_files = list(find_json_files(DATA_DIR, SKIP_DATA_DIRS, SKIP_FILENAMES))
    total_files = len(json_files)
    logging.info("Found %d JSON files to process", total_files)

    for i, filepath in enumerate(json_files, 1):
        if i % 50 == 0 or i == 1:
            logging.info("Processing file %d of %d: %s", i, total_files, filepath.name)

        try:
            with open(filepath, encoding="utf-8") as f:
                doc = json.load(f)
        except Exception as e:
            logging.error("Failed to load %s: %s -- skipping", filepath, e)
            error_count += 1
            continue

        meta = doc.get("meta") or {}
        data = doc.get("data")
        schema_type = meta.get("schema_type")

        if not schema_type:
            logging.warning("No schema_type in meta for %s -- skipping", filepath)
            continue
        if data is None:
            logging.warning("No data field in %s -- skipping", filepath)
            continue

        if schema_type not in all_records:
            all_records[schema_type] = []

        try:
            records = list(extract_records(meta, data, filepath))
            all_records[schema_type].extend(records)
            file_count += 1
        except Exception as e:
            logging.error(
                "Failed to extract records from %s (schema_type=%s): %s -- skipping",
                filepath, schema_type, e,
            )
            error_count += 1
            continue

    logging.info("Loaded %d files (%d errors)", file_count, error_count)

    # API-08: verify at least one schema_type has records
    if not all_records:
        logging.error(
            "No records collected from %s -- check that data/ contains valid JSON files",
            DATA_DIR,
        )
        sys.exit(1)

    # Write one JSONL per schema_type, guarding each independently (REL-08)
    summary_rows = []
    total_records = 0
    write_errors = 0

    for schema_type in sorted(all_records.keys()):
        records = all_records[schema_type]
        output_path = OUTPUT_DIR / f"{schema_type}.jsonl"

        # Compute quality stats before writing (PIPE-02)
        stats = compute_quality_stats(records, schema_type)

        write_error_count = 0
        written = 0
        try:
            with open(output_path, "w", encoding="utf-8") as out:
                for rec_idx, record in enumerate(records):
                    try:
                        out.write(json.dumps(record, ensure_ascii=False) + "\n")
                        written += 1
                    except (TypeError, ValueError) as e:
                        # Log which record failed and continue to the next
                        source_id = record.get("_source_id", "unknown")
                        logging.error(
                            "Failed to serialise record %d in %s (source_id=%s): %s -- skipping record",
                            rec_idx, schema_type, source_id, e,
                        )
                        write_error_count += 1
        except OSError as e:
            logging.error(
                "Failed to open output file for %s: %s -- schema_type skipped",
                schema_type, e,
            )
            write_errors += 1
            continue

        size_kb = output_path.stat().st_size // 1024
        total_records += written
        summary_rows.append((schema_type, written, size_kb, stats, write_error_count))

        if write_error_count:
            logging.warning(
                "  Wrote %-30s  %7d records (%d serialise errors)  %8d KB",
                schema_type, written, write_error_count, size_kb,
            )
            write_errors += write_error_count
        else:
            logging.info(
                "  Wrote %-30s  %7d records  %8d KB  -> %s",
                schema_type, written, size_kb, output_path.name,
            )

    elapsed = time.time() - start

    # Print summary table
    print()
    print("=" * 80)
    print("HuggingFace Export Summary")
    print("=" * 80)
    print(f"{'Schema type':<30}  {'Records':>9}  {'Size KB':>8}  {'Empty%':>6}  {'wc med':>7}")
    print("-" * 80)
    for schema_type, count, size_kb, stats, werrs in summary_rows:
        empty_pct = (stats["empty_content"] / count * 100) if count else 0
        wc_med = median(stats["word_counts"])
        wc_str = str(wc_med) if wc_med is not None else "n/a"
        warn_flag = " !" if empty_pct > 5 else ""
        print(
            f"{schema_type:<30}  {count:>9,}  {size_kb:>8,}  {empty_pct:>5.1f}%{warn_flag}  {wc_str:>7}"
        )
    print("-" * 80)
    print(f"{'TOTAL':<30}  {total_records:>9,}")
    print()
    print(f"Output directory : {OUTPUT_DIR}")
    print(f"Files processed  : {file_count}")
    print(f"Load errors      : {error_count}")
    print(f"Write errors     : {write_errors}")
    print(f"Elapsed          : {elapsed:.1f}s")
    print("=" * 80)

    # API-08: overall completeness check
    total_errors = error_count + write_errors
    if total_errors > 0:
        logging.warning("Export completed with %d total errors -- check log", total_errors)
        sys.exit(1)
    else:
        logging.info("Export complete. [DONE]")


if __name__ == "__main__":
    run_export()
