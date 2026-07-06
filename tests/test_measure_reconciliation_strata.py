"""Strata-separation contract for the M2/M3 measurement harness.

The CCEL scoring reference is consensus-conditioned: a position is "gold" only when
the CCEL token equals the OCR reading after normalization, otherwise it is a
ccel_ocr_disagreement. M2 error and M3 accuracy are therefore correct-by-construction
on gold positions and wrong-by-construction on disagreement positions, so the pooled
headline rate is just the bucket mix. These tests pin the requirement that the harness
exposes the two strata separately and never presents the pooled rate as a bare
accuracy/error number.

Fixtures are built in-memory and written to tmp_path; nothing depends on the live
(gitignored) reports/ artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.tools.ocr_pipeline import measure_reconciliation as measure

PAGE_ID = "page_0010"
VOL_LABEL = "vol_01"

# Two engines in two independent family blocks. Both read correctly on gold positions
# (keeps abbyy/surya co-error below the collapse threshold so they resolve to two
# blocks, which M2's independent-agreement count requires).
ABBYY = {"engine_id": "ia-abbyy-v1", "family": "abbyy"}
SURYA = {"engine_id": "surya-v1", "family": "surya"}


def _span(engine: dict, raw_text: str, *, bbox: bool = False) -> dict:
    span = {
        "engine_id": engine["engine_id"],
        "family": engine["family"],
        "raw_text": raw_text,
        "raw_confidence": 0.9,
        "source_spans": [{"bbox": [0, 0, 10, 10]}] if bbox else [{}],
    }
    return span


def _position(position_id: str, candidates: list[dict], spans: list[dict]) -> dict:
    return {
        "position_id": position_id,
        "zone": {"zone_type": "body"},
        "script": {"text_level": {"label": "latin"}},
        "alignment_confidence": 0.5,
        "reference_bbox": [1, 1, 2, 2],
        "candidate_set": candidates,
        "span_records": spans,
    }


def _agree_position(position_id: str, reading: str) -> dict:
    """Single candidate attested by both blocks (an M2 auto-accept candidate)."""
    candidates = [
        {
            "candidate_id": f"c-{position_id}",
            "raw_reading": reading,
            "attesting_families": ["abbyy", "surya"],
            "attesting_engines": ["ia-abbyy-v1", "surya-v1"],
        }
    ]
    spans = [_span(ABBYY, reading, bbox=True), _span(SURYA, reading)]
    return _position(position_id, candidates, spans)


def _disagree_position(position_id: str, abbyy_reading: str, surya_reading: str) -> dict:
    """Two candidates, one per block (families disagree -> an M3 truth-rule position)."""
    candidates = [
        {
            "candidate_id": f"c-{position_id}-a",
            "raw_reading": abbyy_reading,
            "attesting_families": ["abbyy"],
            "attesting_engines": ["ia-abbyy-v1"],
        },
        {
            "candidate_id": f"c-{position_id}-b",
            "raw_reading": surya_reading,
            "attesting_families": ["surya"],
            "attesting_engines": ["surya-v1"],
        },
    ]
    spans = [_span(ABBYY, abbyy_reading, bbox=True), _span(SURYA, surya_reading)]
    return _position(position_id, candidates, spans)


def _build_fixture() -> dict:
    """Return WCT page, CCEL alignment proposal, and reconciled reviewer_queue dicts.

    Strata laid out so the circularity signature is unambiguous:
      M2 gold:        7 auto-accept rows, 0 errors (reading == CCEL).
      M2 disagreement: 2 auto-accept rows, 2 errors (reading != CCEL by construction).
      M3 gold:        2 rows, matrix choice == CCEL -> 0 wrong (accuracy 1.0).
      M3 disagreement: 2 rows, matrix choice != CCEL -> 2 wrong (accuracy 0.0).
    """
    positions: list[dict] = []
    gold_candidates: list[dict] = []
    reviewer_queue: list[dict] = []
    reconciled_queue: list[dict] = []

    # --- M2 gold: both blocks agree on the CCEL reading ---
    for i in range(1, 8):
        pid = f"vol01:0010:body:0:0:g{i}"
        positions.append(_agree_position(pid, "grace"))
        gold_candidates.append({"position_id": pid, "ccel_token": "grace"})

    # --- M2 disagreement: both blocks agree on a reading that differs from CCEL ---
    for i in range(1, 3):
        pid = f"vol01:0010:body:0:0:d{i}"
        positions.append(_agree_position(pid, "wlth"))
        reviewer_queue.append(
            {"position_id": pid, "reason": "ccel_ocr_disagreement", "ccel_token": "with"}
        )

    # --- M3 gold: blocks disagree, matrix choice equals CCEL (correct by construction) ---
    for i in range(1, 3):
        pid = f"vol01:0010:body:0:0:mg{i}"
        positions.append(_disagree_position(pid, "merit", "rnerit"))
        gold_candidates.append({"position_id": pid, "ccel_token": "merit"})
        reconciled_queue.append({"position_id": pid, "chosen_reading": "merit"})

    # --- M3 disagreement: blocks disagree, matrix choice differs from CCEL (wrong) ---
    for i in range(1, 3):
        pid = f"vol01:0010:body:0:0:md{i}"
        positions.append(_disagree_position(pid, "faith", "faitb"))
        reviewer_queue.append(
            {"position_id": pid, "reason": "ccel_ocr_disagreement", "ccel_token": "hope"}
        )
        reconciled_queue.append({"position_id": pid, "chosen_reading": "faith"})

    wct = {
        "page_id": PAGE_ID,
        "work_id": "schaff-herzog",
        "volume_id": "vol_01",
        "source_image": {"path": "raw/internet-archive/schaff-herzog-pages/vol_01/page_0010.jpg"},
        "available_engines": [ABBYY, SURYA],
        "reading_order": [p["position_id"] for p in positions],
        "positions": positions,
    }
    alignment = {
        "artifact_kind": "ccel-wct-alignment-proposal",
        "status": "PROPOSAL_NOT_GOLD",
        "page_id": PAGE_ID,
        "gold_candidates": gold_candidates,
        "reviewer_queue": reviewer_queue,
    }
    reconciled = {"page_id": PAGE_ID, "queue": reconciled_queue}
    return {"wct": wct, "alignment": alignment, "reconciled": reconciled}


@pytest.fixture()
def measurements(tmp_path: Path) -> dict:
    fixture = _build_fixture()
    wct_root = tmp_path / "wct"
    gold_root = tmp_path / "gold"
    reconciled_root = tmp_path / "reconciled"
    for root in (wct_root, gold_root, reconciled_root):
        (root / VOL_LABEL).mkdir(parents=True)
    (wct_root / VOL_LABEL / f"{PAGE_ID}.json").write_text(
        json.dumps(fixture["wct"]), encoding="utf-8"
    )
    (gold_root / VOL_LABEL / f"ccel_wct_alignment_{PAGE_ID}.json").write_text(
        json.dumps(fixture["alignment"]), encoding="utf-8"
    )
    (reconciled_root / VOL_LABEL / f"{PAGE_ID}.reviewer_queue.json").write_text(
        json.dumps(fixture["reconciled"]), encoding="utf-8"
    )
    return measure.build_measurements(
        volume=1,
        pages=[10],
        wct_root=wct_root,
        reconciled_root=reconciled_root,
        gold_root=gold_root,
    )


def test_ccel_refs_and_strata_membership_mirror_each_other() -> None:
    # Guards against drift between the reference builder and the stratum classifier:
    # every scored position must have exactly one stratum.
    fixture = _build_fixture()
    refs = measure._ccel_refs(fixture["alignment"])
    strata = measure._ccel_strata(fixture["alignment"])
    assert set(refs) == set(strata)
    assert set(strata.values()) == {"gold", "ccel_ocr_disagreement"}


def test_m2_exposes_strata_with_circularity_signature(measurements: dict) -> None:
    m2 = measurements["m2_auto_accept_audit"]
    strata = m2["strata"]

    assert set(strata) == {"gold", "ccel_ocr_disagreement"}
    assert strata["gold"]["n"] == 7
    assert strata["gold"]["errors"] == 0
    # The circularity signature: every disagreement-stratum row is wrong by construction.
    assert strata["ccel_ocr_disagreement"]["n"] == 2
    assert strata["ccel_ocr_disagreement"]["errors"] == 2
    assert strata["ccel_ocr_disagreement"]["error_rate"] == 1.0


def test_m2_pooled_rate_is_flagged_not_bare(measurements: dict) -> None:
    headline = measurements["m2_auto_accept_audit"]["headline"]
    # A bare `error_rate` would read as an OCR/auto-accept accuracy number; it must be gone.
    assert "error_rate" not in headline
    assert headline["pooled_error_rate_circular"] == pytest.approx(2 / 9, abs=1e-6)
    assert headline["circularity_note"]


def test_m3_exposes_strata_and_flags_pooled_accuracy(measurements: dict) -> None:
    matrix = measurements["m3_truth_rule_ab"]["matrix_rule"]
    strata = matrix["strata"]

    assert set(strata) == {"gold", "ccel_ocr_disagreement"}
    assert strata["gold"]["n"] == 2
    assert strata["gold"]["wrong"] == 0
    assert strata["gold"]["accuracy"] == 1.0
    assert strata["ccel_ocr_disagreement"]["n"] == 2
    assert strata["ccel_ocr_disagreement"]["wrong"] == 2
    assert strata["ccel_ocr_disagreement"]["accuracy"] == 0.0

    # The bare reconciler-quality accuracy must be flagged, not presented plainly.
    assert "auto_choice_accuracy" not in matrix
    assert matrix["pooled_auto_choice_accuracy_circular"] == pytest.approx(0.5, abs=1e-6)
    assert matrix["circularity_note"]
    # The A/B is not interpretable as reconciler quality under this reference.
    assert measurements["m3_truth_rule_ab"]["interpretation_note"]


def test_other_measurement_shapes_unchanged(measurements: dict) -> None:
    # M0/M1/family_independence/adjudication_queue keep their existing top-level shape.
    assert set(measurements["family_independence"]) == {
        "artifact_kind",
        "generated_at",
        "pages",
        "reference",
        "fail_closed_rule",
        "family_blocks",
        "dependence_threshold",
    }
    assert set(measurements["m0_single_best_baseline_quality"]) == {
        "artifact_kind",
        "generated_at",
        "pages",
        "reference",
        "population",
        "engines",
    }
    assert set(measurements["m1_confidence_calibration"]) == {
        "artifact_kind",
        "generated_at",
        "pages",
        "reference",
        "population",
        "bins",
        "engines",
    }
    assert set(measurements["adjudication_queue"]) == {
        "artifact_kind",
        "generated_at",
        "pages",
        "reference",
        "population",
        "items",
    }
    # Two independent family blocks (abbyy / surya stay separate) is the precondition
    # that lets M2 see independent agreement at all.
    assert len(set(measurements["family_independence"]["family_blocks"].values())) == 2
