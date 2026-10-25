"""Valid source-contract and package mutants must fail the independent oracle."""
from pathlib import Path
from copy import deepcopy
import json
from jsonschema import Draft202012Validator
from lxml import etree
from build.tei.blaikie_first_samuel_retained_native_prepare import ROOT,LOG,SOURCE_DIR,canonical,sha,_convert
from build.tei.blaikie_first_samuel_retained_native_oracle import _oracle,_p5_schema
from build.tools.prepare_blaikie_first_samuel_candidates import CANDIDATES,MEMBER,authority
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,reconstruct

OUT=Path('D:/Library/Open Christian Data/candidate-reviews/blaikie-first-samuel-contract-challenges-20261003-v1')

def main():
 if OUT.exists():raise FileExistsError('Preserve previous First Samuel contract evidence')
 OUT.mkdir();rows=[];schema=json.loads((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes())
 original_path=SOURCE_DIR/(MEMBER+'.source-manifest.json');original=json.loads((ROOT/original_path).read_bytes());source=SourceManifest.load(ROOT/original_path,repository_root=ROOT);base=CandidatePackage.load(CANDIDATES/'package')
 labels=['policy-required-gates','profile-complete-work-count','primary-source-role','complete-work-count','source-member-count','acquired-member-count','excluded-work-set','source-order','source-identity','candidate-converter-identity','candidate-source-identity','composite-provenance','human-visible-permission']
 for label in labels:
  contract=deepcopy(original);target=OUT/label;target.mkdir(parents=True)
  if label.startswith('candidate-') or label in ('composite-provenance','human-visible-permission'):
   directory=target/'package';directory.mkdir()
   for name in base.member_names:(directory/name).write_bytes(base.member_bytes(name))
   manifest=json.loads((directory/'manifest.json').read_bytes())
   if label=='candidate-converter-identity':manifest['converter']['id']+='CHALLENGE'
   elif label=='candidate-source-identity':manifest['source_id']='unrelated-source'
   else:
    name='provenance.json' if label=='composite-provenance' else 'README.source.md'
    if label=='composite-provenance':
     value=json.loads((directory/name).read_bytes());value['historical_accounting_pin_exact']=True;content=canonical(value)
    else:content=(directory/name).read_bytes().replace(b'Do not sell CCEL files or derivatives of their formatting.',b'Source notice omitted by challenge.')
    (directory/name).write_bytes(content);row=next(r for r in manifest['members'] if r['name']==name);row.update(bytes=len(content),sha256=sha(content))
   (directory/'manifest.json').write_bytes(canonical(manifest));candidate=CandidatePackage.load(directory);mutant_source=source
  else:
   if label.startswith(('policy','profile')):
    name='policy' if label.startswith('policy') else 'profile';a=next(a for a in contract['authorities'] if a['name']==name);record=json.loads((ROOT/a['path']).read_bytes())
    if name=='policy':record['checks']=record['checks'][1:]
    else:record['complete_work_count']+=1
    path=SOURCE_DIR/(MEMBER+'.challenge-'+label+'.json');(ROOT/path).write_bytes(canonical(record));a.update(authority(name,path,a['role']))
   elif label=='primary-source-role':next(a for a in contract['authorities'] if a['name']=='retained-thml')['role']='other-source-role'
   elif label=='source-order':contract['source_order']['members']=['blaikie-expositor2sam']
   elif label=='source-identity':contract['source_id']=MEMBER
   elif label=='excluded-work-set':contract['scope']['excluded_source_members']=[]
   else:contract['scope'][{'complete-work-count':'complete_work_count','source-member-count':'source_member_count','acquired-member-count':'acquired_work_member_count'}[label]]+=1
   path=SOURCE_DIR/(MEMBER+'.challenge-'+label+'.source-manifest.json');(ROOT/path).write_bytes(canonical(contract));mutant_source=SourceManifest.load(ROOT/path,repository_root=ROOT);candidate=reconstruct(mutant_source,target/'package',_convert)
  Draft202012Validator(schema).validate(json.loads(candidate.member_bytes('manifest.json')));_p5_schema().assertValid(etree.fromstring(candidate.member_bytes('content.tei.xml')))
  try:_oracle(mutant_source,candidate)
  except ValueError as error:rows.append(dict(complete_work_id=MEMBER,challenge=label,source_contract_load_pass=True,package_integrity_pass=True,package_schema_valid=True,tei_p5_valid=True,oracle_semantically_rejected=True,reason=str(error),source_manifest_sha256=mutant_source.sha256,candidate_sha256=candidate.sha256))
  else:raise ValueError('First Samuel contract semantic drift admitted '+label)
 if len(rows)!=13:raise ValueError('First Samuel contract finite denominator differs')
 record=dict(status='pass',complete_work_count=1,source_member_count=1,expected_challenges=13,implementation_sha256=sha(Path(__file__).read_bytes()),oracle_sha256=sha((ROOT/'build/tei/blaikie_first_samuel_retained_native_oracle.py').read_bytes()),challenges=rows)
 (ROOT/LOG/'complete-contract-challenges-v1.json').write_bytes(canonical(record));print(json.dumps(dict(status='pass',rejected=len(rows))))

if __name__=='__main__':main()
