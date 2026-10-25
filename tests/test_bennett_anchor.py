"""Focused Bennett Jeremiah II source anchor projection boundary."""

from copy import deepcopy
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.native_content import NS, XML, project_content
from ocd_kernel.projection.native_content_check import observe_content
from ocd_kernel.release.public_allowlist import _scan


ANNOTATION = (
    "urn:ccel:source-attribute:id:i-p1.1 "
    "urn:ccel:source-attribute:shape:rect "
    "urn:ccel:source-attribute:%7Bhttp%3A%2F%2Fwww.w3.org%2FXML%2F1998%2Fnamespace%7Dlink:simple"
)


def _anchor() -> ET.Element:
    return ET.Element(NS + "anchor", {
        XML + "id": "bennett-expositorjer2-i-p1.1",
        "type": "source-anchor", "ana": ANNOTATION,
    })


def test_bennett_anchor_retains_source_identity_shape_and_link_semantics() -> None:
    anchor = _anchor()
    original = deepcopy(anchor.attrib)
    projected = project_content(anchor)
    assert anchor.attrib == original
    assert projected["kind"] == "anchor"
    assert projected["attributes"] == {
        "type": "source-anchor",
        "source_attributes": {"id": "i-p1.1", "shape": "rect", "xml:link": "simple"},
    }
    assert _scan(projected, "Bennett anchor") == []
    observed, readable = observe_content(ET.tostring(anchor, encoding="utf-8"))
    assert observed == projected
    assert readable == ""


@pytest.mark.parametrize("mutation", ["id", "shape", "link", "order", "tei-id", "type"])
def test_bennett_anchor_rejects_changed_source_semantics(mutation: str) -> None:
    anchor = _anchor()
    if mutation == "id":
        anchor.set("ana", ANNOTATION.replace("id:i-p1.1", "id:i-p1.2"))
    elif mutation == "shape":
        anchor.set("ana", ANNOTATION.replace("shape:rect", "shape:circle"))
    elif mutation == "link":
        anchor.set("ana", ANNOTATION.replace("link:simple", "link:extended"))
    elif mutation == "order":
        anchor.set("ana", " ".join(reversed(ANNOTATION.split())))
    elif mutation == "tei-id":
        anchor.set(XML + "id", "bennett-expositorjer2-i-p1.2")
    else:
        anchor.set("type", "source-link")
    with pytest.raises(PipelineError, match="Bennett Jeremiah II source anchor differs"):
        project_content(anchor)
    with pytest.raises(ValueError, match="observed Bennett Jeremiah II anchor"):
        observe_content(ET.tostring(anchor, encoding="utf-8"))
