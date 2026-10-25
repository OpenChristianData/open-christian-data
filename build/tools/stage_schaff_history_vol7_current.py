"""Stage evidence-backed acceptance of the complete retained Schaff History volume VII work."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil

from build.tei.schaff_history_vol7_current_oracle import _oracle, check
from build.tools.prepare_schaff_history_vol7_current import canonical
from ocd_kernel.reconstruction.contract import SourceManifest, CandidatePackage
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update, cached_edition_lookups
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import (build_acceptance_record, make_file_binding,
                                      validate_acceptance, write_acceptance, PROMOTED_MASTER_REASON)
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.install_accepted import _files

from build.tools.prepare_schaff_history_vol7_current import ROOT,WORK_ID,FORM_ID,EDITION_ID,ACQUISITION_ID,WORK,EDITION,ACQUISITION,BASE
EVIDENCE=WORK/'integration/ccel-schaff-history-vol7-v1'
from build.tools.prepare_schaff_history_vol7_current import SCOPE, TITLE


def put(stage: Path, relative: Path, payload: bytes) -> Path:
    p = stage / relative
    io_path(p).parent.mkdir(parents=True, exist_ok=True)
    io_path(p).write_bytes(payload)
    return p


def put_json(stage: Path, relative: Path, record: object) -> Path:
    return put(stage, relative, canonical(record))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("stage", "promoted", "candidate", "replay", "mutations"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    schema_paths = [Path("schemas/v2") / name for name in ("native-content.schema.json", "release-selection.schema.json", "release-report.schema.json", "public-row.schema.json", "projection-receipt.schema.json", "categories/prose.schema.json")]
    schema_pins = {p.as_posix(): sha256((ROOT / p).read_bytes()).hexdigest() for p in schema_paths}
    stage = args.stage.absolute()
    if stage.exists() or args.promoted.exists():
        raise FileExistsError("fresh stage and promotion roots are required")
    for target in (stage,args.promoted.absolute()):
        if target.parent.resolve(strict=True) != Path("D:/Library/Open Christian Data/candidate-reviews").resolve(strict=True) or not target.name.startswith("schaff-history-vol7-"):
            raise ValueError("bounded Schaff History volume VII candidate-review root required")
    manifest = SourceManifest.load(ROOT/BASE/"source-manifest.json",repository_root=ROOT)
    package = CandidatePackage.load(args.candidate/"package")
    replay = CandidatePackage.load(args.replay/"package")
    if package.sha256 != replay.sha256 or any(package.member_bytes(n) != replay.member_bytes(n) for n in package.member_names):
        raise ValueError("fresh-process candidate replay differs")
    validation = json.loads((args.candidate/"validation.json").read_bytes())
    replay_validation = json.loads((args.replay/"validation.json").read_bytes())
    if validation != replay_validation or validation["status"] != "pass":
        raise ValueError("fresh-process validation replay differs")
    oracle = _oracle(manifest, package)
    source_facts = check(manifest, package.member_bytes("content.tei.xml"))
    if oracle["status"] != "pass":
        raise ValueError(oracle["findings"])
    mutations = json.loads((args.mutations/"result.json").read_bytes())
    if (mutations["status"] != "pass" or len(mutations["cases"]) != 29
            or any(c["status"] != "rejected" for c in mutations["cases"])
            or mutations["candidate_sha256"] != package.sha256
            or mutations["replay_sha256"] != replay.sha256
            or mutations["baseline"] != source_facts):
        raise ValueError("mutation proof is incomplete")
    before = _files(ROOT/WORK)
    if any(Path(p).name in {"acceptance.json", "master.tei.xml"} for p in before):
        raise ValueError("canonical edition already has acceptance/master")
    for relative in before:
        put(stage,WORK/relative,io_path(ROOT/WORK/relative).read_bytes())
    acquisition = validate_acquisition(io_path(ROOT/ACQUISITION),root=ROOT)
    for member in acquisition["retained_files"]:
        put(stage,Path(member["path"]),io_path(ROOT/member["path"]).read_bytes())
    original_state = json.loads(io_path(ROOT/WORK/"state.json").read_bytes())
    for target in original_state["targets"]:
        for path in target["evidence"]:
            put(stage,Path(path),io_path(ROOT/path).read_bytes())
    original_work = load_work(ROOT/WORK/"work.json")
    revised = json.loads(canonical(original_work))
    if original_work["title"] != TITLE or original_work["textual_forms"][0]["language"] != "en":
        raise ValueError("Schaff History volume VII identity/language preimage differs")
    revised["textual_forms"][0]["editions"][0].update(category="prose")
    validate_identity_update(original_work,revised)
    put_json(stage,WORK/"work.json",revised)
    notice = (ROOT/BASE/"README.source.md").read_bytes()
    put(stage,WORK/"SOURCE_CREDIT.md",notice)
    for name in package.member_names:
        put(stage,EVIDENCE/"original-package"/name,package.member_bytes(name))
    put_json(stage,EVIDENCE/"source-manifest.json",json.loads(manifest.path.read_bytes()))
    put_json(stage,EVIDENCE/"original-validation.json",validation)
    put_json(stage,EVIDENCE/"mutations.json",mutations)
    identity = dict(work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID)
    source = {key:acquisition[key] for key in ("source_path","source_sha256","source_bytes","source_scope")}
    revision = dict(id='schaff-history-vol-7-ccel-electronic-v1',date='2026-10-01',note='Technical acceptance of the complete retained Schaff volume VII, all opening context, integral preface, nine chapters and four integral indexes; complete native body and source-projection evidence, renewed literal electronic credits.')
    raw_candidate = package.member_bytes("content.tei.xml")
    bound = bind_reviewed_header(raw_candidate,expected_sha256=sha256(raw_candidate).hexdigest(),identity=identity,
                                source=source,source_url=acquisition["url"],declared_scope=SCOPE,revision=revision)
    replay_bound = bind_reviewed_header(replay.member_bytes("content.tei.xml"),expected_sha256=sha256(raw_candidate).hexdigest(),identity=identity,
                                       source=source,source_url=acquisition["url"],declared_scope=SCOPE,revision=revision)
    if bound != replay_bound or bound.split(b"</teiHeader>",1)[1] != raw_candidate.split(b"</teiHeader>",1)[1]:
        raise ValueError("acceptance header changed reviewed text or failed deterministic replay")
    candidate = put(stage,EVIDENCE/"candidate.tei.xml",bound)
    if failures := validate_file(io_path(candidate)):
        raise ValueError(f"bound candidate P5 failures: {failures}")
    expected = [dict(path=m["path"],position=i) for i,m in enumerate(acquisition["retained_files"],1)]
    included = [dict(path=m["path"],position=i,bytes=m["bytes"],sha256=m["sha256"],scope=SCOPE if m["path"]==source["source_path"] else "Unexpected supplemental source member; this route declares exactly the retained XML") for i,m in enumerate(acquisition["retained_files"],1)]
    excluded = []
    scope = dict(kind="selection",declared=SCOPE,expected_members=expected,included_members=included,excluded_members=excluded)
    common = dict(identity=identity,source=source,candidate=make_file_binding(stage,candidate),
                  accepted_scope=dict(kind="selection",declared=SCOPE),expected_members=expected,included_members=included,excluded_members=excluded,
                  missing_members=[],unknown_members=[])
    accounting = put_json(stage,EVIDENCE/"source-accounting.json",common|dict(scope=acquisition["source_scope"],source_sha256=source["source_sha256"],source_bytes=source["source_bytes"], source_oracle=oracle,source_facts=source_facts,source_accountability=json.loads(package.member_bytes("source-accountability.json"))))
    command = "py -3 -m build.tools.stage_schaff_history_vol7_current --stage <fresh-stage> --promoted <fresh-promotion> --candidate <current-candidate> --replay <fresh-replay> --mutations <mutation-proof>"
    technical = dict(producer=dict(id="ocd-schaff-history-vol7-complete-retained-v1"),checker=dict(id=oracle["oracle_id"]),
        shared_assumptions=["Read-only proven family mapping and separate source oracle adapted for the complete HCC7 source. XML parsing is shared; source-derived IDs and all native text/parents/attributes preserved. Prior exposure disclosed; no blind claim."],
        independent_corroboration="Independent whole selected native tree, every mapped attribute/text/tail/heading/attachment and source ledger; independent complete source-header/body/standOff inventories; complete native reconstruction; twenty-nine meaningful mutations and fresh-process replay.")
    evidence = dict(source_oracle=oracle,validation=validation,mutation_cases=mutations["cases"],replay=dict(status="pass",candidate_sha256=package.sha256,validation_equal=True,bound_candidate_sha256=sha256(bound).hexdigest()),tei_p5="pass",text_subtree_byte_identical=True)
    for name in ("validation","accounting","fidelity","reproducibility","schema","closure"):
        path = put_json(stage,EVIDENCE/(name+".json"),common|dict(scope=SCOPE,status="pass",command=command,exit_code=0,claim=name,**evidence))
        technical[name] = dict(path=path,status="pass",command=command,exit_code=0)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    review = dict(reviewer="agent:schaff-history-vol-7-source-check",reviewed_at=now,
                  coverage=dict(status="partial",declared=SCOPE,reached=["complete retained-source native tree and envelope accounting","complete native volume, nine chapters, four integral indexes, 1,012 notes and 780 literal language attributes including index carriers, full source header and source-projection evidence"],
                                inspected=["complete retained-source native tree and envelope accounting"],unreviewed=["current exact-pair visual comparison","print collation"]),
                  source_quality_uncertainty=["Whole electronic volume/source envelope faithfully represented; no independent print collation, page-image retention or worldwide rights claim.","Electronic edition not collated to print."],
                  discrepancies=[],unreviewed_residuals=["Human verification, visual comparison, print equivalence and jurisdictional rights remain unassessed."])
    review_path = put_json(stage,EVIDENCE/"review.json",common|review|dict(scope=SCOPE))
    decision = dict(source_local_disposition="Technical agent acceptance of the complete retained Schaff History volume VII work.",blockers=[],human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted",actor=review["reviewer"],assessed_at=now,supported_scope=SCOPE,unresolved_claims=[],
                                          unassessed_stronger_claims=["visual comparison","human verification","print equivalence","rights clearance","publication"]))
    acceptance = stage/EDITION/"acceptance.json"
    record = build_acceptance_record(stage,identity=identity,candidate_path=candidate,source_accounting_path=accounting,scope=scope,
                                     technical=technical,review=review|dict(report_path=review_path),representation_revision=revision,decision=decision)
    write_acceptance(io_path(acceptance),record)
    validate_acceptance(acceptance,root=stage)
    # The generic temporary promoter uses ordinary os.lstat/copy operations,
    # which cannot inspect these edition paths beyond MAX_PATH on Windows.
    # Follow the existing work-specific staged promotion route, using shared
    # record writers/validators; canonical adoption still uses the guarded installer.
    promoted_root = args.promoted.absolute()
    shutil.copytree(io_path(stage),io_path(promoted_root))
    promoted_acceptance = promoted_root/EDITION/"acceptance.json"
    master = put(promoted_root,EDITION/"master.tei.xml",bound)
    record["promotion"].update(status="promoted",promoted_at=now,master=make_file_binding(promoted_root,master))
    write_acceptance(io_path(promoted_acceptance),record)
    promoted_state = json.loads(canonical(original_state))
    edition_target = next(t for t in promoted_state["targets"] if t["target_id"] == EDITION_ID and t["target_type"] == "edition")
    edition_target.update(stage="accepted",reason=PROMOTED_MASTER_REASON,updated_at=now)
    for path in [(EDITION/"master.tei.xml").as_posix(),(EDITION/"acceptance.json").as_posix()]:
        if path not in edition_target["evidence"]:
            edition_target["evidence"].append(path)
    put_json(promoted_root,WORK/"state.json",promoted_state)
    validate_state(promoted_root/WORK/"state.json",root=promoted_root)
    with cached_edition_lookups():
        validate_acceptance(promoted_acceptance,root=promoted_root)
        projection = project_accepted_document(io_path(promoted_root),acceptance_path=io_path(promoted_acceptance),category="prose")
        errors = verify_accepted_document(io_path(promoted_root),acceptance_path=io_path(promoted_acceptance),rows=projection["rows"],receipt=projection["receipt"],category="prose")
    if errors or len(projection["rows"]) != 3:
        raise ValueError(f"actual-master projection differs: {errors}; rows={len(projection['rows'])}")
    if {p.as_posix(): sha256((ROOT / p).read_bytes()).hexdigest() for p in schema_paths} != schema_pins:
        raise ValueError("shared schema changed during staged projection")
    put_json(promoted_root,EVIDENCE/"stage-projection.json",projection)
    receipt = dict(status="pass",work_id=WORK_ID,source_sha256=source["source_sha256"],category="prose",language="en",
                   source_facts=source_facts,before=before,master_sha256=sha256(bound).hexdigest(),rows=len(projection["rows"]),
                   projection_errors=errors,stage_root=stage.as_posix(),promoted_root=promoted_root.as_posix(),
                   schema_pins=schema_pins,
                   promotion_route="work-specific long-path staged promotion; shared record/binding validators and guarded canonical installer")
    receipt["after"] = _files(promoted_root/WORK)
    put_json(promoted_root,Path("stage-receipt.json"),receipt)
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
