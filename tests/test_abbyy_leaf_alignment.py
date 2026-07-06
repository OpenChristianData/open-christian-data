"""Tests for the R7 ABBYY leaf-alignment + content-verification tool.

The tool verifies that an ABBYY lineage's rich sidecars (named by primary stem)
are correctly aligned onto the canonical manifest's leaf coordinate, by
cross-checking each page's printed page number (running header = the DATA, PIPE-29)
against the canonical manifest's page_num for the leaf the stem resolves to.

The oracle is a BULK OFFSET oracle (design SS6, Codex#3 OQ4): a sustained constant
offset across a contiguous run is a misalignment; isolated mismatches are OCR noise.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.ocr_pipeline.abbyy_leaf_alignment import (  # noqa: E402
    compute_alignment,
    extract_printed_page,
)


def _canonical_manifest(first_page: int = 1, last_page: int = 60, front_offset: int = 36) -> dict:
    """A minimal v4 canonical manifest: body leaf_num = page_num + front_offset."""
    leaves = []
    # front matter leaves (no page_num)
    for leaf_num in range(1, first_page + front_offset):
        leaves.append({"leaf_num": leaf_num, "page_num": None, "kind": "front_matter"})
    for page_num in range(first_page, last_page + 1):
        leaves.append(
            {
                "leaf_num": page_num + front_offset,
                "page_num": page_num,
                "kind": "body",
            }
        )
    return {"volume": 1, "leaves": leaves, "gaps": []}


def _rich_page(page_num: int, *, header_page: int | None = None, text: str | None = None) -> dict:
    """A rich-sidecar-shaped dict the alignment tool consumes (stem + page_num + text)."""
    if text is None:
        hp = page_num if header_page is None else header_page
        # Recto-style: the printed page number sits on its own line by the header.
        text = f"{hp}\nRELIGIOUS ENCYCLOPEDIA\nAbelard the schoolman wrote"
    return {"stem": f"page_{page_num:04d}", "page_num": page_num, "text": text}


# --- extract_printed_page -------------------------------------------------


def test_extract_printed_page_from_recto_header() -> None:
    text = "11\nRELIGIOUS ENCYCLOPEDIA\nAbdias the prophet"
    assert extract_printed_page(text) == 11


def test_extract_printed_page_from_verso_footer() -> None:
    # Verso pages carry the page number at the end, by THE NEW SCHAFF-HERZOG.
    text = "Abelard\nTHE NEW SCHAFF-HERZOG\nlong body of the article here\n12"
    assert extract_printed_page(text) == 12


def test_extract_printed_page_returns_none_when_garbled() -> None:
    text = "Abelard\nTHE NEW SCHAFF-HERZOG\nno numerals near the header at all"
    assert extract_printed_page(text) is None


# --- compute_alignment ----------------------------------------------------


def test_aligned_pages_verify_with_zero_offset() -> None:
    manifest = _canonical_manifest()
    pages = [_rich_page(p) for p in range(8, 20)]
    result = compute_alignment(pages, manifest, lineage="ia-abbyy-v1", volume=1)
    assert result.modal_offset == 0
    assert result.verified is True
    assert result.confidence == pytest.approx(1.0)
    assert result.sustained_bad_run == 0
    assert result.unmapped == []
    # Every body stem resolved to page_num + front_offset.
    by_stem = {pa.stem: pa for pa in result.pages}
    assert by_stem["page_0010"].canonical_leaf_id == 46


def test_injected_plus_n_offset_is_detected_and_fails_verification() -> None:
    # Acceptance: a genuine stem->leaf misalignment shifts the ABBYY scandata page
    # for every page by a constant. Here the rich files for printed pages 10..21 are
    # mis-assigned onto leaves two earlier (the scan's page_num reads canon+2). The
    # bulk oracle must report modal_offset == 2 and a sustained bad run > 5.
    manifest = _canonical_manifest()
    offset = 2
    pages = []
    for p in range(8, 20):
        page = _rich_page(p, header_page=p + offset, text=f"{p + offset}\nRELIGIOUS ENCYCLOPEDIA\nbody")
        page["page_num"] = p + offset  # scandata field shifted -> the misalignment signal
        pages.append(page)
    result = compute_alignment(pages, manifest, lineage="ia-abbyy-v1", volume=1)
    assert result.modal_offset == offset
    assert result.verified is False
    assert result.sustained_bad_run > 5


def test_digit_confused_header_run_does_not_fake_misalignment() -> None:
    # Real-data robustness: a contiguous decade of pages whose running-header glyph
    # suffers the tens-digit confusion (printed 20 OCRs as "80", +60) must NOT be
    # read as a misalignment when the scandata field is clean. The field offset is 0
    # throughout, so the alignment verifies; only header_corroboration drops.
    manifest = _canonical_manifest()
    pages = []
    for p in range(8, 22):
        if 12 <= p <= 20:  # a sustained run of 9 digit-confused header reads
            header = p + 60
        else:
            header = p
        page = _rich_page(p, header_page=header, text=f"{header}\nRELIGIOUS ENCYCLOPEDIA\nbody")
        page["page_num"] = p  # scandata field is correct
        pages.append(page)
    result = compute_alignment(pages, manifest, lineage="ia-abbyy-v1", volume=1)
    assert result.modal_offset == 0
    assert result.verified is True
    assert result.sustained_bad_run == 0
    assert result.header_corroboration < 1.0  # the digit-confused run lowers it


def test_isolated_mismatch_is_noise_not_misalignment() -> None:
    manifest = _canonical_manifest()
    pages = [_rich_page(p) for p in range(8, 20)]
    # One page reads a garbage number (OCR noise) -- must not flip the verdict.
    pages[3]["text"] = "999\nRELIGIOUS ENCYCLOPEDIA\nbody"
    result = compute_alignment(pages, manifest, lineage="ia-abbyy-v1", volume=1)
    assert result.modal_offset == 0
    assert result.verified is True
    assert result.sustained_bad_run == 0


def test_unmapped_stem_is_logged_not_counted() -> None:
    manifest = _canonical_manifest()
    pages = [_rich_page(p) for p in range(8, 14)]
    # An alternate-scan tail leaf with no primary page -- stem cannot resolve.
    pages.append({"stem": "page_leaf0540", "page_num": 540, "text": "tail leaf"})
    result = compute_alignment(pages, manifest, lineage="ia-abbyy-v1", volume=1)
    assert "page_leaf0540" in result.unmapped
    assert result.modal_offset == 0
    assert result.verified is True
