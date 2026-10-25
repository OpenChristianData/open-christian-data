"""Stage twelve inspected bsb00000750 Latin prose child witnesses individually."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build.tools import stage_openmgh_bsb830_next as staging
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000750/tei/bsb00000750.xml")
SOURCE_SHA = "a88f93a090b6fd452a05b3cbc39a50f7bd7059cd94547f3cd712a4937243f0fc"
BATCH = Path("plans/2026-09-22-source-preflight/openmgh-bsb00000750-child-batch-20260926.json")
BATCH_SHA = "e8ab12a76f25a23310824785ddd39513154a70c90d374d224f82e8f4eeae2954"
WORKS = {
    "passio-sancti-memorii": "Peculiaris patroni nostri",
    "passio-sancti-quirini-tegernseensis": "Temporibus Claudii venit quidam vir de Perside",
    "vita-sanctae-genovefae": "Igitur Genovefa in Nymptoderinse parochia nata",
    "vita-sancti-apollinaris-valentinensis": "Quantum se omnium vita sanctorum beatis actibus",
    "vita-sancti-aviti": "Igitur Avitus infra Aurelianorum menia",
    "vita-sancti-carileffi": "Vitam beatissimi Carileffi sacerdotis Anisole",
    "vita-sancti-dalmatii": "Triumphalem hac venerabilem Dalmatii Rutene urbis",
    "vita-sancti-eptadii": "Igitur sanctus Eptadius Augustidunense",
    "vita-sancti-gaugerici": "Igitur beatissimus Gatigericus episcopus",
    "vita-sancti-iuniani": "Quotiens ad narrandas virtutes sanctorum",
    "vita-sancti-melanii": "Dum sanctorum patrum priscorum veneranda memoria",
    "vita-sancti-viviani-santonensis": "Convenienter venerabilis vita sacrae mandatur historiae",
}


def receipt_path(work_id: str) -> Path:
    if work_id not in WORKS:
        raise PipelineError(f"work outside the twelve inspected bsb750 child works: {work_id}")
    return (ROOT / "plans/2026-09-22-source-preflight"
            / f"{work_id}-openmgh-bsb750-acceptance-stage-20260926.json")


def prepare(work_id: str, scratch: Path) -> dict:
    if hashlib.sha256((ROOT / BATCH).read_bytes()).hexdigest() != BATCH_SHA:
        raise PipelineError("original bsb750 inspection receipt changed")
    staging.SOURCE = SOURCE
    staging.SOURCE_SHA = SOURCE_SHA
    staging.BATCH = BATCH
    staging.CATEGORY = "prose"
    staging.IDS = {work_id: WORKS[work_id]}
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
                      "projection_rows": result["projection_rows"],
                      "installation": result["installation"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
