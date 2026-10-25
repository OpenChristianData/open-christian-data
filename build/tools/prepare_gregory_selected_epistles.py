"""Bind complete retained Gregory Selected Epistles, unchanged historical body, and localized header."""
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import gregory_selected_epistles_reconstruction as producer,gregory_selected_epistles_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "gregory-the-great-selected-epistles"
FORM_ID = WORK_ID+"-ccel-npnf213-retained-en"
EDITION_ID = WORK_ID+"-ccel-npnf213-electronic"
ACQUISITION_ID = WORK_ID+"-ccel-npnf213-acquired"
WORK = Path("library/works")/WORK_ID
EDITION = WORK/"forms"/FORM_ID/"editions"/EDITION_ID
ACQUISITION = EDITION/"acquisitions"/(ACQUISITION_ID+".json")
BASE = Path("sources/ccel-gregory-selected-epistles-npnf213")/WORK_ID
SOURCE = Path("raw/ccel/npnf2/npnf213.xml")
SOURCE_SHA = "323ecfb6470854de378fdf47375b2e15b108e72559bbe3167da9c37500bbf2ae"
HISTORICAL = Path("reports/_logs/gregory-selected-epistles-reconciliation-20261001-v1/historical-selected-body.xml")
HISTORICAL_SHA = "aa898caa05eb481798af6b1f7b95fc304abd2e7ecb4ddf2e08fff7cdb21edd91"
TITLE = "Selected Epistles"
SCOPE = "Complete retained CCEL NPNF2-13 ThML.body/div1[@id='ii'], Selected Epistles of Gregory the Great, Books IX through XIV: all 147 selected epistle entries plus the source-owned title page, General Literature, Regula Pastoralis (Notes), and Registrum Epistolarum (Notes). All 2,968 native elements, 158 literal heads, 248 notes, 117 page markers, 189 source reference tags including one neutral letter reference, and all 639 italic elements are conserved. This is the complete retained editorial selection, not every surviving letter or full original compositions. The final source note ii.x.viii-p11 states that the remainder of the last letter has not been translated; that explicit limitation is preserved without invented completion. Shared volume title and indexes remain accounted retained context; sibling Ephraim/Aphrahat collection remains outside this master. Source-owned introductory material is included, not misclassified as separately complete Regula Pastoralis. One complete selected collection, one TEI, no per-letter work identities."
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
    selected = doc.find("ThML.body/div1[@id='ii']")
    credits = []
    for name,role,selector in (("James Barmby","translator, with notes and indices","//*[@id='ii.i-p8']"),("Philip Schaff","editor, as named in the electronic DC header","/ThML/ThML.head/electronicEdInfo/DC/DC.Creator[@sub='Editor'][@scheme='short-form']")):
        credits.append(dict(name=name,role=role,source_selector=selector,literal_text="".join(doc.xpath(selector)[0].itertext())))
    # Localize the one-work header from source-attested credits, retaining all body IDs.
    header = etree.Element(NS+"teiHeader",nsmap={None:NS[1:-1]})
    file = etree.SubElement(header,NS+"fileDesc")
    titles = etree.SubElement(file,NS+"titleStmt")
    etree.SubElement(titles,NS+"title").text = TITLE
    etree.SubElement(titles,NS+"author").text = "Gregory the Great; edition context as attributed in the retained source"
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
    etree.SubElement(etree.SubElement(header,NS+"encodingDesc"),NS+"p").text = "Complete source-native work mapped with retained LIB048 rules; literal title heads, source hierarchy, wording, language spans, classes, notes, source references and physical page markers conserved. Historical global ordinal offset 50326 preserves all original IDs. Unrepresented source attributes and outside context are explicitly inventoried; no spelling correction or new image pixels."
    outside = []
    for child in doc.find("ThML.body"):
        if not isinstance(child.tag,str):
            outside.append(dict(kind="non-element",sha256=sha256(etree.tostring(child)).hexdigest(),destination="retained source shell outside selected work"))
        elif child.get("id")!="ii":
            outside.append(dict(tag=child.tag,id=child.get("id"),title=child.get("title"),elements=sum(1 for n in child.iter() if isinstance(n.tag,str)),sha256=sha256(etree.tostring(child,method="c14n")).hexdigest(),destination="retained sibling work" if child.get("id")=="iii" else "retained shared volume context/index; relevant metadata/credit used in header and notices"))
    accounting = dict(contract="ocd-gregory-the-great-selected-epistles-complete-accountability-v1",work_id=WORK_ID,source_sha256=SOURCE_SHA,source_bytes=len(source),
        represented_source_elements=2968,source_title_heads=158,epistle_count=147,book_count=6,book_epistle_counts=[60,14,38,8,19,8],note_count=248,page_count=117,source_reference_tag_count=189,neutral_letter_reference_count=1,rtl_count=0,
        historical_ordinal_offset=50326,full_envelope_accounted=True,unexplained_omissions=0,source_header=dict(elements=sum(1 for n in doc.find("ThML.head").iter() if isinstance(n.tag,str)),sha256=sha256(etree.tostring(doc.find("ThML.head"),method="c14n")).hexdigest(),destination="retained metadata/permission context; source-attested claims in header and visible notice"),outside_work=outside,
        shell_disposition="Complete unchanged raw XML retains document shell, stylesheet declarations, comments, root/body carriers and their text/tails; only declared ii subtree is the accepted intellectual-work selection.")
    questions = [dict(id=WORK_ID+"-"+key,status="unresolved",kind=key,detail=text) for key,text in (("human","Historical bounded visual review is retained evidence, not current human textual/visual acceptance."),("print","Physical edition equivalence and full print collation remain unassessed."),("rights","Provider Public Domain and CCEL formatting permission are retained evidence, not independent rights clearance."),("publication","No public publication authorization or action."))]
    profile = dict(work_id=WORK_ID,source_sha256=SOURCE_SHA,scope=SCOPE,historical_ordinal_offset=50326,credits=credits,
        header_xml=etree.tostring(header,encoding="unicode"),accounting=accounting,questions=questions,
        historical_reuse="Historical whole fifteen-work package is not current one-work promotion proof; selected body replays exactly. Old 37a-31 mechanical/visual receipts remain bounded historical evidence. Shared source profile/manifest/mapper/oracle left unchanged. The complete source ii editorial selection remains in one TEI; omitted original compositions are not restored or acquired.",review_patterns=["RP-01","RP-03","RP-04","RP-06","RP-11","RP-13","RP-14"])
    put(BASE/"profile.json",canonical(profile))
    put(BASE/"validation-policy.json",canonical(dict(scope=SCOPE,rules=["independent whole native source/TEI structure and every attribute/text/tail/order check","independent source ledgers and outside-envelope dispositions","stdlib/lxml source corroboration","historical body identity and all 639 italic IDs","P5","fresh process replay and meaningful mutations"],shared_assumptions="Readonly declarative LIB048 mapping and XML parsing; source cross-parser fingerprint and historical independent source mapping corroborate.")))
    notice = ("# Gregory Selected Epistles: source and data credit\n\nSourced via [CCEL.org](https://www.ccel.org/ccel/schaff/npnf213.html), Nicene and Post-Nicene Fathers, Second Series, volume XIII. The retained Gregory title page names the late Rev. James Barmby, D.D., as translator with notes and indices, and explicitly limits this collection to Books IX through XIV. The electronic DC header names Philip Schaff as editor. No unsupported allocation or series editor is inferred.\n\n"
        "The retained shared title page names T&T Clark, Edinburgh, and Wm. B. Eerdmans Publishing Company, Grand Rapids, Michigan. Its printSourceInfo publication field is empty. The inherited catalog edition title remains unchanged, but its 1898 date is not asserted as newly verified primary-source metadata.\n\n"
        "The electronic header states Public Domain, identifies Christian Classics Ethereal Library as electronic publisher, and says Carefully proofed. These provider statements do not establish independent rights clearance or print equivalence. Retained CCEL permission permits parsing ThML/XML for text, reserves CCEL file/formatting rights and restricts selling CCEL files or derivatives of their formatting. Credit CCEL when publishing.\n\n"+SCOPE+
        "\n\nHuman textual/visual acceptance, print collation, rights clearance and publication remain separate. Carry visible credit to `"+DATA_NOTICE.as_posix()+"`.\n")
    put(BASE/"README.source.md",notice.encode())
    authorities = [("aggregate-validation-policy","sources/structured-text/npnf2-lib048/npnf2-lib048.validation-policy.json","readonly-declarative-mapping-policy"),("retained-text",SOURCE,"primary-source"),("profile",BASE/"profile.json","complete-source-feature-profile"),("validation-policy",BASE/"validation-policy.json","independent-validation-policy"),("source-readme",BASE/"README.source.md","source-attribution"),("historical-selected-body",HISTORICAL,"checked-historical-body"),("historical-source-check","reports/_logs/gregory-selected-epistles-reconciliation-20261001-v1/historical-body-extraction-and-replay.json","independent-source-corroboration"),("historical-replay","reports/_logs/gregory-selected-epistles-reconciliation-20261001-v1/historical-body-extraction-and-replay.json","historical-body-replay"),("legacy-mapper","build/tei/npnf2_lib048_reconstruction.py","readonly-mapping-support"),("legacy-checker","build/tei/npnf2_lib048_oracle.py","independent-checker-support"),("canonical-acquisition",ACQUISITION,"retained-source-identity"),("ccel-permission","docs/sources/ccel-permission.md","permission-evidence"),("tei-p5-xsd","ocd_kernel/tei/vendor/xsd/tei_all.xsd","tei-validation-schema"),("candidate-package-schema","ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","candidate-package-schema")]
    manifest = dict(contract="ocd-source-manifest-v1",source_id="gregory-the-great-selected-epistles-npnf213-complete-v1",work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=[binding(*a) for a in authorities],
        converter=dict(id=producer.CONVERTER_ID,version=producer.CONVERTER_VERSION,callable="_convert",implementation_path="build/tei/gregory_selected_epistles_reconstruction.py",implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),
        validator=dict(id=checker.ORACLE_ID,version=checker.ORACLE_VERSION,callable="_oracle",implementation_path="build/tei/gregory_selected_epistles_oracle.py",implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),
        package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",sha256=sha256((ROOT/"ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()).hexdigest()))
    put(BASE/"source-manifest.json",canonical(manifest))
    print(json.dumps(dict(status="prepared",source_sha256=SOURCE_SHA,source_elements=2968,epistles=147,books=6,book_epistle_counts=[60,14,38,8,19,8],body_preserved=True)))


if __name__=="__main__":
    main()
