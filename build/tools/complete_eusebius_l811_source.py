"""Finite required source proof for one retained three-tome L811 work.

This outer orchestrator is separately pinned. Each actual source-checking child
enforces the reviewed frozen execution closure. No ordinary test suite runs.
"""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import copy,json,shutil,subprocess,sys
from lxml import etree

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from ocd_kernel.reconstruction import CandidatePackage,SourceManifest
from ocd_kernel.tei.validate import validate_file
from jsonschema import Draft202012Validator

HOME='sources/manifest-acquisitions/eusebius-l811-retained-install-20261004-v1'
LOG=ROOT/'reports/_logs/eusebius-l811-existing-install-20261004-v1'
BASE=Path('D:/Library/Open Christian Data/candidate-reviews/eusebius-l811-retained-repair-20261004-v1')
PROOF=LOG/'source-proof-v1';NS='{http://www.tei-c.org/ns/1.0}';X='{http://www.w3.org/XML/1998/namespace}'

def enc(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def sha(v):return sha256(v).hexdigest()
def pin(p):
    p=Path(p);b=p.read_bytes();return dict(path=p.as_posix(),bytes=len(b),sha256=sha(b))
def fresh(p,raw):
    p=Path(p)
    if p.exists():raise FileExistsError('Preserve L811 proof: '+str(p))
    p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
def process(name,command,cwd=ROOT,expected=None):
    r=subprocess.run(command,cwd=cwd,capture_output=True,text=True,encoding='utf-8',check=False)
    target=PROOF/(name+'-process.json');fresh(target,enc(dict(command=command,cwd=Path(cwd).as_posix(),exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr)))
    print(json.dumps(dict(step=name,exit_code=r.returncode)),flush=True)
    if expected is None:
        if r.returncode:raise ValueError('Required child failed; saved '+str(target))
    elif not r.returncode or expected not in r.stdout+r.stderr:
        raise ValueError('Negative did not fail for intended reason; saved '+str(target))
    return pin(target)
def cli(root,destination,manifest=HOME+'/source-manifest.json'):
    return [sys.executable,'-I','-B',str(root/'build/tools/reconstruct_candidate.py'),'--manifest',manifest,'--destination',str(destination),'--repository-root',str(root)]
def check(package,output=None,late=None):
    c=[sys.executable,'-I','-B',str(ROOT/'build/tools/prove_eusebius_l811_retained.py'),'--package',str(package)]
    if output:c+=['--output',str(output)]
    if late:c+=['--late-import',str(late)]
    return c
def reseal(package,name,payload):
    (package/name).write_bytes(payload);manifest=json.loads((package/'manifest.json').read_bytes())
    for row in manifest['members']:
        raw=(package/row['name']).read_bytes();row.update(bytes=len(raw),sha256=sha(raw))
    (package/'manifest.json').write_bytes(enc(manifest))
def clone_root(source,runtime,destination):
    if destination.exists():raise FileExistsError(destination)
    destination.mkdir(parents=True)
    paths={HOME+'/source-manifest.json'}|{a['path'] for a in source.record['authorities']}|{r['path'] for r in runtime['first_party_files']}
    pins=[]
    for relative in sorted(paths):
        src=ROOT/relative;dst=destination/relative
        if not dst.resolve().is_relative_to(destination.resolve()):raise ValueError('Clone escaped its exact root')
        dst.parent.mkdir(parents=True,exist_ok=True);raw=src.read_bytes();dst.write_bytes(raw);pins.append(dict(path=relative,sha256=sha(raw),bytes=len(raw)))
    return pins
def first(tree,name,predicate=lambda n:True):return next(n for n in tree.iter(NS+name) if predicate(n))

def complete():
    if PROOF.exists():raise FileExistsError('Preserve earlier source proof')
    PROOF.mkdir()
    source=SourceManifest.load(ROOT/(HOME+'/source-manifest.json'),repository_root=ROOT)
    runtime=json.loads(source.authority_path('runtime').read_bytes());runtime_before=sha(source.authority_path('runtime').read_bytes());manifest_before=source.sha256
    baseline=BASE/'strict-final-v1'
    strict_process=process('strict-maintained-cli',cli(ROOT,baseline))
    package=baseline/'package';candidate=CandidatePackage.load(package)
    if sha(candidate.member_bytes('content.tei.xml'))!='29d0845997301ec67aef8625d5014b402ffe552590296db2ca65742944db0697':raise ValueError('Reviewed source payload changed')
    readback=PROOF/'independent-whole-source-readback.json';readback_process=process('fresh-independent-source-readback',check(package,readback))
    facts=json.loads(readback.read_bytes());schema=json.loads(source.authority_path('candidate-package-schema').read_bytes());schema_checker=Draft202012Validator(schema)
    original=candidate.member_bytes('content.tei.xml');tree=etree.fromstring(original);cases=[]
    def mutation(name,modify,reason):
        path=BASE/'semantic-challenges-v1'/name/'package';path.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(package,path)
        actual=etree.fromstring(original);modify(actual)
        payload=etree.tostring(actual,encoding='UTF-8',xml_declaration=True)
        if payload==original:raise ValueError('Mutation did not alter actual TEI '+name)
        reseal(path,'content.tei.xml',payload);errors=validate_file(path/'content.tei.xml')
        fresh(PROOF/(name+'-P5.json'),enc(dict(valid=not errors,errors=errors,tei_sha256=sha(payload))))
        if errors:raise ValueError('Intended source feature mutation is not P5 valid '+name)
        changed=CandidatePackage.load(path);schema_checker.validate(json.loads(changed.member_bytes('manifest.json')))
        result=process(name,check(path),expected=reason)
        cases.append(dict(name=name,p5_valid=True,package_schema_valid=True,candidate=pin(path/'manifest.json'),tei=pin(path/'content.tei.xml'),process=result,intended_reason=reason))
    def volumes(t):return t.find(NS+'text/'+NS+'body')
    def admin(t):return t.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'sourceDesc')[-3][0]
    def exchange(parent):
        a=parent[0];b=parent[1];parent.remove(a);parent.remove(b);parent.insert(0,b);parent.insert(1,a)
    mutation('omit-tome-III',lambda t:volumes(t).remove(volumes(t)[2]),'Exactly three complete source tomes required')
    mutation('swap-tomes-I-II',lambda t:exchange(volumes(t)),'Actual tome envelope differs')
    mutation('omit-German-preface',lambda t:volumes(t)[0][1].remove(volumes(t)[0][1][0]),'Actual whole source-body envelope differs')
    mutation('swap-source-Ps-sections',lambda t:exchange(volumes(t)[0][1][1]),'Actual source field/order/attachment differs')
    mutation('invent-direct-prose',lambda t:setattr(first(volumes(t)[0][1][1],'p',lambda n:bool(n.text and n.text.strip())),'text','invented source prose'),'Actual source field/order/attachment differs')
    mutation('alter-mixed-tail',lambda t:setattr(next(n for n in t.iter() if isinstance(n.tag,str) and n.tail and n.tail.strip()),'tail','changed source tail'),'Actual source field/order/attachment differs')
    mutation('alter-source-comment',lambda t:setattr(next(n for n in t.iter() if n.tag==etree.Comment),'text','changed retained source comment'),'Actual source field/order/attachment differs')
    mutation('alter-lemma',lambda t:setattr(first(t,'lem',lambda n:bool(n.text)),'text','changed lemma'),'Actual source field/order/attachment differs')
    mutation('alter-reading-witness',lambda t:first(t,'rdg',lambda n:'wit' in n.attrib).set('wit','#unattested-witness'),'Actual source field/order/attachment differs')
    def move_app(t):
        n=first(t,'app',lambda n:n.getparent().tag==NS+'p' and len(n.getparent())>1);p=n.getparent();i=p.index(n);p.remove(n);p.insert(0 if i else len(p),n)
    mutation('move-apparatus-attachment',move_app,'Actual source field/order/attachment differs')
    mutation('alter-witDetail-target',lambda t:first(t,'witDetail',lambda n:'target' in n.attrib).set('target','wrong-literal-source-target'),'Actual source field/order/attachment differs')
    mutation('alter-Hebrew-language',lambda t:next(n for n in t.iter() if isinstance(n.tag,str) and n.get(X+'lang') in ('heb','he')).set(X+'lang','ar'),'Actual source field/order/attachment differs')
    mutation('invent-document-base',lambda t:volumes(t)[0].set(X+'base','https://invalid.example/invented/'),'Actual tome envelope differs')
    mutation('alter-scoped-source-ID',lambda t:next(n for n in t.iter() if isinstance(n.tag,str) and n.get(X+'id')).set(X+'id','wrong-scoped-source-id'),'Actual source field/order/attachment differs')
    mutation('alter-cRef',lambda t:next(n for n in t.iter() if isinstance(n.tag,str) and 'cRef' in n.attrib).set('cRef','Ps 999'),'Actual source field/order/attachment differs')
    mutation('alter-witStart',lambda t:first(t,'witStart').set('n','invented-boundary'),'Actual source field/order/attachment differs')
    mutation('alter-lacunaEnd',lambda t:first(t,'lacunaEnd').set('n','invented-lacuna-boundary'),'Actual source field/order/attachment differs')
    mutation('duplicate-administration-field',lambda t:admin(t).append(copy.deepcopy(admin(t)[0])),'Administration field cardinality differs')
    mutation('alter-source-prolog',lambda t:setattr(next(p for p in admin(t) if p.get('n')=='literal_document_prefix'),'text','invented prolog'),'Actual raw-backed administration field differs')
    mutation('omit-source-wrapper-status',lambda t:setattr(next(p for p in admin(t) if p.get('n')=='source_shell_fields'),'text','[]'),'Actual raw-backed administration field differs')
    def witness(t):
        n=volumes(t)[0][1]
        for i in (2,40,3,2,26,1,2,1):n=n[i-1]
        n.set('wit',n.get('wit').rstrip())
    mutation('remove-repaired-witness-space',witness,'Actual source field/order/attachment differs')
    accounting=[]
    for name,modify in [('omit-repair-ledger',lambda a:a['repairs'].pop()),('invent-repair-ledger',lambda a:a['repairs'].append(dict(family='invented'))),('alter-ledger-authority',lambda a:a.update(source_profile_sha256='0'*64))]:
        path=BASE/'accounting-challenges-v1'/name/'package';path.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(package,path)
        account=json.loads((path/'source-accountability.json').read_bytes());modify(account);reseal(path,'source-accountability.json',enc(account));schema_checker.validate(json.loads((path/'manifest.json').read_bytes()))
        receipt=process(name,check(path),expected='Complete actual repair ledger differs');accounting.append(dict(name=name,p5_valid=True,unchanged_tei_sha256=sha((path/'content.tei.xml').read_bytes()),package_schema_valid=True,process=receipt))
    outer=[]
    for name,modify in [('wrong-candidate-source-path',lambda m:m['source_manifest'].update(path='sources/wrong/source-manifest.json')),('wrong-candidate-schema',lambda m:m['package_schema'].update(path='schemas/wrong.json')),('wrong-candidate-converter-ID',lambda m:m['converter'].update(id='wrong-producer'))]:
        path=BASE/'contract-challenges-v1'/name/'package';path.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(package,path)
        m=json.loads((path/'manifest.json').read_bytes());modify(m);(path/'manifest.json').write_bytes(enc(m));schema_checker.validate(m)
        receipt=process(name,check(path),expected='Exact outer candidate manifest record/path/schema/status differs');outer.append(dict(name=name,package_schema_valid=True,p5_valid=True,process=receipt))
    late=[]
    for label,path in [('checkout',ROOT/'build/tools/eusebius_l811_unexpected_late_v1.py'),('physical-Library',LOG/'runtime-negatives-v1/unexpected_library.py')]:
        fresh(path,b'VALUE = "intentional unexpected late execution"\n')
        receipt=process('late-'+label,check(package,late=path),expected='Unexpected or changed L811 executed dependency:')
        evidence=json.loads(Path(receipt['path']).read_bytes())
        if 'after-full-source-and-P5-before-final-runtime-guard' not in evidence['stdout']:raise ValueError('Import was not genuinely late')
        late.append(dict(boundary=label,module=pin(path),process=receipt,checkpoint='after-full-source-and-P5-before-final-runtime-guard'))
    replays=[]
    for number in (1,2):
        root=BASE/f'isolated-replay-v1-{number}'/'repository';copied=clone_root(source,runtime,root);destination=root.parent/'candidate'
        receipt=process(f'isolated-maintained-replay-{number}',cli(root,destination),cwd=root)
        replay=CandidatePackage.load(destination/'package');same={n:sha(replay.member_bytes(n))==sha(candidate.member_bytes(n)) for n in candidate.member_names}
        if not all(same.values()):raise ValueError('Fresh maintained six-member replay differs')
        replay_record=PROOF/f'isolated-replay-{number}-inputs.json';fresh(replay_record,enc(copied));replays.append(dict(process=receipt,isolated_inputs=pin(replay_record),six_members_identical=same,package=pin(destination/'package/manifest.json')))
    # A serialized alternate source path exercises the standalone direct path
    # guard through the unmodified CLI without editing the reviewed manifest.
    alternate=ROOT/(HOME+'/contract-negatives-v1/alternate-source-manifest.json');fresh(alternate,(ROOT/(HOME+'/source-manifest.json')).read_bytes())
    source_negative=process('alternate-source-manifest-path',cli(ROOT,BASE/'alternate-source-path-negative-v1',alternate.relative_to(ROOT).as_posix()),expected='Declared source-manifest root/path differs')
    if source.sha256!=manifest_before or sha(source.authority_path('runtime').read_bytes())!=runtime_before:raise ValueError('Frozen source/runtime changed during proof')
    source.verify()
    root_before=json.loads((LOG/'whole-retained-assessment-v1.json').read_bytes())['canonical_before']
    for relative,row in root_before.items():
        if sha((ROOT/'library/works/eusebius-commentarii-in-psalmos'/relative).read_bytes())!=row['sha256']:raise ValueError('Original canonical file changed')
    failures=[pin(LOG/f'observed-bootstrap-command-v{i}.json') for i in (1,2,3)]
    receipt=dict(contract='ocd-l811-existing-source-completion-v1',status='source-technically-proven-nonaccepted',at=datetime.now(timezone.utc).isoformat(),work_id='eusebius-commentarii-in-psalmos',source_tomes=3,complete_authored_works=1,candidate_members={n:pin(package/n) for n in candidate.member_names},validation=pin(baseline/'validation.json'),strict_cli_process=strict_process,independent_readback=pin(readback),independent_readback_process=readback_process,semantic_challenges=cases,accounting_challenges=accounting,outer_candidate_contract_challenges=outer,source_path_contract_negative=source_negative,late_import_negatives=late,fresh_isolated_six_member_replays=replays,source_manifest=pin(ROOT/(HOME+'/source-manifest.json')),profile=pin(source.authority_path('complete-source-feature-profile')),policy=pin(source.authority_path('independent-validation-policy')),runtime=pin(source.authority_path('runtime')),source_readme=pin(source.authority_path('source-attribution')),code=[pin(ROOT/p) for p in ['build/tei/eusebius_l811_retained_repair.py','build/tei/eusebius_l811_source_oracle.py','build/tei/eusebius_l811_runtime.py','build/tools/capture_eusebius_l811_source.py','build/tools/prove_eusebius_l811_retained.py','build/tools/complete_eusebius_l811_source.py']],finite_census={k:facts[k] for k in ('actual_source_carrier_nodes','attributes_compared','rewritten_reference_attributes')},qualification='Scoped electronic witness, source I/II draft and work in progress, III approved; Greek authored text/German prefaces; literal source-native Psalm numbers and unresolved sigla/XPath/bare/bibliographic targets; no print/visual/human acceptance claim.',bootstrap_history=dict(failed_commands=failures,defects='Attempt1 governed reports destination; attempt2 nonexistent P5 import/API; attempt3 attestation digest used detailed result instead of maintained self-attestation record. All failures retained and no partial runtime or failed package was reused. Bootstrap4 is observation, strict-final CLI is validation.',success=pin(LOG/'observed-bootstrap-command-v4.json')),canonical_original_five_unchanged=True,agent_acceptance='not recorded',canonical_installation='not performed',publication='not authorized')
    final=LOG/'source-completion-packet-v1.json';fresh(final,enc(receipt));return dict(status=receipt['status'],packet=pin(final),package=str(package),tei_sha256=sha(original),valid_semantic_challenges=len(cases),accounting_challenges=len(accounting),candidate_contract_challenges=len(outer),late_import_negatives=len(late),isolated_replays=len(replays))

if __name__=='__main__':print(json.dumps(complete(),sort_keys=True))
