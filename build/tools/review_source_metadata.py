"""Prepare opt-in metadata reviews, verify receipts, or extract exact evidence.

Run a subcommand with --help for its explicit input/output contract. No mode
writes metadata sidecars, changes source authority, or approves semantic claims.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from build.lib import source_metadata as sm
from build.lib import source_metadata_review as review


def _print_error(exc: BaseException, *, malformed: bool = False) -> None:
    """Keep diagnostics printable on strict legacy Windows console encodings."""

    prefix = "metadata review error: malformed input: " if malformed else "metadata review error: "
    message = f"{prefix}{exc}".encode("ascii", "backslashreplace").decode("ascii")
    print(message, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    check = modes.add_parser("preflight", help="check a complete-subject selection before semantic review")
    check.add_argument("--root", type=Path, required=True, help="data/evidence checkout; runtime remains this installed code")
    check.add_argument("--worklist", type=Path, required=True)
    check.add_argument("--decisions", type=Path, required=True, help="one exact candidate JSON file")
    check.add_argument("--selection", type=Path, required=True, help="independently frozen subjects plus worklist_sha256")
    check.add_argument("--predecessor", type=Path, help="exact previously reviewed candidate for complete delta")
    check.add_argument("--notes", type=Path, action="append", default=[])
    check.add_argument(
        "--authority-comparisons", type=Path,
        help="optional explicit current-authority comparison input JSON",
    )
    check.add_argument("--output-dir", type=Path, required=True, help="new review-only directory; existing directories refused")
    verify = modes.add_parser("verify-receipt", help="rehash all explicit receipt artifacts; not a source reverification")
    verify.add_argument("receipt", type=Path)
    impact = modes.add_parser("impact", help="report exactly which claims need evidence rechecking; does not renew approval")
    impact.add_argument("--root", type=Path, required=True)
    impact.add_argument("--review", type=Path, required=True, help="retained review.json with historical bindings")
    impact.add_argument("--receipt", type=Path, help="optional retained receipt with current-authority snapshots")
    impact.add_argument("--path", action="append", default=None, help="limit to this evidence or authority path; repeatable")
    impact.add_argument("--full-json", action="store_true", help="include full historical bindings and current evidence; default is a compact summary")
    extract = modes.add_parser("extract", help="extract exact UTF-8 JSON bindings directly from retained bytes")
    extract.add_argument("--root", type=Path, required=True)
    extract.add_argument("--requests", type=Path, required=True, help="JSON object containing requests array")
    extract.add_argument("--output", type=Path, required=True, help="new file; existing files refused")
    args = parser.parse_args(argv)
    try:
        if args.mode == "preflight":
            receipt, view, delta = review.preflight(
                args.root, worklist_path=args.worklist, decisions_path=args.decisions,
                selection_path=args.selection, predecessor_path=args.predecessor, notes=tuple(args.notes),
                authority_comparisons_path=args.authority_comparisons,
            )
            receipt["artifacts"]["cli"] = review._artifact_identity(__file__, name="cli")
            review.write_review(args.output_dir, args.root, receipt, view, delta)
            print(json.dumps({"mechanical_status": receipt["mechanical_status"], "semantic_review": "required",
                              "counts": receipt["counts"], "failures": receipt["failures"],
                              "receipt": str(review._resolved_path(args.output_dir, field="review output") / "receipt.json")},
                      ensure_ascii=True))
            return 0 if receipt["mechanical_status"] == "pass" else 2
        if args.mode == "verify-receipt":
            issues = review.verify_receipt(sm.load_json(args.receipt))
            print(json.dumps({"artifact_identity": "current" if not issues else "stale", "issues": issues}, ensure_ascii=True))
            return 2 if issues else 0
        if args.mode == "impact":
            from build.lib.source_metadata_impact import recheck_claim_evidence

            result = recheck_claim_evidence(
                args.root, review_view=sm.load_json(args.review),
                receipt=sm.load_json(args.receipt) if args.receipt else None,
                paths=args.path,
            )
            output = result if args.full_json else {
                name: result[name] for name in ("schema_version", "notice", "scope", "counts", "receipt_issues")
            }
            if not args.full_json:
                output["affected_claims"] = [
                    {name: row[name] for name in ("subject", "dimension", "claim_id", "worklist_item_id", "scope", "status")}
                    for row in result["claims"] if row["status"] != "unchanged"
                ]
                output["detail_option"] = "--full-json"
            print(json.dumps(output, ensure_ascii=True))
            return 2 if any(result["counts"].get(state, 0) for state in ("changed", "missing", "unverifiable", "receipt_issues")) else 0
        requests = sm.load_json(args.requests).get("requests")
        if not isinstance(requests, list):
            raise sm.MetadataError("extraction input requires a requests array")
        result = review.extract_bindings(args.root, requests)
        protected = [args.requests]
        protected.extend(
            sm._resolve(args.root, binding["path"], field="extraction path")
            for binding in result["bindings"].values()
        )
        output = review._safe_output_path(
            args.output,
            args.root,
            field="extraction output",
            protected_paths=tuple(protected),
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(sm.canonical_bytes(result))
        print(json.dumps({"bindings": len(result["bindings"]), "output": review.file_identity(output)}, ensure_ascii=True))
        return 0
    except (sm.MetadataError, OSError, UnicodeError) as exc:
        _print_error(exc)
        return 2
    except (TypeError, KeyError) as exc:
        _print_error(exc, malformed=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
