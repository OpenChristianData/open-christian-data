"""Finite retained Plummer authority and existing LIB-033 ledger reconciliation."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[2]
LOG = Path("reports/_logs/plummer-existing-install-20261003-v1")
OLD_PACKAGE = LOG / "immutable-lib033-package"
WORK_ID = "expositors-bible--alfred-plummer"
NS = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
MEMBERS = {
 "plummer-expositorpastoral": dict(volume=1,path="raw/ccel/expositors-bible/plummer_expositorpastoral.xml",
  sha256="1fd1cf712e96ed431f5e4abcf13c21d3819499c39fe603d6af54a404d73d6882",bytes=988188,elements=5134,body_elements=5066,
  front=["i","ii"],back=["vii","viii"]),
 "plummer-expositorjamesjude": dict(volume=2,path="raw/ccel/expositors-bible/plummer_expositorjamesjude.xml",
  sha256="20053cd20a768b654da39896a869bda507f7806cab9bb82013282e06860202a8",bytes=1171840,elements=6866,body_elements=6768,
  front=["i"],back=["v","vi"]),
}
for member,spec in MEMBERS.items():
 spec.update(form=WORK_ID+"--"+member+"--retained-en",edition=WORK_ID+"--"+member+"--ccel-electronic",acquisition=WORK_ID+"--"+member+"--acquired")
 spec.update(body_comments=14 if spec['volume']==1 else 10,tbody_wrappers=0 if spec['volume']==1 else 10,
  native_source_elements=5065 if spec['volume']==1 else 6757,
  source_base_url='https://www.ccel.org/ccel/plummer/'+('expositorpastoral.html' if spec['volume']==1 else 'expositorjamesjude.html'))

OLD_TEI_SHA = "2b213b17e96e7e084bb664e90d664a2c364e0fecc19bcf2cb289145da7da4134"
OLD_ACCOUNT_SHA = "3f5893aa82b9e9f564e3d1eeec64c69fcc56165b717104f3bb79a989f2c99644"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse(raw: bytes) -> etree._Element:
    return etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True,
        load_dtd=False, remove_comments=False, remove_pis=False, huge_tree=True))


def old_authority(member_id: str, root: Path = ROOT) -> tuple[bytes, dict[str, object]]:
    """Recover the existing candidate witness only after matching every ledger feature."""
    raw_tei = (root / OLD_PACKAGE / "content.tei.xml").read_bytes()
    raw_account = (root / OLD_PACKAGE / "source-accountability.json").read_bytes()
    if sha(raw_tei) != OLD_TEI_SHA or sha(raw_account) != OLD_ACCOUNT_SHA:
        raise ValueError("Plummer immutable LIB-033 candidate authority drifted")
    tei = parse(raw_tei)
    account = json.loads(raw_account)
    members = tei.xpath("//*[@xml:id=$member_id]",member_id=member_id)
    if len(members) != 1:
        raise ValueError("Plummer original retained member cardinality differs")
    member = members[0]
    notes = member.findall(NS + "note")
    if len(notes) != 1 or notes[0].get("type") != "exact-retained-source-bytes" or notes[0].get("subtype") != "base64":
        raise ValueError("Plummer original encoded witness differs")
    raw = base64.b64decode(notes[0].text, validate=True)
    spec = MEMBERS[member_id]
    if sha(raw) != spec["sha256"] or raw != (root / spec["path"]).read_bytes():
        raise ValueError("Plummer original encoded witness does not equal retained downloaded source")
    source = parse(raw)
    elements = [x for x in source.iter() if isinstance(x.tag, str)]
    rows = [x for x in account["crosswalk"] if x["member_id"] == member_id]
    ledger = member.findall(".//" + NS + "ab")
    if len(elements) != spec["elements"] or len(rows) != len(elements) or len(ledger) != len(elements):
        raise ValueError("Plummer existing feature census differs")
    positions = {x: n for n, x in enumerate(elements, 1)}
    rebuilt = []
    for ordinal, (source_node, row, retained_node) in enumerate(zip(elements, rows, ledger, strict=True), 1):
        parent = source_node.getparent()
        parent_ordinal = positions.get(parent)
        siblings = [x for x in parent if isinstance(x.tag, str)] if parent is not None else [source_node]
        child_ordinal = siblings.index(source_node) + 1
        if (row["source_tag"] != source_node.tag or row["source_attributes"] != dict(source_node.attrib)
                or row["source_parent_ordinal"] != parent_ordinal or row["source_child_ordinal"] != child_ordinal
                or row["source_direct_text"] != (source_node.text or "") or row["source_tail_text"] != (source_node.tail or "")
                or row["tei_xml_id"] != retained_node.get(XML_ID) or row["feature_id"] != retained_node.get(XML_ID)
                or row["disposition"] != "represented" or retained_node.get("subtype") != source_node.tag
                or retained_node.get("n") != str(child_ordinal)):
            raise ValueError(f"Plummer original source/ledger feature differs at {ordinal}")
        segments = retained_node.findall(NS + "seg")
        if len(segments) != 2 or [x.get("type") for x in segments] != ["direct-text", "tail-text"]:
            raise ValueError(f"Plummer ledger payload carriers differ at {ordinal}")
        for key, segment in zip(["source_direct_text", "source_tail_text"], segments, strict=True):
            if (segment.text or "") != row[key] or len(segment) or sha(row[key].encode()) != row[key + "_sha256"]:
                raise ValueError(f"Plummer existing TEI payload differs at {ordinal}: {key}")
        restored = etree.Element(row["source_tag"], row["source_attributes"])
        restored.text = segments[0].text
        restored.tail = segments[1].text
        if parent_ordinal:
            rebuilt[parent_ordinal - 1].append(restored)
        rebuilt.append(restored)
    # Feature hierarchy omits source comments by historical design. Compare the
    # entire feature forest, while exact encoded witness proves comments/PI/bytes.
    restored_elements = list(rebuilt[0].iter())
    if len(restored_elements) != len(elements):
        raise ValueError("Plummer reconstructed ledger hierarchy differs")
    for left, right in zip(elements, restored_elements, strict=True):
        if (left.tag, dict(left.attrib), left.text or "", left.tail or "") != (right.tag, dict(right.attrib), right.text or "", right.tail or ""):
            raise ValueError("Plummer reconstructed feature graph differs")
    return raw, {"status": "pass", "source_sha256": sha(raw), "original_tei_sha256": OLD_TEI_SHA,
        "original_account_sha256": OLD_ACCOUNT_SHA, "feature_count": len(rows),
        "exact_existing_encoded_witness_equals_downloaded_source": True,
        "all_existing_tei_direct_and_tail_payloads_equal_source": True,
        "all_source_attributes_parent_and_child_order_equal": True,
        "ledger_hierarchy_recovery_equal": True,
        "source_comments_and_processing_instructions": "preserved by byte-identical encoded retained witness; not inferred from historical ledger"}


def retained(member_id: str, root: Path = ROOT) -> bytes:
    spec = MEMBERS[member_id]
    raw, _ = old_authority(member_id, root)
    if sha(raw) != spec["sha256"] or len(raw) != spec["bytes"]:
        raise ValueError(f"{member_id}: retained source identity differs")
    if sum(isinstance(x.tag, str) for x in parse(raw).iter()) != spec["elements"]:
        raise ValueError(f"{member_id}: retained source feature census differs")
    return raw


def scope_report(root: Path = ROOT) -> dict:
 rows=[]
 for member,spec in MEMBERS.items():
  raw,recovery=old_authority(member,root);source=parse(raw);body=source.find("ThML.body");header=source.find("ThML.head")
  source_ids={n.get("id") for n in body.iter() if isinstance(n.tag,str) and n.get("id")}
  broken=[dict(source_id=n.get("id"),href=n.get("href")) for n in body.iter("a") if (n.get("href") or "").startswith("#") and n.get("href")[1:] not in source_ids]
  rows.append(dict(member_id=member,**spec,source_title=header.findtext(".//DC.Title"),source_author=header.findtext(".//DC.Creator[@sub='Author'][@scheme='short-form']"),
   literal_print_statement=header.findtext(".//published"),root_divisions=[dict(id=n.get("id"),title=n.get("title")) for n in body if isinstance(n.tag,str)],
   source_broken_local_links=broken,original_recovery=recovery))
 return dict(contract="ocd-plummer-existing-two-volume-scope-v1",status="pass",work_id=WORK_ID,acquired_volume_count=2,included_volume_count=2,
  scope="Exactly both acquired titled Plummer electronic volumes: Pastoral Epistles and General Epistles of James/Jude. Named epistles are internal commentary parts, not new work identities; no author or Expositor-series completeness claim.",
  front_body_boundary="Pastoral i title and ii contents are front; iii Introductory explicitly Chapter I/the authenticity of the Pastoral Epistles belongs in body. James/Jude i title is front; ii Introductory explicitly Chapter I/The Catholic Epistles belongs in body.",
  source_order="All original root divisions preserve order; printed and generated indices are back matter",members=rows,no_acquisition_or_download=True)

if __name__=="__main__":
 destination=ROOT/LOG/"retained-scope-reconciliation.json"
 destination.write_text(json.dumps(scope_report(),ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
 print(sha(destination.read_bytes()))
