"""Independent lexical/semantic source oracle with exact header-only restoration."""
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
from lxml import etree
from build.tei.bcp_1662_oracle import _read_sources, _derive_blocks, _verify_semantic_tei, _multi_source_digest

ORACLE_ID='ocd-bcp1662-independent-complete-retained-current-v1'
ORACLE_VERSION='1'
NS='{http://www.tei-c.org/ns/1.0}'

def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()

def closure_sha(root):
    paths=['build/tei/bcp1662_current_oracle.py','build/tei/bcp_1662_oracle.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/reconstruction/verifier.py','ocd_kernel/reconstruction/__init__.py','ocd_kernel/tei/validate.py','ocd_kernel/lib/storage_topology.py']
    return sha256(canonical([dict(path=p,sha256=sha256((root/p).read_bytes()).hexdigest()) for p in sorted(paths)])).hexdigest()

def fingerprint(n):
    return n.tag,tuple(n.attrib.items()),n.text,n.tail,tuple(fingerprint(c) for c in n)

class _RestoredContent:
    def __init__(self,raw):
        self.raw=raw
    def member_bytes(self,name):
        if name!='content.tei.xml':
            raise ValueError('Unexpected historical-check member')
        return self.raw

def check(manifest,raw):
    manifest.verify()
    profile=json.loads(manifest.authority_path('profile').read_bytes())
    original=manifest.authority_path('historical-native-candidate').read_bytes()
    doc=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
    if doc.tag!=NS+'TEI' or doc.attrib or [n.tag for n in doc]!=[NS+'teiHeader',NS+'text']:
        raise ValueError('BCP1662 exact namespace/envelope differs')
    if fingerprint(doc[0])!=fingerprint(etree.fromstring(profile['header_xml'].encode())):
        raise ValueError('Qualified current header differs')
    opening=b'<ns0:teiHeader'; closing=b'</ns0:teiHeader>'
    if raw.count(opening)!=1 or raw.count(closing)!=1:
        raise ValueError('Current exact header envelope differs')
    start=raw.index(opening); end=raw.index(closing)+len(closing)
    old_start=original.index(opening); old_end=original.index(closing)+len(closing)
    restored=raw[:start]+original[old_start:old_end]+raw[end:]
    for row in profile['supported_shape_aliases']:
        after=row['after'].encode(); before=row['before'].encode()
        if restored.count(after)!=row['count'] or before in restored:
            raise ValueError('Supported shape alias cardinality/identity differs')
        restored=restored.replace(after,before)
    if restored!=original:
        raise ValueError('Restoring only qualified header and reviewed aliases does not recover exact whole historical TEI')
    native_profile=json.loads(manifest.authority_path('reconstruction-profile').read_bytes())
    items,kinds=_read_sources(manifest,native_profile)
    blocks=_derive_blocks(items,kinds,native_profile)
    _verify_semantic_tei(manifest,_RestoredContent(restored),native_profile,items,blocks)
    ledger=json.loads(manifest.authority_path('historical-accountability').read_bytes())
    clean=[{k:v for k,v in i.items() if not k.startswith('_')} for i in items]
    if ledger['crosswalk']!=clean:
        raise ValueError('Whole original ledger differs from independent ordered source observations')
    etree.XMLSchema(etree.parse(str(manifest.authority_path('tei-p5-xsd')))).assertValid(doc)
    return dict(status='pass',members=25,observations=len(items),speeches=len(doc.findall('.//'+NS+'sp')),blocks=len(blocks),observances=90,collects=85,exact_original_byte_restoration=True,p5='pass',source_native_scope='All25 textual members; five retained404 responses accounted outside body; partial printed scope remains',independence='Original separate HTML source parser and semantic oracle; producer not imported. Both readers share CPython HTMLParser parsing assumptions.')

def _oracle(manifest,candidate):
    candidate.verify_integrity()
    if candidate.manifest['source_manifest']['sha256']!=manifest.sha256 or manifest.record['validator']['import_closure_sha256']!=closure_sha(manifest.repository_root):
        raise ValueError('Current manifest/independent closure differs')
    facts=check(manifest,candidate.member_bytes('content.tei.xml'))
    profile=json.loads(manifest.authority_path('profile').read_bytes())
    if candidate.member_bytes('source-accountability.json')!=manifest.authority_path('historical-accountability').read_bytes() or candidate.member_bytes('README.source.md')!=manifest.authority_path('source-readme').read_bytes():
        raise ValueError('Complete ledger/visible credit differs')
    if [json.loads(x) for x in candidate.member_bytes('unresolved.jsonl').splitlines()]!=profile['questions']:
        raise ValueError('Unresolved qualifications differ')
    expected=dict(work_id='bcp-1662',source_manifest_sha256=manifest.sha256,scope=profile['scope'],historical_candidate_sha256=sha256(manifest.authority_path('historical-native-candidate').read_bytes()).hexdigest(),body_reuse='Exact fresh original reconstruction replay; reviewed reversible heading/break/role aliases and qualified header only',status='nonaccepted')
    if json.loads(candidate.member_bytes('provenance.json'))!=expected:
        raise ValueError('Current provenance differs')
    result=dict(status='pass',oracle_id=ORACLE_ID,oracle_version=ORACLE_VERSION,implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),import_closure_sha256=closure_sha(manifest.repository_root),runtime=f'{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})',source_manifest_sha256=manifest.sha256,candidate_sha256=candidate.sha256,profile_sha256=sha256(manifest.authority_path('profile').read_bytes()).hexdigest(),package_schema_sha256=manifest.record['package_schema']['sha256'],source_sha256=_multi_source_digest(manifest),xsd_sha256=sha256(manifest.authority_path('tei-p5-xsd').read_bytes()).hexdigest(),policy_sha256=sha256(manifest.authority_path('validation-policy-current').read_bytes()).hexdigest(),findings=[])
    result['result_sha256']=sha256(canonical(result)).hexdigest()
    return result

_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
_oracle.implementation_path=Path(__file__).resolve()
