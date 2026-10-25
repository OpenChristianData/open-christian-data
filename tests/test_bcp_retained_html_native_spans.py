"""Closed retained HTML row-span support; independent observer rejection proofs."""
from copy import deepcopy
import json
from urllib.parse import quote
import xml.etree.ElementTree as ET
from lxml import etree
import pytest
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.native_content import BCP_HTML_PROFILE, CAREY_PROFILE, BENNETT_CHRONICLES_PROFILE, project_content, readable_content
from ocd_kernel.projection.native_content_check import observe_content, verify_content

NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'


def source_table(year=1559,value='2'):
 table=ET.Element(NS+'table');row=ET.SubElement(table,NS+'row')
 cell=ET.SubElement(row,NS+'cell',{'rows':value,XML+'id':f'bcp{year}-fixture',
  'ana':f'urn:ocd:bcp{year}:html:'+quote(json.dumps({'tag':'td','attributes':[['width','17%'],['rowspan',value]]},separators=(',',':')),safe='')})
 cell.text='Literal source table cell'
 return table,cell


def rejected(table,profile=BCP_HTML_PROFILE):
 with pytest.raises(PipelineError):project_content(table,source_profile=profile)
 with pytest.raises(ValueError):observe_content(ET.tostring(table),source_profile=profile)


@pytest.mark.parametrize('year,value',[(1559,'2'),(1559,'4'),(1549,'1'),(1549,'2'),(1549,'4')])
def test_literal_span_preserved_by_independent_observer(year,value):
 table,_=source_table(year,value);result=project_content(table,source_profile=BCP_HTML_PROFILE)
 content,text=observe_content(ET.tostring(table),source_profile=BCP_HTML_PROFILE)
 assert result==content and readable_content(result)==text
 assert result['content'][0]['content'][0]['attributes']['row_span']==value
 assert verify_content(ET.tostring(table),result,text,source_profile=BCP_HTML_PROFILE)==[]


@pytest.mark.parametrize('profile',[None,CAREY_PROFILE,BENNETT_CHRONICLES_PROFILE,'ocd-liturgies-bcp1662-retained-members-v1','invented-profile'])
@pytest.mark.parametrize('with_span',[True,False])
def test_source_row_span_rejected_outside_closed_profile(profile,with_span):
 table,cell=source_table()
 if not with_span:cell.attrib.pop('rows')
 rejected(table,profile)


@pytest.mark.parametrize('profile',[None,BENNETT_CHRONICLES_PROFILE])
@pytest.mark.parametrize('span',['1','2','4'])
def test_generic_and_bennett_literal_spans_remain_supported(profile,span):
 table=ET.Element(NS+'table');row=ET.SubElement(table,NS+'row')
 cell=ET.SubElement(row,NS+'cell',rows=span);cell.text='Literal source table cell'
 projected=project_content(table,source_profile=profile)
 observed,text=observe_content(ET.tostring(table),source_profile=profile)
 assert projected==observed and text=='Literal source table cell'
 assert observed['content'][0]['content'][0]['attributes']['row_span']==span
 assert verify_content(ET.tostring(table),projected,text,source_profile=profile)==[]


@pytest.mark.parametrize('value',['0','-1','1.5','01','\u0662','', '2 '])
def test_invalid_literal_spans_fail_both_readers(value):
 table,_=source_table(value=value);rejected(table)


@pytest.mark.parametrize('case',['missing-annotation','changed-span','missing-target-span','missing-source-span','duplicate-source-span','wrong-tag','extra-key','duplicate-json-key','wrong-prefix','wrong-id','malformed-percent','invalid-json','not-pairs','wrong-parent'])
def test_source_annotation_and_hierarchy_are_closed(case):
 table,cell=source_table();original={'tag':'td','attributes':[['width','17%'],['rowspan','2']]}
 if case=='missing-annotation':cell.attrib.pop('ana')
 elif case=='changed-span':cell.set('rows','4')
 elif case=='missing-target-span':cell.attrib.pop('rows')
 elif case=='missing-source-span':original['attributes'].pop()
 elif case=='duplicate-source-span':original['attributes'].append(['rowspan','2'])
 elif case=='wrong-tag':original['tag']='tr'
 elif case=='extra-key':original['invented']='yes'
 elif case=='wrong-prefix':cell.set('ana',cell.get('ana').replace('bcp1559','bcp1662'))
 elif case=='wrong-id':cell.set(XML+'id','bcp1549-fixture')
 elif case=='malformed-percent':cell.set('ana',cell.get('ana')+'%ZZ')
 elif case=='invalid-json':cell.set('ana','urn:ocd:bcp1559:html:%7B')
 elif case=='not-pairs':original['attributes']=['rowspan']
 elif case=='duplicate-json-key':cell.set('ana','urn:ocd:bcp1559:html:'+quote('{"tag":"td","tag":"td","attributes":[["rowspan","2"]]}',safe=''))
 elif case=='wrong-parent':table[0].remove(cell);table.append(cell)
 if case in ('missing-source-span','duplicate-source-span','wrong-tag','extra-key','not-pairs'):
  cell.set('ana','urn:ocd:bcp1559:html:'+quote(json.dumps(original,separators=(',',':')),safe=''))
 rejected(table)


@pytest.mark.parametrize('mutation',['loss','change'])
def test_independent_observer_rejects_public_span_mutation(mutation):
 table,_=source_table();raw=ET.tostring(table);content,text=observe_content(raw,source_profile=BCP_HTML_PROFILE)
 changed=deepcopy(content);attrs=changed['content'][0]['content'][0]['attributes']
 if mutation=='loss':attrs.pop('row_span')
 else:attrs['row_span']='4'
 assert verify_content(raw,changed,text,source_profile=BCP_HTML_PROFILE)


def test_original_carey_cell_position_guard_preserved():
 table=ET.Element(NS+'table',rows='1',cols='5');row=ET.SubElement(table,NS+'row',role='data')
 ET.SubElement(row,NS+'cell',n='6').text='Outside dimensions'
 with pytest.raises(PipelineError):project_content(table,source_profile=CAREY_PROFILE)
 with pytest.raises(ValueError):observe_content(ET.tostring(table),source_profile=CAREY_PROFILE)


def test_non_rowspan_cell_unchanged():
 table,cell=source_table();cell.attrib.pop('rows')
 cell.set('ana','urn:ocd:bcp1559:html:'+quote(json.dumps({'tag':'td','attributes':[['width','17%']]},separators=(',',':')),safe=''))
 content=project_content(table,source_profile=BCP_HTML_PROFILE)
 observed,text=observe_content(ET.tostring(table),source_profile=BCP_HTML_PROFILE)
 assert content==observed and 'row_span' not in content['content'][0]['content'][0]['attributes']
