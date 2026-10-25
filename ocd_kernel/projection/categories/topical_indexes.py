"""Source-defined topical lookup rows and an independent lxml checker.

The document context is supplied by the caller. This bounded entry point does
not establish accepted-master status, source fidelity, or release authority.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import jsonschema
from lxml import etree
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from ocd_kernel.library._common import PipelineError

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / 'schemas/v2/categories/topical-indexes.schema.json'
COMMON = ROOT / 'schemas/v2/public-row.schema.json'
NS = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def project_topical_indexes_document(tei_path, *, identity, language, representation_revision, edition_title):
    if identity.get('work_id') == 'naves-topical-bible':
        from .topical_nave import project_nave_native
        return project_nave_native(tei_path, identity=identity, language=language, representation_revision=representation_revision, edition_title=edition_title)
    if identity.get('work_id') == 'torreys-topical-textbook':
        return _project_torrey_native(tei_path, identity=identity, language=language, representation_revision=representation_revision, edition_title=edition_title)
    raw = Path(tei_path).read_bytes()
    scan = raw.replace(b'\x00', b'')
    if any(s in scan.upper() for s in (b'<!DOCTYPE', b'<!ENTITY', b'<!--')) or re.search(br'<\?(?!xml(?:\s|\?>))', scan, re.I):
        raise PipelineError('unsupported-visible: declarations/comments/instructions')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise PipelineError(f'invalid topical TEI: {exc}') from exc
    schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
    policy = schema['x-ocd-profile']
    inventory, warnings, exclusions, ids = [], [], [], set()

    def walk(node, header=False):
        if not node.tag.startswith(NS): raise PipelineError('unsupported-visible: namespace')
        tag = node.tag[len(NS):]
        header = header or tag == 'teiHeader'
        elements = policy['header_elements'] if header else policy['elements']
        attributes = policy['header_attributes'] if header else policy['attributes']
        if tag not in elements: raise PipelineError('unsupported-visible: element')
        names = {'xml:' + k[len(XML):] if k.startswith(XML) else k for k in node.attrib}
        if names - set(attributes.get(tag, [])): raise PipelineError('unsupported-visible: attribute')
        if node.get(XML + 'id'):
            if node.get(XML + 'id') in ids: raise PipelineError('duplicate source identity')
            ids.add(node.get(XML + 'id'))
        if tag == 'div' and node.get('type') != 'topic': raise PipelineError('unsupported-visible: division type')
        if tag == 'ref':
            role = node.get('type')
            expected = {'type', 'cRef'} if role == 'scripture' else {'type', 'target'} if role == 'topic' else {'type'} if role == 'source-reference-run' else set()
            if not expected or set(node.attrib) != expected: raise PipelineError('unsupported-visible: reference role/target')
            if any(not v.strip() for v in node.attrib.values()): raise PipelineError('unsupported-visible: empty reference target')
        if tag not in ('p', 'title', 'head', 'item', 'ref', 'author', 'publisher', 'idno', 'note', 'change', 'label') and ((node.text or '').strip() or any((c.tail or '').strip() for c in node)):
            raise PipelineError('unsupported-visible: loose structural text')
        header = header or tag == 'teiHeader'
        ordinal = len(inventory) + 1
        disposition = policy['roles']['header' if header else 'text']
        inventory.append({'ordinal': ordinal, 'tag': tag, 'attributes': dict(node.attrib), 'text_sha256': _hash((node.text or '').encode()), 'tail_sha256': _hash((node.tail or '').encode()), 'disposition': disposition})
        if header: exclusions.append({'ordinal': ordinal, 'reason': disposition})
        if tag == 'ref' and node.get('type') == 'source-reference-run': warnings.append({'ordinal': ordinal, 'reason': policy['roles']['reference_run']})
        for child in node:
            if not child.tag.startswith(NS) or child.tag[len(NS):] not in elements[tag]: raise PipelineError('unsupported-visible: child structure')
            walk(child, header)

    walk(root)
    if root.tag != NS + 'TEI' or [c.tag for c in root] != [NS + 'teiHeader', NS + 'text'] or [c.tag for c in root.find(NS + 'text')] != [NS + 'body']:
        raise PipelineError('unsupported-visible: document envelope')
    common = json.loads(COMMON.read_text(encoding='utf-8'))
    registry = Registry().with_resource(common['$id'], Resource.from_contents(common, default_specification=DRAFT202012))
    validator = jsonschema.Draft202012Validator(schema, registry=registry)
    rows, anchors = [], []

    def norm(node):
        return ' '.join(''.join(node.itertext()).split())

    for sequence, unit in enumerate(root.find(NS + 'text').find(NS + 'body'), 1):
        heads = unit.findall(NS + 'head')
        if not unit.get(XML + 'id') or not heads or [c.tag for c in unit] != [NS + 'head'] * len(heads) + [NS + 'list']: raise PipelineError('unsupported-visible: topic boundary/order')
        if heads[0].get('type') is not None or any(h.get('type') != 'alternate' or not norm(h) for h in heads[1:]): raise PipelineError('unsupported-visible: alternate topic heading')
        topic = norm(unit[0])
        items = []
        for item in unit[-1]:
            refs = [{'kind': r.get('type'), 'label': norm(r), 'target': r.get('cRef') if r.get('type') == 'scripture' else r.get('target')} for r in item.findall(NS + 'ref')]
            items.append({'text': norm(item), 'references': refs})
            labels = item.findall(NS + 'label')
            if labels:
                if len(labels) != 1 or item[0] is not labels[0] or (item.text or '').strip() or not norm(labels[0]): raise PipelineError('unsupported-visible: item label')
                items[-1]['label'] = norm(labels[0])
        row = {key: identity[key] for key in ('work_id', 'textual_form_id', 'edition_id')}
        row.update(record_id=identity['edition_id'] + ':topic:' + _hash(unit.get(XML + 'id').encode())[:20], sequence=sequence, category='topical_indexes', language=language, representation_revision=representation_revision, provenance={'edition_title': edition_title}, topic=topic, locator={'kind': 'topic', 'heading': topic}, items=items, text='\n\n'.join(i['text'] for i in items))
        if len(heads) > 1: row['alternative_topics'] = [norm(h) for h in heads[1:]]
        errors = list(validator.iter_errors(row))
        if errors: raise PipelineError('invalid topical row: ' + errors[0].message)
        rows.append(row)
        anchors.append({'unit_id': unit.get(XML + 'id'), 'record_id': row['record_id'], 'text_sha256': _hash(row['text'].encode())})
    if not rows: raise PipelineError('empty topical scope')
    receipt = {'scope': 'tei-document; caller-supplied context', 'mapping_version': policy['version'], 'master_sha256': _hash(raw), 'schema_sha256': _hash(SCHEMA.read_bytes()), 'common_schema_sha256': _hash(COMMON.read_bytes()), 'output_sha256': _hash(_canonical(rows)), 'row_count': len(rows), 'anchors': anchors, 'inventory': inventory, 'warnings': warnings, 'exclusions': exclusions, 'unsupported': [], 'independent_check': {'status': 'pending'}}
    return {'rows': rows, 'receipt': receipt}


def verify_topical_indexes_document(tei_path, rows, receipt, *, identity, language, representation_revision, edition_title):
    """Recompute complete rows and receipt with an independent XPath traversal."""
    if identity.get('work_id') == 'naves-topical-bible':
        from .topical_nave import verify_nave_native
        return verify_nave_native(tei_path, rows, receipt, identity=identity, language=language, representation_revision=representation_revision, edition_title=edition_title)
    if identity.get('work_id') == 'torreys-topical-textbook':
        return _verify_torrey_native(tei_path, rows, receipt, identity=identity, language=language, representation_revision=representation_revision, edition_title=edition_title)
    try:
        raw = Path(tei_path).read_bytes()
        root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        if root.getroottree().docinfo.doctype or root.xpath('//comment() | //processing-instruction()'): return ['unsupported-visible: declarations/comments/instructions']
        schema = json.loads(SCHEMA.read_text(encoding='utf-8')); policy = schema['x-ocd-profile']; ns = {'t': NS[1:-1]}
        inventory, warnings, exclusions, ids = [], [], [], []
        for ordinal, node in enumerate(root.xpath('descendant-or-self::*'), 1):
            q = etree.QName(node); tag = q.localname
            header = bool(node.xpath('ancestor-or-self::t:teiHeader', namespaces=ns))
            elements = policy['header_elements'] if header else policy['elements']
            attributes = policy['header_attributes'] if header else policy['attributes']
            if q.namespace != ns['t'] or tag not in elements: raise ValueError('unsupported-visible: namespace/element')
            names = {'xml:' + etree.QName(k).localname if k.startswith(XML) else k for k in node.attrib}
            if names - set(attributes.get(tag, [])): raise ValueError('unsupported-visible: attribute')
            if node.get(XML + 'id'): ids.append(node.get(XML + 'id'))
            if tag == 'div' and node.get('type') != 'topic': raise ValueError('unsupported-visible: division type')
            if tag == 'ref':
                role = node.get('type')
                if role == 'scripture': valid = set(node.attrib) == {'type', 'cRef'} and bool(node.get('cRef', '').strip())
                elif role == 'topic': valid = set(node.attrib) == {'type', 'target'} and bool(node.get('target', '').strip())
                else: valid = role == 'source-reference-run' and set(node.attrib) == {'type'}
                if not valid: raise ValueError('unsupported-visible: reference role/target')
            if tag not in ('p', 'title', 'head', 'item', 'ref', 'author', 'publisher', 'idno', 'note', 'change', 'label') and any(str(t).strip() for t in node.xpath('text()')): raise ValueError('unsupported-visible: loose structural text')
            if any(etree.QName(c).namespace != ns['t'] or etree.QName(c).localname not in elements[tag] for c in node): raise ValueError('unsupported-visible: child structure')
            header = bool(node.xpath('ancestor-or-self::t:teiHeader', namespaces=ns)); disposition = policy['roles']['header' if header else 'text']
            inventory.append({'ordinal': ordinal, 'tag': tag, 'attributes': dict(node.attrib), 'text_sha256': hashlib.sha256((node.text or '').encode()).hexdigest(), 'tail_sha256': hashlib.sha256((node.tail or '').encode()).hexdigest(), 'disposition': disposition})
            if header: exclusions.append({'ordinal': ordinal, 'reason': disposition})
            if tag == 'ref' and node.get('type') == 'source-reference-run': warnings.append({'ordinal': ordinal, 'reason': policy['roles']['reference_run']})
        if len(ids) != len(set(ids)): raise ValueError('duplicate source identity')
        if root.tag != NS + 'TEI' or [c.tag for c in root] != [NS + 'teiHeader', NS + 'text'] or [c.tag for c in root.find(NS + 'text')] != [NS + 'body']: raise ValueError('unsupported-visible: document envelope')
        expected, anchors = [], []
        for sequence, unit in enumerate(root.xpath('t:text/t:body/t:div', namespaces=ns), 1):
            heads = unit.xpath('t:head', namespaces=ns)
            if not unit.get(XML + 'id') or not heads or [etree.QName(c).localname for c in unit] != ['head'] * len(heads) + ['list']: raise ValueError('unsupported-visible: topic boundary/order')
            alternatives = [' '.join(h.xpath('string(.)').split()) for h in heads[1:]]
            if heads[0].get('type') is not None or any(h.get('type') != 'alternate' for h in heads[1:]) or any(not label for label in alternatives): raise ValueError('unsupported-visible: alternate topic heading')
            topic = ' '.join(unit.xpath('string(t:head)', namespaces=ns).split())
            items = []
            for item in unit.xpath('t:list/t:item', namespaces=ns):
                references = [{'kind': r.get('type'), 'label': ' '.join(''.join(r.xpath('.//text()')).split()), 'target': r.get('cRef') if r.get('type') == 'scripture' else r.get('target')} for r in item.xpath('t:ref', namespaces=ns)]
                items.append({'text': ' '.join(''.join(item.xpath('.//text()')).split()), 'references': references})
                labels = item.xpath('t:label', namespaces=ns)
                if labels:
                    label = ' '.join(labels[0].xpath('string(.)').split())
                    if len(labels) != 1 or item[0] is not labels[0] or (item.text or '').strip() or not label: raise ValueError('unsupported-visible: item label')
                    items[-1]['label'] = label
            row = {'work_id': identity['work_id'], 'textual_form_id': identity['textual_form_id'], 'edition_id': identity['edition_id'], 'record_id': identity['edition_id'] + ':topic:' + hashlib.sha256(unit.get(XML + 'id').encode()).hexdigest()[:20], 'sequence': sequence, 'category': 'topical_indexes', 'language': language, 'representation_revision': representation_revision, 'provenance': {'edition_title': edition_title}, 'topic': topic, 'locator': {'kind': 'topic', 'heading': topic}, 'items': items, 'text': '\n\n'.join(i['text'] for i in items)}
            if alternatives: row['alternative_topics'] = alternatives
            expected.append(row); anchors.append({'unit_id': unit.get(XML + 'id'), 'record_id': row['record_id'], 'text_sha256': hashlib.sha256(row['text'].encode()).hexdigest()})
        if not expected: raise ValueError('empty topical scope')
        wanted = {'scope': 'tei-document; caller-supplied context', 'mapping_version': policy['version'], 'master_sha256': hashlib.sha256(raw).hexdigest(), 'schema_sha256': hashlib.sha256(SCHEMA.read_bytes()).hexdigest(), 'common_schema_sha256': hashlib.sha256(COMMON.read_bytes()).hexdigest(), 'output_sha256': hashlib.sha256(json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest(), 'row_count': len(expected), 'anchors': anchors, 'inventory': inventory, 'warnings': warnings, 'exclusions': exclusions, 'unsupported': [], 'independent_check': {'status': 'pending'}}
        errors = [] if rows == expected else ['topical correspondence: identity/order/topic/text/references differ']
        if receipt != wanted: errors.append('topical receipt differs from independent observations')
        common = json.loads(COMMON.read_text(encoding='utf-8')); registry = Registry().with_resource(common['$id'], Resource.from_contents(common, default_specification=DRAFT202012))
        validator = jsonschema.Draft202012Validator(schema, registry=registry)
        for row in rows: errors.extend('schema: ' + e.message for e in validator.iter_errors(row))
        return errors
    except (OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        return [str(exc)]


def project_accepted_topical_indexes(root, *, acceptance_path):
    """Derive every public context field from validated promoted authority."""
    from ocd_kernel.tei.acceptance import validate_acceptance
    from ocd_kernel.library.identities import edition_by_id, resolve_edition_language
    root = Path(root).resolve()
    acceptance_path = Path(acceptance_path).resolve()
    accepted = validate_acceptance(acceptance_path, root=root)
    if accepted['promotion']['status'] != 'promoted':
        raise PipelineError('projection requires a promoted accepted master')
    work, edition = edition_by_id(root, accepted['identity']['edition_id'], work_id=accepted['identity']["work_id"])
    if edition.record.get('category', work.record.get('category')) != 'topical-indexes':
        raise PipelineError('accepted edition category mismatch')
    result = project_topical_indexes_document(edition.path, identity={k:accepted['identity'][k] for k in ('work_id','textual_form_id','edition_id')}, language=resolve_edition_language(work.record, edition.record, edition.textual_form_id), representation_revision=accepted['representation_revision']['id'], edition_title=edition.title)
    bindings = {}
    for key, value in {'acceptance':acceptance_path,'work':work.path,'master':edition.path,'acquisition':root/accepted['source']['source_manifest']['path']}.items():
        path = Path(value).resolve()
        try: relative = path.relative_to(root).as_posix()
        except ValueError as exc: raise PipelineError('accepted authority outside root') from exc
        bindings[key] = {'path':relative,'sha256':_hash(path.read_bytes())}
    result['receipt']['authority'] = bindings
    result['receipt']['scope'] = 'tei-document; context derived from validated acceptance'
    return result


def verify_accepted_topical_indexes(root, *, acceptance_path, rows, receipt):
    """Independently validate authority and then recompute category correspondence."""
    from ocd_kernel.tei.acceptance import validate_acceptance
    from ocd_kernel.library.identities import edition_by_id, resolve_edition_language
    try:
        directory = Path(root).resolve()
        accepted_file = Path(acceptance_path).resolve()
        record = validate_acceptance(accepted_file, root=directory)
        if record['promotion']['status'] != 'promoted': return ['accepted master is not promoted']
        work, edition = edition_by_id(directory,record['identity']['edition_id'], work_id=record['identity']["work_id"])
        if edition.record.get('category',work.record.get('category')) != 'topical-indexes': return ['accepted category mismatch']
        expected = {}
        for key, path in [('acceptance',accepted_file),('work',Path(work.path)),('master',Path(edition.path)),('acquisition',directory/record['source']['source_manifest']['path'])]:
            resolved = path.resolve()
            expected[key] = {'path':resolved.relative_to(directory).as_posix(),'sha256':hashlib.sha256(resolved.read_bytes()).hexdigest()}
        problems = [] if receipt.get('authority') == expected else ['accepted authority bindings differ']
        if receipt.get('scope') != 'tei-document; context derived from validated acceptance': problems.append('accepted scope label differs')
        document_receipt = {k:v for k,v in receipt.items() if k != 'authority'}
        document_receipt['scope'] = 'tei-document; caller-supplied context'
        problems.extend(verify_topical_indexes_document(edition.path,rows,document_receipt,identity={k:record['identity'][k] for k in ('work_id','textual_form_id','edition_id')},language=resolve_edition_language(work.record, edition.record, edition.textual_form_id),representation_revision=record['representation_revision']['id'],edition_title=edition.title))
        return problems
    except (PipelineError,OSError,ValueError,KeyError,TypeError) as exc:
        return [str(exc)]


# Exact retained-electronic Torrey profile. The source supplies literal ordered
# definition strings, not separately identified verse targets or subheadings.
_TORREY_IDENTITY = {
    'work_id': 'torreys-topical-textbook',
    'textual_form_id': 'torreys-topical-textbook-retained-electronic',
    'edition_id': 'torreys-topical-textbook-retained-electronic-witness',
}
_TORREY_ROOT_ID = 'torreys-topical-textbook-candidate'
_TORREY_SOURCE_SHA = '8211c20290e951f60e21187e3bdaea639c8cf59343675b6518c6c17423906a1c'
_TORREY_PROFILE = 'ocd-topical-indexes-torrey-native-v1'
_TORREY_HEADER_TAGS = {'teiHeader', 'fileDesc', 'titleStmt', 'title', 'publicationStmt',
                       'publisher', 'availability', 'p', 'sourceDesc', 'bibl', 'ptr',
                       'idno', 'note', 'encodingDesc', 'revisionDesc', 'change'}


def _torrey_context(identity, language, edition_title):
    if identity != _TORREY_IDENTITY or language != 'en' or edition_title != "JWBickel/BibleDictionaries retained electronic witness":
        raise PipelineError('unsupported-visible: Torrey native profile identity/context mismatch')


def _torrey_rows_schema():
    schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
    common = json.loads(COMMON.read_text(encoding='utf-8'))
    registry = Registry().with_resource(common['$id'], Resource.from_contents(common, default_specification=DRAFT202012))
    return jsonschema.Draft202012Validator(schema, registry=registry)


def _torrey_raw(tei_path):
    raw = Path(tei_path).read_bytes()
    scan = raw.replace(b'\x00', b'')
    if any(marker in scan.upper() for marker in (b'<!DOCTYPE', b'<!ENTITY', b'<!--')) or re.search(br'<\?(?!xml(?:\s|\?>))', scan, re.I):
        raise PipelineError('unsupported-visible: Torrey declaration/comment/instruction')
    return raw


def _project_torrey_native(tei_path, *, identity, language, representation_revision, edition_title):
    _torrey_context(identity, language, edition_title)
    raw = _torrey_raw(tei_path)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise PipelineError(f'invalid Torrey TEI: {exc}') from exc
    xml_id = XML + 'id'
    if root.tag != NS + 'TEI' or root.attrib != {xml_id: _TORREY_ROOT_ID} or [node.tag for node in root] != [NS + 'teiHeader', NS + 'text']:
        raise PipelineError('unsupported-visible: Torrey TEI envelope')
    header, text = root
    if [node.tag for node in text] != [NS + 'body'] or text.attrib or text.text or text.tail or text[0].attrib:
        raise PipelineError('unsupported-visible: Torrey text/body envelope')
    if [node.tag for node in header] != [NS + 'fileDesc', NS + 'encodingDesc', NS + 'revisionDesc']:
        raise PipelineError('unsupported-visible: Torrey header envelope')
    file_desc, encoding, revisions = header
    if ([node.tag for node in file_desc] != [NS + 'titleStmt', NS + 'publicationStmt', NS + 'sourceDesc']
            or [node.tag for node in file_desc[0]] != [NS + 'title']
            or file_desc[0][0].text != "Torrey's New Topical Textbook"
            or [node.tag for node in file_desc[1]] != [NS + 'publisher', NS + 'availability']
            or [node.tag for node in file_desc[1][1]] != [NS + 'p']
            or [node.tag for node in file_desc[2]] != [NS + 'bibl']
            or [node.tag for node in encoding] != [NS + 'p']
            or [node.tag for node in revisions] != [NS + 'change']):
        raise PipelineError('unsupported-visible: Torrey header structure')
    bibl = header.find('./' + NS + 'fileDesc/' + NS + 'sourceDesc/' + NS + 'bibl')
    if bibl is None or bibl.attrib != {'type': 'ocd-acceptance-binding'}:
        raise PipelineError('unsupported-visible: Torrey source binding')
    if ([node.tag for node in bibl] != [NS + 'ptr'] + [NS + 'idno'] * 9 + [NS + 'note'] * 3
            or bibl[0].get('target') != 'https://huggingface.co/datasets/JWBickel/BibleDictionaries'):
        raise PipelineError('unsupported-visible: Torrey source binding members')
    ids = {node.get('type'): node.text for node in bibl.findall(NS + 'idno')}
    if len(ids) != len(bibl.findall(NS + 'idno')) or any(ids.get(key) != value for key, value in _TORREY_IDENTITY.items()) or ids.get('source_sha256') != _TORREY_SOURCE_SHA or ids.get('retained_sha256') != _TORREY_SOURCE_SHA or ids.get('representation_revision') != representation_revision:
        raise PipelineError('unsupported-visible: Torrey source/edition/revision binding')
    if not any(node.get('type') == 'source-credit' and 'JWBickel/BibleDictionaries' in (node.text or '') for node in bibl.findall(NS + 'note')):
        raise PipelineError('unsupported-visible: Torrey visible source credit')
    if not any(node.get('status') == 'restricted' and 'unresolved' in ''.join(node.itertext()) for node in header.iter(NS + 'availability')):
        raise PipelineError('unsupported-visible: Torrey unresolved rights notice')
    inventory, exclusions, seen = [], [], set()
    header_nodes = set(header.iter())
    for ordinal, node in enumerate(root.iter(), 1):
        tag = node.tag.removeprefix(NS) if isinstance(node.tag, str) and node.tag.startswith(NS) else ''
        is_header = node in header_nodes
        if not tag or (is_header and tag not in _TORREY_HEADER_TAGS):
            raise PipelineError('unsupported-visible: Torrey node')
        if node.get(xml_id):
            if node.get(xml_id) in seen:
                raise PipelineError('duplicate Torrey xml:id')
            seen.add(node.get(xml_id))
        disposition = 'header-context' if is_header else 'projected-or-structural'
        inventory.append({'ordinal': ordinal, 'tag': tag, 'attributes': dict(node.attrib), 'text_sha256': _hash((node.text or '').encode()), 'tail_sha256': _hash((node.tail or '').encode()), 'disposition': disposition})
        if is_header:
            exclusions.append({'ordinal': ordinal, 'reason': disposition})
    rows, anchors = [], []
    validator = _torrey_rows_schema()
    entries = list(text[0])
    if len(entries) != 623 or text[0].text or text[0].tail:
        raise PipelineError('unsupported-visible: Torrey complete topic count/body')
    for sequence, entry in enumerate(entries, 1):
        entry_id = f'torreys-topical-textbook-entry-{sequence:05d}'
        if entry.tag != NS + 'entry' or entry.attrib != {xml_id: entry_id} or entry.text or entry.tail or len(entry) < 2:
            raise PipelineError('unsupported-visible: Torrey native entry')
        form = entry[0]
        if form.tag != NS + 'form' or form.attrib or form.text or form.tail or len(form) != 1:
            raise PipelineError('unsupported-visible: Torrey native form')
        orth = form[0]
        if orth.tag != NS + 'orth' or orth.attrib or len(orth) or not orth.text or orth.tail:
            raise PipelineError('unsupported-visible: Torrey native term')
        items = []
        for index, sense in enumerate(entry[1:], 1):
            if sense.tag != NS + 'sense' or sense.attrib != {xml_id: f'{entry_id}-sense-{index:03d}'} or sense.text or sense.tail or len(sense) != 1:
                raise PipelineError('unsupported-visible: Torrey native sense')
            definition = sense[0]
            if definition.tag != NS + 'def' or definition.attrib != {xml_id: f'{entry_id}-definition-{index:03d}'} or len(definition) or not definition.text or definition.tail:
                raise PipelineError('unsupported-visible: Torrey native definition')
            items.append({'text': definition.text, 'references': []})
        row = {**identity, 'record_id': identity['edition_id'] + ':topic:' + _hash(entry_id.encode())[:20],
               'sequence': sequence, 'category': 'topical_indexes', 'language': language,
               'representation_revision': representation_revision, 'provenance': {'edition_title': edition_title},
               'topic': orth.text, 'locator': {'kind': 'topic', 'heading': orth.text},
               'items': items, 'text': '\n\n'.join(item['text'] for item in items)}
        errors = list(validator.iter_errors(row))
        if errors:
            raise PipelineError('invalid Torrey topical row: ' + errors[0].message)
        rows.append(row)
        anchors.append({'unit_id': entry_id, 'record_id': row['record_id'], 'text_sha256': _hash(row['text'].encode())})
    if sum(len(row['items']) for row in rows) != 23549:
        raise PipelineError('unsupported-visible: Torrey complete definition count')
    receipt = {'scope': 'tei-document; caller-supplied context', 'mapping_version': _TORREY_PROFILE,
               'master_sha256': _hash(raw), 'schema_sha256': _hash(SCHEMA.read_bytes()),
               'common_schema_sha256': _hash(COMMON.read_bytes()), 'output_sha256': _hash(_canonical(rows)),
               'row_count': len(rows), 'anchors': anchors, 'inventory': inventory,
               'warnings': [{'reason': 'Citation-looking text remains literal source text; no verse or subtopic inferred.'}],
               'exclusions': exclusions, 'unsupported': [], 'independent_check': {'status': 'pending'}}
    return {'rows': rows, 'receipt': receipt}


def _verify_torrey_native(tei_path, rows, receipt, *, identity, language, representation_revision, edition_title):
    """Independent lxml traversal of every native Torrey entry and definition."""
    try:
        _torrey_context(identity, language, edition_title)
        raw = _torrey_raw(tei_path)
        root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        ns = {'t': NS[1:-1]}
        xml_id = XML + 'id'
        if root.xpath('//comment() | //processing-instruction()') or root.getroottree().docinfo.doctype:
            raise ValueError('unsupported-visible: Torrey markup')
        if root.tag != NS + 'TEI' or dict(root.attrib) != {xml_id: _TORREY_ROOT_ID} or [node.tag for node in root] != [NS + 'teiHeader', NS + 'text']:
            raise ValueError('unsupported-visible: Torrey envelope')
        header = root[0]
        if [node.tag for node in header] != [NS + 'fileDesc', NS + 'encodingDesc', NS + 'revisionDesc']:
            raise ValueError('unsupported-visible: Torrey header')
        file_desc, encoding, revisions = header
        if ([node.tag for node in file_desc] != [NS + 'titleStmt', NS + 'publicationStmt', NS + 'sourceDesc']
                or [node.tag for node in file_desc[0]] != [NS + 'title']
                or file_desc[0][0].text != "Torrey's New Topical Textbook"
                or [node.tag for node in file_desc[1]] != [NS + 'publisher', NS + 'availability']
                or [node.tag for node in file_desc[1][1]] != [NS + 'p']
                or [node.tag for node in file_desc[2]] != [NS + 'bibl']
                or [node.tag for node in encoding] != [NS + 'p']
                or [node.tag for node in revisions] != [NS + 'change']):
            raise ValueError('unsupported-visible: Torrey header structure')
        if (len(root.xpath('./t:text/t:body', namespaces=ns)) != 1
                or [node.tag for node in root[1]] != [NS + 'body']
                or root[1].attrib or root[1].text or root[1].tail or root[1][0].attrib):
            raise ValueError('unsupported-visible: Torrey body')
        bibl = root.xpath('./t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl[@type="ocd-acceptance-binding"]', namespaces=ns)
        if len(bibl) != 1:
            raise ValueError('unsupported-visible: Torrey source binding')
        if ([node.tag for node in bibl[0]] != [NS + 'ptr'] + [NS + 'idno'] * 9 + [NS + 'note'] * 3
                or bibl[0][0].get('target') != 'https://huggingface.co/datasets/JWBickel/BibleDictionaries'):
            raise ValueError('unsupported-visible: Torrey source binding members')
        ids = {node.get('type'): node.text for node in bibl[0].xpath('./t:idno', namespaces=ns)}
        if len(ids) != len(bibl[0].xpath('./t:idno', namespaces=ns)) or any(ids.get(key) != value for key, value in _TORREY_IDENTITY.items()) or ids.get('source_sha256') != _TORREY_SOURCE_SHA or ids.get('retained_sha256') != _TORREY_SOURCE_SHA or ids.get('representation_revision') != representation_revision:
            raise ValueError('unsupported-visible: Torrey identity/source/revision')
        if not bibl[0].xpath('./t:note[@type="source-credit"][contains(., "JWBickel/BibleDictionaries")]', namespaces=ns):
            raise ValueError('unsupported-visible: Torrey visible credit')
        if not header.xpath('.//t:availability[@status="restricted"]/t:p[contains(., "unresolved")]', namespaces=ns):
            raise ValueError('unsupported-visible: Torrey unresolved notice')
        inventory, exclusions, seen = [], [], set()
        for ordinal, node in enumerate(root.xpath('descendant-or-self::*'), 1):
            tag = etree.QName(node).localname
            is_header = bool(node.xpath('ancestor-or-self::t:teiHeader', namespaces=ns))
            if etree.QName(node).namespace != ns['t'] or (is_header and tag not in _TORREY_HEADER_TAGS):
                raise ValueError('unsupported-visible: Torrey node')
            if node.get(xml_id):
                if node.get(xml_id) in seen:
                    raise ValueError('duplicate Torrey xml:id')
                seen.add(node.get(xml_id))
            disposition = 'header-context' if is_header else 'projected-or-structural'
            inventory.append({'ordinal': ordinal, 'tag': tag, 'attributes': dict(node.attrib), 'text_sha256': _hash((node.text or '').encode()), 'tail_sha256': _hash((node.tail or '').encode()), 'disposition': disposition})
            if is_header:
                exclusions.append({'ordinal': ordinal, 'reason': disposition})
        entries = root.xpath('./t:text/t:body/t:entry', namespaces=ns)
        if len(entries) != 623 or len(root[1][0]) != len(entries) or root[1][0].text or root[1][0].tail:
            raise ValueError('unsupported-visible: Torrey complete entry count')
        expected, anchors = [], []
        for sequence, entry in enumerate(entries, 1):
            entry_id = f'torreys-topical-textbook-entry-{sequence:05d}'
            if dict(entry.attrib) != {xml_id: entry_id} or entry.text or entry.tail or len(entry) < 2:
                raise ValueError('unsupported-visible: Torrey native entry')
            form = entry[0]
            if form.tag != NS + 'form' or form.attrib or form.text or form.tail or len(form) != 1:
                raise ValueError('unsupported-visible: Torrey native form')
            orth = form[0]
            if orth.tag != NS + 'orth' or orth.attrib or len(orth) or not orth.text or orth.tail:
                raise ValueError('unsupported-visible: Torrey native term')
            items = []
            for index, sense in enumerate(entry[1:], 1):
                if sense.tag != NS + 'sense' or dict(sense.attrib) != {xml_id: f'{entry_id}-sense-{index:03d}'} or sense.text or sense.tail or len(sense) != 1:
                    raise ValueError('unsupported-visible: Torrey native sense')
                definition = sense[0]
                if definition.tag != NS + 'def' or dict(definition.attrib) != {xml_id: f'{entry_id}-definition-{index:03d}'} or len(definition) or not definition.text or definition.tail:
                    raise ValueError('unsupported-visible: Torrey native definition')
                items.append({'text': definition.text, 'references': []})
            row = {**identity, 'record_id': identity['edition_id'] + ':topic:' + _hash(entry_id.encode())[:20],
                   'sequence': sequence, 'category': 'topical_indexes', 'language': language,
                   'representation_revision': representation_revision, 'provenance': {'edition_title': edition_title},
                   'topic': orth.text, 'locator': {'kind': 'topic', 'heading': orth.text},
                   'items': items, 'text': '\n\n'.join(item['text'] for item in items)}
            expected.append(row)
            anchors.append({'unit_id': entry_id, 'record_id': row['record_id'], 'text_sha256': _hash(row['text'].encode())})
        if sum(len(row['items']) for row in expected) != 23549:
            raise ValueError('unsupported-visible: Torrey complete definition count')
        wanted = {'scope': 'tei-document; caller-supplied context', 'mapping_version': _TORREY_PROFILE,
                  'master_sha256': _hash(raw), 'schema_sha256': _hash(SCHEMA.read_bytes()),
                  'common_schema_sha256': _hash(COMMON.read_bytes()), 'output_sha256': _hash(_canonical(expected)),
                  'row_count': len(expected), 'anchors': anchors, 'inventory': inventory,
                  'warnings': [{'reason': 'Citation-looking text remains literal source text; no verse or subtopic inferred.'}],
                  'exclusions': exclusions, 'unsupported': [], 'independent_check': {'status': 'pending'}}
        problems = [] if rows == expected else ['Torrey native topical row correspondence differs']
        if receipt != wanted:
            problems.append('Torrey native topical receipt differs')
        validator = _torrey_rows_schema()
        for row in rows:
            problems.extend('schema: ' + error.message for error in validator.iter_errors(row))
        return problems
    except (OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError, PipelineError) as exc:
        return [str(exc)]
