"""Complete and challenge only Farrar's three existing acquired XML witnesses."""
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
from lxml import etree
from build.tei.farrar_retained_native_prepare import ROOT,LOG,SOURCE_DIR,WORK_ID,MEMBERS,SPECS,OLD_PACKAGE,canonical,sha,convert,_convert
from build.tei.farrar_retained_native_oracle import check,_oracle,import_closure,ORACLE_IMPORTS,PRODUCER_IMPORTS,_p5_schema
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,reconstruct,validate
CANDIDATES=Path('D:/Library/Open Christian Data/candidate-reviews/farrar-existing-native-20261003-v2')
def authority(name,path,role):
 raw=(ROOT/path).read_bytes();return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(raw),sha256=sha(raw))
def manifests():
 (ROOT/SOURCE_DIR).mkdir(parents=True,exist_ok=True);paths={};closure=import_closure();producer=import_closure('build.tei.farrar_retained_native_prepare')
 for member,parts in MEMBERS.items():
  spec=SPECS[member];payload=convert(member);source=etree.fromstring((ROOT/spec['path']).read_bytes());body=source.find('ThML.body');account=json.loads(payload['source-accountability.json'])
  temporary=ROOT/LOG/'authority-payloads'/member;temporary.mkdir(parents=True,exist_ok=True)
  for name,data in payload.items():(temporary/name).write_bytes(data)
  direct=check(member,temporary)
  profile=SOURCE_DIR/(member+'.profile.json');policy=SOURCE_DIR/(member+'.policy.json');readme=SOURCE_DIR/(member+'.README.source.md')
  (ROOT/readme).write_bytes(payload['README.source.md'])
  (ROOT/profile).write_bytes(canonical(dict(contract='ocd-farrar-existing-native-profile-v1',work_id=WORK_ID,member_id=member,source=spec,source_census={k:direct[k] for k in ('whole_source_elements','source_body_nodes','note_count','table_count','preformatted_count','relative_nonfragment_links','relative_query_links')},original_package_sha256=account['original_package_sha256'],original_member_c14n_sha256=account['original_member_c14n_sha256'],root_regions=account['root_disposition'],body_tags=dict(Counter(n.tag for n in body.iter() if isinstance(n.tag,str))),body_source_attributes={tag:sorted({k for n in body.iter(tag) for k in n.attrib}) for tag in sorted({n.tag for n in body.iter() if isinstance(n.tag,str)})},producer_import_closure_sha256=producer,producer_imports=list(PRODUCER_IMPORTS),oracle_imports=list(ORACLE_IMPORTS),genre='commentary',scope='All three existing acquired electronic volume witnesses; author and series completeness open',adaptations=['h1 through h6 become source-level heading paragraphs','preformatted ab preserves exact text/inline/space','tbody rows remain owned by table; original wrapper and whitespace are reversible','34 administrative body comments are visible header notes plus exact source ledger and whitespace joins','999 literal query links use acquired URL per-ref xml:base','provider/browser navigation and metadata remain literal ledger fields; no pixel/CSS equivalence claim','logical front/body/back preserves introductions, chronology notes, appendices and indexes'],limitations=direct['limitations'])))
  (ROOT/policy).write_bytes(canonical(dict(contract='ocd-farrar-independent-native-policy-v1',member_id=member,independent='stdlib raw XML corroborated by lxml versus every actual native TEI field; independent exact original package/crosswalk/carriers and actual-backed source-body inverse',required=['all ordered native direct/tail/attributes/attachment','all note/preformatted/table/Scripture labels and links','exact complete root/header/text envelope','full source head/prolog/comments/admin visible and reversible','exact old six-member package and all source fields/carriers','P5','schema-valid source-feature mutations','two fresh six-member byte replays','strict observed producer/oracle imports and late execution closure'],patterns=['RP-01','RP-03','RP-04','RP-06','RP-11','RP-13','RP-14','RP-15'],limitations=direct['limitations'])))
  auth=[authority('retained-thml',spec['path'],'primary-source'),authority('member-profile',profile,'complete-source-feature-profile'),authority('member-policy',policy,'independent-validation-policy'),authority('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),authority('package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema'),authority('source-local-attribution-readme',readme,'source-rights-attribution'),authority('permission','sources/commentaries/expositors-bible/ccel-permission.md','source-rights-evidence'),authority('original-source-credit','data/commentaries/expositors-bible/README.md','historical-source-credit'),authority('work-source-credit',Path('library/works')/WORK_ID/'SOURCE_CREDIT.md','work-source-credit'),authority('source-uri-acquisition',account['source_uri_acquisition_path'],'source-uri-context-authority'),authority('local-native-emitter','build/tei/farrar_retained_native_emitter.py','bounded-existing-source-native-producer')]
  auth += [authority('original-'+p.name,p.relative_to(ROOT),'preexisting-reconstruction-evidence') for p in sorted((ROOT/OLD_PACKAGE).iterdir()) if p.is_file()]
  auth += [authority('import-'+str(i),p,'observed-first-party-import-dependency') for i,p in enumerate(sorted(set(ORACLE_IMPORTS+PRODUCER_IMPORTS)))]
  auth += [authority('existing-assessment',LOG/'existing-scope-assessment.json','existing-candidate-recovery-evidence'),authority('original-scope-proof',LOG/'original-source-scope-reconciliation.json','independent-original-scope-evidence'),authority('source-assessor','build/tools/farrar_retained_assess.py','independent-recovery-implementation'),authority('package-and-challenge-recipe','build/tools/prepare_farrar_retained_candidates.py','replay-and-challenge-implementation')]
  record=dict(contract='ocd-source-manifest-v1',source_id='ccel-farrar-retained-native-'+member+'-v1',work_id=WORK_ID,ticket_id='37c-151-existing-farrar-acquired-editions',authorities=auth,converter=dict(id=_convert.converter_id,version=_convert.converter_version,callable='_convert',implementation_path='build/tei/farrar_retained_native_prepare.py',implementation_sha256=sha((ROOT/'build/tei/farrar_retained_native_prepare.py').read_bytes())),validator=dict(id=_oracle.oracle_id,version=_oracle.oracle_version,callable='_oracle',implementation_path='build/tei/farrar_retained_native_oracle.py',implementation_sha256=sha((ROOT/'build/tei/farrar_retained_native_oracle.py').read_bytes()),import_closure_sha256=closure),package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes())),scope=dict(kind='complete-existing-retained-edition',member_id=member,acquired_work_member_count=3,no_acquisition_or_download=True),source_order=dict(order='Exact source DOM order with explicit reversible region/tbody/comment mapping'))
  path=SOURCE_DIR/(member+'.source-manifest.json');(ROOT/path).write_bytes(canonical(record));SourceManifest.load(ROOT/path,repository_root=ROOT);paths[member]=path
 return paths
def challenges(member,package):
 ns={'t':'http://www.tei-c.org/ns/1.0'};raw=package.member_bytes('content.tei.xml');scratch=CANDIDATES/member/'challenges';scratch.mkdir(exist_ok=True);results=[]
 for n in package.member_names:(scratch/n).write_bytes(package.member_bytes(n))
 def reject(label,data,account=None):
  _p5_schema().assertValid(etree.fromstring(data))
  (scratch/'content.tei.xml').write_bytes(data);(scratch/'source-accountability.json').write_bytes(account or package.member_bytes('source-accountability.json'))
  try:check(member,scratch)
  except ValueError as error:results.append(dict(challenge=label,p5_valid=True,rejected=True,reason=str(error)[:400],tei_sha256=sha(data)))
  else:raise ValueError('Farrar source mutation admitted '+label)
 cases=[('paragraph-text','.//t:text//t:p','text'),('source-tail','.//t:text//t:ref','tail'),('literal-link-target','.//t:text//t:ref[@target]','target'),('query-url-context','.//t:text//t:ref[@xml:base]','{http://www.w3.org/XML/1998/namespace}base'),('note-label','.//t:text//t:note[@n]','n'),('note-anchoring','.//t:text//t:note[@anchored]','anchored'),('inline-rend','.//t:text//t:hi[@rend]','rend'),('source-heading','.//t:text//t:p[@rend="source-h2"]','text'),('preformatted-space','.//t:text//t:ab[@rend="source-preformatted"]','{http://www.w3.org/XML/1998/namespace}space'),('preformatted-payload','.//t:text//t:ab[@rend="source-preformatted"]','text'),('table-summary','.//t:text//t:table[@n]','n'),('Scripture-passage-label','.//t:text//t:ref[@n]','n'),('commentary-type','.//t:text//t:milestone[@type]','type'),('source-head-field','.//t:note[@type="retained-source-head-field"]','text'),('literal-prolog','.//t:note[@type="retained-exact-source-prolog"]','text'),('visible-admin-comment','.//t:note[@type="retained-source-body-comment"]','text')]
 for label,selector,field in cases:
  tree=etree.fromstring(raw);nodes=tree.xpath(selector,namespaces=ns)
  if not nodes:raise ValueError('Required Farrar challenge feature absent '+label)
  node=next((n for n in nodes if getattr(n,field,None)),nodes[0]) if field in {'text','tail'} else nodes[0]
  if field in {'text','tail'}:setattr(node,field,(getattr(node,field) or '')+'CHALLENGE')
  elif label=='note-anchoring':node.set(field,'false')
  elif label=='preformatted-space':node.set(field,'default')
  else:node.set(field,(node.get(field) or '')+'CHALLENGE')
  reject(label,etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 tree=etree.fromstring(raw);note=tree.xpath('.//t:text//t:note',namespaces=ns)[0];target=next(n for n in tree.xpath('.//t:text//t:p',namespaces=ns) if n is not note.getparent() and note not in n.iterancestors());note.getparent().remove(note);target.append(note);reject('note-attachment',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 tree=etree.fromstring(raw);root=tree.find('{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body');root[0],root[1]=root[1],root[0];reject('source-root-order',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 tree=etree.fromstring(raw);etree.SubElement(etree.SubElement(tree.find('{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body'),'{http://www.tei-c.org/ns/1.0}div'),'{http://www.tei-c.org/ns/1.0}p').text='CHALLENGE';reject('outer-body-added-payload',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 tree=etree.fromstring(raw);facsimile=etree.Element('{http://www.tei-c.org/ns/1.0}facsimile');surface=etree.SubElement(facsimile,'{http://www.tei-c.org/ns/1.0}surface');etree.SubElement(surface,'{http://www.tei-c.org/ns/1.0}graphic',url='urn:challenge');tree.insert(1,facsimile);reject('valid-outer-sibling',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 tree=etree.fromstring(raw);desc=tree.find('{http://www.tei-c.org/ns/1.0}teiHeader/{http://www.tei-c.org/ns/1.0}fileDesc/{http://www.tei-c.org/ns/1.0}sourceDesc');etree.SubElement(etree.SubElement(desc,'{http://www.tei-c.org/ns/1.0}bibl'),'{http://www.tei-c.org/ns/1.0}note').text='CHALLENGE';reject('header-added-readable-payload',etree.tostring(tree,encoding='UTF-8',xml_declaration=True))
 account=json.loads(package.member_bytes('source-accountability.json'));next(r for r in account['features'] if r['source_tag']=='#comment')['source_text']+='CHALLENGE';reject('exact-admin-ledger',raw,canonical(account))
 account=json.loads(package.member_bytes('source-accountability.json'));next(r for r in account['features'] if r['source_tag']=='tbody')['source_attributes']['class']='CHALLENGE';reject('source-wrapper-attribute',raw,canonical(account))
 return results
def prepare():
 paths=manifests();results=[];negative={}
 for module,key in [('build.tei.farrar_retained_native_oracle','rejected'),('build.tei.farrar_retained_native_prepare','producer_rejected')]:
  try:import_closure(module,extra_import='ocd_kernel.reconstruction.verifier')
  except ValueError as error:negative[key]=True;negative[key+'_reason']=str(error)
  else:raise ValueError('Farrar unexpected import admitted')
 for member,path in paths.items():
  manifest=SourceManifest.load(ROOT/path,repository_root=ROOT);destination=CANDIDATES/member/'package';destination.parent.mkdir(parents=True,exist_ok=True)
  if destination.exists():raise ValueError('Fresh Farrar six-member package destination required')
  package=reconstruct(manifest,destination,_convert);report=validate(manifest,package,_oracle);direct=check(member,package.path);direct['mutations']=challenges(member,package);replays=[]
  for number in (1,2):
   replay_dir=CANDIDATES/member/('fresh-replay-'+str(number));subprocess.run([sys.executable,'-I','-B','-c','import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module("build.tei.farrar_retained_native_prepare",run_name="__main__")',str(ROOT),str(replay_dir),'--source-manifest',str(ROOT/path)],cwd=ROOT,check=True,capture_output=True)
   replay=CandidatePackage.load(replay_dir)
   if replay.sha256!=package.sha256 or any(replay.member_bytes(n)!=package.member_bytes(n) for n in package.member_names):raise ValueError('Fresh Farrar six-member byte replay differs')
   replays.append(dict(process='fresh-isolated-python',package_sha256=replay.sha256,all_six_members_byte_equal=True))
  result=dict(member_id=member,package_path=destination.as_posix(),package_sha256=package.sha256,source_manifest_path=path.as_posix(),source_manifest_sha256=manifest.sha256,oracle_report=dict(report.attestation),oracle_report_sha256=report.sha256,direct_source_review=direct,reproducibility=dict(status='pass',fresh_python_process=True,exact_six_member_bytes_equal=True,replays=replays),closure_negative=negative)
  (ROOT/LOG/(member+'-current-review-v1.json')).write_bytes(canonical(result));results.append(result)
 (ROOT/LOG/'candidate-completion-receipt-v1.json').write_bytes(canonical(dict(status='pass',work_id=WORK_ID,included_volumes=3,acquired_volumes=3,members=results)))
 return [dict(member_id=r['member_id'],package_sha256=r['package_sha256']) for r in results]
if __name__=='__main__':print(json.dumps(prepare(),sort_keys=True))
