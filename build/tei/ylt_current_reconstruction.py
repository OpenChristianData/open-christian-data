"""Reuse the freshly reproduced native YLT mapping result; qualify header and source book labels."""
from pathlib import Path
from hashlib import sha256
import json
from xml.etree import ElementTree as ET
NS='{http://www.tei-c.org/ns/1.0}'
CONVERTER_ID='ocd-ylt-retained-current-v1'
CONVERTER_VERSION='1'
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
def _convert(manifest):
    manifest.verify();p=json.loads(manifest.authority_path('profile').read_bytes())
    raw=manifest.authority_path('regenerated-tei').read_bytes()
    if sha256(raw).hexdigest()!=p['regenerated_tei_sha256']:raise ValueError('Freshly regenerated native baseline changed')
    source=json.loads(manifest.authority_path('primary-source').read_bytes())
    root=ET.fromstring(raw);root.remove(root.find(NS+'teiHeader'));root.insert(0,ET.fromstring(manifest.authority_path('header').read_bytes()))
    books=root.findall('./'+NS+'text/'+NS+'body/'+NS+'div')
    if len(books)!=66:raise ValueError('Retained book count differs')
    for i,(book,record) in enumerate(zip(books,source['books'],strict=True),1):
        if book.get('n')!=str(i) or book.findtext(NS+'head')!=record['name']:raise ValueError('Retained ordinal/head preimage differs')
        book.set('n',record['name'])
    ET.register_namespace('',NS[1:-1]);tei=ET.tostring(root,encoding='utf-8',xml_declaration=True)+b'\n'
    account=manifest.authority_path('regenerated-accountability').read_bytes()
    if sha256(account).hexdigest()!=p['regenerated_accountability_sha256']:raise ValueError('Retained source ledger changed')
    return {'content.tei.xml':tei,'source-accountability.json':account,
            'provenance.json':canonical(dict(work_id='ylt',source_manifest_sha256=manifest.sha256,scope=p['scope'],status='nonaccepted',freshly_regenerated_native_reused=True,permitted_body_delta='66 generated ordinal book n replaced by literal source names only')),
            'README.source.md':manifest.authority_path('source-readme').read_bytes(),
            'unresolved.jsonl':b''.join(canonical(q) for q in p['questions'])}
_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION
_convert.implementation_path=Path(__file__).resolve()
