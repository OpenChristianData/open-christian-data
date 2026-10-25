"""Bounded source challenges and isolated replays for the existing L637 work."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime, timezone
import argparse, importlib.util, json, shutil, subprocess, sys
from lxml import etree
from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
HOME='sources/manifest-acquisitions/tyerman-samuel-retained-install-20261004-v1'
LOG=ROOT/'reports/_logs/tyerman-samuel-existing-install-20261004-v1'
T='{http://www.tei-c.org/ns/1.0}';X='{http://www.w3.org/XML/1998/namespace}';NS={'t':T[1:-1]}

def enc(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def sha(v):return sha256(v).hexdigest()
def write_new(p,raw):
    if p.exists():raise FileExistsError('Preserve existing proof: '+str(p))
    p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
def load_extra(path):
    spec=importlib.util.spec_from_file_location('_l637_unreviewed_dependency',path);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
def oracle(args):
    from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage
    from build.tei import tyerman_samuel_source_oracle as o
    source=SourceManifest.load(ROOT/args.manifest,repository_root=ROOT);candidate=CandidatePackage.load(args.candidate)
    if args.unexpected:load_extra(args.unexpected)
    if args.late_unexpected:
        expected=o.expected_header
        def late(*values):
            result=expected(*values);load_extra(args.late_unexpected);return result
        o.expected_header=late
    result=o.check(source,candidate)
    result.update(contract='ocd-l637-independent-source-proof-v1',source_manifest_sha256=source.sha256,candidate_sha256=candidate.sha256,oracle_sha256=sha(Path(o.__file__).read_bytes()),producer_imported=any(getattr(m,'__file__',None) and Path(m.__file__).name=='tyerman_samuel_retained_repair.py' for m in sys.modules.copy().values()))
    if result['producer_imported']:raise ValueError('Independent oracle process imported producer')
    if args.output:write_new(Path(args.output),enc(result))
    else:sys.stdout.write(enc(result).decode())
def producer_negative(args):
    from ocd_kernel.reconstruction.contract import SourceManifest
    from build.tei import tyerman_samuel_retained_repair as p
    source=SourceManifest.load(ROOT/args.manifest,repository_root=ROOT)
    block=p.footer_block;injected=False
    def late(*values):
        nonlocal injected
        result=block(*values)
        if not injected:load_extra(args.late_unexpected);injected=True
        return result
    p.footer_block=late;p._convert(source)
    raise ValueError('Unexpected producer import was not rejected')

def seal_package(path,members,source_record=None):
    manifest=json.loads(members['manifest.json'])
    if source_record:manifest['source_manifest']=source_record
    manifest['members']=[dict(name=n,bytes=len(members[n]),sha256=sha(members[n])) for n in sorted(members) if n!='manifest.json']
    schema=json.loads((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes())
    Draft202012Validator(schema).validate(manifest)
    members['manifest.json']=enc(manifest)
    path.mkdir(exist_ok=False,parents=True)
    for n,b in members.items():(path/n).write_bytes(b)
    return manifest

def run_fresh(mode,candidate,manifest=HOME+'/source-manifest.json',output=None,extra=None,driver_root=ROOT):
    cmd=[sys.executable,'-I','-B',str(driver_root/'build/tools/prove_tyerman_samuel_retained.py'),'--mode',mode,'--manifest',manifest]
    if candidate:cmd.extend(['--candidate',str(candidate)])
    if output:cmd.extend(['--output',str(output)])
    if extra:cmd.extend(['--late-unexpected',str(extra)])
    result=subprocess.run(cmd,cwd=driver_root,capture_output=True,text=True,check=False)
    return dict(command=cmd,exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr)

def prove(args):
    from ocd_kernel.reconstruction.contract import CandidatePackage,SourceManifest
    candidate=CandidatePackage.load(args.candidate);source=SourceManifest.load(ROOT/(HOME+'/source-manifest.json'),repository_root=ROOT)
    proof=LOG/'source-proof-v3';proof.mkdir(exist_ok=False)
    baseline=run_fresh('oracle',candidate.path,output=proof/'independent-source-readback.json')
    write_new(proof/'baseline-process.json',enc(baseline))
    if baseline['exit_code']!=0:raise ValueError('Fresh independent baseline failed: '+baseline['stderr'])
    raw={n:(candidate.path/n).read_bytes() for n in candidate.member_names}
    raw['manifest.json']=(candidate.path/'manifest.json').read_bytes()
    schema=etree.XMLSchema(etree.parse(str(source.authority_path('tei-validation-schema'))))
    cases=[]
    def body_case(name,change):
        members=dict(raw);doc=etree.fromstring(raw['content.tei.xml']);change(doc)
        insist=schema.validate(doc)
        if not insist:raise ValueError('Source challenge is not P5-valid: '+name+' '+str(schema.error_log.last_error))
        members['content.tei.xml']=etree.tostring(doc,encoding='UTF-8',xml_declaration=True)
        path=proof/'mutants'/name;sealed=seal_package(path,members)
        result=run_fresh('oracle',path)
        write_new(proof/(name+'-process.json'),enc(result))
        if result['exit_code']==0 or 'Complete actual TEI envelope/header/body' not in result['stderr']:raise ValueError('Source challenge did not fail whole actual graph: '+name)
        cases.append(dict(name=name,p5_valid=True,package_schema_valid=True,candidate_sha256=sha(enc(sealed)),rejected=True,rejection='Complete actual TEI envelope/header/body direct fields, attributes, order, or attachment differ',process_sha256=sha(enc(result))))
    def one(doc,xpath):return doc.xpath(xpath,namespaces=NS)[0]
    def omit(doc,xpath):n=one(doc,xpath);n.getparent().remove(n)
    def attr(doc,xpath,key,value):one(doc,xpath).set(key,value)
    def text(doc,xpath):n=one(doc,xpath);n.text=(n.text or '')+' invented'
    def swap(doc,xpath):
        a,b=doc.xpath(xpath,namespaces=NS)[:2];p=a.getparent();q=b.getparent();i=p.index(a);j=q.index(b);p.remove(a);q.remove(b);p.insert(i,b);q.insert(j,a)
    body_case('correction-tooltip-omission',lambda d:one(d,'.//t:hi[starts-with(@rend,"ins")]').attrib.pop('n'))
    body_case('correction-tooltip-invention',lambda d:attr(d,'.//t:hi[starts-with(@rend,"ins")]', 'n','fabricated correction'))
    body_case('span-language-change',lambda d:attr(d,'.//t:hi[@xml:lang]',X+'lang','fr'))
    body_case('paragraph-presentation-class',lambda d:attr(d,'.//t:p[starts-with(@rend,"source-p ")]','rend','source-p fabricated'))
    body_case('column-style-omission',lambda d:one(d,'.//t:milestone[@unit="source-column"][@style]').attrib.pop('style'))
    body_case('heading-wording',lambda d:text(d,'.//t:head[starts-with(@rend,"source-h1")]'))
    body_case('paragraph-omission',lambda d:omit(d,'.//t:p[starts-with(@rend,"source-p")]'))
    body_case('cell-words',lambda d:text(d,'.//t:cell'))
    body_case('cell-colspan',lambda d:attr(d,'.//t:cell[@cols]','cols','1'))
    body_case('table-row-order',lambda d:swap(d,'.//t:table/t:row'))
    body_case('list-item-order',lambda d:swap(d,'.//t:list/t:item'))
    body_case('footnote-payload',lambda d:text(d,'.//t:div[contains(@rend,"footnote")]//t:p[starts-with(@rend,"source-p")]'))
    body_case('inline-owner-order',lambda d:swap(d,'.//t:hi[starts-with(@rend,"i")]'))
    body_case('inline-tail-words',lambda d:setattr(one(d,'.//t:hi[starts-with(@rend,"i")]'),'tail',' invented tail'))
    body_case('fragment-target-change',lambda d:attr(d,'.//t:ref[starts-with(@target,"#")]', 'target','#pg-header'))
    body_case('absolute-target-change',lambda d:attr(d,'.//t:ref[starts-with(@target,"https:")]', 'target','https://example.invalid/source'))
    body_case('graphic-payload-change',lambda d:attr(d,'.//t:graphic','url','data:image/jpeg;base64,AA=='))
    body_case('graphic-member-context',lambda d:attr(d,'.//t:graphic','corresp','urn:ocd:retained-archive:wrong:member:images/cover.jpg'))
    body_case('graphic-fabricated-network-base',lambda d:attr(d,'.//t:graphic',X+'base','https://www.gutenberg.org/ebooks/67980/'))
    body_case('graphic-empty-alt-omission',lambda d:one(d,'.//t:graphic').attrib.pop('n'))
    body_case('graphic-attachment-order',lambda d:swap(d,'.//t:graphic'))
    body_case('provider-footer-license-words',lambda d:text(d,'.//t:back//t:div[@type="source-footer"]//t:div[@type="source-div"]/t:p[normalize-space(.)!=""]'))
    body_case('provider-footer-link-context',lambda d:attr(d,'.//t:back//t:ref','target','https://example.invalid/license'))
    body_case('provider-author-identity',lambda d:text(d,'./t:teiHeader/t:fileDesc/t:titleStmt/t:author'))
    body_case('head-metadata-field',lambda d:text(d,'.//t:p[@n="source-head-1"]/t:seg[@type="source-attributes"]'))
    body_case('raw-document-suffix',lambda d:text(d,'.//t:p[@n="source-html-document-suffix"]/t:seg'))
    body_case('located-root-comment',lambda d:text(d,'.//t:p[@n="source-root-child-3-administration-comment-fields"]/t:seg[@type="source-text"]'))
    body_case('body-leading-whitespace-invention',lambda d:setattr(one(d,'./t:text/t:body'),'text','\n'))
    def extra(d):
        a=etree.SubElement(one(d,'./t:text/t:body'),T+'div');etree.SubElement(a,T+'p').text='Invented readable outer sibling'
    body_case('outer-readable-sibling',extra)
    for name,modify,error in [('account-ledger-omission',lambda a:a['changed_attribute_families'].pop(),'Complete repair ledger'),('account-ledger-invention',lambda a:a['changed_attribute_families'].append(dict(family='invented',ordinal=0,before={},after={})),'Complete repair ledger'),('account-producer-pin',lambda a:a.update(producer_sha256='0'*64),'Complete repair ledger')]:
        members=dict(raw);account=json.loads(members['source-accountability.json']);modify(account);members['source-accountability.json']=enc(account)
        path=proof/'mutants'/name;sealed=seal_package(path,members);result=run_fresh('oracle',path);write_new(proof/(name+'-process.json'),enc(result))
        if result['exit_code']==0 or error not in result['stderr']:raise ValueError('Accounting challenge failed: '+name)
        cases.append(dict(name=name,p5_valid=True,package_schema_valid=True,rejected=True,candidate_sha256=sha(enc(sealed)),process_sha256=sha(enc(result))))
    contracts=[]
    original_manifest=json.loads((ROOT/(HOME+'/source-manifest.json')).read_bytes())
    contract_mutations=[('work-id',lambda m:m.update(work_id='tyerman-other-book'),'Exact work/source identity'),('source-id',lambda m:m.update(source_id='gutenberg-67980-other'),'Exact work/source identity'),('scope',lambda m:m.update(scope='Different complete book'),'Exact complete biography scope'),('manifest-row',lambda m:m.update(manifest_row='L000'),'Exact complete biography scope'),('source-order',lambda m:m['source_order']['archive_members'].reverse(),'Ordered retained source members'),('authority-order',lambda m:m['authorities'].reverse(),'Exact ordered authority'),('authority-role',lambda m:m['authorities'][0].update(role='retained-source-archive'),'Exact ordered authority'),('producer-id',lambda m:m['converter'].update(id='wrong-current-producer'),'Exact composite producer')]
    for name,modify,error in contract_mutations:
        m=json.loads(enc(original_manifest));modify(m)
        fixture=ROOT/'.tmp_audit/tyerman-samuel-source-contract-fixtures-v3'/name
        if fixture.exists():raise FileExistsError('Preserve contract fixture: '+str(fixture))
        fixture.mkdir(parents=True)
        paths={r['path'] for r in original_manifest['authorities']}
        runtime=json.loads((ROOT/(HOME+'/runtime.json')).read_bytes())
        paths.update(r['path'] for r in runtime['first_party_files'])
        for relative in sorted(paths):write_new(fixture/relative,(ROOT/relative).read_bytes())
        path=fixture/(HOME+'/source-manifest.json');write_new(path,enc(m));loaded=SourceManifest.load(path,repository_root=fixture)
        members=dict(raw);manifest=json.loads(members['manifest.json']);manifest['source_id']=m['source_id'];manifest['converter']=m['converter'];members['manifest.json']=enc(manifest)
        candidate_path=proof/'contract-mutants'/name;sealed=seal_package(candidate_path,members,dict(path=HOME+'/source-manifest.json',sha256=loaded.sha256))
        result=run_fresh('oracle',candidate_path,driver_root=fixture);write_new(proof/(name+'-contract-process.json'),enc(result))
        if result['exit_code']==0 or error not in result['stderr']:raise ValueError('Source contract challenge failed intended guard: '+name+' '+result['stderr'])
        contracts.append(dict(name=name,source_manifest_load_valid=True,package_schema_valid=True,p5_valid=True,rejected=True,intended_guard=error,source_manifest_sha256=loaded.sha256,candidate_sha256=sha(enc(sealed)),process_sha256=sha(enc(result)),isolated_root=fixture.as_posix(),actual_canonical_relative_manifest_path=HOME+'/source-manifest.json'))
    imports=[]
    for location,path in [('checkout',ROOT/'.tmp_audit/tyerman-samuel-unexpected-v1.py'),('library',LOG/'tyerman-samuel-unexpected-v1.py')]:
        write_new(path,b'EXACT_UNEXPECTED_IMPORT = True\n')
        for mode in ('oracle','producer-negative'):
            result=run_fresh(mode,candidate.path,extra=path);write_new(proof/(location+'-'+mode+'-late-import-process.json'),enc(result))
            expected='Unexpected or changed executed oracle dependency' if mode=='oracle' else 'Unexpected or changed executed producer dependency'
            if result['exit_code']==0 or expected not in result['stderr']:raise ValueError('Late import guard failed: '+location+' '+mode)
            imports.append(dict(location=location,mode=mode,late_execution=True,rejected=True,dependency_path=path.as_posix(),dependency_sha256=sha(path.read_bytes()),process_sha256=sha(enc(result))))
    replays=[]
    for i in (1,2):
        destination=Path('D:/Library/Open Christian Data/candidate-reviews')/('tyerman-samuel-readable-20261004-replay-'+str(i))
        if destination.exists():raise FileExistsError('Preserve replay: '+str(destination))
        cmd=[sys.executable,'-I','-B',str(ROOT/'build/tools/reconstruct_candidate.py'),'--manifest',HOME+'/source-manifest.json','--destination',str(destination),'--repository-root',str(ROOT)]
        run=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,check=False);result=dict(command=cmd,exit_code=run.returncode,stdout=run.stdout,stderr=run.stderr);write_new(proof/('replay-'+str(i)+'-process.json'),enc(result))
        if run.returncode!=0:raise ValueError('Fresh supported replay failed: '+run.stderr)
        files={n:dict(bytes=(destination/'package'/n).stat().st_size,sha256=sha((destination/'package'/n).read_bytes())) for n in raw}
        expected_files={n:dict(bytes=len(b),sha256=sha(b)) for n,b in raw.items()}
        if files!=expected_files:raise ValueError('Fresh six-member bytes differ')
        replays.append(dict(destination=destination.as_posix(),isolated_fresh_process=True,six_member_bytes_equal=True,member_pins=files,process_sha256=sha(enc(result)),validation_sha256=sha((destination/'validation.json').read_bytes())))
    receipt=dict(contract='ocd-l637-source-completion-proof-v1',at=datetime.now(timezone.utc).isoformat(),candidate_sha256=candidate.sha256,source_manifest_sha256=source.sha256,source_readback_sha256=sha((proof/'independent-source-readback.json').read_bytes()),semantic_challenges=cases,source_contract_challenges=contracts,strict_late_import_negatives=imports,fresh_six_member_replays=replays,status='pass',acceptance='nonaccepted; held for root source/identity review')
    write_new(proof/'source-completion-proof.json',enc(receipt));sys.stdout.write(enc(dict(status='pass',proof=(proof/'source-completion-proof.json').as_posix(),sha256=sha(enc(receipt)))).decode())

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=['oracle','producer-negative','prove'],required=True);parser.add_argument('--manifest',default=HOME+'/source-manifest.json');parser.add_argument('--candidate');parser.add_argument('--output');parser.add_argument('--unexpected');parser.add_argument('--late-unexpected');args=parser.parse_args()
    if args.mode=='oracle':oracle(args)
    elif args.mode=='producer-negative':producer_negative(args)
    else:prove(args)
