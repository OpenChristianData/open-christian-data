"""Prepare, without canonical installation, Watson's retained CCEL ThML witness."""

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
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/watson-ten-commandments")
EDITION = WORK / "forms/watson-ten-commandments-english/editions/watson-ten-commandments-ccel-thml"
ACQUISITION = EDITION / "acquisitions/watson-ten-commandments-ccel-retained.json"
IDENTITY = dict(
    work_id="watson-ten-commandments",
    textual_form_id="watson-ten-commandments-english",
    edition_id="watson-ten-commandments-ccel-thml",
    acquisition_id="watson-ten-commandments-ccel-retained",
)
SOURCE = Path("raw/ccel/watson/commandments.xml")
MANIFEST = Path("sources/structured-text/watson-ten-commandments/watson-ten-commandments.source-manifest.json")
TICKET = Path("plans/2026-08-31-sample-first-library-verification/issues/37c-318-watson-ten-commandments.md")
REPORT = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-318.md")
RECEIPT = REPORT.with_name("37c-318-receipt.json")
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/37c-318-watson-ten-commandments-20260919-v2")
CVW = Path("D:/Library/Open Christian Data/candidate-reviews/37c-318-watson-ten-commandments-cvw-20260919-v2")
SESSION_ID = "44658961be2342d08347420c197fa778"
SOURCE_SHA = "88f65cbe3a515841a14ecd7c982880b528a32c4420ac71169485ef54ccdb89d6"
MANIFEST_SHA = "c4239ccb247a19f238013069f748e9429654c0d6b9effb85ddf16f76585a9ced"
PACKAGE_SHA = "ef7003a9b1b33489e7095648af7838add4d904c983fa536883cf601ddba29077"
TEI_SHA = "533de6c802c7639d06409ea0d75e9df84eb69a655e4981d29ed91ab630342ca2"
VALIDATION_SHA = "6359537d1fd6b95cab253c0bf5ea8614ffe0c18365a1dcba33a912c853569ea4"
VALIDATION_REPORT_SHA = "2bf7194642786ca877a930b3c615ec10c6ba152a5be2a725ba86fd736a35e813"
SESSION_SHA = "a3ccc15bb41be1fdead66d34306bacf5a4e793815c386dc28c5daf4064d55438"
EVENTS_SHA = "d3fce0e79e1daa894f20e1b5bd4c691ec472d38ccf0735b60259fcd7841fb529"
CATALOG_SHA = "82329c4cb0e51c285a5aa16480d769433f43036be04b3f8ee6e24ef85f6d649a"
SCOPE = "The complete single retained ThML member, including the title page, four ordered content divisions, indexes, and source shell."
FRAMES = {
    "tenth-commandment-h3": (
        "iv.x-p0.1", "src-2195",
        "15464a92526acbef34951020643c8b61678d52a2afea507f6acbbef51c814cab",
        "500056870071568ea35142ca04ac83e0fa465b603651e0c08c52e4956e000207",
    ),
    "law-sin-h3": (
        "v.i-p0.1", "src-2293",
        "09bf9d01c24347cd999313e1d19029079d075f4b16fd2a64807b15fa2086a8e0",
        "54b9c3516323cbb77233ab56c15aff1258c186ab15f2993f8147441aba7fac2d",
    ),
}
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"required Watson evidence is missing: {path}") from exc
    if expected is not None and _sha(content) != expected:
        raise PipelineError(f"Watson evidence SHA-256 mismatch: {path}")
    return content


def _json(content: bytes, label: str) -> dict:
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"invalid Watson JSON: {label}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"Watson JSON is not an object: {label}")
    return value


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _copy(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def _check_stage(root: Path, stage: Path) -> Path:
    stage = stage.absolute()
    if stage.exists():
        raise PipelineError(f"Watson staging root must be fresh: {stage}")
    resolved = stage.resolve()
    for area in (root.resolve(), CANDIDATE.resolve(), CVW.resolve()):
        if resolved == area or area in resolved.parents or resolved in area.parents:
            raise PipelineError("Watson staging root overlaps protected source or checkout")
    if not stage.parent.is_dir() or stage.parent.is_symlink():
        raise PipelineError("Watson staging parent must be an existing ordinary directory")
    return stage


def _bind_existing_header(original: bytes, revision: dict[str, str], source_url: str) -> bytes:
    """Add only the missing revision binding to Watson's already-bound header."""
    header, separator, body = original.partition(b"</teiHeader>")
    if not separator:
        raise PipelineError("Watson candidate lacks a TEI header boundary")
    required = (
        f'<ptr target="{source_url}"/>',
        f'<idno type="sha256">{SOURCE_SHA}</idno>',
        f'<idno type="work_id">{IDENTITY["work_id"]}</idno>',
        f'<idno type="textual_form_id">{IDENTITY["textual_form_id"]}</idno>',
        f'<idno type="edition_id">{IDENTITY["edition_id"]}</idno>',
        f'<idno type="acquisition_id">{IDENTITY["acquisition_id"]}</idno>',
        f'<idno type="source_sha256">{SOURCE_SHA}</idno>',
        '<idno type="source_bytes">1100623</idno>',
        f'<note type="source-location">{SOURCE.as_posix()}</note>',
        f'<note type="source-scope">{SCOPE}</note>',
    )
    if (any(header.count(item.encode()) != 1 for item in required)
            or header.count(b"</bibl></sourceDesc>") != 1
            or b"representation_revision" in header
            or b"<revisionDesc" in header):
        raise PipelineError("Watson reviewed header differs from the expected source binding")
    idno = f'<idno type="representation_revision">{revision["id"]}</idno>'.encode()
    change = (f'<revisionDesc><change xml:id="{revision["id"]}" '
              f'when="{revision["date"]}">{revision["note"]}</change></revisionDesc>').encode()
    bound = header.replace(b"</bibl></sourceDesc>", idno + b"</bibl></sourceDesc>", 1)
    result = bound + change + separator + body
    if result.split(separator, 1)[1] != body:
        raise PipelineError("Watson header binding altered reviewed TEI text")
    return result

def _preflight(root: Path) -> tuple[dict, dict, dict[str, bytes], bytes]:
    """Bind the current v2 package and only its two v2 visual captures."""
    source = _read(resolve_repo_path(root, SOURCE.as_posix()), SOURCE_SHA)
    if len(source) != 1_100_623:
        raise PipelineError("Watson retained source byte count changed")
    manifest_bytes = _read(root / MANIFEST, MANIFEST_SHA)
    manifest = _json(manifest_bytes, "source manifest")
    acquisition = _json(_read(root / ACQUISITION), "acquisition")
    members = acquisition.get("retained_files", [])
    if (manifest.get("work_id") != IDENTITY["work_id"]
            or manifest.get("source_id") != "37c-318-watson-ten-commandments-retained-thml"
            or acquisition.get("acquisition_id") != IDENTITY["acquisition_id"]
            or acquisition.get("edition_id") != IDENTITY["edition_id"]
            or len(members) != 1
            or any(members[0].get(key) != value for key, value in (
                ("path", SOURCE.as_posix()), ("bytes", len(source)), ("sha256", SOURCE_SHA)
            ))):
        raise PipelineError("Watson source manifest or acquisition identity changed")
    receipt_bytes = _read(root / RECEIPT)
    receipt = _json(receipt_bytes, "ticket receipt")
    binding = receipt.get("current_binding", {})
    cvw = receipt.get("cvw", {})
    validation_binding = binding.get("validation", {})
    if (receipt.get("work_id") != IDENTITY["work_id"]
            or binding.get("source_manifest_sha256") != MANIFEST_SHA
            or binding.get("candidate_manifest_sha256") != PACKAGE_SHA
            or binding.get("candidate_content_sha256") != TEI_SHA
            or binding.get("candidate_status") != "nonaccepted"
            or validation_binding.get("validation_report_sha256") != VALIDATION_REPORT_SHA
            or validation_binding.get("validation_sidecar_sha256") != VALIDATION_SHA
            or validation_binding.get("status") != "pass"
            or validation_binding.get("findings") != []
            or cvw.get("session_id") != SESSION_ID
            or cvw.get("session_receipt_sha256") != SESSION_SHA
            or cvw.get("events_log_sha256") != EVENTS_SHA
            or cvw.get("status") != "two_locus_v2_pixel_recheck_complete"):
        raise PipelineError("Watson ticket receipt no longer binds the v2 candidate and review")
    ticket = _read(root / TICKET)
    report = _read(root / REPORT)
    for anchor in (SOURCE_SHA, MANIFEST_SHA, PACKAGE_SHA, TEI_SHA, SESSION_ID):
        if anchor.encode() not in report:
            raise PipelineError(f"Watson report lacks exact evidence anchor: {anchor}")
    package = CandidatePackage.load(CANDIDATE / "package")
    validation_bytes = _read(CANDIDATE / "validation.json", VALIDATION_SHA)
    validation = _json(validation_bytes, "validation")
    original = package.member_bytes("content.tei.xml")
    if (package.sha256 != PACKAGE_SHA or _sha(original) != TEI_SHA
            or package.manifest.get("status") != "nonaccepted"
            or package.manifest.get("source_manifest", {}).get("sha256") != MANIFEST_SHA
            or validation.get("status") != "pass" or validation.get("findings") != []
            or validation.get("report_sha256") != VALIDATION_REPORT_SHA
            or validation.get("candidate_sha256") != PACKAGE_SHA
            or validation.get("source_manifest_sha256") != MANIFEST_SHA
            or validation.get("attestation", {}).get("source_sha256") != SOURCE_SHA):
        raise PipelineError("Watson candidate or validation differs from the reviewed v2 pair")
    session_bytes = _read(CVW / "runtime" / f"{SESSION_ID}.receipt.json", SESSION_SHA)
    session = _json(session_bytes, "CVW session")
    if session.get("session", {}).get("candidate_sha256") != [PACKAGE_SHA]:
        raise PipelineError("Watson CVW session candidate differs")
    files = {
        "ticket.md": ticket, "report.md": report, "receipt.json": receipt_bytes,
        "source-manifest.json": manifest_bytes, "validation.json": validation_bytes,
        "cvw/session-receipt.json": session_bytes,
        "cvw/events.jsonl": _read(CVW / "runtime" / f"{SESSION_ID}.events.jsonl", EVENTS_SHA),
        "cvw/catalog.json": _read(CVW / "catalog/work_catalog.json", CATALOG_SHA),
    }
    files.update({f"package/{name}": package.member_bytes(name) for name in package.member_names})
    frames = cvw.get("frames", [])
    if len(frames) != len(FRAMES):
        raise PipelineError("Watson v2 visual receipt must contain exactly two frames")
    for name, (source_locus, tei_locus, capture_sha, frame_sha) in FRAMES.items():
        item = next((entry for entry in frames if entry.get("bundle") == name), None)
        directory = CVW / "captures" / name
        if (item is None or item.get("source_location") != source_locus
                or item.get("candidate_location") != tei_locus
                or item.get("capture_json_sha256") != capture_sha
                or item.get("frame_sha256") != frame_sha
                or item.get("pixels_inspected") is not True):
            raise PipelineError(f"Watson v2 visual receipt differs: {name}")
        capture_bytes = _read(directory / "capture.json", capture_sha)
        capture = _json(capture_bytes, f"CVW capture {name}")
        route = capture.get("browser_state", {}).get("route", "")
        if (capture.get("session", {}).get("candidate_sha256") != [PACKAGE_SHA]
                or capture.get("session", {}).get("session_id") != SESSION_ID
                or f"source-{MANIFEST_SHA}" not in route
                or f"tei-{PACKAGE_SHA}" not in route
                or f"leftLocation={source_locus}" not in route
                or f"rightLocation={tei_locus}" not in route
                or capture.get("files", {}).get("frame.png") != frame_sha
                or capture.get("acceptance") != "not-established"):
            raise PipelineError(f"Watson v2 CVW capture does not bind exact pair: {name}")
        for member_name, digest in capture["files"].items():
            files[f"cvw/{name}/{member_name}"] = _read(directory / member_name, digest)
        files[f"cvw/{name}/capture.json"] = capture_bytes
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
                  source_bytes=len(source_bytes), source_scope=acquisition["source_scope"])
    now = datetime.now(timezone.utc)
    revision = dict(id="watson-ten-commandments-ccel-thml-reviewed-header-v2",
                    date=now.date().isoformat(),
                    note="Bind the reviewed CCEL electronic witness; TEI text bytes remain unchanged.")
    derived = _bind_existing_header(original, revision, acquisition["url"])
    if original.split(b"</teiHeader>", 1)[1] != derived.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Watson header derivation altered reviewed TEI text")
    candidate = _copy(stage, evidence.relative_to(stage) / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"derived Watson TEI failed vendored XSD: {errors}")
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
    _write(account, common | dict(scope=acquisition["source_scope"], source_sha256=SOURCE_SHA,
                                  source_bytes=len(source_bytes), original_accountability_sha256=account_sha))
    bindings = {name: make_file_binding(stage, evidence / "inputs" / name) for name in files}
    details = {
        "validation": dict(status="pass", findings=[], sidecar=bindings["validation.json"]),
        "accounting": dict(source_sha256=SOURCE_SHA, original_accountability_sha256=account_sha,
                           original_member=bindings["package/source-accountability.json"]),
        "fidelity": dict(original_tei_sha256=TEI_SHA,
                         original_text_sha256=_sha(original.split(b"</teiHeader>", 1)[1]),
                         derived_text_sha256=_sha(derived.split(b"</teiHeader>", 1)[1]),
                         header_only_derivation=True),
        "reproducibility": dict(original_package_sha256=PACKAGE_SHA,
                                historical_focused_verification=receipt["focused_verification"],
                                no_reconstruction_performed=True),
        "schema": dict(vendored_xsd="ocd_kernel/tei/vendor/xsd/tei_all.xsd", validation_errors=[]),
        "closure": dict(source_manifest_sha256=MANIFEST_SHA,
                        original_package_sha256=PACKAGE_SHA, evidence_files=bindings),
    }
    technical = dict(
        producer=dict(id="ocd-watson-ten-commandments-selected-thml-to-tei"),
        checker=dict(id="ocd-watson-ten-commandments-selected-thml-independent-check"),
        shared_assumptions=["Producer and checker share retained source bytes and the source manifest; v2 visual inspection covers only two corrected-heading loci."],
        independent_corroboration="Historical source accounting, mutation checks, clean-process reproduction, passing exact-v2 validation, and two exact-v2 CVW frames; header derivation preserves all TEI text bytes.",
    )
    command = "py -3 -m build.tools.prepare_watson_ten_commandments_acceptance --stage <fresh-external-root>"
    for name in PROOFS:
        path = evidence / f"{name}.json"
        _write(path, common | dict(status="pass", command=command, exit_code=0,
                                   details=details[name]))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    loci = [f"{name}: {FRAMES[name][0]} -> {FRAMES[name][1]}" for name in FRAMES]
    review = dict(
        reviewer="historical:37c-318-two-locus-v2-agent-CVW",
        reviewed_at=max(item["captured_at_utc"] for item in receipt["cvw"]["frames"]),
        coverage=dict(status="partial", declared=SCOPE, reached=loci,
                      inspected=loci, unreviewed=["All other source and candidate loci in the retained member"]),
        source_quality_uncertainty=["Exact print witness and transcription lineage are unknown.",
                                    "Provider rights metadata has not been cleared for release."],
        discrepancies=[],
        unreviewed_residuals=["Only the two corrected headings were visually rechecked against v2; the 17 v1 frames are not v2 visual evidence.",
                             "No exhaustive proofreading or page-image collation was performed."],
    )
    _write(evidence / "review.json", common | review | dict(
        historical_cvw_session=bindings["cvw/session-receipt.json"],
        capture_bindings={name: bindings[f"cvw/{name}/capture.json"] for name in FRAMES},
        no_new_pixel_review=True,
        review_basis="Only the two caller-recorded v2 pixel inspections bind the exact retained source and v2 package; derived TEI text bytes are identical."))
    decision = dict(
        source_local_disposition="Evidence-backed agent acceptance of this exact retained CCEL ThML electronic witness only.",
        blockers=[],
        agent_assessment=dict(
            status="accepted", actor="agent:watson-ten-commandments-ccel-thml-review",
            assessed_at=now.isoformat().replace("+00:00", "Z"), supported_scope=SCOPE,
            unassessed_stronger_claims=["human acceptance", "rights clearance", "print witness and lineage",
                                        "page-image collation", "exhaustive proofreading", "release", "publication"],
            unresolved_claims=[],
        ),
        human_decision=dict(status="not-recorded"),
    )
    record = build_acceptance_record(
        stage, identity=IDENTITY, candidate_path=candidate,
        source_accounting_path=account, scope=scope, technical=technical,
        review=review | dict(report_path=evidence / "review.json"),
        representation_revision=revision, decision=decision,
    )
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
