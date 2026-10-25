"""Literal sic/corr alternatives remain distinct from abbreviation choices."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from lxml import etree, html
import pytest
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection import native_content
from ocd_kernel.projection.native_content import project_content, readable_content
from ocd_kernel.projection.native_content_check import verify_content, observe_content

NS='http://www.tei-c.org/ns/1.0'
ROOT=Path(__file__).resolve().parents[1]
def project(fragment):
    raw=f'<p xmlns="{NS}">{fragment}</p>'.encode()
    content=project_content(ET.fromstring(raw));text=readable_content(content)
    assert verify_content(raw,content,text)==[]
    return raw,content,text

def test_plain_correction_retains_original_and_source_visible_reading():
    raw,content,text=project('The <choice><sic>rendred</sic><corr>rendered</corr></choice> Lives.')
    c=content['content'][1]
    assert c['kind']=='correction-choice'
    assert [x['kind'] for x in c['content']]==['original-text','corrected-text']
    assert c['content'][0]['content'][0]['text']=='rendred'
    assert text=='The rendered Lives.'

def test_mixed_italic_reference_and_choice_whitespace_are_preserved():
    raw,c,text=project('<choice>\n <sic>literal source annotation</sic>\n <corr>the <hi rend="italic">closing</hi> of <ref target="#Page_329">329</ref> Eyes</corr>\n</choice>')
    assert text=='the closing of 329 Eyes'
    choice=c['content'][0]
    assert choice['content'][0]=={'kind':'text','text':'\n '}
    corr=choice['content'][3]
    assert [n['kind'] for n in corr['content']]==['text','emphasis','text','source-reference','text']
    assert corr['content'][3]['attributes']['source_target']=='#Page_329'

@pytest.mark.parametrize('fragment',[
    '<choice><corr>new</corr><sic>old</sic></choice>',
    '<choice><sic>old</sic></choice>',
    '<choice><sic>old</sic><corr>new</corr><corr>again</corr></choice>',
    '<choice><sic/><corr>new</corr></choice>',
    '<choice><sic>old</sic><corr/></choice>',
    '<choice>invented<sic>old</sic><corr>new</corr></choice>',
    '<choice><sic>old</sic>invented<corr>new</corr></choice>',
    '<choice type="invented"><sic>old</sic><corr>new</corr></choice>',
    '<choice><sic type="invented">old</sic><corr>new</corr></choice>',
    '<choice><sic>old</sic><corr type="invented">new</corr></choice>',
    '<choice><sic><hi rend="italic">old</hi></sic><corr>new</corr></choice>',
    '<choice><sic>old</sic><corr><p>new</p></corr></choice>',
    '<choice><sic>old</sic><corr><choice><sic>a</sic><corr>b</corr></choice></corr></choice>',
    '<choice><sic>old</sic><corr><hi rend="bold">new</hi></corr></choice>',
    '<choice><sic>old</sic><corr><hi rend="italic" n="x">new</hi></corr></choice>',
    '<choice><sic>old</sic><corr><hi rend="italic"><hi>new</hi></hi></corr></choice>',
    '<choice><sic>old</sic><corr><ref target="https://example.org">new</ref></corr></choice>',
    '<choice><sic>old</sic><corr><ref target="#p" type="invented">new</ref></corr></choice>',
    '<sic>old</sic><corr>new</corr>',
    '<sic>old</sic>',
    '<corr>new</corr>',
])
def test_malformed_correction_fails_both_routes(fragment):
    raw=f'<p xmlns="{NS}">{fragment}</p>'.encode()
    with pytest.raises(PipelineError):project_content(ET.fromstring(raw))
    assert verify_content(raw,{},'')

@pytest.mark.parametrize('mutation',['original','corrected','omit-original','reorder','target','flatten'])
def test_independent_saved_structure_mutations_rejected(mutation,monkeypatch):
    raw,c,text=project('<choice><sic>old</sic><corr><ref target="#Page_329">329</ref></corr></choice>')
    changed=deepcopy(c);choice=changed['content'][0]
    if mutation=='original':choice['content'][0]['content'][0]['text']='invented'
    elif mutation=='corrected':choice['content'][1]['content'][0]['content'][0]['text']='330'
    elif mutation=='omit-original':choice['content'].pop(0)
    elif mutation=='reorder':choice['content'].reverse()
    elif mutation=='target':choice['content'][1]['content'][0]['attributes']['source_target']='#Page_330'
    else:changed['content']=[{'kind':'text','text':text}]
    def disabled(*args,**kwargs):raise AssertionError('producer called by independent checker')
    monkeypatch.setattr(native_content,'project_content',disabled)
    assert verify_content(raw,c,text)==[]
    assert verify_content(raw,changed,text)
    assert verify_content(raw,c,'old')

def test_all_139_actual_source_choices_and_variants_remain_literal():
    source=ROOT/'raw/clean-ready-acquisition-to-tei/master-4/28/barclay-apology-true-christian-divinity/56487-h.htm'
    master=ROOT/'library/works/barclay-apology-true-christian-divinity/forms/barclay-apology-true-christian-divinity-gutenberg-retained-en/editions/barclay-apology-true-christian-divinity-gutenberg-electronic/master.tei.xml'
    assert sha256(source.read_bytes()).hexdigest()=='0e28cb9ff0b8e9063337c06337d702048df463fd4f50ed11a7517bd7940b4874'
    assert sha256(master.read_bytes()).hexdigest()=='fbaaa5e50d8e66cf8036532c11236f50144e809f9ec67f715380d21ef8bdb427'
    spans=html.fromstring(source.read_bytes()).xpath('//span[contains(concat(" ",normalize-space(@class)," ")," correction ")]')
    choices=etree.fromstring(master.read_bytes()).findall('.//{'+NS+'}choice')
    assert len(spans)==len(choices)==139
    hi=refs=annotations=0
    for span,choice in zip(spans,choices,strict=True):
        title=span.get('title');original=title
        for prefix in ('In the original book: ','Erratum: originally: '):
            if title.startswith(prefix):original=title[len(prefix):];break
        else:annotations+=1
        normalize=lambda s:re.sub(r'\s+',' ',s).strip()
        assert normalize(''.join(choice[0].itertext()))==normalize(original)
        assert normalize(''.join(choice[1].itertext()))==normalize(''.join(span.itertext()))
        hi+=len(choice[1].findall('{'+NS+'}hi'));refs+=len(choice[1].findall('{'+NS+'}ref'))
        fragment=etree.tostring(choice,with_tail=False)
        content=project_content(ET.fromstring(fragment));text=readable_content(content)
        observed,reading=observe_content(fragment)
        assert (observed,reading)==(content,text)
        assert text==normalize(''.join(span.itertext()))
        assert verify_content(fragment,content,text)==[]
    assert (hi,refs,annotations)==(24,2,4)
