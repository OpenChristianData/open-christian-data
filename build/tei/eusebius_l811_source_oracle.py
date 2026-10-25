"""Independent raw-backed actual-object checker for the retained L811 work.

No producer, producer mapping helper, or historical PTA oracle is imported.
Prior exposure: the original producer and read-only assessor were reviewed.
Ordinal source-to-actual comparison is corroborated by stdlib XML, and an
independent exact old-byte inverse constrains the complete synthetic envelope.
Neither inverse alone nor the 150 Psalm divisions proves a finished print edition.
"""
from pathlib import Path
from hashlib import sha256
from collections import Counter
from collections.abc import Mapping
import json,re,platform
import xml.etree.ElementTree as ET
from lxml import etree
from build.tei.eusebius_l811_runtime import guard

ROOT=Path(__file__).resolve().parents[2]
HOME='sources/manifest-acquisitions/eusebius-l811-retained-install-20261004-v1'
LOG='reports/_logs/eusebius-l811-existing-install-20261004-v1'
OLD_HOME='sources/manifest-acquisitions/manifest-acquisition-pta-l811-eusebius-commentarii-psalmos-tomes-i-iii-ef861ab3-v5'
WORK='eusebius-commentarii-in-psalmos';EDITION='pta-ef861ab3-commentarii-psalmos'
SOURCE='pta-l811-retained-three-tome-repair-ef861ab3-v1';COMMIT='ef861ab391ea35c5d85b41dd8d7ba2bf65530b21'
PRODUCER='build/tei/eusebius_l811_retained_repair.py';ORACLE='build/tei/eusebius_l811_source_oracle.py'
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'
TOMES=('I','II','III');MEMBER_NAMES=('manifest.json','content.tei.xml','provenance.json','source-accountability.json','README.source.md','unresolved.jsonl')
RAW_SHA=('19d6a6a8554570a5519d44e554ab27c25170ee1c71d00d15753dcdfd3c44b535','0b721fed3724ebfd62b343740fbe28569676bfb1e51be137e2b39c0d0ec2abcf','6c50c98cb529b2b46a7d2811592bf024a153bf8c392a3ad27a37d1723fb3cfd2')
RAW_BYTES=(1533937,3916115,2529553)
OLD_SHA=('61a74fbaff4cc4d4cff44e0232c50b0c9f21cdbf3297cd53f8adc6c6a6efbb11','a3948866bb7504c12e542efcbca644b51c7f055867af5bd283b5a94e808780f4','c0b2ef2f8d4581fcad348a110744ed87bfb0c431c54e867e9caf83f1e370a1f7','4968d81cc1ec311baf194e618b3e68a3cfd81e45fb32f4086c83a8a660196f4c','7a7d24717fc019e09a4ef5de94cbe8e9c98379a779fa9e00d1b4b23a2a41caa8','5e05b586628b76ecda6444443297c044769dbceb23f93ef8cba79cdde6b42a82')
URI_DISPOSITION='Literal source reference values remain unchanged except already-declared #fragment ID scoping. Bare target identifiers and bibliographic corresp labels are not converted into fabricated HTTP links. The acquisition URL is the retained document context, not evidence that every ambiguous source target resolves.'
SHELL_DISPOSITION='Original wrapper attributes, direct text and tails and document prefix/suffix remain exact readable administration; original header child carriers and body retain their source-defined attachment under the historical three-tome mapping.'

def enc(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def sha(v):return sha256(v).hexdigest()
def insist(ok,why):
    if not ok:raise ValueError(why)
def parse(raw):return etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,recover=False))
def tag(n):return n.tag if isinstance(n.tag,str) else '#comment' if n.tag in (ET.Comment,etree.Comment) else '#processing-instruction'
def fields(n):return [tag(n),dict(n.attrib),n.text,n.tail,[fields(c) for c in n]]
def pin(path):
    raw=(ROOT/path).read_bytes();return dict(path=path,bytes=len(raw),sha256=sha(raw))
def plain(v):
    if isinstance(v,Mapping):return {k:plain(w) for k,w in v.items()}
    if isinstance(v,(tuple,list)):return [plain(w) for w in v]
    return v

def authority_spec():
    """Exact metadata layout, not a source selection or producer mapping helper."""
    rows=[]
    for pos,tome in enumerate(TOMES,1):
        part=tome.lower();base=f'raw/pta/{COMMIT}/pta-l811-eusebius-commentarii-psalmos-tom-{part}-ef861ab3'
        rows.extend([(f'primary-source-tome-{tome}',base+f'/pta0003.pta020.pta-grcBibex{pos}.xml','primary-source'),(f'acquisition-receipt-tome-{tome}',base+'/acquisition-receipt.json','source-acquisition-receipt'),(f'attribution-tome-{tome}',base+'/README.source.md','source-member-attribution')])
        old=f'sources/manifest-acquisitions/manifest-acquisition-pta-l811-eusebius-commentarii-psalmos-tom-{part}-ef861ab3-v2'
        for name in ('source-manifest.json','complete-source-feature-profile.json'):
            rows.append((f'historical-tome-{tome}-{name}',LOG+'/retained-authorities/'+old+'/'+name,'historical-source-authority'))
    for name in MEMBER_NAMES:rows.append(('original-'+name,LOG+'/retained-original-package/'+name,'retained-original-package-member'))
    rows.extend([('historical-source-manifest',OLD_HOME+'/source-manifest.json','historical-source-authority')])
    for name in ('complete-source-feature-profile.json','policy.json','README.source.md'):
        rows.append(('historical-composite-'+name,LOG+'/retained-authorities/'+OLD_HOME+'/'+name,'historical-source-authority'))
    rows.extend([('historical-producer',LOG+'/retained-authorities/build/tei/pta_l811_three_tome.py','historical-producer-lineage'),('historical-oracle',LOG+'/retained-authorities/build/tei/pta_l811_three_tome_oracle.py','historical-oracle-lineage'),('local-authority-recovery',LOG+'/local-authority-recovery-v1.json','local-snapshot-recovery-evidence'),('scoped-version',HOME+'/scoped-source-version.json','immutable-source-row-and-version'),('producer',PRODUCER,'bounded-repair-implementation'),('oracle',ORACLE,'independent-source-oracle-implementation'),('runtime-helper','build/tei/eusebius_l811_runtime.py','work-local-runtime-admission'),('runtime',HOME+'/runtime.json','actual-execution-runtime-closure'),('complete-source-feature-profile',HOME+'/profile.json','complete-source-feature-profile'),('independent-validation-policy',HOME+'/policy.json','independent-validation-policy'),('source-attribution',HOME+'/README.source.md','source-attribution-evidence'),('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),('tei-examples-xsd','ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd','tei-schema-import'),('tei-xml-xsd','ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd','tei-schema-import'),('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema')])
    return rows

def full_source_check(original,actual_raw,raw_members,receipts):
    """Check every raw-owned carrier directly against the real repaired object."""
    insist(sha(original)==OLD_SHA[1],'Exact original TEI lineage differs')
    old=parse(original);actual=parse(actual_raw)
    admin=actual.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'sourceDesc')
    additions=[n for n in admin if n.get('type')=='retained-source-document-envelope']
    insist(len(additions)==3 and list(admin)[-3:]==additions,'Exact last three source-administration carriers differ')
    cursors={name:0 for name in ('titleStmt','editionStmt','publicationStmt','sourceDesc','encodingDesc','profileDesc','revisionDesc')}
    header=actual.find(NS+'teiHeader');file=header.find(NS+'fileDesc');volumes=actual.find(NS+'text/'+NS+'body')
    insist(len(volumes)==3,'Exactly three complete source tomes required')
    counts=dict(nodes=0,attributes=0,rewritten_reference_attributes=0);member_facts=[];repairs=[];inverse=actual_raw
    def compare(b,a,path,ids,label=None):
        expected={}
        for key,value in b.attrib.items():
            if key==XML+'id':expected[key]=ids[value]
            else:expected[key]=re.sub(r'(?<!\S)#([^\s]+)',lambda m:'#'+ids.get(m.group(1),m.group(1)),value)
            counts['rewritten_reference_attributes']+=int(expected[key]!=value and key!=XML+'id')
        if label is not None and 'n' not in expected:expected['n']=label
        insist((tag(b),expected,b.text,b.tail,len(b))==(tag(a),dict(a.attrib),a.text,a.tail,len(a)),'Actual source field/order/attachment differs: '+path)
        counts['nodes']+=1;counts['attributes']+=len(expected)
        for i,(left,right) in enumerate(zip(b,a,strict=True),1):compare(left,right,path+'/'+str(i),ids)
    for pos,(raw,receipt,tome) in enumerate(zip(raw_members,receipts,TOMES,strict=True),1):
        insist(sha(raw)==RAW_SHA[pos-1] and len(raw)==RAW_BYTES[pos-1],'Exact primary source tome differs')
        source=parse(raw);other=ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))
        insist(fields(source)==fields(other),'Independent stdlib/lxml whole-source corroboration differs')
        raw_ids=[n.get(XML+'id') for n in source.iter() if isinstance(n.tag,str) and n.get(XML+'id')]
        insist(len(raw_ids)==len(set(raw_ids)),'Source duplicate IDs')
        ids={v:f'l811-t{pos}-'+v for v in raw_ids};h=source.find(NS+'teiHeader');fd=h.find(NS+'fileDesc');body=source.find(NS+'text/'+NS+'body')
        label='Tome '+tome;vol=volumes[pos-1];title=fd.find(NS+'titleStmt/'+NS+'title')
        insist(dict(vol.attrib)=={'type':'volume','n':label,XML+'lang':source.get(XML+'lang')} and len(vol)==2,'Actual tome envelope differs')
        insist(vol[0].tag==NS+'head' and dict(vol[0].attrib)=={} and len(vol[0])==0 and vol[0].text==' '.join(''.join(title.itertext()).split()),'Actual tome heading differs')
        carrier=vol[1];insist(carrier.tag==NS+'div' and dict(carrier.attrib)=={'type':'source-body'} and carrier.text==body.text and len(carrier)==len(body),'Actual whole source-body envelope differs')
        for i,(b,a) in enumerate(zip(body,carrier,strict=True),1):compare(b,a,f't{pos}/text/body/{i}',ids)
        for name in cursors:
            before=fd.find(NS+name) if name in ('titleStmt','editionStmt','publicationStmt','sourceDesc') else h.find(NS+name)
            after=file.find(NS+name) if name in ('titleStmt','editionStmt','publicationStmt','sourceDesc') else header.find(NS+name)
            if name=='titleStmt' and cursors[name]==0:cursors[name]=1
            for ordinal,child in enumerate(before,1):
                if name=='titleStmt' and child.tag==NS+'title':continue
                compare(child,after[cursors[name]],f't{pos}/header/{name}/{ordinal}',ids,label);cursors[name]+=1
            if name=='sourceDesc':
                bibl=after[cursors[name]]
                insist(dict(bibl.attrib)=={'type':'source-tome-title','n':label} and len(bibl)==1,'Actual retained primary title carrier differs')
                compare(title,bibl[0],f't{pos}/header/title',ids);cursors[name]+=1
        bibl=additions[pos-1]
        insist(bibl.tag==NS+'bibl' and dict(bibl.attrib)=={'type':'retained-source-document-envelope','n':label} and bibl.text is None and bibl.tail is None and len(bibl)==1,'Actual administration bibl envelope differs')
        note=bibl[0];insist(note.tag==NS+'note' and dict(note.attrib)=={'type':'source-document-envelope-administration'} and note.text is None and note.tail is None,'Actual administration typed note differs')
        shell=[source,h,fd,*fd,*list(h)[1:],source.find(NS+'text'),body]
        admin_values=dict(tome=tome,source_sha256=sha(raw),source_bytes=len(raw),literal_document_prefix=raw.split(b'<TEI',1)[0].decode(),literal_document_suffix=raw.rsplit(b'</TEI>',1)[1].decode(),root_namespace_bindings=source.nsmap,source_shell_fields=[dict(path=source.getroottree().getpath(n),tag=n.tag,attributes=dict(n.attrib),text=n.text,tail=n.tail) for n in shell],source_uri_context=dict(source_url=receipt['source_url'],final_url=receipt['final_url'],reader_url=receipt['reader_url'],pinned_commit=receipt['pinned_commit'],disposition=URI_DISPOSITION),source_quality_statements=[''.join(n.itertext()) for n in fd.findall(NS+'editionStmt/'+NS+'p')],field_disposition=SHELL_DISPOSITION)
        insist(len(note)==len(admin_values),'Administration field cardinality differs')
        for paragraph,(name,value) in zip(note,admin_values.items(),strict=True):
            literal=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
            insist(paragraph.tag==NS+'p' and dict(paragraph.attrib)=={'n':name,XML+'space':'preserve'} and paragraph.text==literal and paragraph.tail is None and len(paragraph)==0,'Actual raw-backed administration field differs: '+tome+'/'+name)
        marker=(f'<bibl xmlns="http://www.tei-c.org/ns/1.0" type="retained-source-document-envelope" n="{label}">').encode()
        insist(inverse.count(marker)==1,'Administration literal boundary differs')
        start=inverse.index(marker);end=inverse.index(b'</bibl>',start)+7;chunk=inverse[start:end]
        insist(fields(parse(chunk))==fields(bibl),'Serialized actual administration carrier differs')
        repairs.append(dict(family='located-source-document-administration',tome=tome,fields=admin_values,carrier_sha256=sha(chunk)))
        inverse=inverse[:start]+inverse[end:]
        primary=body[1];numbers=[int(n.get('n')[3:]) for n in primary if isinstance(n.tag,str) and re.fullmatch(r'Ps_\d+',n.get('n',''))]
        insist(numbers==list(range((pos-1)*50+1,pos*50+1)),'Complete ordered source Psalm scope differs')
        insist(source.get(XML+'lang')=='en' and body[0].get(XML+'lang')=='deu' and primary.get(XML+'lang')=='grc','Primary retained language disposition differs')
        member_facts.append(dict(position=pos,tome=tome,source_sha256=sha(raw),source_bytes=len(raw),title=''.join(title.itertext()),source_root_language='en',preface_language='deu',edition_language='grc',source_revision_status=h.find(NS+'revisionDesc').get('status'),psalm_numbers=numbers,source_ids=len(raw_ids),source_body_nodes=sum(1 for _ in body.iter()),source_document_census=dict(sorted(Counter(tag(n).removeprefix(NS) for n in source.iter()).items())),source_uri_attributes=[dict(path=source.getroottree().getpath(n),attribute=k,value=v) for n in source.iter() if isinstance(n.tag,str) for k,v in n.attrib.items() if k in ('target','corresp','wit','ref','source','sameAs')],document_prefix=raw.split(b'<TEI',1)[0].decode(),document_suffix=raw.rsplit(b'</TEI>',1)[1].decode()))
    for name,index in cursors.items():
        parent=file.find(NS+name) if name in ('titleStmt','editionStmt','publicationStmt','sourceDesc') else header.find(NS+name)
        insist(len(parent)==index+(3 if name=='sourceDesc' else 0),'Actual header omission/invention differs: '+name)
    # No producer byte offsets are used. After removing the independently checked
    # exact new header carriers, exactly one inserted byte restores the old file.
    point=next((i for i,(a,b) in enumerate(zip(inverse,original)) if a!=b),None)
    insist(point is not None and inverse[point:point+1]==b' ' and inverse[:point]+inverse[point+1:]==original,'Independent entire historical TEI byte inverse differs')
    witness=actual.find(NS+'text/'+NS+'body')[0][1];raw_witness=parse(raw_members[0]).find(NS+'text/'+NS+'body')
    for i in (2,40,3,2,26,1,2,1):witness=witness[i-1];raw_witness=raw_witness[i-1]
    insist(witness.get('wit').endswith(' ') and witness.get('wit').replace('l811-t1-','')==raw_witness.get('wit'),'Exact repaired source witness-space locus differs')
    old_witness=old.find(NS+'text/'+NS+'body')[0][1]
    for i in (2,40,3,2,26,1,2,1):old_witness=old_witness[i-1]
    original_start=original.rfind(b'<',0,point)
    repairs.insert(0,dict(family='source-witness-attribute-whitespace',tome='I',source_path='/TEI/text/body/2/40/3/2/26/1/2/1',candidate_path=old.getroottree().getpath(old_witness),attribute='wit',before=old_witness.get('wit'),after=witness.get('wit'),source_value=raw_witness.get('wit'),original_byte_start=original_start))
    ids=[n.get(XML+'id') for n in actual.iter() if isinstance(n.tag,str) and n.get(XML+'id')]
    insist(len(ids)==len(set(ids)) and ids==[n.get(XML+'id') for n in old.iter() if isinstance(n.tag,str) and n.get(XML+'id')],'Actual global ID scope changed')
    for n in actual.iter():
        if not isinstance(n.tag,str):continue
        for v in n.attrib.values():
            for token in v.split():
                if re.match(r'^#l811-t[123]-',token):insist(token[1:] in set(ids),'Actual source-bound scoped reference does not close: '+token)
    return dict(status='pass',complete_authored_works=1,source_tomes=3,actual_source_carrier_nodes=counts['nodes'],attributes_compared=counts['attributes'],rewritten_reference_attributes=counts['rewritten_reference_attributes'],members=member_facts,repairs=repairs,full_old_tei_byte_inverse=True,old_tei_sha256=sha(original),actual_tei_sha256=sha(actual_raw),scope='Complete retained three-tome digital edition, including all prefatory and supplementary matter. Tomes I/II are source-declared works in progress, not a claimed finished printed critical edition.',independence='Actual source-to-candidate ordinal fields and attachment, plus independent stdlib XML whole-source corroboration. No producer mapping import; prior producer/assessor exposure declared. Entire old byte inverse independently constrains the remaining synthetic envelope. Bare source targets and bibliographic labels remain literal and are not claimed resolved.')

def check(source,candidate):
    source.verify();candidate.verify_integrity();guard(source)
    record=source.record
    insist(set(record)=={'contract','work_id','edition_id','source_id','manifest_row','source_order','authorities','converter','validator','package_schema'} and record['contract']=='ocd-source-manifest-v1','Exact governing source record envelope differs')
    insist(source.repository_root.resolve(strict=True)==ROOT.resolve(strict=True) and source.path.relative_to(source.repository_root).as_posix()==HOME+'/source-manifest.json','Declared source-manifest root/path differs')
    insist(record['work_id']==WORK and record['edition_id']==EDITION and record['source_id']==SOURCE and record['manifest_row']=='L811','Exact retained work/edition/source identity differs')
    schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha(source.authority_path('candidate-package-schema').read_bytes()))
    insist(plain(record['package_schema'])==schema,'Exact declared source package schema differs')
    expected_candidate=dict(contract='ocd-candidate-package-v1',status='nonaccepted',source_id=SOURCE,source_manifest=dict(path=HOME+'/source-manifest.json',sha256=source.sha256),converter=plain(record['converter']),package_schema=schema,members=[dict(name=n,bytes=len(candidate.member_bytes(n)),sha256=sha(candidate.member_bytes(n))) for n in sorted(MEMBER_NAMES) if n!='manifest.json'])
    insist(plain(candidate.manifest)==expected_candidate,'Exact outer candidate manifest record/path/schema/status differs')
    insist(candidate.manifest['source_id']==SOURCE and candidate.manifest['source_manifest']['sha256']==source.sha256 and dict(candidate.manifest['converter'])==dict(record['converter']),'Exact candidate/source/producer identity differs')
    insist([(a['name'],a['path'],a['role']) for a in record['authorities']]==authority_spec(),'Exact ordered authority layout differs')
    profile=json.loads(source.authority_path('complete-source-feature-profile').read_bytes());policy=json.loads(source.authority_path('independent-validation-policy').read_bytes())
    raws=[source.authority_path('primary-source-tome-'+t).read_bytes() for t in TOMES]
    receipts=[json.loads(source.authority_path('acquisition-receipt-tome-'+t).read_bytes()) for t in TOMES]
    for i,(raw,receipt) in enumerate(zip(raws,receipts,strict=True),1):
        url=f'https://raw.githubusercontent.com/PatristicTextArchive/pta_data/{COMMIT}/data/pta0003/pta020/pta0003.pta020.pta-grcBibex{i}.xml'
        insist(receipt['source_url']==receipt['final_url']==url and receipt['pinned_commit']==COMMIT and receipt['retained_file']['sha256']==sha(raw) and receipt['retained_file']['bytes']==len(raw),'Exact retained acquisition/source URI binding differs')
    originals={n:source.authority_path('original-'+n).read_bytes() for n in MEMBER_NAMES}
    insist([sha(originals[n]) for n in MEMBER_NAMES]==list(OLD_SHA),'Exact original six-member package lineage differs')
    result=full_source_check(originals['content.tei.xml'],candidate.member_bytes('content.tei.xml'),raws,receipts)
    order=dict(primary_members=['primary-source-tome-'+t for t in TOMES],complete_works=1,tome_order=list(TOMES),scope='All three complete retained XML documents; one titled work; complete source bodies and header children plus exact located wrapper/prolog administration; no source exclusions.')
    insist(plain(record['source_order'])==order,'Exact full source-order declaration differs')
    layout=[dict(name=n,path=p,role=r) for n,p,r in authority_spec()]
    expected_members=[]
    for i,fact in enumerate(result['members'],1):
        t=TOMES[i-1];expected_members.append(dict(source_authority='primary-source-tome-'+t,receipt_authority='acquisition-receipt-tome-'+t,**fact))
    expected_profile=dict(contract='ocd-l811-retained-complete-source-profile-v1',work_id=WORK,edition_id=EDITION,source_id=SOURCE,complete_authored_works=1,members=expected_members,source_order=order,original_package_members={n:dict(authority='original-'+n,bytes=len(originals[n]),sha256=sha(originals[n])) for n in MEMBER_NAMES},authority_layout=layout,scoped_source_version_sha256=sha(source.authority_path('scoped-version').read_bytes()),mapping='Historical ID and #fragment scoping, ordered header-child scope labels, and three source-body carriers; restore one exact witness trailing space and preserve omitted document wrappers/prologs as located typed-note paragraphs. No source wording changes.',limitations=result['scope'])
    insist(profile==expected_profile,'Entire independent source profile differs')
    insist(dict(record['converter'])==dict(id='ocd-l811-retained-composite-bounded-repair',version='3',callable='_convert',implementation_path=PRODUCER,implementation_sha256=sha(source.authority_path('producer').read_bytes())),'Exact bounded repair producer binding differs')
    insist(dict(record['validator'])==dict(id='ocd-l811-whole-object-source-oracle',version='1',callable='_oracle',implementation_path=ORACLE,implementation_sha256=sha(Path(__file__).read_bytes()),import_closure_sha256=sha(source.authority_path('runtime').read_bytes())),'Exact whole-object oracle binding differs')
    scoped=json.loads(source.authority_path('scoped-version').read_bytes())
    insist(sha(source.authority_path('scoped-version').read_bytes())=='8560c5f788f4251e63c6b14f65918c85e3eca491a610c098903a7eb20678902f','Exact immutable L811 row/version snapshot differs')
    insist(scoped['row']=='L811' and scoped['work_id']==WORK and scoped['pinned_source_commit']==COMMIT and len(scoped['source_members'])==3,'Exact immutable row/source-version scope differs')
    for i,row in enumerate(scoped['source_members']):
        insist(row['position']==i+1 and row['source_sha256']==RAW_SHA[i] and row['source_bytes']==RAW_BYTES[i] and row['cts_urn']==f'urn:cts:pta:pta0003.pta020.pta-grcBibex{i+1}','Exact scoped version member differs')
    historical_raw=source.authority_path('historical-source-manifest').read_bytes()
    insist(sha(historical_raw)=='a62e68ffa8a034b3f99d6f6c0a6b88e810311fb01c2a0728149f7f0582475f54','Exact historical source contract differs')
    historical=json.loads(historical_raw)
    ancestor=dict((a['name'],a) for a in historical['authorities'])
    for tome in TOMES:
        for new,old_name in [('historical-tome-'+tome+'-source-manifest.json','source-route-manifest-tome-'+tome),('historical-tome-'+tome+'-complete-source-feature-profile.json','source-profile-tome-'+tome)]:
            payload=source.authority_path(new).read_bytes();row=ancestor[old_name]
            insist(sha(payload)==row['sha256'] and len(payload)==row['bytes'],'Exact recovered historical member authority differs')
    for name in ('complete-source-feature-profile.json','policy.json','README.source.md'):
        old_name={'complete-source-feature-profile.json':'complete-source-feature-profile','policy.json':'independent-validation-policy','README.source.md':'source-attribution'}[name]
        payload=source.authority_path('historical-composite-'+name).read_bytes();row=ancestor[old_name]
        insist(sha(payload)==row['sha256'] and len(payload)==row['bytes'],'Exact recovered historical composite authority differs')
    for role in ('converter','validator'):
        payload=source.authority_path('historical-producer' if role=='converter' else 'historical-oracle').read_bytes()
        insist(sha(payload)==historical[role]['implementation_sha256'],'Exact historical implementation lineage differs')
    historical_profile=json.loads(source.authority_path('historical-composite-complete-source-feature-profile.json').read_bytes())
    for row,tome in zip(historical_profile['members'],TOMES,strict=True):
        insist(sha(source.authority_path('attribution-tome-'+tome).read_bytes())==row['attribution_sha256'],'Exact original member attribution differs')
    # Policy and human-visible README are pinned authorities; governing values
    # are constrained independently rather than accepting arbitrary resealing.
    expected_provenance=dict(contract='ocd-l811-retained-composite-provenance-v1',work_id=WORK,edition_id=EDITION,source_id=SOURCE,manifest_row='L811',pinned_commit=COMMIT,source_scope=result['scope'],status='nonaccepted',human_acceptance='pending',rights_clearance='pending human review',publication='not-authorized',composite_producer=dict(historical_package_manifest_sha256=OLD_SHA[0],historical_tei_sha256=OLD_SHA[1],historical_producer_sha256=sha(source.authority_path('historical-producer').read_bytes()),bounded_repair=dict(record['converter']),recipe='Retained original six-member package plus exact three raw tomes and acquisition receipts; supported reconstruct_candidate CLI with the work-local bounded repair. Historical converter is lineage, not the sole current producer.'),file_level_license=dict(name='Creative Commons Attribution-ShareAlike 4.0 International',target='https://creativecommons.org/licenses/by-sa/4.0/',authority='All three exact raw publicationStmt/availability/licence fields, retained in the readable header and original member attribution files.'),source_uri_disposition=URI_DISPOSITION)
    expected_policy=dict(contract='ocd-l811-whole-object-validation-policy-v1',candidate_status='nonaccepted',provenance=expected_provenance,unresolved=[dict(id='l811-source-draft-tomes',status='source-declared',detail='Tomes I/II retain source status draft and work-in-progress statements; III status approved. All retained digital content is included; no completed print-critical-edition claim.'),dict(id='l811-literal-ambiguous-references',status='source-declared',detail=URI_DISPOSITION),dict(id='l811-human-acceptance',status='unresolved',detail='No human verification or acceptance is implied by technical source proof.'),dict(id='l811-rights-review',status='unresolved',detail='CC BY-SA 4.0 source statements and attribution retained; broader rights clearance remains pending.'),dict(id='l811-publication',status='not-authorized',detail='No publication authorization recorded.')])
    insist(policy==expected_policy,'Entire current policy/provenance/qualified unresolved scope differs')
    insist(candidate.member_bytes('README.source.md')==source.authority_path('source-attribution').read_bytes(),'Actual human-visible source README differs')
    readme=candidate.member_bytes('README.source.md').decode()
    for phrase in ('Creative Commons Attribution-ShareAlike 4.0 International','https://creativecommons.org/licenses/by-sa/4.0/','Work in progress','German prefaces','one witness attribute','no publication authorization'):
        insist(phrase in readme,'Required visible source qualification absent: '+phrase)
    for t in TOMES:insist(source.authority_path('attribution-tome-'+t).read_bytes().decode().strip() in readme,'Exact source member attribution missing: '+t)
    insist(candidate.member_bytes('provenance.json')==enc(expected_provenance) and candidate.member_bytes('unresolved.jsonl')==b''.join(enc(r) for r in policy['unresolved']),'Actual candidate provenance/unresolved payload differs')
    expected_account=dict(contract='ocd-l811-retained-composite-bounded-repair-v1',work_id=WORK,edition_id=EDITION,source_id=SOURCE,complete_authored_works=1,source_tomes=3,source_manifest_sha256=source.sha256,original_component_sha256=OLD_SHA[1],candidate_tei_sha256=result['actual_tei_sha256'],repairs=result['repairs'],producer=dict(record['converter']),source_profile_sha256=sha(source.authority_path('complete-source-feature-profile').read_bytes()),policy_sha256=sha(source.authority_path('independent-validation-policy').read_bytes()))
    insist(candidate.member_bytes('source-accountability.json')==enc(expected_account),'Complete actual repair ledger differs')
    from ocd_kernel.tei.validate import validate_file
    errors=validate_file(candidate.path/'content.tei.xml');insist(not errors,'Actual candidate P5 fails: '+str(errors))
    result['actual_execution_paths']=guard(source);return result

def _oracle(source,candidate):
    result=check(source,candidate)
    primaries=sorted([dict(name=a['name'],path=a['path'],bytes=a['bytes'],sha256=a['sha256']) for a in source.record['authorities'] if a['role']=='primary-source'],key=lambda a:(a['path'],a['name']))
    att=dict(status='pass',oracle_id='ocd-l811-whole-object-source-oracle',oracle_version='1',implementation_sha256=sha(Path(__file__).read_bytes()),import_closure_sha256=sha(source.authority_path('runtime').read_bytes()),runtime=f'{platform.python_implementation()} {platform.python_version()} ({Path(__import__("sys").executable).resolve(strict=True)})',source_manifest_sha256=source.sha256,candidate_sha256=candidate.sha256,source_sha256=sha(enc(dict(contract='ocd-source-member-set-v1',members=primaries))),profile_sha256=sha(source.authority_path('complete-source-feature-profile').read_bytes()),policy_sha256=sha(source.authority_path('independent-validation-policy').read_bytes()),xsd_sha256=sha(source.authority_path('tei-p5-xsd').read_bytes()),package_schema_sha256=sha(source.authority_path('candidate-package-schema').read_bytes()),findings=[])
    att['result_sha256']=sha(enc(att));return att

_oracle.oracle_id='ocd-l811-whole-object-source-oracle'
_oracle.oracle_version='1'
_oracle.implementation_path=Path(__file__).resolve()
