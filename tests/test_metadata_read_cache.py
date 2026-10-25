"""Repeated metadata reads share work only within one verified inspection."""
import hashlib

import pytest

from build.lib import source_metadata
from ocd_kernel.library import rights
from ocd_kernel.library._common import PipelineError, inspection_read_phase
from ocd_kernel.library.record_read import RecordRead
from tests.test_library_records import root, write


def test_schema_cache_reuses_exact_payload_and_does_not_hide_mutations(monkeypatch):
    payload = {'schema_version': 'source-metadata-index-v1', 'writer': 'ocd-source-metadata-v1',
               'batch_id': 'fixture', 'counts': {'catalog': 0}, 'subjects': []}
    actual = source_metadata._schema_for
    calls = []
    def observed(kind):
        calls.append(kind)
        return actual(kind)
    monkeypatch.setattr(source_metadata, '_schema_for', observed)
    with inspection_read_phase():
        source_metadata._validate_schema(payload, kind='index')
        source_metadata._validate_schema(payload, kind='index')
        assert calls == ['index']
        payload['unexpected'] = True
        with pytest.raises(source_metadata.MetadataError):
            source_metadata._validate_schema(payload, kind='index')
        assert calls == ['index', 'index']
        del payload['unexpected']
    with inspection_read_phase():
        source_metadata._validate_schema(payload, kind='index')
    assert calls == ['index', 'index', 'index']


def test_rights_parse_cache_keeps_stability_and_stale_binding_checks(root, monkeypatch):
    reference = 'research/decision.json'
    write(root / reference, {'selected': {'finding': 'example'}})
    binding = {'path': reference, 'sha256': hashlib.sha256((root / reference).read_bytes()).hexdigest(),
               'pointer': '/selected'}
    actual = rights.json.loads
    expected_text = (root / reference).read_bytes().decode('utf-8')
    calls = []
    def observed(*args, **kwargs):
        if args[0] == expected_text:
            calls.append(True)
        return actual(*args, **kwargs)
    monkeypatch.setattr(rights.json, 'loads', observed)
    with inspection_read_phase():
        read = RecordRead(root)
        assert rights._bound(read, binding) == {'finding': 'example'}
        assert rights._bound(read, binding) == {'finding': 'example'}
        assert len(calls) == 1
        write(root / reference, {'selected': {'finding': 'changed'}})
        assert not read.stable()
    with inspection_read_phase(), pytest.raises(PipelineError, match='stale rights binding'):
        rights._bound(RecordRead(root), binding)
