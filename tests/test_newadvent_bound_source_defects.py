"""Exact retained malformed-source dispositions and independent mutations."""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from build.tei.newadvent_oracle import _LexicalRegions, _read_document, envelope_for_page, verify_page
from build.tei.newadvent_reconstruction import project_page
from tests.test_newadvent_reconstruction import page, validate

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw/newadvent/catholic-encyclopedia-complete-acquisition-20260911"
NS = {"t": "http://www.tei-c.org/ns/1.0"}


def retained(relative, digest):
    source = RAW / relative
    if not source.is_file():
        pytest.skip("Exact retained New Advent witness unavailable")
    payload = source.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == digest
    return payload


def test_exact_dives_wrapper_accounting_and_source_drift():
    payload = retained("batch-0012/000007.html", "af04fb0b822990f1621c36cfbce2dd64eb78a14f41a412e13dadee4f5ee5e349")
    url = "https://www.newadvent.org/cathen/05048a.htm"
    envelope = envelope_for_page(payload, url, "source")
    wrapper = [row for row in envelope["body_regions"] if row["disposition"] == "exact-retained-malformed-wrapper-transparent-no-metadata-adoption"]
    assert len(wrapper) == 1 and wrapper[0]["source_tag"] == 'description="latin'
    assert wrapper[0]["source_attributes"]["16:19-31\")"] == ""
    relocated = [row for row in envelope["body_regions"] if row["disposition"] == "browser-relocated-source-head-carrier-no-metadata-adoption"]
    assert [row["source_tag"] for row in relocated] == ["meta", "link", "link"]
    candidate, _ = project_page(payload, url, "test")
    assert verify_page(payload, url, "test", candidate)["status"] == "pass"
    validate(candidate)
    with pytest.raises(ValueError, match="source drift"):
        envelope_for_page(payload + b" ", url, "source")


def test_numeric_reference_independent_reader_preserves_control():
    source = '<div id="springfield2">&#23tude; &amp; &#x80;</div>'
    reader = _LexicalRegions(source)
    reader.feed(source)
    reader.close()
    assert "".join(reader.parts["springfield2"]) == "\x17tude; & \u20ac"


def test_exact_numeric_defect_readable_g_and_mutations():
    payload = retained("batch-0102/000053.html", "0f381049ef0067dd6c14a92de8bb4dfdc98f81786a3f7e468bd02acf9ad5b01a")
    url = "https://www.newadvent.org/cathen/13100a.htm"
    assert b"&#23tude;" in payload
    candidate, _ = project_page(payload, url, "test")
    glyphs = candidate.xpath('.//t:g', namespaces=NS)
    assert len(glyphs) == 1
    assert glyphs[0].text == "\u2417" and glyphs[0].get("ref") == "urn:unicode:U+0017"
    assert glyphs[0].tail.startswith("tude;")
    assert verify_page(payload, url, "test", candidate)["status"] == "pass"
    validate(deepcopy(candidate))
    for mutation in ("glyph", "ref", "remove", "modernize"):
        changed = deepcopy(candidate)
        glyph = changed.xpath('.//t:g', namespaces=NS)[0]
        if mutation == "glyph":
            glyph.text = "X"
        elif mutation == "ref":
            glyph.set("ref", "urn:unicode:U+0018")
        elif mutation == "modernize":
            glyph.text = "É"
        else:
            glyph.getparent().remove(glyph)
        with pytest.raises(ValueError):
            verify_page(payload, url, "test", changed)
    for reader in (_read_document, lambda raw: project_page(raw, url, "test")):
        with pytest.raises(ValueError, match="source drift"):
            reader(payload + b" ")


@pytest.mark.parametrize("reference", ["&#23;", "&#24;", "&#x17;"])
def test_unbound_controls_fail_closed(reference):
    payload = page("<p>before" + reference + "after</p>")
    with pytest.raises(ValueError, match="control"):
        project_page(payload, "https://www.newadvent.org/cathen/test.htm", "test")
    with pytest.raises(ValueError, match="control"):
        _read_document(payload)
