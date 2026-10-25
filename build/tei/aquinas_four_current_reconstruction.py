"""Reproduce the retained Aquinas body and apply only an explicit current header."""
from pathlib import Path
from hashlib import sha256
import json
from lxml import etree, html
from ocd_kernel.library._common import io_path
CONVERTER_ID='ocd-aquinas-four-retained-current-v1'
CONVERTER_VERSION='1'
NS='{http://www.tei-c.org/ns/1.0}'
def canonical(value): return (json.dumps(value,ensure_ascii=False,separators=(',',':'),sort_keys=True)+'\n').encode()
def _convert(manifest):
    manifest.verify(); profile=json.loads(manifest.authority_path('profile').read_bytes())
    original=manifest.authority_path('historical-candidate').read_bytes()
    if sha256(original).hexdigest()!=profile['historical_candidate_sha256']:raise ValueError('Reviewed physical historical candidate changed')
    accounting=json.loads(manifest.authority_path('historical-accounting').read_bytes())
    for key in ('validation','tei_relaxng_sha256','candidate_bytes','candidate_sha256'):accounting.pop(key,None)
    start=original.index(b'<teiHeader>'); end=original.index(b'</teiHeader>')+len(b'</teiHeader>')
    header=manifest.authority_path('fresh-header').read_bytes()
    raw=original[:start]+header+original[end:]
    if raw.split(b'</teiHeader>',1)[1]!=original.split(b'</teiHeader>',1)[1]:raise ValueError('Renewal changed source-proven body')
    ledger=[]
    for part in profile['components']:
        source=html.fromstring(manifest.authority_path('source-html-'+str(part['position'])).read_bytes()); nodes=[n for n in source.iter() if isinstance(n.tag,str)]; ordinal={n:i for i,n in enumerate(nodes,1)}
        for n in nodes:
            selected=n
            while selected.getparent() is not None and selected.getparent().tag!='body':selected=selected.getparent()
            content=selected.getparent() is not None and selected.getparent().tag=='body' and selected.tag not in ('header','footer')
            ledger.append(dict(component=part['code'],ordinal=ordinal[n],parent=ordinal.get(n.getparent()),tag=n.tag,attributes=list(n.attrib.items()),text=n.text,tail=n.tail,disposition='book-content' if content else 'retained-provider-or-document-context',source_unit_id=selected.get('id') if content else None,target_unit_id='pg'+str(part['pg_id'])+'-'+selected.get('id') if content else None))
    return {'content.tei.xml':raw,'source-accountability.json':canonical(dict(contract='ocd-aquinas-four-full-html-accountability-v1',nodes=ledger,source_unit_outer_tails='Original HTML layout framing retained here, not appended to readable semantic unit; direct text and all inline tails conserved.',source_style='Literal original layout style retained here; no interpretation of margin spacing as authored wording.',covers='Four exact acquisition package cover PNGs retained and hash-bound as support context; not intrinsic book figures in selected HTML units.',historical_semantic_accounting=accounting)), 'provenance.json':canonical(dict(work_id=profile['work_id'],source_manifest_sha256=manifest.sha256,scope=profile['scope'],status='nonaccepted',historical_body_reproduced_unchanged=True,header_only_renewal=True)), 'README.source.md':manifest.authority_path('source-readme').read_bytes(),'unresolved.jsonl':b''.join(canonical(q) for q in profile['questions'])}
_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION
_convert.implementation_path=Path(__file__).resolve()
