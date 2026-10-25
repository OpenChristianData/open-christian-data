"""Stage Smith's exact retained electronic witness for private technical adoption."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import _files


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "smiths-bible-dictionary"
FORM_ID = "smiths-bible-dictionary-retained-electronic"
EDITION_ID = "smiths-bible-dictionary-retained-electronic-witness"
ACQUISITION_ID = "smiths-bible-dictionary-retained-source"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
INTEGRATION = WORK / "integration/smith-current-v1"
SOURCE = Path("raw/bible_dictionaries/smiths.jsonl")
STAGE = ROOT / ".sm"
OUT = ROOT / "reports/_logs/smiths-bible-dictionary-current-reconciliation-20261002-v1"
HISTORICAL = Path("D:/Library/Open Christian Data/candidate-reviews/jwbickel-dictionaries-20260928-v1/smiths-bible-dictionary")
ROOT_REVIEW = ROOT / "reports/_logs/smith-coordinator-source-review-20261002-v1/review.json"
MASTER_SHA = "c4f3ff3a981f30dd816e6904af014e7eceb619d419f0f4f478fb1dcb34d43d8e"
SOURCE_SHA = "ac91b1c3c359690c2953bd94b9d3dcb34f012a69d734179e82be5f07866cbe0d"
HISTORICAL_SHA = "1ad08fbda35f1445c5c5546493fd2241acbc5a7669d56a99dbf4fb02f293a690"
CATEGORY_SHA = "386cafb583171fb3bf36461a7e0427fb57e292cbf3f528556771d2428d842a81"
ADAPTER_SHA = "37addf99c4327533995f185d15b3a0b56ce63fb4ea6e2f7a4584e94995e25e08"
REVIEW_SHA = "67872b5d84a9dcaf43a8c5aaf3d23bdf37bd990727be6edd82b23c761d0d288a"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")


def copy_relative(path: Path) -> None:
    source = ROOT / path
    destination = STAGE / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if digest(source) != digest(destination):
        raise ValueError(f"Smith stage copy differs: {path}")


def main() -> None:
    if STAGE.exists() or (OUT / "staged-acceptance.json").exists():
        raise FileExistsError("Smith stage exists; inspect it before any continuation")
    guards = {
        ROOT / "ocd_kernel/projection/categories/reference_entries.py": ADAPTER_SHA,
        ROOT / WORK / "work.json": CATEGORY_SHA,
        ROOT / SOURCE: SOURCE_SHA,
        ROOT / INTEGRATION / "candidate.tei.xml": MASTER_SHA,
        HISTORICAL / "package/content.tei.xml": HISTORICAL_SHA,
        ROOT_REVIEW: REVIEW_SHA,
    }
    for path, expected in guards.items():
        if digest(path) != expected:
            raise ValueError(f"Smith acceptance input drifted: {path}")
    acquisition = validate_acquisition(ROOT / EDITION / "acquisitions" / f"{ACQUISITION_ID}.json", root=ROOT)
    members = acquisition["retained_files"]
    if len(members) != 1 or members[0]["path"] != SOURCE.as_posix() or members[0]["sha256"] != SOURCE_SHA:
        raise ValueError("Smith retained member differs")
    member = members[0]
    scope_text = member["scope"]
    if scope_text != acquisition["source_scope"]:
        raise ValueError("Smith acquisition scope differs")
    accounting = json.loads((ROOT / INTEGRATION / "source-accounting.json").read_text(encoding="utf-8"))
    renewal = json.loads((ROOT / INTEGRATION / "header-renewal.json").read_text(encoding="utf-8"))
    review_proof = json.loads(ROOT_REVIEW.read_text(encoding="utf-8"))
    if (accounting["candidate_master_sha256"] != MASTER_SHA
            or accounting["source_sha256"] != SOURCE_SHA
            or accounting["projection_context"]["source_scope"] != scope_text
            or accounting["projection_context"]["source_unit_count"] != 4560
            or accounting["definition_count"] != 5362
            or accounting["projection_context"]["source_selector"] != {"tei_entry_profile": "smith-native-lexical-v1"}
            or renewal["candidate_sha256"] != MASTER_SHA
            or renewal["body_bytes_identical"] is not True
            or renewal["parsed_text_tree_identical"] is not True
            or review_proof["status"] != "pass"
            or review_proof["source_entries"] != 4560
            or review_proof["ordered_definition_blocks"] != 5362):
        raise ValueError("Smith current source/header proof differs")
    validation = json.loads((HISTORICAL / "validation.json").read_text(encoding="utf-8"))
    if validation.get("status") != "pass" or validation.get("findings") or validation.get("candidate_sha256") != "e417a0cb23d7b385eca0f8abf9f4c81b606987b61408a6a72ee1a1f1fc2779c5":
        raise ValueError("Smith historical candidate validation differs")
    preimage = _files(ROOT / WORK)
    if any(path.endswith(("master.tei.xml", "acceptance.json")) for path in preimage):
        raise ValueError("Canonical Smith authority already accepted")
    STAGE.mkdir(parents=True)
    shutil.copytree(ROOT / WORK, STAGE / WORK)
    for path, expected in preimage.items():
        if digest(STAGE / WORK / path) != expected:
            raise ValueError(f"Smith copied preimage differs: {path}")
    copy_relative(SOURCE)
    state = json.loads((ROOT / WORK / "state.json").read_text(encoding="utf-8"))
    for target in state["targets"]:
        for path in target["evidence"]:
            relative = Path(path)
            if not (STAGE / relative).exists():
                copy_relative(relative)
    evidence = STAGE / INTEGRATION / "acceptance-evidence"
    evidence.mkdir(parents=True)
    historical_evidence = {
        "historical-validation.json": HISTORICAL / "validation.json",
        "historical-package-manifest.json": HISTORICAL / "package/manifest.json",
        "historical-crosswalk.json": HISTORICAL / "package/source-accountability.json",
        "coordinator-source-review.json": ROOT_REVIEW,
    }
    for name, source in historical_evidence.items():
        shutil.copy2(source, evidence / name)
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    tree = etree.parse(str(STAGE / INTEGRATION / "candidate.tei.xml"), parser)
    xsd = etree.XMLSchema(etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"), parser))
    if not xsd.validate(tree):
        raise ValueError(f"Smith master fails TEI P5 XSD: {xsd.error_log.last_error}")
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    if len(tree.xpath("./tei:text/tei:body/tei:entry", namespaces=ns)) != 4560:
        raise ValueError("Smith stage entry count differs")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    identity = {"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID, "acquisition_id": ACQUISITION_ID}
    scope = {"kind": "edition", "declared": scope_text, "expected_members": [{"path": SOURCE.as_posix(), "position": 1}], "included_members": [{key: member[key] for key in ("path", "bytes", "sha256", "scope")} | {"position": 1}], "excluded_members": []}
    source_binding = {"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA, "source_bytes": member["bytes"], "source_scope": scope_text}
    candidate_binding = make_file_binding(STAGE, STAGE / INTEGRATION / "candidate.tei.xml")
    acceptance_context = {"identity": identity, "candidate": candidate_binding, "scope": scope_text, "source": source_binding, "accepted_scope": {"kind": "edition", "declared": scope_text}, "expected_members": scope["expected_members"], "included_members": scope["included_members"], "excluded_members": [], "missing_members": [], "unknown_members": []}
    accounting_path = evidence / "current-source-accounting.json"
    write_json(accounting_path, accounting | acceptance_context | {"source_sha256": SOURCE_SHA, "source_bytes": member["bytes"]})
    bindings = {"source_accounting": make_file_binding(STAGE, accounting_path), "coordinator_source_review": make_file_binding(STAGE, evidence / "coordinator-source-review.json"), "historical_validation": make_file_binding(STAGE, evidence / "historical-validation.json"), "header_renewal": make_file_binding(STAGE, STAGE / INTEGRATION / "header-renewal.json")}
    technical: dict = {
        "producer": {"id": "jwbickel-smith-retained-jsonl-to-native-tei; header-only-current-binding"},
        "checker": {"id": "coordinator-independent-full-jsonl-native-entry-review"},
        "shared_assumptions": ["The historical converter and candidate validation share the retained JSONL selection; current coordinator direct comparison and native independent checker constrain this selection."],
        "independent_corroboration": "Coordinator comparison covers all 4,560 literal headwords and 5,362 ordered definitions; header-only renewal conserves body bytes and parsed text tree.",
    }
    descriptions = {
        "validation": "Historical validation passes with zero findings; current header-only master passes TEI P5 XSD.",
        "accounting": "Current census binds all 4,560 source lines and 5,362 ordered definitions to exact source member and master.",
        "fidelity": "Coordinator independent source comparison covers all literal terms, ordered definitions, IDs and text subtree; body bytes are unchanged.",
        "reproducibility": "Retained source, historical package, source crosswalk, and current header renewal are hash-bound.",
        "schema": "Smith header-bound native lexical TEI passes vendored TEI P5 XSD.",
        "closure": "Technical scope is the exact retained electronic witness; identified print witness, modern reuse terms, human acceptance and publication remain unresolved.",
    }
    common = {"status": "pass", "command": "py -3 -m build.tools.stage_smith_current_acceptance", "exit_code": 0, "checked_at": now, **bindings, "adapter_sha256": ADAPTER_SHA, **acceptance_context}
    for name, description in descriptions.items():
        path = evidence / f"{name}.json"
        write_json(path, {**common, "kind": name, "description": description})
        technical[name] = {"path": path, "status": "pass", "command": common["command"], "exit_code": 0}
    review_path = evidence / "review.json"
    review = {"report_path": review_path, "reviewer": "agent:smith-current-technical-adoption", "reviewed_at": now, "coverage": {"status": "partial", "declared": scope_text, "reached": ["retained JSONL", "native TEI"], "inspected": ["retained JSONL/all 4,560 rows", "native TEI/all 5,362 ordered definitions"], "unreviewed": ["full exact-pair human visual collation", "identified print witness"]}, "source_quality_uncertainty": ["No identified print edition has been collated.", "Modern structured JSONL reuse terms remain unresolved."], "discrepancies": [], "unreviewed_residuals": ["full exact-pair human visual collation", "rights clearance", "publication authorization"]}
    write_json(review_path, {**common, "kind": "technical-review", "visual_scope": "Complete exact-pair comparison is computational; full human visual collation is unreviewed.", **{key: review[key] for key in ("reviewer", "reviewed_at", "coverage", "source_quality_uncertainty", "discrepancies", "unreviewed_residuals")}})
    decision = {"source_local_disposition": "Agent technical adoption of exact retained electronic member only; no human rights clearance or publication authorization.", "blockers": [], "agent_assessment": {"status": "accepted", "actor": review["reviewer"], "assessed_at": now, "supported_scope": scope_text, "unresolved_claims": [], "unassessed_stronger_claims": ["human textual acceptance", "identified print edition", "structured-source rights clearance", "public publication"]}, "human_decision": {"status": "not-recorded"}}
    record = build_acceptance_record(STAGE, identity=identity, candidate_path=STAGE / INTEGRATION / "candidate.tei.xml", source_accounting_path=accounting_path, scope=scope, technical=technical, review=review, representation_revision=renewal["representation_revision"], decision=decision)
    acceptance = STAGE / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=STAGE)
    master = STAGE / EDITION / "master.tei.xml"
    shutil.copy2(STAGE / INTEGRATION / "candidate.tei.xml", master)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(STAGE, master))
    write_acceptance(acceptance, record)
    staged_state = json.loads((STAGE / WORK / "state.json").read_text(encoding="utf-8"))
    editions = [item for item in staged_state["targets"] if item["target_type"] == "edition" and item["target_id"] == EDITION_ID]
    if len(editions) != 1 or editions[0]["stage"] != "acquired":
        raise ValueError("Smith stage edition state differs")
    editions[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    editions[0]["evidence"].extend([master.relative_to(STAGE).as_posix(), acceptance.relative_to(STAGE).as_posix()])
    write_json(STAGE / WORK / "state.json", staged_state)
    validate_acceptance(acceptance, root=STAGE)
    validate_state(STAGE / WORK / "state.json", root=STAGE)
    load_work(STAGE / WORK / "work.json")
    after = _files(STAGE / WORK)
    for path, expected in preimage.items():
        if path != "state.json" and after.get(path) != expected:
            raise ValueError(f"Smith staged authority changed existing file: {path}")
    result = {"contract": "ocd-smith-current-staged-acceptance-v1", "status": "staged-only", "work_id": WORK_ID, "stage_root": str(STAGE), "source_sha256": SOURCE_SHA, "master_sha256": MASTER_SHA, "acceptance_sha256": digest(acceptance), "current_work_before": preimage, "staged_work_after": after, "canonical_install_performed": False, "rights_clearance": "unresolved", "publication_authorized": False}
    write_json(OUT / "staged-acceptance.json", result)
    print(json.dumps({"status": result["status"], "acceptance_sha256": result["acceptance_sha256"], "staged_file_count": len(after)}, sort_keys=True))


if __name__ == "__main__":
    main()
