"""R7 ABBYY leaf-alignment + content verification (PIPE-29 bulk-offset oracle).

ABBYY is an ALTERNATE-SOURCE OCR (a different IA scan than the primary images),
so it can never SHA-match a primary leaf -- it must be ALIGNED onto the primary
``leaf_num`` coordinate, not reused by content hash (design SS6).

The rich sidecars are named by the primary stem (``page_0010.ia-abbyy.json``) and
joined by that stem. That mapping is *implicit and unverified*: a wrong
front-matter offset silently mis-maps ABBYY text onto the wrong leaf (the PIPE-29
failure class). This module makes the alignment explicit and content-verified:

  For each page, parse the printed page number from the running header (the DATA --
  PIPE-29 says the data is primary, the ``page_num`` scandata field is secondary)
  and compare it to the canonical manifest's ``page_num`` for the leaf the stem
  resolves to. A SUSTAINED constant offset across a contiguous run is a
  misalignment by that offset; ISOLATED mismatches are OCR noise (Codex#3 OQ4 --
  this is a bulk offset oracle, not a per-page proof).

The module is pure (no file I/O in ``compute_alignment``) so the oracle is
unit-testable; ``align_lineage_volume`` is the thin file-driven wrapper.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[3]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.nsh_leaf_model import canonical_leaf_id, leaves_view  # noqa: E402
from build.lib.page_order import volume_sidecar_files  # noqa: E402

# A bare integer of 1-4 digits is a plausible printed page number. Page numbers
# sit at the start (recto) or end (verso) of the running-header band, so only the
# first/last few lines are searched -- a numeral deep in the body is article text.
_HEADER_SCAN_LINES = 4
_BARE_INT = re.compile(r"^\d{1,4}$")

# A contiguous run of a constant NONZERO offset longer than this is a complex
# misalignment, not a single correctable offset -- the R7 hard-stop threshold.
SUSTAINED_RUN_HARD_STOP = 5


@dataclass(frozen=True)
class PageAlignment:
    stem: str
    canonical_leaf_id: int | None
    canonical_page_num: int | None
    abbyy_page_num: int | None  # ABBYY scandata field (reliable for the offset oracle)
    header_printed_page: int | None  # running-header glyph (PIPE-29 corroboration; noisy)
    offset: int | None  # abbyy_page_num - canonical_page_num (the alignment offset)
    header_clean: bool  # True when the header glyph matches the scandata field exactly


@dataclass(frozen=True)
class LineageAlignment:
    lineage: str
    volume: int
    pages: list[PageAlignment]
    modal_offset: int
    confidence: float
    verified: bool
    sustained_bad_run: int
    header_corroboration: float  # fraction of header-readable pages where glyph == field
    unmapped: list[str] = field(default_factory=list)

    @property
    def mapped_pages(self) -> int:
        return sum(1 for p in self.pages if p.canonical_leaf_id is not None)


def extract_printed_page(text: str) -> int | None:
    """Parse the printed page number from ABBYY running-header text, or None.

    The number is a bare 1-4 digit line within the first or last few non-empty
    lines (recto: top; verso: bottom). Returns the first such numeral found,
    scanning the top band before the bottom band. None when no bare numeral sits
    near the header (OCR-garbled -- the caller falls back to the scandata field).
    """
    if not isinstance(text, str) or not text.strip():
        return None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None
    band = lines[:_HEADER_SCAN_LINES] + lines[-_HEADER_SCAN_LINES:]
    for line in band:
        if _BARE_INT.fullmatch(line):
            return int(line)
    return None


def _leaf_page_nums(manifest: dict[str, Any]) -> dict[int, int]:
    """Map leaf_num -> page_num for every leaf that carries a printed page_num."""
    out: dict[int, int] = {}
    for leaf in leaves_view(manifest):
        leaf_num = leaf.get("leaf_num")
        page_num = leaf.get("page_num")
        if isinstance(leaf_num, int) and isinstance(page_num, int):
            out[leaf_num] = page_num
    return out


def _modal(offsets: list[int]) -> tuple[int, float]:
    """Most-common offset + its share. Deterministic tie-break (PY-09).

    Ties broken toward the offset closest to zero, then the smaller value, so the
    result never depends on dict/Counter iteration order across PYTHONHASHSEED.
    """
    if not offsets:
        return 0, 0.0
    counts = Counter(offsets)
    best = min(counts, key=lambda o: (-counts[o], abs(o), o))
    return best, counts[best] / len(offsets)


def _longest_nonzero_run(ordered_offsets: list[int]) -> int:
    """Longest contiguous run of one constant NONZERO offset value.

    A lone nonzero page (run length 1) is OCR noise, not a sustained offset, so it
    reports 0 -- only >=2 consecutive equal nonzero offsets count as a run.
    """
    longest = 0
    run = 0
    prev: int | None = None
    for off in ordered_offsets:
        if off != 0 and off == prev:
            run += 1
        elif off != 0:
            run = 1
        else:
            run = 0
        prev = off
        longest = max(longest, run)
    return longest if longest >= 2 else 0


def compute_alignment(
    pages: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    lineage: str,
    volume: int,
    confidence_threshold: float = 0.6,
) -> LineageAlignment:
    """Verify a lineage/volume's stem->leaf alignment against printed-page content.

    ``pages`` is an ordered list of rich-sidecar views, each a dict with keys
    ``stem`` (page_native_id), ``page_num`` (ABBYY scandata field, may be None)
    and ``text`` (the OCR text carrying the running header).
    """
    leaf_page_nums = _leaf_page_nums(manifest)
    page_aligns: list[PageAlignment] = []
    unmapped: list[str] = []
    # (canonical_page_num, offset) so the oracle can order by physical page.
    comparable: list[tuple[int, int]] = []
    header_readable = 0
    header_clean_count = 0

    for page in pages:
        stem = str(page["stem"])
        raw_field = page.get("page_num")
        abbyy_page_num = raw_field if isinstance(raw_field, int) else None
        header_page = extract_printed_page(page.get("text", ""))
        leaf = canonical_leaf_id(stem, manifest)
        canon_page = leaf_page_nums.get(leaf) if leaf is not None else None

        # The alignment offset is computed from the ABBYY scandata page_num FIELD,
        # not the running-header glyph. The glyph suffers documented NSH digit
        # confusion (2<->8, 3<->8, 2<->9: printed page 20 OCRs as "80", 23 as "28"),
        # so a decade of tens-digit confusion fakes a CONSTANT offset run that is
        # indistinguishable from real misalignment by constancy alone (the reason
        # cross-engine header consensus is an unreliable page oracle). The scandata
        # field is the trustworthy stem->leaf signal; a genuine stem mis-assignment
        # shifts the field too, so it is still caught.
        offset: int | None = None
        if canon_page is not None and abbyy_page_num is not None:
            offset = abbyy_page_num - canon_page
            comparable.append((canon_page, offset))

        # PIPE-29 corroboration: the running-header glyph (the DATA) confirms the
        # scandata field on cleanly-read pages. A low clean-read rate is digit-OCR
        # noise (visual-sampling fallback territory, Codex#3 OQ4), NOT a field error.
        header_clean = (
            header_page is not None
            and abbyy_page_num is not None
            and header_page == abbyy_page_num
        )
        if header_page is not None:
            header_readable += 1
            if header_clean:
                header_clean_count += 1

        if leaf is None:
            unmapped.append(stem)

        page_aligns.append(
            PageAlignment(
                stem=stem,
                canonical_leaf_id=leaf,
                canonical_page_num=canon_page,
                abbyy_page_num=abbyy_page_num,
                header_printed_page=header_page,
                offset=offset,
                header_clean=header_clean,
            )
        )

    offsets = [off for _page, off in comparable]
    modal_offset, confidence = _modal(offsets)
    ordered = [off for _page, off in sorted(comparable, key=lambda t: t[0])]
    sustained_bad_run = _longest_nonzero_run(ordered)
    header_corroboration = header_clean_count / header_readable if header_readable else 0.0
    verified = (
        modal_offset == 0
        and confidence >= confidence_threshold
        and sustained_bad_run <= SUSTAINED_RUN_HARD_STOP
        and bool(offsets)
    )

    return LineageAlignment(
        lineage=lineage,
        volume=volume,
        pages=page_aligns,
        modal_offset=modal_offset,
        confidence=confidence,
        verified=verified,
        sustained_bad_run=sustained_bad_run,
        header_corroboration=header_corroboration,
        unmapped=unmapped,
    )


def _rich_views(input_root: Path, lineage: str, volume: int) -> list[dict[str, Any]]:
    """Enumerate a lineage/volume's rich sidecars as alignment views in order."""
    suffix = re.sub(r"-v\d+$", "", lineage) + ".json"
    vol_dir = input_root / f"vol_{volume:02d}"
    views: list[dict[str, Any]] = []
    for _seq, stem, path in volume_sidecar_files(vol_dir, suffix):
        rich = json.loads(path.read_text(encoding="utf-8"))
        views.append(
            {
                "stem": stem,
                "page_num": rich.get("page_num"),
                "text": rich.get("text", ""),
            }
        )
    return views


def align_lineage_volume(
    input_root: Path,
    *,
    lineage: str,
    volume: int,
    confidence_threshold: float = 0.6,
) -> LineageAlignment:
    """File-driven wrapper: read the canonical manifest + rich sidecars, verify."""
    input_root = Path(input_root)
    manifest_path = input_root / f"vol_{volume:02d}.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pages = _rich_views(input_root, lineage, volume)
    return compute_alignment(
        pages,
        manifest,
        lineage=lineage,
        volume=volume,
        confidence_threshold=confidence_threshold,
    )
