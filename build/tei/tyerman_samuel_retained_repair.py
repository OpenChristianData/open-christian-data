"""Bounded repairs to the exact retained L637 TEI component; no acquisition."""
from pathlib import Path
from hashlib import sha256
from zipfile import ZipFile
import base64, json, sys
import html5lib
from lxml import etree

ROOT = Path(__file__).resolve().parents[2]
WORK = 'tyerman-life-times-samuel-wesley-1866'
SOURCE_ID = 'gutenberg-67980'
ORIGINAL = ROOT / 'reports/_logs/tyerman-samuel-existing-install-20261004-v1/retained-original-package'
ARCHIVE_SHA = 'a745273a2a6d5bdc0b036cb2b946dc9440b58edf74e6ff24ed8e700ee6995fc7'
T = 'http://www.tei-c.org/ns/1.0'
X = '{http://www.w3.org/XML/1998/namespace}'
NS = {'t': T}
INLINE = {'a', 'span', 'i', 'em', 'b', 'strong', 'small', 'sup', 'sub', 'abbr', 'cite', 'ins'}

def enc(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()

def digest(raw):
    return sha256(raw).hexdigest()

def tagged(parent, name, **attrs):
    return etree.SubElement(parent, '{' + T + '}' + name, **attrs)

def signature(node):
    return dict(tag=node.tag if isinstance(node.tag, str) else '#comment', attributes=dict(node.attrib), text=node.text, tail=node.tail, children=[signature(c) for c in node])

def source_document(raw):
    return html5lib.parse(raw, treebuilder='etree', namespaceHTMLElements=False)

def source_fields(element, target, prefix=None):
    if element.get('id'):
        target.set(X + 'id', element.get('id'))
    if element.get('class'):
        target.set('rend', ((prefix + ' ') if prefix else '') + element.get('class'))
    if 'lang' in element.attrib:
        target.set(X + 'lang', element.get('lang'))
    if 'title' in element.attrib:
        target.set('n', element.get('title'))
    if 'style' in element.attrib:
        target.set('style', element.get('style'))

def footer_inline(source, target):
    target.text = source.text
    for child in source:
        if not isinstance(child.tag, str):
            target.append(etree.Comment(child.text or ''))
            target[-1].tail = child.tail
            continue
        if child.tag == 'br':
            out = tagged(target, 'lb')
        elif child.tag == 'a':
            out = tagged(target, 'ref', target=child.get('href')) if child.get('href') else tagged(target, 'seg', rend='source-anchor')
            source_fields(child, out, 'source-a' if child.get('href') else 'source-anchor')
            footer_inline(child, out)
        elif child.tag in INLINE:
            out = tagged(target, 'hi', rend=child.tag)
            source_fields(child, out, child.tag)
            footer_inline(child, out)
        else:
            raise ValueError('Unexpected footer inline element ' + child.tag)
        out.tail = child.tail

def footer_block(source, parent):
    if not isinstance(source.tag, str):
        parent.append(etree.Comment(source.text or '')); parent[-1].tail = source.tail; return
    tag = source.tag
    if tag in {'footer', 'div', 'header', 'blockquote'}:
        out = tagged(parent, 'div', type='source-' + tag)
        source_fields(source, out)
        if source.text is not None:
            tagged(out, 'p', rend='source-leading-text').text = source.text
        for child in source:
            slot = tagged(out, 'div', type='source-child-carrier')
            footer_block(child, slot)
    elif tag in {'ul', 'ol'}:
        out = tagged(parent, 'list', type=tag); source_fields(source, out)
        if source.text and source.text.strip(): tagged(out, 'head', rend='source-leading-text').text = source.text
        for child in source: footer_block(child, out)
    elif tag in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'pre'}:
        name = 'head' if tag.startswith('h') else {'p': 'p', 'li': 'item', 'pre': 'ab'}[tag]
        prefix = 'source-' + tag
        out = tagged(parent, name, rend=prefix); source_fields(source, out, prefix); footer_inline(source, out)
    elif tag == 'hr':
        out = tagged(parent, 'milestone', unit='source-rule'); source_fields(source, out)
    elif tag == 'br':
        out = tagged(parent, 'p', rend='source-standalone-break'); tagged(out, 'lb')
    elif tag in INLINE:
        out = tagged(parent, 'p', rend='source-standalone-inline')
        if tag == 'a':
            item = tagged(out, 'ref', target=source.get('href')) if source.get('href') else tagged(out, 'seg', rend='source-anchor')
            source_fields(source, item, 'source-a' if source.get('href') else 'source-anchor')
        else:
            item = tagged(out, 'hi', rend=tag); source_fields(source, item, tag)
        footer_inline(source, item)
    else:
        raise ValueError('Unexpected footer block element ' + tag)
    if source.tail:
        if source.tail.strip(): tagged(parent, 'p', rend='source-interstitial-text').text = source.tail
        elif len(parent): parent[-1].tail = (parent[-1].tail or '') + source.tail
        elif parent.text is None: parent.text = source.tail
        else: parent.text += source.tail

def repair(original, raw, images):
    source = source_document(raw); body = source.find('body'); head = source.find('head')
    document = etree.fromstring(original, etree.XMLParser(resolve_entities=False, no_network=True))
    text = document.find('t:text', NS)
    footer = body.find('footer')
    footer_desc = {id(n) for n in footer.iter()}
    selected = [n for n in body.iter() if isinstance(n.tag, str) and id(n) not in footer_desc]
    repairs = []
    def patch_family(nodes, actual, key):
        if len(nodes) != len(actual): raise ValueError('Retained component family differs: ' + key)
        for ordinal, (src, dst) in enumerate(zip(nodes, actual), 1):
            old = dict(dst.attrib)
            if 'class' in src.attrib:
                prefix = (dst.get('rend') or '').split()[0] if key in {'paragraph', 'heading', 'item'} or key.startswith('inline-') else ('source-anchor' if dst.tag == '{' + T + '}seg' else 'source-a') if key == 'anchor' else 'source-' + src.tag if key == 'cell' else None
                source_fields(src, dst, prefix)
            else:
                source_fields(src, dst)
            if dict(dst.attrib) != old:
                repairs.append(dict(family=key, ordinal=ordinal, before=old, after=dict(dst.attrib)))
    families = [
        ('paragraph', [n for n in selected if n.tag == 'p'], [n for n in text.iter('{' + T + '}p') if (n.get('rend') or '').split()[:1] == ['source-p']]),
        ('heading', [n for n in selected if n.tag in {'h1','h2','h3','h4','h5','h6'}], text.xpath('.//t:head[starts-with(@rend,"source-h")]', namespaces=NS)),
        ('anchor', [n for n in selected if n.tag == 'a' and not any(n is c for s in selected if s.tag == 'span' and 'pagenum' in s.get('class','').split() for c in s.iter())], text.xpath('.//t:ref|.//t:seg[@rend="source-anchor"]', namespaces=NS)),
        ('cell', [n for n in selected if n.tag in {'td','th'}], text.xpath('.//t:cell', namespaces=NS)),
        ('table', [n for n in selected if n.tag == 'table'], text.xpath('.//t:table', namespaces=NS)),
        ('list', [n for n in selected if n.tag in {'ul','ol'}], text.xpath('.//t:list', namespaces=NS)),
        ('item', [n for n in selected if n.tag == 'li'], text.xpath('.//t:item', namespaces=NS)),
        ('column', [n for n in selected if n.tag == 'col'], text.xpath('.//t:milestone[@unit="source-column"]', namespaces=NS)),
    ]
    for family, nodes, actual in families: patch_family(nodes, actual, family)
    for tag in sorted(INLINE - {'a'}):
        nodes = [n for n in selected if n.tag == tag and not (tag == 'span' and 'pagenum' in n.get('class','').split())]
        actual = [n for n in text.iter('{' + T + '}hi') if (n.get('rend') or '').split()[:1] == [tag]]
        patch_family(nodes, actual, 'inline-' + tag)
    header = text.find('.//t:div[@type="source-header"]', NS)
    if body.find('header').get('lang'):
        before = dict(header.attrib); header.set(X + 'lang', body.find('header').get('lang'))
        if before != dict(header.attrib): repairs.append(dict(family='provider-header', ordinal=1, before=before, after=dict(header.attrib)))
    image_nodes = [n for n in selected if n.tag == 'img']
    graphics = list(text.iter('{' + T + '}graphic'))
    if len(image_nodes) != 2 or len(graphics) != 2: raise ValueError('Two exact retained images required')
    for src, dst in zip(image_nodes, graphics):
        before = dict(dst.attrib); target = src.get('src')
        if dst.get('url') != target: raise ValueError('Retained literal image target differs')
        dst.set('url', 'data:image/jpeg;base64,' + base64.b64encode(images[target]).decode())
        context = 'urn:ocd:retained-archive:' + ARCHIVE_SHA + ':member:' + target
        dst.set('corresp', context)
        dst.set('n', src.get('alt')); source_fields(src, dst)
        repairs.append(dict(family='image', before=before, after=dict(dst.attrib), source_context=context, payload_sha256=digest(images[target])))
    back = text.find('t:back/t:div[@type="source-provider-footer"]', NS)
    old_footer = etree.tostring(back[0])
    back.remove(back[0]); footer_block(footer, back)
    if body.text is not None or any(not isinstance(n.tag, str) for n in body):
        raise ValueError('Unexpected body leading text or comment needs an explicit disposition')
    if len(source) != 3 or source[0].tag != 'head' or source[1].tag != 'body' or isinstance(source[2].tag, str):
        raise ValueError('Exact root administration comment location differs')
    filedesc = document.find('t:teiHeader/t:fileDesc', NS)
    title_stmt = filedesc.find('t:titleStmt', NS)
    author = next(''.join(p.itertext()).strip().split(':',1)[1].strip() for p in body.find('header').iter('p') if ''.join(p.itertext()).strip().startswith('Author:'))
    tagged(title_stmt, 'author').text = author
    desc = filedesc.find('t:sourceDesc', NS)
    tagged(desc, 'p', n='source-boundary').text = 'One complete Samuel Wesley biography, including twenty chapters, appendices A-C, name index, 361 footnotes, transcriber notes, and provider wrapper. The unrelated John Wesley and Whitefield books are excluded.'
    tagged(desc, 'p', n='source-title-discrepancy').text = 'The literal HTML title names John and Charles Wesley; the retained book title and provider author identify L. Tyerman. The literal conflicting field is preserved below.'
    prefix = raw.decode('utf-8').split('<html',1)[0]
    p = tagged(desc, 'p', n='source-html-prolog'); tagged(p, 'seg', type='source-literal').text = prefix
    suffix = raw.decode('utf-8').rsplit('</body>', 1)[1]
    p = tagged(desc, 'p', n='source-html-document-suffix'); tagged(p, 'seg', type='source-literal').text = suffix
    for label, element in [('root', source), ('head', head), ('body', body), ('root-child-3-administration-comment', source[2])]:
        p = tagged(desc, 'p', n='source-' + label + '-fields')
        for role, value in [('tag', element.tag if isinstance(element.tag, str) else '#comment'), ('attributes', json.dumps(dict(element.attrib), ensure_ascii=False, sort_keys=True, separators=(',', ':'))), ('text', element.text), ('tail', element.tail)]:
            seg = tagged(p, 'seg', type='source-' + role, n='present' if value is not None else 'absent'); seg.text = value
    for ordinal, element in enumerate(head, 1):
        p = tagged(desc, 'p', n='source-head-' + str(ordinal))
        for role, value in [('tag',element.tag),('attributes',json.dumps(dict(element.attrib),ensure_ascii=False,sort_keys=True,separators=(',',':'))),('text',element.text),('tail',element.tail)]:
            seg = tagged(p, 'seg', type='source-' + role, n='present' if value is not None else 'absent')
            seg.text = value
    return etree.tostring(document, encoding='UTF-8', xml_declaration=True), repairs, old_footer

def guard(manifest):
    configuration = json.loads(manifest.authority_path('runtime').read_bytes())
    from ocd_kernel.lib.path_io import resolve_path
    if configuration.get('contract') != 'ocd-l637-actual-runtime-closure-v1': raise ValueError('Exact runtime closure contract required')
    executable = resolve_path(Path(sys.executable), strict=True)
    if configuration['runtime_executable'] != dict(path=executable.as_posix(), bytes=executable.stat().st_size, sha256=digest(executable.read_bytes())): raise ValueError('Executed Python runtime differs')
    physical = resolve_path(ROOT, strict=True); library = resolve_path(Path('D:/Library/Open Christian Data'), strict=True)
    allowed = {resolve_path(ROOT / row['path'], strict=True): row['sha256'] for row in configuration['first_party_files']}
    external = {resolve_path(Path(row['path']),strict=True): row['sha256'] for row in configuration['external_runtime_files']}
    observed = []
    for name, module in sys.modules.copy().items():
        filename = getattr(module, '__file__', None)
        if not filename: continue
        p = resolve_path(Path(filename), strict=True)
        mapping = allowed if p.is_relative_to(physical) or p.is_relative_to(library) else external
        if p not in mapping or digest(p.read_bytes()) != mapping[p]: raise ValueError('Unexpected or changed executed producer dependency: ' + p.as_posix())
        observed.append(p.as_posix())
    return sorted(set(observed))

def _convert(manifest):
    if manifest.record['work_id'] != WORK or manifest.record['source_id'] != SOURCE_ID: raise ValueError('Exact Samuel Wesley source identity required')
    guard(manifest)
    with ZipFile(manifest.authority_path('retained-archive')) as archive:
        raw = archive.read('pg67980-images.html'); images = {name:archive.read(name) for name in ('images/cover.jpg','images/i_004.jpg')}
    original = manifest.authority_path('original-tei').read_bytes()
    xml, changes, footer = repair(original, raw, images)
    policy = json.loads(manifest.authority_path('policy').read_bytes())
    account = dict(contract='ocd-l637-retained-repair-accounting-v1', work_id=WORK, source_id=SOURCE_ID, source_manifest_sha256=manifest.sha256, original_tei_sha256=digest(original), repaired_tei_sha256=digest(xml), changed_attribute_families=changes, replaced_footer_sha256=digest(footer), profile_sha256=digest(manifest.authority_path('profile').read_bytes()), policy_sha256=digest(manifest.authority_path('policy').read_bytes()), producer_sha256=digest(Path(__file__).read_bytes()), original_package_manifest_sha256=digest(manifest.authority_path('original-package-manifest').read_bytes()))
    provenance = dict(policy['provenance']); provenance['source_manifest_sha256'] = manifest.sha256
    guard(manifest)
    return {'content.tei.xml':xml,'source-accountability.json':enc(account),'provenance.json':enc(provenance),'README.source.md':manifest.authority_path('readme').read_bytes(),'unresolved.jsonl':b''.join(enc(row) for row in policy['unresolved'])}

_convert.converter_id = 'ocd-l637-retained-component-bounded-repair'
_convert.converter_version = '1'
