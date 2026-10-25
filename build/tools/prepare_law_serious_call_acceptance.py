"""Prepare agent acceptance for the retained CCEL Serious Call electronic witness.

The September 13 package is historical: its manifest bytes are unavailable in
the current checkout. This helper builds a new package from the current manifest
and writes only to a fresh caller-selected staging root.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from build.tools.reconstruct_candidate import run as reconstruct_candidate
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.reconstruction import SourceManifest
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
WORK = Path("library/works/law-serious-call")
EDITION = WORK / "forms/law-english/editions/ccel-thml-witness"
ACQUISITION = EDITION / "acquisitions/ccel-thml-serious-call.json"
MANIFEST = Path("sources/structured-text/law-serious-call/source-manifest.json")
SOURCE = Path("raw/ccel/law/serious_call.xml")
TICKET = Path("plans/2026-08-31-sample-first-library-verification/issues/37c-241-law-serious-call.md")
REPORT = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-241.md")
FRAMES = REPORT.parent / "37c-241-law-serious-call-cvw-cdp-20260913/10-route-bound-cvw-frames.json"
OLD = Path("D:/Library/Open Christian Data/candidate-reviews/37c-241-law-serious-call-20260913")
IDENTITY = dict(work_id="law-serious-call", textual_form_id="law-english",
                edition_id="ccel-thml-witness", acquisition_id="ccel-thml-serious-call")
SOURCE_SHA = "edc2bf6021f36bb7e42e1feb819c37492f920595e05ed31e22d52e7caa12c2bd"
MANIFEST_SHA = "9871fd284891960a8b8771c24fc4a4690d75a25613615adea89605c602142285"
OLD_MANIFEST_SHA = "0a643aae88b73480640d2b1f8528beb7849371c35eeb659b2354ed13bf6c44dc"
OLD_PACKAGE_SHA = "913441808117fb14a4ab2e2dd639cc693b3a56c5a174d38d3e979854b0ff2bcf"
OLD_VALIDATION_SHA = "3bad0ad74975bcdc5ef6fe5fc4b5abd8755412eb56bed7bd77813804b343d99c"
FRAMES_SHA = "32f84702dcdd90e6776276805d5b277669c8afae434a7ef456a3ef1ac7054595"
TEI_SHA = "75a4bba4fe81ed770068df998fac83f1422273c57c4de3260d41e57ecae82671"
ACCOUNT_SHA = "955fcce7b4f008817d01dec3eb5a5d16b0d725e23370c921dbdd5fb9ff2b02d7"
SCOPE = "complete retained CCEL ThML electronic witness for A Serious Call to a Devout and Holy Life; no print-edition collation"
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"required Law evidence is missing: {path}") from exc
    if expected is not None and _sha(content) != expected:
        raise PipelineError(f"Law evidence SHA-256 mismatch: {path}")
    return content


def _json(content: bytes, label: str) -> dict:
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"invalid Law evidence JSON: {label}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"Law evidence is not an object: {label}")
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
        raise PipelineError(f"Law staging root must be fresh: {stage}")
    resolved = stage.resolve()
    protected = (root.resolve(), OLD.resolve())
    if any(resolved == area or area in resolved.parents or resolved in area.parents for area in protected):
        raise PipelineError("Law staging root overlaps the checkout or candidate library")
    if not stage.parent.is_dir() or stage.parent.is_symlink():
        raise PipelineError("Law staging parent must be an existing ordinary directory")
    return stage


def _visual_evidence(root: Path) -> tuple[dict, dict[str, bytes]]:
    """Bind old CVW pixels to old package, then reuse only identical source/TEI."""
    receipt = _json(_read(root / FRAMES, FRAMES_SHA), "Law CVW frame receipt")
    old = CandidatePackage.load(OLD / "package")
    validation = _json(_read(OLD / "validation.json", OLD_VALIDATION_SHA), "old Law validation")
    provenance = _json(old.member_bytes("provenance.json"), "old Law provenance")
    source = provenance.get("scope", {})
    review = receipt.get("agent_visual_review", {})
    frames = receipt.get("frames", [])
    if (old.sha256 != OLD_PACKAGE_SHA or old.manifest.get("source_manifest", {}).get("sha256") != OLD_MANIFEST_SHA
            or _sha(old.member_bytes("content.tei.xml")) != TEI_SHA
            or validation.get("candidate_sha256") != OLD_PACKAGE_SHA
            or validation.get("attestation", {}).get("source_sha256") != SOURCE_SHA
            or validation.get("status") != "pass" or validation.get("findings") != []
            or source.get("source_sha256") != SOURCE_SHA
            or receipt.get("source_sha256") != OLD_MANIFEST_SHA
            or receipt.get("candidate_package_sha256") != OLD_PACKAGE_SHA
            or receipt.get("contract") != "ocd-source-to-tei-cvw-route-bound-frame-set-v1"
            or receipt.get("frames_reviewed_by_agent") is not True
            or review.get("human_acceptance") is not False
            or len(frames) != 12
            or len(review.get("reviewed_frame_ids", [])) != 12):
        raise PipelineError("historical Law CVW evidence does not bind the exact old source/TEI pair")
    images: dict[str, bytes] = {}
    for frame in frames:
        name = frame.get("file")
        if (not isinstance(name, str) or Path(name).name != name or not name.endswith(".png")
                or name in images or frame.get("id") not in review["reviewed_frame_ids"]):
            raise PipelineError("Law CVW frame inventory is invalid")
        content = _read(root / FRAMES.parent / name, frame.get("sha256"))
        if len(content) != frame.get("bytes") or not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise PipelineError(f"Law CVW frame is not the recorded PNG: {name}")
        images[name] = content
    if {frame["id"] for frame in frames} != set(review["reviewed_frame_ids"]):
        raise PipelineError("Law CVW reviewed frame set differs from captured set")
    return receipt, images


def prepare(root: Path, stage: Path) -> Path:
    root = root.resolve(strict=True)
    stage = _check_stage(root, stage)
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    manifest.verify()
    if manifest.sha256 != MANIFEST_SHA or manifest.record.get("work_id") != IDENTITY["work_id"]:
        raise PipelineError("current Law source manifest identity or bytes changed")
    source_bytes = _read(resolve_repo_path(root, SOURCE.as_posix()), SOURCE_SHA)
    if len(source_bytes) != 807207:
        raise PipelineError("retained Law source byte count changed")
    acquisition = _json(_read(root / ACQUISITION), "Law acquisition")
    retained = acquisition.get("retained_files", [])
    if (acquisition.get("acquisition_id") != IDENTITY["acquisition_id"]
            or acquisition.get("edition_id") != IDENTITY["edition_id"]
            or len(retained) != 1
            or any(retained[0].get(key) != value for key, value in
                   (("path", SOURCE.as_posix()), ("bytes", len(source_bytes)), ("sha256", SOURCE_SHA)))):
        raise PipelineError("Law acquisition does not bind the exact single CCEL member")
    historical, images = _visual_evidence(root)
    _read(root / TICKET)
    report_text = _read(root / REPORT)
    if SOURCE_SHA.encode() not in report_text or TEI_SHA.encode() not in report_text:
        raise PipelineError("Law historical review does not identify the exact source and TEI")

    evidence = stage / WORK / "integration/ccel-thml-current-manifest-agent-handoff"
    evidence.mkdir(parents=True)
    current_root = evidence / "current-candidate"
    summary = reconstruct_candidate(
        manifest=MANIFEST.as_posix(), destination=str(current_root), repository_root=str(root)
    )
    package = CandidatePackage.load(current_root / "package")
    checked = _json(_read(current_root / "validation.json"), "current Law validation")
    original = package.member_bytes("content.tei.xml")
    if (summary.get("status") != "pass" or checked.get("status") != "pass"
            or checked.get("findings") != []
            or checked.get("candidate_sha256") != package.sha256
            or checked.get("source_manifest_sha256") != MANIFEST_SHA
            or checked.get("attestation", {}).get("source_sha256") != SOURCE_SHA
            or _sha(original) != TEI_SHA
            or _sha(package.member_bytes("source-accountability.json")) != ACCOUNT_SHA):
        raise PipelineError("current Law package differs from the reviewed source/TEI")
    worker = subprocess.run(
        [sys.executable, "-m", "build.tools.reconstruct_candidate", "--manifest", MANIFEST.as_posix(),
         "--destination", str(evidence / "reproduced-candidate"), "--repository-root", str(root)],
        cwd=root, check=True, capture_output=True, text=True,
    )
    reproduced = CandidatePackage.load(evidence / "reproduced-candidate/package")
    if (reproduced.sha256 != package.sha256
            or any(reproduced.member_bytes(name) != package.member_bytes(name) for name in package.member_names)):
        raise PipelineError("current Law package does not reproduce in a second process")

    for relative in (WORK / "work.json", WORK / "state.json", ACQUISITION, MANIFEST, TICKET, REPORT):
        _copy(stage, relative, _read(root / relative))
    _copy(stage, SOURCE, source_bytes)
    visual_receipt = _copy(stage, WORK / "integration/ccel-thml-current-manifest-agent-handoff/inputs/cvw/10-route-bound-cvw-frames.json",
                           _read(root / FRAMES, FRAMES_SHA))
    for name, content in images.items():
        _copy(stage, WORK / "integration/ccel-thml-current-manifest-agent-handoff/inputs/cvw" / name, content)
    for name in package.member_names:
        _copy(stage, WORK / "integration/ccel-thml-current-manifest-agent-handoff/inputs/package" / name,
              package.member_bytes(name))
    _copy(stage, WORK / "README.source.md", package.member_bytes("README.source.md"))
    _copy(stage, WORK / "integration/ccel-thml-current-manifest-agent-handoff/inputs/validation.json",
          _read(current_root / "validation.json"))
    _copy(stage, WORK / "integration/ccel-thml-current-manifest-agent-handoff/inputs/old-package-manifest.json",
          _read(OLD / "package/manifest.json"))
    _copy(stage, WORK / "integration/ccel-thml-current-manifest-agent-handoff/inputs/old-validation.json",
          _read(OLD / "validation.json", OLD_VALIDATION_SHA))

    source = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                  source_bytes=len(source_bytes), source_scope=retained[0]["scope"])
    now = datetime.now(timezone.utc)
    revision = dict(id="law-ccel-thml-reviewed-header-v1", date=now.date().isoformat(),
                    note="Acceptance identity and exact retained CCEL electronic witness bound in the header; reviewed TEI text unchanged.")
    derived = bind_reviewed_header(original, expected_sha256=TEI_SHA, identity=IDENTITY,
                                   source=source, source_url=acquisition["url"],
                                   declared_scope=SCOPE, revision=revision)
    if original.split(b"</teiHeader>", 1)[1] != derived.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Law header derivation changed reviewed TEI text")
    candidate = _copy(stage, WORK / "integration/ccel-thml-current-manifest-agent-handoff/candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"derived Law TEI failed vendored XSD: {errors}")

    included = [{key: retained[0][key] for key in ("path", "bytes", "sha256", "scope")} | {"position": 1}]
    scope = dict(kind="edition", declared=SCOPE, expected_members=[dict(path=SOURCE.as_posix(), position=1)],
                 included_members=included, excluded_members=[])
    binding = make_file_binding(stage, candidate)
    common = dict(identity=IDENTITY, source=source, candidate=binding, scope=SCOPE,
                  accepted_scope=dict(kind="edition", declared=SCOPE),
                  expected_members=scope["expected_members"], included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[])
    account = evidence / "source-accounting.json"
    _write(account, common | dict(scope=source["source_scope"],
                                  source_sha256=SOURCE_SHA, source_bytes=len(source_bytes),
                                  original_accountability_sha256=ACCOUNT_SHA,
                                  preserved_absent_toc_targets=2,
                                  source_date_conflict="1729 title page and Appendix A; 1728 Appendix B"))
    details = {
        "validation": dict(status=checked["status"], findings=checked["findings"],
                           current_package_sha256=package.sha256, current_manifest_sha256=MANIFEST_SHA,
                           validation_sidecar=make_file_binding(stage, evidence / "inputs/validation.json")),
        "accounting": dict(source_sha256=SOURCE_SHA, original_accountability_sha256=ACCOUNT_SHA,
                           absent_toc_targets=2, excluded_members=[]),
        "fidelity": dict(historical_tei_sha256=TEI_SHA, current_tei_sha256=_sha(original),
                         derived_text_sha256=_sha(derived.split(b"</teiHeader>", 1)[1]),
                         original_text_sha256=_sha(original.split(b"</teiHeader>", 1)[1]),
                         historical_source_sha256=SOURCE_SHA, current_source_sha256=_sha(source_bytes)),
        "reproducibility": dict(current_package_sha256=package.sha256,
                                second_process_package_sha256=reproduced.sha256,
                                second_process_stdout=worker.stdout.strip()),
        "schema": dict(vendored_xsd="ocd_kernel/tei/vendor/xsd/tei_all.xsd", validation_errors=[]),
        "closure": dict(current_manifest_sha256=MANIFEST_SHA, historical_manifest_sha256=OLD_MANIFEST_SHA,
                        historical_package_sha256=OLD_PACKAGE_SHA, current_package_sha256=package.sha256,
                        old_package_is_historical=True, visual_receipt=make_file_binding(stage, visual_receipt)),
    }
    command = "py -3 -m build.tools.prepare_law_serious_call_acceptance --stage <fresh-external-root>"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Producer and oracle share the retained CCEL bytes and source manifest; the historical visual sample is bounded."],
                     independent_corroboration="Current independent XML oracle, exact source accounting, mutation tests, second-process reproduction, and historical twelve-frame CVW sample for identical source and TEI bytes.")
    for name in PROOFS:
        path = evidence / f"{name}.json"
        _write(path, common | dict(status="pass", command=command, exit_code=0, details=details[name]))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    loci = historical["agent_visual_review"]["reviewed_frame_ids"]
    review = dict(reviewer="historical:37c-241-twelve-frame-agent-CVW",
                  reviewed_at=max(frame["captured_at_utc"] for frame in historical["frames"]),
                  coverage=dict(status="partial", declared=SCOPE, reached=loci, inspected=loci, unreviewed=[]),
                  source_quality_uncertainty=["CCEL Proofed marker is provider-supplied; no page-image or print collation was performed.",
                                              "Title-page and Appendix A 1729 conflict with Appendix B 1728."],
                  discrepancies=[],
                  unreviewed_residuals=["Twelve loci do not establish exhaustive whole-work visual proofreading.",
                                       "Two source-preserved navigation edges point to an absent toc; CVW correspondence was absent."])
    _write(evidence / "review.json", common | review | dict(
        historical_visual_receipt=make_file_binding(stage, visual_receipt),
        applicability="Retained source SHA-256 and original TEI SHA-256 are identical to the September 13 pair; the current package and validation have different hashes and are separately bound here. Header-only derivation preserves all bytes after teiHeader.",
        no_new_pixel_review=True))
    decision = dict(source_local_disposition="Evidence-backed agent acceptance of the exact retained CCEL ThML electronic witness only.",
                    blockers=[], agent_assessment=dict(status="accepted", actor="agent:law-ccel-thml-review",
                    assessed_at=now.isoformat().replace("+00:00", "Z"), supported_scope=SCOPE,
                    unassessed_stronger_claims=["human acceptance", "rights clearance", "print-edition identity",
                                                "page-image collation", "exhaustive visual proofreading", "publication"],
                    unresolved_claims=[]), human_decision=dict(status="not-recorded"))
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
