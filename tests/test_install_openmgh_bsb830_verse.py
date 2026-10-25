"""Exact-pin, native flat-verse, rollback, and live projection fixture checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest
from tests.historical_python_report_fixture import frozen_python_report_runtime  # noqa: F401

pytestmark = pytest.mark.usefixtures("frozen_python_report_runtime")
from lxml import etree

from build.tools import install_openmgh_bsb830_verse as installer
from build.tools import preflight_openmgh_bsb830_verse as verse_preflight
from ocd_kernel.library._common import PipelineError
from tests.openmgh_sidecar_historical_fixture import historical_mgh_sidecar_root
from ocd_kernel.tei.install_accepted import _files, _io_path


ROOT = Path(__file__).resolve().parents[1]


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def test_exact_pin_and_flat_verse_source_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = json.loads(installer.PINS.read_bytes())
    receipt = Path(pin["receipt"])
    record = json.loads(receipt.read_bytes())
    assert _sha(installer.PINS) == installer.PINS_SHA
    assert installer._pin(receipt.resolve(strict=True), record) == pin["receipt_sha256"]
    historical = tmp_path / "historical"
    historical.mkdir()
    _root, historical_receipt, _record = historical_mgh_sidecar_root(
        ROOT, historical, receipt, pin["receipt_sha256"],
    )
    assert verse_preflight.preflight(historical_receipt)["status"] == "ready-for-review"

    source = Path(record["source_path"])
    test_source = tmp_path / source
    _io_path(test_source.parent).mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(ROOT / source), _io_path(test_source))
    tree = etree.parse(str(_io_path(test_source)), etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    selected = tree.xpath("/t:TEI/t:text/t:body/t:div/t:div", namespaces=ns)[27]
    etree.SubElement(selected[0], "{http://www.tei-c.org/ns/1.0}l").text = "invented line"
    tree.write(str(_io_path(test_source)), encoding="UTF-8", xml_declaration=True)
    record["canonical_root"] = tmp_path.as_posix()
    with pytest.raises(PipelineError, match="line grouping changed"):
        verse_preflight._check_flat_verse(record)
    monkeypatch.setattr(installer, "PINS_SHA", "0" * 64)
    with pytest.raises(PipelineError, match="pin index changed"):
        installer._pin(receipt.resolve(strict=True), json.loads(receipt.read_bytes()))


def test_verse_fixture_rolls_back_then_projects_live_master(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = json.loads(installer.PINS.read_bytes())
    source_receipt = Path(pin["receipt"])
    record = json.loads(source_receipt.read_bytes())
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    fixture, _context_receipt, _context = historical_mgh_sidecar_root(
        ROOT, fixture, source_receipt, _sha(source_receipt),
    )
    work = Path("library/works") / record["work_id"]
    target = fixture / work
    record["canonical_root"] = fixture.as_posix()
    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(_json(record))
    pin["receipt"] = receipt.as_posix()
    pin["receipt_sha256"] = _sha(receipt)
    fixture_pin = tmp_path / "pin.json"
    fixture_pin.write_bytes(_json(pin))
    monkeypatch.setattr(installer, "PINS", fixture_pin)
    monkeypatch.setattr(installer, "PINS_SHA", _sha(fixture_pin))
    assert verse_preflight.preflight(receipt)["status"] == "ready-for-review"

    before = _files(target)
    manifest, profile = fixture / record["manifest_path"], fixture / record["profile_path"]
    before_manifest = _io_path(manifest).read_bytes()
    before_profile = _io_path(profile).read_bytes()

    def interrupt(point: str) -> None:
        if point == "after-source-manifest.json-swap":
            raise RuntimeError("injected verse sidecar failure")

    with pytest.raises(RuntimeError, match="injected verse sidecar failure"):
        installer.install(receipt, expected_receipt_sha256=pin["receipt_sha256"], fail_at=interrupt,
                          operation_prefix="b830-verse-fixture")
    assert _files(target) == before
    assert _io_path(manifest).read_bytes() == before_manifest
    assert _io_path(profile).read_bytes() == before_profile
    journals = list((fixture / "library/.sidecar-operations").glob("b830-verse-fixture-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_bytes())["phase"] == "rolled-back"

    result = installer.install(receipt, expected_receipt_sha256=pin["receipt_sha256"],
                               operation_prefix="b830-verse-fixture")
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 1
    assert _files(target) == record["after"]
