"""Install or safely replace one accepted work in a bounded repository.

The ordinary installer refuses to replace a live accepted master without a
complete ``expected_old`` snapshot.  That snapshot opts into the guarded
replacement protocol.  That protocol serializes cooperating writers with a
filesystem lock, stages a complete incoming tree, records durable operation
phases, preserves the previous tree, and lets recovery choose only a complete
old or new generation.

The directory handoff has a brief unavailable interval on platforms where a
non-empty directory cannot be atomically replaced.  Readers using
``read_accepted_work`` retry that interval and therefore receive a complete
generation rather than a partially copied tree.
"""

from __future__ import annotations

from ocd_kernel.lib.path_io import io_path, ordinary_path, resolve_path, io_glob, io_rglob
from ocd_kernel.lib.path_io import io_path as _io_path

from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from typing import Any, Callable, Mapping
import uuid

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError, load_json, safe_identifier
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import load_state, validate_state
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    _validate_acceptance_for_work,
    validate_acceptance,
)


Checkpoint = Callable[[str], None]
_TERMINAL_RECOVERY_PHASES = {
    "complete",
    "recovered-old",
    "recovered-new",
    "rolled-back",
    "failed-before-commit",
}


def _files(directory: Path) -> dict[str, str]:
    directory = ordinary_path(_io_path(directory))
    result: dict[str, str] = {}
    for path in sorted(io_rglob(directory, "*")):
        if io_path(path).is_symlink() or io_path(path).is_junction():
            raise PipelineError(f"work installation refuses linked paths: {path}")
        if io_path(path).is_file():
            result[path.relative_to(directory).as_posix()] = hashlib.sha256(
                io_path(path).read_bytes()
            ).hexdigest()
    return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _write_json_durable(path: Path, value: Mapping[str, Any]) -> None:
    """Replace one journal file after flushing its complete temporary bytes."""

    io_path(path.parent).mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with io_path(temporary).open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(io_path(temporary), io_path(path))
    except Exception:
        try:
            if io_path(temporary).exists():
                io_path(temporary).unlink()
        except OSError:
            pass
        raise


def _journal_update(
    path: Path, journal: Mapping[str, Any], phase: str, **updates: Any
) -> dict[str, Any]:
    updated = dict(journal)
    updated.update(updates)
    updated["phase"] = phase
    updated["updated_at"] = _utc_now()
    _write_json_durable(path, updated)
    return updated


def _checkpoint(fail_at: Checkpoint | None, name: str) -> None:
    if fail_at is not None:
        fail_at(name)


def _is_named_file(path: str, name: str) -> bool:
    return path == name or path.endswith("/" + name)


def _has_accepted_master(manifest: Mapping[str, str]) -> bool:
    return any(
        _is_named_file(path, "acceptance.json") or _is_named_file(path, "master.tei.xml")
        for path in manifest
    )


def _accepted_paths(manifest: Mapping[str, str], name: str) -> set[str]:
    return {path for path in manifest if _is_named_file(path, name)}


def _normalize_manifest(value: Mapping[str, str], *, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise PipelineError(f"{field} must be a file hash mapping")
    result: dict[str, str] = {}
    for path, checksum in value.items():
        if (
            not isinstance(path, str)
            or not path
            or Path(path).is_absolute()
            or ".." in Path(path).parts
        ):
            raise PipelineError(f"{field} contains an unsafe relative path: {path!r}")
        if (
            not isinstance(checksum, str)
            or len(checksum) != 64
            or any(character not in "0123456789abcdef" for character in checksum.lower())
        ):
            raise PipelineError(f"{field} contains an invalid SHA-256 for {path!r}")
        result[path.replace("\\", "/")] = checksum.lower()
    return result


def _identity_key(record: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    identity = record.get("identity")
    if not isinstance(identity, Mapping):
        raise PipelineError("accepted work identity is missing")
    return tuple(
        (key, identity.get(key))
        for key in ("work_id", "textual_form_id", "edition_id", "acquisition_id")
    )


def _acceptance_paths(target: Path) -> list[Path]:
    """Discover long Windows paths while retaining logical paths for validation."""

    return sorted(io_rglob(target, "acceptance.json"))


def _validate_promoted_tree(root: Path, target: Path, *, work_id: str) -> list[dict[str, Any]]:
    acceptances = _acceptance_paths(target)
    if not acceptances:
        raise PipelineError("staging has no accepted edition")
    records: list[dict[str, Any]] = []
    for path in acceptances:
        record = validate_acceptance(path, root=root)
        if (
            record["identity"]["work_id"] != work_id
            or record["promotion"]["status"] != "promoted"
        ):
            raise PipelineError("staging acceptance is not promoted for this work")
        records.append(record)
    return records


def _validate_generation(
    root: Path, target: Path, manifest: Mapping[str, str], *, work_id: str
) -> None:
    if not io_path(target).is_dir() or _files(target) != dict(manifest):
        raise PipelineError("recovered work generation does not match its journaled manifest")
    if _has_accepted_master(manifest):
        _validate_promoted_tree(root, target, work_id=work_id)


def _resolve_work_paths(
    root: Path, promoted: Path, work_id: str
) -> tuple[Path, Path, Path, Path]:
    root, promoted = resolve_path(Path(root)), resolve_path(Path(promoted))
    safe_identifier(work_id, field="work_id")
    relative = Path("library/works") / work_id
    target, source = root / relative, promoted / relative
    for base, path in ((root, target), (promoted, source)):
        resolved = resolve_path(path)
        if resolved != path or base not in resolved.parents:
            raise PipelineError("work installation path escapes its repository")
        if io_path(path).is_symlink() or io_path(path).is_junction():
            raise PipelineError("work installation requires existing local work trees")
        if path == target and not io_path(path).exists():
            continue
        if not io_path(path).is_dir():
            raise PipelineError("work installation requires existing local work trees")
    return root, promoted, target, source


def _replacement_changes_are_scoped(
    before: Mapping[str, str], after: Mapping[str, str]
) -> None:
    if _accepted_paths(before, "acceptance.json") != _accepted_paths(after, "acceptance.json"):
        raise PipelineError("replacement changes the accepted-edition set")
    if _accepted_paths(before, "master.tei.xml") != _accepted_paths(after, "master.tei.xml"):
        raise PipelineError("replacement changes the accepted-master set")

    def is_representation_path(path: str) -> bool:
        return (
            path == "state.json"
            or path.startswith("acceptance/")
            or "/acceptance/" in path
            or _is_named_file(path, "acceptance.json")
            or _is_named_file(path, "master.tei.xml")
        )

    for path in set(before) | set(after):
        if before.get(path) != after.get(path) and not is_representation_path(path):
            raise PipelineError(f"replacement changes non-representation authority: {path}")


def _validate_state_transition(
    target: Path,
    source: Path,
    *,
    existed: bool,
    replacement: bool,
    accepted_evidence_by_edition: Mapping[str, tuple[str, str]],
) -> None:
    new_state = load_json(source / "state.json")
    old_state = load_json(target / "state.json") if existed else {**new_state, "targets": []}
    if {key: value for key, value in old_state.items() if key != "targets"} != {
        key: value for key, value in new_state.items() if key != "targets"
    }:
        raise PipelineError("staging changes existing state identity")
    old_targets = old_state.get("targets", [])
    new_targets = new_state.get("targets", [])
    if not isinstance(old_targets, list) or not isinstance(new_targets, list):
        raise PipelineError("work state targets must be lists")
    if replacement:
        new_by_id = {
            item.get("target_id"): item
            for item in new_targets
            if isinstance(item, dict) and isinstance(item.get("target_id"), str)
        }
        for item in old_targets:
            if not isinstance(item, dict):
                raise PipelineError("existing work state target is invalid")
            replacement_item = new_by_id.get(item.get("target_id"))
            if (
                not isinstance(replacement_item, dict)
                or replacement_item.get("target_type") != item.get("target_type")
            ):
                raise PipelineError("replacement removes or changes an existing state target")
            if replacement_item != item:
                expected_item = dict(item)
                references = accepted_evidence_by_edition.get(item.get("target_id"))
                if item.get("target_type") != "edition" or not references:
                    raise PipelineError("replacement changes another state target")
                expected_item.update(
                    stage="accepted", reason=PROMOTED_MASTER_REASON,
                    updated_at=replacement_item.get("updated_at"),
                    evidence=list(item.get("evidence", [])),
                )
                for reference in references:
                    if reference not in expected_item["evidence"]:
                        expected_item["evidence"].append(reference)
                if replacement_item != expected_item:
                    raise PipelineError("replacement changes accepted state beyond its promotion evidence")
    else:
        new_by_id = {
            item.get("target_id"): item
            for item in new_targets
            if isinstance(item, dict) and isinstance(item.get("target_id"), str)
        }
        for item in old_targets:
            if item in new_targets:
                continue
            if not isinstance(item, dict):
                raise PipelineError("existing work state target is invalid")
            promoted_item = new_by_id.get(item.get("target_id"))
            unchanged_fields = {
                key: value
                for key, value in item.items()
                if key not in {"stage", "updated_at", "evidence", "reason"}
            }
            promoted_unchanged_fields = (
                {
                    key: value
                    for key, value in promoted_item.items()
                    if key not in {"stage", "updated_at", "evidence", "reason"}
                }
                if isinstance(promoted_item, dict)
                else None
            )
            old_evidence = item.get("evidence")
            new_evidence = (
                promoted_item.get("evidence")
                if isinstance(promoted_item, dict)
                else None
            )
            expected_evidence = (
                list(old_evidence) if isinstance(old_evidence, list) else None
            )
            if expected_evidence is not None:
                for reference in accepted_evidence_by_edition.get(
                    item.get("target_id"), ()
                ):
                    if reference not in expected_evidence:
                        expected_evidence.append(reference)
            if (
                item.get("target_type") != "edition"
                or item.get("target_id") not in accepted_evidence_by_edition
                or item.get("stage") not in {"acquired", "review"}
                or not isinstance(promoted_item, dict)
                or promoted_item.get("stage") != "accepted"
                or promoted_item.get("reason") != PROMOTED_MASTER_REASON
                or unchanged_fields != promoted_unchanged_fields
                or not isinstance(old_evidence, list)
                or not isinstance(new_evidence, list)
                or new_evidence != expected_evidence
            ):
                raise PipelineError("staging changes an existing state target")


def _validate_additive_work(
    target: Path,
    source: Path,
    *,
    work_id: str,
    textual_form_id: str,
    edition_id: str,
) -> set[str]:
    """Require the staged work to add exactly one edition to one existing form."""

    old_work = load_work(target / "work.json")
    new_work = load_work(source / "work.json")
    for work, label in ((old_work, "live"), (new_work, "staging")):
        if work["work_id"] != work_id:
            raise PipelineError(f"{label} work identity does not match the request")

    if {
        key: value for key, value in old_work.items() if key != "textual_forms"
    } != {
        key: value for key, value in new_work.items() if key != "textual_forms"
    }:
        raise PipelineError("staging changes work identity or evidence outside the new edition")

    old_forms = old_work["textual_forms"]
    new_forms = new_work["textual_forms"]
    old_form = next(
        (form for form in old_forms if form.get("textual_form_id") == textual_form_id),
        None,
    )
    new_form = next(
        (form for form in new_forms if form.get("textual_form_id") == textual_form_id),
        None,
    )
    if not isinstance(old_form, dict) or not isinstance(new_form, dict):
        raise PipelineError("additive edition requires an existing textual form")

    old_edition_ids = {
        edition.get("edition_id")
        for form in old_forms
        for edition in form.get("editions", [])
        if isinstance(edition, dict)
    }
    if edition_id in old_edition_ids:
        raise PipelineError(f"additive edition collides with existing edition: {edition_id}")

    added_editions = [
        edition
        for edition in new_form.get("editions", [])
        if isinstance(edition, dict) and edition.get("edition_id") == edition_id
    ]
    if len(added_editions) != 1:
        raise PipelineError("staging must declare exactly one requested new edition")

    reduced_forms: list[dict[str, Any]] = []
    removed = False
    for form in new_forms:
        reduced = dict(form)
        if form.get("textual_form_id") == textual_form_id:
            editions = list(form.get("editions", []))
            matching = [
                index
                for index, edition in enumerate(editions)
                if isinstance(edition, dict) and edition.get("edition_id") == edition_id
            ]
            if len(matching) != 1:
                raise PipelineError("staging declares an ambiguous requested new edition")
            editions.pop(matching[0])
            reduced["editions"] = editions
            removed = True
        reduced_forms.append(reduced)
    if not removed or reduced_forms != old_forms:
        raise PipelineError(
            "staging changes an existing form or declares an unrelated edition"
        )

    acquisition_ids = added_editions[0].get("acquisition_ids", [])
    if not isinstance(acquisition_ids, list) or not acquisition_ids:
        raise PipelineError("new edition must declare at least one acquisition_id")
    return {str(value) for value in acquisition_ids}


def _validate_additive_state_transition(
    target: Path,
    source: Path,
    *,
    work_id: str,
    edition_id: str,
    acquisition_ids: set[str],
) -> None:
    """Require existing state targets to remain byte-for-byte represented."""

    old_state = load_state(target / "state.json")
    new_state = load_state(source / "state.json")
    if old_state["work_id"] != work_id or new_state["work_id"] != work_id:
        raise PipelineError("staging changes state work identity")
    if {
        key: value for key, value in old_state.items() if key != "targets"
    } != {
        key: value for key, value in new_state.items() if key != "targets"
    }:
        raise PipelineError("staging changes state identity outside the new edition")

    old_targets = old_state["targets"]
    new_targets = new_state["targets"]
    old_by_id = {item["target_id"]: item for item in old_targets}
    new_by_id = {item["target_id"]: item for item in new_targets}
    missing = set(old_by_id) - set(new_by_id)
    if missing:
        raise PipelineError(
            "additive edition removes existing state targets: " + ", ".join(sorted(missing))
        )
    changed = sorted(
        target_id
        for target_id in old_by_id.keys() & new_by_id.keys()
        if old_by_id[target_id] != new_by_id[target_id]
    )
    if changed:
        raise PipelineError(
            "additive edition changes existing state targets: " + ", ".join(changed)
        )

    added_ids = set(new_by_id) - set(old_by_id)
    if edition_id not in added_ids:
        raise PipelineError("additive edition state target is missing")
    added_edition = new_by_id[edition_id]
    if added_edition["target_type"] != "edition":
        raise PipelineError("new edition state target has the wrong target type")
    for target_id in added_ids - {edition_id}:
        added_target = new_by_id[target_id]
        if (
            added_target["target_type"] != "acquisition"
            or target_id not in acquisition_ids
        ):
            raise PipelineError(
                f"additive edition adds an unrelated state target: {target_id}"
            )

    reduced_targets = [
        item for item in new_targets if item["target_id"] not in added_ids
    ]
    if reduced_targets != old_targets:
        raise PipelineError("additive edition reorders existing state targets")


def _additive_changes_are_scoped(
    before: Mapping[str, str],
    after: Mapping[str, str],
    *,
    textual_form_id: str,
    edition_id: str,
    acquisition_ids: set[str],
) -> None:
    """Reject changes outside the requested edition and declared sidecars."""

    for path, checksum in before.items():
        if path in {"work.json", "state.json"}:
            continue
        if after.get(path) != checksum:
            raise PipelineError(f"additive edition changes existing authority: {path}")

    edition_prefix = f"forms/{textual_form_id}/editions/{edition_id}/"
    allowed = {
        edition_prefix + "acceptance.json",
        edition_prefix + "master.tei.xml",
        *(
            edition_prefix + f"acquisitions/{acquisition_id}.json"
            for acquisition_id in acquisition_ids
        ),
    }
    unrelated = sorted(
        path
        for path in set(after) - set(before)
        if path not in {"work.json", "state.json"}
        and path not in allowed
    )
    if unrelated:
        raise PipelineError(
            "additive edition adds files outside the requested edition: "
            + ", ".join(unrelated)
        )


def _validate_additive_transition(
    root: Path,
    promoted: Path,
    target: Path,
    source: Path,
    *,
    work_id: str,
    textual_form_id: str,
    edition_id: str,
    before: Mapping[str, str],
    after: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Validate one complete future generation for an additive install."""

    old_records = _validate_promoted_tree(root, target, work_id=work_id)
    new_records = _validate_promoted_tree(promoted, source, work_id=work_id)
    if not old_records:
        raise PipelineError("additive edition requires an existing accepted edition")

    old_keys: dict[tuple[tuple[str, Any], ...], dict[str, Any]] = {}
    for record in old_records:
        key = _identity_key(record)
        if key in old_keys:
            raise PipelineError("live work contains duplicate accepted identities")
        old_keys[key] = record
    new_keys: dict[tuple[tuple[str, Any], ...], dict[str, Any]] = {}
    for record in new_records:
        key = _identity_key(record)
        if key in new_keys:
            raise PipelineError("staging contains duplicate accepted identities")
        new_keys[key] = record
    acquisition_ids = _validate_additive_work(
        target,
        source,
        work_id=work_id,
        textual_form_id=textual_form_id,
        edition_id=edition_id,
    )
    if not set(old_keys).issubset(new_keys):
        raise PipelineError("additive edition removes or changes an existing acceptance")
    added_keys = set(new_keys) - set(old_keys)
    if len(added_keys) != 1:
        raise PipelineError("staging must add exactly one accepted edition")
    added_identity = dict(new_keys[next(iter(added_keys))]["identity"])
    if (
        added_identity["work_id"] != work_id
        or added_identity["textual_form_id"] != textual_form_id
        or added_identity["edition_id"] != edition_id
    ):
        raise PipelineError("new acceptance identity does not match the requested edition")
    _additive_changes_are_scoped(
        before,
        after,
        textual_form_id=textual_form_id,
        edition_id=edition_id,
        acquisition_ids=acquisition_ids,
    )
    _validate_additive_state_transition(
        target,
        source,
        work_id=work_id,
        edition_id=edition_id,
        acquisition_ids=acquisition_ids,
    )
    return new_records


def _operation_root(root: Path) -> Path:
    return root / ".tmp_audit"


def _operation_path(root: Path, operation: Path) -> Path:
    audit = resolve_path(_operation_root(root))
    candidate = resolve_path(Path(operation))
    try:
        relative = candidate.relative_to(audit)
    except ValueError as exc:
        raise PipelineError("recovery operation escapes the repository audit area") from exc
    if len(relative.parts) != 1 or not candidate.name.startswith("accepted-install-"):
        raise PipelineError("recovery operation is not an accepted-install operation")
    if io_path(candidate).is_symlink() or io_path(candidate).is_junction() or not io_path(candidate).is_dir():
        raise PipelineError("recovery operation must be a local directory")
    return candidate


def _load_recovery_operation(
    root: Path, work_id: str, operation: Path | None
) -> tuple[Path, dict[str, Any]]:
    audit = _operation_root(root)
    candidates: list[tuple[Path, dict[str, Any]]] = []
    if operation is not None:
        candidate = _operation_path(root, operation)
        journal_path = candidate / "operation.json"
        journal = load_json(journal_path)
        candidates.append((candidate, journal))
    elif io_path(audit).is_dir():
        for journal_path in sorted(io_glob(audit, "accepted-install-*/operation.json")):
            try:
                journal = load_json(journal_path)
            except PipelineError:
                continue
            if (
                journal.get("work_id") == work_id
                and journal.get("phase") not in _TERMINAL_RECOVERY_PHASES
            ):
                candidates.append((journal_path.parent, journal))
    if not candidates:
        raise PipelineError(f"no recoverable accepted-install operation for {work_id}")
    candidate, journal = candidates[-1]
    if journal.get("work_id") != work_id:
        raise PipelineError("recovery operation work identity does not match the request")
    return candidate, journal


def _rollback_after_failure(
    operation: Path,
    journal_path: Path,
    journal: Mapping[str, Any],
    target: Path,
    *,
    existed: bool,
    original_error: Exception,
) -> None:
    phase = str(journal.get("phase"))
    backup = operation / "previous"
    try:
        if phase in {"after-previous-moved", "after-new-live", "after-validated"}:
            if io_path(target).exists():
                failed = operation / "failed"
                if io_path(failed).exists():
                    failed = operation / f"failed-{uuid.uuid4().hex}"
                io_path(target).rename(io_path(failed))
            if existed:
                if not io_path(backup).is_dir():
                    raise PipelineError("previous generation is missing during rollback")
                io_path(backup).rename(io_path(target))
        _journal_update(
            journal_path,
            journal,
            "rolled-back" if phase != "prepared" else "failed-before-commit",
            error=f"{type(original_error).__name__}: {original_error}",
        )
    except Exception as recovery_error:
        _journal_update(
            journal_path,
            journal,
            "recovery-required",
            error=f"{type(original_error).__name__}: {original_error}",
            recovery_error=f"{type(recovery_error).__name__}: {recovery_error}",
        )
        raise PipelineError(
            "installation failed and automatic rollback requires recovery; "
            f"operation retained at {operation}"
        ) from recovery_error


def _commit_generation(
    root: Path,
    target: Path,
    source: Path,
    *,
    work_id: str,
    before: Mapping[str, str],
    after: Mapping[str, str],
    existed: bool,
    replacement: bool,
    operation_kind: str,
    result_status: str,
    accepted_editions: int,
    fail_at: Checkpoint | None,
) -> dict[str, Any]:
    """Commit one already-validated complete generation under the held locks."""

    # Keep the journal under the same-volume audit root while leaving room for long work paths on Windows.
    operation = _operation_root(root) / ("accepted-install-" + uuid.uuid4().hex[:16])
    if resolve_path(operation) != operation or root not in resolve_path(operation).parents:
        raise PipelineError("rollback path escapes repository")
    io_path(operation).mkdir(parents=True)
    incoming, backup = operation / "incoming", operation / "previous"
    journal_path = operation / "operation.json"
    journal: dict[str, Any] = {
        "schema_version": 1,
        "work_id": work_id,
        "target": (Path("library/works") / work_id).as_posix(),
        "existed": existed,
        "replacement": replacement,
        "operation_kind": operation_kind,
        "before": dict(before),
        "after": dict(after),
        "phase": "prepared",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }
    _write_json_durable(journal_path, journal)
    try:
        shutil.copytree(_io_path(source), _io_path(incoming))
        if _files(incoming) != dict(after) or _files(source) != dict(after) or _files(target) != dict(before):
            raise PipelineError("work changed during installation preparation")
        if io_path(target).exists() != existed:
            raise PipelineError("work appeared or disappeared during installation")
        journal = _journal_update(journal_path, journal, "after-incoming")
        _checkpoint(fail_at, "after-incoming")

        io_path(target.parent).mkdir(parents=True, exist_ok=True)
        if _files(source) != dict(after) or _files(target) != dict(before):
            raise PipelineError("work changed before the installation commit")
        if existed:
            io_path(target).rename(io_path(backup))
        journal = _journal_update(journal_path, journal, "after-previous-moved")
        _checkpoint(fail_at, "after-previous-moved")

        io_path(incoming).rename(io_path(target))
        journal = _journal_update(journal_path, journal, "after-new-live")
        _checkpoint(fail_at, "after-new-live")
        for acceptance in _acceptance_paths(target):
            _validate_acceptance_for_work(acceptance, root=root, work_id=work_id)
        work = load_json(target / "work.json")
        if "original_language" in work:
            from build.lib.source_metadata import lookup_work_original_language

            lookup_work_original_language(root, target / "work.json")
        if "work_kind" in work:
            from build.lib.source_metadata import lookup_work_kind

            lookup_work_kind(root, target / "work.json")
        if _files(target) != dict(after):
            raise PipelineError("installed work changed during validation")
        journal = _journal_update(journal_path, journal, "after-validated")
        _checkpoint(fail_at, "after-validated")
        _journal_update(
            journal_path,
            journal,
            "complete",
            result_status=result_status,
        )
    except Exception as exc:
        _rollback_after_failure(
            operation,
            journal_path,
            journal,
            target,
            existed=existed,
            original_error=exc,
        )
        raise
    return {
        "status": result_status,
        "work_id": work_id,
        "backup": str(backup) if existed else None,
        "operation": str(operation),
        "previous_files": dict(before),
        "installed_files": dict(after),
        "accepted_editions": accepted_editions,
    }


def install_accepted_work(
    root: Path,
    promoted: Path,
    *,
    work_id: str,
    expected_old: Mapping[str, str] | None = None,
    reviewed_new: Mapping[str, str] | None = None,
    initial_work_transition: Mapping[str, Any] | None = None,
    fail_at: Checkpoint | None = None,
    lock_acquire_timeout: float = 30.0,
) -> dict[str, Any]:
    """Install one promoted work, or replace an exactly reconciled generation.

    Without ``expected_old`` the existing guard refuses a live accepted
    master.  Supplying the complete hash snapshot opts into the bounded
    replacement protocol and makes the stale-writer check explicit.
    ``reviewed_new`` additionally binds every incoming file when a reviewed
    change includes edition declarations or publication metadata. Existing
    identities, acquisitions, files, and unrelated state targets are retained.
    An initial_work_transition binds the entire original acquired file map and
    one permitted incoming work.json hash. The journal stores original file
    hashes; the previous-generation backup preserves original bytes for the
    ordinary rollback transaction.
    """

    root, promoted, target, source = _resolve_work_paths(root, promoted, work_id)
    expected = (
        _normalize_manifest(expected_old, field="expected_old")
        if expected_old is not None
        else None
    )
    reviewed = (
        _normalize_manifest(reviewed_new, field="reviewed_new")
        if reviewed_new is not None else None
    )
    if reviewed is not None and (expected is None or initial_work_transition is not None):
        raise PipelineError("reviewed generation requires expected_old and no initial_work_transition")
    initial_expected = None
    initial_work_sha = None
    if initial_work_transition is not None:
        if expected is not None:
            raise PipelineError("initial work transition cannot opt into accepted replacement")
        if not isinstance(initial_work_transition, Mapping) or set(initial_work_transition) != {"expected_files", "work_json_sha256"}:
            raise PipelineError("initial work transition requires exact expected_files and work_json_sha256")
        initial_expected = _normalize_manifest(initial_work_transition["expected_files"], field="initial_work_transition.expected_files")
        initial_work_sha = _normalize_manifest({"work.json": initial_work_transition["work_json_sha256"]}, field="initial_work_transition.work_json_sha256")["work.json"]
        if "work.json" not in initial_expected or initial_expected["work.json"] == initial_work_sha:
            raise PipelineError("initial work transition requires an existing and changed work.json")

    lock_targets = sorted({target, source}, key=lambda path: path.as_posix())
    with ExitStack() as locks:
        for lock_target in lock_targets:
            locks.enter_context(
                acquire_jsonl_lock(lock_target, acquire_timeout=lock_acquire_timeout)
            )
        existed = io_path(target).exists()
        before = _files(target)
        if expected is not None and before != expected:
            raise PipelineError("expected-old snapshot does not match live work")
        after = _files(source)
        if reviewed is not None and after != reviewed:
            raise PipelineError("reviewed-new snapshot does not match staging work")
        has_accepted = _has_accepted_master(before)
        if initial_expected is not None:
            if has_accepted:
                raise PipelineError("initial work transition refuses an accepted work")
            if before != initial_expected:
                raise PipelineError("initial work transition expected files do not match live work")
            if after.get("work.json") != initial_work_sha:
                raise PipelineError("initial work transition incoming work.json hash differs")
        replacement = has_accepted and expected is not None
        if has_accepted and expected is None:
            raise PipelineError(
                "work already has master/acceptance; explicit replacement reconciliation required"
            )
        old_records = (
            _validate_promoted_tree(root, target, work_id=work_id) if replacement else []
        )
        new_records = _validate_promoted_tree(promoted, source, work_id=work_id)
        if reviewed is not None:
            old_work = load_work(target / "work.json")
            new_work = load_work(source / "work.json")
            if old_work["work_id"] != work_id or new_work["work_id"] != work_id:
                raise PipelineError("reviewed generation changes work identity")
            def declarations(work):
                result = set()
                for form in work["textual_forms"]:
                    form_id = form["textual_form_id"]
                    result.add((form_id,))
                    for edition in form["editions"]:
                        edition_id = edition["edition_id"]
                        result.add((form_id, edition_id))
                        for acquisition_id in edition.get("acquisition_ids", []):
                            result.add((form_id, edition_id, acquisition_id))
                return result
            if not declarations(old_work) <= declarations(new_work):
                raise PipelineError("reviewed generation removes or moves an existing declaration")
            old_keys = {_identity_key(record) for record in old_records}
            new_keys = {_identity_key(record) for record in new_records}
            if len(new_keys) != len(new_records) or not old_keys <= new_keys:
                raise PipelineError("reviewed generation removes or duplicates an accepted identity")
            archived = set()
            for path, checksum in before.items():
                if path not in after:
                    parts = Path(path).parts
                    matches = [candidate for candidate, digest in after.items()
                        if candidate not in before and candidate not in archived
                        and len(Path(candidate).parts) == 4
                        and Path(candidate).parts[:2] == ("publication", "history")
                        and Path(candidate).name == Path(path).name and digest == checksum]
                    if (len(parts) != 6 or parts[0] != "forms" or parts[2] != "editions"
                            or parts[4] != "rights" or not parts[5].endswith("-assessment.json")
                            or len(matches) != 1):
                        raise PipelineError(f"reviewed generation removes an existing file: {path}")
                    archived.add(matches[0])
                if "/acquisitions/" in path and after[path] != checksum:
                    raise PipelineError(f"reviewed generation changes acquisition evidence: {path}")
            validate_state(source / "state.json", root=promoted)
        elif replacement:
            if {_identity_key(record) for record in old_records} != {
                _identity_key(record) for record in new_records
            }:
                raise PipelineError("replacement changes accepted work identity")
            _replacement_changes_are_scoped(before, after)
        else:
            for path, checksum in before.items():
                if path == "work.json" and initial_expected is not None:
                    continue
                if path != "state.json" and after.get(path) != checksum:
                    raise PipelineError(f"staging changes existing work authority: {path}")
        accepted_evidence_by_edition = {}
        for record in new_records:
            master_reference = record["promotion"]["master"]["path"]
            accepted_evidence_by_edition[record["identity"]["edition_id"]] = (
                master_reference,
                Path(master_reference).with_name("acceptance.json").as_posix(),
            )
        _validate_state_transition(
            target,
            source,
            existed=existed,
            replacement=replacement or reviewed is not None,
            accepted_evidence_by_edition=accepted_evidence_by_edition,
        )
        result_status = (
            "replaced-and-validated" if replacement else "installed-and-validated"
        )
        return _commit_generation(
            root,
            target,
            source,
            work_id=work_id,
            before=before,
            after=after,
            existed=existed,
            replacement=replacement,
            operation_kind="reviewed-generation" if reviewed is not None else "replacement" if replacement else "initial-install",
            result_status=result_status,
            accepted_editions=len(new_records),
            fail_at=fail_at,
        )


def add_accepted_edition(
    root: Path,
    promoted: Path,
    *,
    work_id: str,
    textual_form_id: str,
    edition_id: str,
    expected_old: Mapping[str, str],
    fail_at: Checkpoint | None = None,
    lock_acquire_timeout: float = 30.0,
) -> dict[str, Any]:
    """Add one accepted edition to an exactly reconciled existing work.

    ``promoted`` must contain a complete future work generation: every existing
    accepted edition plus exactly one newly accepted edition.  The operation is
    guarded by the same expected-old, lock, journal, rollback, and
    reader/recovery protocol as accepted-work replacement.  Existing work files
    and state targets are preserved; only the requested edition and its
    declared state additions may be new.
    """

    root, promoted, target, source = _resolve_work_paths(root, promoted, work_id)
    safe_identifier(textual_form_id, field="textual_form_id")
    safe_identifier(edition_id, field="edition_id")
    expected = _normalize_manifest(expected_old, field="expected_old")

    lock_targets = sorted({target, source}, key=lambda path: path.as_posix())
    with ExitStack() as locks:
        for lock_target in lock_targets:
            locks.enter_context(
                acquire_jsonl_lock(lock_target, acquire_timeout=lock_acquire_timeout)
            )
        existed = io_path(target).exists()
        if not existed:
            raise PipelineError("additive edition requires an existing accepted work")
        before = _files(target)
        if before != expected:
            raise PipelineError("expected-old snapshot does not match live work")
        after = _files(source)
        if not _has_accepted_master(before):
            raise PipelineError("additive edition requires an existing accepted edition")
        new_records = _validate_additive_transition(
            root,
            promoted,
            target,
            source,
            work_id=work_id,
            textual_form_id=textual_form_id,
            edition_id=edition_id,
            before=before,
            after=after,
        )
        return _commit_generation(
            root,
            target,
            source,
            work_id=work_id,
            before=before,
            after=after,
            existed=existed,
            replacement=False,
            operation_kind="addition",
            result_status="added-and-validated",
            accepted_editions=len(new_records),
            fail_at=fail_at,
        )


def add_accepted_scope(
    root: Path,
    promoted: Path,
    *,
    work_id: str,
    textual_form_id: str,
    edition_id: str,
    acquisition_id: str,
    expected_old: Mapping[str, str],
    fail_at: Checkpoint | None = None,
    lock_acquire_timeout: float = 30.0,
) -> dict[str, Any]:
    """Add one acquisition-bound acceptance to an already accepted edition."""

    root, promoted, target, source = _resolve_work_paths(root, promoted, work_id)
    for field, value in (("textual_form_id", textual_form_id), ("edition_id", edition_id),
                         ("acquisition_id", acquisition_id)):
        safe_identifier(value, field=field)
    expected = _normalize_manifest(expected_old, field="expected_old")
    with ExitStack() as locks:
        for lock_target in sorted({target, source}, key=lambda path: path.as_posix()):
            locks.enter_context(acquire_jsonl_lock(lock_target, acquire_timeout=lock_acquire_timeout))
        before, after = _files(target), _files(source)
        if before != expected:
            raise PipelineError("expected-old snapshot does not match live work")
        if not _has_accepted_master(before):
            raise PipelineError("scoped addition requires an existing accepted edition")
        prefix = f"forms/{textual_form_id}/editions/{edition_id}/scopes/{acquisition_id}/"
        master_ref = prefix + "master.tei.xml"
        acceptance_ref = prefix + "acceptance.json"
        if set(after) - set(before) != {master_ref, acceptance_ref}:
            raise PipelineError("scoped addition must add exactly the requested master and acceptance")
        for path, checksum in before.items():
            if path != "state.json" and after.get(path) != checksum:
                raise PipelineError(f"scoped addition changes existing authority: {path}")
        old_records = _validate_promoted_tree(root, target, work_id=work_id)
        new_records = _validate_promoted_tree(promoted, source, work_id=work_id)
        old_keys = {_identity_key(record) for record in old_records}
        new_keys = {_identity_key(record) for record in new_records}
        identity = tuple((key, value) for key, value in (
            ("work_id", work_id), ("textual_form_id", textual_form_id),
            ("edition_id", edition_id), ("acquisition_id", acquisition_id)))
        if (len(old_keys) != len(old_records) or len(new_keys) != len(new_records)
                or identity in old_keys or new_keys != old_keys | {identity}):
            raise PipelineError("scoped addition changes or duplicates an accepted identity")
        old_state, new_state = load_state(target / "state.json"), load_state(source / "state.json")
        old_targets, new_targets = old_state["targets"], new_state["targets"]
        if old_state["work_id"] != work_id or new_state["work_id"] != work_id or len(old_targets) != len(new_targets):
            raise PipelineError("scoped addition changes state identity or target count")
        edition_found = False
        for old, new in zip(old_targets, new_targets):
            if old.get("target_id") == edition_id and old.get("target_type") == "edition":
                edition_found = True
                if old.get("stage") != "accepted" or new.get("stage") != "accepted":
                    raise PipelineError("scoped addition requires the accepted edition target")
                expected_target = dict(old)
                expected_target["evidence"] = [
                    *old["evidence"],
                    (Path("library/works") / work_id / master_ref).as_posix(),
                    (Path("library/works") / work_id / acceptance_ref).as_posix(),
                ]
                expected_target["updated_at"] = new.get("updated_at")
                if new != expected_target:
                    raise PipelineError("scoped addition changes accepted edition state beyond its evidence")
            elif old != new:
                raise PipelineError("scoped addition changes another state target")
        if not edition_found:
            raise PipelineError("scoped addition lacks the accepted edition target")
        return _commit_generation(
            root, target, source, work_id=work_id, before=before, after=after,
            existed=True, replacement=False, operation_kind="scope-addition",
            result_status="scope-added-and-validated", accepted_editions=len(new_records),
            fail_at=fail_at,
        )


def read_accepted_work(
    root: Path,
    *,
    work_id: str,
    attempts: int = 100,
    retry_delay: float = 0.01,
) -> Path:
    """Return the live work path, retrying the documented swap gap.

    The writer publishes a complete directory in one rename, but moving the
    old directory aside first can briefly make the target unavailable. Readers
    must use this helper (or the same retry contract) and must not interpret a
    missing target during that interval as a missing work.
    """

    if attempts < 1:
        raise PipelineError("reader attempts must be positive")
    if retry_delay < 0:
        raise PipelineError("reader retry delay cannot be negative")
    root = resolve_path(Path(root))
    safe_identifier(work_id, field="work_id")
    target = root / "library" / "works" / work_id
    for attempt in range(attempts):
        if io_path(target).is_dir() and not io_path(target).is_symlink() and not io_path(target).is_junction():
            return target
        if io_path(target).exists() and not io_path(target).is_dir():
            raise PipelineError(f"live work path is not a directory: {target}")
        if attempt + 1 < attempts:
            time.sleep(retry_delay)
    raise PipelineError(
        f"live work was temporarily unavailable after {attempts} attempts: {target}"
    )


def recover_accepted_work(
    root: Path,
    *,
    work_id: str,
    operation: Path | None = None,
    lock_acquire_timeout: float = 30.0,
    lock_stale_threshold: float = 0.0,
) -> dict[str, Any]:
    """Recover a journaled operation without deleting either generation."""

    root = resolve_path(Path(root))
    safe_identifier(work_id, field="work_id")
    target = root / "library" / "works" / work_id
    operation_path, journal = _load_recovery_operation(root, work_id, operation)
    journal_path = operation_path / "operation.json"
    phase = str(journal.get("phase"))
    if phase == "complete":
        return {
            "status": "already-complete",
            "operation": str(operation_path),
            "work_id": work_id,
        }
    if phase in {"recovered-old", "recovered-new", "rolled-back"}:
        return {"status": phase, "operation": str(operation_path), "work_id": work_id}

    before = _normalize_manifest(journal.get("before", {}), field="journal.before")
    after = _normalize_manifest(journal.get("after", {}), field="journal.after")
    existed = bool(journal.get("existed"))
    incoming = operation_path / "incoming"
    backup = operation_path / "previous"

    with acquire_jsonl_lock(
        target,
        acquire_timeout=lock_acquire_timeout,
        stale_threshold=lock_stale_threshold,
    ):
        if io_path(target).is_dir():
            current = _files(target)
            if current == after:
                _validate_generation(root, target, after, work_id=work_id)
                if existed and (not io_path(backup).is_dir() or _files(backup) != before):
                    raise PipelineError(
                        "new live generation has an invalid previous-generation backup"
                    )
                _journal_update(journal_path, journal, "recovered-new")
                return {
                    "status": "recovered-new",
                    "operation": str(operation_path),
                    "work_id": work_id,
                }
            if current != before:
                raise PipelineError("recovery found a mixed or unknown live work generation")
            if existed and io_path(backup).is_dir() and _files(backup) != before:
                raise PipelineError("recovery found an invalid previous-generation backup")
            if _has_accepted_master(before):
                _validate_generation(root, target, before, work_id=work_id)
            _journal_update(journal_path, journal, "recovered-old")
            return {
                "status": "recovered-old",
                "operation": str(operation_path),
                "work_id": work_id,
            }

        if existed and io_path(backup).is_dir():
            if _files(backup) != before:
                raise PipelineError("recovery previous generation does not match its journal")
            io_path(backup).rename(io_path(target))
            _validate_generation(root, target, before, work_id=work_id)
            _journal_update(journal_path, journal, "recovered-old")
            return {
                "status": "recovered-old",
                "operation": str(operation_path),
                "work_id": work_id,
            }

        if not existed and io_path(incoming).is_dir() and _files(incoming) == after:
            io_path(incoming).rename(io_path(target))
            _validate_generation(root, target, after, work_id=work_id)
            _journal_update(journal_path, journal, "recovered-new")
            return {
                "status": "recovered-new",
                "operation": str(operation_path),
                "work_id": work_id,
            }

    raise PipelineError("recovery operation has no complete old or new generation")


__all__ = [
    "add_accepted_scope",
    "add_accepted_edition",
    "install_accepted_work",
    "read_accepted_work",
    "recover_accepted_work",
]
