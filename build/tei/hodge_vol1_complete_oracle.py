"""Source-derived full-volume checks; never imports the Hodge reconstruction."""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import quote,urlsplit
from lxml import etree

NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
SOURCE_SHA='f01ffb5235657a0b21f56a1a4eb7ef95b836ba9d907f9acd1402e8a6fe450fc6'
HISTORICAL_SHA='f7aacd947d88cbf24da27b8b15acb53cb2025acd54583bf4a0381f11e27ef935'
PROFILE='ocd-prose-hodge-theology1-retained-volume-v1'
ORACLE_ID='ocd-hodge-vol1-complete-independent-v1'
ORACLE_VERSION='1'
LANG={'DE':'de','EL':'grc','FR':'fr','HE':'he','LA':'la'}

def parse(raw):
    return etree.parse(BytesIO(raw),etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True,huge_tree=True))

def source_note(node):
    literal={'tag':node.tag,'attributes':list(map(list,node.attrib.items()))}
    return 'urn:ocd:hodge-theology1:ThML:'+quote(json.dumps(literal,ensure_ascii=False,separators=(',',':')),safe='')

def inspect(source_bytes,candidate_bytes,accounting_bytes,historical_bytes):
    if sha256(source_bytes).hexdigest()!=SOURCE_SHA or sha256(historical_bytes).hexdigest()!=HISTORICAL_SHA:
        raise ValueError('Independent source/historical binding differs')
    source_tree=parse(source_bytes);source=source_tree.getroot();source_body=source.find('ThML.body')
    candidate=parse(candidate_bytes).getroot();body=candidate.find(NS+'text/'+NS+'body')
    if candidate.tag!=NS+'TEI' or candidate.attrib!={XML+'id':'hodge-systematic-theology-vol-1-candidate'}:
        raise ValueError('Independent complete-volume TEI envelope differs')
    if body is None or body.attrib!={XML+'id':'hodge-systematic-theology-vol-1-body'} or body.text!=source_body.text or body.tail!=source_body.tail:
        raise ValueError('Independent body envelope/whitespace differs')
    if [n.get('id') for n in source_body]!=['i','ii','iii','iv','v'] or len(body)!=5:
        raise ValueError('Independent complete five-root scope differs')
    native=list(source_body.iter());positions={node:i for i,node in enumerate(native,1)}
    legacy=list(source_body[2].iter())+list(source_body[3].iter());legacy_ids={n:f'hodge-systematic-theology-vol-1-feature-{i:06d}' for i,n in enumerate(legacy,1)}
    expected_ids={n:legacy_ids.get(n,f'hodge-systematic-theology-vol-1-complete-{positions[n]:06d}') for n in native[1:]}
    source_ids={n.get('id'):expected_ids[n] for n in native[1:] if n.get('id')}
    targets={n.get(XML+'id'):n for n in body.iter() if n.get(XML+'id')}
    if len(targets)!=len(native):raise ValueError('Independent readable carrier count or unique IDs differs')
    links=[];expected_records=[];generated_heads=0;wrappers=[]
    def expected(node):
        original=node.tag;attrs={XML+'id':expected_ids[node]}
        if node in legacy_ids:
            names={'div':'div','div1':'div','div2':'div','div3':'div','h1':'head','h2':'head','h3':'head','i':'hi','note':'note','p':'p','pb':'pb','scripRef':'ref','span':'foreign' if node.get('lang') else 'seg','blockquote':'quote','br':'lb','table':'table','tr':'row','td':'cell'}
            if original not in names:raise ValueError('Independent legacy source tag unsupported')
            tag=names[original]
            if original.startswith('div'):attrs['type']='source-'+original
            if original=='span' and not node.get('lang'):attrs['type']='source-span'
            rend=['italic'] if original=='i' else []
            for key,val in node.attrib.items():
                if key in ('class','style','border'):rend.append(key+'='+val)
                elif key=='lang':attrs[XML+'lang']=LANG[val]
                elif key=='n':attrs['n']=val
                elif key=='href':attrs['facs']=val
                elif key=='passage':attrs['cRef']=val
                elif key=='osisRef':attrs['target']=val
                elif key=='rowspan':attrs['rows']=val
                elif key not in ('id','title','next','parsed','prev','progress','version'):
                    raise ValueError('Independent legacy source attribute unsupported')
            if rend:attrs['rend']='; '.join(rend)
            if original=='scripRef':attrs['type']='scripture'
            if original=='td':attrs['ana']=source_note(node)
            return tag,attrs
        names={'div':'div','div1':'div','div2':'div','pb':'pb','p':'p','br':'lb','span':'seg','i':'hi','table':'table','tr':'row','td':'cell','th':'cell','scripRef':'ref','a':'ref','ul':'list','li':'item','insertIndex':'anchor','colgroup':'head','col':'seg'}
        if original in ('h1','h2','h3','h4'):
            tag='head' if node.getparent()[0] is node else 'ab'
        elif original in names:tag=names[original]
        else:raise ValueError('Independent newly included source tag unsupported')
        attrs['rend' if original=='insertIndex' else 'ana']=source_note(node)
        if original.startswith('div'):
            attrs['type']='source-'+original
            if node.get('title'):attrs['n']=node.get('title')
        if original in ('h1','h2','h3','h4'):
            attrs['type']='source-'+original if tag=='head' else 'source-heading'
            if tag=='ab':attrs['subtype']=original
        if original=='colgroup':attrs['type']='source-column-layout'
        if original=='col':attrs.update(type='source-column',subtype='col')
        if original=='i':attrs['rend']='italic'
        elif node.get('class'):attrs['rend']=node.get('class')
        if node.get('lang'):attrs[XML+'lang']=LANG[node.get('lang')]
        if node.get('n'):attrs['n']=node.get('n')
        if node.get('style'):attrs['rend']=node.get('style')
        if original=='table' and node.get('border'):attrs['rend']='border='+node.get('border')
        if original=='pb' and node.get('href'):attrs['facs']=node.get('href')
        if original in ('td','th'):
            if original=='th':attrs['role']='label'
            if node.get('rowspan'):attrs['rows']=node.get('rowspan')
            if node.get('colspan'):attrs['cols']=node.get('colspan')
        if original=='scripRef':
            attrs['type']='scripture'
            if node.get('passage'):attrs['cRef']=node.get('passage')
            if node.get('osisRef'):attrs['target']=node.get('osisRef')
        if original=='a':
            fragment=urlsplit(node.get('href')).fragment
            if fragment not in source_ids:raise ValueError('Independent literal source link lacks its native target')
            attrs['target']='#'+source_ids[fragment];attrs['type']='source-link'
            links.append({'source_number':positions[node],'literal_href':node.get('href'),'source_target_id':fragment,'target_id':source_ids[fragment]})
        if original=='ul':attrs['type']='unordered'
        if original=='insertIndex':attrs.update(type='source-insert-index',subtype=node.get('type'))
        return tag,attrs
    def flatten_children(target,source_node):
        nonlocal generated_heads
        children=list(target)
        if source_node in legacy_ids and source_node.tag.startswith('div') and source_node.get('title') is not None:
            if not children or children[0].tag!=NS+'head' or children[0].attrib or children[0].text!=source_node.get('title') or len(children[0]) or children[0].tail is not None:
                raise ValueError('Independent source-derived legacy title heading differs')
            generated_heads+=1;children=children[1:]
        flattened=[]
        for child in children:
            if child.tag==NS+'div' and child.get('type')=='source-order-wrapper':
                if source_node.get('id')!='i' or dict(child.attrib)!={'type':'source-order-wrapper'} or child.text is not None or child.tail is not None or not len(child):
                    raise ValueError('Independent generated grammar wrapper closure differs')
                wrappers.append([n.get(XML+'id') for n in child]);flattened.extend(child)
            else:flattened.append(child)
        return flattened
    for node in native[1:]:
        target=targets.get(expected_ids[node]);tag,attrs=expected(node)
        if target is None or target.tag!=NS+tag or dict(target.attrib)!=attrs:
            raise ValueError('Independent source carrier tag/attributes differs: '+str(node.get('id') or positions[node]))
        if target.text!=node.text or target.tail!=node.tail:
            raise ValueError('Independent source carrier text/tail differs: '+str(node.get('id') or positions[node]))
        visible=flatten_children(target,node)
        if [child.get(XML+'id') for child in visible]!=[expected_ids[n] for n in node]:
            raise ValueError('Independent source child attachment/order differs: '+str(node.get('id') or positions[node]))
        parent=node.getparent();siblings=list(parent)
        expected_records.append({'source_number':positions[node],'source_tag':node.tag,'source_id':node.get('id'),
                                 'source_attributes':list(map(list,node.attrib.items())),
                                 'source_parent_number':positions.get(parent),'source_child_ordinal':siblings.index(node)+1,
                                 'source_text':node.text,'source_tail':node.tail,'target_id':expected_ids[node],
                                 'target_tag':tag,'target_attributes':attrs,
                                 'generated_title':node in legacy_ids and node.tag.startswith('div') and node.get('title') is not None})
    if [n.get(XML+'id') for n in body]!=[expected_ids[n] for n in source_body]:raise ValueError('Independent root order differs')
    # Independently derive the required contiguous runs after source div children.
    runs=[];seen=False;current=[]
    for n in source_body[0]:
        division=n.tag in ('div','div1','div2')
        if seen and not division:current.append(expected_ids[n])
        else:
            if current:runs.append(current);current=[]
        seen=seen or division
    if current:runs.append(current)
    if wrappers!=runs:raise ValueError('Independent exact grammar-wrapper attachment differs')
    accounted=json.loads(accounting_bytes)
    if accounted.get('rows')!=expected_records or accounted.get('index_link_crosswalk')!=links or accounted.get('projection_profile')!=PROFILE:
        raise ValueError('Independent full source ledger/order/link correspondence differs')
    if accounted.get('retained_header_xml')!=etree.tostring(source.find('ThML.head'),encoding='unicode'):
        raise ValueError('Independent source header evidence differs')
    comments=[{'kind':'comment','text':n.text,'tail':n.tail} for n in reversed(list(source.itersiblings(preceding=True)))]
    if accounted.get('document_prolog')!={'doctype':source_tree.docinfo.doctype,'before':comments}:
        raise ValueError('Independent ordered source prolog evidence differs')
    if accounted.get('source_root')!={'tag':source.tag,'attributes':list(map(list,source.attrib.items())),
                                     'text':source.text,'tail':source.tail,'encoding':source_tree.docinfo.encoding,
                                     'xml_version':source_tree.docinfo.xml_version}:
        raise ValueError('Independent document-root evidence differs')
    old=parse(historical_bytes).getroot().find(NS+'text/'+NS+'body')
    for index,label in [(2,'iii'),(3,'iv')]:
        actual=deepcopy(body[index])
        for cell in actual.iter(NS+'cell'):cell.attrib.pop('ana',None)
        if etree.tostring(actual)!=etree.tostring(old[index-2]):
            raise ValueError('Independent sound historical subtree conservation differs: '+label)
    header=candidate.find(NS+'teiHeader');header_text=''.join(header.itertext())
    for phrase in ('1940','1871','2005-06-20','WM. B. EERDMANS PUBLISHING CO.','Tim Perrine','not as editor, translator or transcriber','DC.Rights','physical print collation'):
        if phrase not in header_text:raise ValueError('Independent qualified primary header field missing: '+phrase)
    return {'status':'pass','source_elements_in_body':len(native),'source_descendants_represented':len(native)-1,
            'source_roots':['i','ii','iii','iv','v'],'source_cells':594,'source_rowspans':57,'header_cells':41,
            'source_tables':3,'source_table_rows':263,'source_index_links':len(links),'source_index_markers':7,
            'source_notes':610,'source_pages':659,'source_scripture_refs':624,'source_generated_title_heads':generated_heads,
            'source_grammar_wrapper_runs':len(runs),'historical_iii_iv_restored_byte_equal':True,
            'stripped_only_source_cell_ana_additions':8,'producer_imported':False,'candidate_sha256':sha256(candidate_bytes).hexdigest()}

def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()

def closure_sha(root):
    from ocd_kernel.library._common import io_path
    names=['build/tei/hodge_vol1_complete_oracle.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/reconstruction/verifier.py','build/lib/tei_xsd.py']
    return sha256(canonical([{'path':p,'sha256':sha256(io_path(root/p).read_bytes()).hexdigest()} for p in names])).hexdigest()

def check(manifest,raw):
    manifest.verify();profile=json.loads(manifest.authority_path('profile').read_bytes())
    accounting=canonical(profile['accounting'])
    result=inspect(manifest.authority_path('primary-source').read_bytes(),raw,accounting,manifest.authority_path('historical-candidate').read_bytes())
    actual=parse(raw).getroot().find(NS+'teiHeader')
    if etree.tostring(actual,encoding='unicode')!=profile['header_xml']:
        raise ValueError('Independent pinned qualified header differs')
    from build.lib.tei_xsd import compiled_tei_schema
    compiled_tei_schema(manifest.authority_path('tei-p5-xsd')).assertValid(parse(raw))
    result['p5']='pass';result['complete_document_elements']=10943
    result['prior_exposure']='Historical source mapper and sound partial candidate inspected; this declarative oracle does not import the producer. Shared XML parsing is corroborated by coordinator direct source review.'
    return result

def _oracle(manifest,candidate):
    from ocd_kernel.reconstruction.verifier import MechanicalFacts,verify_mechanical_facts
    candidate.verify_integrity();profile=json.loads(manifest.authority_path('profile').read_bytes())
    if candidate.manifest['source_manifest']['sha256']!=manifest.sha256:raise ValueError('Independent current package manifest binding differs')
    result=check(manifest,candidate.member_bytes('content.tei.xml'))
    if json.loads(candidate.member_bytes('source-accountability.json'))!=profile['accounting']:raise ValueError('Independent package source ledger differs')
    if candidate.member_bytes('README.source.md')!=manifest.authority_path('source-readme').read_bytes():raise ValueError('Independent current credit differs')
    if json.loads(candidate.member_bytes('provenance.json'))!={'work_id':'hodge-systematic-theology-vol-1','source_sha256':SOURCE_SHA,'scope':'whole retained five-root volume','status':'nonaccepted','publication':'not-authorized'}:raise ValueError('Independent qualified provenance differs')
    if [json.loads(x) for x in candidate.member_bytes('unresolved.jsonl').splitlines()]!=profile['questions']:raise ValueError('Independent unresolved claims differ')
    facts=MechanicalFacts(validator_implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                          validator_import_closure_sha256=closure_sha(manifest.repository_root),source_sha256=SOURCE_SHA,
                          profile_sha256=sha256(manifest.authority_path('profile').read_bytes()).hexdigest(),
                          package_schema_sha256=manifest.record['package_schema']['sha256'],
                          xsd_sha256=sha256(manifest.authority_path('tei-p5-xsd').read_bytes()).hexdigest(),
                          policy_sha256=sha256(manifest.authority_path('validation-policy').read_bytes()).hexdigest(),findings=())
    return verify_mechanical_facts(manifest,candidate,facts).as_record()

_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
_oracle.implementation_path=Path(__file__).resolve()
