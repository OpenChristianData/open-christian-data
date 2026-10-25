"""Exact acquired generations from immutable NPNF204/NPNF211 stage receipts."""
from hashlib import sha256
import json
from pathlib import Path
from ocd_kernel.tei.install_accepted import _files, _io_path

PINS = {
    "npnf211-electronic-acceptance-stage-20260926-e": "6c0f5221dcd6957cab15c5c8ccc765f20f745a9366e8b40fbfa34a5d2ab8ed56",
    "athanasius-npnf204-acceptance-stage-20260926-v1": "00c7aa4adfcc7a31e9a4e8e739d32e138781f5b6697424595e266eea895e6eed",
}


def historical_npnf_root(stage: Path, destination: Path) -> Path:
    raw = _io_path(stage / "stage-receipt.json").read_bytes()
    assert sha256(raw).hexdigest() == PINS[stage.name]
    receipt = json.loads(raw)
    assert receipt["status"] == "staged-only" and receipt["canonical_install"] is False
    for row in receipt["works"]:
        relative_work = Path("library/works") / row["work_id"]
        assert _files(stage / relative_work) == row["after"]
        for relative, expected in row["before"].items():
            payload = _io_path(stage / relative_work / relative).read_bytes()
            assert sha256(payload).hexdigest() == row["after"][relative]
            if sha256(payload).hexdigest() != expected:
                value = json.loads(payload)
                if relative == "work.json":
                    assert value["textual_forms"][0]["editions"][0].pop("category") == "prose"
                    if stage.name.startswith("athanasius-"):
                        creators = value.pop("creators")
                        assert creators[0]["role"] == "author"
                elif relative == "state.json":
                    edition = next(x for x in value["targets"] if x["target_type"] == "edition")
                    acquisition = next(x for x in value["targets"] if x["target_type"] == "acquisition")
                    assert edition["stage"] == "accepted"
                    edition["stage"] = "acquired"
                    edition.pop("reason")
                    edition["updated_at"] = acquisition["updated_at"]
                    assert edition["evidence"][-2].endswith("/master.tei.xml")
                    assert edition["evidence"][-1].endswith("/acceptance.json")
                    edition["evidence"] = edition["evidence"][:-2]
                else:
                    raise AssertionError("Undocumented historical transition")
                payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
            assert sha256(payload).hexdigest() == expected
            target = _io_path(destination / relative_work / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        assert _files(destination / relative_work) == row["before"]
    for path in _io_path(stage).rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(_io_path(stage))
        if relative.parts[:2] == ("library", "works") or relative.as_posix() == "stage-receipt.json":
            continue
        target = _io_path(destination / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    return destination
