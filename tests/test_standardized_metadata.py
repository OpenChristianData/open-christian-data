"""Queries preserve exact subjects, source wording, and unassessed coverage."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from tests.test_library_records import root, write, core
from ocd_kernel.library.records import lookup_exit_code
from ocd_kernel.library.views import library_browse_snapshot
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.rights import matches
from build.tools.export_library_metadata import export_metadata
from build.tools.report_metadata_consistency import metadata_consistency


def binding(root, path, **extra):
    return {'path': path, 'sha256': hashlib.sha256((root / path).read_bytes()).hexdigest(), **extra}


def assessment(root, identifier='historical', *, status='public-domain', territory=('US',),
               license_ids=(), basis='statutory-assessment', condition='unconditional', components=()):
    base = 'library/works/alpha/forms/en/editions/first'
    decision = f'{base}/rights-subjects/{identifier}-decision.json'
    write(root / decision, {'selected': {'included': ['historical chapters'], 'excluded': ['modern introduction']}})
    subject_path = f'{base}/rights-subjects/{identifier}.json'
    subject = {'schema_version': '2.1', 'subject_id': identifier, 'work_id': 'alpha', 'edition_id': 'first',
               'scope': 'selected-text', 'material': binding(root, decision, pointer='/selected'), 'components': list(components),
               'public_scope': {'include': [{'kind': 'record-id', 'values': [identifier + '-chapter']}],
                                'exclude': [{'kind': 'record-id', 'values': [identifier + '-modern-introduction']}]}}
    write(root / subject_path, subject)
    record = {'schema_version': '2.1', 'record_id': identifier + '-' + (territory[0] if territory else 'provider'),
              'work_id': 'alpha', 'edition_id': 'first', 'scope': 'selected-text',
              'subject': binding(root, subject_path, id=identifier), 'rights_status': status,
              'jurisdictions': list(territory), 'license_ids': list(license_ids), 'basis': basis,
              'condition': condition, 'evidence': [binding(root, decision)],
              'assessed_by': 'Fixture assessment', 'assessed_on': '2026-10-14'}
    path = root / base / 'rights' / (record['record_id'] + '.json')
    write(path, record)
    return path, record


def test_aliases_filter_the_same_edition_and_preserve_raw_metadata(root):
    path = root / 'library/works/alpha/work.json'
    work = json.loads(path.read_text())
    work['textual_forms'][0]['editions'][0]['language'] = 'eng'
    work['creators'] = [{'name': 'A writer', 'role': 'introduction author'}]
    write(path, work)
    ap = root / 'library/works/alpha/forms/en/editions/first/acquisitions/copy.json'
    acquisition = json.loads(ap.read_text()); acquisition['provider'] = 'CCEL'; write(ap, acquisition)
    before = path.read_bytes(), ap.read_bytes()
    for language in ('en', 'eng'):
        report = library_browse_snapshot(root, language=language, provider='Christian Classics Ethereal Library')
        assert [w['work_id'] for w in report['works']] == ['alpha']
        assert report['works'][0]['editions'][0]['language'] == {'raw': 'eng', 'value': 'en', 'mapping': 'mapped'}
    data = core(root)['sections']['metadata']['data']
    assert data['normalized']['creators'][0]['role']['value'] == 'win'
    assert data['normalized']['creators'][0]['scope'] is None
    assert data['rights'][0]['health'] == 'not_assessed'
    assert before == (path.read_bytes(), ap.read_bytes())


def test_territorial_outcomes_and_cc0_combined_query_are_distinct(root):
    path, record = assessment(root)
    australian = dict(record, record_id='historical-AU', jurisdictions=['AU'], rights_status='restricted')
    write(path.with_name('historical-AU.json'), australian)
    assessment(root, 'dedication', status='licensed', territory=('worldwide',), license_ids=('CC0-1.0',), basis='dedication')
    rights = core(root)['sections']['metadata']['data']['rights'][0]
    assert rights['health'] == 'valid'
    assert matches(rights, mode='public-domain', jurisdiction='US', scope='selected-text')
    assert not matches(rights, mode='public-domain', jurisdiction='AU', scope='selected-text')
    assert matches(rights, mode='cc0', jurisdiction='AU')
    assert matches(rights, mode='public-domain-or-cc0', jurisdiction='AU')
    assert not matches(rights, mode='public-domain', jurisdiction='US', scope='whole-edition')
    report = library_browse_snapshot(root, rights_mode='public-domain-or-cc0', jurisdiction='AU', rights_scope='selected-text')
    assert [w['work_id'] for w in report['works']] == ['alpha']


def test_provider_unspecified_territory_and_conditional_grant_survive_export(root):
    assessment(root, 'provider', territory=(), basis='provider-declaration')
    assessment(root, 'electronic', status='licensed', license_ids=('GPL-3.0-only',), basis='license', condition='if-protectable')
    rights = core(root)['sections']['metadata']['data']['rights'][0]
    assert rights['health'] == 'valid'
    assert not matches(rights, mode='public-domain', jurisdiction='US')
    assert matches(rights, status='licensed', jurisdiction='US')
    exported = export_metadata(root)
    assessments = exported['works'][0]['editions'][0]['rights']['assessments']
    assert any(a['basis'] == 'provider-declaration' and a['jurisdictions'] == [] for a in assessments)
    assert any(a['condition'] == 'if-protectable' for a in assessments)
    assert exported == export_metadata(root)
    assert 'owner' not in json.dumps(exported) and 'research/evidence.md' not in json.dumps(exported)


@pytest.mark.parametrize('mutation', ['material', 'territory_conflict', 'missing_component', 'licensed_component'])
def test_stale_conflicting_or_incomplete_rights_cannot_match(root, mutation):
    path, record = assessment(root, components=('annotation',) if mutation in ('missing_component', 'licensed_component') else ())
    if mutation == 'material':
        write(root / 'library/works/alpha/forms/en/editions/first/rights-subjects/historical-decision.json',
              {'selected': {'included': ['modern introduction']}})
    elif mutation == 'territory_conflict':
        write(path.with_name('conflict.json'), dict(record, record_id='conflict', rights_status='restricted'))
    elif mutation == 'licensed_component':
        assessment(root, 'annotation', status='licensed', license_ids=('CC-BY-4.0',), basis='license')
    result = core(root); rights = result['sections']['metadata']['data']['rights'][0]
    assert rights['health'] == 'invalid' and lookup_exit_code(result) == 3
    assert not matches(rights, mode='public-domain', jurisdiction='US')
    assert library_browse_snapshot(root, rights_mode='public-domain', jurisdiction='US')['works'] == []
    with pytest.raises(PipelineError):
        export_metadata(root)


def test_legacy_config_incompatible_values_are_observations_not_guesses(root):
    write(root / 'sources/example/config.json', {'schema_type': 'structured_text', 'era': 'early-modern', 'audience': 'general'})
    report = metadata_consistency(root)
    differences = [i for i in report['issues'] if i['code'] == 'unsupported-legacy-label']
    assert {i['field'] for i in differences} == {'era', 'audience'}
    assert all(i['canonical'] is None for i in differences)


def test_markdown_evidence_is_hash_bound_without_parsing_prose(root):
    path, record = assessment(root)
    evidence = root / 'research/rights.md'
    evidence.write_text('An attributed research argument.\n', encoding='utf-8')
    record['evidence'] = [binding(root, 'research/rights.md')]
    write(path, record)
    assert core(root)['sections']['metadata']['data']['rights'][0]['health'] == 'valid'
    evidence.write_text('Changed argument.\n', encoding='utf-8')
    assert core(root)['sections']['metadata']['data']['rights'][0]['health'] == 'invalid'


def test_export_rejects_private_information_in_display_fields(root):
    path = root / 'library/works/alpha/work.json'
    work = json.loads(path.read_text()); work['title'] = 'library/works/private-work'
    write(path, work)
    with pytest.raises(PipelineError, match='private path'):
        export_metadata(root)


def test_wrong_edition_material_and_multiple_atomic_grants_are_rejected(root):
    path, record = assessment(root)
    decision = root / 'library/works/alpha/forms/en/editions/first/rights-subjects/historical-decision.json'
    write(decision, {'selected': {'work_id': 'other', 'edition_id': 'other'}})
    subject_path = root / record['subject']['path']
    subject = json.loads(subject_path.read_text());subject['material'] = binding(root, decision.relative_to(root).as_posix(), pointer='/selected')
    write(subject_path, subject);record['subject']['sha256'] = hashlib.sha256(subject_path.read_bytes()).hexdigest();write(path, record)
    assert core(root)['sections']['metadata']['data']['rights'][0]['health'] == 'invalid'
    record.update(rights_status='licensed', basis='license', license_ids=['CC-BY-4.0', 'GPL-3.0-only'])
    write(path, record)
    assert core(root)['sections']['metadata']['data']['rights'][0]['health'] == 'invalid'


@pytest.mark.parametrize('case', ['cc0-restricted', 'cc0-other-license', 'provider-missing', 'self-cycle'])
def test_parent_rights_cannot_broaden_component_findings(root, case):
    if case.startswith('cc0'):
        assessment(root, 'parent', status='licensed', license_ids=('CC0-1.0',), basis='dedication', components=('child',))
        if case == 'cc0-restricted':
            assessment(root, 'child', status='restricted')
        else:
            assessment(root, 'child', status='licensed', license_ids=('CC-BY-4.0',), basis='license')
    elif case == 'provider-missing':
        assessment(root, 'parent', status='mixed', territory=(), basis='provider-declaration', components=('missing',))
    else:
        assessment(root, 'parent', components=('parent',))
    rights = core(root)['sections']['metadata']['data']['rights'][0]
    assert rights['health'] == 'invalid'
    assert not matches(rights, mode='public-domain-or-cc0')
    with pytest.raises(PipelineError):
        export_metadata(root)


def test_export_keeps_public_material_selection_and_qualification(root):
    path, record = assessment(root)
    record['scope_note'] = 'The historical chapter only; the modern introduction is excluded.'
    write(path, record)
    rights = export_metadata(root)['works'][0]['editions'][0]['rights']
    assert rights['subjects'][0]['public_scope']['include'][0]['values'] == ['historical-chapter']
    assert rights['subjects'][0]['public_scope']['exclude'][0]['values'] == ['historical-modern-introduction']
    assert rights['assessments'][0]['scope_note'] == record['scope_note']


def test_conflicting_unspecified_provider_declarations_cannot_match(root):
    path, record = assessment(root, territory=(), basis='provider-declaration')
    write(path.with_name('contradiction.json'), dict(record, record_id='contradiction', rights_status='restricted'))
    rights = core(root)['sections']['metadata']['data']['rights'][0]
    assert rights['health'] == 'invalid' and not matches(rights, mode='public-domain')


def test_task_triage_lifecycle_and_narrative_are_separate(root):
    from ocd_kernel.library.record_connections import _ticket_tasks
    from ocd_kernel.library.record_read import RecordRead
    path = root / 'plans/2026-08-31-library-pipeline-redesign/tickets/simplification/08-current.md'
    path.parent.mkdir(parents=True)
    path.write_text('**Ticket ID:** SIMP-008\n**Work ID:** `alpha`\n**Task applicability:** current\n'
                    '**Triage label:** ready-for-agent\n**Lifecycle:** in-progress\n**Status:** Review is underway\n', encoding='utf-8')
    record = _ticket_tasks(RecordRead(root), {'kind': 'work', 'namespace': 'ocd', 'id': 'alpha'}, [])[0]
    assert record['triage_label'] == 'ready-for-agent' and record['lifecycle'] == 'in-progress'
    assert record['status'] == 'Review is underway' and record['applicability'] == 'current'
    path.write_text(path.read_text().replace('in-progress', 'complete'), encoding='utf-8')
    assert _ticket_tasks(RecordRead(root), {'kind': 'work', 'namespace': 'ocd', 'id': 'alpha'}, [])[0]['applicability'] == 'historical'


def test_form_language_fallback_matches_lookup_browse_export(root):
    path = root / 'library/works/alpha/work.json'
    work = json.loads(path.read_text());del work['textual_forms'][0]['editions'][0]['language'];write(path, work)
    lookup = core(root)['sections']['metadata']['data']['normalized']['editions'][0]['language']
    browse = library_browse_snapshot(root, language='eng')['works'][0]['editions'][0]['language']
    exported = export_metadata(root)['works'][0]['editions'][0]['language']
    assert lookup == browse == exported == {'raw': 'en', 'value': 'en', 'mapping': 'mapped'}


def test_acquisition_read_failure_is_accounted_in_browse_and_export(root, monkeypatch):
    from ocd_kernel.library.record_read import RecordRead
    original = RecordRead.record
    def fail(read, reference, section, loader):
        if reference.endswith('/acquisitions/copy.json'):
            read.issue(section, 'unavailable', reference, 'Fixture read failure')
            return None
        return original(read, reference, section, loader)
    monkeypatch.setattr(RecordRead, 'record', fail)
    report = library_browse_snapshot(root, provider='ccel')
    assert report['counts']['failed'] and any(i['code'] == 'unavailable' for i in report['issues'])
    with pytest.raises(PipelineError):
        export_metadata(root)


@pytest.mark.parametrize('config', [[], {'provenance': []}])
def test_malformed_config_shapes_are_reported(root, config):
    write(root / 'sources/example/config.json', config)
    assert any(i['code'] == 'invalid-source-config' for i in metadata_consistency(root)['issues'])


def test_normalized_rights_do_not_change_legacy_wrapper_or_license(root):
    from ocd_kernel.release.public_rights import SPECS, requires_wrapper
    # Normalized record changes do not enter the legacy wrapper API.
    item_id, spec = next(iter(SPECS.items()))
    before = requires_wrapper(item_id, spec['license_after'])
    assessment(root)
    export_metadata(root)
    assert before == requires_wrapper(item_id, spec['license_after'])
    assert spec['license_before'] != spec['license_after']
