"""B16 deliverable #3 -- CCEL gold channel (TEST-16: mark/withdraw_gold replay
+ correct downgrade band).

Contract: ``plans/2026-05-28-arch7-reviewer-synthesis.md`` sections 7.2 (CCEL gold
prefilled-not-read-only on vols 1/2/9), 11 (monthly ``ccel_gold_quality_report``;
per-volume / per-region / cross-volume supersession rate; downgrade bands
<2% / 2-5% / >=5%), and 4.1 / 18-D9 (CCEL downgrade is ``withdraw_gold`` +
store-admin record, NOT a new authority event; non-retroactive). The decision
events ride arch3's locked ``mark_gold`` / ``withdraw_gold`` authority kinds
through the hash-chained ``DecisionStore``, so replay determinism is inherited.

The downgrade *verdict* on real CCEL text is phase 2; this suite proves the
channel + report machinery on synthetic fixtures. Band thresholds are arch9-
ratified phase-2 values surfaced as module constants.
"""

from __future__ import annotations

import json

import pytest

from build.lib import ccel_gold
from build.lib.decision_store import DecisionStore, _canonical_bytes


# ---------------------------------------------------------------------------
# mark_gold / withdraw_gold replay byte-identically through the store
# ---------------------------------------------------------------------------

def _canonical_line(event: dict) -> bytes:
    return json.dumps(event, separators=(",", ":"), ensure_ascii=False, sort_keys=True).encode("utf-8")


def test_ccel_mark_gold_and_withdraw_replay_byte_identically(tmp_path):
    store = DecisionStore(base_dir=tmp_path, volume=1)
    mark = ccel_gold.build_ccel_mark_gold(
        volume=1,
        gold_sample_ref="ccel-gold-vol01-0005",
        actor_id="maintainer",
        timestamp="2026-05-31T00:00:00Z",
        structural_path="vol_01/page_0005/block_2",
        region_class="body",
        source_basis="ccel:bible-bsb:John.1.1",
    )
    store.append(mark)
    withdraw = ccel_gold.build_ccel_withdraw_gold(
        volume=1,
        gold_sample_ref="ccel-gold-vol01-0005",
        actor_id="maintainer",
        timestamp="2026-05-31T01:00:00Z",
        withdrawal_reason="ccel_label_superseded_by_reviewer",
        structural_path="vol_01/page_0005/block_2",
        region_class="body",
    )
    store.append(withdraw)

    # fold() re-verifies the hash chain; reaching here proves no corruption.
    folded = store.fold()
    assert [e["event_type"] for e in folded] == ["mark_gold", "withdraw_gold"]

    # Byte-identical replay: re-serialising each folded event reproduces the
    # exact stored line (the store writes sort_keys canonical JSON).
    raw_lines = [ln for ln in store.store_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for event, raw in zip(folded, raw_lines):
        assert _canonical_line(event) == raw.encode("utf-8")


def test_ccel_mark_gold_is_not_measurement_eligible():
    # mark_gold is NOT a ratification/training action (arch7 s7.2 / arch6 s10.5).
    mark = ccel_gold.build_ccel_mark_gold(
        volume=2,
        gold_sample_ref="ccel-gold-vol02-0010",
        actor_id="maintainer",
        timestamp="2026-05-31T00:00:00Z",
        structural_path="vol_02/page_0010/block_1",
        region_class="body",
        source_basis="ccel:bible-bsb:Rom.1.1",
    )
    assert mark["measurement_eligible"] is False
    assert mark["decision_extras_carried"]["source_channel"] == ccel_gold.CCEL_SOURCE_CHANNEL


# ---------------------------------------------------------------------------
# Downgrade band classification (<2% / 2-5% / >=5%)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "rate,expected",
    [
        (0.0, ccel_gold.BAND_HEALTHY),
        (0.0199, ccel_gold.BAND_HEALTHY),
        (0.02, ccel_gold.BAND_WATCH),       # boundary: 2% enters the watch band
        (0.035, ccel_gold.BAND_WATCH),
        (0.0499, ccel_gold.BAND_WATCH),
        (0.05, ccel_gold.BAND_DOWNGRADE),   # boundary: 5% enters downgrade
        (0.12, ccel_gold.BAND_DOWNGRADE),
    ],
)
def test_classify_downgrade_band_boundaries(rate, expected):
    assert ccel_gold.classify_downgrade_band(rate) == expected


# ---------------------------------------------------------------------------
# Monthly quality report: per-volume + cross-volume rate + correct band
# ---------------------------------------------------------------------------

def _ccel_mark(volume, ref, region, store):
    event = ccel_gold.build_ccel_mark_gold(
        volume=volume,
        gold_sample_ref=ref,
        actor_id="maintainer",
        timestamp="2026-05-31T00:00:00Z",
        structural_path=f"vol_{volume:02d}/{ref}",
        region_class=region,
        source_basis=f"ccel:bible-bsb:{ref}",
    )
    store.append(event)
    return store.fold()[-1]["event_id"]


def _supersede(volume, target_event_id, store):
    event = ccel_gold.build_ccel_supersession(
        volume=volume,
        supersedes_event_id=target_event_id,
        actor_id="maintainer",
        timestamp="2026-05-31T02:00:00Z",
        reason="ccel label disagreed with scan",
        structural_path=f"vol_{volume:02d}/supersede",
    )
    store.append(event)


def test_quality_report_computes_per_volume_and_cross_volume_rate(tmp_path):
    store = DecisionStore(base_dir=tmp_path, volume=1)
    # Vol 1: 5 CCEL gold labels, 1 superseded -> 20%.
    ids_v1 = [_ccel_mark(1, f"ccel-v1-{i}", "body", store) for i in range(5)]
    _supersede(1, ids_v1[0], store)
    events = store.fold()

    report = ccel_gold.ccel_gold_quality_report(events, report_month="2026-05")
    vol1 = report["per_volume"][1]
    assert vol1["ccel_gold_count"] == 5
    assert vol1["superseded_count"] == 1
    assert vol1["supersession_rate"] == pytest.approx(0.2)
    assert report["cross_volume"]["supersession_rate"] == pytest.approx(0.2)
    assert report["cross_volume"]["band"] == ccel_gold.BAND_DOWNGRADE


@pytest.mark.slow
def test_quality_report_healthy_band_below_threshold(tmp_path):
    store = DecisionStore(base_dir=tmp_path, volume=1)
    # 100 CCEL gold labels, 1 superseded -> 1% -> healthy.
    ids = [_ccel_mark(1, f"ccel-v1-{i}", "body", store) for i in range(100)]
    _supersede(1, ids[0], store)
    events = store.fold()
    report = ccel_gold.ccel_gold_quality_report(events, report_month="2026-05")
    assert report["cross_volume"]["supersession_rate"] == pytest.approx(0.01)
    assert report["cross_volume"]["band"] == ccel_gold.BAND_HEALTHY
    assert report["recommended_action"] == "none"


@pytest.mark.slow
def test_quality_report_per_region_rate(tmp_path):
    store = DecisionStore(base_dir=tmp_path, volume=1)
    body_ids = [_ccel_mark(1, f"body-{i}", "body", store) for i in range(10)]
    foot_ids = [_ccel_mark(1, f"foot-{i}", "footnote", store) for i in range(10)]
    # Footnotes much worse than body: 4/10 vs 0/10.
    for i in range(4):
        _supersede(1, foot_ids[i], store)
    events = store.fold()
    report = ccel_gold.ccel_gold_quality_report(events, report_month="2026-05")
    per_region = report["per_region"]
    assert per_region["footnote"]["supersession_rate"] == pytest.approx(0.4)
    assert per_region["body"]["supersession_rate"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Channel downgrade is non-retroactive
# ---------------------------------------------------------------------------

def test_apply_ccel_downgrade_is_non_retroactive():
    admin = ccel_gold.apply_ccel_downgrade(
        actor_id="maintainer",
        timestamp="2026-05-31T03:00:00Z",
        cross_volume_rate=0.07,
        report_month="2026-05",
    )
    assert admin["kind"] == "ccel_channel_downgrade"
    # Non-retroactive: prior labels stay; only future mark_gold stops.
    assert admin["non_retroactive"] is True
    assert admin["prior_labels_retained"] is True
    assert admin["stops_future_mark_gold"] is True
    # It triggers a matrix-replay-impact estimate (arch7 s11.4) and is NOT an event.
    assert admin["matrix_replay_impact_estimate_required"] is True
    assert "event_type" not in admin
