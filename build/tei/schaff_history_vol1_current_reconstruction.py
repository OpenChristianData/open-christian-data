"""Renew the unchanged complete HCC1 reconstruction with a source-attested current header."""
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import schaff_history_vol_1_reconstruction as legacy
CONVERTER_ID = "ocd-schaff-history-vol1-complete-retained-v1"
CONVERTER_VERSION = "1"
NS = "{http://www.tei-c.org/ns/1.0}"
def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
def _convert(manifest):
    manifest.verify()
    profile=json.loads(manifest.authority_path("profile").read_bytes())
    source_tree=legacy._parse_source(manifest.authority_path("primary-source").read_bytes())
    old_profile=json.loads(manifest.authority_path("historical-profile").read_bytes())
    tree=legacy._build_tei_tree(source_tree,old_profile)
    original=legacy._serialize_tei(tree)
    if original!=manifest.authority_path("historical-tei").read_bytes(): raise ValueError("complete historical source replay differs")
    root=tree.getroot();root.replace(root.find(NS+"teiHeader"),etree.fromstring(profile["header_xml"].encode()))
    raw=legacy._serialize_tei(tree)
    if raw.split(b"</teiHeader>",1)[1]!=original.split(b"</teiHeader>",1)[1]: raise ValueError("renewed header changed historical text/evidence bytes")
    return {"content.tei.xml":raw,"source-accountability.json":canonical(profile["accounting"]),
        "provenance.json":canonical(dict(work_id=profile["work_id"],source_manifest_sha256=manifest.sha256,scope=profile["scope"],historical_text_and_evidence_unchanged=True,status="nonaccepted")),
        "README.source.md":manifest.authority_path("source-readme").read_bytes(),"unresolved.jsonl":b"".join(canonical(q) for q in profile["questions"])}
_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION
_convert.implementation_path=Path(__file__).resolve()
