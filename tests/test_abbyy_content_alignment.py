"""Tests for the content-based alternate-scan leaf aligner (R7, design sec 6).

The aligner maps an alternate IA scan's leaves onto canonical leaves by OCR-tolerant
content matching when the scan has its own leaf order (different front matter, duplicate
/ missing / mis-bound leaves). These tests exercise the pure align_by_content over
synthetic pages so the alignment logic is covered without real OCR fixtures.
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.ocr_pipeline.abbyy_content_alignment import (  # noqa: E402
    ContentAlignment,
    align_by_content,
    load_leafmap,
    page_similarity,
    write_leafmap,
)

# Distinct vocab per canonical leaf so a correct match is unambiguous. Each page has
# enough unique 4+ letter words for the Jaccard pre-filter and the text aligner.
_VOCAB = {
    10: "apple banana cherry damson elder fennel ginger hazel indigo juniper kiwi lemon",
    11: "house tower river mountain ocean valley forest meadow canyon glacier prairie tundra",
    12: "saturn jupiter mercury venus mars neptune uranus pluto comet meteor nebula quasar",
    13: "cotton velvet linen satin damask brocade muslin chiffon taffeta corduroy flannel tweed",
    14: "oxygen carbon helium argon sodium calcium iron copper zinc nickel cobalt silver",
}


def _reference():
    """[(leaf, wordset, tokens)] ordered by leaf, mirroring build_reference output."""
    ref = []
    for leaf in sorted(_VOCAB):
        toks = _VOCAB[leaf].split()
        ref.append((leaf, set(t for t in toks if len(t) >= 4), toks))
    return ref


def _align(alt_pages):
    return align_by_content(
        alt_pages, _reference(),
        lineage="ia-abbyy-test-v1", volume=1, reference_lineage="ia-abbyy-v1",
    )


def _mapping(al: ContentAlignment):
    return {p.stem: p.canonical_leaf_id for p in al.pages}


def test_in_order_pages_map_to_their_leaves():
    al = _align([("page_0000", _VOCAB[10]), ("page_0001", _VOCAB[11]), ("page_0002", _VOCAB[12])])
    assert _mapping(al) == {"page_0000": 10, "page_0001": 11, "page_0002": 12}
    assert al.monotonic_violations == 0
    assert al.mapped_pages == 3


def test_front_matter_offset_then_aligns():
    # Two junk front-matter leaves (no canonical match) before the body starts.
    al = _align([
        ("page_0000", "frontis colophon imprint dedication preface foreword"),
        ("page_0001", "contents errata addenda subscribers advertisement notice"),
        ("page_0002", _VOCAB[10]), ("page_0003", _VOCAB[11]),
    ])
    m = _mapping(al)
    assert m["page_0000"] is None and m["page_0001"] is None
    assert m["page_0002"] == 10 and m["page_0003"] == 11


def test_missing_canonical_leaf_is_skipped():
    # Alt scan is missing the page for leaf 11; 10 then 12 still map, monotone.
    al = _align([("page_0000", _VOCAB[10]), ("page_0001", _VOCAB[12]), ("page_0002", _VOCAB[13])])
    assert _mapping(al) == {"page_0000": 10, "page_0001": 12, "page_0002": 13}
    assert al.monotonic_violations == 0


def test_duplicate_alt_leaf_maps_to_same_canonical():
    # A duplicated scan leaf (same content twice) both map to the same canonical leaf.
    al = _align([("page_0000", _VOCAB[10]), ("page_0001", _VOCAB[11]),
                 ("page_0002", _VOCAB[11]), ("page_0003", _VOCAB[12])])
    m = _mapping(al)
    assert m["page_0001"] == 11 and m["page_0002"] == 11
    assert m["page_0000"] == 10 and m["page_0003"] == 12


def test_defect_page_is_unmapped_not_forcemapped():
    # A mis-bound/defect leaf with vocab matching nothing -> unmapped, never forced.
    al = _align([("page_0000", _VOCAB[10]),
                 ("page_0001", "xkcd qwerty zxcvb plugh frobnicate bazqux wibble flonk"),
                 ("page_0002", _VOCAB[11])])
    m = _mapping(al)
    assert m["page_0001"] is None
    assert m["page_0000"] == 10 and m["page_0002"] == 11
    assert "page_0001" in al.unmapped


def test_ocr_noise_still_matches():
    # Realistic cross-scan OCR noise: most words read correctly, a few are garbled
    # (1-char substitutions). The aligner must still recognise canonical leaf 12, and
    # the garbled tokens go through the text aligner's OCR-difference tolerance.
    garbled = "satum jupiter mercviy venus mars neptvne uranus pluto comet meteor nebula quasar"
    al = _align([("page_0000", _VOCAB[11]), ("page_0001", garbled), ("page_0002", _VOCAB[13])])
    assert _mapping(al)["page_0001"] == 12


def test_too_few_words_is_unmapped():
    al = _align([("page_0000", _VOCAB[10]), ("page_0001", "blank"), ("page_0002", _VOCAB[11])])
    assert _mapping(al)["page_0001"] is None


def test_page_similarity_identical_is_one():
    toks = _VOCAB[10].split()
    assert page_similarity(toks, toks) == pytest.approx(1.0)


def test_page_similarity_disjoint_is_low():
    assert page_similarity(_VOCAB[10].split(), _VOCAB[14].split()) < 0.2


def test_leafmap_roundtrip(tmp_path):
    al = _align([("page_0000", _VOCAB[10]), ("page_0001", _VOCAB[11]),
                 ("page_0002", "xkcd qwerty zxcvb plugh frobnicate bazqux wibble flonk")])
    # write_leafmap names the file vol_NN.<lineage>.leafmap.json under input_root.
    out = write_leafmap(tmp_path, al)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["stem_to_leaf"] == {"page_0000": 10, "page_0001": 11}
    assert "page_0002" in data["unmapped"]
    loaded = load_leafmap(tmp_path, "ia-abbyy-test-v1", 1)
    assert loaded == {"page_0000": 10, "page_0001": 11}


def test_load_leafmap_absent_returns_none(tmp_path):
    assert load_leafmap(tmp_path, "ia-abbyy-test-v1", 9) is None


# --- Task 1: gated global (non-monotone) fallback pass ------------------------
# The monotone pass leaves a few mid-body out-of-order leaves unmapped; the global
# pass recovers them by searching the WHOLE reference, behind a high floor + an
# independent primary cross-check. These synthetic refs are large enough (35 leaves)
# that an out-of-order leaf falls OUTSIDE the monotone search band, so the monotone
# pass genuinely skips it and only the global pass can recover it.


def _w(n: int) -> str:
    """Deterministic unique 5-letter lowercase token for an integer (>=4 for _WORD)."""
    out = []
    for _ in range(5):
        out.append(chr(ord("a") + n % 26))
        n //= 26
    return "".join(out)


def _big_reference(n_leaves=35, start_leaf=10, words_per=12):
    ref = []
    for k in range(n_leaves):
        leaf = start_leaf + k
        toks = [_w(leaf * 100 + i) for i in range(words_per)]
        ref.append((leaf, set(t for t in toks if len(t) >= 4), toks))
    return ref


def _leaf_text(leaf, words_per=12):
    return " ".join(_w(leaf * 100 + i) for i in range(words_per))


def _align_global(alt_pages, reference=None, primary_words=None, min_body_words=8):
    return align_by_content(
        alt_pages, reference if reference is not None else _big_reference(),
        lineage="ia-abbyy-test-v1", volume=1, reference_lineage="ia-abbyy-v1",
        global_fallback=True, primary_words=primary_words,
        min_body_words=min_body_words,
    )


def test_global_pass_recovers_misbound_midbody_page():
    ref = _big_reference()  # leaves 10..44
    pages = [(f"page_{leaf:04d}", _leaf_text(leaf)) for leaf in range(10, 31)]
    pages.append(("page_9999", _leaf_text(10)))  # mis-bound: content is leaf 10
    pages += [(f"page_{leaf:04d}", _leaf_text(leaf)) for leaf in range(31, 45)]

    # Without the global pass, the monotone band cannot reach leaf 10 -> unmapped.
    base = align_by_content(
        pages, ref, lineage="ia-abbyy-test-v1", volume=1,
        reference_lineage="ia-abbyy-v1",
    )
    assert {p.stem: p.canonical_leaf_id for p in base.pages}["page_9999"] is None

    al = _align_global(pages, ref)
    rec = {p.stem: p for p in al.pages}["page_9999"]
    assert rec.canonical_leaf_id == 10
    assert rec.recovered is True
    assert "page_9999" not in al.unmapped


def test_global_pass_leaves_nomatch_page_unmapped():
    ref = _big_reference()
    pages = [(f"page_{leaf:04d}", _leaf_text(leaf)) for leaf in range(10, 21)]
    pages.append(("page_8888", " ".join(_w(900000 + i) for i in range(12))))  # matches nothing
    pages += [(f"page_{leaf:04d}", _leaf_text(leaf)) for leaf in range(21, 31)]
    al = _align_global(pages, ref)
    p = {p.stem: p for p in al.pages}["page_8888"]
    assert p.canonical_leaf_id is None
    assert p.classification == "body-unrecoverable"
    assert "page_8888" in al.unmapped


def test_global_pass_rejects_primary_contradicted_candidate():
    ref = _big_reference()
    pages = [(f"page_{leaf:04d}", _leaf_text(leaf)) for leaf in range(10, 21)]
    pages.append(("page_7777", _leaf_text(10)))  # ref-matches leaf 10
    pages += [(f"page_{leaf:04d}", _leaf_text(leaf)) for leaf in range(21, 31)]
    # primary tesseract for leaf 10 has disjoint words -> contradiction
    primary = {10: set(_w(700000 + i) for i in range(12))}
    al = _align_global(pages, ref, primary_words=primary)
    p = {p.stem: p for p in al.pages}["page_7777"]
    assert p.canonical_leaf_id is None
    assert p.classification == "body-unrecoverable"


def test_global_pass_accepts_primary_corroborated_recovery():
    ref = _big_reference()
    pages = [(f"page_{leaf:04d}", _leaf_text(leaf)) for leaf in range(10, 21)]
    pages.append(("page_6666", _leaf_text(10)))
    pages += [(f"page_{leaf:04d}", _leaf_text(leaf)) for leaf in range(21, 31)]
    primary = {10: set(_w(10 * 100 + i) for i in range(12))}  # agrees with leaf 10
    al = _align_global(pages, ref, primary_words=primary)
    p = {p.stem: p for p in al.pages}["page_6666"]
    assert p.canonical_leaf_id == 10
    assert p.recovered is True


def test_front_back_unmapped_classified_non_body():
    ref = _big_reference()
    pages = [("page_0000", "frontis colophon imprint dedication preface foreword extra title")]
    pages += [(f"page_{leaf:04d}", _leaf_text(leaf)) for leaf in range(10, 21)]
    pages.append(("page_9998", "index errata addenda subscribers advertisement notice colophon final"))
    al = _align_global(pages, ref)
    m = {p.stem: p for p in al.pages}
    assert m["page_0000"].canonical_leaf_id is None
    assert m["page_0000"].classification == "non-body"
    assert m["page_9998"].classification == "non-body"


def test_global_pass_recovers_via_primary_when_reference_has_gap():
    # The ia-abbyy-v1 reference is MISSING leaf 25 (a real gap, e.g. vol_10 letter-S),
    # but the primary tesseract has it. A mid-body alt page covering that leaf cannot be
    # matched against the absent reference, yet strongly matches the primary -> recover
    # via the independent primary engine (PIPE-29-safe: a strong cross-engine match).
    ref = [(leaf, w, t) for (leaf, w, t) in _big_reference() if leaf != 25]
    pages = [(f"page_{leaf:04d}", _leaf_text(leaf)) for leaf in range(10, 25)]
    pages.append(("page_2500", _leaf_text(25)))
    pages += [(f"page_{leaf:04d}", _leaf_text(leaf)) for leaf in range(26, 45)]
    from build.tools.ocr_pipeline.abbyy_content_alignment import word_set
    primary = {25: word_set(_leaf_text(25))}
    al = align_by_content(
        pages, ref, lineage="ia-abbyy-test-v1", volume=1,
        reference_lineage="ia-abbyy-v1", global_fallback=True,
        primary_words=primary, min_body_words=8,
    )
    p = {p.stem: p for p in al.pages}["page_2500"]
    assert p.canonical_leaf_id == 25
    assert p.recovered is True


def test_global_pass_primary_fallback_respects_floor():
    # Reference gap at leaf 25, primary has leaf 25, but the alt page matches NEITHER
    # -> stays unmapped (the primary fallback has a high floor, not a catch-all).
    ref = [(leaf, w, t) for (leaf, w, t) in _big_reference() if leaf != 25]
    pages = [(f"page_{leaf:04d}", _leaf_text(leaf)) for leaf in range(10, 25)]
    pages.append(("page_2500", " ".join(_w(950000 + i) for i in range(12))))
    pages += [(f"page_{leaf:04d}", _leaf_text(leaf)) for leaf in range(26, 45)]
    from build.tools.ocr_pipeline.abbyy_content_alignment import word_set
    primary = {25: word_set(_leaf_text(25))}
    al = align_by_content(
        pages, ref, lineage="ia-abbyy-test-v1", volume=1,
        reference_lineage="ia-abbyy-v1", global_fallback=True,
        primary_words=primary, min_body_words=8,
    )
    p = {p.stem: p for p in al.pages}["page_2500"]
    assert p.canonical_leaf_id is None
    assert p.classification == "body-unrecoverable"


def test_leafmap_persists_unmapped_classification(tmp_path):
    ref = _big_reference()
    pages = [("page_0000", "frontis colophon imprint dedication preface foreword extra title")]
    pages += [(f"page_{leaf:04d}", _leaf_text(leaf)) for leaf in range(10, 21)]
    pages.append(("page_8888", " ".join(_w(900000 + i) for i in range(12))))
    pages += [(f"page_{leaf:04d}", _leaf_text(leaf)) for leaf in range(21, 31)]
    al = _align_global(pages, ref)
    out = write_leafmap(tmp_path, al)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["unmapped_classified"]["page_8888"]["class"] == "body-unrecoverable"
    assert data["unmapped_classified"]["page_0000"]["class"] == "non-body"
