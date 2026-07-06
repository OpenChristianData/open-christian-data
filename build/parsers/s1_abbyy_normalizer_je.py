"""S1 ABBYY normalizer for the Jewish Encyclopedia (Vol 2, cu31924091768196).

Streams cu31924091768196_abbyy.gz, uses the JE page manifest for leaf->page
mapping, and emits sidecar-page-v1 records compatible with render_s2.

Non-circularity: IA ABBYY GZ is an engine input, never the reference. The
reference is human JE.com transcription only.

Usage:
  py -3 build/parsers/s1_abbyy_normalizer_je.py \\
      --gz raw/jewish-encyclopedia/ia-abbyy/cu31924091768196_abbyy.gz \\
      --manifest raw/jewish-encyclopedia/ia-pages/vol_02.manifest.json \\
      --output-dir reports/je-s1-sidecars/ia-abbyy-v1/vol_02
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from lxml import etree

_BOOTSTRAP = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP))

from build.parsers.ia_abbyy import _q, parse_page  # noqa: E402
from build.parsers.s1_abbyy_normalizer import (  # noqa: E402
    EMPTY_EXTRAS_SHA256,
    _observation_token_id,
    _prefixed_sha256_json,
)
from build.lib.edition_page_key import body_edition_key  # noqa: E402
from build.lib.nsh_leaf_model import set_leaf_or_exempt  # noqa: E402

logger = logging.getLogger("s1_abbyy_normalizer_je")

WORK_ID = "jewish-encyclopedia.vol_02"
EDITION_ID = "1901-1906"
ENGINE_FAMILY = "abbyy"
ENGINE_ALIAS = "ia-abbyy-v1"
RENDERING_ID = "ia-abbyy/jewish-encyclopedia/1901-1906/v1"
SOURCE_LINEAGE_ID = "ia-abbyy-v1"

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Sidecar conversion
# ---------------------------------------------------------------------------

def _convert_word(
    word: dict[str, Any],
    *,
    rendering_id: str,
    page_native_id: str,
    block_index: int,
    line_index: int,
    word_index: int,
) -> dict[str, Any]:
    """Convert ia_abbyy word dict to S1 sidecar word format."""
    source_raw = word.get("text", "")
    bbox = word.get("bbox")
    ot_seed = {
        "rendering_id": rendering_id,
        "page_native_id": page_native_id,
        "block_index": block_index,
        "line_index": line_index,
        "word_index": word_index,
        "source_raw": source_raw,
    }
    return {
        "observation_token_id": _observation_token_id(ot_seed),
        "word_native_id": f"wd-{block_index}-{line_index}-{word_index}",
        "source_raw": source_raw,
        "confidence": word.get("confidence"),
        "bbox_native": bbox,
    }


def _convert_line(
    line: dict[str, Any],
    *,
    rendering_id: str,
    page_native_id: str,
    block_index: int,
    line_index: int,
) -> dict[str, Any]:
    """Convert ia_abbyy line dict to S1 sidecar line format."""
    words = [
        _convert_word(
            w,
            rendering_id=rendering_id,
            page_native_id=page_native_id,
            block_index=block_index,
            line_index=line_index,
            word_index=wi,
        )
        for wi, w in enumerate(line.get("words", []))
    ]
    source_raw = " ".join(w["source_raw"] for w in words)
    confidences = [w["confidence"] for w in words if isinstance(w.get("confidence"), (int, float))]
    confidence = sum(confidences) / len(confidences) if confidences else None
    ot_seed = {
        "rendering_id": rendering_id,
        "page_native_id": page_native_id,
        "block_index": block_index,
        "line_index": line_index,
        "source_raw": source_raw,
    }
    return {
        "observation_token_id": _observation_token_id(ot_seed),
        "line_native_id": f"ln-{block_index}-{line_index}",
        "source_raw": source_raw,
        "confidence": confidence,
        "bbox_native": line.get("bbox"),
        "words": words,
    }


def _convert_block(
    block: dict[str, Any],
    *,
    rendering_id: str,
    page_native_id: str,
    block_index: int,
) -> dict[str, Any]:
    """Convert ia_abbyy block dict to S1 sidecar block format."""
    lines = [
        _convert_line(
            ln,
            rendering_id=rendering_id,
            page_native_id=page_native_id,
            block_index=block_index,
            line_index=li,
        )
        for li, ln in enumerate(block.get("lines", []))
    ]
    return {
        "block_id": f"blk-{block_index}",
        "block_type": "text" if block.get("block_type", "Text") == "Text" else block.get("block_type", "text"),
        "bbox_native": block.get("bbox"),
        "lines": lines,
    }


def ia_abbyy_page_to_s1_sidecar(
    abbyy_page: dict[str, Any],
    *,
    page_sequence: int,
    manifest_id: str,
    rendering_id: str = RENDERING_ID,
) -> dict[str, Any]:
    """Convert an ia_abbyy.parse_page() dict to sidecar-page-v1 format.

    The key transforms:
    - word.text -> word.source_raw
    - word.bbox -> word.bbox_native (kept in place)
    - block.bbox -> block.bbox_native
    - line.bbox -> line.bbox_native
    - add word.observation_token_id
    - add line.line_native_id and line.source_raw
    - add block.block_id
    - page_size -> page_dimensions_native
    - wrap in sidecar-page-v1 envelope
    """
    page_num = abbyy_page["page_num"]
    page_native_id = f"page_{page_num:04d}"
    page_size = abbyy_page.get("page_size") or {}
    page_dimensions = {
        "width": page_size.get("width"),
        "height": page_size.get("height"),
        "unit": "pixel",
    }
    blocks = [
        _convert_block(
            b,
            rendering_id=rendering_id,
            page_native_id=page_native_id,
            block_index=bi,
        )
        for bi, b in enumerate(abbyy_page.get("blocks", []))
    ]
    source_payload_sha256 = _prefixed_sha256_json(abbyy_page)
    record = {
        "schema_version": "sidecar-page-v1",
        "manifest_id": manifest_id,
        "rendering_id": rendering_id,
        "page_native_id": page_native_id,
        "page_sequence": page_sequence,
        "page_dimensions_native": page_dimensions,
        "blocks": blocks,
        "parsed_keys_index": [],
        "page_extras_carried": {},
        "page_extras_carried_keys": [],
        "page_extras_jcs_sha256": EMPTY_EXTRAS_SHA256,
        "source_payload_sha256": source_payload_sha256,
    }
    set_leaf_or_exempt(record, None)
    record["edition_page_key"] = body_edition_key(page_num)
    return record


def _stamp_je_page_ref(ref: dict[str, Any], page_num: int) -> dict[str, Any]:
    set_leaf_or_exempt(ref, None)
    ref["edition_page_key"] = body_edition_key(page_num)
    return ref


# ---------------------------------------------------------------------------
# Volume normalizer
# ---------------------------------------------------------------------------

def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _leaf_to_page(manifest: dict[str, Any]) -> dict[int, int]:
    return {
        int(p["ia_leaf_id"]): int(p["page_num"])
        for p in manifest.get("pages", [])
    }


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _sidecar_is_done(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d.get("page_extras_carried", {}).get("failure_class") is None
    except Exception:  # noqa: BLE001
        return False


def normalize_je_abbyy_volume(
    gz_path: Path,
    manifest_path: Path,
    output_dir: Path,
    *,
    force: bool = False,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Stream JE ABBYY GZ, emit S1 sidecars for pages in the manifest.

    Args:
        gz_path: Path to cu31924091768196_abbyy.gz.
        manifest_path: JE page manifest with leaf->page mapping.
        output_dir: Root output dir; pages go under output_dir/pages/.
        force: Re-emit even if a valid sidecar already exists.

    Returns:
        Dict with emitted_pages, skipped_pages, failed_pages.
    """
    manifest = _load_manifest(manifest_path)
    leaf_to_page_map = _leaf_to_page(manifest)
    if not leaf_to_page_map:
        raise ValueError(f"Manifest at {manifest_path} has no pages")

    manifest_id = _prefixed_sha256_json(
        {"rendering_id": RENDERING_ID, "manifest_path": str(manifest_path)}
    )
    pages_dir = output_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    emitted = 0
    skipped = 0
    failed = 0
    page_refs: list[dict[str, Any]] = []

    detected_engine_version: str | None = None

    with gzip.open(gz_path, "rb") as fh:
        ctx = etree.iterparse(fh, events=("start", "end"))
        leaf_index = 0
        for event, elem in ctx:
            if (
                event == "start"
                and elem.tag == _q("document")
                and detected_engine_version is None
            ):
                producer = elem.get("producer")
                if producer:
                    detected_engine_version = producer

            if event != "end" or elem.tag != _q("page"):
                continue

            page_num = leaf_to_page_map.get(leaf_index)
            if page_num is None:
                leaf_index += 1
                elem.clear()
                while elem.getprevious() is not None:
                    parent = elem.getparent()
                    if parent is not None:
                        del parent[0]
                    else:
                        break
                continue

            page_native_id = f"page_{page_num:04d}"
            sidecar_path = pages_dir / f"{page_native_id}.json"
            try:
                rel_path = sidecar_path.resolve().relative_to(repo_root.resolve()).as_posix()
            except ValueError:
                rel_path = sidecar_path.as_posix()  # test context outside repo

            if not force and _sidecar_is_done(sidecar_path):
                skipped += 1
                page_refs.append(_stamp_je_page_ref({
                    "page_native_id": page_native_id,
                    "sidecar_page_path": rel_path,
                    "status": "eligible",
                    "failure_class": None,
                }, page_num))
            else:
                try:
                    abbyy_page = parse_page(
                        elem,
                        page_index=leaf_index,
                        page_num=page_num,
                        engine_version=detected_engine_version,
                    )
                    sidecar = ia_abbyy_page_to_s1_sidecar(
                        abbyy_page,
                        page_sequence=emitted + skipped + 1,  # 1-indexed
                        manifest_id=manifest_id,
                    )
                    _atomic_write_json(sidecar_path, sidecar)
                    emitted += 1
                    page_refs.append(_stamp_je_page_ref({
                        "page_native_id": page_native_id,
                        "sidecar_page_path": rel_path,
                        "status": "eligible",
                        "failure_class": None,
                    }, page_num))
                    logger.info(
                        "Emitted %s (leaf %d, page %d)", page_native_id, leaf_index, page_num
                    )
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    logger.error(
                        "Failed leaf %d page %d: %s", leaf_index, page_num, exc
                    )
                    page_refs.append(_stamp_je_page_ref({
                        "page_native_id": page_native_id,
                        "sidecar_page_path": rel_path,
                        "status": "corrupt",
                        "failure_class": "extraction_error",
                    }, page_num))

            leaf_index += 1
            elem.clear()
            while elem.getprevious() is not None:
                parent = elem.getparent()
                if parent is not None:
                    del parent[0]
                else:
                    break

    manifest_out = {
        "schema_version": "sidecar-manifest-v1",
        "rendering_id": RENDERING_ID,
        "source_lineage_id": SOURCE_LINEAGE_ID,
        "engine_family": ENGINE_FAMILY,
        "engine_version": detected_engine_version or "unknown",
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "volume": int(manifest.get("volume", 2)),
        "page_count": len(page_refs),
        "pages": page_refs,
    }
    _atomic_write_json(output_dir / "manifest.json", manifest_out)

    logger.info(
        "JE ABBYY: emitted=%d skipped=%d failed=%d", emitted, skipped, failed
    )
    return {
        "emitted_pages": emitted,
        "skipped_pages": skipped,
        "failed_pages": failed,
        "manifest_path": output_dir / "manifest.json",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Emit S1 ABBYY sidecars for JE Vol 2 from cu31924091768196_abbyy.gz"
    )
    ap.add_argument("--gz", required=True, type=Path, help="Path to _abbyy.gz")
    ap.add_argument(
        "--manifest", required=True, type=Path,
        help="JE page manifest (raw/jewish-encyclopedia/ia-pages/vol_02.manifest.json)",
    )
    ap.add_argument(
        "--output-dir", required=True, type=Path,
        help="Output root; pages written to output-dir/pages/",
    )
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    result = normalize_je_abbyy_volume(
        args.gz, args.manifest, args.output_dir, force=args.force
    )
    sys.stdout.write(
        f"emitted={result['emitted_pages']} "
        f"skipped={result['skipped_pages']} "
        f"failed={result['failed_pages']}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
