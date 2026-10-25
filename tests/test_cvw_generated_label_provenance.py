"""Generated reader labels bind the TEI element that requested them."""

import hashlib

from cvw_app.bounded_tei_provenance import render_body_provenance
from cvw_app.tei_renderer import render_tei


def render(tmp_path, body):
    payload = f"<TEI><text><body>{body}</body></text></TEI>".encode()
    master = tmp_path / "master.xml"
    master.write_bytes(payload)
    output, proof = render_body_provenance(
        master,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        master_member="master.xml",
    )
    assert output == render_tei("application/tei+xml", payload.decode())
    return payload, output, proof


def test_generated_chapter_label_uses_parent_div_identity(tmp_path):
    payload, output, proof = render(
        tmp_path,
        '<div type="chapter" n="23" xml:id="chapter-23"><p>Before.</p></div>',
    )
    assert [node["text"] for node in output["nodes"]] == [
        "[Chapter: 23]",
        "Before.",
    ]
    source = proof.nodes[0].provenance.sources
    assert len(source) == 1
    assert payload[source[0].locator.start:source[0].locator.end] == (
        b'<div type="chapter" n="23" xml:id="chapter-23"><p>Before.</p></div>'
    )


def test_generated_empty_verse_label_uses_verse_identity(tmp_path):
    payload, output, proof = render(
        tmp_path,
        '<div type="chapter" n="1"><ab type="verse" n="14"/></div>',
    )
    assert [node["text"] for node in output["nodes"]] == [
        "[Chapter: 1]",
        "[Verse 14: empty text]",
    ]
    chapter_source = proof.nodes[0].provenance.sources
    verse_source = proof.nodes[1].provenance.sources
    assert len(chapter_source) == len(verse_source) == 1
    assert payload[chapter_source[0].locator.start:chapter_source[0].locator.end] == (
        b'<div type="chapter" n="1"><ab type="verse" n="14"/></div>'
    )
    assert payload[verse_source[0].locator.start:verse_source[0].locator.end] == (
        b'<ab type="verse" n="14"/>'
    )
