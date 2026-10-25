"""Full independent ThML comparison, plus independently traversed literal ledger."""
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from lxml import etree
from build.tei import npnf105_work_oracle as checker
ORACLE_ID='ocd-predestination-two-book-source-oracle'
ORACLE_VERSION='1'
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def _oracle(manifest,candidate):
    report=checker._oracle(manifest,candidate)
    raw=manifest.authority_path('retained-thml').read_bytes()
    root=ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    divs=[d for d in root.find('ThML.body') if d.tag=='div1'];selected=[d for d in divs if d.get('id')=='xxi']
    if len(selected)!=1:raise ValueError('complete source selector mismatch')
    selected=selected[0]
    if [d.get('id') for d in selected]!=['xxi.i','xxi.ii','xxi.iii']:raise ValueError('two-book boundary mismatch')
    if [len(list(d.iter('div3'))) for d in selected]!=[0,43,70]:raise ValueError('complete section count mismatch')
    if [sum(n.get('type')=='Chapter' for n in d.iter('div3')) for d in selected]!=[0,43,68]:raise ValueError('complete native chapter count mismatch')
    openings=[''.join(d.itertext()) for d in selected]
    if 'This Treatise is the first portion of a work' not in openings[1] or 'Being the Second Book' not in openings[2] or 'On the Predestination of the Saints.' not in openings[2]:raise ValueError('native book identity mismatch')
    profile=json.loads(manifest.authority_path('reconstruction-profile').read_bytes());accounting=json.loads(candidate.member_bytes('source-accountability.json'))
    expected=[]
    def walk(node,parent):
        if not isinstance(node.tag,str):return
        expected.append(dict(tag=node.tag,attributes=dict(node.attrib),text=node.text or '',tail=node.tail or '',parent=parent,children=[dict(kind='element' if isinstance(c.tag,str) else 'comment',tag=c.tag if isinstance(c.tag,str) else None,id=c.get('id') if isinstance(c.tag,str) else None,text=c.text or '',tail=c.tail or '') for c in node]))
        for child in node:walk(child,node.get('id'))
    walk(selected,None)
    if accounting['literal_source_nodes']!=expected:raise ValueError('literal original attributes/text/tails/hierarchy ledger mismatch')
    if accounting['boundary']!=profile['boundary'] or accounting['scope']!=profile['scope']:raise ValueError('declared boundary accounting mismatch')
    for id,literal in profile['boundary']['context_literals'].items():
        nodes=[e for e in root.iter() if e.get('id')==id]
        if len(nodes)!=1 or ''.join(nodes[0].itertext())!=literal:raise ValueError('literal context mismatch: '+id)
    if 'One Book' not in profile['boundary']['context_literals']['iii-p70']:raise ValueError('outside contents discrepancy missing')
    # Source parser diversity corroborates whole selected tree, including comments.
    lx=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,remove_comments=False))
    ld=lx.find('ThML.body');envelope=accounting['source_envelope']
    expected_divs=[dict(position=i,id=d.get('id'),title=d.get('title'),elements=sum(isinstance(n.tag,str) for n in d.iter()),comments=sum(not isinstance(n.tag,str) for n in d.iter()),disposition='complete-selected-work' if d.get('id')=='xxi' else 'retained-outside-work',c14n_sha256=sha256(etree.tostring(d,method='c14n')).hexdigest()) for i,d in enumerate([e for e in ld if e.tag=='div1'],1)]
    if envelope['body_divisions']!=expected_divs or envelope['root_attributes']!=dict(root.attrib):raise ValueError('whole envelope disposition mismatch')
    if candidate.member_bytes('README.source.md')!=manifest.authority_path('source-readme').read_bytes():raise ValueError('source credits mismatch')
    report.update(oracle_id=ORACLE_ID,oracle_version='1',implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest())
    report.pop('result_sha256');report['result_sha256']=sha256(canonical(report)).hexdigest()
    return report
_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version='1'
