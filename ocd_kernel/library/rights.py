"""Load attributed rights assessments; never classify rights from prose."""
from __future__ import annotations

import json

from ._common import PipelineError, _reject_duplicate_keys, _read_inputs
from .identities import validate_record, schema_enum


def _json(read, path, *, body=None):
    body = read.bytes(path, 'metadata') if body is None else body
    if body is None:
        raise PipelineError(f'rights input unavailable: {path}')
    cache = _read_inputs.get()
    key = ('rights-json', read.inputs[path]['sha256'])
    if cache is not None and key in cache:
        return cache[key]
    value = json.loads(body.decode('utf-8'), object_pairs_hook=_reject_duplicate_keys)
    if cache is not None:
        cache[key] = value
    return value


def _bound(read, binding, *, document=False):
    body = read.bytes(binding['path'], 'metadata')
    if body is None:
        raise PipelineError(f'rights input unavailable: {binding["path"]}')
    if read.inputs[binding['path']]['sha256'] != binding['sha256']:
        raise PipelineError(f'stale rights binding: {binding["path"]}')
    if not document and 'pointer' not in binding:
        return body
    document = _json(read, binding['path'], body=body)
    for part in binding.get('pointer', '').split('/')[1:]:
        token = part.replace('~1', '/').replace('~0', '~')
        try:
            if isinstance(document, list) and (not token.isdecimal() or token != str(int(token))):
                raise ValueError('invalid array pointer')
            document = document[int(token)] if isinstance(document, list) else document[token]
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise PipelineError(f'rights pointer unavailable: {binding["path"]}#{binding.get("pointer", "")}') from exc
    return document


def collect_rights(read, work_id: str, form_id: str, edition_id: str) -> dict:
    base = f'library/works/{work_id}/forms/{form_id}/editions/{edition_id}/rights'
    names = read.members(base, '*.json', 'metadata', optional=True)
    records, subjects, errors = [], {}, []
    discovery = read.discovery[(base, '*.json')]
    if discovery['health'] != 'valid':
        return {'health': 'unavailable', 'coverage': 'unavailable', 'records': [], 'subjects': [],
                'issues': [{'path': base, 'code': 'unavailable-rights-population', 'message': 'rights directory cannot be inspected'}]}
    for name in names:
        path = f'{base}/{name}'
        try:
            record = _json(read, path)
            validate_record('rights-record', record, context=path)
            if record['work_id'] != work_id or record['edition_id'] != edition_id:
                raise PipelineError('rights assessment identity differs from its edition')
            subject = _bound(read, record['subject'], document=True)
            validate_record('rights-subject', subject, context=record['subject']['path'])
            if any(subject[key] != record[key] for key in ('work_id', 'edition_id', 'scope')):
                raise PipelineError('rights subject identity/scope differs')
            if subject['subject_id'] != record['subject']['id']:
                raise PipelineError('rights subject ID differs')
            if record['rights_status'] in ('public-domain', 'licensed', 'mixed') and not subject['public_scope']['include']:
                raise PipelineError('positive rights finding requires explicitly included material')
            material = _bound(read, subject['material'])
            if isinstance(material, dict) and any(material.get(key, record[key]) != record[key] for key in ('work_id', 'edition_id')):
                raise PipelineError('rights material points at a different edition/work')
            if isinstance(material, dict) and 'acceptance_path' in material and material['acceptance_path'] != base.removesuffix('/rights') + '/acceptance.json':
                raise PipelineError('rights material points at a different accepted edition')
            normalization = None
            for evidence in record['evidence']:
                observed = _bound(read, evidence)
                if isinstance(observed, dict) and observed.get('contract') == 'ocd-rights-normalization-v1':
                    from ._common import canonical_bytes, sha256_bytes
                    expected = {key: record[key] for key in
                                ('work_id', 'edition_id', 'scope', 'rights_status', 'jurisdictions',
                                 'license_ids', 'basis', 'condition')}
                    if (observed.get('assessment') != expected or observed.get('subject_id') != subject['subject_id']
                            or observed.get('components') != subject['components']
                            or observed.get('material') != subject['material']
                            or observed.get('public_scope_sha256') != sha256_bytes(canonical_bytes(subject['public_scope']))
                            or observed.get('subject_evidence') != subject.get('evidence', [])):
                        raise PipelineError('rights finding differs from its reviewed normalization receipt')
                    if normalization is not None and normalization != observed:
                        raise PipelineError('conflicting rights normalization receipts')
                    normalization = observed
            for binding in subject.get('evidence', []):
                _bound(read, binding)
            identifier = subject['subject_id']
            if identifier in subjects and subjects[identifier] != subject:
                raise PipelineError('conflicting definitions of rights subject')
            subjects[identifier] = subject
            records.append({'owner': path, 'record': record, 'normalization': normalization})
        except (PipelineError, OSError, UnicodeError, ValueError) as exc:
            errors.append({'path': path, 'code': 'invalid-rights-record', 'message': str(exc)})
    ids = [item['record']['record_id'] for item in records]
    if len(ids) != len(set(ids)):
        errors.append({'path': base, 'code': 'duplicate-rights-assessment', 'message': 'duplicate assessment IDs'})
    for index, item in enumerate(records):
        a = item['record']
        for other in records[index + 1:]:
            b = other['record']
            territories_overlap = (not a['jurisdictions'] and not b['jurisdictions']) or bool(set(a['jurisdictions']) & set(b['jurisdictions'])) or (
                bool(a['jurisdictions']) and bool(b['jurisdictions']) and 'worldwide' in a['jurisdictions'] + b['jurisdictions'])
            if a['subject']['id'] == b['subject']['id'] and territories_overlap and any(
                    a[key] != b[key] for key in ('rights_status', 'license_ids', 'basis', 'condition')):
                errors.append({'path': base, 'code': 'conflicting-rights-assessment', 'message': a['record_id'] + ' / ' + b['record_id']})
        components = subjects[a['subject']['id']]['components']
        if components:
            child_records = [r['record'] for r in records if r['record']['subject']['id'] in components]
            for country in a['jurisdictions'] or [None]:
                children = [r for r in child_records if
                            (country is None and a['rights_status'] not in ('public-domain', 'licensed')) or
                            (not r['jurisdictions'] if country is None else country in r['jurisdictions']) or
                            'worldwide' in r['jurisdictions']]
                if set(r['subject']['id'] for r in children) != set(components):
                    errors.append({'path': item['owner'], 'code': 'incomplete-rights-components', 'message': country or 'unspecified territory'})
                if a['rights_status'] == 'public-domain' and any(r['rights_status'] != 'public-domain' or r['condition'] != 'unconditional' for r in children):
                    errors.append({'path': item['owner'], 'code': 'broadened-rights-components', 'message': country or 'unspecified territory'})
                if a['rights_status'] == 'licensed' and any(r['rights_status'] != 'licensed' or r['license_ids'] != a['license_ids'] or
                        a['condition'] == 'unconditional' and r['condition'] != 'unconditional' for r in children):
                    errors.append({'path': item['owner'], 'code': 'broadened-rights-components', 'message': country or 'unspecified territory'})
        elif a['rights_status'] == 'mixed':
            errors.append({'path': item['owner'], 'code': 'missing-rights-components', 'message': 'mixed finding requires explicit components'})
    def cyclic(subject_id, ancestors):
        if subject_id in ancestors:
            return True
        return any(cyclic(child, ancestors | {subject_id}) for child in subjects.get(subject_id, {}).get('components', []))
    if any(cyclic(identifier, set()) for identifier in subjects):
        errors.append({'path': base, 'code': 'cyclic-rights-components', 'message': 'component graph contains a cycle'})
    # A malformed or conflicting sibling makes the edition join incomplete.
    return {'health': 'invalid' if errors else 'valid' if records else 'not_assessed',
            'coverage': 'invalid' if errors else 'recorded_subjects_only' if records else 'not_recorded',
            'records': records, 'subjects': list(subjects.values()), 'issues': errors}


def matches(rights: dict, *, mode: str | None = None, status: str | None = None,
            jurisdiction: str | None = None, scope: str | None = None) -> bool:
    if rights['health'] != 'valid':
        return False
    for item in rights['records']:
        record = item['record']
        if jurisdiction and jurisdiction not in record['jurisdictions'] and 'worldwide' not in record['jurisdictions']:
            continue
        if scope and record['scope'] != scope or status and record['rights_status'] != status:
            continue
        public_domain = record['rights_status'] == 'public-domain'
        cc0 = record['rights_status'] == 'licensed' and record['license_ids'] == ['CC0-1.0']
        if mode is not None and record['condition'] != 'unconditional':
            continue
        if mode == 'public-domain' and not public_domain or mode == 'cc0' and not cc0:
            continue
        if mode == 'public-domain-or-cc0' and not (public_domain or cc0):
            continue
        return True
    return False


def validate_filters(mode=None, status=None, jurisdiction=None, scope=None):
    for value, definition in ((mode, 'query_mode'), (status, 'rights_status'), (scope, 'scope')):
        if value is not None and value not in schema_enum('rights-record', definition):
            raise PipelineError(f'unknown rights {definition}: {value}')
    if jurisdiction is not None:
        import re
        if re.fullmatch('[A-Z]{2}|worldwide', jurisdiction) is None:
            raise PipelineError('rights jurisdiction requires an uppercase country code or worldwide')


def public_rights(rights: dict) -> dict:
    return {'health': rights['health'], 'coverage': rights['coverage'],
            'subjects': [{key: subject[key] for key in ('subject_id', 'scope', 'components', 'public_scope')}
                         for subject in rights['subjects']] if rights['health'] == 'valid' else [],
            'assessments': [{key: item['record'][key] for key in
                            ('record_id', 'scope', 'rights_status', 'jurisdictions', 'license_ids', 'basis', 'condition', 'assessed_on')
                            if key in item['record']}
                           | {'subject_id': item['record']['subject']['id']}
                           | ({'scope_note': item['record']['scope_note']} if 'scope_note' in item['record'] else {})
                           for item in rights['records']] if rights['health'] == 'valid' else []}
