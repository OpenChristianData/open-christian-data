"""A known work avoids sibling scans without weakening corpus checks."""
from dataclasses import replace
import json

import pytest

from ocd_kernel.library import identities
from ocd_kernel.library._common import PipelineError
from tests.test_library_pipeline import _fixture_root, WORK_ID, EDITION_ID


def test_known_work_is_fully_resolved_without_global_discovery(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path)

    def reject_global(_root):
        raise AssertionError("single-work lookup must not scan siblings")

    monkeypatch.setattr(identities, "discover_library", reject_global)
    work, edition = identities.edition_by_id(root, EDITION_ID, work_id=WORK_ID)
    assert work.work_id == WORK_ID and edition.edition_id == EDITION_ID
    assert edition.path == work.path.parent / "forms" / edition.textual_form_id / "editions" / EDITION_ID / "master.tei.xml"


def test_unqualified_and_batch_lookups_still_validate_every_sibling(tmp_path):
    root = _fixture_root(tmp_path)
    sibling = root / "library/works/unrelated/work.json"
    sibling.parent.mkdir()
    sibling.write_text("invalid JSON", encoding="utf-8")
    assert identities.edition_by_id(root, EDITION_ID, work_id=WORK_ID)[0].work_id == WORK_ID
    with pytest.raises(PipelineError, match="JSON"):
        identities.edition_by_id(root, EDITION_ID)
    with identities.cached_edition_lookups():
        with pytest.raises(PipelineError, match="JSON"):
            identities.edition_by_id(root, EDITION_ID, work_id=WORK_ID)


def test_known_work_still_rejects_invalid_selected_acquisition(tmp_path):
    root = _fixture_root(tmp_path)
    acquisition = next((root / "library/works" / WORK_ID).glob("forms/*/editions/*/acquisitions/*.json"))
    value = json.loads(acquisition.read_bytes())
    value["edition_id"] = "wrong-edition"
    acquisition.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(PipelineError, match="edition"):
        identities.edition_by_id(root, EDITION_ID, work_id=WORK_ID)


@pytest.mark.parametrize("work_id", ["missing-work", "../outside"])
def test_known_work_cannot_fall_back_or_escape_root(tmp_path, work_id):
    with pytest.raises(PipelineError):
        identities.edition_by_id(_fixture_root(tmp_path), EDITION_ID, work_id=work_id)


def test_batch_keeps_global_edition_ambiguity_guard(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path)
    work = identities.discover_work(root, WORK_ID)
    duplicate = replace(work, work_id="other-work")
    monkeypatch.setattr(identities, "discover_library", lambda _root: (work, duplicate))
    with identities.cached_edition_lookups():
        with pytest.raises(PipelineError, match="ambiguous"):
            identities.edition_by_id(root, EDITION_ID, work_id=WORK_ID)


def test_changed_work_is_read_again_on_the_next_call(tmp_path):
    root = _fixture_root(tmp_path)
    first, _ = identities.edition_by_id(root, EDITION_ID, work_id=WORK_ID)
    value = json.loads(first.path.read_bytes())
    value["title"] = "Changed fixture title"
    first.path.write_text(json.dumps(value), encoding="utf-8")
    second, _ = identities.edition_by_id(root, EDITION_ID, work_id=WORK_ID)
    assert second.title == "Changed fixture title" and second.title != first.title
