"""Literal retained HCC2 inline carriers exercise the closed generic ledger route."""
from copy import deepcopy
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
from lxml import etree
from ocd_kernel.library._common import PipelineError, io_path, io_glob
from ocd_kernel.projection.source_projection_evidence import project_evidence, observe_evidence
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from tests.test_schaff_native_source_evidence import fixture, NS, XML, CONTEXT

ROOT=Path(__file__).resolve().parents[1]
CANDIDATE=Path('D:/Library/Open Christian Data/candidate-reviews/schaff-history-vol2-current-20261001-v1/package/content.tei.xml')
def source_fixture():
    parser=etree.XMLParser(load_dtd=False,resolve_entities=False,no_network=True,huge_tree=True)
    source=etree.fromstring(io_path(ROOT/'raw/ccel/schaff/hcc2.xml').read_bytes(),parser)
    candidate=etree.fromstring(CANDIDATE.read_bytes(),parser)
    all_records=[json.loads(n.text) for n in candidate.find(NS+'standOff/'+NS+'list')]
    by_id={n.get(XML+'id'):n for n in candidate.iter() if n.get(XML+'id')}
    doc=fixture();paragraph=doc.find('.//'+NS+'p[@xml:id="p"]',namespaces={'xml':XML[1:-1]});ledger=doc.find(NS+'standOff/'+NS+'list')
    selected=[source.find('.//b'),source.find('.//sup'),source.find('.//unclear'),next(n for n in source.iter('unclear') if n.find('br') is not None)]
    keys={n:f'hcc2-n{i:06d}' for i,n in enumerate(source.iter(),1)}
    top=[]
    for ordinal,original in enumerate(selected,2):
        source_key=keys[original];identifier=original.get('id') or 'hcc2-generated-'+source_key[6:]
        mapped=deepcopy(by_id[identifier]);paragraph.append(mapped);top.append(mapped)
        first_record=next(r for r in all_records if r['source_key']==source_key)
        descendants={first_record['source_key']};records=[]
        for r in all_records:
            if r['source_key'] in descendants or r['source_parent_key'] in descendants:
                records.append(deepcopy(r));descendants.add(r['source_key'])
        assert len(records)==sum(1 for _ in original.iter())
        records[0]['source_parent_key']='p';records[0]['source_ordinal']=ordinal
        for record in records:
            identifier=dict(record['source_attributes']).get('id') or 'hcc2-generated-'+record['source_key'][6:];item=etree.SubElement(ledger,NS+'item',n=record['source_key'],corresp='#'+identifier);item.text=json.dumps(record)
        assert ''.join(mapped.itertext())==''.join(original.itertext())
    return doc,top

def test_literal_source_inline_carriers_have_public_content_and_exact_private_evidence(tmp_path):
    doc,top=source_fixture();path=tmp_path/'master.xml';path.write_bytes(etree.tostring(doc,encoding='utf-8',xml_declaration=True))
    assert [etree.QName(n).localname for n in top]==['hi','hi','unclear','unclear']
    assert [top[i].get('rend') for i in (0,1)]==['bold','superscript']
    project_evidence(ET.fromstring(path.read_bytes()));observe_evidence(doc)
    result=project_document(path,**CONTEXT)
    assert verify_document(path,result['rows'],result['receipt'],**CONTEXT)==[]
    assert 'Satornilos' in result['rows'][0]['text']
    assert next(top[2].iter(NS+'note')).get('n')=='906'
    assert len(list(top[3].iter(NS+'lb')))==1

def test_actual_volume1_legacy_carriers_keep_full_source_fidelity_and_projection_grammar():
    from build.tei import schaff_history_vol_1_oracle as oracle
    master=next(io_glob(ROOT/'library/works/schaff-history-vol-1','**/master.tei.xml'))
    raw=io_path(master).read_bytes();doc=oracle._parse_xml(raw,'current accepted volume I').getroot()
    source=oracle._parse_xml(io_path(ROOT/'raw/ccel/schaff/hcc1.xml').read_bytes(),'retained source').getroot()
    _,records=oracle._source_records(source)
    original=next(io_glob(ROOT/'library/works/schaff-history-vol-1','**/original-package/content.tei.xml'))
    original_bytes=io_path(original).read_bytes();original_doc=oracle._parse_xml(original_bytes,'source-checked original').getroot()
    oracle._verify_source_projection(source,original_doc,records)
    # Promoted identity metadata adds synthetic header IDs. Compare the unchanged native
    # body/ledger bytes and retained source-header subtree, then validate the actual master normally.
    assert raw.split(b'</teiHeader>',1)[1]==original_bytes.split(b'</teiHeader>',1)[1]
    header_path=NS+'teiHeader/'+NS+'fileDesc/'+NS+'notesStmt/'+NS+'note[@type="retained-ThML-header"]/'+NS+'p/'+NS+'seg'
    assert etree.tostring(doc.find(header_path))==etree.tostring(original_doc.find(header_path))
    assert len(doc.xpath('.//t:seg[@type="ThML-b"]',namespaces={'t':NS[1:-1]}))==9
    assert len(doc.xpath('.//t:seg[@type="ThML-unclear"]',namespaces={'t':NS[1:-1]}))==3
    assert len(source.xpath('ThML.head//b | ThML.head//unclear'))==0
    project_evidence(ET.fromstring(raw));observe_evidence(doc)
    from ocd_kernel.library.identities import cached_edition_lookups
    from ocd_kernel.projection.categories.native_documents import project_accepted_document,verify_accepted_document
    accepted=master.parent/'acceptance.json'
    with cached_edition_lookups():
        result=project_accepted_document(ROOT,acceptance_path=accepted,category='prose')
        assert len(result['rows'])==2
        assert verify_accepted_document(ROOT,acceptance_path=accepted,rows=result['rows'],receipt=result['receipt'],category='prose')==[]

@pytest.mark.parametrize('kind',['wrong-type','extra-attr','class-change'])
def test_exact_legacy_inline_exception_rejects_changed_attributes(kind):
    doc,top=source_fixture();top[0].tag=NS+'seg';top[0].attrib.pop('rend');top[0].set('type','ThML-b')
    project_evidence(ET.fromstring(etree.tostring(doc)));observe_evidence(doc)
    if kind=='wrong-type':top[0].set('type','ThML-invented')
    elif kind=='extra-attr':top[0].set('n','invented')
    else:top[0].set('rend','invented')
    with pytest.raises(PipelineError,match='legacy inline attributes'):project_evidence(ET.fromstring(etree.tostring(doc)))
    with pytest.raises(ValueError,match='legacy inline attributes'):observe_evidence(doc)

@pytest.mark.parametrize('index',[0,1,2])
def test_wrong_target_tag_is_rejected_by_both_routes(index):
    doc,top=source_fixture();top[index].tag=NS+'seg'
    with pytest.raises(PipelineError,match='mapped target tag|legacy inline attributes'):project_evidence(ET.fromstring(etree.tostring(doc)))
    with pytest.raises(ValueError,match='mapped target tag|legacy inline attributes'):observe_evidence(doc)

@pytest.mark.parametrize('kind',['unclear-note-parent','unclear-break'])
def test_source_child_attachment_and_break_are_not_lost(kind):
    doc,top=source_fixture()
    node=next(top[2].iter(NS+'note')) if kind=='unclear-note-parent' else next(top[3].iter(NS+'lb'))
    if kind=='unclear-note-parent':top[3].append(node)
    else:node.getparent().remove(node)
    with pytest.raises(PipelineError,match='child attachment/order|target differs'):project_evidence(ET.fromstring(etree.tostring(doc)))
    with pytest.raises(ValueError,match='child attachment/order|target differs'):observe_evidence(doc)

@pytest.mark.parametrize('kind',['style','language','wording','tail','private-source-attribute'])
def test_saved_projection_rejects_literal_semantic_and_ledger_mutations(tmp_path,kind):
    doc,top=source_fixture();path=tmp_path/'master.xml';path.write_bytes(etree.tostring(doc,encoding='utf-8',xml_declaration=True));result=project_document(path,**CONTEXT)
    if kind=='style':top[0].set('rend','italic')
    elif kind=='language':next(n for n in top[2].iter() if n.get(XML+'lang')).set(XML+'lang','invented')
    elif kind=='wording':top[2].text='Corrected reading'
    elif kind=='tail':top[2].tail='Changed tail'
    else:
        item=doc.find(NS+'standOff/'+NS+'list')[-1];record=json.loads(item.text);record['source_attributes'].append(['invented','yes']);item.text=json.dumps(record)
    path.write_bytes(etree.tostring(doc,encoding='utf-8',xml_declaration=True))
    assert verify_document(path,result['rows'],result['receipt'],**CONTEXT)
