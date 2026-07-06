"""TDD contract for the CCEL-word-to-WCT-position aligner (Step 2 headline tool).

Synthetic WCT + CCEL fixtures mirror the real artifact shapes (a WCT page's
reading_order + per-position candidate_set; a ccel-page-gold-proposal's per-page
ccel_page_text). The real-data integration test is skipif-gated on the real WCT +
proposal existing (TEST-13 / raw-read guard).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.ocr_pipeline.align_ccel_to_wct import (  # noqa: E402
    PROPOSAL_STATUS,
    align_page,
)

_REAL_WCT = REPO_ROOT / "reports" / "wct" / "vol_01" / "page_0010.json"
_REAL_PROPOSAL = REPO_ROOT / "reports" / "gold" / "vol_01" / "ccel_page_gold_proposal.json"


def _candidate(reading: str, engines: list[str], families: list[str]) -> dict:
    return {
        "candidate_id": "cand_001",
        "raw_reading": reading,
        "candidate_key": reading,
        "normalisation_applied": ["unicode_nfkc"],
        "attesting_engines": engines,
        "attesting_families": families,
    }


def _position(position_id: str, *candidates: dict) -> dict:
    return {
        "position_id": position_id,
        "zone": {"zone_id": "z_body_1", "zone_type": "body", "column": 1,
                 "line_order": 0, "position_order": 0},
        "reference_bbox": {"x": 100, "y": 200, "w": 80, "h": 40},
        "candidate_set": list(candidates),
    }


def _wct_page(
    readings: list[str],
    *,
    page_id: str = "page_0010",
    edition_page_key: dict | None = None,
) -> dict:
    """A minimal WCT page: one body position per OCR consensus reading, in order."""
    positions = []
    reading_order = []
    for i, reading in enumerate(readings):
        pid = f"vol_01:{page_id}:body:c1:l000:p{i:03d}"
        positions.append(
            _position(pid, _candidate(reading, ["tesseract-py314-v1", "ia-abbyy-v1"],
                                      ["tesseract", "abbyy"]))
        )
        reading_order.append(pid)
    page = {
        "schema_version": "word-confusion-table-v1",
        "work_id": "schaff-herzog-encyclopedia",
        "volume_id": "vol_01",
        "page_id": page_id,
        "reading_order": reading_order,
        "positions": positions,
    }
    if edition_page_key is not None:
        page["edition_page_key"] = dict(edition_page_key)
    return page


def _ccel_proposal(
    text: str,
    *,
    page_native_id: str = "page_0010",
    edition_page_key: dict | None = None,
) -> dict:
    page = {
        "page_sequence": 10,
        "page_native_id": page_native_id,
        "scan_path": "raw/internet-archive/schaff-herzog-pages/vol_01/page_0010.jpg",
        "ccel_pb_n": "10",
        "ccel_page_text": text,
        "char_count": len(text),
        "word_count": len(text.split()),
    }
    if edition_page_key is not None:
        page["edition_page_key"] = dict(edition_page_key)
    return {
        "artifact_kind": "ccel-page-gold-proposal",
        "status": "PROPOSAL_NOT_GOLD",
        "volume": 1,
        "source": {"source_basis": "ccel:thml:schaff/encyc01.xml#pb"},
        "pages": [page],
    }


def test_agreement_becomes_gold_candidate() -> None:
    wct = _wct_page(["merit", "with", "God"])
    ccel = _ccel_proposal("merit with God")
    artifact = align_page(wct, ccel)

    assert artifact["status"] == PROPOSAL_STATUS
    cand_positions = {c["position_id"] for c in artifact["gold_candidates"]}
    # All three OCR readings match CCEL exactly -> gold candidates, none queued.
    assert len(artifact["gold_candidates"]) == 3
    assert artifact["reviewer_queue"] == []
    gc = artifact["gold_candidates"][0]
    assert gc["ccel_token"] == "merit"
    assert gc["ocr_reading"] == "merit"
    assert wct["positions"][0]["position_id"] in cand_positions


def test_disagreement_routes_to_reviewer_queue() -> None:
    # OCR read "rnerit" (m->rn split) where CCEL has "merit": a real disagreement.
    wct = _wct_page(["rnerit", "with", "God"])
    ccel = _ccel_proposal("merit with God")
    artifact = align_page(wct, ccel)

    queued = artifact["reviewer_queue"]
    assert len(queued) == 1
    item = queued[0]
    assert item["position_id"] == wct["positions"][0]["position_id"]
    assert item["ccel_token"] == "merit"
    assert item["chosen_reading"] == "rnerit"        # mirrors s3 reviewer_queue field name
    assert item["reason"] == "ccel_ocr_disagreement"
    assert "rnerit" in item["candidates"]
    # The two agreeing tokens are still gold candidates.
    assert {c["ocr_reading"] for c in artifact["gold_candidates"]} == {"with", "God"}


def test_wct_position_without_ccel_word_routes_to_review() -> None:
    # A running-header token the OCR carries but CCEL omits (by design).
    wct = _wct_page(["RELIGIOUS", "merit", "with", "God"])
    ccel = _ccel_proposal("merit with God")
    artifact = align_page(wct, ccel)

    queued = {item["reason"] for item in artifact["reviewer_queue"]}
    assert "ccel_omits_token" in queued
    omit = next(i for i in artifact["reviewer_queue"] if i["reason"] == "ccel_omits_token")
    assert omit["chosen_reading"] == "RELIGIOUS"
    assert omit["ccel_token"] is None


def test_ccel_word_without_wct_position_routes_to_review() -> None:
    # CCEL has a word the OCR dropped entirely -> uncertain alignment, route to review.
    wct = _wct_page(["merit", "God"])
    ccel = _ccel_proposal("merit with God")
    artifact = align_page(wct, ccel)

    reasons = [i["reason"] for i in artifact["reviewer_queue"]]
    assert "ccel_token_unaligned" in reasons
    unaligned = next(i for i in artifact["reviewer_queue"] if i["reason"] == "ccel_token_unaligned")
    assert unaligned["ccel_token"] == "with"
    assert unaligned["position_id"] is None


def test_output_never_mints_gold_record() -> None:
    wct = _wct_page(["merit"])
    ccel = _ccel_proposal("merit")
    artifact = align_page(wct, ccel)
    # PROPOSAL_NOT_GOLD, never a gold-record-v1; no machine-authored ground_truth_text.
    assert artifact["status"] == "PROPOSAL_NOT_GOLD"
    assert "schema_version" not in artifact or artifact.get("schema_version") != "gold-record-v1"
    blob = json.dumps(artifact)
    assert "ground_truth_text" not in blob


def test_coverage_and_disagreement_rate() -> None:
    wct = _wct_page(["merit", "wlth", "God"])     # OCR misreads "with" as "wlth"
    ccel = _ccel_proposal("merit with God")
    artifact = align_page(wct, ccel)
    cov = artifact["coverage"]
    assert cov["gold_candidates"] == 2
    assert cov["reviewer_queue_items"] == 1
    # disagreement rate = queued / (gold + queued); reported rounded to 4 dp.
    assert cov["disagreement_rate"] == round(1 / 3, 4)


def test_page_selected_by_native_id_join() -> None:
    # The proposal may carry several pages; the aligner joins on page_native_id.
    wct = _wct_page(["merit"], page_id="page_0010")
    ccel = _ccel_proposal("merit", page_native_id="page_0010")
    ccel["pages"].insert(0, {
        "page_sequence": 1, "page_native_id": "leaf_0037", "scan_path": "x",
        "ccel_pb_n": "1", "ccel_page_text": "Aachen Synods", "char_count": 13, "word_count": 2,
    })
    artifact = align_page(wct, ccel)
    assert len(artifact["gold_candidates"]) == 1
    assert artifact["gold_candidates"][0]["ccel_token"] == "merit"


def test_keyless_page_selected_by_edition_page_key_before_filename() -> None:
    key = {"section": "body", "anchor": 96, "ordinal": 0}
    wct = _wct_page(["merit"], page_id="page_0096", edition_page_key=key)
    ccel = _ccel_proposal("merit", page_native_id="different_stem", edition_page_key=key)
    ccel["pages"].insert(0, {
        "page_sequence": 10,
        "page_native_id": "page_0096",
        "edition_page_key": {"section": "body", "anchor": 10, "ordinal": 0},
        "scan_path": "raw/x/page_0096.jpg",
        "ccel_pb_n": "10",
        "ccel_page_text": "wrong page",
        "char_count": 10,
        "word_count": 2,
    })

    artifact = align_page(wct, ccel)

    assert artifact["coverage"]["gold_candidates"] == 1
    assert artifact["edition_page_key"] == key
    assert artifact["gold_candidates"][0]["ccel_token"] == "merit"


def test_non_body_position_routes_to_ccel_omits_not_gold() -> None:
    # NW may pair a CCEL body word with a non-body WCT position (running header,
    # printed folio) when both normalise to the same string (e.g. CCEL "the" <->
    # header "THE").  Those positions must route to ccel_omits_token, not gold.
    wct = _wct_page(["merit", "with"])
    # Inject a running-header position at the front; NW will pair CCEL's first
    # word "the" with it because _norm("THE") == _norm("the").
    header_pid = "vol_01:page_0010:running_header:c0:l000:p000"
    wct["positions"].insert(0, {
        "position_id": header_pid,
        "zone": {"zone_id": "z_running_header_0", "zone_type": "running_header",
                 "column": 0, "line_order": 0, "position_order": 0},
        "reference_bbox": {"x": 100, "y": 10, "w": 300, "h": 30},
        "candidate_set": [_candidate("THE", ["tesseract-py314-v1"], ["tesseract"])],
    })
    wct["reading_order"].insert(0, header_pid)
    ccel = _ccel_proposal("the merit with")    # "the" aligns to header "THE"

    artifact = align_page(wct, ccel)

    gold_pids = {c["position_id"] for c in artifact["gold_candidates"]}
    assert header_pid not in gold_pids, "non-body position leaked into gold_candidates"
    # Running-header position must appear as ccel_omits_token.
    omit_items = [i for i in artifact["reviewer_queue"] if i["position_id"] == header_pid]
    assert len(omit_items) == 1
    assert omit_items[0]["reason"] == "ccel_omits_token"
    # The displaced CCEL token "the" must appear as ccel_token_unaligned.
    unaligned = [i for i in artifact["reviewer_queue"] if i["reason"] == "ccel_token_unaligned"]
    assert any(u["ccel_token"] == "the" for u in unaligned)


@pytest.mark.slow  # O(1073x1142) NW over the real page in pure Python (~2 min).
@pytest.mark.skipif(
    not (_REAL_WCT.exists() and _REAL_PROPOSAL.exists()),
    reason="real WCT / CCEL proposal not built (run the thin-slice chain first)",
)
def test_real_page10_alignment_integration() -> None:
    wct = json.loads(_REAL_WCT.read_text(encoding="utf-8"))
    ccel = json.loads(_REAL_PROPOSAL.read_text(encoding="utf-8"))
    artifact = align_page(wct, ccel)

    assert artifact["status"] == "PROPOSAL_NOT_GOLD"
    cov = artifact["coverage"]
    # Real page_0010: ~1073 CCEL words vs ~1142 WCT positions.
    assert cov["gold_candidates"] > 200          # a substantial agreeing core
    assert cov["reviewer_queue_items"] > 0        # headers/folios/misreads surface
    assert 0.0 < cov["disagreement_rate"] < 1.0
    # Every gold candidate's position_id is a real WCT position.
    wct_ids = {p["position_id"] for p in wct["positions"]}
    assert all(c["position_id"] in wct_ids for c in artifact["gold_candidates"])
    # No non-body positions (running headers, printed folios) in gold_candidates.
    assert all(
        c["position_id"].split(":")[2] == "body"
        for c in artifact["gold_candidates"]
    ), "non-body position leaked into gold_candidates"
