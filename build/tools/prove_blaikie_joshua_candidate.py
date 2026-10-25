"""Challenge and reproduce only the frozen complete Joshua candidate."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from lxml import etree
import jsonschema
from build.tei.blaikie_joshua_retained_native_prepare import ROOT,LOG,SOURCE_DIR,canonical
from build.tei.blaikie_joshua_retained_native_oracle import check,_oracle,import_closure
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,validate

MEMBER='blaikie-expositorjosh'
SOURCE=SOURCE_DIR/(MEMBER+'.source-manifest-v3.json')
BASE=Path('D:/Library/Open Christian Data/candidate-reviews/blaikie-joshua-existing-readable-20261003-v3')/MEMBER
NS='http://www.tei-c.org/ns/1.0';XML='{http://www.w3.org/XML/1998/namespace}'

def digest(raw):return sha256(raw).hexdigest()

def main():
 output=ROOT/LOG/'candidate-completion-receipt-v3.json'
 if output.exists() or (BASE/'proof-v1').exists():raise FileExistsError('Preserve Joshua proof evidence')
 manifest=SourceManifest.load(ROOT/SOURCE,repository_root=ROOT);package=CandidatePackage.load(BASE/'package')
 if package.sha256!='bbddb9ff7e13e5b1aba72851a5a640649abbea4620588e5c702cd48c34f70e4d':raise ValueError('Frozen Joshua package differs')
 report=validate(manifest,package,_oracle);baseline=check(MEMBER,package.path)
 schema=etree.XMLSchema(etree.parse(str(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd')))
 raw=package.member_bytes('content.tei.xml');proof=BASE/'proof-v1';proof.mkdir();results=[]
 namespaces={'t':NS}
 def tree():return etree.fromstring(raw)
 def serialize(node):return etree.tostring(node,encoding='UTF-8',xml_declaration=True)
 def reject(label,data=None,account=None,other=None):
  directory=proof/label;directory.mkdir()
  for name in package.member_names:
   if name!='manifest.json':(directory/name).write_bytes(package.member_bytes(name))
  altered=data if data is not None else raw
  schema.assertValid(etree.fromstring(altered))
  (directory/'content.tei.xml').write_bytes(altered)
  if account is not None:(directory/'source-accountability.json').write_bytes(canonical(account))
  for name,value in (other or {}).items():(directory/name).write_bytes(value)
  if all((directory/name).read_bytes()==package.member_bytes(name) for name in package.member_names if name!='manifest.json'):raise ValueError('Joshua mutation did not change a payload')
  try:check(MEMBER,directory)
  except ValueError as error:
   row=dict(challenge=label,rejected=True,schema_valid=True,reason=str(error),tei_sha256=digest(altered),changed_members=[name for name in package.member_names if name!='manifest.json' and (directory/name).read_bytes()!=package.member_bytes(name)])
   results.append(row);(directory/'rejection.json').write_bytes(canonical(row))
  else:raise ValueError('Joshua oracle admitted mutation '+label)
 cases=[('paragraph-text','./t:text//t:p[text()]','text'),('inline-tail','./t:text//t:hi','tail'),('heading-level','./t:text//t:p[contains(@rend,"source-h")]','rend'),('inline-semantic-role','./t:text//t:hi','rend'),('chapter-source-title','./t:text//t:div[@n]','n'),('chapter-source-level','./t:text//t:div[@type="source-div1"]','type'),('page-number','./t:text//t:pb[@n]','n'),('note-label','./t:text//t:note[@n]','n'),('verse-line-text','./t:text//t:l[text()]','text'),('verse-group-role','./t:text//t:lg','type'),('original-attribute-annotation','./t:text//*[@ana]','ana'),('source-class-rend','./t:text//t:p[contains(@rend,"source-class")]','rend'),('scripture-target','./t:text//t:ref[@target][not(starts-with(@target,"#"))]','target'),('scripture-passage-label','./t:text//t:milestone[@unit="scripCom"][@n]','n'),('index-directive','./t:text//t:milestone[@unit="insertIndex"][@n]','n'),('relative-query-target','./t:text//t:ref[@xml:base]','target'),('relative-query-base','./t:text//t:ref[@xml:base]',XML+'base'),('primary-header-title','./t:teiHeader/t:fileDesc/t:titleStmt/t:title','text'),('visible-primary-head-field','./t:teiHeader//t:note[@type="retained-source-head-field"]','text'),('visible-document-prefix','./t:teiHeader//t:note[@type="retained-source-document-prefix"]','text'),('visible-stylesheet-directive','./t:teiHeader//t:note[@type="retained-source-prolog"]','text')]
 for label,selector,field in cases:
  root=tree();nodes=root.xpath(selector,namespaces=namespaces)
  if not nodes:raise ValueError('Source-backed Joshua mutation feature missing '+label)
  node=nodes[0]
  if field in {'text','tail'}:setattr(node,field,(getattr(node,field) or '')+'CHALLENGE')
  else:node.set(field,'https://example.invalid/context' if field==XML+'base' else 'urn:challenge' if field=='ana' else (node.get(field) or '')+'CHALLENGE')
  reject(label,serialize(root))
 root=tree();refs=root.xpath('./t:text//t:ref[starts-with(@target,"#")]',namespaces=namespaces);target=root.xpath('./t:text//t:p',namespaces=namespaces)[0].get(XML+'id');refs[0].set('target','#'+target);reject('wrong-existing-local-target',serialize(root))
 root=tree();paragraph=root.xpath('./t:text//t:p',namespaces=namespaces)[0];paragraph.set(XML+'id',MEMBER+'-invented-identity');reject('source-local-identity',serialize(root))
 root=tree();note=root.xpath('./t:text//t:note',namespaces=namespaces)[0];destination=next(n for n in root.xpath('./t:text//t:p',namespaces=namespaces) if n is not note.getparent() and note not in n.iterancestors());note.getparent().remove(note);destination.append(note);reject('note-source-attachment',serialize(root))
 root=tree();groups=root.xpath('./t:text//t:lg',namespaces=namespaces);line=groups[0].find('{'+NS+'}l');groups[0].remove(line);groups[1].append(line);reject('verse-line-source-ownership',serialize(root))
 root=tree();body=root.find('{'+NS+'}text/{'+NS+'}body');first,second=body[0],body[1];body.remove(second);body.insert(0,second);reject('authored-chapter-order',serialize(root))
 root=tree();front=root.find('{'+NS+'}text/{'+NS+'}front');front.remove(front[0]);reject('omit-owned-title-page',serialize(root))
 root=tree();back=root.find('{'+NS+'}text/{'+NS+'}back');back.remove(back[0]);reject('omit-owned-indexes',serialize(root))
 root=tree();stand=etree.SubElement(root,'{'+NS+'}standOff');listing=etree.SubElement(stand,'{'+NS+'}list');etree.SubElement(listing,'{'+NS+'}item').text='Additional outer readable payload';reject('unexpected-outer-readable-payload',serialize(root))
 root=tree();root[0].tail='\n ';reject('unexpected-header-tail',serialize(root))
 account=json.loads(package.member_bytes('source-accountability.json'));next(r for r in account['features'] if r['source_tag']=='#comment')['source_text']='CHALLENGE';reject('administrative-comment-fields',account=account)
 account=json.loads(package.member_bytes('source-accountability.json'));account['source_document_prefix']+='CHALLENGE';reject('literal-source-prefix-account',account=account)
 account=json.loads(package.member_bytes('source-accountability.json'));account['historical_correction_alternatives']=[dict(corr='Invented correction')];reject('invented-historical-correction',account=account)
 provenance=json.loads(package.member_bytes('provenance.json'));provenance['composite_binding']['primary_acquisition']['url']='https://example.invalid/source';reject('composite-acquisition-context',other={'provenance.json':canonical(provenance)})
 reject('omit-typed-source-gaps',other={'unresolved.jsonl':package.member_bytes('unresolved.jsonl').splitlines(keepends=True)[0]})
 reject('visible-permission-notice',other={'README.source.md':b'# Missing retained permission\n'})
 contracts=[];contract_root=ROOT/SOURCE_DIR/'identity-challenges-v3'
 if contract_root.exists():raise FileExistsError('Preserve Joshua source identity challenges')
 contract_root.mkdir()
 package_schema=json.loads((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes())
 def contract_reject(label,alter_source=None,alter_package=None):
  source_record=json.loads((ROOT/SOURCE).read_bytes());candidate_record=json.loads(package.member_bytes('manifest.json'))
  if alter_source:alter_source(source_record)
  source_path=contract_root/(label+'.source-manifest.json');source_bytes=canonical(source_record);source_path.write_bytes(source_bytes)
  candidate_record['source_manifest']=dict(path=source_path.relative_to(ROOT).as_posix(),sha256=digest(source_bytes))
  if alter_package:alter_package(candidate_record)
  jsonschema.Draft202012Validator(package_schema).validate(candidate_record)
  directory=proof/label;directory.mkdir()
  for name in package.member_names:(directory/name).write_bytes(canonical(candidate_record) if name=='manifest.json' else package.member_bytes(name))
  schema.assertValid(etree.fromstring((directory/'content.tei.xml').read_bytes()))
  changed_source=SourceManifest.load(source_path,repository_root=ROOT);changed_candidate=CandidatePackage.load(directory)
  try:_oracle(changed_source,changed_candidate)
  except ValueError as error:
   row=dict(challenge=label,rejected=True,candidate_schema_valid=True,source_sdk_contract_valid=True,p5_valid=True,reason=str(error),source_manifest_path=source_path.relative_to(ROOT).as_posix(),source_manifest_sha256=changed_source.sha256,package_sha256=changed_candidate.sha256,all_five_payloads_byte_unchanged=True)
   contracts.append(row);(proof/(label+'-rejection.json')).write_bytes(canonical(row))
  else:raise ValueError('Joshua oracle admitted source/package identity challenge '+label)
 contract_reject('source-id-missing-prefix',lambda r:r.update(source_id=MEMBER+'-v1'))
 contract_reject('source-id-missing-suffix',lambda r:r.update(source_id='ccel-blaikie-joshua-retained-native-'+MEMBER))
 contract_reject('source-work-identity',lambda r:r.update(work_id='blaikie-book-of-joshua'))
 contract_reject('source-order-declaration',lambda r:r.update(source_order=dict(order='reordered source DOM')))
 contract_reject('source-authority-role',lambda r:r['authorities'][1].update(role='unreviewed-profile'))
 contract_reject('source-authority-order',lambda r:r['authorities'].reverse())
 contract_reject('package-source-identity',alter_package=lambda r:r.update(source_id='ccel-other-retained-source-v1'))
 contract_reject('package-source-manifest-digest',alter_package=lambda r:r['source_manifest'].update(sha256='0'*64))
 negatives={}
 for label,module in [('oracle','build.tei.blaikie_joshua_retained_native_oracle'),('producer','build.tei.blaikie_joshua_retained_native_prepare')]:
  try:import_closure(module,extra_import='ocd_kernel.reconstruction.verifier')
  except ValueError as error:negatives[label]=dict(rejected=True,reason=str(error))
  else:raise ValueError('Joshua unexpected first-party import admitted')
 replays=[]
 for number in (1,2):
  destination=BASE/('fresh-six-member-replay-'+str(number))
  if destination.exists():raise FileExistsError('Preserve Joshua replay')
  subprocess.run([sys.executable,'-I','-B','-c','import sys,runpy;sys.path.insert(0,sys.argv[1]);sys.argv=sys.argv[2:];runpy.run_module("build.tei.blaikie_joshua_retained_native_prepare",run_name="__main__")',str(ROOT),'build.tei.blaikie_joshua_retained_native_prepare',str(destination),'--source-manifest',str(ROOT/SOURCE)],cwd=ROOT,check=True,capture_output=True,text=True)
  replay=CandidatePackage.load(destination)
  if replay.sha256!=package.sha256 or any(replay.member_bytes(name)!=package.member_bytes(name) for name in package.member_names):raise ValueError('Joshua six-member replay differs')
  replays.append(dict(fresh_isolated_python=True,package_path=destination.as_posix(),package_sha256=replay.sha256,all_six_members_byte_equal=True,member_pins={name:digest(replay.member_bytes(name)) for name in replay.member_names}))
 result=dict(status='pass',work_id=manifest.record['work_id'],member_id=MEMBER,complete_authored_works=1,source_members=1,package_path=package.path.as_posix(),package_sha256=package.sha256,source_manifest_path=SOURCE.as_posix(),source_manifest_sha256=manifest.sha256,oracle_report_sha256=report.sha256,direct_source_review=baseline,mutations=results,source_package_identity_challenges=contracts,replays=replays,import_negatives=negatives,proof_implementation_sha256=digest(Path(__file__).read_bytes()),canonical_mutation=False,no_download=True)
 output.write_bytes(canonical(result));print(json.dumps(dict(status='pass',valid_rejected_mutations=len(results),fresh_six_member_replays=len(replays),proof_path=output.relative_to(ROOT).as_posix(),proof_sha256=digest(output.read_bytes())),sort_keys=True))

if __name__=='__main__':main()
