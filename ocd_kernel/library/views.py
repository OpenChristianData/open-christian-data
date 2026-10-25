"""Deterministic generated views over the local library authority tree.

The views are projections only. Stable identity, acquisition, state,
acceptance, and assessment sidecars remain authoritative in their own files;
this module reports their relationships and current byte evidence without
repairing any of them.
"""

from __future__ import annotations

from .record_read import RecordRead, normalize_diagnostic

from ocd_kernel.lib.path_io import io_path, resolve_path, io_glob, io_rglob, io_iterdir

import copy
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Mapping

from ocd_kernel.lib.storage_topology import (
    StorageTopologyError,
    repository_relative_path,
    resolve_repo_path,
)

from ._common import PipelineError, canonical_bytes, load_json, sha256_bytes, sha256_file, write_json
from .acquisitions import (
    load_acquisition,
    load_acquisition_leads,
    source_sha256,
    validate_acquisition,
)
from .assessment import load_agent_assessment, load_human_review
from .identities import Work, discover_library, discover_work, load_work, schema_enum, resolve_edition_language
from .state import load_state, validate_state
from ocd_kernel.tei.acceptance import _validate_acceptance_for_views, load_acceptance


VIEW_VERSION = "ocd-library-views-v2"
SCHEMA_VERSION = "2.0"
_STATUS_NAMES = ("included", "warned", "failed", "excluded")
_TECHNICAL_PROOFS = (
    "validation",
    "accounting",
    "fidelity",
    "reproducibility",
    "schema",
    "closure",
)
_AUTHORITY_JSON_NAMES = {"work.json", "state.json", "acceptance.json"}
_ASSESSMENT_PARENT_NAMES = {"assessments", "reviews"}


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _logical_path(root: Path, path: Path) -> str:
    """Return a portable repository-relative path without resolving junctions."""

    root = Path(root).absolute()
    path = Path(path)
    try:
        return path.absolute().relative_to(root).as_posix()
    except ValueError:
        try:
            return repository_relative_path(root, path)
        except StorageTopologyError as exc:
            raise PipelineError(f"path is outside configured storage: {path}") from exc


def _relative(root: Path, path: Path) -> str:
    """Backward-compatible path helper used by generated rows."""

    return _logical_path(Path(root), Path(path))




class _Collector:
    """Collect deterministic issues and authority input bindings."""

    def __init__(self, root: Path) -> None:
        self.root = resolve_path(Path(root))
        self.issues: list[dict[str, Any]] = []
        self._inputs: dict[tuple[str, str], dict[str, Any]] = {}

    def issue(
        self,
        code: str,
        path: str,
        message: str,
        *,
        severity: str = "error",
    ) -> None:
        self.issues.append(
            {
                "code": code,
                "path": path,
                "severity": severity,
                "message": normalize_diagnostic(self.root, message),
            }
        )

    def input_reference(
        self,
        reference: str,
        *,
        role: str,
        expected_bytes: int | None = None,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Record a logical repository reference and its current byte facts."""

        logical = str(reference).replace("\\", "/")
        key = (logical, role)
        try:
            physical = resolve_repo_path(self.root, logical)
        except StorageTopologyError as exc:
            binding = {
                "path": logical,
                "role": role,
                "exists": False,
                "error": normalize_diagnostic(self.root, exc),
            }
            self.issue("invalid-input-path", logical, str(exc))
        else:
            if io_path(physical).is_file():
                try:
                    binding = {
                        "path": logical,
                        "role": role,
                        "exists": True,
                        "bytes": io_path(physical).stat().st_size,
                        "sha256": sha256_file(physical),
                    }
                except OSError as exc:
                    binding = {
                        "path": logical,
                        "role": role,
                        "exists": False,
                        "error": normalize_diagnostic(self.root, exc),
                    }
                    self.issue("unreadable-input", logical, str(exc))
            else:
                binding = {
                    "path": logical,
                    "role": role,
                    "exists": False,
                }
                self.issue("missing-input", logical, f"authority input is missing: {logical}")
        if expected_bytes is not None:
            binding["declared_bytes"] = expected_bytes
        if expected_sha256 is not None:
            binding["declared_sha256"] = expected_sha256
        self._inputs[key] = binding
        return binding

    def input_path(
        self,
        path: Path,
        *,
        role: str,
        expected_bytes: int | None = None,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        return self.input_reference(
            _logical_path(self.root, Path(path)),
            role=role,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
        )

    def input_bindings(self) -> list[dict[str, Any]]:
        return [
            _copy(self._inputs[key])
            for key in sorted(self._inputs, key=lambda value: (value[0], value[1]))
        ]

    def sorted_issues(self) -> list[dict[str, Any]]:
        return sorted(
            (_copy(issue) for issue in self.issues),
            key=lambda issue: (issue["path"], issue["code"], issue["message"]),
        )


def _json_or_none(path: Path) -> dict[str, Any] | None:
    try:
        return load_json(path)
    except PipelineError:
        return None


def _relative_input_for_record(
    collector: _Collector,
    record: Mapping[str, Any],
    *,
    field: str,
    role: str,
) -> None:
    """Add a file binding from an acceptance or assessment record."""

    value = record.get(field)
    if not isinstance(value, Mapping):
        return
    path = value.get("path")
    if not isinstance(path, str):
        return
    collector.input_reference(
        path,
        role=role,
        expected_bytes=value.get("bytes") if isinstance(value.get("bytes"), int) else None,
        expected_sha256=value.get("sha256") if isinstance(value.get("sha256"), str) else None,
    )


def _acceptance_input_bindings(collector: _Collector, record: Mapping[str, Any]) -> None:
    source = record.get("source")
    if isinstance(source, Mapping):
        _relative_input_for_record(collector, source, field="source_manifest", role="acceptance-source-manifest")
        _relative_input_for_record(collector, source, field="accounting", role="acceptance-source-accounting")
        source_path = source.get("source_path")
        if isinstance(source_path, str):
            # ``source_path`` may identify an upstream source that is not a
            # retained local file. The sidecar itself remains the authority;
            # only an existing local binding participates in freshness.
            try:
                source_candidate = resolve_repo_path(collector.root, source_path)
            except StorageTopologyError:
                source_candidate = None
            if source_candidate is not None and io_path(source_candidate).is_file():
                collector.input_reference(
                    source_path,
                    role="acceptance-source",
                    expected_bytes=source.get("source_bytes") if isinstance(source.get("source_bytes"), int) else None,
                    expected_sha256=source.get("source_sha256") if isinstance(source.get("source_sha256"), str) else None,
                )
    technical = record.get("technical")
    if isinstance(technical, Mapping):
        for name in ("candidate", *_TECHNICAL_PROOFS):
            _relative_input_for_record(
                collector,
                technical,
                field=name,
                role=f"acceptance-technical-{name}",
            )
        for name in ("producer", "checker"):
            actor = technical.get(name)
            if isinstance(actor, Mapping):
                _relative_input_for_record(
                    collector,
                    actor,
                    field="path",
                    role=f"acceptance-actor-{name}",
                )
    review = record.get("review")
    if isinstance(review, Mapping):
        _relative_input_for_record(collector, review, field="report", role="acceptance-review")
    promotion = record.get("promotion")
    if isinstance(promotion, Mapping):
        _relative_input_for_record(collector, promotion, field="master", role="acceptance-promotion-master")
        state_path = promotion.get("state_path")
        if isinstance(state_path, str):
            collector.input_reference(state_path, role="acceptance-promotion-state")
    decision = record.get("decision")
    if isinstance(decision, Mapping):
        blockers = decision.get("blockers")
        if isinstance(blockers, list):
            for index, blocker in enumerate(blockers):
                if not isinstance(blocker, Mapping):
                    continue
                evidence = blocker.get("evidence")
                if not isinstance(evidence, list):
                    continue
                for evidence_index, reference in enumerate(evidence):
                    if isinstance(reference, Mapping) and isinstance(reference.get("path"), str):
                        collector.input_reference(
                            reference["path"],
                            role=f"acceptance-blocker-{index}-{evidence_index}",
                            expected_bytes=reference.get("bytes") if isinstance(reference.get("bytes"), int) else None,
                            expected_sha256=reference.get("sha256") if isinstance(reference.get("sha256"), str) else None,
                        )


def _assessment_summary(
    record: Mapping[str, Any], *, kind: str, path: Path, root: Path
) -> dict[str, Any]:
    identifier = record["assessment_id"] if kind == "agent" else record["review_id"]
    result_key = "outcome" if kind == "agent" else "result"
    result: dict[str, Any] = {
        "record_path": _relative(root, path),
        "record_sha256": sha256_file(path),
        "record_id": identifier,
        "coverage": _copy(record["coverage"]),
        "result": record[result_key],
        "summary": record["summary"],
        "uncertainties": sorted(record["uncertainties"]),
        "issues": sorted(
            (_copy(item) for item in record["issues"]),
            key=lambda item: (item["severity"], item["issue_id"]),
        ),
    }
    if kind == "agent":
        result["assessment_id"] = record["assessment_id"]
        result["assessed_at"] = record["assessed_at"]
        result["agent"] = _copy(record["agent"])
    else:
        result["review_id"] = record["review_id"]
        result["reviewed_at"] = record["reviewed_at"]
        result["reviewer"] = record["reviewer"]
        result["decision_area"] = list(record["decision_area"])
        result["record_origin"] = record["record_origin"]
        result["synthetic"] = record["synthetic"]
    return result


def _assessment_candidates(root: Path) -> list[tuple[str, Path]]:
    """Find PIPE-016 records in their declared fixture/library locations."""

    candidates: dict[Path, str] = {}
    roots = [Path(root) / "assessments", Path(root) / "reviews", Path(root) / "library"]
    for base in roots:
        if not io_path(base).is_dir():
            continue
        for path in sorted(io_rglob(base, "*.json"), key=lambda item: item.as_posix()):
            if path.name in _AUTHORITY_JSON_NAMES:
                continue
            lower_parts = {part.lower() for part in path.parts}
            stem = path.stem.lower()
            if "agent-assessment" in stem or "agent-assessment" in lower_parts:
                candidates[path] = "agent"
            elif "human-review" in stem or "human-review" in lower_parts:
                candidates[path] = "human"
            elif path.parent.name.lower() in _ASSESSMENT_PARENT_NAMES:
                candidates[path] = "agent" if path.parent.name.lower() == "assessments" else "human"
    return sorted(
        ((kind, path) for path, kind in candidates.items()),
        key=lambda item: item[1].as_posix(),
    )


def _acceptance_dimensions(
    record: Mapping[str, Any], *, source_availability: str
) -> dict[str, Any]:
    source = record["source"]
    scope = record["scope"]
    technical = record["technical"]
    review = record["review"]
    decision = record["decision"]
    expected = list(scope["expected_members"])
    included = list(scope["included_members"])
    excluded = list(scope["excluded_members"])
    missing = list(source["missing_members"])
    unknown = list(source["unknown_members"])
    proof_statuses = {name: technical[name]["status"] for name in _TECHNICAL_PROOFS}
    technical_closure = "pass" if all(status == "pass" for status in proof_statuses.values()) else "partial"
    if any(status == "fail" for status in proof_statuses.values()):
        technical_closure = "fail"
    member_status = "complete" if not missing and not unknown and len(included) + len(excluded) == len(expected) else "partial"
    return {
        "source_availability": source_availability,
        "member_completeness": {
            "status": member_status,
            "expected": len(expected),
            "included": len(included),
            "excluded": len(excluded),
            "missing": sorted(missing),
            "unknown": sorted(unknown),
        },
        "fidelity": proof_statuses["fidelity"],
        "technical_closure": {
            "status": technical_closure,
            "proofs": proof_statuses,
        },
        "source_quality": _copy(review["source_quality_uncertainty"]),
        "visual_coverage": review["coverage"]["status"],
        "agent_assessment": decision["agent_assessment"]["status"],
        "human_acceptance": decision["human_decision"]["status"],
    }


def _empty_dimensions(source_availability: str) -> dict[str, Any]:
    return {
        "source_availability": source_availability,
        "member_completeness": "not-recorded",
        "fidelity": "not-recorded",
        "technical_closure": "not-recorded",
        "source_quality": "not-recorded",
        "visual_coverage": "not-recorded",
        "agent_assessment": "not-recorded",
        "human_acceptance": "not-recorded",
    }


def _state_target_key(work_id: str, target_id: str) -> tuple[str, str]:
    return work_id, target_id


def _build_snapshot(root: Path) -> dict[str, Any]:
    root = resolve_path(Path(root))
    works_root = root / "library" / "works"
    if not io_path(works_root).is_dir():
        raise PipelineError(f"missing library work root: {works_root}")

    collector = _Collector(root)
    research_leads: list[dict[str, Any]] = []
    research_manifest_path = root / "research" / "MANIFEST.md"
    research_queue_path = root / "library" / "acquisition-leads.jsonl"
    research_status = "not-present"
    if io_path(research_manifest_path).is_file() or io_path(research_queue_path).is_file():
        research_status = "invalid"
        collector.input_path(research_manifest_path, role="research-manifest")
        collector.input_path(research_queue_path, role="research-leads")
        if io_path(research_manifest_path).is_file() and io_path(research_queue_path).is_file():
            try:
                loaded_leads = load_acquisition_leads(research_queue_path, root=root)
            except PipelineError as exc:
                collector.issue("invalid-research-leads", _relative(root, research_queue_path), str(exc))
            else:
                research_status = "valid"
                bound_migrations: set[str] = set()
                for lead in loaded_leads:
                    if "migration_id" in lead and lead["migration_id"] not in bound_migrations:
                        from .research_leads import migration_path
                        reference = migration_path(lead["migration_id"])
                        collector.input_reference(reference, role="research-lead-migration")
                        migration = load_json(resolve_repo_path(root, reference))
                        for name in ("queue_before", "claims_before", "manifest_current"):
                            binding = migration[name]
                            collector.input_reference(binding["path"], role="research-lead-migration-witness", expected_sha256=binding["sha256"])
                        bound_migrations.add(lead["migration_id"])
                    evidence = lead.get("evidence")
                    if isinstance(evidence, Mapping) and isinstance(evidence.get("path"), str):
                        collector.input_reference(
                            evidence["path"],
                            role="research-lead-evidence",
                            expected_sha256=evidence.get("sha256") if isinstance(evidence.get("sha256"), str) else None,
                        )
                    from .cataloging import load_note
                    note = load_note(root, lead)
                    entry = _copy(lead)
                    if note is not None:
                        collector.input_reference(note['path'], role='lead-cataloging', expected_sha256=note['sha256'])
                        for source in note['evidence']['sources']:
                            collector.input_reference(source['path'], role='lead-cataloging-evidence', expected_sha256=source['sha256'])
                        entry['cataloging'] = note
                    research_leads.append(entry)
        else:
            collector.issue(
                "incomplete-research-leads",
                _relative(root, research_manifest_path if not io_path(research_manifest_path).is_file() else research_queue_path),
                "research manifest and acquisition-leads queue must be present together",
            )
    works: list[dict[str, Any]] = []
    forms: list[dict[str, Any]] = []
    edition_meta: list[dict[str, Any]] = []
    work_by_id: dict[str, dict[str, Any]] = {}
    form_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    edition_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}

    work_dirs = sorted(
        (path for path in io_iterdir(works_root) if io_path(path).is_dir()),
        key=lambda path: path.name,
    )
    if not work_dirs:
        raise PipelineError(f"library contains no works: {works_root}")

    for work_dir in work_dirs:
        work_path = work_dir / "work.json"
        work_reference = _relative(root, work_path)
        collector.input_path(work_path, role="work-sidecar")
        raw_record = _json_or_none(work_path)
        record: dict[str, Any] | None = None
        if raw_record is None:
            collector.issue("invalid-work", work_reference, "work sidecar could not be loaded")
        else:
            try:
                record = load_work(work_path)
            except PipelineError as exc:
                collector.issue("invalid-work", work_reference, str(exc))
        work_id = record.get("work_id") if isinstance(record, dict) else None
        if not isinstance(work_id, str) or not work_id:
            if isinstance(raw_record, dict) and isinstance(raw_record.get("work_id"), str):
                work_id = raw_record["work_id"]
            else:
                work_id = None
        title = record.get("title") if isinstance(record, dict) else None
        work_row: dict[str, Any] = {
            "work_id": work_id,
            "title": title,
            "work_path": work_reference,
            "identity_status": "valid" if record is not None else "invalid",
            "form_count": 0,
            "edition_count": 0,
            "issues": [],
        }
        if isinstance(work_id, str):
            prior = work_by_id.get(work_id)
            if prior is not None:
                collector.issue(
                    "work-id-collision",
                    work_reference,
                    f"work_id {work_id!r} is also declared by {prior['work_path']}",
                )
                work_row["identity_status"] = "collision"
            else:
                work_by_id[work_id] = work_row
        works.append(work_row)
        if record is None or not isinstance(work_id, str):
            continue
        if work_id != work_dir.name:
            collector.issue(
                "work-path-identity-mismatch",
                work_reference,
                f"work_id {work_id!r} does not match directory {work_dir.name!r}",
            )
            work_row["identity_status"] = "contradictory"
        raw_forms = record.get("textual_forms", [])
        if not isinstance(raw_forms, list):
            continue
        seen_forms: set[str] = set()
        for raw_form in raw_forms:
            if not isinstance(raw_form, dict) or not isinstance(raw_form.get("textual_form_id"), str):
                collector.issue("invalid-form", work_reference, "textual_forms contains an invalid entry")
                continue
            form_id = raw_form["textual_form_id"]
            form_key = (work_id, form_id)
            form_row: dict[str, Any] = {
                "work_id": work_id,
                "textual_form_id": form_id,
                "title": raw_form.get("title"),
                "language": raw_form.get("language"),
                "category": raw_form.get("category"),
                "form_path": _relative(root, work_dir / "forms" / form_id),
                "identity_status": "valid",
                "edition_count": 0,
                "issues": [],
            }
            if form_id in seen_forms or form_key in form_by_key:
                collector.issue("form-id-collision", work_reference, f"textual_form_id {form_id!r} is duplicated")
                form_row["identity_status"] = "collision"
            seen_forms.add(form_id)
            form_by_key[form_key] = form_row
            forms.append(form_row)
            work_row["form_count"] += 1
            raw_editions = raw_form.get("editions", [])
            if not isinstance(raw_editions, list):
                collector.issue("invalid-editions", work_reference, f"form {form_id!r} editions must be a list")
                continue
            for raw_edition in raw_editions:
                if not isinstance(raw_edition, dict) or not isinstance(raw_edition.get("edition_id"), str):
                    collector.issue("invalid-edition", work_reference, f"form {form_id!r} contains an invalid edition")
                    continue
                edition_id = raw_edition["edition_id"]
                edition_key = (work_id, form_id, edition_id)
                edition_row = {
                    "work_id": work_id,
                    "textual_form_id": form_id,
                    "edition_id": edition_id,
                    "edition_title": raw_edition.get("title"),
                    "edition_record": raw_edition,
                    "edition_path": _relative(root, work_dir / "forms" / form_id / "editions" / edition_id),
                    "master_path": _relative(root, work_dir / "forms" / form_id / "editions" / edition_id / "master.tei.xml"),
                    "declared_acquisition_ids": _copy(raw_edition.get("acquisition_ids")) if "acquisition_ids" in raw_edition else None,
                    "identity_status": "valid",
                }
                if edition_key in edition_by_key or any(
                    item["work_id"] == work_id and item["edition_id"] == edition_id
                    for item in edition_meta
                ):
                    collector.issue("edition-id-collision", edition_row["edition_path"], f"edition_id {edition_id!r} is duplicated")
                    edition_row["identity_status"] = "collision"
                edition_by_key[edition_key] = edition_row
                edition_meta.append(edition_row)
                form_row["edition_count"] += 1
                work_row["edition_count"] += 1

    acquisitions: list[dict[str, Any]] = []
    acquisitions_by_edition: dict[tuple[str, str], list[dict[str, Any]]] = {}
    acquisitions_by_id: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for work_dir in work_dirs:
        work_path = work_dir / "work.json"
        work_row = next(
            (item for item in works if item["work_path"] == _relative(root, work_path)),
            None,
        )
        work_id = work_row["work_id"] if work_row is not None else work_dir.name
        sidecars = sorted(
            io_glob(work_dir, "forms/*/editions/*/acquisitions/*.json"),
            key=lambda path: path.as_posix(),
        )
        for sidecar in sidecars:
            sidecar_reference = _relative(root, sidecar)
            collector.input_path(sidecar, role="acquisition-sidecar")
            parts = sidecar.relative_to(work_dir).parts
            form_id = parts[1] if len(parts) >= 6 else None
            edition_id = parts[3] if len(parts) >= 6 else None
            raw = _json_or_none(sidecar)
            record: dict[str, Any] | None = None
            evidence_status = "invalid"
            reasons: list[str] = []
            if raw is None:
                reasons.append("acquisition sidecar could not be loaded")
            else:
                try:
                    record = load_acquisition(sidecar)
                except PipelineError as exc:
                    reasons.append(normalize_diagnostic(root, exc))
                else:
                    try:
                        record = validate_acquisition(sidecar, root=root)
                    except PipelineError as exc:
                        reasons.append(normalize_diagnostic(root, exc))
                    else:
                        evidence_status = "valid"
            value = record if record is not None else raw or {}
            acquisition_id = value.get("acquisition_id") if isinstance(value.get("acquisition_id"), str) else sidecar.stem
            retained_files = value.get("retained_files") if isinstance(value.get("retained_files"), list) else []
            for member in retained_files:
                if not isinstance(member, dict) or not isinstance(member.get("path"), str):
                    continue
                collector.input_reference(
                    member["path"],
                    role="retained-source",
                    expected_bytes=member.get("bytes") if isinstance(member.get("bytes"), int) else None,
                    expected_sha256=member.get("sha256") if isinstance(member.get("sha256"), str) else None,
                )
            source_hash = None
            try:
                source_hash = source_sha256(dict(value), context=sidecar_reference)
            except PipelineError:
                source_hash = value.get("source_sha256") if isinstance(value.get("source_sha256"), str) else None
            row: dict[str, Any] = {
                "work_id": work_id,
                "textual_form_id": form_id,
                "edition_id": edition_id,
                "acquisition_id": acquisition_id,
                "acquisition_path": sidecar_reference,
                "provider": value.get("provider"),
                "url": value.get("url"),
                "route": value.get("route"),
                "source_path": value.get("source_path"),
                "source_sha256": source_hash,
                "source_bytes": value.get("source_bytes"),
                "source_scope": value.get("source_scope"),
                "retained_files": _copy(retained_files),
                "warnings": _copy(value.get("warnings", [])),
                "identity_status": "valid",
                "collision_status": "none",
                "evidence_status": evidence_status,
                "source_availability": "available" if evidence_status == "valid" else "invalid",
                "reasons": reasons,
            }
            key = (str(work_id), str(edition_id))
            declared_edition = next(
                (
                    item
                    for item in edition_meta
                    if item["work_id"] == work_id
                    and item["textual_form_id"] == form_id
                    and item["edition_id"] == edition_id
                ),
                None,
            )
            if declared_edition is None:
                row["identity_status"] = "orphan"
                collector.issue("orphan-acquisition", sidecar_reference, "acquisition sidecar is below an undeclared form or edition")
            else:
                declared_ids = declared_edition["declared_acquisition_ids"]
                if isinstance(declared_ids, list) and acquisition_id not in declared_ids:
                    row["identity_status"] = "contradictory"
                    collector.issue("undeclared-acquisition", sidecar_reference, f"acquisition {acquisition_id!r} is absent from the edition declaration")
            if isinstance(value.get("edition_id"), str) and value["edition_id"] != edition_id:
                row["identity_status"] = "contradictory"
                collector.issue("acquisition-edition-mismatch", sidecar_reference, f"sidecar says edition {value['edition_id']!r}, directory says {edition_id!r}")
            if acquisition_id != sidecar.stem:
                row["identity_status"] = "contradictory"
                collector.issue("acquisition-filename-mismatch", sidecar_reference, f"sidecar says acquisition {acquisition_id!r}, filename says {sidecar.stem!r}")
            acquisitions.append(row)
            acquisitions_by_edition.setdefault(key, []).append(row)
            acquisitions_by_id.setdefault((str(work_id), str(acquisition_id)), []).append(row)

    for edition in edition_meta:
        declared_ids = edition["declared_acquisition_ids"]
        if not isinstance(declared_ids, list):
            continue
        existing = {
            row["acquisition_id"]
            for row in acquisitions_by_edition.get((edition["work_id"], edition["edition_id"]), [])
        }
        for acquisition_id in declared_ids:
            if acquisition_id in existing:
                continue
            missing_path = _relative(
                root,
                root
                / "library"
                / "works"
                / edition["work_id"]
                / "forms"
                / edition["textual_form_id"]
                / "editions"
                / edition["edition_id"]
                / "acquisitions"
                / f"{acquisition_id}.json",
            )
            collector.input_reference(missing_path, role="acquisition-sidecar")
            row = {
                "work_id": edition["work_id"],
                "textual_form_id": edition["textual_form_id"],
                "edition_id": edition["edition_id"],
                "acquisition_id": acquisition_id,
                "acquisition_path": missing_path,
                "provider": None,
                "url": None,
                "route": None,
                "source_path": None,
                "source_sha256": None,
                "source_bytes": None,
                "source_scope": None,
                "retained_files": [],
                "warnings": [],
                "identity_status": "declared-missing",
                "collision_status": "none",
                "evidence_status": "missing",
                "source_availability": "missing",
                "reasons": ["declared acquisition sidecar is missing"],
            }
            acquisitions.append(row)
            acquisitions_by_edition.setdefault((edition["work_id"], edition["edition_id"]), []).append(row)
            acquisitions_by_id.setdefault((edition["work_id"], acquisition_id), []).append(row)
            collector.issue("missing-acquisition", missing_path, f"declared acquisition sidecar is missing: {acquisition_id}")

    for key, rows in acquisitions_by_id.items():
        if len(rows) <= 1:
            continue
        for row in rows:
            # Keep an orphan/contradictory identity diagnosis intact.  The
            # repeated acquisition ID is a separate collision fact and must
            # not erase the path relationship that made the row orphaned.
            row["collision_status"] = "collision"
            if row["identity_status"] == "valid":
                row["identity_status"] = "collision"
        collector.issue(
            "acquisition-id-collision",
            rows[0]["acquisition_path"],
            f"acquisition_id {key[1]!r} occurs more than once below work {key[0]!r}",
        )

    states: list[dict[str, Any]] = []
    state_targets: list[dict[str, Any]] = []
    state_by_work: dict[str, dict[str, Any]] = {}
    state_targets_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for work_dir in work_dirs:
        work_path = work_dir / "work.json"
        work_row = next(
            (item for item in works if item["work_path"] == _relative(root, work_path)),
            None,
        )
        work_id = work_row["work_id"] if work_row is not None else work_dir.name
        state_path = work_dir / "state.json"
        state_reference = _relative(root, state_path)
        collector.input_path(state_path, role="state-sidecar")
        raw = _json_or_none(state_path)
        if raw is None:
            state_row = {
                "work_id": work_id,
                "state_path": state_reference,
                "status": "missing",
                "target_count": 0,
                "reasons": ["state sidecar is missing"],
            }
            states.append(state_row)
            state_by_work[str(work_id)] = state_row
            if io_path(state_path).exists():
                collector.issue("invalid-state", state_reference, "state sidecar could not be loaded")
            continue
        state_record: dict[str, Any] | None = None
        state_status = "invalid"
        state_reasons: list[str] = []
        try:
            state_record = load_state(state_path)
        except PipelineError as exc:
            state_reasons.append(normalize_diagnostic(root, exc))
        else:
            try:
                state_record = validate_state(state_path, root=root)
            except PipelineError as exc:
                state_reasons.append(normalize_diagnostic(root, exc))
            else:
                state_status = "valid"
        if state_record is None:
            state_record = raw
        if state_record.get("work_id") != work_id:
            state_reasons.append(f"state work_id {state_record.get('work_id')!r} does not match {work_id!r}")
            state_status = "invalid"
        targets = state_record.get("targets") if isinstance(state_record.get("targets"), list) else []
        state_row = {
            "work_id": work_id,
            "state_path": state_reference,
            "status": state_status,
            "target_count": len(targets),
            "reasons": sorted(set(state_reasons)),
        }
        states.append(state_row)
        state_by_work[str(work_id)] = state_row
        if state_status != "valid":
            for reason in state_reasons:
                collector.issue("invalid-state", state_reference, reason)
        for target in targets:
            if not isinstance(target, dict):
                collector.issue("invalid-state-target", state_reference, "state targets must be objects")
                continue
            target_id = target.get("target_id")
            if not isinstance(target_id, str):
                collector.issue("invalid-state-target", state_reference, "state target lacks target_id")
                continue
            target_row = {
                "work_id": work_id,
                "state_path": state_reference,
                "target_id": target_id,
                "target_type": target.get("target_type"),
                "stage": target.get("stage"),
                "updated_at": target.get("updated_at"),
                "reason": target.get("reason"),
                "evidence": _copy(target.get("evidence", [])),
                "status": state_status,
            }
            state_targets.append(target_row)
            state_targets_by_key.setdefault(_state_target_key(str(work_id), target_id), []).append(target_row)

    masters: list[dict[str, Any]] = []
    masters_by_edition: dict[tuple[str, str, str], dict[str, Any]] = {}
    for edition in edition_meta:
        master_path = root / edition["master_path"]
        exists = io_path(master_path).is_file()
        collector.input_path(master_path, role="accepted-master")
        master_row = {
            "work_id": edition["work_id"],
            "textual_form_id": edition["textual_form_id"],
            "edition_id": edition["edition_id"],
            "master_path": edition["master_path"],
            "exists": exists,
            "bytes": io_path(master_path).stat().st_size if exists else None,
            "sha256": sha256_file(master_path) if exists else None,
            "status": "present-unbound" if exists else "absent",
            "reasons": [] if exists else ["edition master is missing"],
        }
        masters.append(master_row)
        masters_by_edition[(edition["work_id"], edition["textual_form_id"], edition["edition_id"])] = master_row
    declared_master_paths = {item["master_path"] for item in masters}
    for master_path in sorted(
        io_glob(root / "library" / "works", "*/forms/*/editions/*/master.tei.xml"),
        key=lambda path: path.as_posix(),
    ):
        logical = _relative(root, master_path)
        if logical in declared_master_paths:
            continue
        collector.input_path(master_path, role="accepted-master")
        collector.issue("orphan-master", logical, "master file is below an undeclared form or edition")
        parts = master_path.relative_to(root / "library" / "works").parts
        masters.append(
            {
                "work_id": parts[0] if len(parts) >= 6 else None,
                "textual_form_id": parts[2] if len(parts) >= 6 else None,
                "edition_id": parts[4] if len(parts) >= 6 else None,
                "master_path": logical,
                "exists": True,
                "bytes": io_path(master_path).stat().st_size,
                "sha256": sha256_file(master_path),
                "status": "orphan",
                "reasons": ["master is not declared by work.json"],
            }
        )

    acceptances: list[dict[str, Any]] = []
    acceptance_by_edition: dict[tuple[str, str, str], dict[str, Any]] = {}
    declared_acceptance_references: set[str] = set()
    discovered_works: tuple[Work, ...] | None = None
    discovery_error: PipelineError | None = None
    discovery_attempted = False
    for edition in edition_meta:
        acceptance_path = root / edition["edition_path"] / "acceptance.json"
        acceptance_reference = _relative(root, acceptance_path)
        declared_acceptance_references.add(acceptance_reference)
        collector.input_path(acceptance_path, role="acceptance-sidecar")
        acceptance_exists = io_path(acceptance_path).is_file()
        record: dict[str, Any] | None = None
        valid = False
        reasons: list[str] = []
        if acceptance_exists:
            try:
                record = load_acceptance(acceptance_path)
            except PipelineError as exc:
                reasons.append(normalize_diagnostic(root, exc))
            else:
                _acceptance_input_bindings(collector, record)
                try:
                    if not discovery_attempted:
                        discovery_attempted = True
                        try:
                            discovered_works = discover_library(io_path(root))
                        except PipelineError as exc:
                            discovery_error = exc
                    if discovery_error is not None:
                        raise discovery_error
                    record = _validate_acceptance_for_views(
                        io_path(acceptance_path),
                        root=io_path(root),
                        discovered_works=discovered_works,
                    )
                except PipelineError as exc:
                    reasons.append(normalize_diagnostic(root, exc))
                else:
                    valid = True
        # A present but unreadable/malformed canonical sidecar is an invalid
        # acceptance record, even when no parsed record is available to carry
        # its promotion status.  ``not-recorded`` means the sidecar is absent.
        status = "invalid" if acceptance_exists else "not-recorded"
        promotion_status = None
        if record is not None:
            promotion = record.get("promotion")
            promotion_status = promotion.get("status") if isinstance(promotion, Mapping) else None
            status = "promoted" if valid and promotion_status == "promoted" else "pending" if valid else "invalid"
        acceptance_row: dict[str, Any] = {
            "work_id": edition["work_id"],
            "textual_form_id": edition["textual_form_id"],
            "edition_id": edition["edition_id"],
            "acceptance_path": acceptance_reference,
            "exists": acceptance_exists,
            "status": status,
            "promotion_status": promotion_status,
            "representation_revision": _copy(record.get("representation_revision")) if record else None,
            "technical": {
                name: record["technical"][name]["status"]
                for name in _TECHNICAL_PROOFS
            } if record and isinstance(record.get("technical"), Mapping) else {},
            "review_coverage": record["review"]["coverage"]["status"] if record and isinstance(record.get("review"), Mapping) else "not-recorded",
            "agent_decision": record["decision"]["agent_assessment"]["status"] if record and isinstance(record.get("decision"), Mapping) else "not-recorded",
            "human_decision": record["decision"]["human_decision"]["status"] if record and isinstance(record.get("decision"), Mapping) else "not-recorded",
            "dimensions": None,
            "record": _copy(record) if valid else None,
            "reasons": sorted(set(reasons)),
        }
        if valid and record is not None:
            acceptance_row["dimensions"] = _acceptance_dimensions(record, source_availability="available")
        else:
            acceptance_row["dimensions"] = _empty_dimensions("not-recorded")
        acceptances.append(acceptance_row)
        acceptance_by_edition[(edition["work_id"], edition["textual_form_id"], edition["edition_id"])] = acceptance_row
        for reason in reasons:
            collector.issue("invalid-acceptance", acceptance_reference, reason)

    scoped_pairs = set(io_glob(root / "library" / "works", "*/forms/*/editions/*/scopes/*/acceptance.json"))
    scoped_pairs.update(io_glob(root / "library" / "works", "*/forms/*/editions/*/scopes/*/master.tei.xml"))
    for scoped_dir in sorted({path.parent for path in scoped_pairs}, key=lambda path: path.as_posix()):
        relative = scoped_dir.relative_to(root / "library" / "works").parts
        work_id, form_id, edition_id, acquisition_id = relative[0], relative[2], relative[4], relative[6]
        edition = edition_by_key.get((work_id, form_id, edition_id))
        declared = (edition is not None and acquisition_id in (edition.get("declared_acquisition_ids") or []))
        master_path = scoped_dir / "master.tei.xml"
        acceptance_path = scoped_dir / "acceptance.json"
        for path, role in ((master_path, "accepted-master"), (acceptance_path, "acceptance-sidecar")):
            collector.input_path(path, role=role)
        reasons: list[str] = []
        record = None
        if not declared:
            reasons.append("scoped acceptance does not bind a declared acquisition")
        if not io_path(master_path).is_file() or not io_path(acceptance_path).is_file():
            reasons.append("scoped acceptance requires both master and acceptance files")
        if not reasons:
            try:
                if not discovery_attempted:
                    discovery_attempted = True
                    try:
                        discovered_works = discover_library(io_path(root))
                    except PipelineError as exc:
                        discovery_error = exc
                if discovery_error is not None:
                    raise discovery_error
                record = _validate_acceptance_for_views(
                    io_path(acceptance_path), root=io_path(root), discovered_works=discovered_works,
                )
                _acceptance_input_bindings(collector, record)
            except PipelineError as exc:
                reasons.append(normalize_diagnostic(root, exc))
        status = "invalid" if reasons else "promoted" if record["promotion"]["status"] == "promoted" else "pending"
        for reason in reasons:
            collector.issue("invalid-scoped-acceptance", _relative(root, scoped_dir), reason)
        masters.append({
            "work_id": work_id, "textual_form_id": form_id, "edition_id": edition_id,
            "acquisition_id": acquisition_id, "master_path": _relative(root, master_path),
            "exists": io_path(master_path).is_file(),
            "sha256": sha256_file(master_path) if io_path(master_path).is_file() else None,
            "status": "accepted" if status == "promoted" else "present-unbound" if io_path(master_path).is_file() else "absent",
            "reasons": reasons,
        })
        acceptances.append({
            "work_id": work_id, "textual_form_id": form_id, "edition_id": edition_id,
            "acquisition_id": acquisition_id, "acceptance_path": _relative(root, acceptance_path),
            "exists": io_path(acceptance_path).is_file(), "status": status,
            "promotion_status": record["promotion"]["status"] if record else None,
            "record": _copy(record) if record else None, "reasons": reasons,
        })

    # A sidecar below an undeclared form/edition is still an authority input
    # that must be visible in the inventory.  It cannot contribute acceptance
    # to a declared edition, so retain it as an orphan row and never infer a
    # promoted status from its contents.
    for orphan_path in sorted(
        io_glob(root / "library" / "works", "*/forms/*/editions/*/acceptance.json"),
        key=lambda path: path.as_posix(),
    ):
        orphan_reference = _relative(root, orphan_path)
        if orphan_reference in declared_acceptance_references:
            continue
        collector.input_path(orphan_path, role="acceptance-sidecar")
        try:
            parts = orphan_path.relative_to(works_root).parts
        except ValueError:
            parts = ()
        parsed_work_id = parts[0] if len(parts) >= 6 and parts[1] == "forms" else None
        parsed_form_id = parts[2] if len(parts) >= 6 and parts[3] == "editions" else None
        parsed_edition_id = parts[4] if len(parts) >= 6 else None
        raw = _json_or_none(orphan_path)
        record: dict[str, Any] | None = None
        reasons = ["acceptance sidecar is below an undeclared form or edition"]
        if raw is None:
            reasons.append("acceptance sidecar could not be loaded")
        else:
            try:
                record = load_acceptance(orphan_path)
            except PipelineError as exc:
                reasons.append(normalize_diagnostic(root, exc))
            else:
                _acceptance_input_bindings(collector, record)
        promotion = record.get("promotion") if isinstance(record, Mapping) else None
        promotion_status = promotion.get("status") if isinstance(promotion, Mapping) else None
        acceptances.append(
            {
                "work_id": parsed_work_id,
                "textual_form_id": parsed_form_id,
                "edition_id": parsed_edition_id,
                "acceptance_path": orphan_reference,
                "exists": True,
                "identity_status": "orphan",
                "status": "orphan",
                "promotion_status": promotion_status,
                "representation_revision": (
                    _copy(record.get("representation_revision"))
                    if record is not None
                    else None
                ),
                "technical": {
                    name: record["technical"][name]["status"]
                    for name in _TECHNICAL_PROOFS
                }
                if record and isinstance(record.get("technical"), Mapping)
                else {},
                "review_coverage": (
                    record["review"]["coverage"]["status"]
                    if record and isinstance(record.get("review"), Mapping)
                    else "not-recorded"
                ),
                "agent_decision": (
                    record["decision"]["agent_assessment"]["status"]
                    if record and isinstance(record.get("decision"), Mapping)
                    else "not-recorded"
                ),
                "human_decision": (
                    record["decision"]["human_decision"]["status"]
                    if record and isinstance(record.get("decision"), Mapping)
                    else "not-recorded"
                ),
                "dimensions": _empty_dimensions("not-recorded"),
                "record": None,
                "reasons": sorted(set(reasons)),
            }
        )
        for reason in sorted(set(reasons)):
            collector.issue("orphan-acceptance", orphan_reference, reason)

    assessment_rows: list[dict[str, Any]] = []
    assessments_by_edition: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = {}
    seen_assessment_ids: set[tuple[str, str]] = set()
    declared_work_editions = {
        (str(item["work_id"]), str(item["edition_id"])) for item in edition_meta
    }
    for kind, path in _assessment_candidates(root):
        reference = _relative(root, path)
        collector.input_path(path, role=f"{kind}-record")
        record: dict[str, Any] | None = None
        reasons: list[str] = []
        try:
            record = load_agent_assessment(path, root=root) if kind == "agent" else load_human_review(path, root=root)
        except PipelineError as exc:
            reasons.append(normalize_diagnostic(root, exc))
        if record is None:
            raw = _json_or_none(path)
            record = raw
            collector.issue(f"invalid-{kind}-assessment", reference, reasons[0] if reasons else "record could not be loaded")
        else:
            for artifact in record.get("artifacts", []):
                if isinstance(artifact, Mapping) and isinstance(artifact.get("path"), str):
                    collector.input_reference(
                        artifact["path"],
                        role=f"{kind}-artifact",
                        expected_sha256=artifact.get("sha256") if isinstance(artifact.get("sha256"), str) else None,
                    )
        if not isinstance(record, Mapping):
            continue
        work_id = record.get("work_id")
        edition_id = record.get("edition_id")
        identifier = record.get("assessment_id") if kind == "agent" else record.get("review_id")
        row: dict[str, Any] = {
            "kind": kind,
            "work_id": work_id,
            "edition_id": edition_id,
            "record_path": reference,
            "status": "valid" if not reasons else "invalid",
            "identity_status": "valid" if not reasons else "invalid",
            "record_id": identifier,
            "reasons": reasons,
        }
        if not reasons and isinstance(work_id, str) and isinstance(edition_id, str):
            row["record"] = _assessment_summary(record, kind=kind, path=path, root=root)
            key = (work_id, edition_id)
            if key not in declared_work_editions:
                row["status"] = "orphan"
                row["identity_status"] = "orphan"
                collector.issue(
                    "orphan-assessment",
                    reference,
                    f"{kind} record identifies an undeclared work or edition",
                )
            else:
                id_key = (kind, str(identifier))
                if id_key in seen_assessment_ids:
                    collector.issue("assessment-id-collision", reference, f"duplicate {kind} record identifier {identifier!r}")
                seen_assessment_ids.add(id_key)
                grouped = assessments_by_edition.setdefault(key, {"agent": [], "human": []})
                grouped[kind].append(row["record"])
        assessment_rows.append(row)
    for grouped in assessments_by_edition.values():
        grouped["agent"].sort(key=lambda item: item["record_id"])
        grouped["human"].sort(key=lambda item: item["record_id"])

    edition_entries: list[dict[str, Any]] = []
    for edition in edition_meta:
        key = (edition["work_id"], edition["textual_form_id"], edition["edition_id"])
        edition_acquisitions = acquisitions_by_edition.get((edition["work_id"], edition["edition_id"]), [])
        acceptance = acceptance_by_edition[key]
        selected_acquisition: dict[str, Any] | None = None
        bound_acquisition_id = None
        acceptance_record = acceptance.get("record")
        if isinstance(acceptance_record, Mapping):
            identity = acceptance_record.get("identity")
            if isinstance(identity, Mapping) and isinstance(identity.get("acquisition_id"), str):
                bound_acquisition_id = identity["acquisition_id"]
        matching_bound_acquisitions = [
            item
            for item in edition_acquisitions
            if item["acquisition_id"] == bound_acquisition_id
            and item["evidence_status"] == "valid"
            and item["identity_status"] == "valid"
        ]
        if len(matching_bound_acquisitions) == 1:
            # A valid PIPE-004 record names the source acquisition explicitly;
            # that binding resolves an otherwise ambiguous multi-acquisition
            # edition without guessing from directory order.
            selected_acquisition = matching_bound_acquisitions[0]
        elif len(edition_acquisitions) == 1:
            selected_acquisition = edition_acquisitions[0]
        elif isinstance(edition["declared_acquisition_ids"], list) and len(edition["declared_acquisition_ids"]) == 1:
            selected_acquisition = next(
                (
                    item
                    for item in edition_acquisitions
                    if item["acquisition_id"] == edition["declared_acquisition_ids"][0]
                ),
                None,
            )
        reasons: list[str] = []
        source_availability = "unacquired"
        if edition_acquisitions:
            if any(item["evidence_status"] == "valid" for item in edition_acquisitions):
                source_availability = "available"
            elif any(item["evidence_status"] == "missing" for item in edition_acquisitions):
                source_availability = "missing"
            else:
                source_availability = "invalid"
        if len(edition_acquisitions) > 1 and selected_acquisition is None:
            reasons.append("edition has multiple acquisition sidecars; no source was selected")
            if bound_acquisition_id is not None:
                reasons.append(
                    f"acceptance acquisition {bound_acquisition_id!r} does not identify one valid acquisition"
                )
        state_record = state_by_work.get(edition["work_id"])
        edition_targets = state_targets_by_key.get((edition["work_id"], edition["edition_id"]), [])
        edition_target = next((item for item in edition_targets if item["target_type"] == "edition"), None)
        acquisition_target = next(
            (
                target
                for item in edition_acquisitions
                for target in state_targets_by_key.get((edition["work_id"], item["acquisition_id"]), [])
                if target["target_type"] == "acquisition"
            ),
            None,
        )
        state_status = "missing" if state_record is None or state_record["status"] == "missing" else state_record["status"]
        if state_record is not None and state_record["status"] == "valid" and edition_target is None:
            state_status = "untracked"
        state_stage = edition_target["stage"] if edition_target else None
        master = masters_by_edition[key]
        if acceptance["status"] == "promoted" and master["exists"]:
            master["status"] = "accepted"
            master["reasons"] = []
        elif acceptance["status"] == "pending" and master["exists"]:
            master["status"] = "bound-pending"
        elif acceptance["status"] == "invalid" and master["exists"]:
            master["status"] = "present-unbound"
        grouped_assessments = assessments_by_edition.get(
            (edition["work_id"], edition["edition_id"]),
            {"agent": [], "human": []},
        )
        assessment_view = {
            "status": "recorded" if grouped_assessments["agent"] else "not-recorded",
            "records": _copy(grouped_assessments["agent"]),
        }
        review_view = {
            "status": "recorded" if grouped_assessments["human"] else "not-recorded",
            "records": _copy(grouped_assessments["human"]),
        }
        if acceptance["status"] in {"invalid", "pending"}:
            reasons.append(f"acceptance status is {acceptance['status']}")
        if acceptance["status"] == "not-recorded":
            reasons.append("PIPE-004 acceptance record is not recorded; release routing is provisional")
        if source_availability != "available":
            reasons.append(f"source availability is {source_availability}")
        if not master["exists"]:
            reasons.append("edition master is missing")
        status = "excluded"
        stage = state_stage or "excluded"
        if state_record is None or state_record["status"] == "missing":
            reasons.append("state sidecar is missing")
        elif state_record["status"] != "valid":
            reasons.extend(state_record["reasons"])
            status = "failed"
        elif edition_target is None:
            reasons.append("edition has no state target")
        elif edition_target["stage"] != "accepted":
            reasons.append(f"state stage is {edition_target['stage']!r}, not accepted")
        elif not master["exists"]:
            status = "failed"
        elif source_availability != "available" or selected_acquisition is None:
            status = "failed"
        elif acceptance["status"] in {"invalid", "pending"}:
            status = "failed"
        elif acceptance["status"] == "promoted" and master["status"] != "accepted":
            status = "failed"
        else:
            status = "included"
            if selected_acquisition and selected_acquisition.get("warnings"):
                status = "warned"
                if isinstance(selected_acquisition["warnings"], list):
                    reasons.extend(str(item) for item in selected_acquisition["warnings"])
        acceptance_dimensions = (
            acceptance["dimensions"]
            if acceptance["status"] in {"pending", "promoted"}
            else _empty_dimensions(source_availability)
        )
        dimensions = _copy(acceptance_dimensions)
        dimensions["source_availability"] = source_availability
        entry: dict[str, Any] = {
            "work_id": edition["work_id"],
            "textual_form_id": edition["textual_form_id"],
            "edition_id": edition["edition_id"],
            "edition_title": edition["edition_title"],
            "master_path": edition["master_path"],
            "master_sha256": master["sha256"],
            "master_status": master["status"],
            "acquisition_path": selected_acquisition["acquisition_path"] if selected_acquisition else None,
            "acquisition_id": selected_acquisition["acquisition_id"] if selected_acquisition else None,
            "source_sha256": selected_acquisition["source_sha256"] if selected_acquisition else None,
            "source_url": selected_acquisition["url"] if selected_acquisition else None,
            "status": status,
            "release_status": (
                "accepted"
                if status in {"included", "warned"} and master["status"] == "accepted"
                else "provisional"
                if status in {"included", "warned"}
                else "not-eligible"
            ),
            "stage": stage,
            "state_status": state_status,
            "state_stage": state_stage,
            "acquisition_stage": acquisition_target["stage"] if acquisition_target else None,
            "acceptance_status": acceptance["status"],
            "acceptance_path": acceptance["acceptance_path"],
            "representation_revision": _copy(acceptance["representation_revision"]),
            "technical": _copy(acceptance["technical"]),
            "review_coverage": acceptance["review_coverage"],
            "acceptance_agent_assessment": acceptance["agent_decision"],
            "human_acceptance": acceptance["human_decision"],
            "agent_assessment": assessment_view,
            "human_review": review_view,
            "dimensions": dimensions,
            "provisional": master["status"] == "present-unbound",
            "reasons": sorted(set(reasons)),
        }
        edition_entries.append(entry)

    edition_entries.sort(
        key=lambda value: (
            str(value["work_id"]),
            str(value["textual_form_id"]),
            str(value["edition_id"]),
        )
    )
    forms.sort(key=lambda value: (str(value["work_id"]), str(value["textual_form_id"])))
    works.sort(key=lambda value: str(value["work_id"]))
    acquisitions.sort(
        key=lambda value: (
            str(value["work_id"]),
            str(value["textual_form_id"]),
            str(value["edition_id"]),
            str(value["acquisition_id"]),
            value["acquisition_path"],
        )
    )
    state_targets.sort(key=lambda value: (str(value["work_id"]), str(value["target_id"]), str(value["target_type"])))
    states.sort(key=lambda value: str(value["work_id"]))
    masters.sort(key=lambda value: (str(value["work_id"]), str(value["textual_form_id"]), str(value["edition_id"]), value["master_path"]))
    acceptances.sort(
        key=lambda value: (
            str(value["work_id"]),
            str(value["textual_form_id"]),
            str(value["edition_id"]),
            value["acceptance_path"],
        )
    )
    assessment_rows.sort(key=lambda value: (str(value.get("work_id")), str(value.get("edition_id")), str(value.get("record_id")), value["record_path"]))
    issues = collector.sorted_issues()
    input_bindings = collector.input_bindings()
    freshness = {
        "algorithm": "sha256(canonical authority input bindings)",
        "status": "current",
        "inputs": input_bindings,
        "input_sha256": sha256_bytes(canonical_bytes(input_bindings)),
    }
    counts = {
        name: sum(1 for item in edition_entries if item["status"] == name)
        for name in _STATUS_NAMES
    }
    counts.update(
        {
            "works": len(works),
            "textual_forms": len(forms),
            "editions": len(edition_entries),
            "acquisitions": len(acquisitions),
            "state_targets": len(state_targets),
            "master_targets": len(masters),
            "masters": sum(bool(item["exists"]) for item in masters),
            "accepted_masters": sum(item["status"] == "accepted" for item in masters),
            "acceptances": sum(item["status"] != "not-recorded" for item in acceptances),
            "issues": len(issues),
            "agent_assessments": sum(item.get("kind") == "agent" and item.get("status") == "valid" for item in assessment_rows),
            "human_reviews": sum(item.get("kind") == "human" and item.get("status") == "valid" for item in assessment_rows),
            "research_leads": len(research_leads),
        }
    )
    for work in works:
        work["editions"] = [
            _copy(item) for item in edition_entries if item["work_id"] == work["work_id"]
        ]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "view_version": VIEW_VERSION,
        "source_root": "library/works",
        "scope": {
            "status": "declared-library-tree-plus-research-leads",
            "library_authority": "declared identities below library/works and their linked state, acquisition, master, and acceptance sidecars",
            "research_authority": "research/MANIFEST.md and library/acquisition-leads.jsonl when both are present",
            "excluded": [
                "historical raw, data, and ir holdings without a declared library identity",
                "WorkCatalog imports and inferred work identities",
                "rights clearance and publication authorization",
            ],
            "research_leads_status": research_status,
        },
        "authority": {
            "work_identity": "library/works/*/work.json",
            "state": "library/works/*/state.json",
            "acquisition": "library/works/*/forms/*/editions/*/acquisitions/*.json",
            "acceptance": "library/works/*/forms/*/editions/*/acceptance.json",
            "assessment": "PIPE-016 records remain separate evidence",
        },
        "freshness": freshness,
        "works": works,
        "forms": forms,
        "editions": edition_entries,
        "acquisitions": acquisitions,
        "states": states,
        "state_targets": state_targets,
        "masters": masters,
        "acceptances": acceptances,
        "assessments": assessment_rows,
        "research_leads": research_leads,
        "issues": issues,
        "counts": counts,
    }
    status_report = {
        "schema_version": SCHEMA_VERSION,
        "view_version": VIEW_VERSION,
        "freshness": freshness,
        "items": [_copy(item) for item in edition_entries],
        "forms": _copy(forms),
        "acquisitions": _copy(acquisitions),
        "state_targets": _copy(state_targets),
        "masters": _copy(masters),
        "acceptances": _copy(acceptances),
        "assessments": _copy(assessment_rows),
        "research_leads": _copy(research_leads),
        "issues": _copy(issues),
        "counts": counts,
    }
    queue_items = [
        item for item in edition_entries if item["status"] in {"excluded", "failed", "warned"}
    ]
    entries_by_edition: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in edition_entries:
        entries_by_edition.setdefault((item["work_id"], item["edition_id"]), []).append(item)
    acquisition_queue: list[dict[str, Any]] = []
    for item in acquisitions:
        related = entries_by_edition.get((item["work_id"], item["edition_id"]), [])
        queue_reason = None
        if item["evidence_status"] != "valid":
            queue_reason = "acquisition evidence is not valid"
        elif item["warnings"]:
            queue_reason = "acquisition carries warnings"
        elif item["identity_status"] != "valid":
            queue_reason = "acquisition identity is not valid"
        elif not related or any(entry["master_status"] != "accepted" for entry in related):
            queue_reason = "edition has no accepted master bound by PIPE-004"
        if queue_reason is not None:
            queue_item = _copy(item)
            queue_item["queue_reason"] = queue_reason
            acquisition_queue.append(queue_item)
    queue = {
        "schema_version": SCHEMA_VERSION,
        "view_version": VIEW_VERSION,
        "freshness": freshness,
        "items": _copy(queue_items),
        "acquisitions": _copy(acquisition_queue),
        "research_leads": _copy(research_leads),
        "issues": _copy(issues),
    }
    return {"manifest": manifest, "status": status_report, "queue": queue, "paths": {}}


def _markdown(manifest: Mapping[str, Any], status: Mapping[str, Any]) -> str:
    lines = [
        "# OCD library view",
        "",
        f"Generated view: `{manifest['view_version']}`.",
        "",
        "Inventory scope: registered library works and acquisition research leads. Historical holdings outside this structure are not inventoried here.",
        "",
        "This is a generated view. Its machine-readable companion lists the authoritative files and their freshness bindings.",
        "",
        "## Counts",
        "",
    ]
    counts = manifest["counts"]
    for name in (
        "works",
        "textual_forms",
        "editions",
        "acquisitions",
        "master_targets",
        "masters",
        "accepted_masters",
        "acceptances",
        "research_leads",
        "issues",
    ):
        lines.append(f"- {name.replace('_', ' ')}: {counts[name]}")
    lines.extend(
        [
            "",
            "## Editions",
            "",
            "| Work | Edition | Source | Master | Acquisition stage | Edition stage | Acceptance |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in status["items"]:
        lines.append(
            f"| {item['work_id']} | {item['edition_id']} | {item['dimensions']['source_availability']} | {item['master_status']} | {item['acquisition_stage'] or 'not recorded'} | {item['state_stage'] or 'not recorded'} | {item['acceptance_status']} |"
        )
    lines.extend(["", "## Issues", ""])
    if not manifest["issues"]:
        lines.append("None.")
    else:
        for issue in manifest["issues"]:
            lines.append(f"- `{issue['code']}` at `{issue['path']}`: {issue['message']}")
    lines.append("")
    return "\n".join(lines)


def _output_path(output: Path, logical: str, *, in_place: bool) -> Path:
    if in_place:
        try:
            return resolve_repo_path(output, logical)
        except StorageTopologyError as exc:
            raise PipelineError(f"cannot route generated output {logical}: {exc}") from exc
    return output.joinpath(*logical.split("/"))


def build_library_views(
    root: Path,
    output: Path,
    *,
    in_place: bool = False,
) -> dict[str, Any]:
    """Build all four generated views.

    The normal mode requires a fresh staging directory. ``in_place=True`` is
    an explicit durable mode and writes only the four generated outputs named
    by PIPE-005 below the selected repository root.
    """

    root = Path(root)
    output = Path(output)
    if in_place and resolve_path(output) != resolve_path(root):
        raise PipelineError("in-place library views require output to equal root")
    if not in_place and io_path(output).exists():
        raise PipelineError(f"library view output must be fresh: {output}")
    result = _build_snapshot(root)
    manifest = result["manifest"]
    status = result["status"]
    queue = result["queue"]
    manifest_path = _output_path(output, "library/corpus-manifest.json", in_place=in_place)
    markdown_path = _output_path(output, "library/corpus-manifest.md", in_place=in_place)
    status_path = _output_path(output, "reports/library/project-status.json", in_place=in_place)
    queue_path = _output_path(output, "reports/library/acquisition-queue.json", in_place=in_place)
    write_json(manifest_path, manifest)
    io_path(markdown_path.parent).mkdir(parents=True, exist_ok=True)
    io_path(markdown_path).write_text(_markdown(manifest, status), encoding="utf-8", newline="\n")
    write_json(status_path, status)
    write_json(queue_path, queue)
    result["paths"] = {
        "manifest": manifest_path.as_posix(),
        "status": status_path.as_posix(),
        "queue": queue_path.as_posix(),
    }
    return result


def check_library_views(root: Path, output: Path, *, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Check generated views against the current authority input fingerprint."""

    root = Path(root)
    output = Path(output)
    in_place = resolve_path(output) == resolve_path(root)
    manifest_path = _output_path(output, "library/corpus-manifest.json", in_place=in_place)
    status_path = _output_path(output, "reports/library/project-status.json", in_place=in_place)
    markdown_path = _output_path(output, "library/corpus-manifest.md", in_place=in_place)
    queue_path = _output_path(output, "reports/library/acquisition-queue.json", in_place=in_place)
    missing = [
        str(path)
        for path in (manifest_path, markdown_path, status_path, queue_path)
        if not io_path(path).is_file()
    ]
    if missing:
        return {"fresh": False, "reasons": [f"generated view is missing: {path}" for path in missing]}
    try:
        stored = load_json(manifest_path)
        stored_status = load_json(status_path)
        stored_queue = load_json(queue_path)
    except PipelineError as exc:
        return {"fresh": False, "reasons": [normalize_diagnostic(root, exc)]}
    current = _build_snapshot(root) if snapshot is None else snapshot
    reasons: list[str] = []
    current_freshness = current["manifest"]["freshness"]
    for name, value, expected in (
        ("manifest", stored, current["manifest"]),
        ("status", stored_status, current["status"]),
        ("queue", stored_queue, current["queue"]),
    ):
        if value != expected:
            reasons.append(f"{name} generated contents are stale relative to current authority")
    expected_markdown = _markdown(current["manifest"], current["status"])
    try:
        actual_markdown = io_path(markdown_path).read_text(encoding="utf-8")
    except OSError as exc:
        reasons.append(f"cannot read generated Markdown: {normalize_diagnostic(root, exc)}")
    else:
        if actual_markdown != expected_markdown:
            reasons.append("Markdown generated contents are stale relative to current authority")
    return {
        "fresh": not reasons,
        "reasons": reasons,
        "current_input_sha256": current_freshness["input_sha256"],
        "stored_input_sha256": (
            stored.get("freshness", {}).get("input_sha256")
            if isinstance(stored.get("freshness"), Mapping)
            else None
        ),
    }


def library_search_matches(search: str | None, values: Iterable[str]) -> bool:
    """Use the same accent-insensitive token search for library CLI and CVW."""
    def normalize(text: str) -> str:
        return "".join(char for char in unicodedata.normalize("NFKD", text).casefold()
                       if not unicodedata.category(char).startswith("M"))
    haystack = normalize(" ".join(values))
    return all(term in haystack for term in normalize(search or "").split())


def library_browse_snapshot(root: Path, *, search: str | None = None,
                            creator: str | None = None, category: str | None = None,
                            stage: str | None = None, offset: int = 0,
                            limit: int | None = None, language: str | None = None,
                            provider: str | None = None, rights_mode: str | None = None,
                            rights_status: str | None = None, jurisdiction: str | None = None,
                            rights_scope: str | None = None) -> dict[str, Any]:
    """Query validated current records and presence without reading text bodies.

    Browse v1 deliberately reports recorded acceptance and observed presence,
    rather than PIPE-005's independently verified master counts. Deep generated
    snapshots and standalone freshness checks retain their existing contract.
    """
    from ._common import inspection_read_phase
    from .labels import profile, label, work_labels, metadata_decisions, acquisition_description, edition_coverage, coverage_summary
    from .rights import collect_rights, matches, validate_filters
    from ocd_kernel.lib.storage_topology import storage_read_phase
    root = Path(root)
    works_root = root / "library" / "works"
    if not io_path(works_root).is_dir():
        raise PipelineError("declared library/works directory is missing")
    if offset < 0 or limit is not None and limit < 1:
        raise PipelineError("browse offset must be nonnegative and limit must be positive")
    if stage is not None and stage not in schema_enum("state", "stage"):
        raise PipelineError(f"unknown recorded stage filter: {stage}")
    validate_filters(rights_mode, rights_status, jurisdiction, rights_scope)
    vocabulary = profile()
    if language is not None:
        language = label('languages', language, vocabulary=vocabulary)['value']
        if language is None:
            raise PipelineError('unmapped language filter')
    if provider is not None:
        provider = label('providers', provider, vocabulary=vocabulary)['value'] or provider
    works, issues = [], []
    counts = {key: 0 for key in ("works", "forms", "editions", "recorded_accepted_editions", "observed_master_files", "failed")}
    with inspection_read_phase(), storage_read_phase():
        for directory in sorted(io_iterdir(works_root), key=lambda path: path.name):
            if not io_path(directory).is_dir():
                continue
            work_id = directory.name
            work_path = f"library/works/{work_id}/work.json"
            row = {"work_id": work_id, "title": None, "work_path": work_path,
                   "identity_status": "invalid", "form_count": 0, "edition_count": 0,
                   "creators": [], "categories": [], "recorded_stages": [], "editions": [], "issues": [],
                   "lookup": None}
            try:
                work = discover_work(root, work_id)
                row.update(title=work.title, identity_status="valid", form_count=len(work.record["textual_forms"]),
                           edition_count=len(work.editions), creators=_copy(work.record.get("creators", [])),
                           lookup=f"py -3 -m build.tools.lookup_library_record --kind work --namespace ocd --id {work_id} --records-only")
                row['normalized'] = work_labels(work.record, vocabulary)
                metadata_read = RecordRead(root)
                row['normalized']['source_metadata'] = metadata_decisions(metadata_read, work.record)
                if not metadata_read.stable():
                    raise PipelineError('source metadata projections changed during collection')
                row['coverage'] = {'kind': 'identity_only' if not work.record['textual_forms'] else 'declared_forms',
                                   'text_integrity': 'not_assessed'}
                descriptions = {item['edition_id']: item for item in row['normalized']['editions']}
                state_path = directory / "state.json"
                state_record = load_state(state_path) if work.editions or io_path(state_path).exists() else None
                if state_record:
                    if state_record["work_id"] != work_id:
                        raise PipelineError(f"state work identity differs: {work_id}")
                    declared = {"edition": {edition.edition_id for edition in work.editions}, "acquisition": {
                        identifier for edition in work.editions for identifier in edition.record.get("acquisition_ids", [])}}
                    if any(target["target_id"] not in declared[target["target_type"]] for target in state_record["targets"]):
                        raise PipelineError(f"state target has no declared identity: {work_id}")
                form_categories = {form["textual_form_id"]: form.get("category") for form in work.record["textual_forms"]}
                for edition in work.editions:
                    read = RecordRead(root)
                    rights = collect_rights(read, work_id, edition.textual_form_id, edition.edition_id)
                    acquisition_home = f'library/works/{work_id}/forms/{edition.textual_form_id}/editions/{edition.edition_id}/acquisitions'
                    from .acquisitions import load_acquisition
                    provider_labels = []
                    sources = []
                    for name in read.members(acquisition_home, '*.json', 'metadata', optional=True):
                        acquisition = read.record(f'{acquisition_home}/{name}', 'metadata', load_acquisition)
                        if acquisition is not None:
                            if acquisition['edition_id'] != edition.edition_id or acquisition['acquisition_id'] != name[:-5] or (
                                    'acquisition_ids' in edition.record and name[:-5] not in edition.record['acquisition_ids']):
                                read.issue('metadata', 'invalid', f'{acquisition_home}/{name}', 'acquisition identity/parent contradicts its declaration')
                                continue
                            provider_labels.append(label('providers', acquisition['provider'], vocabulary=vocabulary))
                            sources.append(acquisition_description(acquisition, vocabulary))
                    if not read.stable():
                        rights = {'health': 'stale', 'coverage': 'unstable', 'records': [], 'subjects': [],
                                  'issues': [{'path': work_path, 'code': 'stale-rights-input', 'message': 'rights inputs changed during collection'}]}
                    for issue in rights['issues']:
                        diagnostic = {**issue, 'severity': 'error'}
                        row['issues'].append(diagnostic)
                        issues.append(diagnostic)
                    for diagnostic in read.diagnostics:
                        row['issues'].append(diagnostic)
                        issues.append(diagnostic)
                    targets = [target for target in (state_record or {}).get("targets", [])
                               if target["target_type"] == "edition" and target["target_id"] == edition.edition_id]
                    recorded_stage = targets[0]["stage"] if targets else None
                    present = io_path(edition.path).is_file()
                    acceptance_present = io_path(edition.path.with_name("acceptance.json")).is_file()
                    row["editions"].append({"edition_id": edition.edition_id, "textual_form_id": edition.textual_form_id,
                                            "title": edition.title,
                                            "form_title": descriptions[edition.edition_id]['form_title'],
                                            "containing_source": descriptions[edition.edition_id]['containing_source'],
                                            "category": edition.record.get("category", form_categories.get(edition.textual_form_id)), "recorded_stage": recorded_stage,
                                            "language": label('languages', resolve_edition_language(
                                                work.record, edition.record, edition.textual_form_id), vocabulary=vocabulary),
                                            "providers": provider_labels, "rights": rights, "sources": sources,
                                            "coverage": edition_coverage(present, acceptance_present, recorded_stage),
                                            "observed_master_presence": present,
                                            "observed_acceptance_presence": acceptance_present})
                    if recorded_stage == "accepted":
                        for path, observed in ((edition.path, present), (edition.path.with_name("acceptance.json"), acceptance_present)):
                            if not observed:
                                issue = {"path": _relative(root, path), "code": "missing-input", "severity": "error",
                                         "message": "recorded accepted edition lacks required observable authority"}
                                row["issues"].append(issue)
                                issues.append(issue)
                    counts["recorded_accepted_editions"] += recorded_stage == "accepted"
                    counts["observed_master_files"] += present
                row["categories"] = sorted({edition["category"] for edition in row["editions"] if edition["category"]})
                row["recorded_stages"] = sorted({edition["recorded_stage"] for edition in row["editions"] if edition["recorded_stage"]})
            except (PipelineError, OSError, UnicodeError) as exc:
                issue = {"path": work_path, "code": "invalid-record", "severity": "error", "message": normalize_diagnostic(root, exc)}
                row["issues"].append(issue)
                issues.append(issue)
            counts["failed"] += bool(row["issues"])
            counts["works"] += 1
            counts["forms"] += row["form_count"]
            counts["editions"] += row["edition_count"]
            works.append(row)
    matching = [row for row in works
                if library_search_matches(search, [row["work_id"], row["title"] or ""] + [item["name"] for item in row["creators"]])
                and library_search_matches(creator, [item["name"] for item in row["creators"]])
                and (all(value is None for value in (category, stage, language, provider, rights_mode, rights_status, jurisdiction, rights_scope)) or any(
                    (category is None or edition["category"] == category)
                    and (stage is None or edition["recorded_stage"] == stage)
                    and (language is None or edition['language']['value'] == language)
                    and (provider is None or any(p['value'] == provider for p in edition['providers']))
                    and (all(v is None for v in (rights_mode, rights_status, jurisdiction, rights_scope)) or matches(
                        edition['rights'], mode=rights_mode, status=rights_status, jurisdiction=jurisdiction, scope=rights_scope))
                    for edition in row["editions"]))]
    selected = matching[offset:] if limit is None else matching[offset:offset + limit]
    return {
        "view_version": "ocd-library-browse-v1",
        "label_profile": vocabulary['version'],
        "scope": {"basis": "validated declarations, recorded state and observed presence", "text_integrity": "not_assessed"},
        "counts": counts,
        "metadata_coverage": coverage_summary(works),
        "freshness": {"basis": "current records per independent invocation; text-byte integrity not assessed"},
        "works": selected,
        "page": {"offset": offset, "returned": len(selected), "total": len(matching),
                 "next_offset": offset + len(selected) if offset + len(selected) < len(matching) else None},
        "issues": issues,
        "authority": "read-only projection; owning sidecars remain authoritative; acceptance and release eligibility are not reverified",
        "legacy_coverage": "not measured; undeclared data/ and ir/ holdings are excluded",
    }


__all__ = ["VIEW_VERSION", "build_library_views", "check_library_views", "library_browse_snapshot", "library_search_matches"]
