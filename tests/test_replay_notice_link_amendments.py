"""A real notice writer captures reviewed preimages and rejects unexplained edits."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess

import pytest

from build.tools import replay_notice_link_amendments as writer

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repository(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    for name in writer.EDITS:
        original = ROOT / writer.PACKET / "preimages" / name
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(original.read_bytes())
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "add", "--", *writer.EDITS], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-m", "Synthetic original notices"], cwd=root, check=True, capture_output=True)
    monkeypatch.setattr(writer, "CHECKPOINT", writer._git(root, "rev-parse", "HEAD").decode().strip())
    for name in writer.REVIEW_PINS:
        path = root / writer.PACKET / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / writer.PACKET / name).read_bytes())
    for name in writer.EDITS:
        post = (ROOT / writer.PACKET / "review-inputs" / name).read_bytes()
        (root / name).write_bytes(post)
        path = root / writer.PACKET / "review-inputs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(post)
    return root


def test_replay_emits_actual_registered_writer_hashes_and_preserves_installed_notices(repository, tmp_path):
    before = {name: (repository / name).read_bytes() for name in writer.EDITS}
    replay = tmp_path / "replay"
    result = writer.replay(repository, replay)
    assert result["canonical_notice_bytes_unchanged"] and not replay.exists()
    manifest = json.loads((repository / result["manifest"]).read_bytes())
    assert manifest["writer_identity"] == "notice_link_amendment" and manifest["writer"] == "tool"
    assert manifest["data_paths"] == sorted(writer.EDITS) and manifest["allowed_field_paths"] == [""]
    for name, body in before.items():
        original = writer._git(repository, "show", f"{writer.CHECKPOINT}:{name}")
        assert manifest["checksums"][name] == {"before_sha256": sha256(original).hexdigest(),
                                               "after_sha256": sha256(body).hexdigest()}
        assert manifest["expected_delta_counts"][name] == {"entries_changed": 1, "fields_changed": 1}
        assert (repository / name).read_bytes() == body


@pytest.mark.parametrize("damage", ["review", "current", "before", "failed-write"])
def test_changed_authority_or_failed_write_never_emits_success(repository, tmp_path, monkeypatch, damage):
    name = next(iter(writer.EDITS))
    if damage == "review":
        path = repository / writer.PACKET / "NOTICE_INSTALL.json"
        path.write_bytes(path.read_bytes() + b"\n")
    elif damage == "current":
        (repository / name).write_bytes(b"unreviewed notice")
    elif damage == "before":
        original_git = writer._git
        monkeypatch.setattr(writer, "_git", lambda root, *args: b"wrong preimage" if args[0] == "show" else original_git(root, *args))
    else:
        original_write = Path.write_bytes

        def interrupted(path, content):
            if path.is_relative_to(tmp_path / "replay") and content == (repository / name).read_bytes():
                raise OSError("injected notice output failure")
            return original_write(path, content)

        monkeypatch.setattr(Path, "write_bytes", interrupted)
    with pytest.raises((ValueError, OSError)):
        writer.replay(repository, tmp_path / "replay")
    assert not list((repository / "review/writer-manifests").glob("*.json"))
    assert not (tmp_path / "replay").exists()
