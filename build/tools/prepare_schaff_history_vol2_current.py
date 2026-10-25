"""Bind complete native HCC2 source, exact source credits, and work-local reconstruction."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import schaff_history_vol2_current_reconstruction as producer, schaff_history_vol2_current_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
ROOT=Path(__file__).resolve().parents[2]
WORK_ID="schaff-history-vol-2"
FORM_ID=WORK_ID+"-retained-electronic"
EDITION_ID=WORK_ID+"-retained-electronic-witness"
ACQUISITION_ID=WORK_ID+"-retained-source"
WORK=Path("library/works")/WORK_ID
EDITION=WORK/"forms"/FORM_ID/"editions"/EDITION_ID
ACQUISITION=EDITION/"acquisitions"/(ACQUISITION_ID+".json")
BASE=Path("sources/ccel-schaff-hcc2-current")/WORK_ID
SOURCE=Path("raw/ccel/schaff/hcc2.xml")
SOURCE_SHA="edcfba700eb5e33cd662ec801589184dd665885cceca96114d891467c0f85942"
TITLE="History of the Christian Church, Vol. 2: Ante-Nicene Christianity, A.D. 100-325"
SCOPE="Complete retained CCEL hcc2.xml volume II: all six ordered body roots i Title Page, ii Preface to the Third Edition Revised, iii Fifth Edition, iv Preface to the Second Edition, v Second Period: Ante-Nicene Christianity, and vi Indexes with all eight index divisions. All 26,948 native source elements, 26,741 body elements, 1,593 notes, 57 subject-index markers, five unclear carriers, seven bold and 42 superscript carriers are represented with exact mixed text, tails, source parents, order, IDs and ordered attributes. All 2,164 native language annotations are retained literally. Full retained electronic header and the one copyright prolog comment remain represented. No source-body exclusion, new work IDs, corrected reading or invented print completion; one existing volume identity and one TEI. No image elements occur in this retained textual member. Literal source edition-history and rights statements are evidence, not independent print equivalence or rights clearance."
DATA_NOTICE=Path("data/prose")/WORK_ID/"README.md"
canonical=producer.canonical
NS="{http://www.tei-c.org/ns/1.0}"
def put(p,b):
    io_path(ROOT/p).parent.mkdir(parents=True,exist_ok=True);io_path(ROOT/p).write_bytes(b)
def binding(name,p,role):
    b=io_path(ROOT/p).read_bytes();return dict(name=name,path=Path(p).as_posix(),role=role,bytes=len(b),sha256=sha256(b).hexdigest())
def main():
    source=io_path(ROOT/SOURCE).read_bytes();acq=validate_acquisition(io_path(ROOT/ACQUISITION),root=ROOT)
    if sha256(source).hexdigest()!=SOURCE_SHA or acq["source_sha256"]!=SOURCE_SHA:raise ValueError("source/acquisition differs")
    st=checker._parse_xml(source,"source");doc=st.getroot();credits=[]
    for name,role,selector in (("Philip Schaff","author","/ThML/ThML.head/electronicEdInfo/DC/DC.Creator[@scheme='short-form']"),("whp","electronic transcriber as literally named","/ThML/ThML.head/electronicEdInfo/DC/DC.Contributor[@sub='Transcriber']"),("Wendy Huang","electronic markup contributor","/ThML/ThML.head/electronicEdInfo/DC/DC.Contributor[@sub='Markup']"),("Christian Classics Ethereal Library","electronic publisher","/ThML/ThML.head/electronicEdInfo/DC/DC.Publisher"),("Logos Research Systems, Inc.; The Electronic Bible Society","electronic-edition and collation statement, as retained","//*[@id='i-p7.1']")):
        selected=doc.xpath(selector)
        if len(selected)!=1:raise ValueError("nonunique credit "+selector)
        credits.append(dict(name=name,role=role,source_selector=selector,literal_text="".join(selected[0].itertext())))
    header=etree.Element(NS+"teiHeader");fd=etree.SubElement(header,NS+"fileDesc");ts=etree.SubElement(fd,NS+"titleStmt")
    etree.SubElement(ts,NS+"title").text=TITLE
    for c in credits:
        rs=etree.SubElement(ts,NS+"respStmt");etree.SubElement(rs,NS+"resp").text=c["role"];etree.SubElement(rs,NS+"name").text=c["name"]
    ps=etree.SubElement(fd,NS+"publicationStmt");etree.SubElement(ps,NS+"p").text="Nonaccepted reconstruction candidate. Source Public Domain claim and CCEL formatting restrictions are evidence; human textual acceptance, print equivalence, rights clearance and public publication remain separate."
    ns=etree.SubElement(fd,NS+"notesStmt");etree.SubElement(ns,NS+"note",type="source-doctype").text=st.docinfo.doctype or ""
    retained=etree.SubElement(ns,NS+"note",type="retained-ThML-header");etree.SubElement(retained,NS+"p")
    etree.SubElement(ns,NS+"note",type="source-edition-history").text=credits[-1]["literal_text"]
    sd=etree.SubElement(fd,NS+"sourceDesc");b=etree.SubElement(sd,NS+"bibl")
    etree.SubElement(b,NS+"title").text=doc.find("ThML.head/electronicEdInfo/DC/DC.Title").text
    etree.SubElement(b,NS+"publisher").text="Christian Classics Ethereal Library";etree.SubElement(b,NS+"ptr",target=acq["url"])
    etree.SubElement(b,NS+"note",type="work-scope").text=SCOPE
    etree.SubElement(b,NS+"note",type="retained-source").text="Retained raw/ccel/schaff/hcc2.xml, complete electronic volume II. Historical escaped physical-line package preserved as byte-closure history; replaced by native structural reconstruction, not accepted as readable TEI."
    ed=etree.SubElement(header,NS+"encodingDesc");pd=etree.SubElement(ed,NS+"projectDesc");etree.SubElement(pd,NS+"p").text="Native ThML mixed text is conserved. An xml:id-linked standOff source-projection list retains every ordered source attribute, parent and ordinal. Explicit source-order wrappers conserve sibling order while satisfying P5. Source i/b/sup become hi with italic/bold/superscript, unclear remains unclear, and source lang becomes literal xml:lang; no corrections inferred."
    counts=dict(sorted(Counter(n.tag for n in doc.iter()).items()))
    accounting=dict(contract="ocd-schaff-history-vol2-current-accountability-v1",work_id=WORK_ID,source_sha256=SOURCE_SHA,source_bytes=len(source),scope=SCOPE,source_tag_counts=counts,body_exclusions=[],source_elements=26948,body_elements=26741,source_body_roots=[dict(id=n.get("id"),title=n.get("title"),elements=sum(1 for _ in n.iter())) for n in doc.find("ThML.body")],prolog_comments=[dict(text=n.text,tail=n.tail) for n in checker._external_siblings(doc,before=True)],source_doctype=st.docinfo.doctype,source_media=dict(image_element_count=0,retained_print_pixels="not established"),source_attribute_disposition="All ordered attributes retained exactly in private source-projection records; meaningful source language, inline styles, notes, references, headings and division titles additionally mapped to native TEI. Source CSS and historical print/rights assertions retained without interpreting or correcting.",historical_package_disposition="Prior escaped line carrier demonstrates byte closure only, not faithful native TEI/public output.")
    questions=[dict(id=WORK_ID+"-"+k,status="unresolved",kind=k,detail=v) for k,v in (("human","No current human textual/visual acceptance."),("print","Literal edition-history retained; independent exact print equivalence not established."),("rights","Source Public Domain and CCEL permission are evidence, not independent rights clearance."),("publication","No public publication authorization/action."))]
    profile=dict(work_id=WORK_ID,source_sha256=SOURCE_SHA,scope=SCOPE,credits=credits,header_xml=etree.tostring(header,encoding="unicode"),accounting=accounting,questions=questions)
    put(BASE/"profile.json",canonical(profile));put(BASE/"validation-policy.json",canonical(dict(scope=SCOPE,rules=["independent entire native tree and exact source-projection evidence","full text/tail/parent/order and literal attributes","primary-credit bindings","P5; meaningful mutations; exact fresh-process replay"],source_tag_projection=checker._PROJECTION_NAMES,source_language="literal xml:lang",inline_style={"i":"italic","b":"bold","sup":"superscript","unclear":"unclear"})))
    notice="# History of the Christian Church, volume II: source and data credit\n\nSourced via [CCEL.org](https://www.ccel.org/ccel/schaff/hcc2.html). Philip Schaff is the retained author; CCEL is the electronic publisher. The electronic header names `whp` as transcriber and Wendy Huang as markup contributor. Tim Perrine is credited only for the CCEL Staff Writer description. The opening endnote credits Philip Schaff, History of the Christian Church (Oak Harbor, WA: Logos Research Systems, Inc.) 1997, followed by The Electronic Bible Society, Dallas, TX, 1998, for comparison, correction and emendation according to the 1910 Charles Scribner's Sons edition. These literal statements do not establish independent print collation.\n\nThe retained header states firstPublished1882, Third edition, revised, electronic creation2002-11-27 and Public Domain. Its prolog states Copyright Christian Classics Ethereal Library. These are retained source claims, not an independent worldwide rights decision. CCEL permission allows parsing ThML/XML for text, reserves its files/formatting rights, prohibits selling CCEL files or derivatives of their formatting, and requests publication credit. The maintained release carries this permission restriction visibly.\n\n"+SCOPE+"\n\nCarry visible credit to `"+DATA_NOTICE.as_posix()+"`. Human textual/visual acceptance, print equivalence, rights clearance and publication remain separate.\n"
    put(BASE/"README.source.md",notice.encode());put(DATA_NOTICE,notice.encode())
    authorities=[("primary-source",SOURCE,"primary-source"),("profile",BASE/"profile.json","complete-source-feature-profile"),("validation-policy",BASE/"validation-policy.json","independent-validation-policy"),("source-readme",BASE/"README.source.md","source-attribution"),("canonical-acquisition",ACQUISITION,"retained-source-identity"),("ccel-permission","docs/sources/ccel-permission.md","source-permission-evidence"),("tei-p5-xsd","ocd_kernel/tei/vendor/xsd/tei_all.xsd","tei-validation-schema"),("candidate-package-schema","ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","candidate-package-schema")]
    record=dict(contract="ocd-source-manifest-v1",source_id="ccel-schaff-hcc2-complete-current-v1",work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=[binding(*a) for a in authorities],converter=dict(id=producer.CONVERTER_ID,version="1",callable="_convert",implementation_path="build/tei/schaff_history_vol2_current_reconstruction.py",implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),validator=dict(id=checker.ORACLE_ID,version="1",callable="_oracle",implementation_path="build/tei/schaff_history_vol2_current_oracle.py",implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",sha256=sha256((ROOT/"ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()).hexdigest()))
    put(BASE/"source-manifest.json",canonical(record));print(json.dumps(dict(status="prepared",source_elements=26948,body_elements=26741,body_roots=6,indexes=8)))
if __name__=="__main__":main()
