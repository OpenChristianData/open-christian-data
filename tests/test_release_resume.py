"""Real interrupted builds recover only independently valid edition outputs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.build_state import MANIFEST, READY, check_ready
from ocd_kernel.release.resume import DIRECTORY, INPUTS, ResumeStage, StageLock
from tests.test_release_build_state import _profile_fixture


def _interrupt(root, profile, output, monkeypatch, *, committed=True):
    from ocd_kernel.release import resume
    actual = resume.checkpoint

    def crash(*args):
        if committed:
            actual(*args)
        raise KeyboardInterrupt('simulated process interruption')

    with monkeypatch.context() as changes:
        changes.setattr(resume, 'checkpoint', crash)
        with pytest.raises(KeyboardInterrupt):
            assemble_release_v2(root, output, profile_path=profile, reader_check=True)
    assert not output.exists()
    stages = [p for p in output.parent.glob(f'.{output.name}-*') if p.is_dir()]
    assert len(stages) == 1
    assert not (stages[0] / READY).exists()
    return stages[0]


@pytest.mark.parametrize('committed', [True, False])
def test_resume_ignores_uncommitted_tail_and_reuses_committed_edition(tmp_path, monkeypatch, committed):
    root, profile, selection = _profile_fixture(tmp_path, monkeypatch)
    stage = _interrupt(root, profile, tmp_path/'interrupted', monkeypatch, committed=committed)
    import ocd_kernel.projection.categories.quotations as projector
    actual, calls = projector.project_accepted_quotations, []

    def observed(*args, **kwargs):
        calls.append(True)
        return actual(*args, **kwargs)

    monkeypatch.setattr(projector, 'project_accepted_quotations', observed)
    output = tmp_path/'recovered'
    assemble_release_v2(root, output, profile_path=profile, reader_check=True, resume_stage=stage)
    check_ready(output)
    manifest = json.loads((output/MANIFEST).read_bytes())
    assert manifest['items'][0]['reused'] == committed
    assert len(calls) == (0 if committed else 1)
    assert (stage/INPUTS).exists()
    assert not (stage/READY).exists()


def test_legacy_recovery_uses_progress_ranges_and_refreshes_current_metadata(tmp_path, monkeypatch):
    root, profile, selection = _profile_fixture(tmp_path, monkeypatch)
    first = tmp_path/'first'
    assemble_release_v2(root, first, profile_path=profile, reader_check=True)
    legacy = tmp_path/'legacy'
    for path in first.rglob('*'):
        relative = path.relative_to(first)
        if path.is_file() and (relative.as_posix() == 'internal/release-selection.json'
                or 'projection-receipts' in path.parts or 'public-row-transforms' in path.parts
                or path.name == 'train.jsonl'):
            target = legacy/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    saved = json.loads((first/MANIFEST).read_bytes())['items'][0]
    identifier = selection['items'][0]['item_id']
    progress = tmp_path/'legacy-progress.jsonl'
    progress.write_bytes(canonical_bytes({'phase':'projecting', 'item_id':identifier}) +
        canonical_bytes({'phase':'projected','item_id':identifier,'bytes':saved['end']-saved['begin'],
                         'rows':saved['row_count']}) + b'{"phase":"project')
    spool = next((legacy/'public/data').rglob('train.jsonl'))
    spool.write_bytes(spool.read_bytes() + b'{"unfinished')
    before = spool.read_bytes()
    work_path = root/f"library/works/{selection['items'][0]['work_id']}/work.json"
    work = json.loads(work_path.read_bytes())
    work['creators'] = [{'name':'Fixture author','role':'author', 'evidence':[selection['items'][0]['acceptance_path']]}]
    work_path.write_bytes(canonical_bytes(work))
    import ocd_kernel.projection.categories.quotations as projector
    monkeypatch.setattr(projector, 'project_accepted_quotations', lambda *a, **k: pytest.fail('legacy projection repeated'))
    output = tmp_path/'legacy-recovered'
    assemble_release_v2(root, output, profile_path=profile, reader_check=True,
                        resume_stage=legacy, resume_progress=progress)
    check_ready(output)
    current = json.loads((output/MANIFEST).read_bytes())['items'][0]
    assert current['reuse_kind'] == 'legacy-verified'
    assert current['input_fingerprint'] != saved['input_fingerprint']
    assert spool.read_bytes() == before


def test_corrupt_checkpoint_rows_are_reprojected_not_trusted(tmp_path, monkeypatch):
    root, profile, selection = _profile_fixture(tmp_path, monkeypatch)
    stage = _interrupt(root, profile, tmp_path/'interrupted', monkeypatch)
    spool = next((stage/'public/data').rglob('train.jsonl'))
    rows = [json.loads(line) for line in spool.read_bytes().splitlines()]
    rows[0]['text'] = 'forged content'
    spool.write_bytes(b''.join(canonical_bytes(row) for row in rows))
    cp = next((stage/DIRECTORY).glob('*.json'))
    record = json.loads(cp.read_bytes())
    record['range']['end'] = spool.stat().st_size
    record['range']['sha256'] = hashlib.sha256(spool.read_bytes()).hexdigest()
    cp.write_bytes(canonical_bytes(record))
    output = tmp_path/'reprojected'
    assemble_release_v2(root, output, profile_path=profile, reader_check=True, resume_stage=stage)
    check_ready(output)
    assert json.loads((output/MANIFEST).read_bytes())['items'][0]['reused'] is False
    assert b'forged content' not in next((output/'public/data').rglob('train.jsonl')).read_bytes()


def test_active_resume_stage_is_refused_and_lock_releases(tmp_path, monkeypatch):
    root, profile, selection = _profile_fixture(tmp_path, monkeypatch)
    stage = _interrupt(root, profile, tmp_path/'interrupted', monkeypatch)
    with StageLock(stage):
        with pytest.raises(PipelineError, match='actively owned'):
            ResumeStage(stage)
        import subprocess
        import sys
        code = "from pathlib import Path; from ocd_kernel.release.resume import ResumeStage; import sys; ResumeStage(Path(sys.argv[1]))"
        checked = subprocess.run([sys.executable, '-c', code, str(stage)], capture_output=True,
                                 text=True, timeout=30, check=False)
        assert checked.returncode != 0 and 'actively owned' in checked.stderr
    assert ResumeStage(stage).saved


def test_public_metadata_layer_survives_license_and_inverse_checks(tmp_path, monkeypatch):
    root, profile, selection = _profile_fixture(tmp_path, monkeypatch)
    from ocd_kernel.release import work_metadata
    authority = {'version':'ocd-work-metadata-v2','work_id':selection['items'][0]['work_id'],
                 'work_sha256':'a'*64,'claim_sha256':'b'*64,'values':{'original_language':'la'}}
    monkeypatch.setattr(work_metadata, '_authority', lambda *a: dict(authority))
    stage = _interrupt(root, profile, tmp_path/'old-metadata', monkeypatch)
    authority['values'] = {'original_language':'en'}
    authority['claim_sha256'] = 'c'*64
    output = tmp_path/'new-metadata'
    assemble_release_v2(root, output, profile_path=profile, reader_check=True, resume_stage=stage)
    check_ready(output)
    assert json.loads((output/MANIFEST).read_bytes())['items'][0]['reused']
    rows = [json.loads(line) for line in next((output/'public/data').rglob('train.jsonl')).read_bytes().splitlines()]
    assert all(row['provenance']['original_language'] == 'en' for row in rows)


def test_checkpoint_disk_failure_never_promotes_or_commits_item(tmp_path, monkeypatch):
    import errno
    from ocd_kernel.release import resume
    root, profile, selection = _profile_fixture(tmp_path, monkeypatch)
    actual = resume.atomic_json

    def full(path, value):
        if path.parent.name == 'checkpoints':
            raise OSError(errno.ENOSPC, 'simulated full disk')
        return actual(path, value)

    monkeypatch.setattr(resume, 'atomic_json', full)
    output = tmp_path/'disk-full'
    with pytest.raises(PipelineError, match='infrastructure'):
        assemble_release_v2(root, output, profile_path=profile, reader_check=True)
    assert not output.exists()
    stages = [p for p in output.parent.glob(f'.{output.name}-*') if p.is_dir()]
    assert len(stages) == 1 and not list((stages[0]/DIRECTORY).glob('*.json'))
    assert not (stages[0]/READY).exists()


def test_resume_rechecks_reparse_paths_after_inventory(tmp_path, monkeypatch):
    from ocd_kernel.release import public_allowlist
    root, profile, selection = _profile_fixture(tmp_path, monkeypatch)
    stage = _interrupt(root, profile, tmp_path/'interrupted', monkeypatch)
    recovery = ResumeStage(stage)
    spool = next((stage/'public/data').rglob('train.jsonl'))
    actual = public_allowlist._is_link
    monkeypatch.setattr(public_allowlist, '_is_link', lambda path: path == spool or actual(path))
    assert recovery.read_item(root, selection['items'][0], {}) is None
    assert 'reparse point' in recovery.last_miss


@pytest.mark.parametrize('failure', ['checker', 'late-receipt-change'])
def test_resume_requires_current_check_and_stable_source_evidence(tmp_path, monkeypatch, failure):
    root, profile, selection = _profile_fixture(tmp_path, monkeypatch)
    stage = _interrupt(root, profile, tmp_path/'interrupted', monkeypatch)
    recovery = ResumeStage(stage)
    from ocd_kernel.release import verify
    actual = verify.verify_release_item
    calls = []

    def checked(*args):
        calls.append(True)
        if failure == 'checker':
            return ['current independent checker rejected cached rows']
        result = actual(*args)
        path = next((stage/'internal/projection-receipts').glob('*.json'))
        path.write_bytes(path.read_bytes() + b'\n')
        return result

    monkeypatch.setattr(verify, 'verify_release_item', checked)
    assert recovery.read_item(root, selection['items'][0], {}) is None
    assert calls == [True]
    assert ('checker rejected' in recovery.last_miss if failure == 'checker'
            else 'evidence changed' in recovery.last_miss)
def _interrupt_after_encoding(root, profile, output, monkeypatch):
    from ocd_kernel.release import verify

    def stop(*args, **kwargs):
        raise KeyboardInterrupt('interrupted at terminal verification')

    with monkeypatch.context() as changes:
        changes.setattr(verify, 'verify_release_v2', stop)
        with pytest.raises(KeyboardInterrupt):
            assemble_release_v2(root, output, profile_path=profile, reader_check=True)
    return next(output.parent.glob(f'.{output.name}-*'))


@pytest.mark.parametrize('runtime_change', [False, True])
def test_assembled_resume_skips_projection_and_encoding(tmp_path, monkeypatch, runtime_change):
    root, profile, selection = _profile_fixture(tmp_path, monkeypatch)
    stage = _interrupt_after_encoding(root, profile, tmp_path/'interrupted', monkeypatch)
    if runtime_change:
        manifest = json.loads((stage/MANIFEST).read_bytes())
        next(entry for entry in manifest['inputs']['shared'] if entry['scope'] == 'runtime')['sha256'] = '0'*64
        (stage/MANIFEST).write_bytes(canonical_bytes(manifest))
        snapshot = json.loads((stage/INPUTS).read_bytes())
        snapshot['inputs'] = manifest['inputs']
        (stage/INPUTS).write_bytes(canonical_bytes(snapshot))
    before = {p.relative_to(stage): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in stage.rglob('*') if p.is_file()}
    import ocd_kernel.projection.categories.quotations as projector
    from ocd_kernel.release import typed_rows
    monkeypatch.setattr(projector, 'project_accepted_quotations', lambda *a, **k: pytest.fail('producer repeated'))
    monkeypatch.setattr(typed_rows, 'write_rows', lambda *a, **k: pytest.fail('encoding repeated'))
    output = tmp_path/'recovered'
    evidence = tmp_path/'evidence'
    assemble_release_v2(root, output, profile_path=profile, reader_check=True, resume_stage=stage,
                        evidence_dir=evidence)
    check_ready(output)
    events = [json.loads(line) for line in (evidence/'progress.jsonl').read_bytes().splitlines()]
    assert any(event['phase'] == 'resumed-assembly' for event in events)
    assert any(event['phase'] == 'verified-item' for event in events)
    assert all(hashlib.sha256((stage/path).read_bytes()).hexdigest() == digest
               for path, digest in before.items())


@pytest.mark.parametrize('failure', ['bytes', 'terminal-check', 'reader', 'copy-drift'])
def test_assembled_resume_requires_valid_bytes_and_fresh_terminal_check(tmp_path, monkeypatch, failure):
    root, profile, selection = _profile_fixture(tmp_path, monkeypatch)
    stage = _interrupt_after_encoding(root, profile, tmp_path/'interrupted', monkeypatch)
    if failure == 'bytes':
        path = next((stage/'public/data').rglob('train.jsonl'))
        path.write_bytes(path.read_bytes().replace(b'fixture', b'forgery'))
        # The mutation must change a byte regardless of fixture prose.
        path.write_bytes(path.read_bytes() + b'\n')
    elif failure == 'terminal-check':
        from ocd_kernel.release import verify
        monkeypatch.setattr(verify, 'verify_release_v2', lambda *a, **k: {'status':'fail', 'errors':['fresh failure']})
    elif failure == 'reader':
        from build.tools import check_release_reader
        def rejected(*args, **kwargs):
            raise PipelineError('reader rejected resumed stage')
        monkeypatch.setattr(check_release_reader, 'check_reader', rejected)
    else:
        original = shutil.copyfile
        def changed(source, target, *args, **kwargs):
            result = original(source, target, *args, **kwargs)
            if 'projection-receipts' in Path(source).parts:
                Path(source).write_bytes(Path(source).read_bytes() + b'\n')
            return result
        monkeypatch.setattr(shutil, 'copyfile', changed)
    output = tmp_path/'rejected'
    with pytest.raises(PipelineError):
        assemble_release_v2(root, output, profile_path=profile, reader_check=True, resume_stage=stage)
    assert not output.exists()


def test_assembled_resume_falls_back_when_library_authority_changes(tmp_path, monkeypatch):
    root, profile, selection = _profile_fixture(tmp_path, monkeypatch)
    stage = _interrupt_after_encoding(root, profile, tmp_path/'interrupted', monkeypatch)
    manifest = json.loads((stage/MANIFEST).read_bytes())
    inputs = json.loads(json.dumps(manifest['inputs']))
    inputs['profile']['sha256'] = '0'*64
    target = tmp_path/'unused-stage'
    target.mkdir()
    stored = json.loads((stage/'internal/release-selection.json').read_bytes())
    assert ResumeStage(stage).copy_assembled(target, stored, inputs) is None
    assert list(target.iterdir()) == []



@pytest.mark.parametrize('checker_rejects', [False, True])
def test_failed_assembled_stage_recovers_only_fresh_checked_items(tmp_path, monkeypatch, checker_rejects):
    from tests.test_release_assembly_v2 import _item, _promoted_category
    from ocd_kernel.release import verify
    root, profile, _selection = _profile_fixture(tmp_path, monkeypatch)
    second_root, second_acceptance = _promoted_category(
        tmp_path, 'quotations', 'failed-resume-item', namespace=True)
    shutil.copytree(second_root, root, dirs_exist_ok=True)
    acceptance = root / second_acceptance.relative_to(second_root)
    identity = json.loads(acceptance.read_bytes())['identity']
    work_path = root / 'library/works' / identity['work_id'] / 'work.json'
    work = json.loads(work_path.read_bytes())
    for form in work['textual_forms']:
        for edition in form['editions']:
            if edition['edition_id'] == identity['edition_id']:
                edition['acquisition_ids'] = [identity['acquisition_id']]
                edition['category'] = 'quotations'
    work_path.write_bytes(canonical_bytes(work))
    failed_id = f"{identity['work_id']}--{identity['edition_id']}"
    _item(root, failed_id, 'quotations', acceptance, license='CC0-1.0')
    configured = json.loads(profile.read_bytes())
    configured['works'].append({'work_id': identity['work_id'], 'disposition': 'cohort'})
    configured['items'].append({'item_id': failed_id, 'work_id': identity['work_id'],
        'textual_form_id': identity['textual_form_id'], 'edition_id': identity['edition_id'],
        'disposition': 'selected'})
    profile.write_bytes(canonical_bytes(configured))
    import ocd_kernel.projection.categories.quotations as projector
    project = projector.project_accepted_quotations

    def fail_one(*args, **kwargs):
        if kwargs['acceptance_path'] == acceptance:
            raise PipelineError('simulated edition failure')
        return project(*args, **kwargs)

    output = tmp_path / 'failed'
    with monkeypatch.context() as changes:
        changes.setattr(projector, 'project_accepted_quotations', fail_one)
        with pytest.raises(PipelineError, match='release contains failed items'):
            assemble_release_v2(root, output, profile_path=profile, reader_check=True)
    assert not output.exists()
    stage = next(output.parent.glob(f'.{output.name}-*'))
    report = json.loads((stage / 'internal/release-report.json').read_bytes())
    assert report['status'] == 'fail' and report['accounting']['failed'] == 1
    assert len(list((stage / DIRECTORY).glob('*.json'))) == 1
    before = {p.relative_to(stage): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in stage.rglob('*') if p.is_file()}
    recovery = ResumeStage(stage)
    selection = json.loads((stage / 'internal/release-selection.json').read_bytes())
    inputs = json.loads((stage / MANIFEST).read_bytes())['inputs']
    target = tmp_path / 'unused-stage'
    target.mkdir()
    assert recovery.copy_assembled(target, selection, inputs) is None
    assert list(target.iterdir()) == []
    checked, actual = [], verify.verify_release_item

    def checked_now(*args):
        checked.append(args[1]['item_id'])
        return ['fresh checker rejected retained item'] if checker_rejects else actual(*args)

    monkeypatch.setattr(verify, 'verify_release_item', checked_now)
    good = next(item for item in selection['items'] if item['item_id'] != failed_id)
    recovered = recovery.read_item(root, good, inputs)
    assert (recovered is None) == checker_rejects
    assert checked == [good['item_id']]
    if checker_rejects:
        assert 'fresh checker rejected' in recovery.last_miss
    failed = next(item for item in selection['items'] if item['item_id'] == failed_id)
    assert recovery.read_item(root, failed, inputs) is None
    assert checked == [good['item_id']]
    assert before == {p.relative_to(stage): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in stage.rglob('*') if p.is_file()}


@pytest.mark.parametrize('failure', ['schema', 'inconsistent-pass'])
def test_failed_assembled_resume_still_rejects_invalid_report(tmp_path, monkeypatch, failure):
    root, profile, _selection = _profile_fixture(tmp_path, monkeypatch)
    stage = _interrupt_after_encoding(root, profile, tmp_path / 'interrupted', monkeypatch)
    path = stage / 'internal/release-report.json'
    report = json.loads(path.read_bytes())
    if failure == 'schema':
        report['status'] = 'fail'
        report['accounting'].pop('failed')
    else:
        report['accounting']['failed'] = 1
    path.write_bytes(canonical_bytes(report))
    target = tmp_path / 'unused-stage'
    target.mkdir()
    selection = json.loads((stage / 'internal/release-selection.json').read_bytes())
    inputs = json.loads((stage / MANIFEST).read_bytes())['inputs']
    with pytest.raises(PipelineError, match='assembled resume report is invalid'):
        ResumeStage(stage).copy_assembled(target, selection, inputs)
    assert list(target.iterdir()) == []
