"""Install one already promoted work through the shared guarded installer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library._common import load_json
from ocd_kernel.tei.install_accepted import add_accepted_edition, install_accepted_work


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="Destination repository root")
    parser.add_argument("--promoted", required=True, type=Path, help="Promoted staging root")
    parser.add_argument("--work", required=True, help="Work ID to install")
    parser.add_argument("--expected-old", type=Path, help="Complete reviewed work-relative SHA-256 snapshot; required to replace accepted text")
    parser.add_argument("--reviewed-new", type=Path, help="Complete reviewed incoming file snapshot for edition and publication updates; requires --expected-old")
    parser.add_argument("--add-edition", nargs=2, metavar=("TEXTUAL_FORM_ID", "EDITION_ID"), help="Add exactly one accepted edition while preserving existing editions; requires --expected-old")
    args = parser.parse_args(argv)
    if args.add_edition and args.expected_old is None:
        parser.error("--add-edition requires --expected-old")
    if args.reviewed_new and (args.expected_old is None or args.add_edition):
        parser.error("--reviewed-new requires --expected-old and cannot use --add-edition")
    try:
        expected = load_json(args.expected_old) if args.expected_old else None
        if args.add_edition:
            result = add_accepted_edition(args.root, args.promoted, work_id=args.work,
                textual_form_id=args.add_edition[0], edition_id=args.add_edition[1], expected_old=expected)
        else:
            result = install_accepted_work(args.root, args.promoted, work_id=args.work,
                expected_old=expected, reviewed_new=load_json(args.reviewed_new) if args.reviewed_new else None)
    except (PipelineError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
