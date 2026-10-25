"""Public identity checks recognize paths as they appear in source and JSON."""

import json
from pathlib import Path
import subprocess

import pytest

from build.tools import check_public_identity as identity


@pytest.mark.parametrize("separator", ["\\", "\\\\", "\\\\\\\\", "/"])
def test_git_scan_finds_private_path_spellings(tmp_path: Path, monkeypatch, separator):
    marker = r"C:\Users\PrivateReader"
    value = separator.join(("C:", "Users", "PrivateReader", "project"))
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "notes.txt").write_text(value, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "notes.txt"], check=True)
    tree = subprocess.run(["git", "-C", str(tmp_path), "write-tree"], check=True,
                          capture_output=True, text=True).stdout.strip()
    monkeypatch.setattr(identity, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(identity, "LITERALS", [marker])
    monkeypatch.setattr(identity, "WORDS", [])
    assert any("notes.txt" in hit for hit in identity.grep_hits(tree))
    assert identity.filename_hits([value])
    assert not identity.filename_hits([value.replace("PrivateReader", "PublicReader")])


def test_json_spelling_uses_the_same_identity_pattern():
    import re

    marker = r"C:\Users\PrivateReader"
    assert re.search(identity.literal_pattern(marker), json.dumps({"root": marker}))
