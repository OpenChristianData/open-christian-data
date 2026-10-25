"""Independent complete-envelope and selected-markup checker for BCP1928."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import html as html_lib
import json
from pathlib import Path
import re

from lxml import etree, html
from jsonschema import Draft202012Validator

from build.tei.bcp_1928_oracle import _source_expectations
from ocd_kernel.reconstruction.contract import SourceManifest, _validation_authority_bindings
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema

ORACLE_ID = "ocd-bcp1928-complete-envelope-independent-oracle"
ORACLE_VERSION = "2"
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"

def _closure():
    digest=sha256()
    for path in (Path(__file__),Path('build/tei/bcp_1928_oracle.py'),Path('ocd_kernel/reconstruction/contract.py'),Path('ocd_kernel/reconstruction/verifier.py'),Path('ocd_kernel/tei/validate.py')):
        digest.update(path.name.encode()+b'\n'+path.read_bytes()+b'\n')
    return digest.hexdigest()

def _fragment(raw):
    source=raw.decode('utf-8')
    clean=re.sub(r'<(?:script|noscript)\b[^>]*>.*?</(?:script|noscript)\s*>',' ',source,flags=re.I|re.S)
    clean=re.sub(r'<!--.*?-->',' ',clean,flags=re.S)
    marker=re.search(r'The\s+Collects?\s*\.',clean,re.I)
    if marker:
        closing=re.search(r'</(?:center|p)\s*>',clean[marker.end():],re.I)
        if not closing:return ''
        start=marker.end()+closing.end()
    else:
        heading=re.search(r'</h2\s*>',clean,re.I)
        if not heading:return ''
        start=heading.end()
    for paragraph in re.finditer(r'<p\b[^>]*>(.*?)</p\s*>',clean[start:],re.I|re.S):
        fragment=paragraph.group(1)
        plain=' '.join(html_lib.unescape(re.sub(r'<[^>]+>',' ',fragment)).split())
        if marker and plain:return fragment
        if not marker and len(plain.split())>=10 and re.search(r'(?:amen[.!]?|\[who\.\])$',plain,re.I):return fragment
    return ''

def _title(raw):
    source=raw.decode('utf-8')
    source=re.sub(r'<(?:script|noscript)\b[^>]*>.*?</(?:script|noscript)\s*>',' ',source,flags=re.I|re.S)
    source=re.sub(r'<!--.*?-->',' ',source,flags=re.S)
    heading=re.search(r'</h2\s*>',source,re.I)
    value=''
    if heading:
        tail=source[heading.end():]
        marker=re.search(r'The\s+Collect',tail,re.I)
        region=tail[:marker.start() if marker else 600]
        choices=list(re.finditer(r'<(b|strong|em)\b[^>]*>(.*?)</\1\s*>',region,re.I|re.S))
        if choices:
            value=html_lib.unescape(re.sub(r'<[^>]+>',' ',choices[0].group(2)))
            value=re.sub(r'\[[^\]]*\]','',value)
            value=' '.join(re.sub(r'[\[\]()]',' ',value).split()).rstrip('.')
    if not value:
        doc=html.fromstring(raw)
        titles=doc.xpath('//title/text()')
        if not titles:raise ValueError('source occasion title missing')
        value=re.sub(r'\s*Propers?\s*\(1928\s*BCP\)\s*','',titles[0],flags=re.I)
        value=re.sub(r'\s*\(1928\s*BCP\)\s*','',value,flags=re.I)
        value=' '.join(value.split())
    return value

def _tokens(raw,fragment):
    source=raw.decode('utf-8');begin=source.find(fragment) if fragment else -1;end=begin+len(fragment) if fragment else -1
    if fragment and (begin<0 or source.find(fragment,begin+1)>=0):raise ValueError('source fragment ambiguity')
    cursor=0;tokens=[]
    while cursor<len(source):
        start=cursor
        if source.startswith('<!--',cursor):
            stop=source.find('-->',cursor+4)
            if stop<0:raise ValueError('unterminated source comment')
            cursor=stop+3
        elif source[cursor]=='<':
            quote=None;cursor+=1
            while cursor<len(source):
                char=source[cursor];cursor+=1
                if quote:
                    if char==quote:quote=None
                elif char in ('\"',"'"):quote=char
                elif char=='>':break
            else:raise ValueError('unterminated source markup')
        else:
            stop=source.find('<',cursor);cursor=len(source) if stop<0 else stop
        literal=source[start:cursor]
        tokens.append(dict(position=len(tokens)+1,start=start,end=cursor,kind='markup' if literal.startswith('<') else 'text',sha256=sha256(literal.encode()).hexdigest(),disposition='selected-collect-carrier' if begin>=0 and start>=begin and cursor<=end else 'outside-collect-selection'))
    return tokens,begin,end

def _events(node,source=False):
    events=[]
    def text(value):
        if not value:return
        if events and events[-1][0]=='text':events[-1]=('text',events[-1][1]+value)
        else:events.append(('text',value))
    def visit(n):
        tag=n.tag if source else etree.QName(n).localname
        attrs=dict(n.attrib)
        if not source and tag=='seg':
            text(n.text)
            for c in n:visit(c);text(c.tail)
            return
        if source:
            if tag=='br' and not attrs:tag='lb'
            elif tag=='a' and attrs=={'name':'anchor1121543','id':'anchor1121543'} and not ''.join(n.itertext()):tag='anchor';attrs={XML+'id':'anchor1121543'}
            elif tag=='font' and attrs=={'color':'#000000'}:tag='hi';attrs={'rend':'color:#000000'}
            elif tag!='div':raise ValueError('unrecognized source collect markup')
        events.append(('start',tag,tuple(sorted(attrs.items()))));text(n.text)
        for c in n:visit(c);text(c.tail)
        events.append(('end',tag))
    text(node.text)
    for child in node:visit(child);text(child.tail)
    return events

def _header(profile):
    root=etree.Element(NS+'teiHeader',nsmap={None:NS[1:-1]})
    desc=etree.SubElement(root,NS+'fileDesc');title=etree.SubElement(desc,NS+'titleStmt');etree.SubElement(title,NS+'title').text=profile['title']
    pub=etree.SubElement(desc,NS+'publicationStmt');etree.SubElement(pub,NS+'publisher').text='Open Christian Data'
    avail=etree.SubElement(pub,NS+'availability',status='restricted');etree.SubElement(avail,NS+'p').text='Nonaccepted source-bound candidate; technical reconstruction does not establish human acceptance or publication authorization.'
    source=etree.SubElement(desc,NS+'sourceDesc');bibl=etree.SubElement(source,NS+'bibl');etree.SubElement(bibl,NS+'title').text=profile['title'];etree.SubElement(bibl,NS+'ref',target=profile['source_url']).text='Retained source provider';etree.SubElement(bibl,NS+'idno',type='SHA-256').text=profile['source_bundle']['sha256']
    enc=etree.SubElement(root,NS+'encodingDesc');proj=etree.SubElement(enc,NS+'projectDesc');etree.SubElement(proj,NS+'p').text='The two Trinity manual claims are not represented because their exact alternate witness bytes remain unretained.'
    rev=etree.SubElement(root,NS+'revisionDesc',status='candidate');etree.SubElement(rev,NS+'change').text='Deterministic partial reconstruction from 100 retained HTML members.'
    return root

def _signature(node):
    # Compare expanded names and every ordered attribute/text/tail/child count;
    # lxml's inherited default-namespace C14N output differs after detachment.
    return [(n.tag,tuple(sorted(n.attrib.items())),n.text,n.tail,len(n)) for n in node.iter()]

def _oracle(manifest,candidate):
    manifest.verify();candidate.verify_integrity()
    profile=json.loads(manifest.authority_path('reconstruction-profile').read_bytes())
    expected,info=_source_expectations(manifest)
    account=json.loads(candidate.member_bytes('source-accountability.json'))
    schema=json.loads(manifest.authority_path('source-accountability-schema').read_bytes())
    errors=list(Draft202012Validator(schema).iter_errors(account))
    if errors:raise ValueError('source accountability schema differs: '+errors[0].message)
    ledger=account['carrier_ledger']
    if [{k:r[k] for k in ('id','source_path','source_page_order','text')} for r in account['records']]!=expected:raise ValueError('complete source collect accounting differs')
    if account['pages_without_collect']!=info['pages_without_collect'] or info['pages_without_collect']!=['Trinity23.html','Trinity24.html']:raise ValueError('missing source collects differ')
    raw=candidate.member_bytes('content.tei.xml');root=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True))
    if not compiled_schema().validate(etree.ElementTree(root)):raise ValueError('BCP1928 TEI schema failed')
    if _signature(root[0])!=_signature(_header(profile)):raise ValueError('whole source header differs')
    if list(root.attrib) or [etree.QName(n).localname for n in root]!=['teiHeader','text']:raise ValueError('source TEI envelope differs')
    text=root[1]
    if text.attrib or [etree.QName(n).localname for n in text]!=['front','body'] or len(text[0]) or text[0].attrib or text[0].text:raise ValueError('native routing marker differs')
    pages=list(text[1]);members=manifest.record['source_members']
    expected_members=[dict(name=str(m['logical_name']),path=str(m['path']),bytes=m['bytes'],sha256=m['sha256'],order=i) for i,m in enumerate(members)]
    fixed={'contract':'ocd-bcp-1928-source-accountability-v1','schema':'sources/prayers/bcp-1928-collects/bcp1928-current.source-accountability.schema.json','profile_id':profile['profile_id'],'work_id':'bcp-1928-collects','source_id':manifest.record['source_id'],'source_bundle':dict(profile['source_bundle']),'source_members':expected_members,'record_count':100,'omitted_record_count':2,'duplicated_record_count':0}
    for key,value in fixed.items():
        if account.get(key)!=value:raise ValueError('source accountability metadata differs: '+key)
    manual=[dict(id=name,source_page=page,alternate_witness='archive.org/details/1928bookofcommon0000prot',scan_pages=[number],claim_text_sha256=digest,status='unbound-alternate-witness') for name,page,number,digest in [('trinity23','Trinity23.html',222,'f4de9d0227f2ef29fca643e15e9cd20348f7f9f16bd58ff70a334858442d1845'),('trinity24','Trinity24.html',223,'cabff3744664ced376b5f47919e492c496727ab22b10bce00f14ff8c9e343faf')]]
    if account['manual_claims']!=manual:raise ValueError('unbound alternate-witness metadata differs')
    if root.text or root.tail or text.text or text.tail or text[1].text or text[1].tail or text[1].attrib:raise ValueError('loose source envelope content differs')
    if len(pages)!=100 or len(ledger['members'])!=100 or ledger['unbound_manual_claims']!=['trinity23','trinity24']:raise ValueError('whole source member envelope differs')
    if ledger['status']!='partial-collect-selection' or ledger['routing_front']!='empty native-document marker, no source content':raise ValueError('source scope marker differs')
    by_path={};features=Counter();observed_records=[]
    for record in expected:by_path.setdefault(record['source_path'],[]).append(record)
    for i,(page,member,entry) in enumerate(zip(pages,members,ledger['members'])):
        path=str(member['path']);source=(manifest.repository_root/path).read_bytes();fragment=_fragment(source);tokens,begin,end=_tokens(source,fragment)
        if set(entry)!={'path','bytes','sha256','characters','selected_fragment_start','selected_fragment_end','tokens','exclusion_reason'}:raise ValueError('unknown source carrier metadata')
        for key,value in dict(path=path,bytes=len(source),sha256=sha256(source).hexdigest(),characters=len(source.decode()),selected_fragment_start=begin,selected_fragment_end=end,tokens=tokens).items():
            if entry.get(key)!=value:raise ValueError(f'whole source carrier inventory differs: {path} {key}')
        if entry.get('exclusion_reason')!='Other propers, hymns, navigation, styling, scripts and provider page material are outside this explicitly partial collect selection; their exact bytes remain retained.':raise ValueError('source disposition reason differs')
        attrs={'type':'source-page','n':str(member['logical_name']),XML+'id':'page-'+re.sub(r'[^a-zA-Z0-9]+','-',str(member['logical_name'])).strip('-').lower()}
        if page.tag!=NS+'div' or dict(page.attrib)!=attrs or page.text or page.tail:raise ValueError('source page order or identity differs')
        records=by_path.get(path,[])
        if not records:
            if fragment or len(page)!=1 or page[0].tag!=NS+'note' or dict(page[0].attrib)!={'type':'source-page-without-collect'} or page[0].text!='No collect is present in the retained HTML; the alternate witness claim remains unresolved.':raise ValueError('unbound collect leaked into candidate')
            continue
        title=_title(source)
        if len(page)!=2 or page[0].tag!=NS+'head' or page[0].attrib or len(page[0]) or page[0].text!=title or page[0].tail or page[1].tag!=NS+'p' or page[1].attrib or page[1].tail:raise ValueError('source occasion or paragraph boundary differs: '+path)
        source_tree=html.fragment_fromstring(fragment,create_parent='div')
        if _events(source_tree,source=True)!=_events(page[1]):raise ValueError('complete selected markup differs: '+path)
        segments=page[1].xpath('.//t:seg',namespaces={'t':NS[1:-1]})
        if len(segments)!=len(records):raise ValueError('collect segmentation count differs')
        for segment,record in zip(segments,records):
            if dict(segment.attrib)!={'type':'collect','n':record['id'],XML+'id':'collect-'+record['id']} or ' '.join(''.join(segment.itertext()).split())!=record['text']:raise ValueError('collect attachment, identifier or source wording differs')
            observed_records.append(record['id'])
        for n in page[1].iter():features[etree.QName(n).localname]+=1
    if observed_records!=[r['id'] for r in expected] or ledger['features']!=dict(features):raise ValueError('source feature or record order differs')
    if account['tei']!={'bytes':len(raw),'sha256':sha256(raw).hexdigest()}:raise ValueError('candidate accountability binding differs')
    for record in account['records']:
        member=next(m for m in members if m['path']==record['source_path']);source=(manifest.repository_root/str(member['path'])).read_bytes()
        if record['title']!=_title(source) or record['text_sha256']!=sha256(record['text'].encode()).hexdigest() or record['word_count']!=len(record['text'].split()) or record['tei_id']!='collect-'+record['id'] or record['disposition']!='represented':raise ValueError('source record metadata differs')
    provenance=json.loads(candidate.member_bytes('provenance.json'))
    authorities={str(item['name']):{key:item[key] for key in ('path','bytes','sha256','role') if key in item} for item in manifest.record['authorities']}
    expected_provenance={'contract':'ocd-bcp-1928-candidate-provenance-v1','status':'nonaccepted','source_manifest_sha256':manifest.sha256,'source_bundle':dict(profile['source_bundle']),'authorities':authorities,'scope':'100 retained HTML members; 100 page-derived collects; two manual claims unresolved','rights':{'status':'human-review-required','publication_authorized':False}}
    if provenance!=expected_provenance:raise ValueError('complete candidate provenance authority differs')
    unresolved=[dict(id=name,kind='alternate-witness',status='unbound',source_page=page,witness='archive.org/details/1928bookofcommon0000prot',scan_page=number,reason='manual text exists in the legacy producer but no exact retained witness bytes are bound') for name,page,number in [('trinity23','Trinity23.html',222),('trinity24','Trinity24.html',223)]]
    unresolved.extend(dict(id=name,kind='review-gate',status='open') for name in ('candidate-human-acceptance','rights-clearance','cvw-visual-review','durable-admission','publication-authorization'))
    if [json.loads(line) for line in candidate.member_bytes('unresolved.jsonl').splitlines()]!=unresolved:raise ValueError('whole uncertainty record differs')
    readme=('# BCP 1928 Collects retained-source candidate\n\nThis nonaccepted candidate reconstructs the 100 retained HTML pages and their 100 page-derived collect records. Trinity 23 and Trinity 24 are left unresolved: the legacy producer records an Internet Archive scan claim, but those exact witness bytes are not retained and therefore are not represented in the TEI. Technical validation does not establish human acceptance, rights clearance, or publication authorization.\n').encode()
    if candidate.member_bytes('README.source.md')!=readme:raise ValueError('source scope README differs')
    bindings=_validation_authority_bindings(manifest)
    facts=MechanicalFacts(validator_implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),validator_import_closure_sha256=_closure(),findings=(),**bindings)
    return verify_mechanical_facts(manifest,candidate,facts).as_record()

_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
