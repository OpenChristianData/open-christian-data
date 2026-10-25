"""Ryle foreign source-pointer projection regression checks."""
import copy
import xml.etree.ElementTree as ET
from urllib.parse import quote

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.native_content import project_content, readable_content
from ocd_kernel.projection.native_content_check import observe_content, verify_content


@pytest.mark.parametrize(
    ('source_id', 'source_xpath', 'literal'),
    [
        ('iii.i-p5.1', '/ThML[1]/ThML.body[1]/div1[3]/div2[1]/p[5]/i[1]/span[1]', 'quam longissime'),
        ('iii.xvii-p33.1', '/ThML[1]/ThML.body[1]/div1[3]/div2[18]/p[32]/span[1]', 'Quicquid fecit valdé fecit.'),
    ],
)
def test_ryle_foreign_source_pointer_stays_private_but_language_and_text_survive(
    source_id, source_xpath, literal,
):
    pointer = 'urn:source-xpath:' + quote(source_xpath, safe='')
    raw = (
        '<p xmlns="http://www.tei-c.org/ns/1.0">'
        f'<foreign xml:id="{source_id}" corresp="{pointer}" xml:lang="la">{literal}</foreign>'
        '</p>'
    ).encode('utf-8')
    projected = project_content(ET.fromstring(raw))
    observed, observed_text = observe_content(raw)
    assert projected == observed
    assert projected['content'][0] == {
        'kind': 'foreign-text',
        'attributes': {'language': 'la'},
        'content': [{'kind': 'text', 'text': literal}],
    }
    assert literal == observed_text == readable_content(projected)
    assert pointer not in str(projected)
    assert verify_content(raw, projected, observed_text) == []

    altered = copy.deepcopy(projected)
    altered['content'][0]['attributes']['language'] = 'fr'
    assert verify_content(raw, altered, observed_text)
    altered = copy.deepcopy(projected)
    altered['content'][0]['content'][0]['text'] = 'changed'
    assert verify_content(raw, altered, observed_text)

    invalid = raw.replace(b' corresp=', b' unsupported=')
    with pytest.raises(PipelineError, match='unsupported native content attribute'):
        project_content(ET.fromstring(invalid))
    assert verify_content(invalid, projected, observed_text)


def test_ryle_poetry_wrapper_preserves_source_style_and_stanza():
    raw = (
        '<ab xmlns="http://www.tei-c.org/ns/1.0" xml:id="iii.iii-p72.1" '
        'corresp="urn:source-xpath:%2FThML%5B1%5D%2FThML.body%5B1%5D%2Fdiv1%5B3%5D%2Fdiv2%5B3%5D%2Fdiv%5B1%5D" '
        'rend="margin-left:15%; margin-top:12pt" type="poetry">'
        '<lg type="stanza"><l rend="t1">Nothing in my hand I bring, </l>'
        '<l rend="t1">Simply to Thy cross I cling;</l></lg></ab>'
    ).encode('utf-8')
    projected = project_content(ET.fromstring(raw))
    observed, observed_text = observe_content(raw)
    assert projected == observed
    assert projected['kind'] == 'source-block'
    assert projected['attributes'] == {
        'type': 'poetry', 'style': 'margin-left:15%; margin-top:12pt',
    }
    assert projected['content'][0]['kind'] == 'verse-group'
    assert [line['kind'] for line in projected['content'][0]['content']] == [
        'verse-line', 'verse-line',
    ]
    assert 'Nothing in my hand I bring' in observed_text
    assert verify_content(raw, projected, observed_text) == []

    altered = copy.deepcopy(projected)
    altered['attributes']['style'] = 'margin-left:0'
    assert verify_content(raw, altered, observed_text)
    altered = copy.deepcopy(projected)
    altered['content'][0]['content'].pop()
    assert verify_content(raw, altered, observed_text)
