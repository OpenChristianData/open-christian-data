from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.warning_producers import run_all_producers


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _warnings(work_handle: str) -> list[dict[str, Any]]:
    path = Path("review") / "state" / work_handle / "warnings.json"
    if path.exists():
        return list(_read_json(path).get("warnings", []))
    warnings: list[dict[str, Any]] = []
    for record_path in sorted((Path("data") / work_handle / "original").glob("*.json")):
        record = _read_json(record_path)
        grouped = run_all_producers(record, {"resource_id": work_handle, "resource_type": "record"})
        for items in grouped.values():
            warnings.extend(w for w in items if not w.get("ephemeral"))
    return warnings


def _workbench_pending(work_handle: str) -> list[str]:
    path = Path("review") / "state" / work_handle / "workbench.json"
    if not path.exists():
        return []
    workbench = _read_json(path)
    return [key for key, value in workbench.get("entries", {}).items() if value.get("pending")]


def _catalog_pending(work_handle: str) -> list[str]:
    path = Path("data") / work_handle / "catalog.json"
    catalog = _read_json(path)
    return [item["rendering_id"] for item in catalog.get("renderings", []) if item.get("role") == "pending"]


def _audit_complete(work_handle: str) -> bool:
    path = Path("review") / "audit.jsonl"
    if not path.exists():
        return False
    return any(work_handle in line for line in path.read_text(encoding="utf-8").splitlines())


def status(work_handle: str) -> dict[str, Any]:
    warnings = _warnings(work_handle)
    workbench_pending = _workbench_pending(work_handle)
    catalog_pending = _catalog_pending(work_handle)
    audit_complete = _audit_complete(work_handle)
    dimensions = {
        "checker_warnings": {"clean": not warnings, "count": len(warnings)},
        "workbench_pending": {"clean": not workbench_pending, "entries": workbench_pending},
        "catalog_pending": {"clean": not catalog_pending, "renderings": catalog_pending},
        "audit_log_incomplete": {"clean": audit_complete},
    }
    return {
        "work_handle": work_handle,
        "reviewer_clean": all(item["clean"] for item in dimensions.values()),
        "dimensions": dimensions,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report Reviewer-clean status.")
    parser.add_argument("work_handle")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    report = status(args.work_handle)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("reviewer_clean" if report["reviewer_clean"] else "not_reviewer_clean")
    return 0 if report["reviewer_clean"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
