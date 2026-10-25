"""Measure one read-only source-metadata verification run.

The benchmark deliberately starts after Python has imported this module and the
source-metadata engine.  It measures the explicit input load/validation phase
and one evidence-verification phase, and records the exact bytes used by both
the candidate inputs and their referenced source files.  It does not measure
Python startup/import time, output serialization, or token use.

Example::

    py -3 -m build.tools.benchmark_source_metadata \
        --root . \
        --worklist plans/2026-08-31-library-pipeline-redesign/artifacts/META-002/worklist.json \
        --decisions plans/2026-08-31-library-pipeline-redesign/artifacts/META-002/reviews/npnf105-third/29-npnf105-decisions.proposed.json \
        --output benchmark.json

The only optional output is the explicitly named JSON file.  No metadata
sidecars, source files, parent directories, or other repository state are
created or changed.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import time
from typing import Any, Iterator, Mapping

from build.lib import source_metadata as sm
from build.lib import source_metadata_contract, source_metadata_evidence


REPORT_FORMAT = "source-metadata-benchmark-v1"
MEASUREMENT_SCOPE = (
    "One in-process metadata load/validation and one evidence-verification "
    "pass; timing starts after Python/module imports and excludes startup, "
    "import, output serialization, output writing, and token usage. Total "
    "time includes the pre-verification input identity guard reads."
)
AUTHORITY_DIRECTORY_NAMES = (
    ".git",
    "raw",
    "sources",
    "metadata",
    "data",
    "ir",
    "library",
    "schemas",
    "reports",
    "exports",
)


def _file_identity(path: Path) -> dict[str, Any]:
    """Return a byte identity for one existing file."""

    resolved = Path(path).resolve()
    try:
        data = resolved.read_bytes()
    except (OSError, UnicodeError) as exc:
        raise sm.MetadataError(f"cannot read benchmark input {resolved}: {exc}") from exc
    return {
        "path": str(resolved),
        "bytes": len(data),
        "sha256": sm.sha256_bytes(data),
    }


def _require_file(path: Path, label: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise sm.MetadataError(f"{label} must be an existing file: {resolved}")
    return resolved


def _resolve_explicit_path(root: Path, path: Path, label: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    return _require_file(candidate, label)


def _subject_key(subject: Mapping[str, Any]) -> tuple[str, str]:
    return str(subject["kind"]), str(subject["id"])


def _referenced_paths(
    root: Path,
    worklist: Mapping[str, Any],
    decisions: list[Mapping[str, Any]],
) -> list[Path]:
    """Resolve source files touched by this bounded verification run.

    Worklist packets are limited to decided subjects because the engine's
    ``verify_evidence`` input check has the same bounded behavior.  Evidence
    bindings and adoption targets come from the validated candidate and are
    all included, including files whose later verification may report an
    issue.  Archive members are represented by their immutable container file;
    the candidate retains the member byte hash separately.
    """

    selected_subjects = {_subject_key(decision["subject"]) for decision in decisions}
    relative_paths: set[str] = set()
    for entry in worklist.get("subjects", []):
        if _subject_key(entry["subject"]) not in selected_subjects:
            continue
        for dimension in sm.dimension_names():
            for item in entry["dimensions"][dimension].get("items", []):
                relative_paths.add(str(item["source_packet"]))

    for decision in decisions:
        for payload in decision.get("dimensions", {}).values():
            for claim in payload.get("fields", []):
                evidence = claim.get("evidence", {})
                if isinstance(evidence, Mapping):
                    for binding in evidence.get("bindings", []):
                        if isinstance(binding, Mapping) and isinstance(binding.get("path"), str):
                            relative_paths.add(binding["path"])
                adoption = claim.get("adoption", {})
                target = adoption.get("target") if isinstance(adoption, Mapping) else None
                if isinstance(target, Mapping) and isinstance(target.get("path"), str):
                    relative_paths.add(target["path"])

    paths = []
    for relative in sorted(relative_paths):
        paths.append(sm._resolve(root, relative, field="benchmark input"))
    return paths


def _snapshot_paths(paths: Iterator[Path]) -> dict[str, dict[str, Any]]:
    identities: dict[str, dict[str, Any]] = {}
    for path in paths:
        identity = _file_identity(path)
        identities[identity["path"]] = identity
    return dict(sorted(identities.items()))


def _input_snapshot(
    worklist_path: Path,
    decisions_path: Path,
    referenced: list[Path],
) -> dict[str, Any]:
    worklist = _file_identity(worklist_path)
    decisions = _file_identity(decisions_path)
    all_identities = {worklist["path"]: worklist, decisions["path"]: decisions}
    all_identities.update(_snapshot_paths(iter(referenced)))
    ordered = [all_identities[key] for key in sorted(all_identities)]
    return {
        "worklist": worklist,
        "decisions": decisions,
        "referenced": [
            identity
            for identity in ordered
            if identity["path"] not in {worklist["path"], decisions["path"]}
        ],
        "all": ordered,
    }


def _snapshot_map(snapshot: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {identity["path"]: identity for identity in snapshot["all"]}


def _explicit_snapshot_map(snapshot: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        snapshot["worklist"]["path"]: snapshot["worklist"],
        snapshot["decisions"]["path"]: snapshot["decisions"],
    }


def _identity_drift_issue(
    before: Mapping[str, dict[str, Any]],
    after: Mapping[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if before == after:
        return None
    paths = sorted(set(before) | set(after))
    changed = []
    for path in paths:
        if before.get(path) != after.get(path):
            changed.append({"path": path, "before": before.get(path), "after": after.get(path)})
    return {
        "kind": "input_identity",
        "message": "benchmark input bytes changed during verification",
        "changed": changed,
    }


class _ParseCounter:
    def __init__(self) -> None:
        self.count = 0


@contextmanager
def _count_xml_parses(counter: _ParseCounter) -> Iterator[None]:
    """Temporarily count XML parses and always restore the engine hook."""

    original = source_metadata_evidence.ET.fromstring

    def counted(*args: Any, **kwargs: Any) -> Any:
        counter.count += 1
        return original(*args, **kwargs)

    source_metadata_evidence.ET.fromstring = counted
    try:
        yield
    finally:
        source_metadata_evidence.ET.fromstring = original


def benchmark(root: Path, *, worklist_path: Path, decisions_path: Path) -> dict[str, Any]:
    """Run one bounded, read-only source-metadata benchmark."""

    root = Path(root).resolve()
    if not root.is_dir():
        raise sm.MetadataError(f"benchmark root must be an existing directory: {root}")
    worklist_path = _resolve_explicit_path(root, worklist_path, "worklist")
    decisions_path = _resolve_explicit_path(root, decisions_path, "decisions")

    engine_identity = _file_identity(Path(sm.__file__))
    implementation_modules = {"source_metadata_contract": source_metadata_contract, "source_metadata_evidence": source_metadata_evidence}
    implementation_identities = {name: _file_identity(Path(module.__file__)) for name, module in implementation_modules.items()}
    schema_identity = _file_identity(sm.SCHEMA_PATH)
    seed_snapshot = _input_snapshot(worklist_path, decisions_path, [])
    seed_map = _snapshot_map(seed_snapshot)

    measured_start = time.perf_counter()
    load_start = measured_start
    sm.load_schema()
    worklist = sm.load_worklist(root, worklist_path)
    documents = sm.load_decision_documents(root, decisions_path)
    if len(documents) != 1:
        raise sm.MetadataError("decisions input must contain exactly one JSON document")
    decisions = sm.validate_decision_documents(documents, worklist=worklist)
    load_validate_seconds = time.perf_counter() - load_start

    # The explicit candidate files are read before the measured run and again
    # before verification.  A replacement during loading must stop the run.
    loaded_seed = _snapshot_map(_input_snapshot(worklist_path, decisions_path, []))
    seed_issue = _identity_drift_issue(seed_map, loaded_seed)
    if seed_issue is not None:
        raise sm.MetadataError(seed_issue["message"] + ": " + json.dumps(seed_issue["changed"], sort_keys=True))

    referenced = _referenced_paths(root, worklist, decisions)
    input_before = _input_snapshot(worklist_path, decisions_path, referenced)
    full_seed_issue = _identity_drift_issue(
        loaded_seed,
        _explicit_snapshot_map(input_before),
    )
    if full_seed_issue is not None:
        raise sm.MetadataError(
            "benchmark input identities changed before verification: "
            + json.dumps(full_seed_issue["changed"], ensure_ascii=True, sort_keys=True)
        )
    input_before_map = _snapshot_map(input_before)
    counter = _ParseCounter()
    verify_start = time.perf_counter()
    with _count_xml_parses(counter):
        evidence_issues = sm.verify_evidence(root, worklist, decisions)
    verify_seconds = time.perf_counter() - verify_start
    total_measured_seconds = time.perf_counter() - measured_start

    input_after = _input_snapshot(worklist_path, decisions_path, referenced)
    input_issue = _identity_drift_issue(input_before_map, _snapshot_map(input_after))
    issues = list(evidence_issues)
    engine_after = _file_identity(Path(sm.__file__))
    schema_after = _file_identity(sm.SCHEMA_PATH)
    for name, module in implementation_modules.items():
        if _file_identity(Path(module.__file__)) != implementation_identities[name]:
            issues.append({"kind": "engine_identity", "artifact": name, "message": "loaded implementation bytes changed during benchmark"})
    if engine_after != engine_identity:
        issues = [
            *issues,
            {"kind": "engine_identity", "message": "loaded engine bytes changed during benchmark"},
        ]
    if schema_after != schema_identity:
        issues = [
            *issues,
            {"kind": "schema_identity", "message": "loaded schema bytes changed during benchmark"},
        ]
    if input_issue is not None:
        issues = [*issues, input_issue]

    input_hashes = {
        identity["path"]: identity["sha256"]
        for identity in input_before["all"]
    }
    report = {
        "format": REPORT_FORMAT,
        "measurement_scope": MEASUREMENT_SCOPE,
        "status": "invalid_input_identity" if input_issue else ("failed" if issues else "complete"),
        "runtime": {
            "executable": sys.executable,
            "python_executable": sys.executable,
            "python": sys.version,
            "python_version": sys.version,
            "data_root": str(root),
            "loaded_code_root": str(Path(sm.__file__).resolve().parents[2]),
        },
        "loaded_engine": engine_identity,
        "loaded_implementations": implementation_identities,
        "loaded_schema": schema_identity,
        "inputs": input_before,
        "input_byte_hashes": input_hashes,
        "candidate": input_before["decisions"],
        "candidate_bytes": input_before["decisions"]["bytes"],
        "candidate_sha256": input_before["decisions"]["sha256"],
        "timing": {
            "load_validation_seconds": load_validate_seconds,
            "evidence_verification_seconds": verify_seconds,
            "total_measured_seconds": total_measured_seconds,
        },
        # Keep the names used by the existing one-off runtime receipts easy to
        # compare while the nested timing object carries the explicit labels.
        "load_validate_seconds": load_validate_seconds,
        "verify_seconds": verify_seconds,
        "total_measured_seconds": total_measured_seconds,
        "xml_parse_calls": counter.count,
        "issues": issues,
        "evidence": {
            "status": "unverified" if evidence_issues else "verified",
            "unverified_edges": len(evidence_issues),
        },
    }
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="data/evidence root")
    parser.add_argument("--worklist", type=Path, required=True, help="one explicit worklist JSON file")
    parser.add_argument("--decisions", type=Path, required=True, help="one explicit decisions JSON file")
    parser.add_argument("--output", type=Path, help="optional new JSON report file; existing files are refused")
    return parser


def _prepare_output(root: Path, output: Path | None, inputs: tuple[Path, Path]) -> Path | None:
    if output is None:
        return None
    resolved = Path(output).resolve()
    if resolved.exists():
        raise sm.MetadataError(f"refusing to overwrite benchmark output: {resolved}")
    if not resolved.parent.is_dir():
        raise sm.MetadataError(f"benchmark output parent does not exist: {resolved.parent}")
    for name in AUTHORITY_DIRECTORY_NAMES:
        authority = (root / name).resolve()
        try:
            resolved.relative_to(authority)
        except ValueError:
            continue
        raise sm.MetadataError(f"benchmark output cannot be inside authority directory: {name}")
    if resolved in {path.resolve() for path in inputs}:
        raise sm.MetadataError(f"benchmark output cannot replace an input: {resolved}")
    return resolved


def _write_output(path: Path, report: Mapping[str, Any]) -> None:
    data = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    try:
        with path.open("xb") as stream:
            stream.write(data)
    except FileExistsError as exc:
        raise sm.MetadataError(f"refusing to overwrite benchmark output: {path}") from exc
    except OSError as exc:
        raise sm.MetadataError(f"cannot write benchmark output {path}: {exc}") from exc


def _print_report(report: Mapping[str, Any]) -> None:
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))


def _print_error(exc: BaseException) -> None:
    # JSON's ASCII escaping keeps diagnostics safe when the host console is
    # configured for strict CP1252.  The optional report file remains UTF-8.
    sys.stderr.write(
        "source metadata benchmark error: "
        + json.dumps(str(exc), ensure_ascii=True)
        + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).resolve()
        if not root.is_dir():
            raise sm.MetadataError(f"benchmark root must be an existing directory: {root}")
        worklist = _resolve_explicit_path(root, args.worklist, "worklist")
        decisions = _resolve_explicit_path(root, args.decisions, "decisions")
        output = _prepare_output(root, args.output, (worklist, decisions))
        report = benchmark(root, worklist_path=worklist, decisions_path=decisions)
        if output is not None:
            _write_output(output, report)
        _print_report(report)
        return 2 if report["issues"] else 0
    except (sm.MetadataError, OSError, UnicodeError) as exc:
        _print_error(exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
