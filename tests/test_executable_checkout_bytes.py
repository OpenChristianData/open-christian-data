"""Keep executable byte identities stable while preserving historical exceptions."""
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize("logical,ending,content", (
    ("build/example.py", b"\n", b"VALUE = 1\n"),
    ("library/works/example/acceptance.json", b"\n", b"VALUE = 1\n"),
    ("library/works/example/README.source.md", b"\n", b"VALUE = 1\n"),
    ("sources/example/profile.json", b"\n", b"VALUE = 1\n"),
    ("build/lib/tei_link_check.py", b"\n", b"VALUE = 1\n"),
    ("build/tei/durham_import_closure.py", b"\n", b"VALUE = 1\n"),
    ("ocd_kernel/lib/example.py", b"\n", b"VALUE = 1\n"),
    ("cvw_app/example.py", b"\n", b"VALUE = 1\n"),
    ("ocd_kernel/tei/writer.py", b"\r\n", b"VALUE = 1\n"),
    ("build/tei/__init__.py", b"\r\n", b"VALUE = 1\n"),
    ("build/scripts/export_huggingface.py", b"\r\n", b"VALUE = 1\r\n"),
))
def test_executed_python_checkout_preserves_its_declared_byte_contract(tmp_path, logical, ending, content):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    attributes = Path(__file__).resolve().parents[1] / ".gitattributes"
    (tmp_path / ".gitattributes").write_bytes(attributes.read_bytes())
    sha = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=tmp_path,
                         input=content, capture_output=True, check=True).stdout.strip().decode()
    checkout = subprocess.run(["git", "-c", "core.autocrlf=true", "cat-file", "--filters",
                               f"--path={logical}", sha], cwd=tmp_path,
                              capture_output=True, check=True).stdout
    assert checkout == b"VALUE = 1" + ending
