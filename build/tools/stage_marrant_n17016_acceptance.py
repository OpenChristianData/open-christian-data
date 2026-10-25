"""Stage the complete retained Evans-TCP N17016 electronic witness outside the library."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.marrant_prince_hall_african_lodge_sermon_oracle import _oracle
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.sermons import project_accepted_sermons, verify_accepted_sermons
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "marrant-prince-hall-african-lodge-sermon"
WORK = Path("library/works") / WORK_ID
FORM_ID = WORK_ID + "-tcp-retained-en"
EDITION_ID = WORK_ID + "-tcp-electronic"
ACQUISITION_ID = WORK_ID + "-tcp-acquired"
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / (ACQUISITION_ID + ".json")
SOURCE = Path("raw/clean-ready-acquisition-to-tei/master-2/15") / WORK_ID / "N17016.xml"
MANIFEST = Path("sources/structured-text") / WORK_ID / (WORK_ID + ".source-manifest.json")
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/marrant-n17016-exact-source-20260927-v1")
VISUAL = Path("reports/clean-ready-acquisition-to-tei/master-2/15") / WORK_ID
EVIDENCE = WORK / "integration/marrant-n17016-electronic-acceptance-v1"
IDENTITY = dict(work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID,
                acquisition_id=ACQUISITION_ID)
CONTRACT = "ocd-marrant-n17016-electronic-stage-v1"
SOURCE_SHA = "cec45792f758853c291b79aaba32f79bb12360e1247e9d3e0e9271fa3b577434"
MANIFEST_SHA = "3e10d23b795aeb3258c9e045830040922423559e4121372c017ff82eb92f7603"
PACKAGE_SHA = "28e545beb1152ef044c0c2edcca9b99fd08cffe7b1c5a13c5a64220b190531a7"
VALIDATION_SHA = "9deefc70d9e4d50659e0840da34f643b308078969ca7e332ea2f3abb5c8e44a8"
REPORT_SHA = "6b2fc2d51c87441c4e9dc107eab8b5243bcbf5960f70c2e8ec9aed7c0c934c91"
BEFORE = {
    "work.json": "8e824bf34c421cbf545ed2373fcec91b0af428ba432e8d307bce26a203797a63",
    "state.json": "dfdaf0bb7d6a2aa912aabf57fa7e6f789acbee7a9546118093a4bdfb8f400e5d",
    "SOURCE_CREDIT.md": "ed1ba8cfccab1ff04e8649e80c891664b350dc88ac41739e0720bd92dd2683df",
    (ACQUISITION.relative_to(WORK)).as_posix(): "2f13be1fddfa640602419671d3ca551f9c2b38e1f18b6e40f2050d1788809a2e",
}
VISUAL_SHA = "505741a3015e1a9988e9283564f708203387ccc61a6316e4e2afc6c030ea262d"
VISUAL_IMAGES = {
    "visual-paired-spot-check.png": "b126d3cfa403f64d55ef1c39d60b9029e615780598e7c80bffdf4b78e4d62712",
}


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    value = _io_path(path).read_bytes()
    if expected and sha256(value).hexdigest() != expected:
        raise ValueError(f"Marrant N17016 evidence changed: {path}")
    return value


def _json(path: Path) -> dict:
    value = json.loads(_read(path))
    if not isinstance(value, dict):
        raise ValueError(f"Marrant N17016 object required: {path}")
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
            or stage.resolve() == CANDIDATE.resolve() or CANDIDATE.resolve() in stage.resolve().parents):
        raise ValueError("Marrant N17016 stage must be a fresh external directory")
    original = _read(ROOT / SOURCE, SOURCE_SHA)
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(_io_path(CANDIDATE / "package"))
    recorded = _json(CANDIDATE / "validation.json")
    fresh = validate(manifest, package, _oracle)
    if (manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA
            or package.manifest.get("status") != "nonaccepted"
            or _sha(CANDIDATE / "validation.json") != VALIDATION_SHA
            or package.member_bytes("content.tei.xml") != original
            or fresh.status != "pass" or fresh.findings or fresh.sha256 != REPORT_SHA
            or recorded.get("status") != "pass" or recorded.get("findings") != []
            or recorded.get("candidate_sha256") != PACKAGE_SHA
            or recorded.get("source_manifest_sha256") != MANIFEST_SHA
            or recorded.get("report_sha256") != REPORT_SHA
            or recorded.get("attestation", {}).get("source_sha256") != SOURCE_SHA):
        raise ValueError("Marrant N17016 current source/candidate/oracle binding differs")
    root = etree.fromstring(original, etree.XMLParser(resolve_entities=False, no_network=True))
    names = Counter(etree.QName(node).localname for node in root.iter())
    if (root.tag != "{http://www.tei-c.org/ns/1.0}TEI" or len(list(root.iter())) != 256
            or names["pb"] != 24 or names["g"] != 94 or names["gap"] != 9
            or names["front"] != 1 or names["body"] != 1 or names["text"] != 1):
        raise ValueError("Marrant N17016 complete source envelope differs")
    if _files(ROOT / WORK) != BEFORE:
        raise ValueError("Marrant N17016 canonical four-file work preimage differs")
    acquisition = _json(ROOT / ACQUISITION)
    retained = acquisition.get("retained_files", [])
    if (acquisition.get("source_path") != SOURCE.as_posix()
            or acquisition.get("source_bytes") != len(original)
            or acquisition.get("source_sha256") != SOURCE_SHA
            or len(retained) != 1 or retained[0].get("sha256") != SOURCE_SHA
            or retained[0].get("path") != SOURCE.as_posix()
            or acquisition.get("source_scope") != retained[0].get("scope")):
        raise ValueError("Marrant N17016 current acquisition source binding differs")
    old_work = _json(ROOT / WORK / "work.json")
    old_state = _json(ROOT / WORK / "state.json")
    if (_io_path(ROOT / EDITION / "acceptance.json").exists()
            or _io_path(ROOT / EDITION / "master.tei.xml").exists()
            or old_work["textual_forms"][0]["editions"][0]["edition_id"] != EDITION_ID):
        raise ValueError("Marrant N17016 edition preimage differs")
    targets = [t for t in old_state["targets"] if t["target_type"] == "edition" and t["target_id"] == EDITION_ID]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise ValueError("Marrant N17016 edition is not uniquely acquired")
    visual = _json(ROOT / VISUAL / "visual-checklist.json")
    if (_sha(ROOT / VISUAL / "visual-checklist.json") != VISUAL_SHA
            or visual.get("surface", {}).get("source_sha256") != SOURCE_SHA
            or visual.get("surface", {}).get("candidate_tei_sha256") != SOURCE_SHA
            or set(VISUAL_IMAGES) != {item["path"].rsplit("/", 1)[-1] for item in visual["screenshots"]}):
        raise ValueError("Marrant N17016 historical visual source/TEI pair differs")
    for name, digest in VISUAL_IMAGES.items():
        _read(ROOT / VISUAL / name, digest)
    for relative, checksum in BEFORE.items():
        _put(stage, WORK / relative, _read(ROOT / WORK / relative, checksum))
    dependencies = {SOURCE, MANIFEST}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    dependencies.update(Path(manifest.record[key]["implementation_path"]) for key in ("converter", "validator"))
    for reference in set(old_work.get("evidence", [])) | {
        item for target in old_state["targets"] for item in target.get("evidence", [])
    }:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe inherited Marrant N17016 evidence path: {reference}")
        dependencies.add(relative)
    for relative in sorted(dependencies):
        if not relative.is_relative_to(WORK):
            _put(stage, relative, _read(ROOT / relative))
    for name in package.member_names:
        _put(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    _put(stage, EVIDENCE / "inputs/validation.json", _read(CANDIDATE / "validation.json", VALIDATION_SHA))
    _put(stage, EVIDENCE / "inputs/historical-visual-checklist.json", _read(ROOT / VISUAL / "visual-checklist.json", VISUAL_SHA))
    for name, digest in VISUAL_IMAGES.items():
        _put(stage, EVIDENCE / "visual" / name, _read(ROOT / VISUAL / name, digest))
    work = _json(stage / WORK / "work.json")
    edition = work["textual_forms"][0]["editions"][0]
    if edition.get("category") is not None:
        raise ValueError("Marrant N17016 edition category preimage differs")
    edition["category"] = "sermons"
    validate_identity_update(old_work, work)
    _put_json(stage, WORK / "work.json", work)
    load_work(_io_path(stage / WORK / "work.json"))
    revision = dict(id="marrant-n17016-electronic-agent-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Bind the complete retained TCP TEI electronic witness; original source body unchanged.")
    source_binding = dict(source_path=SOURCE.as_posix(), source_bytes=len(original),
                          source_sha256=SOURCE_SHA, source_scope=acquisition["source_scope"])
    derived = bind_reviewed_header(original, expected_sha256=SOURCE_SHA, identity=IDENTITY,
                                   source=source_binding, source_url=acquisition["url"],
                                   declared_scope=acquisition["source_scope"], revision=revision)
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Marrant N17016 accepted header changed the source text")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"Marrant N17016 accepted TEI P5 errors: {errors[:3]}")
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
        source_sha256=SOURCE_SHA, source_bytes=len(original), source_manifest_sha256=MANIFEST_SHA,
        candidate_package_sha256=PACKAGE_SHA, source_element_counts=dict(sorted(names.items())),
        basis="The complete retained XML and candidate are byte-identical; independent current-manifest oracle and TEI P5 validation pass."))
    command = "py -3 -m build.tools.stage_marrant_n17016_acceptance --stage <fresh-external-root>"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Producer and oracle parse the same retained TEI with lxml; exact byte equality independently establishes source conservation."],
                     independent_corroboration="Current manifest-bound oracle, exact candidate/source byte equality, source element census, and retained historical five-locus offline paired review.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = _put_json(stage, EVIDENCE / (name + ".json"), common | dict(
            status="pass", command=command, exit_code=0, claim=name,
            source_manifest_sha256=MANIFEST_SHA, candidate_package_sha256=PACKAGE_SHA,
            validation_sha256=VALIDATION_SHA, oracle_report_sha256=REPORT_SHA,
            original_source_bytes_unchanged=True))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    review = dict(reviewer="agent:marrant-n17016-electronic-stage", reviewed_at=now,
                  coverage=dict(status="partial", declared=acquisition["source_scope"],
                                reached=[f"{SOURCE.as_posix()}#full-byte-source",
                                         f"{SOURCE.as_posix()}#historical-six-locus-offline-pair"],
                                inspected=[f"{SOURCE.as_posix()}#full-byte-source",
                                           f"{SOURCE.as_posix()}#historical-six-locus-offline-pair"],
                                unreviewed=[f"{SOURCE.as_posix()}#complete-new-CVW-visual-proofreading"]),
                  source_quality_uncertainty=["TCP Phase I keyboarded and encoded text was not collated with page images."],
                  discrepancies=[], unreviewed_residuals=[
                      "The August 31 paired spot check used offline sheets after the in-app Browser localhost boundary; it is historical bounded evidence for the same source/TEI bytes, not a fresh CVW pixel review.",
                      "Human textual and rights decisions are not recorded."])
    review_file = _put_json(stage, EVIDENCE / "review.json", common | review | dict(
        historical_visual_checklist_sha256=VISUAL_SHA,
        historical_candidate_source_and_tei_sha256=SOURCE_SHA))
    decision = dict(source_local_disposition="Agent acceptance of the exact complete TCP N17016 electronic witness only.",
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
    projected = project_accepted_sermons(_io_path(stage), acceptance_path=_io_path(acceptance_path))
    errors = verify_accepted_sermons(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                     rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise ValueError(f"Marrant N17016 actual-master sermon projection failed: {errors[:3]}")
    receipt = dict(contract=CONTRACT, status="staged-only", canonical_root=ROOT.as_posix(),
                   stage_root=stage.as_posix(), work_id=WORK_ID, source_path=SOURCE.as_posix(),
                   source_sha256=SOURCE_SHA, source_manifest_sha256=MANIFEST_SHA,
                   original_candidate_sha256=PACKAGE_SHA, original_tei_sha256=SOURCE_SHA,
                   current_validation_sha256=VALIDATION_SHA, historical_visual_sha256=VISUAL_SHA,
                   before=BEFORE, after=_files(stage / WORK), accepted_master_sha256=_sha(master_path),
                   acceptance_sha256=_sha(acceptance_path), projection_rows=1,
                   rights="not-assessed", installation="not-performed")
    _put_json(stage, Path("marrant-n17016-stage-receipt.json"), receipt)
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
