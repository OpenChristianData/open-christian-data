"""Whole native sermon documents; closed structure and independent correspondence.

Document context is caller-supplied. Retained-source fidelity is a separate edge,
corroborated by the source oracle; no acceptance or publication is implied.
"""
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

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.lib.path_io import resolve_path
from ocd_kernel.projection.scripture_authority import BOOK_CODES_PATH, load_book_codes
from ocd_kernel.projection.scripture_targets import normalize_reference_record
from ocd_kernel.projection.scripture_targets_check import observe_reference_record

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / 'schemas/v2/categories/sermons.schema.json'
COMMON = ROOT / 'schemas/v2/public-row.schema.json'
NS = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'

# The category profile deliberately keeps its ordinary document envelope
# narrow.  An accepted master also needs the common acceptance handoff facts
# (identity, source binding, and revision) in its TEI header.  Keep those
# header-only carriers out of the normal document route while allowing the
# accepted wrapper to account for and exclude them explicitly. The richer
# fields below are observed in the retained Occom and Baxter TCP headers;
# header references are bibliographic/license links, not sermon scripture.
_ACCEPTANCE_HEADER_ELEMENTS = {
    'TEI': ['teiHeader', 'text'],
    'teiHeader': ['fileDesc', 'encodingDesc', 'profileDesc', 'revisionDesc'],
    'fileDesc': ['titleStmt', 'editionStmt', 'extent', 'publicationStmt', 'seriesStmt', 'notesStmt', 'sourceDesc'],
    'titleStmt': ['title', 'author', 'editor', 'respStmt', 'sponsor', 'funder', 'principal', 'meeting'],
    'respStmt': ['resp', 'name', 'persName'],
    'resp': [],
    'name': ['ref'],
    'hi': [],
    'lb': [],
    'author': ['name', 'persName', 'forename', 'surname'],
    'editor': ['name', 'persName', 'forename', 'surname', 'roleName', 'orgName'],
    'persName': ['name', 'forename', 'surname'],
    'forename': [],
    'surname': [],
    'roleName': [],
    'orgName': [],
    'sponsor': [],
    'funder': [],
    'principal': [],
    'meeting': [],
    'title': [],
    'editionStmt': ['edition', 'p'],
    'edition': ['date'],
    'extent': [],
    'publicationStmt': ['p', 'publisher', 'pubPlace', 'date', 'idno', 'availability', 'authority', 'distributor'],
    'authority': [],
    'distributor': [],
    'publisher': [],
    'pubPlace': [],
    'date': [],
    'availability': ['p', 'licence'],
    'licence': ['p'],
    'p': ['ref', 'seg'],
    'ref': [],
    'seriesStmt': ['title', 'biblScope'],
    'biblScope': [],
    'notesStmt': ['note'],
    'sourceDesc': ['p', 'bibl', 'biblFull', 'listWit', 'listBibl', 'listPerson'],
    'biblFull': ['titleStmt', 'extent', 'publicationStmt', 'seriesStmt', 'notesStmt'],
    'bibl': ['title', 'author', 'editor', 'publisher', 'respStmt', 'edition', 'pubPlace', 'date', 'idno', 'ptr', 'note', 'ref', 'name', 'biblScope'],
    'idno': [],
    'ptr': [],
    'note': ['seg', 'list', 'label', 'p', 'hi', 'lb', 'ref'],
    'seg': ['seg'],
    'list': ['item'],
    'item': [],
    'revisionDesc': ['change'],
    'change': ['date', 'label', 'ref'],
    'label': [],
    'encodingDesc': ['p', 'projectDesc', 'editorialDecl', 'listPrefixDef', 'tagsDecl', 'charDecl', 'refsDecl', 'classDecl', 'schemaRef', 'variantEncoding'],
    'charDecl': ['char'],
    'char': ['desc', 'mapping'],
    'classDecl': ['taxonomy'],
    'taxonomy': ['bibl', 'category'],
    'category': ['catDesc'],
    'catDesc': [],
    'schemaRef': [],
    'variantEncoding': [],
    'desc': [],
    'mapping': [],
    'tagsDecl': ['rendition'],
    'rendition': [],
    'projectDesc': ['p'],
    'editorialDecl': ['p', 'interpretation', 'normalization', 'punctuation'],
    'interpretation': ['p'],
    'normalization': ['p'],
    'punctuation': ['p'],
    'listPrefixDef': ['prefixDef'],
    'prefixDef': [],
    'profileDesc': ['langUsage', 'textClass', 'creation'],
    'creation': ['date', 'placeName'],
    'placeName': [],
    'langUsage': ['language'],
    'language': [],
    'textClass': ['keywords'],
    'keywords': ['term'],
    'term': [],
    'refsDecl': ['cRefPattern'],
    'cRefPattern': ['p'],
    'listWit': ['head', 'witness', 'listWit'],
    'head': ['abbr'],
    'witness': ['abbr', 'hi', 'locus', 'name', 'origDate'],
    'abbr': ['hi'],
    'locus': [],
    'origDate': [],
    'listBibl': ['head', 'bibl', 'biblStruct', 'listBibl'],
    'biblStruct': ['analytic', 'monogr', 'series', 'ref'],
    'analytic': ['title', 'author', 'editor'],
    'monogr': ['title', 'author', 'editor', 'imprint', 'idno'],
    'series': ['title', 'biblScope'],
    'imprint': ['publisher', 'pubPlace', 'biblScope', 'date', 'note'],
    'listPerson': ['person'],
    'person': ['persName'],
}
_ACCEPTANCE_HEADER_ATTRIBUTES = {
    'teiHeader': ['xml:lang'],
    'bibl': ['type', 'corresp', 'facs'],
    'biblScope': ['unit', 'from', 'to'],
    'biblStruct': ['type', 'facs'],
    'cRefPattern': ['n', 'matchPattern', 'replacementPattern'],
    'change': ['xml:id', 'when', 'who'],
    'availability': ['status'],
    'licence': ['target'],
    'title': ['type', 'xml:lang', 'level'],
    'idno': ['type'],
    'ptr': ['target'],
    'note': ['type', 'corresp', 'subtype', 'n', 'rend', 'source'],
    'p': ['ana'],
    'name': ['type', 'key'],
    'author': ['ref'],
    'editor': ['role'],
    'publisher': ['xml:lang'],
    'edition': ['n'],
    'mapping': ['type'],
    'hi': ['rend'],
    'seg': ['type', 'subtype', 'n', 'corresp'],
    'list': ['type'],
    'item': ['n', 'corresp'],
    'revisionDesc': ['status'],
    'rendition': ['xml:id', 'scheme', 'selector'],
    'date': ['when', 'type', 'n', 'notAfter', 'notBefore'],
    'term': ['type'],
    'ref': ['target', 'type'],
    'prefixDef': ['ident', 'matchPattern', 'replacementPattern'],
    'language': ['ident'],
    'keywords': ['scheme'],
    'abbr': ['type'],
    'locus': ['from', 'to'],
    'origDate': ['notAfter', 'notBefore'],
    'persName': ['key', 'ref'],
    'placeName': ['ref'],
    'refsDecl': ['n'],
    'schemaRef': ['key', 'url'],
    'variantEncoding': ['location', 'method'],
    'witness': ['corresp', 'source'],
}


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _schema(*, native_first=False):
    schema=json.loads(SCHEMA.read_text(encoding='utf-8'))
    common=json.loads(COMMON.read_text(encoding='utf-8'))
    native=json.loads((ROOT / 'schemas/v2/native-content.schema.json').read_text(encoding='utf-8'))
    registry=Registry().with_resources((document['$id'],Resource.from_contents(document,default_specification=DRAFT202012)) for document in (common,native))
    selected = {**schema, 'oneOf': list(reversed(schema['oneOf']))} if native_first else schema
    return schema,projection_validator(selected,registry=registry)


def project_sermons_document(tei_path, *, identity, language, representation_revision, edition_title,
                             _allow_acceptance_metadata=False):
    raw=Path(tei_path).read_bytes();scan=raw.replace(b'\x00',b'')
    if any(t in scan.upper() for t in (b'<!DOCTYPE',b'<!ENTITY',b'<!--')) or re.search(br'<\?(?!xml(?:\s|\?>))',scan,re.I):
        raise PipelineError('unsupported-visible: declarations/comments/instructions')
    try:root=ET.fromstring(raw)
    except ET.ParseError as exc:raise PipelineError(f'invalid sermon TEI: {exc}') from exc
    if root.find(NS+'text/'+NS+'front') is not None:
        from ocd_kernel.projection.categories.native_documents import project_document
        return project_document(tei_path, identity=identity, language=language,
                                representation_revision=representation_revision, edition_title=edition_title,
                                _allow_acceptance_metadata=_allow_acceptance_metadata)
    schema,validator=_schema();policy=schema['x-ocd-profile']
    inventory=[];warnings=[];exclusions=[];ids=set()
    def inventory_node(node,header=False):
        if not node.tag.startswith(NS):raise PipelineError('unsupported-visible: namespace')
        tag=node.tag[len(NS):]
        header=header or tag=='teiHeader'
        elements = (_ACCEPTANCE_HEADER_ELEMENTS if _allow_acceptance_metadata and header
                    else policy['elements'])
        attributes = (_ACCEPTANCE_HEADER_ATTRIBUTES if _allow_acceptance_metadata and header
                       else policy['attributes'])
        if tag not in elements:raise PipelineError(f'unsupported-visible: {tag}')
        for key in node.attrib:
            name='xml:'+key[len(XML):] if key.startswith(XML) else key
            if name not in attributes.get(tag,[]):raise PipelineError(f'unsupported-visible: {tag}@{name}')
        if tag == 'text' and XML+'lang' in node.attrib and not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', node.get(XML+'lang')):
            raise PipelineError('unsupported-visible: document language tag')
        if node.get(XML+'id'):
            if node.get(XML+'id') in ids:raise PipelineError('duplicate native identity')
            ids.add(node.get(XML+'id'))
        if tag=='hi' and node.get('rend') not in policy['renditions']:raise PipelineError('unsupported-visible: rendition')
        if tag=='div' and node.get('type') not in policy['division_types']:raise PipelineError('unsupported-visible: division type')
        if tag=='ref' and not (_allow_acceptance_metadata and header) and (node.get('type') not in ('primary','incidental') or not node.get('cRef')):raise PipelineError('unsupported-visible: scripture role or locus')
        if tag=='ab' and node.get('type')!='scripture-reference':raise PipelineError('unsupported-visible: block role')
        if tag=='rs' and node.get('type')!='occasion':raise PipelineError('unsupported-visible: named field')
        if tag in ('TEI','teiHeader','fileDesc','titleStmt','publicationStmt','sourceDesc','bibl','revisionDesc','text','body','div','opener'):
            if (node.text or '').strip() or any((c.tail or '').strip() for c in node):raise PipelineError('unsupported-visible: loose structural text')
        ordinal=len(inventory)+1
        role=policy['roles']['header' if header else 'text']
        inventory.append({'ordinal':ordinal,'tag':tag,'attributes':dict(node.attrib),'text_sha256':_digest((node.text or '').encode()),'tail_sha256':_digest((node.tail or '').encode()),'role':role})
        if header:exclusions.append({'ordinal':ordinal,'reason':role})
        if tag == 'text' and node.get(XML+'lang'):
            warnings.append({'ordinal':ordinal,'reason':policy['roles']['document_language']})
        if tag in ('hi','foreign') and not header:warnings.append({'ordinal':ordinal,'reason':policy['roles']['typography' if tag=='hi' else 'foreign']})
        for c in node:
            if not c.tag.startswith(NS) or c.tag[len(NS):] not in elements[tag]:raise PipelineError(f'unsupported-visible: child of {tag}')
            inventory_node(c,header)
    inventory_node(root)
    if root.tag!=NS+'TEI' or [c.tag for c in root]!=[NS+'teiHeader',NS+'text'] or [c.tag for c in root.find(NS+'text')]!=[NS+'body']:
        raise PipelineError('unsupported-visible: document envelope')
    def plain(node,omit_notes=False):
        chunks = []
        def visit(current):
            if current.text:
                chunks.append(current.text)
            for child in current:
                if child.tag == NS+'note' and omit_notes:
                    preceding = next((part[-1] for part in reversed(chunks) if part), '')
                    if preceding and child.tail and not preceding.isspace() and not child.tail[0].isspace():
                        raise PipelineError('unsupported-visible: adjacent note boundary')
                else:
                    visit(child)
                if child.tail:
                    chunks.append(child.tail)
        visit(node)
        return ''.join(chunks)
    def norm(node):return ' '.join(plain(node).split()) if node is not None else None
    def block(node):
        tag=node.tag[len(NS):]
        if tag not in policy['block_kinds']:raise PipelineError('unsupported-visible: nested block')
        result={'kind':policy['block_kinds'][tag],'number':node.get('n'),'text':'','notes':[],'references':[],'children':[]}
        if tag=='div':
            if node.get('type')!='section':raise PipelineError('unsupported-visible: nested sermon')
            result['children']=[block(c) for c in node]
        else:
            result['text']=' '.join(plain(node,True).split())
            result['notes']=[{'label':n.get('n'),'text':norm(n),'place':n.get('place')} for n in node.iter(NS+'note')]
            result['references']=[{'label':norm(r),'locus':r.get('cRef')} for r in node.iter(NS+'ref') if r.get('type')=='incidental']
        return result
    book_codes = load_book_codes()
    rows=[];anchors=[]
    for order,unit in enumerate(root.find(NS+'text').find(NS+'body'),1):
        if unit.get('type')!='sermon' or not unit.get(XML+'id'):raise PipelineError('unsupported-visible: native sermon identity')
        heads=unit.findall(NS+'head');openers=unit.findall(NS+'opener')
        if not heads or len(openers)!=1 or len(openers[0])!=1 or openers[0][0].get('type')!='primary':raise PipelineError('unsupported-visible: heading or primary passage')
        primary=openers[0][0]
        for reference in unit.iter(NS+'ref'):
            if reference.get('type')=='primary' and reference.get('cRef')!=primary.get('cRef'):raise PipelineError('unsupported-visible: conflicting primary scripture')
        structure=[block(c) for c in unit if c.tag!=NS+'opener']
        def flatten(items):
            return [text for b in items for text in ([b['text']] if not b['children'] else flatten(b['children']))]
        delivery_notes=[n for n in unit.iter(NS+'note') if n.find(NS+'date') is not None or n.find(NS+'placeName') is not None or n.find(NS+'rs') is not None]
        if len(delivery_notes)>1:raise PipelineError('unsupported-visible: multiple delivery statements')
        delivery={'statement':None,'date':None,'place':None,'occasion':None}
        if delivery_notes:
            note=delivery_notes[0];delivery['statement']=norm(note)
            for key,tag in [('date','date'),('place','placeName'),('occasion','rs')]:
                found=note.findall(NS+tag)
                if len(found)>1:raise PipelineError('unsupported-visible: delivery cardinality')
                delivery[key]=norm(found[0]) if found else None
        collections=root.findall('.//'+NS+'teiHeader/'+NS+'fileDesc/'+NS+'sourceDesc/'+NS+'bibl/'+NS+'title')
        if len(collections)>1:raise PipelineError('unsupported-visible: multiple collections')
        row={k:identity[k] for k in ('work_id','textual_form_id','edition_id')}
        row.update(record_id=identity['edition_id']+':sermon:'+_digest(unit.get(XML+'id').encode())[:20],sequence=order,category='sermons',language=language,representation_revision=representation_revision,provenance={'edition_title':edition_title},locator={'kind':'sermon','number':unit.get('n'),'headings':[' '.join(plain(h,True).split()) for h in heads]},primary_passage=norm(primary),collection=norm(collections[0]) if collections else None,delivery=delivery,structure=structure,text='\n\n'.join(flatten(structure)))
        row['primary_reference'] = normalize_reference_record({'raw': norm(primary), **{k: primary.get(k) for k in ('cRef', 'target') if primary.get(k) is not None}}, book_codes=book_codes)
        errors=list(validator.iter_errors(row))
        if errors:raise PipelineError(f'invalid sermon row: {errors[0].message}')
        rows.append(row);anchors.append({'unit_id':unit.get(XML+'id'),'record_id':row['record_id'],'text_sha256':_digest(row['text'].encode())})
    if not rows:raise PipelineError('empty sermon scope')
    receipt={'scope':'tei-document; caller-supplied context','mapping_version':policy['version'],'master_sha256':_digest(raw),'schema_sha256':_digest(SCHEMA.read_bytes()),'common_schema_sha256':_digest(COMMON.read_bytes()),'book_codes_sha256':_digest(BOOK_CODES_PATH.read_bytes()),'output_sha256':_digest(_json(rows)),'row_count':len(rows),'anchors':anchors,'inventory':inventory,'warnings':warnings,'exclusions':exclusions,'unsupported':[],'independent_check':{'status':'pending'}}
    return {'rows':rows,'receipt':receipt}


def verify_sermons_document(tei_path,rows,receipt,*,identity,language,representation_revision,edition_title,
                            _allow_acceptance_metadata=False):
    """Independently rebuild every public field and receipt from lxml observations."""
    try:
        raw=Path(tei_path).read_bytes();doc=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True))
        if doc.getroottree().docinfo.doctype or doc.xpath('//comment() | //processing-instruction()'):return ['unsupported-visible: declarations/comments/instructions']
        if doc.find(NS+'text/'+NS+'front') is not None:
            from ocd_kernel.projection.categories.native_documents import verify_document
            return verify_document(tei_path, rows, receipt, identity=identity, language=language,
                                   representation_revision=representation_revision, edition_title=edition_title,
                                   _allow_acceptance_metadata=_allow_acceptance_metadata)
        schema=json.loads(SCHEMA.read_text(encoding='utf-8'));policy=schema['x-ocd-profile'];ns={'t':NS[1:-1]}
        inventory=[];warnings=[];exclusions=[];ids=[]
        for i,node in enumerate(doc.xpath('descendant-or-self::*'),1):
            q=etree.QName(node);tag=q.localname
            header=bool(node.xpath('ancestor-or-self::t:teiHeader',namespaces=ns))
            elements = (_ACCEPTANCE_HEADER_ELEMENTS if _allow_acceptance_metadata and header
                        else policy['elements'])
            attributes = (_ACCEPTANCE_HEADER_ATTRIBUTES if _allow_acceptance_metadata and header
                          else policy['attributes'])
            if q.namespace!=ns['t'] or tag not in elements:raise ValueError('unsupported-visible: tag/namespace')
            attrs={('xml:'+etree.QName(k).localname if k.startswith(XML) else k) for k in node.attrib}
            if attrs-set(attributes.get(tag,[])):raise ValueError('unsupported-visible: attribute')
            if tag == 'text' and XML+'lang' in node.attrib and not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', node.get(XML+'lang')):
                raise ValueError('unsupported-visible: document language tag')
            if node.get(XML+'id'):ids.append(node.get(XML+'id'))
            if tag=='hi' and node.get('rend') not in policy['renditions']:raise ValueError('unsupported-visible: rendition')
            if tag=='div' and node.get('type') not in policy['division_types']:raise ValueError('unsupported-visible: division type')
            if tag=='ref' and not (_allow_acceptance_metadata and header) and (node.get('type') not in ('primary','incidental') or not node.get('cRef')):raise ValueError('unsupported-visible: scripture role/locus')
            if tag=='ab' and node.get('type')!='scripture-reference':raise ValueError('unsupported-visible: block role')
            if tag=='rs' and node.get('type')!='occasion':raise ValueError('unsupported-visible: named field')
            if any(etree.QName(c).namespace!=ns['t'] or etree.QName(c).localname not in elements[tag] for c in node):raise ValueError('unsupported-visible: child structure')
            if tag in ('TEI','teiHeader','fileDesc','titleStmt','publicationStmt','sourceDesc','bibl','revisionDesc','text','body','div','opener') and any(str(x).strip() for x in node.xpath('text()')):raise ValueError('unsupported-visible: loose structural text')
            role=policy['roles']['header' if header else 'text']
            inventory.append({'ordinal':i,'tag':tag,'attributes':dict(node.attrib),'text_sha256':hashlib.sha256((node.text or '').encode()).hexdigest(),'tail_sha256':hashlib.sha256((node.tail or '').encode()).hexdigest(),'role':role})
            if header:exclusions.append({'ordinal':i,'reason':role})
            if tag == 'text' and node.get(XML+'lang'):
                warnings.append({'ordinal':i,'reason':policy['roles']['document_language']})
            if tag in ('hi','foreign') and not header:warnings.append({'ordinal':i,'reason':policy['roles']['typography' if tag=='hi' else 'foreign']})
        if len(ids)!=len(set(ids)):raise ValueError('duplicate native identity')
        if doc.tag!=NS+'TEI' or [c.tag for c in doc]!=[NS+'teiHeader',NS+'text'] or [c.tag for c in doc.find(NS+'text')]!=[NS+'body']:raise ValueError('unsupported-visible: envelope')
        def text(node,without_notes=False):
            if node is None:return None
            words=node.xpath('.//text()[not(ancestor::t:note)]' if without_notes else './/text()',namespaces=ns)
            if without_notes:
                for note in node.xpath('.//t:note',namespaces=ns):
                    if not note.tail:
                        continue
                    tail_position = next((i for i, value in enumerate(words) if value.is_tail and value.getparent() is note), None)
                    # XPath text nodes include text inside preceding inline elements.
                    # Restrict the prefix to this block, excluding note content.
                    preceding = ''.join(words[:tail_position]) if tail_position is not None else ''
                    if preceding and not preceding[-1].isspace() and not note.tail[0].isspace():raise ValueError('unsupported-visible: adjacent note boundary')
            return ' '.join(''.join(words).split())
        def describe(node):
            tag=etree.QName(node).localname
            if tag=='div':
                if node.get('type')!='section':raise ValueError('unsupported-visible: nested sermon')
                return {'kind':policy['block_kinds'][tag],'number':node.get('n'),'text':'','notes':[],'references':[],'children':[describe(c) for c in node.xpath('*')]}
            return {'kind':policy['block_kinds'][tag],'number':node.get('n'),'text':text(node,True),'notes':[{'label':n.get('n'),'text':text(n),'place':n.get('place')} for n in node.xpath('.//t:note',namespaces=ns)],'references':[{'label':text(r),'locus':r.get('cRef')} for r in node.xpath('.//t:ref[@type="incidental"]',namespaces=ns)],'children':[]}
        book_codes = load_book_codes()
        expected=[];anchors=[]
        for order,unit in enumerate(doc.xpath('t:text/t:body/t:div',namespaces=ns),1):
            if unit.get('type')!='sermon' or not unit.get(XML+'id'):raise ValueError('unsupported-visible: native sermon identity')
            heads=unit.xpath('t:head',namespaces=ns);opening=unit.xpath('t:opener',namespaces=ns)
            if not heads or len(opening)!=1 or len(opening[0])!=1 or opening[0][0].get('type')!='primary':raise ValueError('unsupported-visible: heading/primary scripture')
            primary=opening[0][0]
            if any(r.get('cRef')!=primary.get('cRef') for r in unit.xpath('.//t:ref[@type="primary"]',namespaces=ns)):raise ValueError('unsupported-visible: primary scripture conflict')
            blocks=[describe(c) for c in unit.xpath('t:head | t:p | t:div | t:ab',namespaces=ns)]
            ordered_text=[]
            for event,node in etree.iterwalk(unit,events=('start',)):
                if node.tag in (NS+'head',NS+'p',NS+'ab'):ordered_text.append(text(node,True))
            delivery={'statement':None,'date':None,'place':None,'occasion':None}
            notes=unit.xpath('.//t:note[t:date or t:placeName or t:rs]',namespaces=ns)
            if len(notes)>1:raise ValueError('unsupported-visible: delivery cardinality')
            if notes:
                delivery['statement']=text(notes[0])
                for key,tag in [('date','date'),('place','placeName'),('occasion','rs')]:
                    values=notes[0].xpath('t:'+tag,namespaces=ns)
                    if len(values)>1:raise ValueError('unsupported-visible: delivery field cardinality')
                    delivery[key]=text(values[0]) if values else None
            collections=doc.xpath('t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:title',namespaces=ns)
            if len(collections)>1:raise ValueError('unsupported-visible: multiple collections')
            row={'work_id':identity['work_id'],'textual_form_id':identity['textual_form_id'],'edition_id':identity['edition_id'],'record_id':identity['edition_id']+':sermon:'+hashlib.sha256(unit.get(XML+'id').encode()).hexdigest()[:20],'sequence':order,'category':'sermons','language':language,'representation_revision':representation_revision,'provenance':{'edition_title':edition_title},'locator':{'kind':'sermon','number':unit.get('n'),'headings':[text(h,True) for h in heads]},'primary_passage':text(primary),'collection':text(collections[0]) if collections else None,'delivery':delivery,'structure':blocks,'text':'\n\n'.join(ordered_text)}
            row['primary_reference'] = observe_reference_record({'raw': text(primary), **{k: primary.get(k) for k in ('cRef', 'target') if primary.get(k) is not None}}, book_codes=book_codes)
            expected.append(row);anchors.append({'unit_id':unit.get(XML+'id'),'record_id':row['record_id'],'text_sha256':hashlib.sha256(row['text'].encode()).hexdigest()})
        if not expected:raise ValueError('empty sermon scope')
        errors=[] if rows==expected else ['sermon correspondence: identity/order/text/structure differs']
        wanted={'scope':'tei-document; caller-supplied context','mapping_version':policy['version'],'master_sha256':hashlib.sha256(raw).hexdigest(),'schema_sha256':hashlib.sha256(SCHEMA.read_bytes()).hexdigest(),'common_schema_sha256':hashlib.sha256(COMMON.read_bytes()).hexdigest(),'book_codes_sha256':hashlib.sha256(BOOK_CODES_PATH.read_bytes()).hexdigest(),'output_sha256':hashlib.sha256(json.dumps(expected,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'row_count':len(expected),'anchors':anchors,'inventory':inventory,'warnings':warnings,'exclusions':exclusions,'unsupported':[],'independent_check':{'status':'pending'}}
        if receipt!=wanted:errors.append('sermon receipt differs from independent observations')
        common=json.loads(COMMON.read_text(encoding='utf-8'));native=json.loads((ROOT / 'schemas/v2/native-content.schema.json').read_text(encoding='utf-8'))
        registry=Registry().with_resources((document['$id'],Resource.from_contents(document,default_specification=DRAFT202012)) for document in (common,native))
        validator=projection_validator(schema,registry=registry)
        for row in rows:errors.extend('schema: '+e.message for e in validator.iter_errors(row))
        return errors
    except (OSError,ValueError,KeyError,TypeError,etree.XMLSyntaxError) as exc:return [str(exc)]


def _accepted_context(root, acceptance_path, *, expected_category="sermons"):
    """Resolve the canonical promoted edition and its authority bindings."""
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
    if category != expected_category:
        holy_images = (
            expected_category == 'prose' and category is None and identity == {
                'work_id': 'pg49917-holy-images',
                'textual_form_id': 'pg49917-holy-images-english',
                'edition_id': 'pg49917-holy-images-pg49917-edition',
                'acquisition_id': 'pg49917-holy-images-pg49917-acquisition',
            }
        )
        if not holy_images:
            raise PipelineError('accepted sermons category mismatch')
        from ocd_kernel.projection.categories.native_documents import HOLY_IMAGES_PROFILE
        from ocd_kernel.projection.categories.prose import _accepted_projection_profile

        if _accepted_projection_profile(root, {'accepted': accepted}) != HOLY_IMAGES_PROFILE:
            raise PipelineError('Holy Images accepted prose profile differs')
    language = resolve_edition_language(work.record, edition.record, edition.textual_form_id)
    if not isinstance(language, str) or not language:
        raise PipelineError('accepted sermons language is missing from the canonical edition')
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
            digest = _digest(io_path(resolved).read_bytes())
        except OSError as exc:
            raise PipelineError(f'cannot read accepted {key} authority: {resolved}') from exc
        authority[key] = {'path': relative, 'sha256': digest}
    context = {
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
    return context


def project_accepted_sermons(root, *, acceptance_path):
    """Project a promoted accepted sermon master with authority-derived context."""
    context = _accepted_context(root, acceptance_path)
    from ocd_kernel.projection.categories import maclaren_native
    if maclaren_native.route(context):
        return maclaren_native.project(context)
    if context['identity']['edition_id'] in {
        'george-whitefield-sermons-ccel-retained-electronic',
        'george-whitefield-sermons-gutenberg-retained-electronic',
    }:
        from ocd_kernel.projection.categories.whitefield_retained import project
        result = project(context['edition'].path, identity=context['identity'],
                         language=context['language'],
                         representation_revision=context['representation_revision'],
                         edition_title=context['edition_title'])
        result['receipt']['authority'] = context['authority']
        return result
    from ocd_kernel.projection.categories.prose import _accepted_projection_profile
    from ocd_kernel.projection.categories.lib040_augustine_selected import PROFILE as SELECTED_PROFILE
    profile = _accepted_projection_profile(root, context)
    if profile == SELECTED_PROFILE:
        from ocd_kernel.projection.categories.lib040_augustine_selected import project
        return project(root, acceptance_path=acceptance_path, category='sermons')
    from ocd_kernel.projection.categories import native_documents
    if context['identity']['work_id'] == 'spurgeon-mtp':
        return native_documents.project_accepted_document(
            root, acceptance_path=acceptance_path, category='sermons', collection=False)
    if native_documents.is_source_collection(context['edition'].path):
        return native_documents.project_accepted_document(root, acceptance_path=acceptance_path, category='sermons', collection=True)
    result = project_sermons_document(
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


def verify_accepted_sermons(root, *, acceptance_path, rows, receipt):
    """Verify accepted sermon rows independently of the category producer."""
    try:
        context = _accepted_context(root, acceptance_path)
        from ocd_kernel.projection.categories import maclaren_native
        if maclaren_native.route(context):
            return maclaren_native.verify(context, rows, receipt)
        if context['identity']['edition_id'] in {
            'george-whitefield-sermons-ccel-retained-electronic',
            'george-whitefield-sermons-gutenberg-retained-electronic',
        }:
            from ocd_kernel.projection.categories.whitefield_retained import verify
            if not isinstance(receipt, dict) or receipt.get('authority') != context['authority']:
                return ['Whitefield accepted authority bindings differ']
            return verify(context['edition'].path, rows, receipt,
                          identity=context['identity'], language=context['language'],
                          representation_revision=context['representation_revision'],
                          edition_title=context['edition_title'])
        from ocd_kernel.projection.categories.prose import _accepted_projection_profile
        from ocd_kernel.projection.categories.lib040_augustine_selected import PROFILE as SELECTED_PROFILE
        profile = _accepted_projection_profile(root, context)
        if profile == SELECTED_PROFILE:
            from ocd_kernel.projection.categories.lib040_augustine_selected import verify
            return verify(root, acceptance_path=acceptance_path, category='sermons', rows=rows, receipt=receipt)
        from ocd_kernel.projection.categories import native_documents
        if context['identity']['work_id'] == 'spurgeon-mtp':
            return native_documents.verify_accepted_document(
                root, acceptance_path=acceptance_path, rows=rows, receipt=receipt,
                category='sermons', collection=False)
        if native_documents.is_source_collection(context['edition'].path):
            return native_documents.verify_accepted_document(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt, category='sermons', collection=True)
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
        problems.extend(verify_sermons_document(
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
