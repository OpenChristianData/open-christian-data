"""Render a TEI IR through the verification viewer: assert the DOM, then screenshot it.

Three instruments verify a TEI, and they catch different things:
  1. lxml probes of the XML       -- the artifact's content; blind to rendering.
  2. rendered-DOM assertions here -- what the viewer actually produces. Catches
     CETEIcean failing to upgrade custom elements, which an XML probe cannot see
     and a screenshot can easily look plausible through.
  3. the screenshot               -- the human-inspectable artifact; the only one
     that catches unknown-unknowns (layout collapse, garbled encoding).

This tool does (2) and (3). It fails loudly on a broken render rather than
writing a screenshot that merely looks fine.

Scope, established by seeded-failure tests (2026-07-15): the render check catches
structural catastrophe -- nothing upgraded, zero paragraphs, a note ref resolving
to no rendered id (seeding a bad target does fail the run). It does NOT catch
silent count drift: deleting one note dropped end_notes 183 -> 182 and still
passed, because expected counts are the census gate's job, not this tool's. Do not
treat a green render check as evidence that nothing was dropped.

The viewer loads TEI via fetch(), so a file:// URL fails same-origin checks --
the bounded localhost server is required, not a convenience.

Usage:
    py -3 build/tools/tei_viewer_screenshot.py ir/calvin/calvins-institutes.gutenberg.tei.xml
    py -3 build/tools/tei_viewer_screenshot.py ir/ccel/*.tei.xml --scroll-to "distinctive body sentence"

Writes <work>.viewer.png beside each TEI and prints per-work render stats.
Reading the PNG afterwards is still part of the verification; producing it is not.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
import socketserver
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_PLAYWRIGHT_ROOT = Path.home() / "AppData" / "Local" / "ms-playwright"

# Rendered-DOM invariants. A TEI can be schema-valid and still render wrong:
# CETEIcean may fail to upgrade its custom elements, or a note ref may point at
# an id that exists in the XML but never reaches the DOM.
_RENDER_PROBE = """() => {
  const q = (s) => [...document.querySelectorAll(s)];
  const ids = new Set(q('[*|id]').map(e => e.getAttribute('xml:id')).filter(Boolean));
  const refs = q('tei-ref[type="note"]');
  return {
    paragraphs: q('tei-p').length,
    note_refs: refs.length,
    end_notes: q('tei-note[place="end"]').length,
    dangling_refs: refs.filter(r => {
      const t = (r.getAttribute('target') || '').replace(/^#/, '');
      return t && !ids.has(t);
    }).length,
    elements_upgraded: !!customElements.get('tei-p'),
  };
}"""


class RenderCheckError(RuntimeError):
    """The viewer rendered the TEI wrongly -- a screenshot alone would have hidden this."""


def _sync_playwright():
    """Prefer upstream Playwright; fall back to the patchright fork if that's what's installed.

    Patchright is a stealth fork for evading bot detection while scraping -- its
    patches buy nothing against a localhost page we serve ourselves, and it trails
    upstream. The API is identical, so prefer the purpose-built library when present.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        from patchright.sync_api import sync_playwright
    return sync_playwright


def _chromium_path() -> str | None:
    """Newest installed Chromium, or None to use the library's own resolution."""
    candidates = sorted(_PLAYWRIGHT_ROOT.glob("chromium-*/chrome-win64/chrome.exe"))
    return str(candidates[-1]) if candidates else None


@contextlib.contextmanager
def _serve(root: Path, port: int):
    """Serve `root` on 127.0.0.1:port for the life of the context."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    # Bind explicitly to 127.0.0.1: on Windows, "localhost" can resolve to ::1
    # and miss an IPv4-only listener.
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        httpd.allow_reuse_address = True
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            httpd.shutdown()


def screenshot(
    tei_paths: list[Path],
    port: int = 8931,
    full_page: bool = False,
    scroll_to: str | None = None,
    suffix: str = ".viewer",
) -> list[Path]:
    sync_playwright = _sync_playwright()

    written: list[Path] = []
    failures: list[str] = []
    with _serve(REPO_ROOT, port) as base:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=_chromium_path(), headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 1800})
            try:
                for tei in tei_paths:
                    resolved = tei.resolve()
                    rel = resolved.relative_to(REPO_ROOT).as_posix()
                    page.goto(f"{base}/viewer/index.html?file=../{rel}", wait_until="networkidle")
                    # CETEIcean registers custom elements after fetch; the status
                    # line is the viewer's own signal that the document rendered.
                    page.wait_for_selector("text=Loaded", timeout=30_000)

                    stats = page.evaluate(_RENDER_PROBE)
                    print(
                        f"{resolved.name}: paragraphs={stats['paragraphs']} "
                        f"note_refs={stats['note_refs']} end_notes={stats['end_notes']} "
                        f"dangling_refs={stats['dangling_refs']} "
                        f"upgraded={stats['elements_upgraded']}"
                    )
                    if not stats["elements_upgraded"]:
                        failures.append(f"{resolved.name}: CETEIcean did not upgrade tei-* elements")
                    if stats["paragraphs"] == 0:
                        failures.append(f"{resolved.name}: zero paragraphs rendered")
                    if stats["dangling_refs"]:
                        failures.append(
                            f"{resolved.name}: {stats['dangling_refs']} note ref(s) resolve to "
                            "no rendered xml:id"
                        )

                    if scroll_to:
                        # A top-of-document viewport shot proves the file renders, not
                        # that a specific region is right. Scroll to the region under
                        # review so the screenshot shows the thing being verified.
                        page.get_by_text(scroll_to, exact=False).first.scroll_into_view_if_needed(
                            timeout=30_000
                        )
                    out = resolved.with_suffix("").with_suffix(f"{suffix}.png")
                    page.screenshot(path=str(out), full_page=full_page)
                    written.append(out)
                    print(f"wrote {out.relative_to(REPO_ROOT).as_posix()}")
            finally:
                browser.close()
    if failures:
        raise RenderCheckError("; ".join(failures))
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tei", nargs="+", type=Path, help="TEI file(s) to render")
    parser.add_argument("--port", type=int, default=8931)
    parser.add_argument("--full-page", action="store_true", help="capture the whole document")
    parser.add_argument(
        "--scroll-to",
        metavar="TEXT",
        help="scroll to the first element containing TEXT before capturing, so the shot "
        "shows the region under review rather than the top of the document",
    )
    parser.add_argument(
        "--suffix",
        default=".viewer",
        help="filename suffix before .png (default: .viewer); use e.g. .viewer-book3 for "
        "a region shot you don't want overwriting the canonical one",
    )
    args = parser.parse_args(argv)

    missing = [p for p in args.tei if not p.exists()]
    if missing:
        print(f"ERROR: not found: {', '.join(str(p) for p in missing)}", file=sys.stderr)
        return 1

    try:
        screenshot(
            args.tei,
            port=args.port,
            full_page=args.full_page,
            scroll_to=args.scroll_to,
            suffix=args.suffix,
        )
    except RenderCheckError as exc:
        print(f"RENDER CHECK FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
