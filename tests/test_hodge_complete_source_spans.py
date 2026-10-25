"""Closed source-backed Hodge spans; retained-candidate cases skip when unavailable."""
from copy import deepcopy
import json
import os
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection import native_content as producer
from ocd_kernel.projection.native_content_check import observe_content,verify_content
from ocd_kernel.projection.categories import native_documents as documents

NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
PROFILE='ocd-prose-hodge-theology1-retained-volume-v1'
IDENTITY={'work_id':'hodge-systematic-theology-vol-1','textual_form_id':'hodge-systematic-theology-vol-1-english','edition_id':'hodge-systematic-theology-vol-1-retained-electronic-witness'}

def token(tag='td',attributes=None):
    attributes=attributes or [['rowspan','3'],['id','iv.x.vi-p28.3']]
    return 'urn:ocd:hodge-theology1:ThML:'+quote(json.dumps({'tag':tag,'attributes':attributes},ensure_ascii=False,separators=(',',':')),safe='')

def row():
    result=ET.Element(NS+'row');cell=ET.SubElement(result,NS+'cell',{XML+'id':'hodge-systematic-theology-vol-1-feature-000123','ana':token(),'rows':'3'});cell.text='source wording'
    return result

def both_reject(node,reason):
    with pytest.raises(Exception,match=reason):producer.project_content(node,source_profile=PROFILE)
    with pytest.raises(ValueError,match=reason):observe_content(ET.tostring(node),source_profile=PROFILE)

def test_literal_span_and_nonspan_header_are_independently_observed():
    value=row();first=producer.project_content(value,source_profile=PROFILE)
    observed,text=observe_content(ET.tostring(value),source_profile=PROFILE)
    assert first==observed and text=='source wording'
    assert first['content'][0]['attributes']['row_span']=='3'
    cell=value[0];cell.attrib.pop('rows');cell.set('role','label');cell.set('ana',token('th',[['colspan','3'],['id','ii-p3.1']]));cell.set('cols','3')
    assert producer.project_content(value,source_profile=PROFILE)==observe_content(ET.tostring(value),source_profile=PROFILE)[0]

@pytest.mark.parametrize('case,reason',[
    ('rows-missing','literal source rowspan'),('rows-changed','literal source rowspan'),('zero','literal source rowspan'),('leading-zero','literal source rowspan'),
    ('ana-missing','identity'),('both-missing','identity'),('foreign-prefix','identity'),('foreign-id','identity'),
    ('duplicate-key','annotation'),('duplicate-attribute','original attributes'),('unknown-attribute','original attributes'),('noncanonical','annotation'),
    ('header-role-missing','header role'),('td-header-role','header role'),('header-rowspan','cannot carry a row span'),('outside-row','row parent'),
])
def test_forbidden_source_shapes_fail_for_the_intended_reason(case,reason):
    value=row();cell=value[0]
    if case=='rows-missing':cell.attrib.pop('rows')
    elif case=='rows-changed':cell.set('rows','4')
    elif case=='zero':cell.set('rows','0')
    elif case=='leading-zero':cell.set('rows','03')
    elif case=='ana-missing':cell.attrib.pop('ana')
    elif case=='both-missing':cell.attrib.pop('ana');cell.attrib.pop('rows')
    elif case=='foreign-prefix':cell.set('ana',cell.get('ana').replace('hodge-theology1','other'))
    elif case=='foreign-id':cell.set(XML+'id','other-123')
    elif case=='duplicate-key':cell.set('ana','urn:ocd:hodge-theology1:ThML:'+quote('{"tag":"td","tag":"td","attributes":[]}',safe=''))
    elif case=='duplicate-attribute':cell.set('ana',token(attributes=[['id','source'],['id','source'],['rowspan','3']]))
    elif case=='unknown-attribute':cell.set('ana',token(attributes=[['id','source'],['rowspan','3'],['unknown','x']]))
    elif case=='noncanonical':cell.set('ana',cell.get('ana').replace('%7B','%7b'))
    elif case=='header-role-missing':cell.attrib.pop('rows');cell.set('ana',token('th',[['id','ii-p3.1']]))
    elif case=='td-header-role':cell.set('role','label')
    elif case=='header-rowspan':cell.set('role','label');cell.set('ana',token('th'))
    elif case=='outside-row':value=ET.Element(NS+'div');value.append(cell)
    both_reject(value,reason)

@pytest.mark.parametrize('profile',[None,producer.CAREY_PROFILE,producer.BCP_HTML_PROFILE,producer.BENNETT_CHRONICLES_PROFILE,'unknown-profile'])
@pytest.mark.parametrize('with_span',[True,False])
def test_other_profiles_do_not_admit_hodge_span(profile,with_span):
    value=row()
    if not with_span:
        value[0].attrib.pop('rows');value[0].set('ana',token(attributes=[['id','iv.x.vi-p28.3']]))
    with pytest.raises(PipelineError):producer.project_content(value,source_profile=profile)
    with pytest.raises(ValueError):observe_content(ET.tostring(value),source_profile=profile)

def test_saved_content_mutations_fail_with_producer_disabled(monkeypatch):
    value=row();raw=ET.tostring(value);content,text=observe_content(raw,source_profile=PROFILE)
    monkeypatch.setattr(producer,'project_content',lambda *a,**k:pytest.fail('producer invoked by checker'))
    assert verify_content(raw,content,text,source_profile=PROFILE)==[]
    for field in ['row_span','source_annotations']:
        changed=deepcopy(content);changed['content'][0]['attributes'].pop(field)
        assert verify_content(raw,changed,text,source_profile=PROFILE)
    changed=deepcopy(content);changed['content']=[]
    assert verify_content(raw,changed,text,source_profile=PROFILE)
    assert verify_content(raw,content,text+' changed',source_profile=PROFILE)

@pytest.mark.parametrize('profile',[None,producer.CAREY_PROFILE])
def test_ordinary_and_carey_positive_compatibility(profile):
    table=ET.Element(NS+'table')
    if profile==producer.CAREY_PROFILE:table.set('rows','1');table.set('cols','5')
    line=ET.SubElement(table,NS+'row')
    if profile==producer.CAREY_PROFILE:line.set('role','data')
    for index in range(1,6):
        cell=ET.SubElement(line,NS+'cell');cell.text='Literal cell '+str(index)
        if profile==producer.CAREY_PROFILE:cell.set('n',str(index))
    assert producer.project_content(table,source_profile=profile)==observe_content(ET.tostring(table),source_profile=profile)[0]

@pytest.fixture
def retained_candidate():
    configured=os.environ.get('OCD_HODGE_COMPLETE_CANDIDATE')
    path=Path(configured) if configured else Path(__file__).resolve().parents[1]/'reports/_logs/hodge-vol1-current-reconciliation-20261002-v1/complete-native-v2/candidate.tei.xml'
    if not path.is_file():pytest.skip('Retained Hodge complete candidate unavailable; configure OCD_HODGE_COMPLETE_CANDIDATE')
    return path

def test_all_actual_594_cells_and_57_literal_spans(retained_candidate):
    root=ET.fromstring(retained_candidate.read_bytes());cells=list(root.find(NS+'text').iter(NS+'cell'));assert len(cells)==594
    assert sum('rows' in c.attrib for c in cells)==57
    assert sum(c.get('role')=='label' for c in cells)==41
    for cell in cells:
        wrapper=ET.Element(NS+'row');wrapper.append(cell)
        content=producer.project_content(wrapper,source_profile=PROFILE)
        assert content==observe_content(ET.tostring(wrapper),source_profile=PROFILE)[0]

@pytest.mark.parametrize('change',['work','form','edition','language','category','profile','accepted','root'])
def test_native_document_identity_opt_in_is_closed(retained_candidate,tmp_path,change):
    path=retained_candidate;identity=dict(IDENTITY);language='en';category='prose';profile=PROFILE;accepted=True
    if change in ('work','form','edition'):identity[{'work':'work_id','form':'textual_form_id','edition':'edition_id'}[change]]='wrong'
    elif change=='language':language='la'
    elif change=='category':category='sermons'
    elif change=='profile':profile='unknown'
    elif change=='accepted':accepted=False
    elif change=='root':
        root=ET.fromstring(path.read_bytes());root.set(XML+'id','wrong');path=tmp_path/'changed.xml';path.write_bytes(ET.tostring(root))
    with pytest.raises(Exception,match='profile|identity|envelope'):
        documents.project_document(path,identity=identity,language=language,category=category,projection_profile=profile,_allow_acceptance_metadata=accepted,representation_revision='focused-test',edition_title='Retained volume')
    errors=documents.verify_document(path,[],{},identity=identity,language=language,category=category,projection_profile=profile,_allow_acceptance_metadata=accepted,representation_revision='focused-test',edition_title='Retained volume')
    assert len(errors)==1 and any(token in errors[0] for token in ['profile','identity','envelope'])
