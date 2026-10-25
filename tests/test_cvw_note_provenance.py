"""Atomic notes bind their actual source owner without flattening inference."""

import hashlib

import pytest

from cvw_app.bounded_tei_provenance import render_body_provenance
from cvw_app.renderer_nodes import MAX_PAGE_SCALARS, RendererError
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


def test_atomic_notes_keep_distinct_identity_and_existing_limitations(tmp_path):
    payload, output, proof = render(
        tmp_path, '<note xml:id="same"> Same </note>' * 2)
    assert output['nodes'] == [{'type': 'blockquote', 'text': 'Same'}] * 2
    assert output['limitations']
    first, second = [node.provenance.sources for node in proof.nodes]
    assert len(first) == len(second) == 1
    assert first != second
    assert [payload[s[0].locator.start:s[0].locator.end] for s in (first, second)] == [
        b'<note xml:id="same"> Same </note>'] * 2
    assert proof.pages == (proof.nodes,)


@pytest.mark.parametrize('note', ['<note/>', '<note> \n </note>'])
def test_blank_note_has_no_fabricated_emission(tmp_path, note):
    _, _, proof = render(tmp_path, note + '<p>Baseline</p>')
    assert len(proof.nodes) == len(proof.emissions) == 1


@pytest.mark.parametrize('content', [
    '<hi>Inline</hi>', 'Mixed<hi>inline</hi>tail', '<note>Nested</note>',
    '<p><hi>Block</hi></p>', 'Before<pb n="2"/>After', '<gap/>', '<hi/>',
    'Before<p>Block</p>', '<p>Block</p>After', '<p><p>Nested</p></p>',
    'Before<cit>Quote</cit>', '<cit>Quote</cit>After',
    '<cit><quote><hi>Nested</hi></quote></cit>', '<cit>Mixed<hi>Inline</hi></cit>',
    '<cit><pb/></cit>', '<cit><gap/></cit>',
    '<cit xmlns="urn:foreign">Foreign</cit>', '<p xmlns="urn:foreign">Foreign</p>',
])
def test_nonatomic_notes_reject_opt_in_even_when_empty(tmp_path, content):
    with pytest.raises(RendererError, match='childless plain note'):
        render(tmp_path, f'<note>{content}</note><p>Baseline</p>')


@pytest.mark.parametrize('body', [
    '<p>Before<note>Note</note>After</p>',
    '<note>Note</note>Unowned tail',
])
def test_surrounding_mixed_text_still_fails_closed(tmp_path, body):
    with pytest.raises(RendererError, match='construction identity'):
        render(tmp_path, body)


def test_split_atomic_note_retains_explicit_page_lineage(tmp_path):
    _, _, proof = render(tmp_path, '<note>' + 'word ' * MAX_PAGE_SCALARS + '</note>')
    original, = proof.nodes
    fragments = [node for page in proof.pages for node in page]
    assert len(fragments) > 1
    assert " ".join(node.document_node()["text"] for node in fragments) == original.document_node()["text"]
    assert all(node.provenance.derived_from == (original.provenance.occurrence,) for node in fragments)
    assert all(node.provenance.sources == original.provenance.sources for node in fragments)


def test_flat_paragraph_notes_bind_actual_owners_before_aggregation(tmp_path):
    note = '<note xml:id="same">\n<p>Same</p><p/><p>Same</p>\n</note>'
    payload, output, proof = render(tmp_path, note * 2)
    assert output['nodes'] == [{'type': 'blockquote', 'text': 'SameSame'}] * 2
    assert proof.pages == (proof.nodes,)
    first, second = [node.provenance.sources for node in proof.nodes]
    assert len(first) == len(second) == 4
    assert first != second
    for sources in (first, second):
        assert [payload[s.locator.start:s.locator.end] for s in sources] == [
            note.encode(), b'<p>Same</p>', b'<p/>', b'<p>Same</p>']


def test_blank_flat_note_has_no_fabricated_emission(tmp_path):
    _, _, proof = render(tmp_path, '<note><p/><p> </p></note><p>Baseline</p>')
    assert len(proof.nodes) == len(proof.emissions) == 1


def test_split_flat_note_retains_explicit_page_lineage(tmp_path):
    _, _, proof = render(tmp_path, '<note><p>' + 'word ' * MAX_PAGE_SCALARS + '</p></note>')
    original, = proof.nodes
    fragments = [node for page in proof.pages for node in page]
    assert len(fragments) > 1
    assert " ".join(node.document_node()["text"] for node in fragments) == original.document_node()["text"]
    assert all(node.provenance.derived_from == (original.provenance.occurrence,) for node in fragments)
    assert all(node.provenance.sources == original.provenance.sources for node in fragments)


@pytest.mark.parametrize('namespace', ['', ' xmlns="http://www.tei-c.org/ns/1.0"'])
def test_flat_note_citations_retain_each_parser_identity(tmp_path, namespace):
    note = f'<note{namespace} xml:id="same"><p>Same</p><cit>Same</cit><cit/></note>'
    payload, output, proof = render(tmp_path, note * 2)
    assert output['nodes'] == [{'type': 'blockquote', 'text': 'SameSame'}] * 2
    first, second = [node.provenance.sources for node in proof.nodes]
    assert len(first) == len(second) == 4
    assert set(first).isdisjoint(second)
    for sources in (first, second):
        assert [payload[s.locator.start:s.locator.end] for s in sources] == [
            note.encode(), b'<p>Same</p>', b'<cit>Same</cit>', b'<cit/>']
    assert proof.pages == (proof.nodes,)


def test_empty_note_citations_emit_nothing(tmp_path):
    _, _, proof = render(tmp_path, '<note><cit/><cit> </cit></note><p>Baseline</p>')
    assert len(proof.nodes) == len(proof.emissions) == 1


def test_split_note_citation_retains_explicit_page_lineage(tmp_path):
    _, _, proof = render(tmp_path, '<note><cit>' + 'word ' * MAX_PAGE_SCALARS + '</cit></note>')
    original, = proof.nodes
    fragments = [node for page in proof.pages for node in page]
    assert len(fragments) > 1
    assert " ".join(node.document_node()["text"] for node in fragments) == original.document_node()["text"]
    assert all(node.provenance.derived_from == (original.provenance.occurrence,) for node in fragments)
    assert all(node.provenance.sources == original.provenance.sources for node in fragments)
