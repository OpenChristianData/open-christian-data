"""Real-witness PG33128 rows and producer-disabled independent mutations."""
from __future__ import annotations
import copy
import importlib.util
from pathlib import Path
import pytest
from lxml import etree
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import pg33128_hymns as adapter

ROOT=Path(__file__).resolve().parents[1]
CONTEXT=dict(retained_path=ROOT/adapter.SOURCE_MEMBER_PATH,
             identity=dict(work_id=adapter.WORK_ID,textual_form_id='pg33128-complete-text',edition_id='pg33128-second-edition-1899'),
             language='mul',representation_revision='pg33128-projection-test',edition_title='Second edition, 1899')

@pytest.fixture(scope='module')
def baseline(tmp_path_factory):
    manifest=SourceManifest.load(ROOT/'sources/manifest-acquisitions/l744-pg33128-gospel-hymns/source-manifest.json',repository_root=ROOT)
    spec=importlib.util.spec_from_file_location('pg33128_projection_fixture',ROOT/'build/tei/l744_hymns.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    members=dict(module._convert(manifest))
    path=tmp_path_factory.mktemp('gh28')/'master.xml'
    path.write_bytes(members['content.tei.xml'])
    result=adapter.project_pg33128_document(path,**CONTEXT)
    return path,result

def test_complete_rows_source_order_stanzas_inline_chorus_and_notices(baseline):
    path,result=baseline
    rows=result['rows']
    assert len(rows)==76
    assert [row['occurrence_id'] for row in rows]==[f'h{n}{suffix}' for n in range(1,39) for suffix in ('','a')]
    assert sum(len(row['segments']) for row in rows)==390
    assert sum(len(row['stanzas']) for row in rows)==384
    assert sum('refrain' in row for row in rows)==6
    assert rows[0]['stanzas'][0]['lines']==['All people that on earth do dwell,','Sing to the Lord with cheerful voice;','Him serve with fear, his praise forth tell,','Come ye before him and rejoice.']
    assert rows[0]['stanzas'][1]['number']==2
    assert rows[6]['refrain']['label']=='Chorus.—'
    assert rows[6]['refrain']['lines']==['E-ven me, e-ven me,','Let thy blessing fall on me.']
    assert rows[7]['refrain']['label']=='Cho.—'
    assert rows[7]['refrain']['lines']==['Kuh ya neen, kuh ya neen,','Mon oo shuh wa ne me shin.']
    assert {row['language'] for row in rows}=={'mul'}
    assert adapter.verify_pg33128_document(path,rows,result['receipt'],**CONTEXT)==[]

def test_exact_html_selection_preserves_full_five_member_envelope():
    included=[dict(path=path,bytes=length,sha256=digest,position=index) for index,(path,length,digest) in enumerate(adapter.ENVELOPE,1)]
    assert adapter.select_pg33128_member(included)['path']==adapter.SOURCE_MEMBER_PATH
    for mutation in ('omit','hash','order'):
        changed=copy.deepcopy(included)
        if mutation=='omit': changed.pop()
        elif mutation=='hash': changed[1]['sha256']='0'*64
        else: changed.reverse()
        with pytest.raises(PipelineError):adapter.select_pg33128_member(changed)

@pytest.mark.parametrize('mutation',['omit-occurrence','invent-occurrence','pair-order','line-text','missing-stanza','stanza-number','chorus-line','chorus-label','title','meter','language','locator','receipt-exclusion','receipt-reason','receipt-warning','receipt-hash'])
def test_independent_verifier_rejects_output_mutations_with_producer_disabled(baseline,monkeypatch,mutation):
    path,result=baseline
    rows=copy.deepcopy(result['rows'])
    receipt=copy.deepcopy(result['receipt'])
    def disabled(*args,**kwargs): raise AssertionError('producer invoked by independent checker')
    monkeypatch.setattr(adapter,'project_pg33128_document',disabled)
    monkeypatch.setattr(adapter,'_tei_rows',disabled)
    monkeypatch.setattr(adapter,'_line',disabled)
    monkeypatch.setattr(adapter,'_receipt',disabled)
    assert adapter.verify_pg33128_document(path,result['rows'],result['receipt'],**CONTEXT)==[]
    if mutation=='omit-occurrence':rows.pop(0)
    elif mutation=='invent-occurrence':rows.append(copy.deepcopy(rows[0]))
    elif mutation=='pair-order':rows[0],rows[1]=rows[1],rows[0]
    elif mutation=='line-text':rows[0]['stanzas'][0]['lines'][0]='invented lyric'
    elif mutation=='missing-stanza':rows[0]['stanzas'].pop()
    elif mutation=='stanza-number':rows[0]['stanzas'][1]['number']=3
    elif mutation=='chorus-line':rows[6]['refrain']['lines'].pop(0)
    elif mutation=='chorus-label':rows[6]['refrain']['label']='Changed label'
    elif mutation=='title':rows[0]['title']='invented title'
    elif mutation=='meter':rows[0]['notes'][0]['text']='Changed meter'
    elif mutation=='language':rows[1]['language']='en'
    elif mutation=='locator':rows[0]['locator']['divisions'][0]['titles']=['Wrong source heading']
    elif mutation=='receipt-exclusion':receipt['exclusions'].pop()
    elif mutation=='receipt-reason':receipt['exclusions'][0]['reason']='unreviewed exclusion reason'
    elif mutation=='receipt-warning':receipt['warnings']=['rights cleared']
    else:receipt['output_sha256']='0'*64
    errors=adapter.verify_pg33128_document(path,rows,receipt,**CONTEXT)
    assert errors,mutation
    assert all('producer invoked' not in error for error in errors)

@pytest.mark.parametrize('mutation',['line','parent','class','title','number','pair-order','inline-order','invent-empty-carrier'])
def test_source_checker_rejects_mutated_master_independently(baseline,tmp_path,monkeypatch,mutation):
    path,result=baseline
    tree=etree.fromstring(path.read_bytes())
    ns={'t':'http://www.tei-c.org/ns/1.0'}
    unit=tree.xpath(".//t:div[@xml:id='h1']",namespaces=ns)[0]
    line=unit.xpath(".//t:p[@rend='source-class:t0']",namespaces=ns)[0]
    verse=unit.xpath(".//t:div[@rend='source-class:verse']",namespaces=ns)[0]
    if mutation=='line':line.text='changed reading'
    elif mutation=='parent':unit.append(line)
    elif mutation=='class':line.set('rend','source-class:t2')
    elif mutation=='title':unit.set('rend','source-title:Wrong hymn')
    elif mutation=='number':line.set('n','999999')
    elif mutation=='inline-order':
        paragraph=tree.xpath(".//t:p[count(t:seg[@rend='source-class:w']) > 1]",namespaces=ns)[0]
        segment=paragraph[0]
        paragraph.remove(segment)
        paragraph.append(segment)
    elif mutation=='invent-empty-carrier':etree.SubElement(unit,'{http://www.tei-c.org/ns/1.0}p')
    else:
        parent=unit.getparent()
        sibling=tree.xpath(".//t:div[@xml:id='h1a']",namespaces=ns)[0]
        parent.remove(unit)
        parent.insert(list(parent).index(sibling)+1,unit)
    changed=tmp_path/'mutated.xml'
    changed.write_bytes(etree.tostring(tree))
    monkeypatch.setattr(adapter,'_tei_rows',lambda *args,**kwargs:pytest.fail('producer invoked'))
    errors=adapter.verify_pg33128_document(changed,result['rows'],result['receipt'],**CONTEXT)
    assert any('master' in error for error in errors),errors

def test_source_hash_substitution_fails_closed(baseline,tmp_path):
    path,result=baseline
    other=tmp_path/'wrong.html'
    other.write_bytes(b'<html>wrong source</html>')
    context=CONTEXT|dict(retained_path=other)
    with pytest.raises(PipelineError,match='source changed'):adapter.project_pg33128_document(path,**context)
    assert adapter.verify_pg33128_document(path,result['rows'],result['receipt'],**context)
