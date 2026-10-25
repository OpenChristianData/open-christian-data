"""Focused offline tests for the guarded v2 Hub publication boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from build.tools import upload_hf_release_v2 as uploader


BASE = "a" * 40
NEXT = "b" * 40
PUBLIC = {"README.md": b"# fixture\n", "data/prose/train.jsonl": b'{"text":"hi"}\n'}


def _files(values: dict[str, bytes]) -> list[dict]:
    return [
        {"path": path, "size_bytes": len(content),
         "sha256": hashlib.sha256(content).hexdigest()}
        for path, content in sorted(values.items())
    ]


class FakeHub:
    def __init__(self, tmp_path: Path, baseline: dict[str, bytes] | None = None):
        self.tmp_path = tmp_path
        self.head = BASE
        self.trees = {BASE: dict(baseline or {})}
        self.calls: list[tuple] = []
        self.corrupt_after_commit = False
        self.move_after_commit = False

    def repo_info(self, *, repo_id: str, repo_type: str, revision: str) -> SimpleNamespace:
        assert (repo_id, repo_type, revision) == (uploader.REPO_ID, "dataset", "main")
        self.calls.append(("head", self.head))
        return SimpleNamespace(sha=self.head)

    def list_repo_tree(self, repo_id: str, *, recursive: bool,
                       revision: str, repo_type: str):
        assert (repo_id, recursive, repo_type) == (uploader.REPO_ID, True, "dataset")
        self.calls.append(("tree", revision))
        return [SimpleNamespace(path=path, size=len(content))
                for path, content in self.trees[revision].items()]

    def hf_hub_download(self, repo_id: str, filename: str, *, repo_type: str,
                        revision: str) -> str:
        assert (repo_id, repo_type) == (uploader.REPO_ID, "dataset")
        self.calls.append(("download", revision, filename))
        path = self.tmp_path / f"download-{revision}-{filename.replace('/', '-') }"
        path.write_bytes(self.trees[revision][filename])
        return str(path)

    def create_commit(self, *, repo_id: str, repo_type: str, revision: str,
                      parent_commit: str, operations: list, commit_message: str):
        assert (repo_id, repo_type, revision) == (uploader.REPO_ID, "dataset", "main")
        assert parent_commit == self.head == BASE
        self.calls.append(("commit", parent_commit, operations))
        current = dict(self.trees[BASE])
        for operation in operations:
            if hasattr(operation, "path_or_fileobj"):
                value = operation.path_or_fileobj
                current[operation.path_in_repo] = value.read_bytes() if isinstance(value, Path) else value
            else:
                del current[operation.path_in_repo]
        if self.corrupt_after_commit:
            current["README.md"] += b"changed"
        self.trees[NEXT] = current
        self.head = "c" * 40 if self.move_after_commit else NEXT
        return SimpleNamespace(oid=NEXT)


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    release = tmp_path / "release"
    public = release / "public"
    (public / "data" / "prose").mkdir(parents=True)
    for path, content in PUBLIC.items():
        (public / path).write_bytes(content)
    monkeypatch.setattr(uploader, "preview_release", lambda *a, **k: {
        "status": "pass", "errors": [], "files": _files(PUBLIC),
        "upload_performed": False,
    })
    return tmp_path, release


def _run(setup, api: FakeHub, **overrides):
    root, release = setup
    kwargs = {
        "api": api, "expected_revision": BASE, "confirm_repo": uploader.REPO_ID,
        "receipt_path": root / "receipt.json", "operation_add": SimpleNamespace,
    }
    kwargs.update(overrides)
    return uploader.upload_release(root, release, {}, **kwargs)


def test_guarded_upload_verifies_exact_files_and_metadata(setup):
    root, _ = setup
    api = FakeHub(root, {".gitattributes": b"*.arrow filter=lfs\n"})
    receipt = _run(setup, api)
    assert receipt["status"] == "pass"
    assert receipt["baseline_revision"] == BASE
    assert receipt["verified_revision"] == NEXT
    assert receipt["verified_files"] == _files(PUBLIC)
    assert set(api.trees[NEXT]) == set(PUBLIC) | {".gitattributes"}
    assert len([call for call in api.calls if call[0] == "commit"]) == 1
    assert json.loads((root / "receipt.json").read_text(encoding="utf-8")) == receipt


@pytest.mark.parametrize("overrides, message", [
    ({"expected_revision": "short"}, "full 40-character"),
    ({"expected_revision": "d" * 40}, "remote revision changed"),
    ({"confirm_repo": "other/repo"}, "confirm_repo"),
])
def test_confirmation_and_revision_fail_before_commit(setup, overrides, message):
    root, _ = setup
    api = FakeHub(root)
    with pytest.raises(uploader.UploadError, match=message):
        _run(setup, api, **overrides)
    assert not any(call[0] == "commit" for call in api.calls)
    assert not (root / "receipt.json").exists()


def test_remote_extra_file_fails_closed(setup):
    root, _ = setup
    api = FakeHub(root, {"legacy.jsonl": b"old"})
    with pytest.raises(uploader.UploadError, match="outside the exact v2 release"):
        _run(setup, api)
    assert not any(call[0] == "commit" for call in api.calls)


def test_local_change_after_preview_fails_closed(setup, monkeypatch):
    root, release = setup
    (release / "public" / "README.md").write_bytes(b"changed")
    api = FakeHub(root)
    with pytest.raises(uploader.UploadError, match="changed after validation"):
        _run(setup, api)
    assert api.calls == []


def test_failed_post_upload_digest_retains_failure_receipt(setup):
    root, _ = setup
    api = FakeHub(root)
    api.corrupt_after_commit = True
    with pytest.raises(uploader.UploadError, match="size or digest differs"):
        _run(setup, api)
    receipt = json.loads((root / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "post-upload-verification-failed"
    assert receipt["commit_revision"] == NEXT


def test_remote_head_move_after_commit_fails_without_retry(setup):
    root, _ = setup
    api = FakeHub(root)
    api.move_after_commit = True
    with pytest.raises(uploader.UploadError, match="differs from created commit"):
        _run(setup, api)
    assert len([call for call in api.calls if call[0] == "commit"]) == 1
    assert json.loads((root / "receipt.json").read_text())["status"] == "post-upload-verification-failed"


def test_default_cli_preview_never_constructs_hub_client(setup, monkeypatch, capsys):
    root, release = setup
    monkeypatch.setattr(uploader, "load_release_selection", lambda path: {})
    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "HfApi", lambda: pytest.fail("network client constructed"))
    result = uploader.main([
        "--root", str(root), "--release", str(release),
        "--selection", str(root / "selection.json"),
    ])
    assert result == 0
    assert json.loads(capsys.readouterr().out)["upload_performed"] is False


def test_uncertain_commit_failure_never_claims_no_upload(setup, monkeypatch):
    root, _ = setup
    api = FakeHub(root)
    def uncertain_commit(**kwargs):
        raise ConnectionError("transport closed after submission")
    monkeypatch.setattr(api, "create_commit", uncertain_commit)
    with pytest.raises(ConnectionError, match="transport closed"):
        _run(setup, api)
    receipt = json.loads((root / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "commit-outcome-unknown"
    assert receipt["upload_performed"] is None


def test_unverifiable_commit_response_never_claims_no_upload(setup, monkeypatch):
    root, _ = setup
    api = FakeHub(root)
    original = api.create_commit

    def malformed_success(**kwargs):
        original(**kwargs)
        return SimpleNamespace(oid="not-a-commit-sha")

    monkeypatch.setattr(api, "create_commit", malformed_success)
    with pytest.raises(uploader.UploadError, match="created commit revision"):
        _run(setup, api)
    receipt = json.loads((root / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "commit-outcome-unknown"
    assert receipt["upload_performed"] is None


def test_cli_reports_post_commit_failure_truthfully(setup, monkeypatch, capsys):
    root, release = setup
    api = FakeHub(root)
    api.corrupt_after_commit = True
    monkeypatch.setattr(uploader, "load_release_selection", lambda path: {})
    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "HfApi", lambda: api)
    monkeypatch.setattr(huggingface_hub, "CommitOperationAdd", SimpleNamespace)
    result = uploader.main([
        "--root", str(root), "--release", str(release),
        "--selection", str(root / "selection.json"), "--live",
        "--expected-revision", BASE, "--confirm-repo", uploader.REPO_ID,
        "--receipt", str(root / "receipt.json"),
    ])
    assert result == 1
    report = json.loads(capsys.readouterr().out)
    assert report["upload_performed"] is True
    assert report["receipt_status"] == "post-upload-verification-failed"


def test_post_commit_extra_file_rejects_exact_remote_set(setup, monkeypatch):
    root, _ = setup
    api = FakeHub(root)
    original = api.create_commit
    def add_unexpected_file(**kwargs):
        commit = original(**kwargs)
        api.trees[NEXT]["unexpected.txt"] = b"extra"
        return commit
    monkeypatch.setattr(api, "create_commit", add_unexpected_file)
    with pytest.raises(uploader.UploadError, match="remote file set differs"):
        _run(setup, api)
    assert json.loads((root / "receipt.json").read_text())["status"] == "post-upload-verification-failed"


def test_duplicate_preview_path_rejected_before_remote_access(setup, monkeypatch):
    root, _ = setup
    files = _files(PUBLIC)
    monkeypatch.setattr(uploader, "preview_release", lambda *a, **k: {
        "status": "pass", "errors": [], "files": files + [files[0]],
    })
    api = FakeHub(root)
    with pytest.raises(uploader.UploadError, match="duplicate paths"):
        _run(setup, api)
    assert api.calls == []


def test_replace_exact_legacy_tree_in_one_conditional_commit(setup):
    root, _ = setup
    api = FakeHub(root, {path: b"old" for path in uploader._LEGACY_FILES})
    receipt = _run(setup, api, replace_legacy=True, operation_delete=SimpleNamespace)
    assert receipt["status"] == "pass"
    assert receipt["removed_legacy_files"] == sorted(uploader._LEGACY_FILES)
    assert api.trees[NEXT] == PUBLIC
    assert len([c for c in api.calls if c[0] == "commit"]) == 1
    assert api.trees[BASE] == {path: b"old" for path in uploader._LEGACY_FILES}


def test_legacy_replacement_rejects_an_unexpected_file(setup):
    root, _ = setup
    baseline = {path: b"old" for path in uploader._LEGACY_FILES}
    baseline["unexpected.json"] = b"private"
    api = FakeHub(root, baseline)
    with pytest.raises(uploader.UploadError, match="outside the exact v2 release"):
        _run(setup, api, replace_legacy=True, operation_delete=SimpleNamespace)
    assert not any(c[0] == "commit" for c in api.calls)


def _manifest(root, release):
    evidence = root / "review.json"
    evidence.write_text('{"status":"pass"}\n', encoding="utf-8")
    tree = {name: uploader.sha256_file(release/name) for name in sorted(uploader.public_files(release))}
    value = {"contract": "ocd-verified-hf-upload-manifest-v1", "status": "pass",
             "selection_sha256": uploader._digest(uploader.canonical_bytes({})),
             "release_tree_sha256": uploader._digest(uploader.canonical_bytes(tree)),
             "verification_evidence": [{"path": "review.json", "sha256": uploader.sha256_file(evidence)}],
             "files": _files(PUBLIC)}
    path = root / "manifest.json"
    path.write_bytes(uploader.canonical_bytes(value))
    return path, uploader.sha256_file(path)


def test_pinned_manifest_reuses_proof_with_exact_package(setup, monkeypatch):
    root, release = setup
    path, digest = _manifest(root, release)
    monkeypatch.setattr(uploader, "preview_release", lambda *a, **k: pytest.fail("full verification repeated"))
    receipt = _run(setup, FakeHub(root), verified_manifest=path, manifest_sha256=digest)
    assert receipt["local_verification"]["verified_manifest_sha256"] == digest


@pytest.mark.parametrize("mutation", ["manifest", "evidence", "selection", "private-file", "public-file", "extra-file"])
def test_pinned_manifest_rejects_drift_before_remote_access(setup, mutation):
    root, release = setup
    (release/"internal").mkdir()
    (release/"internal/proof.json").write_bytes(b"original")
    path, digest = _manifest(root, release)
    selection = {}
    if mutation == "manifest":
        path.write_bytes(path.read_bytes() + b" ")
    elif mutation == "evidence":
        (root/"review.json").write_bytes(b"changed")
    elif mutation == "selection":
        selection = {"changed": True}
    elif mutation == "private-file":
        (release/"internal/proof.json").write_bytes(b"changed")
    elif mutation == "public-file":
        (release/"public/README.md").write_bytes(b"changed")
    else:
        (release/"extra.json").write_bytes(b"extra")
    api = FakeHub(root)
    with pytest.raises(uploader.UploadError):
        uploader.upload_release(root, release, selection, api=api, expected_revision=BASE,
            confirm_repo=uploader.REPO_ID, receipt_path=root/"receipt.json", operation_add=SimpleNamespace,
            verified_manifest=path, manifest_sha256=digest)
    assert api.calls == []


@pytest.mark.parametrize("mutation", [None, "metadata", "notices", "private", "digest"])
def test_editorial_card_preserves_generated_metadata_and_notices(setup, monkeypatch, mutation):
    root, release = setup
    original = b"---\npretty_name: Open Christian Data\nconfigs: exact\n---\n\n# Original\n\n## Source notices\n\nRequired credit.\n"
    (release/"public/README.md").write_bytes(original)
    values = dict(PUBLIC, **{"README.md": original})
    monkeypatch.setattr(uploader, "preview_release", lambda *a, **k: {
        "status": "pass", "errors": [], "files": _files(values)})
    text = original.decode().replace("Open Christian Data\n", "Open Christian Data v1.0.0\n").replace("# Original", "# Release")
    if mutation == "metadata":
        text = text.replace("configs: exact", "configs: changed")
    elif mutation == "notices":
        text = text.replace("Required credit.", "Credit removed.")
    elif mutation == "private":
        text = text.replace("# Release", "# Release\nC:/Users/private")
    card = root/"card.md"
    card.write_text(text, encoding="utf-8", newline="\n")
    digest = uploader.sha256_file(card) if mutation != "digest" else "0" * 64
    api = FakeHub(root)
    if mutation:
        with pytest.raises(uploader.UploadError, match="release card"):
            _run(setup, api, card=card, card_sha256=digest)
        assert api.calls == []
    else:
        receipt = _run(setup, api, card=card, card_sha256=digest)
        assert receipt["status"] == "pass"
        assert api.trees[NEXT]["README.md"] == card.read_bytes()
