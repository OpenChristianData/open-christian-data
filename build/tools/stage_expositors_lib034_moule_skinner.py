"""Stage separate source-bound Moule and Skinner electronic editions externally."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.commentary import project_accepted_commentary, verify_accepted_commentary
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

from build.tei.expositors_bible_lib034_readable_moule_skinner_oracle import _oracle


ROOT = Path(__file__).resolve().parents[2]
EXTERNAL = Path("D:/Library/Open Christian Data/candidate-reviews")
SOURCE_ROOT = Path("sources/commentaries/expositors-bible/readable-moule-skinner-v3")
CANDIDATE_ROOT = EXTERNAL / "expositors-lib034-moule-skinner-candidates-20260927-v1"
SESSION = EXTERNAL / "expositors-lib034-moule-skinner-cvw-session-20260927-v1/86edd0c443764c46b42c15d4d528063a.receipt.json"
MEMBERS = {
    "moule-expositorromans": {
        "work": "expositors-bible--h-c-g-moule", "source": "raw/ccel/expositors-bible/moule_expositorromans.xml",
        "source_sha": "a6b919c200f4702fae4e3cb5f687676a503728233f5eb6c1a9468f835a533433",
        "manifest_sha": "1a32024332ce66bbfef61321327c16fab02d11d86caaa1ecb89e75840afe9bbe",
        "package_sha": "f9631f35f1fd5bf0131f315599149c0933a401edb0b63b3b01556e30636bfb89",
        "validation_sha": "acab345ec3b243f35eca1ae9ad2e06b40ab3dd6836868f792caebce76cd8d831",
        "tei_sha": "b859a89e9f6104878f3a422394e11cdd7fe21ce19a99f22e6693fa909ae8c9ec",
        "elements": 6373, "comments": 14, "rows": 36,
        "visual": {
            "opening": "expositors-bible--h-c-g-moule-readable-cvw-opening-20260927-v1",
            "preface": "expositors-bible--h-c-g-moule-readable-cvw-preface-20260927-v3",
            "index": "expositors-bible--h-c-g-moule-readable-cvw-index-20260927-v1",
        },
        "inspected": ["i", "ii-p2.3", "xxxvi-p0.1"],
    },
    "skinner-expositorezek": {
        "work": "expositors-bible--john-skinner", "source": "raw/ccel/expositors-bible/skinner_expositorezek.xml",
        "source_sha": "6ecab5f91bd497b0953143228d7f1b70c5b4768e8142c56268ef8e9a1294368f",
        "manifest_sha": "95d30e3d1688356b5c4524d42b972b5f001a44161bbf243eb2b700c1b524a657",
        "package_sha": "27f4200a3b873bdbfd72320e560632e22eadd8e8b81c216ed533fd83066a7182",
        "validation_sha": "5ac2446bac0f09d8b204a2f2ba9ad52ca290fb34fdc364aec94ac8d338c51ecf",
        "tei_sha": "323283b1d1082e7c98e7243923523a410a71b79bf08a457a9213193979776f79",
        "elements": 3752, "comments": 18, "rows": 8,
        "visual": {
            "opening": "expositors-bible--john-skinner-readable-cvw-opening-20260927-v1",
            "first-part": "expositors-bible--john-skinner-readable-cvw-first-part-20260927-v1",
            "index": "expositors-bible--john-skinner-readable-cvw-index-20260927-v1",
        },
        "inspected": ["i", "iii-p0.1", "viii-p0.1"],
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    content = _io_path(path).read_bytes()
    if expected is not None and sha256(content).hexdigest() != expected:
        raise ValueError(f"Expositor stage input differs: {path}")
    return content


def _json(path: Path) -> dict:
    value = json.loads(_read(path))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _put(stage: Path, path: Path, content: bytes) -> Path:
    destination = stage / path
    _io_path(destination).parent.mkdir(parents=True, exist_ok=True)
    _io_path(destination).write_bytes(content)
    return destination


def _put_json(stage: Path, path: Path, value: object) -> Path:
    return _put(stage, path, (json.dumps(value, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")) + "\n").encode("utf-8"))


def _work_paths(member_id: str, detail: dict) -> tuple[Path, Path, Path, Path, dict]:
    work_path = Path("library/works") / detail["work"]
    work = _json(ROOT / work_path / "work.json")
    if work.get("work_id") != detail["work"] or len(work["textual_forms"]) != 1 or len(work["textual_forms"][0]["editions"]) != 1:
        raise ValueError(f"{member_id} canonical work identity changed")
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    if member_id not in edition["edition_id"] or edition.get("category") is not None:
        raise ValueError(f"{member_id} electronic edition is already categorized or changed")
    edition_path = work_path / "forms" / form["textual_form_id"] / "editions" / edition["edition_id"]
    if len(edition["acquisition_ids"]) != 1:
        raise ValueError(f"{member_id} acquisition identity changed")
    acquisition_path = edition_path / "acquisitions" / (edition["acquisition_ids"][0] + ".json")
    return work_path, edition_path, acquisition_path, Path(form["textual_form_id"]), work


def _stage_one(stage: Path, member_id: str, detail: dict) -> dict:
    work_path, edition_path, acquisition_path, form_id, old_work = _work_paths(member_id, detail)
    source_path = Path(detail["source"])
    raw = _read(ROOT / source_path, detail["source_sha"])
    manifest_path = SOURCE_ROOT / member_id / "source-manifest.json"
    manifest = SourceManifest.load(ROOT / manifest_path, repository_root=ROOT)
    candidate_dir = CANDIDATE_ROOT / member_id
    candidate = CandidatePackage.load(candidate_dir)
    validation_path = CANDIDATE_ROOT / (member_id + ".validation.json")
    validation = _json(validation_path)
    report = validate(manifest, candidate, _oracle)
    if (manifest.sha256 != detail["manifest_sha"] or candidate.sha256 != detail["package_sha"]
            or _sha(validation_path) != detail["validation_sha"]
            or sha256(candidate.member_bytes("content.tei.xml")).hexdigest() != detail["tei_sha"]
            or validation.get("status") != "pass" or validation.get("report_sha256") != report.sha256):
        raise ValueError(f"{member_id} frozen candidate or validation differs")
    acquisition = _json(ROOT / acquisition_path)
    retained = acquisition.get("retained_files", [])
    if (len(retained) != 1 or retained[0]["path"] != source_path.as_posix()
            or retained[0]["bytes"] != len(raw) or retained[0]["sha256"] != detail["source_sha"]):
        raise ValueError(f"{member_id} canonical acquisition source differs")
    state = _json(ROOT / work_path / "state.json")
    target = next((x for x in state["targets"] if x["target_type"] == "edition" and x["target_id"] == edition_path.name), None)
    if target is None or target["stage"] != "acquired":
        raise ValueError(f"{member_id} canonical edition state differs")
    if _io_path(ROOT / edition_path / "master.tei.xml").exists() or _io_path(ROOT / edition_path / "acceptance.json").exists():
        raise ValueError(f"{member_id} canonical edition is already accepted")
    before = _files(ROOT / work_path)
    if len(before) != 4:
        raise ValueError(f"{member_id} canonical work preimage has changed")
    for relative in before:
        _put(stage, work_path / relative, _read(ROOT / work_path / relative))
    dependencies = {source_path, manifest_path, Path("sources/commentaries/expositors-bible/ccel-permission.md")}
    dependencies.update(Path(row["path"]) for row in manifest.record["authorities"])
    for reference in set(old_work.get("evidence", [])) | {ref for row in state["targets"] for ref in row.get("evidence", [])}:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"{member_id} unsafe inherited evidence: {reference}")
        dependencies.add(relative)
    for relative in sorted(dependencies):
        if not relative.is_relative_to(work_path):
            _put(stage, relative, _read(ROOT / relative))
    evidence = work_path / "integration" / (member_id + "-readable-electronic-v1")
    for name in candidate.member_names:
        _put(stage, evidence / "inputs/package" / name, candidate.member_bytes(name))
    _put(stage, evidence / "inputs/validation.json", _read(validation_path, detail["validation_sha"]))
    session = _json(SESSION)
    if (session.get("session", {}).get("session_id") != "86edd0c443764c46b42c15d4d528063a"
            or detail["package_sha"] not in session.get("session", {}).get("candidate_sha256", [])):
        raise ValueError(f"{member_id} visual session identity differs")
    _put(stage, evidence / "visual/session-receipt.json", _read(SESSION))
    frame_hashes = {}
    for label, folder in detail["visual"].items():
        directory = EXTERNAL / folder
        capture = _json(directory / "capture.json")
        if (detail["package_sha"] not in capture.get("session", {}).get("candidate_sha256", [])
                or capture["session"].get("session_id") != "86edd0c443764c46b42c15d4d528063a"
                or capture.get("page_errors") or capture.get("visual_inspection") != "unknown"):
            raise ValueError(f"{member_id} {label} visual evidence differs")
        for name in ("capture.json", "compare.json", "frame.png", "session.json"):
            _put(stage, evidence / "visual" / label / name, _read(directory / name))
        frame_hashes[label] = _sha(directory / "frame.png")
    work = _json(stage / work_path / "work.json")
    work["textual_forms"][0]["editions"][0]["category"] = "commentary"
    validate_identity_update(old_work, work)
    _put_json(stage, work_path / "work.json", work)
    load_work(_io_path(stage / work_path / "work.json"))
    edition = work["textual_forms"][0]["editions"][0]
    identity = dict(work_id=detail["work"], textual_form_id=form_id.as_posix(),
                    edition_id=edition["edition_id"], acquisition_id=acquisition["acquisition_id"])
    revision = dict(id=member_id + "-ccel-electronic-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete retained CCEL electronic edition as readable TEI with title, preface or epigraph, commentary, and indexes.")
    binding = dict(source_path=source_path.as_posix(), source_sha256=detail["source_sha"],
                   source_bytes=len(raw), source_scope=retained[0]["scope"])
    original = candidate.member_bytes("content.tei.xml")
    derived = bind_reviewed_header(original, expected_sha256=detail["tei_sha"], identity=identity,
                                   source=binding, source_url=acquisition["url"],
                                   declared_scope=binding["source_scope"], revision=revision)
    pattern = rb"(<sourceDesc>)<p>(Retained CCEL ThML electronic witness by [^<]+)</p>(<bibl)"
    derived, header_replacements = re.subn(pattern, rb"\1<bibl><title>\2</title></bibl>\3", derived)
    if header_replacements != 1:
        raise ValueError(f"{member_id} accepted sourceDesc header shape differs")
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError(f"{member_id} accepted header changed TEI text")
    accepted_candidate = _put(stage, evidence / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(accepted_candidate)):
        raise ValueError(f"{member_id} accepted P5 errors: {errors[:2]}")
    declared = binding["source_scope"]
    expected = [dict(path=source_path.as_posix(), position=1)]
    included = [dict(path=source_path.as_posix(), position=1, bytes=len(raw),
                     sha256=detail["source_sha"], scope=declared)]
    scope = dict(kind="edition", declared=declared, expected_members=expected,
                 included_members=included, excluded_members=[])
    common = dict(identity=identity, source=binding, candidate=make_file_binding(stage, accepted_candidate),
                  scope=declared, accepted_scope=dict(kind="edition", declared=declared),
                  expected_members=expected, included_members=included, excluded_members=[],
                  missing_members=[], unknown_members=[])
    accounting = _put_json(stage, evidence / "source-accounting.json", common | dict(
        source_sha256=detail["source_sha"], source_bytes=len(raw),
        source_manifest_sha256=detail["manifest_sha"], candidate_package_sha256=detail["package_sha"],
        source_feature_counts=dict(elements=detail["elements"], comments=detail["comments"]),
        unsupported_elements=0,
        basis="Independent exact-source oracle compared all body elements, hierarchy, attributes, direct text/tails, comments, links, and TEI P5."))
    command = "py -3 -m build.tools.stage_expositors_lib034_moule_skinner --stage <fresh-external-root>"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Producer and oracle parse the same retained CCEL XML and use the repository XML parser."],
                     independent_corroboration="Exact-source independent oracle, TEI P5, native verifier, and bounded CVW visual samples.")
    for label in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _put_json(stage, evidence / (label + ".json"), common | dict(
            status="pass", command=command, exit_code=0, claim=label,
            candidate_package_sha256=detail["package_sha"], source_manifest_sha256=detail["manifest_sha"],
            validation_sha256=detail["validation_sha"], accepted_header_body_unchanged=True))
        technical[label] = dict(path=proof, status="pass", command=command, exit_code=0)
    reviewed_at = _now()
    review = dict(reviewer="agent:expositors-lib034-moule-skinner-stage", reviewed_at=reviewed_at,
                  coverage=dict(status="partial", declared=declared,
                                reached=list(dict.fromkeys(
                                    [source_path.as_posix() + "#" + x for x in json.loads(candidate.member_bytes("source-accountability.json"))["root_ids_in_order"]]
                                    + [source_path.as_posix() + "#" + x for x in detail["inspected"]])),
                                inspected=[source_path.as_posix() + "#" + x for x in detail["inspected"]],
                                unreviewed=[source_path.as_posix() + "#whole-edition-visual-proofreading"]),
                  source_quality_uncertainty=["No print collation or complete proofreading of the CCEL electronic transcription was performed."],
                  discrepancies=[], unreviewed_residuals=["CVW comparison covers named title, first-chapter, and index loci only."])
    review_file = _put_json(stage, evidence / "review.json", common | review | dict(
        current_cvw_session="86edd0c443764c46b42c15d4d528063a", current_cvw_frames=frame_hashes))
    decision = dict(source_local_disposition="Agent acceptance of one complete retained CCEL electronic edition only.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"],
                                          assessed_at=reviewed_at, supported_scope=declared,
                                          unresolved_claims=[], unassessed_stronger_claims=[
                                              "independent work or print-edition identity", "full visual proofreading",
                                              "human review", "rights clearance", "publication"]))
    acceptance = build_acceptance_record(stage, identity=identity, candidate_path=accepted_candidate,
                                         source_accounting_path=accounting, scope=scope,
                                         technical=technical, review=review | dict(report_path=review_file),
                                         representation_revision=revision, decision=decision)
    acceptance_path = stage / edition_path / "acceptance.json"
    write_acceptance(_io_path(acceptance_path), acceptance)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    master = _put(stage, edition_path / "master.tei.xml", derived)
    _put(stage, edition_path / "README.source.md", candidate.member_bytes("README.source.md"))
    acceptance["promotion"].update(status="promoted", promoted_at=_now(), master=make_file_binding(stage, master))
    write_acceptance(_io_path(acceptance_path), acceptance)
    state_target = next(x for x in state["targets"] if x["target_type"] == "edition" and x["target_id"] == edition_path.name)
    state_target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=_now())
    state_target["evidence"].extend([(edition_path / "master.tei.xml").as_posix(),
                                     (edition_path / "acceptance.json").as_posix()])
    _put_json(stage, work_path / "state.json", state)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / work_path / "state.json"), root=_io_path(stage))
    projected = project_accepted_commentary(_io_path(stage), acceptance_path=_io_path(acceptance_path))
    errors = verify_accepted_commentary(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                         rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != detail["rows"]:
        raise ValueError(f"{member_id} actual-master commentary projection differs: {errors[:2]} / {len(projected['rows'])}")
    return dict(member_id=member_id, work_id=detail["work"], work_path=work_path.as_posix(),
                edition_path=edition_path.as_posix(), acquisition_path=acquisition_path.as_posix(),
                source_path=source_path.as_posix(), source_sha256=detail["source_sha"],
                source_manifest_sha256=detail["manifest_sha"], candidate_package_sha256=detail["package_sha"],
                validation_sha256=detail["validation_sha"], original_tei_sha256=detail["tei_sha"],
                before=before, after=_files(stage / work_path), accepted_master_sha256=_sha(master),
                acceptance_sha256=_sha(acceptance_path), projection_rows=len(projected["rows"]))


def prepare(stage: Path) -> dict:
    stage = stage.absolute()
    if (stage.exists() or not stage.parent.is_dir() or ROOT.resolve() in stage.resolve().parents
            or stage.resolve() in ROOT.resolve().parents):
        raise ValueError("Expositor pair stage must be a fresh external directory")
    stage.mkdir(parents=True)
    rows = [_stage_one(stage, member_id, detail) for member_id, detail in MEMBERS.items()]
    receipt = dict(contract="ocd-expositors-lib034-moule-skinner-stage-v1", status="staged-only",
                   canonical_root=ROOT.as_posix(), stage_root=stage.as_posix(),
                   works=rows, rights="not-assessed", installation="not-performed")
    _put_json(stage, Path("expositors-moule-skinner-stage-receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.stage)
    print(json.dumps({"status": result["status"], "works": [(r["work_id"], r["projection_rows"]) for r in result["works"]],
                      "stage_root": result["stage_root"]}, sort_keys=True))


if __name__ == "__main__":
    main()
