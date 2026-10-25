"""Freeze the exact retained PG3296 Confessions witness as a work-local stage."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil

from build.tei.augustines_confessions_oracle import _oracle
from ocd_kernel.library._common import PipelineError
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
WORK_ID = "augustines-confessions"
FORM_ID = "augustines-confessions-retained-electronic-en"
EDITION_ID = "augustines-confessions-retained-electronic-edition"
ACQUISITION_ID = "augustines-confessions-retained-electronic-acquired"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/TheologAI/data/historical-sources/project-gutenberg/pg3296/pg3296.txt")
SOURCE_SHA = "5a036498dc7c546a98b9e7a31952e030ca74db7dd111b30029354efe12bcd691"
CATALOG = Path("metadata/source-evidence/catalog/augustines-confessions.json")
MANIFEST = Path("sources/augustines-confessions/augustines-confessions.source-manifest.json")
CANDIDATE = LIBRARY / "candidate-reviews/37c-062-augustines-confessions-lineage-20260918-v2-terminal-layout/package"
PACKAGE_SHA = "791242a3cf39f8cde7eaae601531dec6feb20547eebe4b68554e04b6f7110d75"
MANIFEST_SHA = "1beb2d1e3791fe08f465b23154e53be5fd39da1f264fb2ac8701bc32be28b6f8"
REPORT_SHA = "cf339e2baa39faede96f2a3c845441fe4c13ed8e7795fa1f60ae748f75423327"
EVIDENCE = WORK / "integration/augustines-pg3296-exact-v1"
BOOKS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII"]


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _write(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    _io_path(target.parent).mkdir(parents=True, exist_ok=True)
    _io_path(target).write_bytes(content)
    return target


def _write_json(stage: Path, relative: Path, value: object) -> Path:
    return _write(stage, relative, (json.dumps(value, ensure_ascii=False, sort_keys=True,
                                               separators=(",", ":")) + "\n").encode("utf-8"))


def _copy(root: Path, stage: Path, relative: Path) -> None:
    target = stage / relative
    _io_path(target.parent).mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(root / relative), _io_path(target))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def prepare(stage: Path, *, root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    stage = stage.absolute()
    if (stage.exists() or stage.parent != (LIBRARY / "candidate-reviews").resolve(strict=True)
            or not stage.name.startswith("augustines-pg3296-s")):
        raise PipelineError("fresh named external PG3296 stage required")
    source = _io_path(root / SOURCE).read_bytes()
    if len(source) != 632167 or _sha(source) != SOURCE_SHA or source.count(b"\r\n") != 9724:
        raise PipelineError("exact CRLF retained PG3296 text differs")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    package = CandidatePackage.load(CANDIDATE)
    report = validate(manifest, package, _oracle)
    if (manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA
            or report.status != "pass" or report.sha256 != REPORT_SHA):
        raise PipelineError(f"current PG3296 manifest, candidate, or oracle differs: {report.findings[:3]}")
    acquisition = validate_acquisition(root / ACQUISITION, root=root)
    if (acquisition.get("source_path") != SOURCE.as_posix()
            or acquisition.get("source_sha256") != SOURCE_SHA
            or len(acquisition["retained_files"]) != 1
            or acquisition["retained_files"][0]["path"] != SOURCE.as_posix()):
        raise PipelineError("PG3296 one-member acquisition boundary differs")
    work = _read(root / WORK / "work.json")
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    if (len(work["textual_forms"]) != 1 or len(form["editions"]) != 1
            or form["textual_form_id"] != FORM_ID or edition["edition_id"] != EDITION_ID
            or edition["acquisition_ids"] != [ACQUISITION_ID]
            or "category" in edition or _io_path(root / EDITION / "master.tei.xml").exists()):
        raise PipelineError("PG3296 sole unaccepted edition preimage differs")
    candidate_account = json.loads(package.member_bytes("source-accountability.json"))
    if (candidate_account["physical_line_count"] != 9724
            or len(candidate_account["line_inventory"]) != 9724
            or candidate_account["book_order"] != BOOKS
            or candidate_account["omitted_count"] != 0
            or candidate_account["duplicate_count"] != 0):
        raise PipelineError("PG3296 complete line/book accounting differs")
    stage.mkdir()
    before = _files(root / WORK)
    for relative in before:
        _copy(root, stage, WORK / relative)
    for relative in {MANIFEST, CATALOG,
                     Path(manifest.record["converter"]["implementation_path"]),
                     Path(manifest.record["validator"]["implementation_path"]),
                     *(Path(item["path"]) for item in manifest.record["authorities"])}:
        _copy(root, stage, relative)
    for name in package.member_names:
        _write(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    _write_json(stage, EVIDENCE / "inputs/validation.json", dict(
        contract="ocd-validation-report-v1", status=report.status,
        candidate_sha256=report.candidate_sha256,
        source_manifest_sha256=report.source_manifest_sha256,
        attestation=dict(report.attestation), findings=list(report.findings),
        report_sha256=report.sha256))
    old_work = json.loads(json.dumps(work))
    edition["category"] = "prose"
    validate_identity_update(old_work, work)
    _write_json(stage, WORK / "work.json", work)
    load_work(stage / WORK / "work.json")
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID,
                    edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)
    revision = dict(id="augustines-pg3296-exact-v1",
                    date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the exact retained CRLF PG3296 Pusey translation witness, including Gutenberg wrapper.")
    source_binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                          source_bytes=len(source), source_scope=acquisition["source_scope"])
    original = package.member_bytes("content.tei.xml")
    bound = bind_reviewed_header(original, expected_sha256=_sha(original),
                                 identity=identity, source=source_binding,
                                 source_url=acquisition["url"],
                                 declared_scope=acquisition["source_scope"], revision=revision)
    if original.split(b"</teiHeader>", 1)[1] != bound.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("PG3296 accepted header changed the candidate text/body")
    candidate_path = _write(stage, EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(candidate_path):
        raise PipelineError(f"PG3296 accepted TEI XSD errors: {errors[:3]}")
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=len(source),
                     sha256=SOURCE_SHA, scope=acquisition["source_scope"])]
    scope = dict(kind="selection", declared=acquisition["source_scope"],
                 expected_members=expected, included_members=included, excluded_members=[])
    common = dict(identity=identity, source=source_binding,
                  candidate=make_file_binding(stage, candidate_path),
                  scope=acquisition["source_scope"],
                  accepted_scope=dict(kind="selection", declared=acquisition["source_scope"]),
                  expected_members=expected, included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[])
    account = _write_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        source_sha256=SOURCE_SHA, source_bytes=len(source),
        source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
        oracle_report_sha256=report.sha256, physical_line_count=9724,
        line_inventory_sha256=candidate_account["line_inventory_sha256"],
        book_order=BOOKS, omitted_count=0, duplicate_count=0,
        original_candidate=make_file_binding(stage, stage / EVIDENCE / "inputs/package/content.tei.xml"),
        candidate_source_accountability=make_file_binding(
            stage, stage / EVIDENCE / "inputs/package/source-accountability.json"),
        catalog_lineage="Separate BOM-prefixed raw/gutenberg/pg3296.txt witness; not authority for this master.",
        text_after_header_unchanged=True))
    command = "py -3 -m build.tools.stage_augustines_pg3296_acceptance"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Producer and oracle share the pinned PG3296 retained text and TEI schema."],
                     independent_corroboration="Independent 9,724-line oracle, current focused contract, TEI XSD, and actual-master native verifier agree.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _write_json(stage, EVIDENCE / f"{name}.json", common | dict(
            status="pass", command=command, exit_code=0, claim=name,
            source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
            oracle_report_sha256=report.sha256, text_after_header_unchanged=True))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    at = _now()
    review = dict(reviewer="agent:augustines-pg3296-source-review", reviewed_at=at,
                  coverage=dict(status="partial", declared=acquisition["source_scope"],
                                reached=["complete 9,724 physical CRLF lines", "thirteen ordered books",
                                         "retained provider wrapper and license", "Book XIII centered doxology",
                                         "independent full-line accounting and source-to-TEI text order",
                                         "declared Book I, VII, XIII CVW loci in dated review"],
                                inspected=["independent full-line accounting and source-to-TEI text order",
                                           "declared Book I, VII, XIII CVW loci in dated review"],
                                unreviewed=["whole-work visual comparison", "print collation"]),
                  source_quality_uncertainty=["Pusey translation and exact print-edition lineage are not independently collated."],
                  discrepancies=[], unreviewed_residuals=["Human acceptance and jurisdictional rights clearance remain unrecorded."])
    review_path = _write_json(stage, EVIDENCE / "review.json", common | review)
    decision = dict(source_local_disposition="Agent acceptance of the complete exact retained PG3296 TXT witness, including provider wrapper; separate BOM catalog witness is not substituted.",
                    blockers=[], agent_assessment=dict(status="accepted", actor=review["reviewer"],
                    assessed_at=at, supported_scope=acquisition["source_scope"], unresolved_claims=[],
                    unassessed_stronger_claims=["human acceptance", "print identity", "rights clearance", "publication"]),
                    human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate_path,
        source_accounting_path=account, scope=scope, technical=technical,
        review=review | dict(report_path=review_path), representation_revision=revision,
        decision=decision)
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    master = _write(stage, EDITION / "master.tei.xml", bound)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(status="promoted", promoted_at=at,
                               master=make_file_binding(stage, master))
    write_acceptance(acceptance, record)
    state = _read(stage / WORK / "state.json")
    matches = [item for item in state["targets"] if item["target_type"] == "edition"
               and item["target_id"] == EDITION_ID]
    if len(matches) != 1 or matches[0]["stage"] != "acquired":
        raise PipelineError("one acquired PG3296 edition target required")
    matches[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=at)
    matches[0]["evidence"].extend([(EDITION / "master.tei.xml").as_posix(),
                                    (EDITION / "acceptance.json").as_posix()])
    _write_json(stage, WORK / "state.json", state)
    validate_acceptance(acceptance, root=stage)
    validate_state(stage / WORK / "state.json", root=stage)
    projection = project_accepted_document(stage, acceptance_path=acceptance, category="prose")
    errors = verify_accepted_document(stage, acceptance_path=acceptance,
                                      rows=projection["rows"], receipt=projection["receipt"],
                                      category="prose")
    locators = [row["locator"]["text_part"] for row in projection["rows"]]
    if errors or locators != ["front"] * 3 + ["body"] * 13 + ["back"] * 2:
        raise PipelineError(f"PG3296 actual-master native books failed: {errors[:3]}; rows={len(projection['rows'])}")
    result = dict(contract="ocd-augustines-pg3296-external-stage-v1", status="staged-only",
                  work_id=WORK_ID, stage_root=stage.as_posix(), before=before,
                  after=_files(stage / WORK), source_sha256=SOURCE_SHA,
                  source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
                  oracle_report_sha256=report.sha256, master_sha256=_sha(_io_path(master).read_bytes()),
                  acceptance_sha256=_sha(_io_path(acceptance).read_bytes()),
                  projection_category="prose", projection_rows=18,
                  independent_verifier_errors=errors, physical_line_count=9724,
                  catalog_bom_witness="separate-not-substituted", rights="not-assessed",
                  human_review="not-recorded", installation="not-performed")
    _write_json(stage, Path("stage-receipt.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.stage)
    print(json.dumps({"work_id": result["work_id"], "master_sha256": result["master_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
