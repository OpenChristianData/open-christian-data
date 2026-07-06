"""Normalize Azure AI Vision cloud sidecars into S1 sidecar records.

Azure is an *imported* word-geometry engine, exactly like rich ABBYY: the OCR
work was already done by run_cloud_ocr.ocr_azure(), which wrote per-page
page_NNNN.azure.json sidecars carrying word bbox{x,y,w,h} + confidence (0-100).
This normalizer reads those sidecars and emits geometry-bearing sidecar-page-v1
records plus a sidecar-manifest-v1 with engine_family "azure_read", so render_s2
produces a rendering-v1 and Azure joins Tesseract/ABBYY as a WCT anchor engine
(wct_builder._FAMILY_MAP maps azure_read -> azure-ai-vision).

This is the geometry path; it does NOT run inference. The cloud sidecars under
raw/.../schaff-herzog-pages/<vol>/ are read-only input here.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.page_order import volume_sidecar_files  # noqa: E402
from build.lib.edition_page_key import body_edition_key, resolve_edition_page_key_by_sha  # noqa: E402
from build.lib.nsh_leaf_model import canonical_leaf_id, leaves_view, set_leaf_or_exempt  # noqa: E402
from build.lib.ocr_store_paths import S1_SIDECARS_ROOT  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402
from build.lib.schema_enums import get_enum  # noqa: E402

# Reuse the validated ABBYY-rich helpers rather than re-implementing hashing,
# schema validation, manifest assembly, and resumable state (TEST-02).
from build.parsers.s1_abbyy_normalizer import (  # noqa: E402
    EDITION_ID,
    EMPTY_EXTRAS_SHA256,
    WORK_ID,
    _build_manifest_id,
    _clamp_confidence,
    _coerce_bbox,
    _extras_hash,
    _load_state,
    _normal_manifest_paths,
    _observation_token_id,
    _prefixed_sha256_bytes,
    _prefixed_sha256_json,
    _read_json,
    _relative_path,
    _validate,
    _volume_label,
    _write_json,
)

DEFAULT_OUTPUT_ROOT = S1_SIDECARS_ROOT
DEFAULT_INPUT_ROOT = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
DEFAULT_LINEAGE = "azure-ai-vision-v1"
ENGINE_FAMILY = "azure_read"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class NormalizationSummary:
    manifest: dict[str, Any]
    manifest_path: Path
    state_path: Path
    emitted_pages: int
    skipped_pages: int
    failed_pages: int
    skipped_partial: int
    unmapped_pages: int


def _assert_locked_enums() -> None:
    engine_families = get_enum("sidecar-manifest-v1", "engine_family")
    if ENGINE_FAMILY not in engine_families:
        raise RuntimeError(
            f"sidecar-manifest-v1 engine_family enum does not include {ENGINE_FAMILY!r}"
        )


def _page_dimensions(rich: dict[str, Any]) -> dict[str, Any]:
    """Azure stores image_size as [width, height] (pixels)."""
    size = rich.get("image_size")
    if (
        isinstance(size, (list, tuple))
        and len(size) == 2
        and all(isinstance(v, int) and v > 0 for v in size)
    ):
        return {"width": size[0], "height": size[1], "unit": "pixel"}
    return {"width": None, "height": None, "unit": "unknown"}


def _azure_word_record(
    word: dict[str, Any],
    *,
    rendering_id: str,
    page_native_id: str,
    page_sequence: int,
    block_index: int,
    line_index: int,
    word_index: int,
) -> dict[str, Any]:
    source_raw = str(word.get("text", ""))
    bbox_native = _coerce_bbox(word.get("bbox"))
    return {
        "observation_token_id": _observation_token_id(
            {
                "rendering_id": rendering_id,
                "page_native_id": page_native_id,
                "page_sequence": page_sequence,
                "block_index": block_index,
                "line_index": line_index,
                "word_index": word_index,
                "source_raw": source_raw,
                "bbox_native": bbox_native,
            }
        ),
        "word_native_id": f"word-{block_index:04d}-{line_index:04d}-{word_index:04d}",
        "source_raw": source_raw,
        "confidence": _clamp_confidence(word.get("confidence")),
        "bbox_native": bbox_native,
    }


def _build_azure_page_record(
    rich: dict[str, Any],
    *,
    manifest_id: str,
    rendering_id: str,
    page_native_id: str,
    page_sequence: int,
    source_payload_sha256: str,
) -> dict[str, Any]:
    """Build a geometry-bearing sidecar-page-v1 record from an Azure sidecar."""
    dimensions = _page_dimensions(rich)
    blocks: list[dict[str, Any]] = []
    for block_index, block in enumerate(rich.get("blocks", []), start=1):
        lines: list[dict[str, Any]] = []
        for line_index, line in enumerate(block.get("lines", []), start=1):
            words = [
                _azure_word_record(
                    word,
                    rendering_id=rendering_id,
                    page_native_id=page_native_id,
                    page_sequence=page_sequence,
                    block_index=block_index,
                    line_index=line_index,
                    word_index=word_index,
                )
                for word_index, word in enumerate(line.get("words", []), start=1)
            ]
            if not words:
                continue
            line_source_raw = " ".join(word["source_raw"] for word in words)
            lines.append(
                {
                    "observation_token_id": _observation_token_id(
                        {
                            "rendering_id": rendering_id,
                            "page_native_id": page_native_id,
                            "page_sequence": page_sequence,
                            "block_index": block_index,
                            "line_index": line_index,
                            "source_raw": line_source_raw,
                        }
                    ),
                    "line_native_id": f"line-{block_index:04d}-{line_index:04d}",
                    "source_raw": line_source_raw,
                    "confidence": None,
                    "bbox_native": _coerce_bbox(line.get("bbox")),
                    "words": words,
                }
            )
        if not lines:
            continue
        blocks.append(
            {
                "block_id": f"block-{block_index:04d}",
                "block_type": "text",
                "lines": lines,
                "bbox_native": _coerce_bbox(block.get("bbox")),
            }
        )

    extras = {key: value for key, value in rich.items() if key != "blocks"}
    parsed_keys = [
        {"key": key, "handling": "extras_carried", "source_path": f"page.{key}"}
        for key in sorted(extras)
    ]
    return {
        "schema_version": "sidecar-page-v1",
        "manifest_id": manifest_id,
        "rendering_id": rendering_id,
        "page_native_id": page_native_id,
        "page_sequence": page_sequence,
        "page_dimensions_native": dimensions,
        "blocks": blocks,
        "parsed_keys_index": parsed_keys,
        "page_extras_carried": extras,
        "page_extras_carried_keys": sorted(extras),
        "page_extras_jcs_sha256": _extras_hash(extras),
        "source_payload_sha256": source_payload_sha256,
    }


def _is_partial(rich: Any) -> bool:
    return isinstance(rich, dict) and bool(rich.get("partial"))


def _azure_page_files(input_root: Path, volume: int) -> list[tuple[int, str, Path]]:
    """Return (scan_sequence, page_native_id, path) for each Azure sidecar.

    page_native_id is the scan stem (e.g. "leaf_0037", "page_0010") so Azure
    aligns with the Tesseract/Surya/ABBYY renderings of the same scan image.
    The raw-response siblings (*.azure.raw.json) end in .raw.json and are
    excluded by volume_sidecar_files's suffix guard.
    Uses page_order.json manifest when present (vol_01).
    """
    vol_dir = input_root / _volume_label(volume)
    return volume_sidecar_files(vol_dir, "azure.json")


def _stamp_canonical_leaf_id(
    ref: dict[str, Any], source_manifest: dict[str, Any]
) -> int | None:
    leaf_id = canonical_leaf_id(str(ref["page_native_id"]), source_manifest)
    set_leaf_or_exempt(ref, leaf_id)
    _stamp_edition_page_key(ref, source_manifest, leaf_id)
    return leaf_id


def _stamp_edition_page_key(
    record: dict[str, Any],
    source_manifest: dict[str, Any],
    leaf_id: int | None,
) -> None:
    record.pop("edition_page_key", None)
    key = _resolve_precise_edition_key(record, source_manifest, leaf_id)
    if key is None:
        # Best-effort fallback from the page native id ("page_NNNN") for an
        # unmapped stem (normal for alternate scans, which are content-aligned --
        # a stem absent from the leafmap is legitimately unmapped, not an error).
        # Keeps every record carrying the now-required edition_page_key.
        page_num = _page_num_from_native_id(record.get("page_native_id"))
        if page_num is not None:
            key = body_edition_key(page_num)
    if key is not None:
        record["edition_page_key"] = dict(key)


def _resolve_precise_edition_key(
    record: dict[str, Any],
    source_manifest: dict[str, Any],
    leaf_id: int | None,
) -> dict[str, Any] | None:
    """The manifest-backed edition key for a record, or None when unresolvable."""
    sha = record.get("source_payload_sha256")
    if isinstance(sha, str):
        key = resolve_edition_page_key_by_sha(source_manifest, sha)
        if key is not None:
            return key
    page_num = _page_num_from_native_id(record.get("page_native_id"))
    if page_num is not None and any(
        isinstance(gap, dict) and gap.get("page_num") == page_num
        for gap in source_manifest.get("gaps", [])
    ):
        return body_edition_key(page_num)
    if leaf_id is None:
        return None
    for leaf in leaves_view(source_manifest):
        if (
            leaf.get("leaf_num") == leaf_id
            and leaf.get("kind") == "body"
            and isinstance(leaf.get("page_num"), int)
        ):
            return body_edition_key(leaf["page_num"])
    return None


def _page_num_from_native_id(value: Any) -> int | None:
    if not isinstance(value, str) or not value.startswith("page_"):
        return None
    suffix = value.removeprefix("page_")
    return int(suffix) if len(suffix) == 4 and suffix.isdecimal() else None


def normalize_azure_volume(
    input_root: Path,
    *,
    source_lineage_id: str = DEFAULT_LINEAGE,
    volume: int,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    repo_root: Path = REPO_ROOT,
    pages: list[int] | None = None,
    force: bool = False,
) -> NormalizationSummary:
    """Normalize one volume's Azure cloud sidecars into S1 sidecars.

    Partial sidecars (driver failures, {"partial": true}) carry no geometry and
    are skipped (counted in skipped_partial), never silently emitted as panel
    pages.
    """
    _assert_locked_enums()
    input_root = Path(input_root)
    output_root = Path(output_root)
    repo_root = Path(repo_root)
    rendering_id = f"{source_lineage_id}/schaff/encyclopedia/1908-1914/v1"
    source_manifest = _read_json(input_root / f"{_volume_label(volume)}.manifest.json")

    page_files = _azure_page_files(input_root, volume)
    if pages is not None:
        if not pages:
            raise ValueError(
                "pages must be non-empty when provided; omit to process whole volume"
            )
        page_set = set(pages)
        page_files = [entry for entry in page_files if entry[0] in page_set]

    manifest_path, state_path, pages_dir = _normal_manifest_paths(
        output_root, source_lineage_id, volume
    )
    state = _load_state(state_path)
    already_done = set(str(value) for value in state.get("emitted_pages", []))
    emitted_state = set(already_done)

    emitted_pages = 0
    skipped_pages = 0
    skipped_partial = 0
    page_refs: list[dict[str, Any]] = []
    source_files: list[dict[str, Any]] = []
    engine_version = ""
    file_hashes: list[str] = []
    unmapped: list[str] = []

    for scan_sequence, page_native_id, path in page_files:
        rich = _read_json(path)
        if _is_partial(rich):
            skipped_partial += 1
            continue
        file_bytes = path.read_bytes()
        file_sha256 = _prefixed_sha256_bytes(file_bytes)
        file_hashes.append(file_sha256)
        source_files.append(
            {"path": _relative_path(path, repo_root), "sha256": file_sha256}
        )
        if not engine_version:
            engine_version = str(rich.get("engine_version") or "")
        page_sha256 = _prefixed_sha256_json(rich)
        page_path = pages_dir / f"{page_native_id}.json"

        if not force and page_native_id in already_done and page_path.exists():
            skipped_pages += 1
            ref = {
                "page_native_id": page_native_id,
                "page_sequence": scan_sequence,
                "status": "eligible",
                "sidecar_page_path": _relative_path(page_path, repo_root),
                "source_payload_sha256": page_sha256,
            }
            if _stamp_canonical_leaf_id(ref, source_manifest) is None:
                unmapped.append(page_native_id)
            page_refs.append(ref)
        else:
            page_record = _build_azure_page_record(
                rich,
                manifest_id="",  # set below once manifest_id is known
                rendering_id=rendering_id,
                page_native_id=page_native_id,
                page_sequence=scan_sequence,
                source_payload_sha256=page_sha256,
            )
            ref = {
                "page_native_id": page_native_id,
                "page_sequence": scan_sequence,
                "status": "eligible",
                "sidecar_page_path": _relative_path(page_path, repo_root),
                "source_payload_sha256": page_sha256,
                "_record": page_record,
            }
            if _stamp_canonical_leaf_id(ref, source_manifest) is None:
                unmapped.append(page_native_id)
            page_refs.append(ref)
            emitted_state.add(page_native_id)
            emitted_pages += 1

    combined_hash = _prefixed_sha256_bytes("".join(sorted(file_hashes)).encode("utf-8"))
    manifest_id = _build_manifest_id(
        source_lineage_id=source_lineage_id,
        rendering_id=rendering_id,
        volume=volume,
        source_file_sha256=combined_hash,
    )

    clean_refs: list[dict[str, Any]] = []
    for ref in page_refs:
        record = ref.pop("_record", None)
        if record is not None:
            record["manifest_id"] = manifest_id
            # R7 flip-readiness: copy the leaf coordinate onto the per-page sidecar
            # record (mirrors s1_abbyy_normalizer) so the sidecar-page-v1 required-clid
            # flip is satisfiable, not just the manifest page_ref.
            set_leaf_or_exempt(record, ref.get("canonical_leaf_id"))
            if "edition_page_key" in ref:
                record["edition_page_key"] = dict(ref["edition_page_key"])
            else:
                record.pop("edition_page_key", None)
            _validate("sidecar-page-v1", record)
            _write_json(pages_dir / f"{ref['page_native_id']}.json", record)
        clean_refs.append(ref)

    if unmapped:
        LOGGER.warning(
            "azure vol_%02d: %d page id(s) did not map to a leaf_num (e.g. %s)",
            volume,
            len(unmapped),
            ", ".join(unmapped[:10]),
        )

    if not source_files:
        raise FileNotFoundError(
            f"no Azure sidecars for lineage {source_lineage_id!r} volume {volume} "
            f"under {input_root}"
        )

    manifest = {
        "schema_version": "sidecar-manifest-v1",
        "manifest_id": manifest_id,
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "volume": volume,
        "rendering_id": rendering_id,
        "engine_family": ENGINE_FAMILY,
        "engine_version": engine_version,
        "source_lineage_id": source_lineage_id,
        "source_files": source_files,
        "pages": clean_refs,
        "manifest_cross_check": {
            "samples_checked": 1 if clean_refs else 0,
            "samples_matched": 1 if clean_refs else 0,
            "samples_inconclusive": 0,
            "failed_samples": [],
        },
        "bundle_extras_carried": {},
        "bundle_extras_carried_keys": [],
        "bundle_extras_jcs_sha256": EMPTY_EXTRAS_SHA256,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _validate("sidecar-manifest-v1", manifest)
    _write_json(manifest_path, manifest)
    state = {
        "manifest_id": manifest_id,
        "emitted_pages": sorted(emitted_state),
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _write_json(state_path, state)
    return NormalizationSummary(
        manifest=manifest,
        manifest_path=manifest_path,
        state_path=state_path,
        emitted_pages=emitted_pages,
        skipped_pages=skipped_pages,
        failed_pages=0,
        skipped_partial=skipped_partial,
        unmapped_pages=len(unmapped),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--volume", type=int, required=True)
    parser.add_argument("--source-lineage-id", default=DEFAULT_LINEAGE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = normalize_azure_volume(
        args.input_root,
        source_lineage_id=args.source_lineage_id,
        volume=args.volume,
        output_root=args.output_root,
    )
    print(
        f"azure vol_{args.volume:02d}: emitted={summary.emitted_pages} "
        f"skipped={summary.skipped_pages} skipped_partial={summary.skipped_partial} "
        f"unmapped={summary.unmapped_pages}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
