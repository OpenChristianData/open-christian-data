"""Explicit reviewed rights for synthetic release fixtures only."""
import hashlib
import importlib
import json
from pathlib import Path

from ocd_kernel.library._common import PipelineError, canonical_bytes, write_json


def authorize_release_fixture(root: Path, selected: dict) -> None:
    if Path(root).resolve() == Path(__file__).resolve().parents[1]:
        raise AssertionError('synthetic rights must never be written to the repository corpus')
    if 'exclude_reason' in selected:
        return
    from tests.test_release_assembly_v2 import SUPPORTED_CATEGORIES
    if selected['category'] not in SUPPORTED_CATEGORIES:
        return
    acceptance_path = root / selected['acceptance_path']
    try:
        acceptance = json.loads(acceptance_path.read_bytes())
        identity = acceptance['identity']
        module = importlib.import_module('ocd_kernel.projection.categories.' + selected['category'])
        rows = getattr(module, 'project_accepted_' + selected['category'])(root, acceptance_path=acceptance_path)['rows']
        record_ids = [row['record_id'] for row in rows]
    except (PipelineError, OSError, ValueError, KeyError, TypeError):
        # Invalid fixture input cannot receive a grant; the real entry point must reject it.
        return
    base = f"library/works/{identity['work_id']}/forms/{identity['textual_form_id']}/editions/{identity['edition_id']}"
    def bind(reference, **extra):
        return {'path': reference, 'sha256': hashlib.sha256((root / reference).read_bytes()).hexdigest(), **extra}
    decision = base + '/rights-subjects/fixture-decision.json'
    write_json(root / decision, {'selected': {**selected, 'work_id': identity['work_id']}})
    subject = {'schema_version': '2.1', 'subject_id': 'fixture-selected',
               'work_id': identity['work_id'], 'edition_id': identity['edition_id'], 'scope': 'selected-text',
               'material': bind(decision, pointer='/selected'), 'components': [],
               'evidence': [bind(selected['acceptance_path'])],
               'public_scope': {'include': [{'kind': 'record-id', 'values': record_ids}], 'exclude': []}}
    subject_path = base + '/rights-subjects/fixture-selected.json'
    write_json(root / subject_path, subject)
    semantics = {'work_id': identity['work_id'], 'edition_id': identity['edition_id'], 'scope': 'selected-text',
                 'rights_status': 'licensed', 'jurisdictions': ['worldwide'], 'license_ids': ['CC0-1.0'],
                 'basis': 'dedication', 'condition': 'unconditional'}
    normalization = {'contract': 'ocd-rights-normalization-v1', 'item_id': selected['item_id'],
                     'acceptance_path': selected['acceptance_path'], 'effective_license': selected.get('license'),
                     'public_notices': selected.get('public_notices', []), 'assessment': semantics,
                     'subject_id': subject['subject_id'], 'components': subject['components'],
                     'material': subject['material'], 'subject_evidence': subject['evidence'],
                     'public_scope_sha256': hashlib.sha256(canonical_bytes(subject['public_scope'])).hexdigest()}
    proof_path = base + '/rights-subjects/fixture-adoption.json'
    write_json(root / proof_path, {'finding': normalization})
    record = {'schema_version': '2.1', 'record_id': 'fixture-selected-assessment', **semantics,
              'subject': bind(subject_path, id=subject['subject_id']),
              'evidence': [bind(decision), bind(proof_path, pointer='/finding')],
              'assessed_by': 'Synthetic fixture grant', 'assessed_on': '2026-10-20'}
    write_json(root / base / 'rights/fixture-selected-assessment.json', record)
