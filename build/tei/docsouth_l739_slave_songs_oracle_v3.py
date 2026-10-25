"""Independent ElementTree oracle for retained DocSouth L739."""
from __future__ import annotations
import hashlib,json,platform,sys
from pathlib import Path
from typing import Mapping
from xml.etree import ElementTree as ET
from lxml import etree
from ocd_kernel.reconstruction.contract import CandidatePackage,SourceManifest
T="{http://www.tei-c.org/ns/1.0}"; X="{http://www.w3.org/XML/1998/namespace}"
ORACLE_ID="ocd-docsouth-l739-independent-source-oracle"; ORACLE_VERSION="3"
def _sha(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def _json(v:object)->bytes:return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
def _norm(s:str)->str:return " ".join(s.split())
def _text(n:ET.Element)->str:
    parts=[]
    def walk(x):
        if x.text:parts.append(x.text)
        children=list(x)
        if x.tag in {"choice", T+"choice"}: children=children[:1]
        for c in children:
            walk(c)
            if c.tail:parts.append(c.tail)
    walk(n);return _norm("".join(parts))

def _local(node:ET.Element)->str:return node.tag.rsplit("}",1)[-1]
def _lyric_shape(node:ET.Element,source:bool):
    if _local(node)=="choice" and not source and list(node):
        # The P4 stylesheet carries sic/corr alternatives in a P5 choice.
        # Keep the source's displayed sic branch while body-text checks cover its text.
        sic=next((child for child in node if _local(child)=="sic"),list(node)[0])
        return _lyric_shape(sic,source)
    tag=_local(node); attrs={}
    for key,value in node.attrib.items():
        local=key.rsplit("}",1)[-1]
        # TEI P5 drops the TEI2 link-order hint and normalizes local targets to fragments.
        if local=="targOrder": continue
        if local=="target" and value.startswith("#"): value=value[1:]
        if local=="corr" and tag=="sic": continue
        if local=="id": attrs["id"]=value
        elif tag=="figure" and local=="entity": attrs["entity"]=value
        else: attrs[local]=value
    children=list(node)
    if tag=="figure":
        graphics=[child for child in children if _local(child)=="graphic"]
        if source:
            attrs["entity"]=node.get("entity")
        elif graphics:
            attrs["entity"]=graphics[0].get("n")
            if "id" not in attrs:
                value=next((v for k,v in graphics[0].attrib.items() if k.rsplit("}",1)[-1]=="id"),None)
                if value is not None: attrs["id"]=value
        children=[child for child in children if _local(child)!="graphic"]
    return [tag,sorted(attrs.items()),[_lyric_shape(child,source) for child in children]]
def _music_counts(root:ET.Element)->dict[str,int]:
    groups=[node for node in root.iter() if _local(node)=="lg"]
    lines=[node for node in root.iter() if _local(node)=="l"]
    figures=[node for node in root.iter() if _local(node)=="figure"]
    pages=[node for node in root.iter() if _local(node)=="pb"]
    nested=0
    for group in groups:
        nested+=sum(1 for node in group.iter() if node is not group and _local(node)=="figure")
    return {"lyric_group_count":len(groups),"lyric_line_count":len(lines),"figure_count":len(figures),"figures_nested_in_lyric_groups":nested,"page_marker_count":len(pages)}

def _oracle(manifest:SourceManifest,candidate:CandidatePackage)->Mapping[str,object]:
    problems=[]; raw=manifest.authority_path("official-source-member").read_bytes(); content=candidate.member_bytes("content.tei.xml")
    s=ET.fromstring(raw); c=ET.fromstring(content)
    if s.tag!="TEI.2" or c.tag!=T+"TEI":problems.append("expected one source TEI.2 and one candidate P5 TEI root")
    st=s.find("text");ct=c.find(T+"text")
    if st is None or ct is None:problems.append("text envelope absent")
    else:
        for sec in ("front","body","back"):
            a=st.find(sec);b=ct.find(T+sec)
            if (a is None)!=(b is None):problems.append(sec+" presence differs")
            elif a is not None and _text(a)!=_text(b):problems.append(sec+" text or order differs")
    sp=[(x.get("id"),x.get("n")) for x in s.iter("pb")];cp=[(x.get(X+"id"),x.get("n")) for x in c.iter(T+"pb")]
    if sp!=cp:problems.append("page marker inventory/order differs")
    sf=[x.get("entity") for x in s.iter("figure") if x.get("entity")];cg=[(x.get("n"),x.get("url")) for x in c.iter(T+"graphic")]
    receipt=json.loads(manifest.authority_path("acquisition-receipt").read_bytes()); profile=json.loads(manifest.authority_path("profile").read_bytes()); base=receipt["source_url"].rsplit("/",1)[0]+"/"
    if cg!=[(e,base+profile["image_entities"][e]) for e in sf]:problems.append("figure/entity graphic locator sequence differs")
    if len([n for n in c.iter() if n.tag==T+"TEI"])!=1:problems.append("candidate must contain exactly one TEI document")
    source_ids=[n.get("id") for n in s.iter() if n.get("id")]
    candidate_ids=[]
    for n in c.iter():
        value=n.get(X+"id")
        if n.tag==T+"language": value=n.get("ident")
        if value: candidate_ids.append(value)
    if source_ids!=candidate_ids:problems.append("source XML ID/language identifier sequence differs")
    account=json.loads(candidate.member_bytes("source-accountability.json")); policy=json.loads(manifest.authority_path("policy").read_bytes())
    if account.get("source_sha256")!=_sha(raw) or account.get("tei_sha256")!=_sha(content) or account.get("tei_bytes")!=len(content):problems.append("accountability does not bind exact source/candidate bytes")
    if account.get("page_markers")!=profile["page_markers"] or account.get("image_entities")!=profile["image_entities"] or account.get("figure_entity_sequence")!=profile["figure_entity_sequence"]:problems.append("source accounting differs from feature profile")
    if candidate.member_bytes("README.source.md")!=manifest.authority_path("readme").read_bytes():problems.append("source README differs")
    if json.loads(candidate.member_bytes("provenance.json"))!=policy["provenance"]:problems.append("provenance differs")
    if candidate.member_bytes("unresolved.jsonl")!=b"".join(_json(x) for x in policy["unresolved"]):problems.append("unresolved ledger differs")
    if account.get("retained_image_members")!=profile.get("retained_image_members"): problems.append("retained image member accounting differs from the exact acquisition receipt")
    if account.get("unretained_declared_image_entities")!=profile.get("unretained_declared_image_entities"): problems.append("unused unretained image entity accounting differs")
    if account.get("music_structure")!=profile.get("music_structure"): problems.append("music structure inventory differs from source profile")
    if _music_counts(s)!=profile.get("music_structure") or _music_counts(c)!=profile.get("music_structure"): problems.append("lyric group, line, figure, or page structure count differs")
    source_groups=[node for node in s.iter() if _local(node)=="lg"]; candidate_groups=[node for node in c.iter() if _local(node)=="lg"]
    if [_lyric_shape(node,True) for node in source_groups]!=[_lyric_shape(node,False) for node in candidate_groups]: problems.append("lyric group/stanza/line nesting or attributes differ")
    retained=[authority for authority in manifest.record["authorities"] if authority.get("role")=="retained-source-image"]
    receipt_images=receipt.get("image_members",[])
    image_binding={(authority.get("path"),authority.get("bytes"),authority.get("sha256")) for authority in retained}
    receipt_binding={(item.get("path"),item.get("bytes"),item.get("sha256")) for item in receipt_images}
    profile_binding={(item.get("path"),item.get("bytes"),item.get("sha256")) for item in profile.get("retained_image_members",[])}
    if len(retained)!=168 or image_binding!=receipt_binding or image_binding!=profile_binding: problems.append("retained image authorities do not exactly bind the 168 receipt/profile members")
    schema=etree.XMLSchema(etree.parse(str(manifest.authority_path("p5-schema")),etree.XMLParser(resolve_entities=False,no_network=True)))
    if not schema.validate(etree.fromstring(content,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))):problems.append("P5 schema invalid: "+str(schema.error_log.last_error))
    att={"status":"pass" if not problems else "fail","oracle_id":ORACLE_ID,"oracle_version":ORACLE_VERSION,"implementation_sha256":_sha(Path(__file__).read_bytes()),"import_closure_sha256":_sha(_json([{"path":"build/tei/docsouth_l739_slave_songs_oracle_v3.py","sha256":_sha(Path(__file__).read_bytes())},{"path":"ocd_kernel/reconstruction/contract.py","sha256":_sha((manifest.repository_root/"ocd_kernel/reconstruction/contract.py").read_bytes())}])),"runtime":f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})","source_manifest_sha256":manifest.sha256,"candidate_sha256":candidate.sha256,"profile_sha256":_sha(manifest.authority_path("profile").read_bytes()),"package_schema_sha256":manifest.record["package_schema"]["sha256"],"source_sha256":_sha(raw),"xsd_sha256":_sha(manifest.authority_path("p5-schema").read_bytes()),"policy_sha256":_sha(manifest.authority_path("policy").read_bytes()),"findings":problems}
    att["result_sha256"]=_sha(_json(att));return att
_oracle.oracle_id=ORACLE_ID;_oracle.oracle_version=ORACLE_VERSION;_oracle.implementation_path=Path(__file__).resolve()
