"""Independent whole-document oracle: three complete Dods works, four raw sources.

Prior exposure to the component mapping is declared. The established independent
stdlib raw/source oracle checks every actual source reading, field and inverse.
This checker additionally verifies actual serialized grouping, complete metadata,
global identities, all source authority and the three-work/four-source boundary.
No producer or emitter is imported.
"""
from pathlib import Path
from hashlib import sha256
from copy import deepcopy
from functools import lru_cache
from tempfile import TemporaryDirectory
import json,subprocess,sys
import xml.etree.ElementTree as ET
from lxml import etree
from ocd_kernel.reconstruction import CandidatePackage,SourceManifest
from ocd_kernel.reconstruction.contract import _canonical,_runtime_binding,_validation_authority_bindings
from ocd_kernel.library.acquisitions import source_member_set_bytes
from ocd_kernel.library.identities import validate_record
from build.tei.dods_retained_native_oracle import check as source_check,SOURCES,SCOPE,LEGACY,CORRECTION_DISPOSITION,_p5_schema

ROOT=Path(__file__).resolve().parents[2]
LOG=Path('reports/_logs/dods-existing-install-20261003-v1')
WORK='expositors-bible--marcus-dods'
WORKS={'dods-genesis':('dods-expositor1',),'dods-first-corinthians':('dods-expositor1cor',),'dods-gospel-john':('dods-expositorjohn1','dods-expositorjohn2')}
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'
ORACLE_IMPORTS=tuple('''build/__init__.py build/tei/__init__.py build/tei/dods_complete_oracle.py build/tei/dods_retained_native_oracle.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/library/__init__.py ocd_kernel/library/_common.py ocd_kernel/library/acquisitions.py ocd_kernel/library/identities.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py'''.split())
PRODUCER_IMPORTS=tuple('''build/__init__.py build/tei/__init__.py build/tei/dods_complete_prepare.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py ocd_kernel/tei/__init__.py ocd_kernel/tei/normalization.py ocd_kernel/tei/projection_profile.py ocd_kernel/tei/writer.py'''.split())
def sha(raw):return sha256(raw).hexdigest()
def fields(root):return [(n.tag,dict(n.attrib),n.text or '',n.tail or '',len(n)) for n in root.iter()]

def observed_imports(module,extra=None):
 script='''import importlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve(strict=True);sys.path.insert(0,str(root));before=set(sys.modules)
importlib.import_module(sys.argv[2])
if len(sys.argv)>3:importlib.import_module(sys.argv[3])
print(json.dumps(sorted({Path(m.__file__).resolve().relative_to(root).as_posix() for name,m in sys.modules.copy().items() if name not in before and getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(root)})))'''
 args=[sys.executable,'-I','-B','-c',script,str(ROOT),module]
 if extra:args.append(extra)
 return json.loads(subprocess.run(args,check=True,capture_output=True,text=True).stdout)
def import_closure(module='build.tei.dods_complete_oracle',extra=None):
 paths=observed_imports(module,extra);expected=ORACLE_IMPORTS if module.endswith('_oracle') else PRODUCER_IMPORTS
 if not expected or tuple(paths)!=expected:raise ValueError('Dods complete-work first-party imports differ: '+repr(paths))
 return sha(_canonical([dict(path=p,sha256=sha((ROOT/p).read_bytes())) for p in paths]))

def component_artifacts(member):
 record=json.loads((ROOT/LOG/'source-component-conservation.json').read_bytes())
 if record['status']!='pass' or record['source_count']!=4 or record['complete_work_count']!=3:raise ValueError('Component conservation denominator differs')
 entry=next(r for r in record['members'] if r['member_id']==member)
 filename,pin,_,_,count=SOURCES[member];raw=(ROOT/'raw/ccel/expositors-bible'/filename).read_bytes()
 tree=ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)));body=tree.find('ThML.body')
 expected_source=dict(path='raw/ccel/expositors-bible/'+filename,sha256=pin,bytes=len(raw),elements=count,body_elements=sum(isinstance(n.tag,str) for n in body.iter()),comments=sum(n.tag is ET.Comment for n in body.iter()),form=WORK+'--'+member+'--retained-en',edition=WORK+'--'+member+'--ccel-electronic',acquisition=WORK+'--'+member+'--acquired')
 if sha(raw)!=pin or entry['source']!=expected_source:raise ValueError('Independent component source identity/counts differ')
 for pin in record['codepins']:
  if sha((ROOT/pin['path']).read_bytes())!=pin['sha256']:raise ValueError('Component exercised code drifted')
 files={r['name']:(ROOT/entry['directory']/r['name']).read_bytes() for r in entry['files']}
 if set(files)!={'content.tei.xml','source-accountability.json','provenance.json','README.source.md','unresolved.jsonl'}:raise ValueError('Component artifact set differs')
 for pin in entry['files']:
  if len(files[pin['name']])!=pin['bytes'] or sha(files[pin['name']])!=pin['sha256']:raise ValueError('Component artifact bytes differ')
 return files,entry

def boundary_check():
 report=json.loads((ROOT/LOG/'complete-work-boundary-report-v2.json').read_bytes())
 if report['status']!='pass' or report['complete_work_count']!=3 or report['acquired_source_count']!=4 or [(r['complete_work_id'],tuple(r['source_members'])) for r in report['classification']]!=list(WORKS.items()):raise ValueError('Complete-work boundary denominator/order differs')
 for position,member in enumerate(WORKS['dods-gospel-john'],1):
  filename,pin,*_=SOURCES[member];raw=(ROOT/'raw/ccel/expositors-bible'/filename).read_bytes()
  if sha(raw)!=pin:raise ValueError('Complete John raw source differs')
  tree=ET.fromstring(raw);head=tree.find('ThML.head');front=tree.find('ThML.body/div1');r=report['john_primary_boundary'][position-1]
  form=WORK+'--'+member+'--retained-en';edition=WORK+'--'+member+'--ccel-electronic';acq=WORK+'--'+member+'--acquired';ap=Path('library/works')/WORK/'forms'/form/'editions'/edition/'acquisitions'/(acq+'.json');araw=(ROOT/ap).read_bytes();a=json.loads(araw)
  texts=[dict(tag=n.tag,attributes=dict(n.attrib),text=''.join(n.itertext())) for n in front.iter() if isinstance(n.tag,str) and n.tag in {'h1','h2','h3','h4','p'}]
  expected=dict(member_id=member,position=position,source_path='raw/ccel/expositors-bible/'+filename,source_sha256=pin,source_bytes=len(raw),source_title=head.findtext('.//DC.Title'),source_print_statement=head.findtext('.//published'),source_url=a['url'],primary_two_volume_fields=[n for n in texts if 'IN TWO VOLUMES' in n['text'].upper()],primary_volume_label_fields=[n for n in texts if ('VOL. I.' if position==1 else 'VOL. II.') in n['text'].upper()],original_acquisition_path=ap.as_posix(),original_acquisition_sha256=sha(araw),original_acquisition_id=acq)
  if r!=expected or not expected['primary_two_volume_fields'] or not expected['primary_volume_label_fields']:raise ValueError('Primary two-volume John boundary differs')
 a=report['schema_bound_acquisition'];validate_record('acquisition',a,context='complete John source authority')
 mraw=(ROOT/a['source_path']).read_bytes()
 if a.get('source_kind')!='retained-member-set' or mraw!=source_member_set_bytes(a) or sha(mraw)!=a['source_sha256'] or len(mraw)!=a['source_bytes']:raise ValueError('Complete John ordered member-set authority differs')
 if [(r['path'],r['sha256'],r['bytes']) for r in a['retained_files']]!=[(r['source_path'],r['source_sha256'],r['source_bytes']) for r in report['john_primary_boundary']]:raise ValueError('John grouped sources/order differ')
 if a['url']!=report['john_primary_boundary'][0]['source_url'] or len(a['retained_files'])!=2 or not all(r.get('scope') for r in a['retained_files']):raise ValueError('John entry URL/scopes differ')
 return report

def expected_component_provenance(member):
 filename,pin,_,_,_=SOURCES[member];raw=(ROOT/'raw/ccel/expositors-bible'/filename).read_bytes();head=ET.fromstring(raw).find('ThML.head')
 form=WORK+'--'+member+'--retained-en';edition=WORK+'--'+member+'--ccel-electronic';aid=WORK+'--'+member+'--acquired';ap=Path('library/works')/WORK/'forms'/form/'editions'/edition/'acquisitions'/(aid+'.json');araw=(ROOT/ap).read_bytes();a=json.loads(araw)
 old=LOG/'replayed-lib035-package';paths=[old/n for n in ('content.tei.xml','source-accountability.json','provenance.json','unresolved.jsonl','README.source.md','manifest.json')]+[LOG/n for n in ('legacy-replay-receipt.json','source-inventory.json','replay_legacy_lib035.py','reconcile_legacy.py')]+[Path('sources/commentaries/expositors-bible/lib035.reconstruction-profile.json'),Path('sources/commentaries/expositors-bible/lib035.source-manifest.json')]
 rows=[r for r in json.loads((ROOT/'sources/commentaries/expositors-bible/lib035.reconstruction-profile.json').read_bytes())['text_corrections'] if r['member_id']==member]
 return dict(contract='ocd-dods-composite-provenance-v1',status='nonaccepted',work_id=WORK,member_id=member,source_path='raw/ccel/expositors-bible/'+filename,source_sha256=pin,source_bytes=len(raw),scope=SCOPE,source_title=head.findtext('.//DC.Title'),source_print_statement=head.findtext('.//published'),source_url=a['url'],form_id=form,edition_id=edition,acquisition_id=aid,acquisition_path=ap.as_posix(),acquisition_sha256=sha(araw),source_document_prefix_sha256=sha(raw[:raw.index(b'<ThML')]),legacy_basis=LEGACY,lineage_bindings=[dict(path=p.as_posix(),bytes=len((ROOT/p).read_bytes()),sha256=sha((ROOT/p).read_bytes())) for p in paths],historical_accounting_pin_exact=True,historical_tei_pin_exact=False,historical_correction_disposition=CORRECTION_DISPOSITION,historical_correction_count=len(rows),producer_recipe_sha256=sha((ROOT/'build/tei/dods_retained_native_prepare.py').read_bytes()),emitter_sha256=sha((ROOT/'build/tei/dods_retained_native_emitter.py').read_bytes()),oracle_sha256=sha((ROOT/'build/tei/dods_retained_native_oracle.py').read_bytes()),ancestor_implementation_pins=[dict(path=p,sha256=sha((ROOT/p).read_bytes())) for p in ('build/tei/maclaren_retained_native_emitter.py','build/tei/maclaren_retained_native_prepare.py','build/tei/maclaren_retained_native_oracle.py')],human_acceptance='not_recorded',rights='unresolved',publication='not_ready')

def check(key,directory):
 if key not in WORKS:raise ValueError('Unknown complete Dods work')
 report=boundary_check();classification=next(r for r in report['classification'] if r['complete_work_id']==key)
 raw=(directory/'content.tei.xml').read_bytes();actual=ET.fromstring(raw);lactual=etree.fromstring(raw)
 if actual.tag!=NS+'TEI' or actual.attrib!={XML+'id':key} or (actual.text or '') or (actual.tail or '') or [n.tag for n in actual]!=[NS+'teiHeader',NS+'text']:raise ValueError('Complete candidate outer envelope differs')
 account=json.loads((directory/'source-accountability.json').read_bytes());provenance=json.loads((directory/'provenance.json').read_bytes())
 components={m:component_artifacts(m) for m in WORKS[key]};trees={m:ET.fromstring(p[0]['content.tei.xml']) for m,p in components.items()}
 if len(trees)==1:
  member=WORKS[key][0];expected_header=deepcopy(trees[member].find(NS+'teiHeader'));texts=[actual.find(NS+'text')]
 else:
  first=next(iter(trees.values()));fd0=first.find(NS+'teiHeader/'+NS+'fileDesc');ts0=fd0.find(NS+'titleStmt');title=ts0.findtext(NS+'title').removesuffix(', Volume I')
  expected_header=ET.Element(NS+'teiHeader');fd=ET.SubElement(expected_header,NS+'fileDesc');ts=ET.SubElement(fd,NS+'titleStmt');ET.SubElement(ts,NS+'title').text=title
  for field in ('author','editor'):ET.SubElement(ts,NS+field).text=ts0.findtext(NS+field)
  fd.append(deepcopy(fd0.find(NS+'publicationStmt')));desc=ET.SubElement(fd,NS+'sourceDesc');qual=ET.SubElement(desc,NS+'bibl');ET.SubElement(qual,NS+'note',{'type':'complete-work-scope'}).text=report['schema_bound_acquisition']['source_scope']
  for m,tree in trees.items():
   src=tree.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'sourceDesc');b=deepcopy(src[1]);b.attrib={XML+'id':m+'-source','type':'retained-source-volume'};b.insert(0,deepcopy(src[0][0]));desc.append(b)
  text=actual.find(NS+'text')
  if text.attrib!={XML+'lang':'en'} or (text.text or '') or (text.tail or '') or len(text)!=1:raise ValueError('Complete John text envelope differs')
  group=text[0]
  if group.tag!=NS+'group' or group.attrib!={XML+'id':key+'-volumes'} or (group.text or '') or (group.tail or '') or len(group)!=2:raise ValueError('Complete John group envelope/order/census differs')
  texts=list(group)
 if fields(actual.find(NS+'teiHeader'))!=fields(expected_header):raise ValueError('Complete actual header/per-volume source metadata differs')
 expected_payloads={};component_provenance={};results=[]
 for m,volume in zip(WORKS[key],texts,strict=True):
  payload,entry=components[m];expected_payloads[m]=[dict(name=n,bytes=len(payload[n]),sha256=sha(payload[n])) for n in sorted(payload)];component_provenance[m]=json.loads(payload['provenance.json'])
  if component_provenance[m]!=expected_component_provenance(m):raise ValueError('Complete component source/composite provenance differs')
  if account.get('components',{}).get(m)!=json.loads(payload['source-accountability.json']):raise ValueError('Complete component source accounting differs')
  if len(trees)>1:
   if volume.tag!=NS+'text' or volume.attrib!={XML+'lang':'en',XML+'id':m+'-volume'} or (volume.tail or ''):raise ValueError('Volume source identity/order/envelope differs')
   normalized=deepcopy(volume);del normalized.attrib[XML+'id']
  else:normalized=deepcopy(volume)
  if fields(normalized)!=fields(trees[m].find(NS+'text')):raise ValueError('Serialized actual volume all fields/order differ from conserved source tree')
  # Source checker independently verifies raw readings/inverse of this ACTUAL group slice.
  root=etree.fromstring(payload['content.tei.xml']);root.remove(root.find(NS+'text'))
  lvolume=deepcopy(lactual.find(NS+'text') if len(trees)==1 else lactual.find(NS+'text/'+NS+'group')[list(WORKS[key]).index(m)])
  if len(trees)>1:del lvolume.attrib[XML+'id']
  root.append(lvolume)
  with TemporaryDirectory(prefix='dods-actual-source-component-') as temporary:
   part=Path(temporary)
   if part.resolve().is_relative_to(directory.resolve()):raise ValueError('Source-check scratch is inside immutable candidate')
   for name,value in payload.items():(part/name).write_bytes(value)
   (part/'content.tei.xml').write_bytes(etree.tostring(root,encoding='UTF-8',xml_declaration=True))
   results.append(source_check(m,part))
 expected_account=dict(contract='ocd-dods-complete-work-accounting-v1',work_id=WORK,complete_work_id=key,source_members=list(WORKS[key]),complete_work_count=3,acquired_source_count=4,boundary=classification,components={m:json.loads(p[0]['source-accountability.json']) for m,p in components.items()},component_payloads=expected_payloads,body_disposition='Single-source works retain complete native text. John retains exactly two ordered complete volume text trees; only synthetic volume text XML IDs are added. Serialized actual group is independently checked against both complete raw-source inverses.')
 if account!=expected_account:raise ValueError('Whole complete-work accounting differs')
 expected_prov=dict(contract='ocd-dods-complete-work-provenance-v1',status='nonaccepted',work_id=WORK,complete_work_id=key,source_members=list(WORKS[key]),boundary_report_path=(LOG/'complete-work-boundary-report-v2.json').as_posix(),boundary_report_sha256=sha((ROOT/LOG/'complete-work-boundary-report-v2.json').read_bytes()),producer_recipe_sha256=sha((ROOT/'build/tei/dods_complete_prepare.py').read_bytes()),oracle_sha256=sha(Path(__file__).read_bytes()),component_provenance=component_provenance,component_payloads=expected_payloads,human_acceptance='not_recorded',rights='unresolved',publication='not_ready')
 if provenance!=expected_prov:raise ValueError('Whole complete-work composite provenance differs')
 expected_readme=(f'# Complete retained work: {key}\n\n{classification["boundary"]}\n\nOne candidate TEI represents this complete electronic work. Three complete works account for the four already acquired Dods source files; no new source was acquired. Human acceptance, print collation, rights and publication remain separate.\n\n').encode('utf-8')
 if len(trees)>1:expected_readme+=(report['schema_bound_acquisition']['source_scope']+'\n\nEach volume retains its complete front/body/back tree and distinct source metadata. The original per-volume acquired URLs remain the literal reference bases; no cross-volume destinations are invented.\n\n').encode('utf-8')
 expected_unresolved=b''
 for m,(p,_) in components.items():
  expected_readme+=('## Retained source component: '+m+'\n\n').encode()+p['README.source.md']+b'\n'
  for line in p['unresolved.jsonl'].splitlines():
   row=json.loads(line);row['source_member_id']=m;expected_unresolved+=_canonical(row)
 if (directory/'README.source.md').read_bytes()!=expected_readme or (directory/'unresolved.jsonl').read_bytes()!=expected_unresolved:raise ValueError('Complete attribution/permission or unresolved payload differs')
 ids=[n.get(XML+'id') for n in actual.iter() if n.get(XML+'id')]
 if len(ids)!=len(set(ids)):raise ValueError('Complete global IDs collide')
 for n in actual.iter(NS+'ref'):
  if (n.get('target') or '').startswith('#') and n.get('target')[1:] not in ids:raise ValueError('Complete global local-reference closure differs')
 _p5_schema().assertValid(lactual)
 return dict(status='pass',work_id=WORK,complete_work_id=key,complete_works=3,acquired_sources=4,source_members=list(WORKS[key]),whole_actual_document_fields_pass=True,serialized_volume_conservation_pass=True,all_source_body_inverses_pass=True,global_ids_and_links='pass',p5='pass',components=results,tei_sha256=sha(raw))

def expected_policy(key):
 return dict(contract='ocd-dods-three-complete-independent-policy-v1',work_id=WORK,complete_work_id=key,source_members=list(WORKS[key]),complete_work_count=3,acquired_source_count=4,independence='Prior exposure to component mappings declared. Independent stdlib raw source tree and complete actual serialized TEI fields, full source-body inverse, exact source component conservation, independently reconstructed grouped header and composite provenance. No producer or emitter import.',required=['complete source head/prolog/literal XML declaration and DOCTYPE prefix','exact source-local copyright/CCEL permission and historical witness qualification visible','whole actual root/text/front/body/back envelope including extra-payload rejection','John exactly two ordered complete volume texts and distinct printed imprints','raw source readings and all original attributes, administrative comments and tail joins','relative URI bases from corresponding exact acquisition URLs','global IDs and local-reference closure','P5-valid semantic challenges including same-text wrong attachment','two fresh six-member equality replays'],historical_lineage='Historical accounting hash matches the ticket; replayed TEI hash differs. All 31 John I historical correction rows remain evidence with absent retained witness bytes, not promoted corrected readings.',visual='not performed; source fidelity checks do not assert print collation or typography equivalence')

def _oracle(source:SourceManifest,candidate:CandidatePackage):
 source.verify();candidate.verify_integrity();key=source.record['scope']['complete_work_id'];result=check(key,candidate.path)
 if source.record['work_id']!=WORK or source.record['scope']['complete_work_count']!=3 or source.record['scope']['acquired_source_count']!=4 or tuple(source.record['scope']['source_members'])!=WORKS[key]:raise ValueError('Complete source manifest scope differs')
 if source.record['scope']['kind']!='complete-retained-work' or source.record['scope']['no_acquisition_or_download'] is not True:raise ValueError('Complete source manifest boundary authorization differs')
 if source.record['source_id']!='ccel-dods-complete-'+key+'-v1':raise ValueError('Complete source manifest identity differs')
 primary=[dict(a) for a in source.record['authorities'] if a['role']=='primary-source']
 expected_primary=[dict(name='raw-'+m,path=component_artifacts(m)[1]['source']['path'],role='primary-source',bytes=component_artifacts(m)[1]['source']['bytes'],sha256=component_artifacts(m)[1]['source']['sha256']) for m in WORKS[key]]
 if primary!=expected_primary:raise ValueError('Complete independently expected primary-source authority inventory differs')
 binding_path=boundary_check()['schema_bound_acquisition']['source_path'] if len(WORKS[key])>1 else expected_primary[0]['path']
 binding_raw=(ROOT/binding_path).read_bytes();bindings=[dict(a) for a in source.record['authorities'] if a['name']=='source-binding']
 if bindings!=[dict(name='source-binding',path=binding_path,role='retained-complete-source-binding',bytes=len(binding_raw),sha256=sha(binding_raw))]:raise ValueError('Complete separate acquisition source-binding authority differs')
 converter=dict(id='ocd-dods-three-complete-existing-works-to-tei',version='1',callable='_convert',implementation_path='build/tei/dods_complete_prepare.py',implementation_sha256=sha((ROOT/'build/tei/dods_complete_prepare.py').read_bytes()))
 if dict(source.record['converter'])!=converter or candidate.manifest['status']!='nonaccepted' or dict(candidate.manifest['converter'])!=converter or candidate.manifest['source_id']!=source.record['source_id']:raise ValueError('Complete candidate status/converter/source binding differs')
 if dict(candidate.manifest['source_manifest'])!=dict(path=source.path.relative_to(ROOT).as_posix(),sha256=source.sha256):raise ValueError('Complete candidate source-manifest binding differs')
 if json.loads(source.authority_path('policy').read_bytes())!=expected_policy(key):raise ValueError('Complete independent validation policy contents differ')
 if candidate.member_bytes('README.source.md')!=source.authority_path('source-local-attribution-readme').read_bytes():raise ValueError('Complete source-local attribution authority differs')
 profile=json.loads(source.authority_path('profile').read_bytes())
 expected=dict(contract='ocd-dods-complete-existing-profile-v1',work_id=WORK,complete_work_id=key,complete_work_count=3,acquired_source_count=4,source_members=list(WORKS[key]),source_component_conservation_sha256=sha((ROOT/LOG/'source-component-conservation.json').read_bytes()),boundary_report_sha256=sha((ROOT/LOG/'complete-work-boundary-report-v2.json').read_bytes()),producer_imports=list(PRODUCER_IMPORTS),oracle_imports=list(ORACLE_IMPORTS),producer_import_closure_sha256=import_closure('build.tei.dods_complete_prepare'),genre='commentary',grouped_source_kind='retained-member-set' if len(WORKS[key])>1 else 'single-retained-source',components=[dict(member_id=m,source=component_artifacts(m)[1]['source'],files=component_artifacts(m)[1]['files']) for m in WORKS[key]])
 if profile!=expected:raise ValueError('Complete independent source profile/counts/roles/closures differs')
 binding=dict(status='pass',oracle_id=_oracle.oracle_id,oracle_version=_oracle.oracle_version,implementation_sha256=sha(Path(__file__).read_bytes()),import_closure_sha256=import_closure(),runtime=_runtime_binding(),source_manifest_sha256=source.sha256,candidate_sha256=candidate.sha256,profile_sha256=sha(source.authority_path('profile').read_bytes()),package_schema_sha256=sha(source.authority_path('package-schema').read_bytes()),source_sha256=_validation_authority_bindings(source)['source_sha256'],xsd_sha256=sha(source.authority_path('tei-p5-xsd').read_bytes()),policy_sha256=sha(source.authority_path('policy').read_bytes()),findings=[json.dumps(result,sort_keys=True)])
 binding['result_sha256']=sha(_canonical(binding));return binding
_oracle.oracle_id='ocd-dods-three-complete-existing-works-independent-oracle'
_oracle.oracle_version='1'
