"""Stage the complete retained EEBO-TCP A48888 electronic witness outside the library."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.locke_reasonableness_christianity import audit_source
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "locke-reasonableness-christianity"
WORK = Path("library/works") / WORK_ID
FORM_ID = WORK_ID + "-tcp-retained-en"
EDITION_ID = WORK_ID + "-tcp-electronic"
ACQUISITION_ID = WORK_ID + "-tcp-acquired"
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / (ACQUISITION_ID + ".json")
SOURCE = Path("raw/clean-ready-acquisition-to-tei/master-4/28") / WORK_ID / "A48888.xml"
REPORT = Path("reports/clean-ready-acquisition-to-tei/master-4/28") / WORK_ID
CANDIDATE = REPORT / "candidate/package/locke-reasonableness-christianity.tei.xml"
VALIDATION = REPORT / "candidate/validation.json"
VISUAL = REPORT / "visual/visual_spot_check.json"
EVIDENCE = WORK / "integration/locke-a48888-electronic-acceptance-v1"
IDENTITY = dict(work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID,
                acquisition_id=ACQUISITION_ID)
CONTRACT = "ocd-locke-a48888-electronic-stage-v1"
SOURCE_SHA = "918f878639032bdd4c495fe7afff7ae557704383a6f90bd8d6e85c360b9226c0"
VALIDATION_SHA = "e726f9c13db6d54b341a49db6a334321846a07addfab784ef78ad932dc276abe"
VISUAL_SHA = "efc04ffe220de8d9f67076944bd491bd7bfdaf0c828a54fe22f79f5b04b0bdda"
ACCOUNTABILITY_SHA = "10cad2d45bb52c4806ac5c0ce21975a9bad4532b3df84d23f2ecfb7d83ca75db"
DETERMINISM_SHA = "be8832314e503b890efa9cd83a7ccf7808852a1095f697ee24ccd4019e8fc712"
BEFORE = {
    "work.json": "7c5d43049fb1164e96e0334c3b6935593cfff8e62d14417904d4ff0fc5100ae8",
    "state.json": "511119b2cfda2f0045bfb87cd732e3fd117e02556ae463729fa717c906406f8d",
    "SOURCE_CREDIT.md": "eda0c84b66b9e0e237355f4a9a6a744249d1c7d7527898a126a58c4498a8c771",
    (ACQUISITION.relative_to(WORK)).as_posix(): "6909722eb6d2df9c718919bbb12e3ed87adc960f53816fc0cdca3edd7bb23f22",
}


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    value = _io_path(path).read_bytes()
    if expected and sha256(value).hexdigest() != expected:
        raise ValueError(f"Locke A48888 evidence changed: {path}")
    return value


def _json(path: Path) -> dict:
    value = json.loads(_read(path))
    if not isinstance(value, dict):
        raise ValueError(f"Locke A48888 object required: {path}")
    return value


def _put(stage: Path, relative: Path, value: bytes) -> Path:
    target = stage / relative
    _io_path(target).parent.mkdir(parents=True, exist_ok=True)
    _io_path(target).write_bytes(value)
    return target


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    data = (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    return _put(stage, relative, data)


def prepare(stage: Path) -> dict:
    stage = stage.absolute()
    if (_io_path(stage).exists() or not _io_path(stage.parent).is_dir()
            or stage.resolve() == ROOT.resolve() or ROOT.resolve() in stage.resolve().parents
            or stage.resolve() == _io_path(ROOT / CANDIDATE).resolve()
            or _io_path(ROOT / CANDIDATE).resolve() in stage.resolve().parents):
        raise ValueError("Locke A48888 stage must be a fresh external directory")
    original = _read(ROOT / SOURCE, SOURCE_SHA)
    audit = audit_source(_io_path(ROOT / SOURCE), repository_root=ROOT)
    recorded = _json(ROOT / VALIDATION)
    visual = _json(ROOT / VISUAL)
    accountability = _json(ROOT / REPORT / "accountability.json")
    determinism = _json(ROOT / REPORT / "candidate/determinism.json")
    if (_read(ROOT / CANDIDATE, SOURCE_SHA) != original
            or _sha(ROOT / VALIDATION) != VALIDATION_SHA
            or _sha(ROOT / VISUAL) != VISUAL_SHA
            or _sha(ROOT / REPORT / "accountability.json") != ACCOUNTABILITY_SHA
            or _sha(ROOT / REPORT / "candidate/determinism.json") != DETERMINISM_SHA
            or recorded.get("candidate_sha256") != SOURCE_SHA
            or recorded.get("source_sha256") != SOURCE_SHA
            or recorded.get("byte_identity") is not True
            or recorded.get("tag_counts") != audit["tag_counts"]
            or recorded.get("gap_reasons") != audit["gap_reasons"]
            or recorded.get("front_divisions") != audit["front_divisions"]
            or recorded.get("body_divisions") != audit["body_divisions"]
            or recorded.get("back_divisions") != audit["back_divisions"]
            or accountability.get("candidate_sha256") != SOURCE_SHA
            or accountability.get("source_sha256") != SOURCE_SHA
            or visual.get("source_candidate_byte_identity") is not True
            or any(item.get("result") != "pass" or item.get("source_candidate_rendered_match") is not True
                   for item in visual.get("checks", {}).values())
            or len(visual.get("checks", {})) != 11
            or determinism.get("candidate_bytes_equal") is not True
            or determinism.get("validation_bytes_equal") is not True):
        raise ValueError("Locke A48888 current source/candidate/audit binding differs")
    root = etree.fromstring(original, etree.XMLParser(resolve_entities=False, no_network=True))
    names = Counter(etree.QName(node).localname for node in root.iter())
    if (root.tag != "{http://www.tei-c.org/ns/1.0}TEI"
            or names["pb"] != 314 or names["g"] != 1565 or names["gap"] != 36
            or names["front"] != 1 or names["body"] != 1 or names["back"] != 1
            or names["text"] != 1):
        raise ValueError("Locke A48888 complete source envelope differs")
    if _files(ROOT / WORK) != BEFORE:
        raise ValueError("Locke A48888 canonical four-file work preimage differs")
    acquisition = _json(ROOT / ACQUISITION)
    retained = acquisition.get("retained_files", [])
    if (acquisition.get("source_path") != SOURCE.as_posix()
            or acquisition.get("source_bytes") != len(original)
            or acquisition.get("source_sha256") != SOURCE_SHA
            or len(retained) != 1 or retained[0].get("sha256") != SOURCE_SHA
            or retained[0].get("path") != SOURCE.as_posix()
            or acquisition.get("source_scope") != retained[0].get("scope")):
        raise ValueError("Locke A48888 current acquisition source binding differs")
    old_work = _json(ROOT / WORK / "work.json")
    old_state = _json(ROOT / WORK / "state.json")
    if (_io_path(ROOT / EDITION / "acceptance.json").exists()
            or _io_path(ROOT / EDITION / "master.tei.xml").exists()
            or old_work["textual_forms"][0]["editions"][0]["edition_id"] != EDITION_ID):
        raise ValueError("Locke A48888 edition preimage differs")
    targets = [t for t in old_state["targets"] if t["target_type"] == "edition" and t["target_id"] == EDITION_ID]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise ValueError("Locke A48888 edition is not uniquely acquired")
    for name in visual["screenshots"]:
        if not isinstance(name, str) or "/" in name or ".." in name or not name.endswith(".png"):
            raise ValueError("Locke A48888 visual screenshot path differs")
        _read(ROOT / REPORT / "visual" / name)
    for relative, checksum in BEFORE.items():
        _put(stage, WORK / relative, _read(ROOT / WORK / relative, checksum))
    dependencies = {SOURCE, CANDIDATE, VALIDATION, VISUAL,
                    REPORT / "accountability.json", REPORT / "candidate/determinism.json",
                    REPORT / "visual/visual_spot_check.md",
                    Path("sources/structured-text") / WORK_ID / "config.json",
                    Path("sources/structured-text") / WORK_ID / "README.md",
                    Path("raw/clean-ready-acquisition-to-tei/master-4/28") / WORK_ID / "tcpchars.xml",
                    Path("raw/clean-ready-acquisition-to-tei/master-4/28") / WORK_ID / "Texts-LICENSE",
                    Path("build/tei/locke_reasonableness_christianity.py")}
    dependencies.update(REPORT / "visual" / name for name in visual["screenshots"])
    for reference in set(old_work.get("evidence", [])) | {
        item for target in old_state["targets"] for item in target.get("evidence", [])
    }:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe inherited Locke A48888 evidence path: {reference}")
        dependencies.add(relative)
    for relative in sorted(dependencies):
        if not relative.is_relative_to(WORK):
            _put(stage, relative, _read(ROOT / relative))
    _put(stage, EVIDENCE / "inputs/source-candidate.tei.xml", original)
    _put(stage, EVIDENCE / "inputs/validation.json", _read(ROOT / VALIDATION, VALIDATION_SHA))
    _put(stage, EVIDENCE / "inputs/source-accountability.json", _read(ROOT / REPORT / "accountability.json", ACCOUNTABILITY_SHA))
    _put(stage, EVIDENCE / "inputs/visual-spot-check.json", _read(ROOT / VISUAL, VISUAL_SHA))
    work = _json(stage / WORK / "work.json")
    edition = work["textual_forms"][0]["editions"][0]
    if edition.get("category") is not None:
        raise ValueError("Locke A48888 edition category preimage differs")
    edition["category"] = "prose"
    validate_identity_update(old_work, work)
    _put_json(stage, WORK / "work.json", work)
    load_work(_io_path(stage / WORK / "work.json"))
    revision = dict(id="locke-a48888-electronic-agent-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Bind the complete retained TCP TEI electronic witness; original source body unchanged.")
    source_binding = dict(source_path=SOURCE.as_posix(), source_bytes=len(original),
                          source_sha256=SOURCE_SHA, source_scope=acquisition["source_scope"])
    derived = bind_reviewed_header(original, expected_sha256=SOURCE_SHA, identity=IDENTITY,
                                   source=source_binding, source_url=acquisition["url"],
                                   declared_scope=acquisition["source_scope"], revision=revision)
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Locke A48888 accepted header changed the source text")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"Locke A48888 accepted TEI P5 errors: {errors[:3]}")
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=len(original),
                     sha256=SOURCE_SHA, scope=acquisition["source_scope"])]
    scope = dict(kind="edition", declared=acquisition["source_scope"], expected_members=expected,
                 included_members=included, excluded_members=[])
    common = dict(identity=IDENTITY, source=source_binding, candidate=make_file_binding(stage, candidate),
                  scope=acquisition["source_scope"], accepted_scope=dict(kind="edition", declared=acquisition["source_scope"]),
                  expected_members=expected, included_members=included, excluded_members=[],
                  missing_members=[], unknown_members=[])
    accounting = _put_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        source_sha256=SOURCE_SHA, source_bytes=len(original), original_candidate_sha256=SOURCE_SHA,
        source_element_counts=dict(sorted(names.items())),
        basis="The complete retained XML and reviewed candidate are byte-identical; source audit, vendored TEI P5 validation, and eleven-locus rendered comparison pass."))
    command = "py -3 -m build.tools.stage_locke_a48888_acceptance --stage <fresh-external-root>"
    technical = dict(producer=dict(id="build.tei.locke_reasonableness_christianity.build_candidate"),
                     checker=dict(id="build.tei.locke_reasonableness_christianity.audit_source"),
                     shared_assumptions=["Candidate builder and source audit share code; exact retained-source/candidate byte equality separately establishes source conservation."],
                     independent_corroboration="Exact source/candidate byte equality, TEI P5, source element and region census, eleven-locus source/candidate rendered comparison, actual-master native prose projection, and independent native row checker.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = _put_json(stage, EVIDENCE / (name + ".json"), common | dict(
            status="pass", command=command, exit_code=0, claim=name,
            original_candidate_sha256=SOURCE_SHA,
            validation_sha256=VALIDATION_SHA, visual_report_sha256=VISUAL_SHA,
            accountability_sha256=ACCOUNTABILITY_SHA, determinism_sha256=DETERMINISM_SHA,
            original_source_bytes_unchanged=True))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    review = dict(reviewer="agent:locke-a48888-electronic-stage", reviewed_at=now,
                  coverage=dict(status="partial", declared=acquisition["source_scope"],
                                reached=[f"{SOURCE.as_posix()}#full-byte-source",
                                         f"{SOURCE.as_posix()}#eleven-locus-rendered-source-candidate-pair"],
                                inspected=[f"{SOURCE.as_posix()}#full-byte-source",
                                           f"{SOURCE.as_posix()}#eleven-locus-rendered-source-candidate-pair"],
                                unreviewed=[f"{SOURCE.as_posix()}#complete-new-CVW-visual-proofreading"]),
                  source_quality_uncertainty=["TCP Phase I keyboarded and encoded text was not collated with page images."],
                  discrepancies=[], unreviewed_residuals=[
                      "The retained eleven-locus rendered pair compares exact source and candidate bytes; it is bounded electronic-witness evidence, not full page-image collation or proofreading.",
                      "Human textual and rights decisions are not recorded."])
    review_file = _put_json(stage, EVIDENCE / "review.json", common | review | dict(
        visual_report_sha256=VISUAL_SHA,
        original_candidate_source_and_tei_sha256=SOURCE_SHA))
    decision = dict(source_local_disposition="Agent acceptance of the exact complete TCP A48888 electronic witness only.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=now,
                                          supported_scope=acquisition["source_scope"], unresolved_claims=[],
                                          unassessed_stronger_claims=["page-image collation", "full visual proofreading",
                                                                     "human review", "rights clearance", "publication"]))
    acceptance = build_acceptance_record(stage, identity=IDENTITY, candidate_path=candidate,
                                         source_accounting_path=accounting, scope=scope,
                                         technical=technical, review=review | dict(report_path=review_file),
                                         representation_revision=revision, decision=decision)
    acceptance_path = stage / EDITION / "acceptance.json"
    write_acceptance(_io_path(acceptance_path), acceptance)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    master_path = _put(stage, EDITION / "master.tei.xml", derived)
    acceptance["promotion"].update(status="promoted", promoted_at=now,
                                   master=make_file_binding(stage, master_path))
    write_acceptance(_io_path(acceptance_path), acceptance)
    state = _json(stage / WORK / "state.json")
    target = next(t for t in state["targets"] if t["target_type"] == "edition" and t["target_id"] == EDITION_ID)
    target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    target["evidence"].extend([(EDITION / "master.tei.xml").as_posix(),
                               (EDITION / "acceptance.json").as_posix()])
    _put_json(stage, WORK / "state.json", state)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projected = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path))
    errors = verify_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                     rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 5:
        raise ValueError(f"Locke A48888 actual-master prose projection failed: {errors[:3]}")
    receipt = dict(contract=CONTRACT, status="staged-only", canonical_root=ROOT.as_posix(),
                   stage_root=stage.as_posix(), work_id=WORK_ID, source_path=SOURCE.as_posix(),
                   source_sha256=SOURCE_SHA, original_candidate_sha256=SOURCE_SHA,
                   current_validation_sha256=VALIDATION_SHA, visual_report_sha256=VISUAL_SHA,
                   source_accountability_sha256=ACCOUNTABILITY_SHA,
                   before=BEFORE, after=_files(stage / WORK), accepted_master_sha256=_sha(master_path),
                   acceptance_sha256=_sha(acceptance_path), projection_rows=5,
                   rights="not-assessed", installation="not-performed")
    _put_json(stage, Path("locke-a48888-stage-receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.stage)
    print(json.dumps({"status": result["status"], "stage_root": result["stage_root"],
                      "master_sha256": result["accepted_master_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
