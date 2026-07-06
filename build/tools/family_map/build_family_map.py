"""B9 CLI: measure family independence on a bake-off sample -> family map.

Builds the family-grouping map for an active engine set from a positions file
(each position: {"gold": <str|null>, "engine_tokens": {engine_id: reading}}) and
an engine-families file ({engine_id: declared_family}), ties it to a matrix-policy
version, and writes it to reports/family_map/ (gitignored, regenerable).

The readiness flip is what later un-blocks B11's class-1 training. A measured
count below two independent families records a contingency and never flips -- the
strict bar is never relaxed to keep flowing (arch D section 4).

The verdict on the REAL family count is phase 2 (real vol_01 bake-off + real
diagnostics); this tool is the measurement + map writer.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.family_independence import (  # noqa: E402
    DEFAULT_DEPENDENCE_THRESHOLD,
    AlignedPosition,
    build_family_map,
    write_family_map,
)


def _load_positions(path: Path) -> list[AlignedPosition]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        AlignedPosition(gold=item.get("gold"), engine_tokens=item.get("engine_tokens", {}))
        for item in raw
    ]


def _default_effective_date() -> str:
    # DATE-01: Melbourne-local date, never a naive now().
    return datetime.now(ZoneInfo("Australia/Melbourne")).date().isoformat()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="B9 family-independence measurement -> family map + policy version."
    )
    parser.add_argument("--positions", required=True, type=Path, help="aligned positions JSON.")
    parser.add_argument(
        "--engine-families", required=True, type=Path, help="engine_id -> declared family JSON."
    )
    parser.add_argument("--policy-version", required=True, help="matrix-policy version string.")
    parser.add_argument("--input-sample-id", required=True, help="bake-off sample id (e.g. vol_01-bakeoff).")
    parser.add_argument(
        "--effective-date",
        default=None,
        help="ISO date the map becomes active (default: today, Melbourne).",
    )
    parser.add_argument("--reports-root", required=True, type=Path, help="report tree root.")
    parser.add_argument(
        "--dependence-threshold",
        type=float,
        default=DEFAULT_DEPENDENCE_THRESHOLD,
        help="same-wrong-string rate at/above which declared-distinct families collapse.",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="compute and print without writing the map.",
    )
    args = parser.parse_args(argv)

    family_map = build_family_map(
        engine_families=json.loads(args.engine_families.read_text(encoding="utf-8")),
        positions=_load_positions(args.positions),
        policy_version=args.policy_version,
        input_sample_id=args.input_sample_id,
        effective_date=args.effective_date or _default_effective_date(),
        dependence_threshold=args.dependence_threshold,
    )

    print(
        "family map: diversity={} independent_check={} readiness={}".format(
            family_map["family_diversity_count"],
            family_map["independent_check_present"],
            family_map["family_map_readiness"],
        )
    )
    for block in family_map["family_groups"]:
        print(
            "  block {}: engines={} families={} merged_by_dependence={}".format(
                block["block_id"],
                ",".join(block["engine_ids"]),
                ",".join(block["declared_families"]),
                block["merged_by_dependence"],
            )
        )
    if "contingency" in family_map:
        print(
            "  CONTINGENCY: {} -> {} (class-1 blocked)".format(
                family_map["contingency"]["status"],
                family_map["contingency"]["recommended_action"],
            )
        )

    if args.read_only:
        print("read-only: family map not written.")
        return 0

    out_path = write_family_map(args.reports_root, family_map)
    print("wrote {}".format(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
