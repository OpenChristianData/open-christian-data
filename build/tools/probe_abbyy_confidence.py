"""Probe ABBYY FineReader confidence scores for arbitrary IA items.

Downloads the _abbyy.gz for one or more IA item IDs and extracts per-leaf
confidence_mean. Use this to compare ABBYY lineages before committing to one
as the engine input for a non-SH pipeline (e.g. Jewish Encyclopedia).

Non-circular constraint: IA ABBYY GZ files are ENGINE INPUT, never the
reference. The JE.com human transcription is the reference.

Usage:
  py -3 build/tools/probe_abbyy_confidence.py \\
      --item cu31924091768196 --leaves 73,74,75

  py -3 build/tools/probe_abbyy_confidence.py \\
      --compare cu31924091768196 OTHER_ITEM_ID --leaves 73,74,75

  py -3 build/tools/probe_abbyy_confidence.py \\
      --item cu31924091768196 --all-leaves
"""
from __future__ import annotations

import argparse
import gzip
import urllib.parse
import logging
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from lxml import etree

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

# Import core parsing logic from ia_abbyy to avoid duplication.
from build.parsers.ia_abbyy import _q, _word_from_chars  # noqa: E402

logger = logging.getLogger("probe_abbyy_confidence")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = REPO_ROOT / "raw" / "jewish-encyclopedia" / "ia-abbyy"
IA_DOWNLOAD_BASE = "https://archive.org/download"
CRAWL_DELAY = 5  # seconds between downloads
USER_AGENT = "OCD-fetcher/1.0 (research; non-commercial)"


# ---------------------------------------------------------------------------
# URL helper
# ---------------------------------------------------------------------------

def abbyy_gz_url(item_id: str, gz_filename: str | None = None) -> str:
    """Return the IA download URL for item_id's ABBYY GZ.

    gz_filename: override the filename portion of the URL for items where
    the GZ is not named {item_id}_abbyy.gz (e.g. HTML5-uploaded items).
    """
    filename = gz_filename if gz_filename is not None else f"{item_id}_abbyy.gz"
    encoded = urllib.parse.quote(filename, safe="")
    return f"{IA_DOWNLOAD_BASE}/{item_id}/{encoded}"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _default_fetch(url: str, dest: str | Path, *, timeout: int = 300) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            tmp.write_bytes(resp.read())
        tmp.replace(dest)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def download_gz_if_needed(
    item_id: str,
    cache_dir: Path,
    *,
    gz_filename: str | None = None,
    _fetch_fn=None,
) -> Path:
    """Return path to the cached GZ, downloading if absent.

    gz_filename: override the remote filename for items with non-standard GZ
    naming (e.g. HTML5-uploaded items where the file is named differently from
    {item_id}_abbyy.gz). The local cache file is always named {item_id}_abbyy.gz
    regardless of gz_filename.
    """
    gz_path = cache_dir / f"{item_id}_abbyy.gz"
    if gz_path.exists():
        return gz_path
    fetch = _fetch_fn if _fetch_fn is not None else _default_fetch
    url = abbyy_gz_url(item_id, gz_filename)
    logger.info("Downloading %s -> %s", url, gz_path)
    fetch(url, gz_path)
    return gz_path


# ---------------------------------------------------------------------------
# Per-leaf confidence extraction
# ---------------------------------------------------------------------------

def _page_confidence(page_elem: etree._Element) -> tuple[float | None, int]:
    """Return (confidence_mean, word_count) for one ABBYY <page> element."""
    all_words: list[dict[str, Any]] = []
    for block in page_elem.findall(_q("block")):
        if block.get("blockType") != "Text":
            continue
        text_elem = block.find(_q("text"))
        if text_elem is None:
            continue
        for par in text_elem.findall(_q("par")):
            for line in par.findall(_q("line")):
                for fmt in line.findall(_q("formatting")):
                    # Group charParams into words by wordStart boundary
                    current: list[etree._Element] = []
                    for cp in fmt.findall(_q("charParams")):
                        if cp.get("wordStart") == "true" and current:
                            w = _word_from_chars(current)
                            if w is not None:
                                all_words.append(w)
                            current = [cp]
                        else:
                            current.append(cp)
                    if current:
                        w = _word_from_chars(current)
                        if w is not None:
                            all_words.append(w)

    confs = [w["confidence"] for w in all_words if w["confidence"] is not None]
    mean = sum(confs) / len(confs) if confs else None
    return mean, len(all_words)


def probe_gz_confidence(
    gz_path: Path,
    leaf_indices: set[int] | None = None,
) -> list[dict[str, Any]]:
    """Stream an ABBYY GZ and return per-leaf confidence data.

    Args:
        gz_path: Path to the local _abbyy.gz file.
        leaf_indices: 0-based leaf indices to return. None means all leaves.

    Returns:
        List of dicts, one per matching leaf, sorted by leaf_index:
          {leaf_index: int, confidence_mean: float | None, word_count: int}
    """
    results: list[dict[str, Any]] = []
    leaf_index = 0

    with gzip.open(gz_path, "rb") as fh:
        ctx = etree.iterparse(fh, events=("end",))
        for _event, elem in ctx:
            if elem.tag != _q("page"):
                continue
            if leaf_indices is None or leaf_index in leaf_indices:
                mean, word_count = _page_confidence(elem)
                results.append({
                    "leaf_index": leaf_index,
                    "confidence_mean": mean,
                    "word_count": word_count,
                })
            leaf_index += 1
            elem.clear()
            while elem.getprevious() is not None:
                parent = elem.getparent()
                if parent is not None:
                    del parent[0]
                else:
                    break

    return results


# ---------------------------------------------------------------------------
# Comparison helper
# ---------------------------------------------------------------------------

def compare_items(
    item_ids: list[str],
    leaf_indices: set[int] | None,
    cache_dir: Path,
    *,
    gz_filenames: dict[str, str] | None = None,
    _fetch_fn=None,
) -> dict[str, list[dict[str, Any]]]:
    """Download and probe all item_ids, return {item_id: [per-leaf results]}.

    gz_filenames: optional {item_id: filename} overrides for items whose GZ is
    not named {item_id}_abbyy.gz.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    fn_map = gz_filenames or {}
    for item_id in item_ids:
        gz_path = download_gz_if_needed(
            item_id, cache_dir,
            gz_filename=fn_map.get(item_id),
            _fetch_fn=_fetch_fn,
        )
        out[item_id] = probe_gz_confidence(gz_path, leaf_indices=leaf_indices)
        if len(item_ids) > 1:
            time.sleep(CRAWL_DELAY)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_table(results: dict[str, list[dict[str, Any]]]) -> None:
    all_leaves = sorted({r["leaf_index"] for rows in results.values() for r in rows})
    item_ids = list(results)

    # Build lookup: item_id -> leaf_index -> row
    table: dict[str, dict[int, dict]] = {
        iid: {r["leaf_index"]: r for r in rows}
        for iid, rows in results.items()
    }

    col_w = max(20, max(len(iid) for iid in item_ids))
    header = f"{'Leaf':>6} | " + " | ".join(f"{iid:>{col_w}}" for iid in item_ids)
    sys.stdout.write(header + "\n")
    sys.stdout.write("-" * len(header) + "\n")
    for leaf in all_leaves:
        row = f"{leaf:>6} | "
        cells = []
        for iid in item_ids:
            entry = table[iid].get(leaf)
            if entry is None:
                cells.append(f"{'N/A':>{col_w}}")
            elif entry["confidence_mean"] is None:
                cells.append(f"{'(no text)':>{col_w}}")
            else:
                cells.append(f"{entry['confidence_mean']:>{col_w}.1f}")
        sys.stdout.write(row + " | ".join(cells) + "\n")

    # Summary: mean across sampled leaves per item
    sys.stdout.write("\nMean confidence across sampled leaves:\n")
    for iid in item_ids:
        means = [
            r["confidence_mean"]
            for r in results[iid]
            if r["confidence_mean"] is not None
        ]
        overall = sum(means) / len(means) if means else None
        label = f"{overall:.1f}" if overall is not None else "N/A"
        sys.stdout.write(f"  {iid}: {label}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe ABBYY GZ confidence for IA items")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--item", metavar="ITEM_ID",
                       help="Single IA item ID to probe")
    group.add_argument("--compare", nargs="+", metavar="ITEM_ID",
                       help="Two or more IA item IDs to compare")
    leaf_group = ap.add_mutually_exclusive_group(required=True)
    leaf_group.add_argument("--leaves", metavar="N,N,...",
                            help="Comma-separated 0-based leaf indices to sample")
    leaf_group.add_argument("--all-leaves", action="store_true",
                            help="Sample every leaf in the GZ (slow for full volumes)")
    ap.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR,
                    help="Directory for cached GZ files")
    ap.add_argument(
        "--gz-filename", metavar="ITEM_ID=FILENAME", action="append", default=[],
        help="Override the GZ filename for a specific item (for non-standard IA uploads). "
             "Example: --gz-filename 'MyItem=My Item Name_abbyy.gz'",
    )
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if args.leaves:
        leaf_set: set[int] | None = {int(x.strip()) for x in args.leaves.split(",")}
    else:
        leaf_set = None  # all leaves

    gz_filenames: dict[str, str] = {}
    for override in args.gz_filename:
        if "=" not in override:
            ap.error(f"--gz-filename must be in ITEM_ID=FILENAME form, got: {override!r}")
        iid, fname = override.split("=", 1)
        gz_filenames[iid.strip()] = fname.strip()

    item_ids = [args.item] if args.item else args.compare
    results = compare_items(item_ids, leaf_set, args.cache_dir, gz_filenames=gz_filenames)
    _print_table(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
