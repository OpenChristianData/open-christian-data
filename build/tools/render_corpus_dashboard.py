"""Render review/index.html — corpus dashboard for review state.

For every resource currently in data/, show:
- resource id + link to per-file review HTML
- confidence axes (structural_fidelity, text_fidelity, edition_provenance)
- outstanding warning count (from sidecar entries; warnings not yet
  dismissed or acknowledged)
- dead-letter counts (read from review/dead-letter/index.json)
- applier-state counts (approved waiting / applied / deferred) from the
  resource's correction ledger if present

Mobile-responsive via build/assets/review.css. Print stylesheet covers
PDF-needs use cases. Renderer cache (build/lib/render_cache.py) governs
incremental regeneration.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))
from build.lib.paths import REPO_ROOT  # noqa: E402

ASSETS = REPO_ROOT / "build" / "assets" / "review.css"


def _safe(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _data_records() -> list[Path]:
    data_dir = REPO_ROOT / "data"
    if not data_dir.exists():
        return []
    return sorted(data_dir.rglob("*.json"))


def _ledger_path(record_path: Path) -> Path:
    rel = record_path.relative_to(REPO_ROOT / "data")
    return REPO_ROOT / "review" / "corrections" / rel.with_suffix(".jsonl")


def _sidecar_path(record_path: Path) -> Path:
    rel = record_path.relative_to(REPO_ROOT / "data")
    return REPO_ROOT / "review" / "state" / rel


def _count_ledger(ledger_path: Path) -> dict[str, int]:
    if not ledger_path.exists():
        return {"approved": 0, "applied": 0, "proposed": 0, "rejected": 0, "deferred": 0}
    counts = defaultdict(int)
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        status = entry.get("status", "unknown")
        counts[status] += 1
        if entry.get("applier_deferred_reason"):
            counts["deferred"] += 1
    return dict(counts)


def _count_outstanding_warnings(sidecar: dict[str, Any] | None) -> dict[str, int]:
    if not sidecar:
        return {"acknowledged": 0, "dismissed": 0, "entries": 0}
    acknowledged = 0
    dismissed = 0
    entries = sidecar.get("entries", {})
    for entry_state in entries.values():
        acknowledged += len(entry_state.get("warnings_acknowledged", []))
        dismissed += len(entry_state.get("warnings_dismissed", []))
    return {"acknowledged": acknowledged, "dismissed": dismissed, "entries": len(entries)}


def _confidence_axes(sidecar: dict[str, Any] | None) -> dict[str, str]:
    if not sidecar:
        return {"structural_fidelity": "n/a", "text_fidelity": "n/a", "edition_provenance": "n/a"}
    return sidecar.get("confidence", {})


def _resource_block(
    record_path: Path,
    sidecar: dict[str, Any] | None,
    ledger_counts: dict[str, int],
    dead_letter: dict[str, Any] | None,
) -> str:
    meta = {}
    record_data = _load_json(record_path)
    if record_data:
        meta = record_data.get("meta", {}) or {}
    resource_id = meta.get("id") or record_path.stem
    relative_data_path = record_path.relative_to(REPO_ROOT / "data")
    review_path = REPO_ROOT / "review" / relative_data_path.with_suffix("") / "index.html"
    resource_label = _safe(resource_id)
    if review_path.exists():
        review_link = review_path.relative_to(REPO_ROOT).as_posix()
        resource_label = f'<a href="{_safe(review_link)}">{resource_label}</a>'
    confidence = _confidence_axes(sidecar)
    counts = _count_outstanding_warnings(sidecar)
    dl_total = (dead_letter or {}).get("total", 0)
    applier_approved = ledger_counts.get("approved", 0)
    applier_applied = ledger_counts.get("applied", 0)
    applier_deferred = ledger_counts.get("deferred", 0)

    return (
        '<div class="dashboard-resource">'
        f"<div>{resource_label}"
        f'<div class="confidence-grid">'
        f'<div class="axis"><div class="axis-label">structural</div>'
        f'<div class="axis-value">{_safe(confidence.get("structural_fidelity", "n/a"))}</div></div>'
        f'<div class="axis"><div class="axis-label">text</div>'
        f'<div class="axis-value">{_safe(confidence.get("text_fidelity", "n/a"))}</div></div>'
        f'<div class="axis"><div class="axis-label">edition</div>'
        f'<div class="axis-value">{_safe(confidence.get("edition_provenance", "n/a"))}</div></div>'
        f'</div></div>'
        f'<div class="dashboard-counts">'
        f'<span class="pill">entries {counts["entries"]}</span>'
        f'<span class="pill">ack {counts["acknowledged"]}</span>'
        f'<span class="pill warn">dismiss {counts["dismissed"]}</span>'
        f'<span class="pill error">dead-letter {dl_total}</span>'
        f'<span class="pill">approved {applier_approved}</span>'
        f'<span class="pill ok">applied {applier_applied}</span>'
        f'<span class="pill warn">deferred {applier_deferred}</span>'
        f'</div>'
        f'</div>'
    )


def render_dashboard(
    *,
    repo_root: Path = REPO_ROOT,
    dead_letter_index: dict[str, Any] | None = None,
) -> str:
    css = ASSETS.read_text(encoding="utf-8") if ASSETS.exists() else ""
    if "</style>" in css:
        raise ValueError("CSS contains a </style> sequence; refusing to inline-render")
    dl_resources = (dead_letter_index or {}).get("resources", {})
    records = sorted((repo_root / "data").rglob("*.json"))
    rendered = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<title>OCD review dashboard</title>',
        f'<style>{css}</style>',
        '</head><body><main>',
        '<h1>OCD review dashboard</h1>',
        f'<p>{len(records)} resources currently in data/.</p>',
    ]
    for record_path in records:
        sidecar = _load_json(_sidecar_path(record_path))
        ledger_counts = _count_ledger(_ledger_path(record_path))
        resource_id = (_load_json(record_path) or {}).get("meta", {}).get("id") or record_path.stem
        dl = dl_resources.get(resource_id)
        rendered.append(_resource_block(record_path, sidecar, ledger_counts, dl))
    rendered.append('</main></body></html>')
    return "\n".join(rendered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "review" / "index.html",
    )
    parser.add_argument(
        "--dead-letter-index",
        type=Path,
        default=REPO_ROOT / "review" / "dead-letter" / "index.json",
    )
    args = parser.parse_args(argv)

    dl_index = _load_json(args.dead_letter_index) or {"resources": {}}
    body = render_dashboard(dead_letter_index=dl_index)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(body, encoding="utf-8")
    print(f"wrote {args.out} ({len(body)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
