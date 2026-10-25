"""Reissue the unchanged complete Gregory Selected Epistles body through the retained LIB048 mapper."""
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import npnf2_lib048_reconstruction as legacy

CONVERTER_ID = "ocd-gregory-the-great-selected-epistles-complete-retained-v1"
CONVERTER_VERSION = "1"
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"


def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()


def _convert(manifest):
    manifest.verify()
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    source = legacy._parse(manifest.authority_path("retained-text"))
    selected = source.getroot().find("ThML.body/div1[@id='ii']")
    root = etree.Element(NS+"TEI",nsmap={None:NS[1:-1]})
    root.set(XML+"id",profile["work_id"])
    root.append(etree.fromstring(profile["header_xml"].encode()))
    body = etree.SubElement(etree.SubElement(root,NS+"text"),NS+"body")
    policy = json.loads(manifest.authority_path("aggregate-validation-policy").read_bytes())
    exceptions = legacy._reference_exception_map(policy)
    rows = [None]*profile["historical_ordinal_offset"]
    legacy._append(selected,body,"npnf213",rows,parent_feature_id=None,work_id=profile["work_id"],reference_exceptions=exceptions,source_root_id="ii")
    rows = rows[profile["historical_ordinal_offset"]:]
    wrapper = body[0]
    # Standalone XML parsing discards the historical file's trailing root whitespace.
    # Compare the complete element here; the independent source checker separately
    # checks the retained root tail inside the new complete-work wrapper.
    if etree.tostring(etree.fromstring(etree.tostring(wrapper,with_tail=False)),method="c14n",with_tail=False) != etree.tostring(etree.fromstring(manifest.authority_path("historical-selected-body").read_bytes()),method="c14n",with_tail=False):
        raise ValueError("replayed complete body differs from retained historical selected body")
    accountability = dict(profile["accounting"],represented_features=rows)
    return {"content.tei.xml":etree.tostring(root,encoding="UTF-8",xml_declaration=True),
        "source-accountability.json":canonical(accountability),
        "provenance.json":canonical(dict(work_id=profile["work_id"],source_manifest_sha256=manifest.sha256,scope=profile["scope"],body_unchanged=True,historical_ordinal_offset=50326,status="nonaccepted")),
        "README.source.md":manifest.authority_path("source-readme").read_bytes(),
        "unresolved.jsonl":b"".join(canonical(q) for q in profile["questions"])}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
