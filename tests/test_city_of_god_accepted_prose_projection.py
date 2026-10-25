from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
import xml.etree.ElementTree as ET

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.projection.native_content import project_content, readable_content
from ocd_kernel.projection.native_content_check import observe_content


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "library/works/augustine-city-of-god"
TEI = "http://www.tei-c.org/ns/1.0"
CASES = (
    ("dods", "augustine-city-of-god-dods-retained-en", "augustine-city-of-god-dods-retained-electronic", ("1", "2")),
    ("npnf", "augustine-city-of-god-npnf-retained-en", "augustine-city-of-god-npnf-retained-electronic", ("2",)),
)


def markers(value: object) -> list[dict]:
    found: list[dict] = []
    def visit(node: object) -> None:
        if isinstance(node, dict):
            if node.get("kind") == "source-marker" and node.get("attributes", {}).get("unit") == "physical-volume":
                found.append(node)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(value)
    return found


@pytest.mark.parametrize("_short,form,edition,numbers", CASES)
def test_installed_city_prose_preserves_volume_markers_and_independently_verifies(
    _short: str, form: str, edition: str, numbers: tuple[str, ...]
) -> None:
    edition_root = WORK / "forms" / form / "editions" / edition
    master = edition_root / "master.tei.xml"
    acceptance = edition_root / "acceptance.json"
    if not master.is_file() or not acceptance.is_file():
        pytest.skip("City electronic acceptance is not installed")
    record = json.loads(acceptance.read_bytes())
    work = json.loads((WORK / "work.json").read_bytes())
    edition_record = next(item for text_form in work["textual_forms"] for item in text_form["editions"] if item["edition_id"] == edition)
    identity = {key: record["identity"][key] for key in ("work_id", "textual_form_id", "edition_id")}
    args = dict(identity=identity, language=edition_record["language"],
                representation_revision=record["representation_revision"]["id"],
                edition_title=edition_record["title"], _allow_acceptance_metadata=True,
                category="prose")
    projection = project_document(master, **args)
    assert projection["rows"]
    assert verify_document(master, projection["rows"], projection["receipt"], **args) == []
    physical = markers(projection["rows"])
    assert tuple(item["attributes"]["number"] for item in physical) == numbers
    assert all(item["attributes"]["unit"] == "physical-volume" for item in physical)

    mutated = deepcopy(projection["rows"])
    markers(mutated)[0]["attributes"]["number"] = "99"
    assert verify_document(master, mutated, projection["receipt"], **args)


def test_physical_volume_marker_is_structural_and_unknown_units_fail_closed() -> None:
    xml = f'<milestone xmlns="{TEI}" unit="physical-volume" n="2"/>'
    projected = project_content(ET.fromstring(xml))
    observed, readable = observe_content(xml.encode())
    assert projected == observed
    assert projected == {"kind": "source-marker", "attributes": {"unit": "physical-volume", "number": "2"}, "content": []}
    assert readable_content(projected) == readable == ""
    unknown = xml.replace("physical-volume", "unattested-unit")
    with pytest.raises(PipelineError, match="unsupported native milestone unit"):
        project_content(ET.fromstring(unknown))
    with pytest.raises(ValueError, match="unsupported native milestone unit"):
        observe_content(unknown.encode())
