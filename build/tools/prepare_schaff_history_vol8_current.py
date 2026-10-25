"""Bind complete native HCC8 source, exact source credits, and work-local reconstruction."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import schaff_history_vol8_current_reconstruction as producer, schaff_history_vol8_current_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
ROOT=Path(__file__).resolve().parents[2]
WORK_ID="schaff-history-vol-8"
FORM_ID=WORK_ID+"-retained-electronic"
EDITION_ID=WORK_ID+"-retained-electronic-witness"
ACQUISITION_ID=WORK_ID+"-retained-source"
WORK=Path("library/works")/WORK_ID
EDITION=WORK/"forms"/FORM_ID/"editions"/EDITION_ID
ACQUISITION=EDITION/"acquisitions"/(ACQUISITION_ID+".json")
BASE=Path("sources/ccel-schaff-hcc8-current-v2")/WORK_ID
SOURCE=Path("raw/ccel/schaff/hcc8.xml")
SOURCE_SHA="95f835fe5d69bf1f1f94303cb4cc6a4487f4ae3b45e60c41f7a522db095d07ec"
TITLE="History of the Christian Church, Vol. 8: Modern Christianity -- The Swiss Reformation"
SCOPE="Complete retained CCEL hcc8.xml volume VIII: six ordered roots i Title Page, ii own Preface, iii signed Postscript, iv Modern Christianity/The Swiss Reformation with nineteen Chapters and 176 div3 subdivisions, v Appendix, and vi all five Indexes. All 14,607 native source elements and 14,446 body elements, 1,315 notes, two literal unclear Greek readings, forty verse groups/244 lines and 718 source language annotations are represented with exact mixed text/tails, source hierarchy/order/IDs and ordered attributes. Full electronic header and copyright prolog retained. Title-page relationship to volume VII as the first part and volume VIII as the second part of History of the Reformation is source context, not a merger or a new identity. Published authorial qualifications in the Postscript about chapters XVII/XVIII, Jackson's aid on Beza and the appendix literature are retained without inventing missing book text. No body exclusions, new work IDs, corrected readings, media acquisition or print completion. Exactly one source passage label at iv.xiv.iv-p29.2 becomes an opaque ref type/n annotation without target URI; literal John 6:37, 44, 65; 10:28; 15:16; l7:12; 18:9 and ordered original attributes are preserved without correcting lowercase l. No source image elements or direction attributes occur. Source scripRef classification does not establish verified biblical identification/parsed-reference correctness. Literal Third edition revised/1910 electronic collation claims and dated 1892 preface/postscript remain qualified source statements, not independent print equivalence or rights clearance; DC.Rights is blank."
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
    for name,role,selector in (("Philip Schaff","volume author literally named on own title page","//*[@id='i-p32']"),("Philip Schaff","literal inherited electronic DC author","/ThML/ThML.head/electronicEdInfo/DC/DC.Creator[@scheme='short-form']"),("Philip Schaff","own Postscript signer","//*[@id='iii-p6.1']"),("Samuel Macauley Jackson","aid on the last chapter about Beza acknowledged in the Postscript","//*[@id='iii-p4']"),("Georg von Wyss; Fréderic Godet","proof-sheet revisers explicitly acknowledged in the preface","//*[@id='ii-p17']"),("whp","electronic transcriber as literally named","/ThML/ThML.head/electronicEdInfo/DC/DC.Contributor[@sub='Transcriber']"),("Wendy Huang","electronic markup contributor","/ThML/ThML.head/electronicEdInfo/DC/DC.Contributor[@sub='Markup']"),("Christian Classics Ethereal Library","electronic publisher","/ThML/ThML.head/electronicEdInfo/DC/DC.Publisher"),("Logos Research Systems, Inc.; The Electronic Bible Society","electronic edition/collation statement as retained","//*[@id='i-p26.1']")):
        selected=doc.xpath(selector)
        if len(selected)!=1:raise ValueError("nonunique credit "+selector)
        credits.append(dict(name=name,role=role,source_selector=selector,literal_text="".join(selected[0].itertext())))
    header=etree.Element(NS+"teiHeader");fd=etree.SubElement(header,NS+"fileDesc");ts=etree.SubElement(fd,NS+"titleStmt")
    etree.SubElement(ts,NS+"title").text=TITLE
    for c in credits:
        rs=etree.SubElement(ts,NS+"respStmt");etree.SubElement(rs,NS+"resp").text=c["role"];etree.SubElement(rs,NS+"name").text=c["name"]
    ps=etree.SubElement(fd,NS+"publicationStmt");etree.SubElement(ps,NS+"p").text="Nonaccepted reconstruction candidate. Blank source rights field and CCEL formatting restrictions are evidence; human textual acceptance, print equivalence, rights clearance and public publication remain separate."
    ns=etree.SubElement(fd,NS+"notesStmt");etree.SubElement(ns,NS+"note",type="source-doctype").text=st.docinfo.doctype or ""
    retained=etree.SubElement(ns,NS+"note",type="retained-ThML-header");etree.SubElement(retained,NS+"p")
    etree.SubElement(ns,NS+"note",type="source-edition-history").text=credits[-1]["literal_text"]
    sd=etree.SubElement(fd,NS+"sourceDesc");b=etree.SubElement(sd,NS+"bibl")
    etree.SubElement(b,NS+"title").text=doc.find("ThML.head/electronicEdInfo/DC/DC.Title").text
    etree.SubElement(b,NS+"publisher").text="Christian Classics Ethereal Library";etree.SubElement(b,NS+"ptr",target=acq["url"])
    etree.SubElement(b,NS+"note",type="work-scope").text=SCOPE
    etree.SubElement(b,NS+"note",type="retained-source").text="Retained raw/ccel/schaff/hcc8.xml, complete electronic volume VIII. Historical escaped physical-line package preserved as byte-closure history; replaced by native structural reconstruction, not accepted as readable TEI."
    ed=etree.SubElement(header,NS+"encodingDesc");pd=etree.SubElement(ed,NS+"projectDesc");etree.SubElement(pd,NS+"p").text="Native ThML mixed text is conserved. An xml:id-linked standOff source-projection list retains every ordered source attribute, parent and ordinal. Explicit source-order wrappers conserve sibling order while satisfying P5. Source i/b/sup become hi with italic/bold/superscript, unclear remains unclear, and source lang becomes literal xml:lang; no corrections inferred."
    counts=dict(sorted(Counter(n.tag for n in doc.iter()).items()))
    accounting=dict(contract="ocd-schaff-history-vol8-current-accountability-v1",work_id=WORK_ID,source_sha256=SOURCE_SHA,source_bytes=len(source),scope=SCOPE,source_tag_counts=counts,body_exclusions=[],source_elements=14607,body_elements=14446,source_body_roots=[dict(id=n.get("id"),title=n.get("title"),elements=sum(1 for _ in n.iter())) for n in doc.find("ThML.body")],prolog_comments=[dict(text=n.text,tail=n.tail) for n in checker._external_siblings(doc,before=True)],source_doctype=st.docinfo.doctype,source_media=dict(image_element_count=0,retained_print_pixels="not established"),source_attribute_disposition="All ordered attributes retained exactly in private source-projection records; meaningful source language, inline styles, notes, references, headings and division titles additionally mapped to native TEI. Source CSS and historical print/rights assertions retained without interpreting or correcting.",historical_package_disposition="Prior escaped line carrier demonstrates byte closure only, not faithful native TEI/public output.")
    questions=[dict(id=WORK_ID+"-"+k,status="unresolved",kind=k,detail=v) for k,v in (("human","No current human textual/visual acceptance."),("print","Literal edition-history retained; independent exact print equivalence not established."),("rights","Source DC.Rights blank; copyright prolog and CCEL permission are evidence, not independent rights clearance."),("publication","No public publication authorization/action."))]
    profile=dict(work_id=WORK_ID,source_sha256=SOURCE_SHA,scope=SCOPE,credits=credits,header_xml=etree.tostring(header,encoding="unicode"),accounting=accounting,questions=questions)
    checker.verify_credits(doc, credits, header)
    put(BASE/"profile.json",canonical(profile));put(BASE/"validation-policy.json",canonical(dict(scope=SCOPE,rules=["independent entire native tree and exact source-projection evidence","full text/tail/parent/order and literal attributes","primary-credit bindings","P5; meaningful mutations; exact fresh-process replay"],source_tag_projection=checker._PROJECTION_NAMES,source_language="literal xml:lang",opaque_reference_exceptions={key:{"attributes":[["passage",value],["id",key]],"tei_type":"ThML-scripRef-opaque","tei_n":value,"target":"absent"} for key,value in checker.OPAQUE_REFERENCES.items()},inline_style={"i":"italic","b":"bold","sup":"superscript","unclear":"unclear"})))
    notice="""# History of the Christian Church, volume VIII: source and data credit

Sourced via [CCEL.org](https://www.ccel.org/ccel/schaff/hcc8.html). Philip Schaff is this volume's author, confirmed by its own title page, DC header and signed Postscript. The Postscript explicitly credits Rev. Samuel Macauley Jackson for aid on the last chapter, about Beza. The preface acknowledges Georg von Wyss and Fréderic Godet for revising proof sheets, along with its library acknowledgments. No translator of this volume is inferred from the preface's discussion of translations of other volumes or quoted authorities.

The electronic publisher is Christian Classics Ethereal Library; the retained header names `whp` as transcriber, Wendy Huang for markup and The Electronic Bible Society for the electronic edition. Tim Perrine is credited only for the CCEL Staff Writer description. Electronic creation is literally 2002-11-27. The own title-page note credits Philip Schaff, History of the Christian Church (Oak Harbor, WA: Logos Research Systems, Inc.) 1997 and comparison, correction and emendation according to the 1910 Charles Scribner's Sons edition by Electronic Bible Society, Dallas, TX, 1998. Title-page i-p49 and printSourceInfo state Third edition, revised. The own preface is dated June 1892; the signed Postscript is dated October 12, 1892. These separate retained source statements do not establish independent print collation or a factual print-date range 1882-1910; firstPublished 1882 remains inherited electronic/series metadata.

The retained DC.Rights field is empty; the prolog states Copyright Christian Classics Ethereal Library. No Public Domain claim, cover license or rights clearance is imported from another volume. CCEL permission allows parsing ThML/XML for text, reserves its files/formatting rights, prohibits selling CCEL files or derivatives of their formatting, and requests publication credit. This private preparation visibly carries that restriction; technical evidence does not authorize publication.

"""+SCOPE+"\n\nCarry visible credit to `"+DATA_NOTICE.as_posix()+"`. Human textual/visual acceptance, print equivalence, rights clearance and publication remain separate.\n"
    checker.verify_notice(credits, notice)
    put(BASE/"README.source.md",notice.encode());put(DATA_NOTICE,notice.encode())
    authorities=[("primary-source",SOURCE,"primary-source"),("profile",BASE/"profile.json","complete-source-feature-profile"),("validation-policy",BASE/"validation-policy.json","independent-validation-policy"),("source-readme",BASE/"README.source.md","source-attribution"),("canonical-acquisition",ACQUISITION,"retained-source-identity"),("ccel-permission","docs/sources/ccel-permission.md","source-permission-evidence"),("tei-p5-xsd","ocd_kernel/tei/vendor/xsd/tei_all.xsd","tei-validation-schema"),("candidate-package-schema","ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","candidate-package-schema")]
    record=dict(contract="ocd-source-manifest-v1",source_id="ccel-schaff-hcc8-complete-current-v1",work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=[binding(*a) for a in authorities],converter=dict(id=producer.CONVERTER_ID,version="1",callable="_convert",implementation_path="build/tei/schaff_history_vol8_current_reconstruction.py",implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),validator=dict(id=checker.ORACLE_ID,version="1",callable="_oracle",implementation_path="build/tei/schaff_history_vol8_current_oracle.py",implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",sha256=sha256((ROOT/"ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()).hexdigest()))
    put(BASE/"source-manifest.json",canonical(record));print(json.dumps(dict(status="prepared",source_elements=14607,body_elements=14446,body_roots=6,indexes=5)))
if __name__=="__main__":main()
