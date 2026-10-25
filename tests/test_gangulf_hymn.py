"""Exact retained Gangulf hymn, literal title bracket, bounded install, and rollback."""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import pytest
from tests.historical_python_report_fixture import frozen_python_report_runtime  # noqa: F401

pytestmark = pytest.mark.usefixtures("frozen_python_report_runtime")
from build.tools import prepare_gangulf_hymn as parts
from build.tools import install_gangulf_hymn as installer
from build.tools import preflight_gangulf_hymn as guard
from build.tools.package_gangulf_hymn import challenge
from build.tei.gangulf_hymn_oracle import check
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path
ROOT=Path(__file__).resolve().parents[1]
RECEIPT=Path("D:/Library/Open Christian Data/candidate-reviews/gangulf-hymn-stage-20261001-v2.json")
BEFORE_HOME=ROOT/"tests/fixtures/reconstruction-runtime/authorities"
BEFORE_FIXTURES={'forms/hymnus-sancti-gangulfi-openmgh-retained/editions/hymnus-sancti-gangulfi-openmgh-electronic/acquisitions/hymnus-sancti-gangulfi-openmgh-acquired.json': 'acquisition.json', 'integration/source-boundary-preflight-20261001/README.md': 'boundary-readme.md', 'integration/source-boundary-preflight-20261001/source-boundary.json': 'source-boundary.json', 'state.json': 'state.json', 'work.json': 'work.json'}
def _bytes(p): return _io_path(p).read_bytes()
def _sha(p): return sha256(_bytes(p)).hexdigest()
def _json(x): return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
def test_source_features_and_ten_mutations():
    p=Path("D:/Library/Open Christian Data/candidate-reviews/gangulf-hymn-20261001-c-readable/package/content.tei.xml")
    proof=challenge(_bytes(ROOT/parts.SOURCE),_bytes(p))
    assert proof["baseline"]["elements"]==28
    assert [len(s["lines"]) for s in proof["baseline"]["stanzas"]]==[4]*5
    assert [c["spanTo"] for c in proof["baseline"]["column_spans"]]==["#cb20","#cb21"]
    assert proof["baseline"]["carrier_counts"]==dict(div=1,ab=1,lb=22,cb=2,anchor=2)
    assert proof["baseline"]["external_span_targets"]==0
    assert len(proof["mutations"])==10
    with pytest.raises(ValueError,match="historical endpoint belongs to Vita"):
        check(_bytes(ROOT/parts.SOURCE),_bytes(p),first_id="bsb00000754_00180_8",last_id="bsb00000754_00184_24")
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
    original_record=deepcopy(r)
    assert set(BEFORE_FIXTURES)==set(r["before"])
    for relative,digest in r["before"].items():
        origin=BEFORE_HOME/("gangulf-before."+BEFORE_FIXTURES[relative])
        assert _sha(origin)==digest
        destination=_io_path(target/relative);destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(_io_path(origin),destination)
    for key,label,hashkey in (("manifest_path","manifest-before.json","source_manifest_before_sha256"),
                              ("profile_path","profile-before.json","profile_before_sha256")):
        origin=BEFORE_HOME/("gangulf-before."+label)
        assert _sha(origin)==r[hashkey]
        shutil.copy2(_io_path(origin),_io_path(fixture/r[key]))
    assert _files(target)==r["before"]
    r["canonical_root"]=fixture.as_posix();receipt=tmp_path/"receipt.json";receipt.write_bytes(_json(r))
    restored=deepcopy(r);restored["canonical_root"]=original_record["canonical_root"];assert restored==original_record
    original_pins=json.loads(_bytes(installer.PINS));pins=deepcopy(original_pins)
    pins["stages"][0].update(receipt=receipt.as_posix(),receipt_sha256=_sha(receipt))
    restored_pins=deepcopy(pins)
    for key in ("receipt","receipt_sha256"):restored_pins["stages"][0][key]=original_pins["stages"][0][key]
    assert restored_pins==original_pins
    p=tmp_path/"pins.json";p.write_bytes(_json(pins))
    monkeypatch.setattr(installer,"PINS",p);monkeypatch.setattr(installer,"PINS_SHA",_sha(p));monkeypatch.setattr(parts,"ROOT",fixture)
    return r,receipt,fixture,target
@pytest.mark.parametrize("mutation",["title","old-locator"])
def test_fixture_rejects_unrelated_work_authority(tmp_path,monkeypatch,mutation):
    r,receipt,fixture,target=_fixture(tmp_path,monkeypatch)
    staged_work=Path(r["stage_root"])/"library/works"/parts.WORK_ID/"work.json"
    # A fresh private stage copy lets the guard reach the additive metadata check.
    fresh=tmp_path/"stage";shutil.copytree(_io_path(Path(r["stage_root"])),_io_path(fresh));r["stage_root"]=fresh.as_posix()
    path=fresh/"library/works"/parts.WORK_ID/"work.json";work=json.loads(_bytes(path));
    if mutation=="title":work["title"]="invented title"
    else:work["textual_forms"][0]["editions"][0]["containing_source"]["locator"]=parts.SOURCE.as_posix()+"#"+parts.FIRST+"; "+parts.SOURCE.as_posix()+"#"+parts.OLD_LAST
    _io_path(path).write_bytes(_json(work));r["after"]=_files(path.parent);receipt.write_bytes(_json(r))
    with pytest.raises(PipelineError,match="outside exact poetry/la/locator refinement"):guard.preflight(receipt)
def test_fixture_rolls_back_both_source_sidecars_then_installs(tmp_path,monkeypatch):
    r,receipt,fixture,target=_fixture(tmp_path,monkeypatch)
    assert guard.preflight(receipt)["status"]=="ready-for-review"
    before=_files(target);manifest=fixture/r["manifest_path"];profile=fixture/r["profile_path"];old_manifest,old_profile=_bytes(manifest),_bytes(profile)
    def fail(point):
        if point=="after-source-manifest.json-swap":raise RuntimeError("injected whole-hymn sidecar failure")
    with pytest.raises(RuntimeError,match="injected whole-hymn"):
        installer.install(receipt,expected_receipt_sha256=_sha(receipt),fail_at=fail,operation_prefix="gangulf-fixture")
    assert _files(target)==before and _bytes(manifest)==old_manifest and _bytes(profile)==old_profile
    journals=list((fixture/"library/.sidecar-operations").glob("gangulf-fixture-*/operation.json"));assert len(journals)==1 and json.loads(_bytes(journals[0]))["phase"]=="rolled-back"
    result=installer.install(receipt,expected_receipt_sha256=_sha(receipt),operation_prefix="gangulf-fixture")
    assert result["status"]=="installed-and-validated" and result["projection_rows"]==1 and _files(target)==r["after"]
