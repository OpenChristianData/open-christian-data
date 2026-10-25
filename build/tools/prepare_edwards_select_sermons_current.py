"""Bind the complete retained Select Sermons collection to a work-local native reconstruction."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import edwards_select_sermons_current_reconstruction as producer, edwards_select_sermons_current_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.tei.install_accepted import _files

ROOT=Path(__file__).resolve().parents[2]
WORK_ID="edwards-select-sermons"
FORM_ID=WORK_ID+"-english"
EDITION_ID=WORK_ID+"-ccel-thml-electronic"
ACQUISITION_ID=WORK_ID+"-ccel-retained-xml"
WORK=Path("library/works")/WORK_ID
EDITION=WORK/"forms"/FORM_ID/"editions"/EDITION_ID
ACQUISITION=EDITION/"acquisitions"/(ACQUISITION_ID+".json")
BASE=Path("sources/ccel-edwards-select-sermons-current")/WORK_ID
SOURCE=Path("raw/ccel/edwards/sermons.xml")
SOURCE_SHA="28c99ca7cb837b2e7d04bb8781982ad826b888233fe0b60598c374e00305de80"
TITLE="Select Sermons"
DATA_NOTICE=Path("data/sermons")/WORK_ID/"README.md"
LOG=Path("reports/_logs/edwards-select-sermons-reconciliation-20261001-v1")
SCOPE="Complete retained CCEL Select Sermons electronic collection: all 21 ordered div1 roots, comprising own title/contents, 19 sermons and integral scripture indexes. All 3,618 source elements, 3,568 body elements, three notes, 14 ordered lists, 55 items, 20 literal empty scripCom markers, 628 scripRef carriers, 717 anchors/links, 17 audio-icon references, 12 separators, 103 body line breaks, six literal gkc language spans and every heading/text/tail/ordered attribute/parent/order are retained. Source title and index material remain with the existing whole collection; no per-sermon work IDs. Full electronic header and copyright prolog retained. Native labels and parsed/osisRef fields are source classifications, not verified biblical identification or parsed-reference correctness. Seventeen externally referenced mp3 icons and linked audio files have no retained pixel/audio payloads; exact references are preserved without acquisition or pixel/audio verification. Constituent sermon editorial omission notice remains literal; no missing print pages are invented. Collection printSourceInfo/DC.Source/DC.Rights are blank; electronic creation 2000-07-09 is not a collection print date. Individual Banner of Truth 1995, Worcester reprint and Macmillan 1904/Gardiner statements remain constituent-specific source claims, not a collection imprint/editor or independent print equivalence."
canonical=producer.canonical
NS="{http://www.tei-c.org/ns/1.0}"

def put(p,b):
    target=io_path(ROOT/p);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b)

def binding(name,p,role):
    raw=io_path(ROOT/p).read_bytes()
    return dict(name=name,path=Path(p).as_posix(),role=role,bytes=len(raw),sha256=sha256(raw).hexdigest())

def main():
    source=io_path(ROOT/SOURCE).read_bytes();acq=validate_acquisition(io_path(ROOT/ACQUISITION),root=ROOT)
    if sha256(source).hexdigest()!=SOURCE_SHA or acq["source_sha256"]!=SOURCE_SHA:raise ValueError("source/acquisition differs")
    tree=checker._parse_xml(source,"source");doc=tree.getroot();body=doc.find("ThML.body")
    credits=[]
    for name,role,selector in (
        ("Jonathan Edwards","collection author literally named on own title page","/ThML/ThML.body/div1[@id='i']/h2"),
        ("Jonathan Edwards","electronic author credit","/ThML/ThML.head/electronicEdInfo/DC/DC.Creator[@scheme='short-form']"),
        ("Christian Classics Ethereal Library","electronic publisher","/ThML/ThML.head/electronicEdInfo/DC/DC.Publisher"),
        ("Abby Zwart","CCEL Staff Writer description author only; not collection editor/transcriber","/ThML/ThML.head/generalInfo/description")):
        nodes=doc.xpath(selector)
        if len(nodes)!=1:raise ValueError("nonunique credit selector "+selector)
        literal="".join(nodes[0].itertext())
        if name not in " ".join(literal.split()) and name!="Christian Classics Ethereal Library":raise ValueError("literal credit absent "+name)
        credits.append(dict(name=name,role=role,source_selector=selector,literal_text=literal))
    header=etree.Element(NS+"teiHeader");fd=etree.SubElement(header,NS+"fileDesc");ts=etree.SubElement(fd,NS+"titleStmt")
    etree.SubElement(ts,NS+"title").text=TITLE
    for c in credits:
        rs=etree.SubElement(ts,NS+"respStmt");etree.SubElement(rs,NS+"resp").text=c["role"];etree.SubElement(rs,NS+"name").text=c["name"]
    ps=etree.SubElement(fd,NS+"publicationStmt");etree.SubElement(ps,NS+"p").text="Nonaccepted technical reconstruction candidate. Retained rights are blank; human textual review, print equivalence, rights clearance and public publication are separate."
    notes=etree.SubElement(fd,NS+"notesStmt");etree.SubElement(notes,NS+"note",type="source-doctype").text=tree.docinfo.doctype or ""
    retained=etree.SubElement(notes,NS+"note",type="retained-ThML-header");etree.SubElement(retained,NS+"p")
    etree.SubElement(notes,NS+"note",type="bibliographic-qualification").text="No collection print imprint, editor, transcriber or translator is supplied by this retained header. Electronic creation is 2000-07-09. Source gssm-p0.5 identifies that sermon with The Works of Jonathan Edwards, Volume Two, Banner of Truth Trust, Reprinted 1995, pp. 849-854; its outline contributor is unnamed. DivineTruth-p0.5 states Works (Worcester reprint), IV:1-15. Mansions-p42.1 literally names H. Horman Gardiner and Macmillan 1904 for Many Mansions only. No name spelling, delivery date or print claim is corrected or generalized."
    sd=etree.SubElement(fd,NS+"sourceDesc");bibl=etree.SubElement(sd,NS+"bibl")
    etree.SubElement(bibl,NS+"title").text=TITLE;etree.SubElement(bibl,NS+"publisher").text="Christian Classics Ethereal Library";etree.SubElement(bibl,NS+"ptr",target=acq["url"])
    etree.SubElement(bibl,NS+"note",type="work-scope").text=SCOPE
    etree.SubElement(bibl,NS+"note",type="retained-source").text="Complete retained raw/ccel/edwards/sermons.xml electronic witness. Historical 37c-143/LIB055 preflight had no native candidate. Bounded current inventory/declared physical evidence discovery found no associated TEI; generated JSON and empty historical witness registry are not reconstruction authority."
    encoding=etree.SubElement(header,NS+"encodingDesc");project=etree.SubElement(encoding,NS+"projectDesc");etree.SubElement(project,NS+"p").text="Source text/tails/order and all ordered attributes are retained. Native elements expose lists, notes, inline styles, literal language, link targets, audio-icon references and separators. Complete private source-projection ledger binds every source carrier. Source-reference classification does not establish biblical parsing correctness."
    accounting=dict(contract="ocd-edwards-select-sermons-current-accountability-v1",work_id=WORK_ID,source_sha256=SOURCE_SHA,source_bytes=len(source),scope=SCOPE,source_tag_counts=dict(sorted(Counter(n.tag for n in doc.iter()).items())),body_exclusions=[],source_elements=3618,body_elements=3568,source_body_roots=[dict(id=n.get("id"),title=n.get("title"),elements=sum(1 for _ in n.iter())) for n in body],prolog_comments=[dict(text=n.text,tail=n.tail) for n in checker._external_siblings(doc,before=True)],source_doctype=tree.docinfo.doctype,source_media=dict(image_element_count=17,retained_pixel_payloads=False,retained_audio_payloads=False,references=[dict(id=n.get("id"),attributes=list(n.attrib.items()),audio_parent_attributes=list(n.getparent().attrib.items())) for n in body.iter("img")]),source_attribute_disposition="Full ordered attributes, parent/ordinal/text/tails linked privately; meaningful language/styles/headings/notes/links/markers/media targets/separators mapped readably.",historical_package_disposition="No native package associated by current dated inventory or bounded declared homes; old ticket expressly lacked one, generated JSON is not TEI.")
    questions=[dict(id=WORK_ID+"-"+k,status="unresolved",kind=k,detail=v) for k,v in (("human","No current human textual/visual acceptance."),("print","Independent print equivalence not established; constituent credits do not define a collection edition."),("rights","DC.Rights blank; CCEL files/formatting restriction is permission evidence, not independent clearance."),("media","Only exact icon/audio references retained; no pixels/audio inspected."),("publication","No public publication authorization/action."))]
    profile=dict(work_id=WORK_ID,source_sha256=SOURCE_SHA,scope=SCOPE,credits=credits,header_xml=etree.tostring(header,encoding="unicode"),accounting=accounting,questions=questions)
    preflight=dict(status="genuine-native-gap",work_id=WORK_ID,source= dict(path=SOURCE.as_posix(),bytes=len(source),sha256=SOURCE_SHA),before=_files(ROOT/WORK),scope=SCOPE,source_roots=accounting["source_body_roots"],bounded_historical_discovery=dict(ticket="37c-143",owner="LIB055",old_report="plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-143.md",dated_inventory="reports/_logs/canonical-library-reconciliation-20261001-v2/inventory.json",associated_candidates=[],qualification="No global filesystem absence claim; bounded declared directories, exact report and current association inventory checked."),runtime={p:sha256(io_path(ROOT/p).read_bytes()).hexdigest() for p in ["schemas/v2/native-content.schema.json","ocd_kernel/projection/native_content.py","ocd_kernel/projection/native_content_check.py","ocd_kernel/projection/source_projection_evidence.py","ocd_kernel/projection/categories/native_documents.py","ocd_kernel/reconstruction/contract.py"]})
    put(LOG/"preflight.json",canonical(preflight));put(BASE/"profile.json",canonical(profile));put(BASE/"validation-policy.json",canonical(dict(scope=SCOPE,rules=["independent full native tree, all attributes/parent/order/text/tails","primary roles and constituent-only bibliographic labels","P5; meaningful source-feature mutations; fresh-process exact replay"],source_tag_projection=checker._PROJECTION_NAMES,source_language="literal gkc, no language correction",media="Exact graphic.url=source src, n=source alt and original a.href; no media payload acquisition",source_marker="20 scripCom become literal marker anchors with type/subtype/n; original passage/parsed/osisRef retained in source ledger; no semantic identification claim")))
    notice="""# Select Sermons: source and data credit

Sourced via [CCEL.org](https://www.ccel.org/ccel/edwards/sermons.html). Jonathan Edwards is named as author by this collection's own title page and electronic header. Christian Classics Ethereal Library is the electronic publisher, with Grand Rapids, MI literally named. Abby Zwart is credited as CCEL Staff Writer for the electronic description only. No collection editor, translator or transcriber is supplied by the retained header, and none is inferred. Electronic creation 2000-07-09 is not a print-publication date. Collection printSourceInfo, DC.Source and DC.Rights are blank.

Individual source notices remain local: God's Sovereignty in the Salvation of Men cites The Works of Jonathan Edwards, Volume Two, Banner of Truth Trust, Reprinted 1995, pp. 849-854, and an unnamed outline contributor. The divine-truth sermon cites Works (Worcester reprint), IV:1-15. Many Mansions cites Selected Sermons of Jonathan Edwards, edited with introduction and notes by literally `H. Horman Gardiner`, New York, Macmillan, 1904. The name is retained without correcting it. These are constituent-sermon source statements, not an independently verified collection imprint or a collection-wide editor. Delivery dates, funeral context and the source editorial notice omitting several pages remain literal; no print completion or equivalence is claimed.

The retained prolog states Copyright Christian Classics Ethereal Library. Blank DC.Rights does not establish Public Domain clearance. The retained CCEL permission allows parsing ThML/XML for text; CCEL reserves rights in its files and formatting, prohibits selling CCEL files or derivatives of their formatting, and appreciates publication attribution. No cover license or contributor from a different Edwards source is imported. This private preparation visibly carries the restrictions; technical evidence does not authorize publication.

All title/contents, nineteen sermons and integral indexes remain one collection. Notes and native source scripture classifications are preserved without claiming verified Bible parsing. Seventeen external MP3-icon references and linked audio targets are retained literally; no pixel/audio payload is retained, fetched or verified. The indexes' query/fragment links preserve their source targets and attachments without claiming a functioning CCEL website.

"""+SCOPE+"\n\nCarry visible credit to `"+DATA_NOTICE.as_posix()+"`. Human textual/visual acceptance, print equivalence, media payload review, rights clearance and public publication remain separate.\n"
    put(BASE/"README.source.md",notice.encode());put(DATA_NOTICE,notice.encode())
    authorities=[("primary-source",SOURCE,"primary-source"),("profile",BASE/"profile.json","complete-source-feature-profile"),("validation-policy",BASE/"validation-policy.json","independent-validation-policy"),("source-readme",BASE/"README.source.md","source-attribution"),("canonical-acquisition",ACQUISITION,"retained-source-identity"),("ccel-permission","docs/sources/ccel-permission.md","source-permission-evidence"),("tei-p5-xsd","ocd_kernel/tei/vendor/xsd/tei_all.xsd","tei-validation-schema"),("candidate-package-schema","ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","candidate-package-schema")]
    record=dict(contract="ocd-source-manifest-v1",source_id="ccel-edwards-select-sermons-complete-current-v1",work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=[binding(*a) for a in authorities],converter=dict(id=producer.CONVERTER_ID,version="1",callable="_convert",implementation_path="build/tei/edwards_select_sermons_current_reconstruction.py",implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),validator=dict(id=checker.ORACLE_ID,version="1",callable="_oracle",implementation_path="build/tei/edwards_select_sermons_current_oracle.py",implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",sha256=sha256((ROOT/"ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()).hexdigest()))
    put(BASE/"source-manifest.json",canonical(record));print(json.dumps(dict(status="prepared",source_elements=3618,body_elements=3568,body_roots=21,sermons=19)))

if __name__=="__main__":main()
