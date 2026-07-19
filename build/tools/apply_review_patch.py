from __future__ import annotations

import json
import argparse
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from ocd_kernel.lib.atomic_io import (
    AtomicWriteError,
    SchemaValidationError,
    append_jsonl_atomic,
    validate_payload,
    write_json_atomic,
)
from ocd_kernel.lib.schema_enums import resolve_schema_path


REPO_ROOT = Path(__file__).resolve().parents[2]
REVIEW_PATCH_SCHEMA_PATH = resolve_schema_path("review_patch")
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


def verify_content_hashes(patch: Mapping[str, Any], *, base_dir: Path | None = None) -> None:
    hashes = patch.get("content_hashes", {})
    if not isinstance(hashes, Mapping):
        raise ContentHashMismatch("content_hashes must be an object")
    root = base_dir or Path.cwd()
    for rel_path, expected in hashes.items():
        target = Path(str(rel_path))
        if not target.is_absolute():
            target = root / target
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


def apply_patch(
    patch: Mapping[str, Any],
    *,
    base_dir: Path | str | None = None,
    decisions_base_dir: Path | str | None = None,
    wct_dir: Path | str | None = None,
    ia_manifest_path: Path | str | None = None,
    tei_out_dir: Path | str | None = None,
) -> None:
    validate_review_patch(patch)
    root = Path(base_dir) if base_dir is not None else Path.cwd()
    verify_content_hashes(patch, base_dir=root)

    decisions = list(patch["decisions"])
    je_decisions = [decision for decision in decisions if decision.get("review_target") == "je_tei_token"]
    legacy_decisions = [decision for decision in decisions if decision.get("review_target") != "je_tei_token"]

    if legacy_decisions:
        _apply_legacy_patch({**dict(patch), "decisions": legacy_decisions})
    if je_decisions:
        raise ValueError("JE TEI review patch application has moved to EzraOCR.")


def _apply_legacy_patch(patch: Mapping[str, Any]) -> None:
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("patch", type=Path)
    parser.add_argument("--base-dir", type=Path, default=Path.cwd())
    parser.add_argument("--decisions-base-dir", type=Path)
    parser.add_argument("--wct-dir", type=Path)
    parser.add_argument("--ia-manifest", type=Path)
    parser.add_argument("--tei-out-dir", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    patch = load_patch(args.patch)
    try:
        apply_patch(
            patch,
            base_dir=args.base_dir,
            decisions_base_dir=args.decisions_base_dir,
            wct_dir=args.wct_dir,
            ia_manifest_path=args.ia_manifest,
            tei_out_dir=args.tei_out_dir,
        )
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
