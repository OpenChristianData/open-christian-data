"""Historical witness-inventory utility; not a current-library admission gate.

Requires explicit --legacy-data, --repo-root and --schema arguments. The old
witness_inventory schema is no longer shipped. Supply the historical schema
from the archive being inspected; rendering catalogs and current acquisitions
have different identities and are not interchangeable with this format.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Allow direct execution: ``py -3 build/tools/scaffold_witness_inventory.py``
_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from ocd_kernel.lib.atomic_io import write_json_atomic  # noqa: E402


def _enumerate_resources(data_root: Path) -> dict[str, list[Path]]:
    by_id: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(data_root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if not isinstance(meta, dict):
            continue
        rid = meta.get("id")
        if isinstance(rid, str) and rid:
            by_id[rid].append(path)
    return by_id


def _empty_inventory(resource_id: str, *, notes: str | None = None) -> dict:
    payload = {
        "schema_version": "1.0.0",
        "related_resource_id": resource_id,
        "witnesses": [],
        "cross_source_readings": [],
    }
    if notes:
        payload["notes"] = notes
    return payload


def scaffold(repo_root: Path, *, schema_path: Path, dry_run: bool = False) -> tuple[list[str], list[str]]:
    """Create empty witnesses.json files for resources missing one.

    Returns ``(created, already_present)`` lists of resource ids.
    """
    data_root = repo_root / "data"
    if not data_root.is_dir():
        raise FileNotFoundError(f"{data_root} does not exist")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    sources_root = repo_root / "sources"

    resources = _enumerate_resources(data_root)
    created: list[str] = []
    already_present: list[str] = []

    for rid in sorted(resources):
        target = sources_root / rid / "witnesses.json"
        if target.exists():
            already_present.append(rid)
            continue
        if dry_run:
            created.append(rid)
            continue
        payload = _empty_inventory(rid, notes="Auto-scaffolded by build/tools/scaffold_witness_inventory.py. Curate when secondary witnesses become available.")
        write_json_atomic(target, payload, schema)
        created.append(rid)
    return created, already_present


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scaffold historical witnesses.json files only; not current acquisitions.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        required=True,
        help="Explicit historical repository root.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be created without writing any files.",
    )
    parser.add_argument("--legacy-data", action="store_true", required=True,
                        help="Explicitly operate on historical data/ inventories.")
    parser.add_argument("--schema", type=Path, required=True,
                        help="Historical witness_inventory schema; no current schema fallback.")
    args = parser.parse_args(argv)
    created, already = scaffold(args.repo_root, schema_path=args.schema, dry_run=args.dry_run)
    verb = "would create" if args.dry_run else "created"
    print(f"{verb} {len(created)} witness-inventory files; {len(already)} already present.")
    for rid in created:
        print(f"  {verb}: sources/{rid}/witnesses.json")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
