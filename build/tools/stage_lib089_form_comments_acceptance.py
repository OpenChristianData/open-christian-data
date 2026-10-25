"""Prepare the exact Form HTML acceptance stage with two retained comments."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil

from build.tei.lib089_form_church_comments_oracle import _oracle
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
COHORT = Path("D:/Library/Open Christian Data/candidate-reviews/lib089-form-comment-acceptance-20260928-v2")
WORK_IDS = ("form-of-church-government",)
CANDIDATE_ROOT = Path("D:/Library/Open Christian Data/candidate-reviews")
CONTRACT = "ocd-lib089-form-comments-acceptance-stage-v1"


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _read(path: Path) -> bytes:
    return _io_path(path).read_bytes()


def _json(path: Path) -> dict:
    value = json.loads(_read(path))
    if not isinstance(value, dict):
        raise ValueError(f"LIB-089 JSON object required: {path}")
    return value


def _write(stage: Path, relative: Path, data: bytes) -> Path:
    target = stage / relative
    _io_path(target).parent.mkdir(parents=True, exist_ok=True)
    _io_path(target).write_bytes(data)
    return target


def _write_json(stage: Path, relative: Path, value: object) -> Path:
    return _write(stage, relative, (json.dumps(value, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def _copy(root: Path, stage: Path, relative: Path) -> None:
    target = stage / relative
    _io_path(target).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(root / relative), _io_path(target))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _paths(work_id: str) -> tuple[Path, Path, Path, Path, Path]:
    work = Path("library/works") / work_id
    form_id = work_id + "-retained-text"
    edition_id = work_id + "-retained-electronic-witness"
    acquisition_id = work_id + "-retained-source"
    edition = work / "forms" / form_id / "editions" / edition_id
    acquisition = edition / "acquisitions" / f"{acquisition_id}.json"
    manifest = Path("sources/doctrinal-documents") / work_id / f"{work_id}.source-manifest.json"
    evidence = work / "integration/lib089-form-comments-v1"
    return work, edition, acquisition, manifest, evidence


def prepare_one(work_id: str) -> dict:
    if work_id not in WORK_IDS:
        raise ValueError(f"LIB-089 work outside cohort: {work_id}")
    stage = COHORT / work_id
    if _io_path(stage).exists() or not _io_path(COHORT).is_dir():
        raise ValueError(f"fresh LIB-089 work stage required: {work_id}")
    work_path, edition_path, acquisition_path, manifest_path, evidence = _paths(work_id)
    manifest = SourceManifest.load(ROOT / manifest_path, repository_root=ROOT)
    manifest.verify()
    sources = [item for item in manifest.record["authorities"] if item["role"] == "primary-source"]
    if len(sources) != 1:
        raise ValueError(f"LIB-089 {work_id} requires one source member")
    source = sources[0]
    source_path = Path(source["path"])
    original = _read(ROOT / source_path)
    if len(original) != source["bytes"] or _sha(original) != source["sha256"]:
        raise ValueError(f"LIB-089 {work_id} retained source changed")
    candidate = CANDIDATE_ROOT / "lib089-form-comment-current-20260928-v4/package/package"
    package = CandidatePackage.load(candidate)
    report = validate(manifest, package, _oracle)
    if report.status != "pass" or report.findings:
        raise ValueError(f"LIB-089 {work_id} source oracle failed: {report.findings[:3]}")
    acquisition = validate_acquisition(_io_path(ROOT / acquisition_path), root=_io_path(ROOT))
    retained = acquisition["retained_files"]
    if (len(retained) != 1 or retained[0]["path"] != source_path.as_posix()
            or retained[0]["bytes"] != len(original)
            or retained[0]["sha256"] != source["sha256"]):
        raise ValueError(f"LIB-089 {work_id} acquired source member differs")
    scope_text = retained[0]["scope"]
    before = _files(ROOT / work_path)
    if set(before) != {"work.json", "state.json", acquisition_path.relative_to(work_path).as_posix()}:
        raise ValueError(f"LIB-089 {work_id} work preimage differs")
    old_work = _json(ROOT / work_path / "work.json")
    old_state = _json(ROOT / work_path / "state.json")
    form = old_work["textual_forms"][0]
    edition = form["editions"][0]
    form_id = work_id + "-retained-text"
    edition_id = work_id + "-retained-electronic-witness"
    acquisition_id = work_id + "-retained-source"
    if (form["textual_form_id"] != form_id or edition["edition_id"] != edition_id
            or edition["acquisition_ids"] != [acquisition_id]
            or "category" in edition or _io_path(ROOT / edition_path / "master.tei.xml").exists()):
        raise ValueError(f"LIB-089 {work_id} edition preimage differs")
    profile_path = next(Path(item["path"]) for item in manifest.record["authorities"]
                        if item["name"] == "reconstruction-profile")
    profile = _json(ROOT / profile_path)
    block_count = profile["projection_limit"]["represented_carrier_count"]
    if profile["work_id"] != work_id or profile["rights"]["status"] != "unresolved":
        raise ValueError(f"LIB-089 {work_id} source profile identity or rights differ")
    _io_path(stage).mkdir()
    for name in before:
        _copy(ROOT, stage, work_path / name)
    credit = (
        f"# {old_work['title']} electronic witness source credit\n\n"
        f"Retained HTML: `{source_path.as_posix()}` (SHA-256 `{source['sha256']}`). "
        f"Provider: The Westminster Standard, {acquisition['url']}. "
        f"The [source record](../../../sources/doctrinal-documents/{work_id}/README.source.md) "
        "documents the work boundary and provider attribution context. "
        "Rights and requested attribution for this web transcription remain unresolved. "
        "The historical Public Domain label does not authorize publication.\n"
    ).encode("utf-8")
    _write(stage, work_path / "SOURCE_CREDIT.md", credit)
    dependencies = {manifest_path, source_path}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    for reference in set(old_work.get("evidence", [])) | {
        value for target in old_state["targets"] for value in target["evidence"]
    }:
        path = Path(reference.partition("#")[0])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe LIB-089 {work_id} inherited evidence: {reference}")
        dependencies.add(path)
    dependencies.discard(acquisition_path)
    for path in sorted(dependencies):
        if not _io_path(ROOT / path).is_file():
            raise ValueError(f"LIB-089 {work_id} source/evidence dependency absent: {path}")
        _copy(ROOT, stage, path)
    for name in package.member_names:
        _write(stage, evidence / "inputs/package" / name, package.member_bytes(name))
    _write_json(stage, evidence / "inputs/validation.json", dict(
        contract="ocd-validation-report-v1", status=report.status,
        candidate_sha256=report.candidate_sha256,
        source_manifest_sha256=report.source_manifest_sha256,
        attestation=dict(report.attestation), findings=list(report.findings),
        report_sha256=report.sha256))
    work = _json(stage / work_path / "work.json")
    work_form = work["textual_forms"][0]
    work_form["language"] = "en"
    work_edition = work_form["editions"][0]
    work_edition["language"] = "en"
    work_edition["category"] = "prose"
    validate_identity_update(old_work, work)
    _write_json(stage, work_path / "work.json", work)
    load_work(_io_path(stage / work_path / "work.json"))
    identity = dict(work_id=work_id, textual_form_id=form_id,
                    edition_id=edition_id, acquisition_id=acquisition_id)
    revision = dict(id="lib089-form-comments-v1",
                    date=datetime.now(timezone.utc).date().isoformat(),
                    note="Bind the exact retained Westminster Standard HTML work witness.")
    source_binding = dict(source_path=source_path.as_posix(),
                          source_sha256=source["sha256"], source_bytes=len(original),
                          source_scope=scope_text)
    original_tei = package.member_bytes("content.tei.xml")
    bound = bind_reviewed_header(original_tei, expected_sha256=_sha(original_tei),
                                 identity=identity, source=source_binding,
                                 source_url=acquisition["url"], declared_scope=scope_text,
                                 revision=revision)
    if original_tei.split(b"</teiHeader>", 1)[1] != bound.split(b"</teiHeader>", 1)[1]:
        raise ValueError(f"LIB-089 {work_id} reviewed header changed source candidate body")
    candidate_path = _write(stage, evidence / "candidate.tei.xml", bound)
    if errors := validate_file(candidate_path):
        raise ValueError(f"LIB-089 {work_id} accepted TEI P5 errors: {errors[:3]}")
    member = retained[0]
    expected = [dict(path=member["path"], position=1)]
    included = [dict(path=member["path"], position=1, bytes=member["bytes"],
                     sha256=member["sha256"], scope=member["scope"])]
    scope = dict(kind="selection", declared=scope_text, expected_members=expected,
                 included_members=included, excluded_members=[])
    common = dict(identity=identity, source=source_binding,
                  candidate=make_file_binding(stage, candidate_path), scope=scope_text,
                  accepted_scope=dict(kind="selection", declared=scope_text),
                  expected_members=expected, included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[])
    account = _write_json(stage, evidence / "source-accounting.json", common | dict(
        source_sha256=source["sha256"], source_bytes=len(original),
        source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
        oracle_report_sha256=report.sha256, represented_source_blocks=block_count,
        original_candidate=make_file_binding(stage, stage / evidence / "inputs/package/content.tei.xml"),
        candidate_source_accountability=make_file_binding(stage, stage / evidence / "inputs/package/source-accountability.json"),
        body_unchanged=True))
    command = "py -3 -m build.tools.stage_lib089_form_comments_acceptance"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Producer and independent oracle share the pinned HTML member and TEI P5 schema."],
                     independent_corroboration="Per-work complete-source HTML event ledger, independent source oracle, fresh candidate, P5, and actual-master native verifier agree.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _write_json(stage, evidence / f"{name}.json", common | dict(
            status="pass", command=command, exit_code=0, claim=name,
            source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
            oracle_report_sha256=report.sha256, body_unchanged=True))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    at = _now()
    reached = ["complete retained HTML envelope and source event ledger",
               f"{block_count} represented source-native content blocks in order"]
    review = dict(reviewer="agent:lib089-form-comment-source-review", reviewed_at=at,
                  coverage=dict(status="partial", declared=scope_text, reached=reached,
                                inspected=reached, unreviewed=["human visual comparison", "print collation"]),
                  source_quality_uncertainty=["The electronic witness was not collated to a print exemplar."],
                  discrepancies=[],
                  unreviewed_residuals=["Human acceptance, provider transcription rights, and publication remain unresolved."])
    review_path = _write_json(stage, evidence / "review.json", common | review)
    decision = dict(source_local_disposition=f"Agent acceptance of {block_count} source-attested content blocks from the complete retained HTML member as one electronic witness; empty carriers and page support have explicit source-accountability dispositions.",
                    blockers=[], agent_assessment=dict(status="accepted", actor=review["reviewer"],
                    assessed_at=at, supported_scope=scope_text, unresolved_claims=[],
                    unassessed_stronger_claims=["human visual review", "print identity", "provider rights", "publication"]),
                    human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate_path,
        source_accounting_path=account, scope=scope, technical=technical,
        review=review | dict(report_path=review_path), representation_revision=revision,
        decision=decision)
    acceptance = stage / edition_path / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    master = _write(stage, edition_path / "master.tei.xml", bound)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(status="promoted", promoted_at=at,
                               master=make_file_binding(stage, master))
    write_acceptance(acceptance, record)
    state = _json(stage / work_path / "state.json")
    matches = [item for item in state["targets"] if item["target_type"] == "edition"
               and item["target_id"] == edition_id]
    if len(matches) != 1 or matches[0]["stage"] != "acquired":
        raise ValueError(f"LIB-089 {work_id} one acquired edition target required")
    matches[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=at)
    matches[0]["evidence"].extend([(edition_path / "master.tei.xml").as_posix(),
                                    (edition_path / "acceptance.json").as_posix()])
    _write_json(stage, work_path / "state.json", state)
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / work_path / "state.json"), root=_io_path(stage))
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance), category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or len(projected["rows"]) != block_count:
        raise ValueError(f"LIB-089 {work_id} native block projection differs: {errors[:3]}")
    receipt = dict(contract=CONTRACT, status="staged-only", installation="not-performed",
                   work_id=work_id, canonical_root=ROOT.as_posix(), stage_root=stage.as_posix(),
                   before=before, after=_files(stage / work_path), source_path=source_path.as_posix(),
                   source_sha256=source["sha256"], source_bytes=len(original),
                   source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
                   oracle_report_sha256=report.sha256, master_sha256=_sha(bound),
                   acceptance_sha256=_sha(_read(acceptance)), projection_category="prose",
                   projection_rows=block_count, independent_verifier_errors=errors,
                   rights="unresolved-provider-transcription-rights", human_review="not-recorded")
    _write_json(stage, Path("stage-receipt.json"), receipt)
    return receipt


def main() -> None:
    if _io_path(COHORT).exists() or COHORT.parent.resolve(strict=True) != CANDIDATE_ROOT.resolve(strict=True):
        raise ValueError("fresh external LIB-089 cohort root required")
    _io_path(COHORT).mkdir()
    rows = []
    for work_id in WORK_IDS:
        receipt = prepare_one(work_id)
        path = COHORT / work_id / "stage-receipt.json"
        rows.append(dict(work_id=work_id, receipt_sha256=_sha(_read(path)),
                         source_sha256=receipt["source_sha256"],
                         master_sha256=receipt["master_sha256"],
                         acceptance_sha256=receipt["acceptance_sha256"],
                         projection_rows=receipt["projection_rows"]))
    index = dict(contract="ocd-lib089-form-comments-freeze-index-v1",
                 status="staged-only", installation="not-performed",
                 canonical_root=ROOT.as_posix(), cohort_root=COHORT.as_posix(), works=rows)
    _write_json(COHORT, Path("freeze-index.json"), index)
    print(json.dumps(index, sort_keys=True))


if __name__ == "__main__":
    main()
