"""Direct retained-witness reconstruction of the 1899 Douay-Rheims Bible."""

from __future__ import annotations

from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-douay-rheims-1899-direct-to-tei"
CONVERTER_VERSION = "1"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_USFM_NAME = re.compile(r"\d+-(?P<book>[0-9A-Z]+)engDRA\.usfm\Z")
_WORD = re.compile(r"""\\w (?P<surface>.*?)\|strong="(?P<strong>[^"]+)"\\w\*""")
_VERSE = re.compile(r"\\v (?P<number>\S+)(?: (?P<text>.*))?\Z")
_MARKER = re.compile(r"\\(?P<marker>[A-Za-z0-9]+)(?: (?P<value>.*))?\Z")
_HEADINGS = frozenset({"h", "toc1", "toc2", "toc3", "mt1", "mt2", "mt3", "cl"})
_SCAN = "raw/internet-archive/douay-rheims/1899-john-murphy-via-1971-tan/scan.pdf"
_OCR = "raw/internet-archive/douay-rheims/1899-john-murphy-via-1971-tan/ocr.xml"
_OCR_INVENTORY_SHA256 = (
    "8c321ec119ec5c8210bcde35e56ce1fee9edac6d2ed963c7ccb7f3ee4f9feabb"
)
_EVIDENCE_SHA256 = {
    "print_selections_sha256": "cf2cec519289d2c703034e07cf5c098186950fb3720a2d70657eae043fa1878d",
    "variant_triage_sha256": "b11a8cd32ec53d1f6f50122e61b4a3dda964f1752b15753a38cb418c802f9245",
    "structural_review_sha256": "16aa5d802287a4abf657e5ed0d85cc9f6696aa9e1fd00b9537085537340c2e52",
}
_STRUCTURAL_DISPOSITIONS: Mapping[str, Mapping[str, str]] = {
    "LAM.4.22": {
        "resolution": "print-derived-separate-prayer-heading",
        "selected_text": (
            "Thau. Thy iniquity is accomplished, O daughter of Sion, he will no "
            "more carry thee away into captivity: he hath visited thy iniquity, "
            "O daughter of Edom, he hath discovered thy sins."
        ),
        "verse_text": (
            "Thau. Thy iniquity is accomplished, O daughter of Sion, he will no "
            "more carry thee away into captivity: he hath visited thy iniquity, "
            "O daughter of Edom, he hath discovered thy sins."
        ),
        "heading": "THE PRAYER OF JEREMIAS THE PROPHET.",
        "placement": "before-next-chapter",
    },
    "PSA.132.1": {
        "resolution": "print-confirms-scrollmapper-reading-with-separate-print-prefix",
        "selected_text": (
            "A gradual canticle of David. Behold how good and how pleasant it is "
            "for brethren to dwell together in unity:"
        ),
        "verse_text": (
            "Behold how good and how pleasant it is for brethren to dwell "
            "together in unity:"
        ),
        "heading": "A gradual canticle of David.",
        "placement": "before-verse",
    },
    "PSA.138.1": {
        "resolution": "print-derived-body-with-separate-psalm-prefix",
        "selected_text": "Lord, thou hast proved me, and known me:",
        "verse_text": "Lord, thou hast proved me, and known me:",
        "heading": "Unto the end, a psalm of David.",
        "placement": "before-verse",
    },
    "PSA.142.1": {
        "resolution": "print-confirms-scrollmapper-prefix-with-separate-structural-node",
        "selected_text": (
            "A psalm of David, when his son Absalom pursued him. [2 Kings 17.] "
            "Hear, O Lord, my prayer: give ear to my supplication in thy truth: "
            "hear me in thy justice."
        ),
        "verse_text": (
            "Hear, O Lord, my prayer: give ear to my supplication in thy truth: "
            "hear me in thy justice."
        ),
        "heading": (
            "A psalm of David, when his son Absalom pursued him. [2 Kings 17.]"
        ),
        "placement": "before-verse",
    },
}
_SCROLL_NAME_BY_OSIS = {
    "GEN": "Genesis",
    "EXO": "Exodus",
    "LEV": "Leviticus",
    "NUM": "Numbers",
    "DEU": "Deuteronomy",
    "JOS": "Joshua",
    "JDG": "Judges",
    "RUT": "Ruth",
    "1SA": "I Samuel",
    "2SA": "II Samuel",
    "1KI": "I Kings",
    "2KI": "II Kings",
    "1CH": "I Chronicles",
    "2CH": "II Chronicles",
    "EZR": "Ezra",
    "NEH": "Nehemiah",
    "TOB": "Tobit",
    "JDT": "Judith",
    "EST": "Esther",
    "JOB": "Job",
    "PSA": "Psalms",
    "PRO": "Proverbs",
    "ECC": "Ecclesiastes",
    "SNG": "Song of Solomon",
    "WIS": "Wisdom",
    "SIR": "Sirach",
    "ISA": "Isaiah",
    "JER": "Jeremiah",
    "LAM": "Lamentations",
    "BAR": "Baruch",
    "EZK": "Ezekiel",
    "DAN": "Daniel",
    "HOS": "Hosea",
    "JOL": "Joel",
    "AMO": "Amos",
    "OBA": "Obadiah",
    "JON": "Jonah",
    "MIC": "Micah",
    "NAM": "Nahum",
    "HAB": "Habakkuk",
    "ZEP": "Zephaniah",
    "HAG": "Haggai",
    "ZEC": "Zechariah",
    "MAL": "Malachi",
    "1MA": "I Maccabees",
    "2MA": "II Maccabees",
    "MAT": "Matthew",
    "MRK": "Mark",
    "LUK": "Luke",
    "JHN": "John",
    "ACT": "Acts",
    "ROM": "Romans",
    "1CO": "I Corinthians",
    "2CO": "II Corinthians",
    "GAL": "Galatians",
    "EPH": "Ephesians",
    "PHP": "Philippians",
    "COL": "Colossians",
    "1TH": "I Thessalonians",
    "2TH": "II Thessalonians",
    "1TI": "I Timothy",
    "2TI": "II Timothy",
    "TIT": "Titus",
    "PHM": "Philemon",
    "HEB": "Hebrews",
    "JAS": "James",
    "1PE": "I Peter",
    "2PE": "II Peter",
    "1JN": "I John",
    "2JN": "II John",
    "3JN": "III John",
    "JUD": "Jude",
    "REV": "Revelation of John",
}
_OSIS_BY_SCROLL_NAME = {name: osis for osis, name in _SCROLL_NAME_BY_OSIS.items()}
_EBIBLE_MEMBER_COUNT = 73


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _authority(manifest: SourceManifest, name: str) -> Mapping[str, object]:
    matches = [
        item for item in manifest.record["authorities"] if item.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Douay authority {name!r} cardinality mismatch")
    return matches[0]


def _ebible_source_members(
    source_manifest: SourceManifest,
) -> tuple[tuple[Mapping[str, object], Path], ...]:
    members = source_manifest.record.get("source_members")
    authorities = source_manifest.record.get("authorities")
    if not isinstance(members, tuple) or len(members) != _EBIBLE_MEMBER_COUNT:
        raise ValueError(
            "Douay manifest must bind exactly 73 retained eBible USFM members"
        )
    if not isinstance(authorities, tuple):
        raise ValueError("Douay manifest authorities are invalid")
    by_name = {
        str(item["name"]): item
        for item in authorities
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }
    result: list[tuple[Mapping[str, object], Path]] = []
    names: set[str] = set()
    logical_names: set[str] = set()
    paths: set[str] = set()
    for member in members:
        if not isinstance(member, Mapping):
            raise ValueError("Douay eBible source member is invalid")
        name = member.get("name")
        logical_name = member.get("logical_name")
        authority = by_name.get(str(name))
        if (
            not isinstance(name, str)
            or name in names
            or not isinstance(logical_name, str)
            or logical_name in logical_names
            or member.get("role") != "primary-source"
            or authority is None
            or authority.get("role") != "primary-source"
            or any(
                member.get(key) != authority.get(key)
                for key in ("path", "bytes", "sha256")
            )
        ):
            raise ValueError(
                "Douay eBible source members must match distinct primary-source authorities"
            )
        match = _USFM_NAME.fullmatch(logical_name)
        if match is None or match.group("book") not in _SCROLL_NAME_BY_OSIS:
            raise ValueError(f"unsupported retained eBible member {logical_name!r}")
        path = source_manifest.authority_path(name)
        path_key = str(member["path"])
        if path_key in paths or path.suffix.lower() != ".usfm":
            raise ValueError("Douay eBible source members must be distinct USFM files")
        names.add(name)
        logical_names.add(logical_name)
        paths.add(path_key)
        result.append((member, path))
    return tuple(result)


def _json_lines(content: bytes, label: str) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for number, line in enumerate(content.splitlines(), 1):
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{label} line {number} is not an object")
        result.append(value)
    return result


def _structural_dispositions(
    records: list[dict[str, object]],
) -> Mapping[str, Mapping[str, str]]:
    by_address = {str(record.get("address")): record for record in records}
    if len(by_address) != len(records) or set(by_address) != set(
        _STRUCTURAL_DISPOSITIONS
    ):
        raise ValueError("structural-review address inventory drifted")
    for address, expected in _STRUCTURAL_DISPOSITIONS.items():
        record = by_address[address]
        if (
            record.get("status") != "open-structural-review"
            or record.get("textual_reading_status") != "print-text-decided"
            or record.get("textual_authority") != "direct-facsimile"
            or record.get("selected_witness")
            != "john-murphy-1899-via-tan-1971-facsimile"
            or record.get("resolution") != expected["resolution"]
            or record.get("selected_text") != expected["selected_text"]
        ):
            raise ValueError(f"structural-review disposition drifted: {address}")
        evidence = record.get("evidence")
        if (
            not isinstance(evidence, Mapping)
            or evidence.get("textual_authority") != "direct-facsimile"
            or expected["heading"].casefold()
            not in json.dumps(evidence, ensure_ascii=False).casefold()
        ):
            raise ValueError(f"structural-review facsimile evidence drifted: {address}")
    return _STRUCTURAL_DISPOSITIONS


def _gzip_json_lines(content: bytes, label: str) -> list[dict[str, object]]:
    return _json_lines(gzip.decompress(content), label)


def _plain_usfm(value: str) -> tuple[str, int]:
    output: list[str] = []
    position = annotations = 0
    for match in _WORD.finditer(value):
        output.extend((value[position : match.start()], match.group("surface")))
        position = match.end()
        annotations += 1
    output.append(value[position:])
    text = "".join(output)
    if "\\" in text:
        raise ValueError(f"unsupported inline USFM marker in verse: {text!r}")
    return text.strip(), annotations


def _load_ebible(source_manifest: SourceManifest) -> list[dict[str, object]]:
    books: list[dict[str, object]] = []
    for source_position, (member, path) in enumerate(
        _ebible_source_members(source_manifest), 1
    ):
        name = str(member["logical_name"])
        match = _USFM_NAME.fullmatch(name)
        assert match is not None
        osis = match.group("book")
        headings: list[dict[str, str]] = []
        verses: list[dict[str, object]] = []
        chapter: int | None = None
        poetry: str | None = None
        for raw in path.read_bytes().decode("utf-8-sig").splitlines():
            line = raw.strip()
            if not line:
                continue
            verse_match = _VERSE.fullmatch(line)
            if verse_match is not None:
                if chapter is None:
                    raise ValueError(f"{name}: verse before chapter")
                text, annotation_count = _plain_usfm(verse_match.group("text") or "")
                number = verse_match.group("number")
                verses.append(
                    {
                        "address": f"{osis}.{chapter}.{number}",
                        "book": osis,
                        "chapter": chapter,
                        "number": number,
                        "text": text,
                        "poetry": poetry,
                        "annotations": annotation_count,
                    }
                )
                poetry = None
                continue
            marker_match = _MARKER.fullmatch(line)
            if marker_match is None:
                raise ValueError(f"{name}: unsupported USFM line {line!r}")
            marker = marker_match.group("marker")
            value = (marker_match.group("value") or "").strip()
            if marker == "c":
                chapter, poetry = int(value), None
            elif marker == "q1":
                poetry = marker
            elif marker == "p":
                poetry = None
            elif marker in _HEADINGS:
                headings.append({"marker": marker, "text": value})
            elif marker == "id":
                if value.split(maxsplit=1)[0] != osis:
                    raise ValueError(f"{name}: ID does not match filename")
            else:
                raise ValueError(f"{name}: unsupported block marker {marker!r}")
        books.append(
            {
                "osis": osis,
                "source_position": source_position,
                "headings": headings,
                "verses": verses,
            }
        )
    if len(books) != 73:
        raise ValueError(f"expected 73 eBible books, found {len(books)}")
    return books


def _load_scrollmapper(
    content: bytes,
) -> tuple[list[dict[str, object]], list[str], str]:
    document = json.loads(content)
    if not isinstance(document, dict) or not isinstance(document.get("books"), list):
        raise ValueError("Scrollmapper authority shape mismatch")
    slots: list[dict[str, object]] = []
    order: list[str] = []
    for carrier_position, book in enumerate(document["books"], 1):
        osis = _OSIS_BY_SCROLL_NAME.get(book["name"])
        if osis is not None and osis not in order:
            order.append(osis)
        for chapter in book["chapters"]:
            for verse in chapter["verses"]:
                slots.append(
                    {
                        "carrier_position": carrier_position,
                        "carrier_name": book["name"],
                        "book": osis,
                        "chapter": chapter["chapter"],
                        "number": verse["verse"],
                        "text": verse["text"],
                        "address": f"{osis}.{chapter['chapter']}.{verse['verse']}"
                        if osis
                        else None,
                    }
                )
    return slots, order, str(document.get("translation", ""))


def _page_scope(number: int) -> tuple[str, str]:
    if number <= 4:
        return "outside-1899-edition", "scan-and-digitization-front"
    singles = {
        5: ("1971-carrier-only", "1971-half-title"),
        6: ("1899-edition", "1899-approbation"),
        7: (
            "mixed-facsimile-carrier",
            "1899-title-page-with-1971-publisher-substitution",
        ),
        8: ("1971-carrier-only", "1971-facsimile-publication-statement"),
        1097: ("1899-edition", "new-testament-title-page"),
        1098: ("1899-edition", "new-testament-contents"),
    }
    if number in singles:
        return singles[number]
    for start, end, role in (
        (9, 10, "1899-preface"),
        (11, 1096, "old-testament-scripture-and-apparatus"),
        (1099, 1393, "new-testament-scripture-and-apparatus"),
        (1394, 1399, "historical-and-chronological-index"),
        (1400, 1402, "reference-and-liturgical-tables"),
        (1403, 1414, "maps-and-plates"),
    ):
        if start <= number <= end:
            return "1899-edition", role
    raise ValueError(f"unexpected facsimile page {number}")


def _ocr_usemaps(path: Path) -> list[str]:
    values: list[str] = []
    for _, element in etree.iterparse(
        str(path), events=("end",), tag="OBJECT", load_dtd=False, no_network=True
    ):
        value = element.get("usemap")
        if value is None:
            raise ValueError("print OCR OBJECT has no usemap")
        values.append(value)
        element.clear()
    expected = [f"holybible00balt_{ordinal:04d}.djvu" for ordinal in range(1, 1415)]
    if (
        values != expected
        or len(set(values)) != 1414
        or _sha(_canonical(values)) != _OCR_INVENTORY_SHA256
    ):
        raise ValueError("print OCR ordered OBJECT inventory drifted")
    return values


def _heading(book: Mapping[str, object]) -> str:
    headings = book["headings"]
    assert isinstance(headings, list)
    for marker in ("toc2", "h", "toc1", "mt1"):
        for item in headings:
            if item["marker"] == marker:
                return str(item["text"])
    return str(book["osis"])


def _tei(
    books: list[dict[str, object]],
    order: list[str],
    selected: Mapping[str, str],
    structural: Mapping[str, Mapping[str, str]],
) -> bytes:
    root = etree.Element(f"{{{_TEI}}}TEI", nsmap={None: _TEI})
    header = etree.SubElement(root, f"{{{_TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{_TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{_TEI}}}titleStmt")
    etree.SubElement(
        title_stmt, f"{{{_TEI}}}title"
    ).text = "Douay-Rheims American Edition of 1899"
    publication = etree.SubElement(file_desc, f"{{{_TEI}}}publicationStmt")
    etree.SubElement(
        publication, f"{{{_TEI}}}p"
    ).text = "Wayfinder reconstruction candidate; not an accepted master."
    source_desc = etree.SubElement(file_desc, f"{{{_TEI}}}sourceDesc")
    etree.SubElement(source_desc, f"{{{_TEI}}}p").text = (
        "Verse text is derived from the 73 individually retained eBible engDRA USFM members. "
        "Witness-specific annotations and structural observations are retained in package sidecars."
    )
    facsimile = etree.SubElement(root, f"{{{_TEI}}}facsimile")
    for page in range(1, 1415):
        membership, role = _page_scope(page)
        surface = etree.SubElement(
            facsimile,
            f"{{{_TEI}}}surface",
            type="facsimile-page",
            n=str(page),
            ana=f"edition-membership:{membership} page-role:{role}",
            corresp=f"{_OCR}#page={page}",
        )
        surface.set(_XML_ID, f"dra-facsimile-page-{page}")
        etree.SubElement(surface, f"{{{_TEI}}}graphic", url=f"{_SCAN}#page={page}")
    body = etree.SubElement(
        etree.SubElement(root, f"{{{_TEI}}}text"), f"{{{_TEI}}}body"
    )
    by_osis = {str(book["osis"]): book for book in books}
    for position, osis in enumerate(order, 1):
        book = by_osis[osis]
        book_div = etree.SubElement(
            body, f"{{{_TEI}}}div", type="book", n=osis, corresp=f"urn:osis:{osis}"
        )
        book_div.set("subtype", "bible")
        book_div.set("source", f"ebible-source-position:{book['source_position']}")
        book_div.set("ana", f"edition-position:{position}")
        etree.SubElement(
            book_div, f"{{{_TEI}}}head", type="source-book-heading"
        ).text = _heading(book)
        chapters: dict[int, list[dict[str, object]]] = defaultdict(list)
        for verse in book["verses"]:
            chapters[int(verse["chapter"])].append(verse)
        for chapter, verses in chapters.items():
            if osis == "LAM" and chapter == 5:
                disposition = structural["LAM.4.22"]
                transition = etree.SubElement(
                    book_div,
                    f"{{{_TEI}}}div",
                    type="source-structural-transition",
                    corresp="urn:osis:LAM.4.22",
                )
                etree.SubElement(
                    transition,
                    f"{{{_TEI}}}head",
                    type="source-prayer-heading",
                ).text = disposition["heading"]
            chapter_div = etree.SubElement(
                book_div, f"{{{_TEI}}}div", type="chapter", n=str(chapter)
            )
            prefix_address = f"{osis}.{chapter}.1"
            if (
                prefix_address in structural
                and structural[prefix_address]["placement"] == "before-verse"
            ):
                etree.SubElement(
                    chapter_div,
                    f"{{{_TEI}}}head",
                    type="source-verse-prefix",
                    corresp=f"urn:osis:{prefix_address}",
                ).text = structural[prefix_address]["heading"]
            for verse in verses:
                address = str(verse["address"])
                node = etree.SubElement(
                    chapter_div,
                    f"{{{_TEI}}}ab",
                    type="verse",
                    n=str(verse["number"]),
                    corresp=f"urn:osis:{address}",
                )
                node.set(_XML_ID, f"dra-{osis.lower()}-{chapter}-{verse['number']}")
                node.text = (
                    structural[address]["verse_text"]
                    if address in structural
                    else selected.get(address, str(verse["text"]))
                )
    return etree.tostring(
        root, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    profile = json.loads(
        source_manifest.authority_path("reconstruction-profile").read_bytes()
    )
    scroll_content = source_manifest.authority_path("scrollmapper-json").read_bytes()
    selections_content = source_manifest.authority_path("print-selections").read_bytes()
    triage_content = source_manifest.authority_path("variant-triage").read_bytes()
    structural_content = source_manifest.authority_path(
        "structural-review"
    ).read_bytes()
    frozen = profile.get("frozen_evidence")
    if (
        not isinstance(frozen, dict)
        or any(frozen.get(name) != digest for name, digest in _EVIDENCE_SHA256.items())
        or frozen.get("ordered_ocr_object_usemaps_sha256") != _OCR_INVENTORY_SHA256
    ):
        raise ValueError("frozen Douay evidence profile pins drifted")
    if {
        "print_selections_sha256": _sha(selections_content),
        "variant_triage_sha256": _sha(triage_content),
        "structural_review_sha256": _sha(structural_content),
    } != _EVIDENCE_SHA256:
        raise ValueError("frozen Douay evidence bytes drifted")
    _ocr_usemaps(source_manifest.authority_path("print-ocr-xml"))
    books = _load_ebible(source_manifest)
    ebible_members = [
        {key: item[key] for key in ("name", "path", "bytes", "sha256")}
        for item, _ in _ebible_source_members(source_manifest)
    ]
    slots, order, translation = _load_scrollmapper(scroll_content)
    selections = _json_lines(selections_content, "print selections")
    triage = _gzip_json_lines(triage_content, "variant triage")
    structural = _json_lines(structural_content, "structural review")
    structural_dispositions = _structural_dispositions(structural)
    verses = [verse for book in books for verse in book["verses"]]
    verse_by_address = {str(item["address"]): str(item["text"]) for item in verses}
    scroll_by_address = {
        str(item["address"]): str(item["text"])
        for item in slots
        if item["book"] is not None
    }
    if len(order) != 73 or set(order) != {str(book["osis"]) for book in books}:
        raise ValueError(
            "retained witnesses do not establish the same 73-book inventory"
        )
    if (
        len(selections) != 599
        or len({str(item["address"]) for item in selections}) != 599
    ):
        raise ValueError("print-selection ledger must bind exactly 599 addresses")
    if (
        sum(
            item.get("print_evidence", {}).get("scan_path") == _SCAN
            for item in selections
        )
        != 553
    ):
        raise ValueError("print-selection portable scan-path census drifted")
    selected: dict[str, str] = {}
    for record in selections:
        address, text = str(record["address"]), str(record["selected_text"])
        if address not in verse_by_address:
            raise ValueError(f"selection address is absent from eBible: {address}")
        if record["selection"] == "ebible" and text != verse_by_address[address]:
            raise ValueError(f"eBible selection reading drifted: {address}")
        if record["selection"] == "scrollmapper" and text != scroll_by_address.get(
            address
        ):
            raw_scroll = scroll_by_address.get(address)
            if (
                address != "GEN.5.31"
                or not isinstance(raw_scroll, str)
                or text != raw_scroll.rstrip()
            ):
                raise ValueError(f"Scrollmapper selection reading drifted: {address}")
        selected[address] = text
    structural_by_address = {str(item["address"]): item for item in structural}
    unresolved = []
    for record in triage:
        if record.get("selection") != "unresolved":
            continue
        address = str(record["address"])
        unresolved.append(
            {
                **record,
                "ebible_text": verse_by_address[address],
                "scrollmapper_text": scroll_by_address[address],
                **(
                    {"structural_review": structural_by_address[address]}
                    if address in structural_by_address
                    else {}
                ),
            }
        )
    if len(unresolved) != 3025 or not set(structural_by_address) <= {
        str(item["address"]) for item in unresolved
    }:
        raise ValueError("unresolved or structural-review census drifted")
    selection_counts = Counter(str(item["selection"]) for item in selections)
    accountability = {
        "contract": "ocd-douay-rheims-1899-source-accountability-v1",
        "schema": "douay-rheims-1899.source-accountability.schema.json",
        "source_members": [
            {key: item[key] for key in ("name", "path", "bytes", "sha256")}
            for item in source_manifest.record["authorities"]
            if item.get("role") == "primary-source"
        ],
        "counts": {
            "books": len(books),
            "chapters": len({(item["book"], item["chapter"]) for item in verses}),
            "verses": len(verses),
            "facsimile_pages": 1414,
            "ebible_annotations": sum(int(item["annotations"]) for item in verses),
            "ebible_poetry_markers": sum(item["poetry"] is not None for item in verses),
            "scrollmapper_slots": len(slots),
            "scrollmapper_empty_slots": sum(not item["text"] for item in slots),
            "scrollmapper_empty_book_shells": len(
                {item["carrier_name"] for item in slots if item["book"] is None}
            ),
            "print_selections": len(selections),
            "ebible_selections": selection_counts["ebible"],
            "scrollmapper_selections": selection_counts["scrollmapper"],
            "print_derived_selections": selection_counts["print-derived"],
            "unresolved_differences": len(unresolved),
            "structural_cases": len(structural),
        },
        "digests": {
            "edition_order_sha256": _sha(_canonical(order)),
            "verse_address_inventory_sha256": _sha(
                _canonical([item["address"] for item in verses])
            ),
            "selected_readings_sha256": _sha(_canonical(selected)),
            "unresolved_address_inventory_sha256": _sha(
                _canonical([item["address"] for item in unresolved])
            ),
        },
        "omitted_verse_count": 0,
        "duplicate_verse_count": 0,
        "candidate_status": "nonaccepted",
        "human_review_required": True,
        "publication_ready": False,
        "print_apparatus_status": "incomplete",
        "source_only_features": {
            "strong_annotations": "eBible witness annotations; not asserted as 1899 print content",
            "poetry_markers": "eBible witness structure; not asserted as print layout",
        },
    }
    provenance = {
        "contract": "ocd-douay-rheims-1899-provenance-v1",
        "edition_id": "douay-rheims-american-1899",
        "source_manifest_sha256": source_manifest.sha256,
        "profile_id": profile["profile_id"],
        "candidate_status": "nonaccepted",
        "human_acceptance": "not performed",
        "publication": "not authorized or ready",
        "primary_text_witness": {
            "members": ebible_members,
            "source_member_set_sha256": _sha(
                _canonical(
                    {
                        "contract": "ocd-source-member-set-v1",
                        "members": sorted(
                            ebible_members,
                            key=lambda item: (str(item["path"]), str(item["name"])),
                        ),
                    }
                )
            ),
        },
        "acquisition_archive": {
            "path": _authority(source_manifest, "ebible-usfm-archive")["path"],
            "bytes": _authority(source_manifest, "ebible-usfm-archive")["bytes"],
            "sha256": _authority(source_manifest, "ebible-usfm-archive")["sha256"],
            "role": "acquisition/archive-provenance",
        },
        "secondary_text_witness": {
            "path": _authority(source_manifest, "scrollmapper-json")["path"],
            "sha256": _sha(scroll_content),
            "claim": translation,
        },
        "print_control": {
            "scan_path": _SCAN,
            "scan_sha256": _authority(source_manifest, "print-pdf")["sha256"],
            "ocr_path": _OCR,
            "ocr_sha256": _authority(source_manifest, "print-ocr-xml")["sha256"],
        },
        "selection_ledger_sha256": _sha(selections_content),
        "triage_ledger_sha256": _sha(triage_content),
        "structural_review_ledger_sha256": _sha(structural_content),
        "page_correspondence": "each TEI surface links to the retained PDF graphic and OCR XML page by repository-relative URI",
    }
    readme = (
        "# Douay-Rheims American Edition of 1899 reconstruction candidate\n\n"
        "This six-member package is a deterministic, nonaccepted candidate reconstructed from 73 individually retained eBible engDRA USFM members, a retained Scrollmapper witness, frozen print-selection and triage ledgers, and a retained 1899 facsimile carried by the 1971 TAN reproduction. The original eBible ZIP is retained only as acquisition/archive provenance.\n\n"
        "The candidate preserves 73 books, 1,334 chapters, 35,811 verses, 1,414 facsimile surfaces, 599 print-supported selections, 3,025 unresolved substantive differences, and four open structural cases. Strong annotations and poetry markers are retained source-witness facts, not claims about 1899 print content. The wider print apparatus remains incomplete. Human acceptance has not occurred, and publication is neither authorized nor ready.\n"
    ).encode("utf-8")
    return {
        "content.tei.xml": _tei(books, order, selected, structural_dispositions),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
