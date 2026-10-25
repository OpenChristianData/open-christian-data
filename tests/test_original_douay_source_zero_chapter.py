"""Explicit source-native Original Douay zero chapter; positive default unchanged."""
from copy import deepcopy
from pathlib import Path
import json
from lxml import etree
import pytest
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import bible
ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'tests/fixtures/library-pipeline/categories/bible'
CONTEXT=json.loads((FIXTURE/'manifest.json').read_bytes())['fixtures'][0]['context']
NS='{http://www.tei-c.org/ns/1.0}'
SPACE='{http://www.w3.org/XML/1998/namespace}space'
POLICY='source-native-zero-chapter-v1'
VERSIFICATION='source-native:original-douay-rheims-v1.0'

def zero_fixture(tmp_path):
    root=etree.fromstring((FIXTURE/'kjv-genesis.tei.xml').read_bytes())
    source=root.find('.//'+NS+'sourceDesc');policy=etree.SubElement(source,NS+'idno',type='bible_native_chapter_policy');policy.text=POLICY
    for node in source.iter(NS+'idno'):
        if node.get('type') in {'bible_versification','versification'}:node.text=VERSIFICATION
    chapter=next(n for n in root.iter(NS+'div') if n.get('type')=='chapter');chapter.set('n','0')
    verses=list(chapter.iter(NS+'ab'))
    for n in verses[2:]:n.getparent().remove(n)
    for index,n in enumerate(verses[:2]):n.set('n',str(index));n.set(SPACE,'preserve');n.text=['Source introduction with native 0:0.','Tobias of the tribe and city of Nephthali.'][index]
    context=dict(CONTEXT,versification=VERSIFICATION)
    return root,chapter,verses[:2],policy,context,tmp_path/'zero.tei.xml'
def save(root,path):path.write_bytes(etree.tostring(root,encoding='UTF-8',xml_declaration=True))

def test_two_native_zero_occurrences_and_schema(tmp_path,monkeypatch):
    root,chapter,verses,policy,context,path=zero_fixture(tmp_path);save(root,path)
    result=bible.project_bible_document(path,**context);rows=result['rows']
    assert len(rows)==2 and [r['text'] for r in rows]==[n.text for n in verses]
    assert [r['locator']['verse'] for r in rows]==['0','1']
    for row in rows:
        assert row['locator']['chapter']==0 and row['locator']['chapter_label']=='0'
        assert row['locator']['native_chapter_policy']==POLICY
        assert row['locator']['reference_status']=='unsupported-verse-components'
        assert 'reference' not in row['locator']
    bible._validate_rows(rows)
    monkeypatch.setattr(bible,'project_bible_document',lambda *a,**k:pytest.fail('producer invoked'))
    monkeypatch.setattr(bible,'_projection',lambda *a,**k:pytest.fail('producer invoked'))
    assert bible.verify_bible_document(path,rows,result['receipt'],**context)==[]

@pytest.mark.parametrize('case',['no-policy','wrong-policy','other-native-edition','double-zero','negative','trimmed-zero','duplicate-policy'])
def test_closed_zero_eligibility_in_both_walks(tmp_path,case):
    root,chapter,verses,policy,context,path=zero_fixture(tmp_path)
    reason='invalid chapter' if case in {'no-policy','double-zero','negative','trimmed-zero'} else 'invalid native chapter policy'
    if case=='no-policy':policy.getparent().remove(policy)
    elif case=='wrong-policy':policy.text='invented'
    elif case=='other-native-edition':
        context['versification']='source-native:other-edition'
        for node in root.iter(NS+'idno'):
            if node.get('type') in {'bible_versification','versification'}:node.text=context['versification']
    elif case=='double-zero':chapter.set('n','00')
    elif case=='negative':chapter.set('n','-1')
    elif case=='trimmed-zero':chapter.set('n',' 0 ')
    elif case=='duplicate-policy':policy.addnext(deepcopy(policy));reason='duplicate source binding bible_native_chapter_policy'
    save(root,path)
    producer_reason='chapter number is not positive' if reason=='invalid chapter' else reason
    with pytest.raises(PipelineError,match='unsupported-visible: '+producer_reason):bible.project_bible_document(path,**context)
    errors=bible.verify_bible_document(path,[],{},**context)
    assert len(errors)==1 and errors[0].startswith('unsupported-visible: '+reason),errors

@pytest.mark.parametrize('case',['omit-first','omit-second','duplicate','chapter-label','policy-marker','invent-reference','normalization-status','wording'])
def test_saved_checker_zero_challenges(tmp_path,monkeypatch,case):
    root,chapter,verses,policy,context,path=zero_fixture(tmp_path);save(root,path)
    result=bible.project_bible_document(path,**context);rows=deepcopy(result['rows']);receipt=deepcopy(result['receipt'])
    if case=='omit-first':rows.pop(0)
    elif case=='omit-second':rows.pop(1)
    elif case=='duplicate':rows.insert(1,deepcopy(rows[0]))
    elif case=='chapter-label':rows[0]['locator']['chapter_label']='1'
    elif case=='policy-marker':rows[0]['locator'].pop('native_chapter_policy')
    elif case=='invent-reference':rows[1]['locator']['reference']={'kind':'verse','start':{'book':'Tob','chapter':1,'verse':1},'end':None}
    elif case=='normalization-status':rows[1]['locator']['reference_status']='normalized-verse-components'
    elif case=='wording':rows[1]['text']='Invented wording'
    monkeypatch.setattr(bible,'project_bible_document',lambda *a,**k:pytest.fail('producer invoked'))
    monkeypatch.setattr(bible,'_projection',lambda *a,**k:pytest.fail('producer invoked'))
    assert bible.verify_bible_document(path,rows,receipt,**context)

def test_positive_default_fixture_unchanged(tmp_path):
    path=tmp_path/'positive.tei.xml';path.write_bytes((FIXTURE/'kjv-genesis.tei.xml').read_bytes())
    result=bible.project_bible_document(path,**CONTEXT)
    assert len(result['rows'])==3
    assert all(r['locator']['chapter']>0 and 'native_chapter_policy' not in r['locator'] and 'chapter_label' not in r['locator'] for r in result['rows'])
    assert bible.verify_bible_document(path,result['rows'],result['receipt'],**CONTEXT)==[]

@pytest.mark.parametrize('case',['missing-label','missing-policy','other-edition','reference','negative'])
def test_category_schema_closed_zero_rows(tmp_path,case):
    root,chapter,verses,policy,context,path=zero_fixture(tmp_path);save(root,path)
    row=deepcopy(bible.project_bible_document(path,**context)['rows'][0])
    if case=='missing-label':row['locator'].pop('chapter_label')
    elif case=='missing-policy':row['locator'].pop('native_chapter_policy')
    elif case=='other-edition':row['versification']=row['locator']['versification']='source-native:other'
    elif case=='reference':row['locator']['reference']={'kind':'verse','start':{'book':'Gen','chapter':1,'verse':1},'end':None}
    elif case=='negative':row['locator']['chapter']=-1
    with pytest.raises(PipelineError,match='invalid Bible public row'):bible._validate_rows([row])
