"""Opt-in complete retained BCP1662 service/calendar members with native roles.

The source edition is explicitly partial. Generated role tokens annotate literal
speaker labels; they are not person declarations or inferred response links.
"""
from hashlib import sha256
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from typing import Mapping
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.native_content import project_content, readable_content

PROFILE='ocd-liturgies-bcp1662-retained-members-v1'
IDENTITY={'work_id':'bcp-1662','textual_form_id':'bcp-1662-retained-electronic','edition_id':'bcp-1662-retained-electronic-witness'}
NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
MEMBERS=('daily__morning.html','daily__evening.html','daily__athanasian.html','daily__litany.html','daily__prayers.html','communion__index.html','baptism__index.html','baptism__riper.html','baptism__private.html','baptism__catechism.html','baptism__confirm.html','occasions__marriage.html','occasion__sick_visit.html','occasions__burial.html','occasions__women.html','occasions__commination.html','misc__sea.html','ordinal__deacons.html','ordinal__priests.html','ordinal__bishops.html','xmas.html','lent.html','easter.html','trinity.html','saints.html')
ROLES=('answer','minister','question','priest','bishop','people','archbishop','catechist')
ROOT=Path(__file__).resolve().parents[3]
SCHEMA=ROOT/'schemas/v2/categories/liturgies.schema.json'
COMMON=ROOT/'schemas/v2/public-row.schema.json'
NATIVE=ROOT/'schemas/v2/native-content.schema.json'
HEADER={'teiHeader':set(),'fileDesc':set(),'titleStmt':set(),'title':{XML+'id','type'},'publicationStmt':set(),'p':{XML+'id'},'sourceDesc':set(),'bibl':{'type'},'ptr':{'target','type'},'idno':{'type'},'note':{'type'},'revisionDesc':set(),'change':{XML+'id','when'}}
CHILDREN={'teiHeader':{'fileDesc','revisionDesc'},'fileDesc':{'titleStmt','publicationStmt','sourceDesc'},'titleStmt':{'title'},'publicationStmt':{'p'},'sourceDesc':{'bibl'},'bibl':{'title','ptr','idno','note'},'revisionDesc':{'change'}}

def _hash(raw):
    return sha256(raw).hexdigest()

def _json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()

def _walk(root):
    """Linear preorder inventory retaining exact text, tails and ordered attributes."""
    rows=[]
    def visit(n,path,in_header=False):
        tag=n.tag[len(NS):]
        header=in_header or tag=='teiHeader'
        rows.append(dict(ordinal=len(rows)+1,tei_path=path,tag=tag,role='private-header' if header else 'mapped-source',attributes=[[k,v] for k,v in n.attrib.items()],text_sha256=_hash((n.text or '').encode()),tail_sha256=_hash((n.tail or '').encode())))
        counts={}
        for c in n:
            name=c.tag[len(NS):]; counts[name]=counts.get(name,0)+1
            visit(c,f'{path}/{name}[{counts[name]}]',header)
    visit(root,'/TEI')
    return rows

def _parts(root):
    if root.tag!=NS+'TEI' or root.attrib or [n.tag for n in root]!=[NS+'teiHeader',NS+'text']:
        raise PipelineError('BCP1662 namespace/envelope differs')
    h,text=list(root)
    if [n.tag for n in h] not in ([NS+'fileDesc'],[NS+'fileDesc',NS+'revisionDesc']):
        raise PipelineError('BCP1662 header envelope differs')
    if [n.tag for n in h[0]]!=[NS+'titleStmt',NS+'publicationStmt',NS+'sourceDesc']:
        raise PipelineError('BCP1662 fileDesc envelope differs')
    for n in h.iter():
        if not isinstance(n.tag,str) or not n.tag.startswith(NS):
            raise PipelineError('BCP1662 header namespace differs')
        tag=n.tag[len(NS):]
        if tag not in HEADER or set(n.attrib)-HEADER[tag] or any(c.tag not in {NS+t for t in CHILDREN.get(tag,set())} for c in n):
            raise PipelineError('BCP1662 unsupported header structure/attribute')
        if tag in CHILDREN and ((n.text or '').strip() or any((c.tail or '').strip() for c in n)):
            raise PipelineError('BCP1662 loose header text differs')
    if text.attrib or [n.tag for n in text]!=[NS+'body'] or text[0].attrib:
        raise PipelineError('BCP1662 requires one native body')
    body=text[0]
    if len(body)!=25:
        raise PipelineError('BCP1662 complete member count differs')
    for i,(n,name) in enumerate(zip(body,MEMBERS)):
        if n.tag!=NS+'div' or n.attrib!={'type':'service' if i<20 else 'calendar-part','n':name} or not len(n) or n[0].tag!=NS+'head':
            raise PipelineError('BCP1662 complete member order/type/heading differs')
    for n in (root,text,body):
        if (n.text or '').strip() or any((c.tail or '').strip() for c in n):
            raise PipelineError('BCP1662 unassigned envelope text')
    speeches=list(body.iter(NS+'sp'))
    if len(speeches)!=255:
        raise PipelineError('BCP1662 complete role census differs')
    for n in speeches:
        if set(n.attrib)!={'ana'} or n.get('ana') not in {'source-role-token:#bcp-role-'+r for r in ROLES}:
            raise PipelineError('BCP1662 literal non-person role annotation differs')
    return list(body)

def _links(member):
    targets={}
    nodes=[]
    def visit(n,path):
        nodes.append((n,path))
        xid=n.get(XML+'id')
        if xid:
            if xid in targets:
                raise PipelineError('BCP1662 duplicate source ID')
            targets[xid]=(n,path)
        for i,c in enumerate(n,1):
            visit(c,path+[i])
    visit(member,[])
    result=[]
    for n,path in nodes:
        for attr in ('corresp','sameAs'):
            if n.get(attr) is None:
                continue
            if (n.tag,n.get('type'),attr) not in ((NS+'seg','source-continuation','corresp'),(NS+'div','alternative-marker','corresp')):
                raise PipelineError('BCP1662 unknown source link semantics')
            values=n.get(attr).split()
            if not values or len(values)!=len(set(values)):
                raise PipelineError('BCP1662 empty/duplicate source targets')
            out=[]
            for value in values:
                if not value.startswith('#') or value[1:] not in targets:
                    raise PipelineError('BCP1662 unresolved source target')
                target,target_path=targets[value[1:]]
                if target is n:
                    raise PipelineError('BCP1662 self source target')
                out.append({'token':_hash(value[1:].encode())[:20],'path':target_path})
            result.append({'kind':'continuation' if n.tag==NS+'seg' else 'alternative','path':path,'targets':out})
    return result

def project_document(tei_path,*,identity,language,representation_revision,edition_title,projection_profile,source_url=None,source_sha256=None,retained_sha256=None):
    if projection_profile!=PROFILE or dict(identity)!=IDENTITY or language!='en':
        raise PipelineError('BCP1662 exact identity/language/profile required')
    path=Path(tei_path); raw=path.read_bytes()
    if any(t in raw.upper() for t in (b'<!DOCTYPE',b'<!ENTITY',b'<!--')) or re.search(rb'<\?(?!xml(?:\s|\?>))',raw,re.I):
        raise PipelineError('BCP1662 declarations/comments/instructions are unsupported')
    try:
        doc=ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))
    except ET.ParseError as exc:
        raise PipelineError('Invalid BCP1662 TEI') from exc
    units=_parts(doc)
    ids=[n.get(XML+'id') for n in doc.iter() if n.get(XML+'id')]
    if len(ids)!=len(set(ids)):
        raise PipelineError('BCP1662 duplicate document ID')
    from ocd_kernel.projection.categories.liturgies import _source_binding_et,_validate_rows
    binding=_source_binding_et(doc,source_url=source_url,source_sha256=source_sha256,retained_sha256=retained_sha256)
    rows=[]; anchors=[]
    for i,n in enumerate(units,1):
        structure=[project_content(n)]
        text=readable_content(structure[0])
        links=_links(n)
        token=_hash(MEMBERS[i-1].encode())[:20]
        row=dict(IDENTITY,record_id=f'{IDENTITY["edition_id"]}:liturgy-member:{token}',sequence=i,category='liturgies',language=language,text=text,representation_revision=representation_revision,provenance={'edition_title':edition_title},notes=[],references=[],row_profile=PROFILE,member_id=token,member_number=i,member_title=' '.join(''.join(n[0].itertext()).split()),member_kind=n.get('type'),response_model='literal-role-annotations-without-person-or-response-links',content_format='ocd-native-content-v1',structure=structure,source_links=links,locator={'kind':'liturgy-member','text_part':'body','member':i,'member_kind':n.get('type')})
        rows.append(row)
        anchors.append(dict(record_id=row['record_id'],tei_path=f'/TEI/text/body/div[{i}]',text_sha256=_hash(text.encode()),structure_sha256=_hash(_json(structure)),source_links_sha256=_hash(_json(links))))
    if sum(len(link['targets']) for row in rows for link in row['source_links'])!=117:
        raise PipelineError('BCP1662 complete117source target occurrences differ')
    _validate_rows(rows)
    receipt=dict(mapping_version=PROFILE,assembler_version='ocd-liturgies-assembler-provisional-v1',projection_profile=PROFILE,master_sha256=_hash(raw),source_binding=binding,policy_sha256=_hash(SCHEMA.read_bytes()),common_schema_sha256=_hash(COMMON.read_bytes()),native_schema_sha256=_hash(NATIVE.read_bytes()),output_sha256=_hash(_json(rows)),row_count=25,anchors=anchors,inventory=_walk(doc),warnings=['Complete declared retained partial electronic edition; printed scope and later1992wording remain qualified.','Role tokens are non-person annotations, not resolving authorities or response links.','Source links use element-child paths excluding text nodes and source-ID hashes.'],exclusions=[{'tei_path':'/TEI/teiHeader','reason':'private-bibliographic-header'}],unsupported=[],independent_check={'status':'pending'})
    return dict(rows=rows,receipt=receipt,mapping_version=PROFILE,assembler_version=receipt['assembler_version'],master_sha256=receipt['master_sha256'],source_binding=binding,anchors=anchors,inventory=receipt['inventory'],warnings=receipt['warnings'],exclusions=receipt['exclusions'],unsupported=[],independent_check=receipt['independent_check'])
