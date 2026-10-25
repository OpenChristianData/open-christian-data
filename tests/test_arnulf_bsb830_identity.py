"""Focused checks for the Arnulf composite electronic witness."""

from __future__ import annotations

import pytest

from build.tools import install_arnulf_bsb830_identity as route


def test_current_title_and_source_scope_bind_both_parts() -> None:
    route._source_boundary()
    work = route._read(route.ROOT / route.WORK / "work.json")
    assert work["work_id"] == route.WORK_ID
    assert work["title"] == route.TITLE
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    acquired = (route.ROOT / route.WORK / "forms" / form["textual_form_id"] / "editions"
                / edition["edition_id"] / "acquisitions" / f"{edition['acquisition_ids'][0]}.json")
    scope = route._read(acquired)["source_scope"]
    assert route.START_ID in scope and route.TRACT_ID in scope and route.END_ID in scope


def test_source_boundary_rejects_wrong_source_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(route, "SOURCE_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="retained bsb830 XML changed"):
        route._source_boundary()
