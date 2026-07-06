import json
import pathlib

import jsonschema

from build.lib.gold_free_corrector.column_vote import correct_position
from build.lib.gold_free_corrector.decide import decide
from build.lib.gold_free_corrector.reconcile_corrected import reconcile_corrected
from build.lib.gold_free_corrector.supersession import (
    make_decision_event_id,
    mark_superseded,
)
from tests.test_corrector_reconcile_corrected import (
    _make_position,
    _make_wct_page,
    _make_work_meta,
    _thresholds_accept,
)

SCHEMA_PATH = pathlib.Path("schemas/v1/corrected-page-v1.schema.json")


def test_decision_event_id_deterministic() -> None:
    first = make_decision_event_id("work-1", "vol-1", "page-1", "pos-1", "policy-1")
    second = make_decision_event_id("work-1", "vol-1", "page-1", "pos-1", "policy-1")

    assert first == second


def test_decision_event_id_unique_per_position() -> None:
    first = make_decision_event_id("work-1", "vol-1", "page-1", "pos-1", "policy-1")
    second = make_decision_event_id("work-1", "vol-1", "page-1", "pos-2", "policy-1")

    assert first != second


def test_decision_event_id_contains_all_components() -> None:
    event_id = make_decision_event_id("work-1", "vol-1", "page-1", "pos-1", "policy-1")

    assert "work-1" in event_id
    assert "vol-1" in event_id
    assert "page-1" in event_id
    assert "pos-1" in event_id
    assert "policy-1" in event_id


def test_mark_superseded_sets_field() -> None:
    old_position = {"position_id": "pos-1", "chosen_action": "release_accepted"}

    result = mark_superseded(old_position, "new-id-xyz")

    assert result["superseded_by"] == "new-id-xyz"


def test_mark_superseded_preserves_other_fields() -> None:
    old_position = {"position_id": "pos-1", "chosen_action": "release_accepted"}

    result = mark_superseded(old_position, "new-id-xyz")

    assert result["position_id"] == old_position["position_id"]
    assert result["chosen_action"] == old_position["chosen_action"]


def test_mark_superseded_does_not_mutate_original() -> None:
    old_position = {"position_id": "pos-1", "chosen_action": "release_accepted"}

    mark_superseded(old_position, "new-id-xyz")

    assert "superseded_by" not in old_position


def test_sidecar_contains_decision_event_id(tmp_path: pathlib.Path) -> None:
    position = _make_position("pos-1", [("alpha", ["a", "b"]), ("alfa", ["c"])])
    corrected = [decide(correct_position(position), _thresholds_accept("L1"), region_class="body")]
    work_meta = _make_work_meta()
    sidecar_path = tmp_path / "sidecar.json"

    reconcile_corrected(
        _make_wct_page([position]),
        work_meta,
        corrected,
        sidecar_path=sidecar_path,
        occurred_at="2026-06-06T00:00:00Z",
        matrix_policy_version="m14-policy",
    )
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))

    assert all("decision_event_id" in position for position in sidecar["positions"])
    assert work_meta["id"] in sidecar["positions"][0]["decision_event_id"]


def test_sidecar_validates_after_m14(tmp_path: pathlib.Path) -> None:
    position = _make_position("pos-1", [("alpha", ["a", "b"]), ("alfa", ["c"])])
    corrected = [decide(correct_position(position), _thresholds_accept("L1"), region_class="body")]
    sidecar_path = tmp_path / "sidecar.json"

    reconcile_corrected(
        _make_wct_page([position]),
        _make_work_meta(),
        corrected,
        sidecar_path=sidecar_path,
        occurred_at="2026-06-06T00:00:00Z",
        matrix_policy_version="m14-policy",
    )
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    jsonschema.validate(sidecar, schema)
