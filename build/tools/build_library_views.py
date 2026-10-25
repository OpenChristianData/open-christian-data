"""CLI for the local generated library views."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.views import build_library_views, check_library_views


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", "--fixture-root", dest="root", type=Path, required=True)
    parser.add_argument("--output", "--destination", dest="output", type=Path)
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="write only PIPE-005's four named outputs below --root",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="check generated views against current authority bytes without writing",
    )
    args = parser.parse_args(argv)
    if args.in_place and args.check:
        parser.error("--in-place and --check cannot be combined")
    output = args.output or args.root
    if not args.in_place and args.output is None:
        parser.error("--output/--destination is required unless --in-place is used")
    try:
        if args.check:
            result = check_library_views(args.root, output)
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
            return 0 if result["fresh"] else 1
        result = build_library_views(args.root, output, in_place=args.in_place)
    except PipelineError as exc:
        parser.error(str(exc))
    print(json.dumps(result["status"]["counts"], sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
