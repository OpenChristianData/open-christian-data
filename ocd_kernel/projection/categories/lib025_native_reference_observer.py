"""Unexecuted independent Expat observer; never imports or calls the projector."""
from pathlib import Path
from xml.parsers import expat
import hashlib,json,re
NS='http://www.tei-c.org/ns/1.0'
XML='http://www.w3.org/XML/1998/namespace}'
SOURCE_SHA='5d9bd4892220a40418c5c04cf9421f6a1e40fc8232da06df2dc5796ad460fa33'
REVIEWED_ACCEPTED_MASTER_SHA='5d9bd4892220a40418c5c04cf9421f6a1e40fc8232da06df2dc5796ad460fa33'
IDENTITY={'work_id':'catholic-encyclopedia-vol01','textual_form_id':'catholic-encyclopedia-vol01-retained-en','edition_id':'catholic-encyclopedia-vol01-retained-electronic'}
NATIVE={'div':'division','ab':'source-block','milestone':'source-marker','head':'heading','hi':'emphasis','ref':'source-reference','list':'list','item':'list-item','table':'table','row':'table-row','cell':'table-cell','seg':'segment','lb':'line-break','quote':'quotation-block','figure':'figure','graphic':'image-reference','figDesc':'figure-description','spanGrp':'source-block','span':'source-marker','anchor':'anchor','gap':'gap','desc':'description','g':'glyph','p':'paragraph'}
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def alias(identifier):return 'PgCE'+identifier.encode('utf-8').hex()
def local(tag):
    if not tag.startswith(NS+'}'):raise ValueError('Observer encountered a non-TEI element')
    return tag[len(NS)+1:]
def forbid(*args):raise ValueError('Observer rejects DTD/entity declarations')
def parse(path,start,end,chars=None):
    parser=expat.ParserCreate(namespace_separator='}')
    parser.StartElementHandler=start;parser.EndElementHandler=end;parser.CharacterDataHandler=chars
    parser.StartDoctypeDeclHandler=forbid;parser.EntityDeclHandler=forbid;parser.ExternalEntityRefHandler=forbid
    sha=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):sha.update(block);parser.Parse(block,False)
        parser.Parse(b'',True)
    return sha.hexdigest()
def _fields(attributes,ids):
    fields={};unbound=[]
    for k,v in attributes.items():
        if k==XML+'id':continue
        expanded='{'+k if '}' in k else k
        if k in ('target','from','to'):
            values=[]
            for literal in v.split():
                if literal.startswith('#'):
                    if literal[1:] in ids:literal='#'+alias(literal[1:])
                    else:unbound.append({'attribute':k,'literal':literal})
                values.append(literal)
            v=' '.join(values)
        fields[expanded]=v
    return fields,unbound
def _render(node,ids):
    tag=node['tag'];source=node['attributes'];fields,unbound=_fields(source,ids)
    role='block-spanning-emphasis-group' if tag=='spanGrp' else 'block-spanning-emphasis-range' if tag=='span' else 'source-'+tag
    attrs={'source_role':role,'source_annotations':canonical({'source_element':tag,'fields':fields,'unbound_source_literals':unbound})}
    if source.get(XML+'id'):attrs['source_anchor']=alias(source[XML+'id'])
    for a,b in [('style','css_style'),('rend','style'),('type','type'),('subtype','subtype'),('reason','reason'),('unit','unit'),('role','source_role'),('cols','source_column_count'),('rows','source_row_count'),(XML+'lang','language')]:
        if a in source:attrs[b]=source[a]
    if 'target' in fields:attrs['source_target']=fields['target']
    if 'url' in source:attrs['source_target']=source['url']
    if 'ref' in source:attrs['reference']=source['ref']
    content=[]
    for item in node['ordered_content']:
        if isinstance(item,str):
            if item:content.append({'kind':'text','text':item})
        else:content.append(_render(item,ids))
    if tag not in NATIVE:raise ValueError('Observer native carrier is outside closed grammar')
    return {'kind':NATIVE[tag],'attributes':attrs,'content':content}
def _plaintext(node):
    pieces=[]
    def walk(n):
        t=n['tag']
        if t in ('head','p','ab','item','row','quote','figDesc','desc'):pieces.append('\n')
        elif t=='cell':pieces.append('\t')
        for part in n['ordered_content']:
            if isinstance(part,str):pieces.append(part)
            else:walk(part)
        if t in ('head','p','ab','item','row','quote','figDesc','desc','lb'):pieces.append('\n')
    walk(node)
    return '\n'.join(' '.join(line.split()) for line in ''.join(pieces).split('\n') if line.strip())
def _event_hash(node):
    digest=hashlib.sha256()
    def walk(n,path,tail):
        parts=n['ordered_content'];text=parts[0] if parts and isinstance(parts[0],str) else None
        attrs=[(('{' + key) if '}' in key else key,value) for key,value in n['attributes'].items()]
        record={'path':path,'tag':'{'+NS+'}'+n['tag'],'attributes':attrs,'text':text,'tail':tail}
        digest.update((canonical(record)+'\n').encode())
        ordinal=0
        for index,part in enumerate(parts):
            if isinstance(part,str):continue
            child_tail=parts[index+1] if index+1<len(parts) and isinstance(parts[index+1],str) else None
            walk(part,path+[ordinal],child_tail);ordinal+=1
    # Frozen producer serialization has no inter-unit text or tails; a changed
    # envelope is rejected by exact whole-master pins and the header/body bridge.
    walk(node,[],None);return digest.hexdigest()
def verify_proposed_units(path,actual_records,*,identity,accepted=False):
    expected=REVIEWED_ACCEPTED_MASTER_SHA if accepted else SOURCE_SHA
    if expected is None or identity!=IDENTITY:raise ValueError('Observer exact admitted identity/master unavailable')
    ids=set();local_targets=set()
    def census(tag,attrs):
        local(tag)
        if XML+'id' in attrs:
            if attrs[XML+'id'] in ids:raise ValueError('Observer duplicate ID')
            ids.add(attrs[XML+'id'])
        for k in ('target','from','to'):
            local_targets.update(v[1:] for v in attrs.get(k,'').split() if v.startswith('#'))
    if parse(path,census,lambda name:None)!=expected:raise ValueError('Observer source pin differs')
    stack=[];unit_stack=[];count=0;cursor=iter(actual_records)
    def begin(name,attrs):
        tag=local(name);parent=stack[-1] if stack else None;stack.append(tag)
        if tag=='div' and parent=='body':unit_stack.append({'tag':tag,'attributes':dict(attrs),'ordered_content':[],'children':[]})
        elif unit_stack:
            child={'tag':tag,'attributes':dict(attrs),'ordered_content':[],'children':[]};unit_stack[-1]['ordered_content'].append(child);unit_stack[-1]['children'].append(child);unit_stack.append(child)
    def characters(text):
        if unit_stack:
            parts=unit_stack[-1]['ordered_content']
            if parts and isinstance(parts[-1],str):parts[-1]+=text
            else:parts.append(text)
    def finish(name):
        nonlocal count
        if unit_stack:
            node=unit_stack.pop()
            if not unit_stack:
                count+=1;attrs=node['attributes'];source_type=attrs.get('type');url=attrs.get('corresp')
                headings=[]
                def collect(n):
                    if n['tag']=='head' and n['attributes'].get('type')=='h1':headings.append(n)
                    for c in n['children']:collect(c)
                if source_type=='source-page':collect(node)
                elif source_type=='unavailable-source-members':headings=[c for c in node['children'] if c['tag']=='head']
                else:raise ValueError('Observer found unaccounted body unit')
                if len(headings)!=1:raise ValueError('Observer unit heading count differs')
                def literal(n):return ''.join(c if isinstance(c,str) else literal(c) for c in n['ordered_content'])
                title=literal(headings[0]);article=bool(url and re.fullmatch(r'https://www\.newadvent\.org/cathen/[0-9]{5}[a-z]\.htm',url))
                kind='encyclopedia-entry' if article else 'encyclopedia-index' if source_type=='source-page' else 'unavailable-source-register'
                expected_row={'row_format':'ocd-native-reference-unit-v1',**IDENTITY,'sequence':count,'category':'reference_entries','language':'en','unit_kind':kind,'source_title':title,'headword':title if article else None,'text':_plaintext(node),'structure':[_render(node,ids)]}
                try:actual=next(cursor)
                except StopIteration:raise ValueError('Observer output ended before complete retained unit set')
                if canonical(actual['public_unit'])!=canonical(expected_row):raise ValueError('Independent full public unit mismatch at '+str(count))
                private=actual['private_receipt']
                if private['source_url']!=url or private['source_id']!=attrs.get(XML+'id') or private['global_unbound_target_count']!=len(local_targets-ids):raise ValueError('Observer private unit identity/closure differs')
                if private['unit_event_sha256']!=_event_hash(node):raise ValueError('Independent complete private unit event digest differs')
        stack.pop()
    if parse(path,begin,finish,characters)!=expected:raise ValueError('Observer master changed during complete verification')
    if count!=11681:raise ValueError('Observer whole retained source unit denominator differs')
    try:next(cursor)
    except StopIteration:return {'status':'pass-full-source-derived-native-unit-observation','rows':count,'source_pages':11680,'scope':'Whole retained body units; no candidate source oracle/schema/acceptance claim'}
    raise ValueError('Observer unexpected output rows beyond retained source envelope')
