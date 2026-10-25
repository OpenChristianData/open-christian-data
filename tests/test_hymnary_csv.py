"""Source-preserving Hymnary quoting and boundary tests."""
import pytest

from build.tei.hymnary_csv import read_rows


def test_mixed_quotes_preserve_literal_backslashes_and_all_byte_spans():
    content = b'\xef\xbb\xbfTitle,Text\n"A","Verf\\soehner\r\nSay ""Hope,\\" now"\n"B",last'
    rows = list(read_rows(content))
    assert [tuple(f.value for f in r.fields) for r in rows] == [
        ("Title", "Text"), ("A", 'Verf\\soehner\r\nSay "Hope,\\" now'), ("B", "last"),
    ]
    assert content[:3] + b"".join(content[r.start:r.end] for r in rows) == content
    assert rows[0].end == rows[1].start and rows[1].end == rows[2].start
    offsets = rows[1].fields[1].anomalous_quote_offsets
    assert len(offsets) == 1 and content[offsets[0] - 1:offsets[0] + 1] == b'\\"'


@pytest.mark.parametrize("content", [b'"unclosed', b'"closed"junk,next', b'bad"quote,x', b'x\ry', b'\xff,x'])
def test_unexplained_syntax_and_invalid_utf8_fail_closed(content):
    with pytest.raises((ValueError, UnicodeDecodeError)):
        list(read_rows(content))


def test_empty_fields_and_multiline_csv_have_exact_boundaries():
    content = b',"",\r\n"two\nlines",x,\n'
    rows = list(read_rows(content))
    assert [tuple(f.value for f in r.fields) for r in rows] == [("", "", ""), ("two\nlines", "x", "")]
    assert b"".join(content[r.start:r.end] for r in rows) == content


def test_literal_trailing_backslash_does_not_hide_a_valid_field_boundary():
    rows = list(read_rows(b'"literal\\",next\n'))
    assert tuple(f.value for f in rows[0].fields) == ("literal\\", "next")
    assert not rows[0].fields[0].anomalous_quote_offsets
