"""Independent retained-TXT oracle for the complete Missionary Survey edition."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re

from lxml import etree

from build.tei.missionary_survey_pg13360_native import NS, SOURCE_SHA256, source_path


CONTRACT = "ocd-missionary-survey-pg13360-independent-txt-oracle-v1"
START = "*** START OF THE PROJECT GUTENBERG EBOOK"
END = "*** END OF THE PROJECT GUTENBERG EBOOK"
TEI = "{http://www.tei-c.org/ns/1.0}"


def _digest(lines: list[str]) -> str:
    return sha256("\n".join(lines).encode("utf-8")).hexdigest()


def check(candidate: bytes, *, source: Path | None = None) -> dict:
    """Prove every selected nonblank TXT line is represented exactly once."""
    raw = (source or source_path()).read_bytes()
    if sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("retained PG13360 TXT source hash differs")
    lines = raw.decode("utf-8-sig").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(START)]
    ends = [i for i, line in enumerate(lines) if line.startswith(END)]
    if len(starts) != 1 or len(ends) != 1 or not starts[0] < ends[0]:
        raise ValueError("PG13360 Gutenberg envelope differs")
    first, last = starts[0], ends[0]
    selected = lines[first + 1:last]
    def normalize(line: str) -> str:
        return re.sub(r"_([^_\n]+)_", lambda match: match.group(1), line)
    expected = [(number, normalize(line)) for number, line in enumerate(selected, first + 2)
                if line.strip()]
    root = etree.fromstring(candidate)
    actual = [(int(seg.get("n")), "".join(seg.itertext())) for seg in root.xpath(
        "//tei:seg[@type='source-line']", namespaces=NS)]
    if actual != expected:
        for ordinal, (left, right) in enumerate(zip(expected, actual)):
            if left != right:
                raise ValueError(f"PG13360 source-line mismatch at ordinal {ordinal}: {left!r} != {right!r}")
        raise ValueError(f"PG13360 source-line count differs: {len(expected)} != {len(actual)}")
    if len(actual) != 4095 or len(selected) != 4652 or len(lines) != 5031:
        raise ValueError("PG13360 complete source envelope count differs")
    page = root.xpath("/tei:TEI/tei:text/tei:front/tei:div[@type='title-page']", namespaces=NS)
    if len(page) != 1 or [(child.tag, child.get("type"), child.get("subtype")) for child in page[0]] != [
            (TEI + "ab", "source-block", role) for role in
            ("main-title", "byline", "author", "byline", "author", "date")]:
        raise ValueError("PG13360 title-page semantic roles differ")
    heading = root.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=NS)
    if (len(heading) != 1 or " ".join("".join(heading[0].itertext()).casefold().split())
            != " ".join((lines[35] + " " + lines[36]).casefold().split())):
        raise ValueError("PG13360 electronic title differs from retained title lines")
    chapters = root.xpath("/tei:TEI/tei:text/tei:body/tei:div[@type='chapter']", namespaces=NS)
    if len(chapters) != 11 or [chapter.get("n") for chapter in chapters] != [
            "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI"]:
        raise ValueError("PG13360 complete eleven-chapter body differs")
    tables = root.xpath("//tei:ab[@rend='fixed-width project-gutenberg-orientation']", namespaces=NS)
    if len(tables) != 76 or any(table.get("type") or table.get("style") for table in tables):
        raise ValueError("PG13360 fixed-width table count/orientation differs")
    for table in tables:
        ranges = table.get("n", "").split("-")
        if len(ranges) != 2 or not all(x.isdecimal() for x in ranges):
            raise ValueError("PG13360 table source-line range differs")
        numbers = [int(seg.get("n")) for seg in table.xpath(".//tei:seg[@type='source-line']", namespaces=NS)]
        if not numbers or numbers != [number for number in range(int(ranges[0]), int(ranges[1]) + 1)
                                     if lines[number - 1].strip()]:
            raise ValueError("PG13360 table source-line ownership differs")
    end_wrapper = root.xpath("/tei:TEI/tei:text/tei:back/tei:div[@type='source-wrapper']", namespaces=NS)
    if len(end_wrapper) != 1 or lines[last] not in "".join(end_wrapper[0].itertext()):
        raise ValueError("PG13360 ending Gutenberg marker not accounted")
    refs = root.xpath("//tei:ref[@type='note']", namespaces=NS)
    notes = root.xpath("//tei:note[@place='end']", namespaces=NS)
    ids = {note.get("{http://www.w3.org/XML/1998/namespace}id") for note in notes}
    if len(refs) != 11 or len(notes) != 10 or {ref.get("target", "").removeprefix("#") for ref in refs} != ids:
        raise ValueError("PG13360 footnote ownership differs")
    return {
        "contract": CONTRACT,
        "source_sha256": SOURCE_SHA256,
        "candidate_sha256": sha256(candidate).hexdigest(),
        "raw_lines": len(lines), "before_start_lines": first,
        "after_end_lines": len(lines) - last - 1,
        "selected_lines": len(selected), "selected_blank_lines": len(selected) - len(expected),
        "source_line_carriers": len(actual),
        "normalized_selected_stream_sha256": _digest([line for _, line in expected]),
        "chapter_count": len(chapters), "fixed_width_table_blocks": len(tables),
        "footnote_bodies": len(notes), "footnote_references": len(refs),
        "gutenberg_end_marker_in_back": True,
    }
