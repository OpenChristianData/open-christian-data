"""Class-1 matrix training gate."""

from __future__ import annotations

from dataclasses import dataclass

from build.lib.schema_enums import get_enum

ELIGIBLE_MATRIX_EVENT_TYPES = frozenset(
    {"choose_attestation", "amend_text", "mark_gold"}
)
# Derived for reference only — do NOT use as the gate check (unknown future event types
# would not appear here and would slip through). Use the ELIGIBLE allowlist instead.
INELIGIBLE_MATRIX_EVENT_TYPES = get_enum("decision-event-v1", "event_type") - ELIGIBLE_MATRIX_EVENT_TYPES


@dataclass(frozen=True)
class Class1GateResult:
    allowed: bool
    weak_reason: str | None


def evaluate_class1(
    *,
    family_map_readiness: bool,
    family_diversity_count: int,
    independent_check_present: bool,
    event_type: str,
    is_dictionary_pass_only: bool,
) -> Class1GateResult:
    """
    Apply the three-conjunct class-1 gate.

    Fail-closed on event_type: only the three explicitly eligible event types
    (choose_attestation, amend_text, mark_gold) can ever return allowed=True.
    Unknown or future event types are blocked, not silently permitted.
    LLM-resolved and dictionary-pass-only observations never pass.
    """
    if event_type not in ELIGIBLE_MATRIX_EVENT_TYPES:
        return Class1GateResult(allowed=False, weak_reason="llm_resolved_event")
    if is_dictionary_pass_only:
        return Class1GateResult(allowed=False, weak_reason="dictionary_pass_only")
    if not family_map_readiness:
        return Class1GateResult(allowed=False, weak_reason="no_family_map_readiness")
    if family_diversity_count < 2:
        return Class1GateResult(allowed=False, weak_reason="insufficient_family_diversity")
    if not independent_check_present:
        return Class1GateResult(allowed=False, weak_reason="no_independent_check")
    return Class1GateResult(allowed=True, weak_reason=None)
