"""Conservation-based native rendition of the retained L671 Cox collection."""
from pathlib import Path
from hashlib import sha256
from urllib.parse import quote
import copy,json
from lxml import etree

TEI='http://www.tei-c.org/ns/1.0';NS='{'+TEI+'}';XML='{http://www.w3.org/XML/1998/namespace}'
ANNOTATION='urn:ocd:cox-pg39440:source:'
BLOCK={'header','footer','div','p','h1','h2','h3','blockquote','dl','dt','dd','ul','li','pre'}
BASE_SHA='ba5e05ff0bae1a32c1613407e916fb21c0722c46992f1330a9dfc73c50dce39f'
QUALIFICATION='The preceding mapping description documents the retained historical candidate. This source-conserving successor gives its attested hymn divisions, stanza groups, verse lines, headings, gloss labels/items, quotations and line breaks native TEI carriers. All original source fields remain attached and all original text slots are conserved. No human, print, rights or publication decision is added.'

def canonical(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()

def descriptor(node):
    value=node.get('rend') or ''
    assert value.startswith('source-tag:')
    tag,encoded=value[len('source-tag:'):].split(';source-attributes:',1)
    return tag,json.loads(encoded)

def adapt(original):
    assert sha256(original).hexdigest()==BASE_SHA
    old=etree.fromstring(original);out=copy.deepcopy(old);body=out.find(NS+'text/'+NS+'body');source=old.find(NS+'text/'+NS+'body')
    etree.SubElement(out.find(NS+'teiHeader/'+NS+'encodingDesc'),NS+'p').text=QUALIFICATION
    assert source.attrib=={'n':'L671'} and source.text is None
    body.clear();records=[]
    def emit(n,parent_source_tag=None,parent_class=None):
        tag,attrs=descriptor(n);classes=(attrs.get('class') or '').split()
        if tag in ('header','footer'):target='div'
        elif tag=='div':target='lg' if 'verse' in classes else 'div' if any(descriptor(c)[0] in BLOCK for c in n) else 'ab'
        elif tag=='p':target='l' if parent_source_tag=='div' and parent_class and 'verse' in parent_class else 'p'
        else:target={'h1':'head','h2':'head','h3':'head','blockquote':'quote','dl':'list','dt':'label','dd':'item','ul':'list','li':'item','pre':'ab','span':'seg','a':'ref','strong':'hi','br':'lb'}[tag]
        record={'source_path':n.get('n'),'source_tag':tag,'source_attributes':attrs,'previous_tei_attributes':dict(n.attrib),'previous_tei_tag':etree.QName(n).localname}
        annotation=ANNOTATION+quote(json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':')),safe='')
        result=etree.Element(NS+target);result.set('rend' if target=='label' else 'ana',annotation)
        if n.get(XML+'id'):result.set(XML+'id',n.get(XML+'id'))
        if attrs.get('lang'):result.set(XML+'lang',attrs['lang'])
        if tag=='a' and attrs.get('href') is not None:result.set('target',attrs['href'])
        if target=='div':result.set('type','hymn' if 'hymn' in classes else 'provider-'+tag if tag in ('header','footer') else 'source-html-div')
        elif target=='head':result.set('type',tag)
        elif target=='list':result.set('type','gloss' if tag=='dl' else 'unordered')
        elif target=='hi':result.set('rend','strong')
        elif target=='lg':result.set('type','stanza')
        elif target=='ab':result.set('type','source-pre' if tag=='pre' else 'source-inline-container')
        if tag=='pre':result.set(XML+'space','preserve')
        if attrs.get('class') and target not in ('label','hi'):result.set('rend','source-class:'+attrs['class'])
        result.text=n.text;result.tail=n.tail
        for child in n:result.append(emit(child,tag,classes))
        # HTML block wrappers can carry direct prose between blocks; explicit
        # paragraph carriers retain those exact source text slots.
        if target in ('div','quote','list'):
            if (result.text or '').strip():
                p=etree.Element(NS+'ab',type='source-block',ana='urn:ocd:cox-pg39440:slot:'+quote(n.get('n')+':text',safe=''));p.text=result.text;result.text=None;result.insert(0,p)
            for child in list(result):
                if (child.tail or '').strip():
                    p=etree.Element(NS+'ab',type='source-block',ana='urn:ocd:cox-pg39440:slot:'+quote(n.get('n')+':tail:'+str(list(result).index(child)),safe=''));p.text=child.tail;child.tail=None;result.insert(list(result).index(child)+1,p)
            for index,child in enumerate(list(result)):
                if etree.QName(child).localname in ('lb','seg','ref','hi'):
                    wrapper=etree.Element(NS+'ab',type='source-inline-container',ana='urn:ocd:cox-pg39440:flow:'+quote(n.get('n')+':'+str(index),safe=''));position=list(result).index(child);result.remove(child);wrapper.append(child);result.insert(position,wrapper)
        if target=='div' and len(result):
            for index,child in enumerate(list(result)):
                if child.tag!=NS+'div':
                    wrapper=etree.Element(NS+'div',type='source-flow-unit',ana='urn:ocd:cox-pg39440:division-flow:'+quote(n.get('n')+':'+str(index),safe=''));result.remove(child);wrapper.append(child);result.insert(index,wrapper)
        if target=='quote' and any(c.tag==NS+'div' for c in result):
            floating=etree.Element(NS+'floatingText',type='source-blockquote-flow',n=n.get('n'));quoted=etree.SubElement(floating,NS+'body');quoted.text=result.text;result.text=None
            for child in list(result):result.remove(child);quoted.append(child)
            result.append(floating)
        records.append(record|{'native_tag':target})
        return result
    for wrapper in source:
        assert wrapper.tag==NS+'p' and wrapper.text is None and wrapper.tail is None and len(wrapper)==1
        mapped=emit(wrapper[0]);unit=etree.Element(NS+'div',type='source-html-unit',ana='urn:ocd:cox-pg39440:unit:'+quote(wrapper.get('n'),safe=''));unit.append(mapped)
        if not ''.join(mapped.itertext()).strip():
            assert len(body);body[-1].append(unit)
        else:body.append(unit)
    assert ''.join(body.itertext())==''.join(source.itertext())
    raw=etree.tostring(out,encoding='UTF-8',xml_declaration=True)
    return raw,records

def _convert(manifest):
    original=manifest.authority_path('previous-content').read_bytes();raw,records=adapt(original)
    account=json.loads(manifest.authority_path('previous-accountability').read_bytes())
    account.update(tei_sha256=sha256(raw).hexdigest(),previous_candidate_sha256=BASE_SHA,native_mapping=records,native_mapping_policy='Source hymn divisions, stanza groups, verse lines, headings, gloss labels/items, quotations and twenty line breaks have native TEI carriers. Every original source tag/attribute/path and prior TEI field remains in its exact attached source annotation; complete text/tail slots and original header are conserved. Language is copied only from literal lang fields, never inferred from paired hymn IDs.')
    return {'content.tei.xml':raw,'source-accountability.json':canonical(account),'README.source.md':manifest.authority_path('readme').read_bytes(),'provenance.json':manifest.authority_path('previous-provenance').read_bytes(),'unresolved.jsonl':manifest.authority_path('previous-unresolved').read_bytes()}

_convert.converter_id='ocd-cox-pg39440-conserved-native-rendition'
_convert.converter_version='1'
_convert.implementation_path=Path(__file__).resolve()
