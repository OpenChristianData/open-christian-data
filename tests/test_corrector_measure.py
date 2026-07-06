from __future__ import annotations

from build.lib.gold_free_corrector.decide import _ACCEPT


def _make_position(position_id: str = "pos-001", *, families: list[str] | None = None) -> dict:
    families = families or ["abbyy", "surya"]
    return {
        "position_id": position_id,
        "candidate_set": [
            {
                "candidate_id": f"{position_id}-c0",
                "raw_reading": "Abraham",
                "candidate_key": "Abraham",
                "attesting_families": families,
                "attesting_engines": [f"eng-{family}" for family in families],
            }
        ],
        "span_records": [],
        "zone": {"zone_id": "zone-body", "zone_type": "body"},
        "script": {"text_level": {"label": "latin"}},
        "alignment_confidence": 0.9,
    }


def _thresholds_accept() -> dict:
    return {
        "body": {
            "L0": {"auto_accept_enabled": True},
            "L1": {"auto_accept_enabled": False},
        }
    }


def _thresholds_accept_l0_l1() -> dict:
    return {
        "body": {
            "L0": {"auto_accept_enabled": True},
            "L1": {"auto_accept_enabled": True},
        }
    }


def _thresholds_reject() -> dict:
    return {
        "body": {
            "L0": {"auto_accept_enabled": False},
            "L1": {"auto_accept_enabled": False},
        }
    }


def _wct_page(*positions: dict, page_id: str = "page-001") -> dict:
    return {"page_id": page_id, "positions": list(positions)}


def test_zero_false_corrections_when_corrector_matches_gold() -> None:
    from build.tools.ocr_pipeline.measure_corrector import StratumKey, measure_page

    position = _make_position()

    stats = measure_page(
        _wct_page(position),
        {"pos-001": {"gold_text": "Abraham"}},
        _thresholds_accept(),
    )

    stratum = stats[StratumKey(level="L0", protected_class="none")]
    assert stratum.false_corrections == 0
    assert stratum.auto_accepted == 1


def test_false_correction_counted_when_accepted_reading_differs() -> None:
    from build.tools.ocr_pipeline.measure_corrector import StratumKey, measure_page

    position = _make_position()

    stats = measure_page(
        _wct_page(position),
        {"pos-001": {"gold_text": "WRONG_GOLD"}},
        _thresholds_accept(),
    )

    stratum = stats[StratumKey(level="L0", protected_class="none")]
    assert stratum.false_corrections == 1
    assert stratum.false_correction_rate == 1.0


def test_route_counted_when_not_accepted() -> None:
    from build.tools.ocr_pipeline.measure_corrector import StratumKey, measure_page

    position = _make_position()

    stats = measure_page(
        _wct_page(position),
        {"pos-001": {"gold_text": "Abraham"}},
        _thresholds_reject(),
    )

    stratum = stats[StratumKey(level="L0", protected_class="none")]
    assert stratum.routes == 1
    assert stratum.auto_accepted == 0
    assert stratum.total_with_gold == 1


def test_positions_without_gold_are_skipped() -> None:
    from build.tools.ocr_pipeline.measure_corrector import measure_page

    covered = _make_position("pos-covered")
    skipped = _make_position("pos-skipped")

    stats = measure_page(
        _wct_page(covered, skipped),
        {"pos-covered": {"gold_text": "Abraham"}},
        _thresholds_accept(),
    )

    assert sum(stratum.total_with_gold for stratum in stats.values()) == 1


def test_protected_class_leak_counted_when_accepted_protected() -> None:
    from build.tools.ocr_pipeline.measure_corrector import (
        MeasurementReport,
        StratumKey,
        _update_stats,
    )

    stats = {}
    _update_stats(
        stats,
        {
            "chosen_action": _ACCEPT,
            "derivation_method": "L0",
            "protected_class": "proper_name",
            "chosen_reading_index": 0,
            "derivable_readings": [{"text": "Augustine"}],
        },
        "Augustine",
    )
    report = MeasurementReport(corpus_name="synthetic", strata=stats)

    assert stats[StratumKey(level="L0", protected_class="proper_name")].protected_leaks == 1
    assert report.protected_leak_count == 1


def test_stratum_key_separates_levels() -> None:
    from build.tools.ocr_pipeline.measure_corrector import StratumKey, measure_page

    l0_position = _make_position("pos-l0")
    l1_position = _make_position("pos-l1", families=["abbyy"])

    stats = measure_page(
        _wct_page(l0_position, l1_position),
        {"pos-l0": {"gold_text": "Abraham"}, "pos-l1": {"gold_text": "Abraham"}},
        _thresholds_accept_l0_l1(),
    )

    assert StratumKey(level="L0", protected_class="none") in stats
    assert StratumKey(level="L1", protected_class="none") in stats


def test_corpus_report_aggregates_pages() -> None:
    from build.tools.ocr_pipeline.measure_corrector import StratumKey, measure_corpus

    report = measure_corpus(
        [
            _wct_page(_make_position("pos-001"), page_id="page-001"),
            _wct_page(_make_position("pos-002"), page_id="page-002"),
        ],
        {
            "page-001": {"pos-001": {"gold_text": "Abraham"}},
            "page-002": {"pos-002": {"gold_text": "Abraham"}},
        },
        _thresholds_accept(),
        corpus_name="synthetic",
    )

    assert report.strata[StratumKey(level="L0", protected_class="none")].total_with_gold == 2


def test_delta_report_correct_sign_and_magnitude() -> None:
    from build.tools.ocr_pipeline.measure_corrector import (
        MeasurementReport,
        StratumKey,
        StratumStats,
        delta_report,
    )

    key = StratumKey(level="L0", protected_class="none")
    report_a = MeasurementReport(
        corpus_name="a",
        strata={key: StratumStats(key, total_with_gold=4, auto_accepted=4, false_corrections=2)},
    )
    report_b = MeasurementReport(
        corpus_name="b",
        strata={key: StratumStats(key, total_with_gold=4, auto_accepted=4, false_corrections=1)},
    )

    delta = delta_report(report_a, report_b)

    assert delta[str(key)]["fcr_delta"] == -0.25


def test_report_serializes_to_json_with_string_keys() -> None:
    import json

    from build.tools.ocr_pipeline.measure_corrector import (
        StratumKey,
        measure_corpus,
        report_to_dict,
    )

    report = measure_corpus(
        [
            _wct_page(_make_position("pos-001"), page_id="page-001"),
            _wct_page(_make_position("pos-002"), page_id="page-002"),
        ],
        {
            "page-001": {"pos-001": {"gold_text": "Abraham"}},
            "page-002": {"pos-002": {"gold_text": "WRONG_GOLD"}},
        },
        _thresholds_accept(),
        corpus_name="synthetic",
    )

    # The bug: dataclasses.asdict(report) leaves strata keyed by the StratumKey
    # NamedTuple, which json.dumps cannot serialize. report_to_dict must produce
    # string keys that survive a full dump/load round-trip.
    payload = report_to_dict(report)
    round_tripped = json.loads(json.dumps(payload, indent=2))

    key = str(StratumKey(level="L0", protected_class="none"))
    assert key in round_tripped["strata"]
    stratum = round_tripped["strata"][key]
    assert stratum["total_with_gold"] == 2
    assert stratum["auto_accepted"] == 2
    assert stratum["false_corrections"] == 1
    assert stratum["routes"] == 0
    assert stratum["protected_leaks"] == 0
    assert stratum["false_correction_rate"] == 0.5
    assert stratum["route_rate"] == 0.0
    assert round_tripped["corpus_name"] == "synthetic"
    assert round_tripped["protected_leak_count"] == 0


def test_delta_report_missing_stratum_produces_zero_counts() -> None:
    from build.tools.ocr_pipeline.measure_corrector import (
        MeasurementReport,
        StratumKey,
        StratumStats,
        delta_report,
    )

    s1 = StratumKey(level="L0", protected_class="none")
    s2 = StratumKey(level="L1", protected_class="none")
    report_a = MeasurementReport(
        corpus_name="a",
        strata={s1: StratumStats(s1, total_with_gold=1, auto_accepted=1)},
    )
    report_b = MeasurementReport(
        corpus_name="b",
        strata={s2: StratumStats(s2, total_with_gold=2, auto_accepted=2)},
    )

    delta = delta_report(report_a, report_b)

    assert delta[str(s1)]["b_count"] == 0
    assert delta[str(s2)]["a_count"] == 0
