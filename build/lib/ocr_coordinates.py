"""hOCR coordinate reader and JSON sidecar reader for OCR-disagreement rendering.

Parses hOCR HTML files (Internet Archive _hocr.html output) and per-page OCR
sidecar JSON files, exposing lookup interfaces for matching a text snippet to
its bounding box on a page.

Public surface:
    read_hocr(path)             -> {(page, line_id): {bbox, text, confidence}}
    lookup_bbox(coords, page, text_snippet, max_levenshtein=3)
                                -> bbox tuple or None

    read_json_sidecar(path)     -> list[dict]   (word-level records)
    lookup_word_bbox(words, text_snippet, max_levenshtein=2)
                                -> (x, y, w, h) or None

Polygon availability per engine (as of format_version=1):
    Tesseract  word: axis-aligned bbox only (no polygon)
    Azure AI   word, line: bbox + bbox_polygon. Block-level polygon absent.
    GCV        word: bbox + bbox_polygon. Lines are reconstructed from word
                     geometry — no native line polygon. Block-level polygon present.
    Textract   word, line: bbox + bbox_polygon (converted from normalized).
                     Block-level polygon absent (Textract has no native block grouping).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class HocrLine:
    page: int
    line_id: str
    bbox: tuple[int, int, int, int]
    text: str
    confidence: float


def _parse_title_attr(title: str) -> dict[str, str]:
    """hOCR encodes geometry in the title attribute as semicolon-separated
    key+args, e.g. 'bbox 100 200 300 400; x_wconf 92'."""
    parts: dict[str, str] = {}
    for chunk in title.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        head, _, tail = chunk.partition(" ")
        parts[head] = tail
    return parts


def _bbox_from_title(title: str) -> tuple[int, int, int, int] | None:
    parts = _parse_title_attr(title)
    bbox_str = parts.get("bbox")
    if not bbox_str:
        return None
    coords = bbox_str.split()
    if len(coords) != 4:
        return None
    try:
        x1, y1, x2, y2 = (int(c) for c in coords)
    except ValueError:
        return None
    return (x1, y1, x2 - x1, y2 - y1)


def _confidence_from_title(title: str) -> float:
    parts = _parse_title_attr(title)
    wconf = parts.get("x_wconf")
    if wconf is None:
        return 0.0
    try:
        return float(wconf.split()[0])
    except (ValueError, IndexError):
        return 0.0


def _page_from_title(title: str) -> int | None:
    parts = _parse_title_attr(title)
    ppageno = parts.get("ppageno")
    if ppageno is None:
        return None
    try:
        return int(ppageno.split()[0]) + 1
    except (ValueError, IndexError):
        return None


class _HocrParser(HTMLParser):
    """Lightweight hOCR parser. Picks out ocr_page / ocr_line / ocrx_word
    boundaries and accumulates per-line text. Robust to nested word tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[HocrLine] = []
        self._page: int = 0
        self._line_id: str | None = None
        self._line_bbox: tuple[int, int, int, int] | None = None
        self._line_confs: list[float] = []
        self._line_text_parts: list[str] = []
        self._in_word: bool = False
        self._word_conf: float = 0.0
        self._depth_word: int = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        cls = a.get("class", "")
        title = a.get("title", "")
        if "ocr_page" in cls.split():
            page = _page_from_title(title)
            if page is not None:
                self._page = page
        elif "ocr_line" in cls.split() or "ocrx_line" in cls.split():
            self._flush_line()
            self._line_id = a.get("id") or f"line_{len(self.lines)}"
            self._line_bbox = _bbox_from_title(title)
            self._line_confs = []
            self._line_text_parts = []
        elif "ocrx_word" in cls.split():
            self._in_word = True
            self._depth_word = 1
            self._word_conf = _confidence_from_title(title)
        elif self._in_word and tag.lower() == "span":
            # nested span inside a word — track depth to know when word ends
            self._depth_word += 1

    def handle_endtag(self, tag: str) -> None:
        if self._in_word:
            self._depth_word -= 1
            if self._depth_word <= 0:
                self._in_word = False
                self._line_confs.append(self._word_conf)
                self._depth_word = 0

    def handle_data(self, data: str) -> None:
        if self._in_word:
            self._line_text_parts.append(data)
            return
        if self._line_id is not None and data.strip():
            # whitespace between words within a line
            self._line_text_parts.append(data)

    def close(self) -> None:
        super().close()
        self._flush_line()

    def _flush_line(self) -> None:
        if self._line_id is None or self._line_bbox is None:
            return
        text = "".join(self._line_text_parts).strip()
        if not text:
            self._line_id = None
            return
        confidence = (sum(self._line_confs) / len(self._line_confs)) if self._line_confs else 0.0
        self.lines.append(
            HocrLine(
                page=self._page,
                line_id=self._line_id,
                bbox=self._line_bbox,
                text=text,
                confidence=confidence,
            )
        )
        self._line_id = None
        self._line_bbox = None
        self._line_confs = []
        self._line_text_parts = []


def read_hocr(path: str | Path) -> dict[tuple[int, str], dict]:
    """Parse an hOCR HTML file and return a dict keyed by (page, line_id)."""
    text = Path(path).read_text(encoding="utf-8")
    parser = _HocrParser()
    parser.feed(text)
    parser.close()
    return {
        (line.page, line.line_id): {
            "bbox": line.bbox,
            "text": line.text,
            "confidence": line.confidence,
        }
        for line in parser.lines
    }


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def _min_window_levenshtein(snippet: str, text: str) -> int:
    if not snippet:
        return 0
    if len(text) < len(snippet):
        return _levenshtein(snippet, text)
    window_len = len(snippet)
    return min(
        _levenshtein(snippet, text[start : start + window_len])
        for start in range(len(text) - window_len + 1)
    )


def lookup_bbox(
    coords: dict[tuple[int, str], dict],
    page: int,
    text_snippet: str,
    max_levenshtein: int = 3,
) -> tuple[int, int, int, int] | None:
    """Find the bounding box for a text snippet on a given page.

    Exact substring match is tried first; falls back to Levenshtein within
    `max_levenshtein` against any line on the page.
    """
    snippet = text_snippet.strip()
    if not snippet:
        return None
    page_lines = [(key, value) for key, value in coords.items() if key[0] == page]
    # Exact substring match
    for _, line in page_lines:
        if snippet in line["text"]:
            return line["bbox"]
    # Fuzzy: pick the line with smallest Levenshtein under threshold
    best: tuple[int, tuple[int, int, int, int]] | None = None
    for _, line in page_lines:
        d = _min_window_levenshtein(snippet, line["text"])
        if d <= max_levenshtein and (best is None or d < best[0]):
            best = (d, line["bbox"])
    return best[1] if best else None


def iter_lines(coords: dict[tuple[int, str], dict]) -> Iterator[tuple[int, str, dict]]:
    for (page, line_id), value in coords.items():
        yield page, line_id, value


# ---------------------------------------------------------------------------
# JSON sidecar reader (per-page .oss-tesseract.json / .azure.json / .gcv.json)
# ---------------------------------------------------------------------------

class ThinSidecarError(ValueError):
    """Raised when a sidecar lacks word-level geometry (legacy thin format)."""


def read_json_sidecar(path: str | Path) -> list[dict]:
    """Read a per-page OCR sidecar JSON and return a flat list of word records.

    Each record:
        text         str
        bbox         (x, y, w, h) in absolute pixels
        bbox_polygon list[{x, y}] or absent if the engine doesn't provide polygons
        confidence   float (0-100)
        block_idx    int
        line_idx     int
        word_idx     int

    Raises ThinSidecarError if the sidecar carries text but no `blocks` field —
    distinguishes a legacy thin sidecar from a valid page with no recognised
    words (which returns []).
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "blocks" not in data and (data.get("raw_text") or data.get("text")):
        raise ThinSidecarError(
            f"{path}: sidecar has text but no `blocks` field "
            "(legacy thin format — re-OCR with current driver to get word geometry)"
        )
    words: list[dict] = []
    for bi, block in enumerate(data.get("blocks", [])):
        for li, line in enumerate(block.get("lines", [])):
            for wi, word in enumerate(line.get("words", [])):
                raw_bbox = word.get("bbox")
                if raw_bbox is None:
                    continue
                record: dict = {
                    "text": word.get("text", ""),
                    "bbox": (raw_bbox["x"], raw_bbox["y"], raw_bbox["w"], raw_bbox["h"]),
                    "confidence": word.get("confidence", 0.0),
                    "block_idx": bi,
                    "line_idx": li,
                    "word_idx": wi,
                }
                if "bbox_polygon" in word:
                    record["bbox_polygon"] = word["bbox_polygon"]
                words.append(record)
    return words


def lookup_word_bbox(
    words: list[dict],
    text_snippet: str,
    max_levenshtein: int = 2,
    min_substring_len: int = 4,
    min_fuzzy_len: int = 4,
) -> tuple[int, int, int, int] | None:
    """Find the first word bbox matching text_snippet.

    Three passes, in order:
        1. Exact equality (any length)
        2. Substring match (only when len(snippet) >= min_substring_len)
        3. Levenshtein <= max_levenshtein (only when len(snippet) >= min_fuzzy_len)

    Short queries ("in", "the", "De") only succeed via exact-equality — substring
    and fuzzy are disabled because at length 2-3 a single edit or any
    embedding produces too many false positives (e.g. "in" matching "within").
    """
    snippet = text_snippet.strip()
    if not snippet:
        return None

    # Pass 1: exact equality — always tried, wins over substring/fuzzy.
    for word in words:
        if snippet == word["text"]:
            return word["bbox"]

    # Pass 2: substring — only safe for longer snippets.
    if len(snippet) >= min_substring_len:
        for word in words:
            if snippet in word["text"]:
                return word["bbox"]

    # Pass 3: Levenshtein fuzzy — gated on length so short tokens don't
    # match arbitrary nearby words.
    if len(snippet) >= min_fuzzy_len:
        best: tuple[int, tuple[int, int, int, int]] | None = None
        for word in words:
            d = _levenshtein(snippet, word["text"])
            if d <= max_levenshtein and (best is None or d < best[0]):
                best = (d, word["bbox"])
        if best:
            return best[1]

    return None
