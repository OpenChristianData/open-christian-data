"""Stage Baths A47235's complete A47235 electronic witness outside the canonical library."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tei.prayers_baths_for_cure_oracle import _oracle
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prayers import project_accepted_prayers, verify_accepted_prayers
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "prayers-baths-for-cure"
WORK = Path("library/works") / WORK_ID
FORM_ID = WORK_ID + "-tcp-retained"
EDITION_ID = WORK_ID + "-tcp-electronic"
ACQUISITION_ID = WORK_ID + "-tcp-acquired"
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / (ACQUISITION_ID + ".json")
SOURCE = Path("raw/tcp/high-range/A47235/A47235.xml")
MANIFEST = Path("sources/structured-text") / WORK_ID / (WORK_ID + ".source-manifest.json")
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/prayers-baths-20261001-a/package")
REPLAY = Path("D:/Library/Open Christian Data/candidate-reviews/prayers-baths-20261001-b/package")
EVIDENCE = WORK / "integration/baths-a47235-electronic-acceptance-v1"
IDENTITY = dict(work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)
SOURCE_SHA = "741b3c5faf5c90d1735563fc793fdc5cd7eebc9118d2707a731742f82f8e0117"
MANIFEST_SHA = "8ea320b182948f18f2f5acaeb014d827d2ee7aa8c2ec5cedf2fa522cd21a1cc9"
PACKAGE_SHA = "933885321e7f4ffcaf6ef06191f072e80c37d5e52df3a6bce07454c025c8ad24"
REPORT_SHA = "459432468c6024d5623f1447e8bec60aae922403ccdcd0815d0047de928b71ee"
BEFORE = {
    "work.json": "4bfd0c04dda923aa2dbb3dd05c214e0c935d4107d30189a052bd4d4373f9ff7e",
    "state.json": "4efd3643da9cd11ae8b7c29ba29a56b68d5ac3a19c6efe7ee97dbcf3e9ab3e27",
    "SOURCE_CREDIT.md": "6f605d2b02596dbefca7bfd1910efa21bc0f24c66d5642460060411549b5d96c",
    (ACQUISITION.relative_to(WORK)).as_posix(): "fe37b11f4b9cc9b733983e0ef05aac6e39ecb057ce3defb32d0901f6b514ccd4",
}


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    content = _io_path(path).read_bytes()
    if expected and sha256(content).hexdigest() != expected:
        raise ValueError(f"Baths A47235 source/stage input drifted: {path}")
    return content


def _json(path: Path) -> dict:
    value = json.loads(_read(path))
    if not isinstance(value, dict):
        raise ValueError(f"Baths A47235 JSON object required: {path}")
    return value


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    path = stage / relative
    _io_path(path).parent.mkdir(parents=True, exist_ok=True)
    _io_path(path).write_bytes(content)
    return path


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    content = (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    return _put(stage, relative, content)


def prepare(stage: Path) -> dict:
    stage = stage.absolute()
    if (_io_path(stage).exists() or not _io_path(stage.parent).is_dir()
            or ROOT.resolve() in stage.resolve().parents or stage.resolve() == ROOT.resolve()):
        raise ValueError("Baths A47235 stage must be a fresh external directory")
    original = _read(ROOT / SOURCE, SOURCE_SHA)
    if len(original) != 69708 or _files(ROOT / WORK) != BEFORE:
        raise ValueError("Baths A47235 retained source or complete work preimage differs")
    acquisition = _json(ROOT / ACQUISITION)
    retained = acquisition.get("retained_files", [])
    if (acquisition.get("source_path") != SOURCE.as_posix() or acquisition.get("source_sha256") != SOURCE_SHA
            or acquisition.get("source_bytes") != len(original) or len(retained) != 1
            or retained[0].get("path") != SOURCE.as_posix() or retained[0].get("sha256") != SOURCE_SHA
            or retained[0].get("scope") != acquisition.get("source_scope")):
        raise ValueError("Baths A47235 acquisition is not the one complete retained XML member")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(_io_path(CANDIDATE))
    report = validate(manifest, package, _oracle)
    replay = CandidatePackage.load(_io_path(REPLAY))
    if package.sha256 != replay.sha256 or _files(CANDIDATE) != _files(REPLAY):
        raise ValueError("Baths A47235 clean-process replay differs")
    mutations = []
    for old, new in ((b'type="map"', b'type="lost-map"'),
                     (b'type="prayers"', b'type="prose"'),
                     (b'char:EOLunhyphen', b'char:EOLhyphen'),
                     (b'<unclear>bear</unclear>', b'bare')):
        if original.count(old) != 1:
            raise ValueError("Baths A47235 mutation locus is not unique")

        class ChangedContent:
            sha256 = package.sha256
            manifest = package.manifest

            def member_bytes(self, name: str) -> bytes:
                return original.replace(old, new, 1) if name == "content.tei.xml" else package.member_bytes(name)

        rejected = _oracle(manifest, ChangedContent())
        if rejected["status"] != "fail" or "candidate TEI is not byte-identical to retained A47235 XML" not in rejected["findings"]:
            raise ValueError("Baths A47235 mutation was not rejected for source change")
        mutations.append(dict(locus=old.decode(), status=rejected["status"], findings=rejected["findings"]))
    if (manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA or report.sha256 != REPORT_SHA
            or report.status != "pass" or report.findings or package.member_bytes("content.tei.xml") != original):
        raise ValueError("Baths A47235 current source/candidate/oracle closure differs")
    old_work = _json(ROOT / WORK / "work.json")
    old_state = _json(ROOT / WORK / "state.json")
    if (len(old_work["textual_forms"]) != 1 or len(old_work["textual_forms"][0]["editions"]) != 1
            or old_work["textual_forms"][0]["editions"][0]["edition_id"] != EDITION_ID
            or _io_path(ROOT / EDITION / "acceptance.json").exists()
            or _io_path(ROOT / EDITION / "master.tei.xml").exists()):
        raise ValueError("Baths A47235 work/edition boundary differs")
    edition_targets = [t for t in old_state["targets"] if t["target_type"] == "edition" and t["target_id"] == EDITION_ID]
    if len(edition_targets) != 1 or edition_targets[0]["stage"] != "acquired":
        raise ValueError("Baths A47235 edition is not uniquely acquired")
    for relative, checksum in BEFORE.items():
        _put(stage, WORK / relative, _read(ROOT / WORK / relative, checksum))
    dependencies = {SOURCE, MANIFEST}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    dependencies.update(Path(manifest.record[key]["implementation_path"]) for key in ("converter", "validator"))
    for reference in set(old_work.get("evidence", [])) | {item for target in old_state["targets"] for item in target.get("evidence", [])}:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe inherited Baths A47235 evidence: {reference}")
        dependencies.add(relative)
    for relative in sorted(dependencies):
        if not relative.is_relative_to(WORK):
            _put(stage, relative, _read(ROOT / relative))
    for name in package.member_names:
        _put(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    _put(stage, WORK / "SOURCE_CREDIT.md", _read(ROOT / "sources/structured-text" / WORK_ID / "README.md"))
    work = _json(stage / WORK / "work.json")
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    if any(value.get("language") is not None for value in (form, edition)) or edition.get("category") is not None:
        raise ValueError("Baths A47235 language/category preimage differs")
    form["language"] = "en"
    edition["language"] = "en"
    edition["category"] = "prayers"
    validate_identity_update(old_work, work)
    _put_json(stage, WORK / "work.json", work)
    load_work(_io_path(stage / WORK / "work.json"))
    revision = dict(id="baths-a47235-electronic-agent-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Bind the complete retained TCP electronic witness; source text body unchanged.")
    source_binding = dict(source_path=SOURCE.as_posix(), source_bytes=len(original),
                          source_sha256=SOURCE_SHA, source_scope=acquisition["source_scope"])
    derived = bind_reviewed_header(original, expected_sha256=SOURCE_SHA, identity=IDENTITY,
                                   source=source_binding, source_url=acquisition["url"],
                                   declared_scope=acquisition["source_scope"], revision=revision)
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Baths A47235 accepted header changed retained text")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"Baths A47235 accepted TEI P5 errors: {errors[:3]}")
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=len(original), sha256=SOURCE_SHA, scope=acquisition["source_scope"])]
    scope = dict(kind="edition", declared=acquisition["source_scope"], expected_members=expected,
                 included_members=included, excluded_members=[])
    common = dict(identity=IDENTITY, source=source_binding, candidate=make_file_binding(stage, candidate),
                  scope=acquisition["source_scope"], accepted_scope=dict(kind="edition", declared=acquisition["source_scope"]),
                  expected_members=expected, included_members=included, excluded_members=[], missing_members=[], unknown_members=[])
    accounting = _put_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        source_sha256=SOURCE_SHA, source_bytes=len(original), source_manifest_sha256=MANIFEST_SHA,
        candidate_package_sha256=PACKAGE_SHA, basis="Complete retained XML and candidate are byte-identical; current independent oracle passes."))
    command = "py -3 -m build.tools.stage_prayers_baths_for_cure_acceptance --stage <fresh-external-root>"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]), checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Producer and oracle both parse the same retained TEI with lxml; exact byte equality independently establishes source conservation."],
                     independent_corroboration="Full source/candidate byte equality, independent source feature census, TEI P5 XSD, and current manifest-bound oracle.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = _put_json(stage, EVIDENCE / (name + ".json"), common | dict(status="pass", command=command,
                         exit_code=0, claim=name, source_manifest_sha256=MANIFEST_SHA,
                         candidate_package_sha256=PACKAGE_SHA, oracle_report_sha256=REPORT_SHA,
                         original_source_bytes_unchanged=True,
                         oracle=dict(report.attestation), mutation_checks=mutations,
                         clean_process_replay=dict(first_package=CANDIDATE.as_posix(), second_package=REPLAY.as_posix(),
                                                   identical_files=_files(CANDIDATE), candidate_sha256=replay.sha256)))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    review = dict(reviewer="agent:baths-a47235-electronic-stage", reviewed_at=now,
                  coverage=dict(status="partial", declared=acquisition["source_scope"],
                                reached=[f"{SOURCE.as_posix()}#full-byte-source"],
                                inspected=[f"{SOURCE.as_posix()}#full-byte-source"],
                                unreviewed=[f"{SOURCE.as_posix()}#print-image-collation"]),
                  source_quality_uncertainty=["TCP keyboarding was not collated with page images in this review."],
                  discrepancies=[], unreviewed_residuals=["Human textual and rights decisions are not recorded."])
    review_file = _put_json(stage, EVIDENCE / "review.json", common | review)
    decision = dict(source_local_disposition="Agent acceptance of exact complete TCP A47235 electronic witness only.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=now,
                                          supported_scope=acquisition["source_scope"], unresolved_claims=[],
                                          unassessed_stronger_claims=["print collation", "human review", "rights clearance", "publication"]))
    acceptance = build_acceptance_record(stage, identity=IDENTITY, candidate_path=candidate,
                                         source_accounting_path=accounting, scope=scope, technical=technical,
                                         review=review | dict(report_path=review_file),
                                         representation_revision=revision, decision=decision)
    acceptance_path = stage / EDITION / "acceptance.json"
    write_acceptance(_io_path(acceptance_path), acceptance)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    master_path = _put(stage, EDITION / "master.tei.xml", derived)
    acceptance["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(stage, master_path))
    write_acceptance(_io_path(acceptance_path), acceptance)
    state = _json(stage / WORK / "state.json")
    target = next(t for t in state["targets"] if t["target_type"] == "edition" and t["target_id"] == EDITION_ID)
    target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    target["evidence"].extend([(EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()])
    _put_json(stage, WORK / "state.json", state)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projected = project_accepted_prayers(_io_path(stage), acceptance_path=_io_path(acceptance_path))
    errors = verify_accepted_prayers(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 3:
        raise ValueError(f"Baths A47235 actual-master native prayers projection failed: {errors[:3]}")
    receipt = dict(contract="ocd-baths-a47235-electronic-stage-v1", status="staged-only",
                   canonical_root=ROOT.as_posix(), stage_root=stage.as_posix(), work_id=WORK_ID,
                   source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA, source_manifest_sha256=MANIFEST_SHA,
                   original_candidate_sha256=PACKAGE_SHA, original_tei_sha256=SOURCE_SHA,
                   oracle_report_sha256=REPORT_SHA, before=BEFORE, after=_files(stage / WORK),
                   accepted_master_sha256=_sha(master_path), acceptance_sha256=_sha(acceptance_path),
                   projection_rows=3, rights="not-assessed", installation="not-performed")
    _put_json(stage, Path("baths-a47235-stage-receipt.json"), receipt)
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
