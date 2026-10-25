from pathlib import Path
import copy
import pytest
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.envelope import project_document
from ocd_kernel.projection.receipt import build_correspondence_receipt
from ocd_kernel.release.verify import _accepted_header_identity, verify_document

CONTEXT = dict(identity={'work_id':'work','textual_form_id':'form','edition_id':'edition'}, language='en', representation_revision='test-v1', edition_title='Witness')

def source(tmp_path, second='', page='', prolog='', comment=''):
    path=tmp_path/'source.xml'
    path.write_text(f'<?xml version="1.0" encoding="utf-8"?>{prolog}<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader/><text><body><div type="chapter" xml:id="first"><p>First.</p></div><div type="chapter" xml:id="second" {second}><p>Second.<pb n="2" {page}/></p>{comment}</div></body></text></TEI>',encoding='utf-8')
    return path

def project(path):
    p=project_document(path,**CONTEXT)
    receipt=build_correspondence_receipt(p,identity=CONTEXT['identity'])
    assert verify_document(path,p['rows'],receipt,**CONTEXT)==[]
    return p['rows'],receipt

def test_private_attributes_round_trip_and_tamper(tmp_path):
    path=source(tmp_path,second='prev="#first" ana="source-tag:div1"',page='facs="/ccel/source/Page_2.html"')
    rows,receipt=project(path)
    assert 'source-tag:div1' not in str(rows)
    assert any(i['attributes'].get('ana')=='source-tag:div1' for i in receipt['inventory'])
    assert any(i['attributes'].get('facs')=='/ccel/source/Page_2.html' for i in receipt['inventory'])
    tampered=copy.deepcopy(receipt)
    next(i for i in tampered['inventory'] if i['attributes'].get('ana'))['attributes']['ana']='source-tag:div2'
    assert verify_document(path,rows,tampered,**CONTEXT)

@pytest.mark.parametrize('second,page',[('prev="#missing"',''),('ana="unaccounted"',''),('','facs="/../escape.html"')])
def test_invalid_private_attributes_fail_closed(tmp_path,second,page):
    with pytest.raises(PipelineError,match='unsupported-visible'):
        project_document(source(tmp_path,second=second,page=page),**CONTEXT)

def test_bounded_comments_are_private_and_mutation_detected(tmp_path):
    path=source(tmp_path,prolog='<!-- Copyright Christian Classics Ethereal Library -->',comment='<!-- Start of automatically inserted scripRef index -->')
    rows,receipt=project(path)
    comments=[i for i in receipt['inventory'] if i['tei_path'].startswith('comment:')]
    assert len(comments)==2
    assert {i['disposition'] for i in comments}=={'private-header','structure'}
    assert 'Copyright Christian Classics' not in str(rows)
    tampered=copy.deepcopy(receipt)
    next(i for i in tampered['inventory'] if i['tei_path'].startswith('comment:'))['text_sha256']='0'*64
    assert verify_document(path,rows,tampered,**CONTEXT)

def test_unaccounted_comment_rejected(tmp_path):
    with pytest.raises(PipelineError,match='XML comment'):
        project_document(source(tmp_path,comment='<!-- omitted annotation -->'),**CONTEXT)

def test_identity_alias_accepts_equal_and_rejects_conflict(tmp_path):
    path=tmp_path/'identity.xml'
    prefix='<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><sourceDesc><bibl>'
    suffix='</bibl></sourceDesc></fileDesc></teiHeader><text><body/></text></TEI>'
    ids='<idno type="work_id">work</idno><idno type="ocd-work-id">work</idno>'
    path.write_text(prefix+ids+suffix,encoding='utf-8')
    errors=[]
    _accepted_header_identity(path,{'work_id':'work'},errors)
    assert errors==[]
    path.write_text(prefix+ids.replace('ocd-work-id">work','ocd-work-id">other')+suffix,encoding='utf-8')
    errors=[]
    _accepted_header_identity(path,{'work_id':'work'},errors)
    assert errors

