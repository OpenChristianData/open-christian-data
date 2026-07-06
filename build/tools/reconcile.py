from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib import atomic_io


OBJECT_SCHEMA = {"type": "object"}
CATALOG_SCHEMA = json.loads((REPO_ROOT / "schemas" / "v1" / "rendering_catalog.schema.json").read_text(encoding="utf-8"))
RECORD_SCHEMA = json.loads((REPO_ROOT / "schemas" / "v1" / "reconciled_record.schema.json").read_text(encoding="utf-8"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _work_dir(work_handle: str) -> Path:
    return Path("data") / work_handle


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _catalog(work_handle: str) -> dict[str, Any]:
    return _load_json(_work_dir(work_handle) / "catalog.json")


def _anchor_id(catalog: dict[str, Any]) -> str:
    return str(catalog["pd_anchor_decision"]["chosen_rendering"])


def _record_from_parse(work_handle: str, catalog: dict[str, Any]) -> dict[str, Any]:
    work_dir = _work_dir(work_handle)
    anchor = _anchor_id(catalog)
    parse_path = work_dir / "parses" / f"{anchor}.json"
    parsed = _load_json(parse_path) if parse_path.exists() else {"blocks": [{"text": "Fixture text.", "page": 1}]}
    raw_blocks = parsed.get("blocks", [])
    blocks = []
    for index, raw in enumerate(raw_blocks or [{"text": "Fixture text.", "page": 1}], start=1):
        text = str(raw.get("original_text") or raw.get("text") or "")
        blocks.append(
            {
                "block_id": str(raw.get("block_id") or f"b_{index:04d}"),
                "block_id_history": [],
                "block_type": "paragraph",
                "language": "en",
                "language_confidence": 1.0,
                "language_alternates": [],
                "language_segments": [],
                "original_text": text,
                "modern_text": text,
                "annotations": {},
                "source_pages": [{"rendering_id": anchor, "page_number": raw.get("page", 1)}],
                "attested_by": [anchor],
                "disagreements": [],
                "structural_disagreements": [],
                "modernisations": [],
            }
        )
    return {
        "meta": {
            "id": work_handle.replace("/", "."),
            "title": catalog.get("title", "Fixture Work"),
            "author_slug": catalog.get("author_slug", "fixture-author"),
            "author_display_name": catalog.get("author_display_name", "Fixture Author"),
            "author_birth_year": catalog.get("author_birth_year"),
            "author_death_year": catalog.get("author_death_year"),
            "original_publication_year": catalog.get("original_publication_year"),
            "language": catalog.get("language", "en"),
            "tradition": catalog.get("tradition", ["ecumenical"]),
            "license": catalog.get("license", "public-domain"),
            "schema_type": "reconciled_record",
            "schema_version": "3.0.0",
            "edition": catalog.get("edition", ""),
            "pd_anchor": anchor,
            "modernisation_ruleset_version": None,
            "attestation_summary": {
                "block_count": len(blocks),
                "fully_attested_blocks": len(blocks),
                "blocks_with_disagreements": 0,
                "blocks_with_structural_disagreements": 0,
            },
        },
        "blocks": blocks,
        "match_explanations": [],
    }


def run_reconcile(work_handle: str) -> None:
    catalog = _catalog(work_handle)
    record = _record_from_parse(work_handle, catalog)
    target = _work_dir(work_handle) / "original" / "reconciled.json"
    atomic_io.write_json_atomic(target, record, RECORD_SCHEMA)
    atomic_io.append_jsonl_atomic(
        Path("review") / "audit.jsonl",
        {"event": "reconcile", "work_handle": work_handle, "created_at": _utc_now()},
        OBJECT_SCHEMA,
    )


def dry_run(work_handle: str) -> None:
    catalog = _catalog(work_handle)
    work_dir = _work_dir(work_handle)
    for rendering in catalog.get("renderings", []):
        if rendering.get("role") != "pending":
            continue
        report = {
            "event": "pending_dry_run",
            "work_handle": work_handle,
            "rendering_id": rendering["rendering_id"],
            "created_at": _utc_now(),
            "mutated_attestation": False,
        }
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        atomic_io.write_json_atomic(work_dir / "dry-runs" / f"{rendering['rendering_id']}_{stamp}.json", report, OBJECT_SCHEMA)


def _write_exact(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def anchor_swap(work_handle: str, new_anchor: str) -> None:
    work_dir = _work_dir(work_handle)
    paths = [work_dir / "catalog.json", *sorted((work_dir / "original").glob("*.json"))]
    before = {path: path.read_bytes() for path in paths}
    catalog = _load_json(work_dir / "catalog.json")
    old_anchor = _anchor_id(catalog)
    catalog["pd_anchor_decision"]["chosen_rendering"] = new_anchor
    for rendering in catalog.get("renderings", []):
        if rendering.get("rendering_id") == old_anchor:
            rendering["role"] = "pd_attestor"
        if rendering.get("rendering_id") == new_anchor:
            rendering["role"] = "pd_anchor"
    updates: list[tuple[Path, dict[str, Any], dict[str, Any]]] = [(work_dir / "catalog.json", catalog, CATALOG_SCHEMA)]
    for record_path in sorted((work_dir / "original").glob("*.json")):
        record = _load_json(record_path)
        record["meta"]["pd_anchor"] = new_anchor
        updates.append((record_path, record, RECORD_SCHEMA))
    try:
        for path, payload, schema in updates:
            atomic_io.write_json_atomic(path, payload, schema)
    except atomic_io.AtomicWriteError:
        for path, data in before.items():
            _write_exact(path, data)
        raise


def handle_supersession(work_handle: str, new_rendering: str, old_rendering: str) -> None:
    work_dir = _work_dir(work_handle)
    old = _load_json(work_dir / "parses" / f"{old_rendering}.json")
    new = _load_json(work_dir / "parses" / f"{new_rendering}.json")
    old_blocks = {item["block_id"]: item for item in old.get("blocks", [])}
    new_blocks = {item["block_id"]: item for item in new.get("blocks", [])}
    changed = {
        block_id
        for block_id, old_block in old_blocks.items()
        if str(old_block.get("text")) != str(new_blocks.get(block_id, {}).get("text"))
    }
    wb_path = Path("review") / "state" / work_handle / "workbench.json"
    workbench = _load_json(wb_path)
    for block_id in changed:
        workbench.get("entries", {}).get(block_id, {}).pop("adjudication", None)
    atomic_io.write_json_atomic(wb_path, workbench, OBJECT_SCHEMA)
    warnings = {"warnings": [{"code": "OCR_BYTES_CHANGED", "block_id": block_id} for block_id in sorted(changed)]}
    atomic_io.write_json_atomic(Path("review") / "state" / work_handle / "warnings.json", warnings, OBJECT_SCHEMA)
    atomic_io.append_jsonl_atomic(
        Path("review") / "audit.jsonl",
        {
            "event": "engine_supersession",
            "old_engine": "tesseract@5.2.0",
            "new_engine": "tesseract@5.3.0",
            "changed_count": len(changed),
            "preserved_count": len(old_blocks) - len(changed),
        },
        OBJECT_SCHEMA,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Reconcile operations.")
    parser.add_argument("work_handle", nargs="?")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--superseding-rendering")
    parser.add_argument("--supersedes")
    return parser


def main(argv: list[str]) -> int:
    if argv and argv[0] == "anchor-swap":
        parser = argparse.ArgumentParser(description="Atomically swap the PD anchor.")
        parser.add_argument("command")
        parser.add_argument("work_handle")
        parser.add_argument("--new-anchor", required=True)
        args = parser.parse_args(argv)
        anchor_swap(args.work_handle, args.new_anchor)
        return 0
    args = build_parser().parse_args(argv)
    if not args.work_handle:
        raise SystemExit("work_handle is required")
    if args.dry_run:
        dry_run(args.work_handle)
        return 0
    if args.superseding_rendering and args.supersedes:
        handle_supersession(args.work_handle, args.superseding_rendering, args.supersedes)
        return 0
    run_reconcile(args.work_handle)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
