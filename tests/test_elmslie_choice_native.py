"""Native abbreviation alternatives retain the source reading and expansion."""

from __future__ import annotations

from copy import deepcopy
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.native_content import (
    ELMSLIE_CHOICE_PROFILE, project_content, readable_content,
)
from ocd_kernel.projection.native_content_check import verify_content


NS = "http://www.tei-c.org/ns/1.0"


def _project(fragment: str) -> tuple[bytes, dict, str]:
    raw = f'<p xmlns="{NS}">{fragment}</p>'.encode()
    content = project_content(ET.fromstring(raw), source_profile=ELMSLIE_CHOICE_PROFILE)
    readable = readable_content(content)
    assert verify_content(raw, content, readable, source_profile=ELMSLIE_CHOICE_PROFILE) == []
    return raw, content, readable


def test_choice_keeps_supplied_expansion_without_doubling_source_reading() -> None:
    raw, content, readable = _project(
        'A <choice><abbr>D.D.</abbr><expan>Doctor of Divinity</expan></choice> wrote.'
    )
    choice = content['content'][1]
    assert choice['kind'] == 'abbreviation-choice'
    assert [child['kind'] for child in choice['content']] == ['abbreviated-text', 'supplied-expansion']
    assert choice['content'][1]['content'][0]['text'] == 'Doctor of Divinity'
    assert readable == 'A D.D. wrote.'
    assert 'Doctor of Divinity' not in readable
    changed = deepcopy(content)
    changed['content'][1]['content'][1]['content'][0]['text'] = 'Doctor of Medicine'
    assert verify_content(raw, changed, readable, source_profile=ELMSLIE_CHOICE_PROFILE)


def test_choice_preserves_inline_links_and_order_in_abbreviation() -> None:
    raw, content, readable = _project(
        '<choice><abbr><seg>vol. </seg><ref target="#note">i.</ref></abbr>'
        '<expan>volume 1</expan></choice>'
    )
    assert readable == 'vol. i.'
    abbreviation = content['content'][0]['content'][0]
    assert [child['kind'] for child in abbreviation['content']] == ['segment', 'source-reference']
    changed = deepcopy(content)
    changed['content'][0]['content'][0]['content'].reverse()
    assert verify_content(raw, changed, readable, source_profile=ELMSLIE_CHOICE_PROFILE)


@pytest.mark.parametrize('fragment', [
    '<choice><expan>full</expan><abbr>x.</abbr></choice>',
    '<choice><abbr>x.</abbr></choice>',
    '<choice><abbr>x.</abbr><expan>full</expan><expan>again</expan></choice>',
    '<choice><abbr></abbr><expan>full</expan></choice>',
    '<choice><abbr>x.</abbr><expan></expan></choice>',
    '<choice>extra<abbr>x.</abbr><expan>full</expan></choice>',
    '<choice><abbr>x.</abbr>extra<expan>full</expan></choice>',
    '<choice><abbr>x.</abbr><expan><hi>full</hi></expan></choice>',
    '<choice><abbr>x.</abbr><expan type="invented">full</expan></choice>',
    '<choice type="invented"><abbr>x.</abbr><expan>full</expan></choice>',
])
def test_malformed_choice_fails_both_producer_and_checker(fragment: str) -> None:
    raw = f'<p xmlns="{NS}">{fragment}</p>'.encode()
    with pytest.raises(PipelineError):
        project_content(ET.fromstring(raw), source_profile=ELMSLIE_CHOICE_PROFILE)
    assert verify_content(raw, {}, '', source_profile=ELMSLIE_CHOICE_PROFILE)


def test_source_titled_choice_works_without_elmslie_profile() -> None:
    raw = f'<p xmlns="{NS}">See <choice><abbr n="source-html-class:spell">ii.</abbr><expan>two</expan></choice> 6.</p>'.encode()
    content = project_content(ET.fromstring(raw))
    readable = readable_content(content)
    assert readable == 'See ii. 6.'
    assert content['content'][1]['content'][1]['content'][0]['text'] == 'two'
    assert 'number' not in content['content'][1]['content'][0]['attributes']
    assert verify_content(raw, content, readable) == []
    changed = deepcopy(content)
    changed['content'][1]['content'][1]['content'][0]['text'] = 'three'
    assert verify_content(raw, changed, readable)


def test_malformed_unprofiled_choice_fails_both_sides() -> None:
    raw = f'<p xmlns="{NS}"><choice><abbr>ii.</abbr><expan><hi>two</hi></expan></choice></p>'.encode()
    with pytest.raises(PipelineError):
        project_content(ET.fromstring(raw))
    assert verify_content(raw, {}, '')


def test_unknown_abbreviation_source_class_fails_both_sides() -> None:
    raw = f'<p xmlns="{NS}"><choice><abbr n="source-html-class:other">ii.</abbr><expan>two</expan></choice></p>'.encode()
    with pytest.raises(PipelineError, match='unsupported abbreviation source class'):
        project_content(ET.fromstring(raw))
    assert verify_content(raw, {}, '')


def test_standalone_expansion_contract_is_unchanged() -> None:
    raw = f'<p xmlns="{NS}"><expan><am>x</am><ex>panded</ex></expan></p>'.encode()
    content = project_content(ET.fromstring(raw))
    assert readable_content(content) == 'panded'
    assert verify_content(raw, content, 'panded') == []
    invalid = f'<p xmlns="{NS}"><expan>expanded</expan></p>'.encode()
    with pytest.raises(PipelineError, match='ordered abbreviation'):
        project_content(ET.fromstring(invalid))
