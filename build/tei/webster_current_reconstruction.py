"""Reuse the exact complete retained Webster native body with qualified scaffolding."""
from hashlib import sha256
import json
from pathlib import Path
from xml.sax.saxutils import escape
from build.tei.webster_reconstruction import convert
CONVERTER_ID='ocd-webster-complete-retained-current-v1'
CONVERTER_VERSION='1'
def canonical(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
def _convert(manifest):
    manifest.verify();profile=json.loads(manifest.authority_path('profile').read_bytes())
    original=manifest.authority_path('rederived-native-baseline').read_bytes()
    ledger=manifest.authority_path('rederived-accountability').read_bytes()
    reproduced=convert(manifest)
    if reproduced['content.tei.xml']!=original or reproduced['source-accountability.json']!=ledger:raise ValueError('Exact original complete source-derived body/accounting replay differs')
    current=original
    for row in profile['book_label_revisions']:
        old=f'<div type="book" n="{row["old_n"]}" xml:id="{row["id"]}">'.encode()
        new=f'<div type="book" n="{escape(row["source_name"],{chr(34): "&quot;"})}" xml:id="{row["id"]}">'.encode()
        if current.count(old)!=1:raise ValueError('Generated book-label preimage differs')
        current=current.replace(old,new)
    start=current.index(b'<teiHeader>');end=current.index(b'</teiHeader>')+len(b'</teiHeader>')
    current=current[:start]+profile['header_xml'].encode()+current[end:]
    return {'content.tei.xml':current,'source-accountability.json':ledger,'provenance.json':canonical(dict(work_id='webster',scope=profile['scope'],source_manifest_sha256=manifest.sha256,rederived_baseline_sha256=sha256(original).hexdigest(),book_label_revisions=profile['book_label_revisions'],status='nonaccepted')),'README.source.md':manifest.authority_path('source-readme').read_bytes(),'unresolved.jsonl':b''.join(canonical(q) for q in profile['questions'])}
_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION
_convert.implementation_path=Path(__file__).resolve()
