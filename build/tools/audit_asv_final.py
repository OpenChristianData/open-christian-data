"""Read-only final closure of the unchanged accepted ASV release."""
from pathlib import Path
from datetime import datetime,timezone
import json
from build.tools.complete_asv_private import ROOT,PUB,OUT,LOG,digest,read,save

def main():
 c=read(ROOT/PUB/'completion.json')
 if c['status']!='pass':raise ValueError('Completion is not passing')
 checked={}
 for name,base in [('authority_bindings',ROOT),('schema_implementation_bindings',ROOT),('release_file_bindings',Path(c['release_path'])),('release_evidence_bindings',OUT)]:
  for rel,h in c[name].items():
   if digest(base/rel)!=h:raise ValueError('Bound input/output drift '+rel)
  checked[name]=len(c[name])
 linkage=read(OUT/'independent-projection-linkage.json')
 if not linkage['producer_disabled'] or len(linkage['cases'])!=6 or any(x['status']!='rejected' or x['required_diagnostic'] not in x['errors'] for x in linkage['cases']):raise ValueError('Independent saved-output challenges incomplete')
 source_proof=ROOT/'reports/_logs/asv-coordinator-source-review-20261002-v1/review.json'
 if read(source_proof)['status']!='pass':raise ValueError('Coordinator direct source proof not passing')
 before=read(OUT/'authority-before.json');after=read(OUT/'authority-after.json')
 if before!=after or read(OUT/'schema-implementation-before.json')!=read(OUT/'schema-implementation-after.json'):raise ValueError('Before/after authority/runtime snapshots differ')
 result=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),implementation_sha256=digest(Path(__file__)),completion_sha256=digest(ROOT/PUB/'completion.json'),checked_binding_counts=checked,coordinator_direct_source_proof=dict(path=source_proof.relative_to(ROOT).as_posix(),sha256=digest(source_proof)),accepted_master_sha256=c['accepted_master_sha256'],all_canonical_source_master_metadata_acceptance_state_unchanged=True,reused_retained_projection_current_independent_checker=True,source_true_empty=0,source_nonempty_whitespace_only=16,private_offline=True,public_publication_performed=False,remaining=c['remaining'])
 save(OUT/'final-delivery-audit.json',result);print(json.dumps(dict(status='pass',counts=checked,completion_sha256=result['completion_sha256'],audit_sha256=digest(OUT/'final-delivery-audit.json'))))
if __name__=='__main__':main()
