"""Source-native mixing survives export independently of plain-text rendering."""
import copy
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.native_content import project_content, readable_content
from ocd_kernel.projection.native_content_check import verify_content
from ocd_kernel.projection.categories.prose import _uses_native_content


def fragment(inner):
    return ('<p xmlns="http://www.tei-c.org/ns/1.0">' + inner + '</p>').encode()


def test_lib031_source_span_routes_to_native_and_checks_its_role(tmp_path):
    raw = fragment('Before <seg type="thml-span">preserved <ref target="#local">link</ref></seg> after.')
    projected = project_content(ET.fromstring(raw))
    readable = readable_content(projected)
    assert projected['content'][1]['attributes']['type'] == 'thml-span'
    assert readable == 'Before preserved link after.'
    assert verify_content(raw, projected, readable) == []
    changed = copy.deepcopy(projected)
    changed['content'][1]['attributes']['type'] = 'different-role'
    assert verify_content(raw, changed, readable)

    template = '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader/><text><body><div><p>{}</p></div></body></text></TEI>'
    selected = tmp_path / 'lib031.xml'
    selected.write_text(template.format('<seg type="thml-span">retained</seg>'), encoding='utf-8')
    assert _uses_native_content(selected)
    selected.write_text(template.format('<seg type="other-role">retained</seg>'), encoding='utf-8')
    assert not _uses_native_content(selected)
    selected.write_text(template.format('<index/>'), encoding='utf-8')
    assert _uses_native_content(selected)


def test_verse_and_list_inside_paragraph_retain_order_and_boundaries(monkeypatch):
    raw = fragment('Before <q><lg><l>First line</l><l>Second line</l></lg></q> between <list><item>One</item><item>Two</item></list> after.')
    tree = project_content(ET.fromstring(raw))
    text = readable_content(tree)
    assert [node['kind'] for node in tree['content']] == ['text', 'quotation', 'text', 'list', 'text']
    assert tree['content'][1]['content'][0]['content'][1]['kind'] == 'verse-line'
    assert 'First line\nSecond line' in text
    assert text.index('Before') < text.index('First line') < text.index('between') < text.index('One') < text.index('after.')
    import ocd_kernel.projection.native_content as producer
    monkeypatch.setattr(producer, 'project_content', lambda *args: pytest.fail('producer called'))
    monkeypatch.setattr(producer, 'readable_content', lambda *args: pytest.fail('renderer called'))
    assert verify_content(raw, tree, text) == []
    for change in ('omit', 'reorder', 'text'):
        mutated = copy.deepcopy(tree)
        if change == 'omit':
            mutated['content'].pop(1)
        elif change == 'reorder':
            mutated['content'].reverse()
        else:
            mutated['content'][0]['text'] = 'Changed'
        assert verify_content(raw, mutated, text)


def test_glyph_gap_and_expansion_use_explicit_source_evidence():
    raw = fragment('water<g ref="char:EOLhyphen"/>bury<g ref="char:punc"/> <gap reason="illegible" extent="1 word"><desc>UNKNOWN</desc></gap> <expan><am><g ref="char:abque"/></am><ex>que</ex></expan>')
    tree = project_content(ET.fromstring(raw))
    text = readable_content(tree)
    assert text == 'water{-}bury{.} UNKNOWN que'
    assert verify_content(raw, tree, text) == []
    assert verify_content(raw, tree, text.replace('{-}', ''))


def test_literal_native_glyph_takes_precedence_over_default_mapping():
    raw = fragment('word<g ref="char:punc">▪</g> next')
    tree = project_content(ET.fromstring(raw))
    text = readable_content(tree)
    assert text == 'word▪ next'
    assert verify_content(raw, tree, text) == []
    assert verify_content(raw, tree, text.replace('▪', '{.}'))


def test_source_ids_facsimiles_and_notes_do_not_leak_into_readable_text():
    raw = fragment('A<note place="margin">Retained note</note> B<pb facs="raw/private.png" xml:id="page1"/> C')
    tree = project_content(ET.fromstring(raw))
    assert 'raw/private.png' not in str(tree)
    assert 'Retained note' in str(tree)
    text = readable_content(tree)
    assert 'Retained note' not in text
    assert verify_content(raw, tree, text) == []


@pytest.mark.parametrize('inner', ['<g ref="char:unknown"/>', '<gap/>', '<pb>lost text</pb>', '<p unexpected="x">Text</p>', '<unknown/>', '<expan><ex>invented</ex></expan>'])
def test_unknown_or_ambiguous_native_features_fail_closed(inner):
    raw = fragment(inner)
    with pytest.raises(PipelineError):
        project_content(ET.fromstring(raw))
    assert verify_content(raw, {}, '')


def test_references_preserve_literal_targets_without_resolving_or_rebasing():
    raw = fragment('See <ref type="scripture" cRef="John 1:1" target="Bible:John.1.1">John</ref> and <ref target="?scrBook=John&amp;scrCh=1&amp;scrV=1#ii">the verse</ref>.')
    tree = project_content(ET.fromstring(raw))
    text = readable_content(tree)
    refs = [node for node in tree['content'] if node['kind'] == 'source-reference']
    assert refs[0]['attributes'] == {
        'type': 'scripture', 'canonical_reference': 'John 1:1',
        'source_target': 'Bible:John.1.1',
    }
    assert refs[1]['attributes']['source_target'] == '?scrBook=John&scrCh=1&scrV=1#ii'
    assert text == 'See John and the verse.'
    assert verify_content(raw, tree, text) == []
    for change in ('target', 'omit', 'reorder'):
        altered = copy.deepcopy(tree)
        if change == 'target':
            altered['content'][1]['attributes']['source_target'] = 'https://example.org/John.1.1'
        elif change == 'omit':
            altered['content'].pop(1)
        else:
            altered['content'][1], altered['content'][3] = altered['content'][3], altered['content'][1]
        assert verify_content(raw, altered, text)


def test_expositor_source_base_and_target_remain_separate_and_source_bound(monkeypatch):
    base = 'https://www.ccel.org/ccel/plummer/expositorjamesjude.html'
    target = '?scrBook=Jas&scrCh=1&scrV=1#iii.i-p3.1'
    raw = fragment('See <ref xml:base="' + base + '" target="' + target.replace('&', '&amp;') + '">James</ref> now.')
    tree = project_content(ET.fromstring(raw), source_base=base)
    text = readable_content(tree)
    assert text == 'See James now.'
    assert tree['content'][1]['attributes'] == {'source_base': base, 'source_target': target}
    import ocd_kernel.projection.native_content as producer
    monkeypatch.setattr(producer, 'project_content', lambda *args, **kwargs: pytest.fail('producer called'))
    assert verify_content(raw, tree, text, source_base=base) == []
    for change in ('base', 'target', 'omit_base', 'omit_target', 'move'):
        altered = copy.deepcopy(tree)
        attrs = altered['content'][1]['attributes']
        if change == 'base':
            attrs['source_base'] = base.replace('plummer', 'other')
        elif change == 'target':
            attrs['source_target'] = target.replace('scrV=1', 'scrV=2')
        elif change == 'omit_base':
            del attrs['source_base']
        elif change == 'omit_target':
            del attrs['source_target']
        else:
            altered['content'][0], altered['content'][1] = altered['content'][1], altered['content'][0]
        assert verify_content(raw, altered, text, source_base=base)
    assert verify_content(raw, tree, text, source_base=base.replace('plummer', 'other'))
    for change in ('other_base', 'missing_base', 'other_target', 'unknown_attribute'):
        source = ET.fromstring(raw)
        ref = source[0]
        if change == 'other_base':
            ref.set('{http://www.w3.org/XML/1998/namespace}base', base.replace('plummer', 'other'))
        elif change == 'missing_base':
            del ref.attrib['{http://www.w3.org/XML/1998/namespace}base']
        elif change == 'other_target':
            ref.set('target', target.replace('scrV=1', 'scrV=2'))
        else:
            ref.set('unexpected', 'x')
        changed_raw = ET.tostring(source)
        if change in ('other_base', 'unknown_attribute'):
            with pytest.raises(PipelineError):
                project_content(source, source_base=base)
        else:
            project_content(source, source_base=base)
        assert verify_content(changed_raw, tree, text, source_base=base)


def test_figure_text_and_abbreviations_preserve_source_without_expansion():
    raw = fragment('Before<figure><head>Portrait</head><p>Olaudah <abbr>Esq</abbr></p><q>Caption</q><gap reason="omitted"><desc>Image not supplied</desc></gap></figure>After')
    tree = project_content(ET.fromstring(raw))
    text = readable_content(tree)
    assert tree['content'][1]['kind'] == 'figure'
    assert tree['content'][1]['content'][1]['content'][1]['kind'] == 'abbreviated-text'
    assert 'Esq' in text and 'Esquire' not in text
    assert 'Image not supplied' in text
    assert verify_content(raw, tree, text) == []
    altered = copy.deepcopy(tree)
    altered['content'][1]['content'].pop()
    assert verify_content(raw, altered, text)
    assert verify_content(raw, tree, text.replace('Esq', 'Esquire'))


def test_empty_markers_and_source_rendition_survive_export():
    raw = fragment('Before<milestone unit="horizontal-rule"/><index/>After <q rend="inline margQuotes">quote</q><gap rend="••" reason="illegible"><desc>two letters</desc></gap><pb rend="source-MS-y"/>')
    tree = project_content(ET.fromstring(raw))
    text = readable_content(tree)
    assert tree['content'][1]['kind'] == 'horizontal-rule'
    assert tree['content'][2]['kind'] == 'index-marker'
    assert tree['content'][4]['attributes']['style'] == 'inline margQuotes'
    assert tree['content'][5]['attributes']['style'] == '••'
    assert 'source-MS-y' not in str(tree)
    assert text.startswith('Before\n\nAfter')
    assert verify_content(raw, tree, text) == []
    altered = copy.deepcopy(tree)
    altered['content'].pop(2)
    assert verify_content(raw, altered, text)


@pytest.mark.parametrize('inner', ['<milestone unit="chapter"/>', '<milestone unit="horizontal-rule">text</milestone>', '<index><p>index content</p></index>'])
def test_unimplemented_marker_semantics_fail_closed(inner):
    raw = fragment(inner)
    with pytest.raises(PipelineError):
        project_content(ET.fromstring(raw))
    assert verify_content(raw, {}, '')


def test_empty_illegibility_gap_keeps_supplied_marker():
    raw = fragment('wo<gap reason="illegible" extent="1 letter" rend="•"/>d')
    tree = project_content(ET.fromstring(raw))
    assert readable_content(tree) == 'wo•d'
    assert verify_content(raw, tree, 'wo•d') == []
    assert verify_content(raw, tree, 'word')
    assert verify_content(raw, tree, 'wod')
    for attribute in ('reason', 'extent', 'rend'):
        element = ET.fromstring(raw)
        del element[0].attrib[attribute]
        with pytest.raises(PipelineError):
            project_content(element)


def test_source_image_reference_description_and_annotations_are_preserved():
    raw = fragment('<p corresp="urn:private:observation" ana="epub:z3998:author">An <emph>emphasis</emph>.</p><figure><graphic url="../images/titlepage.svg"/><figDesc>Source caption.</figDesc></figure><lg type="stanza"><l n="2">Second line</l></lg>')
    tree = project_content(ET.fromstring(raw))
    text = readable_content(tree)
    assert 'private:observation' not in str(tree)
    assert tree['content'][0]['attributes']['source_annotations'] == 'epub:z3998:author'
    figure = tree['content'][1]
    assert figure['content'][0] == {'kind': 'image-reference', 'attributes': {'source_target': '../images/titlepage.svg'}, 'content': []}
    assert 'Source caption.' in text and 'images/' not in text
    assert verify_content(raw, tree, text) == []
    for change in ('target', 'caption', 'annotation', 'number', 'omission'):
        changed = copy.deepcopy(tree)
        if change == 'target':
            changed['content'][1]['content'][0]['attributes']['source_target'] = 'https://example.org/replacement.svg'
        elif change == 'caption':
            changed['content'][1]['content'][1]['content'][0]['text'] = 'Invented caption.'
        elif change == 'annotation':
            changed['content'][0]['attributes']['source_annotations'] = 'epub:z3998:translator'
        elif change == 'number':
            changed['content'][2]['content'][0]['attributes']['number'] = '3'
        else:
            changed['content'].pop(1)
        assert verify_content(raw, changed, text)


@pytest.mark.parametrize('inner', ['<graphic/>', '<graphic url=""/>', '<graphic url="a.svg">invented</graphic>', '<graphic url="a.svg"><p>invented</p></graphic>'])
def test_ambiguous_image_reference_fails_closed(inner):
    raw = fragment(inner)
    with pytest.raises(PipelineError):
        project_content(ET.fromstring(raw))
    assert verify_content(raw, {}, '')
