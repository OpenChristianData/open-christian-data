"""Bind only the second complete Georgius epitaph in its retained triplex collection."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import georgii_aliud_reconstruction as producer
from build.tei import georgii_aliud_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT=Path(__file__).resolve().parents[2]
BASE=Path("sources/manifest-acquisitions/georgii-aliud-bsb720")
WORK_ID=producer.WORK_ID
FORM_ID=WORK_ID+"-openmgh-retained"
EDITION_ID=WORK_ID+"-openmgh-electronic"
ACQUISITION_ID=WORK_ID+"-openmgh-acquired"
WORK=Path("library/works")/WORK_ID
EDITION=WORK/"forms"/FORM_ID/"editions"/EDITION_ID
ACQUISITION=EDITION/"acquisitions"/(ACQUISITION_ID+".json")
canonical=producer.canonical
SCOPE="Complete second independent six-line Georgius epitaph, literal ALIUD, from retained bsb00000720 Carmina div3 ab children96:104. Native heading lb bsb00000720_00271_17, six verse-line lbs through bsb00000720_00272_4, internal pb bsb00000720_00272 preserved exactly. Shared group18 EPITAPHIUM SENIORIS GEORGII TRIPLEX heading at89 is context; first poem90:96 and third TERTIUM poem104:111 remain outside this body, as does numbered19 onward. One complete independent poem from a three-poem collection, not the whole triplex; qualified header/title and context retained. All native tags, attrs, text and tails conserved. Native column markers counted explicitly (none in selected span). Human/visual/print review, rights and publication unassessed."
TITLE=producer.TITLE
ORIGINAL_TITLE="EPITAPHIUM SENIORIS GEORGII TRIPLEX — ALIUD"

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
    original=etree.fromstring(raw); divs=list(original.find(producer.TEI+"text/"+producer.TEI+"body")[0]); ab=divs[2][0]
    boundary=dict(contract="ocd-georgii-aliud-source-boundary-v1",scope=SCOPE,source_sha256=producer.SOURCE_SHA,division_ordinal=3,division_attributes=dict(divs[2].attrib),carrier_child_count=len(ab),selected_indexes_inclusive=[96,103],opening_heading=ab[96].tail,first_verse=ab[97].tail,closing=ab[103].tail,preceding_first_closing=ab[95].tail,following_third_heading=ab[104].tail,next_numbered_heading=ab[111].tail,original_declared_locator=acquisition["source_scope"],internal_page=dict(source_id=ab[99].get(producer.XML_ID),attributes=dict(ab[99].attrib)),title_change=dict(field="title",before=ORIGINAL_TITLE,after=TITLE,evidence="Source ALIUD and complete six-line second poem under literal group18 triplex heading; root authorized precise source-backed one-field display title"))
    put(BASE/"boundary-review.json",canonical(boundary))
    collection_context=dict(source_id="bsb00000720_00271_10",literal=ab[89].tail,cardinality="Three independent complete six-line epitaphs; this candidate represents second ALIUD poem only")
    authorship_context=dict(source_ids=["bsb00000720_00267_1","bsb00000720_00267_2"],literals=[ab[1].tail,ab[2].tail])
    questions=[dict(id="georgii-aliud-human-print-rights",status="unresolved",scope="complete retained second electronic epitaph",evidence="Human/visual review, print equivalence, rights clearance and publication remain separate.")]
    profile=dict(contract="ocd-georgii-aliud-profile-v1",work_id=WORK_ID,work_title=TITLE,original_work_title=ORIGINAL_TITLE,scope=SCOPE,source_sha256=producer.SOURCE_SHA,boundary=boundary,collection_context=collection_context,authorship_context=authorship_context,candidate_questions=questions,
                 independence="Producer uses lxml literal native-node copies; independent checker selects/traverses stdlib source directly and compares every tag/attribute/text/tail/hierarchy, native page/column/verse inventory and original header. Whole-volume stdlib/lxml correspondence corroborates parsing. Prior exposure and agreed ledger format disclosed; no checker producer imports; not blind review.",source_header=etree.tostring(original.find(producer.TEI+"teiHeader"),encoding="unicode"))
    put(BASE/"profile.json",canonical(profile))
    policy=dict(contract="ocd-georgii-aliud-policy-v1",scope=SCOPE,direct_native_attributes=True,cardinality="one independent complete second epitaph; shared triplex is three-poem context",boundary="ALIUD heading through complete sixth line, preserving internal page; stop before TERTIUM",not_asserted=["whole triplex represented","human verification","visual review","print equivalence","rights clearance","publication"])
    put(BASE/"validation-policy.json",canonical(policy))
    notice=("# Second Epitaph for Georgius, from Epitaphium senioris Georgii triplex\n\nSource: Monumenta Germaniae Historica (MGH) and Bavarian State Library, Munich (BSB), retained openMGH MGH SS rer. Germ.73, bsb00000720. Complete second six-line epitaph with literal ALIUD heading, Carmina ab children96:104. Native internal page break remains intact; no lines or column markers invented. Shared triplex heading is context; other epitaphs are excluded. This is one independent complete poem, not the whole triplex.\n\nThe electronic header licenses MGH/BSB annotations under CC BY4.0, does not claim rights in the underlying text, and requests MGH and BSB credit on copies or derivatives. Carry human-visible source/license attribution to `data/structured-text/lambertus-epitaphium-georgii-aliud/README.md`. Human review, print equivalence, rights clearance and publication remain separate.\n\n## Literal collection and author context\n\n"+collection_context["literal"]+"\n"+"".join(authorship_context["literals"])+"\n\n## Retained volume header\n\n"+profile["source_header"]+"\n").encode()
    put(BASE/"README.source.md",notice)
    paths=[("retained-source",producer.SOURCE,"primary-source"),("profile",BASE/"profile.json","complete-source-feature-profile"),("validation-policy",BASE/"validation-policy.json","independent-validation-policy"),("source-readme",BASE/"README.source.md","source-attribution-readme"),("boundary-review",BASE/"boundary-review.json","literal-boundary-evidence"),("canonical-acquisition",ACQUISITION,"canonical-acquisition-evidence"),("retained-receipt","raw/openmgh/bsb00000720/acquisition-receipt.json","retained-acquisition-receipt"),("previous-boundary-hold","plans/2026-09-22-source-preflight/openmgh-bsb720-remaining-nine-holds-20260927.json","prior-locator-evidence"),("tei-p5-xsd","ocd_kernel/tei/vendor/xsd/tei_all.xsd","tei-validation-schema"),("candidate-package-schema","ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","candidate-package-schema")]
    manifest=dict(contract="ocd-source-manifest-v1",source_id="georgii-aliud-bsb720-quoted-v1",work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,authorities=[binding(*p) for p in paths],scope=dict(kind="complete-second-epitaph",root="Carmina div3 ab children96:104"),converter=dict(id=producer.CONVERTER_ID,version=producer.CONVERTER_VERSION,callable="_convert",implementation_path=Path(producer.__file__).relative_to(ROOT).as_posix(),implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),validator=dict(id=checker.ORACLE_ID,version=checker.ORACLE_VERSION,callable="_oracle",implementation_path=Path(checker.__file__).relative_to(ROOT).as_posix(),implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha()),package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",sha256=sha256((ROOT/"ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()).hexdigest()))
    put(BASE/"source-manifest.json",canonical(manifest))
    print(json.dumps(dict(status="prepared",acquisition_sha256=sha256(io_path(ROOT/ACQUISITION).read_bytes()).hexdigest(),boundary=boundary)))

if __name__=="__main__":main()
