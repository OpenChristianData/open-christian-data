"""Prepare a validated external Volume II acceptance handoff; never install."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil

from build.tei import hodge_vol2_complete_oracle as checker
from build.tools.prepare_hodge_vol2_complete import (ROOT, WORK_ID, WORK, EDITION, ACQUISITION,
                                                    IDENTITY, SOURCE, MANIFEST, SCOPE, canonical)
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.acceptance import (build_acceptance_record, make_file_binding,
                                      validate_acceptance, write_acceptance, _source_binding,
                                      _validate_acceptance_for_work)
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

EVIDENCE = WORK / "integration/hodge-vol2-complete-electronic-v1"
REVIEW_HOME = Path("D:/Library/Open Christian Data/candidate-reviews/37c-204-hodge-systematic-theology-vol-2-20260917-v3")


def put(root, relative, raw):
    path = io_path(root / relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return root / relative


def stage(candidate, replay, pending):
    for path in (candidate, replay, pending):
        if path.absolute().parent.resolve(strict=True) != REVIEW_HOME.resolve(strict=True):
            raise ValueError("Exact existing Volume II review home required")
    if pending.exists():
        raise FileExistsError("Fresh acceptance handoff roots required")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package, repeated = (CandidatePackage.load(p / "package") for p in (candidate, replay))
    if package.sha256 != repeated.sha256 or any(package.member_bytes(n) != repeated.member_bytes(n) for n in package.member_names):
        raise ValueError("Fresh process reconstruction differs")
    validation = json.loads((candidate / "validation.json").read_bytes())
    if validation != json.loads((replay / "validation.json").read_bytes()) or validation["status"] != "pass":
        raise ValueError("Fresh process validation differs")
    mutations = json.loads((candidate / "mutations.json").read_bytes())
    raw = package.member_bytes("content.tei.xml")
    account = package.member_bytes("source-accountability.json")
    facts = checker.check(manifest, raw, account)
    oracle = checker._oracle(manifest, package)
    if (oracle["status"] != "pass" or mutations["status"] != "pass" or len(mutations["cases"]) != 15
            or any(c["status"] != "rejected" for c in mutations["cases"])
            or mutations["candidate_sha256"] != package.sha256 or mutations["baseline"] != facts):
        raise ValueError("Exact baseline/mutation evidence differs")
    before = _files(ROOT / WORK)
    previous = _validate_acceptance_for_work(ROOT / EDITION / "acceptance.json", root=ROOT, work_id=WORK_ID)
    if previous["promotion"]["master"]["sha256"] != "c7bdfec7101c041bc135b56b28083b6eafe848fa504889bd1982baa914efacd7":
        raise ValueError("Current accepted parts preimage differs")
    shutil.copytree(io_path(ROOT / WORK), io_path(pending / WORK))
    for relative in (SOURCE, MANIFEST):
        put(pending, relative, io_path(ROOT / relative).read_bytes())
    for authority in manifest.record["authorities"]:
        relative = Path(authority["path"])
        put(pending, relative, io_path(ROOT / relative).read_bytes())
    current_state = json.loads(io_path(ROOT / WORK / "state.json").read_bytes())
    for target in current_state["targets"]:
        for name in target["evidence"]:
            put(pending, Path(name), io_path(ROOT / name).read_bytes())
    acquisition = validate_acquisition(ROOT / ACQUISITION, root=ROOT)
    put(pending, EVIDENCE / "previous-acquisition.json", io_path(ROOT / ACQUISITION).read_bytes())
    put(pending, EVIDENCE / "previous-acceptance.json", io_path(ROOT / EDITION / "acceptance.json").read_bytes())
    put(pending, EVIDENCE / "previous-master.tei.xml", io_path(ROOT / EDITION / "master.tei.xml").read_bytes())
    acquisition["source_scope"] = SCOPE
    acquisition["retained_files"][0]["scope"] = SCOPE
    put(pending, ACQUISITION, canonical(acquisition))
    validate_acquisition(pending / ACQUISITION, root=pending)
    for name in package.member_names:
        put(pending, EVIDENCE / "original-package" / name, package.member_bytes(name))
    put(pending, EVIDENCE / "original-validation.json", (candidate / "validation.json").read_bytes())
    put(pending, EVIDENCE / "mutations.json", canonical(mutations))
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    revision = dict(id="hodge-vol2-complete-electronic-v1", date="2026-10-08",
                    note="Represent the complete retained Volume II: title pages, contents, Anthropology, Soteriology and seven indexes; preserve valid Parts II/III.")
    source = _source_binding(acquisition, context="Volume II complete retained source")
    bound = bind_reviewed_header(raw, expected_sha256=sha256(raw).hexdigest(), identity=IDENTITY,
        source=source, source_url=acquisition["url"], declared_scope=SCOPE, revision=revision)
    if bound.split(b"</teiHeader>", 1)[1] != raw.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Acceptance binding changed the readable body")
    candidate_path = put(pending, EVIDENCE / "candidate.tei.xml", bound)
    if failures := validate_file(candidate_path):
        raise ValueError(f"Bound TEI P5 validation failed: {failures}")
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=acquisition["source_bytes"], sha256=acquisition["source_sha256"], scope=SCOPE)]
    scope = dict(kind="selection", declared=SCOPE, expected_members=expected, included_members=included, excluded_members=[])
    common = dict(identity=IDENTITY, source=source, candidate=make_file_binding(pending, candidate_path),
        scope=SCOPE, accepted_scope=dict(kind="selection", declared=SCOPE), expected_members=expected,
        included_members=included, excluded_members=[], missing_members=[], unknown_members=[])
    accounting = put(pending, EVIDENCE / "source-accounting.json", canonical(common | dict(
        source_sha256=acquisition["source_sha256"], source_bytes=acquisition["source_bytes"],
        source_facts=facts, source_accountability=json.loads(account))))
    command = "py -3 -m build.tools.stage_hodge_vol2_complete --candidate <exact-candidate> --replay <exact-replay> --pending <fresh-pending>"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]), checker=dict(id=manifest.record["validator"]["id"]),
        shared_assumptions=["Historical valid Parts II/III reused. Newly included roots use the established complete-volume mapping semantics, independently re-expressed in the checker. Prior exposure is disclosed; no blind claim. Both use lxml XML parsing."],
        independent_corroboration="All source carriers/relationships and local link targets independently checked; stdlib ElementTree agrees with lxml on every source carrier; fifteen targeted mutations rejected; exact clean-process replay and P5 pass.")
    evidence = dict(status="pass", command=command, exit_code=0, source_facts=facts, oracle=oracle,
        candidate_package_sha256=package.sha256, validation=validation, mutations=mutations["cases"],
        replay_equal=True, p5="pass", acceptance_body_byte_equal=True)
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = put(pending, EVIDENCE / (name + ".json"), canonical(common | evidence | dict(claim=name)))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    review = dict(reviewer="agent:hodge-vol2-complete-source-check", reviewed_at=now,
        coverage=dict(status="partial", declared=SCOPE, reached=["all five retained roots", "complete native source tree and link closure",
            "all source carriers and relationships mechanically", "source title/contents/index boundaries directly"],
            inspected=["all source carriers and relationships mechanically", "source title/contents/index boundaries directly"],
            unreviewed=["current exact-pair visual comparison", "physical print collation"]),
        source_quality_uncertainty=["Retained electronic witness only; inherited 1872-1873 print claim is unverified."],
        discrepancies=[], unreviewed_residuals=["Visual comparison and human verification remain unrecorded; rights clearance and publication are separate."])
    report = put(pending, EVIDENCE / "review.json", canonical(common | review | dict(
        skill_package_root=str(ROOT / ".agents/skills/source-to-tei"), reviewed_project_root=str(ROOT),
        selected_review_patterns=["RP-01", "RP-03", "RP-04", "RP-06", "RP-13", "RP-14", "RP-15"],
        root_dispositions={"i": "represented: own-volume title/copyright/imprint", "ii": "represented: contents of second volume",
            "iii": "preserved byte equal: Anthropology", "iv": "preserved byte equal: Soteriology",
            "v": "represented: seven electronic source indexes"})))
    decision = dict(source_local_disposition="Evidence-backed agent acceptance of complete retained electronic Volume II; canonical adoption pending supported replacement.",
        blockers=[], human_decision=dict(status="not-recorded"), agent_assessment=dict(status="accepted",
        actor=review["reviewer"], assessed_at=now, supported_scope=SCOPE, unresolved_claims=[],
        unassessed_stronger_claims=["exact-pair visual comparison", "human verification", "physical print identity", "rights clearance", "publication"]))
    record = build_acceptance_record(pending, identity=IDENTITY, candidate_path=candidate_path,
        source_accounting_path=accounting, scope=scope, technical=technical,
        review=review | dict(report_path=report), representation_revision=revision, decision=decision)
    write_acceptance(pending / EDITION / "acceptance.json", record)
    validate_acceptance(pending / EDITION / "acceptance.json", root=pending)
    if _files(ROOT / WORK) != before:
        raise ValueError("Canonical work changed during handoff preparation")
    receipt = dict(status="pass", installation_status="held-production-replacement-route",
        work_id=WORK_ID, source_sha256=acquisition["source_sha256"], source_bytes=acquisition["source_bytes"],
        source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
        candidate_tei_sha256=sha256(raw).hexdigest(), bound_candidate_sha256=sha256(bound).hexdigest(),
        before=before, pending_files=_files(pending / WORK), canonical_generation_unchanged=True,
        pending_root=str(pending), promotion_status="pending", source_facts=facts,
        planned_authority_changes=["source_scope", "retained_files[0].scope", "accepted representation and edition state timestamp/reason"],
        install_blocker="Existing Hodge staged promoter permits only C:/Scratch/h204p. Shared install_accepted_work production replacement is fixture-only; the existing Hodge installer also requires absence of acceptance/master.",
        required_capability="Extend the existing exact-work guarded Hodge route to accept the frozen accepted preimage and complete-volume revision, allowing only the two source-scope descriptions plus the new representation/evidence; retain lock, journal, stale-generation check, rollback and post-swap validation.")
    put(pending, Path("stage-receipt.json"), canonical(receipt))
    print(json.dumps({k: v for k, v in receipt.items() if k not in ("before", "pending_files")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "replay", "pending"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    stage(args.candidate, args.replay, args.pending)
