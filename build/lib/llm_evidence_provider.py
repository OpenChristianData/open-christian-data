"""B12 -- arch6 LLM-in-loop evidence provider + batching (S5 / arch6, Wave 4).

Consumes one reconciler dispute/queue position (B10 / S3 output) plus a mockable
LLM provider seam and produces, for one disputed canonical token:

  * a three-state LLM evidence record -- admission outcome (admit_for_resolution /
    admit_for_evidence_only / exclude) x event kind (llm_resolved / llm_candidate /
    llm_disagreement) x agreement result. A token is never collapsed to a single
    unqualified "answer"; per-model raw responses are always preserved.
  * a never-train projection -- the raw LLM record can never become a trusted matrix
    label. It projects through the B11 class-1 gate, which blocks every llm_* event
    type at the event_type conjunct (ineligible_event_type). Only a reviewer
    ratification event (choose_attestation) trains. The record itself carries the
    locked never-train constants measurement_eligible=False, matrix_updated=False.
  * reviewer-ratification batches -- the force-multiplier for the single reviewer
    (arch6 section 10): cap 50 per batch, high-stakes (evidence-only) items never
    share a batch with ordinary resolution items.

The HARD discipline (lock, LLM-in-loop section): three-state evidence; no unattested
canonical text (the LLM proposes evidence, never silently becomes the page text);
reviewer-ratified LLM output trains the matrix only as reviewer-confirmed -- the LLM
never trains the matrix on its own.

Contract source: ``plans/2026-05-28-arch6-llm-in-loop-synthesis.md`` sections 1.1-1.4
(admission), 6 (agreement normalization + attestation-match), 7.5 (event projection),
10 (ratification queue + batching), and the arch6 -> downstream handoff.

Scope note (B12 = the discipline-bearing core, against a mock seam). The full arch6
L-effort surface -- live provider adapters, the 3-index cache, vision + the shared
scan_crop module, the full ratification UI -- is downstream (arch7/arch8) and deferred.
B12 builds the three-state / no-unattested / never-train logic and batching, fully
testable against a mocked provider; the live-key dependency is flagged, not built.

Path note (commit-deviations.md): no new JSON schema is minted here. The llm-evidence-v1
schema is arch3-owned (the handoff lists refusal_reason / llm_evidence_linkage /
admission_outcome as "arch3 absorbs at next-touch"); minting it in a non-arch3 batch
would also trip the whole-tree enum-regen gate. The evidence record is validated
in-code, exactly as B11 validated the matrix snapshot. The reviewer ratification event
is a decision-event-v1 record on the existing (frozen) schema, written via the B15
DecisionStore by the caller.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Protocol

from build.lib.class1_gate import evaluate_class1
from build.lib.matrix_counters import build_observation_entry

# Three-state evidence vocabularies. These are arch6 logic constants, NOT a schema
# enum mirror (the llm-evidence-v1 schema is arch3-owned, not built here) -- so they
# use frozenset([...]) form per PIPE-26.
ADMISSION_OUTCOMES = frozenset(
    ["admit_for_resolution", "admit_for_evidence_only", "exclude"]
)
EVENT_KINDS = frozenset(["llm_resolved", "llm_candidate", "llm_disagreement"])
AGREEMENT_RESULTS = frozenset(
    [
        "all_required_models_agree_attested",
        "models_disagree",
        "single_model_only",
        "agreed_unattested",
        "normalization_ambiguous",
        "high_stakes_blocked",
        "malformed_or_refused",
        "context_unavailable",
    ]
)

# Locked never-train constants (arch3 section 2.15 + arch4 section 6.2). Every LLM
# evidence record carries these; they never flip. The matrix trains only on
# reviewer-confirmed decision events, never on raw LLM output.
MEASUREMENT_ELIGIBLE = False
MATRIX_UPDATED = False

# Default ratification batch size (arch6 section 10.4; B -- calibration knob).
DEFAULT_RATIFICATION_BATCH_SIZE = 50

# Protected region classes downgrade an admit_for_resolution to evidence-only
# regardless of dispute reason (arch6 section 1.1 dimension 2). Logic constant.
_PROTECTED_REGION_CLASSES = frozenset(
    [
        "headword",
        "foreign_language_greek",
        "foreign_language_hebrew",
        "foreign_language_latin",
        "foreign_language_german",
    ]
)

# arch6 dispute reason -> base admission outcome (arch6 section 1.1 dimension 1).
_ADMIT_BASE = {
    "engine_disagreement": "admit_for_resolution",
    "dictionary_fail": "admit_for_resolution",
    "narrow_margin": "admit_for_resolution",
    "external_check_absent": "admit_for_evidence_only",  # pre-screen; never resolves
    "region_class_unknown": "admit_for_evidence_only",  # proposal-only
}

# Reasons that exclude consultation entirely (arch6 section 1.1; high-stakes /
# structural / blocked-until-producer). context_violation_suspected is blocked in v1.
_EXCLUDE_REASONS = frozenset(
    [
        "ccel_disagreement",
        "derived_span_breaks_word_alignment",
        "bibliography_boundary_conflict",
        "single_attestation_learning",
        "single_attestation_bootstrap",
        "no_usable_signal",
        "context_violation_suspected",
    ]
)

# B10 reconciler reviewer-queue ``reason`` -> arch6 dispute reason. The reconciler
# (s3_reconciler.py) routes positions as dispute / consensus_unconfirmed /
# region_class_pending; arch6 names them engine_disagreement / external_check_absent /
# region_class_unknown.
RECONCILER_REASON_TO_DISPUTE = {
    "dispute": "engine_disagreement",
    "consensus_unconfirmed": "external_check_absent",
    "region_class_pending": "region_class_unknown",
}


class UnattestedTextError(ValueError):
    """Raised when LLM-proposed text is surfaced as canonical page text without an attestation.

    The no-unattested-canonical-text lock: the LLM proposes evidence; it never silently
    becomes the page text. Only an ``llm_resolved`` record whose agreed reading matched
    an engine attestation under permissive normalization yields canonical text, and that
    text is the attestation's source-faithful form -- not the LLM's casing.
    """


@dataclass(frozen=True)
class Attestation:
    """One engine candidate reading for the disputed position."""

    observation_token_id: str
    engine_family: str
    text: str  # source-faithful, exactly as the engine produced it


@dataclass(frozen=True)
class DisputeContext:
    """The reconciler dispute position the LLM is consulted about (arch6 section 1.3 input)."""

    canonical_token_id: str
    volume: int
    page_id: str
    article_id: str
    dispute_reason: str
    region_class: str
    candidate_attestations: tuple[Attestation, ...]
    ccel_disagreement: bool = False


@dataclass(frozen=True)
class ConsultationPlan:
    """The triage decision -- recorded on every evidence record (arch6 section 1.3).

    ``build_llm_consultation_plan`` must not call a model and must not modify the
    canonical token; this plan is pure triage.
    """

    admission_outcome: str
    dispute_reason: str
    region_class: str
    protected_qualifiers: tuple[str, ...]
    dispute: DisputeContext


@dataclass(frozen=True)
class ProviderResponse:
    """One per-provider response. Raw text is always preserved (arch6 section 1.4)."""

    provider_id: str
    model_family: str
    response_status: str  # answered | refused | malformed | abstained
    selected_text: str | None
    raw_text: str
    proposal_kind: str = "resolution"


class LLMProvider(Protocol):
    """The mockable provider seam. Live adapters (Claude/Qwen/free-tier) are deferred."""

    provider_id: str
    model_family: str

    def consult(self, plan: ConsultationPlan) -> ProviderResponse: ...


@dataclass
class FakeProvider:
    """In-repo mock provider implementing ``LLMProvider``.

    This is the seam that lets B12 build + test the three-state / never-train logic
    with NO live key (build prompt resource note, rule 4). The live provider adapters
    are a deferred resource dependency, not part of B12.
    """

    response: ProviderResponse
    called: bool = False

    @property
    def provider_id(self) -> str:
        return self.response.provider_id

    @property
    def model_family(self) -> str:
        return self.response.model_family

    def consult(self, plan: ConsultationPlan) -> ProviderResponse:
        self.called = True
        return self.response


@dataclass(frozen=True)
class LLMEvidenceRecord:
    """A three-state LLM evidence record for one disputed token.

    Never-train by construction: ``measurement_eligible`` and ``matrix_updated`` are
    the locked False constants; ``matched_attestation`` is the ONLY source of canonical
    text, and only on an ``llm_resolved`` event.
    """

    consultation_id: str
    canonical_token_id: str
    volume: int
    page_id: str
    article_id: str
    dispute_reason: str
    region_class: str
    admission_outcome: str
    event_kind: str
    agreement_result: str
    agreed_text: str | None
    matched_attestation: Attestation | None
    diagnostic_tags: tuple[str, ...]
    per_provider: tuple[ProviderResponse, ...]
    # Immutable snapshot of the candidate attestations this consultation saw.
    # resolve_canonical_text requires the matched attestation to be identical (id AND
    # source-faithful text) to one of these, so a forged/stale matched_attestation --
    # even one reusing a real candidate id with altered text -- cannot yield canonical
    # text (defense in depth; mirrors B11 snapshot re-derivation).
    candidate_attestations: tuple[Attestation, ...] = ()
    measurement_eligible: bool = MEASUREMENT_ELIGIBLE
    matrix_updated: bool = MATRIX_UPDATED


def permissive_normalize(text: str) -> str:
    """Permissive agreement normalization (arch6 section 6.1) -- for equality only.

    NFC -> casefold -> quote-fold -> diacritic strip -> internal-whitespace collapse ->
    leading/trailing punctuation strip. Never alters canonical / attestation / published
    text; it exists only to test whether two readings are "the same" for the agreement
    gate and the attestation-match check.
    """
    s = unicodedata.normalize("NFC", text)
    s = s.casefold()
    for quote in ("‘", "’", "“", "”", "`", "´"):
        s = s.replace(quote, "'")
    s = "".join(ch for ch in unicodedata.normalize("NFD", s) if not unicodedata.combining(ch))
    s = " ".join(s.split())
    return s.strip(".,;:!?\"'()[]{}-")


def build_consultation_plan(dispute: DisputeContext) -> ConsultationPlan:
    """Triage one dispute into a three-state admission outcome (arch6 section 1.1/1.2).

    Fail-closed: an unknown dispute reason excludes rather than silently admitting.
    A ccel_disagreement flag or an excluded reason forces ``exclude``. A protected
    region class downgrades ``admit_for_resolution`` to ``admit_for_evidence_only``.
    """
    reason = RECONCILER_REASON_TO_DISPUTE.get(dispute.dispute_reason, dispute.dispute_reason)

    protected_qualifiers: list[str] = []
    if dispute.region_class in _PROTECTED_REGION_CLASSES:
        protected_qualifiers.append(f"region_class:{dispute.region_class}")
    if dispute.ccel_disagreement:
        protected_qualifiers.append("ccel_disagreement")

    if dispute.ccel_disagreement or reason in _EXCLUDE_REASONS:
        outcome = "exclude"
    else:
        base = _ADMIT_BASE.get(reason)
        if base is None:
            outcome = "exclude"  # fail closed on an unrecognized reason
        elif base == "admit_for_resolution" and dispute.region_class in _PROTECTED_REGION_CLASSES:
            outcome = "admit_for_evidence_only"
        else:
            outcome = base

    return ConsultationPlan(
        admission_outcome=outcome,
        dispute_reason=reason,
        region_class=dispute.region_class,
        protected_qualifiers=tuple(protected_qualifiers),
        dispute=dispute,
    )


def _consultation_id(dispute: DisputeContext) -> str:
    return f"llm-{dispute.volume}-{dispute.page_id}-{dispute.canonical_token_id}"


def _matching_attestations(
    agreed_norm: str, attestations: tuple[Attestation, ...]
) -> list[Attestation]:
    """Return every attestation whose permissive-normalized text equals the agreed text."""
    return [a for a in attestations if permissive_normalize(a.text) == agreed_norm]


def run_consultation(
    plan: ConsultationPlan,
    providers: list[LLMProvider],
    *,
    occurred_at: str,
) -> LLMEvidenceRecord | None:
    """Dispatch the consultation to the (mock) providers and project a three-state record.

    Returns None when the plan excludes consultation (no llm-evidence record is written).
    Applies the family-independent agreement gate + the attestation-match check
    (arch6 section 6). ``occurred_at`` is caller-supplied so the function is deterministic
    and import-safe (DATE-01 / PY-06).
    """
    dispute = plan.dispute
    if plan.admission_outcome == "exclude":
        return None

    per_provider = tuple(p.consult(plan) for p in providers)
    answered = [
        r for r in per_provider if r.response_status == "answered" and r.selected_text is not None
    ]

    # Group answered responses by normalized reading -> the set of distinct families.
    groups: dict[str, set[str]] = {}
    norm_to_raw: dict[str, str] = {}
    for response in answered:
        norm = permissive_normalize(response.selected_text)  # type: ignore[arg-type]
        groups.setdefault(norm, set()).add(response.model_family)
        norm_to_raw.setdefault(norm, response.selected_text)  # type: ignore[index]

    diagnostic_tags: list[str] = []
    matched: Attestation | None = None
    agreed_text: str | None = None

    if not answered:
        agreement_result = "malformed_or_refused"
        event_kind = "llm_candidate"
        diagnostic_tags.append("llm_unusable_context")
    elif len(answered) == 1:
        # A one-model answer never becomes llm_resolved (arch6 dispatch invariant).
        agreement_result = "single_model_only"
        event_kind = "llm_candidate"
    else:
        agreeing_norms = [norm for norm, families in groups.items() if len(families) >= 2]
        if len(agreeing_norms) != 1:
            # Zero agreeing camps, or the answering families split into >=2 distinct
            # agreeing camps -- a genuine disagreement, never a resolution (arch6 6.4).
            agreement_result = "models_disagree"
            event_kind = "llm_disagreement"
        elif plan.admission_outcome == "admit_for_evidence_only":
            # High-stakes / evidence-only: agreement is recorded as evidence, never resolved.
            agreement_result = "high_stakes_blocked"
            event_kind = "llm_candidate"
            agreed_text = norm_to_raw[agreeing_norms[0]]
        else:
            agreeing_norm = agreeing_norms[0]
            agreed_text = norm_to_raw[agreeing_norm]
            matches = _matching_attestations(agreeing_norm, dispute.candidate_attestations)
            distinct_raw = {a.text for a in matches}
            if agreeing_norm == "":
                # arch6 section 6.3 hard fail: an empty comparison string never resolves.
                agreement_result = "agreed_unattested"
                event_kind = "llm_candidate"
                diagnostic_tags.append("empty_after_normalization")
            elif not matches:
                # Agreed on text in NO attestation -> never canonical; reviewer-routed.
                agreement_result = "agreed_unattested"
                event_kind = "llm_candidate"
                diagnostic_tags.append("unattested_proposal")
            elif len(distinct_raw) >= 2:
                # arch6 section 6.3/6.4: the agreed reading collapses onto >=2 distinct raw
                # attestations under permissive normalization. Fail closed -- route to the
                # reviewer (llm_disagreement), never silently pick one. The glyph-variant
                # exemption (arch3 Position A fingerprint equality) is a v2 refinement that
                # needs the arch3-owned fingerprint normalizer; v1 conservatively routes all
                # multi-distinct-raw matches to review.
                agreement_result = "normalization_ambiguous"
                event_kind = "llm_disagreement"
                diagnostic_tags.append("normalization_ambiguous")
            else:
                matched = matches[0]
                agreement_result = "all_required_models_agree_attested"
                event_kind = "llm_resolved"

    return LLMEvidenceRecord(
        consultation_id=_consultation_id(dispute),
        canonical_token_id=dispute.canonical_token_id,
        volume=dispute.volume,
        page_id=dispute.page_id,
        article_id=dispute.article_id,
        dispute_reason=plan.dispute_reason,
        region_class=plan.region_class,
        admission_outcome=plan.admission_outcome,
        event_kind=event_kind,
        agreement_result=agreement_result,
        agreed_text=agreed_text,
        matched_attestation=matched,
        diagnostic_tags=tuple(diagnostic_tags),
        per_provider=per_provider,
        candidate_attestations=dispute.candidate_attestations,
    )


def resolve_canonical_text(record: LLMEvidenceRecord) -> str:
    """Return the source-faithful canonical text for a resolved token, or refuse.

    No-unattested-canonical-text guard (defense in depth, beyond the run_consultation
    gate). Canonical text is ONLY ever the matched attestation's source-faithful form on
    an ``llm_resolved`` event; any other state -- candidate, disagreement, or a resolved
    record with no matched attestation -- raises rather than surfacing LLM text as page text.

    Threat boundary: this guard defends against a stale or partially-forged record -- a
    swapped/altered ``matched_attestation``, an id reused with altered text, an
    agreed_text mismatch. It does NOT defend against a wholesale-fabricated record whose
    ``candidate_attestations`` snapshot is itself forged self-consistently; no in-function
    check can (the same caller could write canonical text directly). Integrity against
    wholesale fabrication is the cache-poisoning layer's job -- raw-response / context-hash
    verification before a record is admitted (arch6 section 8.4), deferred with the cache
    subsystem (downstream of B12). Records here are frozen (producer-issued, immutable).
    """
    if record.event_kind != "llm_resolved" or record.matched_attestation is None:
        raise UnattestedTextError(
            f"refusing to surface canonical text from a {record.event_kind!r} record "
            f"(agreement_result={record.agreement_result!r}); LLM proposals are evidence, "
            "never page text, unless matched to an attestation"
        )
    matched = record.matched_attestation
    # Re-derive integrity rather than trusting the carried matched_attestation object
    # (defense in depth; mirrors B11 snapshot re-derivation). The matched attestation
    # must (a) be IDENTICAL (id AND source-faithful text) to one of the candidate
    # attestations this consultation actually saw -- so reusing a real candidate id with
    # altered text fails -- and (b) normalize-equal the agreed reading. Either failing
    # means the record is forged or stale -- refuse to surface its text as canonical.
    if matched not in record.candidate_attestations:
        raise UnattestedTextError(
            f"matched attestation {matched.observation_token_id!r} is not identical to any "
            "recorded candidate attestation; refusing to surface unprovenanced text as canonical"
        )
    if not record.agreed_text or permissive_normalize(matched.text) != permissive_normalize(
        record.agreed_text
    ):
        raise UnattestedTextError(
            "matched attestation does not normalize-equal the agreed reading; "
            "refusing to surface inconsistent text as canonical"
        )
    return matched.text


# A placeholder label for the never-train projection. The class-1 gate blocks every
# llm_* event_type before the label is ever consulted, so this is never trained on; it
# exists only to satisfy build_observation_entry's signature.
_NULL_LABEL = {
    "engine_version_key": "llm",
    "scan_lineage_id": "llm",
    "volume": 0,
    "region_class": "unknown",
    "binary_outcome": "incorrect",
}


def project_to_matrix_event(
    record: LLMEvidenceRecord, *, event_id: str, occurred_at: str
) -> dict:
    """Project an LLM evidence record to a matrix-events ledger entry -- always ineligible.

    Runs the B11 class-1 gate with the record's llm_* event_kind under deliberately
    fully-ready family-map inputs to prove the point: the event_type conjunct blocks it
    regardless. The outcome is never ``labels_emitted`` and the entry carries no labels,
    so replay can never train a trusted counter on raw LLM output (lock never-train rule).
    """
    gate = evaluate_class1(
        family_map_readiness=True,
        family_diversity_count=2,
        independent_check_present=True,
        event_type=record.event_kind,
        is_dictionary_pass_only=False,
    )
    return build_observation_entry(
        event_id=event_id,
        event_type=record.event_kind,
        occurred_at=occurred_at,
        label=_NULL_LABEL,
        gate=gate,
    )


_REVIEWER_RELATION = {
    "confirm": "confirmed",
    "override": "overrode_attestation",
}
_DECISION_TOKEN = {
    "confirm": "ratification",
    "override": "override",
}


def build_ratification_decision_event(
    record: LLMEvidenceRecord,
    *,
    reviewer_action: str,
    actor_id: str,
    timestamp: str,
    selected_observation_token_id: str | None = None,
) -> dict:
    """Build the reviewer ratification decision-event (the ONLY training path for LLM evidence).

    Emits a ``choose_attestation`` decision-event-v1 record (authority_decision) carrying
    the ``llm_evidence_linkage`` block (arch6 section 10.6). This is the reviewer-confirmed
    event the matrix may train on -- the LLM evidence is *linked*, never laundered into
    authority. The caller writes it via the B15 DecisionStore (which derives event_id /
    hashes). measurement_eligible is True: a reviewer made this decision.

    For ``confirm`` the selected attestation defaults to the record's matched attestation;
    an ``override`` must pass ``selected_observation_token_id`` explicitly.
    """
    if reviewer_action not in _REVIEWER_RELATION:
        raise ValueError(
            f"unsupported reviewer_action {reviewer_action!r}; "
            f"expected one of {sorted(_REVIEWER_RELATION)}"
        )

    if selected_observation_token_id is None:
        if record.matched_attestation is None:
            raise ValueError(
                "confirm requires a matched attestation or an explicit "
                "selected_observation_token_id"
            )
        selected_observation_token_id = record.matched_attestation.observation_token_id

    decision_token = _DECISION_TOKEN[reviewer_action]
    return {
        "schema_version": "decision-event-v1",
        "event_type": "choose_attestation",
        "event_category": "authority_decision",
        "volume": record.volume,
        "actor_id": actor_id,
        "timestamp": timestamp,
        "canonical_token_id": record.canonical_token_id,
        "structural_path_at_decision": f"{record.page_id}/{record.article_id}",
        "previous_status_at_view": "llm_resolved"
        if record.event_kind == "llm_resolved"
        else "unresolved",
        "new_status": "reviewed",
        "selected_observation_token_id": selected_observation_token_id,
        "decision_token": decision_token,
        "measurement_eligible": True,
        "evidence_seen": {
            "llm_evidence_linkage": {
                "record_ids": [record.consultation_id],
                "reviewer_relation": _REVIEWER_RELATION[reviewer_action],
                "decision_token": decision_token,
                "model_proposal_text": record.agreed_text,
            }
        },
    }


@dataclass(frozen=True)
class RatificationBatch:
    """A page-local batch of ratification items (arch6 section 10.4)."""

    batch_id: str
    volume: int
    page_id: str
    dispute_reason: str
    admission_outcome: str
    records: tuple[LLMEvidenceRecord, ...]


def build_ratification_batches(
    records: list[LLMEvidenceRecord],
    *,
    batch_size: int = DEFAULT_RATIFICATION_BATCH_SIZE,
) -> list[RatificationBatch]:
    """Group LLM evidence records into reviewer-ratification batches (the throughput multiplier).

    Grouping key: volume, page, article, dispute reason, AND admission outcome -- so
    high-stakes ``admit_for_evidence_only`` items never share a batch with ordinary
    ``admit_for_resolution`` items (arch6 section 10.4). Each group is chunked at
    ``batch_size`` (default 50). Every input record lands in exactly one batch.
    """
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")

    groups: dict[tuple, list[LLMEvidenceRecord]] = {}
    order: list[tuple] = []
    for record in records:
        key = (
            record.volume,
            record.page_id,
            record.article_id,
            record.dispute_reason,
            record.admission_outcome,
        )
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(record)

    batches: list[RatificationBatch] = []
    for key in order:
        volume, page_id, article_id, dispute_reason, admission_outcome = key
        group = groups[key]
        for chunk_index in range(0, len(group), batch_size):
            chunk = group[chunk_index : chunk_index + batch_size]
            seq = chunk_index // batch_size
            batches.append(
                RatificationBatch(
                    batch_id=f"rb-{volume}-{page_id}-{article_id}-{dispute_reason}-{admission_outcome}-{seq}",
                    volume=volume,
                    page_id=page_id,
                    dispute_reason=dispute_reason,
                    admission_outcome=admission_outcome,
                    records=tuple(chunk),
                )
            )
    return batches


__all__ = [
    "ADMISSION_OUTCOMES",
    "EVENT_KINDS",
    "AGREEMENT_RESULTS",
    "MEASUREMENT_ELIGIBLE",
    "MATRIX_UPDATED",
    "DEFAULT_RATIFICATION_BATCH_SIZE",
    "RECONCILER_REASON_TO_DISPUTE",
    "Attestation",
    "DisputeContext",
    "ConsultationPlan",
    "ProviderResponse",
    "LLMProvider",
    "FakeProvider",
    "LLMEvidenceRecord",
    "RatificationBatch",
    "UnattestedTextError",
    "permissive_normalize",
    "build_consultation_plan",
    "run_consultation",
    "resolve_canonical_text",
    "project_to_matrix_event",
    "build_ratification_decision_event",
    "build_ratification_batches",
]
