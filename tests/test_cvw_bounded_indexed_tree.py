"""Construction-time source identity and current renderer equivalence."""

import hashlib
from xml.etree import ElementTree

import pytest

from cvw_app.bounded_xml_index import build_index, parse_indexed_master, read_fragment
from cvw_app.renderer_nodes import RendererError
from cvw_app.tei_renderer import _render_tei_root, render_tei


FIXTURES = [
    '<TEI><text><body><div xml:id="same"><head>A</head><p>one</p></div>'
    '<div xml:id="same"><head>B</head><p>two</p></div></body></text></TEI>',
    '<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:space="preserve"><text><body>'
    '<div><head>Outer</head><div><head>Inner</head><p> before <hi rend="italic">'
    'word</hi> after<note>note</note>tail<ref target="#n">reference</ref></p>'
    '</div></div></body></text></TEI>',
    '<teiCorpus><TEI><text><body><p>first</p></body></text></TEI>'
    '<TEI><text><body><p>second</p></body></text></TEI></teiCorpus>',
    '<TEI><text><body><p>before<!--ignored-->middle<?test ignored?>after'
    '<lb/>end<![CDATA[<literal>]]>&amp;é</p></body></text></TEI>',
    '<TEI><text><body><quote type="block"><p>inside</p>tail'
    '<p>more</p></quote><lg><l>line<note>note</note>tail</l><l>two</l></lg>'
    '<list><item>one</item><item>two</item></list></body></text></TEI>',
    '<TEI><text><body><table><row><cell>A</cell><cell>B</cell></row></table>'
    '<p>' + 'long text ' * 3000 + '</p></body></text></TEI>',
]


def prepare(tmp_path, exact):
    master = tmp_path / 'master.xml'
    master.write_bytes(exact.encode('utf-8'))
    sha = hashlib.sha256(master.read_bytes()).hexdigest()
    parsed = parse_indexed_master(master, expected_sha256=sha, renderer_version='test-v1')
    return master, sha, parsed


@pytest.mark.parametrize('exact', FIXTURES)
def test_indexed_tree_preserves_full_renderer_contract(tmp_path, exact):
    master, sha, parsed = prepare(tmp_path, exact)
    assert _render_tei_root(parsed.root) == render_tei('application/tei+xml', exact)
    assert parsed.index == build_index(master, expected_sha256=sha, renderer_version='test-v1')
    assert ElementTree.tostring(parsed.root) == ElementTree.tostring(ElementTree.fromstring(exact))
    assert set(parsed.source_elements) == set(parsed.root.iter())


def test_duplicate_ids_bind_distinct_exact_source_elements(tmp_path):
    master, sha, parsed = prepare(tmp_path, FIXTURES[0])
    divisions = list(parsed.root.iter('div'))
    assert divisions[0].attrib == divisions[1].attrib
    locators = [parsed.source_elements[element] for element in divisions]
    assert locators[0].ordinal != locators[1].ordinal
    fragments = [read_fragment(master, parsed.index, locator.ordinal,
                              expected_sha256=sha, renderer_version='test-v1').payload
                 for locator in locators]
    assert b'<head>A</head>' in fragments[0]
    assert b'<head>B</head>' in fragments[1]
    with pytest.raises(TypeError):
        parsed.source_elements[divisions[0]] = locators[1]
    # A copied/synthetic element never acquires a retained locator implicitly.
    with pytest.raises(KeyError):
        parsed.source_elements[ElementTree.fromstring(fragments[0])]


@pytest.mark.parametrize('exact', ['<TEI><text></TEI>',
                                  '<!DOCTYPE TEI [<!ENTITY x "text">]><TEI>&x;</TEI>'])
def test_invalid_master_returns_no_indexed_tree(tmp_path, exact):
    with pytest.raises(RendererError):
        prepare(tmp_path, exact)


def test_stale_digest_and_element_budget_fail_closed(tmp_path):
    master, sha, _ = prepare(tmp_path, FIXTURES[0])
    with pytest.raises(RendererError, match='sha256'):
        parse_indexed_master(master, expected_sha256='0' * 64, renderer_version='test-v1')
    with pytest.raises(RendererError, match='budget'):
        parse_indexed_master(master, expected_sha256=sha, renderer_version='test-v1', max_elements=1)


def test_indexed_tree_rejects_non_utf8(tmp_path):
    master = tmp_path / 'master.xml'
    master.write_bytes('<TEI/>'.encode('utf-16'))
    with pytest.raises(RendererError, match='UTF-8'):
        parse_indexed_master(master, expected_sha256=hashlib.sha256(master.read_bytes()).hexdigest(),
                             renderer_version='test-v1')
