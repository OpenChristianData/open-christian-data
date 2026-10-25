"""Producer-independent source and TEI oracle for Project Gutenberg #44035."""

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


ORACLE_ID = "ocd-strong-pg44035-independent-volume-oracle"
ORACLE_VERSION = "3"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"
XML_SPACE = f"{{{XML}}}space"
WORK_ID = "strong-systematic-theology-vol-1"
SOURCE_ID = "strong-systematic-theology-vol-1-pg44035-retained"
VOLUME_RANGE = (26, 30580)
TITLE_PAGE_RANGE = (26, 62)
CONTENTS_RANGE = (63, 290)
PREFACE_RANGE = (291, 465)
PARTS = (
    ("I", 466, 4489),
    ("II", 4489, 9138),
    ("III", 9138, 19981),
    ("IV", 19981, 30581),
)
CHAPTERS = (
    ("I", 471, 2324),
    ("II", 2324, 3365),
    ("III", 3365, 4489),
    ("I", 4494, 5944),
    ("II", 5944, 7441),
    ("III", 7441, 9138),
    ("I", 9143, 11832),
    ("II", 11832, 16034),
    ("III", 16034, 19981),
    ("I", 19986, 25058),
    ("II", 25058, 29180),
    ("III", 29180, 30581),
)
CONTENTS_PREFIX = re.compile(
    r"^(?:Preface|Part\s+|Chapter\s+|[IVXLCDM]+\.\s+|\d+\.\s+|"
    r"\d+(?:st|nd|rd|th|d)\.\s+|[A-Z]\.\s+|"
    r"(?:First|Second|Third) [Dd]ivision\.)"
)
HEADING_TYPES = {6: "section", 9: "subsection", 12: "subsubsection"}
PARENT_TYPES = {
    "section": "chapter",
    "subsection": "section",
    "subsubsection": "subsection",
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
    "source_member",
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
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


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
        raise ValueError("Strong oracle source authorities are invalid")
    found = [item for item in authorities if item.get("name") == name]
    if len(found) != 1:
        raise ValueError(f"Strong oracle authority {name} cardinality mismatch")
    return found[0]


def _scan_witness(data: bytes) -> list[dict[str, object]]:
    """Read physical records directly, retaining byte positions and wording."""

    records: list[dict[str, object]] = []
    cursor = 0
    for number, raw in enumerate(data.splitlines(keepends=True), start=1):
        if raw.endswith(b"\r\n"):
            body, terminator = raw[:-2], "CRLF"
        elif raw.endswith(b"\n"):
            body, terminator = raw[:-1], "LF"
        else:
            body, terminator = raw, "none"
        try:
            text = body.decode("utf-8-sig" if number == 1 else "utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Strong retained source line {number} is not UTF-8") from exc
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
    if not records or cursor != len(data) or records[-1]["end"] != len(data):
        raise ValueError("Strong retained source physical record boundary drifted")
    return records


def _inventory_digest(records: list[dict[str, object]]) -> str:
    return _digest(
        _stable_json(
            [
                {
                    "line": record["number"],
                    "byte_start": record["start"],
                    "byte_end": record["end"],
                    "terminator": record["terminator"],
                    "record_sha256": record["record_sha256"],
                }
                for record in records
            ]
        )
    )


def _line_id(number: int) -> str:
    return f"{WORK_ID}-line-{number:05d}"


def _normal(text: str) -> str:
    return " ".join(text.split())


def _contents_entries(records: list[dict[str, object]]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    active: dict[str, object] | None = None
    for record in records:
        number = int(record["number"])
        if number < 66 or number > 256:
            continue
        raw = str(record["text"])
        if not raw.strip():
            continue
        stripped = raw.strip()
        if CONTENTS_PREFIX.match(stripped):
            active = {
                "toc_line": number,
                "indent": len(raw) - len(raw.lstrip(" ")),
                "pieces": [_normal(stripped)],
            }
            entries.append(active)
        elif active is not None:
            pieces = active["pieces"]
            assert isinstance(pieces, list)
            pieces.append(_normal(stripped))
    for entry in entries:
        pieces = entry.pop("pieces")
        assert isinstance(pieces, list)
        entry["text"] = " ".join(str(piece) for piece in pieces)
    return entries


def _body_runs(records: list[dict[str, object]]) -> list[dict[str, object]]:
    runs: list[dict[str, object]] = []
    current: list[dict[str, object]] = []

    def finish() -> None:
        if not current:
            return
        numbers = [int(item["number"]) for item in current]
        runs.append(
            {
                "first": numbers[0],
                "last": numbers[-1],
                "records": tuple(current),
                "text": _normal(" ".join(str(item["text"]) for item in current)),
            }
        )
        current.clear()

    for record in records:
        number = int(record["number"])
        if number < 466 or number > 30580:
            continue
        if str(record["text"]).strip():
            current.append(record)
        else:
            finish()
    finish()
    return runs


def _heading_inventory(records: list[dict[str, object]]) -> tuple[dict[str, object], ...]:
    entries = _contents_entries(records)
    runs = _body_runs(records)
    by_text: dict[str, list[dict[str, object]]] = {}
    for run in runs:
        by_text.setdefault(str(run["text"]).casefold(), []).append(run)

    matched = 0
    headings: list[dict[str, object]] = []
    for entry in entries:
        candidates = by_text.get(str(entry["text"]).casefold(), [])
        if len(candidates) == 1:
            matched += 1
        kind = HEADING_TYPES.get(int(entry["indent"]))
        if kind is None or len(candidates) != 1:
            continue
        run = candidates[0]
        run_records = run["records"]
        assert isinstance(run_records, tuple)
        headings.append(
            {
                "start_line": int(run["first"]),
                "end_line": int(run["last"]),
                "kind": kind,
                "toc_line": int(entry["toc_line"]),
                "toc_indent": int(entry["indent"]),
                "line_numbers": [int(item["number"]) for item in run_records],
            }
        )
    headings.sort(key=lambda item: int(item["start_line"]))
    if len(entries) != 176 or matched != 175 or len(headings) != 159:
        raise ValueError(
            f"Strong independent contents census drifted: entries={len(entries)}, "
            f"matches={matched}, headings={len(headings)}"
        )
    return tuple(headings)


def _required_counts(
    records: list[dict[str, object]], headings: tuple[dict[str, object], ...]
) -> dict[str, object]:
    selected = records[VOLUME_RANGE[0] - 1 : VOLUME_RANGE[1]]
    return {
        "part_count": len(PARTS),
        "chapter_count": len(CHAPTERS),
        "part_line_numbers": [item[1] for item in PARTS],
        "chapter_line_numbers": [item[1] for item in CHAPTERS],
        "title_page_line_range": list(TITLE_PAGE_RANGE),
        "contents_line_range": list(CONTENTS_RANGE),
        "preface_line_range": list(PREFACE_RANGE),
        "volume_line_range": list(VOLUME_RANGE),
        "volume_nonblank_lines": sum(str(item["text"]) != "" for item in selected),
        "volume_blank_lines": sum(str(item["text"]) == "" for item in selected),
        "contents_entry_count": 176,
        "contents_body_match_count": 175,
        "mapped_heading_count": len(headings),
        "mapped_heading_line_ranges": [
            [int(item["start_line"]), int(item["end_line"])] for item in headings
        ],
        "mapped_heading_kind_counts": {
            kind: sum(item["kind"] == kind for item in headings)
            for kind in ("section", "subsection", "subsubsection")
        },
    }


def _module_file(root: Path, dotted: str) -> Path | None:
    base = root.joinpath(*dotted.split("."))
    options = (base.with_suffix(".py"), base / "__init__.py")
    for option in options:
        if option.is_file():
            return option.resolve(strict=True)
    return None


def _import_targets(path: Path, root: Path, node: ast.ImportFrom) -> tuple[str, ...]:
    if node.level == 0:
        prefix = node.module or ""
    else:
        package_parts = list(path.relative_to(root).parts[:-1])
        prefix = ".".join(
            [
                *package_parts[: len(package_parts) - node.level + 1],
                *((node.module or "").split(".") if node.module else []),
            ]
        )
    return tuple(
        [prefix, *(f"{prefix}.{alias.name}" for alias in node.names if alias.name != "*")]
    )


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
                raise ValueError("Strong oracle closure contains dynamic execution")
        for target in targets:
            if any(target == prefix or target.startswith(prefix + ".") for prefix in forbidden):
                raise ValueError(f"Strong oracle closure contains forbidden import {target}")
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
        module = sys.modules.get(name)
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str):
            raise ValueError(f"Strong oracle runtime dependency {name} has no path")
        resolved = Path(module_file).resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Strong oracle runtime dependency {name} is outside root") from exc


def _expected_unresolved() -> list[dict[str, str]]:
    unresolved = (
        (
            "edition-identity",
            "The retained witness identifies the revised and enlarged 1907 Judson Press edition through Project Gutenberg #44035; no claim is made that the electronic transcription is a complete diplomatic facsimile of every paper-edition feature.",
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
            "The retained member is volume 1 of a three-file Project Gutenberg set. Only pg44035.txt is in this ticket's declared member scope; volumes 2 and 3 are not silently inferred or included.",
        ),
        (
            "human-acceptance",
            "This candidate is nonaccepted and has no human textual, identity, editorial, or rights acceptance.",
        ),
    )
    return [
        {"id": f"{WORK_ID}-{suffix}", "status": "unresolved", "detail": detail}
        for suffix, detail in unresolved
    ]


def _candidate_manifest(
    candidate: CandidatePackage, source_manifest: SourceManifest
) -> dict[str, object]:
    record = _load_canonical(
        candidate.member_bytes("manifest.json"), "Strong candidate manifest"
    )
    members = record.get("members")
    expected_path = source_manifest.path.relative_to(
        source_manifest.repository_root
    ).as_posix()
    if (
        set(record) != CANDIDATE_KEYS
        or not isinstance(members, list)
        or [item.get("name") for item in members if isinstance(item, dict)]
        != CANDIDATE_MEMBER_NAMES
        or any(
            not isinstance(item, dict)
            or set(item) != {"name", "bytes", "sha256"}
            for item in members
        )
        or record.get("contract") != "ocd-candidate-package-v1"
        or record.get("status") != "nonaccepted"
        or record.get("source_id") != SOURCE_ID
        or record.get("source_manifest")
        != {"path": expected_path, "sha256": source_manifest.sha256}
        or record.get("converter") != source_manifest.record.get("converter")
        or record.get("package_schema") != source_manifest.record.get("package_schema")
    ):
        raise ValueError("Strong candidate authority binding mutation")
    return record


def _expected_accounting(
    records: list[dict[str, object]],
    authority: Mapping[str, object],
    counts: dict[str, object],
) -> dict[str, object]:
    lines: list[dict[str, object]] = []
    for record in records:
        number = int(record["number"])
        in_volume = VOLUME_RANGE[0] <= number <= VOLUME_RANGE[1]
        represented = in_volume and str(record["text"]) != ""
        if represented:
            disposition = "represented"
            reason = "retained volume line represented in the TEI hierarchy"
            selector: str | None = f"#{_line_id(number)}"
        elif in_volume:
            disposition = "evidence-only"
            reason = "source paragraph separator represented by TEI block structure"
            selector = None
        else:
            disposition = "evidence-only"
            reason = "Project Gutenberg wrapper or license envelope retained as evidence-only"
            selector = None
        lines.append(
            {
                "line": number,
                "byte_start": int(record["start"]),
                "byte_end": int(record["end"]),
                "terminator": record["terminator"],
                "text": record["text"],
                "record_sha256": record["record_sha256"],
                "disposition": disposition,
                "reason": reason,
                "tei_selector": selector,
            }
        )
    represented_count = sum(item["disposition"] == "represented" for item in lines)
    return {
        "contract": "ocd-strong-pg44035-source-accountability-v1",
        "work_id": WORK_ID,
        "source_member": {key: authority[key] for key in ("path", "bytes", "sha256")},
        "volume_line_range": list(VOLUME_RANGE),
        "physical_line_count": len(records),
        "represented_line_count": represented_count,
        "evidence_only_line_count": len(lines) - represented_count,
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "source_inventory_sha256": _inventory_digest(records),
        "required_counts": counts,
        "lines": lines,
    }


def _check_accounting(
    candidate: CandidatePackage,
    records: list[dict[str, object]],
    authority: Mapping[str, object],
    counts: dict[str, object],
) -> dict[str, object]:
    observed = _load_canonical(
        candidate.member_bytes("source-accountability.json"), "Strong source accountability"
    )
    expected = _expected_accounting(records, authority, counts)
    if set(observed) != ACCOUNTABILITY_KEYS:
        raise ValueError("Strong accountability key set drifted")
    for key in ACCOUNTABILITY_KEYS - {"lines"}:
        if observed.get(key) != expected[key]:
            raise ValueError(f"Strong accountability field drifted: {key}")
    lines = observed.get("lines")
    expected_lines = expected["lines"]
    if (
        not isinstance(lines, list)
        or not isinstance(expected_lines, list)
        or len(lines) != len(expected_lines)
    ):
        raise ValueError("Strong source line accounting is incomplete")
    for index, (actual, wanted) in enumerate(
        zip(lines, expected_lines, strict=True), start=1
    ):
        if not isinstance(actual, dict) or set(actual) != ACCOUNTABILITY_LINE_KEYS:
            raise ValueError(f"Strong source line record {index} shape drifted")
        if actual != wanted:
            raise ValueError(f"Strong source line record {index} drifted")
    return {
        "physical_line_count": len(records),
        "represented_line_count": expected["represented_line_count"],
        "evidence_only_line_count": expected["evidence_only_line_count"],
        "source_inventory_sha256": expected["source_inventory_sha256"],
    }


def _node_text(node: etree._Element) -> str:
    return node.text or ""


def _check_head(
    head: etree._Element,
    kind: str,
    expected_records: list[dict[str, object]],
) -> None:
    first = expected_records[0]
    if (
        head.tag != f"{{{TEI}}}head"
        or head.get("type") != kind
        or head.get("n") != str(first["number"])
        or head.get(XML_ID) != _line_id(int(first["number"]))
        or head.get(XML_SPACE) != "preserve"
        or _node_text(head) != str(first["text"])
    ):
        raise ValueError(f"Strong {kind} head carrier drifted at line {first['number']}")
    children = list(head)
    expected_children = 2 * (len(expected_records) - 1)
    if len(children) != expected_children:
        raise ValueError(f"Strong {kind} wrapped-line count drifted")
    for offset, record in enumerate(expected_records[1:]):
        lb = children[offset * 2]
        segment = children[offset * 2 + 1]
        number = int(record["number"])
        if (
            lb.tag != f"{{{TEI}}}lb"
            or segment.tag != f"{{{TEI}}}seg"
            or segment.get(XML_ID) != _line_id(number)
            or segment.get("n") != str(number)
            or segment.get("type") != "source-line"
            or segment.get(XML_SPACE) != "preserve"
            or _node_text(segment) != str(record["text"])
        ):
            raise ValueError(f"Strong wrapped head carrier drifted at line {number}")


def _records_by_number(records: list[dict[str, object]]) -> dict[int, dict[str, object]]:
    return {int(record["number"]): record for record in records}


def _source_body_paths(
    records: list[dict[str, object]], headings: tuple[dict[str, object], ...]
) -> dict[int, tuple[tuple[str, str], ...]]:
    """Derive the enclosing source intervals without consulting the producer."""

    heading_by_start = {int(item["start_line"]): item for item in headings}
    paths: dict[int, tuple[tuple[str, str], ...]] = {}
    active: list[dict[str, object]] = []
    part_starts = {int(item[1]) for item in PARTS}
    chapter_starts = {int(item[1]) for item in CHAPTERS}
    for record in records:
        number = int(record["number"])
        if number < 466 or number > 30580:
            continue
        part = next(
            ((name, start, end) for name, start, end in PARTS if start <= number < end),
            None,
        )
        chapter = next(
            ((name, start, end) for name, start, end in CHAPTERS if start <= number < end),
            None,
        )
        if part is None or (number < 4494 and number >= 4489 and chapter is None):
            if part is None:
                raise ValueError(f"Strong source line {number} is outside a declared part")
        if number in part_starts or number in chapter_starts:
            active.clear()
        heading = heading_by_start.get(number)
        if heading is not None:
            level = {"section": 1, "subsection": 2, "subsubsection": 3}[str(heading["kind"])]
            while active and int(active[-1]["level"]) >= level:
                active.pop()
            active.append({"level": level, **heading})
        if part is None:
            continue
        path: list[tuple[str, str]] = [("part", str(part[0]))]
        if chapter is not None:
            path.append(("chapter", str(chapter[0])))
        path.extend(
            (str(item["kind"]), str(item["start_line"])) for item in active
        )
        paths[number] = tuple(path)
    return paths


def _actual_body_path(
    node: etree._Element, body: etree._Element, ns: dict[str, str]
) -> tuple[tuple[str, str], ...]:
    path: list[tuple[str, str]] = []
    current = node
    allowed = {"part", "chapter", "section", "subsection", "subsubsection"}
    while current is not None and current is not body:
        if current.tag == f"{{{TEI}}}div" and current.get("type") in allowed:
            path.append((str(current.get("type")), str(current.get("n"))))
        current = current.getparent()
    if current is not body:
        raise ValueError("Strong source carrier escaped the TEI body")
    return tuple(reversed(path))


def _source_prose_groups(
    records: list[dict[str, object]], headings: tuple[dict[str, object], ...]
) -> list[list[int]]:
    """Derive body paragraph groups from retained blank-line boundaries."""

    heading_lines = {
        int(number)
        for item in headings
        for number in item["line_numbers"]
    }
    excluded = heading_lines | {int(item[1]) for item in PARTS} | {
        int(item[1]) for item in CHAPTERS
    }
    groups: list[list[int]] = []
    for run in _body_runs(records):
        run_records = run["records"]
        assert isinstance(run_records, tuple)
        numbers = [int(item["number"]) for item in run_records]
        if any(number in excluded for number in numbers):
            if not all(number in excluded for number in numbers):
                raise ValueError("Strong source run mixes structural and prose lines")
            continue
        groups.append(numbers)
    return groups


def _check_text_shell(
    front: etree._Element,
    body: etree._Element,
    expected_ids: set[str],
) -> None:
    """Reject unbound text, tails, and unknown wrappers in readable TEI."""

    allowed = {"front", "body", "div", "head", "p", "seg", "ab", "lb"}
    carrier_tags = {"head", "seg", "ab"}
    for root in (front, body):
        for node in root.iter():
            local = etree.QName(node).localname
            if local not in allowed:
                raise ValueError(
                    f"Strong readable TEI contains an unexpected {local} node"
                )
            identifier = node.get(XML_ID)
            if identifier is not None and identifier not in expected_ids:
                raise ValueError("Strong readable TEI contains an unexpected source identifier")
            if local in carrier_tags and identifier not in expected_ids:
                raise ValueError("Strong readable TEI carrier is missing its source identifier")
            if node.text:
                if identifier not in expected_ids or local not in carrier_tags:
                    raise ValueError("Strong readable TEI contains unbound text")
            if node.tail:
                raise ValueError("Strong readable TEI contains unbound tail text")


def _check_structural_shell(
    front: etree._Element, body: etree._Element
) -> None:
    """Constrain the readable tree without constructing an expected tree."""

    def local(node: etree._Element) -> str:
        return etree.QName(node).localname

    if [local(child) for child in front] != ["div", "div", "div"]:
        raise ValueError("Strong TEI front child shell drifted")
    front_divs = list(front)
    if [child.get("type") for child in front_divs] != [
        "title-page",
        "contents",
        "preface",
    ]:
        raise ValueError("Strong TEI front division shell drifted")
    for node in front_divs[:2]:
        if any(local(child) != "ab" for child in node):
            raise ValueError("Strong TEI front line shell drifted")
    preface_children = list(front_divs[2])
    if not preface_children or local(preface_children[0]) != "head":
        raise ValueError("Strong TEI preface shell drifted")
    if any(local(child) != "p" for child in preface_children[1:]):
        raise ValueError("Strong TEI preface prose shell drifted")
    if [local(child) for child in body] != ["div"] * len(body):
        raise ValueError("Strong TEI body child shell drifted")
    for part in body:
        if part.get("type") != "part":
            raise ValueError("Strong TEI body contains a non-part division")
        children = list(part)
        if not children or local(children[0]) != "head" or any(
            local(child) != "div" or child.get("type") != "chapter"
            for child in children[1:]
        ):
            raise ValueError("Strong TEI part child shell drifted")
    for chapter in body.xpath(".//tei:div[@type='chapter']", namespaces={"tei": TEI}):
        children = list(chapter)
        if not children or local(children[0]) != "head" or any(
            local(child) not in {"p", "div"}
            or (local(child) == "div" and child.get("type") != "section")
            for child in children[1:]
        ):
            raise ValueError("Strong TEI chapter child shell drifted")
    for kind, child_kind in (("section", "subsection"), ("subsection", "subsubsection")):
        for node in body.xpath(f".//tei:div[@type='{kind}']", namespaces={"tei": TEI}):
            children = list(node)
            if not children or local(children[0]) != "head":
                raise ValueError(f"Strong TEI {kind} child shell drifted")
            for child in children[1:]:
                if local(child) == "p":
                    continue
                if local(child) == "div" and child.get("type") == child_kind:
                    continue
                raise ValueError(f"Strong TEI {kind} child shell drifted")
    for node in body.xpath(".//tei:div[@type='subsubsection']", namespaces={"tei": TEI}):
        children = list(node)
        if not children or local(children[0]) != "head" or any(
            local(child) != "p" for child in children[1:]
        ):
            raise ValueError("Strong TEI subsubsection child shell drifted")
    heads = [
        *front.xpath(".//tei:head", namespaces={"tei": TEI}),
        *body.xpath(".//tei:head", namespaces={"tei": TEI}),
    ]
    for node in heads:
        if any(local(child) not in {"lb", "seg"} for child in node):
            raise ValueError("Strong TEI head child shell drifted")
    paragraphs = [
        *front.xpath(".//tei:p", namespaces={"tei": TEI}),
        *body.xpath(".//tei:p", namespaces={"tei": TEI}),
    ]
    for node in paragraphs:
        children = list(node)
        if any(
            local(child) != "seg" if index % 2 == 0 else local(child) != "lb"
            for index, child in enumerate(children)
        ):
            raise ValueError("Strong TEI paragraph carrier shell drifted")
        if not children or local(children[-1]) != "seg":
            raise ValueError("Strong TEI paragraph carrier shell drifted")
    leaves = [
        *front.xpath(".//tei:ab", namespaces={"tei": TEI}),
        *body.xpath(".//tei:seg", namespaces={"tei": TEI}),
        *front.xpath(".//tei:seg", namespaces={"tei": TEI}),
        *body.xpath(".//tei:lb", namespaces={"tei": TEI}),
        *front.xpath(".//tei:lb", namespaces={"tei": TEI}),
    ]
    for node in leaves:
        if len(node):
            raise ValueError("Strong TEI source carrier contains an unexpected child")


def _check_tei_layout(
    document: etree._Element,
    records: list[dict[str, object]],
    headings: tuple[dict[str, object], ...],
) -> dict[str, object]:
    ns = {"tei": TEI, "xml": XML}
    by_number = _records_by_number(records)
    selected_numbers = [
        int(record["number"])
        for record in records[VOLUME_RANGE[0] - 1 : VOLUME_RANGE[1]]
        if str(record["text"]) != ""
    ]
    carrier_nodes = document.xpath("//*[@xml:id]", namespaces=ns)
    carrier_ids = [node.get(XML_ID) for node in carrier_nodes]
    expected_ids = [_line_id(number) for number in selected_numbers]
    if carrier_ids != expected_ids or len(set(carrier_ids)) != len(expected_ids):
        raise ValueError("Strong TEI source-line carrier order or cardinality drifted")
    carriers = {node.get(XML_ID): node for node in carrier_nodes}
    for number in selected_numbers:
        node = carriers.get(_line_id(number))
        record = by_number[number]
        if (
            node is None
            or node.get("n") != str(number)
            or node.get(XML_SPACE) != "preserve"
            or _node_text(node) != str(record["text"])
        ):
            raise ValueError(f"Strong TEI source wording or line binding drifted at line {number}")

    text = document.find(f"{{{TEI}}}text")
    if text is None:
        raise ValueError("Strong TEI text element is absent")
    front = text.find(f"{{{TEI}}}front")
    body = text.find(f"{{{TEI}}}body")
    if front is None or body is None:
        raise ValueError("Strong TEI front/body boundary is absent")
    _check_structural_shell(front, body)
    _check_text_shell(front, body, set(expected_ids))
    front_children = [child for child in front if child.tag == f"{{{TEI}}}div"]
    if [child.get("type") for child in front_children] != ["title-page", "contents", "preface"]:
        raise ValueError("Strong TEI front matter order drifted")
    preface_heads = front_children[2].xpath("./tei:head", namespaces=ns)
    if not preface_heads or list(front_children[2])[0] is not preface_heads[0]:
        raise ValueError("Strong TEI preface head is not the direct first child")

    expected_part_lines = {start: (name, end) for name, start, end in PARTS}
    expected_chapter_lines = {start: (name, end) for name, start, end in CHAPTERS}
    part_nodes = body.xpath("./tei:div[@type='part']", namespaces=ns)
    if len(part_nodes) != len(PARTS):
        raise ValueError("Strong TEI part count drifted")
    chapter_nodes = body.xpath("./tei:div[@type='part']/tei:div[@type='chapter']", namespaces=ns)
    if len(chapter_nodes) != len(CHAPTERS):
        raise ValueError("Strong TEI chapter count drifted")
    for part_node, (name, start, _end) in zip(part_nodes, PARTS, strict=True):
        if part_node.get("n") != name:
            raise ValueError(f"Strong TEI part label drifted at line {start}")
        heads = part_node.xpath("./tei:head", namespaces=ns)
        if len(heads) != 1 or not list(part_node) or list(part_node)[0] is not heads[0]:
            raise ValueError(f"Strong TEI part head cardinality drifted at line {start}")
        _check_head(heads[0], "part", [by_number[start]])
    for chapter_node, (name, start, _end) in zip(chapter_nodes, CHAPTERS, strict=True):
        if chapter_node.get("n") != name:
            raise ValueError(f"Strong TEI chapter label drifted at line {start}")
        heads = chapter_node.xpath("./tei:head", namespaces=ns)
        if len(heads) != 1 or not list(chapter_node) or list(chapter_node)[0] is not heads[0]:
            raise ValueError(f"Strong TEI chapter head cardinality drifted at line {start}")
        _check_head(heads[0], "chapter", [by_number[start]])

    expected_by_start = {int(item["start_line"]): item for item in headings}
    heading_lines: set[int] = set()
    for item in headings:
        heading_lines.update(int(number) for number in item["line_numbers"])
        start = int(item["start_line"])
        kind = str(item["kind"])
        matches = document.xpath(f"//*[@xml:id='{_line_id(start)}']", namespaces=ns)
        if len(matches) != 1 or matches[0].tag != f"{{{TEI}}}head":
            raise ValueError(f"Strong source heading carrier is absent at line {start}")
        head = matches[0]
        parent = head.getparent()
        if parent is None or parent.tag != f"{{{TEI}}}div" or parent.get("type") != kind:
            raise ValueError(f"Strong {kind} heading attachment drifted at line {start}")
        _check_head(
            head,
            kind,
            [by_number[int(number)] for number in item["line_numbers"]],
        )

    actual_heading_divs = document.xpath(
        "//tei:div[@type='section' or @type='subsection' or @type='subsubsection']",
        namespaces=ns,
    )
    expected_counts = {"section": 56, "subsection": 67, "subsubsection": 36}
    actual_counts = {
        kind: sum(node.get("type") == kind for node in actual_heading_divs)
        for kind in expected_counts
    }
    if actual_counts != expected_counts:
        raise ValueError("Strong mapped heading div counts drifted")
    actual_starts: set[int] = set()
    for node in actual_heading_divs:
        kind = str(node.get("type"))
        head = node.find(f"{{{TEI}}}head")
        if head is None or not list(node) or list(node)[0] is not head or len(node.xpath("./tei:head", namespaces=ns)) != 1:
            raise ValueError(f"Strong {kind} heading div has no direct head")
        start = int(head.get("n", "0"))
        actual_starts.add(start)
        expected_parent = PARENT_TYPES[kind]
        parent = node.getparent()
        if parent is None or parent.tag != f"{{{TEI}}}div" or parent.get("type") != expected_parent:
            raise ValueError(f"Strong {kind} heading parent type drifted at line {start}")
        expected = expected_by_start.get(start)
        if expected is None or expected["kind"] != kind:
            raise ValueError(f"Strong TEI contains an uncorrelated {kind} heading at line {start}")
    if actual_starts != set(expected_by_start):
        raise ValueError("Strong TEI heading locations drifted from source inventory")

    part_start_lines = set(expected_part_lines)
    chapter_start_lines = set(expected_chapter_lines)
    preface_head_line = PREFACE_RANGE[0]
    for number in selected_numbers:
        node = carriers[_line_id(number)]
        parent = node.getparent()
        if number in part_start_lines:
            expected_tag, expected_type = "head", "part"
            valid_parent = parent is not None and parent.get("type") == "part"
        elif number in chapter_start_lines:
            expected_tag, expected_type = "head", "chapter"
            valid_parent = parent is not None and parent.get("type") == "chapter"
        elif number == preface_head_line:
            expected_tag, expected_type = "head", "preface"
            valid_parent = parent is not None and parent.get("type") == "preface"
        elif TITLE_PAGE_RANGE[0] <= number <= TITLE_PAGE_RANGE[1]:
            expected_tag, expected_type = "ab", "title-page-line"
            valid_parent = parent is not None and parent.get("type") == "title-page"
        elif CONTENTS_RANGE[0] <= number <= CONTENTS_RANGE[1]:
            expected_tag, expected_type = "ab", "contents-line"
            valid_parent = parent is not None and parent.get("type") == "contents"
        elif number in heading_lines:
            expected_tag, expected_type = None, None
            valid_parent = True
        else:
            expected_tag, expected_type = "seg", "source-line"
            valid_parent = parent is not None and parent.tag == f"{{{TEI}}}p"
        if not valid_parent:
            raise ValueError(f"Strong source line {number} has the wrong TEI parent")
        if expected_tag is not None and (
            node.tag != f"{{{TEI}}}{expected_tag}" or node.get("type") != expected_type
        ):
            raise ValueError(f"Strong source line {number} has the wrong TEI carrier type")
        if number in heading_lines and node.tag not in {
            f"{{{TEI}}}head",
            f"{{{TEI}}}seg",
        }:
            raise ValueError(f"Strong heading line {number} has the wrong TEI carrier")

    expected_groups = _source_prose_groups(records, headings)
    actual_groups: list[list[int]] = []
    for paragraph in body.xpath(".//tei:p", namespaces=ns):
        actual_groups.append(
            [
                int(child.get("n", "0"))
                for child in paragraph
                if child.tag == f"{{{TEI}}}seg"
            ]
        )
    if actual_groups != expected_groups:
        raise ValueError("Strong TEI paragraph grouping drifted from source blank runs")

    expected_paths = _source_body_paths(records, headings)
    body_interval_count = 0
    for number in selected_numbers:
        if number < 466:
            continue
        expected_path = expected_paths.get(number)
        if expected_path is None:
            raise ValueError(f"Strong body source interval is absent at line {number}")
        actual_path = _actual_body_path(carriers[_line_id(number)], body, ns)
        if actual_path != expected_path:
            raise ValueError(
                f"Strong source interval ancestry drifted at line {number}: "
                f"expected {expected_path}, observed {actual_path}"
            )
        body_interval_count += 1

    return {
        "source_line_carrier_count": len(selected_numbers),
        "part_count": len(part_nodes),
        "chapter_count": len(chapter_nodes),
        "head_count": len(actual_heading_divs) + len(part_nodes) + len(chapter_nodes) + 1,
        "mapped_heading_counts": actual_counts,
        "body_interval_ancestry_carrier_count": body_interval_count,
        "substantive_lines_retained_as_prose": [
            number
            for number in (636, 29375)
            if carriers[_line_id(number)].tag == f"{{{TEI}}}seg"
            and carriers[_line_id(number)].getparent().tag == f"{{{TEI}}}p"
        ],
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
        raise ValueError("Strong candidate TEI is not XML") from exc
    if etree.tostring(document, encoding="UTF-8", xml_declaration=True, pretty_print=False) != content:
        raise ValueError("Strong candidate TEI serialization is not canonical")
    schema = compiled_schema()
    if not schema.validate(etree.ElementTree(document)):
        raise ValueError(f"Strong candidate TEI P5 validation failed: {schema.error_log.last_error}")
    ns = {"tei": TEI}
    source_sha = _digest(source)
    expected_header = {
        "work-id": WORK_ID,
        "gutenberg": "44035",
        "source-sha256": source_sha,
        "edition": "Revised and enlarged edition (Judson Press, 1907), PG#44035 (Vol. 1 of 3 files)",
        "source-path": "raw/gutenberg/pg44035.txt",
    }
    for identifier, wanted in expected_header.items():
        actual = document.xpath(
            f"string(//tei:idno[@type='{identifier}'])", namespaces=ns
        )
        if actual != wanted:
            raise ValueError(f"Strong TEI header {identifier} drifted")
    header_idno_types = [
        item.get("type")
        for item in document.xpath("//tei:idno", namespaces=ns)
    ]
    if header_idno_types != [
        "work-id",
        "gutenberg",
        "source-sha256",
        "edition",
        "source-path",
    ]:
        raise ValueError("Strong TEI header identifier set or order drifted")
    if (
        document.xpath("string(//tei:author)", namespaces=ns) != "Augustus H. Strong"
        or document.xpath("string(//tei:title)", namespaces=ns)
        != "Systematic Theology, Vol. 1"
        or document.xpath("string(//tei:publicationStmt/tei:p)", namespaces=ns)
        != "Nonaccepted reconstruction candidate; publication:not_ready."
    ):
        raise ValueError("Strong TEI identity or publication boundary drifted")
    layout = _check_tei_layout(document, records, headings)
    return {"bytes": len(content), "sha256": _digest(content), **layout}


def _check_provenance(
    candidate: CandidatePackage,
    source_manifest: SourceManifest,
    profile: Mapping[str, object],
    policy: Mapping[str, object],
    source: bytes,
    records: list[dict[str, object]],
    headings: tuple[dict[str, object], ...],
) -> None:
    readme = source_manifest.authority_path("attribution-readme").read_bytes()
    if (
        candidate.member_bytes("README.source.md") != readme
        or b"Project Gutenberg" not in readme
        or b"publication:not_ready" not in readme
    ):
        raise ValueError("Strong attribution and rights README drifted")
    unresolved = b"".join(_stable_json(item) for item in _expected_unresolved())
    if candidate.member_bytes("unresolved.jsonl") != unresolved:
        raise ValueError("Strong unresolved evidence drifted")
    if set(policy.get("required_unresolved_ids", [])) != {
        item["id"] for item in _expected_unresolved()
    }:
        raise ValueError("Strong unresolved policy bindings drifted")
    converter = source_manifest.record.get("converter")
    if not isinstance(converter, Mapping):
        raise ValueError("Strong converter binding is invalid")
    producer_path = source_manifest.repository_root / str(converter["implementation_path"])
    forbidden = tuple(str(item) for item in policy.get("producer_forbidden_import_prefixes", []))
    producer_closure = _import_closure(
        source_manifest.repository_root, producer_path, forbidden
    )
    producer_closure_sha = _digest(_stable_json(producer_closure))
    counts = _required_counts(records, headings)
    source_scope = {
        "bytes": len(source),
        "physical_lines": len(records),
        "source_inventory_sha256": _inventory_digest(records),
    }
    expected_hierarchy = {
        "front": ["title-page", "contents", "preface"],
        "parts": 4,
        "chapters": 12,
        "contents_entries": 176,
        "sections": {"section": 56, "subsection": 67, "subsubsection": 36},
    }
    provenance = _load_canonical(
        candidate.member_bytes("provenance.json"), "Strong provenance"
    )
    expected_runtime = (
        f"{platform.python_implementation()} {platform.python_version()} "
        f"({Path(sys.executable).resolve(strict=True)})"
    )
    if (
        set(provenance) != PROVENANCE_KEYS
        or provenance.get("contract") != "ocd-strong-pg44035-candidate-provenance-v2"
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
        or profile.get("producer_import_closure_sha256") != producer_closure_sha
        or profile.get("source_scope") != source_scope
        or profile.get("required_counts") != counts
    ):
        raise ValueError("Strong provenance, profile, or producer closure drifted")


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    """Reconcile retained source records with the actual candidate tree."""

    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _load_canonical(profile_bytes, "Strong reconstruction profile")
    policy = _load_object(policy_bytes, "Strong validation policy")
    if (
        profile.get("contract") != "ocd-strong-pg44035-reconstruction-profile-v2"
        or profile.get("version") != 2
        or profile.get("work_id") != WORK_ID
        or policy.get("contract") != "ocd-strong-pg44035-validation-policy-v2"
        or policy.get("version") != 2
        or policy.get("work_id") != WORK_ID
        or source_manifest.record.get("source_id") != SOURCE_ID
    ):
        raise ValueError("Strong oracle work/source identity mismatch")
    _candidate_manifest(candidate, source_manifest)
    source = source_manifest.authority_path("retained-source").read_bytes()
    source_authority = _authority(source_manifest, "retained-source")
    if (
        len(source) != int(source_authority["bytes"])
        or _digest(source) != source_authority["sha256"]
        or len(source.splitlines()) != 30931
    ):
        raise ValueError("Strong exact retained witness drifted")
    records = _scan_witness(source)
    headings = _heading_inventory(records)
    counts = _required_counts(records, headings)
    _check_accounting(candidate, records, source_authority, counts)
    _check_tei(candidate, source, records, headings)
    _check_provenance(candidate, source_manifest, profile, policy, source, records, headings)

    validator = source_manifest.record.get("validator")
    if not isinstance(validator, Mapping):
        raise ValueError("Strong validator binding is invalid")
    validator_path = root / str(validator["implementation_path"])
    validator_forbidden = tuple(str(item) for item in policy.get("forbidden_import_prefixes", []))
    validator_closure = _import_closure(root, validator_path, validator_forbidden)
    validator_closure_sha = _digest(_stable_json(validator_closure))
    _runtime_paths(root)
    if (
        _digest(validator_path.read_bytes()) != validator["implementation_sha256"]
        or validator_closure_sha != validator["import_closure_sha256"]
    ):
        raise ValueError("Strong oracle implementation or closure drifted")
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
        "package_schema_sha256": _digest(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": _digest(source),
        "xsd_sha256": _digest(
            source_manifest.authority_path("tei-p5-xsd").read_bytes()
        ),
        "policy_sha256": _digest(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _digest(
        _stable_json(
            {key: value for key, value in result.items() if key != "result_sha256"}
        )
    )
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
