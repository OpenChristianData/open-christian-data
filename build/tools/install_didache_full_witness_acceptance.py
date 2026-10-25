"""Preflight or explicitly install the frozen complete Didache electronic witness.

The default command is read-only. ``--apply`` commits exactly one complete
work generation through the shared lock, durable journal, and rollback path.
It does not refresh a corpus, clear rights, or publish anything.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path

from build.tei.didache_prayers_oracle import _oracle
from build.tools.preflight_didache_full_witness import MANIFEST, NEW_TITLE, SOURCE_SHA256
from build.tools.stage_didache_full_witness_acceptance import (
    ACQUISITION, CLAIM_LIMITS, EDITION, IDENTITY, PROJECTION_COUNTS,
    RECEIPT, ROOT, SOURCE_STAGE, WORK, WORK_DIR, _check_full_witness_rows,
    _read_json, _sha, preflight as preflight_stage,
)
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path


STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/didache-lake-accepted-s20260928-v5")
RECEIPT_SHA256 = "3ab42618c0ab4b38c0728b8bb8cb2a958ef4671718f99ed03f6a0cc5894896af"


def _work_map(full_paths: dict[str, str]) -> dict[str, str]:
    prefix = WORK_DIR.as_posix() + "/"
    if any(not name.startswith(prefix) for name in full_paths):
        raise PipelineError("Didache receipt includes a path outside its single work")
    return {name.removeprefix(prefix): digest for name, digest in full_paths.items()}


def _check_delta(root: Path, stage: Path) -> None:
    old_work = _read_json(root / WORK)
    new_work = _read_json(stage / WORK)
    expected_work = json.loads(json.dumps(old_work))
    if (old_work.get("work_id") != IDENTITY["work_id"]
            or len(expected_work.get("textual_forms", [])) != 1
            or len(expected_work["textual_forms"][0].get("editions", [])) != 1
            or "category" in expected_work["textual_forms"][0]["editions"][0]):
        raise PipelineError("Didache original work identity/category differs")
    expected_work["title"] = NEW_TITLE
    expected_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    if new_work != expected_work:
        raise PipelineError("Didache staged work exceeds title and prose-category changes")
    old_state = _read_json(root / WORK_DIR / "state.json")
    new_state = _read_json(stage / WORK_DIR / "state.json")
    expected_state = json.loads(json.dumps(old_state))
    targets = [item for item in expected_state["targets"] if item["target_id"] == IDENTITY["edition_id"]]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise PipelineError("Didache original edition state differs")
    at = next((item["updated_at"] for item in new_state["targets"]
               if item["target_id"] == IDENTITY["edition_id"]), None)
    try:
        parsed_at = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise PipelineError("Didache accepted state timestamp is invalid") from exc
    if parsed_at.tzinfo is None or parsed_at.utcoffset() != timezone.utc.utcoffset(parsed_at):
        raise PipelineError("Didache accepted state timestamp must be UTC")
    targets[0].update(
        stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=at,
        evidence=targets[0]["evidence"] + [
            (EDITION / "master.tei.xml").as_posix(),
            (EDITION / "acceptance.json").as_posix(),
        ],
    )
    if new_state != expected_state:
        raise PipelineError("Didache staged state exceeds one edition acceptance transition")
    if _io_path(root / ACQUISITION).read_bytes() != _io_path(stage / ACQUISITION).read_bytes():
        raise PipelineError("Didache acquired source sidecar changed")


def _check_master(root: Path, stage: Path, receipt: dict) -> None:
    acceptance = stage / EDITION / "acceptance.json"
    accepted = validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK_DIR / "state.json"), root=_io_path(stage))
    decision = accepted["decision"]
    if (accepted["promotion"]["status"] != "promoted"
            or accepted["identity"] != IDENTITY
            or decision["agent_assessment"]["status"] != "accepted"
            or decision["human_decision"]["status"] != "not-recorded"
            or receipt["claim_limits"] != list(CLAIM_LIMITS)):
        raise PipelineError("Didache stage overstates its technical acceptance authority")
    master = _io_path(stage / EDITION / "master.tei.xml").read_bytes()
    original = CandidatePackage.load(SOURCE_STAGE / "package").member_bytes("content.tei.xml")
    if (original.split(b"</teiHeader>", 1)[1] != master.split(b"</teiHeader>", 1)[1]
            or _sha(master) != receipt["master_sha256"]
            or _sha(_io_path(acceptance).read_bytes()) != receipt["acceptance_sha256"]):
        raise PipelineError("Didache accepted header or exact master binding differs")
    projected = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance))
    errors = verify_accepted_prose(
        _io_path(stage), acceptance_path=_io_path(acceptance),
        rows=projected["rows"], receipt=projected["receipt"],
    )
    if errors or receipt["projection_counts"] != PROJECTION_COUNTS:
        raise PipelineError(f"Didache independent native prose verification differs: {errors[:3]}")
    _check_full_witness_rows(projected["rows"])


def preflight(expected_receipt_sha256: str) -> dict:
    if expected_receipt_sha256 != RECEIPT_SHA256:
        raise PipelineError("Didache installer requires the exact frozen v5 receipt pin")
    root = ROOT.resolve(strict=True)
    stage = STAGE.resolve(strict=True)
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("Didache stage and canonical roots overlap")
    preflight_stage(stage, expected_receipt_sha256)
    receipt = _read_json(stage / RECEIPT)
    if (receipt.get("contract") != "ocd-didache-full-witness-accepted-stage-v1"
            or receipt.get("status") != "staged-only"
            or receipt.get("canonical_install") is not False
            or receipt.get("work_id") != IDENTITY["work_id"]
            or receipt.get("source_sha256") != SOURCE_SHA256):
        raise PipelineError("Didache frozen acceptance receipt claim differs")
    before = _work_map(receipt["before"])
    after = _work_map(receipt["after"])
    if _files(root / WORK_DIR) != before or _files(stage / WORK_DIR) != after:
        raise PipelineError("Didache complete work preimage or staged generation differs")
    if (set(before) != {"work.json", "state.json", ACQUISITION.relative_to(WORK_DIR).as_posix()}
            or len(after) != 21):
        raise PipelineError("Didache exact work-generation scope differs")
    _check_delta(root, stage)
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    manifest.verify()
    package = CandidatePackage.load(SOURCE_STAGE / "package")
    report = validate(manifest, package, _oracle)
    validation = _read_json(SOURCE_STAGE / "validation.json")
    if (report.status != "pass" or report.findings
            or report.sha256 != validation["report_sha256"]
            or package.sha256 != receipt["source_candidate_sha256"]):
        raise PipelineError("Didache fresh independent source oracle differs")
    _check_master(root, stage, receipt)
    return {
        "status": "ready-for-review", "installation": "not-performed",
        "work_id": IDENTITY["work_id"], "receipt_sha256": RECEIPT_SHA256,
        "before_files": len(before), "after_files": len(after),
        "native_rows": PROJECTION_COUNTS["rows"],
        "human_verification": "not-recorded", "rights": "unresolved",
    }


def install(expected_receipt_sha256: str, *, fail_at: Callable[[str], None] | None = None) -> dict:
    root = ROOT.resolve(strict=True)
    stage = STAGE.resolve(strict=True)
    target, source = root / WORK_DIR, stage / WORK_DIR
    with ExitStack() as locks:
        for path in sorted((target, source), key=lambda item: item.as_posix()):
            locks.enter_context(acquire_jsonl_lock(path, acquire_timeout=30.0))
        preflight(expected_receipt_sha256)
        receipt = _read_json(stage / RECEIPT)

        def checkpoint(point: str) -> None:
            if point == "after-validated":
                if _files(target) != _work_map(receipt["after"]):
                    raise PipelineError("Didache installed work generation differs")
                acceptance = root / EDITION / "acceptance.json"
                validate_acceptance(_io_path(acceptance), root=_io_path(root))
                validate_state(_io_path(root / WORK_DIR / "state.json"), root=_io_path(root))
                projected = project_accepted_prose(_io_path(root), acceptance_path=_io_path(acceptance))
                errors = verify_accepted_prose(
                    _io_path(root), acceptance_path=_io_path(acceptance),
                    rows=projected["rows"], receipt=projected["receipt"],
                )
                if errors:
                    raise PipelineError(f"Didache installed native verification differs: {errors[:3]}")
                _check_full_witness_rows(projected["rows"])
            if fail_at is not None:
                fail_at(point)

        return _commit_generation(
            root, target, source, work_id=IDENTITY["work_id"],
            before=_work_map(receipt["before"]), after=_work_map(receipt["after"]),
            existed=True, replacement=False,
            operation_kind="didache-lake-full-witness-technical-acceptance-install",
            result_status="installed-and-validated", accepted_editions=1,
            fail_at=checkpoint,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-receipt-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = install(args.expected_receipt_sha256) if args.apply else preflight(args.expected_receipt_sha256)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
