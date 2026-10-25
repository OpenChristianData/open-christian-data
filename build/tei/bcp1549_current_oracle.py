"""Independent retained HTML inverse/conservation check; never imports producer.

The declared libxml HTML recovery is an electronic witness reading, not a print
collation. Numeric C1 references use Python's independent HTML entity decoder.
"""
from collections import Counter
from hashlib import sha256
from html import unescape
import json
from pathlib import Path
import re
import platform
import sys
from urllib.parse import unquote,urljoin
from lxml import etree,html
from ocd_kernel.library._common import io_path

NS='{http://www.tei-c.org/ns/1.0}'
XML_ID='{http://www.w3.org/XML/1998/namespace}id'
PREFIX='urn:ocd:bcp1549:html:'
ROOT=Path(__file__).resolve().parents[2]
ORACLE_ID='ocd-bcp1549-independent-native-html-current-v1'
ORACLE_VERSION='1'

def canonical(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def closure_sha(root):
    paths=['build/tei/bcp1549_current_oracle.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/reconstruction/verifier.py','ocd_kernel/reconstruction/__init__.py','ocd_kernel/tei/validate.py','ocd_kernel/lib/storage_topology.py','ocd_kernel/library/acquisitions.py']
    return sha256(canonical([dict(path=p,sha256=sha256(io_path(root/p).read_bytes()).hexdigest()) for p in sorted(paths)])).hexdigest()
def source_digest(manifest):
    records=[{k:a[k] for k in ('name','path','bytes','sha256')} for a in manifest.record['authorities'] if a['role']=='primary-source']
    records.sort(key=lambda a:(a['path'],a['name']))
    if len(records)!=34:raise ValueError('Exact34primary source authority set differs')
    return sha256(canonical(dict(contract='ocd-source-member-set-v1',members=records))).hexdigest()

def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate annotation JSON key')
        result[key]=value
    return result

def source_reading(raw):
    ledger=[]
    def decode(m):
        number=int(m[1],16) if m[1] else int(m[2])
        if not 128<=number<=159:return m[0]
        lexeme=m[0].decode('ascii')
        visible=unescape(lexeme)
        if lexeme not in ('&#149;','&#151;') or len(visible)!=1:
            raise ValueError('Undeclared source numeric reference')
        ledger.append(dict(byte_start=m.start(),byte_end=m.end(),lexeme=lexeme,
                           source_codepoint=number,visible_codepoint=ord(visible),visible_text=visible))
        return ('&#'+str(ord(visible))+';').encode('ascii')
    decoded=re.sub(rb'&#(?:[xX]([0-9a-fA-F]+)|([0-9]+));?',decode,raw)
    parser=html.HTMLParser(encoding='windows-1252',remove_comments=False)
    return html.document_fromstring(decoded,parser=parser),ledger

def _annotation(node):
    value=node.get('rend') if node.tag==NS+'anchor' else node.get('ana')
    if not value or not value.startswith(PREFIX):raise ValueError('Missing exact source annotation')
    fields=value.split(' source-literal-role:',1)
    decoded=json.loads(unquote(fields[0][len(PREFIX):]),object_pairs_hook=unique_object)
    if set(decoded) not in ({'tag','attributes'},{'tag','attributes','comment'}):
        raise ValueError('Source annotation keys differ')
    pairs=decoded['attributes']
    if not isinstance(pairs,list) or any(not isinstance(p,list) or len(p)!=2 or any(not isinstance(v,str) for v in p) for p in pairs) or len({p[0] for p in pairs})!=len(pairs):
        raise ValueError('Ordered source attributes differ')
    if len(fields)==2 and unquote(fields[1])!=' '.join(''.join(node.itertext()).split()):
        raise ValueError('Literal role annotation differs')
    return decoded

def check_body(candidate,acquired,accounting):
    raw=candidate if isinstance(candidate,bytes) else io_path(Path(candidate)).read_bytes()
    parser=etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True,remove_comments=False)
    tree=etree.fromstring(raw,parser)
    if tree.tag!=NS+'TEI' or tree.attrib or [n.tag for n in tree]!=[NS+'teiHeader',NS+'text']:
        raise ValueError('Candidate exact TEI envelope differs')
    if tree[1].attrib or [n.tag for n in tree[1]]!=[NS+'body'] or tree[1][0].attrib:
        raise ValueError('Candidate body envelope differs')
    members=list(tree[1][0]);manifest={Path(m['path']).name:m for m in acquired['retained_files']}
    declared=accounting['members']
    if len(members)!=34 or len(manifest)!=34 or len(declared)!=34 or {m.get('n') for m in members}!=set(manifest):
        raise ValueError('Whole retained34 member inventory differs')
    if [m.get('n') for m in members]!=[p['member'] for p in declared]:
        raise ValueError('Acquired/reading order crosswalk differs')
    original_positions={Path(m['path']).name:i for i,m in enumerate(acquired['retained_files'],1)}
    totals=Counter();details=[];all_ids=[];observed=[]
    for position,(member,proof) in enumerate(zip(members,declared),1):
        name=member.get('n');record=manifest[name];source_raw=io_path(ROOT/record['path']).read_bytes()
        if len(source_raw)!=record['bytes'] or sha256(source_raw).hexdigest()!=record['sha256']:
            raise ValueError('Retained source bytes differ: '+name)
        doc,decoding=source_reading(source_raw);source=doc.find('body')
        if proof['source_sha256']!=record['sha256'] or proof['source_bytes']!=record['bytes'] or proof['acquired_position']!=original_positions[name] or proof['reading_position']!=position or proof['numeric_reference_decoding']!=decoding or proof['source_member_url']!=urljoin(acquired['url'],name):
            raise ValueError('Member/decoder proof differs: '+name)
        if proof['source_header']!=etree.tostring(doc.find('head'),encoding='unicode'):
            raise ValueError('Private HTML head accounting differs: '+name)
        expected_member={'type':'source-member','n':name,XML_ID:'bcp1549-member-'+sha256(name.encode()).hexdigest()[:12]}
        if dict(member.attrib)!=expected_member or len(member)!=2 or member[0].tag!=NS+'head' or member[0].attrib or len(member[0]) or member[0].text!=''.join(doc.find('head/title').itertext()):
            raise ValueError('Literal member title/envelope differs: '+name)
        ordinal=0;local=Counter()
        def paired(src,tei,path):
            nonlocal ordinal
            ordinal+=1;is_comment=not isinstance(src.tag,str)
            tag='#comment' if is_comment else src.tag;attrs=list(map(list,src.attrib.items()))
            decoded=_annotation(tei)
            if decoded['tag']!=tag or decoded['attributes']!=attrs or is_comment and decoded.get('comment')!=src.text:
                raise ValueError('Source tag/ordered attributes differ: '+name+' '+str(path))
            xid='bcp1549-'+sha256(name.encode()).hexdigest()[:12]+'-'+str(ordinal)
            if tei.get(XML_ID)!=xid:raise ValueError('Original source order/ID differs')
            all_ids.append(xid);local[tag]+=1
            basic={XML_ID:xid,'rend' if tei.tag==NS+'anchor' else 'ana':tei.get('rend') if tei.tag==NS+'anchor' else tei.get('ana')}
            expected={'body':'ab','p':'ab','div':'ab','center':'ab','blockquote':'ab','table':'table','tr':'row','td':'cell','ul':'list','li':'item','h2':'ab','br':'lb','hr':'milestone','img':'figure','map':'seg','area':'anchor','#comment':'anchor'}.get(tag)
            inline={'font','span','i','em','b','strong','big','small','sup','a'}
            emphasis={'i':'italic','em':'italic','b':'bold','strong':'bold','big':'large','small':'small','sup':'superscript'}
            if tag in inline:
                block=any(isinstance(q.tag,str) and q.tag in {'p','div','table','tr','td','ul','li','blockquote','center','h2'} for q in src.iterdescendants())
                expected='ab' if block else 'hi' if tag in emphasis else 'ref' if tag=='a' and src.get('href') is not None else 'seg'
                if tag in emphasis and (block or expected=='hi'):basic['rend']=emphasis[tag]
            if expected is None or tei.tag!=NS+expected:raise ValueError('Native source carrier differs')
            if expected=='ab':
                basic['type']='source-h2' if tag=='h2' else 'source-block'
                if tag!='h2':basic['subtype']='html-'+tag
            if expected=='seg':basic['type']='source-html-'+tag
            if expected=='ref':basic['target']=urljoin(urljoin(acquired['url'],name),src.get('href'))
            if expected=='milestone':basic['unit']='source-horizontal-rule'
            if tag=='#comment':basic['type']='source-html-comment'
            if tag=='td':
                if src.get('colspan') is not None:basic['cols']=src.get('colspan')
                if src.get('rowspan') is not None:basic['rows']=src.get('rowspan')
            if dict(tei.attrib)!=basic:raise ValueError('Native projected attribute differs')
            if (tei.text or '')!=(src.text or '') and not is_comment:raise ValueError('Literal source text differs')
            if tag=='img':
                expected_children=[NS+'graphic']+([NS+'figDesc'] if src.get('alt') is not None else [])
                if [n.tag for n in tei]!=expected_children or dict(tei[0].attrib)!={'url':src.get('src','')} or len(tei[0]) or tei[0].text or tei[0].tail:
                    raise ValueError('Exact source graphic differs')
                if len(tei)>1 and (tei[1].attrib or len(tei[1]) or (tei[1].text or '')!=src.get('alt') or tei[1].tail):raise ValueError('Literal graphic alternative differs')
            elif is_comment:
                if len(tei) or tei.text:raise ValueError('Source comment became visible prose')
            else:
                if len(src)!=len(tei):raise ValueError('Source child count differs')
                for i,(child,target) in enumerate(zip(src,tei),1):
                    wrapper=tag=='ul' and isinstance(child.tag,str) and child.tag!='li'
                    if wrapper:
                        if (name,path+[i],child.tag)!=('Baptism_1549.htm',[5,2,10,1,7,1],'p') or target.tag!=NS+'item' or dict(target.attrib)!={'ana':'generated-unlisted-source-child'} or len(target)!=1 or target.text or target[0].tail:
                            raise ValueError('Declared grammar wrapper differs')
                        actual=target[0]
                    else:actual=target
                    paired(child,actual,path+[i])
                    if (target.tail or '')!=(child.tail or ''):raise ValueError('Literal source tail/attachment differs')
            observed.append((name,path,xid,tag,src.text,src.tail,attrs))
        paired(source,member[1],[])
        if member[1].tail or member[0].tail or member.text or member.tail:raise ValueError('Unassigned member prose')
        totals.update(local);details.append(dict(member=name,nodes=ordinal,source_sha256=record['sha256'],numeric_references=len(decoding),rowspans=sum(n.get('rowspan') is not None for n in source.iter('td'))))
    if len(all_ids)!=len(set(all_ids)):raise ValueError('Duplicate native source identity')
    ledger={(n['member'],tuple(n['path'])):n for n in accounting['observations']}
    if len(ledger)!=len(observed) or len(ledger)!=len(accounting['observations']):raise ValueError('Source node accounting omitted/duplicated observations')
    for name,path,xid,tag,text,tail,attrs in observed:
        n=ledger[(name,tuple(path))]
        if n['tei_id']!=xid or n['text']!=text or n['tail']!=tail or tag!='#comment' and (n['tag']!=tag or n['attributes']!=attrs):raise ValueError('Source accounting exact content differs')
        attributes=dict(attrs)
        if 'href' in attributes:
            if n.get('literal_href')!=attributes['href'] or n.get('source_member_url')!=urljoin(acquired['url'],name) or n.get('resolved_source_url')!=urljoin(urljoin(acquired['url'],name),attributes['href']):
                raise ValueError('Literal/resolved source URL crosswalk differs')
    return dict(status='pass',candidate_sha256=sha256(raw).hexdigest(),members=details,source_node_count=len(observed),source_tag_counts=dict(totals),qualification='Complete declared HTML recovered bodies and reversible attributes; raw source hashes/decoder ledger bind retained bytes. This is not print collation or rights clearance.')

def _oracle(manifest,candidate):
    from ocd_kernel.library.acquisitions import validate_acquisition
    from ocd_kernel.tei.validate import compiled_schema
    manifest.verify();candidate.verify_integrity()
    if candidate.manifest['source_manifest']['sha256']!=manifest.sha256 or manifest.record['validator']['import_closure_sha256']!=closure_sha(manifest.repository_root):
        raise ValueError('Current manifest/independent closure differs')
    profile=json.loads(manifest.authority_path('profile').read_bytes())
    acquired=validate_acquisition(manifest.authority_path('canonical-acquisition'),root=manifest.repository_root)
    raw=candidate.member_bytes('content.tei.xml');doc=etree.fromstring(raw)
    def fingerprint(n):return n.tag,tuple(n.attrib.items()),n.text,n.tail,tuple(fingerprint(c) for c in n)
    if fingerprint(doc[0])!=fingerprint(etree.fromstring(profile['header_xml'].encode())):
        raise ValueError('Fresh qualified header differs')
    ledger=json.loads(candidate.member_bytes('source-accountability.json'))
    facts=check_body(raw,acquired,ledger)
    if [p['member'] for p in ledger['members']]!=profile['reading_order'] or acquired['source_sha256']!=profile['source_sha256']:
        raise ValueError('Declared source order/binding differs')
    if candidate.member_bytes('README.source.md')!=manifest.authority_path('source-readme').read_bytes():raise ValueError('Visible source/data notice differs')
    if [json.loads(x) for x in candidate.member_bytes('unresolved.jsonl').splitlines()]!=profile['questions']:raise ValueError('Source qualifications differ')
    if json.loads(candidate.member_bytes('provenance.json'))!=dict(work_id='bcp-1549',source_manifest_sha256=manifest.sha256,scope=profile['scope'],status='nonaccepted'):raise ValueError('Source provenance differs')
    compiled_schema().assertValid(doc)
    for support in profile['retained_support']:
        evidence=io_path(manifest.repository_root/support['path']).read_bytes()
        if len(evidence)!=support['bytes'] or sha256(evidence).hexdigest()!=support['sha256']:raise ValueError('Retained support source differs')
    result=dict(status='pass',oracle_id=ORACLE_ID,oracle_version=ORACLE_VERSION,implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),import_closure_sha256=closure_sha(manifest.repository_root),runtime=f'{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})',source_manifest_sha256=manifest.sha256,candidate_sha256=candidate.sha256,profile_sha256=sha256(manifest.authority_path('profile').read_bytes()).hexdigest(),package_schema_sha256=manifest.record['package_schema']['sha256'],source_sha256=source_digest(manifest),xsd_sha256=sha256(manifest.authority_path('tei-p5-xsd').read_bytes()).hexdigest(),policy_sha256=sha256(manifest.authority_path('validation-policy-current').read_bytes()).hexdigest(),findings=[])
    result['result_sha256']=sha256(canonical(result)).hexdigest()
    return result

_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
_oracle.implementation_path=Path(__file__).resolve()
