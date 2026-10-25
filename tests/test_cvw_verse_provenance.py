"""Bounded plain verse ownership is captured before line aggregation."""

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
    expected = render_tei('application/tei+xml', payload.decode())
    output, proof = render_body_provenance(
        master, expected_sha256=hashlib.sha256(payload).hexdigest(),
        master_member='master.xml')
    assert output == expected
    return payload, output, proof


@pytest.mark.parametrize('attributes,text', [
    ('', '  first\n second  '),
    (' xml:space="preserve"', '  first\n second  '),
    (' xml:space="default"', 'first\tsecond'),
])
def test_plain_line_preserves_output_and_exact_owner(tmp_path, attributes, text):
    payload, output, proof = render(tmp_path, f'<l{attributes}>{text}</l>')
    node = proof.nodes[0]
    assert node.document_node() == output['nodes'][0]
    assert len(node.provenance.sources) == 1
    source = node.provenance.sources[0].locator
    assert payload[source.start:source.end] == f'<l{attributes}>{text}</l>'.encode()
    assert proof.pages == ((node,),)


@pytest.mark.parametrize('namespace', ['', ' xmlns="http://www.tei-c.org/ns/1.0"'])
@pytest.mark.parametrize('stanza', [False, True])
def test_plain_line_highlights_bind_exact_occurrences(tmp_path, namespace, stanza):
    line = f'<l{namespace}>Same<hi>dup</hi><lb/>Same<hi>dup</hi></l>'
    body = f'<lg{namespace}>{line * 2}</lg>' if stanza else line * 2
    payload, output, proof = render(tmp_path, body)
    text = 'Samedup\nSamedup'
    assert output['nodes'] == [
        {'type': 'preformatted', 'text': f'{text}\n{text}' if stanza else text}
    ] * (1 if stanza else 2)
    source_groups = ([proof.nodes[0].provenance.sources] if stanza else
                     [node.provenance.sources for node in proof.nodes])
    for sources in source_groups:
        expected = ([body.encode()] if stanza else []) + [
            line.encode(), b'<hi>dup</hi>', b'<lb/>', b'<hi>dup</hi>'
        ] * (2 if stanza else 1)
        assert [payload[source.locator.start:source.locator.end]
                for source in sources] == expected
        highlights = [source.locator for source in sources
                      if source.locator.expanded_name.endswith('hi')]
        assert len(highlights) == (4 if stanza else 2)
        assert len({source.ordinal for source in highlights}) == len(highlights)
    if not stanza:
        assert set(source_groups[0]).isdisjoint(source_groups[1])


@pytest.mark.parametrize('namespace', ['', ' xmlns="http://www.tei-c.org/ns/1.0"'])
@pytest.mark.parametrize('stanza', [False, True])
def test_plain_line_segments_bind_exact_occurrences(tmp_path, namespace, stanza):
    line = f'<l{namespace}>\n <seg>Same</seg>\n <hi>word</hi><lb break="no"/><seg>Same</seg></l>'
    body = f'<lg{namespace}>{line * 2}</lg>' if stanza else line * 2
    payload, output, proof = render(tmp_path, body)
    expected_text = 'Same wordSame'
    assert output['nodes'] == [
        {'type': 'preformatted',
         'text': f'{expected_text}\n{expected_text}' if stanza else expected_text}
    ] * (1 if stanza else 2)
    source_groups = ([proof.nodes[0].provenance.sources] if stanza else
                     [node.provenance.sources for node in proof.nodes])
    for sources in source_groups:
        expected = ([body.encode()] if stanza else []) + [
            line.encode(), b'<seg>Same</seg>', b'<hi>word</hi>',
            b'<lb break="no"/>', b'<seg>Same</seg>'
        ] * (2 if stanza else 1)
        assert [payload[source.locator.start:source.locator.end]
                for source in sources] == expected
        segments = [source.locator for source in sources
                    if source.locator.expanded_name.endswith('seg')]
        assert len(segments) == (4 if stanza else 2)
        assert len({source.ordinal for source in segments}) == len(segments)
    if not stanza:
        assert set(source_groups[0]).isdisjoint(source_groups[1])


def test_stanza_aggregates_duplicate_and_empty_line_owners(tmp_path):
    payload, output, proof = render(
        tmp_path, '<lg>\n<l xml:id="same">Same</l>\n<l/>\n'
        '<l xml:id="same">Same</l>\n</lg>')
    assert output['nodes'] == [{'type': 'preformatted', 'text': 'Same\n\nSame'}]
    sources = proof.nodes[0].provenance.sources
    assert len(sources) == 4
    assert [payload[s.locator.start:s.locator.end] for s in sources[1:]] == [
        b'<l xml:id="same">Same</l>', b'<l/>', b'<l xml:id="same">Same</l>']
    assert sources[1].locator.ordinal != sources[3].locator.ordinal


def test_identical_stanzas_keep_distinct_occurrences(tmp_path):
    _, _, proof = render(tmp_path, '<lg><l>Same</l></lg>' * 2)
    first, second = proof.nodes
    assert first.document_node() == second.document_node()
    assert first.provenance.sources != second.provenance.sources
    assert proof.pages[0] == proof.nodes


@pytest.mark.parametrize('body', ['<l/>', '<lg/>', '<lg><l/><l> </l></lg>'])
def test_empty_plain_verse_has_no_fabricated_output(tmp_path, body):
    _, output, proof = render(tmp_path, body + '<p>Baseline</p>')
    assert output['nodes'] == [{'type': 'paragraph', 'text': 'Baseline'}]
    assert len(proof.nodes) == 1
    assert len(proof.emissions) == 1


@pytest.mark.parametrize('body', [
    '<l>A<hi><hi>B</hi></hi></l>', '<l>A<hi><note>N</note></hi></l>',
    '<l>A<hi xmlns="urn:foreign">B</hi></l>',
    '<l>A<seg><seg>B</seg></seg></l>', '<l>A<seg><note>B</note></seg></l>',
    '<l>A<seg xmlns="urn:foreign">B</seg></l>',
    '<l>A<seg type="json-null">B</seg></l>',
    '<l xmlns="urn:foreign">A<hi>B</hi></l>',
    '<l>A<note>N</note>B</l>',
    '<lg>Intro<l>A</l></lg>', '<lg><l>A</l>tail</lg>',
    '<lg><lg><l>A</l></lg></lg>',
    '<lg><l>A</l><pb>Hidden</pb></lg>',
    '<lg><l>A</l><pb><hi/></pb></lg>',
    '<lg><l>A</l><pb xmlns="urn:foreign"/></lg>',
    '<lg><l>A</l><pb/>tail</lg>',
    '<lg><l>A</l><gap/></lg>', '<lg><l>A</l>\u00a0</lg>',
    '<l>A<lb>Hidden</lb>B</l>', '<l>A<lb><hi/></lb>B</l>',
    '<l>A<lb xmlns="urn:foreign"/>B</l>', '<l>A<pb/>B</l>',
    '<l>A<gap/>B</l>', '<l>A<l>B</l></l>', '<l>A<lg><l>B</l></lg></l>',
    '<lg><l>A<lb><hi/></lb>B</l></lg>',
    '<lg><l>A<lb xmlns="urn:foreign"/>B</l></lg>',
    '<lg><l>A<lb>Hidden</lb>B</l></lg>',
    '<lg><l>A<lb/>B</l>tail</lg>',
])
def test_mixed_verse_fails_closed_without_changing_default(tmp_path, body):
    with pytest.raises(RendererError, match='plain line or flat plain stanza'):
        render(tmp_path, body)


@pytest.mark.parametrize('namespace', ['', ' xmlns="http://www.tei-c.org/ns/1.0"'])
def test_line_markers_bind_exact_occurrences_before_projection(tmp_path, namespace):
    line = (
        f'<l{namespace} xml:id="same" xml:space="preserve">'
        'First<lb xml:id="same"/>  Second<lb break="no"/>joined<lb/><lb/>End</l>'
    )
    payload, output, proof = render(tmp_path, line * 2)
    assert output['nodes'] == [
        {'type': 'preformatted', 'text': 'First\n  Secondjoined\n\nEnd'}] * 2
    first, second = [node.provenance.sources for node in proof.nodes]
    assert set(first).isdisjoint(second)
    for sources in (first, second):
        assert [payload[s.locator.start:s.locator.end] for s in sources] == [
            line.encode(), b'<lb xml:id="same"/>', b'<lb break="no"/>', b'<lb/>', b'<lb/>']
    assert proof.pages == (proof.nodes,)


def test_line_markers_preserve_inherited_space_and_formatting(tmp_path):
    _, output, _ = render(
        tmp_path, '<div xml:space="preserve"><l>A\n B<lb/>C</l>'
        '<l xml:space="default">A\n B<lb/>C</l></div>')
    assert [node['text'] for node in output['nodes']] == ['A\n B\nC', 'A B\nC']


def test_empty_line_markers_have_no_fabricated_emission(tmp_path):
    _, _, proof = render(tmp_path, '<l><lb/><lb break="no"/></l><p>Base</p>')
    assert len(proof.nodes) == len(proof.emissions) == 1


@pytest.mark.parametrize('namespace', ['', ' xmlns="http://www.tei-c.org/ns/1.0"'])
def test_stanza_line_markers_bind_every_line_and_separator_owner(tmp_path, namespace):
    stanza = (
        f'<lg{namespace} xml:space="preserve"><l xml:id="same">A<lb/>B</l>'
        '<l><lb/><lb break="no"/></l><l xml:id="same">A<lb break="no"/>B</l></lg>'
    )
    payload, output, proof = render(tmp_path, stanza * 2)
    assert output['nodes'] == [{'type': 'preformatted', 'text': 'A\nB\n\nAB'}] * 2
    first, second = [node.provenance.sources for node in proof.nodes]
    assert set(first).isdisjoint(second)
    for sources in (first, second):
        assert [payload[s.locator.start:s.locator.end] for s in sources] == [
            stanza.encode(), b'<l xml:id="same">A<lb/>B</l>', b'<lb/>',
            b'<l><lb/><lb break="no"/></l>', b'<lb/>', b'<lb break="no"/>',
            b'<l xml:id="same">A<lb break="no"/>B</l>', b'<lb break="no"/>']
    assert proof.pages == (proof.nodes,)


def test_marker_only_stanza_creates_no_emission(tmp_path):
    _, _, proof = render(tmp_path, '<lg><l><lb/></l><l/></lg><p>Base</p>')
    assert len(proof.nodes) == len(proof.emissions) == 1


def test_unbound_verse_source_is_rejected(tmp_path, monkeypatch):
    import cvw_app.tei_renderer as renderer

    monkeypatch.setattr(renderer, '_tei_plain_verse_sources',
                        lambda element: (ElementTree.Element('l'),))
    with pytest.raises(RendererError, match='parser or fragment identity'):
        render(tmp_path, '<l>A</l>')


def test_unexpected_multiple_blocks_reject_ambiguous_ownership(tmp_path, monkeypatch):
    import cvw_app.tei_renderer as renderer

    monkeypatch.setattr(renderer, '_tei_verse_blocks',
                        lambda *args, **kwargs: [('preformatted', 'A')] * 2)
    with pytest.raises(RendererError, match='ambiguous block ownership'):
        render(tmp_path, '<l>A</l>')


@pytest.mark.parametrize('namespace', ['', ' xmlns="http://www.tei-c.org/ns/1.0"'])
def test_stanza_page_markers_keep_exact_label_and_separator_owners(tmp_path, namespace):
    stanza = (f'<lg{namespace}><l xml:id="same">A<lb/>B</l>'
              '<pb xml:id="same" n=" 12 "/><l/><pb/><l>C</l></lg>')
    payload, output, proof = render(tmp_path, stanza * 2)
    expected = 'A\nB\n[Page break: 12]\n\n[Page break]\nC'
    assert output['nodes'] == [{'type': 'preformatted', 'text': expected}] * 2
    first, second = [node.provenance.sources for node in proof.nodes]
    assert set(first).isdisjoint(second)
    for sources in (first, second):
        assert [payload[source.locator.start:source.locator.end] for source in sources] == [
            stanza.encode(), b'<l xml:id="same">A<lb/>B</l>', b'<lb/>',
            b'<pb xml:id="same" n=" 12 "/>', b'<l/>', b'<pb/>', b'<l>C</l>']
    assert proof.pages == (proof.nodes,)


def test_page_marker_only_stanza_retains_existing_visible_label(tmp_path):
    payload, output, proof = render(tmp_path, '<lg><pb/><pb n="iv"/></lg>')
    assert output['nodes'] == [{'type': 'paragraph', 'text': '[Page break] [Page break: iv]'}]
    assert [payload[source.locator.start:source.locator.end]
            for source in proof.nodes[0].provenance.sources
            if source.locator.expanded_name == 'pb'] == [b'<pb/>', b'<pb n="iv"/>']


def test_stanza_marker_crosswalk_uses_actual_parser_occurrence(tmp_path):
    from cvw_app.bounded_tei_crosswalk import render_contribution_crosswalk
    payload = b'<TEI><text><body><lg><l>A</l><pb/><pb/><l>B</l></lg></body></text></TEI>'
    master = tmp_path / 'crosswalk.xml'
    master.write_bytes(payload)
    output, crosswalk = render_contribution_crosswalk(
        master, expected_sha256=hashlib.sha256(payload).hexdigest(), master_member='master.xml')
    assert output == render_tei('application/tei+xml', payload.decode())
    markers = [record for record in crosswalk.records if record.source.locator.expanded_name == 'pb']
    assert len(markers) == 2
    assert markers[0].source.locator != markers[1].source.locator
    for marker in markers:
        assert payload[marker.source.locator.start:marker.source.locator.end] == b'<pb/>'
        assert {item.surface for item in marker.outputs} == {'body', 'page', 'served'}
