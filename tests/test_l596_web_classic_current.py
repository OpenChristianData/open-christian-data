from pathlib import Path
import hashlib
import json
import shutil
import pytest
from lxml import etree
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from build.tei.web_eng_oracle import _oracle
from tests.runtime_candidate_baselines import current_runtime_baseline
ROOT = Path(__file__).resolve().parents[1]
BASE = Path(r"D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925\web-eng-v3")
NS = {"t": "http://www.tei-c.org/ns/1.0"}
@pytest.fixture(scope="module")
def runtime_route(tmp_path_factory):
    case = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-l596-web.json").read_bytes())[0]
    return current_runtime_baseline(
        root=ROOT, original_manifest=case["original"], runtime_manifest=case["manifest"],
        retained_package=BASE / "package", retained_sha256=case["retained_package_sha256"],
        destination=tmp_path_factory.mktemp("web-current") / "candidate",
    )

def test_current_baseline(runtime_route):
    m,c = runtime_route
    result = validate(m,c,_oracle)
    assert result.status == "pass" and not result.findings
    tree = etree.fromstring(c.member_bytes("content.tei.xml"))
    assert len(tree.xpath("//*[local-name()='TEI']")) == 1
    titles = tree.xpath("./t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=NS)
    assert len(titles) == 1 and "".join(titles[0].itertext()).strip()
    assert len(tree.xpath(".//t:div[@type='chapter']", namespaces=NS)) == 1402
    assert len(tree.xpath(".//t:ab[@type='verse']", namespaces=NS)) == 38058
@pytest.mark.parametrize("mutation,reason", [("text","readable carrier text mismatch"),("omission","missing line:"),("heading","marker role mismatch"),("speaker","marker role mismatch")])
def test_source_mutations(tmp_path,mutation,reason,runtime_route):
    m,c = runtime_route; p = tmp_path / mutation
    shutil.copytree(c.path,p)
    try:
        f=p/"content.tei.xml"; tree=etree.parse(str(f))
        kind={"text":"verse","omission":"verse","heading":"usfm-d","speaker":"usfm-sp"}[mutation]
        node=tree.xpath(".//t:ab[@type=$kind]",namespaces=NS,kind=kind)[0]
        if mutation == "text": node.text=(node.text or "")+" MUTATED"
        elif mutation == "omission": node.getparent().remove(node)
        else: node.set("type","mutated-role")
        f.write_bytes(etree.tostring(tree,encoding="UTF-8",xml_declaration=True))
        mf=p/"manifest.json"; rec=json.loads(mf.read_bytes())
        for member in rec["members"]:
            data=(p/member["name"]).read_bytes();member["bytes"]=len(data);member["sha256"]=hashlib.sha256(data).hexdigest()
        mf.write_text(json.dumps(rec,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8")
        result=_oracle(m,CandidatePackage.load(p))
        assert result["status"] == "fail"
        assert any(reason in item for item in result["findings"]), result["findings"]
    finally:
        shutil.rmtree(p)
