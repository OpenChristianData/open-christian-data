"""build/tools/generate_page_order.py
Generate page_order.json for NSH volumes 02-12 from their IA manifests.

vol_01 has its own generator (generate_vol01_page_order.py) because of its
unique dual leaf_*/page_* naming scheme. This script handles all other volumes
where every body page is a page_NNNN.jpg file.

Each output page_order.json covers three sections in physical sequence:
  1. Front-matter leaves  -- unnumbered leaves before body page 1 (file=null, not downloaded)
  2. Body pages 1..N      -- page_NNNN.jpg, or null if unresolved in the primary scan
  3. End-matter leaves    -- unnumbered leaves after the last body page (file=null, not downloaded)

scan_status values:
  "present"            -- page_NNNN.jpg exists on disk with correct content
  "download_pending"   -- ia_filename known in manifest, JPEG not yet fetched
  "unresolved"         -- not present in primary NSH item; needs alternate scan source
  "not_fetched"        -- front/back-matter leaf; not downloaded (body-only pipeline skips these)
  "phantom_duplicate"  -- file exists but points to a duplicated IA leaf; content belongs to a
                          different page number. Requires file renames to fix (see fix_phantom_files.py)

Run:
    py -3 build/tools/generate_page_order.py           # generate all vols 02-12
    py -3 build/tools/generate_page_order.py --vol 7   # single volume
Output:
    raw/internet-archive/schaff-herzog-pages/vol_NN/page_order.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.nsh_leaf_model import back_matter, body_pages, front_matter  # noqa: E402

RAW_PAGES = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"

WORK_TITLE = "New Schaff-Herzog Encyclopedia of Religious Knowledge"

# Volumes with known unresolved pages and their best alternate scan source.
# Haucgoog covers all 44 unresolved body pages across these volumes.
_HAUCGOOG_VOLS = {2, 5, 6, 8, 10}


def _build_entries(vol_num: int, manifest: dict) -> list[dict]:
    page_count: int = manifest["page_count"]
    pages_by_num: dict[int, dict] = {
        p["page_num"]: p
        for p in body_pages(manifest)
        if isinstance(p.get("page_num"), int)
    }
    # Map of page_num -> gap status for in-range gaps.
    # "resolved" gaps are cleared -- they behave like normal (present) pages.
    # "phantom_duplicate"/"phantom_inversion" -> scan_status="phantom_duplicate" in output.
    # "permanently_missing" / "unresolved" -> scan_status="unresolved".
    gap_status: dict[int, str] = {
        g["page_num"]: g.get("status", "unresolved")
        for g in manifest.get("gaps", [])
        if isinstance(g.get("page_num"), int) and g["page_num"] <= page_count
    }
    # Keep set of non-resolved gap pages for fast membership test
    gap_nums: set[int] = {
        pn for pn, st in gap_status.items() if st != "resolved"
    }
    # Front/back leaves come from the accessor, which already de-overlaps the
    # leading-run double-record (design SS4.3); the >= / <= guards below are a
    # harmless no-op on accessor output, kept defensive.
    front_leaves_all = front_matter(manifest)
    back_leaves_all = back_matter(manifest)

    # Identify body page 1's leaf index to split front/back matter. leaf_num is
    # the primary-scan coordinate (R-mixed-source), so use it directly rather
    # than int(ia_leaf_id), which is the alternate item's leaf on a hole page.
    body_p1 = pages_by_num.get(1)
    body_last = pages_by_num.get(page_count)
    first_body_leaf = body_p1["leaf_num"] if body_p1 else None
    last_body_leaf = body_last["leaf_num"] if body_last else None

    vol_dir = RAW_PAGES / f"vol_{vol_num:02d}"
    on_disk: set[int] = set()
    if vol_dir.exists():
        for f in vol_dir.glob("page_*.jpg"):
            try:
                on_disk.add(int(f.stem.split("_")[1]))
            except (ValueError, IndexError):
                pass

    entries: list[dict] = []
    seq = 1

    # --- Front-matter leaves ---
    front_leaves = sorted(
        front_leaves_all,
        key=lambda l: l["leaf_num"],
    )
    for leaf in front_leaves:
        if first_body_leaf is not None and leaf["leaf_num"] >= first_body_leaf:
            continue  # don't include body-range leaves here
        entries.append({
            "seq": seq,
            "file": None,
            "book_page": None,
            "label": f"Front matter, leaf {leaf['leaf_num']:04d}",
            "section": "front-matter",
            "corpus_role": "front-matter",
            "scan_status": "not_fetched",
        })
        seq += 1

    # --- Body pages ---
    alt_source = "ia-abbyy-haucgoog-v1" if vol_num in _HAUCGOOG_VOLS else None

    for page_num in range(1, page_count + 1):
        if page_num in gap_nums:
            filename = f"page_{page_num:04d}.jpg"
            st = gap_status[page_num]
            if st in ("phantom_duplicate", "phantom_inversion"):
                # File exists but has wrong content (duplicate IA leaf assignment).
                # Mark as phantom_duplicate so the OCR pipeline skips it.
                entry: dict = {
                    "seq": seq,
                    "file": filename,
                    "book_page": str(page_num),
                    "label": f"p. {page_num}",
                    "section": "body",
                    "corpus_role": "body",
                    "scan_status": "phantom_duplicate",
                }
            elif page_num in on_disk:
                # Gap page fetched from alternate source -- treat as present.
                entry = {
                    "seq": seq,
                    "file": filename,
                    "book_page": str(page_num),
                    "label": f"p. {page_num}",
                    "section": "body",
                    "corpus_role": "body",
                    "scan_status": "present",
                }
            else:
                entry = {
                    "seq": seq,
                    "file": None,
                    "book_page": str(page_num),
                    "label": f"p. {page_num}",
                    "section": "body",
                    "corpus_role": "body",
                    "scan_status": "unresolved",
                }
            if alt_source:
                entry["alternate_scan_source"] = alt_source
            entries.append(entry)
        else:
            page_data = pages_by_num.get(page_num, {})
            filename = f"page_{page_num:04d}.jpg"
            if page_num in on_disk:
                status = "present"
            elif page_data.get("ia_filename"):
                status = "download_pending"
            else:
                status = "unresolved"
            entries.append({
                "seq": seq,
                "file": filename,
                "book_page": str(page_num),
                "label": f"p. {page_num}",
                "section": "body",
                "corpus_role": "body",
                "scan_status": status,
            })
        seq += 1

    # --- End-matter leaves ---
    back_leaves = sorted(
        back_leaves_all,
        key=lambda l: l["leaf_num"],
    )
    for leaf in back_leaves:
        if last_body_leaf is not None and leaf["leaf_num"] <= last_body_leaf:
            continue  # don't include body-range leaves here
        entries.append({
            "seq": seq,
            "file": None,
            "book_page": None,
            "label": f"End matter, leaf {leaf['leaf_num']:04d}",
            "section": "end-matter",
            "corpus_role": "drop",
            "scan_status": "not_fetched",
        })
        seq += 1

    return entries


def _summary(entries: list[dict]) -> dict:
    from collections import Counter
    by_role = Counter(e["corpus_role"] for e in entries)
    by_status = Counter(e.get("scan_status") for e in entries)
    return {
        "body": by_role.get("body", 0),
        "front_matter": by_role.get("front-matter", 0),
        "drop": by_role.get("drop", 0),
        "duplicate": by_role.get("duplicate", 0),
        "scan_present": by_status.get("present", 0),
        "scan_download_pending": by_status.get("download_pending", 0),
        "scan_unresolved": by_status.get("unresolved", 0),
        "scan_not_fetched": by_status.get("not_fetched", 0),
        "scan_phantom_duplicate": by_status.get("phantom_duplicate", 0),
    }


def generate_volume(vol_num: int, *, dry_run: bool = False) -> None:
    vol_id = f"vol_{vol_num:02d}"
    manifest_path = RAW_PAGES / f"{vol_id}.manifest.json"
    if not manifest_path.exists():
        print(f"  {vol_id}: manifest missing -- skip")
        return

    manifest = json.loads(manifest_path.read_bytes())
    page_count = manifest.get("page_count")
    if not page_count:
        print(f"  {vol_id}: manifest has no page_count -- skip")
        return

    entries = _build_entries(vol_num, manifest)
    s = _summary(entries)

    result = {
        "schema": "page-order-v1",
        "volume": vol_num,
        "work": WORK_TITLE,
        "generated": date.today().isoformat(),
        "total_pages": len(entries),
        "summary": s,
        "note": (
            f"Canonical physical page sequence for {vol_id}. "
            f"All body pages use page_NNNN.jpg naming (no leaf_* files for this volume). "
            f"scan_status='download_pending': {s['scan_download_pending']} body pages have a known "
            f"IA source file but have not been fetched yet. "
            f"scan_status='unresolved': {s['scan_unresolved']} body pages are absent from the "
            f"primary NSH scan; alternate source is {_HAUCGOOG_VOLS and 'ia-abbyy-haucgoog-v1' if vol_num in _HAUCGOOG_VOLS else 'unknown'}. "
            + (f"scan_status='phantom_duplicate': {s['scan_phantom_duplicate']} body pages have a file "
               f"on disk but the content belongs to a different page (IA scandata duplicate leaf). "
               f"Run build/tools/fix_phantom_files.py to correct these. " if s['scan_phantom_duplicate'] else "")
            + "Front-matter and end-matter leaves are listed for completeness but have not "
            f"been downloaded (body-only OCR pipeline ignores them)."
        ),
        "pages": entries,
    }

    out_path = RAW_PAGES / vol_id / "page_order.json"
    phantom_note = f" phantom={s['scan_phantom_duplicate']}" if s["scan_phantom_duplicate"] else ""
    if dry_run:
        print(f"  {vol_id}: DRY RUN -- would write {out_path.name} ({len(entries)} entries)")
        print(f"    body={s['body']} present={s['scan_present']} pending={s['scan_download_pending']} "
              f"unresolved={s['scan_unresolved']} not_fetched={s['scan_not_fetched']}{phantom_note}")
        return

    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out_path)
    print(f"  {vol_id}: written {out_path} ({len(entries)} entries) -- "
          f"body={s['body']} present={s['scan_present']} pending={s['scan_download_pending']} "
          f"unresolved={s['scan_unresolved']} not_fetched={s['scan_not_fetched']}{phantom_note}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate page_order.json for NSH vols 02-13")
    parser.add_argument("--vol", type=int, help="Single volume number (2-13)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without writing")
    args = parser.parse_args()

    volumes = [args.vol] if args.vol else list(range(2, 14))
    print(f"Generating page_order.json for {len(volumes)} volume(s)...")
    for vol_num in volumes:
        generate_volume(vol_num, dry_run=args.dry_run)
    print("Done.")


if __name__ == "__main__":
    main()
