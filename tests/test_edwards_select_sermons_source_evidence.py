"""Closed source-body semantics independently challenge the Select Sermons helper additions."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
from lxml import etree
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.source_projection_evidence import project_evidence,observe_evidence
from tests.test_schaff_native_source_evidence import fixture,NS,XML

CANDIDATE=Path('D:/Library/Open Christian Data/candidate-reviews/edwards-select-sermons-current-20261001-v2/package/content.tei.xml')
BODY_NAMES=('ol','blockquote','em','strong','img','hr','scripCom')

def row(identifier,tag,attributes,parent,ordinal):
    return dict(source_key=identifier,source_element=tag,source_attributes=list(attributes.items()),source_parent_key=parent,source_ordinal=ordinal)

def add_record(doc,record,index=None):
    listing=doc.find(NS+'standOff/'+NS+'list');item=etree.Element(NS+'item',n=record['source_key'],corresp='#'+dict(record['source_attributes'])['id']);item.text=json.dumps(record)
    if index is None:listing.append(item)
    else:listing.insert(index,item)

def body_fixture(tag,legacy=False):
    doc=fixture();parent=doc.find(NS+'text/'+NS+'body/'+NS+'div');original={'id':'new'};attrs={XML+'id':'new'}
    if tag=='ol':original.update(**{'class':'source-list','style':'list-style-type:upper-roman','lang':'en'});name='list';attrs.update(type='ordered',rend='source-list; list-style-type:upper-roman');attrs[XML+'lang']='en'
    elif tag=='blockquote':name='quote';original['class']='quotation';attrs['rend']='quotation'
    elif tag=='em':name='hi';original.update(**{'class':'literal-emphasis','lang':'gkc'});attrs.update(rend='literal-emphasis');attrs[XML+'lang']='gkc'
    elif tag=='strong':name='hi';attrs['rend']='bold'
    elif tag=='img':name='graphic';original.update(src='http://static.ccel.org/pix/mp3.png',alt='mp3');attrs.update(url=original['src'],n='mp3')
    elif tag=='hr':name='milestone';original['style']='width:50%';attrs.update(unit='horizontal-rule',rend='width:50%')
    else:name='anchor';original.update(passage='Luke 22:44',type='Sermon',parsed='|Luke|22|44|0|0',osisRef='Bible:Luke.22.44');attrs.update(type='ThML-scripCom',subtype='Sermon',n='Luke 22:44')
    if legacy:
        name='seg';attrs={XML+'id':'new','type':'ThML-'+tag}
        if original.get('class'):attrs['rend']=original['class']
        if original.get('lang'):attrs[XML+'lang']=original['lang']
    node=etree.SubElement(parent,NS+name,attrib=attrs);add_record(doc,row('new',tag,original,'w',3))
    return doc,node

def passes(doc):
    project_evidence(ET.fromstring(etree.tostring(doc)));observe_evidence(doc)

def rejects(doc,match=None):
    with pytest.raises(PipelineError,match=match):project_evidence(ET.fromstring(etree.tostring(doc)))
    with pytest.raises(ValueError,match=match):observe_evidence(doc)

@pytest.mark.parametrize('tag',BODY_NAMES)
def test_new_body_native_semantics_have_exact_source_attributes(tag):passes(body_fixture(tag)[0])

@pytest.mark.parametrize('tag',BODY_NAMES)
def test_existing_exact_neutral_body_carriers_remain_supported(tag):passes(body_fixture(tag,legacy=True)[0])

@pytest.mark.parametrize('tag',BODY_NAMES)
@pytest.mark.parametrize('mutation',('wrong-tag','extra-attribute'))
def test_new_body_names_do_not_admit_unknown_targets_or_attributes(tag,mutation):
    doc,node=body_fixture(tag)
    if mutation=='wrong-tag':node.tag=NS+'p'
    else:node.set('n' if tag not in ('img','scripCom') else 'ana','invented')
    rejects(doc)

@pytest.mark.parametrize('tag,key,value', [('ol','type','unordered'),('ol','rend','invented'),('ol',XML+'lang','fr'),('blockquote','rend','invented'),('em','rend','bold'),('em',XML+'lang','grc'),('strong','rend','italic'),('img','url','https://example.invalid/icon.png'),('img','n','invented'),('hr','unit','separator'),('hr','rend','width:100%'),('scripCom','n','Invented'),('scripCom','subtype','Invented'),('scripCom','type','Invented')])
def test_literal_added_semantics_reject_changed_payloads(tag,key,value):
    doc,node=body_fixture(tag);node.set(key,value);rejects(doc,'native body attributes')

@pytest.mark.parametrize('tag',BODY_NAMES)
def test_mapped_header_keeps_old_neutral_fallback_and_rejects_body_semantics(tag):
    doc=fixture();holder=doc.find('.//'+NS+'seg[@xml:id="d"]',namespaces={'xml':XML[1:-1]});node=etree.SubElement(holder,NS+'seg',attrib={XML+'id':'header-new','type':'ThML-'+tag});add_record(doc,row('header-new',tag,{'id':'header-new'},'d',3),5);passes(doc)
    node.tag=NS+dict(ol='list',blockquote='quote',em='hi',strong='hi',img='graphic',hr='milestone',scripCom='anchor')[tag];rejects(doc)

def inline_fixture():
    doc=fixture();parent=doc.find(NS+'text/'+NS+'body/'+NS+'div');listing=etree.SubElement(parent,NS+'list',attrib={XML+'id':'outer','type':'ordered'});item=etree.SubElement(listing,NS+'item',attrib={XML+'id':'item'});ab=etree.SubElement(item,NS+'ab',attrib={XML+'id':'inline','type':'source-inline-container','rend':'margin-left: 2em'});ab.text='Exact inline source text';b=etree.SubElement(ab,NS+'hi',attrib={XML+'id':'bold','rend':'bold'});b.text='A)';br=etree.SubElement(ab,NS+'lb',attrib={XML+'id':'break'});br.tail='Closing'
    for record in [row('outer','ol',{'id':'outer'},'w',3),row('item','li',{'id':'item'},'outer',1),row('inline','div',{'style':'margin-left: 2em','id':'inline'},'item',1),row('bold','b',{'id':'bold'},'inline',1),row('break','br',{'id':'break'},'inline',2)]:add_record(doc,record)
    return doc,ab

def test_inline_source_div_under_item_is_a_closed_literal_container():passes(inline_fixture()[0])

@pytest.mark.parametrize('mutation',('type','style','extra-target-attribute','extra-source-attribute','source-style','wrong-source-parent','wrong-target-parent','block-child','nested-division'))
def test_inline_container_does_not_admit_other_hierarchies_or_semantics(mutation):
    doc,ab=inline_fixture();ledger=doc.find(NS+'standOff/'+NS+'list');entry=next(n for n in ledger if n.get('n')=='inline');record=json.loads(entry.text)
    if mutation=='type':ab.set('type','invented')
    elif mutation=='style':ab.set('rend','margin-left:4em')
    elif mutation=='extra-target-attribute':ab.set('n','invented')
    elif mutation=='extra-source-attribute':record['source_attributes'].append(['class','invented']);entry.text=json.dumps(record)
    elif mutation=='source-style':record['source_attributes'][0][1]='margin-left:4em';entry.text=json.dumps(record)
    elif mutation=='wrong-source-parent':
        item=next(n for n in ledger if n.get('n')=='item');value=json.loads(item.text);value['source_element']='p';item.text=json.dumps(value);ab.getparent().tag=NS+'p'
    elif mutation=='wrong-target-parent':ab.getparent().tag=NS+'p'
    else:
        child=ab[0];item=next(n for n in ledger if n.get('n')=='bold');value=json.loads(item.text);value['source_element']='p' if mutation=='block-child' else 'div';item.text=json.dumps(value);child.tag=NS+value['source_element'];child.attrib.pop('rend')
    rejects(doc)

def test_actual_whole_frozen_candidate_projects_and_checks_with_producer_disabled(tmp_path,monkeypatch):
    from ocd_kernel.projection.categories.native_documents import project_document,verify_document
    raw=CANDIDATE.read_bytes();assert sha256(raw).hexdigest()=='b68c425e0323d66f6ab439a2684dd429c3d72f3421e06674f341eec1bea7afb9'
    doc=etree.fromstring(raw);passes(doc)
    # Actual complete native candidate, not a synthetic source-selected document.
    context=dict(identity=dict(work_id='edwards-select-sermons',textual_form_id='edwards-select-sermons-english',edition_id='edwards-select-sermons-ccel-thml-electronic'),language='en',representation_revision='fixture-v1',edition_title='CCEL ThML electronic witness',category='sermons',collection=True,_allow_acceptance_metadata=True)
    result=project_document(CANDIDATE,**context);assert len(result['rows'])==21
    import ocd_kernel.projection.native_content as producer
    def unavailable(*args,**kwargs):pytest.fail('producer or renderer invoked by independent checker')
    monkeypatch.setattr(producer,'project_content',unavailable);monkeypatch.setattr(producer,'readable_content',unavailable)
    assert verify_document(CANDIDATE,result['rows'],result['receipt'],**context)==[]
    changed=deepcopy(result['rows']);changed[1]['text']='Invented';assert verify_document(CANDIDATE,changed,result['receipt'],**context)
