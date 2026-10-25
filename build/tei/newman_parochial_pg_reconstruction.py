"""Faithful native reconstruction of the retained Newman PG VII/VIII witnesses.

Provider administration is delivered verbatim in the source README. The book's
complete front matter, contents, eighteen sermons and terminal volume label
remain in TEI. Numeric note defects and the transcriber's uncertainty are literal.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import re
from lxml import etree

TEI = 'http://www.tei-c.org/ns/1.0'
NS = '{' + TEI + '}'
XML = '{http://www.w3.org/XML/1998/namespace}'
ID = 'ocd-newman-parochial-pg-retained-native-v1'
ROMANS = ('I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII','XIII','XIV','XV','XVI','XVII','XVIII')
SOURCES = {
    'pg24256.txt': ('VII', '713da47f79c97a5b188bd50a43a97a9a419d72c5ee92605b1e3d5effcb86b789', 386616, 143),
    'pg24284.txt': ('VIII', 'b172c4f0379098ac1fdca2fbc27b08fb830c4eea5ce43d39d0263887b7fa3f53', 406274, 201),
}
TOKEN = re.compile(r"_[^_]+_|\[Transcriber's note:[^\]]+\]|\[\d+\]", re.S)


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))+'\n').encode('utf-8')


def _blocks(text, start, stop):
    """Inventory every text and whitespace carrier before constructing XML."""
    blocks = []
    offset = start
    group = ''
    group_start = start
    blank = None
    for line in text[start:stop].splitlines(keepends=True):
        current = not line.strip()
        if blank is not None and current != blank:
            blocks.append(dict(start=group_start, stop=offset, text=group, whitespace=blank))
            group = ''
            group_start = offset
        blank = current
        group += line
        offset += len(line)
    if group:
        blocks.append(dict(start=group_start, stop=offset, text=group, whitespace=blank))
    if offset != stop or ''.join(b['text'] for b in blocks) != text[start:stop]:
        raise ValueError('Newman complete paragraph/whitespace inventory differs')
    return blocks


def inventory(raw, logical):
    name = Path(logical).name
    if name not in SOURCES:
        raise ValueError('Newman unsupported source member')
    volume, digest, size, note_count = SOURCES[name]
    if len(raw) != size or sha256(raw).hexdigest() != digest:
        raise ValueError('Newman retained source bytes drifted')
    text = raw.decode('utf-8-sig').replace('\r\n', '\n')
    if '\r' in text:
        raise ValueError('Newman unsupported lone carriage return')
    starts = list(re.finditer(r'^\*\*\* START OF THE PROJECT GUTENBERG EBOOK .+ \*\*\*\n', text, re.M))
    ends = list(re.finditer(r'^\*\*\* END OF THE PROJECT GUTENBERG EBOOK .+ \*\*\*\n', text, re.M))
    if len(starts) != 1 or len(ends) != 1 or starts[0].end() >= ends[0].start():
        raise ValueError('Newman provider boundary differs')
    first, last = starts[0].end(), ends[0].start()
    heads = list(re.finditer(r'^SERMON ([IVXLCDM]+)\.?\n', text[first:last], re.M))
    if len(heads) != 36 or tuple(h[1] for h in heads[:18]) != ROMANS or tuple(h[1] for h in heads[18:]) != ROMANS:
        raise ValueError('Newman contents/body sermon boundaries differ')
    body_heads = [first+h.start() for h in heads[18:]]
    endings = list(re.finditer(r'^END OF VOL\. '+volume+r'\.\n', text, re.M))
    if len(endings) != 1 or not body_heads[-1] < endings[0].start() < last:
        raise ValueError('Newman terminal volume label differs')
    terminus = endings[0].start()
    regions = [dict(role='front', start=first, stop=body_heads[0])]
    regions += [dict(role='sermon', number=str(i+1), roman=ROMANS[i], start=p,
                     stop=body_heads[i+1] if i<17 else terminus) for i,p in enumerate(body_heads)]
    regions.append(dict(role='back', start=terminus, stop=last))
    definitions = 0
    exceptions = []
    for region in regions:
        region['blocks'] = _blocks(text, region['start'], region['stop'])
        nonblank = [b for b in region['blocks'] if not b['whitespace']]
        labels = {}
        if region['role'] == 'sermon':
            if len(nonblank)<4 or not re.fullmatch(r'SERMON '+region['roman']+r'\.?\n',nonblank[0]['text']) or not nonblank[2]['text'].startswith('"'):
                raise ValueError('Newman sermon heading/title/epigraph differs')
            for block in nonblank:
                match = re.match(r'^\[(\d+)\] ', block['text'])
                if match:
                    if match[1] in labels:
                        raise ValueError('Newman duplicate source note definition')
                    labels[match[1]] = block['start']
            definitions += len(labels)
        region['note_labels'] = labels
        seen = set()
        for index, block in enumerate(nonblank):
            if block['text'].count('_') % 2:
                raise ValueError('Newman unmatched source emphasis marker')
            definition = re.match(r'^\[(\d+)\] ', block['text']) if region['role']=='sermon' else None
            block['kind'] = ('head' if region['role']=='sermon' and index<2 else
                             'quote' if region['role']=='sermon' and index==2 else
                             'note' if definition else 'head' if region['role']=='back' else 'p')
            if definition:
                block['label'] = definition[1]
            for marker in re.finditer(r'\[(\d+)\]', block['text']):
                if definition and marker.start()==0:
                    continue
                if region['role']=='sermon':
                    seen.add(marker[1])
                    if marker[1] not in labels:
                        exceptions.append(dict(kind='unbound-note-reference', sermon=region['number'], label=marker[1], character=block['start']+marker.start()))
            for marker in re.finditer(r"\[Transcriber's note:[^\]]+\]", block['text']):
                exceptions.append(dict(kind='literal-transcriber-uncertainty', sermon=region.get('number'), character=block['start']+marker.start(), wording=marker[0]))
        for label, position in labels.items():
            if label not in seen:
                exceptions.append(dict(kind='orphan-note-definition', sermon=region['number'], label=label, character=position))
    if definitions != note_count:
        raise ValueError('Newman complete footnote definition census differs')
    return dict(source_path=logical, source_sha256=digest, source_bytes=size, volume=volume,
                decoded_text=text, book_start=first, book_stop=last, regions=regions,
                note_definitions=definitions, exceptions=exceptions)


def _append(parent, value):
    if len(parent):
        parent[-1].tail = (parent[-1].tail or '')+value
    else:
        parent.text = (parent.text or '')+value


def _inline(parent, value, region, slug):
    cursor = 0
    for token in TOKEN.finditer(value):
        _append(parent, value[cursor:token.start()])
        word = token[0]
        if word.startswith('_'):
            child = etree.SubElement(parent, NS+'hi', rend='italic', ana='urn:ocd:newman-parochial:underscore-delimited')
            _inline(child, word[1:-1], region, slug)
        elif word.startswith("[Transcriber's note:"):
            child = etree.SubElement(parent, NS+'note', type='transcriber')
            child.text = word
        else:
            label = word[1:-1]
            if label in region['note_labels']:
                child = etree.SubElement(parent, NS+'ref', type='note-reference', target='#'+slug+'-s'+region['number']+'-n'+label)
            else:
                child = etree.SubElement(parent, NS+'seg', type='literal-unbound-note-marker', n=label)
            child.text = word
        cursor = token.end()
    _append(parent, value[cursor:])


def build(raw, logical):
    source = inventory(raw, logical)
    text = source['decoded_text']
    slug = Path(logical).stem
    root = etree.Element(NS+'TEI', nsmap={None:TEI})
    header = etree.SubElement(root, NS+'teiHeader')
    fd = etree.SubElement(header, NS+'fileDesc')
    ts = etree.SubElement(fd, NS+'titleStmt')
    etree.SubElement(ts, NS+'title').text = 'Parochial and Plain Sermons, Vol. '+source['volume']+' (of 8)'
    etree.SubElement(ts, NS+'author').text = 'JOHN HENRY NEWMAN, B.D.'
    etree.SubElement(etree.SubElement(fd, NS+'publicationStmt'), NS+'p').text = 'Nonaccepted reconstruction of the exact retained Project Gutenberg electronic witness; human, print, rights and publication decisions remain open.'
    bibl = etree.SubElement(etree.SubElement(fd, NS+'sourceDesc'), NS+'bibl')
    etree.SubElement(bibl, NS+'title').text = 'PAROCHIAL AND PLAIN SERMONS; VOL. '+source['volume']+'.; New Edition'
    etree.SubElement(bibl, NS+'publisher').text = 'Longmans, Green, and Co.'
    etree.SubElement(bibl, NS+'pubPlace').text = 'London; New York: 15 East 16th Street'
    etree.SubElement(bibl, NS+'date').text = '1891'
    etree.SubElement(bibl, NS+'idno', type='retained-source-sha256').text = source['source_sha256']
    etree.SubElement(bibl, NS+'note', type='source-location').text = logical
    resp = etree.SubElement(bibl, NS+'respStmt')
    etree.SubElement(resp, NS+'resp').text = 'E-text prepared by'
    etree.SubElement(resp, NS+'name').text = 'Al Haines'
    enc = etree.SubElement(header, NS+'encodingDesc')
    etree.SubElement(enc, NS+'p').text = 'Exact retained electronic volume only. UTF-8 BOM is accounted as encoding and CRLF becomes LF. All book characters, paragraph boundaries, wrapped lines and source footnote labels are conserved; paired underscore markers become italic hi with an explicit reversible source annotation. Numeric footnote labels link only within their own source-defined sermon when the exact definition exists. No Bible reference normalization or source-error correction. Provider opening, markers, complete footer/license and source credit are retained in README.source.md.'
    document = etree.SubElement(root, NS+'text', {XML+'lang':'en'})
    front = etree.SubElement(document, NS+'front')
    body = etree.SubElement(document, NS+'body')
    back = etree.SubElement(document, NS+'back')
    carriers = []
    for region in source['regions']:
        container = front if region['role']=='front' else back if region['role']=='back' else body
        attrs = {'type':'source-div1' if region['role']=='sermon' else 'source-'+region['role'], XML+'id':slug+'-'+region['role']+region.get('number','')}
        if region['role']=='sermon':
            attrs['n'] = region['number']
        division = etree.SubElement(container, NS+'div', attrs)
        for number, block in enumerate(region['blocks'], 1):
            feature = slug+'-'+region['role']+region.get('number','')+'-b'+str(number)
            item = dict(carrier_id=feature, start=block['start'], stop=block['stop'], source_sha256=sha256(block['text'].encode()).hexdigest(), disposition='structural-whitespace' if block['whitespace'] else block['kind'])
            carriers.append(item)
            if block['whitespace']:
                _append(division, block['text'])
                continue
            attrs = {XML+'id':feature, 'corresp':logical+'#characters='+str(block['start'])+'-'+str(block['stop']), XML+'space':'preserve'}
            if block['kind']=='head':
                attrs['type'] = 'source-terminal-label' if region['role']=='back' else 'source-heading'
            elif block['kind']=='note':
                attrs.pop(XML+'id')
                attrs[XML+'id'] = slug+'-s'+region['number']+'-n'+block['label']
                attrs.update(n=block['label'], type='footnote', place='end')
            node = etree.SubElement(division, NS+block['kind'], attrs)
            value = block['text']
            if block['kind']=='note':
                prefix = '['+block['label']+'] '
                node.text = prefix
                value = value[len(prefix):]
            _inline(node, value, region, slug)
    content = etree.tostring(root, encoding='UTF-8', xml_declaration=True)
    account = {k:source[k] for k in ('source_path','source_sha256','source_bytes','volume','book_start','book_stop','note_definitions','exceptions')}
    account.update(contract='ocd-newman-parochial-pg-accountability-v1', content_sha256=sha256(content).hexdigest(), carriers=carriers,
                   encoding_dispositions={'utf8_bom':raw.startswith(b'\xef\xbb\xbf'),'crlf_to_lf':raw.count(b'\r\n')},
                   sermons=18, contents_sermons=18, complete_eight_volume_claim=False,
                   provider_administration_disposition='Complete literal opening/start marker and end marker/footer are delivered in README.source.md; excluded from book projection.')
    return content, account, source


def _convert(manifest):
    members = manifest.record['source_members']
    if len(members)!=1:
        raise ValueError('Newman each candidate must have exactly one retained electronic volume')
    logical = members[0]['path']
    raw = manifest.authority_path('retained-source').read_bytes()
    if (manifest.record['work_id']!='newman-parochial-sermons' or manifest.record['ticket_id']!='LIB-018'
            or manifest.record['source_id']!=Path(logical).stem+'-retained-electronic'
            or logical!='raw/gutenberg/sermons/newman/'+Path(logical).name
            or members[0]['bytes']!=len(raw) or members[0]['sha256']!=sha256(raw).hexdigest()):
        raise ValueError('Newman declared source member/identity differs from exact retained authority')
    authority=next(a for a in manifest.record['authorities'] if a['name']=='retained-source')
    if authority['path']!=logical or authority['role']!='primary-source':
        raise ValueError('Newman declared member is not its primary retained authority')
    content, account, source = build(raw, logical)
    policy = json.loads(manifest.authority_path('policy').read_bytes())
    if source['exceptions'] != policy['literal_source_exceptions']:
        raise ValueError('Newman source exception policy differs')
    readme = manifest.authority_path('source-readme').read_bytes()
    text = source['decoded_text']
    if text[:source['book_start']].encode() not in readme or text[source['book_stop']:].encode() not in readme:
        raise ValueError('Newman complete provider administration is absent from README')
    return {'content.tei.xml':content,'source-accountability.json':canonical(account),
            'README.source.md':readme,'provenance.json':canonical(policy['provenance']),
            'unresolved.jsonl':b''.join(canonical(x) for x in policy['unresolved'])}


_convert.converter_id = ID
_convert.converter_version = '1'
_convert.implementation_path = Path(__file__).resolve()
