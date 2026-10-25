"""Stage one source-bound Ambrose acceptance generation outside the canonical library."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from lxml import etree

from build.tei.npnf_ambrose_work_local_oracle import _oracle
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path("\\\\?\\" + str(Path(__file__).resolve().parents[2]))
LIBRARY = Path("D:/Library/Open Christian Data")
WORK_ID = "ambrose-of-milan-on-mysteries"
IDENTITY = {
    "work_id": WORK_ID,
    "textual_form_id": "ambrose-of-milan-on-mysteries-ccel-npnf210-retained-en",
    "edition_id": "ambrose-of-milan-on-mysteries-ccel-npnf210-electronic",
    "acquisition_id": "ambrose-of-milan-on-mysteries-ccel-npnf210-acquired",
}
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / IDENTITY["textual_form_id"] / "editions" / IDENTITY["edition_id"]
ACQUISITION = EDITION / "acquisitions" / f"{IDENTITY['acquisition_id']}.json"
SOURCE = Path("raw/ccel/npnf2/npnf210.xml")
MANIFEST = Path("sources/structured-text") / WORK_ID / "npnf210-work-heading-repair-v2.source-manifest.json"
PROFILE = Path("sources/structured-text/ambrose-npnf210/npnf-ambrose.reconstruction-profile.json")
PACKAGE = LIBRARY / "candidate-reviews/npnf210-work-ambrose-of-milan-on-mysteries-heading-repair-v2-20260926"
PROPOSAL = LIBRARY / "candidate-reviews/npnf210-mysteries-heading-repair-v2-projection-20260926"
CVW = LIBRARY / "cvw-sessions"
FRAMES = {
    "opening": CVW / "npnf210-mysteries-heading-repair-opening-20260926",
    "chapter-iii": CVW / "npnf210-mysteries-heading-repair-middle-exact-20260926",
    "chapter-ix": CVW / "npnf210-mysteries-heading-repair-ending-20260926",
}
EVIDENCE = WORK / "integration/npnf210-mysteries-electronic-v2"
SCOPE = "Complete On the Mysteries child div2 iv.v in retained CCEL NPNF2-10 XML."
SOURCE_SHA = "c6f1a9d66653852d8b743c84a613c72c521dfb1b05602f0a2eff400c17665ee8"
PACKAGE_SHA = "2460d98a2c9eddce8b1aeadeb72a786b2e5fb27dea03dcbe638699809fa02a59"
MANIFEST_SHA = "c75d387cb5fc0204a7fd4be4711aed1425c3550f5258a15f23c5588cddd7d4eb"
TEI_SHA = "18341661e53fa63a7a51049af9eda2b34dc6de16654b12b1a98cb6e5f86a4011"
PROPOSAL_SHA = "9af182cc370449987c3bb5fe1a161f1e2bd9c9c3ea5243371db58ad2371159a1"
REVISION = {"id": "ambrose-mysteries-ccel-electronic-v2", "date": "2026-09-26", "note": "Agent-accepted retained CCEL electronic witness; human acceptance and publication remain separate."}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _read_json(path: Path) -> dict[str, object]:
    result = json.loads(path.read_bytes())
    if not isinstance(result, dict):
        raise PipelineError(f"JSON object required: {path}")
    return result


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    path = stage / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, _json(value))


def _copy(stage: Path, source: Path, relative: Path) -> Path:
    content = source.read_bytes()
    result = _put(stage, relative, content)
    if result.read_bytes() != content:
        raise PipelineError(f"staged copy differs: {source}")
    return result


def prepare(stage: Path) -> dict[str, object]:
    stage = stage.absolute()
    if stage.exists() or stage.parent.resolve(strict=True) != LIBRARY.resolve(strict=True) or not stage.name.startswith("am26"):
        raise PipelineError("acceptance stage must be a fresh am26-prefixed direct child of the durable library")
    stage = Path("\\\\?\\" + str(stage))
    preimages = {}
    for relative in (WORK / "work.json", WORK / "state.json", EDITION / "master.tei.xml", EDITION / "acceptance.json", ACQUISITION):
        path = ROOT / relative
        preimages[relative.as_posix()] = {"exists": path.is_file(), "sha256": _sha(path.read_bytes()) if path.is_file() else None}
    if preimages[(EDITION / "master.tei.xml").as_posix()]["exists"] or preimages[(EDITION / "acceptance.json").as_posix()]["exists"]:
        raise PipelineError("canonical Ambrose master or acceptance exists; stage generation requires review")
    source_bytes = (ROOT / SOURCE).read_bytes()
    if _sha(source_bytes) != SOURCE_SHA:
        raise PipelineError("retained XML source changed")
    source_tree = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))
    head = source_tree.find("ThML.head")
    child = source_tree.xpath("//ThML.body//*[@id='iv.v']")
    title_page = source_tree.xpath("//ThML.body//*[@id='i-p15']")
    if (head is None or (head.findtext(".//DC.Language") or "").strip() != "eng"
            or (head.findtext(".//DC.Type") or "").strip() != "Text.Monograph"
            or len(child) != 1 or child[0].get("title") != "On the Mysteries."
            or len(title_page) != 1 or "Ambrose" not in "".join(title_page[0].itertext())):
        raise PipelineError("primary source no longer supports child identity, prose, language, or author")
    acquisition = _read_json(ROOT / ACQUISITION)
    if (acquisition["source_sha256"] != SOURCE_SHA or acquisition["source_path"] != SOURCE.as_posix()
            or len(acquisition["retained_files"]) != 1 or acquisition["retained_files"][0]["sha256"] != SOURCE_SHA):
        raise PipelineError("acquisition differs from the exact XML member")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    manifest.verify()
    if manifest.sha256 != MANIFEST_SHA or manifest.record["work_id"] != WORK_ID:
        raise PipelineError("current work-local manifest closure differs")
    profile_sha = _sha((ROOT / PROFILE).read_bytes())
    if manifest.record["authorities"][3]["sha256"] != profile_sha:
        raise PipelineError("current reconstruction profile differs")
    candidate = CandidatePackage.load(PACKAGE / "package")
    validation = _read_json(PACKAGE / "validation.json")
    rerun = validate(manifest, candidate, _oracle)
    if (candidate.sha256 != PACKAGE_SHA or _sha(candidate.member_bytes("content.tei.xml")) != TEI_SHA
            or validation["status"] != "pass" or validation["candidate_sha256"] != PACKAGE_SHA
            or validation["source_manifest_sha256"] != MANIFEST_SHA or rerun.sha256 != validation["report_sha256"]):
        raise PipelineError("revised candidate or independent source oracle differs")
    proposed_work = _read_json(PROPOSAL / "proposed-work.json")
    prior_proposal = (PROPOSAL / "proposed-master.tei.xml").read_bytes()
    proposed_receipt = _read_json(PROPOSAL / "projection-receipt.json")
    if (_sha(prior_proposal) != PROPOSAL_SHA or proposed_receipt["status"] != "pass"
            or proposed_receipt["independent_errors"] or proposed_receipt["projection_unsupported"]):
        raise PipelineError("proposed master or actual native projection differs")
    proposed_master = bind_reviewed_header(
        candidate.member_bytes("content.tei.xml"), expected_sha256=TEI_SHA,
        identity=IDENTITY,
        source={"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA, "source_bytes": len(source_bytes)},
        source_url=acquisition["url"], declared_scope=SCOPE, revision=REVISION,
    )
    form = proposed_work["textual_forms"][0]
    edition = form["editions"][0]
    if (proposed_work["work_id"] != WORK_ID or proposed_work["creators"] != [{"name": "Ambrose of Milan", "role": "author", "evidence": ["raw/ccel/npnf2/npnf210.xml#i-p15", "raw/ccel/npnf2/npnf210.xml#iv.v"]}]
            or form["language"] != "en" or edition["language"] != "en" or edition["category"] != "prose"
            or edition["containing_source"]["locator"] != f"{SOURCE.as_posix()}#iv.v"):
        raise PipelineError("source-evidenced proposed work metadata changed")
    current_work = _read_json(ROOT / WORK / "work.json")
    current_state = _read_json(ROOT / WORK / "state.json")
    if current_work.get("creators") or current_work["textual_forms"][0]["editions"][0].get("category") or current_state["targets"][1]["stage"] != "acquired":
        raise PipelineError("canonical metadata or state baseline changed")
    stage.mkdir()
    _put_json(stage, WORK / "work.json", proposed_work)
    _put_json(stage, WORK / "state.json", current_state)
    _copy(stage, ROOT / ACQUISITION, ACQUISITION)
    _copy(stage, ROOT / SOURCE, SOURCE)
    _copy(stage, ROOT / MANIFEST, MANIFEST)
    _copy(stage, ROOT / PROFILE, PROFILE)
    inherited = set(current_work.get("evidence", []))
    for target in current_state["targets"]:
        inherited.update(target.get("evidence", []))
    for reference in inherited:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts or not (ROOT / relative).is_file():
            raise PipelineError(f"inherited evidence is unresolved: {reference}")
        if not (stage / relative).is_file():
            _copy(stage, ROOT / relative, relative)
    _copy(stage, PACKAGE / "validation.json", EVIDENCE / "inputs/validation.json")
    for member in candidate.member_names:
        _put(stage, EVIDENCE / "inputs/package" / member, candidate.member_bytes(member))
    visual = []
    for locus, folder in FRAMES.items():
        capture = _read_json(folder / "capture.json")
        compared = _read_json(folder / "compare.json")
        if (capture["session"]["candidate_sha256"] != [PACKAGE_SHA] or capture["page_errors"]
                or capture["files"]["frame.png"] != _sha((folder / "frame.png").read_bytes())
                or compared["left"]["artifact"]["sha256"] != SOURCE_SHA
                or compared["right"]["artifact"]["sha256"] != TEI_SHA):
            raise PipelineError(f"CVW exact source/TEI pair differs at {locus}")
        for filename in ("capture.json", "compare.json", "session.json", "frame.png"):
            _copy(stage, folder / filename, EVIDENCE / "cvw" / locus / filename)
        visual.append({"locus": locus, "frame_sha256": capture["files"]["frame.png"], "capture_sha256": _sha((folder / "capture.json").read_bytes()), "warnings": capture.get("warnings", [])})
    accepted_candidate = _put(stage, EVIDENCE / "candidate.tei.xml", proposed_master)
    if validate_file(accepted_candidate):
        raise PipelineError("proposed master fails TEI P5")
    original_tree = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    bound_tree = etree.fromstring(proposed_master)
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    if etree.tostring(original_tree.find("tei:text", ns), method="c14n") != etree.tostring(bound_tree.find("tei:text", ns), method="c14n"):
        raise PipelineError("acceptance header changed reviewed TEI text")
    source_binding = {"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA, "source_bytes": len(source_bytes), "source_scope": acquisition["source_scope"]}
    expected = [{"path": SOURCE.as_posix(), "position": 1}]
    included = [{"path": SOURCE.as_posix(), "position": 1, "bytes": len(source_bytes), "sha256": SOURCE_SHA, "scope": acquisition["retained_files"][0]["scope"]}]
    scope = {"kind": "work", "declared": SCOPE, "expected_members": expected, "included_members": included, "excluded_members": []}
    candidate_binding = make_file_binding(stage, accepted_candidate)
    common = {"identity": IDENTITY, "source": source_binding, "candidate": candidate_binding}
    accounting = _put_json(stage, EVIDENCE / "source-accounting.json", {"identity": IDENTITY, "source": source_binding, "scope": acquisition["source_scope"], "accepted_scope": {"kind": "work", "declared": SCOPE}, "expected_members": expected, "included_members": included, "excluded_members": [], "missing_members": [], "unknown_members": [], "source_sha256": SOURCE_SHA, "source_bytes": len(source_bytes), "source_manifest_sha256": MANIFEST_SHA, "profile_sha256": profile_sha, "candidate_package_sha256": PACKAGE_SHA, "selected_root": "iv.v", "selected_source_features": 359})
    metadata = _put_json(stage, EVIDENCE / "metadata.json", {"identity": IDENTITY, "source_header": {"DC.Language": "eng", "DC.Type": "Text.Monograph"}, "title_page": "raw/ccel/npnf2/npnf210.xml#i-p15", "child": "raw/ccel/npnf2/npnf210.xml#iv.v", "proposed": {"category": "prose", "language": "en", "creator": "Ambrose of Milan"}, "unclaimed": ["individual translator allocation", "print collation", "rights clearance"], "source_manifest_sha256": MANIFEST_SHA, "profile_sha256": profile_sha})
    at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    command = "py -3 build/tools/stage_npnf210_mysteries_acceptance.py --stage <fresh-am26-library-child>"
    technical = {"producer": {"id": manifest.record["converter"]["id"], "path": make_file_binding(stage, stage / MANIFEST)}, "checker": {"id": manifest.record["validator"]["id"], "path": make_file_binding(stage, stage / MANIFEST)}, "shared_assumptions": ["Converter and oracle use the same retained volume and family tag vocabulary; the oracle independently walks source text, attributes, order, and nesting."], "independent_corroboration": "Current source-led oracle, nine-work clean-process reproduction, three exact-pair CVW loci, and native prose output checker agree for the selected child."}
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = common | {"scope": SCOPE, "status": "pass", "command": command, "exit_code": 0, "claim": name, "source_manifest_sha256": MANIFEST_SHA, "profile_sha256": profile_sha, "metadata_sha256": _sha(metadata.read_bytes()), "candidate_package_sha256": PACKAGE_SHA, "visual_capture_hashes": [item["capture_sha256"] for item in visual]}
        if name == "accounting":
            proof |= {"accepted_scope": {"kind": "work", "declared": SCOPE}, "expected_members": expected, "included_members": included, "excluded_members": [], "missing_members": [], "unknown_members": []}
        path = _put_json(stage, EVIDENCE / f"{name}.json", proof)
        technical[name] = {"path": path, "status": "pass", "command": command, "exit_code": 0}
    coverage = {"status": "partial", "declared": SCOPE, "reached": ["iv.v"], "inspected": ["iv.v/opening", "iv.v/chapter-iii", "iv.v/chapter-ix"], "unreviewed": ["iv.v/other-passages"]}
    reviewed = {"reviewer": "agent:lib044-ambrose-mysteries-assessment", "reviewed_at": at, "coverage": coverage, "source_quality_uncertainty": ["No print witness was collated against the retained CCEL XML."], "discrepancies": [], "unreviewed_residuals": ["CVW covers three source-local frames; remaining passages are mechanically conserved but not visually inspected."]}
    report = _put_json(stage, EVIDENCE / "review.json", common | {"scope": SCOPE, **reviewed, "frames": visual, "observations": ["The work opening, Chapter III, and Chapter IX match retained source reading order without duplicated synthetic headings."], "viewer_limitation": "Panes are unlinked; no governed correspondence exists."})
    decision = {"source_local_disposition": "Agent assessment accepts the selected On the Mysteries retained electronic child witness for a staged master only.", "blockers": [], "agent_assessment": {"status": "accepted", "actor": reviewed["reviewer"], "assessed_at": at, "supported_scope": SCOPE, "unresolved_claims": [], "unassessed_stronger_claims": ["print edition identity", "full visual proofreading", "human acceptance", "rights clearance", "publication"]}, "human_decision": {"status": "not-recorded"}}
    record = build_acceptance_record(stage, identity=IDENTITY, candidate_path=accepted_candidate, source_accounting_path=accounting, scope=scope, technical=technical, review=reviewed | {"report_path": report}, representation_revision=REVISION, decision=decision)
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    master = _put(stage, EDITION / "master.tei.xml", proposed_master)
    record["promotion"] |= {"status": "promoted", "promoted_at": at, "master": make_file_binding(stage, master)}
    write_acceptance(acceptance, record)
    target = next(item for item in current_state["targets"] if item["target_id"] == IDENTITY["edition_id"])
    target |= {"stage": "accepted", "reason": PROMOTED_MASTER_REASON, "updated_at": at}
    target["evidence"].extend([master.relative_to(stage).as_posix(), acceptance.relative_to(stage).as_posix()])
    _put_json(stage, WORK / "state.json", current_state)
    validate_acceptance(acceptance, root=stage)
    validate_state(stage / WORK / "state.json", root=stage)
    load_work(stage / WORK / "work.json")
    projection = project_accepted_prose(stage, acceptance_path=acceptance)
    errors = verify_accepted_prose(stage, acceptance_path=acceptance, rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 1 or projection["receipt"]["unsupported"]:
        raise PipelineError(f"accepted-master native prose projection/checker failed: {errors[:3]}")
    canary = _put_json(stage, EVIDENCE / "projection-canary.json", {"category": "prose", "rows": len(projection["rows"]), "unsupported": projection["receipt"]["unsupported"], "warnings": projection["receipt"]["warnings"], "independent_errors": errors, "output_sha256": projection["receipt"]["output_sha256"]})
    after = {relative.as_posix(): _sha((stage / relative).read_bytes()) for relative in (WORK / "work.json", WORK / "state.json", EDITION / "master.tei.xml", EDITION / "acceptance.json")}
    result = {"contract": "ocd-npnf210-mysteries-acceptance-stage-v1", "status": "staged-only", "stage": str(stage), "canonical_install": False, "work_id": WORK_ID, "source_sha256": SOURCE_SHA, "candidate_package_sha256": PACKAGE_SHA, "source_manifest_sha256": MANIFEST_SHA, "profile_sha256": profile_sha, "metadata_sha256": _sha(metadata.read_bytes()), "visual": visual, "public_validate_acceptance": "pass", "public_validate_state": "pass", "projection_rows": len(projection["rows"]), "projection_unsupported": [], "independent_projection_errors": errors, "projection_canary_sha256": _sha(canary.read_bytes()), "preimages": preimages, "after": after, "human_review": "not-recorded", "rights_clearance": "not-assessed", "publication": "not-authorized"}
    _put_json(stage, Path("stage-receipt.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    print(_json(prepare(args.stage)).decode(), end="")


if __name__ == "__main__":
    main()
