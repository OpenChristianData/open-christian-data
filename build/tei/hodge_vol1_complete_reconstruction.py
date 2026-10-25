"""Complete retained Hodge volume; preserve the existing sound content subtrees."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from urllib.parse import quote,urlsplit
from lxml import etree

NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
SOURCE_SHA='f01ffb5235657a0b21f56a1a4eb7ef95b836ba9d907f9acd1402e8a6fe450fc6'
HISTORICAL_SHA='f7aacd947d88cbf24da27b8b15acb53cb2025acd54583bf4a0381f11e27ef935'
PROFILE='ocd-prose-hodge-theology1-retained-volume-v1'
CONVERTER_ID='ocd-hodge-vol1-complete-retained-v1'
CONVERTER_VERSION='1'
PREFIX='urn:ocd:hodge-theology1:ThML:'
LANG={'DE':'de','EL':'grc','FR':'fr','HE':'he','LA':'la'}
NEW_TAGS={'div1':'div','div2':'div','div':'div','h1':'head','h2':'head','h3':'head','h4':'head',
          'pb':'pb','p':'p','br':'lb','span':'seg','i':'hi','table':'table','tr':'row','th':'cell','td':'cell',
          'scripRef':'ref','a':'ref','ul':'list','li':'item','insertIndex':'anchor','colgroup':'head','col':'seg'}

def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()

def parse(raw):
    return etree.parse(BytesIO(raw),etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True,huge_tree=True))

def annotation(source):
    payload={'tag':source.tag,'attributes':[[k,v] for k,v in source.attrib.items()]}
    return PREFIX+quote(json.dumps(payload,ensure_ascii=False,separators=(',',':')),safe='')

def build(source_bytes,historical_bytes,historical_accounting):
    if sha256(source_bytes).hexdigest()!=SOURCE_SHA or sha256(historical_bytes).hexdigest()!=HISTORICAL_SHA:
        raise ValueError('Hodge retained source/historical candidate binding differs')
    source_tree=parse(source_bytes);source=source_tree.getroot();body=source.find('ThML.body')
    if [n.get('id') for n in body]!=['i','ii','iii','iv','v']:
        raise ValueError('Hodge complete source root order differs')
    old=parse(historical_bytes).getroot();old_body=old.find(NS+'text/'+NS+'body')
    if len(old_body)!=2:raise ValueError('Historical Hodge subtree count differs')
    history=json.loads(historical_accounting)
    historical_rows=history['crosswalk']
    source_nodes=list(body.iter());numbers={n:i for i,n in enumerate(source_nodes,1)}
    old_mapping={row['source_xml_id']:row['tei_xml_id'] for row in historical_rows if row['source_xml_id']}
    targets={n.get('id'):old_mapping.get(n.get('id'),f'hodge-systematic-theology-vol-1-complete-{numbers[n]:06d}')
             for n in source_nodes if n.get('id')}
    rows=[];links=[]
    def record(src,target,generated_title=False):
        parent=src.getparent();children=[n for n in parent if isinstance(n.tag,str)] if parent is not None else []
        rows.append({'source_number':numbers[src],'source_tag':src.tag,'source_id':src.get('id'),
                     'source_attributes':[[k,v] for k,v in src.attrib.items()],
                     'source_parent_number':numbers.get(parent),'source_child_ordinal':children.index(src)+1 if src in children else 1,
                     'source_text':src.text,'source_tail':src.tail,'target_id':target.get(XML+'id'),
                     'target_tag':etree.QName(target).localname,'target_attributes':dict(target.attrib),
                     'generated_title':generated_title})
    def append_new(src,parent):
        if not isinstance(src.tag,str) or src.tag not in NEW_TAGS:
            raise ValueError('Unsupported new Hodge source element: '+str(src.tag))
        tag=NEW_TAGS[src.tag]
        if src.tag in ('h1','h2','h3','h4') and list(src.getparent())[0] is not src:
            tag='ab'
        target=etree.SubElement(parent,NS+tag)
        target.set(XML+'id',targets.get(src.get('id'),f'hodge-systematic-theology-vol-1-complete-{numbers[src]:06d}'))
        target.set('ana',annotation(src));target.text=src.text;target.tail=src.tail
        if src.tag.startswith('div'):
            target.set('type','source-'+src.tag)
            if src.get('title'):target.set('n',src.get('title'))
        if src.tag in ('h1','h2','h3','h4'):
            target.set('type','source-heading' if tag=='ab' else 'source-'+src.tag)
            if tag=='ab':target.set('subtype',src.tag)
        if src.tag=='colgroup':target.set('type','source-column-layout')
        if src.tag=='col':target.set('type','source-column');target.set('subtype','col')
        if src.tag=='i':target.set('rend','italic')
        elif src.get('class'):target.set('rend',src.get('class'))
        if src.get('lang'):target.set(XML+'lang',LANG[src.get('lang')])
        if src.get('n'):target.set('n',src.get('n'))
        if src.get('style'):target.set('rend',src.get('style'))
        if src.tag=='table' and src.get('border'):target.set('rend','border='+src.get('border'))
        if src.tag=='pb' and src.get('href'):target.set('facs',src.get('href'))
        if src.tag in ('td','th'):
            if src.tag=='th':target.set('role','label')
            for source_attr,target_attr in [('rowspan','rows'),('colspan','cols')]:
                if src.get(source_attr):target.set(target_attr,src.get(source_attr))
        if src.tag=='scripRef':
            target.set('type','scripture')
            if src.get('passage'):target.set('cRef',src.get('passage'))
            if src.get('osisRef'):target.set('target',src.get('osisRef'))
        if src.tag=='a':
            href=src.get('href');fragment=urlsplit(href).fragment
            if fragment not in targets:raise ValueError('Retained Hodge index link target does not resolve')
            target.set('target','#'+targets[fragment]);target.set('type','source-link')
            links.append({'source_number':numbers[src],'literal_href':href,'source_target_id':fragment,'target_id':targets[fragment]})
        if src.tag=='ul':target.set('type','unordered')
        if src.tag=='insertIndex':
            target.set('type','source-insert-index');target.set('subtype',src.get('type'))
            target.set('rend',target.attrib.pop('ana'))
        record(src,target)
        saw_division=False;wrapper=None
        for child in src:
            is_division=child.tag in ('div','div1','div2')
            if src.tag in ('div','div1','div2') and saw_division and not is_division:
                if wrapper is None:wrapper=etree.SubElement(target,NS+'div',type='source-order-wrapper')
                append_new(child,wrapper)
            else:
                wrapper=None;append_new(child,target)
            saw_division=saw_division or is_division
        return target
    result=deepcopy(old);header=result.find(NS+'teiHeader');bibl=header.find(NS+'fileDesc/'+NS+'sourceDesc/'+NS+'bibl')
    for note in list(bibl):
        if note.tag==NS+'note' and note.get('type')=='local-edition-claim':
            note.text=('Historical local configuration claims New York: Scribner, Armstrong, 1872-1873. '
                       'The retained volume title pages explicitly name WM. B. EERDMANS PUBLISHING CO., GRAND RAPIDS, MICH., 1940, '
                       'and a separate 1871 copyright entry by CHARLES SCRIBNER AND COMPANY. These are electronic witness descriptions; '
                       'no physical print collation or identity equivalence is established.')
            note.attrib.pop('source',None)
    for kind,text in [('complete-retained-volume','All five source roots i, ii, iii, iv, v are preserved once in retained order, including title pages, prefatory CARD/contents and seven rendered indexes.'),
                      ('source-description-credit','Tim Perrine is named CCEL Staff Writer for the electronic description, not as editor, translator or transcriber of this volume.'),
                      ('electronic-rights','The retained DC.Rights is empty. CCEL permission evidence permits parsing; technical acceptance is separate from human review, rights clearance and publication.')]:
        note=etree.SubElement(bibl,NS+'note',type=kind);note.text=text
    text=result.find(NS+'text');text.remove(text.find(NS+'body'))
    new_body=etree.SubElement(text,NS+'body',{XML+'id':'hodge-systematic-theology-vol-1-body'});new_body.text=body.text;new_body.tail=body.tail
    for src in body:
        if src.get('id') not in ('iii','iv'):
            append_new(src,new_body);continue
        retained=deepcopy(old_body[0 if src.get('id')=='iii' else 1]);new_body.append(retained)
        represented={n.get(XML+'id'):n for n in retained.iter()}
        source_rows=[row for row in historical_rows if row['source_root_id']==src.get('id')]
        actual=list(src.iter())
        if len(actual)!=len(source_rows):raise ValueError('Historical Hodge crosswalk source count differs')
        for node,row in zip(actual,source_rows):
            if row['source_attributes']!=dict(node.attrib) or row['source_tag']!=node.tag:
                raise ValueError('Historical Hodge crosswalk source attribute/tag differs')
            target=represented[row['tei_xml_id']]
            if target.text!=node.text or target.tail!=node.tail:raise ValueError('Historical Hodge text/tail differs')
            if node.tag in ('td','th'):target.set('ana',annotation(node))
            record(node,target,generated_title=row['source_title_head'] is not None)
    encoded=b'<?xml version="1.0" encoding="UTF-8"?>\n'+etree.tostring(result,encoding='utf-8',pretty_print=False)
    rows.sort(key=lambda row:row['source_number'])
    account={'contract':'hodge-complete-retained-source-accounting-v1','projection_profile':PROFILE,
             'source_sha256':SOURCE_SHA,'historical_candidate_sha256':HISTORICAL_SHA,
             'roots_in_source_order':['i','ii','iii','iv','v'],'rows':rows,'index_link_crosswalk':links,
             'body_carrier':{'attributes':dict(body.attrib),'text':body.text,'tail':body.tail},
             'retained_header_xml':etree.tostring(source.find('ThML.head'),encoding='unicode'),
             'document_prolog':{'doctype':source_tree.docinfo.doctype,
                               'before':[{'kind':'comment','text':node.text,'tail':node.tail} for node in reversed(list(source.itersiblings(preceding=True)))]},
             'source_root':{'tag':source.tag,'attributes':list(map(list,source.attrib.items())),
                            'text':source.text,'tail':source.tail,'encoding':source_tree.docinfo.encoding,
                            'xml_version':source_tree.docinfo.xml_version},
             'scope':'Complete retained volume, all five own-volume roots once. No new edition identity or physical print collation.'}
    return encoded,canonical(account)

def _convert(manifest):
    manifest.verify()
    candidate,account=build(manifest.authority_path('primary-source').read_bytes(),
                          manifest.authority_path('historical-candidate').read_bytes(),
                          manifest.authority_path('historical-accounting').read_bytes())
    return {'content.tei.xml':candidate,'source-accountability.json':account,
            'provenance.json':canonical({'work_id':'hodge-systematic-theology-vol-1','source_sha256':SOURCE_SHA,'scope':'whole retained five-root volume','status':'nonaccepted','publication':'not-authorized'}),
            'README.source.md':manifest.authority_path('source-readme').read_bytes(),
            'unresolved.jsonl':canonical({'id':'rights-human-print-publication','status':'unresolved','evidence':'Physical print collation, human acceptance, rights clearance and public publication remain separate.'})}

_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION
_convert.implementation_path=__import__('pathlib').Path(__file__).resolve()
