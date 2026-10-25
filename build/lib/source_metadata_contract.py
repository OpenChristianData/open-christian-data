"""Shared schema, identity, and path rules for source metadata.

This internal module keeps the evidence reader independent of metadata decisions.
The metadata engine re-exports its established names for existing callers.
"""
from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import jsonschema
from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "v2" / "source-metadata.schema.json"

class MetadataError(ValueError):
    """A visible malformed metadata contract or semantic decision."""

class EvidenceError(MetadataError):
    """A claimed source or adoption binding could not be verified."""

def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MetadataError(f"duplicate JSON key: {key}")
        result[key] = value
    return result

def canonical_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 bytes for generated JSON."""

    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")

def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except FileNotFoundError as exc:
        raise MetadataError(f"missing JSON input: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetadataError(f"cannot read JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MetadataError(f"JSON input must be an object: {path}")
    return value

@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    try:
        value = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MetadataError(f"cannot load source metadata schema {SCHEMA_PATH}: {exc}") from exc
    if not isinstance(value, dict):
        raise MetadataError(f"source metadata schema must be an object: {SCHEMA_PATH}")
    try:
        jsonschema.Draft202012Validator.check_schema(value)
    except jsonschema.SchemaError as exc:
        raise MetadataError(f"invalid source metadata schema: {exc.message}") from exc
    return value

def schema_enum(name: str, *, schema: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """Read an enum from the closed schema rather than duplicating its choices."""

    active = schema if schema is not None else load_schema()
    definition = active.get("$defs", {}).get(name)
    if not isinstance(definition, Mapping) or not isinstance(definition.get("enum"), list):
        raise MetadataError(f"schema enum is missing: {name}")
    return tuple(str(item) for item in definition["enum"])

def _schema_for(kind: str) -> dict[str, Any]:
    schema = load_schema()
    definition = schema.get("$defs", {}).get(kind)
    if not isinstance(definition, Mapping):
        raise MetadataError(f"unknown source metadata document kind: {kind}")
    result = copy.deepcopy(dict(definition))
    result["$schema"] = schema["$schema"]
    result["$defs"] = schema["$defs"]
    return result

def _normal_relative(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise MetadataError(f"{field} must be a normalized repository-relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {".", ".."} for part in path.parts) or ":" in path.parts[0]:
        raise MetadataError(f"{field} must be a normalized repository-relative POSIX path: {value!r}")
    if path.as_posix() != value:
        raise MetadataError(f"{field} must use normalized POSIX separators: {value!r}")
    return value

def _pointer_tokens(pointer: str) -> list[str]:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise MetadataError(f"JSON pointer must start with '/': {pointer!r}")
    return [token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/")]

def _pointer_value(document: Any, pointer: str) -> Any:
    value = document
    for token in _pointer_tokens(pointer):
        if isinstance(value, Mapping):
            if token not in value:
                raise KeyError(token)
            value = value[token]
        elif isinstance(value, list) and token.isdigit():
            index = int(token)
            if index >= len(value):
                raise KeyError(token)
            value = value[index]
        else:
            raise KeyError(token)
    return value

def _json_equal(left: Any, right: Any) -> bool:
    return canonical_bytes(left) == canonical_bytes(right)

def _resolve(root: Path, relative: str, *, field: str) -> Path:
    try:
        return resolve_repo_path(Path(root), _normal_relative(relative, field=field))
    except StorageTopologyError as exc:
        raise EvidenceError(f"{field} cannot be resolved: {relative}: {exc}") from exc

def _read_packet_value(data: bytes, pointer: str) -> Any:
    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
        return _pointer_value(document, pointer)
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, MetadataError) as exc:
        raise EvidenceError(f"cannot resolve JSON pointer {pointer!r}: {exc}") from exc
