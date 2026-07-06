from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.event_vocab import (  # noqa: E402
    UnknownEventTypeError,
    assert_known_event_type,
    partition_events,
)


def test_unknown_event_type_raises() -> None:
    with pytest.raises(UnknownEventTypeError):
        assert_known_event_type("bogus_event", frozenset({"choose_attestation"}))


def test_known_event_type_is_allowed() -> None:
    assert_known_event_type("choose_attestation", frozenset({"choose_attestation"}))


def test_empty_allowed_set_rejects_any_value() -> None:
    with pytest.raises(UnknownEventTypeError):
        assert_known_event_type("choose_attestation", frozenset())


def test_partition_events_splits_known_unknown_and_missing_type() -> None:
    known_event = {"event_type": "choose_attestation", "id": "known"}
    unknown_event = {"event_type": "bogus_event", "id": "unknown"}
    missing_type_event = {"id": "missing"}

    known, unknown = partition_events(
        [known_event, unknown_event, missing_type_event],
        frozenset({"choose_attestation"}),
    )

    assert known == [known_event]
    assert unknown == [unknown_event, missing_type_event]
