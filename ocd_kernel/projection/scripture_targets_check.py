"""Independent observations of explicit scripture target normalization."""
from __future__ import annotations

import re
from collections.abc import Collection, Mapping


def observe_reference_record(record: Mapping[str, str], *, book_codes: Collection[str]) -> dict:
    result = dict(record)
    for attribute in ('cRef', 'target'):
        if attribute not in record:
            continue
        result['normalization_attribute'] = attribute
        try:
            result['scripture'] = observe_explicit_target(record[attribute], book_codes=book_codes)
        except (ValueError, TypeError):
            result['normalization_status'] = 'unsupported-explicit-target'
        else:
            result['normalization_status'] = 'explicit-target-syntax'
        break
    else:
        result['normalization_status'] = 'no-explicit-target'
    return result


def observe_explicit_target(raw: str, *, book_codes: Collection[str]) -> dict:
    if not isinstance(raw, str) or not raw or re.search(r'\s', raw):
        raise ValueError('expected one explicit scripture target')
    text = raw
    prefix, separator, remainder = text.partition(':')
    if separator and prefix.lower() in ('bible', 'osis'):
        text = remainder
    tokens = text.split('-')
    if not 1 <= len(tokens) <= 2 or not all(tokens):
        raise ValueError('invalid scripture interval')

    def endpoint(value: str) -> list[str]:
        match = re.fullmatch(r'([^.:\s]+)(?:\.([1-9][0-9]*))?(?:\.([1-9][0-9]*[a-z]?))?', value)
        if match is None or match[1] not in book_codes:
            raise ValueError('unrecognized scripture endpoint')
        return [part for part in match.groups() if part is not None]

    left = endpoint(tokens[0])
    right = list(left)
    if len(tokens) == 2:
        suffix = tokens[1].split('.')
        if suffix[0] in book_codes:
            right = endpoint(tokens[1])
        else:
            missing = len(left) - len(suffix)
            if missing < 1 or missing >= len(left):
                raise ValueError('ambiguous abbreviated scripture endpoint')
            right = endpoint('.'.join(left[:missing] + suffix))
        if len(right) != len(left):
            raise ValueError('interval endpoints have different granularity')
        if left[0] == right[0]:
            def key(parts):
                result = []
                for part in parts[1:]:
                    numeric = part[:-1] if part[-1:].isalpha() else part
                    result.append((int(numeric), part[len(numeric):]))
                return result
            if key(right) < key(left):
                raise ValueError('scripture interval is reversed')

    def fields(parts):
        return {'book': parts[0], 'chapter': int(parts[1]) if len(parts) >= 2 else None,
                'verse': parts[2] if len(parts) == 3 else None}

    return {'raw': raw, 'normalized': '.'.join(left) + ('-' + '.'.join(right) if len(tokens) == 2 else ''),
            'kind': 'range' if len(tokens) == 2 else {1:'book', 2:'chapter', 3:'verse'}[len(left)],
            'start': fields(left), 'end': fields(right), 'derivation': 'explicit-target-syntax-v1'}


def verify_explicit_target(raw: str, value: Mapping, *, book_codes: Collection[str]) -> list[str]:
    try:
        expected = observe_explicit_target(raw, book_codes=book_codes)
    except (ValueError, TypeError) as exc:
        return [str(exc)]
    return [] if value == expected else ['explicit scripture normalization differs from independent observation']
