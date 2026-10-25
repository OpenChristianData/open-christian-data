"""Independent Hymnary carrier, text and attachment rejection tests."""
import copy
import hashlib

from lxml import etree
import pytest

from build.tei.hymnary_reconstruction import _build
from build.tei.hymnary_oracle import _source_rows, _verify_rows


T = "{http://www.tei-c.org/ns/1.0}"


@pytest.fixture()
def witness():
    content = b'\xef\xbb\xbfTitle,Full text,Author name,Author birth,Author death,Year written,Hymnal title,Hymnal publication year\n"First","Line one\r\n\r\nVerf\\soehner\x08",Writer,1800,,1820,Book,1830\n"Second","Quote ""Hope,\\" remains",Other,,,,Other Book,1840\n'
    policy = {"csv_sha256": hashlib.sha256(content).hexdigest(), "columns": ["Title", "Full text", "Author name", "Author birth", "Author death", "Year written", "Hymnal title", "Hymnal publication year"], "data_rows": 2, "anomalous_quote_byte_offsets": [content.index(b'\\"') + 1], "xml_controls": {"U+0008": 1, "U+000F": 0, "U+0010": 0}}
    config = {"title": "Fixture", "source_url": "https://hymnary.org", "source_edition": "Test retained CSV"}
    tei, accounting, unresolved = _build(content, policy, config)
    return content, policy, tei, accounting, unresolved


def test_independent_source_boundaries_and_tei_agree(witness):
    source, policy, tei, accounting, unresolved = witness
    assert _verify_rows(source, tei, accounting, policy) == unresolved
    rows = list(_source_rows(source))
    assert source[:3] + b"".join(source[start:end] for start, end, _ in rows) == source
    assert rows[1][2][1]["value"] == "Line one\r\n\r\nVerf\\soehner\x08"


@pytest.mark.parametrize("mutation", ["omit", "duplicate", "reorder", "invent", "attachment", "control", "line-ending", "metadata-label", "accounting", "header-invent"])
def test_independent_reader_rejects_semantic_corruption(witness, mutation):
    source, policy, tei, accounting, _ = witness
    tree = etree.fromstring(tei)
    body = tree.find(T + "text/" + T + "body")
    if mutation == "omit":
        body.remove(body[0])
    elif mutation == "duplicate":
        body.append(copy.deepcopy(body[0]))
    elif mutation == "reorder":
        body.insert(0, body[-1])
    elif mutation == "invent":
        body[0][1].text = "Invented text"
    elif mutation == "attachment":
        body[0][0].set("corresp", body[1][0].get("corresp"))
    elif mutation == "control":
        body[0][1].find(T + "g").set("ref", "#hymnary-control-0010")
    elif mutation == "line-ending":
        body[0][1].find(T + "lb").set("n", "LF")
    elif mutation == "metadata-label":
        body[0][2][0][0].text = "Wrong label"
    elif mutation == "header-invent":
        tree.find(T + "text/" + T + "front/" + T + "div/" + T + "head").set("n", "Invented header semantics")
    else:
        accounting["rows"][0]["fields"][0]["start"] += 1
    with pytest.raises(ValueError, match="LIB-087"):
        _verify_rows(source, etree.tostring(tree), accounting, policy)
