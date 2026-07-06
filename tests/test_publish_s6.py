from __future__ import annotations

import json

from build.lib.typography_snapshot import (
    build_typography_envelope,
    build_typography_payload,
    write_typography_snapshot,
)
from build.tools import publish_s6_dryrun


def _records_path(tmp_path):
    records = [
        {
            "record_id": "rec-001",
            "canonical_text": "Clean public text.",
            "title": "Entry",
            "work_id": "schaff_herzog",
            "internal_id": "private-001",
            "output_status": "human_confirmed",
            "attestations": [{"source": "manual"}],
            "evidence": [{"ref": "page-001"}],
        }
    ]
    path = tmp_path / "records.json"
    path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return path


def _envelope_path(tmp_path, approval_state: str):
    payload = build_typography_payload(
        cohort_id="cohort-schaff-herzog-v1",
        tier_assignments=[{"token_id": "v01-p0001-t0001", "relative_size_tier": "body"}],
        canonical_x_size={"unit": "px", "value": 10.5},
        substyles=[],
    )
    envelope = build_typography_envelope(
        payload,
        approval_state=approval_state,
        approved_at="2026-05-31T00:00:00Z" if approval_state == "approved" else None,
        approver_id="maintainer" if approval_state == "approved" else None,
    )
    _payload_path, envelope_path = write_typography_snapshot(tmp_path, payload, envelope)
    return envelope_path


def test_dryrun_orchestrator_no_live_publish(tmp_path) -> None:
    records_path = _records_path(tmp_path)
    envelope_path = _envelope_path(tmp_path, "approved")
    staging_dir = tmp_path / "staging"

    result = publish_s6_dryrun.main(
        [
            "--records",
            str(records_path),
            "--typography-envelope",
            str(envelope_path),
            "--staging-dir",
            str(staging_dir),
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert result == 0
    assert (staging_dir / "slim_config.json").exists()
    assert (staging_dir / "audit_artifact.json").exists()
    assert (staging_dir / "dryrun_manifest.json").exists()
    report = json.loads(
        (tmp_path / "reports" / "publish" / "s6_dryrun_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["dry_run"] is True
    assert report["live_publish_performed"] is False
    assert report["config"] == "option-C-slim-public+audit-private"


def test_dryrun_blocks_unapproved_snapshot(tmp_path) -> None:
    records_path = _records_path(tmp_path)
    envelope_path = _envelope_path(tmp_path, "draft")
    staging_dir = tmp_path / "staging"

    result = publish_s6_dryrun.main(
        [
            "--records",
            str(records_path),
            "--typography-envelope",
            str(envelope_path),
            "--staging-dir",
            str(staging_dir),
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert result == 1
    assert not staging_dir.exists()


def test_dryrun_failure_writes_report(tmp_path) -> None:
    # Even a blocked dry-run writes an auditable report affirming live publish was
    # not performed (Codex review finding 5).
    records_path = _records_path(tmp_path)
    envelope_path = _envelope_path(tmp_path, "draft")
    staging_dir = tmp_path / "staging"

    result = publish_s6_dryrun.main(
        [
            "--records",
            str(records_path),
            "--typography-envelope",
            str(envelope_path),
            "--staging-dir",
            str(staging_dir),
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert result == 1
    report = json.loads(
        (tmp_path / "reports" / "publish" / "s6_dryrun_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["dry_run"] is True
    assert report["live_publish_performed"] is False
    assert report["live_publish_status"] == "not_performed_dryrun_blocked"
