"""Append-only weak-evidence table for matrix observations."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from build.lib.atomic_io import append_jsonl_atomic

WEAK_REASON_VALUES = [
    "no_family_map_readiness",
    "insufficient_family_diversity",
    "no_independent_check",
    "dictionary_pass_only",
    "llm_agreement_only",
    "llm_resolved_event",
]

WEAK_EVIDENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "event_id",
        "occurred_at",
        "policy_version",
        "weak_reason",
        "event_type",
        "canonical_token_id",
        "volume",
        "labels",
    ],
    "properties": {
        "event_id": {"type": "string", "minLength": 1},
        "occurred_at": {"type": "string", "format": "date-time"},
        "policy_version": {"type": "string", "minLength": 1},
        "weak_reason": {"enum": WEAK_REASON_VALUES},
        "event_type": {"type": "string", "minLength": 1},
        "canonical_token_id": {
            "oneOf": [
                {"type": "string", "minLength": 1},
                {"type": "null"},
            ]
        },
        "volume": {
            "oneOf": [
                {"type": "integer", "minimum": 1},
                {"type": "null"},
            ]
        },
        "labels": {"type": "array", "items": {"type": "object"}},
    },
}


@dataclass(frozen=True)
class WeakEvidenceEntry:
    event_id: str
    occurred_at: str
    policy_version: str
    weak_reason: str
    event_type: str
    canonical_token_id: str | None
    volume: int | None
    labels: list[dict]


class WeakEvidenceTable:
    """
    Append-only JSONL store for observations that are not trusted matrix inputs.

    Entries are written under cache/weight_matrix/weak_evidence_table.jsonl.
    """

    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root)
        self.table_dir = self.repo_root / "cache" / "weight_matrix"
        self.table_path = self.table_dir / "weak_evidence_table.jsonl"
        self.table_dir.mkdir(parents=True, exist_ok=True)

    def append(self, entry: WeakEvidenceEntry) -> None:
        """Append one weak-evidence entry atomically."""
        append_jsonl_atomic(self.table_path, asdict(entry), WEAK_EVIDENCE_SCHEMA)

    def iter_entries(self) -> Iterator[WeakEvidenceEntry]:
        """Yield weak-evidence entries in append order."""
        if not self.table_path.exists():
            return
        with self.table_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                yield WeakEvidenceEntry(**json.loads(text))
