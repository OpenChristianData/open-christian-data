"""Regenerate review/dead-letter/index.json from spill files.

Scans review/dead-letter/*.jsonl and groups counts by resource + producer_id +
reason_code. The corpus dashboard reads the index, never the individual
spill entries.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))
from build.lib.paths import REPO_ROOT  # noqa: E402


def build_index(dead_letter_dir: Path) -> dict[str, Any]:
    """Walk dead_letter_dir/*.jsonl, return an index keyed by resource_id."""
    by_resource: dict[str, dict[str, Any]] = {}
    if not dead_letter_dir.exists():
        return {"resources": {}, "generated_at_utc": datetime.now(tz=timezone.utc).isoformat()}
    for path in sorted(dead_letter_dir.glob("*.jsonl")):
        resource_id = path.stem
        counts_by_reason: dict[str, int] = defaultdict(int)
        counts_by_producer: dict[str, int] = defaultdict(int)
        total = 0
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                logging.warning(
                    "Skipping malformed dead-letter spill line in %s at line %s",
                    path,
                    line_number,
                )
                continue
            total += 1
            counts_by_reason[entry.get("reason", "unknown")] += 1
            producer = entry.get("producer_id") or entry.get("producer", "unknown")
            counts_by_producer[producer] += 1
        try:
            spill_relative = str(path.relative_to(REPO_ROOT)).replace(os.sep, "/")
        except ValueError:
            spill_relative = str(path).replace(os.sep, "/")
        by_resource[resource_id] = {
            "total": total,
            "by_reason": dict(counts_by_reason),
            "by_producer": dict(counts_by_producer),
            "spill_path": spill_relative,
        }
    return {
        "resources": by_resource,
        "generated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dead-letter-dir",
        type=Path,
        default=REPO_ROOT / "review" / "dead-letter",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "review" / "dead-letter" / "index.json",
    )
    args = parser.parse_args(argv)

    index = build_index(args.dead_letter_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(args.out.suffix + ".tmp")
    tmp.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, args.out)
    total = sum(r["total"] for r in index["resources"].values())
    print(f"wrote {args.out}: {len(index['resources'])} resources, {total} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
