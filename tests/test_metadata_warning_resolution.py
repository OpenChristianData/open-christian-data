"""Current metadata is authoritative; retired override contracts are rejected."""
import json

import pytest

from tests.test_library_records import root, write, core
from ocd_kernel.library import labels
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.views import library_browse_snapshot
from build.tools.report_metadata_consistency import metadata_consistency
from build.tools.export_library_metadata import export_metadata


@pytest.fixture
def vocabulary(root, monkeypatch):
    value = labels.profile()
    path = root / 'label-profile.json'
    write(path, value)
    monkeypatch.setattr(labels, 'PROFILE', path)
    return value, path


def test_provider_set_survives_lookup_browse_filter_and_export(root):
    path = root / 'library/works/alpha/forms/en/editions/first/acquisitions/copy.json'
    acquisition = json.loads(path.read_text());acquisition['provider'] = 'Kingdom Collective and supplemental retained witnesses'
    write(path, acquisition);before = path.read_bytes()
    lookup = core(root)['sections']['metadata']['data']['normalized']['providers'][0]
    browse = library_browse_snapshot(root, provider='spurgeon-retained-provider-set')['works'][0]['editions'][0]['providers'][0]
    exported = export_metadata(root)['works'][0]['editions'][0]['providers'][0]
    assert lookup == browse == exported
    assert lookup['kind'] == 'provider-set' and lookup['raw'] == acquisition['provider']
    assert 'supplemental' in lookup['description']
    assert library_browse_snapshot(root, provider='kingdom-collective')['works'] == []
    assert path.read_bytes() == before
    assert export_metadata(root) == export_metadata(root)


@pytest.mark.parametrize('description,expected', [
    ('SWORD zCom (BlockType=CHAPTER, CompressType=ZIP, SourceType=ThML)', ('thml', 'utf-8', 'sword-zcom-zip')),
    ('eBible USFM authority package with USFX comparison carrier', ('usfm', None, 'zip')),
    ('HTML transcription cached as extracted UTF-8 text', ('html', None, None)),
])
def test_source_format_description_preserves_carriers_without_quality_claim(root, description, expected):
    write(root / 'sources/example/config.json', {'source_format': description})
    result = metadata_consistency(root)['source_formats'][0]['format']
    first = result['representations'][0]
    assert (first['format'], first['encoding'], first['packaging']) == expected
    assert result['raw'] == description and result['mapping'] == 'mapped'
    assert not any('corrected' in str(carrier) for carrier in result['representations'])
    if description.startswith('HTML transcription'):
        assert 'upstream origin' in first['scope']
        assert result['representations'][1]['scope'] == 'retained extracted text carrier'


@pytest.mark.parametrize('role,scope,expected', [
    ('author', {'kind': 'work', 'id': 'alpha'}, 'aut'),
    ('introduction author', {'kind': 'component', 'id': 'introduction'}, 'win'),
    ('appendix author', {'kind': 'component', 'id': 'appendix'}, 'wst'),
])
def test_canonical_creator_role_scope_survive_lookup_browse_export(root, role, scope, expected):
    path = root / 'library/works/alpha/work.json'
    work = json.loads(path.read_text());work['creators'] = [{'name': 'Verified creator', 'role': role, 'scope': scope}]
    write(path, work)
    lookup = core(root)['sections']['metadata']['data']['normalized']['creators'][0]
    browse = library_browse_snapshot(root)['works'][0]['normalized']['creators'][0]
    exported = export_metadata(root)['works'][0]['creators'][0]
    assert lookup['name'] == browse['name'] == exported['name'] == 'Verified creator'
    assert lookup['role']['value'] == browse['role']['value'] == exported['role']['value'] == expected
    assert lookup['scope'] == browse['scope'] == exported['scope'] == scope
    assert 'display_name' not in exported and 'person_id' not in exported
    work['title'] = 'Legitimate metadata update';write(path, work)
    assert export_metadata(root)['works'][0]['title'] == work['title']


def test_invalid_canonical_creator_scope_fails_closed(root):
    path = root / 'library/works/alpha/work.json'
    work = json.loads(path.read_text());work['creators'] = [{'name': 'Creator', 'role': 'author', 'scope': {'kind': 'invented-kind', 'id': 'alpha'}}]
    write(path, work)
    with pytest.raises(PipelineError):
        export_metadata(root)


@pytest.mark.parametrize('field', ['creator_annotations', 'legacy_labels', 'display_aliases'])
def test_retired_override_profile_keys_are_rejected(root, vocabulary, field):
    value, path = vocabulary;value[field] = [];write(path, value)
    with pytest.raises(PipelineError):
        labels.profile()


def test_export_uses_the_current_profile_and_contract(root):
    profile = labels.profile()['version']
    assert library_browse_snapshot(root)['label_profile'] == profile
    exported = export_metadata(root)
    assert exported['profile'] == profile == 'ocd-metadata-labels-v2'
    assert exported['contract'] == 'ocd-library-metadata-v3'


def test_historical_roles_keep_distinct_responsibility(root):
    path = root / 'library/works/alpha/work.json'
    work = json.loads(path.read_text());work['creators'] = [{'name': 'Sender', 'role': 'sender'}, {'name': 'Dictator', 'role': 'dictator'}]
    write(path, work)
    roles = [c['role'] for c in export_metadata(root)['works'][0]['creators']]
    assert roles == [{'raw': 'sender', 'value': 'crp', 'mapping': 'mapped'}, {'raw': 'dictator', 'value': 'ocd:dictator', 'mapping': 'mapped'}]


@pytest.mark.parametrize('config', [
    {'schema_type': 'structured_text'},
    {'schema_type': 'structured_text', 'era': None, 'audience': None},
])
def test_absent_or_blank_classifications_are_valid_without_exception_records(root, config):
    write(root / 'sources/structured-text/example/config.json', config)
    report = metadata_consistency(root)
    assert not any(i['severity'] == 'error' for i in report['issues'])
    assert 'legacy_labels' not in report
    assert report['contract'] == 'ocd-metadata-consistency-v3'


@pytest.mark.parametrize('field,value', [('era', 'early-modern'), ('audience', 'general')])
def test_invalid_classifications_are_errors_at_their_owning_path(root, field, value):
    path = root / 'sources/structured-text/example/config.json'
    write(path, {'schema_type': 'structured_text', field: value})
    issue = next(i for i in metadata_consistency(root)['issues'] if i['code'] == 'unsupported-legacy-label')
    assert issue['severity'] == 'error' and issue['path'] == path.relative_to(root).as_posix()
    assert issue['field'] == field and issue['raw'] == value


def test_unknown_provider_and_format_remain_actionable(root):
    path = root / 'library/works/alpha/forms/en/editions/first/acquisitions/copy.json'
    acquisition = json.loads(path.read_text());acquisition['provider'] = 'Unreviewed organization';write(path, acquisition)
    write(root / 'sources/example/config.json', {'source_format': 'Unreviewed carrier'})
    codes = {i['code'] for i in metadata_consistency(root)['issues'] if i['severity'] == 'warning'}
    assert {'unmapped-provider', 'unmapped-source-format'} <= codes


def test_adopted_public_facet_exports_without_exposing_private_authority(root):
    path = root / 'library/works/alpha/work.json'
    work = json.loads(path.read_text())
    work['facets'] = [{'kind': 'subject', 'authority': 'https://id.loc.gov/authorities/subjects',
                       'term_id': 'sh85134665', 'label': 'Theology',
                       'evidence': ['research/evidence.md'], 'adoption': 'adopted'}]
    write(path, work)
    assert export_metadata(root)['works'][0]['facets'] == [
        {'kind': 'subject', 'vocabulary': 'https://id.loc.gov/authorities/subjects',
         'term_id': 'sh85134665', 'label': 'Theology'}]
    work['facets'][0]['authority'] = 'raw/private-vocabulary.json'
    write(path, work)
    with pytest.raises(PipelineError, match='private path'):
        export_metadata(root)
