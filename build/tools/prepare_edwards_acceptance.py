"""Prepare, without installing, the exact Edwards CCEL electronic witness."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.reconstruction.contract import CandidatePackage
from ocd_kernel.tei.acceptance import (
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/edwards-religious-affections")
EDITION = WORK / "forms/edwards-religious-affections-english/editions/ccel-thml-electronic-witness"
ACQUISITION = EDITION / "acquisitions/ccel-thml-religious-affections.json"
IDENTITY = dict(work_id="edwards-religious-affections",
                textual_form_id="edwards-religious-affections-english",
                edition_id="ccel-thml-electronic-witness",
                acquisition_id="ccel-thml-religious-affections")
SOURCE = Path("raw/ccel/edwards/affections.xml")
MANIFEST = Path("sources/structured-text/edwards-religious-affections/lib055/37c-142.source-manifest.json")
TICKET = Path("plans/2026-08-31-sample-first-library-verification/issues/37c-142-edwards-religious-affections.md")
REPORT = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-142.md")
RECEIPT = REPORT.with_name("37c-142-receipt.json")
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/37c-142-edwards-religious-affections-20260918-v1")
CVW = CANDIDATE.with_name(CANDIDATE.name + "-cvw-session")
CAPTURES = {0: ("opening", "1fc352472b4373fedfeb01fdbe92f9e948d4ca8a7eca0c94449be0b931c7f86b"),
            1: ("middle-segment-1", "dbfc825848b450d0f13294390cc94378269e08ace397eb75be1fdb96986359ae"),
            2: ("footnote-segment-2", "5484262c5a0517b943c064c7ab956297b85823187f17f59696e5b7b4976ef331"),
            18: ("index-start-segment-18", "c2f67f9332c06a52695d37ecaad066fc2332ec9342ce2744076134dd9a252508"),
            19: ("ending-segment-19", "233544bef14f9af3406d640301548633c6b7e3e8c322f78ea0ca235fb7d9dcd7")}
SOURCE_SHA = "2ffd4300ada5d0cc5b3929ed5b61ed0e1053042a065419ee35943facc79738ce"
MANIFEST_SHA = "5f4656c60660df46d3a146f61d0e994f6fdbb0155da4f100b39de3a7ec549a6f"
PACKAGE_SHA = "eb581ab08a75723b0a9697b588a60fc3454c517020d197e716bf3dbd7e20567b"
TEI_SHA = "07dbc107d16a21cc07ace5c7359acb992c5c0641ce1e3b0c1ae7134fcd5207a3"
VALIDATION_SHA = "d42227d89fb3134462fc5fd6bc6f46b1bf6990c896669f125a2427346f7ed10d"
CVW_SESSION_SHA = "ce5ea812ddfaeccd64a2b5c2fe26ef418ceb16ac5ae1c5dc90f1dd6daf0088bb"
SCOPE = "complete retained CCEL ThML electronic publication of A Treatise Concerning Religious Affections"
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"required Edwards evidence is missing: {path}") from exc
    if expected is not None and _sha(content) != expected:
        raise PipelineError(f"Edwards evidence SHA-256 mismatch: {path}")
    return content


def _json(content: bytes, label: str) -> dict:
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"invalid Edwards JSON: {label}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"Edwards JSON is not an object: {label}")
    return value


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def _copy(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def _check_stage(root: Path, stage: Path) -> Path:
    stage = stage.absolute()
    if stage.exists():
        raise PipelineError(f"Edwards staging root must be fresh: {stage}")
    resolved = stage.resolve()
    protected = (root.resolve(), CANDIDATE.resolve())
    if any(resolved == area or area in resolved.parents or resolved in area.parents
           for area in protected):
        raise PipelineError("Edwards staging root overlaps checkout or reviewed candidate")
    if not stage.parent.is_dir() or stage.parent.is_symlink():
        raise PipelineError("Edwards staging parent must be an existing ordinary directory")
    return stage


def _preflight(root: Path) -> tuple[dict, dict, dict[str, bytes], bytes]:
    """Check inherited source, package and bounded pixels before making a stage."""
    source = _read(resolve_repo_path(root, SOURCE.as_posix()), SOURCE_SHA)
    if len(source) != 1183960:
        raise PipelineError("Edwards retained source byte count changed")
    manifest = _json(_read(root / MANIFEST, MANIFEST_SHA), "source manifest")
    acquisition = _json(_read(root / ACQUISITION), "acquisition")
    member = acquisition.get("retained_files", [])
    if (manifest.get("work_id") != IDENTITY["work_id"]
            or acquisition.get("acquisition_id") != IDENTITY["acquisition_id"]
            or acquisition.get("edition_id") != IDENTITY["edition_id"]
            or len(member) != 1
            or any(member[0].get(key) != value for key, value in
                   (("path", SOURCE.as_posix()), ("bytes", len(source)), ("sha256", SOURCE_SHA)))):
        raise PipelineError("Edwards source manifest or acquisition identity changed")
    receipt = _json(_read(root / RECEIPT), "ticket receipt")
    reviewed = receipt.get("current_evidence", {})
    current = reviewed.get("candidate", {})
    cvw = reviewed.get("cvw", {})
    if (current.get("manifest_sha256") != PACKAGE_SHA
            or current.get("content_tei_sha256") != TEI_SHA
            or current.get("validation_sha256") != VALIDATION_SHA
            or cvw.get("session_receipt_sha256") != CVW_SESSION_SHA
            or cvw.get("targeted_segments_of_20") != list(CAPTURES)
            or cvw.get("agent_visually_inspected") is not True
            or cvw.get("exhaustive_visual_coverage") is not False):
        raise PipelineError("Edwards ticket receipt no longer binds the exact candidate and review")
    ticket = _read(root / TICKET)
    report = _read(root / REPORT)
    for anchor in (SOURCE_SHA, MANIFEST_SHA, PACKAGE_SHA, TEI_SHA):
        if anchor.encode() not in report:
            raise PipelineError(f"Edwards report lacks exact evidence anchor: {anchor}")
    package = CandidatePackage.load(CANDIDATE / "package")
    validation = _json(_read(CANDIDATE / "validation.json", VALIDATION_SHA), "validation")
    original = package.member_bytes("content.tei.xml")
    if (package.sha256 != PACKAGE_SHA or _sha(original) != TEI_SHA
            or package.manifest.get("source_manifest", {}).get("sha256") != MANIFEST_SHA
            or validation.get("status") != "pass" or validation.get("findings") != []
            or validation.get("candidate_sha256") != PACKAGE_SHA
            or validation.get("source_manifest_sha256") != MANIFEST_SHA
            or validation.get("attestation", {}).get("source_sha256") != SOURCE_SHA):
        raise PipelineError("Edwards candidate or validation differs from the reviewed pair")
    session = _json(_read(CVW / f"{cvw['session_id']}.receipt.json", CVW_SESSION_SHA), "CVW session")
    if session.get("session", {}).get("candidate_sha256") != [PACKAGE_SHA]:
        raise PipelineError("Edwards CVW session candidate differs")
    files = {"ticket.md": ticket, "report.md": report, "receipt.json": _read(root / RECEIPT),
             "source-manifest.json": _read(root / MANIFEST, MANIFEST_SHA),
             "validation.json": _read(CANDIDATE / "validation.json", VALIDATION_SHA),
             "cvw/session-receipt.json": _read(CVW / f"{cvw['session_id']}.receipt.json", CVW_SESSION_SHA)}
    files.update({f"package/{name}": package.member_bytes(name) for name in package.member_names})
    frame_records = cvw.get("capture_frames", [])
    if len(frame_records) != len(CAPTURES):
        raise PipelineError("Edwards CVW receipt has incomplete frame inventory")
    for segment, (suffix, expected_frame) in CAPTURES.items():
        item = next((entry for entry in frame_records if entry.get("segment") == segment), None)
        directory = CANDIDATE.with_name(CANDIDATE.name + "-cvw-" + suffix)
        if (item is None or item.get("bundle") != directory.name
                or item.get("frame_sha256") != expected_frame):
            raise PipelineError(f"Edwards CVW segment {segment} differs from ticket receipt")
        capture_bytes = _read(directory / "capture.json")
        capture = _json(capture_bytes, f"CVW capture {segment}")
        if (capture.get("session", {}).get("candidate_sha256") != [PACKAGE_SHA]
                or f"source-{MANIFEST_SHA}" not in capture.get("browser_state", {}).get("route", "")
                or capture.get("files", {}).get("frame.png") != expected_frame
                or capture.get("acceptance") != "not-established"):
            raise PipelineError(f"Edwards CVW segment {segment} does not bind the exact pair")
        for name, digest in capture["files"].items():
            files[f"cvw/segment-{segment}/{name}"] = _read(directory / name, digest)
        files[f"cvw/segment-{segment}/capture.json"] = capture_bytes
    return receipt, acquisition, files, source


def prepare(root: Path, stage: Path) -> Path:
    root = root.resolve(strict=True)
    stage = _check_stage(root, stage)
    receipt, acquisition, files, source_bytes = _preflight(root)
    stage.mkdir()
    evidence = stage / WORK / "integration/ccel-thml-agent-handoff"
    for name, content in files.items():
        _copy(stage, evidence.relative_to(stage) / "inputs" / name, content)
    for relative in (WORK / "work.json", WORK / "state.json", ACQUISITION, TICKET, REPORT):
        _copy(stage, relative, _read(root / relative))
    _copy(stage, SOURCE, source_bytes)
    _copy(stage, MANIFEST, files["source-manifest.json"])
    original = files["package/content.tei.xml"]
    member = acquisition["retained_files"][0]
    source = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                  source_bytes=len(source_bytes), source_scope=member["scope"])
    now = datetime.now(timezone.utc)
    revision = dict(id="edwards-ccel-thml-reviewed-header-v1", date=now.date().isoformat(),
                    note="Bind accepted electronic-witness identity in the header; reviewed TEI text unchanged.")
    derived = bind_reviewed_header(
        original, expected_sha256=TEI_SHA, identity=IDENTITY,
        source=source, source_url=acquisition["url"],
        declared_scope=SCOPE, revision=revision)
    if original.split(b"</teiHeader>", 1)[1] != derived.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Edwards header derivation altered reviewed TEI text")
    candidate = _copy(stage, evidence.relative_to(stage) / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"derived Edwards TEI failed vendored XSD: {errors}")
    included = [{key: member[key] for key in ("path", "bytes", "sha256", "scope")} | {"position": 1}]
    scope = dict(kind="edition", declared=SCOPE,
                 expected_members=[dict(path=SOURCE.as_posix(), position=1)],
                 included_members=included, excluded_members=[])
    common = dict(identity=IDENTITY, source=source, candidate=make_file_binding(stage, candidate),
                  scope=SCOPE, accepted_scope=dict(kind="edition", declared=SCOPE),
                  expected_members=scope["expected_members"], included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[])
    account = evidence / "source-accounting.json"
    account_sha = _sha(files["package/source-accountability.json"])
    _write(account, common | dict(scope=source["source_scope"], source_sha256=SOURCE_SHA, source_bytes=len(source_bytes),
                                  original_accountability_sha256=account_sha))
    bindings = {name: make_file_binding(stage, evidence / "inputs" / name) for name in files}
    details = {
        "validation": dict(status="pass", findings=[], sidecar=bindings["validation.json"]),
        "accounting": dict(source_sha256=SOURCE_SHA, original_accountability_sha256=account_sha,
                           original_member=bindings["package/source-accountability.json"]),
        "fidelity": dict(original_tei_sha256=TEI_SHA, original_text_sha256=_sha(original.split(b"</teiHeader>", 1)[1]),
                         derived_text_sha256=_sha(derived.split(b"</teiHeader>", 1)[1]), header_only_derivation=True),
        "reproducibility": dict(original_package_sha256=PACKAGE_SHA,
                                historical_focused_tests=receipt["current_evidence"]["focused_tests"],
                                no_reconstruction_performed=True),
        "schema": dict(vendored_xsd="ocd_kernel/tei/vendor/xsd/tei_all.xsd", validation_errors=[]),
        "closure": dict(source_manifest_sha256=MANIFEST_SHA, original_package_sha256=PACKAGE_SHA,
                        evidence_files=bindings),
    }
    technical = dict(producer=dict(id="edwards-religious-affections-lib055-source-to-tei"),
                     checker=dict(id="edwards-religious-affections-independent-retained-byte-oracle"),
                     shared_assumptions=["Producer and oracle share the retained source bytes and source manifest; visual coverage is five of twenty segments."],
                     independent_corroboration="Historical independent source accounting, mutation checks, deterministic reproduction, passing validation and five exact-pair CVW captures; unchanged TEI text in this header derivation.")
    command = "py -3 -m build.tools.prepare_edwards_acceptance --stage <fresh-external-root>"
    for name in PROOFS:
        path = evidence / f"{name}.json"
        _write(path, common | dict(status="pass", command=command, exit_code=0, details=details[name]))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    loci = list(CAPTURES)
    captured_at = max(_json(files[f"cvw/segment-{i}/capture.json"], "capture")["captured_at"]
                      for i in loci)
    review = dict(reviewer="historical:37c-142-five-segment-agent-CVW",
                  reviewed_at=captured_at.replace("+00:00", "Z"),
                  coverage=dict(status="partial", declared=SCOPE, reached=[f"segment-{i}" for i in loci],
                                inspected=[f"segment-{i}" for i in loci],
                                unreviewed=[f"segment-{i}" for i in range(20) if i not in CAPTURES]),
                  source_quality_uncertainty=["Underlying print transcription witness is unknown.",
                                              "CCEL proofreading and original digitization history are unknown."],
                  discrepancies=[],
                  unreviewed_residuals=["Five of twenty segments were visually inspected; no exhaustive proofreading or page-image collation was performed.",
                                       "The indented note at iv.i-p11.1 is an intentional CVW presentation, not a TEI omission."])
    _write(evidence / "review.json", common | review | dict(
        historical_cvw_session=bindings["cvw/session-receipt.json"],
        capture_bindings={str(i): bindings[f"cvw/segment-{i}/capture.json"] for i in loci},
        no_new_pixel_review=True,
        review_basis="Historical five-segment pixel review applies to identical retained source and original TEI bytes; derived tei:text bytes are identical."))
    decision = dict(source_local_disposition="Evidence-backed agent acceptance of the exact retained CCEL ThML electronic witness only.",
                    blockers=[], agent_assessment=dict(status="accepted", actor="agent:edwards-ccel-thml-review",
                    assessed_at=now.isoformat().replace("+00:00", "Z"), supported_scope=SCOPE,
                    unassessed_stronger_claims=["human acceptance", "rights clearance", "print transcription lineage",
                                                "page-image collation", "exhaustive proofreading", "release", "publication",
                                                "corrected-text eligibility"], unresolved_claims=[]),
                    human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(stage, identity=IDENTITY, candidate_path=candidate,
             source_accounting_path=account, scope=scope, technical=technical,
             review=review | dict(report_path=evidence / "review.json"),
             representation_revision=revision, decision=decision)
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    return acceptance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(ROOT, args.stage))


if __name__ == "__main__":
    main()
