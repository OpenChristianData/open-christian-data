"""Source-bound line transcription and unlabelled catechism answer edges."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection import native_content
from ocd_kernel.projection.native_content_check import observe_content
from ocd_kernel.projection.categories.catechisms import (
    UnsupportedStructure, _native_question_answers_et,
)
from ocd_kernel.projection.categories.native_documents import (
    _source_lines_public_shadow,
    select_accepted_source_lines_profile,
)

NS = '{http://www.tei-c.org/ns/1.0}'
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'


def _binding(tmp_path):
    source = tmp_path / 'raw/source.txt'
    source.parent.mkdir()
    source_raw = b'First line\nSecond line\n'
    source.write_bytes(source_raw)
    accounting = tmp_path / 'accounting.json'
    accounting_raw = json.dumps({
        'accepted_body_unchanged': True,
        'source_sha256': hashlib.sha256(source_raw).hexdigest(),
    }).encode()
    accounting.write_bytes(accounting_raw)
    master = tmp_path / 'master.tei.xml'
    master.write_text(
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div>'
        '<head type="source-line" n="1">First line</head>'
        '<ab type="source-line" n="2">Second line</ab>'
        '<ab type="source-line" n="3"></ab>'
        '</div></body></text></TEI>', encoding='utf-8')
    context = {'accepted': {'source': {
        'source_path': 'raw/source.txt', 'source_bytes': len(source_raw),
        'source_sha256': hashlib.sha256(source_raw).hexdigest(),
        'accounting': {'path': 'accounting.json', 'bytes': len(accounting_raw),
                       'sha256': hashlib.sha256(accounting_raw).hexdigest()},
    }}, 'edition': SimpleNamespace(path=master)}
    return context, master


def test_accepted_source_lines_preserve_every_line_and_native_content(tmp_path):
    context, master = _binding(tmp_path)
    profile = select_accepted_source_lines_profile(tmp_path, context)
    assert profile == native_content.SOURCE_LINES_PROFILE
    unit = ET.parse(master).getroot().find('.//' + NS + 'div')
    projected = native_content.project_content(unit, source_profile=profile)
    observed, readable = observe_content(ET.tostring(unit), source_profile=profile)
    assert observed == projected
    assert 'First line' in readable and 'Second line' in readable


def test_accepted_source_lines_reject_changed_master_line(tmp_path):
    context, master = _binding(tmp_path)
    master.write_text(master.read_text(encoding='utf-8').replace('Second line', 'Altered line'), encoding='utf-8')
    with pytest.raises(PipelineError, match='source-line 2 differs'):
        select_accepted_source_lines_profile(tmp_path, context)


def test_unrelated_accounting_returns_before_source_path_resolution(tmp_path):
    context, _ = _binding(tmp_path)
    accounting = tmp_path / 'accounting.json'
    raw = json.dumps({'accepted_body_unchanged': False}).encode()
    accounting.write_bytes(raw)
    context['accepted']['source']['accounting'].update(
        bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    context['accepted']['source']['source_path'] = 'raw/../outside.txt'
    assert select_accepted_source_lines_profile(tmp_path, context) is None


def test_source_line_profile_rejects_escaped_source_path(tmp_path):
    context, _ = _binding(tmp_path)
    context['accepted']['source']['source_path'] = 'raw/../outside.txt'
    with pytest.raises(PipelineError, match='outside configured storage'):
        select_accepted_source_lines_profile(tmp_path, context)


def test_ccel_generator_footer_shadow_prunes_empty_container():
    unit = ET.Element(NS + 'div')
    historical = ET.SubElement(unit, NS + 'div', {'type': 'section'})
    ET.SubElement(historical, NS + 'ab', {'type': 'source-line', 'n': '1'}).text = 'Historic text.'
    footer = ET.SubElement(unit, NS + 'div', {'type': 'section'})
    for number, value in enumerate((
            'This document is from the Christian Classics Ethereal',
            'Library at Calvin College, http://www.ccel.org,',
            'generated on demand from ThML source.', '', 'References', '',
            '1. file:///ccel/some/local/path', ''), 2):
        ET.SubElement(footer, NS + 'ab', {'type': 'source-line', 'n': str(number)}).text = value
    shadow, excluded = _source_lines_public_shadow(unit)
    assert len(shadow) == 1
    assert shadow[0].get('type') == 'section'
    assert shadow[0][0].text == 'Historic text.'
    assert footer in excluded
    assert all(child in excluded for child in footer)
    assert 'file:///' not in ET.tostring(shadow, encoding='unicode')


def _question(first_line):
    question = ET.Element(NS + 'div', {XML_ID: 'qa-1'})
    for number, role, text in (
            (1, 'question', first_line),
            (2, 'question-continuation', 'The answer begins without an A. marker.'),
            (3, 'question-continuation', 'It continues here.')):
        carrier = ET.SubElement(question, NS + 'div', {'type': 'source-line'})
        ET.SubElement(carrier, NS + 'ab', {'type': role, 'n': str(number)}).text = text
    return question


def test_unlabelled_source_answer_has_index_role_without_changing_tei():
    question = _question('Q. 630. Why is there a double punishment?')
    indexed = _native_question_answers_et([question])[0]
    assert [line['role'] for line in indexed['answer_lines']] == ['answer', 'answer']
    assert [line['number'] for line in indexed['answer_lines']] == ['2', '3']
    assert [carrier[0].get('type') for carrier in question][1:] == [
        'question-continuation', 'question-continuation']


def test_unlabelled_answer_requires_complete_question():
    with pytest.raises(UnsupportedStructure, match='question or answer is missing'):
        _native_question_answers_et([_question('Q. 630. Why is there a double punishment')])
