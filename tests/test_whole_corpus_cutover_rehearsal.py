"""Complete target accounting must expose gaps instead of shrinking the scope."""

import hashlib
import json

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.corpus_accounting import account_targets
from build.tools import report_corpus_cutover


def test_cli_refuses_existing_report_before_reading_inputs(tmp_path, capsys):
    output = tmp_path / "accounting.json"
    original = b'{"retirement_readiness":"not-ready","retained":"evidence"}'
    output.write_bytes(original)
    result = report_corpus_cutover.main([
        "--root", str(tmp_path), "--scope", str(tmp_path / "absent-scope.json"),
        "--release", str(tmp_path / "absent-release"),
        "--selection", str(tmp_path / "absent-selection.json"),
        "--output", str(output),
    ])
    assert result == 1
    assert "output must be fresh" in capsys.readouterr().err
    assert output.read_bytes() == original


def _fixture(root):
    def write(name, value):
        content = json.dumps(value).encode()
        (root / name).write_bytes(content)
        return {"path": name, "sha256": hashlib.sha256(content).hexdigest()}
    targets = []
    for name in ("volume-one", "volume-two", "unreviewed"):
        subject = {"kind": "catalog", "id": name}
        targets.append({"target_id": "catalog:" + name, "subject": subject,
                        "metadata_evidence": write(name + '.json', {"subject": subject})})
    baseline = write('baseline.json', {"targets": targets})
    acceptance = write('acceptance.json', {"identity": "fixture-only"})
    scope = {"baseline": baseline, "links": [
        {"target_id": row["target_id"], "acceptance": acceptance} for row in targets[:2]]}
    selection = {"items": [{"item_id": "complete-edition", "category": "prose", "acceptance_path": "acceptance.json"}]}
    report = {"items": [{**selection["items"][0], "status": "warned", "reasons": ["source note"], "row_count": 9}]}
    return scope, selection, report


def test_every_target_retained_and_shared_edition_not_double_counted(tmp_path):
    scope, selection, report = _fixture(tmp_path)
    result = account_targets(tmp_path, scope=scope, selection=selection, release_report=report)
    assert result['counts'] == {'targets': 3, 'included': 2, 'excluded': 0, 'unlinked': 1, 'blocked': 0, 'failed': 0}
    assert result['distinct_release_editions'] == 1
    assert result['retirement_readiness'] == 'not-ready'
    assert result['targets'][-1]['target_id'] == 'catalog:unreviewed'
    assert result['targets'][-1]['status'] == 'unlinked'
    assert result['targets'][0]['warnings'] == ['source note']


@pytest.mark.parametrize('mutation', ['metadata', 'acceptance'])
def test_changed_evidence_remains_visible_as_failed_target(tmp_path, mutation):
    scope, selection, report = _fixture(tmp_path)
    path = 'volume-one.json' if mutation == 'metadata' else 'acceptance.json'
    (tmp_path / path).write_text('{}', encoding='utf-8')
    result = account_targets(tmp_path, scope=scope, selection=selection, release_report=report)
    assert result['counts']['targets'] == 3
    assert result['counts']['failed'] == (1 if mutation == 'metadata' else 2)
    assert result['retirement_readiness'] == 'not-ready'


@pytest.mark.parametrize('mutation', ['duplicate-link', 'extra-link', 'unlinked-release', 'missing-item', 'baseline-drift'])
def test_ambiguous_or_shrunken_accounting_rejected(tmp_path, mutation):
    scope, selection, report = _fixture(tmp_path)
    if mutation == 'duplicate-link':
        scope['links'].append(scope['links'][0])
    elif mutation == 'extra-link':
        scope['links'].append({**scope['links'][0], 'target_id': 'catalog:invented'})
    elif mutation == 'unlinked-release':
        scope['links'] = []
    elif mutation == 'missing-item':
        report['items'] = []
    else:
        (tmp_path / 'baseline.json').write_text('{"targets":[]}', encoding='utf-8')
    with pytest.raises(PipelineError):
        account_targets(tmp_path, scope=scope, selection=selection, release_report=report)


def test_public_entry_requires_independent_release_check(tmp_path, monkeypatch):
    from ocd_kernel.release import corpus_accounting
    scope, selection, report = _fixture(tmp_path)
    (tmp_path / 'internal').mkdir()
    (tmp_path / 'internal/release-report.json').write_text(json.dumps(report), encoding='utf-8')
    monkeypatch.setattr(corpus_accounting, 'verify_release_v2', lambda *args, **kwargs: {'status': 'fail', 'errors': ['changed master']})
    with pytest.raises(PipelineError, match='changed master'):
        corpus_accounting.report_corpus(tmp_path, tmp_path, scope=scope, selection=selection)


@pytest.mark.parametrize('mutation', ['valid', 'omitted', 'wrong-member'])
def test_frozen_volume_association_is_preserved(tmp_path, mutation):
    scope, selection, report = _fixture(tmp_path)
    member = {'path': 'raw/volume-two.xml', 'position': 2}
    baseline = json.loads((tmp_path / 'baseline.json').read_text())
    baseline['targets'][1]['existing_integration'] = {'edition_member': member}
    content = json.dumps(baseline).encode()
    (tmp_path / 'baseline.json').write_bytes(content)
    scope['baseline']['sha256'] = hashlib.sha256(content).hexdigest()
    content = json.dumps({'scope': {'expected_members': [member]}}).encode()
    (tmp_path / 'acceptance.json').write_bytes(content)
    for link in scope['links']:
        link['acceptance']['sha256'] = hashlib.sha256(content).hexdigest()
    if mutation != 'omitted':
        scope['links'][1]['edition_member'] = member if mutation == 'valid' else {**member, 'position': 1}
    result = account_targets(tmp_path, scope=scope, selection=selection, release_report=report)
    if mutation == 'valid':
        assert result['targets'][1]['edition_member'] == member
        assert result['targets'][1]['status'] == 'included'
    else:
        assert result['targets'][1]['status'] == 'failed'


def test_explicit_structural_hold_is_not_relabelled_missing_handoff(tmp_path):
    scope, selection, report = _fixture(tmp_path)
    content = json.dumps({'work_id': 'unreviewed', 'targets': [
        {'target_id': 'edition', 'target_type': 'edition', 'stage': 'blocked', 'reason': 'Observed structural loss.'}]}).encode()
    (tmp_path / 'state.json').write_bytes(content)
    scope['holds'] = [{'target_id': 'catalog:unreviewed', 'work_id': 'unreviewed', 'edition_id': 'edition',
                       'state': {'path': 'state.json', 'sha256': hashlib.sha256(content).hexdigest()}}]
    result = account_targets(tmp_path, scope=scope, selection=selection, release_report=report)
    assert result['targets'][-1]['status'] == 'blocked'
    assert result['targets'][-1]['reason'] == 'Observed structural loss.'


def _readiness_fixture(root):
    from ocd_kernel.release.cutover_readiness import REQUIRED_GATES, scope_digest
    root.mkdir(parents=True, exist_ok=True)
    sibling = root.parent / 'EzraOCR'
    (sibling / '.git').mkdir(parents=True)
    (sibling / 'runtime.py').write_bytes(b'current runtime\n')
    scope, selection, report = _fixture(root)
    accounting = account_targets(root, scope=scope, selection=selection, release_report=report)
    # Hypothetical complete accounting exercises the readiness boundary only.
    accounting['targets'][-1]['status'] = 'included'
    accounting['release_verification'] = {'status': 'pass', 'errors': []}
    accounting['release_report_sha256'] = 'a' * 64

    def write(name, value):
        content = json.dumps(value).encode()
        (root / name).write_bytes(content)
        return {'path': name, 'sha256': hashlib.sha256(content).hexdigest()}

    input_binding = write('input.json', {'current': True})
    scope['prerequisites'] = {}
    for gate in REQUIRED_GATES:
        proof = ({'exit_code': 0, 'command': 'py -3 -m pytest -p no:cacheprovider -q'}
                 if gate == 'full_suite' else {'status': 'pass'})
        if gate == 'reader_fidelity':
            proof['release_report_sha256'] = 'a' * 64
        verification = write(gate + '-result.json', proof)
        scope['prerequisites'][gate] = write(gate + '.json', {
            'contract': 'ocd-cutover-prerequisite-v1', 'gate': gate,
            'scope_sha256': scope_digest(scope), 'inputs': [input_binding] + ([{
                'repository': 'EzraOCR', 'path': 'runtime.py',
                'sha256': hashlib.sha256(b'current runtime\n').hexdigest(),
            }] if gate == 'runtime_boundary' else []), 'verification': verification})
    return scope, accounting


def test_readiness_requires_every_gate_and_complete_frozen_scope(tmp_path):
    from ocd_kernel.release.cutover_readiness import complete_readiness
    tmp_path = tmp_path / 'OCD'
    scope, accounting = _readiness_fixture(tmp_path)
    assert complete_readiness(tmp_path, scope, accounting)['retirement_readiness'] == 'ready'
    accounting['targets'].pop()
    assert complete_readiness(tmp_path, scope, accounting)['retirement_readiness'] == 'not-ready'


@pytest.mark.parametrize('remaining_status', ['unlinked', 'blocked'])
def test_verified_work_integration_can_be_ready_while_retirement_is_not(tmp_path, remaining_status):
    from ocd_kernel.release.cutover_readiness import complete_readiness
    tmp_path = tmp_path / 'OCD'
    scope, accounting = _readiness_fixture(tmp_path)
    accounting['targets'][-1]['status'] = remaining_status

    result = complete_readiness(tmp_path, scope, accounting)

    assert result['retirement_readiness'] == 'not-ready'
    assert result['work_integration_readiness']['status'] == 'ready-and-integrated'
    assert result['work_integration_readiness']['included_target_count'] == 2
    assert result['work_integration_readiness']['distinct_acceptance_masters'] == 1
    assert result['work_integration_readiness']['included_target_ids'] == [
        'catalog:volume-one', 'catalog:volume-two']


@pytest.mark.parametrize('mutation', ['missing', 'stale-input', 'changed-verification', 'changed-scope', 'held-target', 'failed-release'])
def test_readiness_fails_closed_on_missing_stale_or_failed_evidence(tmp_path, mutation):
    from ocd_kernel.release.cutover_readiness import complete_readiness
    tmp_path = tmp_path / 'OCD'
    scope, accounting = _readiness_fixture(tmp_path)
    if mutation == 'missing':
        del scope['prerequisites']['category_mappings']
    elif mutation == 'stale-input':
        (tmp_path / 'input.json').write_text('{}')
    elif mutation == 'changed-verification':
        (tmp_path / 'full_suite-result.json').write_text('{"exit_code":1}')
    elif mutation == 'changed-scope':
        scope['new_scope_claim'] = True
    elif mutation == 'held-target':
        accounting['targets'][0]['status'] = 'blocked'
    else:
        accounting['release_verification'] = {'status': 'fail', 'errors': ['changed master']}
    result = complete_readiness(tmp_path, scope, accounting)
    assert result['retirement_readiness'] == 'not-ready'
    if mutation == 'failed-release':
        assert result['work_integration_readiness']['status'] == 'unverified'
        assert result['work_integration_readiness']['included_target_count'] == 0


@pytest.mark.parametrize('command', [
    'py -3 -m pytest -p no:cacheprovider tests/test_one.py -q',
    'py -3 -m pytest -p no:cacheprovider -m "not slow" -q',
    'py -3 -m pytest -p no:cacheprovider --collect-only',
    'py -3 -m pytest -p no:cacheprovider -k selected',
])
def test_selected_or_collection_run_cannot_satisfy_full_gate(command):
    from ocd_kernel.release.cutover_readiness import _full_suite_result
    assert not _full_suite_result({'exit_code': 0, 'command': command})


@pytest.mark.parametrize('mutation', [
    'changed-runtime', 'missing-checkout', 'copied-report-only',
    'unknown-repository', 'parent-traversal', 'wrong-gate', 'duplicate-input',
    'storage-redirection',
])
def test_runtime_readiness_checks_current_named_sibling(tmp_path, mutation):
    from ocd_kernel.release.cutover_readiness import evaluate_prerequisites
    root = tmp_path / 'OCD'
    scope, _ = _readiness_fixture(root)
    gate = 'runtime_boundary'
    receipt_path = root / 'runtime_boundary.json'
    receipt = json.loads(receipt_path.read_bytes())
    if mutation == 'changed-runtime':
        (tmp_path / 'EzraOCR/runtime.py').write_bytes(b'changed runtime\n')
    elif mutation == 'missing-checkout':
        (tmp_path / 'EzraOCR/.git').rmdir()
    elif mutation == 'copied-report-only':
        receipt['inputs'] = receipt['inputs'][:1]
    elif mutation == 'unknown-repository':
        receipt['inputs'][-1]['repository'] = 'arbitrary-sibling'
    elif mutation == 'parent-traversal':
        receipt['inputs'][-1]['path'] = '../OCD/input.json'
    elif mutation == 'wrong-gate':
        gate = 'consumer_replacement'
        receipt['gate'] = gate
    elif mutation == 'storage-redirection':
        external = tmp_path / 'external-library'
        (external / 'raw').mkdir(parents=True)
        (external / 'raw/runtime.py').write_bytes(b'current runtime\n')
        (tmp_path / 'EzraOCR/.ocd-storage.json').write_text(
            json.dumps({'library_root': str(external)}), encoding='utf-8'
        )
        receipt['inputs'][-1]['path'] = 'raw/runtime.py'
    else:
        receipt['inputs'].append(dict(receipt['inputs'][-1]))
    content = json.dumps(receipt).encode()
    receipt_path.write_bytes(content)
    scope['prerequisites'][gate] = {
        'path': receipt_path.name, 'sha256': hashlib.sha256(content).hexdigest(),
    }
    checks = evaluate_prerequisites(root, scope, release_report_sha256='a' * 64)
    result = next(row for row in checks if row['gate'] == gate)
    assert result['status'] == 'failed'
    if mutation == 'storage-redirection':
        assert 'escapes its sibling checkout' in result['reason']
