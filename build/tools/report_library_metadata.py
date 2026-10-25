"""Read-only objective-metadata assessment for META-001.

The report consumes the declared library inventory and the separately retained
acquisition-lead queue.  It never edits a sidecar, master, retained source, or
generated view, and it never turns a research lead into a stable work identity.
Its declared-coverage result is complete only when the inventory validation and
lead accounting succeed; historical raw/data/ir holdings remain unassessed.
Report output is restricted to the META-001 artifact directory (or a new
already-parented external temporary file).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping
from xml.etree import ElementTree as ET

from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path
from ocd_kernel.library._common import (
    PipelineError,
    load_json,
    sha256_file,
    write_json,
)
from ocd_kernel.library.acquisitions import load_acquisition_leads, manifest_research
from ocd_kernel.library.identities import _schema as load_library_schema
from ocd_kernel.library.views import _build_snapshot, check_library_views


REPORT_VERSION = "ocd-metadata-report-v1"
SCHEMA_VERSION = "1.0"
CLASSIFICATIONS = (
    "required_missing",
    "useful_optional_missing",
    "contradictory",
    "unknown",
)
_TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}
_MISSING = object()
_KNOWN_LIBRARY_INPUTS = {
    "sweep-index.json": "ticket37-sweep",
    "readiness325/work-index.json": "ticket37-readiness325",
    "acquisition-gap-report.json": "ticket37-acquisition-gap",
}
_LEGACY_OBSERVED_FIELDS = (
    ("title", "title", "title"),
    ("author", "author", "author"),
    ("contributors", None, "contributors"),
    ("translator", None, "provenance.translator"),
    ("language", None, "language"),
    ("original_language", None, "original_language"),
    ("source_edition", None, "provenance.source_edition"),
    ("source_file", None, "provenance.source_file"),
    ("source_type", None, "provenance.source_type"),
    ("source_format", None, "provenance.source_format"),
    ("source_url", None, "provenance.source_url"),
    ("source_hash", None, "provenance.source_hash"),
    ("download_date", None, "provenance.download_date"),
    ("processing_date", None, "provenance.processing_date"),
    ("publication_date", "publication_date", "publication_date"),
    ("original_publication_year", None, "original_publication_year"),
)
_MAX_OBSERVED_VALUES = 8


def _copy(value: Any) -> Any:
    """Copy JSON-shaped data without giving the report a mutable authority."""

    return json.loads(json.dumps(value, ensure_ascii=False))


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "item"


def _normalize_error(root: Path, message: object) -> str:
    """Strip the selected root from diagnostics without hiding the reason."""

    text = str(message).replace("\\", "/")
    variants = {
        str(Path(root).absolute()).replace("\\", "/"),
        str(Path(root).resolve()).replace("\\", "/"),
    }
    for variant in sorted(variants, key=len, reverse=True):
        variant = variant.rstrip("/")
        if variant:
            text = re.sub(
                re.escape(variant) + r"(?:/|(?=$|[^A-Za-z0-9._-]))",
                "",
                text,
                flags=re.IGNORECASE,
            )
    for logical_root in ("raw", "reports", "exports"):
        try:
            physical_root = _resolve(Path(root), logical_root)
        except PipelineError:
            continue
        variant = str(physical_root).replace("\\", "/").rstrip("/")
        if variant:
            text = re.sub(
                re.escape(variant) + r"/",
                logical_root + "/",
                text,
                flags=re.IGNORECASE,
            )
    return text


def _resolve(root: Path, logical: str) -> Path:
    try:
        return resolve_repo_path(Path(root), logical)
    except StorageTopologyError as exc:
        raise PipelineError(f"cannot resolve {logical}: {exc}") from exc


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _is_reparse_point(path: Path) -> bool:
    """Return whether one output path component redirects outside its spelling."""

    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _has_reparse_component(path: Path, *, stop: Path) -> bool:
    """Reject symlink/junction components between the checkout and an output."""

    try:
        relative = path.absolute().relative_to(stop.absolute())
    except ValueError:
        return False
    current = stop.absolute()
    for part in relative.parts:
        current /= part
        if _is_reparse_point(current):
            return True
    return False


def _ensure_output_allowed(root: Path, output: Path) -> Path:
    """Allow only the META-001 report area or a new external temp file."""

    root = Path(root).resolve()
    candidate = Path(output)
    if not candidate.is_absolute():
        candidate = root / candidate
    lexical = candidate.absolute()
    try:
        lexical_relative = lexical.relative_to(root)
    except ValueError:
        lexical_relative = None
    if lexical_relative is not None and lexical_relative.parts:
        if lexical_relative.parts[0] in {"raw", "reports", "exports", "library", "research", "data", "ir", ".git"}:
            raise PipelineError(
                "refusing to write a metadata report into a repository or durable-storage authority"
            )
    artifact_root_lexical = (
        root
        / "plans"
        / "2026-08-31-library-pipeline-redesign"
        / "artifacts"
        / "META-001"
    )
    if _has_reparse_component(artifact_root_lexical, stop=root):
        raise PipelineError(
            "refusing META-001 output because its artifact directory contains a symlink or junction"
        )
    artifact_root = artifact_root_lexical.resolve(strict=False)
    protected_roots = []
    for logical in ("raw", "reports", "exports"):
        try:
            protected_roots.append(_resolve(root, logical).resolve(strict=False))
        except PipelineError as exc:
            raise PipelineError(
                "refusing META-001 output because the configured storage boundary cannot be verified"
            ) from exc
    if not _is_within(artifact_root, root) or any(
        _is_within(artifact_root, protected_root) for protected_root in protected_roots
    ):
        raise PipelineError(
            "refusing META-001 output because its artifact directory resolves outside the repository"
        )
    resolved = candidate.resolve(strict=False)
    if _is_within(lexical, artifact_root_lexical):
        if _has_reparse_component(lexical, stop=root) or not _is_within(resolved, artifact_root):
            raise PipelineError(
                "refusing META-001 output through a symlink or junction component"
            )
        if resolved.suffix.lower() != ".json":
            raise PipelineError("META-001 output must be a JSON report")
        return resolved
    if _is_within(resolved, root):
        raise PipelineError(
            "refusing to write a metadata report over a repository authority or generated view; "
            "use the META-001 artifact directory"
        )
    for logical_root in ("raw", "reports", "exports"):
        try:
            external_root = _resolve(root, logical_root).resolve()
        except PipelineError:
            continue
        if _is_within(resolved, external_root):
            raise PipelineError(
                "refusing to write a metadata report into the configured durable-storage authority"
            )
    if candidate.exists() or resolved.exists():
        raise PipelineError("external report output must be a new file")
    if not resolved.parent.is_dir():
        raise PipelineError("external report output parent must already exist")
    return resolved


def _file_binding(root: Path, logical: str, *, role: str) -> dict[str, Any]:
    """Return portable byte evidence for one logical authority path."""

    result: dict[str, Any] = {"path": logical, "role": role}
    try:
        physical = _resolve(root, logical)
    except PipelineError as exc:
        result.update({"exists": False, "error": _normalize_error(root, exc)})
        return result
    if not physical.is_file():
        result["exists"] = False
        return result
    result.update(
        {
            "exists": True,
            "bytes": physical.stat().st_size,
            "sha256": sha256_file(physical),
        }
    )
    return result


def _portable_input_path(root: Path, requested: Path | str) -> tuple[Path, str]:
    """Resolve an explicitly selected input while retaining a portable label."""

    candidate = Path(requested)
    if not candidate.is_absolute():
        candidate = Path(root) / candidate
    candidate = candidate.absolute()
    root_absolute = Path(root).absolute()
    try:
        label = candidate.relative_to(root_absolute).as_posix()
    except ValueError:
        label = candidate.as_posix()
    return candidate, label


def _normalized_path_text(value: object) -> str:
    return str(value).replace("\\", "/").lstrip("./")


def _strict_input_binding(
    root: Path,
    path: Path,
    *,
    label: str,
    role: str,
    declared_bytes: int | None = None,
    declared_sha256: str | None = None,
) -> dict[str, Any]:
    """Bind one selected input and fail closed on absence or byte drift."""

    if not path.is_file():
        raise PipelineError(f"{role} input missing: {label}")
    actual_bytes = path.stat().st_size
    actual_sha256 = sha256_file(path)
    if declared_bytes is not None and actual_bytes != declared_bytes:
        raise PipelineError(
            f"{role} input drift: {label} byte count {actual_bytes} != recorded {declared_bytes}"
        )
    if declared_sha256 is not None and actual_sha256 != declared_sha256:
        raise PipelineError(
            f"{role} input drift: {label} SHA-256 {actual_sha256} != recorded {declared_sha256}"
        )
    result: dict[str, Any] = {
        "path": label,
        "role": role,
        "exists": True,
        "bytes": actual_bytes,
        "sha256": actual_sha256,
    }
    if declared_bytes is not None:
        result["declared_bytes"] = declared_bytes
    if declared_sha256 is not None:
        result["declared_sha256"] = declared_sha256
    if declared_bytes is not None or declared_sha256 is not None:
        result["verified"] = True
    return result


def _load_selected_json(path: Path, *, label: str, role: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PipelineError(f"{role} input missing: {label}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"{role} input is not valid UTF-8 JSON: {label}: {exc}") from exc


def _compact_observed_values(value: object) -> tuple[list[Any], int]:
    if value is _MISSING or value is None or value == "" or value == []:
        return [], 0
    values = value if isinstance(value, list) else [value]
    copied = [_copy(item) for item in values]
    return copied[:_MAX_OBSERVED_VALUES], len(copied)


def _value_is_present(value: object) -> bool:
    return value is not _MISSING and value is not None and value != "" and value != []


def _legacy_observed_claim(
    row: Mapping[str, Any],
    metadata: Mapping[str, Any],
    *,
    row_field: str | None,
    metadata_field: str,
) -> dict[str, Any]:
    """Expose selected legacy values as unverified observations, not authority."""

    row_value = row.get(row_field, _MISSING) if row_field else _MISSING
    metadata_value = metadata.get(metadata_field, _MISSING)
    if _value_is_present(row_value):
        selected = row_value
        source = "legacy_catalog.work_row"
    elif _value_is_present(metadata_value):
        selected = metadata_value
        source = "legacy_catalog.metadata_fields"
    elif row_value is not _MISSING:
        selected = row_value
        source = "legacy_catalog.work_row"
    else:
        selected = metadata_value
        source = "legacy_catalog.metadata_fields"
    values, value_count = _compact_observed_values(selected)
    claim: dict[str, Any] = {
        "present": _value_is_present(selected),
        "values": values,
        "value_count": value_count,
        "truncated": value_count > len(values),
        "source": source,
        "top_level_present": _value_is_present(row_value),
        "metadata_field_present": _value_is_present(metadata_value),
    }
    if metadata_value is not _MISSING and source != "legacy_catalog.metadata_fields":
        metadata_values, metadata_count = _compact_observed_values(metadata_value)
        claim["metadata_values"] = metadata_values
        claim["metadata_value_count"] = metadata_count
        claim["metadata_truncated"] = metadata_count > len(metadata_values)
    return claim


def _legacy_observed_metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata_fields")
    if not isinstance(metadata, Mapping):
        metadata = {}
    fields: dict[str, Any] = {}
    for output_field, row_field, metadata_field in _LEGACY_OBSERVED_FIELDS:
        fields[output_field] = _legacy_observed_claim(
            row,
            metadata,
            row_field=row_field,
            metadata_field=metadata_field,
        )
    source_paths = row.get("source_paths")
    if isinstance(source_paths, list):
        paths = [str(item) for item in source_paths if isinstance(item, str)]
    else:
        paths = []
    return {
        "status": "observed_legacy_claim",
        "authoritative": False,
        "fields": fields,
        "source_paths": {
            "count": len(paths),
            "sample": paths[:3],
            "truncated": len(paths) > 3,
        },
    }


def _rows_with_unique_ids(value: object, *, key: str, role: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if not isinstance(value, list):
        raise PipelineError(f"{role} must contain a list of {key} rows")
    rows: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise PipelineError(f"{role} row {index + 1} is not an object")
        item = dict(raw)
        identity = item.get("work_id")
        if not isinstance(identity, str) or not identity:
            raise PipelineError(f"{role} row {index + 1} has no non-empty work_id")
        if identity in by_id:
            duplicates.add(identity)
        else:
            by_id[identity] = item
        rows.append(item)
    if duplicates:
        raise PipelineError(f"duplicate {role} work_id(s): {', '.join(sorted(duplicates))}")
    return rows, by_id


def _set_difference_message(label: str, left: set[str], right: set[str]) -> str:
    missing = sorted(left - right)
    extra = sorted(right - left)
    details = []
    if missing:
        details.append(f"missing={missing[:12]}")
    if extra:
        details.append(f"unexpected={extra[:12]}")
    return f"{label} ID set drift ({'; '.join(details) or 'sets differ'})"


def _known_library_input_identity(
    known: Mapping[str, Any],
    *,
    known_path: Path,
    root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Path], dict[str, dict[str, Any]]]:
    identities = known.get("input_identities")
    if not isinstance(identities, list):
        raise PipelineError("known-library catalog has no input_identities list")
    by_path: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(identities):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("path"), str):
            raise PipelineError(f"known-library input identity {index + 1} is malformed")
        path_key = _normalized_path_text(raw["path"])
        if path_key in by_path:
            raise PipelineError(f"duplicate known-library input identity: {path_key}")
        if not isinstance(raw.get("bytes"), int) or not isinstance(raw.get("sha256"), str):
            raise PipelineError(f"known-library input identity is incomplete: {path_key}")
        by_path[path_key] = dict(raw)
    bindings: list[dict[str, Any]] = []
    paths: dict[str, Path] = {}
    selected: dict[str, dict[str, Any]] = {}
    for expected_path, role in _KNOWN_LIBRARY_INPUTS.items():
        identity = by_path.get(expected_path)
        if identity is None:
            raise PipelineError(f"known-library input identity missing: {expected_path}")
        selected[role] = identity
        path, _ = _portable_input_path(known_path.parent, expected_path)
        label = _portable_input_path(root, path)[1]
        paths[role] = path
        bindings.append(
            _strict_input_binding(
                root,
                path,
                label=label,
                role=role,
                declared_bytes=identity["bytes"],
                declared_sha256=identity["sha256"],
            )
        )
    return bindings, paths, selected


def _receipt_for_catalog(
    root: Path,
    catalog_path: Path,
    *,
    catalog_label: str,
) -> tuple[dict[str, Any], dict[str, Any], Path, str]:
    receipt_path = catalog_path.with_name("library-status-verification.json")
    receipt_label = _portable_input_path(root, receipt_path)[1]
    receipt_binding = _strict_input_binding(
        root,
        receipt_path,
        label=receipt_label,
        role="known-library-verification-receipt",
    )
    receipt = _load_selected_json(
        receipt_path,
        label=receipt_label,
        role="known-library-verification-receipt",
    )
    if not isinstance(receipt, Mapping) or receipt.get("decision") != "PASS":
        raise PipelineError("known-library-verification-receipt is not a PASS receipt")
    outputs = receipt.get("outputs")
    if not isinstance(outputs, list):
        raise PipelineError("known-library-verification-receipt has no outputs list")
    matches = [
        item
        for item in outputs
        if isinstance(item, Mapping)
        and isinstance(item.get("path"), str)
        and (
            _normalized_path_text(item["path"]) == _normalized_path_text(catalog_label)
            or Path(_normalized_path_text(item["path"])).name == catalog_path.name
        )
    ]
    if len(matches) != 1:
        raise PipelineError(
            "known-library-verification-receipt must bind exactly one library-status.json output"
        )
    output = matches[0]
    if not isinstance(output.get("bytes"), int) or not isinstance(output.get("sha256"), str):
        raise PipelineError("known-library-verification-receipt catalog output binding is incomplete")
    catalog_binding = _strict_input_binding(
        root,
        catalog_path,
        label=catalog_label,
        role="known-library-catalog",
        declared_bytes=output["bytes"],
        declared_sha256=output["sha256"],
    )
    return receipt_binding, catalog_binding, receipt_path, receipt_label


def _known_library_lane_row(
    lane: Mapping[str, Any],
    *,
    lead: Mapping[str, Any],
) -> dict[str, Any]:
    catalog_relation = lane.get("catalog_relation")
    if not isinstance(catalog_relation, Mapping):
        catalog_relation = {}
    exact_existing = bool(catalog_relation.get("exact")) and isinstance(
        catalog_relation.get("work_id"), str
    )
    execution_route = lane.get("execution_route")
    if not isinstance(execution_route, Mapping):
        execution_route = {}
    identity_evidence = lane.get("identity_evidence")
    if not isinstance(identity_evidence, Mapping):
        identity_evidence = {}
    research_evidence = lane.get("research_evidence")
    if not isinstance(research_evidence, Mapping):
        research_evidence = {}
    lead_evidence = lead.get("evidence")
    return {
        "sequence": lane.get("sequence"),
        "lane": lane.get("lane"),
        "title": lane.get("title"),
        "grouping_key": lane.get("grouping_key"),
        "identity_disposition": (
            "supported_existing_catalog_id" if exact_existing else "proposed_lane_grouping"
        ),
        "relationship": lane.get("relationship"),
        "classification": lane.get("classification"),
        "scope_status": lane.get("scope_status"),
        "catalog_relation": _copy(
            {
                key: catalog_relation.get(key)
                for key in ("current_view", "exact", "relation", "work_id", "related_work_ids")
                if key in catalog_relation
            }
        ),
        "execution": _copy(
            {
                "ticket": lane.get("execution_ticket"),
                "route_key": execution_route.get("route_key"),
                "path": execution_route.get("path"),
                "status": execution_route.get("status"),
                "next_action": lane.get("next_action"),
            }
        ),
        "identity_evidence": _copy(
            {
                key: identity_evidence.get(key)
                for key in (
                    "file",
                    "path",
                    "archive_member",
                    "locator",
                    "sha256",
                    "container_sha256",
                    "text_member_sha256",
                    "text_member_bytes",
                )
                if key in identity_evidence
            }
        ),
        "unresolved": _copy(lane.get("unresolved", [])),
        "identity_boundaries": {
            "work": "existing_catalog_id" if exact_existing else "proposed_grouping_only",
            "textual_form": "unresolved",
            "edition": "unresolved",
            "parts": "unresolved",
            "witnesses": "unresolved",
            "reasons": _copy(lane.get("unresolved", [])),
        },
        "research_join": {
            "lead_id": research_evidence.get("lead_id"),
            "matched": True,
            "disposition": lead.get("disposition"),
            "identity_status": lead.get("identity_status"),
            "stable_work_id": lead.get("stable_work_id"),
            "line_number": lead.get("line_number"),
            "observed_claim": lead.get("observed_claim"),
            "evidence": _copy(lead_evidence),
        },
    }


def _known_library_assessment(
    root: Path,
    manifest: Mapping[str, Any],
    lead_rows: Iterable[Mapping[str, Any]],
    known_library_catalog: Path,
    legacy_catalog: Path,
) -> dict[str, Any]:
    known_path, known_label = _portable_input_path(root, known_library_catalog)
    legacy_path, legacy_label = _portable_input_path(root, legacy_catalog)
    receipt_binding, catalog_binding, receipt_path, receipt_label = _receipt_for_catalog(
        root,
        known_path,
        catalog_label=known_label,
    )
    receipt = _load_selected_json(receipt_path, label=receipt_label, role="verification receipt")
    known = _load_selected_json(known_path, label=known_label, role="known-library-catalog")
    legacy = _load_selected_json(legacy_path, label=legacy_label, role="legacy-catalog")
    if not isinstance(known, Mapping):
        raise PipelineError("known-library-catalog must contain an object")
    if not isinstance(legacy, Mapping):
        raise PipelineError("legacy-catalog must contain an object")
    known_rows, known_by_id = _rows_with_unique_ids(
        known.get("catalog_rows"), key="catalog_rows", role="known-library-catalog"
    )
    sweep_bindings, input_paths, input_identities = _known_library_input_identity(
        known,
        known_path=known_path,
        root=root,
    )
    sweep = _load_selected_json(
        input_paths["ticket37-sweep"],
        label=sweep_bindings[0]["path"],
        role="ticket37-sweep",
    )
    readiness = _load_selected_json(
        input_paths["ticket37-readiness325"],
        label=next(item["path"] for item in sweep_bindings if item["role"] == "ticket37-readiness325"),
        role="ticket37-readiness325",
    )
    acquisition_gap = _load_selected_json(
        input_paths["ticket37-acquisition-gap"],
        label=next(item["path"] for item in sweep_bindings if item["role"] == "ticket37-acquisition-gap"),
        role="ticket37-acquisition-gap",
    )
    sweep_rows, sweep_by_id = _rows_with_unique_ids(
        sweep.get("catalog_rows") if isinstance(sweep, Mapping) else None,
        key="catalog_rows",
        role="ticket37-sweep",
    )
    legacy_rows_value = legacy.get("works")
    legacy_rows, legacy_by_id = _rows_with_unique_ids(
        legacy_rows_value,
        key="works",
        role="legacy-catalog",
    )
    catalog_ids = set(known_by_id)
    sweep_ids = set(sweep_by_id)
    legacy_ids = set(legacy_by_id)
    if catalog_ids != sweep_ids:
        raise PipelineError(_set_difference_message("known catalog versus sweep", catalog_ids, sweep_ids))
    if catalog_ids != legacy_ids:
        raise PipelineError(_set_difference_message("known catalog versus legacy catalog", catalog_ids, legacy_ids))
    for work_id in sorted(catalog_ids):
        known_row = known_by_id[work_id]
        sweep_row = sweep_by_id[work_id]
        for known_field, sweep_field in (
            ("catalog_status_at_inventory", "status"),
            ("reconstruction_owner", "reconstruction_owner"),
            ("existing_review_ticket", "existing_review_ticket"),
        ):
            if (
                known_field in known_row
                and sweep_field in sweep_row
                and known_row.get(known_field) != sweep_row.get(sweep_field)
            ):
                raise PipelineError(f"known catalog versus sweep drift for {work_id}: {known_field}")
        if (
            known_row.get("assessment_status") == "previously_cataloged"
            and "next_action" in known_row
            and "next_action" in sweep_row
            and known_row.get("next_action") != sweep_row.get("next_action")
        ):
            raise PipelineError(f"known catalog versus sweep drift for {work_id}: next_action")

    readiness_rows, readiness_by_id = _rows_with_unique_ids(
        readiness.get("rows") if isinstance(readiness, Mapping) else None,
        key="rows",
        role="ticket37-readiness325",
    )
    expected_readiness_ids = {
        work_id
        for work_id, row in known_by_id.items()
        if row.get("assessment_status") == "assessed_follow_up_required"
    }
    actual_readiness_ids = set(readiness_by_id)
    if actual_readiness_ids != expected_readiness_ids:
        raise PipelineError(
            _set_difference_message("readiness325 versus assessed catalog subset", expected_readiness_ids, actual_readiness_ids)
        )
    for work_id in sorted(expected_readiness_ids):
        known_row = known_by_id[work_id]
        readiness_row = readiness_by_id[work_id]
        for readiness_field, known_field in (
            ("owner", "reconstruction_owner"),
            ("next_action", "next_action"),
            ("investigation_disposition", "disposition"),
        ):
            if readiness_row.get(readiness_field) != known_row.get(known_field):
                raise PipelineError(
                    f"readiness325 drift for {work_id}: {readiness_field} does not match catalog"
                )
        evidence = known_row.get("assessment_evidence")
        if isinstance(evidence, Mapping):
            for field in ("new_visual_review", "new_review_admission"):
                if field in evidence and readiness_row.get(field) != evidence.get(field):
                    raise PipelineError(f"readiness325 drift for {work_id}: {field} does not match catalog")

    assessment_statuses = {str(row.get("assessment_status")) for row in known_rows}
    if assessment_statuses - {"assessed_follow_up_required", "previously_cataloged"}:
        raise PipelineError("known-library catalog has an unsupported assessment_status partition")
    prior_rows = [
        row for row in known_rows if row.get("assessment_status") == "previously_cataloged"
    ]
    manifest_by_id = {
        str(row.get("work_id")): row
        for row in manifest.get("works", [])
        if isinstance(row, Mapping) and isinstance(row.get("work_id"), str)
    }
    lead_by_id: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for lead in lead_rows:
        lead_id = lead.get("lead_id")
        if isinstance(lead_id, str):
            lead_by_id[lead_id].append(lead)

    catalog_output_rows: list[dict[str, Any]] = []
    registered_count = 0
    for known_row in known_rows:
        work_id = str(known_row["work_id"])
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", work_id):
            raise PipelineError(f"known-library catalog work_id is not a safe stable ID: {work_id}")
        legacy_row = legacy_by_id[work_id]
        current_work = manifest_by_id.get(work_id)
        authority_path = (
            current_work.get("work_path")
            if isinstance(current_work, Mapping) and isinstance(current_work.get("work_path"), str)
            else f"library/works/{work_id}/work.json"
        )
        authority = _file_binding(root, authority_path, role="current-work-authority")
        registered = bool(authority.get("exists"))
        registered_count += int(registered)
        declared_work, _ = _safe_json(root, authority_path) if registered else (None, None)
        declared_forms = declared_work.get("textual_forms", []) if declared_work else []
        readiness_row = readiness_by_id.get(work_id)
        if readiness_row is not None:
            readiness_view = {
                "population": "readiness325",
                "assessment_status": known_row.get("assessment_status"),
                "owner": readiness_row.get("owner"),
                "disposition": readiness_row.get("investigation_disposition"),
                "next_action": readiness_row.get("next_action"),
                "evidence_report": readiness_row.get("evidence_report"),
                "evidence_selector": readiness_row.get("evidence_selector"),
                "new_visual_review": readiness_row.get("new_visual_review"),
                "new_review_admission": readiness_row.get("new_review_admission"),
            }
        else:
            readiness_view = {
                "population": "prior_catalog_disposition",
                "assessment_status": known_row.get("assessment_status"),
                "owner": known_row.get("reconstruction_owner"),
                "disposition": known_row.get("disposition"),
                "next_action": known_row.get("next_action"),
                "reason": "no readiness325 row; prior catalog disposition is carried forward",
            }
        metadata = _legacy_observed_metadata(legacy_row)
        source_paths = legacy_row.get("source_paths")
        source_path_count = len(source_paths) if isinstance(source_paths, list) else 0
        catalog_output_rows.append(
            {
                "work_id": work_id,
                "title": known_row.get("title"),
                "category": legacy_row.get("category"),
                "schema_types": _copy(legacy_row.get("schema_types", [])),
                "file_count": legacy_row.get("file_count"),
                "catalog_status_at_inventory": known_row.get("catalog_status_at_inventory"),
                "assessment_status": known_row.get("assessment_status"),
                "reconstruction_owner": known_row.get("reconstruction_owner"),
                "existing_review_ticket": known_row.get("existing_review_ticket"),
                "sweep_ticket": known_row.get("sweep_ticket"),
                "disposition": known_row.get("disposition"),
                "next_action": known_row.get("next_action"),
                "identity_disposition": "supported_existing_catalog_id",
                "readiness": readiness_view,
                "current_authority": {
                    "registration_status": "registered" if registered else "unregistered_legacy_catalog_id",
                    "work_json": authority,
                    "factual_metadata_verified": False,
                    "declared_textual_forms": _copy(declared_forms),
                },
                "identity_boundaries": {
                    "work": "existing_catalog_id",
                    "textual_form": "declared_in_work_authority" if declared_forms else "unassessed",
                    "edition": "see_declared_textual_forms" if declared_forms else "unassessed",
                    "parts": "unassessed",
                    "witnesses": "unassessed",
                    "reason": "the legacy catalog row does not establish v2 identity relationships",
                },
                "observed_legacy_metadata": metadata,
                "source_path_count": source_path_count,
            }
        )

    lanes = known.get("acquisition_lanes")
    if not isinstance(lanes, list):
        raise PipelineError("known-library catalog has no acquisition_lanes list")
    lane_rows: list[dict[str, Any]] = []
    seen_sequences: set[object] = set()
    seen_lane_names: set[str] = set()
    seen_lead_ids: set[str] = set()
    for index, lane in enumerate(lanes):
        if not isinstance(lane, Mapping):
            raise PipelineError(f"known-library acquisition lane {index + 1} is not an object")
        sequence = lane.get("sequence")
        lane_name = lane.get("lane")
        if not isinstance(sequence, int):
            raise PipelineError(f"known-library acquisition lane {index + 1} has no integer sequence")
        if sequence in seen_sequences:
            raise PipelineError(f"duplicate known-library acquisition lane sequence: {sequence}")
        if not isinstance(lane_name, str) or not lane_name:
            raise PipelineError(f"known-library acquisition lane {index + 1} has no lane name")
        if lane_name in seen_lane_names:
            raise PipelineError(f"duplicate known-library acquisition lane: {lane_name}")
        seen_sequences.add(sequence)
        seen_lane_names.add(lane_name)
        research_evidence = lane.get("research_evidence")
        lead_id = research_evidence.get("lead_id") if isinstance(research_evidence, Mapping) else None
        if not isinstance(lead_id, str):
            raise PipelineError(f"acquisition lane has no research lead_id: {lane_name}")
        if lead_id in seen_lead_ids:
            raise PipelineError(f"duplicate research lead join across acquisition lanes: {lead_id}")
        seen_lead_ids.add(lead_id)
        relation = lane.get("catalog_relation", {})
        if not isinstance(relation, Mapping):
            raise PipelineError(f"invalid catalog relation for acquisition lane: {lane_name}")
        related_ids = relation.get("related_work_ids", [])
        if not isinstance(related_ids, list) or any(not isinstance(value, str) for value in related_ids):
            raise PipelineError(f"invalid related catalog IDs for acquisition lane: {lane_name}")
        if relation.get("work_id"):
            related_ids = related_ids + [relation["work_id"]]
        if set(related_ids) - catalog_ids:
            raise PipelineError(f"unknown existing catalog ID in acquisition lane: {lane_name}")
        matches = lead_by_id.get(lead_id, [])
        if len(matches) != 1:
            raise PipelineError(
                f"acquisition lane lead join must match exactly once: {lane_name} -> {lead_id} ({len(matches)})"
            )
        lane_rows.append(_known_library_lane_row(lane, lead=matches[0]))

    gap_rows = acquisition_gap.get("rows") if isinstance(acquisition_gap, Mapping) else None
    if not isinstance(gap_rows, list) or any(not isinstance(row, Mapping) for row in gap_rows):
        raise PipelineError("acquisition-gap rows must be objects")
    gap_pairs = [(row.get("sequence"), row.get("lane")) for row in gap_rows]
    if any(not isinstance(seq, int) or not isinstance(name, str) for seq, name in gap_pairs):
        raise PipelineError("invalid acquisition-gap lane identity")
    actual_pairs = {(row["sequence"], row["lane"]) for row in lane_rows}
    if len(set(gap_pairs)) != len(gap_pairs) or set(gap_pairs) != actual_pairs:
        raise PipelineError("acquisition-gap versus known catalog lane identities differ")
    receipt_checks = receipt.get("checks") if isinstance(receipt, Mapping) else None
    return {
        "status": "catalog_accounting_complete_factual_verification_incomplete",
        "factual_verification": "incomplete",
        "catalog_accounting": "complete",
        "catalog_rows": sorted(catalog_output_rows, key=lambda row: str(row["work_id"])),
        "input_bindings": [
            catalog_binding,
            receipt_binding,
            _strict_input_binding(root, legacy_path, label=legacy_label, role="legacy-catalog"),
            *sweep_bindings,
        ],
        "verification_receipt": {
            "path": receipt_label,
            "decision": receipt.get("decision"),
            "checks": _copy(receipt_checks or []),
        },
        "legacy_catalog": {
            "path": legacy_label,
            "row_count": len(legacy_rows),
            "unique_work_ids": len(legacy_by_id),
            "observed_claims_authoritative": False,
        },
        "catalog": {
            "row_count": len(known_rows),
            "unique_work_ids": len(known_by_id),
            "sweep_row_count": len(sweep_rows),
            "legacy_row_count": len(legacy_rows),
            "exact_set_against_sweep": True,
            "exact_set_against_legacy_catalog": True,
            "readiness_expected_row_count": len(expected_readiness_ids),
            "readiness_actual_row_count": len(readiness_rows),
            "prior_disposition_row_count": len(prior_rows),
            "registration_status": {
                "registered": registered_count,
                "unregistered_legacy_catalog_id": len(known_rows) - registered_count,
            },
        },
        "readiness": {
            "path": next(
                item["path"] for item in sweep_bindings if item["role"] == "ticket37-readiness325"
            ),
            "row_count": len(readiness_rows),
            "expected_subset": True,
            "assessment_status_counts": dict(
                sorted(Counter(str(row.get("assessment_status")) for row in known_rows).items())
            ),
            "prior_disposition_preserved": len(prior_rows) == len(known_rows) - len(readiness_rows),
        },
        "acquisition_gap": {
            "path": next(
                item["path"] for item in sweep_bindings if item["role"] == "ticket37-acquisition-gap"
            ),
            "row_count": len(gap_rows) if isinstance(gap_rows, list) else None,
        },
        "acquisition_lanes": lane_rows,
        "lane_accounting": {
            "row_count": len(lane_rows),
            "all_joined_once_to_research_lead": True,
            "identity_promotion": False,
            "combined_work_count": None,
        },
        "limits": [
            "Observed legacy catalog values are unverified claims, not metadata authority.",
            "Readiness status and prior dispositions do not establish primary source verification.",
            "Unregistered catalog IDs do not become required metadata defects.",
            "Acquisition lanes retain proposed grouping keys and do not mint or combine work IDs.",
        ],
    }


def _reference_evidence(root: Path, reference: str, *, role: str) -> dict[str, Any]:
    """Retain an authored evidence reference and its current file binding."""

    path, marker, fragment = reference.partition("#")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", path):
        return {"reference": reference, "role": role, "external": True}
    result = _file_binding(root, path, role=role)
    result["reference"] = reference
    if marker:
        match = re.fullmatch(r"L(\d+)(?:-L(\d+))?", fragment)
        if match:
            result["line_start"] = int(match.group(1))
            result["line_end"] = int(match.group(2) or match.group(1))
        else:
            result["fragment"] = fragment
    return result


def _evidence_for_path(root: Path, logical: str, *, role: str) -> list[dict[str, Any]]:
    return [_file_binding(root, logical, role=role)]


def _finding(
    *,
    entity_id: str | None,
    entity_type: str,
    field_path: str,
    classification: str,
    authority_path: str | None,
    authority_route: str,
    authority_kind: str | None = None,
    contract_or_user_need: str,
    evidence: Iterable[Mapping[str, Any]] = (),
    availability: str,
    unresolved_reason: str | None = None,
    dependencies: Iterable[str] = (),
    current_value: Any = _MISSING,
) -> dict[str, Any]:
    if classification not in CLASSIFICATIONS:
        raise ValueError(f"unsupported metadata classification: {classification}")
    key = f"{entity_id or 'unidentified'}:{field_path}:{classification}"
    row: dict[str, Any] = {
        "finding_id": f"finding-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}",
        "identity": entity_id,
        "entity_id": entity_id,
        "entity_type": entity_type,
        "field_path": field_path,
        "classification": classification,
        "availability": availability,
        "authority_path": authority_path,
        "authority_route": authority_route,
        "authority_kind": authority_kind or authority_route,
        "contract_or_user_need": contract_or_user_need,
        "evidence": sorted(
            (_copy(item) for item in evidence),
            key=lambda item: (
                str(item.get("path") or item.get("reference")),
                str(item.get("role")),
                int(item.get("line_start", 0)),
            ),
        ),
        "dependencies": sorted(set(str(item) for item in dependencies)),
    }
    if unresolved_reason is not None:
        row["unresolved_reason"] = unresolved_reason
    if current_value is not _MISSING:
        row["current_value"] = _copy(current_value)
    return row


def _safe_json(root: Path, logical: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return load_json(_resolve(root, logical)), None
    except (PipelineError, OSError) as exc:
        return None, _normalize_error(root, exc)


def _format_schema_path(parts: Iterable[object]) -> str:
    result = ""
    for part in parts:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += ("." if result else "") + str(part)
    return result or "record"


def _schema_error_details(name: str, record: Mapping[str, Any]) -> list[dict[str, str]]:
    """Read current library schema rules and retain each validation defect."""

    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - library dependency is required
        raise PipelineError("jsonschema is required for metadata assessment") from exc
    schema = load_library_schema(name)
    validator = jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )
    details: list[dict[str, str]] = []
    errors = sorted(
        validator.iter_errors(record),
        key=lambda item: tuple(f"{type(part).__name__}:{part}" for part in item.absolute_path),
    )
    for error in errors:
        parts = list(error.absolute_path)
        classification = "unknown"
        availability = "invalid"
        if error.validator in {"required", "dependentRequired"} and isinstance(error.instance, Mapping):
            missing: dict[str, str] = {}
            if error.validator == "required":
                for field in error.validator_value:
                    if field not in error.instance:
                        missing[field] = f"The current {name} schema requires {field}."
            else:
                for trigger, dependencies in error.validator_value.items():
                    if trigger in error.instance:
                        for field in dependencies:
                            if field not in error.instance:
                                missing[field] = (
                                    f"The current {name} schema requires {field} "
                                    f"when {trigger} is recorded."
                                )
            for field, reason in sorted(missing.items()):
                field_parts = parts + [field]
                details.append(
                    {
                        "field_path": _format_schema_path(field_parts),
                        "classification": "required_missing",
                        "availability": "missing",
                        "reason": reason,
                    }
                )
            continue
        details.append(
            {
                "field_path": _format_schema_path(parts),
                "classification": classification,
                "availability": availability,
                "reason": error.message,
            }
        )
    # JSON Schema emits one error per absent property. Each error also exposes
    # the whole required/dependentRequired rule, so retain each finding once.
    unique = {tuple(sorted(detail.items())): detail for detail in details}
    return list(unique.values())


def _entity_id(kind: str, *parts: object) -> str:
    return f"{kind}:" + "/".join(str(part) for part in parts)


def _linked_entities(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expose declared master and acceptance targets without treating status as acceptance."""

    entities: list[dict[str, Any]] = []
    for master in manifest.get("masters", []):
        if not isinstance(master, Mapping):
            continue
        parts = (master.get("work_id"), master.get("textual_form_id"), master.get("edition_id"))
        entities.append(
            {
                "entity_id": _entity_id("master", *parts),
                "entity_type": "master",
                "stable_id_available": all(isinstance(item, str) for item in parts),
                "work_id": master.get("work_id"),
                "textual_form_id": master.get("textual_form_id"),
                "edition_id": master.get("edition_id"),
                "authority_path": master.get("master_path"),
                "status": master.get("status"),
                "exists": master.get("exists"),
            }
        )
    for acceptance in manifest.get("acceptances", []):
        if not isinstance(acceptance, Mapping):
            continue
        parts = (acceptance.get("work_id"), acceptance.get("textual_form_id"), acceptance.get("edition_id"))
        entities.append(
            {
                "entity_id": _entity_id("acceptance", *parts),
                "entity_type": "acceptance",
                "stable_id_available": all(isinstance(item, str) for item in parts),
                "work_id": acceptance.get("work_id"),
                "textual_form_id": acceptance.get("textual_form_id"),
                "edition_id": acceptance.get("edition_id"),
                "authority_path": acceptance.get("acceptance_path"),
                "status": acceptance.get("status"),
                "exists": acceptance.get("exists"),
            }
        )
    return entities


def _bound_conflict_rows(root: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Report only exact-field conflicts between two bound authority records."""

    findings: list[dict[str, Any]] = []
    definitions = (
        ("work", "work_identity", "works", ("work_id",), ("title",)),
        (
            "acquisition",
            "acquisition",
            "acquisitions",
            ("work_id", "textual_form_id", "edition_id", "acquisition_id"),
            ("provider", "url", "source_sha256"),
        ),
        ("state_target", "state", "state_targets", ("work_id", "target_id"), ("stage",)),
        (
            "master",
            "accepted_tei",
            "masters",
            ("work_id", "textual_form_id", "edition_id"),
            ("status", "sha256"),
        ),
        (
            "acceptance",
            "acceptance",
            "acceptances",
            ("work_id", "textual_form_id", "edition_id"),
            ("status", "promotion_status"),
        ),
    )
    for entity_type, route, collection, key_fields, compared_fields in definitions:
        grouped: dict[tuple[object, ...], list[Mapping[str, Any]]] = defaultdict(list)
        for record in manifest.get(collection, []):
            if not isinstance(record, Mapping):
                continue
            key = tuple(record.get(field) for field in key_fields)
            if not all(isinstance(item, str) for item in key):
                continue
            grouped[key].append(record)
        for key, records in sorted(grouped.items(), key=lambda item: tuple(str(value) for value in item[0])):
            if len(records) < 2:
                continue
            for field in compared_fields:
                values: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
                for record in records:
                    value = record.get(field)
                    if value is None:
                        continue
                    values[json.dumps(value, ensure_ascii=False, sort_keys=True)].append(record)
                if len(values) < 2:
                    continue
                evidence = []
                current_values: dict[str, list[Any]] = defaultdict(list)
                for encoded, rows in sorted(values.items()):
                    value = json.loads(encoded)
                    for row in rows:
                        path_key = {
                            "work": "work_path",
                            "acquisition": "acquisition_path",
                            "state_target": "state_path",
                            "master": "master_path",
                            "acceptance": "acceptance_path",
                        }[entity_type]
                        path = row.get(path_key)
                        if not isinstance(path, str):
                            continue
                        evidence.append(_file_binding(root, path, role=f"{entity_type}-authority"))
                        current_values[path].append(_copy(value))
                findings.append(
                    _finding(
                        entity_id=_entity_id(entity_type, *key),
                        entity_type=entity_type,
                        field_path=field,
                        classification="contradictory",
                        authority_path=None,
                        authority_route=route,
                        contract_or_user_need="one stable binding must not carry two values for the same authoritative field",
                        evidence=evidence,
                        availability="conflict",
                        current_value=current_values,
                        unresolved_reason="two bound authority records provide different values for the same semantic field",
                    )
                )
    return findings


def _work_rows(root: Path, manifest: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    for work in manifest.get("works", []):
        if not isinstance(work, Mapping):
            continue
        work_id = work.get("work_id") if isinstance(work.get("work_id"), str) else None
        work_path = str(work.get("work_path"))
        entity_id = _entity_id("work", work_id) if work_id else _entity_id("work-record", work_path)
        entities.append(
            {
                "entity_id": entity_id,
                "entity_type": "work",
                "stable_id_available": isinstance(work_id, str),
                "work_id": work_id,
                "authority_path": work_path,
                "identity_status": work.get("identity_status"),
            }
        )
        if work.get("identity_status") not in {None, "valid"}:
            findings.append(
                _finding(
                    entity_id=entity_id,
                    entity_type="work",
                    field_path="identity",
                    classification="unknown",
                    authority_path=work_path,
                    authority_route="work_identity",
                    contract_or_user_need="a declared work identity must pass schema and relationship validation before metadata is treated as current",
                    evidence=_evidence_for_path(root, work_path, role="work-identity"),
                    availability="invalid",
                    unresolved_reason="the generated inventory reports an invalid work identity; no replacement identity is inferred",
                )
            )
        raw, error = _safe_json(root, work_path)
        sidecar_evidence = _evidence_for_path(root, work_path, role="work-identity")
        if raw is None:
            findings.append(
                _finding(
                    entity_id=entity_id,
                    entity_type="work",
                    field_path="record",
                    classification="unknown",
                    authority_path=work_path,
                    authority_route="work_identity",
                    contract_or_user_need="work.schema.json must validate before a stable work can enter the library",
                    evidence=sidecar_evidence,
                    availability="invalid",
                    unresolved_reason=(
                        "work sidecar could not be loaded; requiredness was not assessed: "
                        + (error or "unknown load failure")
                    ),
                )
            )
            continue
        if isinstance(raw.get("evidence"), list):
            for reference in raw["evidence"]:
                if isinstance(reference, str):
                    sidecar_evidence.append(
                        _reference_evidence(root, reference, role="work-source-evidence")
                    )
        schema_details = _schema_error_details("work", raw)
        for detail in schema_details:
            findings.append(
                _finding(
                    entity_id=entity_id,
                    entity_type="work",
                    field_path=detail["field_path"],
                    classification=detail["classification"],
                    authority_path=work_path,
                    authority_route="work_identity",
                    contract_or_user_need="work.schema.json defines required identity fields and valid metadata types",
                    evidence=sidecar_evidence,
                    availability=detail["availability"],
                    unresolved_reason=detail["reason"],
                )
            )
        if (
            work.get("identity_status") not in {None, "valid"}
            or bool(schema_details)
        ):
            continue
        creators = raw.get("creators")
        if "creators" in raw and creators is not None and not isinstance(creators, list):
            findings.append(
                _finding(
                    entity_id=entity_id,
                    entity_type="work",
                    field_path="creators",
                    classification="unknown",
                    authority_path=work_path,
                    authority_route="work_identity",
                    contract_or_user_need="creator metadata must validate before it can support attribution",
                    evidence=sidecar_evidence,
                    availability="invalid",
                    unresolved_reason="creators is present with an invalid type; no contributor is inferred",
                )
            )
        elif not isinstance(creators, list) or not creators:
            findings.append(
                _finding(
                    entity_id=entity_id,
                    entity_type="work",
                    field_path="creators",
                    classification="useful_optional_missing",
                    authority_path=work_path,
                    authority_route="work_identity",
                    contract_or_user_need="creator attribution helps users identify, cite, and distinguish works",
                    evidence=sidecar_evidence,
                    availability="not_recorded",
                    unresolved_reason="the work sidecar records no creators; no replacement name is inferred",
                    dependencies=("primary title-page, header, or catalog evidence",),
                )
            )
        forms = raw.get("textual_forms")
        if not isinstance(forms, list):
            if "textual_forms" in raw:
                findings.append(
                    _finding(
                        entity_id=entity_id,
                        entity_type="work",
                        field_path="textual_forms",
                        classification="unknown",
                        authority_path=work_path,
                        authority_route="work_identity",
                        contract_or_user_need="textual_forms must be a validated relationship list before form and edition metadata can be assessed",
                        evidence=sidecar_evidence,
                        availability="invalid",
                        unresolved_reason="textual_forms is present but is not a list; no form identity is inferred",
                    )
                )
            continue
        for form in forms:
            if not isinstance(form, Mapping) or not isinstance(form.get("textual_form_id"), str):
                continue
            form_id = str(form["textual_form_id"])
            form_entity = _entity_id("form", work_id or work_path, form_id)
            form_path = f"library/works/{work_id or '<unidentified>'}/forms/{form_id}"
            entities.append(
                {
                    "entity_id": form_entity,
                    "entity_type": "textual_form",
                    "stable_id_available": all(isinstance(item, str) for item in (work_id, form_id)),
                    "work_id": work_id,
                    "textual_form_id": form_id,
                    "authority_path": form_path,
                }
            )
            for field in ("title", "language", "category"):
                if not form.get(field):
                    findings.append(
                        _finding(
                            entity_id=form_entity,
                            entity_type="textual_form",
                            field_path=field,
                            classification="useful_optional_missing",
                            authority_path=work_path,
                            authority_route="work_identity",
                            contract_or_user_need="textual-form metadata supports citation, filtering, and form distinction",
                            evidence=sidecar_evidence,
                            availability="not_recorded",
                            unresolved_reason="optional textual-form property is not recorded; edition evidence is not copied upward",
                            dependencies=("primary edition or form evidence",),
                        )
                    )
            for edition in form.get("editions", []):
                if not isinstance(edition, Mapping) or not isinstance(edition.get("edition_id"), str):
                    continue
                edition_id = str(edition["edition_id"])
                edition_entity = _entity_id("edition", work_id or work_path, form_id, edition_id)
                edition_path = f"library/works/{work_id or '<unidentified>'}/forms/{form_id}/editions/{edition_id}"
                entities.append(
                    {
                        "entity_id": edition_entity,
                        "entity_type": "edition",
                        "stable_id_available": all(
                            isinstance(item, str) for item in (work_id, form_id, edition_id)
                        ),
                        "work_id": work_id,
                        "textual_form_id": form_id,
                        "edition_id": edition_id,
                        "authority_path": edition_path,
                    }
                )
                for field in ("language", "category"):
                    if not edition.get(field):
                        findings.append(
                            _finding(
                                entity_id=edition_entity,
                                entity_type="edition",
                                field_path=field,
                                classification="useful_optional_missing",
                                authority_path=work_path,
                                authority_route="work_identity",
                                contract_or_user_need="edition metadata supports filtering and release configuration",
                                evidence=sidecar_evidence,
                                availability="not_recorded",
                                unresolved_reason="optional edition property is not recorded; no category or language is inferred",
                                dependencies=("primary edition evidence",),
                            )
                        )
    return findings, entities


def _acquisition_rows(root: Path, manifest: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    for acquisition in manifest.get("acquisitions", []):
        if not isinstance(acquisition, Mapping):
            continue
        work_id = acquisition.get("work_id")
        form_id = acquisition.get("textual_form_id")
        edition_id = acquisition.get("edition_id")
        acquisition_id = acquisition.get("acquisition_id")
        path = str(acquisition.get("acquisition_path"))
        parts = (work_id, form_id, edition_id, acquisition_id)
        entity_id = (
            _entity_id("acquisition", *parts)
            if all(isinstance(item, str) for item in parts)
            else _entity_id("acquisition-record", path)
        )
        entities.append(
            {
                "entity_id": entity_id,
                "entity_type": "acquisition",
                "stable_id_available": all(
                    isinstance(item, str)
                    for item in (work_id, form_id, edition_id, acquisition_id)
                ),
                "work_id": work_id,
                "textual_form_id": form_id,
                "edition_id": edition_id,
                "acquisition_id": acquisition_id,
                "authority_path": path,
                "identity_status": acquisition.get("identity_status"),
            }
        )
        raw, error = _safe_json(root, path)
        sidecar_evidence = _evidence_for_path(root, path, role="acquisition")
        if raw is None:
            findings.append(
                _finding(
                    entity_id=entity_id,
                    entity_type="acquisition",
                    field_path="record",
                    classification="unknown",
                    authority_path=path,
                    authority_route="acquisition",
                    contract_or_user_need="acquisition.schema.json must validate exact source provenance and retained-file identity",
                    evidence=sidecar_evidence,
                    availability="invalid",
                    unresolved_reason=(
                        "acquisition sidecar could not be loaded; requiredness was not assessed: "
                        + (error or "unknown load failure")
                    ),
                )
            )
            continue
        schema_details = _schema_error_details("acquisition", raw)
        for detail in schema_details:
            findings.append(
                _finding(
                    entity_id=entity_id,
                    entity_type="acquisition",
                    field_path=detail["field_path"],
                    classification=detail["classification"],
                    authority_path=path,
                    authority_route="acquisition",
                    contract_or_user_need="acquisition.schema.json defines required source provenance and retained-file types",
                    evidence=sidecar_evidence,
                    availability=detail["availability"],
                    unresolved_reason=detail["reason"],
                )
            )
        if acquisition.get("evidence_status") not in {None, "valid"}:
            findings.append(
                _finding(
                    entity_id=entity_id,
                    entity_type="acquisition",
                    field_path="evidence",
                    classification="unknown",
                    authority_path=path,
                    authority_route="acquisition",
                    contract_or_user_need="retained source bytes and hashes must validate before acquisition evidence is current",
                    evidence=sidecar_evidence,
                    availability="invalid",
                    current_value={"evidence_status": acquisition.get("evidence_status")},
                    unresolved_reason="the generated inventory reports invalid or unavailable retained-file evidence",
                )
            )
        if acquisition.get("source_availability") not in {None, "available"}:
            findings.append(
                _finding(
                    entity_id=entity_id,
                    entity_type="acquisition",
                    field_path="source_availability",
                    classification="unknown",
                    authority_path=path,
                    authority_route="acquisition",
                    contract_or_user_need="source availability must be known before an acquisition can support a release decision",
                    evidence=sidecar_evidence,
                    availability="unavailable",
                    current_value={"source_availability": acquisition.get("source_availability")},
                    unresolved_reason="the generated inventory reports unavailable source evidence",
                )
            )
        if acquisition.get("identity_status") not in {None, "valid"}:
            findings.append(
                _finding(
                    entity_id=entity_id,
                    entity_type="acquisition",
                    field_path="identity",
                    classification="unknown",
                    authority_path=path,
                    authority_route="acquisition",
                    contract_or_user_need="acquisition identity must remain bound to one declared edition and filename",
                    evidence=sidecar_evidence,
                    availability="invalid",
                    current_value={"identity_status": acquisition.get("identity_status")},
                    unresolved_reason="the generated inventory reports a sidecar/path/declaration relationship problem; no conflicting authority value is inferred",
                )
            )
        retained_value = raw.get("retained_files")
        authority_valid = (
            acquisition.get("identity_status") in {None, "valid"}
            and not schema_details
        )
        if not authority_valid:
            # Required properties missing from a readable sidecar were already
            # reported above.  Do not assess optional metadata on an invalid
            # authority or silently promote a malformed retained-file list.
            continue
        for field in ("accessed_at", "rights"):
            if not raw.get(field):
                findings.append(
                    _finding(
                        entity_id=entity_id,
                        entity_type="acquisition",
                        field_path=field,
                        classification="useful_optional_missing",
                        authority_path=path,
                        authority_route="acquisition",
                        contract_or_user_need=(
                            "exact acquisition timing supports reproducibility and audit" if field == "accessed_at"
                            else "rights evidence supports release-profile and legal-use decisions"
                        ),
                        evidence=sidecar_evidence,
                        availability="not_recorded",
                        unresolved_reason=f"{field} is absent; the report does not infer a date or rights label",
                        dependencies=("provider or source rights/access evidence",),
                    )
                )
        source_fields = ("source_path", "source_bytes", "source_sha256", "source_scope")
        present_source_fields = [field for field in source_fields if raw.get(field) is not None]
        if not present_source_fields:
            findings.append(
                _finding(
                    entity_id=entity_id,
                    entity_type="acquisition",
                    field_path="source",
                    classification="useful_optional_missing",
                    authority_path=path,
                    authority_route="acquisition",
                    contract_or_user_need="an original-source group helps trace a retained file to its upstream scope",
                    evidence=sidecar_evidence,
                    availability="not_recorded",
                    unresolved_reason="no distinct original-source binding is recorded; retained-file evidence remains separate",
                    dependencies=("provider source record, original bytes, and exact source scope",),
                )
            )
        elif len(present_source_fields) != len(source_fields):
            findings.append(
                _finding(
                    entity_id=entity_id,
                    entity_type="acquisition",
                    field_path="source",
                    classification="useful_optional_missing",
                    authority_path=path,
                    authority_route="acquisition",
                    contract_or_user_need="dependent source fields must form one exact upstream binding",
                    evidence=sidecar_evidence,
                    availability="incomplete",
                    current_value={"present_fields": present_source_fields},
                    unresolved_reason="the optional source group is incomplete; no upstream value is inferred",
                )
            )
        retained_files = raw.get("retained_files")
        if not isinstance(retained_files, list):
            retained_files = []
        for index, member in enumerate(retained_files):
            if not isinstance(member, Mapping):
                findings.append(
                    _finding(
                        entity_id=entity_id,
                        entity_type="acquisition",
                        field_path=f"retained_files[{index}]",
                        classification="unknown",
                        authority_path=path,
                        authority_route="acquisition",
                        contract_or_user_need="retained-file entries must be objects with exact path, byte, hash, and media fields",
                        evidence=sidecar_evidence,
                        availability="invalid",
                        unresolved_reason="retained-file entry is not an object; no source identity is inferred",
                    )
                )
                continue
            retained_path = member.get("path")
            if isinstance(retained_path, str):
                retained_binding = _file_binding(root, retained_path, role="retained-source")
                mismatch = []
                if not retained_binding.get("exists"):
                    mismatch.append("retained file is missing or unreadable")
                if (
                    isinstance(member.get("bytes"), int)
                    and retained_binding.get("bytes") != member["bytes"]
                ):
                    mismatch.append("retained byte count differs from the sidecar")
                if (
                    isinstance(member.get("sha256"), str)
                    and retained_binding.get("sha256") != member["sha256"]
                ):
                    mismatch.append("retained SHA-256 differs from the sidecar")
                if mismatch:
                    findings.append(
                        _finding(
                            entity_id=entity_id,
                            entity_type="acquisition",
                            field_path=f"retained_files[{index}].binding",
                            classification="unknown",
                            authority_path=path,
                            authority_route="acquisition",
                            contract_or_user_need="retained-file bytes and hashes must match the acquisition authority",
                            evidence=[sidecar_evidence[0], retained_binding],
                            availability="invalid",
                            current_value={
                                "declared_bytes": member.get("bytes"),
                                "actual_bytes": retained_binding.get("bytes"),
                                "declared_sha256": member.get("sha256"),
                                "actual_sha256": retained_binding.get("sha256"),
                            },
                            unresolved_reason="; ".join(mismatch),
                        )
                    )
    return findings, entities


def _missing_declared_acquisitions(
    root: Path, manifest: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep declared acquisition targets visible when their sidecar is absent."""

    findings: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    present = {
        (
            item.get("work_id"),
            item.get("textual_form_id"),
            item.get("edition_id"),
            item.get("acquisition_id"),
        )
        for item in manifest.get("acquisitions", [])
        if isinstance(item, Mapping)
    }
    candidates: set[tuple[str, str, str, str]] = set()
    for edition in manifest.get("editions", []):
        if not isinstance(edition, Mapping):
            continue
        parts = (
            edition.get("work_id"),
            edition.get("textual_form_id"),
            edition.get("edition_id"),
            edition.get("acquisition_id"),
        )
        if all(isinstance(item, str) for item in parts):
            candidates.add(parts)  # type: ignore[arg-type]
    for work in manifest.get("works", []):
        if not isinstance(work, Mapping) or not isinstance(work.get("work_id"), str):
            continue
        work_id = work["work_id"]
        work_path = work.get("work_path")
        if not isinstance(work_path, str):
            continue
        raw, _ = _safe_json(root, work_path)
        if not isinstance(raw, Mapping):
            continue
        for form in raw.get("textual_forms", []):
            if not isinstance(form, Mapping) or not isinstance(form.get("textual_form_id"), str):
                continue
            form_id = form["textual_form_id"]
            for edition in form.get("editions", []):
                if not isinstance(edition, Mapping) or not isinstance(edition.get("edition_id"), str):
                    continue
                edition_id = edition["edition_id"]
                for acquisition_id in edition.get("acquisition_ids", []):
                    if isinstance(acquisition_id, str):
                        candidates.add((work_id, form_id, edition_id, acquisition_id))
    for work_id, form_id, edition_id, acquisition_id in sorted(candidates):
        key = (work_id, form_id, edition_id, acquisition_id)
        if key in present:
            continue
        path = (
            f"library/works/{work_id}/forms/{form_id}/editions/{edition_id}/"
            f"acquisitions/{acquisition_id}.json"
        )
        entity_id = _entity_id("acquisition", *key)
        entities.append(
            {
                "entity_id": entity_id,
                "entity_type": "acquisition",
                "stable_id_available": True,
                "work_id": work_id,
                "textual_form_id": form_id,
                "edition_id": edition_id,
                "acquisition_id": acquisition_id,
                "authority_path": path,
                "identity_status": "missing",
            }
        )
        findings.append(
            _finding(
                entity_id=entity_id,
                entity_type="acquisition",
                field_path="record",
                classification="unknown",
                authority_path=path,
                authority_route="acquisition",
                contract_or_user_need="a declared acquisition target needs an acquisition sidecar before source evidence can be assessed",
                evidence=_evidence_for_path(root, path, role="acquisition"),
                availability="missing",
                unresolved_reason="the work or inventory declares an acquisition identity but its sidecar is absent",
            )
        )
    return findings, entities


def _state_rows(root: Path, manifest: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    present_work_ids: set[str] = set()
    for state in manifest.get("states", []):
        if isinstance(state, Mapping):
            if isinstance(state.get("work_id"), str):
                present_work_ids.add(state["work_id"])
            state_path = state.get("state_path")
            state_entity_id = (
                _entity_id("state", state.get("work_id"))
                if isinstance(state.get("work_id"), str)
                else _entity_id("state-record", state_path)
            )
            entities.append(
                {
                    "entity_id": state_entity_id,
                    "entity_type": "state",
                    "stable_id_available": isinstance(state.get("work_id"), str),
                    "work_id": state.get("work_id"),
                    "authority_path": state_path,
                    "status": state.get("status"),
                }
            )
            raw, error = _safe_json(root, str(state_path))
            state_evidence = _evidence_for_path(root, str(state_path), role="state")
            if raw is None and state.get("status") in {None, "valid"}:
                findings.append(
                    _finding(
                        entity_id=state_entity_id,
                        entity_type="state",
                        field_path="record",
                        classification="unknown",
                        authority_path=state_path,
                        authority_route="state",
                        contract_or_user_need="state.schema.json must be readable before workflow availability can be interpreted",
                        evidence=state_evidence,
                        availability="invalid",
                        unresolved_reason=(
                            "state sidecar could not be loaded; requiredness was not assessed: "
                            + (error or "unknown load failure")
                        ),
                    )
                )
            elif raw is not None:
                for detail in _schema_error_details("state", raw):
                    findings.append(
                        _finding(
                            entity_id=state_entity_id,
                            entity_type="state",
                            field_path=detail["field_path"],
                            classification=detail["classification"],
                            authority_path=state_path,
                            authority_route="state",
                            contract_or_user_need="state.schema.json defines required workflow fields and target types",
                            evidence=state_evidence,
                            availability=detail["availability"],
                            unresolved_reason=detail["reason"],
                        )
                    )
            if state.get("status") not in {None, "valid"}:
                findings.append(
                    _finding(
                        entity_id=state_entity_id,
                        entity_type="state",
                        field_path="record",
                        classification="unknown",
                        authority_path=state_path,
                        authority_route="state",
                        contract_or_user_need="state sidecars must validate before workflow availability can be interpreted",
                        evidence=_evidence_for_path(root, str(state_path), role="state"),
                        availability="invalid",
                        unresolved_reason="the generated inventory reports an invalid state sidecar; no stage is inferred",
                    )
                )
    for work in manifest.get("works", []):
        if not isinstance(work, Mapping) or not isinstance(work.get("work_id"), str):
            continue
        work_id = work["work_id"]
        if work_id in present_work_ids:
            continue
        path = f"library/works/{work_id}/state.json"
        entity_id = _entity_id("state", work_id)
        entities.append(
            {
                "entity_id": entity_id,
                "entity_type": "state",
                "stable_id_available": True,
                "work_id": work_id,
                "authority_path": path,
                "status": "missing",
            }
        )
        findings.append(
            _finding(
                entity_id=entity_id,
                entity_type="state",
                field_path="record",
                classification="unknown",
                authority_path=path,
                authority_route="state",
                contract_or_user_need="each declared work needs a validated state sidecar to expose target freshness and availability",
                evidence=_evidence_for_path(root, path, role="state"),
                availability="missing",
                unresolved_reason="the declared work has no state sidecar; stage and target status are not inferred",
            )
        )
    for target in manifest.get("state_targets", []):
        if not isinstance(target, Mapping):
            continue
        path = str(target.get("state_path"))
        target_parts = (target.get("work_id"), target.get("target_id"))
        entity_id = (
            _entity_id("state-target", *target_parts)
            if all(isinstance(item, str) for item in target_parts)
            else _entity_id("state-target-record", path)
        )
        entities.append(
            {
                "entity_id": entity_id,
                "entity_type": "state_target",
                "stable_id_available": all(isinstance(target.get(key), str) for key in ("work_id", "target_id")),
                "work_id": target.get("work_id"),
                "target_id": target.get("target_id"),
                "target_type": target.get("target_type"),
                "authority_path": path,
                "status": target.get("status"),
            }
        )
        if target.get("status") not in {None, "valid"}:
            findings.append(
                _finding(
                    entity_id=entity_id,
                    entity_type="state_target",
                    field_path="target",
                    classification="unknown",
                    authority_path=path,
                    authority_route="state",
                    contract_or_user_need="state targets must bind an explicit stage to an existing acquisition or edition",
                    evidence=_evidence_for_path(root, path, role="state"),
                    availability="invalid",
                    current_value={"status": target.get("status"), "stage": target.get("stage")},
                    unresolved_reason="state relationship validation did not pass; no contradiction is inferred without two bound state authorities",
                )
            )
    return findings, entities


def _tei_header(root: Path, logical: str) -> dict[str, Any] | None:
    try:
        tree = ET.parse(_resolve(root, logical))
    except (ET.ParseError, OSError, PipelineError):
        return None
    title_nodes = tree.findall(".//tei:titleStmt/tei:title", _TEI_NS)
    author_nodes = tree.findall(".//tei:titleStmt/tei:author", _TEI_NS)
    titles = [" ".join("".join(node.itertext()).split()) for node in title_nodes]
    return {
        "title": titles[0] if titles else None,
        "authors": sorted(
            {" ".join("".join(node.itertext()).split()) for node in author_nodes if "".join(node.itertext()).strip()}
        ),
    }


def _tei_rows(root: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    work_by_id = {
        item.get("work_id"): item
        for item in manifest.get("works", [])
        if isinstance(item, Mapping) and isinstance(item.get("work_id"), str)
    }
    for edition in manifest.get("editions", []):
        if not isinstance(edition, Mapping) or edition.get("master_status") != "accepted":
            # An absent/unaccepted master is a pipeline availability fact, not
            # proof that the TEI header has missing metadata.
            continue
        work_id = edition.get("work_id")
        work = work_by_id.get(work_id)
        if not isinstance(work, Mapping):
            continue
        master_path = str(edition.get("master_path"))
        header = _tei_header(root, master_path)
        if header is None:
            entity_id = _entity_id("edition", work_id, edition.get("textual_form_id"), edition.get("edition_id"))
            findings.append(
                _finding(
                    entity_id=entity_id,
                    entity_type="accepted_tei",
                    field_path="record",
                    classification="unknown",
                    authority_path=master_path,
                    authority_route="accepted_tei",
                    contract_or_user_need="an accepted TEI master must remain parseable before its header can be assessed",
                    evidence=_evidence_for_path(root, master_path, role="accepted-tei"),
                    availability="invalid",
                    unresolved_reason="accepted master could not be parsed; metadata comparison was not attempted",
                )
            )
            continue
        # Work titles and edition/TEI titles are distinct contract fields, and
        # contributor roles may legitimately vary.  A string difference is
        # therefore retained as an observation only, never as a repair finding.
    return findings


def _tei_observations(root: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expose accepted-header observations without inventing required fields."""

    rows: list[dict[str, Any]] = []
    for edition in manifest.get("editions", []):
        if not isinstance(edition, Mapping) or edition.get("master_status") != "accepted":
            continue
        work_id = edition.get("work_id")
        form_id = edition.get("textual_form_id")
        edition_id = edition.get("edition_id")
        master_path = edition.get("master_path")
        if not all(isinstance(item, str) for item in (work_id, form_id, edition_id, master_path)):
            continue
        entity_id = _entity_id("edition", work_id, form_id, edition_id)
        header = _tei_header(root, master_path)
        if header is None:
            rows.append(
                {
                    "entity_id": entity_id,
                    "authority_path": master_path,
                    "status": "invalid",
                    "fields": {},
                    "evidence": _evidence_for_path(root, master_path, role="accepted-tei"),
                }
            )
            continue
        rows.append(
            {
                "entity_id": entity_id,
                "authority_path": master_path,
                "status": "observed",
                "fields": {
                    "teiHeader.title": header.get("title"),
                    "teiHeader.author": header.get("authors", []),
                },
                "availability": {
                    "teiHeader.title": "present" if header.get("title") else "not_recorded",
                    "teiHeader.author": "present" if header.get("authors") else "not_recorded",
                },
                "evidence": _evidence_for_path(root, master_path, role="accepted-tei"),
            }
        )
    return rows


def _pipeline_rows(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for edition in manifest.get("editions", []):
        if not isinstance(edition, Mapping):
            continue
        if (
            edition.get("master_status") == "accepted"
            and edition.get("acceptance_status") == "promoted"
            and edition.get("state_stage") == "accepted"
            and edition.get("status") in {"included", "warned"}
        ):
            status = "accepted"
        elif edition.get("acquisition_stage") == "acquired" and edition.get("master_status") in {"absent", "present-unbound"}:
            status = "acquired_no_master"
        elif edition.get("dimensions", {}).get("source_availability") in {"unacquired", "missing", "invalid"}:
            status = "source_unavailable"
        else:
            status = "not_recorded"
        blocked_by: list[str] = []
        if edition.get("master_status") != "accepted":
            blocked_by.append("accepted TEI master is not bound")
        if edition.get("acceptance_status") != "promoted":
            blocked_by.append("PIPE-004 acceptance is not promoted")
        if edition.get("state_stage") != "accepted":
            blocked_by.append("edition state target is not accepted")
        rows.append(
            {
                "entity_id": _entity_id("edition", edition.get("work_id"), edition.get("textual_form_id"), edition.get("edition_id")),
                "work_id": edition.get("work_id"),
                "textual_form_id": edition.get("textual_form_id"),
                "edition_id": edition.get("edition_id"),
                "pipeline_status": status,
                "source_availability": edition.get("dimensions", {}).get("source_availability"),
                "acquisition_stage": edition.get("acquisition_stage"),
                "edition_stage": edition.get("state_stage"),
                "master_status": edition.get("master_status"),
                "acceptance_status": edition.get("acceptance_status"),
                "blocked_by": blocked_by,
                "authority_paths": sorted(
                    path for path in (edition.get("acquisition_path"), edition.get("master_path"), edition.get("acceptance_path")) if path
                ),
            }
        )
    return rows


def _expected_lead_ids(root: Path, manifest: Mapping[str, Any]) -> tuple[list[str], str | None]:
    expected = sorted(
        str(item.get("lead_id"))
        for item in manifest.get("research_leads", [])
        if isinstance(item, Mapping) and isinstance(item.get("lead_id"), str)
    )
    if expected:
        return expected, None
    queue_path = root / "library/acquisition-leads.jsonl"
    if queue_path.is_file():
        try:
            records = []
            for line in queue_path.read_text(encoding="utf-8").splitlines():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    # Legacy malformed-row accounting still uses manifest authority.
                    # A detected migrated queue must pass its versioned validator.
                    continue
            if any(isinstance(record, dict) and record.get("schema_version") == "2.1" for record in records):
                migrated = load_acquisition_leads(queue_path, root=root)
                return sorted(record["lead_id"] for record in migrated), None
        except (PipelineError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            return [], _normalize_error(root, exc)
    try:
        imported = manifest_research(root / "research" / "MANIFEST.md", root=root)
    except PipelineError as exc:
        return [], _normalize_error(root, exc)
    return sorted(
        str(item["lead_id"])
        for item in imported.get("leads", [])
        if isinstance(item, Mapping) and isinstance(item.get("lead_id"), str)
    ), None


def _read_leads(root: Path, manifest: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    path = root / "library" / "acquisition-leads.jsonl"
    rows: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    seen: dict[str, list[int]] = defaultdict(list)
    if not path.is_file():
        expected_ids, expected_error = _expected_lead_ids(root, manifest)
        issues.append({"code": "missing-research-leads", "path": "library/acquisition-leads.jsonl", "message": "research lead queue is missing"})
        if expected_error:
            issues.append({"code": "invalid-research-manifest", "path": "research/MANIFEST.md", "message": expected_error})
        return rows, {
            "expected": len(expected_ids),
            "reported": 0,
            "unique": 0,
            "all_accounted": False,
            "missing_ids": expected_ids,
            "unexpected_ids": [],
            "duplicate_ids": [],
            "validation_error": "research lead queue is missing",
        }, issues
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            issues.append({"code": "invalid-lead-json", "path": "library/acquisition-leads.jsonl", "line": line_number, "message": str(exc)})
            continue
        if not isinstance(value, dict):
            issues.append({"code": "invalid-lead-record", "path": "library/acquisition-leads.jsonl", "line": line_number, "message": "lead must be an object"})
            continue
        lead_id = value.get("lead_id")
        if isinstance(lead_id, str):
            seen[lead_id].append(line_number)
        row = _copy(value)
        row["line_number"] = line_number
        row["stable_work_id"] = (
            value.get("work_id")
            if value.get("disposition") == "promoted" and isinstance(value.get("work_id"), str)
            else None
        )
        row["identity_status"] = "resolved" if row["stable_work_id"] else "unresolved"
        row["stable_id_available"] = isinstance(lead_id, str)
        rows.append(row)
    duplicate_ids = sorted(lead_id for lead_id, lines in seen.items() if len(lines) > 1)
    for lead_id in duplicate_ids:
        issues.append({"code": "duplicate-lead-id", "path": "library/acquisition-leads.jsonl", "lead_id": lead_id, "message": f"lead_id occurs on lines {seen[lead_id]}"})
    validation_error = None
    try:
        validated = load_acquisition_leads(path, root=root)
    except PipelineError as exc:
        validation_error = _normalize_error(root, exc)
        issues.append({"code": "invalid-research-leads", "path": "library/acquisition-leads.jsonl", "message": validation_error})
    else:
        if len(validated) != len(rows):
            issues.append({"code": "lead-accounting-mismatch", "path": "library/acquisition-leads.jsonl", "message": "validated lead count differs from parsed line count"})
    expected_ids, expected_error = _expected_lead_ids(root, manifest)
    if expected_error:
        issues.append(
            {
                "code": "invalid-research-manifest",
                "path": "research/MANIFEST.md",
                "message": expected_error,
            }
        )
    reported_ids = sorted(str(row.get("lead_id")) for row in rows if isinstance(row.get("lead_id"), str))
    accounting = {
        "expected": len(expected_ids),
        "reported": len(rows),
        "unique": len(set(reported_ids)),
        "all_accounted": not issues and reported_ids == expected_ids,
        "missing_ids": sorted(set(expected_ids) - set(reported_ids)),
        "unexpected_ids": sorted(set(reported_ids) - set(expected_ids)),
        "duplicate_ids": duplicate_ids,
        "validation_error": validation_error,
    }
    return rows, accounting, issues


def _lead_rows(root: Path, manifest: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    rows, accounting, issues = _read_leads(root, manifest)
    findings: list[dict[str, Any]] = []
    lead_entities: list[dict[str, Any]] = []
    for row in rows:
        lead_id = row.get("lead_id")
        lead_entity = _entity_id("lead", lead_id) if isinstance(lead_id, str) else None
        evidence_value = row.get("evidence")
        evidence = []
        if isinstance(evidence_value, Mapping) and isinstance(evidence_value.get("path"), str):
            evidence_item = _reference_evidence(
                root, evidence_value["path"], role="research-lead-evidence"
            )
            for key in ("line_start", "line_end"):
                if key in evidence_value:
                    evidence_item[key] = evidence_value[key]
            if isinstance(evidence_value.get("sha256"), str):
                evidence_item["declared_sha256"] = evidence_value["sha256"]
            evidence.append(evidence_item)
        lead_entities.append(
            {
                "entity_id": lead_entity,
                "entity_type": "research_lead",
                "stable_id_available": lead_entity is not None,
                "lead_id": lead_id,
                "stable_work_id": row.get("stable_work_id"),
                "identity_status": row.get("identity_status"),
                "disposition": row.get("disposition"),
                "acquisition_intent": row.get("acquisition_intent"),
                "columns": _copy(row.get("columns", [])),
                "raw_record": _copy(
                    {
                        key: value
                        for key, value in row.items()
                        if key not in {"line_number", "stable_work_id", "identity_status", "stable_id_available"}
                    }
                ),
                "evidence": evidence,
                "line_number": row.get("line_number"),
            }
        )
        if evidence and (
            not evidence[0].get("exists")
            or (
                isinstance(evidence[0].get("declared_sha256"), str)
                and evidence[0].get("sha256") != evidence[0].get("declared_sha256")
            )
        ):
            findings.append(
                _finding(
                    entity_id=lead_entity,
                    entity_type="research_lead",
                    field_path="evidence",
                    classification="unknown",
                    authority_path="library/acquisition-leads.jsonl",
                    authority_route="research_lead",
                    contract_or_user_need="each research claim needs a current, exact manifest evidence binding",
                    evidence=evidence,
                    availability="invalid",
                    unresolved_reason="lead evidence is missing, unreadable, or has a stale hash",
                )
            )
        if not row.get("stable_work_id") and isinstance(lead_id, str):
            findings.append(
                _finding(
                    entity_id=lead_entity,
                    entity_type="research_lead",
                    field_path="work_id",
                    classification="unknown",
                    authority_path="library/acquisition-leads.jsonl",
                    authority_route="research_lead",
                    contract_or_user_need="stable work identity is required before a research claim can join the declared library",
                    evidence=evidence,
                    availability="unresolved",
                    unresolved_reason="the lead preserves a research claim but has no evidenced stable work_id; no identity is minted",
                    dependencies=("primary bibliographic evidence that binds the claim to one work",),
                )
            )
    return rows, findings, accounting, lead_entities + issues


def _batches(findings: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for finding in findings:
        groups[
            (
                str(finding["authority_route"]),
                str(finding["field_path"]),
                str(finding["classification"]),
            )
        ].append(finding)
    result: list[dict[str, Any]] = []
    for (route, field_path, classification), rows in sorted(groups.items()):
        targets = sorted({str(row["entity_id"]) for row in rows if row.get("entity_id")})
        evidence = sorted(
            {
                str(item.get("reference") or item.get("path"))
                for row in rows
                for item in row.get("evidence", [])
                if isinstance(item, Mapping)
            }
        )
        dependencies = sorted(
            {
                str(item)
                for row in rows
                for item in row.get("dependencies", [])
            }
        )
        batch_kind = (
            "investigation"
            if classification in {"unknown", "useful_optional_missing"}
            else "objective-correction-review"
        )
        next_action = {
            "unknown": "obtain or review primary evidence before deciding whether a value is knowable",
            "useful_optional_missing": "collect optional source evidence only if the user need justifies it",
            "required_missing": "validate the named authority and supply an exact evidenced value before repair",
            "contradictory": "compare the bound authorities and obtain a curator decision before repair",
        }[classification]
        result.append(
            {
                "batch_id": f"batch-{_slug(route)}-{_slug(field_path)}-{_slug(classification)}",
                "batch_kind": batch_kind,
                "authority_route": route,
                "field_path": field_path,
                "classification": classification,
                "finding_ids": sorted(str(row["finding_id"]) for row in rows),
                "targets": targets,
                "authority_targets": sorted(
                    {str(row["authority_path"]) for row in rows if row.get("authority_path")}
                ),
                "observed_evidence": evidence,
                "required_evidence_before_correction": dependencies,
                "contract_or_user_needs": sorted(
                    {
                        str(row["contract_or_user_need"])
                        for row in rows
                        if row.get("contract_or_user_need")
                    }
                ),
                "ready_for_repair": False,
                "proposed_replacement": None,
                "next_action": next_action,
            }
        )
    return result


def _load_inventory(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    try:
        snapshot = _build_snapshot(root)
        return snapshot["manifest"], [], snapshot
    except PipelineError as exc:
        # A fresh checked-in PIPE-005 manifest remains useful for diagnosing a
        # malformed current input, but the degraded state must be visible.
        manifest_path = Path(root) / "library" / "corpus-manifest.json"
        if manifest_path.is_file():
            try:
                return load_json(manifest_path), [
                    {"code": "inventory-rebuild-failed", "path": "library/corpus-manifest.json", "message": _normalize_error(root, exc)}
                ], None
            except PipelineError:
                pass
        raise


def _portable_issue(root: Path, issue: Mapping[str, Any]) -> dict[str, Any]:
    result = _copy(issue)
    for key in ("message", "path"):
        value = result.get(key)
        if isinstance(value, str):
            result[key] = _normalize_error(root, value)
    return result


def _portable_view_check(root: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    result = _copy(value)
    reasons = []
    known_views = (
        "library/corpus-manifest.json",
        "library/corpus-manifest.md",
        "reports/library/project-status.json",
        "reports/library/acquisition-queue.json",
    )
    for reason in result.get("reasons", []):
        portable = _normalize_error(root, reason)
        for logical in known_views:
            if logical in portable:
                prefix = portable.split(":", 1)[0]
                if prefix == "generated view is missing":
                    portable = f"{prefix}: {logical}"
                break
        reasons.append(portable)
    result["reasons"] = sorted(set(reasons))
    return result


def _expected_pipeline_absence(manifest: Mapping[str, Any], issue: Mapping[str, Any]) -> bool:
    if issue.get("code") != "missing-input" or not isinstance(issue.get("path"), str):
        return False
    path = issue["path"]
    return any(
        isinstance(edition, Mapping)
        and path in {edition.get("master_path"), edition.get("acceptance_path")}
        for edition in manifest.get("editions", [])
    )


def build_report(
    root: Path,
    known_library_catalog: Path | None = None,
    legacy_catalog: Path | None = None,
) -> dict[str, Any]:
    """Build the deterministic report without modifying any authority."""

    root = Path(root).resolve()
    if (known_library_catalog is None) != (legacy_catalog is None):
        raise PipelineError(
            "known_library_catalog and legacy_catalog must be selected together for the opt-in assessment"
        )
    manifest, inventory_issues, snapshot = _load_inventory(root)
    work_findings, work_entities = _work_rows(root, manifest)
    acquisition_findings, acquisition_entities = _acquisition_rows(root, manifest)
    missing_acquisition_findings, missing_acquisition_entities = _missing_declared_acquisitions(root, manifest)
    state_findings, state_entities = _state_rows(root, manifest)
    tei_findings = _tei_rows(root, manifest)
    tei_observations = _tei_observations(root, manifest)
    conflict_findings = _bound_conflict_rows(root, manifest)
    lead_rows, lead_findings, lead_accounting, lead_tail = _lead_rows(root, manifest)
    lead_entities = [item for item in lead_tail if isinstance(item, Mapping) and item.get("entity_type") == "research_lead"]
    lead_issues = [item for item in lead_tail if isinstance(item, Mapping) and item.get("code")]
    findings = sorted(
        work_findings
        + acquisition_findings
        + missing_acquisition_findings
        + state_findings
        + tei_findings
        + conflict_findings
        + lead_findings,
        key=lambda item: str(item["finding_id"]),
    )
    pipeline_rows = _pipeline_rows(manifest)
    try:
        view_check = _portable_view_check(root, check_library_views(root, root, snapshot=snapshot))
    except (PipelineError, OSError) as exc:
        view_check = {"fresh": None, "reasons": [_normalize_error(root, exc)]}
    inputs = _copy(manifest.get("freshness", {}).get("inputs", []))
    counts = Counter(str(item["classification"]) for item in findings)
    pipeline_counts = Counter(str(item["pipeline_status"]) for item in pipeline_rows)
    all_entities = sorted(
        work_entities
        + acquisition_entities
        + missing_acquisition_entities
        + state_entities
        + lead_entities
        + _linked_entities(manifest),
        key=lambda item: (str(item.get("entity_type")), str(item.get("entity_id")), str(item.get("authority_path"))),
    )
    manifest_issues = [
        _portable_issue(root, item)
        for item in manifest.get("issues", [])
        if isinstance(item, Mapping)
    ]
    issues = sorted(
        [_portable_issue(root, item) for item in inventory_issues]
        + manifest_issues
        + [_portable_issue(root, item) for item in lead_issues],
        key=lambda item: (str(item.get("path")), str(item.get("code")), str(item.get("line"))),
    )
    blocking_manifest_issues = [
        issue for issue in manifest_issues if not _expected_pipeline_absence(manifest, issue)
    ]
    blocking_findings = [
        item
        for item in findings
        if item.get("availability") in {"invalid", "missing", "unavailable"}
    ]
    declared_complete = (
        not inventory_issues
        and not blocking_manifest_issues
        and not blocking_findings
        and bool(lead_accounting.get("all_accounted"))
    )
    known_library = None
    if known_library_catalog is not None and legacy_catalog is not None:
        known_library = _known_library_assessment(
            root,
            manifest,
            lead_rows,
            Path(known_library_catalog),
            Path(legacy_catalog),
        )
    scope = {
        "status": "declared-library-tree-plus-research-leads",
        "declared_coverage": "complete" if declared_complete else "incomplete",
        "historical_coverage": "unassessed",
        "blocking_finding_ids": sorted(str(item["finding_id"]) for item in blocking_findings),
        "library_authority": "library/works/**/work.json and linked acquisition, state, master, and acceptance sidecars",
        "research_authority": "research/MANIFEST.md plus library/acquisition-leads.jsonl",
        "historical_holdings": "not-assessed",
        "historical_holdings_reason": "raw, data, and ir holdings without a declared library identity are outside this report authority",
        "excluded_populations": [
            "unregistered historical raw/data/ir holdings",
            "WorkCatalog imports and inferred identities",
            "generated views treated as metadata authority",
            "rights clearance and publication authorization decisions",
        ],
    }
    if known_library is not None:
        scope.update(
            {
                "status": "known-library-catalog-plus-declared-library-tree-plus-research-leads",
                "known_library_catalog_coverage": "complete",
                "known_library_factual_verification": "incomplete",
                "known_library_registration": "observed per catalog ID; absent work.json is an integration gap",
                "historical_coverage": "selected-known-catalog-observations-only",
                "historical_holdings": "selected catalog IDs accounted; source facts not comprehensively verified",
                "historical_holdings_reason": "the selected legacy catalog supplies observed claims, not replacement metadata authority",
                "finding_counts_basis": "required_missing, useful_optional_missing, contradictory and unknown count declared-library/research findings only; legacy observations and separately reviewed primary-evidence packets are not included",
                "excluded_populations": [
                    "primary source verification of observed legacy catalog metadata",
                    "unregistered historical raw/data/ir holdings outside the selected known catalog",
                    "v2 form, edition, part, and witness relationships not established by the selected inputs",
                    "generated views treated as metadata authority",
                    "rights clearance and publication authorization decisions",
                ],
            }
        )
    result_counts: dict[str, Any] = {
        "findings": len(findings),
        "required_missing": counts["required_missing"],
        "useful_optional_missing": counts["useful_optional_missing"],
        "contradictory": counts["contradictory"],
        "unknown": counts["unknown"],
        "pipeline_statuses": dict(sorted(pipeline_counts.items())),
        "research_leads": len(lead_rows),
        "unresolved_research_leads": sum(1 for row in lead_rows if not row.get("stable_work_id")),
        "resolved_research_leads": sum(1 for row in lead_rows if row.get("stable_work_id")),
    }
    accounting: dict[str, Any] = {
        "declared_entities": len(all_entities),
        "findings": len(findings),
        "research_leads": lead_accounting,
        "all_research_leads_accounted": bool(lead_accounting.get("all_accounted")),
    }
    if known_library is not None:
        catalog_summary = known_library["catalog"]
        registration = catalog_summary["registration_status"]
        result_counts.update(
            {
                "known_library_catalog_rows": catalog_summary["row_count"],
                "known_library_catalog_unique_ids": catalog_summary["unique_work_ids"],
                "known_library_readiness_rows": catalog_summary["readiness_actual_row_count"],
                "known_library_prior_disposition_rows": catalog_summary["prior_disposition_row_count"],
                "known_library_registered_work_ids": registration["registered"],
                "known_library_unregistered_work_ids": registration["unregistered_legacy_catalog_id"],
                "known_library_acquisition_lanes": known_library["lane_accounting"]["row_count"],
            }
        )
        accounting["known_library"] = {
            "catalog_rows": catalog_summary["row_count"],
            "catalog_unique_ids": catalog_summary["unique_work_ids"],
            "readiness_rows": catalog_summary["readiness_actual_row_count"],
            "prior_disposition_rows": catalog_summary["prior_disposition_row_count"],
            "acquisition_lanes": known_library["lane_accounting"]["row_count"],
            "catalog_accounting_complete": known_library["catalog_accounting"] == "complete",
            "factual_verification_complete": False,
        }
    result = {
        "schema_version": SCHEMA_VERSION,
        "report_version": REPORT_VERSION,
        "scope": scope,
        "inputs": inputs,
        "freshness": {
            "authority_input_sha256": manifest.get("freshness", {}).get("input_sha256"),
            "generated_views": _copy(view_check),
            "status": "current" if view_check.get("fresh") is True else "stale-or-unavailable",
        },
        "generated_view_check": view_check,
        "inventory": {
            "view_version": manifest.get("view_version"),
            "input_sha256": manifest.get("freshness", {}).get("input_sha256"),
            "scope": _copy(manifest.get("scope", {})),
            "counts": _copy(manifest.get("counts", {})),
            "rebuild_status": "current" if not inventory_issues else "degraded-fallback",
        },
        "entities": all_entities,
        "pipeline_availability": sorted(
            pipeline_rows,
            key=lambda item: (str(item.get("work_id")), str(item.get("textual_form_id")), str(item.get("edition_id"))),
        ),
        "accepted_tei_observations": sorted(
            tei_observations,
            key=lambda item: (str(item.get("entity_id")), str(item.get("authority_path"))),
        ),
        "research_leads": sorted(
            (
                {
                    "lead_id": row.get("lead_id"),
                    "stable_work_id": row.get("stable_work_id"),
                    "identity_status": row.get("identity_status"),
                    "disposition": row.get("disposition"),
                    "observed_claim": row.get("observed_claim"),
                    "acquisition_intent": row.get("acquisition_intent"),
                    "columns": _copy(row.get("columns", [])),
                    "context": _copy(row.get("context", [])),
                    "evidence": _copy(row.get("evidence")),
                    "raw_record": _copy(row.get("raw_record", row)),
                    "line_number": row.get("line_number"),
                    "stable_id_available": row.get("stable_id_available"),
                }
                for row in lead_rows
            ),
            key=lambda item: (str(item.get("lead_id")), int(item.get("line_number") or 0)),
        ),
        "findings": findings,
        "batches": _batches(findings),
        "issues": issues,
        "accounting": accounting,
        "counts": result_counts,
    }
    if known_library is not None:
        result["known_library"] = known_library
    return result


def write_report(
    root: Path,
    output: Path,
    known_library_catalog: Path | None = None,
    legacy_catalog: Path | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    destination = _ensure_output_allowed(root, Path(output))
    report = build_report(root, known_library_catalog, legacy_catalog)
    write_json(destination, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--known-library-catalog",
        type=Path,
        help="opt-in Ticket 37 library-status.json for known-library coverage assessment",
    )
    parser.add_argument(
        "--legacy-catalog",
        type=Path,
        help="explicit legacy WorkCatalog JSON paired with --known-library-catalog",
    )
    args = parser.parse_args(argv)
    try:
        report = write_report(
            args.root,
            args.output,
            args.known_library_catalog,
            args.legacy_catalog,
        )
    except PipelineError as exc:
        parser.error(str(exc))
    print(json.dumps(report["counts"], sort_keys=True, separators=(",", ":")))
    if report["scope"].get("declared_coverage") != "complete":
        print(
            "META-001 coverage is incomplete; inspect report issues before treating it as a complete assessment",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
