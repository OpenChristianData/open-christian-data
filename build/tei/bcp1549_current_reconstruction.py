"""Source-native retained BCP1549 HTML reconstruction; no source-specific1662 reuse."""
from hashlib import sha256
import json
import re
from pathlib import Path
from urllib.parse import quote,urljoin
from lxml import etree,html
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

NS='http://www.tei-c.org/ns/1.0'
XML_ID='{http://www.w3.org/XML/1998/namespace}id'
ROOT=Path(__file__).resolve().parents[2]
CONVERTER_ID='ocd-bcp1549-complete-native-html-current-v1'
CONVERTER_VERSION='1'
READING_ORDER=(
 'BCP_1549.htm','BCP_1549&52_Intro.htm','front_matter_1549.htm','Kalendar_1549.htm',
 'Matins_1549.htm','Evensong_1549.htm','collects_epistles_gospels_1549.htm',
 'Readings_Advent_1549.htm','Readings_Xmas_1549.htm','Readings_Epiphany_1549.htm',
 'Readings_Lent_1549.htm','Readings_HolyWeek_1549.htm','Reading_EasterWeek_1549.htm',
 'Readings_EasterSeason_1549.htm','Readings_Ascension&Whitsuntide_1549.htm',
 'Readings_TrinityA_1549.htm','Readings_TrinityB_1549.htm','Readings_TrinityC_1549.htm',
 'Readings_SaintsA_1549.htm','Readings_SaintsB_1549.htm','Communion_1549.htm','Litany_1549.htm',
 'Baptism_1549.htm','Confirmation_1549.htm','Marriage_1549.htm','Visitation_Sick_1549.htm',
 'Burial_1549.htm','Purification_Women_1549.htm','Ashwednesday_1549.htm','Of_Ceremonies_1549.htm',
 'Ordinal_1549.htm','Bishops_1549.htm','Priests_1549.htm','Deacons_1549.htm')
BLOCKS={'p','div','table','tr','td','ul','li','blockquote','center','h2'}
INLINE={'font','span','i','em','b','strong','big','small','sup','a'}
TAGS=BLOCKS|INLINE|{'body','br','hr','img','map','area'}
ROLES={'Priest.','Prieste.','Aunswere.','Answer.','Minister.','People.','Bishop.','Bisshop.','Deacon.','The Priest.','The People.'}

def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def node(tag,**attrs):return etree.Element('{'+NS+'}'+tag,attrib=attrs)
def annotation(source):
    fields=dict(tag=source.tag if isinstance(source.tag,str) else '#comment',attributes=list(source.attrib.items()))
    if not isinstance(source.tag,str):fields['comment']=source.text
    return 'urn:ocd:bcp1549:html:'+quote(json.dumps(fields,ensure_ascii=False,separators=(',',':')),safe='')

def decoded_html(raw):
    """Decode only the two C1 numeric references actually present in this source.

    Original bytes remain authority. The ledger binds lexemes and byte offsets;
    this is HTML's defined visible decoding, not a spelling/editorial change.
    """
    ledger=[]
    def replace(match):
        value=int(match[1],16) if match[1] else int(match[2])
        if not 128<=value<=159:return match[0]
        if match[0] not in (b'&#149;',b'&#151;'):
            raise ValueError('Undeclared C1 numeric source reference')
        mapped={149:8226,151:8212}[value]
        ledger.append(dict(byte_start=match.start(),byte_end=match.end(),lexeme=match[0].decode(),source_codepoint=value,visible_codepoint=mapped,visible_text=chr(mapped)))
        return ('&#'+str(mapped)+';').encode()
    return re.sub(rb'&#(?:[xX]([0-9A-Fa-f]+)|([0-9]+));?',replace,raw),ledger

def header():
    h=node('teiHeader');f=etree.SubElement(h,'{'+NS+'}fileDesc')
    t=etree.SubElement(f,'{'+NS+'}titleStmt');etree.SubElement(t,'{'+NS+'}title').text='The Book of Common Prayer (1549): complete retained electronic expression'
    p=etree.SubElement(f,'{'+NS+'}publicationStmt');etree.SubElement(p,'{'+NS+'}p').text='Technical retained-source reconstruction. Human acceptance, print collation, electronic transcription rights and public publication remain unassessed.'
    s=etree.SubElement(f,'{'+NS+'}sourceDesc');b=etree.SubElement(s,'{'+NS+'}bibl')
    etree.SubElement(b,'{'+NS+'}ptr',target='http://justus.anglican.org/resources/bcp/1549/')
    etree.SubElement(b,'{'+NS+'}note',type='retained-electronic-scope').text='All 34 acquired HTML members; shared 1549/1552 introduction, shared 1549/1552/1559 readings, 1550 Ordinal and comparative columns remain explicit electronic-edition context. Not a pure 1549 print witness. The two additional retained directory/PDF-technical HTML files are support evidence outside this acquired text member set.'
    etree.SubElement(b,'{'+NS+'}note',type='primary-source-contributors').text='Retained page footers state Web author: Charles Wohlers. The shared introduction is attributed to Edward C. S. Gibson, Bishop of Gloucester. The inherited Mammana transcription attribution is not corroborated by these retained pages; no transcriber identity is inferred.'
    etree.SubElement(b,'{'+NS+'}note',type='primary-source-print-claims').text='The overview describes a 1910 Everyman reprint and source modernizations/variants; probable original printing statements remain source claims. The technical notes concern a separate PDF/facsimile presentation. Linked PDF and image payloads are not retained here.'
    return h

def build_native(acquired):
    root=node('TEI');root.append(header());text=etree.SubElement(root,'{'+NS+'}text');body=etree.SubElement(text,'{'+NS+'}body')
    by_name={Path(m['path']).name:(i,m) for i,m in enumerate(acquired['retained_files'],1)}
    if set(by_name)!=set(READING_ORDER) or len(by_name)!=34:raise ValueError('Exact retained34 source scope differs')
    inventory=[];member_proofs=[]
    for position,name in enumerate(READING_ORDER,1):
        acquired_position,m=by_name[name];raw=io_path(ROOT/m['path']).read_bytes()
        if len(raw)!=m['bytes'] or sha256(raw).hexdigest()!=m['sha256']:raise ValueError('Source bytes differ: '+name)
        parsed_bytes,entity_ledger=decoded_html(raw)
        source=html.document_fromstring(parsed_bytes,parser=html.HTMLParser(encoding='windows-1252',remove_comments=False))
        src_body=source.find('body');serial=0
        def map_node(src,path):
            nonlocal serial
            if not isinstance(src.tag,str):
                serial+=1;xid='bcp1549-'+sha256(name.encode()).hexdigest()[:12]+'-'+str(serial)
                out=node('anchor',type='source-html-comment',rend=annotation(src));out.set(XML_ID,xid)
                inventory.append(dict(member=name,path=path,kind='comment',text=src.text,tail=src.tail,tei_id=xid,tei_tag='anchor',disposition='nonvisible-source-comment-annotation'))
                return out
            if src.tag not in TAGS:raise ValueError('Unknown source body tag: '+src.tag)
            serial+=1;xid='bcp1549-'+sha256(name.encode()).hexdigest()[:12]+'-'+str(serial)
            block_inline=src.tag in INLINE and any(c.tag in BLOCKS for c in src.iterdescendants())
            target={'body':'ab','table':'table','tr':'row','td':'cell','p':'ab','div':'ab','center':'ab','blockquote':'ab','ul':'list','li':'item','h2':'ab','br':'lb','hr':'milestone','img':'figure','map':'seg','area':'anchor'}.get(src.tag)
            if src.tag in INLINE:target='ab' if block_inline else 'hi' if src.tag in {'i','em','b','strong','big','small','sup'} else 'ref' if src.tag=='a' and src.get('href') is not None else 'seg'
            out=node(target);out.set(XML_ID,xid)
            if target=='anchor':out.set('rend',annotation(src))
            else:out.set('ana',annotation(src))
            if target=='seg':out.set('type','source-html-'+src.tag)
            if target=='ab':
                out.set('type','source-h2' if src.tag=='h2' else 'source-block')
                if src.tag!='h2':out.set('subtype','html-'+src.tag)
            if target=='hi':out.set('rend',{'i':'italic','em':'italic','b':'bold','strong':'bold','big':'large','small':'small','sup':'superscript'}[src.tag])
            if block_inline and src.tag in {'i','em','b','strong','big','small','sup'}:
                out.set('rend',{'i':'italic','em':'italic','b':'bold','strong':'bold','big':'large','small':'small','sup':'superscript'}[src.tag])
            if target=='ref' and src.get('href') is not None:out.set('target',urljoin(urljoin(acquired['url'],name),src.get('href')))
            if target=='milestone':out.set('unit','source-horizontal-rule')
            if target=='cell' and src.get('colspan') is not None:out.set('cols',src.get('colspan'))
            if target=='cell' and src.get('rowspan') is not None:out.set('rows',src.get('rowspan'))
            if src.tag in {'p','div'} and ' '.join(''.join(src.itertext()).split()) in ROLES:
                out.set('ana',out.get('ana')+' source-literal-role:'+quote(' '.join(''.join(src.itertext()).split()),safe=''))
            record=dict(member=name,path=path,kind='element',tag=src.tag,attributes=list(src.attrib.items()),text=src.text,tail=src.tail,
                tei_id=xid,tei_tag=target,block_inline=block_inline,disposition='represented')
            if src.get('href') is not None:
                record.update(literal_href=src.get('href'),source_member_url=urljoin(acquired['url'],name),resolved_source_url=urljoin(urljoin(acquired['url'],name),src.get('href')))
            inventory.append(record)
            if src.tag=='img':
                if src.text or len(src):raise ValueError('Source image has unexpected children')
                etree.SubElement(out,'{'+NS+'}graphic',url=src.get('src',''))
                if src.get('alt') is not None:etree.SubElement(out,'{'+NS+'}figDesc').text=src.get('alt')
                return out
            if src.tag in {'br','hr','area'}:
                if src.text or len(src):raise ValueError('Source void element has unexpected content')
                return out
            out.text=src.text
            for i,c in enumerate(src,1):
                mapped=map_node(c,path+[i])
                if mapped is not None:
                    if src.tag=='ul' and isinstance(c.tag,str) and c.tag!='li':
                        if (name,path+[i],c.tag)!=('Baptism_1549.htm',[5,2,10,1,7,1],'p'):
                            raise ValueError('Undeclared unlisted source child: '+name+' '+str(path+[i]))
                        wrapper=etree.SubElement(out,'{'+NS+'}item',ana='generated-unlisted-source-child')
                        wrapper.append(mapped);wrapper.tail=c.tail
                    else:out.append(mapped);mapped.tail=c.tail
                elif len(out):out[-1].tail=(out[-1].tail or '')+(c.tail or '')
                else:out.text=(out.text or '')+(c.tail or '')
            return out
        member=node('div',type='source-member',n=name)
        member.set(XML_ID,'bcp1549-member-'+sha256(name.encode()).hexdigest()[:12])
        body.append(member)
        etree.SubElement(member,'{'+NS+'}head').text=''.join(source.find('head/title').itertext())
        member.append(map_node(src_body,[]))
        member_proofs.append(dict(member=name,acquired_position=acquired_position,reading_position=position,
            source_member_url=urljoin(acquired['url'],name),
            source_sha256=m['sha256'],source_bytes=m['bytes'],source_header=etree.tostring(source.find('head'),encoding='unicode'),
            comment_count=sum(not isinstance(n.tag,str) for n in source.iter()),numeric_reference_decoding=entity_ledger,
            parser='lxml HTML recovery; declaredISO-8859-1 interpreted as HTML-standardWindows-1252; literal numeric C1 references decoded by the recorded HTML visible-character replacements'))
    return etree.tostring(root,encoding='utf-8',xml_declaration=True),dict(contract='ocd-bcp1549-native-source-accountability-v1',members=member_proofs,observations=inventory)

def _convert(manifest):
    manifest.verify()
    profile=json.loads(manifest.authority_path('profile').read_bytes())
    acquired=validate_acquisition(manifest.authority_path('canonical-acquisition'),root=manifest.repository_root)
    if acquired['source_sha256']!=profile['source_sha256']:
        raise ValueError('Current retained acquisition binding differs')
    raw,accounting=build_native(acquired)
    doc=etree.fromstring(raw);doc.replace(doc[0],etree.fromstring(profile['header_xml'].encode()))
    raw=etree.tostring(doc,encoding='utf-8',xml_declaration=True)
    return {'content.tei.xml':raw,'source-accountability.json':canonical(accounting),
        'provenance.json':canonical(dict(work_id='bcp-1549',source_manifest_sha256=manifest.sha256,scope=profile['scope'],status='nonaccepted')),
        'README.source.md':manifest.authority_path('source-readme').read_bytes(),
        'unresolved.jsonl':b''.join(canonical(q) for q in profile['questions'])}

_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION
_convert.implementation_path=Path(__file__).resolve()
