"""Reconcile selected public material with its normalized rights finding."""
from __future__ import annotations

from pathlib import Path

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.record_read import RecordRead
from ocd_kernel.library.rights import _bound, collect_rights


def require_release_rights(root: Path, selected: dict, identity: dict, rows: list[dict]) -> None:
    read = RecordRead(Path(root))
    rights = collect_rights(read, identity['work_id'], identity['textual_form_id'], identity['edition_id'])
    if rights['health'] != 'valid':
        raise PipelineError('release requires valid normalized rights for the selected edition')
    subjects = {subject['subject_id']: subject for subject in rights['subjects']}
    findings = {}
    for item in rights['records']:
        findings.setdefault(item['record']['subject']['id'], []).append(item)
    row_ids = [row.get('record_id') for row in rows]
    if not row_ids or any(not isinstance(value, str) for value in row_ids) or len(set(row_ids)) != len(row_ids):
        raise PipelineError('release rights require nonempty distinct public record IDs')
    for item in rights['records']:
        record = item['record']
        if record['scope'] != 'selected-text' or record['rights_status'] not in ('public-domain', 'licensed', 'mixed'):
            continue
        subject = subjects[record['subject']['id']]
        if any(sibling['record']['rights_status'] not in ('public-domain', 'licensed', 'mixed')
               for sibling in findings[subject['subject_id']]):
            raise PipelineError('selected rights contain an unresolved territorial assessment')
        normalization = item['normalization']
        if normalization is None:
            continue
        if (normalization.get('item_id') != selected['item_id']
                or normalization.get('acceptance_path') != selected['acceptance_path']
                or normalization.get('effective_license') != selected.get('license')
                or normalization.get('public_notices') != selected.get('public_notices', [])):
            raise PipelineError('selected output differs from its reviewed rights normalization')
        material = _bound(read, subject['material'], document=True)
        if not isinstance(material, dict) or material.get('item_id') != selected['item_id']:
            continue
        if material.get('acceptance_path') != selected['acceptance_path'] or material.get('work_id') != identity['work_id']:
            raise PipelineError('normalized rights material differs from selected identity')
        if material.get('license_after', material.get('license')) != selected.get('license'):
            raise PipelineError('selected license differs from normalized rights material')
        if material.get('public_notices', []) != selected.get('public_notices', []):
            raise PipelineError('selected notices differ from normalized rights material')
        include, exclude = subject['public_scope']['include'], subject['public_scope']['exclude']
        if any(selector['kind'] != 'record-id' for selector in include + exclude):
            raise PipelineError('release rights require explicit public record IDs')
        covered = {value for selector in include for value in selector['values']}
        omitted = {value for selector in exclude for value in selector['values']}
        if not set(row_ids) <= covered - omitted:
            raise PipelineError('public rows exceed normalized rights material')
        pending = list(subject['components'])
        while pending:
            child = pending.pop()
            if any(finding['record']['rights_status'] not in ('public-domain', 'licensed', 'mixed')
                   or finding['normalization'] is None for finding in findings[child]):
                raise PipelineError('selected mixed rights include an unresolved component')
            pending.extend(subjects[child]['components'])
        if not read.stable():
            raise PipelineError('normalized rights changed during release verification')
        return
    raise PipelineError('no positive normalized rights finding covers this selected public material')
