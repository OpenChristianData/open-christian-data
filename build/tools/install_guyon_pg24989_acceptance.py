"""Preflight a frozen Guyon acceptance stage; apply only with explicit --apply.

The maintained atomic installer owns the generation handoff. This caller adds
source, identity, stage, runtime, native-projection, and readback guards around
that one-work installation. Default execution is read-only.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

from ocd_kernel.lib.path_io import io_path
from ocd_kernel.library.acquisitions import source_member_set_bytes, validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    project_accepted_document,
    verify_accepted_document,
)
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import (
    _files,
    _validate_promoted_tree,
    _validate_state_transition,
    install_accepted_work,
    read_accepted_work,
)
from ocd_kernel.tei.validate import validate_file
from build.tei.guyon_short_method_24989_v16_oracle import _oracle

from build.tools.stage_guyon_pg24989_acceptance import (
    ALIAS_RECEIPT,
    ALIAS_RECEIPT_SHA,
    CANDIDATE_MANIFEST_SHA,
    CANDIDATE_VALIDATION_SHA,
    CANDIDATE_TEI_SHA,
    COMBINED_RUNTIME_PLAN,
    COMBINED_RUNTIME_PLAN_SHA,
    COMBINED_RUNTIME_READBACK,
    COMBINED_RUNTIME_READBACK_SHA,
    EDITION,
    EVIDENCE,
    IDENTITY,
    IDENTITY_REVIEW,
    IDENTITY_REVIEW_SHA,
    INVENTORY_NEWLINE_RECEIPT_SHA,
    MASTER_DRAFT_SHA,
    MEMBER_SET,
    PARENT_MASTER_REVIEW,
    PARENT_MASTER_REVIEW_SHA,
    PROPOSAL,
    PROPOSAL_SHA,
    RECEIPT_NAME,
    ROOT,
    SOURCE_MANIFEST,
    SOURCE_MANIFEST_SHA,
    SOURCE_MEMBER_SET_SHA,
    SOURCE_NOTICE_SHA,
    SOURCE_READBACK,
    SOURCE_READBACK_SHA,
    CHALLENGE_RECEIPT,
    CHALLENGE_RECEIPT_SHA,
    WORK,
    WORK_ID,
    _project_and_verify,
    _runtime_python_bindings,
    _runtime_resource_bindings,
    _receipt_sha256_fields,
    _read,
    _sha,
)


def _json(path: Path) -> dict:
    value = json.loads(_read(path))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _unexpected_executed_bindings(observed: dict, expected: object) -> dict[str, str]:
    """Return executed code absent from or changed against the staged proof.

    The stage projection runs before installation in this same process. A
    second projection can therefore omit a previously executed function's
    module from its per-call trace. The complete loaded-module closure is
    checked separately and exactly; every module actually executed again must
    still match the frozen executed-code pins.
    """
    if not isinstance(observed, dict) or not isinstance(expected, dict):
        return {"<binding-map>": "invalid binding map"}
    return {
        path: digest
        for path, digest in observed.items()
        if not isinstance(path, str) or not isinstance(digest, str) or expected.get(path) != digest
    }


def _schema_check(path: Path) -> None:
    errors = validate_file(io_path(path))
    if errors:
        raise ValueError(f"Guyon master failed maintained P5 validation: {errors[:3]}")


def _verify_external_inputs(stage: Path, receipt: dict, *, after_flow: bool = False) -> None:
    current_python = _runtime_python_bindings()
    expected_python = receipt.get("runtime_python_bindings")
    python_matches = (current_python == expected_python if after_flow else
                      isinstance(expected_python, dict) and all(expected_python.get(path) == digest
                                                                 for path, digest in current_python.items()))
    if (not python_matches or _runtime_resource_bindings() != receipt.get("runtime_resource_bindings")):
        raise ValueError("Guyon loaded first-party runtime or schema resources differ from the frozen stage")
    if (receipt.get("combined_runtime_plan_sha256") != COMBINED_RUNTIME_PLAN_SHA
            or receipt.get("combined_runtime_readback_sha256") != COMBINED_RUNTIME_READBACK_SHA):
        raise ValueError("Guyon combined runtime source receipt pins differ")
    if receipt.get("inventory_newline_receipt_sha256") != INVENTORY_NEWLINE_RECEIPT_SHA:
        raise ValueError("Guyon retained inventory newline-accounting receipt pin differs")
    expected_external = receipt.get("external_inputs")
    if not isinstance(expected_external, dict):
        raise ValueError("Guyon stage lacks its external input hash inventory")
    actual_external = {
        path: digest for path, digest in _files(stage).items()
        if not path.startswith(WORK.as_posix() + "/") and path != RECEIPT_NAME
    }
    if actual_external != expected_external:
        raise ValueError("Guyon stage external input inventory differs")
    for relative, digest in expected_external.items():
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"unsafe Guyon stage input path: {relative}")
        if _sha(_read(stage / rel)) != digest or _sha(_read(ROOT / rel)) != digest:
            raise ValueError(f"Guyon frozen external input changed: {relative}")


def preflight(stage_arg: Path, receipt_sha256: str) -> dict:
    stage = stage_arg.resolve(strict=True)
    candidate_root = Path(r"D:\Library\Open Christian Data\candidate-reviews").resolve(strict=True)
    if (stage.parent != candidate_root or not stage.name.startswith("guyon-pg24989-acceptance-stage-")
            or ROOT.resolve(strict=True) in stage.parents):
        raise ValueError("Guyon stage must be a direct child of the governed candidate-reviews directory")
    receipt_path = stage / RECEIPT_NAME
    receipt_bytes = _read(receipt_path)
    if _sha(receipt_bytes) != receipt_sha256:
        raise ValueError("Guyon stage receipt hash differs from the exact caller pin")
    receipt = json.loads(receipt_bytes)
    if (receipt.get("contract") != "ocd-guyon-pg24989-electronic-stage-v1"
            or receipt.get("status") != "staged-only"
            or receipt.get("stage_root") != stage.as_posix()
            or Path(receipt.get("canonical_root", "")).resolve(strict=True) != ROOT.resolve(strict=True)
            or receipt.get("work_id") != WORK_ID
            or receipt.get("identity") != IDENTITY
            or receipt.get("installation") != "not-performed"
            or receipt.get("human_acceptance") != "not-recorded"
            or receipt.get("rights_clearance") != "not-assessed"):
        raise ValueError("Guyon stage receipt scope or status differs")
    _verify_external_inputs(stage, receipt)

    canonical_work = ROOT / WORK
    if io_path(canonical_work).exists() or io_path(canonical_work).is_symlink() or io_path(canonical_work).is_junction():
        raise ValueError("canonical Guyon work appeared; reviewed initial-install preimage changed")
    staged_work = stage / WORK
    after = _files(staged_work)
    if after != receipt.get("after"):
        raise ValueError("complete staged Guyon work generation differs from receipt")
    master = stage / EDITION / "master.tei.xml"
    candidate = stage / EVIDENCE / "candidate.tei.xml"
    acceptance_path = stage / EDITION / "acceptance.json"
    accounting_path = stage / EVIDENCE / "source-accounting.json"
    if (_sha(_read(master)) != MASTER_DRAFT_SHA or _sha(_read(candidate)) != MASTER_DRAFT_SHA
            or _read(master) != _read(candidate)
            or _sha(_read(master)) != receipt.get("master_sha256")
            or _sha(_read(acceptance_path)) != receipt.get("acceptance_sha256")
            or _sha(_read(candidate)) != receipt.get("candidate_sha256")
            or _sha(_read(staged_work / "SOURCE_NOTICE.md")) != SOURCE_NOTICE_SHA):
        raise ValueError("Guyon accepted master, candidate, notice or acceptance binding differs")
    _schema_check(master)
    _schema_check(candidate)

    proposal = _json(ROOT / PROPOSAL)
    if (_sha(_read(ROOT / PROPOSAL)) != PROPOSAL_SHA
            or _sha(_read(ROOT / IDENTITY_REVIEW)) != IDENTITY_REVIEW_SHA
            or _sha(_read(ROOT / PARENT_MASTER_REVIEW)) != PARENT_MASTER_REVIEW_SHA
            or _sha(_read(ROOT / SOURCE_READBACK)) != SOURCE_READBACK_SHA
            or _sha(_read(ROOT / CHALLENGE_RECEIPT)) != CHALLENGE_RECEIPT_SHA
            or _sha(_read(ROOT / ALIAS_RECEIPT)) != ALIAS_RECEIPT_SHA
            or proposal.get("identity") != IDENTITY
            or proposal.get("canonical_write_performed") is not False):
        raise ValueError("Guyon identity/source review authorities differ from reviewed pins")
    work = load_work(io_path(staged_work / "work.json"))
    if work != proposal["proposed_records"]["work.json"]:
        raise ValueError("staged Guyon work metadata differs from reviewed proposal")
    acquisition = validate_acquisition(io_path(staged_work / Path("forms/english/editions/jeanne-guyon-short-method-prayer-pg24989/acquisitions/pg24989-retained-zip.json")), root=io_path(stage))
    if acquisition != proposal["proposed_records"]["acquisition.json"]:
        raise ValueError("staged Guyon acquisition differs from reviewed proposal")
    member_set = _read(stage / MEMBER_SET)
    if _sha(member_set) != SOURCE_MEMBER_SET_SHA or member_set != source_member_set_bytes(acquisition):
        raise ValueError("staged Guyon source-member-set bytes differ")
    validate_state(io_path(staged_work / "state.json"), root=io_path(stage))
    state = _json(staged_work / "state.json")
    edition_targets = [item for item in state["targets"] if item.get("target_id") == IDENTITY["edition_id"]]
    if len(edition_targets) != 1 or edition_targets[0].get("stage") != "accepted":
        raise ValueError("staged Guyon edition target is not accepted")

    staged_manifest = SourceManifest.load(io_path(stage / SOURCE_MANIFEST), repository_root=io_path(stage))
    if staged_manifest.sha256 != SOURCE_MANIFEST_SHA:
        raise ValueError("staged Guyon source manifest differs")
    staged_manifest.verify()
    source_manifest = SourceManifest.load(io_path(ROOT / SOURCE_MANIFEST), repository_root=io_path(ROOT))
    if source_manifest.sha256 != staged_manifest.sha256:
        raise ValueError("canonical Guyon source manifest differs from its staged authority copy")
    source_manifest.verify()
    package = CandidatePackage.load(io_path(stage / EVIDENCE / "inputs/candidate-package"))
    if package.sha256 != CANDIDATE_MANIFEST_SHA or _sha(package.member_bytes("content.tei.xml")) != CANDIDATE_TEI_SHA:
        raise ValueError("staged frozen Guyon candidate package differs")
    report = validate(source_manifest, package, _oracle)
    if (report.status != "pass" or report.findings
            or report.attestation.get("result_sha256") != receipt.get("oracle_result_sha256")):
        raise ValueError("fresh staged Guyon source oracle differs")
    if _sha(_read(stage / EVIDENCE / "inputs/candidate-validation.json")) != CANDIDATE_VALIDATION_SHA:
        raise ValueError("staged outer candidate validation sidecar differs")

    acceptance = validate_acceptance(io_path(acceptance_path), root=io_path(stage))
    validate_state(io_path(staged_work / "state.json"), root=io_path(stage))
    accepted = _validate_promoted_tree(io_path(stage), io_path(staged_work), work_id=WORK_ID)
    if (len(accepted) != 1 or accepted[0]["identity"] != IDENTITY
            or accepted[0]["decision"]["agent_assessment"]["status"] != "accepted"
            or accepted[0]["decision"]["human_decision"]["status"] != "not-recorded"
            or accepted[0]["promotion"]["status"] != "promoted"):
        raise ValueError("Guyon promoted stage does not bind the authorized electronic-witness-only decision")
    _validate_state_transition(canonical_work, staged_work, existed=False, replacement=False,
        accepted_evidence_by_edition={IDENTITY["edition_id"]: (
            (EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix())})

    _verify_external_inputs(stage, receipt)
    projection, errors, executed_python_bindings = _project_and_verify(stage, acceptance_path)
    if (errors or projection != _json(stage / EVIDENCE / "actual-master-projection.json")
            or executed_python_bindings != receipt.get("executed_python_bindings")
            or _receipt_sha256_fields(projection.get("receipt")) != receipt.get("projection_receipt_sha256_fields")
            or projection.get("rows") != json.loads(_read(stage / EVIDENCE / "actual-master-projection.json")).get("rows")
            or len(projection.get("rows", [])) != 1):
        raise ValueError(f"Guyon maintained accepted-master projection changed: {errors[:3]}")

    _verify_external_inputs(stage, receipt, after_flow=True)
    return {
        "status": "ready-for-parent-review; no canonical apply performed",
        "canonical_root": ROOT.as_posix(),
        "canonical_work_preimage": {"exists": False},
        "stage_root": stage.as_posix(),
        "stage_receipt_path": receipt_path.as_posix(),
        "stage_receipt_sha256": receipt_sha256,
        "stage_file_count": len(after),
        "stage_generation_sha256": _sha(json.dumps(after, sort_keys=True, separators=(",", ":")).encode()),
        "identity": IDENTITY,
        "acceptance_sha256": _sha(_read(acceptance_path)),
        "master_sha256": _sha(_read(master)),
        "source_notice_sha256": SOURCE_NOTICE_SHA,
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_package_sha256": package.sha256,
        "oracle_result_sha256": report.attestation.get("result_sha256"),
        "runtime_python_bindings": receipt.get("runtime_python_bindings"),
        "executed_python_bindings": receipt.get("executed_python_bindings"),
        "projection_receipt_sha256_fields": _receipt_sha256_fields(projection.get("receipt")),
        "projection_rows": len(projection["rows"]),
        "projection_sha256": _sha(_read(stage / EVIDENCE / "actual-master-projection.json")),
        "human_acceptance": "not-recorded",
        "rights_clearance": "not-assessed",
        "installation": "not-performed",
    }


def apply(stage: Path, receipt_sha256: str) -> dict:
    preflight(stage, receipt_sha256)
    # The maintained installer acquires the canonical and stage locks, checks
    # the complete generation, journals preimages, and performs atomic handoff.
    result = install_accepted_work(ROOT, stage, work_id=WORK_ID)
    stage_receipt = _json(stage / RECEIPT_NAME)
    _verify_external_inputs(stage, stage_receipt, after_flow=True)
    installed = read_accepted_work(ROOT, work_id=WORK_ID)
    if _files(io_path(installed)) != _files(stage / WORK):
        raise ValueError("installed Guyon work differs from reviewed stage generation")
    installed_acceptance = Path(installed) / EDITION.relative_to(WORK) / "acceptance.json"
    if not io_path(installed_acceptance).is_file():
        raise ValueError("installed Guyon work lacks its exact expected acceptance path")
    validate_acceptance(io_path(installed_acceptance), root=io_path(ROOT))
    validate_state(io_path(Path(installed) / "state.json"), root=io_path(ROOT))
    projection, errors, executed_python_bindings = _project_and_verify(ROOT, installed_acceptance)
    staged_projection = _json(stage / EVIDENCE / "actual-master-projection.json")
    executed_bindings_not_pinned = _unexpected_executed_bindings(
        executed_python_bindings, stage_receipt.get("executed_python_bindings")
    )
    runtime_python_bindings = _runtime_python_bindings()
    if (errors or projection != staged_projection
            or executed_bindings_not_pinned
            or runtime_python_bindings != stage_receipt.get("runtime_python_bindings")):
        raise ValueError(
            "installed Guyon accepted-master readback differs: "
            f"projection_errors={errors[:3]}, executed_unpinned={executed_bindings_not_pinned}, "
            f"runtime_closure_equal={runtime_python_bindings == stage_receipt.get('runtime_python_bindings')}"
        )
    return {
        "status": "installed-and-verified",
        "install_result": result,
        "work_id": WORK_ID,
        "installed_path": Path(installed).as_posix(),
        "installed_file_count": len(_files(io_path(installed))),
        "acceptance_sha256": _sha(_read(installed_acceptance)),
        "master_sha256": _sha(_read(Path(installed_acceptance).parent / "master.tei.xml")),
        "source_notice_sha256": _sha(_read(ROOT / WORK / "SOURCE_NOTICE.md")),
        "projection_rows": len(projection["rows"]),
        "projection": projection,
        "runtime_python_bindings": runtime_python_bindings,
        "executed_python_bindings": executed_python_bindings,
        "executed_bindings_not_reexecuted_after_stage_projection": sorted(
            set(stage_receipt["executed_python_bindings"]) - set(executed_python_bindings)
        ),
        "human_acceptance": "not-recorded",
        "rights_clearance": "not-assessed",
        "public_publication": "not-performed",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--apply", action="store_true", help="install the independently reviewed frozen stage")
    args = parser.parse_args()
    if len(args.receipt_sha256) != 64 or any(char not in "0123456789abcdef" for char in args.receipt_sha256):
        raise ValueError("receipt SHA-256 must be 64 lowercase hexadecimal characters")
    result = apply(args.stage, args.receipt_sha256) if args.apply else preflight(args.stage, args.receipt_sha256)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
