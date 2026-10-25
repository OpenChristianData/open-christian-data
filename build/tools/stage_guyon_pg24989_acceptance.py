"""Build a source-bound, external acceptance stage for Guyon's PG 24989 witness.

This tool creates an isolated staged work generation only. It never writes the
canonical library. The exact reviewed header-bound master is copied byte for
byte; source reconstruction and the native accepted-document reader are
rechecked before the staged receipt is emitted.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

from build.tei.guyon_short_method_24989_v16_oracle import _oracle
from ocd_kernel.lib.path_io import io_path
from ocd_kernel.library.acquisitions import source_member_set_bytes, validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    project_accepted_document,
    verify_accepted_document,
)
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "jeanne-guyon-short-method-prayer"
FORM_ID = "english"
EDITION_ID = "jeanne-guyon-short-method-prayer-pg24989"
ACQUISITION_ID = "pg24989-retained-zip"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
MEMBER_SET = EDITION / "source-member-set.json"
EVIDENCE = WORK / "integration/guyon-pg24989-electronic-acceptance-v1"
RECEIPT_NAME = "guyon-pg24989-stage-receipt.json"

PROPOSAL = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/GUYON_PG24989_IDENTITY_PROPOSAL_20261003.json")
PROPOSAL_SHA = "9d5bd6c47de9c90378f5a7ced1147fb2196871570b5b968ea78ca54f9a5a3ef0"
IDENTITY_REVIEW = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/GUYON_PG24989_IDENTITY_PROPOSAL_PARENT_REVIEW_20261004.json")
IDENTITY_REVIEW_SHA = "7c94f1acc5126afedb703911856c02bd23283217174ab7767b548fbb31077d3c"
MASTER_DRAFT = Path(".tmp_audit/guyon-bound-master-draft-20261004-v2/guyon-bound-draft.tei.xml")
MASTER_DRAFT_SHA = "5085fa30cd52f435afc5cfe63ab8950587391830109f94320716a6fa088f325c"
DRAFT_RECEIPT = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/GUYON_PG24989_BOUND_MASTER_DRAFT_20261004.json")
DRAFT_RECEIPT_SHA = "9f12c7a1512c059ac449c9c28fe74489a07877c09cbadceaa111512879d626af"
PARENT_MASTER_REVIEW = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/GUYON_PG24989_BOUND_MASTER_PARENT_REVIEW_20261004.json")
PARENT_MASTER_REVIEW_SHA = "37f3131c294f3b9714117e6a98c609ab2c88d7f61620f9b9be7863b3a2988b6d"

SOURCE_MANIFEST = Path("sources/manifest-acquisitions/guyon-short-method-pg24989-v16/source-manifest.json")
SOURCE_MANIFEST_SHA = "f77c6d1fe6c9cf65f4fb6a4f442dc4e2bb742e7343ade3cf4a9f40910e6c84e6"
SOURCE_MEMBER_SET_SHA = "dd178e780fae6a51a8d6bebb58343af2830f531f3569496a15f11f8f38e42875"
CANDIDATE = Path(r"D:\Library\Open Christian Data\candidate-reviews\guyon-pg24989-envelope-v16-candidate-20261003-v1\package")
REPLAY = Path(r"D:\Library\Open Christian Data\candidate-reviews\guyon-pg24989-envelope-v16-replay-20261003-v1\package")
CANDIDATE_MANIFEST_SHA = "3250c10c4a67228fa7295ba2e16ad84ce5f1cac98baa4ff959527e25b428ef13"
CANDIDATE_TEI_SHA = "2000f4731da7c49293ed4dee20219b2195f286404117142125a732a40335fb51"
CANDIDATE_VALIDATION_SHA = "0674b864ecc1ea33a0236b66f3628001437b6ed40f68e10ecf81fdeec61d1179"
SOURCE_READBACK = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/GUYON_PG24989_V16_INDEPENDENT_READBACK_20261003_v2.json")
SOURCE_READBACK_SHA = "a11b4cc0504593505269e03e978c4fb932c1cf8f062b2c42d6c98997881d8196"
CHALLENGE_RECEIPT = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/GUYON_PG24989_V16_REPLAY_AND_SEMANTIC_CHALLENGES_20261003.json")
CHALLENGE_RECEIPT_SHA = "de5c2f4d7b54238ed376b02c0cf1ed3c2f6fdeac2d4c675f12c0ee8eb0370d2e"
ALIAS_RECEIPT = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/GUYON_PG24989_CURRENT_IDENTITY_ALIAS_REVIEW_20261003.json")
ALIAS_RECEIPT_SHA = "25a9210e583e82845154a26729329dbaf51c5013b2a96b2d50dcc15aa5a6b52a"
SOURCE_NOTICE_DRAFT = Path(".tmp_audit/GUYON_PG24989_SOURCE_NOTICE_DRAFT_20261004_v2.md")
SOURCE_NOTICE_SHA = "4331ba37805c091ac98537a95d938bc1052fb322bf2951fdd99f5dbe39717823"
INVENTORY_NEWLINE_RECEIPT = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/GUYON_PG24989_RETAINED_INVENTORY_NEWLINE_ACCOUNTING_20261004.json")
INVENTORY_NEWLINE_RECEIPT_SHA = "4bf9392713e1173f02371aeb2e38a20555be89d626cd28091e2950facfdcd6b1"
ORACLE_RESULT_SHA = "d3f3ac945f2fd7406f71b6744d62a17aa0c76d52716d554f2c267fb0ad2268d7"
COMBINED_RUNTIME_PLAN = Path("reports/_logs/native-unified-admissions-applied-20261004-v1/application-plan.json")
COMBINED_RUNTIME_PLAN_SHA = "0ab255817e9980d6eb8edd3f6cecfd7862bd603ebaf0877ddf515a9ce6227023"
COMBINED_RUNTIME_READBACK = Path("reports/_logs/native-unified-admissions-applied-20261004-v1/application-readback.json")
COMBINED_RUNTIME_READBACK_SHA = "3f5a0b3e371b8450aec46fa1ad2fb6891f314d9de5f83b0af8c2a7eb5ea1bec4"

IDENTITY = {
    "work_id": WORK_ID,
    "textual_form_id": FORM_ID,
    "edition_id": EDITION_ID,
    "acquisition_id": ACQUISITION_ID,
}
PROJECTION_PROFILE = "ocd-prose-guyon-pg24989-v16-source-native-v1"
INSTALLER_SCRIPT = Path("build/tools/install_guyon_pg24989_acceptance.py")


def _runtime_python_bindings() -> dict[str, str]:
    """Hash loaded first-party modules plus the explicit stage/install entrypoints."""
    combined = _combined_runtime_bindings()
    paths = {INSTALLER_SCRIPT, *(Path(path) for path in combined if path.endswith(".py"))}
    for module in tuple(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        try:
            path = Path(filename).resolve(strict=True)
            relative = path.relative_to(ROOT.resolve(strict=True))
        except (OSError, ValueError):
            continue
        if relative.suffix == ".py" and relative.parts[0] in {"ocd_kernel", "build"}:
            paths.add(relative)
    return {path.as_posix(): _sha(_read(ROOT / path)) for path in sorted(paths)}


def _runtime_resource_bindings() -> dict[str, str]:
    roots = (ROOT / "schemas", ROOT / "ocd_kernel" / "schemas", ROOT / "ocd_kernel" / "tei" / "vendor" / "xsd")
    paths: set[Path] = set()
    for root in roots:
        if root.exists():
            paths.update(path.relative_to(ROOT) for pattern in ("*.json", "*.xsd") for path in root.rglob(pattern) if path.is_file())
    paths.update(Path(path) for path in _combined_runtime_bindings() if path.endswith(".json"))
    return {path.as_posix(): _sha(_read(ROOT / path)) for path in sorted(paths)}


def _combined_runtime_bindings() -> dict[str, str]:
    plan_bytes = _read(ROOT / COMBINED_RUNTIME_PLAN)
    readback_bytes = _read(ROOT / COMBINED_RUNTIME_READBACK)
    if (_sha(plan_bytes) != COMBINED_RUNTIME_PLAN_SHA
            or _sha(readback_bytes) != COMBINED_RUNTIME_READBACK_SHA):
        raise ValueError("combined native-runtime application receipts differ from reviewed pins")
    plan = json.loads(plan_bytes)
    readback = json.loads(readback_bytes)
    if (readback.get("status") != "pass"
            or readback.get("publication_performed") is not False
            or readback.get("application_plan_sha256") != COMBINED_RUNTIME_PLAN_SHA
            or len(readback.get("readbacks", [])) != 2
            or readback["readbacks"][0].get("sha256") != readback["readbacks"][1].get("sha256")):
        raise ValueError("combined native-runtime receipt does not have two matching successful readbacks")
    hashes = readback["readbacks"][0]["sha256"]
    files = plan.get("files")
    if not isinstance(files, dict) or set(files) != set(hashes):
        raise ValueError("combined native-runtime plan/readback file identities differ")
    bindings = {}
    for name, record in files.items():
        relative = record.get("path")
        digest = record.get("candidate_sha256")
        if (not isinstance(relative, str) or not isinstance(digest, str) or hashes[name] != digest
                or _sha(_read(ROOT / relative)) != digest):
            raise ValueError(f"combined native-runtime postimage differs: {name}")
        bindings[relative] = digest
    return bindings


def _read(path: Path) -> bytes:
    return io_path(path).read_bytes()


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _json_bytes(value: object) -> bytes:
    def plain(item: object) -> object:
        if isinstance(item, Mapping):
            return {str(key): plain(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [plain(child) for child in item]
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        raise TypeError(f"unsupported JSON value in stage receipt: {type(item).__name__}")

    return (json.dumps(plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write(stage: Path, relative: Path, value: bytes) -> Path:
    path = stage / relative
    io_path(path.parent).mkdir(parents=True, exist_ok=True)
    io_path(path).write_bytes(value)
    return path


def _write_json(stage: Path, relative: Path, value: object) -> Path:
    return _write(stage, relative, _json_bytes(value))


def _copy_input(stage: Path, relative: Path, *, expected_sha: str | None = None) -> bytes:
    value = _read(ROOT / relative)
    if expected_sha is not None and _sha(value) != expected_sha:
        raise ValueError(f"Guyon pinned input differs: {relative}")
    _write(stage, relative, value)
    return value


def _member_rows(acquisition: dict) -> tuple[list[dict], list[dict]]:
    expected, included = [], []
    for position, item in enumerate(acquisition["retained_files"], 1):
        expected.append({"path": item["path"], "position": position})
        included.append({
            "path": item["path"], "position": position,
            "bytes": item["bytes"], "sha256": item["sha256"], "scope": item["scope"],
        })
    return expected, included


def _project_and_verify(stage: Path, acceptance_path: Path) -> tuple[dict, list[str], dict[str, str]]:
    """Run the maintained producer and observer while recording executed repo code."""
    executed: set[str] = set()
    filename_cache: dict[str, str | None] = {}
    root_resolved = ROOT.resolve(strict=True)

    def profiler(frame, event, arg):
        if event != "call":
            return
        filename = frame.f_code.co_filename
        if filename in filename_cache:
            relative = filename_cache[filename]
            if relative is not None:
                executed.add(relative)
            return
        try:
            path = Path(filename).resolve(strict=True)
            relative = path.relative_to(root_resolved).as_posix()
        except (OSError, ValueError):
            filename_cache[filename] = None
            return
        if path.suffix == ".py":
            filename_cache[filename] = relative
            executed.add(relative)
        else:
            filename_cache[filename] = None

    previous = sys.getprofile()
    sys.setprofile(profiler)
    try:
        projection = project_accepted_document(
            io_path(stage), acceptance_path=io_path(acceptance_path), category="prose"
        )
        errors = verify_accepted_document(
            io_path(stage), acceptance_path=io_path(acceptance_path),
            rows=projection["rows"], receipt=projection["receipt"], category="prose",
        )
    finally:
        sys.setprofile(previous)
    bindings = {relative: _sha(_read(ROOT / relative)) for relative in sorted(executed)}
    return projection, errors, bindings


def _receipt_sha256_fields(value: object, prefix: str = "") -> dict[str, str]:
    found: dict[str, str] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if (str(key).endswith("_sha256") and isinstance(child, str) and len(child) == 64
                    and all(char in "0123456789abcdef" for char in child)):
                found[name] = child
                found.update(_receipt_sha256_fields(child, name))
    elif isinstance(value, list):
        for index, child in enumerate(value):
                found.update(_receipt_sha256_fields(child, f"{prefix}[{index}]"))
    return found


def prepare(stage_arg: Path) -> dict:
    stage = stage_arg.resolve()
    candidate_root = CANDIDATE.parent.parent
    if (stage.exists() or stage.parent.resolve() != candidate_root.resolve()
            or not stage.name.startswith("guyon-pg24989-acceptance-stage-")
            or ROOT.resolve() in stage.parents or stage in ROOT.resolve().parents):
        raise ValueError("stage must be a fresh, named direct child of the governed candidate-reviews directory")
    if _files(ROOT / WORK):
        raise ValueError("canonical Guyon work is no longer absent; initial-install preimage changed")

    proposal_raw = _copy_input(stage, PROPOSAL, expected_sha=PROPOSAL_SHA)
    identity_review_raw = _copy_input(stage, IDENTITY_REVIEW, expected_sha=IDENTITY_REVIEW_SHA)
    draft_receipt_raw = _copy_input(stage, DRAFT_RECEIPT, expected_sha=DRAFT_RECEIPT_SHA)
    parent_master_review_raw = _copy_input(stage, PARENT_MASTER_REVIEW, expected_sha=PARENT_MASTER_REVIEW_SHA)
    _copy_input(stage, SOURCE_READBACK, expected_sha=SOURCE_READBACK_SHA)
    _copy_input(stage, CHALLENGE_RECEIPT, expected_sha=CHALLENGE_RECEIPT_SHA)
    _copy_input(stage, ALIAS_RECEIPT, expected_sha=ALIAS_RECEIPT_SHA)
    _copy_input(stage, INVENTORY_NEWLINE_RECEIPT, expected_sha=INVENTORY_NEWLINE_RECEIPT_SHA)
    proposal = json.loads(proposal_raw)
    draft_receipt = json.loads(draft_receipt_raw)
    parent_master_review = json.loads(parent_master_review_raw)
    if (proposal.get("canonical_write_performed") is not False
            or proposal.get("identity") != IDENTITY
            or parent_master_review.get("status") != "pass-for-frozen-draft-header-binding"
            or parent_master_review.get("draft_sha256") != MASTER_DRAFT_SHA
            or draft_receipt.get("draft_artifacts", {}).get("master", {}).get("sha256") != MASTER_DRAFT_SHA):
        raise ValueError("reviewed identity or exact bound-master receipt differs")

    _copy_input(stage, SOURCE_MANIFEST, expected_sha=SOURCE_MANIFEST_SHA)
    _copy_input(stage, COMBINED_RUNTIME_PLAN, expected_sha=COMBINED_RUNTIME_PLAN_SHA)
    _copy_input(stage, COMBINED_RUNTIME_READBACK, expected_sha=COMBINED_RUNTIME_READBACK_SHA)
    manifest = SourceManifest.load(ROOT / SOURCE_MANIFEST, repository_root=ROOT)
    manifest.verify()
    package = CandidatePackage.load(io_path(CANDIDATE))
    replay = CandidatePackage.load(io_path(REPLAY))
    if (package.sha256 != CANDIDATE_MANIFEST_SHA or replay.sha256 != package.sha256
            or package.member_bytes("content.tei.xml") is None):
        raise ValueError("frozen Guyon package or replay identity differs")
    report = validate(manifest, package, _oracle)
    if (report.status != "pass" or report.findings
            or report.attestation.get("result_sha256") != ORACLE_RESULT_SHA):
        raise ValueError(f"fresh source oracle rejected frozen Guyon package: {report.findings[:3]}")
    if _sha(_read(CANDIDATE.parent / "validation.json")) != CANDIDATE_VALIDATION_SHA:
        raise ValueError("frozen outer candidate validation sidecar changed")
    if package.member_names != replay.member_names or any(
        package.member_bytes(name) != replay.member_bytes(name) for name in package.member_names
    ):
        raise ValueError("Guyon fresh replay payload differs")

    work_records = proposal["proposed_records"]
    work = work_records["work.json"]
    state = work_records["state.json"]
    acquisition = work_records["acquisition.json"]
    if acquisition.get("identity", IDENTITY) != IDENTITY:
        raise ValueError("proposed acquisition identity differs")
    member_set = source_member_set_bytes(acquisition)
    if (_sha(member_set) != SOURCE_MEMBER_SET_SHA
            or proposal.get("source_member_set", {}).get("sha256") != SOURCE_MEMBER_SET_SHA):
        raise ValueError("canonical source-member-set bytes differ from reviewed proposal")
    if _sha(_read(ROOT / SOURCE_NOTICE_DRAFT)) != SOURCE_NOTICE_SHA:
        raise ValueError("human-readable source notice draft changed")
    _write_json(stage, WORK / "work.json", work)
    _write_json(stage, WORK / "state.json", state)
    _write_json(stage, ACQUISITION, acquisition)
    _write(stage, MEMBER_SET, member_set)
    _write(stage, WORK / "SOURCE_NOTICE.md", _read(ROOT / SOURCE_NOTICE_DRAFT))

    source_binding = {
        "source_path": acquisition["source_path"],
        "source_sha256": acquisition["source_sha256"],
        "source_bytes": acquisition["source_bytes"],
        "source_scope": acquisition["source_scope"],
        "source_kind": acquisition["source_kind"],
    }
    for item in acquisition["retained_files"]:
        _copy_input(stage, Path(item["path"]), expected_sha=item["sha256"])
    validate_acquisition(stage / ACQUISITION, root=stage)
    load_work(stage / WORK / "work.json")
    validate_state(stage / WORK / "state.json", root=stage)

    for item in manifest.record["authorities"]:
        _copy_input(stage, Path(item["path"]), expected_sha=item["sha256"])
    for block in (manifest.record["converter"], manifest.record["validator"]):
        _copy_input(stage, Path(block["implementation_path"]), expected_sha=block["implementation_sha256"])
    _copy_input(stage, Path(__file__).resolve().relative_to(ROOT))
    _copy_input(stage, INSTALLER_SCRIPT)
    stage_manifest = SourceManifest.load(stage / SOURCE_MANIFEST, repository_root=stage)
    stage_manifest.verify()

    package_names = list(package.member_names)
    for name in package_names:
        _write(stage, EVIDENCE / "inputs/candidate-package" / name, package.member_bytes(name))
    validation_bytes = _read(CANDIDATE.parent / "validation.json")
    _write(stage, EVIDENCE / "inputs/candidate-validation.json", validation_bytes)
    candidate_path = _write(stage, EVIDENCE / "candidate.tei.xml", _read(ROOT / MASTER_DRAFT))
    master_path = _write(stage, EDITION / "master.tei.xml", _read(ROOT / MASTER_DRAFT))
    if _sha(_read(candidate_path)) != MASTER_DRAFT_SHA or _sha(_read(master_path)) != MASTER_DRAFT_SHA:
        raise ValueError("stage must reuse the exact parent-reviewed bound master bytes")
    if errors := validate_file(io_path(candidate_path)):
        raise ValueError(f"bound Guyon master failed maintained P5 validation: {errors[:3]}")

    expected_members, included_members = _member_rows(acquisition)
    excluded_members: list[dict] = []
    missing_members: list[str] = []
    unknown_members: list[str] = []
    scope = {
        "kind": "edition", "declared": acquisition["source_scope"],
        "expected_members": expected_members, "included_members": included_members,
        "excluded_members": excluded_members,
    }
    candidate_binding = make_file_binding(stage, candidate_path)
    common = {
        "identity": IDENTITY,
        "candidate": candidate_binding,
        "source": source_binding,
        "scope": acquisition["source_scope"],
        "accepted_scope": {"kind": "edition", "declared": acquisition["source_scope"]},
        "expected_members": expected_members,
        "included_members": included_members,
        "excluded_members": excluded_members,
        "missing_members": missing_members,
        "unknown_members": unknown_members,
    }
    command = "py -3 -m build.tools.stage_guyon_pg24989_acceptance --stage <fresh-external-root>"
    accounting = _write_json(stage, EVIDENCE / "source-accounting.json", common | {
        "source_sha256": acquisition["source_sha256"],
        "source_bytes": acquisition["source_bytes"],
        "projection_profile": PROJECTION_PROFILE,
        "basis": "Complete six-file retained Project Gutenberg electronic acquisition; exact reviewed bound TEI master reused without content changes.",
        "candidate_package_sha256": package.sha256,
        "candidate_validation_sha256": _sha(validation_bytes),
        "source_manifest_sha256": manifest.sha256,
        "combined_runtime_plan_sha256": COMBINED_RUNTIME_PLAN_SHA,
        "combined_runtime_readback_sha256": COMBINED_RUNTIME_READBACK_SHA,
        "all_retained_members_included": True,
        "support_cover_disposition": "retained support image, not represented as a body graphic",
        "inventory_newline_accounting": {
            "evidence_path": INVENTORY_NEWLINE_RECEIPT.as_posix(),
            "evidence_sha256": INVENTORY_NEWLINE_RECEIPT_SHA,
            "retained_bytes": 199,
            "retained_sha256": "e9b127bda94a9fe4752da4405dc9c38e738ac0cb0a3de7a22fb1e91ee41c8f11",
            "historical_lf_serialization_bytes": 197,
            "historical_lf_serialization_sha256": "8f53ce00c997a429b995be6ef44fb6f676b23bf7fd22c267c7e6058e02033bef",
            "disposition": "Exact-content and ordered-field match; only two CRLF versus LF row endings differ. The frozen source manifest binds the actual retained 199-byte CRLF file.",
        },
    })

    proof_sources = {
        "validation": {"evidence": SOURCE_READBACK, "claim": "frozen source package validation and P5"},
        "accounting": {"evidence": SOURCE_READBACK, "claim": "complete retained member set and source envelope accounting"},
        "fidelity": {"evidence": SOURCE_READBACK, "claim": "independent source-to-TEI text/header/structure correspondence"},
        "reproducibility": {"evidence": CHALLENGE_RECEIPT, "claim": "fresh replay and 42 semantic mutation challenges"},
        "schema": {"evidence": CHALLENGE_RECEIPT, "claim": "package integrity/P5 and maintained candidate schema checks"},
        "closure": {"evidence": CHALLENGE_RECEIPT, "claim": "frozen source/candidate/oracle dependency closure"},
    }
    technical = {}
    for name, details in proof_sources.items():
        evidence_bytes = _read(ROOT / details["evidence"])
        proof = _write_json(stage, EVIDENCE / "technical" / f"{name}.json", common | {
            "status": "pass", "command": command, "exit_code": 0,
            "claim": details["claim"],
            "evidence_path": details["evidence"].as_posix(),
            "evidence_sha256": _sha(evidence_bytes),
            "candidate_package_sha256": package.sha256,
            "source_manifest_sha256": manifest.sha256,
            "oracle_attestation": report.attestation,
        })
        technical[name] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}

    technical["producer"] = {"id": manifest.record["converter"]["id"]}
    technical["checker"] = {"id": manifest.record["validator"]["id"]}
    technical["shared_assumptions"] = [
        "The source oracle and historical converter share lxml/HTML recovery; the independent source readback also used lexical/stdlib corroboration and source-bound semantic challenges.",
        "Header binding is reversible and changes no original source paragraph or document text; parent review verified the complete inverse.",
    ]
    technical["independent_corroboration"] = (
        "Parent-reviewed frozen source receipt and 42 resealed semantic challenges; "
        "this stage additionally requires the maintained accepted-context producer and observer to agree on the actual bound master."
    )

    reviewed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    review = {
        "reviewer": "agent:guyon-pg24989-electronic-stage",
        "reviewed_at": reviewed_at,
        "coverage": {
            "status": "partial", "declared": acquisition["source_scope"],
            "reached": ["retained PG 24989 electronic acquisition"],
            "inspected": ["retained PG 24989 electronic acquisition"],
            "unreviewed": ["print-image collation", "jurisdictional rights status", "human acceptance"],
        },
        "source_quality_uncertainty": [
            "The retained electronic transcription has not been collated against print images.",
            "The source's rights and license statements remain source assertions; jurisdictional clearance has not been assessed.",
        ],
        "discrepancies": [
            "The older acquisition README/receipt serialized the member inventory with LF endings (197 bytes); the retained inventory is 199 bytes with two CRLF endings. Exact fields, values, and row order match, and the frozen v16 source manifest binds the retained bytes. See the separately bound newline-accounting receipt."
        ],
        "unreviewed_residuals": [
            "Human acceptance, print collation, jurisdictional rights clearance, and public publication remain unassessed."
        ],
    }
    review_path = _write_json(stage, EVIDENCE / "review.json", common | review)
    revision = {
        "id": "guyon-pg24989-electronic-agent-v1",
        "date": "2026-10-04",
        "note": "Bind the retained Short Method electronic witness to its proposed work, translation, edition, acquisition, and exact source scope; human acceptance, rights, print collation, and public publication are not determined.",
    }
    decision = {
        "source_local_disposition": "Accept only the complete retained English electronic witness of A Short Method of Prayer as an agent technical representation.",
        "blockers": [],
        "agent_assessment": {
            "status": "accepted", "actor": review["reviewer"], "assessed_at": reviewed_at,
            "supported_scope": acquisition["source_scope"],
            "unresolved_claims": [],
            "unassessed_stronger_claims": ["human acceptance", "print collation", "rights clearance", "public publication"],
        },
        "human_decision": {"status": "not-recorded"},
    }
    acceptance = build_acceptance_record(
        stage, identity=IDENTITY, candidate_path=candidate_path,
        source_accounting_path=accounting, scope=scope, technical=technical,
        review=review | {"report_path": review_path}, representation_revision=revision,
        decision=decision,
    )
    acceptance_path = stage / EDITION / "acceptance.json"
    write_acceptance(io_path(acceptance_path), acceptance)
    acceptance["promotion"].update(
        status="promoted", promoted_at=reviewed_at,
        master=make_file_binding(stage, master_path),
    )
    state_path = stage / WORK / "state.json"
    state = json.loads(_read(state_path))
    matches = [item for item in state["targets"] if item.get("target_id") == EDITION_ID]
    if len(matches) != 1 or matches[0].get("stage") != "review":
        raise ValueError("proposed stage work must have one review-stage edition target")
    matches[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=reviewed_at)
    for evidence in (EDITION / "master.tei.xml", EDITION / "acceptance.json"):
        if evidence.as_posix() not in matches[0]["evidence"]:
            matches[0]["evidence"].append(evidence.as_posix())
    write_acceptance(io_path(acceptance_path), acceptance)
    _write_json(stage, WORK / "state.json", state)
    validate_acceptance(io_path(acceptance_path), root=io_path(stage))
    validate_state(io_path(state_path), root=io_path(stage))

    # This call is deliberately the normal maintained accepted-context route.
    projection, errors, executed_python_bindings = _project_and_verify(stage, acceptance_path)
    if errors or len(projection["rows"]) != 1:
        raise ValueError(f"maintained Guyon accepted-master projection failed: {errors[:3]}")
    runtime_python_bindings = _runtime_python_bindings()
    runtime_resource_bindings = _runtime_resource_bindings()
    for relative, digest in runtime_python_bindings.items():
        _copy_input(stage, Path(relative), expected_sha=digest)
    for relative, digest in runtime_resource_bindings.items():
        _copy_input(stage, Path(relative), expected_sha=digest)
    projection_path = _write_json(stage, EVIDENCE / "actual-master-projection.json", projection)

    # A file map plus every copied non-work input lets the installer fail closed
    # if either the stage or any source/runtime dependency changes.
    external_inputs = {
        path: digest for path, digest in _files(stage).items()
        if not path.startswith(WORK.as_posix() + "/") and path != RECEIPT_NAME
    }
    if _files(ROOT / WORK):
        raise ValueError("canonical Guyon work appeared while stage was being prepared")
    after = _files(stage / WORK)
    receipt = {
        "contract": "ocd-guyon-pg24989-electronic-stage-v1",
        "status": "staged-only", "stage_root": stage.as_posix(),
        "canonical_root": ROOT.as_posix(), "work_id": WORK_ID,
        "identity": IDENTITY,
        "identity_proposal_sha256": _sha(proposal_raw),
        "identity_review_sha256": _sha(identity_review_raw),
        "master_draft_sha256": MASTER_DRAFT_SHA,
        "parent_master_review_sha256": _sha(parent_master_review_raw),
        "source_manifest_sha256": manifest.sha256,
        "combined_runtime_plan_sha256": COMBINED_RUNTIME_PLAN_SHA,
        "combined_runtime_readback_sha256": COMBINED_RUNTIME_READBACK_SHA,
        "source_member_set_sha256": SOURCE_MEMBER_SET_SHA,
        "candidate_package_sha256": package.sha256,
        "candidate_validation_sha256": _sha(validation_bytes),
        "oracle_result_sha256": report.attestation.get("result_sha256"),
        "source_review_sha256": SOURCE_READBACK_SHA,
        "semantic_challenges_sha256": CHALLENGE_RECEIPT_SHA,
        "alias_receipt_sha256": ALIAS_RECEIPT_SHA,
        "source_notice_sha256": SOURCE_NOTICE_SHA,
        "inventory_newline_receipt_sha256": INVENTORY_NEWLINE_RECEIPT_SHA,
        "after": after,
        "external_inputs": external_inputs,
        "acceptance_path": (EDITION / "acceptance.json").as_posix(),
        "acceptance_sha256": _sha(_read(acceptance_path)),
        "master_path": (EDITION / "master.tei.xml").as_posix(),
        "master_sha256": _sha(_read(master_path)),
        "candidate_path": (EVIDENCE / "candidate.tei.xml").as_posix(),
        "candidate_sha256": _sha(_read(candidate_path)),
        "projection_path": (EVIDENCE / "actual-master-projection.json").as_posix(),
        "projection_sha256": _sha(_read(projection_path)),
        "projection_rows": len(projection["rows"]),
        "projection_independent_errors": errors,
        "runtime_python_bindings": runtime_python_bindings,
        "executed_python_bindings": executed_python_bindings,
        "runtime_resource_bindings": runtime_resource_bindings,
        "projection_receipt_sha256_fields": _receipt_sha256_fields(projection["receipt"]),
        "rights_clearance": "not-assessed",
        "human_acceptance": "not-recorded",
        "installation": "not-performed",
    }
    _write_json(stage, Path(RECEIPT_NAME), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.stage), sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
