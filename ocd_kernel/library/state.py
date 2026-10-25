"""Mutable project-state sidecar loading and physical-evidence checks."""

from __future__ import annotations

from ocd_kernel.lib.path_io import io_path, resolve_path, io_glob

from pathlib import Path
from typing import Any
from datetime import datetime, timezone
import hashlib

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock, write_json_atomic

from ._common import PipelineError, ensure_relative_path, load_json, require_string, safe_identifier
from ocd_kernel.lib.storage_topology import (
    EXTERNAL_DATA_ROOTS,
    StorageTopologyError,
    resolve_repo_path,
)

from .identities import _schema, _validate_acquisition_layout, load_editions, load_work, schema_enum, validate_record


def load_state(path: Path) -> dict[str, Any]:
    """Load and schema-validate one v2 state sidecar."""

    record = load_json(path)
    validate_record("state", record, context=str(path))
    safe_identifier(require_string(record, "work_id", context=str(path)), field="work_id")
    targets = record["targets"]
    if not isinstance(targets, list):  # guarded by the schema; retain a useful API error
        raise PipelineError(f"{path} targets must be a list")
    seen: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise PipelineError(f"{path} targets must be objects")
        target_id = safe_identifier(
            require_string(target, "target_id", context=str(path)), field="target_id"
        )
        if target_id in seen:
            raise PipelineError(f"duplicate target_id in {path}: {target_id}")
        seen.add(target_id)
    return record


def _work_root_for_state(path: Path, root: Path, work_id: str) -> Path:
    work_root = Path(root) / "library" / "works" / work_id
    try:
        resolve_path(path).relative_to(resolve_path(work_root))
    except (OSError, RuntimeError, ValueError) as exc:
        raise PipelineError(
            f"state sidecar is not under its declared work directory: {path}"
        ) from exc
    return work_root


def _existing_evidence_paths(
    references: list[str], *, root: Path, work_root: Path, context: str
) -> None:
    """Resolve references in work, repo, or configured external storage roots."""

    missing: list[str] = []
    for reference in references:
        relative = ensure_relative_path(reference, field=f"state evidence in {context}")
        if relative.parts and relative.parts[0] in EXTERNAL_DATA_ROOTS:
            try:
                external_candidate = resolve_repo_path(root, relative.as_posix())
            except (OSError, RuntimeError, StorageTopologyError):
                external_candidate = None
            if external_candidate is not None and io_path(external_candidate).is_file():
                continue
            missing.append(reference)
            continue
        found = False
        for base in (work_root, Path(root)):
            try:
                repo_relative = (base / relative).relative_to(Path(root)).as_posix()
                candidate = resolve_repo_path(root, repo_relative)
            except (OSError, RuntimeError, ValueError, StorageTopologyError):
                continue
            if io_path(candidate).is_file():
                found = True
                break
        if not found:
            missing.append(reference)
    if missing:
        raise PipelineError(
            f"state evidence references missing files in {context}: {', '.join(missing)}"
        )


def _evidence_binds_path(
    references: list[str], *, target_path: Path, root: Path, work_root: Path
) -> bool:
    """Return whether evidence names a target using either supported base."""

    for reference in references:
        try:
            relative = ensure_relative_path(reference, field="state evidence")
        except PipelineError:
            continue
        for base in (work_root, root):
            try:
                candidate = resolve_path(base / relative)
            except (OSError, RuntimeError):
                continue
            if candidate == resolve_path(target_path):
                return True
    return False


def _edition_index(work: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    result: dict[str, tuple[str, dict[str, Any]]] = {}
    for form in work.get("textual_forms", []):
        if not isinstance(form, dict):
            continue
        form_id = str(form["textual_form_id"])
        for edition in form.get("editions", []):
            if isinstance(edition, dict):
                result[str(edition["edition_id"])] = (form_id, edition)
    return result


def _acquisition_index(work_root: Path, *, root: Path, context: str) -> dict[str, dict[str, Any]]:
    """Load acquisition records below one work and reject path/ID collisions."""

    from .acquisitions import validate_acquisition

    result: dict[str, dict[str, Any]] = {}
    for sidecar in sorted(
        io_glob(work_root, "forms/*/editions/*/acquisitions/*.json"), key=lambda path: path.as_posix()
    ):
        acquisition = validate_acquisition(sidecar, root=root)
        acquisition_id = str(acquisition["acquisition_id"])
        if acquisition_id in result:
            raise PipelineError(f"duplicate acquisition_id below {context}: {acquisition_id}")
        expected_edition_id = sidecar.parent.parent.name
        if acquisition["edition_id"] != expected_edition_id:
            raise PipelineError(
                f"acquisition edition_id does not match directory: {sidecar} says "
                f"{acquisition['edition_id']!r}, expected {expected_edition_id!r}"
            )
        if acquisition_id != sidecar.stem:
            raise PipelineError(
                f"acquisition_id does not match sidecar filename: {sidecar} says "
                f"{acquisition_id!r}"
            )
        result[acquisition_id] = acquisition
    return result


def validate_state(path: Path, *, root: Path) -> dict[str, Any]:
    """Validate state plus work/form/edition/acquisition relationships.

    State is authoritative for progress, but it cannot mint a target whose
    identity is absent from the work or acquisition sidecars. Evidence paths
    are checked as references within the selected fixture root.
    """

    path = Path(path)
    root = Path(root)
    record = load_state(path)
    work_id = str(record["work_id"])
    work_root = _work_root_for_state(path, root, work_id)
    work_path = work_root / "work.json"
    work = load_work(work_path)
    if work["work_id"] != work_id:
        raise PipelineError(
            f"state work_id mismatch: {path} says {work_id!r}, work sidecar says {work['work_id']!r}"
        )
    _validate_acquisition_layout(work_path, work=work, editions=load_editions(work_path))
    editions = _edition_index(work)
    acquisitions = _acquisition_index(work_root, root=root, context=str(path))
    acquisition_paths = {
        sidecar.stem: sidecar
        for sidecar in io_glob(work_root, "forms/*/editions/*/acquisitions/*.json")
    }

    failures: list[str] = []
    for target in record["targets"]:
        target_id = str(target["target_id"])
        target_type = str(target["target_type"])
        if target_type == "edition":
            edition_entry = editions.get(target_id)
            if edition_entry is None:
                failures.append(f"target {target_id} does not identify an edition in {work_path}")
            elif target["stage"] == "accepted":
                form_id, _edition = edition_entry
                master_path = (
                    work_root
                    / "forms"
                    / form_id
                    / "editions"
                    / target_id
                    / "master.tei.xml"
                )
                if not io_path(master_path).is_file():
                    failures.append(f"accepted edition master missing: {master_path}")
                if not _evidence_binds_path(
                    target["evidence"], target_path=master_path, root=root, work_root=work_root
                ):
                    failures.append(
                        f"accepted edition target {target_id} evidence does not bind its master"
                    )
        elif target_type == "acquisition":
            acquisition = acquisitions.get(target_id)
            if acquisition is None:
                failures.append(
                    f"target {target_id} does not identify an acquisition below {work_root}"
                )
            elif acquisition["edition_id"] not in editions:
                failures.append(
                    f"acquisition {target_id} points to unknown edition "
                    f"{acquisition['edition_id']}"
                )
            elif target["stage"] == "acquired":
                sidecar = acquisition_paths.get(target_id)
                if sidecar is None:
                    failures.append(f"acquisition sidecar missing for acquired target {target_id}")
                else:
                    retained_references = {
                        str(item["path"])
                        for item in acquisition["retained_files"]
                        if isinstance(item, dict)
                    }
                    sidecar_bound = _evidence_binds_path(
                        target["evidence"], target_path=sidecar, root=root, work_root=work_root
                    )
                    retained_bound = any(
                        _evidence_binds_path(
                            target["evidence"],
                            target_path=root / reference,
                            root=root,
                            work_root=work_root,
                        )
                        for reference in retained_references
                    )
                    if not sidecar_bound and not retained_bound:
                        failures.append(
                            f"acquired target {target_id} evidence does not bind its sidecar "
                            "or a retained file"
                        )
        else:  # guarded by schema, retained for callers passing nonstandard dicts
            failures.append(f"target {target_id} has unsupported target_type {target_type!r}")
        evidence = target.get("evidence")
        if isinstance(evidence, list):
            try:
                _existing_evidence_paths(
                    evidence, root=root, work_root=work_root, context=f"{path} target {target_id}"
                )
            except PipelineError as exc:
                failures.append(str(exc))
    if failures:
        raise PipelineError("state relationship validation failed: " + "; ".join(failures))
    return record


def targets_by_id(path: Path) -> dict[str, dict[str, Any]]:
    record = load_state(path)
    return {target["target_id"]: target for target in record["targets"]}


def reopen_blocked_edition(
    root: Path,
    *,
    work_id: str,
    edition_id: str,
    expected_state_sha256: str,
    reason: str,
    evidence: list[str],
) -> dict[str, Any]:
    """Reopen an uninstalled blocked edition, retaining its blocker history."""

    root = resolve_path(Path(root))
    safe_identifier(work_id, field="work_id")
    safe_identifier(edition_id, field="edition_id")
    work_root = root / "library" / "works" / work_id
    path = work_root / "state.json"
    if resolve_path(work_root) != work_root or resolve_path(path) != path:
        raise PipelineError("state reopening refuses linked work paths")
    if not isinstance(reason, str) or not reason.strip() or not evidence:
        raise PipelineError("state reopening requires a reason and evidence")
    with acquire_jsonl_lock(work_root):
        before = io_path(path).read_bytes()
        if hashlib.sha256(before).hexdigest() != expected_state_sha256:
            raise PipelineError("state reopening preimage does not match")
        state = validate_state(path, root=root)
        target = next((item for item in state["targets"] if item["target_id"] == edition_id), None)
        if target is None or target["target_type"] != "edition" or target["stage"] != "blocked":
            raise PipelineError("state reopening requires a blocked edition target")
        form_id, _edition = _edition_index(load_work(work_root / "work.json"))[edition_id]
        edition_root = work_root / "forms" / form_id / "editions" / edition_id
        if any(io_path(edition_root / name).exists() for name in ("master.tei.xml", "acceptance.json")):
            raise PipelineError("state reopening refuses an installed master or acceptance")
        _existing_evidence_paths(evidence, root=root, work_root=work_root, context="state reopening")
        target["stage"] = "review"
        target["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        prior_reason = target.get("reason", "")
        target["reason"] = (prior_reason + "\n" if prior_reason else "") + reason.strip()
        for reference in evidence:
            if reference not in target["evidence"]:
                target["evidence"].append(reference)
        validate_record("state", state, context=str(path))
        if io_path(path).read_bytes() != before:
            raise PipelineError("state changed during reopening validation")
        write_json_atomic(path, state, _schema("state"))
        return validate_state(path, root=root)


def reconcile_state(
    root: Path,
    *,
    work_id: str,
    edition_id: str,
    master_path: Path,
) -> dict[str, Any]:
    """Return generated status facts without changing the authority sidecar."""

    root = Path(root)
    state_path = root / "library" / "works" / work_id / "state.json"
    state = load_state(state_path)
    if state["work_id"] != work_id:
        raise PipelineError(f"state work_id mismatch: {state_path}")
    target = next(
        (item for item in state["targets"] if item["target_id"] == edition_id),
        None,
    )
    if target is None:
        return {
            "work_id": work_id,
            "edition_id": edition_id,
            "stage": "excluded",
            "status": "excluded",
            "reasons": ["edition has no state target"],
        }
    try:
        validate_state(state_path, root=root)
    except PipelineError as exc:
        return {
            "work_id": work_id,
            "edition_id": edition_id,
            "stage": target["stage"],
            "status": "failed",
            "reasons": [str(exc)],
        }
    reasons: list[str] = []
    if target.get("target_type") != "edition":
        reasons.append(f"target type is {target.get('target_type')!r}, not 'edition'")
    try:
        resolve_path(master_path).relative_to(resolve_path(root))
    except (OSError, RuntimeError, ValueError):
        reasons.append("accepted master is outside fixture root")
    evidence = target.get("evidence", [])
    evidence_matches = False
    for reference in evidence:
        if not isinstance(reference, str):
            continue
        try:
            relative = ensure_relative_path(reference, field="state evidence")
        except PipelineError:
            continue
        for base in (root / "library" / "works" / work_id, root):
            try:
                candidate = resolve_path(base / relative)
                candidate.relative_to(resolve_path(root))
            except (OSError, RuntimeError, ValueError):
                continue
            if candidate == resolve_path(master_path):
                evidence_matches = True
                break
        if evidence_matches:
            break
    if not evidence_matches:
        reasons.append("state evidence does not bind the selected accepted master")
    if not io_path(master_path).is_file():
        reasons.append(f"accepted master missing: {master_path}")
    accepted_stage = "accepted"
    if accepted_stage not in schema_enum("state", "stage"):
        raise PipelineError("state schema does not define accepted stage")
    if target["stage"] != accepted_stage:
        return {
            "work_id": work_id,
            "edition_id": edition_id,
            "stage": target["stage"],
            "status": "excluded",
            "reasons": [f"state stage is {target['stage']!r}, not accepted"],
        }
    if reasons:
        return {
            "work_id": work_id,
            "edition_id": edition_id,
            "stage": target["stage"],
            "status": "failed",
            "reasons": reasons,
        }
    return {
        "work_id": work_id,
        "edition_id": edition_id,
        "stage": target["stage"],
        "status": "included",
        "reasons": [],
    }
