"""Read-only preflight or guarded install for one exact bsb829-disputatio stage.

The default only checks the frozen source, candidate, stage, and native row.
An explicit --apply uses the stock durable work transaction for one work.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build.tools.install_openmgh_exact_work_div_batch import install, preflight


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-exact-bsb829-disputatio-freeze-20260927.json"
FREEZE_SHA256 = "377e41d5f8da7bba20eec15651f747c2a887571d96149235ddb55af8caf09462"
WORKS = frozenset({
    'disputatio-vel-defensio-paschalis-papae',
})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(WORKS))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    operation = install if args.apply else preflight
    result = operation(FREEZE, expected_freeze_sha256=FREEZE_SHA256,
                       work_id=args.work_id)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
