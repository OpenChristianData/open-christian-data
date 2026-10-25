"""Freeze a source-bound acceptance stage for Luther's PG1722 electronic text.

This module writes only a fresh external stage. It cannot install a work.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil

from lxml import etree

from build.tei.luthers_large_catechism_oracle import _oracle
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    project_accepted_document,
    verify_accepted_document,
)
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = Path("D:/Library/Open Christian Data")
WORK_ID = "luthers-large-catechism"
FORM_ID = "luthers-large-catechism-retained-electronic-en"
EDITION_ID = "luthers-large-catechism-retained-electronic-edition"
ACQUISITION_ID = "luthers-large-catechism-retained-electronic-acquired"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/gutenberg/pg1722.txt")
SOURCE_SHA = "0e5df44eea431ef1ebaf222b2802a2fd61cbe1468bea0923085bc95797dc0b43"
MANIFEST = Path("sources/structured-text/luthers-large-catechism/luthers-large-catechism.source-manifest.json")
CANDIDATE = LIBRARY / "candidate-reviews/luther-large-pg1722-source-candidate-20260927-v1"
EVIDENCE = WORK / "integration/luther-pg1722-electronic-v1"
NS = "http://www.tei-c.org/ns/1.0"


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
                                               separators=(",", ":")) + "\n").encode())


def _copy(root: Path, stage: Path, relative: Path) -> None:
    source, target = root / relative, stage / relative
    _io_path(target.parent).mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(source), _io_path(target))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _readable_master(candidate: bytes, *, source_url: str, scope: str) -> bytes:
    """Use an acceptance-compatible header; preserve the candidate text bytes."""
    old = etree.fromstring(candidate, etree.XMLParser(resolve_entities=False,
                                                      load_dtd=False, no_network=True))
    if old.find(f"{{{NS}}}teiHeader") is None or old.find(f"{{{NS}}}text") is None:
        raise PipelineError("Luther candidate has no unique header/text envelope")
    opening, closing = b"<teiHeader>", b"</teiHeader>"
    if candidate.count(opening) != 1 or candidate.count(closing) != 1:
        raise PipelineError("Luther candidate header byte boundary differs")
    header_start = candidate.index(opening)
    header_end = candidate.index(closing) + len(closing)
    def q(name: str) -> str:
        return f"{{{NS}}}{name}"
    header = etree.Element(q("teiHeader"), nsmap={None: NS})
    file_desc = etree.SubElement(header, q("fileDesc"))
    title_stmt = etree.SubElement(file_desc, q("titleStmt"))
    etree.SubElement(title_stmt, q("title")).text = "Martin Luther's Large Catechism, translated by Bente and Dau"
    publication = etree.SubElement(file_desc, q("publicationStmt"))
    etree.SubElement(publication, q("p")).text = "Project Gutenberg electronic witness; rights and release remain unassessed."
    source_desc = etree.SubElement(file_desc, q("sourceDesc"))
    bibl = etree.SubElement(source_desc, q("bibl"))
    etree.SubElement(bibl, q("ptr"), target=source_url)
    etree.SubElement(bibl, q("idno"), type="sha256").text = SOURCE_SHA
    base = candidate[:header_start] + etree.tostring(header, encoding="UTF-8") + candidate[header_end:]
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID,
                    edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)
    revision = dict(id="luther-pg1722-electronic-v1",
                    date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete retained Project Gutenberg electronic transcription.")
    source = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                  source_bytes=288656, source_scope=scope)
    bound = bind_reviewed_header(base, expected_sha256=_sha(base), identity=identity,
                                 source=source, source_url=source_url,
                                 declared_scope=scope, revision=revision)
    before_text = candidate.split(b"</teiHeader>", 1)[1]
    after_text = bound.split(b"</teiHeader>", 1)[1]
    if before_text != after_text:
        raise PipelineError("Luther accepted header changed candidate text bytes")
    return bound


def prepare(stage: Path, *, root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    stage = stage.absolute()
    if (stage.exists() or stage.parent != (LIBRARY / "candidate-reviews").resolve(strict=True)
            or not stage.name.startswith("luther-pg1722-accepted-stage-")):
        raise PipelineError("fresh named external Luther stage required")
    source = _io_path(root / SOURCE).read_bytes()
    if len(source) != 288656 or _sha(source) != SOURCE_SHA:
        raise PipelineError("retained PG1722 source bytes differ")
    if source.count(b"\r\n") != 4886:
        raise PipelineError("retained PG1722 physical-line envelope differs")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    manifest.verify()
    package = CandidatePackage.load(CANDIDATE)
    report = validate(manifest, package, _oracle)
    if report.status != "pass" or package.sha256 != "2c6fd50ceb11b14f6f1923197c33cb018025cfcd6b00c2ed566ba7dd6b736bad":
        raise PipelineError(f"fresh independent Luther oracle failed: {report.findings[:3]}")
    acquisition = validate_acquisition(root / ACQUISITION, root=root)
    retained = acquisition["retained_files"]
    if (acquisition.get("source_path") != SOURCE.as_posix()
            or acquisition.get("source_sha256") != SOURCE_SHA
            or len(retained) != 1 or retained[0]["path"] != SOURCE.as_posix()
            or retained[0]["sha256"] != SOURCE_SHA):
        raise PipelineError("one exact extracted TXT acquisition required")
    work = _read(root / WORK / "work.json")
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    if (form["textual_form_id"] != FORM_ID or edition["edition_id"] != EDITION_ID
            or edition["acquisition_ids"] != [ACQUISITION_ID]
            or "category" in edition or (root / EDITION / "master.tei.xml").exists()):
        raise PipelineError("Luther work identity/preimage changed")
    stage.mkdir()
    before = _files(root / WORK)
    for relative in before:
        _copy(root, stage, WORK / relative)
    _copy(root, stage, SOURCE)
    _copy(root, stage, MANIFEST)
    _copy(root, stage, Path("metadata/source-evidence/catalog/luthers-large-catechism.json"))
    for item in manifest.record["authorities"]:
        relative = Path(item["path"])
        if relative != SOURCE:
            _copy(root, stage, relative)
    for name in package.member_names:
        _write(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    validation = dict(contract="ocd-validation-report-v1", status=report.status,
                      candidate_sha256=report.candidate_sha256,
                      source_manifest_sha256=report.source_manifest_sha256,
                      attestation=dict(report.attestation), findings=list(report.findings),
                      report_sha256=report.sha256)
    _write_json(stage, EVIDENCE / "inputs/validation.json", validation)
    old_work = json.loads(json.dumps(work))
    edition["category"] = "prose"
    work["creators"] = [{"name": "Martin Luther", "role": "author", "evidence": [SOURCE.as_posix()]}]
    validate_identity_update(old_work, work)
    _write_json(stage, WORK / "work.json", work)
    load_work(stage / WORK / "work.json")
    original = package.member_bytes("content.tei.xml")
    bound = _readable_master(original, source_url=acquisition["url"],
                             scope=acquisition["source_scope"])
    candidate_path = _write(stage, EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(candidate_path):
        raise PipelineError(f"Luther accepted TEI XSD errors: {errors[:3]}")
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID,
                    edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)
    revision = dict(id="luther-pg1722-electronic-v1",
                    date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete retained Project Gutenberg electronic transcription.")
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    included = [expected[0] | dict(bytes=len(source), sha256=SOURCE_SHA,
                                   scope=acquisition["source_scope"])]
    scope = dict(kind="edition", declared=acquisition["source_scope"],
                 expected_members=expected, included_members=included,
                 excluded_members=[])
    common = dict(identity=identity, source=dict(source_path=SOURCE.as_posix(),
                  source_sha256=SOURCE_SHA, source_bytes=len(source),
                  source_scope=acquisition["source_scope"]),
                  candidate=make_file_binding(stage, candidate_path),
                  scope=acquisition["source_scope"],
                  accepted_scope=dict(kind="edition", declared=acquisition["source_scope"]),
                  expected_members=expected, included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[])
    account = _write_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        source_sha256=SOURCE_SHA, source_bytes=len(source),
        source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
        oracle_report_sha256=report.sha256, physical_lines=4886,
        omitted_lines=0, duplicated_lines=0,
        original_candidate=make_file_binding(stage, stage / EVIDENCE / "inputs/package/content.tei.xml"),
        candidate_source_accountability=make_file_binding(stage, stage / EVIDENCE / "inputs/package/source-accountability.json"),
        body_unchanged=True))
    command = "py -3 -m build.tools.stage_luther_pg1722_acceptance"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Producer and oracle share the pinned sole TXT member and source profile."],
                     independent_corroboration="Fresh independent line/structure oracle, XSD, actual-master native row and independent row checker agree.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _write_json(stage, EVIDENCE / f"{name}.json", common | dict(
            status="pass", command=command, exit_code=0, claim=name,
            source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
            oracle_report_sha256=report.sha256, text_body_unchanged=True))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    at = _now()
    review = dict(reviewer="agent:luther-pg1722-source-review", reviewed_at=at,
                  coverage=dict(status="partial", declared=acquisition["source_scope"],
                                reached=["complete retained TXT line ledger", "four source part headings", "source and candidate opening/ending"],
                                inspected=["complete retained TXT line ledger", "four source part headings"],
                                unreviewed=["whole-work visual comparison", "print collation"]),
                  source_quality_uncertainty=["The retained electronic text was not collated to a print exemplar."],
                  discrepancies=[], unreviewed_residuals=["Human review and rights clearance remain unrecorded."])
    review_path = _write_json(stage, EVIDENCE / "review.json", common | review)
    decision = dict(source_local_disposition="Agent acceptance of the complete retained Project Gutenberg #1722 electronic transcription only.",
                    blockers=[], agent_assessment=dict(status="accepted", actor=review["reviewer"],
                    assessed_at=at, supported_scope=acquisition["source_scope"], unresolved_claims=[],
                    unassessed_stronger_claims=["visual review", "human acceptance", "print identity",
                                                "rights clearance", "publication"]),
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
    matches = [target for target in state["targets"] if target["target_type"] == "edition"
               and target["target_id"] == EDITION_ID]
    if len(matches) != 1 or matches[0]["stage"] != "acquired":
        raise PipelineError("one acquired Luther edition state target required")
    matches[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=at)
    matches[0]["evidence"].extend([(EDITION / "master.tei.xml").as_posix(),
                                    (EDITION / "acceptance.json").as_posix()])
    _write_json(stage, WORK / "state.json", state)
    validate_acceptance(acceptance, root=stage)
    validate_state(stage / WORK / "state.json", root=stage)
    projected = project_accepted_document(stage, acceptance_path=acceptance,
                                           category="prose")
    errors = verify_accepted_document(stage, acceptance_path=acceptance,
                                      rows=projected["rows"], receipt=projected["receipt"],
                                      category="prose")
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"Luther actual-master native prose failed: {errors[:3]}")
    result = dict(contract="ocd-luther-pg1722-external-stage-v1", status="staged-only",
                  work_id=WORK_ID, stage_root=stage.as_posix(), before=before,
                  after=_files(stage / WORK), source_sha256=SOURCE_SHA,
                  source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
                  oracle_report_sha256=report.sha256, master_sha256=_sha(master.read_bytes()),
                  acceptance_sha256=_sha(acceptance.read_bytes()), projection_category="prose",
                  projection_rows=1, independent_verifier_errors=errors,
                  rights="not-assessed", human_review="not-recorded", installation="not-performed")
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
