"""Retain a source inline carrier placed directly in a source division."""
import copy
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.native_content import project_content, readable_content
from ocd_kernel.projection.native_content_check import observe_content, verify_content


NS = 'http://www.tei-c.org/ns/1.0'


def test_empty_confessions_commentary_container_retains_child_and_tail(monkeypatch):
    # Literal accepted vi.XI-p0.1: an empty source scripCom plus two newlines.
    raw = (f'<ab xmlns="{NS}" xml:id="lib040-inline-container-04727" '
           'type="source-inline-container"><ref xml:id="lib040-npnf101-vi.XI-p0.1" '
           'target="Bible:Gen.1" cRef="Genesis 1" type="scripture-commentary"/>\n\n</ab>').encode()
    content = project_content(ET.fromstring(raw))
    text = readable_content(content)
    assert content == {
        'kind': 'source-block', 'attributes': {'type': 'source-inline-container'},
        'content': [
            {'kind': 'source-reference', 'attributes': {
                'source_target': 'Bible:Gen.1', 'canonical_reference': 'Genesis 1',
                'type': 'scripture-commentary'}, 'content': []},
            {'kind': 'text', 'text': '\n\n'},
        ],
    }
    assert text == ''
    import ocd_kernel.projection.native_content as producer
    monkeypatch.setattr(producer, 'project_content', lambda *args: pytest.fail('producer called'))
    monkeypatch.setattr(producer, 'readable_content', lambda *args: pytest.fail('renderer called'))
    assert verify_content(raw, content, text) == []
    missing = copy.deepcopy(content)
    missing['content'].pop(0)
    assert verify_content(raw, missing, text)


@pytest.mark.parametrize('change', ['wrapper', 'target', 'tail', 'order'])
def test_inline_container_mixed_content_mutations_are_detected(change, monkeypatch):
    raw = (f'<ab xmlns="{NS}" type="source-inline-container">Before '
           '<ref target="Bible:Gen.1" cRef="Genesis 1" type="scripture-commentary">'
           'Genesis</ref> after.\n\n</ab>').encode()
    content = project_content(ET.fromstring(raw))
    text = readable_content(content)
    assert text == 'Before Genesis after.'
    import ocd_kernel.projection.native_content as producer
    monkeypatch.setattr(producer, 'project_content', lambda *args: pytest.fail('producer called'))
    monkeypatch.setattr(producer, 'readable_content', lambda *args: pytest.fail('renderer called'))
    assert verify_content(raw, content, text) == []
    altered = copy.deepcopy(content)
    if change == 'wrapper':
        altered = altered['content'][1]
    elif change == 'target':
        altered['content'][1]['attributes']['source_target'] = 'Bible:Gen.2'
    elif change == 'tail':
        altered['content'][2]['text'] = ' changed.\n\n'
    else:
        altered['content'].reverse()
    assert verify_content(raw, altered, text)


def test_unknown_inline_container_type_still_fails_closed():
    raw = f'<ab xmlns="{NS}" type="source-inline-container-invented">Text</ab>'.encode()
    with pytest.raises(PipelineError, match='unsupported native source block type'):
        project_content(ET.fromstring(raw))
    with pytest.raises(ValueError, match='unsupported native source block type'):
        observe_content(raw)
