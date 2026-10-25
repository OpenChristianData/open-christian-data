"""Recover, package, and challenge Findlay's two existing readable members."""
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
from lxml import etree
from build.tei.findlay_retained_prepare import ROOT,LOG,SOURCE_DIR,WORK_ID,MEMBERS,OLD_PACKAGE,canonical,sha,convert,_convert
from build.tei.findlay_retained_oracle import check,_oracle,import_closure,ORACLE_IMPORTS,PRODUCER_IMPORTS
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,reconstruct,validate
CANDIDATES=Path('D:/Library/Open Christian Data/candidate-reviews/findlay-existing-readable-20261003-v3')
def authority(name,path,role):
 raw=(ROOT/path).read_bytes();return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(raw),sha256=sha(raw))
def manifests():
 (ROOT/SOURCE_DIR).mkdir(parents=True,exist_ok=True);paths={};closure=import_closure();producer=import_closure('build.tei.findlay_retained_prepare')
 for member,spec in MEMBERS.items():
  payload=convert(member);source=etree.fromstring((ROOT/spec['path']).read_bytes());body=source.find('ThML.body');account=json.loads(payload['source-accountability.json'])
  profile=SOURCE_DIR/(member+'.profile.json');policy=SOURCE_DIR/(member+'.policy.json');readme=SOURCE_DIR/(member+'.README.source.md')
  (ROOT/SOURCE_DIR/(member+'.bounded-repair-profile.json')).write_bytes(canonical(dict(table_summary_changes=account['summary_changes'],relative_uri_bases=account['relative_uri_bases'],source_uri_acquisition_path=account['source_uri_acquisition_path'],source_uri_acquisition_sha256=account['source_uri_acquisition_sha256'],inverse='Remove exactly declared table@n and per-ref xml:base; every original native node/text/attribute/order equal')))
  (ROOT/readme).write_bytes(payload['README.source.md'])
  (ROOT/profile).write_bytes(canonical(dict(contract='ocd-findlay-existing-readable-profile-v1',work_id=WORK_ID,member_id=member,source=spec,source_body_c14n_sha256=account['source_body_c14n_sha256'],original_native_member_c14n_sha256=account['original_native_member_c14n_sha256'],bounded_changes=account['summary_changes'],body_tags=dict(Counter(n.tag for n in body.iter() if isinstance(n.tag,str))),producer_import_closure_sha256=producer,producer_imports=list(PRODUCER_IMPORTS),oracle_imports=list(ORACLE_IMPORTS),genre='commentary',scope='two existing acquired epistle editions; not complete author or series',limitations=account['limitations'])))
  (ROOT/policy).write_bytes(canonical(dict(contract='ocd-findlay-independent-readable-policy-v1',member_id=member,independent='stdlib raw XML source parser corroborated by lxml versus actual existing native TEI, old independent Findlay validator, full independent ledger reconciliation, actual original-native and source-body inverse',required=['literal entire source head/prolog/CSS/credit visible','all native direct/tail/semantic attrs/order/attachment','all administrative payload/tails ledger and native anchors','full actual source body inverse including all source attributes','bounded original native inverse','P5','feature mutations','two fresh Python six-member equality replays'],patterns=['RP-03','RP-04','RP-06','RP-11','RP-13','RP-14','RP-15'],limitations=account['limitations'])))
  auth=[authority('retained-thml',spec['path'],'primary-source'),authority('member-profile',profile,'complete-source-feature-profile'),authority('member-policy',policy,'independent-validation-policy'),authority('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),authority('package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema'),authority('source-local-attribution-readme',readme,'source-rights-attribution'),authority('permission','sources/commentaries/expositors-bible/ccel-permission.md','source-rights-evidence'),authority('original-source-credit','data/commentaries/expositors-bible/README.md','historical-source-credit'),authority('source-uri-acquisition',account['source_uri_acquisition_path'],'source-uri-context-authority')]
  auth += [authority('original-'+p.name,p,'preexisting-reconstruction-evidence') for p in sorted(OLD_PACKAGE.iterdir() if OLD_PACKAGE.is_absolute() else (ROOT/OLD_PACKAGE).iterdir()) if p.is_file()]
  for a in auth:
   p=Path(a['path'])
   if p.is_absolute():a['path']=p.relative_to(ROOT).as_posix()
  auth += [authority('import-'+str(i),p,'observed-first-party-import-dependency') for i,p in enumerate(sorted(set(ORACLE_IMPORTS+PRODUCER_IMPORTS)))]
  auth += [authority('current-scope-review',LOG/'existing-scope-review.json','existing-candidate-recovery-evidence'),authority('scope-reader',LOG/'existing_scope_review.py','independent-recovery-implementation'),authority('bounded-repair-profile',SOURCE_DIR/(member+'.bounded-repair-profile.json'),'bounded-existing-native-repairs')]
  record=dict(contract='ocd-source-manifest-v1',source_id='ccel-findlay-existing-readable-'+member+'-v1',work_id=WORK_ID,ticket_id='37c-151-existing-findlay-acquired-editions',authorities=auth,converter=dict(id=_convert.converter_id,version=_convert.converter_version,callable='_convert',implementation_path='build/tei/findlay_retained_prepare.py',implementation_sha256=sha((ROOT/'build/tei/findlay_retained_prepare.py').read_bytes())),validator=dict(id=_oracle.oracle_id,version=_oracle.oracle_version,callable='_oracle',implementation_path='build/tei/findlay_retained_oracle.py',implementation_sha256=sha((ROOT/'build/tei/findlay_retained_oracle.py').read_bytes()),import_closure_sha256=closure),package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes())),scope=dict(kind='complete-existing-retained-edition',member_id=member,acquired_work_member_count=2,no_acquisition_or_download=True),source_order=dict(order='existing native member preserving complete retained source DOM'))
  path=SOURCE_DIR/(member+'.source-manifest.json');(ROOT/path).write_bytes(canonical(record));SourceManifest.load(ROOT/path,repository_root=ROOT);paths[member]=path
 return paths
def challenges(member,package):
 ns={'t':'http://www.tei-c.org/ns/1.0'};raw=package.member_bytes('content.tei.xml');scratch=CANDIDATES/member/'challenge';scratch.mkdir(exist_ok=True);results=[]
 for n in package.member_names:(scratch/n).write_bytes(package.member_bytes(n))
 def reject(label,data,account=None):
  (scratch/'content.tei.xml').write_bytes(data);(scratch/'source-accountability.json').write_bytes(account or package.member_bytes('source-accountability.json'))
  try:check(member,scratch)
  except (ValueError,etree.DocumentInvalid) as error:results.append(dict(challenge=label,rejected=True,reason=str(error)[:350],candidate_sha256=sha(data)))
  else:raise ValueError('Findlay mutation admitted '+label)
 cases=[('paragraph-text','.//t:text//t:p','text'),('source-tail','.//t:text//t:ref','tail'),('literal-target','.//t:text//t:ref[@target]','target'),('relative-uri-base','.//t:text//t:ref[@xml:base]','{http://www.w3.org/XML/1998/namespace}base'),('note-label','.//t:text//t:note[@n]','n'),('inline-rend','.//t:text//t:hi[@rend]','rend'),('source-heading','.//t:text//t:head[@xml:id]','text'),('source-admin-digest','.//t:text//t:anchor[@ana]','ana'),('source-head-field','.//t:note[@type="retained-source-head-field"]','text')]
 if member=='findlay-expositoreph':cases += [('table-summary','.//t:text//t:table[@n]','n'),('table-header-role','.//t:text//t:cell[@role="label"]','role')]
 for label,selector,field in cases:
  tree=etree.fromstring(raw);nodes=tree.xpath(selector,namespaces=ns)
  if not nodes:raise ValueError('Findlay required challenge feature absent '+label)
  node=next((n for n in nodes if getattr(n,field,None)),nodes[0]) if field in {'text','tail'} else nodes[0]
  if field in {'text','tail'}:setattr(node,field,(getattr(node,field) or '')+'CHALLENGE')
  else:node.set(field,(node.get(field) or '')+'CHALLENGE')
  reject(label,etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 tree=etree.fromstring(raw);note=tree.xpath('.//t:text//t:note',namespaces=ns)[0];target=next(n for n in tree.xpath('.//t:text//t:p',namespaces=ns) if n is not note.getparent() and note not in n.iterancestors());note.getparent().remove(note);target.append(note);reject('note-attachment',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 tree=etree.fromstring(raw);outside=etree.SubElement(tree.find('{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body'),'{http://www.tei-c.org/ns/1.0}p');outside.text='CHALLENGE';reject('outer-body-added-payload',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 account=json.loads(package.member_bytes('source-accountability.json'));account['body_auxiliaries'][0]['text']+='CHALLENGE';reject('administrative-payload',raw,canonical(account))
 account=json.loads(package.member_bytes('source-accountability.json'));next(r for r in account['crosswalk'] if r['source_tag']=='p')['source_attributes']['class']='CHALLENGE';reject('original-source-attribute-ledger',raw,canonical(account))
 return results
def prepare():
 paths=manifests();results=[];negative={}
 for module,key in [('build.tei.findlay_retained_oracle','rejected'),('build.tei.findlay_retained_prepare','producer_rejected')]:
  try:import_closure(module,extra_import='ocd_kernel.reconstruction.verifier')
  except ValueError as error:negative[key]=True;negative[key+'_reason']=str(error)
  else:raise ValueError('Findlay unexpected import admitted')
 for member,path in paths.items():
  manifest=SourceManifest.load(ROOT/path,repository_root=ROOT);destination=CANDIDATES/member/'package';destination.parent.mkdir(parents=True,exist_ok=True);package=CandidatePackage.load(destination) if destination.exists() else reconstruct(manifest,destination,_convert)
  report=validate(manifest,package,_oracle);direct=check(member,package.path);direct['mutations']=challenges(member,package);replays=[]
  for number in (1,2):
   replay_dir=CANDIDATES/member/('clean-replay-'+str(number));subprocess.run([sys.executable,'-B','-m','build.tei.findlay_retained_prepare',str(replay_dir),'--source-manifest',str(ROOT/path)],cwd=ROOT,check=True,capture_output=True)
   replay=CandidatePackage.load(replay_dir)
   if replay.sha256!=package.sha256 or any(replay.member_bytes(n)!=package.member_bytes(n) for n in package.member_names):raise ValueError('Findlay fresh six-member replay differs')
   replays.append(dict(process='fresh-python',package_sha256=replay.sha256,all_members_byte_equal=True))
  result=dict(member_id=member,package_path=destination.as_posix(),package_sha256=package.sha256,source_manifest_path=path.as_posix(),source_manifest_sha256=manifest.sha256,oracle_report=dict(report.attestation),oracle_report_sha256=report.sha256,direct_source_review=direct,reproducibility=dict(status='pass',fresh_python_process=True,exact_six_member_bytes_equal=True,replays=replays),closure_negative=negative)
  (ROOT/LOG/(member+'-current-review-v3.json')).write_bytes(canonical(result));results.append(result)
 (ROOT/LOG/'candidate-completion-receipt-v3.json').write_bytes(canonical(dict(status='pass',work_id=WORK_ID,included_volumes=2,acquired_volumes=2,members=results)))
 return [dict(member_id=r['member_id'],package_sha256=r['package_sha256']) for r in results]
if __name__=='__main__':print(json.dumps(prepare(),sort_keys=True))
