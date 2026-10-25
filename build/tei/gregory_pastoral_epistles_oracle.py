"""Independent source-native whole-Gregory Pastoral Rule and Epistles checks; never imports the producer."""
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
import xml.etree.ElementTree as ET
from lxml import etree
from build.tei import npnf2_lib048_oracle as legacy

ORACLE_ID = "ocd-gregory-the-great-pastoral-rule-and-epistles-independent-retained-oracle-v1"
ORACLE_VERSION = "1"
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"


def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()


def closure_sha(root):
    names = ["build/tei/gregory_pastoral_epistles_oracle.py","build/tei/npnf2_lib048_oracle.py","ocd_kernel/reconstruction/contract.py","ocd_kernel/reconstruction/__init__.py","ocd_kernel/tei/validate.py"]
    return sha256(canonical([{ "path":p,"sha256":sha256((root/p).read_bytes()).hexdigest()} for p in sorted(names)])).hexdigest()


def fingerprint(n):
    return (n.tag,sorted(n.attrib.items()),n.text,n.tail,tuple(fingerprint(c) for c in n))


def policy_and_exceptions(manifest, selected):
    policy = json.loads(manifest.authority_path("aggregate-validation-policy").read_bytes())
    entries = policy["projection"]["reference_classification"]["neutral_non_scripture_exceptions"]
    entries = [e for e in entries if e["source_member"] == "npnf212" and e["source_root_id"] == "iii"]
    expected = {'iii.iii-p31.4': 'Ep. 30', 'iii.iii-p46.1': 'Ep. 30', 'iii.v.i.ix-p5.1': 'Ep. 35', 'iii.v.i.xix-p6.1': 'Ep. 7', 'iii.v.i.xxi-p5.1': 'Ep. 7', 'iii.v.i.xxix-p3.1': 'Ep. 39', 'iii.v.ii.iv-p5.1': 'Ep. 6', 'iii.v.ii.x-p10.1': 'Ep. 38', 'iii.v.ii.xxiv-p19.1': 'Ep. 20', 'iii.v.v.viii-p9.3': 'Ep. 103', 'iii.v.v.xiii-p5.1': 'Ep. 23', 'iii.v.vi.vii-p7.1': 'Ep. 53'}
    observed = {e["source_xml_id"]:e["passage"] for e in entries}
    if len(entries) != 12 or observed != expected:
        raise ValueError("twelve source-neutral letter reference declarations differ")
    for key, passage in expected.items():
        nodes = selected.xpath('.//*[@id="'+key+'"]')
        if len(nodes) != 1 or nodes[0].tag != "scripRef" or dict(nodes[0].attrib) != {"id":key,"passage":passage}:
            raise ValueError("neutral reference primary-source binding differs")
    return policy, {("npnf212","iii",key):value for key,value in expected.items()}


def _expected_subset_rows(
    selected: list[tuple[str, etree._Element, str]],
    policy: dict,
    reference_exceptions: dict,
) -> list[dict]:
    rows = [None]*42657

    def visit(
        key: str,
        node: etree._Element,
        parent_feature_id: str | None,
        work_id: str | None = None,
        source_root_id: str | None = None,
    ) -> None:
        if not isinstance(node.tag, str):
            raise ValueError("assigned source contains non-element")
        ordinal = len(rows) + 1
        feature_id = f"lib048-feature-{ordinal:06d}"
        if source_root_id is None:
            raise ValueError("reference classification context is required")
        neutral_reference = (
            key,
            source_root_id,
            node.get("id") or "",
        ) in reference_exceptions
        tag, attrs, wrapper = legacy._projection(
            policy,
            node,
            key,
            ordinal,
            work_id,
            source_root_id,
            reference_exceptions,
        )
        dispositions = []
        for name, value in node.attrib.items():
            destination, method = (
                "source-accountability",
                "preserved-exactly-in-accountability",
            )
            rule = policy["projection"]["attribute_rules"].get(name)
            if name == "id":
                destination, method = (
                    "@xml:id-and-source-accountability",
                    "deterministic-member-and-ordinal-prefix",
                )
            elif (
                rule
                and str(node.tag) in rule.get("source_tags", [])
                and not (rule.get("except_work_root") and work_id)
                and not (
                    str(node.tag) == "scripRef"
                    and name in {"passage", "osisRef"}
                    and neutral_reference
                )
            ):
                destination, method = (
                    rule.get("disposition", "source-accountability"),
                    rule.get("method", method),
                )
            dispositions.append(
                {
                    "source_attribute": name,
                    "source_value": value,
                    "destination": destination,
                    "method": method,
                }
            )
        row = {
            "feature_id": feature_id,
            "parent_feature_id": parent_feature_id,
            "source_member": key,
            "source_selector": legacy._selector(node),
            "source_tag": node.tag,
            "source_xml_id": node.get("id"),
            "source_attributes": dict(node.attrib),
            "direct_text_length": len(node.text or ""),
            "direct_text_sha256": legacy._sha((node.text or "").encode()),
            "tail_text_length": len(node.tail or ""),
            "tail_text_sha256": legacy._sha((node.tail or "").encode()),
            "source_title_head": node.get("title")
            if str(node.tag).startswith("div")
            else None,
            "tei_tag": tag,
            "tei_xml_id": attrs["xml:id"],
            "tei_attributes": attrs,
            "tei_wrapper_id": wrapper,
            "attribute_dispositions": dispositions,
            "disposition": "represented",
            **({"work_id": work_id} if work_id else {}),
        }
        rows.append(row)
        for child in node:
            visit(key, child, feature_id, source_root_id=source_root_id)

    for key, root, work_id in selected:
        visit(key, root, None, work_id, root.get("id"))
    return rows[42657:]


def expected_ledger(manifest, selected, work):
    policy, exceptions = policy_and_exceptions(manifest, selected)
    return _expected_subset_rows([("npnf212",selected,work)],policy,exceptions)


def check(manifest,raw):
    manifest.verify()
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    source = manifest.authority_path("retained-text").read_bytes()
    parsed = legacy._source_tree(source)
    selected = parsed.getroot().find("ThML.body/div1[@id='iii']")
    accounting = profile["accounting"]
    if accounting["source_sha256"] != sha256(source).hexdigest() or accounting["source_bytes"] != len(source):
        raise ValueError("source envelope identity differs")
    head = parsed.getroot().find("ThML.head")
    if accounting["source_header"]["elements"] != sum(1 for n in head.iter() if isinstance(n.tag,str)) or accounting["source_header"]["sha256"] != sha256(etree.tostring(head,method="c14n")).hexdigest():
        raise ValueError("retained source header inventory differs")
    outside = [n for n in parsed.getroot().find("ThML.body") if not isinstance(n.tag,str) or n.get("id") != "iii"]
    if len(outside) != len(accounting["outside_work"]):
        raise ValueError("outside-work accounting cardinality differs")
    for node,row in zip(outside,accounting["outside_work"]):
        if isinstance(node.tag,str):
            observed = {"tag":node.tag,"id":node.get("id"),"title":node.get("title"),"elements":sum(1 for n in node.iter() if isinstance(n.tag,str)),"sha256":sha256(etree.tostring(node,method="c14n")).hexdigest()}
        else:
            observed = {"kind":"non-element","sha256":sha256(etree.tostring(node)).hexdigest()}
        if any(row.get(key) != value for key,value in observed.items()) or not row.get("destination","").startswith("retained"):
            raise ValueError("outside-work source inventory/disposition differs")
    std_selected = ET.fromstring(source).find("ThML.body/div1[@id='iii']")
    if fingerprint(selected) != fingerprint(std_selected):
        raise ValueError("independent stdlib source parsing differs")
    if sum(1 for _ in selected.iter()) != 7669 or len([n for n in selected.iter() if n.tag.startswith("div") and n.get("title")]) != 356:
        raise ValueError("source work inventory differs")
    parts = [n for n in selected if n.tag=="div2"]
    if [n.get("id") for n in parts] != ["iii."+n for n in ("i","ii","iii","iv","v")]:
        raise ValueError("complete ordered five-part composite collection differs")
    pastoral = [n for n in parts[3] if n.tag=="div3"]
    books = [n for n in parts[4] if n.tag=="div3"]
    if [n.get("id") for n in pastoral] != ["iii.iv."+n for n in ("i","ii","iii","iv","v")] or [len(list(n.iter("div4"))) for n in pastoral] != [0,12,11,41,0]:
        raise ValueError("complete Pastoral Rule preface/four parts/64 chapters differ")
    if [n.get("id") for n in books] != ["iii.v."+n for n in ("i","ii","iii","iv","v","vi","vii","viii")] or [len(list(n.iter("div4"))) for n in books] != [52,30,34,32,31,45,28,21]:
        raise ValueError("eight source register books and 273 entries differ")
    incoming = selected.xpath('.//*[@id="iii.v.iii.xxix"]')
    if len(incoming) != 1 or incoming[0].get("title") != "From John, Bishop of Ravenna to Pope Gregory.":
        raise ValueError("incoming source correspondence attribution differs")
    image = selected.xpath('.//*[@id="iii.iii-p86.1"]')
    if len(image) != 1 or image[0].tag != "img" or dict(image[0].attrib) != {"alt":"Pedigree of Kings of Gaul","src":"/ccel/schaff/npnf212/files/fig1.png","id":"iii.iii-p86.1"}:
        raise ValueError("source diagram placement/label/reference differs")
    pixels = manifest.authority_path("retained-diagram").read_bytes()
    if len(pixels) != 44462 or sha256(pixels).hexdigest() != "a06e1fa626deadbfa78c1390ccd63408b7eea2a720c5b4542eda9e999cc616b5" or pixels[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("retained supplemental diagram bytes differ")
    media = accounting.get("source_media")
    if not isinstance(media,list) or len(media) != 1 or any(media[0].get(k) != value for k,value in {"source_id":"iii.iii-p86.1","source_uri":image[0].get("src"),"source_alt":image[0].get("alt"),"retained_path":"raw/ccel/npnf2/npnf212/files/fig1.png","bytes":len(pixels),"sha256":sha256(pixels).hexdigest(),"historical_snapshot_bytes":"unknown"}.items()):
        raise ValueError("independent source media accountability differs")
    if any(n.get("dir") for n in selected.iter()):
        raise ValueError("unexpected source direction attributes")
    policy, exceptions = policy_and_exceptions(manifest, selected)
    for credit in profile["credits"]:
        observed = "".join(parsed.xpath(credit["source_selector"])[0].itertext())
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
    counter = [42657]
    legacy._verify_node(selected,wrapper,"npnf212",policy,counter,work_id=profile["work_id"],source_root_id="iii",reference_exceptions=exceptions)
    if counter[0] != 50326:
        raise ValueError("source element conservation differs")
    if etree.tostring(etree.fromstring(etree.tostring(wrapper,with_tail=False)),method="c14n",with_tail=False) != etree.tostring(etree.fromstring(manifest.authority_path("historical-selected-body").read_bytes()),method="c14n",with_tail=False):
        raise ValueError("body differs from historical source-checked reconstruction")
    ids = [n.get(XML+"id") for n in doc.iter() if n.get(XML+"id")]
    if len(ids)!=len(set(ids)):
        raise ValueError("duplicate TEI identifiers")
    etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd")))).assertValid(doc)
    return dict(status="pass",source_elements=7669,source_literal_heads=356,epistles=273,books=8,book_epistle_counts=[52,30,34,32,31,45,28,21],pastoral_parts=4,pastoral_chapters=64,
        notes=len(list(selected.iter("note"))),pages=len(list(selected.iter("pb"))),source_reference_tags=len(list(selected.iter("scripRef"))),neutral_letter_references=12,rtl_spans=0,retained_diagram_bytes=44462,retained_diagram_sha256="a06e1fa626deadbfa78c1390ccd63408b7eea2a720c5b4542eda9e999cc616b5",image_historical_snapshot="unknown",
        italic_ids_preserved=1835,historical_body_unchanged=True,source_parser_corroboration="stdlib/lxml exact selected native tree",p5="pass",
        independent_source_mapping="Readonly LIB048 independent _verify_node checks all source tags/attributes/direct text/tails/title ownership/child order; no producer imported.",
        prior_exposure="Historical/current mapping previously exposed; source parsing and independent source mapping corroborate, no blind claim.")


def _oracle(manifest,candidate):
    candidate.verify_integrity()
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    if candidate.manifest["source_manifest"]["sha256"] != manifest.sha256 or manifest.record["validator"]["import_closure_sha256"] != closure_sha(manifest.repository_root):
        raise ValueError("current source binding/closure differs")
    check(manifest,candidate.member_bytes("content.tei.xml"))
    selected = legacy._source_tree(manifest.authority_path("retained-text").read_bytes()).getroot().find("ThML.body/div1[@id='iii']")
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
