"""Independent source-native whole-Romans checks; never imports the producer."""
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
import xml.etree.ElementTree as ET
from lxml import etree
from build.tei import npnf_chrysostom_oracle as legacy

ORACLE_ID = "ocd-chrysostom-romans-independent-retained-oracle-v1"
ORACLE_VERSION = "1"
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"


def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()


def closure_sha(root):
    names = ["build/tei/chrysostom_romans_oracle.py","build/tei/npnf_chrysostom_oracle.py","ocd_kernel/reconstruction/contract.py","ocd_kernel/reconstruction/__init__.py","ocd_kernel/tei/validate.py"]
    return sha256(canonical([{ "path":p,"sha256":sha256((root/p).read_bytes()).hexdigest()} for p in sorted(names)])).hexdigest()


def fingerprint(n):
    return (n.tag,sorted(n.attrib.items()),n.text,n.tail,tuple(fingerprint(c) for c in n))


def expected_ledger(selected,work):
    rows = []
    offset = 26901
    def visit(node,parent_id,parent_feature,is_root=False,child_ordinal=1):
        number = offset+len(rows)+1
        attrs,dispositions = legacy._expected_attributes(node,"npnf111",number,work,is_work_root=is_root)
        feature = f"npnf-chrysostom-feature-{number:05d}"
        rows.append(dict(ordinal=number,feature_id=feature,member="npnf111",work_id=work,source_selector=legacy._selector(node),
            source_tag=node.tag,source_xml_id=node.get("id"),source_attributes=dict(node.attrib),text_present=node.text is not None,
            text_sha256=sha256((node.text or "").encode()).hexdigest(),tail_present=node.tail is not None,
            tail_sha256=sha256((node.tail or "").encode()).hexdigest(),tei_tag=legacy._target_tag(node),tei_xml_id=attrs["xml:id"],
            tei_parent_id=parent_id,tei_child_ordinal=child_ordinal,tei_attributes=attrs,attribute_dispositions=dispositions,
            tei_selector="#"+attrs["xml:id"],parent_feature_id=parent_feature,source_title_head=node.get("title") if node.tag.startswith("div") else None,disposition="represented"))
        for i,child in enumerate(node,1):
            visit(child,attrs["xml:id"],feature,child_ordinal=i+(1 if node.get("title") is not None else 0))
    visit(selected,work+"-complete-work",None,True)
    return rows


def check(manifest,raw):
    manifest.verify()
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    source = manifest.authority_path("retained-text").read_bytes()
    parsed = legacy._source_tree(source)
    selected = parsed.getroot().find("ThML.body/div1[@id='vii']")
    accounting = profile["accounting"]
    if accounting["source_sha256"] != sha256(source).hexdigest() or accounting["source_bytes"] != len(source):
        raise ValueError("source envelope identity differs")
    head = parsed.getroot().find("ThML.head")
    if accounting["source_header"]["elements"] != sum(1 for n in head.iter() if isinstance(n.tag,str)) or accounting["source_header"]["sha256"] != sha256(etree.tostring(head,method="c14n")).hexdigest():
        raise ValueError("retained source header inventory differs")
    outside = [n for n in parsed.getroot().find("ThML.body") if not isinstance(n.tag,str) or n.get("id") != "vii"]
    if len(outside) != len(accounting["outside_work"]):
        raise ValueError("outside-work accounting cardinality differs")
    for node,row in zip(outside,accounting["outside_work"]):
        if isinstance(node.tag,str):
            observed = {"tag":node.tag,"id":node.get("id"),"title":node.get("title"),"elements":sum(1 for n in node.iter() if isinstance(n.tag,str)),"sha256":sha256(etree.tostring(node,method="c14n")).hexdigest()}
        else:
            observed = {"kind":"non-element","sha256":sha256(etree.tostring(node)).hexdigest()}
        if any(row.get(key) != value for key,value in observed.items()) or not row.get("destination","").startswith("retained"):
            raise ValueError("outside-work source inventory/disposition differs")
    std_selected = ET.fromstring(source).find("ThML.body/div1[@id='vii']")
    if fingerprint(selected) != fingerprint(std_selected):
        raise ValueError("independent stdlib source parsing differs")
    if sum(1 for _ in selected.iter()) != 5141 or len([n for n in selected.iter() if n.tag.startswith("div") and n.get("title")]) != 35:
        raise ValueError("source work inventory differs")
    parts = [n for n in selected if n.tag=="div2"]
    if len(parts)!=34 or [n.get("id") for n in parts[:2]] != ["vii.i","vii.ii"] or not all(n.get("title","").startswith("Homily ") for n in parts[2:]):
        raise ValueError("complete Preface/Argument/32-homily scope differs")
    for credit in profile["credits"]:
        observed = "".join(parsed.xpath('//*[@id="'+credit["source_id"]+'"]')[0].itertext())
        if observed != credit["literal_text"]:
            raise ValueError("source-local credit evidence differs")
    doc = etree.fromstring(raw)
    if doc.tag != NS+"TEI" or doc.attrib != {XML+"id":profile["work_id"]} or [n.tag for n in doc] != [NS+"teiHeader",NS+"text"]:
        raise ValueError("single-work document shell differs")
    if fingerprint(doc[0]) != fingerprint(etree.fromstring(profile["header_xml"].encode())):
        raise ValueError("localized header differs")
    body = doc.find(NS+"text/"+NS+"body")
    if len(doc[1]) != 1 or body is None or len(body) != 1:
        raise ValueError("single complete work/body boundary differs")
    wrapper = body[0]
    if wrapper.tag != NS+"div" or dict(wrapper.attrib) != {"type":"work","subtype":profile["work_id"],XML+"id":profile["work_id"]+"-complete-work"} or len(wrapper)!=1 or (wrapper.text or "") or (wrapper.tail or ""):
        raise ValueError("complete-work wrapper differs")
    counter = [26901]
    legacy._verify_node(selected,wrapper[0],member="npnf111",work_id=profile["work_id"],number=counter,is_work_root=True)
    if counter[0] != 32042:
        raise ValueError("source element conservation differs")
    if etree.tostring(etree.fromstring(etree.tostring(wrapper[0],with_tail=False)),method="c14n",with_tail=False) != etree.tostring(etree.fromstring(manifest.authority_path("historical-selected-body").read_bytes()),method="c14n",with_tail=False):
        raise ValueError("body differs from historical source-checked reconstruction")
    ids = [n.get(XML+"id") for n in doc.iter() if n.get(XML+"id")]
    if len(ids)!=len(set(ids)):
        raise ValueError("duplicate TEI identifiers")
    etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd")))).assertValid(doc)
    return dict(status="pass",source_elements=5141,source_literal_heads=35,prefaces=1,arguments=1,homilies=32,
        notes=len(list(selected.iter("note"))),pages=len(list(selected.iter("pb"))),scripture_references=len(list(selected.iter("scripRef"))),
        italic_ids_preserved=301,historical_body_unchanged=True,source_parser_corroboration="stdlib/lxml exact selected native tree",p5="pass",
        independent_source_mapping="Readonly LIB043 independent _verify_node checks all source tags/attributes/direct text/tails/title ownership/child order; no producer imported.",
        prior_exposure="Historical/current producer and coordinator source review already inspected; no blind claim.")


def _oracle(manifest,candidate):
    candidate.verify_integrity()
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    if candidate.manifest["source_manifest"]["sha256"] != manifest.sha256 or manifest.record["validator"]["import_closure_sha256"] != closure_sha(manifest.repository_root):
        raise ValueError("current source binding/closure differs")
    check(manifest,candidate.member_bytes("content.tei.xml"))
    selected = legacy._source_tree(manifest.authority_path("retained-text").read_bytes()).getroot().find("ThML.body/div1[@id='vii']")
    expected = dict(profile["accounting"],represented_features=expected_ledger(selected,profile["work_id"]))
    if json.loads(candidate.member_bytes("source-accountability.json")) != expected:
        raise ValueError("independent complete source accounting differs")
    if candidate.member_bytes("README.source.md") != manifest.authority_path("source-readme").read_bytes() or [json.loads(x) for x in candidate.member_bytes("unresolved.jsonl").splitlines()] != profile["questions"]:
        raise ValueError("credit or unresolved claims differ")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if provenance["source_manifest_sha256"]!=manifest.sha256 or provenance["scope"]!=profile["scope"]:
        raise ValueError("candidate provenance differs")
    result = dict(status="pass",oracle_id=ORACLE_ID,oracle_version=ORACLE_VERSION,implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        import_closure_sha256=closure_sha(manifest.repository_root),runtime=f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        source_manifest_sha256=manifest.sha256,candidate_sha256=candidate.sha256,profile_sha256=sha256(manifest.authority_path("profile").read_bytes()).hexdigest(),
        package_schema_sha256=manifest.record["package_schema"]["sha256"],source_sha256=profile["source_sha256"],
        xsd_sha256=sha256(manifest.authority_path("tei-p5-xsd").read_bytes()).hexdigest(),policy_sha256=sha256(manifest.authority_path("validation-policy").read_bytes()).hexdigest(),findings=[])
    result["result_sha256"] = sha256(canonical(result)).hexdigest()
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
