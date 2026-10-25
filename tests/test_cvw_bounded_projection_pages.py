"""Opt-in outline/page integrity proof; body ownership remains unproven."""
from dataclasses import replace
import hashlib
import json

import pytest

from cvw_app import bounded_tei_projection as projection_api
from cvw_app import bounded_tei_provenance as provenance_api
from cvw_app.bounded_xml_index import build_index
from cvw_app.renderer_nodes import RendererError


def prepare(tmp_path, text=None):
    text = text or ('<TEI><text><body><div xml:id="same"><head>One</head><p>A</p>'
                    '</div><div xml:id="same"><head>Two</head><p>B</p></div>'
                    '</body></text></TEI>')
    master = tmp_path / 'master.xml'
    master.write_text(text, encoding='utf-8')
    sha = hashlib.sha256(master.read_bytes()).hexdigest()
    index = build_index(master, expected_sha256=sha,
                        renderer_version=projection_api.renderer_version())
    return master, sha, index


def build(master, sha, index, **kwargs):
    return projection_api.build_projection(master, index, expected_sha256=sha, **kwargs)


def select(master, sha, index, projection, segment=0, location='start'):
    return projection_api.select_projection(master, index, projection,
                                           expected_sha256=sha, location=location,
                                           segment=segment)


def test_opt_in_pages_preserve_default_oracle_and_exact(tmp_path):
    master, sha, index = prepare(tmp_path)
    ordinary = build(master, sha, index)
    traced = build(master, sha, index, master_member='package/master.xml')
    assert ordinary.source_bindings is None
    assert ordinary.pages == traced.pages
    assert ordinary.segments == traced.segments
    assert projection_api.exact_projection(master, traced, expected_sha256=sha) == master.read_text()
    for number in range(len(traced.pages)):
        for location, _ in traced.contexts:
            result = select(master, sha, index, traced, number, location)
            sidecar = result.pop('source_bindings')
            assert result == select(master, sha, index, ordinary, number, location)
            assert sidecar['segment'] == number
            assert sidecar['body_ownership'] == 'unknown'
            assert sidecar['requires_check'] is True
            assert sidecar['served_page_sha256'] == hashlib.sha256(
                traced.pages[number].encode()).hexdigest()
    contributions = [entry for record in traced.source_bindings
                     for entry in json.loads(record)['outline_contributions']]
    owners = {entry['location']: entry['provenance']['sources'][0]['locator']['ordinal']
              for entry in contributions}
    assert len(owners) >= 2
    assert len(set(owners.values())) == len(owners)
    result = select(master, sha, index, traced)
    result['source_bindings']['outline_contributions'].clear()
    assert any(json.loads(item)['outline_contributions'] for item in traced.source_bindings)


def test_unoutlined_page_does_not_invent_source_owner(tmp_path):
    master, sha, index = prepare(tmp_path, '<TEI><text><body><p>Plain</p></body></text></TEI>')
    traced = build(master, sha, index, master_member='master.xml')
    sidecar = select(master, sha, index, traced)['source_bindings']
    assert sidecar['outline_contributions'] == []
    assert sidecar['body_ownership'] == 'unknown'


def test_truncated_served_replacement_bound_to_exact_served_bytes(tmp_path):
    # A single atomic table exceeds the actual page cap.
    master, sha, index = prepare(tmp_path, '<TEI><text><body><div><head>Table</head>'
                                '<table><row><cell>' + 'word ' * 18000
                                + '</cell></row></table></div></body></text></TEI>')
    traced = build(master, sha, index, master_member='master.xml')
    replacements = [i for i, record in enumerate(traced.source_bindings)
                    if json.loads(record)['served_replacement']]
    assert replacements
    for number in replacements:
        result = select(master, sha, index, traced, number)
        assert result['document']['nodes'][0]['type'] == 'preformatted'
        assert result['source_bindings']['served_page_sha256'] == hashlib.sha256(
            traced.pages[number].encode()).hexdigest()
        assert result['source_bindings']['requires_check']


@pytest.mark.parametrize('mutation', ['missing', 'version', 'segment', 'page', 'integrity'])
def test_stale_or_missing_binding_fails_closed(tmp_path, mutation):
    master, sha, index = prepare(tmp_path)
    traced = build(master, sha, index, master_member='master.xml')
    records = list(traced.source_bindings)
    record = json.loads(records[0])
    if mutation == 'missing':
        records = []
    else:
        key = {'version': 'version', 'segment': 'segment', 'page': 'served_page_sha256',
               'integrity': 'body_ownership'}[mutation]
        record[key] = 'wrong'
        records[0] = projection_api._pack(record)
    altered = replace(traced, source_bindings=tuple(records))
    # Even a structurally re-digested sidecar cannot claim a different page/version.
    if mutation != 'integrity':
        altered = replace(altered, integrity_sha256=projection_api._digest(altered))
    with pytest.raises(RendererError, match='binding|integrity'):
        select(master, sha, index, altered)


@pytest.mark.parametrize('mutation', ['missing', 'ambiguous', 'stale'])
def test_admission_rejects_unbound_outline_contributions(tmp_path, monkeypatch, mutation):
    master, sha, index = prepare(tmp_path)
    original = provenance_api.render_outline_provenance

    def broken(*args, **kwargs):
        rendered, bindings = original(*args, **kwargs)
        bindings = dict(bindings)
        location = next(iter(bindings))
        if mutation == 'missing':
            del bindings[location]
        elif mutation == 'ambiguous':
            bindings[location] = list(bindings.values())[-1]
        else:
            traced = bindings[location]
            source = replace(traced.provenance.sources[0], master_sha256='0' * 64)
            bindings[location] = replace(traced, provenance=replace(
                traced.provenance, sources=(source,)))
        return rendered, bindings

    monkeypatch.setattr(provenance_api, 'render_outline_provenance', broken)
    with pytest.raises(RendererError, match='binding'):
        build(master, sha, index, master_member='master.xml')
