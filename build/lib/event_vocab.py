"""Fail-closed event vocabulary guard for downstream decision-event consumers.

Production callers obtain the allowed set from
get_enum("decision-event-v1", "event_type") in ocd_kernel.lib.schema_enums once that
schema is built in a later batch; this module never imports it.
"""

from __future__ import annotations


class UnknownEventTypeError(ValueError):
    """Raised when a decision-event carries an event_type outside the allowed set."""


def assert_known_event_type(event_type: str, allowed_event_types: frozenset[str]) -> None:
    if event_type not in allowed_event_types:
        raise UnknownEventTypeError(f"unknown event_type: {event_type}")


def partition_events(
    events: list[dict],
    allowed_event_types: frozenset[str],
) -> tuple[list[dict], list[dict]]:
    known: list[dict] = []
    unknown: list[dict] = []
    for event in events:
        if event.get("event_type") in allowed_event_types:
            known.append(event)
        else:
            unknown.append(event)
    return known, unknown
