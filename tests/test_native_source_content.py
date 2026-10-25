from __future__ import annotations
import copy
import xml.etree.ElementTree as ET
import pytest
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.native_content import project_content, readable_content
from ocd_kernel.projection.native_content_check import verify_content

NS='http://www.tei-c.org/ns/1.0'

def check(xml):
    raw=xml.encode('utf-8')
    content=project_content(ET.fromstring(raw))
    text=readable_content(content)
    assert verify_content(raw,content,text)==[]
    return content,text

def test_source_presentation_navigation_and_milestone_are_structured():
    xml=(f'<div xmlns="{NS}" type="chapter" rend="class:pg" style="margin-left:30%" '
         'prev="#prior" next="#later" xml:space="preserve"><p rend="c21" '
         'rendition="#source-style-34" style="text-align:center">Read '
         '<ref source="LXX" n="1" rend="TOC">Psalm</ref>'
         '<pb n="2" facs="/ccel/Page_2.html"/></p>'
         '<milestone unit="insertIndex" n="scripRef"/></div>')
    content,text=check(xml)
    assert content['attributes']=={'type':'chapter','style':'class:pg','css_style':'margin-left:30%','whitespace':'preserve'}
    assert content['content'][0]['attributes']['rendition']=='#source-style-34'
    assert content['content'][1]['kind']=='source-marker'
    assert content['content'][1]['attributes']=={'number':'scripRef','unit':'insertIndex'}
    assert 'Read Psalm' in text
    tampered=copy.deepcopy(content)
    tampered['content'][1]['attributes']['unit']='scripContext'
    assert 'native structure/text order or attributes differ from source' in verify_content(xml.encode(),tampered,text)


def test_source_blocks_preserve_whitespace_heading_and_placeholder():
    for kind,text_value in [('source-whitespace-line','   '),('source-heading','CHAPTER I'),('source-figure-placeholder','[Illustration]')]:
        content,text=check(f'<ab xmlns="{NS}" type="{kind}" xml:space="preserve" n="1">{text_value}</ab>')
        assert content['kind']=='source-block'
        assert content['attributes']=={'type':kind,'whitespace':'preserve','number':'1'}
        assert content['content'][0]['text']==text_value
        assert text==text_value.strip()


def test_source_verse_block_preserves_number_and_footnote():
    xml=(f'<ab xmlns="{NS}" type="verse" n="8.2">Pray '
         '<note type="footnote" n="1">source note</note> thus.</ab>')
    content,text=check(xml)
    assert content['kind']=='source-block'
    assert content['attributes']=={'type':'verse','number':'8.2'}
    assert content['content'][1]['kind']=='note'
    assert content['content'][1]['content'][0]['text']=='source note'
    assert text=='Pray  thus.'
    mutant=xml.replace('n="8.2"','n="8.3"')
    assert 'native structure/text order or attributes differ from source' in verify_content(mutant.encode(),content,text)


@pytest.mark.parametrize('level', range(1, 7))
def test_ccel_source_heading_level_projects_and_mutation_is_rejected(level):
    xml=f'<ab xmlns="{NS}" type="source-h{level}">Chapter</ab>'
    content,text=check(xml)
    assert content['attributes']=={'type':'source-heading','subtype':str(level)}
    assert text=='Chapter'
    other=1 if level==6 else level+1
    mutant=xml.replace(f'source-h{level}',f'source-h{other}')
    assert 'native structure/text order or attributes differ from source' in verify_content(mutant.encode(),content,text)


def test_ccel_source_heading_conflicting_subtype_fails_closed():
    xml=f'<ab xmlns="{NS}" type="source-h3" subtype="h2">Chapter</ab>'
    with pytest.raises(PipelineError,match='conflicts with subtype'):
        project_content(ET.fromstring(xml))


@pytest.mark.parametrize('style', ['style:margin-top:12pt', 'style:margin-top:48pt'])
def test_ccel_source_heading_style_is_exact_and_checked(style):
    xml=f'<ab xmlns="{NS}" type="source-h2" rend="{style}">Heading</ab>'
    content,text=check(xml)
    assert content['attributes']=={'type':'source-heading','subtype':'2','style':style}
    mutant=xml.replace(style,'style:margin-top:24pt')
    changed,changed_text=check(mutant)
    assert changed['attributes']['style']=='style:margin-top:24pt'
    assert 'native structure/text order or attributes differ from source' in verify_content(mutant.encode(),content,text)
    assert 'native structure/text order or attributes differ from source' in verify_content(xml.encode(),changed,changed_text)


@pytest.mark.parametrize('style', ['', '   ', '\t'])
def test_ccel_source_heading_empty_style_fails_closed(style):
    xml=f'<ab xmlns="{NS}" type="source-h2" rend="{style}">Heading</ab>'
    with pytest.raises(PipelineError,match='unsupported native content attribute'):
        project_content(ET.fromstring(xml))
    assert 'unsupported native attribute' in verify_content(xml.encode(),{},'Heading')[0]


def test_ccel_source_horizontal_rule_maps_to_existing_kind():
    xml=f'<milestone xmlns="{NS}" unit="source-horizontal-rule"/>'
    content,text=check(xml)
    assert content['kind']=='horizontal-rule'
    assert content['attributes']=={}
    mutant=xml.replace('source-horizontal-rule','source-vertical-rule')
    assert 'unsupported native milestone unit' in verify_content(mutant.encode(),content,text)[0]


def test_untyped_prose_block_preserves_split_word_links_and_lemma():
    xml=(f'<ab xmlns="{NS}">The <w xml:id="w1" lemma="sacerdos" '
         'corresp="#w1 #w2">sacer-</w><lb n="1"/>'
         '<w xml:id="w2" lemma="sacerdos" corresp="#w1 #w2">dos</w>.</ab>')
    content,text=check(xml)
    assert content['kind']=='source-block'
    words=[item for item in content['content'] if item['kind']=='word-segment']
    assert len(words)==2
    assert all(word['attributes']=={'lemma':'sacerdos','source_target':'#w1 #w2'} for word in words)
    assert 'sacer-' in text and 'dos' in text
    tampered=copy.deepcopy(content)
    tampered['content'][1]['attributes']['source_target']='#w1 #elsewhere'
    assert 'native structure/text order or attributes differ from source' in verify_content(xml.encode(),tampered,text)
    changed_source=xml.replace('#w1 #w2','#w1 #elsewhere')
    changed,changed_text=check(changed_source)
    changed_words=[item for item in changed['content'] if item['kind']=='word-segment']
    assert len(changed_words)==2
    assert all(word['attributes']['source_target']=='#w1 #elsewhere' for word in changed_words)
    assert 'native structure/text order or attributes differ from source' in verify_content(changed_source.encode(),content,text)
    assert 'native structure/text order or attributes differ from source' in verify_content(xml.encode(),changed,changed_text)


def test_table_cells_and_semantic_names_are_retained():
    content,text=check(f'<table xmlns="{NS}" ana="source-role:table"><row><cell cols="2" style="text-align:center"><p><name key="n1">Robbie</name> <title key="t1">Book</title></p></cell></row></table>')
    assert content['kind']=='table'
    assert content['content'][0]['kind']=='table-row'
    cell=content['content'][0]['content'][0]
    assert cell['attributes']=={'columns':'2','css_style':'text-align:center'}
    assert 'Robbie Book' in text


@pytest.mark.parametrize('xml',[
    f'<milestone xmlns="{NS}" unit="invented"/>',
    f'<ab xmlns="{NS}" type="invented">Text</ab>',
    f'<div xmlns="{NS}" unreviewed="yes"><p>Text</p></div>',
])
def test_unknown_native_semantics_fail_closed(xml):
    with pytest.raises(PipelineError):
        project_content(ET.fromstring(xml))

