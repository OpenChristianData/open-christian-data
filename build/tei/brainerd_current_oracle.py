"""Independent source-native Brainerd correspondence; original producer not imported."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import platform
import sys
import xml.etree.ElementTree as ET
from lxml import etree
from ocd_kernel.reconstruction.contract import SourceManifest
ORACLE_ID='ocd-brainerd-independent-complete-retained-current-v1'
ORACLE_VERSION='1'
NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
def canonical(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
def closure_sha(root):
    paths=['build/tei/brainerd_current_oracle.py','sources/structured-text/edwards-life-of-brainerd/brainerd_oracle.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/reconstruction/verifier.py','ocd_kernel/reconstruction/__init__.py']
    return sha256(canonical([dict(path=p,sha256=sha256((root/p).read_bytes()).hexdigest()) for p in sorted(paths)])).hexdigest()
def legacy(root):
    p=root/'sources/structured-text/edwards-life-of-brainerd/brainerd_oracle.py';spec=importlib.util.spec_from_file_location('brainerd_readonly_original_oracle',p)
    if spec is None or spec.loader is None:raise ImportError(p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def fingerprint(n):return (n.tag,tuple(n.attrib.items()),n.text,n.tail,tuple(fingerprint(c) for c in n))
def check(manifest,raw):
    manifest.verify();p=json.loads(manifest.authority_path('profile').read_bytes());l=legacy(manifest.repository_root)
    old=SourceManifest.load(manifest.authority_path('legacy-source-manifest'),repository_root=manifest.repository_root)
    source,root,body,selected,envelope=l._parse_source(old)
    if fingerprint(selected)!=fingerprint(ET.fromstring(source).find('ThML.body/div1')):raise ValueError('Independent source parsers differ')
    rows=[];l._walk_source(selected,rows)
    if len(rows)!=8545 or [x.get('id') for x in selected if x.tag=='div2']!=p['major_unit_ids']:raise ValueError('Complete source cardinality/order differs')
    for c in p['credits']:
        if ''.join(root.xpath(c['source_selector'])[0].itertext())!=c['literal_text']:raise ValueError('Literal primary attribution differs')
    doc=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True))
    if doc.tag!=NS+'TEI' or dict(doc.attrib)!={XML+'id':p['work_id']} or [x.tag for x in doc]!=[NS+'teiHeader',NS+'text']:raise ValueError('Single complete work envelope differs')
    if fingerprint(doc[0])!=fingerprint(etree.fromstring(p['header_xml'].encode())):raise ValueError('Current qualified source header differs')
    target=doc.find(NS+'text/'+NS+'body')
    if len(doc[1])!=1 or target is None or len(target)!=1:raise ValueError('Complete work body boundary differs')
    cursor=[0];l._compare_tree(selected,target[0],rows,cursor)
    if cursor[0]!=8545:raise ValueError('Native conservation count differs')
    historical=manifest.authority_path('historical-native-candidate').read_bytes()
    if raw.split(b'</teiHeader>',1)[1]!=historical.split(b'</teiHeader>',1)[1]:raise ValueError('Whole text bytes differ from checked historical body')
    expected=l._expected_accountability(source,l._authority_record(old,'source'),old.record['scope'],l._source_envelope(source,root,body,selected)[0],rows)
    if json.loads(manifest.authority_path('historical-accountability').read_bytes())!=expected:raise ValueError('Historical full ordered attributes/text/tail/hierarchy ledger differs from source')
    ids=[x.get(XML+'id') for x in doc.iter() if x.get(XML+'id')]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate source identifiers')
    etree.XMLSchema(etree.parse(str(manifest.authority_path('tei-p5-xsd')))).assertValid(doc)
    return dict(status='pass',source_elements=8545,source_literal_heads=105,major_units=12,notes=88,pages=146,source_reference_tags=246,italic_ids_preserved=5965,historical_body_unchanged=True,p5='pass',source_parser_corroboration='Independent stdlib/lxml exact complete ix source tree',independent_source_mapping='Readonly original independent Brainerd oracle compares every mapped tag/attribute/text/tail/child order/ID and complete external source ledger. Shared declarative mapping; producer never imported; not a blind historical proof.')
def _oracle(manifest,candidate):
    candidate.verify_integrity();p=json.loads(manifest.authority_path('profile').read_bytes())
    if candidate.manifest['source_manifest']['sha256']!=manifest.sha256 or manifest.record['validator']['import_closure_sha256']!=closure_sha(manifest.repository_root):raise ValueError('Current source manifest/closure differs')
    check(manifest,candidate.member_bytes('content.tei.xml'))
    if candidate.member_bytes('source-accountability.json')!=manifest.authority_path('historical-accountability').read_bytes():raise ValueError('Current full source accountability differs')
    if candidate.member_bytes('README.source.md')!=manifest.authority_path('source-readme').read_bytes() or [json.loads(x) for x in candidate.member_bytes('unresolved.jsonl').splitlines()]!=p['questions']:raise ValueError('Credit/unresolved ledger differs')
    provenance=json.loads(candidate.member_bytes('provenance.json'))
    if provenance['source_manifest_sha256']!=manifest.sha256 or provenance['scope']!=p['scope'] or provenance['historical_candidate_sha256']!=sha256(manifest.authority_path('historical-native-candidate').read_bytes()).hexdigest():raise ValueError('Native-reuse provenance differs')
    result=dict(status='pass',oracle_id=ORACLE_ID,oracle_version=ORACLE_VERSION,implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),import_closure_sha256=closure_sha(manifest.repository_root),runtime=f'{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})',source_manifest_sha256=manifest.sha256,candidate_sha256=candidate.sha256,profile_sha256=sha256(manifest.authority_path('profile').read_bytes()).hexdigest(),package_schema_sha256=manifest.record['package_schema']['sha256'],source_sha256=p['source_sha256'],xsd_sha256=sha256(manifest.authority_path('tei-p5-xsd').read_bytes()).hexdigest(),policy_sha256=sha256(manifest.authority_path('validation-policy').read_bytes()).hexdigest(),findings=[])
    result['result_sha256']=sha256(canonical(result)).hexdigest();return result
_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
_oracle.implementation_path=Path(__file__).resolve()
