"""Independent full mapped-tree oracle plus stdlib source boundary corroboration."""
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from lxml import etree
from build.tei import npnf205_work_oracle as checker
ORACLE_ID='ocd-nyssa-letters-collection-source-oracle'
ORACLE_VERSION='1'
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def _oracle(manifest,candidate):
    report=checker._oracle(manifest,candidate)
    raw=manifest.authority_path('retained-thml').read_bytes();source=ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    body=source.find('ThML.body');selected=[n for n in body if n.get('id')=='xiii']
    if len(body)!=16 or len(selected)!=1:raise ValueError('literal collection envelope differs')
    selected=selected[0]
    if len(selected)!=19 or selected[0].get('id')!='xiii.i' or len([n for n in selected if n.get('type')=='Letter'])!=18:raise ValueError('complete eighteen-letter collection differs')
    profile=json.loads(manifest.authority_path('reconstruction-profile').read_bytes());accounting=json.loads(candidate.member_bytes('source-accountability.json'));expected=[]
    def walk(n,parent):
        expected.append(dict(tag=n.tag,attributes=dict(n.attrib),text=n.text or '',tail=n.tail or '',parent=parent,children=[c.get('id') for c in n]))
        for c in n:walk(c,n.get('id'))
    walk(selected,None)
    if expected!=accounting['literal_source_nodes']:raise ValueError('original attrs/text/tails/hierarchy ledger differs')
    if accounting['boundary']!=profile['boundary']:raise ValueError('boundary accounting differs')
    for id,literal in profile['boundary']['context_literals'].items():
        nodes=[n for n in source.iter() if n.get('id')==id]
        if len(nodes)!=1 or ''.join(nodes[0].itertext())!=literal:raise ValueError('literal context differs: '+id)
    intro=selected[1][1]
    if intro.get('id')!='xiii.ii-p1' or 'Harman Chaloner Ogle' not in ''.join(intro.itertext()) or 'first fourteen' not in ''.join(intro.itertext()):raise ValueError('translator introduction location/scope differs')
    lx=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,remove_comments=False));envelope=[dict(position=i,tag=n.tag,id=n.get('id'),title=n.get('title'),elements=len(list(n.iter())),c14n_sha256=sha256(etree.tostring(n,method='c14n')).hexdigest(),disposition='complete-selected-collection' if n.get('id')=='xiii' else 'retained-outside-work') for i,n in enumerate(lx.find('ThML.body'),1) if isinstance(n.tag,str)]
    if envelope!=accounting['source_envelope']:raise ValueError('complete retained envelope dispositions differ')
    if candidate.member_bytes('README.source.md')!=manifest.authority_path('source-readme').read_bytes():raise ValueError('source/data credit binding differs')
    report.update(oracle_id=ORACLE_ID,oracle_version='1',implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest());report.pop('result_sha256');report['result_sha256']=sha256(canonical(report)).hexdigest();return report
_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version='1'
_oracle.implementation_path=Path(__file__).resolve()
