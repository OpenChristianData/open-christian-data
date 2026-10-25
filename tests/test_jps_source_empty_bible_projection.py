"""Closed true-empty verse admission and independent receipt challenges."""
from copy import deepcopy
import json
from pathlib import Path

from lxml import etree
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import bible

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/library-pipeline/categories/bible'
CONTEXT = json.loads((FIXTURE / 'manifest.json').read_text(encoding='utf-8'))['fixtures'][0]['context']
NS = '{http://www.tei-c.org/ns/1.0}'
SPACE = '{http://www.w3.org/XML/1998/namespace}space'


def empty_fixture(tmp_path):
    root = etree.fromstring((FIXTURE / 'kjv-genesis.tei.xml').read_bytes())
    verse = root.find('.//' + NS + 'ab')
    verse.text = None
    verse.set(SPACE, 'preserve')
    return root, verse, tmp_path / 'source-empty.tei.xml'


def save(root, path):
    path.write_bytes(etree.tostring(root, encoding='UTF-8', xml_declaration=True))


def test_true_empty_row_has_source_locator_and_private_marker(tmp_path, monkeypatch):
    root, verse, path = empty_fixture(tmp_path)
    save(root, path)
    output = bible.project_bible_document(path, **CONTEXT)
    assert len(output['rows']) == 3
    assert output['rows'][0]['text'] == ''
    assert output['rows'][0]['locator']['verse'] == '1'
    marker = {'tei_path': output['receipt']['anchors'][0]['tei_path'],
              'reason': 'source-native-blank-verse-slot'}
    assert marker in output['receipt']['warnings']
    bible._validate_rows(output['rows'])  # Actual category schema needs no change.
    monkeypatch.setattr(bible, 'project_bible_document', lambda *a, **k: pytest.fail('producer called'))
    monkeypatch.setattr(bible, '_projection', lambda *a, **k: pytest.fail('producer called'))
    assert bible.verify_bible_document(path, output['rows'], output['receipt'], **CONTEXT) == []


@pytest.mark.parametrize('case', ['no-preserve', 'implicit', 'notes-only', 'nested-empty',
                                  'foreign-namespace', 'extra-attribute', 'meaningful-tail'])
def test_unsupported_empty_forms_fail_in_both_walks(tmp_path, case):
    root, verse, path = empty_fixture(tmp_path)
    if case == 'no-preserve':
        verse.attrib.pop(SPACE)
    elif case == 'implicit':
        verse.attrib.pop('type')
    elif case == 'notes-only':
        etree.SubElement(verse, NS + 'note').text = 'Content omitted from verse text'
    elif case == 'nested-empty':
        etree.SubElement(verse, NS + 'hi', rend='italic').text = ' '
    elif case == 'foreign-namespace':
        verse.tag = '{urn:foreign}ab'
    elif case == 'extra-attribute':
        verse.set('source_empty', 'invented')
    elif case == 'meaningful-tail':
        verse.tail = 'Invented content after the source-empty carrier'
    save(root, path)
    expected_reason = {
        'no-preserve': 'empty Bible verse',
        'implicit': 'empty Bible verse',
        'notes-only': 'empty Bible verse',
        'nested-empty': 'empty Bible verse',
        'foreign-namespace': 'non-TEI element',
        'extra-attribute': 'ab/@source_empty',
        'meaningful-tail': 'loose tail text in div',
    }[case]
    producer_reason = 'loose text in div' if case == 'meaningful-tail' else expected_reason
    with pytest.raises(PipelineError, match='unsupported-visible: ' + producer_reason):
        bible.project_bible_document(path, **CONTEXT)
    errors = bible.verify_bible_document(path, [], {}, **CONTEXT)
    assert len(errors) == 1
    assert errors[0].startswith('unsupported-visible: ' + expected_reason), errors


@pytest.mark.parametrize('case', ['text', 'omission', 'duplication', 'marker', 'locator'])
def test_saved_independent_proof_rejects_empty_row_mutations(tmp_path, monkeypatch, case):
    root, verse, path = empty_fixture(tmp_path)
    save(root, path)
    output = bible.project_bible_document(path, **CONTEXT)
    rows, receipt = deepcopy(output['rows']), deepcopy(output['receipt'])
    if case == 'text':
        rows[0]['text'] = ' '
    elif case == 'omission':
        del rows[0]
    elif case == 'duplication':
        rows.insert(1, deepcopy(rows[0]))
    elif case == 'marker':
        receipt['warnings'] = [w for w in receipt['warnings'] if w['reason'] != 'source-native-blank-verse-slot']
    elif case == 'locator':
        rows[0]['locator']['verse'] = 2
    monkeypatch.setattr(bible, 'project_bible_document', lambda *a, **k: pytest.fail('producer called'))
    monkeypatch.setattr(bible, '_projection', lambda *a, **k: pytest.fail('producer called'))
    assert bible.verify_bible_document(path, rows, receipt, **CONTEXT)


def test_existing_preserved_whitespace_slot_is_unchanged(tmp_path):
    root, verse, path = empty_fixture(tmp_path)
    verse.text = '  \n  '
    save(root, path)
    output = bible.project_bible_document(path, **CONTEXT)
    assert output['rows'][0]['text'] == verse.text
    assert bible.verify_bible_document(path, output['rows'], output['receipt'], **CONTEXT) == []
