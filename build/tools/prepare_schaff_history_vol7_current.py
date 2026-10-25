"""Bind the complete retained HCC7 volume and literal source credits."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import schaff_history_vol7_current_reconstruction as producer, schaff_history_vol7_current_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT=Path(__file__).resolve().parents[2]
WORK_ID="schaff-history-vol-7"
FORM_ID=WORK_ID+"-retained-electronic"
EDITION_ID=WORK_ID+"-retained-electronic-witness"
ACQUISITION_ID=WORK_ID+"-retained-source"
WORK=Path("library/works")/WORK_ID
EDITION=WORK/"forms"/FORM_ID/"editions"/EDITION_ID
ACQUISITION=EDITION/"acquisitions"/(ACQUISITION_ID+".json")
BASE=Path("sources/ccel-schaff-hcc7-current")/WORK_ID
SOURCE=Path("raw/ccel/schaff/hcc7.xml")
SOURCE_SHA="f821de5c332e6febd4a16f32d18dda36a2c9083035c73e6a9975c431d683eacd"
TITLE="History of the Christian Church, Vol. 7: Modern Christianity -- The German Reformation"
SCOPE='Complete retained CCEL hcc7.xml volume VII: all three ordered body roots i Title Page, ii Modern Christianity. German Reformation. with its integral preface, nine explicitly typed chapters and 124 nested divisions, and iii Indexes with four integral divisions (Scripture, Greek, German and French; literal fourth index ID iv preserved). All 11,859 native source elements, 11,679 body elements, 1,012 notes, four source index carriers and 780 literal language annotations, including three on index carriers, are represented with exact mixed text, tails, parents, order, IDs and ordered attributes. The complete retained electronic header and two prolog comments, including inert stylesheet text and copyright, remain represented. This is the complete retained German Reformation volume and the first part of the source-described two-volume Reformation unit, not the Swiss Reformation volume VIII or an inferred narrative through 1648. No source-body exclusion, corrected reading, invented print completion or new chapter/volume identity; one existing work and one TEI. No image elements occur in this retained textual member. Its empty DC.Rights field is retained without inferring a license. Literal Second edition, revised and provider/Logos/Electronic Bible Society edition-history statements remain evidence, not independent print equivalence or rights clearance.'
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
    if len(list(doc.iter()))!=11859 or len(list(doc.find("ThML.body").iter()))!=11679:raise ValueError("complete source census differs")
    credits=[]
    for name,role,selector in (("Philip Schaff","author","/ThML/ThML.head/electronicEdInfo/DC/DC.Creator[@scheme='short-form']"),("whp","electronic transcriber as literally named","/ThML/ThML.head/electronicEdInfo/DC/DC.Contributor[@sub='Transcriber']"),("Wendy Huang","electronic markup contributor","/ThML/ThML.head/electronicEdInfo/DC/DC.Contributor[@sub='Markup']"),("Christian Classics Ethereal Library","electronic publisher","/ThML/ThML.head/electronicEdInfo/DC/DC.Publisher"),("Logos Research Systems, Inc.; The Electronic Bible Society","electronic-edition and collation statement, as retained","//*[@id='i-p25.1']")):
        selected=doc.xpath(selector)
        if len(selected)!=1:raise ValueError("nonunique credit "+selector)
        credits.append(dict(name=name,role=role,source_selector=selector,literal_text="".join(selected[0].itertext())))
    header=etree.Element(NS+"teiHeader");fd=etree.SubElement(header,NS+"fileDesc");ts=etree.SubElement(fd,NS+"titleStmt")
    etree.SubElement(ts,NS+"title").text=TITLE
    for credit in credits:
        resp=etree.SubElement(ts,NS+"respStmt");etree.SubElement(resp,NS+"resp").text=credit["role"];etree.SubElement(resp,NS+"name").text=credit["name"]
    pub=etree.SubElement(fd,NS+"publicationStmt");etree.SubElement(pub,NS+"p").text="Nonaccepted reconstruction candidate. The retained DC.Rights field is empty; provider permission and copyright statements are evidence. Human textual acceptance, print equivalence, rights clearance and public publication remain separate."
    notes=etree.SubElement(fd,NS+"notesStmt");etree.SubElement(notes,NS+"note",type="source-doctype").text=tree.docinfo.doctype or ""
    retained=etree.SubElement(notes,NS+"note",type="retained-ThML-header");etree.SubElement(retained,NS+"p")
    etree.SubElement(notes,NS+"note",type="source-edition-history").text=credits[-1]["literal_text"]
    sd=etree.SubElement(fd,NS+"sourceDesc");bibl=etree.SubElement(sd,NS+"bibl")
    etree.SubElement(bibl,NS+"title").text=doc.find("ThML.head/electronicEdInfo/DC/DC.Title").text
    etree.SubElement(bibl,NS+"publisher").text="Christian Classics Ethereal Library";etree.SubElement(bibl,NS+"ptr",target=acq["url"])
    etree.SubElement(bibl,NS+"note",type="work-scope").text=SCOPE
    etree.SubElement(bibl,NS+"note",type="retained-source").text="Retained raw/ccel/schaff/hcc7.xml, complete electronic volume VII. Historical escaped physical-line route is byte-closure evidence only; native reconstruction now preserves readable source structure."
    encoding=etree.SubElement(header,NS+"encodingDesc");project=etree.SubElement(encoding,NS+"projectDesc")
    etree.SubElement(project,NS+"p").text="Native ThML mixed text is conserved. An xml:id-linked standOff source-projection list retains every ordered source attribute, parent and ordinal. Explicit source-order wrappers conserve sibling order while satisfying P5. Source i/b become hi with literal source class or italic/bold, and source lang becomes literal xml:lang; no corrections inferred."
    literal=doc.xpath("//*[@id='ii.iii.xv-p23.1']")
    if len(literal)!=1 or list(literal[0].attrib.items())!=[("passage","Ep. 5:32"),("id","ii.iii.xv-p23.1")]:raise ValueError("opaque reference source preimage differs")
    opaque=dict(source_id="ii.iii.xv-p23.1",ordered_source_attributes=list(literal[0].attrib.items()),literal_text=literal[0].text,tei_tag="ref",tei_type="scripture-reference",tei_n="Ep. 5:32",tei_target=None,rationale="Retain the source's scripRef classification without parsing or correcting its opaque label. The exact passage is not a valid P5 URI target list; preserve it visibly as n plus exact ordered source evidence, without inventing a URI or resolved scripture reading.")
    etree.SubElement(project,NS+"p").text=opaque["rationale"]
    accounting=dict(contract="ocd-schaff-history-vol7-current-accountability-v1",work_id=WORK_ID,source_sha256=SOURCE_SHA,source_bytes=len(source),scope=SCOPE,source_tag_counts=counts,body_exclusions=[],source_elements=11859,body_elements=11679,source_body_roots=[dict(id=n.get("id"),title=n.get("title"),elements=sum(1 for _ in n.iter())) for n in doc.find("ThML.body")],prolog_comments=[dict(text=n.text,tail=n.tail) for n in checker._external_siblings(doc,before=True)],source_doctype=tree.docinfo.doctype,source_media=dict(image_element_count=0,retained_print_pixels="not established"),source_attribute_disposition="All ordered source attributes retained in private source-projection records; meaningful language, inline styles, notes, references, headings and division titles additionally mapped to native TEI. Source CSS and print/rights assertions retained without interpreting or correcting.",historical_package_disposition="Escaped line carrier route demonstrates byte closure only, not faithful native TEI/public output.")
    questions=[dict(id=WORK_ID+"-"+kind,status="unresolved",kind=kind,detail=detail) for kind,detail in (("human","No current human textual/visual acceptance."),("print","Literal edition-history retained; independent exact print equivalence not established."),("rights","Source DC.Rights is empty; CCEL permission is evidence, not independent rights clearance."),("publication","No public publication authorization/action."))]
    accounting["opaque_reference_disposition"]=opaque
    profile=dict(work_id=WORK_ID,source_sha256=SOURCE_SHA,scope=SCOPE,credits=credits,header_xml=etree.tostring(header,encoding="unicode"),accounting=accounting,questions=questions)
    put(BASE/"profile.json",canonical(profile));put(BASE/"validation-policy.json",canonical(dict(scope=SCOPE,rules=["independent complete native tree and exact source-projection evidence","full text/tail/parent/order and literal attributes","primary-credit bindings","P5; meaningful mutations; exact fresh-process replay"],source_tag_projection=checker._PROJECTION_NAMES,source_language="literal xml:lang",opaque_reference_exception=opaque,inline_style={"i":"italic or literal source class","b":"bold"})))
    notice="# History of the Christian Church, volume VII: source and data credit\n\nSourced via [CCEL.org](https://www.ccel.org/ccel/schaff/hcc7.html). Philip Schaff is the retained author; CCEL is the electronic publisher. The electronic header names `whp` as transcriber and Wendy Huang as markup contributor. Tim Perrine is credited only for the CCEL Staff Writer description. The title-page endnote credits Philip Schaff, History of the Christian Church (Oak Harbor, WA: Logos Research Systems, Inc.) 1997, followed by comparison and correction according to the 1910 edition of Charles Scribner's Sons, with emendations by The Electronic Bible Society, Dallas, TX, 1998. These literal statements do not establish independent print collation.\n\nThe retained header records firstPublished 1882, Second edition, revised, and electronic creation 2002-11-27. Its DC.Rights field is empty; no license is inferred from that absence. Its prolog states Copyright Christian Classics Ethereal Library. CCEL permission allows parsing ThML/XML for text, reserves its files/formatting rights, prohibits selling CCEL files or derivatives of their formatting, and requests publication credit. The maintained release carries this permission restriction visibly.\n\n"+SCOPE+"\n\nCarry visible credit to `"+DATA_NOTICE.as_posix()+"`. Human textual/visual acceptance, print equivalence, rights clearance and publication remain separate.\n"
    notice+="\nThe source's `scripRef` at `ii.iii.xv-p23.1` says exactly `Ep. 5:32`. Its opaque passage is retained as a literal reference label and in ordered source evidence, with no invented URI or parsed/corrected scripture-reading claim. All 780 source languages, including three index-carrier languages, remain literal.\n"
    put(BASE/"README.source.md",notice.encode());put(DATA_NOTICE,notice.encode())
    authorities=[("primary-source",SOURCE,"primary-source"),("profile",BASE/"profile.json","complete-source-feature-profile"),("validation-policy",BASE/"validation-policy.json","independent-validation-policy"),("source-readme",BASE/"README.source.md","source-attribution"),("canonical-acquisition",ACQUISITION,"retained-source-identity"),("ccel-permission","docs/sources/ccel-permission.md","source-permission-evidence"),("tei-p5-xsd","ocd_kernel/tei/vendor/xsd/tei_all.xsd","tei-validation-schema"),("candidate-package-schema","ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","candidate-package-schema"),("historical-line-profile","sources/structured-text/schaff-history-vol-7/schaff-history-vol-7.reconstruction-profile.json","historical-byte-closure-only"),("historical-line-manifest","sources/structured-text/schaff-history-vol-7/schaff-history-vol-7.source-manifest.json","historical-discovery-only"),("historical-line-producer","build/tei/schaff_history_vol7_reconstruction.py","historical-read-only-code"),("historical-line-oracle","build/tei/schaff_history_vol7_oracle.py","historical-read-only-code")]
    manifest=dict(contract="ocd-source-manifest-v1",source_id="ccel-schaff-hcc7-complete-current-v1",work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=[binding(*a) for a in authorities],converter=dict(id=producer.CONVERTER_ID,version="1",callable="_convert",implementation_path="build/tei/schaff_history_vol7_current_reconstruction.py",implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),validator=dict(id=checker.ORACLE_ID,version="1",callable="_oracle",implementation_path="build/tei/schaff_history_vol7_current_oracle.py",implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",sha256=sha256((ROOT/"ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()).hexdigest()))
    put(BASE/"source-manifest.json",canonical(manifest));print(json.dumps(dict(status="prepared",source_elements=11859,body_elements=11679,body_roots=3,indexes=4)))

if __name__=="__main__":main()
