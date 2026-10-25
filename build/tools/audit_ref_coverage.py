"""Audit explicit normalized references in independently verified release rows.

Normal invocation requires --root, --release and --selection. Source-bound OSIS
arrays and explicit normalized scripture targets are supported; other shapes remain
visible as unsupported. Literal source passages are never guessed into OSIS.
A nonzero exit indicates failed, unverified or unsupported coverage.

Historical invocation: --legacy-data [--category commentaries]. This explicit
branch reads old data/ cross_references and writes the historical report next
to this tool. It does not establish current-library reference coverage.
"""

import argparse
import hashlib
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

from build.lib.paths import REPO_ROOT  # noqa: E402
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

log = logging.getLogger(__name__)


def _book_code(osis_ref: str) -> str:
    """Extract the book OSIS code from a ref string (e.g. 'Gen.1.1' -> 'Gen')."""
    return osis_ref.split(".")[0].split("-")[0]


def _validate_ref_verbose(osis_ref: str, validate_fn) -> tuple[str, str]:
    """Call validate_osis_ref and return (bucket, reason).

    Buckets: 'valid-bsb', 'valid-kjv-only', 'deuterocanon', 'failed'.
    """
    if "-" in osis_ref:
        # The shared validator drops positive endpoint reasons for ranges.
        valid, reason = validate_fn(osis_ref)
        if not valid:
            return "failed", reason
        start, end = osis_ref.split("-", 1)
        endpoints = [_validate_ref_verbose(start, validate_fn),
                     _validate_ref_verbose(end, validate_fn)]
        for bucket in ("failed", "unverified", "deuterocanon", "valid-kjv-only"):
            if any(item[0] == bucket for item in endpoints):
                return bucket, "; ".join(item[1] for item in endpoints if item[1])
        return "valid-bsb", ""
    book = _book_code(osis_ref)
    if book in DEUTEROCANONICAL_BOOK_CODES:
        return "deuterocanon", f"book {book} is deuterocanonical"

    valid, reason = validate_fn(osis_ref)
    if not valid:
        return "failed", reason
    if any(marker in reason.lower() for marker in
           ("unavailable", "no verse index", "known omission", "versification offset")):
        return "unverified", reason
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
        "unverified_refs": [],
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
                    elif bucket == "unverified":
                        counts["unverified"] = counts.get("unverified", 0) + 1
                        results["unverified_refs"].append({
                            "file": rel_path, "entry_id": entry_id,
                            "ref": ref, "reason": reason,
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


def legacy_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--category",
        default=None,
        help="Only audit this data category (e.g. commentaries). Default: all.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )
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

    log.info("  unverified:       %d", c.get("unverified", 0))

    if c["failed"] == 0 and c["deuterocanon"] == 0 and not c.get("unverified", 0):
        log.info("---")
        log.info("Layer 3 clear: no refs fail both indexes, no deuterocanonical refs "
                 "found in data files.")

    # Write full report
    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "category_filter": args.category,
        "counts": c,
        "failed_refs": results["failed_refs"],
        "kjv_only_summary": {
            "total": len(results["kjv_only_refs"]),
            "unique_refs": sorted(set(x["ref"] for x in results["kjv_only_refs"])),
        },
        "deuterocanon_refs": results["deuterocanon_refs"],
        "unverified_refs": results["unverified_refs"],
    }
    OUTPUT_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("Report written to %s", OUTPUT_FILE)
    log.info("Completed in %.1fs", elapsed)
    return 1 if c["failed"] or c["deuterocanon"] or c.get("unverified", 0) else 0


def audit_release(root: Path, release: Path, selection: dict, validate_fn) -> dict:
    """Audit explicit normalized OSIS only; account for all unsupported rows."""
    from build.tools.report_release_stats import release_statistics
    from ocd_kernel.library._common import PipelineError

    report_path = release / "internal/release-report.json"
    report_bytes = report_path.read_bytes()
    release_statistics(root, release, selection)
    if report_path.read_bytes() != report_bytes:
        raise PipelineError("release report changed during verification")
    report = json.loads(report_bytes)
    findings = []
    unsupported = []
    rows_scanned = 0
    def references(value, pointer=""):
        if isinstance(value, dict):
            if value.get("derivation") == "explicit-target-syntax-v1":
                yield pointer + "/normalized", value["normalized"]
            elif value.get("normalization_status") in ("unsupported-explicit-target", "no-explicit-target"):
                yield pointer, None
            elif "osis" in value and "raw" in value:
                for index, ref in enumerate(value["osis"]):
                    yield pointer + "/osis/" + str(index), ref
            else:
                for key, child in value.items():
                    yield from references(child, pointer + "/" + key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from references(child, pointer + "/" + str(index))
    for config in report["configurations"]:
        content = (release / config["path"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != config["sha256"]:
            raise PipelineError("release rows changed after verification")
        for line in content.decode("utf-8").splitlines():
            row = json.loads(line)
            rows_scanned += 1
            identity = {"work_id": row["work_id"], "record_id": row["record_id"],
                        "category": row["category"]}
            if row["category"] not in ("catechisms", "doctrinal_documents", "bible",
                                       "commentary", "devotionals", "prayers", "sermons", "prose"):
                unsupported.append({**identity, "reason": "category has no supported normalized OSIS extraction; literal text and record links are not interpreted"})
                continue
            for pointer, ref in references(row):
                if ref is None:
                    unsupported.append({**identity, "pointer": pointer,
                                        "reason": "source reference has no supported explicit normalized target"})
                    continue
                bucket, reason = _validate_ref_verbose(ref, validate_fn)
                findings.append({**identity, "pointer": pointer, "reference": ref,
                                 "outcome": bucket, "reason": reason})
    complete = not unsupported and all(item["outcome"] in ("valid-bsb", "valid-kjv-only") for item in findings)
    return {"status": "pass" if complete else "incomplete", "rows_scanned": rows_scanned,
            "release_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "references": findings, "unsupported_rows": unsupported,
            "scope": "Source-bound OSIS arrays and explicit normalized scripture targets; no reference inference"}


def main(argv: list[str] | None = None) -> int:
    from ocd_kernel.library._common import PipelineError
    from ocd_kernel.release.selection import load_release_selection
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "--legacy-data":
        return legacy_main(arguments[1:])
    parser = argparse.ArgumentParser(description="Audit explicit references in a verified release; unsupported formats remain visible. Historical data requires --legacy-data first.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    args = parser.parse_args(arguments)
    from build.scripts.validate_osis import validate_osis_ref
    try:
        result = audit_release(args.root, args.release, load_release_selection(args.selection), validate_osis_ref)
    except (PipelineError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
