"""Package and independently challenge Smith's three existing downloaded volumes."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

from lxml import etree
from build.tei.smith_retained_native_prepare import ROOT, LOG, SOURCE_DIR, WORK_ID, SPECS, MEMBERS, OLD_PACKAGE, canonical, sha, convert, _convert
from build.tei.smith_retained_native_oracle import check, _oracle, import_closure, ORACLE_IMPORTS, PRODUCER_IMPORTS
from ocd_kernel.reconstruction import SourceManifest, CandidatePackage, reconstruct, validate

CANDIDATES=Path('D:/Library/Open Christian Data/candidate-reviews/smith-existing-readable-20261003-v2')

def authority(name,path,role):
 raw=(ROOT/path).read_bytes()
 return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(raw),sha256=sha(raw))

def manifests():
 (ROOT/SOURCE_DIR).mkdir(parents=True,exist_ok=True)
 closure=import_closure();producer_closure=import_closure('build.tei.smith_retained_native_prepare')
 paths={}
 for member,spec in SPECS.items():
  payload=convert(member)
  antecedent=Path('D:/Library/Open Christian Data/candidate-reviews/smith-native-20261003-v3')/member
  if any((antecedent/name).read_bytes()!=raw for name,raw in payload.items()):raise ValueError('Preserved Smith v3 payload differs')
  source=etree.fromstring((ROOT/spec['path']).read_bytes());body=source.find('ThML.body')
  profile=SOURCE_DIR/(member+'.profile.json');policy=SOURCE_DIR/(member+'.policy.json');readme=SOURCE_DIR/(member+'.README.source.md')
  (ROOT/readme).write_bytes(payload['README.source.md'])
  (ROOT/profile).write_bytes(canonical(dict(contract='ocd-smith-complete-retained-volume-profile-v1',member_id=member,work_id=WORK_ID,source=spec,
   source_body_c14n_sha256=sha(etree.tostring(body,method='c14n',with_comments=True)),body_tags=dict(Counter(n.tag for n in body.iter() if isinstance(n.tag,str))),
   front=MEMBERS[member][1],back=MEMBERS[member][2],acquired_work_volumes=3,producer_import_closure_sha256=producer_closure,
   producer_imports=list(PRODUCER_IMPORTS),oracle_imports=list(ORACLE_IMPORTS),genre='commentary',scope='complete retained acquired volume; not complete author or series',
   graphics='Literal map/Arabic-word pointers and attachment preserved; pixels not retained; no inferred Arabic text')))
  (ROOT/policy).write_bytes(canonical(dict(contract='ocd-smith-independent-readable-policy-v1',member_id=member,
   independent='stdlib ElementTree source reader versus actual TEI; lxml source parser fields separately corroborated; no emitter import or producer account correctness assumption',
   required=['all actual native fields/parent/order/attachments','all administrative comment fields and raw-derived joins','inverse entire source body C14N from actual TEI','all header/prolog rights visible','P5','negative challenges','two fresh process byte-identical replays'],
   patterns=['RP-03','RP-04','RP-06','RP-11','RP-13','RP-14','RP-15'],visual='not performed; graphics pixels absent')))
  authorities=[authority('retained-thml',spec['path'],'primary-source'),authority('volume-profile',profile,'complete-source-feature-profile'),authority('volume-policy',policy,'independent-validation-policy'),
   authority('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),authority('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema'),
   authority('source-local-attribution-readme',readme,'source-rights-attribution'),authority('ccel-permission','sources/commentaries/expositors-bible/ccel-permission.md','source-rights-evidence'),
   authority('original-source-credit','data/commentaries/expositors-bible/README.md','historical-source-credit'),authority('scope-recovery',LOG/'legacy-source-scope-review.json','existing-candidate-recovery-evidence')]
  authorities += [authority('import-'+str(i),p,'observed-first-party-import-dependency') for i,p in enumerate(sorted(set(ORACLE_IMPORTS+PRODUCER_IMPORTS)))]
  if member!='smith-ga-expositorisa1':authorities += [authority('original-tei',OLD_PACKAGE/'content.tei.xml','preexisting-reconstruction-input'),authority('original-account',OLD_PACKAGE/'source-accountability.json','historical-source-feature-proof')]
  record=dict(contract='ocd-source-manifest-v1',source_id='ccel-smith-retained-native-'+member+'-v1',work_id=WORK_ID,ticket_id='37c-153-existing-smith-acquired-volumes',authorities=authorities,
   converter=dict(id=_convert.converter_id,version=_convert.converter_version,callable='_convert',implementation_path='build/tei/smith_retained_native_prepare.py',implementation_sha256=sha((ROOT/'build/tei/smith_retained_native_prepare.py').read_bytes())),
   validator=dict(id=_oracle.oracle_id,version=_oracle.oracle_version,callable='_oracle',implementation_path='build/tei/smith_retained_native_oracle.py',implementation_sha256=sha((ROOT/'build/tei/smith_retained_native_oracle.py').read_bytes()),import_closure_sha256=closure),
   package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes())),
   scope=dict(kind='complete-existing-retained-volume',member_id=member,acquired_work_member_count=3,no_acquisition_or_download=True),source_order=dict(order='complete original source DOM and comment/tail attachment'))
  path=SOURCE_DIR/(member+'.source-manifest.json');(ROOT/path).write_bytes(canonical(record));SourceManifest.load(ROOT/path,repository_root=ROOT);paths[member]=path
 return paths

def challenges(member,package):
 ns={'t':'http://www.tei-c.org/ns/1.0'};raw=package.member_bytes('content.tei.xml');results=[]
 cases=[('paragraph-text','.//t:p','text'),('source-tail','.//t:ref','tail'),('heading-role','.//t:p[contains(@rend,"source-h")]','rend'),('table-span','.//t:cell[@cols]','cols'),('scripture-literal','.//t:ref[@target][not(starts-with(@target,"#"))]','target'),('index-directive','.//t:milestone[@unit="insertIndex"]','n'),('note-label','.//t:note[@n]','n')]
 if member!='smith-ga-expositorprophets1':cases.append(('literal-image-pointer','.//t:graphic','url'))
 scratch=CANDIDATES/member/'challenge';scratch.mkdir(exist_ok=True)
 for name in package.member_names:
  if name!='candidate-manifest.json':(scratch/name).write_bytes(package.member_bytes(name))
 def reject(label,data,account=None):
  (scratch/'content.tei.xml').write_bytes(data);(scratch/'source-accountability.json').write_bytes(account or package.member_bytes('source-accountability.json'))
  try:check(member,scratch,native=False)
  except (ValueError,etree.DocumentInvalid) as error:results.append(dict(challenge=label,rejected=True,reason=str(error)[:350],candidate_sha256=sha(data)))
  else:raise ValueError('Smith oracle admitted mutation '+label)
 for label,selector,field in cases:
  tree=etree.fromstring(raw);nodes=tree.xpath('./t:text'+selector[1:],namespaces=ns)
  if not nodes:raise ValueError('Required source challenge feature absent '+label)
  node=next((n for n in nodes if getattr(n,field,None)),nodes[0]) if field in {'text','tail'} else nodes[0]
  if field in {'text','tail'}:setattr(node,field,(getattr(node,field) or '')+'CHALLENGE')
  else:node.set(field,str(int(node.get(field))+1) if field=='cols' else (node.get(field) or '')+'CHALLENGE')
  reject(label,etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 tree=etree.fromstring(raw);note=tree.xpath('./t:text//t:note',namespaces=ns)[0];target=next(n for n in tree.xpath('./t:text//t:p',namespaces=ns) if n is not note.getparent() and note not in n.iterancestors());note.getparent().remove(note);target.append(note)
 reject('complete-note-attachment',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 account=json.loads(package.member_bytes('source-accountability.json'));next(r for r in account['features'] if r['source_tag']=='#comment')['source_text']+='CHALLENGE';reject('administrative-comment',raw,canonical(account))
 if member!='smith-ga-expositorprophets1':
  tree=etree.fromstring(raw);figure=tree.xpath('./t:text//t:figure',namespaces=ns)[0];target=next(n for n in tree.xpath('./t:text//t:p',namespaces=ns) if n is not figure.getparent() and figure not in n.iterancestors());figure.getparent().remove(figure);target.append(figure);reject('graphic-attachment',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 return results

def prepare():
 paths=manifests();results=[]
 try:import_closure(extra_import='ocd_kernel.reconstruction.verifier')
 except ValueError as error:negative=dict(rejected=True,reason=str(error))
 else:raise ValueError('Unexpected first-party import admitted')
 try:import_closure('build.tei.smith_retained_native_prepare',extra_import='ocd_kernel.reconstruction.verifier')
 except ValueError as error:negative.update(producer_rejected=True,producer_reason=str(error))
 else:raise ValueError('Unexpected producer first-party import admitted')
 for member,path in paths.items():
  manifest=SourceManifest.load(ROOT/path,repository_root=ROOT);destination=CANDIDATES/member/'package';destination.parent.mkdir(parents=True,exist_ok=True)
  package=CandidatePackage.load(destination) if destination.exists() else reconstruct(manifest,destination,_convert)
  report=validate(manifest,package,_oracle);direct=check(member,package.path);direct['mutations']=challenges(member,package)
  replays=[]
  for number in (1,2):
   replay_dir=CANDIDATES/member/('clean-replay-'+str(number))
   if not replay_dir.exists():subprocess.run([sys.executable,'-B','-m','build.tei.smith_retained_native_prepare',str(replay_dir),'--source-manifest',str(ROOT/path)],cwd=ROOT,check=True,capture_output=True)
   replay=CandidatePackage.load(replay_dir)
   if replay.sha256!=package.sha256 or any(replay.member_bytes(n)!=package.member_bytes(n) for n in package.member_names):raise ValueError('Smith fresh process replay differs')
   replays.append(dict(process='fresh-python',package_sha256=replay.sha256,all_members_byte_equal=True))
  result=dict(member_id=member,package_path=destination.as_posix(),package_sha256=package.sha256,source_manifest_path=path.as_posix(),source_manifest_sha256=manifest.sha256,oracle_report=dict(report.attestation),oracle_report_sha256=report.sha256,direct_source_review=direct,reproducibility=dict(status='pass',fresh_python_process=True,exact_six_member_bytes_equal=True,replays=replays),closure_negative=negative)
  (ROOT/LOG/(member+'-current-review.json')).write_bytes(canonical(result));results.append(result)
 (ROOT/LOG/'candidate-completion-receipt.json').write_bytes(canonical(dict(status='pass',work_id=WORK_ID,included_volumes=3,acquired_volumes=3,members=results)))
 return [dict(member_id=r['member_id'],package_sha256=r['package_sha256']) for r in results]

if __name__=='__main__':print(json.dumps(prepare(),sort_keys=True))
