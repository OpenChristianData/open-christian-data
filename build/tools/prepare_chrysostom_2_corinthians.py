"""Bind complete retained Second Corinthians, unchanged historical body, and localized header."""
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import chrysostom_2_corinthians_reconstruction as producer,chrysostom_2_corinthians_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "chrysostom-homilies-on-2-corinthians"
FORM_ID = WORK_ID+"-ccel-npnf112-retained-en"
EDITION_ID = WORK_ID+"-ccel-npnf112-electronic"
ACQUISITION_ID = WORK_ID+"-ccel-npnf112-acquired"
WORK = Path("library/works")/WORK_ID
EDITION = WORK/"forms"/FORM_ID/"editions"/EDITION_ID
ACQUISITION = EDITION/"acquisitions"/(ACQUISITION_ID+".json")
BASE = Path("sources/ccel-2-corinthians-npnf112")/WORK_ID
SOURCE = Path("raw/ccel/npnf1/npnf112.xml")
SOURCE_SHA = "b8b345e060625cdf495e888322d88e922f66e686863e818a978204c5f564a4dd"
HISTORICAL = Path("reports/_logs/chrysostom-2-corinthians-reconciliation-20261001-v1/historical-selected-body.xml")
HISTORICAL_SHA = "ec38624149560592b0f666327191b10c2d272dbc7ec9732559c321bd7a0433f7"
TITLE = "Homilies on the Second Epistle of Paul to the Corinthians"
SCOPE = "Complete retained CCEL NPNF1-12 ThML.body/div1[@id='v'], including own opening title matter in v.i, all 30 homilies, all 703 attached notes, 150 page markers and 751 scripture references. Shared volume title pages and Preface iii, including the Second Epistle-specific translation/revision credits, remain separately source-accounted context with relevant metadata in header/notices; First Corinthians iv and shared indexes remain retained outside this master. One complete titled Second Corinthians collection, one TEI; no homily child work IDs or corrected source readings."
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
    selected = doc.find("ThML.body/div1[@id='v']")
    credits = []
    for name,role,key in (("J. Ashworth","Second Epistle Oxford translator","iii-p17"),("Talbot W. Chambers","Oxford translation reviser and annotator","ii-p8"),("Philip Schaff","series editor","i-p16")):
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
    etree.SubElement(etree.SubElement(header,NS+"encodingDesc"),NS+"p").text = "Complete source-native work mapped with retained LIB043 rules; literal title heads, source hierarchy, wording, Greek spans, classes, notes, scripture references and physical page markers conserved. Historical ordinal offset 37050 preserves all 84 generated italic IDs. Unrepresented source attributes and outside context are explicitly inventoried; no spelling correction or new image pixels."
    outside = []
    for child in doc.find("ThML.body"):
        if not isinstance(child.tag,str):
            outside.append(dict(kind="non-element",sha256=sha256(etree.tostring(child)).hexdigest(),destination="retained source shell outside selected work"))
        elif child.get("id")!="v":
            outside.append(dict(tag=child.tag,id=child.get("id"),title=child.get("title"),elements=sum(1 for n in child.iter() if isinstance(n.tag,str)),sha256=sha256(etree.tostring(child,method="c14n")).hexdigest(),destination="retained sibling work" if child.get("id")=="iv" else "retained shared volume context/index; relevant metadata/credit used in header and notices"))
    accounting = dict(contract="ocd-chrysostom-2-corinthians-complete-accountability-v1",work_id=WORK_ID,source_sha256=SOURCE_SHA,source_bytes=len(source),
        represented_source_elements=4174,source_title_heads=31,homily_count=30,note_count=703,page_count=150,scripture_reference_count=751,
        historical_ordinal_offset=37050,full_envelope_accounted=True,unexplained_omissions=0,source_header=dict(elements=sum(1 for n in doc.find("ThML.head").iter() if isinstance(n.tag,str)),sha256=sha256(etree.tostring(doc.find("ThML.head"),method="c14n")).hexdigest(),destination="retained metadata/permission context; source-attested claims in header and visible notice"),outside_work=outside,
        shell_disposition="Complete unchanged raw XML retains document shell, stylesheet declarations, comments, root/body carriers and their text/tails; only declared v subtree is the accepted intellectual-work selection.")
    questions = [dict(id=WORK_ID+"-"+key,status="unresolved",kind=key,detail=text) for key,text in (("human","Historical bounded visual review is retained evidence, not current human textual/visual acceptance."),("print","Physical edition equivalence and full print collation remain unassessed."),("rights","Provider Public Domain and CCEL formatting permission are retained evidence, not independent rights clearance."),("publication","No public publication authorization or action."))]
    profile = dict(work_id=WORK_ID,source_sha256=SOURCE_SHA,scope=SCOPE,historical_ordinal_offset=37050,credits=credits,
        header_xml=etree.tostring(header,encoding="unicode"),accounting=accounting,questions=questions,
        historical_reuse="Historical whole seven-work package is not current one-work promotion proof; selected body replays exactly. Old 37a-07 mechanical/visual receipts remain bounded historical evidence. Shared source profile/manifest/mapper/oracle left unchanged.",review_patterns=["RP-01","RP-03","RP-04","RP-06","RP-11","RP-13","RP-14"])
    put(BASE/"profile.json",canonical(profile))
    put(BASE/"validation-policy.json",canonical(dict(scope=SCOPE,rules=["independent whole native source/TEI structure and every attribute/text/tail/order check","independent source ledgers and outside-envelope dispositions","stdlib/lxml source corroboration","historical body identity and all84 italic IDs","P5","fresh process replay and meaningful mutations"],shared_assumptions="Readonly declarative LIB043 mapping and XML parsing; source cross-parser fingerprint and historical independent source mapping corroborate.")))
    notice = ("# Chrysostom, Homilies on Second Corinthians: source and data credit\n\nSourced via [CCEL.org](https://www.ccel.org/ccel/schaff/npnf112.html), Nicene and Post-Nicene Fathers, First Series, volume XII, edited by Philip Schaff. "
        "The shared title page names the Oxford Translation revised with additional notes by Talbot W. Chambers. The shared Preface explicitly attributes the Second Epistle translation to the Rev. J. Ashworth of Brasenose College, and states that Chambers occasionally amended both Epistles' translations; his notes appear in square brackets with his initial. Cornish and Medley are credited there specifically for the First Epistle and are not assigned to this work.\n\n"
        "The electronic printSourceInfo states Edinburgh: T&T Clark, 1889. The series title page names T&T Clark, Edinburgh, and Wm. B. Eerdmans Publishing Company, Grand Rapids, Michigan. The shared Preface describes the original London volumes dated 1844 and 1848, gives S. Clement, 1848 for the Second Epistle note, and Chambers signs New York, June, 1889. These distinct source claims are retained; no print-edition equivalence or metadata date correction is inferred.\n\n"
        "The electronic header states Public Domain and careful proofreading. Retained CCEL permission permits parsing ThML/XML for text, reserves rights in CCEL files and formatting, and restricts selling CCEL files or derivatives of their formatting. Credit CCEL when publishing. These are provider statements, not independent rights clearance.\n\n"+SCOPE+
        "\n\nSource readings, including uncertain or apparent typographical errors, remain unchanged. Human textual/visual acceptance, print comparison, final rights disposition and publication remain separate. Carry this visible credit to `"+DATA_NOTICE.as_posix()+"`.\n")
    put(BASE/"README.source.md",notice.encode())
    authorities = [("retained-text",SOURCE,"primary-source"),("profile",BASE/"profile.json","complete-source-feature-profile"),("validation-policy",BASE/"validation-policy.json","independent-validation-policy"),("source-readme",BASE/"README.source.md","source-attribution"),("historical-selected-body",HISTORICAL,"checked-historical-body"),("historical-source-check","reports/_logs/chrysostom-2-corinthians-reconciliation-20261001-v1/historical-body-extraction.json","independent-source-corroboration"),("historical-replay","reports/_logs/chrysostom-2-corinthians-reconciliation-20261001-v1/historical-body-extraction.json","historical-body-replay"),("legacy-mapper","build/tei/npnf_chrysostom_reconstruction.py","readonly-mapping-support"),("legacy-checker","build/tei/npnf_chrysostom_oracle.py","independent-checker-support"),("canonical-acquisition",ACQUISITION,"retained-source-identity"),("ccel-permission","docs/sources/ccel-permission.md","permission-evidence"),("tei-p5-xsd","ocd_kernel/tei/vendor/xsd/tei_all.xsd","tei-validation-schema"),("candidate-package-schema","ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","candidate-package-schema")]
    manifest = dict(contract="ocd-source-manifest-v1",source_id="chrysostom-2-corinthians-npnf112-complete-v1",work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=[binding(*a) for a in authorities],
        converter=dict(id=producer.CONVERTER_ID,version=producer.CONVERTER_VERSION,callable="_convert",implementation_path="build/tei/chrysostom_2_corinthians_reconstruction.py",implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),
        validator=dict(id=checker.ORACLE_ID,version=checker.ORACLE_VERSION,callable="_oracle",implementation_path="build/tei/chrysostom_2_corinthians_oracle.py",implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),
        package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",sha256=sha256((ROOT/"ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()).hexdigest()))
    put(BASE/"source-manifest.json",canonical(manifest))
    print(json.dumps(dict(status="prepared",source_sha256=SOURCE_SHA,source_elements=4174,homilies=30,body_preserved=True)))


if __name__=="__main__":
    main()
