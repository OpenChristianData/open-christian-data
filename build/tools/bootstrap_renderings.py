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

from ocd_kernel.lib import atomic_io
from ocd_kernel.lib.schema_enums import resolve_schema_path
from build.tools.fetch_rendering import fetch
from build.tools.parse_rendering import parse


OBJECT_SCHEMA = {"type": "object"}
CATALOG_SCHEMA = json.loads(resolve_schema_path("rendering_catalog").read_text(encoding="utf-8"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _work_dir(work_handle: str) -> Path:
    return Path("data") / work_handle


def _catalog_path(work_handle: str) -> Path:
    return _work_dir(work_handle) / "catalog.json"


def _load_catalog(work_handle: str) -> dict[str, Any]:
    return json.loads(_catalog_path(work_handle).read_text(encoding="utf-8"))


def bootstrap(work_handle: str) -> None:
    catalog = _load_catalog(work_handle)
    for rendering in catalog.get("renderings", []):
        source_url = rendering.get("source_url")
        if not source_url:
            continue
        fetch(str(source_url), work_handle=work_handle, rendering_id=str(rendering["rendering_id"]))
        parse(str(rendering["rendering_id"]))


def _passes_r58(metrics: dict[str, Any]) -> tuple[bool, str | None]:
    if float(metrics.get("global_agreement", 0)) < 0.90:
        return False, "global agreement gate failed"
    for page in metrics.get("pages", []):
        if int(page.get("comparable_blocks", 0)) >= 6 and float(page.get("agreement", 0)) < 0.70:
            return False, "per-page agreement gate failed"
    for window in metrics.get("three_page_windows", []):
        if int(window.get("comparable_blocks", 0)) >= 18 and float(window.get("agreement", 0)) < 0.80:
            return False, "multi-page window gate failed"
    return True, None


def promote_pending(work_handle: str, rendering_id: str) -> None:
    work_dir = _work_dir(work_handle)
    catalog_path = _catalog_path(work_handle)
    catalog = _load_catalog(work_handle)
    metrics_path = work_dir / "reconcile-metrics" / f"{rendering_id}.json"
    if metrics_path.exists():
        ok, reason = _passes_r58(json.loads(metrics_path.read_text(encoding="utf-8")))
        if not ok:
            raise SystemExit(reason)

    target = None
    old_rendering = None
    for rendering in catalog.get("renderings", []):
        if rendering.get("rendering_id") == rendering_id:
            target = rendering
        if rendering.get("rendering_id") == (target or {}).get("supersedes"):
            old_rendering = rendering
    if target is None:
        raise ValueError(f"rendering not found: {rendering_id}")
    if target.get("role") != "pending":
        return

    supersedes = target.get("supersedes")
    if supersedes is not None:
        old_rendering = next((item for item in catalog.get("renderings", []) if item.get("rendering_id") == supersedes), None)
        if old_rendering is not None:
            old_rendering["superseded_by"] = rendering_id
    target["role"] = "pd_attestor"
    atomic_io.write_json_atomic(catalog_path, catalog, CATALOG_SCHEMA)

    if old_rendering is not None:
        audit = {
            "event": "engine_supersession",
            "old_engine": old_rendering.get("engine"),
            "new_engine": target.get("engine"),
        }
        atomic_io.append_jsonl_atomic(Path("review") / "audit.jsonl", audit, OBJECT_SCHEMA)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap all renderings for a work.")
    parser.add_argument("work_handle", nargs="?")
    return parser


def main(argv: list[str]) -> int:
    if argv and argv[0] == "promote-pending":
        parser = argparse.ArgumentParser(description="Promote a pending rendering after R58 checks.")
        parser.add_argument("command")
        parser.add_argument("work_handle")
        parser.add_argument("--rendering-id", required=True)
        args = parser.parse_args(argv)
        promote_pending(args.work_handle, args.rendering_id)
        return 0
    args = build_parser().parse_args(argv)
    if not args.work_handle:
        raise SystemExit("work_handle is required")
    bootstrap(args.work_handle)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
