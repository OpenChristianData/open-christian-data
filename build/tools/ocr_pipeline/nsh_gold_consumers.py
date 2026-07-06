"""Consumer read paths over human-adjudicated NSH gold-position records."""
from __future__ import annotations

from collections.abc import Callable, Iterable

from build.tools.ocr_pipeline.abbyy_lineage_value_study import score_position, wilson_ci


GoldRecord = dict
ChosenReading = Callable[[GoldRecord], str | None]


def _verified_records(records: Iterable[GoldRecord]) -> list[GoldRecord]:
    return [
        record
        for record in records
        if record.get("review_status") == "verified"
        and isinstance(record.get("true_reading"), str)
        and record["true_reading"].strip()
    ]


def _rate(count: int, n: int) -> float:
    return count / n if n else 0.0


def score_abbyy_lineage(records: Iterable[GoldRecord]) -> dict:
    """Measure whether alternate ABBYY lineages recover truth the baseline lacks."""
    verified = _verified_records(records)
    n = len(verified)
    unique_recovery = 0
    redundant_recovery = 0
    noise_added = 0

    for record in verified:
        score = score_position(
            record["baseline_candidates"],
            record.get("alternate_candidates", {}),
            record["true_reading"],
        )
        unique_recovery += int(score["unique_recovery"])
        redundant_recovery += int(score["redundant_recovery"])
        noise_added += int(score["noise_added"])

    return {
        "n": n,
        "unique_recovery": unique_recovery,
        "redundant_recovery": redundant_recovery,
        "noise_added": noise_added,
        "unique_recovery_rate": _rate(unique_recovery, n),
        "unique_recovery_ci": wilson_ci(unique_recovery, n),
    }


def track_c_agreement(records: Iterable[GoldRecord]) -> dict:
    """Group human-vs-engine agreement by token class and script."""
    verified = _verified_records(records)
    grouped: dict[str, dict[str, int]] = {}
    overall = {"n": 0, "engine_agrees": 0}

    for record in verified:
        key = f"{record['token_class']}|{record['script']}"
        group = grouped.setdefault(key, {"n": 0, "engine_agrees": 0})
        engine_agrees = any(
            reading == record["true_reading"]
            for reading in record["baseline_candidates"].values()
        )

        group["n"] += 1
        group["engine_agrees"] += int(engine_agrees)
        overall["n"] += 1
        overall["engine_agrees"] += int(engine_agrees)

    return {
        "__overall__": {
            **overall,
            "agreement_rate": _rate(overall["engine_agrees"], overall["n"]),
        },
        **{
            key: {
                **group,
                "agreement_rate": _rate(group["engine_agrees"], group["n"]),
            }
            for key, group in sorted(grouped.items())
        },
    }


def _consensus_reading(record: GoldRecord) -> str | None:
    family_counts: dict[str, int] = {}
    for reading in record["baseline_candidates"].values():
        if reading is None:
            continue
        family_counts[reading] = family_counts.get(reading, 0) + 1

    if not family_counts:
        return None

    top_count = max(family_counts.values())
    top_readings = [reading for reading, count in family_counts.items() if count == top_count]
    if len(top_readings) != 1:
        return None
    return top_readings[0]


def m15_false_correction_proxy(
    records: Iterable[GoldRecord],
    *,
    chosen_reading: ChosenReading | None = None,
) -> dict:
    """Estimate false-correction rates by token class.

    When ``chosen_reading`` is None this is a PROXY: it uses the most-attested
    baseline-family consensus as the chosen reading. The real M15 calibration plugs
    in the corrector tier's actual chosen reading.
    """
    verified = _verified_records(records)
    choose = chosen_reading or _consensus_reading
    grouped: dict[str, dict[str, int]] = {}
    overall = {"n": 0, "false_corrections": 0}

    for record in verified:
        key = record["token_class"]
        group = grouped.setdefault(key, {"n": 0, "false_corrections": 0})
        chosen = choose(record)
        false_correction = chosen is not None and chosen != record["true_reading"]

        group["n"] += 1
        group["false_corrections"] += int(false_correction)
        overall["n"] += 1
        overall["false_corrections"] += int(false_correction)

    return {
        "__overall__": {
            **overall,
            "false_correction_rate": _rate(
                overall["false_corrections"],
                overall["n"],
            ),
            "false_correction_ci": wilson_ci(
                overall["false_corrections"],
                overall["n"],
            ),
        },
        **{
            key: {
                **group,
                "false_correction_rate": _rate(
                    group["false_corrections"],
                    group["n"],
                ),
                "false_correction_ci": wilson_ci(
                    group["false_corrections"],
                    group["n"],
                ),
            }
            for key, group in sorted(grouped.items())
        },
    }
