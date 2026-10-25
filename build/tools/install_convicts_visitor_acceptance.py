"""Preflight a frozen N18328 stage; install its complete work only with --apply."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.liturgies import project_accepted_liturgies, verify_accepted_liturgies
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path

from build.tools.stage_convicts_visitor_acceptance import (
    ACCEPTANCE, ACQUISITION, CANDIDATE, CANDIDATE_SHA, EDITION, EVIDENCE,
    MANIFEST, MANIFEST_SHA, MASTER, RECEIPT_NAME, ROOT, SOURCE, SOURCE_SHA, WORK,
)


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _scope(before: dict[str, str], after: dict[str, str], stage: Path) -> None:
    allowed = {"work.json", "state.json", MASTER.relative_to(WORK).as_posix(),
               ACCEPTANCE.relative_to(WORK).as_posix()}
    prefix = EVIDENCE.relative_to(WORK).as_posix() + "/"
    if not before or not after or not set(before).issubset(after):
        raise PipelineError("N18328 stage removed existing work files")
    for path in set(before) | set(after):
        if before.get(path) == after.get(path):
            continue
        if path in allowed:
            continue
        if path.startswith(prefix) and path not in before and path in after:
            continue
        raise PipelineError(f"N18328 staged unrelated work change: {path}")
    old_work = json.loads(_io_path(ROOT / WORK / "work.json").read_bytes())
    new_work = json.loads(_io_path(stage / WORK / "work.json").read_bytes())
    expected = json.loads(json.dumps(old_work))
    if len(expected["textual_forms"]) != 1 or len(expected["textual_forms"][0]["editions"]) != 1:
        raise PipelineError("N18328 work cardinality differs")
    form = expected["textual_forms"][0]
    edition = form["editions"][0]
    if form.get("language") is not None or edition.get("language") is not None or edition.get("category") is not None:
        raise PipelineError("N18328 language/category preimage differs")
    form["language"] = "en"
    edition["language"] = "en"
    edition["category"] = "liturgies"
    if expected != new_work:
        raise PipelineError("N18328 work identity changed beyond approved category/language fields")
    validate_identity_update(old_work, new_work)
    if before[ACQUISITION.relative_to(WORK).as_posix()] != after[ACQUISITION.relative_to(WORK).as_posix()]:
        raise PipelineError("N18328 acquisition authority changed")
    old_state = json.loads(_io_path(ROOT / WORK / "state.json").read_bytes())
    new_state = json.loads(_io_path(stage / WORK / "state.json").read_bytes())
    if len(old_state["targets"]) != len(new_state["targets"]):
        raise PipelineError("N18328 state target count changed")
    for old, new in zip(old_state["targets"], new_state["targets"]):
        if old.get("target_id") != new.get("target_id") or old.get("target_type") != new.get("target_type"):
            raise PipelineError("N18328 state identity changed")
        if old["target_type"] == "acquisition":
            if old != new:
                raise PipelineError("N18328 acquisition state changed")
        else:
            additions = [MASTER.as_posix(), ACCEPTANCE.as_posix()]
            if (old.get("stage") != "acquired" or new.get("stage") != "accepted"
                    or new.get("evidence") != old.get("evidence", []) + additions
                    or any(old.get(key) != new.get(key) for key in old if key not in {"stage", "reason", "updated_at", "evidence"})):
                raise PipelineError("N18328 edition state transition differs")
    if after[MASTER.relative_to(WORK).as_posix()] != after[(EVIDENCE / "candidate.tei.xml").relative_to(WORK).as_posix()]:
        raise PipelineError("N18328 staged master differs from candidate")


def preflight(stage: Path, *, receipt_sha256: str) -> tuple[dict, Path]:
    root = ROOT.resolve(strict=True)
    stage = Path(stage).resolve(strict=True)
    if stage == root or stage in root.parents or root in stage.parents:
        raise PipelineError("N18328 stage and canonical roots overlap")
    receipt_path = stage / RECEIPT_NAME
    if not _io_path(receipt_path).is_file() or _sha(receipt_path) != receipt_sha256:
        raise PipelineError("N18328 stage receipt hash differs")
    receipt = json.loads(_io_path(receipt_path).read_bytes())
    if (receipt.get("contract") != "ocd-convicts-n18328-stage-v1"
            or receipt.get("status") != "staged-only"
            or receipt.get("installation") != "not-performed"
            or Path(receipt.get("stage_root", "")).resolve(strict=True) != stage
            or Path(receipt.get("canonical_root", "")).resolve(strict=True) != root
            or receipt.get("source_sha256") != SOURCE_SHA
            or receipt.get("source_manifest_sha256") != MANIFEST_SHA
            or receipt.get("candidate_sha256") != CANDIDATE_SHA):
        raise PipelineError("N18328 stage receipt contract differs")
    if (_sha(ROOT / SOURCE) != SOURCE_SHA or _sha(ROOT / MANIFEST) != MANIFEST_SHA
            or _sha(ROOT / CANDIDATE) != CANDIDATE_SHA):
        raise PipelineError("N18328 retained source or package authority changed")
    before, after = _files(ROOT / WORK), _files(stage / WORK)
    if before != receipt.get("before") or after != receipt.get("after"):
        raise PipelineError("N18328 complete work snapshot differs from frozen receipt")
    _scope(before, after, stage)
    if (receipt.get("master_sha256") != after[MASTER.relative_to(WORK).as_posix()]
            or receipt.get("acceptance_sha256") != after[ACCEPTANCE.relative_to(WORK).as_posix()]):
        raise PipelineError("N18328 master or acceptance digest differs")
    accepted = validate_acceptance(_io_path(stage / ACCEPTANCE), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    if (accepted["promotion"]["status"] != "promoted"
            or accepted["decision"]["human_decision"]["status"] != "not-recorded"):
        raise PipelineError("N18328 stage overstates human acceptance")
    projected = project_accepted_liturgies(_io_path(stage), acceptance_path=_io_path(stage / ACCEPTANCE))
    errors = verify_accepted_liturgies(_io_path(stage), acceptance_path=_io_path(stage / ACCEPTANCE),
                                       rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 3:
        raise PipelineError(f"N18328 actual-master staged projection differs: {errors[:3]}")
    return receipt, stage


def install(stage: Path, *, receipt_sha256: str) -> dict:
    record, stage = preflight(stage, receipt_sha256=receipt_sha256)
    target, source = ROOT / WORK, stage / WORK
    with ExitStack() as locks:
        for item in sorted((target, source), key=lambda path: path.as_posix()):
            locks.enter_context(acquire_jsonl_lock(item, acquire_timeout=30.0))
        if _files(target) != record["before"] or _files(source) != record["after"]:
            raise PipelineError("N18328 work changed while acquiring install locks")
        result = _commit_generation(
            ROOT.resolve(strict=True), target.resolve(strict=True), source.resolve(strict=True),
            work_id="convicts-visitor", before=record["before"], after=record["after"],
            existed=True, replacement=False, operation_kind="initial-install",
            result_status="installed-and-validated", accepted_editions=1, fail_at=None,
        )
    projected = project_accepted_liturgies(ROOT, acceptance_path=ROOT / ACCEPTANCE)
    errors = verify_accepted_liturgies(ROOT, acceptance_path=ROOT / ACCEPTANCE,
                                       rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 3:
        raise PipelineError(f"N18328 installed actual-master projection differs: {errors[:3]}")
    return {"status": result["status"], "operation": result["operation"],
            "master_sha256": record["master_sha256"], "projection_rows": len(projected["rows"]),
            "projection_receipt_sha256": sha256(json.dumps(projected["receipt"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = install(args.stage, receipt_sha256=args.receipt_sha256) if args.apply else {
        "status": "ready-for-review", "stage_root": str(preflight(args.stage, receipt_sha256=args.receipt_sha256)[1])
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
