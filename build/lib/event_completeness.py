"""Completeness gate for ratification-class decision events."""

from __future__ import annotations

from typing import Any


RATIFICATION_EVENT_TYPES = frozenset({"machine_release", "choose_attestation", "amend_text"})


class EventIncompleteError(ValueError):
    """Raised when a ratification-class event lacks replay-critical context."""


def _has_non_empty_value(evidence_seen: dict[str, Any], *keys: str) -> bool:
    return any(bool(evidence_seen.get(key)) for key in keys)


def check_event_completeness(event: dict) -> list[str]:
    """Return missing replay-context fields for ratification-class events."""
    if event.get("event_type") not in RATIFICATION_EVENT_TYPES:
        return []

    evidence_seen = event.get("evidence_seen")
    if not isinstance(evidence_seen, dict):
        return [
            "evidence_seen must be an object",
            "missing snapshot id (scorecard_snapshot_id or thresholds_file_id)",
            "missing wct_page_sha256",
            "missing seen candidate (chosen_candidate_text or seen_candidate)",
        ]

    missing: list[str] = []
    if not _has_non_empty_value(evidence_seen, "scorecard_snapshot_id", "thresholds_file_id"):
        missing.append("missing snapshot id (scorecard_snapshot_id or thresholds_file_id)")
    if not evidence_seen.get("wct_page_sha256"):
        missing.append("missing wct_page_sha256")
    if "chosen_candidate_text" not in evidence_seen and "seen_candidate" not in evidence_seen:
        missing.append("missing seen candidate (chosen_candidate_text or seen_candidate)")
    return missing


def assert_event_complete(event: dict) -> None:
    """Raise EventIncompleteError if a ratification-class event is incomplete."""
    missing = check_event_completeness(event)
    if not missing:
        return
    event_id = event.get("event_id") or "<missing>"
    raise EventIncompleteError(f"event_id {event_id}: " + "; ".join(missing))
