"""Honorius native-part source, exact stage pins, rollback, and live projection."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest
from tests.historical_python_report_fixture import frozen_python_report_runtime

pytestmark = pytest.mark.usefixtures("frozen_python_report_runtime")
from lxml import etree

from build.tei.openmgh_bsb830_honorius_oracle import check
from build.tools import install_openmgh_bsb830_honorius as installer
from build.tools import preflight_openmgh_bsb830_honorius as guard
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path
from tests.openmgh_journal_historical_fixture import restore_mgh_journal_before


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "raw/openmgh/bsb00000830/tei/bsb00000830.xml"


def _bytes(path: Path) -> bytes:
    return _io_path(path).read_bytes()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(path: Path) -> str:
    return sha256(_bytes(path)).hexdigest()


def test_exact_two_part_pins_and_source_tree_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    pins = json.loads(_bytes(installer.PINS))
    assert _sha(installer.PINS) == installer.PINS_SHA
    assert {pin["work_id"] for pin in pins["stages"]} == installer.IDS
    for pin in pins["stages"]:
        receipt = Path(pin["receipt"])
        record = json.loads(_bytes(receipt))
        assert installer._pin(receipt.resolve(strict=True), record) == pin["receipt_sha256"]

    candidate = Path("D:/Library/Open Christian Data/candidate-reviews/h830/honorius-de-apostatis/package/content.tei.xml")
    source = _bytes(SOURCE)
    original = _bytes(candidate)
    assert check(source, original, first_id="bsb00000830_00065_12",
                 last_id="bsb00000830_00071_4", part_ordinal=2)["status"] == "pass"
    xml = etree.fromstring(original, etree.XMLParser(resolve_entities=False, no_network=True))
    selected = xml.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")[0][0]
    etree.SubElement(selected, "{http://www.tei-c.org/ns/1.0}note").text = "invented"
    with pytest.raises(ValueError, match="complete source and candidate part trees differ"):
        check(source, etree.tostring(xml), first_id="bsb00000830_00065_12",
              last_id="bsb00000830_00071_4", part_ordinal=2)
    monkeypatch.setattr(installer, "PINS_SHA", "0" * 64)
    receipt = Path(pins["stages"][0]["receipt"])
    with pytest.raises(PipelineError, match="pin index changed"):
        installer._pin(receipt.resolve(strict=True), json.loads(_bytes(receipt)))


def test_fixture_rolls_back_and_projects_live_master(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pins = json.loads(_bytes(installer.PINS))
    pin = pins["stages"][0]
    record = json.loads(_bytes(Path(pin["receipt"])))
    stage = Path(record["stage_root"])
    fixture = tmp_path / "root"
    shutil.copytree(_io_path(stage), _io_path(fixture))
    work = Path("library/works") / record["work_id"]
    target = fixture / work
    assert target.resolve(strict=True).is_relative_to(fixture.resolve(strict=True))
    assert not target.is_symlink()
    shutil.rmtree(_io_path(target))
    restore_mgh_journal_before(fixture, record)
    record["canonical_root"] = fixture.as_posix()
    receipt = tmp_path / "r.json"
    receipt.write_bytes(_json(record))
    pin["receipt"] = receipt.as_posix()
    pin["receipt_sha256"] = _sha(receipt)
    fixture_pins = tmp_path / "pins.json"
    fixture_pins.write_bytes(_json(pins))
    monkeypatch.setattr(installer, "PINS", fixture_pins)
    monkeypatch.setattr(installer, "PINS_SHA", _sha(fixture_pins))
    assert guard.preflight(receipt)["status"] == "ready-for-review"

    before = _files(target)
    manifest = fixture / record["manifest_path"]
    profile = fixture / record["profile_path"]
    before_manifest, before_profile = _bytes(manifest), _bytes(profile)

    def fail_after_manifest(point: str) -> None:
        if point == "after-source-manifest.json-swap":
            raise RuntimeError("injected Honorius sidecar failure")

    with pytest.raises(RuntimeError, match="injected Honorius sidecar failure"):
        installer.install(receipt, expected_receipt_sha256=pin["receipt_sha256"],
                          fail_at=fail_after_manifest, operation_prefix="honorius-fixture")
    assert _files(target) == before
    assert _bytes(manifest) == before_manifest
    assert _bytes(profile) == before_profile
    journals = list((fixture / "library/.sidecar-operations").glob("honorius-fixture-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(_bytes(journals[0]))["phase"] == "rolled-back"

    result = installer.install(receipt, expected_receipt_sha256=pin["receipt_sha256"],
                               operation_prefix="honorius-fixture")
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 1
    assert _files(target) == record["after"]


def test_actual_current_generation_rejects_historical_before(tmp_path: Path) -> None:
    raw = Path(r"D:\Library\Open Christian Data\candidate-reviews\h830\r1.json").read_bytes()
    assert sha256(raw).hexdigest() == "493a8042c2ecfd1799e7410f4e6c340738870c79ce8ccb414d603d4097e6ca1f"
    original = json.loads(raw)
    changed = dict(original, canonical_root=ROOT.as_posix())
    assert dict(changed, canonical_root=original["canonical_root"]) == original
    receipt = tmp_path / "current-generation.json"
    receipt.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(Exception, match="work identity or generation changed"):
        guard.preflight(receipt)
