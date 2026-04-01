"""audit_ref_coverage.py
Audit all cross_reference OSIS refs across the data directory.

For each ref in every data file's cross_references field, validate it against
the BSB verse index and the KJV index.  Buckets results into:

  - valid-bsb      : present in BSB critical text
  - valid-kjv-only : present in KJV/TR but absent from BSB (Layer 1 disputes)
  - deuterocanon   : book code is from the deuterocanonical/apocryphal set
                     (would pass the validator but can't be checked for existence)
  - failed         : fails both indexes -- invalid verse ref or genuine data issue

Output: console summary + build/tools/audit_ref_coverage_report.json

The "failed" bucket is the actionable set for Layer 3: these are refs that
slipped through normalisation as valid OSIS strings but point to verses that
don't exist in either the KJV or BSB canon.  Investigate each one to determine
whether it is a normaliser bug, an OCR artefact, or a source-data error.

Usage:
    py -3 build/tools/audit_ref_coverage.py [--category commentaries]
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"
# Output and log co-located with the tool (not a pipeline artifact, so not in build/bible_data/).
OUTPUT_FILE = Path(__file__).resolve().parent / "audit_ref_coverage_report.json"
LOG_FILE = Path(__file__).resolve().parent / "audit_ref_coverage.log"

# Deuterocanonical/apocryphal OSIS book codes (same set as validate_osis.py).
# Refs with these book codes can't be existence-checked against the Protestant
# verse indexes; they are counted separately.
DEUTEROCANONICAL_BOOK_CODES = frozenset({
    "Tob", "Jdt", "Wis", "Sir", "Bar", "EpJer",
    "1Macc", "2Macc",
    "PrAzar", "SgThree", "Sus", "Bel",
    "AddEsth", "EsthGr",
    "PrMan",
    "1Esd", "2Esd", "3Macc", "4Macc", "Ps151", "Odes", "PsSol",
    "1En", "Jub",
})

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def _book_code(osis_ref: str) -> str:
    """Extract the book OSIS code from a ref string (e.g. 'Gen.1.1' -> 'Gen')."""
    return osis_ref.split(".")[0].split("-")[0]


def _validate_ref_verbose(osis_ref: str, validate_fn) -> tuple[str, str]:
    """Call validate_osis_ref and return (bucket, reason).

    Buckets: 'valid-bsb', 'valid-kjv-only', 'deuterocanon', 'failed'.
    """
    book = _book_code(osis_ref)
    if book in DEUTEROCANONICAL_BOOK_CODES:
        return "deuterocanon", f"book {book} is deuterocanonical"

    valid, reason = validate_fn(osis_ref)
    if not valid:
        return "failed", reason
    if "KJV" in reason or "kjv" in reason.lower():
        return "valid-kjv-only", reason
    return "valid-bsb", reason


def audit_data(data_root: Path, category_filter: str | None, validate_fn) -> dict:
    """Walk data directories, validate all cross_reference refs.

    Returns a results dict with counts and lists of failed refs.
    """
    results = {
        "counts": {
            "files_scanned": 0,
            "entries_scanned": 0,
            "entries_with_refs": 0,
            "refs_total": 0,
            "valid_bsb": 0,
            "valid_kjv_only": 0,
            "deuterocanon": 0,
            "failed": 0,
        },
        "failed_refs": [],   # {file, entry_id, ref, reason}
        "kjv_only_refs": [], # {file, entry_id, ref}
        "deuterocanon_refs": [], # {file, entry_id, ref}
    }
    counts = results["counts"]

    # Walk categories
    for cat_dir in sorted(data_root.iterdir()):
        if not cat_dir.is_dir():
            continue
        if category_filter and cat_dir.name != category_filter:
            continue

        json_files = sorted(cat_dir.rglob("*.json"))
        if not json_files:
            continue

        n_files = len(json_files)
        log.info("Scanning category: %s (%d files)", cat_dir.name, n_files)

        for file_idx, json_file in enumerate(json_files, 1):
            if file_idx % 50 == 0 or file_idx == n_files:
                log.info("  Progress: %d / %d files", file_idx, n_files)
            try:
                with open(json_file, encoding="utf-8") as f:
                    doc = json.load(f)
            except Exception as exc:
                log.warning("Could not read %s: %s", json_file, exc)
                continue

            counts["files_scanned"] += 1
            entries = doc.get("data", []) if isinstance(doc, dict) else []
            rel_path = str(json_file.relative_to(data_root))

            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                counts["entries_scanned"] += 1
                refs = entry.get("cross_references", [])
                if not refs or not isinstance(refs, list):
                    continue
                counts["entries_with_refs"] += 1
                entry_id = entry.get("entry_id", "(no id)")

                for ref in refs:
                    if not isinstance(ref, str):
                        continue
                    counts["refs_total"] += 1

                    bucket, reason = _validate_ref_verbose(ref, validate_fn)

                    if bucket == "valid-bsb":
                        counts["valid_bsb"] += 1
                    elif bucket == "valid-kjv-only":
                        counts["valid_kjv_only"] += 1
                        results["kjv_only_refs"].append({
                            "file": rel_path,
                            "entry_id": entry_id,
                            "ref": ref,
                        })
                    elif bucket == "deuterocanon":
                        counts["deuterocanon"] += 1
                        results["deuterocanon_refs"].append({
                            "file": rel_path,
                            "entry_id": entry_id,
                            "ref": ref,
                        })
                    else:  # failed
                        counts["failed"] += 1
                        results["failed_refs"].append({
                            "file": rel_path,
                            "entry_id": entry_id,
                            "ref": ref,
                            "reason": reason,
                        })

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--category",
        default=None,
        help="Only audit this data category (e.g. commentaries). Default: all.",
    )
    args = parser.parse_args()

    start = time.time()
    log.info("=== audit_ref_coverage.py ===")
    if args.category:
        log.info("Filtering to category: %s", args.category)

    # Import validate_osis lazily so the module path resolves correctly.
    sys.path.insert(0, str(REPO_ROOT))
    from build.scripts.validate_osis import validate_osis_ref

    results = audit_data(DATA_ROOT, args.category, validate_osis_ref)
    c = results["counts"]

    elapsed = time.time() - start

    # Summary
    log.info("---")
    log.info("Files scanned:      %d", c["files_scanned"])
    log.info("Entries scanned:    %d", c["entries_scanned"])
    log.info("  with refs:        %d  (%.1f%%)",
             c["entries_with_refs"], 100 * c["entries_with_refs"] / max(c["entries_scanned"], 1))
    log.info("Refs total:         %d", c["refs_total"])
    log.info("  valid-bsb:        %d  (%.1f%%)",
             c["valid_bsb"], 100 * c["valid_bsb"] / max(c["refs_total"], 1))
    log.info("  valid-kjv-only:   %d  (%.1f%%)",
             c["valid_kjv_only"], 100 * c["valid_kjv_only"] / max(c["refs_total"], 1))
    log.info("  deuterocanon:     %d", c["deuterocanon"])
    log.info("  failed:           %d", c["failed"])

    if results["failed_refs"]:
        log.info("---")
        log.info("FAILED refs (first 50):")
        for item in results["failed_refs"][:50]:
            log.info("  %-35s  %s  -- %s", item["file"][:35], item["ref"], item["reason"])

    if results["deuterocanon_refs"]:
        log.info("---")
        log.info("Deuterocanonical refs found (%d) -- these passed normalisation "
                 "but cannot be existence-checked:", len(results["deuterocanon_refs"]))
        for item in results["deuterocanon_refs"][:20]:
            log.info("  %-35s  %s", item["file"][:35], item["ref"])

    if c["failed"] == 0 and c["deuterocanon"] == 0:
        log.info("---")
        log.info("Layer 3 clear: no refs fail both indexes, no deuterocanonical refs "
                 "found in data files.")

    # Write full report
    report = {
        "generated": __import__("datetime").date.today().isoformat(),
        "category_filter": args.category,
        "counts": c,
        "failed_refs": results["failed_refs"],
        "kjv_only_summary": {
            "total": len(results["kjv_only_refs"]),
            "unique_refs": sorted(set(x["ref"] for x in results["kjv_only_refs"])),
        },
        "deuterocanon_refs": results["deuterocanon_refs"],
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    log.info("Report written to %s", OUTPUT_FILE)
    log.info("Completed in %.1fs", elapsed)


if __name__ == "__main__":
    main()
