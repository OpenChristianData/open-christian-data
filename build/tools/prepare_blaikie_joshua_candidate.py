"""Package the one existing complete authored Joshua work, without installation."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlsplit
from lxml import etree
from build.tei.blaikie_joshua_retained_native_prepare import ROOT,LOG,SOURCE_DIR,WORK_ID,SPECS,MEMBERS,OLD_PACKAGE,convert,_convert,canonical
from build.tei.blaikie_joshua_retained_native_oracle import ORACLE_IMPORTS,PRODUCER_IMPORTS,import_closure,_oracle,check
from ocd_kernel.reconstruction import SourceManifest,reconstruct,validate

MEMBER='blaikie-expositorjosh'
CANDIDATES=Path('D:/Library/Open Christian Data/candidate-reviews/blaikie-joshua-existing-readable-20261003-v1')

def sha(raw):return sha256(raw).hexdigest()
def authority(name,path,role):
 raw=(ROOT/path).read_bytes();return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(raw),sha256=sha(raw))
def put(path,raw):
 target=ROOT/path
 if target.exists():raise FileExistsError('Preserve Joshua source contract '+str(path))
 target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)

def prepare():
 if CANDIDATES.exists():raise FileExistsError('Preserve Joshua candidate generation')
 spec=SPECS[MEMBER];payload=convert(MEMBER);raw=(ROOT/spec['path']).read_bytes()
 source=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False));body=source.find('ThML.body')
 body_ids={n.get('id') for n in body.iter() if isinstance(n.tag,str) and n.get('id')}
 missing=[dict(source_id=n.get('id'),attribute=k,target=n.get(k)) for n in body.iter() if isinstance(n.tag,str) for k in ('next','prev') if n.get(k) and n.get(k) not in body_ids]
 relative=[dict(href=n.get('href'),source_id=n.get('id'),source_base=spec['source_base_url']) for n in body.iter() if n.tag=='a' and n.get('href') and not n.get('href').startswith('#') and not urlsplit(n.get('href')).scheme]
 profile=SOURCE_DIR/(MEMBER+'.profile.json');policy=SOURCE_DIR/(MEMBER+'.policy.json');readme=SOURCE_DIR/(MEMBER+'.README.source.md')
 producer_closure=import_closure('build.tei.blaikie_joshua_retained_native_prepare');oracle_closure=import_closure()
 profile_record=dict(contract='ocd-blaikie-joshua-complete-retained-volume-profile-v1',member_id=MEMBER,work_id=WORK_ID,source=spec,
  source_body_c14n_sha256=sha(etree.tostring(body,method='c14n',with_comments=True)),source_head_c14n_sha256=sha(etree.tostring(source.find('ThML.head'),method='c14n',with_comments=True)),literal_document_prefix_sha256=sha(raw[:raw.index(b'<ThML')]),
  body_tags=dict(Counter(n.tag for n in body.iter() if isinstance(n.tag,str))),front=list(MEMBERS[MEMBER][1]),back=list(MEMBERS[MEMBER][2]),acquired_work_volumes=1,complete_authored_works=1,
  producer_import_closure_sha256=producer_closure,producer_imports=list(PRODUCER_IMPORTS),oracle_imports=list(ORACLE_IMPORTS),genre='commentary',scope='complete authored Joshua; inherited author catalog and series excluded',graphics='No source image elements; no pixels acquired or inferred',
  adaptations='Raw readings and source attributes; independently reversible administrative-comment whitespace joins; original query URI contexts; source-level heading paragraphs; full primary head and document prefix visible',relative_links=relative,missing_next_prev=missing,historical_corrections=[],region_owner='Joshua owns title page, all authored chapters including introduction, and all generated indexes; no Samuel content',comment_classes=dict(Counter(n.text for n in body.iter() if n.tag is etree.Comment)))
 policy_record=dict(contract='ocd-blaikie-joshua-independent-readable-policy-v1',member_id=MEMBER,
  independent='stdlib raw traversal/mapping and actual TEI comparison; all strict lxml raw fields corroborated; no producer or emitter import supplies expectations',prior_exposure='Bennett producer/checker and First Samuel historical-carrier checker inspected as separate maintained ancestors; not blind review',
  required=['exact acquired bytes and URL','full actual native fields/parent/order/attachment/attributes','all administrative comments and raw-derived whitespace joins','entire actual-TEI-backed source body inverse','all raw primary header/prolog/XML prefix fields visible and accounted','all40 source relative URI contexts','complete qualified legacy graph reconciliation','P5','valid semantic mutations','two fresh six-member byte replays','strict fresh producer/oracle import closure'],
  patterns=['RP-03','RP-04','RP-06','RP-11','RP-13','RP-14','RP-15'],visual='not performed; no browser/CSS equivalence or print collation claimed',source_quality='Two exact missing source next/prev toc destinations remain typed unresolved; zero source tables, images or historical correction proposals')
 put(profile,canonical(profile_record));put(policy,canonical(policy_record));put(readme,payload['README.source.md'])
 acq=Path('library/works')/WORK_ID/'forms'/spec['form']/'editions'/spec['edition']/'acquisitions'/(spec['acquisition']+'.json')
 authorities=[authority('retained-thml',spec['path'],'primary-source'),authority('volume-profile',profile,'complete-source-feature-profile'),authority('volume-policy',policy,'independent-validation-policy'),authority('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),authority('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema'),authority('source-local-attribution-readme',readme,'source-rights-attribution'),authority('ccel-permission','sources/commentaries/expositors-bible/ccel-permission.md','source-rights-evidence'),authority('original-source-credit','data/commentaries/expositors-bible/README.md','historical-source-credit'),authority('scope-recovery',LOG/'retained-scope-reconciliation.json','existing-candidate-recovery-evidence'),authority('source-preflight',LOG/'source-inventory-read-only-preflight.json','complete-work-boundary-evidence'),authority('primary-acquired-url-context',acq,'primary-source-url-context'),authority('frozen-emitter-ancestor','build/tei/ccel_retained_native_emitter.py','reviewed-emitter-ancestor'),authority('legacy-actual-checker','build/tei/blaikie_joshua_legacy_oracle.py','independent-legacy-source-graph-checker')]
 authorities.extend(authority('schema-import-'+p.stem,p.relative_to(ROOT),'source-validation-schema-import') for p in sorted((ROOT/'ocd_kernel/tei/vendor/xsd').glob('*.xsd')) if p.name!='tei_all.xsd')
 authorities.extend(authority('import-'+str(i),p,'observed-first-party-import-dependency') for i,p in enumerate(sorted(set(ORACLE_IMPORTS+PRODUCER_IMPORTS))))
 authorities.extend(authority('replay-'+name,OLD_PACKAGE/name,'qualified-current-aggregate-replay-lineage') for name in ['README.source.md','content.tei.xml','manifest.json','provenance.json','source-accountability.json','unresolved.jsonl'])
 authorities.extend([authority('historical-profile','sources/commentaries/expositors-bible/lib036.reconstruction-profile.json','historical-correction-profile'),authority('replay-receipt',LOG/'qualified-current-lib036-replay-receipt.json','qualified-current-converter-replay-evidence'),authority('replay-source-manifest',SOURCE_DIR/'qualified-lib036-replay.source-manifest.json','qualified-current-converter-only-execution-admission')])
 record=dict(contract='ocd-source-manifest-v1',source_id='ccel-blaikie-joshua-retained-native-'+MEMBER+'-v1',work_id=WORK_ID,ticket_id='37c-167-existing-blaikie-joshua',authorities=authorities,
  converter=dict(id=_convert.converter_id,version=_convert.converter_version,callable='_convert',implementation_path='build/tei/blaikie_joshua_retained_native_prepare.py',implementation_sha256=sha((ROOT/'build/tei/blaikie_joshua_retained_native_prepare.py').read_bytes())),
  validator=dict(id=_oracle.oracle_id,version=_oracle.oracle_version,callable='_oracle',implementation_path='build/tei/blaikie_joshua_retained_native_oracle.py',implementation_sha256=sha((ROOT/'build/tei/blaikie_joshua_retained_native_oracle.py').read_bytes()),import_closure_sha256=oracle_closure),
  package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes())),scope=dict(kind='complete-existing-retained-authored-work',member_id=MEMBER,complete_work_count=1,acquired_work_member_count=1,no_acquisition_or_download=True),source_order=dict(order='complete original source DOM, notes/inline and administrative comment/tail attachment'))
 manifest_path=SOURCE_DIR/(MEMBER+'.source-manifest.json');put(manifest_path,canonical(record));manifest=SourceManifest.load(ROOT/manifest_path,repository_root=ROOT)
 return package_existing_contract()

def package_existing_contract():
 manifest_path=SOURCE_DIR/(MEMBER+'.source-manifest.json')
 manifest=SourceManifest.load(ROOT/manifest_path,repository_root=ROOT)
 destination=CANDIDATES/MEMBER/'package'
 if destination.exists():raise FileExistsError('Preserve Joshua candidate package')
 destination.parent.mkdir(parents=True,exist_ok=True)
 package=reconstruct(manifest,destination,_convert);report=validate(manifest,package,_oracle);direct=check(MEMBER,package.path)
 result=dict(status='baseline-pass',complete_authored_works=1,source_members=1,work_id=WORK_ID,member_id=MEMBER,package_path=package.path.as_posix(),package_sha256=package.sha256,source_manifest_path=manifest_path.as_posix(),source_manifest_sha256=manifest.sha256,oracle_report_sha256=report.sha256,direct_source_review=direct,canonical_mutation=False)
 put(LOG/'initial-native-baseline.json',canonical(result));print(json.dumps({k:v for k,v in result.items() if k!='direct_source_review'},sort_keys=True))

if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--package-existing-contract',action='store_true');args=parser.parse_args()
 package_existing_contract() if args.package_existing_contract else prepare()
