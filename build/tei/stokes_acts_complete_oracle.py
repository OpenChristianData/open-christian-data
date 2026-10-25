"""Raw-backed checks of one actual Stokes group and all per-volume metadata.

Prior exposure to the legacy source mapping is declared. The independently
reviewed legacy oracle checks actual extracted native payloads against raw;
this oracle additionally derives grouping, URL repairs, and complete headers
from raw sources, and compares the complete serialized outer envelope.
"""
from copy import deepcopy
from hashlib import sha256
import json,subprocess,sys
from pathlib import Path
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from lxml import etree
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage
from ocd_kernel.reconstruction.contract import _canonical,_runtime_binding,_validation_authority_bindings
from ocd_kernel.library.acquisitions import load_acquisition,source_member_set_bytes
from build.tei.stokes_retained_completion_oracle import check as raw_check

ROOT=Path(__file__).resolve().parents[2]
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'
MEMBERS=('stokes-expositoracts1','stokes-expositoracts2');WORK='expositors-bible--g-t-stokes'
TITLE="The Expositor's Bible: The Acts of the Apostles"
STATUS='Nonaccepted complete authored Acts commentary containing both already acquired Stokes volumes in source order. Legacy accepted volumes remain unchanged. Human review, print collation, rights and publication remain separate.'
BOUNDARY='One authored Acts commentary in two volumes by G.T. Stokes. Volume I Preface defines the early narrative before Paul conversion/Cornelius; Volume II Preface explicitly terminates the survey and describes this volume together with the previous one. Complete source titles, common author/editor, contents and ordered volume envelopes establish one work. Chapters and per-volume indexes are parts; The Expositors Bible is the surrounding series. No entire-author or series completeness claim.'
IMPORTS=tuple('''build/__init__.py build/tei/__init__.py build/tei/stokes_acts_complete_oracle.py build/tei/stokes_retained_completion_oracle.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/library/__init__.py ocd_kernel/library/_common.py ocd_kernel/library/acquisitions.py ocd_kernel/library/identities.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py ocd_kernel/reconstruction/verifier.py'''.split())
PRODUCER_IMPORTS=tuple('''build/__init__.py build/tei/__init__.py build/tei/stokes_acts_complete_prepare.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py ocd_kernel/tei/__init__.py ocd_kernel/tei/normalization.py ocd_kernel/tei/projection_profile.py ocd_kernel/tei/writer.py'''.split())

def sha(raw):return sha256(raw).hexdigest()
def fields(node):return [(n.tag,dict(n.attrib),n.text,n.tail,len(n)) for n in node.iter()]
def closure(module='build.tei.stokes_acts_complete_oracle',extra=None):
 script='''import importlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve(strict=True);sys.path.insert(0,str(root));before=set(sys.modules)
importlib.import_module(sys.argv[2])
if len(sys.argv)>3:importlib.import_module(sys.argv[3])
print(json.dumps(sorted({Path(m.__file__).resolve().relative_to(root).as_posix() for n,m in sys.modules.copy().items() if n not in before and getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(root)})))'''
 args=[sys.executable,'-I','-B','-c',script,str(ROOT),module]
 if extra:args.append(extra)
 observed=json.loads(subprocess.run(args,check=True,capture_output=True,text=True).stdout)
 if tuple(observed)!=(IMPORTS if module.endswith('_oracle') else PRODUCER_IMPORTS):raise ValueError('Stokes complete observed import inventory differs: '+repr(observed))
 return sha(_canonical([dict(path=p,sha256=sha((ROOT/p).read_bytes())) for p in observed]))

def check(source,candidate):
 source.verify();candidate.verify_integrity()
 if candidate.manifest['status']!='nonaccepted' or candidate.manifest['converter']!=source.record['converter']:raise ValueError('Complete candidate converter/status differs')
 profile=json.loads(source.authority_path('complete-profile').read_bytes());policy=json.loads(source.authority_path('complete-policy').read_bytes())
 expected_policy=dict(contract='ocd-stokes-acts-complete-policy-v1',ordered_members=list(MEMBERS),complete_works=1,acquired_volumes=2,actual_group_and_raw_inverse=True,exact_metadata=True,uri_base_addition_only=True,no_acquisition=True,oracle_imports=list(IMPORTS),producer_imports=list(PRODUCER_IMPORTS))
 if policy!=expected_policy or profile['ordered_members']!=list(MEMBERS) or profile['complete_works']!=1 or profile['source_volumes']!=2:raise ValueError('Complete policy/profile denominator differs')
 if set(profile)!={'contract','complete_works','source_volumes','ordered_members','title','boundary','volumes','canonical_before'} or profile['contract']!='ocd-stokes-acts-complete-profile-v1' or profile['title']!=TITLE or profile['boundary']!=BOUNDARY:raise ValueError('Exact complete-work boundary/profile envelope differs')
 inherited={a['name']:a for a in source.record['authorities'] if a['role']=='unchanged-inherited-work-authority'}
 if len(profile['canonical_before'])!=44 or len(inherited)!=44:raise ValueError('Complete immutable legacy authority set differs')
 for ordinal,(relative,digest) in enumerate(sorted(profile['canonical_before'].items())):
  authority=inherited['inherited-file-'+str(ordinal)]
  expected_path='sources/commentaries/expositors-bible/stokes-acts-complete-20261003-v2/legacy-'+relative if relative in {'work.json','state.json'} else 'library/works/'+WORK+'/'+relative
  if authority['path']!=expected_path or authority['sha256']!=digest:raise ValueError('Exact legacy before-table binding differs')
 if source.authority_path('acquisition-schema').read_bytes()!=(ROOT/'schemas/v2/acquisition.schema.json').read_bytes():raise ValueError('Current acquisition schema binding differs')
 proposed=load_acquisition(source.authority_path('proposed-acquisition'));descriptor_bytes=source.authority_path('proposed-member-set').read_bytes()
 if descriptor_bytes!=source_member_set_bytes(proposed):raise ValueError('Independent exact descriptor byte binding differs')
 form=WORK+'--acts-complete-retained-en';edition=WORK+'--acts-complete-ccel-electronic';acquisition_id=WORK+'--acts-complete-retained-member-set'
 descriptor_path='library/works/'+WORK+'/forms/'+form+'/editions/'+edition+'/source-member-set.json'
 urls=['https://www.ccel.org/ccel/stokes/expositoracts'+str(number)+'.html' for number in (1,2)]
 if proposed['acquisition_id']!=acquisition_id or proposed['edition_id']!=edition or proposed['source_path']!=descriptor_path or proposed['provider']!='CCEL' or proposed['route']!='born-digital' or proposed['url']!=urls[0]:raise ValueError('Exact derived acquired member-set identity/entry URL differs')
 url_warning='Derived entry URL is the original Volume I acquired URL; member URLs in source order: '+', '.join(urls)+'. No provider entry URL or download is invented.'
 if url_warning not in proposed['warnings']:raise ValueError('Exact both-member URL qualification differs')
 if proposed['source_kind']!='retained-member-set' or len(proposed['retained_files'])!=2 or proposed['source_sha256']!=sha(source.authority_path('proposed-member-set').read_bytes()) or proposed['source_bytes']!=len(source.authority_path('proposed-member-set').read_bytes()):raise ValueError('Complete ordered retained-set proposal differs')
 expected=ET.Element(NS+'TEI',{XML+'id':'stokes-acts-complete-work'});h=ET.SubElement(expected,NS+'teiHeader');fd=ET.SubElement(h,NS+'fileDesc');ts=ET.SubElement(fd,NS+'titleStmt');ET.SubElement(ts,NS+'title').text=TITLE
 raw_tei=candidate.member_bytes('content.tei.xml');actual=ET.fromstring(raw_tei);actual_group=actual.find(NS+'text/'+NS+'group')
 if actual_group is None or len(actual_group)!=2:raise ValueError('One complete Acts work requires exactly two volume text trees')
 primary_sources=[];components=[];packages=[];source_records=[];base_repairs=[];reports=[];metadata_notes=[]
 for ordinal,member in enumerate(MEMBERS,1):
  raw=source.authority_path(member+'-raw').read_bytes();primary=ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)));primary_sources.append(primary)
  if primary.findtext('.//DC.Title')!=TITLE+', Volume '+('I' if ordinal==1 else 'II'):raise ValueError('Raw volume title/order differs')
  preface=''.join(primary.find("ThML.body/div1[@id='ii']").itertext())
  if ordinal==1 and ('down to, but not including' not in preface or 'conversion of St. Paul' not in preface):raise ValueError('Primary opening-volume work boundary differs')
  if ordinal==2 and ('terminates my survey and exposition' not in preface or 'together with the previous one' not in preface):raise ValueError('Primary concluding-volume work boundary differs')
  package=CandidatePackage.load(source.authority_path(member+'-manifest').parent);package.verify_integrity();packages.append(package)
  master_raw=source.authority_path(member+'-master').read_bytes();component=ET.fromstring(master_raw);components.append(component)
  acquisition=json.loads(source.authority_path(member+'-acquisition').read_bytes());expected_url='https://www.ccel.org/ccel/stokes/expositoracts'+str(ordinal)+'.html'
  if acquisition['url']!=expected_url or acquisition['source_sha256']!=sha(raw) or acquisition['source_bytes']!=len(raw):raise ValueError('Exact original acquired source URI/bytes differs')
  retained=proposed['retained_files'][ordinal-1]
  if retained['path']!='raw/ccel/expositors-bible/stokes_expositoracts'+str(ordinal)+'.xml' or retained['sha256']!=sha(raw) or retained['bytes']!=len(raw):raise ValueError('Exact ordered proposed source member differs')
  row=profile['volumes'][ordinal-1]
  if row!=dict(member_id=member,volume=ordinal,raw_sha256=sha(raw),raw_bytes=len(raw),raw_elements=sum(isinstance(n.tag,str) for n in primary.iter()),title=primary.findtext('.//DC.Title'),package_sha256=package.sha256,master_sha256=sha(master_raw),acceptance_sha256=sha(source.authority_path(member+'-acceptance').read_bytes()),acquisition_sha256=sha(source.authority_path(member+'-acquisition').read_bytes()),source_url=expected_url):raise ValueError('Exact raw/installed/profile binding differs')
  legacy_text=component.find(NS+'text');package_text=ET.fromstring(package.member_bytes('content.tei.xml')).find(NS+'text')
  if fields(legacy_text)!=fields(package_text):raise ValueError('Legacy native text/package fields differ')
  volume=deepcopy(legacy_text);volume.set(XML+'id',member+'-volume');native=[n for region in volume for child in region for n in child.iter()]
  body=primary.find('ThML.body');source_nodes=[]
  def walk(parent,path=()):
   for i,n in enumerate(parent):
    p=path+(i,);source_nodes.append((p,n));walk(n,p)
  walk(body);source_elements=[(p,n) for p,n in source_nodes if isinstance(n.tag,str)]
  if len(source_elements)!=len(native):raise ValueError('Raw/native volume feature census differs')
  for (path,node),mapped in zip(source_elements,native,strict=True):
   href=node.get('href')
   if node.tag=='a' and href and not href.startswith('#') and not urlsplit(href).scheme:
    if mapped.tag!=NS+'ref' or mapped.get('target')!=href or mapped.get(XML+'base') is not None:raise ValueError('Raw-relative target/current native carrier differs')
    mapped.set(XML+'base',expected_url);base_repairs.append(dict(member_id=member,source_path=list(path),tei_id=mapped.get(XML+'id'),target=href,base=expected_url))
  if fields(volume)!=fields(actual_group[ordinal-1]):raise ValueError('Actual grouped volume fields/order/URI context differ')
  # Strip only individually source-backed additions from ACTUAL serialized text.
  stripped=deepcopy(actual_group[ordinal-1]);del stripped.attrib[XML+'id'];byid={n.get(XML+'id'):n for n in stripped.iter() if n.get(XML+'id')}
  for repair in base_repairs:
   if repair['member_id']==member:
    mapped=byid[repair['tei_id']]
    if mapped.get(XML+'base')!=expected_url:raise ValueError('Actual source URL base differs')
    del mapped.attrib[XML+'base']
  if fields(stripped)!=fields(legacy_text):raise ValueError('Removing only exact additions fails legacy field conservation')
  extracted=deepcopy(component);extracted.remove(extracted.find(NS+'text'));extracted.append(stripped)
  reports.append(raw_check(member,ET.tostring(extracted,encoding='utf8',xml_declaration=True),package.member_bytes('source-accountability.json')))
  lsource=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,remove_comments=False,remove_pis=False));head=lsource.find('ThML.head');lmaster=etree.fromstring(master_raw)
  notes=[dict(type='source-document-prefix',n='1',text=raw[:raw.index(b'<ThML')].decode('utf8')),dict(type='source-document-root',n='1',text=json.dumps(dict(tag=lsource.tag,attributes=dict(lsource.attrib),text=lsource.text,tail=lsource.tail),ensure_ascii=False,sort_keys=True))]
  for index,node in enumerate(head.iter(),1):
   value=dict(xpath=lsource.getroottree().getpath(node),kind='element' if isinstance(node.tag,str) else 'comment' if node.tag is etree.Comment else 'pi',tag=node.tag if isinstance(node.tag,str) else None,attributes=dict(node.attrib),text=node.text,tail=node.tail)
   notes.append(dict(type='complete-source-head-field',n=str(index),text=json.dumps(value,ensure_ascii=False,sort_keys=True)))
  notes.append(dict(type='legacy-installed-volume-header',n='1',text=etree.tostring(lmaster.find(NS+'teiHeader'),encoding='unicode')));metadata_notes.append(notes);source_records.append(volume)
 for role in ('author','editor'):
  values=[p.findtext('.//DC.Creator[@sub="'+role.title()+'"][@scheme="short-form"]') for p in primary_sources]
  if not values[0] or len(set(values))!=1:raise ValueError('Common primary author/editor differs')
  ET.SubElement(ts,NS+role).text=values[0]
 pub=ET.SubElement(fd,NS+'publicationStmt');ET.SubElement(pub,NS+'p').text=STATUS;desc=ET.SubElement(fd,NS+'sourceDesc');listing=ET.SubElement(desc,NS+'listBibl');outer=ET.SubElement(listing,NS+'bibl');ET.SubElement(outer,NS+'note',{'type':'complete-work-boundary'}).text=profile['boundary']
 for member,primary,notes in zip(MEMBERS,primary_sources,metadata_notes,strict=True):
  bibl=ET.SubElement(listing,NS+'bibl',{XML+'id':member+'-source-records','type':'retained-source-volume'});ET.SubElement(bibl,NS+'title').text=primary.findtext('.//DC.Title')
  for note in notes:ET.SubElement(bibl,NS+'note',{'type':note['type'],'n':note['n']}).text=note['text']
 text=ET.SubElement(expected,NS+'text',{XML+'lang':'en'});group=ET.SubElement(text,NS+'group',{XML+'id':'stokes-acts-source-volumes'});group.extend(source_records)
 if fields(actual)!=fields(expected):raise ValueError('Exact aggregate serialized root/header/group envelope differs')
 schema=etree.XMLSchema(etree.parse(str(source.authority_path('tei-p5-xsd'))));schema.assertValid(etree.fromstring(raw_tei))
 ids=[n.get(XML+'id') for n in actual.iter() if n.get(XML+'id')]
 if len(ids)!=len(set(ids)):raise ValueError('Aggregate duplicate XML identity')
 for ref in actual.iter(NS+'ref'):
  target=ref.get('target','')
  if target.startswith('#') and target[1:] not in ids:raise ValueError('Aggregate local reference closure differs')
 expected_account=dict(contract='ocd-stokes-acts-complete-accounting-v1',complete_works=1,source_volumes=2,ordered_members=list(MEMBERS),profile=profile,volume_accounting=[json.loads(p.member_bytes('source-accountability.json')) for p in packages],uri_base_repairs=base_repairs,grouping='Each entire legacy volume text occurs once, I then II, including its own front/body/back matter. Only synthetic volume XML ID and exact source-backed relative-link XML base are added. No chapter regrouping or cross-volume targets are invented.')
 if json.loads(candidate.member_bytes('source-accountability.json'))!=expected_account:raise ValueError('Complete source accounting and exact base repairs differ')
 expected_provenance=dict(status='nonaccepted',work_id=WORK,complete_work=TITLE,profile=profile,converter=dict(source.record['converter']),source_manifest_sha256=source.sha256,human_acceptance='not_recorded',rights='unresolved',publication='not_ready')
 if json.loads(candidate.member_bytes('provenance.json'))!=expected_provenance:raise ValueError('Complete provenance differs')
 if candidate.member_bytes('README.source.md')!=source.authority_path('complete-readme').read_bytes():raise ValueError('Exact visible source attribution differs')
 if candidate.member_bytes('unresolved.jsonl')!=_canonical(dict(id='stokes-acts-complete-human-rights-print',status='unresolved',detail=STATUS)):raise ValueError('Complete qualification differs')
 if len(base_repairs)!=57:raise ValueError('Exact relative source URI census differs')
 return dict(status='pass',complete_works=1,source_volumes=2,p5='pass',complete_actual_group_fields='pass',actual_body_inverse_reports=reports,uri_base_repairs=base_repairs,all_original_legacy_fields_conserved_after_exact_addition_removal=True,ordered_full_source_headers_and_prefixes_visible=True)

def oracle(source,candidate):
 finding=check(source,candidate);result=dict(status='pass',oracle_id=oracle.oracle_id,oracle_version=oracle.oracle_version,implementation_sha256=sha(Path(__file__).read_bytes()),import_closure_sha256=closure(),runtime=_runtime_binding(),source_manifest_sha256=source.sha256,candidate_sha256=candidate.sha256,**_validation_authority_bindings(source),findings=[json.dumps(finding,sort_keys=True)]);result['result_sha256']=sha(_canonical(result));return result
oracle.oracle_id='ocd-stokes-acts-complete-independent-oracle';oracle.oracle_version='1'
