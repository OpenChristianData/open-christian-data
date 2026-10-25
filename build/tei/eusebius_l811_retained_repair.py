"""Bounded source-backed repair of the existing L811 three-tome TEI.

The historical readable composition remains the component. Restore one source
attribute's trailing whitespace at its exact structural locus and append located
source-shell administration. No source download or shared PTA producer is used.
"""
from pathlib import Path
from hashlib import sha256
import json,re
from xml.parsers import expat
from lxml import etree
from ocd_kernel.reconstruction import SourceManifest
from build.tei.eusebius_l811_runtime import guard

TEI='http://www.tei-c.org/ns/1.0';NS='{'+TEI+'}';XML='{http://www.w3.org/XML/1998/namespace}'
OLD_TEI_SHA='a3948866bb7504c12e542efcbca644b51c7f055867af5bd283b5a94e808780f4'
RAW_SHA=['19d6a6a8554570a5519d44e554ab27c25170ee1c71d00d15753dcdfd3c44b535','0b721fed3724ebfd62b343740fbe28569676bfb1e51be137e2b39c0d0ec2abcf','6c50c98cb529b2b46a7d2811592bf024a153bf8c392a3ad27a37d1723fb3cfd2']
WIT_PATH=[2,40,3,2,26,1,2,1]
ID_PREFIX='l811-t1-'

def digest(raw):return sha256(raw).hexdigest()
def encode(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def parse(raw):return etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,recover=False))

def administration(raw,receipt,position):
    tree=parse(raw);header=tree.find(NS+'teiHeader');file=header.find(NS+'fileDesc');body=tree.find(NS+'text/'+NS+'body')
    nodes=[tree,header,file,*file,*list(header)[1:],tree.find(NS+'text'),body]
    fields=[dict(path=tree.getroottree().getpath(n),tag=n.tag,attributes=dict(n.attrib),text=n.text,tail=n.tail) for n in nodes]
    return dict(tome=['I','II','III'][position-1],source_sha256=digest(raw),source_bytes=len(raw),
        literal_document_prefix=raw[:raw.index(b'<TEI')].decode('utf-8'),literal_document_suffix=raw[raw.rindex(b'</TEI>')+6:].decode('utf-8'),
        root_namespace_bindings=tree.nsmap,source_shell_fields=fields,
        source_uri_context=dict(source_url=receipt['source_url'],final_url=receipt['final_url'],reader_url=receipt['reader_url'],pinned_commit=receipt['pinned_commit'],
            disposition='Literal source reference values remain unchanged except already-declared #fragment ID scoping. Bare target identifiers and bibliographic corresp labels are not converted into fabricated HTTP links. The acquisition URL is the retained document context, not evidence that every ambiguous source target resolves.'),
        source_quality_statements=[''.join(n.itertext()) for n in file.findall(NS+'editionStmt/'+NS+'p')],
        field_disposition='Original wrapper attributes, direct text and tails and document prefix/suffix remain exact readable administration; original header child carriers and body retain their source-defined attachment under the historical three-tome mapping.')

def _start_tags(raw):
    offsets=[];parser=expat.ParserCreate();parser.StartElementHandler=lambda name,attrs:offsets.append(parser.CurrentByteIndex)
    parser.ExternalEntityRefHandler=lambda *args:0;parser.Parse(raw,True);return offsets

def _tag_end(raw,start):
    quote=None
    for offset in range(start,len(raw)):
        byte=raw[offset]
        if quote is not None:
            if byte==quote:quote=None
        elif byte in (34,39):quote=byte
        elif byte==62:return offset+1
    raise ValueError('Unclosed actual retained start tag')

def repair(original,raw_members,receipts):
    if digest(original)!=OLD_TEI_SHA or len(raw_members)!=3 or len(receipts)!=3:raise ValueError('Exact retained original L811 component required')
    for position,raw in enumerate(raw_members,1):
        if digest(raw)!=RAW_SHA[position-1]:raise ValueError('Exact primary tome pin differs')
        receipt=receipts[position-1]
        if receipt['retained_file']['sha256']!=digest(raw) or receipt['retained_file']['bytes']!=len(raw) or receipt['source_url']!=receipt['final_url'] or receipt['pinned_commit']!='ef861ab391ea35c5d85b41dd8d7ba2bf65530b21':raise ValueError('Exact retained source URI/acquisition binding differs')
    tree=parse(original);source=parse(raw_members[0]);old=tree.find(NS+'text/'+NS+'body')[0][1];before=source.find(NS+'text/'+NS+'body')
    for ordinal in WIT_PATH:old=old[ordinal-1];before=before[ordinal-1]
    if old.tag!=before.tag or not before.get('wit','').endswith(' '):raise ValueError('Exact located witness field preimage differs')
    idmap={n.get(XML+'id'):ID_PREFIX+n.get(XML+'id') for n in source.iter() if isinstance(n.tag,str) and n.get(XML+'id')}
    after=re.sub(r'(?<!\S)#([^\s]+)',lambda m:'#'+idmap.get(m.group(1),m.group(1)),before.get('wit'))
    if old.get('wit')!=after.rstrip(' ') or not after.endswith(' ') or after.endswith('  '):raise ValueError('Single source trailing-space repair differs')
    nodes=[n for n in tree.iter() if isinstance(n.tag,str)];ordinal=next(i for i,n in enumerate(nodes) if n is old);start=_start_tags(original)[ordinal];end=_tag_end(original,start);tag=original[start:end]
    old_attr=('wit="'+old.get('wit')+'"').encode();new_attr=('wit="'+after+'"').encode()
    if tag.count(old_attr)!=1:raise ValueError('Exact lexical witness attribute at located tag differs')
    repaired=original[:start]+tag.replace(old_attr,new_attr,1)+original[end:]
    ledger=[dict(family='source-witness-attribute-whitespace',tome='I',source_path='/TEI/text/body/'+ '/'.join(map(str,WIT_PATH)),candidate_path=tree.getroottree().getpath(old),attribute='wit',before=old.get('wit'),after=after,source_value=before.get('wit'),original_byte_start=start)]
    inserted=[]
    for position,(raw,receipt) in enumerate(zip(raw_members,receipts,strict=True),1):
        values=administration(raw,receipt,position)
        bibl=etree.Element(NS+'bibl',nsmap={None:TEI},type='retained-source-document-envelope',n='Tome '+values['tome'])
        note=etree.SubElement(bibl,NS+'note',type='source-document-envelope-administration')
        for name,value in values.items():
            paragraph=etree.SubElement(note,NS+'p',n=name);paragraph.set(XML+'space','preserve')
            paragraph.text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        inserted.append(etree.tostring(bibl,encoding='UTF-8',with_tail=False))
        ledger.append(dict(family='located-source-document-administration',tome=values['tome'],fields=values,carrier_sha256=digest(inserted[-1])))
    if repaired.count(b'</sourceDesc>')!=1:raise ValueError('Unique original sourceDesc insertion boundary required')
    additions=b''.join(inserted);repaired=repaired.replace(b'</sourceDesc>',additions+b'</sourceDesc>',1)
    inverse=repaired.replace(additions,b'',1)
    if inverse[:start]+inverse[start:_tag_end(inverse,start)].replace(new_attr,old_attr,1)+inverse[_tag_end(inverse,start):]!=original:raise ValueError('Entire historical component byte inverse differs')
    return repaired,ledger

def _convert(source:SourceManifest):
    guard(source)
    profile=json.loads(source.authority_path('complete-source-feature-profile').read_bytes());policy=json.loads(source.authority_path('independent-validation-policy').read_bytes())
    if source.record['work_id']!='eusebius-commentarii-in-psalmos' or source.record['manifest_row']!='L811' or profile['complete_authored_works']!=1 or len(profile['members'])!=3:raise ValueError('Exact L811 source scope required')
    retained={}
    for name,row in profile['original_package_members'].items():
        raw=source.authority_path(row['authority']).read_bytes()
        if digest(raw)!=row['sha256'] or len(raw)!=row['bytes']:raise ValueError('Retained historical package member differs '+name)
        retained[name]=raw
    raw=[source.authority_path(row['source_authority']).read_bytes() for row in profile['members']]
    receipts=[json.loads(source.authority_path(row['receipt_authority']).read_bytes()) for row in profile['members']]
    content,ledger=repair(retained['content.tei.xml'],raw,receipts)
    account=dict(contract='ocd-l811-retained-composite-bounded-repair-v1',work_id=source.record['work_id'],edition_id=source.record['edition_id'],source_id=source.record['source_id'],complete_authored_works=1,source_tomes=3,source_manifest_sha256=source.sha256,original_component_sha256=OLD_TEI_SHA,candidate_tei_sha256=digest(content),repairs=ledger,producer=dict(source.record['converter']),source_profile_sha256=digest(source.authority_path('complete-source-feature-profile').read_bytes()),policy_sha256=digest(source.authority_path('independent-validation-policy').read_bytes()))
    result={'content.tei.xml':content,'source-accountability.json':encode(account),'README.source.md':source.authority_path('source-attribution').read_bytes(),'unresolved.jsonl':b''.join(encode(row) for row in policy['unresolved']),'provenance.json':encode(policy['provenance'])}
    guard(source)
    return result

_convert.converter_id='ocd-l811-retained-composite-bounded-repair'
_convert.converter_version='3'
