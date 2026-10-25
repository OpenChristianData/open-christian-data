"""Declared-library browsing must not depend on the historical catalog."""
import json

import pytest

from build.tools.report_library import main, render_markdown
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.views import library_browse_snapshot
from tests.test_library_views import _fixture_root


def test_browse_ignores_catalog_and_stale_generated_views(tmp_path):
    root = _fixture_root(tmp_path)
    before = library_browse_snapshot(root)
    for relative in ("reports/publish/work_catalog.json", "library/corpus-manifest.json",
                     "data/legacy.json"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("invalid JSON", encoding="utf-8")
    assert library_browse_snapshot(root) == before
    assert before["counts"]["works"] == 1
    assert "routes" not in json.dumps(before["works"])
    assert "undeclared" in before["legacy_coverage"]


def test_browse_reads_current_identity_without_regeneration(tmp_path):
    root = _fixture_root(tmp_path)
    path = next((root / "library/works").glob("*/work.json"))
    work = json.loads(path.read_text(encoding="utf-8"))
    work["title"] = "Updated | title"
    path.write_text(json.dumps(work), encoding="utf-8")
    report = library_browse_snapshot(root)
    assert report["works"][0]["title"] == "Updated | title"
    assert "Updated \\| title" in render_markdown(report)


def test_missing_library_fails_closed(tmp_path):
    with pytest.raises(PipelineError):
        library_browse_snapshot(tmp_path)


def test_browse_cli_reports_missing_authority_as_failure(tmp_path, capsys):
    root = _fixture_root(tmp_path)
    for path in (root / "library/works").rglob("work.json"):
        path.write_text("invalid JSON", encoding="utf-8")
    assert main(["--root", str(root), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["issues"]


def test_metadata_report_default_ignores_legacy_catalog(tmp_path):
    from build.tools.report_library_metadata import build_report
    from tests.test_library_metadata_report import _root

    root = _root(tmp_path)
    before = build_report(root)
    catalog = root / "reports/publish/work_catalog.json"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text("invalid legacy JSON", encoding="utf-8")
    assert build_report(root) == before
    assert before["scope"]["declared_coverage"] == "complete"
    assert before["scope"]["historical_coverage"] == "unassessed"


def test_metadata_legacy_comparison_requires_explicit_paired_inputs(tmp_path):
    from build.tools.report_library_metadata import build_report
    from tests.test_library_metadata_report import _root

    root = _root(tmp_path)
    with pytest.raises(PipelineError, match="selected together"):
        build_report(root, legacy_catalog=root / "unselected-catalog.json")
