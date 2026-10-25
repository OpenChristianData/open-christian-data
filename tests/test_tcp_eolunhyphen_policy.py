from __future__ import annotations

import xml.etree.ElementTree as ET

from ocd_kernel.projection.native_content import project_content, readable_content
from ocd_kernel.projection.native_content_check import verify_content


TEI = "http://www.tei-c.org/ns/1.0"


def test_tcp_eolunhyphen_default_mapping_is_preserved_and_independently_checked():
    source = (
        f'<div xmlns="{TEI}"><p>continues<g ref="char:EOLunhyphen"/>'
        "without a printed hyphen.</p></div>"
    ).encode("utf-8")

    content = project_content(ET.fromstring(source))
    rendered = readable_content(content)

    glyphs = [
        child
        for block in content["content"]
        for child in block["content"]
        if child["kind"] == "glyph"
    ]
    assert len(glyphs) == 1
    assert glyphs[0]["attributes"]["reference"] == "char:EOLunhyphen"
    assert glyphs[0]["content"] == []
    assert rendered == "continues{+}without a printed hyphen."
    assert verify_content(source, content, rendered) == []
    assert "readable text differs" in verify_content(
        source, content, rendered.replace("{+}", "", 1)
    )[0]


def test_label_type_is_retained_as_native_structure():
    source = f'<label xmlns="{TEI}" type="milestone">verse 2</label>'.encode("utf-8")

    content = project_content(ET.fromstring(source))
    rendered = readable_content(content)

    assert content["kind"] == "label"
    assert content["attributes"] == {"type": "milestone"}
    assert rendered == "verse 2"
    assert verify_content(source, content, rendered) == []
