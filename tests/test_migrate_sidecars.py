"""Tests for build/tools/migrate_sidecars.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools import migrate_sidecars as mig  # noqa: E402
from build.lib import review_state, sidecar_migrations  # noqa: E402


def test_skips_already_current_sidecars(tmp_path: Path, capsys):
    repo = tmp_path / "repo"
    (repo / "review" / "state").mkdir(parents=True)
    sidecar_path = repo / "review" / "state" / "x.json"
    review_state.save_sidecar(
        sidecar_path,
        review_state.empty_sidecar(
            record_path="data/x.json",
            record_resource_id="x",
            record_checksum_sha256="0" * 64,
            parser_version_seen="build/parsers/x.py@v1.0.0",
        ),
    )
    rc = mig.main(["--repo-root", str(repo), str(sidecar_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Migrated 0" in out
    assert "skipped 1" in out
    # Audit log should remain empty (no migration event for already-current).
    audit_path = repo / "review" / "audit.jsonl"
    assert not audit_path.exists()


def test_no_path_raises_when_unknown_target(tmp_path: Path, capsys):
    # An older-schema sidecar without a migration path raises MigrationError.
    sidecar_path = tmp_path / "x.json"
    sidecar_path.write_text(
        json.dumps(
            {
                "schema_type": "review_state",
                "schema_version": "0.5.0",
                "record_path": "data/x.json",
                "record_resource_id": "x",
                "record_checksum_sha256": "0" * 64,
                "parser_version_seen": "build/parsers/x.py@v1.0.0",
                "confidence": {
                    "structural_fidelity": "unverified",
                    "text_fidelity": "unverified",
                    "edition_provenance": "unverified",
                },
                "entries": {},
                "dead_letter": [],
            }
        ),
        encoding="utf-8",
    )
    import pytest
    with pytest.raises(sidecar_migrations.MigrationError):
        mig.main(["--repo-root", str(tmp_path), str(sidecar_path)])


def test_dry_run_reports_without_writing(tmp_path: Path, capsys, monkeypatch):
    # Inject a synthetic 0.5.0 -> 1.0.0 migration so the walker has a target.
    monkeypatch.setitem(sidecar_migrations.MIGRATIONS, ("0.5.0", "1.0.0"), lambda p: dict(p))

    repo = tmp_path / "repo"
    (repo / "review" / "state").mkdir(parents=True)
    sidecar_path = repo / "review" / "state" / "x.json"
    sidecar_path.write_text(
        json.dumps(
            {
                "schema_type": "review_state",
                "schema_version": "0.5.0",
                "record_path": "data/x.json",
                "record_resource_id": "x",
                "record_checksum_sha256": "0" * 64,
                "parser_version_seen": "build/parsers/x.py@v1.0.0",
                "confidence": {
                    "structural_fidelity": "unverified",
                    "text_fidelity": "unverified",
                    "edition_provenance": "unverified",
                },
                "entries": {},
                "dead_letter": [],
            }
        ),
        encoding="utf-8",
    )
    try:
        rc = mig.main(["--repo-root", str(repo), "--dry-run", str(sidecar_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "would migrate" in out
        assert not (repo / "review" / "audit.jsonl").exists()
    finally:
        sidecar_migrations.MIGRATIONS.clear()
