"""Stage the source-bound Easton electronic witness without installing it."""

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
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "eastons-bible-dictionary"
FORM_ID = "eastons-bible-dictionary-retained-electronic"
EDITION_ID = "eastons-bible-dictionary-retained-electronic-witness"
ACQUISITION_ID = "eastons-bible-dictionary-retained-source"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
INTEGRATION = WORK / "integration/easton-current-v1"
SOURCE = Path("raw/bible_dictionaries/eastons.jsonl")
STAGE = ROOT / ".h"
OUT = ROOT / "reports/_logs/eastons-bible-dictionary-current-reconciliation-20261002-v1"
HISTORICAL = Path("D:/Library/Open Christian Data/candidate-reviews/jwbickel-dictionaries-20260928-v1/eastons-bible-dictionary")
MASTER_SHA = "11e86481620c1edea9bdf6a291ef4cd7bb83bbc4324838a78ed1062722feb257"
SOURCE_SHA = "978e09fdb66e9c6b722085f868c0cc84030df9e15c6188a06390f3822888082a"
ADAPTER_SHA = "ba8a1886ca39b06ba47adb5c4c06c24d118a24612385c0fc4673c212994c88bc"
CATEGORY_SHA = "92f234ea0c784dfd6eef203a5e9c10c9f3bada6e72f9e74474a3eb25db1d7cc2"


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
        raise ValueError(f"stage copy differs: {path}")


def main() -> None:
    if STAGE.exists():
        raise FileExistsError("Easton stage already exists; inspect it instead of overwriting")
    if digest(ROOT / "ocd_kernel/projection/categories/reference_entries.py") != ADAPTER_SHA:
        raise ValueError("reviewed Easton adapter drifted")
    if digest(ROOT / WORK / "work.json") != CATEGORY_SHA:
        raise ValueError("reviewed Easton category metadata drifted")
    if digest(ROOT / SOURCE) != SOURCE_SHA or digest(ROOT / INTEGRATION / "candidate-v2.tei.xml") != MASTER_SHA:
        raise ValueError("Easton retained source or staged TEI drifted")
    acquisition = validate_acquisition(ROOT / EDITION / "acquisitions" / f"{ACQUISITION_ID}.json", root=ROOT)
    member = acquisition["retained_files"]
    if len(member) != 1 or member[0]["path"] != SOURCE.as_posix() or member[0]["sha256"] != SOURCE_SHA:
        raise ValueError("Easton acquisition member differs")
    scope_text = member[0]["scope"]
    if scope_text != acquisition["source_scope"]:
        raise ValueError("Easton acquisition scopes differ")
    source_accounting = json.loads((ROOT / INTEGRATION / "source-accounting-v2.json").read_text(encoding="utf-8"))
    source_proof = json.loads((ROOT / INTEGRATION / "source-proof.json").read_text(encoding="utf-8"))
    if (source_accounting["projection_context"]["source_scope"] != scope_text
            or source_accounting["projection_context"]["source_unit_count"] != 3963
            or source_accounting["definition_count"] != 7464
            or source_proof["status"] != "pass"):
        raise ValueError("Easton current source accounting/proof differs")
    validation_source = HISTORICAL / "validation.json"
    validation = json.loads(validation_source.read_text(encoding="utf-8"))
    if validation.get("status") != "pass" or validation.get("findings") or validation.get("candidate_sha256") != "6aa27e6bea06153dd61b6802cbe70434921fad2b98bdd176ebf0a37a56da3a9b":
        raise ValueError("original candidate validation differs")
    if digest(HISTORICAL / "package/content.tei.xml") != "79ed9b76699611e8816ca713ac1c645083d73ea06fb6f19e5f2a1faceeee3240":
        raise ValueError("original candidate changed")
    renewal = json.loads((ROOT / INTEGRATION / "header-renewal.json").read_text(encoding="utf-8"))
    scope_renewal = json.loads((ROOT / INTEGRATION / "header-scope-v2.json").read_text(encoding="utf-8"))
    if not scope_renewal["native_body_bytes_identical"] or not scope_renewal["parsed_text_tree_identical"] or scope_renewal["candidate_sha256"] != MASTER_SHA:
        raise ValueError("header-only renewal proof differs")
    preimage = _files(ROOT / WORK)
    if any(path.endswith(("master.tei.xml", "acceptance.json")) for path in preimage):
        raise ValueError("canonical Easton already has accepted authority")
    STAGE.mkdir(parents=True)
    shutil.copytree(ROOT / WORK, STAGE / WORK)
    for path, expected in preimage.items():
        if digest(STAGE / WORK / path) != expected:
            raise ValueError(f"work preimage copy differs: {path}")
    copy_relative(SOURCE)
    state = json.loads((ROOT / WORK / "state.json").read_text(encoding="utf-8"))
    for target in state["targets"]:
        for path in target["evidence"]:
            relative = Path(path)
            if not (STAGE / relative).exists():
                copy_relative(relative)
    evidence = STAGE / INTEGRATION / "acceptance-evidence"
    evidence.mkdir(parents=True)
    shutil.copy2(validation_source, evidence / "historical-validation.json")
    shutil.copy2(HISTORICAL / "package/manifest.json", evidence / "historical-package-manifest.json")
    shutil.copy2(HISTORICAL / "package/source-accountability.json", evidence / "historical-crosswalk.json")
    visual_source = ROOT / "plans/2026-08-31-sample-first-library-verification/27-eastons-bible-dictionary-visual-review.md"
    shutil.copy2(visual_source, evidence / "prior-visual-review.md")
    source_proof_binding = make_file_binding(STAGE, STAGE / INTEGRATION / "source-proof.json")
    accounting_binding = make_file_binding(STAGE, STAGE / INTEGRATION / "source-accounting-v2.json")
    validation_binding = make_file_binding(STAGE, evidence / "historical-validation.json")
    visual_binding = make_file_binding(STAGE, evidence / "prior-visual-review.md")
    header_binding = make_file_binding(STAGE, STAGE / INTEGRATION / "header-scope-v2.json")
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    tei_tree = etree.parse(str(STAGE / INTEGRATION / "candidate-v2.tei.xml"), parser)
    xsd_tree = etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"), parser)
    xsd = etree.XMLSchema(xsd_tree)
    if not xsd.validate(tei_tree):
        raise ValueError(f"Easton prepared master fails TEI P5 XSD: {xsd.error_log.last_error}")
    if len(tei_tree.xpath("./tei:text/tei:body/tei:entry", namespaces=ns)) != 3963:
        raise ValueError("Easton stage master has a changed entry count")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    identity = {"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID, "acquisition_id": ACQUISITION_ID}
    scope = {"kind": "edition", "declared": scope_text, "expected_members": [{"path": SOURCE.as_posix(), "position": 1}], "included_members": [{key: member[0][key] for key in ("path", "bytes", "sha256", "scope")} | {"position": 1}], "excluded_members": []}
    source_binding = {"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA, "source_bytes": member[0]["bytes"], "source_scope": scope_text}
    candidate_binding = make_file_binding(STAGE, STAGE / INTEGRATION / "candidate-v2.tei.xml")
    acceptance_context = {"identity": identity, "candidate": candidate_binding, "scope": scope_text, "source": source_binding, "accepted_scope": {"kind": "edition", "declared": scope_text}, "expected_members": scope["expected_members"], "included_members": scope["included_members"], "excluded_members": [], "missing_members": [], "unknown_members": []}
    source_accounting_path = evidence / "current-source-accounting.json"
    write_json(source_accounting_path, source_accounting | acceptance_context | {"source_sha256": SOURCE_SHA, "source_bytes": member[0]["bytes"]})
    technical: dict = {
        "producer": {"id": "ocd-eastons-bible-dictionary-source-to-tei-v1; header-only-current-binding"},
        "checker": {"id": "ocd-eastons-bible-dictionary-independent-oracle; current-source-proof-v1"},
        "shared_assumptions": ["Historical converter and oracle share the retained JSONL member; the current line-by-line source proof, complete crosswalk, visual anchors, and independently traversed reference projection constrain that shared selection."],
        "independent_corroboration": "Historical independent oracle and visual review plus current exact JSONL-to-native-TEI comparison cover all 3,963 entries and 7,464 ordered definitions; current native projection and independent lxml checker pass.",
    }
    descriptions = {
        "validation": "Historical independent candidate validation passed with zero findings; current TEI differs only in the separately checked header.",
        "accounting": "Current source-proof compares all JSONL lines, terms, definition order, n attributes, and IDs to the header-bound TEI.",
        "fidelity": "Original and current parsed text trees are identical, and the current complete source proof passes.",
        "reproducibility": "The retained original package and source hashes are pinned; the current header renewal conserves exact body bytes.",
        "schema": "The header-bound candidate passes the vendored TEI P5 XSD, with 3,963 lexical entries.",
        "closure": "Retained source, historical candidate, current header, source accounting, prior visual anchors, and current adapter are hash-bound.",
    }
    common = {"status": "pass", "command": "py -3 -m build.tools.stage_easton_current_acceptance", "exit_code": 0, "checked_at": now, "source_proof": source_proof_binding, "source_accounting": accounting_binding, "historical_validation": validation_binding, "prior_visual_review": visual_binding, "header_renewal": header_binding, "adapter_sha256": ADAPTER_SHA, **acceptance_context}
    for name, description in descriptions.items():
        path = evidence / f"{name}.json"
        write_json(path, {**common, "kind": name, "description": description})
        technical[name] = {"path": path, "status": "pass", "command": "py -3 -m build.tools.stage_easton_current_acceptance", "exit_code": 0}
    review_path = evidence / "review.json"
    review = {"report_path": review_path, "reviewer": "agent:easton-current-technical-adoption", "reviewed_at": now, "coverage": {"status": "partial", "declared": scope_text, "reached": ["retained JSONL", "native TEI", "technical visual anchors"], "inspected": ["retained JSONL/all 3,963 rows", "native TEI/all 7,464 definitions", "technical visual anchors/ten screenshots"], "unreviewed": ["full human visual collation", "identified print witness"]}, "source_quality_uncertainty": ["No identified print edition has been collated.", "Modern structured JSONL reuse terms remain unresolved."], "discrepancies": [], "unreviewed_residuals": ["full human visual collation", "rights clearance", "publication authorization"]}
    write_json(review_path, {**common, "kind": "technical-review", "visual_scope": "Ten identity-bound screenshot anchors across beginning, middle, late, terminal, duplicates, long entries, and many-definition entries; complete source/TEI comparison is computational, not full visual collation.", "reviewer": review["reviewer"], "reviewed_at": now, "coverage": review["coverage"], "source_quality_uncertainty": review["source_quality_uncertainty"], "discrepancies": [], "unreviewed_residuals": review["unreviewed_residuals"]})
    decision = {"source_local_disposition": "Agent technical adoption of the exact retained electronic member only; no human rights clearance or publication authorization.", "blockers": [], "agent_assessment": {"status": "accepted", "actor": review["reviewer"], "assessed_at": now, "supported_scope": scope_text, "unresolved_claims": [], "unassessed_stronger_claims": ["human textual acceptance", "identified print edition", "structured-source rights clearance", "public publication"]}, "human_decision": {"status": "not-recorded"}}
    revision = renewal["representation_revision"]
    record = build_acceptance_record(STAGE, identity=identity, candidate_path=STAGE / INTEGRATION / "candidate-v2.tei.xml", source_accounting_path=source_accounting_path, scope=scope, technical=technical, review=review, representation_revision=revision, decision=decision)
    acceptance = STAGE / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=STAGE)
    master = STAGE / EDITION / "master.tei.xml"
    shutil.copy2(STAGE / INTEGRATION / "candidate-v2.tei.xml", master)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(STAGE, master))
    write_acceptance(acceptance, record)
    stage_state = json.loads((STAGE / WORK / "state.json").read_text(encoding="utf-8"))
    editions = [item for item in stage_state["targets"] if item["target_type"] == "edition" and item["target_id"] == EDITION_ID]
    if len(editions) != 1 or editions[0]["stage"] != "acquired":
        raise ValueError("Easton stage edition state differs")
    editions[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    editions[0]["evidence"].extend([master.relative_to(STAGE).as_posix(), acceptance.relative_to(STAGE).as_posix()])
    write_json(STAGE / WORK / "state.json", stage_state)
    validate_acceptance(acceptance, root=STAGE)
    validate_state(STAGE / WORK / "state.json", root=STAGE)
    load_work(STAGE / WORK / "work.json")
    after = _files(STAGE / WORK)
    for path, expected in preimage.items():
        if path != "state.json" and after.get(path) != expected:
            raise ValueError(f"staged work changed existing authority: {path}")
    result = {"contract": "ocd-easton-current-staged-acceptance-v1", "status": "staged-only", "work_id": WORK_ID, "stage_root": str(STAGE), "source_sha256": SOURCE_SHA, "master_sha256": MASTER_SHA, "acceptance_sha256": digest(acceptance), "current_work_before": preimage, "staged_work_after": after, "canonical_install_performed": False, "rights_clearance": "unresolved", "publication_authorized": False}
    write_json(OUT / "staged-acceptance.json", result)
    print(json.dumps({"status": result["status"], "acceptance_sha256": result["acceptance_sha256"], "staged_file_count": len(after)}, sort_keys=True))


if __name__ == "__main__":
    main()
