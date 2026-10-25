"""Independent lxml observations for ordered native content and readable text."""
from __future__ import annotations
from ocd_kernel.projection.categories import strong_vol2_source_lines as strong_source
from ocd_kernel.projection.categories import coppens_pg70790_source_profile as coppens_source
from ocd_kernel.projection.categories import cassiodorus_source_profile as cass_source
from ocd_kernel.projection.categories import woolman_pg37311_source_profile as woolman_source

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote, quote

import jsonschema
import jsonschema_rs
from functools import lru_cache
from jsonschema.validators import extend
from referencing.exceptions import NoSuchResource
from lxml import etree

SCHEMA = Path(__file__).resolve().parents[2] / 'schemas/v2/native-content.schema.json'
TEI = 'http://www.tei-c.org/ns/1.0'
XML = 'http://www.w3.org/XML/1998/namespace'
CAREY_PROFILE = 'ocd-prose-carey-pg11449-grouped-tables-v1'
BCP_HTML_PROFILE = 'ocd-liturgies-bcp-retained-html-v1'
HODGE_PROFILE = 'ocd-prose-hodge-theology1-retained-volume-v1'
ELMSLIE_CHOICE_PROFILE = 'ocd-prose-elmslie-pg71811-abbreviation-choice-v1'
HOLY_IMAGES_PROFILE = 'ocd-prose-pg49917-holy-images-v1'
PETER_JONES_PROFILE = 'ocd-prose-peter-jones-1860-source-markers-v1'
AMERICAN_MISSIONARY_PROFILE = 'ocd-prose-american-missionary-monthly-issues-v1'
MARK_PROFILE = 'ocd-commentary-chadwick-mark-source-native-v1'
MTP_PROFILE = 'ocd-sermons-spurgeon-mtp-source-native-v1'
GUYON_PROFILE = 'ocd-prose-guyon-pg24989-v16-source-native-v1'
SAMUEL_PROFILE = 'ocd-prose-tyerman-samuel-pg67980-source-native-v1'
_SAMUEL_GRAPHICS = {
    'img_images_cover.jpg': ('images/cover.jpg', '48ab74695d1a7afcd0b99994df7e76c758e2bb2e242809ff337d8a41fdcf1339'),
    'img_images_i_004.jpg': ('images/i_004.jpg', 'b1ff1f378f7025e4219485d7df4b2b0742a4c3688ee44ef45b9fb8022b2c927b'),
}
_SAMUEL_ARCHIVE = 'a745273a2a6d5bdc0b036cb2b946dc9440b58edf74e6ff24ed8e700ee6995fc7'
BENNETT_CHRONICLES_PROFILE = 'ocd-commentary-bennett-chronicles-source-colgroup-v1'
THOME_PROFILE = 'ocd-prose-thome-pg70704-source-native-v1'
MOODY_PROFILE = 'ocd-prose-moody-pg61883-source-native-v1'
COPPENS_PROFILE = coppens_source.PROFILE
HYMNARY_PROFILE = 'ocd-hymns-hymnary-retained-csv-source-record-v1'
_HYMNARY_GLYPHS = {
    '#hymnary-control-0008': '[source control U+0008]',
    '#hymnary-control-000f': '[source control U+000F]',
    '#hymnary-control-0010': '[source control U+0010]',
}
FOX_PROFILE = 'ocd-prose-fox-pg43031-source-native-v1'
WOOLMAN_PROFILE = woolman_source.PROFILE
PTA_ANONYMOUS_VITA_PROFILE = 'ocd-prose-pta-anonymous-vita-standalone-sic-v1'
PTA_HESYCHIUS_PROFILE = 'ocd-prose-pta-hesychius-empty-sic-v1'
SOURCE_LINES_PROFILE = 'ocd-prose-source-attested-lines-v1'
SOURCE_LINES_BLOCK_TYPES = frozenset({'source-line', 'section-start', 'page-marker',
    'page-url', 'page-title', 'display-heading'})
FOX_GRAPHICS = {
    'img_images_title_page.jpg': ('images/title_page.jpg', 'source-alt:titlepage', '4.1'),
    'img_images_i_004.jpg': ('images/i_004.jpg', 'source-alt:GEORGE FOX', '8.1'),
    'img_images_logo1.jpg': ('images/logo1.jpg', 'source-alt:logo', '13.1'),
    'img_images_i_011.jpg': ('images/i_011.jpg', 'source-alt:map', '28.1'),
    'img_images_i_066.jpg': ('images/i_066.jpg', 'source-alt:Signature George Fox', '122.1'),
    'img_images_i_498.jpg': ('images/i_498.jpg', 'source-alt:America', '1638.1'),
}
FOX_BLOCKS = {'source-header','source-div','source-footer','source-hr','source-p','source-blockquote','source-h1','source-h2','source-h3'}
_MOODY_BLOCKS = {'source-header', 'source-div', 'source-footer', 'source-hr', 'source-p', 'source-blockquote'}
_MOODY_TBODY = {'source-tbody-start', 'source-tbody-end'}
_FOX_TBODY = {'source-tbody-start', 'source-tbody-end'}
from ocd_kernel.projection.categories import tyerman_whitefield_source_profile as whitefield_source
WHITEFIELD_PROFILE = whitefield_source.PROFILE
STRONG_PROFILE = strong_source.PROFILE
_GUYON_BLOCKS = {'source-tail-text', 'source-div-leading-text',
                 'source-inline-carrier', 'source-hr'}
_GUYON_TBODY = {'source-tbody-start', 'source-tbody-end'}
_GUYON_DOTTED = r'[1-9][0-9]*(?:\.[1-9][0-9]*)+'
_GUYON_LOCATOR = r'[1-9][0-9]*(?:\.[1-9][0-9]*)*'
_MARK_BLOCKS = {'heading', 'scripture-commentary'}
_MTP_SOURCE_BASES = {
    'https://answersingenesis.org/education/spurgeon-sermons/708-the-blood-of-abel-and-the-blood-of-jesus/',
    'https://answersingenesis.org/education/spurgeon-sermons/3032-form-of-this-world/',
    'https://archive.spurgeon.org/',
}
_AMERICAN_MISSIONARY_BLOCKS = {'direct-text', 'html-span', 'html-a', 'html-em', 'html-b', 'html-i', 'html-cite'}
PETER_JONES_MARKERS = {'unretained-media-reference', 'unexpanded-source-template', 'source-rule'}


NATIVE_SCHEMA_ID = 'ocd://schemas/v2/native-content.schema.json'


@lru_cache(maxsize=4)
def _compiled(serialized):
    try:
        return jsonschema_rs.Draft202012Validator(json.loads(serialized), offline=True)
    except jsonschema_rs.ValidationError as error:
        raise jsonschema.SchemaError(str(error)) from error


def _native_validator(schema):
    return _compiled(json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


def native_content_errors(schema, instance):
    """Validate fresh content; retain the original errors for rejected instances."""
    try:
        valid = _native_validator(schema).is_valid(instance)
    except (TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        yield from jsonschema.Draft202012Validator(schema).iter_errors(instance)


def projection_validator(schema, *, registry, format_checker=None):
    """Accelerate only the closed native-content reference in a row schema."""
    try:
        native = _native_validator(registry.contents(NATIVE_SCHEMA_ID))
    except NoSuchResource:
        return jsonschema.Draft202012Validator(schema, registry=registry, format_checker=format_checker)
    original_ref = jsonschema.Draft202012Validator.VALIDATORS['$ref']

    def native_ref(validator, reference, instance, current_schema):
        if reference == NATIVE_SCHEMA_ID:
            try:
                if native.is_valid(instance):
                    return
            except (TypeError, ValueError, OverflowError):
                pass
        yield from original_ref(validator, reference, instance, current_schema)

    validator_class = extend(jsonschema.Draft202012Validator, {'$ref': native_ref})
    return validator_class(schema, registry=registry, format_checker=format_checker)


def _observe_bcp_row_span(node: etree._Element) -> None:
    span = node.get('rows', '')
    token = node.get('ana', '')
    match = re.fullmatch(r'urn:ocd:bcp(1549|1559):html:(.+)', token)
    if (match is None
            or not node.get('{'+XML+'}id', '').startswith('bcp'+match[1]+'-')):
        raise ValueError('BCP source span profile identity/value differs')
    def distinct(items):
        names = set()
        for key, _ in items:
            if key in names:
                raise ValueError('BCP source span duplicate JSON key')
            names.add(key)
        return dict(items)
    try:
        source = json.loads(unquote(match[2], errors='strict'), object_pairs_hook=distinct)
    except (ValueError, UnicodeError) as exc:
        raise ValueError('BCP source span annotation cannot be decoded') from exc
    if (not isinstance(source, dict) or sorted(source) != ['attributes', 'tag']
            or source['tag'] != 'td' or not isinstance(source['attributes'], list)
            or quote(json.dumps(source, ensure_ascii=False, separators=(',', ':')), safe='') != match[2]):
        raise ValueError('BCP source span annotation envelope differs')
    observed = {}
    for pair in source['attributes']:
        if (not isinstance(pair, list) or len(pair) != 2
                or not all(isinstance(value, str) for value in pair)
                or pair[0] in observed):
            raise ValueError('BCP source span original attributes differ')
        observed[pair[0]] = pair[1]
    if 'rowspan' not in observed and node.get('rows') is None:
        return
    if re.fullmatch(r'[1-9][0-9]*', span) is None or observed.get('rowspan') != span:
        raise ValueError('BCP source span differs from literal HTML rowspan')



def _observe_hodge_row_span(node: etree._Element) -> None:
    """Check literal span eligibility independently of the native producer."""
    token = node.get('ana', '')
    marker = 'urn:ocd:hodge-theology1:ThML:'
    identifier = node.get('{'+XML+'}id', '')
    if (not token.startswith(marker)
            or re.fullmatch(r'hodge-systematic-theology-vol-1-(?:feature|complete)-[0-9]{6}', identifier) is None):
        raise ValueError('Hodge source span identity differs')
    def distinct(items):
        names = set()
        for key, _ in items:
            if key in names:
                raise ValueError('duplicate Hodge span JSON key')
            names.add(key)
        return dict(items)
    payload = token[len(marker):]
    try:
        record = json.loads(unquote(payload, errors='strict'), object_pairs_hook=distinct)
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Hodge source span annotation cannot be decoded') from exc
    if (not isinstance(record, dict) or tuple(record) != ('tag', 'attributes')
            or record['tag'] not in ('td', 'th') or not isinstance(record['attributes'], list)
            or payload != quote(json.dumps(record, ensure_ascii=False, separators=(',', ':')), safe='')):
        raise ValueError('Hodge source span annotation envelope differs')
    original = {}
    for pair in record['attributes']:
        if (not isinstance(pair, list) or len(pair) != 2
                or not all(isinstance(value, str) for value in pair)
                or pair[0] in original or pair[0] not in ('id', 'rowspan', 'colspan', 'style')):
            raise ValueError('Hodge source span original attributes differ')
        original[pair[0]] = pair[1]
    if not original.get('id'):
        raise ValueError('Hodge source span original attributes differ')
    if ((record['tag'] == 'th' and node.get('role') != 'label')
            or (record['tag'] == 'td' and node.get('role') is not None)):
        raise ValueError('Hodge source cell header role differs')
    if record['tag'] == 'th' and ('rowspan' in original or node.get('rows') is not None):
        raise ValueError('Hodge source header cell cannot carry a row span')
    if 'rowspan' not in original and node.get('rows') is None:
        return
    value = node.get('rows', '')
    if re.fullmatch(r'[1-9][0-9]*', value) is None or original.get('rowspan') != value:
        raise ValueError('Hodge source span differs from literal source rowspan')


WESLEY_PROFILE = 'ocd-sermons-wesley-ccel-native-v1'


def observe_content(fragment: bytes, *, source_profile: str | None = None,
                    source_base: str | None = None, _schema: dict | None = None) -> tuple[dict, str]:
    """Observe a subtree independently for category-level correspondence checks."""
    if source_profile not in (None, CAREY_PROFILE, ELMSLIE_CHOICE_PROFILE, HOLY_IMAGES_PROFILE,
                              PETER_JONES_PROFILE, BCP_HTML_PROFILE, HODGE_PROFILE,
                              AMERICAN_MISSIONARY_PROFILE, MARK_PROFILE, MTP_PROFILE,
                              GUYON_PROFILE, SAMUEL_PROFILE, MOODY_PROFILE, COPPENS_PROFILE, WHITEFIELD_PROFILE, STRONG_PROFILE, THOME_PROFILE, BENNETT_CHRONICLES_PROFILE, cass_source.PROFILE, HYMNARY_PROFILE, FOX_PROFILE, WOOLMAN_PROFILE, PTA_ANONYMOUS_VITA_PROFILE, PTA_HESYCHIUS_PROFILE, WESLEY_PROFILE, SOURCE_LINES_PROFILE):
        raise ValueError('unsupported native content source profile')
    document = etree.fromstring(fragment, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    if document.getroottree().docinfo.doctype or document.xpath('//comment() | //processing-instruction()'):
        raise ValueError('unsupported native declaration/comment/instruction')
    schema = json.loads(SCHEMA.read_text(encoding='utf-8')) if _schema is None else _schema
    policy = dict(schema['x-ocd-native-content'])
    if source_profile == BENNETT_CHRONICLES_PROFILE:
        policy['milestone_kinds'] = dict(policy['milestone_kinds']) | {'source-colgroup': 'source-marker'}
    if source_profile == WESLEY_PROFILE:
        policy['source_block_types'] = list(policy['source_block_types']) + ['thml-h2', 'thml-h3']
    if source_profile == SOURCE_LINES_PROFILE:
        policy['source_block_types'] = list(policy['source_block_types']) + sorted(SOURCE_LINES_BLOCK_TYPES)
    if source_profile == THOME_PROFILE:
        policy['source_block_types'] = list(policy['source_block_types']) + ['source-header','source-div','source-footer','source-hr','source-p']
        policy['milestone_kinds'] = dict(policy['milestone_kinds']) | {'source-tbody-start':'source-marker','source-tbody-end':'source-marker'}
    if source_profile == cass_source.PROFILE:
        policy = cass_source.extend_policy(policy)
    if source_profile == FOX_PROFILE:
        policy = dict(policy)
        policy['source_block_types'] = list(policy['source_block_types']) + sorted(FOX_BLOCKS)
    if source_profile == WOOLMAN_PROFILE:
        policy = dict(policy)
        policy['source_block_types'] = list(policy['source_block_types']) + sorted(woolman_source.BLOCK_TYPES)
    source_ids = {
        node.get('{'+XML+'}id') for node in document.iter()
        if isinstance(node.tag, str) and node.get('{'+XML+'}id')
    }
    built = {}
    for node in reversed(list(document.iter())):
        name = etree.QName(node)
        if name.namespace != TEI or name.localname not in policy['elements']:
            raise ValueError('unsupported native element or namespace')
        rule = policy['elements'][name.localname]
        if name.localname in {'sic', 'corr'} and (
                node.getparent() is None or node.getparent().tag != '{'+TEI+'}choice'):
            parent = node.getparent()
            pta_variant = (source_profile == PTA_ANONYMOUS_VITA_PROFILE
                           and name.localname == 'sic' and parent is not None
                           and parent.tag == '{'+TEI+'}seg'
                           and any(child.tag == '{'+TEI+'}app'
                                   and child.get('type') == 'variants' for child in node))
            hesychius_empty = (source_profile == PTA_HESYCHIUS_PROFILE
                               and name.localname == 'sic' and parent is not None
                               and parent.tag == '{'+TEI+'}p'
                               and not node.attrib and node.text is None and not len(node))
            if not (pta_variant or hesychius_empty):
                raise ValueError('native correction alternatives require a choice parent')
        if source_profile == STRONG_PROFILE:
            parent = node.getparent()
            strong_source.check_content_node(node, etree.QName(parent).localname if parent is not None else None)
        if source_profile == cass_source.PROFILE:
            cass_source.check_content_node_lxml(node)
        if name.localname == 'ref' and node.get('{'+XML+'}base') is not None:
            target = node.get('target') or ''
            mtp_link = (source_profile == MTP_PROFILE and source_base is None
                        and node.get('type') == 'source-link'
                        and node.get('{'+XML+'}base') in _MTP_SOURCE_BASES
                        and target.startswith('/') and not any(char.isspace() for char in target))
            expositor_link = (node.get('{'+XML+'}base') == source_base and source_base
                              and re.fullmatch(r'https://www\.ccel\.org/ccel/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+\.html', source_base)
                              and re.fullmatch(r'\?scrBook=[A-Za-z0-9]+&scrCh=[0-9]+&scrV=[0-9]+#[A-Za-z0-9_.-]+', target))
            if not (mtp_link or expositor_link):
                raise ValueError('native source reference base or literal target differs')
        if name.localname == 'sp':
            visible_children = [child for child in node if child.tag != '{'+TEI+'}pb']
            if (len(visible_children) < 2 or visible_children[0].tag != '{'+TEI+'}speaker'
                    or any(child.tag == '{'+TEI+'}speaker' for child in visible_children[1:])
                    or (node.text or '').strip() or any((child.tail or '').strip() for child in node)):
                raise ValueError('native speech lacks one leading speaker or spoken content')
        if name.localname == 'speaker' and (node.getparent() is None
                                             or node.getparent().tag != '{'+TEI+'}sp'
                                             or not ''.join(node.itertext()).strip()):
            raise ValueError('native speaker lacks a speech or label')
        if name.localname == 'app' and ((node.text or '').strip()
                                        or any((child.tail or '').strip() for child in node)):
            raise ValueError('critical-apparatus text is outside lemma or reading')
        if name.localname == 'choice':
            if source_profile == WHITEFIELD_PROFILE:
                whitefield_source.choice_lxml(node)
            children = list(node)
            correction = [child.tag for child in children] == ['{'+TEI+'}sic', '{'+TEI+'}corr']
            if correction:
                if (source_profile not in (None, BENNETT_CHRONICLES_PROFILE) or dict(node.attrib) or (node.text or '').strip()
                        or any((child.tail or '').strip() for child in children)
                        or any(dict(child.attrib) for child in children) or len(children[0])
                        or not (children[0].text or '').strip()
                        or not ''.join(children[1].itertext()).strip()
                        or any(not (child.tag == '{'+TEI+'}hi' and dict(child.attrib) == {'rend': 'italic'}
                                    or child.tag == '{'+TEI+'}ref' and set(child.attrib) == {'target'}
                                    and re.fullmatch(r'#[A-Za-z_][A-Za-z0-9_.-]*', child.get('target', '')))
                               or len(child) or not (child.text or '').strip() for child in children[1])):
                    raise ValueError('native correction choice differs')
            elif (source_profile not in (None, BENNETT_CHRONICLES_PROFILE, ELMSLIE_CHOICE_PROFILE, WHITEFIELD_PROFILE) or (dict(node.attrib) and source_profile != WHITEFIELD_PROFILE)
                    or [child.tag for child in children] != ['{'+TEI+'}abbr', '{'+TEI+'}expan']
                    or node.text or any(child.tail for child in children)
                    or not ''.join(children[0].itertext()).strip()
                    or not (children[1].text or '').strip() or len(children[1])
                    or dict(children[1].attrib)):
                raise ValueError('Elmslie abbreviation choice differs')
        if name.localname == 'abbr' and node.get('n') not in (None, 'source-html-class:spell'):
            raise ValueError('unsupported abbreviation source class')
        if name.localname == 'title' and ('type' in node.attrib or 'n' in node.attrib):
            number = node.get('n') or ''
            if (source_profile not in (GUYON_PROFILE, FOX_PROFILE)
                    or set(node.attrib) != {'{'+XML+'}id', 'type', 'n'}
                    or node.get('type') != 'source-citation'
                    or re.fullmatch(_GUYON_DOTTED, number) is None
                    or node.get('{'+XML+'}id') != 'source-node-'+number
                    or len(node) or not (node.text or '').strip()):
                raise ValueError('observed Guyon source citation title differs')
        if name.localname == 'ab' and source_profile == GUYON_PROFILE and node.get('type') in _GUYON_BLOCKS:
            number = node.get('n') or ''
            kind = node.get('type')
            expected = ('source-node-'+number if kind == 'source-hr' else
                        kind+'-'+number.removesuffix('.tail').removesuffix('.text'))
            shape = (re.fullmatch(_GUYON_LOCATOR, number[:-5]) is not None
                     if kind in {'source-tail-text', 'source-div-leading-text'} else
                     number == '3' if kind == 'source-hr' else
                     re.fullmatch(_GUYON_DOTTED, number) is not None)
            attrs = ({'type', 'n', '{'+XML+'}id', '{'+XML+'}space'} if kind in
                     {'source-tail-text', 'source-div-leading-text'} else
                     {'type', 'n', '{'+XML+'}id', 'rend'} if kind == 'source-hr' else
                     {'type', 'n', '{'+XML+'}id'})
            if (source_profile != GUYON_PROFILE or not shape or set(node.attrib) != attrs
                    or node.get('{'+XML+'}id') != expected
                    or kind in {'source-tail-text', 'source-div-leading-text'}
                    and (node.get('{'+XML+'}space') != 'preserve' or len(node))
                    or kind == 'source-inline-carrier' and
                    (len(node) != 1 or etree.QName(node[0]).localname not in {'ref', 'seg', 'lb'})
                    or kind == 'source-hr' and
                    (node.get('rend') != 'source-class:pg' or len(node)
                     or (node.text or '').strip())):
                raise ValueError('observed Guyon source block carrier differs')
        if name.localname == 'space':
            line = node.get('n') or ''
            prefix = 'carey-enquiry' if source_profile == CAREY_PROFILE else 'wilberforce-practical-view'
            last_line = 2073 if source_profile == CAREY_PROFILE else 10820
            if (set(node.attrib) != {'{'+XML+'}id', 'type', 'unit', 'quantity', 'n', 'subtype'}
                    or not line.isdecimal() or not 1 <= int(line) <= last_line
                    or node.get('{'+XML+'}id') != f'{prefix}-blank-{int(line):05d}'
                    or node.get('type') != 'source-blank-line'
                    or node.get('unit') != 'line' or node.get('quantity') != '1'
                    or node.get('subtype') != 'crlf' or len(node) or (node.text or '').strip()):
                raise ValueError('source blank-line carrier differs')
        if name.localname == 'head' and node.get('type') == 'source-located-heading':
            line = node.get('n') or ''
            prefix = 'carey-enquiry' if source_profile == CAREY_PROFILE else 'wilberforce-practical-view'
            last_line = 1751 if source_profile == CAREY_PROFILE else 10820
            levels = {'1', '2', '3'} if source_profile == CAREY_PROFILE else {'1', '2'}
            if (not line.isdecimal() or not 1 <= int(line) <= last_line
                    or node.get('{'+XML+'}id') != f'{prefix}-heading-{int(line):05d}'
                    or node.get('subtype') not in levels):
                raise ValueError('source heading carrier differs')
        if name.localname in {'table', 'row', 'cell'}:
            if source_profile == GUYON_PROFILE and name.localname == 'table':
                number = node.get('n') or ''
                start, end = (node[0], node[-1]) if len(node) >= 2 else (None, None)
                if (number not in {'6.11.1', '6.15.1'}
                        or node.get('{'+XML+'}id') != 'source-node-'+number
                        or start is None or etree.QName(start).localname != 'milestone'
                        or start.get('unit') != 'source-tbody-start'
                        or start.get('n') != number+'.1'
                        or etree.QName(end).localname != 'milestone'
                        or end.get('unit') != 'source-tbody-end'
                        or end.get('n') != number+'.1.end'
                        or any(etree.QName(child).localname != 'row' for child in node[1:-1])):
                    raise ValueError('observed Guyon source table structure differs')
            if source_profile == GUYON_PROFILE and name.localname == 'cell':
                number = node.get('n') or ''
                if (node.getparent() is None or etree.QName(node.getparent()).localname != 'row'
                        or re.fullmatch(_GUYON_DOTTED, number) is None
                        or node.get('{'+XML+'}id') != 'source-node-'+number
                        or node.get('cols') not in (None, '3')
                        or node.get('role') is not None):
                    raise ValueError('observed Guyon source cell DOM locator differs')
            if source_profile == AMERICAN_MISSIONARY_PROFILE:
                if name.localname == 'row':
                    numbered = [int(child.get('n')) for child in node
                                if etree.QName(child).localname == 'cell'
                                and child.get('n') is not None
                                and re.fullmatch(r'[1-9][0-9]*', child.get('n') or '')]
                    if numbered != sorted(set(numbered)):
                        raise ValueError('American Missionary source cell numbers differ in row')
                if name.localname == 'cell':
                    number = node.get('n')
                    identifier = node.get('{'+XML+'}id')
                    if (node.getparent() is None or node.getparent().tag != '{'+TEI+'}row'
                            or node.get('role') != 'data'
                            or (number is None) != (identifier is None)
                            or number is not None and (re.fullmatch(r'[1-9][0-9]*', number) is None
                                or not identifier.endswith(f'B{int(number):05d}'))):
                        raise ValueError('American Missionary source cell identity differs')
            if (name.localname == 'cell' and source_profile != BCP_HTML_PROFILE
                    and node.get('ana', '').startswith(
                        ('urn:ocd:bcp1549:html:', 'urn:ocd:bcp1559:html:'))):
                raise ValueError('BCP retained HTML annotation requires its source profile')
            if (name.localname == 'cell' and source_profile != HODGE_PROFILE
                    and node.get('ana', '').startswith('urn:ocd:hodge-theology1:ThML:')):
                raise ValueError('Hodge source annotation requires its source profile')
            if name.localname == 'cell' and source_profile == HODGE_PROFILE:
                if node.getparent() is None or node.getparent().tag != '{'+TEI+'}row':
                    raise ValueError('Hodge source cell requires a row parent')
                _observe_hodge_row_span(node)
            if (name.localname == 'cell' and source_profile == BCP_HTML_PROFILE
                    and node.get('ana', '').startswith(('urn:ocd:bcp1549:html:', 'urn:ocd:bcp1559:html:'))):
                _observe_bcp_row_span(node)
            if name.localname == 'cell' and node.get('rows') is not None:
                if node.getparent() is None or node.getparent().tag != '{'+TEI+'}row':
                    raise ValueError('native cell row span requires a row parent')
                if source_profile == HODGE_PROFILE:
                    _observe_hodge_row_span(node)
                elif source_profile == BCP_HTML_PROFILE:
                    _observe_bcp_row_span(node)
                elif source_profile not in (None, BENNETT_CHRONICLES_PROFILE) or not re.fullmatch(r'[1-9][0-9]*', node.get('rows') or ''):
                    raise ValueError('unsupported native attribute: cell@rows')
            new_attributes = {'table': {'rows', 'cols'}, 'row': {'role'}, 'cell': {'n'}}[name.localname]
            if source_profile != CAREY_PROFILE and not (
                    source_profile in (AMERICAN_MISSIONARY_PROFILE, MOODY_PROFILE, THOME_PROFILE, FOX_PROFILE, WOOLMAN_PROFILE) and name.localname == 'cell'
                    and new_attributes.intersection(node.attrib) <= {'n'}
            ) and not (
                    source_profile == GUYON_PROFILE and name.localname == 'cell'
                    and new_attributes.intersection(node.attrib) <= {'n'}
            ) and not (
                    source_profile == cass_source.PROFILE and name.localname == 'cell'
                    and new_attributes.intersection(node.attrib) <= {'n','cols'}
            ) and new_attributes.intersection(node.attrib):
                raise ValueError('unsupported native attribute')
            if source_profile == CAREY_PROFILE:
                if name.localname == 'table':
                    if (not (node.get('rows') or '').isdecimal() or int(node.get('rows')) != len(node)
                            or node.get('cols') not in {'5', '6'} or any(etree.QName(child).localname != 'row' for child in node)):
                        raise ValueError('Carey table dimensions or rows differ')
                    if any(
                        not (cell.get('n') or '').isdecimal()
                        or not 1 <= int(cell.get('n')) <= int(node.get('cols'))
                        for row in node for cell in row if etree.QName(cell).localname == 'cell'
                    ):
                        raise ValueError('Carey table column position exceeds dimensions')
                if name.localname == 'row':
                    if node.get('role') not in {
                        'data', 'continuation', 'source-blank-line', 'footnote',
                        'table-superheading', 'column-headings', 'unit-headings',
                        'table-note', 'group-heading', 'data-group-heading',
                        'column-subheadings',
                    } or not len(node) or any(etree.QName(child).localname != 'cell' for child in node):
                        raise ValueError('Carey table row role or cells differ')
                    positions = [child.get('n') or '' for child in node]
                    if (any(not value.isdecimal() for value in positions)
                            or [int(value) for value in positions] != sorted({int(value) for value in positions})):
                        raise ValueError('Carey table cell positions differ')
                if name.localname == 'cell' and not (node.get('n') or '').isdecimal():
                    raise ValueError('Carey table cell position differs')
        if name.localname == 'ab' and re.fullmatch(r'source[-_]h[1-6]', node.get('type') or ''):
            heading_style = node.get('rend')
            if heading_style is not None and not heading_style.strip():
                raise ValueError('unsupported native attribute')
        samuel_column = (name.localname == 'milestone' and source_profile == SAMUEL_PROFILE
                         and node.get('unit') == 'source-column')
        if samuel_column and (set(node.attrib) != {'unit', 'style'}
                              or re.fullmatch(r'width: (?:[1-9]|[1-9][0-9]|100)%;', node.get('style') or '') is None):
            raise ValueError('observed Samuel source-column width differs')
        mark_marker = (name.localname == 'milestone' and source_profile == MARK_PROFILE
                       and node.get('unit') == 'source-index')
        guyon_tbody = name.localname == 'milestone' and source_profile == GUYON_PROFILE and node.get('unit') in _GUYON_TBODY
        moody_tbody = name.localname == 'milestone' and source_profile == MOODY_PROFILE and node.get('unit') in _MOODY_TBODY
        fox_tbody = name.localname == 'milestone' and source_profile in (FOX_PROFILE, WOOLMAN_PROFILE) and node.get('unit') in _FOX_TBODY
        if mark_marker and dict(node.attrib) not in (
                {'{'+XML+'}id': 'xix.i-p0.2', 'rend': 'source-type:scripRef', 'unit': 'source-index'},
                {'{'+XML+'}id': 'xix.ii-p0.2', 'rend': 'source-type:scripCom', 'unit': 'source-index'}):
            raise ValueError('observed Chadwick Mark source index marker differs')
        peter_blank_page = (source_profile == PETER_JONES_PROFILE and name.localname == 'gap'
                            and dict(node.attrib) == {'reason': 'blank', 'unit': 'page', 'extent': '1'}
                            and len(node) == 0 and not (node.text or '').strip())
        properties = {}
        source_attributes = {}
        attribute_rules = rule.get('attributes', {})
        whitefield_graphic = whitefield_source.graphic_lxml(node) if source_profile == WHITEFIELD_PROFILE and name.localname == 'graphic' else None
        if whitefield_graphic and whitefield_graphic[1]:
            properties['css_style'] = whitefield_graphic[1]
        for attribute, value in node.attrib.items():
            key = etree.QName(attribute)
            spelling = 'xml:' + key.localname if key.namespace == XML else attribute
            if source_profile == STRONG_PROFILE and name.localname == 'seg' and spelling == 'xml:space':
                if value != 'preserve':raise ValueError('Observed Strong II source-line whitespace differs')
                properties['whitespace'] = value
                continue
            if name.localname == 'graphic' and spelling == 'url' and source_profile == SAMUEL_PROFILE:
                selected = _SAMUEL_GRAPHICS.get(node.get('{'+XML+'}id'))
                if selected is None:
                    raise ValueError('unknown Samuel retained image')
                properties['source_target'] = 'retained-embedded-image:' + selected[0]
                continue
            if (source_profile == MOODY_PROFILE and name.localname == 'graphic'
                    and spelling in {'width', 'height'}
                    and node.get('url') in {'images/i_127.jpg', 'images/i_127a.jpg'}
                    and value == ('25px' if spelling == 'width' else '15px')):
                continue  # Retained exactly in the pinned TEI/source-node inventory.
            if source_profile == WHITEFIELD_PROFILE and spelling == 'ana':
                whitefield_source.annotation(value)
                continue  # Literal remains in independent private inventory.
            if (name.localname == 'anchor' and spelling == 'ana'
                    and (node.get('{'+XML+'}id') or '').startswith('bennett-expositorjer2-')):
                tokens = value.split(' ')
                prefix = 'urn:ccel:source-attribute:'
                names = ('id:', 'shape:', '%7Bhttp%3A%2F%2Fwww.w3.org%2FXML%2F1998%2Fnamespace%7Dlink:')
                if len(tokens) != 3 or any(not token.startswith(prefix+key) for token, key in zip(tokens, names)):
                    raise ValueError('observed Bennett Jeremiah II anchor annotation differs')
                observed_id = tokens[0][len(prefix+names[0]):]
                if (not re.fullmatch(r'[A-Za-z0-9_.-]+', observed_id)
                        or node.get('{'+XML+'}id') != 'bennett-expositorjer2-'+observed_id
                        or node.get('type') != 'source-anchor'
                        or tokens[1][len(prefix+names[1]):] != 'rect'
                        or tokens[2][len(prefix+names[2]):] != 'simple'):
                    raise ValueError('observed Bennett Jeremiah II anchor semantics differ')
                source_attributes.update({'id': observed_id, 'shape': 'rect', 'xml:link': 'simple'})
                continue
            if source_profile == WHITEFIELD_PROFILE and name.localname == 'choice' and spelling == 'xml:id':
                properties['source_anchor'] = whitefield_source.anchor(value)
                continue
            if source_profile == WHITEFIELD_PROFILE and name.localname == 'ref' and spelling == 'target' and value.startswith('#') and value[1:] in whitefield_source.ANCHORS:
                properties['source_target'] = '#'+whitefield_source.anchor(value[1:])
                continue
            if whitefield_graphic and spelling in {'url', 'width', 'height', 'style'}:
                if spelling == 'url':properties['source_target'] = whitefield_graphic[0]
                continue
            if name.localname == 'ab' and spelling == 'rend' and re.fullmatch(r'source[-_]h[1-6]', node.get('type') or '') and value in {'style:margin-top:12pt', 'style:margin-top:48pt'}:
                properties['style'] = value
                continue
            if name.localname == 'ab' and spelling == 'source' and source_profile == MARK_PROFILE:
                if (node.get('type') != 'scripture-commentary' or
                        re.fullmatch(r'urn:ccel-thml-parsed:%7CMark(?:%7C[0-9]+){4}(?:%3B%7CMark(?:%7C[0-9]+){4})*', value) is None):
                    raise ValueError('observed Chadwick Mark parsed-source carrier differs')
                continue  # The literal remains in independent private inventory.
            if spelling == 'unit' and (mark_marker or peter_blank_page or guyon_tbody or samuel_column or moody_tbody or name.localname == 'milestone' and source_profile == PETER_JONES_PROFILE and node.get('unit') in PETER_JONES_MARKERS):
                properties['unit'] = value
                continue
            if spelling not in attribute_rules:
                if spelling == 'xml:id':
                    continue
                if spelling == 'xml:lang':
                    properties['language'] = value
                    continue
                if spelling not in rule.get('source_attributes', ()):
                    raise ValueError('unsupported native attribute')
                source_attributes[spelling] = value
                continue
            field = attribute_rules[spelling]
            if field is not None:
                properties[field] = value
        if source_attributes:
            properties['source_attributes'] = source_attributes
        if rule.get('source_element'):
            properties['source_element'] = name.localname
        local = name.localname
        if local == 'graphic':
            if len(node) != 0 or (node.text or '').strip() or not (node.get('url') or '').strip():
                raise ValueError('native graphic lacks a unique empty image reference')
            coppens_graphic = (source_profile == COPPENS_PROFILE and local == 'graphic'
                               and coppens_source.graphic_allowed(node))
            if node.get('{'+XML+'}base') is not None or node.get('rend') is not None:
                url = node.get('url')
                layout = (url == 'images/indent.gif' and node.get('rend') == 'source-layout-spacer'
                          and node.get('n') == '    ')
                initial = (url == 'images/s.gif'
                           and node.get('rend') == 'source-initial-letter source-align-LEFT'
                           and node.get('n') is None)
                samuel_image = False
                if source_profile == SAMUEL_PROFILE:
                    identifier = node.get('{'+XML+'}id') or ''
                    expected = _SAMUEL_GRAPHICS.get(identifier)
                    samuel_image = (expected is not None and set(node.attrib) ==
                                    {'url', '{'+XML+'}id', 'corresp', 'n', 'rend'}
                                    and node.get('corresp') == f'urn:ocd:retained-archive:{_SAMUEL_ARCHIVE}:member:{expected[0]}'
                                    and node.get('n') == '' and node.get('rend') == 'ig001'
                                    and url.startswith('data:image/jpeg;base64,')
                                    and hashlib.sha256(url.encode()).hexdigest() == expected[1])
                    if not samuel_image:
                        raise ValueError('observed Samuel JPEG or archive binding differs')
                moody_alt = (source_profile == MOODY_PROFILE and node.get('{'+XML+'}base') is None
                             and node.get('rend') in {'source-alt-empty', 'source-alt:D. L. Moody.'})
                cass_graphic = (source_profile == cass_source.PROFILE and
                                cass_source.GRAPHICS.get(node.get('{'+XML+'}id')) == (url, node.get('rend')) and
                                set(node.attrib) == {'n','{'+XML+'}id','url','rend'})
                fox_expected = FOX_GRAPHICS.get(node.get('{'+XML+'}id') or '') if source_profile == FOX_PROFILE else None
                fox_image = (fox_expected is not None and node.get('{'+XML+'}base') is None
                             and set(node.attrib) == {'n', '{'+XML+'}id', 'url', 'rend'}
                             and (node.get('url'), node.get('rend'), node.get('n')) == fox_expected)
                if source_profile == FOX_PROFILE and not fox_image:
                    raise ValueError('observed Fox retained image reference differs')
                if (not samuel_image and not moody_alt and not coppens_graphic and not cass_graphic and not fox_image and (source_profile != MTP_PROFILE or node.get('{'+XML+'}base') != 'https://archive.spurgeon.org/'
                        or not (layout or initial) or not node.get('{'+XML+'}id'))):
                    raise ValueError('observed MTP literal image reference differs')
        if local in ('milestone', 'index', 'divGen'):
            if len(node) or (node.text or '').strip():
                raise ValueError('native marker contains content')
            peter_marker = local == 'milestone' and source_profile == PETER_JONES_PROFILE and node.get('unit') in PETER_JONES_MARKERS
            if moody_tbody:
                expected_n = '21.1' if node.get('unit') == 'source-tbody-start' else '21.1.end'
                if (node.getparent() is None or etree.QName(node.getparent()).localname != 'table'
                        or set(node.attrib) != {'unit', 'n', '{'+XML+'}id'}
                        or node.get('n') != expected_n or node.get('{'+XML+'}id') != 'source-node-'+expected_n):
                    raise ValueError('observed Moody source table boundary differs')
            if fox_tbody:
                number = node.get('n') or ''
                expected_end = node.get('unit') == 'source-tbody-end'
                if (node.getparent() is None or etree.QName(node.getparent()).localname != 'table'
                        or set(node.attrib) != {'unit', 'n', '{'+XML+'}id'}
                        or re.fullmatch(_GUYON_DOTTED + (r'\.end' if expected_end else ''), number) is None
                        or node.get('{'+XML+'}id') != 'source-node-'+number):
                    raise ValueError('observed Fox source table boundary differs')
            if guyon_tbody:
                number = node.get('n') or ''
                if (source_profile != GUYON_PROFILE or node.getparent() is None
                        or etree.QName(node.getparent()).localname != 'table'
                        or set(node.attrib) != {'unit', 'n', '{'+XML+'}id'}
                        or re.fullmatch(_GUYON_DOTTED + (r'\.end' if node.get('unit') == 'source-tbody-end' else ''), number) is None
                        or node.get('{'+XML+'}id') != 'source-node-'+number):
                    raise ValueError('observed Guyon source table boundary differs')
            if local == 'milestone' and source_profile == BENNETT_CHRONICLES_PROFILE and node.get('unit') == 'source-colgroup' and (
                    node.getparent() is None or etree.QName(node.getparent()).localname != 'table'
                    or dict(node.attrib) != {
                        '{'+XML+'}id': 'bennett-expositor10-iv.ii-p16.2', 'unit': 'source-colgroup', 'n': '2',
                        'ana': 'urn:ccel:source-attribute:id:iv.ii-p16.2 urn:ccel:source-attribute:span:2'}):
                raise ValueError('observed Bennett source column group differs')
            if local == 'milestone' and node.get('unit') == 'column_group':
                if node.getparent() is None or etree.QName(node.getparent()).localname != 'table':
                    raise ValueError('native column-group marker requires a table parent')
            if peter_marker and (set(node.attrib) != ({'unit'} if node.get('unit') == 'source-rule' else {'unit', 'n'})
                                 or node.get('unit') != 'source-rule' and not (node.get('n') or '').strip()):
                raise ValueError('Peter Jones source marker attributes differ')
            if local == 'milestone' and node.get('unit') not in policy['milestone_kinds'] and node.get('unit') != 'source-horizontal-rule' and not peter_marker and not mark_marker and not guyon_tbody and not fox_tbody and not (source_profile == WHITEFIELD_PROFILE and node.get('unit') == 'source-hr') and not samuel_column and not moody_tbody and not (source_profile == HOLY_IMAGES_PROFILE and node.get('unit') == 'source-html-comment' and set(node.attrib) == {'unit', 'n'} and re.fullmatch(r'[0-9a-f]{64}', node.get('n') or '')):
                raise ValueError('unsupported native milestone unit')
            if local == 'index' and node.get('indexName') is not None and node.get('indexName') not in policy['index_names']:
                raise ValueError('unsupported native index name')
            if local == 'divGen' and node.get('type') not in policy['generator_types']:
                raise ValueError('unsupported native generator placeholder')
        source_heading = None
        if local == 'ab' and re.fullmatch(r'source[-_]h[1-6]', node.get('type') or ''):
            if node.get('subtype') is not None:
                raise ValueError('source heading level conflicts with subtype')
            source_heading = node.get('type')[-2:]
        if (local == 'ab' and node.get('type') is not None
                and node.get('type') not in policy['source_block_types']
                and not (source_profile == AMERICAN_MISSIONARY_PROFILE
                         and node.get('type') in _AMERICAN_MISSIONARY_BLOCKS)
                and not (source_profile == MARK_PROFILE and node.get('type') in _MARK_BLOCKS)
                and not (source_profile == MTP_PROFILE and node.get('type') == 'source-flow')
                and not (source_profile == GUYON_PROFILE and node.get('type') in _GUYON_BLOCKS)
                and not (source_profile == MOODY_PROFILE and node.get('type') in _MOODY_BLOCKS)
                and not (source_profile == COPPENS_PROFILE and node.get('type') in coppens_source.PROFILE_BLOCK_TYPES)
                and not (source_profile == HYMNARY_PROFILE and node.get('type') == 'hymn-text')
                and not (source_profile == STRONG_PROFILE and node.get('type') in strong_source.BLOCK_COUNTS)
                and source_heading is None):
            raise ValueError('unsupported native source block type')
        if source_heading is not None:
            properties['type'] = 'source-heading'
            properties['subtype'] = source_heading[1:]
        if local == 'w' and source_profile == STRONG_PROFILE:
            own_id = node.get('{'+XML+'}id')
            references = (node.get('corresp') or '').split()
            if (any(child.tag != '{'+TEI+'}hi' for child in node)
                    or not ''.join(node.itertext()).strip() or not (node.get('lemma') or '').strip()
                    or not own_id or len(references) < 2
                    or f'#{own_id}' not in references
                    or any(not ref.startswith('#') or ref[1:] not in source_ids for ref in references)):
                raise ValueError('unsupported native word-segment linkage')
        if samuel_column or local == 'milestone' and node.get('unit') in policy['milestone_kinds'] and policy['milestone_kinds'][node.get('unit')] == 'source-marker':
            properties['unit'] = node.get('unit')
        if local == 'g':
            reference = node.get('ref')
            if (reference not in policy['glyphs'] and reference not in policy['source_declared_glyphs']
                    and not (source_profile == HYMNARY_PROFILE and reference in _HYMNARY_GLYPHS)) or len(node):
                raise ValueError('unsupported native glyph')
            if source_profile == HYMNARY_PROFILE and reference in _HYMNARY_GLYPHS and node.text != _HYMNARY_GLYPHS[reference]:
                raise ValueError('Hymnary source control glyph literal differs')
            if reference in policy['source_declared_glyphs'] and node.text != policy['source_declared_glyphs'][reference]:
                raise ValueError('source-declared glyph literal differs')
        if local in ('pb', 'lb', 'cb') and (len(node) or (node.text or '').strip()):
            raise ValueError('native milestone has content')
        marked_gap = local == 'gap' and len(node) == 0 and not (node.text or '').strip() and node.get('reason') == 'illegible' and bool((node.get('extent') or '').strip()) and bool((node.get('rend') or '').strip())
        source_byte_gap = (
            local == 'gap' and len(node) == 0 and not (node.text or '').strip()
            and node.get('reason') == 'unrepresentable'
            and re.fullmatch(r'[1-9][0-9]* bytes', node.get('extent') or '') is not None
            and node.get('ana') in {'#source-invalid-utf8', '#source-xml-1.0-forbidden-character'}
            and re.fullmatch(r'[0-9a-f]{64}', node.get('n') or '') is not None
            and bool(node.get('{'+XML+'}id'))
        )
        source_text_gap = (
            local == 'gap' and len(node) == 0 and not (node.text or '').strip()
            and node.get('reason') in {'damage', 'missing', 'illegible'}
            and node.get('unit') in {'word', 'character'}
            and re.fullmatch(r'[1-9][0-9]*', node.get('quantity') or '') is not None
        )
        if local == 'gap' and not marked_gap and not source_byte_gap and not source_text_gap and not peter_blank_page and (len(node) != 1 or node[0].tag != '{'+TEI+'}desc' or not ''.join(node[0].itertext()).strip()):
            raise ValueError('native gap has no unique description')
        supplied = (local == 'expan' and source_profile in (None, ELMSLIE_CHOICE_PROFILE, WHITEFIELD_PROFILE) and node.getparent() is not None
                    and node.getparent().tag == '{'+TEI+'}choice')
        if local == 'expan' and not supplied and ([child.tag for child in node] != ['{'+TEI+'}am', '{'+TEI+'}ex'] or (node.text or '').strip() or any((child.tail or '').strip() for child in node)):
            raise ValueError('native expansion structure differs')
        ordered = []
        if node.text:
            ordered.append({'kind': 'text', 'text': str(node.text)})
        for child in node:
            if not (source_profile == HOLY_IMAGES_PROFILE and child.tag == '{'+TEI+'}milestone' and child.get('unit') == 'source-html-comment'):
                ordered.append(built[child])
            if child.tail:
                ordered.append({'kind': 'text', 'text': str(child.tail)})
        kind = ('source-marker' if (samuel_column or guyon_tbody or moody_tbody or fox_tbody or source_profile == MARK_PROFILE and node.get('unit') == 'source-index'
                                    or source_profile == HOLY_IMAGES_PROFILE and node.get('unit') == 'source-html-comment'
                                    or source_profile == PETER_JONES_PROFILE and node.get('unit') in PETER_JONES_MARKERS - {'source-rule'})
                else 'horizontal-rule' if node.get('unit') == 'source-horizontal-rule' or source_profile == WHITEFIELD_PROFILE and node.get('unit') == 'source-hr'
                else policy['milestone_kinds'][node.get('unit')]) if local == 'milestone' else 'supplied-expansion' if supplied else rule['kind']
        if local == 'choice' and correction:
            kind = 'correction-choice'
        built[node] = {'kind': kind, 'attributes': properties, 'content': ordered}

    def source_text(node):
        tag = etree.QName(node).localname
        if tag == 'choice':
            return source_text(node[1] if node[0].tag == '{'+TEI+'}sic' else node[0])
        if tag == 'app':
            return ''.join(source_text(child) for child in node
                           if etree.QName(child).localname == 'lem')
        kind = ('source-marker' if ((source_profile == MOODY_PROFILE and node.get('unit') in _MOODY_TBODY) or source_profile == SAMUEL_PROFILE and node.get('unit') == 'source-column'
                                    or source_profile == GUYON_PROFILE and node.get('unit') in _GUYON_TBODY
                                    or source_profile in (FOX_PROFILE, WOOLMAN_PROFILE) and node.get('unit') in _FOX_TBODY
                                    or source_profile == MARK_PROFILE and node.get('unit') == 'source-index'
                                    or source_profile == HOLY_IMAGES_PROFILE and node.get('unit') == 'source-html-comment'
                                    or source_profile == PETER_JONES_PROFILE and node.get('unit') in PETER_JONES_MARKERS - {'source-rule'})
                else 'horizontal-rule' if node.get('unit') == 'source-horizontal-rule' or source_profile == WHITEFIELD_PROFILE and node.get('unit') == 'source-hr'
                else policy['milestone_kinds'][node.get('unit')]) if tag == 'milestone' else policy['elements'][tag]['kind']
        if kind in policy['text_omissions']:
            return ''
        if tag == 'g':
            return ((node.text or '').strip() or policy['glyphs'].get(node.get('ref'))
                    or policy['source_declared_glyphs'][node.get('ref')])
        if tag == 'lb':
            return '' if node.get('break') == 'no' else ' '
        if tag == 'gap' and len(node) == 0:
            if source_profile == PETER_JONES_PROFILE and dict(node.attrib) == {'reason': 'blank', 'unit': 'page', 'extent': '1'}:
                return ''
            if node.get('reason') == 'unrepresentable':
                return '[unrepresentable source bytes]'
            if (node.get('reason') in {'damage', 'missing', 'illegible'}
                    and node.get('unit') in {'word', 'character'}
                    and re.fullmatch(r'[1-9][0-9]*', node.get('quantity') or '')):
                quantity = node.get('quantity')
                unit = node.get('unit')
                suffix = '' if quantity == '1' else 's'
                return f"[{node.get('reason')}: {quantity} {unit}{suffix}]"
            return node.get('rend')
        if tag == 'expan' and node.getparent() is not None and node.getparent().tag == '{'+TEI+'}choice':
            return re.sub(r'\s+', ' ', node.text or '')
        if tag == 'expan':
            return source_text(node[1])
        parts = [re.sub(r'\s+', ' ', node.text or '')]
        for child in node:
            parts.extend((source_text(child), re.sub(r'\s+', ' ', child.tail or '')))
        value = ''.join(parts)
        if tag == 'l':
            return value.strip() + '\n'
        if kind in policy['block_boundaries']:
            return '\n\n' + value.strip() + '\n\n'
        return value

    expected_text = re.sub(r'\n{3,}', '\n\n', re.sub(r' *\n *', '\n', source_text(document))).strip()
    return built[document], expected_text


def verify_content(fragment: bytes, content: dict, text: str, *, source_profile: str | None = None,
                   source_base: str | None = None) -> list[str]:
    """Check a selected subtree; category selection and acceptance are separate."""
    try:
        expected, expected_text = observe_content(fragment, source_profile=source_profile,
                                                  source_base=source_base)
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        errors = []
        if content != expected:
            errors.append('native structure/text order or attributes differ from source')
        if text != expected_text:
            errors.append('native readable text differs from source rendering')
        errors.extend('native content schema: ' + error.message for error in native_content_errors(schema, content))
        return errors
    except (OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        return ['native content verification failed: ' + str(exc)]
