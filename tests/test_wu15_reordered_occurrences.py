"""Bounded WU-15 proof for repeated Hymnary text across reordered contexts."""

from __future__ import annotations

import copy
from pathlib import Path
import xml.etree.ElementTree as ET

from ocd_kernel.projection.categories.hymns import (
    project_hymns_document,
    verify_hymns_document,
)


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "tests/fixtures/library-pipeline/categories/hymns/master.tei.xml"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
NS = {"t": TEI}
IDENTITY = {"work_id": "wu15-fixture-work", "textual_form_id": "wu15-fixture-form", "edition_id": "wu15-fixture-edition"}
CONTEXT = {"identity": IDENTITY, "language": "en", "representation_revision": "wu15-fixture-v1", "edition_title": "WU-15 reordered Hymnary fixture"}


def _fixture(tmp_path: Path, *, reordered: bool) -> Path:
    root = ET.parse(MASTER).getroot()
    body = root.find("t:text/t:body", NS)
    assert body is not None
    source_occurrence = body.find("t:div/t:div[@xml:id='occ-at-bethlehem']", {**NS, "xml": XML})
    assert source_occurrence is not None

    # These are structural fixture contexts, not durable source or composition keys.
    first_context = ET.Element(f"{{{TEI}}}div", {"type": "collection", f"{{{XML}}}id": "fixture-context-a"})
    ET.SubElement(first_context, f"{{{TEI}}}head").text = "Context A: The Service of Praise"
    first_context.append(copy.deepcopy(source_occurrence))
    second_context = ET.Element(f"{{{TEI}}}div", {"type": "collection", f"{{{XML}}}id": "fixture-context-b"})
    ET.SubElement(second_context, f"{{{TEI}}}head").text = "Context B: Hymnal for Church and Home"
    second_occurrence = copy.deepcopy(source_occurrence)
    # Reuse the second existing fixture occurrence locator; no new durable key is allocated.
    second_occurrence.set(f"{{{XML}}}id", "occ-babe-born")
    second_context.append(second_occurrence)
    body[:] = [second_context, first_context] if reordered else [first_context, second_context]

    path = tmp_path / ("reordered.xml" if reordered else "original.xml")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


def _project(path: Path) -> dict:
    return project_hymns_document(path, **CONTEXT)


def _by_occurrence(result: dict) -> dict[str, dict]:
    return {row["occurrence_id"]: row for row in result["rows"]}


def test_reordered_acquisition_preserves_repeated_text_and_explicit_locator_crosswalk(tmp_path: Path):
    original_path = _fixture(tmp_path, reordered=False)
    reordered_path = _fixture(tmp_path, reordered=True)
    original = _project(original_path)
    reordered = _project(reordered_path)

    old = _by_occurrence(original)
    new = _by_occurrence(reordered)
    assert len(old) == len(new) == 2
    assert len({row["occurrence_id"] for row in original["rows"]}) == 2
    assert [row["text"] for row in original["rows"]] == [row["text"] for row in original["rows"][::-1]]
    assert len({row["hymn_text_id"] for row in original["rows"]}) == 1
    assert len({row["hymn_text_id"] for row in reordered["rows"]}) == 1
    assert {row["hymn_text_id"] for row in original["rows"]} == {row["hymn_text_id"] for row in reordered["rows"]}
    assert {row["language"] for row in original["rows"]} == {"en"}
    assert {row["contributor"] for row in original["rows"]} == {"Clark, Luella"}

    crosswalk = {
        occurrence_id: {"old_locator": old[occurrence_id]["locator"], "new_locator": new[occurrence_id]["locator"]}
        for occurrence_id in old
    }
    assert [crosswalk[row["occurrence_id"]]["old_locator"]["occurrence"] for row in original["rows"]] == [1, 2]
    assert [crosswalk[row["occurrence_id"]]["new_locator"]["occurrence"] for row in reordered["rows"]] == [1, 2]
    assert crosswalk[original["rows"][0]["occurrence_id"]]["old_locator"]["part_titles"] == ["Context A: The Service of Praise"]
    assert crosswalk[original["rows"][0]["occurrence_id"]]["new_locator"]["part_titles"] == ["Context A: The Service of Praise"]
    assert crosswalk[original["rows"][0]["occurrence_id"]]["old_locator"]["divisions"][0]["order"] == 1
    assert crosswalk[original["rows"][0]["occurrence_id"]]["new_locator"]["divisions"][0]["order"] == 2
    assert crosswalk[original["rows"][1]["occurrence_id"]]["old_locator"]["divisions"][0]["order"] == 2
    assert crosswalk[original["rows"][1]["occurrence_id"]]["new_locator"]["divisions"][0]["order"] == 1
    assert verify_hymns_document(reordered_path, reordered["rows"], reordered["receipt"], **CONTEXT) == []

    wrong_mapping = copy.deepcopy(reordered["rows"])[::-1]
    errors = verify_hymns_document(reordered_path, wrong_mapping, reordered["receipt"], **CONTEXT)
    assert any("source correspondence" in error for error in errors)

    # The current hymn row contract has text identity, not an inferred composition grouping.
    assert not any("composition" in key for row in reordered["rows"] for key in row)
