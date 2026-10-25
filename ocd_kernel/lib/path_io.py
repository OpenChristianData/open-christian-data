"""Filesystem path handling without storage policy or application dependencies.

Keep ordinary paths in identities and serialized records. Convert at the I/O
call only, after the caller has applied its own containment and ownership rules.
This module does not authorize a path or change which storage roots are allowed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator


def ordinary_path(path: str | Path) -> Path:
    """Return a normal Windows path without an extended-length I/O prefix."""
    path = Path(path)
    if os.name != "nt":
        return path
    value = str(path)
    if value.startswith("\\\\?\\UNC\\"):
        return Path("\\\\" + value[8:])
    if value.startswith("\\\\?\\"):
        return Path(value[4:])
    return path


def io_path(path: str | Path) -> Path:
    """Return an absolute path suitable for long-path filesystem operations.

    Make relative paths absolute without resolving links or rewriting parent
    components. Callers validate logical paths and use ``resolve_path`` for
    containment checks. Already-prefixed paths retain their existing spelling.
    """
    path = Path(path)
    if os.name == "nt" and str(path).startswith("\\\\?\\"):
        return path
    path = path.absolute()
    if os.name != "nt":
        return path
    value = str(path)
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)


def resolve_path(
    path: str | Path, *, strict: bool = False, preserve_prefix: bool = False
) -> Path:
    """Resolve links through long-path I/O, ordinarily returning a normal path.

    ``preserve_prefix`` retains an explicit input prefix for legacy cache keys
    and I/O identity records. It never adds one to an ordinary input's identity.
    """
    resolved = io_path(path).resolve(strict=strict)
    if preserve_prefix and os.name == "nt" and str(path).startswith("\\\\?\\"):
        return resolved
    return ordinary_path(resolved)


def io_glob(directory: str | Path, pattern: str) -> Iterator[Path]:
    """Discover deep files while returning ordinary absolute paths."""
    directory = ordinary_path(io_path(directory))
    physical = io_path(directory)
    for found in physical.glob(pattern):
        yield directory / found.relative_to(physical)


def io_rglob(directory: str | Path, pattern: str) -> Iterator[Path]:
    """Recursively discover deep files, retaining ordinary absolute paths."""
    directory = ordinary_path(io_path(directory))
    physical = io_path(directory)
    for found in physical.rglob(pattern):
        yield directory / found.relative_to(physical)


def io_iterdir(directory: str | Path) -> Iterator[Path]:
    """List direct children through long-path I/O, returning ordinary paths."""
    directory = ordinary_path(io_path(directory))
    physical = io_path(directory)
    for found in physical.iterdir():
        yield directory / found.name
