"""Independent lxml reconstruction of the retained BCP1662 public profile.

This checker does not import the producer. Actual HTML source fidelity remains
the separately bound complete source oracle; these checks reconstruct projection
rows and the private inventory from the exact TEI master.
"""
from hashlib import sha256
import json
from pathlib import Path
import re
from lxml import etree
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.native_content_check import observe_content

PROFILE='ocd-liturgies-bcp1662-retained-members-v1'
IDENTITY={'work_id':'bcp-1662','textual_form_id':'bcp-1662-retained-electronic','edition_id':'bcp-1662-retained-electronic-witness'}
TEI='http://www.tei-c.org/ns/1.0'
NS='{'+TEI+'}'
XML='{http://www.w3.org/XML/1998/namespace}'
MEMBERS=('daily__morning.html','daily__evening.html','daily__athanasian.html','daily__litany.html','daily__prayers.html','communion__index.html','baptism__index.html','baptism__riper.html','baptism__private.html','baptism__catechism.html','baptism__confirm.html','occasions__marriage.html','occasion__sick_visit.html','occasions__burial.html','occasions__women.html','occasions__commination.html','misc__sea.html','ordinal__deacons.html','ordinal__priests.html','ordinal__bishops.html','xmas.html','lent.html','easter.html','trinity.html','saints.html')
ROLES=('answer','minister','question','priest','bishop','people','archbishop','catechist')
ROOT=Path(__file__).resolve().parents[3]
SCHEMA=ROOT/'schemas/v2/categories/liturgies.schema.json'
COMMON=ROOT/'schemas/v2/public-row.schema.json'
NATIVE=ROOT/'schemas/v2/native-content.schema.json'
HEADER={'teiHeader':set(),'fileDesc':set(),'titleStmt':set(),'title':{XML+'id','type'},'publicationStmt':set(),'p':{XML+'id'},'sourceDesc':set(),'bibl':{'type'},'ptr':{'target','type'},'idno':{'type'},'note':{'type'},'revisionDesc':set(),'change':{XML+'id','when'}}
CHILDREN={'teiHeader':{'fileDesc','revisionDesc'},'fileDesc':{'titleStmt','publicationStmt','sourceDesc'},'titleStmt':{'title'},'publicationStmt':{'p'},'sourceDesc':{'bibl'},'bibl':{'title','ptr','idno','note'},'revisionDesc':{'change'}}

def _sha(raw):
    return sha256(raw).hexdigest()

def _json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()

def _inspect(doc):
    if doc.tag!=NS+'TEI' or dict(doc.attrib) or [n.tag for n in doc]!=[NS+'teiHeader',NS+'text']:
        raise PipelineError('BCP1662 namespace/envelope differs')
    header=doc[0]
    if [n.tag for n in header] not in ([NS+'fileDesc'],[NS+'fileDesc',NS+'revisionDesc']):
        raise PipelineError('BCP1662 header envelope differs')
    if [n.tag for n in header[0]]!=[NS+'titleStmt',NS+'publicationStmt',NS+'sourceDesc']:
        raise PipelineError('BCP1662 fileDesc envelope differs')
    for n in header.iter():
        if not isinstance(n.tag,str) or etree.QName(n).namespace!=TEI:
            raise PipelineError('BCP1662 header namespace differs')
        name=etree.QName(n).localname
        if name not in HEADER or set(n.attrib)-HEADER[name] or any(c.tag not in {NS+t for t in CHILDREN.get(name,set())} for c in n):
            raise PipelineError('BCP1662 unsupported header structure/attribute')
        if name in CHILDREN and ((n.text or '').strip() or any((c.tail or '').strip() for c in n)):
            raise PipelineError('BCP1662 loose header text differs')
    text=doc[1]
    if dict(text.attrib) or [n.tag for n in text]!=[NS+'body'] or dict(text[0].attrib):
        raise PipelineError('BCP1662 requires one native body')
    body=text[0]
    if len(body)!=25:
        raise PipelineError('BCP1662 complete member count differs')
    for index,node in enumerate(body):
        if node.tag!=NS+'div' or dict(node.attrib)!={'type':'service' if index<20 else 'calendar-part','n':MEMBERS[index]} or len(node)==0 or node[0].tag!=NS+'head':
            raise PipelineError('BCP1662 complete member order/type/heading differs')
    for n in (doc,text,body):
        if (n.text or '').strip() or any((c.tail or '').strip() for c in n):
            raise PipelineError('BCP1662 unassigned envelope text')
    speeches=list(body.iter(NS+'sp'))
    if len(speeches)!=255:
        raise PipelineError('BCP1662 complete role census differs')
    for n in speeches:
        role=n.get('ana')
        if dict(n.attrib)!={'ana':role} or role not in tuple('source-role-token:#bcp-role-'+r for r in ROLES):
            raise PipelineError('BCP1662 literal non-person role annotation differs')
    return list(body)

def _paths(doc):
    paths={doc:'/TEI'}
    for node in doc.iter():
        tally={}
        for child in node:
            if not isinstance(child.tag,str) or etree.QName(child).namespace!=TEI:
                raise PipelineError('BCP1662 body namespace/instruction differs')
            tag=etree.QName(child).localname
            tally[tag]=tally.get(tag,0)+1
            paths[child]=paths[node]+'/'+tag+'['+str(tally[tag])+']'
    inventory=[]
    for index,node in enumerate(doc.iter(),1):
        name=etree.QName(node).localname
        header=name=='teiHeader' or any(a.tag==NS+'teiHeader' for a in node.iterancestors())
        inventory.append(dict(ordinal=index,tei_path=paths[node],tag=name,role='private-header' if header else 'mapped-source',attributes=[[k,v] for k,v in node.attrib.items()],text_sha256=_sha((node.text or '').encode()),tail_sha256=_sha((node.tail or '').encode())))
    return inventory

def _correspondence(unit):
    position={unit:[]}
    indexed={}
    for parent in unit.iter():
        xid=parent.get(XML+'id')
        if xid:
            if xid in indexed:
                raise PipelineError('BCP1662 duplicate source ID')
            indexed[xid]=parent
        for offset,child in enumerate(parent,1):
            position[child]=position[parent]+[offset]
    observed=[]
    for node in unit.iter():
        for attribute in ('corresp','sameAs'):
            literal=node.get(attribute)
            if literal is None:
                continue
            allowed=(node.tag==NS+'seg' and node.get('type')=='source-continuation' or node.tag==NS+'div' and node.get('type')=='alternative-marker') and attribute=='corresp'
            if not allowed:
                raise PipelineError('BCP1662 unknown source link semantics')
            pieces=literal.split()
            if len(pieces)==0 or len(pieces)!=len(set(pieces)):
                raise PipelineError('BCP1662 empty/duplicate source targets')
            targets=[]
            for pointer in pieces:
                key=pointer[1:]
                if not pointer.startswith('#') or key not in indexed:
                    raise PipelineError('BCP1662 unresolved source target')
                target=indexed[key]
                if target is node:
                    raise PipelineError('BCP1662 self source target')
                targets.append(dict(token=_sha(key.encode())[:20],path=position[target]))
            observed.append(dict(kind='continuation' if node.tag==NS+'seg' else 'alternative',path=position[node],targets=targets))
    return observed

def _expected(path,*,identity,language,representation_revision,edition_title,projection_profile,source_url,source_sha256,retained_sha256):
    if dict(identity)!=IDENTITY or language!='en' or projection_profile!=PROFILE:
        raise PipelineError('BCP1662 exact identity/language/profile required')
    raw=path.read_bytes()
    if any(t in raw.upper() for t in (b'<!DOCTYPE',b'<!ENTITY',b'<!--')) or re.search(rb'<\?(?!xml(?:\s|\?>))',raw,re.I):
        raise PipelineError('BCP1662 declarations/comments/instructions are unsupported')
    doc=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
    units=_inspect(doc)
    ids=doc.xpath('//@xml:id')
    if len(ids)!=len(set(ids)):
        raise PipelineError('BCP1662 duplicate document ID')
    from ocd_kernel.projection.categories.liturgies import _source_binding_lxml
    binding=_source_binding_lxml(doc,source_url=source_url,source_sha256=source_sha256,retained_sha256=retained_sha256)
    rows=[]; anchors=[]
    for number,unit in enumerate(units,1):
        content,reading=observe_content(etree.tostring(unit,with_tail=False))
        structure=[content]
        links=_correspondence(unit)
        token=_sha(MEMBERS[number-1].encode())[:20]
        row=dict(IDENTITY,record_id=f'{IDENTITY["edition_id"]}:liturgy-member:{token}',sequence=number,category='liturgies',language=language,text=reading,representation_revision=representation_revision,provenance={'edition_title':edition_title},notes=[],references=[],row_profile=PROFILE,member_id=token,member_number=number,member_title=' '.join(''.join(unit[0].itertext()).split()),member_kind=unit.get('type'),response_model='literal-role-annotations-without-person-or-response-links',content_format='ocd-native-content-v1',structure=structure,source_links=links,locator={'kind':'liturgy-member','text_part':'body','member':number,'member_kind':unit.get('type')})
        rows.append(row)
        anchors.append(dict(record_id=row['record_id'],tei_path=f'/TEI/text/body/div[{number}]',text_sha256=_sha(reading.encode()),structure_sha256=_sha(_json(structure)),source_links_sha256=_sha(_json(links))))
    if sum(len(x['targets']) for r in rows for x in r['source_links'])!=117:
        raise PipelineError('BCP1662 complete117source target occurrences differ')
    receipt=dict(mapping_version=PROFILE,assembler_version='ocd-liturgies-assembler-provisional-v1',projection_profile=PROFILE,master_sha256=_sha(raw),source_binding=binding,policy_sha256=_sha(SCHEMA.read_bytes()),common_schema_sha256=_sha(COMMON.read_bytes()),native_schema_sha256=_sha(NATIVE.read_bytes()),output_sha256=_sha(_json(rows)),row_count=25,anchors=anchors,inventory=_paths(doc),warnings=['Complete declared retained partial electronic edition; printed scope and later1992wording remain qualified.','Role tokens are non-person annotations, not resolving authorities or response links.','Source links use element-child paths excluding text nodes and source-ID hashes.'],exclusions=[{'tei_path':'/TEI/teiHeader','reason':'private-bibliographic-header'}],unsupported=[],independent_check={'status':'pending'})
    return rows,receipt

def verify_document(tei_path,rows,receipt=None,*,identity,language,representation_revision,edition_title,projection_profile,source_url=None,source_sha256=None,retained_sha256=None):
    try:
        expected,proof=_expected(Path(tei_path),identity=identity,language=language,representation_revision=representation_revision,edition_title=edition_title,projection_profile=projection_profile,source_url=source_url,source_sha256=source_sha256,retained_sha256=retained_sha256)
        errors=[]
        if rows!=expected:
            errors.append('BCP1662 member source correspondence: text/roles/structure/order/links differ')
        if receipt is None or dict(receipt)!=proof:
            errors.append('BCP1662 complete source correspondence receipt differs')
        from ocd_kernel.projection.categories.liturgies import _validator
        validator=_validator()
        for i,row in enumerate(rows,1):
            errors.extend('BCP1662 schema row '+str(i)+': '+e.message for e in validator.iter_errors(row))
        return errors
    except (OSError,ValueError,TypeError,KeyError,PipelineError,etree.XMLSyntaxError) as exc:
        return [str(exc)]
