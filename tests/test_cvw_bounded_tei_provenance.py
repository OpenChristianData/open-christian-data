"""Explicit provenance is independent of IDs, text, and output node fields."""

from dataclasses import replace
import hashlib
from types import MappingProxyType
from xml.etree import ElementTree

import pytest

from cvw_app.bounded_tei_provenance import (
    PROVENANCE_VERSION, ProvenanceBuilder, render_outline_provenance,
)
from cvw_app.bounded_xml_index import parse_indexed_master
from cvw_app.renderer_nodes import RendererError, _node


@pytest.fixture
def parsed(tmp_path):
    master = tmp_path / 'master.xml'
    master.write_bytes(b'<TEI><text><body><p xml:id="same">identical</p>'
                       b'<p xml:id="same">identical</p></body></text></TEI>')
    sha = hashlib.sha256(master.read_bytes()).hexdigest()
    return parse_indexed_master(master, expected_sha256=sha, renderer_version='renderer-v1')


def builder(parsed, **kwargs):
    options = dict(master_member='master.tei.xml', expected_sha256=parsed.index.master_sha256,
                   expected_renderer_version='renderer-v1')
    options.update(kwargs)
    return ProvenanceBuilder(parsed, **options)


def test_duplicate_id_and_identical_text_keep_explicit_distinct_sources(parsed):
    provenance = builder(parsed)
    first, second = parsed.root.iter('p')
    a = provenance.emit(_node('paragraph', 'identical'), sources=[first])
    b = provenance.emit(_node('paragraph', 'identical'), sources=[second])
    assert a.document_node() == b.document_node()
    assert a.provenance.occurrence != b.provenance.occurrence
    assert a.provenance.sources[0].locator is parsed.source_elements[first]
    assert b.provenance.sources[0].locator is parsed.source_elements[second]
    assert a.provenance.sources != b.provenance.sources
    source = a.provenance.sources[0]
    assert source.master_member == 'master.tei.xml'
    assert source.master_sha256 == parsed.index.master_sha256
    assert source.index_integrity == parsed.index.integrity_sha256
    assert source.renderer_version == 'renderer-v1'
    assert a.provenance.version == PROVENANCE_VERSION


def test_split_occurrences_preserve_one_source_with_explicit_lineage(parsed):
    provenance = builder(parsed)
    original = provenance.emit(_node('paragraph', 'identical'), sources=[next(parsed.root.iter('p'))])
    first = provenance.emit(_node('paragraph', 'iden'), derived_from=[original])
    second = provenance.emit(_node('paragraph', 'tical'), derived_from=[original])
    assert first.provenance.sources == second.provenance.sources == original.provenance.sources
    assert first.provenance.derived_from == second.provenance.derived_from == (original.provenance.occurrence,)
    assert len({item.provenance.occurrence for item in [original, first, second]}) == 3


def test_aggregation_and_wrapper_union_only_explicit_contributors(parsed):
    provenance = builder(parsed)
    first, second = parsed.root.iter('p')
    a = provenance.emit(_node('paragraph', 'identical'), sources=[first])
    b = provenance.emit(_node('paragraph', 'identical'), sources=[second])
    wrapper = provenance.emit(_node('blockquote', '', children=[a.document_node(), b.document_node()]),
                              derived_from=[b, a, b], sources=[first])
    assert wrapper.provenance.sources == a.provenance.sources + b.provenance.sources
    assert wrapper.provenance.derived_from == (b.provenance.occurrence, a.provenance.occurrence)
    assert wrapper.provenance.no_source_reason is None


def test_source_free_emission_and_derived_replacement_require_explicit_reason(parsed):
    provenance = builder(parsed)
    original = provenance.emit(_node('paragraph', '[generated control]'),
                               no_source_reason='Generated viewer control')
    assert original.provenance.sources == ()
    assert original.provenance.no_source_reason == 'Generated viewer control'
    with pytest.raises(RendererError, match='neither source'):
        provenance.emit(_node('paragraph', '[replacement]'), derived_from=[original])
    replacement = provenance.emit(_node('paragraph', '[replacement]'), derived_from=[original],
                                  no_source_reason='Replacement viewer control')
    assert replacement.provenance.derived_from == (original.provenance.occurrence,)
    assert replacement.provenance.sources == ()
    assert replacement.provenance.occurrence == 1


@pytest.mark.parametrize('reason', [None, '', '   ', 5])
def test_missing_source_is_not_silently_synthetic(parsed, reason):
    with pytest.raises(RendererError):
        builder(parsed).emit(_node('paragraph', 'identical'), no_source_reason=reason)


def test_source_backed_node_cannot_claim_no_source(parsed):
    with pytest.raises(RendererError, match='cannot claim no source'):
        builder(parsed).emit(_node('paragraph', 'label'), sources=[next(parsed.root.iter('p'))],
                             no_source_reason='generated')


def test_copied_source_element_has_no_implicit_binding(parsed):
    copied = ElementTree.fromstring(ElementTree.tostring(next(parsed.root.iter('p'))))
    with pytest.raises(RendererError, match='no parser identity'):
        builder(parsed).emit(_node('paragraph', 'identical'), sources=[copied])


def test_foreign_and_forged_emissions_are_not_accepted_by_value(parsed):
    first, second = builder(parsed), builder(parsed)
    original = first.emit(_node('paragraph', 'text'), sources=[next(parsed.root.iter('p'))])
    for receiver, parent in [(second, original), (first, replace(original))]:
        with pytest.raises(RendererError, match='not an emission'):
            receiver.emit(_node('paragraph', 'copy'), derived_from=[parent])


def test_export_and_input_mutations_do_not_change_emission_or_lineage(parsed):
    provenance = builder(parsed)
    node = _node('paragraph', 'original')
    emitted = provenance.emit(node, sources=[next(parsed.root.iter('p'))])
    node['text'] = 'changed input'
    exported = emitted.document_node()
    assert exported == _node('paragraph', 'original')
    exported['text'] = 'changed export'
    assert emitted.document_node() == _node('paragraph', 'original')
    assert set(emitted.document_node()) == {'type', 'text'}


def test_invalid_node_returns_no_partial_occurrence(parsed):
    provenance = builder(parsed)
    source = next(parsed.root.iter('p'))
    with pytest.raises(RendererError):
        provenance.emit({'type': 'invented', 'text': 'text'}, sources=[source])
    assert provenance.emit(_node('paragraph', 'text'), sources=[source]).provenance.occurrence == 0


@pytest.mark.parametrize('field,value', [('master_sha256', '0' * 64),
                                       ('renderer_version', 'old'),
                                       ('indexer_version', 'old'),
                                       ('integrity_sha256', '0' * 64)])
def test_index_drift_fails_closed(parsed, field, value):
    with pytest.raises(RendererError, match='binding mismatch'):
        builder(replace(parsed, index=replace(parsed.index, **{field: value})))


def test_unbound_locator_and_missing_root_fail_closed(parsed):
    element = next(parsed.root.iter('p'))
    mapping = dict(parsed.source_elements)
    mapping[element] = replace(mapping[element])
    with pytest.raises(RendererError, match='unbound source locator'):
        builder(replace(parsed, source_elements=MappingProxyType(mapping)))
    mapping = dict(parsed.source_elements)
    del mapping[parsed.root]
    with pytest.raises(RendererError, match='no indexed root'):
        builder(replace(parsed, source_elements=MappingProxyType(mapping)))


@pytest.mark.parametrize('member', ['', '.', '../master.xml', '/master.xml',
                                   'a/../master.xml', 'a//master.xml', 'C:/master.xml',
                                   'a\\master.xml'])
def test_ambiguous_member_identity_fails_closed(parsed, member):
    with pytest.raises(RendererError, match='canonical relative'):
        builder(parsed, master_member=member)


def render_file(tmp_path, exact):
    master = tmp_path / 'outline.xml'
    master.write_bytes(exact.encode('utf-8'))
    sha = hashlib.sha256(master.read_bytes()).hexdigest()
    return master, sha, render_outline_provenance(master, expected_sha256=sha,
                                                 master_member='master.tei.xml')


@pytest.mark.parametrize('exact', [
    '<TEI><text><body><div xml:id="same"><head>One</head><p>body</p></div>'
    '<div xml:id="same"><head>Two</head><p>body</p></div></body></text></TEI>',
    '<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:space="preserve"><text><body>'
    '<div xml:id="outer"><head>Outer <hi rend="italic">label</hi></head>'
    '<div xml:id="inner"><head>Inner</head><p>body<note>note</note></p></div>'
    '</div></body></text></TEI>',
    '<TEI><text><body><p xml:id="one" rend="source-h2">Source heading</p>'
    '<ab type="source-heading" subtype="h3" corresp="two">Other heading</ab>'
    '<p xml:id="three">Paragraph location</p></body></text></TEI>',
    '<teiCorpus><TEI><text><body><div xml:id="same"><head>One</head></div>'
    '</body></text></TEI><TEI><text><body><div xml:id="same"><head>Two</head>'
    '</div></body></text></TEI></teiCorpus>',
    '<TEI><text><body><p>Body without an outline</p></body></text></TEI>',
])
def test_integrated_outline_preserves_existing_renderer_output(tmp_path, exact):
    from cvw_app.review_renderers import DEFAULT_RENDERER_REGISTRY

    master, sha, (rendered, bindings) = render_file(tmp_path, exact)
    normal, supported = DEFAULT_RENDERER_REGISTRY.render('tei-reader', 'application/tei+xml', exact)
    assert supported and rendered == normal
    assert list(bindings) == [item['location'] for item in rendered['outline']]
    for location, occurrence in bindings.items():
        assert occurrence.document_node()['location'] == location
        assert len(occurrence.provenance.sources) == 1
        source = occurrence.provenance.sources[0]
        assert source.master_sha256 == sha
        payload = master.read_bytes()[source.locator.start:source.locator.end]
        assert payload.startswith((b'<head', b'<p', b'<ab'))
    with pytest.raises(TypeError):
        bindings['invented'] = None


def test_actual_duplicate_allocations_bind_distinct_retained_heading_ranges(tmp_path):
    exact = ('<TEI><text><body><div xml:id="same"><head>Identical</head></div>'
             '<div xml:id="same"><head>Identical</head></div></body></text></TEI>')
    _, _, (rendered, bindings) = render_file(tmp_path, exact)
    assert len(bindings) == 2
    first, second = bindings.values()
    assert first.document_node()['text'] == second.document_node()['text']
    assert first.provenance.sources[0].locator.ordinal != second.provenance.sources[0].locator.ordinal
    assert first.provenance.sources[0].locator.start != second.provenance.sources[0].locator.start
    assert list(bindings)[0] == 'same'
    assert list(bindings)[1] != 'same'
    assert list(bindings) == [item['location'] for item in rendered['outline']]


@pytest.mark.parametrize('body', [
    '<p xml:id="paragraph">before<quote type="block">quoted</quote>after</p>',
    '<quote type="block" xml:id="paragraph">quoted <hi>inline</hi></quote>',
    '<quote type="block">before <hi>inline</hi><p xml:id="inner">body</p>after</quote>',
    '<list><item>before<label>Label</label><p xml:id="inner">body</p>after</item></list>',
    '<p xml:id="paragraph">before<quote type="block"><p xml:id="nested">nested'
    '<quote type="block">deep</quote>tail</p></quote>after</p>',
])
def test_explicit_fragment_bindings_preserve_renderer_and_source_owner(tmp_path, body):
    from cvw_app.review_renderers import DEFAULT_RENDERER_REGISTRY

    exact = '<TEI><text><body>' + body + '</body></text></TEI>'
    master, _, (rendered, bindings) = render_file(tmp_path, exact)
    normal, supported = DEFAULT_RENDERER_REGISTRY.render('tei-reader', 'application/tei+xml', exact)
    assert supported and rendered == normal
    assert bool(bindings) == bool(normal["outline"])
    for emitted in bindings.values():
        source = emitted.provenance.sources[0]
        payload = master.read_bytes()[source.locator.start:source.locator.end]
        assert b'xml:id=' in payload
    if body.startswith('<p xml:id="paragraph">'):
        first, last = list(bindings.values())[0], list(bindings.values())[-1]
        assert first.provenance.sources == last.provenance.sources
        assert first.provenance.occurrence != last.provenance.occurrence


def test_missing_fragment_callback_fails_closed(tmp_path, monkeypatch):
    from cvw_app import tei_renderer

    original = tei_renderer._render_tei_root

    def omit_fragments(root, **kwargs):
        kwargs.pop('_on_fragment')
        return original(root, **kwargs)

    monkeypatch.setattr(tei_renderer, '_render_tei_root', omit_fragments)
    with pytest.raises(RendererError, match='no parser identity'):
        render_file(tmp_path, '<TEI><text><body><p xml:id="p">before'
                    '<quote type="block">quoted</quote>after</p></body></text></TEI>')



def test_missing_renderer_callback_coverage_fails_closed(tmp_path, monkeypatch):
    from cvw_app import tei_renderer

    original = tei_renderer._render_tei_root
    monkeypatch.setattr(tei_renderer, '_render_tei_root',
                        lambda root, **kwargs: original(root))
    with pytest.raises(RendererError, match='coverage does not match'):
        render_file(tmp_path, '<TEI><text><body><div><head>Heading</head></div></body></text></TEI>')


def test_integrated_outline_rehashes_current_master(tmp_path):
    master, sha, _ = render_file(tmp_path, '<TEI><text><body><p xml:id="p">One</p></body></text></TEI>')
    master.write_bytes(master.read_bytes().replace(b'One', b'Two'))
    with pytest.raises(RendererError, match='sha256'):
        render_outline_provenance(master, expected_sha256=sha, master_member='master.tei.xml')


def test_deepcopy_callback_binds_descendants_by_actual_identity():
    from cvw_app.tei_renderer import _render_tei_root

    root = ElementTree.fromstring('<TEI><text><body><quote type="block" xml:id="q">'
                                  'word<hi rend="italic">marked</hi></quote></body></text></TEI>')
    quote = next(root.iter('quote'))
    inline = next(root.iter('hi'))
    copies = {}
    _render_tei_root(root, _on_fragment=lambda original, copied: copies.update({original: copied}))
    assert quote in copies and inline in copies
    assert copies[quote] is not quote and copies[inline] is not inline
    assert copies[quote][0] is copies[inline]
    assert quote.tag == 'quote' and copies[quote].tag == 'p'


def table_render(tmp_path, body):
    from cvw_app.bounded_tei_provenance import render_table_provenance
    exact = '<TEI><text><body>' + body + '</body></text></TEI>'
    master = tmp_path / 'table.xml'
    master.write_text(exact, encoding='utf-8')
    sha = hashlib.sha256(master.read_bytes()).hexdigest()
    rendered, traced = render_table_provenance(master, expected_sha256=sha,
                                               master_member='master.tei.xml')
    from cvw_app.review_renderers import DEFAULT_RENDERER_REGISTRY
    normal, supported = DEFAULT_RENDERER_REGISTRY.render('tei-reader', 'application/tei+xml', exact)
    assert supported and rendered == normal
    return master, rendered, traced


def test_table_construction_sources_and_actual_child_lineage(tmp_path):
    master, _, traced = table_render(tmp_path, '<table><row><cell xml:id="same">equal</cell>'
                                    '<cell xml:id="same">equal</cell></row></table>')
    assert [node.document_node()['type'] for node in traced] == [
        'table-cell', 'table-cell', 'table-row', 'table']
    assert [node.provenance.derived_from for node in traced] == [(), (), (0, 1), (2,)]
    first, second, row, table = traced
    assert first.document_node() == second.document_node()
    assert first.provenance.sources != second.provenance.sources
    assert len(row.provenance.sources) == 3
    assert len(table.provenance.sources) == 4
    source = first.provenance.sources[0]
    assert master.read_bytes()[source.locator.start:source.locator.end] == b'<cell xml:id="same">equal</cell>'


@pytest.mark.parametrize('body', [
    '<table><row><cell role="label" cols="2"><hi rend="italic">Title</hi></cell>'
    '<cell rows="2">value</cell></row></table>',
    '<quote type="block"><table><row><cell>value</cell></row></table></quote>',
    '<table><row><cell>outer<table><row><cell>nested</cell></row></table></cell></row></table>',
    '<p>body</p><table><row/></table>',
    '<p>no table</p>',
])
def test_table_construction_preserves_registered_output(tmp_path, body):
    _, _, traced = table_render(tmp_path, body)
    if body == '<p>body</p><table><row/></table>':
        assert len(traced) == 1
        assert traced[0].document_node()['type'] == 'table-row'
    elif body == '<p>no table</p>':
        assert traced == ()
    else:
        assert traced


def test_table_missing_callback_fails_closed(tmp_path, monkeypatch):
    from cvw_app import tei_renderer
    original = tei_renderer._render_tei_root
    def omitted(root, **kwargs):
        kwargs.pop('_on_table_node')
        return original(root, **kwargs)
    monkeypatch.setattr(tei_renderer, '_render_tei_root', omitted)
    with pytest.raises(RendererError, match='coverage lacks'):
        table_render(tmp_path, '<table><row><cell>value</cell></row></table>')


def test_table_missing_child_callback_fails_closed(tmp_path, monkeypatch):
    from cvw_app import tei_renderer
    original = tei_renderer._render_tei_root
    def omitted(root, **kwargs):
        callback = kwargs['_on_table_node']
        kwargs['_on_table_node'] = lambda element, node: (
            callback(element, node) if node['type'] != 'table-cell' else None)
        return original(root, **kwargs)
    monkeypatch.setattr(tei_renderer, '_render_tei_root', omitted)
    with pytest.raises(RendererError, match='child has no construction'):
        table_render(tmp_path, '<table><row><cell>value</cell></row></table>')
