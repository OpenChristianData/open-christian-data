"""Explicit source-semantic challenges/replays, not an ordinary test suite."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from build.tei import tyerman_whitefield_complete as producer
from build.tei import tyerman_whitefield_complete_oracle as oracle
from build.tei.tyerman_whitefield_runtime import observed
from ocd_kernel.reconstruction import SourceManifest, CandidatePackage

SOURCE=ROOT/'sources/manifest-acquisitions/tyerman-life-george-whitefield-complete-20261004-v3/source-manifest.json'
LOG=ROOT/'reports/_logs/tyerman-whitefield-complete-20261004-v1'
SCRATCH=ROOT/'.tmp_audit/tyerman-whitefield-complete-proof-v4'
DEST=Path('D:/Library/Open Christian Data/candidate-reviews/tyerman-whitefield-complete-20261004-v4')


def enc(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def sha(value):return hashlib.sha256(value).hexdigest()
def pin(path):
    data=path.read_bytes();return {'path':str(path),'bytes':len(data),'sha256':sha(data)}


def supported(destination):
    code='''import sys
from pathlib import Path
r=Path(sys.argv[1]);manifest=sys.argv[2];destination=sys.argv[3];sys.path.insert(0,str(r))
import build.tools.prepare_tyerman_whitefield_complete
import build.tools.prove_tyerman_whitefield_complete
from build.tools.reconstruct_candidate import main
sys.argv=['reconstruct_candidate','--manifest',manifest,'--destination',destination,'--repository-root',str(r)]
main()'''
    args=[sys.executable,'-I','-B','-c',code,str(ROOT),SOURCE.relative_to(ROOT).as_posix(),str(destination)]
    result=subprocess.run(args,check=True,capture_output=True,text=True,cwd=ROOT)
    return {'arguments':args,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr,'package':[pin(destination/'package'/name) for name in CandidatePackage.load(destination/'package').member_names],'validation':pin(destination/'validation.json')}


def reseal(directory):
    record=json.loads((directory/'manifest.json').read_bytes())
    for row in record['members']:
        data=(directory/row['name']).read_bytes();row.update(bytes=len(data),sha256=sha(data))
    (directory/'manifest.json').write_bytes(enc(record))
    return CandidatePackage.load(directory)


def semantic_mutants(base,manifest):
    root=etree.fromstring(base.member_bytes('content.tei.xml'));n=oracle.N;x=oracle.X
    variants=[]
    def add(name,change,reason):variants.append((name,change,reason))
    add('literal-language',lambda r:next(e for e in r.iter() if e.get(x+'lang')=='la').set(x+'lang','fr'),'attributes/role')
    add('abbr-expansion',lambda r:setattr(next(r.iter(n+'expan')),'text','Invented expansion'),'expan')
    add('tooltip-title',lambda r:setattr(next(e for e in r.iter(n+'note') if e.get('type')=='source-tooltip'),'text','Invented tooltip'),'note')
    add('table-summary',lambda r:setattr(next(e for e in r.iter(n+'head') if e.get('type')=='source-table-summary'),'text','Invented summary'),'head')
    add('figure-caption-target',lambda r:next(e for e in r.iter() if e.get('subtype')=='source-role-figure').set('corresp','#v44280-pg-header'),'attributes/role')
    add('inline-style',lambda r:next(e for e in r.iter() if e.get('style')).set('style','margin-left:99em;'),'attributes/role')
    add('brace-height',lambda r:next(e for e in r.iter(n+'graphic') if 'brace_lt.png' in e.get('corresp','')).set('height','3em'),'attributes/role')
    add('graphic-member',lambda r:next(r.iter(n+'graphic')).set('corresp','urn:ocd:retained:pg44280:images/coverpage.jpg'),'attributes/role')
    add('graphic-pixels',lambda r:next(r.iter(n+'graphic')).set('url',list(r.iter(n+'graphic'))[-1].get('url')),'attributes/role')
    add('fragment-target',lambda r:next(e for e in r.iter(n+'ref') if e.get('target','').startswith('#')).set('target','#v62023-pg-header'),'attributes/role')
    add('empty-heading-title',lambda r:next(e for e in r.iter(n+'head') if e.get('n')=='').set('n','Invented title'),'attributes/role')
    add('paragraph-direct-text',lambda r:setattr(next(e for e in r.iter(n+'p') if e.get('rend')=='source-p' and e.text and e.text.strip()),'text','Added payload '+next(e for e in r.iter(n+'p') if e.get('rend')=='source-p' and e.text and e.text.strip()).text),'inverse')
    add('source-tail',lambda r:setattr(next(e for e in r.iter() if e.get('ana') and e.tail),'tail','\n '+next(e for e in r.iter() if e.get('ana') and e.tail).tail),'inverse')
    add('full-header-assertion',lambda r:setattr(r.find(n+'teiHeader/'+n+'fileDesc/'+n+'titleStmt/'+n+'author'),'text','Invented author'),'header')
    add('html-head-CSS',lambda r:setattr(next(e for e in r.iter(n+'note') if e.get('type')=='source-envelope'),'text',next(e for e in r.iter(n+'note') if e.get('type')=='source-envelope').text.replace('all: inherit','all: initial',1)),'header')
    add('acquired-time',lambda r:setattr(next(e for e in r.iter(n+'note') if e.get('type')=='retained-acquisition'),'text',next(e for e in r.iter(n+'note') if e.get('type')=='retained-acquisition').text.replace('05:52:23Z','05:52:24Z')),'header')
    def table_rows(r):
        table=next(r.iter(n+'table'));rows=[e for e in table if e.tag==n+'row'];a,b=rows[:2];i=table.index(a);table.remove(b);table.insert(i,b)
    add('table-row-order',table_rows,'inverse')
    def omit(r):
        carrier=next(e for e in r.iter(n+'div') if e.get('type')=='source-body-carrier' and e[0].get('rend')=='source-p');carrier.getparent().remove(carrier)
    add('body-carrier-omission',omit,'order/duplication')
    def volume_order(r):
        group=r.find(n+'text/'+n+'group');group.insert(0,group[1])
    add('volume-order',volume_order,'text')
    def extra_volume(r):
        group=r.find(n+'text/'+n+'group');copy_volume=copy.deepcopy(group[1]);
        for e in copy_volume.iter():e.attrib.pop(x+'id',None)
        group.append(copy_volume)
    add('outer-extra-volume',extra_volume,'volume set/order')
    def footer_target(r):
        back=r.find(n+'text/'+n+'group/'+n+'text/'+n+'back');next(back.iter(n+'ref')).set('target','https://example.invalid/altered')
    add('footer-linked-structure',footer_target,'attributes/role')
    def section(r):
        table=next(r.iter(n+'table'));info=oracle.ann(table);info['sections'][0]['rows']-=1;table.set('ana',oracle.PREFIX+oracle.quote(enc(info).decode().rstrip('\n'),safe=''))
    add('table-section-ownership',section,'rows invented')
    def reparent(r):
        footer=next(e for e in r.iter(n+'div') if e.get('type')=='source-footer')
        containers=[e for e in footer.iter(n+'div') if e.get('type')=='source-div' and len(e)>1]
        source,target=next((a,b) for a in containers for b in containers if a is not b and a not in b.iterancestors() and b not in a.iterancestors())
        carrier=next(e for e in source if e.get('type')=='source-child-carrier');target.append(carrier)
    add('footer-reparenting',reparent,'inverse')
    def invent(r):
        container=next(e for e in r.iter(n+'div') if e.get('type')=='source-footer')
        para=copy.deepcopy(next(e for e in r.iter(n+'p') if e.get('rend')=='source-p' and not any(c.get(x+'id') for c in e.iter())))
        slot=etree.SubElement(container,n+'div',type='source-child-carrier');slot.append(para)
    add('invented-readable-body-payload',invent,'inverse')
    def language_fields(r):
        e=next(e for e in r.iter() if e.get(x+'lang')=='la');info=oracle.ann(e);info['attributes']['lang']='fr';e.set('ana',oracle.PREFIX+oracle.quote(enc(info).decode().rstrip('\n'),safe=''));e.set(x+'lang','fr')
    add('consistent-native-source-language-mutation',language_fields,'inverse')
    results=[];schema=etree.XMLSchema(etree.parse(str(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd')))
    for name,change,reason in variants:
        mutated=copy.deepcopy(root);change(mutated);data=etree.tostring(mutated,encoding='UTF-8',xml_declaration=True)
        if data==base.member_bytes('content.tei.xml') or not schema.validate(mutated):raise ValueError('Semantic challenge is unchanged or P5 invalid: '+name+': '+str(schema.error_log.last_error))
        folder=SCRATCH/name;shutil.copytree(base.path,folder)
        (folder/'content.tei.xml').write_bytes(data)
        account=json.loads((folder/'source-accountability.json').read_bytes());account['tei_sha256']=sha(data);(folder/'source-accountability.json').write_bytes(enc(account))
        package=reseal(folder);result=oracle._oracle(manifest,package)
        if result['status']!='fail' or not any(reason in value for value in result['findings']):raise ValueError('Intended semantic rejection not proved: '+name+' '+repr(result['findings']))
        results.append({'name':name,'P5':'pass','resealed_package_integrity':'pass','changed_content_sha256':sha(data),'package_sha256':package.sha256,'intended_rejection':result['findings']})
    return results


def contract_mutants(base,manifest):
    record=json.loads(SOURCE.read_bytes());variants=[]
    variants.append(('source-id',lambda r:r.update(source_id='gutenberg-wrong'),'identity/scope'))
    variants.append(('source-work',lambda r:r.update(work_id='tyerman-other-work'),'identity/scope'))
    variants.append(('source-scope',lambda r:r.update(scope='One volume only'),'identity/scope'))
    variants.append(('source-order',lambda r:r.update(source_order=list(reversed(r['source_order']))),'fields/order'))
    variants.append(('authority-role',lambda r:r['authorities'][0].update(role='metadata-only'),'authority'))
    variants.append(('manifest-row',lambda r:r.update(manifest_row='L634'),'fields/order'))
    variants.append(('authority-order',lambda r:r['authorities'].reverse(),'authority'))
    variants.append(('authority-name',lambda r:r['authorities'][0].update(name='unexpected-source-name'),'authority'))
    variants.append(('added-authority',lambda r:r['authorities'].append(r['authorities'][0]|{'name':'extra'}),'authority'))
    results=[]
    for name,change,reason in variants:
        folder=SCRATCH/('contract-'+name);folder.mkdir();changed=copy.deepcopy(record);change(changed)
        path=folder/'source-manifest.json';path.write_bytes(enc(changed));source=SourceManifest.load(path,repository_root=ROOT)
        package_path=folder/'package';shutil.copytree(base.path,package_path)
        candidate_record=json.loads((package_path/'manifest.json').read_bytes());candidate_record['source_id']=changed['source_id'];candidate_record['source_manifest']={'path':path.relative_to(ROOT).as_posix(),'sha256':source.sha256};(package_path/'manifest.json').write_bytes(enc(candidate_record));package=CandidatePackage.load(package_path)
        result=oracle._oracle(source,package)
        if result['status']!='fail' or not any(reason in value for value in result['findings']):raise ValueError('Intended source-contract rejection not proved '+name+' '+repr(result['findings']))
        results.append({'name':name,'serialized_source_contract_load':'pass','resealed_candidate_integrity':'pass','source_manifest_sha256':source.sha256,'intended_rejection':result['findings']})
    return results


def import_challenges(base):
    probe=SCRATCH/'unexpected_firstparty.py';probe.write_text('VALUE = 635\n',encoding='utf-8')
    baseline_runtime=json.loads((SOURCE.parent/'execution-runtime.json').read_bytes())
    if any('email/mime/image.py' in r['path'].replace('\\','/') for r in baseline_runtime['files']):raise ValueError('Choose a truly unloaded external challenge')
    results=[]
    for role in ['producer','oracle']:
        for timing in ['before','after']:
            for kind in ['first-party','external']:
                program='''import importlib.util,json,sys
from pathlib import Path
r=Path(sys.argv[1]);sys.path.insert(0,str(r))
import build.tools.prepare_tyerman_whitefield_complete
import build.tools.prove_tyerman_whitefield_complete as proof
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage
from build.tei import tyerman_whitefield_complete as p,tyerman_whitefield_complete_oracle as o
import html5lib
def inject():
 if sys.argv[5]=='external':__import__('email.mime.image')
 else:
  s=importlib.util.spec_from_file_location('_l635_unexpected',sys.argv[6]);m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
if sys.argv[4]=='before':inject()
else:
 original=html5lib.HTMLParser.parse
 def wrapped(self,*a,**k):inject();return original(self,*a,**k)
 html5lib.HTMLParser.parse=wrapped
m=SourceManifest.load(proof.SOURCE,repository_root=r);c=CandidatePackage.load(sys.argv[2])
try:
 p._convert(m) if sys.argv[3]=='producer' else o._oracle(m,c)
except ValueError as e:
 phase=('before-' if sys.argv[4]=='before' else 'after-')+('conversion' if sys.argv[3]=='producer' else 'oracle')
 if 'L635 unexpected or changed executed file at '+phase not in str(e):raise
 print(json.dumps({'status':'intended-runtime-rejection','role':sys.argv[3],'timing':sys.argv[4],'kind':sys.argv[5],'reason':str(e)}))
else:raise RuntimeError('Unexpected import was admitted')'''
                args=[sys.executable,'-I','-B','-c',program,str(ROOT),str(base.path),role,timing,kind,str(probe)]
                run=subprocess.run(args,check=True,capture_output=True,text=True)
                results.append(json.loads(run.stdout))
    for role in ['producer','oracle']:
        try:oracle.closure(role,extra='ocd_kernel.library.identities')
        except ValueError as e:
            if 'Unexpected first-party import closure' not in str(e):raise
            results.append({'role':role,'kind':'fresh-import-first-party','status':'intended-rejection','reason':str(e)})
        else:raise ValueError('Unexpected fresh import admitted')
    return {'probe':pin(probe),'challenges':results}


def prove():
    if SCRATCH.exists() or DEST.exists():raise ValueError('Preserve all existing proof/candidate generations')
    SCRATCH.mkdir(parents=True)
    before={r['path']:r for r in observed()['files']}
    baseline=supported(DEST)
    manifest=SourceManifest.load(SOURCE,repository_root=ROOT);base=CandidatePackage.load(DEST/'package')
    result=oracle._oracle(manifest,base)
    if result['status']!='pass':raise ValueError(result['findings'])
    rows=oracle.check_content(base.member_bytes('content.tei.xml'),json.loads(manifest.authority_path('profile').read_bytes()))
    semantic=semantic_mutants(base,manifest);contracts=contract_mutants(base,manifest);imports=import_challenges(base)
    replays=[]
    for i in [1,2]:
        replay=Path(str(DEST)+f'-fresh-replay-{i}');receipt=supported(replay)
        package=CandidatePackage.load(replay/'package')
        if any(package.member_bytes(name)!=base.member_bytes(name) for name in base.member_names):raise ValueError('Fresh process package member bytes differ')
        replays.append(receipt|{'all_six_members_byte_identical':True})
    after=observed()
    expected=json.loads((SOURCE.parent/'execution-runtime.json').read_bytes())
    if any({r['path']:r for r in expected['files']}.get(r['path'])!=r for r in after['files']):raise ValueError('Proof process execution closure drift')
    receipt={'contract':'ocd-l635-complete-biography-source-proof-v3','status':'pass','scope':oracle.SCOPE,'source_manifest':pin(SOURCE),'candidate':baseline,'actual_source_inverse':rows,'semantic_mutations':semantic,'source_contract_mutations':contracts,'import_mutations':imports,'fresh_process_replays':replays,'actual_execution_runtime':after,'before_loaded_files':list(before.values()),'qualification':'One nonaccepted candidate for the whole authored biography. No human acceptance, rights clearance, publication or print/CVW collation implied. Historical packages and shared Tyerman modules preserved.'}
    path=LOG/'complete-work-source-proof-v4.json';path.write_bytes(enc(receipt));return pin(path)|{'status':'pass','semantic_mutations':len(semantic),'contract_mutations':len(contracts),'import_mutations':len(imports['challenges'])}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prove']);p.parse_args()
    print(json.dumps(prove(),sort_keys=True))
