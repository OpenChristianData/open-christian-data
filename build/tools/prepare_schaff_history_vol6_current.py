"""Bind complete native HCC6 source, exact source credits, and work-local reconstruction."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import schaff_history_vol6_current_reconstruction as producer, schaff_history_vol6_current_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
ROOT=Path(__file__).resolve().parents[2]
WORK_ID="schaff-history-vol-6"
FORM_ID=WORK_ID+"-retained-electronic"
EDITION_ID=WORK_ID+"-retained-electronic-witness"
ACQUISITION_ID=WORK_ID+"-retained-source"
WORK=Path("library/works")/WORK_ID
EDITION=WORK/"forms"/FORM_ID/"editions"/EDITION_ID
ACQUISITION=EDITION/"acquisitions"/(ACQUISITION_ID+".json")
BASE=Path("sources/ccel-schaff-hcc6-current")/WORK_ID
SOURCE=Path("raw/ccel/schaff/hcc6.xml")
SOURCE_SHA="7221658476b0847e10a58ac01eea5f3b5fbf884d5941d32d758be5ef1cdca4c5"
TITLE="History of the Christian Church, Vol. 6: The Middle Ages, A.D. 1294-1517"
SCOPE="Complete retained CCEL hcc6.xml volume VI: all four ordered body roots i Title Page, ii Preface, iii History of the Christian Church Volume VI with Introductory Survey and ten native chapters, and iv Indexes with all six native index divisions. All 7,754 native source elements, 7,654 body elements, 1,353 notes, six subject-index markers, one unclear carrier, 270 literal language annotations, 14 literal CSS declarations and all ordered source class attributes are conserved with exact mixed text, tails, native parents, order and IDs. Full retained source header and two inert prolog comments are represented. No body exclusion, silent reading correction, new work IDs or invented print completion; one existing volume identity and one TEI. No image elements occur in this retained textual member. Literal source edition-history, title/byline and copyright statements are source evidence, not independent print equivalence or rights clearance."

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
    for name,role,selector in (("David S. Schaff, D.D.","volume VI title-page byline","//*[@id='i-p0.12']"),("Philip Schaff","umbrella title-page and retained DC.Creator credit","/ThML/ThML.head/electronicEdInfo/DC/DC.Creator[@scheme='short-form']"),("whp","electronic transcriber as literally named","/ThML/ThML.head/electronicEdInfo/DC/DC.Contributor[@sub='Transcriber']"),("Wendy Huang","electronic markup contributor","/ThML/ThML.head/electronicEdInfo/DC/DC.Contributor[@sub='Markup']"),("Christian Classics Ethereal Library","electronic publisher","/ThML/ThML.head/electronicEdInfo/DC/DC.Publisher"),("The Electronic Bible Society","electronic collation statement, as retained","//*[@id='i-p0.4']")):
        selected=doc.xpath(selector)
        if len(selected)!=1:raise ValueError("nonunique credit "+selector)
        credits.append(dict(name=name,role=role,source_selector=selector,literal_text="".join(selected[0].itertext())))
    header=etree.Element(NS+"teiHeader");fd=etree.SubElement(header,NS+"fileDesc");ts=etree.SubElement(fd,NS+"titleStmt")
    etree.SubElement(ts,NS+"title").text=TITLE
    for c in credits:
        rs=etree.SubElement(ts,NS+"respStmt");etree.SubElement(rs,NS+"resp").text=c["role"];etree.SubElement(rs,NS+"name").text=c["name"]
    ps=etree.SubElement(fd,NS+"publicationStmt");etree.SubElement(ps,NS+"p").text="Nonaccepted reconstruction candidate. The blank retained DC.Rights field establishes no rights claim; CCEL formatting restrictions are evidence; human textual acceptance, print equivalence, rights clearance and public publication remain separate."
    ns=etree.SubElement(fd,NS+"notesStmt");etree.SubElement(ns,NS+"note",type="source-doctype").text=st.docinfo.doctype or ""
    retained=etree.SubElement(ns,NS+"note",type="retained-ThML-header");etree.SubElement(retained,NS+"p")
    etree.SubElement(ns,NS+"note",type="source-edition-history").text=credits[-1]["literal_text"]
    sd=etree.SubElement(fd,NS+"sourceDesc");b=etree.SubElement(sd,NS+"bibl")
    etree.SubElement(b,NS+"title").text=doc.find("ThML.head/electronicEdInfo/DC/DC.Title").text
    etree.SubElement(b,NS+"publisher").text="Christian Classics Ethereal Library";etree.SubElement(b,NS+"ptr",target=acq["url"])
    etree.SubElement(b,NS+"note",type="work-scope").text=SCOPE
    etree.SubElement(b,NS+"note",type="retained-source").text="Retained raw/ccel/schaff/hcc6.xml, complete electronic volume VI. Historical escaped physical-line package preserved as byte-closure history; replaced by native structural reconstruction, not accepted as readable TEI."
    ed=etree.SubElement(header,NS+"encodingDesc");pd=etree.SubElement(ed,NS+"projectDesc");etree.SubElement(pd,NS+"p").text="Native ThML mixed text is conserved. An xml:id-linked standOff source-projection list retains every ordered source attribute, parent and ordinal. Explicit source-order wrappers conserve sibling order while satisfying P5. Source i/b/sup become hi with italic/bold/superscript, unclear remains unclear, and source lang becomes literal xml:lang; no corrections inferred."
    counts=dict(sorted(Counter(n.tag for n in doc.iter()).items()))
    accounting=dict(contract="ocd-schaff-history-vol6-current-accountability-v1",work_id=WORK_ID,source_sha256=SOURCE_SHA,source_bytes=len(source),scope=SCOPE,source_tag_counts=counts,body_exclusions=[],source_elements=7754,body_elements=7654,source_body_roots=[dict(id=n.get("id"),title=n.get("title"),elements=sum(1 for _ in n.iter())) for n in doc.find("ThML.body")],prolog_comments=[dict(text=n.text,tail=n.tail) for n in checker._external_siblings(doc,before=True)],source_doctype=st.docinfo.doctype,source_media=dict(image_element_count=0,retained_print_pixels="not established"),source_attribute_disposition="All ordered attributes retained exactly in private source-projection records; meaningful source language, inline styles, notes, references, headings and division titles additionally mapped to native TEI. Source p/seg style remains exact TEI style alongside unchanged class rend. Source heading style is an opaque ana source-css: literal value alongside unchanged class rend; no CSS interpretation. The independent checker derives and checks both source values and heading parent/ordinal directly. Source CSS and historical print/rights assertions retained without interpreting or correcting.",historical_package_disposition="Prior escaped line carrier demonstrates byte closure only, not faithful native TEI/public output.")
    questions=[dict(id=WORK_ID+"-"+k,status="unresolved",kind=k,detail=v) for k,v in (("human","No current human textual/visual acceptance."),("print","Literal edition-history retained; independent exact print equivalence not established."),("rights","Retained DC.Rights and printed published fields are blank. CCEL permission evidence is not independent rights clearance."),("publication","No public publication authorization/action."))]
    profile=dict(work_id=WORK_ID,source_sha256=SOURCE_SHA,scope=SCOPE,credits=credits,header_xml=etree.tostring(header,encoding="unicode"),accounting=accounting,questions=questions)
    put(BASE/"profile.json",canonical(profile));put(BASE/"validation-policy.json",canonical(dict(scope=SCOPE,rules=["independent entire native tree and exact source-projection evidence","full text/tail/parent/order and literal attributes","primary-credit bindings","P5; meaningful mutations; exact fresh-process replay"],source_tag_projection=checker._PROJECTION_NAMES,source_language="literal xml:lang",inline_style={"i":"italic","unclear":"unclear"},literal_css_disposition={"heading":"class unchanged in rend; exact style value prefixed source-css: in ana", "paragraph_or_span":"class unchanged in rend; style exact in style", "interpretation":"none"})))
    notice="# History of the Christian Church, volume VI: source and data credit\n\nSourced via [CCEL.org](https://www.ccel.org/ccel/schaff/hcc6.html). The title page gives the umbrella History of the Christian Church byline PHILIP SCHAFF, also named in DC.Creator, then separately identifies VOLUME VI, THE MIDDLE AGES, From BONIFACE VIII., 1294 to the Protestant Reformation, 1517, by DAVID S. SCHAFF, D.D. Both literal credits are preserved with their source locations; Philip Schaff is not substituted for the volume-specific byline. CCEL is the electronic publisher; whp is named as transcriber and Wendy Huang as markup contributor. Tim Perrine is credited only for the CCEL Staff Writer description.\n\nThe opening note attributes comparison, correction and emendation according to the 1910 Charles Scribner's Sons edition to The Electronic Bible Society, Dallas, TX, 1998. Literal source wording is retained, including its punctuation; this is not an independent print-collation claim. The header records firstPublished1882 and electronic creation2002-11-27; the printed published and DC.Rights fields are blank. No public-domain claim is inferred from those blank fields. Two inert prolog comments retain stylesheet text and Copyright Christian Classics Ethereal Library.\n\nCCEL permission allows parsing ThML/XML for text, reserves its files/formatting rights, prohibits selling CCEL files or derivatives of their formatting, and requests publication credit. This maintained release carries the permission restriction visibly. These source statements are evidence, not independent worldwide rights clearance.\n\n"+SCOPE+"\n\nCarry visible credit to `"+DATA_NOTICE.as_posix()+"`. Human textual/visual acceptance, print equivalence, rights clearance and publication remain separate.\n"
    put(BASE/"README.source.md",notice.encode());put(DATA_NOTICE,notice.encode())
    authorities=[("primary-source",SOURCE,"primary-source"),("profile",BASE/"profile.json","complete-source-feature-profile"),("validation-policy",BASE/"validation-policy.json","independent-validation-policy"),("source-readme",BASE/"README.source.md","source-attribution"),("canonical-acquisition",ACQUISITION,"retained-source-identity"),("ccel-permission","docs/sources/ccel-permission.md","source-permission-evidence"),("tei-p5-xsd","ocd_kernel/tei/vendor/xsd/tei_all.xsd","tei-validation-schema"),("candidate-package-schema","ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","candidate-package-schema")]
    record=dict(contract="ocd-source-manifest-v1",source_id="ccel-schaff-hcc6-complete-current-v1",work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=[binding(*a) for a in authorities],converter=dict(id=producer.CONVERTER_ID,version="1",callable="_convert",implementation_path="build/tei/schaff_history_vol6_current_reconstruction.py",implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),validator=dict(id=checker.ORACLE_ID,version="1",callable="_oracle",implementation_path="build/tei/schaff_history_vol6_current_oracle.py",implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",sha256=sha256((ROOT/"ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()).hexdigest()))
    put(BASE/"source-manifest.json",canonical(record));print(json.dumps(dict(status="prepared",source_elements=7754,body_elements=7654,body_roots=4,indexes=6)))
if __name__=="__main__":main()
