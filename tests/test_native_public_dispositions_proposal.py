"""Maintained public disposition checks against accepted sources and saved rows."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import quote, unquote
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import cached_edition_lookups

from ocd_kernel.projection import native_public_dispositions as policy

ROOT = Path(__file__).resolve().parents[1]

CASES = (
    ('pg49917-assumption-sermon-i', 'pg49917-assumption-sermon-i-private-release-20261003-v3', 2, 9),
    ('pg49917-assumption-sermon-ii', 'pg49917-assumption-sermon-ii-private-release-20261003-v1', 2, 10),
    ('pg77576-ignatius-romans', 'pg77576-ignatius-romans-private-release-20261003-v2', 3, 1),
    ('pg77576-ignatius-polycarp', 'pg77576-ignatius-polycarp-private-release-20261003-v1', 3, 1),
)


def test_distinct_newman_edition_uses_generic_route(tmp_path):
    identity = {**policy.NEWMAN_IDENTITY, 'edition_id': 'newman-reader-i-vi'}
    accepted = {'identity': identity, 'source': {'source_path': 'raw/newman-reader/index.html'}}
    assert policy.select(tmp_path, identity, accepted, b'distinct accepted master',
                         category='sermons', collection=True, projection_profile=None,
                         allow_acceptance_metadata=True) is None


def test_newman_pg_authority_still_requires_exact_identity_source_and_master():
    edition = ROOT / policy._NEWMAN_EDITION
    accepted = json.loads((edition / 'acceptance.json').read_text(encoding='utf-8'))
    raw = (edition / 'master.tei.xml').read_bytes()
    identity = deepcopy(policy.NEWMAN_IDENTITY)
    options = dict(category='sermons', collection=True, projection_profile=None,
                   allow_acceptance_metadata=True)
    assert policy.select(ROOT, identity, accepted, raw, **options) == policy.NEWMAN_WORK
    for changed_identity, changed_accepted, changed_raw in (
        ({**identity, 'edition_id': 'unrelated'}, accepted, raw),
        (identity, {**accepted, 'source': {**accepted['source'],
                                        'source_path': 'raw/unrelated.html'}}, raw),
        (identity, accepted, raw + b' '),
        ({**identity, 'work_id': 'unrelated'}, accepted, raw),
    ):
        with pytest.raises(PipelineError):
            policy.select(ROOT, changed_identity, changed_accepted, changed_raw, **options)


def authority(work):
    edition = next((ROOT / 'library/works' / work).rglob('acceptance.json')).parent
    accepted = json.loads((edition / 'acceptance.json').read_text(encoding='utf-8'))
    identity = {key: accepted['identity'][key] for key in ('work_id', 'textual_form_id', 'edition_id')}
    raw = (edition / 'master.tei.xml').read_bytes()
    return identity, accepted, raw


def saved(release):
    path = ROOT / 'reports/_logs' / release / 'actual-master-projection.json'
    return json.loads(path.read_text(encoding='utf-8'))


def original_rows(rows, work):
    """Reverse only known saved public aliases to simulate current generic rows."""
    result = deepcopy(rows)
    if work.startswith('pg49917-'):
        rules = policy._rules(work)
        def visit(item):
            if isinstance(item, dict):
                if item.get('kind') == 'source-marker':
                    attrs = item.get('attributes', {})
                    number = attrs.get('number')
                    if number in rules:
                        token, _, alias = rules[number]
                        assert attrs['style'] == alias
                        detail = json.loads(unquote(attrs['source_annotations'][len(policy.ANNOTATION):]))
                        assert detail['rend'] == alias
                        detail['rend'] = token
                        attrs['style'] = token
                        attrs['source_annotations'] = policy.ANNOTATION + quote(
                            json.dumps(detail, ensure_ascii=False, separators=(',', ':')), safe='')
                for child in item.values():
                    visit(child)
            elif isinstance(item, list):
                for child in item:
                    visit(child)
        visit(result)
    else:
        node = result[0]['structure'][0]['content'][4]['content'][0]['content'][3]
        node['attributes']['source_target'] = policy.PRIVATE_PAGE
        result[0]['source_references'][0]['target'] = policy.PRIVATE_PAGE
    return result


@pytest.mark.parametrize('work,release,row_count,carrier_count', CASES)
def test_exact_accepted_dispositions_match_saved_rows_and_independent_observer(
        work, release, row_count, carrier_count, monkeypatch):
    identity, accepted, raw = authority(work)
    selected = policy.select(ROOT, identity, accepted, raw, category='prose', collection=False,
                             projection_profile=None, allow_acceptance_metadata=True)
    assert selected == work
    output = saved(release)
    original = original_rows(output['rows'], work)
    assert len(original) == row_count
    expected = policy.project_rows(original, raw, selected)
    assert expected == output['rows']
    assert sha256(json.dumps(expected, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')).encode()).hexdigest() == output['receipt']['output_sha256']
    before_text = [row['text'] for row in original]
    assert [row['text'] for row in expected] == before_text
    if work.startswith('pg49917-'):
        assert sum(json.dumps(expected, ensure_ascii=False).count(alias) for alias in
                   (policy.COMMENT_PUBLIC, policy.STYLE_PUBLIC)) == 2 * carrier_count
    else:
        assert json.dumps(expected, ensure_ascii=False).count(policy.PUBLIC_PAGE) == 2
    monkeypatch.setattr(policy, 'project_rows', lambda *args, **kwargs: pytest.fail('producer called'))
    monkeypatch.setattr(policy, 'source_census_et', lambda *args, **kwargs: pytest.fail('ET producer called'))
    assert policy.observe_rows(original, raw, selected) == output['rows']


@pytest.mark.parametrize('work,release,_,__', CASES)
def test_known_authority_changes_fail_closed(work, release, _, __):
    identity, accepted, raw = authority(work)
    for changed_identity, changed_accepted, changed_raw in (
        ({**identity, 'edition_id': 'unrelated'}, accepted, raw),
        (identity, {**accepted, 'representation_revision': {'id': 'changed'}}, raw),
        (identity, {**accepted, 'source': {**accepted['source'], 'source_sha256': '0'*64}}, raw),
        (identity, {**accepted, 'source': {**accepted['source'], 'source_path': 'raw/unrelated.html'}}, raw),
        (identity, {**accepted, 'source': {**accepted['source'], 'source_bytes': 1}}, raw),
        (identity, {**accepted, 'source': {**accepted['source'], 'source_manifest': {
            **accepted['source']['source_manifest'], 'sha256': '0'*64}}}, raw),
        (identity, {**accepted, 'source': {**accepted['source'], 'source_manifest': {
            **accepted['source']['source_manifest'], 'bytes': 1}}}, raw),
        (identity, accepted, raw + b'\n'),
    ):
        with pytest.raises(PipelineError):
            policy.select(ROOT, changed_identity, changed_accepted, changed_raw,
                          category='prose', collection=False, projection_profile=None,
                          allow_acceptance_metadata=True)
    with pytest.raises(PipelineError):
        policy.select(ROOT, identity, accepted, raw, category='commentary', collection=False,
                      projection_profile=None, allow_acceptance_metadata=True)


@pytest.mark.parametrize('work,release,_,__', CASES)
def test_source_and_public_carrier_mutations_reject(work, release, _, __):
    _, _, raw = authority(work)
    baseline = original_rows(saved(release)['rows'], work)
    if work.startswith('pg49917-'):
        for change in ('style', 'annotation', 'missing', 'moved', 'duplicate',
                       'unknown_attribute', 'invented_child', 'unknown_private'):
            rows = deepcopy(baseline)
            markers = []
            def find(item):
                if isinstance(item, dict):
                    if item.get('kind') == 'source-marker' and item.get('attributes', {}).get('number') in policy._rules(work):
                        markers.append(item)
                    for child in item.values(): find(child)
                elif isinstance(item, list):
                    for child in item: find(child)
            find(rows)
            assert len(markers) == len(policy._rules(work))
            if change == 'style':
                markers[0]['attributes']['style'] = 'comment-digest:' + '0'*64
            elif change == 'annotation':
                markers[0]['attributes']['source_annotations'] += '%20'
            elif change == 'missing':
                markers[0]['attributes']['number'] = '9999'
            elif change == 'moved':
                markers[0]['attributes']['number'], markers[1]['attributes']['number'] = (
                    markers[1]['attributes']['number'], markers[0]['attributes']['number'])
            elif change == 'duplicate':
                markers[1]['attributes'] = deepcopy(markers[0]['attributes'])
            elif change == 'unknown_attribute':
                markers[0]['attributes']['invented'] = 'x'
            elif change == 'invented_child':
                markers[0]['content'] = [{'kind': 'text', 'text': 'invented'}]
            else:
                rows[0]['invented'] = 'raw/gutenberg/49917/html/other.html'
            with pytest.raises(ValueError): policy.project_rows(rows, raw, work)
            with pytest.raises(ValueError): policy.observe_rows(rows, raw, work)
        source = ET.fromstring(raw)
        marker = next(node for node in source.iter() if isinstance(node.tag, str)
                      and node.get('rend', '').startswith('comment-digest:'))
        marker.set('n', '9999')
    else:
        for change in ('target', 'number', 'path', 'extra_private'):
            rows = deepcopy(baseline)
            node = rows[0]['structure'][0]['content'][4]['content'][0]['content'][3]
            if change == 'target':
                node['attributes']['source_target'] = policy.PRIVATE_PAGE.replace('141', '142')
            elif change == 'number':
                node['attributes']['number'] = 'other'
            elif change == 'path':
                rows[0]['source_references'][0]['source_child_path'] = [4, 0, 2]
            else:
                rows[1]['invented'] = 'raw/gutenberg/77576/html/other.html'
            with pytest.raises(ValueError): policy.project_rows(rows, raw, work)
            with pytest.raises(ValueError): policy.observe_rows(rows, raw, work)
        source = ET.fromstring(raw)
        marker = next(node for node in source.iter(policy.TEI+'ref') if node.get('target') == policy.PRIVATE_PAGE)
        marker.set('target', policy.PRIVATE_PAGE.replace('141', '142'))
    altered = ET.tostring(source)
    with pytest.raises((PipelineError, ValueError)):
        policy.source_census_et(altered, work)
    with pytest.raises(ValueError):
        policy.source_census_lxml(altered, work)


@pytest.mark.parametrize('work,release', (
    ('pg49917-assumption-sermon-iii', 'pg49917-assumption-sermon-iii-private-release-20261003-v1'),
    ('pg77576-ignatius-philadelphians', 'pg77576-ignatius-philadelphians-private-release-20261003-v1'),
))
def test_unprofiled_neighbors_remain_generic(work, release):
    identity, accepted, raw = authority(work)
    chosen = policy.select(ROOT, identity, accepted, raw, category='prose', collection=False,
                           projection_profile=None, allow_acceptance_metadata=True)
    assert chosen is None
    existing = saved(release)['rows']
    assert policy.project_rows(existing, raw, chosen) == existing
    assert policy.observe_rows(existing, raw, chosen) == existing


def test_maintained_accepted_route_uses_independent_checker(monkeypatch):
    """Exercise the maintained accepted route and its independent observer."""
    from ocd_kernel.projection.categories import native_documents as candidate, prose
    import ocd_kernel.projection.native_content as native_content

    with cached_edition_lookups():
        for work, release, _, __ in CASES:
            edition = next((ROOT / 'library/works' / work).rglob('acceptance.json')).parent
            actual = prose.project_accepted_prose(ROOT, acceptance_path=edition / 'acceptance.json')
            saved_projection = saved(release)
            assert actual['rows'] == saved_projection['rows'], work
            for key in ('output_sha256', 'master_sha256'):
                assert actual['receipt'][key] == saved_projection['receipt'][key], (work, key)
            assert actual['receipt']['mapping_version'] == policy.PROSE_MAPPING_VERSION
            assert actual['receipt']['mapping_version'] != saved_projection['receipt']['mapping_version']
            with monkeypatch.context() as disabled:
                def unavailable(*args, **kwargs):
                    raise AssertionError('independent checker invoked a producer')
                disabled.setattr(prose, 'project_accepted_prose', unavailable)
                disabled.setattr(candidate, 'project_accepted_document', unavailable)
                disabled.setattr(candidate, 'project_document', unavailable)
                disabled.setattr(native_content, 'project_content', unavailable)
                assert prose.verify_accepted_prose(
                    ROOT, acceptance_path=edition / 'acceptance.json',
                    rows=actual['rows'], receipt=actual['receipt']) == [], work
        for work, release in (
            ('pg49917-assumption-sermon-iii', 'pg49917-assumption-sermon-iii-private-release-20261003-v1'),
            ('pg77576-ignatius-philadelphians', 'pg77576-ignatius-philadelphians-private-release-20261003-v1'),
        ):
            edition = next((ROOT / 'library/works' / work).rglob('acceptance.json')).parent
            actual = prose.project_accepted_prose(ROOT, acceptance_path=edition / 'acceptance.json')
            saved_projection = saved(release)
            assert actual['rows'] == saved_projection['rows'], work
            assert actual['receipt']['mapping_version'] == saved_projection['receipt']['mapping_version']
            assert actual['receipt']['output_sha256'] == saved_projection['receipt']['output_sha256']
