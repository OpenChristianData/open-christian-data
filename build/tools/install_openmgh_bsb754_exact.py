"""Read-only preflight or guarded install for eight exact bsb754 stages.

The default only checks the frozen source, candidate, stage, and native row.
An explicit --apply uses the stock durable work transaction for one work.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build.tools.install_openmgh_exact_work_div_batch import install, preflight


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-exact-bsb754-freeze-20260927.json"
FREEZE_SHA256 = "3d2e95e781b050e2852d160e36ae9c4d1573df3c47e2e4cbab8aab47d5b1545b"
WORKS = frozenset({
    "vita-sancti-pardulfi",
    "vita-sancti-willibrordi",
    "vita-sancti-bertuini",
    "vita-sancti-gamalberti",
    "vita-sancti-germani-autissiodorensis",
    "vita-sancti-sollemnis",
    "vita-sancti-lonoghylii-et-agnofledae",
    "libellus-de-ecclesiis-claromontanis",
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
