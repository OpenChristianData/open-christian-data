"""Hash-proven acquired preimages for the retained Mysteries stage."""
from hashlib import sha256
import json
from pathlib import Path
from ocd_kernel.tei.install_accepted import _files, _io_path
ROOT = Path(__file__).resolve().parents[1]
CASES = [{'path': 'library/works/ambrose-of-milan-on-mysteries/forms/ambrose-of-milan-on-mysteries-ccel-npnf210-retained-en/editions/ambrose-of-milan-on-mysteries-ccel-npnf210-electronic/acquisitions/ambrose-of-milan-on-mysteries-ccel-npnf210-acquired.json', 'fixture': 'tests/fixtures/reconstruction-runtime/authorities/npnf210-mysteries-before/ambrose-of-milan-on-mysteries-ccel-npnf210-acquired.json', 'sha256': '1300bc0aca29d460ee935968fed743ad1c40fb4f8a4bf8170380eb652d79bc9b'}, {'path': 'library/works/ambrose-of-milan-on-mysteries/state.json', 'fixture': 'tests/fixtures/reconstruction-runtime/authorities/npnf210-mysteries-before/state.json', 'sha256': '0ddf37fdd3fd83d65430c6c2b8fb6e73f137745637ed63e9b8182b03e0d4d5da'}, {'path': 'library/works/ambrose-of-milan-on-mysteries/work.json', 'fixture': 'tests/fixtures/reconstruction-runtime/authorities/npnf210-mysteries-before/work.json', 'sha256': 'b7d4156978d73f98b02a4e4fd2ba483848c56f90ef75ed45d2a2c36b34c90695'}]


def mysteries_historical_root(stage, destination):
    raw = _io_path(stage / "stage-receipt.json").read_bytes()
    assert sha256(raw).hexdigest() == "5f0bf7388291d1007e44644356de7aff13156671c59baa72d6311dc87a9bb0f5"
    receipt = json.loads(raw)
    for row in CASES:
        payload = (ROOT / row["fixture"]).read_bytes()
        assert sha256(payload).hexdigest() == row["sha256"] == receipt["preimages"][row["path"]]["sha256"]
        target = _io_path(destination / row["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    for relative, expected in receipt["preimages"].items():
        target = _io_path(destination / relative)
        assert target.is_file() == expected["exists"]
        assert (sha256(target.read_bytes()).hexdigest() if expected["exists"] else None) == expected["sha256"]
    for relative, digest in _files(stage).items():
        if relative == "stage-receipt.json" or relative.startswith("library/works/"):
            continue
        payload = _io_path(stage / relative).read_bytes()
        assert sha256(payload).hexdigest() == digest
        target = _io_path(destination / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return destination
