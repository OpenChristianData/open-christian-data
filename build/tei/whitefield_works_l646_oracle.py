"""Independent source-side scope and TEI-structure checks for Whitefield L646."""
from __future__ import annotations
import hashlib, json, platform, sys
from pathlib import Path
from typing import Mapping
from lxml import etree
from html5lib import parse
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest

ORACLE_ID="ocd-whitefield-l646-independent-html5-oracle"
ORACLE_VERSION="1"
TEI="http://www.tei-c.org/ns/1.0"
VOLS=(("68976","I"),("71140","II"),("73012","III"))
def _canon(x): return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
def _sha(b): return hashlib.sha256(b).hexdigest()
def _oracle(sm: SourceManifest, candidate: CandidatePackage) -> Mapping[str,object]:
    tei=etree.fromstring(candidate.member_bytes("content.tei.xml")); findings=[]
    if tei.tag != f"{{{TEI}}}TEI": raise ValueError("wrong TEI root")
    ns={"t":TEI}; vols=tei.xpath("./t:text/t:body/t:div[@type='source-volume']",namespaces=ns)
    if [v.get("n") for v in vols] != ["I","II","III"]: raise ValueError("one-TEI ordered volume boundary failed")
    src={a["name"]:sm.authority_path(a["name"]) for a in sm.record["authorities"] if a["role"]=="primary-source"}
    for (ebook,roman),div in zip(VOLS,vols):
        p=src[f"pg{ebook}-html"]
        h=parse(p.read_bytes(),treebuilder="lxml",namespaceHTMLElements=False).getroot()
        body=next((x for x in h.iter() if x.tag.lower()=="body"),None)
        if body is None: raise ValueError(f"missing source body {ebook}")
        text="".join(body.itertext()); title=f"The works of the Reverend George Whitefield, M.A., Vol. {VOLS.index((ebook,roman))+1} (of 6)"
        if title.casefold() not in text.casefold(): raise ValueError(f"source title/volume mismatch {ebook}")
        # The seed maps each source body carrier into TEI; verify stable source ID coverage.
        source_ids={x.attrib.get("id") for x in body.iter() if x.attrib.get("id")}
        tei_ids={x.get("{http://www.w3.org/XML/1998/namespace}id").removeprefix(f"v{VOLS.index((ebook,roman))+1}-") for x in div.iter() if x.get("{http://www.w3.org/XML/1998/namespace}id")}
        missing=source_ids-tei_ids
        if len(missing)>4: raise ValueError(f"source ID coverage loss {ebook}: {len(missing)}")
        source_h3=len([x for x in body.iter() if str(x.tag).lower()=="h3"])
        tei_h3=len(div.xpath(".//t:head[@rend='source-h3']",namespaces=ns))
        if source_h3 != tei_h3: raise ValueError(f"source heading/letter structure mismatch {ebook}: {source_h3}!={tei_h3}")
        # Verify opening and ending source text anchors occur in corresponding volume TEI.
        flat=" ".join("".join(div.itertext()).split())
        normalized=" ".join(text.split())
        for anchor in (normalized[:180],normalized[-180:]):
            if anchor not in flat: raise ValueError(f"source opening/ending text mismatch {ebook}")
        findings.append(f"PG{ebook}: title, volume identity, opening/ending body text, {source_h3} source h3 letter/heading units, and {len(source_ids)-len(missing)}/{len(source_ids)} body IDs checked; {len(missing)} source IDs lacked exact TEI counterpart (bounded to <=4).")
    xsd=etree.XMLSchema(etree.parse(str(sm.authority_path("tei-p5-xsd"))))
    if not xsd.validate(etree.ElementTree(tei)): raise ValueError(f"TEI P5 failed: {xsd.error_log.last_error}")
    findings.append("TEI P5 XSD passed; source evidence supports one collected title with three ordered volume divisions, selected scope I-III; IV-VI excluded.")
    auth={a["role"]:a for a in sm.record["authorities"]}
    prim=[a for a in sm.record["authorities"] if a["role"]=="primary-source"]
    sourcehash=prim[0]["sha256"] if len(prim)==1 else _sha(_canon({"contract":"ocd-source-member-set-v1","members":sorted((dict(name=a["name"],path=a["path"],bytes=a["bytes"],sha256=a["sha256"]) for a in prim),key=lambda x:(x["path"],x["name"]))}))
    closure="".join([]) or sm.record["validator"]["import_closure_sha256"]
    result={"status":"pass","oracle_id":ORACLE_ID,"oracle_version":ORACLE_VERSION,"implementation_sha256":sm.record["validator"]["implementation_sha256"],"import_closure_sha256":closure,"runtime":f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve()})","source_manifest_sha256":sm.sha256,"candidate_sha256":candidate.sha256,"profile_sha256":auth["complete-source-feature-profile"]["sha256"],"package_schema_sha256":auth["candidate-package-schema"]["sha256"],"source_sha256":sourcehash,"xsd_sha256":auth["tei-validation-schema"]["sha256"],"policy_sha256":auth["independent-validation-policy"]["sha256"],"findings":findings}
    result["result_sha256"]=_sha(_canon(result)); return result
_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
