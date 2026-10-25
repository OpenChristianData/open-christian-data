"""Bind the previously acquired Ludewic reply and its literal quoted boundaries."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import ludewic_reconstruction as producer
from build.tei import ludewic_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT=Path(__file__).resolve().parents[2]
BASE=Path("sources/manifest-acquisitions/ludewic-bsb829")
WORK_ID=producer.WORK_ID
FORM_ID=WORK_ID+"-openmgh-retained"
EDITION_ID=WORK_ID+"-openmgh-electronic"
ACQUISITION_ID=WORK_ID+"-openmgh-acquired"
WORK=Path("library/works")/WORK_ID
EDITION=WORK/"forms"/FORM_ID/"editions"/EDITION_ID
ACQUISITION=EDITION/"acquisitions"/(ACQUISITION_ID+".json")
canonical=producer.canonical
SCOPE="Complete literal quoted Ludewic reply in retained openMGH bsb00000829 volume division4 sole ab children107:483, from bsb00000829_00295_29 through complete closing tail at bsb00000829_00299_46. Preceding introduction0:15, separate Walram letter15:90 and response narrative/attribution90:107 excluded/accounted; all four acquired association locators remain unchanged. All original body tags, attributes, texts, tails and word links retained, including nine empty native word carriers; no inferred filling. Source context supports Count Ludewic as sender and Herrand of Halberstadt as dictator. One complete electronic source-defined reply, one TEI. Human/visual/print review, rights and publication unassessed."

def put(path,payload):
    target=io_path(ROOT/path); target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(payload)

def binding(name,path,role):
    payload=io_path(ROOT/path).read_bytes()
    return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(payload),sha256=sha256(payload).hexdigest())

def main():
    roster=json.loads((ROOT/"plans/2026-09-22-source-preflight/whole-library-handoff-inventory-20260926.json").read_bytes())
    matches=[w for w in roster["works"] if w["work_id"]==WORK_ID]
    if len(matches)!=1 or not any(e["edition_id"]==EDITION_ID for e in matches[0]["editions"]): raise ValueError("fixed755 declared edition missing")
    acquisition=validate_acquisition(io_path(ROOT/ACQUISITION),root=ROOT)
    raw=(ROOT/producer.SOURCE).read_bytes()
    if sha256(raw).hexdigest()!=producer.SOURCE_SHA or acquisition["source_path"]!=producer.SOURCE or acquisition["source_sha256"]!=producer.SOURCE_SHA: raise ValueError("acquisition source drift")
    original=etree.fromstring(raw); divs=list(original.find(producer.TEI+"text/"+producer.TEI+"body")[0]); ab=divs[3][0]
    boundary=dict(contract="ocd-ludewic-source-boundary-v1",scope=SCOPE,source_sha256=producer.SOURCE_SHA,division_ordinal=4,division_attributes=dict(divs[3].attrib),carrier_child_count=len(ab),selected_indexes_inclusive=[107,482],opening=ab[107].tail,closing=ab[482].tail,before=ab[106].tail,separate_walram_closing=ab[89].text,original_declared_locator=acquisition["source_scope"],prior_hold="The September26 remainder handoff left narrative/letter assignment unresolved. Direct quoted salutation and full closing define the exclusive complete response; acquisition associations unchanged.",initial_page_context="The preceding native pb bsb00000829_00295 n287 lies outside the selected response; four later native pb markers remain inside. No page marker synthesized.")
    creator_context={"sender":dict(name="Count Ludewic",role="sender",source_id="bsb00000829_00295_29",literal=ab[107].tail),"dictator":dict(name="Herrand of Halberstadt",role="dictator",source_ids=["bsb00000829_00295_17","bsb00000829_00295_23"],literals=[ab[91].tail,ab[97].tail])}
    put(BASE/"boundary-review.json",canonical(boundary))
    questions=[dict(id="ludewic-"+slug,status="unresolved",scope="complete retained quoted electronic letter",evidence=text) for slug,text in [("human-print-rights","Human/visual review, print equivalence, rights clearance and publication remain separate."),("empty-native-words","Nine native word carriers w5041/w5042, w5051/w5052, w5077/w5078, w5090 and w5093/w5094 have no text; original lemma and corresp remain exact. No reading guessed or inserted."),("shared-narrative","Surrounding narrative remains outside the literal reply; source context supports Ludewic sender and Herrand dictator; shared collection title and volume metadata retained as source context.")]]
    profile=dict(contract="ocd-ludewic-profile-v1",work_id=WORK_ID,work_title=producer.TITLE,scope=SCOPE,source_sha256=producer.SOURCE_SHA,boundary=boundary,creator_context=creator_context,candidate_questions=questions,
                 independence="Producer uses lxml and copies literal native children. Checker independently selects and traverses original source with stdlib ElementTree; directly checks every original tag/attribute/text/tail/hierarchy and reference closure. Whole-source stdlib/lxml tree correspondence corroborates parser behavior; no producer imports in checker. Prior source exposure and format agreement disclosed; not blind review.",source_header=etree.tostring(original.find(producer.TEI+"teiHeader"),encoding="unicode"))
    put(BASE/"profile.json",canonical(profile))
    policy=dict(contract="ocd-ludewic-policy-v1",scope=SCOPE,direct_native_attributes=True,empty_native_words="preserve literal empty text, lemma and corresp; reject filling",boundary="source quoted response salutation through full closing at end of native carrier; preceding attribution remains context",parser_independence="stdlib source selection/check versus lxml producer; full-volume parse corroboration",not_asserted=["human verification","visual review","print equivalence","rights clearance","publication"])
    put(BASE/"validation-policy.json",canonical(policy))
    notice=("# Count Ludewic reply to Walram retained source\n\nSource: Monumenta Germaniae Historica (MGH) and Bavarian State Library, Munich (BSB), retained openMGH electronic MGH Ldl2, bsb00000829. The complete quoted Ludewic reply is selected from flat division4 ab children107:483; surrounding narrative and Walram's letter remain excluded. Full literal source attributes and mixed content are preserved, including nine empty native word carriers. No reading is invented.\n\nThe electronic header licenses MGH/BSB annotations under CC BY4.0, does not claim rights in the underlying text, and requests credit to MGH and BSB on copies or derivatives. Carry this human-visible source/license credit to `data/structured-text/ludewic-reply-to-walram/README.md`. Technical completion does not establish human review, print equivalence, rights clearance or publication authority.\n\n## Source sender and dictator context\n\n"+"\n\n".join(creator_context["dictator"]["literals"])+"\n\n## Retained volume header\n\n"+profile["source_header"]+"\n").encode()
    put(BASE/"README.source.md",notice)
    paths=[("retained-source",producer.SOURCE,"primary-source"),("profile",BASE/"profile.json","complete-source-feature-profile"),("validation-policy",BASE/"validation-policy.json","independent-validation-policy"),("source-readme",BASE/"README.source.md","source-attribution-readme"),("boundary-review",BASE/"boundary-review.json","literal-boundary-evidence"),("canonical-acquisition",ACQUISITION,"canonical-acquisition-evidence"),("root-boundary-preflight",WORK/"integration/source-boundary-preflight-20261001/source-boundary.json","retained-root-preflight"),("root-preflight-readme",WORK/"integration/source-boundary-preflight-20261001/README.md","retained-root-preflight-readme"),("retained-receipt","raw/openmgh/bsb00000829/acquisition-receipt.json","retained-acquisition-receipt"),("previous-boundary-hold","plans/2026-09-22-source-preflight/openmgh-bsb829-remainder-flat-boundaries-20260926.json","prior-locator-evidence"),("tei-p5-xsd","ocd_kernel/tei/vendor/xsd/tei_all.xsd","tei-validation-schema"),("candidate-package-schema","ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","candidate-package-schema")]
    manifest=dict(contract="ocd-source-manifest-v1",source_id="ludewic-bsb829-quoted-v1",work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,authorities=[binding(*p) for p in paths],scope=dict(kind="complete-quoted-letter",root="volume division4 ab children107:483"),converter=dict(id=producer.CONVERTER_ID,version=producer.CONVERTER_VERSION,callable="_convert",implementation_path=Path(producer.__file__).relative_to(ROOT).as_posix(),implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),validator=dict(id=checker.ORACLE_ID,version=checker.ORACLE_VERSION,callable="_oracle",implementation_path=Path(checker.__file__).relative_to(ROOT).as_posix(),implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha()),package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",sha256=sha256((ROOT/"ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()).hexdigest()))
    put(BASE/"source-manifest.json",canonical(manifest))
    print(json.dumps(dict(status="prepared",acquisition_sha256=sha256(io_path(ROOT/ACQUISITION).read_bytes()).hexdigest(),boundary=boundary)))

if __name__=="__main__":main()
