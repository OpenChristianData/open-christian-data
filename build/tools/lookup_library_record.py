"""Look up one explicitly identified library record without changing it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ocd_kernel.library.records import lookup_exit_code, lookup_library_record, render_library_record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--id", required=True)
    for field in ("work-id", "textual-form-id", "edition-id"):
        parser.add_argument("--" + field)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--records-only", action="store_true", help="Inspect only canonical identity, holdings, and state; research and task coverage remain unassessed")
    args = parser.parse_args(argv)
    selector = {key: value for key, value in vars(args).items() if key not in {"root", "json", "records_only"} and value is not None}
    result = lookup_library_record(args.root, selector, connections=not args.records_only)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_library_record(result))
    return lookup_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
