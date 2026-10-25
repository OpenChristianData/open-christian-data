"""Prepare the exact two reviewed Equiano volumes as one technical edition."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from lxml import etree
from build.tools.integrate_reviewed_wesley import sha, write
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import source_member_set_bytes
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.reviewed_composition import compose_reviewed_documents, verify_reviewed_composition
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
WORK = 'equiano-interesting-narrative-1789'
PACKAGES = ('02c77024b6ba5514af7ef5e0be51cacf8467912d4e9dde58f5e55d956981cc8d', 'd37439f2a590ac0e467c9e7e6103972f7499819ba50d24d0fbd3ccec74bb9c08')


def _assert_replay_payloads_match(
    historical: CandidatePackage, current: CandidatePackage, part: int
) -> None:
    """Keep binding-only regeneration from silently changing reviewed payloads."""

    for name in current.member_names:
        if name == 'manifest.json':
            continue
        if historical.member_bytes(name) != current.member_bytes(name):
            raise PipelineError(f'Equiano replay payload changed for volume {part}: {name}')


def prepare(root: Path, stage: Path) -> Path:
    if stage.exists():
        raise PipelineError('Equiano staging root must be fresh')
    ready = json.loads((root / 'plans/2026-08-31-library-pipeline-redesign/artifacts/PIPE-004/12-additional-integration-readiness.json').read_bytes())['items'][1]
    candidate_roots = ready.get('candidate_roots')
    if not isinstance(candidate_roots, list) or len(candidate_roots) != len(PACKAGES):
        raise PipelineError('reviewed Equiano continuation must declare both ordered members')
    work = stage / 'library/works' / WORK
    evidence = work / 'integration/reviewed-equiano-v1'
    members, retained, validations, attribution = [], [], [], []
    identity = dict(work_id=WORK, textual_form_id='equiano-english', edition_id='ecco-second-edition', acquisition_id='ecco-two-volumes')
    scope_text = 'Complete ordered volumes 1 and 2 of the retained ECCO-TCP second-edition transcription; original volume headers and explicit gaps preserved. No print-image collation.'
    with tempfile.TemporaryDirectory(prefix='ocd-equiano-current-replay-') as replay_root:
        for i, directory in enumerate(candidate_roots, 1):
            name = WORK + f'-part-{i}'
            manifest_path = root / 'sources/structured-text' / name / (name + '.source-manifest.json')
            manifest = SourceManifest.load(manifest_path, repository_root=root)
            historical = CandidatePackage.load(Path(directory) / 'package')
            if historical.sha256 != PACKAGES[i-1]:
                raise PipelineError('reviewed Equiano package changed')
            reconstruction = importlib.import_module(f'build.tei.equiano_interesting_narrative_1789_part_{i}_reconstruction')
            replay_parent = Path(replay_root) / f'part-{i}'
            replay_parent.mkdir()
            current = reconstruct(
                manifest,
                replay_parent / 'package',
                reconstruction._convert,
            )
            _assert_replay_payloads_match(historical, current, i)
            oracle = importlib.import_module(f'build.tei.equiano_interesting_narrative_1789_part_{i}_oracle')
            validation = validate(manifest, current, oracle._oracle)
            if validation.status != 'pass':
                raise PipelineError('current Equiano validation failed')
            validations.append(dict(
                part=i,
                status=validation.status,
                attestation=dict(validation.attestation),
                validation_sha256=validation.sha256,
                historical_package_sha256=historical.sha256,
                current_package_sha256=current.sha256,
                payloads_byte_identical=True,
            ))
            original = current.member_bytes('content.tei.xml')
            members.append((original, sha(original)))
            primary = [dict(a) for a in manifest.record['authorities'] if a['role'] == 'primary-source']
            if len(primary) != 1:
                raise PipelineError('Equiano volume requires one explicit primary XML member')
            item = primary[0]
            retained.append({k: item[k] for k in ('path', 'bytes', 'sha256')} | dict(media_type='application/xml', scope=f'Complete retained volume {i} ETS XML'))
            part = evidence / f'part-{i}'; part.mkdir(parents=True)
            shutil.copytree(historical.path, part / 'historical-package')
            shutil.copytree(current.path, part / 'current-package')
            (part / 'source-manifest.json').write_bytes(manifest_path.read_bytes())
            source = stage / item['path']; source.parent.mkdir(parents=True, exist_ok=True); source.write_bytes(resolve_repo_path(root, item['path']).read_bytes())
            attribution.append(f'## Volume {i}\n\n'.encode() + current.member_bytes('README.source.md'))
    review_path = root / 'plans/2026-08-31-sample-first-library-verification/30-equiano-visual-continuation-20260906.md'
    review_raw = review_path.read_bytes(); frames = {}
    for name, digest in re.findall(r'\| `([^`]+\.jpg)` \|[^\n]*?`([0-9a-f]{64})`', review_raw.decode()):
        image = review_path.parent / 'artifacts/equiano-20260906' / name
        if sha(image.read_bytes()) != digest:
            raise PipelineError('historical Equiano frame changed: ' + name)
        frames[name] = digest
    if len(frames) != 6 or any(digest not in review_raw.decode() for digest in PACKAGES):
        raise PipelineError('historical review does not bind both volumes and six frames')
    (evidence / 'historical-review.md').write_bytes(review_raw)
    write(evidence / 'current-validation.json', validations)
    (work / 'README.source.md').write_bytes(b'# Equiano source attribution\n\n' + b'\n\n'.join(attribution))
    acquisition = dict(schema_version='2.0', acquisition_id=identity['acquisition_id'], edition_id=identity['edition_id'], provider='Text Creation Partnership', url='https://github.com/Text-Creation-Partnership/ECCO-TCP', route='born-digital', retained_files=retained, source_kind='retained-member-set', source_path=(evidence / 'source-member-set.json').relative_to(stage).as_posix(), source_scope=scope_text, warnings=['Historical rights wording requires human review before publication; image rights and human acceptance are not established.'])
    set_bytes = source_member_set_bytes(acquisition); (stage / acquisition['source_path']).write_bytes(set_bytes)
    acquisition.update(source_bytes=len(set_bytes), source_sha256=sha(set_bytes))
    source = {key: acquisition[key] for key in ('source_kind', 'source_path', 'source_bytes', 'source_sha256', 'source_scope')}
    revision = dict(id='reviewed-equiano-composition-v1', date='2026-09-10', note='Ordered complete reviewed volume documents retained in a single edition container; original member bytes preserved apart from XML declarations.')
    header = b'<teiHeader xmlns="http://www.tei-c.org/ns/1.0"><fileDesc><titleStmt><title>The Interesting Narrative, two-volume second edition</title></titleStmt><publicationStmt><p>Private technical integration; human acceptance and publication are not recorded.</p></publicationStmt><sourceDesc><bibl><note>Ordered complete reviewed volume documents, with original source descriptions preserved in each volume.</note></bibl></sourceDesc></fileDesc></teiHeader>'
    shell = b'<TEI xmlns="http://www.tei-c.org/ns/1.0">'+header+b'<text><body><p>Header derivation envelope</p></body></text></TEI>'
    bound = bind_reviewed_header(shell, expected_sha256=sha(shell), identity=identity, source=source, source_url=acquisition['url'], declared_scope=scope_text, revision=revision)
    header = bound[bound.index(b'<teiHeader'):bound.index(b'</teiHeader>')+len(b'</teiHeader>')]
    candidate = evidence / 'candidate.tei.xml'; composed = compose_reviewed_documents(header, members); candidate.write_bytes(composed)
    if verify_reviewed_composition(composed, header, members) or validate_file(candidate):
        raise PipelineError('Equiano composition or schema verification failed')
    (evidence / 'composition-header.xml').write_bytes(header)
    write(evidence / 'composition-members.json', [dict(path=f'part-{i}/current-package/content.tei.xml', sha256=digest) for i, (_, digest) in enumerate(members, 1)])
    worker = "import sys,json; from pathlib import Path; from ocd_kernel.tei.reviewed_composition import compose_reviewed_documents; p=Path(sys.argv[1]); m=json.loads((p/'composition-members.json').read_bytes()); sys.stdout.buffer.write(compose_reviewed_documents((p/'composition-header.xml').read_bytes(),[((p/r['path']).read_bytes(),r['sha256']) for r in m]))"
    if subprocess.run([sys.executable, '-c', worker, str(evidence)], cwd=root, check=True, capture_output=True).stdout != composed:
        raise PipelineError('Equiano composition reproduction differs')
    title = ''.join(etree.fromstring(members[0][0]).find('.//{http://www.tei-c.org/ns/1.0}sourceDesc/{http://www.tei-c.org/ns/1.0}bibl/{http://www.tei-c.org/ns/1.0}title').itertext())
    edition = work / 'forms' / identity['textual_form_id'] / 'editions' / identity['edition_id']
    write(work / 'work.json', dict(schema_version='2.0', work_id=WORK, title=title, evidence=[r['path'] for r in retained], textual_forms=[dict(textual_form_id=identity['textual_form_id'], language='en', editions=[dict(edition_id=identity['edition_id'], title='Second edition, volumes 1 and 2', language='en', category='prose', acquisition_ids=[identity['acquisition_id']])])]))
    write(edition / 'acquisitions' / (identity['acquisition_id']+'.json'), acquisition)
    binding = make_file_binding(stage, candidate); now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    scope = dict(kind='edition', declared=scope_text, expected_members=[dict(path=r['path'], position=i) for i, r in enumerate(retained, 1)], included_members=[{k:r[k] for k in ('path','bytes','sha256','scope')} | dict(position=i) for i,r in enumerate(retained,1)], excluded_members=[])
    common = dict(identity=identity, source=source, candidate=binding, scope=scope_text, accepted_scope=dict(kind='edition', declared=scope_text), **{k:scope[k] for k in ('expected_members','included_members','excluded_members')}, missing_members=[], unknown_members=[])
    observations = dict(validation='Both exact reviewed packages pass current independent validators; complete composition passes schema.', accounting='Both primary XML members included in source order, with original per-volume accountability retained.', fidelity='Independent per-volume source check plus complete composed-member tree comparison; six historical visual anchors remain bounded.', reproducibility='Composition reproduced in a second Python process with identical bytes.', schema='Composed edition passes current vendored TEI P5 XSD.', closure='Current validator attestations and composition/acceptance implementation hashes retained.')
    command = 'py -3 -m build.tools.integrate_reviewed_equiano --stage '+str(stage)
    implementation = {p.relative_to(root).as_posix():sha(p.read_bytes()) for p in (Path(__file__).resolve(), root/'ocd_kernel/tei/reviewed_composition.py', root/'ocd_kernel/tei/acceptance.py', root/'ocd_kernel/library/acquisitions.py')}
    technical = dict(producer=dict(id='reviewed-equiano-composition-v1'), checker=dict(id='independent-volume-oracles-and-composition-comparison'), shared_assumptions=['Source declarations and XML schema are shared; original whole-document preservation and historical bounded visual observations corroborate independently.'], independent_corroboration='Separate per-volume oracles, ordered member-tree comparison, original byte preservation and six exact historical frames.')
    for name, observation in observations.items():
        path=evidence/(name+'.json'); write(path,common|dict(status='pass', command=command, exit_code=0, checked_at=now, observation=observation, implementation=implementation, historical_frames=frames)); technical[name]=dict(path=path,status='pass',command=command,exit_code=0)
    account=evidence/'source-accounting.json'; write(account,common|dict(source_sha256=source['source_sha256'],source_bytes=source['source_bytes']))
    review=dict(reviewer='agent:reviewed-equiano-integration',reviewed_at=now,coverage=dict(status='partial',declared=scope_text,reached=list(frames),inspected=list(frames),unreviewed=[]),source_quality_uncertainty=['Explicit transcription gaps retained; no print-image collation.'],discrepancies=[],unreviewed_residuals=['Six historical beginning/middle/end anchors across both volumes; no exhaustive visual traversal or fresh visual review.'])
    write(evidence/'review.json',common|review)
    decision=dict(source_local_disposition='Two complete reviewed volume documents integrated as one ordered edition.',blockers=[],agent_assessment=dict(status='accepted',actor='agent:reviewed-equiano-integration',assessed_at=now,supported_scope=scope_text,unassessed_stronger_claims=['human acceptance','print-image fidelity','rights clearance','publication'],unresolved_claims=[]),human_decision=dict(status='not-recorded'))
    write(work/'state.json',dict(schema_version='2.0',work_id=WORK,targets=[dict(target_id=identity['edition_id'],target_type='edition',stage='review',updated_at=now,reason='Both reviewed volumes and ordered composition verified.',evidence=[binding['path']])]))
    record=build_acceptance_record(stage,identity=identity,candidate_path=candidate,source_accounting_path=account,scope=scope,technical=technical,review=review|dict(report_path=evidence/'review.json'),representation_revision=revision,decision=decision)
    acceptance=edition/'acceptance.json';write_acceptance(acceptance,record);validate_acceptance(acceptance,root=stage)
    return acceptance


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--stage',type=Path,required=True)
    print(prepare(ROOT,parser.parse_args().stage.resolve()))
