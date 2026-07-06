"""models.py -- Candidate and ScanResult dataclasses for the OCR error scanner.

Import-safe: no file I/O, no network calls, no CLI parsing at import time (PY-06).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# Reason codes -> tier. Single source of truth for tier assignment.
# Extend here when adding new detectors; scanner + report both consume this dict.
REASON_CODES: dict[str, int] = {
    # Tier 1 (ia_djvu) -- deterministic, >=95% reviewer-confirmed precision target
    "digit_in_letter": 1,
    "ligature_bracket": 1,
    "stray_pipe_backslash": 1,
    # Tier 2 (ia_djvu) -- heuristic + whitelist, >=50% precision target
    "short_allcaps_orphan": 2,
    "apparent_space_insertion": 2,
    "apparent_space_deletion": 2,
    # Tier 3 (ia_djvu) -- exploratory, off by default in configs
    "ligature_ae_loss": 3,
    "hapax_legomenon": 3,
    "case_anomaly": 3,
    # ccel_thml pattern_set
    "entity_leak": 1,
    "unusual_bigram": 2,
    # universal (all pattern_sets) -- field-level detectors
    "pg_header": 1,
}


@dataclass
class Candidate:
    """One flagged OCR-corruption candidate. Serialised to reports/<source>_<date>.json."""

    id: str                          # "cand-0001"
    tier: int                        # 1, 2, or 3 -- must match REASON_CODES[reason]
    reason: str                      # reason code from REASON_CODES
    source_id: str                   # "schaff-herzog"
    entry_id: str                    # "schaff-herzog.theotokos"
    field_path: str                  # "term" | "definition_blocks[2]" | "alt_terms[0]"
    value: str                       # the corrupted token/phrase as it appears in the data
    suggestion: Optional[str]        # proposed correction, or None if detector has no suggestion
    suggestion_source: Optional[str] # "digit_substitution_table" | "dictionary" | "split_point" | None
    confidence: float                # 0.0-1.0; starts at detector default, updated from approval rates
    context_before: str              # ~40 chars of text before the value
    context_after: str               # ~40 chars of text after the value
    occurrences: int                 # count within this entry (not corpus-wide)

    def __post_init__(self) -> None:
        """Validate tier matches REASON_CODES[reason] and confidence is in [0.0, 1.0]."""
        expected_tier = REASON_CODES.get(self.reason)
        if expected_tier is not None and self.tier != expected_tier:
            raise ValueError(
                f"Candidate tier {self.tier} does not match "
                f"REASON_CODES['{self.reason}'] = {expected_tier}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"Candidate confidence {self.confidence} is outside [0.0, 1.0]"
            )

    def to_dict(self) -> dict:
        """Serialise to plain dict for JSON output."""
        return asdict(self)


@dataclass
class ScanResult:
    """Output of scanner.scan_entries(). Emitted by report.write_report()."""

    source_id: str
    scanned_at: str                  # ISO8601. Producer path uses UTC; legacy CLI keeps Australia/Melbourne.
    entries_scanned: int
    pattern_set: str
    pattern_set_version: str
    candidates: list[Candidate] = field(default_factory=list)
    truncated: bool = False
    truncated_reason: Optional[str] = None

    def candidates_by_tier(self) -> dict[str, int]:
        """Return count of candidates at each tier level."""
        counts = {"tier1": 0, "tier2": 0, "tier3": 0}
        for c in self.candidates:
            key = f"tier{c.tier}"
            if key in counts:
                counts[key] += 1
        return counts

    def to_dict(self) -> dict:
        """Serialise to the top-level JSON structure expected by report.write_report()."""
        return {
            "source_id": self.source_id,
            "scanned_at": self.scanned_at,
            "entries_scanned": self.entries_scanned,
            "pattern_set": self.pattern_set,
            "pattern_set_version": self.pattern_set_version,
            "candidates_total": len(self.candidates),
            "candidates_by_tier": self.candidates_by_tier(),
            "truncated": self.truncated,
            "truncated_reason": self.truncated_reason,
            "candidates": [c.to_dict() for c in self.candidates],
        }
