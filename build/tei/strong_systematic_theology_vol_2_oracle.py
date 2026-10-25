"""Producer-independent oracle for the retained Project Gutenberg volume 2 witness."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-strong-pg44555-independent-volume-oracle"
ORACLE_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"
XML_SPACE = f"{{{XML}}}space"
WORK_ID = "strong-systematic-theology-vol-2"
SOURCE_ID = "strong-systematic-theology-vol-2-pg44555-retained"
EDITION = "Revised and enlarged edition (Judson Press, 1907), PG#44555 (Vol. 2 of 3 files)"
SOURCE_PATH = "raw/gutenberg/pg44555.txt"
VOLUME_RANGE = (26, 34172)
TITLE_PAGE_RANGE = (26, 61)
CONTENTS_RANGE = (62, 260)
FRONT_MATTER_RANGE = (261, 294)
PARTS = (
    ("IV", 295, 8225),
    ("V", 8225, 24652),
    ("VI", 24652, 34173),
)
PART_HEADING_LINE_RANGES = (
    (295, 295),
    (8225, 8225),
    (24652, 24653),
)
CHAPTERS = (
    ("IV", 300, 8225),
    ("I", 8230, 12213),
    ("II", 12213, 13773),
    ("III", 13773, 24652),
    ("I", 24658, 34173),
)
HEADING_KINDS = {
    6: "section",
    9: "subsection",
    12: "subsubsection",
    15: "subsubsubsection",
    18: "subsubsubsubsection",
}
HEADING_LEVELS = {kind: index for index, kind in enumerate(HEADING_KINDS.values(), 1)}
PARENT_TYPES = {
    "section": "chapter",
    "subsection": "section",
    "subsubsection": "subsection",
    "subsubsubsection": "subsubsection",
    "subsubsubsubsection": "subsubsubsection",
}
CANDIDATE_KEYS = {
    "contract",
    "status",
    "source_id",
    "source_manifest",
    "converter",
    "package_schema",
    "members",
}
CANDIDATE_MEMBER_NAMES = [
    "README.source.md",
    "content.tei.xml",
    "provenance.json",
    "source-accountability.json",
    "unresolved.jsonl",
]
ACCOUNTABILITY_KEYS = {
    "contract",
    "work_id",
    "source_classification",
    "source_member",
    "work_binding",
    "volume_line_range",
    "physical_line_count",
    "represented_line_count",
    "evidence_only_line_count",
    "omitted_line_count",
    "duplicate_line_count",
    "source_inventory_sha256",
    "required_counts",
    "lines",
}
ACCOUNTABILITY_LINE_KEYS = {
    "line",
    "byte_start",
    "byte_end",
    "terminator",
    "text",
    "record_sha256",
    "disposition",
    "reason",
    "tei_selector",
}
PROVENANCE_KEYS = {
    "contract",
    "status",
    "publication",
    "work_id",
    "source_sha256",
    "source_manifest_sha256",
    "producer_import_closure",
    "producer_import_closure_sha256",
    "runtime",
    "source_scope",
    "hierarchy",
}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _load_canonical(data: bytes, label: str) -> dict[str, object]:
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict) or _stable_json(value) != data:
        raise ValueError(f"{label} is not canonical JSON")
    return value


def _load_object(data: bytes, label: str) -> dict[str, object]:
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value


def _authority(manifest: SourceManifest, name: str) -> Mapping[str, object]:
    authorities = manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("Strong Vol. 2 oracle authorities are invalid")
    matches = [item for item in authorities if item.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Strong Vol. 2 oracle authority {name} cardinality mismatch")
    return matches[0]


def _scan_source(data: bytes) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    cursor = 0
    for number, raw in enumerate(data.splitlines(keepends=True), 1):
        if raw[-2:] == b"\r\n":
            payload, terminator = raw[:-2], "CRLF"
        elif raw[-1:] == b"\n":
            payload, terminator = raw[:-1], "LF"
        else:
            payload, terminator = raw, "none"
        text = payload.decode("utf-8-sig" if number == 1 else "utf-8")
        records.append(
            {
                "number": number,
                "start": cursor,
                "end": cursor + len(raw),
                "terminator": terminator,
                "text": text,
                "record_sha256": _digest(raw),
            }
        )
        cursor += len(raw)
    if cursor != len(data):
        raise ValueError("Strong Vol. 2 source scan is not contiguous")
    return records


def _inventory_digest(records: list[dict[str, object]]) -> str:
    return _digest(
        _stable_json(
            [
                {
                    "line": item["number"],
                    "byte_start": item["start"],
                    "byte_end": item["end"],
                    "terminator": item["terminator"],
                    "record_sha256": item["record_sha256"],
                }
                for item in records
            ]
        )
    )


def _line_id(number: int) -> str:
    return f"strong-systematic-theology-vol-2-line-{number:05d}"


def _is_contents_start(text: str) -> bool:
    value = text.strip()
    if value.startswith(("Part ", "Chapter ", "Section ")):
        return True
    patterns = (
        r"^[IVXLCDM]+\.(?:\s+|—)",
        r"^\d+(?:st|nd|rd|th|d)?\.(?:\s+|—)",
        r"^[A-Z]\.(?:\s+|—)",
    )
    return any(re.match(pattern, value) for pattern in patterns)


def _contents(records: list[dict[str, object]]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for number in range(CONTENTS_RANGE[0], CONTENTS_RANGE[1] + 1):
        text = str(records[number - 1]["text"])
        if not text.strip():
            continue
        if _is_contents_start(text):
            current = {
                "toc_line": number,
                "indent": len(text) - len(text.lstrip(" ")),
                "text": text.strip(),
            }
            entries.append(current)
        elif current is not None:
            current["text"] = f"{current['text']} {text.strip()}"
    return entries


def _body_runs(records: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    runs: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    for number in range(PARTS[0][1], VOLUME_RANGE[1] + 1):
        record = records[number - 1]
        if str(record["text"]).strip():
            current.append(record)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def _heading_inventory(records: list[dict[str, object]]) -> tuple[dict[str, object], ...]:
    by_text: dict[str, list[list[dict[str, object]]]] = {}
    for run in _body_runs(records):
        text = " ".join(str(record["text"]).strip() for record in run)
        by_text.setdefault(" ".join(text.split()).casefold(), []).append(run)

    result: list[dict[str, object]] = []
    entries = _contents(records)
    for entry in entries:
        indent = int(entry["indent"])
        if indent not in HEADING_KINDS:
            continue
        candidates = by_text.get(" ".join(str(entry["text"]).split()).casefold(), [])
        if len(candidates) != 1:
            raise ValueError(
                f"Strong Vol. 2 heading is not uniquely source-correlated at contents line {entry['toc_line']}"
            )
        run = candidates[0]
        result.append(
            {
                "start_line": int(run[0]["number"]),
                "end_line": int(run[-1]["number"]),
                "kind": HEADING_KINDS[indent],
                "toc_line": int(entry["toc_line"]),
                "toc_indent": indent,
                "line_numbers": [int(record["number"]) for record in run],
            }
        )
    result.sort(key=lambda item: int(item["start_line"]))
    if len(entries) != 175 or len(result) != 167:
        raise ValueError("Strong Vol. 2 independent heading census drifted")
    return tuple(result)


def _prose_groups(
    records: list[dict[str, object]], headings: tuple[dict[str, object], ...]
) -> list[list[int]]:
    excluded = {
        number
        for heading in headings
        for number in heading["line_numbers"]
    } | {
        number
        for part_start, part_end in PART_HEADING_LINE_RANGES
        for number in range(part_start, part_end + 1)
    } | {start for _, start, _ in CHAPTERS}
    groups: list[list[int]] = []
    current: list[int] = []
    for number in range(PARTS[0][1], VOLUME_RANGE[1] + 1):
        text = str(records[number - 1]["text"])
        if number in excluded:
            if current:
                groups.append(current)
                current = []
        elif text:
            current.append(number)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _required_counts(
    records: list[dict[str, object]], headings: tuple[dict[str, object], ...]
) -> dict[str, object]:
    selected = records[VOLUME_RANGE[0] - 1 : VOLUME_RANGE[1]]
    contents = _contents(records)
    return {
        "part_count": len(PARTS),
        "chapter_count": len(CHAPTERS),
        "part_line_numbers": [start for _, start, _ in PARTS],
        "chapter_line_numbers": [start for _, start, _ in CHAPTERS],
        "title_page_line_range": list(TITLE_PAGE_RANGE),
        "contents_line_range": list(CONTENTS_RANGE),
        "front_matter_line_range": list(FRONT_MATTER_RANGE),
        "volume_line_range": list(VOLUME_RANGE),
        "volume_nonblank_lines": sum(bool(str(item["text"])) for item in selected),
        "volume_blank_lines": sum(not str(item["text"]) for item in selected),
        "contents_entry_count": len(contents),
        "contents_body_match_count": 175,
        "mapped_heading_count": len(headings),
        "mapped_heading_line_count": sum(len(item["line_numbers"]) for item in headings),
        "mapped_heading_line_ranges": [
            [int(item["start_line"]), int(item["end_line"])] for item in headings
        ],
        "mapped_heading_kind_counts": {
            kind: sum(item["kind"] == kind for item in headings)
            for kind in HEADING_KINDS.values()
        },
        "body_prose_group_count": len(_prose_groups(records, headings)),
        "front_nonblank_lines": sum(bool(str(item["text"])) for item in records[25:294]),
        "body_nonblank_lines": sum(bool(str(item["text"])) for item in records[294:34172]),
    }


def _module_file(root: Path, dotted: str) -> Path | None:
    base = root.joinpath(*dotted.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate.resolve(strict=True)
    return None


def _import_targets(path: Path, root: Path, node: ast.ImportFrom) -> tuple[str, ...]:
    if node.level == 0:
        prefix = node.module or ""
    else:
        package = list(path.relative_to(root).parts[:-1])
        prefix = ".".join(
            [
                *package[: len(package) - node.level + 1],
                *((node.module or "").split(".") if node.module else []),
            ]
        )
    return tuple([prefix, *(f"{prefix}.{alias.name}" for alias in node.names if alias.name != "*")])


def _import_closure(
    root: Path, entry: Path, forbidden: tuple[str, ...]
) -> tuple[dict[str, str], ...]:
    root = root.resolve(strict=True)
    pending = [entry.resolve(strict=True)]
    seen: set[Path] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        current.relative_to(root)
        seen.add(current)
        tree = ast.parse(current.read_text(encoding="utf-8"), filename=str(current))
        targets: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                targets.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                targets.extend(_import_targets(current, root, node))
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "eval", "exec"}
            ):
                raise ValueError("Strong Vol. 2 oracle contains dynamic execution")
        for target in targets:
            if any(target == prefix or target.startswith(prefix + ".") for prefix in forbidden):
                raise ValueError(f"Strong Vol. 2 oracle contains forbidden import {target}")
            dependency = _module_file(root, target)
            if dependency is not None and dependency not in seen:
                pending.append(dependency)
    return tuple(
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _digest(path.read_bytes()),
        }
        for path in sorted(seen, key=lambda item: item.relative_to(root).as_posix())
    )


def _runtime_paths(root: Path) -> None:
    for name in ("ocd_kernel.reconstruction.contract", "ocd_kernel.tei.validate"):
        module_file = getattr(sys.modules.get(name), "__file__", None)
        if not isinstance(module_file, str):
            raise ValueError(f"Strong Vol. 2 runtime dependency {name} has no path")
        resolved = Path(module_file).resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Strong Vol. 2 runtime dependency {name} is outside root") from exc


def _expected_unresolved() -> list[dict[str, str]]:
    details = (
        (
            "edition-identity",
            "The retained witness identifies the revised and enlarged 1907 Judson Press edition through Project Gutenberg #44555; no claim is made that the electronic transcription is a complete diplomatic facsimile of every paper-edition feature.",
        ),
        (
            "textual-form",
            "The retained file is an English Project Gutenberg plain-text witness of Augustus H. Strong's volume; no separate translator or editorial contributor is asserted from the current source envelope.",
        ),
        (
            "rights",
            "The Project Gutenberg wrapper states a United States basis and directs users to check local law; this candidate does not establish worldwide rights clearance or publication authorization.",
        ),
        (
            "source-envelope",
            "The retained member is volume 2 of a three-file Project Gutenberg set. Only pg44555.txt is in this ticket's declared member scope; volumes 1 and 3 are not silently inferred or included.",
        ),
        (
            "human-acceptance",
            "This candidate is nonaccepted and has no human textual, identity, editorial, or rights acceptance.",
        ),
    )
    return [
        {"id": f"{WORK_ID}-{suffix}", "status": "unresolved", "detail": detail}
        for suffix, detail in details
    ]


def _candidate_manifest(
    candidate: CandidatePackage, source_manifest: SourceManifest
) -> dict[str, object]:
    record = _load_canonical(candidate.member_bytes("manifest.json"), "Strong Vol. 2 candidate manifest")
    members = record.get("members")
    expected_path = source_manifest.path.relative_to(source_manifest.repository_root).as_posix()
    if (
        set(record) != CANDIDATE_KEYS
        or record.get("contract") != "ocd-candidate-package-v1"
        or record.get("status") != "nonaccepted"
        or record.get("source_id") != SOURCE_ID
        or record.get("source_manifest") != {"path": expected_path, "sha256": source_manifest.sha256}
        or record.get("converter") != dict(source_manifest.record["converter"])
        or record.get("package_schema") != dict(source_manifest.record["package_schema"])
        or not isinstance(members, list)
        or [item.get("name") for item in members if isinstance(item, dict)] != CANDIDATE_MEMBER_NAMES
        or any(
            not isinstance(item, dict) or set(item) != {"name", "bytes", "sha256"}
            for item in members
        )
    ):
        raise ValueError("Strong Vol. 2 candidate authority binding mutated")
    return record


def _check_accountability(
    candidate: CandidatePackage,
    records: list[dict[str, object]],
    source_authority: Mapping[str, object],
    counts: dict[str, object],
) -> None:
    accountability = _load_canonical(
        candidate.member_bytes("source-accountability.json"),
        "Strong Vol. 2 source accountability",
    )
    if set(accountability) != ACCOUNTABILITY_KEYS:
        raise ValueError("Strong Vol. 2 accountability keys drifted")
    if (
        accountability["contract"] != "ocd-strong-pg44555-source-accountability-v1"
        or accountability["work_id"] != WORK_ID
        or accountability["source_classification"]
        != {
            "source_type": "gutenberg_txt",
            "source_format": "plain text (UTF-8)",
            "ocr_classification": "non-ocr-retained-gutenberg-witness",
        }
        or accountability["source_member"]
        != {key: source_authority[key] for key in ("path", "bytes", "sha256")}
        or accountability["work_binding"]
        != {
            "work_id": WORK_ID,
            "title": "Systematic Theology, Vol. 2",
            "source_member": SOURCE_PATH,
            "source_selector": "retained volume lines 26-34172; PG #44555",
        }
        or accountability["volume_line_range"] != list(VOLUME_RANGE)
        or accountability["physical_line_count"] != len(records)
        or accountability["represented_line_count"] != counts["volume_nonblank_lines"]
        or accountability["evidence_only_line_count"]
        != len(records) - int(counts["volume_nonblank_lines"])
        or accountability["omitted_line_count"] != 0
        or accountability["duplicate_line_count"] != 0
        or accountability["source_inventory_sha256"] != _inventory_digest(records)
        or accountability["required_counts"] != counts
    ):
        raise ValueError("Strong Vol. 2 accountability summary drifted")

    lines = accountability.get("lines")
    if not isinstance(lines, list) or len(lines) != len(records):
        raise ValueError("Strong Vol. 2 accountability line inventory drifted")
    selected = set(range(VOLUME_RANGE[0], VOLUME_RANGE[1] + 1))
    for record, observed in zip(records, lines, strict=True):
        if not isinstance(observed, dict) or set(observed) != ACCOUNTABILITY_LINE_KEYS:
            raise ValueError("Strong Vol. 2 accountability line record drifted")
        number = int(record["number"])
        in_volume = number in selected
        represented = in_volume and bool(str(record["text"]))
        expected = {
            "line": number,
            "byte_start": record["start"],
            "byte_end": record["end"],
            "terminator": record["terminator"],
            "text": record["text"],
            "record_sha256": record["record_sha256"],
            "disposition": "represented" if represented else "evidence-only",
            "reason": (
                "retained volume line represented in the TEI hierarchy"
                if represented
                else (
                    "source paragraph separator represented by TEI block structure"
                    if in_volume
                    else "Project Gutenberg wrapper or license envelope retained as evidence-only"
                )
            ),
            "tei_selector": f"#{_line_id(number)}" if represented else None,
        }
        if observed != expected:
            raise ValueError(f"Strong Vol. 2 accountability drifted at line {number}")


def _node_text(node: etree._Element) -> str:
    if node.tag == f"{{{TEI}}}head":
        return node.text or ""
    return node.text or ""


def _check_heading(
    node: etree._Element,
    rows: list[dict[str, object]],
    line_numbers: list[int],
    kind: str,
) -> None:
    if node.tag != f"{{{TEI}}}head" or node.get("type") != kind:
        raise ValueError("Strong Vol. 2 heading carrier type drifted")
    children = list(node)
    expected_ids = [_line_id(number) for number in line_numbers]
    actual_ids = [node.get(XML_ID)] + [
        child.get(XML_ID)
        for child in children
        if child.tag == f"{{{TEI}}}seg"
    ]
    if actual_ids != expected_ids:
        raise ValueError("Strong Vol. 2 heading line order drifted")
    if node.get("n") != str(line_numbers[0]) or node.get(XML_SPACE) != "preserve":
        raise ValueError("Strong Vol. 2 heading anchor drifted")
    if _node_text(node) != str(rows[line_numbers[0] - 1]["text"]):
        raise ValueError(f"Strong Vol. 2 heading wording drifted at line {line_numbers[0]}")
    if len(children) != 2 * (len(line_numbers) - 1):
        raise ValueError("Strong Vol. 2 heading separator structure drifted")
    for number, lb, child in zip(
        line_numbers[1:], children[0::2], children[1::2], strict=True
    ):
        if (
            lb.tag != f"{{{TEI}}}lb"
            or lb.text is not None
            or lb.tail is not None
            or child.tag != f"{{{TEI}}}seg"
            or child.get("type") != "source-line"
            or child.get("n") != str(number)
            or child.get(XML_SPACE) != "preserve"
            or child.text != str(rows[number - 1]["text"])
            or child.tail is not None
        ):
            raise ValueError(f"Strong Vol. 2 wrapped heading drifted at line {number}")


def _actual_body_path(node: etree._Element, body: etree._Element) -> tuple[tuple[str, str], ...]:
    path: list[tuple[str, str]] = []
    current = node
    allowed = {"part", "chapter", *HEADING_KINDS.values()}
    while current is not None and current is not body:
        if current.tag == f"{{{TEI}}}div" and current.get("type") in allowed:
            path.append((str(current.get("type")), str(current.get("n"))))
        current = current.getparent()
    if current is not body:
        raise ValueError("Strong Vol. 2 source carrier escaped the body")
    return tuple(reversed(path))


def _expected_body_paths(
    records: list[dict[str, object]], headings: tuple[dict[str, object], ...]
) -> dict[int, tuple[tuple[str, str], ...]]:
    by_start = {int(item["start_line"]): item for item in headings}
    active: list[dict[str, object]] = []
    result: dict[int, tuple[tuple[str, str], ...]] = {}
    part_starts = {start for _, start, _ in PARTS}
    chapter_starts = {start for _, start, _ in CHAPTERS}
    for number in range(PARTS[0][1], VOLUME_RANGE[1] + 1):
        if number in part_starts or number in chapter_starts:
            active.clear()
        heading = by_start.get(number)
        if heading is not None:
            level = HEADING_LEVELS[str(heading["kind"])]
            while active and int(active[-1]["level"]) >= level:
                active.pop()
            active.append({"level": level, **heading})
        part = next(
            (name for name, start, end in PARTS if start <= number < end),
            None,
        )
        if part is None:
            raise ValueError(f"Strong Vol. 2 body line {number} is outside parts")
        chapter = next(
            (name for name, start, end in CHAPTERS if start <= number < end),
            None,
        )
        path: list[tuple[str, str]] = [("part", part)]
        if chapter is not None:
            path.append(("chapter", chapter))
        path.extend(
            (str(item["kind"]), str(item["start_line"])) for item in active
        )
        result[number] = tuple(path)
    return result


def _check_text_and_structure(
    document: etree._Element,
    records: list[dict[str, object]],
    headings: tuple[dict[str, object], ...],
) -> dict[str, object]:
    text = document.find(f"{{{TEI}}}text")
    if text is None:
        raise ValueError("Strong Vol. 2 TEI text element is absent")
    front = text.find(f"{{{TEI}}}front")
    body = text.find(f"{{{TEI}}}body")
    if front is None or body is None:
        raise ValueError("Strong Vol. 2 TEI front/body boundary is absent")
    front_divs = list(front)
    if [item.tag for item in front_divs] != [f"{{{TEI}}}div"] * 3:
        raise ValueError("Strong Vol. 2 front division shell drifted")
    if [item.get("type") for item in front_divs] != ["title-page", "contents", "front-matter"]:
        raise ValueError("Strong Vol. 2 front division order drifted")
    for division in front_divs:
        if any(child.tag != f"{{{TEI}}}ab" for child in division):
            raise ValueError("Strong Vol. 2 front line shell drifted")

    expected_numbers = [
        number
        for number in range(VOLUME_RANGE[0], VOLUME_RANGE[1] + 1)
        if str(records[number - 1]["text"])
    ]
    expected_ids = [_line_id(number) for number in expected_numbers]
    carriers = document.xpath("//*[@xml:id]", namespaces={"xml": XML})
    if [node.get(XML_ID) for node in carriers] != expected_ids:
        raise ValueError("Strong Vol. 2 source-line carrier order or cardinality drifted")
    by_id = {node.get(XML_ID): node for node in carriers}
    for number in expected_numbers:
        node = by_id[_line_id(number)]
        if (
            node.get("n") != str(number)
            or node.get(XML_SPACE) != "preserve"
            or node.tail is not None
            or _node_text(node) != str(records[number - 1]["text"])
        ):
            raise ValueError(f"Strong Vol. 2 source wording or anchor drifted at line {number}")
        for child in node:
            if child.tail is not None:
                raise ValueError("Strong Vol. 2 carrier has unexpected tail text")

    for node in list(front) + [body]:
        for descendant in node.iter():
            local = etree.QName(descendant).localname
            if local not in {"body", "div", "head", "p", "seg", "ab", "lb"}:
                raise ValueError(f"Strong Vol. 2 readable TEI contains {local}")
            if local in {"div", "p", "lb"} and descendant.text:
                raise ValueError("Strong Vol. 2 readable TEI has unbound text")
            if descendant.tail is not None:
                raise ValueError("Strong Vol. 2 readable TEI has unbound tail text")
            if local in {"head", "seg", "ab"} and descendant.get(XML_ID) not in expected_ids:
                raise ValueError("Strong Vol. 2 readable TEI carrier is unbound")

    for division, interval, kind in zip(
        front_divs,
        (TITLE_PAGE_RANGE, CONTENTS_RANGE, FRONT_MATTER_RANGE),
        ("title-page-line", "contents-line", "front-matter-line"),
        strict=True,
    ):
        expected = [
            _line_id(number)
            for number in range(interval[0], interval[1] + 1)
            if str(records[number - 1]["text"])
        ]
        if [node.get(XML_ID) for node in division] != expected:
            raise ValueError(f"Strong Vol. 2 {kind} inventory drifted")
        if any(node.get("type") != kind for node in division):
            raise ValueError(f"Strong Vol. 2 {kind} carrier type drifted")

    part_nodes = body.xpath("./tei:div[@type='part']", namespaces={"tei": TEI})
    if len(part_nodes) != len(PARTS):
        raise ValueError("Strong Vol. 2 part count drifted")
    chapter_nodes = body.xpath(
        "./tei:div[@type='part']/tei:div[@type='chapter']",
        namespaces={"tei": TEI},
    )
    if len(chapter_nodes) != len(CHAPTERS):
        raise ValueError("Strong Vol. 2 chapter count drifted")
    for node, (name, start, _end) in zip(part_nodes, PARTS, strict=True):
        children = list(node)
        if (
            node.get("n") != name
            or not children
            or children[0].tag != f"{{{TEI}}}head"
            or any(child.tag != f"{{{TEI}}}div" or child.get("type") != "chapter" for child in children[1:])
        ):
            raise ValueError(f"Strong Vol. 2 part shell drifted at line {start}")
        part_index = next(index for index, item in enumerate(PARTS) if item[1] == start)
        part_start, part_end = PART_HEADING_LINE_RANGES[part_index]
        _check_heading(
            children[0],
            records,
            list(range(part_start, part_end + 1)),
            "part",
        )
    for node, (name, start, _end) in zip(chapter_nodes, CHAPTERS, strict=True):
        children = list(node)
        if (
            node.get("n") != name
            or not children
            or children[0].tag != f"{{{TEI}}}head"
            or any(
                child.tag != f"{{{TEI}}}p"
                and (child.tag != f"{{{TEI}}}div" or child.get("type") not in HEADING_KINDS.values())
                for child in children[1:]
            )
        ):
            raise ValueError(f"Strong Vol. 2 chapter shell drifted at line {start}")
        _check_heading(children[0], records, [start], "chapter")

    expected_heading_pairs = [
        (int(item["start_line"]), str(item["kind"])) for item in headings
    ]
    actual_heading_divs = document.xpath(
        ".//tei:div[@type='section' or @type='subsection' or @type='subsubsection' or @type='subsubsubsection' or @type='subsubsubsubsection']",
        namespaces={"tei": TEI},
    )
    actual_pairs = [(int(node.get("n", "0")), str(node.get("type"))) for node in actual_heading_divs]
    if actual_pairs != expected_heading_pairs:
        raise ValueError("Strong Vol. 2 heading division inventory drifted")
    for node, heading in zip(actual_heading_divs, headings, strict=True):
        kind = str(heading["kind"])
        children = list(node)
        if (
            not children
            or children[0].tag != f"{{{TEI}}}head"
            or any(
                child.tag == f"{{{TEI}}}div"
                and child.get("type") != next(
                    (value for value, level in HEADING_LEVELS.items() if level == HEADING_LEVELS[kind] + 1),
                    "",
                )
                for child in children[1:]
                if child.tag == f"{{{TEI}}}div"
            )
        ):
            raise ValueError(f"Strong Vol. 2 {kind} child shell drifted")
        parent = node.getparent()
        if parent is None or parent.tag != f"{{{TEI}}}div" or parent.get("type") != PARENT_TYPES[kind]:
            raise ValueError(f"Strong Vol. 2 {kind} parent drifted")
        _check_heading(node[0], records, [int(number) for number in heading["line_numbers"]], kind)

    for node in document.xpath(".//tei:div[@type='subsubsubsubsection']", namespaces={"tei": TEI}):
        if any(child.tag != f"{{{TEI}}}p" for child in list(node)[1:]):
            raise ValueError("Strong Vol. 2 deepest heading shell drifted")
    for node in body.xpath(".//tei:p", namespaces={"tei": TEI}):
        children = list(node)
        if not children or children[-1].tag != f"{{{TEI}}}seg":
            raise ValueError("Strong Vol. 2 paragraph carrier shell drifted")
        if any(
            child.tag != (f"{{{TEI}}}seg" if index % 2 == 0 else f"{{{TEI}}}lb")
            for index, child in enumerate(children)
        ):
            raise ValueError("Strong Vol. 2 paragraph line order drifted")

    expected_paths = _expected_body_paths(records, headings)
    heading_lines = {
        number for item in headings for number in item["line_numbers"]
    }
    part_lines = {
        number
        for part_start, part_end in PART_HEADING_LINE_RANGES
        for number in range(part_start, part_end + 1)
    }
    chapter_lines = {start for _, start, _ in CHAPTERS}
    body_groups: list[list[int]] = []
    for paragraph in body.xpath(".//tei:p", namespaces={"tei": TEI}):
        body_groups.append(
            [int(child.get("n", "0")) for child in paragraph if child.tag == f"{{{TEI}}}seg"]
        )
    if body_groups != _prose_groups(records, headings):
        raise ValueError("Strong Vol. 2 paragraph grouping drifted")
    for number in range(PARTS[0][1], VOLUME_RANGE[1] + 1):
        if not str(records[number - 1]["text"]):
            continue
        node = by_id[_line_id(number)]
        if number in part_lines:
            if number in {start for _, start, _ in PARTS}:
                expected_parent = "part"
                expected_tag = "head"
            else:
                expected_parent = "head"
                expected_tag = "seg"
        elif number in chapter_lines:
            expected_parent = "chapter"
            expected_tag = "head"
        elif number in heading_lines:
            expected_parent = None
            expected_tag = None
        else:
            expected_parent = "p"
            expected_tag = "seg"
        parent = node.getparent()
        if expected_parent is not None:
            if expected_tag is None or etree.QName(node).localname != expected_tag:
                raise ValueError(f"Strong Vol. 2 carrier tag drifted at line {number}")
            if parent is None or (
                (
                    etree.QName(parent).localname != "div"
                    or parent.get("type") != expected_parent
                )
                if expected_parent in {"part", "chapter"}
                else etree.QName(parent).localname != expected_parent
            ):
                raise ValueError(f"Strong Vol. 2 carrier parent drifted at line {number}")
        elif etree.QName(node).localname not in {"head", "seg"}:
            raise ValueError(f"Strong Vol. 2 heading carrier drifted at line {number}")
        if _actual_body_path(node, body) != expected_paths[number]:
            raise ValueError(f"Strong Vol. 2 source ancestry drifted at line {number}")
    return {
        "source_line_carrier_count": len(expected_numbers),
        "part_count": len(part_nodes),
        "chapter_count": len(chapter_nodes),
        "head_count": len(part_nodes) + len(chapter_nodes) + len(actual_heading_divs),
        "mapped_heading_counts": {
            kind: sum(item["kind"] == kind for item in headings)
            for kind in HEADING_KINDS.values()
        },
        "body_paragraph_count": len(body_groups),
    }


def _check_tei(
    candidate: CandidatePackage,
    source: bytes,
    records: list[dict[str, object]],
    headings: tuple[dict[str, object], ...],
) -> dict[str, object]:
    content = candidate.member_bytes("content.tei.xml")
    try:
        document = etree.fromstring(content)
    except etree.XMLSyntaxError as exc:
        raise ValueError("Strong Vol. 2 candidate TEI is not XML") from exc
    if etree.tostring(document, encoding="UTF-8", xml_declaration=True, pretty_print=False) != content:
        raise ValueError("Strong Vol. 2 candidate TEI serialization is not canonical")
    schema = compiled_schema()
    if not schema.validate(etree.ElementTree(document)):
        raise ValueError(f"Strong Vol. 2 TEI P5 validation failed: {schema.error_log.last_error}")
    ns = {"tei": TEI}
    expected_header = {
        "work-id": WORK_ID,
        "gutenberg": "44555",
        "source-sha256": _digest(source),
        "edition": EDITION,
        "source-path": SOURCE_PATH,
    }
    for identifier, wanted in expected_header.items():
        actual = document.xpath(
            f"string(//tei:idno[@type='{identifier}'])", namespaces=ns
        )
        if actual != wanted:
            raise ValueError(f"Strong Vol. 2 TEI header {identifier} drifted")
    if [node.get("type") for node in document.xpath("//tei:idno", namespaces=ns)] != list(expected_header):
        raise ValueError("Strong Vol. 2 TEI header identifier order drifted")
    if (
        document.xpath("string(//tei:title)", namespaces=ns) != "Systematic Theology, Vol. 2"
        or document.xpath("string(//tei:author)", namespaces=ns) != "Augustus H. Strong"
        or document.xpath("string(//tei:publicationStmt/tei:p)", namespaces=ns)
        != "Nonaccepted reconstruction candidate; publication:not_ready."
    ):
        raise ValueError("Strong Vol. 2 TEI identity or publication boundary drifted")
    return {"bytes": len(content), "sha256": _digest(content), **_check_text_and_structure(document, records, headings)}


def _check_provenance(
    candidate: CandidatePackage,
    source_manifest: SourceManifest,
    profile: Mapping[str, object],
    policy: Mapping[str, object],
    source: bytes,
    records: list[dict[str, object]],
    headings: tuple[dict[str, object], ...],
) -> None:
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("attribution-readme").read_bytes():
        raise ValueError("Strong Vol. 2 attribution evidence drifted")
    unresolved = b"".join(_stable_json(item) for item in _expected_unresolved())
    if candidate.member_bytes("unresolved.jsonl") != unresolved:
        raise ValueError("Strong Vol. 2 unresolved evidence drifted")
    if set(policy.get("required_unresolved_ids", [])) != {
        item["id"] for item in _expected_unresolved()
    }:
        raise ValueError("Strong Vol. 2 unresolved policy binding drifted")
    converter = source_manifest.record.get("converter")
    if not isinstance(converter, Mapping):
        raise ValueError("Strong Vol. 2 converter binding is invalid")
    producer_path = source_manifest.repository_root / str(converter["implementation_path"])
    producer_closure = _import_closure(
        source_manifest.repository_root,
        producer_path,
        tuple(str(item) for item in policy.get("producer_forbidden_import_prefixes", [])),
    )
    producer_closure_sha = _digest(_stable_json(producer_closure))
    counts = _required_counts(records, headings)
    source_scope = {
        "bytes": len(source),
        "physical_lines": len(records),
        "source_inventory_sha256": _inventory_digest(records),
    }
    provenance = _load_canonical(candidate.member_bytes("provenance.json"), "Strong Vol. 2 provenance")
    expected_runtime = (
        f"{platform.python_implementation()} {platform.python_version()} "
        f"({Path(sys.executable).resolve(strict=True)})"
    )
    expected_hierarchy = {
        "front": ["title-page", "contents", "front-matter"],
        "parts": 3,
        "chapters": 5,
        "contents_entries": 175,
        "sections": {
            kind: sum(item["kind"] == kind for item in headings)
            for kind in HEADING_KINDS.values()
        },
    }
    if (
        set(provenance) != PROVENANCE_KEYS
        or provenance.get("contract") != "ocd-strong-pg44555-candidate-provenance-v1"
        or provenance.get("status") != "nonaccepted"
        or provenance.get("publication") != "not_ready"
        or provenance.get("work_id") != WORK_ID
        or provenance.get("source_sha256") != _digest(source)
        or provenance.get("source_manifest_sha256") != source_manifest.sha256
        or provenance.get("producer_import_closure") != list(producer_closure)
        or provenance.get("producer_import_closure_sha256") != producer_closure_sha
        or provenance.get("runtime") != expected_runtime
        or provenance.get("source_scope") != source_scope
        or provenance.get("hierarchy") != expected_hierarchy
        or profile.get("source_scope") != source_scope
        or profile.get("required_counts") != counts
    ):
        raise ValueError("Strong Vol. 2 provenance, profile, or producer closure drifted")


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _load_canonical(profile_bytes, "Strong Vol. 2 reconstruction profile")
    policy = _load_object(policy_bytes, "Strong Vol. 2 validation policy")
    if (
        profile.get("contract") != "ocd-strong-pg44555-reconstruction-profile-v1"
        or profile.get("version") != 1
        or profile.get("work_id") != WORK_ID
        or policy.get("contract") != "ocd-strong-pg44555-validation-policy-v1"
        or policy.get("version") != 1
        or policy.get("work_id") != WORK_ID
        or source_manifest.record.get("source_id") != SOURCE_ID
    ):
        raise ValueError("Strong Vol. 2 oracle work/source identity mismatch")
    _candidate_manifest(candidate, source_manifest)
    source = source_manifest.authority_path("retained-source").read_bytes()
    source_authority = _authority(source_manifest, "retained-source")
    if (
        len(source) != int(source_authority["bytes"])
        or _digest(source) != source_authority["sha256"]
        or len(source.splitlines()) != 34523
    ):
        raise ValueError("Strong Vol. 2 exact retained witness drifted")
    records = _scan_source(source)
    headings = _heading_inventory(records)
    counts = _required_counts(records, headings)
    if profile.get("source_scope") != {
        "bytes": len(source),
        "physical_lines": len(records),
        "source_inventory_sha256": _inventory_digest(records),
    } or profile.get("required_counts") != counts:
        raise ValueError("Strong Vol. 2 source profile census drifted")
    _check_accountability(candidate, records, source_authority, counts)
    _check_tei(candidate, source, records, headings)
    _check_provenance(candidate, source_manifest, profile, policy, source, records, headings)

    validator = source_manifest.record.get("validator")
    if not isinstance(validator, Mapping):
        raise ValueError("Strong Vol. 2 validator binding is invalid")
    validator_path = root / str(validator["implementation_path"])
    forbidden = tuple(str(item) for item in policy.get("forbidden_import_prefixes", []))
    validator_closure = _import_closure(root, validator_path, forbidden)
    validator_closure_sha = _digest(_stable_json(validator_closure))
    _runtime_paths(root)
    if (
        _digest(validator_path.read_bytes()) != validator["implementation_sha256"]
        or validator_closure_sha != validator["import_closure_sha256"]
    ):
        raise ValueError("Strong Vol. 2 oracle implementation or closure drifted")
    runtime = (
        f"{platform.python_implementation()} {platform.python_version()} "
        f"({Path(sys.executable).resolve(strict=True)})"
    )
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _digest(validator_path.read_bytes()),
        "import_closure_sha256": validator_closure_sha,
        "runtime": runtime,
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _digest(profile_bytes),
        "package_schema_sha256": _digest(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": _digest(source),
        "xsd_sha256": _digest(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _digest(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _digest(
        _stable_json({key: value for key, value in result.items() if key != "result_sha256"})
    )
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
