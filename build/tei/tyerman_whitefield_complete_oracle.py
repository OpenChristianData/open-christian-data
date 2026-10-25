"""Independent actual-object inverse for the one L635 two-volume biography.

Prior exposure: historical producer/oracle and their limitations were read.
Expected source trees come from raw HTML; no producer selection or mapping is
imported. A separately configured libxml HTML parser corroborates all fields
except three explicitly bound document-boundary whitespace fields per source.
"""
from __future__ import annotations

import base64
from collections import Counter
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote, unquote
from zipfile import ZipFile

import html5lib
from lxml import etree, html
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.contract import _canonical, _runtime_binding, _validation_authority_bindings
from build.tei.tyerman_whitefield_runtime import guard

ROOT = Path(__file__).resolve().parents[2]
N = "{http://www.tei-c.org/ns/1.0}"
X = "{http://www.w3.org/XML/1998/namespace}"
PREFIX = "urn:ocd:l635:source:"
WORK = "tyerman-life-george-whitefield"
TITLE = "The Life of the Rev. George Whitefield, B.A."
SCOPE = "One complete authored Tyerman biography: both full already retained electronic volumes I (1876, PG44280) and II (1877, PG62023), with provider matter, advertisement, narrative, notes, tables, index, transcriber notices, source head/prolog and every archive member. No Whitefield sermon/collected-work or other Tyerman source acquisition."
ORACLE_ID = "ocd-l635-independent-complete-biography-source-inverse"
DATA = {
    "44280": ("e20db686be152c089ebbaae0cd41c7bcc92c42953bc5d4d7f3a2a12075bcf8bf", "8b1f346c952efe26f71c259fd08ebcbe38097a03eeeeae41d8f3c0cf556e0aca", "40800187045cd202e10d57f675be53353db9bd7fe6bdd3584c208d91dda4fa04", "1d8e7bf69e0a20674a6251ecc88a06d915ce7f51d7d1b356e188fa7ea43c0ca2"),
    "62023": ("9f420e133c7d5f0ee2a1c6c09093039016609f22be8903f325efc42e8770a5e6", "24a3a6825397c9e4c9fb061bdbb865bb5cc6be455501ccc2c784a21efd0febfa", "8050e7d28bf241ad3cfe7c04fa4f6309813d1111900c1a17ccf966aaee88cc91", "01f98331c197a62c1d149a92f5791a87adf693fc3ddac549d082b51300af88bc"),
}
IMPORTS = {
    "oracle": tuple("build/__init__.py build/tei/__init__.py build/tei/tyerman_whitefield_complete_oracle.py build/tei/tyerman_whitefield_runtime.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py".split()),
    "producer": tuple("build/__init__.py build/tei/__init__.py build/tei/tyerman_whitefield_complete.py build/tei/tyerman_whitefield_runtime.py".split()),
}


def digest(b):
    return hashlib.sha256(b).hexdigest()


def plain(value):
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def closure(role="oracle", extra=None):
    module = "build.tei.tyerman_whitefield_complete" + ("_oracle" if role == "oracle" else "")
    code = """import importlib,json,sys
from pathlib import Path
r=Path(sys.argv[1]).resolve();sys.path.insert(0,str(r));before=set(sys.modules)
importlib.import_module(sys.argv[2])
if len(sys.argv)>3:importlib.import_module(sys.argv[3])
paths=sorted({Path(m.__file__).resolve().relative_to(r).as_posix() for name,m in sys.modules.copy().items() if name not in before and getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(r)})
print(json.dumps(paths))"""
    args = [sys.executable, "-I", "-B", "-c", code, str(ROOT), module] + ([extra] if extra else [])
    observed = json.loads(subprocess.run(args, check=True, capture_output=True, text=True).stdout)
    if tuple(observed) != IMPORTS[role]:
        raise ValueError("Unexpected first-party import closure: " + repr(observed))
    return digest(_canonical([{"path": p, "sha256": digest((ROOT / p).read_bytes())} for p in observed]))


def records(root):
    result = []
    queue = [(root, "/" + root.tag, None, 1)]
    while queue:
        e, selector, parent, ordinal = queue.pop()
        result.append({"selector": selector, "parent": parent, "ordinal": ordinal, "tag": e.tag, "attributes": dict(e.attrib), "direct_text_sha256": digest((e.text or '').encode()), "direct_text_is_none": e.text is None, "tail_text_sha256": digest((e.tail or '').encode()), "tail_text_is_none": e.tail is None, "children": len(e)})
        queue.extend((c, selector + f"/{c.tag}[{i}]", selector, i) for i, c in reversed(list(enumerate(e, 1))))
    return result


def source_fields(root):
    return [{"selector": row['selector'], "tag": e.tag, "attributes": dict(e.attrib), "direct_text": e.text, "tail_text": e.tail, "children": len(e)} for row, e in zip(records(root), root.iter())]


def sources():
    loaded = []
    for eid, pins in DATA.items():
        path = ROOT / f"raw/gutenberg/{eid}/pg{eid}-h.zip"
        if digest(path.read_bytes()) != pins[0]:
            raise ValueError("Retained ZIP source identity differs")
        with ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ValueError("ZIP CRC differs")
            inventory = [{"path": e.filename, "bytes": e.file_size, "compressed_bytes": e.compress_size, "crc32": f"{e.CRC:08x}", "sha256": digest(archive.read(e))} for e in archive.infolist() if not e.is_dir()]
            raw = archive.read(f"pg{eid}-images.html")
            assets = {e.filename: archive.read(e) for e in archive.infolist() if not e.is_dir() and e.filename.startswith('images/')}
        if digest(raw) != pins[1]:
            raise ValueError("Retained HTML source identity differs")
        parser = html5lib.HTMLParser(namespaceHTMLElements=False)
        source = parser.parse(raw)
        if parser.errors or any(not isinstance(e.tag, str) for e in source.iter()):
            raise ValueError("Undeclared parser recovery/comments")
        other = html.document_fromstring(raw, parser=html.HTMLParser(encoding='utf-8'))
        if len(list(source.iter())) != len(list(other.iter())):
            raise ValueError("Independent HTML parser cardinality differs")
        differences = []
        for i, (a, b) in enumerate(zip(source.iter(), other.iter())):
            for field, av, bv in [('tag', a.tag, b.tag), ('attributes', dict(a.attrib), dict(b.attrib)), ('direct_text', a.text, b.text), ('tail_text', a.tail, b.tail)]:
                if isinstance(bv, str):
                    bv = bv.replace('\r\n', '\n').replace('\r', '\n')
                if av != bv:
                    differences.append({'position': i, 'tag': a.tag, 'field': field, 'html5lib': av, 'libxml': bv})
        expected = [{'position': 0, 'tag': 'html', 'field': 'direct_text', 'html5lib': None, 'libxml': '\n'}, {'position': 24, 'tag': 'body', 'field': 'tail_text', 'html5lib': None, 'libxml': '\n'}, {'position': 11499 if eid == '44280' else 19664, 'tag': 'footer', 'field': 'tail_text', 'html5lib': '\n\n', 'libxml': None}]
        if differences != expected:
            raise ValueError("Independent parser full-field corroboration differs: " + repr(differences[:4]))
        folder = ROOT / f"reports/_logs/tyerman-whitefield-complete-20261004-v1/retained-components/{eid}/package"
        old_bytes = (folder / 'content.tei.xml').read_bytes()
        if digest((folder / 'manifest.json').read_bytes()) != pins[2] or digest(old_bytes) != pins[3]:
            raise ValueError("Recovered component authority differs")
        CandidatePackage.load(folder).verify_integrity()
        legacy_path=ROOT/f'sources/manifest-acquisitions/tyerman-life-george-whitefield-vol-{1 if eid=="44280" else 2}-{1876 if eid=="44280" else 1877}/source-manifest.json'
        expected_legacy='60348b2e4ad6d5f7b33aca2447c3930fd3be2ed4de4aeb2c9298839cdc989a28' if eid=='44280' else '14679063b733a4f268fc8ed9fc6ed736c7f3e63147780f958d72ba9130565eba'
        if digest(legacy_path.read_bytes())!=expected_legacy:
            raise ValueError('Original source-manifest lineage differs')
        SourceManifest.load(legacy_path,repository_root=ROOT).verify()
        old = etree.fromstring(old_bytes, etree.XMLParser(resolve_entities=False, no_network=True))
        if ' '.join(''.join(old.find(N+'text').itertext()).split()) != ' '.join(''.join(source.find('body').itertext()).split()):
            raise ValueError("Original component normalized text correspondence differs")
        loaded.append((eid, raw, source, assets, old, inventory, differences))
    return loaded


def expected_profile():
    volumes = []
    for eid, raw, source, assets, old, members, differences in sources():
        body = source.find('body')
        ids = [e.get('id') for e in body.iter() if e.get('id')]
        broken = [e.get('href') for e in body.iter('a') if e.get('href', '').startswith('#') and e.get('href')[1:] not in ids]
        volumes.append({'ebook_id': eid, 'archive_sha256': DATA[eid][0], 'html_sha256': DATA[eid][1], 'archive_members': members, 'source_fields': records(source), 'tags': dict(sorted(Counter(e.tag for e in source.iter()).items())), 'languages': [e.get('lang') for e in source.iter() if e.get('lang') is not None], 'abbreviation_expansions': sum(e.tag == 'abbr' and e.get('title') is not None for e in body.iter()), 'tooltip_titles': sum(e.tag == 'span' and e.get('title') is not None for e in body.iter()), 'table_summary_labels': [e.get('data-summary') for e in body.iter('table') if e.get('data-summary') is not None], 'body_graphics': [e.get('src') for e in body.iter('img')], 'unresolved_local_fragments': broken, 'independent_parser_boundary_whitespace': differences, 'original_tei_sha256': DATA[eid][3], 'original_native_fields_sha256': digest(_canonical(records(old)))})
    return {'contract': 'ocd-l635-complete-biography-source-profile-v1', 'work_id': WORK, 'scope': SCOPE, 'boundary': 'One explicitly two-volume authored biography. John Wesley advertisement, quoted correspondence, provider notices and index remain contextual source parts, not new complete works. Historical per-volume distinct-work claims are qualified and superseded for this candidate only.', 'volumes': volumes, 'inverse_model': 'Complete HTML5 DOM fields including null/direct text/tails, attributes, child count, parent, ordinal and selector. libxml independently matches all fields after HTML newline normalization except three pinned boundary whitespace loci per volume. Raw HTML bytes and ZIP envelope remain independently pinned; DOM inversion does not assert byte-identical HTML serialization.'}


def expected_policy():
    return {'contract': 'ocd-l635-complete-biography-policy-v1', 'work_id': WORK, 'scope': SCOPE, 'provenance': {'work_id': WORK, 'status': 'nonaccepted', 'provider': 'Project Gutenberg', 'author_literal': 'L. Tyerman', 'primary_title': TITLE, 'source_order': list(DATA), 'source_archive_sha256': [v[0] for v in DATA.values()], 'original_component_manifest_sha256': [v[2] for v in DATA.values()], 'original_component_tei_sha256': [v[3] for v in DATA.values()], 'representation': 'Source-backed repaired representation of exact retained TEI components; no whole-body additive byte inverse claim.', 'boundary': 'Both volumes constitute one complete authored biography; obsolete distinct-work claims remain unchanged historical lineage, not current scope.', 'rights': 'Retained sources state public domain in the USA. Human acceptance, applicable rights/jurisdiction, disclosure, attribution, print collation, CVW review and publication remain separate.', 'mapping': 'Volume-qualified IDs and fragment targets; exact embedded retained image pixels and member identity; actual source-language attributes, abbreviation expansions, tooltip notices and table summaries; complete native footer and explicit table-section whitespace/ownership accounting. Source styles and head/prolog/header fields are human-visible source annotations.'}, 'unresolved': [{'kind': 'human-review', 'message': 'Technical candidate only. Human acceptance, rights/jurisdiction, contact disclosure and publication not established.'}, {'kind': 'print-and-visual-review', 'message': 'Retained image pixels inspected; no print-page collation or CVW visual review claimed.'}, {'kind': 'source-representation', 'message': 'Electronic transcriber corrections and source defects remain as supplied. Table tbody wrappers are explicitly accounted because TEI rows do not admit HTML section wrappers; no inferred layout is claimed.'}]}


def metadata(raw, source, old):
    string = raw.decode('utf-8', errors='strict')
    b = source.find('body')
    return {'raw_document_prefix': string[:string.index('<html')], 'raw_document_suffix': string[string.rindex('</html>')+7:], 'html': {'tag': source.tag, 'attributes': dict(source.attrib), 'direct_text': source.text, 'tail_text': source.tail}, 'head': source_fields(source.find('head')), 'body': {'tag': b.tag, 'attributes': dict(b.attrib), 'direct_text': b.text, 'tail_text': b.tail}, 'legacy_header': etree.tostring(old.find(N+'teiHeader'), encoding='unicode'), 'legacy_scope_qualification': 'The historical per-volume candidate and distinct-work claim are superseded for current scope only. Both volumes constitute this one authored biography; historical records remain unchanged.'}


def ensure(e, tag, attrs, text=None, tail=None):
    if e.tag != N+tag or dict(e.attrib) != attrs or e.text != text or e.tail != tail:
        raise ValueError('Actual native field/role differs: ' + tag)


def ann(e):
    value = e.get('ana', '')
    if not value.startswith(PREFIX):
        raise ValueError('Native source annotation absent')
    decoded = json.loads(unquote(value[len(PREFIX):]))
    if value != PREFIX + quote(_canonical(decoded).decode().rstrip('\n'), safe=''):
        raise ValueError('Noncanonical native source annotation')
    if set(decoded) not in ({'tag','attributes'}, {'tag','attributes','sections'}):
        raise ValueError('Invented annotation fields')
    return decoded


def inverse(e, eid, assets, inline=False):
    if not inline and e.get('rend')=='source-standalone-inline':
        ensure(e,'p',{'rend':'source-standalone-inline'})
        if len(e)!=1:raise ValueError('Standalone inline cardinality differs')
        return inverse(e[0],eid,assets,True)
    info = ann(e)
    tag, attrs = info['tag'], info['attributes']
    base = {'ana': e.get('ana')}
    if attrs.get('id'):
        base[X+'id'] = 'v' + eid + '-' + attrs['id']
    if 'lang' in attrs:
        base[X+'lang'] = attrs['lang']
    if 'style' in attrs:
        base['style'] = attrs['style']
    if 'role' in attrs:
        base['subtype'] = 'source-role-' + attrs['role']
    if 'aria-labelledby' in attrs:
        base['corresp'] = ' '.join('#v' + eid + '-' + x for x in attrs['aria-labelledby'].split())
    if tag in {'h1','h2','h3','h4','h5','h6'} and 'title' in attrs:
        base['n'] = attrs['title']
    native = None
    special = []
    source = etree.Element(tag, **attrs)
    source.tail = e.tail
    if inline:
        if tag == 'a':
            native = 'ref' if attrs.get('href') else 'seg'
            base['rend'] = 'source-a'
            if attrs.get('href'):
                href = attrs['href']
                base['target'] = '#v'+eid+'-'+href[1:] if href.startswith('#') else href
        elif tag == 'img':
            native = 'graphic'
            raw = assets[attrs['src']]
            base['url'] = 'data:' + ('image/png' if attrs['src'].endswith('.png') else 'image/jpeg') + ';base64,' + base64.b64encode(raw).decode()
            base['corresp'] = f"urn:ocd:retained:pg{eid}:{attrs['src']}"
            if 'alt' in attrs:
                base['n'] = attrs['alt']
            for dimension in ('width','height'):
                if attrs.get(dimension):
                    base[dimension] = attrs[dimension] + 'px'
            if attrs['src']=='images/brace_lt.png':
                if attrs.get('style')!='height: 2em;':raise ValueError('Brace source height style differs')
                base['height']='2em'
        elif tag == 'br':
            native = 'lb'
        elif tag == 'abbr':
            native = 'choice'
            if len(e) != 2:
                raise ValueError('Source abbreviation choice cardinality differs')
            abbreviation, expansion = e
            ensure(abbreviation, 'abbr', {}, abbreviation.text)
            ensure(expansion, 'expan', {}, attrs.get('title'))
            if len(expansion):
                raise ValueError('Invented abbreviation expansion payload')
            source.text = abbreviation.text
            source.extend(inverse(c, eid, assets, True) for c in abbreviation)
        elif tag in {'p','div','h1','h2','h3','h4','h5','h6'}:
            native = 'seg'; base['type'] = 'source-'+tag
        elif tag in {'span','i','em','strong','small','sup','sub','cite'}:
            native = 'hi'; base['rend'] = 'source-'+tag + (' '+attrs['class'] if attrs.get('class') else '')
        else:
            raise ValueError('Unexpected native inline source role '+tag)
        if tag != 'abbr':
            source.text = e.text
            children = list(e)
            if tag == 'span' and attrs.get('title') is not None:
                if not children:
                    raise ValueError('Tooltip missing')
                tooltip = children.pop()
                ensure(tooltip, 'note', {'type':'source-tooltip'}, attrs['title'])
                if len(tooltip):
                    raise ValueError('Invented tooltip payload')
            if tag == 'span' and 'pagenum' in attrs.get('class','').split():
                if not children:
                    raise ValueError('Page marker missing')
                marker = children.pop()
                source.extend(inverse(c,eid,assets,True) for c in children)
                m = re.search(r'(?:\[(?:Pg\s*)?|\{)([^\]}]+)(?:\]|\})',''.join(source.itertext()))
                ensure(marker,'pb',{'n':m.group(1)} if m else {})
                if len(marker):
                    raise ValueError('Invented page payload')
            else:
                source.extend(inverse(c,eid,assets,True) for c in children)
    elif tag in {'div','header','footer','blockquote'}:
        native = 'div'; base['type'] = 'source-'+tag
        children = list(e)
        if children and children[0].get('rend') == 'source-leading-text':
            lead = children.pop(0)
            ensure(lead,'p',{'rend':'source-leading-text'},lead.text)
            if len(lead):
                raise ValueError('Invented leading text payload')
            source.text = lead.text
        for carrier in children:
            ensure(carrier,'div',{'type':'source-child-carrier'})
            if len(carrier) != 1:
                raise ValueError('Child carrier cardinality differs')
            source.append(inverse(carrier[0],eid,assets))
        if e.text is not None:
            raise ValueError('Invented container leading text')
    elif tag == 'table':
        native = 'table'; source.text = e.text
        children = list(e)
        if attrs.get('data-summary') is not None:
            summary = children.pop(0)
            ensure(summary,'head',{'type':'source-table-summary'},attrs['data-summary'])
            if len(summary):
                raise ValueError('Invented table summary payload')
        for section in info.get('sections',[]):
            if set(section) != {'tag','attributes','direct_text','tail_text','rows'} or section['tag'] != 'tbody':
                raise ValueError('Table section accounting differs')
            wrap = etree.SubElement(source,section['tag'],**section['attributes'])
            wrap.text,wrap.tail = section['direct_text'],section['tail_text']
            for unused in range(section['rows']):
                if not children:
                    raise ValueError('Table rows omitted')
                wrap.append(inverse(children.pop(0),eid,assets))
        if children:
            raise ValueError('Table rows invented')
    elif tag == 'tr':
        native = 'row';source.text=e.text
        source.extend(inverse(c,eid,assets) for c in e)
    elif tag in {'td','th'}:
        native = 'cell';source.text=e.text
        if tag == 'th':base['role']='label'
        if attrs.get('colspan'):base['cols']=attrs['colspan']
        source.extend(inverse(c,eid,assets,True) for c in e)
    elif tag == 'ul':
        native = 'list';base['type']='source-ul';source.text=e.text
        source.extend(inverse(c,eid,assets) for c in e)
    elif tag == 'li':
        native='item';source.text=e.text
        source.extend(inverse(c,eid,assets,True) for c in e)
    elif tag == 'hr':
        native='milestone';base['unit']='source-hr';source.text=e.text
        if len(e):raise ValueError('Invented rule payload')
    elif tag in {'p','h1','h2','h3','h4','h5','h6'}:
        native='p' if tag == 'p' else 'head';base['rend']='source-'+tag;source.text=e.text
        source.extend(inverse(c,eid,assets,True) for c in e)
    else:
        raise ValueError('Unexpected native block source role '+tag)
    if e.tag != N+native or dict(e.attrib) != base:
        raise ValueError('Actual source-derived native attributes/role differ '+tag)
    if 'sections' in info and tag != 'table':
        raise ValueError('Table annotation on other role')
    return source


def check_content(content, profile):
    loaded = sources()
    root = etree.fromstring(content, etree.XMLParser(resolve_entities=False,no_network=True))
    ensure(root,'TEI',{X+'lang':'en'})
    if len(root) != 2:
        raise ValueError('Outer TEI cardinality differs')
    hd,outer = root
    ensure(hd,'teiHeader',{})
    ensure(outer,'text',{})
    if len(outer) != 1:
        raise ValueError('Outer text cardinality differs')
    group=outer[0];ensure(group,'group',{})
    if len(group)!=2:
        raise ValueError('Complete volume set/order differs')
    # Independently construct the entire exact expected metadata header.
    expected=etree.Element(N+'teiHeader')
    def add(p,t,text=None,**attrs):
        e=etree.SubElement(p,N+t,**attrs);e.text=text;return e
    fd=add(expected,'fileDesc');ts=add(fd,'titleStmt')
    add(ts,'title',TITLE);add(ts,'author','L. Tyerman')
    pub=add(fd,'publicationStmt');add(pub,'p','Nonaccepted complete-work reconstruction candidate. Technical validation, human acceptance, rights clearance, and publication are separate.')
    sd=add(fd,'sourceDesc')
    results=[]
    for pos,((eid,raw,src,assets,old,members,differences),actual) in enumerate(zip(loaded,group),1):
        b=add(sd,'bibl',n=str(pos));add(b,'title',TITLE+(' Vol. I' if pos==1 else ' Vol. II'));add(b,'author','L. Tyerman');add(b,'pubPlace','London');add(b,'publisher','Hodder and Stoughton');add(b,'date','MDCCCLXXVI' if pos==1 else 'MDCCCLXXVII',when='1876' if pos==1 else '1877');add(b,'ref',f'Retained Project Gutenberg eBook {eid}',target=f'https://www.gutenberg.org/ebooks/{eid}')
        acquisition=json.loads((ROOT/f'raw/gutenberg/{eid}/acquisition-receipt.json').read_bytes())
        if acquisition['source_url']!=f'https://www.gutenberg.org/ebooks/{eid}' or acquisition['package_url']!=f'https://www.gutenberg.org/cache/epub/{eid}/pg{eid}-h.zip' or acquisition['downloaded_utc']!=('2026-09-23T05:52:23Z' if pos==1 else '2026-09-23T05:52:26Z'):
            raise ValueError('Original acquisition URL/time differs')
        add(b,'note',_canonical(acquisition).decode().rstrip('\n'),type='retained-acquisition')
        add(b,'note',_canonical(metadata(raw,src,old)).decode().rstrip('\n'),type='source-envelope')
        support={'archive_members':members,'qualification':'All original archive members are retained and hash-bound. Body-referenced images are embedded as exact pixels; the Volume I cover is head-linked support, not invented body illustration. CSS and electronic head/prolog fields are source annotations, not authored prose. No print collation or rights clearance is claimed.'}
        add(b,'note',_canonical(support).decode().rstrip('\n'),type='retained-archive-support')
        body=src.find('body');info=ann(actual)
        if info!={'tag':'body','attributes':dict(body.attrib)}:
            raise ValueError('Complete source body attributes differ')
        url=next(e.get('content') for e in src.find('head') if e.get('property')=='og:url')
        ensure(actual,'text',{'n':'I' if pos==1 else 'II','ana':actual.get('ana'),X+'id':'volume-'+eid,X+'lang':src.get('lang'),X+'base':url})
        if len(actual)!=3:
            raise ValueError('Volume envelope cardinality differs')
        decoded=etree.Element('body',**body.attrib);decoded.tail=body.tail
        carriers=[]
        for region_name,region in zip(('front','body','back'),actual):
            ensure(region,region_name,{})
            if len(region)!=1:raise ValueError('Region cardinality differs')
            wrapper=region[0];ensure(wrapper,'div',{'type':'source-'+region_name+'-envelope'})
            items=list(wrapper)
            if region_name=='front' and body.text is not None:
                lead=items.pop(0);ensure(lead,'p',{'rend':'source-body-leading-text'},body.text)
                if len(lead):raise ValueError('Invented body leading payload')
                decoded.text=lead.text
            for carrier in items:
                index=int(carrier.get('n','0'))
                ensure(carrier,'div',{'type':'source-body-carrier','n':str(index)})
                if len(carrier)!=1:raise ValueError('Body carrier cardinality differs')
                e=carrier[0]
                if e.get('rend')=='source-standalone-inline':
                    ensure(e,'p',{'rend':'source-standalone-inline'})
                    if len(e)!=1:raise ValueError('Standalone inline cardinality differs')
                    restored=inverse(e[0],eid,assets,True)
                else:restored=inverse(e,eid,assets)
                correct='front' if restored.tag=='header' else 'back' if restored.tag=='footer' else 'body'
                if correct!=region_name:raise ValueError('Source region ownership differs')
                carriers.append((index,restored))
        if [i for i,e in carriers]!=list(range(1,len(body)+1)):
            raise ValueError('Actual source global order/duplication differs')
        decoded.extend(e for i,e in carriers)
        if records(decoded)!=records(body):
            for a,c in zip(records(body),records(decoded)):
                if a!=c:raise ValueError('Actual-object full source inverse differs at '+a['selector'])
            raise ValueError('Actual-object full source inverse cardinality differs')
        results.append({'ebook_id':eid,'body_elements':len(list(body.iter())),'source_inverse_sha256':digest(_canonical(records(decoded))),'raw_source_sha256':digest(raw),'independent_parser_boundary_whitespace':differences})
    if records(hd)!=records(expected):
        raise ValueError('Complete actual header fields/assertions differ')
    ids=[e.get(X+'id') for e in root.iter() if e.get(X+'id')]
    if len(ids)!=len(set(ids)):
        raise ValueError('Duplicate actual IDs')
    schema=etree.XMLSchema(etree.parse(str(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd')))
    if not schema.validate(root):
        raise ValueError('TEI P5 XSD failure: '+str(schema.error_log.last_error))
    return results


def authority_spec():
    rows=[]
    for eid in DATA:
        base=f'raw/gutenberg/{eid}'
        rows.extend([(f'archive-{eid}',base+f'/pg{eid}-h.zip','primary-source'),(f'acquisition-{eid}',base+'/acquisition-receipt.json','retained-acquisition-receipt'),(f'member-inventory-{eid}',base+'/member-inventory.tsv','retained-member-inventory')])
        legacy=f'sources/manifest-acquisitions/tyerman-life-george-whitefield-vol-{1 if eid=="44280" else 2}-{1876 if eid=="44280" else 1877}'
        for name in ['source-manifest.json','profile.json','policy.json','README.source.md','REVIEW.md']:
            rows.append((f'historical-{eid}-{name}',legacy+'/'+name,'qualified-historical-source-authority'))
        retained=f'reports/_logs/tyerman-whitefield-complete-20261004-v1/retained-components/{eid}'
        for name in ['README.source.md','content.tei.xml','manifest.json','provenance.json','source-accountability.json','unresolved.jsonl']:
            rows.append((f'legacy-tei-{eid}' if name=='content.tei.xml' else f'legacy-{eid}-{name}',retained+'/package/'+name,'qualified-recovered-component'))
        for name in ['validation.json','mutation-reproduction.json']:
            rows.append((f'legacy-{eid}-{name}',retained+'/'+name,'qualified-dated-proof'))
    rows.extend([('historical-recovery-receipt','reports/_logs/tyerman-whitefield-complete-20261004-v1/historical-components-recovery.json','exact-recovery-receipt'),('shared-producer','build/tei/tyerman_pg_html.py','frozen-historical-converter'),('shared-oracle','build/tei/tyerman_pg_html_oracle.py','frozen-historical-validator')])
    home='sources/manifest-acquisitions/tyerman-life-george-whitefield-complete-20261004-v3'
    rows.extend([('profile',home+'/profile.json','complete-source-feature-profile'),('policy',home+'/policy.json','independent-validation-policy'),('readme',home+'/README.source.md','source-local-attribution-readme'),('execution-runtime',home+'/execution-runtime.json','observed-complete-execution-runtime'),('tei-validation-schema','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema')])
    rows.extend((name,'ocd_kernel/tei/vendor/xsd/'+name+'.xsd','tei-schema-transitive-dependency') for name in ['tei_all_teix','tei_all_xml'])
    rows.extend((f'import-{i}',p,'observed-first-party-import-dependency') for i,p in enumerate(sorted(set(IMPORTS['oracle']+IMPORTS['producer']))))
    return rows


def source_contract(manifest,candidate):
    record=plain(manifest.record)
    expected_keys={'contract','work_id','source_id','manifest_row','scope','source_order','authorities','converter','validator','package_schema'}
    if set(record)!=expected_keys or record['source_order']!=list(DATA) or record['manifest_row']!='L635':
        raise ValueError('Exact source contract fields/order differ')
    expected=[]
    for name,path,role in authority_spec():
        value=(ROOT/path).read_bytes()
        expected.append({'name':name,'path':path,'role':role,'bytes':len(value),'sha256':digest(value)})
    if record['authorities']!=expected:raise ValueError('Exact authority names/roles/order/paths/pins differ')
    home=ROOT/'sources/manifest-acquisitions/tyerman-life-george-whitefield-complete-20261004-v3/source-manifest.json'
    capture_paths=[ROOT/f'.tmp_audit/tyerman-whitefield-runtime-capture-{version}/source-manifest.json' for version in ['v3','v3b','v3c','v3d']]
    capture_mode=manifest.path.resolve() in [p.resolve() for p in capture_paths]
    # Every source manifest path is bound by the candidate. Scratch resealed
    # contract challenges may use the same exact authority paths. Only the
    # single named capture manifest may select unguarded capture callables.
    if plain(candidate.manifest['source_manifest'])!={'path':manifest.path.relative_to(ROOT).as_posix(),'sha256':manifest.sha256}:
        raise ValueError('Exact candidate source path/hash differs')
    for role,path,identity,call in [('converter','build/tei/tyerman_whitefield_complete.py','ocd-l635-retained-complete-whitefield-biography','_build' if capture_mode else '_convert'),('validator','build/tei/tyerman_whitefield_complete_oracle.py',ORACLE_ID,'_inspect' if capture_mode else '_oracle')]:
        binding={'id':identity,'version':'1','callable':call,'implementation_path':path,'implementation_sha256':digest((ROOT/path).read_bytes())}
        if role=='validator':binding['import_closure_sha256']=closure()
        if record[role]!=binding:raise ValueError('Exact guarded callable binding differs '+role)
    schema='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json'
    if record['package_schema']!={'path':schema,'sha256':digest((ROOT/schema).read_bytes())}:raise ValueError('Package schema binding differs')
    if digest(manifest.authority_path('readme').read_bytes())!='a7c817e39d943a87e6767e0f476212dd19add0c3d439e2c9ceeb21a9b3b670a0':
        raise ValueError('Complete independently pinned source README differs')
    if plain(candidate.manifest['converter'])!=record['converter'] or plain(candidate.manifest['package_schema'])!=record['package_schema']:
        raise ValueError('Candidate full callable/schema binding differs')


def _inspect(manifest: SourceManifest,candidate: CandidatePackage):
    findings=[]
    try:
        source_contract(manifest,candidate)
        if manifest.record['work_id']!=WORK or manifest.record['source_id']!='gutenberg-44280-62023-retained-biography' or manifest.record['scope']!=SCOPE:
            raise ValueError('Exact source identity/scope differs')
        if candidate.manifest['source_id']!=manifest.record['source_id'] or candidate.manifest['source_manifest']['sha256']!=manifest.sha256:
            raise ValueError('Candidate source contract binding differs')
        profile=json.loads(manifest.authority_path('profile').read_bytes())
        if profile!=expected_profile():raise ValueError('Complete independent source profile differs')
        policy=json.loads(manifest.authority_path('policy').read_bytes())
        if policy!=expected_policy():raise ValueError('Complete independent policy differs')
        content=candidate.member_bytes('content.tei.xml')
        result_rows=check_content(content,profile)
        account={'contract':'ocd-l635-complete-biography-accountability-v1','work_id':WORK,'scope':'One complete authored biography, two ordered complete electronic source-volume envelopes','tei_sha256':digest(content),'source_inventory':profile,'representation':'Source-backed repaired representation of exact retained legacy TEI components. No whole-body additive byte inverse is claimed. Actual native source fields invert to the complete bound HTML5 source DOM; table tbody wrappers alone use explicit nontextual wrapper accounting.','legacy_component_normalized_body_correspondence':True}
        if json.loads(candidate.member_bytes('source-accountability.json'))!=account:raise ValueError('Full source accounting differs')
        if json.loads(candidate.member_bytes('provenance.json'))!=policy['provenance']:raise ValueError('Exact provenance differs')
        if candidate.member_bytes('unresolved.jsonl')!=b''.join(_canonical(e) for e in policy['unresolved']):raise ValueError('Exact unresolved ledger differs')
        if candidate.member_bytes('README.source.md')!=manifest.authority_path('readme').read_bytes():raise ValueError('Exact visible source README differs')
    except (ValueError,KeyError,IndexError,etree.XMLSyntaxError) as exc:
        findings.append(str(exc));result_rows=[]
    result={'status':'pass' if not findings else 'fail','oracle_id':ORACLE_ID,'oracle_version':'1','implementation_sha256':digest(Path(__file__).read_bytes()),'import_closure_sha256':closure(),'runtime':_runtime_binding(),'source_manifest_sha256':manifest.sha256,'candidate_sha256':candidate.sha256,**_validation_authority_bindings(manifest),'findings':findings}
    result['result_sha256']=digest(_canonical(result))
    return result


def _oracle(manifest,candidate):
    if manifest.record['converter']['callable']!='_convert' or manifest.record['validator']['callable']!='_oracle':
        raise ValueError('Final guarded source callable fence differs')
    guard(manifest,'before-oracle')
    result=_inspect(manifest,candidate)
    guard(manifest,'after-oracle')
    return result


_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version='1'
_oracle.implementation_path=Path(__file__).resolve()
_inspect.oracle_id=ORACLE_ID
_inspect.oracle_version='1'
_inspect.implementation_path=Path(__file__).resolve()
