"""Ordered native mixed content for public category projections.

This module never edits TEI or establishes acceptance. Category projectors own
unit selection and bind this representation and its schema in their receipts.
"""
from __future__ import annotations
from ocd_kernel.projection.categories import strong_vol2_source_lines as strong_source
from ocd_kernel.projection.categories import coppens_pg70790_source_profile as coppens_source
from ocd_kernel.projection.categories import cassiodorus_source_profile as cass_source
from ocd_kernel.projection.categories import woolman_pg37311_source_profile as woolman_source

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, quote
import xml.etree.ElementTree as ET

from ocd_kernel.library._common import PipelineError

SCHEMA = Path(__file__).resolve().parents[2] / 'schemas/v2/native-content.schema.json'
NS = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'
CAREY_PROFILE = 'ocd-prose-carey-pg11449-grouped-tables-v1'
ELMSLIE_CHOICE_PROFILE = 'ocd-prose-elmslie-pg71811-abbreviation-choice-v1'
HOLY_IMAGES_PROFILE = 'ocd-prose-pg49917-holy-images-v1'
PETER_JONES_PROFILE = 'ocd-prose-peter-jones-1860-source-markers-v1'
BCP_HTML_PROFILE = 'ocd-liturgies-bcp-retained-html-v1'
HODGE_PROFILE = 'ocd-prose-hodge-theology1-retained-volume-v1'
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


def content_policy() -> dict[str, Any]:
    return json.loads(SCHEMA.read_text(encoding='utf-8'))['x-ocd-native-content']


def _bcp_source_row_span(node: ET.Element) -> None:
    """Require the literal HTML span annotation for this closed source profile."""
    value = node.get('rows') or ''
    annotation = node.get('ana') or ''
    prefix = next((f'urn:ocd:bcp{year}:html:' for year in (1549, 1559)
                   if annotation.startswith(f'urn:ocd:bcp{year}:html:')), None)
    if (prefix is None
            or not (node.get(XML+'id') or '').startswith(prefix.split(':')[2]+'-')):
        raise PipelineError('BCP retained HTML source row span identity/value differs')
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError('duplicate source annotation key')
            result[key] = item
        return result
    encoded = annotation[len(prefix):]
    try:
        original = json.loads(unquote(encoded, errors='strict'), object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise PipelineError('BCP retained HTML span annotation is invalid') from exc
    if (not isinstance(original, dict) or set(original) != {'tag', 'attributes'}
            or original['tag'] != 'td' or not isinstance(original['attributes'], list)
            or encoded != quote(json.dumps(original, ensure_ascii=False, separators=(',', ':')), safe='')):
        raise PipelineError('BCP retained HTML span annotation shape differs')
    pairs = original['attributes']
    if (any(not isinstance(pair, list) or len(pair) != 2
            or any(not isinstance(item, str) for item in pair) for pair in pairs)
            or len({pair[0] for pair in pairs}) != len(pairs)
            ):
        raise PipelineError('BCP retained HTML span original attribute shape differs')
    spans = [pair[1] for pair in pairs if pair[0] == 'rowspan']
    if not spans and node.get('rows') is None:
        return
    if not re.fullmatch(r'[1-9][0-9]*', value) or spans != [value]:
        raise PipelineError('BCP retained HTML span differs from literal source rowspan')



def _hodge_source_row_span(node: ET.Element) -> None:
    """Observe the literal source annotation; primary fidelity is a separate gate."""
    prefix = 'urn:ocd:hodge-theology1:ThML:'
    annotation = node.get('ana') or ''
    if (not annotation.startswith(prefix)
            or not re.fullmatch(r'hodge-systematic-theology-vol-1-(?:feature|complete)-[0-9]{6}', node.get(XML+'id') or '')):
        raise PipelineError('Hodge source span identity differs')
    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError('duplicate Hodge annotation key')
            result[name] = value
        return result
    encoded = annotation[len(prefix):]
    try:
        source = json.loads(unquote(encoded, errors='strict'), object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise PipelineError('Hodge source span annotation is invalid') from exc
    if (not isinstance(source, dict) or list(source) != ['tag', 'attributes']
            or source['tag'] not in ('td', 'th') or not isinstance(source['attributes'], list)
            or quote(json.dumps(source, ensure_ascii=False, separators=(',', ':')), safe='') != encoded):
        raise PipelineError('Hodge source span annotation shape differs')
    pairs = source['attributes']
    if (any(not isinstance(pair, list) or len(pair) != 2
            or any(not isinstance(value, str) for value in pair) for pair in pairs)
            or len({pair[0] for pair in pairs}) != len(pairs)
            or any(pair[0] not in {'id', 'rowspan', 'colspan', 'style'} for pair in pairs)
            or not dict(pairs).get('id')):
        raise PipelineError('Hodge source span original attributes differ')
    spans = [pair[1] for pair in pairs if pair[0] == 'rowspan']
    if ((source['tag'] == 'th' and node.get('role') != 'label')
            or (source['tag'] == 'td' and node.get('role') is not None)):
        raise PipelineError('Hodge source cell header role differs')
    if source['tag'] == 'th' and (spans or node.get('rows') is not None):
        raise PipelineError('Hodge source header cell cannot carry a row span')
    if not spans and node.get('rows') is None:
        return
    value = node.get('rows') or ''
    if not re.fullmatch(r'[1-9][0-9]*', value) or spans != [value]:
        raise PipelineError('Hodge source span differs from literal source rowspan')


def _bennett_jer2_anchor_attributes(node: ET.Element, annotation: str) -> dict[str, str]:
    """Expose Bennett's source anchor semantics without its private URN carrier."""
    prefix = 'bennett-expositorjer2-'
    identifier = node.get(XML+'id') or ''
    source_id = identifier.removeprefix(prefix)
    expected = (f'urn:ccel:source-attribute:id:{source_id} '
                'urn:ccel:source-attribute:shape:rect '
                'urn:ccel:source-attribute:%7Bhttp%3A%2F%2Fwww.w3.org%2FXML%2F1998%2Fnamespace%7Dlink:simple')
    if (not identifier.startswith(prefix) or not re.fullmatch(r'[A-Za-z0-9_.-]+', source_id)
            or node.get('type') != 'source-anchor' or annotation != expected):
        raise PipelineError('Bennett Jeremiah II source anchor differs')
    return {'id': source_id, 'shape': 'rect', 'xml:link': 'simple'}


WESLEY_PROFILE = 'ocd-sermons-wesley-ccel-native-v1'


def project_content(element: ET.Element, *, source_profile: str | None = None,
                    source_base: str | None = None, _policy: dict | None = None) -> dict[str, Any]:
    """Preserve text/tail order, nested native carriers and declared attributes.

    Whitespace text is retained in structured content, including inline spaces.
    Source identifiers and facsimile addresses belong in private node accounting,
    which the category caller must supply separately; they are never copied here.
    """
    if source_profile not in (None, CAREY_PROFILE, ELMSLIE_CHOICE_PROFILE, HOLY_IMAGES_PROFILE,
                              PETER_JONES_PROFILE, BCP_HTML_PROFILE, HODGE_PROFILE,
                              AMERICAN_MISSIONARY_PROFILE, MARK_PROFILE, MTP_PROFILE,
                              GUYON_PROFILE, SAMUEL_PROFILE, MOODY_PROFILE, COPPENS_PROFILE, WHITEFIELD_PROFILE, STRONG_PROFILE, THOME_PROFILE, BENNETT_CHRONICLES_PROFILE, cass_source.PROFILE, HYMNARY_PROFILE, FOX_PROFILE, WOOLMAN_PROFILE, PTA_ANONYMOUS_VITA_PROFILE, PTA_HESYCHIUS_PROFILE, WESLEY_PROFILE, SOURCE_LINES_PROFILE):
        raise PipelineError('unsupported native content source profile')
    policy = content_policy() if _policy is None else dict(_policy)
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
        policy['source_block_types'] = list(policy['source_block_types']) + sorted(FOX_BLOCKS)
    if source_profile == WOOLMAN_PROFILE:
        policy['source_block_types'] = list(policy['source_block_types']) + sorted(woolman_source.BLOCK_TYPES)
    source_ids = {
        node.get(XML + 'id') for node in element.iter()
        if isinstance(node.tag, str) and node.get(XML + 'id')
    }

    def visit(node: ET.Element, parent_tag: str | None = None) -> dict[str, Any]:
        if not isinstance(node.tag, str) or not node.tag.startswith(NS):
            raise PipelineError('unsupported native content namespace')
        tag = node.tag[len(NS):]
        if tag in {'sic', 'corr'} and parent_tag != 'choice':
            pta_variant = (source_profile == PTA_ANONYMOUS_VITA_PROFILE
                           and tag == 'sic' and parent_tag == 'seg'
                           and any(child.tag == NS+'app' and child.get('type') == 'variants'
                                   for child in node))
            hesychius_empty = (source_profile == PTA_HESYCHIUS_PROFILE
                               and tag == 'sic' and parent_tag == 'p'
                               and not node.attrib and node.text is None and not len(node))
            if not (pta_variant or hesychius_empty):
                raise PipelineError('native correction alternatives require a choice parent')
        if source_profile == STRONG_PROFILE:
            try:strong_source.check_content_node(node, parent_tag)
            except ValueError as exc:raise PipelineError(str(exc)) from exc
        if source_profile == cass_source.PROFILE:
            try:cass_source.check_content_node_et(node, parent_tag)
            except ValueError as exc:raise PipelineError(str(exc)) from exc
        if tag not in policy['elements']:
            raise PipelineError(f'unsupported native content element: {tag}')
        rule = policy['elements'][tag]
        if tag == 'ref' and node.get(XML+'base') is not None:
            target = node.get('target') or ''
            mtp_link = (source_profile == MTP_PROFILE and source_base is None
                        and node.get('type') == 'source-link'
                        and node.get(XML+'base') in _MTP_SOURCE_BASES
                        and target.startswith('/') and not any(char.isspace() for char in target))
            expositor_link = (node.get(XML+'base') == source_base and source_base
                              and re.fullmatch(r'https://www\.ccel\.org/ccel/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+\.html', source_base)
                              and re.fullmatch(r'\?scrBook=[A-Za-z0-9]+&scrCh=[0-9]+&scrV=[0-9]+#[A-Za-z0-9_.-]+', target))
            if not (mtp_link or expositor_link):
                raise PipelineError('native source reference base or literal target differs')
        if tag == 'sp':
            visible_children = [child for child in node if child.tag != NS+'pb']
            if (len(visible_children) < 2 or visible_children[0].tag != NS+'speaker'
                    or any(child.tag == NS+'speaker' for child in visible_children[1:])
                    or (node.text or '').strip() or any((child.tail or '').strip() for child in node)):
                raise PipelineError('native speech requires one leading speaker and spoken content')
        if tag == 'speaker' and (parent_tag != 'sp' or not ''.join(node.itertext()).strip()):
            raise PipelineError('native speaker requires a speech and nonempty label')
        if tag == 'app' and ((node.text or '').strip()
                             or any((child.tail or '').strip() for child in node)):
            raise PipelineError('critical-apparatus text must be carried by lemma or reading')
        if tag == 'choice':
            if source_profile == WHITEFIELD_PROFILE:
                whitefield_source.choice_et(node)
            correction = [child.tag for child in node] == [NS+'sic', NS+'corr']
            if correction:
                if (source_profile not in (None, BENNETT_CHRONICLES_PROFILE) or node.attrib or (node.text or '').strip()
                        or any((child.tail or '').strip() for child in node)
                        or any(child.attrib for child in node) or len(node[0])
                        or not (node[0].text or '').strip()
                        or not ''.join(node[1].itertext()).strip()
                        or any(not (child.tag == NS+'hi' and dict(child.attrib) == {'rend': 'italic'}
                                    or child.tag == NS+'ref' and set(child.attrib) == {'target'}
                                    and re.fullmatch(r'#[A-Za-z_][A-Za-z0-9_.-]*', child.get('target', '')))
                               or len(child) or not (child.text or '').strip() for child in node[1])):
                    raise PipelineError('native correction choice differs')
            elif (source_profile not in (None, BENNETT_CHRONICLES_PROFILE, ELMSLIE_CHOICE_PROFILE, WHITEFIELD_PROFILE) or (node.attrib and source_profile != WHITEFIELD_PROFILE)
                    or [child.tag for child in node] != [NS+'abbr', NS+'expan']
                    or node.text or any(child.tail for child in node)
                    or not ''.join(node[0].itertext()).strip()
                    or not (node[1].text or '').strip() or len(node[1]) or node[1].attrib):
                raise PipelineError('Elmslie abbreviation choice differs')
        if tag == 'abbr' and node.get('n') not in (None, 'source-html-class:spell'):
            raise PipelineError('unsupported abbreviation source class')
        if tag == 'title' and ('type' in node.attrib or 'n' in node.attrib):
            number = node.get('n') or ''
            if (source_profile not in (GUYON_PROFILE, FOX_PROFILE)
                    or set(node.attrib) != {XML+'id', 'type', 'n'}
                    or node.get('type') != 'source-citation'
                    or re.fullmatch(_GUYON_DOTTED, number) is None
                    or node.get(XML+'id') != 'source-node-'+number
                    or len(node) or not (node.text or '').strip()):
                raise PipelineError('Guyon source citation title differs')
        if tag == 'ab' and source_profile == GUYON_PROFILE and node.get('type') in _GUYON_BLOCKS:
            number = node.get('n') or ''
            kind = node.get('type')
            expected = ('source-node-'+number if kind == 'source-hr' else
                        kind+'-'+number.removesuffix('.tail').removesuffix('.text'))
            shape = (re.fullmatch(_GUYON_LOCATOR, number[:-5]) is not None
                     if kind in {'source-tail-text', 'source-div-leading-text'} else
                     number == '3' if kind == 'source-hr' else
                     re.fullmatch(_GUYON_DOTTED, number) is not None)
            attrs = ({'type', 'n', XML+'id', XML+'space'} if kind in
                     {'source-tail-text', 'source-div-leading-text'} else
                     {'type', 'n', XML+'id', 'rend'} if kind == 'source-hr' else
                     {'type', 'n', XML+'id'})
            if (source_profile != GUYON_PROFILE or not shape or set(node.attrib) != attrs
                    or node.get(XML+'id') != expected
                    or kind in {'source-tail-text', 'source-div-leading-text'}
                    and (node.get(XML+'space') != 'preserve' or len(node))
                    or kind == 'source-inline-carrier' and
                    (len(node) != 1 or node[0].tag not in {NS+'ref', NS+'seg', NS+'lb'})
                    or kind == 'source-hr' and
                    (node.get('rend') != 'source-class:pg' or len(node)
                     or (node.text or '').strip())):
                raise PipelineError('Guyon source block carrier differs')
        if tag == 'space':
            line = node.get('n') or ''
            prefix = 'carey-enquiry' if source_profile == CAREY_PROFILE else 'wilberforce-practical-view'
            last_line = 2073 if source_profile == CAREY_PROFILE else 10820
            if (set(node.attrib) != {XML+'id', 'type', 'unit', 'quantity', 'n', 'subtype'}
                    or not line.isdecimal() or not 1 <= int(line) <= last_line
                    or node.get(XML+'id') != f'{prefix}-blank-{int(line):05d}'
                    or node.get('type') != 'source-blank-line'
                    or node.get('unit') != 'line' or node.get('quantity') != '1'
                    or node.get('subtype') != 'crlf' or len(node) or (node.text or '').strip()):
                raise PipelineError('source blank-line carrier differs')
        if tag == 'head' and node.get('type') == 'source-located-heading':
            line = node.get('n') or ''
            prefix = 'carey-enquiry' if source_profile == CAREY_PROFILE else 'wilberforce-practical-view'
            last_line = 1751 if source_profile == CAREY_PROFILE else 10820
            levels = {'1', '2', '3'} if source_profile == CAREY_PROFILE else {'1', '2'}
            if (not line.isdecimal() or not 1 <= int(line) <= last_line
                    or node.get(XML+'id') != f'{prefix}-heading-{int(line):05d}'
                    or node.get('subtype') not in levels):
                raise PipelineError('source heading carrier differs')
        if tag in {'table', 'row', 'cell'}:
            if source_profile == GUYON_PROFILE and tag == 'table':
                number = node.get('n') or ''
                start, end = (node[0], node[-1]) if len(node) >= 2 else (None, None)
                if (number not in {'6.11.1', '6.15.1'}
                        or node.get(XML+'id') != 'source-node-'+number
                        or start is None or start.tag != NS+'milestone'
                        or start.get('unit') != 'source-tbody-start'
                        or start.get('n') != number+'.1'
                        or end.tag != NS+'milestone'
                        or end.get('unit') != 'source-tbody-end'
                        or end.get('n') != number+'.1.end'
                        or any(child.tag != NS+'row' for child in node[1:-1])):
                    raise PipelineError('Guyon source table structure differs')
            if source_profile == GUYON_PROFILE and tag == 'cell':
                number = node.get('n') or ''
                if (parent_tag != 'row' or re.fullmatch(_GUYON_DOTTED, number) is None
                        or node.get(XML+'id') != 'source-node-'+number
                        or node.get('cols') not in (None, '3')
                        or node.get('role') is not None):
                    raise PipelineError('Guyon source cell DOM locator differs')
            if source_profile == AMERICAN_MISSIONARY_PROFILE:
                if tag == 'row':
                    numbers = [int(child.get('n')) for child in node
                               if child.tag == NS+'cell' and child.get('n') is not None
                               and re.fullmatch(r'[1-9][0-9]*', child.get('n') or '')]
                    if numbers != sorted(set(numbers)):
                        raise PipelineError('American Missionary source cell numbers differ in row')
                if tag == 'cell':
                    number = node.get('n')
                    identifier = node.get(XML+'id')
                    if (parent_tag != 'row' or node.get('role') != 'data'
                            or (number is None) != (identifier is None)
                            or number is not None and (re.fullmatch(r'[1-9][0-9]*', number) is None
                                or not identifier.endswith(f'B{int(number):05d}'))):
                        raise PipelineError('American Missionary source cell identity differs')
            if (tag == 'cell' and source_profile != BCP_HTML_PROFILE
                    and (node.get('ana') or '').startswith(
                        ('urn:ocd:bcp1549:html:', 'urn:ocd:bcp1559:html:'))):
                raise PipelineError('BCP retained HTML annotation requires its source profile')
            if (tag == 'cell' and source_profile != HODGE_PROFILE
                    and (node.get('ana') or '').startswith('urn:ocd:hodge-theology1:ThML:')):
                raise PipelineError('Hodge source annotation requires its source profile')
            if tag == 'cell' and source_profile == HODGE_PROFILE:
                if parent_tag != 'row':
                    raise PipelineError('Hodge source cell requires a row parent')
                _hodge_source_row_span(node)
            if (tag == 'cell' and source_profile == BCP_HTML_PROFILE
                    and (node.get('ana') or '').startswith(('urn:ocd:bcp1549:html:', 'urn:ocd:bcp1559:html:'))):
                _bcp_source_row_span(node)
            if tag == 'cell' and node.get('rows') is not None:
                if parent_tag != 'row':
                    raise PipelineError('native cell row span requires a row parent')
                if source_profile == HODGE_PROFILE:
                    _hodge_source_row_span(node)
                elif source_profile == BCP_HTML_PROFILE:
                    _bcp_source_row_span(node)
                elif source_profile not in (None, BENNETT_CHRONICLES_PROFILE) or not re.fullmatch(r'[1-9][0-9]*', node.get('rows') or ''):
                    raise PipelineError('unsupported native content attribute: cell@rows')
            carey_attributes = {'table': {'rows', 'cols'}, 'row': {'role'}, 'cell': {'n'}}[tag]
            if source_profile != CAREY_PROFILE and not (
                    source_profile in (AMERICAN_MISSIONARY_PROFILE, MOODY_PROFILE, THOME_PROFILE, FOX_PROFILE, WOOLMAN_PROFILE) and tag == 'cell'
                    and carey_attributes.intersection(node.attrib) <= {'n'}
            ) and not (
                    source_profile == GUYON_PROFILE and tag == 'cell'
                    and carey_attributes.intersection(node.attrib) <= {'n'}
            ) and not (
                    source_profile == cass_source.PROFILE and tag == 'cell'
                    and carey_attributes.intersection(node.attrib) <= {'n','cols'}
            ) and carey_attributes.intersection(node.attrib):
                unsupported = sorted(carey_attributes.intersection(node.attrib))[0]
                raise PipelineError(f'unsupported native content attribute: {tag}@{unsupported}')
            if source_profile == CAREY_PROFILE:
                if tag == 'table' and (not (node.get('rows') or '').isdecimal()
                                       or int(node.get('rows')) != len(node)
                                       or node.get('cols') not in {'5', '6'}):
                    raise PipelineError('Carey table dimensions differ')
                if tag == 'table' and any(child.tag != NS+'row' for child in node):
                    raise PipelineError('Carey table row structure differs')
                if tag == 'table' and any(
                    not (cell.get('n') or '').isdecimal()
                    or not 1 <= int(cell.get('n')) <= int(node.get('cols'))
                    for row in node for cell in row if cell.tag == NS+'cell'
                ):
                    raise PipelineError('Carey table column position exceeds dimensions')
                if tag == 'row' and node.get('role') not in {
                    'data', 'continuation', 'source-blank-line', 'footnote',
                    'table-superheading', 'column-headings', 'unit-headings',
                    'table-note', 'group-heading', 'data-group-heading',
                    'column-subheadings',
                }:
                    raise PipelineError('Carey table row role differs')
                if tag == 'row' and (not len(node) or any(child.tag != NS+'cell' for child in node)):
                    raise PipelineError('Carey table cells differ')
                if tag == 'row':
                    positions = [child.get('n') or '' for child in node]
                    if (any(not value.isdecimal() for value in positions)
                            or [int(value) for value in positions] != sorted({int(value) for value in positions})):
                        raise PipelineError('Carey table cell positions differ')
                if tag == 'cell' and not (node.get('n') or '').isdecimal():
                    raise PipelineError('Carey table cell position differs')
        samuel_column = (tag == 'milestone' and source_profile == SAMUEL_PROFILE
                         and node.get('unit') == 'source-column')
        if samuel_column and (set(node.attrib) != {'unit', 'style'}
                              or re.fullmatch(r'width: (?:[1-9]|[1-9][0-9]|100)%;', node.get('style') or '') is None):
            raise PipelineError('Samuel source-column width differs')
        mark_marker = (tag == 'milestone' and source_profile == MARK_PROFILE
                       and node.get('unit') == 'source-index')
        guyon_tbody = tag == 'milestone' and source_profile == GUYON_PROFILE and node.get('unit') in _GUYON_TBODY
        moody_tbody = tag == 'milestone' and source_profile == MOODY_PROFILE and node.get('unit') in _MOODY_TBODY
        fox_tbody = tag == 'milestone' and source_profile in (FOX_PROFILE, WOOLMAN_PROFILE) and node.get('unit') in _FOX_TBODY
        if mark_marker and dict(node.attrib) not in (
                {XML+'id': 'xix.i-p0.2', 'rend': 'source-type:scripRef', 'unit': 'source-index'},
                {XML+'id': 'xix.ii-p0.2', 'rend': 'source-type:scripCom', 'unit': 'source-index'}):
            raise PipelineError('Chadwick Mark source index marker differs')
        if tag in ('milestone', 'index', 'divGen'):
            if len(node) or (node.text or '').strip():
                raise PipelineError('native marker must be empty')
            if tag == 'milestone' and source_profile == BENNETT_CHRONICLES_PROFILE and node.get('unit') == 'source-colgroup' and (
                    parent_tag != 'table' or dict(node.attrib) != {
                        XML+'id': 'bennett-expositor10-iv.ii-p16.2', 'unit': 'source-colgroup', 'n': '2',
                        'ana': 'urn:ccel:source-attribute:id:iv.ii-p16.2 urn:ccel:source-attribute:span:2'}):
                raise PipelineError('Bennett source column group differs')
            if tag == 'milestone' and node.get('unit') == 'column_group' and parent_tag != 'table':
                raise PipelineError('native column-group marker requires a table parent')
            peter_marker = tag == 'milestone' and source_profile == PETER_JONES_PROFILE and node.get('unit') in PETER_JONES_MARKERS
            if moody_tbody:
                expected_n = '21.1' if node.get('unit') == 'source-tbody-start' else '21.1.end'
                if (parent_tag != 'table' or set(node.attrib) != {'unit', 'n', XML+'id'}
                        or node.get('n') != expected_n or node.get(XML+'id') != 'source-node-'+expected_n):
                    raise PipelineError('Moody source table boundary differs')
            if fox_tbody:
                number = node.get('n') or ''
                expected_end = node.get('unit') == 'source-tbody-end'
                if (parent_tag != 'table' or set(node.attrib) != {'unit', 'n', XML+'id'}
                        or re.fullmatch(_GUYON_DOTTED + (r'\.end' if expected_end else ''), number) is None
                        or node.get(XML+'id') != 'source-node-'+number):
                    raise PipelineError('Fox source table boundary differs')
            if guyon_tbody:
                number = node.get('n') or ''
                if (source_profile != GUYON_PROFILE or parent_tag != 'table'
                        or set(node.attrib) != {'unit', 'n', XML+'id'}
                        or re.fullmatch(_GUYON_DOTTED + (r'\.end' if node.get('unit') == 'source-tbody-end' else ''), number) is None
                        or node.get(XML+'id') != 'source-node-'+number):
                    raise PipelineError('Guyon source table boundary differs')
            if peter_marker and (set(node.attrib) != ({'unit'} if node.get('unit') == 'source-rule' else {'unit', 'n'})
                                 or node.get('unit') != 'source-rule' and not (node.get('n') or '').strip()):
                raise PipelineError('Peter Jones source marker attributes differ')
            if tag == 'milestone' and node.get('unit') not in policy['milestone_kinds'] and node.get('unit') != 'source-horizontal-rule' and not peter_marker and not mark_marker and not guyon_tbody and not fox_tbody and not (source_profile == WHITEFIELD_PROFILE and node.get('unit') == 'source-hr') and not samuel_column and not moody_tbody and not (source_profile == HOLY_IMAGES_PROFILE and node.get('unit') == 'source-html-comment' and set(node.attrib) == {'unit', 'n'} and re.fullmatch(r'[0-9a-f]{64}', node.get('n') or '')):
                raise PipelineError('unsupported native milestone unit')
            if tag == 'index' and node.get('indexName') is not None and node.get('indexName') not in policy['index_names']:
                raise PipelineError('unsupported native index name')
            if tag == 'divGen' and node.get('type') not in policy['generator_types']:
                raise PipelineError('unsupported native generator placeholder')
        source_heading_level = None
        # Existing accepted TEI uses both the hyphenated and underscored
        # source-heading spellings; both carry the same explicit level.
        if tag == 'ab' and re.fullmatch(r'source[-_]h[1-6]', node.get('type') or ''):
            if node.get('subtype') is not None:
                raise PipelineError('source heading level conflicts with subtype')
            source_heading_level = node.get('type')[-2:]
            heading_style = node.get('rend')
            if heading_style is not None and not heading_style.strip():
                raise PipelineError('unsupported native content attribute: ab@rend')
        if (tag == 'ab' and node.get('type') is not None
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
                and source_heading_level is None):
            raise PipelineError('unsupported native source block type')
        if tag == 'w' and source_profile == STRONG_PROFILE:
            own_id = node.get(XML + 'id')
            references = (node.get('corresp') or '').split()
            if (any(child.tag != NS + 'hi' for child in node)
                    or not ''.join(node.itertext()).strip() or not (node.get('lemma') or '').strip()
                    or not own_id or len(references) < 2
                    or f'#{own_id}' not in references
                    or any(not ref.startswith('#') or ref[1:] not in source_ids for ref in references)):
                raise PipelineError('unsupported native word-segment linkage')
        peter_blank_page = (source_profile == PETER_JONES_PROFILE and tag == 'gap'
                            and dict(node.attrib) == {'reason': 'blank', 'unit': 'page', 'extent': '1'}
                            and len(node) == 0 and not (node.text or '').strip())
        attributes = {}
        whitefield_graphic = whitefield_source.graphic_et(node) if source_profile == WHITEFIELD_PROFILE and tag == 'graphic' else None
        if whitefield_graphic and whitefield_graphic[1]:
            attributes['css_style'] = whitefield_graphic[1]
        if tag == 'graphic' and (len(node) or (node.text or '').strip() or not (node.get('url') or '').strip()):
            raise PipelineError('native graphic requires an empty reference with an explicit URL')
        coppens_graphic = (source_profile == COPPENS_PROFILE and tag == 'graphic'
                           and coppens_source.graphic_allowed(node))
        if tag == 'graphic' and (node.get(XML+'base') is not None or node.get('rend') is not None):
            url = node.get('url')
            samuel_image = False
            if source_profile == SAMUEL_PROFILE:
                identifier = node.get(XML+'id') or ''
                expected = _SAMUEL_GRAPHICS.get(identifier)
                samuel_image = (expected is not None and set(node.attrib) ==
                                {'url', XML+'id', 'corresp', 'n', 'rend'}
                                and node.get('corresp') == f'urn:ocd:retained-archive:{_SAMUEL_ARCHIVE}:member:{expected[0]}'
                                and node.get('n') == '' and node.get('rend') == 'ig001'
                                and url.startswith('data:image/jpeg;base64,')
                                and hashlib.sha256(url.encode()).hexdigest() == expected[1])
                if not samuel_image:
                    raise PipelineError('Samuel retained JPEG source or private archive binding differs')
            layout = (url == 'images/indent.gif' and node.get('rend') == 'source-layout-spacer'
                      and node.get('n') == '    ')
            initial = (url == 'images/s.gif'
                       and node.get('rend') == 'source-initial-letter source-align-LEFT'
                       and node.get('n') is None)
            moody_alt = (source_profile == MOODY_PROFILE and node.get(XML+'base') is None
                         and node.get('rend') in {'source-alt-empty', 'source-alt:D. L. Moody.'})
            cass_graphic = (source_profile == cass_source.PROFILE and
                            cass_source.GRAPHICS.get(node.get(XML+'id')) == (url, node.get('rend')) and
                            set(node.attrib) == {'n',XML+'id','url','rend'})
            fox_expected = FOX_GRAPHICS.get(node.get(XML+'id') or '') if source_profile == FOX_PROFILE else None
            fox_image = (fox_expected is not None and node.get(XML+'base') is None
                         and set(node.attrib) == {'n', XML+'id', 'url', 'rend'}
                         and (node.get('url'), node.get('rend'), node.get('n')) == fox_expected)
            if source_profile == FOX_PROFILE and not fox_image:
                raise PipelineError('Fox retained image reference differs')
            if (not samuel_image and not moody_alt and not coppens_graphic and not cass_graphic and not fox_image and (source_profile != MTP_PROFILE or node.get(XML+'base') != 'https://archive.spurgeon.org/'
                    or not (layout or initial) or not node.get(XML+'id'))):
                raise PipelineError('MTP literal image reference differs')
        source_attributes = {}
        attribute_rules = rule.get('attributes', {})
        for key, value in node.attrib.items():
            name = 'xml:' + key[len(XML):] if key.startswith(XML) else key
            if source_profile == STRONG_PROFILE and tag == 'seg' and name == 'xml:space':
                if value != 'preserve':raise PipelineError('Strong II source-line whitespace differs')
                attributes['whitespace'] = value
                continue
            if tag == 'graphic' and name == 'url' and source_profile == SAMUEL_PROFILE:
                # Image bytes and the archive digest stay in private TEI/inventory.
                attributes['source_target'] = 'retained-embedded-image:' + _SAMUEL_GRAPHICS[node.get(XML+'id')][0]
                continue
            if (source_profile == MOODY_PROFILE and tag == 'graphic' and name in {'width', 'height'}
                    and node.get('url') in {'images/i_127.jpg', 'images/i_127a.jpg'}
                    and value == ('25px' if name == 'width' else '15px')):
                continue  # Retained exactly in the pinned TEI/source-node inventory.
            if source_profile == WHITEFIELD_PROFILE and name == 'ana':
                whitefield_source.annotation(value)
                continue  # Exact literal remains private source inventory, not public administration.
            if tag == 'anchor' and name == 'ana' and (node.get(XML+'id') or '').startswith('bennett-expositorjer2-'):
                source_attributes.update(_bennett_jer2_anchor_attributes(node, value))
                continue
            if source_profile == WHITEFIELD_PROFILE and tag == 'choice' and name == 'xml:id':
                attributes['source_anchor'] = whitefield_source.anchor(value)
                continue
            if source_profile == WHITEFIELD_PROFILE and tag == 'ref' and name == 'target' and value.startswith('#') and value[1:] in whitefield_source.ANCHORS:
                attributes['source_target'] = '#'+whitefield_source.anchor(value[1:])
                continue
            if whitefield_graphic and name in {'url', 'width', 'height', 'style'}:
                if name == 'url':attributes['source_target'] = whitefield_graphic[0]
                continue
            if tag == 'ab' and name == 'rend' and source_heading_level is not None and value in {'style:margin-top:12pt', 'style:margin-top:48pt'}:
                attributes['style'] = value
                continue
            if tag == 'ab' and name == 'source' and source_profile == MARK_PROFILE:
                if (node.get('type') != 'scripture-commentary' or
                        not re.fullmatch(r'urn:ccel-thml-parsed:%7CMark(?:%7C[0-9]+){4}(?:%3B%7CMark(?:%7C[0-9]+){4})*', value)):
                    raise PipelineError('Chadwick Mark parsed-source carrier differs')
                continue  # The exact literal stays in the private source inventory.
            if name == 'unit' and (mark_marker or peter_blank_page or guyon_tbody or samuel_column or moody_tbody or tag == 'milestone' and source_profile == PETER_JONES_PROFILE and node.get('unit') in PETER_JONES_MARKERS):
                attributes['unit'] = value
                continue
            if name not in attribute_rules:
                if name == 'xml:id':
                    continue
                if name == 'xml:lang':
                    attributes['language'] = value
                    continue
                if name not in rule.get('source_attributes', ()):
                    raise PipelineError(f'unsupported native content attribute: {tag}@{name}')
                source_attributes[name] = value
                continue
            destination = attribute_rules[name]
            if destination is not None:
                attributes[destination] = value
        if source_attributes:
            attributes['source_attributes'] = source_attributes
        if rule.get('source_element'):
            attributes['source_element'] = tag
        if source_heading_level is not None:
            attributes['type'] = 'source-heading'
            attributes['subtype'] = source_heading_level[1:]
        if mark_marker or samuel_column or tag == 'milestone' and node.get('unit') in policy['milestone_kinds'] and policy['milestone_kinds'][node.get('unit')] == 'source-marker':
            attributes['unit'] = node.get('unit')
        if tag == 'g':
            reference = node.get('ref')
            if (reference not in policy['glyphs'] and reference not in policy['source_declared_glyphs']
                    and not (source_profile == HYMNARY_PROFILE and reference in _HYMNARY_GLYPHS)) or len(node):
                raise PipelineError('unsupported native glyph reference or content')
            if source_profile == HYMNARY_PROFILE and reference in _HYMNARY_GLYPHS and node.text != _HYMNARY_GLYPHS[reference]:
                raise PipelineError('Hymnary source control glyph literal differs')
            if reference in policy['source_declared_glyphs'] and node.text != policy['source_declared_glyphs'][reference]:
                raise PipelineError('source-declared glyph literal differs')
        if tag in ('pb', 'lb', 'cb') and (len(node) or (node.text or '').strip()):
            raise PipelineError('native milestone contains text')
        marked_gap = tag == 'gap' and not len(node) and not (node.text or '').strip() and node.get('reason') == 'illegible' and bool((node.get('extent') or '').strip()) and bool((node.get('rend') or '').strip())
        source_byte_gap = (
            tag == 'gap' and not len(node) and not (node.text or '').strip()
            and node.get('reason') == 'unrepresentable'
            and re.fullmatch(r'[1-9][0-9]* bytes', node.get('extent') or '') is not None
            and node.get('ana') in {'#source-invalid-utf8', '#source-xml-1.0-forbidden-character'}
            and re.fullmatch(r'[0-9a-f]{64}', node.get('n') or '') is not None
            and bool(node.get(XML+'id'))
        )
        source_text_gap = (
            tag == 'gap' and not len(node) and not (node.text or '').strip()
            and node.get('reason') in {'damage', 'missing', 'illegible'}
            and node.get('unit') in {'word', 'character'}
            and re.fullmatch(r'[1-9][0-9]*', node.get('quantity') or '') is not None
        )
        if tag == 'gap' and not marked_gap and not source_byte_gap and not source_text_gap and not peter_blank_page and (len(node) != 1 or node[0].tag != NS+'desc' or not ''.join(node[0].itertext()).strip()):
            raise PipelineError('native gap requires one explicit nonempty description')
        supplied = (tag == 'expan' and source_profile in (None, ELMSLIE_CHOICE_PROFILE, WHITEFIELD_PROFILE)
                    and parent_tag == 'choice')
        if tag == 'expan' and not supplied and ([child.tag for child in node] != [NS+'am', NS+'ex'] or (node.text or '').strip() or any((child.tail or '').strip() for child in node)):
            raise PipelineError('native expansion requires ordered abbreviation and expansion')
        parts = []
        if node.text:
            parts.append({'kind': 'text', 'text': node.text})
        for child in node:
            projected = visit(child, tag)
            if not (source_profile == HOLY_IMAGES_PROFILE and child.tag == NS+'milestone' and child.get('unit') == 'source-html-comment'):
                parts.append(projected)
            if child.tail:
                parts.append({'kind': 'text', 'text': child.tail})
        kind = ('source-marker' if (mark_marker or samuel_column or guyon_tbody or moody_tbody or fox_tbody or source_profile == HOLY_IMAGES_PROFILE and node.get('unit') == 'source-html-comment'
                                    or source_profile == PETER_JONES_PROFILE and node.get('unit') in PETER_JONES_MARKERS - {'source-rule'})
                else 'horizontal-rule' if node.get('unit') == 'source-horizontal-rule' or source_profile == WHITEFIELD_PROFILE and node.get('unit') == 'source-hr'
                else policy['milestone_kinds'][node.get('unit')]) if tag == 'milestone' else 'supplied-expansion' if supplied else rule['kind']
        if tag == 'choice' and correction:
            kind = 'correction-choice'
        return {'kind': kind, 'attributes': attributes, 'content': parts}

    return visit(element)


def readable_content(content: dict[str, Any], *, _policy: dict | None = None) -> str:
    """Render readable text while preserving hierarchy in the parallel content.

    Notes and page milestones remain structural evidence; expanded spelling uses
    the source's explicit expansion. Glyphs preserve literal source text where present and otherwise use the
    pinned TCP display mapping, never an inferred replacement. Formatting whitespace is normalized only here.
    """
    policy = content_policy() if _policy is None else _policy

    def render(node: dict[str, Any]) -> str:
        kind = node['kind']
        if kind == 'text':
            return re.sub(r'\s+', ' ', node['text'])
        if kind in policy['text_omissions']:
            return ''
        if kind == 'line-break':
            return '' if node['attributes'].get('break_mode') == 'no' else ' '
        if kind == 'gap' and not node['content']:
            if node['attributes'] == {'reason': 'blank', 'unit': 'page', 'extent': '1'}:
                return ''
            if node['attributes'].get('reason') == 'unrepresentable':
                return '[unrepresentable source bytes]'
            if (node['attributes'].get('reason') in {'damage', 'missing', 'illegible'}
                    and node['attributes'].get('unit') in {'word', 'character'}
                    and re.fullmatch(r'[1-9][0-9]*', node['attributes'].get('extent', ''))):
                quantity = node['attributes']['extent']
                unit = node['attributes']['unit']
                suffix = '' if quantity == '1' else 's'
                return f"[{node['attributes']['reason']}: {quantity} {unit}{suffix}]"
            return node['attributes']['style']
        if kind == 'glyph':
            reference = node['attributes'].get('reference')
            literal = ''.join(child['text'] for child in node['content'] if child['kind'] == 'text').strip()
            if reference in _HYMNARY_GLYPHS:
                if literal != _HYMNARY_GLYPHS[reference]:
                    raise PipelineError('Hymnary source control glyph literal differs')
                return literal
            if reference not in policy['glyphs'] and reference not in policy['source_declared_glyphs']:
                raise PipelineError('unsupported native glyph reference')
            return literal or policy['glyphs'].get(reference) or policy['source_declared_glyphs'][reference]
        if kind == 'abbreviation-choice':
            children = node['content']
            if ([child['kind'] for child in children] != ['abbreviated-text', 'supplied-expansion']):
                raise PipelineError('native abbreviation choice content differs')
            return render(children[0])
        if kind == 'correction-choice':
            children = [child for child in node['content'] if child['kind'] != 'text']
            if ([child['kind'] for child in children] != ['original-text', 'corrected-text']
                    or any(child['text'].strip() for child in node['content'] if child['kind'] == 'text')):
                raise PipelineError('native correction choice content differs')
            return render(children[1])
        if kind == 'critical-apparatus':
            return ''.join(render(child) for child in node['content']
                           if child.get('attributes', {}).get('source_element') == 'lem')
        if kind == 'expansion':
            expanded = [child for child in node['content'] if child['kind'] == 'expanded-text']
            if len(expanded) != 1:
                raise PipelineError('native expansion has no unique expanded text')
            return render(expanded[0])
        value = ''.join(render(child) for child in node['content'])
        if kind == 'verse-line':
            return value.strip() + '\n'
        if kind in policy['block_boundaries']:
            return '\n\n' + value.strip() + '\n\n'
        return value

    result = re.sub(r' *\n *', '\n', render(content))
    return re.sub(r'\n{3,}', '\n\n', result).strip()
