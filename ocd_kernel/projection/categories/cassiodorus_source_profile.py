"""Exact source-native projection profile for Cassiodorus PG18590."""
from __future__ import annotations
from collections import Counter
import hashlib
import re
from lxml import etree

PROFILE = 'ocd-prose-cassiodorus-pg18590-source-native-v1'
IDENTITY = {'work_id':'cassiodorus-letters-hodgkin-condensed',
            'textual_form_id':'cassiodorus-letters-hodgkin-condensed-english',
            'edition_id':'cassiodorus-letters-hodgkin-condensed-pg18590-1886'}
ACQUISITION_ID = 'pg18590-hodgkin-html-retained'
MASTER_SHA256 = '93d76a6e098ad65a52b02d20ee81766ad0e34e95e879e61cd30350fc0c09c3d2'
ACCOUNTING_PATH = 'library/works/cassiodorus-letters-hodgkin-condensed/integration/cassiodorus-pg18590-current-v13/acceptance-v1/source-accounting-v6.json'
ACCOUNTING_SHA256 = 'd18c040def42f697e5ffeaace80b689212919ddec8a245b96e832e574f336311'
SOURCE_MANIFEST_SHA256 = 'c6452d88e38f1a1faf3dd32116be8100ac384a3f5577da6247dc206025825545'
ARCHIVE_SHA256 = '8b663097982c52d82370c96ce44d9ffa804963a4fde9802f2d4dd2ef2ac63325'
HTML_SHA256 = '62421bc56b576afeecfca98f51032863753ba8fd545bebccced556963e5ac1bf'
BODY_TEXT_SHA256 = '5373cb69531da997434c47cda10c6859fa6904be36340ce6eb53df42473af0da'
BLOCK_COUNTS = {'source-tail-text':4190, 'source-div-leading-text':659,
                'source-inline-carrier':49, 'source-hr':35, 'source-pre':2}
BLOCKS = set(BLOCK_COUNTS)
INLINE_CHILD_COUNTS = {'seg':35, 'ref':9, 'lb':4, 'hi':1}
GRAPHICS = {
    'img_images_image01.png': ('images/image01.png','source-alt:map'),
    'img_images_image02.png': ('images/image02.png','source-alt:Plan of Ancient Circus'),
    'img_images_image03.png': ('images/image03.png','source-alt:Circus Maximus'),
}
START_UNIT = 'source-tbody-start'
END_UNIT = 'source-tbody-end'
TABLE_COUNT = 26
TAIL_REND = 'source-tail-utf8-base64:DQo='
NS = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'
LOCATOR = re.compile(r'[1-9][0-9]*(?:\.[1-9][0-9]*)*\Z')
DOTTED = re.compile(r'[1-9][0-9]*(?:\.[1-9][0-9]*)+\Z')


def extend_policy(policy):
    """Return a call-local policy extension; the shared JSON remains unchanged."""
    policy = dict(policy)
    policy['source_block_types'] = list(policy['source_block_types']) + sorted(BLOCKS)
    policy['milestone_kinds'] = dict(policy['milestone_kinds']) | {
        START_UNIT:'source-marker', END_UNIT:'source-marker'}
    return policy


def _local(tag):
    if isinstance(tag, str) and tag.startswith(NS):
        return tag[len(NS):]
    return None


def check_content_node_et(node, parent_tag=None):
    """Validate one source-native block or table-tail marker in the producer."""
    tag = _local(node.tag)
    if tag == 'ab' and node.get('type') in BLOCKS:
        kind, number = node.get('type'), node.get('n') or ''
        if kind in {'source-tail-text','source-div-leading-text'}:
            suffix = '.tail' if kind == 'source-tail-text' else '.text'
            loc = number[:-len(suffix)] if number.endswith(suffix) else ''
            expected_id = kind+'-'+loc
            valid = (bool(loc) and LOCATOR.fullmatch(loc) is not None and
                     node.get(XML+'id') == expected_id and node.get(XML+'space') == 'preserve' and
                     set(node.attrib) == {'type','n',XML+'id',XML+'space'} and
                     len(node) == 0 and node.text is not None)
        elif kind == 'source-inline-carrier':
            valid = (DOTTED.fullmatch(number) is not None and
                     set(node.attrib) == {'type','n',XML+'id'} and
                     node.get(XML+'id') == kind+'-'+number and node.text is None and len(node) == 1 and
                     _local(node[0].tag) in INLINE_CHILD_COUNTS and node[0].tail is None)
        elif kind == 'source-hr':
            valid = (number.isdecimal() and node.get(XML+'id') == 'source-node-'+number and
                     set(node.attrib) == {'type','n',XML+'id','rend'} and
                     re.fullmatch(r'source-style:width: (?:15|35|45|65)%;',node.get('rend') or '') is not None and
                     len(node) == 0 and node.text is None)
        else:
            valid = (number in {'2','4107'} and set(node.attrib) == {'type','n',XML+'id'} and
                     node.get(XML+'id') == 'source-node-'+number and len(node) == 0 and node.text is None)
        if not valid:
            raise ValueError('Cassiodorus source-native block carrier differs')
    if tag in {'table','row','cell'}:
        number = node.get('n') or ''
        expected = {'table': {'n',XML+'id','rend'},
                    'row': {'n',XML+'id'},
                    'cell': ({'n',XML+'id'}, {'n',XML+'id','rend'}, {'n',XML+'id','cols','rend'})}[tag]
        shape = set(node.attrib) in expected if tag == 'cell' else set(node.attrib) == expected
        valid = (LOCATOR.fullmatch(number) is not None and shape and
                 node.get(XML+'id') == 'source-node-'+number and
                 (tag != 'cell' or node.get('cols') is None or node.get('cols') in {'2','3','4','5'}))
        if not valid:
            raise ValueError('Cassiodorus source table locator differs')
    if tag == 'milestone' and node.get('unit') in {START_UNIT,END_UNIT}:
        unit, number = node.get('unit'), node.get('n') or ''
        is_start = unit == START_UNIT
        suffix = '.1' if is_start else '.1.end'
        table_number = number[:-len(suffix)] if number.endswith(suffix) else ''
        expected_n = table_number + suffix
        expected_attrs = {'unit','n',XML+'id'} | (set() if is_start else {'rend'})
        valid = (parent_tag in (None, 'table') and LOCATOR.fullmatch(table_number) is not None and
                 number == expected_n and set(node.attrib) == expected_attrs and
                 node.get(XML+'id') == 'source-node-'+number and
                 len(node) == 0 and node.text is None and
                 (node.tail == '\r\n' if is_start else node.tail is None and node.get('rend') == TAIL_REND))
        if not valid:
            raise ValueError('Cassiodorus source table-tail marker differs')


def check_content_node_lxml(node):
    """Independently validate one carrier with lxml node APIs."""
    name = etree.QName(node).localname
    if name == 'ab' and node.get('type') in BLOCKS:
        kind, number = node.get('type'), node.get('n') or ''
        if kind in {'source-tail-text','source-div-leading-text'}:
            suffix = '.tail' if kind == 'source-tail-text' else '.text'
            loc = number[:-len(suffix)] if number.endswith(suffix) else ''
            ok = (bool(loc) and LOCATOR.fullmatch(loc) is not None and
                  node.get(XML+'id') == kind+'-'+loc and node.get(XML+'space') == 'preserve' and
                  set(node.attrib) == {'type','n',XML+'id',XML+'space'} and not len(node) and node.text is not None)
        elif kind == 'source-inline-carrier':
            ok = (DOTTED.fullmatch(number) is not None and set(node.attrib) == {'type','n',XML+'id'} and
                  node.get(XML+'id') == kind+'-'+number and node.text is None and len(node) == 1 and
                  etree.QName(node[0]).localname in INLINE_CHILD_COUNTS and node[0].tail is None)
        elif kind == 'source-hr':
            ok = (number.isdecimal() and node.get(XML+'id') == 'source-node-'+number and
                  set(node.attrib) == {'type','n',XML+'id','rend'} and
                  re.fullmatch(r'source-style:width: (?:15|35|45|65)%;',node.get('rend') or '') is not None and
                  not len(node) and node.text is None)
        else:
            ok = (number in {'2','4107'} and set(node.attrib) == {'type','n',XML+'id'} and
                  node.get(XML+'id') == 'source-node-'+number and not len(node) and node.text is None)
        if not ok:
            raise ValueError('observed Cassiodorus source-native block carrier differs')
    if name in {'table','row','cell'}:
        number = node.get('n') or ''
        expected = {'table': {'n',XML+'id','rend'},
                    'row': {'n',XML+'id'},
                    'cell': ({'n',XML+'id'}, {'n',XML+'id','rend'}, {'n',XML+'id','cols','rend'})}[name]
        shape = set(node.attrib) in expected if name == 'cell' else set(node.attrib) == expected
        parent = node.getparent()
        parent_ok = (name == 'table' and parent is not None and etree.QName(parent).localname == 'div'
                     or name == 'row' and parent is not None and etree.QName(parent).localname == 'table'
                     or name == 'cell' and parent is not None and etree.QName(parent).localname == 'row')
        ok = (LOCATOR.fullmatch(number) is not None and shape and parent_ok and
              node.get(XML+'id') == 'source-node-'+number and
              (name != 'cell' or node.get('cols') is None or node.get('cols') in {'2','3','4','5'}))
        if not ok:
            raise ValueError('observed Cassiodorus source table locator differs')
    if name == 'milestone' and node.get('unit') in {START_UNIT,END_UNIT}:
        unit, number = node.get('unit'), node.get('n') or ''
        parent = node.getparent()
        if parent is None:
            raise ValueError('observed Cassiodorus table boundary lacks table parent')
        table_number = parent.get('n') or ''
        start = unit == START_UNIT
        suffix = '.1' if start else '.1.end'
        attrs = {'unit','n',XML+'id'} | (set() if start else {'rend'})
        ok = (etree.QName(parent).localname == 'table' and LOCATOR.fullmatch(table_number) is not None and
              number == table_number+suffix and set(node.attrib) == attrs and
              node.get(XML+'id') == 'source-node-'+number and
              (parent[0] is node if start else parent[-1] is node) and not len(node) and node.text is None and
              (node.tail == '\r\n' if start else node.tail is None and node.get('rend') == TAIL_REND))
        if not ok:
            raise ValueError('observed Cassiodorus table-tail marker differs')


def check_document_et(root, raw, identity, language, category, collection):
    if (identity != IDENTITY or language != 'en' or category != 'prose' or collection or
            hashlib.sha256(raw).hexdigest() != MASTER_SHA256):
        raise ValueError('Cassiodorus accepted profile identity/master differs')
    body = root.find(NS+'text/'+NS+'body')
    if body is None or len(body) != 1 or len(list(body.iter())) != 38849:
        raise ValueError('Cassiodorus body envelope differs')
    blocks = [node for node in body.iter(NS+'ab') if node.get('type') in BLOCKS]
    if Counter(node.get('type') for node in blocks) != BLOCK_COUNTS:
        raise ValueError('Cassiodorus source block inventory differs')
    tables = list(body.iter(NS+'table'))
    starts = [node for node in body.iter(NS+'milestone') if node.get('unit') == START_UNIT]
    ends = [node for node in body.iter(NS+'milestone') if node.get('unit') == END_UNIT]
    if len(tables) != TABLE_COUNT or len(starts) != TABLE_COUNT or len(ends) != TABLE_COUNT:
        raise ValueError('Cassiodorus table boundary inventory differs')
    for table in tables:
        if (len(table) < 2 or table[0].tag != NS+'milestone' or table[0].get('unit') != START_UNIT
                or table[-1].tag != NS+'milestone' or table[-1].get('unit') != END_UNIT):
            raise ValueError('Cassiodorus table boundary placement differs')
    for node in body.iter():
        check_content_node_et(node, 'table' if node.tag == NS+'milestone' and node.get('unit') in {START_UNIT,END_UNIT} else None)


def check_document_lxml(root, raw, identity, language, category, collection):
    if (identity != IDENTITY or language != 'en' or category != 'prose' or collection or
            hashlib.sha256(raw).hexdigest() != MASTER_SHA256):
        raise ValueError('observed Cassiodorus accepted profile identity/master differs')
    body = root.find(NS+'text/'+NS+'body')
    if body is None or len(body) != 1 or len(list(body.iter())) != 38849:
        raise ValueError('observed Cassiodorus body envelope differs')
    blocks = [node for node in body.iter(NS+'ab') if node.get('type') in BLOCKS]
    if Counter(node.get('type') for node in blocks) != BLOCK_COUNTS:
        raise ValueError('observed Cassiodorus source block inventory differs')
    tables = list(body.iter(NS+'table'))
    starts = [node for node in body.iter(NS+'milestone') if node.get('unit') == START_UNIT]
    ends = [node for node in body.iter(NS+'milestone') if node.get('unit') == END_UNIT]
    if len(tables) != TABLE_COUNT or len(starts) != TABLE_COUNT or len(ends) != TABLE_COUNT:
        raise ValueError('observed Cassiodorus table boundary inventory differs')
    for node in body.iter():
        check_content_node_lxml(node)
