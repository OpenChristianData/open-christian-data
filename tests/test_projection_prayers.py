"""Source-defined prayers, explicit office/response evidence, and corruption checks."""
import copy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

from lxml import etree as E
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.prayers import project_prayers_document as project, verify_prayers_document as verify
from build.lib.tei_xsd import compiled_tei_schema

ROOT = Path(__file__).resolve().parents[1]
F = ROOT / 'tests/fixtures/library-pipeline/categories/prayers'
CASES = json.loads((F / 'manifest.json').read_text(encoding='utf-8'))['cases']
NS = {'t': 'http://www.tei-c.org/ns/1.0'}


@pytest.mark.parametrize('invalid', [None, 'duplicate', 'header', 'body-url', 'empty'])
def test_prayer_entry_attribution_keeps_source_context(tmp_path, invalid):
    case = CASES[0]
    tree = E.parse(str(F / case['tei_file']))
    unit = tree.xpath('//t:body/t:div', namespaces=NS)[0]
    note = E.SubElement(unit, '{'+NS['t']+'}note', type='source-attribution')
    E.SubElement(note, '{'+NS['t']+'}seg', type='source-title').text = 'Explicit source work'
    E.SubElement(note, '{'+NS['t']+'}seg', type='source-location').text = 'Page 4'
    ref = E.SubElement(note, '{'+NS['t']+'}ref', type='source-url', target='https://example.org/prayer')
    ref.text = 'Source'
    if invalid == 'duplicate':
        unit.append(copy.deepcopy(note))
    elif invalid == 'header':
        tree.xpath('//t:sourceDesc/t:bibl', namespaces=NS)[0].append(note)
    elif invalid == 'body-url':
        unit.xpath('t:p | t:ab', namespaces=NS)[0].append(ref)
    elif invalid == 'empty':
        note[0].text = ''
    path = tmp_path / 'attribution.xml'
    tree.write(str(path), encoding='utf-8')
    if invalid:
        with pytest.raises(PipelineError):
            project(path, **case['context'])
        assert verify(path, [], {}, **case['context'])
        return
    out = project(path, **case['context'])
    assert out['rows'][0]['provenance'] == {'edition_title':case['context']['edition_title'], 'source_title':'Explicit source work', 'source_location':'Page 4', 'source_url':'https://example.org/prayer'}
    assert 'Explicit source work' not in out['rows'][0]['text']
    assert all('source_title' not in row['provenance'] for row in out['rows'][1:])
    assert verify(path, out['rows'], out['receipt'], **case['context']) == []
    changed = copy.deepcopy(out['rows'])
    changed[0]['provenance']['source_location'] = 'Page 5'
    assert verify(path, changed, out['receipt'], **case['context'])


@pytest.mark.parametrize('attributes', [
    {'cRef':'John.3.16a-4.2b'},
    {'target':'Bible:John.3.16a-4.2b'},
    {'cRef':'John.3.16a-4.2b','target':'https://example.org/source'},
    {'target':'https://example.org/source'},
    {},
])
def test_prayer_reference_normalization_retains_source_attributes(tmp_path, monkeypatch, attributes):
    case = CASES[0]
    tree = E.parse(str(F / case['tei_file']))
    paragraph = tree.xpath('//t:body/t:div/t:p | //t:body/t:div/t:ab', namespaces=NS)[0]
    ref = E.SubElement(paragraph, '{'+NS['t']+'}ref', type='scripture', **attributes)
    ref.text = 'Printed reference label'
    path = tmp_path / 'normalized.xml'
    tree.write(str(path), encoding='utf-8')
    out = project(path, **case['context'])
    record = out['rows'][0]['divisions'][0]['references'][-1]
    assert record['raw'] == 'Printed reference label'
    for key, value in attributes.items():
        assert record[key] == value
    if not attributes:
        assert record['normalization_status'] == 'no-explicit-target'
    elif attributes == {'target':'https://example.org/source'}:
        assert record['normalization_status'] == 'unsupported-explicit-target'
    else:
        assert record['scripture']['normalized'] == 'John.3.16a-John.4.2b'
        assert record['normalization_attribute'] == ('cRef' if 'cRef' in attributes else 'target')
    from ocd_kernel.projection.categories import prayers
    monkeypatch.setattr(prayers, 'normalize_reference_record', lambda *a, **k: pytest.fail('producer called'))
    assert verify(path, out['rows'], out['receipt'], **case['context']) == []
    changed = copy.deepcopy(out['rows'])
    changed[0]['divisions'][0]['references'][-1]['raw'] = 'Invented label'
    assert verify(path, changed, out['receipt'], **case['context'])


class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.parts = []

    def handle_data(self, data): self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == 'img': self.parts.append(dict(attrs)['alt'])


def text(markup):
    parser = Visible(); parser.feed(markup); parser.close()
    return ' '.join(''.join(parser.parts).split())


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_complete_prayers_match_independent_html_oracle(case):
    source = json.loads((F / case['retained_file']).read_text(encoding='utf-8'))
    out = project(F / case['tei_file'], **case['context'])
    for name, digest in case['files'].items(): assert hashlib.sha256((F / name).read_bytes()).hexdigest() == digest
    assert len(out['rows']) == len(source['selected_units'])
    for row, unit in zip(out['rows'], source['selected_units'], strict=True):
        assert row['category'] == 'prayers'
        assert row['locator'] == {'kind': 'prayer', 'title': unit['title']}
        assert row['occasion'] == unit['title']
        assert row['office'] == (source['page_title'] if case['name'] == 'suffrages' else None)
        assert row['rubrics'] == ([source['usage']] if source['usage'] else [])
        if case['name'] == 'collects':
            markup = unit['raw_fragment']
            heading_end = markup.index('</CENTER>') + len('</CENTER>')
            assert text(markup[:heading_end]) == unit['title']
            assert markup[heading_end:] == unit['body_fragment']
            divisions = [{'kind': 'paragraph', 'text': text(markup[heading_end:]), 'speaker': None, 'response_to': None}]
        else:
            lines = re.split(r'<BR>', unit['raw_fragment'], flags=re.I)
            divisions = []
            for i, line in enumerate(lines, 1):
                label = re.search(r'<FONT[^>]*><EM>(Answer|Priest)</EM>\.</FONT>', line)
                speaker = label[1] + '.' if label else None
                whole = text(line)
                assert not speaker or whole.startswith(speaker)
                divisions.append({'kind': 'response' if speaker == 'Answer.' else 'petition', 'text': whole[len(speaker):].strip() if speaker else whole, 'speaker': speaker, 'response_to': i - 1 if speaker == 'Answer.' else None})
            assert len(divisions) == 12
        assert row['divisions'] == divisions
        assert len(divisions) == unit['divisions']
        assert row['text'] == '\n\n'.join((b['speaker'] + ' ' if b['speaker'] else '') + b['text'] for b in divisions)
    assert verify(F / case['tei_file'], out['rows'], out['receipt'], **case['context']) == []


@pytest.mark.requires_local_artifacts
def test_original_html_context_fragments_and_every_byte_are_accounted_for():
    for case in CASES:
        source = json.loads((F / case['retained_file']).read_text(encoding='utf-8'))
        raw = (ROOT / source['source_path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == source['source_sha256']
        assert len(raw) == source['source_bytes']
        title = re.search(rb'<TITLE>(.*?)</TITLE>', raw, re.S | re.I)[1].decode()
        assert text(title) == source['page_title']
        if source['usage']:
            usage = re.search(r'<EM>(To be used before.*?)</EM>', raw.decode(), re.S)[1]
            assert text(usage) == source['usage']
        cursor = 0
        for interval in source['byte_census']:
            assert interval['start'] == cursor
            assert hashlib.sha256(raw[cursor:interval['end']]).hexdigest() == interval['sha256']
            cursor = interval['end']
        assert cursor == len(raw)
        for unit in source['selected_units']:
            assert raw[unit['start']:unit['end']].decode() == unit['raw_fragment']
            assert any(i['start'] == unit['start'] and i['end'] == unit['end'] and i['disposition'] == 'selected-complete-source-unit' for i in source['byte_census'])


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_prayer_tei_passes_bundled_p5(case):
    compiled_tei_schema(ROOT / 'ocd_kernel/tei/vendor/xsd/tei_all.xsd').assertValid(E.parse(str(F / case['tei_file'])))


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
@pytest.mark.parametrize('change', ['omit', 'duplicate', 'order', 'text', 'locator', 'office', 'occasion', 'rubric', 'division', 'speaker', 'response', 'role', 'subjective'])
def test_source_derived_corruption_is_not_hidden_by_consistent_hashes(case, change):
    out = project(F / case['tei_file'], **case['context']); rows = out['rows']; row = rows[0]
    if change == 'omit': rows.pop()
    elif change == 'duplicate': rows.append(copy.deepcopy(rows[-1]))
    elif change == 'order':
        if len(rows) > 1: rows.reverse()
        else: row['divisions'].reverse()
    elif change == 'text': row['text'] += ' Invented words.'
    elif change == 'locator': row['locator']['title'] = 'Invented title'
    elif change == 'office': row['office'] = 'Invented office'
    elif change == 'occasion': row['occasion'] = 'Invented occasion'
    elif change == 'rubric': row['rubrics'] = ['Invented instruction']
    elif change == 'division': row['divisions'].pop()
    elif change == 'speaker': row['divisions'][0]['speaker'] = 'Invented speaker'
    elif change == 'response': row['divisions'][-1]['response_to'] = 99
    elif change == 'role': row['divisions'][0]['kind'] = 'response'
    elif change == 'subjective': row['theme'] = 'Invented theme'
    for i, row in enumerate(rows, 1): row['sequence'] = i
    out['receipt']['row_count'] = len(rows)
    out['receipt']['output_sha256'] = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    for row, anchor in zip(rows, out['receipt']['anchors']): anchor['text_sha256'] = hashlib.sha256(row['text'].encode()).hexdigest()
    assert any('correspondence' in e for e in verify(F / case['tei_file'], rows, out['receipt'], **case['context']))


@pytest.mark.parametrize('field', ['scope', 'mapping_version', 'master_sha256', 'schema_sha256', 'common_schema_sha256', 'output_sha256', 'row_count', 'anchors', 'inventory', 'warnings', 'exclusions', 'unsupported', 'independent_check'])
def test_every_receipt_claim_is_recomputed(field):
    case = CASES[0]; out = project(F / case['tei_file'], **case['context']); out['receipt'][field] = 'forged'
    assert verify(F / case['tei_file'], out['rows'], out['receipt'], **case['context'])


@pytest.mark.parametrize('change', ['table', 'attribute', 'namespace', 'loose', 'duplicate-id', 'response-link', 'role', 'speaker-order', 'empty', 'prolog-pi'])
def test_unsupported_prayer_tei_fails_both_routes(change, tmp_path):
    case = CASES[1]; path = F / case['tei_file']; tree = E.parse(str(path)); unit = tree.xpath('//t:body/t:div', namespaces=NS)[0]; paragraphs = list(unit)
    if change == 'table': E.SubElement(unit, '{' + NS['t'] + '}table')
    elif change == 'attribute': unit.set('ana', 'invented')
    elif change == 'namespace': unit.tag = '{urn:wrong}div'
    elif change == 'loose': unit.text = 'Unmapped text'
    elif change == 'duplicate-id': paragraphs[1].set('{http://www.w3.org/XML/1998/namespace}id', paragraphs[0].get('{http://www.w3.org/XML/1998/namespace}id'))
    elif change == 'response-link': paragraphs[1].set('corresp', '#suffrage-3')
    elif change == 'role': paragraphs[0].set('type', 'devotional')
    elif change == 'speaker-order': paragraphs[1].text = 'Words before speaker'
    elif change == 'empty': paragraphs[0].text = None
    raw = E.tostring(tree)
    if change == 'prolog-pi': raw = b'<?xml-stylesheet hidden?>' + raw
    changed = tmp_path / 'bad.xml'; changed.write_bytes(raw)
    with pytest.raises(PipelineError): project(changed, **case['context'])
    out = project(path, **case['context'])
    assert verify(changed, out['rows'], out['receipt'], **case['context'])


def test_checker_does_not_call_producer(monkeypatch):
    import ocd_kernel.projection.categories.prayers as module
    case = CASES[0]; out = project(F / case['tei_file'], **case['context'])
    monkeypatch.setattr(module, 'project_prayers_document', lambda *a, **k: (_ for _ in ()).throw(AssertionError('producer called')))
    assert verify(F / case['tei_file'], out['rows'], out['receipt'], **case['context']) == []


class SourceStyles(Visible):
    def __init__(self):
        super().__init__(); self.active = []; self.features = []

    def handle_starttag(self, tag, attrs):
        if tag in ('strong', 'i'):
            self.active.append((tag, len(''.join(self.parts))))
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in ('strong', 'i'):
            opened, start = self.active.pop(); assert opened == tag
            full = ''.join(self.parts)
            self.features.append(('bold' if tag == 'strong' else 'italic', ' '.join(full[:start].split()), ' '.join(full[start:].split())))


def assert_source_styles(tree, retained):
    paragraphs = tree.xpath('//t:body/t:div/t:p', namespaces=NS)
    for paragraph, unit in zip(paragraphs, retained['selected_units'], strict=True):
        oracle = SourceStyles(); oracle.feed(unit['body_fragment']); oracle.close()
        chunks, prefixes, actual = [], {}, []
        for event, node in E.iterwalk(paragraph, events=('start', 'end')):
            if event == 'start':
                prefixes[node] = ''.join(chunks)
                if node.text: chunks.append(node.text)
            else:
                if node.tag == '{'+NS['t']+'}hi':
                    actual.append((node.get('rend'), ' '.join(prefixes[node].split()), ' '.join(''.join(node.itertext()).split())))
                if node is not paragraph and node.tail: chunks.append(node.tail)
        assert actual == oracle.features, 'source emphasis attachment differs'


def test_prayer_source_emphasis_is_preserved_and_projection_reports_it():
    case = CASES[0]; retained = json.loads((F/case['retained_file']).read_text(encoding='utf-8')); tree = E.parse(str(F/case['tei_file']))
    assert_source_styles(tree, retained)
    out = project(F/case['tei_file'], **case['context'])
    features = tree.xpath('//t:body//t:hi', namespaces=NS)
    assert len(out['receipt']['warnings']) == len(features) == 4
    assert all(w['reason'] == 'typography-in-readable-text' for w in out['receipt']['warnings'])
    stripped = copy.deepcopy(tree)
    E.strip_tags(stripped, '{'+NS['t']+'}hi')
    with pytest.raises(AssertionError, match='source emphasis attachment'):
        assert_source_styles(stripped, retained)

@pytest.mark.parametrize('mutation', ['none', 'drop', 'reorder', 'move', 'target'])
def test_prayer_scripture_references_preserve_order_and_attachment(tmp_path, mutation):
    case = CASES[0]
    tree = E.parse(str(F / case['tei_file']))
    paragraphs = tree.xpath('//t:body/t:div/t:p', namespaces=NS)
    for label, target in [('Psalm 1:1', 'Ps.1.1'), ('Psalm 2:1', 'Ps.2.1')]:
        ref = E.SubElement(paragraphs[0], '{'+NS['t']+'}ref', type='scripture', cRef=target)
        ref.text = label
        ref.tail = ' '
    path = tmp_path / 'references.xml'
    tree.write(str(path), encoding='utf-8')
    out = project(path, **case['context'])
    expected = [{'raw': 'Psalm 1:1', 'cRef': 'Ps.1.1'}, {'raw': 'Psalm 2:1', 'cRef': 'Ps.2.1'}]
    references = out['rows'][0]['divisions'][0]['references']
    assert [{'raw': ref['raw'], 'cRef': ref['cRef']} for ref in references] == expected
    assert [ref['scripture']['normalized'] for ref in references] == ['Ps.1.1', 'Ps.2.1']
    assert all(ref['normalization_attribute'] == 'cRef' for ref in references)
    assert 'Psalm 1:1 Psalm 2:1' in out['rows'][0]['text']
    assert verify(path, out['rows'], out['receipt'], **case['context']) == []
    rows = copy.deepcopy(out['rows'])
    first = rows[0]['divisions'][0]
    if mutation == 'drop': del first['references']
    elif mutation == 'reorder': first['references'].reverse()
    elif mutation == 'move': rows[1]['divisions'][0]['references'] = first.pop('references')
    elif mutation == 'target': first['references'][0]['cRef'] = 'Ps.1.2'
    if mutation != 'none':
        assert any('prayer correspondence' in error for error in verify(path, rows, out['receipt'], **case['context']))


@pytest.mark.parametrize('attribute,value', [('type','topic'), ('cRef',''), ('target','  ')])
def test_invalid_prayer_reference_fails_both_routes(tmp_path, attribute, value):
    case = CASES[0]
    tree = E.parse(str(F / case['tei_file']))
    paragraph = tree.xpath('//t:body/t:div/t:p', namespaces=NS)[0]
    ref = E.SubElement(paragraph, '{'+NS['t']+'}ref', type='scripture')
    ref.text = 'Psalm 1:1'
    ref.set(attribute, value)
    path = tmp_path / 'invalid-ref.xml'
    tree.write(str(path), encoding='utf-8')
    with pytest.raises(PipelineError, match='reference'):
        project(path, **case['context'])
    original = project(F / case['tei_file'], **case['context'])
    assert any('reference' in error for error in verify(path, original['rows'], original['receipt'], **case['context']))


def test_prayer_reference_typed_encoding_and_old_receipt(tmp_path):
    from ocd_kernel.release.features import configuration_features
    from ocd_kernel.release.typed_rows import encode_rows, check_rows
    case = CASES[0]
    tree = E.parse(str(F / case['tei_file']))
    paragraph = tree.xpath('//t:body/t:div/t:p', namespaces=NS)[0]
    ref = E.SubElement(paragraph, '{'+NS['t']+'}ref', type='scripture', target='https://example.org/psalm#1')
    ref.text = 'Psalm 1'
    path = tmp_path / 'typed-reference.xml'
    tree.write(str(path), encoding='utf-8')
    out = project(path, **case['context'])
    assert out['rows'][0]['divisions'][0]['references'] == [{'raw': 'Psalm 1', 'target': 'https://example.org/psalm#1', 'normalization_attribute': 'target', 'normalization_status': 'unsupported-explicit-target'}]
    features = configuration_features(out['rows'])
    check_rows(encode_rows(out['rows'], features), out['rows'], features)
    out['receipt']['mapping_version'] = 'ocd-prayers-bounded-v1'
    assert verify(path, out['rows'], out['receipt'], **case['context'])
