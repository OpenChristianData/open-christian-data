"""Reconstruct valid packages with wrong source contracts; reject semantic drift."""
from pathlib import Path
from copy import deepcopy
import json
from jsonschema import Draft202012Validator
from build.tei.dods_complete_prepare import ROOT,LOG,SOURCE_DIR,WORKS,canonical,sha,_convert
from build.tei.dods_complete_oracle import _oracle,_p5_schema
from build.tools.prepare_dods_complete_candidates import CANDIDATES,authority
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,reconstruct
from lxml import etree

OUT=Path('D:/Library/Open Christian Data/candidate-reviews/dods-complete-contract-challenges-20261003-v1')

def main():
 if OUT.exists():raise FileExistsError('Preserve previous Dods contract challenge evidence')
 OUT.mkdir();rows=[];schema=json.loads((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes())
 for key,members in WORKS.items():
  original_path=SOURCE_DIR/(key+'.source-manifest.json');original=json.loads((ROOT/original_path).read_bytes());source=SourceManifest.load(ROOT/original_path,repository_root=ROOT);base=CandidatePackage.load(CANDIDATES/key/'package')
  labels=['policy-required-gates','profile-complete-work-count','primary-source-inventory','complete-source-binding','candidate-converter-identity']
  if key=='dods-gospel-john':labels.append('john-first-volume-only-scope')
  for label in labels:
   contract=deepcopy(original);target=OUT/key/label;target.mkdir(parents=True)
   if label=='candidate-converter-identity':
    directory=target/'package';directory.mkdir()
    for name in base.member_names:(directory/name).write_bytes(base.member_bytes(name))
    manifest=json.loads((directory/'manifest.json').read_bytes());manifest['converter']['id']+='CHALLENGE';(directory/'manifest.json').write_bytes(canonical(manifest));candidate=CandidatePackage.load(directory);mutant_source=source
   else:
    if label.startswith(('policy','profile')):
     name='policy' if label.startswith('policy') else 'profile';a=next(a for a in contract['authorities'] if a['name']==name);record=json.loads((ROOT/a['path']).read_bytes())
     if name=='policy':record['required']=record['required'][1:]
     else:record['complete_work_count']+=1
     path=SOURCE_DIR/(key+'.challenge-'+label+'.json');(ROOT/path).write_bytes(canonical(record));a.update(authority(name,path,a['role']))
    elif label=='primary-source-inventory':next(a for a in contract['authorities'] if a['role']=='primary-source')['name']+='CHALLENGE'
    elif label=='complete-source-binding':
     a=next(a for a in contract['authorities'] if a['name']=='source-binding');other='raw/ccel/expositors-bible/dods_expositor1cor.xml' if key=='dods-genesis' else 'raw/ccel/expositors-bible/dods_expositor1.xml';a.update(authority('source-binding',other,a['role']))
    else:contract['scope']['source_members']=list(members[:1])
    path=SOURCE_DIR/(key+'.challenge-'+label+'.source-manifest.json');(ROOT/path).write_bytes(canonical(contract));mutant_source=SourceManifest.load(ROOT/path,repository_root=ROOT);candidate=reconstruct(mutant_source,target/'package',_convert)
   Draft202012Validator(schema).validate(json.loads(candidate.member_bytes('manifest.json')));_p5_schema().assertValid(etree.fromstring(candidate.member_bytes('content.tei.xml')))
   try:_oracle(mutant_source,candidate)
   except ValueError as error:rows.append(dict(complete_work_id=key,challenge=label,source_contract_load_pass=True,package_integrity_pass=True,package_schema_valid=True,tei_p5_valid=True,oracle_semantically_rejected=True,reason=str(error),source_manifest_sha256=mutant_source.sha256,candidate_sha256=candidate.sha256))
   else:raise ValueError('Dods complete contract semantic drift admitted '+key+' '+label)
  print(json.dumps(dict(complete_work_id=key,rejected=len(labels))),flush=True)
 if len(rows)!=16:raise ValueError('Complete-contract challenge finite denominator differs')
 record=dict(status='pass',complete_work_count=3,acquired_source_count=4,expected_challenges=16,implementation_sha256=sha(Path(__file__).read_bytes()),oracle_sha256=sha((ROOT/'build/tei/dods_complete_oracle.py').read_bytes()),challenges=rows)
 (ROOT/LOG/'complete-contract-challenges-v1.json').write_bytes(canonical(record))
if __name__=='__main__':main()
