"""B10 -- S3 degraded reconciler (arch5 / lock section 2).

Consumes one word-confusion-table-v1 page (B6 / S2.5 output) plus a work-meta
envelope and produces, in degraded mode:

  * a reconciled_record conforming to schemas/v1/reconciled_record.schema.json,
    with the region_class policy id ("v1") stamped on every block;
  * matrix-event candidates conforming to schemas/v1/matrix-events-v1.schema.json;
  * a reviewer queue of routed positions.

"Degraded mode" = no promoted matrix snapshot and no family-map readiness. Per the
lock (archC section 3, amending arch5 section 9.2 -- the named stale spot), class-1
training is blocked until family independence is measured on the vol_01 bake-off.
So in degraded mode NOTHING is measurement-eligible: every consensus is
`consensus_unconfirmed` with `external_check_absent: true` and routes to the reviewer
queue. Dictionary and edition checks are POST-ALIGNMENT signals applied after matrix
evidence -- never matrix training labels (lock section 2 layer boundary).

This is the un-tuned reconciler; S3 scoring-threshold tuning is gated by the B8
diagnostics verdict (phase 2). Placement note: this lives alongside the other new
Schaff-Herzog pipeline tooling (B6 wct_builder, B8 diagnostics, B9 family_map), NOT
inside build/lib/reconcile/ -- that package is the separate published-dataset
reconciler (catalog + parses, work-editions, pd_anchor), a different track.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from build.lib._generated_enums import (
    MATRIX_EVENTS_V1__DEFS__OUTCOME,
    MATRIX_EVENTS_V1__DEFS__REGION_CLASS,
)

# Versioned region-class assignment policy id (lock section 6 item 23:
# `schaff-region-class-policy-id: v1`). Stamped with every block so the policy that
# produced each region_class travels with the data.
REGION_CLASS_POLICY_ID = "v1"

# Matrix-policy version carried on every matrix-event candidate. Degraded build: the
# reconciler is un-tuned and pre-family-map-readiness, so the policy version names that.
DEFAULT_MATRIX_POLICY_VERSION = "schaff-matrix-policy-degraded-v1"

_GENESIS_HASH = "0" * 64  # page-local proposals are unchained; the S4 sink owns chaining.

# zone_type (WCT layout label) -> region_class base, BEFORE script/block-type overrides.
# zone_type and region_class are distinct vocabularies (lock section 6, finding D2):
# bibliography (zone) -> bibliography_entry (region_class). Layout labels with no clean
# region_class home resolve to "unknown" -> region_class_pending, NEVER a silent body
# fallback (lock section 6 item 23).
_ZONE_TYPE_TO_REGION_CLASS = {
    "body": "body",
    "footnote": "footnote",
    "bibliography": "bibliography_entry",
    "figure": "caption",
    "running-header": "unknown",
    "page-number": "unknown",
    "marginalia": "unknown",
}

# zone_type -> reconciled_record block_type (RECONCILED_RECORD__DEFS__BLOCK__BLOCK_TYPE).
_ZONE_TYPE_TO_BLOCK_TYPE = {
    "body": "paragraph",
    "footnote": "footnote",
    "bibliography": "paragraph",
    "figure": "paragraph",
    "running-header": "heading",
    "page-number": "paragraph",
    "marginalia": "paragraph",
}

# Routing reason -> matrix-event candidate outcome. The invariant the lock protects:
# degraded-mode candidates are NEVER `labels_emitted`. A consensus that a dictionary
# corroborates is still ineligible -- a dictionary pass is not an independent check.
_REASON_TO_OUTCOME = {
    "consensus_unconfirmed": "not_measurement_eligible",
    "dispute": "not_measurement_eligible",
    "region_class_pending": "queued_region_class_pending",
}


class RegionClassStampError(ValueError):
    """A reconciled_record block is missing its region_class policy-id stamp."""


@dataclass(frozen=True)
class RegionClassAssignment:
    """Result of the v1 region_class assignment policy for one position."""

    region_class: str
    pending: bool


@dataclass
class ReconcileResult:
    """Everything the degraded reconciler emits for one WCT page."""

    reconciled_record: dict
    matrix_event_candidates: list[dict] = field(default_factory=list)
    reviewer_queue: list[dict] = field(default_factory=list)
    post_alignment_signals: list[dict] = field(default_factory=list)


def assign_region_class(
    zone_type: str,
    script_label: str,
    *,
    block_type_hint: str | None = None,
    latin_german_high_conf: bool = False,
) -> RegionClassAssignment:
    """Assign a region_class under the locked v1 policy (lock section 6 item 23).

    Precedence:
      1. Greek/Hebrew script override -- a structural rule applied immediately at
         medium confidence (the >=3-char gate lives in S2.5 script detection; by the
         time a position carries script_label greek/hebrew it has cleared it).
      2. Latin/German foreign override -- only at explicit high confidence; degraded
         default is no override (route uncertain cases to review, never auto-foreign).
      3. block-type hint (L9) -- e.g. a detected headword / section_heading.
      4. zone_type base mapping; an unmapped layout label -> unknown + pending.

    `unknown` is returned with pending=True and must route to the reviewer queue
    (region_class_pending); it is never silently coerced to body.
    """
    if script_label == "greek":
        return RegionClassAssignment("foreign_language_greek", False)
    if script_label == "hebrew":
        return RegionClassAssignment("foreign_language_hebrew", False)
    if latin_german_high_conf and script_label in ("latin", "german"):
        foreign = "foreign_language_german" if script_label == "german" else "foreign_language_latin"
        return RegionClassAssignment(foreign, False)
    if block_type_hint and block_type_hint in MATRIX_EVENTS_V1__DEFS__REGION_CLASS:
        return RegionClassAssignment(block_type_hint, block_type_hint == "unknown")
    region_class = _ZONE_TYPE_TO_REGION_CLASS.get(zone_type, "unknown")
    return RegionClassAssignment(region_class, region_class == "unknown")


def validate_region_class_stamp(record: dict) -> None:
    """Reject a reconciled_record whose blocks are not all region_class-stamped.

    Every block must carry annotations.region_class = {region_class, policy_id} with
    policy_id == the active policy version. The JSON schema cannot enforce this (the
    stamp lives in the free-form annotations object), so it is a code-level guard.
    """
    for index, block in enumerate(record.get("blocks", [])):
        stamp = block.get("annotations", {}).get("region_class")
        if not isinstance(stamp, dict):
            raise RegionClassStampError(
                f"block {index} ({block.get('block_id')!r}) has no region_class stamp"
            )
        if stamp.get("policy_id") != REGION_CLASS_POLICY_ID:
            raise RegionClassStampError(
                f"block {index} ({block.get('block_id')!r}) region_class stamp policy_id "
                f"{stamp.get('policy_id')!r} != {REGION_CLASS_POLICY_ID!r}"
            )
        if stamp.get("region_class") not in MATRIX_EVENTS_V1__DEFS__REGION_CLASS:
            raise RegionClassStampError(
                f"block {index} ({block.get('block_id')!r}) region_class "
                f"{stamp.get('region_class')!r} is not a valid region_class value"
            )


def _best_candidate(candidates: list[dict]) -> dict:
    """Pick the most-attested candidate (provisional reading); deterministic tie-break."""
    return max(
        candidates,
        key=lambda c: (
            len(set(c.get("attesting_families", []))),
            len(c.get("attesting_engines", [])),
            c["candidate_id"],
        ),
    )


def _page_number(page_id: str) -> int | None:
    digits = "".join(ch for ch in page_id if ch.isdigit())
    return int(digits) if digits else None


def _iter_ordered_positions(wct_page: dict) -> list[dict]:
    positions_by_id = {p["position_id"]: p for p in wct_page["positions"]}
    ordered_ids = [pid for pid in wct_page.get("reading_order", []) if pid in positions_by_id]
    for position in wct_page["positions"]:
        if position["position_id"] not in ordered_ids:
            ordered_ids.append(position["position_id"])
    return [positions_by_id[pid] for pid in ordered_ids]


def _assemble_position_blocks(ordered_positions: list[dict]) -> list[tuple[str, list[dict]]]:
    zone_order: list[str] = []
    zone_positions: dict[str, list[dict]] = {}
    for position in ordered_positions:
        zone_id = position["zone"]["zone_id"]
        if zone_id not in zone_positions:
            zone_positions[zone_id] = []
            zone_order.append(zone_id)
        zone_positions[zone_id].append(position)
    return [(zone_id, zone_positions[zone_id]) for zone_id in zone_order]


def _stamp_region_class(zone_type: str, script_label: str) -> dict:
    assignment = assign_region_class(zone_type, script_label)
    return {
        "region_class": assignment.region_class,
        "policy_id": REGION_CLASS_POLICY_ID,
        "pending": assignment.pending,
    }


def _choose_position_reading(candidates: list[dict], reading_source) -> dict:
    return reading_source(candidates)


def _zone_dominant_language(positions: list[dict], default_language: str) -> str:
    labels = [p["script"]["text_level"]["label"] for p in positions]
    if labels and labels.count("greek") > len(labels) / 2:
        return "grc"
    if labels and labels.count("hebrew") > len(labels) / 2:
        return "hbo"
    return default_language


def _build_reviewer_queue_item(
    *,
    position_id: str,
    reason: str,
    external_check_absent: bool,
    pos_region: RegionClassAssignment,
    candidates: list[dict],
    chosen_reading: str,
) -> dict:
    return {
        "position_id": position_id,
        "reason": reason,
        "external_check_absent": external_check_absent,
        "region_class": pos_region.region_class,
        "region_class_pending": pos_region.pending,
        "audit_priority": pos_region.pending,
        "candidates": [c["raw_reading"] for c in candidates],
        "chosen_reading": chosen_reading,
    }


def _make_matrix_candidate(
    *,
    volume_id: str,
    page_id: str,
    position_id: str,
    reason: str,
    entry_seq: int,
    occurred_at: str,
    matrix_policy_version: str,
) -> dict:
    outcome = _REASON_TO_OUTCOME[reason]
    return {
        "schema_version": "matrix-events-v1",
        "entry_seq": entry_seq,
        "prev_entry_hash": _GENESIS_HASH,
        "event_id": f"{volume_id}:{page_id}:{position_id}",
        "event_type": f"{reason}_observation",
        "occurred_at": occurred_at,
        "policy_version": matrix_policy_version,
        "outcome": outcome,
    }


def _finalize_reconcile_invariants(record: dict, matrix_candidates: list[dict]) -> None:
    validate_region_class_stamp(record)
    _assert_no_premature_matrix_labels(matrix_candidates)


def reconcile_degraded(
    wct_page: dict,
    work_meta: dict,
    *,
    occurred_at: str,
    dictionary_signals: dict[str, dict] | None = None,
    matrix_policy_version: str = DEFAULT_MATRIX_POLICY_VERSION,
) -> ReconcileResult:
    """Reconcile one WCT page in degraded mode.

    Args:
        wct_page: a word-confusion-table-v1 page.
        work_meta: the reconciled_record envelope inputs (id/title/author/.../pd_anchor).
        occurred_at: ISO-8601 timestamp stamped on matrix-event candidates (caller-supplied
            so the function is deterministic and import-safe -- DATE-01/PY-06).
        dictionary_signals: optional {position_id: {"reading", "status"}} post-alignment
            corroboration; recorded as a signal, never as a matrix label.
        matrix_policy_version: policy version stamped on every candidate.
    """
    dictionary_signals = dictionary_signals or {}
    ordered_positions = _iter_ordered_positions(wct_page)

    page_id = wct_page["page_id"]
    volume_id = wct_page["volume_id"]
    page_num = _page_number(page_id)
    default_language = work_meta.get("language", "en")

    reviewer_queue: list[dict] = []
    matrix_candidates: list[dict] = []
    post_alignment_signals: list[dict] = []
    match_explanations: list[dict] = []

    # Group positions into blocks by zone, preserving reading order.
    blocks: list[dict] = []

    seq = 0
    for zone_id, zone_pos in _assemble_position_blocks(ordered_positions):
        zone_type = zone_pos[0]["zone"]["zone_type"]
        block_attested: list[str] = []
        chosen_readings: list[str] = []
        disagreements: list[dict] = []

        for token_index, position in enumerate(zone_pos):
            pid = position["position_id"]
            candidates = position["candidate_set"]
            if not candidates:
                continue  # all engines skipped this slot -- no reading contributed.

            chosen = _choose_position_reading(candidates, _best_candidate)
            chosen_readings.append(chosen["raw_reading"])
            for engine in chosen.get("attesting_engines", []):
                if engine not in block_attested:
                    block_attested.append(engine)

            script_label = position["script"]["text_level"]["label"]
            pos_region = assign_region_class(zone_type, script_label)

            # Route the position. region_class unknown wins (it gates the phase-2 vote).
            if pos_region.pending:
                reason = "region_class_pending"
                external_check_absent = False
            elif len(candidates) >= 2:
                reason = "dispute"
                external_check_absent = False
            else:
                # Single agreed reading, but degraded mode never has family-map readiness:
                # the strict bar's conjunct (iii) fails -> consensus_unconfirmed.
                reason = "consensus_unconfirmed"
                external_check_absent = True

            me_id = f"me-{volume_id}-{page_id}-{pid}"
            signals = [
                {"name": "alignment_confidence", "raw_score": float(position["alignment_confidence"]),
                 "weight": 0.0, "contribution": 0.0},
            ]

            # Dictionary / edition corroboration is a POST-ALIGNMENT signal -- recorded
            # for the reviewer, never a matrix training label (lock section 3 amendment).
            dict_signal = dictionary_signals.get(pid)
            if dict_signal:
                post_alignment_signals.append({
                    "position_id": pid,
                    "kind": "dictionary_corroboration",
                    "reading": dict_signal.get("reading"),
                    "status": dict_signal.get("status"),
                    "is_matrix_label": False,
                })
                signals.append({
                    "name": "dictionary_corroboration", "raw_score": 1.0,
                    "weight": 0.0, "contribution": 0.0,
                })

            match_explanations.append({
                "match_explanation_id": me_id,
                "scope": "disagreement",
                "signals": signals,
                "total_score": 0.0,
                "decision": {
                    "kind": "reading_score",
                    "pd_only_gap": 0.0,
                    "winning_has_pd_support": False,
                    "classification": reason,
                    "advisory_score": 0.0,
                },
            })

            disagreement = {
                "span": {"start_token": token_index, "end_token": token_index + 1},
                "kind": reason,
                "chosen_reading": chosen["raw_reading"],
                "chosen_reading_attested_by": list(chosen.get("attesting_engines", [])),
                "external_check_absent": external_check_absent,
                "match_explanation_id": me_id,
            }
            disagreements.append(disagreement)

            reviewer_queue.append(_build_reviewer_queue_item(
                position_id=pid,
                reason=reason,
                external_check_absent=external_check_absent,
                pos_region=pos_region,
                candidates=candidates,
                chosen_reading=chosen["raw_reading"],
            ))

            matrix_candidates.append(_make_matrix_candidate(
                volume_id=volume_id,
                page_id=page_id,
                position_id=pid,
                reason=reason,
                entry_seq=seq,
                occurred_at=occurred_at,
                matrix_policy_version=matrix_policy_version,
            ))
            seq += 1

        block_id = f"blk-{volume_id}-{page_id}-{zone_id}"
        blocks.append({
            "block_id": block_id,
            "block_id_history": [],
            "block_type": _ZONE_TYPE_TO_BLOCK_TYPE.get(zone_type, "paragraph"),
            "language": _zone_dominant_language(zone_pos, default_language),
            "language_confidence": 1.0,
            "language_alternates": [],
            "language_segments": [],
            "original_text": " ".join(chosen_readings),
            "modern_text": "",
            "annotations": {
                "region_class": _stamp_region_class(zone_type, _zone_dominant_script(zone_pos)),
            },
            "source_pages": [
                {"rendering_id": engine, "page_number": page_num} for engine in block_attested
            ] or [{"rendering_id": work_meta.get("pd_anchor", volume_id), "page_number": page_num}],
            "attested_by": block_attested,
            "disagreements": disagreements,
            "structural_disagreements": [],
            "modernisations": [],
        })

    block_count = len(blocks)
    blocks_with_disagreements = sum(1 for b in blocks if b["disagreements"])
    record = {
        "meta": {
            "id": work_meta["id"],
            "title": work_meta["title"],
            "author_slug": work_meta["author_slug"],
            "author_display_name": work_meta["author_display_name"],
            "author_birth_year": work_meta.get("author_birth_year"),
            "author_death_year": work_meta.get("author_death_year"),
            "original_publication_year": work_meta.get("original_publication_year"),
            "language": default_language,
            "tradition": work_meta.get("tradition", ["ecumenical"]),
            "license": work_meta.get("license", "public-domain"),
            "schema_type": "reconciled_record",
            "schema_version": "3.0.0",
            "edition": work_meta.get("edition", ""),
            "pd_anchor": work_meta.get("pd_anchor", ""),
            "modernisation_ruleset_version": None,
            "attestation_summary": {
                "block_count": block_count,
                "fully_attested_blocks": block_count - blocks_with_disagreements,
                "blocks_with_disagreements": blocks_with_disagreements,
                "blocks_with_structural_disagreements": 0,
            },
        },
        "blocks": blocks,
        "match_explanations": match_explanations,
    }

    # Fail-closed on the load-bearing invariants before returning.
    _finalize_reconcile_invariants(record, matrix_candidates)

    return ReconcileResult(
        reconciled_record=record,
        matrix_event_candidates=matrix_candidates,
        reviewer_queue=reviewer_queue,
        post_alignment_signals=post_alignment_signals,
    )


def _zone_dominant_script(positions: list[dict]) -> str:
    """The script label shared by most positions in a zone (for the block-level region)."""
    labels = [p["script"]["text_level"]["label"] for p in positions]
    if labels and labels.count("greek") > len(labels) / 2:
        return "greek"
    if labels and labels.count("hebrew") > len(labels) / 2:
        return "hebrew"
    return "latin"


def _assert_no_premature_matrix_labels(candidates: list[dict]) -> None:
    """Degraded mode emits no trained labels; reject any `labels_emitted` candidate."""
    for candidate in candidates:
        outcome = candidate["outcome"]
        if outcome not in MATRIX_EVENTS_V1__DEFS__OUTCOME:
            raise ValueError(f"matrix-event candidate has unknown outcome {outcome!r}")
        if outcome == "labels_emitted":
            raise ValueError(
                "degraded reconciler emitted a labels_emitted matrix candidate -- "
                "no family-map readiness, nothing is measurement-eligible (lock section 3)"
            )
