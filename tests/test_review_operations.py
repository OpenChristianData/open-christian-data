"""Protect shared review operations against data loss and identity drift."""

import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from build.tools import ambrose_review, docsouth_review, expositors_review, openmgh_review
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path


@pytest.mark.parametrize('failure', [None, 'after-old-rename', 'after-new-rename', 'after-postcheck'])
def test_install_commits_or_restores_the_exact_generation(tmp_path, failure):
    root, stage = tmp_path / 'repo', tmp_path / 'stage'
    work_id = 'ambrose-of-milan-fixture'
    work = Path('library/works') / work_id
    old, new = root / work, stage / work
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    old.joinpath('work.json').write_text('{"generation":"old"}', encoding='utf-8')
    form = {'textual_form_id': 'form', 'editions': [{'edition_id': 'edition', 'acquisition_ids': ['acquisition']}]}
    new.joinpath('work.json').write_text(json.dumps({'textual_forms': [form]}), encoding='utf-8')
    before, after = _files(old), _files(new)

    def preflight(work_id, *, root_override):
        assert root_override == root
        return {'target_root': str(root), 'stage': str(stage), 'before': before, 'after': after}

    def copy_generation(source, target, expected):
        shutil.copytree(source, target)
        assert _files(target) == expected

    def check_generation(selected_root, **kwargs):
        assert selected_root == root
        assert _files(old) == kwargs['after'] == after

    def fail_at(point):
        if point == failure:
            raise RuntimeError('injected failure')

    kwargs = dict(root_override=root, fail_at=fail_at, CONTRACT='fixture-install-v1',
                  PINS={work_id: {'receipt': '0' * 64}}, _checked_generation=check_generation,
                  _copy_generation=copy_generation, _external_dependencies=lambda *a, **k: None,
                  _now=lambda: '2026-10-02T00:00:00Z',
                  _read_json=lambda path: json.loads(_io_path(path).read_bytes()), preflight=preflight)
    if failure:
        with pytest.raises(RuntimeError, match='injected failure'):
            ambrose_review.install(work_id, **kwargs)
        assert _files(old) == before
    else:
        result = ambrose_review.install(work_id, **kwargs)
        assert result['status'] == 'installed-and-validated'
        assert _files(old) == after
    journals = list((root / 'library/.sidecar-operations').glob('*/operation.json'))
    assert len(journals) == 1
    journal = json.loads(journals[0].read_bytes())
    assert journal['phase'] == ('rolled-back' if failure else 'complete')


def test_openmgh_work_requires_unambiguous_source_bound_acquisition():
    source, package = Path('raw/source.xml'), Path('raw/package.zip')
    form = {'textual_form_id': 'form', 'editions': [{'edition_id': 'edition', 'acquisition_ids': ['a']}]}
    work = {'work_id': 'fixture', 'textual_forms': [form]}
    acquisition = {'source_path': source.as_posix(), 'source_sha256': '1' * 64,
                   'retained_files': [{'path': package.as_posix()}, {'path': source.as_posix()}]}
    kwargs = dict(PACKAGE=package, SOURCE=source, SOURCE_SHA256='1' * 64,
                  _read=lambda path: work if path.name == 'work.json' else acquisition)
    result = openmgh_review.load_bound_work(Path('.'), 'fixture', **kwargs)
    assert result[:2] == (work, acquisition)
    acquisition['source_sha256'] = '2' * 64
    with pytest.raises(ValueError, match='text authority changed'):
        openmgh_review.load_bound_work(Path('.'), 'fixture', **kwargs)
    acquisition['source_sha256'] = '1' * 64
    form['editions'][0]['acquisition_ids'].append('b')
    with pytest.raises(ValueError, match='acquisition identity ambiguous'):
        openmgh_review.load_bound_work(Path('.'), 'fixture', **kwargs)


def test_docsouth_stage_pin_rejects_tampering_and_duplicate_work(tmp_path):
    work_id = 'fixture'
    stage = tmp_path / work_id
    stage.mkdir()
    record = {'contract': 'fixture-stage-v1', 'status': 'staged-only', 'installation': 'not-performed',
              'work_id': work_id, 'source_sha256': '1' * 64, 'source_rights_text_sha256': '2' * 64,
              'source_entity_declarations': 1, 'source_oracle': {'status': 'pass'}, 'projection_rows': 1}
    receipt = stage / 'stage-receipt.json'
    receipt.write_text(json.dumps(record), encoding='utf-8')
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    pin = dict(record, stage_receipt_sha256=sha(receipt), stage_files=_files(stage))
    frozen = {'stage_home': str(tmp_path), 'works': [pin]}
    kwargs = dict(_read=lambda path: json.loads(path.read_bytes()), _sha=sha,
                  staging=SimpleNamespace(CONTRACT='fixture-stage-v1'))
    assert docsouth_review.work_pin(frozen, work_id, **kwargs)[2] == record
    receipt.write_bytes(receipt.read_bytes() + b' ')
    with pytest.raises(PipelineError, match='complete stage differs'):
        docsouth_review.work_pin(frozen, work_id, **kwargs)
    frozen['works'].append(pin)
    with pytest.raises(PipelineError, match='absent or repeated'):
        docsouth_review.work_pin(frozen, work_id, **kwargs)


def test_candidate_cli_retains_validation_report_and_rejects_existing_destination(tmp_path, monkeypatch, capsys):
    root = tmp_path / 'repo'
    root.mkdir()
    destination = tmp_path / 'candidate'
    manifest = SimpleNamespace(sha256='1' * 64)
    candidate = SimpleNamespace(sha256='2' * 64)
    report = SimpleNamespace(status='pass', candidate_sha256=candidate.sha256,
                             source_manifest_sha256=manifest.sha256, attestation={'verified': True},
                             findings=[], sha256='3' * 64)
    monkeypatch.setattr(expositors_review, 'SourceManifest', SimpleNamespace(load=lambda *a, **k: manifest))
    monkeypatch.setattr(expositors_review, 'reconstruct', lambda *a: candidate)
    monkeypatch.setattr(expositors_review, 'validate', lambda *a: report)
    monkeypatch.setattr('sys.argv', ['candidate-command', str(destination)])
    kwargs = dict(AUTHORITY=root / 'sources', MEMBERS=('member',), ROOT=root,
                  _convert=lambda _: {}, _oracle=lambda *_: {}, __doc__='Existing command description')
    expositors_review.build_candidates(**kwargs)
    recorded = json.loads((destination / 'member.validation.json').read_bytes())
    assert recorded == {'contract': 'ocd-validation-report-v1', 'status': 'pass',
                        'candidate_sha256': candidate.sha256, 'source_manifest_sha256': manifest.sha256,
                        'attestation': {'verified': True}, 'findings': [], 'report_sha256': report.sha256}
    assert json.loads(capsys.readouterr().out)[0]['member'] == 'member'
    with pytest.raises(ValueError, match='fresh and external'):
        expositors_review.build_candidates(**kwargs)
    monkeypatch.setattr('sys.argv', ['candidate-command', str(root / 'candidate')])
    with pytest.raises(ValueError, match='fresh and external'):
        expositors_review.build_candidates(**kwargs)


