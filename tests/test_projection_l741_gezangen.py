"""Source-bound checks for the first text-only L741 projection."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from build.tools.stage_l741_portable_candidate import STAGED_CANDIDATE, stage
from ocd_kernel.projection.categories.l741_gezangen import (
    project_l741_document,
    verify_l741_document,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "raw/dbnl/evangelische-gezangen-1806/evangelische-gezangen-1806.xml"
IDENTITY = {
    "work_id": "evangelische-gezangen-1806",
    "textual_form_id": "evangelische-gezangen-1806-dbnl-retained",
    "edition_id": "evangelische-gezangen-1806-dbnl-electronic",
}
CONTEXT = {
    "retained_path": SOURCE,
    "identity": IDENTITY,
    "language": "nl",
    "representation_revision": "l741-projection-test",
    "edition_title": "DBNL retained XML electronic witness",
}


@pytest.fixture(scope="module")
def master(tmp_path_factory: pytest.TempPathFactory) -> Path:
    destination = tmp_path_factory.mktemp("l741-p5") / "s"
    stage(destination)
    return destination / STAGED_CANDIDATE


def test_l741_rows_match_retained_hymns_and_explicit_exclusions(master: Path) -> None:
    projected = project_l741_document(master, **CONTEXT)
    rows, receipt = projected["rows"], projected["receipt"]
    assert len(rows) == 192
    assert [row["sequence"] for row in rows] == list(range(1, 193))
    assert [len(row["sections"]) for row in rows].count(6) == 1
    assert len(rows[45]["sections"]) == 6
    assert [section["label"] for section in rows[45]["sections"]] == [
        "Eerste afdeeling.", "Tweede afdeeling.", "Derde afdeeling.",
        "Vierde afdeeling.", "Vijfde afdeeling.", "Zesde afdeeling.",
    ]
    assert all(row["stanzas"] == [stanza for section in row["sections"] for stanza in section["stanzas"]] for row in rows)
    assert all(row["segments"] == [{"kind": "stanza", **stanza} for stanza in row["stanzas"]] for row in rows)
    assert receipt["source_disposition"]["excluded_score_gifs"] == 68
    assert receipt["source_disposition"]["excluded_index_tables"] == 26
    assert verify_l741_document(master, rows, receipt, **CONTEXT) == []


def test_l741_independent_source_check_rejects_missing_section(master: Path) -> None:
    projected = project_l741_document(master, **CONTEXT)
    rows = copy.deepcopy(projected["rows"])
    rows[45]["sections"].pop(2)
    assert any("six-part hymn XLVI" in error for error in verify_l741_document(
        master, rows, projected["receipt"], **CONTEXT
    ))
