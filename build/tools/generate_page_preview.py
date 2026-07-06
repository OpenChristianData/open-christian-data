"""Generate a self-contained HTML preview of per-page OCR sidecars alongside the source scan.

Usage:
    py -3 build/tools/generate_page_preview.py --volume 1 --pages 10,60,110,160,210,260,310,360,410,460
    py -3 build/tools/generate_page_preview.py --volume 1  # all pages with sidecars

Output: review/schaff_vol<N>_preview.html  (self-contained, inline images as base64)
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from html import escape
from pathlib import Path

from PIL import Image as _PILImage

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

RAW_PAGES = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
REVIEW_DIR = REPO_ROOT / "review"


def _conf_class(conf: float) -> str:
    return "conf-hi" if conf >= 90 else "conf-lo"


def _read_sidecar(path: Path) -> tuple[str, float, int]:
    d = json.loads(path.read_text(encoding="utf-8"))
    text = d.get("raw_text") or d.get("text", "")
    conf = float(d.get("confidence_mean", 0))
    blocks = len(d.get("blocks", []))
    return text, conf, blocks


CSS = """
body { font-family: sans-serif; margin: 0; background: #1a1a1a; color: #e0e0e0; }
h1 { padding: 1rem 1.5rem; background: #111; margin: 0; font-size: 1.1rem; color: #ccc; }
.nav { padding: .5rem 1.5rem; background: #111; border-top: 1px solid #333; }
.nav a { color: #7ab; margin-right: 1rem; font-size: .85rem; text-decoration: none; }
.nav a:hover { text-decoration: underline; }
.page-block { border-top: 3px solid #444; padding: 1rem 1.5rem; }
.page-block h2 { margin: 0 0 .75rem; font-size: 1rem; color: #aaa; }
.columns-2 { display: grid; grid-template-columns: 420px 1fr 1fr; gap: 1rem; align-items: start; }
.columns-4 { display: grid; grid-template-columns: 420px 1fr 1fr 1fr 1fr; gap: 1rem; align-items: start; }
.col-img img { width: 100%; border: 1px solid #555; display: block; }
.col-label { font-size: .75rem; color: #888; margin-bottom: .25rem; }
.conf { display: inline-block; padding: .1rem .4rem; border-radius: 3px;
        font-size: .72rem; font-weight: bold; margin-left: .5rem; }
.conf-hi { background: #1a4a1a; color: #6f6; }
.conf-lo { background: #4a2a1a; color: #f96; }
.conf-na { background: #2a2a2a; color: #888; }
pre { font-family: "Courier New", monospace; font-size: .72rem; line-height: 1.45;
      background: #111; border: 1px solid #333; padding: .6rem; margin: 0;
      white-space: pre-wrap; word-break: break-word; max-height: 640px; overflow-y: auto; }
"""

# Engine display metadata: (sidecar_suffix, label)
_ENGINE_META = [
    ("oss-tesseract", "Tesseract 5.5 PSM=1"),
    ("azure", "Azure Image Analysis v4.0"),
    ("gcv", "Google Cloud Vision"),
    ("textract", "AWS Textract"),
]


def build_html(pages: list[tuple], engines: list[str]) -> str:
    """Build HTML preview.

    pages: list of (page_num, img_b64, {engine: (text, conf, blocks)})
    engines: ordered list of engine suffixes present
    """
    nav = "".join(f'<a href="#p{p:04d}">p.{p}</a> ' for p, *_ in pages)
    col_class = "columns-4" if len(engines) > 2 else "columns-2"

    blocks = []
    for page_data in pages:
        p, img_b64, eng_data = page_data
        conf_spans = ""
        for suffix, label in _ENGINE_META:
            if suffix not in engines:
                continue
            txt, conf, blks = eng_data.get(suffix, ("", 0.0, 0))
            cls = _conf_class(conf) if conf > 0 else "conf-na"
            short = label.split()[0]
            conf_spans += f'<span class="conf {cls}">{short} {conf:.1f}%</span>'

        eng_cols = ""
        for suffix, label in _ENGINE_META:
            if suffix not in engines:
                continue
            txt, conf, blks = eng_data.get(suffix, ("", 0.0, 0))
            words = len(txt.split()) if txt else 0
            placeholder = "<em style='color:#555'>no sidecar</em>" if not txt else escape(txt)
            eng_cols += (
                f'    <div class="col-ocr">\n'
                f'      <div class="col-label">{escape(label)} &mdash; {words} words</div>\n'
                f'      <pre>{placeholder}</pre>\n'
                f'    </div>\n'
            )

        block = (
            f'<div class="page-block" id="p{p:04d}">\n'
            f'  <h2>Page {p} {conf_spans}</h2>\n'
            f'  <div class="{col_class}">\n'
            f'    <div class="col-img"><img src="data:image/jpeg;base64,{img_b64}" alt="page {p}"></div>\n'
            + eng_cols
            + f'  </div>\n</div>\n'
        )
        blocks.append(block)

    eng_labels = " + ".join(
        label for suffix, label in _ENGINE_META if suffix in engines
    )
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<title>Schaff-Herzog OCR Preview</title>\n'
        f'<style>{CSS}</style>\n'
        '</head>\n<body>\n'
        f'<h1>Schaff-Herzog Vol 1 &mdash; OCR Preview'
        f' &nbsp;<small style="color:#666">{escape(eng_labels)}</small></h1>\n'
        f'<div class="nav">{nav}</div>\n'
        + "".join(blocks)
        + '</body>\n</html>\n'
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--volume", type=int, required=True)
    ap.add_argument(
        "--pages",
        default="all",
        help="Comma-separated page numbers, or 'all' for every page with any sidecar",
    )
    ap.add_argument(
        "--engines",
        default="oss-tesseract,azure,gcv,textract",
        help="Comma-separated engine suffixes to include (default: all four)",
    )
    args = ap.parse_args()

    vol_dir = RAW_PAGES / f"vol_{args.volume:02d}"
    if not vol_dir.exists():
        raise SystemExit(f"Vol dir not found: {vol_dir}")

    engines = [e.strip() for e in args.engines.split(",")]

    if args.pages == "all":
        jpegs = sorted(vol_dir.glob("page_*.jpg"))
        page_nums = [int(j.stem.split("_")[1]) for j in jpegs]
    else:
        page_nums = sorted(int(x.strip()) for x in args.pages.split(","))

    # Require at least Tesseract sidecar to include a page; other engines optional.
    primary_engine = engines[0] if engines else "oss-tesseract"

    pages = []
    skipped = []
    for p in page_nums:
        jpeg = vol_dir / f"page_{p:04d}.jpg"
        primary_sidecar = vol_dir / f"page_{p:04d}.{primary_engine}.json"
        if not jpeg.exists() or not primary_sidecar.exists():
            skipped.append(p)
            continue
        img = _PILImage.open(jpeg)
        img.thumbnail((900, 1400), _PILImage.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        eng_data: dict = {}
        for suffix in engines:
            path = vol_dir / f"page_{p:04d}.{suffix}.json"
            if path.exists():
                text, conf, blks = _read_sidecar(path)
                eng_data[suffix] = (text, conf, blks)

        pages.append((p, img_b64, eng_data))

    if skipped:
        print(f"Skipped {len(skipped)} pages (missing jpeg or primary sidecar): {skipped[:10]}")
    if not pages:
        raise SystemExit("No pages to render.")

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out = REVIEW_DIR / f"schaff_vol{args.volume:02d}_preview.html"
    out.write_text(build_html(pages, engines), encoding="utf-8")
    size_kb = out.stat().st_size // 1024
    print(f"Written {len(pages)} pages -> {out}  ({size_kb} KB)")


if __name__ == "__main__":
    main()
