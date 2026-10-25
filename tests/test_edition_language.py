"""Language precedence must agree across declared parents and consumers."""
from copy import deepcopy
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import discover_work, resolve_edition_language
from ocd_kernel.library.views import library_browse_snapshot
from ocd_kernel.projection.categories.prose import _language
from ocd_kernel.release.assemble import _edition_language
from build.tools.export_library_metadata import export_metadata
from tests.test_library_records import root, write


def language_records():
    return {"textual_forms": [
        {"textual_form_id": "english", "language": "en", "editions": [
            {"edition_id": "english-edition"}]},
        {"textual_form_id": "french", "language": "fr", "editions": [
            {"edition_id": "french-edition"}]},
    ]}


def test_language_uses_exact_parent_instead_of_first_form():
    work = language_records()
    edition = work["textual_forms"][1]["editions"][0]
    assert resolve_edition_language(work, edition, "french") == "fr"


def test_explicit_edition_language_overrides_different_form_language():
    work = language_records()
    edition = work["textual_forms"][1]["editions"][0]
    edition["language"] = "la"
    assert resolve_edition_language(work, edition, "french") == "la"


def test_missing_language_does_not_borrow_other_form_or_work_language():
    work = language_records()
    work["language"] = "en"  # Retired work-level fallback must stay unused.
    del work["textual_forms"][1]["language"]
    edition = work["textual_forms"][1]["editions"][0]
    assert resolve_edition_language(work, edition, "french") is None


def test_missing_sidecar_language_preserves_prose_tei_fallback_and_failure():
    work = language_records()
    del work["textual_forms"][1]["language"]
    edition = work["textual_forms"][1]["editions"][0]
    requested = resolve_edition_language(work, edition, "french")
    assert _language(ET.fromstring('<TEI xml:lang="la"/>'), requested) == "la"
    with pytest.raises(PipelineError, match="language must be declared"):
        _language(ET.fromstring("<TEI/>"), requested)


@pytest.mark.parametrize("value", [None, 0, " "])
def test_unsupported_explicit_value_cannot_silently_inherit(value):
    work = language_records()
    edition = work["textual_forms"][1]["editions"][0]
    edition["language"] = value
    assert resolve_edition_language(work, edition, "french") is None


@pytest.mark.parametrize("parent", ["english", "missing"])
def test_wrong_parent_is_rejected_even_with_explicit_edition_language(parent):
    work = language_records()
    edition = work["textual_forms"][1]["editions"][0]
    edition["language"] = "la"
    with pytest.raises(PipelineError, match="textual form|parent mismatch"):
        resolve_edition_language(work, edition, parent)


def test_ambiguous_parent_and_detached_edition_are_rejected():
    work = language_records()
    edition = work["textual_forms"][1]["editions"][0]
    detached = dict(edition, language="la")
    with pytest.raises(PipelineError, match="parent mismatch"):
        resolve_edition_language(work, detached, "french")
    work["textual_forms"].append(deepcopy(work["textual_forms"][1]))
    with pytest.raises(PipelineError, match="one declared textual form"):
        resolve_edition_language(work, edition, "french")


@pytest.mark.parametrize("explicit,expected", [(None, "fr"), ("la", "la")])
def test_form_language_and_edition_override_agree_in_release_browse_export(
    root: Path, explicit: str | None, expected: str,
):
    path = root / "library/works/alpha/work.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    edition = record["textual_forms"][1]["editions"][0]
    if explicit is None:
        del edition["language"]
    else:
        edition["language"] = explicit
    write(path, record)

    work = discover_work(root, "alpha")
    selected = next(e for e in work.editions if e.edition_id == "second")
    assert _edition_language(work, selected) == expected
    for snapshot in (library_browse_snapshot(root), export_metadata(root)):
        edition = next(e for e in snapshot["works"][0]["editions"]
                       if e["edition_id"] == "second")
        assert edition["language"]["value"] == expected
