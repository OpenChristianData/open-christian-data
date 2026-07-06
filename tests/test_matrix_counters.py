"""B11 — S4 matrix Beta-posterior counters + class-1 gate integration (TEST-16 RED-first).

These tests are the failing-first contract for build/lib/matrix_counters.py. They
encode the arch4 weight-matrix contract (synthesis 2026-05-27 sections 1.3, 4.1,
4.2, 5) and the lock section 3 class-1 strict bar:

- class-1 conjuncts: a trusted (labels_emitted) increment fires only when every
  conjunct holds (family_diversity_count >= 2, independent check, family_map
  readiness, eligible event type, not dictionary-pass-only). Any missing conjunct
  routes the observation to the weak-evidence tally and never touches a trusted
  counter. LLM-resolved / dictionary-pass observations never train.
- Beta posteriors: trusted counters update as correct Beta posteriors from
  observations; weak evidence never silently promotes to trusted counts.
"""

from __future__ import annotations

import pytest

from build.lib.matrix_counters import (
    NEUTRAL_PRIOR,
    CellKey,
    MatrixCounters,
    compute_phase,
    posterior,
    record_observation,
    threshold_class_for,
    thresholds_for,
)
from build.lib.matrix_observation_sink import LedgerIntegrityError, MatrixObservationSink
from build.lib.schema_enums import get_enum

POLICY_VERSION = "weight-matrix-policy-v1"

# All-conjuncts-met state — the only state that produces a trusted increment.
PASSING_CONJUNCTS = dict(
    family_map_readiness=True,
    family_diversity_count=2,
    independent_check_present=True,
    event_type="choose_attestation",
    is_dictionary_pass_only=False,
)


def _label(region_class="body", binary_outcome="correct", volume=1):
    return {
        "engine_version_key": "tesseract|5.5.0|eng|default",
        "scan_lineage_id": "ia-abbyy-v1",
        "volume": volume,
        "region_class": region_class,
        "binary_outcome": binary_outcome,
    }


def _sink(tmp_path):
    return MatrixObservationSink(repo_root=tmp_path, policy_version=POLICY_VERSION)


def _record(sink, event_id, label, **conjunct_overrides):
    conjuncts = dict(PASSING_CONJUNCTS)
    conjuncts.update(conjunct_overrides)
    return record_observation(
        sink,
        event_id=event_id,
        event_type=conjuncts.pop("event_type"),
        occurred_at="2026-05-29T00:00:00Z",
        label=label,
        family_map_readiness=conjuncts["family_map_readiness"],
        family_diversity_count=conjuncts["family_diversity_count"],
        independent_check_present=conjuncts["independent_check_present"],
        is_dictionary_pass_only=conjuncts["is_dictionary_pass_only"],
    )


# --- threshold + phase contract (arch4 4.1 / 4.2) ----------------------------


def test_threshold_classes_cover_every_region_class_enum_value():
    # No-drift guard: every schema region_class maps to exactly one threshold class.
    enum_values = get_enum("matrix-events-v1", "labels", "region_class")
    for region_class in enum_values:
        tc = threshold_class_for(region_class)
        assert tc in {"ordinary", "structured", "protected", "ineligible"}


def test_compute_phase_matches_locked_thresholds():
    # ordinary body: N1=40, N2=250
    assert compute_phase("body", 0) == "bootstrap"
    assert compute_phase("body", 39) == "bootstrap"
    assert compute_phase("body", 40) == "learning"
    assert compute_phase("body", 249) == "learning"
    assert compute_phase("body", 250) == "mature"
    # protected headword: N1=100, N2=600
    assert compute_phase("headword", 99) == "bootstrap"
    assert compute_phase("headword", 100) == "learning"
    assert compute_phase("headword", 600) == "mature"
    # ineligible classes never leave bootstrap
    assert compute_phase("table_cell", 10_000) == "bootstrap"


def test_thresholds_for_protected_is_100_600():
    assert thresholds_for("headword") == (100, 600)
    assert thresholds_for("body") == (40, 250)


# --- Beta posterior formula (arch4 1.3 / 5) ----------------------------------


def test_posterior_uses_locked_beta_formula():
    alpha, beta = NEUTRAL_PRIOR
    # 7 correct, 3 incorrect, neutral Beta(1,1): (7+1)/(10+2) = 8/12
    assert posterior(7, 3, alpha, beta) == pytest.approx(8 / 12)


# --- class-1 conjuncts: trusted vs weak (lock section 3) ---------------------


def test_all_conjuncts_met_increments_trusted_counter(tmp_path):
    sink = _sink(tmp_path)
    _record(sink, "e1", _label(binary_outcome="correct"))
    _record(sink, "e2", _label(binary_outcome="correct"))
    _record(sink, "e3", _label(binary_outcome="incorrect"))

    counters = MatrixCounters.from_ledger(sink.iter_entries())
    cell = counters.trusted_cell(
        CellKey("tesseract|5.5.0|eng|default", "ia-abbyy-v1", 1, "body")
    )
    assert cell is not None
    assert cell.correct == 2
    assert cell.incorrect == 1
    assert cell.n_observed == 3


@pytest.mark.parametrize(
    "override",
    [
        dict(family_map_readiness=False),
        dict(family_diversity_count=1),
        dict(independent_check_present=False),
        dict(is_dictionary_pass_only=True),
        dict(event_type="llm_resolved"),
        dict(event_type="amend_text", is_dictionary_pass_only=True),
    ],
)
def test_any_missing_conjunct_routes_to_weak_never_trusted(tmp_path, override):
    sink = _sink(tmp_path)
    _record(sink, "weak1", _label(binary_outcome="correct"), **override)

    counters = MatrixCounters.from_ledger(sink.iter_entries())
    cell = counters.trusted_cell(
        CellKey("tesseract|5.5.0|eng|default", "ia-abbyy-v1", 1, "body")
    )
    # No trusted cell created; the observation lives only in the weak tally.
    assert cell is None
    assert counters.weak_count() == 1


def test_replay_rejects_forged_labels_emitted_with_ineligible_event_type(tmp_path):
    # Codex review finding 1: defense-in-depth at the replay boundary. A
    # labels_emitted entry written directly (bypassing record_observation) with
    # an ineligible event_type is a corrupt authority claim -- replay must fail
    # closed, never train on it.
    sink = _sink(tmp_path)
    sink.append(
        {
            "event_id": "forged",
            "event_type": "llm_resolved",  # NOT class-1 eligible
            "occurred_at": "2026-05-29T00:00:00Z",
            "outcome": "labels_emitted",
            "labels": [_label(binary_outcome="correct")],
        }
    )
    with pytest.raises(LedgerIntegrityError):
        MatrixCounters.from_ledger(sink.iter_entries())


@pytest.mark.slow
def test_weak_evidence_never_silently_promotes_to_trusted(tmp_path):
    # One trusted correct + a flood of dictionary-pass-only "correct" observations.
    # The posterior must reflect ONLY the single trusted observation.
    sink = _sink(tmp_path)
    _record(sink, "trusted", _label(binary_outcome="correct"))
    for i in range(50):
        _record(
            sink,
            f"weak{i}",
            _label(binary_outcome="correct"),
            is_dictionary_pass_only=True,
        )

    counters = MatrixCounters.from_ledger(sink.iter_entries())
    cell = counters.trusted_cell(
        CellKey("tesseract|5.5.0|eng|default", "ia-abbyy-v1", 1, "body")
    )
    assert cell.correct == 1
    assert cell.incorrect == 0
    assert cell.n_observed == 1
    # Still bootstrap — weak evidence did not push it toward learning/mature.
    assert cell.phase == "bootstrap"
    assert counters.weak_count() == 50
