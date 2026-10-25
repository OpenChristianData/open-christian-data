"""Bind complete retained Romans, unchanged historical body, and localized header."""
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import chrysostom_romans_reconstruction as producer,chrysostom_romans_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "chrysostom-homilies-on-romans"
FORM_ID = WORK_ID+"-ccel-npnf111-retained-en"
EDITION_ID = WORK_ID+"-ccel-npnf111-electronic"
ACQUISITION_ID = WORK_ID+"-ccel-npnf111-acquired"
WORK = Path("library/works")/WORK_ID
EDITION = WORK/"forms"/FORM_ID/"editions"/EDITION_ID
ACQUISITION = EDITION/"acquisitions"/(ACQUISITION_ID+".json")
BASE = Path("sources/ccel-romans-npnf111")/WORK_ID
SOURCE = Path("raw/ccel/npnf1/npnf111.xml")
SOURCE_SHA = "46072a7fefb80b4b7ea68544b46c13fc1785bd29d99834fd2f867f8aa5e14f08"
HISTORICAL = Path("reports/_logs/chrysostom-romans-reconciliation-20261001-v1/replayed-selected-body.xml")
HISTORICAL_SHA = "8e899887654b77a7ac252ab90eca8f20ae336d62d6dd72161ea34b51a86205e3"
TITLE = "Homilies on the Epistle of Paul to the Romans"
SCOPE = "Complete retained CCEL NPNF1-11 ThML.body/div1[@id='vii'], including its own title/translator/reviser matter, Preface, Argument, all 32 homilies, all 528 attached notes, 236 page markers and 1510 scripture references. Shared volume headers/prefaces and index are separately source-accounted context; complete Acts (vi) is a sibling work outside this master. One complete titled Romans work, one TEI; no homily child work IDs or corrected source readings."
DATA_NOTICE = Path("data/prose")/WORK_ID/"README.md"
canonical = producer.canonical
NS = "{http://www.tei-c.org/ns/1.0}"


def put(p,raw):
    io_path(ROOT/p).parent.mkdir(parents=True,exist_ok=True)
    io_path(ROOT/p).write_bytes(raw)


def binding(name,p,role):
    raw = io_path(ROOT/p).read_bytes()
    return dict(name=name,path=Path(p).as_posix(),role=role,bytes=len(raw),sha256=sha256(raw).hexdigest())


def main():
    source = (ROOT/SOURCE).read_bytes()
    acq = validate_acquisition(io_path(ROOT/ACQUISITION),root=ROOT)
    if sha256(source).hexdigest()!=SOURCE_SHA or acq["source_sha256"]!=SOURCE_SHA or sha256((ROOT/HISTORICAL).read_bytes()).hexdigest()!=HISTORICAL_SHA:
        raise ValueError("retained source/historical body/acquisition differs")
    doc = etree.fromstring(source,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
    selected = doc.find("ThML.body/div1[@id='vii']")
    credits = []
    for name,role,key in (("J. B. Morris","translator and annotator","vii.i-p12"),("W. H. Simcox","translation reviser","vii.i-p14"),("George B. Stevens","reviser and annotator","vii-p13")):
        credits.append(dict(name=name,role=role,source_id=key,literal_text="".join(doc.xpath('//*[@id="'+key+'"]')[0].itertext())))
    # Localize the one-work header from source-attested credits, retaining all body IDs.
    header = etree.Element(NS+"teiHeader",nsmap={None:NS[1:-1]})
    file = etree.SubElement(header,NS+"fileDesc")
    titles = etree.SubElement(file,NS+"titleStmt")
    etree.SubElement(titles,NS+"title").text = TITLE
    etree.SubElement(titles,NS+"author").text = "John Chrysostom"
    for credit in credits:
        resp = etree.SubElement(titles,NS+"respStmt")
        etree.SubElement(resp,NS+"resp").text = credit["role"]
        etree.SubElement(resp,NS+"name").text = credit["name"]
    etree.SubElement(etree.SubElement(file,NS+"publicationStmt"),NS+"p").text = "Private nonaccepted retained electronic-witness reconstruction; rights and publication not established."
    bibl = etree.SubElement(etree.SubElement(file,NS+"sourceDesc"),NS+"bibl")
    etree.SubElement(bibl,NS+"title").text = doc.find("ThML.head/electronicEdInfo/DC/DC.Title").text
    etree.SubElement(bibl,NS+"publisher").text = "Christian Classics Ethereal Library"
    etree.SubElement(bibl,NS+"ptr",target=acq["url"])
    etree.SubElement(bibl,NS+"note",type="work-scope").text = SCOPE
    etree.SubElement(bibl,NS+"note",type="retained-print-statement").text = doc.find("ThML.head/printSourceInfo/published").text
    etree.SubElement(etree.SubElement(header,NS+"encodingDesc"),NS+"p").text = "Complete source-native work mapped with retained LIB043 rules; literal title heads, source hierarchy, wording, Greek spans, classes, notes, scripture references and physical page markers conserved. Historical ordinal offset 26901 preserves all generated italic IDs. Unrepresented source attributes and outside context are explicitly inventoried; no spelling correction or new image pixels."
    outside = []
    for child in doc.find("ThML.body"):
        if not isinstance(child.tag,str):
            outside.append(dict(kind="non-element",sha256=sha256(etree.tostring(child)).hexdigest(),destination="retained source shell outside selected work"))
        elif child.get("id")!="vii":
            outside.append(dict(tag=child.tag,id=child.get("id"),title=child.get("title"),elements=sum(1 for n in child.iter() if isinstance(n.tag,str)),sha256=sha256(etree.tostring(child,method="c14n")).hexdigest(),destination="retained sibling work" if child.get("id")=="vi" else "retained shared volume context/index; relevant metadata/credit used in header and notices"))
    accounting = dict(contract="ocd-chrysostom-romans-complete-accountability-v1",work_id=WORK_ID,source_sha256=SOURCE_SHA,source_bytes=len(source),
        represented_source_elements=5141,source_title_heads=35,homily_count=32,note_count=528,page_count=236,scripture_reference_count=1510,
        historical_ordinal_offset=26901,full_envelope_accounted=True,unexplained_omissions=0,source_header=dict(elements=sum(1 for n in doc.find("ThML.head").iter() if isinstance(n.tag,str)),sha256=sha256(etree.tostring(doc.find("ThML.head"),method="c14n")).hexdigest(),destination="retained metadata/permission context; source-attested claims in header and visible notice"),outside_work=outside,
        shell_disposition="Complete unchanged raw XML retains document shell, stylesheet declarations, comments, root/body carriers and their text/tails; only declared vii subtree is the accepted intellectual-work selection.")
    questions = [dict(id=WORK_ID+"-"+key,status="unresolved",kind=key,detail=text) for key,text in (("human","Historical bounded visual review is retained evidence, not current human textual/visual acceptance."),("print","Physical edition equivalence and full print collation remain unassessed."),("rights","Provider Public Domain and CCEL formatting permission are retained evidence, not independent rights clearance."),("publication","No public publication authorization or action."))]
    profile = dict(work_id=WORK_ID,source_sha256=SOURCE_SHA,scope=SCOPE,historical_ordinal_offset=26901,credits=credits,
        header_xml=etree.tostring(header,encoding="unicode"),accounting=accounting,questions=questions,
        historical_reuse="Historical whole seven-work package is not current one-work promotion proof; selected body replays exactly. Old 37a-12 mechanical/visual receipts remain bounded historical evidence. Shared source profile/manifest/mapper/oracle left unchanged.",review_patterns=["RP-01","RP-03","RP-04","RP-06","RP-11","RP-13","RP-14"])
    put(BASE/"profile.json",canonical(profile))
    put(BASE/"validation-policy.json",canonical(dict(scope=SCOPE,rules=["independent whole native source/TEI structure and every attribute/text/tail/order check","independent source ledgers and outside-envelope dispositions","stdlib/lxml source corroboration","historical body identity and all301 italic IDs","P5","fresh process replay and meaningful mutations"],shared_assumptions="Readonly declarative LIB043 mapping and XML parsing; source cross-parser fingerprint and coordinator direct native tree review corroborate.")))
    notice = ("# Chrysostom, Homilies on Romans: source and data credit\n\nSourced via [CCEL.org](https://www.ccel.org/ccel/schaff/npnf111.html), Nicene and Post-Nicene Fathers, First Series, volume XI. "
        "The work's own title matter names J. B. Morris and W. H. Simcox as translators and George B. Stevens as reviser with notes. Its Preface credits Morris with the translation, much of the notes, and index; it describes Simcox's revision by Field's revised Benedictine text, preserving other previous translation. These source-local roles govern this work, without assigning unrelated volume translators.\n\n"
        "The electronic printSourceInfo states Edinburgh: T&T Clark. Canonical edition wording is retained unchanged; no unverified date or print-edition equivalence is inferred. The source states Public Domain and careful proofreading. Retained CCEL permission permits parsing ThML/XML for text, reserves rights in CCEL files/formatting, and restricts selling CCEL files or derivatives of their formatting. Credit CCEL when publishing. These are provider statements, not independent rights clearance.\n\n"+SCOPE+
        "\n\nSource readings, including uncertain or apparent typographical errors, remain unchanged. Human textual/visual acceptance, print comparison, final rights disposition and publication remain separate. Carry this visible credit to `"+DATA_NOTICE.as_posix()+"`.\n")
    put(BASE/"README.source.md",notice.encode())
    authorities = [("retained-text",SOURCE,"primary-source"),("profile",BASE/"profile.json","complete-source-feature-profile"),("validation-policy",BASE/"validation-policy.json","independent-validation-policy"),("source-readme",BASE/"README.source.md","source-attribution"),("historical-selected-body",HISTORICAL,"checked-historical-body"),("coordinator-source-review","reports/_logs/chrysostom-romans-reconciliation-20261001-v1/direct-historical-body-review.json","independent-source-corroboration"),("historical-replay","reports/_logs/chrysostom-romans-reconciliation-20261001-v1/selected-body-replay.json","historical-body-replay"),("legacy-mapper","build/tei/npnf_chrysostom_reconstruction.py","readonly-mapping-support"),("legacy-checker","build/tei/npnf_chrysostom_oracle.py","independent-checker-support"),("canonical-acquisition",ACQUISITION,"retained-source-identity"),("ccel-permission","docs/sources/ccel-permission.md","permission-evidence"),("tei-p5-xsd","ocd_kernel/tei/vendor/xsd/tei_all.xsd","tei-validation-schema"),("candidate-package-schema","ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","candidate-package-schema")]
    manifest = dict(contract="ocd-source-manifest-v1",source_id="chrysostom-romans-npnf111-complete-v1",work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=[binding(*a) for a in authorities],
        converter=dict(id=producer.CONVERTER_ID,version=producer.CONVERTER_VERSION,callable="_convert",implementation_path="build/tei/chrysostom_romans_reconstruction.py",implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),
        validator=dict(id=checker.ORACLE_ID,version=checker.ORACLE_VERSION,callable="_oracle",implementation_path="build/tei/chrysostom_romans_oracle.py",implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),
        package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",sha256=sha256((ROOT/"ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()).hexdigest()))
    put(BASE/"source-manifest.json",canonical(manifest))
    print(json.dumps(dict(status="prepared",source_sha256=SOURCE_SHA,source_elements=5141,homilies=32,body_preserved=True)))


if __name__=="__main__":
    main()
