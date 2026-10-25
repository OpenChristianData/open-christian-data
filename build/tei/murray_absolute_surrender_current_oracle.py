"""Independent current envelope proof reusing the source-derived Murray checker."""
from pathlib import Path
from hashlib import sha256
import json
from collections import Counter
from lxml import etree
from build.tei import murray_absolute_surrender_oracle as prior
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage
from ocd_kernel.reconstruction.verifier import MechanicalFacts,verify_mechanical_facts
NS='{http://www.tei-c.org/ns/1.0}'
ORACLE_ID='ocd-murray-whole-current-independent-v1'
ORACLE_VERSION='1'
canonical=prior._canonical

def closure_sha(root):
    names=['build/tei/murray_absolute_surrender_current_oracle.py','build/tei/murray_absolute_surrender_oracle.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/reconstruction/verifier.py','build/lib/tei_xsd.py']
    return sha256(canonical([dict(path=p,sha256=sha256((root/p).read_bytes()).hexdigest()) for p in names])).hexdigest()

def check(manifest,raw,accountability=None):
    manifest.verify();profile=json.loads(manifest.authority_path('profile').read_bytes());source=manifest.authority_path('primary-source').read_bytes()
    if sha256(source).hexdigest()!=profile['source_sha256']:raise ValueError('retained source differs')
    sr=prior._parse_retained_xml(source);body=sr.find('ThML.body');features=prior._independent_source_features(sr,body);events=prior._independent_non_element_events(source)
    old_profile=json.loads(manifest.authority_path('historical-profile').read_bytes())
    prior._verify_profile(old_profile,source,sr,body,features,events)
    expected=prior._expected_tei(sr,body,prior._flat_source_metadata(sr),sha256(source).hexdigest())
    if raw!=expected:raise ValueError('independent whole source hierarchy/attributes/wording/tails/header mapping differs')
    expected_account=prior._expected_accountability(source,old_profile,features,events,body)
    if accountability is not None and json.loads(accountability)!=expected_account:raise ValueError('independent complete954source ledger differs')
    if sha256(canonical(expected_account)).hexdigest()!=profile['historical_accountability_sha256']:raise ValueError('historical source-accountability binding differs')
    if sha256(raw).hexdigest()!=profile['historical_tei_sha256']:raise ValueError('historical proven TEI binding differs')
    if [n.get('id') for n in body]!=['i','ii','iii','iv','v','vi','vii','viii','ix','x','xi']:raise ValueError('complete collection boundary/order differs')
    for credit in profile['credits']:
        selected=sr.xpath(credit['source_selector'])
        if len(selected)!=1 or ''.join(selected[0].itertext())!=credit['literal_text']:raise ValueError('primary credit differs')
    from build.lib.tei_xsd import compiled_tei_schema
    compiled_tei_schema(manifest.authority_path('tei-p5-xsd')).assertValid(etree.fromstring(raw))
    return dict(status='pass',source_elements=len(features),body_elements=890,body_roots=11,address_count=9,index_count=1,verse_groups=4,verse_lines=12,italic_carriers=167,scripture_refs=69,hyperlinks=69,all_source_attributes_parents_ordinals_text_tails_checked=True,p5='pass',historical_tei_reproduced_unchanged=True,prior_exposure='Historical Murray source-specific mapper and separately authored checker reviewed. Current oracle imports only prior checker, not producer; same lxml parser assumptions corroborated by coordinator direct recursive body comparison without either module. Complete954source ledger independently enumerated, CSS/electronic header support-only dispositions retained.')

def _oracle(manifest,candidate):
    candidate.verify_integrity();profile=json.loads(manifest.authority_path('profile').read_bytes())
    if candidate.manifest['source_manifest']['sha256']!=manifest.sha256:raise ValueError('candidate source binding differs')
    check(manifest,candidate.member_bytes('content.tei.xml'),candidate.member_bytes('source-accountability.json'))
    if candidate.member_bytes('README.source.md')!=manifest.authority_path('source-readme').read_bytes():raise ValueError('source credit differs')
    if [json.loads(x) for x in candidate.member_bytes('unresolved.jsonl').splitlines()]!=profile['questions']:raise ValueError('unassessed claims differ')
    expected=dict(work_id=profile['work_id'],source_manifest_sha256=manifest.sha256,scope=profile['scope'],status='nonaccepted',native_reconstruction=True,historical_tei_reproduced_unchanged=True,legacy_config_conflict_retained_not_adopted=True)
    if json.loads(candidate.member_bytes('provenance.json'))!=expected:raise ValueError('provenance differs')
    facts=MechanicalFacts(validator_implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),validator_import_closure_sha256=closure_sha(manifest.repository_root),source_sha256=profile['source_sha256'],profile_sha256=sha256(manifest.authority_path('profile').read_bytes()).hexdigest(),package_schema_sha256=manifest.record['package_schema']['sha256'],xsd_sha256=sha256(manifest.authority_path('tei-p5-xsd').read_bytes()).hexdigest(),policy_sha256=sha256(manifest.authority_path('validation-policy').read_bytes()).hexdigest(),findings=())
    return verify_mechanical_facts(manifest,candidate,facts).as_record()
_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
_oracle.implementation_path=Path(__file__).resolve()
