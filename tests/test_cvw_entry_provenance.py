"""Plain dictionary field ownership follows actual renderer selection."""

import hashlib
from xml.etree import ElementTree

import pytest

from cvw_app.bounded_tei_provenance import render_body_provenance
from cvw_app.renderer_nodes import RendererError
from cvw_app.tei_renderer import render_tei


def render(tmp_path, body):
    payload = f'<TEI><text><body>{body}</body></text></TEI>'.encode()
    master = tmp_path / 'master.xml'
    master.write_bytes(payload)
    normal = render_tei('application/tei+xml', payload.decode())
    output, proof = render_body_provenance(
        master, expected_sha256=hashlib.sha256(payload).hexdigest(),
        master_member='master.xml')
    assert output == normal
    return payload, output, proof


@pytest.mark.parametrize('tag', ['entry', 'entryFree'])
def test_flat_fields_keep_selected_owners_and_duplicate_identity(tmp_path, tag):
    payload, output, proof = render(tmp_path, f'<{tag}><orth xml:id="same">Same</orth>'
                                   '<def/><def xml:id="same">Same</def>'
                                   f'</{tag}>')
    assert output['nodes'] == [{'type': 'paragraph', 'text': 'Same Same'}]
    sources = proof.nodes[0].provenance.sources
    assert len(sources) == 3
    assert [payload[s.locator.start:s.locator.end] for s in sources[1:]] == [
        b'<orth xml:id="same">Same</orth>', b'<def xml:id="same">Same</def>']
    assert sources[1].locator.ordinal != sources[2].locator.ordinal
    assert proof.pages == (proof.nodes,)


@pytest.mark.parametrize('tag', ['entry', 'entryFree'])
def test_childless_entry_and_identical_occurrences(tmp_path, tag):
    _, output, proof = render(tmp_path, f'<{tag}> Same </{tag}>' * 2)
    assert output['nodes'][0] == output['nodes'][1]
    assert len(proof.nodes[0].provenance.sources) == 1
    assert proof.nodes[0].provenance.sources != proof.nodes[1].provenance.sources


@pytest.mark.parametrize('body', ['<entry/>', '<entry><orth/><def> </def></entry>'])
def test_empty_entries_emit_no_fabricated_owner(tmp_path, body):
    _, _, proof = render(tmp_path, body + '<p>Baseline</p>')
    assert len(proof.nodes) == len(proof.emissions) == 1


@pytest.mark.parametrize('body', [
    '<entry>Mixed<orth>Word</orth></entry>',
    '<entry><orth>Word</orth>tail</entry>',
    '<entry><orth><hi>Word</hi></orth></entry>',
    '<entry><form><orth>Word</orth>tail</form></entry>',
    '<entry><form>Mixed<orth>Word</orth></form></entry>',
    '<entry><sense><sense><def>Meaning</def></sense></sense></entry>',
    '<entry><form><def>Meaning</def></form></entry>',
    '<entry><entry><orth>Word</orth></entry></entry>',
    '<entry><def>Meaning<note>Note</note></def></entry>',
    '<entry><def>Meaning</def><gram>noun</gram></entry>',
])
def test_unsupported_entries_fail_closed_but_default_renders(tmp_path, body):
    with pytest.raises(RendererError, match='plain entry or flat plain fields'):
        render(tmp_path, body)


def test_foreign_entry_owner_is_rejected(tmp_path, monkeypatch):
    import cvw_app.tei_renderer as renderer

    monkeypatch.setattr(renderer, '_tei_plain_entry_sources',
                        lambda element: (ElementTree.Element('def'),))
    with pytest.raises(RendererError, match='parser or fragment identity'):
        render(tmp_path, '<entry><def>Meaning</def></entry>')


@pytest.mark.parametrize('tag', ['entry', 'entryFree'])
def test_nested_plain_fields_bind_wrappers_and_selected_occurrences(tmp_path, tag):
    payload, output, proof = render(
        tmp_path, f'<{tag}><form><orth/><orth xml:id="same">Same</orth></form>'
        '<def>Direct</def><sense><def xml:id="same">Same</def><def> </def></sense>'
        f'<form/><sense><def/></sense></{tag}>')
    assert output['nodes'] == [{'type': 'paragraph', 'text': 'Same Direct Same'}]
    sources = proof.nodes[0].provenance.sources
    assert [payload[s.locator.start:s.locator.end] for s in sources[1:]] == [
        b'<form><orth/><orth xml:id="same">Same</orth></form>',
        b'<orth xml:id="same">Same</orth>', b'<def>Direct</def>',
        b'<sense><def xml:id="same">Same</def><def> </def></sense>',
        b'<def xml:id="same">Same</def>']
    assert len({s.locator.ordinal for s in sources}) == 6
    assert proof.pages == (proof.nodes,)


@pytest.mark.parametrize('tag', ['entry', 'entryFree'])
def test_empty_nested_fields_emit_no_owner(tmp_path, tag):
    _, output, proof = render(
        tmp_path, f'<{tag}><form><orth/></form><sense><def> </def></sense>'
        f'</{tag}><p>Baseline</p>')
    assert output['nodes'] == [{'type': 'paragraph', 'text': 'Baseline'}]
    assert len(proof.emissions) == 1
