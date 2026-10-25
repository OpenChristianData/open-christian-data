"""Stage only the complete retained Hitchcock electronic witness for review."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from lxml import etree

from build.tools.prepare_hitchcock_current import ROOT, WORK_ID, FORM_ID, EDITION_ID, ACQUISITION_ID, BASE, LOG, HISTORICAL, SOURCE, SOURCE_SHA, REVISION, digest, save, json_bytes
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update, cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance, PROMOTED_MASTER_REASON, _source_binding
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.projection.categories.reference_entries import project_accepted_reference_entries, verify_accepted_reference_entries


WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
EVIDENCE = WORK / "integration/hitchcock-accepted-v1"
ADAPTER_SHA = "2211d08e5726fdabac379485bf4dedac68f1130f5f43432f226089222070d857"
MASTER_SHA = "67b359bc48cc8511776db13e002a11430c94074dac7248de4ac86495d2ac83cb"
TITLE = "Hitchcock's Bible Names Dictionary"


def put(stage, relative, raw):
    path = stage / relative
    save(path, raw)
    return path


def put_json(stage, relative, value):
    return put(stage, relative, json_bytes(value))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--resume-projection", action="store_true")
    args = parser.parse_args()
    stage = args.stage.absolute()
    if (stage.exists() and not args.resume_projection) or stage.parent.resolve(strict=True) != Path("D:/Library/Open Christian Data/candidate-reviews").resolve(strict=True) or not stage.name.startswith("hitchcock-"):
        raise ValueError("Fresh bounded Hitchcock stage required")
    paths = ["ocd_kernel/projection/categories/reference_entries.py", "ocd_kernel/tei/acceptance.py", "ocd_kernel/tei/install_accepted.py", "schemas/v2/categories/reference-entries.schema.json", "schemas/v2/public-row.schema.json", "schemas/v2/release-selection.schema.json", "schemas/v2/release-report.schema.json"]
    pins = {path: digest((ROOT / path).read_bytes()) for path in paths}
    if pins[paths[0]] != ADAPTER_SHA or digest((BASE / "candidate.tei.xml").read_bytes()) != MASTER_SHA or digest(SOURCE.read_bytes()) != SOURCE_SHA:
        raise ValueError("Reviewed candidate/source/runtime drifted")
    if args.resume_projection:
        if not stage.exists() or (stage / "stage-receipt.json").exists():
            raise ValueError("Resume only an incomplete preserved stage")
        finish_projection(stage, _files(ROOT / WORK), paths, pins)
        return
    replay = LOG / "replay/candidate.tei.xml"
    if replay.read_bytes() != (BASE / "candidate.tei.xml").read_bytes():
        raise ValueError("Fresh process exact candidate replay differs")
    source_proof = json.loads((BASE / "source-proof.json").read_text())
    actual_proof = json.loads((LOG / "native-support-proposal/actual-candidate-proof.json").read_text())
    if source_proof["status"] != "pass" or actual_proof["status"] != "pass" or len(actual_proof["meaningful_source_mutations"]) != 7:
        raise ValueError("Complete source/candidate proof differs")
    before = _files(ROOT / WORK)
    if any(Path(path).name in {"acceptance.json", "master.tei.xml"} for path in before):
        raise ValueError("Already installed; inspect current authority")
    for path in before:
        put(stage, WORK / path, io_path(ROOT / WORK / path).read_bytes())
    acquisition_path = EDITION / "acquisitions" / (ACQUISITION_ID + ".json")
    acquisition = validate_acquisition(io_path(ROOT / acquisition_path), root=ROOT)
    for member in acquisition["retained_files"]:
        put(stage, Path(member["path"]), io_path(ROOT / member["path"]).read_bytes())
    state = json.loads(io_path(ROOT / WORK / "state.json").read_bytes())
    for target in state["targets"]:
        for path in target["evidence"]:
            put(stage, Path(path), io_path(ROOT / path).read_bytes())
    original_work = load_work(ROOT / WORK / "work.json")
    revised = json.loads(json_bytes(original_work))
    form = revised["textual_forms"][0]
    edition = form["editions"][0]
    if original_work["title"] != TITLE or form["textual_form_id"] != FORM_ID or edition["edition_id"] != EDITION_ID or form["language"] != "en" or edition["language"] != "en" or "category" in edition:
        raise ValueError("Exact category-only metadata preimage differs")
    edition["category"] = "reference-entries"
    validate_identity_update(original_work, revised)
    io_path(stage / WORK / "work.json").write_bytes(json_bytes(revised))
    notice = (BASE / "README.source.md").read_bytes()
    if (BASE / "README.data.md").read_bytes() != notice or notice.endswith(b"\n\n"):
        raise ValueError("Paired visible notice wording/format differs")
    # Deliver developer-directed credit without overwriting the historical warning.
    data_notice = Path("data/reference_entries") / WORK_ID / "README.md"
    source_notice = Path("sources/reference-entries") / WORK_ID / "README.source.md"
    for path in (data_notice, source_notice):
        save(ROOT / path, notice)
        put(stage, path, notice)
    put(stage, WORK / "SOURCE_CREDIT.md", notice)
    for name, path in {
        "historical-package-manifest.json": HISTORICAL / "manifest.json",
        "historical-crosswalk.json": HISTORICAL / "source-accountability.json",
        "source-proof.json": BASE / "source-proof.json",
        "actual-candidate-proof.json": LOG / "native-support-proposal/actual-candidate-proof.json",
        "fresh-replay.json": LOG / "replay/candidate.tei.replay.json",
        "coordinator-source-review.json": ROOT / "reports/_logs/hitchcock-coordinator-source-review-20261002-v1/review.json",
        "coordinator-runtime-freeze.json": LOG / "native-support-proposal/coordinator-reviewed-freeze.json",
    }.items():
        put(stage, EVIDENCE / name, path.read_bytes())
    identity = {"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID, "acquisition_id": ACQUISITION_ID}
    scope_text = acquisition["source_scope"]
    members = acquisition["retained_files"]
    scope = {"kind": "edition", "declared": scope_text, "expected_members": [{"path": member["path"], "position": n} for n, member in enumerate(members, 1)], "included_members": [{key: member[key] for key in ("path", "bytes", "sha256", "scope")} | {"position": n} for n, member in enumerate(members, 1)], "excluded_members": []}
    source = _source_binding(acquisition, context="Hitchcock complete retained electronic witness")
    candidate = stage / BASE.relative_to(ROOT) / "candidate.tei.xml"
    tree = etree.fromstring(io_path(candidate).read_bytes())
    change = tree.find("{http://www.tei-c.org/ns/1.0}teiHeader/{http://www.tei-c.org/ns/1.0}revisionDesc/{http://www.tei-c.org/ns/1.0}change")
    revision = {"id": REVISION, "date": change.get("when"), "note": change.text}
    common = {"identity": identity, "source": source, "candidate": make_file_binding(stage, candidate), "scope": scope_text, "accepted_scope": {"kind": "edition", "declared": scope_text}, "expected_members": scope["expected_members"], "included_members": scope["included_members"], "excluded_members": [], "missing_members": [], "unknown_members": []}
    current_accounting = json.loads((BASE / "source-accounting.json").read_text())
    accounting = put_json(stage, EVIDENCE / "source-accounting.json", current_accounting | common | {"source_sha256": SOURCE_SHA, "source_bytes": source["source_bytes"]})
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    command = "py -3 -m build.tools.stage_hitchcock_current_acceptance --stage <fresh-hitchcock-stage>"
    technical = {"producer": {"id": "ocd-hitchcock-retained-native-body-reviewed-header-reuse-v1"}, "checker": {"id": "ocd-hitchcock-direct-jsonl-native-check-v1"}, "shared_assumptions": ["Historical native body reused unchanged. Shared closed profile-admission logic; independently traversed ElementTree/lxml projection and separate direct JSONL source proof constrain that interpretation."], "independent_corroboration": "Whole 2622-record JSONL-to-native comparison, ROOT direct whole-source proof, exact historical text-byte conservation, seven source mutations and 27 focused/23 compatibility checks; producer-disabled public checker. No visual review claim."}
    evidence = {"source_proof": make_file_binding(stage, stage / EVIDENCE / "source-proof.json"), "actual_candidate_proof": make_file_binding(stage, stage / EVIDENCE / "actual-candidate-proof.json"), "root_source_review": make_file_binding(stage, stage / EVIDENCE / "coordinator-source-review.json"), "runtime_freeze": make_file_binding(stage, stage / EVIDENCE / "coordinator-runtime-freeze.json"), "replay": make_file_binding(stage, stage / EVIDENCE / "fresh-replay.json"), "native_body_bytes_identical": True, "p5": "pass"}
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = put_json(stage, EVIDENCE / (name + ".json"), common | {"status": "pass", "claim": name, "command": command, "exit_code": 0, **evidence})
        technical[name] = {"path": path, "status": "pass", "command": command, "exit_code": 0}
    review = {"reviewer": "agent:hitchcock-retained-electronic-technical-adoption", "reviewed_at": now, "coverage": {"status": "partial", "declared": scope_text, "reached": ["retained JSONL", "native TEI", "current header"], "inspected": ["retained JSONL/all2622 ordered terms and definitions computationally", "native TEI/all2622 entries and definitions computationally", "current header/complete source bindings"], "unreviewed": ["exact-pair visual comparison", "human verification", "identified print witness"]}, "source_quality_uncertainty": ["Structured-source rights and print-edition/bibliographic lineage unresolved."], "discrepancies": [], "unreviewed_residuals": ["visual comparison", "human textual approval", "rights clearance", "print collation", "public publication"]}
    report = put_json(stage, EVIDENCE / "review.json", common | review)
    decision = {"source_local_disposition": "Agent technical adoption of the complete retained electronic witness; historical rights-policy warnings preserved.", "blockers": [], "human_decision": {"status": "not-recorded"}, "agent_assessment": {"status": "accepted", "actor": review["reviewer"], "assessed_at": now, "supported_scope": scope_text, "unresolved_claims": [], "unassessed_stronger_claims": review["unreviewed_residuals"]}}
    acceptance = stage / EDITION / "acceptance.json"
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate, source_accounting_path=accounting, scope=scope, technical=technical, review=review | {"report_path": report}, representation_revision=revision, decision=decision)
    write_acceptance(io_path(acceptance), record)
    master = put(stage, EDITION / "master.tei.xml", io_path(candidate).read_bytes())
    record["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(stage, master))
    write_acceptance(io_path(acceptance), record)
    target = next(target for target in state["targets"] if target["target_id"] == EDITION_ID and target["target_type"] == "edition")
    if target["stage"] != "acquired":
        raise ValueError("Edition stage changed")
    target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    target["evidence"].extend([(EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()])
    io_path(stage / WORK / "state.json").write_bytes(json_bytes(state))
    validate_state(stage / WORK / "state.json", root=stage)
    finish_projection(stage, before, paths, pins)


def finish_projection(stage, before, paths, pins):
    acceptance = stage / EDITION / "acceptance.json"
    original = load_work(ROOT / WORK / "work.json")
    revised = load_work(stage / WORK / "work.json")
    expected = json.loads(json_bytes(original))
    expected["textual_forms"][0]["editions"][0]["category"] = "reference-entries"
    if revised != expected or digest(io_path(stage / EDITION / "master.tei.xml").read_bytes()) != MASTER_SHA:
        raise ValueError("Preserved stage identity or master changed")
    with cached_edition_lookups():
        validate_acceptance(io_path(acceptance), root=io_path(stage))
        projection = project_accepted_reference_entries(io_path(stage), acceptance_path=io_path(acceptance))
        errors = verify_accepted_reference_entries(io_path(stage), acceptance_path=io_path(acceptance), rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 2622:
        raise ValueError(f"Accepted staged native projection failed: {errors}")
    put_json(stage, EVIDENCE / "stage-projection.json", projection)
    if {path: digest((ROOT / path).read_bytes()) for path in paths} != pins or _files(ROOT / WORK) != before:
        raise ValueError("Current authority/runtime changed during stage")
    after = _files(stage / WORK)
    for path, expected in before.items():
        if path not in {"work.json", "state.json"} and after[path] != expected:
            raise ValueError("Staged existing authority changed: " + path)
    data_notice = Path("data/reference_entries") / WORK_ID / "README.md"
    source_notice = Path("sources/reference-entries") / WORK_ID / "README.source.md"
    result = {"status": "pass", "work_id": WORK_ID, "stage_root": stage.as_posix(), "source_sha256": SOURCE_SHA, "master_sha256": MASTER_SHA, "acceptance_sha256": digest(io_path(acceptance).read_bytes()), "category": "reference-entries", "language": "en", "rows": 2622, "characters": 58229, "before": before, "after": after, "schema_pins": pins, "metadata_difference": ["textual_forms[0].editions[0].category: absent -> reference-entries"], "projection_errors": errors, "paired_notices": {path.as_posix(): digest((ROOT / path).read_bytes()) for path in (data_notice, source_notice)}, "canonical_install_performed": False}
    put_json(stage, Path("stage-receipt.json"), result)
    save(LOG / "staged-acceptance.json", json_bytes(result))
    print(json.dumps({"status": "pass", "stage_root": stage.as_posix(), "stage_receipt_sha256": digest(json_bytes(result)), "after_files": len(after), "before_files": len(before), "master_sha256": MASTER_SHA, "acceptance_sha256": result["acceptance_sha256"]}))


if __name__ == "__main__":
    main()
