"""Single complete On the Holy Spirit using the retained LIB-046 projection rules."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import npnf2_lib046_reconstruction as historical
from ocd_kernel.reconstruction.contract import reconstruct
from ocd_kernel.tei.writer import tei_el

WORK_ID = "basil-of-caesarea-on-the-holy-spirit"
CONVERTER_ID = "ocd-basil-holy-spirit-retained-to-tei"
CONVERTER_VERSION = "2"
SOURCE = "raw/ccel/npnf2/npnf208.xml"
SOURCE_SHA = "95cf3dafefccec80e0949a03c7f1f605da293302d0dc7a8bd62a4e711a0c5532"

def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()

def _convert(manifest):
    manifest.verify()
    raw = manifest.authority_path("retained-source").read_bytes()
    if len(raw)!=3303323 or sha256(raw).hexdigest()!=SOURCE_SHA:
        raise ValueError("retained NPNF208 drift")
    tree = historical._parse(manifest.authority_path("retained-source"))
    selected = tree.xpath("/ThML/ThML.body/div1[@id='vii']")
    if len(selected)!=1 or selected[0].get("title")!="De Spiritu Sancto.":
        raise ValueError("complete On the Holy Spirit root boundary differs")
    source=selected[0]
    root=historical._header({"npnf208":tree})
    root.set("{http://www.w3.org/XML/1998/namespace}id",WORK_ID)
    title=root.find(".//{http://www.tei-c.org/ns/1.0}titleStmt/{http://www.tei-c.org/ns/1.0}title")
    title.text="De Spiritu Sancto."
    title.attrib.pop("n") # Redundant producer source-key label, not a retained source attribute.
    source_desc=root.find(".//{http://www.tei-c.org/ns/1.0}sourceDesc")
    wrapper=source_desc[0]; bibl=wrapper[0]; wrapper.remove(bibl); source_desc.remove(wrapper); source_desc.append(bibl)
    for credit in root.xpath(".//t:note[@source]",namespaces={"t":"http://www.tei-c.org/ns/1.0"}):
        credit.set("source","https://www.ccel.org/ccel/schaff/npnf208.html"+credit.get("source"))
    text=tei_el("text",{"xml:lang":"en"}); body=tei_el("body"); text.append(body); root.append(text)
    rows=[]
    historical._append(source,body,"npnf208",rows,None,WORK_ID,{},"vii")
    # Source attribute order must not erase the direction of this Hebrew span.
    for span in source.iter("span"):
        if not span.get("dir"):
            continue
        row=next(r for r in rows if r["source_xml_id"]==span.get("id"))
        target=root.xpath("//*[@xml:id=$identifier]",identifier=row["tei_xml_id"],namespaces={"xml":"http://www.w3.org/XML/1998/namespace"})[0]
        rendition=((span.get("class") or "")+" direction:"+span.get("dir")).strip()
        target.set("rend",rendition); row["tei_attributes"]["rend"]=rendition
    top,direct=historical._division_accounting(tree,{"vii"})
    accounting=dict(contract="ocd-basil-holy-spirit-accountability-v1",work_id=WORK_ID,source_sha256=SOURCE_SHA,
        source_selector="/ThML/ThML.body/div1[7]",feature_count=len(rows),crosswalk=rows,
        assigned_census=historical._census(list(source.iter())),complete_document_census=historical._census(list(tree.getroot().iter())),
        document_accounting=historical._document_accounting(tree),top_level_division_accounting=top,direct_div2_accounting=direct)
    return {"content.tei.xml":etree.tostring(root,encoding="utf-8",xml_declaration=True),
        "source-accountability.json":canonical(accounting),"provenance.json":manifest.authority_path("profile").read_bytes(),
        "README.source.md":manifest.authority_path("source-readme").read_bytes(),
        "unresolved.jsonl":b"".join(canonical(row) for row in json.loads(manifest.authority_path("profile").read_bytes())["candidate_questions"])}

_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION

def build_candidate(manifest,destination):
    return reconstruct(manifest,destination,_convert)
