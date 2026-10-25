"""Focused tests for native text-envelope whitespace declarations."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from lxml import etree
import pytest

from ocd_kernel.library._common import PipelineError


from ocd_kernel.projection.categories import native_documents as NATIVE

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


@pytest.mark.parametrize(("factory", "error_type"), [(ET.Element, PipelineError), (etree.Element, ValueError)])
def test_preserve_is_accounted_without_changing_source_text(factory, error_type) -> None:
    node = factory("text", attrib={XML_SPACE: "preserve"})
    node.text = "  literal retained text\n"
    allowed = {"existing"}
    NATIVE._allow_preserved_text_space(node, allowed, error_type=error_type)
    assert allowed == {"existing", XML_SPACE}
    assert node.attrib == {XML_SPACE: "preserve"}
    assert node.text == "  literal retained text\n"


@pytest.mark.parametrize("factory", [ET.Element, etree.Element])
def test_absent_space_does_not_expand_envelope(factory) -> None:
    node = factory("text")
    allowed = {"existing"}
    NATIVE._allow_preserved_text_space(node, allowed, error_type=ValueError)
    assert allowed == {"existing"}


@pytest.mark.parametrize("value", ["default", "collapse", "Preserve", ""])
def test_unsupported_text_space_values_fail_closed(value: str) -> None:
    node = ET.Element("text", attrib={XML_SPACE: value})
    allowed = {"existing"}
    with pytest.raises(PipelineError, match="unsupported native text whitespace declaration"):
        NATIVE._allow_preserved_text_space(node, allowed, error_type=PipelineError)
    assert allowed == {"existing"}
