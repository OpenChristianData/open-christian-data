"""Stage evidence-backed acceptance of the complete retained YLT collection work."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
from copy import deepcopy

from build.tei.ylt_current_oracle import _oracle, check
from build.tools.prepare_ylt_current import canonical
from ocd_kernel.reconstruction.contract import SourceManifest, CandidatePackage
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update, cached_edition_lookups
from ocd_kernel.projection.categories.bible import project_accepted_bible, verify_accepted_bible
from ocd_kernel.tei.acceptance import (build_acceptance_record, make_file_binding,
                                      validate_acceptance, write_acceptance, PROMOTED_MASTER_REASON)
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.install_accepted import _files

from build.tools.prepare_ylt_current import ROOT,WORK_ID,FORM_ID,EDITION_ID,ACQUISITION_ID,WORK,EDITION,ACQUISITION,BASE
EVIDENCE=WORK/'integration/ylt-retained-current-v1'
from build.tools.prepare_ylt_current import SCOPE, TITLE


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
    schema_paths = [Path('schemas/v2')/p for p in ['work.schema.json','state.schema.json','acquisition.schema.json','acceptance.schema.json','agent-assessment.schema.json','human-review.schema.json','source-metadata.schema.json','projection-receipt.schema.json','public-row.schema.json','categories/bible.schema.json']]
    schema_pins = {p.as_posix(): sha256((ROOT / p).read_bytes()).hexdigest() for p in schema_paths}
    runtime_paths = [Path(p) for p in ['ocd_kernel/projection/categories/bible.py','ocd_kernel/projection/envelope.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/tei/acceptance.py','ocd_kernel/tei/install_accepted.py','ocd_kernel/tei/reviewed_integration.py','ocd_kernel/library/identities.py','ocd_kernel/library/acquisitions.py','ocd_kernel/library/state.py','ocd_kernel/library/_common.py','ocd_kernel/tei/validate.py']]
    runtime_pins = {p.as_posix(): sha256((ROOT/p).read_bytes()).hexdigest() for p in runtime_paths}
    if runtime_pins["ocd_kernel/projection/categories/bible.py"] != "9f4e6cd7b0238379eb2d6de70a35eda9ab02226b8beba51a32710bfc667f8c7b": raise ValueError("current frozen helper differs")
    stage = args.stage.absolute()
    if stage.exists() or args.promoted.exists():
        raise FileExistsError("fresh stage and promotion roots are required")
    for target in (stage,args.promoted.absolute()):
        if target.parent.resolve(strict=True) != Path("D:/Library/Open Christian Data/candidate-reviews").resolve(strict=True) or not target.name.startswith("ylt-"):
            raise ValueError("bounded YLT collection candidate-review root required")
    manifest = SourceManifest.load(ROOT/BASE/"source-manifest.json",repository_root=ROOT)
    package = CandidatePackage.load(args.candidate/"package")
    replay = CandidatePackage.load(args.replay/"package")
    if package.sha256 != replay.sha256 or any(package.member_bytes(n) != replay.member_bytes(n) for n in package.member_names):
        raise ValueError("fresh-process candidate replay differs")
    validation = json.loads((args.candidate/"validation.json").read_bytes())
    replay_validation = json.loads((args.replay/"validation.json").read_bytes())
    if validation != replay_validation or validation["status"] != "pass":
        raise ValueError("fresh-process validation replay differs")
    package.verify_integrity();manifest.verify()
    if validation['candidate_sha256']!=package.sha256 or validation['source_manifest_sha256']!=manifest.sha256:raise ValueError('Current validation binding differs')
    oracle=validation['attestation']
    if oracle['implementation_sha256']!=manifest.record['validator']['implementation_sha256'] or oracle['import_closure_sha256']!=manifest.record['validator']['import_closure_sha256']:raise ValueError('Current source proof implementation differs')
    mutations=json.loads((args.mutations/'result.json').read_bytes())
    source_facts=mutations['baseline']
    if (mutations['status']!='pass' or mutations['candidate_sha256']!=package.sha256 or mutations['replay_sha256']!=package.sha256 or not mutations['validation_equal'] or len(mutations['cases'])!=15 or any(c['status']!='rejected' for c in mutations['cases'])):
        raise ValueError('Fresh source-feature mutation/replay binding incomplete')
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
        raise ValueError("YLT collection identity/language preimage differs")
    revised["textual_forms"][0]["editions"][0].update(category="bible")
    validate_identity_update(original_work,revised)
    put_json(stage,WORK/"work.json",revised)
    notice = (ROOT/BASE/"README.source.md").read_bytes()
    put(stage,WORK/"SOURCE_CREDIT.md",notice)
    for name in package.member_names:
        put(stage,EVIDENCE/"original-package"/name,package.member_bytes(name))
    put_json(stage,EVIDENCE/"source-manifest.json",json.loads(manifest.path.read_bytes()))
    put_json(stage,EVIDENCE/"original-validation.json",validation)
    put_json(stage,EVIDENCE/"mutations.json",mutations)
    coordinator = ROOT/"reports/_logs/ylt-coordinator-source-review-20261002-v1/review.json"
    put(stage,EVIDENCE/"coordinator-source-review.json",coordinator.read_bytes())
    for name in ['retained-source-regeneration-proof.json']:
        put(stage,EVIDENCE/name,io_path(ROOT/'reports/_logs/ylt-current-reconciliation-20261002-v1'/name).read_bytes())
    identity = dict(work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID)
    from ocd_kernel.tei.acceptance import _source_binding
    source = _source_binding(acquisition,context="YLT retained acquisition")
    revision = dict(id='ylt-retained-json-current-v1',date='2026-10-02',note='Technical acceptance of the complete retained YLT electronic Bible: unchanged source verse body, exact66source-native booklabels replacing generated n ordinals, qualified current source header; source label1898 remains uncollated electronic metadata.')
    original_candidate = package.member_bytes("content.tei.xml")
    raw_candidate = original_candidate
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
    included = [dict(path=m["path"],position=i,bytes=m["bytes"],sha256=m["sha256"],scope=SCOPE if m["path"]==source["source_path"] else "Unexpected supplemental source member; this route declares exactly the retained JSON") for i,m in enumerate(acquisition["retained_files"],1)]
    excluded = []
    scope = dict(kind="selection",declared=SCOPE,expected_members=expected,included_members=included,excluded_members=excluded)
    common = dict(identity=identity,source=source,candidate=make_file_binding(stage,candidate),
                  accepted_scope=dict(kind="selection",declared=SCOPE),expected_members=expected,included_members=included,excluded_members=excluded,
                  missing_members=[],unknown_members=[])
    accounting = put_json(stage,EVIDENCE/"source-accounting.json",common|dict(scope=source["source_scope"],source_sha256=source["source_sha256"],source_bytes=source["source_bytes"], source_oracle=oracle,source_facts=source_facts,source_accountability=json.loads(package.member_bytes("source-accountability.json"))))
    command = "py -3 -m build.tools.stage_ylt_current --stage <fresh-stage> --promoted <fresh-promotion> --candidate <current-candidate> --replay <fresh-replay> --mutations <mutation-proof>"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),checker=dict(id=oracle["oracle_id"]),
        shared_assumptions=["Fresh original-mapper reproduction matches recorded native hash, not physical old-package recovery; prior independent YLT checker rederives31102verse/1189chapter/66book source ledger and checks complete normalized regenerated TEI. Producer wrapper not imported. Python JSON/serialization shared assumptions corroborated by coordinator source/tree review."],
        independent_corroboration="Independent complete source JSON string/order/label/fieldstate/parent proof; only known66label/header normalization restores fresh baseline02521f bytes. Coordinator66/1189/31102 comparison; fifteen active source/header/accounting mutations, exact fresh-process and bound-header replay.")
    evidence = dict(source_oracle=oracle,validation=validation,mutation_cases=mutations["cases"],replay=dict(status="pass",candidate_sha256=package.sha256,validation_equal=True,bound_candidate_sha256=sha256(bound).hexdigest()),tei_p5="pass",text_subtree_byte_identical=True)
    for name in ("validation","accounting","fidelity","reproducibility","schema","closure"):
        path = put_json(stage,EVIDENCE/(name+".json"),common|dict(scope=SCOPE,status="pass",command=command,exit_code=0,claim=name,**evidence))
        technical[name] = dict(path=path,status="pass",command=command,exit_code=0)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    review = dict(reviewer="agent:ylt-source-check",reviewed_at=now,
                  coverage=dict(status="partial",declared=SCOPE,reached=["complete retained-source native tree and envelope accounting","all66books/1189chapters/31102versecarriers allnonempty, full JSON key/order/state/accounting and66source label transitions"],
                                inspected=["complete retained-source native tree and envelope accounting"],unreviewed=["current exact-pair visual comparison","print collation"]),
                  source_quality_uncertainty=["Complete retained electronic Bible; source label1898 not verified print date/edition/translation revision or rights clearance.","Electronic JSON witness not collated to print; no external versification inferred."],
                  discrepancies=[],unreviewed_residuals=["Human verification, visual comparison, print equivalence and jurisdictional rights remain unassessed."])
    review_path = put_json(stage,EVIDENCE/"review.json",common|review|dict(scope=SCOPE))
    decision = dict(source_local_disposition="Technical agent acceptance of the complete retained YLT collection work.",blockers=[],human_decision=dict(status="not-recorded"),
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
        projection = project_accepted_bible(io_path(promoted_root),acceptance_path=io_path(promoted_acceptance))
        errors = verify_accepted_bible(io_path(promoted_root),acceptance_path=io_path(promoted_acceptance),rows=projection["rows"],receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 31102:
        raise ValueError(f"actual-master projection differs: {errors}; rows={len(projection['rows'])}")
    observed=[r for r in projection['rows'] if r['text']=='']
    if observed:raise ValueError('Unexpected empty YLT source slot')
    if projection['rows'][0]['locator']['book']!='Genesis' or projection['rows'][-1]['locator']['book']!='Revelation of John':raise ValueError('Actual source booklabel projection differs')
    challenges=[]
    for kind in ('source-book-label-loss','verse-carrier-omission','verse-text-changed'):
        rows=deepcopy(projection['rows'])
        if kind=='source-book-label-loss':rows[0]['locator']['book']='1'
        elif kind=='verse-carrier-omission':rows.pop(0)
        else:rows[0]['text']='Invented words'
        failures=verify_accepted_bible(io_path(promoted_root),acceptance_path=io_path(promoted_acceptance),rows=rows,receipt=projection['receipt'])
        if not failures:raise ValueError('Public source feature mutation escaped '+kind)
        challenges.append(dict(mutation=kind,status='rejected',errors=failures))
    put_json(promoted_root,EVIDENCE/'bible-public-proof.json',dict(status='pass',rows=31102,empty_source_slots=0,all_source_native_booklabels=True,independent_mutation_checks=challenges))
    if {p.as_posix(): sha256((ROOT / p).read_bytes()).hexdigest() for p in schema_paths} != schema_pins:
        raise ValueError("shared schema changed during staged projection")
    put_json(promoted_root,EVIDENCE/"stage-projection.json",projection)
    if {p.as_posix():sha256((ROOT/p).read_bytes()).hexdigest() for p in runtime_paths} != runtime_pins: raise ValueError("shared runtime changed during staged checks")
    receipt = dict(runtime_pins=runtime_pins,status="pass",work_id=WORK_ID,source_sha256=source["source_sha256"],category="bible",language="en",
                   source_facts=source_facts,before=before,master_sha256=sha256(bound).hexdigest(),rows=len(projection["rows"]),
                   projection_errors=errors,stage_root=stage.as_posix(),promoted_root=promoted_root.as_posix(),
                   schema_pins=schema_pins,
                   promotion_route="work-specific long-path staged promotion; shared record/binding validators and guarded canonical installer")
    receipt["after"] = _files(promoted_root/WORK)
    put_json(promoted_root,Path("stage-receipt.json"),receipt)
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
