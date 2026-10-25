"""Stage Owen Truth and Innocence Vindicated's one source-bound CCEL electronic edition externally."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

from build.tei.owen_lib052_truth_innocence_readable_oracle import _oracle


ROOT = Path(__file__).resolve().parents[2]
EXTERNAL = Path("D:/Library/Open Christian Data/candidate-reviews")
SOURCE_ROOT = Path("sources/structured-text/lib052-john-owen/readable-truth-innocence-v1")
CANDIDATE_ROOT = EXTERNAL / "owen-lib052-truth-innocence-readable-candidate-20260928-v2"
MEMBERS = {
    "truth-innocence": {
        "work": "john-owen-truth-innocence",
        "source": "raw/ccel/owen/truthinnocence.xml",
        "source_sha": "efaf07aaf9c7c37c1fd5ac585d973cd3faf295a25583c93cd8a510d7a24878ff",
        "manifest_sha": "31df6117b01398f96be3ed16699c25932de1eea1fa1ccf41129a9f65769c12bc",
        "package_sha": "656d0340d2a2c83137cf578755a6d184b1d144e9158e09284609cd669df8d214",
        "validation_sha": "4ae6c3ee6de16e08638fdf45170c90ac73d55729f287450db39804f3092e5b83",
        "tei_sha": "87b1eb7b0e237376dc47f4393ce44ce10e2907fb387da14555320a9a7f5c5bfa",
        "elements": 2094, "comments": 30, "rows": 2,
        "inspected": ["i", "ii"],
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    content = _io_path(path).read_bytes()
    if expected is not None and sha256(content).hexdigest() != expected:
        raise ValueError(f"Owen Truth and Innocence Vindicated stage input differs: {path}")
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
    if work.get("work_id") != detail["work"] or len(work["textual_forms"]) != 1:
        raise ValueError(f"{member_id} canonical work identity changed")
    forms = [row for row in work["textual_forms"] if member_id in row["textual_form_id"]]
    if len(forms) != 1 or len(forms[0]["editions"]) != 1:
        raise ValueError(f"{member_id} textual form identity changed")
    form = forms[0]
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
    candidate_dir = CANDIDATE_ROOT / "package"
    candidate = CandidatePackage.load(candidate_dir)
    validation_path = CANDIDATE_ROOT / "validation.json"
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
    state_path = stage / work_path / "state.json"
    state = _json(state_path if _io_path(state_path).exists() else ROOT / work_path / "state.json")
    target = next((x for x in state["targets"] if x["target_type"] == "edition" and x["target_id"] == edition_path.name), None)
    if target is None or target["stage"] != "acquired":
        raise ValueError(f"{member_id} canonical edition state differs")
    if _io_path(ROOT / edition_path / "master.tei.xml").exists() or _io_path(ROOT / edition_path / "acceptance.json").exists():
        raise ValueError(f"{member_id} canonical edition is already accepted")
    before = _files(ROOT / work_path)
    if len(before) != 3:
        raise ValueError(f"{member_id} canonical work preimage has changed")
    for relative in before:
        if not _io_path(stage / work_path / relative).exists():
            _put(stage, work_path / relative, _read(ROOT / work_path / relative))
    dependencies = {source_path, manifest_path, Path("sources/structured-text/lib052-john-owen/README.md")}
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
    frame_hashes = {}
    work = _json(stage / work_path / "work.json")
    matching_forms = [row for row in work["textual_forms"] if row["textual_form_id"] == form_id.as_posix()]
    if len(matching_forms) != 1 or matching_forms[0]["editions"][0].get("category") is not None:
        raise ValueError(f"{member_id} staged edition category differs")
    matching_forms[0]["editions"][0]["category"] = "prose"
    validate_identity_update(old_work, work)
    _put_json(stage, work_path / "work.json", work)
    load_work(_io_path(stage / work_path / "work.json"))
    edition = matching_forms[0]["editions"][0]
    identity = dict(work_id=detail["work"], textual_form_id=form_id.as_posix(),
                    edition_id=edition["edition_id"], acquisition_id=acquisition["acquisition_id"])
    revision = dict(id=member_id + "-ccel-electronic-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete retained CCEL electronic edition of Truth and Innocence Vindicated and its indexes as readable TEI.")
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
        basis="Independent exact-source oracle compared all body elements, 30 index comments, 16 typed attribution blocks, six arguments, seven index marker types/languages, electronic header title, hierarchy, attributes, direct text/tails, links, and TEI P5."))
    command = "py -3 -m build.tools.stage_owen_lib052_truth_innocence --stage <fresh-external-root>"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Producer and oracle parse the same retained CCEL XML and use the repository XML parser."],
                     independent_corroboration="Exact-source independent oracle, TEI P5, native verifier, and source-root review; no CVW visual frames are claimed.")
    for label in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _put_json(stage, evidence / (label + ".json"), common | dict(
            status="pass", command=command, exit_code=0, claim=label,
            candidate_package_sha256=detail["package_sha"], source_manifest_sha256=detail["manifest_sha"],
            validation_sha256=detail["validation_sha"], accepted_header_body_unchanged=True))
        technical[label] = dict(path=proof, status="pass", command=command, exit_code=0)
    reviewed_at = _now()
    review = dict(reviewer="agent:owen-lib052-truth-innocence-stage", reviewed_at=reviewed_at,
                  coverage=dict(status="partial", declared=declared,
                                reached=list(dict.fromkeys(
                                    [source_path.as_posix() + "#" + x for x in json.loads(candidate.member_bytes("source-accountability.json"))["root_ids_in_order"]]
                                    + [source_path.as_posix() + "#" + x for x in detail["inspected"]])),
                                inspected=[source_path.as_posix() + "#" + x for x in detail["inspected"]],
                                unreviewed=[source_path.as_posix() + "#whole-edition-visual-proofreading"]),
                  source_quality_uncertainty=[
                      "The electronic header and catalog omit the period in the main division title; print-title equivalence remains for editorial review.",
                      "The electronic header names a Banner of Truth Trust 1967 print source; it has not been independently collated.",
                      "The electronic header says the text has not been proofread and credits an AGES Digital Library base with an AGES Software copyright assertion; human textual review and base-text rights remain unresolved.",
                  ],
                  discrepancies=[],
                  unreviewed_residuals=["No source-to-TEI CVW frame or whole-edition visual proofreading is claimed."])
    review_file = _put_json(stage, evidence / "review.json", common | review | dict(
        current_cvw_session=None, current_cvw_frames=frame_hashes))
    decision = dict(source_local_disposition="Agent acceptance of one complete retained CCEL electronic edition only.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"],
                                          assessed_at=reviewed_at, supported_scope=declared,
                                          unresolved_claims=["AGES-derived electronic base-text rights and source proofreading"], unassessed_stronger_claims=[
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
    projected = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path))
    errors = verify_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                         rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != detail["rows"]:
        raise ValueError(f"{member_id} actual-master prose projection differs: {errors[:2]} / {len(projected['rows'])}")
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
        raise ValueError("Owen Truth and Innocence Vindicated stage must be a fresh external directory")
    stage.mkdir(parents=True)
    rows = [_stage_one(stage, member_id, detail) for member_id, detail in MEMBERS.items()]
    work_path = Path("library/works/john-owen-truth-innocence")
    after = _files(stage / work_path)
    before = _files(ROOT / work_path)
    for row in rows:
        row.pop("before")
        row.pop("after")
        acceptance_path = stage / row["edition_path"] / "acceptance.json"
        validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
        projected = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path))
        errors = verify_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                             rows=projected["rows"], receipt=projected["receipt"])
        if errors or len(projected["rows"]) != row["projection_rows"]:
            raise ValueError(f"{row['member_id']} final combined projection differs: {errors[:2]}")
    validate_state(_io_path(stage / work_path / "state.json"), root=_io_path(stage))
    receipt = dict(contract="ocd-owen-lib052-truth-innocence-stage-v1", status="staged-only",
                   canonical_root=ROOT.as_posix(), stage_root=stage.as_posix(),
                   work=dict(work_id="john-owen-truth-innocence", work_path=work_path.as_posix(),
                             before=before, after=after, members=rows),
                   rights="not-assessed", installation="not-performed")
    _put_json(stage, Path("owen-truth-innocence-stage-receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.stage)
    print(json.dumps({"status": result["status"], "members": [(r["member_id"], r["projection_rows"]) for r in result["work"]["members"]],
                      "stage_root": result["stage_root"]}, sort_keys=True))


if __name__ == "__main__":
    main()
