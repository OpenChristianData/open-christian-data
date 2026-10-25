"""Fail-safe storage optimization for candidate-package mutation tests.

Only explicitly named immutable data members may be hardlinked. Every other
member is copied, so an omitted optimization annotation costs performance
rather than candidate integrity. Python and reparse-backed trees are refused:
hardlinking those trees is not semantically neutral in this repository.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
from typing import Iterable


CandidateFingerprint = tuple[tuple[str, int, str], ...]


def _is_reparse_path(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    return path.is_symlink() or is_junction(path)


def _refuse_lexical_reparse_components(path: Path, *, label: str) -> None:
    """Reject reparse points before ``resolve`` can erase their identity."""
    absolute = Path(os.path.abspath(path))
    for component in (absolute, *absolute.parents):
        if _is_reparse_path(component):
            raise ValueError(f"{label} contains a symlink or reparse path: {component}")


def _validated_source(source: Path) -> Path:
    _refuse_lexical_reparse_components(source, label="candidate source path")
    resolved = source.resolve(strict=True)
    if not resolved.is_dir():
        raise NotADirectoryError(resolved)
    for member in resolved.rglob("*"):
        if _is_reparse_path(member):
            raise ValueError(f"candidate package contains a symlink or reparse path: {member}")
        physical = member.resolve(strict=True)
        if not physical.is_relative_to(resolved):
            raise ValueError(f"candidate package member escapes its root: {member}")
        if member.is_file() and member.suffix.lower() == ".py":
            raise ValueError(f"candidate clone helper refuses Python shadow trees: {member}")
    return resolved


def _member_key(source: Path, value: str | Path) -> str:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
        raise ValueError(f"hardlink member must be a contained relative path: {value}")
    member = source / relative
    if _is_reparse_path(member):
        raise ValueError(f"hardlink member is a symlink or reparse path: {value}")
    try:
        resolved = member.resolve(strict=True)
    except FileNotFoundError:
        raise FileNotFoundError(f"hardlink member does not exist: {value}") from None
    if not resolved.is_relative_to(source):
        raise ValueError(f"hardlink member escapes the candidate package: {value}")
    if not resolved.is_file():
        raise ValueError(f"hardlink member is not a regular file: {value}")
    if resolved.suffix.lower() == ".py":
        raise ValueError(f"candidate clone helper refuses Python members: {value}")
    return resolved.relative_to(source).as_posix()


def clone_candidate_package(
    source: str | Path,
    target: str | Path,
    *,
    hardlink_members: Iterable[str | Path] = (),
) -> Path:
    """Clone a package, linking only explicitly immutable regular data files."""
    source_root = _validated_source(Path(source))
    target_path = Path(target)
    if target_path.exists():
        raise FileExistsError(target_path)
    _refuse_lexical_reparse_components(
        target_path.parent, label="candidate target parent"
    )
    target_parent = target_path.parent.resolve(strict=True)
    target_physical = (target_parent / target_path.name).resolve(strict=False)
    if target_physical.is_relative_to(source_root):
        raise ValueError("candidate clone target must be outside the source package")

    link_keys = {_member_key(source_root, member) for member in hardlink_members}
    same_volume = source_root.stat().st_dev == target_parent.stat().st_dev

    def copy_member(source_member: str, target_member: str) -> str:
        source_path = Path(source_member)
        key = source_path.resolve(strict=True).relative_to(source_root).as_posix()
        if same_volume and key in link_keys:
            try:
                os.link(source_path, target_member)
                return target_member
            except OSError:
                pass
        return str(shutil.copy2(source_path, target_member))

    try:
        shutil.copytree(source_root, target_path, copy_function=copy_member)
    except Exception:
        if target_path.exists():
            shutil.rmtree(target_path)
        raise
    return target_path


def candidate_package_fingerprint(package: str | Path) -> CandidateFingerprint:
    """Return a stable complete member-path, size, and SHA-256 fingerprint."""
    root = _validated_source(Path(package))
    records: list[tuple[str, int, str]] = []
    for member in sorted(path for path in root.rglob("*") if path.is_file()):
        digest = hashlib.sha256()
        with member.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        records.append(
            (member.relative_to(root).as_posix(), member.stat().st_size, digest.hexdigest())
        )
    return tuple(records)
