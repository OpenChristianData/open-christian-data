"""Read-only preflight or guarded install for seven exact bsb705 stages.

The default is read-only. --apply uses the stock durable work transaction only
after the frozen manifest, retained source, stage and native row preflight pass.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build.tools.install_openmgh_exact_work_div_batch import install, preflight


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-exact-bsb705-freeze-20260927.json"
FREEZE_SHA256 = "cddcf42222bc0f014a327a85e8d14583aead5cba73ce7070925a8f9288c9cc5f"
WORKS = frozenset({
    "vita-bonifatii-willibald",
    "martyrologium-fuldense",
    "vita-altera-bonifatii-radbod",
    "vita-tertia-bonifatii",
    "vita-quarta-bonifatii-moguntino",
    "vita-quinta-bonifatii",
    "vita-bonifatii-otloh",
})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(WORKS))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        result = install(FREEZE, expected_freeze_sha256=FREEZE_SHA256,
                         work_id=args.work_id)
    else:
        result = preflight(FREEZE, expected_freeze_sha256=FREEZE_SHA256,
                           work_id=args.work_id)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
