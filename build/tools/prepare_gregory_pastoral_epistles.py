"""Bind complete retained Gregory Pastoral Rule and Epistles, unchanged historical body, and localized header."""
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import gregory_pastoral_epistles_reconstruction as producer,gregory_pastoral_epistles_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "gregory-the-great-pastoral-rule-and-epistles"
FORM_ID = WORK_ID+"-ccel-npnf212-retained-en"
EDITION_ID = WORK_ID+"-ccel-npnf212-electronic"
ACQUISITION_ID = WORK_ID+"-ccel-npnf212-acquired"
WORK = Path("library/works")/WORK_ID
EDITION = WORK/"forms"/FORM_ID/"editions"/EDITION_ID
ACQUISITION = EDITION/"acquisitions"/(ACQUISITION_ID+".json")
BASE = Path("sources/ccel-gregory-pastoral-epistles-npnf212")/WORK_ID
SOURCE = Path("raw/ccel/npnf2/npnf212.xml")
SOURCE_SHA = "f701b4ce5196bc5890e50adabce4900cd07b803f3221115a7cce526ae0a95570"
HISTORICAL = Path("reports/_logs/gregory-pastoral-epistles-reconciliation-20261001-v1/historical-selected-body.xml")
HISTORICAL_SHA = "f3d9f08b37c68a6389ce4529ba4c6366b4e2bd1b2331a58b9496132188fa6578"
TITLE = "Pastoral Rule and Selected Epistles"
SCOPE = "Complete retained CCEL NPNF2-12 ThML.body/div1[@id='iii'], The Book of Pastoral Rule, and Selected Epistles, of Gregory the Great: source-owned title, Prefatory Note, Prolegomena, complete Pastoral Rule (preface and four parts, 64 titled chapters), and all 273 selected register entries in Books I through VIII. All 7,669 native elements, 356 literal heads, 506 notes, 273 page markers, 721 source reference tags including 12 neutral letter references, 1,835 italic elements and the pedigree image reference/label are conserved. The current retained supplemental pedigree PNG is bound separately; its historical snapshot bytes remain unknown. This is the complete retained editorial selection, not every surviving or fully translated original letter. The prefatory selection/specimen rationale, incoming John of Ravenna letter and all source limitations remain literal. Shared volume title/index remain accounted retained context; sibling Leo work remains outside this master. One complete source-titled composite collection, one TEI; no per-letter or per-book work identities, invented completion or corrected source readings."
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
    selected = doc.find("ThML.body/div1[@id='iii']")
    credits = []
    for name,role,selector in (("James Barmby","translator, with introduction, notes and indices","//*[@id='iii.i-p10']"),("Philip Schaff","editor, as named in the electronic DC header","/ThML/ThML.head/electronicEdInfo/DC/DC.Creator[@sub='Editor'][@scheme='short-form']")):
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
    etree.SubElement(etree.SubElement(header,NS+"encodingDesc"),NS+"p").text = "Complete source-native work mapped with retained LIB048 rules; literal title heads, source hierarchy, wording, language spans, classes, notes, source references and physical page markers conserved. Historical global ordinal offset 42657 preserves all original IDs. Unrepresented source attributes and outside context are explicitly inventoried; no spelling correction or new image pixels."
    outside = []
    for child in doc.find("ThML.body"):
        if not isinstance(child.tag,str):
            outside.append(dict(kind="non-element",sha256=sha256(etree.tostring(child)).hexdigest(),destination="retained source shell outside selected work"))
        elif child.get("id")!="iii":
            outside.append(dict(tag=child.tag,id=child.get("id"),title=child.get("title"),elements=sum(1 for n in child.iter() if isinstance(n.tag,str)),sha256=sha256(etree.tostring(child,method="c14n")).hexdigest(),destination="retained sibling work" if child.get("id")=="ii" else "retained shared volume context/index; relevant metadata/credit used in header and notices"))
    accounting = dict(contract="ocd-gregory-the-great-pastoral-rule-and-epistles-complete-accountability-v1",work_id=WORK_ID,source_sha256=SOURCE_SHA,source_bytes=len(source),
        represented_source_elements=7669,source_title_heads=356,epistle_count=273,book_count=8,book_epistle_counts=[52,30,34,32,31,45,28,21],pastoral_parts=4,pastoral_chapters=64,note_count=506,page_count=273,source_reference_tag_count=721,neutral_letter_reference_count=12,rtl_count=0,
        historical_ordinal_offset=42657,full_envelope_accounted=True,unexplained_omissions=0,source_header=dict(elements=sum(1 for n in doc.find("ThML.head").iter() if isinstance(n.tag,str)),sha256=sha256(etree.tostring(doc.find("ThML.head"),method="c14n")).hexdigest(),destination="retained metadata/permission context; source-attested claims in header and visible notice"),outside_work=outside,
        shell_disposition="Complete unchanged raw XML retains document shell, stylesheet declarations, comments, root/body carriers and their text/tails; only declared iii subtree is the accepted intellectual-work selection.")
    asset = Path("raw/ccel/npnf2/npnf212/files/fig1.png")
    image = doc.xpath('//*[@id="iii.iii-p86.1"]')[0]
    if sha256((ROOT/asset).read_bytes()).hexdigest() != "a06e1fa626deadbfa78c1390ccd63408b7eea2a720c5b4542eda9e999cc616b5":
        raise ValueError("retained diagram asset differs")
    accounting["source_media"] = [dict(source_id=image.get("id"),source_selector="ThML.body/div1[@id='iii']/div2[@id='iii.iii']/p[@id='iii.iii-p86']/img[@id='iii.iii-p86.1']",source_uri=image.get("src"),source_alt=image.get("alt"),retained_path=asset.as_posix(),bytes=len((ROOT/asset).read_bytes()),sha256=sha256((ROOT/asset).read_bytes()).hexdigest(),historical_snapshot_bytes="unknown",candidate_carrier="source-derived figure with exact graphic URI and figure description",presentation="hash-bound retained PNG displayed and identified as pedigree; full image textual collation and offline embedded image rendering not claimed")]
    questions = [dict(id=WORK_ID+"-"+key,status="unresolved",kind=key,detail=text) for key,text in (("human","Historical bounded visual review is retained evidence, not current human textual/visual acceptance."),("print","Physical edition equivalence and full print collation remain unassessed."),("rights","Provider Public Domain and CCEL formatting permission are retained evidence, not independent rights clearance."),("publication","No public publication authorization or action."))]
    profile = dict(work_id=WORK_ID,source_sha256=SOURCE_SHA,scope=SCOPE,historical_ordinal_offset=42657,credits=credits,
        header_xml=etree.tostring(header,encoding="unicode"),accounting=accounting,questions=questions,
        historical_reuse="Historical whole fifteen-work package is not current one-work promotion proof; selected body replays exactly. Old 37a-30 mechanical/visual receipts remain bounded historical evidence. Shared source profile/manifest/mapper/oracle left unchanged. The complete source iii composite editorial selection remains in one TEI; omitted original compositions are not restored or acquired.",review_patterns=["RP-01","RP-03","RP-04","RP-06","RP-11","RP-13","RP-14"])
    put(BASE/"profile.json",canonical(profile))
    put(BASE/"validation-policy.json",canonical(dict(scope=SCOPE,rules=["independent whole native source/TEI structure and every attribute/text/tail/order check","independent source ledgers and outside-envelope dispositions","stdlib/lxml source corroboration","historical body identity and all 1835 italic IDs","P5","fresh process replay and meaningful mutations"],shared_assumptions="Readonly declarative LIB048 mapping and XML parsing; source cross-parser fingerprint and historical independent source mapping corroborate.")))
    notice = ("# Gregory Pastoral Rule and Selected Epistles: source and data credit\n\nSourced via [CCEL.org](https://www.ccel.org/ccel/schaff/npnf212.html), Nicene and Post-Nicene Fathers, Second Series, volume XII. The retained Gregory title page credits Rev. James Barmby, D.D., with translation, introduction, notes and indices. His Prefatory Note explains the selection and specimen policy for letters, acknowledges H. R. Bramley's earlier translation while calling the present one original, and identifies the appended Merovingian pedigree. The electronic DC header names Philip Schaff as editor. These source-local roles do not assign editorial context to Gregory's original authorship.\n\n"
        "The retained shared title page names T&T Clark, Edinburgh, and Wm. B. Eerdmans Publishing Company, Grand Rapids, Michigan. Its printSourceInfo publication field is empty. The inherited catalog edition title remains unchanged, but its 1895 date is not asserted as newly verified primary-source metadata. The electronic header states Public Domain, identifies Christian Classics Ethereal Library as publisher, and supplies a Proofed subject marker; these statements do not establish independent rights clearance or print equivalence.\n\n"
        "Retained CCEL permission permits parsing ThML/XML for text, reserves CCEL file/formatting rights and restricts selling CCEL files or derivatives of their formatting. Credit CCEL when publishing. The [Pedigree of Kings of Gaul diagram](https://ccel.org/ccel/schaff/npnf212/files/fig1.png) is separately retained and acquisition-bound; the image is supplemental current source evidence and historical snapshot bytes remain unknown. Its source URI, label and placement are preserved. Image-byte retention and reference conservation are distinct from full visual collation or embedding pixels in offline JSON.\n\n"+SCOPE+
        "\n\nHuman textual/visual acceptance, print collation, rights clearance and publication remain separate. Carry visible credit to `"+DATA_NOTICE.as_posix()+"`.\n")
    put(BASE/"README.source.md",notice.encode())
    authorities = [("retained-diagram","raw/ccel/npnf2/npnf212/files/fig1.png","supplemental-source-media"),("diagram-acquisition-receipt","plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-10-structural-audit/14-gregory-asset-acquisition.json","historical-source-media-receipt"),("aggregate-validation-policy","sources/structured-text/npnf2-lib048/npnf2-lib048.validation-policy.json","readonly-declarative-mapping-policy"),("retained-text",SOURCE,"primary-source"),("profile",BASE/"profile.json","complete-source-feature-profile"),("validation-policy",BASE/"validation-policy.json","independent-validation-policy"),("source-readme",BASE/"README.source.md","source-attribution"),("historical-selected-body",HISTORICAL,"checked-historical-body"),("historical-source-check","reports/_logs/gregory-pastoral-epistles-reconciliation-20261001-v1/historical-body-extraction-and-replay.json","independent-source-corroboration"),("historical-replay","reports/_logs/gregory-pastoral-epistles-reconciliation-20261001-v1/historical-body-extraction-and-replay.json","historical-body-replay"),("legacy-mapper","build/tei/npnf2_lib048_reconstruction.py","readonly-mapping-support"),("legacy-checker","build/tei/npnf2_lib048_oracle.py","independent-checker-support"),("canonical-acquisition",ACQUISITION,"retained-source-identity"),("ccel-permission","docs/sources/ccel-permission.md","permission-evidence"),("tei-p5-xsd","ocd_kernel/tei/vendor/xsd/tei_all.xsd","tei-validation-schema"),("candidate-package-schema","ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","candidate-package-schema")]
    manifest = dict(contract="ocd-source-manifest-v1",source_id="gregory-the-great-pastoral-rule-and-epistles-npnf212-complete-v1",work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=[binding(*a) for a in authorities],
        converter=dict(id=producer.CONVERTER_ID,version=producer.CONVERTER_VERSION,callable="_convert",implementation_path="build/tei/gregory_pastoral_epistles_reconstruction.py",implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),
        validator=dict(id=checker.ORACLE_ID,version=checker.ORACLE_VERSION,callable="_oracle",implementation_path="build/tei/gregory_pastoral_epistles_oracle.py",implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),
        package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",sha256=sha256((ROOT/"ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()).hexdigest()))
    put(BASE/"source-manifest.json",canonical(manifest))
    print(json.dumps(dict(status="prepared",source_sha256=SOURCE_SHA,source_elements=7669,epistles=273,books=8,book_epistle_counts=[52,30,34,32,31,45,28,21],pastoral_parts=4,pastoral_chapters=64,body_preserved=True)))


if __name__=="__main__":
    main()
