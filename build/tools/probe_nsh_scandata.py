"""Probe live IA scandata for NSH volumes: confirm front-page offset, gaps,
and duplicates against the runbook table BEFORE any expensive JP2 fetch (PIPE-29).

Reads only the scandata XML (cheap) for each requested volume and prints:
  - numbered printed-page range and the leaf of the first numbered page
  - the contiguous run of unnumbered leaves immediately before it (front candidates)
  - derived front offset (page = leaf - offset)
  - in-range scan gaps (printed pages with no leaf)
  - duplicate pageNumbers (same printed page on >1 leaf)

Usage:
  py -3 build/tools/probe_nsh_scandata.py 8 1 2 5 11 6

Fetcher helpers live in the sibling OCR repo:
  ../EzraOCR/ezra/tools/fetch_ia_pages.py
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Import helpers from the sibling OCR fetcher by path (no package install needed).
import importlib.util

REPO_ROOT = Path(__file__).resolve().parents[2]
EZRA_ROOT = REPO_ROOT.parent / "EzraOCR"
_spec = importlib.util.spec_from_file_location(
    "fetch_ia_pages", EZRA_ROOT / "ezra" / "tools" / "fetch_ia_pages.py"
)
_fip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fip)


def _ordered_leaf_pages(scandata_root: ET.Element) -> list[tuple[int, int | None]]:
    """Return [(leaf_num, pageNumber-or-None), ...] in document order."""
    ns = "http://www.archive.org/scandata"
    pages = (
        scandata_root.findall(f".//{{{ns}}}page")
        or scandata_root.findall(".//page")
    )
    rows: list[tuple[int, int | None]] = []
    for page in pages:
        leaf_str = page.get("leafNum", "")
        if not leaf_str.isdigit():
            continue
        pnum_el = page.find(f"{{{ns}}}pageNumber") or page.find("pageNumber")
        pnum = (pnum_el.text or "").strip() if pnum_el is not None else ""
        rows.append((int(leaf_str), int(pnum) if pnum.isdigit() else None))
    return rows


def probe(volume: int) -> None:
    zip_name, page_to_leaf, total_pages, info = _fip._resolve_volume(
        _fip.IA_ITEM_ID, volume
    )
    prefix = zip_name.replace("_jp2.zip", "")
    scandata_url = f"{_fip._IA_BASE_URL.format(item_id=_fip.IA_ITEM_ID)}/{prefix}_scandata.xml"
    rows = _ordered_leaf_pages(_fip._fetch_xml(scandata_url))
    leaf_of_page = {pn: leaf for leaf, pn in rows if pn is not None}

    rng = info["numbered_range"]
    print(f"\n=== vol_{volume:02d} ===")
    print(f"  zip: {zip_name}")
    print(f"  total scandata leaves: {total_pages}")
    print(f"  numbered range: {rng}")
    if not rng:
        print("  (no numbered pages?)")
        return
    first_page = rng[0]
    first_leaf = leaf_of_page[first_page]
    print(f"  first numbered page {first_page} -> leaf {first_leaf}")

    # Walk backwards from first_leaf over contiguous unnumbered leaves -> front body.
    by_leaf = {leaf: pn for leaf, pn in rows}
    front_leaves = []
    leaf = first_leaf - 1
    while leaf in by_leaf and by_leaf[leaf] is None:
        front_leaves.append(leaf)
        leaf -= 1
    front_leaves.sort()
    if front_leaves:
        offset = first_leaf - first_page  # page = leaf - offset
        # front body pages map page -> leaf = page + offset
        lo_leaf, hi_leaf = front_leaves[0], front_leaves[-1]
        lo_page, hi_page = lo_leaf - offset, hi_leaf - offset
        print(f"  contiguous unnumbered leaves before body: {lo_leaf}..{hi_leaf} "
              f"({len(front_leaves)} leaves)")
        print(f"  derived offset (leaf-page) = {offset}")
        print(f"  => front body pages {lo_page}..{hi_page} = leaves {lo_leaf}..{hi_leaf}")
        spec = ",".join(f"{lf}:{lf - offset}" for lf in front_leaves)
        print(f"  --primary-leaf-page-spec \"{spec}\"")
    else:
        print("  no contiguous unnumbered leaves before first body page")

    gaps = info["missing_pages"]
    print(f"  in-range scan gaps ({len(gaps)}): {gaps}")
    dups = {p: sorted(ls) for p, ls in sorted(info["duplicates"].items())}
    print(f"  duplicate pageNumbers ({len(dups)}): {dups}")


def main() -> int:
    vols = [int(v) for v in sys.argv[1:]] or [8, 1, 2, 5, 11, 6]
    for v in vols:
        probe(v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
