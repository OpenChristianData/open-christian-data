"""Single complete Hexaemeron using the retained LIB-046 projection rules."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import npnf2_lib046_reconstruction as historical
from ocd_kernel.reconstruction.contract import reconstruct
from ocd_kernel.tei.writer import tei_el

WORK_ID = "basil-of-caesarea-hexaemeron"
CONVERTER_ID = "ocd-basil-hexaemeron-retained-to-tei"
CONVERTER_VERSION = "2"
SOURCE = "raw/ccel/npnf2/npnf208.xml"
SOURCE_SHA = "95cf3dafefccec80e0949a03c7f1f605da293302d0dc7a8bd62a4e711a0c5532"
NEUTRAL_ID = "viii.iii-p43.1"

def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()

def _convert(manifest):
    manifest.verify()
    raw = manifest.authority_path("retained-source").read_bytes()
    if len(raw)!=3303323 or sha256(raw).hexdigest()!=SOURCE_SHA:
        raise ValueError("retained NPNF208 drift")
    tree = historical._parse(manifest.authority_path("retained-source"))
    selected = tree.xpath("/ThML/ThML.body/div1[@id='viii']")
    if len(selected)!=1 or selected[0].get("title")!="The Hexæmeron.":
        raise ValueError("complete Hexaemeron root boundary differs")
    source=selected[0]
    root=historical._header({"npnf208":tree})
    root.set("{http://www.w3.org/XML/1998/namespace}id",WORK_ID)
    title=root.find(".//{http://www.tei-c.org/ns/1.0}titleStmt/{http://www.tei-c.org/ns/1.0}title")
    title.text="The Hexæmeron."
    title.attrib.pop("n") # Redundant producer source-key label, not a retained source attribute.
    source_desc=root.find(".//{http://www.tei-c.org/ns/1.0}sourceDesc")
    wrapper=source_desc[0]; bibl=wrapper[0]; wrapper.remove(bibl); source_desc.remove(wrapper); source_desc.append(bibl)
    for credit in root.xpath(".//t:note[@source]",namespaces={"t":"http://www.tei-c.org/ns/1.0"}):
        credit.set("source","https://www.ccel.org/ccel/schaff/npnf208.html"+credit.get("source"))
    text=tei_el("text",{"xml:lang":"en"}); body=tei_el("body"); text.append(body); root.append(text)
    rows=[]
    historical._append(source,body,"npnf208",rows,None,WORK_ID,{},"viii")
    for row in rows:
        if row["source_xml_id"]==NEUTRAL_ID:
            node=root.xpath("//*[@xml:id=$identifier]",identifier=row["tei_xml_id"],namespaces={"xml":"http://www.w3.org/XML/1998/namespace"})[0]
            node.set("type","source-reference")
            row["tei_attributes"]["type"]="source-reference"
    top,direct=historical._division_accounting(tree,{"viii"})
    accounting=dict(contract="ocd-basil-hexaemeron-accountability-v1",work_id=WORK_ID,source_sha256=SOURCE_SHA,
        source_selector="/ThML/ThML.body/div1[8]",feature_count=len(rows),crosswalk=rows,
        assigned_census=historical._census(list(source.iter())),complete_document_census=historical._census(list(tree.getroot().iter())),
        document_accounting=historical._document_accounting(tree),top_level_division_accounting=top,direct_div2_accounting=direct,
        reference_classification_override=dict(source_id=NEUTRAL_ID,type="source-reference",reason="Endnote cites Jerome Quaest. Heb., column 508; retain erroneous native Bible:Col.508 target without asserting biblical classification."))
    return {"content.tei.xml":etree.tostring(root,encoding="utf-8",xml_declaration=True),
        "source-accountability.json":canonical(accounting),"provenance.json":manifest.authority_path("profile").read_bytes(),
        "README.source.md":manifest.authority_path("source-readme").read_bytes(),
        "unresolved.jsonl":b"".join(canonical(row) for row in json.loads(manifest.authority_path("profile").read_bytes())["candidate_questions"])}

_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION

def build_candidate(manifest,destination):
    return reconstruct(manifest,destination,_convert)
