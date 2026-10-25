"""Renew one complete retained partial BCP1662 witness without body changes."""
from hashlib import sha256
import json
from pathlib import Path
from build.tei.bcp_1662_reconstruction import _inventory, _group_blocks, _build_tei

CONVERTER_ID='ocd-bcp1662-complete-retained-current-v1'
CONVERTER_VERSION='1'

def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()

def _convert(manifest):
    manifest.verify()
    profile=json.loads(manifest.authority_path('profile').read_bytes())
    original=manifest.authority_path('historical-native-candidate').read_bytes()
    native_profile=json.loads(manifest.authority_path('reconstruction-profile').read_bytes())
    records,kinds=_inventory(manifest,native_profile)
    replay=_build_tei(manifest,native_profile,_group_blocks(records,kinds,native_profile))
    if replay!=original:
        raise ValueError('Fresh original native source reconstruction differs from historical whole TEI')
    opening=b'<ns0:teiHeader>'
    closing=b'</ns0:teiHeader>'
    if original.count(opening)!=1 or original.count(closing)!=1:
        raise ValueError('Exact historical header envelope differs')
    start=original.index(opening); end=original.index(closing)+len(closing)
    adapted=original
    for row in profile['supported_shape_aliases']:
        before=row['before'].encode(); after=row['after'].encode()
        if adapted.count(before)!=row['count'] or after in adapted:
            raise ValueError('Source-backed alias preimage differs')
        adapted=adapted.replace(before,after)
    start=adapted.index(opening); end=adapted.index(closing)+len(closing)
    renewed=adapted[:start]+profile['header_xml'].encode()+adapted[end:]
    return {'content.tei.xml':renewed,'source-accountability.json':manifest.authority_path('historical-accountability').read_bytes(),
        'provenance.json':canonical(dict(work_id='bcp-1662',source_manifest_sha256=manifest.sha256,scope=profile['scope'],historical_candidate_sha256=sha256(original).hexdigest(),body_reuse='Exact fresh original reconstruction replay; reviewed reversible heading/break/role aliases and qualified header only',status='nonaccepted')),
        'README.source.md':manifest.authority_path('source-readme').read_bytes(),
        'unresolved.jsonl':b''.join(canonical(q) for q in profile['questions'])}

_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION
_convert.implementation_path=Path(__file__).resolve()
