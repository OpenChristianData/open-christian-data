"""Exact retained Strong II source-line grammar for native prose readers.

This grammar does not reconstruct source text or establish acceptance.
The maintained mapper and its independent observer must each retain and check
the actual fields. No generic policy is changed by importing this module.
"""
from collections import Counter
from hashlib import sha256
import re

PROFILE = 'ocd-prose-strong-vol2-retained-source-lines-v1'
MASTER_SHA = '12938e99a0aef121f5380b9ee4b0c8d58a4d8afbc5f3e19d30bff7e6a85ed3ab'
IDENTITY = {'work_id': 'strong-systematic-theology-vol-2', 'textual_form_id': 'strong-systematic-theology-vol-2-english', 'edition_id': 'strong-systematic-theology-vol-2-retained-electronic-witness'}
NS = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'
BLOCK_COUNTS = {'title-page-line': 14, 'contents-line': 197, 'front-matter-line': 13}
HEADING_COUNTS = {'part': 3, 'chapter': 5, 'section': 22, 'subsection': 57, 'subsubsection': 75, 'subsubsubsection': 7, 'subsubsubsubsection': 6}
CONTINUED_HEADINGS = {1979: 1980, 12757: 12758, 17142: 17143, 17529: 17530, 18166: 18167, 18519: 18520, 24652: 24653, 29532: 29533}
COUNTS = {'text': 1, 'front': 1, 'body': 1, 'div': 178, 'ab': 224, 'head': 175, 'p': 2362, 'seg': 29763, 'lb': 27401}

def route(identity, raw, *, language, category, collection, allow_acceptance_metadata, projection_profile=None, source_base=None):
    if identity.get('work_id') != IDENTITY['work_id']:
        return False
    if identity != IDENTITY or sha256(raw).hexdigest() != MASTER_SHA or language != 'en' or category != 'prose' or collection or not allow_acceptance_metadata or projection_profile is not None or source_base is not None:
        raise ValueError('Strong II source-line route requires the exact reviewed master and accepted identity')
    return True

def check_et(root):
    """Check finite grammar and attachment from actual parsed carrier fields."""
    text = root.find(NS+'text')
    if root.tag != NS+'TEI' or root.attrib or [n.tag for n in root] != [NS+'teiHeader', NS+'text'] or text is None or text.attrib or text.text is not None or text.tail is not None or [n.tag for n in text] != [NS+'front', NS+'body']:
        raise ValueError('Strong II exact readable outer envelope differs')
    front, body = text
    if [n.get('type') for n in front] != ['title-page', 'contents', 'front-matter'] or [n.get('n') for n in body] != ['IV', 'V', 'VI'] or any(n.get('type') != 'part' for n in body):
        raise ValueError('Strong II exact front/body regions differ')
    parents = {child: node for node in text.iter() for child in node}
    counts = Counter()
    blocks, headings, numbers = Counter(), Counter(), []
    for node in text.iter():
        if not isinstance(node.tag, str) or not node.tag.startswith(NS):
            raise ValueError('Strong II unsupported source namespace/comment carrier')
        tag = node.tag.removeprefix(NS)
        counts[tag] += 1
        if node.tail is not None:
            raise ValueError('Strong II unexpected native tail slot')
        parent = parents.get(node)
        if tag in {'head', 'ab', 'seg'}:
            if set(node.attrib) != {XML+'id', 'n', 'type', XML+'space'} or node.get(XML+'space') != 'preserve' or tag != 'head' and len(node) or node.text is None or not node.text.strip():
                raise ValueError('Strong II source-line field/space/child shape differs')
            number = node.get('n')
            if re.fullmatch(r'[1-9][0-9]*', number or '') is None or not 26 <= int(number) <= 34172 or node.get(XML+'id') != f'strong-systematic-theology-vol-2-line-{int(number):05d}':
                raise ValueError('Strong II literal source-line locator differs')
            numbers.append(int(number))
            if tag == 'ab':
                owner = {'title-page-line': 'title-page', 'contents-line': 'contents', 'front-matter-line': 'front-matter'}.get(node.get('type'))
                if owner is None or parent.tag != NS+'div' or parent.get('type') != owner or parents.get(parent) is not front:
                    raise ValueError('Strong II source block is attached to the wrong front region')
                blocks[node.get('type')] += 1
            elif tag == 'head':
                if node.get('type') not in HEADING_COUNTS or parent.tag != NS+'div' or parent.get('type') != node.get('type') or parent[0] is not node:
                    raise ValueError('Strong II heading role/owner differs')
                headings[node.get('type')] += 1
                continuation = CONTINUED_HEADINGS.get(int(number))
                if continuation is None and len(node) or continuation is not None and ([child.tag for child in node] != [NS+'lb', NS+'seg'] or node[1].get('n') != str(continuation)):
                    raise ValueError('Strong II located two-line heading continuation differs')
            elif parent.tag not in {NS+'p', NS+'head'} or node.get('type') != 'source-line':
                raise ValueError('Strong II paragraph source-line ownership differs')
        elif tag == 'p':
            if node.attrib != {XML+'space': 'preserve'} or node.text is not None or not len(node) or any(child.tag != (NS+'seg' if i % 2 == 0 else NS+'lb') for i, child in enumerate(node)) or len(node) % 2 != 1 or parent.tag != NS+'div':
                raise ValueError('Strong II exact source paragraph/line-break grouping differs')
        elif tag == 'lb':
            if node.attrib or node.text is not None or len(node) or parent.tag not in {NS+'p', NS+'head'}:
                raise ValueError('Strong II literal empty line-break carrier differs')
        elif tag == 'div':
            kind = node.get('type')
            if node.text is not None:
                raise ValueError('Strong II unexpected division leading text')
            if parent is front:
                if set(node.attrib) != {'type'} or kind not in {'title-page', 'contents', 'front-matter'} or any(child.tag != NS+'ab' for child in node):
                    raise ValueError('Strong II exact front division fields differ')
            elif set(node.attrib) != {'type', 'n'} or kind not in HEADING_COUNTS or not node.get('n') or not len(node) or node[0].tag != NS+'head' or any(child.tag not in {NS+'head', NS+'p', NS+'div'} for child in node) or sum(child.tag == NS+'head' for child in node) != 1:
                raise ValueError('Strong II nested heading division fields differ')
        elif tag in {'front', 'body', 'text'}:
            if node.attrib or node.text is not None:
                raise ValueError('Strong II exact region leading fields differ')
        else:
            raise ValueError('Strong II unsupported native carrier')
    if dict(counts) != COUNTS or dict(blocks) != BLOCK_COUNTS or dict(headings) != HEADING_COUNTS or len(numbers) != 30162 or numbers != sorted(set(numbers)):
        raise ValueError('Strong II source-carrier counts/order/unique locators differ')
    return {'source_line_carriers': 30162, 'paragraph_groups': 2362, 'paragraph_lines': 29755, 'heading_continuation_lines': 8, 'paragraph_line_breaks': 27393, 'heading_line_breaks': 8, 'line_breaks': 27401, 'front_regions': 3, 'body_parts': 3}

PROPOSED_POLICY_EXTENSIONS = {
    'source_block_types': tuple(BLOCK_COUNTS),
    'attributes': {'head': (XML+'space',), 'ab': (XML+'space',), 'seg': (XML+'space',), 'p': (XML+'space',)},
    'heading_continuations': CONTINUED_HEADINGS,
    'space_disposition': 'Literal xml:space=preserve stays in the complete private node inventory; no generic public schema change is needed.',
    'space_constraint': 'Only preserve; exact attribute sets checked by the gated source grammar.',
    'private_inventory': 'Retain exact source IDs, all attributes and text/tail ownership; public structure must preserve source line carriers and paragraph line breaks.',
    'reader_status': 'Proposal only; actual maintained reader positive and independent row readback still required.',
}


def check_lxml(root):
    """Observe exact source carriers separately from the ET mapper-side grammar."""
    text = root.find(NS+'text')
    if root.tag != NS+'TEI' or dict(root.attrib) or [n.tag for n in root] != [NS+'teiHeader', NS+'text'] or text is None or dict(text.attrib) or text.text is not None or text.tail is not None or [n.tag for n in text] != [NS+'front', NS+'body']:
        raise ValueError('Observed Strong II readable envelope differs')
    front, body = text
    if [n.get('type') for n in front] != ['title-page','contents','front-matter'] or [(n.get('type'),n.get('n')) for n in body] != [('part','IV'),('part','V'),('part','VI')]:
        raise ValueError('Observed Strong II regions differ')
    counts, blocks, headings, addresses = Counter(), Counter(), Counter(), []
    for node in text.iter():
        local = node.tag.removeprefix(NS) if isinstance(node.tag,str) and node.tag.startswith(NS) else None
        counts[local] += 1
        parent = node.getparent()
        if node.tail is not None:
            raise ValueError('Observed Strong II unbound tail slot')
        if local in {'ab','head','seg'}:
            if dict(node.attrib).keys() != {XML+'id','n','type',XML+'space'} or node.get(XML+'space') != 'preserve' or node.text is None or not node.text.strip():
                raise ValueError('Observed Strong II source-line fields differ')
            value = node.get('n','')
            if re.fullmatch(r'[1-9][0-9]*',value) is None or not 26 <= int(value) <= 34172 or node.get(XML+'id') != 'strong-systematic-theology-vol-2-line-'+value.zfill(5):
                raise ValueError('Observed Strong II source-line address differs')
            addresses.append(int(value))
            if local == 'ab':
                owner = {'title-page-line':'title-page','contents-line':'contents','front-matter-line':'front-matter'}.get(node.get('type'))
                if len(node) or owner is None or parent.tag != NS+'div' or parent.get('type') != owner or parent.getparent() is not front:
                    raise ValueError('Observed Strong II source front-block ownership differs')
                blocks[node.get('type')] += 1
            elif local == 'head':
                expected = CONTINUED_HEADINGS.get(int(value))
                if parent.tag != NS+'div' or parent.get('type') != node.get('type') or parent[0] is not node or node.get('type') not in HEADING_COUNTS:
                    raise ValueError('Observed Strong II heading ownership differs')
                if expected is None and len(node) or expected is not None and ([n.tag for n in node] != [NS+'lb',NS+'seg'] or node[1].get('n') != str(expected)):
                    raise ValueError('Observed Strong II heading continuation differs')
                headings[node.get('type')] += 1
            elif len(node) or node.get('type') != 'source-line' or parent.tag not in {NS+'p',NS+'head'}:
                raise ValueError('Observed Strong II source-line attachment differs')
        elif local == 'p':
            expected = [NS+'seg' if index % 2 == 0 else NS+'lb' for index in range(len(node))]
            if dict(node.attrib) != {XML+'space':'preserve'} or node.text is not None or len(node) == 0 or len(node)%2 != 1 or [n.tag for n in node] != expected or parent.tag != NS+'div':
                raise ValueError('Observed Strong II paragraph-line grouping differs')
        elif local == 'lb':
            if dict(node.attrib) or node.text is not None or len(node) or parent.tag not in {NS+'p',NS+'head'}:
                raise ValueError('Observed Strong II empty line-break fields differ')
        elif local == 'div':
            if node.text is not None:
                raise ValueError('Observed Strong II division leading text differs')
            if parent is front:
                if dict(node.attrib).keys() != {'type'} or node.get('type') not in {'title-page','contents','front-matter'} or any(n.tag != NS+'ab' for n in node):
                    raise ValueError('Observed Strong II front division fields differ')
            elif dict(node.attrib).keys() != {'type','n'} or node.get('type') not in HEADING_COUNTS or not node.get('n') or not len(node) or node[0].tag != NS+'head' or sum(n.tag == NS+'head' for n in node) != 1 or any(n.tag not in {NS+'head',NS+'p',NS+'div'} for n in node):
                raise ValueError('Observed Strong II nested division fields differ')
        elif local in {'front','body','text'}:
            if dict(node.attrib) or node.text is not None:
                raise ValueError('Observed Strong II region leading fields differ')
        else:
            raise ValueError('Observed Strong II unsupported source carrier')
    if dict(counts) != COUNTS or dict(blocks) != BLOCK_COUNTS or dict(headings) != HEADING_COUNTS or len(addresses) != 30162 or addresses != sorted(set(addresses)):
        raise ValueError('Observed Strong II carrier count/order/identity differs')
    return {'source_line_carriers':30162,'paragraph_groups':2362,'heading_continuations':8}


def check_content_node(node, parent_tag):
    """Bound admission for per-unit mapper calls; whole source checked upstream."""
    tag = node.tag.removeprefix(NS)
    if tag in {'ab','head','seg'}:
        if set(node.attrib) != {XML+'id','n','type',XML+'space'} or node.get(XML+'space') != 'preserve' or node.text is None or not node.text.strip() or node.tail is not None:
            raise ValueError('Strong II source-line content fields differ')
        number = node.get('n','')
        if re.fullmatch(r'[1-9][0-9]*',number) is None or not 26 <= int(number) <= 34172 or node.get(XML+'id') != 'strong-systematic-theology-vol-2-line-'+number.zfill(5):
            raise ValueError('Strong II source-line content locator differs')
        if tag == 'seg' and (len(node) or node.get('type') != 'source-line' or parent_tag not in {'p','head'}):
            raise ValueError('Strong II source-line content parent differs')
        if tag == 'ab' and (len(node) or node.get('type') not in BLOCK_COUNTS or parent_tag != 'div'):
            raise ValueError('Strong II source-block content fields differ')
        if tag == 'head':
            expected = CONTINUED_HEADINGS.get(int(number))
            if parent_tag != 'div' or node.get('type') not in HEADING_COUNTS or expected is None and len(node) or expected is not None and ([n.tag for n in node] != [NS+'lb',NS+'seg'] or node[1].get('n') != str(expected)):
                raise ValueError('Strong II source heading continuation content differs')
    elif tag == 'p':
        if dict(node.attrib) != {XML+'space':'preserve'} or node.text is not None or node.tail is not None or not len(node) or len(node)%2 != 1 or [n.tag for n in node] != [NS+'seg' if i%2 == 0 else NS+'lb' for i in range(len(node))]:
            raise ValueError('Strong II source paragraph content grouping differs')
    elif tag == 'lb' and (node.attrib or node.text is not None or node.tail is not None or len(node) or parent_tag not in {'p','head'}):
        raise ValueError('Strong II source line-break content fields differ')
    elif tag not in {'div','lb'}:
        raise ValueError('Strong II unsupported source content carrier')
