"""Independent stdlib observer for the bounded L811 scratch native proposal.

No leaf projector, installer, producer, source oracle, or shared reader is
imported. This reconstructs expected fields/contexts/anchors independently
from the actual frozen TEI; it is not a registered maintained checker yet.
"""
from collections import Counter
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
import re
import sys
import xml.etree.ElementTree as ET

T = '{http://www.tei-c.org/ns/1.0}'
X = '{http://www.w3.org/XML/1998/namespace}'
SOURCE_SHA = '29d0845997301ec67aef8625d5014b402ffe552590296db2ca65742944db0697'
HEADER_PROPOSAL_SHA = 'b67b84fe42425800cabcd99f923e26d866b34f4123e37d65dca8e0922577acae'
PROFILE = 'ocd-prose-eusebius-l811-pta-three-tome-critical-v1'
REFERENCE_FIELDS = {'corresp','decls','edRef','target','targetEnd','wit','resp',
                    'copyOf','next','prev','source','ref','cRef','rendition','n'}
DISPLAY_FIELDS = {'type','subtype','n','rend','place','reason','quantity','unit','break','anchored','varSeq'}
ELEMENT_POLICY = {
    'body':('body','source-body'),'div':('division','source-div'),
    'p':('paragraph','source-p'),'head':('heading','source-head'),
    'quote':('quotation-block','source-quote'),'l':('verse-line','source-l'),
    'list':('list','source-list'),'item':('list-item','source-item'),
    'note':('note','source-note'),'hi':('emphasis','source-hi'),
    'emph':('emphasis','source-emph'),'foreign':('foreign-text','source-foreign'),
    'gap':('gap','source-gap'),'pb':('page-break','source-pb'),
    'ref':('source-reference','literal-source-reference'),'anchor':('anchor','source-anchor'),
    'bibl':('bibliographic-label','source-bibl'),'title':('work-title','source-title'),
    'persName':('person-name','source-persName'),'placeName':('segment','source-placeName'),
    'orgName':('segment','source-orgName'),'num':('segment','source-num'),
    'seg':('segment','source-seg'),'mentioned':('segment','mentioned-source-text'),
    'supplied':('segment','supplied-text'),'unclear':('uncertain-text','source-unclear'),
    'add':('segment','source-addition'),'del':('segment','source-deletion'),
    'surplus':('segment','surplus-text'),'milestone':('source-marker','source-milestone'),
    'app':('source-block','critical-apparatus'),'rdgGrp':('source-block','variant-reading-group'),
    'lem':('segment','lemma'),'rdg':('segment','variant-reading'),
    'witDetail':('note','witness-detail'),'witStart':('source-marker','witness-start'),
    'witEnd':('source-marker','witness-end'),'lacunaStart':('source-marker','lacuna-start'),
    'lacunaEnd':('source-marker','lacuna-end'),
}


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def parse(raw):
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True))
    namespace_fields, pending, stack = {}, [], []
    events = ET.iterparse(BytesIO(raw), events=('start','end','start-ns','comment','pi'), parser=parser)
    for event,value in events:
        if event == 'start-ns':
            pending.append((value[0] or None,value[1]))
        elif event == 'start':
            inherited = stack[-1] if stack else []
            local_keys = {key for key,_ in pending}
            current = pending + [(key,url) for key,url in inherited if key not in local_keys]
            pending=[];stack.append(current);namespace_fields[id(value)]=current
        elif event == 'end':
            stack.pop()
        else:
            # Comments/PIs are not namespace-bearing element objects. The
            # producer's actual lxml objects expose an empty nsmap here.
            namespace_fields[id(value)] = []
    return events.root,namespace_fields


def observe(raw):
    digest = sha256(raw).hexdigest()
    if digest not in {SOURCE_SHA,HEADER_PROPOSAL_SHA}:
        raise ValueError('Independent L811 observer requires frozen source/header proposal bytes')
    root,namespaces = parse(raw)
    if root.tag != T+'TEI' or [n.tag for n in root] != [T+'teiHeader',T+'text']:
        raise ValueError('Independent L811 exact outer envelope differs')
    body=root.find(T+'text/'+T+'body')
    if body is None or [(n.tag,n.get('type'),n.get('n')) for n in body] != [
            (T+'div','volume','Tome I'),(T+'div','volume','Tome II'),(T+'div','volume','Tome III')]:
        raise ValueError('Independent L811 ordered volume envelope differs')
    nodes=list(root.iter());parents={id(c):n for n in nodes for c in n}
    ids={}
    for n in nodes:
        value=n.get(X+'id')
        if value:
            if value in ids:raise ValueError('Independent L811 duplicate actual source ID')
            ids[value]=n
    body_nodes={id(n) for n in body.iter()}
    body_ids={key for key,n in ids.items() if id(n) in body_nodes}
    if len(ids)!=(1278 if digest==HEADER_PROPOSAL_SHA else 1277) or len(body_ids)!=1135:
        raise ValueError('Independent L811 full source/body ID denominator differs')
    unbound=[]
    def scan(sequence,location,collect):
        resolved=set()
        for n in sequence:
            for key,value in n.attrib.items():
                if key not in REFERENCE_FIELDS:continue
                for token in value.split():
                    if not token.startswith('#'):continue
                    if token[1:] in ids:resolved.add(token[1:])
                    elif collect:unbound.append(dict(location=location,tag=str(n.tag),attribute=key,literal=token,
                                                    disposition='unbound-source-literal-not-a-public-anchor'))
        return resolved
    targets=scan(body.iter(),'body',True)-body_ids
    first_targets=set(targets)
    if len(targets)!=58:raise ValueError('Independent L811 referenced-header target denominator differs')
    def selected_roots():
        selected=[]
        for key,n in ids.items():
            if key not in targets:continue
            parent=parents.get(id(n));nested=False
            while parent is not None:
                if parent.get(X+'id') in targets:nested=True;break
                parent=parents.get(id(parent))
            if not nested:selected.append(n)
        return selected
    while True:
        selected=selected_roots();context_ids={id(n) for s in selected for n in s.iter()}
        context=[n for n in nodes if id(n) in context_ids]
        found=scan(context,'header-context',False)-body_ids
        if found<=targets:break
        targets.update(found)
    scan(context,'header-context',True)
    header_ids={key for key,n in ids.items() if id(n) in context_ids}
    public_map={key:'PgL811'+key.encode('utf-8').hex() for key in ids if key in body_ids|header_ids}
    if len(set(public_map.values()))!=len(public_map):raise ValueError('Independent L811 public ID mapping collision')

    def public(n,in_header=False):
        if n.tag in {ET.Comment,ET.ProcessingInstruction}:
            return dict(kind='source-marker',attributes=dict(source_role='source-administration-node'),content=[])
        if not isinstance(n.tag,str) or not n.tag.startswith(T):raise ValueError('Independent L811 foreign carrier')
        name=n.tag[len(T):]
        if name not in ELEMENT_POLICY and not in_header:raise ValueError('Independent L811 unsupported body carrier '+name)
        kind,role=ELEMENT_POLICY.get(name,('source-block','source-'+name))
        if in_header:role='retained-header-'+name
        fields={key:value for key,value in n.attrib.items() if key in DISPLAY_FIELDS};qualified=[]
        for key,value in n.attrib.items():
            if key not in REFERENCE_FIELDS:continue
            def alias(match):
                token=match.group(0)
                if token.startswith('#') and token[1:] in public_map:return '#'+public_map[token[1:]]
                if token.startswith('#'):qualified.append(dict(attribute=key,literal=token,
                                                               disposition='unbound-source-literal-not-a-public-anchor'))
                return token
            fields[key]=re.sub(r'\S+',alias,value)
        attrs=dict(source_role=role,source_annotations=canonical(dict(source_element=name,fields=fields,
                                                                     qualified_reference_literals=qualified)))
        identifier=n.get(X+'id')
        if identifier:attrs['source_anchor']=public_map[identifier]
        for key,destination in [(X+'lang','language'),('n','number'),('type','type'),('subtype','subtype'),
                                 ('place','place'),('rend','style'),('rendition','rendition'),('anchored','anchored')]:
            if key in n.attrib:attrs[destination]=fields[key] if key in REFERENCE_FIELDS else n.attrib[key]
        if 'target' in n.attrib:attrs['source_target']=fields['target']
        if 'cRef' in n.attrib:attrs['reference']=fields['cRef']
        elif 'ref' in n.attrib:attrs['reference']=fields['ref']
        mixed=[]
        if n.text:mixed.append(dict(kind='text',text=n.text))
        for child in n:
            mixed.append(public(child,in_header))
            if child.tail:mixed.append(dict(kind='text',text=child.tail))
        return dict(kind=kind,attributes=attrs,content=mixed)

    ledger=[]
    def inventory(n,path,parent,ordinal):
        text=n.text
        if n.tag is ET.Comment:tag,kind='#comment','comment'
        elif n.tag is ET.ProcessingInstruction:
            tag,separator,text=(n.text or '').partition(' ');kind='processing-instruction'
            if not separator:text=''
        else:tag,kind=n.tag,'element'
        ledger.append(dict(path=path,parent=parent,position=ordinal,node_kind=kind,expanded_tag=tag,
                           attributes=list(n.attrib.items()),namespace_bindings=list(namespaces[id(n)]),text=text,tail=n.tail))
        for position,child in enumerate(n):inventory(child,path+[position],path,position)
    inventory(root,[],None,0)
    return dict(contract='ocd-l811-native-leaf-proposal-v1',profile=PROFILE,complete_authored_works=1,
                proposed_prose_rows=1,native_body=public(body),
                native_header_reference_context=dict(kind='source-block',attributes=dict(source_role='retained-header-reference-context'),
                                                     content=[public(n,True) for n in selected]),
                ordered_tome_labels=[n.get('n') for n in body],public_anchor_map=public_map,
                reference_census=dict(actual_ids=len(ids),body_ids=len(body_ids),initial_body_header_targets=len(first_targets),
                                      closed_header_targets=len(targets),displayed_header_ids=len(header_ids)),
                unresolved_literal_qualification=unbound,private_actual_object_ledger=ledger,
                private_ledger_sha256=sha256(canonical(ledger).encode('utf-8')).hexdigest(),
                source_feature_census=dict(Counter(n.tag[len(T):] for n in body.iter() if isinstance(n.tag,str))),
                scripture_normalizations=[],
                display_requirement='Render nested lemma, variant-reading and witness roles distinctly; never concatenate apparatus readings as a preferred commentary reading.',
                qualifications='Exact retained electronic three-tome edition; source I/II work in progress, source III approved; Greek Psalm labels remain literal.')


def verify(raw,projected):
    expected=observe(raw)
    if set(projected)!=set(expected):raise ValueError('Independent L811 native envelope fields differ')
    for key,value in expected.items():
        if canonical(projected[key])!=canonical(value):raise ValueError('Independent L811 actual projected field differs: '+key)
    projector_path=(Path(__file__).resolve().parent/'eusebius_l811_native_leaf_proposal.py').resolve()
    imported_paths={Path(name).resolve(strict=False) for module in sys.modules.copy().values()
                    if (name:=getattr(module,'__file__',None))}
    return dict(status='pass',independent_engine='stdlib-ET-with-namespace-events',
                producer_imported=projector_path in imported_paths,
                producer_called=False,
                actual_object_rows=len(expected['private_actual_object_ledger']),
                private_actual_object_sha256=expected['private_ledger_sha256'],
                reference_census=expected['reference_census'],
                checked_all_public_and_private_fields=True,scripture_normalizations=[])
