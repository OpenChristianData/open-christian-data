"""Actual complete1559 projection plus closed identity/member/schema checks."""
from copy import deepcopy
from pathlib import Path
import os
import xml.etree.ElementTree as ET
from lxml import etree
import pytest
from ocd_kernel.library._common import PipelineError
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.projection.categories import liturgies
from ocd_kernel.projection.categories import liturgies_bcp1559 as producer
from ocd_kernel.projection.categories import liturgies_bcp1559_check as observer

ROOT=Path(__file__).resolve().parents[1]
CANDIDATE=Path(os.environ['OCD_BCP1559_CANDIDATE']) if os.environ.get('OCD_BCP1559_CANDIDATE') else resolve_repo_path(ROOT,'reports').parent/'candidate-reviews/bcp1559-current-20261002-v2/package/content.tei.xml'
SHA='3907571f9368082a0f45e2aba8d4c36d0503a7931631d690ee5dc700d336591e'
KWARGS=dict(identity=producer.IDENTITY,language='en',representation_revision='bcp1559-support-probe',
 edition_title='The Book of Common Prayer (1559) retained electronic witness',projection_profile=producer.PROFILE,
 source_url='http://justus.anglican.org/resources/bcp/1559/',source_sha256=SHA,retained_sha256=SHA)


@pytest.fixture(scope='module')
def actual_file():
 if not CANDIDATE.is_file():
  pytest.skip('Complete retained BCP1559 candidate is unavailable; set OCD_BCP1559_CANDIDATE for actual-source checks')
 return CANDIDATE


@pytest.fixture(scope='module')
def actual(actual_file):
 return liturgies.project_liturgies_document(CANDIDATE,**KWARGS)


def test_actual_complete_projection_independent_with_producer_disabled(actual,monkeypatch):
 def forbidden(*args,**kwargs):raise AssertionError('Independent check invoked producer')
 monkeypatch.setattr(producer,'project_document',forbidden)
 monkeypatch.setattr('ocd_kernel.projection.native_content.project_content',forbidden)
 assert liturgies.verify_liturgies_document(CANDIDATE,actual['rows'],actual['receipt'],**KWARGS)==[]
 assert len(actual['rows'])==16
 spans=[]
 def walk(n):
  if n['kind']=='text':return
  if 'row_span' in n['attributes']:spans.append(n['attributes']['row_span'])
  for c in n['content']:walk(c)
 for row in actual['rows']:
  assert row['member_kind']=='source-member' and row['source_links']==[]
  assert row['response_model']=='source-native-labels-without-response-inference'
  walk(row['structure'][0])
 assert spans.count('2')==44 and spans.count('4')==2


def test_actual_changed_public_span_rejected(actual):
 rows=deepcopy(actual['rows'])
 def change(n):
  if n['kind']=='text':return False
  if 'row_span' in n['attributes']:n['attributes'].pop('row_span');return True
  return any(change(c) for c in n['content'])
 assert change(rows[0]['structure'][0])
 assert liturgies.verify_liturgies_document(CANDIDATE,rows,actual['receipt'],**KWARGS)


@pytest.mark.parametrize('case',['foreign-work','foreign-form','foreign-edition','wrong-language','unknown-profile','subset'])
def test_identity_and_profile_are_closed(case):
 kwargs=deepcopy(KWARGS)
 if case.startswith('foreign-'):kwargs['identity'][{'foreign-work':'work_id','foreign-form':'textual_form_id','foreign-edition':'edition_id'}[case]]='bcp-1662'
 elif case=='wrong-language':kwargs['language']='la'
 elif case=='unknown-profile':kwargs['projection_profile']='invented-profile'
 else:kwargs['scope_id']='one-member'
 with pytest.raises(PipelineError):liturgies.project_liturgies_document(CANDIDATE,**kwargs)
 assert liturgies.verify_liturgies_document(CANDIDATE,[],{},**kwargs)


@pytest.mark.parametrize('case',['missing-member','extra-member','member-order','member-name','wrong-wrapper','extra-envelope-text'])
def test_source_member_structure_rejected_by_both_grammars(case,actual_file):
 raw=actual_file.read_bytes(); a=ET.fromstring(raw);b=etree.fromstring(raw)
 for doc in (a,b):
  body=doc.find(producer.NS+'text/'+producer.NS+'body')
  if case=='missing-member':body.remove(body[-1])
  elif case=='extra-member':body.append(deepcopy(body[0]))
  elif case=='member-order':node=body[-1];body.remove(node);body.insert(0,node)
  elif case=='member-name':body[0].set('n','Invented.htm')
  elif case=='wrong-wrapper':body[0][1].set('subtype','invented')
  else:body.text='Unassigned source text'
 with pytest.raises(PipelineError):producer._parts(a)
 with pytest.raises(PipelineError):observer._inspect(b)


@pytest.mark.parametrize('case',['max1559','foreign1559','kind1559','response1559','inferred-link','old-step-field','max1662','kind1662','max1549'])
def test_schema_profile_boundaries(actual,case):
 row=deepcopy(actual['rows'][0]);row['structure']=[{'kind':'text','text':'Schema-only small fixture'}]
 if case=='max1559':row['member_number']=17;row['locator']['member']=17
 elif case=='foreign1559':row['work_id']='bcp-1662'
 elif case=='kind1559':row['member_kind']='service';row['locator']['member_kind']='service'
 elif case=='response1559':row['response_model']='literal-role-annotations-without-person-or-response-links'
 elif case=='inferred-link':row['source_links']=[{'kind':'continuation','path':[],'targets':[{'token':'a'*20,'path':[]}]}]
 elif case=='old-step-field':row['service_id']='invented'
 elif case in ('max1662','kind1662'):
  row.update(row_profile='ocd-liturgies-bcp1662-retained-members-v1',work_id='bcp-1662',textual_form_id='bcp-1662-retained-electronic',edition_id='bcp-1662-retained-electronic-witness',response_model='literal-role-annotations-without-person-or-response-links')
  row['member_kind']=row['locator']['member_kind']='service' if case=='max1662' else 'source-member'
  if case=='max1662':row['member_number']=26;row['locator']['member']=26
 else:
  row.update(row_profile='ocd-liturgies-bcp1549-retained-members-v1',work_id='bcp-1549',textual_form_id='bcp-1549-retained-electronic',edition_id='bcp-1549-retained-electronic-witness',member_number=35)
  row['locator']['member']=35
 assert list(liturgies._validator().iter_errors(row))
