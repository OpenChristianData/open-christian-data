"""Stage three exact reviewed Standard Ebooks editions without reconstructing them."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from lxml import etree

from build.tools.integrate_reviewed_wesley import sha, write
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import source_member_set_bytes
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import CandidatePackage
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
BASE = Path('plans/2026-08-31-library-pipeline-redesign/artifacts/PIPE-004')
CASES = {
    'paradise-lost': ('7bb539e84bdd2478046d8bc769814f0e7795084f48d5a0d8904d08277aadeb63', 'poetry', 'milton-english'),
    'imitation-of-christ': ('ae09c8d64c3bfc35215b2621b12f33e84ff680e9562f2053382ac6b69360252e', 'prose', 'benham-english'),
    'pilgrims-progress': ('4d8b2262b85ee384a386fd5654578bf20f4258df80e55837ecc00c56d297fba2', 'prose', 'bunyan-english'),
}


def prepare(root: Path, stage: Path, work_id: str) -> Path:
    if stage.exists() or work_id not in CASES:
        raise PipelineError('Requires a fresh stage and an explicitly reviewed work')
    expected, category, form = CASES[work_id]
    readiness = next(r for r in json.loads((root / BASE / '28-standard-ebooks-manifest-drift.json').read_bytes()) if r['work_id'] == work_id)
    package = CandidatePackage.load(Path(readiness['candidate_root']) / 'package')
    if package.sha256 != expected:
        raise PipelineError('Reviewed package identity changed')
    review_raw = (root / readiness['review']).read_bytes()
    reviewed = json.loads(re.search(r'```json\s+(.*?)```', review_raw.decode(), re.S).group(1))
    if reviewed['candidate']['package_sha256'] != expected:
        raise PipelineError('Review identity differs from exact package')
    recovery = readiness['historical_manifest_matches'][0]
    historical = subprocess.run(['git', 'show', recovery['git_revision'] + ':' + recovery['path']], cwd=root, check=True, capture_output=True).stdout
    if sha(historical) != reviewed['validation']['source_manifest_sha256']:
        raise PipelineError('Historical source manifest identity changed')
    manifest = json.loads(historical)
    proof_name = '35-paradise-exact-dependency-replay.json' if work_id == 'paradise-lost' else '34-standard-ebooks-exact-dependency-replay.json'
    proof = json.loads((root / BASE / proof_name).read_bytes())
    run = proof if work_id == 'paradise-lost' else next(r for r in proof['works'] if r['work_id'] == work_id)
    result = json.loads(run['stdout'])
    if (run['exit_code'] != 0 or result['status'] != 'pass' or result['findings']
            or result['sha256'] != reviewed['validation']['report_sha256']
            or result['candidate_sha256'] != expected
            or result['source_manifest_sha256'] != sha(historical)):
        raise PipelineError('Historical validation replay does not bind this review')

    # Preserve the already installed Paradise identity; subsequent editions and
    # acquisitions need globally distinct IDs, not merely distinct work paths.
    edition_id = 'retained-standard-ebooks' if work_id == 'paradise-lost' else work_id + '-standard-ebooks'
    acquisition_id = 'se-retained-checkout' if work_id == 'paradise-lost' else work_id + '-se-checkout'
    identity = dict(work_id=work_id, textual_form_id=form, edition_id=edition_id, acquisition_id=acquisition_id)
    work = stage / 'library/works' / work_id
    evidence = work / 'integration/reviewed-standard-ebooks-v1'
    evidence.mkdir(parents=True)
    shutil.copytree(package.path, evidence / 'original-package')
    (evidence / 'historical-source-manifest.json').write_bytes(historical)
    (evidence / 'historical-review.md').write_bytes(review_raw)
    (evidence / 'historical-validation-replay.json').write_bytes((root / BASE / proof_name).read_bytes())
    (work / 'README.source.md').write_bytes(package.member_bytes('README.source.md'))
    retained = []
    for authority in manifest['authorities']:
        if authority['role'] != 'primary-source':
            continue
        raw = resolve_repo_path(root, authority['path']).read_bytes()
        if len(raw) != authority['bytes'] or sha(raw) != authority['sha256']:
            raise PipelineError('Reviewed retained member changed: ' + authority['path'])
        target = stage / authority['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        retained.append({k: authority[k] for k in ('path', 'bytes', 'sha256')} | dict(scope='Complete retained checkout member', media_type='application/octet-stream'))
    original = package.member_bytes('content.tei.xml')
    tree = etree.fromstring(original)
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    title = tree.xpath('string(t:teiHeader/t:fileDesc/t:titleStmt/t:title)', namespaces=ns)
    pointers = tree.xpath('t:teiHeader//t:sourceDesc//t:ptr/@target', namespaces=ns)
    hashes = tree.xpath('t:teiHeader//t:idno[@type="sha256"]/text()', namespaces=ns)
    if not title or not pointers:
        raise PipelineError('Reviewed edition lacks a title or source pointer')
    declared = f'Complete retained Standard Ebooks checkout and its exact reviewed {title} TEI representation; all source members accounted for. No independent print-edition collation.'
    acquisition = dict(schema_version='2.0', acquisition_id=identity['acquisition_id'], edition_id=identity['edition_id'], provider='Standard Ebooks', url=pointers[0], route='born-digital', retained_files=retained, source_kind='retained-member-set', source_path=(evidence / 'source-member-set.json').relative_to(stage).as_posix(), source_scope=declared, warnings=['Historical attribution, contributor, date and rights uncertainties remain in original provenance and review; publication and human acceptance are not established.'])
    member_set = source_member_set_bytes(acquisition)
    (stage / acquisition['source_path']).write_bytes(member_set)
    acquisition.update(source_bytes=len(member_set), source_sha256=sha(member_set))
    source = {k: acquisition[k] for k in ('source_kind', 'source_path', 'source_bytes', 'source_sha256', 'source_scope')}
    revision = dict(id='reviewed-standard-ebooks-v1', date='2026-09-11', note='Reversible technical acceptance bindings added; exact reviewed header, source text and original package preserved.')
    arguments = dict(expected_sha256=sha(original), identity=identity, source=source, source_url=pointers[0], declared_scope=declared, revision=revision, historical_source_description=dict(pointers=pointers, sha256=hashes))
    derived = bind_reviewed_header(original, **arguments)
    write(evidence / 'derivation-arguments.json', arguments)
    worker = "import json,sys; from pathlib import Path; from ocd_kernel.tei.reviewed_integration import bind_reviewed_header; p=Path(sys.argv[1]); sys.stdout.buffer.write(bind_reviewed_header((p/'original-package/content.tei.xml').read_bytes(), **json.loads((p/'derivation-arguments.json').read_bytes())))"
    reproduced = subprocess.run([sys.executable, '-c', worker, str(evidence)], cwd=root, check=True, capture_output=True).stdout
    header = tree.find('{http://www.tei-c.org/ns/1.0}teiHeader')
    prefix = (header.prefix + ':') if header.prefix else ''
    header_end = ('</' + prefix + 'teiHeader>').encode('utf-8')
    if reproduced != derived or original.split(header_end, 1)[1] != derived.split(header_end, 1)[1]:
        raise PipelineError('Reversible header reproduction or reviewed text preservation failed')
    candidate = evidence / 'candidate.tei.xml'
    candidate.write_bytes(derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(str(errors))
    edition = work / 'forms' / form / 'editions' / identity['edition_id']
    write(work / 'work.json', dict(schema_version='2.0', work_id=work_id, title=title, evidence=[source['source_path']], textual_forms=[dict(textual_form_id=form, language='en', editions=[dict(edition_id=identity['edition_id'], title='Retained Standard Ebooks edition', language='en', category=category, acquisition_ids=[identity['acquisition_id']])])]))
    write(edition / 'acquisitions' / (identity['acquisition_id'] + '.json'), acquisition)
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    binding = make_file_binding(stage, candidate)
    scope = dict(kind='edition', declared=declared, expected_members=[dict(path=r['path'], position=i) for i, r in enumerate(retained, 1)], included_members=[{k:r[k] for k in ('path','bytes','sha256','scope')} | dict(position=i) for i,r in enumerate(retained,1)], excluded_members=[])
    common = dict(identity=identity, source=source, candidate=binding, scope=declared, accepted_scope=dict(kind='edition', declared=declared), **{k:scope[k] for k in ('expected_members','included_members','excluded_members')}, missing_members=[], unknown_members=[])
    command = f'py -3 -m build.tools.integrate_reviewed_standard_ebooks --work {work_id} --stage {stage}'
    observations = dict(validation='Exact historical validator report reproduced; derived header passes current TEI XSD.', accounting='All reviewed primary members hash-verified; original package accountability preserved.', fidelity='Exact reviewed text bytes retained; historical independent validation and whole-candidate review remain separately bound.', reproducibility='Reversible header derivation reproduced in a separate Python process.', schema='Derived complete candidate passes current vendored TEI P5 XSD.', closure='Historical replay preserves strict dependency fingerprints; integration code hashes recorded separately.')
    implementation = {p.relative_to(root).as_posix():sha(p.read_bytes()) for p in (Path(__file__).resolve(),root/'ocd_kernel/tei/reviewed_integration.py',root/'ocd_kernel/tei/acceptance.py',root/'ocd_kernel/library/acquisitions.py')}
    technical = dict(producer=dict(id='reviewed-standard-ebooks-header-adapter-v1'), checker=dict(id='historical-oracle-and-reversible-header-check'), shared_assumptions=['Retained manifests and schemas are shared; unchanged reviewed text and historical visual observations corroborate independently.'], independent_corroboration='Exact historical validation report reproduced and reviewed original bytes preserved.')
    for name, observation in observations.items():
        path = evidence / (name + '.json')
        write(path, common | dict(status='pass', command=command, exit_code=0, checked_at=now, observation=observation, implementation=implementation))
        technical[name] = dict(path=path, status='pass', command=command, exit_code=0)
    account = evidence / 'source-accounting.json'
    write(account, common | dict(source_sha256=source['source_sha256'], source_bytes=source['source_bytes']))
    review = dict(reviewer='agent:reviewed-standard-ebooks-integration', reviewed_at=now, coverage=dict(status='partial', declared=declared, reached=['historical-whole-candidate-review'], inspected=['historical-whole-candidate-review'], unreviewed=[]), source_quality_uncertainty=['No independent print-edition collation.'], discrepancies=[], unreviewed_residuals=['Historical review report reused; no fresh visual review. Original unresolved metadata, attribution, contributor, date and rights claims remain preserved in the original package.'])
    write(evidence / 'review.json', common | review)
    decision = dict(source_local_disposition='Exact reviewed candidate integrated through reversible header bindings.', blockers=[], agent_assessment=dict(status='accepted', actor='agent:reviewed-standard-ebooks-integration', assessed_at=now, supported_scope=declared, unassessed_stronger_claims=['human acceptance','print-edition fidelity','disputed metadata resolution','rights clearance','publication'], unresolved_claims=[]), human_decision=dict(status='not-recorded'))
    write(work / 'state.json', dict(schema_version='2.0', work_id=work_id, targets=[dict(target_id=identity['edition_id'], target_type='edition', stage='review', updated_at=now, reason='Reviewed package and exact historical validation reconciled.', evidence=[binding['path']])]))
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate, source_accounting_path=account, scope=scope, technical=technical, review=review | dict(report_path=evidence/'review.json'), representation_revision=revision, decision=decision)
    acceptance = edition / 'acceptance.json'
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    return acceptance


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', choices=sorted(CASES), required=True)
    parser.add_argument('--stage', type=Path, required=True)
    args = parser.parse_args()
    print(prepare(ROOT, args.stage.resolve(), args.work))
