"""Read-only preflight or guarded install of the exact Origo Francorum stage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build.tools.install_openmgh_exact_work_div_batch import install, preflight


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-exact-bsb754-origo-freeze-20260927.json"
FREEZE_SHA256 = "c0f6fef6817f0d5abd8c62a5b5ef01b143d8d35aed1b9b1b532c43a8b1d4dfba"
WORK_ID = "origo-francorum"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        result = install(FREEZE, expected_freeze_sha256=FREEZE_SHA256, work_id=WORK_ID)
    else:
        result = preflight(FREEZE, expected_freeze_sha256=FREEZE_SHA256, work_id=WORK_ID)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
