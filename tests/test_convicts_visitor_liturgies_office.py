"""Focused source correspondence for N18328's opt-in liturgy offices."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.liturgies import (
    project_liturgies_document,
    verify_liturgies_document,
)
from ocd_kernel.projection.categories.liturgies_office import IDENTITY, PROFILE
from ocd_kernel.projection.categories import liturgies as liturgies_module
from ocd_kernel.projection.categories import prose as prose_module

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "library/works/convicts-visitor/integration/convicts-n18328-electronic-v1/candidate.tei.xml"
NS = "{http://www.tei-c.org/ns/1.0}"
KWARGS = {
    "identity": IDENTITY,
    "language": "en",
    "representation_revision": "convicts-n18328-electronic-agent-v1",
    "edition_title": "The Convicts Visitor",
    "projection_profile": PROFILE,
}


def _project(path: Path = CANDIDATE):
    return project_liturgies_document(path, **KWARGS)


def _kinds(node: dict) -> list[str]:
    return [node["kind"], *[kind for child in node.get("content", []) for kind in _kinds(child)]]


def test_three_complete_offices_and_ordered_shared_prelude():
    result = _project()
    rows, receipt = result["rows"], result["receipt"]
    assert [row["category"] for row in rows] == ["liturgies"] * 3
    assert [row["office_number"] for row in rows] == [1, 2, 3]
    assert [row["locator"]["office"] for row in rows] == [1, 2, 3]
    assert [[node["kind"] for node in row["structure"]] for row in rows] == [
        ["page-break", "heading", "division"], ["division"], ["division"]
    ]
    assert len(rows[0]["front_matter"]) == 2
    assert all("front_matter" not in row for row in rows[1:])
    assert [sum(_kinds(node).count("speech") for node in row["structure"]) for row in rows] == [23, 62, 30]
    assert [sum(_kinds(node).count("speaker") for node in row["structure"]) for row in rows] == [23, 62, 30]
    assert sum(_kinds(node).count("verse-line") for row in rows for node in row["structure"]) == 28
    assert sum(_kinds(node).count("glyph") for row in rows for node in row["structure"]) == 377
    assert sum(_kinds(node).count("glyph") for node in rows[0]["front_matter"]) == 10
    assert sum(_kinds(node).count("page-break") for row in rows for node in row["structure"]) == 85
    assert receipt["inventory"] == {
        "text_element_count": 1291,
        "represented_element_count": 1287,
        "speech_counts": [23, 62, 30],
    }
    assert receipt["shared_prelude"]["row_occurrences"] == 1
    assert verify_liturgies_document(CANDIDATE, rows, receipt, **KWARGS) == []


def test_checker_rejects_public_speaker_and_prelude_mutations():
    result = _project()
    rows = deepcopy(result["rows"])
    rows[0]["structure"][1]["content"][0]["text"] = "ALTERED OPENING"
    assert verify_liturgies_document(CANDIDATE, rows, result["receipt"], **KWARGS)
    rows = deepcopy(result["rows"])
    speech = next(node for node in rows[0]["structure"][2]["content"] if node["kind"] == "speech")
    speaker = next(node for node in speech["content"] if node["kind"] == "speaker")
    speaker["content"][0]["text"] = "Other role"
    assert verify_liturgies_document(CANDIDATE, rows, result["receipt"], **KWARGS)


def test_changed_office_number_fails_closed(tmp_path: Path):
    tree = ET.parse(CANDIDATE)
    office = tree.getroot().find(NS + "text/" + NS + "body/" + NS + "div/" + NS + "div")
    assert office is not None
    office.set("n", "9")
    changed = tmp_path / "changed.tei.xml"
    tree.write(changed, encoding="utf-8", xml_declaration=True)
    with pytest.raises(PipelineError, match="office 1 identity"):
        _project(changed)


@pytest.mark.parametrize("carrier", ["root-text", "header-tail", "text-text", "front-tail"])
def test_envelope_visible_text_fails_both_routes(tmp_path: Path, carrier: str):
    projected = _project()
    tree = ET.parse(CANDIDATE)
    root = tree.getroot()
    text = root.find(NS + "text")
    assert text is not None
    node, field = {
        "root-text": (root, "text"),
        "header-tail": (root.find(NS + "teiHeader"), "tail"),
        "text-text": (text, "text"),
        "front-tail": (text.find(NS + "front"), "tail"),
    }[carrier]
    assert node is not None
    setattr(node, field, (getattr(node, field) or "") + "UNACCOUNTED")
    changed = tmp_path / f"{carrier}.tei.xml"
    tree.write(changed, encoding="utf-8", xml_declaration=True)
    with pytest.raises(PipelineError, match="unassigned visible text"):
        _project(changed)
    assert any("unassigned visible text" in error for error in verify_liturgies_document(
        changed, projected["rows"], projected["receipt"], **KWARGS
    ))


def test_office_profile_is_explicit_and_service_route_stays_default():
    with pytest.raises(PipelineError, match="unsupported-visible"):
        project_liturgies_document(CANDIDATE, **{key: value for key, value in KWARGS.items() if key != "projection_profile"})
    with pytest.raises(PipelineError, match="exact profile"):
        project_liturgies_document(CANDIDATE, **{**KWARGS, "identity": {**IDENTITY, "work_id": "other-work"}})


@pytest.mark.parametrize("profile,expected", [(None, "absent"), ("unknown-office-profile", "unsupported")])
def test_accepted_convicts_profile_fails_closed(monkeypatch: pytest.MonkeyPatch, profile: str | None, expected: str):
    monkeypatch.setattr(liturgies_module, "_accepted_metadata", lambda root, acceptance_path: {
        "identity": {"work_id": "convicts-visitor"}, "root": ROOT, "acceptance": {}
    })
    monkeypatch.setattr(prose_module, "_accepted_projection_profile", lambda root, context: profile)
    with pytest.raises(PipelineError, match=f"convicts-visitor.*projection_profile.*{expected}"):
        liturgies_module.project_accepted_liturgies(ROOT, acceptance_path=CANDIDATE)
    errors = liturgies_module.verify_accepted_liturgies(
        ROOT, acceptance_path=CANDIDATE, rows=[], receipt={}
    )
    assert len(errors) == 1 and "convicts-visitor" in errors[0] and expected in errors[0]
