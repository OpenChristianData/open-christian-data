"""The literal source 3415 marker must remain readable and privately accounted."""
from copy import deepcopy
from pathlib import Path
import pytest
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import project_document, verify_document

OPEN='<!-- <a href="#_edn3415" name="_ednref3415" id="xxi.ii-p5.3"> -->'
CLOSE='<!-- </a> -->'
SEG=f'<seg xml:id="npnf105-xxi.ii-p5.2" rend="MsoEndnoteReference">{OPEN} [3415]{CLOSE}</seg>'
BEFORE='<seg xml:id="npnf105-xxi.ii-p5.1" rend="c44">addressed to prosper and hilary.</seg> '
DOCUMENT=('<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><titleStmt><title>Predestination</title></titleStmt><publicationStmt><p>Private</p></publicationStmt><sourceDesc><p>Retained source</p></sourceDesc></fileDesc></teiHeader><text><body><div><p xml:id="npnf105-xxi.ii-p5" rend="c39">'+BEFORE+SEG+'</p></div></body></text></TEI>')
CONTEXT=dict(identity=dict(work_id='augustine-predestination-of-saints',textual_form_id='form',edition_id='edition'),language='en',representation_revision='source-3415-regression',edition_title='Predestination',category='prose',_allow_acceptance_metadata=True)

def test_readable_marker_and_exact_private_ledger(tmp_path:Path):
    path=tmp_path/'predestination.xml';path.write_text(DOCUMENT,encoding='utf-8');r=project_document(path,**CONTEXT)
    assert r['rows'][0]['text']=='addressed to prosper and hilary.  [3415]'
    ledger=r['receipt']['source_comments']
    assert ledger==[dict(parent_path='/*/*[2]/*/*/*/*[2]',child_index=0,text=' <a href="#_edn3415" name="_ednref3415" id="xxi.ii-p5.3"> ',tail=' [3415]',disposition='source-endnote-anchor-marker'),dict(parent_path='/*/*[2]/*/*/*/*[2]',child_index=1,text=' </a> ',tail='',disposition='source-endnote-anchor-marker')]
    assert verify_document(path,r['rows'],r['receipt'],**CONTEXT)==[]
    changed=deepcopy(r['receipt']);changed['source_comments'][0]['tail']='[3415]'
    assert verify_document(path,r['rows'],changed,**CONTEXT)
    changed_rows=deepcopy(r['rows']);changed_rows[0]['text']=changed_rows[0]['text'].replace('[3415]','[3414]')
    assert verify_document(path,changed_rows,r['receipt'],**CONTEXT)

@pytest.mark.parametrize('mutated',[
    DOCUMENT.replace('#_edn3415','#_edn3414'),
    DOCUMENT.replace(' [3415]','[3415]'),
    DOCUMENT.replace(CLOSE,'<!-- </b> -->'),
    DOCUMENT.replace('rend="MsoEndnoteReference"','rend="other"'),
    DOCUMENT.replace('npnf105-xxi.ii-p5.2','npnf105-xxi.ii-p5.9'),
    DOCUMENT.replace(OPEN,' '+OPEN),
    DOCUMENT.replace(OPEN+' [3415]'+CLOSE,CLOSE+' [3415]'+OPEN),
    DOCUMENT.replace(CLOSE+'</seg>','</seg>'+CLOSE),
    DOCUMENT.replace(BEFORE+SEG,SEG+BEFORE),
    DOCUMENT.replace('npnf105-xxi.ii-p5"','npnf105-xxi.ii-p6"'),
],ids=['anchor-target','marker-spacing','closing-comment','segment-class','segment-id','segment-text','comment-order','comment-location','segment-position','paragraph-id'])
def test_changed_source_pair_fails_producer_and_independent_checker(tmp_path:Path,mutated:str):
    path=tmp_path/'predestination.xml';path.write_text(DOCUMENT,encoding='utf-8');r=project_document(path,**CONTEXT)
    path.write_text(mutated,encoding='utf-8')
    with pytest.raises(PipelineError,match='source endnote marker|source comment location'):project_document(path,**CONTEXT)
    errors=verify_document(path,r['rows'],r['receipt'],**CONTEXT)
    assert any('source endnote marker' in e or 'source comment location' in e for e in errors)
