"""Finish only the changed L637 proof case, final guards, and byte replays.

Earlier valid source challenges stay dated evidence. Every child uses the
frozen supported CLI or independent proof driver; no canonical installation.
"""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import json,subprocess,sys
from lxml import etree
from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from build.tools.prove_tyerman_samuel_retained import enc,run_fresh,write_new
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage

HOME='sources/manifest-acquisitions/tyerman-samuel-retained-install-20261004-v1'
LOG=ROOT/'reports/_logs/tyerman-samuel-existing-install-20261004-v1'
PACKAGE=Path('D:/Library/Open Christian Data/candidate-reviews/tyerman-samuel-readable-20261004-v3/package')
PACKAGE_SHA='8f812fc98c12a7268999afd1d35ee0e66ac91d10d16b8679e72c996b6600380a'
SOURCE_SHA='c92e55520624c505f874bec43b4bc95281ce66630b8e3ae5a858154dc8082c39'

def sha(b):return sha256(b).hexdigest()
def pin(p):return dict(path=p.as_posix(),bytes=p.stat().st_size,sha256=sha(p.read_bytes()))
def command(cmd):
    r=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,check=False)
    return dict(command=cmd,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr)
def frozen_runtime():
    record=json.loads((ROOT/(HOME+'/runtime.json')).read_bytes())
    for key in ('first_party_files','external_runtime_files'):
        for row in record[key]:
            p=ROOT/row['path'] if key=='first_party_files' else Path(row['path'])
            if p.stat().st_size!=row['bytes'] or sha(p.read_bytes())!=row['sha256']:raise ValueError('Frozen runtime drift: '+str(p))
    row=record['runtime_executable'];p=Path(sys.executable).resolve()
    if row!=pin(p):raise ValueError('Runtime executable drift')
    return record

def main():
    runtime=frozen_runtime();source=SourceManifest.load(ROOT/(HOME+'/source-manifest.json'),repository_root=ROOT);candidate=CandidatePackage.load(PACKAGE)
    if source.sha256!=SOURCE_SHA or candidate.sha256!=PACKAGE_SHA:raise ValueError('Exact final source/package differs')
    proof=LOG/'source-proof-v3';proof.mkdir(exist_ok=False)
    before=json.loads((LOG/'source-contract-v2/source-manifest.json').read_bytes())
    current=json.loads((ROOT/(HOME+'/source-manifest.json')).read_bytes())
    for k in ('converter','validator','source_order','scope','work_id','source_id'):
        a=dict(before[k]) if isinstance(before[k],dict) else before[k];b=dict(current[k]) if isinstance(current[k],dict) else current[k]
        if k=='validator':a.pop('import_closure_sha256');b.pop('import_closure_sha256')
        if a!=b:raise ValueError('Source semantics changed during proof-only renewal: '+k)
    for name in ('primary-html','retained-archive','profile','policy','readme','producer','oracle','tei-validation-schema','candidate-package-schema'):
        a=next(r for r in before['authorities'] if r['name']==name);b=next(r for r in current['authorities'] if r['name']==name)
        if a!=b:raise ValueError('Source/body authority changed: '+name)
    old_package=Path('D:/Library/Open Christian Data/candidate-reviews/tyerman-samuel-readable-20261004-v2/package')
    for name in ('content.tei.xml','README.source.md','unresolved.jsonl'):
        if (old_package/name).read_bytes()!=candidate.member_bytes(name):raise ValueError('Invariant payload changed: '+name)
    baseline=run_fresh('oracle',PACKAGE,output=proof/'independent-source-readback.json');write_new(proof/'baseline-process.json',enc(baseline))
    if baseline['exit_code']!=0:raise ValueError('Current guarded source baseline failed: '+baseline['stderr'])
    schema=etree.XMLSchema(etree.parse(str(source.authority_path('tei-validation-schema'))))
    package_schema=json.loads(source.authority_path('candidate-package-schema').read_bytes())
    old_runner=LOG/'source-proof-v2/proof-runner.py'
    if sha(old_runner.read_bytes())!='d5d82397a67e176ff77da6b16de67e0704c97b224d6d6549d17962af91b6c49e':raise ValueError('Dated source proof runner differs')
    cases=[]
    for path in sorted((LOG/'source-proof-v2/mutants').iterdir()):
        c=CandidatePackage.load(path);m=json.loads((path/'manifest.json').read_bytes());Draft202012Validator(package_schema).validate(m)
        if not schema.validate(etree.fromstring(c.member_bytes('content.tei.xml'))):raise ValueError('Dated challenge is not P5-valid: '+path.name)
        process=LOG/('source-proof-v2/'+path.name+'-process.json');r=json.loads(process.read_bytes())
        error='Complete repair ledger' if path.name.startswith('account-') else 'Complete actual TEI envelope/header/body'
        if r['exit_code']==0 or error not in r['stderr']:raise ValueError('Dated intended source rejection differs: '+path.name)
        cases.append(dict(name=path.name,p5_valid=True,package_schema_valid=True,rejected=True,candidate_sha256=c.sha256,source_manifest_sha256=m['source_manifest']['sha256'],process=pin(process),runner=pin(old_runner),qualification='Dated v2 negative execution retained. Current source oracle/producer/profile/policy/raw and repaired TEI bytes are unchanged; only proof-harness/runtime/source-contract metadata bindings renew.'))
    if len(cases)!=32 or sum(r['name'].startswith('account-') for r in cases)!=3:raise ValueError('Exact 29 source plus 3 accounting denominator differs')
    contracts=[]
    errors={'work-id':'Exact work/source identity','source-id':'Exact work/source identity','scope':'Exact complete biography scope','manifest-row':'Exact complete biography scope','source-order':'Ordered retained source members','authority-order':'Exact ordered authority','authority-role':'Exact ordered authority'}
    for name,error in errors.items():
        process=LOG/('source-proof-v2/'+name+'-contract-process.json');r=json.loads(process.read_bytes())
        p=LOG/('source-proof-v2/contract-mutants/'+name);c=CandidatePackage.load(p);Draft202012Validator(package_schema).validate(json.loads((p/'manifest.json').read_bytes()))
        if r['exit_code']==0 or error not in r['stderr']:raise ValueError('Dated source contract intended rejection differs: '+name)
        contracts.append(dict(name=name,rejected=True,intended_guard=error,package_schema_valid=True,p5_valid=True,candidate_sha256=c.sha256,process=pin(process),runner=pin(old_runner),qualification='Dated v2 guard execution on serialized SDK-loaded source manifest; current semantic implementation and authority bytes are unchanged.'))
    wrong=HOME+'/challenges-v3/producer-id/source-manifest.json'
    loaded=SourceManifest.load(ROOT/wrong,repository_root=ROOT)
    destination=Path('D:/Library/Open Christian Data/candidate-reviews/tyerman-samuel-producer-id-negative-20261004-v3')
    if destination.exists():raise FileExistsError('Preserve negative destination: '+str(destination))
    cmd=[sys.executable,'-I','-B',str(ROOT/'build/tools/reconstruct_candidate.py'),'--manifest',wrong,'--destination',str(destination),'--repository-root',str(ROOT)]
    r=command(cmd);write_new(proof/'producer-id-supported-cli-process.json',enc(r))
    if r['exit_code']==0 or 'converter callable provenance mismatch' not in r['stderr']:raise ValueError('Supported CLI producer identity negative failed: '+r['stderr'])
    contracts.append(dict(name='producer-id',rejected=True,intended_guard='converter callable provenance mismatch',source_manifest_load_valid=True,source_manifest_sha256=loaded.sha256,process=pin(proof/'producer-id-supported-cli-process.json'),fresh_supported_cli=True))
    negatives=[]
    for location,p in [('checkout',ROOT/'.tmp_audit/tyerman-samuel-unexpected-v1.py'),('library',LOG/'tyerman-samuel-unexpected-v1.py')]:
        write_new(p,b'EXACT_UNEXPECTED_IMPORT = True\n')
        for mode in ('oracle','producer-negative'):
            r=run_fresh(mode,PACKAGE,extra=p);process=proof/(location+'-'+mode+'-late-import-process.json');write_new(process,enc(r))
            error='Unexpected or changed executed oracle dependency' if mode=='oracle' else 'Unexpected or changed executed producer dependency'
            if r['exit_code']==0 or error not in r['stderr']:raise ValueError('Actual late unexpected import was not rejected: '+location+' '+mode+' '+r['stderr'])
            negatives.append(dict(location=location,mode=mode,rejected=True,actual_late_execution=True,dependency=pin(p),process=pin(process)))
    replays=[]
    for i in (1,2):
        destination=Path('D:/Library/Open Christian Data/candidate-reviews')/('tyerman-samuel-readable-20261004-replay-'+str(i))
        if destination.exists():raise FileExistsError('Preserve replay: '+str(destination))
        cmd=[sys.executable,'-I','-B',str(ROOT/'build/tools/reconstruct_candidate.py'),'--manifest',HOME+'/source-manifest.json','--destination',str(destination),'--repository-root',str(ROOT)]
        r=command(cmd);process=proof/('replay-'+str(i)+'-process.json');write_new(process,enc(r))
        if r['exit_code']!=0:raise ValueError('Fresh supported replay failed: '+r['stderr'])
        replay=CandidatePackage.load(destination/'package')
        if replay.sha256!=candidate.sha256 or any(replay.member_bytes(n)!=candidate.member_bytes(n) for n in candidate.member_names):raise ValueError('Fresh six-member replay differs')
        replays.append(dict(destination=destination.as_posix(),fresh_isolated_python=True,six_member_bytes_equal=True,member_pins={n:pin(destination/'package'/n) for n in candidate.member_names},validation=pin(destination/'validation.json'),process=pin(process)))
    if runtime!=frozen_runtime():raise ValueError('Final frozen runtime changed')
    source.verify();candidate.verify_integrity()
    readback=json.loads((proof/'independent-source-readback.json').read_bytes())
    receipt=dict(contract='ocd-l637-source-completion-proof-v3',status='pass',at=datetime.now(timezone.utc).isoformat(),complete_works=1,work_id='tyerman-life-times-samuel-wesley-1866',candidate_sha256=candidate.sha256,source_manifest_sha256=source.sha256,current_source_readback=pin(proof/'independent-source-readback.json'),semantic_challenges=cases,source_contract_challenges=contracts,strict_late_import_negatives=negatives,fresh_six_member_replays=replays,producer=pin(ROOT/'build/tei/tyerman_samuel_retained_repair.py'),oracle=pin(ROOT/'build/tei/tyerman_samuel_source_oracle.py'),proof_driver=pin(ROOT/'build/tools/prove_tyerman_samuel_retained.py'),completion_orchestrator=pin(Path(__file__)),runtime=pin(ROOT/(HOME+'/runtime.json')),execution_qualification='Producer and independent oracle child processes enforce their exact executed module/runtime guards; this outer work-specific orchestration code is separately pinned. Prior 29 valid source and3 accounting negatives plus7 contract guards are dated and explicitly retained, not claimed as current reruns.',source_profile=pin(ROOT/(HOME+'/profile.json')),policy=pin(ROOT/(HOME+'/policy.json')),readme=pin(ROOT/(HOME+'/README.source.md')),identity_proposal=pin(LOG/'primary-work-identity-proposal-v2.json'),payload_comparison=pin(LOG/'proof-successor-payload-comparison-v3.json'),candidate_members={n:pin(PACKAGE/n) for n in candidate.member_names},validation=pin(PACKAGE.parent/'validation.json'),finite_source_census={k:readback[k] for k in ('complete_works','textual_members','archive_members','source_body_elements','corrections','span_languages','images')},acceptance='nonaccepted; root source/identity review and separate installation release required',publication='not authorized')
    p=proof/'source-completion-proof.json';write_new(p,enc(receipt));print(enc(dict(status='pass',proof=p.as_posix(),sha256=sha(p.read_bytes()))).decode(),end='')

if __name__=='__main__':main()
