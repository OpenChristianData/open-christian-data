"""Bind complete retained Jerome Letters, unchanged historical body, and localized header."""
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import jerome_letters_reconstruction as producer,jerome_letters_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "jerome-letters"
FORM_ID = WORK_ID+"-ccel-npnf206-retained-en"
EDITION_ID = WORK_ID+"-ccel-npnf206-electronic"
ACQUISITION_ID = WORK_ID+"-ccel-npnf206-acquired"
WORK = Path("library/works")/WORK_ID
EDITION = WORK/"forms"/FORM_ID/"editions"/EDITION_ID
ACQUISITION = EDITION/"acquisitions"/(ACQUISITION_ID+".json")
BASE = Path("sources/ccel-jerome-letters-npnf206")/WORK_ID
SOURCE = Path("raw/ccel/npnf2/npnf206.xml")
SOURCE_SHA = "6bf37affb240f5a775995ab2353c00569b34990130c98649a358f30f37f41f8d"
HISTORICAL = Path("reports/_logs/jerome-letters-reconciliation-20261001-v1/historical-selected-body.xml")
HISTORICAL_SHA = "3a4d3b09d5b34404075b53431e3c114d7c466a8673fb87c8de08d8638935656a"
TITLE = "Letters"
SCOPE = "Complete retained CCEL NPNF2-06 ThML.body/div1[@id='v'], The Letters of St. Jerome, all 150 source-numbered entries, including translated text, abstracts, incoming correspondence and disputed attributions exactly as supplied. This is the complete retained editorial collection, not 150 fully translated letters all authored by Jerome. All 13,459 native elements, 151 literal heads, 4,012 notes, 295 page markers, and 2,853 source scripRef tags, six explicitly neutral letter references and five Hebrew RTL spans are preserved. Shared title pages/Translator's Preface/Prolegomena and indexes remain separately accounted retained context; relevant primary credits are localized in header/notices. All nine sibling treatises remain outside this master. One collection, one TEI; no child work identities, invented missing text or corrected source readings."
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
    for name,role,key in (("W. H. Fremantle","volume translator and reviser","iii-p4"),("G. Lewis","coadjutor: first translation draft and notes","ii-p7"),("W. G. Martley","coadjutor: first translation draft and notes","ii-p10")):
        credits.append(dict(name=name,role=role,source_id=key,literal_text="".join(doc.xpath('//*[@id="'+key+'"]')[0].itertext())))
    # Localize the one-work header from source-attested credits, retaining all body IDs.
    header = etree.Element(NS+"teiHeader",nsmap={None:NS[1:-1]})
    file = etree.SubElement(header,NS+"fileDesc")
    titles = etree.SubElement(file,NS+"titleStmt")
    etree.SubElement(titles,NS+"title").text = TITLE
    etree.SubElement(titles,NS+"author").text = "Jerome and correspondents, as attributed in the retained collection"
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
    etree.SubElement(etree.SubElement(header,NS+"encodingDesc"),NS+"p").text = "Complete source-native work mapped with retained LIB048 rules; literal title heads, source hierarchy, wording, Greek spans, classes, notes, scripture references and physical page markers conserved. Historical ordinal offset zero preserves all original IDs. Unrepresented source attributes and outside context are explicitly inventoried; no spelling correction or new image pixels."
    outside = []
    for child in doc.find("ThML.body"):
        if not isinstance(child.tag,str):
            outside.append(dict(kind="non-element",sha256=sha256(etree.tostring(child)).hexdigest(),destination="retained source shell outside selected work"))
        elif child.get("id")!="v":
            outside.append(dict(tag=child.tag,id=child.get("id"),title=child.get("title"),elements=sum(1 for n in child.iter() if isinstance(n.tag,str)),sha256=sha256(etree.tostring(child,method="c14n")).hexdigest(),destination="retained sibling work" if child.get("id")=="vi" else "retained shared volume context/index; relevant metadata/credit used in header and notices"))
    accounting = dict(contract="ocd-jerome-letters-complete-accountability-v1",work_id=WORK_ID,source_sha256=SOURCE_SHA,source_bytes=len(source),
        represented_source_elements=13459,source_title_heads=151,letter_count=150,note_count=4012,page_count=295,source_reference_tag_count=2853,neutral_letter_reference_count=6,rtl_count=5,
        historical_ordinal_offset=0,full_envelope_accounted=True,unexplained_omissions=0,source_header=dict(elements=sum(1 for n in doc.find("ThML.head").iter() if isinstance(n.tag,str)),sha256=sha256(etree.tostring(doc.find("ThML.head"),method="c14n")).hexdigest(),destination="retained metadata/permission context; source-attested claims in header and visible notice"),outside_work=outside,
        shell_disposition="Complete unchanged raw XML retains document shell, stylesheet declarations, comments, root/body carriers and their text/tails; only declared v subtree is the accepted intellectual-work selection.")
    questions = [dict(id=WORK_ID+"-"+key,status="unresolved",kind=key,detail=text) for key,text in (("human","Historical bounded visual review is retained evidence, not current human textual/visual acceptance."),("print","Physical edition equivalence and full print collation remain unassessed."),("rights","Provider Public Domain and CCEL formatting permission are retained evidence, not independent rights clearance."),("publication","No public publication authorization or action."))]
    profile = dict(work_id=WORK_ID,source_sha256=SOURCE_SHA,scope=SCOPE,historical_ordinal_offset=0,credits=credits,
        header_xml=etree.tostring(header,encoding="unicode"),accounting=accounting,questions=questions,
        historical_reuse="Historical whole fifteen-work package is not current one-work promotion proof; selected body replays exactly. Old 37a-17 mechanical/visual receipts remain bounded historical evidence. Shared source profile/manifest/mapper/oracle left unchanged. Historical treatise helper constituent-ID suggestion is outside this collection task; all 150 parts remain in this one TEI.",review_patterns=["RP-01","RP-03","RP-04","RP-06","RP-11","RP-13","RP-14"])
    put(BASE/"profile.json",canonical(profile))
    put(BASE/"validation-policy.json",canonical(dict(scope=SCOPE,rules=["independent whole native source/TEI structure and every attribute/text/tail/order check","independent source ledgers and outside-envelope dispositions","stdlib/lxml source corroboration","historical body identity and all 233 italic IDs","P5","fresh process replay and meaningful mutations"],shared_assumptions="Readonly declarative LIB048 mapping and XML parsing; source cross-parser fingerprint and historical independent source mapping corroborate.")))
    notice = ("# Jerome Letters: source and data credit\n\nSourced via [CCEL.org](https://www.ccel.org/ccel/schaff/npnf206.html), Nicene and Post-Nicene Fathers, Second Series, volume VI, edited by Philip Schaff and Henry Wace. The title page names W. H. Fremantle, assisted by G. Lewis and W. G. Martley. In the Translator's Preface, Fremantle says Lewis and Martley prepared the first draft and added most notes, while he reviewed every part, correcting, adding and sometimes rewriting manuscript/proofs, and composed Prolegomena and Indices. These are source-attested volume roles; no unsupported per-letter allocation is inferred.\n\n"
        "The electronic printSourceInfo states New York: Christian Literature Publishing Co., 1892. The retained title page names T&T Clark, Edinburgh, and Wm. B. Eerdmans Publishing Company, Grand Rapids, Michigan. Fremantle signs Canterbury, November, 1892. These distinct source claims remain separate; no print-equivalence or date correction is inferred.\n\n"
        "The electronic header states Public Domain and identifies Christian Classics Ethereal Library as electronic publisher. Retained CCEL permission permits parsing ThML/XML for text, reserves CCEL file/formatting rights and restricts selling CCEL files or derivatives of their formatting. Credit CCEL when publishing. Provider statements are not independent rights clearance.\n\n"+SCOPE+
        "\n\nSource headings preserve correspondents and disputed attribution; some numbered entries are only abstracts, including CXLVIII through CL, whose source explicitly qualifies non-Jerome authorship. Full omitted compositions are not invented. Historical treatise-only helpers' suggestion of constituent work IDs is not adopted for this explicitly authorized complete collection identity. Human textual/visual acceptance, print collation, rights clearance and publication remain separate. Carry visible credit to `"+DATA_NOTICE.as_posix()+"`.\n")
    put(BASE/"README.source.md",notice.encode())
    authorities = [("aggregate-validation-policy","sources/structured-text/npnf2-lib048/npnf2-lib048.validation-policy.json","readonly-declarative-mapping-policy"),("retained-text",SOURCE,"primary-source"),("profile",BASE/"profile.json","complete-source-feature-profile"),("validation-policy",BASE/"validation-policy.json","independent-validation-policy"),("source-readme",BASE/"README.source.md","source-attribution"),("historical-selected-body",HISTORICAL,"checked-historical-body"),("historical-source-check","reports/_logs/jerome-letters-reconciliation-20261001-v1/historical-body-extraction-and-replay.json","independent-source-corroboration"),("historical-replay","reports/_logs/jerome-letters-reconciliation-20261001-v1/historical-body-extraction-and-replay.json","historical-body-replay"),("legacy-mapper","build/tei/npnf2_lib048_reconstruction.py","readonly-mapping-support"),("legacy-checker","build/tei/npnf2_lib048_oracle.py","independent-checker-support"),("canonical-acquisition",ACQUISITION,"retained-source-identity"),("ccel-permission","docs/sources/ccel-permission.md","permission-evidence"),("tei-p5-xsd","ocd_kernel/tei/vendor/xsd/tei_all.xsd","tei-validation-schema"),("candidate-package-schema","ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","candidate-package-schema")]
    manifest = dict(contract="ocd-source-manifest-v1",source_id="jerome-letters-npnf206-complete-v1",work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=[binding(*a) for a in authorities],
        converter=dict(id=producer.CONVERTER_ID,version=producer.CONVERTER_VERSION,callable="_convert",implementation_path="build/tei/jerome_letters_reconstruction.py",implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),
        validator=dict(id=checker.ORACLE_ID,version=checker.ORACLE_VERSION,callable="_oracle",implementation_path="build/tei/jerome_letters_oracle.py",implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),
        package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",sha256=sha256((ROOT/"ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()).hexdigest()))
    put(BASE/"source-manifest.json",canonical(manifest))
    print(json.dumps(dict(status="prepared",source_sha256=SOURCE_SHA,source_elements=13459,letters=150,body_preserved=True)))


if __name__=="__main__":
    main()
