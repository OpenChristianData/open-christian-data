"""Prepare the exact reviewed Wesley candidate for library acceptance."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from ocd_kernel.library._common import PipelineError
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import CandidatePackage
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
BASE = Path('plans/2026-08-31-library-pipeline-redesign/artifacts/PIPE-004')
WORK = 'wesley-plain-account'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def prepare(root: Path, stage: Path) -> Path:
    if stage.exists():
        raise PipelineError('Wesley staging root must be fresh')
    readiness = json.loads((root / BASE / '12-additional-integration-readiness.json').read_bytes())['items'][0]
    probe = json.loads((root / BASE / '17-wesley-header-integration-probe.json').read_bytes())
    replay = json.loads((root / BASE / '16-wesley-current-checker-replay.json').read_bytes())
    result = replay['oracle_result']
    signed = {k: v for k, v in result.items() if k != 'result_sha256'}
    canonical = (json.dumps(signed, ensure_ascii=False, separators=(',', ':'), sort_keys=True) + '\n').encode()
    if result['status'] != 'pass' or sha(canonical) != result['result_sha256']:
        raise PipelineError('current checker replay result is invalid')
    for item in replay['replay_input_bindings']:
        raw = resolve_repo_path(root, item['path']).read_bytes()
        if len(raw) != item['bytes'] or sha(raw) != item['sha256']:
            raise PipelineError('replay authority changed: ' + item['path'])
    package = CandidatePackage.load(readiness['package_path'])
    if package.sha256 != '4828bd54cea757b96898502c1ab4e5c65cce48a945a246a71c574ad96171fb03' or result['candidate_sha256'] != package.sha256:
        raise PipelineError('reviewed Wesley package changed')
    historical_manifest = (root / readiness['manifest_recovery']['reviewed_snapshot_path']).read_bytes()
    if sha(historical_manifest) != result['source_manifest_sha256'] or sha(historical_manifest) != readiness['bound_source_manifest_sha256']:
        raise PipelineError('historical manifest binding changed')
    review_path = Path(readiness['package_path']).parents[2] / 'ticket18-wesley-cvw-review/ticket18-cvw-review-receipt.json'
    review_bytes = review_path.read_bytes()
    if sha(review_bytes) != '56e688578fb5d7742f2d7cacccae8ef8d703a0f4c5ed63065bfd108d1e33e13c':
        raise PipelineError('historical visual review changed')
    for anchor in json.loads(review_bytes)['close_comparison_anchors']:
        image = anchor['screenshot']
        image_bytes = Path(image['path']).read_bytes()
        if len(image_bytes) != image['bytes'] or sha(image_bytes) != image['sha256']:
            raise PipelineError('historical screenshot changed: ' + anchor['label'])
    args = probe['arguments']
    identity = args['identity']
    if identity['work_id'] != WORK:
        raise PipelineError('wrong integration work')
    original = package.member_bytes('content.tei.xml')
    derived = bind_reviewed_header(original, **args)
    if sha(derived) != probe['candidate_sha256']:
        raise PipelineError('header derivation differs from verified probe')
    work = stage / 'library/works' / WORK
    evidence = work / 'integration/reviewed-wesley-v1'
    evidence.mkdir(parents=True)
    shutil.copytree(package.path, evidence / 'original-package')
    (evidence / 'historical-source-manifest.json').write_bytes(historical_manifest)
    (evidence / 'historical-review.json').write_bytes(review_bytes)
    for name in ('16-wesley-current-checker-replay.json', '17-wesley-header-integration-probe.json'):
        (evidence / name).write_bytes((root / BASE / name).read_bytes())
    (evidence / 'historical-review.md').write_bytes((root / 'plans/2026-08-31-sample-first-library-verification/18-wesley-plain-account-whole-candidate-review.md').read_bytes())
    write(evidence / 'derivation-arguments.json', args)
    worker = "import json,sys; from pathlib import Path; from ocd_kernel.tei.reviewed_integration import bind_reviewed_header; p=Path(sys.argv[1]); sys.stdout.buffer.write(bind_reviewed_header((p/'original-package/content.tei.xml').read_bytes(), **json.loads((p/'derivation-arguments.json').read_bytes())))"
    reproduced = subprocess.run([sys.executable, '-c', worker, str(evidence)], cwd=root, check=True, capture_output=True).stdout
    if reproduced != derived or original.split(b'</teiHeader>', 1)[1] != derived.split(b'</teiHeader>', 1)[1]:
        raise PipelineError('header reproducibility or preservation failed')
    candidate = evidence / 'candidate.tei.xml'
    candidate.write_bytes(derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(str(errors))
    source = args['source'] | {'source_scope': args['declared_scope']}
    payload = resolve_repo_path(root, source['source_path']).read_bytes()
    if sha(payload) != source['source_sha256'] or len(payload) != source['source_bytes']:
        raise PipelineError('retained Wesley source changed')
    target = stage / source['source_path']; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(payload)
    (work / 'README.source.md').write_bytes(package.member_bytes('README.source.md'))
    declared = args['declared_scope']; now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    edition = work / 'forms' / identity['textual_form_id'] / 'editions' / identity['edition_id']
    write(work / 'work.json', dict(schema_version='2.0', work_id=WORK, title='A Plain Account of Christian Perfection', evidence=[source['source_path']], creators=[dict(name='John Wesley', role='author', evidence=[source['source_path']])], textual_forms=[dict(textual_form_id=identity['textual_form_id'], language='en', editions=[dict(edition_id=identity['edition_id'], title='CCEL retained ThML witness', language='en', category='prose', acquisition_ids=[identity['acquisition_id']])])]))
    member = dict(path=source['source_path'], bytes=source['source_bytes'], sha256=source['source_sha256'], scope=declared, media_type='application/xml')
    write(edition / 'acquisitions' / (identity['acquisition_id'] + '.json'), dict(schema_version='2.0', acquisition_id=identity['acquisition_id'], edition_id=identity['edition_id'], provider='Christian Classics Ethereal Library', url=args['source_url'], route='born-digital', retained_files=[member], warnings=['Print-edition collation, human acceptance, rights clearance and publication are not established.']))
    binding = make_file_binding(stage, candidate)
    scope = dict(kind='edition', declared=declared, expected_members=[dict(path=member['path'], position=1)], included_members=[{k: member[k] for k in ('path', 'bytes', 'sha256', 'scope')} | dict(position=1)], excluded_members=[])
    common = dict(identity=identity, source=source, candidate=binding, scope=declared, accepted_scope=dict(kind='edition', declared=declared), **{k: scope[k] for k in ('expected_members', 'included_members', 'excluded_members')}, missing_members=[], unknown_members=[])
    observations = dict(validation='Exact historical candidate passed current independent oracle; derived header passes TEI XSD.', accounting='Current oracle verified complete source accounting, provenance and unresolved records against the retained source.', fidelity='Current oracle verified exact expected TEI bytes and tree. Header additions are reversible; historical whole-artifact traversal and fourteen close-comparison anchors remain bounded.', reproducibility='Header derivation repeated in a second Python process with identical output; no new source reconstruction claimed.', schema='Current vendored TEI XSD accepts derived candidate.', closure='Current replay inputs including imported XSDs are hash-verified before staging; integration implementation hashes recorded.')
    command = 'py -3 -m build.tools.integrate_reviewed_wesley --stage ' + str(stage)
    technical = dict(producer=dict(id='reviewed-wesley-header-adapter-v1'), checker=dict(id='wesley-independent-oracle-and-reversible-header-check'), shared_assumptions=['Producer and oracle share retained-source declarations and schema; historical review provides separately bounded corroboration.'], independent_corroboration='Current independent source-derived oracle replay plus unchanged reviewed text and historical fourteen-anchor visual review.')
    implementation = {str(p.relative_to(root)).replace('\\', '/'): sha(p.read_bytes()) for p in (Path(__file__).resolve(), root / 'ocd_kernel/tei/reviewed_integration.py', root / 'ocd_kernel/tei/acceptance.py')}
    for name, observation in observations.items():
        path = evidence / (name + '.json')
        write(path, common | dict(status='pass', command=command, exit_code=0, checked_at=now, observation=observation, implementation=implementation))
        technical[name] = dict(path=path, status='pass', command=command, exit_code=0)
    account = evidence / 'source-accounting.json'; write(account, common | dict(source_sha256=member['sha256'], source_bytes=member['bytes']))
    anchors = [item['label'] for item in json.loads(review_bytes)['close_comparison_anchors']]
    review = dict(reviewer='agent:reviewed-wesley-integration', reviewed_at=now, coverage=dict(status='partial', declared=declared, reached=['complete-reviewed-candidate', *anchors], inspected=anchors, unreviewed=[]), source_quality_uncertainty=['No print-edition collation.'], discrepancies=[], unreviewed_residuals=['Historical whole-candidate traversal with fourteen targeted anchors is not exhaustive proofreading; no fresh visual review.'])
    write(evidence / 'review.json', common | review)
    decision = dict(source_local_disposition='Exact reviewed candidate integrated with preserved historical header and scoped acceptance additions.', blockers=[], agent_assessment=dict(status='accepted', actor='agent:reviewed-wesley-integration', assessed_at=now, supported_scope=declared, unassessed_stronger_claims=['human acceptance', 'print-edition fidelity', 'rights clearance', 'publication'], unresolved_claims=[]), human_decision=dict(status='not-recorded'))
    write(work / 'state.json', dict(schema_version='2.0', work_id=WORK, targets=[dict(target_id=identity['edition_id'], target_type='edition', stage='review', updated_at=now, reason='Reviewed candidate and current checker evidence reconciled.', evidence=[binding['path']])]))
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate, source_accounting_path=account, scope=scope, technical=technical, review=review | dict(report_path=evidence / 'review.json'), representation_revision=args['revision'], decision=decision)
    acceptance = edition / 'acceptance.json'; write_acceptance(acceptance, record); validate_acceptance(acceptance, root=stage)
    return acceptance


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    args = parser.parse_args()
    print(prepare(ROOT, args.stage.resolve()))
