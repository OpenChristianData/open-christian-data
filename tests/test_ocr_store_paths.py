from pathlib import Path

from build.lib.paths import REPO_ROOT as PATHS_REPO_ROOT
from build.lib.ocr_store_paths import (
    CORPUS_COVERAGE_ROOT,
    RECONCILED_ROOT,
    REPORTS_ROOT,
    REPO_ROOT,
    S1_SIDECARS_ROOT,
    S2_RENDERINGS_ROOT,
    WCT_ROOT,
    corpus_coverage_root,
    reconciled_root,
    s1_sidecars_root,
    s2_renderings_root,
    wct_root,
)


def test_absolute_store_roots_are_under_reports() -> None:
    assert REPORTS_ROOT == REPO_ROOT / "reports"
    assert S1_SIDECARS_ROOT == REPO_ROOT / "reports" / "s1-sidecars"
    assert S2_RENDERINGS_ROOT == REPO_ROOT / "reports" / "s2-renderings"
    assert CORPUS_COVERAGE_ROOT == REPO_ROOT / "reports" / "corpus-coverage"
    assert WCT_ROOT == REPO_ROOT / "reports" / "wct"
    assert RECONCILED_ROOT == REPO_ROOT / "reports" / "reconciled"


def test_relative_store_helpers_resolve_against_repo_root_argument() -> None:
    repo_root = Path("/tmp/x")

    assert s1_sidecars_root(repo_root) == repo_root / "reports" / "s1-sidecars"
    assert s2_renderings_root(repo_root) == repo_root / "reports" / "s2-renderings"
    assert corpus_coverage_root(repo_root) == repo_root / "reports" / "corpus-coverage"
    assert wct_root(repo_root) == repo_root / "reports" / "wct"
    assert reconciled_root(repo_root) == repo_root / "reports" / "reconciled"


def test_repo_root_is_reexported_from_paths_module() -> None:
    assert REPO_ROOT is PATHS_REPO_ROOT
