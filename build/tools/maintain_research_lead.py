"""Add or resolve one evidenced research lead without replaying migration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.research_leads import apply_lead_upkeep, plan_lead_upkeep


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--lead-id", required=True)
    parser.add_argument("--evidence-path", required=True)
    parser.add_argument("--line-start", type=int, required=True)
    parser.add_argument("--line-end", type=int, required=True)
    parser.add_argument("--write", action="store_true")
    modes = parser.add_subparsers(dest="mode", required=True)
    add = modes.add_parser("add")
    add.add_argument("--intent", required=True)
    add.add_argument("--context", action="append", required=True)
    resolve = modes.add_parser("resolve")
    resolve.add_argument("--disposition", choices=("promoted", "closed"), required=True)
    resolve.add_argument("--work-id")
    args = parser.parse_args(argv)
    try:
        plan = plan_lead_upkeep(
            args.root, lead_id=args.lead_id, evidence_path=args.evidence_path,
            line_start=args.line_start, line_end=args.line_end,
            disposition=getattr(args, "disposition", None), work_id=getattr(args, "work_id", None),
            acquisition_intent=getattr(args, "intent", None), context=getattr(args, "context", None),
        )
        result = apply_lead_upkeep(args.root, plan) if args.write else {
            key: plan[key] for key in ("action", "lead_id", "queue_before_sha256", "queue_after_sha256")
        }
        print(json.dumps({**result, "written": args.write}, sort_keys=True))
        return 0
    except (PipelineError, OSError, UnicodeError) as exc:
        print(f"lead upkeep error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
