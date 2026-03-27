"""creeds_json_catechism.py
Parse a Creeds.json catechism document and map to the catechism_qa schema.

Generic -- handles all Creeds.json catechisms. Add an entry to DOCUMENT_CONFIGS
for any new catechism to set tradition, audience, era, and other metadata.

Usage:
    py -3 build/parsers/creeds_json_catechism.py --source raw/Creeds.json/creeds/heidelberg_catechism.json
    py -3 build/parsers/creeds_json_catechism.py --source raw/Creeds.json/creeds/westminster_larger_catechism.json
    py -3 build/parsers/creeds_json_catechism.py --all
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "data" / "catechisms"
CREEDS_DIR = REPO_ROOT / "raw" / "Creeds.json" / "creeds"
LOG_FILE = Path(__file__).resolve().parent / "creeds_json_catechism.log"

SCRIPT_VERSION = "v1.0.0"

# Date raw Creeds.json data was downloaded to disk -- update if data is re-downloaded
SOURCE_DOWNLOAD_DATE = "2026-03-27"

# ---------------------------------------------------------------------------
# Per-document config
# Keyed by source filename stem (without .json).
# ---------------------------------------------------------------------------

DOCUMENT_CONFIGS = {
    "heidelberg_catechism": {
        "document_id": "heidelberg-catechism",
        "tradition": ["reformed", "continental-reformed"],
        "tradition_notes": (
            "Composed by Zacharias Ursinus and Caspar Olevianus in 1563 for the Palatinate. "
            "One of the Three Forms of Unity; widely used in Continental Reformed churches."
        ),
        "era": "reformation",
        "audience": "lay",
    },
    "westminster_larger_catechism": {
        "document_id": "westminster-larger-catechism",
        "tradition": ["reformed", "presbyterian"],
        "tradition_notes": (
            "Produced by the Westminster Assembly (1643-1652). "
            "Companion to the Shorter Catechism; intended for public preaching and teaching."
        ),
        "era": "post-reformation",
        "audience": "clergy",
    },
    "keachs_catechism": {
        "document_id": "keachs-catechism",
        "tradition": ["reformed", "particular-baptist"],
        "tradition_notes": (
            "Baptist catechism compiled by William Collins (1680), revised by Benjamin Keach. "
            "Closely follows the Westminster Shorter Catechism with Baptist distinctives."
        ),
        "era": "post-reformation",
        "audience": "lay",
    },
    "1695_baptist_catechism": {
        "document_id": "1695-baptist-catechism",
        "tradition": ["reformed", "particular-baptist"],
        "tradition_notes": (
            "Baptist catechism (1695) by William Collins. "
            "An early Particular Baptist catechism drawing on Westminster."
        ),
        "era": "post-reformation",
        "audience": "lay",
    },
    "catechism_for_young_children": {
        "document_id": "catechism-for-young-children",
        "tradition": ["reformed", "presbyterian"],
        "tradition_notes": (
            "Elementary catechism for children by Joseph Engles (1840). "
            "Preparatory instruction before the Westminster Shorter Catechism."
        ),
        "era": "modern",
        "audience": "children",
    },
    "puritan_catechism": {
        "document_id": "puritan-catechism",
        "tradition": ["reformed", "puritan"],
        "tradition_notes": (
            "Catechism compiled by Charles Spurgeon (1855). "
            "Draws on the Westminster Shorter Catechism with slight adaptations."
        ),
        "era": "modern",
        "audience": "lay",
    },
    "matthew_henrys_scripture_catechism": {
        "document_id": "matthew-henrys-scripture-catechism",
        "tradition": ["reformed", "puritan", "nonconformist"],
        "tradition_notes": (
            "Scripture Catechism in the Method of the Assembly's by Matthew Henry (1703). "
            "Each answer supported by scriptural sub-questions and answers."
        ),
        "era": "post-reformation",
        "audience": "lay",
    },
    "exposition_of_the_assemblies_catechism": {
        "document_id": "exposition-of-the-assemblies-catechism",
        "tradition": ["reformed", "puritan", "nonconformist"],
        "tradition_notes": (
            "Exposition of the Assembly's Shorter Catechism by John Flavel (1688). "
            "Each question expanded with explanatory sub-questions."
        ),
        "era": "post-reformation",
        "audience": "lay",
    },
    "shorter_catechism_explained": {
        "document_id": "shorter-catechism-explained",
        "tradition": ["reformed", "presbyterian"],
        "tradition_notes": (
            "The Shorter Catechism Explained from Scripture by James Fisher (1765). "
            "Westminster Shorter Catechism with expository sub-questions."
        ),
        "era": "post-reformation",
        "audience": "lay",
    },
}

# All catechism source filenames to process with --all
ALL_CATECHISMS = list(DOCUMENT_CONFIGS.keys())

# Valid tradition values (must match catechism_qa.schema.json enum)
VALID_TRADITIONS = {
    "reformed", "lutheran", "anglican", "baptist", "methodist",
    "catholic", "orthodox", "ecumenical", "non-denominational",
    "puritan", "nonconformist", "patristic", "wesleyan",
    "presbyterian", "particular-baptist", "continental-reformed",
}

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

_log_lines: list = []


def log(msg: str) -> None:
    """Print to console and buffer for log file."""
    print(msg)
    _log_lines.append(msg)


def flush_log() -> None:
    """Append buffered log lines to the log file."""
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"=== Run at {ts} ===\n")
        for line in _log_lines:
            f.write(line + "\n")
        f.write("\n")


# ---------------------------------------------------------------------------
# Proof mapper (same structure as creeds_json_confession.py)
# ---------------------------------------------------------------------------


def map_proofs(raw_proofs: list) -> list:
    """Map Creeds.json Proofs to our proof schema.

    Input:  [{"Id": 1, "References": ["1Cor.6.19", "John.15.12,John.15.17", ...]}, ...]
    Output: [{"id": 1, "references": [{"raw": "...", "osis": ["..."]}, ...]}, ...]

    Some Creeds.json catechism references join multiple OSIS refs with commas
    (e.g. "John.15.12,John.15.17"). The raw field preserves the original string;
    osis splits on commas so each element is a single valid OSIS reference.
    Sorted by Id for consistency.
    """
    mapped = []
    for proof in sorted(raw_proofs, key=lambda p: p.get("Id", 0)):
        refs = []
        for ref_str in proof.get("References", []):
            osis_parts = [r.strip() for r in ref_str.split(",") if r.strip()]
            refs.append({"raw": ref_str, "osis": osis_parts})
        mapped.append({
            "id": proof["Id"],
            "references": refs,
        })
    return mapped


# ---------------------------------------------------------------------------
# Item mapper
# ---------------------------------------------------------------------------


def _parse_sort_key(number) -> int:
    """Parse the Number field to an integer sort key.

    Most catechisms use plain integers. Falls back to 0 on failure.
    """
    try:
        return int(str(number).strip())
    except (ValueError, TypeError):
        return 0


def _map_sub_questions(sub_questions: list) -> list:
    """Map SubQuestions list to our schema format."""
    result = []
    for sq in sub_questions:
        entry = {
            "item_id": str(sq.get("Number", "")),
            "question": (sq.get("Question") or "").strip(),
            "answer": (sq.get("Answer") or "").strip(),
        }
        result.append(entry)
    return result


def map_item(item: dict, document_id: str) -> dict:
    """Map one Creeds.json catechism Q&A to a catechism_qa entry."""
    number = item["Number"]
    proofs_raw = item.get("Proofs") or []
    sub_questions_raw = item.get("SubQuestions") or []

    entry = {
        "document_id": document_id,
        "item_id": str(number),
        "sort_key": _parse_sort_key(number),
        "question": (item.get("Question") or "").strip(),
        "answer": (item.get("Answer") or "").strip() or None,
        "answer_with_proofs": item.get("AnswerWithProofs") or None,
        "proofs": map_proofs(proofs_raw),
        "group": None,
        "sub_questions": _map_sub_questions(sub_questions_raw) if sub_questions_raw else None,
    }
    return entry


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------


def build_meta(
    source_hash: str,
    doc_cfg: dict,
    metadata: dict,
    process_date: str,
    completeness: str = "full",
) -> dict:
    """Build the resource-level meta envelope."""
    authors = metadata.get("Authors") or []
    year_raw = metadata.get("Year")
    try:
        pub_year = int(str(year_raw).strip()) if year_raw else None
    except ValueError:
        log(f"WARNING: Could not parse year '{year_raw}' as integer -- setting to None")
        pub_year = None

    return {
        "id": doc_cfg["document_id"],
        "title": metadata.get("Title", doc_cfg["document_id"]),
        "author": authors[0] if authors else None,
        "author_birth_year": None,
        "author_death_year": None,
        "contributors": authors[1:],
        "original_publication_year": pub_year,
        "language": "en",
        "original_language": "en",
        "tradition": doc_cfg["tradition"],
        "tradition_notes": doc_cfg.get("tradition_notes"),
        "era": doc_cfg.get("era"),
        "audience": doc_cfg.get("audience"),
        "license": "cc0-1.0",
        "schema_type": "catechism_qa",
        "schema_version": "2.1.0",
        "completeness": completeness,
        "provenance": {
            "source_url": metadata.get("SourceUrl") or "",
            "source_format": "JSON",
            "source_edition": "Creeds.json (github.com/NonlinearFruit/Creeds.json)",
            "download_date": SOURCE_DOWNLOAD_DATE,
            "source_hash": f"sha256:{source_hash}",
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/creeds_json_catechism.py@{SCRIPT_VERSION}"
            ),
            "processing_date": process_date,
            "notes": (
                "Proof texts from Creeds.json are already in OSIS format -- "
                "raw and osis fields are identical."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Main processor
# ---------------------------------------------------------------------------


def process_catechism(
    source_file: Path,
    output_file: Path,
    doc_cfg: dict,
) -> bool:
    """Parse one Creeds.json catechism file and write output. Returns True on success."""
    log(f"Source: {source_file}")
    log(f"Output: {output_file}")

    # Load source
    try:
        raw_text = source_file.read_text(encoding="utf-8")
        source_data = json.loads(raw_text)
    except (OSError, json.JSONDecodeError) as exc:
        log(f"ERROR: Failed to load source: {exc}")
        log(f"  -> Check that raw/Creeds.json is present at {CREEDS_DIR}")
        return False

    source_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

    metadata = source_data.get("Metadata", {})
    items_raw = source_data.get("Data", [])

    log(f"Title:  {metadata.get('Title', '(unknown)')}")
    log(f"Year:   {metadata.get('Year', '(unknown)')}")
    log(f"Items in source: {len(items_raw)}")

    document_id = doc_cfg["document_id"]
    entries = []
    errors = 0
    empty_q = 0
    empty_a = 0

    skipped_placeholder = 0
    for i, item in enumerate(items_raw):
        number = item.get("Number", "")
        # Skip '?' placeholder rows -- source data gaps where question/answer are unknown
        if str(number) == "?":
            skipped_placeholder += 1
            continue
        try:
            entry = map_item(item, document_id)
            if not entry["question"]:
                log(f"WARNING: Q{number} has empty question")
                empty_q += 1
            if not entry["answer"]:
                log(f"WARNING: Q{number} has empty answer")
                empty_a += 1
            entries.append(entry)
        except Exception as exc:
            log(f"ERROR: Item {number} failed: {exc}")
            errors += 1
    if skipped_placeholder:
        log(f"NOTE: Skipped {skipped_placeholder} '?' placeholder items (source data gaps)")

    # Quality stats
    has_proofs = sum(1 for e in entries if e["proofs"])
    has_sub_q = sum(1 for e in entries if e["sub_questions"])
    has_awp = sum(1 for e in entries if e["answer_with_proofs"])
    total_words = sum(
        len(((e["question"] or "") + " " + (e["answer"] or "")).split()) for e in entries
    )
    log(f"Mapped: {len(entries)} entries, {errors} errors")
    log(f"  empty questions: {empty_q}, empty answers: {empty_a}")
    log(f"  entries with proofs: {has_proofs}/{len(entries)}")
    log(f"  entries with answer_with_proofs: {has_awp}/{len(entries)}")
    log(f"  entries with sub_questions: {has_sub_q}/{len(entries)}")
    log(f"  total words (Q+A): {total_words}")

    process_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Completeness: partial if source has empty answers (source data gaps)
    completeness = "partial" if empty_a > 0 else "full"
    if empty_a > 0:
        log(f"NOTE: {empty_a} empty answers -- marking completeness as 'partial' (source data gaps)")

    output = {
        "meta": build_meta(source_hash, doc_cfg, metadata, process_date, completeness=completeness),
        "data": entries,
    }

    # Write output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(output_file, "w", encoding="utf-8", newline="\n") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError as exc:
        log(f"ERROR: Failed to write output: {exc}")
        log(f"  -> Check that {output_file.parent} exists and is writable")
        return False

    size_kb = output_file.stat().st_size / 1024
    log(f"Wrote {output_file} ({size_kb:.0f} KB)")

    return errors == 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse a Creeds.json catechism to catechism_qa schema"
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--source",
        metavar="PATH",
        help="Path to source Creeds.json catechism JSON file (absolute or repo-relative)",
    )
    source_group.add_argument(
        "--all",
        action="store_true",
        help="Process all known catechisms in DOCUMENT_CONFIGS",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Override output file path (absolute or repo-relative; ignored with --all)",
    )
    args = parser.parse_args()

    start = datetime.now(timezone.utc)
    log(f"creeds_json_catechism.py {SCRIPT_VERSION}")

    if args.all:
        total_ok = 0
        total_fail = 0
        total = len(ALL_CATECHISMS)
        for idx, stem in enumerate(ALL_CATECHISMS, start=1):
            log("")
            log(f"--- [{idx}/{total}] {stem} ---")
            source_file = CREEDS_DIR / f"{stem}.json"
            doc_cfg = DOCUMENT_CONFIGS[stem]
            output_file = OUTPUT_DIR / f"{doc_cfg['document_id']}.json"
            ok = process_catechism(source_file, output_file, doc_cfg)
            if ok:
                total_ok += 1
            else:
                total_fail += 1
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        log("")
        log(f"All done in {elapsed:.1f}s: {total_ok} ok, {total_fail} failed")
        if total_fail:
            log(f"FAILED: check log at {LOG_FILE}")
    else:
        source_file = Path(args.source)
        if not source_file.is_absolute():
            source_file = REPO_ROOT / source_file

        if not source_file.exists():
            log(f"ERROR: Source file not found: {source_file}")
            flush_log()
            sys.exit(1)

        stem = source_file.stem

        if stem in DOCUMENT_CONFIGS:
            doc_cfg = dict(DOCUMENT_CONFIGS[stem])
            log(f"Config: using DOCUMENT_CONFIGS entry for '{stem}'")
        else:
            doc_cfg = {
                "document_id": stem.replace("_", "-"),
                "tradition": [],
                "tradition_notes": None,
                "era": None,
                "audience": None,
            }
            log(f"WARNING: No DOCUMENT_CONFIGS entry for '{stem}' -- using defaults. Consider adding one.")

        # Validate tradition values
        for t in doc_cfg.get("tradition", []):
            if t not in VALID_TRADITIONS:
                log(f"WARNING: Tradition value '{t}' not in VALID_TRADITIONS -- may fail schema validation")

        if args.output:
            output_file = Path(args.output)
            if not output_file.is_absolute():
                output_file = REPO_ROOT / output_file
        else:
            output_file = OUTPUT_DIR / f"{doc_cfg['document_id']}.json"

        try:
            success = process_catechism(source_file, output_file, doc_cfg)
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            log("")
            if success:
                log(f"Done in {elapsed:.1f}s. Output: {output_file}")
                log(f"  -> See counts above. Validate: py -3 build/validate.py {output_file.relative_to(REPO_ROOT)}")
            else:
                log(f"Completed with errors in {elapsed:.1f}s. Check log: {LOG_FILE}")
        finally:
            flush_log()

        if not success:
            sys.exit(1)

    flush_log()


if __name__ == "__main__":
    main()
