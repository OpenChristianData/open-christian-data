"""Exact small acquired generations for retained, single-use install tests."""
from hashlib import sha256
import json
from pathlib import Path

from ocd_kernel.tei.install_accepted import _files, _io_path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "tests/fixtures/reconstruction-runtime/authorities/frozen-install-preimage-index.json"


def copy_recorded_preimage(stage: Path, work: Path, receipt_sha256: str, destination: Path) -> None:
    entries = json.loads(INDEX.read_bytes())
    entry = entries[work.name]
    receipt_raw = (stage / "stage-receipt.json").read_bytes()
    assert sha256(receipt_raw).hexdigest() == entry["receipt_sha256"] == receipt_sha256
    receipt = json.loads(receipt_raw)
    if "before" in receipt:
        assert receipt["before"] == entry["before"]
    target = destination / work
    assert not _io_path(target).exists()
    assert set(entry["fixtures"]) == set(entry["before"])
    for relative, expected in entry["before"].items():
        logical = Path(relative)
        assert not logical.is_absolute() and ".." not in logical.parts
        raw = (ROOT / entry["fixtures"][relative]).read_bytes()
        assert sha256(raw).hexdigest() == expected, relative
        output = _io_path(target / logical)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(raw)
    assert _files(target) == entry["before"]


def copy_stage_dependencies(stage: Path, work: Path, destination: Path) -> None:
    prefix = work.as_posix() + "/"
    for relative, expected in _files(stage).items():
        if relative == "stage-receipt.json" or relative.startswith(prefix):
            continue
        logical = Path(relative)
        assert not logical.is_absolute() and ".." not in logical.parts
        raw = _io_path(stage / logical).read_bytes()
        assert sha256(raw).hexdigest() == expected
        output = _io_path(destination / logical)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(raw)
