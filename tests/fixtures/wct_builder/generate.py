"""Generate synthetic rendering-v1 fixtures for the B6 WCT-builder tests.

B5's real vol_01 rendering output is thin, so the S2.5 alignment builder is
unit-tested against a small synthetic per-engine rendering-v1 fixture set (the
B6 prompt explicitly authorises this; the builder is the deliverable, running it
on real vol_01 at scale is downstream). Every record this script writes is
validated against schemas/v1/rendering-v1.schema.json by
tests/test_wct_builder.py::test_fixtures_are_valid_rendering_v1 -- so the inputs
are genuine rendering-v1 instances, not structural descriptions (TEST-13 is
satisfied via schema conformance because no real downloaded rendering exists yet).

The page mirrors the arch A worked example (plans/.../archA section 2): a body
line containing the hyphenated word "church-history". Four engines exhibit the
contract's structurally-critical cases:

  surya   (layout authority + recogniser): the / early / church-history / council
  azure   (exact, joined hyphen)         : the / early / church-history / council
  tesseract (SPLIT across a line break)  : the / early / [church- + history] / council
  abbyy   (SKIP at the hyphen position)  : the / early / council

tesseract additionally mislabels "early" with zone_label "marginalia" even though
its bbox sits inside the surya body zone -- the builder must zone it to "body" by
surya bbox-overlap, not by the engine's self-reported label (layout-authority).

Run:  py -3 tests/fixtures/wct_builder/generate.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
IMAGE_W, IMAGE_H = 2000, 3000

# Surya layout: one body zone. Native pixel frame.
BODY_ZONE = {"x": 200, "y": 300, "w": 1600, "h": 2400}


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ot_id(engine: str, text: str, index: int) -> str:
    raw = f"{engine}:{text}:{index}"
    return "ot-sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ds_id(engine: str, marker: str) -> str:
    raw = f"{engine}:join:{marker}"
    return "ds-sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


_EMPTY_JCS = _sha256("{}")


def _canonical(bbox: dict) -> list[float]:
    return [
        round(bbox["x"] / IMAGE_W, 6),
        round(bbox["y"] / IMAGE_H, 6),
        round(bbox["w"] / IMAGE_W, 6),
        round(bbox["h"] / IMAGE_H, 6),
    ]


def _layers(text: str) -> dict:
    return {"source_raw": text, "normalised": text, "structured": text, "display": text}


def _membership() -> dict:
    return {"status": "none", "candidate_article_ids": []}


def _word(
    engine: str,
    text: str,
    index: int,
    bbox: dict,
    *,
    confidence: float,
    zone_label: str = "body",
    join_id: str | None = None,
) -> dict:
    return {
        "observation_token_id": _ot_id(engine, text, index),
        "native_sequence_index": index,
        "layers": _layers(text),
        "bbox_native": dict(bbox),
        "bbox_canonical": _canonical(bbox),
        "confidence_raw": confidence,
        "zone_label": zone_label,
        "candidate_article_membership": _membership(),
        "word_extras_carried": {},
        "word_extras_carried_keys": [],
        "word_extras_jcs_sha256": _EMPTY_JCS,
        "in_derived_join_span": join_id is not None,
        "derived_join_span_id": join_id,
    }


def _line_geometry() -> dict:
    return {"x_size": 60.0, "baseline": 460.0, "x_descenders": 470.0, "x_ascenders": 405.0}


def _indent_evidence() -> dict:
    return {"style": "none", "block_x": float(BODY_ZONE["x"]), "line_x": float(BODY_ZONE["x"])}


def _line(engine: str, line_index: int, words: list[dict], bbox: dict) -> dict:
    return {
        "rendering_line_id": f"{engine}-l{line_index}",
        "native_line_ids": [f"{engine}:nl{line_index}"],
        "native_order": line_index,
        "derived_order": line_index,
        "bbox_native": dict(bbox),
        "bbox_canonical": _canonical(bbox),
        "line_geometry": _line_geometry(),
        "indent_evidence": _indent_evidence(),
        "relative_size_tier": "body",
        "raw_size_pt": 11.0,
        "layers": _layers(" ".join(w["layers"]["structured"] for w in words)),
        "words": words,
        "line_extras_carried": {},
        "line_extras_carried_keys": [],
        "line_extras_jcs_sha256": _EMPTY_JCS,
    }


def _block(engine: str, lines: list[dict]) -> dict:
    all_words = [w for ln in lines for w in ln["words"]]
    return {
        "rendering_block_id": f"{engine}-b0",
        "native_block_ids": [f"{engine}:nb0"],
        "native_order": 0,
        "derived_order": 0,
        "block_type": "paragraph",
        "block_type_evidence": {"signals": []},
        "block_type_confidence": "high",
        "block_type_conflicts": [],
        "region_class": "body",
        "language_lane": "en",
        "language_lane_confidence": "high",
        "zone_label": "body",
        "candidate_article_membership": _membership(),
        "bibliography_layout": {"status": "not_bibliography", "evidence": []},
        "indent_style": "none",
        "bbox_canonical": _canonical(BODY_ZONE),
        "block_extras_carried": {},
        "block_extras_carried_keys": [],
        "block_extras_jcs_sha256": _EMPTY_JCS,
        "layers": _layers(" ".join(w["layers"]["structured"] for w in all_words)),
        "lines": lines,
    }


def _page(engine: str, blocks: list[dict]) -> dict:
    return {
        "manifest_id": "schaff-herzog/vol_01",
        "rendering_id": f"rendering-{engine}-vol01-p0010",
        "page_native_id": "leaf_0010",
        "canonical_leaf_id": 10,
        "edition_page_key": {"section": "body", "anchor": 10, "ordinal": 0},
        "page_sequence": 10,
        "page_dimensions_native": {"width": IMAGE_W, "height": IMAGE_H, "unit": "pixel"},
        "source_payload_sha256": _sha256(f"source-image:{engine}"),
        "coverage_state": "covered",
        "reading_order_reliability": "high",
        "blocks": blocks,
        "page_extras_carried": {},
        "page_extras_carried_keys": [],
        "page_extras_jcs_sha256": _EMPTY_JCS,
    }


def _rendering(engine_family: str, lineage: str, page: dict, derived_spans: dict) -> dict:
    rid = page["rendering_id"]
    return {
        "schema_version": "rendering-v1",
        "stage_version": "s2-render-v1",
        "rendering_id": rid,
        "engine_family": engine_family,
        "engine_version": "fixture-1.0",
        "source_lineage_id": lineage,
        "work_id": "schaff-herzog",
        "edition_id": "1908-1914",
        "volume": 1,
        "pipeline_config_hash": _sha256("pipeline-config"),
        "typography_snapshot_id": "typo-fixture",
        "typography_snapshot_approval_state": "provisional",
        "ccel_annotation_source_id": None,
        "dictionary_snapshot_ids": {},
        "nfkc_allowlist_hash": _sha256("nfkc-allowlist"),
        "fingerprint_function_hash": _sha256("fingerprint-fn"),
        "source_sidecar_refs": [],
        "parsed_keys_index_refs": [],
        "witness_coverage": {
            "page_count": 1,
            "eligible_pages": 1,
            "diagnostic_pages": 0,
            "corrupt_pages": 0,
            "missing_pages": 0,
            "coverage_state": "covered",
        },
        "pages": [page],
        "candidate_articles": [],
        "derived_spans_by_block": derived_spans,
        "structural_uncertainty_queue": [],
        "operations_ledger_ref": {"path": "reports/ledger.json", "sha256": _sha256("ledger")},
        "operations_ledger_hash": _sha256("ledger"),
        "replay_verification": {
            "passed": True,
            "ledger_schema_valid": True,
            "forward_replay_sha256": _sha256("fwd"),
            "inverse_replay_sha256": _sha256("inv"),
            "source_raw_reconstruction_sha256": _sha256("recon"),
            "verified_at": "2026-05-28T00:00:00Z",
            "verifier_version": "fixture-1.0",
            "failure_codes": [],
        },
        "admission_state": {
            "fully_admitted": True,
            "coverage_gaps": 0,
            "reading_order_low_pages": 0,
            "reading_order_failed_pages": 0,
            "unresolved_hyphen_count": 0,
        },
    }


def build_surya() -> dict:
    words = [
        _word("surya", "the", 0, {"x": 210, "y": 400, "w": 120, "h": 60}, confidence=0.97),
        _word("surya", "early", 1, {"x": 350, "y": 400, "w": 180, "h": 60}, confidence=0.96),
        _word("surya", "church-history", 2, {"x": 560, "y": 400, "w": 420, "h": 60}, confidence=0.95),
        _word("surya", "council", 3, {"x": 1000, "y": 400, "w": 300, "h": 60}, confidence=0.96),
    ]
    page = _page("surya", [_block("surya", [_line("surya", 0, words, {"x": 200, "y": 395, "w": 1200, "h": 70})])])
    return _rendering("surya", "surya/0.17.1", page, {})


def build_azure() -> dict:
    words = [
        _word("azure", "the", 0, {"x": 212, "y": 402, "w": 118, "h": 58}, confidence=0.98),
        _word("azure", "early", 1, {"x": 352, "y": 402, "w": 178, "h": 58}, confidence=0.97),
        _word("azure", "church-history", 2, {"x": 562, "y": 402, "w": 418, "h": 58}, confidence=0.96),
        _word("azure", "council", 3, {"x": 1002, "y": 402, "w": 298, "h": 58}, confidence=0.97),
    ]
    page = _page("azure", [_block("azure", [_line("azure", 0, words, {"x": 200, "y": 397, "w": 1200, "h": 66})])])
    return _rendering("azure_read", "azure-read-v4", page, {})


def build_tesseract() -> dict:
    join = _ds_id("oss-tesseract", "church-history")
    # "early" is deliberately mislabelled "marginalia"; its bbox is inside the
    # surya body zone, so the builder must zone it body by overlap, not by label.
    line1_words = [
        _word("oss-tesseract", "the", 0, {"x": 211, "y": 401, "w": 119, "h": 59}, confidence=0.90),
        _word("oss-tesseract", "early", 1, {"x": 351, "y": 401, "w": 179, "h": 59},
              confidence=0.88, zone_label="marginalia"),
        _word("oss-tesseract", "church-", 2, {"x": 561, "y": 401, "w": 210, "h": 59},
              confidence=0.85, join_id=join),
    ]
    line2_words = [
        _word("oss-tesseract", "history", 3, {"x": 210, "y": 470, "w": 230, "h": 59},
              confidence=0.86, join_id=join),
        _word("oss-tesseract", "council", 4, {"x": 470, "y": 470, "w": 300, "h": 59}, confidence=0.89),
    ]
    block = _block(
        "oss-tesseract",
        [
            _line("oss-tesseract", 0, line1_words, {"x": 200, "y": 396, "w": 600, "h": 68}),
            _line("oss-tesseract", 1, line2_words, {"x": 200, "y": 465, "w": 600, "h": 68}),
        ],
    )
    derived = {
        block["rendering_block_id"]: [
            {
                "derived_span_id": join,
                "operation": "joined_continuation",
                "contributor_observation_token_ids": [
                    _ot_id("oss-tesseract", "church-", 2),
                    _ot_id("oss-tesseract", "history", 3),
                ],
                "boundary_type": "line_break",
                "structured_text": "church history",
                "language_lane": "en",
                "dictionary_match": {
                    "matched": False,
                    "resource_id": "en-core",
                    "snapshot_hash": _sha256("dict"),
                    "matched_form": None,
                },
                "candidate_window": "church-history",
                "confidence_floor": 0.85,
            }
        ]
    }
    page = _page("oss-tesseract", [block])
    return _rendering("tesseract", "tesseract/5.5", page, derived)


def build_abbyy() -> dict:
    # ABBYY produces nothing at the church-history slot -> a skip in the WCT.
    words = [
        _word("ia-abbyy", "the", 0, {"x": 213, "y": 403, "w": 117, "h": 57}, confidence=0.91),
        _word("ia-abbyy", "early", 1, {"x": 353, "y": 403, "w": 177, "h": 57}, confidence=0.90),
        _word("ia-abbyy", "council", 2, {"x": 1003, "y": 403, "w": 297, "h": 57}, confidence=0.91),
    ]
    page = _page("ia-abbyy", [_block("ia-abbyy", [_line("ia-abbyy", 0, words, {"x": 200, "y": 398, "w": 1200, "h": 64})])])
    return _rendering("abbyy", "abbyy/luradocument-nsh-main", page, {})


def build_textract() -> dict:
    # Textract RAN on the page but produced only a header token ABOVE the surya
    # body zone (y=120 < body y=300) -> zero body tokens. It must still appear as
    # a skip at every body position (arch A section 5: an available engine that
    # produced nothing where it could have is a skip, never silently dropped).
    words = [
        _word("textract", "RELIGIOUS", 0, {"x": 600, "y": 120, "w": 400, "h": 60}, confidence=0.80),
    ]
    page = _page("textract", [_block("textract", [_line("textract", 0, words, {"x": 600, "y": 115, "w": 400, "h": 70})])])
    return _rendering("textract", "textract/detect-document-text-v1", page, {})


def build_merge() -> dict:
    # Kraken MERGES the two adjacent words "the" + "early" into one token
    # "theearly" (n:1), while surya/azure keep them separate. Exercises the
    # merge span-record path.
    words = [
        _word("kraken-merge", "theearly", 0, {"x": 210, "y": 400, "w": 320, "h": 60}, confidence=0.84),
        _word("kraken-merge", "church-history", 1, {"x": 560, "y": 400, "w": 420, "h": 60}, confidence=0.83),
        _word("kraken-merge", "council", 2, {"x": 1000, "y": 400, "w": 300, "h": 60}, confidence=0.85),
    ]
    page = _page("kraken-merge", [_block("kraken-merge", [_line("kraken-merge", 0, words, {"x": 200, "y": 395, "w": 1200, "h": 70})])])
    return _rendering("kraken", "kraken/7.0.2", page, {})


FIXTURES = {
    "rendering_surya.json": build_surya,
    "rendering_azure.json": build_azure,
    "rendering_tesseract.json": build_tesseract,
    "rendering_abbyy.json": build_abbyy,
    "rendering_textract.json": build_textract,
    "rendering_merge.json": build_merge,
}


def main() -> None:
    for name, builder in FIXTURES.items():
        path = OUT_DIR / name
        path.write_text(json.dumps(builder(), indent=2) + "\n", encoding="utf-8")
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
