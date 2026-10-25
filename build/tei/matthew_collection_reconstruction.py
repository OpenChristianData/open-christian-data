"""Reuse the exact reviewed full Matthew collection body with a supported header."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import npnf_chrysostom_reconstruction as mapper
from ocd_kernel.tei.writer import tei_el

CONVERTER_ID='ocd-matthew-complete-collection-to-tei'
CONVERTER_VERSION='1'
def canonical(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
def _convert(manifest):
    manifest.verify()
    profile=json.loads(manifest.authority_path('reconstruction-profile').read_bytes())
    raw=manifest.authority_path('retained-thml').read_bytes()
    source=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,remove_comments=False))
    selected=source.xpath('/ThML/ThML.body/div1[@id="iii"]')[0]
    original=etree.fromstring(manifest.authority_path('historical-content').read_bytes())
    historic=original.xpath('//*[@xml:id="npnf110-iii"]',namespaces={'xml':'http://www.w3.org/XML/1998/namespace'})[0]
    doc=tei_el('TEI',{'xml:id':'chrysostom-matthew-complete-electronic'})
    text=tei_el('text');doc.append(text)
    body=tei_el('body',{'xml:id':'npnf-chrysostom-assigned-body'});text.append(body)
    rows=[]
    mapper._append(selected,body,rows,member='npnf110',work_id=profile['work_id'],parent_feature_id=None)
    if etree.tostring(body[0],method='c14n')!=etree.tostring(historic,method='c14n'):
        raise ValueError('Current mapping differs from full verified historical Matthew body')
    body.remove(body[0]);body.append(deepcopy(historic))
    header=tei_el('teiHeader');fd=tei_el('fileDesc');ts=tei_el('titleStmt')
    ts.append(tei_el('title',text=profile['title']))
    ts.append(tei_el('author',text=profile['author']))
    for c in profile['contributors']:
        resp=tei_el('respStmt');resp.append(tei_el('resp',text=c['role']));resp.append(tei_el('name',text=c['name']));ts.append(resp)
    fd.append(ts);pub=tei_el('publicationStmt');pub.append(tei_el('p',text=profile['rights_statement']));fd.append(pub)
    desc=tei_el('sourceDesc');bibl=tei_el('bibl')
    bibl.append(tei_el('title',text=profile['volume_title']))
    bibl.append(tei_el('idno',{'type':'source-url'},profile['source_url']))
    bibl.append(tei_el('idno',{'type':'sha256'},profile['source_sha256']))
    bibl.append(tei_el('note',text=profile['print_source']))
    bibl.append(tei_el('note',text=profile['scope']))
    desc.append(bibl);fd.append(desc);header.append(fd);doc.insert(0,header)
    ledger=[]
    def walk(n,parent):
        ledger.append(dict(tag=n.tag,attributes=dict(n.attrib),text=n.text or '',tail=n.tail or '',parent=parent,children=[c.get('id') for c in n]))
        for c in n:walk(c,n.get('id'))
    walk(selected,None)
    envelope=[dict(position=i,id=n.get('id'),tag=n.tag,title=n.get('title'),elements=sum(isinstance(c.tag,str) for c in n.iter()),c14n_sha256=sha256(etree.tostring(n,method='c14n')).hexdigest(),disposition='complete-selected-collection' if n.get('id')=='iii' else 'shared-volume-context-or-index-excluded') for i,n in enumerate(source.find('ThML.body'),1) if isinstance(n.tag,str)]
    shell=[dict(tag=n.tag,attributes=dict(n.attrib),text=n.text or '',tail=n.tail or '',c14n_sha256=sha256(etree.tostring(n,method='c14n')).hexdigest(),disposition='retained-outside-readable-work-body; header and source-evidence context') for n in source if isinstance(n.tag,str) and n.tag!='ThML.body']
    accounting=dict(contract='ocd-matthew-collection-accounting-v1',work_id=profile['work_id'],scope=profile['scope'],source_sha256=sha256(raw).hexdigest(),source_bytes=len(raw),source_root_id='iii',elements=len(rows),crosswalk=rows,literal_source_nodes=ledger,source_envelope=envelope,source_shell=shell,context_literals=profile['context_literals'],historical_body_c14n_sha256=sha256(etree.tostring(body[0],method='c14n')).hexdigest(),historical_source_review=profile['historical_review'],historical_review_limit='Dated structured visual sample only; no fresh full human or print review.')
    provenance=dict(contract='ocd-matthew-collection-provenance-v1',work_id=profile['work_id'],source_manifest_sha256=manifest.sha256,source_sha256=profile['source_sha256'],historical_content_sha256=sha256(manifest.authority_path('historical-content').read_bytes()).hexdigest(),unchanged_complete_historical_body=True,scope=profile['scope'])
    unresolved=[dict(claim=c,status='not-established') for c in ('human textual acceptance','fresh full visual review','print completeness/equivalence','independent rights clearance','publication')]
    return {'content.tei.xml':etree.tostring(doc,encoding='UTF-8',xml_declaration=True),'source-accountability.json':canonical(accounting),'provenance.json':canonical(provenance),'README.source.md':manifest.authority_path('source-readme').read_bytes(),'unresolved.jsonl':b''.join(canonical(r) for r in unresolved)}
_convert.converter_id=CONVERTER_ID
_convert.converter_version='1'
_convert.implementation_path=Path(__file__).resolve()
