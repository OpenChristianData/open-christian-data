"""Build the B7 vol_07 representativeness spot-check manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.gold_strata import (  # noqa: E402
    MIN_PER_OBSERVED_VALUE,
    STRATA_CONTRACT,
    derive_page_strata,
)
from build.lib.paths import REPO_ROOT  # noqa: E402
from build.tools.build_gold_sample import (  # noqa: E402
    DEFAULT_SIDECAR_ROOT,
    build_sample_manifest,
    default_output_path,
    write_manifest,
)

SPOTCHECK_TARGET = 10
BASELINE_VOLUME = 1
COMPARED_VOLUME = 7
ORACLE_GAP_TOLERANCE = 0.03
SEGMENTATION_DIFFERENCE_TOLERANCE = 0.05
SAMPLE_ROLE_REPRESENTATIVENESS = "representativeness_spot_check"


def build_comparison_contract(*, compared_volume: int, baseline_volume: int) -> dict[str, Any]:
    return {
        "compared_volume": compared_volume,
        "baseline_volume": baseline_volume,
        "indicators": ["oracle_gap", "segmentation_difference"],
        "tolerance_bands": {
            "oracle_gap": ORACLE_GAP_TOLERANCE,
            "segmentation_difference": SEGMENTATION_DIFFERENCE_TOLERANCE,
        },
    }


def build_spotcheck_manifest(
    *,
    sidecar_root: Path,
    compared_volume: int = COMPARED_VOLUME,
    baseline_volume: int = BASELINE_VOLUME,
    target_total: int = SPOTCHECK_TARGET,
    min_per_value: int = MIN_PER_OBSERVED_VALUE,
) -> dict[str, Any]:
    return build_sample_manifest(
        sidecar_root=sidecar_root,
        volume=compared_volume,
        sample_id=f"gold-sample-vol{compared_volume:02d}-representativeness-spot-check",
        sample_role=SAMPLE_ROLE_REPRESENTATIVENESS,
        target_total=target_total,
        min_per_value=min_per_value,
        comparison_contract=build_comparison_contract(
            compared_volume=compared_volume,
            baseline_volume=baseline_volume,
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sidecar-root", type=Path, default=DEFAULT_SIDECAR_ROOT)
    parser.add_argument("--compared-volume", type=int, default=COMPARED_VOLUME)
    parser.add_argument("--baseline-volume", type=int, default=BASELINE_VOLUME)
    parser.add_argument("--target-total", type=int, default=SPOTCHECK_TARGET)
    parser.add_argument("--min-per-value", type=int, default=MIN_PER_OBSERVED_VALUE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--write", action="store_true", help="Write the manifest. Default is dry-run.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv or []))
    manifest = build_spotcheck_manifest(
        sidecar_root=args.sidecar_root,
        compared_volume=args.compared_volume,
        baseline_volume=args.baseline_volume,
        target_total=args.target_total,
        min_per_value=args.min_per_value,
    )
    output = args.output or default_output_path(args.compared_volume, SAMPLE_ROLE_REPRESENTATIVENESS)
    if not args.write:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return 0
    write_manifest(output, manifest)
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
