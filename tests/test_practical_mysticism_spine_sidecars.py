"""Focused checks for Practical Mysticism's staged text/support boundary."""
from __future__ import annotations

from pathlib import Path
from hashlib import sha256
import json
import sys
import pytest

from build.tools.install_practical_mysticism_spine_sidecars import RECEIPT_REL, preflight
from build.tools.prepare_practical_mysticism_spine_sidecars import PACKET_REL
from ocd_kernel.library._common import load_json, sha256_file
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[1]
STAGE = Path("C:/Scratch/Open Christian Data/practical-mysticism-spine-stage-20260926-v2")


def test_exact_opf_spine_text_and_complete_support() -> None:
    packet = load_json(ROOT / PACKET_REL)
    text = packet["ordered_text_members"]
    support = packet["support_members"]
    assert len(text) == 18
    assert len(support) == 15
    assert all(item["path"].endswith(".xhtml") for item in text)
    assert packet["opf"]["path"] in {item["path"] for item in support}
    assert not {item["path"] for item in text} & {item["path"] for item in support}
    assert any(item["path"].endswith(".jpg") for item in support)
    assert any(item["path"].endswith(".css") for item in support)


def test_staged_or_installed_sidecars_are_exact() -> None:
    receipt = load_json(ROOT / RECEIPT_REL)
    installed = all(_io_path(ROOT / item["path"]).is_file()
                    and sha256_file(_io_path(ROOT / item["path"])) == item["proposed_sha256"]
                    for item in receipt["files"])
    if installed:
        acquisition = next(item["path"] for item in receipt["files"] if "/acquisitions/" in item["path"])
        validate_acquisition(ROOT / acquisition, root=ROOT)
    else:
        assert len(preflight(ROOT, STAGE)["files"]) == 6


SOURCE_ROOT = ROOT
BEFORE_FIXTURES = {'state': 'tests/fixtures/reconstruction-runtime/authorities/practical-mysticism-original-before.state.json', 'work': 'tests/fixtures/reconstruction-runtime/authorities/practical-mysticism-original-before.work.json'}


@pytest.fixture(autouse=True)
def historical_spine_sidecar_context(tmp_path, monkeypatch):
    """Use the genuine identity-only preimage required by the frozen six-file stage."""
    packet_raw = (SOURCE_ROOT / PACKET_REL).read_bytes()
    assert sha256(packet_raw).hexdigest() == "75a148898672eebf7aa5a3c5a1121470642a19e217b24ecc30ebb9e4a2137424"
    packet = json.loads(packet_raw)
    receipt_raw = (SOURCE_ROOT / RECEIPT_REL).read_bytes()
    assert sha256(receipt_raw).hexdigest() == "d49a2a635009e0dd8371d146e6a90891b843281b1ebe38199b3ac9369ae5fde4"
    # The original Windows checkpoint pinned this complete record with CRLF.
    assert sha256(receipt_raw.replace(b"\n", b"\r\n")).hexdigest() == "4f3028234b7888e042cf984bc194b34c66c7cdc15c9274616c586539ca5896bb"
    receipt = json.loads(receipt_raw)
    stage_receipt = (STAGE / "receipt.json").read_bytes()
    assert json.loads(stage_receipt) == receipt
    assert receipt["packet_sha256"] == sha256(packet_raw).hexdigest()
    root = tmp_path / "historical-root"
    root.mkdir()
    catalog_relative = "metadata/source-evidence/catalog/practical-mysticism.json"
    catalog_before = (SOURCE_ROOT / catalog_relative).read_bytes()
    authority_paths = set(packet["authorities"]) | {PACKET_REL, RECEIPT_REL}
    for relative in authority_paths:
        source = SOURCE_ROOT / relative
        if relative == catalog_relative:
            source = SOURCE_ROOT / "tests/fixtures/reconstruction-runtime/authorities/practical-mysticism-original-catalog.json"
        raw = source.read_bytes()
        if relative in packet["authorities"]:
            assert sha256(raw).hexdigest() == packet["authorities"][relative]
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    for row in packet["ordered_text_members"] + packet["support_members"]:
        raw = (SOURCE_ROOT / row["path"]).read_bytes()
        assert len(raw) == row["bytes"] and sha256(raw).hexdigest() == row["sha256"]
        target = root / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    originals = {}
    for name, fixture in BEFORE_FIXTURES.items():
        raw = (SOURCE_ROOT / fixture).read_bytes()
        assert sha256(raw).hexdigest() == packet["before"][name]
        relative = "library/works/practical-mysticism/" + name + ".json"
        originals[relative] = (SOURCE_ROOT / relative).read_bytes()
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    assert len(receipt["files"]) == 6
    for row in receipt["files"]:
        assert sha256((STAGE / row["path"]).read_bytes()).hexdigest() == row["proposed_sha256"]
        current = root / row["path"]
        assert (sha256(current.read_bytes()).hexdigest() if current.is_file() else None) == row["before_sha256"]
    monkeypatch.setattr(sys.modules[__name__], "ROOT", root)
    yield
    for relative, raw in originals.items():
        assert (SOURCE_ROOT / relative).read_bytes() == raw
    assert (SOURCE_ROOT / PACKET_REL).read_bytes() == packet_raw
    assert (SOURCE_ROOT / RECEIPT_REL).read_bytes() == receipt_raw
    assert (STAGE / "receipt.json").read_bytes() == stage_receipt
    assert (SOURCE_ROOT / catalog_relative).read_bytes() == catalog_before
