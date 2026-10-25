"""Pin the complete Origo Francorum source division and its stage-only route."""

from __future__ import annotations

from hashlib import sha256
import json
import shutil
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
import pytest

from build.tei.openmgh_exact_work_div import check_candidate
from build.tools import install_openmgh_exact_work_div_batch as installer
from build.tools.install_openmgh_exact_work_div_batch import preflight
from tests.openmgh_historical_fixture import historical_exact_work_root
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "plans/2026-09-22-source-preflight/openmgh-exact-batch-bsb754-origo-20260927.json"
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-exact-bsb754-origo-freeze-20260927.json"
FREEZE_SHA = "c0f6fef6817f0d5abd8c62a5b5ef01b143d8d35aed1b9b1b532c43a8b1d4dfba"
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb754-origo-direct-v1/origo-francorum/candidate.tei.xml")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb754-origo-stages-20260927/origo-francorum")
NS = {"t": "http://www.tei-c.org/ns/1.0"}


def _bindings(historical_root: Path) -> tuple[dict, dict, dict, dict, bytes, bytes]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entry = manifest["works"][0]
    work = json.loads(_io_path(historical_root / entry["work_path"]).read_text(encoding="utf-8"))
    acquired = json.loads(_io_path(historical_root / entry["acquisition_path"]).read_text(encoding="utf-8"))
    return manifest, entry, work, acquired, (ROOT / manifest["source"]["path"]).read_bytes(), DIRECT.read_bytes()


def test_extracted_xml_is_the_only_text_witness_and_complete_division_passes(historical_context: tuple[Path, Path, str]) -> None:
    manifest, entry, work, acquired, source, candidate = _bindings(historical_context[0])
    assert sha256(source).hexdigest() == "3349fbef5e7e957e964433d097e94a4a35d84addcbd6a314a88819e6a53039ff"
    package = ROOT / manifest["package"]["path"]
    assert sha256(package.read_bytes()).hexdigest() == manifest["package"]["sha256"]
    with ZipFile(package) as archive:
        assert archive.namelist() == ["bsb00000754.xml"]
        assert archive.read("bsb00000754.xml") == source
    result = check_candidate(source, candidate, manifest, entry, work, acquired)
    assert (result["status"], result["source_node_count"], result["source_line_breaks"],
            result["source_page_breaks"]) == ("pass", 32, 25, 1)
    assert result["catalog_locator_ids"] == ["bsb00000754_00542_1", "bsb00000754_00542_25"]
    root = etree.fromstring(candidate)
    assert len(root.xpath("./t:text/t:body/t:div[@type='work']", namespaces=NS)) == 1
    assert "Monumenta Germaniae Historica" in " ".join(root.xpath("./t:teiHeader/t:fileDesc/t:publicationStmt", namespaces=NS)[0].itertext())
    notice = _io_path(STAGE / "library/works/origo-francorum/forms/origo-francorum-openmgh-retained/editions/origo-francorum-openmgh-electronic/README.source.md")
    assert b"Bavarian State Library" in notice.read_bytes()


@pytest.mark.parametrize("change", ["line-text", "line-id", "page-removed"])
def test_complete_division_oracle_rejects_source_mutations(change: str, historical_context: tuple[Path, Path, str]) -> None:
    manifest, entry, work, acquired, source, candidate = _bindings(historical_context[0])
    root = etree.fromstring(candidate)
    division = root.xpath("./t:text/t:body/t:div[@type='work']", namespaces=NS)[0]
    if change == "line-text":
        division.xpath(".//t:lb", namespaces=NS)[2].tail = "Changed source line.\n"
    elif change == "line-id":
        division.xpath(".//t:lb", namespaces=NS)[2].set("{http://www.w3.org/XML/1998/namespace}id", "changed-line")
    else:
        division.xpath(".//t:pb", namespaces=NS)[0].getparent().remove(division.xpath(".//t:pb", namespaces=NS)[0])
    with pytest.raises(ValueError, match="complete source work div"):
        check_candidate(source, etree.tostring(root, encoding="UTF-8", xml_declaration=True),
                        manifest, entry, work, acquired)


def test_frozen_read_only_preflight_rejects_wrong_pin(historical_context: tuple[Path, Path, str], monkeypatch: pytest.MonkeyPatch) -> None:
    root, freeze, digest = historical_context
    monkeypatch.setattr(installer, "ROOT", root)
    ready = preflight(freeze, expected_freeze_sha256=digest, work_id="origo-francorum", root=root)
    assert (ready["status"], ready["before_files"], ready["after_files"], ready["projection_rows"]) == (
        "ready-for-review", 3, 16, 1,
    )
    with pytest.raises(PipelineError, match="freeze changed"):
        preflight(freeze, expected_freeze_sha256="0" * 64, work_id="origo-francorum", root=root)


@pytest.fixture(scope="module")
def historical_context(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str]:
    raw = FREEZE.read_bytes()
    assert sha256(raw).hexdigest() == FREEZE_SHA
    original = json.loads(raw)
    home = tmp_path_factory.mktemp("origo-historical")
    root = historical_exact_work_root(ROOT, home / "root", MANIFEST, FREEZE, FREEZE_SHA)
    manifest_raw = MANIFEST.read_bytes()
    manifest = json.loads(manifest_raw)
    dependencies = [original["manifest"]]
    dependencies += [manifest[key] for key in ("source", "package", "acquisition_receipt", "source_inventory")]
    for binding in dependencies:
        payload = _io_path(ROOT / binding["path"]).read_bytes()
        assert sha256(payload).hexdigest() == binding["sha256"]
        target = _io_path(root / binding["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    stage_home = home / "stages"
    stage_home.mkdir()
    current = json.loads(raw)
    for pin in current["works"]:
        original_receipt = Path(original["stage_home"]) / pin["stage_receipt"]
        receipt_raw = _io_path(original_receipt).read_bytes()
        assert sha256(receipt_raw).hexdigest() == pin["stage_receipt_sha256"]
        record = json.loads(receipt_raw)
        stage = stage_home / pin["work_id"]
        shutil.copytree(_io_path(Path(record["stage_root"])), _io_path(stage))
        derived = dict(record, canonical_root=root.as_posix(), stage_root=stage.as_posix())
        assert dict(derived, canonical_root=record["canonical_root"], stage_root=record["stage_root"]) == record
        payload = (json.dumps(derived, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        (stage_home / pin["stage_receipt"]).write_bytes(payload)
        pin["stage_receipt_sha256"] = sha256(payload).hexdigest()
    current["stage_home"] = stage_home.as_posix()
    restored = json.loads(json.dumps(current))
    restored["stage_home"] = original["stage_home"]
    for pin, original_pin in zip(restored["works"], original["works"], strict=True):
        pin["stage_receipt_sha256"] = original_pin["stage_receipt_sha256"]
    assert restored == original
    payload = (json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    freeze = home / "freeze.json"
    freeze.write_bytes(payload)
    return root, freeze, sha256(payload).hexdigest()


def test_original_installer_rejects_wrong_root(historical_context: tuple[Path, Path, str]) -> None:
    with pytest.raises(PipelineError, match="canonical workspace checkout required"):
        preflight(FREEZE, expected_freeze_sha256=FREEZE_SHA, work_id="origo-francorum", root=historical_context[0])
