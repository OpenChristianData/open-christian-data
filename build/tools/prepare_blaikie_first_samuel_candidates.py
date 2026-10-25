"""Seal one complete First Samuel candidate from its already retained XML."""
from pathlib import Path
from collections import Counter
from hashlib import sha256
import json
import subprocess
import sys
from lxml import etree
from build.tei.blaikie_first_samuel_retained_native_prepare import ROOT,LOG,SOURCE_DIR,WORK,MEMBERS,SPECS,ANCESTORS,SCOPE,convert,canonical,sha,_convert,lineage_bindings
from build.tei.blaikie_first_samuel_retained_native_oracle import check,_oracle,import_closure,ORACLE_IMPORTS,PRODUCER_IMPORTS,expected_policy,CORRECTION_DISPOSITION
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,reconstruct,validate

MEMBER='blaikie-expositor8'
CANDIDATES=Path('D:/Library/Open Christian Data/candidate-reviews/blaikie-first-samuel-complete-20261003-v4')

def authority(name,path,role):
 raw=(ROOT/path).read_bytes()
 return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(raw),sha256=sha(raw))

def seal_manifest():
 (ROOT/SOURCE_DIR).mkdir(exist_ok=True)
 payload=convert(MEMBER);account=json.loads(payload['source-accountability.json']);spec=SPECS[MEMBER]
 raw=(ROOT/spec['path']).read_bytes();source=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True));body=source.find('ThML.body')
 front,back=MEMBERS[MEMBER][1:];producer=import_closure('build.tei.blaikie_first_samuel_retained_native_prepare');closure=import_closure()
 profile=SOURCE_DIR/(MEMBER+'.profile.json');policy=SOURCE_DIR/(MEMBER+'.policy.json');readme=SOURCE_DIR/(MEMBER+'.README.source.md')
 record=dict(contract='ocd-blaikie-first-samuel-existing-readable-profile-v1',member_id=MEMBER,work_id=WORK,source=spec,source_body_c14n_sha256=sha(etree.tostring(body,method='c14n',with_comments=True)),body_tags=dict(Counter(n.tag for n in body.iter() if isinstance(n.tag,str))),front=list(front),back=list(back),root_ids_in_order=[n.get('id') for n in body if isinstance(n.tag,str)],root_disposition=account['root_disposition'],acquired_work_units=1,producer_import_closure_sha256=producer,producer_imports=list(PRODUCER_IMPORTS),oracle_imports=list(ORACLE_IMPORTS),genre='commentary',scope=SCOPE,source_uri_acquisition_path=account['source_uri_acquisition_path'],source_uri_acquisition_sha256=account['source_uri_acquisition_sha256'],source_url=json.loads((ROOT/account['source_uri_acquisition_path']).read_bytes())['url'],source_document_prefix_sha256=account['source_document_prefix_sha256'],missing_source_navigation=account['missing_source_navigation'],historical_correction_count=0,historical_correction_disposition=CORRECTION_DISPOSITION,index_container=[],lineage_bindings=lineage_bindings(),complete_work_count=1,complete_work_id=MEMBER,source_member_count=1,excluded_source_members=['blaikie-expositor2sam','blaikie-expositorjosh'])
 (ROOT/profile).write_bytes(canonical(record));(ROOT/policy).write_bytes(canonical(expected_policy()));(ROOT/readme).write_bytes(payload['README.source.md'])
 auth=[authority('retained-thml',spec['path'],'primary-source'),authority('profile',profile,'complete-source-feature-profile'),authority('policy',policy,'independent-validation-policy'),authority('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),authority('package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema'),authority('source-local-attribution-readme',readme,'source-rights-attribution'),authority('ccel-permission','sources/commentaries/expositors-bible/ccel-permission.md','source-rights-evidence'),authority('source-uri-acquisition',account['source_uri_acquisition_path'],'source-uri-context-authority')]
 auth.extend(authority('lineage-'+str(i),row['path'],'qualified-existing-reconstruction-lineage') for i,row in enumerate(lineage_bindings()))
 code=sorted(set(ORACLE_IMPORTS+PRODUCER_IMPORTS+ANCESTORS+('build/tools/prepare_blaikie_first_samuel_route.py',)))
 auth.extend(authority('implementation-'+str(i),p,'source-implementation-dependency') for i,p in enumerate(code))
 record=dict(contract='ocd-source-manifest-v1',source_id='ccel-blaikie-first-samuel-retained-native-'+MEMBER+'-v1',work_id=WORK,ticket_id='37c-167-existing-blaikie-first-samuel-only',authorities=auth,converter=dict(id=_convert.converter_id,version=_convert.converter_version,callable='_convert',implementation_path='build/tei/blaikie_first_samuel_retained_native_prepare.py',implementation_sha256=sha((ROOT/'build/tei/blaikie_first_samuel_retained_native_prepare.py').read_bytes())),validator=dict(id=_oracle.oracle_id,version=_oracle.oracle_version,callable='_oracle',implementation_path='build/tei/blaikie_first_samuel_retained_native_oracle.py',implementation_sha256=sha((ROOT/'build/tei/blaikie_first_samuel_retained_native_oracle.py').read_bytes()),import_closure_sha256=closure),package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes())),scope=dict(kind='complete-retained-work',member_id=MEMBER,acquired_work_member_count=1,complete_work_count=1,source_member_count=1,excluded_source_members=['blaikie-expositor2sam','blaikie-expositorjosh'],no_acquisition_or_download=True),source_order=dict(order='Complete retained First Samuel source DOM including all title page, chapters I-XXXVI and indexes',members=[MEMBER]))
 path=SOURCE_DIR/(MEMBER+'.source-manifest.json');(ROOT/path).write_bytes(canonical(record));return SourceManifest.load(ROOT/path,repository_root=ROOT)

def prepare():
 source=seal_manifest();negative=[]
 for module in ('build.tei.blaikie_first_samuel_retained_native_prepare','build.tei.blaikie_first_samuel_retained_native_oracle'):
  try:import_closure(module,extra_import='ocd_kernel.reconstruction.verifier')
  except ValueError as error:negative.append(dict(module=module,unexpected_first_party_import_rejected=True,reason=str(error)))
  else:raise ValueError('Unexpected fresh import admitted')
 destination=CANDIDATES/'package';CANDIDATES.mkdir(exist_ok=True)
 package=CandidatePackage.load(destination) if destination.exists() else reconstruct(source,destination,_convert)
 report=validate(source,package,_oracle);direct=check(MEMBER,destination);replays=[]
 for n in (1,2):
  target=CANDIDATES/('fresh-replay-'+str(n))
  if target.exists():raise FileExistsError('Preserve existing fresh replay')
  process=subprocess.run([sys.executable,'-B','-m','build.tei.blaikie_first_samuel_retained_native_prepare',str(target),'--source-manifest',str(ROOT/SOURCE_DIR/(MEMBER+'.source-manifest.json'))],cwd=ROOT,check=True,capture_output=True,text=True)
  replay=CandidatePackage.load(target)
  if package.sha256!=replay.sha256 or any(package.member_bytes(name)!=replay.member_bytes(name) for name in package.member_names):raise ValueError('Fresh six-member replay differs')
  replays.append(dict(number=n,process='fresh-python',exit_code=process.returncode,package_sha256=replay.sha256,exact_six_member_bytes_equal=True))
 receipt=dict(status='pass',work_id=WORK,complete_work_count=1,source_member_count=1,member_id=MEMBER,source_manifest_path=(SOURCE_DIR/(MEMBER+'.source-manifest.json')).as_posix(),source_manifest_sha256=source.sha256,package_path=destination.as_posix(),package_sha256=package.sha256,oracle_report=dict(report.attestation),oracle_report_sha256=report.sha256,direct_source_review=direct,reproducibility=replays,closure_challenges=negative,implementation_sha256=sha(Path(__file__).read_bytes()))
 (ROOT/LOG/'complete-package-receipt-v4.json').write_bytes(canonical(receipt))
 (ROOT/LOG/(MEMBER+'-complete-package-review-v4.json')).write_bytes(canonical(receipt))
 print(json.dumps(dict(status='pass',package_sha256=package.sha256,source_manifest_sha256=source.sha256,p5='pass',source_inverse='pass',fresh_six_member_replays=2)))
 return receipt

if __name__=='__main__':prepare()
