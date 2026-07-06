"""CCEL gold channel -- mark/withdraw_gold builders + monthly quality report.

B16 deliverable #3. The CCEL-sourced gold pass (arch7 s7.2) prefills reviewer
gold on vols 1/2/9 from CCEL biblical text; the reviewer can confirm, supersede,
or route, so bad CCEL labels are counted, not hidden. Each gold action rides
arch3's locked ``mark_gold`` / ``withdraw_gold`` authority events through the
hash-chained ``DecisionStore`` -- replay determinism is inherited, this module
adds no new event type and no new schema (the CCEL channel + region are carried
on ``decision_extras_carried``, a free object in decision-event-v1).

The monthly ``ccel_gold_quality_report`` (arch7 s11) measures the reviewer
supersession rate per volume, per region, and cross-volume, and classifies it
into the <2% / 2-5% / >=5% downgrade bands. A channel downgrade is a store-admin
record + report flag (arch7 s4.1 / 18-D9), never a new authority event, and is
non-retroactive: it stops future CCEL ``mark_gold`` but leaves prior labels in
place and only triggers a matrix-replay-impact estimate.

The band thresholds and the recommended cross-volume downgrade point are arch9-
ratified phase-2 values (arch7 s11.4 / s17); they live here as constants so the
machinery is exercisable now and the verdict is a config change later.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


# --- CCEL channel identity ---
CCEL_SOURCE_CHANNEL = "ccel"
# Vols 1/2/9 carry the CCEL gold pass (arch7 s7.2). Other volumes have no CCEL
# prefill; this tuple documents the scope, it does not gate the builders.
CCEL_GOLD_VOLUMES: tuple[int, ...] = (1, 2, 9)

# --- Downgrade bands (arch7 s11.4; arch4 s19; arch9 ratifies the final values) ---
BAND_HEALTHY = "healthy"
BAND_WATCH = "per_region_watch"
BAND_DOWNGRADE = "downgrade"

# <2% healthy; 2-5% per-region watch; >=5% whole-channel downgrade candidate.
BAND_WATCH_MIN = 0.02
BAND_DOWNGRADE_MIN = 0.05
# Recommended cross-volume downgrade threshold (arch7 s11.4 recommends 2%);
# the final value is an arch9 / maintainer phase-2 decision.
RECOMMENDED_DOWNGRADE_THRESHOLD = 0.02

_STATUS_REVIEWED = "reviewed"
_STATUS_UNRESOLVED = "unresolved"


def classify_downgrade_band(rate: float) -> str:
    """Map a supersession rate to its arch7 downgrade band.

    Boundaries are inclusive at the lower edge: exactly 2% enters the watch
    band, exactly 5% enters the downgrade band (the bands are read as
    [0,2%) / [2%,5%) / [5%,100%]).
    """
    if rate < BAND_WATCH_MIN:
        return BAND_HEALTHY
    if rate < BAND_DOWNGRADE_MIN:
        return BAND_WATCH
    return BAND_DOWNGRADE


def _authority_envelope(
    *,
    event_type: str,
    volume: int,
    actor_id: str,
    timestamp: str,
    structural_path: str,
    previous_status: str,
    new_status: str,
) -> dict[str, Any]:
    """Shared required fields for an authority_decision decision-event-v1 body.

    Returns the pre-envelope content dict (no event_id / hash -- those are set
    by DecisionStore.append). mark_gold/withdraw_gold/supersede_decision are NOT
    matrix-training actions, so measurement_eligible is False.
    """
    return {
        "schema_version": "decision-event-v1",
        "event_type": event_type,
        "event_category": "authority_decision",
        "volume": volume,
        "actor_id": actor_id,
        "timestamp": timestamp,
        "measurement_eligible": False,
        "structural_path_at_decision": structural_path,
        "previous_status_at_view": previous_status,
        "new_status": new_status,
    }


def build_ccel_mark_gold(
    *,
    volume: int,
    gold_sample_ref: str,
    actor_id: str,
    timestamp: str,
    structural_path: str,
    region_class: str,
    source_basis: str,
    previous_status: str = _STATUS_UNRESOLVED,
    new_status: str = _STATUS_REVIEWED,
) -> dict[str, Any]:
    """Build a CCEL-sourced ``mark_gold`` decision-event body.

    ``source_basis`` records the CCEL provenance (e.g. ``ccel:bible-bsb:John.1.1``)
    so the gold record's origin is auditable; ``region_class`` and the CCEL
    channel marker ride ``decision_extras_carried`` for the quality report.
    """
    event = _authority_envelope(
        event_type="mark_gold",
        volume=volume,
        actor_id=actor_id,
        timestamp=timestamp,
        structural_path=structural_path,
        previous_status=previous_status,
        new_status=new_status,
    )
    event["gold_sample_ref"] = gold_sample_ref
    event["decision_extras_carried"] = {
        "source_channel": CCEL_SOURCE_CHANNEL,
        "region_class": region_class,
        "source_basis": source_basis,
    }
    return event


def build_ccel_withdraw_gold(
    *,
    volume: int,
    gold_sample_ref: str,
    actor_id: str,
    timestamp: str,
    withdrawal_reason: str,
    structural_path: str,
    region_class: str,
    previous_status: str = _STATUS_REVIEWED,
    new_status: str = _STATUS_REVIEWED,
) -> dict[str, Any]:
    """Build a ``withdraw_gold`` event retiring one bad CCEL gold label.

    This is the per-label withdrawal (arch3 ``withdraw_gold``), distinct from a
    whole-channel downgrade (see ``apply_ccel_downgrade``). new_status stays
    ``reviewed``: the reviewer has now seen the token; the gold flag is what is
    withdrawn.
    """
    event = _authority_envelope(
        event_type="withdraw_gold",
        volume=volume,
        actor_id=actor_id,
        timestamp=timestamp,
        structural_path=structural_path,
        previous_status=previous_status,
        new_status=new_status,
    )
    event["gold_sample_ref"] = gold_sample_ref
    event["withdrawal_reason"] = withdrawal_reason
    event["decision_extras_carried"] = {
        "source_channel": CCEL_SOURCE_CHANNEL,
        "region_class": region_class,
    }
    return event


def build_ccel_supersession(
    *,
    volume: int,
    supersedes_event_id: str,
    actor_id: str,
    timestamp: str,
    reason: str,
    structural_path: str,
    previous_status: str = _STATUS_REVIEWED,
    new_status: str = _STATUS_REVIEWED,
) -> dict[str, Any]:
    """Build a ``supersede_decision`` correcting a CCEL gold label.

    The reviewer noticed the CCEL prefill disagreed with the scan during the
    gold pass. ``supersedes_event_id`` points at the superseded ``mark_gold``
    event_id; the quality report folds these to measure the supersession rate.
    """
    event = _authority_envelope(
        event_type="supersede_decision",
        volume=volume,
        actor_id=actor_id,
        timestamp=timestamp,
        structural_path=structural_path,
        previous_status=previous_status,
        new_status=new_status,
    )
    event["supersedes_event_id"] = supersedes_event_id
    event["reason"] = reason
    return event


def _is_ccel_mark_gold(event: Mapping[str, Any]) -> bool:
    if event.get("event_type") != "mark_gold":
        return False
    extras = event.get("decision_extras_carried")
    return isinstance(extras, Mapping) and extras.get("source_channel") == CCEL_SOURCE_CHANNEL


def _rate(superseded: int, total: int) -> float:
    return superseded / total if total else 0.0


def ccel_gold_quality_report(
    events: Sequence[Mapping[str, Any]],
    *,
    report_month: str,
    prior_cross_volume_rate: float | None = None,
) -> dict[str, Any]:
    """Compute the monthly CCEL gold quality report from a folded event list.

    A CCEL gold label counts as *superseded* when a later ``supersede_decision``
    references its event_id. Rates are reported per volume, per region, and
    cross-volume; the cross-volume rate selects the downgrade band. ``trend`` is
    derived against ``prior_cross_volume_rate`` when supplied.
    """
    ccel_marks = [e for e in events if _is_ccel_mark_gold(e)]
    superseded_ids = {
        e.get("supersedes_event_id")
        for e in events
        if e.get("event_type") == "supersede_decision"
    }

    per_volume: dict[int, dict[str, Any]] = {}
    per_region: dict[str, dict[str, Any]] = {}
    total = 0
    total_superseded = 0

    for mark in ccel_marks:
        volume = mark["volume"]
        region = mark.get("decision_extras_carried", {}).get("region_class", "unknown")
        is_superseded = mark.get("event_id") in superseded_ids

        total += 1
        total_superseded += int(is_superseded)

        vol_bucket = per_volume.setdefault(volume, {"ccel_gold_count": 0, "superseded_count": 0})
        vol_bucket["ccel_gold_count"] += 1
        vol_bucket["superseded_count"] += int(is_superseded)

        region_bucket = per_region.setdefault(region, {"ccel_gold_count": 0, "superseded_count": 0})
        region_bucket["ccel_gold_count"] += 1
        region_bucket["superseded_count"] += int(is_superseded)

    for bucket in per_volume.values():
        bucket["supersession_rate"] = _rate(bucket["superseded_count"], bucket["ccel_gold_count"])
    for bucket in per_region.values():
        bucket["supersession_rate"] = _rate(bucket["superseded_count"], bucket["ccel_gold_count"])

    cross_rate = _rate(total_superseded, total)
    band = classify_downgrade_band(cross_rate)

    if prior_cross_volume_rate is None:
        trend = "insufficient_history"
    elif cross_rate > prior_cross_volume_rate:
        trend = "rising"
    elif cross_rate < prior_cross_volume_rate:
        trend = "falling"
    else:
        trend = "flat"

    # Regions in the watch band are surfaced so a per-region downgrade can be
    # considered before a whole-channel one (arch7 s11.4 / s15.5).
    watch_regions = sorted(
        region
        for region, bucket in per_region.items()
        if bucket["supersession_rate"] >= BAND_WATCH_MIN
    )

    if band == BAND_DOWNGRADE:
        recommended_action = "downgrade_channel"
    elif band == BAND_WATCH:
        recommended_action = "watch_per_region"
    else:
        recommended_action = "none"

    return {
        "report_kind": "ccel_gold_quality_report",
        "report_month": report_month,
        "per_volume": per_volume,
        "per_region": per_region,
        "cross_volume": {
            "ccel_gold_count": total,
            "superseded_count": total_superseded,
            "supersession_rate": cross_rate,
            "band": band,
            "trend": trend,
        },
        "recommended_downgrade_threshold": RECOMMENDED_DOWNGRADE_THRESHOLD,
        "exceeds_recommended_threshold": cross_rate >= RECOMMENDED_DOWNGRADE_THRESHOLD,
        "watch_regions": watch_regions,
        "recommended_action": recommended_action,
    }


def apply_ccel_downgrade(
    *,
    actor_id: str,
    timestamp: str,
    cross_volume_rate: float,
    report_month: str,
) -> dict[str, Any]:
    """Record a whole-channel CCEL downgrade.

    Returns a store-admin record (NOT a decision-event -- arch7 s4.1 / 18-D9
    forbids a new ``ccel_downgrade`` authority type). The downgrade is
    non-retroactive: prior CCEL gold labels stay, future ``mark_gold`` on the
    channel stops, and a matrix-replay-impact estimate is required.
    """
    return {
        "kind": "ccel_channel_downgrade",
        "channel": CCEL_SOURCE_CHANNEL,
        "actor_id": actor_id,
        "timestamp": timestamp,
        "report_month": report_month,
        "triggered_by_cross_volume_rate": cross_volume_rate,
        "threshold": RECOMMENDED_DOWNGRADE_THRESHOLD,
        "non_retroactive": True,
        "prior_labels_retained": True,
        "stops_future_mark_gold": True,
        "matrix_replay_impact_estimate_required": True,
    }
