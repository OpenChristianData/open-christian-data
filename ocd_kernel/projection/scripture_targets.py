"""Lossless syntax normalization of explicit scripture targets.

This is not prose extraction or a versification validator. Callers supply and
bind their book-code authority; this module has no independent book catalog.
"""
from __future__ import annotations

import re
from collections.abc import Collection, Mapping

from ocd_kernel.library._common import PipelineError


def normalize_reference_record(record: Mapping[str, str], *, book_codes: Collection[str]) -> dict:
    """Annotate a source reference without replacing its label or attributes.

    cRef is the explicit canonical-reference attribute. A target is used when
    cRef is absent; the chosen attribute is recorded, not silently substituted.
    """
    result = dict(record)
    attribute = 'cRef' if 'cRef' in record else 'target' if 'target' in record else None
    if attribute is None:
        result['normalization_status'] = 'no-explicit-target'
        return result
    result['normalization_attribute'] = attribute
    try:
        result['scripture'] = normalize_explicit_target(record[attribute], book_codes=book_codes)
    except PipelineError:
        result['normalization_status'] = 'unsupported-explicit-target'
    else:
        result['normalization_status'] = 'explicit-target-syntax'
    return result


def normalize_explicit_target(raw: str, *, book_codes: Collection[str]) -> dict:
    """Fully qualify range endpoints without dropping their scope or suffixes.

    Accepted forms are explicit book/chapter/verse tokens, optionally prefixed
    by Bible: or osis:. Unknown books and ambiguous syntax are rejected. The
    returned target does not claim that its numbers exist in a versification.
    """
    if not isinstance(raw, str) or not raw or raw != raw.strip() or any(c.isspace() for c in raw):
        raise PipelineError('scripture target requires one explicit token')
    token = re.sub(r'^(?:Bible|osis):', '', raw, flags=re.IGNORECASE)
    pieces = token.split('-')
    if len(pieces) > 2 or any(not item for item in pieces):
        raise PipelineError('unsupported scripture range syntax')

    def full(value: str) -> tuple[str, ...]:
        components = tuple(value.split('.'))
        if not 1 <= len(components) <= 3 or components[0] not in book_codes:
            raise PipelineError('unknown scripture book or target syntax')
        if len(components) >= 2 and not re.fullmatch(r'[1-9][0-9]*', components[1]):
            raise PipelineError('invalid scripture chapter')
        if len(components) == 3 and not re.fullmatch(r'[1-9][0-9]*[a-z]?', components[2]):
            raise PipelineError('invalid scripture verse')
        return components

    start = full(pieces[0])
    end = start
    if len(pieces) == 2:
        right = pieces[1].split('.')
        if right[0] in book_codes:
            end = full(pieces[1])
        elif len(start) == 3 and len(right) == 1:
            end = full('.'.join((*start[:2], *right)))
        elif len(start) >= 2 and len(right) == len(start) - 1:
            end = full('.'.join((start[0], *right)))
        else:
            raise PipelineError('ambiguous scripture range endpoint')
        if len(start) != len(end):
            raise PipelineError('mixed scripture range granularity')
        if start[0] == end[0]:
            # Suffixless verse and partial verse are not treated as equivalent.
            def position(parts: tuple[str, ...]) -> tuple:
                return tuple((int(re.match(r'[0-9]+', part).group()),
                              part.lstrip('0123456789')) for part in parts[1:])
            if position(end) < position(start):
                raise PipelineError('reversed scripture range')
    normalized = '.'.join(start)
    if len(pieces) == 2:
        normalized += '-' + '.'.join(end)
    return {
        'raw': raw,
        'normalized': normalized,
        'kind': 'range' if len(pieces) == 2 else ('book', 'chapter', 'verse')[len(start)-1],
        'start': {'book': start[0], 'chapter': int(start[1]) if len(start) > 1 else None,
                  'verse': start[2] if len(start) > 2 else None},
        'end': {'book': end[0], 'chapter': int(end[1]) if len(end) > 1 else None,
                'verse': end[2] if len(end) > 2 else None},
        'derivation': 'explicit-target-syntax-v1',
    }
