from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from build.tools import check_writer_manifest_gate as gate


REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(repo_root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture
def isolated_gate_repo(tmp_path: Path) -> Path:
    """Provide a disposable staged index matching the executing gate authorizer."""
    repo = tmp_path / "isolated-writer-gate-repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "core.autocrlf", "false")

    schema_rel = Path(gate.WRITER_MANIFEST_SCHEMA_RELATIVE_PATH)
    schema_path = repo / schema_rel
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_bytes(
        (REPO_ROOT / "schemas" / "v1" / "writer_manifest.schema.json").read_bytes()
    )

    allowlist_rel = Path(gate.WRITER_IDENTITIES_RELATIVE_PATH)
    allowlist_path = repo / allowlist_rel
    allowlist_path.parent.mkdir(parents=True, exist_ok=True)
    allowlist_path.write_bytes(gate.EXECUTING_WRITER_IDENTITIES_PATH.read_bytes())
    _git(repo, "add", schema_rel.as_posix(), allowlist_rel.as_posix())
    return repo


def _manifest(writer_identity: str, run_id: str) -> dict:
    data_path = "data/reference/schaff-herzog-encyclopedia.json"
    return {
        "schema_version": "1.0.0",
        "writer": "parser",
        "writer_version": "build/parsers/ia_schaff_herzog.py@v1.0.0",
        "writer_identity": writer_identity,
        "run_id": run_id,
        "started_at": "2026-05-12T10:00:00+00:00",
        "data_paths": [data_path],
        "checksums": {
            data_path: {
                "before_sha256": "a" * 64,
                "after_sha256": "b" * 64,
            }
        },
        "expected_delta_counts": {
            data_path: {
                "entries_changed": 1,
                "fields_changed": 1,
            }
        },
        "allowed_field_paths": ["/data/*/layers/*/display"],
        "partial_completion_policy": "all_or_nothing",
        "renames": [],
    }


def test_allow_case_with_registered_identity(isolated_gate_repo: Path):
    from build.lib import writer_identities
    from build.tools.check_writer_manifest_gate import evaluate_gate

    assert writer_identities.is_authorised("ia_schaff_herzog_parser")

    manifest_body = _manifest("ia_schaff_herzog_parser", "test-allow-case-001")
    staged = [
        "data/reference/schaff-herzog-encyclopedia.json",
        "review/writer-manifests/test-allow-case-001.json",
    ]

    def fake_loader(path):
        if path == "review/writer-manifests/test-allow-case-001.json":
            return manifest_body
        return None

    exit_code, messages = evaluate_gate(
        staged,
        load_manifest=fake_loader,
        repo_root=isolated_gate_repo,
    )
    assert exit_code == 0, f"Gate should pass but blocked with: {messages}"


def test_allow_case_all_registered_identities_pass(isolated_gate_repo: Path):
    from build.lib import writer_identities
    from build.tools.check_writer_manifest_gate import evaluate_gate

    for identity in writer_identities.registered_identities():
        manifest_body = _manifest(identity, f"test-{identity}-001")
        staged = [
            "data/reference/schaff-herzog-encyclopedia.json",
            f"review/writer-manifests/test-{identity}-001.json",
        ]
        exit_code, messages = evaluate_gate(
            staged,
            load_manifest=lambda p, mb=manifest_body: mb if p.startswith("review/writer-manifests/") else None,
            repo_root=isolated_gate_repo,
        )
        assert exit_code == 0, f"Identity {identity!r} should pass gate but blocked: {messages}"
