"""Small, source-local decision contract for reconstruction evidence.

Decision files bind a work to one exact source manifest, candidate package,
validation report, and decider.  This module only reads and validates those
artifacts; it does not create acceptance state or publish an IR.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import sys
from typing import Mapping

from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path
from .text_quality import verify_text_quality

from .contract import (
    CandidatePackage,
    ReviewView,
    SourceManifest,
    ValidationReport,
    prepare_review,
    validate as validate_candidate,
)


DECISION_CONTRACT = "ocd-source-local-reconstruction-decision-v2"
CANDIDATE_DECISION_DISPOSITIONS = frozenset(
    {"accepted", "rejected", "needs-correction"}
)
DECISION_DISPOSITIONS = CANDIDATE_DECISION_DISPOSITIONS | {"blocked"}
BLOCKER_KINDS = frozenset({"source", "acquisition", "ezraocr", "rights", "identity"})
_COMMON_DECISION_KEYS = frozenset(
    {
        "contract",
        "source_id",
        "work_id",
        "source_manifest_path",
        "source_manifest_sha256",
        "disposition",
        "decided_by",
        "decided_at",
    }
)
_CANDIDATE_DECISION_KEYS = _COMMON_DECISION_KEYS | {
    "candidate_sha256",
    "validation_sha256",
    "rationale",
}
_BLOCKED_DECISION_KEYS = _COMMON_DECISION_KEYS | {"blocker"}
_BLOCKER_KEYS = frozenset(
    {
        "kind",
        "dependency",
        "evidence",
        "attempted_routes",
        "owner",
        "next_action",
        "reopening_condition",
    }
)
_BLOCKER_EVIDENCE_KEYS = frozenset({"path", "sha256"})
_ATTEMPTED_ROUTE_KEYS = frozenset({"route", "outcome", "evidence_refs"})
_VALIDATION_REPORT_KEYS = frozenset(
    {
        "contract",
        "status",
        "candidate_sha256",
        "source_manifest_sha256",
        "attestation",
        "findings",
    }
)


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            _jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    if value != value.casefold() or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _identity(value: object, label: str) -> str:
    text = _nonempty(value, label)
    if Path(text).name != text or text in {".", ".."}:
        raise ValueError(f"{label} must be a source-local identifier")
    return text


def _repository_file(root: Path, value: object, label: str) -> tuple[Path, str]:
    lexical_text = _nonempty(value, label)
    try:
        path = resolve_repo_path(root, lexical_text)
    except (IndexError, OSError, StorageTopologyError) as exc:
        raise ValueError(f"{label} is unavailable or escapes the repository") from exc
    if not path.is_file():
        raise ValueError(f"{label} must identify a file")
    return path, lexical_text


def _validate_decider(value: object, *, blocked: bool) -> str:
    role = _nonempty(value, "decided_by")
    allowed = (
        {"project-maintainer", "technical-reviewer"}
        if blocked
        else {"project-maintainer"}
    )
    if role not in allowed and not role.startswith("designated-human-reviewer:"):
        raise ValueError("decided_by must be an authorized stable role token")
    if (
        role.startswith("designated-human-reviewer:")
        and not role.split(":", 1)[1].strip()
    ):
        raise ValueError("decided_by designated reviewer token is empty")
    return role


def _resolved_identity(
    source_manifest: SourceManifest,
    *,
    source_id: str | None,
    work_id: str | None,
) -> tuple[str, str]:
    manifest_source_id = source_manifest.record.get("source_id")
    resolved_source_id = _identity(
        source_id if source_id is not None else manifest_source_id,
        "source_id",
    )
    if manifest_source_id != resolved_source_id:
        raise ValueError("decision source_id does not bind the source manifest")
    manifest_work_id = source_manifest.record.get("work_id")
    resolved_work_id = _identity(
        work_id if work_id is not None else manifest_work_id,
        "work_id",
    )
    if manifest_work_id is not None and manifest_work_id != resolved_work_id:
        raise ValueError("decision work_id does not bind the source manifest")
    return resolved_source_id, resolved_work_id


def decision_path(
    manifest_path: str | Path,
    source_id: str,
    work_id: str,
) -> Path:
    """Return the only source-local path for one work decision."""

    return Path(manifest_path).parent / (
        f"{_identity(source_id, 'source_id')}--{_identity(work_id, 'work_id')}.decision.json"
    )


def _validate_decided_at(value: object) -> str:
    decided_at = _nonempty(value, "decided_at")
    if not decided_at.endswith("Z"):
        raise ValueError("decided_at must be an ISO-8601 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(decided_at[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("decided_at must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("decided_at must include a UTC offset")
    return decided_at


def _raw_manifest_identity(
    manifest_path: str | Path,
    repository_root: str | Path,
    *,
    source_id: str | None,
    work_id: str | None,
) -> tuple[Path, bytes, str, str, str]:
    root = Path(repository_root).resolve(strict=True)
    supplied = Path(manifest_path)
    lexical = (
        supplied.relative_to(root).as_posix()
        if supplied.is_absolute()
        else supplied.as_posix()
    )
    path, relative_path = _repository_file(root, lexical, "source_manifest_path")
    content = path.read_bytes()
    raw = _strict_json(content, "source manifest")
    if raw.get("contract") != "ocd-source-manifest-v1":
        raise ValueError("source manifest contract mismatch")
    resolved_source_id = _identity(
        source_id if source_id is not None else raw.get("source_id"), "source_id"
    )
    resolved_work_id = _identity(
        work_id if work_id is not None else raw.get("work_id"), "work_id"
    )
    if raw.get("source_id") is not None and raw.get("source_id") != resolved_source_id:
        raise ValueError("decision source_id does not bind the source manifest")
    if raw.get("work_id") is not None and raw.get("work_id") != resolved_work_id:
        raise ValueError("decision work_id does not bind the source manifest")
    return path, content, relative_path, resolved_source_id, resolved_work_id


def _validate_blocker(value: object, repository_root: Path) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _BLOCKER_KEYS:
        raise ValueError("blocked decision blocker has missing or unknown fields")
    blocker = dict(_jsonable(value))
    kind = _nonempty(blocker.get("kind"), "blocker kind")
    if kind not in BLOCKER_KINDS:
        raise ValueError("blocked decision kind is not admissible")
    _nonempty(blocker.get("dependency"), "blocker dependency")
    evidence = blocker.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("blocked decision evidence must be a nonempty array")
    evidence_paths: set[str] = set()
    for index, item in enumerate(evidence):
        if not isinstance(item, Mapping) or set(item) != _BLOCKER_EVIDENCE_KEYS:
            raise ValueError("blocked decision evidence has missing or unknown fields")
        path, relative_path = _repository_file(
            repository_root, item.get("path"), f"blocker evidence[{index}].path"
        )
        if relative_path in evidence_paths:
            raise ValueError("blocked decision evidence paths must be unique")
        evidence_paths.add(relative_path)
        if item.get("path") != relative_path:
            raise ValueError("blocked decision evidence path is not normalized")
        if _sha(path.read_bytes()) != _digest(
            item.get("sha256"), f"blocker evidence[{index}].sha256"
        ):
            raise ValueError("blocked decision evidence digest is stale")
    attempts = blocker.get("attempted_routes")
    if not isinstance(attempts, list) or not attempts:
        raise ValueError("blocked decision attempted_routes must be a nonempty array")
    seen_routes: set[str] = set()
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, Mapping) or set(attempt) != _ATTEMPTED_ROUTE_KEYS:
            raise ValueError(
                "blocked decision attempted route has missing or unknown fields"
            )
        route = _nonempty(attempt.get("route"), f"attempted_routes[{index}].route")
        if route in seen_routes:
            raise ValueError("blocked decision attempted routes must be unique")
        seen_routes.add(route)
        _nonempty(attempt.get("outcome"), f"attempted_routes[{index}].outcome")
        refs = attempt.get("evidence_refs")
        if (
            not isinstance(refs, list)
            or not refs
            or any(
                not isinstance(ref, str) or ref not in evidence_paths for ref in refs
            )
        ):
            raise ValueError(
                "blocked decision attempted route evidence_refs must reference evidence paths"
            )
        if len(set(refs)) != len(refs):
            raise ValueError(
                "blocked decision attempted route evidence_refs must be unique"
            )
    _nonempty(blocker.get("owner"), "blocker owner")
    _nonempty(blocker.get("next_action"), "blocker next_action")
    _nonempty(blocker.get("reopening_condition"), "blocker reopening_condition")
    return blocker


def _validate_bound_record(
    record: Mapping[str, object],
    *,
    repository_root: Path,
    source_id: str,
    work_id: str,
    manifest_path: str,
    manifest_sha256: str,
    candidate_sha256: str | None = None,
    validation_sha256: str | None = None,
) -> dict[str, object]:
    values = dict(_jsonable(record))
    disposition = _nonempty(values.get("disposition"), "disposition")
    expected_keys = (
        _BLOCKED_DECISION_KEYS if disposition == "blocked" else _CANDIDATE_DECISION_KEYS
    )
    if set(values) != expected_keys:
        raise ValueError("source-local decision contract has missing or unknown fields")
    if values.get("contract") != DECISION_CONTRACT:
        raise ValueError("source-local decision contract mismatch")
    if values.get("source_id") != source_id:
        raise ValueError("source-local decision source_id mismatch")
    if values.get("work_id") != work_id:
        raise ValueError("source-local decision work_id mismatch")
    if values.get("source_manifest_path") != manifest_path:
        raise ValueError("source-local decision source manifest path mismatch")
    if values.get("source_manifest_sha256") != manifest_sha256:
        raise ValueError("source-local decision source manifest digest is stale")
    if disposition not in DECISION_DISPOSITIONS:
        raise ValueError("source-local decision disposition is not supported")
    _validate_decider(values.get("decided_by"), blocked=disposition == "blocked")
    _validate_decided_at(values.get("decided_at"))
    if disposition == "blocked":
        values["blocker"] = _validate_blocker(values.get("blocker"), repository_root)
        return values
    observed_candidate = _digest(values.get("candidate_sha256"), "candidate_sha256")
    observed_validation = _digest(values.get("validation_sha256"), "validation_sha256")
    if candidate_sha256 is not None and observed_candidate != _digest(
        candidate_sha256, "candidate_sha256"
    ):
        raise ValueError("source-local decision candidate digest mismatch")
    if validation_sha256 is not None and observed_validation != _digest(
        validation_sha256, "validation_sha256"
    ):
        raise ValueError("source-local decision validation digest mismatch")
    _nonempty(values.get("rationale"), "rationale")
    return values


def validate_decision(
    record: Mapping[str, object],
    source_manifest: SourceManifest,
    *,
    source_id: str | None = None,
    work_id: str | None = None,
    candidate_sha256: str | None = None,
    validation_sha256: str | None = None,
) -> dict[str, object]:
    """Validate one decision against current source and optional evidence digests."""

    source_manifest.verify()
    resolved_source_id, resolved_work_id = _resolved_identity(
        source_manifest, source_id=source_id, work_id=work_id
    )
    return _validate_bound_record(
        record,
        repository_root=source_manifest.repository_root,
        source_id=resolved_source_id,
        work_id=resolved_work_id,
        manifest_path=source_manifest.path.relative_to(
            source_manifest.repository_root
        ).as_posix(),
        manifest_sha256=source_manifest.sha256,
        candidate_sha256=candidate_sha256,
        validation_sha256=validation_sha256,
    )


def decision_record(
    source_manifest: SourceManifest,
    review: ReviewView | None = None,
    *,
    work_id: str | None = None,
    disposition: str,
    rationale: str,
    decided_by: str,
    decided_at: str,
    source_id: str | None = None,
) -> dict[str, object]:
    """Build a decision from one independently verified current review."""

    if disposition not in CANDIDATE_DECISION_DISPOSITIONS:
        raise ValueError("source-local candidate decision disposition is not supported")
    source_manifest.verify()
    resolved_source_id, resolved_work_id = _resolved_identity(
        source_manifest, source_id=source_id, work_id=work_id
    )
    if review is None or not isinstance(review, ReviewView):
        raise ValueError("source-local decision requires a verified review")
    if (
        review.source_manifest.path.resolve() != source_manifest.path.resolve()
        or review.source_manifest.sha256 != source_manifest.sha256
    ):
        raise ValueError(
            "source-local decision review is bound to a different source manifest"
        )
    _verify_candidate_bindings(source_manifest, review.candidate)
    verified_review = prepare_review(
        source_manifest, review.candidate, review.validation
    )
    record = {
        "contract": DECISION_CONTRACT,
        "source_id": resolved_source_id,
        "work_id": resolved_work_id,
        "source_manifest_path": source_manifest.path.relative_to(
            source_manifest.repository_root
        ).as_posix(),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": verified_review.candidate_sha256,
        "validation_sha256": verified_review.validation.sha256,
        "disposition": disposition,
        "rationale": rationale,
        "decided_by": decided_by,
        "decided_at": decided_at,
    }
    return validate_decision(
        record,
        source_manifest,
        source_id=resolved_source_id,
        work_id=resolved_work_id,
    )


def blocker_record(
    manifest_path: str | Path,
    *,
    repository_root: str | Path,
    source_id: str,
    work_id: str,
    blocker: Mapping[str, object],
    decided_by: str,
    decided_at: str,
) -> dict[str, object]:
    """Build an evidence-backed technical blocker without requiring viable source bytes."""

    _, content, relative_path, resolved_source_id, resolved_work_id = (
        _raw_manifest_identity(
            manifest_path,
            repository_root,
            source_id=source_id,
            work_id=work_id,
        )
    )
    record = {
        "contract": DECISION_CONTRACT,
        "source_id": resolved_source_id,
        "work_id": resolved_work_id,
        "source_manifest_path": relative_path,
        "source_manifest_sha256": _sha(content),
        "disposition": "blocked",
        "blocker": dict(_jsonable(blocker)),
        "decided_by": decided_by,
        "decided_at": decided_at,
    }
    return _validate_bound_record(
        record,
        repository_root=Path(repository_root).resolve(strict=True),
        source_id=resolved_source_id,
        work_id=resolved_work_id,
        manifest_path=relative_path,
        manifest_sha256=_sha(content),
    )


def serialize_decision(record: Mapping[str, object]) -> bytes:
    """Serialize an already validated decision deterministically with LF."""

    if frozenset(record) not in {_CANDIDATE_DECISION_KEYS, _BLOCKED_DECISION_KEYS}:
        raise ValueError("source-local decision contract has missing or unknown fields")
    return _canonical(record)


def load_decision(
    path: str | Path,
    source_manifest: SourceManifest,
    *,
    source_id: str | None = None,
    work_id: str | None = None,
) -> dict[str, object]:
    """Read and validate an existing source-local decision without writing."""

    resolved_source_id, resolved_work_id = _resolved_identity(
        source_manifest, source_id=source_id, work_id=work_id
    )
    requested = Path(path).resolve(strict=False)
    expected = decision_path(
        source_manifest.path,
        source_id=resolved_source_id,
        work_id=resolved_work_id,
    ).resolve(strict=False)
    if requested != expected:
        raise ValueError(
            "source-local decision path is not the source-local decision path"
        )
    if not requested.is_file():
        raise FileNotFoundError(requested)
    return validate_decision(
        _strict_json(requested.read_bytes(), "source-local decision"),
        source_manifest,
        source_id=resolved_source_id,
        work_id=resolved_work_id,
    )


def load_blocked_decision(
    path: str | Path,
    manifest_path: str | Path,
    *,
    repository_root: str | Path,
    source_id: str,
    work_id: str,
) -> dict[str, object]:
    """Read a technical blocker bound to exact manifest and retained evidence bytes."""

    manifest, content, relative_path, resolved_source_id, resolved_work_id = (
        _raw_manifest_identity(
            manifest_path,
            repository_root,
            source_id=source_id,
            work_id=work_id,
        )
    )
    requested = Path(path).resolve(strict=False)
    expected = decision_path(
        manifest, source_id=resolved_source_id, work_id=resolved_work_id
    ).resolve(strict=False)
    if requested != expected:
        raise ValueError(
            "source-local decision path is not the source-local decision path"
        )
    if not requested.is_file():
        raise FileNotFoundError(requested)
    record = _strict_json(requested.read_bytes(), "source-local decision")
    if record.get("disposition") != "blocked":
        raise ValueError("source-local decision is not a blocked disposition")
    return _validate_bound_record(
        record,
        repository_root=Path(repository_root).resolve(strict=True),
        source_id=resolved_source_id,
        work_id=resolved_work_id,
        manifest_path=relative_path,
        manifest_sha256=_sha(content),
    )


def _load_bound_validator(source_manifest: SourceManifest) -> object:
    binding = source_manifest.record.get("validator")
    if not isinstance(binding, Mapping):
        raise ValueError("source manifest validator binding is invalid")
    implementation_path = binding.get("implementation_path")
    if not isinstance(implementation_path, str) or not implementation_path:
        raise ValueError("source manifest validator implementation path is invalid")
    lexical = Path(implementation_path)
    if lexical.is_absolute() or ".." in lexical.parts:
        raise ValueError("source manifest validator implementation path is invalid")
    path = (source_manifest.repository_root / lexical).resolve(strict=True)
    implementation_sha256 = _digest(
        binding.get("implementation_sha256"), "validator implementation_sha256"
    )
    if _sha(path.read_bytes()) != implementation_sha256:
        raise ValueError("validator implementation is stale")
    callable_name = binding.get("callable")
    if not isinstance(callable_name, str) or not callable_name.isidentifier():
        raise ValueError("source manifest validator callable binding is invalid")
    module_name = f"_ocd_catalog_bound_validator_{implementation_sha256}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError("validator implementation cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    previous_path = list(sys.path)
    sys.path.insert(0, str(source_manifest.repository_root))
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise ValueError("validator implementation could not be loaded") from exc
    finally:
        sys.path[:] = previous_path
    loaded_file = getattr(module, "__file__", None)
    if loaded_file is None or not Path(loaded_file).resolve(strict=True).samefile(path):
        raise ValueError("validator loaded from a shadow path")
    value = getattr(module, callable_name, None)
    if not callable(value):
        raise ValueError("validator callable is absent")
    source = inspect.getsourcefile(value)
    if source is None or not Path(source).resolve(strict=True).samefile(path):
        raise ValueError("validator callable is imported or shadowed")
    if getattr(value, "__module__", None) != module_name:
        raise ValueError("validator callable does not belong to its bound module")
    return value


def _verify_candidate_bindings(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> None:
    """Require candidate metadata to remain bound to the selected source."""

    if candidate.manifest.get("status") != "nonaccepted":
        raise ValueError("candidate manifest status must remain nonaccepted")
    source_binding = candidate.manifest.get("source_manifest")
    expected_path = source_manifest.path.relative_to(
        source_manifest.repository_root
    ).as_posix()
    if not isinstance(source_binding, Mapping) or (
        source_binding.get("path") != expected_path
        or source_binding.get("sha256") != source_manifest.sha256
    ):
        raise ValueError("candidate source-manifest binding mismatch")
    if candidate.manifest.get("source_id") != source_manifest.record.get("source_id"):
        raise ValueError("candidate source identity binding mismatch")
    source_converter = source_manifest.record.get("converter")
    candidate_converter = candidate.manifest.get("converter")
    if (
        not isinstance(source_converter, Mapping)
        or not isinstance(candidate_converter, Mapping)
        or dict(candidate_converter) != dict(source_converter)
    ):
        raise ValueError("candidate converter binding mismatch")
    source_schema = source_manifest.record.get("package_schema")
    candidate_schema = candidate.manifest.get("package_schema")
    if (
        not isinstance(source_schema, Mapping)
        or not isinstance(candidate_schema, Mapping)
        or dict(candidate_schema) != dict(source_schema)
    ):
        raise ValueError("candidate package schema binding mismatch")


def _load_validation_report(
    path: str | Path,
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
) -> ValidationReport:
    value = _strict_json(Path(path).read_bytes(), "validation report")
    required = _VALIDATION_REPORT_KEYS | {"report_sha256"}
    if set(value) not in (required, required | {"text_quality_sha256"}):
        raise ValueError("validation report has missing or unknown fields")
    verify_text_quality(Path(path).with_name("text-quality.json"), value.get("text_quality_sha256"), source_manifest, candidate)
    report_sha256 = _digest(value.get("report_sha256"), "report_sha256")
    report_record = {key: value[key] for key in _VALIDATION_REPORT_KEYS}
    if _sha(_canonical(report_record)) != report_sha256:
        raise ValueError("validation report digest is stale")
    if value.get("contract") != "ocd-validation-report-v1":
        raise ValueError("validation report contract mismatch")
    if value.get("status") != "pass":
        raise ValueError("validation report is not a passing report")
    if value.get("candidate_sha256") != candidate.sha256:
        raise ValueError("validation report candidate digest mismatch")
    if value.get("source_manifest_sha256") != source_manifest.sha256:
        raise ValueError("validation report source-manifest digest mismatch")
    attestation = value.get("attestation")
    findings = value.get("findings")
    if not isinstance(attestation, Mapping) or not isinstance(findings, list):
        raise ValueError("validation report evidence shape is invalid")
    if any(not isinstance(item, str) for item in findings):
        raise ValueError("validation report findings are invalid")
    return ValidationReport(
        status="pass",
        candidate_sha256=candidate.sha256,
        source_manifest_sha256=source_manifest.sha256,
        attestation=attestation,
        findings=tuple(findings),
        sha256=report_sha256,
    )


def load_verified_review(
    source_manifest: SourceManifest,
    *,
    candidate_path: str | Path,
    validation_path: str | Path,
) -> ReviewView:
    """Load candidate/report paths and reverify them with the bound oracle."""

    source_manifest.verify()
    try:
        candidate = CandidatePackage.load(candidate_path)
        supplied = _load_validation_report(validation_path, source_manifest, candidate)
    except OSError as exc:
        raise ValueError("candidate or validation evidence is unavailable") from exc
    _verify_candidate_bindings(source_manifest, candidate)
    validator = _load_bound_validator(source_manifest)
    current = validate_candidate(source_manifest, candidate, validator)
    if (
        supplied.status != current.status
        or supplied.candidate_sha256 != current.candidate_sha256
        or supplied.source_manifest_sha256 != current.source_manifest_sha256
        or _jsonable(supplied.attestation) != _jsonable(current.attestation)
        or supplied.findings != current.findings
        or supplied.sha256 != current.sha256
    ):
        raise ValueError("validation evidence is stale or fabricated")
    return prepare_review(source_manifest, candidate, current)


def catalog_decision(
    manifest_path: str | Path,
    *,
    repository_root: str | Path,
    source_id: str | None = None,
    work_id: str | None = None,
    candidate_path: str | Path | None = None,
    validation_path: str | Path | None = None,
) -> dict[str, object] | None:
    """Load one existing decision only after revalidating current evidence."""

    raw_path, _, _, resolved_source_id, resolved_work_id = _raw_manifest_identity(
        manifest_path,
        repository_root,
        source_id=source_id,
        work_id=work_id,
    )
    path = decision_path(
        raw_path, source_id=resolved_source_id, work_id=resolved_work_id
    )
    if not path.exists():
        return None
    raw_decision = _strict_json(path.read_bytes(), "source-local decision")
    if raw_decision.get("disposition") == "blocked":
        record = load_blocked_decision(
            path,
            raw_path,
            repository_root=repository_root,
            source_id=resolved_source_id,
            work_id=resolved_work_id,
        )
        return {
            "path": path.relative_to(
                Path(repository_root).resolve(strict=True)
            ).as_posix(),
            "sha256": _sha(path.read_bytes()),
            "disposition": "blocked",
            "blocker": record["blocker"],
        }
    if candidate_path is None or validation_path is None:
        raise ValueError(
            "explicit candidate and validation evidence paths are required for a source-local decision"
        )
    manifest = SourceManifest.load(raw_path, repository_root=repository_root)
    review = load_verified_review(
        manifest,
        candidate_path=candidate_path,
        validation_path=validation_path,
    )
    record = load_decision(
        path,
        manifest,
        source_id=resolved_source_id,
        work_id=resolved_work_id,
    )
    record = validate_decision(
        record,
        manifest,
        source_id=resolved_source_id,
        work_id=resolved_work_id,
        candidate_sha256=review.candidate_sha256,
        validation_sha256=review.validation.sha256,
    )
    return {
        "path": path.relative_to(manifest.repository_root).as_posix(),
        "sha256": _sha(path.read_bytes()),
        "candidate_sha256": review.candidate_sha256,
        "validation_sha256": review.validation.sha256,
        "disposition": record["disposition"],
    }


__all__ = [
    "BLOCKER_KINDS",
    "CANDIDATE_DECISION_DISPOSITIONS",
    "DECISION_CONTRACT",
    "DECISION_DISPOSITIONS",
    "blocker_record",
    "catalog_decision",
    "decision_path",
    "decision_record",
    "load_blocked_decision",
    "load_decision",
    "load_verified_review",
    "serialize_decision",
    "validate_decision",
]
