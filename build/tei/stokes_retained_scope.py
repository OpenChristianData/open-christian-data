"""Finite retained Stokes authority and existing LIB-034 ledger reconciliation."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[2]
LOG = Path("reports/_logs/stokes-existing-install-20261003-v1")
OLD_PACKAGE = LOG / "immutable-lib034-package"
WORK_ID = "expositors-bible--g-t-stokes"
NS = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
MEMBERS = {
    "stokes-expositoracts1": {
        "volume": 1, "path": "raw/ccel/expositors-bible/stokes_expositoracts1.xml",
        "sha256": "a6d7b301d9fd13ff5d298093eca5caa7463505684b0e4eae951ef2fc0fda34f6",
        "bytes": 1022435, "elements": 4669, "body_elements": 4612,
        "front": ["i", "ii", "iii"], "back": ["xxiv", "xxv"],
        "form": WORK_ID + "--stokes-expositoracts1--retained-en",
        "edition": WORK_ID + "--stokes-expositoracts1--ccel-electronic",
        "acquisition": WORK_ID + "--stokes-expositoracts1--acquired",
    },
    "stokes-expositoracts2": {
        "volume": 2, "path": "raw/ccel/expositors-bible/stokes_expositoracts2.xml",
        "sha256": "2f6cbaf722c823db42d7e63dda7b6ef17f691bc83e7fedc563df51440d15edf8",
        "bytes": 1202000, "elements": 5892, "body_elements": 5827,
        "front": ["i", "ii", "iii"], "back": ["xxii", "xxiii"],
        "form": WORK_ID + "--stokes-expositoracts2--retained-en",
        "edition": WORK_ID + "--stokes-expositoracts2--ccel-electronic",
        "acquisition": WORK_ID + "--stokes-expositoracts2--acquired",
    },
}
OLD_TEI_SHA = "03a8d0b6af4c4f27471e5d82fedf8d2b73e265af89ea94d4bac4916c41c32b81"
OLD_ACCOUNT_SHA = "b4e4b0b6e0540431029b25f1699fc97f07c1fbcdc7c7311cb9505a51b0002903"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse(raw: bytes) -> etree._Element:
    return etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True,
        load_dtd=False, remove_comments=False, remove_pis=False, huge_tree=True))


def old_authority(root: Path = ROOT) -> tuple[bytes, dict[str, object]]:
    """Recover the existing candidate witness only after matching every ledger feature."""
    raw_tei = (root / OLD_PACKAGE / "content.tei.xml").read_bytes()
    raw_account = (root / OLD_PACKAGE / "source-accountability.json").read_bytes()
    if sha(raw_tei) != OLD_TEI_SHA or sha(raw_account) != OLD_ACCOUNT_SHA:
        raise ValueError("Stokes immutable LIB-034 candidate authority drifted")
    tei = parse(raw_tei)
    account = json.loads(raw_account)
    members = tei.xpath("//*[@xml:id='stokes-expositoracts2']")
    if len(members) != 1:
        raise ValueError("Stokes original retained member cardinality differs")
    member = members[0]
    notes = member.findall(NS + "note")
    if len(notes) != 1 or notes[0].get("type") != "exact-retained-source-bytes" or notes[0].get("subtype") != "base64":
        raise ValueError("Stokes original encoded witness differs")
    raw = base64.b64decode(notes[0].text, validate=True)
    spec = MEMBERS["stokes-expositoracts2"]
    if sha(raw) != spec["sha256"] or raw != (root / spec["path"]).read_bytes():
        raise ValueError("Stokes original encoded witness does not equal retained downloaded source")
    source = parse(raw)
    elements = [x for x in source.iter() if isinstance(x.tag, str)]
    rows = [x for x in account["crosswalk"] if x["member_id"] == "stokes-expositoracts2"]
    ledger = member.findall(".//" + NS + "ab")
    if len(elements) != spec["elements"] or len(rows) != len(elements) or len(ledger) != len(elements):
        raise ValueError("Stokes existing feature census differs")
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
            raise ValueError(f"Stokes original source/ledger feature differs at {ordinal}")
        segments = retained_node.findall(NS + "seg")
        if len(segments) != 2 or [x.get("type") for x in segments] != ["direct-text", "tail-text"]:
            raise ValueError(f"Stokes ledger payload carriers differ at {ordinal}")
        for key, segment in zip(["source_direct_text", "source_tail_text"], segments, strict=True):
            if (segment.text or "") != row[key] or len(segment) or sha(row[key].encode()) != row[key + "_sha256"]:
                raise ValueError(f"Stokes existing TEI payload differs at {ordinal}: {key}")
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
        raise ValueError("Stokes reconstructed ledger hierarchy differs")
    for left, right in zip(elements, restored_elements, strict=True):
        if (left.tag, dict(left.attrib), left.text or "", left.tail or "") != (right.tag, dict(right.attrib), right.text or "", right.tail or ""):
            raise ValueError("Stokes reconstructed feature graph differs")
    return raw, {"status": "pass", "source_sha256": sha(raw), "original_tei_sha256": OLD_TEI_SHA,
        "original_account_sha256": OLD_ACCOUNT_SHA, "feature_count": len(rows),
        "exact_existing_encoded_witness_equals_downloaded_source": True,
        "all_existing_tei_direct_and_tail_payloads_equal_source": True,
        "all_source_attributes_parent_and_child_order_equal": True,
        "ledger_hierarchy_recovery_equal": True,
        "source_comments_and_processing_instructions": "preserved by byte-identical encoded retained witness; not inferred from historical ledger"}


def retained(member_id: str, root: Path = ROOT) -> bytes:
    spec = MEMBERS[member_id]
    if member_id.endswith("acts2"):
        raw, _ = old_authority(root)
    else:
        raw = (root / spec["path"]).read_bytes()
    if sha(raw) != spec["sha256"] or len(raw) != spec["bytes"]:
        raise ValueError(f"{member_id}: retained source identity differs")
    if sum(isinstance(x.tag, str) for x in parse(raw).iter()) != spec["elements"]:
        raise ValueError(f"{member_id}: retained source feature census differs")
    return raw


def scope_report(root: Path = ROOT) -> dict[str, object]:
    _, recovered = old_authority(root)
    rows = []
    for member_id, spec in MEMBERS.items():
        source = parse(retained(member_id, root))
        body = source.find("ThML.body")
        roots = [x for x in body if isinstance(x.tag, str)]
        header = source.find("ThML.head")
        rows.append({"member_id": member_id, **spec,
            "source_title": header.findtext("electronicEdInfo/DC/DC.Title"),
            "literal_print_statement": header.findtext("printSourceInfo/published"),
            "root_divisions": [{"id": x.get("id"), "title": x.get("title")} for x in roots],
            "body_comments": sum(x.tag is etree.Comment for x in body.iter()),
            "original_candidate": "repaired existing flat feature ledger" if spec["volume"] == 2 else "already-acquired and started companion; no prior TEI found in bounded searches"})
    return {"contract": "ocd-stokes-existing-two-volume-scope-v1", "status": "pass",
        "work_id": WORK_ID, "acquired_volume_count": 2, "included_volume_count": 2,
        "scope": "Both complete retained electronic volume editions; together Stokes's Acts commentary, not the entire Expositor series",
        "historical_gap": "LIB-034 included Acts II and explicitly excluded downloaded Acts I; old technical completion did not close this two-volume work",
        "authorization": "Existing acquired companion completion and existing TEI repair; no acquisition or download",
        "prior_no_tei_search_boundary": ["current ir filenames", "durable dated 8009-path TEI inventory", "exact LIB-034 temp roots", "Git filename history", "August 1 migration content manifest"],
        "unrelated_series_members": "outside this work; no inclusion or conversion here",
        "members": rows, "existing_acts2_ledger_reconciliation": recovered}


if __name__ == "__main__":
    destination = ROOT / LOG / "retained-scope-reconciliation.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(scope_report(), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(sha(destination.read_bytes()))
