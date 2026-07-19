"""Phase 0 scaffolder: ensure every resource in data/ has a sources/<resource>/witnesses.json file.

Walks data/, groups records by ``meta.id``, and writes an empty
``sources/<meta.id>/witnesses.json`` for any resource that doesn't have one
yet. Existing witnesses.json files are never overwritten — this is a creator,
not a migrator. Use ``check_witness_inventory.py`` to validate after running.

The flat layout (``sources/<meta.id>/witnesses.json``) is the canonical
witness-inventory path per the v2 plan's worked examples. Existing
``sources/<category>/<resource>/`` directories holding raw source material are
untouched.
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
from build.lib.paths import REPO_ROOT  # noqa: E402


SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "witness_inventory.schema.json"


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


def scaffold(repo_root: Path, *, dry_run: bool = False) -> tuple[list[str], list[str]]:
    """Create empty witnesses.json files for resources missing one.

    Returns ``(created, already_present)`` lists of resource ids.
    """
    data_root = repo_root / "data"
    if not data_root.is_dir():
        raise FileNotFoundError(f"{data_root} does not exist")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
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
    parser = argparse.ArgumentParser(description="Scaffold empty witnesses.json files.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root (defaults to the OCD repo containing this script).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be created without writing any files.",
    )
    args = parser.parse_args(argv)
    created, already = scaffold(args.repo_root, dry_run=args.dry_run)
    verb = "would create" if args.dry_run else "created"
    print(f"{verb} {len(created)} witness-inventory files; {len(already)} already present.")
    for rid in created:
        print(f"  {verb}: sources/{rid}/witnesses.json")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
