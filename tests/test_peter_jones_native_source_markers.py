"""Bound the public mapping of the accepted 1860 electronic witness markers."""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.prose import _peter_jones_profile
from ocd_kernel.projection.native_content import (
    PETER_JONES_PROFILE, project_content, readable_content,
)
from ocd_kernel.projection.native_content_check import verify_content


MASTER_SHA = "ee67ac29066b35c6fc98252d5f1bbfa8988a94df53f0fd7d7cb11eaa09354039"
SOURCE = (
    '<div xmlns="http://www.tei-c.org/ns/1.0">'
    '<p>Before <milestone unit="unretained-media-reference" n="Grey line.png"/>'
    ' after <milestone unit="unexpanded-source-template" n="upe"/>'
    '<pb n="20"/><gap reason="blank" unit="page" extent="1"/></p>'
    '<milestone unit="source-rule"/></div>'
).encode("utf-8")


def test_source_markers_and_blank_page_keep_order_and_literal_meaning() -> None:
    content = project_content(ET.fromstring(SOURCE), source_profile=PETER_JONES_PROFILE)
    text = readable_content(content)
    assert verify_content(SOURCE, content, text, source_profile=PETER_JONES_PROFILE) == []
    paragraph = content["content"][0]
    assert [(node["kind"], node.get("attributes", {})) for node in paragraph["content"] if node["kind"] != "text"] == [
        ("source-marker", {"unit": "unretained-media-reference", "number": "Grey line.png"}),
        ("source-marker", {"unit": "unexpanded-source-template", "number": "upe"}),
        ("page-break", {"number": "20"}),
        ("gap", {"reason": "blank", "unit": "page", "extent": "1"}),
    ]
    assert content["content"][1] == {"kind": "horizontal-rule", "attributes": {"unit": "source-rule"}, "content": []}
    assert text == "Before  after"


@pytest.mark.parametrize("mutation", ["drop-media", "change-media", "change-template", "change-rule", "change-gap"])
def test_independent_checker_rejects_marker_loss_or_mutation(mutation: str) -> None:
    content = project_content(ET.fromstring(SOURCE), source_profile=PETER_JONES_PROFILE)
    text = readable_content(content)
    changed = copy.deepcopy(content)
    parts = changed["content"][0]["content"]
    if mutation == "drop-media":
        parts.pop(1)
    elif mutation == "change-media":
        parts[1]["attributes"]["number"] = "different.png"
    elif mutation == "change-template":
        parts[3]["attributes"]["unit"] = "invented-template"
    elif mutation == "change-rule":
        changed["content"][1]["attributes"]["unit"] = "separator"
    else:
        parts[-1]["attributes"]["extent"] = "2"
    assert "native structure/text order or attributes differ from source" in verify_content(
        SOURCE, changed, text, source_profile=PETER_JONES_PROFILE,
    )


def test_profile_fails_closed_for_unknown_markers_and_other_masters() -> None:
    with pytest.raises(PipelineError, match="unsupported native milestone unit"):
        project_content(ET.fromstring(SOURCE))
    changed_source = SOURCE.replace(b"unexpanded-source-template", b"invented-template")
    with pytest.raises(PipelineError, match="unsupported native milestone unit"):
        project_content(ET.fromstring(changed_source), source_profile=PETER_JONES_PROFILE)
    context = {
        "identity": {
            "work_id": "peter-jones-life-and-journals",
            "textual_form_id": "peter-jones-life-and-journals-wikisource-retained",
            "edition_id": "peter-jones-life-and-journals-wikisource-electronic",
        },
        "authority": {"master": {"sha256": MASTER_SHA}},
    }
    assert _peter_jones_profile(context) == PETER_JONES_PROFILE
    context["authority"]["master"]["sha256"] = "0" * 64
    with pytest.raises(PipelineError, match="requires review"):
        _peter_jones_profile(context)
