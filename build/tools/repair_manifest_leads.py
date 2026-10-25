"""Stage a conservative manifest-lead repair; apply only with the explicit flag."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.research_leads import apply_lead_repair, plan_lead_repair


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = plan_lead_repair(args.root)
        result = apply_lead_repair(args.root, plan) if args.apply else plan["conservation"]
    except (PipelineError, OSError, UnicodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=True))
        return 1
    print(json.dumps({"applied": args.apply, **result}, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
