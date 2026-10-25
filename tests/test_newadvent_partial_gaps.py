"""Unavailable source images remain readable, explicit gaps, never fake graphics."""
from copy import deepcopy

import pytest

from build.tei.newadvent_reconstruction import project_page
from build.tei.newadvent_oracle import verify_page
from tests.test_newadvent_reconstruction import page, validate, NS

URL = "https://www.newadvent.org/cathen/01001a.htm"
IMAGE = "https://www.newadvent.org/images/missing.gif"
SOURCE = page('<p>Before <img src="../images/missing.gif" alt="Source diagram"> after.</p>')


def test_named_reference_without_semicolon_is_not_silently_completed():
    source = page('<p>First &mdash; second &mdash third &amp fourth.</p>\n<p>Later &notit; &copy end.</p>')
    candidate, _ = project_page(source, URL, "entities")
    assert verify_page(source, URL, "entities", candidate)["status"] == "pass"
    assert "second &mdash third" in "".join(candidate.itertext())


def test_unavailable_image_requires_explicit_gap_and_preserves_alt():
    with pytest.raises(ValueError, match="image"):
        project_page(SOURCE, URL, "partial")
    candidate, _ = project_page(SOURCE, URL, "partial", unavailable_images={IMAGE: 404})
    assert verify_page(SOURCE, URL, "partial", candidate, unavailable_images={IMAGE: 404})["status"] == "pass"
    assert candidate.xpath('.//t:gap/@corresp', namespaces=NS) == [IMAGE]
    assert candidate.xpath('.//t:figDesc/text()', namespaces=NS) == ["Source diagram"]
    assert not candidate.xpath('.//t:graphic', namespaces=NS)
    validate(candidate)


@pytest.mark.parametrize("mutation", ["remove", "url", "status", "alt", "graphic"])
def test_unavailable_image_mutations_fail(mutation):
    candidate, _ = project_page(SOURCE, URL, "partial", unavailable_images={IMAGE: 404})
    changed = deepcopy(candidate)
    gap = changed.xpath('.//t:gap', namespaces=NS)[0]
    if mutation == "remove":
        gap.getparent().remove(gap)
    elif mutation == "url":
        gap.set("corresp", IMAGE + "?alternate")
    elif mutation == "status":
        gap[0].text = "Source image unavailable at acquisition (HTTP 410)."
    elif mutation == "alt":
        changed.xpath('.//t:figDesc', namespaces=NS)[0].text = "Invented diagram"
    else:
        gap.tag = "{http://www.tei-c.org/ns/1.0}graphic"
    with pytest.raises(ValueError):
        verify_page(SOURCE, URL, "partial", changed, unavailable_images={IMAGE: 404})
