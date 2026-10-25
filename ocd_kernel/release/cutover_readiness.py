"""Fail-closed evaluation of explicit, scope-bound cutover prerequisite evidence.

Prerequisite receipts are coordinator-owned evidence, not publication authority.
Each names its verification result and all inputs on which that result depends.
The original scope digest excludes only the prerequisite receipts themselves.
"""

from __future__ import annotations

import hashlib
import json
import shlex
from pathlib import Path

from ocd_kernel.library._common import PipelineError, canonical_bytes, _reject_duplicate_keys
from ocd_kernel.lib.storage_topology import resolve_repo_path


REQUIRED_GATES = (
    "consumer_replacement", "legacy_field_replacement", "runtime_boundary",
    "category_mappings", "required_metadata", "view_freshness", "reader_fidelity", "full_suite",
)


def scope_digest(scope: dict) -> str:
    return hashlib.sha256(canonical_bytes({key: value for key, value in scope.items()
                                         if key != "prerequisites"})).hexdigest()


def bound_bytes(root: Path, binding: dict) -> bytes:
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
        raise PipelineError("cutover evidence requires exact path and SHA-256")
    content = resolve_repo_path(root, binding["path"]).read_bytes()
    if hashlib.sha256(content).hexdigest() != binding["sha256"]:
        raise PipelineError(f"cutover evidence changed: {binding['path']}")
    return content


def _prerequisite_input(root: Path, binding: dict, gate: str) -> tuple[str, str]:
    """Check local inputs or the explicitly supported sibling runtime."""
    if not isinstance(binding, dict):
        raise PipelineError("cutover input must be an object")
    if "repository" not in binding:
        bound_bytes(root, binding)
        return "OCD", binding["path"]
    if (gate != "runtime_boundary" or binding.get("repository") != "EzraOCR"
            or set(binding) != {"repository", "path", "sha256"}):
        raise PipelineError("external inputs are restricted to the EzraOCR runtime boundary")
    # No caller-supplied repository path or arbitrary parent traversal. A
    # redirected sibling must not silently substitute another runtime.
    sibling = root.resolve(strict=True).parent / "EzraOCR"
    if sibling.resolve(strict=True) != sibling or not (sibling / ".git").exists():
        raise PipelineError("EzraOCR sibling checkout is missing or redirected")
    path = resolve_repo_path(sibling, binding["path"])
    if not path.is_relative_to(sibling):
        raise PipelineError("EzraOCR runtime input escapes its sibling checkout")
    if hashlib.sha256(path.read_bytes()).hexdigest() != binding["sha256"]:
        raise PipelineError(f"cutover evidence changed: EzraOCR/{binding['path']}")
    return "EzraOCR", binding["path"]


def _object(content: bytes) -> dict:
    value = json.loads(content, object_pairs_hook=_reject_duplicate_keys)
    if not isinstance(value, dict):
        raise PipelineError("cutover evidence must be an object")
    return value


def _full_suite_result(result: dict) -> bool:
    """Require the entire suite, not a selected test disguised by exit zero."""
    if type(result.get("exit_code")) is not int or result["exit_code"] != 0:
        return False
    command = result.get("command")
    if not isinstance(command, str):
        return False
    args = shlex.split(command)
    if args[:6] != ["py", "-3", "-m", "pytest", "-p", "no:cacheprovider"]:
        return False
    rest = args[6:]
    index = 0
    while index < len(rest):
        arg = rest[index]
        if arg in ("-q", "-v", "-vv") or arg.startswith("--durations="):
            index += 1
        elif arg in ("--basetemp", "-n", "--dist", "--durations"):
            if index + 1 == len(rest):
                return False
            index += 2
        else:
            return False
    return True


def evaluate_prerequisites(root: Path, scope: dict, *, release_report_sha256: str | None = None) -> list[dict]:
    declared = scope.get("prerequisites", {})
    if not isinstance(declared, dict) or set(declared) - set(REQUIRED_GATES):
        raise PipelineError("unknown or malformed cutover prerequisites")
    expected_scope = scope_digest(scope)
    results = []
    for gate in REQUIRED_GATES:
        result = {"gate": gate, "status": "missing", "reason": "No prerequisite evidence supplied."}
        if gate in declared:
            result["evidence"] = declared[gate]
            try:
                receipt = _object(bound_bytes(root, declared[gate]))
                if set(receipt) != {"contract", "gate", "scope_sha256", "inputs", "verification"}:
                    raise PipelineError("invalid cutover prerequisite receipt fields")
                if (receipt["contract"] != "ocd-cutover-prerequisite-v1" or receipt["gate"] != gate
                        or receipt["scope_sha256"] != expected_scope):
                    raise PipelineError("prerequisite identity or corpus scope differs")
                inputs = receipt["inputs"]
                if not isinstance(inputs, list) or not inputs:
                    raise PipelineError("prerequisite has no freshness inputs")
                seen = set()
                for binding in inputs:
                    identity = _prerequisite_input(root, binding, gate)
                    if identity in seen:
                        raise PipelineError("duplicate prerequisite input")
                    seen.add(identity)
                if gate == "runtime_boundary" and not any(repo == "EzraOCR" for repo, _ in seen):
                    raise PipelineError("runtime boundary requires current EzraOCR inputs")
                verification = _object(bound_bytes(root, receipt["verification"]))
                success = (_full_suite_result(verification) if gate == "full_suite"
                           else verification.get("status") == "pass")
                if not success:
                    raise PipelineError("bound verification is not a successful required check")
                if gate == "reader_fidelity" and verification.get("release_report_sha256") != release_report_sha256:
                    raise PipelineError("reader verification belongs to a different release")
                result.update(status="pass", reason="Bound verification passes and declared inputs are current.")
            except (PipelineError, OSError, ValueError, TypeError, KeyError) as exc:
                result.update(status="failed", reason=str(exc))
        results.append(result)
    return results


def complete_readiness(root: Path, scope: dict, accounting: dict) -> dict:
    """Combine current accounting, independent verification, and all prerequisites."""
    checks = evaluate_prerequisites(root, scope, release_report_sha256=accounting.get("release_report_sha256"))
    blockers = [f"{row['gate']}: {row['reason']}" for row in checks if row["status"] != "pass"]
    release_verified = accounting.get("release_verification") == {"status": "pass", "errors": []}
    if not release_verified:
        blockers.append("Independent release verification did not pass.")
    targets = accounting["targets"]
    baseline = _object(bound_bytes(root, scope["baseline"]))
    expected_ids = [row["target_id"] for row in baseline["targets"]]
    if (not targets or len({row["target_id"] for row in targets}) != len(targets)
            or len(set(expected_ids)) != len(expected_ids)
            or {row["target_id"] for row in targets} != set(expected_ids)
            or any(row["status"] not in ("included", "excluded") for row in targets)):
        blockers.append("Some corpus targets are missing, unlinked, blocked, failed or duplicated.")
    included = [row for row in targets
                if release_verified and row.get("status") == "included"
                and isinstance(row.get("acceptance"), dict)
                and set(row["acceptance"]) == {"path", "sha256"}]
    included_targets = sorted({row["target_id"] for row in included})
    acceptance_paths = {row["acceptance"]["path"] for row in included}
    work_integration = {
        "status": ("ready-and-integrated" if included_targets else
                   "none-included" if release_verified else "unverified"),
        "included_target_count": len(included_targets),
        "distinct_acceptance_masters": len(acceptance_paths),
        "included_target_ids": included_targets,
        "interpretation": (
            "Included targets are ready and already present in the independently verified "
            "rehearsal release. This per-work result is separate from whole-corpus "
            "retirement_readiness."
        ),
    }
    return {**accounting, "phase": "retirement-readiness", "prerequisite_checks": checks,
            "scope_sha256": scope_digest(scope), "readiness_blockers": blockers,
            "work_integration_readiness": work_integration,
            "retirement_readiness": "not-ready" if blockers else "ready"}
