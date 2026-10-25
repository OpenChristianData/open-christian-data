"""Reuse the reviewed complete PG42957 body with reversible native type aliases."""
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree

NS='{http://www.tei-c.org/ns/1.0}'
HISTORICAL_SHA='b82c494679c3d3f4e6628060e107b51f0fe72fee2105cc5da6b2b5fef798d0c3'
CONVERTER_ID='ocd-modern-scepticism-current-native-reuse-v1'

def canonical(value):return (json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
def parse(raw):return etree.fromstring(raw,etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True))

def build(raw):
    if sha256(raw).hexdigest()!=HISTORICAL_SHA:raise ValueError('Exact latest complete historical candidate differs')
    root=parse(raw);text=root.find(NS+'text');counts={'rules':0,'headings':0,'thought_breaks':0,'row_renditions':0}
    for node in text.iter():
        if node.tag==NS+'milestone' and node.get('unit')=='rule':
            if dict(node.attrib)!={'unit':'rule'} or len(node) or node.text is not None:raise ValueError('Historical source rule shape differs')
            node.set('unit','horizontal-rule');counts['rules']+=1
        elif node.tag==NS+'ab' and node.get('type') in ('h1','h2','h3'):
            if dict(node.attrib)!={'type':node.get('type')}:raise ValueError('Historical source heading attributes differ')
            node.set('type','source-'+node.get('type'));counts['headings']+=1
        elif node.tag==NS+'ab' and node.get('type')=='thought_break':
            if set(node.attrib)!={'type','rend'}:raise ValueError('Historical thought break attributes differ')
            node.set('type','source-block');node.set('subtype','thought_break');counts['thought_breaks']+=1
        elif node.tag==NS+'row' and node.get('rend') is not None:
            if dict(node.attrib)!={'rend':'smaller'}:raise ValueError('Historical single source row rendition differs')
            node.attrib.pop('rend');node.set('ana','urn:ocd:pg42957:legacy-row-rend:smaller');counts['row_renditions']+=1
    if counts!={'rules':33,'headings':21,'thought_breaks':4,'row_renditions':1}:raise ValueError('Historical closed alias census differs')
    return etree.tostring(root,encoding='UTF-8',xml_declaration=True),counts

def _convert(manifest):
    raw,counts=build(manifest.authority_path('historical-candidate').read_bytes())
    profile=json.loads(manifest.authority_path('profile').read_bytes())
    if counts!=profile['alias_counts']:raise ValueError('Pinned alias profile differs')
    root=parse(raw)
    root.replace(root.find(NS+'teiHeader'),parse(profile['header_xml'].encode()))
    raw=etree.tostring(root,encoding='UTF-8',xml_declaration=True)
    account=json.loads(manifest.authority_path('historical-accounting').read_bytes())
    account['current_native_aliases']={'historical_candidate_sha256':HISTORICAL_SHA,'counts':counts,'inverse':'Restore only the aliases on 59 declared carriers; text tree becomes exact historical text tree.'}
    provenance={'work_id':manifest.record['work_id'],'edition_id':manifest.record['edition_id'],'acquisition_id':manifest.record['acquisition_id'],'source_sha256':profile['source_sha256'],'status':'nonaccepted','publication':'not-authorized','historical_body_reused':True}
    return {'content.tei.xml':raw,'source-accountability.json':canonical(account),'provenance.json':canonical(provenance),'README.source.md':manifest.authority_path('source-readme').read_bytes(),'unresolved.jsonl':manifest.authority_path('historical-unresolved').read_bytes()}

_convert.converter_id=CONVERTER_ID
_convert.converter_version='1'
_convert.implementation_path=Path(__file__).resolve()
