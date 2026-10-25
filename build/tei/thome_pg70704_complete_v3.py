"""Rebuild the complete retained Thome tract as one direct TEI document."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from lxml import etree

TEI = 'http://www.tei-c.org/ns/1.0'

def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))+'\n').encode('utf-8')

def _bound(source, name):
    path = source.authority_path(name)
    spec = importlib.util.spec_from_file_location('thome_source_producer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def _convert(source):
    source.verify()
    profile = json.loads(source.authority_path('complete-work-profile').read_bytes())
    output = _bound(source, 'historical-producer')._convert(source)
    corpus = etree.fromstring(output['content.tei.xml'], etree.XMLParser(resolve_entities=False, no_network=True))
    children = corpus.findall(f'{{{TEI}}}TEI')
    if len(children) != 1 or children[0].get('{http://www.w3.org/XML/1998/namespace}id') != 'pg70704-bounded-witness':
        raise ValueError('Thome complete-work identity/cardinality differs')
    direct = etree.tostring(children[0], encoding='UTF-8', xml_declaration=True, pretty_print=False)
    if hashlib.sha256(direct).hexdigest() != profile['direct_tei_sha256']:
        raise ValueError('Thome direct TEI differs from independently conserved historical source subtree')
    account = json.loads(output['source-accountability.json'])
    account.update(contract='ocd-thome-pg70704-complete-accounting-v3',
                   predecessor_corpus_sha256=account.pop('tei_sha256'),
                   tei_sha256=hashlib.sha256(direct).hexdigest(),
                   complete_work_boundary=profile['complete_work_boundary'])
    output.update({'content.tei.xml': direct, 'source-accountability.json': _json(account),
                   'README.source.md': source.authority_path('complete-work-notice').read_bytes(),
                   'provenance.json': _json({'source_id': source.record['source_id'],
                       'source_manifest_sha256': source.sha256, 'work_id': source.record['work_id'],
                       'edition_id': source.record['edition_id'], 'acquisition_id': source.record['acquisition_id'],
                       'status': 'nonaccepted', 'historical_profile_sha256': profile['historical_profile_sha256']})})
    return output

_convert.converter_id = 'ocd-thome-pg70704-complete'
_convert.converter_version = '3'
