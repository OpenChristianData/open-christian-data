"""match_explanations — ledger for match explanation entries.

Each method returns the generated match_explanation_id. Schema shapes must
match reconciled_record.schema.json (additionalProperties: false enforced).
"""

from __future__ import annotations

import hashlib


def _mx_id(entry_data: dict) -> str:
    """Produce a deterministic match_explanation_id from entry data."""
    raw = str(entry_data)
    return "mx_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


_BUCKET_SCORE_RANGE = {
    "high": "78-100",
    "mid_high": "60-77",
    "mid_low": "45-59",
    "low": "0-44",
}


class MatchExplanationLedger:
    """Accumulates match explanation records for assembly into the final reconciled record."""

    def __init__(self) -> None:
        self._entries: list[dict] = []

    def add_edge_match(
        self,
        block_id_pair: list[str],
        signals: list[dict],
        total_score: int | float,
        bucket: str,
        action: str,
        surface: str,
    ) -> str:
        """Record a block-pair edge match decision. Returns match_explanation_id."""
        score_range = _BUCKET_SCORE_RANGE.get(bucket, "0-44")
        entry: dict = {
            "scope": "block_pair_edge",
            "block_id_pair": list(block_id_pair),
            "signals": signals,
            "total_score": total_score,
            "decision": {
                "kind": "edge_match",
                "bucket": bucket,
                "score_range": score_range,
                "action": action,
                "surface": surface,
            },
        }
        mx_id = _mx_id(entry)
        entry["match_explanation_id"] = mx_id
        self._entries.append(entry)
        return mx_id

    def add_reading_score(
        self,
        block_id: str,
        signals: list[dict],
        pd_only_gap: float,
        winning_has_pd_support: bool,
        classification: str,
        advisory_score: float,
    ) -> str:
        """Record a reading-score decision for a disagreement. Returns match_explanation_id."""
        entry: dict = {
            "scope": "disagreement",
            "block_id": block_id,
            "signals": signals,
            "total_score": sum(s.get("contribution", 0) for s in signals),
            "decision": {
                "kind": "reading_score",
                "pd_only_gap": pd_only_gap,
                "winning_has_pd_support": winning_has_pd_support,
                "classification": classification,
                "advisory_score": advisory_score,
            },
        }
        mx_id = _mx_id(entry)
        entry["match_explanation_id"] = mx_id
        self._entries.append(entry)
        return mx_id

    def add_structural_rule(
        self,
        block_id: str,
        rule_applied: str,
        outcome: str,
    ) -> str:
        """Record a structural rule application. Returns match_explanation_id."""
        entry: dict = {
            "scope": "structural_disagreement",
            "block_id": block_id,
            "signals": [],
            "total_score": 0,
            "decision": {
                "kind": "structural_rule",
                "rule_applied": rule_applied,
                "outcome": outcome,
            },
        }
        mx_id = _mx_id(entry)
        entry["match_explanation_id"] = mx_id
        self._entries.append(entry)
        return mx_id

    def all_entries(self) -> list[dict]:
        """Return all recorded entries."""
        return list(self._entries)
