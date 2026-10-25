"""Tests for the explicit local OCD data-plane boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ocd_kernel.lib.storage_topology import (
    StorageTopologyError,
    configured_external_path,
    repository_relative_path,
    resolve_repo_path,
)


def _configure_library(repo_root: Path, library_root: Path) -> None:
    (repo_root / ".ocd-storage.json").write_text(
        json.dumps({"library_root": str(library_root)}),
        encoding="utf-8",
    )


def test_configured_library_routes_only_external_data_plane_roots(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    library_root = tmp_path / "library"
    repo_root.mkdir()
    (repo_root / "data").mkdir()
    (repo_root / "data" / "canonical.json").write_text("repo", encoding="utf-8")
    (library_root / "raw" / "witnesses").mkdir(parents=True)
    raw_witness = library_root / "raw" / "witnesses" / "source.txt"
    raw_witness.write_text("library", encoding="utf-8")
    (library_root / "reports").mkdir()
    report = library_root / "reports" / "audit.json"
    report.write_text("library", encoding="utf-8")
    (library_root / "exports").mkdir()
    export = library_root / "exports" / "dataset.jsonl"
    export.write_text("library", encoding="utf-8")
    _configure_library(repo_root, library_root)

    assert resolve_repo_path(repo_root, "raw/witnesses/source.txt") == raw_witness.resolve()
    assert resolve_repo_path(repo_root, "reports/audit.json") == report.resolve()
    assert resolve_repo_path(repo_root, "exports/dataset.jsonl") == export.resolve()
    assert resolve_repo_path(repo_root, "data/canonical.json") == (
        repo_root / "data" / "canonical.json"
    ).resolve()


def test_external_data_route_rejects_noncanonical_paths(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    library_root = tmp_path / "library"
    repo_root.mkdir()
    library_root.mkdir()
    _configure_library(repo_root, library_root)

    with pytest.raises(StorageTopologyError, match="normalized repository-relative"):
        resolve_repo_path(repo_root, "raw//witness.txt")


def test_physical_library_path_round_trips_to_logical_repository_path(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    library_root = tmp_path / "library"
    repo_root.mkdir()
    raw_witness = library_root / "raw" / "witnesses" / "source.txt"
    raw_witness.parent.mkdir(parents=True)
    raw_witness.write_text("library", encoding="utf-8")
    _configure_library(repo_root, library_root)

    assert repository_relative_path(repo_root, raw_witness) == "raw/witnesses/source.txt"
    assert configured_external_path(repo_root, raw_witness) == raw_witness.resolve()

    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    with pytest.raises(StorageTopologyError, match="outside configured storage"):
        repository_relative_path(repo_root, outside)
    assert configured_external_path(repo_root, outside) is None


def test_read_phase_reuses_boundaries_but_resolves_every_member(tmp_path, monkeypatch):
    from collections import Counter
    from ocd_kernel.lib import storage_topology

    repo = tmp_path / "repo"
    library = tmp_path / "library"
    repo.mkdir()
    raw = library / "raw"
    raw.mkdir(parents=True)
    _configure_library(repo, library)
    members = [raw / f"source-{index}.txt" for index in range(128)]
    for member in members:
        member.write_text("source", encoding="utf-8")
    calls = Counter()
    resolve = storage_topology._resolve

    def observed(path, **kwargs):
        calls[Path(path)] += 1
        return resolve(path, **kwargs)

    monkeypatch.setattr(storage_topology, "_resolve", observed)
    with storage_topology.storage_read_phase():
        for member in members:
            assert resolve_repo_path(repo, "raw/" + member.name) == member
    assert calls[raw] == 1
    assert all(calls[member] == 1 for member in members)
    with storage_topology.storage_read_phase():
        assert resolve_repo_path(repo, "raw/" + members[0].name) == members[0]
    assert calls[raw] == 2


def test_manifest_containment_resolves_each_member_once_strictly(tmp_path, monkeypatch):
    from ocd_kernel.lib import storage_topology
    from ocd_kernel.reconstruction import contract

    source = tmp_path / "source.txt"
    source.write_text("retained source", encoding="utf-8")
    calls = []
    resolve = storage_topology._resolve

    def observed(path, **kwargs):
        if Path(path) == source:
            calls.append(kwargs.get("strict", False))
        return resolve(path, **kwargs)

    monkeypatch.setattr(storage_topology, "_resolve", observed)
    monkeypatch.setattr(contract, "resolve_path", observed)
    assert contract._contained(tmp_path, "source.txt", "source") == source
    assert calls == [True]
    source.unlink()
    with pytest.raises(OSError):
        contract._contained(tmp_path, "source.txt", "source")
