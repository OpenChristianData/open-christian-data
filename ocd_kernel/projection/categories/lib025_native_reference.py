"""Unexecuted work-specific streaming leaf; no registered accepted entry point."""
from pathlib import Path
import hashlib,json,re
from lxml import etree

NS='http://www.tei-c.org/ns/1.0'
XML='{http://www.w3.org/XML/1998/namespace}'
SOURCE_SHA='5d9bd4892220a40418c5c04cf9421f6a1e40fc8232da06df2dc5796ad460fa33'
IDENTITY={'work_id':'catholic-encyclopedia-vol01','textual_form_id':'catholic-encyclopedia-vol01-retained-en','edition_id':'catholic-encyclopedia-vol01-retained-electronic'}
POLICY_PATH=Path(__file__).with_name('native_reference_policy_v1.json')
POLICY_SHA='999ae9c02989c957b08e4b73f9764d57d39cb7389cae5ebd107cda30a9f475c4'
REVIEWED_ACCEPTED_MASTER_SHA='5d9bd4892220a40418c5c04cf9421f6a1e40fc8232da06df2dc5796ad460fa33'
REVISION='lib025-newadvent-retained-complete-20261004-v1'
def encoded(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def alias(value):return 'PgCE'+value.encode('utf-8').hex()
def local(tag):
    if not isinstance(tag,str) or not tag.startswith('{'+NS+'}'):raise ValueError('Non-TEI native carrier')
    return tag[len(NS)+2:]
def hash_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()
def policy():
    raw=POLICY_PATH.read_bytes()
    if POLICY_SHA.startswith('PENDING_') or hashlib.sha256(raw).hexdigest()!=POLICY_SHA:
        raise ValueError('Native reference leaf lacks a root-reviewed policy pin')
    return json.loads(raw)
def _scan_ids(path):
    ids=set();targets=set()
    for event,node in etree.iterparse(str(path),events=('end',),resolve_entities=False,no_network=True,load_dtd=False,remove_blank_text=False,huge_tree=True):
        if node.getroottree().docinfo.doctype:raise ValueError('DTD is forbidden')
        local(node.tag)
        if node.get(XML+'id'):
            value=node.get(XML+'id')
            if value in ids:raise ValueError('Duplicate TEI ID')
            ids.add(value)
        for key in ('target','from','to'):
            for value in (node.get(key) or '').split():
                if value.startswith('#'):targets.add(value[1:])
        node.clear(keep_tail=True)
        while node.getprevious() is not None:del node.getparent()[0]
    return ids,targets-ids
def _native(node,ids,kinds):
    tag=local(node.tag)
    if tag not in kinds:raise ValueError('Unexpected body native carrier: '+tag)
    fields={};unbound=[]
    for key,value in node.attrib.items():
        if key==XML+'id':continue
        if key in ('target','from','to'):
            tokens=[]
            for token in value.split():
                if token.startswith('#') and token[1:] in ids:token='#'+alias(token[1:])
                elif token.startswith('#'):unbound.append({'attribute':key,'literal':token})
                tokens.append(token)
            value=' '.join(tokens)
        fields[key]=value
    attrs={'source_role':{'spanGrp':'block-spanning-emphasis-group','span':'block-spanning-emphasis-range'}.get(tag,'source-'+tag),'source_annotations':encoded({'source_element':tag,'fields':fields,'unbound_source_literals':unbound})}
    if node.get(XML+'id'):attrs['source_anchor']=alias(node.get(XML+'id'))
    for source,target in [('style','css_style'),('rend','style'),('type','type'),('subtype','subtype'),('reason','reason'),('unit','unit'),('role','source_role'),('cols','source_column_count'),('rows','source_row_count'),(XML+'lang','language')]:
        if source in node.attrib:attrs[target]=node.get(source)
    if 'target' in fields:attrs['source_target']=fields['target']
    if node.get('url'):attrs['source_target']=node.get('url')
    if node.get('ref'):attrs['reference']=node.get('ref')
    content=[]
    if node.text:content.append({'kind':'text','text':node.text})
    for child in node:
        content.append(_native(child,ids,kinds))
        if child.tail:content.append({'kind':'text','text':child.tail})
    return {'kind':kinds[tag],'attributes':attrs,'content':content}
def _ledger_hash(node):
    sha=hashlib.sha256()
    def walk(element,path):
        sha.update((encoded({'path':path,'tag':element.tag,'attributes':list(element.attrib.items()),'text':element.text,'tail':element.tail})+'\n').encode())
        for i,child in enumerate(element):walk(child,path+[i])
    walk(node,[]);return sha.hexdigest()
def _plain(node):
    text=[]
    def visit(n):
        tag=local(n.tag)
        if tag in ('head','p','ab','item','row','quote','figDesc','desc'):text.append('\n')
        elif tag=='cell':text.append('\t')
        if n.text:text.append(n.text)
        for child in n:
            visit(child)
            if child.tail:text.append(child.tail)
        if tag in ('head','p','ab','item','row','quote','figDesc','desc','lb'):text.append('\n')
    visit(node)
    return '\n'.join(' '.join(line.split()) for line in ''.join(text).split('\n') if line.strip())
def iter_proposed_units(path,*,identity,accepted=False):
    rules=policy()
    expected=REVIEWED_ACCEPTED_MASTER_SHA if accepted else SOURCE_SHA
    if expected is None or identity!=IDENTITY or hash_file(path)!=expected:raise ValueError('Exact reviewed master/identity required')
    ids,unbound=_scan_ids(path);count=0
    # Every complete direct body division is freed only after its row is emitted.
    for event,node in etree.iterparse(str(path),events=('end',),resolve_entities=False,no_network=True,load_dtd=False,remove_blank_text=False,huge_tree=True):
        parent=node.getparent()
        if node.tag!='{'+NS+'}div' or parent is None or parent.tag!='{'+NS+'}body':continue
        count+=1;source_type=node.get('type');url=node.get('corresp')
        heads=[n for n in node.iter('{'+NS+'}head') if n.get('type')=='h1'] if source_type=='source-page' else list(node.findall('{'+NS+'}head'))
        if len(heads)!=1:raise ValueError('Source unit has no unique actual heading')
        title=''.join(heads[0].itertext())
        article=bool(url and re.fullmatch(r'https://www\.newadvent\.org/cathen/\d{5}[a-z]\.htm',url))
        kind='encyclopedia-entry' if article else 'encyclopedia-index' if source_type=='source-page' else 'unavailable-source-register'
        if source_type not in ('source-page','unavailable-source-members'):raise ValueError('Unknown direct body unit')
        public_unit={'row_format':'ocd-native-reference-unit-v1',**IDENTITY,'sequence':count,'category':'reference_entries','language':'en','unit_kind':kind,'source_title':title,'headword':title if article else None,'text':_plain(node),'structure':[_native(node,ids,rules['public_native_kind_map'])]}
        yield {'public_unit':public_unit,'private_receipt':{'unit_event_sha256':_ledger_hash(node),'source_url':url,'source_id':node.get(XML+'id'),'global_unbound_target_count':len(unbound)}}
        node.clear(keep_tail=True)
        while node.getprevious() is not None:del parent[0]
    if count!=rules['expected_rows']:raise ValueError('Complete source-defined unit denominator differs')
    if hash_file(path)!=expected:raise ValueError('Master changed during streaming projection')
