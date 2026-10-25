"""Retain source uncertainty as structure without inventing a corrected reading."""

from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.native_content import project_content, readable_content
from ocd_kernel.projection.native_content_check import verify_content


NS = "http://www.tei-c.org/ns/1.0"


def test_unclear_keeps_reading_attributes_and_inline_attachment(monkeypatch):
    fragment = (f'<p xmlns="{NS}">To <unclear reason="illegible" cert="low" '
                'resp="#transcriber" xml:lang="en">b<hi rend="italic">ea</hi>r</unclear> '
                'the pain.</p>').encode()
    content = project_content(ET.fromstring(fragment))
    text = readable_content(content)
    uncertain = content["content"][1]
    assert text == "To bear the pain."
    assert uncertain["kind"] == "uncertain-text"
    assert uncertain["attributes"] == {
        "reason": "illegible", "certainty": "low", "responsibility": "#transcriber", "language": "en",
    }
    assert [part["kind"] for part in uncertain["content"]] == ["text", "emphasis", "text"]
    monkeypatch.setattr("ocd_kernel.projection.native_content.project_content",
                        lambda *args, **kwargs: pytest.fail("checker called producer"))
    assert verify_content(fragment, content, text) == []
    for mutation in ("flatten", "reading", "certainty", "attachment"):
        altered = deepcopy(content)
        carrier = altered["content"][1]
        if mutation == "flatten":
            altered["content"][1] = {"kind": "text", "text": "bear"}
        elif mutation == "reading":
            carrier["content"][0]["text"] = "c"
        elif mutation == "certainty":
            carrier["attributes"]["certainty"] = "high"
        else:
            altered["content"][1], altered["content"][2] = altered["content"][2], altered["content"][1]
        assert "native structure/text order or attributes differ from source" in verify_content(fragment, altered, text)


def test_unknown_unclear_attribute_fails_closed():
    fragment = f'<p xmlns="{NS}"><unclear invented="yes">word</unclear></p>'.encode()
    with pytest.raises(PipelineError, match="unsupported native content attribute"):
        project_content(ET.fromstring(fragment))
    assert verify_content(fragment, {}, "word")


def test_baths_actual_source_unclear_readings_are_retained():
    source = Path(__file__).resolve().parents[1] / "raw/tcp/high-range/A47235/A47235.xml"
    root = ET.fromstring(source.read_bytes())
    readings = root.findall(f".//{{{NS}}}unclear")
    assert ["".join(node.itertext()) for node in readings] == ["bear", "that"]
    for node in readings:
        detached = deepcopy(node)
        detached.tail = None
        fragment = ET.tostring(detached, encoding="utf-8")
        content = project_content(node)
        text = readable_content(content)
        assert content["kind"] == "uncertain-text"
        assert text == node.text
        assert verify_content(fragment, content, text) == []
