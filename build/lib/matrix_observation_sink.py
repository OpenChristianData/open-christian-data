"""Append-only matrix observation ledger."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Iterator

from build.lib.atomic_io import SchemaValidationError, append_jsonl_atomic, validate_payload

ZERO_HASH = "0" * 64
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "v1" / "matrix-events-v1.schema.json"


class LedgerIntegrityError(Exception):
    """Raised when a prev_entry_hash mismatch or schema violation is detected."""


class MatrixObservationSink:
    """
    Append-only, hash-chained JSONL ledger for matrix observation events.

    The ledger is written under cache/weight_matrix/replay_ledger/ and its
    current head hash is mirrored to matrix-events.jsonl.head_hash after each
    append.

    Single-writer constraint (v1): the hash-chain fields (entry_seq,
    prev_entry_hash) are computed from the ledger state at call time, outside
    the file lock. Concurrent callers will produce a broken chain detectable
    by verify_chain(). Callers must serialize appends in their own layer.
    """

    def __init__(self, repo_root: Path, policy_version: str):
        self.repo_root = Path(repo_root)
        self.policy_version = policy_version
        self.ledger_dir = self.repo_root / "cache" / "weight_matrix" / "replay_ledger"
        self.ledger_path = self.ledger_dir / "matrix-events.jsonl"
        self.head_hash_path = self.ledger_path.with_name(self.ledger_path.name + ".head_hash")
        self._schema = self._load_schema()
        self.ledger_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def entry_hash(entry: dict) -> str:
        payload = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return sha256(payload).hexdigest()

    def append(self, entry_fields: dict) -> dict:
        """
        Build, validate, and append one ledger entry.

        Caller-provided schema_version, entry_seq, and prev_entry_hash are
        ignored except that a provided prev_entry_hash must match the current
        head hash.
        """
        entries = list(self.iter_entries())
        current_head = self._head_hash_from_entries(entries)
        provided_prev_hash = entry_fields.get("prev_entry_hash")
        if provided_prev_hash is not None and provided_prev_hash != current_head:
            raise LedgerIntegrityError(
                f"prev_entry_hash {provided_prev_hash!r} does not match current head {current_head!r}"
            )

        clean_fields = dict(entry_fields)
        clean_fields.pop("schema_version", None)
        clean_fields.pop("entry_seq", None)
        clean_fields.pop("prev_entry_hash", None)
        clean_fields["policy_version"] = self.policy_version

        entry = {
            "schema_version": "matrix-events-v1",
            "entry_seq": len(entries),
            "prev_entry_hash": current_head,
            **clean_fields,
        }
        self._validate_entry(entry)
        try:
            append_jsonl_atomic(self.ledger_path, entry, self._schema)
        except SchemaValidationError as exc:
            raise LedgerIntegrityError(str(exc)) from exc
        self._write_head_hash_atomic(self.entry_hash(entry))
        return entry

    def verify_chain(self) -> None:
        """Verify that every ledger entry links to the previous entry hash."""
        previous_hash = ZERO_HASH
        for expected_seq, entry in enumerate(self.iter_entries()):
            self._validate_entry(entry)
            if entry["entry_seq"] != expected_seq:
                raise LedgerIntegrityError(
                    f"entry_seq {entry['entry_seq']} does not match expected {expected_seq}"
                )
            if entry["prev_entry_hash"] != previous_hash:
                raise LedgerIntegrityError(
                    f"entry {expected_seq} prev_entry_hash does not match previous entry hash"
                )
            previous_hash = self.entry_hash(entry)

    def head_hash(self) -> str:
        """Return the hash of the last entry, or the all-zero genesis sentinel."""
        entries = list(self.iter_entries())
        current_head = self._head_hash_from_entries(entries)
        if current_head != ZERO_HASH:
            self._write_head_hash_atomic(current_head)
        return current_head

    def iter_entries(self) -> Iterator[dict]:
        """Yield each ledger entry in order."""
        if not self.ledger_path.exists():
            return
        with self.ledger_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    yield json.loads(text)
                except json.JSONDecodeError as exc:
                    raise LedgerIntegrityError(
                        f"invalid JSON in {self.ledger_path} at line {line_number}"
                    ) from exc

    def _load_schema(self) -> dict:
        with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _validate_entry(self, entry: dict) -> None:
        try:
            validate_payload(entry, self._schema)
        except SchemaValidationError as exc:
            raise LedgerIntegrityError(str(exc)) from exc

    def _head_hash_from_entries(self, entries: list[dict]) -> str:
        if not entries:
            return ZERO_HASH
        return self.entry_hash(entries[-1])

    def _write_head_hash_atomic(self, head_hash: str) -> None:
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.head_hash_path.with_name(
            self.head_hash_path.name + f".tmp-{head_hash[:12]}"
        )
        tmp_path.write_text(head_hash + "\n", encoding="utf-8")
        tmp_path.replace(self.head_hash_path)
