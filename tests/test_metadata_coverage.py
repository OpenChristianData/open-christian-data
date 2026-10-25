"""Recorded description, explicit gaps and source decisions are separate facts."""
import hashlib
import json

import pytest

from tests.test_library_records import root, write, core
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.record_read import RecordRead
from ocd_kernel.library.identities import validate_record
from ocd_kernel.library.views import library_browse_snapshot
from build.tools.export_library_metadata import export_metadata
from build.tools.report_metadata_consistency import metadata_consistency


def projected_decision(root, *, private=False, member='private-member-id'):
    claim = {'worklist_item_id': 'edition:imprint', 'claim_id': 'private-claim-id',
             'scope': {'member': member, 'entity': 'edition',
                       'predicate': 'imprint', 'event_role': 'publication'},
             'evidence': {'classification': 'unresolved', 'value': None, 'bindings': [],
                          'question': 'Which historical edition is represented?',
                          'evidence_needed': 'A source-attested historical imprint.'},
             'requirement': {'classification': 'useful_optional', 'reason': 'Describe the recorded edition.'},
             'adoption': {'classification': 'not_selected', 'destination': 'none',
                          'reason': 'The historical edition remains unresolved.'},
             'inspection': {'classification': 'inspected', 'owner': 'private-owner'}}
    if private:
        claim['evidence']['evidence_needed'] = 'Read reports/private-review.json'
    sidecar = {'schema_version': 'source-metadata-sidecar-v1', 'writer': 'ocd-source-metadata-v1',
               'batch_id': 'private-batch-id', 'subject': {'kind': 'catalog', 'id': 'alpha'},
               'dimensions': {'edition': {'status': 'inspected', 'owner': 'private-owner', 'fields': [claim]}}}
    path = root / 'metadata/source-evidence/catalog/alpha.json'
    write(path, sidecar)
    write(root / 'metadata/source-evidence/index.json', {
        'schema_version': 'source-metadata-index-v1', 'writer': 'ocd-source-metadata-v1',
        'batch_id': 'private-batch-id', 'counts': {'catalog': 1},
        'subjects': [{'subject': sidecar['subject'], 'path': 'metadata/source-evidence/catalog/alpha.json',
                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]})
    return path


def known_provider(root):
    path = root / 'library/works/alpha/forms/en/editions/first/acquisitions/copy.json'
    value = json.loads(path.read_text(encoding='utf-8')); value['provider'] = 'CCEL'
    write(path, value)
    return path, value


def test_zero_validity_issues_still_exposes_actual_description_gaps(root):
    known_provider(root)
    write(root / 'library/works/identity-only/work.json', {
        'schema_version': '2.0', 'work_id': 'identity-only', 'title': 'Research identity',
        'evidence': ['research/evidence.md'], 'textual_forms': []})
    report = metadata_consistency(root)
    assert report['issues'] == []
    counts = report['completeness']['counts']
    assert counts['identity_only_works'] == 1
    assert counts['works_without_creators'] == 2
    assert counts['editions_without_scoped_rights'] == 2
    assert counts['declared_editions_without_master'] == 2
    assert report['completeness']['source_accuracy'] == 'not_assessed'
    assert export_metadata(root)['coverage'] == report['completeness']
    lookup = core(root)
    validate_record('library-record', lookup)
    assert lookup['sections']['metadata']['data']['normalized']['coverage']['counts']['works_without_creators'] == 1


def test_completeness_changes_with_actual_canonical_credit_and_language(root):
    known_provider(root)
    path = root / 'library/works/alpha/work.json'
    work = json.loads(path.read_text(encoding='utf-8'))
    work['creators'] = [{'name': 'Recorded contributor', 'role': 'author'}]
    del work['textual_forms'][1]['language']
    del work['textual_forms'][1]['editions'][0]['language']
    write(path, work)
    before = metadata_consistency(root)['completeness']['counts']
    assert before['unscoped_contributors'] == before['editions_without_language'] == 1
    work['creators'][0]['scope'] = {'kind': 'work', 'id': 'alpha'}
    work['textual_forms'][1]['language'] = 'fr'
    write(path, work)
    after = metadata_consistency(root)['completeness']['counts']
    assert after['works_without_creators'] == after['unscoped_contributors'] == after['editions_without_language'] == 0


def test_export_carries_recorded_titles_sources_and_terms_without_reading_master(root):
    path, acquisition = known_provider(root)
    acquisition['rights'] = 'Source terms: https://example.org/terms'
    write(path, acquisition)
    work_path = root / 'library/works/alpha/work.json'
    work = json.loads(work_path.read_text(encoding='utf-8'))
    work['textual_forms'][0]['title'] = 'Recorded English form'
    work['textual_forms'][0]['editions'][0]['containing_source'] = {
        'title': 'Recorded source container', 'locator': 'Volume I, title page',
        'evidence': ['research/evidence.md']}
    write(work_path, work)
    master = path.parent.parent / 'master.tei.xml'
    master.write_bytes(b'Deliberately not XML: default metadata must not parse this body.')
    result = export_metadata(root)
    edition = result['works'][0]['editions'][0]
    assert result['contract'] == 'ocd-library-metadata-v3'
    assert edition['title'] == 'First witness'
    assert edition['form_title'] == 'Recorded English form'
    assert edition['containing_source']['title'] == 'Recorded source container'
    assert edition['sources'][0]['url'] == 'https://example.org/source'
    assert edition['sources'][0]['recorded_rights_statement'] == acquisition['rights']
    assert edition['sources'][0]['rights_interpretation'] == 'provider_statement_only'
    assert edition['coverage']['availability'] == 'observed_master'
    assert edition['coverage']['text_integrity'] == 'not_assessed'
    assert edition['rights']['coverage'] == 'not_recorded'


@pytest.mark.parametrize('member', ['private-member-id', 'reports/private-member.json'])
def test_existing_unresolved_decision_remains_visible_without_private_bindings(root, member):
    known_provider(root); projected_decision(root, private=True, member=member)
    result = export_metadata(root)
    metadata = result['works'][0]['source_metadata']
    assert metadata['coverage'] == 'recorded_subjects_only'
    assert metadata['claims'][0]['question'] == 'Which historical edition is represented?'
    assert metadata['claims'][0]['evidence_needed'] is None
    assert metadata['claims'][0]['recorded_adoption'] == {'classification': 'not_selected', 'destination': 'none'}
    assert metadata['claims'][0]['subject'] == {'kind': 'catalog', 'id': 'alpha'}
    assert metadata['claims'][0]['scope'] == {'member': member if not member.startswith('reports/') else None, 'entity': 'edition',
                                             'predicate': 'imprint', 'event_role': 'publication'}
    assert metadata['withheld_private_fields'] == 1 + member.startswith('reports/')
    assert result['coverage']['counts']['unresolved_metadata_claims'] == 1
    encoded = json.dumps(result)
    assert 'private-claim-id' not in encoded and 'private-owner' not in encoded
    assert 'reports/' not in encoded and 'source-evidence/' not in encoded
    assert core(root)['sections']['metadata']['data']['normalized']['source_metadata'] == metadata


def test_stale_indexed_projection_blocks_export_instead_of_becoming_a_gap(root):
    known_provider(root); path = projected_decision(root)
    value = json.loads(path.read_text(encoding='utf-8'))
    value['dimensions']['edition']['fields'][0]['evidence']['question'] = 'Changed without index update'
    write(path, value)
    assert any(issue['severity'] == 'error' for issue in metadata_consistency(root)['issues'])
    with pytest.raises(PipelineError, match='valid declared records'):
        export_metadata(root)


def test_private_provider_terms_are_accounted_for_without_public_disclosure(root):
    path, acquisition = known_provider(root)
    acquisition['rights'] = 'See reports/internal-terms.md'
    write(path, acquisition)
    source = export_metadata(root)['works'][0]['editions'][0]['sources'][0]
    assert source['rights_statement_recorded'] is True
    assert source['recorded_rights_statement'] is None


def test_only_metadata_selection_material_is_readable_under_exports(root):
    selection = 'exports/frozen-release/internal/release-selection.json'
    write(root / selection, {'recorded': 'selection'})
    reader = RecordRead(root)
    assert json.loads(reader.bytes(selection, 'metadata')) == {'recorded': 'selection'}
    assert reader.inputs[selection]['sha256'] == hashlib.sha256((root / selection).read_bytes()).hexdigest()
    for kind in ('projection-receipts', 'public-row-transforms'):
        reference = f'exports/frozen-release/internal/{kind}/item.json'
        write(root / reference, {'kind': kind})
        assert json.loads(reader.bytes(reference, 'metadata')) == {'kind': kind}
    for reference, section in [(selection, 'holdings'),
                               ('exports/frozen-release/public/data/prose/train.jsonl', 'metadata'),
                               ('exports/frozen-release/internal/other.json', 'metadata'),
                               ('raw/internal/release-selection.json', 'metadata')]:
        with pytest.raises(PipelineError, match='cannot read a text body'):
            reader.bytes(reference, section)


def test_containing_source_exports_title_without_retained_locator(root):
    path = root / 'library/works/alpha/work.json'
    work = json.loads(path.read_text())
    work['textual_forms'][0]['editions'][0]['containing_source'] = {
        'title': 'Collected works', 'locator': 'raw/provider/collection.xml',
        'evidence': ['research/evidence.md']}
    write(path, work)
    edition = export_metadata(root)['works'][0]['editions'][0]
    assert edition['containing_source'] == {'title': 'Collected works'}
