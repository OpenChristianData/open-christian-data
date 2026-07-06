"""Single source of truth for the NSH OCR working-store roots under reports/."""

from __future__ import annotations

from pathlib import Path

from build.lib.paths import REPO_ROOT


def s1_sidecars_root(repo_root: Path = REPO_ROOT) -> Path:
    return Path(repo_root) / "reports" / "s1-sidecars"


def s2_renderings_root(repo_root: Path = REPO_ROOT) -> Path:
    return Path(repo_root) / "reports" / "s2-renderings"


def corpus_coverage_root(repo_root: Path = REPO_ROOT) -> Path:
    return Path(repo_root) / "reports" / "corpus-coverage"


def wct_root(repo_root: Path = REPO_ROOT) -> Path:
    return Path(repo_root) / "reports" / "wct"


def reconciled_root(repo_root: Path = REPO_ROOT) -> Path:
    return Path(repo_root) / "reports" / "reconciled"


REPORTS_ROOT = REPO_ROOT / "reports"
S1_SIDECARS_ROOT = s1_sidecars_root()
S2_RENDERINGS_ROOT = s2_renderings_root()
CORPUS_COVERAGE_ROOT = corpus_coverage_root()
WCT_ROOT = wct_root()
RECONCILED_ROOT = reconciled_root()

__all__ = (
    "CORPUS_COVERAGE_ROOT",
    "RECONCILED_ROOT",
    "REPORTS_ROOT",
    "REPO_ROOT",
    "S1_SIDECARS_ROOT",
    "S2_RENDERINGS_ROOT",
    "WCT_ROOT",
    "corpus_coverage_root",
    "reconciled_root",
    "s1_sidecars_root",
    "s2_renderings_root",
    "wct_root",
)
