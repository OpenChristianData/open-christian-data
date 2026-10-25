"""Compose adopted work metadata without replacing TEI correspondence checks."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import edition_by_id


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _authority(root, rows):
    if not rows:
        raise PipelineError('work metadata requires rows')
    work, edition = edition_by_id(root, rows[0]['edition_id'])
    if any(row['work_id'] != work.work_id or row['edition_id'] != edition.edition_id or row['textual_form_id'] != edition.textual_form_id for row in rows):
        raise PipelineError('work metadata row identity differs')
    if not any(field in work.record for field in ('original_language', 'work_kind')):
        return None
    from build.lib.source_metadata import lookup_work_original_language, lookup_work_kind
    claims = {}
    for field, lookup in (('original_language', lookup_work_original_language), ('work_kind', lookup_work_kind)):
        if field in work.record:
            claims[field] = lookup(root, work.path)
    if not claims:
        return None
    return {'version':'ocd-work-metadata-v2', 'work_id':work.work_id,
            'work_sha256':hashlib.sha256(work.path.read_bytes()).hexdigest(),
            'claim_sha256':_digest(claims),
            'values':{field:claim['evidence']['value'] for field, claim in claims.items()}}


def compose_work_metadata(root: Path, rows: list, receipt: dict, *, public_layer: bool = False):
    authority = _authority(root, rows)
    if authority is None:
        return rows, receipt
    if public_layer:
        authority['version'] = 'ocd-work-metadata-v3-public'
    result = copy.deepcopy(rows)
    for row in result:
        for field, value in authority['values'].items():
            if field in row['provenance']:
                raise PipelineError('category already supplied work metadata')
            row['provenance'][field] = value
    if 'work_metadata' in receipt:
        raise PipelineError('category already supplied work metadata receipt')
    return result, {**receipt, 'work_metadata':{**authority, 'output_sha256':_digest(result)}}


def check_work_metadata(root: Path, rows: list, receipt: dict):
    """Check adopted metadata, then return inputs for the independent TEI checker."""
    observed = _authority(root, rows)
    if observed is not None and receipt.get('work_metadata', {}).get('version') == 'ocd-work-metadata-v3-public':
        observed['version'] = 'ocd-work-metadata-v3-public'
    if observed is None:
        if 'work_metadata' in receipt or any(field in row['provenance'] for row in rows for field in ('original_language', 'work_kind')):
            raise PipelineError('unadopted original language in release')
        return rows, receipt
    base_rows, base_receipt = copy.deepcopy(rows), copy.deepcopy(receipt)
    expected = {**observed, 'output_sha256':_digest(rows)}
    if base_receipt.pop('work_metadata', None) != expected:
        raise PipelineError('work metadata receipt differs from adopted evidence')
    for row in base_rows:
        for field, value in observed['values'].items():
            if row['provenance'].pop(field, None) != value:
                raise PipelineError('public '+field.replace('_', ' ')+' differs from adopted evidence')
        if any(field in row['provenance'] for field in ('original_language', 'work_kind')):
            raise PipelineError('unadopted work metadata in release')
    return base_rows, base_receipt


def strip_retained_metadata(rows: list, receipt: dict):
    """Check the old layer's internal binding; it supplies no current authority."""
    layer = receipt.get('work_metadata')
    if layer is None:
        if any(field in row['provenance'] for row in rows for field in ('original_language', 'work_kind')):
            raise PipelineError('retained rows contain unaccounted work metadata')
        return rows, receipt
    if (not isinstance(layer, dict)
            or set(layer) != {'version', 'work_id', 'work_sha256', 'claim_sha256', 'values', 'output_sha256'}
            or layer.get('version') not in ('ocd-work-metadata-v2', 'ocd-work-metadata-v3-public')
            or layer.get('work_id') != rows[0]['work_id'] or layer.get('output_sha256') != _digest(rows)
            or not isinstance(layer.get('values'), dict)
            or not layer['values'] or not set(layer['values']) <= {'original_language', 'work_kind'}):
        raise PipelineError('retained work metadata binding differs')
    base, proof = copy.deepcopy(rows), dict(receipt)
    proof.pop('work_metadata')
    for row in base:
        for field, value in layer['values'].items():
            if row['provenance'].pop(field, None) != value:
                raise PipelineError('retained metadata values differ')
        if any(field in row['provenance'] for field in ('original_language', 'work_kind')):
            raise PipelineError('retained metadata has extra values')
    return base, proof
