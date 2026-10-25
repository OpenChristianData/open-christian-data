"""Strict assessment/review records and deterministic internal reports.

Agent assessments and human reviews are deliberately separate record types.
This module validates their narrow contracts, optionally verifies the exact
artifact bytes they cite, and renders a report that preserves partial coverage
and uncertainty.  It does not create human reviews, update state, accept a
master, or make a publication decision.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from ._common import (
    PipelineError,
    ensure_relative_path,
    load_json,
    safe_identifier,
    sha256_file,
    write_json,
)
from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path


REPORT_VERSION = "ocd-library-assessment-review-v1"
_SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "v2"
_SCHEMA_NAMES = {
    "agent-assessment": "agent-assessment.schema.json",
    "human-review": "human-review.schema.json",
}


def _schema(kind: str) -> dict[str, Any]:
    filename = _SCHEMA_NAMES.get(kind)
    if filename is None:
        raise PipelineError(f"unsupported assessment record: {kind}")
    path = _SCHEMA_ROOT / filename
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"cannot load assessment schema {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"assessment schema must be an object: {path}")
    return value


def _validate_schema(kind: str, record: Mapping[str, Any], *, context: str) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise PipelineError(f"{context} must be a JSON object")
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - dependency is required by the package
        raise PipelineError("jsonschema is required for assessment validation") from exc

    validator = jsonschema.Draft202012Validator(
        _schema(kind), format_checker=jsonschema.FormatChecker()
    )
    errors = sorted(validator.iter_errors(dict(record)), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(
            f"{context}{error.json_path}: {error.message}" for error in errors[:8]
        )
        if len(errors) > 8:
            details += f"; {len(errors) - 8} more schema errors"
        raise PipelineError(details)
    return dict(record)


def _require_id(record: Mapping[str, Any], key: str, *, context: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PipelineError(f"{context} requires non-empty string {key}")
    return safe_identifier(value.strip(), field=key)


def _validate_reference(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PipelineError(f"{field} must be a non-empty relative path")
    reference = value.strip()
    # ``Path.is_absolute`` alone permits Windows drive-relative values such as
    # ``C:foo``.  The schema rejects them too; retain the semantic check here
    # for callers using this module without re-reading the schema.
    if Path(reference).drive or ":" in reference or "\\" in reference:
        raise PipelineError(f"{field} must use a repository-relative POSIX path: {reference}")
    return str(ensure_relative_path(reference, field=field)).replace("\\", "/")


def _validate_evidence_lists(record: Mapping[str, Any], *, context: str) -> None:
    artifacts = record.get("artifacts")
    citations = record.get("citations")
    if not isinstance(artifacts, list) or not isinstance(citations, list):
        raise PipelineError(f"{context} artifacts and citations must be lists")
    if not artifacts and not citations:
        raise PipelineError(f"{context} requires at least one artifact binding or citation")

    artifact_ids: set[str] = set()
    evidence_ids: set[str] = set()
    paths: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict):
            raise PipelineError(f"{context} artifact bindings must be objects")
        artifact_id = _require_id(item, "artifact_id", context=context)
        if artifact_id in artifact_ids:
            raise PipelineError(f"duplicate artifact_id in {context}: {artifact_id}")
        artifact_ids.add(artifact_id)
        evidence_ids.add(artifact_id)
        path = _validate_reference(item.get("path"), field=f"artifact path in {context}")
        if path in paths:
            raise PipelineError(f"duplicate artifact path in {context}: {path}")
        paths.add(path)
        digest = item.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or digest != digest.lower():
            raise PipelineError(f"artifact {artifact_id} in {context} requires lowercase SHA-256")
        if any(character not in "0123456789abcdef" for character in digest):
            raise PipelineError(f"artifact {artifact_id} in {context} has invalid SHA-256")

    citation_ids: set[str] = set()
    for item in citations:
        if not isinstance(item, dict):
            raise PipelineError(f"{context} citations must be objects")
        citation_id = _require_id(item, "citation_id", context=context)
        if citation_id in citation_ids:
            raise PipelineError(f"duplicate citation_id in {context}: {citation_id}")
        citation_ids.add(citation_id)
        evidence_ids.add(citation_id)
    overlap_ids = artifact_ids.intersection(citation_ids)
    if overlap_ids:
        raise PipelineError(
            f"artifact_id and citation_id must be disjoint in {context}: "
            f"{sorted(overlap_ids)!r}"
        )

    issues = record.get("issues")
    if not isinstance(issues, list):
        raise PipelineError(f"{context} issues must be a list")
    issue_ids: set[str] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            raise PipelineError(f"{context} issues must be objects")
        issue_id = _require_id(issue, "issue_id", context=context)
        if issue_id in issue_ids:
            raise PipelineError(f"duplicate issue_id in {context}: {issue_id}")
        issue_ids.add(issue_id)
        refs = issue.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            raise PipelineError(f"issue {issue_id} in {context} requires evidence_refs")
        for reference in refs:
            if not isinstance(reference, str) or reference not in evidence_ids:
                raise PipelineError(
                    f"issue {issue_id} in {context} references unknown evidence: {reference!r}"
                )

    coverage = record.get("coverage")
    if not isinstance(coverage, dict):
        raise PipelineError(f"{context} coverage must be an object")
    inspected = coverage.get("inspected")
    omitted = coverage.get("omitted")
    if not isinstance(inspected, list) or not inspected:
        raise PipelineError(f"{context} coverage must list inspected locators")
    if not isinstance(omitted, list):
        raise PipelineError(f"{context} coverage must list omitted locators")
    overlap = set(inspected).intersection(omitted)
    if overlap:
        raise PipelineError(
            f"{context} coverage locator is both inspected and omitted: {sorted(overlap)!r}"
        )
    completeness = coverage.get("completeness")
    if completeness in {"partial", "unknown"} and not omitted:
        raise PipelineError(
            f"{context} {completeness} coverage must name omitted or unreached scope"
        )
    if completeness == "complete" and omitted:
        raise PipelineError(
            f"{context} complete coverage cannot list omitted or unreached scope"
        )


def _validate_common(kind: str, record: Mapping[str, Any], *, context: str) -> dict[str, Any]:
    value = _validate_schema(kind, record, context=context)
    _require_id(value, "work_id", context=context)
    _require_id(value, "edition_id", context=context)
    id_field = "assessment_id" if kind == "agent-assessment" else "review_id"
    _require_id(value, id_field, context=context)
    _validate_evidence_lists(value, context=context)

    scope = value.get("scope")
    if not isinstance(scope, dict) or not isinstance(scope.get("reference"), str):
        raise PipelineError(f"{context} requires a concrete scope reference")

    if kind == "human-review":
        origin = value.get("record_origin")
        synthetic = value.get("synthetic")
        if synthetic is True and origin != "synthetic-test":
            raise PipelineError(
                f"{context} synthetic records must declare record_origin='synthetic-test'"
            )
        if synthetic is False and origin != "human-asserted":
            raise PipelineError(
                f"{context} non-synthetic records must declare record_origin='human-asserted'"
            )
    return value


def validate_agent_assessment(
    record: Mapping[str, Any], *, context: str = "agent assessment"
) -> dict[str, Any]:
    """Validate one in-memory provisional agent assessment."""

    return _validate_common("agent-assessment", record, context=context)


def validate_human_review(
    record: Mapping[str, Any], *, context: str = "human review"
) -> dict[str, Any]:
    """Validate one in-memory scoped human-review assertion.

    Validation checks the declared shape only.  It cannot authenticate that a
    human performed the review; that limitation is retained in every report.
    """

    return _validate_common("human-review", record, context=context)


def _assert_within(path: Path, root: Path, *, field: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise PipelineError(f"{field} is outside the selected root: {path}") from exc


def _check_artifact_bytes(record: Mapping[str, Any], *, root: Path, context: str) -> None:
    root = Path(root)
    if not root.is_dir():
        raise PipelineError(f"selected assessment root is not a directory: {root}")
    for artifact in record["artifacts"]:
        relative = _validate_reference(artifact["path"], field=f"artifact in {context}")
        try:
            # Resolve through the repository's explicit storage topology so a
            # logical raw/reports/exports binding can point at its configured
            # durable library without weakening the path boundary.
            candidate = resolve_repo_path(root, relative)
        except (StorageTopologyError, TypeError) as exc:
            raise PipelineError(
                f"invalid artifact storage route for {context}: {relative}: {exc}"
            ) from exc
        if not candidate.is_file():
            raise PipelineError(f"artifact is missing for {context}: {relative}")
        actual = sha256_file(candidate)
        if actual != artifact["sha256"]:
            raise PipelineError(
                f"artifact SHA-256 mismatch for {context} {relative}: "
                f"declared {artifact['sha256']}, found {actual}"
            )


def _load_record(kind: str, path: Path, *, root: Path | None) -> dict[str, Any]:
    path = Path(path)
    record = _validate_common(kind, load_json(path), context=str(path))
    if root is not None:
        root = Path(root)
        _assert_within(path, root, field=f"{kind} record")
        _check_artifact_bytes(record, root=root, context=str(path))
    return record


def load_agent_assessment(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    """Load and validate one agent assessment, optionally checking artifact bytes."""

    return _load_record("agent-assessment", Path(path), root=root)


def load_human_review(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    """Load and validate one human-review assertion, optionally checking artifact bytes."""

    return _load_record("human-review", Path(path), root=root)


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, RuntimeError, ValueError) as exc:
        raise PipelineError(f"record is outside the selected root: {path}") from exc


def _record_summary(
    record: Mapping[str, Any], *, kind: str, path: Path, root: Path
) -> dict[str, Any]:
    identifier = record["assessment_id"] if kind == "agent-assessment" else record["review_id"]
    result_key = "outcome" if kind == "agent-assessment" else "result"
    summary = {
        "record_path": _relative(root, path),
        "record_sha256": sha256_file(path),
        "artifact_hashes_verified": bool(record["artifacts"]),
        "verified_artifact_count": len(record["artifacts"]),
        "citations_not_verified": len(record["citations"]),
        "record_id": identifier,
        "scope": copy.deepcopy(record["scope"]),
        "artifacts": sorted(
            (copy.deepcopy(item) for item in record["artifacts"]),
            key=lambda item: (item["kind"], item["path"], item["artifact_id"]),
        ),
        "citations": sorted(
            (copy.deepcopy(item) for item in record["citations"]),
            key=lambda item: item["citation_id"],
        ),
        "coverage": copy.deepcopy(record["coverage"]),
        "result": record[result_key],
        "summary": record["summary"],
        "uncertainties": sorted(record["uncertainties"]),
        "issues": sorted(
            (copy.deepcopy(item) for item in record["issues"]),
            key=lambda item: (item["severity"], item["issue_id"]),
        ),
    }
    if kind == "agent-assessment":
        summary["assessment_id"] = record["assessment_id"]
        summary["assessed_at"] = record["assessed_at"]
        summary["agent"] = copy.deepcopy(record["agent"])
    else:
        summary["review_id"] = record["review_id"]
        summary["reviewed_at"] = record["reviewed_at"]
        summary["reviewer"] = record["reviewer"]
        summary["decision_area"] = list(record["decision_area"])
        summary["synthetic"] = record["synthetic"]
        summary["record_origin"] = record["record_origin"]
        # This is a declared limitation, not a positive authentication result.
        summary["human_authorship"] = (
            "synthetic-test-record"
            if record["synthetic"]
            else "human-authorship-asserted; not-machine-authenticated"
        )
    return summary


def build_assessment_report(
    root: Path,
    *,
    assessment_paths: Iterable[Path] = (),
    review_paths: Iterable[Path] = (),
) -> dict[str, Any]:
    """Build a stable report from exact assessment/review records.

    ``root`` is mandatory so every source/TEI binding can be checked against
    current bytes before it appears in the report.  Inputs are grouped only by
    their declared work and edition IDs; agent and human records remain
    separate, so partial human coverage cannot erase or downgrade an agent
    assessment.
    """

    root = Path(root).resolve()
    if not root.is_dir():
        raise PipelineError(f"selected assessment root is not a directory: {root}")
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    seen: set[tuple[str, str]] = set()

    def add(kind: str, path: Path) -> None:
        path = Path(path)
        record = (
            load_agent_assessment(path, root=root)
            if kind == "agent-assessment"
            else load_human_review(path, root=root)
        )
        id_field = "assessment_id" if kind == "agent-assessment" else "review_id"
        identity = (kind, str(record[id_field]))
        if identity in seen:
            raise PipelineError(f"duplicate {kind} record: {record[id_field]}")
        seen.add(identity)
        key = (str(record["work_id"]), str(record["edition_id"]))
        group = groups.setdefault(
            key,
            {
                "work_id": key[0],
                "edition_id": key[1],
                "agent_assessments": [],
                "human_reviews": [],
            },
        )
        summary = _record_summary(record, kind=kind, path=path, root=root)
        group["agent_assessments" if kind == "agent-assessment" else "human_reviews"].append(
            summary
        )

    for path in sorted((Path(item) for item in assessment_paths), key=lambda item: item.as_posix()):
        add("agent-assessment", path)
    for path in sorted((Path(item) for item in review_paths), key=lambda item: item.as_posix()):
        add("human-review", path)

    entries: list[dict[str, Any]] = []
    total_uncertain = 0
    total_issues = 0
    partial_human = 0
    for key in sorted(groups):
        group = groups[key]
        group["agent_assessments"].sort(key=lambda item: item["assessment_id"])
        group["human_reviews"].sort(key=lambda item: item["review_id"])
        human_partial = sum(
            1
            for item in group["human_reviews"]
            if item["coverage"]["completeness"] in {"partial", "unknown"}
        )
        partial_human += human_partial
        uncertain = sum(
            1
            for item in [*group["agent_assessments"], *group["human_reviews"]]
            if item["uncertainties"]
        )
        issues = sum(
            1
            for item in [*group["agent_assessments"], *group["human_reviews"]]
            if item["issues"]
        )
        total_uncertain += uncertain
        total_issues += issues
        group["flags"] = {
            "partial_or_unknown_human_review": human_partial > 0,
            "records_with_uncertainty": uncertain,
            "records_with_issues": issues,
            "acceptance": "unchanged",
            "publication": "unchanged",
        }
        entries.append(group)

    return {
        "report_version": REPORT_VERSION,
        "root": ".",
        "artifact_hashes_verified": any(
            item["artifact_hashes_verified"]
            for group in entries
            for item in [*group["agent_assessments"], *group["human_reviews"]]
        ),
        "verified_artifact_count": sum(
            item["verified_artifact_count"]
            for group in entries
            for item in [*group["agent_assessments"], *group["human_reviews"]]
        ),
        "citations_not_verified": sum(
            item["citations_not_verified"]
            for group in entries
            for item in [*group["agent_assessments"], *group["human_reviews"]]
        ),
        "items": entries,
        "counts": {
            "work_editions": len(entries),
            "agent_assessments": sum(len(item["agent_assessments"]) for item in entries),
            "human_reviews": sum(len(item["human_reviews"]) for item in entries),
            "partial_or_unknown_human_reviews": partial_human,
            "records_with_uncertainty": total_uncertain,
            "records_with_issues": total_issues,
        },
        "authority": {
            "agent_assessments": "provisional-evidence",
            "human_reviews": "asserted-inspection-scope",
            "human_authorship": "not-machine-authenticated",
            "acceptance": "unchanged",
            "publication": "unchanged",
        },
    }


def _markdown_value(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def render_assessment_report(report: Mapping[str, Any]) -> str:
    """Render a deterministic, human-readable report from ``build_assessment_report``."""

    lines = [
        "# Assessment and human review report",
        "",
        f"Report version: `{report['report_version']}`.",
        "",
        f"Artifact hashes verified: {str(report['artifact_hashes_verified']).lower()} "
        f"({report['verified_artifact_count']} artifact(s)).",
        f"Citation URLs not verified: {report['citations_not_verified']}.",
        "Acceptance effect: unchanged.",
        "Publication effect: unchanged.",
        "Human authorship is asserted by a record's provenance field and is not machine-authenticated.",
        "",
        "## Counts",
        "",
        f"- Work/edition groups: {report['counts']['work_editions']}",
        f"- Agent assessments: {report['counts']['agent_assessments']}",
        f"- Human reviews: {report['counts']['human_reviews']}",
        f"- Partial or unknown human reviews: {report['counts']['partial_or_unknown_human_reviews']}",
        f"- Records with uncertainty: {report['counts']['records_with_uncertainty']}",
        f"- Records with issues: {report['counts']['records_with_issues']}",
        "",
    ]
    for item in report["items"]:
        lines.extend(
            [
                f"## {_markdown_value(item['work_id'])} / {_markdown_value(item['edition_id'])}",
                "",
                "### Agent assessments",
                "",
            ]
        )
        if not item["agent_assessments"]:
            lines.append("None recorded.")
            lines.append("")
        for assessment in item["agent_assessments"]:
            coverage = assessment["coverage"]
            lines.append(
                f"- `{assessment['assessment_id']}`: {assessment['result']} "
                f"({coverage['completeness']} coverage); {assessment['summary']}"
            )
            lines.append(
                f"  inspected: {', '.join(coverage['inspected'])}; "
                f"omitted: {', '.join(coverage['omitted']) or 'none'}"
            )
            if assessment["uncertainties"]:
                lines.append(
                    f"  uncertainties: {'; '.join(assessment['uncertainties'])}"
                )
            if assessment["issues"]:
                lines.append(
                    "  issues: "
                    + "; ".join(
                        f"{issue['severity']}: {issue['statement']}"
                        for issue in assessment["issues"]
                    )
                )
        lines.extend(["", "### Human reviews", ""])
        if not item["human_reviews"]:
            lines.append("None recorded.")
            lines.append("")
        for review in item["human_reviews"]:
            coverage = review["coverage"]
            lines.append(
                f"- `{review['review_id']}`: {review['result']} "
                f"({coverage['completeness']} coverage); {review['summary']}"
            )
            lines.append(
                f"  reviewer: {_markdown_value(review['reviewer'])}; "
                f"decision area: {', '.join(review['decision_area'])}; "
                f"provenance: {review['human_authorship']}"
            )
            lines.append(
                f"  inspected: {', '.join(coverage['inspected'])}; "
                f"omitted: {', '.join(coverage['omitted']) or 'none'}"
            )
            if review["uncertainties"]:
                lines.append(f"  uncertainties: {'; '.join(review['uncertainties'])}")
            if review["issues"]:
                lines.append(
                    "  issues: "
                    + "; ".join(
                        f"{issue['severity']}: {issue['statement']}"
                        for issue in review["issues"]
                    )
                )
        lines.append("")
    return "\n".join(lines)


def write_assessment_report(
    report: Mapping[str, Any], *, json_path: Path, markdown_path: Path
) -> None:
    """Write an already-built report in canonical JSON and deterministic Markdown."""

    write_json(Path(json_path), report)
    markdown_path = Path(markdown_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_assessment_report(report), encoding="utf-8", newline="\n")
