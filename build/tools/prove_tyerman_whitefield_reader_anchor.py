"""One schema-valid public alias challenge; preserved v7 source/reader stays exact."""
from pathlib import Path
import copy,hashlib,json
from types import SimpleNamespace
from unittest.mock import patch
import jsonschema
from build.tools import prove_tyerman_whitefield_reader as draft
from ocd_kernel.library import acquisitions
from ocd_kernel.projection.categories import native_documents,sermons
ROOT=draft.ROOT;HOME=draft.HOME
def main():
 target=ROOT/'reports/_logs/tyerman-whitefield-complete-20261004-v1/reader-v7/valid-anchor-challenge.json'
 if target.exists():raise FileExistsError('Preserve valid anchor challenge')
 leaf=draft.load('ocd_kernel.projection.categories.tyerman_whitefield_source_profile',HOME/'tyerman_whitefield_source_profile.py')
 observer=draft.load('whitefield_anchor_observer',HOME/'native_content_check_candidate.py')
 native=draft.load('whitefield_anchor_native',HOME/'native_documents_candidate.py')
 prose=draft.load('whitefield_anchor_prose',HOME/'prose_candidate.py')
 observer.SCHEMA=ROOT/'schemas/v2/native-content.schema.json';native.observe_content=observer.observe_content
 result=json.loads((ROOT/'reports/_logs/tyerman-whitefield-complete-20261004-v1/reader-v7/actual-rows-and-receipt.json').read_bytes());changed=copy.deepcopy(result)
 def walk(node):
  if isinstance(node,dict):
   if node.get('kind')=='abbreviation-choice' and node.get('attributes',{}).get('source_anchor')==leaf.ANCHORS['v62023-p154a']:
    node['attributes']['source_anchor']='PgCHALLENGE';return node
   for value in node.values():
    if answer:=walk(value):return answer
  elif isinstance(node,list):
   for value in node:
    if answer:=walk(value):return answer
 mutation=walk(changed['rows']);assert mutation
 schema=json.loads(observer.SCHEMA.read_bytes());jsonschema.Draft202012Validator(schema).validate(mutation)
 a=json.loads(draft.AP.read_bytes())
 context={'root':ROOT,'identity':leaf.IDENTITY,'accepted':{'identity':{**leaf.IDENTITY,'acquisition_id':leaf.ACQUISITION},'source':{**leaf.SOURCE,'missing_members':[],'unknown_members':[]}},'language':'en','representation_revision':'tyerman-whitefield-complete-retained-20261004-v1','edition_title':'The Life of the Rev. George Whitefield, B.A.','edition':SimpleNamespace(path=draft.MASTER),'authority':{'master':{'sha256':leaf.MASTER_SHA},'acquisition':{'sha256':draft.sha(draft.AP.read_bytes())}}}
 with (patch.object(sermons,'_accepted_context',lambda *a,**k:context),patch.object(acquisitions,'acquisition_for_edition',lambda *args,**kw:(draft.AP,a)),patch.object(native_documents,'verify_accepted_document',native.verify_accepted_document),patch.object(native,'project_document',side_effect=AssertionError('Producer invoked for independent valid alias challenge'))):
  errors=prose.verify_accepted_prose(ROOT,acceptance_path=ROOT/'.tmp_audit/whitefield-no-installed-acceptance.json',rows=changed['rows'],receipt=changed['receipt'])
 assert errors and any('rows' in e or 'correspondence' in e for e in errors),errors
 record={'status':'pass','mutation':'One public choice source_anchor changes to schema-valid PgCHALLENGE; literal source/current master unchanged.','mutation_native_schema':'pass','independent_lxml_rejection':errors,'producer_disabled':True,'original_v7_proof_sha256':draft.sha(ROOT/'reports/_logs/tyerman-whitefield-complete-20261004-v1/reader-v7/proof.json'),'qualification':'Original v7 CHALLENGE anchor negative is schema rejection. This supplement establishes actual correspondence rejection for a schema-valid alias; accepted context/acquisition lookup remain mocked, not installation proof.','driver_sha256':draft.sha(Path(__file__)),'candidate_code_pins':{p.name:draft.sha(p) for p in HOME.glob('*.py')}}
 draft.save(target,record);print(json.dumps({'receipt':str(target),'sha256':draft.sha(target)}))
if __name__=='__main__':main()
