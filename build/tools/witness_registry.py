"""Validate and list OCD source witness registry records."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib._generated_enums import (  # noqa: E402
    WITNESS_REGISTRY__RIGHTS_STATUS,
    WITNESS_REGISTRY__SOURCE_TYPE,
)
from build.lib.paths import REPO_ROOT  # noqa: E402

DEFAULT_REGISTRY_PATH = REPO_ROOT / "sources" / "witnesses" / "registry.json"

REQUIRED_FIELDS = {
    "witness_id",
    "related_resource_id",
    "related_work_title",
    "author",
    "witness_title",
    "source_url",
    "source_type",
    "rights_status",
    "edition_note",
    "provider",
    "local_path",
    "notes",
}


# NOTE: Phase-G schema wiring (schemas/v1/witness_registry.schema.json)
# deferred — see plans/2026-05-13-plan-review.md D-11. The schema
# describes a nested `edition` shape; WitnessRecord is still Phase-0
# flat. Generated enums above are sourced from the schema, so the
# enum surface IS shared.
@dataclass(frozen=True)
class WitnessRecord:
    witness_id: str
    related_resource_id: str
    related_work_title: str
    author: str
    witness_title: str
    source_url: str
    source_type: str
    rights_status: str
    edition_note: str
    provider: str
    local_path: str | None
    notes: str


@dataclass(frozen=True)
class WitnessMetadata:
    title: str
    source_url: str
    source_type: str
    rights_status: str
    edition_note: str


def load_witness_registry(path: Path = DEFAULT_REGISTRY_PATH) -> list[WitnessRecord]:
    """Load and validate a witness registry."""
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("witnesses"), list):
        raise ValueError("Witness registry must be an object with a witnesses array.")

    records = [_record_from_object(item, index) for index, item in enumerate(payload["witnesses"], start=1)]
    _validate_unique_ids(records)
    return records


def validate_witness_registry(path: Path = DEFAULT_REGISTRY_PATH) -> list[WitnessRecord]:
    return load_witness_registry(path)


def list_witnesses_for_resource(path: Path, resource_id: str) -> list[WitnessRecord]:
    return [record for record in load_witness_registry(path) if record.related_resource_id == resource_id]


def metadata_for_witness(path: Path, witness_id: str) -> WitnessMetadata:
    for record in load_witness_registry(path):
        if record.witness_id == witness_id:
            return WitnessMetadata(
                title=record.witness_title,
                source_url=record.source_url,
                source_type=record.source_type,
                rights_status=record.rights_status,
                edition_note=record.edition_note,
            )
    raise ValueError(f"Witness not found: {witness_id}")


def _record_from_object(item: Any, index: int) -> WitnessRecord:
    if not isinstance(item, dict):
        raise ValueError(f"Witness record {index} must be an object.")
    missing = sorted(REQUIRED_FIELDS - set(item))
    if missing:
        raise ValueError(f"Witness record {index} missing required fields: {', '.join(missing)}")

    source_type = _required_string(item, "source_type", index)
    if source_type not in WITNESS_REGISTRY__SOURCE_TYPE:
        raise ValueError(f"Invalid source_type for witness record {index}: {source_type}")

    rights_status = _required_string(item, "rights_status", index)
    if rights_status not in WITNESS_REGISTRY__RIGHTS_STATUS:
        raise ValueError(f"Invalid rights_status for witness record {index}: {rights_status}")

    local_path = item.get("local_path")
    if local_path is not None and not isinstance(local_path, str):
        raise ValueError(f"Witness record {index} local_path must be a string or null.")

    return WitnessRecord(
        witness_id=_required_string(item, "witness_id", index),
        related_resource_id=_required_string(item, "related_resource_id", index),
        related_work_title=_required_string(item, "related_work_title", index),
        author=_required_string(item, "author", index),
        witness_title=_required_string(item, "witness_title", index),
        source_url=_required_string(item, "source_url", index),
        source_type=source_type,
        rights_status=rights_status,
        edition_note=_required_string(item, "edition_note", index),
        provider=_required_string(item, "provider", index),
        local_path=local_path,
        notes=_required_string(item, "notes", index),
    )


def _required_string(item: dict[str, Any], field: str, index: int) -> str:
    value = item.get(field)
    if not isinstance(value, str):
        raise ValueError(f"Witness record {index} field {field} must be a string.")
    return value


def _validate_unique_ids(records: list[WitnessRecord]) -> None:
    seen: set[str] = set()
    for record in records:
        if record.witness_id in seen:
            raise ValueError(f"Duplicate witness_id: {record.witness_id}")
        seen.add(record.witness_id)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="Validate the witness registry.")
    list_parser = subparsers.add_parser("list", help="List witnesses for a resource ID.")
    list_parser.add_argument("--resource-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "validate":
        records = validate_witness_registry(args.registry)
    elif args.command == "list":
        records = list_witnesses_for_resource(args.registry, args.resource_id)
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    print(json.dumps([record.__dict__ for record in records], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
