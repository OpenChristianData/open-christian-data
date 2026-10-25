"""Opt-in fixture measurement of the full-projection oracle, never a route.

Index admission parses the complete master; first view constructs the complete
projection. These are deliberately not WorkCatalog admission or bounded loading.
Serialized response bytes are uncompressed canonical JSON, not HTTP wire bytes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter

from cvw_app.bounded_tei_projection import build_projection, renderer_version, select_projection
from cvw_app.bounded_xml_index import build_index
from cvw_app.ingest_cache import estimate_retained_bytes


@dataclass(frozen=True)
class BudgetResult:
    first_view_pass: bool
    warm_navigation_pass: bool
    warm_trials_within_budget: int


def evaluate_budgets(first_view_seconds: float, navigation_seconds: tuple[float, ...]) -> BudgetResult:
    """Evaluate the spec's 5-second first view and 9/10 one-second warm trials."""
    if len(navigation_seconds) != 10:
        raise ValueError("exactly ten navigation trials are required")
    if any(isinstance(value, bool) or not math.isfinite(value) or value < 0
           for value in (first_view_seconds, *navigation_seconds)):
        raise ValueError("durations must be finite nonnegative seconds")
    successes = sum(value <= 1.0 for value in navigation_seconds)
    return BudgetResult(first_view_seconds <= 5.0, successes >= 9, successes)


def _encoded(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def measure_fixture_projection(master: Path, *, expected_sha256: str,
                               location: str, segment: int) -> dict[str, object]:
    """Measure one fresh local oracle and ten same-selection navigation calls.

    Caller supplies an exact fixture digest and existing global CVW selection.
    No source identity is inferred; all selections use normal integrity checks.
    No result escapes if an input changes or a requested location is invalid.
    Retained size counts the reachable index/projection payload graph, not RSS.
    The observer reports one full-render input; internal parser replays and
    separate verification I/O are not counted as if they were measured here.
    """
    version = renderer_version()
    started = perf_counter()
    index = build_index(master, expected_sha256=expected_sha256, renderer_version=version)
    admission_seconds = perf_counter() - started
    retained_after_admission = estimate_retained_bytes(index)
    render_inputs: list[int] = []
    started = perf_counter()
    projection = build_projection(master, index, expected_sha256=expected_sha256,
                                  observe_render_input=render_inputs.append)
    selected = select_projection(master, index, projection, expected_sha256=expected_sha256,
                                 location=location, segment=segment)
    first_view_seconds = perf_counter() - started
    encoded = _encoded(selected)
    response_sha256 = hashlib.sha256(encoded).hexdigest()
    retained_after_first_view = estimate_retained_bytes((index, projection))
    navigation_seconds = []
    navigation_bytes = []
    for _ in range(10):
        started = perf_counter()
        selected = select_projection(master, index, projection, expected_sha256=expected_sha256,
                                     location=location, segment=segment)
        navigation_seconds.append(perf_counter() - started)
        encoded_navigation = _encoded(selected)
        if encoded_navigation != encoded:
            raise ValueError("navigation response drifted from the first selected view")
        navigation_bytes.append(len(encoded_navigation))
    return {
        "measurement_scope": "fixture-full-projection-oracle",
        "master_sha256": index.master_sha256,
        "index_integrity_sha256": index.integrity_sha256,
        "indexer_version": index.indexer_version,
        "renderer_version": projection.renderer_version,
        "projection_integrity_sha256": projection.integrity_sha256,
        "selected_response_sha256": response_sha256,
        "location": location, "segment": segment,
        "index_admission_seconds": admission_seconds,
        "first_view_after_index_admission_seconds": first_view_seconds,
        "navigation_seconds": navigation_seconds,
        "index_parser_input_bytes": index.byte_count,
        "full_renderer_input_bytes": sum(render_inputs),
        "first_view_serialized_response_bytes": len(encoded),
        "navigation_serialized_response_bytes": navigation_bytes,
        "retained_after_index_admission_bytes": retained_after_admission,
        "retained_index_and_projection_bytes": retained_after_first_view,
        "budgets": asdict(evaluate_budgets(first_view_seconds, tuple(navigation_seconds))),
        "unmeasured": ["HTTP wire bytes", "renderer-internal parse/reparse bytes",
                       "verification I/O bytes and isolated timing", "peak process RSS",
                       "20-percent cold/memory regression without a paired baseline"],
        "fresh_process_repeats": 0,
        "route_activated": False,
    }
