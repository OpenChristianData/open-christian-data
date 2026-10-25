"""Declared candidate association must bind identity and exact acquired members."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from cvw_app import library_admission
from ocd_kernel.library._common import PipelineError


@pytest.fixture
def declared(tmp_path, monkeypatch):
    source = tmp_path / 'retained.xml'
    source.write_bytes(b'<source/>')
    member = dict(path='retained.xml', bytes=source.stat().st_size,
                  sha256=hashlib.sha256(source.read_bytes()).hexdigest(), media_type='application/xml')
    work = tmp_path / 'library/works/work'
    acquisition = work / 'forms/english/editions/edition/acquisitions/acquisition.json'
    acquisition.parent.mkdir(parents=True)
    work_record = dict(schema_version='2.0', work_id='work', title='Declared title', evidence=['retained.xml'],
                       textual_forms=[dict(textual_form_id='english', editions=[dict(edition_id='edition', title='Edition',
                           category='prose', acquisition_ids=['acquisition'])])])
    (work / 'work.json').write_text(json.dumps(work_record), encoding='utf-8')
    acquired = dict(schema_version='2.0', acquisition_id='acquisition', edition_id='edition',
                    provider='Fixture provider', url='https://example.org/source', retained_files=[member])
    acquisition.write_text(json.dumps(acquired), encoding='utf-8')
    (tmp_path / 'source.json').write_text('{}', encoding='utf-8')
    manifest = SimpleNamespace(sha256='a'*64, record=dict(work_id='work', source_id='source',
        authorities=[dict(member, role='primary-source', name='primary')]))
    candidate = SimpleNamespace(manifest=dict(source_id='source', source_manifest=dict(path='source.json', sha256='a'*64)))
    monkeypatch.setattr(library_admission.CandidatePackage, 'load', lambda path: candidate)
    monkeypatch.setattr(library_admission.SourceManifest, 'load', lambda path, **kw: manifest)
    return tmp_path, manifest, work_record, acquisition


def test_declared_association_ignores_catalog_and_generated_views(declared):
    root, _, _, _ = declared
    (root / 'work-catalog.json').write_text('invalid', encoding='utf-8')
    (root / 'library/corpus-manifest.json').write_text('invalid', encoding='utf-8')
    rows = library_admission.declared_candidate_records(root, [root / 'candidate'])
    assert rows[0]['work_id'] == 'work'
    assert rows[0]['title'] == 'Declared title'
    assert rows[0]['reconstruction_state']['routes'][0]['source_id'] == 'source'


def test_missing_explicit_source_identity_is_rejected(declared):
    root, manifest, _, _ = declared
    del manifest.record['work_id']
    with pytest.raises(PipelineError):
        library_admission.declared_candidate_records(root, [root / 'candidate'])


def test_changed_retained_source_is_rejected(declared):
    root, _, _, _ = declared
    (root / 'retained.xml').write_bytes(b'<changed/>')
    with pytest.raises(PipelineError, match='evidence failed'):
        library_admission.declared_candidate_records(root, [root / 'candidate'])


def test_large_acquisition_checks_every_member_and_reports_all_mismatches(declared, monkeypatch):
    from collections import Counter
    from threading import Lock, get_ident
    from ocd_kernel.library import acquisitions

    root, _, _, sidecar = declared
    content = b"source"
    members = []
    for index in range(512):
        name = f"source-{index}.txt"
        (root / name).write_bytes(content)
        members.append(dict(path=name, bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(), media_type="text/plain"))
    record = json.loads(sidecar.read_text(encoding="utf-8"))
    record["retained_files"] = members
    sidecar.write_text(json.dumps(record), encoding="utf-8")
    sha256_file = acquisitions.sha256_file
    checked = Counter()
    threads = set()
    lock = Lock()

    def observed(path):
        with lock:
            checked[path.name] += 1
            threads.add(get_ident())
        return sha256_file(path)

    monkeypatch.setattr(acquisitions, "sha256_file", observed)
    assert len(acquisitions.validate_acquisition(sidecar, root=root)["retained_files"]) == 512
    assert checked == Counter({member["path"]: 1 for member in members})
    assert 1 < len(threads) <= 4
    (root / "source-511.txt").write_bytes(b"SOURCE")
    (root / "source-499.txt").unlink()
    with pytest.raises(PipelineError) as rejected:
        acquisitions.validate_acquisition(sidecar, root=root)
    assert "missing retained file: source-499.txt" in str(rejected.value)
    assert "sha256 mismatch for source-511.txt" in str(rejected.value)


def test_ambiguous_acquisition_is_not_selected_by_first_match(declared):
    root, _, work, acquisition = declared
    work['textual_forms'][0]['editions'][0]['acquisition_ids'].append('second')
    (root / 'library/works/work/work.json').write_text(json.dumps(work), encoding='utf-8')
    second = json.loads(acquisition.read_text(encoding='utf-8'))
    second['acquisition_id'] = 'second'
    acquisition.with_name('second.json').write_text(json.dumps(second), encoding='utf-8')
    with pytest.raises(PipelineError, match='exactly one'):
        library_admission.declared_candidate_records(root, [root / 'candidate'])


def test_unacquired_editions_do_not_block_exact_candidate_admission(declared):
    root, _, work, _ = declared
    work['textual_forms'][0]['editions'].insert(0, dict(
        edition_id='historical-edition', title='Historical edition', category='prose'))
    (root / 'library/works/work/work.json').write_text(json.dumps(work), encoding='utf-8')

    rows = library_admission.declared_candidate_records(root, [root / 'candidate'])

    assert len(rows) == 1
    assert rows[0]['work_id'] == 'work'
    assert rows[0]['reconstruction_state']['routes'][0]['source_id'] == 'source'


def _add_package_and_support_members(root, manifest, acquisition, *, source_sha256=None):
    source_bytes = (root / 'retained.xml').read_bytes()
    acquired = json.loads(acquisition.read_text(encoding='utf-8'))
    acquired.update(source_path='retained.xml', source_bytes=len(source_bytes),
                    source_sha256=source_sha256 or hashlib.sha256(source_bytes).hexdigest(),
                    source_scope='The retained XML is the text source; the ZIP is its package.')
    for name, media_type, payload in (
        ('package.zip', 'application/zip', b'package bytes'),
        ('cover.jpg', 'image/jpeg', b'cover bytes'),
        ('spine.jpg', 'image/jpeg', b'spine bytes'),
    ):
        path = root / name
        path.write_bytes(payload)
        member = dict(
            path=name, bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
            media_type=media_type,
        )
        acquired['retained_files'].append(member)
        role = 'acquisition-container' if media_type == 'application/zip' else 'source-support'
        manifest.record['authorities'].append(dict(member, role=role, name=name))
    acquisition.write_text(json.dumps(acquired), encoding='utf-8')
    work_path = root / 'library/works/work/work.json'
    authority_paths = {'work': work_path, 'acquisition': acquisition}
    for name, role, path in (
        ('work', 'work-identity-config', work_path),
        ('acquisition', 'acquisition-selection-authority', acquisition),
    ):
        content = path.read_bytes()
        manifest.record['authorities'].append(dict(
            name=name, role=role, path=path.relative_to(root).as_posix(),
            bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
        ))
    manifest.authority_path = lambda name: authority_paths[name]


def test_selected_text_source_excludes_retained_package_and_support_files(declared):
    root, manifest, _, acquisition = declared
    _add_package_and_support_members(root, manifest, acquisition)

    rows = library_admission.declared_candidate_records(root, [root / 'candidate'])

    assert rows[0]['work_id'] == 'work'
    assert rows[0]['reconstruction_state']['routes'][0]['source_id'] == 'source'


def test_selected_text_source_must_match_its_retained_identity(declared):
    root, manifest, _, acquisition = declared
    _add_package_and_support_members(root, manifest, acquisition, source_sha256='0' * 64)

    with pytest.raises(PipelineError, match='selected source identity'):
        library_admission.declared_candidate_records(root, [root / 'candidate'])


def test_missing_optional_category_uses_neutral_review_label(declared):
    root, _, work, _ = declared
    del work['textual_forms'][0]['editions'][0]['category']
    (root / 'library/works/work/work.json').write_text(json.dumps(work), encoding='utf-8')

    rows = library_admission.declared_candidate_records(root, [root / 'candidate'])

    assert rows[0]['category'] == 'uncategorized'


def test_long_author_list_uses_a_bounded_label_without_editing_the_work(declared):
    root, _, work, _ = declared
    work['creators'] = [dict(name=f'Author {index} with a long recorded name', role='author', evidence=['retained.xml']) for index in range(40)]
    path = root / 'library/works/work/work.json'
    path.write_text(json.dumps(work), encoding='utf-8')
    before = path.read_bytes()
    rows = library_admission.declared_candidate_records(root, [root / 'candidate'])
    assert rows[0]['author'] == 'Author 0 with a long recorded name and 39 others'
    assert path.read_bytes() == before


def _second_work(root, work, acquisition):
    import copy
    second = copy.deepcopy(work)
    second['work_id'] = 'second-work'
    second['textual_forms'][0]['editions'][0]['edition_id'] = 'second-edition'
    directory = root / 'library/works/second-work'
    path = directory / 'forms/english/editions/second-edition/acquisitions/acquisition.json'
    path.parent.mkdir(parents=True)
    (directory / 'work.json').write_text(json.dumps(second), encoding='utf-8')
    acquired = json.loads(acquisition.read_text(encoding='utf-8'))
    acquired['edition_id'] = 'second-edition'
    path.write_text(json.dumps(acquired), encoding='utf-8')
    return path


def _bind_direct_source_authorities(root, manifest, work_path, acquisition_path):
    source = root / 'retained.xml'
    source_bytes = source.read_bytes()
    acquired = json.loads(acquisition_path.read_text(encoding='utf-8'))
    acquired.update(
        source_path='retained.xml', source_bytes=len(source_bytes),
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        source_scope='The retained XML is the selected textual source.',
    )
    acquisition_path.write_text(json.dumps(acquired), encoding='utf-8')
    path_by_name = {'selected-work': work_path, 'selected-acquisition': acquisition_path}
    for name, role, path in (
        ('selected-work', 'work-identity-config', work_path),
        ('selected-acquisition', 'acquisition-selection-authority', acquisition_path),
    ):
        payload = path.read_bytes()
        manifest.record['authorities'].append(dict(
            name=name, role=role, path=path.relative_to(root).as_posix(),
            bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
        ))
    manifest.authority_path = lambda name: path_by_name[name]


def test_direct_source_path_binds_exact_selected_work_and_acquisition(declared):
    root, manifest, _, acquisition_path = declared
    work_path = root / 'library/works/work/work.json'
    _bind_direct_source_authorities(root, manifest, work_path, acquisition_path)

    rows = library_admission.declared_candidate_records(root, [root / 'candidate'])

    route = rows[0]['reconstruction_state']['routes'][0]
    assert route['work_identity_authority'] == 'library/works/work/work.json'
    assert route['acquisition_selection_authority'] == acquisition_path.relative_to(root).as_posix()


def test_direct_source_path_rejects_same_source_authorities_from_another_work(declared):
    root, manifest, work, acquisition_path = declared
    _bind_direct_source_authorities(
        root, manifest, root / 'library/works/work/work.json', acquisition_path
    )
    other_acquisition = _second_work(root, work, acquisition_path)
    other_work = other_acquisition.parents[5] / 'work.json'
    manifest.record['authorities'] = [manifest.record['authorities'][0]]
    _bind_direct_source_authorities(root, manifest, other_work, other_acquisition)

    with pytest.raises(PipelineError, match='does not bind declared acquisition and work'):
        library_admission.declared_candidate_records(root, [root / 'candidate'])


def test_explicit_shared_volume_cohort_preserves_work_order(declared):
    root, manifest, work, acquisition = declared
    _second_work(root, work, acquisition)
    del manifest.record['work_id']
    manifest.record['work_ids'] = ('second-work', 'work')
    rows = library_admission.declared_candidate_records(root, [root / 'candidate'])
    assert [row['work_id'] for row in rows] == ['second-work', 'work']
    assert all(row['reconstruction_state']['routes'][0]['source_id'] == 'source' for row in rows)


def test_work_specific_asset_is_required_only_for_its_declared_work(declared):
    root, manifest, work, acquisition = declared
    second_path = _second_work(root, work, acquisition)
    del manifest.record['work_id']
    manifest.record['work_ids'] = ['work', 'second-work']
    asset = root / 'image.png'
    asset.write_bytes(b'exact retained image fixture')
    member = dict(path='image.png', bytes=asset.stat().st_size,
                  sha256=hashlib.sha256(asset.read_bytes()).hexdigest(), media_type='image/png')
    manifest.record['authorities'].append(dict(member, role='primary-source', name='image', work_ids=('second-work',)))
    acquired = json.loads(second_path.read_text())
    acquired['retained_files'].append(member)
    second_path.write_text(json.dumps(acquired), encoding='utf-8')
    rows = library_admission.declared_candidate_records(root, [root / 'candidate'])
    assert len(rows) == 2
    acquired['retained_files'].pop()
    second_path.write_text(json.dumps(acquired), encoding='utf-8')
    with pytest.raises(PipelineError, match='exactly one'):
        library_admission.declared_candidate_records(root, [root / 'candidate'])


@pytest.mark.parametrize('mutation', ['duplicate', 'empty', 'string', 'competing', 'unknown-asset', 'duplicate-asset', 'empty-asset', 'uncovered-work'])
def test_cohort_ambiguity_and_unassigned_members_are_rejected(declared, mutation):
    root, manifest, _, _ = declared
    del manifest.record['work_id']
    manifest.record['work_ids'] = ['work']
    if mutation == 'duplicate':
        manifest.record['work_ids'] = ['work', 'work']
    elif mutation == 'empty':
        manifest.record['work_ids'] = []
    elif mutation == 'string':
        manifest.record['work_ids'] = 'work'
    elif mutation == 'competing':
        manifest.record['work_id'] = 'work'
    elif mutation == 'unknown-asset':
        manifest.record['authorities'][0]['work_ids'] = ['invented']
    elif mutation == 'duplicate-asset':
        manifest.record['authorities'].append(manifest.record['authorities'][0])
    elif mutation == 'empty-asset':
        manifest.record['authorities'][0]['work_ids'] = []
    else:
        manifest.record['work_ids'] = ['work', 'second-work']
        manifest.record['authorities'][0]['work_ids'] = ['work']
    with pytest.raises(PipelineError):
        library_admission.declared_candidate_records(root, [root / 'candidate'])
