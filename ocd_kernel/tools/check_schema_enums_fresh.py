"""Fail if a generated enum module is stale relative to schemas/v1 inputs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from ocd_kernel.tools.generate_schema_enums import (
    OUTPUT_PATH,
    collect_generated_constants,
    render_generated_module,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--generated-path",
        type=Path,
        default=OUTPUT_PATH,
        help="Path to the generated module to verify.",
    )
    parser.add_argument(
        "--schemas-dir",
        type=Path,
        action="append",
        help="Directory containing *.schema.json files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    constants, schema_hashes = collect_generated_constants(schemas_dirs=args.schemas_dir)
    expected = render_generated_module(constants, schema_hashes)
    if not args.generated_path.exists():
        print(
            "Schema enum module is missing. Run "
            "'py -3 -m ocd_kernel.tools.generate_schema_enums' to regenerate."
        )
        return 1
    actual = args.generated_path.read_text(encoding="utf-8")
    if actual != expected:
        print(
            "Schema enum module is stale. Run "
            "'py -3 -m ocd_kernel.tools.generate_schema_enums' to regenerate "
            "ocd_kernel/lib/_generated_enums.py."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
