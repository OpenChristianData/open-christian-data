"""Independent raw-backed oracle for one complete Isaiah work, two volumes.

Prior exposure to the original Smith source mapping and sibling aggregate
architecture is declared. No producer or emitter is imported. Expected primary
metadata and source profile come from raw XML and exact original acquisitions.
Every ACTUAL serialized volume slice is checked by a work-local independent
stdlib source oracle, including all reading fields and full source body inverse.
"""
from copy import deepcopy
from collections import Counter
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json,subprocess,sys
import xml.etree.ElementTree as ET
from urllib.parse import urljoin,urlsplit
from lxml import etree
from ocd_kernel.reconstruction import CandidatePackage,SourceManifest
from ocd_kernel.reconstruction.contract import _canonical,_runtime_binding,_validation_authority_bindings
from ocd_kernel.library.acquisitions import source_member_set_bytes
from build.tei.smith_isaiah_source_oracle import check as source_check,SOURCES

ROOT=Path(__file__).resolve().parents[2]
WORK='expositors-bible--george-adam-smith';KEY='smith-ga-isaiah-complete'
MEMBERS=('smith-ga-expositorisa1','smith-ga-expositorisa2')
TITLE="The Expositor's Bible: The Book of Isaiah"
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'
STATUS='Nonaccepted complete electronic Book of Isaiah from two already acquired source volumes. Distinct London1910 and London1890 print witnesses remain separate. Human acceptance, print collation, rights and publication remain unresolved.'
SCOPE='Complete retained CCEL electronic XML witness for this separately acquired volume; not complete author or series. Human acceptance, print collation, rights and publication remain unresolved. External image pixels were not acquired, inferred or visually reviewed.'
BOUNDARY='The authored Book of Isaiah is explicitly in two volumes: I Isaiah I–XXXIX and II Isaiah XL–LXVI. Both entire retained electronic envelopes belong to one complete work. Distinct Volume I London1910/Twentieth Edition and Volume II London1890 statements remain separate witnesses, not a claim of one printed edition.'
SHARED='Each source front/body/back, title matter, contents, appendices/indexes and notes stays in its source volume exactly once; no deduplication or invented cross-volume target.'
EXCLUDED='Twelve Prophets Volume I is a separate authored work and explicitly partial in this two-source subtask.'
ORACLE_IMPORTS=tuple('''build/__init__.py build/tei/__init__.py build/tei/smith_isaiah_complete_oracle.py build/tei/smith_isaiah_source_oracle.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/library/__init__.py ocd_kernel/library/_common.py ocd_kernel/library/acquisitions.py ocd_kernel/library/identities.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py'''.split())
PRODUCER_IMPORTS=tuple('''build/__init__.py build/tei/__init__.py build/tei/smith_isaiah_complete_prepare.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py ocd_kernel/tei/__init__.py ocd_kernel/tei/normalization.py ocd_kernel/tei/projection_profile.py ocd_kernel/tei/writer.py'''.split())

def sha(raw):return sha256(raw).hexdigest()
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
def fields(tree):return [(n.tag,dict(n.attrib),n.text,n.tail,len(n)) for n in tree.iter()]
def parse(raw):return ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))
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
def closure(module='build.tei.smith_isaiah_complete_oracle',extra=None):
    paths=observed_imports(module,extra);expected=ORACLE_IMPORTS if module.endswith('_oracle') else PRODUCER_IMPORTS
    if not expected or tuple(paths)!=expected:raise ValueError('Isaiah observed first-party import inventory differs: '+repr(paths))
    return sha(_canonical([dict(path=p,sha256=sha((ROOT/p).read_bytes())) for p in paths]))

def raw_records(source):
    rows=[];packages=[];trees=[]
    scope=json.loads(source.authority_path('scope-assessment').read_bytes())
    if {k:scope[k] for k in ('work_id','complete_work_id','complete_works','source_volumes','ordered_members','boundary','shared_material','excluded')}!=dict(work_id=WORK,complete_work_id=KEY,complete_works=1,source_volumes=2,ordered_members=list(MEMBERS),boundary=BOUNDARY,shared_material=SHARED,excluded=EXCLUDED):raise ValueError('Independent complete-work scope/boundary differs')
    for position,member in enumerate(MEMBERS,1):
        filename,pin,front,back,count=SOURCES[member];raw=source.authority_path(member+'-raw').read_bytes();tree=parse(raw);h=tree.find('ThML.head');b=tree.find('ThML.body')
        if sha(raw)!=pin or h is None or b is None or sum(isinstance(n.tag,str) for n in tree.iter())!=count:raise ValueError('Exact whole acquired source differs')
        ar=source.authority_path(member+'-acquisition').read_bytes();a=json.loads(ar)
        if a['source_sha256']!=pin or a['source_bytes']!=len(raw) or a['source_path']!='raw/ccel/expositors-bible/'+filename or a['retained_files']!=[dict(a['retained_files'][0],path=a['source_path'],sha256=pin,bytes=len(raw))]:raise ValueError('Original source acquisition binding differs')
        if a['acquisition_id']!=WORK+'--'+member+'--acquired' or a['edition_id']!=WORK+'--'+member+'--ccel-electronic':raise ValueError('Original acquired identity differs')
        title=h.findtext('.//DC.Title');page=b.find('div1');page_fields=[dict(tag=n.tag,attributes=dict(n.attrib),text=''.join(n.itertext())) for n in page.iter() if isinstance(n.tag,str) and n.tag in {'p','h1','h2','h3','h4','h5','h6'}]
        both=[r for r in page_fields if 'IN TWO VOLUMES' in r['text'].upper()];label=[r for r in page_fields if ('VOL. I.' if position==1 else 'VOL. II.') in r['text'].upper()]
        if not both or not label or title!=TITLE+', Volume '+('I','II')[position-1]:raise ValueError('Primary complete-work authored volume boundary/order differs')
        package=CandidatePackage.load(source.authority_path(member+'-manifest').parent);package.verify_integrity();packages.append(package)
        component=parse(package.member_bytes('content.tei.xml'));master=parse(source.authority_path(member+'-master').read_bytes())
        if fields(component.find(NS+'text'))!=fields(master.find(NS+'text')):raise ValueError('Installed source-volume conservation differs')
        ids={n.get('id') for n in b.iter() if isinstance(n.tag,str) and n.get('id')}
        gaps=[dict(id=n.get('id'),attribute=k,target=n.get(k)) for n in b.iter() if isinstance(n.tag,str) for k in ('next','prev') if n.get(k) is not None and n.get(k) not in ids]
        roles=dict(sorted(Counter(n.tag for n in b.iter() if isinstance(n.tag,str)).items()))
        ordinals={id(n):i for i,n in enumerate(list(b.iter())[1:],1)}
        rel=[dict(id=n.get('id'),source_ordinal=ordinals[id(n)],tei_id=member+'-'+n.get('id') if n.get('id') else member+'-feature-'+str(ordinals[id(n)]).zfill(6),href=n.get('href'),resolved=urljoin(a['url'],n.get('href'))) for n in b.iter('a') if n.get('href') and not n.get('href').startswith('#') and not urlsplit(n.get('href')).scheme]
        row=dict(member_id=member,position=position,source_path=a['source_path'],source_sha256=pin,source_bytes=len(raw),whole_elements=count,body_elements=sum(isinstance(n.tag,str) for n in b.iter()),body_roles=roles,comments=sum(n.tag is ET.Comment for n in tree.iter()),source_title=title,source_print_statement=h.findtext('.//published'),source_url=a['url'],acquisition_sha256=sha(ar),document_prefix=raw[:raw.index(b'<ThML')].decode('utf-8'),source_wrapper_fields=[dict(tag=n.tag,attributes=dict(n.attrib),text=n.text,tail=n.tail,children=len(n)) for n in (tree,h,b)],source_head_xml_sha256=sha(etree.tostring(etree.fromstring(raw).find('ThML.head'))),source_head_fields=[dict(tag=n.tag if isinstance(n.tag,str) else '#comment',attributes=dict(n.attrib),text=n.text,tail=n.tail,children=len(n)) for n in h.iter()],source_regions=dict(front=list(front),back=list(back),body=[n.get('id') for n in b if isinstance(n.tag,str) and n.get('id') not in front+back]),source_navigation_gaps=gaps,relative_refs=rel,primary_two_volume_fields=both,primary_volume_label_fields=label,package_sha256=package.sha256,package_files=[dict(name=n,sha256=sha(package.member_bytes(n)),bytes=len(package.member_bytes(n))) for n in sorted(package.member_names)],master_sha256=sha(source.authority_path(member+'-master').read_bytes()),acceptance_sha256=sha(source.authority_path(member+'-acceptance').read_bytes()))
        r=scope['volumes'][position-1]
        if r['source']!=dict(path=a['source_path'],sha256=pin,bytes=len(raw)) or r['source_url']!=a['url'] or r['primary_two_volume_fields']!=both or r['primary_volume_label_fields']!=label or r['document_prefix']!=row['document_prefix']:raise ValueError('Source-derived scope evidence differs')
        rows.append(row);trees.append((tree,component))
    if scope['source_bytes']!=sum(r['source_bytes'] for r in rows) or scope['whole_elements']!=sum(r['whole_elements'] for r in rows) or scope['body_elements']!=sum(r['body_elements'] for r in rows):raise ValueError('Full source scope denominator differs')
    return rows,packages,trees

def expected_profile(source):
    rows,_,_=raw_records(source)
    return dict(contract='ocd-smith-isaiah-complete-profile-v1',work_id=WORK,complete_work_id=KEY,title=TITLE,complete_works=1,source_volumes=2,ordered_members=list(MEMBERS),boundary=BOUNDARY,shared_material=SHARED,excluded=EXCLUDED,source_kind='retained-member-set',source_bytes=sum(r['source_bytes'] for r in rows),whole_elements=sum(r['whole_elements'] for r in rows),body_elements=sum(r['body_elements'] for r in rows),relative_ref_count=sum(len(r['relative_refs']) for r in rows),volumes=rows,permission_sha256=sha(source.authority_path('ccel-permission').read_bytes()),source_mapping_ancestor_sha256=sha(source.authority_path('source-mapping-ancestor').read_bytes()),raw_oracle_sha256=sha(source.authority_path('raw-volume-oracle').read_bytes()),producer_imports=list(PRODUCER_IMPORTS),oracle_imports=list(ORACLE_IMPORTS),producer_import_closure_sha256=closure('build.tei.smith_isaiah_complete_prepare'))

def expected_policy():return dict(contract='ocd-smith-isaiah-complete-policy-v1',complete_works=1,source_volumes=2,ordered_members=list(MEMBERS),no_acquisition=True,full_actual_volume_inverse=True,whole_serialized_envelope=True,raw_primary_metadata=True,original_acquired_uri_context=True,source_volume_preservation=True,legacy_identity_preservation=True,rights_clearance=False,oracle_imports=list(ORACLE_IMPORTS),producer_imports=list(PRODUCER_IMPORTS),prior_exposure='Independent source mapping derived from original exercised Smith oracle; sibling Dods/Maclaren aggregate architecture reviewed. Neither producer nor emitter imported by oracle.')

def expected_readme(source,profile,packages):
    raw=('# Complete retained electronic work: '+TITLE+'\n\n'+BOUNDARY+'\n\n'+SHARED+'\n\n'+EXCLUDED+'\n\nThe inherited author-cohort catalog is preserved as a container; adding a complete-work form does not make it one intellectual work. All legacy source IDs, masters, acceptances and acquired records remain unchanged. No downloads or new source witnesses. Only two synthetic volume text IDs and per-volume acquired-URL xml:base attributes are added to the preserved native volume envelopes. All '+str(profile['relative_ref_count'])+' relative references keep literal targets and exact original acquired URL context. Raw source defects, spelling and punctuation remain literal; no print collation or visual/pixel/CSS equivalence is claimed. Human acceptance, rights and publication remain unresolved.\n\n## Retained CCEL developer/publisher permission notice\n\n').encode('utf-8')+source.authority_path('ccel-permission').read_bytes()+b'\n\n'
    for row,package in zip(profile['volumes'],packages,strict=True):
        raw+=('## Source volume '+str(row['position'])+': '+row['member_id']+'\n\nLiteral original acquired URL: '+row['source_url']+'\n\nLiteral XML declaration/document prefix:\n\n```xml\n'+row['document_prefix']+'```\n\nAbsent source navigation destinations: '+json.dumps(row['source_navigation_gaps'],ensure_ascii=False,sort_keys=True)+'. These remain explicit source gaps, not invented targets.\n\n').encode('utf-8')+package.member_bytes('README.source.md')+b'\n\n'
    return raw

def raw_header(expected,source,rows,trees):
    header=ET.SubElement(expected,NS+'teiHeader');fd=ET.SubElement(header,NS+'fileDesc');ts=ET.SubElement(fd,NS+'titleStmt');ET.SubElement(ts,NS+'title').text=TITLE
    for role in ('author','editor'):
        values=[next(n.text for n in t[0].findall('.//DC.Creator') if n.get('sub')==role.capitalize() and n.get('scheme')=='short-form') for t in trees]
        if not values[0] or len(set(values))!=1:raise ValueError('Raw common authored identity differs')
        ET.SubElement(ts,NS+role).text=values[0]
    pub=ET.SubElement(fd,NS+'publicationStmt');ET.SubElement(pub,NS+'p').text=STATUS
    desc=ET.SubElement(fd,NS+'sourceDesc');qual=ET.SubElement(desc,NS+'bibl')
    for kind,value in [('complete-work-scope',BOUNDARY),('shared-material-disposition',SHARED),('excluded-partial-work',EXCLUDED)]:ET.SubElement(qual,NS+'note',{'type':kind}).text=value
    for member,row in zip(MEMBERS,rows,strict=True):
        raw=source.authority_path(member+'-raw').read_bytes();tree=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True));h=tree.find('ThML.head')
        bibl=ET.SubElement(desc,NS+'bibl',{XML+'id':member+'-source','type':'retained-source-volume'});ET.SubElement(bibl,NS+'note',{'type':'source-limitations'}).text=SCOPE;ET.SubElement(bibl,NS+'title').text=h.findtext('.//DC.Title')
        for ordinal,node in enumerate(h.iter(),1):
            if not isinstance(node.tag,str):ET.SubElement(bibl,NS+'note',{'type':'retained-source-head-comment','n':str(ordinal)}).text='Retained source head comment: '+(node.text or '')
            elif (node.text or '').strip() or node.attrib:
                ET.SubElement(bibl,NS+'note',{'type':'retained-source-head-field','n':str(ordinal)}).text='Source field '+tree.getroottree().getpath(node)+': '+json.dumps(dict(attributes=dict(node.attrib),text=node.text),ensure_ascii=False,sort_keys=True)
        prolog=[dict(node_kind='comment' if n.tag is etree.Comment else 'pi',target=n.target if n.tag is etree.PI else None,text=n.text,tail=n.tail) for n in reversed(list(tree.itersiblings(preceding=True)))]
        for ordinal,r in enumerate(prolog,1):ET.SubElement(bibl,NS+'note',{'type':'retained-source-prolog','n':str(ordinal)}).text='Retained source prolog '+str(ordinal)+': '+json.dumps(r,ensure_ascii=False,sort_keys=True)
        ET.SubElement(bibl,NS+'note',{'type':'retained-source-document-prefix'}).text=row['document_prefix'];ET.SubElement(bibl,NS+'note',{'type':'retained-source-uri-context'}).text=row['source_url']

def check(source:SourceManifest,candidate:CandidatePackage):
    source.verify();candidate.verify_integrity()
    if candidate.manifest['status']!='nonaccepted' or candidate.manifest['converter']!=source.record['converter'] or source.record['work_id']!=WORK or canonical(dict(source.record['scope']))!=canonical(dict(kind='complete-existing-authored-work',complete_work_id=KEY,complete_works=1,source_volumes=2,new_acquisition=False,ordered_members=list(MEMBERS))):raise ValueError('Aggregate complete-work source/converter/identity/status differs')
    rows,packages,trees=raw_records(source);profile=expected_profile(source)
    if json.loads(source.authority_path('complete-profile').read_bytes())!=profile or json.loads(source.authority_path('complete-policy').read_bytes())!=expected_policy():raise ValueError('Exact independent source profile/policy/closures differs')
    acquisition=json.loads(source.authority_path('grouped-acquisition-proposal').read_bytes());manifest=source.authority_path('member-set').read_bytes()
    if acquisition.get('source_kind')!='retained-member-set' or manifest!=source_member_set_bytes(acquisition) or sha(manifest)!=acquisition['source_sha256'] or len(manifest)!=acquisition['source_bytes'] or [(r['path'],r['sha256'],r['bytes']) for r in acquisition['retained_files']]!=[(r['source_path'],r['source_sha256'],r['source_bytes']) for r in rows]:raise ValueError('Canonical ordered member-set authority differs')
    authority_paths={a['name']:a['path'] for a in source.record['authorities']}
    form=WORK+'--smith-ga-isaiah-complete--retained-en';edition=WORK+'--smith-ga-isaiah-complete--ccel-electronic';aid=WORK+'--smith-ga-isaiah-complete--retained-member-set'
    expected_acquisition=dict(schema_version='2.0',acquisition_id=aid,edition_id=edition,provider='Christian Classics Ethereal Library',url=rows[0]['source_url'],route='born-digital',source_kind='retained-member-set',source_path=authority_paths['member-set'],source_scope=BOUNDARY+' '+SHARED+' Original acquired URL context remains per volume; no human acceptance, print collation, rights clearance or publication authorization.',retained_files=[dict(path=r['source_path'],sha256=r['source_sha256'],bytes=r['source_bytes'],media_type='application/xml',scope='Entire source-attested Volume '+('I','II')[i]+': '+r['source_title']+'; literal printed witness '+r['source_print_statement']+'; acquired URI '+r['source_url']+'. Full front/body/back, metadata, directives and source defects retained.') for i,r in enumerate(rows)],rights='Unresolved; retained statements and CCEL developer/publisher permission notice remain subject to review.',warnings=['Derived ordered member set of two existing acquisitions; no downloads or new witnesses.','Entry URL is exact original Volume I acquisition URL; original Volume II URL remains distinct per-volume base.','Author catalog is preserved as inherited container, not asserted to be one intellectual work.','Twelve Prophets Volume I is excluded and explicitly partial.'],source_sha256=sha(manifest),source_bytes=len(manifest))
    if acquisition!=expected_acquisition:raise ValueError('Whole exact derived acquisition identity/scope/URLs differs')
    original_work=json.loads(source.authority_path('legacy-catalog').read_bytes());expected_work=deepcopy(original_work)
    if original_work['work_id']!=WORK or any(f['textual_form_id']==form for f in original_work['textual_forms']):raise ValueError('Preserved catalog baseline identity differs')
    expected_work['textual_forms'].append(dict(textual_form_id=form,language='en',editions=[dict(edition_id=edition,title=TITLE,language='en',category='commentary',acquisition_ids=[aid])]))
    expected_work['evidence']+=[authority_paths['scope-assessment'],authority_paths['member-set']]
    if json.loads(source.authority_path('work-proposal').read_bytes())!=expected_work:raise ValueError('Derived complete-work identity proposal is not exact append-only baseline')
    root=parse(candidate.member_bytes('content.tei.xml'));expected=ET.Element(NS+'TEI',{XML+'id':KEY});raw_header(expected,source,rows,trees)
    text=ET.SubElement(expected,NS+'text',{XML+'lang':'en'});group=ET.SubElement(text,NS+'group',{XML+'id':KEY+'-volumes'});actual_group=root.find(NS+'text/'+NS+'group')
    if actual_group is None or len(actual_group)!=2:raise ValueError('Exactly two full source-volume envelopes required')
    reports=[];resolved=[]
    with TemporaryDirectory(prefix='ocd-smith-isaiah-actual-') as temporary:
        for member,row,(primary,component),package,actual in zip(MEMBERS,rows,trees,packages,actual_group,strict=True):
            volume=deepcopy(component.find(NS+'text'));volume.set(XML+'id',member+'-volume');volume.set(XML+'base',row['source_url']);group.append(volume)
            stripped=deepcopy(actual)
            if stripped.attrib!={XML+'lang':'en',XML+'id':member+'-volume',XML+'base':row['source_url']}:raise ValueError('Volume native identity/URI base/order differs')
            del stripped.attrib[XML+'id'];del stripped.attrib[XML+'base']
            if fields(stripped)!=fields(component.find(NS+'text')):raise ValueError('Actual serialized full volume fields/order/attachment differ')
            extracted=deepcopy(component);extracted.remove(extracted.find(NS+'text'));extracted.append(stripped);destination=Path(temporary)/member;destination.mkdir()
            for name in package.member_names:(destination/name).write_bytes(package.member_bytes(name))
            (destination/'content.tei.xml').write_bytes(ET.tostring(extracted,encoding='UTF-8',xml_declaration=True));reports.append(source_check(member,destination))
            refs={n.get(XML+'id'):n for n in actual.iter(NS+'ref')}
            for r in row['relative_refs']:
                n=refs.get(r['tei_id'])
                if n is None or n.get('target')!=r['href'] or urljoin(actual.get(XML+'base'),n.get('target'))!=r['resolved']:raise ValueError('Actual literal source relative URI/context differs')
                resolved.append(dict(member_id=member,source_id=r['id'],source_ordinal=r['source_ordinal'],tei_id=r['tei_id'],target=r['href'],source_url=row['source_url'],resolved=r['resolved']))
    if fields(root)!=fields(expected):raise ValueError('Whole aggregate root/header/group envelope, payload or attachment differs')
    etree.XMLSchema(etree.parse(str(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd'))).assertValid(etree.fromstring(candidate.member_bytes('content.tei.xml')))
    ids=[n.get(XML+'id') for n in root.iter() if n.get(XML+'id')]
    if len(ids)!=len(set(ids)):raise ValueError('Aggregate global IDs collide')
    for n in root.iter(NS+'ref'):
        if (n.get('target') or '').startswith('#') and n.get('target')[1:] not in ids:raise ValueError('Aggregate local-reference closure differs')
    expected_account=dict(contract='ocd-smith-isaiah-complete-accounting-v1',work_id=WORK,complete_work_id=KEY,complete_works=1,source_volumes=2,ordered_members=list(MEMBERS),profile=profile,volume_accounting=[json.loads(p.member_bytes('source-accountability.json')) for p in packages],native_changes='Only two synthetic volume text IDs and two acquired-URL xml:base attributes. All preexisting text fields, attributes, children, attachment and volume front/body/back are preserved exactly; independent raw inverses prove all source readings. Original full document prefixes are human-visible and accounted.',historical_package_provenance=[json.loads(p.member_bytes('provenance.json')) for p in packages])
    expected_prov=dict(contract='ocd-smith-isaiah-composite-provenance-v1',status='nonaccepted',work_id=WORK,complete_work_id=KEY,title=TITLE,ordered_members=list(MEMBERS),source_manifest_sha256=source.sha256,converter=dict(source.record['converter']),producer_recipe_sha256=sha(source.authority_path('producer').read_bytes()),oracle_sha256=sha(Path(__file__).read_bytes()),source_profile=profile,historical_packages='Immutable already installed source-volume packages are ingredients, not the sole current producer. Complete-work recipe groups both serialized text envelopes and binds each original acquired URI context.',human_acceptance='not_recorded',rights='unresolved',publication='not_ready')
    if json.loads(candidate.member_bytes('source-accountability.json'))!=expected_account or json.loads(candidate.member_bytes('provenance.json'))!=expected_prov:raise ValueError('Complete source accounting/composite provenance differs')
    readme=expected_readme(source,profile,packages)
    if candidate.member_bytes('README.source.md')!=readme or source.authority_path('complete-readme').read_bytes()!=readme:raise ValueError('Actual human-visible attribution/permission/source prefix differs')
    unresolved=b''
    for m,p in zip(MEMBERS,packages,strict=True):
        for line in p.member_bytes('unresolved.jsonl').splitlines():
            r=json.loads(line);r['source_member_id']=m;unresolved+=canonical(r)
    unresolved+=canonical(dict(id=KEY+'-identity-print-rights',status='unresolved',detail=STATUS))
    for row in rows:
        for i,gap in enumerate(row['source_navigation_gaps'],1):unresolved+=canonical(dict(id=row['member_id']+'-source-navigation-gap-'+str(i),status='unresolved',kind='missing-source-navigation-target',source_member_id=row['member_id'],source_id=gap['id'],source_attribute=gap['attribute'],literal_target=gap['target'],detail='Target is absent from the complete acquired source ID set; no destination is invented.'))
    if candidate.member_bytes('unresolved.jsonl')!=unresolved:raise ValueError('Aggregate unresolved source record differs')
    return dict(status='pass',complete_works=1,source_volumes=2,whole_elements=profile['whole_elements'],body_elements=profile['body_elements'],actual_serialized_full_fields_and_source_inverses='pass',all_primary_metadata_and_document_prefix='pass',relative_source_uris_resolved=len(resolved),relative_source_uri_evidence=resolved,global_ids=len(ids),global_local_reference_closure='pass',p5='pass',volumes=reports,tei_sha256=sha(candidate.member_bytes('content.tei.xml')),limits=['Inherited author catalog remains container','Distinct print editions preserved; no print collation','Twelve Prophets Volume I excluded/partial','External image pixels not acquired or visually reviewed','Human acceptance, rights and publication unresolved'])

def oracle(source:SourceManifest,candidate:CandidatePackage):
    findings=check(source,candidate)
    record=dict(status='pass',oracle_id=oracle.oracle_id,oracle_version=oracle.oracle_version,implementation_sha256=sha(Path(__file__).read_bytes()),import_closure_sha256=closure(),runtime=_runtime_binding(),source_manifest_sha256=source.sha256,candidate_sha256=candidate.sha256,**_validation_authority_bindings(source),findings=[json.dumps(findings,sort_keys=True)])
    record['result_sha256']=sha(_canonical(record));return record
oracle.oracle_id='ocd-smith-isaiah-complete-raw-backed-independent-oracle'
oracle.oracle_version='1'
