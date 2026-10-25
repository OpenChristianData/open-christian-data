"""Reuse the exact native Brainerd body; independently replay its original mapper."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from ocd_kernel.reconstruction.contract import SourceManifest
CONVERTER_ID='ocd-brainerd-complete-retained-current-v1'
CONVERTER_VERSION='1'
def canonical(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
def load_legacy(root):
    p=root/'sources/structured-text/edwards-life-of-brainerd/brainerd_converter.py'
    spec=importlib.util.spec_from_file_location('brainerd_readonly_original_mapper',p)
    if spec is None or spec.loader is None:raise ImportError(p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def _convert(manifest):
    manifest.verify();profile=json.loads(manifest.authority_path('profile').read_bytes())
    original=SourceManifest.load(manifest.authority_path('legacy-source-manifest'),repository_root=manifest.repository_root)
    reproduced=load_legacy(manifest.repository_root)._convert(original)
    raw=manifest.authority_path('historical-native-candidate').read_bytes()
    if reproduced['content.tei.xml']!=raw:raise ValueError('Original whole native candidate replay differs')
    ledger=manifest.authority_path('historical-accountability').read_bytes()
    if reproduced['source-accountability.json']!=ledger:raise ValueError('Original native source-accounting replay differs')
    start=raw.index(b'<teiHeader>');end=raw.index(b'</teiHeader>')+len(b'</teiHeader>')
    current=raw[:start]+profile['header_xml'].encode()+raw[end:]
    if current.split(b'</teiHeader>',1)[1]!=raw.split(b'</teiHeader>',1)[1]:raise ValueError('Header renewal altered text bytes')
    return {'content.tei.xml':current,'source-accountability.json':ledger,'provenance.json':canonical(dict(work_id=profile['work_id'],source_manifest_sha256=manifest.sha256,scope=profile['scope'],body_unchanged=True,status='nonaccepted',historical_candidate_sha256=sha256(raw).hexdigest())), 'README.source.md':manifest.authority_path('source-readme').read_bytes(),'unresolved.jsonl':b''.join(canonical(q) for q in profile['questions'])}
_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION
_convert.implementation_path=Path(__file__).resolve()
