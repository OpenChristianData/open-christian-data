"""Bind the complete retained HCC4 volume and literal source credits."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import schaff_history_vol4_current_reconstruction as producer, schaff_history_vol4_current_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT=Path(__file__).resolve().parents[2]
WORK_ID="schaff-history-vol-4"
FORM_ID=WORK_ID+"-ccel-hcc4-retained-en"
EDITION_ID=WORK_ID+"-ccel-hcc4-electronic"
ACQUISITION_ID=WORK_ID+"-ccel-hcc4-acquired"
WORK=Path("library/works")/WORK_ID
EDITION=WORK/"forms"/FORM_ID/"editions"/EDITION_ID
ACQUISITION=EDITION/"acquisitions"/(ACQUISITION_ID+".json")
BASE=Path("sources/ccel-schaff-hcc4-current")/WORK_ID
SOURCE=Path("raw/ccel/schaff/hcc4.xml")
SOURCE_SHA="7a4b158f20983c50fac6542e1904a24e611f52dba7f293fc4831e2d3030364d6"
TITLE="History of the Christian Church, Vol. 4: Medieval Christianity, A.D. 590-1073"
SCOPE="Complete retained CCEL hcc4.xml volume IV: both ordered body roots i Mediaeval Christianity (opening title/context and fourteen complete chapters with 182 nested divisions) and ii Indexes with all five integral indexes. All 15,955 native source elements, 15,804 body elements, 1,545 notes, two subject-index markers, literal verse/line structure and the source unclear reading are conserved with exact mixed text, tails, parents, order, IDs and ordered attributes. Existing readable native body, source header, standOff and two prolog comments are reused; the only body repair restores all 589 literal source language annotations as xml:lang. Stripping precisely those verified additions reproduces the entire native base body/evidence bytes. No body exclusion, normalized correction, invented print completion or new work identity; one existing work and one TEI. No image elements occur in the retained XML. Source DC.Rights and published fields are empty; no license or print-edition identity is inferred. Literal edition-history and provider permission are retained evidence, not independent print equivalence or rights clearance."
DATA_NOTICE=Path("data/prose")/WORK_ID/"README.md"
canonical=producer.canonical
NS="{http://www.tei-c.org/ns/1.0}"

def put(path,content):
    target=io_path(ROOT/path);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)

def binding(name,path,role):
    content=io_path(ROOT/path).read_bytes()
    return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(content),sha256=sha256(content).hexdigest())

def main():
    source=io_path(ROOT/SOURCE).read_bytes();acq=validate_acquisition(io_path(ROOT/ACQUISITION),root=ROOT)
    if sha256(source).hexdigest()!=SOURCE_SHA or acq["source_sha256"]!=SOURCE_SHA:raise ValueError("source/acquisition differs")
    tree=checker._parse_xml(source,"source");doc=tree.getroot();counts=dict(sorted(Counter(n.tag for n in doc.iter()).items()))
    if len(list(doc.iter()))!=15955 or len(list(doc.find("ThML.body").iter()))!=15804:raise ValueError("complete source census differs")
    credits=[]
    for name,role,selector in (("Philip Schaff","author","/ThML/ThML.head/electronicEdInfo/DC/DC.Creator[@scheme='short-form']"),("whp","electronic transcriber as literally named","/ThML/ThML.head/electronicEdInfo/DC/DC.Contributor[@sub='Transcriber']"),("Wendy Huang","electronic markup contributor","/ThML/ThML.head/electronicEdInfo/DC/DC.Contributor[@sub='Markup']"),("Christian Classics Ethereal Library","electronic publisher","/ThML/ThML.head/electronicEdInfo/DC/DC.Publisher"),("Logos Research Systems, Inc.; The Electronic Bible Society","electronic-edition and collation statement, as retained","//*[@id='i-p9.1']")):
        selected=doc.xpath(selector)
        if len(selected)!=1:raise ValueError("nonunique credit "+selector)
        credits.append(dict(name=name,role=role,source_selector=selector,literal_text="".join(selected[0].itertext())))
    header=etree.Element(NS+"teiHeader");fd=etree.SubElement(header,NS+"fileDesc");ts=etree.SubElement(fd,NS+"titleStmt")
    etree.SubElement(ts,NS+"title").text=TITLE
    for credit in credits:
        resp=etree.SubElement(ts,NS+"respStmt");etree.SubElement(resp,NS+"resp").text=credit["role"];etree.SubElement(resp,NS+"name").text=credit["name"]
    pub=etree.SubElement(fd,NS+"publicationStmt");etree.SubElement(pub,NS+"p").text="Nonaccepted reconstruction candidate. The retained DC.Rights field is empty; provider permission and copyright statements are evidence. Human textual acceptance, print equivalence, rights clearance and public publication remain separate."
    notes=etree.SubElement(fd,NS+"notesStmt");etree.SubElement(notes,NS+"note",type="source-doctype").text=tree.docinfo.doctype or ""
    retained=etree.SubElement(notes,NS+"note",type="retained-ThML-header");holder=etree.SubElement(retained,NS+"p");base_tree=checker._parse_xml((ROOT/"reports/_logs/schaff-history-vol-4-reconciliation-20261001-v1/replayed-native-base.tei.xml").read_bytes(),"native base");holder.append(base_tree.getroot().find(NS+"teiHeader/"+NS+"fileDesc/"+NS+"notesStmt/"+NS+"note[@type='retained-ThML-header']/"+NS+"p/"+NS+"seg"))
    etree.SubElement(notes,NS+"note",type="source-edition-history").text=credits[-1]["literal_text"]
    sd=etree.SubElement(fd,NS+"sourceDesc");bibl=etree.SubElement(sd,NS+"bibl")
    etree.SubElement(bibl,NS+"title").text=doc.find("ThML.head/electronicEdInfo/DC/DC.Title").text
    etree.SubElement(bibl,NS+"publisher").text="Christian Classics Ethereal Library";etree.SubElement(bibl,NS+"ptr",target=acq["url"])
    etree.SubElement(bibl,NS+"note",type="work-scope").text=SCOPE
    etree.SubElement(bibl,NS+"note",type="retained-source").text="Retained raw/ccel/schaff/hcc4.xml, complete electronic volume IV. Existing readable native route is reused; its language ledger-only gap is repaired without other body/evidence changes. Historical escaped physical-line route remains byte-closure evidence only."
    encoding=etree.SubElement(header,NS+"encodingDesc");project=etree.SubElement(encoding,NS+"projectDesc")
    etree.SubElement(project,NS+"p").text="Native ThML mixed text is conserved. An xml:id-linked standOff source-projection list retains every ordered source attribute, parent and ordinal. Explicit source-order wrappers conserve sibling order while satisfying P5. Existing readable native structure and legacy ThML-unclear representation remain exact. Source lang becomes literal xml:lang; no corrections inferred."
    accounting=dict(contract="ocd-schaff-history-vol4-current-accountability-v1",work_id=WORK_ID,source_sha256=SOURCE_SHA,source_bytes=len(source),scope=SCOPE,source_tag_counts=counts,body_exclusions=[],source_elements=15955,body_elements=15804,source_body_roots=[dict(id=n.get("id"),title=n.get("title"),elements=sum(1 for _ in n.iter())) for n in doc.find("ThML.body")],prolog_comments=[dict(text=n.text,tail=n.tail) for n in checker._external_siblings(doc,before=True)],source_doctype=tree.docinfo.doctype,source_media=dict(image_element_count=0,retained_print_pixels="not established"),source_attribute_disposition="All ordered source attributes retained in private source-projection records; meaningful language, inline styles, notes, references, headings and division titles additionally mapped to native TEI. Source CSS and print/rights assertions retained without interpreting or correcting.",historical_package_disposition="Escaped line carrier route demonstrates byte closure only, not faithful native TEI/public output.")
    questions=[dict(id=WORK_ID+"-"+kind,status="unresolved",kind=kind,detail=detail) for kind,detail in (("human","No current human textual/visual acceptance."),("print","Literal edition-history retained; independent exact print equivalence not established."),("rights","Source DC.Rights is empty; CCEL permission is evidence, not independent rights clearance."),("publication","No public publication authorization/action."))]
    profile=dict(work_id=WORK_ID,source_sha256=SOURCE_SHA,scope=SCOPE,credits=credits,header_xml=etree.tostring(header,encoding="unicode"),accounting=accounting,questions=questions)
    put(BASE/"profile.json",canonical(profile));put(BASE/"validation-policy.json",canonical(dict(scope=SCOPE,rules=["independent complete native tree and exact source-projection evidence","full text/tail/parent/order and literal attributes","primary-credit bindings","P5; meaningful mutations; exact fresh-process replay"],source_tag_projection=checker._PROJECTION_NAMES,source_language="literal xml:lang",inline_style={"i":"italic or literal source class","unclear":"existing seg type ThML-unclear"})))
    notice="# History of the Christian Church, volume IV: source and data credit\n\nSourced via [CCEL.org](https://www.ccel.org/ccel/schaff/hcc4.html). Philip Schaff is the retained author; CCEL is the electronic publisher. The electronic header names `whp` as transcriber and Wendy Huang as markup contributor. Tim Perrine is credited only for the CCEL Staff Writer description. The title-page endnote credits Philip Schaff, History of the Christian Church (Oak Harbor, WA: Logos Research Systems, Inc.) 1997, followed by comparison, correction and emendation according to the 1910 edition of Charles Scribner's Sons by The Electronic Bible Society, Dallas, TX, 1998. These literal statements do not establish independent print collation.\n\nThe retained header records firstPublished1882 and electronic creation2002-11-27; its published print-edition field is empty. Its DC.Rights field is empty; no license is inferred from that absence. Its prolog states Copyright Christian Classics Ethereal Library. CCEL permission allows parsing ThML/XML for text, reserves its files/formatting rights, prohibits selling CCEL files or derivatives of their formatting, and requests publication credit. The maintained release carries this permission restriction visibly.\n\n"+SCOPE+"\n\nCarry visible credit to `"+DATA_NOTICE.as_posix()+"`. Human textual/visual acceptance, print equivalence, rights clearance and publication remain separate.\n"
    put(BASE/"README.source.md",notice.encode());put(DATA_NOTICE,notice.encode())
    authorities=[("primary-source",SOURCE,"primary-source"),("native-base","reports/_logs/schaff-history-vol-4-reconciliation-20261001-v1/replayed-native-base.tei.xml","replayed-existing-readable-route-not-recovered-historical-bytes"),("native-base-profile","sources/structured-text/schaff-history-vol-4-readable/schaff-history-vol-4.reconstruction-profile.json","readonly-readable-source-profile"),("native-base-producer","build/tei/schaff_history_vol_4_reconstruction.py","readonly-readable-producer"),("native-base-checker","build/tei/schaff_history_vol_4_oracle.py","readonly-independent-source-checker"),("profile",BASE/"profile.json","complete-source-feature-profile"),("validation-policy",BASE/"validation-policy.json","independent-validation-policy"),("source-readme",BASE/"README.source.md","source-attribution"),("canonical-acquisition",ACQUISITION,"retained-source-identity"),("ccel-permission","docs/sources/ccel-permission.md","source-permission-evidence"),("tei-p5-xsd","ocd_kernel/tei/vendor/xsd/tei_all.xsd","tei-validation-schema"),("candidate-package-schema","ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","candidate-package-schema")]
    manifest=dict(contract="ocd-source-manifest-v1",source_id="ccel-schaff-hcc4-complete-current-v1",work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=[binding(*a) for a in authorities],converter=dict(id=producer.CONVERTER_ID,version="1",callable="_convert",implementation_path="build/tei/schaff_history_vol4_current_reconstruction.py",implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),validator=dict(id=checker.ORACLE_ID,version="1",callable="_oracle",implementation_path="build/tei/schaff_history_vol4_current_oracle.py",implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",sha256=sha256((ROOT/"ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()).hexdigest()))
    put(BASE/"source-manifest.json",canonical(manifest));print(json.dumps(dict(status="prepared",source_elements=15955,body_elements=15804,body_roots=2,indexes=5)))

if __name__=="__main__":main()
