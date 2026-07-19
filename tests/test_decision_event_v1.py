"""B3 TDD contract — decision-event-v1 schema + reconciled event_type enum.

Failing-first tests for the arch3 implementation pass (batch B3). They cover the
prompt's three named gates plus the maintainer-signed reconciliation:

  * enum conformance      -> the reconciled 13-value event_type set
  * replay rejects unknown -> an unrecognized event_type is a hard validation error
  * clear action existing  -> the promotion-gate clear is an existing event, never
                              a newly minted `reviewer_inconsistency_resolved`
  * axis lock (T18 sibling) -> the 4 workflow events MUST carry
                               event_category=workflow_event; the 9 authority kinds
                               MUST carry authority_decision; typography_tier_correction
                               is matrix-ineligible

Enum *values* are asserted against the design contract (the locked set). Generated
constant *names* are read from the regenerated module, never asserted from memory
beyond the deterministic generator naming (TEST-12). The event-vocab consumer tie
to batch B0 is import-skipped so this file runs before or after B0 lands.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib import _generated_enums  # noqa: E402
from ocd_kernel.lib.schema_enums import get_enum, resolve_schema_path  # noqa: E402

SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
SCHEMA_NAME = "decision-event-v1"

# The reconciled, maintainer-signed event_type set (2026-05-29): arch1's nine
# authority kinds (unchanged, closed) + arch3's three workflow events + arch8's
# typography_tier_correction folded onto the extensible workflow axis. The three
# arch4/5 names (rebind_or_reclassify_decision / page_repair / vote_excluded_reversed)
# map onto existing authority events via payload, NOT new enum slots.
AUTHORITY_KINDS = frozenset({
    "choose_attestation", "amend_text", "confirm_unresolved", "resolve_structure",
    "reject_machine_flag", "rebind_target", "supersede_decision", "mark_gold",
    "withdraw_gold", "machine_release",
})
WORKFLOW_KINDS = frozenset({
    "orphan_decision", "auto_rebind_system", "reviewer_recheck_requested",
    "typography_tier_correction",
})
EXPECTED_EVENT_TYPES = AUTHORITY_KINDS | WORKFLOW_KINDS  # 14 values

_HEX64 = "0" * 64


def _schema() -> dict:
    return json.loads(resolve_schema_path(SCHEMA_NAME).read_text(encoding="utf-8"))


def _accepts(instance: dict) -> None:
    jsonschema.validate(instance=instance, schema=_schema())


def _rejects(instance: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=_schema())


def _base_authority(event_type: str = "choose_attestation") -> dict:
    """A full, valid authority-decision envelope; per-kind fields added by caller."""
    return {
        "schema_version": "decision-event-v1",
        "event_id": f"de-sha256:{_HEX64}",
        "event_type": event_type,
        "event_category": "authority_decision",
        "volume": 1,
        "canonical_token_id": f"ct-sha256:{_HEX64}",
        "structural_path_at_decision": "vol_01/article_aaron/block_0/token_3",
        "minted_anchor_set_at_decision": [f"ot-sha256:{_HEX64}"],
        "fallback_fingerprint_at_decision": f"sha256:{_HEX64}",
        "match_method_used": None,
        "previous_status_at_view": "unresolved",
        "new_status": "reviewed",
        "evidence_seen": {},
        "measurement_eligible": True,
        "actor_id": "maintainer",
        "timestamp": "2026-05-29T00:00:00Z",
        "ui_mode": "word",
        "ui_version": "mvu-0",
        "decision_extras_carried": {},
        # choose_attestation per-kind fields:
        "selected_observation_token_id": f"ot-sha256:{_HEX64}",
        "decision_token": "ratification",
    }


def _base_workflow(event_type: str) -> dict:
    return {
        "schema_version": "decision-event-v1",
        "event_id": f"de-sha256:{_HEX64}",
        "event_type": event_type,
        "event_category": "workflow_event",
        "volume": 1,
        "actor_id": "system:auto_rebind",
        "timestamp": "2026-05-29T00:00:00Z",
        "measurement_eligible": False,
    }


# --------------------------------------------------------------------------- #
# Enum conformance
# --------------------------------------------------------------------------- #


def test_event_type_enum_is_the_reconciled_14() -> None:
    assert get_enum(SCHEMA_NAME, "event_type") == EXPECTED_EVENT_TYPES
    assert len(EXPECTED_EVENT_TYPES) == 14


def test_event_category_enum() -> None:
    assert get_enum(SCHEMA_NAME, "event_category") == frozenset(
        {"authority_decision", "workflow_event"}
    )


def test_generated_constant_present_and_agrees() -> None:
    # Deterministic generator naming: schema name + property path, upper-cased.
    constant = _generated_enums.DECISION_EVENT_V1__EVENT_TYPE
    assert constant == get_enum(SCHEMA_NAME, "event_type")


def test_machine_release_branch_matches_adr_0021() -> None:
    event = _base_authority("machine_release")
    del event["selected_observation_token_id"]
    del event["decision_token"]
    event["event_id"] = (
        "jewish-encyclopedia.vol_02:vol_02:page_0010:"
        "vol_02:page_0010:body:c1:l000:p000:schaff-matrix-policy-degraded-v1"
    )
    event["actor_id"] = "system:corrector"
    event["measurement_eligible"] = False
    event["new_status"] = "consensus"
    event["status_authority"] = "consensus"
    event["evidence_seen"] = {
        "wct_page_sha256": "cc7dfc066531135243667f5032621f9efba0ce7d2d8419a2080e1cc49ca54cca",
        "chosen_candidate_text": "on",
        "thresholds_file_id": "prompts/je-measurement-thresholds.json",
    }
    event["decision_extras_carried"] = {
        "origin_kind": "observed",
        "derivation_method": "L0",
        "chosen_action": "release_accepted",
        "chosen_reading_index": 0,
    }
    _accepts(event)

    missing_payload = dict(event)
    del missing_payload["decision_extras_carried"]
    _rejects(missing_payload)

    measured_machine_release = dict(event)
    measured_machine_release["measurement_eligible"] = True
    _rejects(measured_machine_release)


# --------------------------------------------------------------------------- #
# Clear action is an existing event, not a newly minted one (lock S6 item 25)
# --------------------------------------------------------------------------- #


def test_promotion_gate_clear_action_is_an_existing_event() -> None:
    types = get_enum(SCHEMA_NAME, "event_type")
    # The withdrawn Claude proposal must not exist as an event type.
    assert "reviewer_inconsistency_resolved" not in types
    # The reconciled clear path reuses existing authority events.
    assert "choose_attestation" in types
    assert "supersede_decision" in types


def test_arch4_names_are_not_enum_values_but_are_mapped() -> None:
    types = get_enum(SCHEMA_NAME, "event_type")
    for arch4_name in ("rebind_or_reclassify_decision", "page_repair", "vote_excluded_reversed"):
        assert arch4_name not in types
    mapping = _schema().get("x-ocd-event-type-mapping")
    assert isinstance(mapping, dict)
    for arch4_name in (
        "rebind_or_reclassify_decision", "page_repair",
        "vote_excluded_reversed", "reviewer_inconsistency_resolved",
    ):
        assert arch4_name in mapping, f"{arch4_name} missing from mapping table"


# --------------------------------------------------------------------------- #
# Replay rejects an unknown event_type
# --------------------------------------------------------------------------- #


def test_unknown_event_type_rejected() -> None:
    bad = _base_authority()
    bad["event_type"] = "reviewer_inconsistency_resolved"
    _rejects(bad)
    bad2 = _base_authority()
    bad2["event_type"] = "page_repair"  # arch4 ledger name, not a decision-event type
    _rejects(bad2)


# --------------------------------------------------------------------------- #
# Axis lock (the T18 invariant, full-instance form)
# --------------------------------------------------------------------------- #


def test_valid_choose_attestation_validates() -> None:
    _accepts(_base_authority())


def test_typography_tier_correction_is_workflow_not_authority() -> None:
    ok = _base_workflow("typography_tier_correction")
    ok["prior_tier"] = "footnote"
    ok["new_tier"] = "body"
    _accepts(ok)

    # Same event on the authority axis must fail (axis lock).
    bad = dict(ok)
    bad["event_category"] = "authority_decision"
    _rejects(bad)


def test_typography_tier_correction_is_matrix_ineligible() -> None:
    bad = _base_workflow("typography_tier_correction")
    bad["prior_tier"] = "footnote"
    bad["new_tier"] = "body"
    bad["measurement_eligible"] = True  # matrix-ineligible by lock §7
    _rejects(bad)


def test_authority_kind_on_workflow_axis_rejected() -> None:
    bad = _base_authority("choose_attestation")
    bad["event_category"] = "workflow_event"
    _rejects(bad)


def test_workflow_kind_on_authority_axis_rejected() -> None:
    bad = _base_workflow("orphan_decision")
    bad["event_category"] = "authority_decision"
    _rejects(bad)


# --------------------------------------------------------------------------- #
# Per-kind required fields
# --------------------------------------------------------------------------- #


def test_choose_attestation_requires_selection() -> None:
    bad = _base_authority("choose_attestation")
    del bad["selected_observation_token_id"]
    _rejects(bad)


def test_supersede_decision_requires_target() -> None:
    ev = _base_authority("supersede_decision")
    del ev["selected_observation_token_id"]
    del ev["decision_token"]
    ev["supersedes_event_id"] = f"de-sha256:{_HEX64}"
    ev["reason"] = "reviewer reaffirmed prior reading"
    _accepts(ev)
    del ev["supersedes_event_id"]
    _rejects(ev)


def test_orphan_decision_requires_candidates() -> None:
    ev = _base_workflow("orphan_decision")
    ev["orphaned_event_id"] = f"de-sha256:{_HEX64}"
    ev["orphan_reason"] = "no_anchor_match"
    ev["candidate_canonical_token_ids"] = []
    _accepts(ev)
    del ev["orphan_reason"]
    _rejects(ev)


def test_schema_is_valid_metaschema() -> None:
    Draft202012Validator.check_schema(_schema())


# --------------------------------------------------------------------------- #
# Tie to batch B0 — the event-vocab consumer fails closed on unknown types.
# Skips cleanly if B0 has not landed yet.
# --------------------------------------------------------------------------- #


def test_b0_event_vocab_consumer_rejects_unknown() -> None:
    event_vocab = pytest.importorskip("build.lib.event_vocab")
    allowed = get_enum(SCHEMA_NAME, "event_type")
    event_vocab.assert_known_event_type("choose_attestation", allowed)
    with pytest.raises(event_vocab.UnknownEventTypeError):
        event_vocab.assert_known_event_type("reviewer_inconsistency_resolved", allowed)
