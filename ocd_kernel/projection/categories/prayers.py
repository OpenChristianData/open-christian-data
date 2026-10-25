"""Bounded source-defined prayers, petitions, and attached responses."""
from __future__ import annotations
from ocd_kernel.projection.native_content_check import projection_validator

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
from ocd_kernel.lib.path_io import io_path, resolve_path
from ocd_kernel.projection.categories.native_documents import _entry_attribution, _observe_entry_attribution
from ocd_kernel.projection import native_content
from ocd_kernel.projection.scripture_authority import BOOK_CODES_PATH, load_book_codes
from ocd_kernel.projection.scripture_targets import normalize_reference_record
from ocd_kernel.projection.scripture_targets_check import observe_reference_record

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / 'schemas/v2/categories/prayers.schema.json'
COMMON = ROOT / 'schemas/v2/public-row.schema.json'
NS = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'

# Acceptance validation requires common TEI header carriers for canonical
# identity, acquisition/source binding, and representation revision.  Keep
# those carriers behind the accepted entry points; ordinary document
# projection remains governed by the category profile above.
_ACCEPTANCE_HEADER_ELEMENTS = {
    'TEI': ['teiHeader', 'text'],
    'teiHeader': ['fileDesc', 'revisionDesc'],
    'fileDesc': ['titleStmt', 'publicationStmt', 'sourceDesc'],
    'titleStmt': ['title'],
    'title': [],
    'publicationStmt': ['p'],
    'p': [],
    'sourceDesc': ['bibl'],
    'bibl': ['title', 'idno', 'ptr', 'note'],
    'idno': [],
    'ptr': [],
    'note': [],
    'revisionDesc': ['change'],
    'change': [],
}
_ACCEPTANCE_HEADER_ATTRIBUTES = {
    'title': ['type'],
    'idno': ['type'],
    'ptr': ['target'],
    'note': ['type'],
    'change': ['xml:id', 'when'],
}


def _prayers_validator():
    """Validate either a bounded liturgical prayer or a native anthology row."""
    common = json.loads(COMMON.read_text(encoding='utf-8'))
    native = json.loads(native_content.SCHEMA.read_text(encoding='utf-8'))
    registry = Registry().with_resources([
        (common['$id'], Resource.from_contents(common, default_specification=DRAFT202012)),
        (native['$id'], Resource.from_contents(native, default_specification=DRAFT202012)),
    ])
    return projection_validator(
        json.loads(SCHEMA.read_text(encoding='utf-8')), registry=registry,
    )


def _uses_native_anthology(path: Path) -> bool:
    """Choose source hierarchy for an anthology; keep liturgical roles bounded."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise PipelineError(f'invalid prayer TEI: {exc}') from exc
    text = root.find(NS + 'text')
    if text is None:
        return False
    if any(child.tag in {NS + 'front', NS + 'back'} for child in text):
        return True
    return any(node.tag in {NS + name for name in ('table', 'fw', 'lg', 'l', 'list', 'item')}
               for node in text.iter())


def _hash(data): return hashlib.sha256(data).hexdigest()


def project_prayers_document(tei_path, *, identity, language, representation_revision,
                             edition_title, _allow_acceptance_metadata=False):
    if _uses_native_anthology(Path(tei_path)):
        from ocd_kernel.projection.categories.native_documents import project_document
        return project_document(
            tei_path, identity=identity, language=language,
            representation_revision=representation_revision, edition_title=edition_title,
            _allow_acceptance_metadata=_allow_acceptance_metadata, category='prayers',
        )
    raw = Path(tei_path).read_bytes(); scan = raw.replace(b'\x00', b'')
    if any(x in scan.upper() for x in (b'<!DOCTYPE', b'<!ENTITY', b'<!--')) or re.search(br'<\?(?!xml(?:\s|\?>))', scan, re.I):
        raise PipelineError('unsupported-visible: declarations/comments/instructions')
    try: root = ET.fromstring(raw)
    except ET.ParseError as exc: raise PipelineError(f'invalid prayer TEI: {exc}') from exc
    schema = json.loads(SCHEMA.read_text(encoding='utf-8')); policy = schema['x-ocd-profile']
    inventory, exclusions, warnings, ids = [], [], [], set()

    parents = {child: parent for parent in root.iter() for child in parent}

    def walk(node, header=False, attribution=False):
        if not node.tag.startswith(NS): raise PipelineError('unsupported-visible: namespace')
        tag = node.tag[len(NS):]
        header = header or tag == 'teiHeader'
        attribution = attribution or (tag == 'note' and node.get('type') == 'source-attribution')
        elements = (_ACCEPTANCE_HEADER_ELEMENTS if _allow_acceptance_metadata and header
                    else policy['elements'])
        attributes = (_ACCEPTANCE_HEADER_ATTRIBUTES if _allow_acceptance_metadata and header
                      else policy['attributes'])
        if tag not in elements: raise PipelineError('unsupported-visible: element')
        names = {'xml:' + k[len(XML):] if k.startswith(XML) else k for k in node.attrib}
        if names - set(attributes.get(tag, [])): raise PipelineError('unsupported-visible: attribute')
        if node.get(XML + 'id'):
            if node.get(XML + 'id') in ids: raise PipelineError('duplicate source identity')
            ids.add(node.get(XML + 'id'))
        if not (_allow_acceptance_metadata and header) and tag == 'hi' and node.get('rend') not in policy['renditions']: raise PipelineError('unsupported-visible: rendition')
        if not (_allow_acceptance_metadata and header) and tag == 'div' and node.get('type') != 'prayer': raise PipelineError('unsupported-visible: division type')
        if not (_allow_acceptance_metadata and header) and tag == 'ab' and node.get('type') not in ('petition', 'response'): raise PipelineError('unsupported-visible: prayer role')
        if not (_allow_acceptance_metadata and header) and tag == 'head' and node.get('type') != 'occasion': raise PipelineError('unsupported-visible: heading role')
        if not (_allow_acceptance_metadata and header) and tag == 'note' and node.get('type') not in ('usage', 'source-attribution'): raise PipelineError('unsupported-visible: note role')
        if not (_allow_acceptance_metadata and header) and tag == 'title' and node.get('type') not in (None, 'office', 'source-title'): raise PipelineError('unsupported-visible: title role')
        if tag == 'note' and node.get('type') == 'source-attribution' and (header or parents[node].tag != NS+'div'):
            raise PipelineError('unsupported-visible: entry attribution placement')
        if tag == 'note' and node.get('type') == 'usage' and len(node):
            raise PipelineError('unsupported-visible: usage note structure')
        if tag == 'ref' and node.get('type') != ('source-url' if attribution else 'scripture'): raise PipelineError('unsupported-visible: reference role')
        if tag not in ('p', 'ab', 'title', 'head', 'label', 'note', 'hi', 'idno', 'change', 'ref', 'seg') and ((node.text or '').strip() or any((c.tail or '').strip() for c in node)):
            raise PipelineError('unsupported-visible: loose structural text')
        ordinal = len(inventory) + 1; role = policy['roles']['header' if header else 'text']
        inventory.append({'ordinal': ordinal, 'tag': tag, 'attributes': dict(node.attrib), 'text_sha256': _hash((node.text or '').encode()), 'tail_sha256': _hash((node.tail or '').encode()), 'role': role})
        if header: exclusions.append({'ordinal': ordinal, 'reason': role})
        if tag == 'hi' and not header: warnings.append({'ordinal': ordinal, 'reason': policy['roles']['typography']})
        for child in node:
            if not child.tag.startswith(NS) or child.tag[len(NS):] not in elements[tag]: raise PipelineError('unsupported-visible: child structure')
            walk(child, header, attribution)

    walk(root)
    if root.tag != NS + 'TEI' or [c.tag for c in root] != [NS + 'teiHeader', NS + 'text'] or [c.tag for c in root.find(NS + 'text')] != [NS + 'body']:
        raise PipelineError('unsupported-visible: document envelope')
    def norm(node): return ' '.join(''.join(node.itertext()).split())
    offices = [n for n in root.findall('.//' + NS + 'sourceDesc/' + NS + 'bibl/' + NS + 'title') if n.get('type') == 'office']
    if len(offices) > 1: raise PipelineError('unsupported-visible: multiple office labels')
    office = norm(offices[0]) if offices else None
    rubrics = [norm(n) for n in root.findall('.//' + NS + 'sourceDesc/' + NS + 'bibl/' + NS + 'note') if n.get('type') == 'usage']
    common = json.loads(COMMON.read_text(encoding='utf-8')); registry = Registry().with_resource(common['$id'], Resource.from_contents(common, default_specification=DRAFT202012))
    validator = projection_validator(schema, registry=registry)
    rows, anchors = [], []
    book_codes = load_book_codes(BOOK_CODES_PATH)
    for sequence, unit in enumerate(root.find(NS + 'text').find(NS + 'body'), 1):
        heads = unit.findall(NS + 'head'); paragraphs = [c for c in unit if c.tag in (NS + 'p', NS + 'ab')]
        if not unit.get(XML + 'id') or len(heads) > 1 or not paragraphs or list(unit) != heads + paragraphs + unit.findall(NS + "note[@type='source-attribution']"): raise PipelineError('unsupported-visible: prayer boundary/order')
        title = norm(heads[0]) if heads else None; divisions = []
        for position, paragraph in enumerate(paragraphs, 1):
            labels = paragraph.findall(NS + 'label')
            if len(labels) > 1 or (labels and ((paragraph.text or '').strip() or list(paragraph)[0] is not labels[0])): raise PipelineError('unsupported-visible: speaker placement')
            speaker = norm(labels[0]) if labels else None
            spoken = ' '.join(((paragraph.text or '') + ''.join((''.join(c.itertext()) if c.tag != NS+'label' else '') + (c.tail or '') for c in paragraph)).split())
            kind = 'paragraph' if paragraph.tag == NS + 'p' else paragraph.get('type'); target = paragraph.get('corresp')
            if kind == 'response':
                if position == 1 or not speaker or not paragraphs[position - 2].get(XML + 'id') or target != '#' + paragraphs[position - 2].get(XML + 'id') or paragraphs[position - 2].get('type') != 'petition': raise PipelineError('unsupported-visible: response attachment')
            elif target is not None: raise PipelineError('unsupported-visible: nonresponse target')
            divisions.append({'kind': kind, 'text': spoken, 'speaker': speaker, 'response_to': position - 1 if kind == 'response' else None})
            references = []
            for ref in paragraph.findall(NS + 'ref'):
                record = {'raw': norm(ref)}
                record.update({key: ref.get(key) for key in ('cRef', 'target') if key in ref.attrib})
                if any(not value or not value.strip() for value in record.values()): raise PipelineError('unsupported-visible: empty reference')
                references.append(normalize_reference_record(record, book_codes=book_codes))
            if references: divisions[-1]['references'] = references
        row = {k: identity[k] for k in ('work_id', 'textual_form_id', 'edition_id')}
        row.update(record_id=identity['edition_id'] + ':prayer:' + _hash(unit.get(XML + 'id').encode())[:20], sequence=sequence, category='prayers', language=language, representation_revision=representation_revision, provenance={'edition_title': edition_title, **_entry_attribution(unit)}, locator={'kind': 'prayer', 'title': title}, office=office, occasion=title, rubrics=rubrics, divisions=divisions, text='\n\n'.join((b['speaker'] + ' ' if b['speaker'] else '') + b['text'] for b in divisions))
        errors = list(validator.iter_errors(row))
        if errors: raise PipelineError('invalid prayer row: ' + errors[0].message)
        rows.append(row); anchors.append({'unit_id': unit.get(XML + 'id'), 'record_id': row['record_id'], 'text_sha256': _hash(row['text'].encode())})
    if not rows: raise PipelineError('empty prayer scope')
    receipt = {'scope': 'tei-document; caller-supplied context', 'mapping_version': policy['version'], 'master_sha256': _hash(raw), 'schema_sha256': _hash(SCHEMA.read_bytes()), 'common_schema_sha256': _hash(COMMON.read_bytes()), 'native_content_schema_sha256': _hash(native_content.SCHEMA.read_bytes()), 'book_codes_sha256': _hash(BOOK_CODES_PATH.read_bytes()), 'output_sha256': _hash(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()), 'row_count': len(rows), 'anchors': anchors, 'inventory': inventory, 'warnings': warnings, 'exclusions': exclusions, 'unsupported': [], 'independent_check': {'status': 'pending'}}
    return {'rows': rows, 'receipt': receipt}


def verify_prayers_document(tei_path, rows, receipt, *, identity, language, representation_revision,
                            edition_title, _allow_acceptance_metadata=False):
    if _uses_native_anthology(Path(tei_path)):
        from ocd_kernel.projection.categories.native_documents import verify_document
        return verify_document(
            tei_path, rows, receipt, identity=identity, language=language,
            representation_revision=representation_revision, edition_title=edition_title,
            _allow_acceptance_metadata=_allow_acceptance_metadata, category='prayers',
        )
    """Independently recompute source order, roles, links, metadata, and receipt."""
    try:
        raw = Path(tei_path).read_bytes(); root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        if root.getroottree().docinfo.doctype or root.xpath('//comment() | //processing-instruction()'): return ['unsupported-visible: declarations/comments/instructions']
        schema = json.loads(SCHEMA.read_text(encoding='utf-8')); policy = schema['x-ocd-profile']; ns = {'t': NS[1:-1]}
        inventory, exclusions, warnings, ids = [], [], [], []
        for ordinal, node in enumerate(root.xpath('descendant-or-self::*'), 1):
            q = etree.QName(node); tag = q.localname
            header = bool(node.xpath('ancestor-or-self::t:teiHeader', namespaces=ns))
            attribution = bool(node.xpath('ancestor-or-self::t:note[@type="source-attribution"]', namespaces=ns))
            elements = (_ACCEPTANCE_HEADER_ELEMENTS if _allow_acceptance_metadata and header
                        else policy['elements'])
            attributes = (_ACCEPTANCE_HEADER_ATTRIBUTES if _allow_acceptance_metadata and header
                          else policy['attributes'])
            if q.namespace != ns['t'] or tag not in elements: raise ValueError('unsupported-visible: element/namespace')
            names = {'xml:' + etree.QName(k).localname if k.startswith(XML) else k for k in node.attrib}
            if names - set(attributes.get(tag, [])): raise ValueError('unsupported-visible: attribute')
            if node.get(XML + 'id'): ids.append(node.get(XML + 'id'))
            if not (_allow_acceptance_metadata and header) and tag == 'hi' and node.get('rend') not in policy['renditions']: raise ValueError('unsupported-visible: rendition')
            if not (_allow_acceptance_metadata and header) and tag == 'div' and node.get('type') != 'prayer': raise ValueError('unsupported-visible: division type')
            if not (_allow_acceptance_metadata and header) and tag == 'ab' and node.get('type') not in ('petition', 'response'): raise ValueError('unsupported-visible: prayer role')
            if not (_allow_acceptance_metadata and header) and tag == 'head' and node.get('type') != 'occasion': raise ValueError('unsupported-visible: heading role')
            if not (_allow_acceptance_metadata and header) and tag == 'note' and node.get('type') not in ('usage', 'source-attribution'): raise ValueError('unsupported-visible: note role')
            if not (_allow_acceptance_metadata and header) and tag == 'title' and node.get('type') not in (None, 'office', 'source-title'): raise ValueError('unsupported-visible: title role')
            if tag == 'note' and node.get('type') == 'source-attribution' and (header or node.getparent().tag != NS+'div'):
                raise ValueError('unsupported-visible: entry attribution placement')
            if tag == 'note' and node.get('type') == 'usage' and len(node):
                raise ValueError('unsupported-visible: usage note structure')
            if tag == 'ref' and node.get('type') != ('source-url' if attribution else 'scripture'): raise ValueError('unsupported-visible: reference role')
            if tag not in ('p', 'ab', 'title', 'head', 'label', 'note', 'hi', 'idno', 'change', 'ref', 'seg') and any(str(v).strip() for v in node.xpath('text()')): raise ValueError('unsupported-visible: loose text')
            if any(etree.QName(c).namespace != ns['t'] or etree.QName(c).localname not in elements[tag] for c in node): raise ValueError('unsupported-visible: child structure')
            role = policy['roles']['header' if header else 'text']
            inventory.append({'ordinal': ordinal, 'tag': tag, 'attributes': dict(node.attrib), 'text_sha256': hashlib.sha256((node.text or '').encode()).hexdigest(), 'tail_sha256': hashlib.sha256((node.tail or '').encode()).hexdigest(), 'role': role})
            if header: exclusions.append({'ordinal': ordinal, 'reason': role})
            if tag == 'hi' and not header: warnings.append({'ordinal': ordinal, 'reason': policy['roles']['typography']})
        if len(ids) != len(set(ids)): raise ValueError('duplicate source identity')
        if root.tag != NS + 'TEI' or [c.tag for c in root] != [NS + 'teiHeader', NS + 'text'] or [c.tag for c in root.find(NS + 'text')] != [NS + 'body']: raise ValueError('unsupported-visible: envelope')
        def value(node): return ' '.join(''.join(node.xpath('.//text()')).split())
        offices = root.xpath('t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:title[@type="office"]', namespaces=ns)
        if len(offices) > 1: raise ValueError('unsupported-visible: multiple offices')
        office = value(offices[0]) if offices else None
        rubrics = [value(n) for n in root.xpath('t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:note[@type="usage"]', namespaces=ns)]
        expected, anchors = [], []
        book_codes = load_book_codes(BOOK_CODES_PATH)
        for sequence, unit in enumerate(root.xpath('t:text/t:body/t:div', namespaces=ns), 1):
            heads = unit.xpath('t:head', namespaces=ns); paragraphs = unit.xpath('t:p | t:ab', namespaces=ns)
            if not unit.get(XML + 'id') or len(heads) > 1 or not paragraphs or list(unit) != heads + paragraphs + unit.xpath('t:note[@type="source-attribution"]', namespaces=ns): raise ValueError('unsupported-visible: prayer boundary/order')
            title = value(heads[0]) if heads else None; divisions = []
            for position, p in enumerate(paragraphs, 1):
                labels = p.xpath('t:label', namespaces=ns)
                if len(labels) > 1 or (labels and ((p.text or '').strip() or p[0] is not labels[0])): raise ValueError('unsupported-visible: speaker placement')
                speaker = value(labels[0]) if labels else None
                kind = 'paragraph' if p.tag == NS + 'p' else p.get('type'); target = p.get('corresp')
                if kind == 'response':
                    previous = p.getprevious()
                    if previous is None or previous.tag != NS + 'ab' or previous.get('type') != 'petition' or not speaker or not previous.get(XML + 'id') or target != '#' + previous.get(XML + 'id'): raise ValueError('unsupported-visible: response attachment')
                elif target is not None: raise ValueError('unsupported-visible: nonresponse target')
                divisions.append({'kind': kind, 'text': ' '.join(''.join(p.xpath('.//text()[not(ancestor::t:label)]', namespaces=ns)).split()), 'speaker': speaker, 'response_to': position - 1 if kind == 'response' else None})
                references = []
                for ref in p.xpath('t:ref', namespaces=ns):
                    record = {'raw': value(ref)}
                    for key in ('cRef', 'target'):
                        if key in ref.attrib: record[key] = ref.attrib[key]
                    if any(not item or not item.strip() for item in record.values()): raise ValueError('unsupported-visible: empty reference')
                    references.append(observe_reference_record(record, book_codes=book_codes))
                if references: divisions[-1]['references'] = references
            row = {'work_id': identity['work_id'], 'textual_form_id': identity['textual_form_id'], 'edition_id': identity['edition_id'], 'record_id': identity['edition_id'] + ':prayer:' + hashlib.sha256(unit.get(XML + 'id').encode()).hexdigest()[:20], 'sequence': sequence, 'category': 'prayers', 'language': language, 'representation_revision': representation_revision, 'provenance': {'edition_title': edition_title, **_observe_entry_attribution(unit)}, 'locator': {'kind': 'prayer', 'title': title}, 'office': office, 'occasion': title, 'rubrics': rubrics, 'divisions': divisions, 'text': '\n\n'.join((b['speaker'] + ' ' if b['speaker'] else '') + b['text'] for b in divisions)}
            expected.append(row); anchors.append({'unit_id': unit.get(XML + 'id'), 'record_id': row['record_id'], 'text_sha256': hashlib.sha256(row['text'].encode()).hexdigest()})
        if not expected: raise ValueError('empty prayer scope')
        wanted = {'scope': 'tei-document; caller-supplied context', 'mapping_version': policy['version'], 'master_sha256': hashlib.sha256(raw).hexdigest(), 'schema_sha256': hashlib.sha256(SCHEMA.read_bytes()).hexdigest(), 'common_schema_sha256': hashlib.sha256(COMMON.read_bytes()).hexdigest(), 'native_content_schema_sha256': hashlib.sha256(native_content.SCHEMA.read_bytes()).hexdigest(), 'book_codes_sha256': hashlib.sha256(BOOK_CODES_PATH.read_bytes()).hexdigest(), 'output_sha256': hashlib.sha256(json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest(), 'row_count': len(expected), 'anchors': anchors, 'inventory': inventory, 'warnings': warnings, 'exclusions': exclusions, 'unsupported': [], 'independent_check': {'status': 'pending'}}
        errors = [] if rows == expected else ['prayer correspondence: identity/order/text/roles/metadata differ']
        if receipt != wanted: errors.append('prayer receipt differs from independent observations')
        common = json.loads(COMMON.read_text(encoding='utf-8')); registry = Registry().with_resource(common['$id'], Resource.from_contents(common, default_specification=DRAFT202012)); validator = projection_validator(schema, registry=registry)
        for row in rows: errors.extend('schema: ' + e.message for e in validator.iter_errors(row))
        return errors
    except (OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc: return [str(exc)]


def _accepted_context(root, acceptance_path):
    """Resolve the canonical promoted prayer edition and authority bindings."""
    from ocd_kernel.library.acquisitions import acquisition_for_edition
    from ocd_kernel.library.identities import edition_by_id, resolve_edition_language
    from ocd_kernel.tei.acceptance import validate_acceptance

    root = resolve_path(root)
    acceptance_path = resolve_path(acceptance_path)
    accepted = validate_acceptance(acceptance_path, root=root)
    if accepted['promotion']['status'] != 'promoted':
        raise PipelineError('projection requires a promoted accepted master')
    identity = accepted.get('identity')
    if not isinstance(identity, dict):
        raise PipelineError('accepted identity is missing')
    work, edition = edition_by_id(root, identity['edition_id'], work_id=identity["work_id"])
    expected = {
        'work_id': work.work_id,
        'textual_form_id': edition.textual_form_id,
        'edition_id': edition.edition_id,
    }
    if any(identity.get(key) != value for key, value in expected.items()):
        raise PipelineError('accepted identity does not identify the canonical edition')
    forms = work.record.get('textual_forms')
    form = next(
        (
            value
            for value in forms or []
            if isinstance(value, dict)
            and value.get('textual_form_id') == edition.textual_form_id
        ),
        None,
    )
    if not isinstance(form, dict):
        raise PipelineError('accepted identity does not identify the canonical textual form')
    category = edition.record.get('category', form.get('category'))
    if category != 'prayers':
        raise PipelineError('accepted prayers category mismatch')
    language = resolve_edition_language(work.record, edition.record, edition.textual_form_id)
    if not isinstance(language, str) or not language:
        raise PipelineError('accepted prayers language is missing from the canonical edition')
    acquisition_path, _acquisition = acquisition_for_edition(
        root,
        work.work_id,
        edition.edition_id,
        acquisition_id=identity['acquisition_id'],
    )
    authority = {}
    for key, path in {
        'acceptance': acceptance_path,
        'work': work.path,
        'master': edition.path,
        'acquisition': acquisition_path,
    }.items():
        resolved = resolve_path(path)
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise PipelineError('accepted authority outside root') from exc
        try:
            digest = _hash(io_path(resolved).read_bytes())
        except OSError as exc:
            raise PipelineError(f'cannot read accepted {key} authority: {resolved}') from exc
        authority[key] = {'path': relative, 'sha256': digest}
    return {
        'root': root,
        'acceptance_path': acceptance_path,
        'accepted': accepted,
        'identity': {key: identity[key] for key in ('work_id', 'textual_form_id', 'edition_id')},
        'language': language,
        'representation_revision': accepted['representation_revision']['id'],
        'edition_title': edition.title,
        'work': work,
        'edition': edition,
        'authority': authority,
    }


def project_accepted_prayers(root, *, acceptance_path):
    """Project a promoted accepted prayer master with authority-derived context."""
    context = _accepted_context(root, acceptance_path)
    from ocd_kernel.projection.categories.native_documents import select_accepted_source_lines_profile
    source_lines_profile = select_accepted_source_lines_profile(root, context)
    if source_lines_profile is not None:
        from ocd_kernel.projection.categories.native_documents import project_accepted_document
        return project_accepted_document(root, acceptance_path=acceptance_path,
                                         category='prayers', projection_profile=source_lines_profile)
    if context['identity'] == {'work_id': 'bcp-1662-collects', 'textual_form_id': 'bcp-1662-collects-retained-electronic', 'edition_id': 'bcp-1662-collects-retained-electronic-witness'}:
        from ocd_kernel.projection.categories.native_documents import project_accepted_document
        return project_accepted_document(root, acceptance_path=acceptance_path, category='prayers')
    if _uses_native_anthology(context['edition'].path):
        from ocd_kernel.projection.categories.native_documents import project_accepted_document
        return project_accepted_document(root, acceptance_path=acceptance_path, category='prayers')
    result = project_prayers_document(
        context['edition'].path,
        identity=context['identity'],
        language=context['language'],
        representation_revision=context['representation_revision'],
        edition_title=context['edition_title'],
        _allow_acceptance_metadata=True,
    )
    result['receipt']['authority'] = context['authority']
    result['receipt']['scope'] = 'tei-document; context derived from validated acceptance'
    return result


def verify_accepted_prayers(root, *, acceptance_path, rows, receipt):
    """Verify accepted prayer rows independently of the category producer."""
    try:
        context = _accepted_context(root, acceptance_path)
        from ocd_kernel.projection.categories.native_documents import select_accepted_source_lines_profile
        source_lines_profile = select_accepted_source_lines_profile(root, context)
        if source_lines_profile is not None:
            from ocd_kernel.projection.categories.native_documents import verify_accepted_document
            return verify_accepted_document(root, acceptance_path=acceptance_path,
                                            rows=rows, receipt=receipt, category='prayers',
                                            projection_profile=source_lines_profile)
        if context['identity'] == {'work_id': 'bcp-1662-collects', 'textual_form_id': 'bcp-1662-collects-retained-electronic', 'edition_id': 'bcp-1662-collects-retained-electronic-witness'}:
            from ocd_kernel.projection.categories.native_documents import verify_accepted_document
            return verify_accepted_document(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt, category='prayers')
        if _uses_native_anthology(context['edition'].path):
            from ocd_kernel.projection.categories.native_documents import verify_accepted_document
            return verify_accepted_document(root, acceptance_path=acceptance_path,
                                            rows=rows, receipt=receipt, category='prayers')
        if not isinstance(receipt, dict):
            return ['accepted projection receipt must be an object']
        problems = []
        if receipt.get('authority') != context['authority']:
            problems.append('accepted authority bindings differ')
        if receipt.get('scope') != 'tei-document; context derived from validated acceptance':
            problems.append('accepted scope label differs')
        document_receipt = dict(receipt)
        document_receipt.pop('authority', None)
        document_receipt['scope'] = 'tei-document; caller-supplied context'
        problems.extend(verify_prayers_document(
            context['edition'].path,
            rows,
            document_receipt,
            identity=context['identity'],
            language=context['language'],
            representation_revision=context['representation_revision'],
            edition_title=context['edition_title'],
            _allow_acceptance_metadata=True,
        ))
        return problems
    except (PipelineError, OSError, ValueError, KeyError, TypeError) as exc:
        return [str(exc)]
