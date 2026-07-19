"""B12 -- arch6 LLM-in-loop evidence provider + batching, failing-first tests (TEST-16).

Architectural slot: S5 / arch6 (LLM-in-loop), Wave 4. The provider consumes a
reconciler dispute/queue position (B10 / S3 output) plus a mockable LLM provider
seam and produces, for one disputed canonical token:

  * a three-state LLM evidence record (admission outcome x event kind x agreement
    result) -- a token is never collapsed to a single unqualified "answer";
  * a never-train projection: the raw LLM record can never become a trusted matrix
    label (it projects ineligible through the B11 class-1 gate); only a reviewer
    ratification event (choose_attestation) trains;
  * reviewer-ratification batches that multiply the single reviewer's throughput.

These tests are the B12 TDD contract from the build prompt + arch D plan (section 2,
B12 row) -- written-failed-then-satisfied, never authored after the code. The three
named contracts:

  1. three-state evidence  -- the provider emits the three evidence states; a token
                              is never collapsed to a single unqualified answer.
  2. no unattested text    -- LLM-proposed text never enters canonical output without
                              an attestation; an attempt to surface unattested LLM
                              text as page text is rejected.
  3. reviewer-ratified-only training -- LLM output trains the matrix only after
                              reviewer confirmation; raw LLM output never trains.
                              Run against a MOCKED provider so the test needs no key.

The provider seam is a Protocol; tests inject FakeProvider instances. No live key,
no network -- the never-train + three-state logic is the deliverable and is fully
testable against a mock (build prompt resource note, rule 4).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ocd_kernel.lib.class1_gate import evaluate_class1  # noqa: E402
from build.lib.llm_evidence_provider import (  # noqa: E402
    ADMISSION_OUTCOMES,
    EVENT_KINDS,
    MATRIX_UPDATED,
    MEASUREMENT_ELIGIBLE,
    Attestation,
    DisputeContext,
    FakeProvider,
    LLMEvidenceRecord,
    ProviderResponse,
    UnattestedTextError,
    build_consultation_plan,
    build_ratification_batches,
    build_ratification_decision_event,
    project_to_matrix_event,
    resolve_canonical_text,
    run_consultation,
)
from build.lib.matrix_counters import record_observation  # noqa: E402
from build.lib.matrix_observation_sink import MatrixObservationSink  # noqa: E402

OCCURRED_AT = "2026-05-30T00:00:00+00:00"
CT = "ct-sha256:" + "a" * 64


def _attestations(*pairs):
    """Build attestations from (engine_family, text) pairs with synthetic token ids."""
    out = []
    for index, (family, text) in enumerate(pairs):
        out.append(
            Attestation(
                observation_token_id="ot-sha256:" + f"{index:064d}",
                engine_family=family,
                text=text,
            )
        )
    return tuple(out)


def _dispute(
    *,
    reason="engine_disagreement",
    region_class="body",
    attestations=None,
    ccel_disagreement=False,
):
    return DisputeContext(
        canonical_token_id=CT,
        volume=1,
        page_id="vol_01_0042",
        article_id="ABELARD",
        dispute_reason=reason,
        region_class=region_class,
        candidate_attestations=attestations
        if attestations is not None
        else _attestations(("abbyy", "ABELARD"), ("tesseract", "ABELAKD")),
        ccel_disagreement=ccel_disagreement,
    )


def _provider(provider_id, family, selected_text, status="answered"):
    return FakeProvider(
        response=ProviderResponse(
            provider_id=provider_id,
            model_family=family,
            response_status=status,
            selected_text=selected_text,
            raw_text=f'{{"selected_text": {selected_text!r}}}',
        )
    )


# ---------------------------------------------------------------------------
# Contract 1 -- three-state evidence (never collapsed to a single answer)
# ---------------------------------------------------------------------------

def test_three_state_evidence_admission_outcome_is_one_of_three():
    """Every plan carries a three-state admission outcome, never a bare admit bool."""
    plan = build_consultation_plan(_dispute())
    assert plan.admission_outcome in ADMISSION_OUTCOMES
    assert ADMISSION_OUTCOMES == frozenset(
        {"admit_for_resolution", "admit_for_evidence_only", "exclude"}
    )


def test_three_state_evidence_emits_all_three_event_kinds():
    """The provider can emit each of the three locked event kinds from real inputs.

    Two independent families agreeing on an attested reading -> llm_resolved.
    A single answering model -> llm_candidate (never resolved on one model).
    Two families selecting different readings -> llm_disagreement.
    """
    atts = _attestations(("abbyy", "ABELARD"), ("tesseract", "ABELAKD"))

    resolved = run_consultation(
        build_consultation_plan(_dispute(attestations=atts)),
        [_provider("p_a", "claude", "Abelard"), _provider("p_b", "qwen", "Abelard")],
        occurred_at=OCCURRED_AT,
    )
    candidate = run_consultation(
        build_consultation_plan(_dispute(attestations=atts)),
        [_provider("p_a", "claude", "Abelard"), _provider("p_b", "qwen", None, status="abstained")],
        occurred_at=OCCURRED_AT,
    )
    disagreement = run_consultation(
        build_consultation_plan(_dispute(attestations=atts)),
        [_provider("p_a", "claude", "Abelard"), _provider("p_b", "qwen", "Abelakd")],
        occurred_at=OCCURRED_AT,
    )

    assert resolved.event_kind == "llm_resolved"
    assert candidate.event_kind == "llm_candidate"
    assert disagreement.event_kind == "llm_disagreement"
    # All three are valid locked event kinds; none is a bare string answer.
    for record in (resolved, candidate, disagreement):
        assert record.event_kind in EVENT_KINDS
        assert record.agreement_result is not None
        assert record.admission_outcome in ADMISSION_OUTCOMES
        # Per-model raw responses are always preserved (never flattened to one answer).
        assert len(record.per_provider) == 2


def test_three_state_single_model_never_resolves():
    """A one-model answer never becomes llm_resolved (arch6 dispatch invariant)."""
    record = run_consultation(
        build_consultation_plan(_dispute()),
        [_provider("p_a", "claude", "Abelard")],
        occurred_at=OCCURRED_AT,
    )
    assert record.event_kind == "llm_candidate"
    assert record.agreement_result == "single_model_only"


def test_three_state_high_stakes_blocks_resolution():
    """A protected region_class downgrades admission to evidence-only; never resolves.

    Even when two families agree on an attested reading, a headword token is
    admit_for_evidence_only and the provider emits llm_candidate, not llm_resolved
    (arch6 AR-6 high-stakes misrouting guard).
    """
    plan = build_consultation_plan(_dispute(region_class="headword"))
    assert plan.admission_outcome == "admit_for_evidence_only"
    record = run_consultation(
        plan,
        [_provider("p_a", "claude", "Abelard"), _provider("p_b", "qwen", "Abelard")],
        occurred_at=OCCURRED_AT,
    )
    assert record.event_kind == "llm_candidate"


def test_excluded_dispute_produces_no_record():
    """ccel_disagreement forces exclude -> no consultation, no evidence record."""
    plan = build_consultation_plan(_dispute(ccel_disagreement=True))
    assert plan.admission_outcome == "exclude"
    record = run_consultation(
        plan,
        [_provider("p_a", "claude", "Abelard"), _provider("p_b", "qwen", "Abelard")],
        occurred_at=OCCURRED_AT,
    )
    assert record is None


# ---------------------------------------------------------------------------
# Contract 2 -- no unattested canonical text
# ---------------------------------------------------------------------------

def test_no_unattested_text_agreed_unattested_is_candidate_not_resolved():
    """Two families agreeing on text in NO attestation never resolves.

    The agreed reading must match an attestation under permissive normalization.
    "Abailard" is not in {ABELARD, ABELAKD} -> agreed_unattested -> llm_candidate.
    """
    atts = _attestations(("abbyy", "ABELARD"), ("tesseract", "ABELAKD"))
    record = run_consultation(
        build_consultation_plan(_dispute(attestations=atts)),
        [_provider("p_a", "claude", "Abailard"), _provider("p_b", "qwen", "Abailard")],
        occurred_at=OCCURRED_AT,
    )
    assert record.event_kind == "llm_candidate"
    assert record.agreement_result == "agreed_unattested"
    assert "unattested_proposal" in record.diagnostic_tags


def test_no_unattested_text_resolve_canonical_rejects_unattested():
    """Surfacing unattested LLM text as canonical page text is rejected."""
    atts = _attestations(("abbyy", "ABELARD"), ("tesseract", "ABELAKD"))
    record = run_consultation(
        build_consultation_plan(_dispute(attestations=atts)),
        [_provider("p_a", "claude", "Abailard"), _provider("p_b", "qwen", "Abailard")],
        occurred_at=OCCURRED_AT,
    )
    with pytest.raises(UnattestedTextError):
        resolve_canonical_text(record)


def test_no_unattested_text_normalization_ambiguous_does_not_resolve():
    """An agreed reading collapsing onto >=2 DISTINCT attestations never auto-resolves.

    arch6 section 6.3 hard fail / section 6.4 normalization_ambiguous: when permissive
    normalization makes the agreed text match two distinct raw attestations, the token
    is routed to the reviewer (llm_disagreement), not silently resolved to one of them.
    """
    atts = _attestations(("abbyy", "bear."), ("tesseract", "bear,"))
    record = run_consultation(
        build_consultation_plan(_dispute(attestations=atts)),
        [_provider("p_a", "claude", "bear"), _provider("p_b", "qwen", "bear")],
        occurred_at=OCCURRED_AT,
    )
    assert record.agreement_result == "normalization_ambiguous"
    assert record.event_kind == "llm_disagreement"
    assert record.matched_attestation is None
    with pytest.raises(UnattestedTextError):
        resolve_canonical_text(record)


def test_no_unattested_text_resolve_rejects_forged_matched_attestation():
    """resolve_canonical_text refuses a matched_attestation absent from the record's provenance.

    Defense in depth (mirrors B11 snapshot re-derivation): a record carrying a forged
    or stale matched_attestation -- one whose observation_token_id is not in the recorded
    candidate set -- must not yield canonical text.
    """
    forged = LLMEvidenceRecord(
        consultation_id="llm-forged",
        canonical_token_id="ct-forged",
        volume=1,
        page_id="p1",
        article_id="a1",
        dispute_reason="engine_disagreement",
        region_class="body",
        admission_outcome="admit_for_resolution",
        event_kind="llm_resolved",
        agreement_result="all_required_models_agree_attested",
        agreed_text="FORGED",
        matched_attestation=Attestation(
            observation_token_id="ot-forged",
            engine_family="not-an-engine",
            text="FORGED",
        ),
        diagnostic_tags=(),
        per_provider=(),
        candidate_attestations=(),
    )
    with pytest.raises(UnattestedTextError):
        resolve_canonical_text(forged)


def test_no_unattested_text_resolve_rejects_real_id_forged_text():
    """A matched_attestation reusing a real candidate id but altered text is refused.

    Storing only ids would let a forged record with a genuine candidate id and a
    self-consistent forged text/agreed_text slip through. The guard requires the
    matched attestation to be IDENTICAL (id AND source-faithful text) to a recorded
    candidate.
    """
    real_id = "ot-sha256:" + "0" * 64
    forged = LLMEvidenceRecord(
        consultation_id="llm-forged2",
        canonical_token_id="ct-forged",
        volume=1,
        page_id="p1",
        article_id="a1",
        dispute_reason="engine_disagreement",
        region_class="body",
        admission_outcome="admit_for_resolution",
        event_kind="llm_resolved",
        agreement_result="all_required_models_agree_attested",
        agreed_text="FORGED",
        matched_attestation=Attestation(real_id, "abbyy", "FORGED"),
        diagnostic_tags=(),
        per_provider=(),
        # The recorded candidate has the same id but the real (different) text.
        candidate_attestations=(Attestation(real_id, "abbyy", "ABELARD"),),
    )
    with pytest.raises(UnattestedTextError):
        resolve_canonical_text(forged)


def test_three_state_multi_cluster_agreement_is_disagreement_not_resolved():
    """When answering families split into two agreeing camps, the token never resolves.

    Two families agree on "Abelard" and two on "Abelakd" -- a 2-2 split is a genuine
    disagreement (arch6 section 6.4), not a resolution to the first camp.
    """
    atts = _attestations(("abbyy", "ABELARD"), ("tesseract", "ABELAKD"))
    record = run_consultation(
        build_consultation_plan(_dispute(attestations=atts)),
        [
            _provider("p_a", "claude", "Abelard"),
            _provider("p_b", "qwen", "Abelard"),
            _provider("p_c", "llama", "Abelakd"),
            _provider("p_d", "mistral", "Abelakd"),
        ],
        occurred_at=OCCURRED_AT,
    )
    assert record.event_kind == "llm_disagreement"
    assert record.agreement_result == "models_disagree"
    assert record.matched_attestation is None


def test_no_unattested_text_empty_after_normalization_is_candidate():
    """An agreed reading that is empty after normalization never resolves."""
    atts = _attestations(("abbyy", "ABELARD"), ("tesseract", "ABELAKD"))
    record = run_consultation(
        build_consultation_plan(_dispute(attestations=atts)),
        [_provider("p_a", "claude", "..."), _provider("p_b", "qwen", "--")],
        occurred_at=OCCURRED_AT,
    )
    assert record.event_kind == "llm_candidate"
    assert "empty_after_normalization" in record.diagnostic_tags
    with pytest.raises(UnattestedTextError):
        resolve_canonical_text(record)


def test_no_unattested_text_resolved_returns_source_faithful_attestation():
    """A resolved token's canonical text is the attestation's source-faithful form.

    Both models propose the correctly-cased "Abelard"; the matched attestation is
    the small-caps headword "ABELARD" -- the WRITTEN canonical text preserves what
    the OCR saw, not the LLM's casing (arch6 section 6.2).
    """
    atts = _attestations(("abbyy", "ABELARD"), ("tesseract", "ABELAKD"))
    record = run_consultation(
        build_consultation_plan(_dispute(attestations=atts)),
        [_provider("p_a", "claude", "Abelard"), _provider("p_b", "qwen", "Abelard")],
        occurred_at=OCCURRED_AT,
    )
    assert record.event_kind == "llm_resolved"
    assert resolve_canonical_text(record) == "ABELARD"


# ---------------------------------------------------------------------------
# Contract 3 -- reviewer-ratified-only training
# ---------------------------------------------------------------------------

def test_reviewer_ratified_only_raw_llm_never_trains(tmp_path):
    """Even under fully-ready family-map conditions, a raw LLM event never trains.

    The matrix candidate projected from an llm_resolved record carries an llm_*
    event_type, which the class-1 gate blocks at the event_type conjunct -> the
    outcome is never labels_emitted, regardless of family diversity / readiness.
    """
    atts = _attestations(("abbyy", "ABELARD"), ("tesseract", "ABELAKD"))
    record = run_consultation(
        build_consultation_plan(_dispute(attestations=atts)),
        [_provider("p_a", "claude", "Abelard"), _provider("p_b", "qwen", "Abelard")],
        occurred_at=OCCURRED_AT,
    )

    candidate = project_to_matrix_event(record, event_id="ev-llm-1", occurred_at=OCCURRED_AT)
    assert candidate["outcome"] != "labels_emitted"
    assert "labels" not in candidate

    # The record itself is stamped never-train.
    assert record.measurement_eligible is False
    assert record.matrix_updated is False
    assert MEASUREMENT_ELIGIBLE is False
    assert MATRIX_UPDATED is False

    # Defense in depth: the gate, called directly with the llm event_kind under
    # fully-ready conditions, still blocks (event_type conjunct fails closed).
    gate = evaluate_class1(
        family_map_readiness=True,
        family_diversity_count=5,
        independent_check_present=True,
        event_type=record.event_kind,
        is_dictionary_pass_only=False,
    )
    assert gate.allowed is False
    assert gate.weak_reason == "llm_resolved_event"


def test_reviewer_ratification_event_trains_when_family_map_ready(tmp_path):
    """A reviewer choose_attestation ratification IS trainable once the gate clears.

    The reviewer confirms the LLM-proposed attestation -> a choose_attestation
    decision-event carrying the llm_evidence_linkage. That event_type is class-1
    eligible, so with family-map readiness it trains (labels_emitted) -- proving
    training happens only via reviewer confirmation, never the raw LLM output.
    """
    atts = _attestations(("abbyy", "ABELARD"), ("tesseract", "ABELAKD"))
    record = run_consultation(
        build_consultation_plan(_dispute(attestations=atts)),
        [_provider("p_a", "claude", "Abelard"), _provider("p_b", "qwen", "Abelard")],
        occurred_at=OCCURRED_AT,
    )

    event = build_ratification_decision_event(
        record,
        reviewer_action="confirm",
        actor_id="maintainer",
        timestamp=OCCURRED_AT,
    )
    assert event["event_type"] == "choose_attestation"
    assert event["decision_token"] == "ratification"
    assert event["measurement_eligible"] is True
    # The LLM evidence is linked, not laundered into canonical authority.
    linkage = event["evidence_seen"]["llm_evidence_linkage"]
    assert linkage["reviewer_relation"] == "confirmed"
    assert record.canonical_token_id in (event["canonical_token_id"],)

    # That reviewer event, fed to the matrix with readiness, trains.
    sink = MatrixObservationSink(repo_root=tmp_path, policy_version="p-v1")
    label = {
        "engine_version_key": "abbyy@v1",
        "scan_lineage_id": "ia-abbyy-v1",
        "volume": 1,
        "region_class": "body",
        "binary_outcome": "correct",
    }
    gate = record_observation(
        sink,
        event_id=event["event_id"] if event.get("event_id") else "de-ratify-1",
        event_type="choose_attestation",
        occurred_at=OCCURRED_AT,
        label=label,
        family_map_readiness=True,
        family_diversity_count=2,
        independent_check_present=True,
        is_dictionary_pass_only=False,
    )
    assert gate.allowed is True


# ---------------------------------------------------------------------------
# Batching -- multiply the single reviewer's throughput
# ---------------------------------------------------------------------------

def test_batching_caps_size_and_never_mixes_high_stakes():
    """Ratification batches cap at the configured size and isolate high-stakes items.

    admit_for_evidence_only (protected/high-stakes) items never share a batch with
    ordinary admit_for_resolution items (arch6 section 10.4).
    """
    atts = _attestations(("abbyy", "ABELARD"), ("tesseract", "ABELAKD"))
    ordinary = [
        run_consultation(
            build_consultation_plan(_dispute(attestations=atts)),
            [_provider("p_a", "claude", "Abelard"), _provider("p_b", "qwen", "Abelard")],
            occurred_at=OCCURRED_AT,
        )
        for _ in range(120)
    ]
    high_stakes = run_consultation(
        build_consultation_plan(_dispute(region_class="headword", attestations=atts)),
        [_provider("p_a", "claude", "Abelard"), _provider("p_b", "qwen", "Abelard")],
        occurred_at=OCCURRED_AT,
    )

    batches = build_ratification_batches(ordinary + [high_stakes], batch_size=50)
    for batch in batches:
        assert len(batch.records) <= 50
        outcomes = {r.admission_outcome for r in batch.records}
        assert not (
            "admit_for_evidence_only" in outcomes and "admit_for_resolution" in outcomes
        )
    # Every input record lands in exactly one batch (none dropped).
    assert sum(len(b.records) for b in batches) == 121


# ---------------------------------------------------------------------------
# Mock seam -- no live call leaks through the provider seam
# ---------------------------------------------------------------------------

def test_mock_seam_only_injected_providers_are_called():
    """run_consultation dispatches only to the injected providers (no hidden live call)."""
    p_a = _provider("p_a", "claude", "Abelard")
    p_b = _provider("p_b", "qwen", "Abelard")
    run_consultation(build_consultation_plan(_dispute()), [p_a, p_b], occurred_at=OCCURRED_AT)
    assert p_a.called is True
    assert p_b.called is True
