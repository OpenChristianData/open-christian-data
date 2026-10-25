"""Small, dependency-free helpers shared by the PIPE-001 runtime.

The ticket deliberately keeps the first runtime slice provisional.  These
helpers nevertheless make the important boundary explicit: JSON sidecars are
strictly parsed, paths are kept relative to the selected fixture root, and all
generated JSON uses one canonical representation.
"""

from __future__ import annotations

from ocd_kernel.lib.path_io import io_path, resolve_path, io_glob as io_glob

import hashlib
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any


class PipelineError(ValueError):
    """A visible, user-actionable failure in the offline pipeline."""


_read_inputs: ContextVar[dict | None] = ContextVar("library_read_inputs", default=None)


@contextmanager
def inspection_read_phase():
    """Reuse successful small inputs only until this inspection phase ends."""
    token = _read_inputs.set({})
    try:
        yield
    finally:
        _read_inputs.reset(token)


def read_input_bytes(path: Path) -> bytes:
    cache = _read_inputs.get()
    path = io_path(path)
    key = ("bytes", path)
    if cache is None:
        return path.read_bytes()
    if key not in cache:
        cache[key] = path.read_bytes()
    return cache[key]


def read_input_lines(path: Path, *, body: bytes | None = None) -> list[str]:
    cache = _read_inputs.get()
    key = ("lines", io_path(path))
    if cache is None:
        return (body if body is not None else read_input_bytes(path)).decode("utf-8").splitlines()
    if key not in cache:
        cache[key] = (body if body is not None else read_input_bytes(path)).decode("utf-8").splitlines()
    return cache[key]


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PipelineError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    """Load an object sidecar and reject duplicate keys and non-objects."""

    try:
        value = json.loads(
            read_input_bytes(path).decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except FileNotFoundError as exc:
        raise PipelineError(f"missing JSON sidecar: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PipelineError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"JSON sidecar must contain an object: {path}")
    return value


def canonical_bytes(value: Any) -> bytes:
    """Return the stable UTF-8 JSON bytes used by generated artifacts."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    io_path(path.parent).mkdir(parents=True, exist_ok=True)
    io_path(path).write_bytes(canonical_bytes(value))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with io_path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PipelineError(f"cannot read file for SHA-256: {path}: {exc}") from exc
    return digest.hexdigest()


def ensure_relative_path(value: str, *, field: str) -> Path:
    """Validate a sidecar path without allowing absolute or parent traversal."""

    candidate = Path(value)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise PipelineError(f"{field} must be a relative path within the fixture: {value}")
    if not value or str(candidate) in {".", ""}:
        raise PipelineError(f"{field} must name a file")
    return candidate


def within(root: Path, relative: str | Path, *, field: str) -> Path:
    rel = ensure_relative_path(str(relative), field=field)
    root = resolve_path(root)
    candidate = resolve_path(root / rel)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PipelineError(f"{field} escapes fixture root: {relative}") from exc
    return candidate


def require_string(record: dict[str, Any], key: str, *, context: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PipelineError(f"{context} requires non-empty string {key}")
    return value.strip()


def safe_identifier(value: str, *, field: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise PipelineError(f"{field} is not a safe identifier: {value}")
    return value


def as_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise PipelineError(f"{field} must be a list")
    return value
