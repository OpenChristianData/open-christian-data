"""Prepare exact current release inputs and notice gate, without releasing."""
from datetime import datetime, timezone
from hashlib import sha256
import ast
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.dont_write_bytecode=True
from ocd_kernel.library._common import io_path,io_glob
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.selection import validate_release_selection

WORK=Path('library/works/watson-beatitudes')
EDITION=WORK/'forms/watson-beatitudes-route-source-form/editions/watson-beatitudes-retained-thml-route'
PUB=WORK/'publication'
LOG=Path('reports/_logs/watson-beatitudes-downstream-preflight-20261002-v1')
SOURCE_NOTICE='sources/prose/watson-beatitudes/README.source.md'
DATA_NOTICE='data/prose/watson-beatitudes/README.md'
AMEND=LOG/'selection-preimage-amendment-v3'
SELECTION_BEFORE='2141400dfcb36a6bde4a03f7bb4907243bbebba3ce0ba1104833fa2074d1d591'

def digest(path):
    return sha256(io_path(ROOT/path).read_bytes()).hexdigest()

def read(path):
    return json.loads(io_path(ROOT/path).read_bytes())

def save(path,value):
    p=io_path(ROOT/path)
    p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():
        raise FileExistsError('Do not overwrite a frozen proposal: '+str(path))
    p.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')

def main():
    output=Path('reports/_logs/watson-beatitudes-private-release-20261002-v2')
    if io_path(ROOT/output).exists() or io_path(ROOT/PUB/'completion.json').exists():
        raise FileExistsError('Release output must remain absent during review preparation')
    selection_path=PUB/'selection.json'
    preserved=AMEND/'selection-v1.before.json'
    if digest(selection_path)!=SELECTION_BEFORE or digest(preserved)!=SELECTION_BEFORE:
        raise ValueError('Canonical selection or preserved preimage changed')
    integrated=read(LOG/'canonical-integration-v3.json')
    for p,h in integrated['protected_inputs'].items():
        if digest(Path(p))!=h:
            raise ValueError('Protected integration input changed: '+p)
    for p,h in integrated['after_files'].items():
        if digest(Path(p))!=h:
            raise ValueError('Installed generation changed: '+p)
    check=read(LOG/'closure-successor-proposal/installed-focused-tests.json')
    assert check['exit_code']==0 and len(check['runtime_loads'])==11
    assert io_path(ROOT/LOG/'closure-successor-proposal/installed-focused-tests.log.exit').read_text()=='0'
    assert check['canonical_shared_sha256']==digest(Path('ocd_kernel/tei/acceptance.py'))
    authority={p.relative_to(ROOT).as_posix():digest(p.relative_to(ROOT))
        for p in io_glob(ROOT/WORK,'**/*') if io_path(p).is_file() and 'publication' not in p.relative_to(ROOT/WORK).parts}
    authority['raw/ccel/watson/beatitudes.xml']=digest(Path('raw/ccel/watson/beatitudes.xml'))
    for p in io_glob(ROOT/'sources/structured-text/watson-beatitudes','**/*'):
        if io_path(p).is_file():
            authority[p.relative_to(ROOT).as_posix()]=digest(p.relative_to(ROOT))
    for directory in [LOG]:
        for p in io_glob(ROOT/directory,'**/*'):
            if io_path(p).is_file():
                authority[p.relative_to(ROOT).as_posix()]=digest(p.relative_to(ROOT))
    for p in [SOURCE_NOTICE,DATA_NOTICE,'docs/sources/ccel-permission.md',
              'build/tools/preflight_watson_beatitudes_private.py','build/tools/prepare_watson_beatitudes_closure_proposal.py',
              'build/tools/integrate_watson_beatitudes_closure_v3.py','build/tools/check_watson_beatitudes_installed_closure.py',
              'build/tools/freeze_watson_beatitudes_private_release.py',
              'tests/test_watson_beatitudes_current_closure.py',integrated['journal_path']]:
        authority[p]=digest(Path(p))
    # The failed v1 reached no projection. Its map enumerates the intended
    # dependencies, then every binding is refreshed from actual current bytes.
    prior=read(Path('reports/_logs/watson-beatitudes-private-release-20261002-v1/schema-implementation-before.json'))
    runtime={p:digest(Path(p)) for p in prior}
    runtime['ocd_kernel/reconstruction/contract.py']=digest(Path('ocd_kernel/reconstruction/contract.py'))
    runtime['sources/structured-text/watson-beatitudes/watson_beatitudes_oracle.py']=digest(Path('sources/structured-text/watson-beatitudes/watson_beatitudes_oracle.py'))
    runner=PUB/'complete_private_release.py'
    ast.parse(io_path(ROOT/runner).read_text(encoding='utf-8'))
    assert runner.as_posix() in runtime
    binding=dict(source_path=SOURCE_NOTICE,source_sha256=authority[SOURCE_NOTICE],notice_path=DATA_NOTICE,notice_sha256=authority[DATA_NOTICE])
    selection=dict(schema_version='2.0',release_id='watson-beatitudes-private-offline-20261002-v2',
        items=[dict(item_id='watson-beatitudes',category='prose',acceptance_path=(EDITION/'acceptance.json').as_posix(),public_notices=[binding])])
    validated = validate_release_selection(selection)
    assert validated == selection
    selection_proof = AMEND/'selection-preflight.json'
    save(selection_proof,dict(status='pass',validator='ocd_kernel.release.selection.validate_release_selection',
        validator_sha256=digest(Path('ocd_kernel/release/selection.py')),selection=validated,
        optional_work_id_omitted=True,full_library_work_coverage_not_claimed=True,assembly_not_run=True))
    authority[selection_proof.as_posix()]=digest(selection_proof)
    assert notice_texts_for_item(ROOT,selection['items'][0],ROOT/EDITION/'acceptance.json')==[io_path(ROOT/DATA_NOTICE).read_text(encoding='utf-8')]
    postimage=AMEND/'selection-v2.expected.json'
    payload=(json.dumps(selection,sort_keys=True,ensure_ascii=True,indent=2)+'\n').encode('utf-8')
    io_path(ROOT/postimage).parent.mkdir(parents=True,exist_ok=True)
    with io_path(ROOT/postimage).open('xb') as stream:
        stream.write(payload)
    control=dict(path=selection_path.as_posix(),before_sha256=SELECTION_BEFORE,
        after_sha256=sha256(payload).hexdigest(),preserved_preimage_path=preserved.as_posix(),
        preserved_preimage_sha256=digest(preserved),expected_postimage_path=postimage.as_posix(),
        expected_postimage_sha256=digest(postimage))
    preservation=AMEND/'preimage-preservation-receipt.json'
    save(preservation,dict(status='pass',controlled_selection_output=control,
        preserved_v2_freeze_sha256=digest(PUB/'release-input-freeze-v2.json'),
        output_absent=True,canonical_completion_absent=True,selection_preflight='pass',notice_preflight='pass',
        no_release_executed=True,checked_at=datetime.now(timezone.utc).isoformat()))
    # Bind every immutable preparation artifact after producing the new evidence.
    for p in io_glob(ROOT/LOG,'**/*'):
        if io_path(p).is_file():
            authority[p.relative_to(ROOT).as_posix()]=digest(p.relative_to(ROOT))
    authority[(PUB/'release-input-freeze.json').as_posix()]=digest(PUB/'release-input-freeze.json')
    authority[(PUB/'release-input-freeze-v2.json').as_posix()]=digest(PUB/'release-input-freeze-v2.json')
    record=dict(status='prepared-awaiting-coordinator-review',checked_at=datetime.now(timezone.utc).isoformat(),
        work_id='watson-beatitudes',authority_bindings=authority,schema_implementation_bindings=runtime,
        selection=selection,maintained_selection_preflight='pass',notice_preflight='pass',notice_binding=binding,canonical_master_unchanged=True,
        controlled_selection_output=control,
        integration_result_sha256=digest(LOG/'canonical-integration-v3.json'),installed_focused_test_exit_code=0,
        installed_public_validate_acceptance='pass',no_release_executed=True,
        execution_command='py -3 library/works/watson-beatitudes/publication/complete_private_release.py',
        scope='Existing exact25unit electronic route envelope; retain title/address/21chapters/appendix/indexes and existing identity/human/rights qualifications.')
    for p,h in authority.items():
        if digest(Path(p))!=h:
            raise ValueError('Preparation input drift: '+p)
    if digest(selection_path)!=SELECTION_BEFORE or io_path(ROOT/output).exists():
        raise ValueError('Selection/output changed during preparation')
    save(PUB/'release-input-freeze-v3.json',record)
    print(json.dumps(dict(status=record['status'],path=(PUB/'release-input-freeze-v3.json').as_posix(),
        sha256=digest(PUB/'release-input-freeze-v3.json'),authority_bindings=len(authority),schema_implementation_bindings=len(runtime),notice_preflight='pass',selection_preflight='pass',controlled_selection_output=control)))

if __name__=='__main__':
    main()
