"""Test the frozen direct-script Woolman helpers in their declared import context."""

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def modules(monkeypatch):
    manifest = json.loads((ROOT / "sources/manifest-acquisitions/gutenberg-pg37311-woolman-v5/source-manifest.json").read_bytes())
    authorities = {row["path"]: row["sha256"] for row in manifest["authorities"]}
    loaded = {}
    for suffix in ("oracle", "reconstruction", "runner", "challenge"):
        name = f"woolman_37311_{suffix}"
        relative = f"build/tei/{name}.py"
        path = ROOT / relative
        assert sha256(path.read_bytes()).hexdigest() == authorities[relative]
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        loaded[suffix] = module
    return loaded


def test_runner_preserves_nonempty_candidate_destination(modules, tmp_path):
    retained = tmp_path / "keep.txt"
    retained.write_bytes(b"existing candidate\n")
    with pytest.raises(ValueError, match="candidate destination must be absent or empty"):
        modules["runner"].build(tmp_path)
    assert list(tmp_path.iterdir()) == [retained]
    assert retained.read_bytes() == b"existing candidate\n"


def test_challenge_reseal_updates_selected_member_binding(modules, tmp_path):
    selected = tmp_path / "content.tei.xml"
    selected.write_bytes(b"original")
    retained = tmp_path / "README.source.md"
    retained.write_bytes(b"retained source notice\n")
    record = {"members": [
        {"name": path.name, "bytes": len(path.read_bytes()), "sha256": sha256(path.read_bytes()).hexdigest()}
        for path in (selected, retained)
    ]}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(record), encoding="utf-8")
    replacement = b"challenged content"
    modules["challenge"]._reseal(tmp_path, selected.name, replacement)
    result = json.loads(manifest.read_bytes())
    assert selected.read_bytes() == replacement
    assert result["members"][0] == {"name": selected.name, "bytes": len(replacement), "sha256": sha256(replacement).hexdigest()}
    assert result["members"][1] == record["members"][1]
    assert retained.read_bytes() == b"retained source notice\n"
