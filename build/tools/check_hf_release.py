"""CLI for the independent offline release checker."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ocd_kernel.release.check import check_release
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.release.selection import load_release_selection
from ocd_kernel.library._common import PipelineError, load_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", "--fixture-root", dest="root", type=Path, required=True)
    parser.add_argument("--release", "--output", dest="release", type=Path, required=True)
    parser.add_argument("--selection", type=Path, help="Required original selection for a v2 release")
    args = parser.parse_args(argv)
    try:
        report = load_json(args.release / "internal/release-report.json")
        if args.selection is not None or report.get("schema_version") == "2.0":
            original = load_release_selection(args.selection) if args.selection else None
            result = verify_release_v2(args.root, args.release, selection=original)
        else:
            result = check_release(args.root, args.release)
    except (PipelineError, OSError) as exc:
        result = {"status": "fail", "errors": [str(exc)]}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
