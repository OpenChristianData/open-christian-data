"""Compare the complete Thome TEI to independent retained-HTML evidence."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path
from lxml import etree
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts

TEI = 'http://www.tei-c.org/ns/1.0'

def _sha(raw):
    return hashlib.sha256(raw).hexdigest()

def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))+'\n').encode('utf-8')

def _oracle(source, candidate):
    source.verify()
    candidate.verify_integrity()
    profile_raw = source.authority_path('complete-work-profile').read_bytes()
    profile = json.loads(profile_raw)
    historical = json.loads(source.authority_path('profile').read_bytes())
    spec = importlib.util.spec_from_file_location('thome_independent_html_observer', source.authority_path('historical-observer'))
    observer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(observer)
    body, members, body_text = observer._source(source, historical)
    raw = candidate.member_bytes('content.tei.xml')
    tree = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
    if tree.tag != f'{{{TEI}}}TEI' or tree.findall(f'{{{TEI}}}TEI') or _sha(raw) != profile['direct_tei_sha256']:
        raise ValueError('Thome must be one complete conserved direct TEI')
    targets = tree.find(f'{{{TEI}}}text/{{{TEI}}}body')
    if targets is None or len(targets) != 108 or targets.text != body.text:
        raise ValueError('Thome source opening/body accounting differs')
    for i, (original, target) in enumerate(zip(body, targets, strict=True), 1):
        observer._compare_node(original, target, str(i), top=True)
    if ''.join(targets.itertext()) != body_text:
        raise ValueError('Thome body omissions, duplication or invention')
    ids = [e.get('{http://www.w3.org/XML/1998/namespace}id') for e in tree.iter()
           if e.get('{http://www.w3.org/XML/1998/namespace}id')]
    if len(ids) != len(set(ids)):
        raise ValueError('Thome duplicate source IDs')
    for ref in tree.iter(f'{{{TEI}}}ref'):
        target = ref.get('target') or ''
        if target.startswith('#') and target[1:] not in ids:
            raise ValueError('Thome dangling local link')
    for graphic in tree.iter(f'{{{TEI}}}graphic'):
        if graphic.get('url') not in {m['path'] for m in members}:
            raise ValueError('Thome image lacks retained member')
    titles = tree.xpath('./t:teiHeader/t:fileDesc/t:titleStmt/t:title/text()', namespaces={'t':TEI})
    if titles != ['Prayer for the Oppressed: A Premium Tract']:
        raise ValueError('Thome work title differs')
    schema = etree.XMLSchema(etree.parse(str(source.authority_path('tei-p5-xsd'))))
    if not schema.validate(tree):
        raise ValueError('Thome fails P5: '+str(schema.error_log.last_error))
    account = json.loads(candidate.member_bytes('source-accountability.json'))
    expected_account = {
        'contract':'ocd-thome-pg70704-complete-accounting-v3', 'ebook_id':'70704',
        'source_tag_counts': dict(Counter(e.tag.lower() for e in body.iter() if isinstance(e.tag,str))),
        'source_attribute_counts': dict(Counter(k for e in body.iter() if isinstance(e.tag,str) for k in e.attrib)),
        'archive_members':members, 'body_direct_children':len(body),
        'body_text_sha256':_sha(body_text.encode('utf-8')),
        'body_element_count':sum(isinstance(e.tag,str) for e in body.iter()),
        'complete_work_boundary':profile['complete_work_boundary'],
        'tei_sha256':_sha(raw), 'html_sha256':historical['html_sha256'],
        'archive_sha256':historical['archive_sha256'], 'units':historical['units'],
        'image_references':[e.get('src') for e in body.iter('img')],
        'link_references':[e.get('href') for e in body.iter('a') if e.get('href')],
        'predecessor_corpus_sha256':profile['predecessor_corpus_sha256'],
        'mapping':'Every retained HTML body direct child is represented once in source order; nested text, local links, headings, images, lists, tables, inline emphasis, and source IDs are mapped. HTML head and binary image members remain retained and hash-accounted; the source archive controls visual assets.',
    }
    if account != expected_account:
        raise ValueError('Thome complete accounting differs')
    if candidate.member_bytes('README.source.md') != source.authority_path('complete-work-notice').read_bytes():
        raise ValueError('Thome human-visible source notice differs')
    policy = json.loads(source.authority_path('policy').read_bytes())
    if candidate.member_bytes('unresolved.jsonl') != b''.join(_json(x) for x in policy['unresolved']):
        raise ValueError('Thome unresolved qualifications differ')
    provenance = json.loads(candidate.member_bytes('provenance.json'))
    if provenance != {'source_id': source.record['source_id'], 'source_manifest_sha256': source.sha256,
            'work_id': source.record['work_id'], 'edition_id': source.record['edition_id'],
            'acquisition_id': source.record['acquisition_id'], 'status': 'nonaccepted',
            'historical_profile_sha256': profile['historical_profile_sha256']}:
        raise ValueError('Thome provenance differs')
    closure = _sha(_json([{'path':p, 'sha256':_sha((source.repository_root / p).read_bytes())}
                          for p in profile['closure_paths']]))
    if closure != source.record['validator']['import_closure_sha256']:
        raise ValueError('Thome current measured observer closure differs')
    facts = MechanicalFacts(_sha(Path(__file__).read_bytes()), closure,
        _sha(source.authority_path('retained-archive').read_bytes()), _sha(profile_raw),
        _sha(source.authority_path('candidate-package-schema').read_bytes()),
        _sha(source.authority_path('tei-p5-xsd').read_bytes()),
        _sha(source.authority_path('complete-work-policy').read_bytes()), ())
    return verify_mechanical_facts(source, candidate, facts).as_record()

_oracle.oracle_id = 'ocd-thome-pg70704-complete-observer'
_oracle.oracle_version = '3'
