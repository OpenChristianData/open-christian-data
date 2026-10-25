"""Independent complete-line-tree oracle for bsb830's seven simony poems."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000830/tei/bsb00000830.xml")
SOURCE_SHA = "bb97bf6037a31d6a6c37f0e967aa23e9df1933bdd688fe4aaa84e5e034ff67ac"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
CONTRACT = "ocd-openmgh-bsb830-simony-seven-source-oracle-v1"
SPANS = {
    "decrees-of-simon-poem": (4, 102, "bsb00000830_00706_16", "bsb00000830_00707_72"),
    "satis-verba-varia-poem": (103, 129, "bsb00000830_00707_73", "bsb00000830_00708_18"),
    "nicolaus-verses-on-abbots-entering-christs-fold": (130, 179, "bsb00000830_00709_23", "bsb00000830_00710_30"),
    "verses-on-roman-avarice": (180, 229, "bsb00000830_00710_31", "bsb00000830_00712_29"),
    "wilhelmus-metrical-address-to-wibert": (230, 275, "bsb00000830_00713_9", "bsb00000830_00714_24"),
    "gens-romanorum-subdola-poem": (276, 404, "bsb00000830_00715_11", "bsb00000830_00716_60"),
    "magister-peter-verses-against-simony": (405, 479, "bsb00000830_00717_19", "bsb00000830_00719_25"),
}


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _same(source: etree._Element, target: etree._Element, *, outer: bool = False) -> bool:
    if (source.tag != target.tag or dict(source.attrib) != dict(target.attrib)
            or source.text != target.text or len(source) != len(target)
            or not outer and source.tail != target.tail):
        return False
    return all(_same(left, right) for left, right in zip(source, target, strict=True))


def check(work_id: str, candidate_bytes: bytes, *, source_override: bytes | None = None) -> dict:
    if work_id not in SPANS:
        raise ValueError(f"bsb830 simony work not selected: {work_id}")
    source_bytes = source_override if source_override is not None else _io_path(ROOT / SOURCE).read_bytes()
    if _sha(source_bytes) != SOURCE_SHA:
        raise ValueError("bsb830 retained XML changed")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True)
    source = etree.fromstring(source_bytes, parser)
    candidate = etree.fromstring(candidate_bytes, parser)
    if (source.tag != TEI + "TEI" or candidate.tag != TEI + "TEI"
            or source.getroottree().docinfo.doctype or candidate.getroottree().docinfo.doctype):
        raise ValueError("bsb830 source or candidate envelope changed")
    source_body = source.find(TEI + "text/" + TEI + "body")
    candidate_body = candidate.find(TEI + "text/" + TEI + "body")
    if (source_body is None or len(source_body) != 1 or len(source_body[0]) != 29
            or candidate_body is None or len(candidate_body) != 1
            or candidate_body[0].tag != TEI + "div" or candidate_body[0].get("type") != "work"
            or len(candidate_body[0]) != 1 or candidate_body[0][0].tag != TEI + "ab"):
        raise ValueError("bsb830 candidate is not one source-bound poem")
    division = source_body[0][24]
    if (division.get("n") != "Carmina in simoniam et Romanorum avaritiam"
            or division.get("type") != "work" or len(division) != 1
            or division[0].tag != TEI + "ab" or len(division[0]) != 480):
        raise ValueError("bsb830 source division 25 changed")
    children = list(division[0])
    spans = sorted((start, end) for start, end, _, _ in SPANS.values())
    if spans != [(4, 102), (103, 129), (130, 179), (180, 229), (230, 275), (276, 404), (405, 479)]:
        raise ValueError("bsb830 source node partition changed")
    start, end, first_id, last_id = SPANS[work_id]
    work = json.loads(_io_path(ROOT / "library/works" / work_id / "work.json").read_bytes())
    edition = work["textual_forms"][0]["editions"][0]
    declared = [part.split("#", 1)[1] for part in edition["containing_source"]["locator"].split("; ")]
    if (work["work_id"] != work_id or declared != [first_id, last_id]
            or candidate_body[0].get("n") != work["title"]):
        raise ValueError("bsb830 catalog identity or locator differs")
    header = source.find(TEI + "teiHeader")
    candidate_header = candidate.find(TEI + "teiHeader")
    if header is None or candidate_header is None or not _same(header, candidate_header, outer=True):
        raise ValueError("bsb830 source publication, license, or bibliography differs")
    expected = etree.Element(TEI + "ab", attrib=dict(division[0].attrib))
    for node in children[start:end + 1]:
        expected.append(deepcopy(node))
    actual = candidate_body[0][0]
    if not _same(expected, actual, outer=True):
        raise ValueError("bsb830 source and candidate poem trees differ")
    occurrences = Counter(node.get(XML_ID) for node in source.iter() if node.get(XML_ID))
    ids = [node.get(XML_ID) for node in expected.iter() if node.get(XML_ID)]
    if (occurrences[first_id] != 1 or occurrences[last_id] != 1
            or ids.count(first_id) != 1 or ids.count(last_id) != 1
            or ids.index(first_id) > ids.index(last_id)
            or expected[-1].get(XML_ID) != last_id):
        raise ValueError("bsb830 complete poem locator boundary differs")
    selected = set(ids)
    for node in expected.iter():
        for key in ("target", "corresp"):
            value = node.get(key)
            if value and any(not ref.startswith("#") or ref[1:] not in selected for ref in value.split()):
                raise ValueError("bsb830 poem has outside fragment target")
    shared = children[:4]
    shared_text = " ".join(" ".join((node.tail or "") for node in shared).split())
    if "CARMINA IN SIMONIAM ET ROMANORUM AVARITIAM." not in shared_text:
        raise ValueError("bsb830 shared collection heading differs")
    return dict(contract=CONTRACT, work_id=work_id, source_sha256=SOURCE_SHA,
                candidate_sha256=_sha(candidate_bytes), source_division_ordinal=25,
                source_division_child_count=480, selected_child_start=start, selected_child_end=end,
                selected_child_count=end - start + 1, selected_xml_id_count=len(ids),
                catalog_first_xml_id=first_id, catalog_last_xml_id=last_id,
                selection_c14n_sha256=_sha(etree.tostring(expected, method="c14n", with_comments=True)),
                shared_heading_child_indexes=[0, 1, 2, 3],
                outside_fragment_count=0, source_tree="pass", header="pass")
