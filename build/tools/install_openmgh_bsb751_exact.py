"""Read-only preflight or guarded install for nine exact bsb751 stages.

The default only checks the frozen source, candidate, stage, and native row.
An explicit --apply uses the stock durable work transaction for one work.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build.tools.install_openmgh_exact_work_div_batch import install, preflight


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-exact-bsb751-freeze-20260927.json"
FREEZE_SHA256 = "bc4269632c973396662e61dd2d89be0b7b53ced57e84144cca0cefee9ecada2d"
WORKS = frozenset({
    'vita-sancti-walarici',
    'vita-sancti-lupi-senonici',
    'vita-sanctae-rusticulae',
    'passio-sancti-thrudperti',
    'vita-sancti-sulpicii-biturgensis',
    'vita-sancti-goaris',
    'vita-sancti-desiderii-cadurcensis',
    'vita-sancti-sigiramni',
    'vita-sancti-geremari',
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
