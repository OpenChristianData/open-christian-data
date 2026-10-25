"""Read-only preflight or guarded install for nine exact bsb753 stages.

The default only checks the frozen source, candidate, stage, and native row.
An explicit --apply uses the stock durable work transaction for one work.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build.tools.install_openmgh_exact_work_div_batch import install, preflight


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-exact-bsb753-freeze-20260927.json"
FREEZE_SHA256 = "355cf646425b644ed573c20d4c020826fa5c585436351c2b8f993342f1fc8393"
WORKS = frozenset({
    'vita-sancti-erhardi',
    'vita-sanctae-odiliae',
    'vita-sanctae-anstrudis',
    'vita-sancti-boniti',
    'gesta-sancti-hrodberti',
    'vita-sancti-wilfridi-stephani',
    'vita-sancti-trudonis',
    'vita-sancti-landelini',
    'vita-sancti-hugberti',
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
