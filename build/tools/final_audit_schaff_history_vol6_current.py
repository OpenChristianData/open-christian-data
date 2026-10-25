"""Final pinned canonical, retained-source, private-output, and review evidence audit."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from build.tools.prepare_schaff_history_vol6_current import ROOT,WORK,BASE,EDITION,SOURCE,SOURCE_SHA,DATA_NOTICE,SCOPE,canonical
from ocd_kernel.library._common import io_path
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.reconstruction.contract import SourceManifest

LOGS=Path('reports/_logs/schaff-history-vol-6-reconciliation-20261001-v1')
INSTALL=Path('reports/_logs/schaff-history-vol-6-install-20261001-v1')
def digest(path):return sha256(io_path(ROOT/path).read_bytes()).hexdigest()
def main():
    SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT).verify()
    pin=json.loads(io_path(ROOT/BASE/'stage-pin.json').read_bytes());stage=Path(pin['receipt']);frozen=json.loads(stage.read_bytes())
    if sha256(stage.read_bytes()).hexdigest()!=pin['receipt_sha256']:raise ValueError('frozen stage receipt changed')
    publication=WORK/'publication/private-offline-20261001';completion=json.loads(io_path(ROOT/publication/'completion.json').read_bytes())
    current={p:h for p,h in _files(ROOT/WORK).items() if not p.startswith('publication/')}
    if current!=frozen['after'] or completion['projection_rows']!=4 or completion['independent_check']['status']!='pass' or completion['reader_normal_and_streaming']!='pass':raise ValueError('installed generation/private closure failed')
    schema=frozen['schema_pins'];runtime=frozen['runtime_pins']
    if {p:digest(p) for p in schema}!=schema or {p:digest(p) for p in runtime}!=runtime:raise ValueError('schema/runtime freeze changed')
    if digest(SOURCE)!=SOURCE_SHA or completion['source_sha256']!=SOURCE_SHA or completion['master_sha256']!=digest(EDITION/'master.tei.xml'):raise ValueError('source/master binding failed')
    paths=[SOURCE,DATA_NOTICE,*[BASE/n for n in ('profile.json','validation-policy.json','README.source.md','source-manifest.json','stage-pin.json')],*[Path(p) for p in runtime],Path('docs/sources/ccel-permission.md'),
        Path('build/tei/schaff_history_vol6_current_reconstruction.py'),Path('build/tei/schaff_history_vol6_current_oracle.py'),
        *[Path('build/tools')/(r+'_schaff_history_vol6_current.py') for r in ('prepare','run','package','stage','freeze','install','release','audit','final_audit')],Path('build/tools/verify_schaff_history_vol6_header_replay.py'),
        *[LOGS/n for n in ('canonical-preimage.json','fresh-process-exact-replay.json','exact-promoted-header-replay.json','literal-class-css-public-proof.json','whole-candidate-projection.json','rollback-proof.json','notice-preflight.json','prove_isolated_rollback.py','verification-fixture-failures.json')],
        *[INSTALL/n for n in ('installation.json','installed-audit.json','metadata-prerequisite.json','original-work.json','staged-receipt.json','coordinator-installed-hash-audit.json')],Path('reports/_logs/schaff-history-vol-6-coordinator-source-review-20261001/review.json')]
    evidence={p.as_posix():digest(p) for p in paths}
    retained={}
    for label,folder in [('candidate','schaff-history-vol6-current-20261001-v1'),('replay','schaff-history-vol6-current-20261001-replay-v1'),('mutations','schaff-history-vol6-current-20261001-mutations-v1')]:
        root=Path('D:/Library/Open Christian Data/candidate-reviews')/folder
        retained[label]=dict(root=root.as_posix(),files={p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()})
    mutations=json.loads((Path(retained['mutations']['root'])/'result.json').read_bytes())
    if len(mutations['cases'])!=28 or any(c['status']!='rejected' or retained['mutations']['files'][c['name']+'.tei.xml']!=c['mutated_sha256'] for c in mutations['cases']):raise ValueError('retained mutation payloads changed')
    private=Path(completion['release']);private_files={p.relative_to(private).as_posix():sha256(p.read_bytes()).hexdigest() for p in sorted(private.rglob('*')) if p.is_file()}
    if not private_files:raise ValueError('private output absent')
    preimage=json.loads(io_path(ROOT/LOGS/'canonical-preimage.json').read_bytes())
    historical={p:digest(p) for p in preimage['historical_line_route_preserved']}
    if historical!=preimage['historical_line_route_preserved']:raise ValueError('historical line route changed')
    sibling={}
    for work,expected in preimage['sibling_authorities'].items():
        actual={p:h for p,h in _files(ROOT/'library/works'/work).items() if not p.startswith('publication/')}
        sibling[work]=dict(before=expected,current=actual,unchanged=actual==expected,phase_qualification='Active disjoint owner during preparation' if work in preimage['live_sibling_owners'] else 'Closed authority conserved')
        if work not in preimage['live_sibling_owners'] and actual!=expected:raise ValueError('closed sibling authority changed '+work)
    publication_files={p:h for p,h in _files(ROOT/WORK).items() if p.startswith('publication/')}
    receipt=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),canonical_completion=(publication/'completion.json').as_posix(),completion_sha256=digest(publication/'completion.json'),master_sha256=completion['master_sha256'],source_sha256=SOURCE_SHA,
        current_installed_hashes=current,installed_hash_count=len(current),schemas=schema,schema_count=len(schema),runtime=runtime,evidence_bindings=evidence,evidence_count=len(evidence),publication_hashes=publication_files,publication_count=len(publication_files),retained_candidate_replay_mutations=retained,
        frozen_stage_sha256=pin['receipt_sha256'],coordinator_installed_audit=json.loads(io_path(ROOT/INSTALL/'coordinator-installed-hash-audit.json').read_bytes()),sibling_authorities=sibling,active_sibling_exception='Volume VII has a separate active owner; no volume VII authority is claimed or modified by this task.',historical_route_unchanged=historical,
        private_release=completion['release'],private_release_hashes=private_files,rows=4,statistics=completion['statistics'],independent_verifier='pass',readers='normal and streaming pass',human_review='not recorded',rights_clearance='not recorded',print_equivalence='not established',public_publication='not performed or authorized',scope=SCOPE)
    output=ROOT/INSTALL/'final-delivery-audit.json';io_path(output).write_bytes(canonical(receipt));print(json.dumps(dict(status='pass',completion=receipt['canonical_completion'],completion_sha256=receipt['completion_sha256'],final_delivery_sha256=sha256(io_path(output).read_bytes()).hexdigest(),installed=len(current),schemas=len(schema),evidence=len(evidence),publication=len(publication_files),rows=4,statistics=receipt['statistics'])))
if __name__=='__main__':main()
