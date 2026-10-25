"""Exact opt-in whole retained BCP1549 electronic members, including context.

This projects a faithful TEI; the separately bound HTML oracle proves source
conservation. Native labels assert neither people nor response relationships.
"""
from hashlib import sha256
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.native_content import project_content,readable_content

PROFILE='ocd-liturgies-bcp1549-retained-members-v1'
SOURCE_PROFILE='ocd-liturgies-bcp-retained-html-v1'
IDENTITY={'work_id':'bcp-1549','textual_form_id':'bcp-1549-retained-electronic','edition_id':'bcp-1549-retained-electronic-witness'}
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'
MEMBERS=('BCP_1549.htm','BCP_1549&52_Intro.htm','front_matter_1549.htm','Kalendar_1549.htm','Matins_1549.htm','Evensong_1549.htm','collects_epistles_gospels_1549.htm','Readings_Advent_1549.htm','Readings_Xmas_1549.htm','Readings_Epiphany_1549.htm','Readings_Lent_1549.htm','Readings_HolyWeek_1549.htm','Reading_EasterWeek_1549.htm','Readings_EasterSeason_1549.htm','Readings_Ascension&Whitsuntide_1549.htm','Readings_TrinityA_1549.htm','Readings_TrinityB_1549.htm','Readings_TrinityC_1549.htm','Readings_SaintsA_1549.htm','Readings_SaintsB_1549.htm','Communion_1549.htm','Litany_1549.htm','Baptism_1549.htm','Confirmation_1549.htm','Marriage_1549.htm','Visitation_Sick_1549.htm','Burial_1549.htm','Purification_Women_1549.htm','Ashwednesday_1549.htm','Of_Ceremonies_1549.htm','Ordinal_1549.htm','Bishops_1549.htm','Priests_1549.htm','Deacons_1549.htm')
ROOT=Path(__file__).resolve().parents[3]
SCHEMA=ROOT/'schemas/v2/categories/liturgies.schema.json';COMMON=ROOT/'schemas/v2/public-row.schema.json';NATIVE=ROOT/'schemas/v2/native-content.schema.json'
HEADER={'teiHeader':set(),'fileDesc':set(),'titleStmt':set(),'title':{XML+'id','type'},'publicationStmt':set(),'p':{XML+'id'},'sourceDesc':set(),'bibl':{'type'},'ptr':{'target','type'},'idno':{'type'},'note':{'type'},'revisionDesc':set(),'change':{XML+'id','when'}}
CHILDREN={'teiHeader':{'fileDesc','revisionDesc'},'fileDesc':{'titleStmt','publicationStmt','sourceDesc'},'titleStmt':{'title'},'publicationStmt':{'p'},'sourceDesc':{'bibl'},'bibl':{'title','ptr','idno','note'},'revisionDesc':{'change'}}

def _hash(raw):return sha256(raw).hexdigest()
def _json(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()

def _parts(root):
    if root.tag!=NS+'TEI' or root.attrib or [n.tag for n in root]!=[NS+'teiHeader',NS+'text']:
        raise PipelineError('BCP1549 exact namespace/envelope differs')
    header,text=root
    if [n.tag for n in header] not in ([NS+'fileDesc'],[NS+'fileDesc',NS+'revisionDesc']) or [n.tag for n in header[0]]!=[NS+'titleStmt',NS+'publicationStmt',NS+'sourceDesc']:
        raise PipelineError('BCP1549 qualified header envelope differs')
    for n in header.iter():
        if not isinstance(n.tag,str) or not n.tag.startswith(NS):raise PipelineError('BCP1549 header namespace differs')
        tag=n.tag[len(NS):]
        if tag not in HEADER or set(n.attrib)-HEADER[tag] or any(c.tag not in {NS+t for t in CHILDREN.get(tag,set())} for c in n):
            raise PipelineError('BCP1549 unsupported header structure/attribute')
        if tag in CHILDREN and ((n.text or '').strip() or any((c.tail or '').strip() for c in n)):raise PipelineError('BCP1549 loose header text differs')
    if text.attrib or [n.tag for n in text]!=[NS+'body'] or text[0].attrib:raise PipelineError('BCP1549 requires one complete native body')
    body=text[0]
    if len(body)!=34:raise PipelineError('BCP1549 complete34member count differs')
    for member,name in zip(body,MEMBERS):
        attrs={'type':'source-member','n':name,XML+'id':'bcp1549-member-'+_hash(name.encode())[:12]}
        if member.tag!=NS+'div' or dict(member.attrib)!=attrs or len(member)!=2 or member[0].tag!=NS+'head' or member[0].attrib or len(member[0]) or not (member[0].text or '').strip() or member[1].tag!=NS+'ab' or member[1].get('type')!='source-block' or member[1].get('subtype')!='html-body':
            raise PipelineError('BCP1549 exact member order/title/body differs')
    for n in (root,text,body):
        if (n.text or '').strip() or any((c.tail or '').strip() for c in n):raise PipelineError('BCP1549 unassigned envelope text')
    ids=[n.get(XML+'id') for n in root.iter() if n.get(XML+'id')]
    if len(ids)!=len(set(ids)):raise PipelineError('BCP1549 duplicate source identity')
    return list(body)

def _walk(root):
    rows=[]
    def visit(n,path,private=False):
        tag=n.tag[len(NS):];private=private or tag=='teiHeader'
        rows.append(dict(ordinal=len(rows)+1,tei_path=path,tag=tag,role='private-header' if private else 'mapped-source',attributes=[[k,v] for k,v in n.attrib.items()],text_sha256=_hash((n.text or '').encode()),tail_sha256=_hash((n.tail or '').encode())))
        counts={}
        for child in n:
            label=child.tag[len(NS):];counts[label]=counts.get(label,0)+1
            visit(child,f'{path}/{label}[{counts[label]}]',private)
    visit(root,'/TEI');return rows

def project_document(tei_path,*,identity,language,representation_revision,edition_title,projection_profile,source_url=None,source_sha256=None,retained_sha256=None):
    if projection_profile!=PROFILE or dict(identity)!=IDENTITY or language!='en':raise PipelineError('BCP1549 exact identity/language/profile required')
    raw=Path(tei_path).read_bytes()
    if any(q in raw.upper() for q in (b'<!DOCTYPE',b'<!ENTITY',b'<!--')) or re.search(rb'<\?(?!xml(?:\s|\?>))',raw,re.I):raise PipelineError('BCP1549 declarations/comments/instructions unsupported')
    try:doc=ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))
    except ET.ParseError as error:raise PipelineError('Invalid BCP1549 TEI') from error
    members=_parts(doc)
    from ocd_kernel.projection.categories.liturgies import _source_binding_et,_validate_rows
    binding=_source_binding_et(doc,source_url=source_url,source_sha256=source_sha256,retained_sha256=retained_sha256)
    rows=[];anchors=[]
    for i,(member,name) in enumerate(zip(members,MEMBERS),1):
        structure=[project_content(member,source_profile=SOURCE_PROFILE)];text=readable_content(structure[0]);token=_hash(name.encode())[:20]
        row=dict(IDENTITY,record_id=f'{IDENTITY["edition_id"]}:liturgy-member:{token}',sequence=i,category='liturgies',language=language,text=text,representation_revision=representation_revision,provenance={'edition_title':edition_title},notes=[],references=[],row_profile=PROFILE,member_id=token,member_number=i,member_title=' '.join((member[0].text or '').split()),member_kind='source-member',response_model='source-native-labels-without-response-inference',content_format='ocd-native-content-v1',structure=structure,source_links=[],locator={'kind':'liturgy-member','text_part':'body','member':i,'member_kind':'source-member'})
        rows.append(row);anchors.append(dict(record_id=row['record_id'],tei_path=f'/TEI/text/body/div[{i}]',text_sha256=_hash(text.encode()),structure_sha256=_hash(_json(structure)),source_links_sha256=_hash(_json([]))))
    _validate_rows(rows)
    warnings=['Complete34member retained electronic envelope; shared introduction/readings and1550/comparative ordinal context are explicit, not a pure1549print witness.','Literal HTML labels/formatting assert no people or response links.','Source hrefs resolve against original source-member URLs; linked image/PDF payloads unretained.','Source198numeric bullets and1em dash follow exact recorded HTML character decoding; original bytes/lexemes remain private evidence.']
    exclusions=[{'tei_path':'/TEI/teiHeader','reason':'private-bibliographic-header'}]
    receipt=dict(mapping_version=PROFILE,assembler_version='ocd-liturgies-assembler-provisional-v1',projection_profile=PROFILE,master_sha256=_hash(raw),source_binding=binding,policy_sha256=_hash(SCHEMA.read_bytes()),common_schema_sha256=_hash(COMMON.read_bytes()),native_schema_sha256=_hash(NATIVE.read_bytes()),output_sha256=_hash(_json(rows)),row_count=34,anchors=anchors,inventory=_walk(doc),warnings=warnings,exclusions=exclusions,unsupported=[],independent_check={'status':'pending'})
    return dict(rows=rows,receipt=receipt,mapping_version=PROFILE,assembler_version=receipt['assembler_version'],master_sha256=receipt['master_sha256'],source_binding=binding,anchors=anchors,inventory=receipt['inventory'],warnings=warnings,exclusions=exclusions,unsupported=[],independent_check=receipt['independent_check'])
