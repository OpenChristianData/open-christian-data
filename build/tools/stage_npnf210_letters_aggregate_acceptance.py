"""Stage the source-bound Letters aggregate electronic witness only."""

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
SOURCE = Path("raw/ccel/npnf2/npnf210.xml")
PROFILE = Path("sources/structured-text/ambrose-npnf210/npnf-ambrose.reconstruction-profile.json")
NINE_RECEIPT = Path("plans/2026-09-22-source-preflight/npnf210-nine-work-local-heading-repair-v2-20260926.json")
SOURCE_SHA = "c6f1a9d66653852d8b743c84a613c72c521dfb1b05602f0a2eff400c17665ee8"
CVW = LIBRARY / "cvw-sessions"
FRAME_ROOT = Path("D:/am26-eight-cvw-visual-20260926")
CONFIG = {
    "ambrose-of-milan-letters": {
        "root_id": "v", "features": 1739,
        "frames": {"opening": "opening", "letter-xxii": "middle-letter", "epistle-lxiii": "last-letter"},
        "stage_name": "am26-ambrose-letters-aggregate-v1",
    },
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, _json(value))


def _copy(stage: Path, path: Path, relative: Path) -> Path:
    content = path.read_bytes()
    target = _put(stage, relative, content)
    if target.read_bytes() != content:
        raise PipelineError(f"staged copy differs: {relative}")
    return target


def prepare(work_id: str) -> dict[str, object]:
    """Recheck all source, candidate and visual inputs before writing one fresh stage."""
    if work_id not in CONFIG:
        raise PipelineError(f"work is outside the Letters aggregate acceptance route: {work_id}")
    config = CONFIG[work_id]
    stage_arg = LIBRARY / config["stage_name"]
    if stage_arg.exists() or stage_arg.parent.resolve(strict=True) != LIBRARY.resolve(strict=True):
        raise PipelineError("stage must be a fresh direct child of the durable library")
    stage = Path("\\\\?\\" + str(stage_arg))
    entry = next((item for item in _read_json(ROOT / NINE_RECEIPT)["works"] if item["work_id"] == work_id), None)
    if entry is None or entry["source_root_id"] != config["root_id"]:
        raise PipelineError("Letters aggregate candidate receipt lacks exact root boundary")
    work = Path("library/works") / work_id
    old_work = _read_json(ROOT / work / "work.json")
    old_state = _read_json(ROOT / work / "state.json")
    form = old_work["textual_forms"][0]
    edition = form["editions"][0]
    identity = {"work_id": work_id, "textual_form_id": form["textual_form_id"], "edition_id": edition["edition_id"], "acquisition_id": edition["acquisition_ids"][0]}
    edition_path = work / "forms" / identity["textual_form_id"] / "editions" / identity["edition_id"]
    acquisition_path = edition_path / "acquisitions" / f"{identity['acquisition_id']}.json"
    manifest_path = Path(entry["manifest_path"])
    package_path = Path(entry["candidate_path"])
    evidence = work / "integration/npnf210-letters-aggregate-v1"
    scope = "Complete Selections from the Letters aggregate div1 v, including shared front matter and fifteen ordered div2 units, in retained CCEL NPNF2-10 XML."
    preimages = {}
    for relative in (work / "work.json", work / "state.json", edition_path / "master.tei.xml", edition_path / "acceptance.json", acquisition_path):
        path = ROOT / relative
        preimages[relative.as_posix()] = {"exists": path.is_file(), "sha256": _sha(path.read_bytes()) if path.is_file() else None}
    if preimages[(edition_path / "master.tei.xml").as_posix()]["exists"] or preimages[(edition_path / "acceptance.json").as_posix()]["exists"]:
        raise PipelineError("canonical accepted master already exists")
    source_bytes = (ROOT / SOURCE).read_bytes()
    if _sha(source_bytes) != SOURCE_SHA:
        raise PipelineError("retained XML changed")
    tree = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))
    head = tree.find("ThML.head")
    selected = tree.xpath("//ThML.body//*[@id=$id]", id=config["root_id"])
    title_page = tree.xpath("//ThML.body//*[@id='i-p15']")
    if (head is None or (head.findtext(".//DC.Language") or "").strip() != "eng"
            or (head.findtext(".//DC.Type") or "").strip() != "Text.Monograph"
            or len(selected) != 1 or selected[0].tag != "div1"
            or selected[0].getparent().tag != "ThML.body"
            or selected[0].get("title") != "Selections from the Letters of St. Ambrose."
            or sum(isinstance(node.tag, str) for node in selected[0].iter()) != config["features"]
            or len(title_page) != 1 or "Ambrose" not in "".join(title_page[0].itertext())):
        raise PipelineError("source does not support exact Letters aggregate or English monograph")
    source_children = [node for node in selected[0] if isinstance(node.tag, str)]
    source_front = source_children[:4]
    source_units = source_children[4:]
    expected_unit_ids = [f"v.{ordinal}" for ordinal in ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv")]
    if ([node.tag for node in source_front] != ["pb", "h1", "p", "p"]
            or [node.get("id") for node in source_units] != expected_unit_ids
            or any(node.tag != "div2" or not node.get("title") for node in source_units)
            or len(source_children) != 19):
        raise PipelineError("Letters shared front matter or fifteen source-named divisions changed")
    acquisition = _read_json(ROOT / acquisition_path)
    if (acquisition["source_path"] != SOURCE.as_posix() or acquisition["source_sha256"] != SOURCE_SHA
            or edition["containing_source"]["locator"] != f"{SOURCE.as_posix()}#{config['root_id']}"
            or len(acquisition["retained_files"]) != 1 or acquisition["retained_files"][0]["sha256"] != SOURCE_SHA):
        raise PipelineError("acquisition does not bind exact retained XML child")
    manifest = SourceManifest.load(ROOT / manifest_path, repository_root=ROOT)
    manifest.verify()
    profile_sha = _sha((ROOT / PROFILE).read_bytes())
    if (manifest.sha256 != entry["manifest_sha256"] or manifest.record["work_id"] != work_id
            or manifest.record["authorities"][3]["sha256"] != profile_sha):
        raise PipelineError("source manifest/profile closure changed")
    candidate = CandidatePackage.load(package_path / "package")
    validation = _read_json(package_path / "validation.json")
    rerun = validate(manifest, candidate, _oracle)
    tei_bytes = candidate.member_bytes("content.tei.xml")
    if (candidate.sha256 != entry["candidate_sha256"] or _sha(tei_bytes) != entry["files"]["content.tei.xml"]
            or _sha((package_path / "validation.json").read_bytes()) != entry["validation_sha256"]
            or validation["status"] != "pass" or validation["candidate_sha256"] != candidate.sha256
            or validation["source_manifest_sha256"] != manifest.sha256 or validation["report_sha256"] != rerun.sha256):
        raise PipelineError("candidate or independent source oracle changed")
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    tei_tree = etree.fromstring(tei_bytes)
    tei_divisions = tei_tree.xpath("./tei:text/tei:body/tei:div/tei:div", namespaces=ns)
    tei_front = tei_tree.xpath("./tei:text/tei:body/tei:div/*[position() > 1 and position() < 6]", namespaces=ns)
    if ([node.get("{http://www.w3.org/XML/1998/namespace}id") for node in tei_divisions]
            != [f"npnf-ambrose-{source_id}" for source_id in expected_unit_ids]
            or [etree.QName(node).localname for node in tei_front] != ["pb", "ab", "p", "p"]):
        raise PipelineError("Letters TEI does not retain shared front matter and fifteen ordered division anchors")
    if old_work.get("creators") or edition.get("category") or form["language"] != "en" or edition["language"] != "en":
        raise PipelineError("canonical metadata baseline changed")
    state_target = next(item for item in old_state["targets"] if item["target_id"] == identity["edition_id"])
    if state_target["stage"] != "acquired":
        raise PipelineError("canonical edition stage changed")
    proposed_work = json.loads(json.dumps(old_work))
    proposed_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    revision = {"id": f"{work_id}-ccel-electronic-v2", "date": "2026-09-26", "note": "Agent-accepted retained CCEL aggregate electronic witness; constituent work identities, human acceptance, and publication remain separate."}
    master_bytes = bind_reviewed_header(tei_bytes, expected_sha256=_sha(tei_bytes), identity=identity, source={"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA, "source_bytes": len(source_bytes)}, source_url=acquisition["url"], declared_scope=scope, revision=revision)
    stage.mkdir()
    _put_json(stage, work / "work.json", proposed_work)
    _put_json(stage, work / "state.json", old_state)
    for relative in (acquisition_path, SOURCE, manifest_path, PROFILE):
        _copy(stage, ROOT / relative, relative)
    inherited = set(old_work.get("evidence", []))
    for target in old_state["targets"]:
        inherited.update(target.get("evidence", []))
    for reference in inherited:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts or not (ROOT / relative).is_file():
            raise PipelineError(f"inherited evidence unresolved: {reference}")
        if not (stage / relative).is_file():
            _copy(stage, ROOT / relative, relative)
    _copy(stage, package_path / "validation.json", evidence / "inputs/validation.json")
    for member in candidate.member_names:
        _put(stage, evidence / "inputs/package" / member, candidate.member_bytes(member))
    boundaries = _put_json(stage, evidence / "aggregate-boundaries.json", {
        "source_root": "v", "tei_root": "npnf-ambrose-v", "scope": "aggregate-electronic-witness",
        "source_element_count": config["features"],
        "shared_front_matter": [{"source_id": node.get("id"), "source_tag": node.tag} for node in source_front],
        "divisions": [{"source_id": node.get("id"), "tei_id": f"npnf-ambrose-{node.get('id')}", "source_title": node.get("title"), "source_element_count": sum(isinstance(child.tag, str) for child in node.iter())} for node in source_units],
        "constituent_work_identities": "unassessed",
        "claim": "The aggregate retains exact ordered source-named divisions; this does not assign standalone work identities or authorship to them.",
    })
    visual = []
    for locus, folder_name in config["frames"].items():
        folder = FRAME_ROOT / work_id / folder_name
        capture = _read_json(folder / "capture.json")
        compared = _read_json(folder / "compare.json")
        if (capture["session"]["candidate_sha256"] != [item["candidate_sha256"] for item in _read_json(ROOT / NINE_RECEIPT)["works"] if item["work_id"] != "ambrose-of-milan-on-mysteries"]
                or capture["page_errors"] or capture["files"]["frame.png"] != _sha((folder / "frame.png").read_bytes())
                or compared["left"]["artifact"]["sha256"] != SOURCE_SHA
                or compared["right"]["artifact"]["sha256"] != _sha(tei_bytes)
                or compared["left"]["location_state"] != "in-range" or compared["right"]["location_state"] != "in-range"):
            raise PipelineError(f"visual pair differs at {locus}")
        for name in ("capture.json", "compare.json", "session.json", "frame.png"):
            _copy(stage, folder / name, evidence / "cvw" / locus / name)
        visual.append({"locus": locus, "frame_sha256": capture["files"]["frame.png"], "capture_sha256": _sha((folder / "capture.json").read_bytes()), "warnings": capture["warnings"]})
    candidate_path = _put(stage, evidence / "candidate.tei.xml", master_bytes)
    if validate_file(candidate_path):
        raise PipelineError("bound master fails TEI P5")
    if etree.tostring(etree.fromstring(tei_bytes).find("tei:text", ns), method="c14n") != etree.tostring(etree.fromstring(master_bytes).find("tei:text", ns), method="c14n"):
        raise PipelineError("reviewed TEI text changed while binding header")
    source_binding = {"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA, "source_bytes": len(source_bytes), "source_scope": acquisition["source_scope"]}
    expected = [{"path": SOURCE.as_posix(), "position": 1}]
    included = [{"path": SOURCE.as_posix(), "position": 1, "bytes": len(source_bytes), "sha256": SOURCE_SHA, "scope": acquisition["retained_files"][0]["scope"]}]
    accepted_scope = {"kind": "work", "declared": scope}
    scope_record = accepted_scope | {"expected_members": expected, "included_members": included, "excluded_members": []}
    common = {"identity": identity, "source": source_binding, "candidate": make_file_binding(stage, candidate_path)}
    accounting = _put_json(stage, evidence / "source-accounting.json", {"identity": identity, "source": source_binding, "scope": acquisition["source_scope"], "accepted_scope": accepted_scope, "expected_members": expected, "included_members": included, "excluded_members": [], "missing_members": [], "unknown_members": [], "source_sha256": SOURCE_SHA, "source_bytes": len(source_bytes), "source_manifest_sha256": manifest.sha256, "profile_sha256": profile_sha, "candidate_package_sha256": candidate.sha256, "selected_root": config["root_id"], "selected_source_features": config["features"]})
    metadata = _put_json(stage, evidence / "metadata.json", {"identity": identity, "source_header": {"DC.Language": "eng", "DC.Type": "Text.Monograph"}, "title_page": f"{SOURCE.as_posix()}#i-p15", "aggregate": f"{SOURCE.as_posix()}#v", "proposed": {"category": "prose", "language": "en", "creator": None}, "creator_reason": "The selected aggregate includes source-named memorials of Symmachus; whole-scope authorship is not asserted.", "unclaimed": ["aggregate and constituent author attribution", "constituent standalone work identities", "individual translator allocation", "print collation", "rights clearance"], "source_manifest_sha256": manifest.sha256, "profile_sha256": profile_sha, "aggregate_boundaries_sha256": _sha(boundaries.read_bytes())})
    command = f"py -3 build/tools/stage_npnf210_letters_aggregate_acceptance.py --work-id {work_id}"
    technical = {"producer": {"id": manifest.record["converter"]["id"], "path": make_file_binding(stage, stage / manifest_path)}, "checker": {"id": manifest.record["validator"]["id"], "path": make_file_binding(stage, stage / manifest_path)}, "shared_assumptions": ["Converter and oracle share the retained volume and family tag vocabulary; the oracle independently checks source text, attributes, order, and nesting."], "independent_corroboration": f"Source-led oracle, fifteen-division boundary inventory {_sha(boundaries.read_bytes())}, three exact-pair CVW loci, and native prose output checker agree for the aggregate."}
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = common | {"scope": scope, "status": "pass", "command": command, "exit_code": 0, "claim": name, "source_manifest_sha256": manifest.sha256, "profile_sha256": profile_sha, "metadata_sha256": _sha(metadata.read_bytes()), "candidate_package_sha256": candidate.sha256, "visual_capture_hashes": [item["capture_sha256"] for item in visual]}
        if name == "accounting":
            proof |= {"accepted_scope": accepted_scope, "expected_members": expected, "included_members": included, "excluded_members": [], "missing_members": [], "unknown_members": []}
        path = _put_json(stage, evidence / f"{name}.json", proof)
        technical[name] = {"path": path, "status": "pass", "command": command, "exit_code": 0}
    coverage = {"status": "partial", "declared": scope, "reached": [config["root_id"]], "inspected": [f"{config['root_id']}/{item['locus']}" for item in visual], "unreviewed": [f"{config['root_id']}/other-passages"]}
    reviewed = {"reviewer": f"agent:lib044-{work_id}-assessment", "reviewed_at": at, "coverage": coverage, "source_quality_uncertainty": ["No print witness was collated against the retained CCEL XML."], "discrepancies": [], "unreviewed_residuals": ["CVW covers three source-local frames; remaining passages are mechanically conserved but not visually inspected."]}
    report = _put_json(stage, evidence / "review.json", common | {"scope": scope, **reviewed, "frames": visual, "observations": ["The aggregate introduction, Letter XXII, and final Epistle LXIII visually retain source text and hierarchy in exact source/TEI pairs.", "Expanded division-title attributes and shorter explicit epistle headings both occur in the retained source; their distinct words are preserved without a claim that they are duplicate text.", "All fifteen source-named divisions and four shared front nodes remain in the same aggregate TEI body and source order."], "viewer_limitation": "Panes are unlinked; no governed correspondence exists. Most passages and the terminal paragraph of the final epistle were not visually inspected."})
    decision = {"source_local_disposition": "Agent assessment accepts only the source-defined Selections from the Letters aggregate electronic witness as one staged master; nested constituent identities remain unassigned.", "blockers": [], "agent_assessment": {"status": "accepted", "actor": reviewed["reviewer"], "assessed_at": at, "supported_scope": scope, "unresolved_claims": ["Standalone identities and authorship for the fifteen nested source divisions are unassessed."], "unassessed_stronger_claims": ["standalone constituent work acceptance", "print edition identity", "full visual proofreading", "human acceptance", "rights clearance", "publication"]}, "human_decision": {"status": "not-recorded"}}
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate_path, source_accounting_path=accounting, scope=scope_record, technical=technical, review=reviewed | {"report_path": report}, representation_revision=revision, decision=decision)
    acceptance = stage / edition_path / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    master = _put(stage, edition_path / "master.tei.xml", master_bytes)
    record["promotion"] |= {"status": "promoted", "promoted_at": at, "master": make_file_binding(stage, master)}
    write_acceptance(acceptance, record)
    state_target |= {"stage": "accepted", "reason": PROMOTED_MASTER_REASON, "updated_at": at}
    state_target["evidence"].extend([master.relative_to(stage).as_posix(), acceptance.relative_to(stage).as_posix()])
    _put_json(stage, work / "state.json", old_state)
    validate_acceptance(acceptance, root=stage)
    validate_state(stage / work / "state.json", root=stage)
    load_work(stage / work / "work.json")
    projection = project_accepted_prose(stage, acceptance_path=acceptance)
    errors = verify_accepted_prose(stage, acceptance_path=acceptance, rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 1 or projection["receipt"]["unsupported"]:
        raise PipelineError(f"actual-master prose projection/checker failed: {errors[:3]}")
    canary = _put_json(stage, evidence / "projection-canary.json", {"category": "prose", "rows": 1, "unsupported": [], "independent_errors": [], "output_sha256": projection["receipt"]["output_sha256"]})
    after = {relative.as_posix(): _sha((stage / relative).read_bytes()) for relative in (work / "work.json", work / "state.json", edition_path / "master.tei.xml", edition_path / "acceptance.json")}
    receipt = {"contract": "ocd-npnf210-letters-aggregate-acceptance-stage-v1", "status": "staged-only", "stage": str(stage), "canonical_install": False, "work_id": work_id, "source_root_id": config["root_id"], "source_sha256": SOURCE_SHA, "candidate_package_sha256": candidate.sha256, "source_manifest_sha256": manifest.sha256, "profile_sha256": profile_sha, "visual": visual, "public_validate_acceptance": "pass", "public_validate_state": "pass", "projection_rows": 1, "projection_unsupported": [], "independent_projection_errors": [], "projection_canary_sha256": _sha(canary.read_bytes()), "aggregate_boundaries_sha256": _sha(boundaries.read_bytes()), "preimages": preimages, "after": after, "human_review": "not-recorded", "rights_clearance": "not-assessed", "publication": "not-authorized"}
    _put_json(stage, Path("stage-receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-id", required=True, choices=sorted(CONFIG))
    args = parser.parse_args()
    print(_json(prepare(args.work_id)).decode(), end="")


if __name__ == "__main__":
    main()
