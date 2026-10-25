"""Read-only preflight or guarded install for the frozen Arnulf bsb830 master."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build.tools.install_openmgh_exact_work_div_batch import install, preflight


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "plans/2026-09-22-source-preflight/arnulf-bsb830-exact-freeze-20260929.json"
FREEZE_SHA256 = "a544c4ad8445081785808d4b481c36b64b039d7d0013cff7757f535837bf49ec"
WORK_ID = "arnulf-of-sees-invective-to-geoffrey-of-chartres"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    operation = install if args.apply else preflight
    result = operation(FREEZE, expected_freeze_sha256=FREEZE_SHA256, work_id=WORK_ID)
    print(json.dumps({"status": result["status"], "work_id": WORK_ID,
                      "installation": "performed" if args.apply else "not-performed",
                      "operation": result.get("operation")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
