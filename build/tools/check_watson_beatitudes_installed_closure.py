"""Run the reviewed regression against exact installed shared bytes."""
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.dont_write_bytecode=True
from ocd_kernel.library._common import io_path

PROPOSAL = ROOT/'reports/_logs/watson-beatitudes-downstream-preflight-20261002-v1/closure-successor-proposal'

def digest(path):
    return sha256(io_path(path).read_bytes()).hexdigest()

def main():
    import pytest
    installed = ROOT/'ocd_kernel/tei/acceptance.py'
    proposal = json.loads(io_path(PROPOSAL/'proposal.json').read_bytes())
    freeze = json.loads(io_path(PROPOSAL/'focused-proposal-freeze.json').read_bytes())
    test = 'tests/test_watson_beatitudes_current_closure.py'
    if digest(installed)!=proposal['after_sha256'] or digest(ROOT/test)!=freeze['proposal_proof_bindings'][test]:
        raise ValueError('Reviewed runtime or test bytes differ')
    fixture = json.loads(io_path(PROPOSAL/'current-fixture-proof.json').read_bytes())
    for p,h in fixture['fixture_file_bindings'].items():
        if digest(Path(fixture['fixture_root'])/p)!=h:
            raise ValueError('Pinned fixture drift: '+p)
    os.environ['OCD_BEATITUDES_CLOSURE_FIXTURE']=fixture['fixture_root']
    original = importlib.util.spec_from_file_location
    loads=[]
    def installed_only(name, location, *args, **kwargs):
        # The reviewed test imports the proposal snapshot. Redirect precisely
        # that snapshot to its byte-identical installed successor; no test or
        # canonical input is altered, and every independent oracle stays intact.
        if name=='owned_beatitudes_proposal_test' and str(location).replace('\\','/').endswith('/closure-successor-proposal/acceptance.after.py'):
            location=installed
            loads.append(dict(path=installed.as_posix(),sha256=digest(installed)))
        return original(name,location,*args,**kwargs)
    importlib.util.spec_from_file_location=installed_only
    argv=['-p','no:cacheprovider',test,'-v',*sys.argv[1:]]
    try:
        code=pytest.main(argv)
    finally:
        importlib.util.spec_from_file_location=original
    if code==0 and len(loads)!=11:
        raise ValueError('All11 tests must load installed bytes')
    record=dict(contract='ocd-installed-closure-regression-v1',exit_code=int(code),pytest_argv=argv,
        runtime_loads=loads,test_sha256=digest(ROOT/test),frozen_fixture_proof_sha256=digest(PROPOSAL/'current-fixture-proof.json'),
        canonical_shared_sha256=digest(installed),proposal_snapshot_sha256=digest(PROPOSAL/'acceptance.after.py'),
        qualification='Reviewed test bytes unchanged; exact snapshot import redirects to installed identical shared code. Public candidate/source checks use their pinned isolated fixture; canonical public acceptance separately passed during integration.')
    io_path(PROPOSAL/'installed-focused-tests.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    return int(code)

if __name__=='__main__':
    raise SystemExit(main())
