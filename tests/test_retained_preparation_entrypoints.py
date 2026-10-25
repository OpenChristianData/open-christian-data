"""Standalone retained-source preparers preserve their narrow write boundaries."""

from hashlib import sha256
from pathlib import Path
import subprocess
import sys
import pytest

from tests.test_cli_input_guards import _invoke


ROOT = Path(__file__).resolve().parents[1]


def _copy_script(tmp_path, name):
    script = tmp_path / "build/tools" / name
    script.parent.mkdir(parents=True)
    script.write_bytes((ROOT / "build/tools" / name).read_bytes())
    (tmp_path / "build/tei").mkdir()
    return script


def test_watson_binding_refresh_updates_only_emitter_pin(tmp_path):
    imported = _invoke("build.tools.watson_fix_initial_binding", "__ocd_import_contract__")
    assert imported.returncode == 0, imported.stderr
    script = _copy_script(tmp_path, "watson_fix_initial_binding.py")
    emitter = tmp_path / "build/tei/watson_retained_native_emitter.py"
    emitter.write_bytes(b"retained emitter fixture\n")
    producer = tmp_path / "build/tei/watson_retained_native_prepare.py"
    producer.write_text("BEFORE = 1\nEMITTER_SHA = 'old'\nAFTER = 2\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(script)], check=True, capture_output=True, text=True)
    pin = sha256(emitter.read_bytes()).hexdigest()
    assert result.stdout.strip() == pin
    assert producer.read_text(encoding="utf-8") == f"BEFORE = 1\nEMITTER_SHA = '{pin}'\nAFTER = 2\n"
    assert emitter.read_bytes() == b"retained emitter fixture\n"


def test_farrar_initializer_preserves_existing_destination(tmp_path):
    imported = _invoke("build.tools.farrar_initialize_retained", "__ocd_import_contract__")
    assert imported.returncode == 0, imported.stderr
    script = _copy_script(tmp_path, "farrar_initialize_retained.py")
    template = tmp_path / "build/tei/ccel_retained_native_emitter.py"
    template.write_bytes((ROOT / "build/tei/ccel_retained_native_emitter.py").read_bytes())
    destination = tmp_path / "build/tei/farrar_retained_native_emitter.py"
    destination.write_bytes(b"preserve existing destination\n")
    result = subprocess.run([sys.executable, str(script)], check=False, capture_output=True, text=True)
    assert result.returncode != 0
    assert "AssertionError" in result.stderr
    assert destination.read_bytes() == b"preserve existing destination\n"
    assert set(path.name for path in destination.parent.iterdir()) == {template.name, destination.name}


@pytest.mark.parametrize("name", ["watson_prepare_authoring.py", "watson_renew_aborted_proof.py"])
def test_watson_authoring_preserves_unmatched_or_existing_authority(tmp_path, name):
    imported = _invoke(f"build.tools.{name.removesuffix('.py')}", "__ocd_import_contract__")
    assert imported.returncode == 0, imported.stderr
    script = _copy_script(tmp_path, name)
    oracle = tmp_path / "build/tei/watson_retained_native_oracle.py"
    oracle.write_bytes(b"unrecognized oracle preimage\n")
    archive = tmp_path / "reports/_logs/watson-existing-install-20261003-v1/aborted-v1-source-contract"
    archive.mkdir(parents=True)
    record = archive / "keep.json"
    record.write_bytes(b"retained archive\n")
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    result = subprocess.run([sys.executable, str(script)], check=False, capture_output=True, text=True)
    assert result.returncode != 0
    assert ("AssertionError" if name == "watson_prepare_authoring.py" else "Preserve prior aborted Watson proof archive") in result.stderr
    assert {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before
