"""Inventory source-native headings and parts of the retained Maclaren cohort.

This source-reading preflight writes a versioned mapping proposal. The
conversion route consumes the frozen output, while its checker independently
re-reads the retained texts and checks every mapped and unmapped title-like
line. No print-volume boundary is inferred from a Gutenberg file boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

PROFILE = Path("sources/sermons/maclaren-expositions/maclaren-expositions.reconstruction-profile.json")
PARTS = {
    "7069": [(1, 63, 174, 10428, "source-part"), (10429, 10438, 10580, None, "source-part")],
    "8068": [(1, 58, 148, 12473, "source-part"), (12474, 12484, 12538, None, "source-part")],
    "7883": [(1, 62, 329, None, "source-part")],
    "7925": [(1, 59, 142, 10987, "printed-volume-I"), (10994, 10997, 11089, 22345, "printed-volume-II")],
    "8069": [(1, 65, 185, 10502, "source-part"), (10503, 10515, 10653, None, "source-part")],
    "15836": [(1, 59, 163, 10827, "source-part"), (10828, 10840, 10904, 23200, "printed-volume-I-by-end-marker")],
    "7351": [(1, 69, 156, 11813, "source-part"), (11814, 11827, 11919, None, "source-part")],
    "8071": [(1, 55, 221, None, "source-part")],
    "8200": [(1, 62, 168, 12240, "printed-volume-I"), (12248, 12253, 12358, 24702, "printed-volume-II")],
    "8070": [(1, 46, 130, None, "printed-volumes-I-II-undivided")],
    "8381": [(1, 61, 156, 11880, "printed-volume-III-by-end-marker")],
    "8397": [(1, 65, 167, 11943, "printed-volume-I-by-end-marker"), (11948, 11958, 12068, None, "source-part")],
    "13601": [(1, 58, 166, 12229, "source-part"), (12230, 12239, 12329, None, "source-part")],
    "21190": [(1, 81, 183, 11742, "source-part"), (11743, 11754, 11860, None, "source-part")],
    "24674": [(1, 77, 176, 11607, "source-part"), (11608, 11618, 11718, None, "source-part")],
}
BOOK_HEADS = {
    "7069": {10580, 17705, 19715},
    "8068": {148, 2758, 5941, 7959, 8198, 12538, 17022},
    "7883": {329, 2641, 3840, 8731, 10271, 12467, 13343, 14639, 21416},
    "8069": {17944},
    "15836": {163, 1298, 2922, 4317, 5297, 5875, 7039, 7234, 7349, 7773, 9449},
    "13601": {12329, 20374},
    "21190": {183, 2818, 5944, 14214, 16336, 19014, 20447},
    "24674": {11718, 16589, 18783},
}
NONEXPOSITION_HEADS = {
    "8070": {10167: "internal-subsection", 10244: "internal-subsection"},
    "24674": {18866: "verse-column-label"},
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lines(root: Path, member: dict[str, object]) -> list[str]:
    data = (root / str(member["path"])).read_bytes()
    if len(data) != member["bytes"] or _sha(data) != member["sha256"]:
        raise ValueError(f"PG #{member['pg_id']} differs from its retained source profile")
    if (not data.startswith(b"\xef\xbb\xbf") or not data.endswith(b"\r\n")
            or data.count(b"\r\n") != data.count(b"\n")
            or data.count(b"\r\n") != data.count(b"\r")):
        raise ValueError(f"PG #{member['pg_id']} physical line framing changed")
    lines = data.decode("utf-8-sig").split("\r\n")[:-1]
    if len(lines) != member["physical_line_count"]:
        raise ValueError(f"PG #{member['pg_id']} physical line count changed")
    return lines


def _heading_candidates(lines: list[str], first: int, last: int) -> list[tuple[int, str]]:
    result = []
    for number in range(first, last + 1):
        value = lines[number - 1].strip()
        if not value or value != value.upper() or not any(char.isalpha() for char in value):
            continue
        before = number - 2
        after = number
        if before < 0 or after >= len(lines) or lines[before].strip() or lines[after].strip():
            continue
        if re.match(r"END O[FPR] VOL", value):
            continue
        result.append((number, value))
    return result


def _adjacent_text_span(lines: list[str], heading_line: int, body_end: int) -> list[int]:
    """Return the first nonblank source paragraph following a body heading."""
    number = heading_line + 1
    while number <= body_end and not lines[number - 1].strip():
        number += 1
    if number > body_end:
        raise ValueError(f"heading at line {heading_line} has no following source paragraph")
    start = number
    while number <= body_end and lines[number - 1].strip():
        number += 1
    return [start, number - 1]


def inventory(root: Path) -> dict[str, object]:
    profile_data = (root / PROFILE).read_bytes()
    profile = json.loads(profile_data)
    members = []
    for member in profile["members"]:
        pg = str(member["pg_id"])
        lines = _lines(root, member)
        end_marker = int(member["end_marker_lines"][0])
        parts = []
        detected_book: set[int] = set()
        detected_nonexposition: set[int] = set()
        for index, (part_start, toc_line, body_start, body_end, part_kind) in enumerate(PARTS[pg]):
            body_end = body_end or end_marker - 1
            next_start = PARTS[pg][index + 1][0] if index + 1 < len(PARTS[pg]) else end_marker
            marker = lines[toc_line - 1].strip().lower()
            if marker not in ("contents", "contents."):
                raise ValueError(f"PG #{pg} source contents anchor changed at {toc_line}")
            if not (part_start <= toc_line < body_start <= body_end < next_start):
                raise ValueError(f"PG #{pg} part {index + 1} boundaries overlap")
            toc_text = re.sub(r"[^A-Z0-9]", "", " ".join(lines[toc_line - 1:body_start - 1]).upper())
            heading_rows = []
            for number, value in _heading_candidates(lines, body_start, body_end):
                if re.fullmatch(r"[IVXLCDM]+", value):
                    role = "internal-subsection"
                elif number in BOOK_HEADS.get(pg, set()):
                    role = "book-section"
                    detected_book.add(number)
                elif number in NONEXPOSITION_HEADS.get(pg, {}):
                    role = NONEXPOSITION_HEADS[pg][number]
                    detected_nonexposition.add(number)
                else:
                    role = "exposition"
                normalized = re.sub(r"[^A-Z0-9]", "", value.upper())
                found_in_contents = normalized in toc_text
                row = {"line": number, "text": lines[number - 1],
                       "role": role, "found_in_contents_text": found_in_contents}
                if role == "exposition" and not found_in_contents:
                    row["adjacent_epigraph_lines"] = _adjacent_text_span(
                        lines, number, body_end
                    )
                heading_rows.append(row)
            if not heading_rows or heading_rows[0]["line"] != body_start:
                raise ValueError(f"PG #{pg} part {index + 1} opening body heading changed")
            parts.append({"index": index + 1, "kind": part_kind,
                          "line_start": part_start, "contents_line": toc_line,
                          "body_start": body_start, "body_end": body_end,
                          "tail_start": body_end + 1 if body_end + 1 < next_start else None,
                          "tail_end": next_start - 1 if body_end + 1 < next_start else None,
                          "headings": heading_rows})
        if detected_book != BOOK_HEADS.get(pg, set()):
            raise ValueError(f"PG #{pg} book section anchors no longer match the source")
        if detected_nonexposition != set(NONEXPOSITION_HEADS.get(pg, {})):
            raise ValueError(f"PG #{pg} exception headings no longer match the source")
        members.append({"pg_id": pg, "path": member["path"],
                        "bytes": member["bytes"], "sha256": member["sha256"],
                        "physical_line_count": len(lines), "end_marker_line": end_marker,
                        "parts": parts})
    return {"contract": "maclaren-expositions-structured-cohort-map-v3",
            "status": "nonaccepted-source-mapping-proposal", "work_id": "maclaren-expositions",
            "edition_id": "maclaren-expositions-pg-fifteen-volume-cohort",
            "profile_sha256": _sha(profile_data), "source_member_count": len(members),
            "source_line_count": sum(item["physical_line_count"] for item in members),
            "members": members}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inventory(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"members": result["source_member_count"],
                      "lines": result["source_line_count"],
                      "headings": sum(len(part["headings"]) for member in result["members"]
                                      for part in member["parts"])}))


if __name__ == "__main__":
    main()
