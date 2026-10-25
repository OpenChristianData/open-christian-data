"""Build an isolated current-closure fixture without canonical writes."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from ocd_kernel.library._common import io_path, io_glob
from ocd_kernel.reconstruction.contract import SourceManifest, CandidatePackage, validate

LOG = ROOT/'reports/_logs/watson-beatitudes-downstream-preflight-20261002-v1'
PROPOSAL = LOG/'closure-successor-proposal'
WORK = Path('library/works/watson-beatitudes')
EDITION = WORK/'forms/watson-beatitudes-route-source-form/editions/watson-beatitudes-retained-thml-route'
FIXTURE = Path('D:/Library/Open Christian Data/candidate-reviews/btd-v3-20261002')

def digest(p):
    return sha256(io_path(p).read_bytes()).hexdigest()

def copy(p, relative):
    target = io_path(FIXTURE/relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(io_path(p).read_bytes())

def load(path):
    name = 'owned_watson_closure_proposal'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    module.SCHEMA_PATH = FIXTURE/'schemas/v2/acceptance.schema.json'
    return module

def main():
    info = json.loads(io_path(PROPOSAL/'proposal.json').read_bytes())
    if digest(ROOT/'ocd_kernel/tei/acceptance.py') != info['before_sha256']:
        raise ValueError('Canonical shared preimage changed')
    resume = '--resume-state-support' in sys.argv
    if FIXTURE.exists() and not resume:
        raise FileExistsError('Fixture must be a fresh independent directory')
    if not FIXTURE.exists():
        FIXTURE.mkdir()
    for p in io_glob(ROOT/WORK,'**/*'):
        if io_path(p).is_file() and 'publication' not in p.relative_to(ROOT/WORK).parts:
            if resume:
                assert digest(FIXTURE/p.relative_to(ROOT)) == digest(p)
            else:
                copy(p,p.relative_to(ROOT))
    old_manifest = Path('sources/structured-text/watson-beatitudes/watson-beatitudes.source-manifest-v2.json')
    for p in io_glob(ROOT/old_manifest.parent,'**/*'):
        if io_path(p).is_file():
            copy(p,p.relative_to(ROOT))
    manifest = json.loads(io_path(PROPOSAL/'source-manifest-v3.after.json').read_bytes())
    for a in manifest['authorities']:
        copy(ROOT/a['path'],Path(a['path']))
    for p in io_glob(ROOT/'schemas/v2','**/*.json'):
        copy(p,p.relative_to(ROOT))
    copy(PROPOSAL/'source-manifest-v3.after.json',Path(info['new_manifest_path']))
    package_path = WORK/'integration/ccel-thml-closure-rebind-v3/current-candidate/package'
    for p in io_glob(ROOT/WORK/'integration/ccel-thml-closure-rebind-v2/current-candidate/package','*'):
        if p.name != 'manifest.json':
            copy(p,package_path/p.name)
    copy(PROPOSAL/'package-manifest-v3.after.json',package_path/'manifest.json')
    # State references remain immutable; the isolated mirror includes their
    # exact ticket/report evidence rather than removing those references.
    state = json.loads(io_path(ROOT/WORK/'state.json').read_bytes())
    for target in state['targets']:
        for relative in target.get('evidence', []):
            if relative.startswith('plans/'):
                copy(ROOT/relative, Path(relative))
    shared = load(io_path(PROPOSAL/'acceptance.after.py'))
    current_manifest = SourceManifest.load(FIXTURE/info['new_manifest_path'],repository_root=FIXTURE)
    package = CandidatePackage.load(FIXTURE/package_path)
    validation = validate(current_manifest,package,shared._beatitudes_oracle())
    record = shared.validate_acceptance(FIXTURE/EDITION/'acceptance.json',root=FIXTURE)
    if record['promotion']['master']['sha256'] != '07b0070649c6a6b8e6ebbfd300834299dc2d64cc3684e2198fc42dadb82b0aef':
        raise ValueError('Accepted master changed')
    identical = {p.name:digest(p) for p in io_glob(ROOT/WORK/'integration/ccel-thml-closure-rebind-v2/current-candidate/package','*') if p.name!='manifest.json'}
    for n,h in identical.items():
        if digest(FIXTURE/package_path/n)!=h:
            raise ValueError('Substantive payload changed: '+n)
    manifest_map = {p.relative_to(FIXTURE).as_posix():digest(p) for p in io_glob(FIXTURE,'**/*') if io_path(p).is_file()}
    proof = dict(status='pass-proposal-only',fixture_root=FIXTURE.as_posix(),source_manifest_sha256=current_manifest.sha256,
        package_sha256=package.sha256,substantive_payload_bindings=identical,fixture_file_bindings=manifest_map,
        oracle_result=dict(validation.attestation),public_validate_acceptance='pass',canonical_shared_preimage_unchanged=True,
        accepted_master_unchanged=True,no_converter_invoked=True,shared_successor_sha256=digest(PROPOSAL/'acceptance.after.py'),
        acceptance_sha256=digest(FIXTURE/EDITION/'acceptance.json'),
        regression_seam='Public validate_acceptance -> _validate_tei -> _check_beatitudes_for_acceptance -> SourceManifest.load/current unchanged oracle',
        existing_test='tests/test_tei_acceptance_beatitudes.py::test_versioned_rebind_public_acceptance_and_mutations',
        existing_test_limitation='Original v2 preparer also pins pre-v2 acceptance and cannot rerun against the currently installed v2; use current fixture-focused successor without changing historical tests.')
    io_path(PROPOSAL/'current-fixture-proof.json').write_text(json.dumps(proof,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    assert digest(ROOT/'ocd_kernel/tei/acceptance.py') == info['before_sha256']
    print(json.dumps(dict(status=proof['status'],fixture_files=len(manifest_map),proof_sha256=digest(PROPOSAL/'current-fixture-proof.json'),fixture_root=FIXTURE.as_posix())))

if __name__ == '__main__':
    main()
