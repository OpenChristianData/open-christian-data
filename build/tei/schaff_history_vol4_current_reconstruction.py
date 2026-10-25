"""Reuse the complete readable HCC4 route and restore literal language attributes."""
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import schaff_history_vol_4_reconstruction as legacy

CONVERTER_ID="ocd-schaff-history-vol4-complete-retained-v1"
CONVERTER_VERSION="1"
NS="{http://www.tei-c.org/ns/1.0}"
XML_ID="{http://www.w3.org/XML/1998/namespace}id"
XML_LANG="{http://www.w3.org/XML/1998/namespace}lang"

def canonical(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()

def _convert(manifest):
    manifest.verify();profile=json.loads(manifest.authority_path("profile").read_bytes())
    source_tree=legacy._parse_source(manifest.authority_path("primary-source").read_bytes())
    old_profile=json.loads(manifest.authority_path("native-base-profile").read_bytes())
    tree=legacy._build_tei_tree(source_tree,old_profile);original=legacy._serialize_tei(tree)
    if original!=manifest.authority_path("native-base").read_bytes():raise ValueError("readable native base replay differs")
    root=tree.getroot();root.replace(root.find(NS+"teiHeader"),etree.fromstring(profile["header_xml"].encode()))
    nodes,index=legacy._source_index(source_tree.getroot());targets={n.get(XML_ID):n for n in root.iter() if n.get(XML_ID)}
    restored=0
    for source in nodes:
        if source.get("lang") is not None:
            key=source.get("id") or "hcc4-generated-"+str(index[source]["source_key"])[6:]
            targets[key].set(XML_LANG,source.get("lang"));restored+=1
    if restored!=589:raise ValueError("source language census differs")
    copy=etree.fromstring(etree.tostring(root),etree.XMLParser(huge_tree=True))
    for n in copy.iter():
        if XML_LANG in n.attrib:del n.attrib[XML_LANG]
    if legacy._serialize_tei(copy.getroottree()).split(b"</teiHeader>",1)[1]!=original.split(b"</teiHeader>",1)[1]:raise ValueError("language repair changed other native body/evidence bytes")
    return {"content.tei.xml":legacy._serialize_tei(tree),"source-accountability.json":canonical(profile["accounting"]),"provenance.json":canonical(dict(work_id=profile["work_id"],source_manifest_sha256=manifest.sha256,scope=profile["scope"],status="nonaccepted",native_base_reused=True,literal_languages_restored=restored)),"README.source.md":manifest.authority_path("source-readme").read_bytes(),"unresolved.jsonl":b"".join(canonical(q) for q in profile["questions"])}

_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION
_convert.implementation_path=Path(__file__).resolve()
