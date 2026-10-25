"""Canonical query labels from current authoritative metadata."""
from __future__ import annotations

import json
from pathlib import Path

from ._common import PipelineError, read_input_bytes, _reject_duplicate_keys
from .identities import validate_record, resolve_edition_language

PROFILE = Path(__file__).resolve().parents[2] / 'schemas/v2/metadata-labels.json'


def profile() -> dict:
    return validate_record('metadata-labels', json.loads(read_input_bytes(PROFILE).decode('utf-8'),
                            object_pairs_hook=_reject_duplicate_keys), context=str(PROFILE))


def label(kind: str, raw: str | None, *, vocabulary: dict | None = None) -> dict:
    vocabulary = vocabulary or profile()
    values = vocabulary[kind]
    key = raw.strip().casefold() if isinstance(raw, str) else None
    result = {'raw': raw, 'value': values.get(key),
              'mapping': 'mapped' if key in values else 'missing' if raw is None else 'unmapped'}
    if kind == 'providers' and result['value'] in vocabulary.get('provider_sets', {}):
        result.update(vocabulary['provider_sets'][result['value']])
    if kind == 'formats' and key in vocabulary.get('format_descriptions', {}):
        result.update(vocabulary['format_descriptions'][key])
    return result


def creators(work: dict, vocabulary: dict) -> list[dict]:
    return [{'name': c['name'], 'role': label('roles', c.get('role'), vocabulary=vocabulary),
             'scope': c.get('scope'), 'evidence': c.get('evidence', [])}
            for c in work.get('creators', [])]


def work_labels(work: dict, vocabulary: dict) -> dict:
    return {'profile': vocabulary['version'], 'creators': creators(work, vocabulary),
            'description': {'title': work['title'],
                            'original_language': work.get('original_language', {}).get('value'),
                            'work_kind': work.get('work_kind', {}).get('value'),
                            'evidence_and_adoption': 'not_reverified'},
            'editions': [{'textual_form_id': form['textual_form_id'], 'edition_id': edition['edition_id'],
                          'title': edition['title'], 'form_title': form.get('title'),
                          'containing_source': {key: edition['containing_source'][key] for key in ('title', 'locator')}
                                               if 'containing_source' in edition else None,
                          'language': label('languages', resolve_edition_language(work, edition, form['textual_form_id']), vocabulary=vocabulary),
                          'download_category': edition.get('category', form.get('category'))}
                         for form in work['textual_forms'] for edition in form['editions']],
            'facets': work.get('facets', [])}


def public_value(value):
    """Keep literal recorded values only when the existing public scanner permits them."""
    from ocd_kernel.release.public_allowlist import _scan
    return None if _scan(value, 'metadata description') else value


def acquisition_description(acquisition: dict, vocabulary: dict) -> dict:
    """Expose provider declarations without turning them into rights assessments."""
    url = acquisition['url']
    return {'provider': label('providers', acquisition['provider'], vocabulary=vocabulary),
            'url': public_value(url) if url.startswith(('https://', 'http://')) else None,
            'accessed_at': acquisition.get('accessed_at'),
            'recorded_rights_statement': public_value(acquisition.get('rights')),
            'rights_statement_recorded': 'rights' in acquisition,
            'rights_interpretation': 'provider_statement_only'}


def metadata_decisions(read, work: dict, subjects: list[dict] | None = None) -> dict:
    """Read existing indexed decisions; never reclassify or adopt their claims.

    The source-metadata engine owns schema, exact index/sidecar binding and
    semantic descriptor validation. Source text and adoption targets are not
    read here. Explicit aliases can be supplied by their existing owner.
    """
    from build.lib.source_metadata import lookup_sidecar, sidecar_relative_path, MetadataError, SCHEMA_PATH, _validate_schema
    index_path = 'metadata/source-evidence/index.json'
    result = {'coverage': 'not_recorded', 'claims': [], 'withheld_private_fields': 0,
              'inspection': 'indexed projections only; source evidence and adoption not reverified'}
    if not read.observe(index_path)['present']:
        return result
    if read.bytes('@runtime/source-metadata.schema.json', 'metadata', physical=SCHEMA_PATH) is None:
        raise PipelineError('source metadata schema is unavailable')
    body = read.bytes(index_path, 'metadata')
    if body is None:
        raise PipelineError('metadata source-evidence index is unavailable')
    try:
        index = json.loads(body.decode('utf-8'), object_pairs_hook=_reject_duplicate_keys)
        _validate_schema(index, kind='index')
        requested = list(subjects) if subjects is not None else [{'kind': 'catalog', 'id': work['work_id']}]
        exact_references = {reference.partition('#')[0] for reference in work.get('evidence', [])
                            if reference.startswith('metadata/source-evidence/catalog/')}
        indexed_references = {entry['path'] for entry in index['subjects']}
        if not exact_references <= indexed_references:
            raise MetadataError('work references an unindexed metadata projection')
        requested += [entry['subject'] for entry in index['subjects'] if entry['path'] in exact_references]
        requested += [work[key]['source_metadata_subject'] for key in ('original_language', 'work_kind') if key in work]
        seen = set()
        for subject in requested:
            key = (subject['kind'], subject['id'])
            if key in seen:
                continue
            seen.add(key)
            if not any(entry['subject'] == subject for entry in index['subjects']):
                continue
            relative = sidecar_relative_path(subject)
            if read.bytes(relative, 'metadata') is None:
                raise PipelineError('indexed metadata projection is unavailable')
            sidecar = lookup_sidecar(read.root, *key)
            result['coverage'] = 'recorded_subjects_only'
            for dimension, payload in sidecar['dimensions'].items():
                for claim in payload.get('fields', []):
                    evidence, adoption = claim['evidence'], claim['adoption']
                    row = {'dimension': dimension, 'subject': public_value(subject),
                           'scope': {key: public_value(value) for key, value in claim['scope'].items()},
                           'evidence_status': evidence['classification'],
                           'recorded_adoption': {key: adoption[key] for key in ('classification', 'destination')},
                           'semantics': {key: value for key, value in claim.get('semantics', {}).items()
                                         if key in ('kind', 'predicate', 'scope', 'role', 'event')}}
                    result['withheld_private_fields'] += sum(value is not None and row['scope'][key] is None
                                                             for key, value in claim['scope'].items())
                    for name, value in (('value', evidence.get('value')), ('question', evidence.get('question')),
                                        ('evidence_needed', evidence.get('evidence_needed')),
                                        ('adoption_reason', adoption.get('reason')),
                                        ('requirement_reason', claim['requirement'].get('reason'))):
                        safe = public_value(value)
                        result['withheld_private_fields'] += value is not None and safe is None
                        row[name] = safe
                    # Semantic descriptors can contain private member references.
                    if public_value(row['semantics']) is None:
                        row['semantics'] = None
                    result['claims'].append(row)
    except (MetadataError, UnicodeError, ValueError) as exc:
        raise PipelineError(f'invalid source metadata projection: {exc}') from exc
    return result


def edition_coverage(master: bool, acceptance: bool, stage: str | None) -> dict:
    return {'availability': 'declared_no_master' if not master else
            'recorded_accepted_master_present' if acceptance and stage == 'accepted' else 'observed_master',
            'master_present': master, 'acceptance_record_present': acceptance,
            'recorded_stage': stage, 'text_integrity': 'not_assessed',
            'acceptance_and_release_eligibility': 'not_reverified'}


def coverage_summary(works: list[dict]) -> dict:
    """Keep missing assertions separate from validity and source-accuracy checks."""
    counts = dict.fromkeys(('identity_only_works', 'works_without_creators', 'unscoped_contributors',
                            'editions_without_language', 'editions_without_scoped_rights',
                            'editions_with_unresolved_rights',
                            'declared_editions_without_master', 'recorded_accepted_masters_present',
                            'unresolved_metadata_claims', 'contradicted_metadata_claims',
                            'unapplied_metadata_claims'), 0)
    findings = []
    for work in works:
        normalized = work.get('normalized', {})
        if work.get('identity_status', 'valid') != 'valid':
            continue
        def missing(code, **identity):
            counts[code] += 1
            findings.append({'code': code, 'work_id': work['work_id'], **identity})
        if work['form_count'] == 0:
            missing('identity_only_works')
        if not normalized.get('creators'):
            missing('works_without_creators')
        for number, creator in enumerate(normalized.get('creators', [])):
            if creator['scope'] is None:
                missing('unscoped_contributors', contributor=number)
        for edition in work['editions']:
            identity = {'edition_id': edition['edition_id']}
            if edition['language']['mapping'] == 'missing':
                missing('editions_without_language', **identity)
            if edition['rights']['coverage'] == 'not_recorded':
                missing('editions_without_scoped_rights', **identity)
            if edition['rights']['health'] == 'not_assessed' or any(
                    item['record']['rights_status'] in ('not-assessed', 'undetermined') for item in edition['rights']['records']):
                counts['editions_with_unresolved_rights'] += 1
            if not edition['observed_master_presence']:
                missing('declared_editions_without_master', **identity)
            elif edition['observed_acceptance_presence'] and edition['recorded_stage'] == 'accepted':
                counts['recorded_accepted_masters_present'] += 1
        for claim in normalized.get('source_metadata', {}).get('claims', []):
            if claim['evidence_status'] in ('unresolved', 'contradicted'):
                counts[claim['evidence_status'] + '_metadata_claims'] += 1
            if claim['recorded_adoption']['classification'] == 'supported_unapplied':
                counts['unapplied_metadata_claims'] += 1
    return {'counts': counts, 'missing_assertions': findings,
            'meaning': 'unrecorded is not unknown, inapplicable, incorrect, or permission to infer',
            'source_accuracy': 'not_assessed', 'completeness_is_validity': False}
