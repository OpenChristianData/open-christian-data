from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from ocd_kernel.lib.git_artifact import (
    CanonicalGitArtifactError,
    committed_artifact,
    is_committed_path,
    repository_revision,
    staged_artifact,
)


def _git(repo: Path, *arguments: str, input_bytes: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", *arguments],
        check=True,
        cwd=repo,
        input=input_bytes,
        capture_output=True,
    ).stdout


def _repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "ticket01@example.invalid")
    _git(repo, "config", "user.name", "Ticket 01 Test")
    (repo / "ir").mkdir()
    (repo / "ir" / "artifact.txt").write_text(
        "canonical\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    return repo


def test_committed_artifact_rejects_worktree_symlink(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    artifact = repo / "ir" / "artifact.txt"
    target = repo / "real.txt"
    target.write_bytes(artifact.read_bytes())
    artifact.unlink()
    try:
        artifact.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    with pytest.raises(CanonicalGitArtifactError, match="reparse|symlink"):
        committed_artifact(
            artifact,
            repository_root=repo,
            revision="HEAD",
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_committed_artifact_rejects_worktree_junction(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    linked = repo / "ir"
    target = tmp_path / "junction-target"
    target.mkdir()
    (target / "artifact.txt").write_text(
        "canonical\n",
        encoding="utf-8",
        newline="\n",
    )
    (linked / "artifact.txt").unlink()
    linked.rmdir()
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(linked), str(target)],
        check=True,
        capture_output=True,
    )
    try:
        with pytest.raises(CanonicalGitArtifactError, match="reparse|symlink"):
            committed_artifact(
                linked / "artifact.txt",
                repository_root=repo,
                revision="HEAD",
            )
    finally:
        os.rmdir(linked)


@pytest.mark.parametrize(
    ("mode", "path"),
    (("120000", "alias.txt"), ("160000", "modules/demo")),
    ids=("git-symlink", "gitlink"),
)
def test_committed_artifact_rejects_non_regular_git_modes(
    tmp_path: Path,
    mode: str,
    path: str,
) -> None:
    repo = _repository(tmp_path)
    if mode == "120000":
        oid = _git(repo, "hash-object", "-w", "--stdin", input_bytes=b"real.txt").decode().strip()
        (repo / path).write_text("real.txt", encoding="utf-8", newline="\n")
    else:
        oid = repository_revision(repo)
        (repo / path).mkdir(parents=True)
    _git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}")
    _git(repo, "commit", "-m", f"add mode {mode}")

    with pytest.raises(CanonicalGitArtifactError, match=mode):
        committed_artifact(
            repo / path,
            repository_root=repo,
            revision="HEAD",
        )


def test_committed_artifact_rejects_tree_entry(tmp_path: Path) -> None:
    repo = _repository(tmp_path)

    with pytest.raises(CanonicalGitArtifactError, match="040000"):
        committed_artifact(
            repo / "ir",
            repository_root=repo,
            revision="HEAD",
        )


def test_committed_path_distinguishes_absent_from_missing_checkout(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    revision = repository_revision(repo)
    untracked = repo / "untracked.txt"
    untracked.write_text("untracked\n", encoding="utf-8", newline="\n")

    assert is_committed_path(
        untracked,
        repository_root=repo,
        revision=revision,
    ) is False
    with pytest.raises(CanonicalGitArtifactError, match="not present"):
        committed_artifact(
            untracked,
            repository_root=repo,
            revision=revision,
        )

    tracked = repo / "ir" / "artifact.txt"
    tracked.unlink()
    assert is_committed_path(
        tracked,
        repository_root=repo,
        revision=revision,
    ) is True
    with pytest.raises(CanonicalGitArtifactError, match="unavailable"):
        committed_artifact(
            tracked,
            repository_root=repo,
            revision=revision,
        )


def test_committed_path_propagates_tree_query_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repository(tmp_path)
    revision = repository_revision(repo)
    original_run = subprocess.run

    def failed_ls_tree(arguments, *args, **kwargs):
        if arguments[:2] == ["git", "ls-tree"]:
            raise subprocess.CalledProcessError(128, arguments, stderr=b"corrupt tree")
        return original_run(arguments, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", failed_ls_tree)

    with pytest.raises(CanonicalGitArtifactError, match="ls-tree"):
        is_committed_path(
            repo / "ir" / "artifact.txt",
            repository_root=repo,
            revision=revision,
        )


def test_git_authority_preserves_safe_operational_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repository(tmp_path)
    original_run = subprocess.run

    def dubious_repository(arguments, *args, **kwargs):
        if arguments[:2] == ["git", "rev-parse"]:
            raise subprocess.CalledProcessError(
                128,
                arguments,
                stderr=b"fatal: detected dubious ownership in repository\n",
            )
        return original_run(arguments, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", dubious_repository)

    with pytest.raises(
        CanonicalGitArtifactError,
        match="detected dubious ownership",
    ):
        repository_revision(repo)


def test_repository_revision_rejects_nested_directory_as_repository_root(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)

    with pytest.raises(CanonicalGitArtifactError, match="repository root|top-level"):
        repository_revision(repo / "ir")


def test_staged_artifact_returns_canonical_index_bytes_across_crlf_checkout(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    (repo / ".gitattributes").write_text("*.txt text eol=lf\n", encoding="utf-8")
    _git(repo, "add", ".gitattributes")
    _git(repo, "commit", "-m", "bind text normalization")
    artifact_path = repo / "ir" / "artifact.txt"
    artifact_path.write_bytes(b"candidate\r\nsecond\r\n")
    _git(repo, "add", "ir/artifact.txt")

    artifact = staged_artifact(artifact_path, repository_root=repo)

    assert artifact.canonical_bytes == b"candidate\nsecond\n"
    assert artifact.checkout_bytes == b"candidate\r\nsecond\r\n"
    assert artifact.index_blob_oid != artifact.head_blob_oid


def test_staged_artifact_rejects_mode_only_change_with_head_blob(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    artifact_path = repo / "ir" / "artifact.txt"
    head_oid = _git(repo, "rev-parse", "HEAD:ir/artifact.txt").decode().strip()
    _git(repo, "update-index", "--chmod=+x", "ir/artifact.txt")
    index_oid = _git(repo, "rev-parse", ":ir/artifact.txt").decode().strip()

    assert index_oid == head_oid
    with pytest.raises(CanonicalGitArtifactError, match="blob.*HEAD"):
        staged_artifact(artifact_path, repository_root=repo)


def test_staged_artifact_rejects_worktree_only_and_post_stage_mutation(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    artifact_path = repo / "ir" / "artifact.txt"
    artifact_path.write_text("worktree only\n", encoding="utf-8", newline="\n")
    with pytest.raises(CanonicalGitArtifactError, match="not staged"):
        staged_artifact(artifact_path, repository_root=repo)

    _git(repo, "add", "ir/artifact.txt")
    artifact_path.write_text("changed after stage\n", encoding="utf-8", newline="\n")
    with pytest.raises(CanonicalGitArtifactError, match="index identity mismatch"):
        staged_artifact(artifact_path, repository_root=repo)


def test_staged_artifact_rejects_absent_deleted_and_directory_paths(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    untracked = repo / "untracked.txt"
    untracked.write_text("untracked\n", encoding="utf-8", newline="\n")
    with pytest.raises(CanonicalGitArtifactError, match="not present in the index"):
        staged_artifact(untracked, repository_root=repo)

    artifact_path = repo / "ir" / "artifact.txt"
    _git(repo, "rm", "--cached", "ir/artifact.txt")
    with pytest.raises(CanonicalGitArtifactError, match="not present in the index"):
        staged_artifact(artifact_path, repository_root=repo)

    with pytest.raises(CanonicalGitArtifactError, match="directory|tree"):
        staged_artifact(repo / "ir", repository_root=repo)


@pytest.mark.parametrize("mode", ("120000", "160000"), ids=("git-symlink", "gitlink"))
def test_staged_artifact_rejects_non_regular_index_modes(
    tmp_path: Path,
    mode: str,
) -> None:
    repo = _repository(tmp_path)
    path = "staged-mode"
    if mode == "120000":
        oid = _git(repo, "hash-object", "-w", "--stdin", input_bytes=b"real.txt").decode().strip()
        (repo / path).write_text("real.txt", encoding="utf-8", newline="\n")
    else:
        oid = repository_revision(repo)
        (repo / path).mkdir()
    _git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}")

    with pytest.raises(CanonicalGitArtifactError, match=mode):
        staged_artifact(repo / path, repository_root=repo)


def test_staged_artifact_rejects_reparse_checkout_and_bad_repository_root(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    artifact_path = repo / "ir" / "artifact.txt"
    artifact_path.write_text("staged\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "ir/artifact.txt")
    target = repo / "real.txt"
    target.write_bytes(artifact_path.read_bytes())
    artifact_path.unlink()
    try:
        artifact_path.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    with pytest.raises(CanonicalGitArtifactError, match="reparse|symlink"):
        staged_artifact(artifact_path, repository_root=repo)
    with pytest.raises(CanonicalGitArtifactError, match="repository root|top-level"):
        staged_artifact(artifact_path, repository_root=repo / "ir")


def test_staged_artifact_propagates_index_query_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repository(tmp_path)
    original_run = subprocess.run

    def failed_ls_files(arguments, *args, **kwargs):
        if arguments[:2] == ["git", "ls-files"]:
            raise subprocess.CalledProcessError(128, arguments, stderr=b"corrupt index")
        return original_run(arguments, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", failed_ls_files)

    with pytest.raises(CanonicalGitArtifactError, match="corrupt index"):
        staged_artifact(repo / "ir" / "artifact.txt", repository_root=repo)


def test_ticket01_baseline_names_non_receipt_canonical_identities() -> None:
    root = Path(__file__).resolve().parents[1]
    baseline_path = (
        root
        / "plans"
        / "2026-08-10-post-migration-integrity-cleanup"
        / "01-canonical-evidence-byte-baseline.json"
    )
    baseline = json.loads(baseline_path.read_bytes())
    identities = baseline["additional_canonical_identities"]
    expected = {
        "ir/census/athanasius-on-the-incarnation.ccel-npnf204.census.json": (
            "3846ead2f1ccdd8917eaa38153d9f66aed65ad5d8454d1116e267c59252d562b"
        ),
        "sources/structured-text/athanasius-on-the-incarnation/config.json": (
            "34e0e29959b165139959349fb69a0fbab4389a95e481aba98e9c9c3a580cba34"
        ),
    }

    assert {record["path"] for record in identities} == set(expected)
    # The baseline pins a historical revision; later metadata corrections must
    # not make that immutable receipt compare against today's HEAD.
    revision = baseline["accepted_fixed_point"]
    for record in identities:
        canonical_bytes = _git(root, "cat-file", "blob", f"{revision}:{record['path']}")
        # This receipt records a historical checkout, not today's EOL policy.
        # Reproduce the recorded EOL representation from the canonical blob.
        assert isinstance(record["pure_crlf_to_lf"], bool)
        historical_checkout = (
            canonical_bytes.replace(b"\n", b"\r\n")
            if record["pure_crlf_to_lf"]
            else canonical_bytes
        )
        assert b"\r" not in canonical_bytes
        assert record["checkout_byte_count"] == len(historical_checkout)
        assert record["checkout_sha256"] == hashlib.sha256(
            historical_checkout
        ).hexdigest()
        assert record["canonical_git_byte_count"] == len(canonical_bytes)
        assert hashlib.sha256(canonical_bytes).hexdigest() == expected[
            record["path"]
        ]
        assert json.loads(historical_checkout) == json.loads(canonical_bytes)
        assert record["canonical_git_sha256"] == expected[record["path"]]
        assert record["stored_binding_sha256"] == expected[record["path"]]
        assert record["pure_crlf_to_lf"] is (
            historical_checkout != canonical_bytes
        )
        assert record["json_semantics_equal"] is True
        assert record["artifact_written"] is False
