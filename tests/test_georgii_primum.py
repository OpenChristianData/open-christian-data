"""Exact retained first Georgius epitaph, exact display title and sibling conservation, bounded install, and rollback."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
import shutil
import pytest
from tests.historical_python_report_fixture import frozen_python_report_runtime  # noqa: F401

pytestmark = pytest.mark.usefixtures("frozen_python_report_runtime")
from build.tools import prepare_georgii_primum as parts
from build.tools import install_georgii_primum as installer
from build.tools import preflight_georgii_primum as guard
from build.tools.package_georgii_primum import challenge
from build.tei.georgii_primum_oracle import check
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path
ROOT=Path(__file__).resolve().parents[1]
RECEIPT=Path("D:/Library/Open Christian Data/candidate-reviews/georgii-primum-stage-20261001-v1.json")
def _bytes(p): return _io_path(p).read_bytes()
def _sha(p): return sha256(_bytes(p)).hexdigest()
def _json(x): return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
def test_source_features_and_ten_mutations():
    p=Path("D:/Library/Open Christian Data/candidate-reviews/georgii-primum-20261001-a-readable/package/content.tei.xml")
    proof=challenge(_bytes(ROOT/parts.SOURCE),_bytes(p))
    assert proof["baseline"]["elements"]==8
    assert len(proof["baseline"]["first_poem_lines"])==6
    assert proof["baseline"]["triplex_poem_line_counts"]==[6,6,6]
    assert proof["baseline"]["carrier_counts"]==dict(ab=1,lb=7)
    assert proof["baseline"]["shared_heading_context"] and proof["baseline"]["sibling_epitaphs_excluded"]
    assert len(proof["mutations"])==10
    with pytest.raises(ValueError,match="combined triplex exceeds this identity"):
        check(_bytes(ROOT/parts.SOURCE),_bytes(p),first_id=parts.FIRST,last_id=parts.COMBINED_LAST)

def test_exact_single_work_pin_and_language(monkeypatch):
    r=json.loads(_bytes(RECEIPT));assert installer._pin(RECEIPT.resolve(strict=True),r)==_sha(RECEIPT)
    assert installer.IDS=={parts.WORK_ID}
    for key,value in (("language","en"),("work_id","lambertus-epitaphium-georgii-aliud")):
        altered=dict(r);altered[key]=value
        with pytest.raises(PipelineError):installer._pin(RECEIPT.resolve(strict=True),altered)
    monkeypatch.setattr(installer,"PINS_SHA","0"*64)
    with pytest.raises(PipelineError,match="pin index changed"):installer._pin(RECEIPT.resolve(strict=True),r)
def _fixture(tmp_path,monkeypatch):
    r=json.loads(_bytes(RECEIPT));stage=Path(r["stage_root"]);fixture=tmp_path/"root";shutil.copytree(_io_path(stage),_io_path(fixture))
    w=Path("library/works")/parts.WORK_ID;target=fixture/w
    assert target.resolve(strict=True).is_relative_to(fixture.resolve(strict=True)) and not target.is_symlink()
    shutil.rmtree(_io_path(target))
    old=ROOT/w;profile=ROOT/r["profile_path"];manifest=ROOT/r["manifest_path"]
    journals=[]
    assert _sha(RECEIPT)=="8cb8103f11fd1c2b18225057444b09495cb31b31fe78868da8bd678c8c783f76"
    historical_root=Path(r["canonical_root"]).resolve(strict=True)
    for j in (historical_root/"library/.sidecar-operations").glob("georgii-primum-*/operation.json"):
        record=json.loads(_bytes(j))
        if record.get("phase")=="complete" and record.get("work_id")==parts.WORK_ID: journals.append(j)
    if journals:
        assert len(journals)==1
        operation=journals[0].parent;old=operation/"previous";profile=operation/"profile-before.json";manifest=operation/"manifest-before.json"
        record=json.loads(_bytes(journals[0]))
        assert record["stage_receipt_sha256"]==_sha(RECEIPT) and record["before"]==r["before"]
        assert _sha(profile)==r["profile_before_sha256"]
        assert _sha(manifest)==r["source_manifest_before_sha256"]
    shutil.copytree(_io_path(old),_io_path(target))
    for key,origin in (("profile_path",profile),("manifest_path",manifest)):shutil.copy2(_io_path(origin),_io_path(fixture/r[key]))
    assert _files(target)==r["before"]
    r["canonical_root"]=fixture.as_posix();receipt=tmp_path/"receipt.json";receipt.write_bytes(_json(r))
    pins=json.loads(_bytes(installer.PINS));pins["stages"][0].update(receipt=receipt.as_posix(),receipt_sha256=_sha(receipt));p=tmp_path/"pins.json";p.write_bytes(_json(pins))
    monkeypatch.setattr(installer,"PINS",p);monkeypatch.setattr(installer,"PINS_SHA",_sha(p));monkeypatch.setattr(parts,"ROOT",fixture)
    return r,receipt,fixture,target
@pytest.mark.parametrize("mutation",["title","combined-locator"])
def test_fixture_rejects_unrelated_work_authority(tmp_path,monkeypatch,mutation):
    r,receipt,fixture,target=_fixture(tmp_path,monkeypatch)
    staged_work=Path(r["stage_root"])/"library/works"/parts.WORK_ID/"work.json"
    # A fresh private stage copy lets the guard reach the additive metadata check.
    fresh=tmp_path/"stage";shutil.copytree(_io_path(Path(r["stage_root"])),_io_path(fresh));r["stage_root"]=fresh.as_posix()
    path=fresh/"library/works"/parts.WORK_ID/"work.json";work=json.loads(_bytes(path));
    if mutation=="title":work["title"]="invented title"
    else:work["textual_forms"][0]["editions"][0]["containing_source"]["locator"]=parts.SOURCE.as_posix()+"#"+parts.FIRST+"; "+parts.SOURCE.as_posix()+"#"+parts.COMBINED_LAST
    _io_path(path).write_bytes(_json(work));r["after"]=_files(path.parent);receipt.write_bytes(_json(r))
    with pytest.raises(PipelineError,match="outside exact poetry/la/first-poem title refinement"):guard.preflight(receipt)
def test_fixture_rolls_back_both_source_sidecars_then_installs(tmp_path,monkeypatch):
    r,receipt,fixture,target=_fixture(tmp_path,monkeypatch)
    assert guard.preflight(receipt)["status"]=="ready-for-review"
    before=_files(target);manifest=fixture/r["manifest_path"];profile=fixture/r["profile_path"];old_manifest,old_profile=_bytes(manifest),_bytes(profile)
    def fail(point):
        if point=="after-source-manifest.json-swap":raise RuntimeError("injected first-epitaph sidecar failure")
    with pytest.raises(RuntimeError,match="injected first-epitaph"):
        installer.install(receipt,expected_receipt_sha256=_sha(receipt),fail_at=fail,operation_prefix="georgii-fixture")
    assert _files(target)==before and _bytes(manifest)==old_manifest and _bytes(profile)==old_profile
    journals=list((fixture/"library/.sidecar-operations").glob("georgii-fixture-*/operation.json"));assert len(journals)==1 and json.loads(_bytes(journals[0]))["phase"]=="rolled-back"
    result=installer.install(receipt,expected_receipt_sha256=_sha(receipt),operation_prefix="georgii-fixture")
    assert result["status"]=="installed-and-validated" and result["projection_rows"]==1 and _files(target)==r["after"]


def test_protected_sibling_authority_fails_closed(tmp_path,monkeypatch):
    r,receipt,fixture,target=_fixture(tmp_path,monkeypatch)
    sibling=fixture/"library/works/lambertus-epitaphium-georgii-aliud/work.json"
    data=json.loads(_bytes(sibling));data["title"]="changed sibling title"
    _io_path(sibling).write_bytes(_json(data))
    with pytest.raises(ValueError,match="protected sibling generation changed"):
        guard.preflight(receipt)
