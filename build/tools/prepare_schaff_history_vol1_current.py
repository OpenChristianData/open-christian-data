"""Prepare a whole-volume current HCC1 package while retaining complete historical content."""
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import schaff_history_vol1_current_reconstruction as producer, schaff_history_vol1_current_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
ROOT=Path(__file__).resolve().parents[2]
WORK_ID="schaff-history-vol-1"
FORM_ID=WORK_ID+"-retained-electronic"
EDITION_ID=WORK_ID+"-retained-electronic-witness"
ACQUISITION_ID=WORK_ID+"-retained-source"
WORK=Path("library/works")/WORK_ID
EDITION=WORK/"forms"/FORM_ID/"editions"/EDITION_ID
ACQUISITION=EDITION/"acquisitions"/(ACQUISITION_ID+".json")
BASE=Path("sources/ccel-schaff-hcc1-current")/WORK_ID
SOURCE=Path("raw/ccel/schaff/hcc1.xml")
SOURCE_SHA="0a2a7cc56e2d00c791eeaacd5516a292a855426c3a8ceb8d5eeef6eeb49e3d09"
HISTORICAL=Path("reports/_logs/schaff-history-vol-1-reconciliation-20261001-v1/historical-package/content.tei.xml")
TITLE="History of the Christian Church, Vol. 1: Apostolic Christianity, A.D. 1-100"
SCOPE="Complete retained CCEL hcc1.xml volume I: all source body roots i (Apostolic Christianity) and ii (Indexes), opening title/context, three prefaces, Contents, Addenda, twelve chapters and all eight integral indexes. All 30,285 native source elements, 30,098 body elements, 1,272 notes, 40 subject-index markers, literal headings and complete mixed text/order/parents/ordered attributes are conserved. The full retained source header, three prolog comments and xml:id-linked standOff source-projection evidence remain represented. No body exclusion or invented print completion; one existing volume identity and one TEI. No image elements occur in this retained textual member; its Google Books page-image pointer does not establish retained or inspected print pixels. Literal edition-history statements are preserved as witness evidence, not independent print equivalence or worldwide rights clearance."
DATA_NOTICE=Path("data/prose")/WORK_ID/"README.md"
canonical=producer.canonical
NS="{http://www.tei-c.org/ns/1.0}"
def put(p,b):
    io_path(ROOT/p).parent.mkdir(parents=True,exist_ok=True);io_path(ROOT/p).write_bytes(b)
def binding(name,p,role):
    b=io_path(ROOT/p).read_bytes();return dict(name=name,path=Path(p).as_posix(),role=role,bytes=len(b),sha256=sha256(b).hexdigest())
def main():
    source=(ROOT/SOURCE).read_bytes();acq=validate_acquisition(io_path(ROOT/ACQUISITION),root=ROOT)
    if sha256(source).hexdigest()!=SOURCE_SHA or acq["source_sha256"]!=SOURCE_SHA:raise ValueError("source/acquisition differs")
    doc=checker.legacy._parse_xml(source,"source").getroot()
    old=checker.legacy._parse_xml((ROOT/HISTORICAL).read_bytes(),"historical");header=old.getroot().find(NS+"teiHeader")
    credits=[]
    for name,role,selector in (("Philip Schaff","author","/ThML/ThML.head/electronicEdInfo/DC/DC.Creator[@scheme='short-form']"),("Wendy Huang","electronic markup contributor","/ThML/ThML.head/electronicEdInfo/DC/DC.Contributor[@sub='Markup']"),("Christian Classics Ethereal Library","electronic publisher","/ThML/ThML.head/electronicEdInfo/DC/DC.Publisher"),("Logos Research Systems, Inc.; The Electronic Bible Society","electronic-edition and collation statement, as retained","//*[@id='i-p7.1']")):
        credits.append(dict(name=name,role=role,source_selector=selector,literal_text="".join(doc.xpath(selector)[0].itertext())))
    title_stmt=header.find(NS+"fileDesc/"+NS+"titleStmt")
    for c in credits:
        resp=etree.SubElement(title_stmt,NS+"respStmt");etree.SubElement(resp,NS+"resp").text=c["role"];etree.SubElement(resp,NS+"name").text=c["name"]
    source_desc=header.find(NS+"fileDesc/"+NS+"sourceDesc")
    prior_descriptions=[n.text for n in source_desc]
    for n in list(source_desc):source_desc.remove(n)
    bibliography=etree.SubElement(source_desc,NS+"bibl")
    etree.SubElement(bibliography,NS+"title").text=doc.find("ThML.head/electronicEdInfo/DC/DC.Title").text
    etree.SubElement(bibliography,NS+"publisher").text="Christian Classics Ethereal Library"
    etree.SubElement(bibliography,NS+"ptr",target=acq["url"])
    for value in prior_descriptions:etree.SubElement(bibliography,NS+"note",type="historical-source-description").text=value
    etree.SubElement(bibliography,NS+"note",type="work-scope").text=SCOPE
    notes=header.find(NS+"fileDesc/"+NS+"notesStmt")
    etree.SubElement(notes,NS+"note",type="source-edition-history").text=credits[3]["literal_text"]
    old_account=json.loads((ROOT/HISTORICAL.parent/"source-accountability.json").read_bytes())
    accounting=dict(contract="ocd-schaff-history-vol1-current-accountability-v1",work_id=WORK_ID,source_sha256=SOURCE_SHA,source_bytes=len(source),scope=SCOPE,body_exclusions=[],native_source_accountability=old_account,source_media=dict(image_element_count=0,page_image_pointer="http://google.com/books?id=NV8sAAAAYAAJ",retained_print_pixels="not established",pixel_presentation="not claimed"),historical_text_and_standoff_sha256=sha256((ROOT/HISTORICAL).read_bytes().split(b"</teiHeader>",1)[1]).hexdigest())
    questions=[dict(id=WORK_ID+"-"+k,status="unresolved",kind=k,detail=v) for k,v in (("human","No current human textual/visual acceptance."),("print","Source firstPublished1882/Revised edition and Logos1997/EBS1998 collation-against1910 statements retained; independent exact print equivalence not established."),("rights","Source Public Domain and CCEL permission are evidence, not independent rights clearance."),("publication","No public publication authorization/action."),("images","Source prolog Google Books page-image pointer retained; no retained or inspected print image bytes established."))]
    profile=dict(work_id=WORK_ID,source_sha256=SOURCE_SHA,scope=SCOPE,credits=credits,header_xml=etree.tostring(header,encoding="unicode"),accounting=accounting,questions=questions,historical_reuse="Historical 37c-272 whole candidate replays byte for byte. Fresh one-work bindings/header renew technical evidence; no new body mapping or spelling normalization.")
    put(BASE/"profile.json",canonical(profile));put(BASE/"validation-policy.json",canonical(dict(scope=SCOPE,rules=["full independent native tree and exact source-projection evidence","whole historical body and standOff byte conservation","primary-credit bindings","P5 and meaningful mutations/replay"],historical_policy="sources/structured-text/schaff-history-vol-1/schaff-history-vol-1.validation-policy.json")))
    notice="# History of the Christian Church, volume I: source and data credit\n\nSourced via [CCEL.org](https://www.ccel.org/ccel/schaff/hcc1.html). The retained electronic header names Philip Schaff as author, CCEL as publisher and Wendy Huang as markup contributor; its descriptive introduction credits Tim Perrine, CCEL Staff Writer. Its literal opening endnote credits Philip Schaff, History of the Christian Church (Oak Harbor, WA: Logos Research Systems, Inc.) 1997, followed by The Electronic Bible Society, Dallas, TX, 1998, for comparison, correction and emendation according to the 1910 Charles Scribner's Sons edition. Those source statements are preserved without correcting their literal reading, and do not establish independent print collation.\n\nThe retained header states firstPublished1882, Revised edition, created2002-11-26 and Public Domain; the prolog credits Copyright Christian Classics Ethereal Library. These source claims are evidence, not a worldwide rights decision. Retained CCEL permission permits parsing ThML/XML for text, reserves CCEL file/formatting rights, restricts selling CCEL files or derivatives of their formatting, and requests credit when publishing. See the retained project permission evidence.\n\n"+SCOPE+"\n\nCarry visible credit to `"+DATA_NOTICE.as_posix()+"`. Human textual/visual acceptance, print equivalence, rights clearance and publication remain separate.\n"
    put(BASE/"README.source.md",notice.encode());put(DATA_NOTICE,notice.encode())
    authorities=[("primary-source",SOURCE,"primary-source"),("profile",BASE/"profile.json","complete-source-feature-profile"),("validation-policy",BASE/"validation-policy.json","independent-validation-policy"),("source-readme",BASE/"README.source.md","source-attribution"),("historical-tei",HISTORICAL,"source-checked-complete-historical-TEI"),("historical-accounting",HISTORICAL.parent/"source-accountability.json","historical-source-accounting"),("historical-profile","sources/structured-text/schaff-history-vol-1/schaff-history-vol-1.reconstruction-profile.json","readonly-source-projection-profile"),("historical-policy","sources/structured-text/schaff-history-vol-1/schaff-history-vol-1.validation-policy.json","readonly-mapping-policy"),("historical-source-review","reports/_logs/schaff-history-vol-1-reconciliation-20261001-v1/historical-source-review.json","historical-current-native-check"),("legacy-producer","build/tei/schaff_history_vol_1_reconstruction.py","readonly-producer"),("legacy-checker","build/tei/schaff_history_vol_1_oracle.py","readonly-independent-checker"),("canonical-acquisition",ACQUISITION,"retained-source-identity"),("ccel-permission","docs/sources/ccel-permission.md","source-permission-evidence"),("tei-p5-xsd","ocd_kernel/tei/vendor/xsd/tei_all.xsd","tei-validation-schema"),("candidate-package-schema","ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","candidate-package-schema")]
    record=dict(contract="ocd-source-manifest-v1",source_id="ccel-schaff-hcc1-complete-current-v1",work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=[binding(*a) for a in authorities],converter=dict(id=producer.CONVERTER_ID,version="1",callable="_convert",implementation_path="build/tei/schaff_history_vol1_current_reconstruction.py",implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),validator=dict(id=checker.ORACLE_ID,version="1",callable="_oracle",implementation_path="build/tei/schaff_history_vol1_current_oracle.py",implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",sha256=sha256((ROOT/"ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()).hexdigest()))
    put(BASE/"source-manifest.json",canonical(record));print(json.dumps(dict(status="prepared",source_elements=30285,body_elements=30098,chapters=12,indexes=8)))
if __name__=="__main__":main()
