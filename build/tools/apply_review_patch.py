from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from build.lib.atomic_io import (
    AtomicWriteError,
    SchemaValidationError,
    append_jsonl_atomic,
    validate_payload,
    write_json_atomic,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
REVIEW_PATCH_SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "review_patch.schema.json"
OBJECT_SCHEMA = {"type": "object"}
AUDIT_PATH = Path("review/audit.jsonl")


class ContentHashMismatch(Exception):
    """Raised when a review patch target has drifted since patch generation."""


def load_patch(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_review_patch_schema() -> dict[str, Any]:
    return json.loads(REVIEW_PATCH_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_review_patch(patch: Mapping[str, Any]) -> None:
    validate_payload(patch, load_review_patch_schema())


def verify_content_hashes(patch: Mapping[str, Any]) -> None:
    hashes = patch.get("content_hashes", {})
    if not isinstance(hashes, Mapping):
        raise ContentHashMismatch("content_hashes must be an object")
    for rel_path, expected in hashes.items():
        target = Path(str(rel_path))
        expected_hex = str(expected)
        if expected_hex.startswith("sha256:"):
            expected_hex = expected_hex.removeprefix("sha256:")
        actual_hex = sha256(target.read_bytes()).hexdigest()
        if actual_hex != expected_hex:
            raise ContentHashMismatch(f"content hash mismatch for {rel_path}")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def decision_target(decision: Mapping[str, Any]) -> str:
    kind = decision.get("decision_kind")
    if kind == "catalog_role_change":
        return str(decision["catalog_path"])
    if "record_path" in decision:
        return str(decision["record_path"])
    if "workbench_path" in decision:
        return str(decision["workbench_path"])
    return "<unknown>"


def build_mutations(patch: Mapping[str, Any]) -> tuple[dict[Path, dict[str, Any]], dict[Path, dict[str, Any]]]:
    workbench_updates: dict[Path, dict[str, Any]] = {}
    catalog_updates: dict[Path, dict[str, Any]] = {}

    for decision in patch["decisions"]:
        kind = decision["decision_kind"]
        if kind == "adjudication":
            workbench_path = Path(decision["workbench_path"])
            workbench = workbench_updates.get(workbench_path)
            if workbench is None:
                workbench = json.loads(workbench_path.read_text(encoding="utf-8"))
            entries = workbench.setdefault("entries", {})
            entry = entries.setdefault(decision["block_id"], {})
            entry["adjudication"] = {
                "chosen_reading": decision["chosen_reading"],
                "decided_at": decision["decided_at"],
                "rationale": decision["rationale"],
            }
            workbench_updates[workbench_path] = workbench
        elif kind == "catalog_role_change":
            catalog_path = Path(decision["catalog_path"])
            catalog = catalog_updates.get(catalog_path)
            if catalog is None:
                catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            rendering_id = decision["rendering_id"]
            for rendering in catalog.get("renderings", []):
                if rendering.get("rendering_id") == rendering_id:
                    rendering["role"] = decision["to_role"]
                    break
            else:
                raise ValueError(f"rendering_id not found in {catalog_path}: {rendering_id}")
            catalog_updates[catalog_path] = catalog
        elif kind in {"structural_resolution", "modernisation_approval"}:
            workbench_path = Path(decision["workbench_path"])
            workbench = workbench_updates.get(workbench_path)
            if workbench is None:
                workbench = json.loads(workbench_path.read_text(encoding="utf-8"))
            entries = workbench.setdefault("entries", {})
            block_id = decision.get("block_id") or decision.get("entry_id")
            if not block_id:
                raise ValueError(f"{kind} decision missing block_id or entry_id")
            entry = entries.setdefault(str(block_id), {})
            entry[kind] = {
                key: value
                for key, value in decision.items()
                if key not in {"decision_kind", "record_path", "workbench_path", "block_id", "entry_id"}
            }
            workbench_updates[workbench_path] = workbench
        else:
            raise ValueError(f"unsupported decision_kind: {kind}")

    return workbench_updates, catalog_updates


def apply_patch(patch: Mapping[str, Any]) -> None:
    validate_review_patch(patch)
    verify_content_hashes(patch)
    workbench_updates, catalog_updates = build_mutations(patch)

    for path, payload in workbench_updates.items():
        write_json_atomic(path, payload, OBJECT_SCHEMA)
    for path, payload in catalog_updates.items():
        write_json_atomic(path, payload, OBJECT_SCHEMA)

    applied_at = utc_now_iso()
    for decision in patch["decisions"]:
        audit_entry = dict(decision)
        audit_entry["applied_at"] = applied_at
        append_jsonl_atomic(AUDIT_PATH, audit_entry, OBJECT_SCHEMA)


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if len(args) != 1:
        print("usage: apply_review_patch.py <patch.json>", file=sys.stderr)
        raise SystemExit(2)
    patch = load_patch(args[0])
    try:
        apply_patch(patch)
    except SchemaValidationError:
        raise
    except AtomicWriteError as exc:
        print(f"atomic write failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]) or 0)
    except SchemaValidationError as exc:
        print(f"review patch schema violation: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
