"""Guarded, rollback-capable integration of the reviewed closure-only fixture."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from ocd_kernel.library._common import io_path

LOG = ROOT/'reports/_logs/watson-beatitudes-downstream-preflight-20261002-v1'
PROPOSAL = LOG/'closure-successor-proposal'
WORK = Path('library/works/watson-beatitudes')
EDITION = WORK/'forms/watson-beatitudes-route-source-form/editions/watson-beatitudes-retained-thml-route'
PACKAGE = WORK/'integration/ccel-thml-closure-rebind-v3/current-candidate/package'
MANIFEST = Path('sources/structured-text/watson-beatitudes/watson-beatitudes.source-manifest-v3.json')
SHARED = Path('ocd_kernel/tei/acceptance.py')

def digest(p):
    return sha256(io_path(p).read_bytes()).hexdigest()

def save(p, data):
    p = io_path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')

def main():
    result_path = LOG/'canonical-integration-v3.json'
    if io_path(result_path).exists():
        raise FileExistsError('Inspect previous operation before another apply')
    pre = json.loads(io_path(LOG/'preflight.json').read_bytes())
    proposal = json.loads(io_path(PROPOSAL/'proposal.json').read_bytes())
    freeze = json.loads(io_path(PROPOSAL/'focused-proposal-freeze.json').read_bytes())
    fixture_proof = json.loads(io_path(PROPOSAL/'current-fixture-proof.json').read_bytes())
    fixture = Path(fixture_proof['fixture_root'])
    for rel, h in pre['input_bindings'].items():
        if digest(ROOT/rel) != h:
            raise ValueError('Protected preimage differs: '+rel)
    for rel, h in fixture_proof['fixture_file_bindings'].items():
        if digest(fixture/rel) != h:
            raise ValueError('Frozen fixture differs: '+rel)
    if digest(ROOT/SHARED) != proposal['before_sha256']:
        raise ValueError('Shared immediate preimage differs')
    test = 'tests/test_watson_beatitudes_current_closure.py'
    if digest(ROOT/test) != freeze['proposal_proof_bindings'][test]:
        raise ValueError('Reviewed focused test differs')
    if io_path(ROOT/MANIFEST).exists() or io_path(ROOT/PACKAGE.parents[1]).exists():
        raise FileExistsError('One of the required v3 targets is already present')
    sources = {MANIFEST.as_posix():PROPOSAL/'source-manifest-v3.after.json'}
    for name in ['manifest.json',*fixture_proof['substantive_payload_bindings']]:
        sources[(PACKAGE/name).as_posix()] = fixture/PACKAGE/name
    expected = {rel:digest(src) for rel, src in sources.items()}
    expected[SHARED.as_posix()] = proposal['after_sha256']
    if digest(PROPOSAL/'acceptance.after.py') != proposal['after_sha256']:
        raise ValueError('Reviewed successor bytes differ')
    token = uuid.uuid4().hex
    journal = ROOT/'.tmp_audit'/('beatitudes-closure-v3-'+token)/'operation.json'
    state = dict(contract='ocd-reviewed-work-closure-integration-v1',work_id='watson-beatitudes',
        phase='preflight',started_at=datetime.now(timezone.utc).isoformat(),
        before_shared_sha256=proposal['before_sha256'],after_files=expected,
        protected_inputs=pre['input_bindings'],focused_test_unchanged_sha256=digest(ROOT/test),
        approval='Coordinator independent review and explicit integration clearance in this session; exact four-pin delta only',
        source_or_master_conversion=False,acceptance_record_or_state_written=False)
    save(journal,state)
    created = []
    shared_applied = False
    temporary = []
    try:
        for rel, src in sources.items():
            target = io_path(ROOT/rel)
            if target.exists():
                raise FileExistsError('Target appeared during integration: '+rel)
            target.parent.mkdir(parents=True,exist_ok=True)
            temp = target.with_name('.'+target.name+'.'+token)
            temporary.append(temp)
            with temp.open('xb') as handle:
                handle.write(io_path(src).read_bytes())
            if digest(temp) != expected[rel]:
                raise ValueError('Prepared copy differs: '+rel)
            os.replace(temp,target)
            created.append(rel)
        if digest(ROOT/SHARED) != proposal['before_sha256']:
            raise ValueError('Shared preimage drift immediately before atomic replacement')
        target = ROOT/SHARED
        temp = target.with_name('.acceptance-v3-'+token+'.py')
        temporary.append(temp)
        with temp.open('xb') as handle:
            handle.write(io_path(PROPOSAL/'acceptance.after.py').read_bytes())
        if digest(temp) != proposal['after_sha256']:
            raise ValueError('Prepared shared successor differs')
        os.replace(temp,target)
        shared_applied = True
        state['phase'] = 'applied-pending-public-validation'
        save(journal,state)
        # Import only after replacement, so the public call reads installed code.
        from ocd_kernel.tei.acceptance import validate_acceptance
        from ocd_kernel.library.identities import cached_edition_lookups
        with cached_edition_lookups():
            accepted = validate_acceptance(ROOT/EDITION/'acceptance.json',root=ROOT)
        for rel,h in expected.items():
            if digest(ROOT/rel)!=h:
                raise ValueError('Installed readback differs: '+rel)
        for rel,h in pre['input_bindings'].items():
            if digest(ROOT/rel)!=h:
                raise ValueError('Protected preimage changed: '+rel)
        state.update(phase='complete',completed_at=datetime.now(timezone.utc).isoformat(),
            public_validate_acceptance='pass',unchanged_master_sha256=accepted['promotion']['master']['sha256'],
            unchanged_decision=accepted['decision'],unchanged_promotion=accepted['promotion'])
        save(journal,state)
        save(result_path,state|dict(journal_path=journal.relative_to(ROOT).as_posix(),journal_sha256=digest(journal),
            proposal_sha256=digest(PROPOSAL/'proposal.json'),focused_freeze_sha256=digest(PROPOSAL/'focused-proposal-freeze.json'),
            fixture_proof_sha256=digest(PROPOSAL/'current-fixture-proof.json')))
        print(json.dumps(dict(status='pass',installed_files=len(expected),protected_files_unchanged=len(pre['input_bindings']),
            result_sha256=digest(result_path),journal_path=journal.relative_to(ROOT).as_posix(),journal_sha256=digest(journal))))
    except Exception:
        if shared_applied:
            if digest(ROOT/SHARED)!=proposal['after_sha256']:
                raise RuntimeError('Shared file drift after apply; preserve journal and backups for coordinator recovery')
            (ROOT/SHARED).write_bytes(io_path(PROPOSAL/'acceptance.before.py').read_bytes())
        for rel in reversed(created):
            target = io_path(ROOT/rel)
            if digest(target)!=expected[rel]:
                raise RuntimeError('New fixture drift; preserve rather than remove: '+rel)
            target.unlink()
        for temp in temporary:
            if temp.exists():
                temp.unlink()
        state['phase']='rolled-back'
        save(journal,state)
        raise

if __name__=='__main__':
    main()
