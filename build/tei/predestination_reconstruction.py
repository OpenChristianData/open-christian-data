"""Use proven ThML mapping for the entire source-defined two-book work."""
from hashlib import sha256
import json
from pathlib import Path
from build.tei import npnf105_reconstruction as mapper
from lxml import etree
from ocd_kernel.tei.writer import stamp_header, tei_el
CONVERTER_ID='ocd-predestination-two-book-to-tei'
CONVERTER_VERSION='1'
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def _convert(manifest):
    manifest.verify()
    profile=json.loads(manifest.authority_path('reconstruction-profile').read_bytes())
    if profile['work_id']!='augustine-predestination-of-saints' or profile['div1_id']!='xxi':raise ValueError('wrong complete work')
    tree=mapper._parse(manifest.authority_path('retained-thml'));divs=mapper._source_divisions(tree);selected=divs[20]
    if sha256(manifest.authority_path('retained-thml').read_bytes()).hexdigest()!=mapper.SOURCE_SHA256 or sha256(etree.tostring(selected,method='c14n')).hexdigest()!=profile['source_div1_c14n_sha256']:raise ValueError('exact retained work changed')
    document=tei_el('TEI',{'xml:id':f"npnf105-{profile['work_id']}-electronic"})
    document.append(stamp_header(title=profile['source_title'],author='Augustine of Hippo',contributors=[dict(name='Philip Schaff',role='retained volume editor'),dict(name='Robert Ernest Wallis',role='retained source translator'),dict(name='Benjamin B. Warfield',role='translation reviser and introduction author')],source_url='https://www.ccel.org/ccel/schaff/npnf105.xml',source_sha256=mapper.SOURCE_SHA256,print_source='New York: Christian Literature Publishing Co., 1886 (retained title page; no print collation).',rights_statement='Retained header states Public Domain. CCEL permits ThML parsing; do not sell CCEL files or derivatives of its formatting. Publication rights require separate review.'))
    body=tei_el('body',{'xml:id':f"npnf105-{profile['work_id']}-body"})
    mapped=[{} for _ in range(profile['feature_offset'])]
    mapper._append_source_node(selected,body,mapped,None)
    text=tei_el('text');text.append(body);document.append(text)
    accounting=dict(contract='ocd-npnf105-work-accounting-v1',work_id=profile['work_id'],source_path='raw/ccel/npnf1/npnf105.xml',source_sha256=mapper.SOURCE_SHA256,div1_id='xxi',source_title=profile['source_title'],feature_offset=profile['feature_offset'],feature_count=profile['feature_count'],source_div1_c14n_sha256=profile['source_div1_c14n_sha256'],tei_div_c14n_sha256=sha256(etree.tostring(body[0],method='c14n')).hexdigest(),translator=profile['translator'],translator_evidence_id=profile['translator_evidence_id'],outside_scope='Volume front matter, shared contents, sibling works, and indexes remain in retained XML.')
    members={'content.tei.xml':etree.tostring(document,encoding='UTF-8',xml_declaration=True),'provenance.json':canonical(dict(contract='ocd-npnf105-work-provenance-v1',status='nonaccepted',work_id=profile['work_id'],edition_id=profile['edition_id'],acquisition_id=profile['acquisition_id'],div1_id='xxi',canonical_ir_written=False,publication='not-ready')),'unresolved.jsonl':canonical(dict(status='unresolved',item='Human/visual review, print equivalence, final rights and publication remain separate.'))}
    rows=[]
    def walk(node,parent):
        if not isinstance(node.tag,str):return
        rows.append(dict(tag=node.tag,attributes=dict(node.attrib),text=node.text or '',tail=node.tail or '',parent=parent,children=[dict(kind='element' if isinstance(c.tag,str) else 'comment',tag=c.tag if isinstance(c.tag,str) else None,id=c.get('id') if isinstance(c.tag,str) else None,text=c.text or '',tail=c.tail or '') for c in node]))
        for child in node:walk(child,node.get('id'))
    walk(selected,None)
    accounting.update(literal_source_nodes=rows,scope=profile['scope'],boundary=profile['boundary'],source_envelope=dict(root_attributes=dict(tree.getroot().attrib),header='Retained ThML.head is volume metadata/support, not this work body.',body_divisions=[dict(position=i,id=d.get('id'),title=d.get('title'),elements=sum(isinstance(n.tag,str) for n in d.iter()),comments=sum(not isinstance(n.tag,str) for n in d.iter()),disposition='complete-selected-work' if d.get('id')=='xxi' else 'retained-outside-work',c14n_sha256=sha256(mapper.etree.tostring(d,method='c14n')).hexdigest()) for i,d in enumerate(divs,1)]))
    members['source-accountability.json']=canonical(accounting)
    members['README.source.md']=manifest.authority_path('source-readme').read_bytes()
    return members
_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION
_convert.implementation_path=Path(__file__).resolve()
