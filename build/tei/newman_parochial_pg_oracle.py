"""Independent source enumeration, semantic inline observation and inverse check.

This module imports no reconstruction or producer traversal. Source paragraphs
are enumerated by blank-line spans; XML is observed with the standard library.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET
from lxml import etree
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema

T = '{http://www.tei-c.org/ns/1.0}'
X = '{http://www.w3.org/XML/1998/namespace}'
ROMANS = ('I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII','XIII','XIV','XV','XVI','XVII','XVIII')
MEMBERS = {
    'pg24256.txt': ('VII',386616,'713da47f79c97a5b188bd50a43a97a9a419d72c5ee92605b1e3d5effcb86b789',143),
    'pg24284.txt': ('VIII',406274,'b172c4f0379098ac1fdca2fbc27b08fb830c4eea5ce43d39d0263887b7fa3f53',201),
}
ENCODING = 'Exact retained electronic volume only. UTF-8 BOM is accounted as encoding and CRLF becomes LF. All book characters, paragraph boundaries, wrapped lines and source footnote labels are conserved; paired underscore markers become italic hi with an explicit reversible source annotation. Numeric footnote labels link only within their own source-defined sermon when the exact definition exists. No Bible reference normalization or source-error correction. Provider opening, markers, complete footer/license and source credit are retained in README.source.md.'


def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()


def digest(value):
    return sha256(value).hexdigest()


def enumerate_source(raw, logical):
    volume,size,source_sha,notes = MEMBERS[Path(logical).name]
    assert len(raw)==size and digest(raw)==source_sha, 'retained Newman source bytes differ'
    text=raw.decode('utf-8-sig').replace('\r\n','\n')
    assert '\r' not in text
    lines=text.splitlines(keepends=True)
    positions=[];offset=0;start_lines=[];end_lines=[];headings=[];terminal=[]
    for line in lines:
        positions.append(offset)
        if line.startswith('*** START OF THE PROJECT GUTENBERG EBOOK ') and line.endswith(' ***\n'):start_lines.append((offset,offset+len(line)))
        if line.startswith('*** END OF THE PROJECT GUTENBERG EBOOK ') and line.endswith(' ***\n'):end_lines.append((offset,offset+len(line)))
        if line.startswith('SERMON '):
            label=line[len('SERMON '):].strip().removesuffix('.')
            if label in ROMANS:headings.append((offset,label))
        if line=='END OF VOL. '+volume+'.\n':terminal.append(offset)
        offset+=len(line)
    assert offset==len(text) and len(start_lines)==len(end_lines)==len(terminal)==1
    first,last=start_lines[0][1],end_lines[0][0]
    assert len(headings)==36 and tuple(h[1] for h in headings[:18])==ROMANS and tuple(h[1] for h in headings[18:])==ROMANS
    assert first<headings[0][0]<headings[18][0]<terminal[0]<last
    regions=[dict(role='front',start=first,stop=headings[18][0])]
    for i,(start,label) in enumerate(headings[18:]):
        regions.append(dict(role='sermon',number=str(i+1),roman=label,start=start,
                            stop=headings[19+i][0] if i<17 else terminal[0]))
    regions.append(dict(role='back',start=terminal[0],stop=last))
    exceptions=[];definition_total=0;carriers=[];slug=Path(logical).stem
    for region in regions:
        region_text=text[region['start']:region['stop']]
        spans=[];cursor=0
        for match in re.finditer(r'(?m)^(?:[ \t]*\n)+',region_text):
            if match.start()>cursor:spans.append((cursor,match.start(),False))
            spans.append((match.start(),match.end(),True));cursor=match.end()
        if cursor<len(region_text):spans.append((cursor,len(region_text),False))
        assert ''.join(region_text[a:b] for a,b,_ in spans)==region_text
        blocks=[dict(start=region['start']+a,stop=region['start']+b,text=region_text[a:b],whitespace=w) for a,b,w in spans]
        meaningful=[b for b in blocks if not b['whitespace']]
        labels={}
        if region['role']=='sermon':
            assert meaningful[0]['text'].strip().removesuffix('.')=='SERMON '+region['roman'] and meaningful[2]['text'].startswith('"')
            for block in meaningful:
                m=re.match(r'^\[(\d+)\] ',block['text'])
                if m:
                    assert m[1] not in labels
                    labels[m[1]]=block['start'];block['label']=m[1]
            definition_total+=len(labels)
        region['labels']=labels;region['blocks']=blocks;seen=set()
        for i,block in enumerate(meaningful):
            block['kind']='head' if region['role']=='back' or (region['role']=='sermon' and i<2) else 'quote' if region['role']=='sermon' and i==2 else 'note' if 'label' in block else 'p'
            for m in re.finditer(r'\[(\d+)\]',block['text']):
                if 'label' in block and m.start()==0:continue
                if region['role']=='sermon':
                    seen.add(m[1])
                    if m[1] not in labels:exceptions.append(dict(kind='unbound-note-reference',sermon=region['number'],label=m[1],character=block['start']+m.start()))
            for m in re.finditer(r"\[Transcriber's note:[^\]]+\]",block['text']):
                exceptions.append(dict(kind='literal-transcriber-uncertainty',sermon=region.get('number'),character=block['start']+m.start(),wording=m[0]))
        for label,position in labels.items():
            if label not in seen:exceptions.append(dict(kind='orphan-note-definition',sermon=region['number'],label=label,character=position))
        for n,block in enumerate(blocks,1):
            feature=slug+'-'+region['role']+region.get('number','')+'-b'+str(n)
            block['feature']=feature
            carriers.append(dict(carrier_id=feature,start=block['start'],stop=block['stop'],source_sha256=digest(block['text'].encode()),disposition='structural-whitespace' if block['whitespace'] else block['kind']))
    assert definition_total==notes
    front=text[first:headings[18][0]]
    for literal in ('JOHN HENRY NEWMAN, B.D.\n','New Edition\n','Longmans, Green, and Co.\n','1891\n','E-text prepared by Al Haines\n','VOL. '+volume+'.\n'):
        assert literal in front, 'source title-page assertion differs'
    return dict(source_path=logical,source_sha256=source_sha,source_bytes=size,volume=volume,
                text=text,book_start=first,book_stop=last,regions=regions,carriers=carriers,
                note_definitions=definition_total,exceptions=exceptions)


def source_inline(text,labels,slug,number,offset=0):
    """Character-scanning interpretation, independent of producer token regex."""
    features=[];i=0
    while i<len(text):
        if text[i]=='_':
            end=text.find('_',i+1);assert end>i+1, 'unmatched emphasis delimiter'
            features.append(dict(kind='italic',start=offset+i,stop=offset+end+1))
            features.extend(source_inline(text[i+1:end],labels,slug,number,offset+i+1));i=end+1;continue
        if text.startswith("[Transcriber's note:",i):
            end=text.find(']',i);assert end>i
            features.append(dict(kind='transcriber',start=offset+i,stop=offset+end+1));i=end+1;continue
        if text[i]=='[':
            end=text.find(']',i+1)
            if end!=-1 and text[i+1:end].isdigit():
                label=text[i+1:end];record=dict(kind='reference' if label in labels else 'unbound',start=offset+i,stop=offset+end+1,label=label)
                if label in labels:record['target']='#'+slug+'-s'+number+'-n'+label
                features.append(record);i=end+1;continue
        i+=1
    return features


def observe_inline(node,offset=0):
    result=node.text or '';features=[]
    for child in node:
        start=offset+len(result);tag=child.tag
        if tag==T+'hi':
            assert child.attrib=={'rend':'italic','ana':'urn:ocd:newman-parochial:underscore-delimited'}
            inner,nested=observe_inline(child,start+1)
            reconstructed='_'+inner+'_'
            features.append(dict(kind='italic',start=start,stop=start+len(reconstructed)));features.extend(nested)
        elif tag==T+'note':
            assert child.attrib=={'type':'transcriber'} and not len(child)
            reconstructed=child.text or '';assert reconstructed.startswith("[Transcriber's note:") and reconstructed.endswith(']')
            features.append(dict(kind='transcriber',start=start,stop=start+len(reconstructed)))
        elif tag in (T+'ref',T+'seg'):
            assert not len(child) and re.fullmatch(r'\[\d+\]',child.text or '')
            reconstructed=child.text;label=reconstructed[1:-1]
            record=dict(kind='reference' if tag==T+'ref' else 'unbound',start=start,stop=start+len(reconstructed),label=label)
            if tag==T+'ref':
                assert set(child.attrib)=={'type','target'} and child.get('type')=='note-reference';record['target']=child.get('target')
            else:assert child.attrib=={'type':'literal-unbound-note-marker','n':label}
            features.append(record)
        else:raise AssertionError('unsupported Newman inline element '+tag)
        result+=reconstructed+(child.tail or '')
    return result,features


def _header(source):
    root=ET.Element(T+'teiHeader');fd=ET.SubElement(root,T+'fileDesc');ts=ET.SubElement(fd,T+'titleStmt')
    ET.SubElement(ts,T+'title').text='Parochial and Plain Sermons, Vol. '+source['volume']+' (of 8)'
    ET.SubElement(ts,T+'author').text='JOHN HENRY NEWMAN, B.D.'
    ET.SubElement(ET.SubElement(fd,T+'publicationStmt'),T+'p').text='Nonaccepted reconstruction of the exact retained Project Gutenberg electronic witness; human, print, rights and publication decisions remain open.'
    bibl=ET.SubElement(ET.SubElement(fd,T+'sourceDesc'),T+'bibl')
    for tag,value in [('title','PAROCHIAL AND PLAIN SERMONS; VOL. '+source['volume']+'.; New Edition'),('publisher','Longmans, Green, and Co.'),('pubPlace','London; New York: 15 East 16th Street'),('date','1891')]:ET.SubElement(bibl,T+tag).text=value
    ET.SubElement(bibl,T+'idno',type='retained-source-sha256').text=source['source_sha256']
    ET.SubElement(bibl,T+'note',type='source-location').text=source['source_path']
    resp=ET.SubElement(bibl,T+'respStmt');ET.SubElement(resp,T+'resp').text='E-text prepared by';ET.SubElement(resp,T+'name').text='Al Haines'
    ET.SubElement(ET.SubElement(root,T+'encodingDesc'),T+'p').text=ENCODING
    return root


def signature(node):
    return (node.tag,dict(node.attrib),node.text,node.tail,tuple(signature(c) for c in node))


def check_document(raw,logical,content):
    scan=content.replace(b'\x00',b'')
    assert not any(token in scan.upper() for token in (b'<!DOCTYPE',b'<!ENTITY',b'<!--')) and not re.search(br'<\?(?!xml(?:\s|\?>))',scan,re.I), 'unsupported Newman XML declaration/comment/instruction'
    source=enumerate_source(raw,logical);root=ET.fromstring(content)
    assert root.tag==T+'TEI' and not root.attrib and root.text is None and root.tail is None and len(root)==2
    assert signature(root[0])==signature(_header(source)), 'complete source-bound Newman header differs'
    text=root[1];assert text.tag==T+'text' and text.attrib=={X+'lang':'en'} and text.text is None and text.tail is None
    assert [p.tag for p in text]==[T+'front',T+'body',T+'back']
    assert len(text[0])==len(text[2])==1 and len(text[1])==18
    divisions=[text[0][0],*list(text[1]),text[2][0]];slug=Path(logical).stem
    for region,division in zip(source['regions'],divisions,strict=True):
        attrs={'type':'source-div1' if region['role']=='sermon' else 'source-'+region['role'],X+'id':slug+'-'+region['role']+region.get('number','')}
        if region['role']=='sermon':attrs['n']=region['number']
        assert division.tag==T+'div' and division.attrib==attrs and division.tail is None
        blocks=region['blocks'];nodes=iter(division);current=None;prefix=''
        for block in blocks:
            if block['whitespace']:
                if current is None:prefix+=block['text']
                else:assert (current.tail or '')==block['text'];current=None
                continue
            node=next(nodes);current=node
            attrs={X+'id':block['feature'],'corresp':logical+'#characters='+str(block['start'])+'-'+str(block['stop']),X+'space':'preserve'}
            if block['kind']=='head':attrs['type']='source-terminal-label' if region['role']=='back' else 'source-heading'
            if block['kind']=='note':attrs.update({X+'id':slug+'-s'+region['number']+'-n'+block['label'],'n':block['label'],'type':'footnote','place':'end'})
            assert node.tag==T+block['kind'] and node.attrib==attrs, 'source carrier role/identity/coordinates differ'
            reconstructed,features=observe_inline(node)
            assert reconstructed==block['text'], 'complete source text/order/whitespace differs'
            expected_text=block['text'];prefix_length=0
            if block['kind']=='note':prefix_length=len('['+block['label']+'] ');expected_text=expected_text[prefix_length:]
            expected=source_inline(expected_text,region['labels'],slug,region.get('number',''),prefix_length)
            assert features==expected, 'source emphasis/reference/transcriber semantics differ'
        assert next(nodes,None) is None
        # Whitespace preceding the first carrier occupies the division's text;
        # every later whitespace carrier is the immediately preceding tail.
        leading=blocks[0]['text'] if blocks and blocks[0]['whitespace'] else ''
        assert (division.text or '')==leading
        assert (division.text or '')+''.join(observe_inline(n)[0]+(n.tail or '') for n in division)==source['text'][region['start']:region['stop']], 'complete region text slots differ'
    for part in text:assert not part.attrib and part.text is None and part.tail is None
    schema=compiled_schema()
    assert schema.validate(etree.fromstring(content)), str(schema.error_log.last_error)
    return source


def complete_check(manifest,candidate):
    assert len(manifest.record['source_members'])==1
    logical=manifest.record['source_members'][0]['path'];raw=manifest.authority_path('retained-source').read_bytes()
    member=manifest.record['source_members'][0]
    assert manifest.record['work_id']=='newman-parochial-sermons' and manifest.record['ticket_id']=='LIB-018'
    assert manifest.record['source_id']==Path(logical).stem+'-retained-electronic' and logical=='raw/gutenberg/sermons/newman/'+Path(logical).name
    assert member['bytes']==len(raw) and member['sha256']==digest(raw), 'declared Newman source member byte identity differs'
    binding=next(a for a in manifest.record['authorities'] if a['name']=='retained-source')
    assert binding['path']==logical and binding['role']=='primary-source', 'primary retained authority differs from declared member'
    source=check_document(raw,logical,candidate.member_bytes('content.tei.xml'))
    profile=json.loads(manifest.authority_path('profile').read_bytes());policy=json.loads(manifest.authority_path('policy').read_bytes())
    assert profile['source_path']==logical and profile['source_sha256']==source['source_sha256'] and profile['source_bytes']==len(raw)
    assert profile['volume']==source['volume'] and profile['sermons']==profile['contents_sermons']==18 and profile['note_definitions']==source['note_definitions']
    assert source['exceptions']==policy['literal_source_exceptions']
    expected_provenance=dict(contract='ocd-newman-parochial-pg-provenance-v1',work_id='newman-parochial-sermons',textual_form_id='newman-parochial-gutenberg-english',edition_id='newman-parochial-sermons-pg-'+('07' if source['volume']=='VII' else '08')+'-retained-electronic',source_path=logical,source_sha256=source['source_sha256'],candidate_status='nonaccepted',supported_scope='Complete exact retained PG electronic volume '+source['volume']+' only; not the complete eight-volume work or a collated print edition.',human_review='not-recorded',rights='not-assessed-for-publication')
    assert policy['provenance']==expected_provenance
    expected_unresolved=[dict(id=Path(logical).stem+'-source-exception-'+str(i+1),status='literal-source-exception-preserved',scope=record) for i,record in enumerate(source['exceptions'])]
    expected_unresolved.append(dict(id=Path(logical).stem+'-scope-boundaries',status='unassessed-stronger-claims',items=['Six IA OCR volumes I-VI excluded from this retained born-digital reconstruction.','No complete eight-volume or unified 1868 print-edition claim.','1891 title-page fields are source assertions; print collation and human acceptance are unrecorded.','Provider permission text is retained; jurisdictional rights and publication remain unassessed.']))
    assert policy['unresolved']==expected_unresolved
    account=json.loads(candidate.member_bytes('source-accountability.json'))
    expected={k:source[k] for k in ('source_path','source_sha256','source_bytes','volume','book_start','book_stop','note_definitions','exceptions')}
    expected.update(contract='ocd-newman-parochial-pg-accountability-v1',content_sha256=digest(candidate.member_bytes('content.tei.xml')),carriers=source['carriers'],encoding_dispositions={'utf8_bom':raw.startswith(b'\xef\xbb\xbf'),'crlf_to_lf':raw.count(b'\r\n')},sermons=18,contents_sermons=18,complete_eight_volume_claim=False,provider_administration_disposition='Complete literal opening/start marker and end marker/footer are delivered in README.source.md; excluded from book projection.')
    assert account==expected and candidate.member_bytes('source-accountability.json')==canonical(expected)
    readme=candidate.member_bytes('README.source.md');assert readme==manifest.authority_path('source-readme').read_bytes()
    assert source['text'][:source['book_start']].encode() in readme and source['text'][source['book_stop']:].encode() in readme
    assert candidate.member_bytes('provenance.json')==canonical(policy['provenance'])
    assert candidate.member_bytes('unresolved.jsonl')==b''.join(canonical(x) for x in policy['unresolved'])
    return dict(complete_source_book_and_header=True,complete_carrier_and_inline_semantics=True,source_carriers=len(source['carriers']),sermons=18,note_definitions=source['note_definitions'],literal_source_exceptions=source['exceptions'])


def closure(root):
    paths=['build/tei/newman_parochial_pg_oracle.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/reconstruction/verifier.py','ocd_kernel/lib/path_io.py','ocd_kernel/lib/storage_topology.py','ocd_kernel/tei/validate.py']
    return digest(canonical([dict(path=p,sha256=digest((root/p).read_bytes())) for p in paths]))


def _oracle(manifest,candidate):
    complete_check(manifest,candidate);bound=closure(manifest.repository_root)
    assert bound==manifest.record['validator']['import_closure_sha256']
    facts=MechanicalFacts(validator_implementation_sha256=digest(Path(__file__).read_bytes()),validator_import_closure_sha256=bound,source_sha256=digest(manifest.authority_path('retained-source').read_bytes()),profile_sha256=digest(manifest.authority_path('profile').read_bytes()),package_schema_sha256=digest(manifest.authority_path('candidate-package-schema').read_bytes()),xsd_sha256=digest(manifest.authority_path('tei-p5-xsd').read_bytes()),policy_sha256=digest(manifest.authority_path('policy').read_bytes()),findings=())
    return verify_mechanical_facts(manifest,candidate,facts).as_record()


_oracle.oracle_id='ocd-newman-parochial-pg-complete-source-oracle-v1'
_oracle.oracle_version='1'
_oracle.implementation_path=Path(__file__).resolve()
