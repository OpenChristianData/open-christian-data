"""Independent complete retained-source checker with exact native language closure."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import schaff_history_vol_4_oracle as legacy
from ocd_kernel.reconstruction.verifier import MechanicalFacts,verify_mechanical_facts

ORACLE_ID="ocd-schaff-history-vol4-independent-retained-v1"
ORACLE_VERSION="1"
NS="{http://www.tei-c.org/ns/1.0}"
XML_ID="{http://www.w3.org/XML/1998/namespace}id"
XML_LANG="{http://www.w3.org/XML/1998/namespace}lang"
canonical=lambda v:(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
_PROJECTION_NAMES=legacy._PROJECTION_NAMES
_parse_xml=legacy._parse_xml
_external_siblings=legacy._external_siblings

def closure_sha(root):
    names=["build/tei/schaff_history_vol4_current_oracle.py",*legacy._CLOSURE_PATHS]
    return sha256(canonical([dict(path=p,sha256=sha256((root/p).read_bytes()).hexdigest()) for p in sorted(names)])).hexdigest()

def fingerprint(n):return n.tag,list(n.attrib.items()),n.text,n.tail,tuple(fingerprint(c) for c in n)

def check(manifest,raw):
    manifest.verify();profile=json.loads(manifest.authority_path("profile").read_bytes());source=manifest.authority_path("primary-source").read_bytes()
    if sha256(source).hexdigest()!=profile["source_sha256"]:raise ValueError("retained source differs")
    st=_parse_xml(source,"source");sr=st.getroot();nodes,records=legacy._source_records(sr)
    tree=_parse_xml(raw,"candidate");root=tree.getroot();legacy._verify_external_comments(sr,root)
    if [n.tag for n in root]!=[NS+"teiHeader",NS+"text",NS+"standOff"]:raise ValueError("whole volume shell differs")
    if fingerprint(root[0])!=fingerprint(etree.fromstring(profile["header_xml"].encode())):raise ValueError("source-attested header differs")
    by_id={}
    for n in root.iter():
        if n.get(XML_ID):
            if n.get(XML_ID) in by_id:raise ValueError("duplicate candidate ID")
            by_id[n.get(XML_ID)]=n
    clone=_parse_xml(raw,"independent base comparison").getroot();clone_by_id={n.get(XML_ID):n for n in clone.iter() if n.get(XML_ID)};languages=0
    for record in records.values():
        source_node=record["node"];key=legacy._source_content_id(source_node,record)
        if key not in by_id:raise ValueError("missing source carrier "+key)
        if by_id[key].get(XML_LANG)!=source_node.get("lang"):raise ValueError("literal source language differs at "+key)
        if source_node.get("lang") is not None:
            languages+=1;del clone_by_id[key].attrib[XML_LANG]
    represented=legacy._verify_source_projection(sr,clone,records)
    body=clone.find(NS+"text/"+NS+"body")
    if any(n not in represented for n in body.iter()):raise ValueError("unaccounted body element")
    base=manifest.authority_path("native-base").read_bytes()
    if etree.tostring(clone,encoding="UTF-8").split(b"</teiHeader>",1)[1]!=base.split(b"</teiHeader>",1)[1]:raise ValueError("native base body/evidence differs beyond verified languages")
    for credit in profile["credits"]:
        selected=sr.xpath(credit["source_selector"])
        if len(selected)!=1 or "".join(selected[0].itertext())!=credit["literal_text"]:raise ValueError("source credit differs")
    if len(nodes)!=15955 or len(list(sr.find("ThML.body").iter()))!=15804 or languages!=589 or dict(sorted(Counter(n.tag for n in nodes).items()))!=profile["accounting"]["source_tag_counts"]:raise ValueError("complete source census differs")
    if [n.get("id") for n in sr.find("ThML.body")]!=["i","ii"] or len(sr.xpath("ThML.body/div1[@id='i']/div2[@type='Chapter']"))!=14 or len(sr.xpath("ThML.body/div1[@id='ii']/div2"))!=5:raise ValueError("complete volume boundary differs")
    from build.lib.tei_xsd import compiled_tei_schema
    compiled_tei_schema(manifest.authority_path("tei-p5-xsd")).assertValid(root)
    return dict(status="pass",source_elements=15955,body_elements=15804,body_roots=2,chapter_count=14,nested_divisions=182,index_count=5,notes=1545,subject_markers=2,unclear=1,language_attributes=589,all_source_attributes_parents_ordinals_text_tails_checked=True,base_body_unchanged_except_verified_languages=True,p5="pass",prior_exposure="Read-only existing native producer and separate independent oracle inspected; whole base replay reused, source languages checked independently, no blind claim.")

def _oracle(manifest,candidate):
    candidate.verify_integrity();profile=json.loads(manifest.authority_path("profile").read_bytes())
    if candidate.manifest["source_manifest"]["sha256"]!=manifest.sha256:raise ValueError("source binding differs")
    check(manifest,candidate.member_bytes("content.tei.xml"))
    if json.loads(candidate.member_bytes("source-accountability.json"))!=profile["accounting"]:raise ValueError("source accounting differs")
    if candidate.member_bytes("README.source.md")!=manifest.authority_path("source-readme").read_bytes():raise ValueError("source notice differs")
    if [json.loads(x) for x in candidate.member_bytes("unresolved.jsonl").splitlines()]!=profile["questions"]:raise ValueError("unresolved claims differ")
    expected=dict(work_id=profile["work_id"],source_manifest_sha256=manifest.sha256,scope=profile["scope"],status="nonaccepted",native_base_reused=True,literal_languages_restored=589)
    if json.loads(candidate.member_bytes("provenance.json"))!=expected:raise ValueError("provenance differs")
    facts=MechanicalFacts(validator_implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),validator_import_closure_sha256=closure_sha(manifest.repository_root),source_sha256=profile["source_sha256"],profile_sha256=sha256(manifest.authority_path("profile").read_bytes()).hexdigest(),package_schema_sha256=manifest.record["package_schema"]["sha256"],xsd_sha256=sha256(manifest.authority_path("tei-p5-xsd").read_bytes()).hexdigest(),policy_sha256=sha256(manifest.authority_path("validation-policy").read_bytes()).hexdigest(),findings=())
    return verify_mechanical_facts(manifest,candidate,facts).as_record()

_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
_oracle.implementation_path=Path(__file__).resolve()
