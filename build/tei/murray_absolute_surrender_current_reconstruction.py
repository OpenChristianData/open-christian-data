"""Renew the proven complete Murray electronic witness without rewriting its TEI."""
from pathlib import Path
from hashlib import sha256
from lxml import etree
import json
from build.tei import murray_absolute_surrender_reconstruction as legacy
from ocd_kernel.reconstruction.contract import SourceManifest
TEI_NS=legacy.TEI_NS
NS='{'+TEI_NS+'}'
CONVERTER_ID='ocd-murray-whole-current-v1'
CONVERTER_VERSION='1'
canonical=legacy._canonical

def _convert(manifest):
    manifest.verify()
    source=manifest.authority_path('primary-source').read_bytes()
    profile=json.loads(manifest.authority_path('profile').read_bytes())
    old_profile=json.loads(manifest.authority_path('historical-profile').read_bytes())
    sr=legacy._parse_source(source);body=sr.find('ThML.body')
    features,events=legacy._validate_profile(source,old_profile,sr,body)
    ordinal={n:i for i,n in enumerate((n for n in sr.iter() if isinstance(n.tag,str)),1)}
    root=legacy._element('TEI',{'xml:id':profile['work_id']})
    root.append(legacy._header(legacy._metadata_authority_record(sr),sha256(source).hexdigest()))
    text=legacy._element('text',{'xml:id':profile['work_id']+'-text'})
    front=legacy._element('front');middle=legacy._element('body');back=legacy._element('back')
    for n in body:
        out=legacy._convert_body_element(n,ordinal);out.tail=n.tail
        (front if n.get('id')=='i' else back if n.get('id')=='xi' else middle).append(out)
    legacy._append_text(text,body.text)
    text.extend([front,middle,back]);text.tail=body.tail;root.append(text)
    raw=etree.tostring(root,encoding='UTF-8',xml_declaration=True,pretty_print=False)
    account=canonical(legacy._source_accountability(features,events,old_profile))
    if sha256(raw).hexdigest()!=profile['historical_tei_sha256']:raise ValueError('proven historical whole TEI did not replay exactly')
    if sha256(account).hexdigest()!=profile['historical_accountability_sha256']:raise ValueError('proven historical whole accountability did not replay exactly')
    return {'content.tei.xml':raw,'source-accountability.json':account,'provenance.json':canonical(dict(work_id=profile['work_id'],source_manifest_sha256=manifest.sha256,scope=profile['scope'],status='nonaccepted',native_reconstruction=True,historical_tei_reproduced_unchanged=True,legacy_config_conflict_retained_not_adopted=True)),'README.source.md':manifest.authority_path('source-readme').read_bytes(),'unresolved.jsonl':b''.join(canonical(q) for q in profile['questions'])}
_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION
_convert.implementation_path=Path(__file__).resolve()
