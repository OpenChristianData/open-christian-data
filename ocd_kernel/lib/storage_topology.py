"""Resolve repository paths across the explicit local OCD data plane."""

from __future__ import annotations

from ocd_kernel.lib.path_io import resolve_path
from ocd_kernel.lib.path_io import io_path as _io_path, ordinary_path as _ordinary_path, resolve_path as _resolve

import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path, PurePosixPath


EXTERNAL_DATA_ROOTS = frozenset({"exports", "raw", "reports"})
LOCAL_CONFIG_NAME = ".ocd-storage.json"
_read_roots: ContextVar[dict | None] = ContextVar("storage_read_roots", default=None)


@contextmanager
def storage_read_phase():
    """Reuse validated base roots within one read phase; callers end it before writes."""
    token = _read_roots.set({})
    try:
        yield
    finally:
        _read_roots.reset(token)


class StorageTopologyError(ValueError):
    """Raised when a local storage route is missing or escapes its boundary."""


def _library_root(repo_root: Path) -> Path | None:
    config_path = repo_root / LOCAL_CONFIG_NAME
    if not _io_path(config_path).is_file():
        return None
    try:
        payload = json.loads(_io_path(config_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageTopologyError(f"invalid local storage config: {config_path}") from exc
    value = payload.get("library_root") if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise StorageTopologyError("local storage config requires a non-empty library_root")
    library_root = Path(value)
    if not library_root.is_absolute():
        raise StorageTopologyError("local storage library_root must be absolute")
    return _resolve(library_root)


def resolve_repo_path(repo_root: Path, relative_path: str, *, strict: bool = False) -> Path:
    """Resolve a normalized repository path through the configured data plane."""

    roots = _read_roots.get()
    key = Path(repo_root).absolute()
    root = roots[key][0] if roots is not None and key in roots else _resolve(repo_root)
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        raise StorageTopologyError("path must be normalized repository-relative POSIX text")
    relative = PurePosixPath(relative_path)
    parts = relative.parts
    if (
        relative.is_absolute()
        or relative.as_posix() != relative_path
        or any(part in {".", ".."} for part in parts)
        or (parts and ":" in parts[0])
    ):
        raise StorageTopologyError("path must be normalized repository-relative POSIX text")
    if roots is not None and key in roots:
        library_root = roots[key][1]
        boundaries = roots[key][2]
    else:
        library_root = _library_root(root)
        boundaries = {}
        if roots is not None:
            roots[key] = (root, library_root, boundaries)
    base = library_root if library_root is not None and parts[0] in EXTERNAL_DATA_ROOTS else root
    candidate = _resolve(base / Path(*parts), strict=strict)
    if base == library_root:
        if parts[0] not in boundaries:
            boundaries[parts[0]] = _resolve(base / parts[0])
        allowed_root = boundaries[parts[0]]
    else:
        allowed_root = root
    try:
        candidate.relative_to(allowed_root)
    except ValueError as exc:
        raise StorageTopologyError(f"path escapes configured storage boundary: {relative_path}") from exc
    return candidate


def repository_relative_path(repo_root: Path, path: Path) -> str:
    """Return the logical repository path for a contained physical path."""

    roots = _read_roots.get()
    key = Path(repo_root).absolute()
    if roots is not None and key in roots:
        root, library_root, _ = roots[key]
    else:
        root = _resolve(repo_root)
        library_root = _library_root(root)
        if roots is not None:
            roots[key] = (root, library_root, {})
    lexical_root = _ordinary_path(Path(os.path.abspath(repo_root)))
    source_path = _ordinary_path(Path(path if path.is_absolute() else repo_root / path))
    lexical_path = _ordinary_path(Path(os.path.abspath(source_path)))
    try:
        relative_path = lexical_path.relative_to(lexical_root).as_posix()
    except ValueError:
        if library_root is None:
            raise StorageTopologyError(f"path is outside configured storage: {path}")
        physical_path = _resolve(source_path)
        try:
            relative_path = physical_path.relative_to(library_root).as_posix()
        except ValueError as exc:
            raise StorageTopologyError(f"path is outside configured storage: {path}") from exc
    resolved = resolve_repo_path(repo_root, relative_path)
    if resolved != _resolve(source_path):
        raise StorageTopologyError(f"path does not match configured storage route: {path}")
    return relative_path


def configured_external_path(repo_root: Path, path: Path) -> Path | None:
    """Return a validated physical data-plane path, or None for normal paths."""

    if _library_root(resolve_path(repo_root)) is None:
        return None
    try:
        relative_path = repository_relative_path(repo_root, path)
    except StorageTopologyError:
        return None
    if PurePosixPath(relative_path).parts[0] not in EXTERNAL_DATA_ROOTS:
        return None
    return resolve_repo_path(repo_root, relative_path)
