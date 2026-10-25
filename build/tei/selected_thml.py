"""Bounded per-work ThML reconstruction consuming acquisition-owned selections."""
from __future__ import annotations

import json
import re

from lxml import etree

from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.source_selection import (
    verify_complete_source_accounting,
    verify_source_selection,
)
from ocd_kernel.tei.writer import tei_el, stamp_header


TAGS = {'div1': 'div', 'div2': 'div', 'div3': 'div', 'div': 'div', 'p': 'p',
        'h1': 'head', 'h2': 'head', 'h3': 'head', 'span': 'seg', 'i': 'hi', 'em': 'hi',
        'note': 'note', 'pb': 'pb', 'scripRef': 'ref', 'name': 'name',
        'cite': 'title', 'a': 'ref', 'ul': 'list', 'li': 'item',
        'scripContext': 'milestone', 'insertIndex': 'milestone'}


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def _node_kind(node):
    if isinstance(node, etree._Comment):
        return 'comment'
    if isinstance(node, etree._ProcessingInstruction):
        return 'processing-instruction'
    raise ValueError(f'unsupported document-shell node: {type(node).__name__}')


def _shell_node(node, tree, disposition):
    record = {
        'kind': _node_kind(node),
        'path': tree.getroottree().getpath(node) if node.getparent() is not None else None,
        'text': node.text or '',
        'tail': node.tail or '',
        'disposition': disposition,
    }
    if isinstance(node, etree._ProcessingInstruction):
        record['target'] = node.target
    return record


def _document_shell(raw, tree, selected_roots):
    root = tree.getroottree().getroot()
    before = []
    node = root.getprevious()
    while node is not None:
        before.append(node)
        node = node.getprevious()
    before.reverse()
    after = []
    node = root.getnext()
    while node is not None:
        after.append(node)
        node = node.getnext()

    def selected_comment(node):
        parent = node.getparent()
        while parent is not None:
            if parent in selected_roots:
                return True
            parent = parent.getparent()
        return False

    declaration = None
    if raw.startswith(b'<?xml') and b'?>' in raw:
        declaration = raw.split(b'?>', 1)[0].decode('ascii') + '?>'
    comments = []
    for node in tree.iter():
        if isinstance(node, (etree._Comment, etree._ProcessingInstruction)):
            comments.append(_shell_node(
                node,
                tree,
                'preserved-in-tei' if selected_comment(node) else 'accounted-outside-selected-content',
            ))
    head = tree.find('ThML.head')
    head_children = []
    if head is not None:
        for position, child in enumerate(head):
            if not isinstance(child.tag, str):
                raise ValueError('unsupported non-element node in ThML head')
            if child.tag == 'style' and child.get('type') == 'text/css':
                disposition = 'represented-in-tei-encodingDesc'
            elif child.tag == 'style' and not ''.join(child.itertext()).strip():
                disposition = 'accounted-empty-source-stylesheet'
            else:
                disposition = 'reproduced-in-source-readme'
            head_children.append({
                'position': position,
                'tag': child.tag,
                'attributes': dict(child.attrib),
                'text': ''.join(child.itertext()).strip(),
                'disposition': disposition,
            })
    docinfo = tree.getroottree().docinfo
    return {
        'xml_declaration': declaration,
        'doctype': docinfo.doctype or None,
        'root_name': etree.QName(root).localname,
        'prolog': [_shell_node(node, tree, 'accounted-source-document-shell') for node in before],
        'epilog': [_shell_node(node, tree, 'accounted-source-document-shell') for node in after],
        'comments_and_processing_instructions': comments,
        'head_children': head_children,
    }


def _tei_region(source, unit):
    if source.tag == 'div1' and source.get('title') == 'Title Page':
        if unit['role'] != 'body':
            raise ValueError('a source title page must have the acquisition body role')
        return 'front'
    return unit['role']


def _convert(manifest):
    manifest.verify()
    root_path = manifest.repository_root
    acquisition = validate_acquisition(manifest.authority_path('acquisition'), root=root_path)
    work = load_work(manifest.authority_path('work'))
    verified = verify_source_selection(acquisition, work, root=root_path)
    selection = acquisition['source_selection']
    raw = manifest.authority_path('retained-source').read_bytes()
    tree = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
    for style in tree.xpath('/ThML/ThML.head/style[not(@type="text/css")]'):
        if ''.join(style.itertext()).strip():
            raise ValueError('unsupported non-CSS retained stylesheet content')
    form = next(f for f in work['textual_forms'] if any(e['edition_id'] == acquisition['edition_id'] for e in f['editions']))
    edition = next(e for e in form['editions'] if e['edition_id'] == acquisition['edition_id'])
    root = tei_el('TEI', {'xml:id': work['work_id']})
    containing_source = edition.get('containing_source')
    header = stamp_header(title=work['title'], author='; '.join(c['name'] for c in work.get('creators', []) if c.get('role') == 'author'),
        contributors=[], source_url=acquisition['url'], source_sha256=acquisition['retained_files'][0]['sha256'],
        print_source=containing_source['title'] if containing_source else '', rights_statement=acquisition.get('rights'))
    if containing_source is None:
        source_desc = header.find('.//t:bibl', {'t': 'http://www.tei-c.org/ns/1.0'})
        print_note = source_desc.find('{http://www.tei-c.org/ns/1.0}note[@type="print-source"]')
        if print_note is not None:
            source_desc.remove(print_note)
    root.append(header)
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    binding = header.find('.//t:bibl', ns)
    for key, value in dict(work_id=work['work_id'], textual_form_id=form['textual_form_id'], edition_id=edition['edition_id'],
            acquisition_id=acquisition['acquisition_id'], source_sha256=acquisition['retained_files'][0]['sha256'],
            source_bytes=str(len(raw)), source_selection_sha256=verified['selection_sha256']).items():
        binding.append(tei_el('idno', {'type': key}, text=value))
    binding.append(tei_el('note', {'type':'source-location'}, text=selection['member_path']))
    binding.append(tei_el('note', {'type':'source-scope'}, text=acquisition['source_scope']))
    for dependency in verified['dependencies']:
        binding.append(tei_el('note', {'type':'source-credit', 'corresp': acquisition['url'] + '#' + dependency['native_id']}, text=dependency['text']))
    css_rules = []
    for style in tree.xpath('/ThML/ThML.head/style[@type="text/css"]'):
        css = style.text or ''
        rules = re.findall(r'([^{}]+)\{([^{}]*)\}', css)
        if re.sub(r'[^{}]+\{[^{}]*\}', '', css).strip():
            raise ValueError('unsupported retained stylesheet structure')
        for selector, declarations in rules:
            selector = selector.strip()
            if not re.fullmatch(r'(?:[A-Za-z][A-Za-z0-9]*)?\.[A-Za-z][A-Za-z0-9_-]*', selector):
                raise ValueError(f'unsupported retained CSS selector: {selector}')
            css_rules.append((selector, declarations))
    if css_rules:
        encoding = tei_el('encodingDesc')
        tags = tei_el('tagsDecl')
        encoding.append(tags)
        header.append(encoding)
        for i, (selector, declarations) in enumerate(css_rules, 1):
            tags.append(tei_el('rendition', {'xml:id':f'source-style-{i}', 'scheme':'css', 'selector':selector}, text=declarations))
    source_body = tree.find('ThML.body')
    unit_by_id = {unit['native_id']: unit for unit in selection['units']}
    selected_sources = {
        unit['native_id']: tree.xpath('//*[@id=$value]', value=unit['native_id'])[0]
        for unit in selection['units']
    }
    selected_roots = set(selected_sources.values())
    front = tei_el('front') if any(
        _tei_region(selected_sources[unit['native_id']], unit) == 'front'
        for unit in selection['units']
    ) else None
    envelope = []
    body_node_sequence = []
    selected_ids = set(verified['selected_native_ids'])
    dependency_ids = {dependency['native_id'] for dependency in verified['dependencies']}
    for position, node in enumerate(source_body):
        if isinstance(node.tag, str):
            native_id = node.get('id')
            contained_ids = {child.get('id') for child in node.iter() if child.get('id')}
            unit = unit_by_id.get(native_id)
            if native_id in selected_ids:
                disposition = 'selected-work'
            elif contained_ids & dependency_ids:
                disposition = 'shared-credit-context'
            else:
                disposition = 'outside-selected-work'
            carrier = {
                'position': position,
                'native_id': native_id,
                'source_tag': node.tag,
                'source_title': node.get('title'),
                'disposition': disposition,
            }
            if unit is not None:
                carrier['selection_role'] = unit['role']
                carrier['tei_region'] = _tei_region(node, unit)
            envelope.append(carrier)
            body_node_sequence.append(dict(carrier, node_kind='carrier'))
        elif isinstance(node, (etree._Comment, etree._ProcessingInstruction)):
            body_node_sequence.append(_shell_node(node, tree, 'accounted-source-body-wrapper'))
            body_node_sequence[-1]['position'] = position
        else:
            raise ValueError('unsupported non-element source node in ThML body')
    verify_complete_source_accounting(
        acquisition,
        [dict(work_id=work['work_id'], selected_native_ids=verified['selected_native_ids'])],
        [
            dict(
                native_id=row['native_id'],
                disposition='selected' if row['disposition'] == 'selected-work' else row['disposition'],
                **({'work_id': work['work_id']} if row['disposition'] == 'selected-work' else {}),
            )
            for row in envelope
        ],
        root=root_path,
    )
    document_shell = _document_shell(raw, tree, selected_roots)
    text = tei_el('text', {'xml:lang': form.get('language') or edition.get('language') or 'en'})
    root.append(text)
    if front is not None:
        text.append(front)
    body = tei_el('body')
    text.append(body)
    back = None
    rows = []
    selected_nodes = [n for unit in selection['units'] for n in selected_sources[unit['native_id']].iter() if isinstance(n.tag,str)]
    native_targets = {n.get('id'): f'#src-{i}' for i,n in enumerate(selected_nodes,1) if n.get('id')}
    responsibilities = sorted({n.get('resp') for n in selected_nodes if n.tag == 'note' and n.get('resp')})
    for i,label in enumerate(responsibilities,1):
        statement = tei_el('respStmt', {'xml:id':f'source-responsibility-{i}'})
        statement.append(tei_el('resp',text='Note responsibility label in the retained source'))
        statement.append(tei_el('name',text=label))
        header.find('.//t:titleStmt',ns).append(statement)

    def convert(source, parent):
        if not isinstance(source.tag, str):
            if not isinstance(source, etree._Comment):
                raise ValueError('unsupported source XML node')
            node = etree.Comment(source.text or '')
            node.tail = source.tail
            parent.append(node)
            return
        if source.tag not in TAGS:
            raise ValueError(f'unsupported selected ThML element: {source.tag}')
        number = len(rows) + 1
        attrs = {'xml:id': f'src-{number}'}
        for source_key, tei_key in [('n','n'),('class','rend'),('style','style'),('lang','xml:lang')]:
            if source.get(source_key):
                attrs[tei_key] = source.get(source_key)
        if source.tag in ('i','em'):
            attrs['rend'] = 'italic'
        styles = [f'#source-style-{i}' for i,(selector,_) in enumerate(css_rules,1)
                  if selector.split('.')[-1] in source.get('class','').split()
                  and (selector.startswith('.') or selector.split('.')[0] == source.tag)]
        if styles:
            attrs['rendition'] = ' '.join(styles)
        if source.tag == 'note' and source.get('place'):
            attrs['place'] = source.get('place')
        if source.tag == 'note' and source.get('resp'):
            attrs['resp'] = f"#source-responsibility-{responsibilities.index(source.get('resp'))+1}"
        if source.tag == 'note' and source.get('anchored'):
            if source.get('anchored') not in ('yes','no'):
                raise ValueError('unsupported source anchored value')
            attrs['anchored'] = 'true' if source.get('anchored') == 'yes' else 'false'
        if source.tag == 'pb' and source.get('href'):
            attrs['facs'] = source.get('href')
        if source.tag == 'scripRef' and source.get('passage'):
            attrs['cRef'] = source.get('passage')
        if source.tag == 'scripRef' and source.get('osisRef'):
            attrs['target'] = source.get('osisRef')
        if source.tag in ('name','cite') and source.get('title'):
            attrs['key'] = source.get('title')
        if source.tag == 'a' and source.get('href'):
            href = source.get('href')
            attrs['target'] = native_targets.get(href[1:], acquisition['url'] + href) if href.startswith('#') else href
        if source.tag in ('scripContext','insertIndex'):
            attrs['unit'] = source.tag
            attrs['n'] = source.get('version') or source.get('type') or source.tag
        if source.tag == 'h3':
            attrs['type'] = 'thml-h3'
        node = tei_el(TAGS[source.tag], attrs)
        node.text, node.tail = source.text, source.tail
        parent.append(node)
        rows.append({'source_path': tree.getroottree().getpath(source), 'native_id': source.get('id'),
                     'source_tag': source.tag, 'attributes': dict(source.attrib), 'tei_id': f'src-{number}'})
        direct_heading = any(child.tag in ('h1','h2','h3') and ' '.join(''.join(child.itertext()).split()).casefold() == ' '.join(source.get('title','').split()).casefold() for child in source)
        if source.tag.startswith('div') and source.get('title') and not direct_heading:
            node.append(tei_el('head', text=source.get('title')))
        for child in source:
            convert(child, node)

    for unit in selection['units']:
        source = selected_sources[unit['native_id']]
        region = _tei_region(source, unit)
        target = front if region == 'front' else body
        if region == 'back':
            if back is None:
                back = tei_el('back')
                text.append(back)
            target = back
        convert(source, target)
    context = tree.find('ThML.head')
    context_text = '\n\n'.join(
        f"### ThML.head/{node.tag}\n\n{''.join(node.itertext()).strip()}"
        for node in context if node.tag != 'style' and ''.join(node.itertext()).strip()
    )
    containing_line = f"Containing source: {containing_source['title']}\n\n" if containing_source else ''
    readme = (
        f"# {work['title']}\n\nNonaccepted per-work reconstruction.\n\n"
        f"{containing_line}Retained electronic source locator: {acquisition['url']}\n\n"
        f"{context_text}\n\n"
        "Shared source credits (verbatim; roles are source-level unless explicitly allocated):\n\n"
        + '\n\n'.join(dependency['text'] for dependency in verified['dependencies']) + '\n'
    )
    unresolved_rows = []
    try:
        profile_path = manifest.authority_path('profile')
    except (AttributeError, KeyError, ValueError):
        profile_path = None
    if profile_path is not None:
        profile = json.loads(profile_path.read_text(encoding='utf-8'))
        unresolved_rows = profile.get('candidate_questions', [])
        if not isinstance(unresolved_rows, list) or any(not isinstance(row, dict) for row in unresolved_rows):
            raise ValueError('selected ThML candidate questions must be a list of objects')
    return {'content.tei.xml': etree.tostring(root, encoding='utf-8', xml_declaration=True),
            'source-accountability.json': _json(dict(selection_sha256=verified['selection_sha256'], units=selection['units'], features=rows, source_envelope=envelope, body_node_sequence=body_node_sequence, document_shell=document_shell)),
            'provenance.json': _json(dict(work_id=work['work_id'], acquisition_id=acquisition['acquisition_id'], source_selection_sha256=verified['selection_sha256'])),
            'unresolved.jsonl': b''.join(_json(row) for row in unresolved_rows),
            'README.source.md': readme.encode('utf-8')}


_convert.converter_id = 'ocd-selected-thml-to-tei'
_convert.converter_version = '1'
