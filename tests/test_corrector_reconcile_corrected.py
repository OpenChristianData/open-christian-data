import json
import pathlib

import jsonschema

from build.lib.gold_free_corrector.column_vote import ColumnVoteResult, correct_position
from build.lib.gold_free_corrector.decide import decide
from build.lib.gold_free_corrector.reconcile_corrected import reconcile_corrected
from build.lib.s3_reconciler import ReconcileResult

SCHEMA_PATH = pathlib.Path("schemas/v1/corrected-page-v1.schema.json")


def _make_position(position_id: str, readings: list[tuple[str, list[str]]]) -> dict:
    """Build a minimal WCT position.
    readings: list of (text, [family, ...]) pairs - one per candidate.
    """
    candidates = [
        {
            "candidate_id": f"{position_id}-c{i}",
            "raw_reading": text,
            "candidate_key": text,
            "attesting_families": families,
            "attesting_engines": [f"eng-{families[0]}"] if families else [],
        }
        for i, (text, families) in enumerate(readings)
    ]
    return {
        "position_id": position_id,
        "candidate_set": candidates,
        "span_records": [],
        "zone": {"zone_id": "zone-body", "zone_type": "body"},
        "script": {"text_level": {"label": "latin"}},
        "alignment_confidence": 0.9,
    }


def _make_wct_page(positions: list[dict]) -> dict:
    return {
        "page_id": "vol_01_page_001",
        "volume_id": "vol_01",
        "positions": positions,
        "reading_order": [p["position_id"] for p in positions],
    }


def _make_work_meta() -> dict:
    return {
        "id": "test-work",
        "title": "Test Work",
        "author_slug": "test-author",
        "author_display_name": "Test Author",
        "language": "en",
        "pd_anchor": "vol_01",
    }


def _thresholds_accept(level: str = "L1") -> dict:
    """Thresholds that allow auto-accept for the given level in body region."""
    return {
        "body": {
            level: {
                "auto_accept_enabled": True,
                "max_real_word_error_rate": None,
            }
        }
    }


def _thresholds_reject() -> dict:
    """Thresholds where nothing is auto-accept-eligible."""
    return {
        "body": {
            "L1": {"auto_accept_enabled": False},
        }
    }


def _reconcile(
    tmp_path: pathlib.Path,
    positions: list[dict],
    corrected_positions: list[ColumnVoteResult],
) -> ReconcileResult:
    return reconcile_corrected(
        _make_wct_page(positions),
        _make_work_meta(),
        corrected_positions,
        sidecar_path=tmp_path / "sidecar.json",
        occurred_at="2026-06-06T00:00:00Z",
    )


def test_uses_corrector_reading_on_accept(tmp_path: pathlib.Path) -> None:
    position = _make_position("pos-accept", [("Lord", ["a", "b"]), ("Lard", ["c"])])
    cvr = correct_position(position)
    decided = decide(cvr, _thresholds_accept("L1"), region_class="body")

    assert decided.corrected_position["chosen_action"] == "release_accepted"
    chosen_index = decided.corrected_position["chosen_reading_index"]
    chosen_text = decided.corrected_position["derivable_readings"][chosen_index]["text"]

    result = _reconcile(tmp_path, [position], [decided])

    block = result.reconciled_record["blocks"][0]
    assert block["original_text"] == chosen_text


def test_falls_through_to_best_candidate_on_route(tmp_path: pathlib.Path) -> None:
    position = _make_position("pos-route", [("Smyth", ["a", "b"]), ("Smith", ["c"])])
    routed_cp = {
        "position_id": "pos-route",
        "protected_class": "proper_name",
        "derivable_readings": [
            {
                "derivation_level": "L1",
                "origin_kind": "machine_composed",
                "text": "Smith",
                "scores": {"confidence": 0.9, "character_vote_score": 0.9},
            }
        ],
        "chosen_reading_index": 0,
        "chosen_action": "release_flagged",
    }
    routed_cvr = ColumnVoteResult(corrected_position=routed_cp, columns=[], agreement_score=0.9)
    decided = decide(routed_cvr, _thresholds_accept(), region_class="body")

    assert decided.corrected_position["chosen_action"] == "route_human_review"

    result = _reconcile(tmp_path, [position], [decided])

    assert isinstance(result, ReconcileResult)
    assert result.reconciled_record["blocks"][0]["original_text"] == "Smyth"


def test_falls_through_on_flag(tmp_path: pathlib.Path) -> None:
    position = _make_position("pos-flag", [("faith", ["a", "b"]), ("fayth", ["c"])])
    decided = decide(correct_position(position), _thresholds_reject(), region_class="body")

    assert decided.corrected_position["chosen_action"] == "release_flagged"

    result = _reconcile(tmp_path, [position], [decided])

    assert isinstance(result, ReconcileResult)


def test_sidecar_file_written(tmp_path: pathlib.Path) -> None:
    positions = [
        _make_position("pos-1", [("alpha", ["a", "b"]), ("alfa", ["c"])]),
        _make_position("pos-2", [("beta", ["a", "b"]), ("betta", ["c"])]),
    ]
    corrected = [
        decide(correct_position(position), _thresholds_accept("L1"), region_class="body")
        for position in positions
    ]

    _reconcile(tmp_path, positions, corrected)

    assert (tmp_path / "sidecar.json").exists()


def test_sidecar_validates_against_schema(tmp_path: pathlib.Path) -> None:
    positions = [
        _make_position("pos-1", [("alpha", ["a", "b"]), ("alfa", ["c"])]),
        _make_position("pos-2", [("beta", ["a", "b"]), ("betta", ["c"])]),
    ]
    corrected = [
        decide(correct_position(position), _thresholds_accept("L1"), region_class="body")
        for position in positions
    ]

    _reconcile(tmp_path, positions, corrected)
    sidecar = json.loads((tmp_path / "sidecar.json").read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    jsonschema.validate(sidecar, schema)


def test_sidecar_covers_all_wct_positions(tmp_path: pathlib.Path) -> None:
    positions = [
        _make_position("pos-1", [("alpha", ["a", "b"]), ("alfa", ["c"])]),
        _make_position("pos-2", [("beta", ["a", "b"]), ("betta", ["c"])]),
        _make_position("pos-3", [("gamma", ["a", "b"]), ("gama", ["c"])]),
    ]
    corrected = [
        decide(correct_position(position), _thresholds_accept("L1"), region_class="body")
        for position in positions
    ]

    _reconcile(tmp_path, positions, corrected)
    sidecar = json.loads((tmp_path / "sidecar.json").read_text(encoding="utf-8"))

    assert len(sidecar["positions"]) == 3


def test_returns_reconcile_result(tmp_path: pathlib.Path) -> None:
    position = _make_position("pos-result", [("grace", ["a", "b"]), ("grace", ["c"])])
    corrected = [decide(correct_position(position), _thresholds_accept("L0"), region_class="body")]

    result = _reconcile(tmp_path, [position], corrected)

    assert isinstance(result, ReconcileResult)
    assert result.reconciled_record
