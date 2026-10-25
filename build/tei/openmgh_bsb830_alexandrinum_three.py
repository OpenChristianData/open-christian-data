"""Extract three complete numbered poems from bsb830 division 8."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000830/tei/bsb00000830.xml")
SOURCE_SHA = "bb97bf6037a31d6a6c37f0e967aa23e9df1933bdd688fe4aaa84e5e034ff67ac"
PACKAGE = Path("raw/openmgh/bsb00000830/bsb00000830.zip")
PACKAGE_SHA = "3cc84719875aec1c7a3bceb9cb754f55d191705bce73f628f93135bad6e8f1e5"
ACQUISITION_RECEIPT = Path("raw/openmgh/bsb00000830/acquisition-receipt.json")
ACQUISITION_RECEIPT_SHA = "6937a8c05fc2c094ae1b9ab57f34fe639e77972877976474ba2513de0d8b885c"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
CONTRACT = "ocd-openmgh-bsb830-alexandrinum-three-p5-v1"
DIVISION = 9
SELECTED = {
    "cause-of-the-two-popes-octavian-and-alexander": (
        5, 116, "bsb00000830_00557_11", "bsb00000830_00559_41"),
    "verses-against-octavian": (
        117, 194, "bsb00000830_00560_1", "bsb00000830_00561_30"),
    "de-apostolicis-poem": (
        195, 234, "bsb00000830_00561_31", "bsb00000830_00562_26"),
}


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _source() -> tuple[bytes, etree._Element, list[etree._Element]]:
    content = _io_path(ROOT / SOURCE).read_bytes()
    if _sha(content) != SOURCE_SHA or _sha(_io_path(ROOT / PACKAGE).read_bytes()) != PACKAGE_SHA:
        raise ValueError("bsb830 extracted source or acquisition package changed")
    if _sha(_io_path(ROOT / ACQUISITION_RECEIPT).read_bytes()) != ACQUISITION_RECEIPT_SHA:
        raise ValueError("bsb830 acquisition receipt changed")
    root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True,
                                                     remove_comments=False, huge_tree=True))
    if root.getroottree().docinfo.doctype or root.tag != TEI + "TEI":
        raise ValueError("bsb830 source envelope changed")
    body = root.find(TEI + "text/" + TEI + "body")
    if body is None or len(body) != 1 or len(body[0]) != 29:
        raise ValueError("bsb830 29-work volume changed")
    division = body[0][DIVISION - 1]
    if (division.tag != TEI + "div" or division.get("type") != "work"
            or division.get("n") != "Carmina ad schisma Alexandrinum pert."
            or len(division) != 1 or division[0].tag != TEI + "ab"
            or division[0].text != "\n" or len(division[0]) != 235):
        raise ValueError("bsb830 Alexandrinum flat collection changed")
    children = list(division[0])
    if ([(start, end) for start, end, _, _ in sorted(SELECTED.values())]
            != [(5, 116), (117, 194), (195, 234)]
            or children[117].tag != TEI + "pb"
            or children[117].get(XML_ID) != "bsb00000830_00560"):
        raise ValueError("bsb830 three-span partition or boundary page changed")
    return content, root, children


def convert(work_id: str) -> tuple[bytes, dict]:
    if work_id not in SELECTED:
        raise ValueError(f"bsb830 Alexandrinum work not selected: {work_id}")
    source_bytes, source, children = _source()
    work = json.loads(_io_path(ROOT / "library/works" / work_id / "work.json").read_bytes())
    state = json.loads(_io_path(ROOT / "library/works" / work_id / "state.json").read_bytes())
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    targets = [item for item in state["targets"]
               if item["target_type"] == "edition" and item["target_id"] == edition["edition_id"]]
    if (work["work_id"] != work_id or len(work["textual_forms"]) != 1
            or len(form["editions"]) != 1 or len(targets) != 1 or targets[0]["stage"] != "acquired"):
        raise ValueError("bsb830 Alexandrinum work is not uniquely unaccepted")
    start, end, first_id, last_id = SELECTED[work_id]
    catalog = [part.split("#", 1)[1] for part in edition["containing_source"]["locator"].split("; ")]
    if catalog != [first_id, last_id]:
        raise ValueError("bsb830 Alexandrinum catalog locator pair differs")
    selected = children[start:end + 1]
    occurrences = {id: sum(node.get(XML_ID) == id for node in source.iter()) for id in (first_id, last_id)}
    ids = [node.get(XML_ID) for child in selected for node in child.iter() if node.get(XML_ID)]
    if (occurrences != {first_id: 1, last_id: 1} or first_id not in ids or last_id not in ids
            or ids.index(first_id) > ids.index(last_id) or selected[-1].get(XML_ID) != last_id
            or any(node.tag in {TEI + "gap", TEI + "unclear"} for child in selected for node in child.iter())):
        raise ValueError("bsb830 Alexandrinum complete source span differs")
    selected_ids = set(ids)
    for child in selected:
        for node in child.iter():
            for key in ("target", "corresp"):
                value = node.get(key)
                if value and any(not ref.startswith("#") or ref[1:] not in selected_ids for ref in value.split()):
                    raise ValueError(f"bsb830 Alexandrinum outside-source fragment: {work_id} {key}")
    result = etree.Element(TEI + "TEI", nsmap=source.nsmap)
    result.set(XML_ID, f"ocd-{work_id}-openmgh-bsb830-v1")
    result.append(deepcopy(source.find(TEI + "teiHeader")))
    body = etree.SubElement(etree.SubElement(result, TEI + "text"), TEI + "body")
    division = etree.SubElement(body, TEI + "div", type="work", n=work["title"])
    ab = etree.SubElement(division, TEI + "ab")
    source_selection = etree.Element(TEI + "ab")
    for child in selected:
        ab.append(deepcopy(child))
        source_selection.append(deepcopy(child))
    content = etree.tostring(result, encoding="UTF-8", xml_declaration=True)
    report = dict(contract=CONTRACT, work_id=work_id, source_path=SOURCE.as_posix(),
                  source_sha256=_sha(source_bytes), package_path=PACKAGE.as_posix(),
                  package_sha256=PACKAGE_SHA, source_division_ordinal=DIVISION,
                  source_division_n="Carmina ad schisma Alexandrinum pert.",
                  source_child_start=start, source_child_end=end,
                  catalog_first_xml_id=first_id, catalog_last_xml_id=last_id,
                  selected_child_count=len(selected), selected_xml_id_count=len(ids),
                  selected_c14n_sha256=_sha(etree.tostring(source_selection, method="c14n", with_comments=True)),
                  candidate_sha256=_sha(content), candidate_bytes=len(content),
                  shared_heading_child_indexes=[0, 1, 2, 3, 4],
                  boundary_page=dict(child_index=117, xml_id="bsb00000830_00560",
                                     owner="verses-against-octavian"),
                  disposition="Three disjoint poem spans partition direct children 5 through 234. "
                              "Children 0 through 4 are shared collection heading and preceding pagination; "
                              "page marker 117 opens the second poem's page and belongs to that span.")
    return content, report
