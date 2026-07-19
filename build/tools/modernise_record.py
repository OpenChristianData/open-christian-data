from __future__ import annotations

import argparse
import os
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ocd_kernel.lib.atomic_io import write_json_atomic
from ocd_kernel.lib.schema_enums import resolve_schema_path
from build.lib.modernisation.engine import modernise_record as modernise


MODERNISED_SCHEMA = json.loads(resolve_schema_path("modernised_record").read_text(encoding="utf-8"))


def _target_for(record_path: Path) -> Path:
    if record_path.parent.name == "original":
        return record_path.parent.parent / "modernised" / record_path.name
    return record_path.with_name(record_path.stem + ".modernised.json")


def modernise_path(record_path: Path) -> Path:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    modernised = modernise(record)
    modernised["meta"]["paired_with"] = str(record_path)
    target = _target_for(record_path)
    write_json_atomic(target, modernised, MODERNISED_SCHEMA)
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Modernise one Reviewer-clean record.")
    parser.add_argument("record_path")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    modernise_path(Path(args.record_path))
    if not resolve_schema_path("modernised_record").exists():
        os.chdir(REPO_ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
