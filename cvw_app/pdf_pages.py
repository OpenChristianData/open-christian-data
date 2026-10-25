"""Bounded scan previews; MuPDF runs in a disposable process, never the server."""
from __future__ import annotations

import json
import subprocess
import sys

from cvw_app.renderer_nodes import RendererError

MAX_PDF_BYTES = 256 * 1024 * 1024
MAX_PDF_PAGES = 5000


def pdf_preview(payload: bytes, page: int | None = None) -> bytes:
    if len(payload) > MAX_PDF_BYTES:
        raise RendererError("This PDF exceeds the 256 MiB preview limit. Download the original file.")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "cvw_app.pdf_pages", "info" if page is None else str(page)],
            input=payload, capture_output=True, timeout=30, check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RendererError("PDF preview timed out. Download the original file.") from error
    if result.returncode:
        raise RendererError("PDF preview is unavailable. Download the original file.")
    if len(result.stdout) > 8 * 1024 * 1024:
        raise RendererError("PDF page preview exceeds the image limit.")
    return result.stdout


def pdf_page_count(payload: bytes) -> int:
    count = json.loads(pdf_preview(payload))["pages"]
    if type(count) is not int or not 1 <= count <= MAX_PDF_PAGES:
        raise RendererError("PDF page count exceeds the preview limit.")
    return count


def _main() -> None:
    import pymupdf

    payload = sys.stdin.buffer.read(MAX_PDF_BYTES + 1)
    if len(payload) > MAX_PDF_BYTES:
        raise ValueError("PDF input exceeds preview limit")
    with pymupdf.open(stream=payload, filetype="pdf") as document:
        if document.needs_pass or not 1 <= len(document) <= MAX_PDF_PAGES:
            raise ValueError("PDF is encrypted or has too many pages")
        if sys.argv[1] == "info":
            sys.stdout.buffer.write(json.dumps({"pages": len(document)}).encode())
            return
        page = int(sys.argv[1])
        if not 1 <= page <= len(document):
            raise ValueError("PDF page is out of range")
        leaf = document[page - 1]
        edge = max(leaf.rect.width, leaf.rect.height)
        if not 0 < edge < 100000:
            raise ValueError("PDF page dimensions are invalid")
        image = leaf.get_pixmap(matrix=pymupdf.Matrix(1800 / edge, 1800 / edge), alpha=False)
        sys.stdout.buffer.write(image.tobytes("png"))


if __name__ == "__main__":
    _main()
