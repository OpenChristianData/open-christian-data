"""Explicit offline release selection derived from generated view facts."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from ocd_kernel.library._common import PipelineError, load_json, safe_identifier
from ocd_kernel.library.identities import discover_library


SELECTION_VERSION = "ocd-release-selection-provisional-v1"


def make_selection(
    *,
    release_id: str,
    category: str,
    edition_id: str | None,
    status_report: dict[str, Any],
) -> dict[str, Any]:
    safe_identifier(release_id, field="release_id")
    if category != "prose":
        raise PipelineError(f"PIPE-001 only supports prose, not {category!r}")
    if edition_id is None:
        raise PipelineError("PIPE-001 requires one explicit edition_id")
    statuses = status_report.get("items")
    if not isinstance(statuses, list):
        raise PipelineError("project status report items must be a list")
    selected = [item for item in statuses if item.get("edition_id") == edition_id]
    if not selected:
        raise PipelineError(f"selected edition not found: {edition_id}")
    if len(selected) != 1:
        raise PipelineError(f"selected edition is not unique: {edition_id}")
    selected = sorted(selected, key=lambda item: (item.get("work_id", ""), item.get("edition_id", "")))
    publishable = [item for item in selected if item.get("status") in {"included", "warned"}]
    return {
        "schema_version": "provisional-v1",
        "selection_version": SELECTION_VERSION,
        "release_id": release_id,
        "categories": [category],
        "items": [
            {
                "work_id": item["work_id"],
                "textual_form_id": item["textual_form_id"],
                "edition_id": item["edition_id"],
                "status": item["status"],
                "selected": item in publishable,
                "reasons": item.get("reasons", []),
            }
            for item in selected
        ],
        "accounting": {
            "requested": len(selected),
            "selected": len(publishable),
            "included": sum(1 for item in selected if item.get("status") == "included"),
            "warned": sum(1 for item in selected if item.get("status") == "warned"),
            "failed": sum(1 for item in selected if item.get("status") == "failed"),
            "excluded": sum(1 for item in selected if item.get("status") == "excluded"),
        },
    }


def load_selection(path: Path) -> dict[str, Any]:
    record = load_json(path)
    if record.get("selection_version") != SELECTION_VERSION:
        raise PipelineError(f"unsupported release selection version: {path}")
    if not isinstance(record.get("release_id"), str) or not record["release_id"]:
        raise PipelineError(f"release selection requires release_id: {path}")
    categories = record.get("categories")
    if categories != ["prose"]:
        raise PipelineError(f"release selection must request prose: {path}")
    items = record.get("items")
    if not isinstance(items, list) or not items:
        raise PipelineError(f"release selection requires items: {path}")
    return record


# PIPE-017 v2 is deliberately separate from the provisional PIPE-001 contract
# above.  Keep the older names and shapes available until the release consumers
# complete their cutover.
RELEASE_SELECTION_SCHEMA_VERSION = "2.0"

_SELECTION_KEYS = ("schema_version", "release_id", "items", "work_coverage")
_SELECTION_REQUIRED_KEYS = ("schema_version", "release_id", "items")
_SELECTION_ITEM_KEYS = frozenset(
    {"item_id", "category", "acceptance_path", "exclude_reason", "work_id", "license", "public_notices"}
)
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *{f"com{index}" for index in range(1, 10)},
        *{f"lpt{index}" for index in range(1, 10)},
    }
)


def _non_empty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or not value.strip():
        raise PipelineError(f"{field} must be a non-empty string")
    return value


def _safe_release_identifier(value: Any, *, field: str) -> str:
    identifier = _non_empty_string(value, field=field)
    safe_identifier(identifier, field=field)
    if identifier.endswith("."):
        raise PipelineError(
            f"{field} safe identifier cannot end with a dot: {identifier!r}"
        )
    if identifier.casefold().split(".", 1)[0] in _WINDOWS_RESERVED_NAMES:
        raise PipelineError(f"{field} uses a reserved Windows name: {identifier!r}")
    return identifier


def _check_windows_portable_parts(parts: tuple[str, ...], *, field: str) -> None:
    for part in parts:
        if part.endswith((".", " ")):
            raise PipelineError(
                f"{field} contains a Windows-aliasing segment: {part!r}"
            )
        if part.casefold().split(".", 1)[0] in _WINDOWS_RESERVED_NAMES:
            raise PipelineError(f"{field} contains a reserved Windows name: {part!r}")


def _selection_relative_path(value: Any, *, field: str) -> str:
    """Validate a normalized root-relative POSIX path without resolving it."""

    relative = _non_empty_string(value, field=field)
    if (
        any(ord(character) < 0x20 or ord(character) == 0x7F for character in relative)
        or "\\" in relative
        or ":" in relative
    ):
        raise PipelineError(f"{field} must be a root-relative POSIX path: {relative!r}")
    if relative.startswith("/"):
        raise PipelineError(f"{field} must be a root-relative POSIX path: {relative!r}")
    if "//" in relative or relative.endswith("/"):
        raise PipelineError(f"{field} must be a normalized POSIX path: {relative!r}")
    path = PurePosixPath(relative)
    if path.is_absolute() or path.as_posix() != relative:
        raise PipelineError(f"{field} must be a normalized POSIX path: {relative!r}")
    if not path.parts or any(part in {".", ".."} for part in path.parts):
        raise PipelineError(f"{field} must stay within the root: {relative!r}")
    _check_windows_portable_parts(path.parts, field=field)
    return relative


def _validate_selection_item(value: Any, *, index: int) -> dict[str, Any]:
    field_prefix = f"items[{index}]"
    if not isinstance(value, Mapping):
        raise PipelineError(f"{field_prefix} must be an object")
    unexpected = [key for key in value if key not in _SELECTION_ITEM_KEYS]
    if unexpected:
        raise PipelineError(
            f"{field_prefix} contains unexpected keys: "
            + ", ".join(sorted((str(key) for key in unexpected)))
        )
    for key in ("item_id", "category", "acceptance_path"):
        if key not in value:
            raise PipelineError(f"{field_prefix} requires {key}")

    item_id = _safe_release_identifier(
        value["item_id"], field=f"{field_prefix}.item_id"
    )
    category = _non_empty_string(value["category"], field=f"{field_prefix}.category")
    acceptance_path = _selection_relative_path(
        value["acceptance_path"], field=f"{field_prefix}.acceptance_path"
    )
    normalized: dict[str, Any] = {
        "item_id": item_id,
        "category": category,
        "acceptance_path": acceptance_path,
    }
    if "work_id" in value:
        normalized["work_id"] = _safe_release_identifier(
            value["work_id"], field=f"{field_prefix}.work_id"
        )
    if "exclude_reason" in value:
        normalized["exclude_reason"] = _non_empty_string(
            value["exclude_reason"], field=f"{field_prefix}.exclude_reason"
        )
    if "license" in value:
        if "exclude_reason" in value:
            raise PipelineError(f"{field_prefix} cannot assign a public license to excluded text")
        normalized["license"] = _non_empty_string(
            value["license"], field=f"{field_prefix}.license"
        )
    if "public_notices" in value:
        if "exclude_reason" in value:
            raise PipelineError(f"{field_prefix} cannot bind notices to an excluded item")
        notices = []
        keys = {"source_path", "source_sha256", "notice_path", "notice_sha256"}
        for notice_index, notice in enumerate(value["public_notices"]):
            field = f"{field_prefix}.public_notices[{notice_index}]"
            if not isinstance(notice, Mapping) or set(notice) != keys:
                raise PipelineError(f"{field} requires exact source and notice bindings")
            bound = {name: _selection_relative_path(notice[name], field=f"{field}.{name}")
                     for name in ("source_path", "notice_path")}
            for name in ("source_sha256", "notice_sha256"):
                digest = notice[name]
                if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                    raise PipelineError(f"{field}.{name} must be a SHA-256 digest")
                bound[name] = digest
            notices.append(bound)
        targets = [(entry["source_path"].casefold(), entry["notice_path"].casefold())
                   for entry in notices]
        if len(set(targets)) != len(targets):
            raise PipelineError(f"{field_prefix} repeats a public notice binding")
        normalized["public_notices"] = sorted(
            notices, key=lambda entry: (entry["source_path"], entry["notice_path"])
        )
    return normalized


def _validate_release_selection_schema(value: Mapping[str, Any]) -> None:
    """Apply the checked-in JSON Schema before semantic normalization."""

    schema_path = (
        Path(__file__).resolve().parents[2]
        / "schemas"
        / "v2"
        / "release-selection.schema.json"
    )
    try:
        import jsonschema
    except ImportError as exc:
        raise PipelineError(
            "cannot validate release selection: jsonschema is unavailable"
        ) from exc
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        failures = sorted(
            validator.iter_errors(value),
            key=lambda failure: tuple(
                (type(part).__name__, str(part)) for part in failure.absolute_path
            ),
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        jsonschema.exceptions.SchemaError,
    ) as exc:
        raise PipelineError(
            f"cannot validate release selection against {schema_path}: {exc}"
        ) from exc
    if failures:
        failure = failures[0]
        location = "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}"
            for part in failure.absolute_path
        ) or "<root>"
        raise PipelineError(
            f"release selection schema validation failed at {location}: "
            f"{failure.message}"
        )


def _validate_work_coverage(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"included_work_ids", "excluded_works"}
    ):
        raise PipelineError("work_coverage requires included_work_ids and excluded_works")
    included = value["included_work_ids"]
    excluded = value["excluded_works"]
    if not isinstance(included, list) or not isinstance(excluded, list):
        raise PipelineError("work_coverage lists must be arrays")
    included_ids = [
        _safe_release_identifier(work_id, field="work_coverage.included_work_ids")
        for work_id in included
    ]
    excluded_works = []
    for entry in excluded:
        if not isinstance(entry, Mapping) or set(entry) != {"work_id", "reason"}:
            raise PipelineError("work_coverage excluded work requires work_id and reason")
        excluded_works.append({
            "work_id": _safe_release_identifier(
                entry["work_id"], field="work_coverage.excluded_works.work_id"
            ),
            "reason": _non_empty_string(
                entry["reason"], field="work_coverage.excluded_works.reason"
            ),
        })
    all_ids = included_ids + [entry["work_id"] for entry in excluded_works]
    if len({work_id.casefold() for work_id in all_ids}) != len(all_ids):
        raise PipelineError("duplicate work_id in work_coverage")
    return {
        "included_work_ids": sorted(included_ids),
        "excluded_works": sorted(excluded_works, key=lambda entry: entry["work_id"]),
    }


def validate_work_cohort(root: Path, request: Mapping[str, Any]) -> dict[str, str]:
    """Check a declared cohort and bind every requested text item to one included work."""
    coverage = request.get("work_coverage")
    if coverage is None:
        return {}
    canonical = {work.work_id for work in discover_library(root)}
    included = set(coverage["included_work_ids"])
    excluded = {entry["work_id"] for entry in coverage["excluded_works"]}
    declared = included | excluded
    missing = sorted(canonical - declared)
    extra = sorted(declared - canonical)
    if missing or extra:
        raise PipelineError(
            f"work_coverage differs from canonical works: missing={missing}, extra={extra}"
        )
    item_work_ids: dict[str, str] = {}
    for item in request["items"]:
        if "exclude_reason" in item:
            continue
        work_id = item.get("work_id")
        if not isinstance(work_id, str):
            raise PipelineError(
                f"work_coverage requires work_id for selected text item: {item['item_id']}"
            )
        if work_id in excluded:
            raise PipelineError(f"excluded work selected for text: {work_id}")
        if work_id not in included:
            raise PipelineError(f"selected text work is outside included cohort: {work_id}")
        item_work_ids[item["item_id"]] = work_id
    return item_work_ids


def validate_release_selection(value: Any) -> dict[str, Any]:
    """Validate and deterministically normalize a PIPE-017 v2 selection.

    Category names remain open at this boundary.  The category assembler owns
    the supported-adapter registry and records an unsupported category as a
    failed item, allowing a selection to name a future category before its
    adapter is available.
    """

    if not isinstance(value, Mapping):
        raise PipelineError("release selection must be an object")
    _validate_release_selection_schema(value)
    unexpected = [key for key in value if key not in _SELECTION_KEYS]
    if unexpected:
        raise PipelineError(
            "release selection contains unexpected keys: "
            + ", ".join(sorted((str(key) for key in unexpected)))
        )
    for key in _SELECTION_REQUIRED_KEYS:
        if key not in value:
            raise PipelineError(f"release selection requires {key}")
    if value["schema_version"] != RELEASE_SELECTION_SCHEMA_VERSION:
        raise PipelineError(
            "release selection has unsupported schema_version: "
            f"{value['schema_version']!r}"
        )
    release_id = _safe_release_identifier(value["release_id"], field="release_id")
    raw_items = value["items"]
    if not isinstance(raw_items, list) or not raw_items:
        raise PipelineError("release selection items must be a non-empty list")

    items = [_validate_selection_item(item, index=index) for index, item in enumerate(raw_items)]
    item_ids: set[str] = set()
    category_paths: set[tuple[str, str]] = set()
    for item in items:
        item_id = item["item_id"]
        category_path = (item["category"], item["acceptance_path"])
        item_id_key = item_id.casefold()
        category_path_key = tuple(value.casefold() for value in category_path)
        if item_id_key in item_ids:
            raise PipelineError(f"duplicate release selection item_id: {item_id}")
        if category_path_key in category_paths:
            raise PipelineError(
                "duplicate release selection category/acceptance_path pair: "
                f"{category_path[0]!r}, {category_path[1]!r}"
            )
        item_ids.add(item_id_key)
        category_paths.add(category_path_key)

    result = {
        "schema_version": RELEASE_SELECTION_SCHEMA_VERSION,
        "release_id": release_id,
        "items": sorted(items, key=lambda item: item["item_id"]),
    }
    if "work_coverage" in value:
        result["work_coverage"] = _validate_work_coverage(value["work_coverage"])
        missing_licenses = [item["item_id"] for item in items
                            if "exclude_reason" not in item and "license" not in item]
        if missing_licenses:
            raise PipelineError(
                "complete work coverage requires an item license for every selected text: "
                + ", ".join(missing_licenses)
            )
    elif any("work_id" in item for item in items):
        raise PipelineError("selection item work_id requires work_coverage")
    return result


def load_release_selection(path: Path) -> dict[str, Any]:
    """Load, validate, and normalize a PIPE-017 v2 selection sidecar."""

    selection_path = Path(path)
    return validate_release_selection(load_json(selection_path))


def resolve_acceptance_path(root: Path, relative: str) -> Path:
    """Resolve a selection path while rejecting lexical and symlink escapes."""

    root_input = Path(root)
    try:
        root_path = root_input.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PipelineError(f"release root is unavailable: {root_input}") from exc
    if not root_path.is_dir():
        raise PipelineError(f"release root is not a directory: {root_input}")

    relative_path = _selection_relative_path(relative, field="acceptance_path")
    try:
        candidate = (root_path / Path(*PurePosixPath(relative_path).parts)).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise PipelineError(f"cannot resolve acceptance_path: {relative_path}") from exc
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise PipelineError(
            f"acceptance_path escapes release root: {relative_path}"
        ) from exc
    return candidate
