"""build/tools/generate_vol01_page_order.py
Generate the canonical page-order manifest for vol_01 of the
Schaff-Herzog IA image set.

vol_01 is unique: it has 52 leaf_*.jpg files alongside 491 page_*.jpg files.
vols 02-13 have page_*.jpg only. This script produces the manifest that lets
the pipeline process all files in correct physical sequence.

Run:
    py -3 build/tools/generate_vol01_page_order.py
Output:
    raw/internet-archive/schaff-herzog-pages/vol_01/page_order.json
"""
import json
import os
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
VOL_DIR = MANIFEST_DIR / "vol_01"
OUTPUT = VOL_DIR / "page_order.json"

# book_page: printed page label as it appears in the book (Roman numeral for front matter,
# Arabic integer string for body, null for unnumbered pages).
# section: digitizer-addition | front-matter | body | end-matter
# corpus_role:
#   body         — encyclopedia article text; include in body corpus
#   front-matter — original printed front matter; include as named front-matter block
#   drop         — blank, digitizer addition, or library marking; exclude entirely
#   duplicate    — byte-identical to another file already in the manifest; exclude
LEAF_METADATA = {
    # --- Digitizer addition (not in the original printed book) ---
    "leaf_0000": {
        "book_page": None,
        "label": "Google Books digitization notice",
        "section": "digitizer-addition",
        "corpus_role": "drop",
    },
    # --- Front-matter blanks ---
    "leaf_0001": {
        "book_page": None,
        "label": "Blank",
        "section": "front-matter",
        "corpus_role": "duplicate",
        "duplicate_of": "page_0001",
    },
    "leaf_0002": {
        "book_page": None,
        "label": "Blank",
        "section": "front-matter",
        "corpus_role": "drop",
    },
    "leaf_0003": {
        "book_page": None,
        "label": "Blank",
        "section": "front-matter",
        "corpus_role": "duplicate",
        "duplicate_of": "page_0001",
    },
    "leaf_0004": {
        "book_page": None,
        "label": "Blank",
        "section": "front-matter",
        "corpus_role": "duplicate",
        "duplicate_of": "page_0001",
    },
    "leaf_0005": {
        "book_page": None,
        "label": "Blank (ink transfer from adjacent page)",
        "section": "front-matter",
        "corpus_role": "drop",
    },
    "leaf_0006": {
        "book_page": None,
        "label": "Blank",
        "section": "front-matter",
        "corpus_role": "drop",
    },
    "leaf_0007": {
        "book_page": None,
        "label": "Blank",
        "section": "front-matter",
        "corpus_role": "drop",
    },
    "leaf_0008": {
        "book_page": None,
        "label": "Blank",
        "section": "front-matter",
        "corpus_role": "drop",
    },
    # --- Book front matter (printed, unnumbered pages) ---
    "leaf_0009": {
        "book_page": None,
        "label": "Title page",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0010": {
        "book_page": None,
        "label": "Copyright page (Funk & Wagnalls, 1908)",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0011": {
        "book_page": None,
        "label": "Editorial staff (1/4) — Sherman, Gilmore, Beckwith, Carroll",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0012": {
        "book_page": None,
        "label": "Editorial staff (2/4) — Bousset, Brieger, Briggs, Buhl",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0013": {
        "book_page": None,
        "label": "Editorial staff (3/4) — Hoelscher, Hofmann, Jeremias",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0014": {
        "book_page": None,
        "label": "Editorial staff (4/4) — Pick, Price, Radlach, Rietschel, Rogge",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    # --- Preface (pp. ix-xxiv) — Roman numerals confirmed from running headers in OCR ---
    # leaf_0015 = p. ix inferred (one before p. x; no running header on section-opening pages)
    "leaf_0015": {
        "book_page": "ix",
        "label": "Preface, p. ix (opening page; book_page inferred from sequence)",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0016": {
        "book_page": "x",
        "label": "Preface, p. x",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0017": {
        "book_page": "xi",
        "label": "Preface, p. xi",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0018": {
        "book_page": "xii",
        "label": "Preface, p. xii",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0019": {
        "book_page": "xiii",
        "label": "Preface, p. xiii",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0020": {
        "book_page": "xiv",
        "label": "Preface, p. xiv",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0021": {
        "book_page": "xv",
        "label": "Preface, p. xv",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0022": {
        "book_page": "xvi",
        "label": "Preface, p. xvi",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0023": {
        "book_page": "xvii",
        "label": "Preface, p. xvii",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0024": {
        "book_page": "xviii",
        "label": "Preface, p. xviii",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0025": {
        "book_page": "xix",
        "label": "Preface, p. xix",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0026": {
        "book_page": "xx",
        "label": "Preface, p. xx",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0027": {
        "book_page": "xxi",
        "label": "Preface, p. xxi",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0028": {
        "book_page": "xxii",
        "label": "Preface, p. xxii",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0029": {
        "book_page": "xxiii",
        "label": "Preface, p. xxiii",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0030": {
        "book_page": "xxiv",
        "label": "Preface, p. xxiv",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    # --- Recent bibliography supplement (pp. xxv-xxvi) ---
    "leaf_0031": {
        "book_page": "xxv",
        "label": "Recent bibliography supplement, p. xxv",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0032": {
        "book_page": "xxvi",
        "label": "Recent bibliography supplement, p. xxvi",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    # --- Abbreviations key (pp. xxvii-xxix) ---
    "leaf_0033": {
        "book_page": "xxvii",
        "label": "Abbreviations key, p. xxvii",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0034": {
        "book_page": "xxviii",
        "label": "Abbreviations key, p. xxviii",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    "leaf_0035": {
        "book_page": "xxix",
        "label": "Abbreviations key, p. xxix",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    # --- Transliteration key (p. xxx) ---
    "leaf_0036": {
        "book_page": "xxx",
        "label": "Transliteration key, p. xxx",
        "section": "front-matter",
        "corpus_role": "front-matter",
    },
    # --- Body pages 1-9 (absent from the page_* sequence) ---
    "leaf_0037": {
        "book_page": "1",
        "label": "p. 1 — AACHEN, SYNODS OF (first body article)",
        "section": "body",
        "corpus_role": "body",
    },
    "leaf_0038": {
        "book_page": "2",
        "label": "p. 2 — Aaron; Abbey",
        "section": "body",
        "corpus_role": "body",
    },
    "leaf_0039": {
        "book_page": "3",
        "label": "p. 3 — Abbadie, Jacques (concl.); Abbey (cont.)",
        "section": "body",
        "corpus_role": "body",
    },
    "leaf_0040": {
        "book_page": "4",
        "label": "p. 4 — Abbey, monastery bibliography",
        "section": "body",
        "corpus_role": "body",
    },
    "leaf_0041": {
        "book_page": "5",
        "label": "p. 5 — Abbo; Abbot",
        "section": "body",
        "corpus_role": "body",
    },
    "leaf_0042": {
        "book_page": "6",
        "label": "p. 6 — Abbot, Robert; Abdias",
        "section": "body",
        "corpus_role": "body",
    },
    "leaf_0043": {
        "book_page": "7",
        "label": "p. 7 — Abbott, Jacob",
        "section": "body",
        "corpus_role": "body",
    },
    "leaf_0044": {
        "book_page": "8",
        "label": "p. 8 — Abdias (bibliography)",
        "section": "body",
        "corpus_role": "body",
    },
    "leaf_0045": {
        "book_page": "9",
        "label": "p. 9 — Abeel; Abelard",
        "section": "body",
        "corpus_role": "body",
    },
    # --- End matter ---
    "leaf_0535": {
        "book_page": None,
        "label": "Blank",
        "section": "end-matter",
        "corpus_role": "duplicate",
        "duplicate_of": "page_0001",
    },
    "leaf_0536": {
        "book_page": None,
        "label": "Blank",
        "section": "end-matter",
        "corpus_role": "drop",
    },
    "leaf_0537": {
        "book_page": None,
        "label": "Blank",
        "section": "end-matter",
        "corpus_role": "drop",
    },
    "leaf_0538": {
        "book_page": None,
        "label": "Blank",
        "section": "end-matter",
        "corpus_role": "duplicate",
        "duplicate_of": "page_0001",
    },
    "leaf_0539": {
        "book_page": None,
        "label": 'Library circulation stamp ("DOES NOT CIRCULATE")',
        "section": "end-matter",
        "corpus_role": "drop",
    },
    "leaf_0540": {
        "book_page": None,
        "label": "Blank",
        "section": "end-matter",
        "corpus_role": "duplicate",
        "duplicate_of": "page_0001",
    },
}

LEAF_FRONT_STEMS = [f"leaf_{n:04d}" for n in range(46)]   # leaf_0000..leaf_0045
LEAF_END_STEMS = [f"leaf_{n:04d}" for n in range(535, 541)]  # leaf_0535..leaf_0540


def _entry(seq: int, stem: str, meta: dict) -> dict:
    e = {
        "seq": seq,
        "file": stem + ".jpg",
        "book_page": meta["book_page"],
        "label": meta["label"],
        "section": meta["section"],
        "corpus_role": meta["corpus_role"],
        # All leaf_* files are present on disk (main() raises FileNotFoundError otherwise).
        "scan_status": "present",
    }
    if "duplicate_of" in meta:
        e["duplicate_of"] = meta["duplicate_of"]
    return e


def main() -> None:
    pages = []
    seq = 1

    # Load gap statuses from the manifest so phantom pages are correctly tagged.
    # Only non-resolved gaps are retained; resolved gaps behave like normal present pages.
    manifest = json.loads((MANIFEST_DIR / "vol_01.manifest.json").read_bytes())
    page_count: int = manifest["page_count"]
    gap_status: dict[int, str] = {
        g["page_num"]: g.get("status", "unresolved")
        for g in manifest.get("gaps", [])
        if isinstance(g.get("page_num"), int)
        and g["page_num"] <= page_count
        and g.get("status") != "resolved"
    }

    # Front matter + body pp. 1-9: leaf_0000 to leaf_0045
    for stem in LEAF_FRONT_STEMS:
        img = VOL_DIR / (stem + ".jpg")
        if not img.exists():
            raise FileNotFoundError(f"Expected image missing: {img}")
        pages.append(_entry(seq, stem, LEAF_METADATA[stem]))
        seq += 1

    # Body pp. 10-500: page_*.jpg files starting at page 10.
    # Pages 1-9 are already represented by leaf_0037-leaf_0045 above; skip any
    # page_*.jpg files covering those same printed pages to avoid duplicates.
    # Pages listed as phantom_duplicate/phantom_inversion in the manifest have wrong
    # content (IA scandata assigned the same leaf to two page numbers); mark them so
    # the OCR pipeline knows to skip them rather than process incorrect content.
    page_imgs = sorted(
        VOL_DIR.glob("page_*.jpg"),
        key=lambda p: int(p.stem.split("_")[1]),
    )
    for img_path in page_imgs:
        page_num = int(img_path.stem.split("_")[1])
        if page_num <= 9:
            continue  # pp. 1-9 already covered by leaf_0037-leaf_0045
        st = gap_status.get(page_num, "")
        if st in ("phantom_duplicate", "phantom_inversion"):
            scan_status = "phantom_duplicate"
        else:
            scan_status = "present"
        pages.append({
            "seq": seq,
            "file": img_path.name,
            "book_page": str(page_num),
            "label": f"p. {page_num}",
            "section": "body",
            "corpus_role": "body",
            "scan_status": scan_status,
        })
        seq += 1

    # End matter: leaf_0535 to leaf_0540
    for stem in LEAF_END_STEMS:
        img = VOL_DIR / (stem + ".jpg")
        if not img.exists():
            raise FileNotFoundError(f"Expected image missing: {img}")
        pages.append(_entry(seq, stem, LEAF_METADATA[stem]))
        seq += 1

    body_pages = [p for p in pages if p["corpus_role"] == "body"]
    front_pages = [p for p in pages if p["corpus_role"] == "front-matter"]
    drop_pages = [p for p in pages if p["corpus_role"] == "drop"]
    dup_pages = [p for p in pages if p["corpus_role"] == "duplicate"]

    from collections import Counter
    by_status = Counter(p.get("scan_status") for p in pages)

    result = {
        "schema": "page-order-v1",
        "volume": 1,
        "work": "New Schaff-Herzog Encyclopedia of Religious Knowledge",
        "generated": date.today().isoformat(),
        "total_pages": len(pages),
        "summary": {
            "body": len(body_pages),
            "front_matter": len(front_pages),
            "drop": len(drop_pages),
            "duplicate": len(dup_pages),
            "scan_present": by_status.get("present", 0),
            "scan_phantom_duplicate": by_status.get("phantom_duplicate", 0),
            "scan_unresolved": by_status.get("unresolved", 0),
        },
        "note": (
            "Canonical physical page sequence for vol_01. "
            "leaf_* files (52 total) are unique to this volume; vols 02-13 have page_* only. "
            "Six leaf_* files are byte-identical to page_0001 (all blank; corpus_role=duplicate). "
            "Body pages 1-9 are covered by leaf_0037-leaf_0045 (higher-quality scans); "
            "page_0001.jpg-page_0009.jpg also exist on disk but are intentionally skipped in this manifest. "
            "Preface page numbers (pp. x-xxiv) confirmed from OCR running headers; "
            "p. ix is inferred from position (no running header on section-opening pages). "
            "Pipeline should read this manifest instead of globbing page_*.jpg for vol_01."
        ),
        "pages": pages,
    }

    tmp = OUTPUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, OUTPUT)

    phantom_note = (
        f"  Phantom dup : {by_status['phantom_duplicate']} (wrong content -- IA scandata duplication)"
        if by_status.get("phantom_duplicate") else ""
    )
    print(f"Written: {OUTPUT}")
    print(f"  Total pages : {len(pages)}")
    print(f"  Body        : {len(body_pages)} (pp. 1-9 from leaf_0037-0045, pp. 10-500 from page_*)")
    print(f"  Front matter: {len(front_pages)}")
    print(f"  Drop        : {len(drop_pages)}")
    print(f"  Duplicate   : {len(dup_pages)}")
    if phantom_note:
        print(phantom_note)


if __name__ == "__main__":
    main()
