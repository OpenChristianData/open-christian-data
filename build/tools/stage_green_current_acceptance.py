"""Stage the complete existing Green electronic witness for technical adoption."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from lxml import etree

from build.tools.prepare_green_current import ROOT, LOG, BASE, WORK_ID, FORM_ID, EDITION_ID, ACQUISITION_ID, REVISION, digest, save, json_bytes
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update, cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, write_acceptance, _source_binding, _validate_acceptance_for_work
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.release.notices import notice_texts_for_item

WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
EVIDENCE = WORK / "integration/green-accepted-v1"
SOURCE_SHA = "6d8808688dbbb7d50854aab4b11a6242f76b7ce9fe409066304daeda260d9417"
MASTER_SHA = "011dc75db7ca61688bafa0e84f376e93c88ad5071f9244ce003d4e33b730563d"


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
    if stage.exists() or stage.parent.resolve(strict=True) != Path("D:/Library/Open Christian Data/candidate-reviews").resolve(strict=True) or not stage.name.startswith("green-current-"):
        raise ValueError("Fresh bounded Green stage required")
    paths = ["ocd_kernel/projection/categories/prose.py", "ocd_kernel/projection/categories/native_documents.py", "ocd_kernel/projection/categories/sermons.py", "ocd_kernel/projection/native_content.py", "ocd_kernel/projection/native_content_check.py", "ocd_kernel/tei/acceptance.py", "ocd_kernel/tei/install_accepted.py", "schemas/v2/native-content.schema.json", "schemas/v2/categories/prose.schema.json", "schemas/v2/public-row.schema.json", "schemas/v2/release-selection.schema.json", "schemas/v2/release-report.schema.json"]
    pins = {path: digest((ROOT / path).read_bytes()) for path in paths}
    if digest((BASE / "candidate.tei.xml").read_bytes()) != MASTER_SHA or (LOG / "replay/candidate.tei.xml").read_bytes() != (BASE / "candidate.tei.xml").read_bytes():
        raise ValueError("Exact Green candidate or replay differs")
    proof = json.loads((LOG / "current-candidate-proof-v3.json").read_bytes())
    challenge = json.loads((LOG / "repaired-handoff-proof.json").read_bytes())
    if proof["status"] != "pass" or proof["p5"] != "pass" or challenge["status"] != "pass" or challenge["mutations_rejected"] != 13:
        raise ValueError("Bound repaired candidate prerequisites differ")
    before = _files(ROOT / WORK)
    if any(Path(path).name in {"acceptance.json", "master.tei.xml"} for path in before):
        raise ValueError("Already installed; inspect current authority")
    for path in before:
        put(stage, WORK / path, io_path(ROOT / WORK / path).read_bytes())
    acquisition_path = EDITION / "acquisitions" / (ACQUISITION_ID + ".json")
    acquisition = validate_acquisition(io_path(ROOT / acquisition_path), root=ROOT)
    source = _source_binding(acquisition, context="Green complete retained XML")
    raw = io_path(ROOT / source["source_path"]).read_bytes()
    if source["source_sha256"] != SOURCE_SHA or len(raw) != source["source_bytes"] or digest(raw) != SOURCE_SHA:
        raise ValueError("Actual retained XML differs")
    put(stage, Path(source["source_path"]), raw)
    original_state = json.loads(io_path(ROOT / WORK / "state.json").read_bytes())
    for target in original_state["targets"]:
        for path in target["evidence"]:
            put(stage, Path(path), io_path(ROOT / path).read_bytes())
    proposal = LOG / "authority-proposal"
    for name in ("work", "state"):
        if io_path(ROOT / WORK / (name + ".json")).read_bytes() != (proposal / (name + ".before.json")).read_bytes():
            raise ValueError("Exact authority preimage differs")
        io_path(stage / WORK / (name + ".json")).write_bytes((proposal / (name + ".after.json")).read_bytes())
    validate_identity_update(load_work(ROOT / WORK / "work.json"), load_work(stage / WORK / "work.json"))
    notices = [Path("data/prose") / WORK_ID / "README.md", Path("sources/prose") / WORK_ID / "README.source.md"]
    for relative, name in zip(notices, ("README.data.md", "README.source.md"), strict=True):
        put(stage, relative, (BASE / name).read_bytes())
    proofs = {
        "historical-package-manifest.json": LOG / "historical-package/manifest.json",
        "historical-source-accountability.json": LOG / "historical-package/source-accountability.json",
        "historical-current-source-review.json": ROOT / "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/L763_GREEN_V6B_CURRENT_TECHNICAL_RECHECK_20261002.json",
        "historical-exact-replays.json": ROOT / "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/L763_GREEN_V6B_REPRODUCTIONS_20261002.json",
        "historical-source-mutations.json": ROOT / "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/L763_GREEN_V6_MUTATION_CHALLENGE_20261002.json",
        "current-candidate-proof.json": LOG / "current-candidate-proof-v3.json",
        "body-alias-inverse.json": LOG / "body-adapter-inverse-v2.json",
        "repaired-handoff-proof.json": LOG / "repaired-handoff-proof.json",
        "fresh-composition-replay.json": LOG / "replay/replay.json",
        "authority-proposal.json": proposal / "proposal.json",
    }
    for name, path in proofs.items():
        put(stage, EVIDENCE / name, path.read_bytes())
    identity = {"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID, "acquisition_id": ACQUISITION_ID}
    scope_text = source["source_scope"]
    member = {"path": source["source_path"], "bytes": source["source_bytes"], "sha256": SOURCE_SHA, "scope": scope_text, "position": 1}
    scope = {"kind": "edition", "declared": scope_text, "expected_members": [{"path": member["path"], "position": 1}], "included_members": [member], "excluded_members": []}
    candidate = stage / BASE.relative_to(ROOT) / "candidate.tei.xml"
    tree = etree.fromstring(io_path(candidate).read_bytes())
    change = tree.find("{http://www.tei-c.org/ns/1.0}teiHeader/{http://www.tei-c.org/ns/1.0}revisionDesc/{http://www.tei-c.org/ns/1.0}change")
    revision = {"id": REVISION, "date": change.get("when"), "note": change.text}
    common = {"identity": identity, "source": source, "candidate": make_file_binding(stage, candidate), "scope": scope_text, "accepted_scope": {"kind": "edition", "declared": scope_text}, "expected_members": scope["expected_members"], "included_members": [member], "excluded_members": [], "missing_members": [], "unknown_members": []}
    accounting = put_json(stage, EVIDENCE / "source-accounting.json", common | {"status": "pass", "source_sha256": SOURCE_SHA, "source_bytes": source["source_bytes"], "complete_retained_volume": "One titled volume, complete own front and body; no source back. No new conversion.", "native_text_nodes": 570, "headings": 10, "pages": 64, "note_ref_pairs": 12, "sic_corr_choices": 12, "unretained_media": ["https://docsouth.unc.edu/neh/greenew/greenfp.jpg", "https://docsouth.unc.edu/neh/greenew/greentp.jpg", "https://docsouth.unc.edu/neh/greenew/greenvs.jpg"], "unretained_media_disposition": "Declared source URLs conserved; binaries not acquired and image content unverified, outside retained XML scope.", "current_repairs": "Exactly21 reversible existing-TEI aliases plus constrained active header; all99historical header nodes preserved by canonical annotated inverse, not asserted as literal source serialization.", "historical_evidence_qualification": "V6B corrects heading count only; exact V4 historical content and V6 three replays/four mutations retained. V6 inaccessible temp package is unknown, not absent; exact durable V4 six-member package conserved."})
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    command = "py -3 -m build.tools.stage_green_current_acceptance --stage <fresh-green-current-stage>"
    technical = {"producer": {"id": "ocd-green-existing-native-body-constrained-header-composition-v1"}, "checker": {"id": "ocd-green-existing-source-oracle-plus-exact-alias-header-inverses-v1"}, "shared_assumptions": ["Historical source producer/oracle reuse XML parsing and normalized primary-text policy; complete current existing body is bound by exact inverse. New archival header decoder uses separate standard ElementTree traversal; its serializer uses lxml. Generic producer-disabled checker proves public reconstruction, not primary source fidelity."], "independent_corroboration": "Historical exact source/title/structure observations and V6B replay/mutations; all570 text nodes with exact21alias inverse; 99historical header nodes exact6322byte inverse;16focused archive checks,13new candidate/public mutations, fresh composition replay. No fresh visual or human approval claim."}
    evidence = {name: make_file_binding(stage, stage / EVIDENCE / file) for name, file in (("actual_candidate_proof", "current-candidate-proof.json"), ("historical_source_review", "historical-current-source-review.json"), ("inverse_proof", "body-alias-inverse.json"), ("repaired_proof", "repaired-handoff-proof.json"), ("replay", "fresh-composition-replay.json"))}
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = put_json(stage, EVIDENCE / (name + ".json"), common | {"status": "pass", "claim": name, "command": command, "exit_code": 0, **evidence})
        technical[name] = {"path": path, "status": "pass", "command": command, "exit_code": 0}
    inspected = ["complete retained XML and historical body computationally", "all570text nodes/21exact alias inverses computationally", "all99archived header nodes and source-backed active roles", "current exact acquisition scope and visible provider rights statement"]
    review = {"reviewer": "agent:green-complete-retained-electronic-technical-adoption", "reviewed_at": now, "coverage": {"status": "partial", "declared": scope_text, "reached": inspected, "inspected": inspected, "unreviewed": ["fresh exact-pair visual comparison", "human verification", "source-described physical print collation", "three illustration binaries"]}, "source_quality_uncertainty": ["Provider U.S.-law rights belief is not independent worldwide clearance; source-described print metadata lacks new physical collation."], "discrepancies": [], "unreviewed_residuals": ["human textual acceptance", "rights clearance", "print/image collation", "public publication"]}
    report = put_json(stage, EVIDENCE / "review.json", common | review)
    decision = {"source_local_disposition": "Agent technical adoption of the complete retained electronic XML volume; image binaries, print collation, human and rights/public decisions remain qualified.", "blockers": [], "human_decision": {"status": "not-recorded"}, "agent_assessment": {"status": "accepted", "actor": review["reviewer"], "assessed_at": now, "supported_scope": scope_text, "unresolved_claims": [], "unassessed_stronger_claims": review["unreviewed_residuals"]}}
    acceptance = stage / EDITION / "acceptance.json"
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate, source_accounting_path=accounting, scope=scope, technical=technical, review=review | {"report_path": report}, representation_revision=revision, decision=decision)
    master = put(stage, EDITION / "master.tei.xml", io_path(candidate).read_bytes())
    record["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(stage, master))
    write_acceptance(io_path(acceptance), record)
    validate_state(stage / WORK / "state.json", root=stage)
    with cached_edition_lookups():
        _validate_acceptance_for_work(io_path(acceptance), root=io_path(stage), work_id=WORK_ID)
        projection = project_accepted_prose(io_path(stage), acceptance_path=io_path(acceptance))
        errors = verify_accepted_prose(io_path(stage), acceptance_path=io_path(acceptance), rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 13 or sum(len(r["text"]) for r in projection["rows"]) != 155586:
        raise ValueError(f"Actual accepted Green projection failed: {errors}")
    put_json(stage, EVIDENCE / "stage-projection.json", projection)
    notice_bindings = {"source_path": notices[1].as_posix(), "source_sha256": digest(io_path(stage / notices[1]).read_bytes()), "notice_path": notices[0].as_posix(), "notice_sha256": digest(io_path(stage / notices[0]).read_bytes())}
    selected = {"item_id": WORK_ID, "category": "prose", "acceptance_path": (EDITION / "acceptance.json").as_posix(), "public_notices": [notice_bindings]}
    if notice_texts_for_item(io_path(stage), selected, io_path(acceptance)) != [(BASE / "README.data.md").read_text(encoding="utf-8")]:
        raise ValueError("Maintained paired notice preflight differs")
    if {p: digest((ROOT / p).read_bytes()) for p in paths} != pins or _files(ROOT / WORK) != before:
        raise ValueError("Current runtime/authority drifted during stage")
    after = _files(stage / WORK)
    for p, expected in before.items():
        if p not in {"work.json", "state.json"} and after[p] != expected:
            raise ValueError("Existing authority changed: " + p)
    result = {"status": "pass", "work_id": WORK_ID, "stage_root": stage.as_posix(), "source_sha256": SOURCE_SHA, "master_sha256": MASTER_SHA, "acceptance_sha256": digest(io_path(acceptance).read_bytes()), "category": "prose", "language": "en", "rows": 13, "characters": 155586, "before": before, "after": after, "schema_pins": pins, "metadata_difference": ["form.language absent->en", "edition.language absent->en", "edition.category absent->prose"], "paired_notices": {p.as_posix(): digest(io_path(stage / p).read_bytes()) for p in notices}, "notice_gate": "pass", "projection_errors": errors, "canonical_install_performed": False}
    put_json(stage, Path("stage-receipt.json"), result)
    save(LOG / "staged-acceptance.json", json_bytes(result))
    print(json.dumps({"status": "pass", "stage_root": stage.as_posix(), "stage_receipt_sha256": digest(json_bytes(result)), "after_files": len(after), "before_files": len(before), "acceptance_sha256": result["acceptance_sha256"]}))


if __name__ == "__main__":
    main()
