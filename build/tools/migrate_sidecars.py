"""Explicit sidecar schema migration command.

Reads an old-schema sidecar, walks it through ``build.lib.sidecar_migrations``
single-step migrations until it reaches the current writer schema, writes the
upgraded sidecar back via atomic IO, and emits one ``sidecar_schema_migrated``
audit event recording the migration chain. This is the only authorised mutation
path for upgrading a sidecar's schema version.

Use::

    python -m build.tools.migrate_sidecars review/state/<path>/<record>.json

or pass a directory to walk every ``*.json`` underneath it. Sidecars already at
the current schema are skipped silently (idempotent).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib import sidecar_migrations  # noqa: E402
from build.lib.atomic_io import append_jsonl_atomic, write_json_atomic  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402


AUDIT_SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "audit_event.schema.json"
REVIEW_STATE_SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "review_state.schema.json"


def _utc_now_iso() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _iter_sidecars(target: Path) -> Iterable[Path]:
    if target.is_file():
        yield target
        return
    yield from sorted(target.rglob("*.json"))


def _emit_audit(
    *,
    repo_root: Path,
    sidecar: dict,
    from_version: str,
    chain: list[tuple[str, str]],
    actor: str,
) -> None:
    audit_path = repo_root / "review" / "audit.jsonl"
    schema = json.loads(AUDIT_SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = {
        "schema_version": "1.0.0",
        "event_type": "sidecar_schema_migrated",
        "timestamp_utc": _utc_now_iso(),
        "actor": actor,
        "resource_id": sidecar["record_resource_id"],
        "record_path": sidecar["record_path"],
        "from_version": from_version,
        "to_version": sidecar_migrations.CURRENT_VERSION,
        "migration_chain": [f"{f}->{t}" for (f, t) in chain],
    }
    append_jsonl_atomic(audit_path, payload, schema)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m build.tools.migrate_sidecars",
        description="Migrate sidecars to the current review_state schema.",
    )
    parser.add_argument("path", type=Path, help="Sidecar file or directory to walk.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root (defaults to the OCD repo containing this script).",
    )
    parser.add_argument(
        "--actor",
        default="migrate_sidecars",
        help="Audit-log actor identity for the migration event.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    schema = json.loads(REVIEW_STATE_SCHEMA_PATH.read_text(encoding="utf-8"))
    target_version = sidecar_migrations.CURRENT_VERSION
    migrated = 0
    skipped = 0

    for path in _iter_sidecars(args.path):
        try:
            on_disk = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if on_disk.get("schema_type") != "review_state":
            continue
        current = on_disk.get("schema_version")
        if current == target_version:
            skipped += 1
            continue
        chain = sidecar_migrations.chain(current, target_version)
        if not chain:
            skipped += 1
            continue
        upgraded = sidecar_migrations.upgrade(on_disk, target_version=target_version)
        if args.dry_run:
            print(f"would migrate {path}: {current} -> {target_version} via {chain}")
            migrated += 1
            continue
        write_json_atomic(path, upgraded, schema)
        _emit_audit(
            repo_root=args.repo_root,
            sidecar=upgraded,
            from_version=current,
            chain=chain,
            actor=args.actor,
        )
        print(f"migrated {path}: {current} -> {target_version}")
        migrated += 1

    print(f"Migrated {migrated} sidecar(s); skipped {skipped} already-current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
