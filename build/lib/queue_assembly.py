"""Queue item assembly for the reviewer minimum-viable UI (arch7 s2.2).

Assembles a reviewer queue item from a WCT/reconciled token dict.
The store is the only irreplaceable artifact; this assembly layer is a thin,
replaceable shell over it (arch7 s20).

scan_crop is always None in MVP — scan_crop.py is arch8's dependency
and does not exist yet (arch7 s2.3 blocking dependency).
"""

from __future__ import annotations


def _disagreement_score(candidate_attestations: list[dict]) -> float:
    """Measure how divided engine families are across candidate readings."""
    if not candidate_attestations:
        return 0.0

    all_families: set[str] = set()
    max_attesting_family_count = 0

    for candidate in candidate_attestations:
        families = set(candidate.get("attesting_families", []))
        all_families.update(families)
        max_attesting_family_count = max(max_attesting_family_count, len(families))

    total_distinct_families = max(len(all_families), 1)
    return round(1.0 - (max_attesting_family_count / total_distinct_families), 4)


def assemble_queue_item(token: dict) -> dict:
    """Assemble a reviewer queue item from a WCT/reconciled token dict.

    Returns a dict with 8 fields:
      canonical_token_id, batch_id, candidate_attestations,
      matrix_phase, decision_action, deferral_reason, disagreement_score, scan_crop.

    scan_crop is None until scan_crop.py (arch8 dependency) is implemented.
    """
    candidate_attestations = token.get("candidate_attestations", [])
    return {
        "canonical_token_id": token["canonical_token_id"],
        "batch_id": token.get("batch_id"),
        "candidate_attestations": candidate_attestations,
        "matrix_phase": token.get("matrix_phase"),
        "decision_action": token.get("decision_action"),
        "deferral_reason": token.get("deferral_reason"),
        "disagreement_score": _disagreement_score(candidate_attestations),
        "scan_crop": None,
    }
