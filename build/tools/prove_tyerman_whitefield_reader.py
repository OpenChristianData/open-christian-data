"""Exercise isolated Whitefield candidates through the maintained prose entry.

Acceptance context is explicitly mocked; this is not an installed acceptance gate.
"""
from pathlib import Path
import copy,hashlib,importlib.util,json,sys
from types import SimpleNamespace
from unittest.mock import patch
import xml.etree.ElementTree as ET
from ocd_kernel.library import acquisitions
from ocd_kernel.projection.categories import native_documents,sermons

ROOT=Path(__file__).resolve().parents[2]
HOME=ROOT/'.tmp_audit/tyerman_whitefield_native_v7'
LOG=ROOT/'reports/_logs/tyerman-whitefield-complete-20261004-v1/reader-v7'
MASTER=ROOT/'sources/manifest-acquisitions/tyerman-life-george-whitefield-accepted-header-draft-20261004-v1/candidate.tei.xml'
AP=ROOT/'sources/manifest-acquisitions/tyerman-life-george-whitefield-identity-proposal-20261004-v1/tyerman-life-george-whitefield--pg44280-62023-retained-member-set.json'
N='{http://www.tei-c.org/ns/1.0}';X='{http://www.w3.org/XML/1998/namespace}'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def save(path,v):path.write_bytes((json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode())
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
def main():
 if LOG.exists():raise FileExistsError('Preserve existing reader run')
 LOG.mkdir(parents=True)
 for p in HOME.glob('*.py'):compile(p.read_text(encoding='utf-8'),str(p),'exec')
 leaf=load('ocd_kernel.projection.categories.tyerman_whitefield_source_profile',HOME/'tyerman_whitefield_source_profile.py')
 producer=load('whitefield_candidate_producer',HOME/'native_content_candidate.py')
 observer=load('whitefield_candidate_observer',HOME/'native_content_check_candidate.py')
 native=load('whitefield_candidate_native',HOME/'native_documents_candidate.py')
 prose=load('whitefield_candidate_prose',HOME/'prose_candidate.py')
 producer.SCHEMA=ROOT/'schemas/v2/native-content.schema.json';observer.SCHEMA=producer.SCHEMA
 native.native_content=producer;native.observe_content=observer.observe_content
 a=json.loads(AP.read_bytes())
 context={'root':ROOT,'identity':leaf.IDENTITY,'accepted':{'identity':{**leaf.IDENTITY,'acquisition_id':leaf.ACQUISITION},'source':{**leaf.SOURCE,'missing_members':[],'unknown_members':[]}},'language':'en','representation_revision':'tyerman-whitefield-complete-retained-20261004-v1','edition_title':'The Life of the Rev. George Whitefield, B.A.','edition':SimpleNamespace(path=MASTER),'authority':{'master':{'sha256':leaf.MASTER_SHA},'acquisition':{'sha256':sha(AP.read_bytes())}}}
 acceptance=ROOT/'.tmp_audit/whitefield-no-installed-acceptance.json'
 with (patch.object(sermons,'_accepted_context',lambda *args,**kw:context),patch.object(acquisitions,'acquisition_for_edition',lambda *args,**kw:(AP,a)),patch.object(native_documents,'project_accepted_document',native.project_accepted_document),patch.object(native_documents,'verify_accepted_document',native.verify_accepted_document)):
  result=prose.project_accepted_prose(ROOT,acceptance_path=acceptance)
  save(LOG/'actual-rows-and-receipt.json',result)
  assert len(result['rows'])==6
  with patch.object(native,'project_document',side_effect=AssertionError('Producer invoked during independent observation')):
   errors=prose.verify_accepted_prose(ROOT,acceptance_path=acceptance,rows=result['rows'],receipt=result['receipt'])
   assert errors==[],errors
  def anchor_mutation(result):
   def walk(value):
    if isinstance(value,dict):
     if value.get('kind')=='abbreviation-choice' and value.get('attributes',{}).get('source_anchor')==leaf.ANCHORS['v62023-p154a']:
      value['attributes']['source_anchor']='CHALLENGE';return True
     return any(walk(v) for v in value.values())
    if isinstance(value,list):return any(walk(v) for v in value)
    return False
   assert walk(result['rows'])
  challenges=[]
  for label,mutate in [('choice-anchor',anchor_mutation),('row-text',lambda r:r['rows'][0].update(text=r['rows'][0]['text']+'CHALLENGE')),('row-order',lambda r:r['rows'].reverse()),('receipt-mapping',lambda r:r['receipt'].update(mapping_version='CHALLENGE'))]:
   changed=copy.deepcopy(result);mutate(changed)
   with patch.object(native,'project_document',side_effect=AssertionError('Producer invoked during independent observation')):
    errors=prose.verify_accepted_prose(ROOT,acceptance_path=acceptance,rows=changed['rows'],receipt=changed['receipt'])
   assert errors,(label,'challenge accepted');challenges.append({'name':label,'errors':errors})
 raw=MASTER.read_bytes();root=ET.fromstring(raw)
 for label,mutate in [('volume-order',lambda r:r.find(N+'text/'+N+'group').insert(0,r.find(N+'text/'+N+'group')[1])),('body-invented-text',lambda r:setattr(r.find('.//'+N+'body'),'text','CHALLENGE')),('header-title',lambda r:setattr(r.find('.//'+N+'title'),'text','CHALLENGE'))]:
  changed=copy.deepcopy(root);mutate(changed)
  try:leaf.check_et(changed)
  except ValueError as exc:challenges.append({'name':label,'errors':[str(exc)]})
  else:raise AssertionError(label+' accepted')
 for label,node,mutate,check in [('abbr-expansion',root.find('.//'+N+'choice'),lambda n:setattr(n[1],'text','CHALLENGE'),leaf.choice_et),('graphic-pixels',root.find('.//'+N+'graphic'),lambda n:n.set('url',n.get('url')+'CHALLENGE'),leaf.graphic_et),('graphic-dimension',root.find('.//'+N+'graphic'),lambda n:n.set('height','999px'),leaf.graphic_et)]:
  changed=copy.deepcopy(node);mutate(changed)
  try:check(changed)
  except ValueError as exc:challenges.append({'name':label,'errors':[str(exc)]})
  else:raise AssertionError(label+' accepted')
 public=json.dumps(result['rows'],ensure_ascii=False)
 from urllib.parse import unquote
 assert 'data:image' not in public and 'urn:ocd:' not in unquote(public)
 def walk(n):
  if isinstance(n,dict):
   yield n
   for v in n.values():yield from walk(v)
  elif isinstance(n,list):
   for v in n:yield from walk(v)
 nodes=list(walk(result['rows']))
 graphics=[n for n in nodes if n.get('kind')=='image-reference']
 receipt={'status':'PASS isolated maintained prose public entry','qualification':'Accepted context and acquisition lookup mocked to exact reviewed proposal; source/acquisition/master files real and pinned. No accepted sidecars or canonical installation validated. Independent lxml verifier invoked with producer disabled.','row_count':len(result['rows']),'locators':[r['locator'] for r in result['rows']],'graphic_count':len(graphics),'challenges':challenges,'package':{'path':str(HOME/'packet.json'),'sha256':sha((HOME/'packet.json').read_bytes())},'master_sha256':sha(raw),'schema_sha256':sha(producer.SCHEMA.read_bytes()),'row_file_sha256':sha((LOG/'actual-rows-and-receipt.json').read_bytes()),'code_pins':{str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in HOME.glob('*.py')},'public_no_private_urn_or_embedded_pixels':True}
 assert len(graphics)==5
 assert sum(n.get('attributes',{}).get('source_anchor')==leaf.ANCHORS['v62023-p154a'] for n in nodes)==1
 assert sum(n.get('attributes',{}).get('source_target')=='#'+leaf.ANCHORS['v62023-p154a'] for n in nodes)==1
 receipt['reversible_choice_anchor_map']=leaf.ANCHORS
 save(LOG/'proof.json',receipt);print(json.dumps({'proof':str(LOG/'proof.json'),'sha256':sha((LOG/'proof.json').read_bytes()),'rows':len(result['rows'])}))
if __name__=='__main__':main()
