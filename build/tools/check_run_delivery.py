"""Check one explicitly declared reconstruction run delivery without writing."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any

from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path


CONTRACT = "ocd-run-delivery-check-v1"
_EXPECTED_CANDIDATE_ENTRIES = frozenset({"package", "validation.json"})
_EXPECTED_PACKAGE_ENTRIES = frozenset(
    {
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }
)
_LIMITATIONS = (
    "This check establishes delivery presence and path containment only.",
    "It does not validate candidate bytes, source fidelity, or human acceptance.",
    "It does not infer run status from directory names or maintain a run registry.",
)


class DeliveryInputError(ValueError):
    """Raised when a declared delivery path cannot be checked safely."""


def _json_line(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"


def _entry_exists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _is_reparse_point(path: Path) -> bool:
    if not _entry_exists(path):
        return False
    try:
        information = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise DeliveryInputError(f"cannot inspect reparse state: {path}: {exc}") from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(
        reparse_flag
        and getattr(information, "st_file_attributes", 0) & reparse_flag
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _normalized_logical_path(value: str, *, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise DeliveryInputError(
            f"{label} must be normalized repository-relative POSIX text"
        )
    relative = PurePosixPath(value)
    parts = relative.parts
    if (
        relative.is_absolute()
        or relative.as_posix() != value
        or not parts
        or any(part in {".", ".."} for part in parts)
        or ":" in parts[0]
    ):
        raise DeliveryInputError(
            f"{label} must be normalized repository-relative POSIX text"
        )
    return relative


def _repository_root(value: str | Path) -> Path:
    requested = Path(value)
    if not requested.is_absolute():
        raise DeliveryInputError("repository root must be an absolute path")
    try:
        root = requested.resolve(strict=True)
    except OSError as exc:
        raise DeliveryInputError(f"repository root is not readable: {requested}") from exc
    if not root.is_dir():
        raise DeliveryInputError(f"repository root is not a directory: {requested}")
    return root


def _configured_library_root(repository_root: Path) -> tuple[Path, Path]:
    """Derive the configured library root using only public resolver behavior."""

    config = repository_root / ".ocd-storage.json"
    if not config.is_file():
        raise DeliveryInputError(
            "configured .ocd-storage.json is required for durable delivery checks"
        )
    try:
        raw_root = resolve_repo_path(repository_root, "raw")
        reports_root = resolve_repo_path(repository_root, "reports")
        exports_root = resolve_repo_path(repository_root, "exports")
    except StorageTopologyError as exc:
        raise DeliveryInputError(f"configured storage topology is invalid: {exc}") from exc
    library_root = reports_root.parent
    if (
        _is_relative_to(library_root, repository_root)
        or raw_root.parent != library_root
        or exports_root.parent != library_root
        or reports_root != library_root / "reports"
    ):
        raise DeliveryInputError(
            "configured library routes do not resolve to one external library root"
        )
    return library_root, reports_root


def _ticket_info(repository_root: Path, value: str) -> tuple[dict[str, Any], bool]:
    relative = _normalized_logical_path(value, label="ticket")
    if relative.parts[0] != "plans":
        raise DeliveryInputError("ticket must be an existing repository plans file")
    try:
        path = resolve_repo_path(repository_root, value)
    except StorageTopologyError as exc:
        raise DeliveryInputError(f"ticket path is invalid: {exc}") from exc
    if not _is_relative_to(path, repository_root):
        raise DeliveryInputError("ticket path resolves outside the repository")
    if _is_reparse_point(repository_root / Path(*relative.parts)):
        raise DeliveryInputError("ticket path must not be a reparse alias")
    exists = _entry_exists(path)
    if exists and not path.is_file():
        raise DeliveryInputError("ticket path is not a file")
    return {
        "path": value,
        "resolved_path": str(path),
        "exists": exists,
    }, exists


def _candidate_info(
    library_root: Path,
    value: str,
) -> tuple[dict[str, Any], bool, bool]:
    requested = Path(value)
    if not requested.is_absolute():
        raise DeliveryInputError("candidate directory must be an absolute physical path")
    requested = Path(os.path.abspath(os.fspath(requested)))
    approved_lexical_root = library_root / "candidate-reviews"
    if _is_reparse_point(approved_lexical_root):
        raise DeliveryInputError("candidate-reviews root must not be a reparse alias")
    try:
        approved_root = approved_lexical_root.resolve(strict=False)
        resolved = requested.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise DeliveryInputError(f"candidate directory cannot be resolved safely: {requested}") from exc
    if not _is_relative_to(resolved, approved_root):
        raise DeliveryInputError(
            "candidate directory must resolve under the configured library candidate-reviews root"
        )
    if _is_reparse_point(requested):
        raise DeliveryInputError("candidate directory must not be a reparse alias")

    result: dict[str, Any] = {
        "requested_path": str(requested),
        "resolved_path": str(resolved),
        "approved_root": str(approved_root),
        "exists": _entry_exists(requested),
    }
    if not result["exists"]:
        result["shape"] = {"exact_outer_entries": False}
        result["package"] = {"exists": False}
        result["validation"] = {"exists": False}
        return result, False, False
    if not requested.is_dir():
        raise DeliveryInputError("candidate directory path is not a directory")

    try:
        entries = list(requested.iterdir())
    except OSError as exc:
        raise DeliveryInputError(f"candidate directory is unreadable: {requested}") from exc
    observed = {entry.name for entry in entries}
    exact = observed == _EXPECTED_CANDIDATE_ENTRIES
    result["shape"] = {
        "exact_outer_entries": exact,
        "observed_entries": sorted(observed),
    }
    if not exact:
        return result, True, True

    package = requested / "package"
    validation = requested / "validation.json"
    if _is_reparse_point(package) or _is_reparse_point(validation):
        raise DeliveryInputError("candidate package and validation sidecar must not be reparse aliases")
    package_exists = _entry_exists(package)
    validation_exists = _entry_exists(validation)
    package_is_directory = package_exists and package.is_dir()
    validation_is_file = validation_exists and validation.is_file()
    result["package"] = {
        "exists": package_exists,
        "directory": package_is_directory,
    }
    result["validation"] = {
        "exists": validation_exists,
        "file": validation_is_file,
    }
    structural_complete = package_is_directory and validation_is_file
    if package_is_directory:
        try:
            package_entries = list(package.iterdir())
        except OSError as exc:
            raise DeliveryInputError(f"candidate package is unreadable: {package}") from exc
        package_files = []
        package_indirections = []
        for entry in package_entries:
            if _is_reparse_point(entry):
                package_indirections.append(entry.name)
                continue
            if entry.is_file():
                package_files.append(entry.name)
            else:
                package_indirections.append(entry.name)
        observed_package = {entry.name for entry in package_entries}
        exact_package = observed_package == _EXPECTED_PACKAGE_ENTRIES
        result["package"]["file_count"] = len(package_files)
        result["package"]["flat"] = not package_indirections
        result["package"]["exact_entries"] = exact_package
        result["package"]["observed_entries"] = sorted(observed_package)
        if package_indirections:
            result["package"]["invalid_entries"] = sorted(package_indirections)
        if package_indirections or not exact_package:
            structural_complete = False
    if not structural_complete:
        return result, True, True
    return result, True, False


def _evidence_info(
    repository_root: Path,
    reports_root: Path,
    value: str,
) -> tuple[dict[str, Any], bool, bool]:
    relative = _normalized_logical_path(value, label="evidence directory")
    if len(relative.parts) < 3 or relative.parts[:2] != ("reports", "runs"):
        raise DeliveryInputError(
            "evidence directory must be under normalized reports/runs/<run-id>"
        )
    try:
        path = resolve_repo_path(repository_root, value)
    except StorageTopologyError as exc:
        raise DeliveryInputError(f"evidence directory path is invalid: {exc}") from exc
    approved_lexical_root = reports_root / "runs"
    if _is_reparse_point(approved_lexical_root):
        raise DeliveryInputError("reports/runs root must not be a reparse alias")
    try:
        approved_root = approved_lexical_root.resolve(strict=False)
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise DeliveryInputError(f"evidence directory cannot be resolved safely: {path}") from exc
    if not _is_relative_to(resolved, approved_root):
        raise DeliveryInputError(
            "evidence directory must resolve under the configured reports/runs root"
        )
    lexical_path = repository_root.joinpath(*relative.parts)
    if _is_reparse_point(lexical_path):
        raise DeliveryInputError("evidence directory must not be a reparse alias")

    result: dict[str, Any] = {
        "logical_path": value,
        "resolved_path": str(resolved),
        "approved_root": str(approved_root),
        "exists": _entry_exists(path),
    }
    if not result["exists"]:
        result["files"] = {"count": 0, "present": False}
        return result, False, False
    if not path.is_dir():
        raise DeliveryInputError("evidence directory path is not a directory")

    file_count = 0
    invalid_entries: list[str] = []
    try:
        pending = [path]
        while pending:
            for entry in pending.pop().iterdir():
                # Check before descending: Windows junctions are not always
                # classified as symbolic links by recursive globbing.
                if _is_reparse_point(entry):
                    invalid_entries.append(entry.relative_to(path).as_posix())
                elif entry.is_dir():
                    pending.append(entry)
                elif entry.is_file():
                    file_count += 1
    except OSError as exc:
        raise DeliveryInputError(f"evidence directory is unreadable: {path}") from exc
    result["files"] = {
        "count": file_count,
        "present": file_count > 0,
    }
    if invalid_entries:
        result["invalid_entries"] = sorted(invalid_entries)
        return result, True, True
    return result, True, file_count == 0


def check_run_delivery(
    *,
    repository_root: str | Path,
    ticket: str,
    candidate_dir: str,
    evidence_dir: str,
) -> dict[str, Any]:
    """Check declared run inputs without creating, deleting, or rewriting files."""

    root = _repository_root(repository_root)
    ticket_result, ticket_exists = _ticket_info(root, ticket)
    library_root, reports_root = _configured_library_root(root)
    candidate_result, candidate_exists, candidate_malformed = _candidate_info(
        library_root, candidate_dir
    )
    evidence_result, evidence_exists, evidence_incomplete = _evidence_info(
        root, reports_root, evidence_dir
    )

    if candidate_malformed or evidence_result.get("invalid_entries"):
        status = "invalid"
    elif not ticket_exists or not candidate_exists or not evidence_exists or evidence_incomplete:
        status = "incomplete"
    else:
        status = "complete"
    return {
        "contract": CONTRACT,
        "status": status,
        "ticket": ticket_result,
        "candidate": candidate_result,
        "evidence": evidence_result,
        "limitations": list(_LIMITATIONS),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--evidence-dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = check_run_delivery(
            repository_root=args.repository_root,
            ticket=args.ticket,
            candidate_dir=args.candidate_dir,
            evidence_dir=args.evidence_dir,
        )
    except DeliveryInputError as exc:
        result = {
            "contract": CONTRACT,
            "status": "invalid",
            "errors": [str(exc)],
            "limitations": list(_LIMITATIONS),
        }
        print(_json_line(result), end="")
        return 2
    print(_json_line(result), end="")
    if result["status"] == "complete":
        return 0
    return 2 if result["status"] == "invalid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
