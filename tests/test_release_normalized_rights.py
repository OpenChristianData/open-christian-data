"""Fresh releases must reconcile their material with normalized rights."""
import json

import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes, sha256_bytes
from ocd_kernel.release.rights import require_release_rights
from tests.test_library_records import root, write, core
from ocd_kernel.library.rights import matches
from tests.test_standardized_metadata import assessment, binding


@pytest.fixture
def selected_rights(root):
    path, record = assessment(root)
    selected = {'item_id': 'alpha-first', 'work_id': 'alpha',
                'acceptance_path': 'library/works/alpha/forms/en/editions/first/acceptance.json',
                'license': 'Public domain (United States)',
                'public_notices': [{'notice_path': 'data/prose/README.md'}]}
    subject_path = root / record['subject']['path']
    subject = json.loads(subject_path.read_text())
    decision_path = subject['material']['path']
    write(root / decision_path, {'selected': selected})
    subject['material'] = binding(root, decision_path, pointer='/selected')
    write(subject_path, subject)
    record['subject'] = binding(root, record['subject']['path'], id=subject['subject_id'])
    record['evidence'] = [binding(root, decision_path)]
    proof = {'contract': 'ocd-rights-normalization-v1', 'item_id': selected['item_id'],
             'acceptance_path': selected['acceptance_path'], 'effective_license': selected['license'],
             'public_notices': selected['public_notices'], 'subject_id': subject['subject_id'],
             'components': subject['components'], 'material': subject['material'], 'subject_evidence': [],
             'public_scope_sha256': sha256_bytes(canonical_bytes(subject['public_scope'])),
             'assessment': {key: record[key] for key in
                            ('work_id', 'edition_id', 'scope', 'rights_status', 'jurisdictions',
                             'license_ids', 'basis', 'condition')}}
    write(root / 'reports/adoption.json', {'findings': [proof]})
    record['evidence'].append(binding(root, 'reports/adoption.json', pointer='/findings/0'))
    write(path, record)
    identity = {'work_id': 'alpha', 'textual_form_id': 'en', 'edition_id': 'first'}
    return selected, identity, [{'record_id': 'historical-chapter'}], root / decision_path


def test_exact_material_and_covered_subset_pass(root, selected_rights):
    selected, identity, rows, _ = selected_rights
    require_release_rights(root, selected, identity, rows)


@pytest.mark.parametrize('change', ['added-row', 'wrong-edition', 'license', 'notice', 'stale-material', 'no-rows'])
def test_changed_or_uncovered_selection_fails(root, selected_rights, change):
    selected, identity, rows, decision = selected_rights
    if change == 'added-row':
        rows.append({'record_id': 'new-modern-introduction'})
    elif change == 'wrong-edition':
        identity['edition_id'] = 'second'
    elif change == 'license':
        selected = dict(selected, license='CC0-1.0')
    elif change == 'notice':
        selected = dict(selected, public_notices=[])
    elif change == 'stale-material':
        write(decision, {'selected': {}})
    elif change == 'no-rows':
        rows = []
    with pytest.raises(PipelineError):
        require_release_rights(root, selected, identity, rows)


@pytest.mark.parametrize('status', ['mixed', 'undetermined'])
def test_unspecified_parent_preserves_component_territories(root, status):
    assessment(root, 'combined', status=status, territory=(), basis='provider-declaration',
               components=('historical', 'digital'))
    assessment(root, 'historical', territory=('US',))
    assessment(root, 'digital', status='licensed', territory=('worldwide',),
               license_ids=('CC-BY-4.0',), basis='license')
    rights = core(root)['sections']['metadata']['data']['rights'][0]
    assert rights['health'] == 'valid'
    assert matches(rights, status=status)
    assert not matches(rights, status=status, jurisdiction='US')
    assert matches(rights, mode='public-domain', jurisdiction='US')
    assert not matches(rights, mode='public-domain', jurisdiction='AU')


@pytest.mark.parametrize('change', ['license', 'territory', 'scope-ids', 'missing-proof'])
def test_changed_normalized_finding_requires_a_reviewed_successor(root, selected_rights, change):
    selected, identity, rows, _ = selected_rights
    path = next((root / 'library/works/alpha/forms/en/editions/first/rights').glob('*.json'))
    record = json.loads(path.read_text())
    if change == 'license':
        record.update(rights_status='licensed', license_ids=['CC0-1.0'], basis='dedication')
    elif change == 'territory':
        record['jurisdictions'] = ['worldwide']
    elif change == 'missing-proof':
        record['evidence'] = record['evidence'][:-1]
    else:
        subject_path = root / record['subject']['path']
        subject = json.loads(subject_path.read_text())
        subject['public_scope']['include'][0]['values'].append('added-modern-text')
        write(subject_path, subject)
        record['subject'] = binding(root, record['subject']['path'], id=subject['subject_id'])
    write(path, record)
    with pytest.raises(PipelineError):
        require_release_rights(root, selected, identity, rows)


def test_second_territorial_assessment_is_preserved_and_blocks_unqualified_release(root, selected_rights):
    selected, identity, rows, _ = selected_rights
    directory = root / 'library/works/alpha/forms/en/editions/first/rights'
    record = json.loads(next(directory.glob('*.json')).read_text())
    sibling = dict(record, record_id='historical-AU', jurisdictions=['AU'], rights_status='restricted')
    proof = json.loads((root / 'reports/adoption.json').read_text())['findings'][0]
    proof['assessment'].update(jurisdictions=['AU'], rights_status='restricted')
    write(root / 'reports/australian-adoption.json', {'finding': proof})
    sibling['evidence'] = record['evidence'][:-1] + [binding(root, 'reports/australian-adoption.json', pointer='/finding')]
    write(directory / 'historical-AU.json', sibling)
    rights = core(root)['sections']['metadata']['data']['rights'][0]
    assert rights['health'] == 'valid' and len(rights['records']) == 2
    assert matches(rights, mode='public-domain', jurisdiction='US')
    assert not matches(rights, mode='public-domain', jurisdiction='AU')
    with pytest.raises(PipelineError, match='territorial'):
        require_release_rights(root, selected, identity, rows)


def test_assembly_and_verification_require_the_reviewed_rights(tmp_path):
    from tests.test_release_assembly_v2 import _promoted_category, _item, _selection
    from ocd_kernel.release.assemble import assemble_release_v2
    from ocd_kernel.release.verify import verify_release_v2
    fixture, acceptance = _promoted_category(tmp_path, 'quotations', 'normalized-rights')
    selection = _selection(_item(fixture, 'quote', 'quotations', acceptance))
    release = tmp_path / 'release'
    assert assemble_release_v2(fixture, release, selection=selection)['status'] == 'pass'
    assert verify_release_v2(fixture, release, selection=selection)['status'] == 'pass'
    path = next((fixture / 'library/works').glob('*/forms/*/editions/*/rights/*.json'))
    record = json.loads(path.read_bytes())
    record['jurisdictions'] = ['US']
    write(path, record)
    checked = verify_release_v2(fixture, release, selection=selection)
    assert checked['status'] == 'fail' and any('normalized rights' in error for error in checked['errors'])
    from tests.test_release_assembly_v2 import _failed_release
    rebuilt, diagnostic = _failed_release(fixture, tmp_path / 'changed-rights-release', selection=selection)
    assert rebuilt['status'] == 'fail' and rebuilt['accounting']['failed'] == 1


def test_empty_unassessed_material_is_valid_but_an_empty_positive_sibling_invalidates_the_join(root):
    path, record = assessment(root, 'unassessed', status='not-assessed', territory=(), basis='not-assessed')
    subject_path = root / record['subject']['path']
    subject = json.loads(subject_path.read_bytes())
    subject['public_scope']['include'] = []
    write(subject_path, subject)
    record['subject'] = binding(root, record['subject']['path'], id=subject['subject_id'])
    record['evidence'] = []
    write(path, record)
    rights = core(root)['sections']['metadata']['data']['rights'][0]
    assert rights['health'] == 'valid' and not matches(rights, mode='public-domain-or-cc0')
    positive_path, positive = assessment(root, 'invalid-positive')
    positive_subject = root / positive['subject']['path']
    value = json.loads(positive_subject.read_bytes())
    value['public_scope']['include'] = []
    write(positive_subject, value)
    positive['subject'] = binding(root, positive['subject']['path'], id=value['subject_id'])
    write(positive_path, positive)
    rights = core(root)['sections']['metadata']['data']['rights'][0]
    assert rights['health'] == 'invalid' and not matches(rights, mode='public-domain-or-cc0')
    assert any('positive rights finding requires' in issue['message'] for issue in rights['issues'])
