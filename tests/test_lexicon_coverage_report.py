from __future__ import annotations

import json
from pathlib import Path

from build.tools.lexicon_coverage_report import build_coverage_report, write_report


def _resource(path: Path, text: str) -> Path:
    payload = {
        "meta": {"schema_type": "commentary", "schema_version": "2.2.0", "id": "sample", "language": "en"},
        "data": [{"entry_id": "sample.1", "commentary_text": text}],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_report_generation_and_convergence_threshold(tmp_path: Path) -> None:
    resource = _resource(tmp_path / "data" / "sample.json", "The writer wandereth and reasoneth publickly.")

    report = build_coverage_report([resource], "en", 3)

    assert report["run_count"] == 3
    assert report["convergence_check"]["passed"] is True
    assert report["convergence_check"]["last_top_50_change_count"] == 0
    assert report["lexicon_status"] == "production"
    assert any(item["surface"] == "wandereth" for item in report["unmatched_top_50"])


def test_refuses_production_status_before_three_runs(tmp_path: Path) -> None:
    resource = _resource(tmp_path / "data" / "sample.json", "The writer wandereth.")

    report = build_coverage_report([resource], "en", 2)

    assert report["convergence_check"]["passed"] is False
    assert report["lexicon_status"] == "candidate_pending_convergence"
    assert report["convergence_check"]["refusal_reason"]


def test_write_report_uses_requested_path(tmp_path: Path) -> None:
    resource = _resource(tmp_path / "data" / "sample.json", "The writer wandereth.")
    out = tmp_path / "report.json"

    written = write_report(build_coverage_report([resource], "en", 3), out)

    assert written == out
    assert json.loads(out.read_text(encoding="utf-8"))["lexicon"] == "en"
