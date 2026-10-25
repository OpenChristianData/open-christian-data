"""Whole-envelope Guyon PG24989 reconstruction; immutable legacy body mapping."""
from pathlib import Path
import hashlib
import importlib.util
import json
from zipfile import ZipFile
from lxml import etree, html

NS = '{http://www.tei-c.org/ns/1.0}'
BODY_PATH = 'build/tei/manifest_pg_l772_l790.py'
BODY_SHA = '5e54d5a7d78d46fce9e25b5e05ac7723611f853c54e1f7717f57aa2946bcf427'
def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')

def _convert(manifest):
    dependency = manifest.repository_root / BODY_PATH
    if hashlib.sha256(dependency.read_bytes()).hexdigest() != BODY_SHA:
        raise ValueError('Guyon historical body converter dependency changed')
    spec = importlib.util.spec_from_file_location('_guyon_bound_body_converter', dependency)
    if spec is None or spec.loader is None:
        raise ValueError('Guyon body converter cannot load')
    body = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(body)
    payloads = body._convert(manifest)
    root = etree.fromstring(payloads['content.tei.xml'], parser=etree.XMLParser(resolve_entities=False, no_network=True))
    description = root.find(NS + 'teiHeader/' + NS + 'fileDesc/' + NS + 'sourceDesc')
    if description is None:
        raise ValueError('Guyon source description missing')
    with ZipFile(manifest.authority_path('retained-archive')) as archive:
        retained_html = archive.read('pg24989-images.html')
        support = archive.read('24989-cover.png')
    head = html.fromstring(retained_html.decode('utf-8', errors='strict')).find('head')
    if head is None:
        raise ValueError('Guyon retained HTML head missing')
    ledger = []
    for position, source in enumerate(head, 1):
        row = {'position': position, 'tag': source.tag, 'attributes': list(source.attrib.items()), 'text': source.text or ''}
        if source.tag == 'style':
            row['disposition'] = 'presentation-only stylesheet; complete original retained in bound HTML/ZIP; no visual equivalence claimed'
        else:
            paragraph = etree.SubElement(description, NS + 'p')
            entry = etree.SubElement(paragraph, NS + 'seg', type='source-head-metadata', n=str(position))
            element = etree.SubElement(entry, NS + 'seg', type='source-head-element')
            element.text = source.tag
            element.tail = ': '
            for key, value in source.attrib.items():
                field = etree.SubElement(entry, NS + 'seg', type='source-head-attribute', n=key)
                field.text = key + '='
                if value.startswith(('http://', 'https://')):
                    etree.SubElement(field, NS + 'ref', target=value).text = value
                else:
                    field.text += value
                field.tail = '; '
            if source.text:
                etree.SubElement(entry, NS + 'seg', type='source-head-text').text = source.text
            row['disposition'] = 'readable sourceDesc paragraph'
            row['tei_locator'] = 'teiHeader/fileDesc/sourceDesc/p/seg[@type="source-head-metadata" and @n="' + str(position) + '"]'
        ledger.append(row)
    if len(ledger) != 21:
        raise ValueError('Guyon HTML head envelope changed')
    xml = etree.tostring(root, encoding='UTF-8', xml_declaration=True)
    payloads['content.tei.xml'] = xml
    account = json.loads(payloads['source-accountability.json'])
    account['tei_sha256'] = hashlib.sha256(xml).hexdigest()
    account['mapping'] += ' Guyon v13 gives every non-style HTML head child a readable metadata destination; two stylesheet children have explicit presentation-only dispositions. Retained cover PNG is separately delivered as unreferenced binary support, without an invented body placement or fetched external image.'
    payloads['source-accountability.json'] = _canonical(account)
    payloads['head-accountability.json'] = _canonical({'contract': 'ocd-guyon-head-accountability-v1', 'children': ledger, 'support': {'source_member': '24989-cover.png', 'candidate_member': '24989-cover.png', 'sha256': hashlib.sha256(support).hexdigest(), 'bytes': len(support), 'role': 'retained unreferenced binary support; no invented text-body placement'}})
    payloads['24989-cover.png'] = support
    return payloads
