"""Prepare a pending agent acceptance handoff for the exact 37c-298 v9 witness.

Only a fresh caller-selected staging root is written. This does not install a
master, change the reviewed package, or decide human acceptance or publication.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

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
WORK_ID = "strong-systematic-theology-vol-3"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms/strong-systematic-theology-vol-3-english/editions/project-gutenberg-45283"
IDENTITY = dict(
    work_id=WORK_ID,
    textual_form_id="strong-systematic-theology-vol-3-english",
    edition_id="project-gutenberg-45283",
    acquisition_id="strong-systematic-theology-vol-3-pg45283-retained",
)
ACQUISITION = EDITION / "acquisitions/strong-systematic-theology-vol-3-pg45283-retained.json"
SOURCE = Path("raw/gutenberg/pg45283.txt")
MANIFEST = Path("sources/strong-systematic-theology-vol-3/strong-systematic-theology-vol-3.source-manifest.json")
PROFILE = MANIFEST.with_name("strong-systematic-theology-vol-3.reconstruction-profile.json")
POLICY = MANIFEST.with_name("strong-systematic-theology-vol-3.validation-policy.json")
TICKET = Path("plans/2026-08-31-sample-first-library-verification/issues/37c-298-strong-systematic-theology-vol-3.md")
REPORT = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-298.md")
RECEIPT = REPORT.with_name("37c-298-receipt.json")
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/37c-298-strong-systematic-theology-vol-3-20260920-v9-source-marked-structure")
PACKAGE_SHA = "f65481dd67e5dc40f9546fa96e10c4de9c210c1ad5b035e1baf553a6968ffa1c"
TEI_SHA = "7d6f82584e978f588498c95a57306733ba97b025328f62023c0af7f802704ed6"
SOURCE_SHA = "103dc623072326111214078015dfbe8cb8f97197cba6e5e6faffede8bb1a20fe"
MANIFEST_SHA = "c0c90cb85fb4220651c605740bca808257db8150c425e7a4f2e42064f5ecf477"
PROFILE_SHA = "7bbd9a38820564da259a455ca7736f8c73b9568dcb7fa8bad2153b28661e9646"
POLICY_SHA = "b599dc479779d0681d7f7200b260b2ba5cb2bdf89697d58ab9bd3691037ac0bf"
RECEIPT_PROFILE_SHA = "7bbd9a38820564da259a455ca7736f8c73b9568dcb7ffa8bad2153b28661e9646"
RECEIPT_POLICY_SHA = "b599dc479779d0681dd7f7200b260b2ba5cb2bdf89697d58ab9bd3691037ac0bf"
VALIDATION_SHA = "e7d685e0f99fb5a765faaae6abe49ac8c4f0218f3320081c2b9e3b13ea2d06d3"
REPORT_SHA = "84be0c811fcf5cba976f93eabdbc4018504e59b629cd2976de1926a6ddc22572"
ACCOUNT_SHA = "3ec216a3421ab99bbae74906b8f20d5ce5dbb34f7ea724687e3e01dd5660543c"
SCOPE = "complete retained Project Gutenberg eBook #45283 electronic Volume 3 witness"
REVISION_ID = "strong-vol3-pg45283-reviewed-header-v1"
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"required Strong evidence is missing: {path}") from exc
    if expected is not None and _sha(content) != expected:
        raise PipelineError(f"Strong evidence SHA-256 mismatch: {path}")
    return content


def _json(content: bytes, label: str) -> dict:
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"invalid Strong evidence JSON: {label}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"Strong evidence is not an object: {label}")
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
        raise PipelineError(f"staging root must be fresh: {stage}")
    resolved = stage.resolve()
    protected = (root.resolve(), CANDIDATE.parent.parent.resolve(), CANDIDATE.resolve())
    if any(resolved == area or area in resolved.parents or resolved in area.parents for area in protected):
        raise PipelineError("staging root overlaps the checkout or durable candidate library")
    if not stage.parent.is_dir() or stage.parent.is_symlink():
        raise PipelineError("staging parent must be an existing ordinary directory")
    return stage


CORRECTION_HEADING = "2026-09-23 UTC profile and policy digest correction"


def _require_correction(document: str, *, label: str) -> None:
    if CORRECTION_HEADING not in document:
        raise PipelineError(f"dated Strong digest correction is missing from {label}")
    correction = document.split(CORRECTION_HEADING, 1)[1]
    for path, size, verified, recorded in (
        (PROFILE, 220661, PROFILE_SHA, RECEIPT_PROFILE_SHA),
        (POLICY, 1236, POLICY_SHA, RECEIPT_POLICY_SHA),
    ):
        if (path.as_posix() not in correction or f"{size:,}" not in correction
                or verified not in correction or recorded not in correction):
            raise PipelineError(f"dated Strong digest correction is incomplete in {label}: {path}")

def _preflight(root: Path) -> tuple[dict, dict, dict[str, bytes], list[dict]]:
    """Verify every inherited binding before creating a staging directory."""
    ticket = _read(root / TICKET).decode("utf-8")
    report_text = _read(root / REPORT).decode("utf-8")
    current_ticket = ticket.split("## 2026-09-20 v9 source-marked structure", 1)
    current_report = report_text.split("## 2026-09-20 v9 source-marked structure", 1)
    if (PROFILE_SHA not in ticket or POLICY_SHA not in ticket
            or "preserves the two malformed 65-character values" not in ticket
            or "#2026-09-23-utc-profile-and-policy-digest-correction" not in ticket):
        raise PipelineError("ticket does not link its verified digest correction")
    _require_correction(report_text, label="review report")
    if len(current_ticket) != 2 or len(current_report) != 2:
        raise PipelineError("current v9 ticket or report section is missing")
    for section in (current_ticket[1], current_report[1]):
        for exact in (CANDIDATE.as_posix(), PACKAGE_SHA, TEI_SHA, SOURCE_SHA, MANIFEST_SHA, VALIDATION_SHA):
            if exact not in section:
                raise PipelineError(f"current v9 ticket/report binding is missing: {exact}")

    receipt = _json(_read(root / RECEIPT), "37c-298 receipt")
    current = receipt.get("technical_completion_continuation_20260920", {})
    candidate = current.get("candidate", {})
    route = current.get("route", {})
    if (route.get("profile_sha256") != RECEIPT_PROFILE_SHA
            or route.get("policy_sha256") != RECEIPT_POLICY_SHA):
        raise PipelineError("preserved machine receipt digest transcription differs")
    if (receipt.get("ticket") != "37c-298" or receipt.get("work_id") != WORK_ID
            or candidate.get("path") != CANDIDATE.as_posix()
            or candidate.get("package_sha256") != PACKAGE_SHA
            or candidate.get("tei_sha256") != TEI_SHA
            or candidate.get("validation_report_sha256") != REPORT_SHA
            or candidate.get("validation_sidecar_sha256") != VALIDATION_SHA
            or candidate.get("status") != "nonaccepted"
            or current.get("focused_route_tests", {}).get("passed") != 31
            or current.get("focused_route_tests", {}).get("exit_code") != 0):
        raise PipelineError("machine receipt does not bind the current nonaccepted v9 package")

    source = _read(root / SOURCE, SOURCE_SHA)
    if len(source) != 1868543:
        raise PipelineError("retained Strong source byte count changed")
    acquisition = _json(_read(root / ACQUISITION), "Strong acquisition")
    retained = acquisition.get("retained_files")
    if (acquisition.get("acquisition_id") != IDENTITY["acquisition_id"]
            or acquisition.get("edition_id") != IDENTITY["edition_id"]
            or not isinstance(retained, list) or len(retained) != 1
            or any(retained[0].get(k) != v for k, v in
                   (("path", SOURCE.as_posix()), ("bytes", len(source)), ("sha256", SOURCE_SHA)))):
        raise PipelineError("Strong acquisition does not bind the sole retained PG 45283 member")
    manifest = _json(_read(root / MANIFEST, MANIFEST_SHA), "Strong source manifest")
    profile_bytes = _read(root / PROFILE, PROFILE_SHA)
    policy_bytes = _read(root / POLICY, POLICY_SHA)
    if len(profile_bytes) != 220661 or len(policy_bytes) != 1236:
        raise PipelineError("Strong profile or policy byte count differs from dated correction")
    authorities = {item.get("role"): item.get("sha256") for item in manifest.get("authorities", [])}
    if (authorities.get("complete-source-feature-profile") != PROFILE_SHA
            or authorities.get("independent-validation-policy") != POLICY_SHA):
        raise PipelineError("SourceManifest profile or policy authority differs from verified bytes")
    if manifest.get("source_id") != IDENTITY["acquisition_id"]:
        raise PipelineError("Strong source manifest ID changed")

    try:
        package = CandidatePackage.load(CANDIDATE / "package")
    except (OSError, ValueError) as exc:
        raise PipelineError("current Strong candidate package failed integrity") from exc
    if (package.sha256 != PACKAGE_SHA or package.manifest.get("source_id") != IDENTITY["acquisition_id"]
            or package.manifest.get("source_manifest", {}).get("sha256") != MANIFEST_SHA
            or package.manifest.get("status") != "nonaccepted"):
        raise PipelineError("candidate package does not bind current retained v9 route")
    _read(CANDIDATE / "package/content.tei.xml", TEI_SHA)
    _read(CANDIDATE / "package/source-accountability.json", ACCOUNT_SHA)
    validation = _json(_read(CANDIDATE / "validation.json", VALIDATION_SHA), "Strong validation")
    if (validation.get("contract") != "ocd-validation-report-v1" or validation.get("status") != "pass"
            or validation.get("findings") != [] or validation.get("candidate_sha256") != PACKAGE_SHA
            or validation.get("source_manifest_sha256") != MANIFEST_SHA
            or validation.get("report_sha256") != REPORT_SHA
            or validation.get("attestation", {}).get("source_sha256") != SOURCE_SHA
            or validation.get("attestation", {}).get("profile_sha256") != PROFILE_SHA
            or validation.get("attestation", {}).get("policy_sha256") != POLICY_SHA):
        raise PipelineError("current Strong validation is stale or not passing")

    visual = receipt.get("latest_cvw_visual_review", {})
    captures = visual.get("captures", [])
    if (visual.get("candidate") != CANDIDATE.as_posix()
            or visual.get("candidate_sha256") != PACKAGE_SHA
            or visual.get("tei_sha256") != TEI_SHA
            or visual.get("source_sha256") != SOURCE_SHA
            or visual.get("acceptance") != "not-established"
            or len(captures) != 3
            or [item.get("boundary") for item in captures] != ["opening", "middle", "ending"]):
        raise PipelineError("current CVW receipt does not bind the exact v9 pair")
    capture_files: dict[str, bytes] = {}
    for item in captures:
        directory = Path(item["directory"])
        if directory.parent != CANDIDATE.parent or not directory.name.startswith("37c-298-"):
            raise PipelineError("CVW capture directory is outside the current Strong evidence area")
        capture = _json(_read(directory / "capture.json", item["capture_sha256"]), item["boundary"])
        if (capture.get("contract") != "ocd-cvw-capture-bundle-v1"
                or capture.get("session", {}).get("candidate_sha256") != [PACKAGE_SHA]
                or capture.get("session", {}).get("session_id") != visual.get("session_id")
                or capture.get("browser_state", {}).get("route_digest") != item["route_digest"]
                or capture.get("files", {}).get("frame.png") != item["frame_sha256"]
                or capture.get("page_errors") != []
                or any(capture.get("targets", {}).get(side, {}).get("match_count") != 1
                       for side in ("left", "right"))):
            raise PipelineError(f"CVW {item['boundary']} capture does not bind the current v9 pair")
        for name, expected in capture["files"].items():
            capture_files[f"{item['boundary']}/{name}"] = _read(directory / name, expected)
        capture_files[f"{item['boundary']}/capture.json"] = _read(directory / "capture.json", item["capture_sha256"])

    files = {
        "ticket.md": _read(root / TICKET),
        "report.md": _read(root / REPORT),
        "receipt.json": _read(root / RECEIPT),
        "source-manifest.json": _read(root / MANIFEST, MANIFEST_SHA),
        "profile.json": _read(root / PROFILE, PROFILE_SHA),
        "policy.json": _read(root / POLICY, POLICY_SHA),
        "validation.json": _read(CANDIDATE / "validation.json", VALIDATION_SHA),
    }
    files.update({f"package/{name}": _read(CANDIDATE / "package" / name)
                  for name in package.member_names})
    files.update({f"cvw/{name}": content for name, content in capture_files.items()})
    return receipt, acquisition, files, captures


def prepare(root: Path, stage: Path) -> Path:
    root = root.resolve(strict=True)
    stage = _check_stage(root, stage)
    receipt, acquisition, files, captures = _preflight(root)
    stage.mkdir()
    evidence = stage / WORK / "integration/strong-vol3-pg45283-v9-agent-handoff"
    for name, content in files.items():
        _copy(stage, evidence.relative_to(stage) / "inputs" / name, content)
    _copy(stage, TICKET, files["ticket.md"])
    _copy(stage, REPORT, files["report.md"])
    _copy(stage, SOURCE, _read(root / SOURCE, SOURCE_SHA))
    for relative in (WORK / "work.json", WORK / "state.json", ACQUISITION):
        _copy(stage, relative, _read(root / relative))

    original = files["package/content.tei.xml"]
    source = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                  source_bytes=1868543, source_scope=acquisition["retained_files"][0]["scope"])
    now = datetime.now(timezone.utc)
    revision = dict(id=REVISION_ID, date=now.date().isoformat(),
                    note="Acceptance identity and exact retained electronic witness bindings added to the reviewed v9 header; TEI text unchanged.")
    derived = bind_reviewed_header(original, expected_sha256=TEI_SHA, identity=IDENTITY,
                                   source=source, source_url=acquisition["url"],
                                   declared_scope=SCOPE, revision=revision)
    if original.split(b"</teiHeader>", 1)[1] != derived.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Strong header derivation changed reviewed TEI text")
    candidate = _copy(stage, evidence.relative_to(stage) / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"derived Strong TEI failed vendored XSD: {errors}")

    member = acquisition["retained_files"][0]
    included = [{key: member[key] for key in ("path", "bytes", "sha256", "scope")} | {"position": 1}]
    scope = dict(kind="edition", declared=SCOPE,
                 expected_members=[dict(path=SOURCE.as_posix(), position=1)],
                 included_members=included, excluded_members=[])
    binding = make_file_binding(stage, candidate)
    common = dict(identity=IDENTITY, source=source, candidate=binding, scope=SCOPE,
                  accepted_scope=dict(kind="edition", declared=SCOPE),
                  expected_members=scope["expected_members"], included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[])
    account = evidence / "source-accounting.json"
    _write(account, common | dict(scope=source["source_scope"], source_sha256=SOURCE_SHA, source_bytes=len(_read(stage / SOURCE)),
                                  original_accountability_sha256=ACCOUNT_SHA))
    original_text_sha = _sha(original.split(b"</teiHeader>", 1)[1])
    evidence_bindings = {name: make_file_binding(stage, evidence / "inputs" / name)
                         for name in files}
    details = {
        "validation": dict(status="pass", findings=[], report_sha256=REPORT_SHA,
                           sidecar=evidence_bindings["validation.json"]),
        "accounting": dict(source_sha256=SOURCE_SHA, original_accountability_sha256=ACCOUNT_SHA,
                           original_member=evidence_bindings["package/source-accountability.json"]),
        "fidelity": dict(original_tei_sha256=TEI_SHA, original_text_sha256=original_text_sha,
                         derived_text_sha256=_sha(derived.split(b"</teiHeader>", 1)[1]),
                         header_only_derivation=True),
        "reproducibility": dict(historical_route_tests=receipt["technical_completion_continuation_20260920"]["focused_route_tests"],
                                original_package_sha256=PACKAGE_SHA,
                                no_reconstruction_performed=True),
        "schema": dict(vendored_xsd="ocd_kernel/tei/vendor/xsd/tei_all.xsd", validation_errors=[]),
        "closure": dict(original_package_sha256=PACKAGE_SHA, original_tei_sha256=TEI_SHA,
                        evidence_files=evidence_bindings),
    }
    command = "py -3 -m build.tools.prepare_strong_vol3_acceptance --stage <fresh-external-root>"
    technical = dict(producer=dict(id="ocd-strong-pg45283-volume-3-structured-transcription"),
                     checker=dict(id="ocd-strong-pg45283-independent-structure-oracle"),
                     shared_assumptions=["Producer and oracle use the same retained bytes and SourceManifest; the three visual loci are a partial sample."],
                     independent_corroboration="Current independent oracle, physical-line accounting, mutation and fresh-process reproduction recorded in the v9 receipt; exact-pair native CVW opening/middle/ending captures.")
    for name in PROOFS:
        path = evidence / f"{name}.json"
        _write(path, common | dict(status="pass", command=command, exit_code=0, details=details[name]))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    loci = [item["boundary"] for item in captures]
    reviewed_at = receipt["latest_cvw_visual_review"]["observed_at_utc"]
    review = dict(reviewer="agent:37c-298-v9-reported-visual-review", reviewed_at=reviewed_at,
                  coverage=dict(status="partial", declared=SCOPE, reached=loci,
                                inspected=loci, unreviewed=[]),
                  source_quality_uncertainty=["Original-publication year and underlying print-transcription lineage remain unresolved."],
                  discrepancies=[],
                  unreviewed_residuals=["Opening, middle, and ending captures do not establish exhaustive whole-work proofreading; source/TEI panes were unlinked and middle/ending start-location warnings remain."])
    _write(evidence / "review.json", common | review | dict(
        capture_bindings={item["boundary"]: evidence_bindings[f"cvw/{item['boundary']}/capture.json"]
                          for item in captures},
        review_basis="Historical ticket/report manual pixel inspection of the exact original v9 source/TEI pair; this helper did not re-inspect frames. Derived TEI text bytes are identical."))
    decision = dict(source_local_disposition="Evidence-backed agent acceptance of the exact retained Project Gutenberg #45283 electronic Volume 3 witness only.",
                    blockers=[], agent_assessment=dict(status="accepted", actor="agent:strong-vol3-pg45283-review",
                    assessed_at=now.isoformat().replace("+00:00", "Z"), supported_scope=SCOPE,
                    unassessed_stronger_claims=["human acceptance", "exhaustive whole-work proofreading", "rights clearance", "original-publication year", "print-transcription lineage", "release", "publication"],
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
