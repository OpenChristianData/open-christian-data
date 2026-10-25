"""Exact immutable acquired metadata for the six original Ambrose v3 stages."""
from hashlib import sha256
import json
from pathlib import Path
from ocd_kernel.tei.install_accepted import _files, _io_path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests/fixtures/reconstruction-runtime/next-binding-npnf210-before.json"


def historical_ambrose_root(destination: Path, pins: dict) -> Path:
    cases = [row for row in json.loads(CASES.read_bytes()) if row["work_id"] in pins]
    assert {row["work_id"] for row in cases} == set(pins)
    for case in cases:
        work_id = case["work_id"]
        stage = Path(case["stage"])
        raw = _io_path(stage / "stage-receipt.json").read_bytes()
        assert sha256(raw).hexdigest() == pins[work_id]["receipt"] == case["receipt_sha256"]
        receipt = json.loads(raw)
        assert receipt["status"] == "staged-only" and receipt["canonical_install"] is False
        for row in case["preimages"]:
            payload = (ROOT / row["fixture"]).read_bytes()
            assert sha256(payload).hexdigest() == row["sha256"] == receipt["preimages"][row["path"]]["sha256"]
            assert len(payload) == row["bytes"]
            target = _io_path(destination / row["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        for relative, preimage in receipt["preimages"].items():
            target = _io_path(destination / relative)
            assert target.is_file() == preimage["exists"]
            assert (sha256(target.read_bytes()).hexdigest() if preimage["exists"] else None) == preimage["sha256"]
        work = Path("library/works") / work_id
        for path in _io_path(stage).rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(_io_path(stage))
            if relative.as_posix() == "stage-receipt.json" or relative.parts[:3] == work.parts:
                continue
            target = _io_path(destination / relative)
            if target.exists():
                assert target.read_bytes() == path.read_bytes()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
        assert _files(destination / work) == {row["path"].removeprefix(work.as_posix() + "/"): row["sha256"] for row in case["preimages"] if row["path"].startswith(work.as_posix() + "/")}
    return destination
