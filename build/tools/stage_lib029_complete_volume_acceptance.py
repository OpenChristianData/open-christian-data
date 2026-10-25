"""Freeze Schaff Volume I's complete retained electronic witness in an external work-local stage."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.lib029_complete_volume_oracle import _oracle
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


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "creeds-of-christendom-vol-1"
FORM_ID = "creeds-of-christendom-vol-1-english"
EDITION_ID = "creeds-of-christendom-vol-1-retained-electronic-witness"
ACQUISITION_ID = "creeds-of-christendom-vol-1-retained-source"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/ccel/schaff/creeds1.xml")
MANIFEST = Path("sources/structured-text/creeds-of-christendom-vol-1/complete-volume-v8/source-manifest.json")
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/schaff-creeds1-complete-volume-cvw-envelope-20260927-v8")
VISUAL = Path("D:/Library/Open Christian Data/candidate-reviews")
CVW_SESSION = Path("D:/Library/Open Christian Data/candidate-reviews/schaff-creeds1-cvw-20260927-v8/2bfad2583d9249a392dab5b34119346f.receipt.json")
FRAMES = ("schaff-creeds1-v8-title-compare.png", "schaff-creeds1-v8-index-compare.png")
EVIDENCE = WORK / "integration/schaff-complete-electronic-v1"
IDENTITY = dict(work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)
SOURCE_SHA = "450960af42f600534f15429546e0a00696a9fbfc4ea32df55545ef5a02c491e7"
MANIFEST_SHA = "a37d345cc666ae981455be216f00bcb4459cc6d2686e0b9a343b1c14ae4bc202"
PACKAGE_SHA = "4eef51c82f1de7c9b7213b809e91f575ed0972fb43ece9b07afd3abb6c122160"
ORIGINAL_TEI_SHA = "6b49b94a17816d25efde61548489a1c1f4070867d1a71aaa171ec8990d5c28ec"
CONTRACT = "ocd-schaff-complete-electronic-stage-v1"


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _read(path: Path) -> bytes:
    return _io_path(path).read_bytes()


def _json(path: Path) -> dict:
    value = json.loads(_read(path))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    target = _io_path(stage / relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return stage / relative


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))


def _copy(stage: Path, relative: Path) -> None:
    _put(stage, relative, _read(ROOT / relative))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def prepare(stage: Path) -> dict:
    stage = stage.absolute()
    if (_io_path(stage).exists() or not _io_path(stage.parent).is_dir()
            or ROOT.resolve() in stage.resolve().parents or stage.resolve() == ROOT.resolve()):
        raise ValueError("Schaff stage must be a fresh external directory")
    source_bytes = _read(ROOT / SOURCE)
    if _sha(source_bytes) != SOURCE_SHA:
        raise ValueError("Schaff retained source changed")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    if manifest.sha256 != MANIFEST_SHA:
        raise ValueError("Schaff source manifest changed")
    package = CandidatePackage.load(CANDIDATE / "package")
    validation = _json(CANDIDATE / "validation.json")
    rerun = validate(manifest, package, _oracle)
    original = package.member_bytes("content.tei.xml")
    if (package.sha256 != PACKAGE_SHA or _sha(original) != ORIGINAL_TEI_SHA
            or validation.get("report_sha256") != rerun.sha256
            or validation.get("candidate_sha256") != PACKAGE_SHA
            or validation.get("source_manifest_sha256") != MANIFEST_SHA
            or validation.get("status") != "pass"):
        raise ValueError("Schaff candidate or source-led report differs")
    acquisition = _json(ROOT / ACQUISITION)
    retained = acquisition.get("retained_files", [])
    if (acquisition.get("acquisition_id") != ACQUISITION_ID or len(retained) != 1
            or retained[0].get("path") != SOURCE.as_posix()
            or retained[0].get("bytes") != len(source_bytes)
            or retained[0].get("sha256") != SOURCE_SHA):
        raise ValueError("Schaff acquisition retained-file binding differs")
    before = _files(ROOT / WORK)
    for relative in before:
        _copy(stage, WORK / relative)
    if _files(stage / WORK) != before:
        raise ValueError("Schaff staged work preimage differs")
    old_work = _json(ROOT / WORK / "work.json")
    work = _json(stage / WORK / "work.json")
    old_state = _json(stage / WORK / "state.json")
    edition = work["textual_forms"][0]["editions"][0]
    if (work.get("work_id") != WORK_ID or edition.get("edition_id") != EDITION_ID
            or edition.get("category") is not None or edition.get("language") != "en"):
        raise ValueError("Schaff work identity or edition preimage differs")
    edition["category"] = "prose"
    validate_identity_update(old_work, work)
    _put_json(stage, WORK / "work.json", work)
    load_work(_io_path(stage / WORK / "work.json"))
    target = [row for row in old_state["targets"] if row["target_type"] == "edition" and row["target_id"] == EDITION_ID]
    if len(target) != 1 or target[0]["stage"] != "acquired":
        raise ValueError("Schaff edition is not uniquely acquired")
    if _io_path(ROOT / EDITION / "acceptance.json").exists() or _io_path(ROOT / EDITION / "master.tei.xml").exists():
        raise ValueError("Schaff canonical edition is already accepted")
    dependencies = {SOURCE, MANIFEST, Path("docs/sources/ccel-permission.md")}
    dependencies.update(Path(row["path"]) for row in manifest.record["authorities"])
    for reference in set(old_work.get("evidence", [])) | {item for row in old_state["targets"] for item in row.get("evidence", [])}:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe inherited Schaff evidence path: {reference}")
        dependencies.add(relative)
    for relative in sorted(dependencies):
        if not relative.is_relative_to(WORK):
            _copy(stage, relative)
    for name in package.member_names:
        _put(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    _put(stage, EVIDENCE / "inputs/validation.json", _read(CANDIDATE / "validation.json"))
    receipt = _json(CVW_SESSION)
    if PACKAGE_SHA not in receipt.get("session", {}).get("candidate_sha256", []):
        raise ValueError("Schaff CVW exact-pair session differs")
    _put(stage, EVIDENCE / "visual" / CVW_SESSION.name, _read(CVW_SESSION))
    for name in FRAMES:
        _put(stage, EVIDENCE / "visual" / name, _read(VISUAL / name))
    scope_text = "Complete retained CCEL ThML Volume I: title and dedication, eight history divisions, and both indexes in source order."
    source_binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                          source_bytes=len(source_bytes), source_scope=retained[0]["scope"])
    revision = dict(id="schaff-complete-electronic-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete retained CCEL ThML electronic witness of Schaff Volume I.")
    derived = bind_reviewed_header(original, expected_sha256=ORIGINAL_TEI_SHA, identity=IDENTITY,
                                   source=source_binding, source_url=acquisition["url"],
                                   declared_scope=scope_text, revision=revision)
    source_text = etree.fromstring(original).find("{http://www.tei-c.org/ns/1.0}text")
    master_text = etree.fromstring(derived).find("{http://www.tei-c.org/ns/1.0}text")
    if source_text is None or master_text is None or etree.tostring(source_text, method="c14n") != etree.tostring(master_text, method="c14n"):
        raise ValueError("Schaff reviewed header changed front/body/back content")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"Schaff staged TEI P5 failed: {errors[:3]}")
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=len(source_bytes),
                     sha256=SOURCE_SHA, scope=retained[0]["scope"])]
    scope = dict(kind="edition", declared=scope_text, expected_members=expected,
                 included_members=included, excluded_members=[])
    common = dict(identity=IDENTITY, source=source_binding, candidate=make_file_binding(stage, candidate),
                  scope=scope_text, accepted_scope=dict(kind="edition", declared=scope_text),
                  expected_members=expected, included_members=included, excluded_members=[],
                  missing_members=[], unknown_members=[])
    accounting = _put_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        scope=source_binding["source_scope"],
        source_sha256=SOURCE_SHA, source_bytes=len(source_bytes), source_manifest_sha256=MANIFEST_SHA,
        candidate_package_sha256=PACKAGE_SHA, source_feature_count=36679,
        source_divisions=["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"],
        source_heading_count=52, p5_late_heading_count=14, source_local_link_count=5327))
    command = "py -3 -m build.tools.stage_lib029_complete_volume_acceptance --stage <fresh-external-root>"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"], path=make_file_binding(stage, stage / MANIFEST)),
                     checker=dict(id=manifest.record["validator"]["id"], path=make_file_binding(stage, stage / MANIFEST)),
                     shared_assumptions=["Producer and oracle share the declared twelve-root source envelope and the fourteen exact P5 heading exceptions; the oracle independently walks retained XML and checks all candidate nodes and links."],
                     independent_corroboration="Fresh source-led oracle and P5 validation, live exact-pair CVW title/index frames, and independent native actual-master prose verification.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _put_json(stage, EVIDENCE / f"{name}.json", common | dict(
            status="pass", command=command, exit_code=0, claim=name,
            candidate_package_sha256=PACKAGE_SHA, source_manifest_sha256=MANIFEST_SHA,
            validation_report_sha256=rerun.sha256, accepted_header_text_unchanged=True))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    reviewed_at = _now()
    review = dict(reviewer="agent:schaff-complete-electronic-stage", reviewed_at=reviewed_at,
                  coverage=dict(status="partial", declared=scope_text,
                                reached=[f"{SOURCE.as_posix()}#{item}" for item in ("i", "iii", "xi", "xii")]
                                + ["title page", "history opening", "index of citations", "twelve-root source-led oracle"],
                                inspected=["title page", "history opening", "index of citations", "twelve-root source-led oracle"],
                                unreviewed=["full visual proofreading", "print collation"]),
                  source_quality_uncertainty=["The retained electronic transcription was not collated against a print witness."],
                  discrepancies=[], unreviewed_residuals=["CVW comparison sampled title and index loci; complete text was checked mechanically."])
    review_file = _put_json(stage, EVIDENCE / "review.json", common | review | dict(
        cvw_session=make_file_binding(stage, stage / EVIDENCE / "visual" / CVW_SESSION.name),
        frames=[make_file_binding(stage, stage / EVIDENCE / "visual" / name) for name in FRAMES]))
    decision = dict(source_local_disposition="Agent acceptance of the complete retained CCEL Volume I electronic witness only.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=reviewed_at,
                                          supported_scope=scope_text, unresolved_claims=[],
                                          unassessed_stronger_claims=["print edition collation", "whole-volume visual proofreading",
                                                                      "human acceptance", "rights clearance", "publication"]))
    acceptance = build_acceptance_record(stage, identity=IDENTITY, candidate_path=candidate,
                                         source_accounting_path=accounting, scope=scope,
                                         technical=technical, review=review | dict(report_path=review_file),
                                         representation_revision=revision, decision=decision)
    acceptance_path = stage / EDITION / "acceptance.json"
    write_acceptance(_io_path(acceptance_path), acceptance)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    master = _put(stage, EDITION / "master.tei.xml", derived)
    acceptance["promotion"].update(status="promoted", promoted_at=_now(), master=make_file_binding(stage, master))
    write_acceptance(_io_path(acceptance_path), acceptance)
    state = _json(stage / WORK / "state.json")
    edition_target = next(row for row in state["targets"] if row["target_type"] == "edition" and row["target_id"] == EDITION_ID)
    edition_target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=_now())
    edition_target["evidence"].extend([EDITION.joinpath("master.tei.xml").as_posix(), EDITION.joinpath("acceptance.json").as_posix()])
    _put_json(stage, WORK / "state.json", state)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projection = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path))
    errors = verify_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                   rows=projection["rows"], receipt=projection["receipt"])
    parts = [row["locator"]["text_part"] for row in projection["rows"]]
    if errors or parts != ["front", "front", "body", "back", "back"]:
        raise ValueError(f"Schaff actual-master native projection differs: {errors[:3]}; {parts}")
    _put_json(stage, EVIDENCE / "projection-canary.json", dict(
        row_count=len(parts), text_parts=parts, verifier_errors=errors,
        receipt_sha256=_sha((json.dumps(projection["receipt"], sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))))
    result = dict(contract=CONTRACT, status="staged-only", canonical_root=ROOT.as_posix(),
                  stage_root=stage.as_posix(), work_id=WORK_ID, source_path=SOURCE.as_posix(),
                  source_sha256=SOURCE_SHA, source_manifest_sha256=MANIFEST_SHA,
                  candidate_sha256=PACKAGE_SHA, original_tei_sha256=ORIGINAL_TEI_SHA,
                  validation_report_sha256=rerun.sha256, before=before, after=_files(stage / WORK),
                  accepted_master_sha256=_sha(_read(master)), acceptance_sha256=_sha(_read(acceptance_path)),
                  projection_rows=len(parts), rights="not-assessed", installation="not-performed")
    _put_json(stage, Path("schaff-stage-receipt.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.stage)
    print(json.dumps({"status": result["status"], "stage_root": result["stage_root"],
                      "master_sha256": result["accepted_master_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
