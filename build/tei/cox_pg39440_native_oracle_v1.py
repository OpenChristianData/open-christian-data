"""Independent source/field and inverse-envelope check for Cox's native TEI."""
from pathlib import Path
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import quote,unquote
from zipfile import ZipFile
import copy,json,re
from lxml import etree
from ocd_kernel.reconstruction.contract import CandidatePackage,SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts,verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema

T='{http://www.tei-c.org/ns/1.0}';X='{http://www.w3.org/XML/1998/namespace}'
PREFIX='urn:ocd:cox-pg39440:'
BASE='ba5e05ff0bae1a32c1613407e916fb21c0722c46992f1330a9dfc73c50dce39f'
QUALIFICATION='The preceding mapping description documents the retained historical candidate. This source-conserving successor gives its attested hymn divisions, stanza groups, verse lines, headings, gloss labels/items, quotations and line breaks native TEI carriers. All original source fields remain attached and all original text slots are conserved. No human, print, rights or publication decision is added.'

def canonical(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def digest(value):return sha256(value).hexdigest()
def signature(n):return (n.tag,dict(n.attrib),n.text,n.tail,tuple(signature(c) for c in n))

class SourceFields(HTMLParser):
    """Nonrecovering standard-library reader; no lxml source traversal reuse."""
    def __init__(self):
        super().__init__(convert_charrefs=True);self.root={'tag':'document','attributes':{},'text':'','tail':'','children':[]};self.stack=[self.root];self.declarations=[]
    def handle_starttag(self,tag,attrs):
        if len(dict(attrs))!=len(attrs):raise ValueError('duplicate HTML source attribute')
        n={'tag':tag,'attributes':dict(attrs),'text':'','tail':'','children':[]};self.stack[-1]['children'].append(n)
        if tag not in {'br','meta','link','hr','img','input'}:self.stack.append(n)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if self.stack[-1]['tag']==tag:self.stack.pop()
    def handle_endtag(self,tag):
        if self.stack[-1]['tag']!=tag:raise ValueError('source requires parser recovery at '+tag)
        self.stack.pop()
    def handle_data(self,data):
        current=self.stack[-1]
        if current['children']:current['children'][-1]['tail']+=data
        else:current['text']+=data
    def handle_comment(self,data):self.stack[-1]['children'].append({'tag':'#comment','attributes':{},'text':data,'tail':'','children':[]})
    def handle_decl(self,decl):self.declarations.append(decl)

def source_fields(raw):
    p=SourceFields();p.feed(raw.decode('utf-8',errors='strict'));p.close()
    if len(p.stack)!=1:raise ValueError('unclosed source HTML')
    htmls=[n for n in p.root['children'] if n['tag']=='html'];assert len(htmls)==1
    outer=htmls[0];head=next(n for n in outer['children'] if n['tag']=='head');body=next(n for n in outer['children'] if n['tag']=='body');return outer,head,body,p

def norm(value):return ' '.join((value or '').split())

def annotation(n):
    encoded=n.get('rend') if n.tag==T+'label' else n.get('ana')
    if not encoded or not encoded.startswith(PREFIX+'source:'):raise ValueError('missing source-native field binding')
    record=json.loads(unquote(encoded[len(PREFIX+'source:'):]));assert encoded==PREFIX+'source:'+quote(json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':')),safe='')
    assert set(record)=={'source_path','source_tag','source_attributes','previous_tei_attributes','previous_tei_tag'}
    return record

def inverse_body(root):
    body=root.find(T+'text/'+T+'body');assert body is not None and not body.attrib and body.text is None
    source=etree.Element(T+'body',n='L671');records=[]
    def undo(node,parent_tag=None,parent_classes=()):
        rec=annotation(node);path=rec['source_path'];tag=rec['source_tag'];attrs=rec['source_attributes'];classes=(attrs.get('class') or '').split()
        encoded_old=rec['previous_tei_attributes'].get('rend','');assert encoded_old=='source-tag:'+tag+';source-attributes:'+json.dumps(attrs,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        target=etree.QName(node).localname
        if tag=='div':wanted='lg' if 'verse' in classes else 'div' if target=='div' else 'ab'
        elif tag=='p':wanted='l' if parent_tag=='div' and 'verse' in parent_classes else 'p'
        else:wanted={'header':'div','footer':'div','h1':'head','h2':'head','h3':'head','blockquote':'quote','dl':'list','dt':'label','dd':'item','ul':'list','li':'item','pre':'ab','span':'seg','a':'ref','strong':'hi','br':'lb'}[tag]
        assert target==wanted
        expected={'rend' if wanted=='label' else 'ana':node.get('rend') if wanted=='label' else node.get('ana')}
        if attrs.get('id'):expected[X+'id']=attrs['id']
        if attrs.get('lang'):expected[X+'lang']=attrs['lang']
        if tag=='a' and attrs.get('href') is not None:expected['target']=attrs['href']
        if wanted=='div':expected['type']='hymn' if 'hymn' in classes else 'provider-'+tag if tag in ('header','footer') else 'source-html-div'
        elif wanted=='head':expected['type']=tag
        elif wanted=='list':expected['type']='gloss' if tag=='dl' else 'unordered'
        elif wanted=='hi':expected['rend']='strong'
        elif wanted=='lg':expected['type']='stanza'
        elif wanted=='ab':expected['type']='source-pre' if tag=='pre' else 'source-inline-container'
        if tag=='pre':expected[X+'space']='preserve'
        if attrs.get('class') and wanted not in ('label','hi'):expected['rend']='source-class:'+attrs['class']
        if dict(node.attrib)!=expected:raise ValueError('native source attributes differ at '+path+': '+repr({k:(node.get(k),expected.get(k)) for k in set(node.attrib)|set(expected) if node.get(k)!=expected.get(k)})[:700])
        original=etree.Element(T+rec['previous_tei_tag'],attrib=rec['previous_tei_attributes']);original.text=node.text;original.tail=node.tail
        container=node
        if target=='quote' and len(node)==1 and node[0].tag==T+'floatingText':
            floating=node[0];assert dict(floating.attrib)=={'type':'source-blockquote-flow','n':path} and floating.text is None and floating.tail is None and len(floating)==1 and floating[0].tag==T+'body' and not floating[0].attrib and floating[0].tail is None and node.text is None
            container=floating[0];original.text=container.text
        for index,child in enumerate(container):
            item=child
            # Introduced wrappers are shape-constrained and never supply words.
            if (item.get('ana') or '').startswith(PREFIX+'division-flow:'):
                assert item.tag==T+'div' and dict(item.attrib)=={'type':'source-flow-unit','ana':PREFIX+'division-flow:'+quote(path+':'+str(index),safe='')} and item.text is None and item.tail is None and len(item)==1
                item=item[0]
            if (item.get('ana') or '').startswith(PREFIX+'flow:'):
                assert item.tag==T+'ab' and dict(item.attrib)=={'type':'source-inline-container','ana':PREFIX+'flow:'+quote(path+':'+str(index),safe='')} and item.text is None and item.tail is None and len(item)==1
                item=item[0]
            if (item.get('ana') or '').startswith(PREFIX+'slot:'):
                suffix=unquote(item.get('ana')[len(PREFIX+'slot:'):]);assert item.tag==T+'ab' and set(item.attrib)=={'ana','type'} and item.get('type')=='source-block' and len(item)==0 and item.tail is None
                if suffix==path+':text':assert index==0 and original.text is None;original.text=item.text
                else:
                    assert suffix==path+':tail:'+str(index-1) and len(original) and original[-1].tail is None;original[-1].tail=item.text
            else:original.append(undo(item,tag,classes))
        if tag=='div':
            block_children=any((c.get('rend') or '').split(';',1)[0].removeprefix('source-tag:') in {'header','footer','div','p','h1','h2','h3','blockquote','dl','dt','dd','ul','li','pre'} for c in original)
            assert wanted==('lg' if 'verse' in classes else 'div' if block_children else 'ab')
        records.append(rec|{'native_tag':wanted});return original
    units=[n for n in body.iter(T+'div') if (n.get('ana') or '').startswith(PREFIX+'unit:')]
    for ordinal,unit in enumerate(units,1):
        path='body/'+str(ordinal);assert dict(unit.attrib)=={'type':'source-html-unit','ana':PREFIX+'unit:'+quote(path,safe='')} and unit.text is None and unit.tail is None
        mapped=[n for n in unit if not (n.get('ana') or '').startswith(PREFIX+'unit:')];assert len(mapped)==1
        wrapper=etree.SubElement(source,T+'p',n=path);wrapper.append(undo(mapped[0]))
        empty=not ''.join(mapped[0].itertext()).strip()
        if empty:assert ordinal>1 and unit.getparent() is units[ordinal-2]
        else:assert unit.getparent() is body
        assert all(c is mapped[0] or (c.get('ana') or '').startswith(PREFIX+'unit:') for c in unit)
    assert len(units)==125 and len(body)==123
    return source,records

def complete_check(manifest,candidate):
    original=manifest.authority_path('previous-content').read_bytes();assert digest(original)==BASE
    old=etree.fromstring(original);actual=etree.fromstring(candidate.member_bytes('content.tei.xml'));assert compiled_schema().validate(actual)
    assert actual.tag==old.tag and dict(actual.attrib)==dict(old.attrib) and [n.tag for n in actual]==[T+'teiHeader',T+'text']
    header=copy.deepcopy(actual[0]);encoding=header.find(T+'encodingDesc');assert encoding[-1].tag==T+'p' and not encoding[-1].attrib and encoding[-1].text==QUALIFICATION and len(encoding[-1])==0;encoding.remove(encoding[-1]);assert signature(header)==signature(old[0])
    assert dict(actual[1].attrib)==dict(old[1].attrib) and actual[1].text==old[1].text and actual[1].tail==old[1].tail and [n.tag for n in actual[1]]==[T+'body']
    restored,records=inverse_body(actual);assert signature(restored)==signature(old.find(T+'text/'+T+'body'))
    raw=manifest.authority_path('extracted-html').read_bytes();outer,head,body,parser=source_fields(raw);profile=json.loads(manifest.authority_path('profile').read_bytes())
    head_profile=profile['head_metadata_disposition'];assert outer['attributes']==head_profile['html_root_attributes'] and len(head['children'])==head_profile['head_direct_child_count']==31
    for ordinal,(observed,wanted) in enumerate(zip(head['children'],head_profile['head_children'],strict=True)):
        assert observed['tag']==wanted['tag'] and observed['attributes']==wanted['attributes']
        # HTML parsers interpret CR/CRLF differently; meaningful slot equality
        # is corroborated here, while exact retained and candidate bytes remain pinned.
        assert digest(observed['text'].replace('\r\r\n','\r\n').encode())==wanted['text_sha256']
        assert digest(observed['tail'].replace('\r\r\n','\r\n').encode())==wanted['tail_sha256']
    expected={}
    def inventory(node,path,parent):
        assert node['tag']!='#comment';expected[path]=node|{'parent':parent}
        for i,child in enumerate(node['children'],1):inventory(child,path+'/'+str(i),path)
    for i,node in enumerate(body['children'],1):inventory(node,'body/'+str(i),'body')
    targets=restored.xpath('.//t:seg[@n]|.//t:ref[@n]',namespaces={'t':T[1:-1]});assert len(expected)==len(targets)==6547
    assert list(expected)==[n.get('n') for n in targets]
    for n in targets:
        row=expected[n.get('n')];attrs=json.loads(n.get('rend').split(';source-attributes:',1)[1]);assert n.get('rend').split(';',1)[0]=='source-tag:'+row['tag'] and attrs==row['attributes']
        assert norm(n.text)==norm(row['text']) and norm(n.tail)==norm(row['tail'])
        parent=n.getparent();actual_parent=parent.get('n') if parent.tag in (T+'seg',T+'ref') else 'body';assert actual_parent==row['parent']
    old_package=CandidatePackage.load(manifest.authority_path('previous-package-manifest').parent);old_package.verify_integrity()
    assert old_package.sha256=='97919e14018d84b83763344cda097e38fb9a702c8d2fa3af1db7035a5b6b00d2'
    with ZipFile(manifest.authority_path('retained-archive')) as archive:
        assert archive.testzip() is None
        members=[{'path':i.filename,'bytes':i.file_size,'crc32':f'{i.CRC:08x}','sha256':digest(archive.read(i))} for i in archive.infolist() if not i.is_dir()]
        assert members==profile['archive_members'] and archive.read(profile['html_member'])==raw
    account=json.loads(candidate.member_bytes('source-accountability.json'));old_account=json.loads(manifest.authority_path('previous-accountability').read_bytes())
    assert set(account)==set(old_account)|{'previous_candidate_sha256','native_mapping','native_mapping_policy'}
    assert {k:v for k,v in account.items() if k in old_account and k!='tei_sha256'}=={k:v for k,v in old_account.items() if k!='tei_sha256'}
    assert account['tei_sha256']==digest(candidate.member_bytes('content.tei.xml')) and account['previous_candidate_sha256']==BASE and account['native_mapping']==records
    assert account['native_mapping_policy']=='Source hymn divisions, stanza groups, verse lines, headings, gloss labels/items, quotations and twenty line breaks have native TEI carriers. Every original source tag/attribute/path and prior TEI field remains in its exact attached source annotation; complete text/tail slots and original header are conserved. Language is copied only from literal lang fields, never inferred from paired hymn IDs.'
    for name,authority in [('README.source.md','readme'),('provenance.json','previous-provenance'),('unresolved.jsonl','previous-unresolved')]:assert candidate.member_bytes(name)==manifest.authority_path(authority).read_bytes()
    return {'source_carriers':6547,'body_units':125,'native_rows':123,'verse_groups':len(actual.findall('.//'+T+'lg')),'verse_lines':len(actual.findall('.//'+T+'l')),'line_breaks':len(actual.findall('.//'+T+'lb')),'complete_inverse_previous_envelope':True,'independent_html_parser_fields':True,'literal_languages_only':True}

def closure(root):
    paths=['build/tei/cox_pg39440_native_oracle_v1.py','build/tei/l671_l674_semantic_oracle.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/reconstruction/verifier.py','ocd_kernel/tei/validate.py']
    return digest(canonical([{'path':p,'sha256':digest((root/p).read_bytes())} for p in paths]))

def _oracle(manifest,candidate):
    complete_check(manifest,candidate);bound=closure(manifest.repository_root);assert bound==manifest.record['validator']['import_closure_sha256']
    facts=MechanicalFacts(validator_implementation_sha256=digest(Path(__file__).read_bytes()),validator_import_closure_sha256=bound,source_sha256=digest(manifest.authority_path('retained-archive').read_bytes()),profile_sha256=digest(manifest.authority_path('profile').read_bytes()),package_schema_sha256=digest(manifest.authority_path('candidate-package-schema').read_bytes()),xsd_sha256=digest(manifest.authority_path('tei-p5-xsd').read_bytes()),policy_sha256=digest(manifest.authority_path('policy').read_bytes()),findings=())
    return verify_mechanical_facts(manifest,candidate,facts).as_record()

_oracle.oracle_id='ocd-cox-pg39440-complete-native-envelope-oracle'
_oracle.oracle_version='1'
_oracle.implementation_path=Path(__file__).resolve()
