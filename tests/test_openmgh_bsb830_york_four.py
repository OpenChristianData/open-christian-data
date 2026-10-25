"""Exact retained York IV, source breakoff, bounded install, and rollback."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
import shutil
import pytest
from tests.historical_python_report_fixture import frozen_python_report_runtime

pytestmark = pytest.mark.usefixtures("frozen_python_report_runtime")
from build.tools import prepare_openmgh_bsb830_york_four as parts
from build.tools import install_openmgh_bsb830_york_four as installer
from build.tools import preflight_openmgh_bsb830_york_four as guard
from build.tools.package_openmgh_bsb830_york_four import challenge
from build.tei.openmgh_bsb830_york_four_oracle import check
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path
from tests.openmgh_journal_historical_fixture import restore_mgh_journal_before
ROOT=Path(__file__).resolve().parents[1]
RECEIPT=Path("D:/Library/Open Christian Data/candidate-reviews/y830iv-stage-20261001-v2.json")
def _bytes(p): return _io_path(p).read_bytes()
def _sha(p): return sha256(_bytes(p)).hexdigest()
def _json(x): return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
def test_source_features_and_seven_mutations():
    p=Path("D:/Library/Open Christian Data/candidate-reviews/y830iv-20261001-c-readable/package/content.tei.xml")
    proof=challenge(_bytes(ROOT/parts.SOURCE),_bytes(p))
    assert proof["baseline"]["element_count"]==1420
    assert proof["baseline"]["carrier_counts"]==dict(div=1,ab=1,lb=724,w=276,hi=401,pb=17)
    assert proof["baseline"]["external_fragment_target_count"]==0
    assert len(proof["mutations"])==7
    with pytest.raises(ValueError,match="complete York fourth part"):
        check(_bytes(ROOT/parts.SOURCE),_bytes(p),first_id="bsb00000830_00671_27",last_id="bsb00000830_00688_27",part_ordinal=4)
def test_exact_single_work_pin_and_language(monkeypatch):
    r=json.loads(_bytes(RECEIPT));assert installer._pin(RECEIPT.resolve(strict=True),r)==_sha(RECEIPT)
    assert installer.IDS=={parts.WORK_ID}
    for key,value in (("language","en"),("work_id","york-tractate-roman-pontiff")):
        altered=dict(r);altered[key]=value
        with pytest.raises(PipelineError):installer._pin(RECEIPT.resolve(strict=True),altered)
    monkeypatch.setattr(installer,"PINS_SHA","0"*64)
    with pytest.raises(PipelineError,match="pin index changed"):installer._pin(RECEIPT.resolve(strict=True),r)
def _fixture(tmp_path,monkeypatch):
    r=json.loads(_bytes(RECEIPT));stage=Path(r["stage_root"]);fixture=tmp_path/"root";shutil.copytree(_io_path(stage),_io_path(fixture))
    w=Path("library/works")/parts.WORK_ID;target=fixture/w
    assert target.resolve(strict=True).is_relative_to(fixture.resolve(strict=True)) and not target.is_symlink()
    shutil.rmtree(_io_path(target))
    restore_mgh_journal_before(fixture,r)
    assert _files(target)==r["before"]
    r["canonical_root"]=fixture.as_posix();receipt=tmp_path/"receipt.json";receipt.write_bytes(_json(r))
    pins=json.loads(_bytes(installer.PINS));pins["stages"][0].update(receipt=receipt.as_posix(),receipt_sha256=_sha(receipt));p=tmp_path/"pins.json";p.write_bytes(_json(pins))
    monkeypatch.setattr(installer,"PINS",p);monkeypatch.setattr(installer,"PINS_SHA",_sha(p));monkeypatch.setattr(parts,"ROOT",fixture)
    return r,receipt,fixture,target
def test_fixture_rejects_unrelated_work_authority(tmp_path,monkeypatch):
    r,receipt,fixture,target=_fixture(tmp_path,monkeypatch)
    staged_work=Path(r["stage_root"])/"library/works"/parts.WORK_ID/"work.json"
    # A fresh private stage copy lets the guard reach the additive metadata check.
    fresh=tmp_path/"stage";shutil.copytree(_io_path(Path(r["stage_root"])),_io_path(fresh));r["stage_root"]=fresh.as_posix()
    path=fresh/"library/works"/parts.WORK_ID/"work.json";work=json.loads(_bytes(path));work["title"]="invented title";_io_path(path).write_bytes(_json(work));r["after"]=_files(path.parent);receipt.write_bytes(_json(r))
    with pytest.raises(PipelineError,match="outside exact prose/la additions"):guard.preflight(receipt)
def test_fixture_rolls_back_both_source_sidecars_then_installs(tmp_path,monkeypatch):
    r,receipt,fixture,target=_fixture(tmp_path,monkeypatch)
    assert guard.preflight(receipt)["status"]=="ready-for-review"
    before=_files(target);manifest=fixture/r["manifest_path"];profile=fixture/r["profile_path"];old_manifest,old_profile=_bytes(manifest),_bytes(profile)
    def fail(point):
        if point=="after-source-manifest.json-swap":raise RuntimeError("injected fourth-tractate sidecar failure")
    with pytest.raises(RuntimeError,match="injected fourth-tractate"):
        installer.install(receipt,expected_receipt_sha256=_sha(receipt),fail_at=fail,operation_prefix="york-iv-fixture")
    assert _files(target)==before and _bytes(manifest)==old_manifest and _bytes(profile)==old_profile
    journals=list((fixture/"library/.sidecar-operations").glob("york-iv-fixture-*/operation.json"));assert len(journals)==1 and json.loads(_bytes(journals[0]))["phase"]=="rolled-back"
    result=installer.install(receipt,expected_receipt_sha256=_sha(receipt),operation_prefix="york-iv-fixture")
    assert result["status"]=="installed-and-validated" and result["projection_rows"]==1 and _files(target)==r["after"]


def test_current_generation_rejects_historical_receipt(tmp_path: Path) -> None:
    assert _sha(installer.PINS) == installer.PINS_SHA
    pins = json.loads(_bytes(installer.PINS))
    pin = pins["stages"][0]
    original = Path(pin["receipt"])
    assert _sha(original) == pin["receipt_sha256"]
    record = json.loads(_bytes(original))
    work = Path("library/works") / record["work_id"]
    assert _files(ROOT / work) != record["before"]
    context = dict(record, canonical_root=ROOT.as_posix())
    assert dict(context, canonical_root=record["canonical_root"]) == record
    receipt = tmp_path / "current-generation-negative.json"
    receipt.write_bytes(_json(context))
    with pytest.raises(PipelineError, match="work identity or generation changed"):
        guard.preflight(receipt)
