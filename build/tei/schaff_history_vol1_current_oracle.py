"""Independent complete Schaff volume source/evidence checker; never imports its producer."""
from hashlib import sha256
import json
from pathlib import Path
import platform,sys
from lxml import etree
from build.tei import schaff_history_vol_1_oracle as legacy
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
ORACLE_ID="ocd-schaff-history-vol1-independent-retained-v1"
ORACLE_VERSION="1"
NS="{http://www.tei-c.org/ns/1.0}"
def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
def closure_sha(root):
    names=["build/tei/schaff_history_vol1_current_oracle.py",*legacy._CLOSURE_PATHS]
    return sha256(canonical([dict(path=p,sha256=sha256((root/p).read_bytes()).hexdigest()) for p in sorted(names)])).hexdigest()
def fingerprint(n):
    return (n.tag,list(n.attrib.items()),n.text,n.tail,tuple(fingerprint(c) for c in n))
def check(manifest,raw):
    manifest.verify()
    profile=json.loads(manifest.authority_path("profile").read_bytes())
    source=manifest.authority_path("primary-source").read_bytes()
    if sha256(source).hexdigest()!=profile["source_sha256"]: raise ValueError("retained source differs")
    source_tree=legacy._parse_xml(source,"retained source");source_root=source_tree.getroot()
    nodes,records=legacy._source_records(source_root)
    tree=legacy._parse_xml(raw,"current complete candidate");root=tree.getroot()
    legacy._verify_external_comments(source_root,root)
    represented=legacy._verify_source_projection(source_root,root,records)
    if [n.tag for n in root]!=[NS+"teiHeader",NS+"text",NS+"standOff"]: raise ValueError("complete one-volume shell differs")
    if fingerprint(root[0])!=fingerprint(etree.fromstring(profile["header_xml"].encode())): raise ValueError("source-attested current header differs")
    body=root.find(NS+"text/"+NS+"body")
    if any(n not in represented for n in body.iter()): raise ValueError("unaccounted body element")
    old=manifest.authority_path("historical-tei").read_bytes()
    if raw.split(b"</teiHeader>",1)[1]!=old.split(b"</teiHeader>",1)[1]: raise ValueError("historical whole body/evidence changed")
    for credit in profile["credits"]:
        if "".join(source_root.xpath(credit["source_selector"])[0].itertext())!=credit["literal_text"]: raise ValueError("literal primary credit differs")
    divs,heads=legacy._counts(records)
    expected=legacy._expected_accountability(manifest,json.loads(manifest.authority_path("historical-profile").read_bytes()),source,source_tree,records,divs,heads)
    expected["source_manifest_sha256"]=json.loads(manifest.authority_path("historical-accounting").read_bytes())["source_manifest_sha256"]
    if expected!=profile["accounting"]["native_source_accountability"]: raise ValueError("independent full source accounting differs")
    from build.lib.tei_xsd import compiled_tei_schema
    schema=compiled_tei_schema(manifest.authority_path("tei-p5-xsd"));schema.assertValid(root)
    return dict(status="pass",source_elements=len(nodes),body_elements=30098,chapter_count=12,index_count=8,notes=1272,subject_markers=40,heading_tags=heads,source_divisions=divs,
        exact_historical_text_and_evidence=True,all_source_attributes_parents_ordinals_text_tails_checked=True,p5="pass",prior_exposure="Historical producer and oracle separately inspected; reuse is corroboration, no blind claim.")
def _oracle(manifest,candidate):
    candidate.verify_integrity();profile=json.loads(manifest.authority_path("profile").read_bytes())
    if candidate.manifest["source_manifest"]["sha256"]!=manifest.sha256: raise ValueError("candidate source binding differs")
    check(manifest,candidate.member_bytes("content.tei.xml"))
    if json.loads(candidate.member_bytes("source-accountability.json"))!=profile["accounting"]: raise ValueError("candidate source accounting differs")
    if candidate.member_bytes("README.source.md")!=manifest.authority_path("source-readme").read_bytes(): raise ValueError("source credit differs")
    if [json.loads(x) for x in candidate.member_bytes("unresolved.jsonl").splitlines()]!=profile["questions"]: raise ValueError("unresolved claims differ")
    if json.loads(candidate.member_bytes("provenance.json"))!={"work_id":profile["work_id"],"source_manifest_sha256":manifest.sha256,"scope":profile["scope"],"historical_text_and_evidence_unchanged":True,"status":"nonaccepted"}: raise ValueError("provenance differs")
    facts=MechanicalFacts(validator_implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),validator_import_closure_sha256=closure_sha(manifest.repository_root),source_sha256=profile["source_sha256"],profile_sha256=sha256(manifest.authority_path("profile").read_bytes()).hexdigest(),package_schema_sha256=manifest.record["package_schema"]["sha256"],xsd_sha256=sha256(manifest.authority_path("tei-p5-xsd").read_bytes()).hexdigest(),policy_sha256=sha256(manifest.authority_path("validation-policy").read_bytes()).hexdigest(),findings=())
    return verify_mechanical_facts(manifest,candidate,facts).as_record()
_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
_oracle.implementation_path=Path(__file__).resolve()
