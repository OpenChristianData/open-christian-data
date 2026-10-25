"""Bind only the already acquired complete Hexaemeron subtree; no acquisition."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import basil_hexaemeron_reconstruction as producer
from build.tei import basil_hexaemeron_oracle as checker
from build.tei import npnf2_lib046_reconstruction as prior
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT=Path(__file__).resolve().parents[2]
BASE=Path("sources/manifest-acquisitions/basil-hexaemeron-npnf208")
WORK_ID="basil-of-caesarea-hexaemeron"
FORM_ID=WORK_ID+"-ccel-npnf208-retained-en"
EDITION_ID=WORK_ID+"-ccel-npnf208-electronic"
ACQUISITION_ID=WORK_ID+"-ccel-npnf208-acquired"
WORK=Path("library/works")/WORK_ID
EDITION=WORK/"forms"/FORM_ID/"editions"/EDITION_ID
ACQUISITION=EDITION/"acquisitions"/(ACQUISITION_ID+".json")

canonical=producer.canonical

def put(path,payload):
    target=io_path(ROOT/path); target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(payload)

def binding(name,path,role):
    payload=io_path(ROOT/path).read_bytes()
    return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(payload),sha256=sha256(payload).hexdigest())

def main():
    roster=json.loads((ROOT/"plans/2026-09-22-source-preflight/whole-library-handoff-inventory-20260926.json").read_bytes())
    if not any(w["work_id"]==WORK_ID for w in roster["works"]):
        raise ValueError("outside fixed roster")
    acquisition=validate_acquisition(io_path(ROOT/ACQUISITION),root=ROOT)
    raw=(ROOT/producer.SOURCE).read_bytes()
    if acquisition["source_sha256"]!=producer.SOURCE_SHA or sha256(raw).hexdigest()!=producer.SOURCE_SHA:
        raise ValueError("acquisition/retained source differs")
    tree=prior._parse(ROOT/producer.SOURCE)
    source=tree.xpath("/ThML/ThML.body/div1[@id='viii']")[0]
    header=prior._header({"npnf208":tree})
    title=header.find(".//{http://www.tei-c.org/ns/1.0}titleStmt/{http://www.tei-c.org/ns/1.0}title")
    title.text="The Hexæmeron."; title.attrib.pop("n")
    desc=header.find(".//{http://www.tei-c.org/ns/1.0}sourceDesc")
    wrapper=desc[0]; bibl=wrapper[0]; wrapper.remove(bibl); desc.remove(wrapper); desc.append(bibl)
    for credit in header.xpath(".//t:note[@source]",namespaces={"t":"http://www.tei-c.org/ns/1.0"}):
        credit.set("source","https://www.ccel.org/ccel/schaff/npnf208.html"+credit.get("source"))
    questions=[dict(id="basil-hexaemeron-"+slug,scope="complete retained electronic Hexaemeron",status="unresolved",evidence=text) for slug,text in [
        ("human-visual-print-rights","Human verification, visual comparison, print collation, rights clearance and publication are separate and not established."),
        ("native-reference-parser","Native scripRef annotations are preserved exactly; their Bible parsing is not independently corrected. viii.iii-p43.1 is Jerome Quaest. Heb. column508, represented neutrally with original annotations."),
        ("credit-allocation","Retained volume title pages/preface credit Schaff, Wace and Jackson. Preserve their source-level roles without independently allocating all contributors to the child.")]]
    profile=dict(contract="ocd-basil-hexaemeron-profile-v1",work_id=WORK_ID,source_sha256=producer.SOURCE_SHA,
        scope="Complete NPNF208 div1 viii: Introduction and nine homilies; one complete work, one TEI. No sibling works in readable body.",
        boundary_basis="Retained complete volume top-level children i through x; vii De Spiritu Sancto, viii The Hexæmeron, ix The Letters. viii has Introduction viii.i and nine numbered homilies viii.ii through viii.x; its own explicit div1 closure precedes ix.",
        assigned_census=prior._census(list(source.iter())),header_hex=etree.tostring(header[0],encoding="utf-8").hex(),
        mapping="Reuse unchanged source-local LIB046 element/attribute/text/tail mapping for viii alone, with independent historical checker. Every native source attribute retained in accountability. One exact scholarly column reference has neutral type while cRef and target retain original parser annotations. Header uses one sourceDesc/bibl for the containing volume and omits redundant converter-added title@n source-key scaffolding; all source metadata/credit values conserved.",
        independence="Separate historical producer and oracle traverse source independently and use distinct mapping implementations; shared lxml parser corroborated for complete volume by stdlib ElementTree, every tag, attribute, text and tail. Source-grounded policy and inherited exposure disclosed; not blind review.",
        exclusions="All other div1 roots, volume title pages/preface/prolegomena/indexes remain full-document accounted outside body. Shared contributors and metadata retained in header/source notice; no neighboring work is repeated as text.",candidate_questions=questions)
    put(BASE/"profile.json",canonical(profile))
    notice=("# Basil of Caesarea: The Hexaemeron retained source\n\nComplete child work `/ThML/ThML.body/div1[8]`, ID `viii`, in retained NPNF2-08. Basil: Letters and Select Works; sourced via CCEL.org. Introduction and nine homilies remain one work. Retained print-source statement: Edinburgh: T&T Clark, 1895; no print collation performed.\n\nCCEL permission evidence permits parsing, reserves files/formatting rights and restricts selling those files or derivatives of formatting. Public Domain is the provider's retained text statement, not a new rights determination. Carry human-visible attribution to `data/structured-text/basil-of-caesarea-hexaemeron/README.md`. Human review, rights and publication remain separate.\n\n## Retained electronic header and stylesheet support\n\n"+etree.tostring(tree.find('ThML.head'),encoding='unicode')+"\n\n## Source title-page/preface contributor context\n\n"+"\n\n".join(prior._source_text(tree,i) for i in ["i-p10","i-p11","i-p13","i-p14","ii-p8","iii-p4","iii-p5","iii-p6"])+"\n").encode()
    put(BASE/"README.source.md",notice)
    policy=json.loads((ROOT/"sources/structured-text/npnf2-lib046/npnf2-lib046.validation-policy.json").read_bytes())
    policy["child_scope"]="viii only; introduction+9 homilies"
    policy["located_override"]={"source_xml_id":"viii.iii-p43.1","type":"source-reference","native_annotations":"retain exact cRef and target; no inferred Bible identity"}
    put(BASE/"validation-policy.json",canonical(policy))
    paths=[("retained-source",producer.SOURCE,"primary-source"),("profile",BASE/"profile.json","complete-source-feature-profile"),("validation-policy",BASE/"validation-policy.json","independent-validation-policy"),("source-readme",BASE/"README.source.md","source-attribution-readme"),
        ("tei-p5-xsd","ocd_kernel/tei/vendor/xsd/tei_all.xsd","tei-validation-schema"),("candidate-package-schema","ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","candidate-package-schema"),
        ("historical-producer","build/tei/npnf2_lib046_reconstruction.py","supporting-producer"),("historical-oracle","build/tei/npnf2_lib046_oracle.py","supporting-independent-checker"),
        ("child-boundary-evidence","plans/2026-09-22-source-preflight/basil-npnf208-child-scope-20260926.json","child-boundary-evidence"),("canonical-acquisition",ACQUISITION,"canonical-acquisition-evidence"),("ccel-permission","docs/sources/ccel-permission.md","source-permission-evidence")]
    manifest=dict(contract="ocd-source-manifest-v1",source_id="basil-hexaemeron-npnf208-viii-v1",work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,
        authorities=[binding(*p) for p in paths],scope=dict(kind="complete-source-subtree",root="viii"),
        converter=dict(id=producer.CONVERTER_ID,version=producer.CONVERTER_VERSION,callable="_convert",implementation_path=Path(producer.__file__).relative_to(ROOT).as_posix(),implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),
        validator=dict(id=checker.ORACLE_ID,version=checker.ORACLE_VERSION,callable="_oracle",implementation_path=Path(checker.__file__).relative_to(ROOT).as_posix(),implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha()),
        package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",sha256=sha256((ROOT/"ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()).hexdigest()))
    put(BASE/"source-manifest.json",canonical(manifest))
    print(json.dumps(dict(status="prepared",census=profile["assigned_census"],acquisition_sha256=sha256(io_path(ROOT/ACQUISITION).read_bytes()).hexdigest())))

if __name__=="__main__":main()
