"""Reversible work-local public envelope for the complete retained Allen witness.

The retained mapper remains the source parser. These aliases concern its generated
TEI scaffolding, not additions, emendations, or substitutions in source text.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from ocd_kernel.reconstruction.contract import CandidatePackage

NS = 'http://www.tei-c.org/ns/1.0'
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'
CONVERTER_ID = 'ocd-calvin-complete-reversible-native-envelope'
CONVERTER_VERSION = '1'


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))+'\n').encode()


def body_digest(body):
    return sha256(etree.tostring(body, method='c14n', exclusive=True)).hexdigest()


def header(volume=None):
    node = etree.Element('{'+NS+'}teiHeader')
    desc = etree.SubElement(node, '{'+NS+'}fileDesc')
    title = etree.SubElement(desc, '{'+NS+'}titleStmt')
    etree.SubElement(title, '{'+NS+'}title').text = 'Institutes of the Christian Religion'+('' if volume is None else ', Volume '+str(volume))
    etree.SubElement(title, '{'+NS+'}author').text = 'John Calvin'
    resp = etree.SubElement(title, '{'+NS+'}respStmt')
    etree.SubElement(resp, '{'+NS+'}resp').text = 'Translation from Latin, collated with the author’s last French edition'
    etree.SubElement(resp, '{'+NS+'}name').text = 'John Allen'
    pub = etree.SubElement(desc, '{'+NS+'}publicationStmt')
    etree.SubElement(pub, '{'+NS+'}p').text = 'Retained source reconstruction for technical review; no publication authorization.'
    source = etree.SubElement(desc, '{'+NS+'}sourceDesc')
    bibl = etree.SubElement(source, '{'+NS+'}bibl')
    etree.SubElement(bibl, '{'+NS+'}title').text = 'Sixth American Edition, Revised and Corrected, in Two Volumes'
    etree.SubElement(bibl, '{'+NS+'}publisher').text = 'Presbyterian Board of Publication'
    etree.SubElement(bibl, '{'+NS+'}pubPlace').text = 'Philadelphia'
    etree.SubElement(bibl, '{'+NS+'}note').text = ('Project Gutenberg retained electronic witnesses 45001 and 64392. '+
        'Volume I title-page year 1813 and the appended S. T. Livermore Scripture-index year 1852 are retained source labels; their relation remains unresolved. '+
        'United States public-domain claims, jurisdiction warning, and Gutenberg license and trademark terms are distinct; worldwide status remains unresolved.'+
        ('' if volume is None else ' Physical volume '+str(volume)+'; original text-envelope n='+str(volume)+'.'))
    return node


def adapt(payload: bytes):
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    original = etree.fromstring(payload, parser)
    ns = {'t': NS}
    texts = original.xpath('./t:text/t:group/t:text', namespaces=ns)
    if [(x.get(XML_ID), x.get('n')) for x in texts] != [('calvin-volume-1', '1'), ('calvin-volume-2', '2')]:
        raise ValueError('exact two-volume source envelope is required')
    corpus = etree.Element('{'+NS+'}teiCorpus', nsmap={None: NS})
    corpus.set(XML_ID, original.get(XML_ID))
    corpus.append(header())
    changes = []
    bodies = []
    for volume, text in enumerate(texts, 1):
        member = etree.SubElement(corpus, '{'+NS+'}TEI')
        member.set(XML_ID, 'calvin-physical-volume-'+str(volume))
        member.append(header(volume))
        target_text = deepcopy(text)
        del target_text.attrib['n']
        member.append(target_text)
        body = target_text.find('{'+NS+'}body')
        if body is None or len(text) != 1:
            raise ValueError('physical volume body cardinality differs')
        bodies.append({'volume': volume, 'source_body_sha256': body_digest(text[0])})
        def visit(node, path):
            old_tag, old_attrs = etree.QName(node).localname, dict(node.attrib)
            if old_tag == 'ab':
                if 'type' not in node.attrib or set(node.attrib) - {XML_ID, 'type'}:
                    raise ValueError('unknown original block alias shape')
                source_type = node.get('type')
                source_text = ''.join(node.itertext())
                node.set('type', 'source-whitespace' if not source_text.strip() else 'source-block')
                node.set('subtype', source_type)
            elif old_tag == 'c':
                if dict(node.attrib) != {'type': 'emphasis-delimiter'} or node.text != '_' or len(node):
                    raise ValueError('unknown source delimiter shape')
                node.tag = '{'+NS+'}seg'
            elif old_tag == 'div' and 'part' in node.attrib:
                if node.get('type') != 'book' or node.get('part') not in {'N', 'I', 'F'} or 'ana' in node.attrib:
                    raise ValueError('unknown physical book part alias shape')
                node.set('ana', 'source-part:'+node.attrib.pop('part'))
            elif old_tag == 'table':
                if 'ana' in node.attrib or node.get('cols') != '4' or int(node.get('rows', '-1')) != len(node):
                    raise ValueError('unknown source table dimensions')
                node.set('ana', 'source-rows:'+node.attrib.pop('rows')+' source-cols:'+node.attrib.pop('cols'))
            elif old_tag == 'row':
                if node.get('role') != 'data' or 'ana' in node.attrib:
                    raise ValueError('unknown original row role')
                node.set('ana', 'source-role:'+node.attrib.pop('role'))
            if old_tag != etree.QName(node).localname or old_attrs != dict(node.attrib):
                changes.append({'volume': volume, 'body_child_path': path, 'old_tag': old_tag,
                    'old_attributes': old_attrs, 'new_tag': etree.QName(node).localname,
                    'new_attributes': dict(node.attrib)})
            for position, child in enumerate(node):
                visit(child, path+[position])
        visit(body, [])
    inventory = {'contract': 'ocd-calvin-reversible-native-envelope-v1',
        'original_tei_sha256': sha256(payload).hexdigest(), 'physical_volumes': bodies,
        'aliases': changes, 'scaffolding': 'one teiCorpus, two ordered physical TEI documents; original inner text IDs retained; original n retained in physical-volume milestone and member bibliographic note',
        'source_interpretation': 'none; inert literal annotations on generated source mapping scaffolding'}
    return etree.tostring(corpus, encoding='UTF-8', xml_declaration=True), canonical(inventory)


def _convert(manifest):
    manifest.verify()
    baseline=CandidatePackage.load(manifest.authority_path('baseline-package-manifest').parent)
    baseline.verify_integrity()
    content,inventory=adapt(baseline.member_bytes('content.tei.xml'))
    accounting=json.loads(baseline.member_bytes('source-accountability.json'))
    accounting['native_envelope']=json.loads(inventory)
    provenance=dict(contract='ocd-calvin-complete-native-provenance-v1',status='nonaccepted',
        baseline_package_sha256=baseline.sha256,baseline_tei_sha256=sha256(baseline.member_bytes('content.tei.xml')).hexdigest(),
        converter=dict(manifest.record['converter']),authorities={a['name']:{k:a[k] for k in ('path','role','bytes','sha256')} for a in manifest.record['authorities']},
        source_interpretation='none; exact reversible aliases of generated scaffolding; complete source text retained')
    return {'content.tei.xml':content,'source-accountability.json':canonical(accounting),
        'provenance.json':canonical(provenance),'README.source.md':manifest.authority_path('source-readme').read_bytes(),
        'unresolved.jsonl':baseline.member_bytes('unresolved.jsonl')}


_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION
_convert.implementation_path=Path(__file__).resolve()
