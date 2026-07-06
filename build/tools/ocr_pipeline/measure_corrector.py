from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

from build.lib.gold_free_corrector.column_vote import correct_position
from build.lib.gold_free_corrector.decide import _ACCEPT, decide


class StratumKey(NamedTuple):
    level: str | None
    protected_class: str


@dataclass
class StratumStats:
    stratum_key: StratumKey
    total_with_gold: int = 0
    auto_accepted: int = 0
    false_corrections: int = 0
    routes: int = 0
    protected_leaks: int = 0

    @property
    def false_correction_rate(self) -> float:
        return self.false_corrections / self.auto_accepted if self.auto_accepted else 0.0

    @property
    def route_rate(self) -> float:
        return self.routes / self.total_with_gold if self.total_with_gold else 0.0


@dataclass
class MeasurementReport:
    corpus_name: str
    strata: dict[StratumKey, StratumStats] = field(default_factory=dict)

    @property
    def protected_leak_count(self) -> int:
        return sum(s.protected_leaks for s in self.strata.values())


def measure_page(
    wct_page: dict,
    gold_page: dict[str, dict],
    thresholds: dict,
    *,
    region_class: str = "body",
) -> dict[StratumKey, StratumStats]:
    """Measure corrector decisions for one WCT page against gold labels."""
    stats_by_stratum: dict[StratumKey, StratumStats] = {}
    for position in wct_page["positions"]:
        pid = position["position_id"]
        if pid not in gold_page:
            continue
        cvr = correct_position(position)
        cvr = decide(cvr, thresholds, region_class=region_class)
        _update_stats(stats_by_stratum, cvr.corrected_position, gold_page[pid]["gold_text"])
    return stats_by_stratum


def measure_corpus(
    wct_pages: list[dict],
    gold_corpus: dict[str, dict[str, dict]],
    thresholds: dict,
    *,
    corpus_name: str,
    region_class: str = "body",
) -> MeasurementReport:
    """Aggregate measure_page across all pages into one MeasurementReport."""
    report = MeasurementReport(corpus_name=corpus_name)
    for wct_page in wct_pages:
        page_id = wct_page["page_id"]
        if page_id not in gold_corpus:
            continue
        page_stats = measure_page(
            wct_page,
            gold_corpus[page_id],
            thresholds,
            region_class=region_class,
        )
        for key, stats in page_stats.items():
            aggregate = report.strata.setdefault(key, StratumStats(stratum_key=key))
            _accumulate(aggregate, stats)
    return report


def delta_report(
    report_a: MeasurementReport,
    report_b: MeasurementReport,
) -> dict[str, dict]:
    """Return per-stratum deltas between two corpus reports."""
    deltas = {}
    for key in sorted(set(report_a.strata) | set(report_b.strata), key=str):
        a_stats = report_a.strata.get(key, StratumStats(stratum_key=key))
        b_stats = report_b.strata.get(key, StratumStats(stratum_key=key))
        deltas[str(key)] = {
            "a_fcr": a_stats.false_correction_rate,
            "b_fcr": b_stats.false_correction_rate,
            "fcr_delta": b_stats.false_correction_rate - a_stats.false_correction_rate,
            "a_route_rate": a_stats.route_rate,
            "b_route_rate": b_stats.route_rate,
            "route_rate_delta": b_stats.route_rate - a_stats.route_rate,
            "a_count": a_stats.total_with_gold,
            "b_count": b_stats.total_with_gold,
        }
    return deltas


def report_to_dict(report: MeasurementReport) -> dict:
    """Serialize a MeasurementReport into a JSON-safe dict.

    ``dataclasses.asdict`` cannot be used directly: ``strata`` is keyed by the
    ``StratumKey`` NamedTuple, and ``json.dumps`` rejects non-str/int/float/bool/None
    dict keys. Each stratum is re-keyed by ``str(key)`` (matching the convention in
    ``delta_report``) and carries its raw fields plus the derived rates.
    """
    return {
        "corpus_name": report.corpus_name,
        "protected_leak_count": report.protected_leak_count,
        "strata": {
            str(key): {
                "level": key.level,
                "protected_class": key.protected_class,
                "total_with_gold": stats.total_with_gold,
                "auto_accepted": stats.auto_accepted,
                "false_corrections": stats.false_corrections,
                "routes": stats.routes,
                "protected_leaks": stats.protected_leaks,
                "false_correction_rate": stats.false_correction_rate,
                "route_rate": stats.route_rate,
            }
            for key, stats in report.strata.items()
        },
    }


def _update_stats(
    stats_by_stratum: dict[StratumKey, StratumStats],
    corrected_position: dict,
    gold_text: str,
) -> None:
    chosen_action = corrected_position["chosen_action"]
    level = corrected_position.get("derivation_method")
    protected = corrected_position.get("protected_class", "none")
    key = StratumKey(level=level, protected_class=protected)
    stats = stats_by_stratum.setdefault(key, StratumStats(stratum_key=key))
    stats.total_with_gold += 1

    if chosen_action == _ACCEPT:
        stats.auto_accepted += 1
        idx = corrected_position.get("chosen_reading_index")
        readings = corrected_position.get("derivable_readings", [])
        if idx is not None and 0 <= idx < len(readings):
            chosen_text = readings[idx]["text"]
            if chosen_text != gold_text:
                stats.false_corrections += 1
        if protected != "none":
            stats.protected_leaks += 1
    else:
        stats.routes += 1


def _accumulate(target: StratumStats, source: StratumStats) -> None:
    target.total_with_gold += source.total_with_gold
    target.auto_accepted += source.auto_accepted
    target.false_corrections += source.false_corrections
    target.routes += source.routes
    target.protected_leaks += source.protected_leaks


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--wct-dir", type=Path, required=True)
    parser.add_argument("--gold-dir", type=Path, required=True, help="Directory of <page_id>.gold.json files")
    parser.add_argument("--thresholds", type=Path, default=None)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    wct_pages = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(args.wct_dir.glob("*.json"))
    ]
    gold_corpus = {}
    for gf in args.gold_dir.glob("*.gold.json"):
        page_id = gf.stem.removesuffix(".gold")
        gold_corpus[page_id] = json.loads(gf.read_text(encoding="utf-8"))["positions"]
    thresholds = json.loads(args.thresholds.read_text(encoding="utf-8")) if args.thresholds else {}

    report = measure_corpus(wct_pages, gold_corpus, thresholds, corpus_name=args.corpus)

    print(f"Corpus: {report.corpus_name}")
    print(f"Strata: {len(report.strata)}")
    for key, s in sorted(report.strata.items(), key=lambda item: str(item[0])):
        print(
            f"  {key}: {s.auto_accepted}/{s.total_with_gold} accepted, "
            f"fcr={s.false_correction_rate:.3f}, routes={s.route_rate:.3f}, "
            f"leaks={s.protected_leaks}"
        )
    print(f"Protected-class leaks total: {report.protected_leak_count}")

    if args.out:
        args.out.write_text(json.dumps(report_to_dict(report), indent=2), encoding="utf-8")
