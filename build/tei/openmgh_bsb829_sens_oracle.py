"""Independent retained-XML check for the Bishops of Sens letter."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256

from lxml import etree

TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
START = "bsb00000829_00657_19"
HEADING = "bsb00000829_00657_20"
SALUTATION = "bsb00000829_00657_21"
END = "bsb00000829_00662_20"
NEXT = "bsb00000829_00662_21"
REPLY = "bsb00000829_00662_22"


def _parse(data: bytes) -> etree._Element:
    root = etree.fromstring(data, etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True,
        remove_comments=False, huge_tree=True,
    ))
    if root.getroottree().docinfo.doctype:
        raise ValueError("DOCTYPE is forbidden")
    return root


def _same(a: etree._Element, b: etree._Element, *, root: bool = False) -> bool:
    return (a.tag == b.tag and dict(a.attrib) == dict(b.attrib)
            and a.text == b.text and (root or a.tail == b.tail)
            and len(a) == len(b)
            and all(_same(x, y) for x, y in zip(a, b, strict=True)))


def check(source_bytes: bytes, candidate_bytes: bytes) -> dict:
    source, candidate = _parse(source_bytes), _parse(candidate_bytes)
    body = source.find(f"{TEI}text/{TEI}body")
    if body is None or len(body) != 1 or body[0].get("type") != "volume":
        raise ValueError("source volume differs")
    divisions = list(body[0])
    if len(divisions) != 21 or len(divisions[16]) != 1:
        raise ValueError("source division 17 differs")
    ab = divisions[16][0]
    if ab.tag != f"{TEI}ab":
        raise ValueError("source carrier is not ab")
    children = list(ab)
    counts = Counter(node.get(XML_ID) for node in source.iter() if node.get(XML_ID))
    markers = (START, HEADING, SALUTATION, END, NEXT, REPLY)
    if any(counts[marker] != 1 for marker in markers):
        raise ValueError("source line marker absent or duplicated")
    positions = {child.get(XML_ID): i for i, child in enumerate(children) if child.get(XML_ID)}
    first, heading, salutation, final, following, reply = (positions[m] for m in markers)
    if not (first + 1 == heading and heading + 1 == salutation
            and final + 1 == following and following + 1 == reply
            and all(children[i].tag == f"{TEI}lb" for i in
                    (first, heading, salutation, final, following, reply))):
        raise ValueError("letter line boundaries differ")
    if ((children[first].tail or "").strip() != "1."
            or "Ivonis epistola ad Ioscerannum" not in (children[heading].tail or "")
            or "Iosceranno Dei gratia" not in (children[salutation].tail or "")
            or not (children[final].tail or "").strip().endswith("Valete.")
            or (children[following].tail or "").strip() != "2."
            or "Iosceranni responsio" not in (children[reply].tail or "")):
        raise ValueError("source letter and reply wording differs")
    expected = etree.Element(f"{TEI}ab", attrib=dict(ab.attrib))
    for node in children[first:following]:
        expected.append(deepcopy(node))
    selected_ids = {node.get(XML_ID) for node in expected.iter() if node.get(XML_ID)}
    for node in expected.iter():
        for name in ("corresp", "target"):
            for ref in (node.get(name) or "").split():
                if not ref.startswith("#") or ref[1:] not in selected_ids:
                    raise ValueError(f"external {name} target: {node.get(XML_ID)} {ref}")
    actual_body = candidate.find(f"{TEI}text/{TEI}body")
    if (candidate.tag != f"{TEI}TEI" or actual_body is None
            or len(actual_body) != 1 or actual_body[0].get("type") != "work"
            or len(actual_body[0]) != 1
            or not _same(expected, actual_body[0][0], root=True)):
        raise ValueError("candidate body does not match the full source selection")
    original_file = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    new_file = candidate.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if original_file is None or new_file is None:
        raise ValueError("file description absent")
    for path in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        a, b = original_file.find(path), new_file.find(path)
        if a is None or b is None or not _same(a, b, root=True):
            raise ValueError("electronic rights or print bibliography differs")
    return {
        "status": "pass", "source_sha256": sha256(source_bytes).hexdigest(),
        "candidate_sha256": sha256(candidate_bytes).hexdigest(),
        "first_child_index": first, "last_child_index": final,
        "next_child_index": following, "selected_child_count": following - first,
        "selected_c14n_sha256": sha256(etree.tostring(
            expected, method="c14n", with_comments=True)).hexdigest(),
        "outside_fragment_target_count": 0,
    }
