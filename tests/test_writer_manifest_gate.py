"""Tests for the staged writer-manifest and paired-data pre-commit gate."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools import check_writer_manifest_gate as gate  # noqa: E402


def _manifest(writer_identity: str = "ia_schaff_herzog_parser", data_paths=None) -> dict:
    return {
        "schema_version": "1.0.0",
        "writer": "parser",
        "writer_version": "build/parsers/ia_schaff_herzog.py@v1.0.0",
        "writer_identity": writer_identity,
        "run_id": "test-run",
        "started_at": "2026-05-12T10:00:00+00:00",
        "data_paths": list(data_paths or ["data/reference/schaff-herzog-encyclopedia.json"]),
        "checksums": {
            (data_paths[0] if data_paths else "data/reference/schaff-herzog-encyclopedia.json"): {
                "before_sha256": "a" * 64,
                "after_sha256": "b" * 64,
            }
        },
        "expected_delta_counts": {
            (data_paths[0] if data_paths else "data/reference/schaff-herzog-encyclopedia.json"): {
                "entries_changed": 1,
                "fields_changed": 1,
            }
        },
        "allowed_field_paths": ["/data/*/layers/*/display"],
        "partial_completion_policy": "all_or_nothing",
        "renames": [],
    }


def _git(repo_root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )


def test_no_data_edits_passes_through():
    rc, messages = gate.evaluate_gate(
        ["docs/README.md", "schemas/v1/foo.schema.json"],
        load_manifest=lambda p: None,
    )
    assert rc == 0
    assert messages == []


def test_missing_staged_allowlist_blocks_before_non_writer_pass_through(monkeypatch):
    monkeypatch.setattr(gate, "_staged_blob_bytes", lambda path, repo_root: None)

    rc, messages = gate.evaluate_gate(["docs/README.md"])

    assert rc == 1
    assert "writer-identity allowlist could not be loaded from the staged index" in "\n".join(
        messages
    )


def test_unstaged_historical_manifests_are_not_scanned():
    loaded = []

    def fail_if_loaded(path):
        loaded.append(path)
        raise AssertionError(f"unstaged path was scanned: {path}")

    rc, messages = gate.evaluate_gate(["docs/README.md"], load_manifest=fail_if_loaded)

    assert rc == 0
    assert messages == []
    assert loaded == []


def test_valid_staged_manifest_passes_without_a_staged_data_edit():
    manifest_path = "review/writer-manifests/test-run.json"
    rc, messages = gate.evaluate_gate(
        [manifest_path],
        load_manifest=lambda path: _manifest(),
    )

    assert rc == 0
    assert messages == []


def test_schema_invalid_staged_manifest_blocks_with_actionable_message():
    manifest_path = "review/writer-manifests/test-run.json"
    invalid = _manifest()
    del invalid["renames"]

    rc, messages = gate.evaluate_gate(
        [manifest_path],
        load_manifest=lambda path: invalid,
    )

    assert rc == 1
    joined = "\n".join(messages)
    assert "fails validation against schemas/v1/writer_manifest.schema.json" in joined
    assert "renames" in joined


def test_schema_invalid_non_object_manifest_blocks_with_actionable_message():
    rc, messages = gate.evaluate_gate(
        ["review/writer-manifests/test-run.json"],
        load_manifest=lambda path: [],
    )

    assert rc == 1
    joined = "\n".join(messages)
    assert "fails validation against schemas/v1/writer_manifest.schema.json" in joined
    assert "<root>" in joined


def test_json_null_staged_manifest_is_schema_invalid(monkeypatch):
    schema_text = (REPO_ROOT / "schemas" / "v1" / "writer_manifest.schema.json").read_text(
        encoding="utf-8"
    )

    def null_blob(path, *, repo_root):
        if path == gate.WRITER_MANIFEST_SCHEMA_RELATIVE_PATH:
            return schema_text
        return "null"

    monkeypatch.setattr(gate, "_staged_blob", null_blob)

    rc, messages = gate.evaluate_gate(["review/writer-manifests/test-run.json"])

    assert rc == 1
    assert "fails validation against schemas/v1/writer_manifest.schema.json" in "\n".join(messages)


def test_malformed_staged_manifest_blocks_with_actionable_message(monkeypatch):
    schema_text = (REPO_ROOT / "schemas" / "v1" / "writer_manifest.schema.json").read_text(
        encoding="utf-8"
    )

    def malformed_blob(path, *, repo_root):
        if path == gate.WRITER_MANIFEST_SCHEMA_RELATIVE_PATH:
            return schema_text
        return '{"schema_version":'

    monkeypatch.setattr(gate, "_staged_blob", malformed_blob)

    rc, messages = gate.evaluate_gate(["review/writer-manifests/test-run.json"])

    assert rc == 1
    joined = "\n".join(messages)
    assert "contains malformed JSON" in joined
    assert "line" in joined


def test_real_git_index_uses_staged_schema_and_alternate_repo_root(tmp_path, capsys):
    from build.lib import writer_identities

    identity = "ia_schaff_herzog_parser"
    assert writer_identities.is_authorised(identity)
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Writer Manifest Gate Test")
    _git(tmp_path, "config", "user.email", "writer-manifest-gate@example.invalid")

    schema_rel = Path(gate.WRITER_MANIFEST_SCHEMA_RELATIVE_PATH)
    schema_path = tmp_path / schema_rel
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema = json.loads(
        (REPO_ROOT / "schemas" / "v1" / "writer_manifest.schema.json").read_text(encoding="utf-8")
    )
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    allowlist_rel = Path(gate.WRITER_IDENTITIES_RELATIVE_PATH)
    allowlist_path = tmp_path / allowlist_rel
    allowlist_path.parent.mkdir(parents=True, exist_ok=True)
    executing_allowlist = Path(writer_identities.__file__).read_text(encoding="utf-8")
    allowlist_path.write_text(executing_allowlist, encoding="utf-8")

    historical_rel = Path("review/writer-manifests/historical-invalid.json")
    historical_path = tmp_path / historical_rel
    historical_path.parent.mkdir(parents=True, exist_ok=True)
    historical_path.write_text(json.dumps({"writer_identity": identity}), encoding="utf-8")
    _git(
        tmp_path,
        "add",
        schema_rel.as_posix(),
        allowlist_rel.as_posix(),
        historical_rel.as_posix(),
    )
    _git(tmp_path, "commit", "-m", "seed historical state")

    data_rel = Path("data/reference/paired.json")
    data_path = tmp_path / data_rel
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text("{}", encoding="utf-8")
    manifest_rel = Path("review/writer-manifests/real-index-run.json")
    manifest_path = tmp_path / manifest_rel
    manifest = _manifest(writer_identity=identity, data_paths=[data_rel.as_posix()])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _git(tmp_path, "add", data_rel.as_posix(), manifest_rel.as_posix())

    staged = gate._staged_paths(repo_root=tmp_path)
    assert historical_rel.as_posix() not in staged
    assert data_rel.as_posix() in staged
    assert manifest_rel.as_posix() in staged
    assert gate.main(["--repo-root", str(tmp_path)]) == 0
    capsys.readouterr()

    # Relax only the working-tree schema. The staged schema remains strict.
    relaxed_schema = dict(schema)
    relaxed_schema["required"] = [field for field in schema["required"] if field != "renames"]
    schema_path.write_text(json.dumps(relaxed_schema), encoding="utf-8")
    invalid_manifest = dict(manifest)
    del invalid_manifest["renames"]
    manifest_path.write_text(json.dumps(invalid_manifest), encoding="utf-8")
    _git(tmp_path, "add", manifest_rel.as_posix())

    assert gate.main(["--repo-root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "fails validation against schemas/v1/writer_manifest.schema.json" in captured.err
    assert "renames" in captured.err

    unregistered_manifest = _manifest(
        writer_identity="actually_unregistered_writer",
        data_paths=[data_rel.as_posix()],
    )
    manifest_path.write_text(json.dumps(unregistered_manifest), encoding="utf-8")
    _git(tmp_path, "add", manifest_rel.as_posix())

    assert gate.main(["--repo-root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "unregistered writer_identity" in captured.err
    assert "actually_unregistered_writer" in captured.err

    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    allowlist_path.write_text(executing_allowlist + "\n# staged mismatch\n", encoding="utf-8")
    _git(tmp_path, "add", manifest_rel.as_posix(), allowlist_rel.as_posix())

    assert gate.main(["--repo-root", str(tmp_path)]) == 1
    assert "staged writer-identity allowlist differs" in capsys.readouterr().err

    allowlist_path.write_bytes(b"\xff\xfe")
    _git(tmp_path, "add", allowlist_rel.as_posix())

    assert gate.main(["--repo-root", str(tmp_path)]) == 1
    assert "staged writer-identity allowlist is not readable UTF-8" in capsys.readouterr().err

    _git(tmp_path, "rm", "--cached", "--force", allowlist_rel.as_posix())

    assert gate.main(["--repo-root", str(tmp_path)]) == 1
    assert (
        "writer-identity allowlist could not be loaded from the staged index"
        in capsys.readouterr().err
    )


def test_git_staged_path_discovery_failure_blocks(tmp_path, capsys):
    bad_repo = tmp_path / "not-a-repository"
    bad_repo.mkdir()

    assert gate.main(["--repo-root", str(bad_repo)]) == 1
    assert "BLOCKED: git staged-path discovery failed" in capsys.readouterr().err


def test_non_json_data_paths_pass_through():
    # Markdown docs under data/ are human-written documentation, not parser output.
    # They must commit without a writer manifest.
    rc, messages = gate.evaluate_gate(
        ["data/sermons/MANIFEST.md", "data/README.md"],
        load_manifest=lambda p: None,
    )
    assert rc == 0
    assert messages == []


def test_data_edit_with_no_manifest_blocks():
    rc, messages = gate.evaluate_gate(
        ["data/reference/schaff-herzog-encyclopedia.json"],
        load_manifest=lambda p: None,
    )
    assert rc == 1
    joined = "\n".join(messages)
    assert "no review/writer-manifests" in joined
    assert "schaff-herzog-encyclopedia" in joined


def test_data_edit_with_manifest_carrying_unregistered_identity_blocks():
    # Exercise the real production allowlist with an identity that is genuinely absent.
    rc, messages = gate.evaluate_gate(
        [
            "data/reference/schaff-herzog-encyclopedia.json",
            "review/writer-manifests/test-run.json",
        ],
        load_manifest=lambda p: _manifest(writer_identity="actually_unregistered_writer"),
    )
    assert rc == 1
    joined = "\n".join(messages)
    assert "writer_identity" in joined
    assert "writer_identities.py" in joined


def test_data_edit_uncovered_by_manifest_blocks():
    # Manifest exists and writer_identity is somehow registered, but the data
    # path isn't declared in the manifest's data_paths.
    rc, messages = gate.evaluate_gate(
        [
            "data/reference/schaff-herzog-encyclopedia.json",
            "review/writer-manifests/test-run.json",
        ],
        load_manifest=lambda p: _manifest(data_paths=["data/some/other.json"]),
    )
    assert rc == 1
    joined = "\n".join(messages)
    assert "not declared in any staged manifest" in joined


def test_unreadable_manifest_blocks_with_clear_message():
    rc, messages = gate.evaluate_gate(
        [
            "data/reference/schaff-herzog-encyclopedia.json",
            "review/writer-manifests/test-run.json",
        ],
        load_manifest=lambda p: None,
    )
    assert rc == 1
    joined = "\n".join(messages)
    assert "could not be loaded" in joined


def test_allow_case_now_active_at_a2():
    from build.lib import writer_identities

    assert "ia_schaff_herzog_parser" in writer_identities.registered_identities()
