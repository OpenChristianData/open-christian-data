from __future__ import annotations

import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Callable

import pytest

import ocd_kernel.lib.git_artifact as git_artifact


def _git(
    repo: Path,
    *arguments: str,
    input_bytes: bytes | None = None,
) -> bytes:
    return subprocess.run(
        ["git", *arguments],
        check=True,
        cwd=repo,
        input=input_bytes,
        capture_output=True,
    ).stdout


def _repository(tmp_path: Path) -> tuple[Path, tuple[Path, ...]]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "perf02@example.invalid")
    _git(repo, "config", "user.name", "PERF-02 Test")
    paths = (repo / "first.txt", repo / "nested" / "second.txt")
    paths[1].parent.mkdir()
    paths[0].write_bytes(b"first\n")
    paths[1].write_bytes(b"second\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    return repo, paths


def _outcome(function: Callable[[], object]) -> tuple[object, ...]:
    try:
        return ("return", function())
    except Exception as error:
        return ("raise", type(error), str(error))


def _scalar_batch_outcomes(
    path: Path,
    *,
    repository_root: Path,
    revision: str,
) -> tuple[tuple[object, ...], tuple[object, ...]]:
    scalar = _outcome(
        lambda: git_artifact.committed_artifact(
            path,
            repository_root=repository_root,
            revision=revision,
        )
    )
    batch = _outcome(
        lambda: git_artifact.committed_artifacts(
            (path,),
            repository_root=repository_root,
            revision=revision,
        )[0]
    )
    return scalar, batch


def test_batch_attests_one_revision_with_fewer_git_processes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, paths = _repository(tmp_path)
    original_git = git_artifact._git
    commands: list[tuple[str, ...]] = []

    def recording_git(
        repository_root: Path,
        arguments: list[str],
        *,
        input_bytes: bytes | None = None,
    ) -> bytes:
        commands.append(tuple(arguments))
        return original_git(
            repository_root,
            arguments,
            input_bytes=input_bytes,
        )

    monkeypatch.setattr(git_artifact, "_git", recording_git)
    reference = tuple(
        git_artifact.committed_artifact(
            path,
            repository_root=repo,
            revision="HEAD",
        )
        for path in paths
    )
    reference_commands = tuple(commands)
    commands.clear()

    batch_api = getattr(git_artifact, "committed_artifacts", None)
    assert callable(batch_api), (
        "the governed scalar call graph launched "
        f"{len(reference_commands)} Git processes for two paths"
    )
    actual = batch_api(paths, repository_root=repo, revision="HEAD")

    assert actual == reference
    assert len(reference_commands) == 10
    assert len(commands) == 6
    assert len(commands) < len(reference_commands)


def test_batch_matches_scalar_for_regular_modes_and_crlf_clean_filter(
    tmp_path: Path,
) -> None:
    repo, paths = _repository(tmp_path)
    attributes = repo / ".gitattributes"
    attributes.write_text("*.txt text eol=lf\n", encoding="utf-8", newline="\n")
    _git(repo, "add", ".gitattributes")
    _git(repo, "update-index", "--chmod=+x", "nested/second.txt")
    _git(repo, "commit", "-m", "bind modes and filtering")
    paths[0].write_bytes(b"first\r\n")
    paths[1].write_bytes(b"second\r\n")

    reference = tuple(
        git_artifact.committed_artifact(
            path,
            repository_root=repo,
            revision="HEAD",
        )
        for path in paths
    )
    actual = git_artifact.committed_artifacts(
        paths,
        repository_root=repo,
        revision="HEAD",
    )

    assert actual == reference
    assert tuple(item.canonical_bytes for item in actual) == (b"first\n", b"second\n")
    assert tuple(item.checkout_bytes for item in actual) == (
        b"first\r\n",
        b"second\r\n",
    )
    modes = _git(repo, "ls-tree", "HEAD", "first.txt", "nested/second.txt")
    assert b"100644 blob" in modes
    assert b"100755 blob" in modes


def test_batch_matches_scalar_for_missing_untracked_tree_and_nonregular_modes(
    tmp_path: Path,
) -> None:
    repo, paths = _repository(tmp_path)
    untracked = repo / "untracked.txt"
    untracked.write_bytes(b"untracked\n")
    symlink_path = repo / "alias.txt"
    symlink_oid = _git(
        repo,
        "hash-object",
        "-w",
        "--stdin",
        input_bytes=b"first.txt",
    ).decode().strip()
    symlink_path.write_bytes(b"first.txt")
    _git(
        repo,
        "update-index",
        "--add",
        "--cacheinfo",
        f"120000,{symlink_oid},alias.txt",
    )
    gitlink_path = repo / "modules" / "demo"
    gitlink_path.mkdir(parents=True)
    commit = git_artifact.repository_revision(repo)
    _git(
        repo,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{commit},modules/demo",
    )
    _git(repo, "commit", "-m", "nonregular modes")

    for path in (
        untracked,
        repo / "missing.txt",
        repo / "nested",
        symlink_path,
        gitlink_path,
    ):
        scalar, batch = _scalar_batch_outcomes(
            path,
            repository_root=repo,
            revision="HEAD",
        )
        assert batch == scalar

    paths[0].unlink()
    scalar, batch = _scalar_batch_outcomes(
        paths[0],
        repository_root=repo,
        revision="HEAD",
    )
    assert batch == scalar


def test_batch_matches_scalar_for_lexical_aliases_and_containment_failures(
    tmp_path: Path,
) -> None:
    repo, paths = _repository(tmp_path)
    alias = repo / "nested" / ".." / "first.txt"
    scalar, batch = _scalar_batch_outcomes(
        alias,
        repository_root=repo,
        revision="HEAD",
    )
    assert batch == scalar
    assert batch[0] == "return"

    for path, root in (
        (tmp_path / "outside.txt", repo),
        (repo / ".." / "outside.txt", repo),
        (paths[0], repo / "nested"),
    ):
        scalar, batch = _scalar_batch_outcomes(
            path,
            repository_root=root,
            revision="HEAD",
        )
        assert batch == scalar


def test_batch_binds_one_resolved_revision_and_matches_changed_worktree_failures(
    tmp_path: Path,
) -> None:
    repo, paths = _repository(tmp_path)
    old_revision = git_artifact.repository_revision(repo)
    paths[0].write_bytes(b"new head\n")
    _git(repo, "add", "first.txt")
    _git(repo, "commit", "-m", "new head")
    new_revision = git_artifact.repository_revision(repo)
    paths[0].write_bytes(b"first\n")

    scalar, batch = _scalar_batch_outcomes(
        paths[0],
        repository_root=repo,
        revision=old_revision,
    )
    assert batch == scalar
    assert batch[1].repository_revision == old_revision

    scalar, batch = _scalar_batch_outcomes(
        paths[0],
        repository_root=repo,
        revision=new_revision,
    )
    assert batch == scalar
    assert batch[0] == "raise"

    scalar, batch = _scalar_batch_outcomes(
        paths[0],
        repository_root=repo,
        revision="not-a-revision",
    )
    assert batch == scalar


def test_batch_matches_scalar_for_symlink_ancestry(tmp_path: Path) -> None:
    repo, paths = _repository(tmp_path)
    real = repo / "real.txt"
    real.write_bytes(paths[0].read_bytes())
    paths[0].unlink()
    try:
        paths[0].symlink_to(real)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    scalar, batch = _scalar_batch_outcomes(
        paths[0],
        repository_root=repo,
        revision="HEAD",
    )

    assert batch == scalar


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_batch_matches_scalar_for_junction_ancestry(tmp_path: Path) -> None:
    repo, paths = _repository(tmp_path)
    linked = repo / "nested"
    target = tmp_path / "junction-target"
    target.mkdir()
    (target / "second.txt").write_bytes(paths[1].read_bytes())
    paths[1].unlink()
    linked.rmdir()
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(linked), str(target)],
        check=True,
        capture_output=True,
    )
    try:
        scalar, batch = _scalar_batch_outcomes(
            linked / "second.txt",
            repository_root=repo,
            revision="HEAD",
        )
        assert batch == scalar
    finally:
        os.rmdir(linked)


def test_batch_stays_bound_when_head_changes_after_revision_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, paths = _repository(tmp_path)
    old_revision = git_artifact.repository_revision(repo)
    paths[0].write_bytes(b"future\n")
    _git(repo, "add", "first.txt")
    _git(repo, "commit", "-m", "future")
    future_revision = git_artifact.repository_revision(repo)
    _git(repo, "checkout", "--detach", old_revision)
    original_git = git_artifact._git
    changed = False

    def drifting_head(repository_root, arguments, *, input_bytes=None):
        nonlocal changed
        raw = original_git(repository_root, arguments, input_bytes=input_bytes)
        if arguments[:2] == ["rev-parse", "--verify"] and not changed:
            _git(repo, "update-ref", "HEAD", future_revision)
            changed = True
        return raw

    monkeypatch.setattr(git_artifact, "_git", drifting_head)

    artifact = git_artifact.committed_artifacts(
        (paths[0],),
        repository_root=repo,
        revision="HEAD",
    )[0]

    assert artifact.repository_revision == old_revision
    assert artifact.canonical_bytes == b"first\n"
    assert git_artifact.repository_revision(repo) == future_revision


def test_batch_matches_scalar_for_malformed_revision_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, paths = _repository(tmp_path)
    original_git = git_artifact._git

    def malformed_revision(repository_root, arguments, *, input_bytes=None):
        if arguments[:2] == ["rev-parse", "--verify"]:
            return b"not-a-full-commit\n"
        return original_git(repository_root, arguments, input_bytes=input_bytes)

    monkeypatch.setattr(git_artifact, "_git", malformed_revision)
    scalar, batch = _scalar_batch_outcomes(
        paths[0],
        repository_root=repo,
        revision="HEAD",
    )

    assert batch == scalar


def test_batch_rejects_stable_read_race_like_scalar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, paths = _repository(tmp_path)
    target = paths[0]
    original_stat = Path.stat

    def run_with_race(function: Callable[[], object]) -> tuple[object, ...]:
        calls = 0

        def racing_stat(path: Path, *args, **kwargs):
            nonlocal calls
            status = original_stat(path, *args, **kwargs)
            if path == target:
                calls += 1
                if calls == 2:
                    return SimpleNamespace(
                        st_mode=status.st_mode,
                        st_dev=status.st_dev,
                        st_ino=status.st_ino,
                        st_size=status.st_size,
                        st_mtime_ns=status.st_mtime_ns + 1,
                    )
            return status

        with monkeypatch.context() as patch:
            patch.setattr(Path, "stat", racing_stat)
            return _outcome(function)

    scalar = run_with_race(
        lambda: git_artifact.committed_artifact(
            target,
            repository_root=repo,
            revision="HEAD",
        )
    )
    batch = run_with_race(
        lambda: git_artifact.committed_artifacts(
            (target,),
            repository_root=repo,
            revision="HEAD",
        )[0]
    )

    assert batch == scalar
    assert batch[0] == "raise"


def test_batch_rejects_ambiguous_unrequested_and_malformed_git_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, paths = _repository(tmp_path)
    original_git = git_artifact._git

    def duplicate_tree(repository_root, arguments, *, input_bytes=None):
        raw = original_git(repository_root, arguments, input_bytes=input_bytes)
        if arguments[:1] == ["ls-tree"]:
            return raw + raw
        return raw

    monkeypatch.setattr(git_artifact, "_git", duplicate_tree)
    with pytest.raises(git_artifact.CanonicalGitArtifactError, match="ambiguous"):
        git_artifact.committed_artifacts(
            paths,
            repository_root=repo,
            revision="HEAD",
        )

    with monkeypatch.context() as patch:
        def malformed_blob(repository_root, arguments, *, input_bytes=None):
            raw = original_git(repository_root, arguments, input_bytes=input_bytes)
            if arguments[:2] == ["cat-file", "--batch"]:
                return raw[:-1]
            return raw

        patch.setattr(git_artifact, "_git", malformed_blob)
        with pytest.raises(
            git_artifact.CanonicalGitArtifactError,
            match="invalid canonical blob",
        ):
            git_artifact.committed_artifacts(
                paths,
                repository_root=repo,
                revision="HEAD",
            )

    with monkeypatch.context() as patch:
        def unrequested_tree(repository_root, arguments, *, input_bytes=None):
            raw = original_git(repository_root, arguments, input_bytes=input_bytes)
            if arguments[:1] == ["ls-tree"]:
                extra = original_git(
                    repository_root,
                    [
                        "ls-tree",
                        "-z",
                        "--full-tree",
                        "HEAD",
                        "--",
                        ":(literal)nested/second.txt",
                    ],
                )
                return raw + extra
            return raw

        patch.setattr(git_artifact, "_git", unrequested_tree)
        with pytest.raises(
            git_artifact.CanonicalGitArtifactError,
            match="invalid tree entry",
        ):
            git_artifact.committed_artifacts(
                (paths[0],),
                repository_root=repo,
                revision="HEAD",
            )


def test_batch_propagates_git_command_failure_and_returns_only_requested_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, paths = _repository(tmp_path)
    duplicated = git_artifact.committed_artifacts(
        (paths[1], paths[1]),
        repository_root=repo,
        revision="HEAD",
    )
    assert tuple(item.repository_relative_path for item in duplicated) == (
        "nested/second.txt",
        "nested/second.txt",
    )
    original_run = subprocess.run

    def failed_ls_tree(arguments, *args, **kwargs):
        if arguments[:2] == ["git", "ls-tree"]:
            raise subprocess.CalledProcessError(
                128,
                arguments,
                stderr=b"corrupt tree",
            )
        return original_run(arguments, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", failed_ls_tree)
    with pytest.raises(
        git_artifact.CanonicalGitOperationalError,
        match="corrupt tree",
    ):
        git_artifact.committed_artifacts(
            paths,
            repository_root=repo,
            revision="HEAD",
        )
