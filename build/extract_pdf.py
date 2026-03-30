"""build/extract_pdf.py
Universal PDF-to-Markdown extraction script for the Open Christian Data pipeline.

Extracts text from a PDF using pymupdf4llm, runs quality checks, normalises
the Markdown, and writes clean output to raw/{source}/{id}/markdown/.

Usage:
    py -3 build/extract_pdf.py --source ccel --id treasury-of-david
    py -3 build/extract_pdf.py --source ccel --id treasury-of-david --dry-run
    py -3 build/extract_pdf.py --pdf raw/ccel/calvin-institutes/institutes.pdf
    py -3 build/extract_pdf.py --source ccel --id treasury-of-david --force

Design notes:
    - Archive.org OCR PDFs use GlyphLessFont with uniform 7-9pt sizes.
      IdentifyHeaders cannot distinguish headings by font size for these files.
      Auto-detection sets ignore_code=True for GlyphLessFont PDFs; heading
      structure is then driven by regex patterns in the source config.
    - For born-digital/typeset PDFs, IdentifyHeaders works normally.
    - No auto-OCR: image-only pages are flagged in the quality report.
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root is on sys.path so `from build.lib.X import Y` works
# when running as py -3 build/extract_pdf.py from the repo root.
_REPO_ROOT_FOR_PATH = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT_FOR_PATH) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_FOR_PATH))

import pymupdf
import pymupdf4llm
from pymupdf4llm.helpers.pymupdf_rag import IdentifyHeaders
from pymupdf4llm.helpers.pymupdf_rag import to_markdown as rag_to_markdown

# ---------------------------------------------------------------------------
# Repo layout
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_VERSION = "v1.0.0"
SCHEMA_VERSION = "2.1.0"

# Default extraction settings (overridden by config pdf_extraction block)
DEFAULT_BODY_LIMIT = None        # let IdentifyHeaders decide
DEFAULT_MAX_LEVELS = 4
DEFAULT_STRIP_HEADERS_FOOTERS = True
DRY_RUN_PAGES = 3                # pages to process in dry-run mode

# Font that signals archive.org OCR (GlyphLessFont = invisible text overlay)
GLYPH_LESS_FONT = "GlyphLessFont"

# Log file (Rule 3: same folder as script)
LOG_FILE = Path(__file__).with_suffix(".log")

# Output base dir (Rule 14); full path: RAW_OUTPUT_BASE/{source}/{id}/markdown/
RAW_OUTPUT_BASE = REPO_ROOT / "raw"


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(source: str, resource_id: str) -> dict:
    """
    Load sources/{type}/{id}/config.json.
    Tries commentaries, doctrinal_documents, devotionals, sermons in order.
    """
    for content_type in ("commentaries", "doctrinal_documents", "devotionals", "sermons"):
        config_path = REPO_ROOT / "sources" / content_type / resource_id / "config.json"
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(
        f"No config.json found for source={source!r} id={resource_id!r}. "
        f"Looked under sources/{{commentaries,doctrinal_documents,devotionals,sermons}}/{resource_id}/config.json"
    )


def get_pdf_config(config: dict) -> dict:
    """Return the pdf_extraction block from config, or an empty dict."""
    return config.get("pdf_extraction", {})


# ---------------------------------------------------------------------------
# PDF discovery
# ---------------------------------------------------------------------------

def find_pdfs(source: str, resource_id: str, pdf_config: dict) -> list:
    """
    Return a list of Path objects for PDFs to process.
    Priority: explicit pdf_files list in config > all *.pdf in raw_dir.
    """
    raw_dir_str = pdf_config.get("raw_dir", f"raw/{source}/{resource_id}")
    raw_dir = REPO_ROOT / raw_dir_str
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw directory not found: {raw_dir}")

    explicit = pdf_config.get("pdf_files", [])
    if explicit:
        paths = [raw_dir / fname for fname in explicit]
        missing = [p for p in paths if not p.exists()]
        if missing:
            raise FileNotFoundError(f"Configured PDF(s) not found: {missing}")
        return paths

    # Auto-discover
    paths = sorted(raw_dir.glob("*.pdf"))
    if not paths:
        raise FileNotFoundError(f"No *.pdf files found in {raw_dir}")
    return paths


# ---------------------------------------------------------------------------
# OCR font detection
# ---------------------------------------------------------------------------

def is_ocr_pdf(doc: pymupdf.Document, sample_pages: int = 10) -> bool:
    """
    Return True if the PDF uses GlyphLessFont (archive.org OCR invisible text overlay).
    Samples up to sample_pages pages with text content.
    """
    checked = 0
    for i in range(len(doc)):
        page = doc[i]
        if not page.get_text().strip():
            continue
        blocks = page.get_text("dict").get("blocks", [])
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    font = span.get("font", "")
                    if font == GLYPH_LESS_FONT:
                        return True
                    if font and font != GLYPH_LESS_FONT:
                        # Found a real font on this page -- not OCR
                        return False
        checked += 1
        if checked >= sample_pages:
            break
    return False


# ---------------------------------------------------------------------------
# Text layer detection
# ---------------------------------------------------------------------------

def check_text_layer(doc: pymupdf.Document) -> dict:
    """
    Check how many pages have a usable text layer.
    Returns a summary dict used by the quality gate and extraction report.
    """
    total = len(doc)
    empty_pages = []
    for i in range(total):
        text = doc[i].get_text().strip()
        if len(text) < 10:
            empty_pages.append(i + 1)   # 1-indexed for reporting
    return {
        "total_pages": total,
        "pages_with_text": total - len(empty_pages),
        "empty_pages": empty_pages,
    }


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def extract_pdf(
    pdf_path: Path,
    pdf_config: dict,
    dry_run: bool = False,
) -> tuple:
    """
    Extract a single PDF to a Markdown string.

    Returns (markdown_str, extraction_meta_dict).
    """
    body_limit = pdf_config.get("body_font_size_min", DEFAULT_BODY_LIMIT)
    max_levels = pdf_config.get("max_heading_levels", DEFAULT_MAX_LEVELS)

    print(f"  Opening: {pdf_path.name}")
    doc = pymupdf.open(str(pdf_path))
    total_pages = len(doc)
    print(f"  Pages: {total_pages}")

    # Text layer check
    text_info = check_text_layer(doc)
    pct_with_text = text_info["pages_with_text"] * 100 / total_pages if total_pages else 0
    print(f"  Text layer: {text_info['pages_with_text']}/{total_pages} pages ({pct_with_text:.0f}%)")

    if text_info["empty_pages"]:
        count = len(text_info["empty_pages"])
        sample = text_info["empty_pages"][:5]
        suffix = "..." if count > 5 else ""
        print(
            f"  WARNING: {count} pages have <10 chars "
            f"(pages {sample}{suffix}) -- may be image-only; no auto-OCR"
        )

    # OCR font detection
    ocr_mode = is_ocr_pdf(doc)
    if ocr_mode:
        print(f"  PDF type: OCR/scanned (GlyphLessFont detected) -- ignore_code=True")
    else:
        print(f"  PDF type: born-digital/typeset -- using IdentifyHeaders")

    # Build header info
    hdr_kwargs = {}
    if body_limit is not None:
        hdr_kwargs["body_limit"] = body_limit
    if max_levels is not None:
        hdr_kwargs["max_levels"] = max_levels
    hdr_info = IdentifyHeaders(doc, **hdr_kwargs)
    print(f"  Header sizes: body_limit={hdr_info.body_limit}, levels={list(hdr_info.header_id.keys())}")

    # Page selection
    if dry_run:
        pages = list(range(min(DRY_RUN_PAGES, total_pages)))
        print(f"  [dry-run] Processing first {len(pages)} pages only")
    else:
        pages = None   # all pages

    # Extract to Markdown
    extract_start = time.time()
    kwargs = dict(
        hdr_info=hdr_info,
        page_chunks=True,
        ignore_code=ocr_mode,
    )
    if pages is not None:
        kwargs["pages"] = pages

    print(f"  Extracting...", end="", flush=True)

    if pages is not None:
        chunks = rag_to_markdown(doc, **kwargs)
    else:
        # Process in batches of 50 pages, print progress every 10 pages
        chunks = []
        batch_size = 50
        total_to_process = total_pages
        processed = 0
        for batch_start in range(0, total_to_process, batch_size):
            batch_end = min(batch_start + batch_size, total_to_process)
            batch_pages = list(range(batch_start, batch_end))
            batch_chunks = rag_to_markdown(doc, pages=batch_pages, **kwargs)
            chunks.extend(batch_chunks)
            processed = batch_end
            if processed % 10 == 0 or processed == total_to_process:
                print(f"\r  Extracting... {processed}/{total_to_process} pages", end="", flush=True)

    print()
    elapsed = time.time() - extract_start

    # Join chunks to single Markdown string
    raw_markdown = "\n\n".join(
        chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
        for chunk in chunks
    )

    pages_processed = len(pages) if pages is not None else total_pages
    chars = len(raw_markdown)
    chars_per_page = chars / pages_processed if pages_processed else 0
    print(
        f"  Extracted {pages_processed} pages, {chars} chars, {elapsed:.1f}s "
        f"({chars_per_page:.0f} chars/page avg)"
    )

    # SHA-256 of source PDF
    pdf_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    extraction_meta = {
        "pdf_file": pdf_path.name,
        "pdf_hash_sha256": pdf_hash,
        "total_pages": total_pages,
        "pages_processed": pages_processed,
        "ocr_mode": ocr_mode,
        "body_limit": hdr_info.body_limit,
        "header_sizes": list(hdr_info.header_id.keys()),
        "text_layer": text_info,
        "extraction_elapsed_s": round(elapsed, 2),
        "raw_chars": chars,
        "processing_script_version": f"build/extract_pdf.py@{SCRIPT_VERSION}",
        "processing_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    doc.close()
    return raw_markdown, extraction_meta


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process_one_pdf(
    source: str,
    resource_id: str,
    pdf_path: Path,
    pdf_config: dict,
    config: dict,
    dry_run: bool,
    force: bool,
) -> dict:
    """Run extraction + quality gate + normalizer for one PDF. Returns report dict."""
    from build.lib.pdf_quality_gate import run_quality_gate
    from build.lib.pdf_normalizer import normalise

    print(f"\n--- {pdf_path.name} ---")

    # Output paths
    md_dir = REPO_ROOT / "raw" / source / resource_id / "markdown"
    md_file = md_dir / (pdf_path.stem + ".md")
    report_file = md_dir / "_extraction_report.json"

    if md_file.exists() and not force and not dry_run:
        print(f"  Already exists: {md_file.name}  (use --force to re-extract)")
        return {}

    # Extract
    raw_markdown, extraction_meta = extract_pdf(pdf_path, pdf_config, dry_run=dry_run)

    # Quality gate (never blocks -- returns warnings)
    qg_warnings = run_quality_gate(raw_markdown, extraction_meta, pdf_config)
    if qg_warnings:
        print(f"  Quality gate: {len(qg_warnings)} warning(s)")
        for w in qg_warnings:
            print(f"    WARNING: {w}")
    else:
        print(f"  Quality gate: OK (0 warnings)")

    # Normaliser
    clean_markdown = normalise(raw_markdown, pdf_config)
    reduction = (len(raw_markdown) - len(clean_markdown)) * 100 / len(raw_markdown) if raw_markdown else 0
    print(f"  Normaliser: {len(clean_markdown)} chars ({reduction:.1f}% reduction)")

    if dry_run:
        print()
        print("  [dry-run] First 1000 chars of clean Markdown:")
        print("  " + "-" * 60)
        for line in clean_markdown[:1000].split("\n"):
            print(f"  {line}")
        print("  " + "-" * 60)
        print()
        print(f"  [dry-run] Would write to: {md_file}")
        return {
            "pdf_file": pdf_path.name,
            "dry_run": True,
            "quality_warnings": qg_warnings,
            "extraction_meta": extraction_meta,
        }

    # Write Markdown
    md_dir.mkdir(parents=True, exist_ok=True)
    with open(md_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(clean_markdown)
    size_kb = md_file.stat().st_size / 1024
    print(f"  Wrote: {md_file.name} ({size_kb:.0f} KB)")

    # Write extraction report
    report = {
        "resource_id": resource_id,
        "source": source,
        "extraction_meta": extraction_meta,
        "quality_warnings": qg_warnings,
        "normaliser_output_chars": len(clean_markdown),
        "schema_version": SCHEMA_VERSION,
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    with open(report_file, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"  Wrote: {report_file.name}")

    return report


# ---------------------------------------------------------------------------
# Log tee (writes every print() to stdout + LOG_FILE simultaneously)
# ---------------------------------------------------------------------------

class _TeeWriter:
    """Duplicate stdout writes to an open log file."""
    def __init__(self, stdout, log_file):
        self._stdout = stdout
        self._log = log_file

    def write(self, data: str) -> None:
        self._stdout.write(data)
        self._log.write(data)

    def flush(self) -> None:
        self._stdout.flush()
        self._log.flush()

    def fileno(self) -> int:
        return self._stdout.fileno()

    def isatty(self) -> bool:
        return self._stdout.isatty()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    """Entry point: sets up log tee then delegates to _run()."""
    with open(LOG_FILE, "a", encoding="utf-8") as _lf:
        _lf.write(
            f"\n=== {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} ===\n"
        )
        _orig = sys.stdout
        sys.stdout = _TeeWriter(_orig, _lf)
        try:
            _run(args)
        finally:
            sys.stdout = _orig


def _run(args: argparse.Namespace) -> None:
    start_time = time.time()

    # -- Ad-hoc single file mode --
    if args.pdf:
        pdf_path = Path(args.pdf)
        if not pdf_path.is_absolute():
            pdf_path = REPO_ROOT / pdf_path
        if not pdf_path.exists():
            print(f"ERROR: PDF not found: {pdf_path}")
            sys.exit(1)
        # No config for ad-hoc mode
        pdf_config = {}
        config = {"resource_id": pdf_path.stem}
        source = "adhoc"
        resource_id = pdf_path.stem

        from build.lib.pdf_quality_gate import run_quality_gate
        from build.lib.pdf_normalizer import normalise

        try:
            raw_md, meta = extract_pdf(pdf_path, pdf_config, dry_run=args.dry_run)
            warnings = run_quality_gate(raw_md, meta, pdf_config)
            clean_md = normalise(raw_md, pdf_config)
        except Exception as exc:
            print(f"ERROR: extraction failed: {exc}")
            sys.exit(1)
        print(f"\nExtraction complete: {len(clean_md)} chars, {len(warnings)} warning(s)")
        if args.dry_run:
            print("\nFirst 800 chars:")
            print(clean_md[:800])
        return

    # -- Source + ID mode --
    if not args.source or not args.id:
        print("ERROR: provide --source and --id, or --pdf")
        sys.exit(1)

    source = args.source.lower()
    resource_id = args.id.lower()

    # Load config
    try:
        config = load_config(source, resource_id)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    pdf_config = get_pdf_config(config)
    title = config.get("title", resource_id)
    print(f"Resource: {title}")
    print(f"Source:   {source}")
    print(f"ID:       {resource_id}")
    if args.dry_run:
        print(f"Mode:     dry-run (first {DRY_RUN_PAGES} pages per PDF, no write)")
    print()

    # Find PDFs
    try:
        pdf_paths = find_pdfs(source, resource_id, pdf_config)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    print(f"PDFs found: {len(pdf_paths)}")
    for p in pdf_paths:
        size_mb = p.stat().st_size / 1024 / 1024
        print(f"  {p.name} ({size_mb:.1f} MB)")

    reports = []
    errors = 0
    for pdf_path in pdf_paths:
        try:
            report = process_one_pdf(
                source, resource_id, pdf_path, pdf_config, config,
                dry_run=args.dry_run, force=args.force,
            )
            reports.append(report)
        except Exception as exc:
            print(f"  ERROR: {pdf_path.name} failed: {exc}")
            reports.append({"pdf_file": pdf_path.name, "error": str(exc)})
            errors += 1

    # Summary
    elapsed = time.time() - start_time
    total_warnings = sum(len(r.get("quality_warnings", [])) for r in reports if r)
    print()
    print(
        f"=== DONE: {len(pdf_paths)} PDF(s), {errors} error(s), "
        f"{total_warnings} quality warning(s), {elapsed:.1f}s ==="
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract PDFs to clean Markdown for the OCD pipeline"
    )
    parser.add_argument("--source", metavar="SRC", help="Source name (e.g. ccel)")
    parser.add_argument("--id", metavar="ID", help="Resource ID (e.g. treasury-of-david)")
    parser.add_argument("--pdf", metavar="PATH", help="Ad-hoc single PDF file path")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=f"Process first {DRY_RUN_PAGES} pages only, print stats, do not write files",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract even if output Markdown already exists",
    )
    args = parser.parse_args()

    if not args.pdf and not (args.source and args.id):
        parser.print_help()
        sys.exit(1)

    run(args)


if __name__ == "__main__":
    main()
