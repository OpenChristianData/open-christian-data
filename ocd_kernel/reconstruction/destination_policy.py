"""Filesystem-only policy for reconstruction candidate destinations.

The policy owns path containment and destination ownership checks.  It does
not reconstruct, validate, accept, or publish candidates.  Caller migrations
are separately owned and reviewed; importing this shared policy does not imply
that any caller migration has been accepted.
"""

from __future__ import annotations

from ocd_kernel.lib.path_io import io_path, ordinary_path, resolve_path, io_iterdir

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Literal


__all__ = [
    "AppearedEmptyMode",
    "DestinationPlan",
    "DestinationPolicyError",
    "RepositoryLexicalMode",
    "StagedDestination",
    "preflight_destination",
]


AppearedEmptyMode = Literal["preserve", "replace"]
RepositoryLexicalMode = Literal["reject", "allow_resolved_escape"]


class DestinationPolicyError(ValueError):
    """The requested destination cannot be used without risking owner data."""


@dataclass(frozen=True, slots=True)
class DestinationPlan:
    """A destination accepted by the shared preflight policy.

    ``destination_existed`` records whether the resolved destination was an
    existing empty directory at preflight.  The default ``appeared_empty``
    mode preserves and rejects every entry that appears after an absent
    preflight.  Explicit ``"replace"`` permits promotion to replace only a
    late ordinary, non-reparse empty directory; every other appeared entry is
    rejected and preserved.  ``repository_lexical`` is also immutable:
    default ``"reject"`` rejects requested paths lexically inside the
    repository, while explicit ``"allow_resolved_escape"`` permits only such
    a requested path whose resolved destination is outside the repository and
    every governed root.  ``lexical_repository_root`` retains the original
    requested repository-root form separately from the resolved
    ``repository_root`` so both remain protected through every recheck.
    """

    lexical_repository_root: Path
    repository_root: Path
    destination: Path
    destination_existed: bool
    appeared_empty: AppearedEmptyMode
    repository_lexical: RepositoryLexicalMode
    _requested_destination: Path
    _destination_identity: tuple[int, int] | None

    def stage(self) -> "StagedDestination":
        """Create one owned sibling staging directory for this plan."""

        return StagedDestination._create(self)


_GOVERNED_ROOT_NAMES = (
    "raw",
    "data",
    "ir",
    "reports",
    "exports",
    "acceptance",
    "publication",
)


def _reject_if_contained(path: Path, root: Path, message: str) -> None:
    try:
        path.relative_to(root)
    except ValueError:
        return
    raise DestinationPolicyError(message)


def _identity(path: Path) -> tuple[int, int]:
    stat = io_path(path).stat(follow_symlinks=False)
    return stat.st_dev, stat.st_ino


def _entry_exists(path: Path) -> bool:
    return os.path.lexists(io_path(os.fspath(path)))


def _is_reparse_point(path: Path) -> bool:
    if not _entry_exists(path):
        return False
    entry = io_path(path).stat(follow_symlinks=False)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return io_path(path).is_symlink() or bool(
        getattr(entry, "st_file_attributes", 0) & reparse_flag
    )


def _resolved_destination(
    lexical_repository_root: Path,
    repository_root: Path,
    requested_destination: Path,
    repository_lexical: RepositoryLexicalMode,
) -> Path:
    if _is_reparse_point(requested_destination):
        raise DestinationPolicyError(
            "candidate destination final entry must not be a reparse point"
        )
    resolved = resolve_path(requested_destination, strict=False)
    if repository_lexical == "reject":
        for lexical_root_form in (
            lexical_repository_root,
            repository_root,
        ):
            _reject_if_contained(
                requested_destination,
                lexical_root_form,
                "candidate destination must be lexically outside the repository",
            )
    _reject_if_contained(
        resolved,
        repository_root,
        "candidate destination must resolve outside the repository",
    )
    for name in _GOVERNED_ROOT_NAMES:
        lexical_governed_root = lexical_repository_root / name
        physical_governed_root = repository_root / name
        resolved_governed_root = resolve_path(physical_governed_root, strict=False)
        for governed_root_form in (
            lexical_governed_root,
            physical_governed_root,
            resolved_governed_root,
        ):
            _reject_if_contained(
                requested_destination,
                governed_root_form,
                "candidate destination is lexically inside governed storage",
            )
        _reject_if_contained(
            resolved,
            resolved_governed_root,
            "candidate destination resolves inside governed storage",
        )
    return resolved


class StagedDestination:
    """One policy-owned staging directory with fail-closed promotion.

    Use as a context manager.  Exiting without successful promotion removes
    only the exact staging directory created by the policy.  The final
    destination is never cleaned up on failure.
    """

    def __init__(
        self,
        plan: DestinationPlan,
        path: Path,
        identity: tuple[int, int],
    ) -> None:
        self._plan = plan
        self.path = path
        self._identity = identity
        self._promoted = False

    @classmethod
    def _create(cls, plan: DestinationPlan) -> "StagedDestination":
        current = _resolved_destination(
            plan.lexical_repository_root,
            plan.repository_root,
            plan._requested_destination,
            plan.repository_lexical,
        )
        if current != plan.destination or not io_path(plan.destination.parent).is_dir():
            raise DestinationPolicyError(
                "candidate destination path changed before staging"
            )
        path = ordinary_path(Path(
            tempfile.mkdtemp(
                prefix=f".{plan.destination.name}.staging-",
                dir=io_path(plan.destination.parent),
            )
        ))
        return cls(plan, path, _identity(path))

    def __enter__(self) -> "StagedDestination":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.cleanup()

    def _require_owned_staging(self) -> None:
        if not _entry_exists(self.path):
            raise DestinationPolicyError("owned staging directory disappeared")
        if not io_path(self.path).is_dir() or _identity(self.path) != self._identity:
            raise DestinationPolicyError("owned staging directory identity changed")

    def cleanup(self) -> None:
        """Remove an unpromoted staging tree without touching final output."""

        if self._promoted or not _entry_exists(self.path):
            return
        self._require_owned_staging()
        shutil.rmtree(io_path(self.path))

    def promote(self) -> Path:
        """Atomically rename complete staging after race revalidation.

        The recheck cannot create a general cross-process lock around the
        final observation/removal/rename sequence.  Default ``"preserve"``
        rejects and preserves every destination entry observed after an absent
        preflight.  Explicit ``"replace"`` may replace only a late ordinary,
        non-reparse empty directory; every other appeared entry remains
        rejected and preserved.
        """

        if self._promoted:
            raise DestinationPolicyError("staging directory was already promoted")
        self._require_owned_staging()
        current = _resolved_destination(
            self._plan.lexical_repository_root,
            self._plan.repository_root,
            self._plan._requested_destination,
            self._plan.repository_lexical,
        )
        if current != self._plan.destination:
            raise DestinationPolicyError(
                "candidate destination resolved path changed after preflight"
            )

        destination = self._plan.destination
        if self._plan.destination_existed:
            if (
                not _entry_exists(destination)
                or not io_path(destination).is_dir()
                or any(io_iterdir(destination))
                or _identity(destination) != self._plan._destination_identity
            ):
                raise DestinationPolicyError(
                    "preflight empty destination changed before promotion"
                )
            io_path(destination).rmdir()
        elif _entry_exists(destination):
            replace_late_empty = (
                self._plan.appeared_empty == "replace"
                and io_path(destination).is_dir()
                and not _is_reparse_point(destination)
                and not any(io_iterdir(destination))
            )
            if not replace_late_empty:
                raise DestinationPolicyError(
                    "candidate destination appeared after preflight"
                )
            io_path(destination).rmdir()

        io_path(self.path).replace(io_path(destination))
        self._promoted = True
        return resolve_path(destination, strict=True)


def preflight_destination(
    repository_root: str | Path,
    destination: str | Path,
    *,
    appeared_empty: AppearedEmptyMode = "preserve",
    repository_lexical: RepositoryLexicalMode = "reject",
) -> DestinationPlan:
    """Validate one requested candidate destination without changing it.

    ``appeared_empty="preserve"`` rejects and preserves every final entry that
    appears after an absent preflight.  The explicit ``"replace"`` mode allows
    promotion to replace only a late ordinary empty directory; every other
    appeared state remains protected.  ``repository_lexical="reject"`` keeps
    lexical repository containment fail-closed; the explicit
    ``"allow_resolved_escape"`` compatibility mode permits a requested path
    lexically inside the repository only when its resolved destination is
    external.  It does not relax lexical or resolved governed-root checks,
    resolved repository containment, or destination ownership behavior.
    """

    if appeared_empty not in ("preserve", "replace"):
        raise DestinationPolicyError(
            "appeared_empty must be either 'preserve' or 'replace'"
        )
    if repository_lexical not in ("reject", "allow_resolved_escape"):
        raise DestinationPolicyError(
            "repository_lexical must be either 'reject' or "
            "'allow_resolved_escape'"
        )

    lexical_root = Path(os.path.abspath(os.fspath(repository_root)))
    if not io_path(lexical_root).is_dir():
        raise DestinationPolicyError("repository root must be an existing directory")
    resolved_root = resolve_path(lexical_root, strict=True)
    lexical_destination = Path(os.path.abspath(os.fspath(destination)))
    resolved_destination = _resolved_destination(
        lexical_root,
        resolved_root,
        lexical_destination,
        repository_lexical,
    )

    if not io_path(resolved_destination.parent).is_dir():
        raise DestinationPolicyError(
            "candidate destination parent must already be a directory"
        )
    destination_existed = io_path(resolved_destination).exists()
    if destination_existed and (
        not io_path(resolved_destination).is_dir() or any(io_iterdir(resolved_destination))
    ):
        raise DestinationPolicyError(
            "candidate destination must be absent or an empty directory"
        )
    return DestinationPlan(
        lexical_repository_root=lexical_root,
        repository_root=resolved_root,
        destination=resolved_destination,
        destination_existed=destination_existed,
        appeared_empty=appeared_empty,
        repository_lexical=repository_lexical,
        _requested_destination=lexical_destination,
        _destination_identity=(
            _identity(resolved_destination) if destination_existed else None
        ),
    )
