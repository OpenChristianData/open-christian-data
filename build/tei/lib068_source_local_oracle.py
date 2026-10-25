"""Producer-independent retained-source oracle for the four LIB-068 works."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import platform
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-lib068-source-local-independent-oracle"
ORACLE_VERSION = "2"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


@dataclass(frozen=True, slots=True)
class _Spec:
    source_id: str
    path: str
    size: int
    sha256: str
    newline: bytes
    newline_label: str
    line_count: int
    blank_count: int


_SPECS = {
    "donne-devotions-upon-emergent-occasions": _Spec("gutenberg-pg23772-retained", "raw/gutenberg/pg23772.txt", 427_543, "f1f2b08f2dcfe9f6618bb8031a5d055b5d58e30f80a399ff866d5b205b1773b7", b"\r\n", "CRLF with terminal CRLF", 7_647, 1_098),
    "newman-apologia-pro-vita-sua": _Spec("gutenberg-pg22088-retained", "raw/gutenberg/pg22088.txt", 818_680, "18e63c1d0bf11c66d6a6fdda83c19de9005c50b06831785a3507fcd1b6a49073", b"\r\n", "CRLF with terminal CRLF", 14_174, 1_553),
    "taylor-holy-dying": _Spec("ccel-taylor-holy-dying-retained", "raw/ccel/taylor-holy-dying.txt", 626_969, "a99a2da53737c99b48acd37c5506926620a0a66d5b74c1f2c0759bbe638679ad", b"\n", "LF with terminal LF", 10_057, 926),
    "taylor-holy-living": _Spec("ccel-taylor-holy-living-retained", "raw/ccel/taylor-holy-living.txt", 872_260, "e10fe562260708ce06081e39d728e738ac0fa8b8a3ee72d696bca5c44cb76856", b"\n", "LF with terminal LF", 14_613, 1_782),
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _closure(root: Path) -> str:
    paths = {
        Path(__file__).resolve(strict=True),
        Path(__file__).with_name("lib068_source_letters_oracle.py").resolve(strict=True),
        Path(__file__).with_name("lib068_literary_blocks_oracle.py").resolve(strict=True),
        (root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True),
        (root / "ocd_kernel/reconstruction/__init__.py").resolve(strict=True),
    }
    records = [
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix())
    ]
    return _sha(_canonical(records))


def _source_lines(source: bytes, spec: _Spec) -> list[str]:
    if len(source) != spec.size or _sha(source) != spec.sha256:
        raise ValueError("LIB-068 retained source bytes drifted")
    other = b"\n" if spec.newline == b"\r\n" else b"\r"
    if not source.endswith(spec.newline) or other in source.replace(spec.newline, b""):
        raise ValueError("LIB-068 retained source newline contract drifted")
    try:
        lines = source.decode("utf-8", errors="strict").split(spec.newline.decode("ascii"))
    except UnicodeDecodeError as exc:
        raise ValueError("LIB-068 retained source is not strict UTF-8") from exc
    if len(lines) != spec.line_count or sum(line == "" for line in lines) != spec.blank_count:
        raise ValueError("LIB-068 retained source line census drifted")
    return lines


def _unresolved(work_id: str) -> list[dict[str, str]]:
    kinds = (
        ("projection", "Source-located literary structures, emphasis and local notes are encoded; source-bound technical checks do not replace native visual comparison or human textual acceptance." if work_id.startswith(("newman-", "donne-")) else "The line-faithful projection is technical evidence, not an editorially accepted reading structure."),
        ("identity", "Human review must confirm the bounded work and creator identity."),
        ("edition-witness", "Human review must confirm the retained transcription's edition and witness claims."),
        ("rights", "Human rights review is required before any publication decision."),
        ("editorial", "No headings, divisions, apparatus, spelling, punctuation, or wording receive an editorial disposition here."),
        ("textual-acceptance", "Technical validation is not human textual acceptance."),
        ("publication", "This candidate is not publication-ready or publication-authorized."),
    )
    return [
        {"id": f"{work_id}-{kind}-review", "status": "unresolved", "kind": kind, "detail": detail}
        for kind, detail in kinds
    ]


def _tag(name: str) -> str:
    return f"{{{_TEI}}}{name}"


def _children(node: etree._Element, names: list[str], label: str) -> None:
    if [child.tag for child in node] != [_tag(name) for name in names]:
        raise ValueError(f"LIB-068 {label} child order drifted")


def _leaf(node: etree._Element, name: str, text: str, attributes: Mapping[str, str] | None = None) -> None:
    if (
        node.tag != _tag(name)
        or dict(node.attrib) != dict(attributes or {})
        or (node.text or "") != text
        or len(node) != 0
        or (node.tail or "") != ""
    ):
        raise ValueError(f"LIB-068 {name} element drifted")


def _verify_tei(candidate: CandidatePackage, work_id: str, spec: _Spec, identity: Mapping[str, object], lines: list[str], profile: Mapping[str, object]) -> None:
    try:
        root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    except etree.XMLSyntaxError as exc:
        raise ValueError("LIB-068 TEI is not well-formed") from exc
    if dict(root.attrib) != {_XML_ID: f"{work_id}-candidate"} or root.tag != _tag("TEI") or (root.text or "") != "" or (root.tail or "") != "":
        raise ValueError("LIB-068 TEI root drifted")
    _children(root, ["teiHeader", "text"], "TEI")
    header, text = root
    _children(header, ["fileDesc", "encodingDesc", "revisionDesc"], "header")
    file_desc, encoding, revision = header
    _children(file_desc, ["titleStmt", "publicationStmt", "sourceDesc"], "fileDesc")
    title_stmt, publication, source_desc = file_desc
    _children(title_stmt, ["title", "author"], "titleStmt")
    _leaf(title_stmt[0], "title", str(identity["work_title"]))
    _leaf(title_stmt[1], "author", str(identity["creator_statement"]))
    _children(publication, ["publisher", "availability"], "publicationStmt")
    _leaf(publication[0], "publisher", "Open Christian Data")
    availability = publication[1]
    if dict(availability.attrib) != {"status": "restricted"}:
        raise ValueError("LIB-068 availability drifted")
    _children(availability, ["p"], "availability")
    _leaf(availability[0], "p", "Nonaccepted candidate; publication is not authorized.")
    _children(source_desc, ["bibl"], "sourceDesc")
    bibl = source_desc[0]
    _children(bibl, ["title", "author", "note", "idno", "idno"], "source bibliography")
    _leaf(bibl[0], "title", str(identity["source_title"]))
    _leaf(bibl[1], "author", str(identity["creator_statement"]))
    _leaf(bibl[2], "note", str(identity["retained_edition_statement"]), {"type": "retained-edition"})
    _leaf(bibl[3], "idno", str(identity["source_url"]), {"type": "source-url"})
    _leaf(bibl[4], "idno", spec.sha256, {"type": "sha256"})
    _children(encoding, ["p"], "encodingDesc")
    encoding_statement = f"Every retained physical line is represented once, in order, without wording normalization; the source uses {spec.newline_label}."
    if work_id.startswith(("newman-", "donne-")):
        encoding_statement += " Literary v2 encodes source-located divisions, headings, paragraphs, local notes, embedded documents, verse, lists and tables. Numbered source-line segments and checked table column fragments preserve the physical witness. hi with rend source-underscore includes the literal underscore delimiters; ref text retains the literal bracketed note number. Empty and space-only lines remain exact, including blanks inside multiline headings. These encodings do not establish editorial acceptance."
    _leaf(encoding[0], "p", encoding_statement)
    if dict(revision.attrib) != {"status": "candidate"}:
        raise ValueError("LIB-068 revision description drifted")
    _children(revision, ["change"], "revisionDesc")
    _leaf(revision[0], "change", "Generated as a nonaccepted source-bound candidate.", {"when": "2026-08-31"})
    _children(text, ["body"], "text")
    body = text[0]
    _children(body, ["div"], "body")
    source_div = body[0]
    if dict(source_div.attrib) != {"type": "retained-source", _XML_ID: f"{work_id}-retained-source"}:
        raise ValueError("LIB-068 retained-source scope drifted")
    if work_id in {"newman-apologia-pro-vita-sua", "donne-devotions-upon-emergent-occasions"}:
        normalized = source_div
        for name, operation in (("lib068_source_letters_oracle", "verify_and_normalize_letters"), ("lib068_literary_blocks_oracle", "verify_and_normalize_blocks")):
            helper_path = Path(__file__).with_name(f"{name}.py")
            helper_spec = importlib.util.spec_from_file_location(name, helper_path)
            if helper_spec is None or helper_spec.loader is None:
                raise ValueError(f"LIB-068 literary oracle unavailable: {name}")
            helper = importlib.util.module_from_spec(helper_spec)
            helper_spec.loader.exec_module(helper)
            normalized = getattr(helper, operation)(normalized, work_id, lines, profile)
        _verify_literary(normalized, work_id, lines, profile)
        return
    candidate_lines = list(source_div)
    if len(candidate_lines) != len(lines):
        raise ValueError("LIB-068 source line omission, duplication, or invention")
    for number, (node, expected) in enumerate(zip(candidate_lines, lines, strict=True), 1):
        if node.tag != _tag("ab") or dict(node.attrib) != {"type": "source-line", "n": str(number)} or len(node) or (node.text or "") != expected or (node.tail or "") != "":
            raise ValueError(f"LIB-068 source line {number} order, identity, or text drifted")


def _verify_literary(scope: etree._Element, work_id: str, lines: list[str], profile: Mapping[str, object]) -> None:
    """Check the actual tree's coverage, ranges, ancestors and source paragraphs.

    The source-located inventory is shared declarative authority, not generated
    expected TEI. Chapter/devotion discovery below independently corroborates
    its critical boundaries. This oracle never imports the producer.
    """
    rows = profile.get("literary_sections")
    if not isinstance(rows, list) or not rows:
        raise ValueError("LIB-068 independent literary inventory absent")
    starts = [row["line"] for row in rows]
    if starts != sorted(set(starts)) or starts[0] != 1:
        raise ValueError("LIB-068 independent literary inventory order invalid")
    leaves = list(scope.iter(_tag("seg")))
    if len(leaves) != len(lines):
        raise ValueError("LIB-068 source line omission, duplication, or invention")
    for number, (leaf, source_line) in enumerate(zip(leaves, lines, strict=True), 1):
        if dict(leaf.attrib) != {"type": "source-line", "n": str(number)} or "".join(leaf.itertext()) != source_line:
            raise ValueError(f"LIB-068 source line {number} order, identity, or text drifted")
    if work_id.startswith("newman-"):
        discovered = _newman_section_census(lines)
        if [(row["line"], row["kind"], row["depth"]) for row in rows] != discovered:
            raise ValueError("LIB-068 source-defined Newman section census drifted")
        all_chapters = [(i, line) for i, line in enumerate(lines, 1) if re.fullmatch(r"CHAPTER [IVX]+\.", line)]
        if len(all_chapters) != 10 or [value for _, value in all_chapters[:5]] != [value for _, value in all_chapters[5:]]:
            raise ValueError("LIB-068 chapter/contents source census drifted")
        contents = next(row["line"] for row in rows if row["kind"] == "contents")
        main = next(row["line"] for row in rows if row["kind"] == "main-text")
        if not all(contents < n < main for n, _ in all_chapters[:5]):
            raise ValueError("LIB-068 contents heading classification drifted")
        source_heads = {i for i, _ in all_chapters[5:]}
        recorded_heads = {row["line"] for row in rows if row["kind"] == "chapter"}
        century_heads = {i for i, value in enumerate(lines, 1) if value.isupper() and value.endswith(("CENTURY.", "CENTURIES."))}
        if len(century_heads) != 34 or century_heads != {row["line"] for row in rows if row["kind"] == "century"}:
            raise ValueError("LIB-068 chronology heading census drifted")
    else:
        if [(row["line"], row["kind"], row["depth"]) for row in rows] != _donne_section_census(lines):
            raise ValueError("LIB-068 source-defined Donne section census drifted")
        source_heads = {i for i, line in enumerate(lines, 1) if re.fullmatch(r"[IVX]+\. (MEDITATION|EXPOSTULATION|PRAYER)\.", line)}
        recorded_heads = {row["line"] for row in rows if row["kind"] in {"meditation", "expostulation", "prayer"}}
        if len(source_heads) != 69:
            raise ValueError("LIB-068 source devotional census drifted")
        footnote_heads = {i for i, value in enumerate(lines, 1) if value == "FOOTNOTES:"}
        if len(footnote_heads) != 23 or footnote_heads != {row["line"] for row in rows if row["kind"] in {"station-footnotes", "sermon-footnotes"}}:
            raise ValueError("LIB-068 footnote heading census drifted")
        contents_start = next(row["line"] for row in rows if row["kind"] == "station-contents")
        main_start = next(row["line"] for row in rows if row["kind"] == "devotions")
        station_entries = [int(match.group(1)) for value in lines[contents_start - 1:main_start - 1] if (match := re.match(r"^(\d+)\. ", value))]
        if station_entries != list(range(1, 24)) or len([row for row in rows if row["kind"] == "station"]) != len(station_entries):
            raise ValueError("LIB-068 station contents source census drifted")
        main_stop = next(row["line"] for row in rows if row["kind"] == "deaths-duel")
        source_stations = []
        for n, value in enumerate(lines, 1):
            match = re.fullmatch(r"\s*([IVX]+)(?:\.\s*(.*))?", value)
            if main_start < n < main_stop and match and match.group(2) not in {"MEDITATION.", "EXPOSTULATION.", "PRAYER."}:
                source_stations.append(n)
        if len(source_stations) != 23 or source_stations != [row["line"] for row in rows if row["kind"] == "station"]:
            raise ValueError("LIB-068 source station position census drifted")
    if source_heads != recorded_heads:
        raise ValueError("LIB-068 inventory omits or invents source headings")
    divisions = list(scope.iter(_tag("div")))[1:]
    if len(divisions) != len(rows):
        raise ValueError("LIB-068 literary division omission or invention")
    for i, (row, node) in enumerate(zip(rows, divisions, strict=True)):
        first, depth = row["line"], row["depth"]
        end = next((later["line"] for later in rows[i + 1:] if later["depth"] <= depth), len(lines) + 1)
        if not str(row["anchor"]).strip() or lines[first - 1] != row["anchor"]:
            raise ValueError(f"LIB-068 source heading anchor drift at {first}")
        if dict(node.attrib) != {"type": row["kind"], "n": str(first), _XML_ID: f"{work_id}-section-{first}"}:
            raise ValueError(f"LIB-068 literary division identity drift at {first}")
        ancestors = [p for p in node.iterancestors(_tag("div")) if p is not scope]
        expected_parent = next((prior["line"] for prior in reversed(rows[:i]) if prior["depth"] == depth - 1), None)
        if len(ancestors) != depth - 1 or (node.getparent() is not scope and node.getparent().get("n") != str(expected_parent)):
            raise ValueError(f"LIB-068 literary attachment drift at {first}")
        actual_range = [int(p.get("n", "-1")) for p in node.iter(_tag("seg"))]
        if actual_range != list(range(first, end)):
            raise ValueError(f"LIB-068 literary boundary coverage drift at {first}")
        head_end = row.get("head_end", first - 1)
        next_start = starts[i + 1] if i + 1 < len(starts) else len(lines) + 1
        if head_end >= next_start or (head_end < first and not (first == 1 and head_end == 0 and row["kind"] == "gutenberg-header")):
            raise ValueError(f"LIB-068 literary heading overlaps next section at {first}")
        heads = node.findall(_tag("head"))
        expected_heading_lines = list(range(first, head_end + 1))
        actual_heading_lines = [int(p.get("n", "-1")) for head in heads for p in head]
        if actual_heading_lines != expected_heading_lines or len(heads) != bool(expected_heading_lines):
            raise ValueError(f"LIB-068 readable heading drift at {first}")
    _verify_inline(leaves, work_id, lines, profile)
    previous = None
    for number, (leaf, source_line) in enumerate(zip(leaves, lines, strict=True), 1):
        parent = leaf.getparent()
        expected_tail = "\n" if leaf.getnext() is not None else ""
        if (leaf.tail or "") != expected_tail:
            raise ValueError(f"LIB-068 source line {number} presentation separator drifted")
        if parent.tag != _tag("head"):
            blank = not source_line.strip()
            first_text = "".join(parent[0].itertext())
            note = re.match(r"^\s*\[(\d+)\] ", first_text)
            expected_tag = _tag("ab") if blank else _tag("note") if note else _tag("p")
            if parent.tag != expected_tag:
                raise ValueError(f"LIB-068 source block kind drift at {number}")
            attributes = {"type": "source-whitespace"} if blank else {"type": "source-footnote", "n": note.group(1), _XML_ID: f"{work_id}-footnote-{note.group(1)}"} if note else {}
            if dict(parent.attrib) != attributes:
                raise ValueError(f"LIB-068 source block attributes drift at {number}")
            if previous is not None and previous.getparent().getparent() is parent.getparent() and previous.getparent().tag != _tag("head"):
                same_run = bool(not "".join(previous.itertext()).strip()) == blank
                if (previous.getparent() is parent) != same_run:
                    raise ValueError(f"LIB-068 source paragraph boundary drift at {number}")
        previous = leaf
    allowed = {_tag(k) for k in ("div", "head", "p", "ab", "note", "seg", "hi", "ref")}
    for node in scope.iter():
        if node.tag not in allowed or (node.tag not in {_tag("seg"), _tag("hi"), _tag("ref")} and ((node.text or "") or (node.tail or ""))):
            raise ValueError("LIB-068 invented literary content")
        if node.tag == _tag("head") and node.attrib:
            raise ValueError("LIB-068 invented heading attributes")


def _newman_section_census(lines: list[str]) -> list[tuple[int, str, int]]:
    """Discover section starts from literal source labels and contents contexts.

    Repeated contents/main labels are classified before taking the main label;
    repeated century headings remain distinct occurrences. No profile rows or
    producer output supply these coordinates.
    """
    result = [(1, "gutenberg-header", 1)]

    def positions(label: str) -> list[int]:
        return [i for i, value in enumerate(lines, 1) if value == label]

    def one(label: str, kind: str, depth: int = 1) -> int:
        found = positions(label)
        if len(found) != 1:
            raise ValueError(f"LIB-068 source heading census differs for {kind}")
        result.append((found[0], kind, depth))
        return found[0]

    one("APOLOGIA PRO VITA SUA", "title-page")
    one("PREFACE.", "preface")
    contents = one("CONTENTS.", "contents")
    main = one("MY RELIGIOUS OPINIONS.", "main-text")
    one("PROTEST.", "protest", 3)
    one("CALENDAR OF ENGLISH SAINTS.", "calendar", 3)
    one("CHRONOLOGICAL ARRANGEMENT.", "chronology", 3)
    for label, kind in (("NOTES.", "notes"), ("SUPPLEMENTAL MATTER.", "supplement"), ("ADDITIONAL NOTES.", "additional-notes")):
        found = positions(label)
        if len(found) != 2 or not contents < found[0] < main < found[1]:
            raise ValueError(f"LIB-068 source contents/main classification differs for {kind}")
        result.append((found[1], kind, 1))
    supplement = positions("SUPPLEMENTAL MATTER.")[-1]
    additional = positions("ADDITIONAL NOTES.")[-1]
    roman_sections = [(i, value) for i, value in enumerate(lines, 1) if supplement < i < additional and re.fullmatch(r"[IVX]+\.", value)]
    if [value for _, value in roman_sections] != ["I.", "II.", "III.", "IV."]:
        raise ValueError("LIB-068 supplement section census drifted")
    result.extend((i, "supplement-section", 2) for i, _ in roman_sections)
    months = "JANUARY FEBRUARY MARCH APRIL MAY JUNE JULY AUGUST SEPTEMBER OCTOBER NOVEMBER DECEMBER".split()
    for month in months:
        one(month + ".", "month", 4)
    for i, value in enumerate(lines, 1):
        if re.fullmatch(r"CHAPTER [IVX]+\.", value) and i > main:
            result.append((i, "chapter", 2))
        elif re.fullmatch(r"NOTE [A-G]\. ON PAGE \d+\.", value):
            result.append((i, "endnote", 2))
        elif value.isupper() and value.endswith(("CENTURY.", "CENTURIES.")):
            result.append((i, "century", 4))
        elif roman_sections[1][0] < i < roman_sections[2][0] and re.fullmatch(r"[1-7]\. [A-Z]+\.", value):
            result.append((i, "bibliography-category", 3))
        elif roman_sections[3][0] < i < additional and value.isupper() and re.match(r"^[IVX]+\.", value):
            result.append((i, "address", 3))
        elif re.fullmatch(r"NOTE ON PAGES? \d+(?:-\d+)?\.", value):
            result.append((i, "additional-note", 2))
        elif value.startswith("*** END OF THE PROJECT GUTENBERG EBOOK "):
            result.append((i, "gutenberg-license", 1))
    if len(result) != 97 or len({i for i, _, _ in result}) != 97:
        raise ValueError("LIB-068 complete Newman section census drifted")
    return sorted(result)


def _donne_section_census(lines: list[str]) -> list[tuple[int, str, int]]:
    """Discover the retained book envelope and all station/part/note headings."""
    result = [(1, "gutenberg-header", 1)]
    found: dict[str, int] = {}
    labels = {"title-page": "JOHN DONNE", "biography": "_THE LIFE OF DR. JOHN DONNE_", "devotions-title-page": "    DEVOTIONS", "dedication": "_TO THE MOST EXCELLENT PRINCE_,", "devotions": "_DEVOTIONS_", "deaths-duel": "_DEATH'S DUEL,_", "preface": "_TO THE READER_", "sermon": "_DEATH'S DUEL_"}
    for kind, label in labels.items():
        positions = [i for i, value in enumerate(lines, 1) if value == label]
        if len(positions) != 1:
            raise ValueError(f"LIB-068 source heading census differs for {kind}")
        found[kind] = positions[0]
        result.append((positions[0], kind, 2 if kind in {"preface", "sermon"} else 1))
    contents = [i for i, value in enumerate(lines, 1) if value == "CONTENTS"]
    if len(contents) != 2 or not contents[0] < found["biography"] < contents[1] < found["devotions"]:
        raise ValueError("LIB-068 source contents classification drifted")
    result.extend(((contents[0], "contents", 1), (contents[1], "station-contents", 1)))
    for i, value in enumerate(lines, 1):
        part = re.fullmatch(r"[IVX]+\. (MEDITATION|EXPOSTULATION|PRAYER)\.", value)
        station = re.fullmatch(r"\s*[IVX]+(?:\.\s*(.*))?", value)
        if part:
            if not found["devotions"] < i < found["deaths-duel"]:
                raise ValueError("LIB-068 devotional part outside source work")
            result.append((i, part.group(1).lower(), 3))
        elif found["devotions"] < i < found["deaths-duel"] and station:
            result.append((i, "station", 2))
        elif value == "FOOTNOTES:":
            if found["devotions"] < i < found["deaths-duel"]:
                result.append((i, "station-footnotes", 3))
            elif i > found["sermon"]:
                result.append((i, "sermon-footnotes", 2))
            else:
                raise ValueError("LIB-068 unclassified source footnote heading")
        elif value.startswith("*** END OF THE PROJECT GUTENBERG EBOOK "):
            result.append((i, "gutenberg-license", 1))
    if len(result) != 127 or len({i for i, _, _ in result}) != 127:
        raise ValueError("LIB-068 complete Donne section census drifted")
    return sorted(result)


def _verify_inline(leaves: list[etree._Element], work_id: str, lines: list[str], profile: Mapping[str, object]) -> None:
    """Compare source character spans with actual nested TEI spans.

    This uses paired positions in the whole source, independently of the
    producer's streaming state machine. Delimiters themselves stay represented.
    """
    text = "\n".join(lines)
    underscores = [m.start() for m in re.finditer("_", text)]
    expected_count = {"newman-apologia-pro-vita-sua": 1310, "donne-devotions-upon-emergent-occasions": 974}[work_id]
    if len(underscores) != expected_count:
        raise ValueError("LIB-068 source emphasis census drifted")
    emphasis = list(zip(underscores[::2], [p + 1 for p in underscores[1::2]], strict=True))
    definitions: dict[str, tuple[int, int]] = {}
    for n, line in enumerate(lines, 1):
        match = re.match(r"^\s*\[(\d+)\] ", line)
        if match:
            if match.group(1) in definitions:
                raise ValueError("LIB-068 duplicate source note identity")
            definitions[match.group(1)] = (n, match.start(1) - 1)
    if len(definitions) != {"newman-apologia-pro-vita-sua": 21, "donne-devotions-upon-emergent-occasions": 386}[work_id]:
        raise ValueError("LIB-068 source note census drifted")
    discovered_literals = {(n, match.group()) for n, value in enumerate(lines, 1) for match in re.finditer(r"\[(\d+)\]", value) if match.group(1) not in definitions}
    declared_literals = profile.get("literal_numeric_markers")
    if not isinstance(declared_literals, list) or any(not row.get("reason") for row in declared_literals):
        raise ValueError("LIB-068 literal marker authority absent")
    literal_positions = {(row["line"], row["token"]) for row in declared_literals}
    if literal_positions != discovered_literals or len(declared_literals) != len(literal_positions):
        raise ValueError("LIB-068 literal marker authority differs from source census")
    scope = leaves[0].getroottree().getroot()
    note_ids = [node.get(_XML_ID) for node in scope.iter(_tag("note")) if node.get("type") == "source-footnote"]
    if len(note_ids) != len(set(note_ids)) or set(note_ids) != {f"{work_id}-footnote-{number}" for number in definitions}:
        raise ValueError("LIB-068 source note target identity set drifted")
    offset = 0
    for n, (line, node) in enumerate(zip(lines, leaves, strict=True), 1):
        expected = []
        for first, stop in emphasis:
            a, b = max(first, offset), min(stop, offset + len(line))
            if a < b:
                expected.append((a - offset, b - offset, "hi", (("rend", "source-underscore"),)))
        for match in re.finditer(r"\[(\d+)\]", line):
            number = match.group(1)
            if definitions.get(number) == (n, match.start()) or (n, match.group()) in literal_positions:
                continue
            if number not in definitions:
                raise ValueError(f"LIB-068 unattached source note at {n}")
            expected.append((match.start(), match.end(), "ref", tuple(sorted({"type": "source-note-reference", "target": f"#{work_id}-footnote-{number}"}.items()))))
        observed = []

        def visit(element: etree._Element, position: int) -> int:
            position += len(element.text or "")
            for child in element:
                start = position
                position = visit(child, position)
                observed.append((start, position, etree.QName(child).localname, tuple(sorted(child.attrib.items()))))
                position += len(child.tail or "")
            return position

        if visit(node, 0) != len(line) or sorted(observed) != sorted(expected):
            raise ValueError(f"LIB-068 inline emphasis or note attachment drift at {n}")
        offset += len(line) + 1


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    work_id = source_manifest.record.get("work_id")
    if source_manifest.record.get("ticket_id") != "LIB-068" or work_id not in _SPECS:
        raise ValueError("LIB-068 source identity drifted")
    assert isinstance(work_id, str)
    spec = _SPECS[work_id]
    if source_manifest.record.get("source_id") != spec.source_id:
        raise ValueError("LIB-068 source member identity drifted")
    converter = source_manifest.record.get("converter")
    validator = source_manifest.record.get("validator")
    if not isinstance(converter, Mapping) or not isinstance(validator, Mapping):
        raise ValueError("LIB-068 callable bindings are invalid")
    logical_manifest = source_manifest.path.relative_to(source_manifest.repository_root).as_posix()
    if (
        candidate.manifest.get("status") != "nonaccepted"
        or candidate.manifest.get("source_id") != spec.source_id
        or candidate.manifest.get("source_manifest") != {"path": logical_manifest, "sha256": source_manifest.sha256}
        or candidate.manifest.get("converter") != dict(converter)
        or candidate.manifest.get("package_schema") != dict(source_manifest.record["package_schema"])
    ):
        raise ValueError("LIB-068 candidate manifest binding drifted")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict(profile_bytes, "LIB-068 profile")
    policy = _strict(policy_bytes, "LIB-068 policy")
    version = "2" if work_id.startswith(("newman-", "donne-")) else "1"
    if profile.get("profile_id") != f"lib068-{work_id}-retained-text-v{version}" or policy.get("policy_id") != f"lib068-{work_id}-policy-v{version}" or policy.get("oracle_id") != ORACLE_ID:
        raise ValueError("LIB-068 profile or policy identity drifted")
    unresolved = _unresolved(work_id)
    if policy.get("required_unresolved_ids") != [item["id"] for item in unresolved]:
        raise ValueError("LIB-068 unresolved policy drifted")
    identity = profile.get("identity")
    rights = profile.get("rights")
    if not isinstance(identity, dict) or not isinstance(rights, dict):
        raise ValueError("LIB-068 profile metadata is invalid")
    source = source_manifest.authority_path("retained-text").read_bytes()
    lines = _source_lines(source, spec)
    _verify_tei(candidate, work_id, spec, identity, lines, profile)
    census = [{"bytes": spec.size, "decision": "include", "path": spec.path, "reason": "The sole frozen LIB-068 retained primary-source member for this work.", "sha256": spec.sha256}]
    expected_accountability = {
        "contract": f"ocd-lib068-{work_id}-source-accountability-v1",
        "profile_id": profile["profile_id"],
        "work_id": work_id,
        "source_id": spec.source_id,
        "member_census": census,
        "excluded_member_count": 0,
        "source_bytes": spec.size,
        "source_sha256": spec.sha256,
        "encoding": "strict UTF-8",
        "newline": spec.newline_label,
        "source_line_count": spec.line_count,
        "blank_line_count": spec.blank_count,
        "source_line_sequence_sha256": _sha(_canonical(lines)),
        "represented_line_count": spec.line_count,
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "invented_line_count": 0,
        "reordered_line_count": 0,
        "unresolved_count": len(unresolved),
    }
    if work_id.startswith(("newman-", "donne-")):
        actual_body = etree.fromstring(candidate.member_bytes("content.tei.xml")).find(_tag("text") + "/" + _tag("body"))
        if actual_body is None:
            raise ValueError("LIB-068 actual TEI body absent")
        counts: dict[str, int] = {}
        for element in actual_body.iterdescendants():
            kind = etree.QName(element).localname
            counts[kind] = counts.get(kind, 0) + 1
        expected_accountability["native_tei_element_counts"] = counts
    accountability_bytes = candidate.member_bytes("source-accountability.json")
    if _strict(accountability_bytes, "LIB-068 accountability") != expected_accountability or accountability_bytes != _canonical(expected_accountability):
        raise ValueError("LIB-068 source accountability drifted")
    schema = _strict(source_manifest.authority_path("source-accountability-schema").read_bytes(), "LIB-068 accountability schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(expected_accountability), key=str)
    if errors:
        raise ValueError(f"LIB-068 accountability schema failure: {errors[0].message}")
    xsd = etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd"))))
    if not xsd.validate(etree.fromstring(candidate.member_bytes("content.tei.xml"))):
        raise ValueError(f"LIB-068 TEI P5 schema failure: {xsd.error_log}")
    authorities = {
        str(item["name"]): {key: item[key] for key in ("path", "bytes", "sha256", "role")}
        for item in source_manifest.record["authorities"]
    }
    expected_provenance = {
        "contract": f"ocd-lib068-{work_id}-candidate-provenance-v1",
        "status": "nonaccepted",
        "ticket_id": "LIB-068",
        "work_id": work_id,
        "source_id": spec.source_id,
        "source_manifest_sha256": source_manifest.sha256,
        "identity": identity,
        "rights": rights,
        "source_member_census": census,
        "candidate_boundary": {"technical_validation_status": "candidate-pending-validation", "human_acceptance_status": "unresolved", "publication_status": "not-authorized", "canonical_data_or_ir_written": False},
        "authorities": authorities,
    }
    if _strict(candidate.member_bytes("provenance.json"), "LIB-068 provenance") != expected_provenance:
        raise ValueError("LIB-068 provenance or metadata drifted")
    observed_unresolved = [_strict(line, "LIB-068 unresolved record") for line in candidate.member_bytes("unresolved.jsonl").splitlines() if line.strip()]
    if observed_unresolved != unresolved:
        raise ValueError("LIB-068 unresolved scope drifted")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-attribution-readme").read_bytes():
        raise ValueError("LIB-068 source attribution drifted")
    closure = _closure(source_manifest.repository_root)
    if closure != validator.get("import_closure_sha256"):
        raise ValueError("LIB-068 oracle import closure drifted")
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
        "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": spec.sha256,
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
