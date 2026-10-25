"""Renew Joshua's oracle contract without changing any producer payload."""
from hashlib import sha256
import json
from pathlib import Path
from build.tei.blaikie_joshua_retained_native_prepare import ROOT,LOG,SOURCE_DIR,canonical,_convert
from build.tei.blaikie_joshua_retained_native_oracle import _oracle,import_closure,check
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,reconstruct,validate

MEMBER='blaikie-expositorjosh'
BASE=Path('D:/Library/Open Christian Data/candidate-reviews')

def main():
 manifest_path=SOURCE_DIR/(MEMBER+'.source-manifest-v3.json')
 destination=BASE/'blaikie-joshua-existing-readable-20261003-v3'/MEMBER/'package'
 output=ROOT/LOG/'initial-native-baseline-v3.json'
 if (ROOT/manifest_path).exists() or destination.parent.exists() or output.exists():raise FileExistsError('Preserve Joshua contract generations')
 old_path=SOURCE_DIR/(MEMBER+'.source-manifest-v2.json')
 old_raw=(ROOT/old_path).read_bytes()
 if sha256(old_raw).hexdigest()!='d37d5515aa2a1d24de77f0a055c08b0a399025b856fac30ffc0d9abe001e12dc':raise ValueError('Preserved source contract differs')
 record=json.loads(old_raw)
 for a in record['authorities']:
  raw=(ROOT/a['path']).read_bytes()
  if a['path']=='build/tei/blaikie_joshua_retained_native_oracle.py':a.update(bytes=len(raw),sha256=sha256(raw).hexdigest())
  elif a['bytes']!=len(raw) or a['sha256']!=sha256(raw).hexdigest():raise ValueError('Unexpected authority drift '+a['path'])
 record['validator']['implementation_sha256']=sha256((ROOT/'build/tei/blaikie_joshua_retained_native_oracle.py').read_bytes()).hexdigest()
 record['validator']['import_closure_sha256']=import_closure()
 (ROOT/manifest_path).write_bytes(canonical(record))
 source=SourceManifest.load(ROOT/manifest_path,repository_root=ROOT)
 destination.parent.mkdir(parents=True)
 package=reconstruct(source,destination,_convert);report=validate(source,package,_oracle)
 previous=CandidatePackage.load(BASE/'blaikie-joshua-existing-readable-20261003-v2'/MEMBER/'package')
 if previous.sha256!='221fcf5da01b75f333079f984b926e3926495970736d83556d4b46a4bf3472f6':raise ValueError('Preserved package differs')
 for name in package.member_names:
  if name!='manifest.json' and package.member_bytes(name)!=previous.member_bytes(name):raise ValueError('Renewal changed source payload '+name)
 result=dict(status='baseline-pass',complete_authored_works=1,source_members=1,work_id=record['work_id'],member_id=MEMBER,
  source_manifest_path=manifest_path.as_posix(),source_manifest_sha256=source.sha256,package_path=package.path.as_posix(),package_sha256=package.sha256,
  oracle_report_sha256=report.sha256,direct_source_review=check(MEMBER,package.path),
  renewal=dict(previous_source_manifest_sha256=sha256(old_raw).hexdigest(),previous_package_sha256=previous.sha256,
   all_five_producer_payloads_byte_unchanged=True,reason='Exact source/work/package identity, ordered authority roles and source-order oracle guards; result scope wording'),canonical_mutation=False,no_download=True)
 output.write_bytes(canonical(result));print(json.dumps({k:v for k,v in result.items() if k not in {'direct_source_review','renewal'}},sort_keys=True))

if __name__=='__main__':main()
