"""Seal three complete Dods candidates from four already retained sources."""
from pathlib import Path
import json, subprocess, sys
from build.tei.dods_complete_prepare import ROOT,LOG,SOURCE_DIR,WORK,WORKS,convert,canonical,sha,_convert
from build.tei.dods_complete_oracle import check,_oracle,import_closure,ORACLE_IMPORTS,PRODUCER_IMPORTS,component_artifacts,expected_policy,boundary_check
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,reconstruct,validate

CANDIDATES=Path('D:/Library/Open Christian Data/candidate-reviews/dods-three-complete-20261003-v2')

def authority(name,path,role):
 raw=(ROOT/path).read_bytes()
 return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(raw),sha256=sha(raw))

def manifests():
 report=boundary_check();closure=import_closure();producer=import_closure('build.tei.dods_complete_prepare');paths={}
 for key,members in WORKS.items():
  payload=convert(key);profile=SOURCE_DIR/(key+'.profile.json');policy=SOURCE_DIR/(key+'.policy.json');readme=SOURCE_DIR/(key+'.README.source.md')
  (ROOT/readme).write_bytes(payload['README.source.md'])
  record=dict(contract='ocd-dods-complete-existing-profile-v1',work_id=WORK,complete_work_id=key,complete_work_count=3,acquired_source_count=4,source_members=list(members),source_component_conservation_sha256=sha((ROOT/LOG/'source-component-conservation.json').read_bytes()),boundary_report_sha256=sha((ROOT/LOG/'complete-work-boundary-report-v2.json').read_bytes()),producer_imports=list(PRODUCER_IMPORTS),oracle_imports=list(ORACLE_IMPORTS),producer_import_closure_sha256=producer,genre='commentary',grouped_source_kind='retained-member-set' if len(members)>1 else 'single-retained-source',components=[dict(member_id=m,source=component_artifacts(m)[1]['source'],files=component_artifacts(m)[1]['files']) for m in members])
  (ROOT/profile).write_bytes(canonical(record));(ROOT/policy).write_bytes(canonical(expected_policy(key)))
  auth=[authority('profile',profile,'complete-source-feature-profile'),authority('policy',policy,'independent-validation-policy'),authority('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),authority('package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema'),authority('source-local-attribution-readme',readme,'source-rights-attribution'),authority('ccel-permission','sources/commentaries/expositors-bible/ccel-permission.md','source-rights-evidence'),authority('source-component-conservation',LOG/'source-component-conservation.json','component-conservation-authority'),authority('complete-work-boundary',LOG/'complete-work-boundary-report-v2.json','complete-work-boundary-authority'),authority('boundary-implementation',LOG/'work_boundary_proposal.py','complete-work-boundary-implementation'),authority('grouped-acquisition-proposal',LOG/'john-grouped-acquisition-proposal-v2.json','derived-grouped-acquisition-authority'),authority('work-append-proposal',LOG/'work-plus-john-group-proposal-v2.json','derived-work-append-authority')]
  binding=report['schema_bound_acquisition']['source_path'] if len(members)>1 else component_artifacts(members[0])[1]['source']['path']
  auth.append(authority('source-binding',binding,'retained-complete-source-binding'))
  for m in members:
   p,entry=component_artifacts(m);s=entry['source'];auth.append(authority('raw-'+m,s['path'],'primary-source'))
   cp=json.loads(p['provenance.json']);auth.append(authority('acquisition-'+m,cp['acquisition_path'],'source-uri-context-authority'))
   auth.extend(authority('component-'+m+'-'+f['name'],Path(entry['directory'])/f['name'],'source-component-conservation-evidence') for f in entry['files'])
  old=LOG/'replayed-lib035-package'
  auth.extend(authority('legacy-'+n,old/n,'historical-replay-evidence') for n in ('content.tei.xml','source-accountability.json','provenance.json','unresolved.jsonl','README.source.md','manifest.json'))
  auth.extend(authority('legacy-'+n,LOG/n,'historical-reconciliation-evidence') for n in ('legacy-replay-receipt.json','source-inventory.json','replay_legacy_lib035.py','reconcile_legacy.py','source_inventory.py'))
  for n in ('lib035.source-manifest.json','lib035.reconstruction-profile.json'):
   auth.append(authority('legacy-'+n,Path('sources/commentaries/expositors-bible')/n,'historical-reconstruction-authority'))
  legacy=json.loads((ROOT/'sources/commentaries/expositors-bible/lib035.source-manifest.json').read_bytes())
  auth.extend(authority('legacy-authority-'+str(i),a['path'],'historical-reconstruction-dependency') for i,a in enumerate(legacy['authorities']))
  auth.extend(authority('legacy-implementation-'+n,'build/tei/'+n+'.py','historical-reconstruction-implementation') for n in ('expositors_bible_lib035_reconstruction','expositors_bible_lib035_oracle'))
  code=sorted(set(ORACLE_IMPORTS+PRODUCER_IMPORTS+('build/tei/dods_retained_native_prepare.py','build/tei/dods_retained_native_emitter.py','build/tei/maclaren_retained_native_prepare.py','build/tei/maclaren_retained_native_emitter.py','build/tei/maclaren_retained_native_oracle.py')))
  auth.extend(authority('implementation-'+str(i),p,'exercised-source-implementation-dependency') for i,p in enumerate(code))
  record=dict(contract='ocd-source-manifest-v1',source_id='ccel-dods-complete-'+key+'-v1',work_id=WORK,ticket_id='37c-160-existing-dods-three-complete-works-four-sources',authorities=auth,converter=dict(id=_convert.converter_id,version=_convert.converter_version,callable='_convert',implementation_path='build/tei/dods_complete_prepare.py',implementation_sha256=sha((ROOT/'build/tei/dods_complete_prepare.py').read_bytes())),validator=dict(id=_oracle.oracle_id,version=_oracle.oracle_version,callable='_oracle',implementation_path='build/tei/dods_complete_oracle.py',implementation_sha256=sha((ROOT/'build/tei/dods_complete_oracle.py').read_bytes()),import_closure_sha256=closure),package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes())),scope=dict(kind='complete-retained-work',complete_work_id=key,complete_work_count=3,acquired_source_count=4,source_members=list(members),no_acquisition_or_download=True),source_order=dict(order='complete retained source DOM; John exactly two ordered volume text envelopes',members=list(members)))
  path=SOURCE_DIR/(key+'.source-manifest.json');(ROOT/path).write_bytes(canonical(record));SourceManifest.load(ROOT/path,repository_root=ROOT);paths[key]=path
 return paths

def prepare():
 paths=manifests();results=[];negative=[];CANDIDATES.mkdir(exist_ok=True)
 for module in ('build.tei.dods_complete_prepare','build.tei.dods_complete_oracle'):
  try:import_closure(module,extra='ocd_kernel.reconstruction.verifier')
  except ValueError as error:negative.append(dict(module=module,unexpected_first_party_import_rejected=True,reason=str(error)))
  else:raise ValueError('Unexpected Dods fresh import admitted')
 for key,path in paths.items():
  source=SourceManifest.load(ROOT/path,repository_root=ROOT);destination=CANDIDATES/key/'package';destination.parent.mkdir(exist_ok=True)
  package=CandidatePackage.load(destination) if destination.exists() else reconstruct(source,destination,_convert)
  report=validate(source,package,_oracle);direct=check(key,destination)
  replays=[]
  for n in (1,2):
   target=CANDIDATES/key/('fresh-replay-'+str(n))
   if target.exists():raise FileExistsError('Preserve existing fresh Dods complete replay')
   process=subprocess.run([sys.executable,'-B','-m','build.tei.dods_complete_prepare',str(target),'--source-manifest',str(ROOT/path)],cwd=ROOT,check=True,capture_output=True,text=True)
   replay=CandidatePackage.load(target)
   if package.sha256!=replay.sha256 or any(package.member_bytes(name)!=replay.member_bytes(name) for name in package.member_names):raise ValueError('Fresh complete six-member Dods replay differs')
   replays.append(dict(number=n,process='fresh-python',exit_code=process.returncode,package_sha256=replay.sha256,exact_six_member_bytes_equal=True))
  row=dict(complete_work_id=key,source_members=list(WORKS[key]),source_manifest_path=path.as_posix(),source_manifest_sha256=source.sha256,package_path=destination.as_posix(),package_sha256=package.sha256,oracle_report=dict(report.attestation),oracle_report_sha256=report.sha256,direct_source_review=direct,reproducibility=replays)
  (ROOT/LOG/(key+'-complete-package-review-v2.json')).write_bytes(canonical(row));results.append(row)
  print(json.dumps(dict(complete_work_id=key,package_sha256=package.sha256,p5='pass',source_inverse='pass',fresh_six_member_replays=2)),flush=True)
 receipt=dict(status='pass',work_id=WORK,complete_work_count=3,acquired_source_count=4,members=results,closure_challenges=negative,implementation_sha256=sha(Path(__file__).read_bytes()),boundary_report_sha256=sha((ROOT/LOG/'complete-work-boundary-report-v2.json').read_bytes()))
 (ROOT/LOG/'complete-package-receipt-v2.json').write_bytes(canonical(receipt))
 return receipt

if __name__=='__main__':prepare()
