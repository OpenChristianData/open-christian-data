"""ia_abbyy.py -- IA ABBYY FineReader XML parser for Schaff-Herzog volumes.

Reads the `_abbyy.gz` files served by archive.org and emits one OCR sidecar
per page plus a per-volume rendering JSON, mirroring the shape used by
local_schaff_tesseract.py and run_cloud_ocr.py.

Four IA sources are supported:

  nsh-main  -- NewSchaffHerzogEncyclopediaOfReligious (all 13 vols, single item)
  dli       -- Digital Library of India (ABBYY 11.0, 7 vols: 1,3,4,6,8,10,11)
  haucgoog  -- Harvard/Google Books (12 vols; multiple copies per vol)
  jackgoog  -- Jacksonville/Google Books (6 vols: 2,3,6,7,12,13)

Each (source, volume) can have multiple copies -- different physical library
copies of the same volume that were scanned independently.  Copy 0 is the
designated primary; copies 1+ are independent re-scans useful for OCR
confidence cross-checking.

For nsh-main the manifest (leaf->page mapping) is required; sidecars are named
by printed page number.  For dli, haucgoog, and jackgoog the manifest is
optional; when omitted sidecars are named by leaf index (0-based position in
the ABBYY file).

The sidecar shape:
  format_version: 1
  coordinate_unit: "pixel"
  coordinate_frame: "source_image"
  page_rotation: 0.0
  engine: "abbyy-finereader"
  engine_version: <ABBYY producer string if present>
  confidence_mean: mean of per-word confidences on the page
  blocks[].lines[].words[]  -- word text, confidence, bbox{x,y,w,h}
  blocks[].lines[] also carries bbox; baseline and x_size are emitted but
    ABBYY's schema does not expose x_size -- that field is always null.

Per ENV-WIN/REL-09 the parser is import-safe (no module-level CLI args / file
opens). CLI dispatch lives under `if __name__ == "__main__":`.

Usage:
  py -3 build/parsers/ia_abbyy.py --volume 1 --source haucgoog --download
  py -3 build/parsers/ia_abbyy.py --volume 1 --source haucgoog --copy 1 --download
  py -3 build/parsers/ia_abbyy.py --volume 1 --source haucgoog --all-copies --download
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lxml import etree

ABBYY_NS = "http://www.abbyy.com/FineReader_xml/FineReader6-schema-v1.xml"
NS = {"abbyy": ABBYY_NS}

# charConfidence sentinel emitted by ABBYY for spaces and decorative glyphs.
# Excluded from confidence aggregation.
ABBYY_CONFIDENCE_SENTINEL = 255

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.nsh_leaf_model import body_pages  # noqa: E402

DEFAULT_RAW_BASE = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
DEFAULT_RENDERING_BASE = (
    REPO_ROOT / "data" / "reference" / "schaff" / "encyclopedia" / "1908-1914" / "ia-abbyy-v1"
)
DEFAULT_ABBYY_GZ_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog"

logger = logging.getLogger("ia_abbyy")

DRY_RUN = False  # API-01 compliance -- flipped inside main() under if __name__ == "__main__"
SKIP_RATE_WARNING_THRESHOLD = 0.05
SKIP_RATE_WARNING_TEMPLATE = (
    "[ia-abbyy] volume %s skipped %d of %d leaves (skip rate %.1f%%); "
    "inspect coverage.%s.json for unmapped leaf details"
)

# Primary rendering identifiers (copy 0).  Per-copy values are derived at runtime.
RENDERING_ID = "ia-abbyy/schaff/encyclopedia/1908-1914/v1"
ENGINE_ALIAS = "ia-abbyy-v1"

# ---------------------------------------------------------------------------
# Source configuration
# ---------------------------------------------------------------------------

NSH_MAIN_ITEM_ID = "NewSchaffHerzogEncyclopediaOfReligious"

# Per-source volume->[item_ids] tables.  Copy 0 (the first entry) is the
# designated primary.  Additional entries are independent re-scans.

# DLI items confirmed from IA metadata search 2026-05-26.
# Vols 2, 5, 7, 9, 12, 13 are absent from the DLI collection on IA.
DLI_VOLUMES: dict[int, list[str]] = {
    1: ["in.ernet.dli.2015.168094"],
    3: ["in.ernet.dli.2015.166446"],
    4: ["in.ernet.dli.2015.88585"],
    6: ["in.ernet.dli.2015.179317"],
    8: ["in.ernet.dli.2015.167097"],
    10: ["in.ernet.dli.2015.75906"],
    11: ["in.ernet.dli.2015.179290"],
}

# Harvard/Google Books haucgoog series.  Primary picked from confirmed jp2
# where available (vol 8); falls back to first confirmed item otherwise.
# Vol 3 and 12 only have tif copies in haucgoog.  Vol 13 absent entirely.
# Mapping built from IA metadata search 2026-05-26 (42-item series).
HAUCGOOG_VOLUMES: dict[int, list[str]] = {
    1: [
        "newschaffherzog11haucgoog",
        "newschaffherzog25haucgoog",
        # newschaffherzog37haucgoog omitted: IA imagecount=267 (genuine partial scan,
        # A-through-Basil only). Last OCR page ends mid-article on "Basil/Basilians"
        # (~p.600); the other two copies reach 539-541 leaves including back matter.
        # Confirmed 2026-05-27 by comparing uncompressed ABBYY size (~831 MB for only
        # 267 pages vs ~1.54 MB/leaf for the full copies) and IA metadata.
    ],
    2: ["newschaffherzog27haucgoog"],
    3: [
        "newschaffherzog29haucgoog",  # tif only -- no jp2 in haucgoog for vol 3
        "newschaffherzog32haucgoog",
    ],
    4: [
        "newschaffherzog13haucgoog",
        "newschaffherzog33haucgoog",
    ],
    5: [
        "newschaffherzog04haucgoog",
        "newschaffherzog16haucgoog",
        "newschaffherzog26haucgoog",
        "newschaffherzog38haucgoog",
        "newschaffherzog40haucgoog",
    ],
    6: [
        "newschaffherzog07haucgoog",
        "newschaffherzog17haucgoog",
        "newschaffherzog28haucgoog",
        "newschaffherzog30haucgoog",
    ],
    7: [
        "newschaffherzog00haucgoog",
        "newschaffherzog23haucgoog",
        "newschaffherzog24haucgoog",
    ],
    8: [
        "newschaffherzog08haucgoog",  # jp2 confirmed
        "newschaffherzog03haucgoog",
        "newschaffherzog14haucgoog",
        "newschaffherzog21haucgoog",
    ],
    9: [
        "newschaffherzog05haucgoog",
        "newschaffherzog09haucgoog",
        "newschaffherzog20haucgoog",
        "newschaffherzog35haucgoog",
        "newschaffherzog36haucgoog",
    ],
    10: [
        "newschaffherzog15haucgoog",
        "newschaffherzog18haucgoog",
        "newschaffherzog19haucgoog",
        "newschaffherzog22haucgoog",
        "newschaffherzog41haucgoog",
    ],
    11: [
        "newschaffherzog06haucgoog",
        "newschaffherzog12haucgoog",
        "newschaffherzog31haucgoog",
        "newschaffherzog34haucgoog",
    ],
    12: ["newschaffherzog39haucgoog"],  # tif only -- no jp2 in haucgoog for vol 12
}

# Jacksonville/Google Books jackgoog series -- 6 volumes only.
JACKGOOG_VOLUMES: dict[int, list[str]] = {
    2: ["newschaffherzog01jackgoog"],
    3: ["newschaffherzog04jackgoog"],
    6: ["newschaffherzog05jackgoog"],
    7: ["newschaffherzog02jackgoog"],
    12: ["newschaffherzog00jackgoog"],
    13: ["newschaffherzog03jackgoog"],
}

_SOURCE_VOLUMES: dict[str, dict[int, list[str]] | None] = {
    "nsh-main": None,  # special-cased: single item for all volumes
    "dli": DLI_VOLUMES,
    "haucgoog": HAUCGOOG_VOLUMES,
    "jackgoog": JACKGOOG_VOLUMES,
}

# Base rendering-id prefix per source.  Combined with copy index to produce
# the actual rendering_id, engine_alias, and sidecar_suffix at runtime.
_SOURCE_BASE_ID = {
    "nsh-main": "ia-abbyy",
    "dli": "ia-abbyy-dli",
    "haucgoog": "ia-abbyy-haucgoog",
    "jackgoog": "ia-abbyy-jackgoog",
}

DEFAULT_DLI_GZ_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-dli"
DEFAULT_HAUCGOOG_GZ_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-haucgoog"
DEFAULT_JACKGOOG_GZ_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-jackgoog"

IA_METADATA_BASE = "https://archive.org/metadata"
IA_DOWNLOAD_BASE = "https://archive.org/download"


# ---------------------------------------------------------------------------
# Source / copy helpers
# ---------------------------------------------------------------------------
def _copy_count(volume: int, source: str) -> int:
    """Number of available copies for this volume from this source."""
    if source == "nsh-main":
        return 1
    table = _SOURCE_VOLUMES.get(source)
    if table is None or volume not in table:
        return 0
    return len(table[volume])


def _source_item_id(volume: int, source: str, copy: int = 0) -> str:
    """Return the IA item identifier for a (volume, source, copy)."""
    if source == "nsh-main":
        if copy != 0:
            raise ValueError("nsh-main only has one item (copy must be 0)")
        return NSH_MAIN_ITEM_ID
    table = _SOURCE_VOLUMES.get(source)
    if table is None:
        raise ValueError(f"Unknown source: {source!r}")
    if volume not in table:
        raise ValueError(
            f"Volume {volume} not available from {source}. Available: {sorted(table)}"
        )
    items = table[volume]
    if copy < 0 or copy >= len(items):
        raise ValueError(
            f"Copy index {copy} out of range for {source} vol {volume} "
            f"(have {len(items)} copies)"
        )
    return items[copy]


def _suffixed_base(source: str, copy: int) -> str:
    """Compose the per-copy base id, e.g. 'ia-abbyy-haucgoog-c1' for copy 1."""
    base = _SOURCE_BASE_ID[source]
    return f"{base}-c{copy}" if copy > 0 else base


def _sidecar_suffix(source: str, copy: int = 0) -> str:
    return _suffixed_base(source, copy)


def _rendering_id_for(source: str, copy: int = 0) -> str:
    return f"{_suffixed_base(source, copy)}/schaff/encyclopedia/1908-1914/v1"


def _engine_alias_for(source: str, copy: int = 0) -> str:
    return f"{_suffixed_base(source, copy)}-v1"


def _gz_dir_for_source(source: str) -> Path:
    return {
        "nsh-main": DEFAULT_ABBYY_GZ_DIR,
        "dli": DEFAULT_DLI_GZ_DIR,
        "haucgoog": DEFAULT_HAUCGOOG_GZ_DIR,
        "jackgoog": DEFAULT_JACKGOOG_GZ_DIR,
    }[source]


# ---------------------------------------------------------------------------
# Page-level parser
# ---------------------------------------------------------------------------
def _q(tag: str) -> str:
    return f"{{{ABBYY_NS}}}{tag}"


def _int_attr(elem, name: str, default: int | None = None) -> int | None:
    v = elem.get(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _word_from_chars(chars: list[etree._Element]) -> dict[str, Any] | None:
    """Build a word dict from a list of charParams.

    Strips trailing whitespace from the text. Returns None when the word
    has no non-space text (pure whitespace, ABBYY's between-word spacer).
    """
    text = "".join((cp.text or "") for cp in chars)
    stripped = text.strip()
    if not stripped:
        return None
    # Confidence is mean of non-sentinel char confidences (excluding spaces).
    confs = []
    for cp in chars:
        if cp.text == " ":
            continue
        c = _int_attr(cp, "charConfidence")
        if c is None or c == ABBYY_CONFIDENCE_SENTINEL:
            continue
        confs.append(c)
    word_conf = sum(confs) / len(confs) if confs else None
    # Bbox over non-space chars
    ls, ts, rs, bs = [], [], [], []
    for cp in chars:
        if cp.text == " ":
            continue
        l = _int_attr(cp, "l")
        t = _int_attr(cp, "t")
        r = _int_attr(cp, "r")
        b = _int_attr(cp, "b")
        if None in (l, t, r, b):
            continue
        ls.append(l)
        ts.append(t)
        rs.append(r)
        bs.append(b)
    if ls and ts and rs and bs:
        bbox = {
            "x": min(ls),
            "y": min(ts),
            "w": max(rs) - min(ls),
            "h": max(bs) - min(ts),
        }
    else:
        bbox = None
    return {"text": stripped, "confidence": word_conf, "bbox": bbox}


def _words_from_line(line_elem: etree._Element) -> list[dict[str, Any]]:
    """Split charParams into words by `wordStart="true"` boundaries.

    Spaces (text=" ") between words have wordStart="false" but break the run
    naturally because their leading-space stripping makes them invisible.
    """
    words: list[dict[str, Any]] = []
    current: list[etree._Element] = []
    # Iterate all charParams across all formatting children
    for fmt in line_elem.findall(_q("formatting")):
        for cp in fmt.findall(_q("charParams")):
            if cp.get("wordStart") == "true" and current:
                w = _word_from_chars(current)
                if w is not None:
                    words.append(w)
                current = [cp]
            else:
                current.append(cp)
    if current:
        w = _word_from_chars(current)
        if w is not None:
            words.append(w)
    return words


def _line_dict(line_elem: etree._Element) -> dict[str, Any]:
    l = _int_attr(line_elem, "l")
    t = _int_attr(line_elem, "t")
    r = _int_attr(line_elem, "r")
    b = _int_attr(line_elem, "b")
    baseline = _int_attr(line_elem, "baseline")
    bbox = None
    if None not in (l, t, r, b):
        bbox = {"x": l, "y": t, "w": r - l, "h": b - t}
    return {
        "bbox": bbox,
        "baseline": baseline,
        "x_size": None,  # ABBYY's schema does not expose x-height
        "words": _words_from_line(line_elem),
    }


def _block_dict(block_elem: etree._Element) -> dict[str, Any]:
    l = _int_attr(block_elem, "l")
    t = _int_attr(block_elem, "t")
    r = _int_attr(block_elem, "r")
    b = _int_attr(block_elem, "b")
    bbox = None
    if None not in (l, t, r, b):
        bbox = {"x": l, "y": t, "w": r - l, "h": b - t}
    lines: list[dict[str, Any]] = []
    text_elem = block_elem.find(_q("text"))
    if text_elem is not None:
        for par in text_elem.findall(_q("par")):
            for line in par.findall(_q("line")):
                lines.append(_line_dict(line))
    return {
        "block_type": block_elem.get("blockType", "Text"),
        "bbox": bbox,
        "lines": lines,
    }


def parse_page(
    page_elem: etree._Element,
    *,
    page_index: int,
    page_num: int | str | None,
    engine_version: str | None = None,
) -> dict[str, Any]:
    """Convert an ABBYY <page> element into a sidecar dict."""
    width = _int_attr(page_elem, "width")
    height = _int_attr(page_elem, "height")

    blocks: list[dict[str, Any]] = []
    for block in page_elem.findall(_q("block")):
        if block.get("blockType") != "Text":
            continue
        blocks.append(_block_dict(block))

    # Aggregate words, confidence, text
    all_words = [w for blk in blocks for ln in blk["lines"] for w in ln["words"]]
    word_count = len(all_words)
    confs = [w["confidence"] for w in all_words if w["confidence"] is not None]
    confidence_mean = sum(confs) / len(confs) if confs else None

    # Page text: concatenate lines (one line per source line; blank between blocks)
    page_lines: list[str] = []
    for blk in blocks:
        if blk["lines"]:
            page_lines.extend(" ".join(w["text"] for w in ln["words"]) for ln in blk["lines"])
            page_lines.append("")  # block separator
    text = "\n".join(line for line in page_lines).strip()

    return {
        "format_version": 1,
        "coordinate_unit": "pixel",
        "coordinate_frame": "source_image",
        "page_rotation": 0.0,
        "engine": "abbyy-finereader",
        "engine_version": engine_version,
        "page_index": page_index,
        "page_num": page_num,
        "page_size": {"width": width, "height": height} if width and height else None,
        "confidence_mean": confidence_mean,
        "word_count": word_count,
        "text": text,
        "blocks": blocks,
    }


# ---------------------------------------------------------------------------
# Volume parser -- streams the gzipped XML
# ---------------------------------------------------------------------------
def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _leaf_to_pagenum(manifest: dict[str, Any]) -> dict[int, int]:
    out: dict[int, int] = {}
    # Body leaves via the accessor (legacy fallback carries ia_leaf_id verbatim,
    # so the primary item's leaf->page map is identical to the old read).
    for p in body_pages(manifest):
        try:
            leaf = int(p["ia_leaf_id"])
            out[leaf] = int(p["page_num"])
        except (KeyError, ValueError):
            continue
    # Image-less body pages (permanent scan gaps) that still carry ABBYY text:
    # if the gap entry records its leaf, map it to the printed page so the sidecar
    # is named page_NNNN (findable body content) rather than the page_leafNNNN
    # fallback, which is reserved for genuinely unnumbered front/back matter.
    # vol_13 pp209-211 (leaves 225-227) are bibliographical-appendix body pages
    # absent as images but present as text -- see NSH_FETCHER_MECHANISM_DIAGNOSIS.
    for g in manifest.get("gaps", []):
        if g.get("status") in ("permanently_missing", "absent_from_primary_scan") and g.get("ia_leaf_id"):
            try:
                out[int(g["ia_leaf_id"])] = int(g["page_num"])
            except (KeyError, ValueError):
                continue
    return out


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def parse_volume(
    gz_path: Path,
    manifest_path: Path | None,
    sidecar_dir: Path,
    *,
    engine_version: str | None = None,
    verbose: bool = False,
    sidecar_suffix: str = "ia-abbyy",
) -> dict[str, Any]:
    """Stream the ABBYY XML, emit per-page sidecars + raw XML.

    manifest_path: Path to the volume manifest (leaf->printed-page mapping).
      Pass None for single-volume sources where no manifest has been built --
      sidecars are then named by leaf index instead of printed page number.

    sidecar_suffix controls the output filename, e.g.:
      "ia-abbyy"             -> page_NNNN.ia-abbyy.json
      "ia-abbyy-haucgoog"    -> page_NNNN.ia-abbyy-haucgoog.json (copy 0)
      "ia-abbyy-haucgoog-c1" -> page_NNNN.ia-abbyy-haucgoog-c1.json (copy 1)

    Returns stats: pages_parsed, pages_skipped, pages_leaf_captured,
    mean_confidence, total_words, total_leaves, skip_rate, skipped_leaf_indices.
    """
    manifest: dict[str, Any] | None = None
    if manifest_path is not None:
        manifest = _load_manifest(manifest_path)
        leaf_to_page: dict[int, int] | None = _leaf_to_pagenum(manifest)
    else:
        leaf_to_page = None  # use leaf index directly as page identifier

    sidecar_dir.mkdir(parents=True, exist_ok=True)

    pages_parsed = 0
    pages_skipped = 0
    pages_leaf_captured = 0
    skipped_leaf_indices: list[int] = []
    all_confidences: list[float] = []
    total_words = 0
    detected_version = engine_version

    with gzip.open(gz_path, "rb") as fh:
        ctx = etree.iterparse(fh, events=("start", "end"))
        page_index = 0
        for event, elem in ctx:
            # Detect engine version from <document> producer attribute at start
            if (
                event == "start"
                and elem.tag == _q("document")
                and detected_version is None
            ):
                producer = elem.get("producer")
                if producer:
                    detected_version = producer
            if event == "end" and elem.tag == _q("page"):
                leaf_fallback = False
                if leaf_to_page is not None:
                    page_num: int | str | None = leaf_to_page.get(page_index)
                    if page_num is None:
                        pages_skipped += 1
                        pages_leaf_captured += 1
                        skipped_leaf_indices.append(page_index)
                        page_num = f"leaf{page_index:04d}"
                        leaf_fallback = True
                else:
                    page_num = page_index  # leaf index as page identifier

                sidecar = parse_page(
                    elem,
                    page_index=page_index,
                    page_num=page_num,
                    engine_version=detected_version,
                )
                if isinstance(page_num, int):
                    page_stem = f"page_{page_num:04d}"
                else:
                    page_stem = f"page_{page_num}"
                sidecar_path = sidecar_dir / f"{page_stem}.{sidecar_suffix}.json"
                raw_path = sidecar_dir / f"{page_stem}.{sidecar_suffix}.raw.xml"
                _atomic_write_json(sidecar_path, sidecar)
                raw_bytes = etree.tostring(elem, pretty_print=False)
                _atomic_write_bytes(raw_path, raw_bytes)
                if not leaf_fallback:
                    pages_parsed += 1
                    if sidecar["confidence_mean"] is not None:
                        all_confidences.extend(
                            [w["confidence"] for blk in sidecar["blocks"]
                             for ln in blk["lines"] for w in ln["words"]
                             if w["confidence"] is not None]
                        )
                    total_words += sidecar["word_count"]
                    if verbose and pages_parsed % 50 == 0:
                        logger.info(
                            "[ia-abbyy] parsed page %d (page_num=%s, words=%d, mean_conf=%.1f)",
                            pages_parsed,
                            page_num,
                            sidecar["word_count"],
                            sidecar["confidence_mean"] or 0.0,
                        )
                page_index += 1
                # free memory
                elem.clear()
                while elem.getprevious() is not None:
                    parent = elem.getparent()
                    if parent is not None:
                        del parent[0]
                    else:
                        break

    mean_conf = (
        sum(all_confidences) / len(all_confidences) if all_confidences else None
    )
    total_leaves = page_index
    skip_rate = pages_skipped / max(pages_skipped + pages_parsed, 1)
    if skip_rate > SKIP_RATE_WARNING_THRESHOLD:
        volume_label = manifest.get("volume", gz_path.stem) if manifest is not None else gz_path.stem
        logger.warning(
            SKIP_RATE_WARNING_TEMPLATE,
            volume_label,
            pages_skipped,
            total_leaves,
            100 * skip_rate,
            sidecar_suffix,
        )
    return {
        "pages_parsed": pages_parsed,
        "pages_skipped": pages_skipped,
        "pages_leaf_captured": pages_leaf_captured,
        "mean_confidence": mean_conf,
        "total_words": total_words,
        "engine_version": detected_version,
        "total_leaves": total_leaves,
        "skip_rate": skip_rate,
        "skipped_leaf_indices": skipped_leaf_indices,
    }


def _leaf_coverage_report(
    *,
    volume: int,
    source: str,
    copy: int,
    sidecar_suffix: str,
    sidecar_dir: Path,
    stats: dict[str, Any],
    manifest_path: Path | None,
) -> dict[str, Any]:
    """Write one atomic summary of parsed and unmapped ABBYY leaves."""
    manifest = _load_manifest(manifest_path) if manifest_path is not None else None
    payload = {
        "volume": volume,
        "source": source,
        "copy": copy,
        "sidecar_suffix": sidecar_suffix,
        "assembled_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "total_leaves": stats["total_leaves"],
        "manifest_entries": len(_leaf_to_pagenum(manifest)) if manifest is not None else None,
        "pages_parsed": stats["pages_parsed"],
        "pages_skipped": stats["pages_skipped"],
        "skip_rate": round(stats["skip_rate"], 4),
        "skipped_leaf_indices": stats["skipped_leaf_indices"],
        "manifest_warnings": manifest.get("manifest_warnings", []) if manifest is not None else [],
    }
    _atomic_write_json(sidecar_dir / f"coverage.{sidecar_suffix}.json", payload)
    return payload


# ---------------------------------------------------------------------------
# Volume assembler -- mirrors local_schaff_tesseract.assemble_volume_json
# ---------------------------------------------------------------------------
def assemble_volume_json(
    *,
    volume_num: int,
    sidecar_dir: Path,
    out_path: Path,
    sidecar_suffix: str = "ia-abbyy",
    rendering_id: str = RENDERING_ID,
    engine_alias: str = ENGINE_ALIAS,
) -> dict[str, Any]:
    """Aggregate per-page sidecars into a per-volume rendering.

    sidecar_suffix, rendering_id, engine_alias should match the (source, copy)
    used when parse_volume was called.

    Output shape mirrors data/reference/.../oss-tesseract-v1/vol_NN.json:
      rendering_id, volume, assembled_at, engine_alias, engine_version,
      page_count, pages_with_data, confidence_mean,
      pages: [{page, confidence_mean, word_count, text}, ...]
    """
    sidecars = sorted(sidecar_dir.glob(f"page_*.{sidecar_suffix}.json"))
    pages: list[dict[str, Any]] = []
    weighted_sum = 0.0
    weighted_n = 0
    engine_version: str | None = None
    for path in sidecars:
        d = json.loads(path.read_text(encoding="utf-8"))
        if engine_version is None:
            engine_version = d.get("engine_version")
        page_num = d["page_num"]
        conf = d.get("confidence_mean")
        wc = d.get("word_count", 0)
        text = d.get("text", "")
        pages.append(
            {
                "page": page_num,
                "confidence_mean": round(conf, 1) if conf is not None else None,
                "word_count": wc,
                "text": text,
            }
        )
        if conf is not None and wc > 0:
            weighted_sum += conf * wc
            weighted_n += wc
    pages.sort(
        key=lambda page: (
            0,
            page["page"],
        )
        if isinstance(page["page"], int)
        else (
            1,
            int(page["page"][4:]) if page["page"].startswith("leaf") else sys.maxsize,
        )
    )
    confidence_mean = round(weighted_sum / weighted_n, 1) if weighted_n else None
    pages_with_data = sum(1 for p in pages if p["word_count"] > 0)
    unmapped_leaf_count = sum(1 for page in pages if isinstance(page["page"], str))

    payload = {
        "rendering_id": rendering_id,
        "volume": volume_num,
        "assembled_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "engine_alias": engine_alias,
        "engine_version": engine_version,
        "page_count": len(pages),
        "pages_with_data": pages_with_data,
        "unmapped_leaf_count": unmapped_leaf_count,
        "confidence_mean": confidence_mean,
        "pages": pages,
    }
    _atomic_write_json(out_path, payload)
    return payload


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------
def _ia_metadata(item_id: str, timeout: int = 30) -> dict[str, Any]:
    """Fetch IA item metadata JSON with retry on transient errors."""
    url = f"{IA_METADATA_BASE}/{item_id}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read())  # type: ignore[return-value]
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503) and attempt < 2:
                wait = 2 ** (attempt + 1)
                logger.info("HTTP %d fetching metadata, retry in %ds", exc.code, wait)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"Failed to fetch metadata for {item_id} after 3 attempts")


def _find_abbyy_gz_name(
    files: list[dict[str, Any]], volume: int, source: str = "nsh-main"
) -> str | None:
    """Return the _abbyy.gz filename from an IA item file list.

    nsh-main has all 13 volumes in one item, so files are prefixed by volume
    number (e.g. "01.NewSchaffHerzog...").  All other sources are single-
    volume items, so any file ending in _abbyy.gz is the right one.
    """
    if source == "nsh-main":
        prefix = f"{volume:02d}."
        candidates = [
            f["name"]
            for f in files
            if f.get("name", "").startswith(prefix) and f["name"].endswith("_abbyy.gz")
        ]
    else:
        candidates = [f["name"] for f in files if f.get("name", "").endswith("_abbyy.gz")]
    return candidates[0] if candidates else None


def download_abbyy_gz(
    volume: int,
    *,
    source: str = "nsh-main",
    copy: int = 0,
    gz_dir: Path | None = None,
    dry_run: bool = False,
) -> Path:
    """Download the ABBYY .gz file for a (volume, source, copy) from IA.

    Returns the local path to the downloaded (or already-present) file.
    """
    item_id = _source_item_id(volume, source, copy=copy)
    dest_dir = gz_dir or _gz_dir_for_source(source)

    metadata = _ia_metadata(item_id)
    files = metadata.get("files", [])
    fname = _find_abbyy_gz_name(files, volume, source)
    if fname is None:
        raise FileNotFoundError(
            f"No _abbyy.gz found for volume {volume} in IA item {item_id}"
        )

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / fname

    if dest.exists():
        logger.info("[ia-abbyy] %s already present, skipping download", dest.name)
        return dest

    url = f"{IA_DOWNLOAD_BASE}/{item_id}/{fname}"
    if dry_run:
        logger.info("[dry-run] would download %s -> %s", url, dest)
        return dest

    logger.info("[ia-abbyy] downloading %s ...", fname)
    # urllib.request.urlretrieve is fine here: public IA content, no secrets.
    urllib.request.urlretrieve(url, dest)
    logger.info("[ia-abbyy] downloaded %s (%.1f MB)", fname, dest.stat().st_size / 1e6)
    return dest


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------
def _gz_path_for_volume(volume: int, source: str = "nsh-main", copy: int = 0) -> Path:
    gz_dir = _gz_dir_for_source(source)
    if source == "nsh-main":
        pattern = f"{volume:02d}.*._abbyy.gz"
    else:
        # Single-volume item: file is named by IA's own convention.
        # Use the known item_id as the search anchor.
        item_id = _source_item_id(volume, source, copy=copy)
        pattern = f"{item_id}*_abbyy.gz"
    candidates = sorted(gz_dir.glob(pattern))
    if not candidates:
        raise FileNotFoundError(
            f"No ABBYY .gz found for volume {volume} ({source}, copy {copy}) under {gz_dir}. "
            f"Run with --download to fetch it first."
        )
    return candidates[0]


def _manifest_path_for_volume(volume: int) -> Path:
    return DEFAULT_RAW_BASE / f"vol_{volume:02d}.manifest.json"


def _sidecar_dir_for_volume(volume: int) -> Path:
    return DEFAULT_RAW_BASE / f"vol_{volume:02d}"


def _rendering_out_path(volume: int, source: str = "nsh-main", copy: int = 0) -> Path:
    alias = _engine_alias_for(source, copy)
    base = (
        REPO_ROOT / "data" / "reference" / "schaff" / "encyclopedia" / "1908-1914" / alias
    )
    return base / f"vol_{volume:02d}.json"


def _run_one(
    volume: int,
    source: str,
    copy: int,
    *,
    download: bool,
    assemble_only: bool,
    verbose: bool,
    dry_run: bool,
) -> int:
    """Run a single (volume, source, copy) through download + parse + assemble."""
    sidecar_suffix = _sidecar_suffix(source, copy)
    rendering_id = _rendering_id_for(source, copy)
    engine_alias = _engine_alias_for(source, copy)
    sidecar_dir = _sidecar_dir_for_volume(volume)
    out_path = _rendering_out_path(volume, source=source, copy=copy)
    manifest_path = _manifest_path_for_volume(volume) if source == "nsh-main" else None

    if download:
        gz_path = download_abbyy_gz(volume, source=source, copy=copy, dry_run=dry_run)
    else:
        gz_path = _gz_path_for_volume(volume, source=source, copy=copy)

    if dry_run:
        print(f"[dry-run] would parse {gz_path} using manifest {manifest_path}")
        print(f"[dry-run] would write sidecars under {sidecar_dir}/page_*.{sidecar_suffix}.json")
        print(f"[dry-run] would assemble {out_path}")
        return 0

    if not assemble_only:
        stats = parse_volume(
            gz_path=gz_path,
            manifest_path=manifest_path,
            sidecar_dir=sidecar_dir,
            verbose=verbose,
            sidecar_suffix=sidecar_suffix,
        )
        mean_conf = stats["mean_confidence"]
        mean_str = f"{mean_conf:.1f}" if mean_conf is not None else "n/a"
        print(
            f"[{source} c{copy}] parse_volume: pages_parsed={stats['pages_parsed']}, "
            f"pages_skipped={stats['pages_skipped']}, "
            f"mean_confidence={mean_str}, total_words={stats['total_words']}"
        )
        _leaf_coverage_report(
            volume=volume,
            source=source,
            copy=copy,
            sidecar_suffix=sidecar_suffix,
            sidecar_dir=sidecar_dir,
            stats=stats,
            manifest_path=manifest_path,
        )

    payload = assemble_volume_json(
        volume_num=volume,
        sidecar_dir=sidecar_dir,
        out_path=out_path,
        sidecar_suffix=sidecar_suffix,
        rendering_id=rendering_id,
        engine_alias=engine_alias,
    )
    print(
        f"[{source} c{copy}] assemble_volume_json: page_count={payload['page_count']}, "
        f"pages_with_data={payload['pages_with_data']}, "
        f"confidence_mean={payload['confidence_mean']} -> {out_path}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    global DRY_RUN
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--volume", type=int, required=True)
    parser.add_argument(
        "--source",
        choices=list(_SOURCE_BASE_ID),
        default="nsh-main",
        help="IA source (default: nsh-main)",
    )
    parser.add_argument(
        "--copy",
        type=int,
        default=0,
        help="Copy index for sources with multiple library copies (default: 0)",
    )
    parser.add_argument(
        "--all-copies",
        action="store_true",
        help="Run every available copy for this (volume, source) sequentially.",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the ABBYY .gz file from IA before parsing.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--assemble-only",
        action="store_true",
        help="Skip XML parsing; only build the per-volume rendering JSON.",
    )
    args = parser.parse_args(argv)
    if args.dry_run:
        DRY_RUN = True

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.all_copies:
        n = _copy_count(args.volume, args.source)
        if n == 0:
            raise SystemExit(
                f"Volume {args.volume} not available from source {args.source}"
            )
        copies = list(range(n))
    else:
        copies = [args.copy]

    print(f"Running {args.source} vol {args.volume} for copies {copies}")
    # API-01: announce the mode at the live boundary -- DRY_RUN gates every IA
    # download + sidecar write threaded through _run_one (dry_run=DRY_RUN).
    if DRY_RUN:
        print("DRY RUN -- no IA downloads or sidecar writes will be performed.")
    else:
        print("LIVE -- will download from IA (if --download) and write sidecars.")
    for c in copies:
        _run_one(
            volume=args.volume,
            source=args.source,
            copy=c,
            download=args.download,
            assemble_only=args.assemble_only,
            verbose=args.verbose,
            dry_run=DRY_RUN,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
