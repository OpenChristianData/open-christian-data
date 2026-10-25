from __future__ import annotations
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
from lxml import etree
import pytest
from ocd_kernel.reconstruction.contract import CandidatePackage,SourceManifest
from build.tei.wikisource_l594_chrysostom_oracle_v2 import _oracle
ROOT=Path(__file__).resolve().parents[1]
RUNTIME_ROOT=ROOT
ORIGINAL_MANIFEST=ROOT/'sources/manifest-acquisitions/wikisource-chrysostom-l594/source-manifest-v3.json'
MANIFEST=ROOT/'tests/fixtures/reconstruction-runtime/wikisource-l594-chrysostom-v3.source-manifest.json'
def _run(destination:Path)->dict:
    result=subprocess.run([sys.executable,str(ROOT/'build/tools/reconstruct_candidate.py'),'--manifest',MANIFEST.relative_to(RUNTIME_ROOT).as_posix(),'--destination',str(destination),'--repository-root',str(RUNTIME_ROOT)],cwd=ROOT,check=False,capture_output=True,text=True)
    assert result.returncode==0,result.stderr+result.stdout
    return json.loads([line for line in result.stdout.splitlines() if line.startswith('{')][-1])
def _files(root:Path)->dict[str,str]:
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
def test_fresh_process_reproduction_and_complete_export_inventory(tmp_path:Path,current_catalog_context)->None:
    first=tmp_path/'first';second=tmp_path/'second';a=_run(first);b=_run(second)
    assert a['status']==b['status']=='pass'
    assert a['candidate']['sha256']==b['candidate']['sha256']
    assert _files(first)==_files(second)
    validation=json.loads((first/'validation.json').read_bytes())
    assert validation['status']=='pass' and validation['findings']==[]
    tei=etree.parse(str(first/'package/content.tei.xml'))
    assert len(tei.xpath('/*[local-name()="TEI"]'))==1
    assert len(tei.xpath('//*[local-name()="TEI"]'))==1
    assert len(tei.xpath('//*[local-name()="titlePage"]'))==1
    assert [(g.get("n"),g.get("quantity"),g.get("unit")) for g in tei.xpath('//*[local-name()="gap" and @reason="not-transcribed"]')]==[("1-6","6","scan-position"),("8-118","111","scan-position")]
    assert [etree.QName(n).localname for n in tei.xpath('//*[local-name()="front"]/*')]==["gap","titlePage"]
    assert etree.QName(tei.xpath('//*[local-name()="body"]/*[1]')[0]).localname=="gap"
    accountability=json.loads((first/'package/source-accountability.json').read_bytes())
    assert accountability['export_record_count']==81
    assert etree.parse(str(first/'package/content.tei.xml')).getroot().get('{http://www.w3.org/XML/1998/namespace}id')=='chrysostom-divine-and-sacred-liturgy'
    assert accountability['work_id']=='chrysostom-divine-and-sacred-liturgy'
    assert accountability['textual_form_id']=='chrysostom-divine-and-sacred-liturgy-wikisource-retained'
    assert accountability['edition_id']=='chrysostom-divine-and-sacred-liturgy-wikisource-electronic'
    assert accountability['acquisition_id']=='chrysostom-divine-and-sacred-liturgy-wikisource-acquired'
    assert accountability['work_catalog_link']['identity']['work_id']==accountability['work_id']
    assert accountability['record_disposition']=={'work':1,'proofread-page':1,'index':1,'support':78}
    assert len(accountability['transclusion']['linked_subpages'])==2
    assert accountability["scan_position_accounting"]=={
        "index_page_title":"Index:Liturgy of John Chrysostom (1866).pdf",
        "indexed_positions":{"first":1,"last":118,"count":118},
        "retained_positions":[{"page_title":"Page:Liturgy of John Chrysostom (1866).pdf/7","position":7}],
        "untranscribed_ranges":[{"first":1,"last":6,"count":6},{"first":8,"last":118,"count":111}],
        "untranscribed_count":117,
    }

def test_source_witness_mutation_is_rejected(tmp_path:Path,current_catalog_context)->None:
    baseline=tmp_path/'baseline';package=tmp_path/'mutated-package';_run(baseline);shutil.copytree(baseline/'package',package)
    content_path=package/'content.tei.xml';old=content_path.read_bytes();marker=b'<ab type="page-7-wikitext"';offset=old.index(marker);prefix,suffix=old[:offset],old[offset:];needle=b'JOSEPH MASTERS';replacement=b'JOSEPH ALTERED'
    assert suffix.count(needle)==1
    new=prefix+suffix.replace(needle,replacement,1);content_path.write_bytes(new)
    record=json.loads((package/'manifest.json').read_bytes())
    for item in record['members']:
        if item['name']=='content.tei.xml':item.update(bytes=len(new),sha256=hashlib.sha256(new).hexdigest())
    (package/'manifest.json').write_text(json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
    candidate=CandidatePackage.load(package);manifest=SourceManifest.load(MANIFEST,repository_root=RUNTIME_ROOT);result=_oracle(manifest,candidate)
    assert result['status']=='fail'
    assert any('Page 7 source wikitext differs' in item for item in result['findings'])


def test_indexed_scan_position_gap_mutation_is_rejected(tmp_path:Path,current_catalog_context)->None:
    baseline=tmp_path/'baseline';package=tmp_path/'mutated-package';_run(baseline);shutil.copytree(baseline/'package',package)
    content_path=package/'content.tei.xml';tree=etree.parse(str(content_path))
    gaps=tree.xpath('//*[local-name()="gap" and @reason="not-transcribed"]')
    assert [(g.get("n"),g.get("quantity")) for g in gaps]==[("1-6","6"),("8-118","111")]
    gaps[0].set("n","2-6")
    new=etree.tostring(tree,encoding="UTF-8",xml_declaration=True,pretty_print=True)
    content_path.write_bytes(new)
    record=json.loads((package/'manifest.json').read_bytes())
    for item in record['members']:
        if item['name']=='content.tei.xml':item.update(bytes=len(new),sha256=hashlib.sha256(new).hexdigest())
    (package/'manifest.json').write_text(json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
    candidate=CandidatePackage.load(package);manifest=SourceManifest.load(MANIFEST,repository_root=RUNTIME_ROOT);result=_oracle(manifest,candidate)
    assert result['status']=='fail'
    assert any('indexed page gap positions differ' in item for item in result['findings'])


def test_wrong_work_id_is_rejected(tmp_path:Path,current_catalog_context)->None:
    baseline=tmp_path/'baseline';package=tmp_path/'mutated-package';_run(baseline);shutil.copytree(baseline/'package',package)
    path=package/'content.tei.xml';tree=etree.parse(str(path));tree.getroot().set('{http://www.w3.org/XML/1998/namespace}id','unbound-route-local-id')
    new=etree.tostring(tree,encoding='UTF-8',xml_declaration=True,pretty_print=True);path.write_bytes(new)
    record=json.loads((package/'manifest.json').read_bytes())
    for item in record['members']:
        if item['name']=='content.tei.xml':item.update(bytes=len(new),sha256=hashlib.sha256(new).hexdigest())
    (package/'manifest.json').write_text(json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
    candidate=CandidatePackage.load(package);manifest=SourceManifest.load(MANIFEST,repository_root=RUNTIME_ROOT);result=_oracle(manifest,candidate)
    assert result['status']=='fail'
    assert any('TEI root xml:id' in item for item in result['findings'])



def test_runtime_manifest_preserves_complete_original_and_actual_current_oracle_closure():
    from copy import deepcopy
    from build.tei.wikisource_l594_chrysostom_oracle_v2 import _json as oracle_json, _sha as oracle_sha

    original_raw = ORIGINAL_MANIFEST.read_bytes()
    assert hashlib.sha256(original_raw).hexdigest() == "2eb84bac1e71e1dea6e75a8a2cd2e35a5c4862dbf661bb13cb945f4d6886cdad"
    # The historical Windows checkout used CRLF for this same complete record.
    assert hashlib.sha256(original_raw.replace(b"\n", b"\r\n")).hexdigest() == "ec9995b46d5a3068f82cf57af9bdba1b509c0c84d9029e7c7c4116ddfdfffe25"
    original = json.loads(original_raw)
    runtime = json.loads(MANIFEST.read_bytes())
    restored = deepcopy(runtime)
    restored["validator"]["import_closure_sha256"] = original["validator"]["import_closure_sha256"]
    assert restored == original
    records = [
        {"path": "build/tei/wikisource_l594_chrysostom_oracle_v2.py",
         "sha256": oracle_sha((ROOT / "build/tei/wikisource_l594_chrysostom_oracle_v2.py").read_bytes())},
        {"path": "ocd_kernel/reconstruction/contract.py",
         "sha256": oracle_sha((ROOT / "ocd_kernel/reconstruction/contract.py").read_bytes())},
    ]
    assert oracle_sha(oracle_json(records)) == runtime["validator"]["import_closure_sha256"]
    SourceManifest.load(ORIGINAL_MANIFEST, repository_root=ROOT).verify()
    SourceManifest.load(MANIFEST, repository_root=ROOT).verify()


_CURRENT_CATALOG = [{'role': 'work', 'fixture': 'tests/fixtures/reconstruction-runtime/authorities/wikisource-l594-current-catalog-work.json', 'path': 'library/works/chrysostom-divine-and-sacred-liturgy/work.json', 'bytes': 983, 'sha256': '5f9fb2420e01e697a9381a5a530b9a3d46a43b0939c94f6a9d0efdf83afd3000'}, {'role': 'state', 'fixture': 'tests/fixtures/reconstruction-runtime/authorities/wikisource-l594-current-catalog-state.json', 'path': 'library/works/chrysostom-divine-and-sacred-liturgy/state.json', 'bytes': 2705, 'sha256': '81673c9341df9b8f0f93074f2d2e80149725879f517553771c68db6d8b70d540'}, {'role': 'acquisition', 'fixture': 'tests/fixtures/reconstruction-runtime/authorities/wikisource-l594-current-catalog-acquisition.json', 'path': 'library/works/chrysostom-divine-and-sacred-liturgy/forms/chrysostom-divine-and-sacred-liturgy-wikisource-retained/editions/chrysostom-divine-and-sacred-liturgy-wikisource-electronic/acquisitions/chrysostom-divine-and-sacred-liturgy-wikisource-acquired.json', 'bytes': 1866, 'sha256': 'a744231a71f57835362ec52280e1f37de7b9e35869d6ccdb691421749a40eda0'}]


def _l594_json(record):
    return (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


@pytest.fixture
def current_catalog_context(tmp_path, monkeypatch):
    """Bind a private current catalog without changing the historical source profile."""
    from copy import deepcopy
    from ocd_kernel.lib.storage_topology import resolve_repo_path
    from ocd_kernel.lib.path_io import io_path

    original_profile_raw = (ROOT / "sources/manifest-acquisitions/wikisource-chrysostom-l594/profile-v2.json").read_bytes()
    assert hashlib.sha256(original_profile_raw).hexdigest() == "5f046ce6a1e7f03e54db8ad6afd985e91fdbf95115165c6d4eb2cf3792ef87b9"
    original_profile = json.loads(original_profile_raw)
    original_runtime_raw = MANIFEST.read_bytes()
    original_runtime = json.loads(original_runtime_raw)
    SourceManifest.load(MANIFEST, repository_root=ROOT).verify()
    root = tmp_path / "r"
    root.mkdir()
    references = {row["path"] for row in original_runtime["authorities"]}
    references.update(original_runtime[key]["implementation_path"] for key in ("converter", "validator"))
    references.add("ocd_kernel/reconstruction/contract.py")
    for relative in sorted(references):
        raw = resolve_repo_path(ROOT, relative).read_bytes()
        target = io_path(root / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    from tests.vendored_schema_mirrors import copy_vendored_schema_imports
    copy_vendored_schema_imports(ROOT, root)
    profile = deepcopy(original_profile)
    link = profile["work_catalog_link"]
    link["canonical_workspace_root"] = str(io_path(root))
    assert len(link["sidecars"]) == len(_CURRENT_CATALOG) == 3
    for row, bound in zip(link["sidecars"], _CURRENT_CATALOG):
        assert row["role"] == bound["role"] and row["path"] == bound["path"]
        raw = (ROOT / bound["fixture"]).read_bytes()
        assert len(raw) == bound["bytes"] and hashlib.sha256(raw).hexdigest() == bound["sha256"]
        target = io_path(root / row["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        row.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    restored_profile = deepcopy(profile)
    restored_profile["work_catalog_link"]["canonical_workspace_root"] = original_profile["work_catalog_link"]["canonical_workspace_root"]
    for row, original in zip(restored_profile["work_catalog_link"]["sidecars"], original_profile["work_catalog_link"]["sidecars"]):
        row.update(bytes=original["bytes"], sha256=original["sha256"])
    assert restored_profile == original_profile
    profile_row = next(row for row in original_runtime["authorities"] if row["name"] == "profile")
    private_profile_raw = _l594_json(profile)
    io_path(root / profile_row["path"]).write_bytes(private_profile_raw)
    runtime = deepcopy(original_runtime)
    current_row = next(row for row in runtime["authorities"] if row["name"] == "profile")
    current_row.update(bytes=len(private_profile_raw), sha256=hashlib.sha256(private_profile_raw).hexdigest())
    restored_runtime = deepcopy(runtime)
    next(row for row in restored_runtime["authorities"] if row["name"] == "profile").update(profile_row)
    assert restored_runtime == original_runtime
    manifest = root / MANIFEST.relative_to(ROOT)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_bytes(_l594_json(runtime))
    loaded = SourceManifest.load(manifest, repository_root=root)
    assert loaded.sha256 == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert json.loads(json.dumps(loaded.record, default=dict)) == runtime
    monkeypatch.setattr(sys.modules[__name__], "RUNTIME_ROOT", root)
    monkeypatch.setattr(sys.modules[__name__], "MANIFEST", manifest)
    yield {"root": root, "manifest": manifest, "original_runtime": original_runtime,
           "original_profile": original_profile, "runtime": runtime, "profile": profile}
    assert (ROOT / "sources/manifest-acquisitions/wikisource-chrysostom-l594/profile-v2.json").read_bytes() == original_profile_raw
    assert (ROOT / "tests/fixtures/reconstruction-runtime/wikisource-l594-chrysostom-v3.source-manifest.json").read_bytes() == original_runtime_raw


def test_current_catalog_profile_has_complete_inverse_and_rejects_drift(tmp_path, current_catalog_context):
    from copy import deepcopy
    context = current_catalog_context
    original_runtime = context["original_runtime"]
    runtime = deepcopy(context["runtime"])
    next(row for row in runtime["authorities"] if row["name"] == "profile").update(
        next(row for row in original_runtime["authorities"] if row["name"] == "profile"))
    assert runtime == original_runtime
    profile = deepcopy(context["profile"])
    original = context["original_profile"]["work_catalog_link"]
    profile["work_catalog_link"]["canonical_workspace_root"] = original["canonical_workspace_root"]
    for row, old in zip(profile["work_catalog_link"]["sidecars"], original["sidecars"]):
        row.update(bytes=old["bytes"], sha256=old["sha256"])
    assert profile == context["original_profile"]
    baseline = tmp_path / "catalog-baseline"
    _run(baseline)
    candidate = CandidatePackage.load(baseline / "package")
    manifest = SourceManifest.load(MANIFEST, repository_root=RUNTIME_ROOT)
    assert _oracle(manifest, candidate)["status"] == "pass"
    target = RUNTIME_ROOT / _CURRENT_CATALOG[0]["path"]
    old = target.read_bytes()
    target.write_bytes(old + b" ")
    try:
        result = _oracle(manifest, candidate)
        assert result["status"] == "fail"
        assert "WorkCatalog sidecar bytes or SHA-256 differ: work" in result["findings"]
    finally:
        target.write_bytes(old)
