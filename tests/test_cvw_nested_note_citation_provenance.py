"""Bounded note citations retain owners before atomic text aggregation."""

import pytest

from cvw_app.renderer_nodes import MAX_PAGE_SCALARS, RendererError
from tests.test_cvw_note_provenance import render


@pytest.mark.parametrize('namespace', ['', ' xmlns="http://www.tei-c.org/ns/1.0"'])
def test_note_citation_children_keep_distinct_exact_owners(tmp_path, namespace):
    citation = '<cit xml:id="same"><quote>Same</quote><bibl/><hi>Same</hi><ref/></cit>'
    note = f'<note{namespace}><p>Before</p>{citation}<cit/></note>'
    payload, output, proof = render(tmp_path, note * 2)
    assert output['nodes'] == [{'type': 'blockquote', 'text': 'BeforeSameSame'}] * 2
    first, second = [node.provenance.sources for node in proof.nodes]
    assert set(first).isdisjoint(second)
    for sources in (first, second):
        assert [payload[s.locator.start:s.locator.end] for s in sources] == [
            note.encode(), b'<p>Before</p>', citation.encode(),
            b'<quote>Same</quote>', b'<bibl/>', b'<hi>Same</hi>', b'<ref/>', b'<cit/>']
    assert proof.pages == (proof.nodes,)


@pytest.mark.parametrize('content', [
    '<quote><hi>deep</hi></quote>', 'Mixed<quote>quote</quote>',
    '<quote>quote</quote>tail', '<quote xmlns="urn:foreign">quote</quote>',
    '<p>paragraph</p>', '<pb/>', '<gap/>', '<note>nested</note>',
])
def test_unsupported_note_citation_shapes_still_reject(tmp_path, content):
    with pytest.raises(RendererError, match='childless plain note'):
        render(tmp_path, f'<note><cit>{content}</cit></note><p>Baseline</p>')


def test_empty_nested_citation_emits_no_invented_node(tmp_path):
    _, _, proof = render(tmp_path, '<note><cit><quote/><bibl> </bibl></cit></note><p>Base</p>')
    assert len(proof.nodes) == len(proof.emissions) == 1


def test_split_nested_citation_retains_explicit_page_lineage(tmp_path):
    _, _, proof = render(tmp_path, '<note><cit><quote>' + 'word ' * MAX_PAGE_SCALARS + '</quote></cit></note>')
    original, = proof.nodes
    fragments = [node for page in proof.pages for node in page]
    assert len(fragments) > 1
    assert " ".join(node.document_node()["text"] for node in fragments) == original.document_node()["text"]
    assert all(node.provenance.derived_from == (original.provenance.occurrence,) for node in fragments)
    assert all(node.provenance.sources == original.provenance.sources for node in fragments)
