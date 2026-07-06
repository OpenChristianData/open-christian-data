"""Append-only, hash-chained decision-event store for the reviewer subsystem.

Default store location: <base_dir>/decisions/schaff-herzog/vol_{NN:02d}/events.jsonl
Each line is one decision-event-v1 record with three envelope fields added by
this writer: event_id (JCS-derived), prev_event_hash, event_hash.

Fold order is hash-chain append order, NEVER occurred_at/timestamp.
A corrupt line is publish-blocking (arch7 s1.5).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema

from build.lib.event_completeness import assert_event_complete
from build.lib.schema_enums import get_enum


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "v1" / "decision-event-v1.schema.json"
GENESIS_HASH = "sha256:" + "0" * 64

# Eight failure classes from arch7 s1.5
_FAILURE_CLASSES = frozenset([
    "json_parse_error",
    "schema_validation_error",
    "event_hash_mismatch",
    "prev_hash_mismatch",
    "duplicate_event_id",
    "unknown_event_type",
    "unknown_event_category",
    "missing_decision_key",
])


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _canonical_bytes(obj: Any) -> bytes:
    """Produce deterministic UTF-8 JSON bytes for hashing (sort_keys, no extra whitespace)."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, sort_keys=True).encode("utf-8")


def _sha256hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _derive_event_id(event: dict) -> str:
    """Compute event_id as de-sha256 of JCS-canonical event content.

    Excludes event_hash, prev_event_hash, and event_id itself from the hash
    so that the id is stable regardless of chain position.
    """
    excluded = {"event_hash", "prev_event_hash", "event_id"}
    payload = {k: v for k, v in event.items() if k not in excluded}
    return "de-sha256:" + _sha256hex(_canonical_bytes(payload))


def _derive_event_hash(event_with_id_and_prev: dict) -> str:
    """Compute event_hash from the event dict that has event_id + prev_event_hash set,
    but does NOT yet have event_hash set."""
    excluded = {"event_hash"}
    payload = {k: v for k, v in event_with_id_and_prev.items() if k not in excluded}
    return "sha256:" + _sha256hex(_canonical_bytes(payload))


class StoreCorruptError(Exception):
    """Raised when fold() encounters a corrupt line. Publish-blocking (arch7 s1.5)."""

    def __init__(self, failure_class: str, line_number: int, detail: str) -> None:
        if failure_class not in _FAILURE_CLASSES:
            raise ValueError(f"unknown failure_class: {failure_class!r}")
        self.failure_class = failure_class
        self.line_number = line_number
        self.detail = detail
        super().__init__(f"{failure_class} at line {line_number}: {detail}")


class DecisionStore:
    """Append-only hash-chained decisions store for one volume.

    Usage:
        store = DecisionStore(base_dir=Path("/repo"), volume=1)
        store.append(event_dict)
        events = store.fold()
    """

    def __init__(
        self,
        *,
        base_dir: Path | str,
        volume: int,
        corpus_slug: str = "schaff-herzog",
        volume_id: str | None = None,
    ) -> None:
        # base_dir must resolve outside any cloud-sync root (arch7 s1.7 / ENV-WIN-05).
        # The store writer has no guard — the caller is responsible for choosing a
        # non-sync destination (e.g. repo root or a local path outside Sync.com scope).
        self._base_dir = Path(base_dir)
        self._volume = volume
        self._corpus_slug = corpus_slug
        self._volume_id = volume_id
        self._schema: dict | None = None

    @property
    def store_path(self) -> Path:
        """Path to this volume's events.jsonl file."""
        return (
            self._base_dir
            / "decisions"
            / self._corpus_slug
            / (self._volume_id or f"vol_{self._volume:02d}")
            / "events.jsonl"
        )

    def _get_schema(self) -> dict:
        if self._schema is None:
            self._schema = _load_schema()
        return self._schema

    def _read_last_event_hash(self) -> str:
        """Return the event_hash of the most recently appended event, or GENESIS_HASH."""
        path = self.store_path
        if not path.exists() or path.stat().st_size == 0:
            return GENESIS_HASH
        # Read the last non-empty line efficiently
        text = path.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            return GENESIS_HASH
        last = json.loads(lines[-1])
        return last.get("event_hash", GENESIS_HASH)

    def append(self, event: dict, *, preserve_event_id: bool = False) -> None:
        """Validate and append a decision-event-v1 record to the store.

        Mutates the event dict in-place to set event_id, prev_event_hash, event_hash.
        Raises jsonschema.ValidationError if the event violates the schema before writing.
        """
        self.append_many([event], preserve_event_id=preserve_event_id)

    def append_many(
        self,
        events: list[dict],
        *,
        preserve_event_id: bool = False,
        enforce_ratification_context: bool = False,
    ) -> None:
        """Validate and append decision-event-v1 records to the store."""
        if not events:
            return
        if enforce_ratification_context:
            for event in events:
                assert_event_complete(event)
        schema = self._get_schema()
        validator = jsonschema.Draft202012Validator(schema)
        prev_event_hash = self._read_last_event_hash()
        lines: list[str] = []

        for event in events:
            # 1. Derive and set event_id from content unless importing a pre-minted
            # event from an existing decision artifact.
            if preserve_event_id:
                if not event.get("event_id"):
                    raise ValueError("preserve_event_id=True requires event['event_id']")
            else:
                event["event_id"] = _derive_event_id(event)

            # 2. Set prev_event_hash from store tail or the prior event in this batch
            event["prev_event_hash"] = prev_event_hash

            # 3. Compute and set event_hash (event_id + prev_event_hash present, event_hash absent)
            event["event_hash"] = _derive_event_hash(event)

            # 4. Validate against schema before writing
            validator.validate(event)
            prev_event_hash = event["event_hash"]
            lines.append(json.dumps(event, separators=(",", ":"), ensure_ascii=False, sort_keys=True))

        # 5. Atomic append: read existing + append + write to tmp + replace
        path = self.store_path
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        separator = "" if not existing or existing.endswith("\n") else "\n"
        new_content = existing + separator + "\n".join(lines) + "\n"
        tmp_path = path.with_suffix(".jsonl.tmp")
        tmp_path.write_text(new_content, encoding="utf-8")
        tmp_path.replace(path)

    def fold(self) -> list[dict]:
        """Read all events in hash-chain append order.

        Raises StoreCorruptError on the first corrupt line (publish-blocking).
        Returns an empty list if the store file does not exist.
        """
        path = self.store_path
        if not path.exists():
            return []

        valid_event_types = get_enum("decision-event-v1", "event_type")
        valid_event_categories = get_enum("decision-event-v1", "event_category")

        events: list[dict] = []
        seen_ids: set[str] = set()
        prev_hash = GENESIS_HASH
        text = path.read_text(encoding="utf-8")

        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            # Failure class: json_parse_error
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise StoreCorruptError("json_parse_error", line_number, str(exc)) from exc

            # Failure class: unknown_event_type (check before schema validation for clear message)
            event_type = record.get("event_type", "")
            if event_type not in valid_event_types:
                raise StoreCorruptError(
                    "unknown_event_type", line_number,
                    f"event_type {event_type!r} not in locked enum",
                )

            # Failure class: unknown_event_category
            event_category = record.get("event_category", "")
            if event_category not in valid_event_categories:
                raise StoreCorruptError(
                    "unknown_event_category", line_number,
                    f"event_category {event_category!r} not in locked enum",
                )

            # Failure class: event_hash_mismatch
            stored_event_hash = record.get("event_hash", "")
            recomputed_event_hash = _derive_event_hash(record)
            if stored_event_hash != recomputed_event_hash:
                raise StoreCorruptError(
                    "event_hash_mismatch", line_number,
                    f"stored {stored_event_hash!r} != recomputed {recomputed_event_hash!r}",
                )

            # Failure class: prev_hash_mismatch
            stored_prev = record.get("prev_event_hash", "")
            if stored_prev != prev_hash:
                raise StoreCorruptError(
                    "prev_hash_mismatch", line_number,
                    f"stored prev_event_hash {stored_prev!r} != expected {prev_hash!r}",
                )

            # Failure class: duplicate_event_id
            event_id = record.get("event_id", "")
            if event_id in seen_ids:
                raise StoreCorruptError(
                    "duplicate_event_id", line_number,
                    f"event_id {event_id!r} already seen",
                )
            seen_ids.add(event_id)

            prev_hash = stored_event_hash
            events.append(record)

        return events

    @property
    def publication_mode(self) -> str:
        """Return 'complete' if the store folds cleanly, 'blocked_store_corrupt' otherwise."""
        try:
            self.fold()
            return "complete"
        except StoreCorruptError:
            return "blocked_store_corrupt"
