"""Focused contract tests for the shared reconstruction destination policy."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess

import pytest

from ocd_kernel.reconstruction.destination_policy import (
    DestinationPolicyError,
    preflight_destination,
)


GOVERNED_ROOTS = (
    "raw",
    "data",
    "ir",
    "reports",
    "exports",
    "acceptance",
    "publication",
)


def _make_directory_reparse(link: Path, target: Path) -> None:
    """Create a physical directory symlink or Windows junction."""

    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError as symlink_error:
        if os.name != "nt":
            pytest.skip(f"directory symlink unavailable: {symlink_error!r}")
        try:
            subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as junction_error:
            pytest.skip(
                "directory reparse unavailable: "
                f"symlink={symlink_error!r}; "
                f"junction_rc={junction_error.returncode}; "
                f"junction_stderr={junction_error.stderr.strip()!r}"
            )


def _remove_directory_reparse(link: Path) -> None:
    if link.is_symlink():
        link.unlink()
    else:
        link.rmdir()


def _entry_identity(path: Path) -> tuple[int, int]:
    entry = path.stat(follow_symlinks=False)
    return entry.st_dev, entry.st_ino


def _is_directory_reparse(path: Path) -> bool:
    entry = path.stat(follow_symlinks=False)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(
        getattr(entry, "st_file_attributes", 0) & reparse_flag
    )


@pytest.mark.parametrize("appeared_empty", ["preserve", "replace"])
def test_preflight_rejects_lexical_repository_destination_without_creation(
    tmp_path: Path,
    appeared_empty: str,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    destination = repository / "candidate"

    with pytest.raises(ValueError):
        preflight_destination(
            repository,
            destination,
            appeared_empty=appeared_empty,
        )

    assert not destination.exists()


def test_preflight_rejects_resolved_repository_destination_through_reparse(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    destination_parent = repository / "candidate-zone"
    destination_parent.mkdir(parents=True)
    external_alias = tmp_path / "external-alias"
    _make_directory_reparse(external_alias, destination_parent)
    destination = external_alias / "candidate"

    with pytest.raises(ValueError):
        preflight_destination(
            repository,
            destination,
            appeared_empty="replace",
            repository_lexical="allow_resolved_escape",
        )

    assert not destination.exists()


def test_preflight_rejects_lexical_repository_escape_through_reparse(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    _make_directory_reparse(repository / "escape", external)
    destination = repository / "escape/candidate"

    with pytest.raises(ValueError):
        preflight_destination(repository, destination)

    assert not (external / "candidate").exists()


@pytest.mark.parametrize("appeared_empty", ["preserve", "replace"])
def test_explicit_mode_allows_lexical_repository_escape_to_ungoverned_external(
    tmp_path: Path,
    appeared_empty: str,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    _make_directory_reparse(repository / "escape", external)
    destination = repository / "escape/candidate"

    plan = preflight_destination(
        repository,
        destination,
        appeared_empty=appeared_empty,
        repository_lexical="allow_resolved_escape",
    )

    assert plan.repository_lexical == "allow_resolved_escape"
    assert plan.destination == (external / "candidate").resolve(strict=False)
    with plan.stage() as staged:
        (staged.path / "result.txt").write_bytes(b"complete")
        staged.promote()
    assert (external / "candidate/result.txt").read_bytes() == b"complete"


@pytest.mark.parametrize("appeared_empty", ["preserve", "replace"])
@pytest.mark.parametrize(
    "repository_lexical",
    ["reject", "allow_resolved_escape"],
)
def test_reparsed_repository_root_cannot_lexically_escape_governed_storage(
    tmp_path: Path,
    appeared_empty: str,
    repository_lexical: str,
) -> None:
    actual_repository = tmp_path / "actual-repository"
    actual_repository.mkdir()
    repository_alias = tmp_path / "repository-alias"
    _make_directory_reparse(repository_alias, actual_repository)
    governed_target = tmp_path / "governed-target"
    governed_target.mkdir()
    _make_directory_reparse(actual_repository / "raw", governed_target)
    external = tmp_path / "external"
    external.mkdir()
    _make_directory_reparse(governed_target / "escape", external)
    destination = repository_alias / "raw/escape/candidate"

    with pytest.raises(DestinationPolicyError):
        preflight_destination(
            repository_alias,
            destination,
            appeared_empty=appeared_empty,
            repository_lexical=repository_lexical,
        )

    assert repository_alias.resolve(strict=True) == actual_repository.resolve(
        strict=True
    )
    assert (actual_repository / "raw").resolve(strict=True) == (
        governed_target.resolve(strict=True)
    )
    assert (governed_target / "escape").resolve(strict=True) == external.resolve(
        strict=True
    )
    assert not (external / "candidate").exists()


@pytest.mark.parametrize("root_name", GOVERNED_ROOTS)
@pytest.mark.parametrize("appeared_empty", ["preserve", "replace"])
@pytest.mark.parametrize(
    "repository_lexical",
    ["reject", "allow_resolved_escape"],
)
def test_preflight_rejects_each_resolved_governed_root_without_mutation(
    tmp_path: Path,
    root_name: str,
    appeared_empty: str,
    repository_lexical: str,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    governed_target = tmp_path / f"governed-{root_name}"
    governed_target.mkdir()
    _make_directory_reparse(repository / root_name, governed_target)
    sentinel = governed_target / "owner.txt"
    sentinel.write_bytes(b"owner")
    destination = governed_target / "candidate"

    with pytest.raises(ValueError):
        preflight_destination(
            repository,
            destination,
            appeared_empty=appeared_empty,
            repository_lexical=repository_lexical,
        )

    assert sentinel.read_bytes() == b"owner"
    assert not destination.exists()


@pytest.mark.parametrize("root_name", GOVERNED_ROOTS)
@pytest.mark.parametrize(
    "repository_lexical",
    ["reject", "allow_resolved_escape"],
)
def test_preflight_rejects_lexical_governed_root_escape_through_reparse(
    tmp_path: Path,
    root_name: str,
    repository_lexical: str,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    governed_target = tmp_path / f"governed-{root_name}"
    governed_target.mkdir()
    _make_directory_reparse(repository / root_name, governed_target)
    outward_target = tmp_path / f"outward-{root_name}"
    outward_target.mkdir()
    escape = governed_target / "escape"
    _make_directory_reparse(escape, outward_target)
    destination = governed_target / "escape/candidate"

    with pytest.raises(ValueError):
        preflight_destination(
            repository,
            destination,
            repository_lexical=repository_lexical,
        )

    assert escape.resolve(strict=True) == outward_target.resolve(strict=True)
    assert not (outward_target / "candidate").exists()


def test_preflight_allows_ungoverned_external_reparse(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    alias = tmp_path / "external-alias"
    _make_directory_reparse(alias, external)
    destination = alias / "candidate"

    plan = preflight_destination(repository, destination)

    assert plan.destination == (external / "candidate").resolve(strict=False)
    assert not plan.destination.exists()


def test_plan_retains_distinct_lexical_and_resolved_repository_roots(
    tmp_path: Path,
) -> None:
    actual_repository = tmp_path / "actual-repository"
    actual_repository.mkdir()
    repository_alias = tmp_path / "repository-alias"
    _make_directory_reparse(repository_alias, actual_repository)
    destination = tmp_path / "candidate"

    plan = preflight_destination(repository_alias, destination)

    assert plan.lexical_repository_root == Path(
        os.path.abspath(os.fspath(repository_alias))
    )
    assert plan.repository_root == actual_repository.resolve(strict=True)


def test_preflight_rejects_final_reparse_to_empty_target_and_preserves_owner(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    target = tmp_path / "owner-target"
    target.mkdir()
    destination = tmp_path / "candidate"
    _make_directory_reparse(destination, target)
    owner_identity = _entry_identity(destination)

    with pytest.raises(ValueError):
        preflight_destination(
            repository,
            destination,
            repository_lexical="allow_resolved_escape",
        )

    assert _is_directory_reparse(destination)
    assert _entry_identity(destination) == owner_identity
    assert destination.resolve(strict=True) == target.resolve(strict=True)
    assert not list(target.iterdir())


def test_preflight_rejects_broken_final_reparse_and_preserves_owner_entry(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    missing_target = tmp_path / "missing-owner-target"
    destination = tmp_path / "candidate"
    _make_directory_reparse(destination, missing_target)
    owner_identity = _entry_identity(destination)

    with pytest.raises(ValueError):
        preflight_destination(
            repository,
            destination,
            repository_lexical="allow_resolved_escape",
        )

    assert os.path.lexists(destination)
    assert _is_directory_reparse(destination)
    assert _entry_identity(destination) == owner_identity
    assert not missing_target.exists()


def test_preflight_rejects_absent_parent_without_creation(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    destination = tmp_path / "missing/candidate"

    with pytest.raises(ValueError):
        preflight_destination(repository, destination)

    assert not destination.parent.exists()


@pytest.mark.parametrize(
    "repository_lexical",
    ["reject", "allow_resolved_escape"],
)
def test_preflight_rejects_file_and_preserves_bytes(
    tmp_path: Path,
    repository_lexical: str,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    destination = tmp_path / "owner-file"
    destination.write_bytes(b"owner")

    with pytest.raises(ValueError):
        preflight_destination(
            repository,
            destination,
            repository_lexical=repository_lexical,
        )

    assert destination.read_bytes() == b"owner"


@pytest.mark.parametrize(
    "repository_lexical",
    ["reject", "allow_resolved_escape"],
)
def test_preflight_rejects_nonempty_directory_and_preserves_owner(
    tmp_path: Path,
    repository_lexical: str,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    destination = tmp_path / "occupied"
    destination.mkdir()
    sentinel = destination / "owner.txt"
    sentinel.write_bytes(b"owner")

    with pytest.raises(ValueError):
        preflight_destination(
            repository,
            destination,
            repository_lexical=repository_lexical,
        )

    assert list(destination.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"owner"


@pytest.mark.parametrize("already_exists", [False, True], ids=["absent", "empty"])
def test_preflight_accepts_absent_or_empty_destination_without_mutation(
    tmp_path: Path,
    already_exists: bool,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    destination = tmp_path / "candidate"
    if already_exists:
        destination.mkdir()

    plan = preflight_destination(repository, destination)

    assert plan.destination == destination.resolve(strict=False)
    assert plan.destination_existed is already_exists
    assert plan.appeared_empty == "preserve"
    assert plan.repository_lexical == "reject"
    assert destination.exists() is already_exists


@pytest.mark.parametrize("mode", [None, "", "remove", 1])
def test_preflight_rejects_invalid_appeared_empty_mode_without_mutation(
    tmp_path: Path,
    mode: object,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    destination = tmp_path / "candidate"

    with pytest.raises(DestinationPolicyError):
        preflight_destination(repository, destination, appeared_empty=mode)

    assert not destination.exists()


@pytest.mark.parametrize("mode", [None, "", "allow", 1])
def test_preflight_rejects_invalid_repository_lexical_mode_without_mutation(
    tmp_path: Path,
    mode: object,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    destination = tmp_path / "candidate"

    with pytest.raises(DestinationPolicyError):
        preflight_destination(repository, destination, repository_lexical=mode)

    assert not destination.exists()


def test_staging_promotes_complete_content_to_preflight_absent_destination(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    destination = tmp_path / "candidate"
    plan = preflight_destination(repository, destination)

    with plan.stage() as staged:
        staged_path = staged.path
        (staged.path / "result.txt").write_bytes(b"complete")
        promoted = staged.promote()

    assert promoted == destination.resolve(strict=True)
    assert (destination / "result.txt").read_bytes() == b"complete"
    assert not staged_path.exists()


@pytest.mark.parametrize("appeared_empty", ["preserve", "replace"])
def test_construction_failure_cleans_owned_staging_and_leaves_absent_destination(
    tmp_path: Path,
    appeared_empty: str,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    destination = tmp_path / "candidate"
    plan = preflight_destination(
        repository,
        destination,
        appeared_empty=appeared_empty,
    )
    staged_path: Path | None = None

    with pytest.raises(RuntimeError, match="construction failed"):
        with plan.stage() as staged:
            staged_path = staged.path
            (staged.path / "partial.txt").write_bytes(b"partial")
            raise RuntimeError("construction failed")

    assert staged_path is not None and not staged_path.exists()
    assert not destination.exists()


@pytest.mark.parametrize(
    "appeared_kind",
    ["empty-directory", "nonempty-directory", "file"],
)
def test_promotion_rejects_and_preserves_every_appeared_destination_state(
    tmp_path: Path,
    appeared_kind: str,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    destination = tmp_path / "candidate"
    plan = preflight_destination(repository, destination)
    staged_path: Path | None = None

    with pytest.raises(ValueError):
        with plan.stage() as staged:
            staged_path = staged.path
            (staged.path / "result.txt").write_bytes(b"complete")
            if appeared_kind == "empty-directory":
                destination.mkdir()
            elif appeared_kind == "nonempty-directory":
                destination.mkdir()
                (destination / "owner.txt").write_bytes(b"owner")
            else:
                destination.write_bytes(b"owner")
            staged.promote()

    assert staged_path is not None and not staged_path.exists()
    if appeared_kind == "empty-directory":
        assert destination.is_dir()
        assert not list(destination.iterdir())
    elif appeared_kind == "nonempty-directory":
        assert list(destination.iterdir()) == [destination / "owner.txt"]
        assert (destination / "owner.txt").read_bytes() == b"owner"
    else:
        assert destination.is_file()
        assert destination.read_bytes() == b"owner"


def test_replace_mode_promotes_over_late_ordinary_empty_directory(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    destination = tmp_path / "candidate"
    plan = preflight_destination(
        repository,
        destination,
        appeared_empty="replace",
        repository_lexical="allow_resolved_escape",
    )

    with plan.stage() as staged:
        staged_path = staged.path
        (staged.path / "result.txt").write_bytes(b"complete")
        destination.mkdir()
        promoted = staged.promote()

    assert promoted == destination.resolve(strict=True)
    assert (destination / "result.txt").read_bytes() == b"complete"
    assert not staged_path.exists()


@pytest.mark.parametrize("appeared_kind", ["nonempty-directory", "file"])
def test_replace_mode_rejects_and_preserves_late_owned_content(
    tmp_path: Path,
    appeared_kind: str,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    destination = tmp_path / "candidate"
    plan = preflight_destination(
        repository,
        destination,
        appeared_empty="replace",
        repository_lexical="allow_resolved_escape",
    )

    with pytest.raises(DestinationPolicyError):
        with plan.stage() as staged:
            staged_path = staged.path
            (staged.path / "result.txt").write_bytes(b"complete")
            if appeared_kind == "nonempty-directory":
                destination.mkdir()
                (destination / "owner.txt").write_bytes(b"owner")
            else:
                destination.write_bytes(b"owner")
            staged.promote()

    assert not staged_path.exists()
    if appeared_kind == "nonempty-directory":
        assert list(destination.iterdir()) == [destination / "owner.txt"]
        assert (destination / "owner.txt").read_bytes() == b"owner"
    else:
        assert destination.read_bytes() == b"owner"


@pytest.mark.parametrize("target_state", ["empty", "missing"])
def test_replace_mode_rejects_late_final_reparse_and_preserves_owner_entry(
    tmp_path: Path,
    target_state: str,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    destination = tmp_path / "candidate"
    target = tmp_path / "owner-target"
    if target_state == "empty":
        target.mkdir()
    plan = preflight_destination(
        repository,
        destination,
        appeared_empty="replace",
        repository_lexical="allow_resolved_escape",
    )

    with pytest.raises(DestinationPolicyError):
        with plan.stage() as staged:
            staged_path = staged.path
            (staged.path / "result.txt").write_bytes(b"complete")
            _make_directory_reparse(destination, target)
            owner_identity = _entry_identity(destination)
            staged.promote()

    assert not staged_path.exists()
    assert os.path.lexists(destination)
    assert _is_directory_reparse(destination)
    assert _entry_identity(destination) == owner_identity
    if target_state == "empty":
        assert not list(target.iterdir())
    else:
        assert not target.exists()


def test_preflight_existing_empty_destination_is_replaced_only_if_unchanged(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    destination = tmp_path / "candidate"
    destination.mkdir()
    plan = preflight_destination(repository, destination)

    with plan.stage() as staged:
        (staged.path / "result.txt").write_bytes(b"complete")
        staged.promote()

    assert (destination / "result.txt").read_bytes() == b"complete"


def test_preflight_existing_empty_destination_is_preserved_on_construction_failure(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    destination = tmp_path / "candidate"
    destination.mkdir()
    plan = preflight_destination(repository, destination)
    staged_path: Path | None = None

    with pytest.raises(RuntimeError, match="validation failed"):
        with plan.stage() as staged:
            staged_path = staged.path
            (staged.path / "result.txt").write_bytes(b"complete")
            raise RuntimeError("validation failed")

    assert destination.is_dir() and not list(destination.iterdir())
    assert staged_path is not None and not staged_path.exists()


@pytest.mark.parametrize("appeared_empty", ["preserve", "replace"])
def test_promotion_rejects_changed_preflight_empty_destination_and_preserves_owner(
    tmp_path: Path,
    appeared_empty: str,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    destination = tmp_path / "candidate"
    destination.mkdir()
    plan = preflight_destination(
        repository,
        destination,
        appeared_empty=appeared_empty,
        repository_lexical="allow_resolved_escape",
    )

    with pytest.raises(ValueError):
        with plan.stage() as staged:
            (staged.path / "result.txt").write_bytes(b"complete")
            (destination / "owner.txt").write_bytes(b"owner")
            staged.promote()

    assert list(destination.iterdir()) == [destination / "owner.txt"]
    assert (destination / "owner.txt").read_bytes() == b"owner"


@pytest.mark.parametrize("appeared_empty", ["preserve", "replace"])
def test_promotion_revalidates_physical_reparse_target_and_cleans_staging(
    tmp_path: Path,
    appeared_empty: str,
) -> None:
    repository = tmp_path / "repo"
    repository_target = repository / "candidate-zone"
    repository_target.mkdir(parents=True)
    first_target = tmp_path / "first-target"
    first_target.mkdir()
    alias = tmp_path / "candidate-alias"
    _make_directory_reparse(alias, first_target)
    requested = alias / "candidate"
    plan = preflight_destination(
        repository,
        requested,
        appeared_empty=appeared_empty,
    )
    staged_path: Path | None = None

    with pytest.raises(ValueError):
        with plan.stage() as staged:
            staged_path = staged.path
            (staged.path / "result.txt").write_bytes(b"complete")
            _remove_directory_reparse(alias)
            _make_directory_reparse(alias, repository_target)
            staged.promote()

    assert requested.resolve(strict=False) == (
        repository_target / "candidate"
    ).resolve(strict=False)
    assert not requested.exists()
    assert staged_path is not None and not staged_path.exists()


def test_staging_revalidates_physical_reparse_target_before_creation(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository_target = repository / "candidate-zone"
    repository_target.mkdir(parents=True)
    first_target = tmp_path / "first-target"
    first_target.mkdir()
    alias = tmp_path / "candidate-alias"
    _make_directory_reparse(alias, first_target)
    requested = alias / "candidate"
    plan = preflight_destination(repository, requested)
    _remove_directory_reparse(alias)
    _make_directory_reparse(alias, repository_target)

    with pytest.raises(ValueError):
        plan.stage()

    assert not list(first_target.iterdir())
    assert not list(repository_target.iterdir())


def test_allow_mode_rejects_inside_repository_retarget_before_staging(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository_target = repository / "candidate-zone"
    repository_target.mkdir(parents=True)
    first_target = tmp_path / "first-target"
    first_target.mkdir()
    alias = repository / "escape"
    _make_directory_reparse(alias, first_target)
    requested = alias / "candidate"
    plan = preflight_destination(
        repository,
        requested,
        repository_lexical="allow_resolved_escape",
    )

    _remove_directory_reparse(alias)
    _make_directory_reparse(alias, repository_target)

    with pytest.raises(DestinationPolicyError):
        plan.stage()

    assert not list(first_target.iterdir())
    assert not list(repository_target.iterdir())


def test_allow_mode_rejects_inside_repository_retarget_before_promotion(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository_target = repository / "candidate-zone"
    repository_target.mkdir(parents=True)
    first_target = tmp_path / "first-target"
    first_target.mkdir()
    alias = repository / "escape"
    _make_directory_reparse(alias, first_target)
    requested = alias / "candidate"
    plan = preflight_destination(
        repository,
        requested,
        repository_lexical="allow_resolved_escape",
    )

    with pytest.raises(DestinationPolicyError):
        with plan.stage() as staged:
            staged_path = staged.path
            (staged.path / "result.txt").write_bytes(b"complete")
            _remove_directory_reparse(alias)
            _make_directory_reparse(alias, repository_target)
            staged.promote()

    assert not list(first_target.iterdir())
    assert not list(repository_target.iterdir())
    assert not staged_path.exists()


def test_allow_mode_default_preserve_rejects_late_empty_directory(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    alias = repository / "escape"
    _make_directory_reparse(alias, external)
    requested = alias / "candidate"
    plan = preflight_destination(
        repository,
        requested,
        repository_lexical="allow_resolved_escape",
    )

    with pytest.raises(DestinationPolicyError):
        with plan.stage() as staged:
            staged_path = staged.path
            (staged.path / "result.txt").write_bytes(b"complete")
            requested.mkdir()
            staged.promote()

    assert requested.is_dir() and not list(requested.iterdir())
    assert not staged_path.exists()
