"""Canonical byte authority for artifacts committed to Git."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import hashlib
import os
import re
import stat
import subprocess
from pathlib import Path


_FULL_SHA1 = re.compile(r"[0-9a-f]{40}")
_REGULAR_BLOB_MODES = frozenset({"100644", "100755"})
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class CanonicalGitArtifactError(ValueError):
    """Raised when live bytes do not resolve to their committed Git identity."""


class CanonicalGitArtifactIdentityMismatch(CanonicalGitArtifactError):
    """Raised only when a regular checkout file differs from its committed blob."""


class CanonicalGitOperationalError(CanonicalGitArtifactError):
    """Raised when Git cannot execute an authority query."""


class CanonicalGitRepositoryRootError(CanonicalGitArtifactError):
    """Raised when the caller did not bind Git's actual worktree top-level."""


@dataclass(frozen=True, slots=True)
class CanonicalGitArtifact:
    """One committed artifact whose checkout still clean-filters to its blob."""

    repository_relative_path: str
    repository_revision: str
    blob_oid: str
    canonical_bytes: bytes
    checkout_bytes: bytes


@dataclass(frozen=True, slots=True)
class CanonicalGitArtifactCandidate:
    """A regular Git blob and the stable, non-reparse checkout bytes at its path."""

    repository_relative_path: str
    repository_revision: str
    blob_oid: str
    canonical_bytes: bytes
    checkout_bytes: bytes
    checkout_clean_oid: str


@dataclass(frozen=True, slots=True)
class CanonicalGitIndexArtifact:
    """One explicitly staged regular blob whose checkout matches the index."""

    repository_relative_path: str
    head_revision: str
    head_blob_oid: str | None
    index_blob_oid: str
    canonical_bytes: bytes
    checkout_bytes: bytes


@dataclass(frozen=True, slots=True)
class _TreeEntry:
    mode: str
    object_type: str
    oid: str


def _git(
    repository_root: Path,
    arguments: list[str],
    *,
    input_bytes: bytes | None = None,
) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            check=True,
            cwd=repository_root,
            input=input_bytes,
            capture_output=True,
        )
    except OSError as error:
        diagnostic = " ".join(str(error).split())[:500]
        raise CanonicalGitOperationalError(
            "Git could not establish canonical artifact authority: "
            f"{' '.join(arguments)}: {diagnostic}"
        ) from error
    except subprocess.CalledProcessError as error:
        diagnostic = " ".join(
            (error.stderr or b"").decode("utf-8", errors="backslashreplace").split()
        )[:500]
        suffix = f": {diagnostic}" if diagnostic else ""
        raise CanonicalGitOperationalError(
            "Git could not establish canonical artifact authority: "
            f"{' '.join(arguments)}{suffix}"
        ) from error
    return completed.stdout


def repository_revision(repository_root: Path, revision: str = "HEAD") -> str:
    """Resolve one commit-ish to an exact full commit identifier."""

    root = Path(repository_root).resolve(strict=True)
    if not root.is_dir():
        raise CanonicalGitArtifactError("repository root must be a directory")
    top_level_raw = _git(root, ["rev-parse", "--show-toplevel"])
    try:
        top_level = Path(os.fsdecode(top_level_raw).strip()).resolve(strict=True)
    except (OSError, ValueError) as error:
        raise CanonicalGitRepositoryRootError(
            "Git returned an invalid repository top-level"
        ) from error
    if top_level != root:
        raise CanonicalGitRepositoryRootError(
            f"repository root {root} does not match Git top-level {top_level}"
        )
    resolved = _git(root, ["rev-parse", "--verify", f"{revision}^{{commit}}"])
    commit = resolved.decode("ascii", errors="strict").strip()
    if not _FULL_SHA1.fullmatch(commit):
        raise CanonicalGitArtifactError("Git did not return a full commit identifier")
    return commit


def _lexical_target(path: Path, repository_root: Path) -> tuple[Path, str]:
    root = Path(repository_root).resolve(strict=True)
    target = Path(os.path.abspath(os.fspath(path)))
    try:
        relative = target.relative_to(root)
    except ValueError as error:
        raise CanonicalGitArtifactError(
            "canonical artifact target is outside the repository"
        ) from error
    if not relative.parts:
        raise CanonicalGitArtifactError("canonical artifact target is the repository root")
    return target, relative.as_posix()


def repository_lexical_path(path: Path, *, repository_root: Path) -> Path:
    """Return an absolute contained path without dereferencing any component."""

    root = Path(repository_root).resolve(strict=True)
    target, _ = _lexical_target(path, root)
    return target


def repository_checkout_path(path: Path, *, repository_root: Path) -> Path:
    """Return a contained checkout path only when no component is a reparse alias."""

    root = Path(repository_root).resolve(strict=True)
    target, relative = _lexical_target(path, root)
    _reject_reparse_ancestry(target, root, relative)
    return target


def _tree_entry(
    repository_root: Path,
    *,
    commit: str,
    relative: str,
) -> _TreeEntry | None:
    raw = _git(
        repository_root,
        ["ls-tree", "-z", "--full-tree", commit, "--", f":(literal){relative}"],
    )
    if not raw:
        return None
    records = raw.removesuffix(b"\0").split(b"\0")
    if len(records) != 1 or b"\t" not in records[0]:
        raise CanonicalGitArtifactError(
            f"Git returned an ambiguous tree entry for {relative} at {commit}"
        )
    metadata, raw_path = records[0].split(b"\t", 1)
    fields = metadata.decode("ascii", errors="strict").split()
    if len(fields) != 3 or os.fsdecode(raw_path) != relative:
        raise CanonicalGitArtifactError(
            f"Git returned an invalid tree entry for {relative} at {commit}"
        )
    mode, object_type, oid = fields
    if not _FULL_SHA1.fullmatch(oid):
        raise CanonicalGitArtifactError(
            f"Git returned an invalid object identifier for {relative} at {commit}"
        )
    return _TreeEntry(mode=mode, object_type=object_type, oid=oid)


def _tree_entries(
    repository_root: Path,
    *,
    commit: str,
    relatives: tuple[str, ...],
) -> dict[str, _TreeEntry]:
    if not relatives:
        return {}
    requested = frozenset(relatives)
    raw = _git(
        repository_root,
        [
            "ls-tree",
            "-z",
            "--full-tree",
            commit,
            "--",
            *(f":(literal){relative}" for relative in relatives),
        ],
    )
    entries: dict[str, _TreeEntry] = {}
    for record in raw.removesuffix(b"\0").split(b"\0") if raw else ():
        if b"\t" not in record:
            raise CanonicalGitArtifactError(
                f"Git returned an invalid tree entry set at {commit}"
            )
        metadata, raw_path = record.split(b"\t", 1)
        try:
            fields = metadata.decode("ascii", errors="strict").split()
            relative = os.fsdecode(raw_path)
        except (UnicodeError, ValueError) as error:
            raise CanonicalGitArtifactError(
                f"Git returned an invalid tree entry set at {commit}"
            ) from error
        if len(fields) != 3 or relative not in requested:
            raise CanonicalGitArtifactError(
                f"Git returned an invalid tree entry for {relative} at {commit}"
            )
        if relative in entries:
            raise CanonicalGitArtifactError(
                f"Git returned an ambiguous tree entry for {relative} at {commit}"
            )
        mode, object_type, oid = fields
        if not _FULL_SHA1.fullmatch(oid):
            raise CanonicalGitArtifactError(
                f"Git returned an invalid object identifier for {relative} at {commit}"
            )
        entries[relative] = _TreeEntry(
            mode=mode,
            object_type=object_type,
            oid=oid,
        )
    return entries


def _canonical_blobs(
    repository_root: Path,
    entries: tuple[_TreeEntry, ...],
) -> dict[str, bytes]:
    ordered_oids = tuple(dict.fromkeys(entry.oid for entry in entries))
    if not ordered_oids:
        return {}
    raw = _git(
        repository_root,
        ["cat-file", "--batch"],
        input_bytes=("\n".join(ordered_oids) + "\n").encode("ascii"),
    )
    blobs: dict[str, bytes] = {}
    cursor = 0
    for expected_oid in ordered_oids:
        header_end = raw.find(b"\n", cursor)
        if header_end < 0:
            raise CanonicalGitArtifactError(
                f"Git returned an invalid canonical blob for {expected_oid}"
            )
        try:
            fields = raw[cursor:header_end].decode("ascii", errors="strict").split()
        except UnicodeError as error:
            raise CanonicalGitArtifactError(
                f"Git returned an invalid canonical blob for {expected_oid}"
            ) from error
        if (
            len(fields) != 3
            or fields[0] != expected_oid
            or fields[1] != "blob"
            or not fields[2].isdecimal()
        ):
            raise CanonicalGitArtifactError(
                f"Git returned an invalid canonical blob for {expected_oid}"
            )
        byte_count = int(fields[2])
        content_start = header_end + 1
        content_end = content_start + byte_count
        if content_end >= len(raw) or raw[content_end : content_end + 1] != b"\n":
            raise CanonicalGitArtifactError(
                f"Git returned an invalid canonical blob for {expected_oid}"
            )
        blobs[expected_oid] = raw[content_start:content_end]
        cursor = content_end + 1
    if cursor != len(raw):
        raise CanonicalGitArtifactError("Git returned unexpected canonical blob output")
    return blobs


def _index_entry(repository_root: Path, *, relative: str) -> _TreeEntry | None:
    raw = _git(
        repository_root,
        ["ls-files", "--stage", "-z", "--full-name", "--", f":(literal){relative}"],
    )
    if not raw:
        return None
    records = raw.removesuffix(b"\0").split(b"\0")
    exact_records = []
    for record in records:
        if b"\t" not in record:
            raise CanonicalGitArtifactError(
                f"Git returned an invalid index entry for {relative}"
            )
        _metadata, raw_path = record.split(b"\t", 1)
        if os.fsdecode(raw_path) == relative:
            exact_records.append(record)
    if not exact_records:
        return None
    if len(exact_records) != 1:
        raise CanonicalGitArtifactError(
            f"Git returned an ambiguous index entry for {relative}"
        )
    metadata, raw_path = exact_records[0].split(b"\t", 1)
    fields = metadata.decode("ascii", errors="strict").split()
    if (
        len(fields) != 3
        or fields[2] != "0"
        or os.fsdecode(raw_path) != relative
    ):
        raise CanonicalGitArtifactError(
            f"Git returned an invalid or unmerged index entry for {relative}"
        )
    mode, oid, _stage = fields
    if not _FULL_SHA1.fullmatch(oid):
        raise CanonicalGitArtifactError(
            f"Git returned an invalid index object identifier for {relative}"
        )
    return _TreeEntry(mode=mode, object_type="blob", oid=oid)


def _regular_blob_entry(relative: str, entry: _TreeEntry | None, commit: str) -> _TreeEntry:
    if entry is None:
        raise CanonicalGitArtifactError(
            f"{relative} is not present in the committed tree at {commit}"
        )
    if entry.mode not in _REGULAR_BLOB_MODES or entry.object_type != "blob":
        raise CanonicalGitArtifactError(
            f"{relative} has unsupported Git mode {entry.mode} "
            f"and type {entry.object_type} at {commit}"
        )
    return entry


def _reject_reparse_ancestry(target: Path, repository_root: Path, relative: str) -> None:
    current = repository_root
    for part in Path(relative).parts:
        current /= part
        try:
            status = current.lstat()
        except OSError as error:
            raise CanonicalGitArtifactError(
                f"{relative} checkout path is unavailable"
            ) from error
        file_attributes = getattr(status, "st_file_attributes", 0)
        if stat.S_ISLNK(status.st_mode) or file_attributes & _REPARSE_POINT:
            raise CanonicalGitArtifactError(
                f"{relative} checkout path has a symlink or reparse component"
            )
    if current != target:
        raise CanonicalGitArtifactError("canonical artifact lexical path mismatch")


def _stable_checkout_bytes(target: Path, relative: str) -> bytes:
    status_before = target.stat()
    if not stat.S_ISREG(status_before.st_mode):
        raise CanonicalGitArtifactError(f"{relative} checkout path is not a regular file")
    checkout_bytes = target.read_bytes()
    status_after = target.stat()
    if (
        status_before.st_dev,
        status_before.st_ino,
        status_before.st_size,
        status_before.st_mtime_ns,
    ) != (
        status_after.st_dev,
        status_after.st_ino,
        status_after.st_size,
        status_after.st_mtime_ns,
    ):
        raise CanonicalGitArtifactError(
            f"{relative} changed while canonical authority was being established"
        )
    return checkout_bytes


def _regular_blob_authority(
    path: Path,
    *,
    repository_root: Path,
    revision: str,
) -> tuple[Path, Path, str, str, _TreeEntry, bytes]:
    root = Path(repository_root).resolve(strict=True)
    target, relative = _lexical_target(path, root)
    commit = repository_revision(root, revision)
    entry = _regular_blob_entry(
        relative,
        _tree_entry(root, commit=commit, relative=relative),
        commit,
    )
    _reject_reparse_ancestry(target, root, relative)
    canonical_bytes = _git(root, ["cat-file", "blob", entry.oid])
    return root, target, relative, commit, entry, canonical_bytes


def is_committed_path(
    path: Path,
    *,
    repository_root: Path,
    revision: str,
) -> bool:
    """Return whether a lexical repository path names a regular blob at one commit."""

    root = Path(repository_root).resolve(strict=True)
    _, relative = _lexical_target(path, root)
    commit = repository_revision(root, revision)
    entry = _tree_entry(root, commit=commit, relative=relative)
    if entry is None:
        return False
    _regular_blob_entry(relative, entry, commit)
    return True


def committed_artifact_candidate(
    path: Path,
    *,
    repository_root: Path,
    revision: str,
) -> CanonicalGitArtifactCandidate:
    """Return a regular committed blob and stable checkout bytes before identity approval."""

    root, target, relative, commit, entry, canonical_bytes = _regular_blob_authority(
        path,
        repository_root=repository_root,
        revision=revision,
    )
    checkout_bytes = _stable_checkout_bytes(target, relative)
    clean_oid = _git(
        root,
        ["hash-object", "--path", relative, "--stdin"],
        input_bytes=checkout_bytes,
    ).decode("ascii", errors="strict").strip()
    if not _FULL_SHA1.fullmatch(clean_oid):
        raise CanonicalGitArtifactError(
            f"Git did not return a clean object identifier for {relative}"
        )
    return CanonicalGitArtifactCandidate(
        repository_relative_path=relative,
        repository_revision=commit,
        blob_oid=entry.oid,
        canonical_bytes=canonical_bytes,
        checkout_bytes=checkout_bytes,
        checkout_clean_oid=clean_oid,
    )


def staged_artifact(
    path: Path,
    *,
    repository_root: Path,
) -> CanonicalGitIndexArtifact:
    """Return canonical index bytes for one explicit, live-matching staged change.

    This is a candidate-review authority, not a fallback from committed ``HEAD``
    authority.  The index entry must differ from ``HEAD`` and the live checkout
    must clean-filter to that exact regular index blob.
    """

    root = Path(repository_root).resolve(strict=True)
    head_revision = repository_revision(root, "HEAD")
    target, relative = _lexical_target(path, root)
    _reject_reparse_ancestry(target, root, relative)
    index_entry = _index_entry(root, relative=relative)
    if index_entry is None:
        if target.is_dir():
            raise CanonicalGitArtifactError(
                f"{relative} checkout path is a directory/tree, not a staged artifact"
            )
        raise CanonicalGitArtifactError(f"{relative} is not present in the index")
    _regular_blob_entry(relative, index_entry, "the index")
    head_entry = _tree_entry(root, commit=head_revision, relative=relative)
    if head_entry is not None and head_entry.oid == index_entry.oid:
        raise CanonicalGitArtifactError(
            f"{relative} is not staged with a blob different from HEAD"
        )
    checkout_bytes = _stable_checkout_bytes(target, relative)
    clean_oid = _git(
        root,
        ["hash-object", "--path", relative, "--stdin"],
        input_bytes=checkout_bytes,
    ).decode("ascii", errors="strict").strip()
    if not _FULL_SHA1.fullmatch(clean_oid):
        raise CanonicalGitArtifactError(
            f"Git did not return a clean object identifier for staged {relative}"
        )
    if clean_oid != index_entry.oid:
        raise CanonicalGitArtifactIdentityMismatch(
            f"{relative} staged index identity mismatch"
        )
    canonical_bytes = _git(root, ["cat-file", "blob", index_entry.oid])
    index_entry_after = _index_entry(root, relative=relative)
    if index_entry_after != index_entry:
        raise CanonicalGitArtifactError(
            f"{relative} index entry changed while staged authority was established"
        )
    return CanonicalGitIndexArtifact(
        repository_relative_path=relative,
        head_revision=head_revision,
        head_blob_oid=head_entry.oid if head_entry is not None else None,
        index_blob_oid=index_entry.oid,
        canonical_bytes=canonical_bytes,
        checkout_bytes=checkout_bytes,
    )


def committed_artifact(
    path: Path,
    *,
    repository_root: Path,
    revision: str,
) -> CanonicalGitArtifact:
    """Return canonical blob bytes only when live bytes retain that Git identity."""

    root, target, relative, commit, entry, canonical_bytes = _regular_blob_authority(
        path,
        repository_root=repository_root,
        revision=revision,
    )
    status_before = target.stat()
    if not stat.S_ISREG(status_before.st_mode):
        raise CanonicalGitArtifactError(f"{relative} checkout path is not a regular file")
    checkout_bytes = target.read_bytes()
    status_after = target.stat()
    if (
        status_before.st_dev,
        status_before.st_ino,
        status_before.st_size,
        status_before.st_mtime_ns,
    ) != (
        status_after.st_dev,
        status_after.st_ino,
        status_after.st_size,
        status_after.st_mtime_ns,
    ):
        raise CanonicalGitArtifactError(
            f"{relative} changed while canonical authority was being established"
        )
    clean_oid = _git(
        root,
        ["hash-object", "--path", relative, "--stdin"],
        input_bytes=checkout_bytes,
    ).decode("ascii", errors="strict").strip()
    if clean_oid != entry.oid:
        raise CanonicalGitArtifactIdentityMismatch(
            f"{relative} canonical Git identity mismatch"
        )
    return CanonicalGitArtifact(
        repository_relative_path=relative,
        repository_revision=commit,
        blob_oid=entry.oid,
        canonical_bytes=canonical_bytes,
        checkout_bytes=checkout_bytes,
    )


def committed_artifacts(
    paths: Iterable[Path],
    *,
    repository_root: Path,
    revision: str,
) -> tuple[CanonicalGitArtifact, ...]:
    """Attest an ordered fixed path set against one verified immutable commit."""

    root = Path(repository_root).resolve(strict=True)
    requested = tuple(_lexical_target(path, root) for path in paths)
    commit = repository_revision(root, revision)
    unique_relatives = tuple(dict.fromkeys(relative for _target, relative in requested))
    tree_entries = _tree_entries(
        root,
        commit=commit,
        relatives=unique_relatives,
    )
    regular_entries: list[_TreeEntry] = []
    for target, relative in requested:
        entry = _regular_blob_entry(relative, tree_entries.get(relative), commit)
        _reject_reparse_ancestry(target, root, relative)
        regular_entries.append(entry)
    canonical_blobs = _canonical_blobs(root, tuple(regular_entries))

    artifacts = []
    for (target, relative), entry in zip(requested, regular_entries, strict=True):
        checkout_bytes = _stable_checkout_bytes(target, relative)
        clean_oid = _git(
            root,
            ["hash-object", "--path", relative, "--stdin"],
            input_bytes=checkout_bytes,
        ).decode("ascii", errors="strict").strip()
        if clean_oid != entry.oid:
            raise CanonicalGitArtifactIdentityMismatch(
                f"{relative} canonical Git identity mismatch"
            )
        artifacts.append(
            CanonicalGitArtifact(
                repository_relative_path=relative,
                repository_revision=commit,
                blob_oid=entry.oid,
                canonical_bytes=canonical_blobs[entry.oid],
                checkout_bytes=checkout_bytes,
            )
        )
    return tuple(artifacts)


def committed_artifact_sha256(
    path: Path,
    *,
    repository_root: Path,
    revision: str,
) -> str:
    """Return the raw SHA-256 identity of a verified committed Git blob."""

    artifact = committed_artifact(
        path,
        repository_root=repository_root,
        revision=revision,
    )
    return hashlib.sha256(artifact.canonical_bytes).hexdigest()
