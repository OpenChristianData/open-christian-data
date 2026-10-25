"""State evidence must follow the configured OCD data-plane boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import _existing_evidence_paths


def test_state_evidence_resolves_configured_reports_root(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    work_root = repo_root / "library" / "works" / "example"
    library_root = tmp_path / "durable-library"
    work_root.mkdir(parents=True)
    report = library_root / "reports" / "runs" / "receipt.json"
    report.parent.mkdir(parents=True)
    report.write_text("{}", encoding="utf-8")
    (repo_root / ".ocd-storage.json").write_text(
        json.dumps({"library_root": str(library_root)}),
        encoding="utf-8",
    )

    _existing_evidence_paths(
        ["reports/runs/receipt.json"],
        root=repo_root,
        work_root=work_root,
        context="fixture state",
    )


def test_state_evidence_fails_closed_when_report_is_outside_configured_root(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    work_root = repo_root / "library" / "works" / "example"
    library_root = tmp_path / "durable-library"
    work_root.mkdir(parents=True)
    (library_root / "reports").mkdir(parents=True)
    (library_root / "reports" / "receipt.json").write_text("{}", encoding="utf-8")
    config = repo_root / ".ocd-storage.json"
    config.write_text(
        json.dumps({"library_root": str(tmp_path / "other-library")}),
        encoding="utf-8",
    )

    with pytest.raises(PipelineError, match="state evidence references missing files"):
        _existing_evidence_paths(
            ["reports/receipt.json"],
            root=repo_root,
            work_root=work_root,
            context="fixture state",
        )
