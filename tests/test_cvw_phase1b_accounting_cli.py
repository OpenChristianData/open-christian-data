"""Public CLI tests for selected-catalog Phase 1B accounting."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cvw_phase1b.accounting_cli import main
from tests.test_cvw_phase1b_catalog_accounting import (
    _render_catalog,
    _render_catalog_identity,
    accounting_repo,
)


def test_accounting_cli_reports_ready_snapshot_with_reconstruction_depth(
    accounting_repo: tuple[Path, Path], capsys
) -> None:
    root, registry = accounting_repo

    result = main(
        [
            "--repository-root",
            str(root),
            "--registry",
            str(registry),
            "--format",
            "text",
            "--catalog-only",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    lines = captured.out.splitlines()
    assert lines[0] == "phase1b-catalog-exit: READY"
    assert lines[2] == (
        "reconstruction-depth: authenticated=1 referenced_only=1 unavailable=0 total=2"
    )
    assert lines[3] == "canonical-data: owned_work_units=2 owned_artifacts=3"
    assert lines[4] == "blockers: none"


def test_accounting_cli_json_is_deterministic_and_ready_returns_zero(
    accounting_repo: tuple[Path, Path], capsys
) -> None:
    root, registry = accounting_repo
    (root / "data/structured-text/unowned-work.json").unlink()
    catalog = root / "docs/WORK_CATALOG.md"
    catalog_bytes = _render_catalog(root)
    identity_bytes = _render_catalog_identity(root)
    catalog.write_bytes(catalog_bytes)
    (root / "cvw_phase1a/fixtures/work_catalog_identity.json").write_bytes(identity_bytes)
    registry_payload = json.loads(registry.read_bytes())
    registry_payload["catalog"]["raw_sha256"] = hashlib.sha256(catalog_bytes).hexdigest()
    registry_payload["catalog"]["identity_raw_sha256"] = hashlib.sha256(
        identity_bytes
    ).hexdigest()
    registry.write_text(json.dumps(registry_payload, indent=2) + "\n", encoding="utf-8")

    result = main(
        [
            "--repository-root",
            str(root),
            "--registry",
            str(registry),
            "--format",
            "json",
            "--catalog-only",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["phase1b_exit"] == {"reasons": [], "state": "READY"}


def test_accounting_cli_invalid_snapshot_returns_two(
    accounting_repo: tuple[Path, Path], capsys
) -> None:
    root, registry = accounting_repo
    (root / "docs/WORK_CATALOG.md").write_bytes(b"changed\n")

    result = main(
        [
            "--repository-root",
            str(root),
            "--registry",
            str(registry),
            "--catalog-only",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert "snapshot hash" in captured.err
