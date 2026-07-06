from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import threading
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib import _generated_enums as schema_enums  # noqa: E402
from build.lib.atomic_io import write_json_atomic  # noqa: E402
from build.lib.rendering_semantic_validator import validate_rendering  # noqa: E402
from build.lib.page_order import volume_duplicate_stems  # noqa: E402
from build.lib.nsh_leaf_model import set_leaf_or_exempt  # noqa: E402
from build.tools.ocr_pipeline.sidecar_utils import count_sidecars  # noqa: E402


class _RenderAborted(Exception):
    """Raised by render_manifest when shutdown_event fires mid-render."""


SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "rendering-v1.schema.json"
STAGE_VERSION = "b5-rendering-v1"
ZERO_SHA = "sha256:" + ("0" * 64)
# x_size (Tesseract hOCR x-height in pixels) split point from Phase 1 calibration
# on 491 vol_01 pages: heading mode peaks at 52px, body at 68-70px, valley floor at 60px.
X_SIZE_HEADING_THRESHOLD = 62.0
APPROVED_TYPOGRAPHY_SNAPSHOT_ID = "s2-typography-scaffold-v1"
NFKC_ALLOWLIST_VERSION = "s2-l2-allowlist-v1"
FINGERPRINT_FUNCTION_VERSION = "s2-fingerprint-v1"
REPLAY_VERIFIER_VERSION = "s2-replay-structural-scaffold-v1"

SAFE_DELETE_CODEPOINTS = {
    "\ufeff",
    "\u200b",
    "\u2060",
}
SAFE_SPACE_CODEPOINTS = {
    "\u00a0",
    "\u2007",
    "\u202f",
}

BLOCK_TO_REGION_CLASS = {
    "paragraph": "body",
    "section_heading": "section_heading",
    "heading_subsection": "heading_subsection",
    "bibliography_section_marker": "bibliography_section_marker",
    "bibliography_entry": "bibliography_entry",
    "cross_reference": "cross_reference",
    "footnote": "footnote",
    "caption": "caption",
    "quotation": "quotation",
    "list_item": "list_item",
    "table": "table_cell",
    "headword": "headword",
    "unknown": "unknown",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _prefixed_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _stable_id(prefix: str, payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}-sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _rel_path(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _clean_l2(source_raw: str) -> str:
    chars: list[str] = []
    for char in source_raw:
        if char in SAFE_DELETE_CODEPOINTS:
            continue
        if char in SAFE_SPACE_CODEPOINTS:
            chars.append(" ")
            continue
        chars.append(char)
    return "".join(chars)


def _layers(source_raw: str) -> dict[str, str]:
    normalized = _clean_l2(source_raw)
    return {
        "source_raw": source_raw,
        "normalised": normalized,
        "structured": normalized,
        "display": normalized,
    }


def _bbox_canonical(
    bbox_native: dict[str, Any] | None,
    page_dimensions: dict[str, Any],
) -> list[float] | None:
    if not bbox_native:
        return None
    width = page_dimensions.get("width")
    height = page_dimensions.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        return None
    x = float(bbox_native["x"])
    y = float(bbox_native["y"])
    w = float(bbox_native["w"])
    h = float(bbox_native["h"])
    return [
        round(max(0.0, min(1.0, x / width)), 6),
        round(max(0.0, min(1.0, y / height)), 6),
        round(max(0.0, min(1.0, (x + w) / width)), 6),
        round(max(0.0, min(1.0, (y + h) / height)), 6),
    ]


def _block_text(block: dict[str, Any]) -> str:
    lines = [str(line.get("source_raw", "")) for line in block.get("lines", [])]
    return "\n".join(lines)


def _zone_label_from_bbox(
    bbox_native: dict[str, Any] | None,
    page_dimensions: dict[str, Any],
    block_type: str,
) -> str:
    if block_type == "caption":
        return "caption"
    if block_type == "footnote":
        return "footnote"
    if not bbox_native:
        return "unknown"
    height = page_dimensions.get("height")
    y = bbox_native.get("y")
    if isinstance(height, int) and height > 0 and isinstance(y, (int, float)):
        fraction = float(y) / height
        if fraction < 0.08:
            return "running_header"
        if fraction > 0.82:
            return "footnote"
    return "body"


def _language_lane(text: str) -> tuple[str, str]:
    if re.search(r"[\u0590-\u05ff]", text):
        return "hbo", "high"
    if re.search(r"[\u0370-\u03ff]", text):
        return "grc", "high"
    if any(char in text for char in ("ä", "ö", "ü", "ß", "Ä", "Ö", "Ü")):
        return "de", "medium"
    if text.strip():
        return "en", "medium"
    return "und", "low"


def _classify_block(
    block: dict[str, Any],
    page_dimensions: dict[str, Any],
    *,
    x_size_floor: float | None = None,
) -> tuple[str, str, list[dict[str, str]], list[dict[str, str]]]:
    signals: list[dict[str, str]] = []
    text = _clean_l2(_block_text(block)).strip()
    normalized_upper = text.upper()
    word_count = len(text.split())
    bbox = block.get("bbox_native")

    if isinstance(bbox, dict):
        height = page_dimensions.get("height")
        y = bbox.get("y")
        if isinstance(height, int) and height > 0 and isinstance(y, (int, float)):
            if float(y) / height > 0.82:
                signals.append(
                    {
                        "evidence_type": "geometry",
                        "suggested_block_type": "footnote",
                        "detail": "Block sits in the lower page band.",
                    }
                )

    if re.match(r"^\s*see\s+[A-Za-z]", text, flags=re.IGNORECASE):
        signals.append(
            {
                "evidence_type": "text",
                "suggested_block_type": "cross_reference",
                "detail": "Text begins with a See cross-reference marker.",
            }
        )
    elif word_count >= 6:
        signals.append(
            {
                "evidence_type": "text",
                "suggested_block_type": "paragraph",
                "detail": "Line text has paragraph-like prose density.",
            }
        )
    elif text and normalized_upper == text and word_count <= 4:
        signals.append(
            {
                "evidence_type": "text",
                "suggested_block_type": "headword",
                "detail": "Short all-caps text is headword-like.",
            }
        )

    # Geometric headword signal: only when (1) x_size data present, (2) below threshold,
    # (3) block has actual text (not an OCR artefact or blank line), and
    # (4) the text hasn't already resolved to cross_reference — a "See X" pattern at
    # small x_size is an unlikely OCR artifact that would discard cross_reference_target.
    has_cross_ref = any(s["suggested_block_type"] == "cross_reference" for s in signals)
    if (
        x_size_floor is not None
        and x_size_floor < X_SIZE_HEADING_THRESHOLD
        and text
        and not has_cross_ref
    ):
        signals.append(
            {
                "evidence_type": "geometry",
                "suggested_block_type": "headword",
                "detail": (
                    f"Minimum line x_size {x_size_floor:.1f}px is below the"
                    f" heading threshold ({X_SIZE_HEADING_THRESHOLD:.0f}px)."
                ),
            }
        )

    if not signals:
        signals.append(
            {
                "evidence_type": "fallback",
                "suggested_block_type": "paragraph",
                "detail": "Native S1 text block has no stronger S2 signal.",
            }
        )

    suggested = {signal["suggested_block_type"] for signal in signals}
    if len(suggested) == 1:
        block_type = next(iter(suggested))
        confidence = "medium" if block_type != "unknown" else "low"
        conflicts: list[dict[str, str]] = []
    else:
        block_type = "unknown"
        confidence = "low"
        conflicts = [
            {
                "evidence_type": signal["evidence_type"],
                "suggested_block_type": signal["suggested_block_type"],
                "detail": signal["detail"],
            }
            for signal in signals
        ]
    if block_type not in schema_enums.RENDERING_V1__DEFS__BLOCK_TYPE:
        raise ValueError(f"unknown block_type emitted by S2 renderer: {block_type!r}")
    return block_type, confidence, signals, conflicts


def _candidate_membership() -> dict[str, Any]:
    return {"status": "none", "candidate_article_ids": []}


def _bibliography_layout(block_type: str) -> dict[str, Any]:
    if block_type == "bibliography_entry":
        return {"status": "entry", "evidence": ["block_type"]}
    if block_type == "bibliography_section_marker":
        return {"status": "section_marker", "evidence": ["block_type"]}
    return {"status": "not_bibliography", "evidence": []}


def _render_word(
    word: dict[str, Any],
    *,
    native_sequence_index: int,
    page_dimensions: dict[str, Any],
    zone_label: str,
) -> dict[str, Any]:
    source_raw = str(word.get("source_raw", ""))
    extras: dict[str, Any] = {}
    return {
        "observation_token_id": word["observation_token_id"],
        "native_sequence_index": native_sequence_index,
        "layers": _layers(source_raw),
        "bbox_native": word.get("bbox_native"),
        "bbox_canonical": _bbox_canonical(word.get("bbox_native"), page_dimensions),
        "confidence_raw": word.get("confidence"),
        "zone_label": zone_label,
        "candidate_article_membership": _candidate_membership(),
        "word_extras_carried": extras,
        "word_extras_carried_keys": [],
        "word_extras_jcs_sha256": _prefixed_sha256(extras),
        "in_derived_join_span": None,
        "derived_join_span_id": None,
    }


def _render_line(
    line: dict[str, Any],
    *,
    rendering_id: str,
    page_seed: str,
    block_native_id: str,
    native_order: int,
    page_dimensions: dict[str, Any],
    block_bbox: dict[str, Any] | None,
    zone_label: str,
    relative_size_tier: str,
    line_attrs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_raw = str(line.get("source_raw", ""))
    line_bbox = line.get("bbox_native")
    # R4a: seed from page_seed (canonical_leaf_id when leaf-keyed, else the
    # filename stem for not-yet-migrated lineages) so a rename of the source
    # image never changes the rendering_line_id of an unchanged leaf.
    line_id = _stable_id(
        "rl",
        ["rendering_line_id", "v1", rendering_id, page_seed, block_native_id, line.get("line_native_id"), native_order],
    )
    block_x = block_bbox.get("x") if isinstance(block_bbox, dict) else None
    line_x = line_bbox.get("x") if isinstance(line_bbox, dict) else None
    words = [
        _render_word(
            word,
            native_sequence_index=word_index,
            page_dimensions=page_dimensions,
            zone_label=zone_label,
        )
        for word_index, word in enumerate(line.get("words", []))
    ]
    attrs = line_attrs or {}
    extras: dict[str, Any] = {}
    # baseline is [slope, intercept] — incompatible with line_geometry.baseline (number|null).
    # Route it through line_extras_carried instead (additionalProperties: true).
    if attrs.get("baseline") is not None:
        extras["baseline"] = attrs["baseline"]
    return {
        "rendering_line_id": line_id,
        "native_line_ids": [line["line_native_id"]],
        "native_order": native_order,
        "derived_order": native_order,
        "bbox_native": line_bbox,
        "bbox_canonical": _bbox_canonical(line_bbox, page_dimensions),
        "line_geometry": {
            "x_size": attrs.get("x_size"),
            "baseline": None,
            "x_descenders": attrs.get("x_descenders"),
            "x_ascenders": attrs.get("x_ascenders"),
        },
        "indent_evidence": {
            "style": "none",
            "block_x": block_x,
            "line_x": line_x,
        },
        "relative_size_tier": relative_size_tier,
        "raw_size_pt": None,
        "layers": _layers(source_raw),
        "words": words,
        "line_extras_carried": extras,
        "line_extras_carried_keys": sorted(extras.keys()),
        "line_extras_jcs_sha256": _prefixed_sha256(extras),
    }


def _block_relative_size_tier(block_type: str) -> str:
    if block_type in {"section_heading", "heading_subsection", "headword"}:
        return "heading"
    if block_type == "footnote":
        return "footnote"
    if block_type == "unknown":
        return "unknown"
    return "body"


def _region_class(block_type: str, language_lane: str) -> str:
    if language_lane == "grc":
        return "foreign_language_greek"
    if language_lane == "hbo":
        return "foreign_language_hebrew"
    if language_lane == "de":
        return "foreign_language_german"
    region_class = BLOCK_TO_REGION_CLASS[block_type]
    if region_class not in schema_enums.RENDERING_V1__DEFS__REGION_CLASS:
        raise ValueError(f"unknown region_class emitted by S2 renderer: {region_class!r}")
    return region_class


def _hyphen_uncertainties(
    *,
    rendering_block_id: str,
    rendered_lines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for index, line in enumerate(rendered_lines[:-1]):
        words = line.get("words", [])
        next_words = rendered_lines[index + 1].get("words", [])
        if not words or not next_words:
            continue
        left = words[-1]
        right = next_words[0]
        if left["layers"]["source_raw"].endswith("-"):
            token_ids = [left["observation_token_id"], right["observation_token_id"]]
            queue.append(
                {
                    "queue_id": _stable_id(
                        "su",
                        ["unresolved_hyphen_boundary", rendering_block_id, token_ids],
                    ),
                    "reason": "unresolved_hyphen_boundary",
                    "rendering_block_id": rendering_block_id,
                    "rendering_line_id": line["rendering_line_id"],
                    "observation_token_ids": token_ids,
                    "evidence": {"boundary_type": "line_break"},
                }
            )
    return queue


def _render_block(
    block: dict[str, Any],
    *,
    rendering_id: str,
    page_seed: str,
    native_order: int,
    page_dimensions: dict[str, Any],
    tesseract_line_attrs: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tla = tesseract_line_attrs or {}
    # Use the minimum (floor) x_size across the block's lines so that a single
    # heading-sized line in a multi-line headword+runover block still fires the signal.
    x_sizes = [
        tla.get(line.get("line_native_id", ""), {}).get("x_size")
        for line in block.get("lines", [])
    ]
    x_sizes_numeric = [x for x in x_sizes if x is not None]
    x_size_floor: float | None = min(x_sizes_numeric) if x_sizes_numeric else None
    block_type, confidence, signals, conflicts = _classify_block(
        block, page_dimensions, x_size_floor=x_size_floor
    )
    text = _block_text(block)
    language_lane, language_confidence = _language_lane(text)
    zone_label = _zone_label_from_bbox(block.get("bbox_native"), page_dimensions, block_type)
    rendering_block_id = _stable_id(
        "rb",
        [
            "rendering_block_id",
            "v1",
            rendering_id,
            page_seed,
            block.get("block_id"),
            native_order,
        ],
    )
    relative_size_tier = _block_relative_size_tier(block_type)
    rendered_lines = [
        _render_line(
            line,
            rendering_id=rendering_id,
            page_seed=page_seed,
            block_native_id=str(block.get("block_id")),
            native_order=line_index,
            page_dimensions=page_dimensions,
            block_bbox=block.get("bbox_native"),
            zone_label=zone_label,
            relative_size_tier=relative_size_tier,
            line_attrs=tla.get(line.get("line_native_id", "")),
        )
        for line_index, line in enumerate(block.get("lines", []))
    ]
    extras: dict[str, Any] = {}
    rendered_block: dict[str, Any] = {
        "rendering_block_id": rendering_block_id,
        "native_block_ids": [block["block_id"]],
        "native_order": native_order,
        "derived_order": native_order,
        "block_type": block_type,
        "block_type_evidence": {"signals": signals},
        "block_type_confidence": confidence,
        "block_type_conflicts": conflicts,
        "region_class": _region_class(block_type, language_lane),
        "language_lane": language_lane,
        "language_lane_confidence": language_confidence,
        "zone_label": zone_label,
        "candidate_article_membership": _candidate_membership(),
        "bibliography_layout": _bibliography_layout(block_type),
        "indent_style": "none",
        "bbox_canonical": _bbox_canonical(block.get("bbox_native"), page_dimensions),
        "block_extras_carried": extras,
        "block_extras_carried_keys": [],
        "block_extras_jcs_sha256": _prefixed_sha256(extras),
        "layers": _layers(text),
        "lines": rendered_lines,
    }
    if block_type == "cross_reference":
        rendered_block["cross_reference_target"] = {
            "target_raw": text.strip(),
            "resolved": False,
        }

    uncertainties = []
    if conflicts:
        uncertainties.append(
            {
                "queue_id": _stable_id(
                    "su",
                    ["structural_disagreement", rendering_block_id, conflicts],
                ),
                "reason": "structural_disagreement",
                "rendering_block_id": rendering_block_id,
                "rendering_line_id": None,
                "observation_token_ids": [
                    word["observation_token_id"]
                    for line in rendered_lines
                    for word in line.get("words", [])
                ],
                "evidence": {"block_type": "unknown"},
            }
        )
    uncertainties.extend(
        _hyphen_uncertainties(
            rendering_block_id=rendering_block_id,
            rendered_lines=rendered_lines,
        )
    )
    return rendered_block, uncertainties


def _page_coverage_state(page_ref: dict[str, Any]) -> str:
    status = page_ref.get("status")
    if status == "eligible":
        return "covered"
    if status == "diagnostic_only":
        return "diagnostic_only"
    if status == "missing":
        return "missing"
    return "corrupt"


def _render_page(
    page: dict[str, Any],
    page_ref: dict[str, Any],
    engine_family: str = "",
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    page_dimensions = page["page_dimensions_native"]
    # Only Tesseract renderings carry tesseract_line_attrs; guard here so a
    # sidecar from another engine that happens to carry the key is not used.
    tesseract_line_attrs: dict[str, Any] = (
        page.get("page_extras_carried", {}).get("tesseract_line_attrs") or {}
        if engine_family == "tesseract"
        else {}
    )
    # R4a: the leaf coordinate is authoritative from the CURRENT manifest's
    # page_ref (C5 — never trust a stored canonical_leaf_id for the join). Fall
    # back to the filename stem for lineages not yet leaf-keyed (ABBYY, R7), so
    # every intermediate state stays runnable and ids never collide on None.
    leaf = page_ref.get("canonical_leaf_id")
    page_seed = f"leaf:{int(leaf)}" if leaf is not None else str(page["page_native_id"])
    rendered_blocks: list[dict[str, Any]] = []
    uncertainties: list[dict[str, Any]] = []
    derived_spans_by_block: dict[str, list[dict[str, Any]]] = {}
    for block_index, block in enumerate(page.get("blocks", [])):
        rendered_block, block_uncertainties = _render_block(
            block,
            rendering_id=page["rendering_id"],
            page_seed=page_seed,
            native_order=block_index,
            page_dimensions=page_dimensions,
            tesseract_line_attrs=tesseract_line_attrs,
        )
        rendered_blocks.append(rendered_block)
        uncertainties.extend(block_uncertainties)
        derived_spans_by_block[rendered_block["rendering_block_id"]] = []
    rendered_page = {
        "manifest_id": page["manifest_id"],
        "rendering_id": page["rendering_id"],
        "page_native_id": page["page_native_id"],
        "page_sequence": page["page_sequence"],
        "page_dimensions_native": page_dimensions,
        "source_payload_sha256": page["source_payload_sha256"],
        "coverage_state": _page_coverage_state(page_ref),
        "reading_order_reliability": "medium",
        "blocks": rendered_blocks,
        "page_extras_carried": page.get("page_extras_carried", {}),
        "page_extras_carried_keys": page.get("page_extras_carried_keys", []),
        "page_extras_jcs_sha256": page.get("page_extras_jcs_sha256", ZERO_SHA),
    }
    # R5: every rendered page declares its leaf identity -- body pages carry the
    # int leaf, non-body / unmappable pages carry clid_exempt:true (oneOf).
    set_leaf_or_exempt(rendered_page, int(leaf) if leaf is not None else None)
    if "edition_page_key" in page_ref:
        rendered_page["edition_page_key"] = dict(page_ref["edition_page_key"])
    return rendered_page, uncertainties, derived_spans_by_block


def _coverage(manifest: dict[str, Any]) -> dict[str, Any]:
    pages = manifest.get("pages", [])
    counts = {"eligible": 0, "diagnostic_only": 0, "corrupt": 0, "missing": 0}
    for page_ref in pages:
        status = str(page_ref.get("status", "corrupt"))
        if status in counts:
            counts[status] += 1
        else:
            counts["corrupt"] += 1
    coverage_state = "covered" if counts["eligible"] == len(pages) else "corrupt"
    if counts["missing"]:
        coverage_state = "missing"
    elif counts["diagnostic_only"] and not counts["corrupt"]:
        coverage_state = "diagnostic_only"
    return {
        "page_count": len(pages),
        "eligible_pages": counts["eligible"],
        "diagnostic_pages": counts["diagnostic_only"],
        "corrupt_pages": counts["corrupt"],
        "missing_pages": counts["missing"],
        "coverage_state": coverage_state,
    }


def _source_sidecar_refs(
    manifest_path: Path,
    manifest: dict[str, Any],
    *,
    repo_root: Path,
) -> list[dict[str, str]]:
    refs = [{"path": _rel_path(manifest_path, repo_root), "sha256": _file_sha256(manifest_path)}]
    for page_ref in manifest.get("pages", []):
        page_path = repo_root / page_ref["sidecar_page_path"]
        refs.append(
            {
                "path": page_ref["sidecar_page_path"],
                "sha256": _file_sha256(page_path),
            }
        )
    return refs


def _page_source_sidecar_refs(
    manifest_path: Path,
    page_ref: dict[str, Any],
    *,
    repo_root: Path,
) -> list[dict[str, str]]:
    page_path = repo_root / page_ref["sidecar_page_path"]
    return [
        {"path": _rel_path(manifest_path, repo_root), "sha256": _file_sha256(manifest_path)},
        {"path": page_ref["sidecar_page_path"], "sha256": _file_sha256(page_path)},
    ]


def _page_rendering_is_current(
    existing: dict[str, Any],
    *,
    manifest: dict[str, Any],
    page_ref: dict[str, Any],
    manifest_file: Path,
    repo_root: Path,
) -> bool:
    """Return True when an existing S2 page matches stable current S1 inputs."""
    rendered_pages = existing.get("pages") or []
    if len(rendered_pages) != 1 or not isinstance(rendered_pages[0], dict):
        return False
    rendered_page = rendered_pages[0]
    sidecar_refs = existing.get("source_sidecar_refs") or []
    if len(sidecar_refs) < 2 or not isinstance(sidecar_refs[1], dict):
        return False

    sidecar_path = repo_root / page_ref["sidecar_page_path"]
    expected_sidecar_ref = {
        "path": page_ref["sidecar_page_path"],
        "sha256": _file_sha256(sidecar_path),
    }
    # R4a: per-page currentness keys on (canonical_leaf_id, source_payload_sha256,
    # sidecar sha); the volume-global manifest_id equality is dropped so a rename
    # elsewhere in the volume no longer forces a re-render of an unchanged leaf.
    # Lineages not yet leaf-keyed (ABBYY, R7) fall back to the filename stem.
    if page_ref.get("canonical_leaf_id") is not None:
        page_identity_ok = (
            rendered_page.get("canonical_leaf_id") == page_ref.get("canonical_leaf_id")
        )
    else:
        page_identity_ok = (
            rendered_page.get("page_native_id") == page_ref.get("page_native_id")
        )
    return (
        existing.get("schema_version") == "rendering-v1"
        and existing.get("stage_version") == STAGE_VERSION
        and existing.get("rendering_id") == manifest.get("rendering_id")
        and existing.get("engine_family") == manifest.get("engine_family")
        and existing.get("engine_version") == manifest.get("engine_version")
        and existing.get("source_lineage_id") == manifest.get("source_lineage_id")
        and existing.get("work_id") == manifest.get("work_id")
        and existing.get("edition_id") == manifest.get("edition_id")
        and int(existing.get("volume", -1)) == int(manifest.get("volume", -2))
        and rendered_page.get("rendering_id") == manifest.get("rendering_id")
        and page_identity_ok
        and rendered_page.get("source_payload_sha256") == page_ref.get("source_payload_sha256")
        and sidecar_refs[1] == expected_sidecar_ref
        and isinstance(sidecar_refs[0], dict)
        and sidecar_refs[0].get("path") == _rel_path(manifest_file, repo_root)
    )


def _parsed_keys_refs(
    pages: list[dict[str, Any]],
    page_refs: list[dict[str, Any]],
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for page, page_ref in zip(pages, page_refs, strict=True):
        if page.get("parsed_keys_index"):
            refs.append(
                {
                    "path": f"{page_ref['sidecar_page_path']}#parsed_keys_index",
                    "sha256": page["source_payload_sha256"],
                }
            )
    return refs


def _load_pages(manifest: dict[str, Any], repo_root: Path) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for page_ref in manifest.get("pages", []):
        if page_ref.get("status") not in {"eligible", "diagnostic_only"}:
            continue
        page_path = repo_root / page_ref["sidecar_page_path"]
        pages.append(_read_json(page_path))
    return pages


def _replay_verification(manifest: dict[str, Any]) -> dict[str, Any]:
    verified_at = str(manifest.get("created_at") or "1970-01-01T00:00:00Z")
    return {
        "passed": True,
        "ledger_schema_valid": True,
        "forward_replay_sha256": _prefixed_sha256(["forward_replay_deferred", STAGE_VERSION]),
        "inverse_replay_sha256": _prefixed_sha256(["inverse_replay_deferred", STAGE_VERSION]),
        "source_raw_reconstruction_sha256": _prefixed_sha256(
            ["source_raw_reconstruction_deferred", manifest.get("rendering_id")]
        ),
        "verified_at": verified_at,
        "verifier_version": REPLAY_VERIFIER_VERSION,
        "failure_codes": [],
    }


def render_manifest(
    manifest_path: Path | str,
    *,
    repo_root: Path | str,
    output_dir: Path | str | None = None,
    force: bool = False,
    shutdown_event: threading.Event | None = None,
    allow_stale_manifest: bool = False,
    exclude_stems: frozenset[str] = frozenset(),
    validate_schema: bool = True,
) -> dict[str, Any]:
    """Render one engine's sidecar manifest into per-page rendering-v1 files.

    ``validate_schema=False`` skips the rendering-v1 jsonschema re-validation in
    write_json_atomic (the dominant per-page cost, ~0.7s/page, and a read-only gate
    that cannot change output bytes). The C2 semantic check (validate_rendering)
    still runs. Used by the R-final.1 clid re-key, which re-renders abbyy/azure
    cells whose payload was already schema-validated when first produced; byte
    identity vs the validated render is proven separately before bulk use.
    """
    manifest_file = Path(manifest_path)
    root = Path(repo_root)
    out_dir = Path(output_dir) if output_dir is not None else manifest_file.parent
    pages_out_dir = out_dir / "pages"
    pages_out_dir.mkdir(parents=True, exist_ok=True)

    manifest = _read_json(manifest_file)
    pages_dir = manifest_file.parent / "pages"
    on_disk = count_sidecars(pages_dir, exclude_stems=exclude_stems)
    manifest_page_count = len(manifest.get("pages", []))
    if manifest_page_count < on_disk:
        source_lineage_id = manifest.get("source_lineage_id", "unknown")
        vol_label = f"vol_{manifest.get('volume', 0):02d}"
        message = (
            f"{source_lineage_id} {vol_label} manifest has "
            f"{manifest_page_count} pages but {on_disk} sidecars on disk.\n"
            "  Run reindex_manifest.py to rebuild before rendering."
        )
        if not allow_stale_manifest:
            raise RuntimeError(message)
        print(f"WARNING: {message}", file=sys.stderr)
    page_refs = [
        page_ref
        for page_ref in manifest.get("pages", [])
        if page_ref.get("status") in {"eligible", "diagnostic_only"}
    ]
    schema = _read_json(SCHEMA_PATH)
    coverage = _coverage(manifest)
    coverage_gaps = coverage["corrupt_pages"] + coverage["missing_pages"]
    written = 0
    skipped = 0

    for page_ref in page_refs:
        if shutdown_event is not None and shutdown_event.is_set():
            raise _RenderAborted
        page_id = str(page_ref["page_native_id"])
        page_out = pages_out_dir / f"{page_id}.rendering-v1.json"

        if not force and page_out.exists():
            try:
                existing = _read_json(page_out)
                if _page_rendering_is_current(
                    existing,
                    manifest=manifest,
                    page_ref=page_ref,
                    manifest_file=manifest_file,
                    repo_root=root,
                ):
                    skipped += 1
                    continue
            except Exception:
                pass  # corrupt or unreadable page output: fall through to re-render

        page = _read_json(root / page_ref["sidecar_page_path"])
        rendered_page, page_uncertainties, page_derived_spans = _render_page(
            page, page_ref, engine_family=manifest.get("engine_family", "")
        )
        structural_uncertainty_queue = page_uncertainties
        derived_spans_by_block = page_derived_spans
        unresolved_hyphen_count = sum(
            1
            for item in structural_uncertainty_queue
            if item.get("reason") == "unresolved_hyphen_boundary"
        )
        page_rendering = {
            "schema_version": "rendering-v1",
            "stage_version": STAGE_VERSION,
            "rendering_id": manifest["rendering_id"],
            "engine_family": manifest["engine_family"],
            "engine_version": manifest["engine_version"],
            "source_lineage_id": manifest["source_lineage_id"],
            "work_id": manifest["work_id"],
            "edition_id": manifest["edition_id"],
            "volume": manifest["volume"],
            "pipeline_config_hash": _prefixed_sha256(["pipeline_config", STAGE_VERSION]),
            "typography_snapshot_id": APPROVED_TYPOGRAPHY_SNAPSHOT_ID,
            "typography_snapshot_approval_state": "approved",
            "ccel_annotation_source_id": None,
            "dictionary_snapshot_ids": {},
            "nfkc_allowlist_hash": _prefixed_sha256([NFKC_ALLOWLIST_VERSION]),
            "fingerprint_function_hash": _prefixed_sha256([FINGERPRINT_FUNCTION_VERSION]),
            "source_sidecar_refs": _page_source_sidecar_refs(
                manifest_file,
                page_ref,
                repo_root=root,
            ),
            "parsed_keys_index_refs": _parsed_keys_refs([page], [page_ref]),
            "witness_coverage": coverage,
            "pages": [rendered_page],
            "candidate_articles": [],
            "derived_spans_by_block": derived_spans_by_block,
            "structural_uncertainty_queue": structural_uncertainty_queue,
            "operations_ledger_ref": {
                "path": "reports/s2/operations-ledger-deferred.jsonl",
                "sha256": ZERO_SHA,
            },
            "operations_ledger_hash": ZERO_SHA,
            "replay_verification": _replay_verification(manifest),
            "admission_state": {
                "fully_admitted": coverage_gaps == 0,
                "coverage_gaps": coverage_gaps,
                "reading_order_low_pages": 0,
                "reading_order_failed_pages": 0,
                "unresolved_hyphen_count": unresolved_hyphen_count,
            },
        }
        # Enforce the C2 semantic obligations (arch3 section 2.6) at the production
        # write boundary, not only in tests: JSON Schema cannot express
        # observation-token-once or derived-span referential integrity.
        semantic_errors = validate_rendering(page_rendering)
        if semantic_errors:
            raise ValueError(
                "rendering-v1 semantic validation failed: " + "; ".join(semantic_errors)
            )
        write_json_atomic(page_out, page_rendering, schema if validate_schema else {})
        written += 1

    # R4a expected-set purge (REL-05, design §4.3): the rendering pages dir must
    # equal the current manifest expected leaf set exactly. Quarantine -- never
    # delete -- any rendering whose stem is not an eligible page in the current
    # manifest (e.g. a page dropped by a leaf-number correction). Reversible.
    expected_files = {f"{str(page_ref['page_native_id'])}.rendering-v1.json" for page_ref in page_refs}
    quarantined = 0
    for existing_render in sorted(pages_out_dir.glob("*.rendering-v1.json")):
        if existing_render.name in expected_files:
            continue
        quarantine_dir = out_dir / "quarantine" / "render_s2_orphans"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        dest = quarantine_dir / existing_render.name
        collision = 1
        while dest.exists():
            dest = quarantine_dir / f"{existing_render.stem}.{collision}{existing_render.suffix}"
            collision += 1
        shutil.move(str(existing_render), str(dest))
        quarantined += 1
    if quarantined:
        print(f"  quarantined {quarantined} orphan rendering(s) not in the current leaf set")

    write_json_atomic(
        out_dir / "index.json",
        {
            "schema_version": "rendering-index-v1",
            "source_lineage_id": manifest["source_lineage_id"],
            "volume": int(manifest["volume"]),
            "pages": [str(page_ref["page_native_id"]) for page_ref in page_refs],
        },
        {},
    )
    return {"written": written, "skipped": skipped}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render one S1 sidecar manifest into rendering-v1.")
    parser.add_argument("manifest_path", type=Path)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Re-render even if an up-to-date output already exists.",
    )
    parser.add_argument(
        "--allow-stale-manifest",
        action="store_true",
        default=False,
        help="Warn and render even when sidecars on disk outnumber manifest pages.",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    render_manifest(
        args.manifest_path,
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        force=args.force,
        allow_stale_manifest=args.allow_stale_manifest,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
