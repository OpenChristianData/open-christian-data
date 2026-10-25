import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from ocd_kernel.library.acquisitions import source_member_set_bytes, validate_acquisition
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.acceptance import _source_binding, _validate_scope


def fixture(tmp_path):
    root = tmp_path / 'r'
    shutil.copytree(Path(__file__).parent / 'fixtures/library-pipeline', root)
    path = root / 'library/works/athanasius-on-the-incarnation/forms/athanasius-on-the-incarnation-prose/editions/ccel-npnf204/acquisitions/ccel-npnf204-retained-xml.json'
    record = json.loads(path.read_bytes())
    record['retained_files'][0]['scope'] = 'First member'
    second = root / 'retained/second.xml'; second.write_bytes(b'<source>Second</source>')
    record['retained_files'].append(dict(path='retained/second.xml', bytes=second.stat().st_size, sha256=hashlib.sha256(second.read_bytes()).hexdigest(), media_type='application/xml', scope='Second member'))
    record.update(source_kind='retained-member-set', source_path='retained/member-set.json', source_scope='Complete ordered two-member set')
    raw = source_member_set_bytes(record)
    (root / record['source_path']).write_bytes(raw)
    record.update(source_bytes=len(raw), source_sha256=hashlib.sha256(raw).hexdigest())
    path.write_text(json.dumps(record), encoding='utf-8')
    return root, path, record


def test_explicit_member_set_binds_manifest_and_each_original_file(tmp_path):
    root, path, record = fixture(tmp_path)
    assert validate_acquisition(path, root=root) == record
    binding = _source_binding(record, context='test')
    assert binding['source_kind'] == 'retained-member-set'
    assert binding['source_sha256'] == hashlib.sha256((root / record['source_path']).read_bytes()).hexdigest()
    assert binding['source_sha256'] not in {member['sha256'] for member in record['retained_files']}


@pytest.mark.parametrize('change', ['reorder', 'omit', 'manifest-resealed', 'member-bytes'])
def test_member_set_rejects_order_omission_and_resealed_manifest_mutation(tmp_path, change):
    root, path, record = fixture(tmp_path)
    if change == 'reorder':
        record['retained_files'].reverse()
    elif change == 'omit':
        record['retained_files'].pop()
    elif change == 'member-bytes':
        (root / record['retained_files'][1]['path']).write_bytes(b'Changed source')
    else:
        raw = (root / record['source_path']).read_bytes().replace(b'First member', b'False member')
        (root / record['source_path']).write_bytes(raw)
        record.update(source_bytes=len(raw), source_sha256=hashlib.sha256(raw).hexdigest())
    path.write_text(json.dumps(record), encoding='utf-8')
    with pytest.raises(PipelineError):
        validate_acquisition(path, root=root)


def test_acceptance_cannot_reverse_declared_member_set_order(tmp_path):
    root, _, acquisition = fixture(tmp_path)
    members = acquisition['retained_files']
    expected = [{'path': member['path'], 'position': i} for i, member in enumerate(reversed(members), 1)]
    scope = {'expected_members': expected, 'included_members': copy.deepcopy(expected), 'excluded_members': []}
    with pytest.raises(PipelineError, match='member order'):
        _validate_scope({'scope': scope}, acquisition, root)
