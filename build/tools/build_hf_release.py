"""Build an offline v2 release from a selection, or the provisional prose tracer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.assemble import assemble_release, assemble_release_v2
from ocd_kernel.release.selection import load_release_selection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", "--fixture-root", dest="root", type=Path, required=True)
    parser.add_argument("--output", "--destination", "--release", dest="output", type=Path, required=True)
    parser.add_argument("--release-id", default="pipe-001-release")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--edition-id")
    source.add_argument("--selection", type=Path, help="Original v2 selection for a multi-configuration offline release")
    parser.add_argument("--category", default="prose")
    args = parser.parse_args(argv)
    try:
        if args.selection:
            result = assemble_release_v2(args.root, args.output, selection=load_release_selection(args.selection))
        else:
            result = assemble_release(
                args.root,
                args.output,
                release_id=args.release_id,
                edition_id=args.edition_id,
                category=args.category,
            )
    except (PipelineError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({"release_id": result["release_id"], "status": result["status"]}, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
