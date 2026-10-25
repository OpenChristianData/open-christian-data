"""Stage evidence-backed acceptance of the complete retained BCP1549 complete electronic witness work."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil

from build.tei.bcp1549_current_oracle import _oracle
from build.tools.prepare_bcp1549_current import canonical
from ocd_kernel.reconstruction.contract import SourceManifest, CandidatePackage, _validation_authority_bindings, _runtime_binding
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update, cached_edition_lookups
from ocd_kernel.projection.categories.liturgies import project_accepted_liturgies, verify_accepted_liturgies
from ocd_kernel.tei.acceptance import (build_acceptance_record, make_file_binding,
                                      validate_acceptance, write_acceptance, PROMOTED_MASTER_REASON)
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.release.notices import notice_texts_for_item

from build.tools.prepare_bcp1549_current import ROOT,WORK_ID,FORM_ID,EDITION_ID,ACQUISITION_ID,WORK,EDITION_PATH as EDITION,ACQ as ACQUISITION,BASE
EVIDENCE=WORK/'integration/bcp1549-current-v1'
from build.tools.prepare_bcp1549_current import SCOPE, TITLE


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
    schema_paths = [Path("schemas/v2") / name for name in ("release-selection.schema.json", "release-report.schema.json", "public-row.schema.json", "projection-receipt.schema.json", "categories/liturgies.schema.json")]
    schema_paths.extend(Path(p) for p in ("ocd_kernel/projection/categories/liturgies.py","ocd_kernel/projection/categories/liturgies_bcp1549.py","ocd_kernel/projection/categories/liturgies_bcp1549_check.py","schemas/v2/native-content.schema.json","ocd_kernel/projection/native_content.py","ocd_kernel/projection/native_content_check.py"))
    schema_pins = {p.as_posix(): sha256((ROOT / p).read_bytes()).hexdigest() for p in schema_paths}
    stage = args.stage.absolute()
    if stage.exists() or args.promoted.exists():
        raise FileExistsError("fresh stage and promotion roots are required")
    for target in (stage,args.promoted.absolute()):
        if target.parent.resolve(strict=True) != Path("D:/Library/Open Christian Data/candidate-reviews").resolve(strict=True) or not target.name.startswith("bcp1549-current-"):
            raise ValueError("bounded BCP1549 complete electronic witness candidate-review root required")
    manifest = SourceManifest.load(ROOT/BASE/"source-manifest.json",repository_root=ROOT)
    manifest.verify()
    package = CandidatePackage.load(args.candidate/"package")
    replay = CandidatePackage.load(args.replay/"package")
    if package.sha256 != replay.sha256 or any(package.member_bytes(n) != replay.member_bytes(n) for n in package.member_names):
        raise ValueError("fresh-process candidate replay differs")
    validation = json.loads((args.candidate/"validation.json").read_bytes())
    replay_validation = json.loads((args.replay/"validation.json").read_bytes())
    if validation != replay_validation or validation["status"] != "pass":
        raise ValueError("fresh-process validation replay differs")
    oracle = validation["attestation"]
    if oracle != replay_validation["attestation"] or oracle["source_manifest_sha256"] != manifest.sha256 or oracle["candidate_sha256"] != package.sha256:
        raise ValueError("Exact current package/replay oracle bindings differ")
    if oracle["status"] != "pass":
        raise ValueError(oracle["findings"])
    validator = manifest.record["validator"]
    expected_oracle = _validation_authority_bindings(manifest) | dict(
        oracle_id=validator["id"], oracle_version=validator["version"],
        implementation_sha256=validator["implementation_sha256"],
        import_closure_sha256=validator["import_closure_sha256"], runtime=_runtime_binding())
    if any(oracle.get(key) != value for key,value in expected_oracle.items()):
        raise ValueError("Saved oracle current authority/runtime bindings differ")
    if oracle["result_sha256"] != sha256(canonical({k:v for k,v in oracle.items() if k != "result_sha256"})).hexdigest():
        raise ValueError("Saved oracle result digest differs")
    if validation["report_sha256"] != sha256(canonical({k:v for k,v in validation.items() if k != "report_sha256"})).hexdigest():
        raise ValueError("Saved validation report digest differs")
    mutations = json.loads((args.mutations/"result.json").read_bytes())
    source_facts = mutations["baseline"]
    if source_facts.get("status") != "pass" or source_facts.get("source_node_count") != 19975 or len(source_facts.get("members",[])) != 34 or source_facts.get("source_tag_counts",{}).get("table") != 236:
        raise ValueError("Complete current bound independent source check differs")
    if (mutations["status"] != "pass" or len(mutations["cases"]) != 20
            or any(c["status"] != "rejected" for c in mutations["cases"])
            or mutations["candidate_sha256"] != package.sha256
            or mutations["replay_sha256"] != replay.sha256
            or mutations["source_manifest_sha256"] != manifest.sha256):
        raise ValueError("mutation proof is incomplete")
    before = _files(ROOT/WORK)
    if any(Path(p).name in {"acceptance.json", "master.tei.xml"} for p in before):
        raise ValueError("canonical edition already has acceptance/master")
    for relative in before:
        put(stage,WORK/relative,io_path(ROOT/WORK/relative).read_bytes())
    acquisition = validate_acquisition(io_path(ROOT/ACQUISITION),root=ROOT)
    for member in acquisition["retained_files"]:
        put(stage,Path(member["path"]),io_path(ROOT/member["path"]).read_bytes())
    for support in json.loads(manifest.authority_path("profile").read_bytes())["retained_support"]:
        put(stage,Path(support["path"]),io_path(ROOT/support["path"]).read_bytes())
    original_state = json.loads(io_path(ROOT/WORK/"state.json").read_bytes())
    for target in original_state["targets"]:
        for path in target["evidence"]:
            put(stage,Path(path),io_path(ROOT/path).read_bytes())
    original_work = load_work(ROOT/WORK/"work.json")
    revised = json.loads(canonical(original_work))
    if original_work["title"] != TITLE or original_work["textual_forms"][0]["language"] != "en":
        raise ValueError("BCP1549 complete electronic witness identity/language preimage differs")
    revised["textual_forms"][0]["editions"][0].update(category="liturgies")
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
    source = dict(source_path=acquisition["source_path"],source_sha256=acquisition["source_sha256"],source_bytes=acquisition["source_bytes"],source_scope=acquisition["source_scope"],source_kind="retained-member-set")
    revision = dict(id='bcp1549-complete-retained-electronic-v1',date='2026-10-02',note='Technical acceptance of all34retained electronic members including shared/editorial/1550/comparative context; full236native tables and65rowspans/218colspans/literalroles/inlinewording preserved. Not a pure1549print witness; human acceptance/rights/publication separate.')
    raw_candidate = package.member_bytes("content.tei.xml")
    bound = bind_reviewed_header(raw_candidate,expected_sha256=sha256(raw_candidate).hexdigest(),identity=identity,
                                source=source,source_url=acquisition["url"],declared_scope=SCOPE,revision=revision)
    replay_bound = bind_reviewed_header(replay.member_bytes("content.tei.xml"),expected_sha256=sha256(raw_candidate).hexdigest(),identity=identity,
                                       source=source,source_url=acquisition["url"],declared_scope=SCOPE,revision=revision)
    if bound != replay_bound or bound.split(b"</ns0:teiHeader>",1)[1] != raw_candidate.split(b"</ns0:teiHeader>",1)[1]:
        raise ValueError("acceptance header changed reviewed text or failed deterministic replay")
    candidate = put(stage,EVIDENCE/"candidate.tei.xml",bound)
    if failures := validate_file(io_path(candidate)):
        raise ValueError(f"bound candidate P5 failures: {failures}")
    expected = [dict(path=m["path"],position=i) for i,m in enumerate(acquisition["retained_files"],1)]
    included = [dict(path=m["path"],position=i,bytes=m["bytes"],sha256=m["sha256"],scope="Complete textual HTML member within the declared 34-member electronic envelope; acquisition position is not reading order.") for i,m in enumerate(acquisition["retained_files"],1)]
    excluded = []
    scope = dict(kind="selection",declared=SCOPE,expected_members=expected,included_members=included,excluded_members=excluded)
    common = dict(identity=identity,source=source,candidate=make_file_binding(stage,candidate),
                  accepted_scope=dict(kind="selection",declared=SCOPE),expected_members=expected,included_members=included,excluded_members=excluded,
                  missing_members=[],unknown_members=[])
    accounting = put_json(stage,EVIDENCE/"source-accounting.json",common|dict(projection_profile="ocd-liturgies-bcp1549-retained-members-v1",scope=source["source_scope"],source_sha256=source["source_sha256"],source_bytes=source["source_bytes"], source_oracle=oracle,source_facts=source_facts,source_accountability=json.loads(package.member_bytes("source-accountability.json"))))
    command = "py -3 -m build.tools.stage_bcp1549_current --stage <fresh-stage> --promoted <fresh-promotion> --candidate <current-candidate> --replay <fresh-replay> --mutations <mutation-proof>"
    technical = dict(producer=dict(id="ocd-bcp1549-complete-retained-current-v1"),checker=dict(id=oracle["oracle_id"]),shared_assumptions=["Independent wholeHTML inverse oracle; producer not imported. Both readers share declared libxml HTMLrecovery; independentPythonHTMLdecoder binds199visibleglyph replacements. No browser/print-collation claim."],independent_corroboration="Complete34-member/19,975source-node inverse conservation,236tables/65rowspans/218colspans,199sourcevisibleglyphdecoderledger,sourceURL/inline/role/grammar-wrapper conservation;20source mutations plusfocusedpublic/profile checks and fresh package/validation/bound-header replay.")
    evidence = dict(source_oracle=oracle,validation=validation,mutation_cases=mutations["cases"],replay=dict(status="pass",candidate_sha256=package.sha256,validation_equal=True,bound_candidate_sha256=sha256(bound).hexdigest()),tei_p5="pass",text_subtree_byte_identical=True)
    for name in ("validation","accounting","fidelity","reproducibility","schema","closure"):
        path = put_json(stage,EVIDENCE/(name+".json"),common|dict(scope=SCOPE,projection_profile="ocd-liturgies-bcp1549-retained-members-v1",status="pass",command=command,exit_code=0,claim=name,**evidence))
        technical[name] = dict(path=path,status="pass",command=command,exit_code=0)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    review = dict(reviewer="agent:bcp1549-complete-retained-source-check",reviewed_at=now,coverage=dict(status="partial",declared=SCOPE,reached=["complete retained source native tree and envelope accounting","all34members/19,975source nodes/236tables/65rowspans/218colspans/199glyphdecodings and literal source attributes/text/tails/attachment/order"],inspected=["complete retained source native tree and envelope accounting"],unreviewed=["current exact-pair full visual comparison","print collation"]),source_quality_uncertainty=["Shared/comparative1549electronic expression, primaryWebauthor/introductionauthor roles and unretainedassets qualified; inheritedtranscriber/publicdomain assertions not corroborated. No retainedpermission found.","Electronic witness not collated to print."],discrepancies=[],unreviewed_residuals=["Human acceptance, full visual review, print collation and independent rights clearance remain unassessed."])
    review_path = put_json(stage,EVIDENCE/"review.json",common|review|dict(scope=SCOPE))
    decision = dict(source_local_disposition="Technical agent acceptance of the complete retained BCP1549 complete electronic witness work.",blockers=[],human_decision=dict(status="not-recorded"),
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
        projection = project_accepted_liturgies(io_path(promoted_root),acceptance_path=io_path(promoted_acceptance))
        errors = verify_accepted_liturgies(io_path(promoted_root),acceptance_path=io_path(promoted_acceptance),rows=projection["rows"],receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 34:
        raise ValueError(f"actual-master projection differs: {errors}; rows={len(projection['rows'])}")
    def native_nodes(n):
        yield n
        for c in n.get('content',[]):
            if isinstance(c,dict):yield from native_nodes(c)
    native=[n for row in projection['rows'] for structure in row['structure'] for n in native_nodes(structure)]
    if sum(n.get('kind')=='table' for n in native)!=236 or sum('row_span' in n.get('attributes',{}) for n in native)!=65 or sum('columns' in n.get('attributes',{}) for n in native)!=218:
        raise ValueError('Complete236native tables/65rowspans/218colspans must remain')
    from build.tools.prepare_bcp1549_current import DATA_NOTICE
    put(promoted_root, BASE/'README.source.md', notice)
    put(promoted_root, DATA_NOTICE, notice)
    binding = dict(source_path=(BASE/'README.source.md').as_posix(), source_sha256=sha256(notice).hexdigest(),
                   notice_path=DATA_NOTICE.as_posix(), notice_sha256=sha256(notice).hexdigest())
    if notice_texts_for_item(promoted_root, dict(item_id=WORK_ID, category='liturgies', public_notices=[binding]), promoted_acceptance) != [notice.decode()]:
        raise ValueError('Maintained source/data notice preflight differs')
    if {p.as_posix(): sha256((ROOT / p).read_bytes()).hexdigest() for p in schema_paths} != schema_pins:
        raise ValueError("shared schema changed during staged projection")
    put_json(promoted_root,EVIDENCE/"stage-projection.json",projection)
    receipt = dict(status="pass",work_id=WORK_ID,source_sha256=source["source_sha256"],category="liturgies",language="en",
                   source_facts=source_facts,before=before,master_sha256=sha256(bound).hexdigest(),rows=len(projection["rows"]),
                   projection_errors=errors,stage_root=stage.as_posix(),promoted_root=promoted_root.as_posix(),
                   schema_pins=schema_pins,
                   source_table_count=236,source_rowspan_count=65,source_colspan_count=218, notice=binding,
                   promotion_route="work-specific long-path staged promotion; shared record/binding validators and guarded canonical installer")
    receipt["after"] = _files(promoted_root/WORK)
    put_json(promoted_root,Path("stage-receipt.json"),receipt)
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
