"""Independent retained-source oracle for the direct Douay-Rheims candidate."""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-douay-rheims-1899-independent-source-oracle"
ORACLE_VERSION = "1"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_NS = {"tei": _TEI, "xml": "http://www.w3.org/XML/1998/namespace"}
_FILE = re.compile(r"\d+-([0-9A-Z]+)engDRA\.usfm\Z")
_VERSE_LINE = re.compile(r"\\v (\S+)(?: (.*))?\Z")
_BLOCK_LINE = re.compile(r"\\([A-Za-z0-9]+)(?: (.*))?\Z")
_ANNOTATED_WORD = re.compile(r"""\\w (.*?)\|strong="[^"]+"\\w\*""")
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
_NAMES = {
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
_OSIS = {name: osis for osis, name in _NAMES.items()}
_HEADING_MARKERS = frozenset({"h", "toc1", "toc2", "toc3", "mt1", "mt2", "mt3", "cl"})
_EBIBLE_MEMBER_COUNT = 73


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _digest(value: object) -> str:
    return _sha(_canonical(value))


def _strict(content: bytes, label: str) -> dict[str, object]:
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value


def _records(content: bytes, label: str) -> list[dict[str, object]]:
    rows = []
    for number, line in enumerate(content.splitlines(), 1):
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{label} line {number} is not an object")
        rows.append(value)
    return rows


def _structural_dispositions(
    records: list[dict[str, object]],
) -> Mapping[str, Mapping[str, str]]:
    by_address = {str(record.get("address")): record for record in records}
    if len(by_address) != len(records) or set(by_address) != set(
        _STRUCTURAL_DISPOSITIONS
    ):
        raise ValueError("Douay structural-review address inventory mutation")
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
            raise ValueError(
                f"Douay structural-review disposition mutation at {address}"
            )
        evidence = record.get("evidence")
        if (
            not isinstance(evidence, Mapping)
            or evidence.get("textual_authority") != "direct-facsimile"
            or expected["heading"].casefold()
            not in json.dumps(evidence, ensure_ascii=False).casefold()
        ):
            raise ValueError(
                f"Douay structural-review facsimile evidence mutation at {address}"
            )
    return _STRUCTURAL_DISPOSITIONS


def _authority(manifest: SourceManifest, name: str) -> Mapping[str, object]:
    rows = [item for item in manifest.record["authorities"] if item.get("name") == name]
    if len(rows) != 1:
        raise ValueError(f"independent Douay authority {name!r} cardinality mismatch")
    return rows[0]


def _surface_text(value: str) -> tuple[str, int]:
    cursor = annotations = 0
    fragments: list[str] = []
    for match in _ANNOTATED_WORD.finditer(value):
        fragments.extend((value[cursor : match.start()], match.group(1)))
        cursor = match.end()
        annotations += 1
    fragments.append(value[cursor:])
    text = "".join(fragments)
    if "\\" in text:
        raise ValueError("independent parser found unsupported inline USFM")
    return text.strip(), annotations


def _retained_ebible_members(
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
        match = _FILE.fullmatch(logical_name)
        if match is None or match.group(1) not in _NAMES:
            raise ValueError(
                f"independent parser rejected USFM member {logical_name!r}"
            )
        path = source_manifest.authority_path(name)
        path_key = str(member["path"])
        if path_key in paths or path.suffix.lower() != ".usfm":
            raise ValueError("Douay eBible source members must be distinct USFM files")
        names.add(name)
        logical_names.add(logical_name)
        paths.add(path_key)
        result.append((member, path))
    return tuple(result)


def _parse_members(
    source_manifest: SourceManifest,
) -> list[dict[str, object]]:
    result = []
    for ordinal, (member, path) in enumerate(
        _retained_ebible_members(source_manifest), 1
    ):
        logical_name = str(member["logical_name"])
        match = _FILE.fullmatch(logical_name)
        assert match is not None
        book = match.group(1)
        headings: list[tuple[str, str]] = []
        verses: list[dict[str, object]] = []
        chapter: int | None = None
        poetry = False
        for source_line in path.read_bytes().decode("utf-8-sig").splitlines():
            line = source_line.strip()
            if not line:
                continue
            verse_match = _VERSE_LINE.fullmatch(line)
            if verse_match:
                if chapter is None:
                    raise ValueError("independent parser found verse before chapter")
                text, annotations = _surface_text(verse_match.group(2) or "")
                number = verse_match.group(1)
                verses.append(
                    {
                        "book": book,
                        "chapter": chapter,
                        "number": number,
                        "address": f"{book}.{chapter}.{number}",
                        "text": text,
                        "poetry": poetry,
                        "annotations": annotations,
                    }
                )
                poetry = False
                continue
            block = _BLOCK_LINE.fullmatch(line)
            if block is None:
                raise ValueError("independent parser found malformed USFM block")
            marker, value = block.group(1), (block.group(2) or "").strip()
            if marker == "c":
                chapter, poetry = int(value), False
            elif marker == "q1":
                poetry = True
            elif marker == "p":
                poetry = False
            elif marker in _HEADING_MARKERS:
                headings.append((marker, value))
            elif marker == "id":
                if value.split(maxsplit=1)[0] != book:
                    raise ValueError(
                        "independent parser found mismatched USFM identity"
                    )
            else:
                raise ValueError(
                    f"independent parser found unsupported USFM marker {marker!r}"
                )
        result.append(
            {
                "book": book,
                "source_position": ordinal,
                "headings": headings,
                "verses": verses,
            }
        )
    return result


def _parse_scrollmapper(
    content: bytes,
) -> tuple[list[dict[str, object]], list[str], str]:
    source = _strict(content, "Scrollmapper witness")
    slots = []
    order: list[str] = []
    for carrier_position, carrier in enumerate(source["books"], 1):
        book = _OSIS.get(carrier["name"])
        if book is not None and book not in order:
            order.append(book)
        for chapter in carrier["chapters"]:
            for verse in chapter["verses"]:
                slots.append(
                    {
                        "carrier_position": carrier_position,
                        "carrier_name": carrier["name"],
                        "book": book,
                        "chapter": chapter["chapter"],
                        "number": verse["verse"],
                        "text": verse["text"],
                        "address": f"{book}.{chapter['chapter']}.{verse['verse']}"
                        if book
                        else None,
                    }
                )
    return slots, order, str(source["translation"])


def _scope(page: int) -> tuple[str, str]:
    exact = {
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
    if page <= 4:
        return "outside-1899-edition", "scan-and-digitization-front"
    if page in exact:
        return exact[page]
    ranges = (
        (9, 10, "1899-preface"),
        (11, 1096, "old-testament-scripture-and-apparatus"),
        (1099, 1393, "new-testament-scripture-and-apparatus"),
        (1394, 1399, "historical-and-chronological-index"),
        (1400, 1402, "reference-and-liturgical-tables"),
        (1403, 1414, "maps-and-plates"),
    )
    return next(
        ("1899-edition", role) for start, end, role in ranges if start <= page <= end
    )


def _title(book: Mapping[str, object]) -> str:
    headings = book["headings"]
    assert isinstance(headings, list)
    for preferred in ("toc2", "h", "toc1", "mt1"):
        match = next((text for marker, text in headings if marker == preferred), None)
        if match is not None:
            return str(match)
    return str(book["book"])


def _projection(node: etree._Element) -> object:
    return (
        etree.QName(node).text,
        tuple(sorted(node.attrib.items())),
        node.text,
        node.tail,
        tuple(_projection(child) for child in node),
    )


def _expected_tree(
    books: list[dict[str, object]],
    order: list[str],
    selected: Mapping[str, str],
    structural: Mapping[str, Mapping[str, str]],
) -> etree._Element:
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
        membership, role = _scope(page)
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
    indexed = {str(item["book"]): item for item in books}
    for edition_position, osis in enumerate(order, 1):
        book = indexed[osis]
        book_node = etree.SubElement(
            body, f"{{{_TEI}}}div", type="book", n=osis, corresp=f"urn:osis:{osis}"
        )
        book_node.set("subtype", "bible")
        book_node.set("source", f"ebible-source-position:{book['source_position']}")
        book_node.set("ana", f"edition-position:{edition_position}")
        etree.SubElement(
            book_node, f"{{{_TEI}}}head", type="source-book-heading"
        ).text = _title(book)
        chapters: dict[int, list[dict[str, object]]] = defaultdict(list)
        for verse in book["verses"]:
            chapters[int(verse["chapter"])].append(verse)
        for chapter, verses in chapters.items():
            if osis == "LAM" and chapter == 5:
                disposition = structural["LAM.4.22"]
                transition = etree.SubElement(
                    book_node,
                    f"{{{_TEI}}}div",
                    type="source-structural-transition",
                    corresp="urn:osis:LAM.4.22",
                )
                etree.SubElement(
                    transition,
                    f"{{{_TEI}}}head",
                    type="source-prayer-heading",
                ).text = disposition["heading"]
            chapter_node = etree.SubElement(
                book_node, f"{{{_TEI}}}div", type="chapter", n=str(chapter)
            )
            prefix_address = f"{osis}.{chapter}.1"
            if (
                prefix_address in structural
                and structural[prefix_address]["placement"] == "before-verse"
            ):
                etree.SubElement(
                    chapter_node,
                    f"{{{_TEI}}}head",
                    type="source-verse-prefix",
                    corresp=f"urn:osis:{prefix_address}",
                ).text = structural[prefix_address]["heading"]
            for verse in verses:
                address = str(verse["address"])
                node = etree.SubElement(
                    chapter_node,
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
    return root


def _module_path(root: Path, name: str) -> Path | None:
    path = root.joinpath(*name.split("."))
    for candidate in (path.with_suffix(".py"), path / "__init__.py"):
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("Douay oracle import closure escaped repository") from exc
        if resolved.is_file():
            return resolved
    return None


def _from_imports(path: Path, root: Path, node: ast.ImportFrom) -> tuple[str, ...]:
    if node.level == 0:
        base = node.module or ""
    else:
        package = list(path.relative_to(root).parts[:-1])
        if node.level - 1 > len(package):
            raise ValueError("Douay oracle relative import escaped repository")
        base = ".".join(
            [
                *package[: len(package) - node.level + 1],
                *((node.module or "").split(".") if node.module else []),
            ]
        )
    return tuple(
        [base, *(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")]
    )


def _repository_import_closure(
    root: Path, entry: Path, forbidden: tuple[str, ...]
) -> tuple[dict[str, str], ...]:
    root = root.resolve(strict=True)
    pending, visited = [entry.resolve(strict=True)], set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        path.relative_to(root)
        visited.add(path)
        relative = path.relative_to(root)
        for depth in range(1, len(relative.parts)):
            initializer = root.joinpath(*relative.parts[:depth], "__init__.py")
            if initializer.is_file() and initializer.resolve() not in visited:
                pending.append(initializer.resolve())
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "eval", "exec"}
            ):
                raise ValueError(
                    "Douay oracle closure contains dynamic import or execution"
                )
            names = (
                tuple(alias.name for alias in node.names)
                if isinstance(node, ast.Import)
                else (
                    _from_imports(path, root, node)
                    if isinstance(node, ast.ImportFrom)
                    else ()
                )
            )
            for name in names:
                if any(
                    name == prefix or name.startswith(prefix + ".")
                    for prefix in forbidden
                ):
                    raise ValueError(
                        f"Douay oracle closure contains forbidden import {name}"
                    )
                dependency = _module_path(root, name)
                if dependency is not None and dependency not in visited:
                    pending.append(dependency)
    return tuple(
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in sorted(visited, key=lambda item: item.relative_to(root).as_posix())
    )


def _closure_digest(
    root: Path, policy: Mapping[str, object], entry: Path | None = None
) -> str:
    return _digest(
        _repository_import_closure(
            root,
            entry or Path(__file__),
            tuple(str(item) for item in policy["forbidden_import_prefixes"]),
        )
    )


def _runtime_paths(root: Path) -> None:
    for name, module_file in {
        "oracle": __file__,
        "contract": sys.modules["ocd_kernel.reconstruction.contract"].__file__,
        "tei_validate": sys.modules["ocd_kernel.tei.validate"].__file__,
    }.items():
        if not isinstance(module_file, str):
            raise ValueError(f"Douay oracle loaded {name} without a path")
        path = Path(module_file).resolve(strict=False)
        try:
            relative = path.relative_to(root.resolve(strict=True)).as_posix()
        except ValueError as exc:
            raise ValueError(f"Douay oracle loaded {name} outside repository") from exc
        if (
            "__editable__" in relative
            or "site-packages" in relative
            or not path.is_file()
        ):
            raise ValueError(f"Douay oracle loaded shadowed or missing {name}")


def _ordered_ocr_usemaps(path: Path) -> list[str]:
    values: list[str] = []
    for _, node in etree.iterparse(
        str(path), events=("end",), tag="OBJECT", load_dtd=False, no_network=True
    ):
        usemap = node.attrib.get("usemap")
        if usemap is None:
            raise ValueError("Douay OCR OBJECT lacks usemap")
        values.append(usemap)
        node.clear()
    expected = [f"holybible00balt_{number:04d}.djvu" for number in range(1, 1415)]
    if (
        values != expected
        or len(values) != len(set(values))
        or _digest(values) != _OCR_INVENTORY_SHA256
    ):
        raise ValueError("Douay ordered OCR OBJECT identity mutation")
    return values


def _readme() -> bytes:
    return (
        "# Douay-Rheims American Edition of 1899 reconstruction candidate\n\n"
        "This six-member package is a deterministic, nonaccepted candidate reconstructed from 73 individually retained eBible engDRA USFM members, a retained Scrollmapper witness, frozen print-selection and triage ledgers, and a retained 1899 facsimile carried by the 1971 TAN reproduction. The original eBible ZIP is retained only as acquisition/archive provenance.\n\n"
        "The candidate preserves 73 books, 1,334 chapters, 35,811 verses, 1,414 facsimile surfaces, 599 print-supported selections, 3,025 unresolved substantive differences, and four open structural cases. Strong annotations and poetry markers are retained source-witness facts, not claims about 1899 print content. The wider print apparatus remains incomplete. Human acceptance has not occurred, and publication is neither authorized nor ready.\n"
    ).encode("utf-8")


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    expected_source = {
        "path": source_manifest.path.relative_to(root).as_posix(),
        "sha256": source_manifest.sha256,
    }
    if (
        candidate.manifest.get("status") != "nonaccepted"
        or candidate.manifest.get("source_manifest") != expected_source
    ):
        raise ValueError("Douay candidate source/status binding mutation")
    if (
        candidate.manifest.get("converter") != source_manifest.record["converter"]
        or candidate.manifest.get("package_schema")
        != source_manifest.record["package_schema"]
    ):
        raise ValueError("Douay candidate converter/schema binding mutation")
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict(profile_bytes, "Douay profile")
    policy = _strict(policy_bytes, "Douay validation policy")
    producer_path = root / str(
        source_manifest.record["converter"]["implementation_path"]
    )
    producer_closure = _repository_import_closure(
        root,
        producer_path,
        tuple(str(item) for item in policy["producer_forbidden_import_prefixes"]),
    )
    if _digest(producer_closure) != profile.get("producer_import_closure_sha256"):
        raise ValueError("Douay producer recursive import closure mutation")
    scroll_bytes = source_manifest.authority_path("scrollmapper-json").read_bytes()
    selection_bytes = source_manifest.authority_path("print-selections").read_bytes()
    triage_bytes = source_manifest.authority_path("variant-triage").read_bytes()
    structural_bytes = source_manifest.authority_path("structural-review").read_bytes()
    frozen = profile.get("frozen_evidence")
    if (
        not isinstance(frozen, dict)
        or any(frozen.get(name) != digest for name, digest in _EVIDENCE_SHA256.items())
        or frozen.get("ordered_ocr_object_usemaps_sha256") != _OCR_INVENTORY_SHA256
    ):
        raise ValueError("Douay frozen-evidence profile pin mutation")
    if {
        "print_selections_sha256": _sha(selection_bytes),
        "variant_triage_sha256": _sha(triage_bytes),
        "structural_review_sha256": _sha(structural_bytes),
    } != _EVIDENCE_SHA256:
        raise ValueError("Douay frozen evidence byte mutation")
    books = _parse_members(source_manifest)
    ebible_members = [
        {key: item[key] for key in ("name", "path", "bytes", "sha256")}
        for item, _ in _retained_ebible_members(source_manifest)
    ]
    slots, order, translation = _parse_scrollmapper(scroll_bytes)
    selections = _records(selection_bytes, "Douay print selection")
    triage = _records(gzip.decompress(triage_bytes), "Douay variant triage")
    structural = _records(structural_bytes, "Douay structural review")
    structural_dispositions = _structural_dispositions(structural)
    verses = [verse for book in books for verse in book["verses"]]
    ebible = {str(item["address"]): str(item["text"]) for item in verses}
    scroll = {
        str(item["address"]): str(item["text"])
        for item in slots
        if item["book"] is not None
    }
    if (
        len(books) != 73
        or len(order) != 73
        or set(order) != {str(item["book"]) for item in books}
    ):
        raise ValueError("Douay independent 73-book inventory/order mutation")
    selected: dict[str, str] = {}
    for item in selections:
        address, text, choice = (
            str(item["address"]),
            str(item["selected_text"]),
            str(item["selection"]),
        )
        scroll_exact = text == scroll.get(address)
        scroll_normalized = (
            address == "GEN.5.31"
            and isinstance(scroll.get(address), str)
            and text == scroll[address].rstrip()
        )
        if (
            address not in ebible
            or (choice == "ebible" and text != ebible[address])
            or (choice == "scrollmapper" and not (scroll_exact or scroll_normalized))
        ):
            raise ValueError(f"Douay selected source reading mutation at {address}")
        selected[address] = text
    counts = Counter(str(item["selection"]) for item in selections)
    structural_by_address = {str(item["address"]): item for item in structural}
    unresolved = []
    for item in triage:
        if item.get("selection") == "unresolved":
            address = str(item["address"])
            unresolved.append(
                {
                    **item,
                    "ebible_text": ebible[address],
                    "scrollmapper_text": scroll[address],
                    **(
                        {"structural_review": structural_by_address[address]}
                        if address in structural_by_address
                        else {}
                    ),
                }
            )
    expected_counts = {
        "books": len(books),
        "chapters": len({(item["book"], item["chapter"]) for item in verses}),
        "verses": len(verses),
        "facsimile_pages": 1414,
        "ebible_annotations": sum(int(item["annotations"]) for item in verses),
        "ebible_poetry_markers": sum(bool(item["poetry"]) for item in verses),
        "scrollmapper_slots": len(slots),
        "scrollmapper_empty_slots": sum(not item["text"] for item in slots),
        "scrollmapper_empty_book_shells": len(
            {item["carrier_name"] for item in slots if item["book"] is None}
        ),
        "print_selections": len(selections),
        "ebible_selections": counts["ebible"],
        "scrollmapper_selections": counts["scrollmapper"],
        "print_derived_selections": counts["print-derived"],
        "unresolved_differences": len(unresolved),
        "structural_cases": len(structural),
    }
    if expected_counts != profile.get("required_counts"):
        raise ValueError("Douay retained-source census mutation")
    if (
        len(unresolved) != 3025
        or len(structural) != 4
        or not set(structural_by_address)
        <= {str(item["address"]) for item in unresolved}
    ):
        raise ValueError("Douay unresolved/structural inventory mutation")
    if len(selections) != 599 or counts != Counter(
        {"ebible": 307, "scrollmapper": 288, "print-derived": 4}
    ):
        raise ValueError("Douay print-selection census mutation")
    if any(
        item.get("print_evidence", {}).get("scan_path") not in (None, _SCAN)
        for item in selections
    ):
        raise ValueError("Douay print-selection scan path is not portable")
    _ordered_ocr_usemaps(source_manifest.authority_path("print-ocr-xml"))
    document = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    schema = compiled_schema()
    if not schema.validate(document):
        error = schema.error_log.last_error
        raise ValueError(
            f"Douay TEI XSD failure: {error.message if error else 'unknown'}"
        )
    if _projection(document) != _projection(
        _expected_tree(books, order, selected, structural_dispositions)
    ):
        raise ValueError("Douay full recursive TEI projection mutation")
    addresses = [
        node.get("corresp", "").removeprefix("urn:osis:")
        for node in document.xpath("//tei:ab[@type='verse']", namespaces=_NS)
    ]
    if addresses != [
        str(item["address"])
        for book in order
        for item in next(row for row in books if row["book"] == book)["verses"]
    ] or len(addresses) != len(set(addresses)):
        raise ValueError("Douay TEI address omission, duplication, or order mutation")
    accountability = _strict(
        candidate.member_bytes("source-accountability.json"), "Douay accountability"
    )
    accountability_schema = _strict(
        source_manifest.authority_path("source-accountability-schema").read_bytes(),
        "Douay accountability schema",
    )
    errors = sorted(
        Draft202012Validator(accountability_schema).iter_errors(accountability), key=str
    )
    if errors:
        raise ValueError(f"Douay accountability schema failure: {errors[0].message}")
    primary = [
        {key: item[key] for key in ("name", "path", "bytes", "sha256")}
        for item in source_manifest.record["authorities"]
        if item.get("role") == "primary-source"
    ]
    expected_accountability = {
        "contract": "ocd-douay-rheims-1899-source-accountability-v1",
        "schema": "douay-rheims-1899.source-accountability.schema.json",
        "source_members": primary,
        "counts": expected_counts,
        "digests": {
            "edition_order_sha256": _digest(order),
            "verse_address_inventory_sha256": _digest(
                [item["address"] for item in verses]
            ),
            "selected_readings_sha256": _digest(selected),
            "unresolved_address_inventory_sha256": _digest(
                [item["address"] for item in unresolved]
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
    if accountability != expected_accountability:
        raise ValueError("Douay source-accountability mutation")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(
        _canonical(item) for item in unresolved
    ):
        raise ValueError("Douay unresolved evidence mutation")
    expected_provenance = {
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
            "sha256": _sha(scroll_bytes),
            "claim": translation,
        },
        "print_control": {
            "scan_path": _SCAN,
            "scan_sha256": _authority(source_manifest, "print-pdf")["sha256"],
            "ocr_path": _OCR,
            "ocr_sha256": _authority(source_manifest, "print-ocr-xml")["sha256"],
        },
        "selection_ledger_sha256": _sha(selection_bytes),
        "triage_ledger_sha256": _sha(triage_bytes),
        "structural_review_ledger_sha256": _sha(structural_bytes),
        "page_correspondence": "each TEI surface links to the retained PDF graphic and OCR XML page by repository-relative URI",
    }
    if (
        _strict(candidate.member_bytes("provenance.json"), "Douay provenance")
        != expected_provenance
    ):
        raise ValueError("Douay provenance or publication boundary mutation")
    if candidate.member_bytes("README.source.md") != _readme():
        raise ValueError("Douay README acceptance/publication boundary mutation")
    _runtime_paths(root)
    closure = _closure_digest(root, policy)
    if (
        closure != source_manifest.record["validator"]["import_closure_sha256"]
        or _sha(Path(__file__).read_bytes())
        != source_manifest.record["validator"]["implementation_sha256"]
    ):
        raise ValueError("Douay oracle implementation or import closure drifted")
    members = sorted(
        (
            {key: item[key] for key in ("name", "path", "bytes", "sha256")}
            for item in source_manifest.record["authorities"]
            if item["role"] == "primary-source"
        ),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": closure,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": _digest(
            {"contract": "ocd-source-member-set-v1", "members": members}
        ),
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
