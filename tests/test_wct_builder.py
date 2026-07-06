"""B6 -- S2.5 alignment / WCT builder, failing-first tests (TEST-16).

Architectural slot: S2.5 (arch A alignment layer). The builder consumes the
per-engine rendering-v1 records for one page image and emits one
word-confusion-table-v1 page. These four tests are the B6 TDD contract from the
arch D plan (section 2, B6 row) -- written-failed-then-satisfied, never authored
after the implementation:

  1. WCT conformance      -- output validates against the frozen
                             word-confusion-table-v1 schema AND passes
                             build/lib/wct_semantic_validator.validate_page.
  2. null/skip preserved  -- an engine that produced nothing at a slot is
                             represented as a skip span record, never dropped.
  3. span not flattened   -- a split (1:n) span record survives with all its
                             source_spans, not collapsed to a single token.
  4. layout authority     -- token-to-zone assignment follows the surya bbox
                             layout, not the producing engine's self-label.

Inputs are synthetic rendering-v1 fixtures (tests/fixtures/wct_builder/) because
B5's real vol_01 rendering output is thin; the B6 prompt authorises this. The
fixtures are proven to be genuine rendering-v1 instances by
test_fixtures_are_valid_rendering_v1.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.edition_page_key import body_edition_key  # noqa: E402
from build.lib.wct_builder import (  # noqa: E402
    build_wct_page,
    confusion_distance,
    weighted_edit_backtrace,
    _nw_align,
    _build_zones,
)
from build.lib.wct_semantic_validator import validate_page  # noqa: E402

SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "wct_builder"
SOURCE_IMAGE = {
    "path": "raw/internet-archive/schaff-herzog-pages/vol_01/page_0010.jpg",
    "sha256": "3b1f9c2e7a4d6058e1c9b2f0a7d34e58f6b1029c3d4e5f60718293a4b5c6d7e8",
}


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def _rendering(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"rendering_{name}.json").read_text(encoding="utf-8"))


def _all_renderings() -> list[dict]:
    return [_rendering(n) for n in ("surya", "azure", "tesseract", "abbyy")]


def _build(names: tuple[str, ...] | None = None) -> dict:
    renderings = [_rendering(n) for n in names] if names else _all_renderings()
    return build_wct_page(
        renderings,
        work_id="schaff-herzog",
        volume_id="vol_01",
        page_id="page_0010",
        source_image=SOURCE_IMAGE,
        edition_page_key=body_edition_key(10),
    )


def _position_with_candidate_substr(page: dict, needle: str) -> dict:
    for position in page["positions"]:
        for candidate in position["candidate_set"]:
            if needle in candidate["candidate_key"] or needle in candidate["raw_reading"]:
                return position
    raise AssertionError(f"no position carries a candidate matching {needle!r}")


# --------------------------------------------------------------------------- #
# Fixture legitimacy: the inputs are real rendering-v1 instances.
# --------------------------------------------------------------------------- #


def test_fixtures_are_valid_rendering_v1() -> None:
    schema = _schema("rendering-v1")
    validator = jsonschema.Draft202012Validator(schema)
    for name in ("surya", "azure", "tesseract", "abbyy"):
        errors = list(validator.iter_errors(_rendering(name)))
        assert errors == [], f"rendering_{name}.json invalid: {errors[:1]}"


# --------------------------------------------------------------------------- #
# 1. WCT conformance.
# --------------------------------------------------------------------------- #


def test_wct_output_validates_schema_and_semantic_validator() -> None:
    page = _build()
    jsonschema.validate(instance=page, schema=_schema("word-confusion-table-v1"))
    assert validate_page(page) == [], "segmentation invariant violated"


# --------------------------------------------------------------------------- #
# 2. null/skip preserved.
# --------------------------------------------------------------------------- #


def test_skip_token_is_preserved_never_dropped() -> None:
    page = _build()
    position = _position_with_candidate_substr(page, "church")
    abbyy_records = [
        sr for sr in position["span_records"] if sr["family"] == "abbyy"
    ]
    assert abbyy_records, "abbyy attestation dropped from the church-history slot"
    skip = abbyy_records[0]
    assert skip["token_span_type"] == "skip"
    assert skip["segmentation_relation"] == "gap"
    assert skip["candidate_id"] is None
    assert skip["source_spans"] == []
    assert skip["raw_confidence"] is None


# --------------------------------------------------------------------------- #
# 3. split/merge span records not flattened.
# --------------------------------------------------------------------------- #


def test_split_span_record_not_flattened() -> None:
    page = _build()
    position = _position_with_candidate_substr(page, "church")
    tesseract_records = [
        sr for sr in position["span_records"] if sr["family"] == "tesseract"
    ]
    assert tesseract_records, "tesseract attestation dropped from the church-history slot"
    split = tesseract_records[0]
    assert split["token_span_type"] == "split"
    assert split["segmentation_relation"] == "1:n"
    # The two raw tokens (church- / history) survive as distinct source spans,
    # never collapsed to one token.
    texts = [s["text"] for s in split["source_spans"]]
    assert len(split["source_spans"]) == 2, f"split flattened: {texts}"
    assert "church-" in texts and "history" in texts


# --------------------------------------------------------------------------- #
# 4. token-to-zone uses the surya layout authority, not the engine self-label.
# --------------------------------------------------------------------------- #


def test_token_to_zone_uses_surya_layout_authority() -> None:
    page = build_wct_page(
        _all_renderings(),
        work_id="schaff-herzog",
        volume_id="vol_01",
        page_id="page_0010",
        source_image=SOURCE_IMAGE,
        layout_authority="surya",
        edition_page_key=body_edition_key(10),
    )
    assert page["layout_authority"]["tool"] == "surya"
    # tesseract self-labelled "early" as zone_label "marginalia", but its bbox is
    # inside the surya body zone -> the builder must zone it body by overlap.
    position = _position_with_candidate_substr(page, "early")
    assert position["zone"]["zone_type"] == "body"
    # the slot is in the body reading order, not stranded in a furniture track.
    assert position["position_id"] in page["reading_order"]


# --------------------------------------------------------------------------- #
# 5. An available engine with zero body tokens is a skip, never dropped
#    (Codex adversarial review Attack 1 -- coverage-denominator integrity).
# --------------------------------------------------------------------------- #


def test_available_engine_with_no_body_tokens_is_skip_not_dropped() -> None:
    # textract ran (its only token is a header above the body zone), so it has
    # zero body tokens. It must appear as a skip at every body position, never
    # silently dropped while still counting in the coverage denominator.
    page = _build(("surya", "azure", "tesseract", "abbyy", "textract"))
    textract_ids = [
        e["engine_id"] for e in page["available_engines"] if e["family"] == "aws-textract"
    ]
    assert textract_ids, "textract missing from available_engines"
    assert page["positions"]
    for position in page["positions"]:
        textract_records = [
            sr for sr in position["span_records"] if sr["family"] == "aws-textract"
        ]
        assert textract_records, f"textract dropped at {position['position_id']}"
        assert textract_records[0]["token_span_type"] == "skip"
        assert textract_records[0]["segmentation_relation"] == "gap"


# --------------------------------------------------------------------------- #
# 6. merge (n:1) span records are reachable and correctly typed
#    (Codex adversarial review Attack 2 -- merge must not be dead code).
# --------------------------------------------------------------------------- #


def test_merge_span_record_n_to_1_reachable() -> None:
    # kraken merges "the" + "early" into one token "theearly"; surya/azure keep
    # them separate. The merge must surface as a merge / n:1 span record whose
    # single source token survives, and the page must still pass both validators.
    page = _build(("surya", "azure", "merge"))
    jsonschema.validate(instance=page, schema=_schema("word-confusion-table-v1"))
    assert validate_page(page) == []
    merges = [
        sr
        for position in page["positions"]
        for sr in position["span_records"]
        if sr["token_span_type"] == "merge"
    ]
    assert merges, "merge span type is unreachable"
    merge = merges[0]
    assert merge["segmentation_relation"] == "n:1"
    assert merge["family"] == "kraken"
    assert len(merge["source_spans"]) == 1   # one token covering n positions


# --------------------------------------------------------------------------- #
# 7. Duplicate layout authority fails fast (Codex secondary finding).
# --------------------------------------------------------------------------- #


def test_duplicate_layout_authority_rejected() -> None:
    with pytest.raises(ValueError):
        build_wct_page(
            [_rendering("surya"), _rendering("surya")],
            work_id="schaff-herzog", volume_id="vol_01", page_id="page_0010",
            source_image=SOURCE_IMAGE,
            layout_authority="surya",
        )


# --------------------------------------------------------------------------- #
# 8. Multi-character OCR confusion entries from YAML feed WCT slot distance.
# --------------------------------------------------------------------------- #


def test_multichar_confusion_rn_m_direct_distance_uses_yaml_model() -> None:
    assert confusion_distance("rn", "m") <= 0.25


def test_multichar_confusion_rn_m_embedded_in_word_uses_yaml_model() -> None:
    assert confusion_distance("modern", "rnodern") < 0.2


def test_multichar_confusion_latin_ligature_entry_uses_yaml_model() -> None:
    assert confusion_distance("æ", "ae") <= 0.25


# --------------------------------------------------------------------------- #
# 8a. Public weighted edit backtrace exposes the WCT character cost model.
# --------------------------------------------------------------------------- #


def _apply_backtrace(a: str, ops: list[dict]) -> str:
    cursor = 0
    output = []
    for op in ops:
        source = op["source"]
        target = op["target"]
        assert a[cursor:cursor + len(source)] == source
        cursor += len(source)
        output.append(target)
    assert cursor == len(a)
    return "".join(output)


def test_weighted_edit_backtrace_distance_matches_confusion_distance_cost() -> None:
    for a, b in [
        ("Abelard", "Abelard"),
        ("belavd", "belard"),
        ("modern", "rnodern"),
        ("æ", "ae"),
        ("longs", "longf"),
        ("", "tri"),
        ("tri", ""),
    ]:
        distance, ops = weighted_edit_backtrace(a, b)
        assert distance == confusion_distance(a, b) * max(len(a), len(b), 1)
        assert _apply_backtrace(a, ops) == b


def test_weighted_edit_backtrace_ops_reconstruct_character_columns() -> None:
    distance, ops = weighted_edit_backtrace("Abelard", "belavd")
    assert distance == 2.0
    assert [op["op"] for op in ops] == [
        "delete",
        "match",
        "match",
        "match",
        "match",
        "substitute",
        "match",
    ]
    assert [(op["source"], op["target"]) for op in ops] == [
        ("A", ""),
        ("b", "b"),
        ("e", "e"),
        ("l", "l"),
        ("a", "a"),
        ("r", "v"),
        ("d", "d"),
    ]
    assert _apply_backtrace("Abelard", ops) == "belavd"


def test_weighted_edit_backtrace_uses_multichar_confusion_ops() -> None:
    distance, ops = weighted_edit_backtrace("modern", "rnodern")
    assert distance == 0.25
    assert ops[0] == {"op": "substitute", "source": "m", "target": "rn"}
    assert _apply_backtrace("modern", ops) == "rnodern"


def test_weighted_edit_backtrace_deterministic_across_hash_seeds() -> None:
    script = (
        "import json;"
        "from build.lib.wct_builder import weighted_edit_backtrace;"
        "print(json.dumps(weighted_edit_backtrace('Abelard', 'belavd'), sort_keys=True))"
    )

    def run(seed: int) -> str:
        env = {**os.environ, "PYTHONHASHSEED": str(seed)}
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )
        return result.stdout

    assert run(0) == run(1)


# --------------------------------------------------------------------------- #
# 9. _nw_align must not walk off the array on real page_0010 key sequences
#    (bug 1 -- float-equality backtrace; reproduced on real renderings).
# --------------------------------------------------------------------------- #

# The real Tesseract reading-order body-token keys for vol_01 page_0010, copied
# verbatim from reports/_thinslice/rendering_single/tesseract-py314-v1.rendering-v1.json
# (TEST-13: real data, not a hand-built description). Aligning this 70-key spine
# against a short real subsequence forces the backtrace up the j=0 gap column,
# where i*GAP_PENALTY accumulates float drift -- the float-`==` backtrace then
# matches no branch, drives j negative, and indexes off the end.
_REAL_PAGE10_TESSERACT_KEYS = [
    "Abelard", "Abhedananda", "love,", "faithful", "his", "example.", "By",
    "highest", "to", "the", "with", "and", "God;", "has", "merit", "because",
    "death,", "Christ", "won", "those", "God", "forgives", "who", "into",
    "merit", "this", "enter", "of", "Christ", "and", "enables", "them",
    "fulfil", "with", "communion", "to", "personal", "Christ,", "with", "is",
    "communion", "in", "It", "law.", "the", "Only", "the", "real", "consists.",
    "that", "Atonement", "therefore,", "themselves", "impressed", "the", "love",
    "with", "let", "be", "such", "as", "this", "By", "the", "communion.",
    "Christ", "into", "of", "enter", "curse",
]


def _assert_valid_alignment(ops, n, m):
    """Every spine idx 0..n-1 and token idx 0..m-1 appears once, in order."""
    spine_seen = [c for c, _ in ops if c is not None]
    token_seen = [t for _, t in ops if t is not None]
    assert spine_seen == list(range(n)), "spine indices missing or reordered"
    assert token_seen == list(range(m)), "token indices missing or reordered"


def test_nw_align_real_page10_tail_does_not_walk_off_array() -> None:
    spine = _REAL_PAGE10_TESSERACT_KEYS
    tokens = spine[-4:]  # real reading-order tail ['into','of','enter','curse']
    ops = _nw_align(spine, tokens)
    _assert_valid_alignment(ops, len(spine), len(tokens))


def test_nw_align_real_spine_against_empty_token_list() -> None:
    # The degenerate real case the prior session hit: a line-level engine that
    # contributed zero body tokens before bug 2 was fixed. All-deletion path.
    ops = _nw_align(_REAL_PAGE10_TESSERACT_KEYS, [])
    _assert_valid_alignment(ops, len(_REAL_PAGE10_TESSERACT_KEYS), 0)


# --------------------------------------------------------------------------- #
# 10. _build_zones reads bbox_canonical as corners [x0,y0,x1,y1], not [x,y,w,h]
#     (bug 3 -- render_s2 emits corners; _build_zones misread them as origin+size).
# --------------------------------------------------------------------------- #


def _surya_blocks_rendering(blocks: list[dict], width: int, height: int) -> dict:
    """Minimal surya rendering carrying just what _build_zones reads."""
    return {
        "engine_family": "surya",
        "source_lineage_id": "surya-py312-v1",
        "engine_version": "0.17.1",
        "rendering_id": "r-surya",
        "pages": [
            {
                "page_dimensions_native": {"width": width, "height": height, "unit": "pixel"},
                "blocks": blocks,
            }
        ],
    }


def test_build_zones_reads_bbox_canonical_as_corners() -> None:
    # A body block [0.1, 0.1, 0.8, 0.8] on a 2000x3000 page is corners
    # [x0,y0,x1,y1]: native width = (0.8-0.1)*2000 = 1400, NOT 0.8*2000 = 1600.
    # render_s2._bbox_canonical emits (x+w)/width at index 2, so corners is canonical.
    surya = _surya_blocks_rendering([{"zone_label": "body", "bbox_canonical": [0.1, 0.1, 0.8, 0.8]}], 2000, 3000)
    body = next(z for z in _build_zones(surya) if z["zone_type"] == "body")
    assert body["_native"]["w"] == pytest.approx((0.8 - 0.1) * 2000)
    assert body["_native"]["h"] == pytest.approx((0.8 - 0.1) * 3000)


# --------------------------------------------------------------------------- #
# 11. _build_zones groups body-labeled line-blocks into ONE body column zone
#     (bug 4 -- real surya emits 137 body line-blocks; build_wct aligned only
#     within the first, so 1085 body words collapsed to one line's worth).
# --------------------------------------------------------------------------- #


def test_build_zones_groups_body_line_blocks_into_one_column() -> None:
    # Three stacked body line-blocks (mirrors real surya's per-line blocks) plus a
    # footnote block. The body must become ONE zone spanning all three; the
    # footnote stays its own zone.
    blocks = [
        {"zone_label": "body", "bbox_canonical": [0.1, 0.10, 0.5, 0.13]},
        {"zone_label": "body", "bbox_canonical": [0.1, 0.14, 0.5, 0.17]},
        {"zone_label": "body", "bbox_canonical": [0.1, 0.18, 0.5, 0.21]},
        {"zone_label": "footnote", "bbox_canonical": [0.1, 0.90, 0.5, 0.93]},
    ]
    zones = _build_zones(_surya_blocks_rendering(blocks, 2000, 3000))
    body_zones = [z for z in zones if z["zone_type"] == "body"]
    assert len(body_zones) == 1, f"expected one body column, got {len(body_zones)}"
    # The single body zone spans the union of the three line-blocks (y from 0.10 to
    # 0.21 of 3000 = 300..630).
    nat = body_zones[0]["_native"]
    assert nat["y"] == pytest.approx(0.10 * 3000)
    assert nat["y"] + nat["h"] == pytest.approx(0.21 * 3000)
    assert any(z["zone_type"] == "footnote" for z in zones), "footnote zone dropped"


def test_build_zones_splits_two_column_body_into_two_column_zones() -> None:
    # Real NSH body pages are two-column: surya's body block x-centers are bimodal
    # (page_0010 = 67 left + 62 right). The layout authority's columns must become
    # two body column zones so reading order is left-column-then-right, not the
    # (y,x) interleave of both columns. Left blocks center x~0.275, right x~0.725.
    blocks = []
    for i in range(4):
        y = 0.10 + i * 0.04
        blocks.append({"zone_label": "body", "bbox_canonical": [0.10, y, 0.45, y + 0.03]})
        blocks.append({"zone_label": "body", "bbox_canonical": [0.55, y, 0.90, y + 0.03]})
    zones = _build_zones(_surya_blocks_rendering(blocks, 2000, 3000))
    body_zones = sorted(
        (z for z in zones if z["zone_type"] == "body"), key=lambda z: z["_native"]["x"]
    )
    assert len(body_zones) == 2, f"expected two body columns, got {len(body_zones)}"
    left, right = body_zones
    assert left["column"] == 1 and right["column"] == 2
    # Columns don't overlap horizontally: left ends before right begins.
    assert left["_native"]["x"] + left["_native"]["w"] <= right["_native"]["x"]
