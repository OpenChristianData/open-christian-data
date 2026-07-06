"""Tests for the matrix observation sink and class-1 gate."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.class1_gate import INELIGIBLE_MATRIX_EVENT_TYPES, evaluate_class1  # noqa: E402
from build.lib.matrix_observation_sink import LedgerIntegrityError, MatrixObservationSink  # noqa: E402
from build.lib.weak_evidence_table import WeakEvidenceEntry, WeakEvidenceTable  # noqa: E402


def _label() -> dict:
    return {
        "engine_version_key": "tesseract:5.3.0:eng:default",
        "scan_lineage_id": "scan-lineage-1",
        "volume": 1,
        "region_class": "body",
        "binary_outcome": "correct",
        "diagnostic_metadata": {
            "typography_substyle": "roman",
            "language_overlay": None,
            "engine_self_confidence": 0.97,
            "admission_scope": None,
        },
    }


def _ledger_fields(event_id: str, *, outcome: str = "labels_emitted") -> dict:
    fields = {
        "event_id": event_id,
        "event_type": "choose_attestation",
        "occurred_at": "2026-05-29T00:00:00Z",
        "policy_version": "matrix-policy-test",
        "outcome": outcome,
    }
    if outcome == "labels_emitted":
        fields["labels"] = [_label()]
    return fields


def test_ledger_rejects_out_of_order_append(tmp_path: Path) -> None:
    """
    The hash chain detects any entry whose prev_entry_hash does not match
    the actual head hash of the ledger. Writing an entry with a wrong
    prev_entry_hash raises LedgerIntegrityError.
    """
    sink = MatrixObservationSink(tmp_path, policy_version="matrix-policy-test")
    first = sink.append(_ledger_fields("de-sha256:" + "1" * 64))
    sink.append(_ledger_fields("de-sha256:" + "2" * 64))

    stale_prev_hash = MatrixObservationSink.entry_hash(first)
    tampered_fields = _ledger_fields("de-sha256:" + "3" * 64)
    tampered_fields["prev_entry_hash"] = stale_prev_hash

    with pytest.raises(LedgerIntegrityError):
        sink.append(tampered_fields)


def test_trusted_obs_goes_to_ledger_weak_goes_to_weak_table(tmp_path: Path) -> None:
    """
    A gold-anchored observation writes a labels_emitted ledger entry.
    An LLM-resolved observation routes only to the weak-evidence table and never
    appears in trusted labels_emitted ledger entries.
    """
    sink = MatrixObservationSink(tmp_path, policy_version="matrix-policy-test")
    weak_table = WeakEvidenceTable(tmp_path)

    trusted_event_id = "de-sha256:" + "a" * 64
    weak_event_id = "de-sha256:" + "b" * 64
    sink.append(_ledger_fields(trusted_event_id))
    weak_table.append(
        WeakEvidenceEntry(
            event_id=weak_event_id,
            occurred_at="2026-05-29T00:00:00Z",
            policy_version="matrix-policy-test",
            weak_reason="llm_resolved_event",
            event_type="confirm_unresolved",
            canonical_token_id="ct-sha256:" + "c" * 64,
            volume=1,
            labels=[_label()],
        )
    )

    trusted_entries = [
        entry
        for entry in sink.iter_entries()
        if entry["outcome"] == "labels_emitted"
    ]
    weak_entries = list(weak_table.iter_entries())

    assert any(entry["event_id"] == trusted_event_id for entry in trusted_entries)
    assert weak_entries[0].event_id == weak_event_id
    assert weak_entries[0].weak_reason == "llm_resolved_event"
    assert not any(entry["event_id"] == weak_event_id for entry in trusted_entries)


def test_class1_blocked_without_family_map_readiness() -> None:
    """
    A class-1 emission is rejected unless family-map readiness, measured family
    diversity, and an independent check are all present.
    """
    result = evaluate_class1(
        family_map_readiness=False,
        family_diversity_count=2,
        independent_check_present=True,
        event_type="choose_attestation",
        is_dictionary_pass_only=False,
    )
    assert result.allowed is False
    assert result.weak_reason == "no_family_map_readiness"

    result = evaluate_class1(
        family_map_readiness=True,
        family_diversity_count=1,
        independent_check_present=True,
        event_type="choose_attestation",
        is_dictionary_pass_only=False,
    )
    assert result.allowed is False
    assert result.weak_reason == "insufficient_family_diversity"

    result = evaluate_class1(
        family_map_readiness=True,
        family_diversity_count=2,
        independent_check_present=False,
        event_type="choose_attestation",
        is_dictionary_pass_only=False,
    )
    assert result.allowed is False
    assert result.weak_reason == "no_independent_check"

    result = evaluate_class1(
        family_map_readiness=True,
        family_diversity_count=2,
        independent_check_present=True,
        event_type="choose_attestation",
        is_dictionary_pass_only=False,
    )
    assert result.allowed is True
    assert result.weak_reason is None

    assert "confirm_unresolved" in INELIGIBLE_MATRIX_EVENT_TYPES
    result = evaluate_class1(
        family_map_readiness=True,
        family_diversity_count=2,
        independent_check_present=True,
        event_type="confirm_unresolved",
        is_dictionary_pass_only=False,
    )
    assert result.allowed is False
    assert result.weak_reason == "llm_resolved_event"

    result = evaluate_class1(
        family_map_readiness=True,
        family_diversity_count=2,
        independent_check_present=True,
        event_type="choose_attestation",
        is_dictionary_pass_only=True,
    )
    assert result.allowed is False
    assert result.weak_reason == "dictionary_pass_only"


def test_empty_labels_rejected_by_schema(tmp_path: Path) -> None:
    """An empty labels array must not pass for outcome=labels_emitted (minItems: 1)."""
    sink = MatrixObservationSink(tmp_path, policy_version="matrix-policy-test")
    fields = _ledger_fields("de-sha256:" + "d" * 64)
    fields["labels"] = []
    with pytest.raises(LedgerIntegrityError):
        sink.append(fields)


def test_unknown_event_type_blocked_by_class1_gate() -> None:
    """An event type not in the eligible set must be fail-closed, not fail-open."""
    result = evaluate_class1(
        family_map_readiness=True,
        family_diversity_count=2,
        independent_check_present=True,
        event_type="unknown_future_event_type",
        is_dictionary_pass_only=False,
    )
    assert result.allowed is False
    assert result.weak_reason == "llm_resolved_event"
