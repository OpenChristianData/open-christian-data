"""Independent source traversal using the separate historical LIB-046 checker."""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
from xml.etree import ElementTree
from lxml import etree
from build.tei import npnf2_lib046_oracle as historical
from ocd_kernel.reconstruction.contract import _canonical,_validation_authority_bindings
from ocd_kernel.tei.validate import compiled_schema

ORACLE_ID="ocd-basil-holy-spirit-independent-check"
ORACLE_VERSION="2"
ROOT=Path(__file__).resolve().parents[2]
TEI="http://www.tei-c.org/ns/1.0"
XML_ID="{http://www.w3.org/XML/1998/namespace}id"

def closure_sha():
    policy=json.loads((ROOT/"sources/structured-text/npnf2-lib046/npnf2-lib046.validation-policy.json").read_bytes())
    paths=set(historical._closure_paths(ROOT,policy))|{Path(__file__).resolve(),ROOT/"ocd_kernel/tei/validate.py"}
    return sha256(_canonical([dict(path=p.relative_to(ROOT).as_posix(),sha256=sha256(p.read_bytes()).hexdigest()) for p in sorted(paths,key=str)])).hexdigest()

def _oracle(manifest,candidate):
    findings=[]
    try:
        manifest.verify(); candidate.verify_integrity()
        raw=manifest.authority_path("retained-source").read_bytes()
        if sha256(raw).hexdigest()!="95cf3dafefccec80e0949a03c7f1f605da293302d0dc7a8bd62a4e711a0c5532" or len(raw)!=3303323:
            raise ValueError("exact retained source differs")
        source_tree=historical._source_tree(raw)
        # Independent XML parser corroborates every original element/attribute/text/tail.
        other=ElementTree.fromstring(raw)
        lnodes=list(source_tree.getroot().iter()); snodes=list(other.iter())
        if len(lnodes)!=len(snodes) or any((a.tag,dict(a.attrib),a.text or "",a.tail or "")!=(b.tag,dict(b.attrib),b.text or "",b.tail or "") for a,b in zip(lnodes,snodes,strict=True)):
            raise ValueError("independent source XML parser correspondence differs")
        top=source_tree.xpath("/ThML/ThML.body/div1")
        if [n.get("id") for n in top]!=["i","ii","iii","iv","v","vi","vii","viii","ix","x"]:
            raise ValueError("source envelope/order differs")
        source=top[6]
        roman=["i","ii","iii","iv","v","vi","vii","viii","ix","x","xi","xii","xiii","xiv","xv","xvi","xvii","xviii","xix","xx","xxi","xxii","xxiii","xxiv","xxv","xxvi","xxvii","xxviii","xxix","xxx","xxxi"]
        if source.get("title")!="De Spiritu Sancto." or [n.get("id") for n in source]!=["vii."+x for x in roman]:
            raise ValueError("complete preface/thirty-chapter boundary differs")
        tei=historical._tei_tree(candidate.member_bytes("content.tei.xml"))
        body=tei.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")
        if body is None or len(body)!=1 or len(tei.findall("{http://www.tei-c.org/ns/1.0}text"))!=1:
            raise ValueError("one complete work in one TEI required")
        policy=json.loads(manifest.authority_path("validation-policy").read_bytes())
        exceptions=historical._neutral_reference_inventory(policy,[("npnf208",source,"basil-of-caesarea-on-the-holy-spirit")])
        rows=historical._expected_rows([("npnf208",source,"basil-of-caesarea-on-the-holy-spirit")],policy,exceptions)
        checked=deepcopy(body[0])
        directions=[]
        # Derive direction/class together from source, independently of attribute order.
        for span in source.iter("span"):
            if not span.get("dir"):
                continue
            row=next(r for r in rows if r["source_xml_id"]==span.get("id"))
            expected_rend=((span.get("class") or "")+" direction:"+span.get("dir")).strip()
            target=body[0].xpath(".//*[@xml:id=$identifier]",identifier=row["tei_xml_id"],namespaces={"xml":"http://www.w3.org/XML/1998/namespace"})[0]
            if target.get("rend")!=expected_rend:
                raise ValueError("source direction/class rendition differs at "+span.get("id"))
            directions.append(span.get("id"))
            normalized=checked.xpath(".//*[@xml:id=$identifier]",identifier=row["tei_xml_id"],namespaces={"xml":"http://www.w3.org/XML/1998/namespace"})[0]
            normalized.set("rend",row["tei_attributes"]["rend"])
            row["tei_attributes"]["rend"]=expected_rend
        if directions!=["vii.vii-p30.6"]:
            raise ValueError("complete source direction-carrier census differs")
        counter=[0]
        historical._verify_node(source,checked,"npnf208",policy,counter,"basil-of-caesarea-on-the-holy-spirit","vii",exceptions)
        if counter[0]!=3406:
            raise ValueError("complete readable source carrier count differs")
        schema=compiled_schema()
        if not schema.validate(tei):
            raise ValueError(f"P5 schema failure: {schema.error_log}")
        original_header=etree.fromstring(bytes.fromhex(json.loads(manifest.authority_path("profile").read_bytes())["header_hex"]))
        actual_header=tei.find("{http://www.tei-c.org/ns/1.0}teiHeader")
        signature=lambda region:[(n.tag,dict(n.attrib),n.text or "",n.tail or "",len(n)) for n in region.iter()]
        if signature(actual_header)!=signature(original_header):
            raise ValueError("retained source metadata/header differs")
        ns={"t":TEI}
        source_metadata=historical._source_metadata(source_tree)
        for credit in actual_header.xpath(".//t:note[@source]",namespaces=ns):
            locator=credit.get("source")
            if not locator.startswith("https://www.ccel.org/ccel/schaff/npnf208.html#") or credit.text!=historical._source_text(source_tree,locator.split("#",1)[1]):
                raise ValueError("source-located contributor credit differs")
        if actual_header.xpath(".//t:availability/t:p/text()",namespaces=ns)!=["Public Domain"] or source_tree.xpath("/ThML/ThML.head/electronicEdInfo/DC/DC.Rights/text()")!=["Public Domain"]:
            raise ValueError("retained rights statement differs")
        census=historical._census(list(source.iter()))
        t,d=historical._division_accounting(source_tree,{"vii"})
        expected=dict(contract="ocd-basil-holy-spirit-accountability-v1",work_id="basil-of-caesarea-on-the-holy-spirit",source_sha256=sha256(raw).hexdigest(),
            source_selector="/ThML/ThML.body/div1[7]",feature_count=len(rows),crosswalk=rows,assigned_census=census,
            complete_document_census=historical._census(lnodes),document_accounting=historical._document_accounting(source_tree),
            top_level_division_accounting=t,direct_div2_accounting=d)
        if json.loads(candidate.member_bytes("source-accountability.json"))!=expected:
            raise ValueError("independent complete source accountability differs")
        profile=manifest.authority_path("profile").read_bytes()
        if candidate.member_bytes("provenance.json")!=profile or candidate.member_bytes("unresolved.jsonl")!=b"".join(_canonical(r) for r in json.loads(profile)["candidate_questions"]):
            raise ValueError("provenance/unresolved source scope differs")
        if candidate.member_bytes("README.source.md")!=manifest.authority_path("source-readme").read_bytes():
            raise ValueError("source metadata/credit notice differs")
        if manifest.record["work_id"]!="basil-of-caesarea-on-the-holy-spirit" or manifest.record["validator"]["import_closure_sha256"]!=closure_sha():
            raise ValueError("work identity or independent checker closure differs")
    except (ValueError,OSError,KeyError,TypeError,etree.XMLSyntaxError,ElementTree.ParseError,json.JSONDecodeError) as exc:
        findings.append(str(exc))
    result=dict(status="fail" if findings else "pass",oracle_id=ORACLE_ID,oracle_version=ORACLE_VERSION,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),import_closure_sha256=closure_sha(),
        runtime=f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        source_manifest_sha256=manifest.sha256,candidate_sha256=candidate.sha256,**_validation_authority_bindings(manifest),findings=findings)
    result["result_sha256"]=sha256(_canonical(result)).hexdigest()
    return result

_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
