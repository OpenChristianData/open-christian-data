"""Whitefield's two retained electronic witnesses remain separate acquisitions."""
from __future__ import annotations

from pathlib import Path
from hashlib import sha256
import json
import pytest
from ocd_kernel.library._common import PipelineError

from build.tools.install_whitefield_two_witness_sidecars import RECEIPT_REL, preflight
from build.tools.prepare_whitefield_two_witness_sidecars import PACKET_REL
from ocd_kernel.library._common import load_json, sha256_file
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[1]
STAGE = Path("C:/Scratch/Open Christian Data/whitefield-two-witness-stage-20260926")


def test_two_distinct_retained_witnesses_and_pg_selection() -> None:
    packet = load_json(ROOT / PACKET_REL)
    assert packet["witnesses"]["ccel"]["source"]["path"].endswith("whitefield_sermons.xml")
    assert packet["witnesses"]["gutenberg"]["source"]["path"].endswith("pg77041.txt")
    assert packet["witnesses"]["gutenberg"]["selected_labels"] == ["LVIII", "LIX"]
    assert len(packet["witnesses"]["ccel"]["div1_ids"]) == 62
    acquisitions = [load_json(path) for path in STAGE.rglob("*-acquired.json")]
    assert len(acquisitions) == 2
    assert len({item["edition_id"] for item in acquisitions}) == 2
    assert len({item["source_sha256"] for item in acquisitions}) == 2
    assert all(len(item["retained_files"]) == 1 for item in acquisitions)


def test_staged_or_installed_witnesses_are_exact(tmp_path: Path) -> None:
    receipt = load_json(ROOT / RECEIPT_REL)
    installed = all(_io_path(ROOT / item["path"]).is_file()
                    and sha256_file(_io_path(ROOT / item["path"])) == item["proposed_sha256"]
                    for item in receipt["files"])
    if installed:
        for item in receipt["files"]:
            if "/acquisitions/" in item["path"]:
                validate_acquisition(ROOT / item["path"], root=ROOT)
    else:
        historical = _historical_packet_root(tmp_path / "historical")
        assert len(preflight(historical, STAGE)["files"]) == 5


def _historical_packet_root(destination: Path) -> Path:
    packet = load_json(ROOT / PACKET_REL)
    receipt = load_json(ROOT / RECEIPT_REL)
    assert sha256((ROOT / PACKET_REL).read_bytes()).hexdigest() == receipt["packet_sha256"]
    retained = Path(__file__).parent / "fixtures/whitefield-packet-before"
    for name, expected in packet["before"].items():
        raw = (retained / (name + ".json")).read_bytes()
        assert sha256(raw).hexdigest() == expected
        target = destination / "library/works/george-whitefield-sermons" / (name + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    historical_manifest = "sources/sermons/george-whitefield-sermons/george-whitefield-sermons.source-manifest.json"
    historical_authorities = {historical_manifest: retained / "source-manifest.json",
                              "metadata/source-evidence/catalog/george-whitefield-sermons.json": retained / "source-evidence.json"}
    for relative in {PACKET_REL, RECEIPT_REL, *packet["authorities"],
                     *(packet["witnesses"][label]["source"]["path"] for label in ("ccel", "gutenberg"))}:
        raw = historical_authorities.get(relative, _io_path(ROOT / relative)).read_bytes()
        if relative in packet["authorities"]:
            assert sha256(raw).hexdigest() == packet["authorities"][relative]
        target = _io_path(destination / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return destination


def test_current_metadata_cannot_masquerade_as_the_original_packet() -> None:
    with pytest.raises(PipelineError, match="packet, source evidence, or receipt differs"):
        preflight(ROOT, STAGE)
