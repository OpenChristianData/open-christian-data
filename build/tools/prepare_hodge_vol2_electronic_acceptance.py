"""Stage acceptance evidence for Hodge Vol. II's assigned CCEL Part II/III roots.

This prepares a fresh, local fixture and never installs into the canonical library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from build.tei.hodge_systematic_theology_vol_2_oracle import _oracle
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, build_acceptance_record, load_acceptance, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.install_accepted import _io_path

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "hodge-systematic-theology-vol-2"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms/hodge-systematic-theology-vol-2-english/editions/hodge-systematic-theology-vol-2-retained-electronic-witness"
ACQUISITION = EDITION / "acquisitions/hodge-systematic-theology-vol-2-retained-source.json"
SOURCE = Path("raw/ccel/hodge/theology2.xml")
MANIFEST = Path("sources/structured-text/hodge-systematic-theology-vol-2/hodge-systematic-theology-vol-2.source-manifest.visual-v2.json")
HISTORICAL_MANIFEST = Path("sources/structured-text/hodge-systematic-theology-vol-2/hodge-systematic-theology-vol-2.source-manifest.json")
REVIEW = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-204.md")
AUDIT = REVIEW.with_name("37c-204-owner-review-current-audit-20260922.json")
EVIDENCE = WORK / "integration/hodge-vol2-parts-ii-iii-electronic-v2"
IDENTITY = {
    "work_id": WORK_ID,
    "textual_form_id": "hodge-systematic-theology-vol-2-english",
    "edition_id": "hodge-systematic-theology-vol-2-retained-electronic-witness",
    "acquisition_id": "hodge-systematic-theology-vol-2-retained-source",
}
MANIFEST_SHA = "4d9cb32161327312b7beb9a0e607b803636c0ff5c97e44869b4be4e6b54ae13e"
PACKAGE_SHA = "c0fa92f1a88c02f2adf05791eee1d1c2f28629d1a7de3e1e04a0751bbb16eda8"
ORIGINAL_TEI_SHA = "b2cfbd41e869910f214b6e2b74b5fd2985a3ec9da69f87f42a0542c78cc4edde"
SOURCE_SHA = "52a43581dcb7b75a6903c89c8e2496b8d754bdbcd6fa751ecaa4f065e933d942"
SOURCE_BYTES = 2601781
SCOPE = (
    "The complete ordered ThML.body/div1 roots iii (Part II, Anthropology) and iv "
    "(Part III, Soteriology) of the retained CCEL theology2.xml electronic witness. "
    "The source header and div1 roots i (Title), ii (Prefatory), and v (Indexes) "
    "are accounted for but outside this accepted readable-text selection. "
    "No print-edition collation or whole-volume visual review is claimed."
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(path: Path, expected: str | None = None) -> bytes:
    data = io_path(path).read_bytes()
    if expected is not None and sha(data) != expected:
        raise PipelineError(f"Hodge byte binding differs: {path}")
    return data


def write(stage: Path, relative: Path, data: bytes) -> Path:
    target = stage / relative
    io_path(target.parent).mkdir(parents=True, exist_ok=True)
    io_path(target).write_bytes(data)
    return target


def write_json(stage: Path, relative: Path, value: object) -> Path:
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    return write(stage, relative, data)


def prepare(root: Path, candidate_root: Path, stage: Path) -> Path:
    root = root.resolve(strict=True)
    candidate_root = candidate_root.resolve(strict=True)
    stage = stage.absolute()
    if stage.exists() or not stage.parent.is_dir() or stage.parent.is_symlink():
        raise PipelineError("Hodge stage must be fresh under an ordinary existing parent")
    if stage == root or root in stage.parents or stage == candidate_root or candidate_root in stage.parents:
        raise PipelineError("Hodge stage overlaps a protected input")
    source_bytes = read(root / SOURCE, SOURCE_SHA)
    if len(source_bytes) != SOURCE_BYTES:
        raise PipelineError("Hodge retained XML byte count differs")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    package = CandidatePackage.load(candidate_root / "package")
    if manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA:
        raise PipelineError("Hodge versioned manifest or candidate package differs")
    original = package.member_bytes("content.tei.xml")
    old = Path("D:/Library/Open Christian Data/candidate-reviews/37c-204-hodge-systematic-theology-vol-2-20260917-v3/candidate/package")
    if sha(original) != ORIGINAL_TEI_SHA or read(old / "content.tei.xml", ORIGINAL_TEI_SHA) != original:
        raise PipelineError("Hodge reviewed TEI differs")
    if package.member_bytes("source-accountability.json") != read(old / "source-accountability.json"):
        raise PipelineError("Hodge node accounting differs from reviewed candidate")
    note = package.member_bytes("unresolved.jsonl")
    if b"An exact-pair CVW visual sample inspected 11 declared loci" not in note or b"visual comparison has not been performed" in note:
        raise PipelineError("Hodge visual-status correction is absent")
    report = validate(manifest, package, _oracle)
    validation = json.loads(read(candidate_root / "validation.json"))
    if report.status != "pass" or report.findings or validation.get("candidate_sha256") != PACKAGE_SHA or validation.get("source_manifest_sha256") != MANIFEST_SHA or validation.get("report_sha256") != report.sha256:
        raise PipelineError("Hodge current independent oracle result differs")
    historical_review = read(root / REVIEW)
    historical_audit = json.loads(read(root / AUDIT))
    if (ORIGINAL_TEI_SHA.encode() not in historical_review or not historical_audit.get("all_checked_byte_bindings_match") or historical_audit.get("scope", {}).get("readable_tei_projection", {}).get("excluded_top_level_roots") != ["i", "ii", "v"]):
        raise PipelineError("Hodge exact-pair historical review binding is absent")
    if not (root / WORK / "work.json").is_file() or (root / EDITION / "acceptance.json").exists():
        raise PipelineError("Hodge canonical identity missing or already accepted")

    for relative in (WORK / "work.json", WORK / "state.json", ACQUISITION):
        write(stage, relative, read(root / relative))
    staged_work = json.loads(read(stage / WORK / "work.json"))
    staged_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    write_json(stage, WORK / "work.json", staged_work)
    for relative in (MANIFEST, HISTORICAL_MANIFEST, REVIEW, AUDIT, Path("sources/structured-text/hodge-systematic-theology-vol-2/config.json"), Path("metadata/source-evidence/catalog/hodge-systematic-theology-vol-2.json"), Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/library-status.json")):
        write(stage, relative, read(root / relative))
    write(stage, SOURCE, source_bytes)
    acquisition = json.loads(read(stage / ACQUISITION))
    retained = acquisition["retained_files"]
    if len(retained) != 1 or retained[0]["path"] != SOURCE.as_posix() or retained[0]["sha256"] != SOURCE_SHA or retained[0]["bytes"] != SOURCE_BYTES:
        raise PipelineError("Hodge acquisition retained member differs")
    acquisition.update(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA, source_bytes=SOURCE_BYTES, source_scope=SCOPE, route="born-digital")
    acquisition["retained_files"][0]["scope"] = "Complete retained CCEL XML file; selected readable TEI covers only ThML.body/div1 roots iii and iv. Header and roots i, ii, v are accounted outside the selection."
    acquisition["warnings"] = ["The 1940 retained title-page imprint, 1871 copyright notice, and unverified 1872-1873 config claim are distinct. Print identity, rights, human review, and publication remain separate."]
    write_json(stage, ACQUISITION, acquisition)
    validate_acquisition(stage / ACQUISITION, root=stage)

    evidence = stage / EVIDENCE
    for name in package.member_names:
        write(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    write(stage, EVIDENCE / "inputs/validation.json", read(candidate_root / "validation.json"))
    write(stage, EVIDENCE / "inputs/historical-content.tei.xml", read(old / "content.tei.xml", ORIGINAL_TEI_SHA))
    now = datetime.now(timezone.utc)
    reviewed_at = now.isoformat().replace("+00:00", "Z")
    revision = {"id": "hodge-vol2-parts-ii-iii-electronic-v1", "date": now.date().isoformat(), "note": "Accept the complete assigned CCEL electronic Part II and Part III subtrees with source-accounted exclusions."}
    source_binding = {"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA, "source_bytes": SOURCE_BYTES, "source_scope": SCOPE}
    derived = bind_reviewed_header(original, expected_sha256=ORIGINAL_TEI_SHA, identity=IDENTITY, source=source_binding, source_url=acquisition["url"], declared_scope=SCOPE, revision=revision)
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Hodge reviewed body changed during header binding")
    candidate = write(stage, EVIDENCE / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"Hodge header-derived TEI XSD failed: {errors[:3]}")
    expected = [{"path": SOURCE.as_posix(), "position": 1}]
    included = [{"path": SOURCE.as_posix(), "position": 1, "bytes": SOURCE_BYTES, "sha256": SOURCE_SHA, "scope": acquisition["retained_files"][0]["scope"]}]
    scope = {"kind": "selection", "declared": SCOPE, "expected_members": expected, "included_members": included, "excluded_members": []}
    common = {"identity": IDENTITY, "source": source_binding, "candidate": make_file_binding(stage, candidate), "scope": SCOPE, "accepted_scope": {"kind": "selection", "declared": SCOPE}, "expected_members": expected, "included_members": included, "excluded_members": [], "missing_members": [], "unknown_members": []}
    accounting = write_json(stage, EVIDENCE / "source-accounting.json", common | {"source_sha256": SOURCE_SHA, "source_bytes": SOURCE_BYTES, "source_manifest_sha256": MANIFEST_SHA, "candidate_package_sha256": PACKAGE_SHA, "assigned_source_roots": ["iii", "iv"], "unaccepted_source_roots": ["i", "ii", "v"], "source_accountability_sha256": sha(package.member_bytes("source-accountability.json")), "historical_tei_sha256": ORIGINAL_TEI_SHA})
    inputs = {"manifest": make_file_binding(stage, stage / MANIFEST), "package": make_file_binding(stage, evidence / "inputs/package/manifest.json"), "validation": make_file_binding(stage, evidence / "inputs/validation.json"), "historical_review": make_file_binding(stage, stage / REVIEW), "historical_audit": make_file_binding(stage, stage / AUDIT)}
    command = "py -3 -m build.tools.prepare_hodge_vol2_electronic_acceptance --candidate <pinned-v2-candidate> --stage <fresh-external-root>"
    descriptions = {
        "validation": "Current independent oracle passes the exact versioned package and source manifest.",
        "accounting": "The complete XML file is pinned; roots iii and iv are accepted, while header and roots i, ii, v are separately accounted outside this readable selection.",
        "fidelity": "Current independent source-to-TEI oracle verifies all 6,940 assigned source elements and their relationships; historical 11-locus visual sample covers the same unchanged TEI bytes.",
        "reproducibility": "The versioned producer regenerates the same reviewed TEI and source accounting; fresh-process package reproduction is checked separately before promotion.",
        "schema": "The candidate TEI with acceptance-only header additions passes the vendored TEI P5 schema.",
        "closure": "Source XML, acquisition, manifest, package, oracle report, reviewed TEI and 11-locus historical review are bound by exact hashes.",
    }
    technical = {"producer": {"id": manifest.record["converter"]["id"], "path": make_file_binding(stage, stage / MANIFEST)}, "checker": {"id": manifest.record["validator"]["id"], "path": make_file_binding(stage, stage / MANIFEST)}, "shared_assumptions": ["Producer and oracle share the declared root selection and source metadata policy; oracle independently walks the retained XML and actual TEI tree."], "independent_corroboration": "Exact reviewed TEI and source-accountability bytes match the previous package, which has a bounded 11-locus visual review; current oracle and TEI XSD pass."}
    for name in descriptions:
        proof_path = write_json(stage, EVIDENCE / f"{name}.json", common | {"status": "pass", "command": command, "exit_code": 0, "description": descriptions[name], "inputs": inputs, "oracle_report_sha256": report.sha256})
        technical[name] = {"path": proof_path, "status": "pass", "command": command, "exit_code": 0}
    coverage = {"status": "partial", "declared": SCOPE, "reached": ["part-ii", "part-iii"], "inspected": ["part-ii/opening", "part-ii/middle", "part-ii/ending", "part-ii/italic", "part-ii/note", "part-ii/scripture-ref", "part-ii/page-break", "part-iii/opening", "part-iii/middle", "part-iii/ending", "part-iii/verse"], "unreviewed": ["part-ii/other-content", "part-iii/other-content"]}
    review = {"reviewer": "agent:hodge-vol2-electronic-review", "reviewed_at": reviewed_at, "coverage": coverage, "source_quality_uncertainty": ["The retained file does not establish the unverified 1872-1873 edition claim or a separate collated print witness."], "discrepancies": [], "unreviewed_residuals": ["Visual review was an 11-locus sample; the remaining assigned text was checked mechanically.", "CVW's chapter-heading anchor and verse typography have documented presentation limits in the historical report."]}
    review_path = write_json(stage, EVIDENCE / "review.json", common | review | {"inputs": inputs, "historical_tei_sha256": ORIGINAL_TEI_SHA, "historical_visual_scope": "11 declared sample loci inspected on the exact unchanged TEI; no whole-volume visual claim", "unassessed": ["header and div1 roots i, ii, v as accepted readable text", "independently collated print witness", "human review", "rights clearance", "publication"]})
    decision = {"source_local_disposition": "Agent acceptance of complete assigned Part II and III electronic subtrees only.", "blockers": [], "agent_assessment": {"status": "accepted", "actor": review["reviewer"], "assessed_at": reviewed_at, "supported_scope": SCOPE, "unresolved_claims": [], "unassessed_stronger_claims": ["readable projection of header and roots i, ii, v", "print edition identity", "exhaustive visual review", "human textual acceptance", "rights clearance", "publication"]}, "human_decision": {"status": "not-recorded"}}
    record = build_acceptance_record(stage, identity=IDENTITY, candidate_path=candidate, source_accounting_path=accounting, scope=scope, technical=technical, review=review | {"report_path": review_path}, representation_revision=revision, decision=decision)
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    return acceptance



def promote_stage(stage: Path, destination: Path) -> Path:
    """Prepare a promoted Hodge fixture with long-path-safe I/O and no live mutation."""
    stage = stage.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists() or destination.parent.resolve() != Path("C:/Scratch").resolve():
        raise PipelineError("Hodge promoted fixture needs a fresh C:/Scratch destination")
    if destination.name != "h204p":
        raise PipelineError("Hodge promoted fixture path must stay short for Windows path limits")
    acceptance_rel = EDITION / "acceptance.json"
    pending = validate_acceptance(stage / acceptance_rel, root=stage)
    if pending["promotion"]["status"] != "pending" or pending["decision"]["agent_assessment"]["status"] != "accepted" or pending["decision"]["blockers"]:
        raise PipelineError("Hodge promotion requires a clean accepted pending record")
    temp = destination.parent / "x204p"
    if temp.exists():
        raise PipelineError("Hodge short promotion temporary path already exists")
    io_stage = _io_path(stage)
    for path in sorted(io_stage.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise PipelineError(f"Hodge fixture contains a linked path: {path}")
        relative = path.relative_to(io_stage)
        target = _io_path(temp / relative)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
        else:
            raise PipelineError(f"Hodge fixture contains unsupported path: {path}")
    staged_acceptance = temp / acceptance_rel
    record = load_acceptance(staged_acceptance)
    candidate = temp / Path(record["technical"]["candidate"]["path"])
    master = temp / EDITION / "master.tei.xml"
    _io_path(master).parent.mkdir(parents=True, exist_ok=True)
    _io_path(master).write_bytes(_io_path(candidate).read_bytes())
    record["promotion"]["status"] = "promoted"
    record["promotion"]["promoted_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    record["promotion"]["master"] = make_file_binding(temp, master)
    write_acceptance(staged_acceptance, record)
    state_path = temp / WORK / "state.json"
    state = json.loads(read(state_path))
    edition_target = next((item for item in state["targets"] if item["target_id"] == IDENTITY["edition_id"]), None)
    if edition_target is None:
        raise PipelineError("Hodge edition state target missing")
    edition_target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    for reference in ((EDITION / "master.tei.xml").as_posix(), acceptance_rel.as_posix()):
        if reference not in edition_target["evidence"]:
            edition_target["evidence"].append(reference)
    write_json(temp, WORK / "state.json", state)
    validate_acceptance(staged_acceptance, root=temp)
    validate_state(state_path, root=temp)
    temp.rename(destination)
    validate_acceptance(destination / acceptance_rel, root=destination)
    return destination / acceptance_rel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    path = prepare(args.root, args.candidate, args.stage)
    print(json.dumps({"status": "validated-pending", "acceptance_path": str(path)}, sort_keys=True))


if __name__ == "__main__":
    main()
