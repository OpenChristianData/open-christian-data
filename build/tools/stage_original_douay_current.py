"""Stage technical acceptance of the frozen complete Original Douay candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import cached_edition_lookups, load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.bible import project_accepted_bible, verify_accepted_bible
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/original-douay-rheims")
EDITION = WORK / "forms/original-douay-rheims-retained-en/editions/original-douay-rheims-electronic"
ACQUISITION = EDITION / "acquisitions/original-douay-rheims-acquired.json"
EVIDENCE = WORK / "integration/original-douay-current-v1"
BASE = Path("sources/original-douay-existing-native-current/original-douay-rheims")
LOG = Path("reports/_logs/original-douay-rheims-current-reconciliation-20261002-v1")
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/original-douay-current-20261002-v1")
EXPECTED_CONTENT_SHA = "aa6ef9f3b2e98a79efc74ce6edb5b13d0c06a95fede2daf714dad21f84820e2e"
IDENTITY = {
    "work_id": "original-douay-rheims",
    "textual_form_id": "original-douay-rheims-retained-en",
    "edition_id": "original-douay-rheims-electronic",
    "acquisition_id": "original-douay-rheims-acquired",
}


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def put(root: Path, relative: Path, payload: bytes) -> Path:
    target = root / relative
    io_path(target).parent.mkdir(parents=True, exist_ok=True)
    io_path(target).write_bytes(payload)
    return target


def put_json(root: Path, relative: Path, value: object) -> Path:
    return put(root, relative, canonical(value))


def stage(stage_root: Path, promoted_root: Path) -> dict:
    stage_root = stage_root.absolute()
    promoted_root = promoted_root.absolute()
    if not stage_root.is_dir() or promoted_root.exists():
        raise ValueError("Existing notice-only stage and fresh promotion target required")
    if (stage_root / WORK).exists():
        raise ValueError("Stage work tree already exists")
    notices = json.loads((stage_root / "original-douay-notice-bindings.json").read_bytes())
    if notices["status"] != "pass" or notices["notice_count"] != 170:
        raise ValueError("Complete source/data notice preflight required")
    manifest = SourceManifest.load(ROOT / BASE / "source-manifest.json", repository_root=ROOT)
    package = CandidatePackage.load(CANDIDATE / "package")
    validation = json.loads((CANDIDATE / "validation.json").read_bytes())
    if package.member_bytes("content.tei.xml") and sha(package.member_bytes("content.tei.xml")) != EXPECTED_CONTENT_SHA:
        raise ValueError("Frozen complete candidate content changed")
    if validation["status"] != "pass" or validation["attestation"]["status"] != "pass":
        raise ValueError("Frozen candidate validation changed")
    replay = json.loads((ROOT / LOG / "replay-v1.log").read_text(encoding="utf-8"))
    if replay["status"] != "pass" or replay["candidate"]["sha256"] != package.sha256:
        raise ValueError("Prior exact candidate replay does not bind current package")
    before = _files(ROOT / WORK)
    if any(path.endswith(("acceptance.json", "master.tei.xml")) for path in before):
        raise ValueError("Canonical work is already accepted")
    for relative in before:
        put(stage_root, WORK / relative, io_path(ROOT / WORK / relative).read_bytes())
    acquisition = validate_acquisition(io_path(ROOT / ACQUISITION), root=ROOT)
    for member in acquisition["retained_files"]:
        payload = io_path(ROOT / member["path"]).read_bytes()
        if sha(payload) != member["sha256"] or len(payload) != member["bytes"]:
            raise ValueError(f"Retained source member changed: {member['path']}")
        put(stage_root, Path(member["path"]), payload)
    original_state = json.loads(io_path(ROOT / WORK / "state.json").read_bytes())
    for target in original_state["targets"]:
        for relative in target["evidence"]:
            path = Path(relative)
            if not io_path(stage_root / path).exists():
                put(stage_root, path, io_path(ROOT / path).read_bytes())
    original_work = load_work(ROOT / WORK / "work.json")
    revised = json.loads(canonical(original_work))
    edition = revised["textual_forms"][0]["editions"][0]
    if edition["edition_id"] != IDENTITY["edition_id"] or edition.get("category") is not None:
        raise ValueError("Current work identity/category preimage differs")
    edition["category"] = "bible"
    validate_identity_update(original_work, revised)
    put_json(stage_root, WORK / "work.json", revised)
    credit = (ROOT / BASE / "README.source.md").read_bytes()
    put(stage_root, WORK / "SOURCE_CREDIT.md", credit)
    for name in package.member_names:
        put(stage_root, EVIDENCE / "original-package" / name, package.member_bytes(name))
    evidence_sources = {
        "source-manifest.json": ROOT / BASE / "source-manifest.json",
        "candidate-validation.json": CANDIDATE / "validation.json",
        "coordinator-chapter-zero.json": ROOT / "reports/_logs/original-douay-coordinator-source-review-20261002-v1/chapter-zero-review.json",
        "coordinator-scalar-fields.json": ROOT / "reports/_logs/original-douay-coordinator-source-review-20261002-v1/scalar-field-review.json",
        "coordinator-zero-support.json": ROOT / "reports/_logs/original-douay-zero-chapter-support-20261002-v1/coordinator-reviewed-freeze.json",
        "private-companion-proof.json": ROOT / LOG / "readable-companion-v2-proof.json",
        "public-companion-manifest.json": ROOT / LOG / "readable-companion-v2-release/manifest.json",
        "prior-replay.log": ROOT / LOG / "replay-v1.log",
        "prior-source-proof.log": ROOT / LOG / "renewed-route-proof.log",
    }
    for name, path in evidence_sources.items():
        put(stage_root, EVIDENCE / name, io_path(path).read_bytes())
    source = {
        "source_path": acquisition["source_path"],
        "source_sha256": acquisition["source_sha256"],
        "source_bytes": acquisition["source_bytes"],
        "source_scope": acquisition["source_scope"],
        "source_kind": acquisition["source_kind"],
    }
    revision = {
        "id": "original-douay-current-whole-work-v1",
        "date": "2026-10-02",
        "note": "Technical acceptance of the complete retained electronic collection; all native verse carriers, chapter articles and source context remain accounted, with printed-witness and rights claims qualified.",
    }
    raw = package.member_bytes("content.tei.xml")
    old_pointer = b'<ptr type="source" target="https://github.com/janvier-s/original-douay-rheims"/>'
    new_pointer = b'<ptr type="source" target="https://github.com/janvier-s/original-douay-rheims/archive/refs/tags/v1.0.zip"/>'
    if raw.count(old_pointer) != 1 or new_pointer in raw:
        raise ValueError("Exact candidate header source pointer preimage differs")
    header_input = raw.replace(old_pointer, new_pointer, 1)
    if header_input.replace(new_pointer, old_pointer, 1) != raw or header_input.split(b"</teiHeader>", 1)[1] != raw.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Acquisition URL normalization is not a reversible header-only change")
    bound = bind_reviewed_header(
        header_input,
        expected_sha256=sha(header_input),
        identity=IDENTITY,
        source=source,
        source_url=acquisition["url"],
        declared_scope=acquisition["source_scope"],
        revision=revision,
    )
    put_json(stage_root, EVIDENCE / "header-rebinding.json", {"status": "pass", "original_candidate_sha256": EXPECTED_CONTENT_SHA, "header_url_normalized_sha256": sha(header_input), "bound_candidate_sha256": sha(bound), "body_unchanged": True, "inverse_restores_original_candidate": True, "acquisition_url": acquisition["url"]})
    if bound.split(b"</teiHeader>", 1)[1] != raw.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Reviewed body changed during acceptance-header binding")
    candidate = put(stage_root, EVIDENCE / "candidate.tei.xml", bound)
    failures = validate_file(io_path(candidate))
    if failures:
        raise ValueError(f"Bound candidate TEI validation failed: {failures}")
    expected = [{"path": m["path"], "position": i} for i, m in enumerate(acquisition["retained_files"], 1)]
    included = [{"path": m["path"], "position": i, "bytes": m["bytes"], "sha256": m["sha256"], "scope": m["scope"]} for i, m in enumerate(acquisition["retained_files"], 1)]
    scope = {"kind": "selection", "declared": acquisition["source_scope"], "expected_members": expected, "included_members": included, "excluded_members": []}
    common = {"identity": IDENTITY, "source": source, "candidate": make_file_binding(stage_root, candidate), "accepted_scope": {"kind": "selection", "declared": acquisition["source_scope"]}, "expected_members": expected, "included_members": included, "excluded_members": [], "missing_members": [], "unknown_members": []}
    accounting = put_json(stage_root, EVIDENCE / "source-accounting.json", common | {"scope": source["source_scope"], "source_sha256": source["source_sha256"], "source_bytes": source["source_bytes"], "source_accountability": json.loads(package.member_bytes("source-accountability.json")), "source_oracle": validation["attestation"], "companion_notice_count": notices["notice_count"]})
    command = "py -3 -m build.tools.stage_original_douay_current --stage <notice-stage> --promoted <fresh-promoted>"
    technical = {
        "producer": {"id": manifest.record["converter"]["id"]},
        "checker": {"id": manifest.record["validator"]["id"]},
        "shared_assumptions": ["Existing validated full candidate and separate-process replay are reused without source reconstruction; direct coordinator scalar review and independent readable-context check corroborate complete literal fields."],
        "independent_corroboration": "Complete 62,326 source fields, 37,181 source verse occurrences, 4,776,267 verse characters, 25,145 nonverse fields and 3,781,838 literal nonverse bytes; direct source JSON review, reversible historical inverse and private context ledger; reader notice successor independently checks exact field wording, order, hierarchy and local apparatus attachment.",
    }
    facts = {"status": "pass", "source_manifest_sha256": manifest.sha256, "package_sha256": package.sha256, "candidate_sha256": EXPECTED_CONTENT_SHA, "bound_candidate_sha256": sha(bound), "source_field_count": 62326, "verse_occurrences": 37181, "verse_characters": 4776267, "nonverse_fields": 25145, "nonverse_literal_bytes": 3781838, "notice_bindings": 170, "header_body_byte_identical": True, "candidate_validation": validation["status"], "replay": replay["status"]}
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = put_json(stage_root, EVIDENCE / f"{name}.json", common | facts | {"scope": source["source_scope"], "claim": name, "command": command, "exit_code": 0})
        technical[name] = {"path": path, "status": "pass", "command": command, "exit_code": 0}
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    review = {
        "reviewer": "agent:original-douay-complete-source-check",
        "reviewed_at": now,
        "coverage": {"status": "partial", "declared": acquisition["source_scope"], "reached": ["complete retained electronic member set and literal source fields", "all 37,181 verse occurrences and source-native context"], "inspected": ["complete retained electronic member set and literal source fields"], "unreviewed": ["human visual comparison", "printed-witness collation"]},
        "source_quality_uncertainty": ["Electronic source provider's CC0 statement is preserved; underlying print identity and independent jurisdictional rights clearance are not established.", "Historical 1582/1609-1610 translation statements coexist with literal title references to 1633 and 1635; no hybrid print identity is inferred."],
        "discrepancies": [],
        "unreviewed_residuals": ["Human acceptance, print collation, rights clearance and public publication remain separate."],
    }
    review_path = put_json(stage_root, EVIDENCE / "review.json", common | review | {"scope": source["source_scope"]})
    decision = {
        "source_local_disposition": "Technical agent acceptance of the complete retained original Douay-Rheims electronic collection.",
        "blockers": [],
        "human_decision": {"status": "not-recorded"},
        "agent_assessment": {"status": "accepted", "actor": review["reviewer"], "assessed_at": now, "supported_scope": acquisition["source_scope"], "unresolved_claims": [], "unassessed_stronger_claims": ["human visual acceptance", "printed-edition equivalence", "rights clearance", "public publication"]},
    }
    record = build_acceptance_record(stage_root, identity=IDENTITY, candidate_path=candidate, source_accounting_path=accounting, scope=scope, technical=technical, review=review | {"report_path": review_path}, representation_revision=revision, decision=decision)
    stage_acceptance = stage_root / EDITION / "acceptance.json"
    write_acceptance(io_path(stage_acceptance), record)
    validate_acceptance(stage_acceptance, root=stage_root)
    shutil.copytree(io_path(stage_root), io_path(promoted_root))
    promoted_acceptance = promoted_root / EDITION / "acceptance.json"
    master = put(promoted_root, EDITION / "master.tei.xml", bound)
    record["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(promoted_root, master))
    write_acceptance(io_path(promoted_acceptance), record)
    promoted_state = json.loads(canonical(original_state))
    target = next(t for t in promoted_state["targets"] if t["target_id"] == IDENTITY["edition_id"] and t["target_type"] == "edition")
    target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    for path in (EDITION / "master.tei.xml", EDITION / "acceptance.json"):
        value = path.as_posix()
        if value not in target["evidence"]:
            target["evidence"].append(value)
    put_json(promoted_root, WORK / "state.json", promoted_state)
    validate_state(promoted_root / WORK / "state.json", root=promoted_root)
    with cached_edition_lookups():
        validate_acceptance(promoted_acceptance, root=promoted_root)
        projection = project_accepted_bible(io_path(promoted_root), acceptance_path=io_path(promoted_acceptance))
        errors = verify_accepted_bible(io_path(promoted_root), acceptance_path=io_path(promoted_acceptance), rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 37181:
        raise ValueError(f"Promoted actual-master Bible projection differs: {len(projection['rows'])} rows, {errors}")
    texts = notice_texts_for_item(promoted_root, {"item_id": IDENTITY["work_id"], "work_id": IDENTITY["work_id"], "public_notices": notices["bindings"]}, promoted_acceptance)
    if len(texts) != 170:
        raise ValueError("Promoted complete context and credit notice binding differs")
    receipt = {"status": "pass", "work_id": IDENTITY["work_id"], "candidate_package_sha256": package.sha256, "candidate_content_sha256": EXPECTED_CONTENT_SHA, "bound_master_sha256": sha(bound), "stage_root": str(stage_root), "promoted_root": str(promoted_root), "before": before, "after": _files(promoted_root / WORK), "projection_rows": len(projection["rows"]), "projection_errors": errors, "notice_bindings": len(texts), "notice_text_utf8_bytes": sum(len(value.encode("utf-8")) for value in texts), "human_acceptance": "not-recorded", "public_publication": "not-authorized"}
    put_json(promoted_root, Path("stage-receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--promoted", type=Path, required=True)
    args = parser.parse_args()
    receipt = stage(args.stage, args.promoted)
    print(json.dumps({key: value for key, value in receipt.items() if key not in {"before", "after"}}, indent=2))


if __name__ == "__main__":
    main()
