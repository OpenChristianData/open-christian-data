"""Keep retained literary whitespace and source coordinates in native content."""
from copy import deepcopy
import xml.etree.ElementTree as ET
import pytest
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.native_content import project_content, readable_content
from ocd_kernel.projection.native_content_check import verify_content

NS = "http://www.tei-c.org/ns/1.0"
FRAGMENT = (f'<div xmlns="{NS}"><ab type="source-whitespace">'
    '<seg type="source-line" n="1">  </seg></ab>'
    '<list n="2"><item n="1"><label n="1">1.</label> Contents</item></list>'
    '<floatingText n="3"><body><p>Dedication.</p></body></floatingText></div>').encode()


def test_literary_carriers_preserve_structure_numbers_and_whitespace(monkeypatch):
    content = project_content(ET.fromstring(FRAGMENT))
    text = readable_content(content)
    assert " ".join(text.split()) == "1. Contents Dedication."
    blank, listing, letter = content["content"]
    assert blank["attributes"]["type"] == "source-whitespace"
    assert blank["content"][0]["content"] == [{"kind": "text", "text": "  "}]
    assert listing["attributes"]["number"] == "2"
    assert listing["content"][0]["content"][0]["attributes"]["number"] == "1"
    assert letter["attributes"]["number"] == "3"
    monkeypatch.setattr("ocd_kernel.projection.native_content.project_content",
                        lambda *args, **kwargs: pytest.fail("independent checker called producer"))
    assert verify_content(FRAGMENT, content, text) == []
    for mutation in ("block-type", "blank-text", "list-number", "label-number", "embedded-number", "attachment"):
        altered = deepcopy(content)
        blank, listing, letter = altered["content"]
        if mutation == "block-type":
            blank["attributes"]["type"] = "blank"
        elif mutation == "blank-text":
            blank["content"][0]["content"][0]["text"] = " "
        elif mutation == "list-number":
            listing["attributes"]["number"] = "200"
        elif mutation == "label-number":
            listing["content"][0]["content"][0]["attributes"]["number"] = "2"
        elif mutation == "embedded-number":
            letter["attributes"]["number"] = "300"
        else:
            altered["content"][0], altered["content"][2] = altered["content"][2], altered["content"][0]
        assert "native structure/text order or attributes differ from source" in verify_content(FRAGMENT, altered, text)


@pytest.mark.parametrize("tag", ["list", "label", "floatingText"])
def test_unknown_literary_attribute_fails_closed(tag):
    fragment = f'<{tag} xmlns="{NS}" n="1" invented="yes">word</{tag}>'.encode()
    with pytest.raises(PipelineError, match="unsupported native content attribute"):
        project_content(ET.fromstring(fragment))
    assert verify_content(fragment, {}, "word")


def test_unknown_source_block_type_still_fails_closed():
    fragment = f'<ab xmlns="{NS}" type="source-whitespace-invented"> </ab>'.encode()
    with pytest.raises(PipelineError, match="source block type"):
        project_content(ET.fromstring(fragment))
    assert verify_content(fragment, {}, "")


def test_numbered_illustration_placeholders_preserve_coordinates_and_empty_description(monkeypatch):
    fragment = (f'<div xmlns="{NS}"><figure type="source-illustration-placeholder" n="860">'
                '<figDesc/></figure><figure type="source-illustration-placeholder" n="867">'
                '<figDesc/></figure></div>').encode()
    content = project_content(ET.fromstring(fragment))
    text = readable_content(content)
    assert [n["attributes"]["number"] for n in content["content"]] == ["860", "867"]
    assert all(len(n["content"]) == 1 and n["content"][0]["kind"] == "figure-description"
               and n["content"][0]["content"] == [] for n in content["content"])
    monkeypatch.setattr("ocd_kernel.projection.native_content.project_content",
                        lambda *args, **kwargs: pytest.fail("independent checker called producer"))
    assert verify_content(fragment, content, text) == []
    for mutation in ("coordinate", "attachment", "invented-description"):
        altered = deepcopy(content)
        if mutation == "coordinate":
            altered["content"][0]["attributes"]["number"] = "861"
        elif mutation == "attachment":
            altered["content"].reverse()
        else:
            altered["content"][0]["content"][0]["content"] = [{"kind": "text", "text": "Invented image"}]
        assert verify_content(fragment, altered, text)


def test_unknown_figure_attribute_fails_closed():
    fragment = f'<figure xmlns="{NS}" n="860" invented="yes"><figDesc/></figure>'.encode()
    with pytest.raises(PipelineError, match="unsupported native content attribute"):
        project_content(ET.fromstring(fragment))
    assert verify_content(fragment, {}, "")
