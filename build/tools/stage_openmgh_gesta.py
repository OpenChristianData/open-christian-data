"""Stage the exact Gesta electronic witness, including its retained lacuna."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build.tools import stage_openmgh_bsb830_next as staging


WORK_ID = "gesta-domni-lantberti"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    staging.SOURCE = Path("raw/openmgh/bsb00000752/tei/bsb00000752.xml")
    staging.SOURCE_SHA = (
        "620b80ade431a814ebf41296cdf88476d9a39741cdba1925c0cd75fb9772c98a"
    )
    staging.BATCH = Path(
        "plans/2026-09-22-source-preflight/openmgh-bsb752-inspected-batch-20260926.json"
    )
    staging.IDS = {WORK_ID: "Lambertus vir valde clarissimus"}
    result = staging.prepare(staging.ROOT, WORK_ID, args.scratch, args.receipt)
    print(json.dumps({key: result[key] for key in (
        "work_id", "status", "accepted_master_sha256", "projection_rows",
        "projection_status", "installation",
    )}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
