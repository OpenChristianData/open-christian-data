"""Stage exact LIB-055 electronic witnesses for guarded agent acceptance.

Only the three reviewed single-member CCEL ThML packages in the pinned preflight
are eligible. This tool does not install canonical identities or masters.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import uuid
from pathlib import Path

from lxml import etree

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.acceptance import (
    build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = Path("plans/2026-09-22-source-preflight/lib055-next-acceptance-preflight-20260925.json")
PREFLIGHT_SHA = "d20ad2bc39cf2195f4ed66e44acd4a1ea27a5260558e9712b06bb9d9e2aa1460"
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")
SOURCE_URLS = {
    "flavel-fountain-of-life": "https://www.ccel.org/ccel/flavel/fountain.xml",
    "flavel-method-of-grace": "https://www.ccel.org/ccel/flavel/grace.xml",
    "ryle-expository-thoughts-matthew": "https://www.ccel.org/ccel/ryle/matthew.xml",
}
OLD_AVAILABILITY = {
    "flavel-fountain-of-life": b"Nonaccepted technical candidate; publication is not authorized.",
    "flavel-method-of-grace": b"Nonaccepted technical candidate; publication is not authorized.",
    "ryle-expository-thoughts-matthew": b"Nonaccepted technical candidate; human acceptance and publication are not authorized.",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"LIB-055 handoff input unavailable: {path}") from exc
    if expected is not None and _sha(content) != expected:
        raise PipelineError(f"LIB-055 handoff input SHA-256 mismatch: {path}")
    return content


def _obj(content: bytes, label: str) -> dict:
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"invalid LIB-055 {label} JSON") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"LIB-055 {label} is not a JSON object")
    return value


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def _copy(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def _stage_path(root: Path, stage: Path, package_home: Path) -> Path:
    stage = stage.absolute()
    if stage.exists() or not stage.parent.is_dir() or stage.parent.is_symlink():
        raise PipelineError("LIB-055 stage must be fresh beneath an ordinary existing parent")
    resolved = stage.resolve()
    for protected in (root.resolve(), package_home.resolve()):
        if resolved == protected or protected in resolved.parents or resolved in protected.parents:
            raise PipelineError("LIB-055 stage overlaps the checkout or reviewed package")
    return stage


def _identity(work_id: str) -> dict[str, str]:
    if work_id == "ryle-expository-thoughts-matthew":
        # Short IDs retain scope and fit Windows promotion/install staging paths.
        return dict(work_id=work_id, textual_form_id="ryle-matthew-retained-english",
                    edition_id="ccel-matthew-electronic-witness",
                    acquisition_id="ccel-matthew-retained")
    return dict(work_id=work_id, textual_form_id=f"{work_id}-retained-english",
                edition_id=f"{work_id}-ccel-electronic-witness",
                acquisition_id=f"{work_id}-ccel-retained")


CATEGORY = {
    "flavel-fountain-of-life": "sermons",
    "flavel-method-of-grace": "sermons",
    "ryle-expository-thoughts-matthew": "commentary",
}


def _historical_proof(receipt: dict, row: dict) -> dict:
    """Require each ticket's actual independent accounting and review claims."""
    wid = row["work_id"]
    if wid == "flavel-fountain-of-life":
        v = receipt.get("verification", {})
        c = receipt.get("coordinator_candidate_follow_through", {})
        required = ("independent_source_tei_accounting", "meaningful_mutation_rejection",
                    "deterministic_candidate_reproduction", "cvw")
        if (any(not str(v.get(k, "")).startswith("pass") for k in required)
                or c.get("candidate_sha256") != row["candidate_manifest_sha256"]
                or c.get("source_manifest_sha256") != row["source_manifest_sha256"]
                or c.get("validation_status") != "pass"):
            raise PipelineError("Fountain technical and CVW receipt does not bind the candidate")
        return {k: v[k] for k in required}
    if wid == "flavel-method-of-grace":
        v = receipt.get("verification", {})
        accounting = v.get("source_accounting", {})
        mutations = v.get("mutation_rejection", {})
        determinism = v.get("determinism", {})
        cvw = v.get("cvw", {})
        if (receipt.get("candidate", {}).get("package_sha256") != row["candidate_manifest_sha256"]
                or receipt.get("candidate", {}).get("content_tei_sha256") != row["candidate_tei_sha256"]
                or accounting.get("status") != "pass" or accounting.get("complete_envelope") is not True
                or mutations.get("status") != "pass" or mutations.get("cases_passed") != 10
                or determinism.get("status") != "pass" or determinism.get("fresh_process") is not True
                or cvw.get("status") != "declared_native_systematic_sample_complete"
                or cvw.get("primary_candidate_content_sha256") != row["candidate_tei_sha256"]
                or cvw.get("three_locus_recheck", {}).get("status") != "complete"):
            raise PipelineError("Method technical and CVW receipt does not bind the candidate")
        return dict(accounting=accounting, mutations=mutations, determinism=determinism,
                    visual_status=cvw["status"], three_locus_recheck=cvw["three_locus_recheck"]["status"])
    c = receipt.get("coordinator_candidate_follow_through", {})
    candidate = c.get("candidate", {})
    validation = c.get("validation", {})
    reproduction = c.get("fresh_process_reproduction", {})
    cvw = c.get("cvw", {})
    if (candidate.get("package_sha256") != row["candidate_manifest_sha256"]
            or candidate.get("source_manifest_sha256") != row["source_manifest_sha256"]
            or validation.get("status") != "pass" or validation.get("findings") != []
            or validation.get("oracle_result_sha256") is None
            or reproduction.get("status") != "pass"
            or reproduction.get("package_members_byte_identical") is not True
            or cvw.get("status") != "bounded_visual_review_complete"
            or cvw.get("source_sha256") != row["source_member_sha256"]):
        raise PipelineError("Ryle technical and CVW receipt does not bind the candidate")
    return dict(oracle_result_sha256=validation["oracle_result_sha256"],
                reproduction_status=reproduction["status"], visual_status=cvw["status"],
                source_heading_assessment="132 source h1/h2/h3 texts equal 132 TEI head or p@rend source-heading texts in order; the 101 p@rend carriers explicitly retain h1/h2/h3 source roles. Structural normalization and print layout remain unassessed.")
def _assess_ryle_headings(source_bytes: bytes, original: bytes) -> dict:
    """Prove source heading wording/order and explicit role carriers survive."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    source_tree = etree.fromstring(source_bytes, parser)
    tei_tree = etree.fromstring(original, parser)
    source = [(" ".join("".join(node.itertext()).split()), etree.QName(node).localname)
              for node in source_tree.iter() if isinstance(node.tag, str)
              and etree.QName(node).localname in {"h1", "h2", "h3"}]
    target = [(" ".join("".join(node.itertext()).split()), etree.QName(node).localname,
               node.get("rend")) for node in tei_tree.iter() if isinstance(node.tag, str)
              and (etree.QName(node).localname == "head" or
                   (node.get("rend") or "").startswith("source-heading-h"))]
    if len(source) != 132 or len(target) != 132 or sum(x[1] == "p" for x in target) != 101:
        raise PipelineError("Ryle source/TEI heading carrier census differs")
    for index, (before, after) in enumerate(zip(source, target, strict=True)):
        if before[0] != after[0] or (after[1] == "p" and after[2] != "source-heading-" + before[1]):
            raise PipelineError(f"Ryle source heading text or role differs at position {index + 1}")
    return dict(source_headings=len(source), tei_heading_carriers=len(target),
                explicit_p_rend_roles=101, exact_heading_text_order=True,
                assessment="Exact source heading text/order survives; p@rend preserves source h-level. Structural head normalization and print typography are not inferred.")


def _bind_header(original: bytes, *, row: dict, identity: dict, source: dict, revision: dict) -> bytes:
    work_id = identity["work_id"]
    old = OLD_AVAILABILITY[work_id]
    if original.count(old) != 1:
        raise PipelineError("reviewed LIB-055 availability statement differs")
    derived = bind_reviewed_header(
        original, expected_sha256=row["candidate_tei_sha256"], identity=identity,
        source=source, source_url=SOURCE_URLS[work_id],
        declared_scope=source["source_scope"], revision=revision,
    )
    derived = derived.replace(
        old, b"Agent-accepted exact CCEL electronic witness; human verification and publication are not authorized.", 1
    )
    boundary = b"</teiHeader>"
    if original.count(boundary) != 1 or derived.count(boundary) != 1:
        raise PipelineError("reviewed LIB-055 TEI header boundary is ambiguous")
    if original.split(boundary, 1)[1] != derived.split(boundary, 1)[1]:
        raise PipelineError("LIB-055 acceptance derivation changed reviewed TEI text bytes")
    return derived


def prepare(root: Path, stage: Path, work_id: str) -> Path:
    root = root.resolve(strict=True)
    packet = _obj(_read(root / PREFLIGHT, PREFLIGHT_SHA), "pinned preflight")
    if packet.get("contract") != "ocd-next-acceptance-handoff-preflight-v1":
        raise PipelineError("LIB-055 pinned preflight contract differs")
    rows = {row["work_id"]: row for row in packet["works"]}
    if set(rows) != set(SOURCE_URLS) or work_id not in rows:
        raise PipelineError("LIB-055 pinned cohort identity differs")
    row = rows[work_id]
    package_home = Path(row["candidate_package"])
    stage = _stage_path(root, stage, package_home)
    work_dir = Path("library/works") / work_id
    work_bytes = _read(root / work_dir / "work.json", row["work_sha256"])
    work = _obj(work_bytes, "work")
    state_bytes = _read(root / work_dir / "state.json")
    state = _obj(state_bytes, "state")
    if work.get("work_id") != work_id or work.get("textual_forms") != [] or state.get("work_id") != work_id or state.get("targets") != []:
        raise PipelineError("LIB-055 handoff requires this exact identity-only work and empty target state")
    manifest_path = root / row["source_manifest"]
    manifest_bytes = _read(manifest_path, row["source_manifest_sha256"])
    manifest = SourceManifest.load(manifest_path, repository_root=root)
    manifest.verify()
    if (manifest.sha256 != row["source_manifest_sha256"] or manifest.record.get("work_id") != work_id
            or manifest.record.get("scope", {}).get("member_count") != 1
            or manifest.record.get("scope", {}).get("selector") != row["source_selector"]):
        raise PipelineError("LIB-055 source manifest scope differs")
    authorities = [a for a in manifest.record["authorities"] if a.get("role") == "primary-source"]
    if len(authorities) != 1 or any(authorities[0].get(key) != value for key, value in (
        ("path", row["source_member"]), ("sha256", row["source_member_sha256"]),
        ("bytes", row["source_member_bytes"]),
    )):
        raise PipelineError("LIB-055 source member declaration differs")
    source_bytes = _read(resolve_repo_path(root, row["source_member"]), row["source_member_sha256"])
    if len(source_bytes) != row["source_member_bytes"]:
        raise PipelineError("LIB-055 retained source byte count differs")
    config_path = root / "sources/structured-text" / work_id / "config.json"
    config = _obj(_read(config_path), "source config")
    if (config.get("resource_id") != work_id or config.get("source_url") != SOURCE_URLS[work_id]
            or config.get("source_hash") != "sha256:" + row["source_member_sha256"]):
        raise PipelineError("LIB-055 source URL and hash differ from bound work config")
    package = CandidatePackage.load(package_home)
    original = package.member_bytes("content.tei.xml")
    if (package.sha256 != row["candidate_manifest_sha256"]
            or package.manifest.get("status") != "nonaccepted"
            or package.manifest.get("source_manifest", {}).get("sha256") != manifest.sha256
            or _sha(original) != row["candidate_tei_sha256"]):
        raise PipelineError("LIB-055 reviewed candidate differs")
    heading_assessment = (_assess_ryle_headings(source_bytes, original)
                          if work_id == "ryle-expository-thoughts-matthew" else None)
    validation_path = package_home.parent / "validation.json"
    validation_bytes = _read(validation_path, row["validation_sha256"])
    validation = _obj(validation_bytes, "validation")
    if (validation.get("status") != "pass" or validation.get("findings") != []
            or validation.get("candidate_sha256") != package.sha256
            or validation.get("source_manifest_sha256") != manifest.sha256
            or validation.get("report_sha256") != row["validation_report_sha256"]
            or validation.get("attestation", {}).get("source_sha256") != row["source_member_sha256"]):
        raise PipelineError("LIB-055 recorded validation does not bind exact source and candidate")
    ticket = _read(root / row["ticket"], row["ticket_sha256"])
    report = _read(root / row["review_report"], row["review_report_sha256"])
    receipt_bytes = _read(root / row["review_receipt"], row["review_receipt_sha256"])
    receipt = _obj(receipt_bytes, "review receipt")
    if (receipt.get("work_id") != work_id or row["source_member_sha256"].encode() not in report
            or row["candidate_manifest_sha256"].encode() not in report
            or row["candidate_manifest_sha256"].encode() not in receipt_bytes):
        raise PipelineError("LIB-055 review does not identify the exact source and TEI")
    for marker in ("CVW", "nonaccepted"):
        if marker.encode() not in ticket:
            raise PipelineError(f"LIB-055 ticket lost the {marker} review boundary")
    historical_proof = _historical_proof(receipt, row)

    identity = _identity(work_id)
    edition = work_dir / "forms" / identity["textual_form_id"] / "editions" / identity["edition_id"]
    acquisition_path = edition / "acquisitions" / f'{identity["acquisition_id"]}.json'
    evidence_rel = work_dir / "integration/lib055-electronic-witness-agent-handoff"
    evidence = stage / evidence_rel
    now = datetime.now(timezone.utc)
    source_scope = ("Complete retained CCEL ThML[1] electronic member at " + row["source_member"]
                    + "; no print-exemplar, full catalog-work, or historical-edition equivalence asserted.")
    source = dict(source_path=row["source_member"], source_sha256=row["source_member_sha256"],
                  source_bytes=len(source_bytes), source_scope=source_scope)
    revision = dict(id=f"{work_id}-ccel-electronic-agent-v1", date=now.date().isoformat(),
                    note="Bind the exact retained CCEL electronic witness; reviewed TEI text bytes unchanged.")
    derived = _bind_header(original, row=row, identity=identity, source=source, revision=revision)
    candidate = _copy(stage, evidence_rel / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"derived LIB-055 TEI failed vendored XSD: {errors[:3]}")
    _copy(stage, work_dir / "README.source.md", package.member_bytes("README.source.md"))
    _copy(stage, Path(row["source_member"]), source_bytes)
    _copy(stage, Path(row["source_manifest"]), manifest_bytes)
    _copy(stage, evidence_rel / "inputs/preflight.json", _read(root / PREFLIGHT, PREFLIGHT_SHA))
    _copy(stage, evidence_rel / "inputs/source-config.json", _read(config_path))
    _copy(stage, evidence_rel / "inputs/original-work.json", work_bytes)
    _copy(stage, evidence_rel / "inputs/original-state.json", state_bytes)
    _copy(stage, evidence_rel / "inputs/ticket.md", ticket)
    _copy(stage, evidence_rel / "inputs/report.md", report)
    _copy(stage, evidence_rel / "inputs/review-receipt.json", receipt_bytes)
    _copy(stage, evidence_rel / "inputs/validation.json", validation_bytes)
    for name in package.member_names:
        _copy(stage, evidence_rel / "inputs/package" / name, package.member_bytes(name))

    acquisition = dict(schema_version="2.0", acquisition_id=identity["acquisition_id"],
                       edition_id=identity["edition_id"], provider="Christian Classics Ethereal Library",
                       url=SOURCE_URLS[work_id], retained_files=[dict(
                           path=row["source_member"], bytes=len(source_bytes),
                           sha256=row["source_member_sha256"], scope=source_scope,
                           media_type="application/xml")],
                       warnings=["Only the exact retained electronic witness is identified; print exemplar, full work boundary, and rights clearance remain unresolved."])
    _write(stage / acquisition_path, acquisition)
    form_title = manifest.record["identity"]["source_record_metadata"]["title"]
    work["textual_forms"].append(dict(textual_form_id=identity["textual_form_id"],
                                      title=form_title, language="en", category=CATEGORY[work_id],
                                      editions=[dict(edition_id=identity["edition_id"],
                                                     title=f"CCEL electronic witness of {form_title}",
                                                     language="en", category=CATEGORY[work_id],
                                                     acquisition_ids=[identity["acquisition_id"]])]))
    validate_identity_update(_obj(work_bytes, "original work"), work)
    _write(stage / work_dir / "work.json", work)
    state["targets"].append(dict(target_id=identity["edition_id"], target_type="edition",
                                 stage="review", updated_at=now.isoformat().replace("+00:00", "Z"),
                                 evidence=[(evidence_rel / "inputs/ticket.md").as_posix(),
                                           (evidence_rel / "inputs/report.md").as_posix(),
                                           acquisition_path.as_posix()]))
    _write(stage / work_dir / "state.json", state)
    load_work(stage / work_dir / "work.json")

    included = [dict(path=row["source_member"], bytes=len(source_bytes),
                     sha256=row["source_member_sha256"], scope=source_scope, position=1)]
    scope = dict(kind="edition", declared=source_scope,
                 expected_members=[dict(path=row["source_member"], position=1)],
                 included_members=included, excluded_members=[])
    common = dict(identity=identity, source=source, candidate=make_file_binding(stage, candidate),
                  scope=source_scope, accepted_scope=dict(kind="edition", declared=source_scope),
                  expected_members=scope["expected_members"], included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[])
    account = _write(evidence / "source-accounting.json", common | dict(
        source_manifest_sha256=manifest.sha256,
        source_sha256=row["source_member_sha256"], source_bytes=len(source_bytes),
        original_accountability_sha256=_sha(package.member_bytes("source-accountability.json")),
        source_selector=row["source_selector"],
        historical_proof=historical_proof,
        heading_assessment=heading_assessment,
    ))
    original_body = original.split(b"</teiHeader>", 1)[1]
    derived_body = derived.split(b"</teiHeader>", 1)[1]
    details = {
        "validation": dict(status="pass", findings=[], sidecar=make_file_binding(stage, evidence / "inputs/validation.json"),
                           report_sha256=row["validation_report_sha256"]),
        "accounting": dict(source_sha256=row["source_member_sha256"], selector=row["source_selector"],
                           original_member=make_file_binding(stage, evidence / "inputs/package/source-accountability.json")),
        "fidelity": dict(original_tei_sha256=row["candidate_tei_sha256"],
                         original_body_sha256=_sha(original_body), derived_body_sha256=_sha(derived_body),
                         header_only_derivation=True, heading_assessment=heading_assessment,
                         historical_review=make_file_binding(stage, evidence / "inputs/report.md")),
        "reproducibility": dict(historical_receipt=make_file_binding(stage, evidence / "inputs/review-receipt.json"),
                                historical_proof=historical_proof,
                                original_package_sha256=package.sha256, no_reconstruction_performed=True),
        "schema": dict(vendored_xsd="ocd_kernel/tei/vendor/xsd/tei_all.xsd", validation_errors=[]),
        "closure": dict(source_manifest_sha256=manifest.sha256, original_package_sha256=package.sha256,
                        pinned_preflight=make_file_binding(stage, evidence / "inputs/preflight.json")),
    }
    command = "py -3 -m build.tools.prepare_lib055_electronic_witness_acceptance --work <reviewed-id> --stage <fresh-external-root>"
    technical = dict(producer=dict(id=package.manifest["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["The producer and oracle share the retained ThML member and route manifest; CVW evidence is bounded."],
                     independent_corroboration="Manifest-bound independent source accounting and oracle, stored passing validation, ticket-local mutations and reproduction, bounded exact-pair CVW review, unchanged TEI text after header binding.")
    for name in PROOFS:
        path = _write(evidence / f"{name}.json", common | dict(status="pass", command=command,
                                                                 exit_code=0, details=details[name]))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    reviewed_at = receipt.get("reviewed_at_utc") or receipt.get("observed_at_utc")
    if not isinstance(reviewed_at, str):
        raise PipelineError("LIB-055 receipt lacks historical review time")
    review = dict(reviewer=f"historical:{row['ticket'].split('/')[-1]}-agent-CVW",
                  reviewed_at=reviewed_at,
                  coverage=dict(status="partial", declared=source_scope,
                                reached=[row["visual_review"]], inspected=[row["visual_review"]],
                                unreviewed=["All other source and candidate locations outside the declared bounded sample"]),
                  source_quality_uncertainty=[row["scope_limit"], "Rights clearance remains unresolved."],
                  discrepancies=[],
                  unreviewed_residuals=["Bounded native visual review is not whole-document or print-exemplar proofreading."])
    review_path = _write(evidence / "review.json", common | review | dict(
        historical_review_report=make_file_binding(stage, evidence / "inputs/report.md"),
        historical_review_receipt=make_file_binding(stage, evidence / "inputs/review-receipt.json"),
        historical_proof=historical_proof,
        heading_assessment=heading_assessment,
        reviewed_original_tei_sha256=row["candidate_tei_sha256"],
        derived_body_bytes_unchanged=True, no_new_pixel_review=True,
    ))
    decision = dict(source_local_disposition="Agent acceptance of this exact retained CCEL electronic member only.",
                    blockers=[], agent_assessment=dict(status="accepted",
                        actor=f"agent:{work_id}-retained-electronic-witness-review",
                        assessed_at=now.isoformat().replace("+00:00", "Z"), supported_scope=source_scope,
                        unassessed_stronger_claims=["human verification", "rights clearance", "print-edition identity",
                                                    "full catalog-work equivalence", "exhaustive proofreading", "publication"],
                        unresolved_claims=(["Ryle print typography and full TEI heading-hierarchy equivalence beyond exact text/order and preserved source h-level are unassessed."]
                                           if heading_assessment else [])),
                    human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate,
                                     source_accounting_path=account, scope=scope, technical=technical,
                                     review=review | dict(report_path=review_path),
                                     representation_revision=revision, decision=decision)
    acceptance = stage / edition / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    return acceptance


def declare(root: Path, promoted: Path, work_id: str) -> tuple[Path, Path]:
    """Guardedly declare only the reviewed identity/acquisition before install."""
    root, promoted = root.resolve(strict=True), promoted.resolve(strict=True)
    packet = _obj(_read(root / PREFLIGHT, PREFLIGHT_SHA), "pinned preflight")
    rows = {row["work_id"]: row for row in packet["works"]}
    if work_id not in SOURCE_URLS or set(rows) != set(SOURCE_URLS):
        raise PipelineError("LIB-055 declaration cohort differs")
    row = rows[work_id]
    identity = _identity(work_id)
    work_dir = Path("library/works") / work_id
    edition = work_dir / "forms" / identity["textual_form_id"] / "editions" / identity["edition_id"]
    acquisition_rel = edition / "acquisitions" / f'{identity["acquisition_id"]}.json'
    evidence_rel = work_dir / "integration/lib055-electronic-witness-agent-handoff"
    acceptance = promoted / edition / "acceptance.json"
    record = validate_acceptance(acceptance, root=promoted)
    if record["promotion"]["status"] != "promoted" or record["identity"] != identity:
        raise PipelineError("LIB-055 declaration requires exact promoted acceptance")
    live_work, live_state = root / work_dir / "work.json", root / work_dir / "state.json"
    original_state = _read(promoted / evidence_rel / "inputs/original-state.json")
    staged_work = _read(promoted / work_dir / "work.json")
    staged_acquisition = _read(promoted / acquisition_rel)
    expected_work = row["work_sha256"]
    expected_state = _sha(original_state)
    previous = _obj(_read(promoted / evidence_rel / "inputs/original-work.json", expected_work), "original work")
    proposed = _obj(staged_work, "promoted work")
    validate_identity_update(previous, proposed)
    if ({k: v for k, v in proposed.items() if k != "textual_forms"}
            != {k: v for k, v in previous.items() if k != "textual_forms"}
            or previous.get("textual_forms") != []
            or len(proposed["textual_forms"]) != 1
            or proposed["textual_forms"][0]["textual_form_id"] != identity["textual_form_id"]
            or proposed["textual_forms"][0]["category"] != CATEGORY[work_id]
            or len(proposed["textual_forms"][0]["editions"]) != 1
            or proposed["textual_forms"][0]["editions"][0]["edition_id"] != identity["edition_id"]
            or proposed["textual_forms"][0]["editions"][0]["category"] != CATEGORY[work_id]):
        raise PipelineError("LIB-055 declaration changes more than one reviewed form and edition")
    acquisition = _obj(staged_acquisition, "promoted acquisition")
    if (acquisition.get("acquisition_id") != identity["acquisition_id"]
            or acquisition.get("edition_id") != identity["edition_id"]
            or acquisition.get("url") != SOURCE_URLS[work_id]
            or len(acquisition.get("retained_files", [])) != 1
            or acquisition["retained_files"][0].get("sha256") != row["source_member_sha256"]):
        raise PipelineError("LIB-055 acquisition differs from reviewed source")
    live_acquisition = root / acquisition_rel
    with acquire_jsonl_lock(root / work_dir, acquire_timeout=30.0):
        _read(live_work, expected_work)
        _read(live_state, expected_state)
        if live_acquisition.exists() or (root / edition).exists():
            raise PipelineError("LIB-055 declaration target already exists")
        live_acquisition.parent.mkdir(parents=True, exist_ok=False)
        with live_acquisition.open("xb") as handle:
            handle.write(staged_acquisition)
        temporary = live_work.with_name(f".work.json.lib055-{uuid.uuid4().hex}")
        try:
            temporary.write_bytes(staged_work)
            os.replace(temporary, live_work)
        finally:
            if temporary.exists():
                temporary.unlink()
        load_work(live_work)
        if _read(live_acquisition) != staged_acquisition:
            raise PipelineError("LIB-055 declared acquisition bytes drifted")
    return live_work, live_acquisition


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", choices=sorted(SOURCE_URLS), required=True)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--stage", type=Path)
    operation.add_argument("--declare-from", type=Path)
    args = parser.parse_args()
    if args.stage is not None:
        print(prepare(ROOT, args.stage, args.work))
    else:
        print(declare(ROOT, args.declare_from, args.work))


if __name__ == "__main__":
    main()




