"""Readable preservation of source line endings and forbidden XML controls."""
from lxml import etree
import pytest

from build.tei.hymnary_text import append_source_text, character_declarations
from ocd_kernel.tei.writer import stamp_header
from ocd_kernel.tei.validate import validate_file


T = "{http://www.tei-c.org/ns/1.0}"


def test_source_lines_and_control_positions_survive_schema_valid_tei(tmp_path):
    original = 'First\r\n\r\nVerf\\söhner\t"quote"\x08middle\x0f\x10\nLast\r'
    root = etree.Element(T + "TEI", nsmap={None: T[1:-1]})
    header = stamp_header(title="Source cell fixture", author="", contributors=[], source_url="https://hymnary.org", source_sha256="a" * 64, print_source="CSV fixture", rights_statement="Unaccepted test fixture.")
    encoding = etree.SubElement(header, T + "encodingDesc")
    encoding.append(character_declarations())
    root.append(header)
    cell = etree.SubElement(etree.SubElement(etree.SubElement(root, T + "text"), T + "body"), T + "ab")
    append_source_text(cell, original)
    path = tmp_path / "source-cell.xml"
    path.write_bytes(etree.tostring(root, encoding="UTF-8", xml_declaration=True))
    assert validate_file(path) == []
    # Test-side inverse uses literal expected codepoints, not writer helpers.
    result = cell.text or ""
    controls = {"#hymnary-control-0008": "\x08", "#hymnary-control-000f": "\x0f", "#hymnary-control-0010": "\x10"}
    for node in cell:
        if node.tag == T + "lb":
            result += {"CRLF": "\r\n", "CR": "\r", "LF": "\n"}[node.get("n")]
        else:
            assert node.tag == T + "g"
            result += controls[node.get("ref")]
            assert "source control" in node.text
        result += node.tail or ""
    assert result == original


def test_unprofiled_control_fails_closed():
    with pytest.raises(ValueError, match="U\\+0001"):
        append_source_text(etree.Element(T + "ab"), "Unexpected\x01")
