"""Focused public/private boundary checks for the exact Calvin collection route."""

from collections import Counter
import copy
import xml.etree.ElementTree as ET

import pytest
from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection import native_content
from ocd_kernel.projection.native_content_check import observe_content
from ocd_kernel.projection.categories import calvin_collection_source_native as calvin


TEI = "http://www.tei-c.org/ns/1.0"


def _unit() -> bytes:
    return (f'<div xmlns="{TEI}" type="source-div1" n="i" rend="CCEL-style">'
            '<p n="i-p1">The original <hi rend="s21">commentary</hi> text.</p>'
            '<p>CHRISTIAN CLASSICS ETHEREAL LIBRARY GRAND RAPIDS, MI</p>'
            '<p><ref target="http://www.ccel.org">http://www.ccel.org</ref></p>'
            '<p>A source <ref cRef="Gen.1.1">reference</ref> remains.</p>'
            '<graphic url="../files/cover.jpg" />'
            '</div>').encode('utf-8')


def test_public_shadow_preserves_text_and_reference_without_electronic_layers():
    source = ET.fromstring(_unit())
    original = copy.deepcopy(source)
    removed = Counter()
    public = calvin._public_et(source, removed)
    structure = native_content.project_content(public)
    text = native_content.readable_content(structure)
    assert removed == {'provider-paragraph': 2, 'image-reference': 1}
    assert 'The original' in text and 'reference remains.' in text
    assert 'CCEL' not in text and 'cover.jpg' not in str(structure)
    assert 'Gen.1.1' in str(structure)
    assert 'CCEL-style' not in str(structure) and 'i-p1' not in str(structure)
    assert ET.tostring(source) == ET.tostring(original)
    observed, observed_text = observe_content(etree.tostring(
        calvin._public_lxml(etree.fromstring(_unit()), Counter()),
        encoding='utf-8', with_tail=False))
    assert observed == structure and observed_text == text


@pytest.mark.parametrize('replacement', [
    b'<graphic url="../files/cover.jpg">new caption</graphic>',
    b'<graphic url="../files/cover.jpg" /><p>new caption</p>',
])
def test_graphic_text_cannot_disappear(replacement):
    source = _unit().replace(b'<graphic url="../files/cover.jpg" />', replacement)
    if b'<p>new caption</p>' in replacement:
        # A sibling paragraph is independent text and must be retained.
        public = calvin._public_et(ET.fromstring(source), Counter())
        assert 'new caption' in native_content.readable_content(
            native_content.project_content(public))
    else:
        with pytest.raises(PipelineError, match='visible'):
            calvin._public_et(ET.fromstring(source), Counter())
        with pytest.raises(PipelineError, match='visible'):
            calvin._public_lxml(etree.fromstring(source), Counter())


def test_provider_paragraph_with_visible_tail_is_rejected_by_both_paths():
    source = _unit().replace(
        b'<p>CHRISTIAN CLASSICS ETHEREAL LIBRARY GRAND RAPIDS, MI</p>',
        b'<p>CHRISTIAN CLASSICS ETHEREAL LIBRARY GRAND RAPIDS, MI</p>new words')
    with pytest.raises(PipelineError, match='visible'):
        calvin._public_et(ET.fromstring(source), Counter())
    with pytest.raises(PipelineError, match='visible'):
        calvin._public_lxml(etree.fromstring(source), Counter())


def test_wrong_calvin_acceptance_identity_fails_closed():
    metadata = {'acceptance': {'identity': {'work_id': 'calvin-commentaries',
        'textual_form_id': 'wrong', 'edition_id': 'wrong', 'acquisition_id': 'wrong'}},
        'language': 'en'}
    with pytest.raises(PipelineError, match='exact accepted identity'):
        calvin.route(metadata)


def test_source_reference_number_and_semantic_rendition_survive_private_style_filter():
    raw = (f'<div xmlns="{TEI}" type="source-div1" n="ii" rend="CCEL-style">'
           '<div type="source-div" n="Bible:Gen.1.1" rend="Commentary">'
           '<p n="ii-p2" rend="SCRIPTURE">'
           '<ref type="scripture" n="Genesis 1:1-6" cRef="Gen.1.1-Gen.1.6">Genesis</ref>'
           '<hi rend="italic"> beginning</hi>'
           '<foreign rend="Greek">logos</foreign>'
           '<seg rend="Hebrew">bereshit</seg>'
           '<ref n="ii-p2.1" target="#source-anchor">see</ref>'
           '</p><note><p rend="Footnote">A historical note.</p></note>'
           '</div></div>').encode('utf-8')
    source = ET.fromstring(raw)
    et = calvin._public_et(source, Counter())
    lx = calvin._public_lxml(etree.fromstring(raw), Counter())
    assert et.get('n') == 'ii' and et.get('rend') is None
    division = et[0]
    assert division.get('n') == 'Bible:Gen.1.1' and division.get('rend') == 'Commentary'
    paragraph = division[0]
    assert paragraph.get('n') is None and paragraph.get('rend') == 'SCRIPTURE'
    assert paragraph[0].get('n') == 'Genesis 1:1-6'
    assert paragraph[1].get('rend') == 'italic'
    assert paragraph[2].get('rend') == 'Greek'
    assert paragraph[3].get('rend') == 'Hebrew'
    assert paragraph[4].get('n') is None
    assert division[1][0].get('rend') is None
    structure = native_content.project_content(et)
    observed, text = observe_content(etree.tostring(lx, encoding='utf-8', with_tail=False))
    assert structure == observed
    assert 'Genesis 1:1-6' in str(structure)
    assert 'Bible:Gen.1.1' in str(structure)
    assert 'A historical note.' in str(structure)
    assert 'Genesis' in text
