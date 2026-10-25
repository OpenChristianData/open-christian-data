"""Safety contract for selective hardlink candidate-package clones."""

from __future__ import annotations

import os
from pathlib import Path
import shutil

import pytest

from build.lib import pytest_candidate_clone as clone_module
from build.lib.pytest_candidate_clone import (
    candidate_package_fingerprint,
    clone_candidate_package,
)


def _package(root: Path) -> Path:
    package = root / "package"
    package.mkdir(parents=True)
    (package / "content.tei.xml").write_bytes(b"<TEI>large immutable text</TEI>\n")
    (package / "manifest.json").write_bytes(b'{"members":[]}\n')
    (package / "source-accountability.json").write_bytes(b"{}\n")
    return package


def test_clone_copies_every_member_by_default(tmp_path: Path) -> None:
    source = _package(tmp_path / "source")
    target = clone_candidate_package(source, tmp_path / "target")

    for member in source.iterdir():
        assert not os.path.samefile(member, target / member.name)

    (target / "content.tei.xml").write_bytes(b"mutated\n")
    assert (source / "content.tei.xml").read_bytes() == b"<TEI>large immutable text</TEI>\n"


def test_clone_hardlinks_only_explicit_immutable_members(tmp_path: Path) -> None:
    source = _package(tmp_path / "source")
    before = candidate_package_fingerprint(source)

    target = clone_candidate_package(
        source,
        tmp_path / "target",
        hardlink_members=("content.tei.xml",),
    )

    assert os.path.samefile(source / "content.tei.xml", target / "content.tei.xml")
    assert not os.path.samefile(source / "manifest.json", target / "manifest.json")
    (target / "manifest.json").write_bytes(b'{"mutated":true}\n')
    assert candidate_package_fingerprint(source) == before


def test_clone_falls_back_to_private_copy_when_link_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _package(tmp_path / "source")

    def unavailable_link(_source: object, _target: object) -> None:
        raise OSError("hardlinks unavailable")

    monkeypatch.setattr(os, "link", unavailable_link)
    target = clone_candidate_package(
        source,
        tmp_path / "target",
        hardlink_members=("content.tei.xml",),
    )

    assert not os.path.samefile(source / "content.tei.xml", target / "content.tei.xml")
    assert (target / "content.tei.xml").read_bytes() == (
        source / "content.tei.xml"
    ).read_bytes()


@pytest.mark.parametrize(
    "member",
    [
        "../outside.txt",
        "missing.json",
        "nested",
    ],
)
def test_clone_rejects_unsafe_or_non_file_hardlink_members(
    tmp_path: Path, member: str
) -> None:
    source = _package(tmp_path / "source")
    (source / "nested").mkdir()
    target = tmp_path / "target"

    with pytest.raises((ValueError, FileNotFoundError)):
        clone_candidate_package(source, target, hardlink_members=(member,))

    assert not target.exists()


def test_clone_rejects_python_shadow_trees(tmp_path: Path) -> None:
    source = _package(tmp_path / "source")
    (source / "oracle.py").write_text("VALUE = 1\n", encoding="utf-8")
    target = tmp_path / "target"

    with pytest.raises(ValueError, match=r"Python|\.py"):
        clone_candidate_package(source, target)

    assert not target.exists()


def test_clone_rejects_reparse_escape_when_supported(tmp_path: Path) -> None:
    source = _package(tmp_path / "source")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside\n")
    link = source / "linked-outside.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Windows symlink creation is unavailable")

    target = tmp_path / "target"
    with pytest.raises(ValueError, match="symlink|reparse|escapes"):
        clone_candidate_package(source, target)

    assert not target.exists()


def test_clone_rejects_lexical_source_root_reparse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _package(tmp_path / "source")
    source_absolute = Path(os.path.abspath(source))
    real_isjunction = getattr(os.path, "isjunction", lambda _path: False)

    def source_root_is_junction(path: object) -> bool:
        return Path(os.path.abspath(path)) == source_absolute or real_isjunction(path)

    monkeypatch.setattr(os.path, "isjunction", source_root_is_junction, raising=False)

    target = tmp_path / "target"
    with pytest.raises(ValueError, match="source.*reparse"):
        clone_module.clone_candidate_package(source, target)

    assert not target.exists()


def test_clone_removes_partial_target_when_copy_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _package(tmp_path / "source")
    target = tmp_path / "target"
    original_copy2 = shutil.copy2
    calls = 0

    def fail_second_copy(source_path: object, target_path: object, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic copy failure")
        return original_copy2(source_path, target_path, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", fail_second_copy)
    with pytest.raises(OSError, match="synthetic copy failure"):
        clone_candidate_package(source, target)

    assert not target.exists()


def test_candidate_fingerprint_detects_member_drift(tmp_path: Path) -> None:
    source = _package(tmp_path / "source")
    before = candidate_package_fingerprint(source)

    (source / "manifest.json").write_bytes(b'{"drifted":true}\n')

    assert candidate_package_fingerprint(source) != before
