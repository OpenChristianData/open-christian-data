"""Generate the Schaff-Herzog headword inventory."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
import sys
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))


from build.lib.paths import REPO_ROOT  # noqa: E402
DEFAULT_INPUT = REPO_ROOT / "data" / "reference" / "schaff-herzog-encyclopedia.json"
DEFAULT_OUTPUT = REPO_ROOT / "build" / "inventories" / "schaff-herzog.json"


def build_inventory(record_path: Path) -> dict:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    data = record.get("data")
    entries = data if isinstance(data, list) else []
    counts = Counter()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        term = entry.get("term")
        if isinstance(term, str) and term:
            counts[term[0].upper()] += 1
    by_letter = {letter: counts[letter] for letter in sorted(counts)}
    return {
        "expected_letters": "".join(by_letter.keys()),
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "entry_count": len(entries),
        "by_letter": by_letter,
    }


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        handle.write(rendered)
    os.replace(temp_path, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inventory = build_inventory(args.input)
    write_json_atomic(args.output, inventory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
