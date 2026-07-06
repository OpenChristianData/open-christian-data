"""Supersession contract for machine-composed corrector decisions (ADR-0014 F8).

Each corrector decision carries a deterministic event ID so published readings
are traceable and supersedeable when the policy version changes.
"""


def make_decision_event_id(
    work_id: str,
    volume_id: str,
    page_id: str,
    position_id: str,
    derivation_policy_version: str,
) -> str:
    """Return a deterministic, unique ID for one corrector decision.

    Format: "{work_id}:{volume_id}:{page_id}:{position_id}:{derivation_policy_version}"
    Deterministic: same inputs always produce the same ID.
    Unique: different (position_id, policy_version) pairs produce different IDs.
    """
    return f"{work_id}:{volume_id}:{page_id}:{position_id}:{derivation_policy_version}"


def mark_superseded(
    old_position: dict,
    new_decision_event_id: str,
) -> dict:
    """Return a copy of old_position with superseded_by set to new_decision_event_id.

    Does not mutate old_position. All other fields are preserved unchanged.
    """
    return {**old_position, "superseded_by": new_decision_event_id}
