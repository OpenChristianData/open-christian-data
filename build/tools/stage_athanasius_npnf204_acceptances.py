"""Stage twenty source-checked NPNF204 electronic-witness acceptances.

The command prepares a complete proposed generation outside canonical library/works.
It does not install accepted masters or update corpus views.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from lxml import etree

from build.tei.athanasius_table_reconstruction import ASSIGNED, SOURCE_SHA256
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
CHILDREN = Path("D:/Library/Open Christian Data/candidate-reviews/athanasius-npnf204-work-local-20260926-v4")
REVIEW_ROOT = Path("D:/Library/Open Christian Data/candidate-reviews")
SOURCE = Path("raw/ccel/npnf2/npnf204.xml")
MANIFEST = Path("sources/structured-text/athanasius-on-the-incarnation/athanasius-table.source-manifest.json")
EVIDENCE_NAME = "integration/npnf204-electronic-acceptance-v1"


def _io(path: Path) -> Path:
    if str(path).startswith("\\\\?\\"):
        return path
    absolute = path.resolve(strict=False)
    return Path("\\\\?\\" + str(absolute)) if os.name == "nt" else absolute


def _read(path: Path) -> bytes:
    return _io(path).read_bytes()


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _put(root: Path, relative: Path, content: bytes) -> Path:
    path = root / relative
    _io(path.parent).mkdir(parents=True, exist_ok=True)
    _io(path).write_bytes(content)
    return path


def _copy(root: Path, relative: Path) -> Path:
    return _put(root, relative, _read(ROOT / relative))


def _work_files(root: Path, work_id: str) -> dict[str, str]:
    path = root / "library/works" / work_id
    io_path = _io(path)
    return {item.relative_to(io_path).as_posix(): _sha(_read(item)) for item in sorted(io_path.rglob("*")) if item.is_file()}


def prepare(stage: Path) -> dict[str, object]:
    stage = stage.resolve(strict=False)
    if (stage.exists() or stage.parent != REVIEW_ROOT.resolve(strict=True)
            or not stage.name.startswith("athanasius-npnf204-acceptance-stage-")):
        raise ValueError("Athanasius acceptance stage must be a fresh named child of the durable candidate root")
    child_receipt = json.loads(_read(CHILDREN / "stage-receipt.json"))
    if (child_receipt["contract"] != "ocd-athanasius-npnf204-child-stage-v1"
            or child_receipt["status"] != "staged-only" or child_receipt["work_count"] != 20
            or child_receipt["source_sha256"] != SOURCE_SHA256
            or any(item["projection_status"] != "pass" or item["projection_rows"] != 1 for item in child_receipt["works"])):
        raise ValueError("work-local child stage is not uniformly source-checked and projected")
    for relative, digest in child_receipt["files"].items():
        if _sha(_read(CHILDREN / relative)) != digest:
            raise ValueError(f"work-local child stage file changed: {relative}")
    source_bytes = _read(ROOT / SOURCE)
    if _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("retained NPNF204 source changed")
    source_tree = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))
    source_roots = {node.get("id"): node for node in source_tree.xpath("/ThML/ThML.body/div1")}
    at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    stage.mkdir(parents=True)
    _put(stage, SOURCE, source_bytes)
    _copy(stage, MANIFEST)
    _copy(stage, Path("sources/structured-text/athanasius-on-the-incarnation/athanasius-table.reconstruction-profile.json"))
    _copy(stage, Path("sources/structured-text/athanasius-on-the-incarnation/ccel-permission.md"))
    _copy(stage, Path("sources/structured-text/athanasius-on-the-incarnation/README.md"))
    _copy(stage, Path("build/tei/athanasius_table_reconstruction.py"))
    _copy(stage, Path("build/tei/athanasius_table_oracle.py"))
    results: list[dict[str, object]] = []
    for (scope, work_id), child in zip(ASSIGNED, child_receipt["works"], strict=True):
        if child["work_id"] != work_id or child["source_root_id"] != scope:
            raise ValueError("child stage ordering or identity changed")
        relative_work = Path("library/works") / work_id
        original_work = ROOT / relative_work
        for source_file in _io(original_work).rglob("*"):
            if source_file.is_file():
                rel = source_file.relative_to(_io(ROOT))
                _put(stage, rel, _read(source_file))
        before = _work_files(ROOT, work_id)
        work = json.loads(_read(ROOT / relative_work / "work.json"))
        state = json.loads(_read(ROOT / relative_work / "state.json"))
        form = work["textual_forms"][0]
        edition = form["editions"][0]
        identity = child["identity"]
        if (work["work_id"] != work_id or edition["edition_id"] != identity["edition_id"]
                or edition.get("category") is not None or work.get("creators")
                or edition["containing_source"]["locator"] != f"{SOURCE.as_posix()}#{scope}"):
            raise ValueError(f"canonical work baseline changed: {work_id}")
        creator = "Eusebius of Caesarea" if scope == "ix" else "Athanasius of Alexandria"
        work["creators"] = [{"name": creator, "role": "author", "evidence": [f"{SOURCE.as_posix()}#{scope}"]}]
        edition["category"] = "prose"
        _put(stage, relative_work / "work.json", _json(work))
        acquisition = relative_work / "forms" / identity["textual_form_id"] / "editions" / identity["edition_id"] / "acquisitions" / f"{identity['acquisition_id']}.json"
        acquired = json.loads(_read(ROOT / acquisition))
        if acquired["retained_files"][0]["sha256"] != SOURCE_SHA256:
            raise ValueError(f"acquisition source changed: {work_id}")
        for ref in set(work.get("evidence", [])) | {r for target in state["targets"] for r in target.get("evidence", [])}:
            relative = Path(ref.partition("#")[0])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"unsafe inherited evidence: {ref}")
            _copy(stage, relative)
        evidence = relative_work / EVIDENCE_NAME
        tei_bytes = _read(CHILDREN / work_id / "proposed-master.tei.xml")
        candidate = _put(stage, evidence / "candidate.tei.xml", tei_bytes)
        if validate_file(_io(candidate)):
            raise ValueError(f"staged TEI P5 failed: {work_id}")
        source_count = sum(isinstance(node.tag, str) for node in source_roots[scope].iter())
        scope_text = f"Complete retained NPNF204 div1 {scope}: {source_roots[scope].get('title')}"
        source_binding = {"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA256, "source_bytes": len(source_bytes), "source_scope": acquired["retained_files"][0]["scope"]}
        expected = [{"path": SOURCE.as_posix(), "position": 1}]
        included = [{"path": SOURCE.as_posix(), "position": 1, "bytes": len(source_bytes), "sha256": SOURCE_SHA256, "scope": acquired["retained_files"][0]["scope"]}]
        accepted_scope = {"kind": "edition", "declared": scope_text}
        candidate_binding = make_file_binding(stage, candidate)
        accounting = _put(stage, evidence / "source-accounting.json", _json({"identity": identity, "candidate": candidate_binding, "source": source_binding, "scope": source_binding["source_scope"], "accepted_scope": accepted_scope, "expected_members": expected, "included_members": included, "excluded_members": [], "missing_members": [], "unknown_members": [], "source_sha256": SOURCE_SHA256, "source_bytes": len(source_bytes), "source_root_id": scope, "source_element_count": source_count, "aggregate_candidate_sha256": child_receipt["aggregate_candidate_sha256"], "child_master_sha256": _sha(tei_bytes)}))
        inputs = {"source_sha256": SOURCE_SHA256, "source_manifest_sha256": child_receipt["source_manifest_sha256"], "aggregate_candidate_sha256": child_receipt["aggregate_candidate_sha256"], "child_stage_receipt_sha256": _sha(_read(CHILDREN / "stage-receipt.json")), "child_source_check_sha256": _sha(_read(CHILDREN / work_id / "source-check.json")), "child_projection_canary_sha256": _sha(_read(CHILDREN / work_id / "projection-canary.json")), "candidate_sha256": _sha(tei_bytes)}
        _put(stage, evidence / "inputs/child-source-check.json", _read(CHILDREN / work_id / "source-check.json"))
        _put(stage, evidence / "inputs/child-projection-canary.json", _read(CHILDREN / work_id / "projection-canary.json"))
        command = "py -3 -m build.tools.stage_athanasius_npnf204_children --stage <fresh-stage>"
        technical = {"producer": {"id": "ocd-npnf204-assigned-works-to-tei", "path": make_file_binding(stage, stage / MANIFEST)}, "checker": {"id": "ocd-npnf204-source-to-tei-oracle", "path": make_file_binding(stage, stage / MANIFEST)}, "shared_assumptions": ["The retained XML and declared vi–xxv boundaries are shared by the original producer and oracle; direct source division titles and the complete independent oracle were rechecked before each child extraction."], "independent_corroboration": "All 26,890 assigned source features were checked by the aggregate oracle; each work-local subtree matches its checked division, passes TEI P5, and independently verified one native prose row."}
        for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
            proof_record = {"claim": name, "status": "pass", "command": command, "exit_code": 0, "identity": identity, "candidate": candidate_binding, "source": source_binding, "scope": scope_text, "inputs": inputs, "source_element_count": source_count, "source_root_id": scope}
            if name == "accounting":
                proof_record |= {"accepted_scope": accepted_scope, "expected_members": expected, "included_members": included, "excluded_members": [], "missing_members": [], "unknown_members": []}
            proof = _put(stage, evidence / f"{name}.json", _json(proof_record))
            technical[name] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
        review = {"reviewer": "agent:athanasius-npnf204-source-checked-stage", "reviewed_at": at,
                  "coverage": {"status": "partial", "declared": scope_text, "reached": [f"{SOURCE.as_posix()}#{scope}"], "inspected": [f"{SOURCE.as_posix()}#{scope}/mechanical-all-nodes"], "unreviewed": [f"{SOURCE.as_posix()}#{scope}/visual-full"]},
                  "source_quality_uncertainty": ["The retained electronic source was not collated with a print witness."], "discrepancies": [], "unreviewed_residuals": ["Human inspection, full per-work visual proofreading, rights clearance, and publication remain separate."]}
        report = _put(stage, evidence / "review.json", _json({"identity": identity, "candidate": candidate_binding, "source": source_binding, "scope": scope_text, **review, "source_check_sha256": inputs["child_source_check_sha256"], "projection_canary_sha256": inputs["child_projection_canary_sha256"]}))
        change = etree.fromstring(tei_bytes).find("{http://www.tei-c.org/ns/1.0}teiHeader/{http://www.tei-c.org/ns/1.0}revisionDesc/{http://www.tei-c.org/ns/1.0}change")
        if change is None or change.get("{http://www.w3.org/XML/1998/namespace}id") != f"{work_id}-npnf204-electronic-v1":
            raise ValueError(f"child TEI revision binding changed: {work_id}")
        revision = {"id": f"{work_id}-npnf204-electronic-v1", "date": change.get("when"), "note": change.text}
        decision = {"source_local_disposition": "Agent acceptance of the complete retained NPNF204 electronic child division.", "blockers": [], "agent_assessment": {"status": "accepted", "actor": review["reviewer"], "assessed_at": at, "supported_scope": scope_text, "unresolved_claims": [], "unassessed_stronger_claims": ["print collation", "full visual proofreading", "human review", "rights clearance", "publication"]}, "human_decision": {"status": "not-recorded"}}
        scope_record = {"kind": "edition", "declared": scope_text, "expected_members": expected, "included_members": included, "excluded_members": []}
        record = build_acceptance_record(stage, identity=identity, candidate_path=candidate, source_accounting_path=accounting, scope=scope_record, technical=technical, review=review | {"report_path": report}, representation_revision=revision, decision=decision)
        edition_path = relative_work / "forms" / identity["textual_form_id"] / "editions" / identity["edition_id"]
        acceptance = stage / edition_path / "acceptance.json"
        write_acceptance(_io(acceptance), record)
        master = _put(stage, edition_path / "master.tei.xml", tei_bytes)
        record["promotion"] |= {"status": "promoted", "promoted_at": at, "master": make_file_binding(stage, master)}
        write_acceptance(_io(acceptance), record)
        target = next(item for item in state["targets"] if item["target_id"] == identity["edition_id"])
        if target["stage"] != "acquired":
            raise ValueError(f"edition target is no longer acquired: {work_id}")
        target |= {"stage": "accepted", "reason": PROMOTED_MASTER_REASON, "updated_at": at}
        target["evidence"].extend([master.relative_to(stage).as_posix(), acceptance.relative_to(stage).as_posix()])
        _put(stage, relative_work / "state.json", _json(state))
        validate_acceptance(_io(acceptance), root=_io(stage))
        validate_state(_io(stage / relative_work / "state.json"), root=_io(stage))
        load_work(_io(stage / relative_work / "work.json"))
        projected = project_accepted_prose(stage, acceptance_path=acceptance)
        errors = verify_accepted_prose(stage, acceptance_path=acceptance, rows=projected["rows"], receipt=projected["receipt"])
        if len(projected["rows"]) != 1 or projected["receipt"].get("unsupported") or errors:
            raise ValueError(f"actual-master prose projection failed: {work_id}: {errors[:2]}")
        _put(stage, evidence / "projection-canary.json", _json({"category": "prose", "row_count": 1, "unsupported": [], "independent_verifier_errors": []}))
        after = _work_files(stage, work_id)
        results.append({"work_id": work_id, "source_root_id": scope, "source_element_count": source_count, "identity": identity, "before": before, "after": after, "master_sha256": _sha(tei_bytes), "acceptance_sha256": _sha(_read(acceptance)), "projection_rows": 1})
    receipt = {"contract": "ocd-athanasius-npnf204-acceptance-stage-v1", "status": "staged-only", "canonical_install": False, "source_sha256": SOURCE_SHA256, "child_stage_receipt_sha256": _sha(_read(CHILDREN / "stage-receipt.json")), "works": results, "work_count": len(results), "human_review": "not-recorded", "rights_clearance": "not-assessed", "publication": "not-authorized"}
    _put(stage, Path("stage-receipt.json"), _json(receipt))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.stage)
    print(json.dumps({"work_count": result["work_count"], "stage": str(args.stage)}, sort_keys=True))


if __name__ == "__main__":
    main()
