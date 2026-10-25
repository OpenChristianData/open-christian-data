"""Report, verify, and generate the bounded source-metadata projection.

Examples::

    py -3 -m build.tools.report_source_metadata --root . --check
    py -3 -m build.tools.report_source_metadata --root . --verify-evidence
    py -3 -m build.tools.report_source_metadata --root . --verify-evidence --report-file evidence-report.json
    py -3 -m build.tools.report_source_metadata --root . --write
    py -3 -m build.tools.report_source_metadata --root . \
        --subject-kind catalog --subject augustine-against-two-letters-pelagians

The writer only owns ``metadata/source-evidence/**``.  It refuses to write any
sidecar or index when a claimed evidence/adoption edge is unverifiable.
Report modes print a bounded summary by default. Use --full-report for the
complete report on stdout, or --report-file to retain the complete report as
an exact UTF-8 JSON artifact; a report file does not make stdout unbounded.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from build.lib import source_metadata_review as review
from build.lib.source_metadata import (
    MetadataError,
    build_report,
    check_outputs_detailed,
    lookup_sidecar,
    persist_subject,
    schema_enum,
    write_outputs,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="repository checkout root")
    parser.add_argument("--worklist", type=Path, help="override the frozen worklist path")
    parser.add_argument("--decisions", type=Path, help="override the authored decision file/directory")
    parser.add_argument(
        "--full-report",
        action="store_true",
        help="print the full report to stdout (default: bounded summary)",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        help="retain the full report as new UTF-8 JSON; stdout stays bounded unless --full-report",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--write", action="store_true", help="write generated sidecars and index")
    modes.add_argument("--write-subject", action="store_true", help="replace one existing subject, preserving unrelated index entries")
    modes.add_argument("--check-subject", action="store_true", help="verify one subject and compare its persisted output")
    modes.add_argument("--check", action="store_true", help="compare generated outputs without writing")
    modes.add_argument("--verify-evidence", action="store_true", help="verify exact source and adoption bindings")
    parser.add_argument("--subject-kind", choices=schema_enum("subject_kind"), help="subject namespace for lookup")
    parser.add_argument("--subject", help="exact catalog id or acquisition lane for lookup")
    return parser


def _print(value: object) -> None:
    # JSON escapes preserve Unicode values while keeping Windows console output
    # representable even when stdout uses CP1252 or another legacy encoding.
    print(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2))


_SUMMARY_ISSUE_LIMIT = 20
_SUMMARY_TEXT_LIMIT = 800
_REPORT_AXES = ("persistence", "inspection", "evidence", "required_repair", "optional_decision")


def _bounded_issue_rows(issues: list[dict], keys: tuple[str, ...]) -> tuple[list[dict], int, bool]:
    """Return bounded, console-safe issue details plus omission indicators."""

    details = []
    for issue in issues[:_SUMMARY_ISSUE_LIMIT]:
        row = {}
        truncated = False
        for key in keys:
            if key not in issue:
                continue
            value = str(issue[key])
            if len(value) > _SUMMARY_TEXT_LIMIT:
                truncated = True
            row[key] = value[:_SUMMARY_TEXT_LIMIT]
        row["truncated"] = truncated
        details.append(row)
    omitted = max(0, len(issues) - len(details))
    return details, omitted, any(row["truncated"] for row in details)


def _verification_summary(report: dict, mode: str = "verify") -> dict:
    """Project a report to bounded scalar axes and bounded error details."""

    issues = report.get("unverified_edges", [])
    evidence_details, issues_omitted, issues_truncated = _bounded_issue_rows(
        issues, ("kind", "subject", "claim_id", "message")
    )
    persistence = report.get("persistence", {})
    summary = {
        "mode": mode,
        # Keep the original verification-summary scope key for consumers that
        # already read it, while the axes below expose the other scalar counts.
        "scope": {"decision_subjects": persistence.get("decided_subjects", 0)},
        "unverified_edges": evidence_details,
        "issues_omitted": issues_omitted,
        "issues_truncated": issues_truncated,
        "report_scope": "Bounded report summary; full report remains available with --full-report or --report-file.",
    }
    for axis in _REPORT_AXES:
        values = report.get(axis)
        if not isinstance(values, dict):
            continue
        summary[axis] = {
            key: value
            for key, value in values.items()
            if value is None or isinstance(value, (bool, int, float, str))
        }

    output_issues = report.get("output_check")
    if isinstance(output_issues, list):
        output_details, output_issues_omitted, output_issues_truncated = _bounded_issue_rows(
            output_issues, ("path", "message")
        )
        summary["output_check"] = output_details
        summary["output_check_issues_omitted"] = output_issues_omitted
        summary["output_check_issues_truncated"] = output_issues_truncated

    written = report.get("written")
    if isinstance(written, list):
        # The full report retains paths for an explicitly requested artifact;
        # console summaries expose only the bounded count.
        summary["written"] = {"count": len(written)}
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if (args.subject_kind is None) != (args.subject is None):
        parser.error("--subject-kind and --subject must be supplied together")
    if (args.write_subject or args.check_subject) and args.subject is None:
        parser.error("subject operations require --subject-kind and --subject")
    try:
        if args.write_subject or args.check_subject:
            if args.report_file or args.full_report:
                parser.error("subject operations emit their complete scoped manifest on stdout")
            result = persist_subject(
                root, args.subject_kind, args.subject,
                worklist_path=args.worklist, decisions_path=args.decisions,
                write=args.write_subject,
            )
            _print(result)
            return 0 if result["current"] else 2
        if args.subject_kind is not None:
            if args.write or args.check or args.verify_evidence or args.full_report or args.report_file:
                parser.error("subject lookup cannot be combined with report options or a write/check/verification mode")
            _print(lookup_sidecar(root, args.subject_kind, args.subject))
            return 0

        exit_code = 0
        mode = "report"
        if args.write:
            mode = "write"
            result = write_outputs(
                root,
                worklist_path=args.worklist,
                decisions_path=args.decisions,
            )
            report = dict(result["report"])
            report["written"] = result["written"]
        elif args.check:
            mode = "check"
            issues, report = check_outputs_detailed(
                root,
                worklist_path=args.worklist,
                decisions_path=args.decisions,
            )
            report = dict(report)
            report["output_check"] = issues
            exit_code = 2 if issues or report["evidence"]["unverified_edges"] else 0
        else:
            mode = "verify" if args.verify_evidence else "report"
            report = build_report(root, worklist_path=args.worklist, decisions_path=args.decisions)
            if args.verify_evidence:
                exit_code = 2 if report["evidence"]["unverified_edges"] else 0
        if args.report_file is not None:
            report_file = review._safe_output_path(args.report_file, root, field="report file")
            with report_file.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        _print(report if args.full_report else _verification_summary(report, mode))
        return exit_code
    except (MetadataError, OSError) as exc:
        diagnostic = f"source metadata error: {exc}".encode("ascii", errors="backslashreplace").decode("ascii")
        print(diagnostic, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
