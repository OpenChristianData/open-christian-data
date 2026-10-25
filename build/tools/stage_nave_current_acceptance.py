"""Stage the existing complete Nave native body for technical adoption only."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from lxml import etree

from build.tools.prepare_nave_current import ROOT, WORK_ID, FORM_ID, EDITION_ID, ACQUISITION_ID, BASE, LOG, HISTORICAL, REVISION, digest, save, json_bytes
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update, cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance, _source_binding
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.projection.categories.topical_indexes import project_accepted_topical_indexes, verify_accepted_topical_indexes


WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
EVIDENCE = WORK / "integration/nave-accepted-v1"
SOURCE_SHA = "0b83eb74adf00b56987e49e7f00731bc8b4be5e7daa3828d62ec6a3943884f17"
MASTER_SHA = "199c1a0e4d8de4ecce8ef712a3b30edd7c0b19aaf61cf3e4315e8ad0f9cd652a"
DISPATCH_SHA = "d00dcda6c29a9350da8fa09a45364b79bbd1b238ce6d22cb4ce8e5aecf699c7b"
ADAPTER_SHA = "44d72d6ba331456a58360de1cf90f515b003e346951ceec26ac70846695d0277"
TITLE = "Nave's Topical Bible"


def put(stage, relative, raw):
    path = stage / relative
    save(path, raw)
    return path


def put_json(stage, relative, value):
    return put(stage, relative, json_bytes(value))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    stage = args.stage.absolute()
    if stage.exists() or stage.parent.resolve(strict=True) != Path("D:/Library/Open Christian Data/candidate-reviews").resolve(strict=True) or not stage.name.startswith("nave-"):
        raise ValueError("Fresh bounded Nave stage required")
    paths = ["ocd_kernel/projection/categories/topical_indexes.py", "ocd_kernel/projection/categories/topical_nave.py", "ocd_kernel/tei/acceptance.py", "ocd_kernel/tei/install_accepted.py", "schemas/v2/categories/topical-indexes.schema.json", "schemas/v2/public-row.schema.json", "schemas/v2/release-selection.schema.json", "schemas/v2/release-report.schema.json"]
    pins = {path: digest((ROOT / path).read_bytes()) for path in paths}
    if pins[paths[0]] != DISPATCH_SHA or pins[paths[1]] != ADAPTER_SHA or digest((BASE / "candidate.tei.xml").read_bytes()) != MASTER_SHA:
        raise ValueError("Reviewed Nave candidate/runtime drifted")
    replay = LOG / "replay/candidate.tei.xml"
    if replay.read_bytes() != (BASE / "candidate.tei.xml").read_bytes():
        raise ValueError("Fresh exact header/body composition replay differs")
    source_proof = json.loads((LOG / "retained-source-native-review.json").read_bytes())
    actual_proof = json.loads((LOG / "native-support-proposal-v2/actual-projection-proof.json").read_bytes())
    if source_proof["status"] != "pass" or actual_proof["status"] != "pass":
        raise ValueError("Complete source/candidate proof differs")
    before = _files(ROOT / WORK)
    if any(Path(path).name in {"acceptance.json", "master.tei.xml"} for path in before):
        raise ValueError("Already installed; inspect current authority")
    for path in before:
        put(stage, WORK / path, io_path(ROOT / WORK / path).read_bytes())
    acquisition_path = EDITION / "acquisitions" / (ACQUISITION_ID + ".json")
    acquisition = validate_acquisition(io_path(ROOT / acquisition_path), root=ROOT)
    if acquisition["source_sha256"] != SOURCE_SHA:
        raise ValueError("Actual acquired member-set differs")
    for member in acquisition["retained_files"]:
        raw = io_path(ROOT / member["path"]).read_bytes()
        if len(raw) != member["bytes"] or digest(raw) != member["sha256"]:
            raise ValueError("Actual extracted source member drifted")
        put(stage, Path(member["path"]), raw)
    original_state = json.loads(io_path(ROOT / WORK / "state.json").read_bytes())
    for target in original_state["targets"]:
        for path in target["evidence"]:
            put(stage, Path(path), io_path(ROOT / path).read_bytes())
    proposal = LOG / "authority-proposal"
    for name in ("work", "state"):
        if io_path(ROOT / WORK / (name + ".json")).read_bytes() != (proposal / (name + ".before.json")).read_bytes():
            raise ValueError("Exact proposed authority preimage drifted")
        io_path(stage / WORK / (name + ".json")).write_bytes((proposal / (name + ".after.json")).read_bytes())
    validate_identity_update(load_work(ROOT / WORK / "work.json"), load_work(stage / WORK / "work.json"))
    for relative, source in ((Path("data/topical_indexes") / WORK_ID / "README.md", "README.data.md"), (Path("sources/topical-indexes") / WORK_ID / "README.source.md", "README.source.md")):
        put(stage, relative, (BASE / source).read_bytes())
    put(stage, WORK / "SOURCE_CREDIT.md", (BASE / "SOURCE_CREDIT.md").read_bytes())
    proofs = {
        "historical-package-manifest.json": HISTORICAL / "manifest.json",
        "historical-crosswalk.json": HISTORICAL / "source-accountability.json",
        "source-proof.json": LOG / "retained-source-native-review.json",
        "actual-candidate-proof.json": LOG / "native-support-proposal-v2/actual-projection-proof.json",
        "fresh-replay.json": LOG / "replay/candidate.tei.replay.json",
        "coordinator-source-review.json": ROOT / "reports/_logs/nave-coordinator-source-review-20261002-v1/review.json",
        "coordinator-runtime-clearance.json": LOG / "native-support-proposal-v2/coordinator-adapter-clearance.json",
        "applied-runtime.json": LOG / "native-support-proposal-v2/applied-runtime.json",
        "header-acceptance-facts.json": LOG / "header-acceptance-facts-v2.json",
        "authority-proposal.json": proposal / "proposal.json",
    }
    for name, path in proofs.items():
        put(stage, EVIDENCE / name, path.read_bytes())
    identity = {"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID, "acquisition_id": ACQUISITION_ID}
    scope_text = acquisition["source_scope"]
    members = acquisition["retained_files"]
    scope = {"kind": "edition", "declared": scope_text, "expected_members": [{"path": m["path"], "position": n} for n, m in enumerate(members, 1)], "included_members": [{k: m[k] for k in ("path", "bytes", "sha256", "scope")} | {"position": n} for n, m in enumerate(members, 1)], "excluded_members": []}
    source = _source_binding(acquisition, context="Nave complete retained electronic module")
    candidate = stage / BASE.relative_to(ROOT) / "candidate.tei.xml"
    tree = etree.fromstring(io_path(candidate).read_bytes())
    change = tree.find("{http://www.tei-c.org/ns/1.0}teiHeader/{http://www.tei-c.org/ns/1.0}revisionDesc/{http://www.tei-c.org/ns/1.0}change")
    revision = {"id": REVISION, "date": change.get("when"), "note": change.text}
    common = {"identity": identity, "source": source, "candidate": make_file_binding(stage, candidate), "scope": scope_text, "accepted_scope": {"kind": "edition", "declared": scope_text}, "expected_members": scope["expected_members"], "included_members": scope["included_members"], "excluded_members": [], "missing_members": [], "unknown_members": []}
    accounting = put_json(stage, EVIDENCE / "source-accounting.json", common | {"status": "pass", "source_sha256": SOURCE_SHA, "source_bytes": source["source_bytes"], "native_entries": 5322, "native_references": 82303, "reading_order": "dict.idx addressed entry order; acquisition inventory order is distinct", "support_dispositions": {"raw/naves_topical/mods.d/nave.conf": "literal module metadata/rights/credit support", "raw/naves_topical/Nave.zip": "acquisition package only, independently checked extracted-member equality", "raw/naves_topical/_download_nave.py": "historical acquisition procedure; not content", "raw/naves_topical/format_inspection.txt": "historical format inspection; not content"}, "historical_manifest_missing": "Historical manifest path is retained as evidence only; current physical acquisition/member authority and full fresh source-native linkage replace its unavailable linkage, without fabricating it.", "binary_controls": "One terminal NUL per payload and exactly 1024 zero padding bytes per compressed allocation explicitly accounted in full historical crosswalk and fresh source proof."})
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    command = "py -3 -m build.tools.stage_nave_current_acceptance --stage <fresh-nave-stage>"
    technical = {"producer": {"id": "ocd-nave-pinned-native-body-current-header-composition-v1"}, "checker": {"id": "ocd-nave-maintained-binary-source-and-independent-native-check-v1"}, "shared_assumptions": ["Maintained binary decoder reused by source oracle and coordinator; independent recursive XML comparisons and producer-disabled lxml projection checker constrain interpretation. Public rendering is plain text plus literal references, not XML-preserving public rows."], "independent_corroboration": "ROOT whole 5322 decoded-payload direct XML comparison; exact unchanged historical body, fresh header facts/replay, P5 and 20 focused checks plus two unchanged default-route fixtures. Historical visual review is dated; no fresh visual/human approval claim."}
    evidence = {k: make_file_binding(stage, stage / EVIDENCE / v) for k, v in (("source_proof", "source-proof.json"), ("actual_candidate_proof", "actual-candidate-proof.json"), ("root_source_review", "coordinator-source-review.json"), ("runtime_clearance", "coordinator-runtime-clearance.json"), ("replay", "fresh-replay.json"))}
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = put_json(stage, EVIDENCE / (name + ".json"), common | {"status": "pass", "claim": name, "command": command, "exit_code": 0, **evidence})
        technical[name] = {"path": path, "status": "pass", "command": command, "exit_code": 0}
    review = {"reviewer": "agent:nave-complete-retained-electronic-technical-adoption", "reviewed_at": now, "coverage": {"status": "partial", "declared": scope_text, "reached": ["all extracted binary members", "all native entries", "current header"], "inspected": ["5322 decoded entry payloads and keys computationally", "all native XML tags/attributes/text/tails/hierarchy/order computationally", "literal config and exact acceptance header bindings"], "unreviewed": ["fresh exact-pair visual comparison", "human verification", "identified print witness"]}, "source_quality_uncertainty": ["Module-stated rights and historical print/ISBN claims lack independent clearance/collation."], "discrepancies": [], "unreviewed_residuals": ["human textual acceptance", "rights clearance", "print collation", "public publication"]}
    # The acceptance contract requires inspected loci to be within reached loci.
    review["coverage"]["reached"] = list(review["coverage"]["inspected"])
    report = put_json(stage, EVIDENCE / "review.json", common | review)
    decision = {"source_local_disposition": "Agent technical adoption of the complete retained electronic module; historical manifest and rights warnings remain explicitly historical/unresolved.", "blockers": [], "human_decision": {"status": "not-recorded"}, "agent_assessment": {"status": "accepted", "actor": review["reviewer"], "assessed_at": now, "supported_scope": scope_text, "unresolved_claims": [], "unassessed_stronger_claims": review["unreviewed_residuals"]}}
    acceptance = stage / EDITION / "acceptance.json"
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate, source_accounting_path=accounting, scope=scope, technical=technical, review=review | {"report_path": report}, representation_revision=revision, decision=decision)
    master = put(stage, EDITION / "master.tei.xml", io_path(candidate).read_bytes())
    record["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(stage, master))
    write_acceptance(io_path(acceptance), record)
    validate_state(stage / WORK / "state.json", root=stage)
    with cached_edition_lookups():
        validate_acceptance(io_path(acceptance), root=io_path(stage))
        projection = project_accepted_topical_indexes(io_path(stage), acceptance_path=io_path(acceptance))
        errors = verify_accepted_topical_indexes(io_path(stage), acceptance_path=io_path(acceptance), rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 5322 or sum(len(r["text"]) for r in projection["rows"]) != 1410060:
        raise ValueError(f"Actual accepted Nave projection failed: {errors}")
    put_json(stage, EVIDENCE / "stage-projection.json", projection)
    if {p: digest((ROOT / p).read_bytes()) for p in paths} != pins or _files(ROOT / WORK) != before:
        raise ValueError("Current runtime/authority drifted during stage")
    after = _files(stage / WORK)
    for p, expected in before.items():
        if p not in {"work.json", "state.json"} and after[p] != expected:
            raise ValueError("Existing staged authority changed: " + p)
    notices = [Path("data/topical_indexes") / WORK_ID / "README.md", Path("sources/topical-indexes") / WORK_ID / "README.source.md"]
    result = {"status": "pass", "work_id": WORK_ID, "stage_root": stage.as_posix(), "source_sha256": SOURCE_SHA, "master_sha256": MASTER_SHA, "acceptance_sha256": digest(io_path(acceptance).read_bytes()), "category": "topical-indexes", "language": "en", "rows": 5322, "characters": 1410060, "before": before, "after": after, "schema_pins": pins, "metadata_difference": ["textual_forms[0].editions[0].category: absent -> topical-indexes"], "paired_notices": {p.as_posix(): digest(io_path(stage / p).read_bytes()) for p in notices}, "projection_errors": errors, "canonical_install_performed": False}
    put_json(stage, Path("stage-receipt.json"), result)
    save(LOG / "staged-acceptance.json", json_bytes(result))
    print(json.dumps({"status": "pass", "stage_root": stage.as_posix(), "stage_receipt_sha256": digest(json_bytes(result)), "after_files": len(after), "before_files": len(before), "acceptance_sha256": result["acceptance_sha256"]}))


if __name__ == "__main__":
    main()
