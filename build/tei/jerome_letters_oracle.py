"""Independent source-native whole-Jerome Letters checks; never imports the producer."""
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
import xml.etree.ElementTree as ET
from lxml import etree
from build.tei import npnf2_lib048_oracle as legacy

ORACLE_ID = "ocd-jerome-letters-independent-retained-oracle-v1"
ORACLE_VERSION = "1"
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"


def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()


def closure_sha(root):
    names = ["build/tei/jerome_letters_oracle.py","build/tei/npnf2_lib048_oracle.py","ocd_kernel/reconstruction/contract.py","ocd_kernel/reconstruction/__init__.py","ocd_kernel/tei/validate.py"]
    return sha256(canonical([{ "path":p,"sha256":sha256((root/p).read_bytes()).hexdigest()} for p in sorted(names)])).hexdigest()


def fingerprint(n):
    return (n.tag,sorted(n.attrib.items()),n.text,n.tail,tuple(fingerprint(c) for c in n))


def policy_and_exceptions(manifest, selected):
    policy = json.loads(manifest.authority_path("aggregate-validation-policy").read_bytes())
    entries = policy["projection"]["reference_classification"]["neutral_non_scripture_exceptions"]
    entries = [e for e in entries if e["source_member"] == "npnf206" and e["source_root_id"] == "v"]
    expected = {"v.XIV-p4.1":"Ep. lxxvii. 9", "v.XXXIX-p75.1":"Ep. cxxxiii. 3", "v.XLVIII-p18.1":"Ep. cxxiii. 9", "v.XLVIII-p141.1":"Ep. 93", "v.XLVIII-p171.1":"Ep. i. 6, 67, 68", "v.CVIII-p44.1":"Ep. xv. 2"}
    observed = {e["source_xml_id"]: e["passage"] for e in entries}
    if len(entries) != 6 or observed != expected:
        raise ValueError("six source-neutral letter reference declarations differ")
    for key, passage in observed.items():
        nodes = selected.xpath('.//*[@id="'+key+'"]')
        if len(nodes) != 1 or nodes[0].tag != "scripRef" or dict(nodes[0].attrib) != {"id":key,"passage":passage}:
            raise ValueError("neutral reference primary-source binding differs")
    return policy, {("npnf206","v",key): value for key,value in observed.items()}


def expected_ledger(manifest, selected, work):
    policy, exceptions = policy_and_exceptions(manifest, selected)
    return legacy._expected_rows([("npnf206",selected,work)],policy,exceptions)


def check(manifest,raw):
    manifest.verify()
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    source = manifest.authority_path("retained-text").read_bytes()
    parsed = legacy._source_tree(source)
    selected = parsed.getroot().find("ThML.body/div1[@id='v']")
    accounting = profile["accounting"]
    if accounting["source_sha256"] != sha256(source).hexdigest() or accounting["source_bytes"] != len(source):
        raise ValueError("source envelope identity differs")
    head = parsed.getroot().find("ThML.head")
    if accounting["source_header"]["elements"] != sum(1 for n in head.iter() if isinstance(n.tag,str)) or accounting["source_header"]["sha256"] != sha256(etree.tostring(head,method="c14n")).hexdigest():
        raise ValueError("retained source header inventory differs")
    outside = [n for n in parsed.getroot().find("ThML.body") if not isinstance(n.tag,str) or n.get("id") != "v"]
    if len(outside) != len(accounting["outside_work"]):
        raise ValueError("outside-work accounting cardinality differs")
    for node,row in zip(outside,accounting["outside_work"]):
        if isinstance(node.tag,str):
            observed = {"tag":node.tag,"id":node.get("id"),"title":node.get("title"),"elements":sum(1 for n in node.iter() if isinstance(n.tag,str)),"sha256":sha256(etree.tostring(node,method="c14n")).hexdigest()}
        else:
            observed = {"kind":"non-element","sha256":sha256(etree.tostring(node)).hexdigest()}
        if any(row.get(key) != value for key,value in observed.items()) or not row.get("destination","").startswith("retained"):
            raise ValueError("outside-work source inventory/disposition differs")
    std_selected = ET.fromstring(source).find("ThML.body/div1[@id='v']")
    if fingerprint(selected) != fingerprint(std_selected):
        raise ValueError("independent stdlib source parsing differs")
    if sum(1 for _ in selected.iter()) != 13459 or len([n for n in selected.iter() if n.tag.startswith("div") and n.get("title")]) != 151:
        raise ValueError("source work inventory differs")
    parts = [n for n in selected if n.tag=="div2"]
    def roman(n):
        output=""
        for value, symbol in ((100,"C"),(90,"XC"),(50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I")):
            while n >= value: output += symbol; n -= value
        return output
    if [n.get("id") for n in parts] != ["v."+roman(n) for n in range(1,151)] or not all(n.get("title") for n in parts):
        raise ValueError("complete ordered 150-entry editorial collection differs")
    rtl = [n for n in selected.iter("span") if n.get("dir")]
    if len(rtl) != 5 or any(n.get("dir") != "rtl" or n.get("lang") != "HE" for n in rtl):
        raise ValueError("five Hebrew RTL primary-source spans differ")
    policy, exceptions = policy_and_exceptions(manifest, selected)
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
    counter = [0]
    legacy._verify_node(selected,wrapper,"npnf206",policy,counter,work_id=profile["work_id"],source_root_id="v",reference_exceptions=exceptions)
    if counter[0] != 13459:
        raise ValueError("source element conservation differs")
    if etree.tostring(etree.fromstring(etree.tostring(wrapper,with_tail=False)),method="c14n",with_tail=False) != etree.tostring(etree.fromstring(manifest.authority_path("historical-selected-body").read_bytes()),method="c14n",with_tail=False):
        raise ValueError("body differs from historical source-checked reconstruction")
    ids = [n.get(XML+"id") for n in doc.iter() if n.get(XML+"id")]
    if len(ids)!=len(set(ids)):
        raise ValueError("duplicate TEI identifiers")
    etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd")))).assertValid(doc)
    return dict(status="pass",source_elements=13459,source_literal_heads=151,letters=150,
        notes=len(list(selected.iter("note"))),pages=len(list(selected.iter("pb"))),source_reference_tags=len(list(selected.iter("scripRef"))),neutral_letter_references=6,hebrew_rtl_spans=5,
        italic_ids_preserved=233,historical_body_unchanged=True,source_parser_corroboration="stdlib/lxml exact selected native tree",p5="pass",
        independent_source_mapping="Readonly LIB048 independent _verify_node checks all source tags/attributes/direct text/tails/title ownership/child order; no producer imported.",
        prior_exposure="Historical/current mapping previously exposed; source parsing and independent source mapping corroborate, no blind claim.")


def _oracle(manifest,candidate):
    candidate.verify_integrity()
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    if candidate.manifest["source_manifest"]["sha256"] != manifest.sha256 or manifest.record["validator"]["import_closure_sha256"] != closure_sha(manifest.repository_root):
        raise ValueError("current source binding/closure differs")
    check(manifest,candidate.member_bytes("content.tei.xml"))
    selected = legacy._source_tree(manifest.authority_path("retained-text").read_bytes()).getroot().find("ThML.body/div1[@id='v']")
    expected = dict(profile["accounting"],represented_features=expected_ledger(manifest,selected,profile["work_id"]))
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
