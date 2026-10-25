"""Read-only exact-receipt preflight for the Greenleaf PG34989 work stage."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from build.tools.stage_greenleaf_pg34989_acceptance import (
    ACQUISITION, EDITION, EVIDENCE, ORIGINAL_SHA, PROJECTION_FILES, ROOT, SOURCE, SOURCE_REPORTS,
    SOURCE_SHA, WORK, WORK_ID, source_oracle,
)
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files

CONTRACT = "ocd-greenleaf-pg34989-stage-v1"


def _sha(path: Path) -> str:
    return sha256(io_path(path).read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    value = json.loads(io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"Greenleaf JSON object required: {path}")
    return value


def preflight(receipt: Path, *, expected_sha256: str) -> dict[str, object]:
    receipt = receipt.resolve(strict=True)
    if not expected_sha256 or _sha(receipt) != expected_sha256:
        raise PipelineError("exact reviewed Greenleaf receipt SHA-256 is required and must match")
    record = _json(receipt)
    if record.get("contract") != CONTRACT or record.get("status") != "staged-only" or record.get("work_id") != WORK_ID:
        raise PipelineError("Greenleaf receipt contract, status, or work differs")
    if receipt.name != "greenleaf-stage-receipt.json":
        raise PipelineError("Greenleaf receipt filename differs")
    stage = Path(record["stage_root"]).resolve(strict=True)
    canonical = Path(record["canonical_root"]).resolve(strict=True)
    durable = Path("D:/Library/Open Christian Data/candidate-reviews").resolve(strict=True)
    if receipt != (stage / receipt.name).resolve(strict=True) or stage.parent != durable or canonical != ROOT.resolve(strict=True):
        raise PipelineError("Greenleaf receipt root binding differs")
    if _files(canonical / WORK) != record["before"] or _files(stage / WORK) != record["after"]:
        raise PipelineError("Greenleaf live preimage or staged work generation differs")
    if (set(record.get("projection_files_sha256", {})) != set(PROJECTION_FILES)
            or any(_sha(canonical / path) != record["projection_files_sha256"][path]
                   for path in PROJECTION_FILES)):
        raise PipelineError("Greenleaf reviewed projection/schema bytes changed")
    if record["source_sha256"] != SOURCE_SHA or record["original_candidate_sha256"] != ORIGINAL_SHA:
        raise PipelineError("Greenleaf source/candidate pins differ")
    if _sha(canonical / SOURCE) != SOURCE_SHA or _sha(stage / SOURCE) != SOURCE_SHA:
        raise PipelineError("Greenleaf retained direct source differs")
    original = stage / EVIDENCE / "inputs/original-candidate.tei.xml"
    if _sha(original) != ORIGINAL_SHA:
        raise PipelineError("Greenleaf reviewed P5 candidate differs")
    oracle = source_oracle(io_path(stage / SOURCE).read_bytes(), io_path(original).read_bytes())
    if oracle != record["oracle"]:
        raise PipelineError("Greenleaf independent source walk differs")
    for name, expected in SOURCE_REPORTS.items():
        if (record["retained_report_sha256"].get(name) != expected
                or _sha(canonical / "reports/clean-ready-acquisition-to-tei/master-4/28" / WORK_ID / "evidence" / f"{name}.json") != expected
                or _sha(stage / EVIDENCE / "inputs" / f"{name}.json") != expected):
            raise PipelineError(f"Greenleaf source report differs: {name}")
    if _sha(canonical / ACQUISITION) != _sha(stage / ACQUISITION):
        raise PipelineError("Greenleaf acquisition declaration differs")
    acquisition = _json(stage / ACQUISITION)
    for member in acquisition["retained_files"]:
        path = Path(member["path"])
        if _sha(canonical / path) != member["sha256"] or _sha(stage / path) != member["sha256"]:
            raise PipelineError(f"Greenleaf retained acquisition member differs: {path}")
    acceptance = stage / EDITION / "acceptance.json"
    accepted = validate_acceptance(acceptance, root=stage)
    master = stage / EDITION / "master.tei.xml"
    if (accepted["identity"]["work_id"] != WORK_ID
            or _sha(master) != record["accepted_master_sha256"]
            or _sha(acceptance) != record["acceptance_sha256"]):
        raise PipelineError("Greenleaf accepted master or record differs")
    projection = project_accepted_prose(io_path(stage), acceptance_path=io_path(acceptance))
    errors = verify_accepted_prose(io_path(stage), acceptance_path=io_path(acceptance),
                                   rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != record["native_rows"] or len(projection["rows"]) != 13:
        raise PipelineError(f"Greenleaf actual-master native projection differs: {errors[:3]}")
    rows_sha = sha256(json.dumps(projection["rows"], ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode("utf-8")).hexdigest()
    receipt_sha = sha256(json.dumps(projection["receipt"], ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")).encode("utf-8")).hexdigest()
    if rows_sha != record.get("native_rows_sha256") or receipt_sha != record.get("native_receipt_sha256"):
        raise PipelineError("Greenleaf native public rows or projection receipt changed")
    return dict(status="preflight-pass", receipt_sha256=expected_sha256,
                work_id=WORK_ID, before_count=len(record["before"]),
                after_count=len(record["after"]), native_rows=len(projection["rows"]),
                master_sha256=record["accepted_master_sha256"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(preflight(args.receipt, expected_sha256=args.expected_sha256), sort_keys=True))


if __name__ == "__main__":
    main()
