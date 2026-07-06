"""S4 matrix Beta-posterior counters + class-1 gate wiring (B11).

Built on top of the B14 append-only ledger (``matrix_observation_sink.py``).
Logging is decoupled from training: the sink records every observation; these
counters trust *only* class-1-eligible (``labels_emitted``) entries. Everything
else stays in a weak-evidence tally and never touches a trusted counter
(lock section 3 "build-and-measure").

Contract source: ``plans/2026-05-27-arch4-weight-matrix-synthesis.md``
sections 1.1 (cell key), 1.3 (counter shape), 4.1 (thresholds), 4.2
(``compute_phase``), 5 (one posterior formula). The class-1 gate itself lives in
``class1_gate.py`` (the B14 stub B11 wires in); this module decides, from the
gate verdict, whether an observation becomes a trusted label or a weak entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from build.lib.atomic_io import SchemaValidationError
from build.lib.class1_gate import (
    ELIGIBLE_MATRIX_EVENT_TYPES,
    Class1GateResult,
    evaluate_class1,
)
from build.lib.matrix_observation_sink import LedgerIntegrityError, MatrixObservationSink

# Neutral Beta(1, 1) prior (arch4 section 3.2 P0). Stored on every trusted cell;
# fixed floats so canonical serialisation stays byte-stable across rebuilds.
NEUTRAL_PRIOR: tuple[float, float] = (1.0, 1.0)

# Phase thresholds per risk class (arch4 section 4.1). (N1 bootstrap->learning,
# N2 learning->mature). ``ineligible`` classes never gain vote authority.
# List-form frozensets: these are logic constants (which region_class sits in
# which risk band), NOT a schema-enum mirror -- see PIPE-26.
_ORDINARY_CLASSES = frozenset(["body", "caption", "cross_reference"])
_STRUCTURED_CLASSES = frozenset(
    [
        "bibliography_entry",
        "bibliography_section_marker",
        "section_heading",
        "heading_subsection",
        "footnote",
    ]
)
_PROTECTED_CLASSES = frozenset(
    [
        "headword",
        "foreign_language_greek",
        "foreign_language_hebrew",
        "foreign_language_latin",
        "foreign_language_german",
    ]
)
_INELIGIBLE_CLASSES = frozenset(["unknown", "list_item", "table_cell", "quotation"])

_THRESHOLDS: dict[str, tuple[int, int]] = {
    "ordinary": (40, 250),
    "structured": (60, 400),
    "protected": (100, 600),
}

# Ledger outcome that carries trusted labels (the only one that trains).
_TRUSTED_OUTCOME = "labels_emitted"

# weak_reason (from the class-1 gate) -> ledger outcome enum value
# (matrix-events-v1 ``outcome``). The event-type rejections project as
# ``ineligible_event_type``; the measurement-eligibility rejections project as
# ``not_measurement_eligible``.
_WEAK_REASON_TO_OUTCOME = {
    "llm_resolved_event": "ineligible_event_type",
    "dictionary_pass_only": "not_measurement_eligible",
    "no_family_map_readiness": "not_measurement_eligible",
    "insufficient_family_diversity": "not_measurement_eligible",
    "no_independent_check": "not_measurement_eligible",
}


def threshold_class_for(region_class: str) -> str:
    """Return the risk class (ordinary/structured/protected/ineligible) for a region_class."""
    if region_class in _ORDINARY_CLASSES:
        return "ordinary"
    if region_class in _STRUCTURED_CLASSES:
        return "structured"
    if region_class in _PROTECTED_CLASSES:
        return "protected"
    if region_class in _INELIGIBLE_CLASSES:
        return "ineligible"
    # Fail closed: an unmapped region_class is treated as ineligible (no vote
    # authority) rather than silently defaulting to a trainable band.
    return "ineligible"


def thresholds_for(region_class: str) -> tuple[int | None, int | None]:
    """Return (N1, N2) for a region_class; (None, None) for ineligible classes."""
    tc = threshold_class_for(region_class)
    if tc == "ineligible":
        return (None, None)
    return _THRESHOLDS[tc]


def compute_phase(region_class: str, active_observations: int) -> str:
    """Phase as a pure function of active observations and region_class (arch4 4.2).

    Ineligible classes never leave bootstrap. A retraction that drops the active
    count below N1 regresses the phase to bootstrap, by construction.
    """
    n1, n2 = thresholds_for(region_class)
    if n1 is None or n2 is None:
        return "bootstrap"
    if active_observations < n1:
        return "bootstrap"
    if active_observations < n2:
        return "learning"
    return "mature"


def posterior(correct: int, incorrect: int, alpha: float, beta: float) -> float:
    """The one locked Beta posterior mean (arch4 section 5).

    posterior = (correct + alpha) / (n_observed + alpha + beta)
    """
    n_observed = correct + incorrect
    return (correct + alpha) / (n_observed + alpha + beta)


@dataclass(frozen=True)
class CellKey:
    """Word-cell key materialised from a ledger label.

    The arch4 5-tuple is (engine_family, engine_version, scan_lineage_id, volume,
    region_class); engine_version_key is the canonical composite that subsumes
    engine_family (arch4 section 1.2), so it is the keying field here. The fifth
    axis, comparison_profile_id, is fixed at ``source-faithful-token-v1`` in v1.
    """

    engine_version_key: str
    scan_lineage_id: str
    volume: int
    region_class: str

    def as_tuple(self) -> tuple[str, str, int, str]:
        return (self.engine_version_key, self.scan_lineage_id, self.volume, self.region_class)


@dataclass
class WeightCell:
    """A Beta-Binomial counter for one cell (arch4 section 1.3).

    ``correct``/``incorrect`` are integer counts mutated only by replay;
    ``alpha``/``beta`` are the fixed prior. Derived quantities (n_observed,
    posterior, phase, threshold_class) are computed, never persisted into the
    snapshot payload, so byte-identical replay does not depend on float repr of a
    derived value.
    """

    cell_key: CellKey
    correct: int = 0
    incorrect: int = 0
    retracted: int = 0
    alpha: float = NEUTRAL_PRIOR[0]
    beta: float = NEUTRAL_PRIOR[1]

    @property
    def n_observed(self) -> int:
        return self.correct + self.incorrect

    @property
    def posterior(self) -> float:
        return posterior(self.correct, self.incorrect, self.alpha, self.beta)

    @property
    def threshold_class(self) -> str:
        return threshold_class_for(self.cell_key.region_class)

    @property
    def phase(self) -> str:
        return compute_phase(self.cell_key.region_class, self.n_observed)


@dataclass
class MatrixCounters:
    """Trusted Beta counters + a weak-evidence tally, materialised by ledger replay."""

    cells: dict[tuple, WeightCell] = field(default_factory=dict)
    _weak: int = 0

    @classmethod
    def from_ledger(cls, entries) -> "MatrixCounters":
        """Replay ledger entries into trusted cells; tally everything else as weak.

        Only ``labels_emitted`` entries increment trusted counters. Any other
        outcome (ineligible_event_type, not_measurement_eligible, the skip
        outcomes) is weak evidence and never touches a trusted counter.
        """
        counters = cls()
        for entry in entries:
            if entry.get("outcome") != _TRUSTED_OUTCOME:
                counters._weak += 1
                continue
            # Defense-in-depth at the replay boundary (not just the gate at write
            # time): a labels_emitted entry whose event_type is not class-1
            # eligible is a corrupt authority claim -- forged, or written outside
            # record_observation. Fail closed: a corrupt trust claim blocks
            # replay (lock section 6 item 24), it is never trained on.
            if entry.get("event_type") not in ELIGIBLE_MATRIX_EVENT_TYPES:
                raise LedgerIntegrityError(
                    f"labels_emitted entry {entry.get('event_id')!r} has "
                    f"ineligible event_type {entry.get('event_type')!r}; "
                    "refusing to train"
                )
            for label in entry.get("labels", []):
                counters._apply_label(label)
        return counters

    def _apply_label(self, label: dict) -> None:
        key = CellKey(
            engine_version_key=label["engine_version_key"],
            scan_lineage_id=label["scan_lineage_id"],
            volume=label["volume"],
            region_class=label["region_class"],
        )
        cell = self.cells.get(key.as_tuple())
        if cell is None:
            cell = WeightCell(cell_key=key)
            self.cells[key.as_tuple()] = cell
        if label["binary_outcome"] == "correct":
            cell.correct += 1
        else:
            cell.incorrect += 1

    def trusted_cell(self, cell_key: CellKey) -> WeightCell | None:
        return self.cells.get(cell_key.as_tuple())

    def weak_count(self) -> int:
        return self._weak


def build_observation_entry(
    *,
    event_id: str,
    event_type: str,
    occurred_at: str,
    label: dict,
    gate: Class1GateResult,
) -> dict:
    """Turn a gate verdict into the ledger entry_fields to append.

    Gate allowed -> ``labels_emitted`` with the single label (trusted, trains).
    Gate blocked -> the mapped weak outcome, NO labels (the schema only allows
    ``labels`` on ``labels_emitted``), so weak evidence can never be replayed
    into a trusted counter.
    """
    fields: dict = {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
    }
    if gate.allowed:
        fields["outcome"] = _TRUSTED_OUTCOME
        fields["labels"] = [label]
    else:
        # weak_reason is always set when allowed is False (class1_gate contract).
        fields["outcome"] = _WEAK_REASON_TO_OUTCOME[gate.weak_reason]
    return fields


def record_observation(
    sink: MatrixObservationSink,
    *,
    event_id: str,
    event_type: str,
    occurred_at: str,
    label: dict,
    family_map_readiness: bool,
    family_diversity_count: int,
    independent_check_present: bool,
    is_dictionary_pass_only: bool,
) -> Class1GateResult:
    """Gate one observation and append the resulting entry to the B14 ledger.

    Returns the gate verdict. The caller serialises appends (single-writer
    constraint of the sink). Raises ``LedgerIntegrityError`` on a schema or
    hash-chain failure, surfacing it rather than silently dropping the event.
    """
    gate = evaluate_class1(
        family_map_readiness=family_map_readiness,
        family_diversity_count=family_diversity_count,
        independent_check_present=independent_check_present,
        event_type=event_type,
        is_dictionary_pass_only=is_dictionary_pass_only,
    )
    entry_fields = build_observation_entry(
        event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        label=label,
        gate=gate,
    )
    try:
        sink.append(entry_fields)
    except SchemaValidationError as exc:  # pragma: no cover - defensive surface
        raise LedgerIntegrityError(str(exc)) from exc
    return gate


__all__ = [
    "NEUTRAL_PRIOR",
    "CellKey",
    "WeightCell",
    "MatrixCounters",
    "compute_phase",
    "posterior",
    "threshold_class_for",
    "thresholds_for",
    "build_observation_entry",
    "record_observation",
]
