"""Explicit targets retain complete reference scope without prose guessing."""
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.scripture_targets import normalize_explicit_target
from ocd_kernel.projection.scripture_targets_check import observe_explicit_target, verify_explicit_target


@pytest.mark.parametrize(('raw', 'expected'), [
    ('Bible:John.3.16a-18b', 'John.3.16a-John.3.18b'),
    ('Gen.1.26-2.3', 'Gen.1.26-Gen.2.3'),
    ('Gen.50.26-Exod.1.2', 'Gen.50.26-Exod.1.2'),
    ('osis:John.3-4', 'John.3-John.4'),
    ('John.3.16a', 'John.3.16a'),
    ('John.3', 'John.3'),
    ('John', 'John'),
])
def test_explicit_scope_and_suffix_survive(raw, expected):
    result = normalize_explicit_target(raw, book_codes=['Gen', 'Exod', 'John'])
    assert result['raw'] == raw
    assert result['normalized'] == expected
    assert verify_explicit_target(raw, result, book_codes=['Gen', 'Exod', 'John']) == []
    assert normalize_explicit_target(expected, book_codes=['Gen', 'Exod', 'John'])['normalized'] == expected


@pytest.mark.parametrize('raw', [
    'Unknown.3.16', 'John 3:16', 'John.3.16,18', 'John.3.16-18-20',
    'John.3.18-16', 'John.0.1', 'John.3.0', 'John.03.16',
    'John.3.16-4', 'John.3.16a-16', 'John.3.16-Gen.4',
    'https://example.org/John.3.16', 'John.3.16 ', 'John.3.16cdef',
])
def test_unsupported_targets_are_not_silently_reduced(raw):
    with pytest.raises(PipelineError):
        normalize_explicit_target(raw, book_codes=['Gen', 'Exod', 'John'])
    with pytest.raises(ValueError):
        observe_explicit_target(raw, book_codes=['Gen', 'Exod', 'John'])


def test_independent_target_check_rejects_loss_and_does_not_call_producer(monkeypatch):
    import copy
    from ocd_kernel.projection import scripture_targets
    raw = 'Bible:John.3.16a-4.2b'
    result = normalize_explicit_target(raw, book_codes=['John'])
    monkeypatch.setattr(scripture_targets, 'normalize_explicit_target', lambda *a, **k: pytest.fail('producer called'))
    assert verify_explicit_target(raw, result, book_codes=['John']) == []
    for field, value in [('normalized','John.3.16'), ('end',result['start']), ('raw','John.3.16a-4.2b'), ('derivation','inferred')]:
        changed = copy.deepcopy(result)
        changed[field] = value
        assert verify_explicit_target(raw, changed, book_codes=['John'])
