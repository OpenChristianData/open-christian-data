"""Deep I/O must work without relying on a machine's long-path setting."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import shutil

import pytest

from ocd_kernel.lib import path_io, storage_topology
from ocd_kernel.lib.atomic_io import (
    acquire_jsonl_lock,
    append_jsonl_atomic,
    write_json_atomic,
)
from ocd_kernel.lib.storage_topology import (
    StorageTopologyError,
    repository_relative_path,
    resolve_repo_path,
)
from ocd_kernel.library._common import PipelineError, load_json, within, write_json
from ocd_kernel.reconstruction.destination_policy import (
    DestinationPolicyError,
    preflight_destination,
)
from ocd_kernel.tei.install_accepted import (
    _files,
    _write_json_durable,
    install_accepted_work,
)
from tests.test_install_accepted_work import installation as _installation_fixture
from tests.test_tei_acceptance import WORK_ID

# Make the established installation fixture available to this test module.
installation = _installation_fixture


@pytest.fixture
def legacy_paths(monkeypatch):
    """Reject ordinary deep calls while still performing real prefixed I/O.

    This models legacy MAX_PATH on the already-enabled development machine;
    it does not change the registry or pretend to verify another machine.
    """
    if os.name != "nt":
        pytest.skip("Windows extended-length filesystem regression")

    def reject(value):
        if isinstance(value, (str, bytes, os.PathLike)):
            value = os.fsdecode(value)
            if len(value) >= 260 and not value.startswith("\\\\?\\"):
                raise OSError(errno.ENAMETOOLONG, "legacy path rejected", value)

    for name in (
        "stat",
        "open",
        "mkdir",
        "resolve",
        "glob",
        "rglob",
        "iterdir",
        "rename",
        "replace",
        "unlink",
        "rmdir",
    ):
        original = getattr(Path, name)

        def checked(path, *args, _original=original, _name=name, **kwargs):
            reject(path)
            if _name in {"rename", "replace"} and args:
                reject(args[0])
            return _original(path, *args, **kwargs)

        monkeypatch.setattr(Path, name, checked)
    for name in ("open", "replace", "scandir"):
        original = getattr(os, name)

        def checked_os(*args, _original=original, _name=name, **kwargs):
            for arg in args[: 2 if _name == "replace" else 1]:
                reject(arg)
            return _original(*args, **kwargs)

        monkeypatch.setattr(os, name, checked_os)


def deep_directory(tmp_path):
    path = tmp_path / ("retained-" * 12) / ("edition-" * 12) / ("evidence-" * 6)
    assert len(str(path)) > 300
    path_io.io_path(path).mkdir(parents=True)
    return path


def test_relative_paths_become_absolute_before_io(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    expected = tmp_path / "member.json"
    assert path_io.ordinary_path(path_io.io_path("member.json")) == expected
    assert path_io.io_path(path_io.io_path(expected)) == path_io.io_path(expected)


def test_resolution_preserves_explicit_prefix_only_when_requested(tmp_path):
    physical = path_io.io_path(tmp_path)
    assert path_io.resolve_path(physical, strict=True) == tmp_path
    assert path_io.resolve_path(
        physical, strict=True, preserve_prefix=True
    ) == physical.resolve(strict=True)
    assert path_io.resolve_path(tmp_path, strict=True, preserve_prefix=True) == tmp_path


@pytest.mark.skipif(os.name != "nt", reason="Windows UNC representation")
@pytest.mark.parametrize(
    "value", [r"C:\source\member.json", r"\\server\share\source\member.json"]
)
def test_windows_paths_round_trip_without_filesystem_access(value):
    ordinary = Path(value)
    physical = path_io.io_path(ordinary)
    assert str(physical).startswith("\\\\?\\")
    assert path_io.ordinary_path(physical) == ordinary
    assert path_io.io_path(physical) == physical


def test_deep_json_discovery_and_resolution_keep_logical_paths(tmp_path, legacy_paths):
    directory = deep_directory(tmp_path)
    member = directory / "member.json"
    write_json(member, {"work_id": "fixture"})
    assert load_json(member) == {"work_id": "fixture"}
    for found in (
        list(path_io.io_glob(directory, "*.json")),
        list(path_io.io_rglob(tmp_path, "member.json")),
        list(path_io.io_iterdir(directory)),
    ):
        assert found == [member]
        assert not str(found[0]).startswith("\\\\?\\")
    assert path_io.resolve_path(member, strict=True) == member
    assert within(tmp_path, member.relative_to(tmp_path), field="member") == member
    with pytest.raises(PipelineError, match="relative path"):
        within(tmp_path, "../escape.json", field="member")


def test_deep_storage_routes_keep_logical_identity(tmp_path, legacy_paths):
    repo = deep_directory(tmp_path)
    library = tmp_path / "durable"
    source = library / "raw" / ("source-" * 15) / ("member-" * 15) / "source.txt"
    path_io.io_path(source.parent).mkdir(parents=True)
    path_io.io_path(source).write_bytes(b"retained")
    (path_io.io_path(repo) / ".ocd-storage.json").write_text(
        json.dumps({"library_root": str(library)}), encoding="utf-8"
    )
    logical = source.relative_to(library).as_posix()
    assert resolve_repo_path(repo, logical) == source
    assert repository_relative_path(repo, source) == logical
    assert resolve_repo_path(repo, "data/work.json") == repo / "data/work.json"
    for invalid in (
        "../escape",
        "raw/../data/work.json",
        "raw\\source.txt",
        "C:/outside",
    ):
        with pytest.raises(StorageTopologyError):
            resolve_repo_path(repo, invalid)


def test_deep_atomic_writes_locks_and_journals_remain_readable(tmp_path, legacy_paths):
    directory = deep_directory(tmp_path)
    target = directory / "record.json"
    schema = {
        "type": "object",
        "required": ["value"],
        "properties": {"value": {"type": "integer"}},
    }
    write_json_atomic(target, {"value": 1}, schema)
    assert load_json(target) == {"value": 1}
    with acquire_jsonl_lock(target) as lock:
        assert lock == target.with_name("record.json.lock")
        assert load_json(lock)["target_path"] == str(target)
    assert not path_io.io_path(lock).exists()
    ledger = directory / "ledger.jsonl"
    append_jsonl_atomic(ledger, {"value": 2}, schema)
    assert path_io.io_path(ledger).read_text(encoding="utf-8").strip() == '{"value": 2}'
    _write_json_durable(directory / "operation.json", {"path": str(target)})
    assert load_json(directory / "operation.json")["path"] == str(target)
    assert {p.name for p in path_io.io_iterdir(directory)} == {
        "record.json",
        "ledger.jsonl",
        "operation.json",
    }


def test_deep_installation_copy_retains_names_and_detects_tampering(
    tmp_path, legacy_paths
):
    source = deep_directory(tmp_path)
    member = source / "acquisitions" / "member.json"
    path_io.io_path(member.parent).mkdir()
    path_io.io_path(member).write_bytes(b"pinned")
    incoming = source.parent / "incoming"
    shutil.copytree(path_io.io_path(source), path_io.io_path(incoming))
    assert _files(source) == _files(incoming)
    assert set(_files(incoming)) == {"acquisitions/member.json"}
    path_io.io_path(incoming / "acquisitions/member.json").write_bytes(b"changed")
    assert _files(source) != _files(incoming)


def test_deep_destination_promotion_preserves_ownership_rules(tmp_path, legacy_paths):
    repo = tmp_path / "repo"
    repo.mkdir()
    parent = deep_directory(tmp_path)
    destination = parent / "candidate"
    plan = preflight_destination(repo, destination)
    with plan.stage() as staged:
        path_io.io_path(staged.path / "member.json").write_bytes(b"candidate")
        assert staged.promote() == destination
    assert path_io.io_path(destination / "member.json").read_bytes() == b"candidate"
    blocked = parent / "blocked"
    plan = preflight_destination(repo, blocked)
    with plan.stage() as staged:
        path_io.io_path(blocked).mkdir()
        path_io.io_path(blocked / "owner.txt").write_bytes(b"owner")
        with pytest.raises(DestinationPolicyError, match="appeared"):
            staged.promote()
    assert path_io.io_path(blocked / "owner.txt").read_bytes() == b"owner"


def test_deep_installer_rolls_back_failure_then_installs(
    installation, tmp_path, legacy_paths
):
    original_live, promoted = installation
    parent = deep_directory(tmp_path)
    live, staged = parent / "live", parent / "promoted"
    shutil.copytree(path_io.io_path(original_live), path_io.io_path(live))
    shutil.copytree(path_io.io_path(promoted.destination_root), path_io.io_path(staged))
    work = live / "library/works" / WORK_ID
    before = _files(work)

    def reject_new_live(phase):
        if phase == "after-new-live":
            raise RuntimeError("injected live failure")

    with pytest.raises(RuntimeError, match="injected live failure"):
        install_accepted_work(live, staged, work_id=WORK_ID, fail_at=reject_new_live)
    assert _files(work) == before
    result = install_accepted_work(live, staged, work_id=WORK_ID)
    assert result["status"] == "installed-and-validated"
    assert result["previous_files"] == before
    assert result["installed_files"] == _files(work)
    assert "\\\\?\\" not in json.dumps(result)


def test_cvw_deep_identity_reads_and_session_receipts(tmp_path, legacy_paths):
    from cvw_app.serving_identity import file_identity
    from cvw_app.session_observability import SessionRecorder, sha256_file

    directory = deep_directory(tmp_path)
    source = directory / "retained.txt"
    path_io.io_path(source).write_bytes(b"retained authority")
    identity = file_identity(source)
    assert identity["byte_length"] == len(b"retained authority")
    assert identity["sha256"] == sha256_file(source)
    recorder = SessionRecorder(session_id="fixture", output_dir=directory)
    recorder.write_receipt({"source": str(source)})
    recorder.emit("verified")
    assert not recorder.health.degraded
    assert load_json(recorder.receipt_path)["source"] == str(source)
    assert path_io.io_path(recorder.event_path).is_file()


def test_repository_relative_path_preserves_alias_root_spelling(tmp_path, monkeypatch):
    physical_root = tmp_path / ("physical-" * 12) / ("repository-" * 12)
    alias_root = (
        tmp_path
        / ("alias-" * 18)
        / ("repo-" * 20)
        / ("checkout-" * 12)
    )
    member = physical_root / "data" / "member.json"
    path_io.io_path(member).parent.mkdir(parents=True)
    path_io.io_path(member).write_bytes(b"{}")

    real_resolve_path = path_io.resolve_path

    def resolve_alias(path, **kwargs):
        ordinary = path_io.ordinary_path(path)
        try:
            relative = ordinary.relative_to(alias_root)
        except ValueError:
            return real_resolve_path(path, **kwargs)
        return real_resolve_path(physical_root / relative, **kwargs)

    monkeypatch.setattr(storage_topology, "_resolve", resolve_alias)
    alias_member = alias_root / member.relative_to(physical_root)
    assert len(str(alias_root)) > 260
    assert repository_relative_path(
        path_io.io_path(alias_root), path_io.io_path(alias_member)
    ) == alias_member.relative_to(alias_root).as_posix()
