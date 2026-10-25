"""Complete retained BCP1559 HTML expression, including native calendar tables.

Inventory order is not an inferred print reading order. HTML body wrappers are
represented one for one; original ordered attributes are reversible URI-valued
source annotations. HTML head/prolog/comments are explicitly accounted rather
than promoted to liturgical prose. No source spelling or response inference.
"""
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import quote
from lxml import etree, html
from ocd_kernel.library._common import io_path

ROOT = Path(__file__).resolve().parents[2]
NS = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'
CONVERTER_ID = 'ocd-bcp1559-complete-native-html-current-v1'
CONVERTER_VERSION = '1'
ANNO = 'urn:ocd:bcp1559:html:'
NUMERIC_HTML_CHARACTERS = {134: '\u2020', 149: '\u2022'}
INLINE_SOURCE_BLOCKS = {
    (4, '/html/body/table[3]/tr[2]/td[1]/font[1]/p[1]'): ('p', 'font'),
    (5, '/html/body/div[1]/center[1]/table[1]/tr[1]/td[1]/b[1]/h1[1]'): ('h1', 'b'),
    (5, '/html/body/div[1]/center[1]/table[1]/tr[1]/td[1]/b[1]/h3[1]'): ('h3', 'b'),
    (13, '/html/body/table[3]/tr[3]/td[1]/font[1]/div[1]'): ('div', 'font'),
    (13, '/html/body/table[3]/tr[4]/td[1]/font[1]/div[1]'): ('div', 'font'),
}


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':')) + '\n').encode()


def annotation(source):
    obj = {'tag': source.tag if isinstance(source.tag, str) else '#comment',
           'attributes': list(map(list, source.attrib.items()))}
    if not isinstance(source.tag, str):
        obj['comment'] = source.text or ''
    return ANNO + quote(json.dumps(obj, ensure_ascii=False, separators=(',', ':')), safe='')


def mapped(source, member_number, ordinal, ledger, source_path):
    """Closed one-source-element/one-TEI-carrier mapping; preserve child order."""
    index = len(ordinal) + 1
    ordinal.append(source)
    original_tag = source.tag if isinstance(source.tag, str) else '#comment'
    attrs = {XML+'id': f'bcp1559-m{member_number:02d}-n{index:05d}',
             'ana': annotation(source)}
    if (member_number, source_path) in INLINE_SOURCE_BLOCKS:
        expected_tag, parent = INLINE_SOURCE_BLOCKS[(member_number, source_path)]
        if original_tag != expected_tag or source.getparent().tag != parent or any(
                isinstance(q.tag, str) and q.tag not in {'a', 'font', 'span', 'b',
                'strong', 'em', 'i', 'br', 'sup', 'sub', 'small'} for q in source.iterdescendants()):
            raise ValueError('Exact inline source-block exception differs')
        tag = 'seg'; attrs.update(type='source-html-inline-block', subtype=original_tag)
    elif original_tag in ('body', 'p', 'div', 'center', 'blockquote'):
        tag = 'ab'; attrs.update(type='source-block', subtype='html-'+original_tag)
    elif original_tag in ('h1', 'h2', 'h3'):
        tag = 'ab'; attrs['type'] = 'source-'+original_tag
    elif original_tag in ('b', 'strong', 'i', 'em', 'sup', 'sub'):
        tag = 'hi'
        attrs['rend'] = {'b':'bold', 'strong':'bold', 'i':'italic', 'em':'italic',
                         'sup':'superscript', 'sub':'subscript'}[original_tag]
    elif original_tag in ('font', 'span', 'small'):
        tag = 'seg'; attrs['type'] = 'source-html-'+original_tag
    elif original_tag == 'table':
        tag = 'table'; attrs['type'] = 'source-html-table'
    elif original_tag == 'tr':
        tag = 'row'
    elif original_tag == 'td':
        tag = 'cell'
        if source.get('colspan') is not None:
            attrs['cols'] = source.get('colspan')
        if source.get('rowspan') is not None:
            attrs['rows'] = source.get('rowspan')
    elif original_tag == 'ul':
        tag = 'list'; attrs['type'] = 'unordered'
    elif original_tag == 'li':
        tag = 'item'
    elif original_tag == 'br':
        tag = 'lb'
    elif original_tag == 'hr':
        tag = 'milestone'; attrs['unit'] = 'horizontal-rule'
    elif original_tag == 'img':
        tag = 'graphic'; attrs['url'] = source.get('src', '')
        if source.get('alt') is not None:
            attrs['n'] = source.get('alt')
    elif original_tag == 'a':
        tag = 'ref' if source.get('href') is not None else 'seg'
        if tag == 'ref':
            attrs['target'] = source.get('href')
        else:
            attrs['type'] = 'source-html-anchor'
    elif original_tag == '#comment':
        tag = 'anchor'; attrs['type'] = 'source-html-comment'
    else:
        raise ValueError('Unmapped retained HTML element: '+str(original_tag))
    target = etree.Element(NS+tag, attrs)
    if original_tag != '#comment':
        target.text = source.text
        counts = {}
        for child in source:
            name = child.tag if isinstance(child.tag, str) else '#comment'
            counts[name] = counts.get(name, 0)+1
            target.append(mapped(child, member_number, ordinal, ledger,
                                 source_path+'/'+name+'['+str(counts[name])+']'))
    target.tail = source.tail
    ledger.append(dict(member=member_number, source_path=source_path,
                       ordinal=index, source_tag=original_tag,
                       source_attributes=list(map(list, source.attrib.items())),
                       text=source.text, tail=source.tail,
                       target_id=attrs[XML+'id'], target_tag=tag,
                       disposition='comment-annotation' if original_tag=='#comment'
                       else 'native-html-body-carrier'))
    return target


def build(profile):
    root = etree.Element(NS+'TEI', nsmap={None:NS[1:-1]})
    root.append(etree.fromstring(profile['header_xml'].encode()))
    body = etree.SubElement(etree.SubElement(root, NS+'text'), NS+'body')
    ledger = []; members = []
    for number, record in enumerate(profile['source_members'], 1):
        raw = io_path(ROOT/record['path']).read_bytes()
        if len(raw)!=record['bytes'] or sha256(raw).hexdigest()!=record['sha256']:
            raise ValueError('Retained member bytes differ: '+record['path'])
        # All declared sources specify ISO-8859-1 and contain no C1 bytes.
        if any(0x80 <= byte <= 0x9f for byte in raw):
            raise ValueError('Undeclared C1 source encoding ambiguity')
        parser = html.HTMLParser(encoding='iso-8859-1', remove_comments=False)
        doc = html.document_fromstring(raw, parser=parser)
        entities = []
        for match in re.finditer(rb'&#(x[0-9A-Fa-f]+|[0-9]+);', raw):
            literal = match.group(1)
            code = int(literal[1:], 16) if literal[:1].lower()==b'x' else int(literal)
            if 0x80 <= code <= 0x9f:
                if code not in NUMERIC_HTML_CHARACTERS:
                    raise ValueError('Unreviewed HTML numeric C1 reference')
                entities.append(dict(byte_start=match.start(), byte_end=match.end(),
                                     lexeme=match.group().decode('ascii'), numeric_value=code,
                                     decoded_character=NUMERIC_HTML_CHARACTERS[code]))
        for code, decoded in NUMERIC_HTML_CHARACTERS.items():
            occurrences = sum((n.text or '').count(chr(code)) + (n.tail or '').count(chr(code))
                              for n in doc.iter())
            if occurrences != sum(e['numeric_value']==code for e in entities):
                raise ValueError('Numeric HTML entity source-location census differs')
            for n in doc.iter():
                if n.text:
                    n.text=n.text.replace(chr(code), decoded)
                if n.tail:
                    n.tail=n.tail.replace(chr(code), decoded)
        native_body = doc.find('body')
        if native_body is None or doc.find('head/title') is None:
            raise ValueError('HTML member envelope differs')
        member = etree.SubElement(body, NS+'div', type='retained-member', n=record['name'])
        etree.SubElement(member, NS+'head').text = ''.join(doc.find('head/title').itertext())
        ordinals = []
        member.append(mapped(native_body, number, ordinals, ledger, '/html/body'))
        members.append(dict(member=number, name=record['name'], sha256=record['sha256'],
                            html_envelope=etree.tostring(doc, encoding='unicode', method='xml'),
                            native_body_elements=len(ordinals),
                            numeric_character_references=entities,
                            numeric_reference_decoding='HTML numeric-reference-end-state: 0x86 dagger and 0x95 bullet; original source byte lexemes retained.',
                            post_html_whitespace=raw.decode('latin1').rsplit('</html>', 1)[1],
                            pre_html_declaration=raw.decode('latin1').split('<html>', 1)[0],
                            parser_diagnostics=[str(q) for q in parser.error_log],
                            disposition='All body carriers represented; head/prolog remain source evidence, title also literal member head.'))
    raw = etree.tostring(root, encoding='UTF-8', xml_declaration=True)
    ledger.sort(key=lambda q:(q['member'], q['ordinal']))
    return raw, dict(contract='ocd-bcp1559-native-html-accountability-v1',
                     members=members, nodes=ledger,
                     parser_qualification='libxml2 HTML recovery is part of this explicit electronic-source reading; it is not print or browser visual collation.')


def _convert(manifest):
    manifest.verify()
    profile=json.loads(manifest.authority_path('profile').read_bytes())
    raw, ledger=build(profile)
    return {'content.tei.xml':raw, 'source-accountability.json':canonical(ledger),
            'provenance.json':canonical({'work_id':'bcp-1559', 'source_manifest_sha256':manifest.sha256,
                                        'scope':profile['scope'], 'status':'nonaccepted'}),
            'README.source.md':manifest.authority_path('source-readme').read_bytes(),
            'unresolved.jsonl':b''.join(canonical(q) for q in profile['questions'])}


_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION
_convert.implementation_path=Path(__file__).resolve()
