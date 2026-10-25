"""Reuse the reviewed complete-root mapper; add source-bound collection evidence."""
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import npnf205_work_reconstruction as mapper
CONVERTER_ID='ocd-nyssa-letters-collection-to-tei'
CONVERTER_VERSION='1'
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def _convert(manifest):
    members=dict(mapper._convert(manifest));profile=json.loads(manifest.authority_path('reconstruction-profile').read_bytes());raw=manifest.authority_path('retained-thml').read_bytes()
    source=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,remove_comments=False));selected=source.xpath('//*[@id="xiii"]')[0]
    doc=etree.fromstring(members['content.tei.xml']);ns='{http://www.tei-c.org/ns/1.0}'
    bibliography=doc.find(ns+'teiHeader/'+ns+'fileDesc/'+ns+'sourceDesc/'+ns+'bibl')
    credit=etree.SubElement(bibliography,ns+'note');credit.text='Collection introduction xiii.ii-p1.2 credits Harman Chaloner Ogle for the first fourteen letters. Volume title page credits William Moore and Henry Austin Wilson as translators and Philip Schaff and Henry Wace as editors; no narrower allocation is inferred for the remaining four letters. Retained electronic header: Public Domain; New York: Christian Literature Publishing Co., 1892. Canonical edition title retains its separate 1893 statement.'
    members['content.tei.xml']=etree.tostring(doc,encoding='UTF-8',xml_declaration=True)
    accounting=json.loads(members['source-accountability.json']);ledger=[]
    def walk(n,parent):
        ledger.append(dict(tag=n.tag,attributes=dict(n.attrib),text=n.text or '',tail=n.tail or '',parent=parent,children=[c.get('id') for c in n]))
        for c in n:walk(c,n.get('id'))
    walk(selected,None)
    accounting.update(literal_source_nodes=ledger,boundary=profile['boundary'],source_envelope=[dict(position=i,tag=n.tag,id=n.get('id'),title=n.get('title'),elements=len(list(n.iter())),c14n_sha256=sha256(etree.tostring(n,method='c14n')).hexdigest(),disposition='complete-selected-collection' if n.get('id')=='xiii' else 'retained-outside-work') for i,n in enumerate(source.find('ThML.body'),1) if isinstance(n.tag,str)])
    members['source-accountability.json']=canonical(accounting);members['README.source.md']=manifest.authority_path('source-readme').read_bytes()
    return members
_convert.converter_id=CONVERTER_ID
_convert.converter_version='1'
_convert.implementation_path=Path(__file__).resolve()
