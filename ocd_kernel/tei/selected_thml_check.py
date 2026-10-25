"""Independent retained-source comparison for the bounded ThML route.

This checker parses the retained member and candidate itself. It deliberately
does not import the converter, source-selection traversal, or producer
accounting helpers. Shared assumptions are the XML parser, validated sidecar
schemas, and TEI P5 vocabulary.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError

NS = {'t': 'http://www.tei-c.org/ns/1.0'}
TEI_NS = 'http://www.tei-c.org/ns/1.0'
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'
XML_LANG = '{http://www.w3.org/XML/1998/namespace}lang'
AUGUSTINE_DOCTRINE_ROUTE = (
    'augustine-on-christian-doctrine',
    'augustine-on-christian-doctrine-retained',
    'raw/ccel/npnf1/npnf102.xml',
    'b8ca21dfa7d553681651f85197064b0fe52ae6c17e5e17252df9301536a4ae2a',
)


def _selection_digest(selection: dict) -> str:
    canonical = json.dumps(
        selection, ensure_ascii=False, sort_keys=True, separators=(',', ':')
    ).encode('utf-8') + b'\n'
    return hashlib.sha256(canonical).hexdigest()


def _shell_node(node, tree, disposition: str) -> dict:
    if isinstance(node, etree._Comment):
        kind = 'comment'
    elif isinstance(node, etree._ProcessingInstruction):
        kind = 'processing-instruction'
    else:
        raise PipelineError(f'unsupported source document-shell node: {type(node).__name__}')
    record = {
        'kind': kind,
        'path': tree.getroottree().getpath(node) if node.getparent() is not None else None,
        'text': node.text or '',
        'tail': node.tail or '',
        'disposition': disposition,
    }
    if kind == 'processing-instruction':
        record['target'] = node.target
    return record


def _document_shell(raw: bytes, tree, selected_roots: set) -> dict:
    root = tree.getroottree().getroot()
    prolog_nodes = []
    node = root.getprevious()
    while node is not None:
        prolog_nodes.append(node)
        node = node.getprevious()
    prolog_nodes.reverse()
    epilog_nodes = []
    node = root.getnext()
    while node is not None:
        epilog_nodes.append(node)
        node = node.getnext()

    def in_selected_unit(comment) -> bool:
        parent = comment.getparent()
        while parent is not None:
            if parent in selected_roots:
                return True
            parent = parent.getparent()
        return False

    declaration = None
    if raw.startswith(b'<?xml') and b'?>' in raw:
        declaration = raw.split(b'?>', 1)[0].decode('ascii') + '?>'
    comments_and_pis = []
    for node in tree.iter():
        if isinstance(node, (etree._Comment, etree._ProcessingInstruction)):
            disposition = (
                'preserved-in-tei'
                if in_selected_unit(node)
                else 'accounted-outside-selected-content'
            )
            comments_and_pis.append(_shell_node(node, tree, disposition))

    head = tree.find('ThML.head')
    head_children = []
    if head is not None:
        for position, child in enumerate(head):
            if not isinstance(child.tag, str):
                raise PipelineError('unsupported non-element node in ThML head')
            content = ''.join(child.itertext()).strip()
            if child.tag == 'style' and child.get('type') == 'text/css':
                disposition = 'represented-in-tei-encodingDesc'
            elif child.tag == 'style' and not content:
                disposition = 'accounted-empty-source-stylesheet'
            else:
                disposition = 'reproduced-in-source-readme'
            head_children.append({
                'position': position,
                'tag': child.tag,
                'attributes': dict(child.attrib),
                'text': content,
                'disposition': disposition,
            })

    return {
        'xml_declaration': declaration,
        'doctype': tree.getroottree().docinfo.doctype or None,
        'root_name': etree.QName(root).localname,
        'prolog': [
            _shell_node(item, tree, 'accounted-source-document-shell')
            for item in prolog_nodes
        ],
        'epilog': [
            _shell_node(item, tree, 'accounted-source-document-shell')
            for item in epilog_nodes
        ],
        'comments_and_processing_instructions': comments_and_pis,
        'head_children': head_children,
    }


def _tei_region(source, role: str) -> str:
    if source.tag == 'div1' and source.get('title') == 'Title Page':
        if role != 'body':
            raise PipelineError('a source title page must have the acquisition body role')
        return 'front'
    return role


def _source_scope(source_body, acquisition: dict, work: dict, member: dict, tree):
    selection = acquisition.get('source_selection')
    if not isinstance(selection, dict):
        raise PipelineError('selected ThML checker requires a source selection')
    if selection.get('work_id') != work.get('work_id'):
        raise PipelineError('source selection work identity differs')
    if selection.get('member_path') != member['path']:
        raise PipelineError('source selection member differs from retained member')
    units = selection.get('units')
    dependencies = selection.get('dependencies')
    if not isinstance(units, list) or not units or not isinstance(dependencies, list):
        raise PipelineError('source selection units or dependencies are invalid')
    unit_ids = [unit.get('native_id') for unit in units if isinstance(unit, dict)]
    if len(unit_ids) != len(units) or any(not isinstance(value, str) or not value for value in unit_ids):
        raise PipelineError('source selection unit identity is invalid')
    if len(set(unit_ids)) != len(unit_ids):
        raise PipelineError('source selection contains duplicate units')
    roles = [unit.get('role') for unit in units]
    if not roles or roles[0] != 'body' or any(role not in {'body', 'back'} for role in roles):
        raise PipelineError('source selection requires one or more leading body units')
    first_back = roles.index('back') if 'back' in roles else len(roles)
    if any(role == 'body' for role in roles[first_back:]):
        raise PipelineError('source selection body units cannot follow back units')

    source_by_id: dict[str, list] = {}
    for node in tree.iter():
        if isinstance(node.tag, str) and node.get('id'):
            source_by_id.setdefault(node.get('id'), []).append(node)
    selected = []
    for unit in units:
        matches = source_by_id.get(unit['native_id'], [])
        if len(matches) != 1:
            raise PipelineError(f"source selection native ID is missing or ambiguous: {unit['native_id']}")
        node = matches[0]
        if node.getparent() is not source_body or node.tag != 'div1':
            raise PipelineError(f"source selection unit is not a top-level div1: {unit['native_id']}")
        if node.get('title') != unit.get('title'):
            raise PipelineError(f"source selection title differs for {unit['native_id']}")
        reference = f"{member['path']}#{unit['native_id']}"
        if reference not in work.get('evidence', []):
            raise PipelineError(f"selected unit lacks work evidence: {reference}")
        selected.append(node)
    if selected != sorted(selected, key=source_body.index):
        raise PipelineError('source selection order differs from retained source')
    selected_source_ids = [
        node.get('id') for unit in selected for node in unit.iter()
        if isinstance(node.tag, str) and node.get('id')
    ]
    if len(selected_source_ids) != len(set(selected_source_ids)):
        raise PipelineError('selected source subtrees contain duplicate native IDs')

    editions = [
        edition
        for form in work.get('textual_forms', [])
        if isinstance(form, dict)
        for edition in form.get('editions', [])
        if isinstance(edition, dict) and edition.get('edition_id') == acquisition.get('edition_id')
    ]
    if len(editions) != 1:
        raise PipelineError('selected acquisition does not identify exactly one work edition')
    containing_source = editions[0].get('containing_source')
    source_titles = tree.xpath('/ThML/ThML.head//DC.Title[not(@sub)]/text()')
    if containing_source is not None:
        if (
            source_titles != [containing_source.get('title')]
            or containing_source.get('locator') != member['path']
        ):
            raise PipelineError('selected source title or locator differs from containing-source authority')
    elif source_titles:
        if source_titles != [work.get('title')]:
            raise PipelineError('retained source title differs from work declaration')
    elif units[0].get('title') != work.get('title'):
        raise PipelineError('retained source work title differs from work declaration')

    prefix = member['path'] + '#'
    declared_ids = {
        item[len(prefix):]
        for item in work.get('evidence', [])
        if isinstance(item, str) and item.startswith(prefix)
    }
    dependency_ids = []
    dependency_text = []
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            raise PipelineError('source selection dependency is invalid')
        native_id = dependency.get('native_id')
        if not isinstance(native_id, str) or not native_id:
            raise PipelineError('source selection dependency identity is invalid')
        matches = source_by_id.get(native_id, [])
        if len(matches) != 1:
            raise PipelineError(f'source dependency native ID is missing or ambiguous: {native_id}')
        node = matches[0]
        if any(node is unit or unit in node.iterancestors() for unit in selected):
            raise PipelineError(f'source dependency duplicates selected content: {native_id}')
        content = ''.join(node.itertext())
        digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
        if digest != dependency.get('text_sha256'):
            raise PipelineError(f'source dependency text binding differs: {native_id}')
        dependency_ids.append(native_id)
        dependency_text.append(dict(native_id=native_id, text=content))
    if len(dependency_ids) != len(set(dependency_ids)):
        raise PipelineError('source selection contains duplicate dependencies')
    if declared_ids != set(unit_ids) | set(dependency_ids):
        raise PipelineError('selected units and dependencies differ from work evidence')
    return editions[0], selected, source_by_id, dependency_text


def _source_envelope(source_body, units: list, dependencies: list, tree):
    by_id = {unit['native_id']: unit for unit in units}
    dependency_ids = {dependency['native_id'] for dependency in dependencies}
    envelope = []
    body_sequence = []
    for position, node in enumerate(source_body):
        if isinstance(node.tag, str):
            native_id = node.get('id')
            if not native_id:
                raise PipelineError('top-level ThML carrier has no native ID')
            unit = by_id.get(native_id)
            descendants = {
                child.get('id') for child in node.iter()
                if isinstance(child.tag, str) and child.get('id')
            }
            if unit is not None:
                disposition = 'selected-work'
            elif descendants & dependency_ids:
                disposition = 'shared-credit-context'
            else:
                disposition = 'outside-selected-work'
            row = {
                'position': position,
                'native_id': native_id,
                'source_tag': node.tag,
                'source_title': node.get('title'),
                'disposition': disposition,
            }
            if unit is not None:
                row['selection_role'] = unit['role']
                row['tei_region'] = _tei_region(node, unit['role'])
            envelope.append(row)
            body_sequence.append(dict(row, node_kind='carrier'))
        elif isinstance(node, (etree._Comment, etree._ProcessingInstruction)):
            item = _shell_node(node, tree, 'accounted-source-body-wrapper')
            item['position'] = position
            body_sequence.append(item)
        else:
            raise PipelineError('unsupported non-element node in retained ThML body')
    ids = [row['native_id'] for row in envelope]
    if len(ids) != len(set(ids)):
        raise PipelineError('retained ThML body contains duplicate carrier IDs')
    return envelope, body_sequence


def _stylesheet(source, tei):
    rules = []
    for style in source.xpath('/ThML/ThML.head/style[@type="text/css"]'):
        css = style.text or ''
        for fragment in css.split('}'):
            if not fragment.strip():
                continue
            if '{' not in fragment:
                raise PipelineError('retained ThML stylesheet syntax is unsupported')
            selector, declarations = fragment.split('{', 1)
            rules.append((selector.strip(), declarations))
    for style in source.xpath('/ThML/ThML.head/style[not(@type="text/css")]'):
        if ''.join(style.itertext()).strip():
            raise PipelineError('retained non-CSS ThML stylesheet is unsupported')
    renditions = tei.xpath(
        '/t:TEI/t:teiHeader/t:encodingDesc/t:tagsDecl/t:rendition', namespaces=NS
    )
    observed = [
        (item.get('selector'), item.text, item.get(XML_ID), item.get('scheme'))
        for item in renditions
    ]
    expected = [
        (selector, declarations, f'source-style-{index}', 'css')
        for index, (selector, declarations) in enumerate(rules, 1)
    ]
    if observed != expected:
        raise PipelineError('selected ThML source stylesheet differs')
    return rules


def _expected_attributes(source, number: int, css_rules: list, targets: dict, responsibilities: list,
                         acquisition: dict, *, augustine_doctrine: bool = False) -> dict[str, str]:
    attrs = {XML_ID: f'src-{number}'}
    for source_key, tei_key in [('n', 'n'), ('class', 'rend'), ('style', 'style'), ('lang', XML_LANG)]:
        if source.get(source_key):
            attrs[tei_key] = source.get(source_key)
    if source.tag in ('i', 'em'):
        attrs['rend'] = 'italic'
    rendition_refs = [
        f'#source-style-{index}'
        for index, (selector, _declarations) in enumerate(css_rules, 1)
        if selector.split('.')[-1] in source.get('class', '').split()
        and (selector.startswith('.') or selector.split('.')[0] == source.tag)
    ]
    if rendition_refs:
        attrs['rendition'] = ' '.join(rendition_refs)
    if augustine_doctrine and source.tag.startswith('div'):
        if source.get('type'):
            attrs['type'] = source.get('type')
        for relation in ('prev', 'next'):
            native_id = source.get(relation)
            if native_id:
                attrs[relation] = targets.get(native_id, f"{acquisition['url']}#{native_id}")
    if source.tag == 'note' and source.get('place'):
        attrs['place'] = source.get('place')
    if source.tag == 'note' and source.get('resp'):
        attrs['resp'] = f"#source-responsibility-{responsibilities.index(source.get('resp')) + 1}"
    if source.tag == 'note' and source.get('anchored'):
        if source.get('anchored') not in ('yes', 'no'):
            raise PipelineError('retained note anchoring value is unsupported')
        attrs['anchored'] = 'true' if source.get('anchored') == 'yes' else 'false'
    if source.tag == 'pb' and source.get('href'):
        attrs['facs'] = source.get('href')
    if source.tag == 'scripRef' and source.get('passage'):
        attrs['cRef'] = source.get('passage')
    if source.tag == 'scripRef' and source.get('osisRef'):
        attrs['target'] = source.get('osisRef')
    if augustine_doctrine and source.tag == 'scripRef' and source.get('version'):
        attrs['source'] = source.get('version')
    if source.tag in ('name', 'cite') and source.get('title'):
        attrs['key'] = source.get('title')
    if source.tag == 'a' and source.get('href'):
        href = source.get('href')
        attrs['target'] = targets.get(href[1:], acquisition['url'] + href) if href.startswith('#') else href
    if source.tag in ('scripContext', 'insertIndex'):
        attrs['unit'] = source.tag
        attrs['n'] = source.get('version') or source.get('type') or source.tag
    if source.tag == 'h3':
        attrs['type'] = 'thml-h3'
    return attrs


def check_selected_thml(root: Path, acquisition: dict, work: dict, candidate: Path) -> dict:
    """Re-read the complete retained member and compare every selected node."""
    selection = acquisition.get('source_selection')
    if not isinstance(selection, dict):
        raise PipelineError('selected ThML checker requires a source selection')
    member_path = selection.get('member_path')
    members = [item for item in acquisition.get('retained_files', []) if item.get('path') == member_path]
    if len(members) != 1 or len(acquisition.get('retained_files', [])) != 1:
        raise PipelineError('selected ThML checker requires exactly one declared retained member')
    member = members[0]
    if acquisition.get('source_path') is not None and any(
        acquisition.get(key) != member[field]
        for key, field in [('source_path', 'path'), ('source_bytes', 'bytes'), ('source_sha256', 'sha256')]
    ):
        raise PipelineError('selected ThML original-source binding differs from retained member')
    source_path = resolve_repo_path(root, member_path)
    raw = source_path.read_bytes()
    source_sha256 = hashlib.sha256(raw).hexdigest()
    if len(raw) != member.get('bytes') or source_sha256 != member.get('sha256'):
        raise PipelineError('selected ThML retained member byte or hash binding differs')
    augustine_doctrine = (
        work.get('work_id'), acquisition.get('acquisition_id'), member_path, source_sha256
    ) == AUGUSTINE_DOCTRINE_ROUTE
    try:
        parser = etree.XMLParser(
            resolve_entities=False, no_network=True, recover=False,
            remove_comments=False, remove_pis=False,
        )
        source_root = etree.fromstring(raw, parser)
        source = source_root.getroottree()
        tei = etree.parse(
            str(candidate),
            etree.XMLParser(
                resolve_entities=False, no_network=True, recover=False,
                remove_comments=False, remove_pis=False,
            ),
        )
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(f'selected ThML source or candidate XML is invalid: {exc}') from exc
    if source_root.tag != 'ThML' or any(isinstance(node, etree._Entity) for node in source_root.iter()):
        raise PipelineError('selected ThML checker requires a resolved ThML source tree')
    heads = source_root.findall('ThML.head')
    bodies = source_root.findall('ThML.body')
    if len(heads) != 1 or len(bodies) != 1:
        raise PipelineError('selected ThML source requires exactly one head and body')
    source_body = bodies[0]

    edition, selected, source_by_id, dependency_text = _source_scope(
        source_body, acquisition, work, member, source_root
    )
    selection_sha256 = _selection_digest(selection)
    digest = tei.xpath(
        '/t:TEI/t:teiHeader//t:idno[@type="source_selection_sha256"]/text()', namespaces=NS
    )
    if digest != [selection_sha256]:
        raise PipelineError('candidate selection binding differs from acquisition')
    form_matches = [
        form for form in work.get('textual_forms', [])
        if any(item.get('edition_id') == acquisition.get('edition_id') for item in form.get('editions', []))
    ]
    if len(form_matches) != 1:
        raise PipelineError('candidate acquisition does not resolve to one textual form')
    form = form_matches[0]
    identity_values = {
        'work_id': work['work_id'],
        'textual_form_id': form['textual_form_id'],
        'edition_id': acquisition['edition_id'],
        'acquisition_id': acquisition['acquisition_id'],
        'source_sha256': source_sha256,
        'source_bytes': str(len(raw)),
        'source_selection_sha256': selection_sha256,
    }
    if tei.getroot().tag != f'{{{TEI_NS}}}TEI' or tei.getroot().get(XML_ID) != work['work_id']:
        raise PipelineError('candidate TEI root identity differs')
    for key, value in identity_values.items():
        observed = tei.xpath(
            '/t:TEI/t:teiHeader//t:idno[@type=$kind]/text()',
            kind=key, namespaces=NS,
        )
        if observed != [value]:
            raise PipelineError(f'candidate selected work identity differs: {key}')
    if tei.xpath('/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title/text()', namespaces=NS) != [work['title']]:
        raise PipelineError('candidate title differs from work declaration')
    authors = '; '.join(
        creator['name'] for creator in work.get('creators', [])
        if creator.get('role') == 'author'
    )
    if tei.xpath('/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:author/text()', namespaces=NS) != [authors]:
        raise PipelineError('candidate author differs from work declaration')
    source_ptrs = tei.xpath('/t:TEI/t:teiHeader/t:fileDesc/t:sourceDesc//t:ptr/@target', namespaces=NS)
    if source_ptrs != [acquisition['url']]:
        raise PipelineError('candidate source locator differs from acquisition authority')
    source_desc = tei.xpath('/t:TEI/t:teiHeader/t:fileDesc/t:sourceDesc//t:bibl', namespaces=NS)
    if len(source_desc) != 1:
        raise PipelineError('candidate source bibliography is missing or duplicated')
    containing_source = edition.get('containing_source')
    print_sources = tei.xpath(
        '/t:TEI/t:teiHeader/t:fileDesc/t:sourceDesc//t:note[@type="print-source"]/text()',
        namespaces=NS,
    )
    expected_print_sources = [containing_source['title']] if containing_source else []
    if print_sources != expected_print_sources:
        raise PipelineError('candidate contains an unsupported or changed print-source assertion')
    expected_language = form.get('language') or edition.get('language')
    text_nodes = tei.xpath('/t:TEI/t:text', namespaces=NS)
    if len(text_nodes) != 1 or (expected_language and text_nodes[0].get(XML_LANG) != expected_language):
        raise PipelineError('candidate textual-form language differs')
    if tei.xpath('/t:TEI/t:teiHeader//t:note[@type="source-location"]/text()', namespaces=NS) != [member_path]:
        raise PipelineError('candidate source location differs')
    if tei.xpath('/t:TEI/t:teiHeader//t:note[@type="source-scope"]/text()', namespaces=NS) != [acquisition['source_scope']]:
        raise PipelineError('candidate source scope differs')

    expected_front = any(
        _tei_region(node, unit['role']) == 'front'
        for unit, node in zip(selection['units'], selected)
    )
    expected_back = any(unit['role'] == 'back' for unit in selection['units'])
    text_children = [child for child in text_nodes[0] if isinstance(child.tag, str)]
    expected_regions = (['front'] if expected_front else []) + ['body'] + (['back'] if expected_back else [])
    if [etree.QName(child).localname for child in text_children] != expected_regions:
        raise PipelineError('candidate front/body/back region structure differs')
    region_containers = {
        etree.QName(child).localname: child for child in text_children
    }
    actual_units = []
    for region in expected_regions:
        container = region_containers[region]
        if any(not isinstance(child.tag, str) for child in container):
            raise PipelineError('candidate has an unaccounted direct comment or instruction in a text region')
        actual_units.extend((region, child) for child in container)
    if len(selected) != len(actual_units):
        raise PipelineError('selected ThML unit count differs')

    selected_elements = [
        node for unit_root in selected for node in unit_root.iter()
        if isinstance(node.tag, str)
    ]
    native_targets = {
        node.get('id'): f'#src-{number}'
        for number, node in enumerate(selected_elements, 1) if node.get('id')
    }
    responsibilities = sorted({
        node.get('resp') for node in selected_elements
        if node.tag == 'note' and node.get('resp')
    })
    responsibility_rows = tei.xpath(
        '/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:respStmt', namespaces=NS
    )
    observed_responsibilities = [
        (row.get(XML_ID), row.findtext(f'{{{TEI_NS}}}name'))
        for row in responsibility_rows if row.get(XML_ID, '').startswith('source-responsibility-')
    ]
    expected_responsibilities = [
        (f'source-responsibility-{index}', label)
        for index, label in enumerate(responsibilities, 1)
    ]
    if observed_responsibilities != expected_responsibilities:
        raise PipelineError('selected ThML source responsibility labels differ')
    css_rules = _stylesheet(source_root, tei)

    tag_map = {
        'div1': 'div', 'div2': 'div', 'div3': 'div', 'div': 'div', 'p': 'p',
        'h1': 'head', 'h2': 'head', 'h3': 'head', 'span': 'seg', 'i': 'hi', 'em': 'hi',
        'note': 'note', 'pb': 'pb', 'scripRef': 'ref', 'name': 'name', 'cite': 'title',
        'a': 'ref', 'ul': 'list', 'li': 'item', 'scripContext': 'milestone',
        'insertIndex': 'milestone',
    }
    if augustine_doctrine:
        tag_map['br'] = 'lb'
    checked = 0
    features = []

    def compare(original, reconstructed):
        nonlocal checked
        if isinstance(original, etree._Comment):
            if (
                not isinstance(reconstructed, etree._Comment)
                or original.text != reconstructed.text
                or original.tail != reconstructed.tail
            ):
                raise PipelineError('selected ThML comment attachment differs')
            return
        if not isinstance(original.tag, str) or original.tag not in tag_map:
            raise PipelineError(f'selected ThML source node is unsupported: {original.tag}')
        expected_tag = f'{{{TEI_NS}}}{tag_map[original.tag]}'
        if reconstructed.tag != expected_tag:
            raise PipelineError(f'selected ThML element differs: {original.tag}')
        checked += 1
        if reconstructed.get(XML_ID) != f'src-{checked}':
            raise PipelineError('selected ThML source node order differs')
        if original.text != reconstructed.text or original.tail != reconstructed.tail:
            raise PipelineError(f'selected ThML text or tail differs: {original.get("id")}')
        expected_attrs = _expected_attributes(
            original, checked, css_rules, native_targets, responsibilities, acquisition,
            augustine_doctrine=augustine_doctrine,
        )
        if dict(reconstructed.attrib) != expected_attrs:
            raise PipelineError(f'selected ThML attribute mapping differs: {original.tag}/{original.get("id")}')
        features.append({
            'source_path': source.getpath(original),
            'native_id': original.get('id'),
            'source_tag': original.tag,
            'attributes': dict(original.attrib),
            'tei_id': f'src-{checked}',
        })
        children = list(reconstructed)
        title_matches_heading = any(
            child.tag in ('h1', 'h2', 'h3')
            and ' '.join(''.join(child.itertext()).split()).casefold()
            == ' '.join((original.get('title') or '').split()).casefold()
            for child in original if isinstance(child.tag, str)
        )
        if (not augustine_doctrine and original.tag.startswith('div')
                and original.get('title') and not title_matches_heading):
            if (
                not children
                or children[0].tag != f'{{{TEI_NS}}}head'
                or children[0].text != original.get('title')
                or children[0].get('type') is not None
            ):
                raise PipelineError('selected ThML source division title differs')
            children = children[1:]
        if len(original) != len(children):
            raise PipelineError('selected ThML hierarchy or attachment differs')
        for left, right in zip(original, children):
            compare(left, right)

    for (unit, original), (actual_region, reconstructed) in zip(
        zip(selection['units'], selected), actual_units
    ):
        expected_region = _tei_region(original, unit['role'])
        if actual_region != expected_region:
            raise PipelineError('selected ThML front/body/back placement differs')
        compare(original, reconstructed)
    if checked != len(selected_elements):
        raise PipelineError('selected ThML candidate feature count differs')

    credits = tei.xpath(
        '/t:TEI/t:teiHeader/t:fileDesc/t:sourceDesc//t:note[@type="source-credit"]',
        namespaces=NS,
    )
    expected_credits = [
        (acquisition['url'] + '#' + item['native_id'], item['text'])
        for item in dependency_text
    ]
    if [(item.get('corresp'), ''.join(item.itertext())) for item in credits] != expected_credits:
        raise PipelineError('selected ThML shared source credit is missing or changed')

    envelope, body_sequence = _source_envelope(
        source_body, selection['units'], dependency_text, source_root
    )
    shell = _document_shell(raw, source_root, set(selected))
    return {
        'status': 'pass',
        'checked_elements': checked,
        'selection_sha256': selection_sha256,
        'bytes_parsed': len(raw),
        'source_sha256': source_sha256,
        'selected_native_ids': [unit['native_id'] for unit in selection['units']],
        'features': features,
        'source_envelope': envelope,
        'body_node_sequence': body_sequence,
        'document_shell': shell,
        'carrier_count': len(envelope),
        'source_comment_count': sum(1 for node in source_root.iter() if isinstance(node, etree._Comment)),
        'selected_comment_count': sum(
            1 for unit_root in selected for node in unit_root.iter()
            if isinstance(node, etree._Comment)
        ),
    }
