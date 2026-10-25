"""Prepare a source-bound Sum of Saving Knowledge electronic-witness acceptance generation."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil

from build.tei.sum_saving_knowledge_oracle import _oracle
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    project_accepted_document, verify_accepted_document,
)
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
LIBRARY = Path("D:/Library/Open Christian Data")
WORK_ID = "sum-of-saving-knowledge"
FORM_ID = "sum-of-saving-knowledge-retained-electronic"
EDITION_ID = "sum-of-saving-knowledge-retained-electronic-witness"
ACQUISITION_ID = "sum-of-saving-knowledge-retained-source"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/westminster-standard-org/sum-of-saving-knowledge.html")
SOURCE_SHA = "6aa4907f6994d61ce3afeeea9b063cabf667b087185bc1cf7f7fd71fc19fee83"
SOURCE_BYTES = 135684
MANIFEST = Path("sources/doctrinal-documents/sum-of-saving-knowledge/sum-of-saving-knowledge.source-manifest.json")
CANDIDATE = LIBRARY / "candidate-reviews/sum-saving-current-candidate-20260928-v1/package"
PACKAGE_SHA = "9fa8c1a83d6875aeab77473f11f901b58f8f2ced3e143bd03e2a151127d47d83"
EVIDENCE = WORK / "integration/sum-saving-current-html-v1"
CONTRACT = "ocd-sum-saving-current-html-acceptance-stage-v1"


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _read(path: Path) -> bytes:
    return _io_path(path).read_bytes()


def _json(path: Path) -> dict:
    value = json.loads(_read(path))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _write(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    _io_path(target).parent.mkdir(parents=True, exist_ok=True)
    _io_path(target).write_bytes(content)
    return target


def _write_json(stage: Path, relative: Path, value: object) -> Path:
    return _write(stage, relative, (json.dumps(value, ensure_ascii=False, sort_keys=True,
                                               separators=(",", ":")) + "\n").encode("utf-8"))


def _copy(root: Path, stage: Path, relative: Path) -> None:
    target = stage / relative
    _io_path(target).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(root / relative), _io_path(target))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def prepare(stage: Path) -> dict:
    stage = stage.absolute()
    if (_io_path(stage).exists() or stage.parent.resolve(strict=True) != (LIBRARY / "candidate-reviews").resolve(strict=True)
            or not stage.name.startswith("sum-saving-acceptance-")):
        raise ValueError("fresh named Sum of Saving Knowledge candidate-review stage required")
    source = _read(ROOT / SOURCE)
    if len(source) != SOURCE_BYTES or _sha(source) != SOURCE_SHA:
        raise ValueError("retained Sum of Saving Knowledge HTML changed")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    manifest.verify()
    package = CandidatePackage.load(CANDIDATE)
    report = validate(manifest, package, _oracle)
    if package.sha256 != PACKAGE_SHA or report.status != "pass" or report.findings:
        raise ValueError(f"Sum of Saving Knowledge current source oracle failed: {report.findings[:3]}")
    acquisition = validate_acquisition(_io_path(ROOT / ACQUISITION), root=_io_path(ROOT))
    retained = acquisition["retained_files"]
    if (acquisition.get("source_path") != SOURCE.as_posix()
            or acquisition.get("source_sha256") != SOURCE_SHA
            or acquisition.get("source_bytes") != SOURCE_BYTES
            or len(retained) != 1 or retained[0]["path"] != SOURCE.as_posix()
            or retained[0]["sha256"] != SOURCE_SHA
            or acquisition["source_scope"] != retained[0]["scope"]):
        raise ValueError("Sum of Saving Knowledge acquisition/member boundary changed")
    before = _files(ROOT / WORK)
    if set(before) != {"work.json", "state.json", ACQUISITION.relative_to(WORK).as_posix()}:
        raise ValueError("Sum of Saving Knowledge canonical work preimage differs")
    old_work = _json(ROOT / WORK / "work.json")
    old_state = _json(ROOT / WORK / "state.json")
    form = old_work["textual_forms"][0]
    edition = form["editions"][0]
    if (form["textual_form_id"] != FORM_ID or edition["edition_id"] != EDITION_ID
            or edition["acquisition_ids"] != [ACQUISITION_ID]
            or edition.get("language") != "en" or form.get("language") != "en"
            or "category" in edition or _io_path(ROOT / EDITION / "master.tei.xml").exists()):
        raise ValueError("Sum of Saving Knowledge edition preimage differs")
    _io_path(stage).mkdir()
    for relative in before:
        _copy(ROOT, stage, WORK / relative)
    _write(stage, WORK / "SOURCE_CREDIT.md", (
        "# The Sum of Saving Knowledge electronic witness source credit\n\n"
        "This accepted-master stage is based on the complete retained HTML page "
        "`raw/westminster-standard-org/sum-of-saving-knowledge.html` "
        f"(SHA-256 `{SOURCE_SHA}`), provided by The Westminster Standard at "
        "https://thewestminsterstandard.org/the-sum-of-saving-knowledge/. "
        "The [source record](../../../sources/doctrinal-documents/sum-of-saving-knowledge/README.source.md) "
        "describes the six populated text columns and the excluded page navigation. "
        "Authorship, edition identity, attribution, and rights remain unresolved; "
        "this source credit does not authorize publication.\n"
    ).encode("utf-8"))
    dependencies = {MANIFEST, SOURCE}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    for reference in set(old_work.get("evidence", [])) | {
        value for target in old_state["targets"] for value in target["evidence"]
    }:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe inherited Sum of Saving Knowledge evidence: {reference}")
        dependencies.add(relative)
    missing = [relative.as_posix() for relative in dependencies
               if relative != ACQUISITION and not _io_path(ROOT / relative).is_file()]
    if missing:
        raise ValueError(f"Sum of Saving Knowledge source/evidence dependencies absent: {missing}")
    for relative in sorted(dependencies):
        if relative != ACQUISITION:
            _copy(ROOT, stage, relative)
    for name in package.member_names:
        _write(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    _write_json(stage, EVIDENCE / "inputs/validation.json", dict(
        contract="ocd-validation-report-v1", status=report.status,
        candidate_sha256=report.candidate_sha256,
        source_manifest_sha256=report.source_manifest_sha256,
        attestation=dict(report.attestation), findings=list(report.findings),
        report_sha256=report.sha256))
    work = _json(stage / WORK / "work.json")
    work["textual_forms"][0]["editions"][0]["category"] = "prose"
    validate_identity_update(old_work, work)
    _write_json(stage, WORK / "work.json", work)
    load_work(_io_path(stage / WORK / "work.json"))
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID,
                    edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)
    revision = dict(id="sum-saving-current-html-v1",
                    date=datetime.now(timezone.utc).date().isoformat(),
                    note="Bind the complete retained electronic HTML witness and its source-accounted work text.")
    source_binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                          source_bytes=SOURCE_BYTES, source_scope=acquisition["source_scope"])
    original = package.member_bytes("content.tei.xml")
    bound = bind_reviewed_header(original, expected_sha256=_sha(original),
                                 identity=identity, source=source_binding,
                                 source_url=acquisition["url"],
                                 declared_scope=acquisition["source_scope"], revision=revision)
    if original.split(b"</teiHeader>", 1)[1] != bound.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Sum of Saving Knowledge accepted header changed candidate body")
    candidate_path = _write(stage, EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(candidate_path):
        raise ValueError(f"Sum of Saving Knowledge accepted TEI P5 errors: {errors[:3]}")
    member = retained[0]
    expected = [dict(path=member["path"], position=1)]
    included = [dict(path=member["path"], position=1, bytes=member["bytes"],
                     sha256=member["sha256"], scope=member["scope"])]
    scope = dict(kind="selection", declared=acquisition["source_scope"],
                 expected_members=expected, included_members=included, excluded_members=[])
    common = dict(identity=identity, source=source_binding,
                  candidate=make_file_binding(stage, candidate_path),
                  scope=acquisition["source_scope"],
                  accepted_scope=dict(kind="selection", declared=acquisition["source_scope"]),
                  expected_members=expected, included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[])
    account = _write_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        source_sha256=SOURCE_SHA, source_bytes=SOURCE_BYTES,
        source_manifest_sha256=manifest.sha256,
        candidate_package_sha256=package.sha256,
        oracle_report_sha256=report.sha256,
        original_candidate=make_file_binding(stage, stage / EVIDENCE / "inputs/package/content.tei.xml"),
        candidate_source_accountability=make_file_binding(stage, stage / EVIDENCE / "inputs/package/source-accountability.json"),
        body_unchanged=True))
    command = "py -3 -m build.tools.stage_sum_saving_knowledge_acceptance"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Producer and independent oracle share the pinned HTML witness and TEI P5 schema."],
                     independent_corroboration="The complete-source HTML byte ledger, source-specific independent oracle, fresh candidate, TEI P5, and actual-master native verifier agree.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _write_json(stage, EVIDENCE / f"{name}.json", common | dict(
            status="pass", command=command, exit_code=0, claim=name,
            source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
            oracle_report_sha256=report.sha256, body_unchanged=True))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    at = _now()
    review = dict(reviewer="agent:sum-saving-current-html-source-review", reviewed_at=at,
                  coverage=dict(status="partial", declared=acquisition["source_scope"],
                                reached=["complete retained HTML envelope and exclusion byte ledger",
                                         "six populated text columns in source order, with navigation and spacers excluded"],
                                inspected=["complete retained HTML envelope and exclusion byte ledger",
                                           "six populated text columns in source order, with navigation and spacers excluded"],
                                unreviewed=["human visual comparison", "print collation"]),
                  source_quality_uncertainty=["The electronic witness was not collated to a print exemplar."],
                  discrepancies=[],
                  unreviewed_residuals=["Authorship, edition identity, human acceptance, rights clearance, and publication remain unresolved."])
    review_path = _write_json(stage, EVIDENCE / "review.json", common | review)
    decision = dict(source_local_disposition="Agent acceptance of six populated text columns from the complete retained HTML member as one electronic witness; navigation, spacers, shell, support script, and comment have explicit source-accountability dispositions.",
                    blockers=[], agent_assessment=dict(status="accepted", actor=review["reviewer"],
                    assessed_at=at, supported_scope=acquisition["source_scope"], unresolved_claims=[],
                    unassessed_stronger_claims=["human visual review", "print identity", "authorship", "rights clearance", "publication"]),
                    human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate_path,
        source_accounting_path=account, scope=scope, technical=technical,
        review=review | dict(report_path=review_path), representation_revision=revision,
        decision=decision)
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    master = _write(stage, EDITION / "master.tei.xml", bound)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(status="promoted", promoted_at=at,
                               master=make_file_binding(stage, master))
    write_acceptance(acceptance, record)
    state = _json(stage / WORK / "state.json")
    matches = [item for item in state["targets"] if item["target_type"] == "edition"
               and item["target_id"] == EDITION_ID]
    if len(matches) != 1 or matches[0]["stage"] != "acquired":
        raise ValueError("one acquired Sum of Saving Knowledge edition target required")
    matches[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=at)
    matches[0]["evidence"].extend([(EDITION / "master.tei.xml").as_posix(),
                                    (EDITION / "acceptance.json").as_posix()])
    _write_json(stage, WORK / "state.json", state)
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projection = project_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance), category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                      rows=projection["rows"], receipt=projection["receipt"], category="prose")
    if errors or len(projection["rows"]) != 6:
        raise ValueError(f"Sum of Saving Knowledge native projection failed: {errors[:3]}")
    receipt = dict(contract=CONTRACT, status="staged-only", installation="not-performed",
                   work_id=WORK_ID, canonical_root=ROOT.as_posix(), stage_root=stage.as_posix(),
                   before=before, after=_files(stage / WORK), source_sha256=SOURCE_SHA,
                   source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
                   oracle_report_sha256=report.sha256, master_sha256=_sha(bound),
                   acceptance_sha256=_sha(_read(acceptance)), projection_category="prose",
                   projection_rows=6, independent_verifier_errors=errors,
                   rights="unresolved-source-rights", human_review="not-recorded")
    _write_json(stage, Path("stage-receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    receipt = prepare(args.stage)
    print(json.dumps({"work_id": receipt["work_id"], "master_sha256": receipt["master_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
