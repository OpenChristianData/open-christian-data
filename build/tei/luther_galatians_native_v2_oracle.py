"""Independent source-to-TEI checks for Project Gutenberg 1549."""

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


WORK_ID = "luther-commentary-on-galatians"
SOURCE_ID = "luther-commentary-on-galatians-pg1549-retained"
ORACLE_ID = "ocd-luther-galatians-pg1549-independent-native-line-oracle"
ORACLE_VERSION = "2"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
CHAPTER_LINES = (166, 1410, 2935, 5181, 6703, 8250)
VERSE = re.compile(r"^\s+VERSES?\s+\d")
ACCOUNTABILITY_KEYS = {"contract", "work_id", "source_member", "physical_line_count", "represented_line_count", "evidence_only_line_count", "omitted_line_count", "duplicate_line_count", "source_inventory_sha256", "required_counts", "lines"}
LINE_KEYS = {"line", "byte_start", "byte_end", "terminator", "text", "record_sha256", "disposition", "reason", "tei_selector"}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _read_source(data: bytes) -> list[dict[str, object]]:
    observed: list[dict[str, object]] = []
    cursor = 0
    for physical, payload in enumerate(data.splitlines(keepends=True), 1):
        ending = "CRLF" if payload.endswith(b"\r\n") else "LF" if payload.endswith(b"\n") else "CR" if payload.endswith(b"\r") else "none"
        width = 2 if ending == "CRLF" else 1 if ending in {"LF", "CR"} else 0
        text_bytes = payload[:-width] if width else payload
        observed.append({
            "number": physical,
            "start": cursor,
            "stop": cursor + len(payload),
            "ending": ending,
            "value": text_bytes.decode("utf-8-sig" if physical == 1 else "utf-8", errors="strict"),
            "sha": _digest(payload),
        })
        cursor += len(payload)
    if cursor != len(data):
        raise ValueError("Luther Galatians oracle did not account for all source bytes")
    return observed


def _chapter_numbers(source_rows: list[dict[str, object]]) -> tuple[int, ...]:
    locations = tuple(int(item["number"]) for item in source_rows if re.fullmatch(r"CHAPTER [1-6]", str(item["value"])))
    if locations != CHAPTER_LINES:
        raise ValueError("Luther Galatians source has an unsupported chapter boundary map")
    return locations


def _counts(source_rows: list[dict[str, object]]) -> dict[str, object]:
    carriers = [str(item["value"]) for item in source_rows if VERSE.match(str(item["value"]))]
    return {
        "physical_lines": len(source_rows),
        "blank_lines": sum(str(item["value"]) == "" for item in source_rows),
        "whitespace_only_lines": sum(bool(str(item["value"])) and not str(item["value"]).strip() for item in source_rows),
        "nonblank_lines": sum(bool(str(item["value"]).strip()) for item in source_rows),
        "chapter_count": len(_chapter_numbers(source_rows)),
        "chapter_heading_lines": list(CHAPTER_LINES),
        "singular_verse_carrier_count": sum(item.lstrip().startswith("VERSE ") for item in carriers),
        "plural_verse_carrier_count": sum(item.lstrip().startswith("VERSES ") for item in carriers),
        "verse_carrier_count": len(carriers),
        "represented_lines": len(source_rows),
        "unrepresented_lines": 0,
    }


def _local_module(root: Path, name: str) -> Path | None:
    base = root.joinpath(*name.split("."))
    candidates = (base.with_suffix(".py"), base / "__init__.py")
    return next((candidate.resolve(strict=True) for candidate in candidates if candidate.is_file()), None)


def _closure(root: Path, entry: Path, forbidden: tuple[str, ...]) -> tuple[dict[str, str], ...]:
    root = root.resolve(strict=True)
    queue = [entry.resolve(strict=True)]
    visited: set[Path] = set()
    while queue:
        module_path = queue.pop()
        if module_path in visited:
            continue
        module_path.relative_to(root)
        visited.add(module_path)
        parsed = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        names: list[str] = []
        for node in ast.walk(parsed):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    prefix = node.module or ""
                else:
                    package = list(module_path.relative_to(root).parts[:-1])
                    prefix = ".".join([*package[:len(package) - node.level + 1], *((node.module or "").split(".") if node.module else [])])
                names.extend([prefix, *(f"{prefix}.{alias.name}" for alias in node.names if alias.name != "*")])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "__import__"}:
                raise ValueError("Luther Galatians validator uses dynamic code loading")
        for imported in names:
            if any(imported == blocked or imported.startswith(blocked + ".") for blocked in forbidden):
                raise ValueError(f"Luther Galatians oracle imports prohibited code: {imported}")
            resolved = _local_module(root, imported)
            if resolved is not None and resolved not in visited:
                queue.append(resolved)
    return tuple({"path": item.relative_to(root).as_posix(), "sha256": _digest(item.read_bytes())} for item in sorted(visited, key=lambda item: item.relative_to(root).as_posix()))


def _check_tei(candidate: CandidatePackage, source_rows: list[dict[str, object]], manifest: SourceManifest, source_sha: str) -> None:
    raw = candidate.member_bytes("content.tei.xml")
    root = etree.fromstring(raw)
    xsd_path = manifest.authority_path("tei-p5-xsd")
    etree.XMLSchema(etree.parse(str(xsd_path))).assertValid(etree.ElementTree(root))
    ns = {"t": TEI}
    text_node = root.find(f"{{{TEI}}}text")
    if (root.tag != f"{{{TEI}}}TEI" or root.get("{http://www.w3.org/XML/1998/namespace}lang") is not None
            or text_node is None or text_node.get("{http://www.w3.org/XML/1998/namespace}lang") != "en"):
        raise ValueError("Luther Galatians TEI text language or element is wrong")
    if root.xpath("string(./t:teiHeader/t:fileDesc/t:titleStmt/t:title)", namespaces=ns) != "COMMENTARY ON THE EPISTLE TO THE GALATIANS":
        raise ValueError("Luther Galatians TEI title is not source-bound")
    if root.xpath("string(./t:teiHeader/t:fileDesc/t:titleStmt/t:author)", namespaces=ns) != "Martin Luther":
        raise ValueError("Luther Galatians TEI author is not source-bound")
    if root.xpath("string(./t:teiHeader/t:fileDesc/t:titleStmt/t:respStmt/t:name)", namespaces=ns) != "Theodore Graebner":
        raise ValueError("Luther Galatians TEI translator is not source-bound")
    if source_sha not in root.xpath("string(./t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl)", namespaces=ns):
        raise ValueError("Luther Galatians TEI source description lost the retained digest")
    body = root.find("./{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")
    if body is None:
        raise ValueError("Luther Galatians TEI body is absent")
    top = list(body)
    if len(top) != 9 or [node.get("subtype") for node in top[:2]] != ["gutenberg-header", "work-front-matter"] or top[-1].get("subtype") != "gutenberg-footer":
        raise ValueError("Luther Galatians TEI envelope regions are out of order")
    if [node.get("type") for node in top[2:8]] != ["chapter"] * 6 or [node.get("n") for node in top[2:8]] != [str(number) for number in range(1, 7)]:
        raise ValueError("Luther Galatians six chapter divisions are missing or reordered")
    chapter_lines = set(CHAPTER_LINES)
    selectors: dict[int, etree._Element] = {}
    for node in body.iter():
        value = node.get(XML_ID)
        if value and value.startswith("luther-galatians-line-"):
            try:
                line = int(value.rsplit("-", 1)[1])
            except ValueError as exc:
                raise ValueError("Luther Galatians TEI line identifier is malformed") from exc
            if line in selectors:
                raise ValueError("Luther Galatians TEI duplicates a source-line identity")
            selectors[line] = node
    if set(selectors) != set(range(1, len(source_rows) + 1)):
        raise ValueError("Luther Galatians TEI omitted or invented a physical-line carrier")
    if list(selectors) != list(range(1, len(source_rows) + 1)):
        raise ValueError("Luther Galatians TEI source-line order changed")
    for line, source_row in enumerate(source_rows, 1):
        node = selectors[line]
        value = str(source_row["value"])
        expected_tag = f"{{{TEI}}}head" if line in chapter_lines else f"{{{TEI}}}ab"
        if node.tag != expected_tag or (node.text or "") != value:
            raise ValueError(f"Luther Galatians source line {line} text or structure drifted")
        if line not in chapter_lines:
            expected_kind = "verse-carrier" if VERSE.match(value) else ("blank-line" if value == "" else "source-line")
            expected_type = {"verse-carrier": "source-heading", "blank-line": "blank", "source-line": "source-block"}[expected_kind]
            if (node.get("type") != expected_type or node.get("subtype") != expected_kind
                    or node.get(XML_SPACE) != "preserve" or node.get("n") is not None):
                raise ValueError(f"Luther Galatians source line {line} carrier markup or verse identity drifted")
    if len([row for row in source_rows if VERSE.match(str(row["value"]))]) != 230:
        raise ValueError("Luther Galatians verse-carrier occurrence census drifted")


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    if source_manifest.record.get("work_id") != WORK_ID or source_manifest.record.get("source_id") != SOURCE_ID:
        raise ValueError("Luther Galatians oracle work/source binding mismatch")
    source = source_manifest.authority_path("retained-source").read_bytes()
    source_authority = next(item for item in source_manifest.record["authorities"] if item["name"] == "retained-source")
    if len(source) != source_authority["bytes"] or _digest(source) != source_authority["sha256"]:
        raise ValueError("Luther Galatians oracle retained source mismatch")
    source_rows = _read_source(source)
    if not source.startswith(b"\xef\xbb\xbf") or any(row["ending"] != "CRLF" for row in source_rows):
        raise ValueError("Luther Galatians oracle BOM or CRLF framing drifted")
    if (
        str(source_rows[28]["value"]) != "*** START OF THE PROJECT GUTENBERG EBOOK COMMENTARY ON THE EPISTLE TO THE GALATIANS ***"
        or str(source_rows[8799]["value"]) != "*** END OF THE PROJECT GUTENBERG EBOOK COMMENTARY ON THE EPISTLE TO THE GALATIANS ***"
    ):
        raise ValueError("Luther Galatians oracle Gutenberg envelope markers drifted")
    counts = _counts(source_rows)
    if len(source_rows) != 9150 or counts["singular_verse_carrier_count"] != 216 or counts["plural_verse_carrier_count"] != 14 or counts["verse_carrier_count"] != 230 or counts["chapter_heading_lines"] != list(CHAPTER_LINES):
        raise ValueError("Luther Galatians complete source census failed")
    if (
        str(source_rows[21]["value"]) != "Language: English"
        or str(source_rows[33]["value"]) != "COMMENTARY ON THE EPISTLE TO THE GALATIANS"
        or str(source_rows[37]["value"]) != "By Martin Luther"
        or str(source_rows[39]["value"]) != "Translated by Theodore Graebner"
    ):
        raise ValueError("Luther Galatians source-header identity observations drifted")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    profile = json.loads(profile_bytes)
    if profile.get("required_counts") != counts or profile.get("source_scope") != {
        "path": "raw/gutenberg/pg1549.txt",
        "bytes": len(source),
        "sha256": _digest(source),
        "physical_lines": len(source_rows),
        "encoding": "UTF-8 with BOM",
        "line_ending": "CRLF",
    }:
        raise ValueError("Luther Galatians independent source counts differ from profile")
    record = json.loads(candidate.member_bytes("manifest.json"))
    if record.get("status") != "nonaccepted" or record.get("source_id") != SOURCE_ID or record.get("source_manifest", {}).get("sha256") != source_manifest.sha256:
        raise ValueError("Luther Galatians candidate source/acceptance binding is invalid")
    accountability_bytes = candidate.member_bytes("source-accountability.json")
    accountability = json.loads(accountability_bytes)
    if set(accountability) != ACCOUNTABILITY_KEYS or accountability.get("contract") != "ocd-luther-galatians-source-accountability-v1" or accountability.get("work_id") != WORK_ID:
        raise ValueError("Luther Galatians source-accountability shape or identity is wrong")
    line_rows = accountability.get("lines")
    if not isinstance(line_rows, list) or len(line_rows) != len(source_rows):
        raise ValueError("Luther Galatians source-accountability line census is incomplete")
    expected_inventory = []
    for physical, (actual, carried) in enumerate(zip(source_rows, line_rows, strict=True), 1):
        if not isinstance(carried, dict) or set(carried) != LINE_KEYS:
            raise ValueError("Luther Galatians accountability line shape is invalid")
        observed = {"line": physical, "byte_start": actual["start"], "byte_end": actual["stop"], "terminator": actual["ending"], "text": actual["value"], "record_sha256": actual["sha"]}
        if any(carried.get(key) != value for key, value in observed.items()) or carried.get("disposition") != "represented" or carried.get("tei_selector") != f"#luther-galatians-line-{physical:05d}":
            raise ValueError(f"Luther Galatians source-accountability mismatch at line {physical}")
        expected_inventory.append({"line": physical, "byte_start": actual["start"], "byte_end": actual["stop"], "terminator": actual["ending"], "record_sha256": actual["sha"]})
    if (
        accountability.get("source_member") != {"path": "raw/gutenberg/pg1549.txt", "bytes": len(source), "sha256": _digest(source)}
        or accountability.get("physical_line_count") != len(source_rows)
        or accountability.get("represented_line_count") != len(source_rows)
        or accountability.get("evidence_only_line_count") != 0
        or accountability.get("omitted_line_count") != 0
        or accountability.get("duplicate_line_count") != 0
        or accountability.get("required_counts") != counts
        or accountability.get("source_inventory_sha256") != _digest(_stable(expected_inventory))
    ):
        raise ValueError("Luther Galatians accounting totals or source inventory digest drifted")
    _check_tei(candidate, source_rows, source_manifest, _digest(source))
    validator = source_manifest.record["validator"]
    root = source_manifest.repository_root
    policy = json.loads(source_manifest.authority_path("validation-policy").read_bytes())
    forbidden = tuple(str(item) for item in policy["forbidden_import_prefixes"])
    actual_oracle_path = root / str(validator["implementation_path"])
    oracle_closure = _closure(root, actual_oracle_path, forbidden)
    oracle_closure_sha = _digest(_stable(oracle_closure))
    converter = source_manifest.record["converter"]
    producer_path = root / str(converter["implementation_path"])
    producer_closure = _closure(root, producer_path, ())
    producer_closure_sha = _digest(_stable(producer_closure))
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if (
        provenance.get("contract") != "ocd-luther-galatians-candidate-provenance-v1"
        or provenance.get("status") != "nonaccepted"
        or provenance.get("publication") != "not_ready"
        or provenance.get("work_id") != WORK_ID
        or provenance.get("source_sha256") != _digest(source)
        or provenance.get("source_manifest_sha256") != source_manifest.sha256
        or provenance.get("producer_import_closure") != list(producer_closure)
        or provenance.get("producer_import_closure_sha256") != producer_closure_sha
        or provenance.get("source_scope") != profile.get("source_scope")
        or provenance.get("required_counts") != counts
        or provenance.get("verse_identity_policy") != "No verse-number identity is asserted; source occurrences are located only by physical line number."
    ):
        raise ValueError("Luther Galatians candidate provenance or producer binding drifted")
    unresolved = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").decode("utf-8").splitlines()]
    if [item.get("id") for item in unresolved] != ["edition-identity", "verse-carrier-count-semantics", "rights-clearance", "human-acceptance"] or unresolved[1].get("status") != "unresolved" or "216 singular VERSE and 14 plural VERSES" not in unresolved[1].get("scope", ""):
        raise ValueError("Luther Galatians unresolved count/decision boundaries are missing")
    runtime = f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})"
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _digest(actual_oracle_path.read_bytes()),
        "import_closure_sha256": oracle_closure_sha,
        "runtime": runtime,
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _digest(profile_bytes),
        "package_schema_sha256": _digest(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": _digest(source),
        "xsd_sha256": _digest(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _digest(source_manifest.authority_path("validation-policy").read_bytes()),
        "findings": [],
    }
    result["result_sha256"] = _digest(_stable(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
