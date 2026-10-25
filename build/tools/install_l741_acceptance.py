"""Freeze, preflight, and guarded-install exactly one L741 accepted work generation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.hymns import project_accepted_hymns, verify_accepted_hymns
from ocd_kernel.tei.acceptance import _validate_acceptance_for_work, validate_acceptance
from ocd_kernel.tei.install_accepted import _files, install_accepted_work


ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / ".tmp_audit/c"
WORK_ID = "evangelische-gezangen-1806"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms/evangelische-gezangen-1806-dbnl-retained/editions/evangelische-gezangen-1806-dbnl-electronic"
ACCEPTANCE = EDITION / "acceptance.json"
HANDOFF = STAGE / "l741-install-handoff-v3.json"
METADATA_HANDOFF = ROOT / ".tmp_audit/m/l741-metadata-handoff.json"
METADATA_RESULT = ROOT / ".tmp_audit/m/l741-metadata-install-result.json"
METADATA_HANDOFF_SHA256 = "461693301abeb11f92a53ff26ee300fce02d2b62c5028a6729486b55f15f6945"
RELEASE_FILES = (
    "internal/release-selection.json",
    "internal/release-report.json",
    "internal/work-coverage.json",
    "internal/checks/independent-check.json",
    "internal/projection-receipts/l741-gezangen.json",
    "public/data/hymns/train.jsonl",
    "public/data/hymns/train.arrow",
    "public/README.md",
)
SOURCE_NOTE = Path("sources/dbnl/evangelische-gezangen-1806/README.source.md")
PUBLIC_NOTICE = Path("data/hymns/evangelische-gezangen-1806/README.md")
EXPECTED_BEFORE = {
    "work.json": "0515ccc32f4c5b7aa8c45542057ad92080162daa716bb4f9bc8d0e2941d878ee",
    "state.json": "6b27f9758a52831cfb4b44d349f9fd6b2c6ab991f4e1571e92ddb06a1c109c32",
    "forms/evangelische-gezangen-1806-dbnl-retained/editions/evangelische-gezangen-1806-dbnl-electronic/acquisitions/evangelische-gezangen-1806-dbnl-acquired.json": "b694e97b4560799b8e8027e5d53ed7dee9341e01319f20ac5f3a72f90a634e29",
}
ORIGINAL_WORK_SHA256 = "a2cf66e3e7c5c7916669fd6c098f21d448a63029de311f55ff580b604d2d8e13"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_stage(*, allow_pending_metadata: bool) -> dict[str, str]:
    if not STAGE.is_dir() or STAGE.parent != ROOT / ".tmp_audit":
        raise PipelineError("L741 stage location differs")
    live = _files(ROOT / WORK)
    allowed = [EXPECTED_BEFORE]
    if allow_pending_metadata:
        allowed.append(EXPECTED_BEFORE | {"work.json": ORIGINAL_WORK_SHA256})
    if live not in allowed:
        raise PipelineError("L741 canonical work preimage differs")
    if (ROOT / EDITION / "master.tei.xml").exists() or (ROOT / ACCEPTANCE).exists():
        raise PipelineError("L741 canonical master or acceptance already exists")
    after = _files(STAGE / WORK)
    if after.get(next(key for key in EXPECTED_BEFORE if key.endswith("acquired.json"))) != next(
        value for key, value in EXPECTED_BEFORE.items() if key.endswith("acquired.json")
    ):
        raise PipelineError("L741 acquisition sidecar changed in stage")
    if set(after) - set(EXPECTED_BEFORE) != {
        "forms/evangelische-gezangen-1806-dbnl-retained/editions/evangelische-gezangen-1806-dbnl-electronic/acceptance-candidate.tei.xml",
        "forms/evangelische-gezangen-1806-dbnl-retained/editions/evangelische-gezangen-1806-dbnl-electronic/acceptance.json",
        "forms/evangelische-gezangen-1806-dbnl-retained/editions/evangelische-gezangen-1806-dbnl-electronic/master.tei.xml",
        *{f"integration/l741-dbnl-electronic-v1/{name}.json" for name in (
            "accounting", "closure", "fidelity", "reproducibility", "review", "schema",
            "source-accounting", "validation")},
        "integration/l741-dbnl-electronic-v1/candidate.tei.xml",
    }:
        raise PipelineError("L741 stage file additions differ")
    for relative in (SOURCE_NOTE, PUBLIC_NOTICE):
        if _sha(ROOT / relative) != _sha(STAGE / relative):
            raise PipelineError(f"L741 source-bound notice differs: {relative}")
    validate_acceptance(STAGE / ACCEPTANCE, root=STAGE)
    validate_state(STAGE / WORK / "state.json", root=STAGE)
    projected = project_accepted_hymns(STAGE, acceptance_path=STAGE / ACCEPTANCE)
    if len(projected["rows"]) != 192 or len(projected["rows"][45]["sections"]) != 6:
        raise PipelineError("L741 staged hymn projection count differs")
    if issues := verify_accepted_hymns(
        STAGE, acceptance_path=STAGE / ACCEPTANCE, rows=projected["rows"],
        receipt=projected["receipt"],
    ):
        raise PipelineError(f"L741 independent staged projection failed: {issues[:3]}")
    return after


def _release_artifacts() -> dict[str, str]:
    release = ROOT / ".tmp_audit/l741-release-v4"
    artifacts = {relative: _sha(release / relative) for relative in RELEASE_FILES}
    report = json.loads((release / "internal/release-report.json").read_text(encoding="utf-8"))
    independent = json.loads((release / "internal/checks/independent-check.json").read_text(encoding="utf-8"))
    projection = json.loads((release / "internal/projection-receipts/l741-gezangen.json").read_text(encoding="utf-8"))
    rows = (release / "public/data/hymns/train.jsonl").read_text(encoding="utf-8").splitlines()
    card = (release / "public/README.md").read_text(encoding="utf-8")
    if (report.get("status") != "pass" or independent != {"status": "pass", "errors": []}
            or len(report.get("configurations", [])) != 1
            or report["configurations"][0].get("row_count") != 192
            or report["configurations"][0].get("category") != "hymns"
            or projection.get("row_count") != 192
            or projection.get("source_sha256") != "d8132943dd20b1053d1d77bda57cab2b69c9dc567e38ea4450baab914925abb9"
            or projection.get("master_sha256") != "e35cf3cf9989e5f40be0a1ffa61dd3db7d284bbd4fef22eeb8560f47ac5f84c1"
            or projection.get("source_credit", {}).get("recommended_credit") != "geraadpleegd via DBNL (KB, nationale bibliotheek)"
            or len(rows) != 192
            or "geraadpleegd via DBNL (KB, nationale bibliotheek)" not in card
            or "68 score GIF" not in card):
        raise PipelineError("L741 release status, source/notice binding, or 192-row scope differs")
    return artifacts


def _metadata_receipts(*, require_installed: bool) -> None:
    if _sha(METADATA_HANDOFF) != METADATA_HANDOFF_SHA256:
        raise PipelineError("L741 prior metadata handoff SHA-256 differs")
    handoff = json.loads(METADATA_HANDOFF.read_text(encoding="utf-8"))
    if handoff.get("after", {}).get("work.json") != EXPECTED_BEFORE["work.json"]:
        raise PipelineError("L741 prior metadata handoff postimage differs")
    if not require_installed:
        return
    result = json.loads(METADATA_RESULT.read_text(encoding="utf-8"))
    journal = Path(result["operation_journal"]).resolve(strict=True)
    if ROOT not in journal.parents or journal.name != "operation.json":
        raise PipelineError("L741 metadata journal path differs")
    operation = json.loads(journal.read_text(encoding="utf-8"))
    if (result.get("contract") != "ocd-l741-metadata-install-result-v1"
            or result.get("status") != "installed-and-validated"
            or result.get("handoff_sha256") != METADATA_HANDOFF_SHA256
            or result.get("before", {}).get("work.json") != ORIGINAL_WORK_SHA256
            or result.get("after") != EXPECTED_BEFORE
            or result.get("operation_journal_sha256") != _sha(journal)
            or operation.get("phase") != "complete"
            or operation.get("result_status") != "installed-and-validated"
            or operation.get("work_id") != WORK_ID
            or operation.get("operation_kind") != "l741-category-language-metadata"
            or operation.get("before") != EXPECTED_BEFORE | {"work.json": ORIGINAL_WORK_SHA256}
            or operation.get("after") != EXPECTED_BEFORE):
        raise PipelineError("L741 prior metadata installation receipt differs")


def freeze() -> dict[str, object]:
    if HANDOFF.exists():
        raise PipelineError("L741 install handoff already exists")
    after = _validate_stage(allow_pending_metadata=True)
    artifacts = _release_artifacts()
    _metadata_receipts(require_installed=False)
    receipt = {
        "contract": "ocd-l741-guarded-install-handoff-v3",
        "status": "awaiting-guarded-metadata-update",
        "work_id": WORK_ID,
        "stage_root": STAGE.relative_to(ROOT).as_posix(),
        "before": EXPECTED_BEFORE,
        "required_prior_metadata_handoff_sha256": METADATA_HANDOFF_SHA256,
        "after": after,
        "removed_files": [],
        "source_notice": {"path": SOURCE_NOTE.as_posix(), "sha256": _sha(ROOT / SOURCE_NOTE)},
        "public_notice": {"path": PUBLIC_NOTICE.as_posix(), "sha256": _sha(ROOT / PUBLIC_NOTICE)},
        "release_artifacts": artifacts,
        "publication": "not-performed",
        "human_acceptance": "not-recorded",
        "rights_clearance": "not-determined",
        "canonical_install": "not-performed",
    }
    HANDOFF.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"handoff": str(HANDOFF), "handoff_sha256": _sha(HANDOFF),
            "before_files": len(EXPECTED_BEFORE), "after_files": len(after),
            "additions": len(set(after) - set(EXPECTED_BEFORE)), "removals": 0}


def preflight(expected_sha256: str) -> dict[str, object]:
    if _sha(HANDOFF) != expected_sha256:
        raise PipelineError("L741 handoff SHA-256 differs")
    receipt = json.loads(HANDOFF.read_text(encoding="utf-8"))
    if (receipt.get("contract") != "ocd-l741-guarded-install-handoff-v3"
            or receipt.get("status") != "awaiting-guarded-metadata-update"
            or receipt.get("required_prior_metadata_handoff_sha256") != METADATA_HANDOFF_SHA256
            or receipt.get("canonical_install") != "not-performed"):
        raise PipelineError("L741 handoff status differs")
    after = _validate_stage(allow_pending_metadata=True)
    if receipt["before"] != EXPECTED_BEFORE or receipt["after"] != after or receipt["removed_files"]:
        raise PipelineError("L741 handoff file generation differs")
    for key, relative in (("source_notice", SOURCE_NOTE), ("public_notice", PUBLIC_NOTICE)):
        if receipt[key] != {"path": relative.as_posix(), "sha256": _sha(ROOT / relative)}:
            raise PipelineError(f"L741 {key} binding differs")
    if receipt.get("release_artifacts") != _release_artifacts():
        raise PipelineError("L741 offline release artifact hashes differ")
    live = _files(ROOT / WORK)
    status = "ready-to-install" if live == EXPECTED_BEFORE else "awaiting-guarded-metadata-update"
    _metadata_receipts(require_installed=status == "ready-to-install")
    return {"status": status, "work_id": WORK_ID,
            "handoff_sha256": expected_sha256, "files_after": len(after),
            "master_sha256": after[(EDITION / "master.tei.xml").relative_to(WORK).as_posix()],
            "acceptance_sha256": after[ACCEPTANCE.relative_to(WORK).as_posix()]}


def apply(expected_sha256: str) -> dict[str, object]:
    ready = preflight(expected_sha256)
    if ready["status"] != "ready-to-install":
        raise PipelineError("L741 category/language metadata update must complete first")

    def checkpoint(point: str) -> None:
        if point == "after-incoming":
            if preflight(expected_sha256)["status"] != "ready-to-install":
                raise PipelineError("L741 frozen acceptance handoff changed under installer locks")
        elif point == "after-validated":
            _validate_acceptance_for_work(ROOT / ACCEPTANCE, root=ROOT, work_id=WORK_ID)
            validate_state(ROOT / WORK / "state.json", root=ROOT)
            projected = project_accepted_hymns(ROOT, acceptance_path=ROOT / ACCEPTANCE)
            if len(projected["rows"]) != 192 or verify_accepted_hymns(
                ROOT, acceptance_path=ROOT / ACCEPTANCE,
                rows=projected["rows"], receipt=projected["receipt"],
            ):
                raise PipelineError("L741 installed accepted projection failed")

    ready["installation"] = install_accepted_work(
        ROOT, STAGE, work_id=WORK_ID, fail_at=checkpoint,
        lock_acquire_timeout=30.0,
    )
    return ready


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "preflight", "apply"))
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    if args.action == "freeze":
        result = freeze()
    elif args.expected_sha256 is None:
        parser.error("preflight and apply require --expected-sha256")
    elif args.action == "preflight":
        result = preflight(args.expected_sha256)
    else:
        result = apply(args.expected_sha256)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
