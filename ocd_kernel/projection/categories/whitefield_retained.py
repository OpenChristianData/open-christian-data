"""Source-native public sermon rows for the two retained Whitefield selections.

The TEI remains the complete reconstruction. This mapping only selects readable
sermon prose; its receipt accounts for every non-row carrier in the edition.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.sermons import _schema

NS = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'
VERSION = 'ocd-whitefield-retained-selections-v1'
EDITIONS = {
    'george-whitefield-sermons-ccel-retained-electronic': ('ccel', 59),
    'george-whitefield-sermons-gutenberg-retained-electronic': ('gutenberg', 2),
}


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _normal(value: str) -> str:
    return ' '.join(value.split())


def _source_attrs(node: ET.Element) -> tuple[str, dict[str, str]]:
    try:
        data = json.loads(node.get('n') or '')
        return data['source_tag'], dict(data['source_attributes'])
    except (ValueError, TypeError, KeyError) as exc:
        raise PipelineError('Whitefield source attribute ledger differs') from exc


def _block(kind: str, value: str) -> dict:
    return {'kind': kind, 'number': None, 'text': value, 'notes': [], 'references': [], 'children': []}


def _ccel_rows(wrapper: ET.Element) -> tuple[list[dict], list[dict]]:
    carriers = list(wrapper.findall(NS+'div'))
    if len(carriers) != 62:
        raise PipelineError('Whitefield CCEL carrier count differs')
    rows, exclusions = [], []
    for position, carrier in enumerate(carriers, 1):
        tag, attrs = _source_attrs(carrier)
        if tag != 'div1' or attrs.get('id') is None:
            raise PipelineError('Whitefield CCEL carrier identity differs')
        if position in (1, 2, 62):
            exclusions.append({'carrier': attrs['id'], 'reason': {1: 'title-page', 2: 'contents', 62: 'indexes'}[position]})
            continue
        blocks = []
        for node in carrier.iter():
            if node is carrier or node.tag not in (NS+'p', NS+'ab'):
                continue
            source_tag, source = _source_attrs(node)
            if source_tag not in ('p', 'h1', 'h2', 'h3', 'h4', 'scripCom', 'scripRef', 'insertIndex'):
                raise PipelineError(f'unsupported Whitefield CCEL source block: {source_tag}')
            value = _normal(''.join(node.itertext()))
            if value:
                kind = 'paragraph' if source_tag == 'p' else 'heading' if source_tag.startswith('h') else 'scripture-reference'
                blocks.append(_block(kind, value))
        if not blocks:
            raise PipelineError('Whitefield CCEL sermon has no readable blocks')
        title = attrs.get('title', '')
        if not title:
            raise PipelineError('Whitefield CCEL sermon title is missing')
        passage = None
        for node in carrier.iter(NS+'ab'):
            source_tag, source = _source_attrs(node)
            if source_tag == 'scripCom' and source.get('type') == 'Sermon':
                passage = source.get('passage')
                break
        rows.append({'unit_id': carrier.get(XML+'id'), 'number': attrs.get('n'),
                     'heading': re.sub(r'^\d+\.\s*', '', title), 'primary': passage,
                     'structure': blocks})
    if len(rows) != 59:
        raise PipelineError('Whitefield CCEL selected sermon count differs')
    return rows, exclusions


def _gutenberg_rows(wrapper: ET.Element) -> tuple[list[dict], list[dict]]:
    sermons = list(wrapper)
    if len(sermons) != 2 or [item.get('n') for item in sermons] != ['LVIII', 'LIX']:
        raise PipelineError('Whitefield Gutenberg selected sermon scope differs')
    rows = []
    for sermon in sermons:
        if sermon.get('type') != 'source-gutenberg-sermon':
            raise PipelineError('Whitefield Gutenberg sermon carrier differs')
        lines = list(sermon)
        if not lines or any(line.tag != NS+'ab' or line.get('type') != 'source-physical-line'
                            or not (line.get('n') or '').isdecimal() for line in lines):
            raise PipelineError('Whitefield Gutenberg line carrier differs')
        if [int(line.get('n')) for line in lines] != list(range(int(lines[0].get('n')), int(lines[-1].get('n'))+1)):
            raise PipelineError('Whitefield Gutenberg physical lines are not contiguous')
        values = [line.text or '' for line in lines]
        nonblank = [value.strip() for value in values if value.strip()]
        if len(nonblank) < 4 or not nonblank[0].startswith('SERMON '+sermon.get('n')):
            raise PipelineError('Whitefield Gutenberg sermon heading differs')
        heading = nonblank[1].strip(' _')
        groups, current = [], []
        for value in values:
            if not value.strip():
                if current:
                    groups.append(_normal(' '.join(current)))
                    current = []
            else:
                current.append(value.strip())
        if current:
            groups.append(_normal(' '.join(current)))
        blocks = [_block('paragraph', group) for group in groups]
        rows.append({'unit_id': sermon.get(XML+'id'), 'number': sermon.get('n'),
                     'heading': heading, 'primary': None, 'structure': blocks,
                     'first_line': int(lines[0].get('n')), 'last_line': int(lines[-1].get('n'))})
    return rows, [{'carrier': 'other-source-lines', 'reason': '13,512 acquired lines outside the LVIII/LIX selection'}]


def project(path: Path, *, identity: dict, language: str, representation_revision: str,
            edition_title: str) -> dict:
    edition = identity['edition_id']
    if identity['work_id'] != 'george-whitefield-sermons' or edition not in EDITIONS:
        raise PipelineError('Whitefield projection identity differs')
    raw = Path(path).read_bytes()
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise PipelineError('Whitefield TEI declaration differs')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise PipelineError(f'invalid Whitefield TEI: {exc}') from exc
    body = root.find(NS+'text/'+NS+'body')
    if root.tag != NS+'TEI' or body is None or len(body) != 1:
        raise PipelineError('Whitefield TEI envelope differs')
    kind, count = EDITIONS[edition]
    wrapper = body[0]
    if wrapper.get('type') != ('source-ThML.body' if kind == 'ccel' else 'source-project-gutenberg-member'):
        raise PipelineError('Whitefield source member differs')
    units, exclusions = _ccel_rows(wrapper) if kind == 'ccel' else _gutenberg_rows(wrapper)
    if len(units) != count:
        raise PipelineError('Whitefield row count differs')
    rows = []
    for sequence, unit in enumerate(units, 1):
        structure = unit['structure']
        row = {key: identity[key] for key in ('work_id', 'textual_form_id', 'edition_id')}
        row.update(record_id=edition+':sermon:'+_sha(unit['unit_id'].encode())[:20],
                   sequence=sequence, category='sermons', language=language,
                   representation_revision=representation_revision,
                   provenance={'edition_title': edition_title},
                   locator={'kind': 'sermon', 'number': unit['number'], 'headings': [unit['heading']]},
                   primary_passage=unit['primary'], collection=edition_title,
                   delivery=dict.fromkeys(('statement', 'date', 'place', 'occasion')),
                   structure=structure, text='\n\n'.join(block['text'] for block in structure))
        if not row['text']:
            raise PipelineError('Whitefield public sermon text is empty')
        rows.append(row)
    _, validator = _schema()
    for row in rows:
        problems = list(validator.iter_errors(row))
        if problems:
            raise PipelineError(f'Whitefield sermon public row invalid: {problems[0].message}')
    receipt = {'scope': 'Whitefield source-native edition selection', 'mapping_version': VERSION,
               'master_sha256': _sha(raw), 'output_sha256': _sha(_json(rows)), 'row_count': len(rows),
               'source_kind': kind, 'unit_ids': [unit['unit_id'] for unit in units],
               'exclusions': exclusions, 'independent_check': {'status': 'pending'}}
    return {'rows': rows, 'receipt': receipt}


def verify(path: Path, rows: list[dict], receipt: dict, *, identity: dict, language: str,
           representation_revision: str, edition_title: str) -> list[str]:
    """Check actual rows against lxml source observations and receipt bindings."""
    try:
        raw = Path(path).read_bytes()
        doc = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        kind, count = EDITIONS[identity['edition_id']]
        ns = {'t': NS[1:-1]}
        wrapper = doc.xpath('./t:text/t:body/t:div', namespaces=ns)
        if len(wrapper) != 1 or wrapper[0].get('type') != ('source-ThML.body' if kind == 'ccel' else 'source-project-gutenberg-member'):
            return ['Whitefield source wrapper differs']
        divisions = wrapper[0].xpath('./t:div', namespaces=ns)
        selected = divisions[2:61] if kind == 'ccel' else divisions
        if len(divisions) != (62 if kind == 'ccel' else 2) or len(selected) != count or len(rows) != count:
            return ['Whitefield source/row selection count differs']
        if [row.get('sequence') for row in rows] != list(range(1, count+1)):
            return ['Whitefield public sequence differs']
        for unit, row in zip(selected, rows):
            if row.get('record_id') != identity['edition_id']+':sermon:'+_sha(unit.get(XML+'id').encode())[:20]:
                return ['Whitefield row source identity differs']
            if row.get('edition_id') != identity['edition_id'] or row.get('provenance', {}).get('edition_title') != edition_title:
                return ['Whitefield row edition credit differs']
            if kind == 'ccel':
                ledger = json.loads(unit.get('n'))
                source = dict(ledger['source_attributes'])
                expected_blocks = []
                for node in unit.xpath('.//t:p | .//t:ab', namespaces=ns):
                    annotation = json.loads(node.get('n'))
                    source_tag = annotation['source_tag']
                    value = ' '.join(''.join(node.itertext()).split())
                    if value:
                        block_kind = 'paragraph' if source_tag == 'p' else 'heading' if source_tag in ('h1', 'h2', 'h3', 'h4') else 'scripture-reference'
                        expected_blocks.append({'kind': block_kind, 'number': None, 'text': value, 'notes': [], 'references': [], 'children': []})
                primary = None
                for node in unit.xpath('.//t:ab', namespaces=ns):
                    annotation = json.loads(node.get('n'))
                    attrs = dict(annotation['source_attributes'])
                    if annotation['source_tag'] == 'scripCom' and attrs.get('type') == 'Sermon':
                        primary = attrs.get('passage')
                        break
                expected_row = {key: identity[key] for key in ('work_id', 'textual_form_id', 'edition_id')}
                expected_row.update(record_id=identity['edition_id']+':sermon:'+sha256(unit.get(XML+'id').encode()).hexdigest()[:20], sequence=selected.index(unit)+1, category='sermons', language=language, representation_revision=representation_revision, provenance={'edition_title': edition_title}, locator={'kind': 'sermon', 'number': source.get('n'), 'headings': [re.sub(r'^\d+\.\s*', '', source['title'])]}, primary_passage=primary, collection=edition_title, delivery=dict.fromkeys(('statement', 'date', 'place', 'occasion')), structure=expected_blocks, text='\n\n'.join(block['text'] for block in expected_blocks))
                if row != expected_row:
                    return ['Whitefield CCEL complete row metadata or structure differs']
                observed = [_normal(''.join(node.itertext())) for node in unit.xpath('.//t:p | .//t:ab', namespaces=ns)]
                observed = [value for value in observed if value]
                if source['title'].split('. ', 1)[-1] != row['locator']['headings'][0]:
                    return ['Whitefield CCEL title differs']
                if [block['text'] for block in row['structure']] != observed:
                    return ['Whitefield CCEL prose correspondence differs']
            else:
                lines = unit.xpath('./t:ab[@type="source-physical-line"]', namespaces=ns)
                if len(lines) != len(unit) or unit.get('n') != row['locator']['number']:
                    return ['Whitefield Gutenberg line selection differs']
                values = [line.text or '' for line in lines]
                chunks = re.split(r'\n\s*\n', '\n'.join(values))
                observed = [_normal(chunk) for chunk in chunks if chunk.strip()]
                if [block['text'] for block in row['structure']] != observed:
                    return ['Whitefield Gutenberg prose correspondence differs']
                headings = [value.strip() for value in values if value.strip()]
                if headings[1].strip(' _') != row['locator']['headings'][0]:
                    return ['Whitefield Gutenberg heading differs']
            if row['text'] != '\n\n'.join(block['text'] for block in row['structure']):
                return ['Whitefield readable text differs']
        if kind == 'ccel':
            expected_exclusions = [{'carrier': dict(json.loads(divisions[index].get('n'))['source_attributes'])['id'], 'reason': reason} for index, reason in ((0, 'title-page'), (1, 'contents'), (61, 'indexes'))]
            if receipt.get('unit_ids') != [unit.get(XML+'id') for unit in selected] or receipt.get('exclusions') != expected_exclusions or receipt.get('source_kind') != 'ccel' or receipt.get('scope') != 'Whitefield source-native edition selection' or receipt.get('independent_check') != {'status': 'pending'}:
                return ['Whitefield CCEL receipt source inventory differs']
        if receipt.get('master_sha256') != _sha(raw) or receipt.get('output_sha256') != _sha(_json(rows)) or receipt.get('row_count') != count or receipt.get('mapping_version') != VERSION:
            return ['Whitefield receipt binding differs']
        return []
    except (OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError, AttributeError) as exc:
        return [f'Whitefield independent verification failed: {exc}']
