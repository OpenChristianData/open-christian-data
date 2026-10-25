"""Independent retained-source oracle for Rupert's complete bsb622 work."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree

TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_SHA256 = "94770b7657fb9da5bac46e6254aa9e8fb2c4b5eb136d7828f2e391c5ae76dc7e"
HEADING = "bsb00000622_00062_1"
LAST_LINE = "bsb00000622_00487_21"
INCIPIT_ROMANS = ("I", "II", "III", "IIII", "V", "VI", "VII", "VIII", "IX",
                 "X", "XI", "XII", "XIII")
EXPLICIT_ROMANS = ("I", "II", "III", "IIII", "V", "VI", "VII", "VIII", "VIIII",
                  "X", "XI", "XII", "XIII")


def _parse(data: bytes) -> etree._Element:
    root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True,
                                                  remove_comments=False, huge_tree=True))
    if root.getroottree().docinfo.doctype or root.tag != f"{TEI}TEI":
        raise ValueError("entity-free TEI root required")
    return root


def _equal(left: etree._Element, right: etree._Element, *, outer: bool = False) -> bool:
    if (left.tag != right.tag or dict(left.attrib) != dict(right.attrib)
            or left.text != right.text or len(left) != len(right)):
        return False
    if not outer and left.tail != right.tail:
        return False
    return all(_equal(a, b) for a, b in zip(left, right, strict=True))


def source_span(source_bytes: bytes, number: int) -> tuple[etree._Element, dict]:
    if number != 0 or sha256(source_bytes).hexdigest() != SOURCE_SHA256:
        raise ValueError("bsb622 Rupert selection or source hash changed")
    root = _parse(source_bytes)
    ns = {"t": TEI[1:-1]}
    volumes = root.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volumes) != 1 or len(volumes[0]) != 1:
        raise ValueError("bsb622 single-work volume changed")
    carrier = volumes[0][0]
    if (carrier.tag != f"{TEI}div" or carrier.get("type") != "work"
            or carrier.get("n") != "Rup. Deutz Vict." or len(carrier) != 15
            or carrier[0].tag != f"{TEI}ab" or len(carrier[0]) != 2
            or carrier[0][0].tag != f"{TEI}pb"
            or carrier[0][0].get(XML_ID) != "bsb00000622_00062"
            or carrier[0][1].tag != f"{TEI}lb"
            or carrier[0][1].get(XML_ID) != HEADING
            or (carrier[0][1].tail or "").strip() != "DE VICTORIA VERBI DEI LIBRI XIII"):
        raise ValueError("Rupert work title or whole-volume boundary changed")
    for index, part in enumerate(carrier[1:]):
        if (part.tag != f"{TEI}div" or part.get("type") != "part"
                or len(part) != 1 or part[0].tag != f"{TEI}ab"):
            raise ValueError(f"Rupert native part {index} changed")
        text = " ".join("".join(part.itertext()).split())
        if index == 0:
            if not text.startswith("[PROLOGUS ") or not text.endswith("[EXPLICIT PROLOGUS]"):
                raise ValueError("Rupert prologue boundary changed")
        elif (not text.startswith(f"INCIPIT LIBER {INCIPIT_ROMANS[index - 1]}.")
              or not text.endswith(f"EXPLICIT LIBER {EXPLICIT_ROMANS[index - 1]}.")):
            raise ValueError(f"Rupert book {index} incipit or explicit changed")
    if (carrier[-1][0][-1].tag != f"{TEI}lb"
            or carrier[-1][0][-1].get(XML_ID) != LAST_LINE
            or (carrier[-1][0][-1].tail or "").strip() != "EXPLICIT LIBER XIII."):
        raise ValueError("Rupert final explicit changed")
    nodes = list(carrier.iter())
    profile = {"lb": 13967, "w": 6934, "hi": 5933, "pb": 426, "div": 15, "ab": 15}
    if {tag: sum(node.tag == f"{TEI}{tag}" for node in nodes) for tag in profile} != profile:
        raise ValueError("Rupert whole-work node profile changed")
    pages = [node for node in nodes if node.tag == f"{TEI}pb"]
    expected_pages = [f"bsb00000622_{page:05d}" for page in range(62, 488)]
    if ([node.get(XML_ID) for node in pages] != expected_pages
            or [node.get("n", "").strip("()") for node in pages]
               != [str(page) for page in range(1, 427)]):
        raise ValueError("Rupert whole-work pagination changed")
    ids = [node.get(XML_ID) for node in nodes if node.get(XML_ID)]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate Rupert De victoria IDs")
    return carrier, {
        "number": number, "source_child_start": 0, "source_child_end": 14,
        "source_heading_id": HEADING, "source_last_line_id": LAST_LINE,
        "source_end_id": LAST_LINE,
        "following_heading_id": None, "following_boundary_page": None,
        "book_count": 13, "line_count": 13967,
        "internal_page_break": expected_pages, "source_word_count": 6934,
        "source_highlight_count": 5933, "source_carrier_division_index": 0,
    }


def check_candidate(source_bytes: bytes, candidate_bytes: bytes,
                    work: dict, acquisition: dict, *, number: int) -> dict:
    selected, details = source_span(source_bytes, number)
    if (acquisition.get("source_sha256") != SOURCE_SHA256
            or acquisition.get("source_path") != "raw/openmgh/bsb00000622/tei/bsb00000622.xml"):
        raise ValueError("acquisition/source binding changed")
    declared = work["textual_forms"][0]["editions"][0]["containing_source"]["locator"]
    path = "raw/openmgh/bsb00000622/tei/bsb00000622.xml"
    if (work.get("title") != "Rupert von Deutz, De victoria verbi Dei"
            or declared != f"{path}#teiHeader/fileDesc/sourceDesc/biblFull/titleStmt/title"):
        raise ValueError("catalog work identity differs")
    source, candidate = _parse(source_bytes), _parse(candidate_bytes)
    ns = {"t": TEI[1:-1]}
    works = candidate.xpath("/t:TEI/t:text/t:body/t:div[@type='work']", namespaces=ns)
    if len(works) != 1 or works[0].get("n") != "Rup. Deutz Vict.":
        raise ValueError("candidate work wrapper differs")
    if not _equal(selected, works[0]):
        raise ValueError("candidate native Rupert De victoria changed")
    titles = candidate.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=ns)
    if len(titles) != 1 or titles[0].text != work["title"]:
        raise ValueError("candidate title differs")
    old_file = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    new_file = candidate.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if old_file is None or new_file is None:
        raise ValueError("source/candidate header absent")
    for suffix in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        old, new = old_file.find(suffix), new_file.find(suffix)
        if old is None or new is None or not _equal(old, new, outer=True):
            raise ValueError("source publication or bibliography changed")
    return {"status": "pass", **details, "source_sha256": SOURCE_SHA256,
            "mapping": "complete sole Rupert work division: title, prologue, and thirteen books"}
