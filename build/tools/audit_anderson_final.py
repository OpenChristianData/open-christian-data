"""Read-only final hash closure and later coordinator corroboration binding."""
from datetime import datetime,timezone
from pathlib import Path
import json
from build.tools.release_anderson_private import ROOT,PUB,OUT,digest,read,save
from build.tools.prepare_anderson_current import BASE,LOG,WORK
from ocd_kernel.reconstruction.contract import SourceManifest
def main():
 completion=read(ROOT/PUB/'completion.json')
 if completion['status']!='pass':raise ValueError('Completion not passing')
 checked={}
 for name,base in [('authority_bindings',ROOT),('schema_implementation_bindings',ROOT),('release_file_bindings',Path(completion['release_path'])),('release_evidence_bindings',OUT)]:
  for rel,h in completion[name].items():
   if digest(base/rel)!=h:raise ValueError('Final bound input/output differs '+rel)
  checked[name]=len(completion[name])
 root_review=ROOT/'reports/_logs/anderson-install-20261002-v1/canonical/coordinator-installed-generation-review.json'
 review=read(root_review)
 if review['status']!='pass':raise ValueError('Coordinator installed-generation review not passing')
 public=read(OUT/'independent-projection-linkage.json')
 if public['status']!='pass' or not public['producer_disabled'] or len(public['cases'])!=7 or any(c['status']!='rejected' for c in public['cases']):raise ValueError('Independent public mutation closure incomplete')
 publications={p.relative_to(ROOT).as_posix():digest(p) for p in (ROOT/PUB).glob('*.json')}
 cases=[dict(mutation=c['mutation'],status=c['status'],error_count=len(c['errors']),first_diagnostics=c['errors'][:3]) for c in public['cases']]
 manifest_path=ROOT/BASE/'source-manifest.json';manifest=read(manifest_path)
 source_authorities={}
 for entry in manifest['authorities']:
  path=Path(entry['path'])
  if entry['name']=='work-identity':
   path=Path('reports/_logs/anderson-install-20261002-v1/canonical/original-generation')/path
  if digest(ROOT/path)!=entry['sha256']:raise ValueError('Retained source or exact acquired identity preimage differs '+str(path))
  source_authorities[path.as_posix()]=entry['sha256']
 preflight=read(ROOT/LOG/'retained-handoff-preflight.json');retained_envelope={}
 for rel,h in preflight['pins'].items():
  path=Path(rel)
  if path in (WORK/'work.json',WORK/'state.json'):
   path=Path('reports/_logs/anderson-install-20261002-v1/canonical/original-generation')/path
  if digest(ROOT/path)!=h:raise ValueError('Retained envelope/historical package or exact original identity differs '+rel)
  retained_envelope[path.as_posix()]=h
 result=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),implementation_sha256=digest(Path(__file__)),checked_binding_counts=checked,completion_path=(PUB/'completion.json').as_posix(),completion_sha256=digest(ROOT/PUB/'completion.json'),publication_files=publications,later_coordinator_corroboration=dict(path=root_review.relative_to(ROOT).as_posix(),sha256=digest(root_review),status='pass',qualification='Coordinator proof was added after private before-map capture; separately bound here without rerunning closed pipeline gates.'),all_current_bound_hashes_equal=True,public_checker_negative_cases=cases,complete_negative_proof_sha256=digest(OUT/'independent-projection-linkage.json'),private_offline=True,public_publication_performed=False)
 result.update(current_source_manifest_sha256=digest(manifest_path),retained_source_manifest_authorities_verified=source_authorities,retained_envelope_original_inputs_verified=retained_envelope,retained_envelope_files=58,historical_candidate_members=8,acquired_identity_binding_qualification="Exact pre-category work identity is verified from guarded original generation; authorized category prerequisite is separately journaled, without resealing historical manifest.")
 save(OUT/'final-delivery-audit.json',result);print(json.dumps(dict(status='pass',completion_sha256=result['completion_sha256'],checked_counts=checked,source_authority_bindings=len(source_authorities),final_audit_sha256=digest(OUT/'final-delivery-audit.json'))))
if __name__=='__main__':main()
