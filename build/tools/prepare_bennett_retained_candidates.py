"""Package and independently challenge Bennett's two existing downloaded volumes."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

from lxml import etree
from build.tei.bennett_retained_native_prepare import ROOT, LOG, SOURCE_DIR, WORK_ID, SPECS, MEMBERS, OLD_PACKAGE, canonical, sha, convert, _convert
from build.tei.bennett_retained_native_oracle import check, _oracle, import_closure, ORACLE_IMPORTS, PRODUCER_IMPORTS
from ocd_kernel.reconstruction import SourceManifest, CandidatePackage, reconstruct, validate

CANDIDATES=Path('D:/Library/Open Christian Data/candidate-reviews/bennett-existing-readable-20261003-v1')

def authority(name,path,role):
 raw=(ROOT/path).read_bytes()
 return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(raw),sha256=sha(raw))

def manifests():
 (ROOT/SOURCE_DIR).mkdir(parents=True,exist_ok=True)
 closure=import_closure();producer_closure=import_closure('build.tei.bennett_retained_native_prepare')
 paths={}
 for member,spec in SPECS.items():
  payload=convert(member)
  source=etree.fromstring((ROOT/spec['path']).read_bytes());body=source.find('ThML.body')
  profile=SOURCE_DIR/(member+'.profile.json');policy=SOURCE_DIR/(member+'.policy.json');readme=SOURCE_DIR/(member+'.README.source.md')
  (ROOT/readme).write_bytes(payload['README.source.md'])
  (ROOT/profile).write_bytes(canonical(dict(contract='ocd-bennett-complete-retained-volume-profile-v1',member_id=member,work_id=WORK_ID,source=spec,
   source_body_c14n_sha256=sha(etree.tostring(body,method='c14n',with_comments=True)),body_tags=dict(Counter(n.tag for n in body.iter() if isinstance(n.tag,str))),
   front=MEMBERS[member][1],back=MEMBERS[member][2],acquired_work_volumes=2,producer_import_closure_sha256=producer_closure,
   producer_imports=list(PRODUCER_IMPORTS),oracle_imports=list(ORACLE_IMPORTS),genre='commentary',scope='complete retained acquired volume; not complete author or series',
   graphics='Neither source has any image elements',adaptations='Exact empty column-group native milestone; literal Hebrew index division; separate language namespace semantics and source-attribute annotations; exact comments/tbody joins; per-query primary URL bases; raw readings with unconfirmed historical alternatives')))
  (ROOT/policy).write_bytes(canonical(dict(contract='ocd-bennett-independent-readable-policy-v1',member_id=member,
   independent='stdlib ElementTree source reader versus actual TEI; lxml source parser fields separately corroborated; no emitter import or producer account correctness assumption',
   required=['all actual native fields/parent/order/attachments','all administrative comment fields and raw-derived joins','inverse entire source body C14N from actual TEI','all header/prolog rights visible','P5','negative challenges','two fresh process byte-identical replays'],
   patterns=['RP-03','RP-04','RP-06','RP-11','RP-13','RP-14','RP-15'],visual='not performed; graphics pixels absent')))
  authorities=[authority('retained-thml',spec['path'],'primary-source'),authority('volume-profile',profile,'complete-source-feature-profile'),authority('volume-policy',policy,'independent-validation-policy'),
   authority('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),authority('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema'),
   authority('source-local-attribution-readme',readme,'source-rights-attribution'),authority('ccel-permission','sources/commentaries/expositors-bible/ccel-permission.md','source-rights-evidence'),
   authority('original-source-credit','data/commentaries/expositors-bible/README.md','historical-source-credit'),authority('scope-recovery',LOG/'retained-scope-reconciliation.json','existing-candidate-recovery-evidence')]
  acquisition=Path('library/works')/WORK_ID/'forms'/spec['form']/'editions'/spec['edition']/'acquisitions'/(spec['acquisition']+'.json')
  authorities += [authority('primary-acquired-url-context',acquisition,'primary-source-url-context')]
  authorities += [authority('frozen-emitter-ancestor','build/tei/ccel_retained_native_emitter.py','reviewed-emitter-ancestor')]
  authorities += [authority('import-'+str(i),p,'observed-first-party-import-dependency') for i,p in enumerate(sorted(set(ORACLE_IMPORTS+PRODUCER_IMPORTS)))]
  authorities += [authority('original-tei',OLD_PACKAGE/'content.tei.xml','preexisting-reconstruction-input'),authority('original-account',OLD_PACKAGE/'source-accountability.json','historical-source-feature-proof')]
  authorities += [authority('replay-'+name,OLD_PACKAGE/name,'qualified-current-aggregate-replay-lineage') for name in ['README.source.md','manifest.json','provenance.json','unresolved.jsonl']]
  authorities += [authority('historical-profile','sources/commentaries/expositors-bible/lib036.reconstruction-profile.json','historical-unconfirmed-correction-alternatives'),authority('replay-receipt',LOG/'qualified-current-lib036-replay-receipt.json','qualified-current-converter-replay-evidence'),authority('replay-source-manifest',SOURCE_DIR/'qualified-lib036-replay.source-manifest.json','qualified-current-converter-only-execution-admission')]
  record=dict(contract='ocd-source-manifest-v1',source_id='ccel-bennett-retained-native-'+member+'-v1',work_id=WORK_ID,ticket_id='37c-165-existing-bennett-acquired-works',authorities=authorities,
   converter=dict(id=_convert.converter_id,version=_convert.converter_version,callable='_convert',implementation_path='build/tei/bennett_retained_native_prepare.py',implementation_sha256=sha((ROOT/'build/tei/bennett_retained_native_prepare.py').read_bytes())),
   validator=dict(id=_oracle.oracle_id,version=_oracle.oracle_version,callable='_oracle',implementation_path='build/tei/bennett_retained_native_oracle.py',implementation_sha256=sha((ROOT/'build/tei/bennett_retained_native_oracle.py').read_bytes()),import_closure_sha256=closure),
   package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes())),
   scope=dict(kind='complete-existing-retained-volume',member_id=member,acquired_work_member_count=2,no_acquisition_or_download=True),source_order=dict(order='complete original source DOM and comment/tail attachment'))
  path=SOURCE_DIR/(member+'.source-manifest.json');(ROOT/path).write_bytes(canonical(record));SourceManifest.load(ROOT/path,repository_root=ROOT);paths[member]=path
 return paths

def challenges(member,package):
 ns={'t':'http://www.tei-c.org/ns/1.0'};xml='{http://www.w3.org/XML/1998/namespace}';raw=package.member_bytes('content.tei.xml');results=[]
 scratch=CANDIDATES/member/'challenge';scratch.mkdir(exist_ok=True)
 for name in package.member_names:
  if name!='manifest.json':(scratch/name).write_bytes(package.member_bytes(name))
 schema=etree.XMLSchema(etree.parse(str(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd')))
 def reject(label,data=None,account=None,other=None):
  for name in package.member_names:
   if name!='manifest.json':(scratch/name).write_bytes(package.member_bytes(name))
  (scratch/'content.tei.xml').write_bytes(data or raw)
  if account is not None:(scratch/'source-accountability.json').write_bytes(canonical(account))
  for name,value in (other or {}).items():(scratch/name).write_bytes(value)
  schema.assertValid(etree.fromstring(data or raw))
  try:check(member,scratch,native=False)
  except ValueError as error:results.append(dict(challenge=label,rejected=True,p5_valid=True,reason=str(error)[:350],candidate_sha256=sha(data or raw)))
  else:raise ValueError('Bennett oracle admitted mutation '+label)
 cases=[('paragraph-text','.//t:p','text'),('source-tail','.//t:ref','tail'),('heading-level','.//t:p[contains(@rend,"source-h")]','rend'),('cell-span','.//t:cell[@cols]','cols'),('scripture-target','.//t:ref[@target][not(starts-with(@target,"#"))]','target'),('actual-index-directive','.//t:milestone[@unit="insertIndex"]','n'),('note-label','.//t:note[@n]','n'),('table-summary','.//t:table[@n]','n'),('original-attribute-annotation','.//*[@ana]','ana'),('relative-query-base','.//t:ref[@xml:base]',xml+'base')]
 for label,selector,field in cases:
  tree=etree.fromstring(raw);nodes=tree.xpath('./t:text'+selector[1:],namespaces=ns)
  if not nodes:raise ValueError('Required source mutation feature missing '+label)
  node=next((n for n in nodes if getattr(n,field,None)),nodes[0]) if field in {'text','tail'} else nodes[0]
  if field in {'text','tail'}:setattr(node,field,(getattr(node,field) or '')+'CHALLENGE')
  else:node.set(field,str(int(node.get(field))+1) if field=='cols' else 'urn:challenge' if field=='ana' else 'https://example.invalid/source' if field==xml+'base' else (node.get(field) or '')+'CHALLENGE')
  reject(label,etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 tree=etree.fromstring(raw);note=tree.xpath('./t:text//t:note',namespaces=ns)[0];target=next(n for n in tree.xpath('./t:text//t:p',namespaces=ns) if n is not note.getparent() and note not in n.iterancestors());note.getparent().remove(note);target.append(note);reject('note-ownership',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 tree=etree.fromstring(raw);table=tree.xpath('./t:text//t:table',namespaces=ns)[0];rows=table.findall('{http://www.tei-c.org/ns/1.0}row');table.remove(rows[1]);table.insert(list(table).index(rows[0]),rows[1]);reject('table-row-source-order',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 for tag,field,label in [('#comment','source_text','administrative-comment'),('tbody','source_tail','tbody-wrapper-tail')]:
  account=json.loads(package.member_bytes('source-accountability.json'));next(r for r in account['features'] if r['source_tag']==tag)[field]='CHALLENGE';reject(label,account=account)
 tree=etree.fromstring(raw);stand=etree.SubElement(tree,'{http://www.tei-c.org/ns/1.0}standOff');etree.SubElement(stand,'{http://www.tei-c.org/ns/1.0}list').append(etree.Element('{http://www.tei-c.org/ns/1.0}item'));stand[0][0].text='Additional outer payload';reject('outer-root-payload',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 tree=etree.fromstring(raw);tree.xpath('./t:teiHeader/t:fileDesc/t:titleStmt/t:title',namespaces=ns)[0].text+='CHALLENGE';reject('primary-header-title',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 account=json.loads(package.member_bytes('source-accountability.json'));account['source_document_prefix']+='CHALLENGE';reject('literal-source-prolog',account=account)
 provenance=json.loads(package.member_bytes('provenance.json'));provenance['composite_binding']['primary_acquisition']['url']='https://example.invalid/source';reject('composite-acquisition-provenance',other={'provenance.json':canonical(provenance)})
 reject('unresolved-gate-qualification',other={'unresolved.jsonl':b'{}\n'})
 reject('visible-source-credit',other={'README.source.md':b'# Missing source credit\n'})
 if member.endswith('jer2'):
  account=json.loads(package.member_bytes('source-accountability.json'));account['historical_correction_alternatives'][0]['corr']='CHALLENGE';reject('unconfirmed-historical-alternative',account=account)
 else:
  tree=etree.fromstring(raw);group=tree.xpath('./t:text//t:milestone[@unit="source-colgroup"]',namespaces=ns)[0];group.set('n','3');reject('literal-column-group-span',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
  tree=etree.fromstring(raw);group=tree.xpath('./t:text//t:milestone[@unit="source-colgroup"]',namespaces=ns)[0];table=group.getparent();table.remove(group);table.append(group);reject('column-group-source-position',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
  tree=etree.fromstring(raw);span=tree.xpath('./t:text//t:seg[@xml:lang]',namespaces=ns)[0];span.set(xml+'lang','fr');reject('native-source-language',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
  account=json.loads(package.member_bytes('source-accountability.json'));row=next(r for r in account['features'] if 'lang' in r['source_attributes'] and xml+'lang' in r['source_attributes']);row['source_attributes']['lang']='fr';reject('separate-ordinary-language-attribute',account=account)
  tree=etree.fromstring(raw);wrapper=tree.xpath('./t:text//t:div[@xml:id="bennett-expositor10-vii.ii-p0.2"]',namespaces=ns)[0];index=wrapper.find('{http://www.tei-c.org/ns/1.0}div');wrapper.remove(index);wrapper.addnext(index);reject('hebrew-index-source-ownership',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 return results


def prepare():
 paths=manifests();results=[]
 try:import_closure(extra_import='ocd_kernel.reconstruction.verifier')
 except ValueError as error:negative=dict(rejected=True,reason=str(error))
 else:raise ValueError('Unexpected first-party import admitted')
 try:import_closure('build.tei.bennett_retained_native_prepare',extra_import='ocd_kernel.reconstruction.verifier')
 except ValueError as error:negative.update(producer_rejected=True,producer_reason=str(error))
 else:raise ValueError('Unexpected producer first-party import admitted')
 for member,path in paths.items():
  manifest=SourceManifest.load(ROOT/path,repository_root=ROOT);destination=CANDIDATES/member/'package';destination.parent.mkdir(parents=True,exist_ok=True)
  package=CandidatePackage.load(destination) if destination.exists() else reconstruct(manifest,destination,_convert)
  report=validate(manifest,package,_oracle);direct=check(member,package.path,native=False);direct['mutations']=challenges(member,package)
  replays=[]
  for number in (1,2):
   replay_dir=CANDIDATES/member/('clean-replay-'+str(number))
   if replay_dir.exists():raise ValueError('Fresh Bennett replay destination required')
   subprocess.run([sys.executable,'-B','-m','build.tei.bennett_retained_native_prepare',str(replay_dir),'--source-manifest',str(ROOT/path)],cwd=ROOT,check=True,capture_output=True)
   replay=CandidatePackage.load(replay_dir)
   if replay.sha256!=package.sha256 or any(replay.member_bytes(n)!=package.member_bytes(n) for n in package.member_names):raise ValueError('Bennett fresh process replay differs')
   replays.append(dict(process='fresh-python',package_sha256=replay.sha256,all_members_byte_equal=True))
  result=dict(member_id=member,package_path=destination.as_posix(),package_sha256=package.sha256,source_manifest_path=path.as_posix(),source_manifest_sha256=manifest.sha256,oracle_report=dict(report.attestation),oracle_report_sha256=report.sha256,direct_source_review=direct,reproducibility=dict(status='pass',fresh_python_process=True,exact_six_member_bytes_equal=True,replays=replays),closure_negative=negative)
  (ROOT/LOG/(member+'-current-review.json')).write_bytes(canonical(result));results.append(result)
 (ROOT/LOG/'candidate-completion-receipt.json').write_bytes(canonical(dict(status='pass',work_id=WORK_ID,included_volumes=2,acquired_volumes=2,members=results)))
 return [dict(member_id=r['member_id'],package_sha256=r['package_sha256']) for r in results]

if __name__=='__main__':print(json.dumps(prepare(),sort_keys=True))
