"""Characterization tests for reconstruction destination-safety behavior.

These tests freeze the direct kernel writer and the staging generic runner.
The runner exercises the shared destination policy after ticket 04 migration;
remaining caller differences are part of the characterized contract.
"""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

import ocd_kernel.reconstruction as reconstruction
import ocd_kernel.reconstruction.contract as contract_module
import ocd_kernel.reconstruction.destination_policy as destination_policy


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "build/tools/reconstruct_candidate.py"
GOVERNED_ROOTS = (
    "raw",
    "data",
    "ir",
    "reports",
    "exports",
    "acceptance",
    "publication",
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = _load_module("_destination_safety_runner", RUNNER_PATH)
CONTRACT_SUPPORT = _load_module(
    "_destination_safety_contract_support",
    ROOT / "tests/test_reconstruction_contract.py",
)
RUNNER_SUPPORT = _load_module(
    "_destination_safety_runner_support",
    ROOT / "tests/test_reconstruct_candidate.py",
)


class _ManifestRoot:
    def __init__(self, root: Path) -> None:
        self.repository_root = root.resolve(strict=True)


def _kernel_preflight(root: Path, destination: Path) -> Path:
    return contract_module._safe_candidate_destination(
        _ManifestRoot(root), destination
    )


def _runner_preflight(root: Path, destination: Path) -> Path:
    plan = RUNNER._destination_policy().preflight_destination(
        root.resolve(strict=True),
        destination,
        appeared_empty="replace",
        repository_lexical="allow_resolved_escape",
    )
    return plan.destination


PREFLIGHTS = (
    pytest.param(_kernel_preflight, id="kernel"),
    pytest.param(_runner_preflight, id="runner"),
)


def _make_directory_reparse(link: Path, target: Path) -> None:
    """Create the strongest available directory reparse for this platform."""

    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError as symlink_error:
        if os.name != "nt":
            pytest.skip(f"directory symlink unavailable: {symlink_error!r}")
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip(
                "directory reparse unavailable: "
                f"symlink={symlink_error!r}; junction_rc={completed.returncode}; "
                f"junction_stderr={completed.stderr.strip()!r}"
            )


@pytest.mark.parametrize("preflight", PREFLIGHTS)
def test_lexical_repository_destination_is_rejected_without_creation(
    tmp_path: Path, preflight
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    destination = root / "candidate"

    with pytest.raises(ValueError):
        preflight(root, destination)

    assert not destination.exists()


@pytest.mark.parametrize("preflight", PREFLIGHTS)
@pytest.mark.parametrize("root_name", GOVERNED_ROOTS)
def test_every_resolved_governed_root_is_independently_rejected_without_mutation(
    tmp_path: Path, preflight, root_name: str
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    external_governed = tmp_path / f"external-{root_name}"
    external_governed.mkdir()
    _make_directory_reparse(root / root_name, external_governed)
    sentinel = external_governed / "owner.txt"
    sentinel.write_bytes(b"owner")
    # The requested path is lexically external and resolves outside the
    # repository.  Only this individual governed-root entry can reject it.
    destination = external_governed / "candidate"

    with pytest.raises(ValueError):
        preflight(root, destination)

    assert sentinel.read_bytes() == b"owner"
    assert not destination.exists()


def test_ungoverned_reparse_escape_records_intentional_lexical_difference(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    external = tmp_path / "external-candidates"
    external.mkdir()
    _make_directory_reparse(root / "escape", external)
    lexical_destination = root / "escape/candidate"

    with pytest.raises(ValueError):
        _kernel_preflight(root, lexical_destination)
    runner_destination = _runner_preflight(root, lexical_destination)

    assert runner_destination == (external / "candidate").resolve(strict=False)
    assert not runner_destination.exists()


def test_external_reparse_into_ungoverned_repository_records_reverse_difference(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    repository_destination_parent = root / "candidate-zone"
    repository_destination_parent.mkdir(parents=True)
    external_alias = tmp_path / "external-alias"
    _make_directory_reparse(external_alias, repository_destination_parent)
    lexical_destination = external_alias / "candidate"

    kernel_destination = _kernel_preflight(root, lexical_destination)
    with pytest.raises(ValueError):
        _runner_preflight(root, lexical_destination)

    assert kernel_destination == (repository_destination_parent / "candidate").resolve(
        strict=False
    )
    assert not kernel_destination.exists()


@pytest.mark.parametrize("preflight", PREFLIGHTS)
def test_absent_parent_is_rejected_without_creation(tmp_path: Path, preflight) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    destination = tmp_path / "missing-parent/candidate"

    with pytest.raises(ValueError):
        preflight(root, destination)

    assert not destination.parent.exists()


@pytest.mark.parametrize("preflight", PREFLIGHTS)
def test_non_directory_target_is_rejected_and_preserved(
    tmp_path: Path, preflight
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    destination = tmp_path / "owner-file"
    destination.write_bytes(b"owner")

    with pytest.raises(ValueError):
        preflight(root, destination)

    assert destination.read_bytes() == b"owner"


@pytest.mark.parametrize("preflight", PREFLIGHTS)
def test_nonempty_directory_is_rejected_and_preserved(
    tmp_path: Path, preflight
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    destination = tmp_path / "occupied"
    destination.mkdir()
    sentinel = destination / "owner.txt"
    sentinel.write_bytes(b"owner")

    with pytest.raises(ValueError):
        preflight(root, destination)

    assert list(destination.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"owner"


@pytest.mark.parametrize("preflight", PREFLIGHTS)
@pytest.mark.parametrize("already_exists", [False, True], ids=["absent", "empty"])
def test_fresh_or_existing_empty_destination_is_accepted_without_creation(
    tmp_path: Path, preflight, already_exists: bool
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    destination = tmp_path / "candidate"
    if already_exists:
        destination.mkdir()

    observed = preflight(root, destination)

    assert observed == destination.resolve(strict=False)
    assert destination.exists() is already_exists


def test_kernel_empty_appearance_race_is_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, converter, _ = CONTRACT_SUPPORT._fixture(tmp_path / "fixture")
    destination = tmp_path / "candidate"
    original = contract_module._safe_candidate_destination

    def appear_empty(source_manifest, requested):
        output = original(source_manifest, requested)
        output.mkdir()
        return output

    monkeypatch.setattr(contract_module, "_safe_candidate_destination", appear_empty)

    candidate = reconstruction.reconstruct(source, destination, converter)

    assert candidate.path == destination.resolve(strict=True)
    assert set(path.name for path in destination.iterdir()) == {
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }


def test_kernel_nonempty_race_overwrites_owner_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, converter, _ = CONTRACT_SUPPORT._fixture(tmp_path / "fixture")
    destination = tmp_path / "candidate"
    original = contract_module._safe_candidate_destination

    def appear_with_owner_member(source_manifest, requested):
        output = original(source_manifest, requested)
        output.mkdir()
        (output / "content.tei.xml").write_bytes(b"owner")
        return output

    monkeypatch.setattr(
        contract_module,
        "_safe_candidate_destination",
        appear_with_owner_member,
    )

    candidate = reconstruction.reconstruct(source, destination, converter)

    assert candidate.member_bytes("content.tei.xml") != b"owner"
    assert candidate.member_bytes("content.tei.xml") == b"<TEI/>\n"


def test_kernel_nonempty_race_preserves_unrecognized_owner_content_but_leaves_candidate_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, converter, _ = CONTRACT_SUPPORT._fixture(tmp_path / "fixture")
    destination = tmp_path / "candidate"
    original = contract_module._safe_candidate_destination

    def appear_with_sentinel(source_manifest, requested):
        output = original(source_manifest, requested)
        output.mkdir()
        (output / "owner.txt").write_bytes(b"owner")
        return output

    monkeypatch.setattr(
        contract_module,
        "_safe_candidate_destination",
        appear_with_sentinel,
    )

    with pytest.raises(ValueError):
        reconstruction.reconstruct(source, destination, converter)

    assert (destination / "owner.txt").read_bytes() == b"owner"
    assert {path.name for path in destination.iterdir()} == {
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "owner.txt",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }
    assert not list(tmp_path.glob(".*.staging-*"))


def test_kernel_appeared_file_race_preserves_owner_file_without_candidate_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, converter, _ = CONTRACT_SUPPORT._fixture(tmp_path / "fixture")
    destination = tmp_path / "candidate"
    original = contract_module._safe_candidate_destination

    def appear_as_owner_file(source_manifest, requested):
        output = original(source_manifest, requested)
        output.write_bytes(b"owner")
        return output

    monkeypatch.setattr(
        contract_module,
        "_safe_candidate_destination",
        appear_as_owner_file,
    )

    with pytest.raises(FileExistsError):
        reconstruction.reconstruct(source, destination, converter)

    assert destination.is_file()
    assert destination.read_bytes() == b"owner"
    assert not list(tmp_path.glob(".*.staging-*"))


def test_kernel_write_failure_leaves_partial_destination_without_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, converter, _ = CONTRACT_SUPPORT._fixture(tmp_path / "fixture")
    destination = tmp_path / "candidate"
    original_write_bytes = Path.write_bytes
    failing_path = contract_module.io_path(destination / "provenance.json")
    failed_writes = []

    def fail_during_write(path: Path, content: bytes) -> int:
        if path == failing_path:
            failed_writes.append(path)
            raise OSError("characterized write failure")
        return original_write_bytes(path, content)

    monkeypatch.setattr(Path, "write_bytes", fail_during_write)

    with pytest.raises(OSError, match="characterized write failure"):
        reconstruction.reconstruct(source, destination, converter)

    assert failed_writes == [failing_path]
    assert {path.name for path in destination.iterdir()} == {
        "README.source.md",
        "content.tei.xml",
    }
    assert not list(tmp_path.glob(".*.staging-*"))


def _runner_run(repo: Path, destination: Path) -> dict[str, object]:
    return RUNNER.run(
        manifest=RUNNER_SUPPORT.MANIFEST,
        destination=str(destination),
        repository_root=str(repo),
    )


def _runner_staging_paths(destination: Path) -> list[Path]:
    return list(destination.parent.glob(f".{destination.name}.staging-*"))


def test_runner_empty_appearance_race_is_replaced_by_completed_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = RUNNER_SUPPORT._synthetic_repository(tmp_path / "fixture")
    destination = tmp_path / "candidate"
    original = destination_policy.preflight_destination

    def appear_empty(
        root: Path,
        value: str,
        *,
        appeared_empty: str,
        repository_lexical: str,
    ):
        assert appeared_empty == "replace"
        assert repository_lexical == "allow_resolved_escape"
        plan = original(
            root,
            value,
            appeared_empty=appeared_empty,
            repository_lexical=repository_lexical,
        )
        plan.destination.mkdir()
        return plan

    monkeypatch.setattr(destination_policy, "preflight_destination", appear_empty)

    summary = _runner_run(repo, destination)

    assert summary["status"] == "pass"
    assert {path.name for path in destination.iterdir()} == {
        "package",
        "text-quality.json",
        "validation.json",
    }
    text_quality_sha256 = hashlib.sha256((destination / "text-quality.json").read_bytes()).hexdigest()
    assert summary["text_quality"]["sha256"] == text_quality_sha256
    assert summary["digests"]["text_quality_sidecar"] == text_quality_sha256
    validation = json.loads((destination / "validation.json").read_bytes())
    assert validation["text_quality_sha256"] == text_quality_sha256
    assert not _runner_staging_paths(destination)


@pytest.mark.parametrize("owner_kind", ["member", "file"], ids=["nonempty-dir", "file"])
def test_runner_appearance_race_preserves_owner_content_and_cleans_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner_kind: str
) -> None:
    repo = RUNNER_SUPPORT._synthetic_repository(tmp_path / "fixture")
    destination = tmp_path / "candidate"
    original = destination_policy.preflight_destination

    def appear_owned(
        root: Path,
        value: str,
        *,
        appeared_empty: str,
        repository_lexical: str,
    ):
        assert appeared_empty == "replace"
        assert repository_lexical == "allow_resolved_escape"
        plan = original(
            root,
            value,
            appeared_empty=appeared_empty,
            repository_lexical=repository_lexical,
        )
        output = plan.destination
        if owner_kind == "member":
            output.mkdir()
            (output / "content.tei.xml").write_bytes(b"owner")
        else:
            output.write_bytes(b"owner")
        return plan

    monkeypatch.setattr(destination_policy, "preflight_destination", appear_owned)

    with pytest.raises(ValueError):
        _runner_run(repo, destination)

    if owner_kind == "member":
        assert (destination / "content.tei.xml").read_bytes() == b"owner"
        assert list(destination.iterdir()) == [destination / "content.tei.xml"]
    else:
        assert destination.read_bytes() == b"owner"
    assert not _runner_staging_paths(destination)


def test_runner_validation_failure_cleans_staging_and_preserves_empty_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = RUNNER_SUPPORT._synthetic_repository(tmp_path / "fixture")
    destination = tmp_path / "candidate"
    destination.mkdir()

    def fail_validation(*_args, **_kwargs):
        raise RuntimeError("characterized validation failure")

    monkeypatch.setattr(contract_module, "validate", fail_validation)

    with pytest.raises(RuntimeError):
        _runner_run(repo, destination)

    assert destination.is_dir()
    assert not list(destination.iterdir())
    assert not _runner_staging_paths(destination)


def test_runner_member_write_failure_preserves_appeared_owner_and_cleans_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = RUNNER_SUPPORT._synthetic_repository(tmp_path / "fixture")
    destination = tmp_path / "candidate"
    original_preflight = destination_policy.preflight_destination
    original_write_bytes = Path.write_bytes

    def appear_with_owner(
        root: Path,
        value: str,
        *,
        appeared_empty: str,
        repository_lexical: str,
    ):
        assert appeared_empty == "replace"
        assert repository_lexical == "allow_resolved_escape"
        plan = original_preflight(
            root,
            value,
            appeared_empty=appeared_empty,
            repository_lexical=repository_lexical,
        )
        output = plan.destination
        output.mkdir()
        (output / "owner.txt").write_bytes(b"owner")
        return plan

    def fail_staged_member_write(path: Path, content: bytes) -> int:
        staging = path.parent.parent
        if (
            path.name == "provenance.json"
            and path.parent.name == "package"
            and staging.name.startswith(f".{destination.name}.staging-")
        ):
            raise OSError("characterized staged member write failure")
        return original_write_bytes(path, content)

    monkeypatch.setattr(
        destination_policy,
        "preflight_destination",
        appear_with_owner,
    )
    monkeypatch.setattr(Path, "write_bytes", fail_staged_member_write)

    with pytest.raises(OSError):
        _runner_run(repo, destination)

    assert list(destination.iterdir()) == [destination / "owner.txt"]
    assert (destination / "owner.txt").read_bytes() == b"owner"
    assert not _runner_staging_paths(destination)
