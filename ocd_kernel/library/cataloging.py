"""Read evidence-bound cataloging notes for existing acquisition leads."""
from __future__ import annotations

import json
from pathlib import Path

from ocd_kernel.lib.path_io import io_path
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ._common import PipelineError, _reject_duplicate_keys, canonical_bytes, read_input_bytes, safe_identifier, sha256_bytes


FIELDS = {
    'title': 'Title',
    'identifiers': 'Existing lead ID / work ID, if any',
    'author': 'Author or attributed author, including any qualification',
    'work_scope': 'Work scope',
    'original_language': 'Original language',
    'edition': 'Edition title and language',
    'contributors': 'Translator, editor, or other credited contributors',
    'publication': 'Historical publisher, place, year, volume, and edition statement',
    'source': 'Electronic provider and exact source URL',
    'format_extent': 'Available format and extent',
    'source_problems': 'Known omissions, OCR, or other source problems',
    'primary_evidence': 'Title page, catalog entry, contents, or other primary evidence and locator',
    'rights': 'Rights statement and its exact URL; distinguish the edition from the provider',
    'holdings': 'Relationship to existing holdings',
    'open_questions': 'What still needs checking',
    'next_action': 'Proposed next action',
    'researcher': 'Researcher and date',
}
MARKER = '\n## Evidence bindings\n\n```json\n'


def note_path(lead_id: str) -> str:
    return f'library/acquisition-research/{safe_identifier(lead_id, field="lead_id")}.md'


def render_note(lead: dict, fields: dict, sources: list[dict]) -> str:
    if set(fields) != set(FIELDS) or any(not isinstance(value, str) or '\n' in value for value in fields.values()):
        raise PipelineError('cataloging requires every template field; unknown values are empty strings')
    binding = {'lead_sha256': sha256_bytes(canonical_bytes(lead)), 'sources': sources}
    lines = [f"# {fields['title'] or fields['work_scope']}", '']
    for key, label in FIELDS.items():
        lines.extend([f'**{label}:** {fields[key]}'.rstrip(), ''])
    lines.extend(['## Research used', '',
                  *(f"- [{source['path']}](../../{source['path']}) — lines {source['line_start']}–{source['line_end']}"
                    for source in sources)])
    return '\n'.join(lines) + '\n' + MARKER + json.dumps(binding, ensure_ascii=False, indent=2) + '\n```\n'


def load_note(root: Path, lead: dict, *, read=None) -> dict | None:
    reference = note_path(lead['lead_id'])
    path = resolve_repo_path(root, reference)
    if read is None:
        if not io_path(path).is_file():
            return None
        body = read_input_bytes(path)
    else:
        if read.observe(reference)['present'] is False:
            return None
        body = read.bytes(reference, 'research')
        if body is None:
            return None
    text = body.decode('utf-8').replace('\r\n', '\n')
    if text.count(MARKER) != 1:
        raise PipelineError(f'cataloging note lacks unique evidence bindings: {reference}')
    description, evidence = text.split(MARKER)
    if not evidence.endswith('\n```\n'):
        raise PipelineError(f'invalid cataloging evidence block: {reference}')
    try:
        binding = json.loads(evidence[:-5], object_pairs_hook=_reject_duplicate_keys)
    except ValueError as exc:
        raise PipelineError(f'invalid cataloging evidence JSON: {reference}') from exc
    if not isinstance(binding, dict) or set(binding) != {'lead_sha256', 'sources'} or binding['lead_sha256'] != sha256_bytes(canonical_bytes(lead)):
        raise PipelineError(f'cataloging note differs from its queue entry: {reference}')
    fields = {}
    for line in description.splitlines():
        for key, label in FIELDS.items():
            prefix = '**' + label + ':**'
            if line.startswith(prefix):
                if key in fields:
                    raise PipelineError(f'duplicate cataloging field {key}: {reference}')
                fields[key] = line[len(prefix):].strip()
                break
    if set(fields) != set(FIELDS) or fields['identifiers'].split(';')[0].strip() != lead['lead_id']:
        raise PipelineError(f'incomplete or mismatched cataloging template: {reference}')
    if not isinstance(binding['sources'], list) or not binding['sources']:
        raise PipelineError(f'cataloging note requires source evidence: {reference}')
    for source in binding['sources']:
        if not isinstance(source, dict) or set(source) != {'path', 'sha256', 'line_start', 'line_end'}:
            raise PipelineError(f'invalid cataloging source binding: {reference}')
        source_path = resolve_repo_path(root, source['path'])
        raw = read.bytes(source['path'], 'research') if read is not None else read_input_bytes(source_path)
        if raw is None or sha256_bytes(raw) != source['sha256']:
            raise PipelineError(f'stale cataloging source: {source["path"]}')
        start, end = source['line_start'], source['line_end']
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(raw.decode('utf-8').splitlines()):
            raise PipelineError(f'invalid cataloging source extent: {reference}')
    return {'path': reference, 'sha256': sha256_bytes(body), 'fields': fields, 'evidence': binding}
