from dataclasses import replace
import hashlib
import json

import pytest

from cvw_app.bounded_xml_index import build_index, read_fragment
from cvw_app.bounded_tei_projection import (
    build_projection, exact_projection, renderer_version, select_projection,
)
from cvw_app.renderer_nodes import RendererError
from cvw_app.review_contract import ReviewApplication
from cvw_app.review_renderers import DEFAULT_RENDERER_REGISTRY


FIXTURES = [
    '<TEI><text><body><div xml:id="same"><head>First</head><p>A</p></div><div xml:id="same"><head>Second</head><p>B</p></div></body></text></TEI>',
    '<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:space="preserve"><text><body><div xml:id="outer"><head>Outer</head><p>  before  </p><div xml:id="inner"><head>Inner</head><p xml:space="default"> nested <hi rend="italic">words</hi> </p></div><p>after</p></div></body></text></TEI>',
    '<TEI><text><body><div xml:id="notes"><head>Notes</head><p>before<note xml:id="n">shared note</note>after</p><p>other<ref target="#n">reference</ref></p></div></body></text></TEI>',
    '<teiCorpus><TEI><text><body><div xml:id="one"><head>One</head><p>A</p></div></body></text></TEI><TEI><text><body><div xml:id="two"><head>Two</head><p>B</p></div></body></text></TEI></teiCorpus>',
]


def prepare(tmp_path, exact=FIXTURES[0]):
    master = tmp_path / 'master.xml'
    master.write_bytes(exact.encode('utf-8'))
    sha = hashlib.sha256(master.read_bytes()).hexdigest()
    index = build_index(master, expected_sha256=sha, renderer_version=renderer_version())
    return master, sha, index, build_projection(master, index, expected_sha256=sha)


@pytest.mark.parametrize('exact', FIXTURES)
def test_global_projection_matches_existing_stage_semantics(tmp_path, exact):
    master, sha, index, projection = prepare(tmp_path, exact)
    rendered, _ = DEFAULT_RENDERER_REGISTRY.render('tei-reader', 'application/tei+xml', exact)
    assert json.loads(projection.outline_json) == rendered['outline']
    assert [json.loads(value) for value in projection.segments] == rendered['segments']
    assert exact_projection(master, projection, expected_sha256=sha) == exact
    for location, context in rendered['contexts'].items():
        for segment in range(len(rendered['segments'])):
            selected = select_projection(master, index, projection, expected_sha256=sha,
                                         location=location, segment=segment)
            assert selected['selected_context'] == {
                'location': location, 'label': context['label'], 'text': context['text'],
                'document': {'nodes': context['nodes']},
            }
            assert selected['document']['nodes'] == ReviewApplication._served_page_nodes(None, rendered, segment, 1)
            containing = {0} if location == 'start' else {
                i for i, item in enumerate(rendered['segments']) if location in item['locations']}
            assert selected['location_state'] == ('in-range' if segment in containing else 'location-outside-range')


def test_selected_output_cannot_mutate_cached_projection(tmp_path):
    master, sha, index, projection = prepare(tmp_path)
    args = dict(expected_sha256=sha, location='start', segment=0)
    selected = select_projection(master, index, projection, **args)
    selected['document']['nodes'].clear()
    assert select_projection(master, index, projection, **args)['document']['nodes']


@pytest.mark.parametrize('field,value', [('renderer_version', 'old'), ('master_sha256', '0'*64),
                                         ('outline_json', '[]'), ('index_integrity', '0'*64)])
def test_projection_mismatch_fails_closed(tmp_path, field, value):
    master, sha, index, projection = prepare(tmp_path)
    projection = replace(projection, **{field: value})
    with pytest.raises(RendererError, match='mismatch'):
        select_projection(master, index, projection, expected_sha256=sha, location='start', segment=0)
    with pytest.raises(RendererError, match='mismatch'):
        exact_projection(master, projection, expected_sha256=sha)


def test_stale_master_blocks_selection_and_exact(tmp_path):
    master, sha, index, projection = prepare(tmp_path)
    master.write_bytes(master.read_bytes().replace(b'First', b'Other'))
    with pytest.raises(RendererError, match='sha256'):
        select_projection(master, index, projection, expected_sha256=sha, location='start', segment=0)
    with pytest.raises(RendererError, match='sha256'):
        exact_projection(master, projection, expected_sha256=sha)


def test_index_mismatch_rejected(tmp_path):
    master, sha, index, projection = prepare(tmp_path)
    with pytest.raises(RendererError, match='mismatch'):
        select_projection(master, replace(index, indexer_version='old'), projection,
                          expected_sha256=sha, location='start', segment=0)


@pytest.mark.parametrize('location,segment', [('missing', 0), ('start', -1), ('start', True), ('start', 999)])
def test_unknown_selection_never_substitutes(tmp_path, location, segment):
    master, sha, index, projection = prepare(tmp_path)
    with pytest.raises(RendererError, match='unknown'):
        select_projection(master, index, projection, expected_sha256=sha, location=location, segment=segment)


def test_malformed_xml_has_no_projection(tmp_path):
    with pytest.raises(RendererError):
        prepare(tmp_path, '<TEI><text></TEI>')


def test_non_tei_does_not_fall_through_to_other_renderer(tmp_path):
    with pytest.raises(RendererError, match='root'):
        prepare(tmp_path, '<other><p>text</p></other>')


@pytest.mark.parametrize('exact', FIXTURES[:2])
def test_source_ordinals_do_not_claim_global_cvw_crosswalk(tmp_path, exact):
    """Duplicate IDs and nested elements require renderer provenance, not guesses."""
    master, sha, index, projection = prepare(tmp_path, exact)
    divisions = [entry for entry in index.elements
                 if entry.expanded_name.split('}')[-1] == 'div']
    assert len(divisions) == 2
    assert divisions[0].ordinal != divisions[1].ordinal
    for entry in divisions:
        fragment = read_fragment(master, index, entry.ordinal, expected_sha256=sha,
                                 renderer_version=renderer_version())
        with pytest.raises(RendererError, match='no equivalent CVW projection adapter'):
            fragment.cvw_presentation()
        # A source ordinal string is not a generated global location, even
        # though the same immutable projection contains the division's text.
        with pytest.raises(RendererError, match='unknown global location'):
            select_projection(master, index, projection, expected_sha256=sha,
                              location=str(entry.ordinal), segment=0)


@pytest.mark.parametrize('ordinal', [-1, 999, True, None])
def test_missing_source_ordinal_never_selects_neighbor(tmp_path, ordinal):
    master, sha, index, _ = prepare(tmp_path)
    with pytest.raises(RendererError, match='unknown source element ordinal'):
        read_fragment(master, index, ordinal, expected_sha256=sha,
                      renderer_version=renderer_version())


def test_index_implementation_change_invalidates_projection(tmp_path, monkeypatch):
    from pathlib import Path

    master, sha, index, projection = prepare(tmp_path)
    original_read_bytes = Path.read_bytes

    def changed_index_code(path):
        payload = original_read_bytes(path)
        if path.name == 'bounded_xml_index.py':
            return payload + b'\n# changed index implementation\n'
        return payload

    monkeypatch.setattr(Path, 'read_bytes', changed_index_code)
    assert renderer_version() != projection.renderer_version
    with pytest.raises(RendererError, match='mismatch'):
        select_projection(master, index, projection, expected_sha256=sha,
                          location='start', segment=0)
    with pytest.raises(RendererError, match='mismatch'):
        build_projection(master, index, expected_sha256=sha)
