"""One exact L599 header leaf and bounded native-document hook proposal."""
from pathlib import Path
import difflib
import hashlib
import json
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
HOME = ROOT / "sources/manifest-acquisitions/l599-slave-trade-header-proposal-v1"
OUT = ROOT / ".tmp_audit/l599_native_packet_v1"
BASE = ROOT / "ocd_kernel/projection/categories/native_documents.py"
def digest(raw):
    return hashlib.sha256(raw).hexdigest()
def enc(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
def pin(path):
    raw = path.read_bytes()
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": len(raw), "sha256": digest(raw)}
def fields(node):
    return [node.tag, sorted(node.attrib.items()), node.text, node.tail, [fields(c) for c in node]]
def replace(source, before, after):
    if source.count(before) != 1:
        raise ValueError("Exact current native hook anchor differs: " + before)
    return source.replace(before, after, 1)


def prepare():
    if OUT.exists():
        raise ValueError("Preserve existing native proposal")
    OUT.mkdir()
    proposal = json.loads((HOME / "proposal.json").read_bytes())
    raw = (HOME / "candidate.tei.xml").read_bytes()
    if digest(raw) != proposal["header_bound_candidate"]["sha256"]:
        raise ValueError("Header proposal changed")
    full_fields = digest(json.dumps(fields(ET.fromstring(raw)), ensure_ascii=False, separators=(",", ":")).encode())
    identity = {key: proposal["identity"][key] for key in ["work_id", "textual_form_id", "edition_id"]}
    leaf_text = '''"""Exact L599 retained Wikisource header admission; no acceptance creation."""
import hashlib
import json
N='{http://www.tei-c.org/ns/1.0}'
IDENTITY=__IDENTITY__
MASTER_SHA=__MASTER__
FULL_FIELDS_SHA=__FIELDS__
def digest(raw):return hashlib.sha256(raw).hexdigest()
def route(identity,raw,*,language,category,collection,projection_profile,allow_acceptance_metadata,source_base):
 if identity.get('work_id')!=IDENTITY['work_id']:return False
 if identity!=IDENTITY or digest(raw)!=MASTER_SHA or language!='en' or category!='prose' or collection or projection_profile is not None or not allow_acceptance_metadata or source_base is not None:raise ValueError('L599 exact reviewed master/identity/prose context differs')
 return True
def fields_et(node):return [node.tag,sorted(node.attrib.items()),node.text,node.tail,[fields_et(c) for c in node]]
def fields_lxml(node):return [str(node.tag),sorted((str(k),str(v)) for k,v in node.attrib.items()),node.text,node.tail,[fields_lxml(c) for c in node]]
def check_et(root):
 if digest(json.dumps(fields_et(root),ensure_ascii=False,separators=(',',':')).encode())!=FULL_FIELDS_SHA:raise ValueError('L599 whole actual header/body/fields/ownership differs')
 return True
def check_lxml(root):
 if digest(json.dumps(fields_lxml(root),ensure_ascii=False,separators=(',',':')).encode())!=FULL_FIELDS_SHA:raise ValueError('Observed L599 entire actual tree/fields differs')
 return True
def header_rules(elements,attributes):
 elements={key:list(value) for key,value in elements.items()};attributes={key:list(value) for key,value in attributes.items()}
 elements['sourceDesc']=list(dict.fromkeys(elements['sourceDesc']+['biblStruct']))
 elements.update(biblStruct=['monogr','note'],monogr=['title','author','imprint'],imprint=['pubPlace','publisher','date'])
 attributes['author']=list(dict.fromkeys(attributes.get('author',[])+['role']))
 attributes['p']=list(dict.fromkeys(attributes.get('p',[])+['n','xml:space']))
 return elements,attributes
'''.replace("__IDENTITY__", repr(identity)).replace("__MASTER__", repr(digest(raw))).replace("__FIELDS__", repr(full_fields))
    leaf = OUT / "l599_slave_trade_source_profile.py"
    leaf.write_bytes(leaf_text.encode())
    text = BASE.read_text(encoding="utf-8")
    text = replace(text, "from __future__ import annotations", "from __future__ import annotations\n\nfrom ocd_kernel.projection.categories import l599_slave_trade_source_profile as l599_source")
    route = "    l599 = l599_source.route(identity, raw, language=language, category=category, collection=collection, projection_profile=projection_profile, allow_acceptance_metadata=_allow_acceptance_metadata, source_base=source_base)\n"
    text = replace(text, "    if whitefield:whitefield_source.check_et(root)", route + "    if l599:l599_source.check_et(root)\n    if whitefield:whitefield_source.check_et(root)")
    text = replace(text, "        if whitefield:whitefield_source.check_lxml(doc)", "        " + route.lstrip() + "        if l599:l599_source.check_lxml(doc)\n        if whitefield:whitefield_source.check_lxml(doc)")
    text = replace(text, "\n    elements, attributes = _header_rules(_allow_acceptance_metadata)\n", "\n    elements, attributes = _header_rules(_allow_acceptance_metadata)\n    if l599:elements, attributes = l599_source.header_rules(elements, attributes)\n")
    text = replace(text, "\n        elements, attributes = _header_rules(_allow_acceptance_metadata)\n", "\n        elements, attributes = _header_rules(_allow_acceptance_metadata)\n        if l599:elements, attributes = l599_source.header_rules(elements, attributes)\n")
    candidate = OUT / "native_documents_candidate.py"
    candidate.write_bytes(text.encode())
    diff = "".join(difflib.unified_diff(BASE.read_text(encoding="utf-8").splitlines(keepends=True), text.splitlines(keepends=True), fromfile=BASE.relative_to(ROOT).as_posix(), tofile=candidate.relative_to(ROOT).as_posix()))
    diff_path = OUT / "native_documents.diff"
    diff_path.write_bytes(diff.encode())
    packet = {"status": "unexecuted-isolated-reader-proposal", "identity": identity, "master": pin(HOME / "candidate.tei.xml"),
              "full_actual_ET_fields_sha256": full_fields, "leaf": pin(leaf), "target_leaf": "ocd_kernel/projection/categories/l599_slave_trade_source_profile.py",
              "baseline": pin(BASE), "candidate": pin(candidate), "bounded_diff": pin(diff_path),
              "header_gap": "Source-attributed author role, full biblStruct/monogr/imprint and exact raw administration p@n/xml:space fields exceed generic sermon header vocabulary.",
              "source_fidelity": "Exact reviewed master and full independently observed ET/lxml fields bound; generic content mapping, body, styles, quotation ownership, links, source gaps, schema, other routes and source packages unchanged.",
              "shared_writes": False, "acceptance_or_installation": False,
              "qualification": "No shared file is edited. Maintained prose auto-dispatch already selects native content for this ab/gap/style-bearing body; no prose hook or native-content/schema edit proposed."}
    (OUT / "packet.json").write_bytes(enc(packet))
    return pin(OUT / "packet.json")


if __name__ == "__main__":
    print(json.dumps(prepare(), sort_keys=True))
