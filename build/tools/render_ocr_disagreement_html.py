"""Render an OCR-disagreement review page beside source-scan image regions.

For each ocr_scanner or llm_triage warning on a resource, looks up the bbox
via the resource's scans_manifest + per-entry scan_source pointer + hOCR
coordinate data, and emits an HTML row with [image crop] | [canonical OCR
text] | [witness OCR text] | [proposed correction].

Entries without entry.scan_source are skipped silently; CCEL-only SH entries
fall in this bucket because their scan coordinates were never captured.

CLI:
    py -3 build/tools/render_ocr_disagreement_html.py \
        --resource data/reference/schaff-herzog-encyclopedia.json \
        --sidecar review/state/reference/schaff-herzog-encyclopedia.json \
        --out review/reference/schaff-herzog-disagreements.html \
        --max-disagreements 25
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Iterable

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.ocr_coordinates import lookup_bbox, read_hocr
from build.lib.paths import REPO_ROOT  # noqa: E402


def _safe(value: object) -> str:
    return html.escape(str(value) if value is not None else "")


def _row(
    *,
    entry_id: str,
    code: str,
    image_url: str,
    bbox: tuple[int, int, int, int] | None,
    canonical_text: str,
    witness_text: str,
    suggested_correction: str,
) -> str:
    bbox_html = ""
    if bbox is not None:
        x, y, w, h = bbox
        bbox_html = (
            f'<div class="bbox-overlay" '
            f'data-bbox="{x},{y},{w},{h}" '
            f'style="position:absolute; left:{x}px; top:{y}px; width:{w}px; height:{h}px; '
            'border: 2px solid red; pointer-events: none;"></div>'
        )
    img_block = (
        f'<div class="image-cell" style="position:relative; max-width:600px;">'
        f'<a href="{_safe(image_url)}" target="_blank" rel="noopener">'
        f'<img src="{_safe(image_url)}" alt="scan page" '
        'style="max-width:100%; height:auto;"></a>'
        f"{bbox_html}"
        f"</div>"
    )
    return (
        f'<tr><td>{_safe(entry_id)}</td>'
        f'<td>{_safe(code)}</td>'
        f"<td>{img_block}</td>"
        f'<td class="canonical">{_safe(canonical_text)}</td>'
        f'<td class="witness">{_safe(witness_text)}</td>'
        f'<td class="correction">{_safe(suggested_correction)}</td>'
        "</tr>"
    )


def _ocr_warnings(
    warnings: Iterable[dict],
    *,
    producers: tuple[str, ...] = ("ocr_scanner", "llm_triage"),
) -> list[dict]:
    out = []
    for w in warnings:
        if w.get("producer") in producers:
            out.append(w)
    return out


def _entry_index(record: dict) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for entry in record.get("data", []):
        entry_id = entry.get("entry_id")
        if entry_id:
            index[entry_id] = entry
    return index


def render_disagreement_html(
    record: dict,
    warnings: list[dict],
    scans_manifest: dict,
    hocr_coords: dict[tuple[int, str], dict],
    *,
    max_disagreements: int = 25,
) -> str:
    entries = _entry_index(record)
    scans_by_page: dict[tuple[object, int], dict] = {
        (s["volume"], s["page"]): s for s in scans_manifest.get("scans", [])
    }
    rows: list[str] = []
    skipped = 0
    for w in _ocr_warnings(warnings):
        if len(rows) >= max_disagreements:
            break
        entry_id = w.get("entry_id") or ""
        entry = entries.get(entry_id)
        if entry is None:
            skipped += 1
            continue
        scan_source = entry.get("scan_source")
        if not scan_source:
            skipped += 1
            continue
        key = (scan_source.get("volume"), scan_source.get("page"))
        scan = scans_by_page.get(key)
        if scan is None:
            skipped += 1
            continue
        evidence = w.get("evidence") or {}
        surface = evidence.get("surface") or evidence.get("snippet") or ""
        bbox = lookup_bbox(hocr_coords, page=scan_source["page"], text_snippet=str(surface))
        rows.append(
            _row(
                entry_id=entry_id,
                code=w.get("code", ""),
                image_url=scan.get("image_url", ""),
                bbox=bbox,
                canonical_text=evidence.get("canonical_text") or surface,
                witness_text=evidence.get("witness_text") or evidence.get("suggested_replacement") or "",
                suggested_correction=evidence.get("suggested_replacement") or "",
            )
        )
    table = (
        "<table><thead><tr>"
        "<th>entry</th><th>code</th><th>scan</th>"
        "<th>canonical</th><th>witness</th><th>suggested</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )
    body = (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<title>OCR disagreements — {_safe(record.get('meta', {}).get('id', ''))}</title>"
        "<style>body{font-family:system-ui,sans-serif}"
        "td{vertical-align:top;padding:8px;border-bottom:1px solid #ddd}"
        ".canonical,.witness,.correction{max-width:200px;word-wrap:break-word}"
        "img{display:block}</style></head><body>"
        f"<h1>OCR disagreements — {_safe(record.get('meta', {}).get('id', ''))}</h1>"
        f"<p>Showing {len(rows)} disagreement(s); {skipped} skipped (no scan_source or unmatched).</p>"
        + table
        + "</body></html>"
    )
    return body


def _open_warnings_from_producers(record: dict, sidecar: dict | None) -> list[dict]:
    """Run the producer registry over the record and return visible OCR
    warnings (ocr_scanner + llm_triage), filtering out sidecar-acknowledged
    or sidecar-dismissed signatures.

    The review_state sidecar carries decisions under ``entries``, NOT a
    top-level ``warnings`` array. Pre-fix code read ``sidecar["warnings"]``
    which is always empty under the current schema, so the renderer
    silently produced empty pages.
    """
    from build.lib.warning_producers import discover_producers, run_all_producers  # noqa: WPS433
    from build.lib.text_extractor import effective_resource_type  # noqa: WPS433

    meta = {
        "resource_id": str((record.get("meta") or {}).get("id") or ""),
        "resource_type": effective_resource_type(record, REPO_ROOT / "schemas" / "v1"),
        "record_path": "",
    }
    results = run_all_producers(record, meta, producers=discover_producers())
    decided: set[tuple[str, str]] = set()
    for entry_id, state in (sidecar or {}).get("entries", {}).items():
        if not isinstance(state, dict):
            continue
        for bucket in ("warnings_acknowledged", "warnings_dismissed"):
            for decision in state.get(bucket) or []:
                if isinstance(decision, dict):
                    sig = decision.get("signature")
                    if isinstance(sig, str):
                        decided.add((str(entry_id), sig))

    warnings: list[dict] = []
    for producer_id, ws in results.items():
        if producer_id not in {"ocr_scanner", "llm_triage"}:
            continue
        for warning in ws:
            entry_id = str(warning.get("entry_id") or "")
            signature = str(warning.get("signature") or "")
            if (entry_id, signature) in decided:
                continue
            w = dict(warning)
            w.setdefault("producer", producer_id)
            warnings.append(w)
    return warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource", required=True, type=Path)
    parser.add_argument("--sidecar", required=False, type=Path,
                        help="Optional review-state sidecar; decisions filter producer warnings.")
    parser.add_argument("--hocr", required=False, type=Path, help="Local hOCR file (optional; required for bbox)")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--max-disagreements", type=int, default=25)
    args = parser.parse_args(argv)

    record = json.loads(args.resource.read_text(encoding="utf-8"))
    sidecar = json.loads(args.sidecar.read_text(encoding="utf-8")) if args.sidecar else None
    manifest_path = REPO_ROOT / "sources" / record["meta"]["id"] / "scans_manifest.json"
    scans_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    coords = read_hocr(args.hocr) if args.hocr else {}

    warnings = _open_warnings_from_producers(record, sidecar)

    body = render_disagreement_html(
        record,
        warnings,
        scans_manifest,
        coords,
        max_disagreements=args.max_disagreements,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(body, encoding="utf-8")
    print(f"wrote {args.out} ({len(body)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
