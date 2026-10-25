"""Stage the remaining three inspected bsb00000830 electronic witnesses."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build.tools import stage_openmgh_bsb830_next as staging
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000830/tei/bsb00000830.xml")
SOURCE_SHA = "bb97bf6037a31d6a6c37f0e967aa23e9df1933bdd688fe4aaa84e5e034ff67ac"
BATCH = Path("plans/2026-09-22-source-preflight/openmgh-bsb830-inspected-batch-20260926.json")
BATCH_SHA = "9115c45b7bb855125f81fc4f8122a217f600b6bac2239160e9d6c9c0822f2562"
WORKS = {
    "merseburg-fragment-on-clerical-celibacy": (
        "prose", "in medio contradixit, honorabiles confessus nuptias"),
    "poem-on-the-simoniacal-heresy": (
        "poetry", "Crevit in aecclesia monstrum"),
    "satire-against-the-people-of-metz": (
        "poetry", "Nulla salus aut pax veniat tibi, gens tenebrosa"),
}


def receipt_path(work_id: str) -> Path:
    if work_id not in WORKS:
        raise PipelineError(f"work outside the three inspected bsb830 remainder: {work_id}")
    return (ROOT / "plans/2026-09-22-source-preflight"
            / f"{work_id}-openmgh-bsb830-remainder-stage-20260926.json")


def prepare(work_id: str, scratch: Path) -> dict:
    category, clause = WORKS[work_id]
    if hashlib.sha256((ROOT / BATCH).read_bytes()).hexdigest() != BATCH_SHA:
        raise PipelineError("original bsb830 inspection receipt changed")
    staging.SOURCE = SOURCE
    staging.SOURCE_SHA = SOURCE_SHA
    staging.BATCH = BATCH
    staging.CATEGORY = category
    staging.IDS = {work_id: clause}
    return staging.prepare(ROOT, work_id, scratch, receipt_path(work_id))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(WORKS))
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.work_id, args.scratch)
    receipt = receipt_path(args.work_id)
    print(json.dumps({"work_id": args.work_id, "status": result["status"],
                      "receipt": receipt.as_posix(),
                      "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
                      "accepted_master_sha256": result["accepted_master_sha256"],
                      "category": result["category"], "projection_rows": result["projection_rows"],
                      "installation": result["installation"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
