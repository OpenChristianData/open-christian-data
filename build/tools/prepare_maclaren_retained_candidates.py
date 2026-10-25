"""Package and independently challenge the four existing acquired Maclaren units."""
from pathlib import Path
from collections import Counter
import json,subprocess,sys
from lxml import etree
from build.tei.maclaren_retained_native_prepare import ROOT,LOG,SOURCE_DIR,WORK_ID,SPECS,MEMBERS,OLD_PACKAGE,canonical,sha,convert,_convert
from build.tei.maclaren_retained_native_oracle import check,_oracle,import_closure,ORACLE_IMPORTS,PRODUCER_IMPORTS,_p5_schema
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,reconstruct,validate
CANDIDATES=Path('D:/Library/Open Christian Data/candidate-reviews/maclaren-existing-readable-20261003-v2')
EXPECTED_MUTATIONS={m:20 if m=='maclaren-expositorcolphm' else 19 if m=='maclaren-expositorpsalms2' else 15 for m in MEMBERS}
def authority(name,path,role):
 raw=(ROOT/path).read_bytes();return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(raw),sha256=sha(raw))
def manifests():
 (ROOT/SOURCE_DIR).mkdir(parents=True,exist_ok=True);paths={};closure=import_closure();producer=import_closure('build.tei.maclaren_retained_native_prepare')
 for member,spec in SPECS.items():
  payload=convert(member);source=etree.fromstring((ROOT/spec['path']).read_bytes());body=source.find('ThML.body');account=json.loads(payload['source-accountability.json'])
  profile=SOURCE_DIR/(member+'.profile.json');policy=SOURCE_DIR/(member+'.policy.json');readme=SOURCE_DIR/(member+'.README.source.md');(ROOT/readme).write_bytes(payload['README.source.md'])
  (ROOT/profile).write_bytes(canonical(dict(contract='ocd-maclaren-existing-readable-profile-v1',member_id=member,work_id=WORK_ID,source=spec,source_body_c14n_sha256=sha(etree.tostring(body,method='c14n',with_comments=True)),body_tags=dict(Counter(n.tag for n in body.iter() if isinstance(n.tag,str))),front=MEMBERS[member][1],back=MEMBERS[member][2],acquired_work_units=4,producer_import_closure_sha256=producer,producer_imports=list(PRODUCER_IMPORTS),oracle_imports=list(ORACLE_IMPORTS),genre='commentary',scope='four registered acquired units: Psalms I1-38 /II39-89 /III90-150 and combined Colossians/Philemon volume; not complete author or series',source_uri_acquisition_path=account['source_uri_acquisition_path'],source_uri_acquisition_sha256=account['source_uri_acquisition_sha256'],navigation='known source next/prev IDs map locally; absent toc remains exact typed source annotation',verse='literal source span/br versus verse/l preserved; no invented regrouping',graphics='No img elements in these four sources')))
  (ROOT/policy).write_bytes(canonical(dict(contract='ocd-maclaren-independent-native-policy-v1',member_id=member,independence='Prior exposure to old ledger and native mapping declared. Independent stdlib raw tree versus all actual native fields, secondary lxml raw parser corroboration, source-derived full attributes and inverse entire source body including admin/tbody joins; no producer/emitter import.',required=['complete source head/prolog/copyright/CSS visible','whole actual root/text/front/body/back envelope and all payloads','native paragraphs/headings/verse/lines/tables/th/notes/links and same-text attachment','next/prev with explicit source toc gaps','relative URI context from exact acquisition','actual body-backed full inverse','P5','schema-valid semantic mutations','two fresh six-member equality replays'],patterns=['RP-03','RP-04','RP-06','RP-11','RP-13','RP-14','RP-15'],visual='not performed; technical source comparison, no print or typography equivalence claim')))
  auth=[authority('retained-thml',spec['path'],'primary-source'),authority('profile',profile,'complete-source-feature-profile'),authority('policy',policy,'independent-validation-policy'),authority('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),authority('package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema'),authority('source-local-attribution-readme',readme,'source-rights-attribution'),authority('ccel-permission','sources/commentaries/expositors-bible/ccel-permission.md','source-rights-evidence'),authority('old-credit','data/commentaries/expositors-bible/README.md','historical-source-credit'),authority('source-uri-acquisition',account['source_uri_acquisition_path'],'source-uri-context-authority'),authority('original-reader',LOG/'source_inventory.py','independent-recovery-implementation'),authority('original-review',LOG/'source-inventory.json','existing-candidate-recovery-evidence')]
  auth += [authority('old-'+p.name,p.relative_to(ROOT),'preexisting-reconstruction-evidence') for p in sorted((ROOT/OLD_PACKAGE).iterdir()) if p.is_file()]
  auth += [authority('import-'+str(i),p,'observed-first-party-import-dependency') for i,p in enumerate(sorted(set(ORACLE_IMPORTS+PRODUCER_IMPORTS)))]
  record=dict(contract='ocd-source-manifest-v1',source_id='ccel-maclaren-retained-native-'+member+'-v1',work_id=WORK_ID,ticket_id='37c-147-existing-maclaren-four-acquired-units',authorities=auth,converter=dict(id=_convert.converter_id,version=_convert.converter_version,callable='_convert',implementation_path='build/tei/maclaren_retained_native_prepare.py',implementation_sha256=sha((ROOT/'build/tei/maclaren_retained_native_prepare.py').read_bytes())),validator=dict(id=_oracle.oracle_id,version=_oracle.oracle_version,callable='_oracle',implementation_path='build/tei/maclaren_retained_native_oracle.py',implementation_sha256=sha((ROOT/'build/tei/maclaren_retained_native_oracle.py').read_bytes()),import_closure_sha256=closure),package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes())),scope=dict(kind='complete-existing-retained-volume',member_id=member,acquired_work_member_count=4,no_acquisition_or_download=True),source_order=dict(order='entire retained raw source DOM, all original source regions and attachments'))
  path=SOURCE_DIR/(member+'.source-manifest.json');(ROOT/path).write_bytes(canonical(record));SourceManifest.load(ROOT/path,repository_root=ROOT);paths[member]=path
 return paths
def challenges(member,package):
 ns={'t':'http://www.tei-c.org/ns/1.0'};raw=package.member_bytes('content.tei.xml');scratch=CANDIDATES/member/'challenge';scratch.mkdir(exist_ok=True);results=[]
 for name in package.member_names:(scratch/name).write_bytes(package.member_bytes(name))
 def reject(label,data,account=None):
  _p5_schema().assertValid(etree.fromstring(data))
  (scratch/'content.tei.xml').write_bytes(data);(scratch/'source-accountability.json').write_bytes(account or package.member_bytes('source-accountability.json'))
  try:check(member,scratch)
  except ValueError as error:results.append(dict(challenge=label,schema_valid=True,rejected=True,reason=str(error)[:350],candidate_sha256=sha(data)))
  else:raise ValueError('Maclaren valid-source mutation admitted '+label)
 cases=[('paragraph-text','.//t:text//t:p','text'),('source-tail','.//t:text//t:ref','tail'),('heading-role','.//t:text//t:p[@rend]','rend'),('literal-target','.//t:text//t:ref[@target]','target'),('relative-uri-base','.//t:text//t:ref[@xml:base]','{http://www.w3.org/XML/1998/namespace}base'),('index-directive','.//t:text//t:milestone[@unit="insertIndex"]','n'),('verse-line','.//t:text//t:l','text'),('page-marker','.//t:text//t:pb[@n]','n'),('native-navigation','.//t:text//t:div[@next]','next'),('unresolved-toc','.//t:text//t:div[@ana]','ana'),('source-head-field','.//t:note[@type="retained-source-head-field"]','text')]
 if member in {'maclaren-expositorpsalms2','maclaren-expositorcolphm'}:cases += [('table-summary','.//t:text//t:table[@n]','n'),('table-span','.//t:text//t:cell[@cols]','cols'),('note-label','.//t:text//t:note[@n]','n')]
 if member=='maclaren-expositorcolphm':cases.append(('table-header-role','.//t:text//t:cell[@role="label"]','role'))
 for label,selector,field in cases:
  tree=etree.fromstring(raw);nodes=tree.xpath(selector,namespaces=ns)
  if not nodes:raise ValueError('Required Maclaren source feature absent '+label)
  node=next((n for n in nodes if getattr(n,field,None)),nodes[0]) if field in {'text','tail'} else nodes[0]
  if field in {'text','tail'}:setattr(node,field,(getattr(node,field) or '')+'CHALLENGE')
  elif field=='cols':node.set(field,str(int(node.get(field))+1))
  elif field=='role':node.set(field,'data')
  else:node.set(field,(node.get(field) or '')+'CHALLENGE')
  reject(label,etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 tree=etree.fromstring(raw);extra=etree.SubElement(tree.find('t:text/t:body',namespaces=ns),'{http://www.tei-c.org/ns/1.0}div');etree.SubElement(extra,'{http://www.tei-c.org/ns/1.0}p').text='CHALLENGE';reject('outer-body-added-payload',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 tree=etree.fromstring(raw);groups=tree.xpath('.//t:text//t:lg',namespaces=ns);origin=next(n for n in groups if len(n.findall('t:l',namespaces=ns))>1);line=origin.find('t:l',namespaces=ns);target=next(n for n in groups if n is not origin);origin.remove(line);target.append(line);reject('same-text-verse-wrong-attachment',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 account=json.loads(package.member_bytes('source-accountability.json'));next(r for r in account['features'] if r['source_tag']=='#comment')['source_text']+='CHALLENGE';reject('administrative-comment-payload',raw,canonical(account))
 account=json.loads(package.member_bytes('source-accountability.json'));next(r for r in account['features'] if r['source_tag']=='p')['source_attributes']['class']='CHALLENGE';reject('whole-source-attribute-ledger',raw,canonical(account))
 if member in {'maclaren-expositorpsalms2','maclaren-expositorcolphm'}:
  tree=etree.fromstring(raw);note=tree.xpath('.//t:text//t:note',namespaces=ns)[0];parent=next(n for n in tree.xpath('.//t:text//t:p',namespaces=ns) if n is not note.getparent() and note not in n.iterancestors());note.getparent().remove(note);parent.append(note);reject('same-text-note-wrong-attachment',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 if len(results)!=EXPECTED_MUTATIONS[member]:raise ValueError('Maclaren challenge finite denominator differs '+str(len(results)))
 return results
def prepare():
 paths=manifests();results=[];negative={}
 for module,key in [('build.tei.maclaren_retained_native_oracle','rejected'),('build.tei.maclaren_retained_native_prepare','producer_rejected')]:
  try:import_closure(module,extra_import='ocd_kernel.reconstruction.verifier')
  except ValueError as error:negative[key]=True;negative[key+'_reason']=str(error)
  else:raise ValueError('Maclaren unexpected fresh first-party import admitted')
 for member,path in paths.items():
  manifest=SourceManifest.load(ROOT/path,repository_root=ROOT);destination=CANDIDATES/member/'package';destination.parent.mkdir(parents=True,exist_ok=True);package=CandidatePackage.load(destination) if destination.exists() else reconstruct(manifest,destination,_convert)
  report=validate(manifest,package,_oracle);direct=check(member,package.path);direct['mutations']=challenges(member,package);replays=[]
  for number in (1,2):
   target=CANDIDATES/member/('clean-replay-'+str(number))
   if target.exists():raise FileExistsError('Preserve existing Maclaren fresh replay')
   subprocess.run([sys.executable,'-B','-m','build.tei.maclaren_retained_native_prepare',str(target),'--source-manifest',str(ROOT/path)],cwd=ROOT,check=True,capture_output=True);replay=CandidatePackage.load(target)
   if replay.sha256!=package.sha256 or any(replay.member_bytes(n)!=package.member_bytes(n) for n in package.member_names):raise ValueError('Maclaren fresh-process six-member replay differs')
   replays.append(dict(process='fresh-python',package_sha256=replay.sha256,all_members_byte_equal=True))
  result=dict(member_id=member,package_path=destination.as_posix(),package_sha256=package.sha256,source_manifest_path=path.as_posix(),source_manifest_sha256=manifest.sha256,oracle_report=dict(report.attestation),oracle_report_sha256=report.sha256,direct_source_review=direct,reproducibility=dict(status='pass',fresh_python_process=True,exact_six_member_bytes_equal=True,replays=replays),closure_negative=negative)
  (ROOT/LOG/(member+'-current-review-v2.json')).write_bytes(canonical(result));results.append(result)
 (ROOT/LOG/'candidate-completion-receipt-v2.json').write_bytes(canonical(dict(status='pass',work_id=WORK_ID,included_volumes=4,acquired_volumes=4,members=results)))
 return [dict(member_id=r['member_id'],package_sha256=r['package_sha256']) for r in results]
if __name__=='__main__':print(json.dumps(prepare(),sort_keys=True))
