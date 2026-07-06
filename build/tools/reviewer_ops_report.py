"""Reviewer-ops report: inflow, throughput, and starvation-diagnosis metrics.

Surfaces the six fields needed to tell engine/family starvation from
reviewer-capacity starvation (archD Phase-3 reviewer row, arch7 s14).

Usage:
    py -3 build/tools/reviewer_ops_report.py --volume 1 [--base-dir <path>]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.decision_store import DecisionStore  # noqa: E402

_AUTHORITY_CATEGORY = "authority_decision"
DEFAULT_BASE_DIR = _BOOTSTRAP_ROOT


def compute_reviewer_ops_report(store: DecisionStore) -> dict:
    """Compute reviewer-ops metrics from the given DecisionStore.

    Returns a dict with keys:
      inflow, completed, batch_confirm_rate, override_rate,
      stale_age_seconds, time_per_decision_seconds, volume, generated_at.
    """
    events = store.fold()
    now = datetime.now(timezone.utc)

    authority_events = [e for e in events if e.get("event_category") == _AUTHORITY_CATEGORY]
    inflow = len(events)
    completed = len(authority_events)

    if completed == 0:
        batch_confirm_rate = 0.0
        override_rate = 0.0
    else:
        ratifications = sum(
            1 for e in authority_events if e.get("decision_token") == "ratification"
        )
        overrides = sum(
            1 for e in authority_events if e.get("decision_token") == "override"
        )
        batch_confirm_rate = ratifications / completed
        override_rate = overrides / completed

    # stale_age_seconds: age of the oldest event (proxy for oldest unresolved item)
    if not events:
        stale_age_seconds = 0.0
    else:
        oldest_ts_str = events[0].get("timestamp", "")
        try:
            oldest_dt = datetime.fromisoformat(oldest_ts_str.replace("Z", "+00:00"))
            stale_age_seconds = (now - oldest_dt).total_seconds()
        except (ValueError, AttributeError):
            stale_age_seconds = 0.0

    # time_per_decision_seconds: average gap between consecutive authority events
    if len(authority_events) < 2:
        time_per_decision_seconds = 0.0
    else:
        gaps: list[float] = []
        prev_dt: datetime | None = None
        for e in authority_events:
            ts_str = e.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            if prev_dt is not None:
                gap = abs((dt - prev_dt).total_seconds())
                gaps.append(gap)
            prev_dt = dt
        time_per_decision_seconds = sum(gaps) / len(gaps) if gaps else 0.0

    return {
        "inflow": inflow,
        "completed": completed,
        "batch_confirm_rate": batch_confirm_rate,
        "override_rate": override_rate,
        "stale_age_seconds": stale_age_seconds,
        "time_per_decision_seconds": time_per_decision_seconds,
        "volume": store._volume,
        "generated_at": now.isoformat(),
    }


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="py -3 build/tools/reviewer_ops_report.py",
        description="Print reviewer-ops metrics for a decision store volume.",
    )
    parser.add_argument("--volume", type=int, required=True, help="Volume number (e.g. 1)")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=DEFAULT_BASE_DIR,
        help="Base directory containing decisions/. Defaults to repo root.",
    )
    args = parser.parse_args(argv)
    store = DecisionStore(base_dir=args.base_dir, volume=args.volume)
    report = compute_reviewer_ops_report(store)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
