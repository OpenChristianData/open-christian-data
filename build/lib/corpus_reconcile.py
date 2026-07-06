"""B16 deliverable #1 -- corpus-wide S2.5/S3 aligned consumption (degraded-flagged).

Wraps the B10 per-page degraded reconciler (``s3_reconciler.reconcile_degraded``)
across all volumes. This is the "aligned consumption" the B8 first-diagnostics
gate binds (archD section 3 / Codex Attack 1): scaling alignment before measuring
it would bake vol_01-class error into all 13 volumes, so corpus reconcile fails
closed until the first diagnostics reports exist (the tuning embargo). B13's
*acquisition* is ungated; this *consumption* is gated.

Where a volume's per-page engine coverage is thin (fewer than two attesting
families on a page, so there is no cross-engine evidence to reconcile), the page
is still reconciled in single-engine degraded mode and FLAGGED -- never silently
dropped, never passed off as a multi-engine reconcile.

The reconcile *verdict* on real corpus data is phase 2; this module is the wrapper
+ gate + degraded flag, proven on the synthetic vol_01 WCT fixture.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from build.lib import tuning_embargo
from build.lib.s3_reconciler import ReconcileResult, reconcile_degraded

# A page needs at least this many attesting engine families for cross-engine
# reconcile; below it the reconcile is single-engine degraded and flagged.
MIN_ENGINE_FAMILIES = 2

# The corpus reconcile is always in degraded MODE in B16: no promoted matrix
# snapshot and no family-map readiness yet (both phase 2). Distinct from
# thin-coverage degradation, which is per-volume.
DEGRADED_MODE_REASON = "no_promoted_matrix_snapshot"

COVERAGE_THIN = "thin_coverage"

# Corpus reconcile is the alignment-strategy consumption surface, so it rides the
# same embargo operation class the B8 gate protects.
_EMBARGO_OPERATION = "alignment_strategy"


@dataclass
class VolumeReconcileResult:
    volume_id: str
    page_results: list[ReconcileResult]
    engine_families: tuple[str, ...]
    engine_family_count: int
    min_page_engine_family_count: int
    thin_coverage: bool
    coverage_flag: str | None


@dataclass
class CorpusReconcileResult:
    volumes: list[VolumeReconcileResult]
    degraded_mode: bool
    degraded_mode_reason: str
    has_thin_coverage: bool
    thin_coverage_volumes: tuple[str, ...]
    degraded_flags: list[dict[str, Any]]


def _page_engine_families(wct_page: Mapping[str, Any]) -> set[str]:
    families: set[str] = set()
    for position in wct_page.get("positions", []):
        for candidate in position.get("candidate_set", []):
            families.update(candidate.get("attesting_families", []))
    return families


def reconcile_corpus(
    volumes: Sequence[Mapping[str, Any]],
    *,
    occurred_at: str,
    reports_root: Path | str,
    read_only: bool = False,
    min_engine_families: int = MIN_ENGINE_FAMILIES,
) -> CorpusReconcileResult:
    """Reconcile every volume's WCT pages in degraded mode, behind the B8 gate.

    Args:
        volumes: a sequence of ``{"volume_id", "work_meta", "wct_pages"}`` dicts.
        occurred_at: ISO-8601 timestamp threaded to each page reconcile
            (deterministic / import-safe -- DATE-01 / PY-06).
        reports_root: root under which the first-diagnostics reports must exist
            for consumption to proceed.
        read_only: diagnostic dry-run; bypasses the embargo (read-only diagnostic
            mode is always allowed -- archD section 3).
        min_engine_families: per-page cross-engine minimum; below it a volume is
            flagged thin coverage.

    Raises:
        tuning_embargo.TuningEmbargoError: when consumption is attempted before the
            first-diagnostics reports exist (fail-closed).
    """
    # B8 first-diagnostics gate: aligned consumption is embargoed until the
    # diagnostics reports exist and validate. This is the load-bearing gate.
    tuning_embargo.check_tuning_allowed(
        _EMBARGO_OPERATION,
        reports_root=Path(reports_root),
        read_only=read_only,
    )

    volume_results: list[VolumeReconcileResult] = []
    degraded_flags: list[dict[str, Any]] = []
    thin_volumes: list[str] = []

    for volume in volumes:
        volume_id = volume["volume_id"]
        work_meta = volume["work_meta"]
        wct_pages = volume["wct_pages"]

        families: set[str] = set()
        page_results: list[ReconcileResult] = []
        min_page_family_count: int | None = None

        for wct_page in wct_pages:
            page_families = _page_engine_families(wct_page)
            families |= page_families
            count = len(page_families)
            if min_page_family_count is None or count < min_page_family_count:
                min_page_family_count = count
            page_results.append(
                reconcile_degraded(wct_page, work_meta, occurred_at=occurred_at)
            )

        min_page_family_count = min_page_family_count or 0
        # Thin if ANY page falls below the cross-engine minimum -- coverage is
        # measured per page so a single thin page surfaces, not averaged away.
        thin = min_page_family_count < min_engine_families
        flag = COVERAGE_THIN if thin else None

        if thin:
            thin_volumes.append(volume_id)
            degraded_flags.append(
                {
                    "volume_id": volume_id,
                    "flag": COVERAGE_THIN,
                    "engine_family_count": len(families),
                    "min_page_engine_family_count": min_page_family_count,
                    "min_required": min_engine_families,
                }
            )

        volume_results.append(
            VolumeReconcileResult(
                volume_id=volume_id,
                page_results=page_results,
                engine_families=tuple(sorted(families)),
                engine_family_count=len(families),
                min_page_engine_family_count=min_page_family_count,
                thin_coverage=thin,
                coverage_flag=flag,
            )
        )

    return CorpusReconcileResult(
        volumes=volume_results,
        degraded_mode=True,
        degraded_mode_reason=DEGRADED_MODE_REASON,
        has_thin_coverage=bool(thin_volumes),
        thin_coverage_volumes=tuple(thin_volumes),
        degraded_flags=degraded_flags,
    )
