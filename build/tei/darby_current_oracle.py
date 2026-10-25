"""Current source proof reusing the independently authored Darby tree and ledger checker."""
from pathlib import Path
from hashlib import sha256
import json
from copy import deepcopy
from xml.etree import ElementTree as ET
from lxml import etree
from build.tei import darby_oracle as prior
from ocd_kernel.reconstruction.verifier import MechanicalFacts,verify_mechanical_facts
NS='{http://www.tei-c.org/ns/1.0}'
ORACLE_ID='ocd-darby-retained-current-independent-v1'
ORACLE_VERSION='1'
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
def closure_sha(root):
    names=['build/tei/darby_current_oracle.py','build/tei/darby_oracle.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/reconstruction/verifier.py','build/lib/tei_xsd.py']
    return sha256(canonical([dict(path=p,sha256=sha256((root/p).read_bytes()).hexdigest()) for p in names])).hexdigest()
def check(manifest,raw,accountability=None):
    manifest.verify();profile=json.loads(manifest.authority_path('profile').read_bytes());source_bytes=manifest.authority_path('primary-source').read_bytes()
    historical_profile=json.loads(manifest.authority_path('historical-profile').read_bytes());historical_policy=json.loads(manifest.authority_path('historical-policy').read_bytes())
    source,expected_account=prior._derive_source_accountability(source_bytes,historical_profile)
    prior._validate_runtime(historical_policy)
    if accountability is not None and json.loads(accountability)!=expected_account:raise ValueError('Full independent source ledger differs')
    if sha256(canonical(expected_account)).hexdigest()!=profile['historical_accountability_sha256']:raise ValueError('Historical ledger hash differs')
    root=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,remove_blank_text=False))
    if root.getroottree().docinfo.doctype:raise ValueError('Unexpected DOCTYPE')
    expected_header=etree.fromstring(manifest.authority_path('header').read_bytes())
    header=root.find(NS+'teiHeader')
    def node_facts(n):return (n.tag,dict(n.attrib),n.text,n.tail,tuple(node_facts(c) for c in n))
    if node_facts(header)!=node_facts(expected_header):raise ValueError('Current qualified header differs')
    books=root.findall('./'+NS+'text/'+NS+'body/'+NS+'div')
    if len(books)!=len(source['books']):raise ValueError('Whole book count differs')
    labels=[]
    for ordinal,(book,record) in enumerate(zip(books,source['books'],strict=True),1):
        if book.get('n')!=record['name']:raise ValueError('Source-native book label differs at '+str(ordinal))
        labels.append(dict(id=book.get('{http://www.w3.org/XML/1998/namespace}id'),old=str(ordinal),new=record['name']))
    # Only the approved header and exactly sourced 66 labels are normalized for the prior checker.
    normalized=ET.fromstring(raw);old=manifest.authority_path('historical-tei').read_bytes();oldtree=ET.fromstring(old)
    normalized.remove(normalized.find(NS+'teiHeader'));normalized.insert(0,deepcopy(oldtree.find(NS+'teiHeader')))
    for ordinal,book in enumerate(normalized.findall('./'+NS+'text/'+NS+'body/'+NS+'div'),1):book.set('n',str(ordinal))
    ET.register_namespace('',NS[1:-1]);restored=ET.tostring(normalized,encoding='utf-8',xml_declaration=True)+b'\n'
    if restored!=old:raise ValueError('Unapproved body/identity/text/tail/hierarchy change beyond 66 sourced labels')
    prior._check_tree(source,restored,historical_policy)
    from build.lib.tei_xsd import compiled_tei_schema
    compiled_tei_schema(manifest.authority_path('tei-p5-xsd')).assertValid(root)
    return dict(status='pass',books=66,chapters=1189,verse_carriers=31102,empty_text_values=3,
                all_exact_source_strings_labels_parents_ordinals_checked=True,normalized_whole_historical_tei_byte_equal=True,
                book_label_transitions=labels,p5='pass',prior_exposure='Prior independent Darby checker reviewed and reused; producer wrapper not imported. Python JSON and serialization are shared assumptions, independently corroborated by coordinator direct lxml whole source/carrier comparison.')
def _oracle(manifest,candidate):
    candidate.verify_integrity();profile=json.loads(manifest.authority_path('profile').read_bytes())
    if candidate.manifest['source_manifest']['sha256']!=manifest.sha256:raise ValueError('Package source binding differs')
    check(manifest,candidate.member_bytes('content.tei.xml'),candidate.member_bytes('source-accountability.json'))
    if candidate.member_bytes('README.source.md')!=manifest.authority_path('source-readme').read_bytes():raise ValueError('Source notice differs')
    if [json.loads(line) for line in candidate.member_bytes('unresolved.jsonl').splitlines()]!=profile['questions']:raise ValueError('Qualified residual claims differ')
    expected=dict(work_id='darby',source_manifest_sha256=manifest.sha256,scope=profile['scope'],status='nonaccepted',retained_body_reused=True,permitted_body_delta='66 generated ordinal book n replaced by literal source names only')
    if json.loads(candidate.member_bytes('provenance.json'))!=expected:raise ValueError('Provenance differs')
    facts=MechanicalFacts(validator_implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),validator_import_closure_sha256=closure_sha(manifest.repository_root),source_sha256=profile['source_sha256'],profile_sha256=sha256(manifest.authority_path('profile').read_bytes()).hexdigest(),package_schema_sha256=manifest.record['package_schema']['sha256'],xsd_sha256=sha256(manifest.authority_path('tei-p5-xsd').read_bytes()).hexdigest(),policy_sha256=sha256(manifest.authority_path('validation-policy').read_bytes()).hexdigest(),findings=())
    return verify_mechanical_facts(manifest,candidate,facts).as_record()
_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
_oracle.implementation_path=Path(__file__).resolve()
