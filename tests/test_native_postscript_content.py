from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.native_content import SCHEMA, project_content, readable_content
from ocd_kernel.projection.native_content_check import verify_content


TEI = "http://www.tei-c.org/ns/1.0"


def test_postscript_is_preserved_as_a_distinct_ordered_block():
    source = (
        f'<div xmlns="{TEI}"><p>Before.</p>'
        '<trailer>Editorial trailer.</trailer><closer>Closing.</closer>'
        '<postscript xml:id="afterword" xml:lang="la"><p>Postscript '
        '<q>quoted</q> <g ref="char:EOLhyphen"/> <bibl>citation</bibl>.</p></postscript>'
        '<p>After.</p></div>'
    ).encode("utf-8")

    content = project_content(ET.fromstring(source))
    text = readable_content(content)

    trailer, closer, postscript = content["content"][1:4]
    assert trailer["kind"] == "trailer"
    assert closer["kind"] == "closing"
    assert postscript["kind"] == "postscript"
    assert postscript["attributes"] == {"language": "la"}
    assert postscript["content"][0]["kind"] == "paragraph"
    paragraph = postscript["content"][0]
    assert [child["kind"] for child in paragraph["content"]] == [
        "text", "quotation", "text", "glyph", "text", "bibliographic-label", "text"
    ]
    assert text.index("Editorial trailer.") < text.index("Closing.")
    assert text.index("Closing.") < text.index("Postscript quoted {-} citation.")
    assert text.index("Postscript quoted {-} citation.") < text.index("After.")
    assert verify_content(source, content, text) == []

    reclassified_source = source.replace(b"postscript", b"trailer")
    errors = verify_content(reclassified_source, content, text)
    assert "native structure/text order or attributes differ from source" in errors


def test_postscript_rejects_unmapped_attributes():
    source = f'<postscript xmlns="{TEI}" rend="class:unknown"><p>Text.</p></postscript>'
    with pytest.raises(PipelineError, match="unsupported native content attribute"):
        project_content(ET.fromstring(source))


def test_postscript_kind_is_allowed_by_the_native_content_schema():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert "postscript" in schema["oneOf"][1]["properties"]["kind"]["enum"]
