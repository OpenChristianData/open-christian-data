"""Prepare a guarded, noncanonical Bounds Power electronic-witness acceptance.

The staged tree is deliberately separate from the repository's library. It
contains a proposed accepted generation and a local prose-projection canary;
this command has no install or publication operation.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from lxml import etree

from build.tei.lib031_work_local_oracle import _oracle
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "bounds-power-through-prayer"
IDENTITY = {
    "work_id": WORK_ID,
    "textual_form_id": "bounds-power-through-prayer-english",
    "edition_id": "bounds-power-through-prayer-ccel-thml-electronic",
    "acquisition_id": "bounds-power-through-prayer-ccel-retained-xml",
}
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / IDENTITY["textual_form_id"] / "editions" / IDENTITY["edition_id"]
EVIDENCE = WORK / "integration/lib031-bounds-power-electronic-v1"
ACQUISITION = EDITION / "acquisitions" / (IDENTITY["acquisition_id"] + ".json")
SOURCE = Path("raw/ccel/bounds/power.xml")
MANIFEST = Path("sources/structured-text") / WORK_ID / "lib031-work.source-manifest.json"
PROFILE = Path("sources/structured-text/bounds-essentials-of-prayer/lib031.reconstruction-profile.json")
REVIEW_ROOT = Path(r"D:\Library\Open Christian Data\candidate-reviews")
PACKAGE = REVIEW_ROOT / f"lib031-work-{WORK_ID}-20260926-v6"
VISUAL_ROOT = Path(r"D:\Library\Open Christian Data\cvw-sessions")
VISUAL = {
    "opening": VISUAL_ROOT / "lib031-bounds-power-v6-opening-20260926",
    "ending": VISUAL_ROOT / "lib031-bounds-power-v6-ending-20260926",
}
SCOPE = "Complete retained CCEL electronic witness raw/ccel/bounds/power.xml (one acquired XML file)."
NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


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
    return _put(stage, relative, (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def _copy(stage: Path, source: Path, relative: Path) -> Path:
    content = source.read_bytes()
    target = _put(stage, relative, content)
    if target.read_bytes() != content:
        raise PipelineError(f"stage copy changed: {source}")
    return target


def _visual(stage: Path, package_hash: str, source_hash: str, tei_hash: str) -> list[dict[str, object]]:
    frames = []
    for label, source in VISUAL.items():
        receipt = _read_json(source / "capture.json")
        if (receipt.get("contract") != "ocd-cvw-capture-bundle-v1"
                or receipt.get("session", {}).get("candidate_sha256") != [package_hash]
                or receipt.get("page_errors") != []
                or receipt.get("files", {}).get("frame.png") != _sha((source / "frame.png").read_bytes())):
            raise PipelineError(f"visual receipt is not bound to v6: {label}")
        response = _read_json(source / "compare.json")
        if (response.get("left", {}).get("artifact", {}).get("sha256") != source_hash
                or response.get("right", {}).get("artifact", {}).get("sha256") != tei_hash):
            raise PipelineError(f"visual panes do not bind the source and TEI: {label}")
        if label == "ending":
            targets = receipt.get("targets", {})
            if any(targets.get(side, {}).get("literal") != "Let us pray ardently" or not targets[side].get("visible") for side in ("left", "right")):
                raise PipelineError("closing paragraph was not visible in both panes")
        for name in ("capture.json", "compare.json", "session.json", "frame.png"):
            _copy(stage, source / name, EVIDENCE / "cvw" / label / name)
        frames.append({"locus": label, "capture_sha256": _sha((source / "capture.json").read_bytes()), "frame_sha256": receipt["files"]["frame.png"], "warnings": receipt.get("warnings", [])})
    return frames


def prepare(stage: Path) -> dict[str, object]:
    stage = stage.resolve(strict=False)
    if (stage.exists() or stage.parent.resolve(strict=True) != REVIEW_ROOT.parent.resolve(strict=True)
            or not stage.name.startswith("bpow")):
        raise PipelineError("stage must be a fresh bpow-prefixed direct child of the durable library root")
    source_bytes = (ROOT / SOURCE).read_bytes()
    acquisition = _read_json(ROOT / ACQUISITION)
    retained = acquisition["retained_files"]
    if (len(retained) != 1 or retained[0]["path"] != SOURCE.as_posix()
            or retained[0]["sha256"] != _sha(source_bytes)
            or retained[0]["bytes"] != len(source_bytes)
            or acquisition["source_sha256"] != _sha(source_bytes)):
        raise PipelineError("Bounds acquisition differs from exact retained source")
    source_tree = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, no_network=True))
    if (source_tree.findtext(".//DC.Title") != "Power Through Prayer"
            or source_tree.findtext(".//DC.Language") != "eng"
            or source_tree.findtext(".//DC.Type") != "Text.Monograph"
            or source_tree.findtext(".//DC.Publisher") != "Grand Rapids, MI: Christian Classics Ethereal Library"
            or source_tree.findtext(".//DC.Creator[@scheme='file-as']") != "Bounds, Edward M. (1835-1913)"):
        raise PipelineError("primary CCEL header no longer supports staged metadata")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    manifest.verify()
    if manifest.record.get("work_id") != WORK_ID or manifest.record["authorities"][0]["sha256"] != _sha(source_bytes):
        raise PipelineError("work-local manifest identity differs")
    profile_sha = _sha((ROOT / PROFILE).read_bytes())
    if manifest.record["authorities"][3]["sha256"] != profile_sha:
        raise PipelineError("work-local source profile binding differs")
    candidate = CandidatePackage.load(PACKAGE / "package")
    validation = _read_json(PACKAGE / "validation.json")
    rerun = validate(manifest, candidate, _oracle)
    if (validation.get("status") != "pass" or validation.get("candidate_sha256") != candidate.sha256
            or validation.get("source_manifest_sha256") != manifest.sha256 or rerun.sha256 != validation.get("report_sha256")):
        raise PipelineError("current independent oracle or validation sidecar differs")
    original = candidate.member_bytes("content.tei.xml")
    original_tree = etree.fromstring(original)
    if original_tree.xpath("string(./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:publisher)", namespaces=NS) != "Grand Rapids, MI: Christian Classics Ethereal Library":
        raise PipelineError("TEI does not credit the retained electronic publisher")
    frames_input = [(source / "capture.json", source / "frame.png") for source in VISUAL.values()]
    if any(not capture.is_file() or not frame.is_file() for capture, frame in frames_input):
        raise PipelineError("bounded work-local visual evidence is missing")
    stage.mkdir()
    work = _read_json(ROOT / WORK / "work.json")
    state = _read_json(ROOT / WORK / "state.json")
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    if (work["work_id"] != WORK_ID or form["language"] != "en" or edition["language"] != "en"
            or edition["edition_id"] != IDENTITY["edition_id"] or edition["acquisition_ids"] != [IDENTITY["acquisition_id"]]
            or edition.get("category") is not None or work.get("creators")):
        raise PipelineError("canonical work metadata changed; review staged metadata delta")
    edition["category"] = "prose"
    work["creators"] = [{"name": "Edward M. Bounds", "role": "author", "evidence": [SOURCE.as_posix()]}]
    _put_json(stage, WORK / "work.json", work)
    _put_json(stage, WORK / "state.json", state)
    _copy(stage, ROOT / ACQUISITION, ACQUISITION)
    _copy(stage, ROOT / SOURCE, SOURCE)
    _copy(stage, ROOT / MANIFEST, MANIFEST)
    _copy(stage, ROOT / PROFILE, PROFILE)
    inherited_evidence = set(work.get("evidence", []))
    for target in state["targets"]:
        inherited_evidence.update(target.get("evidence", []))
    for reference in sorted(inherited_evidence):
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts or not (ROOT / relative).is_file():
            raise PipelineError(f"staged inherited evidence cannot be resolved: {reference}")
        if not (stage / relative).is_file():
            _copy(stage, ROOT / relative, relative)
    _copy(stage, PACKAGE / "validation.json", EVIDENCE / "inputs/validation.json")
    for member in candidate.member_names:
        _put(stage, EVIDENCE / "inputs/package" / member, candidate.member_bytes(member))
    frames = _visual(stage, candidate.sha256, _sha(source_bytes), _sha(original))
    now = datetime.now(timezone.utc)
    at = now.isoformat().replace("+00:00", "Z")
    revision = {"id": "bounds-power-ccel-electronic-v1", "date": now.date().isoformat(), "note": "Accept the complete retained CCEL Power Through Prayer electronic witness."}
    source_binding = {"source_path": SOURCE.as_posix(), "source_sha256": _sha(source_bytes), "source_bytes": len(source_bytes), "source_scope": acquisition["source_scope"]}
    bound = bind_reviewed_header(original, expected_sha256=_sha(original), identity=IDENTITY, source=source_binding, source_url=acquisition["url"], declared_scope=SCOPE, revision=revision)
    accepted_candidate = _put(stage, EVIDENCE / "candidate.tei.xml", bound)
    errors = validate_file(accepted_candidate)
    if errors:
        raise PipelineError(f"staged TEI P5 failed: {errors[:3]}")
    bound_tree = etree.fromstring(bound)
    if (etree.tostring(original_tree.find("tei:text", NS), method="c14n")
            != etree.tostring(bound_tree.find("tei:text", NS), method="c14n")):
        raise PipelineError("acceptance header integration changed reviewed TEI text")
    expected = [{"path": SOURCE.as_posix(), "position": 1}]
    included = [{"path": SOURCE.as_posix(), "position": 1, "bytes": len(source_bytes), "sha256": _sha(source_bytes), "scope": retained[0]["scope"]}]
    scope = {"kind": "edition", "declared": SCOPE, "expected_members": expected, "included_members": included, "excluded_members": []}
    candidate_binding = make_file_binding(stage, accepted_candidate)
    common = {"identity": IDENTITY, "source": source_binding, "candidate": candidate_binding}
    accounting = _put_json(stage, EVIDENCE / "source-accounting.json", {"identity": IDENTITY, "source": source_binding, "scope": source_binding["source_scope"], "accepted_scope": {"kind": "edition", "declared": SCOPE}, "expected_members": expected, "included_members": included, "excluded_members": [], "missing_members": [], "unknown_members": [], "source_sha256": _sha(source_bytes), "source_bytes": len(source_bytes), "source_manifest_sha256": manifest.sha256, "profile_sha256": profile_sha, "candidate_package_sha256": candidate.sha256, "body_nodes": 289})
    inputs = {"source_manifest_sha256": manifest.sha256, "profile_sha256": profile_sha, "candidate_package_sha256": candidate.sha256, "validation_sha256": _sha((PACKAGE / "validation.json").read_bytes()), "original_tei_sha256": _sha(original), "source_sha256": _sha(source_bytes)}
    metadata = _put_json(stage, EVIDENCE / "metadata.json", {"identity": IDENTITY, "source_header": {"DC.Title": "Power Through Prayer", "DC.Creator.file-as": "Bounds, Edward M. (1835-1913)", "DC.Language": "eng", "DC.Type": "Text.Monograph", "DC.Publisher": "Grand Rapids, MI: Christian Classics Ethereal Library"}, "proposed_work": {"category": "prose", "language": "en", "creator": "Edward M. Bounds"}, "unclaimed": ["print edition", "original publication year", "transcription license", "public release rights"], **inputs})
    command = "py -3 -m build.tools.stage_lib031_bounds_power_acceptance --stage <fresh-short-bpow-library-child>"
    technical = {"producer": {"id": manifest.record["converter"]["id"], "path": make_file_binding(stage, stage / MANIFEST)}, "checker": {"id": manifest.record["validator"]["id"], "path": make_file_binding(stage, stage / MANIFEST)}, "shared_assumptions": ["Both producer and oracle use the same retained one-file envelope and source-profile declaration; the oracle walks source XML independently and rejects semantic mutations."], "independent_corroboration": "The independently rerun source-led oracle, byte-for-byte package reproduction test, and two inspected work-local CVW frames agree for the declared electronic witness."}
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = common | {"scope": SCOPE, "status": "pass", "command": command, "exit_code": 0, "claim": name, "inputs": inputs, "metadata_sha256": _sha(metadata.read_bytes()), "visual_capture_hashes": [item["capture_sha256"] for item in frames]}
        if name == "accounting":
            proof |= {"accepted_scope": {"kind": "edition", "declared": SCOPE}, "expected_members": expected, "included_members": included, "excluded_members": [], "missing_members": [], "unknown_members": []}
        path = _put_json(stage, EVIDENCE / f"{name}.json", proof)
        technical[name] = {"path": path, "status": "pass", "command": command, "exit_code": 0}
    coverage = {"status": "partial", "declared": SCOPE, "reached": ["power.xml"], "inspected": ["power.xml/opening", "power.xml/XX/end"], "unreviewed": ["power.xml/other-content"]}
    reviewed = {"reviewer": "agent:lib031-bounds-power-assessment", "reviewed_at": at, "coverage": coverage, "source_quality_uncertainty": ["No print witness was collated against the retained CCEL XML."], "discrepancies": [], "unreviewed_residuals": ["The two visually inspected frames are a bounded sample; the remaining source nodes were checked mechanically."]}
    report = _put_json(stage, EVIDENCE / "review.json", common | {"scope": SCOPE, **reviewed, "frames": frames, "inspected_observations": ["Opening title, credited author, and first paragraphs agree in both panes; the TEI adds a structural Title Page heading.", "The final chapter's closing paragraphs, including 'Let us pray ardently', agree in both panes."], "viewer_limitation": "No governed correspondence mapping; independently selected unlinked panes. The ending frame records an out-of-range start-location notice while its targeted final paragraph is visible."})
    decision = {"source_local_disposition": "Agent acceptance of the complete retained CCEL Power Through Prayer electronic witness.", "blockers": [], "agent_assessment": {"status": "accepted", "actor": reviewed["reviewer"], "assessed_at": at, "supported_scope": SCOPE, "unresolved_claims": [], "unassessed_stronger_claims": ["print edition identity and collation", "full visual proofreading", "human acceptance", "public rights clearance", "publication"]}, "human_decision": {"status": "not-recorded"}}
    record = build_acceptance_record(stage, identity=IDENTITY, candidate_path=accepted_candidate, source_accounting_path=accounting, scope=scope, technical=technical, review=reviewed | {"report_path": report}, representation_revision=revision, decision=decision)
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    master = _put(stage, EDITION / "master.tei.xml", bound)
    record["promotion"] |= {"status": "promoted", "promoted_at": at, "master": make_file_binding(stage, master)}
    write_acceptance(acceptance, record)
    target = next((item for item in state["targets"] if item["target_id"] == IDENTITY["edition_id"]), None)
    if target is None or target["stage"] != "acquired":
        raise PipelineError("edition target is no longer acquired")
    target |= {"stage": "accepted", "reason": PROMOTED_MASTER_REASON, "updated_at": at}
    target["evidence"].extend([master.relative_to(stage).as_posix(), acceptance.relative_to(stage).as_posix()])
    _put_json(stage, WORK / "state.json", state)
    validate_acceptance(acceptance, root=stage)
    load_work(stage / WORK / "work.json")
    projection = project_accepted_prose(stage, acceptance_path=acceptance)
    problems = verify_accepted_prose(stage, acceptance_path=acceptance, rows=projection["rows"], receipt=projection["receipt"])
    if problems:
        raise PipelineError(f"independent accepted prose verification failed: {problems[:3]}")
    kinds: Counter[str] = Counter()

    def count_structure(value: object) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("kind"), str):
                kinds[value["kind"]] += 1
            for child in value.values():
                count_structure(child)
        elif isinstance(value, list):
            for child in value:
                count_structure(child)

    for row in projection["rows"]:
        count_structure(row.get("structure"))
    if (len(projection["rows"]) != 1 or kinds["division"] != 22 or kinds["heading"] != 21
            or projection["receipt"]["unsupported"]):
        raise PipelineError("native prose projection lost the source-supported chapter structure")
    canary = _put_json(stage, EVIDENCE / "projection-canary.json", {"category": "prose", "row_count": len(projection["rows"]), "structure_kinds": dict(kinds), "source_inventory_count": len(projection["receipt"]["inventory"]), "unsupported": projection["receipt"]["unsupported"], "warnings": projection["receipt"]["warnings"], "independent_verifier_errors": problems})
    result = {"contract": "ocd-lib031-bounds-power-stage-v1", "status": "staged-only", "stage_root": stage.as_posix(), "acceptance_path": acceptance.relative_to(stage).as_posix(), "acceptance_sha256": _sha(acceptance.read_bytes()), "master_sha256": _sha(master.read_bytes()), "source_sha256": _sha(source_bytes), "source_manifest_sha256": manifest.sha256, "profile_sha256": profile_sha, "candidate_package_sha256": candidate.sha256, "metadata_sha256": _sha(metadata.read_bytes()), "visual_frames": frames, "projection_category": "prose", "projection_rows": len(projection["rows"]), "projection_structure_kinds": dict(kinds), "projection_source_inventory_count": len(projection["receipt"]["inventory"]), "projection_canary_sha256": _sha(canary.read_bytes()), "projection_independent_verifier_errors": problems, "rights_clearance": "not-assessed", "human_review": "not-recorded", "publication": "not-authorized"}
    _put_json(stage, Path("stage-receipt.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.stage), sort_keys=True))


if __name__ == "__main__":
    main()
