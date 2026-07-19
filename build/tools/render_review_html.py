"""Render OCD resource JSON as local HTML for human review."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any


_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib import review_state  # noqa: E402
from build.lib.render_cache import (  # noqa: E402
    CacheKey,
    CacheManifest,
    DEFAULT_CACHE_PATH,
    producer_registry_version,
    renderer_version,
    sha256_of_file,
)
from build.lib.render_strategies import get_strategy  # noqa: E402
from ocd_kernel.lib.text_extractor import effective_resource_type  # noqa: E402
from ocd_kernel.lib.schema_enums import resolve_schema_path  # noqa: E402
from build.lib.warning_producers import discover_producers, run_all_producers  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402


DEFAULT_DATA_ROOT = REPO_ROOT / "data"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "review"
SCHEMAS_DIR = REPO_ROOT / "schemas" / "v1"
SEVERITIES = ("info", "warning", "error")


def build_output_path(source_path: Path, data_root: Path, output_root: Path) -> Path:
    """Return review/<relative-json-path-without-suffix>/index.html."""
    source_path = Path(source_path)
    data_root = Path(data_root)
    output_root = Path(output_root)
    comparable_source = _absolute_for_comparison(source_path)
    comparable_data_root = _absolute_for_comparison(data_root)

    try:
        relative = comparable_source.relative_to(comparable_data_root)
    except ValueError:
        return output_root / Path(source_path.name).with_suffix("") / "index.html"
    return output_root / relative.with_suffix("") / "index.html"


def render_resource_review(
    source_path: Path,
    data_root: Path = DEFAULT_DATA_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    queue_json: Path | None = None,
    out: Path | None = None,
) -> Path:
    """Read one resource JSON file and write its review HTML."""
    source_path = Path(source_path)
    record = json.loads(source_path.read_text(encoding="utf-8"))
    output_path = Path(out) if out is not None else build_output_path(source_path, Path(data_root), Path(output_root))
    try:
        sidecar_path = review_state.derive_sidecar_path(source_path)
    except ValueError:
        sidecar_path = None
    key = CacheKey(
        record_sha256=sha256_of_file(source_path),
        sidecar_sha256=sha256_of_file(sidecar_path) if sidecar_path is not None else "",
        producer_registry_version=producer_registry_version(),
        renderer_version=renderer_version(),
        schema_version=str(record.get("meta", {}).get("schema_version") or ""),
        scans_manifest_checksum_sha256=None,
    )
    resource_id = str(record.get("meta", {}).get("id") or "") or source_path.stem
    manifest = CacheManifest.load(DEFAULT_CACHE_PATH)
    if manifest.is_hit(resource_id, key) and output_path.exists():
        return output_path

    html = render_resource_html(record, source_path=source_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    if queue_json is not None:
        write_review_queue_json(record, source_path=source_path, output_path=Path(queue_json))
    manifest.record(resource_id, key, str(output_path))
    manifest.save(DEFAULT_CACHE_PATH)
    return output_path


def render_commentary_review(
    source_path: Path,
    data_root: Path = DEFAULT_DATA_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    queue_json: Path | None = None,
) -> Path:
    """Compatibility wrapper for the pre-A3 commentary renderer API."""
    return render_resource_review(source_path, data_root=data_root, output_root=output_root, queue_json=queue_json)


def render_commentary_html(payload: dict[str, Any], source_path: Path | None = None) -> str:
    """Compatibility wrapper for commentary tests and callers."""
    return render_resource_html(payload, source_path=source_path)


def render_resource_html(
    payload: dict[str, Any],
    source_path: Path | None = None,
    catalog: dict[str, Any] | None = None,
) -> str:
    """Render one resource payload as standalone HTML."""
    _validate_resource_payload(payload)
    meta = payload["meta"]
    schema_type = str(meta.get("schema_type") or "")
    is_multi_source = schema_type in {"reconciled_record", "modernised_record"}
    if is_multi_source:
        # New schema types carry resource_type in meta; no x-ocd-default-resource-type.
        resource_type = str(meta.get("resource_type") or "reference")
        strategy = None
    else:
        resource_type = effective_resource_type(payload, SCHEMAS_DIR)
        strategy = get_strategy(resource_type)
    sidecar = _load_sidecar_for_record(payload, source_path)

    title = str(meta.get("title") or "Untitled Resource")
    source_label = str(source_path) if source_path is not None else "unspecified source"
    warnings_by_producer = _producer_warnings(payload, source_path, resource_type)
    warnings = _visible_warnings(_flatten_warnings(warnings_by_producer), sidecar)
    body = (
        _render_split_pane_review(payload, catalog=catalog)
        if is_multi_source
        else _render_strategy_layout(strategy, payload)
    )

    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{escape(title)} - OCD review</title>",
            "<style>",
            _stylesheet(),
            "</style>",
            "</head>",
            "<body>",
            '<header class="page-header">',
            f'<div class="eyebrow">OCD {escape(resource_type)} review</div>',
            f"<h1>{escape(title)}</h1>",
            '<dl class="meta-grid">',
            _metadata_row("Author", meta.get("author")),
            _metadata_row("Resource ID", meta.get("id")),
            _metadata_row("Schema", _join_values(meta.get("schema_type"), meta.get("schema_version"))),
            _metadata_row("Resource type", resource_type),
            _metadata_row("Licence", meta.get("license")),
            _metadata_row("Source file", source_label),
            _metadata_row("Source URL", (meta.get("provenance") or {}).get("source_url")),
            _metadata_row("Source edition", (meta.get("provenance") or {}).get("source_edition")),
            "</dl>",
            "</header>",
            '<main class="review-shell">',
            _render_warning_queue(warnings, payload, sidecar, source_path),
            body,
            "</main>",
            _render_review_ui_scripts(),
            "</body>",
            "</html>",
        ]
    )


def build_review_queue(payload: dict[str, Any], source_path: Path) -> dict[str, Any]:
    """Build a JSON-serialisable warning queue for one resource payload."""
    _validate_resource_payload(payload)
    resource_type = effective_resource_type(payload, SCHEMAS_DIR)
    sidecar = _load_sidecar_for_record(payload, source_path)
    warnings_by_producer = _producer_warnings(payload, source_path, resource_type)
    warnings = _visible_warnings(_flatten_warnings(warnings_by_producer), sidecar)
    return {
        "source_file": str(source_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "resource_type": resource_type,
        "total_entries": len(payload["data"]),
        "warning_counts_by_severity": _warning_counts_by_severity(warnings),
        "warnings": warnings,
    }


def write_review_queue_json(payload: dict[str, Any], source_path: Path, output_path: Path) -> Path:
    output_path = Path(output_path)
    queue = build_review_queue(payload=payload, source_path=source_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def _render_strategy_layout(strategy: Any, payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            '<div class="layout">',
            '<aside class="review-panel">',
            "<h2>Navigation</h2>",
            strategy.render_navigation(payload),
            "</aside>",
            '<section class="entries" aria-label="Resource entries">',
            strategy.render_resource(payload),
            "</section>",
            "</div>",
        ]
    )


def _render_split_pane_review(payload: dict[str, Any], catalog: dict[str, Any] | None) -> str:
    blocks = payload.get("blocks") if isinstance(payload.get("blocks"), list) else []
    return "\n".join(
        [
            '<div class="split-pane">',
            '<aside class="review-panel split-nav">',
            "<h2>Blocks</h2>",
            _render_block_navigation(blocks),
            _render_catalog_management(payload, catalog),
            "</aside>",
            '<section class="scan-pane" aria-label="Source scan">',
            _render_scan_pages(blocks),
            "</section>",
            '<section class="text-pane" aria-label="Reconciled text">',
            '<button type="button" class="download-review-state" data-action="download">Download review decisions</button>',
            _render_review_blocks(blocks),
            "</section>",
            "</div>",
        ]
    )


def _render_block_navigation(blocks: list[Any]) -> str:
    items = []
    for index, block in enumerate(blocks, start=1):
        block_dict = block if isinstance(block, dict) else {}
        block_id = str(block_dict.get("block_id") or f"block-{index}")
        items.append(f'<li><a href="#{escape(_anchor_id(block_id))}">{escape(block_id)}</a></li>')
    if not items:
        return '<p class="empty-state">No blocks available.</p>'
    return f'<ol class="nav-list">{"".join(items)}</ol>'


def _render_scan_pages(blocks: list[Any]) -> str:
    seen: set[tuple[str, int]] = set()
    figures = []
    for block in blocks:
        block_dict = block if isinstance(block, dict) else {}
        for page in _source_pages(block_dict):
            rendering_id = page.get("rendering_id")
            page_number = page.get("page_number")
            if not isinstance(rendering_id, str) or not isinstance(page_number, int):
                continue
            key = (rendering_id, page_number)
            if key in seen:
                continue
            seen.add(key)
            src = f"scans-derived/{rendering_id}/p{page_number}.webp"
            label = f"{rendering_id} page {page_number}"
            figures.append(
                "\n".join(
                    [
                        f'<figure class="scan-page" data-rendering-id="{escape(rendering_id)}" data-page-number="{page_number}">',
                        f'<img src="{escape(src)}" alt="{escape(label)}">',
                        f"<figcaption>{escape(label)}</figcaption>",
                        '<div class="bbox-overlay" aria-hidden="true"></div>',
                        "</figure>",
                    ]
                )
            )
    if not figures:
        return '<p class="empty-state">No scan derivative available.</p>'
    return "\n".join(figures)


def _render_review_blocks(blocks: list[Any]) -> str:
    rendered = []
    for index, block in enumerate(blocks, start=1):
        block_dict = block if isinstance(block, dict) else {}
        block_id = str(block_dict.get("block_id") or f"block-{index}")
        rendered.append(
            "\n".join(
                [
                    f'<article class="review-block" id="{escape(_anchor_id(block_id))}">',
                    '<div class="entry-toolbar">',
                    f'<span class="entry-type">Block type: {escape(str(block_dict.get("block_type") or "unknown"))}</span>',
                    f'<a class="entry-id" href="#{escape(_anchor_id(block_id))}">{escape(block_id)}</a>',
                    "</div>",
                    _render_block_text(block_dict),
                    _render_disagreements(block_dict),
                    _render_structural_disagreements(block_dict),
                    _render_modernisations(block_dict),
                    _render_block_source_pages(block_dict),
                    "</article>",
                ]
            )
        )
    if not rendered:
        return '<p class="empty-state">No review blocks available.</p>'
    return "\n".join(rendered)


def _render_block_text(block: dict[str, Any]) -> str:
    original = str(block.get("original_text") or "")
    modern = str(block.get("modern_text") or "")
    parts = [
        '<section class="block-text">',
        "<h3>Original text</h3>",
        f"<p>{escape(original)}</p>",
    ]
    if modern:
        parts.extend(["<h3>Modern text</h3>", f"<p>{escape(modern)}</p>"])
    parts.append("</section>")
    return "\n".join(parts)


def _render_block_source_pages(block: dict[str, Any]) -> str:
    page_links = []
    for page in _source_pages(block):
        rendering_id = page.get("rendering_id")
        page_number = page.get("page_number")
        if not isinstance(rendering_id, str) or not isinstance(page_number, int):
            continue
        attrs = [
            f'data-rendering-id="{escape(rendering_id)}"',
            f'data-page-number="{page_number}"',
        ]
        bbox = page.get("bbox")
        if isinstance(bbox, dict):
            bbox_json = json.dumps(bbox, separators=(",", ":"), sort_keys=True)
            attrs.append(f'data-bbox="{escape(bbox_json, quote=True)}"')
        text = str(block.get("original_text") or "")
        raw_bbox = f"<!-- {bbox_json} -->" if isinstance(bbox, dict) else ""
        page_links.append(f'{raw_bbox}<button type="button" class="hocr-block" {" ".join(attrs)}>{escape(text)}</button>')
    if not page_links:
        return ""
    return '<section class="source-page-links"><h4>Source pages</h4>' + "".join(page_links) + "</section>"


def _render_disagreements(block: dict[str, Any]) -> str:
    disagreements = block.get("disagreements")
    if not isinstance(disagreements, list) or not disagreements:
        return ""
    items = []
    for disagreement in disagreements:
        if not isinstance(disagreement, dict):
            continue
        reading_a = str(disagreement.get("reading_a") or "")
        reading_b = str(disagreement.get("reading_b") or "")
        kind = str(disagreement.get("kind") or "disagreement")
        items.append(
            '<li class="disagreement" data-kind="'
            + escape(kind)
            + '"><button type="button" class="reading" data-reading="a">'
            + escape(reading_a)
            + '</button><button type="button" class="reading" data-reading="b">'
            + escape(reading_b)
            + "</button></li>"
        )
    if not items:
        return ""
    return '<section class="disagreement-affordance"><h4>Disagreements</h4><ul>' + "".join(items) + "</ul></section>"


def _render_structural_disagreements(block: dict[str, Any]) -> str:
    structural = block.get("structural_disagreements")
    if not isinstance(structural, list) or not structural:
        return ""
    controls = []
    for item in structural:
        if not isinstance(item, dict):
            continue
        anchor = str(item.get("anchor_block_id") or block.get("block_id") or "")
        controls.append(
            '<div class="structural-control" data-anchor-block-id="'
            + escape(anchor)
            + '"><button type="button" data-action="split">Split</button>'
            + '<button type="button" data-action="merge">Merge</button></div>'
        )
    if not controls:
        return ""
    return '<section class="structural-affordance"><h4>Structural disagreement</h4>' + "".join(controls) + "</section>"


def _render_modernisations(block: dict[str, Any]) -> str:
    modernisations = block.get("modernisations")
    if not isinstance(modernisations, list) or not modernisations:
        return ""
    tokens = []
    for modernisation in modernisations:
        if not isinstance(modernisation, dict):
            continue
        rule_id = str(modernisation.get("rule_id") or "")
        original = str(modernisation.get("original") or "")
        modern = str(modernisation.get("modern") or "")
        tokens.append(
            '<span class="modernisation-token" data-rule-id="'
            + escape(rule_id)
            + '"><span class="original">'
            + escape(original)
            + '</span><span class="modern">'
            + escape(modern)
            + '</span><button type="button" data-action="accept">Accept</button>'
            + '<button type="button" data-action="override">Override</button></span>'
        )
    if not tokens:
        return ""
    return '<section class="modernisation-affordance"><h4>Modernisations</h4>' + "".join(tokens) + "</section>"


def _render_catalog_management(payload: dict[str, Any], catalog: dict[str, Any] | None) -> str:
    if catalog is None:
        return ""
    renderings = catalog.get("renderings")
    if not isinstance(renderings, list):
        return ""
    pd_anchor = str((payload.get("meta") or {}).get("pd_anchor") or "")
    rows = []
    for rendering in renderings:
        if not isinstance(rendering, dict):
            continue
        rendering_id = str(rendering.get("rendering_id") or "")
        role = str(rendering.get("role") or "")
        if not rendering_id:
            continue
        controls = ""
        if role != "pd_anchor" and rendering_id != pd_anchor:
            controls = '<button type="button" data-action="promote">Promote</button>'
        controls += '<button type="button" data-action="demote">Demote</button>'
        rows.append(
            f'<div class="catalog-rendering" data-rendering-id="{escape(rendering_id)}">'
            f'<span>{escape(rendering_id)}</span><span>{escape(role)}</span>{controls}</div>'
        )
    if not rows:
        return ""
    return '<section class="catalog-management"><h2>Catalog</h2>' + "".join(rows) + "</section>"


def _source_pages(block: dict[str, Any]) -> list[dict[str, Any]]:
    pages = block.get("source_pages")
    if not isinstance(pages, list):
        return []
    return [page for page in pages if isinstance(page, dict)]


def _render_review_ui_scripts() -> str:
    script_dir = REPO_ROOT / "build" / "lib" / "review_ui_js"
    if not script_dir.exists():
        return ""
    chunks = []
    for path in sorted(script_dir.glob("*.js")):
        if path.name.endswith(".test.js"):
            continue
        chunks.append(path.read_text(encoding="utf-8"))
    if not chunks:
        return ""
    return "<script>\n" + "\n".join(chunks) + "\n</script>"


def _producer_warnings(payload: dict[str, Any], source_path: Path | None, resource_type: str) -> dict[str, list[dict[str, Any]]]:
    meta = {
        "resource_id": str((payload.get("meta") or {}).get("id") or ""),
        "resource_type": resource_type,
        "record_path": str(source_path) if source_path is not None else "",
    }
    return run_all_producers(payload, meta, producers=discover_producers())


def _flatten_warnings(warnings_by_producer: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for producer_id in sorted(warnings_by_producer):
        for warning in warnings_by_producer[producer_id]:
            flattened.append({"producer": producer_id, **warning})
    return flattened


def _visible_warnings(warnings: list[dict[str, Any]], sidecar: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = _decision_index(sidecar)
    visible = []
    for warning in warnings:
        key = _warning_key(warning)
        if key in decisions["dismissed"]:
            continue
        status = "acknowledged" if key in decisions["acknowledged"] else "open"
        visible.append({**warning, "status": status})
    return sorted(visible, key=_warning_queue_sort_key)


def _warning_queue_sort_key(warning: dict[str, Any]) -> tuple[int, int, str, str, str, str]:
    evidence = warning.get("evidence")
    has_markable_snippet = (
        isinstance(evidence, dict)
        and isinstance(evidence.get("snippet"), str)
        and isinstance(evidence.get("surface"), str)
        and bool(evidence.get("surface"))
    )
    producer = str(warning.get("producer") or "")
    producer_priority = {"ocr_scanner": 0, "llm_triage": 0}.get(producer, 1)
    evidence_dict = evidence if isinstance(evidence, dict) else {}
    return (
        0 if has_markable_snippet else 1,
        producer_priority,
        str(evidence_dict.get("candidate_signature") or warning.get("signature") or ""),
        producer,
        str(warning.get("entry_id") or ""),
        str(warning.get("code") or ""),
    )


def _decision_index(sidecar: dict[str, Any]) -> dict[str, set[tuple[str | None, str, str, str]]]:
    acknowledged: set[tuple[str | None, str, str, str]] = set()
    dismissed: set[tuple[str | None, str, str, str]] = set()
    for entry_id, entry_state in (sidecar.get("entries") or {}).items():
        if not isinstance(entry_state, dict):
            continue
        for decision in entry_state.get("warnings_acknowledged") or []:
            if isinstance(decision, dict):
                acknowledged.add(_decision_key(entry_id, decision))
        for decision in entry_state.get("warnings_dismissed") or []:
            if isinstance(decision, dict):
                dismissed.add(_decision_key(entry_id, decision))
    return {"acknowledged": acknowledged, "dismissed": dismissed}


def _decision_key(entry_id: str, decision: dict[str, Any]) -> tuple[str | None, str, str, str]:
    return (
        entry_id,
        str(decision.get("producer") or ""),
        str(decision.get("code") or ""),
        str(decision.get("signature") or ""),
    )


def _warning_key(warning: dict[str, Any]) -> tuple[str | None, str, str, str]:
    entry_id = warning.get("entry_id")
    return (
        str(entry_id) if entry_id is not None else None,
        str(warning.get("producer") or ""),
        str(warning.get("code") or ""),
        str(warning.get("signature") or ""),
    )


def _load_sidecar_for_record(payload: dict[str, Any], source_path: Path | None) -> dict[str, Any]:
    if source_path is not None:
        try:
            sidecar_path = review_state.derive_sidecar_path(source_path, repo_root=REPO_ROOT)
        except ValueError:
            sidecar_path = None
        if sidecar_path is not None and sidecar_path.exists():
            return review_state.load_sidecar(sidecar_path)
    record_path = str(source_path) if source_path is not None else "<memory>"
    record_bytes = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    meta = payload.get("meta") if isinstance(payload, dict) else {}
    return review_state.empty_sidecar(
        record_path=record_path,
        record_resource_id=str((meta or {}).get("id") or "unknown"),
        record_checksum_sha256=hashlib.sha256(record_bytes).hexdigest(),
        parser_version_seen=str(((meta or {}).get("provenance") or {}).get("processing_script_version") or "unknown@unknown"),
    )


def _render_warning_queue(
    warnings: list[dict[str, Any]],
    record: dict[str, Any],
    sidecar: dict[str, Any],
    source_path: Path | None,
) -> str:
    counts = _warning_counts_by_severity(warnings)
    summary = " ".join(f"{severity}: {counts[severity]}" for severity in SEVERITIES)
    rows = "\n".join(_render_warning_row(warning, record, source_path) for warning in warnings)
    if not rows:
        rows = '<tr><td colspan="8" class="empty-state">No open or acknowledged warnings.</td></tr>'
    return "\n".join(
        [
            '<section class="warning-queue" aria-label="Review warning queue">',
            "<h2>Review warnings</h2>",
            f'<p class="queue-summary">{escape(summary)}</p>',
            '<div class="queue-table-wrap">',
            '<table class="warning-table">',
            "<thead><tr><th>Entry</th><th>Warning</th><th>Message</th><th>Snippet</th><th>Field</th><th>Status</th><th>Acknowledge</th><th>Dismiss</th></tr></thead>",
            f"<tbody>{rows}</tbody>",
            "</table>",
            "</div>",
            _render_confidence_summary(sidecar),
            "</section>",
        ]
    )


def _render_warning_row(warning: dict[str, Any], record: dict[str, Any], source_path: Path | None) -> str:
    entry_id = warning.get("entry_id")
    producer = str(warning.get("producer") or "")
    code = str(warning.get("code") or "")
    signature = str(warning.get("signature") or "")
    field_path = warning.get("field_path")
    return "\n".join(
        [
            "<tr>",
            f"<td>{_entry_link(entry_id)}</td>",
            f"<td><code>{escape(producer)}/{escape(code)}</code>{_legacy_warning_alias(producer, code)}</td>",
            f"<td>{escape(str(warning.get('message') or ''))}</td>",
            f"<td>{_warning_snippet(record, warning)}</td>",
            f"<td><code>{escape(str(field_path or ''))}</code></td>",
            f"<td>{escape(str(warning.get('status') or 'open'))}</td>",
            f"<td>{_action_form('acknowledge', warning, source_path)}</td>",
            f"<td>{_action_form('dismiss', warning, source_path)}</td>",
            "</tr>",
        ]
    )


def _entry_link(entry_id: Any) -> str:
    if not entry_id:
        return "<span>Record</span>"
    anchor = _anchor_id(str(entry_id))
    return f'<a href="#{escape(anchor)}">{escape(str(entry_id))}</a>'


def _legacy_warning_alias(producer: str, code: str) -> str:
    if producer == "historical_lexicon" and code == "archaic_variant":
        return ' <code>historical_lexicon_variant</code>'
    return ""


def _action_form(action: str, warning: dict[str, Any], source_path: Path | None) -> str:
    record = str(source_path) if source_path is not None else ""
    fields = {
        "action": action,
        "record": record,
        "entry": str(warning.get("entry_id") or ""),
        "producer": str(warning.get("producer") or ""),
        "code": str(warning.get("code") or ""),
        "signature": str(warning.get("signature") or ""),
        "reason": "expected" if action == "acknowledge" else "false_positive",
    }
    hidden = "".join(
        f'<input type="hidden" name="{escape(name)}" value="{escape(value)}">' for name, value in fields.items()
    )
    query = "&".join(f"{name}={_urlish(value)}" for name, value in fields.items())
    label = "Ack" if action == "acknowledge" else "Dismiss"
    return (
        f'<form method="get" action="?{escape(query)}">{hidden}'
        f'<button type="submit">{escape(label)}</button></form>'
    )


def _warning_snippet(record: dict[str, Any], warning: dict[str, Any]) -> str:
    evidence = warning.get("evidence")
    source = _source_text(record, warning.get("entry_id"), warning.get("field_path"))
    if isinstance(evidence, dict) and isinstance(evidence.get("snippet"), str):
        source = evidence["snippet"]
    surface = evidence.get("surface") if isinstance(evidence, dict) else None
    if not isinstance(surface, str) or not surface:
        surface = "\ufffd" if "\ufffd" in source else ""
    return _highlighted_snippet(source, surface)


def _source_text(record: dict[str, Any], entry_id: Any, field_path: Any) -> str:
    if not field_path:
        return ""
    field = str(field_path)
    if field.startswith("meta."):
        value: Any = record.get("meta")
        for part in field.split(".")[1:]:
            value = value.get(part) if isinstance(value, dict) else None
        return "" if value is None else str(value)
    entry = _entry_by_id(record, str(entry_id)) if entry_id else None
    if entry is None:
        return ""
    value = _value_at_field_path(entry, field)
    return "" if value is None else str(value)


def _entry_by_id(record: dict[str, Any], entry_id: str) -> dict[str, Any] | None:
    data = record.get("data")
    if not isinstance(data, list):
        return None
    for entry in data:
        if isinstance(entry, dict) and entry.get("entry_id") == entry_id:
            return entry
    return None


def _value_at_field_path(entry: dict[str, Any], field_path: str) -> Any:
    value: Any = entry
    for part in field_path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit():
            index = int(part)
            value = value[index] if 0 <= index < len(value) else None
        else:
            return None
    if isinstance(value, dict) and isinstance(value.get("text"), str):
        return value["text"]
    return value


def _highlighted_snippet(text: str, surface: str, limit: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ""
    mark_start = cleaned.find(surface) if surface else -1
    mark_end = mark_start + len(surface) if mark_start >= 0 else -1
    if mark_start < 0:
        snippet = cleaned[:limit]
        suffix = "..." if len(cleaned) > limit else ""
        return f"<mark>{escape(snippet)}</mark>{escape(suffix)}"
    start = max(0, min(mark_start - 45, len(cleaned) - limit))
    end = min(len(cleaned), start + limit)
    snippet = cleaned[start:end]
    rel_start = max(0, mark_start - start)
    rel_end = min(len(snippet), mark_end - start)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(cleaned) else ""
    return (
        escape(prefix + snippet[:rel_start])
        + f"<mark>{escape(snippet[rel_start:rel_end])}</mark>"
        + escape(snippet[rel_end:] + suffix)
    )


def _render_confidence_summary(sidecar: dict[str, Any]) -> str:
    confidence = sidecar.get("confidence") or {}
    items = "".join(
        f"<li><span>{escape(axis.replace('_', ' '))}</span> {escape(str(confidence.get(axis, 'unverified')))}</li>"
        for axis in ("structural_fidelity", "text_fidelity", "edition_provenance")
    )
    return f'<ul class="confidence-summary">{items}</ul>'


def _warning_counts_by_severity(warnings: list[dict[str, Any]]) -> dict[str, int]:
    counts = {severity: 0 for severity in SEVERITIES}
    for warning in warnings:
        severity = str(warning.get("severity") or "")
        if severity not in counts:
            counts[severity] = 0
        counts[severity] += 1
    return counts


def _validate_resource_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Expected resource JSON object.")
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("Expected resource JSON with meta object and data array.")
    schema_type = meta.get("schema_type")
    if not isinstance(schema_type, str) or not schema_type:
        raise ValueError("Expected resource JSON with meta.schema_type.")
    try:
        schema_path = resolve_schema_path(schema_type)
    except FileNotFoundError:
        raise ValueError(f"Unknown meta.schema_type: {schema_type}")
    # reconciled_record and modernised_record use "blocks"; legacy types use "data".
    if schema_type in {"reconciled_record", "modernised_record"}:
        if not isinstance(payload.get("blocks"), list):
            raise ValueError("Expected reconciled/modernised record with blocks array.")
    else:
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            raise ValueError("Expected resource JSON with at least one data entry.")


def _metadata_row(label: str, value: Any) -> str:
    display = "" if value is None else str(value)
    if not display:
        display = "Not supplied"
    if label == "Source URL" and display.startswith(("http://", "https://")):
        value_html = f'<a href="{escape(display)}">{escape(display)}</a>'
    else:
        value_html = escape(display)
    return f"<div><dt>{escape(label)}</dt><dd>{value_html}</dd></div>"


def _absolute_for_comparison(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _anchor_id(entry_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.:-]+", "-", entry_id).strip("-")
    return slug or "entry"


def _join_values(*values: Any) -> str:
    return " ".join(str(value) for value in values if value)


def _urlish(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:/@-]+", "+", value)


def _iter_resource_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    candidates = sorted(path for path in input_path.rglob("*.json") if path.name != "_manifest.json")
    return [path for path in candidates if _looks_like_resource(path)]


def _iter_commentary_files(input_path: Path) -> list[Path]:
    return [
        path
        for path in _iter_resource_files(input_path)
        if (json.loads(path.read_text(encoding="utf-8")).get("meta") or {}).get("schema_type") == "commentary"
    ]


def _looks_like_resource(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    meta = payload.get("meta") if isinstance(payload, dict) else None
    return isinstance(meta, dict) and isinstance(meta.get("schema_type"), str) and isinstance(payload.get("data"), list)


def _stylesheet() -> str:
    return """
:root {
  color-scheme: light;
  --bg: #f7f6f2;
  --paper: #fffdfa;
  --ink: #24211c;
  --muted: #6e665c;
  --line: #ded7cb;
  --accent: #7b4d2f;
  --label: #0f5f68;
  --warning: #9b2f24;
  --mark: #ffe08a;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: Georgia, "Times New Roman", serif;
  line-height: 1.58;
}

.page-header {
  padding: 32px max(24px, 6vw) 24px;
  border-bottom: 1px solid var(--line);
  background: var(--paper);
}

.eyebrow,
.entry-type,
dt,
h4,
summary,
.warning-table,
.queue-summary,
.confidence-summary {
  font-family: Arial, Helvetica, sans-serif;
}

.eyebrow {
  color: var(--accent);
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

h1 {
  max-width: 980px;
  margin: 8px 0 18px;
  font-size: clamp(2rem, 4vw, 3.8rem);
  line-height: 1.05;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px 24px;
  max-width: 1180px;
  margin: 0;
}

.meta-grid div { min-width: 0; }

dt {
  color: var(--muted);
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
}

dd {
  margin: 2px 0 0;
  overflow-wrap: anywhere;
}

.review-shell {
  padding: 28px max(20px, 5vw) 56px;
}

.warning-queue {
  max-width: 1280px;
  margin: 0 auto 28px;
  border-bottom: 1px solid var(--line);
  padding-bottom: 24px;
}

.warning-queue h2 {
  margin: 0 0 4px;
  font: 700 1rem Arial, Helvetica, sans-serif;
}

.queue-summary {
  margin: 0 0 12px;
  color: var(--muted);
}

.queue-table-wrap {
  max-height: 50vh;
  overflow: auto;
  border: 1px solid var(--line);
  background: var(--paper);
}

.warning-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}

.warning-table th,
.warning-table td {
  border-bottom: 1px solid var(--line);
  padding: 8px;
  text-align: left;
  vertical-align: top;
}

.warning-table th {
  position: sticky;
  top: 0;
  background: #f1eee8;
  z-index: 1;
}

.warning-table code,
.entry-id,
pre {
  font-family: Consolas, "Courier New", monospace;
}

.warning-table button {
  border: 1px solid var(--line);
  border-radius: 4px;
  background: #ffffff;
  color: var(--label);
  cursor: pointer;
  font: inherit;
  padding: 4px 7px;
}

mark {
  background: var(--mark);
  color: inherit;
  padding: 0 2px;
}

.confidence-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  color: var(--muted);
  font-size: 0.85rem;
}

.confidence-summary span {
  color: var(--ink);
  font-weight: 700;
}

.layout {
  display: grid;
  grid-template-columns: minmax(220px, 320px) minmax(0, 860px);
  gap: 28px;
  align-items: start;
  max-width: 1280px;
  margin: 0 auto;
}

.review-panel {
  position: sticky;
  top: 0;
  max-height: 100vh;
  overflow: auto;
  padding: 18px 0;
  color: var(--muted);
}

.review-panel h2 {
  margin: 0 0 8px;
  color: var(--ink);
  font: 700 0.9rem Arial, Helvetica, sans-serif;
}

.nav-list {
  margin: 0 0 24px;
  padding-left: 18px;
}

.nav-list a {
  color: var(--label);
  text-decoration: none;
}

.entries {
  display: grid;
  gap: 22px;
}

.chapter-page,
.headword-page {
  display: grid;
  gap: 18px;
}

.chapter-page > h2,
.headword-page > h2 {
  margin: 0;
  font: 700 1rem Arial, Helvetica, sans-serif;
  color: var(--muted);
  text-transform: uppercase;
}

.entry {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 22px;
}

.entry-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.entry-type {
  color: var(--label);
  font-size: 0.78rem;
  font-weight: 700;
}

.entry-id {
  color: var(--muted);
  font-size: 0.82rem;
  overflow-wrap: anywhere;
}

.entry h3 {
  margin: 0 0 16px;
  font-size: 1.35rem;
  line-height: 1.25;
}

.commentary-text,
.definition-block p {
  margin: 0 0 1rem;
  font-size: 1.08rem;
}

.verse-text,
.summary-block,
.cross-refs,
.alt-terms,
.related-terms,
.definition-block {
  border-left: 3px solid var(--line);
  margin: 14px 0;
  padding-left: 14px;
}

h4 {
  margin: 0 0 4px;
  color: var(--muted);
  font-size: 0.82rem;
  text-transform: uppercase;
}

h4 span,
.summary-block h4 span {
  color: var(--label);
  font-weight: 400;
  text-transform: none;
}

.cross-refs ul,
.alt-terms ul,
.related-terms ul {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  list-style: none;
  margin: 0;
  padding: 0;
}

.cross-refs li,
.alt-terms li,
.related-terms li {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 8px;
  font-family: Arial, Helvetica, sans-serif;
  font-size: 0.82rem;
}

details {
  border-top: 1px solid var(--line);
  margin-top: 18px;
  padding-top: 12px;
}

summary {
  cursor: pointer;
  color: var(--label);
  font-size: 0.9rem;
  font-weight: 700;
}

pre {
  max-height: 420px;
  overflow: auto;
  padding: 12px;
  background: #f1eee8;
  font-size: 0.82rem;
  white-space: pre-wrap;
}

.empty-state {
  margin: 0 0 24px;
}

@media (max-width: 860px) {
  .review-shell {
    padding: 18px 14px 40px;
  }

  .layout {
    grid-template-columns: 1fr;
  }

  .review-panel {
    position: static;
    max-height: none;
    padding: 0;
  }
}

@media print {
  body {
    background: white;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }

  .review-panel {
    position: static;
  }
}
""".strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path", type=Path, help="Resource JSON file or directory containing resource JSON files.")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--out", type=Path, help="Explicit output HTML path. Supported for a single input file.")
    parser.add_argument("--queue-json", type=Path, help="Optional JSON review queue path for a single input file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input_path
    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")

    source_paths = _iter_resource_files(input_path)
    if (args.queue_json is not None or args.out is not None) and len(source_paths) != 1:
        raise ValueError("--out and --queue-json can only be used when rendering a single JSON file.")

    rendered = [
        render_resource_review(
            source_path=source_path,
            data_root=args.data_root,
            output_root=args.output_root,
            queue_json=args.queue_json,
            out=args.out,
        )
        for source_path in source_paths
    ]
    if not rendered:
        raise ValueError(f"No resource JSON files found under {input_path}")
    for output_path in rendered:
        print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
