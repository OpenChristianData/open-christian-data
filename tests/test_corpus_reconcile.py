"""B16 deliverable #1 -- corpus-wide aligned consumption (TEST-16: degraded-flag
present + B8 diagnostics gate binds).

Contract: ``plans/2026-05-28-arch5-reconciler-synthesis.md`` (corpus reconcile) +
``plans/2026-05-28-archD-implementation-reconciled.md`` section 3 / the build
prompt's "Diagnostics gate also binds here" -- corpus-wide WCT/S3 *consumption*
is the one place the B8 first-diagnostics embargo binds (B13 *acquisition* is
ungated). Scaling alignment before measuring it bakes vol_01-class error into all
13 volumes, so corpus reconcile fails closed until the diagnostics reports exist.

Where a volume's per-page engine coverage is thin (fewer than two attesting
families, so there is no cross-engine evidence), the page is still reconciled in
single-engine degraded mode and FLAGGED -- never silently dropped, never passed
off as a multi-engine reconcile. The reconcile *verdict* on real corpus data is
phase 2; this suite proves the wrapper + gate + degraded flag on the synthetic
vol_01 WCT fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.lib import corpus_reconcile
from build.lib.first_diagnostics_contract import write_minimal_valid_reports
from build.lib.tuning_embargo import TuningEmbargoError

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "s3_reconciler"
OCCURRED_AT = "2026-05-30T00:00:00+00:00"


def _wct() -> dict:
    return json.loads((FIXTURE_DIR / "wct_vol01_synthetic.json").read_text(encoding="utf-8"))


def _meta() -> dict:
    return json.loads((FIXTURE_DIR / "work_meta.json").read_text(encoding="utf-8"))


def _thin_wct() -> dict:
    """The same page reduced to a single attesting family (no cross-engine evidence)."""
    page = _wct()
    for position in page.get("positions", []):
        for candidate in position.get("candidate_set", []):
            if candidate.get("attesting_families"):
                candidate["attesting_families"] = ["tesseract"]
    return page


def _rich_volume(volume_id: str = "vol_01") -> dict:
    page = _wct()
    return {"volume_id": volume_id, "work_meta": _meta(), "wct_pages": [page]}


def _thin_volume(volume_id: str = "vol_07") -> dict:
    return {"volume_id": volume_id, "work_meta": _meta(), "wct_pages": [_thin_wct()]}


# ---------------------------------------------------------------------------
# The B8 first-diagnostics gate binds aligned consumption
# ---------------------------------------------------------------------------

def test_corpus_reconcile_blocked_before_diagnostics(tmp_path):
    # No diagnostics reports under reports_root -> consumption is embargoed.
    with pytest.raises(TuningEmbargoError):
        corpus_reconcile.reconcile_corpus(
            [_rich_volume()],
            occurred_at=OCCURRED_AT,
            reports_root=tmp_path,
            read_only=False,
        )


def test_corpus_reconcile_read_only_dry_run_allowed(tmp_path):
    # Read-only diagnostic mode is allowed even with no diagnostics report.
    result = corpus_reconcile.reconcile_corpus(
        [_rich_volume()],
        occurred_at=OCCURRED_AT,
        reports_root=tmp_path,
        read_only=True,
    )
    assert result.volumes


def test_corpus_reconcile_allowed_after_diagnostics(tmp_path):
    write_minimal_valid_reports(tmp_path)
    result = corpus_reconcile.reconcile_corpus(
        [_rich_volume()],
        occurred_at=OCCURRED_AT,
        reports_root=tmp_path,
        read_only=False,
    )
    assert len(result.volumes) == 1


# ---------------------------------------------------------------------------
# Thin coverage is flagged, never silently dropped
# ---------------------------------------------------------------------------

def test_thin_coverage_volume_is_flagged(tmp_path):
    write_minimal_valid_reports(tmp_path)
    result = corpus_reconcile.reconcile_corpus(
        [_rich_volume("vol_01"), _thin_volume("vol_07")],
        occurred_at=OCCURRED_AT,
        reports_root=tmp_path,
    )
    assert result.has_thin_coverage is True
    assert "vol_07" in result.thin_coverage_volumes
    flagged = {f["volume_id"]: f for f in result.degraded_flags}
    assert "vol_07" in flagged
    assert flagged["vol_07"]["flag"] == corpus_reconcile.COVERAGE_THIN
    assert flagged["vol_07"]["min_page_engine_family_count"] == 1


def test_thin_coverage_volume_is_not_silently_dropped(tmp_path):
    write_minimal_valid_reports(tmp_path)
    result = corpus_reconcile.reconcile_corpus(
        [_thin_volume("vol_07")],
        occurred_at=OCCURRED_AT,
        reports_root=tmp_path,
    )
    # The thin volume is still present AND still produces a reconciled record --
    # degraded, but not dropped.
    assert [v.volume_id for v in result.volumes] == ["vol_07"]
    volume = result.volumes[0]
    assert volume.thin_coverage is True
    assert volume.page_results
    assert volume.page_results[0].reconciled_record["blocks"]


def test_rich_coverage_volume_not_flagged_thin(tmp_path):
    write_minimal_valid_reports(tmp_path)
    result = corpus_reconcile.reconcile_corpus(
        [_rich_volume("vol_01")],
        occurred_at=OCCURRED_AT,
        reports_root=tmp_path,
    )
    volume = result.volumes[0]
    assert volume.thin_coverage is False
    assert volume.engine_family_count == 3
    assert result.has_thin_coverage is False
    assert result.degraded_flags == []


def test_corpus_reconcile_is_always_degraded_mode(tmp_path):
    write_minimal_valid_reports(tmp_path)
    result = corpus_reconcile.reconcile_corpus(
        [_rich_volume("vol_01")],
        occurred_at=OCCURRED_AT,
        reports_root=tmp_path,
    )
    # B16 has no promoted matrix snapshot / family-map readiness yet (phase 2),
    # so the whole corpus reconcile is degraded mode regardless of coverage.
    assert result.degraded_mode is True
    assert result.degraded_mode_reason == corpus_reconcile.DEGRADED_MODE_REASON
