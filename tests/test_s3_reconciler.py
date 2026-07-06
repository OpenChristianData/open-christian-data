"""B10 -- S3 degraded reconciler, failing-first tests (TEST-16).

Architectural slot: S3 (arch5 reconciler), degraded mode on vol_01. The reconciler
consumes one word-confusion-table-v1 page (B6 / S2.5 output) plus a work-meta
envelope and emits:
  * a reconciled_record (validates against schemas/v1/reconciled_record.schema.json),
  * matrix-event candidates (matrix-events-v1 conformant),
  * a reviewer queue.

These tests are the B10 TDD contract from the arch D plan (section 2, B10 row) and
the build prompt -- written-failed-then-satisfied, never authored after the code:

  1. reconciled conformance     -- output validates against reconciled_record.schema.json.
  2. region_class policy id      -- every block carries the region_class policy id ("v1");
                                    a record missing it is rejected.
  3. unconfirmed routing         -- consensus_unconfirmed + external_check_absent route to
                                    the reviewer queue (never silently resolved); a
                                    dictionary corroboration is a post-alignment signal,
                                    NEVER a matrix label (lock-amended bar, archC section 3).

The WCT input is a synthetic vol_01 fixture (tests/fixtures/s3_reconciler/) because
the real vol_01 WCT is thin; the B10 prompt authorises this. The fixture is proven a
genuine word-confusion-table-v1 instance by test_fixture_is_valid_wct.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.s3_reconciler import (  # noqa: E402
    REGION_CLASS_POLICY_ID,
    RegionClassStampError,
    assign_region_class,
    reconcile_degraded,
    validate_region_class_stamp,
)

SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "s3_reconciler"
OCCURRED_AT = "2026-05-30T00:00:00+00:00"


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def _wct() -> dict:
    return json.loads((FIXTURE_DIR / "wct_vol01_synthetic.json").read_text(encoding="utf-8"))


def _meta() -> dict:
    return json.loads((FIXTURE_DIR / "work_meta.json").read_text(encoding="utf-8"))


def _run(dictionary_signals: dict | None = None):
    return reconcile_degraded(
        _wct(),
        _meta(),
        occurred_at=OCCURRED_AT,
        dictionary_signals=dictionary_signals,
    )


# --------------------------------------------------------------------------- #
# Fixture legitimacy: the input is a real word-confusion-table-v1 instance.
# --------------------------------------------------------------------------- #


def test_fixture_is_valid_wct() -> None:
    errors = list(jsonschema.Draft202012Validator(_schema("word-confusion-table-v1")).iter_errors(_wct()))
    assert errors == [], f"synthetic WCT fixture invalid: {errors[:1]}"


# --------------------------------------------------------------------------- #
# 1. reconciled conformance.
# --------------------------------------------------------------------------- #


def test_reconciled_output_validates_schema() -> None:
    result = _run()
    jsonschema.validate(instance=result.reconciled_record, schema=_schema("reconciled_record"))


def test_reconciled_record_has_a_block_per_zone() -> None:
    result = _run()
    blocks = result.reconciled_record["blocks"]
    # The fixture has two zones (body, running-header) -> two assembled blocks.
    assert len(blocks) == 2
    body = next(b for b in blocks if b["annotations"]["region_class"]["region_class"] == "body")
    # The body zone carried three reading slots; their chosen readings flow into the text.
    assert "church" in body["original_text"]


# --------------------------------------------------------------------------- #
# 2. region_class policy id stamped.
# --------------------------------------------------------------------------- #


def test_region_class_policy_id_stamped_on_every_block() -> None:
    result = _run()
    for block in result.reconciled_record["blocks"]:
        stamp = block["annotations"]["region_class"]
        assert stamp["policy_id"] == REGION_CLASS_POLICY_ID == "v1"
        assert stamp["region_class"], "region_class value missing from the stamp"
    # The guard accepts a correctly-stamped record.
    validate_region_class_stamp(result.reconciled_record)


def test_record_without_region_class_stamp_is_rejected() -> None:
    result = _run()
    record = result.reconciled_record
    # Strip the stamp from one block -> the guard must reject the record.
    record["blocks"][0]["annotations"].pop("region_class", None)
    with pytest.raises(RegionClassStampError):
        validate_region_class_stamp(record)


def test_region_class_policy_assignment_inputs() -> None:
    # zone_type base mappings.
    assert assign_region_class("body", "latin").region_class == "body"
    assert assign_region_class("footnote", "latin").region_class == "footnote"
    assert assign_region_class("bibliography", "latin").region_class == "bibliography_entry"
    # Greek/Hebrew script override (medium-confidence structural rule, archC section 6 item 23).
    assert assign_region_class("body", "greek").region_class == "foreign_language_greek"
    assert assign_region_class("body", "hebrew").region_class == "foreign_language_hebrew"
    # A layout label with no clean region_class home -> unknown + pending, NEVER a silent body fallback.
    unknown = assign_region_class("running-header", "latin")
    assert unknown.region_class == "unknown"
    assert unknown.pending is True
    # Latin/German foreign override needs explicit high confidence (degraded default: no override).
    assert assign_region_class("body", "latin", latin_german_high_conf=False).region_class == "body"


# --------------------------------------------------------------------------- #
# 3. unconfirmed routing + dictionary-is-not-a-matrix-label.
# --------------------------------------------------------------------------- #


def test_consensus_unconfirmed_routes_to_reviewer_queue() -> None:
    result = _run()
    queue = result.reviewer_queue
    reasons = {item["position_id"]: item for item in queue}
    # p_body_1: two families agree but degraded mode never has family-map readiness ->
    # consensus_unconfirmed + external_check_absent, routed (not silently resolved).
    assert "p_body_1" in reasons
    assert reasons["p_body_1"]["reason"] == "consensus_unconfirmed"
    assert reasons["p_body_1"]["external_check_absent"] is True


def test_genuine_disagreement_routes_as_dispute() -> None:
    result = _run()
    reasons = {item["position_id"]: item for item in result.reviewer_queue}
    # p_body_2: Christ vs Chvist -> a real dispute, routed to review.
    assert reasons.get("p_body_2", {}).get("reason") == "dispute"


def test_region_class_unknown_routes_pending_never_silent_body() -> None:
    result = _run()
    reasons = {item["position_id"]: item for item in result.reviewer_queue}
    assert reasons.get("p_head_1", {}).get("reason") == "region_class_pending"
    assert reasons["p_head_1"]["region_class"] == "unknown"


def test_no_matrix_label_emitted_in_degraded_mode() -> None:
    # In degraded mode (no family-map readiness, no promoted matrix snapshot), NOTHING is
    # measurement-eligible: no candidate may carry the labels_emitted outcome.
    result = _run()
    outcomes = {c["outcome"] for c in result.matrix_event_candidates}
    assert "labels_emitted" not in outcomes
    assert outcomes <= {"not_measurement_eligible", "queued_region_class_pending"}


def test_dictionary_corroboration_is_post_alignment_signal_never_matrix_label() -> None:
    # A dictionary check that corroborates the p_body_1 consensus reading must be recorded
    # as a POST-ALIGNMENT signal, never converted into a matrix training label (archC
    # section 3 lock-amendment to arch5 section 9.2 -- the named stale spot).
    result = _run(dictionary_signals={"p_body_1": {"reading": "church", "status": "corroborated"}})
    signals = [s for s in result.post_alignment_signals if s["position_id"] == "p_body_1"]
    assert signals, "dictionary corroboration was dropped instead of recorded as a signal"
    assert signals[0]["kind"] == "dictionary_corroboration"
    assert signals[0]["is_matrix_label"] is False
    # The dictionary corroboration did NOT make p_body_1 measurement-eligible.
    assert "labels_emitted" not in {c["outcome"] for c in result.matrix_event_candidates}


# --------------------------------------------------------------------------- #
# Conformance: matrix-event candidates validate against matrix-events-v1.
# --------------------------------------------------------------------------- #


def test_matrix_event_candidates_conform_to_schema() -> None:
    result = _run()
    schema = _schema("matrix-events-v1")
    validator = jsonschema.Draft202012Validator(schema)
    assert result.matrix_event_candidates, "expected at least one matrix-event candidate"
    for candidate in result.matrix_event_candidates:
        errors = list(validator.iter_errors(candidate))
        assert errors == [], f"matrix-event candidate invalid: {errors[:1]}"


# --------------------------------------------------------------------------- #
# CLI: fail-closed, writes a schema-valid reconciled_record + sidecar outputs.
# --------------------------------------------------------------------------- #


def test_reconcile_s3_cli_writes_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "reports" / "reconciled" / "vol_01" / "page_0010.json"

    from build.tools.ocr_pipeline.reconcile_s3 import main

    rc = main([
        "--wct", str(FIXTURE_DIR / "wct_vol01_synthetic.json"),
        "--work-meta", str(FIXTURE_DIR / "work_meta.json"),
        "--output", str(out),
        "--occurred-at", OCCURRED_AT,
    ])
    assert rc == 0
    assert out.exists()
    record = json.loads(out.read_text(encoding="utf-8"))
    jsonschema.validate(instance=record, schema=_schema("reconciled_record"))
    # Sidecar candidate + queue artifacts land next to the record.
    assert (out.parent / "page_0010.matrix_candidates.json").exists()
    assert (out.parent / "page_0010.reviewer_queue.json").exists()
