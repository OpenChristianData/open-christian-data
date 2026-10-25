"""Complete primary-source envelope observer for the retained engwmb successor.

Uses standard-library ElementTree and an independent token-event grammar.
Does not import the reconstruction producer or its inline parser.
"""
from pathlib import Path
from hashlib import sha256
from zipfile import ZipFile
from collections import Counter
from xml.etree import ElementTree as ET
import json,re
from lxml import etree
from ocd_kernel.reconstruction.verifier import MechanicalFacts,verify_mechanical_facts

T='{http://www.tei-c.org/ns/1.0}';X='{http://www.w3.org/XML/1998/namespace}'
HEADINGS={'h','toc1','toc2','toc3','mt1','mt2','mt3','s1','s2','s3','is1','is2','ms1','ms2'}
TOK=re.compile(r'\\(?P<tag>\+?[A-Za-z][A-Za-z0-9]*)(?P<close>\*)?')
FIELDS={'fr':('ref','source-label'),'xo':('ref','source-origin'),'ft':('seg','footnote-text'),'xt':('ref','source-target'),'fqa':('seg','alternate-reading'),'fq':('seg','quoted-reading')}
OPEN={'w':('w',{}),'+w':('w',{'type':'usfm-plus-w'}),'wj':('q',{'type':'words-of-Jesus'}),'+wh':('foreign',{X+'lang':'he'}),'qs':('seg',{'type':'selah'}),'bk':('title',{'type':'biblical-book'}),'k':('term',{})}

def _hash(b):return sha256(b).hexdigest()
def _canon(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def _append(node,value):
    if not value:return
    if len(node):node[-1].tail=(node[-1].tail or '')+value
    else:node.text=(node.text or '')+value

def _inline(value,pointer,counts):
    """Construct an expected subtree from lexical events, with exact text slots."""
    holder=ET.Element('holder');frames=[];field=None;caller=False;cursor=0
    for event in TOK.finditer(value):
        segment=value[cursor:event.start()]
        if field is not None:field[0].set('corresp',pointer+'&span='+str(field[1])+':'+str(event.start()))
        if caller:
            mark=re.match(r'^(\s*)\+(\s*)',segment)
            if mark:
                scope=next(frame[1] for frame in reversed(frames) if frame[0] in {'f','x'})
                _append(scope,mark[1]);label=ET.SubElement(scope,T+'label',{'type':'caller'});label.text='+';_append(scope,mark[2]);segment=segment[mark.end():]
            caller=False
        target=field[0] if field is not None else frames[-1][1] if frames else holder
        _append(target,segment);field=None
        tag=event['tag'];end=bool(event['close']);counts[tag+('*' if end else '')]+=1
        parent=frames[-1][1] if frames else holder
        if end:
            assert frames and frames[-1][0]==tag,'source scope closing token'
            _,node,start=frames.pop();node.set('corresp',pointer+'&span='+str(start)+':'+str(event.end()))
            if tag in {'w','+w'}:
                raw=node.text or '';word=re.fullmatch(r'(.*?)(?:\|strong="([^"]+)")?',raw,re.S);assert word is not None
                node.text=word[1]
                if word[2]:node.set('n',word[2])
                whitespace=re.match(r'^\s+',node.text or '')
                if whitespace:
                    # Word's leading separator belongs to its parent's preceding slot.
                    owner=frames[-1][1] if frames else holder;index=list(owner).index(node)
                    if index:owner[index-1].tail=(owner[index-1].tail or '')+whitespace[0]
                    else:owner.text=(owner.text or '')+whitespace[0]
                    node.text=node.text[whitespace.end():]
        elif tag in {'f','x'}:
            node=ET.SubElement(parent,T+'note',{'type':'footnote' if tag=='f' else 'cross-reference'});frames.append((tag,node,event.start()));caller=True
        elif tag in FIELDS:
            name,kind=FIELDS[tag];node=ET.SubElement(parent,T+name,{'type':kind});field=(node,event.start())
        else:
            assert tag in OPEN,'unsupported source inline marker '+tag
            name,attrs=OPEN[tag];node=ET.SubElement(parent,T+name,attrs);frames.append((tag,node,event.start()))
        cursor=event.end()
    remainder=value[cursor:]
    if caller:
        mark=re.match(r'^(\s*)\+(\s*)',remainder)
        if mark:
            scope=next(frame[1] for frame in reversed(frames) if frame[0] in {'f','x'});_append(scope,mark[1]);label=ET.SubElement(scope,T+'label',{'type':'caller'});label.text='+';_append(scope,mark[2]);remainder=remainder[mark.end():]
    _append(field[0] if field is not None else frames[-1][1] if frames else holder,remainder)
    if field is not None:field[0].set('corresp',pointer+'&span='+str(field[1])+':'+str(len(value)))
    assert not frames,'source scope is left open'
    return holder

def _slots(root):
    # Start/end events include every expanded name, attribute, text and tail.
    todo=[(root,False)]
    while todo:
        node,end=todo.pop()
        if end:yield ('end',node.tail or '');continue
        yield ('start',node.tag,tuple(sorted(node.attrib.items())),node.text or '')
        todo.append((node,True));todo.extend((child,False) for child in reversed(list(node)))

def _equal(left,right,context):
    sentinel=object();a=iter(_slots(left));b=iter(_slots(right));ordinal=0
    while True:
        one=next(a,sentinel);two=next(b,sentinel)
        if one is sentinel and two is sentinel:return
        assert one==two,(context,ordinal,one,two)
        ordinal+=1

def _expected(manifest,semantic):
    profile=json.loads(manifest.authority_path('edition-profile').read_bytes());receipt=json.loads(manifest.authority_path('acquisition-receipt').read_bytes());work='engwmb'
    root=ET.Element(T+'TEI',{X+'id':work,'ana':'#nonaccepted-candidate'});header=ET.SubElement(root,T+'teiHeader');fd=ET.SubElement(header,T+'fileDesc');ts=ET.SubElement(fd,T+'titleStmt');ET.SubElement(ts,T+'title').text=profile['title'];pub=ET.SubElement(fd,T+'publicationStmt');ET.SubElement(pub,T+'p').text='Nonaccepted source-to-TEI candidate; human acceptance, rights review, and publication remain open.';sd=ET.SubElement(fd,T+'sourceDesc');ET.SubElement(sd,T+'p').text=f"Exact retained eBible USFM package raw/ebible/engwmb/usfm/engwmb_usfm.zip (sha256:{receipt['package']['sha256']}); source edition label from acquisition receipt: {receipt['edition']}."
    body=ET.SubElement(ET.SubElement(root,T+'text'),T+'body');counts=Counter();moves=[];archive_rows=[];line_rows=[];dispositions=[];inline=Counter()
    raw=manifest.authority_path('source-archive').read_bytes();assert _hash(raw)==profile['archive_sha256']==receipt['package']['sha256']
    rows=[line.split('\t') for line in manifest.authority_path('member-inventory').read_text(encoding='utf-8').splitlines()]
    with ZipFile(manifest.authority_path('source-archive')) as archive:
        assert archive.testzip() is None;assert len(archive.infolist())==len(rows)==69
        for position,(info,row) in enumerate(zip(archive.infolist(),rows,strict=True),1):
            payload=archive.read(info);assert (info.filename,len(payload),f'{info.CRC:08x}',_hash(payload))==(row[0],int(row[1]),row[2],row[3])
            archive_rows.append(dict(position=position,name=info.filename,bytes=len(payload),crc32=f'{info.CRC:08x}',sha256=_hash(payload)))
            match=re.fullmatch(r'\d{2,3}-([A-Z0-9]{3})[A-Za-z0-9-]*\.usfm',info.filename)
            if match is None:dispositions.append(dict(member=info.filename,disposition='retained-support-member',sha256=_hash(payload),bytes=len(payload)));continue
            assert manifest.authority_path('text-'+info.filename).read_bytes()==payload
            code=match[1];special=code in {'FRT','GLO'};book=ET.SubElement(body,T+'div',{'type':'front' if code=='FRT' else 'back' if code=='GLO' else 'book','n':code,X+'id':work+'-'+code});chapter=None
            lines=payload.decode('utf-8').splitlines()
            for number,line in enumerate(lines,1):
                if not line:marker=value=''
                else:
                    line_match=re.fullmatch(r'\\([A-Za-z0-9]+)(?: (.*))?',line,re.S);assert line_match is not None;marker=line_match[1];value=line_match[2] or ''
                counts[marker]+=1;pointer=f'source-usfm:{work}/{info.filename}#line={number}';target=None
                if marker=='c' and not special:
                    label,separator,extra=value.partition(' ');assert label.isdecimal();chapter=ET.SubElement(book,T+'div',{'type':'chapter','n':label,'corresp':pointer})
                    if separator:ET.SubElement(ET.SubElement(chapter,T+'p'),T+'seg',{'type':'usfm-c-content'}).text=extra
                elif marker=='v' and not special:
                    label,separator,wording=value.partition(' ');assert chapter is not None and separator;target=ET.SubElement(chapter,T+'ab',{'type':'verse','n':label,'corresp':pointer,X+'space':'preserve'});target.text=wording
                elif marker in HEADINGS:
                    wrapper=ET.SubElement(book,T+'div',{'type':'usfm-heading','n':marker+'-'+str(number)});target=ET.SubElement(wrapper,T+'head',{'type':'usfm-'+marker,'corresp':pointer});target.text=value
                else:
                    owner=chapter if chapter is not None and not special else ET.SubElement(book,T+'div',{'type':'usfm-line','n':str(number)})
                    if not marker:target=ET.SubElement(owner,T+'milestone',{'unit':'source-blank-line','corresp':pointer})
                    elif marker=='p' and not value:target=ET.SubElement(owner,T+'milestone',{'unit':'paragraph','corresp':pointer})
                    else:target=ET.SubElement(ET.SubElement(owner,T+'p'),T+'seg',{'type':'usfm-'+marker,'corresp':pointer});target.text=value
                if semantic and target is not None and target.text and '\\' in target.text:
                    expected=_inline(target.text,pointer,inline);target.text=expected.text
                    for child in list(expected):target.append(child)
                line_rows.append(dict(member=info.filename,line=number,marker=marker,raw_line_sha256=_hash(line.encode()),content_sha256=_hash(value.encode()),target=pointer))
            dispositions.append(dict(member=info.filename,disposition='mapped-to-tei-source-lines',sha256=_hash(payload),bytes=len(payload),line_count=len(lines)))
    assert archive_rows==profile['archive_entries']
    if semantic:
        # Scope and location are source-defined; the inverse record pins removed wrappers.
        for book in body:
            for wrapper in list(book):
                if wrapper.get('type')!='usfm-heading' or len(wrapper)!=1 or wrapper[0].get('type')!='usfm-ms1':continue
                head=wrapper[0];pointer=head.get('corresp');number=int(pointer.rsplit('=',1)[1]);filename=pointer.split('/',1)[1].split('#',1)[0];lines=manifest.authority_path('text-'+filename).read_text(encoding='utf-8').splitlines();label=next(line[3:].partition(' ')[0] for line in reversed(lines[:number-1]) if line.startswith('\\c '));chapter=next(c for c in book if c.get('type')=='chapter' and c.get('n')==label)
                moves.append(dict(pointer=pointer,chapter=label,wrapper_attributes=dict(wrapper.attrib),wrapper_index=list(book).index(wrapper)));book.remove(wrapper);chapter.insert(0,head)
    account=dict(contract='ocd-l225-usfm-accountability-v1',work_id=work,source_id='engwmb-usfm',archive_sha256=_hash(raw),member_inventory_sha256=receipt['verification']['member_inventory_sha256'],archive_member_count=69,archive_members=archive_rows,member_dispositions=dispositions,counts=dict(books=66,chapters=counts['c'],verses=counts['v'],source_lines=sum(counts.values())),marker_counts=dict(sorted(counts.items())),source_lines=line_rows)
    assert account['counts']==dict(books=66,chapters=1189,verses=31103,source_lines=60960)
    if semantic:account.update(inline_marker_counts=dict(sorted(inline.items())),source_heading_moves=moves);assert len(moves)==5
    return root,account

def check(manifest,candidate):
    manifest.verify();candidate.verify_integrity();assert manifest.record['work_id']=='engwmb'
    original=manifest.authority_path('previous-content').read_bytes();assert _hash(original)=='4af183d98a800c196648b38bb6108f1a8ffb401a43693787a1fe90337de2c5be'
    historical,old_account=_expected(manifest,False);_equal(historical,ET.fromstring(original),'complete original primary-source envelope')
    assert json.loads(manifest.authority_path('previous-source-accountability.json').read_bytes())==old_account
    del historical
    expected,account=_expected(manifest,True);_equal(expected,ET.fromstring(candidate.member_bytes('content.tei.xml')),'complete source-native envelope')
    assert json.loads(candidate.member_bytes('source-accountability.json'))==account
    for name in ['README.source.md','provenance.json','unresolved.jsonl']:assert candidate.member_bytes(name)==manifest.authority_path('previous-'+name).read_bytes()
    return dict(complete_header_body_attributes_text_tails=True,independent_standard_library_primary_source_tree=True,counts=account['counts'],inline_marker_counts=account['inline_marker_counts'],source_heading_moves=account['source_heading_moves'])

def _closure():
    root=Path(__file__).resolve().parents[2]
    return _hash(_canon({name:_hash((root/name).read_bytes()) for name in ['ocd_kernel/reconstruction/contract.py','ocd_kernel/reconstruction/verifier.py',str(Path(__file__).resolve().relative_to(root)).replace('\\','/')]}))

def _oracle(manifest,candidate):
    check(manifest,candidate)
    schema=etree.XMLSchema(etree.parse(str(manifest.authority_path('tei-p5-xsd'))));schema.assertValid(etree.fromstring(candidate.member_bytes('content.tei.xml'),etree.XMLParser(huge_tree=True,resolve_entities=False,no_network=True)))
    hashes={a['name']:a['sha256'] for a in manifest.record['authorities']}
    facts=MechanicalFacts(validator_implementation_sha256=_hash(Path(__file__).read_bytes()),validator_import_closure_sha256=_closure(),source_sha256=hashes['source-archive'],profile_sha256=hashes['edition-profile'],package_schema_sha256=hashes['candidate-package-schema'],xsd_sha256=hashes['tei-p5-xsd'],policy_sha256=hashes['edition-policy'],findings=())
    return verify_mechanical_facts(manifest,candidate,facts).as_record()
_oracle.oracle_id='ocd-l225-engwmb-complete-envelope-source-oracle'
_oracle.oracle_version='1'
_oracle.implementation_path=Path(__file__).resolve()
