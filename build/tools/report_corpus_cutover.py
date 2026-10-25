"""Account every frozen corpus target against an independently verified release."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.corpus_accounting import report_corpus
from ocd_kernel.release.selection import load_release_selection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise PipelineError(f"accounting output must be fresh: {args.output}")
        result = report_corpus(args.root, args.release,
                               scope=json.loads(args.scope.read_text(encoding="utf-8")),
                               selection=load_release_selection(args.selection))
    except (PipelineError, OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"counts": result["counts"], "retirement_readiness": result["retirement_readiness"]}))
    # Successful accounting does not imply readiness; report the distinction.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
