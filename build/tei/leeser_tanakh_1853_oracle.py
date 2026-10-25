"""Independent source-line and work-boundary oracle for the Leeser Tanakh."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from collections import Counter
from pathlib import Path

from lxml import etree
from lxml import html
from jsonschema import Draft202012Validator

from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
SOURCE_PREFIX = "source-usfm:englee/"
WORK_ID = "isaac-leeser-tanakh"
SOURCE_ID = "ebible-englee-leeser-1853-usfm"
ORACLE_ID = "ocd-englee-independent-source-line-oracle-current"
ORACLE_VERSION = "1"
EXPECTED_BOOK_IDS = (
    "GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT", "1SA", "2SA",
    "1KI", "2KI", "1CH", "2CH", "EZR", "NEH", "EST", "JOB", "PSA", "PRO",
    "ECC", "SNG", "ISA", "JER", "LAM", "EZK", "DAN", "HOS", "JOL", "AMO",
    "OBA", "JON", "MIC", "NAM", "HAB", "ZEP", "HAG", "ZEC", "MAL",
)


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_object(data: bytes, label: str) -> dict[str, object]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result
    value = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _profile(manifest) -> dict[str, object]:
    return _load_object(manifest.authority_path("leeser-profile").read_bytes(), "profile")


def _source_parts(data: bytes, member: str) -> tuple[str, list[str], list[str]]:
    text = data.decode("utf-8", errors="strict")
    if text.startswith("\ufeff") or "\r" in text or text.endswith("\n"):
        raise ValueError(f"source line-ending contract failed for {member}")
    lines = text.split("\n")
    if not lines or any(not line.startswith("\\") for line in lines):
        raise ValueError(f"source contains empty or unmarked line in {member}")
    first = lines[0].split(maxsplit=2)
    if len(first) < 2 or first[0] != r"\id":
        raise ValueError(f"source member ID is malformed: {member}")
    book_id = first[1]
    chapters = []
    for line in lines:
        marker = line[1:].split(maxsplit=1)[0]
        if marker == "c":
            rest = line[2:].lstrip()
            label = rest.split(maxsplit=1)[0] if rest else ""
            if not label:
                raise ValueError(f"empty chapter label in {member}")
            chapters.append(label)
        elif marker not in {"id", "h", "toc1", "toc2", "toc3", "mt1", "mt2", "p", "v"}:
            raise ValueError(f"unprofiled source marker {marker!r} in {member}")
    return book_id, lines, chapters


def _source_inventory(manifest, profile: dict[str, object]) -> tuple[list[dict[str, object]], list[tuple[str, list[str], list[str]]]]:
    rows = [dict(item) for item in manifest.record["authorities"] if item.get("role") == "primary-source"]
    support = [dict(item) for item in manifest.record["authorities"] if item.get("role") == "supporting-source"]
    expected_names = list(profile["book_members"])
    if len(rows) != 39 or [Path(row["path"]).name for row in rows] != expected_names:
        raise ValueError("source manifest does not bind the exact 39 ordered book members")
    if len(support) != 3 or {Path(row["path"]).name for row in support} != {"copr.htm", "keys.asc", "dejavuserif.css"}:
        raise ValueError("source manifest support-member set drift")
    parsed = []
    for position, row in enumerate(rows):
        raw = manifest.authority_path(f"usfm-{position + 1:02d}").read_bytes()
        if len(raw) != row["bytes"] or _sha(raw) != row["sha256"]:
            raise ValueError(f"USFM authority hash mismatch: {row['path']}")
        book_id, lines, chapters = _source_parts(raw, Path(row["path"]).name)
        if book_id != EXPECTED_BOOK_IDS[position] or book_id != profile["book_ids"][position]:
            raise ValueError(f"book identity/order mismatch at position {position + 1}")
        parsed.append((book_id, lines, chapters))
    for row in support:
        raw = manifest.authority_path(row["name"]).read_bytes()
        if len(raw) != row["bytes"] or _sha(raw) != row["sha256"]:
            raise ValueError(f"support authority hash mismatch: {row['path']}")
        if Path(row["path"]).name == "copr.htm":
            page = html.fromstring(raw)
            h1 = [value.strip() for value in page.xpath("//h1/text()")]
            h2 = [value.strip() for value in page.xpath("//h2/text()")]
            text = " ".join(" ".join(page.xpath("//p//text()" )).split())
            if h1 != ["Isaac Leeser Tanakh"] or h2 != ["The Isaac Leeser Tanakh (Jewish Bible)"] or "Translation by: Isaac Leeser" not in text:
                raise ValueError("retained title page does not establish the declared work title/translator")
    return rows, parsed


def oracle(manifest, candidate) -> dict[str, object]:
    manifest.verify()
    if manifest.record.get("work_id") != WORK_ID or manifest.record.get("source_id") != SOURCE_ID:
        raise ValueError("work/source identity mismatch")
    profile = _profile(manifest)
    sources, parsed = _source_inventory(manifest, profile)
    tei_bytes = candidate.member_bytes("content.tei.xml")
    document = etree.fromstring(tei_bytes, etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False))
    xsd = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd"))))
    tree = etree.ElementTree(document)
    if not xsd.validate(tree):
        raise ValueError("candidate TEI fails the bound TEI P5 XSD: " + str(xsd.error_log[0]))
    if document.tag != TEI + "TEI" or document.get(XML_ID) != WORK_ID:
        raise ValueError("candidate must be one TEI document with the declared work identity")
    works = document.findall(".//" + TEI + "body/" + TEI + "div[@type='work']")
    if len(works) != 1 or works[0].get(XML_ID) != WORK_ID + "-work":
        raise ValueError("candidate work boundary must resolve to exactly one top-level TEI work")
    books = works[0].findall(TEI + "div[@type='book']")
    if len(books) != 39:
        raise ValueError("candidate must contain all 39 books nested under the Tanakh work")
    observed_lines = 0
    observed_chapters = 0
    observed_verses = 0
    marker_counts: Counter[str] = Counter()
    member_records = []
    for book_pos, (book, source_row, source) in enumerate(zip(books, sources, parsed), 1):
        book_id, lines, expected_chapters = source
        member_name = Path(source_row["path"]).name
        if book.get("n") != book_id or book.get(XML_ID) != f"{WORK_ID}-book-{book_id}":
            raise ValueError(f"book TEI identity mismatch: {member_name}")
        chapters = book.findall(TEI + "div[@type='chapter']")
        observed_labels = [node.get("n") for node in chapters]
        if observed_labels != expected_chapters:
            raise ValueError(f"chapter order/labels differ from {member_name}")
        if any(node.get(XML_ID) is None for node in chapters):
            raise ValueError(f"chapter lacks stable xml:id in {member_name}")
        carriers = book.findall(".//" + TEI + "ab[@type='usfm-source-line']")
        if len(carriers) != len(lines):
            raise ValueError(f"omitted or duplicated source lines in {member_name}")
        for line_no, (line, carrier) in enumerate(zip(lines, carriers), 1):
            if carrier.text != line or carrier.get("n") != str(line_no) or carrier.get(XML_SPACE) != "preserve":
                raise ValueError(f"source line text/order/space mismatch at {member_name}:{line_no}")
            if carrier.get("corresp") != f"{SOURCE_PREFIX}{member_name}#line={line_no}":
                raise ValueError(f"source pointer mismatch at {member_name}:{line_no}")
            marker = line[1:].split(maxsplit=1)[0]
            marker_counts[marker] += 1
            observed_lines += 1
            observed_chapters += marker == "c"
            observed_verses += marker == "v"
        member_records.append({"path": source_row["path"], "bytes": source_row["bytes"], "sha256": source_row["sha256"], "book_id": book_id, "source_lines": len(lines), "chapters": len(expected_chapters)})
    if (observed_lines, observed_chapters, observed_verses) != (25239, 929, 23145):
        raise ValueError("complete source counts differ from the profiled evidence")
    header_titles = document.findall(".//" + TEI + "titleStmt/" + TEI + "title")
    header_authors = document.findall(".//" + TEI + "titleStmt/" + TEI + "author")
    if [node.text for node in header_titles] != ["Isaac Leeser Tanakh"] or [node.text for node in header_authors] != ["Isaac Leeser"]:
        raise ValueError("source-supported work title or translator is absent")
    support_rows = [dict(item) for item in manifest.record["authorities"] if item.get("role") == "supporting-source"]
    account = {
        "contract": "ocd-englee-source-accountability-v1",
        "source_manifest_sha256": manifest.sha256,
        "source_archive_sha256": profile["source_archive_sha256"],
        "work_id": WORK_ID,
        "work_boundary": profile["work_boundary"],
        "book_members": [Path(row["path"]).name for row in sources],
        "book_ids": [book_id for book_id, _, _ in parsed],
        "books": member_records,
        "support_members": [{"path": row["path"], "bytes": row["bytes"], "sha256": row["sha256"], "role": row["role"]} for row in support_rows],
        "book_count": 39,
        "source_line_count": observed_lines,
        "chapter_count": observed_chapters,
        "verse_count": observed_verses,
        "line_marker_counts": dict(sorted(marker_counts.items())),
        "line_mapping": "Every decoded USFM source line is one ordered TEI ab carrier with a member and line pointer.",
        "support_member_policy": profile["support_member_policy"],
        "excluded": [],
    }
    if candidate.member_bytes("source-accountability.json") != _canonical(account):
        raise ValueError("source-accountability member differs from independent source reconstruction")
    account_schema = _load_object(manifest.authority_path("leeser-accountability-schema").read_bytes(), "accountability schema")
    account_errors = sorted(Draft202012Validator(account_schema).iter_errors(account), key=lambda error: list(error.path))
    if account_errors:
        raise ValueError("source-accountability schema failure: " + account_errors[0].message)
    provenance = _load_object(candidate.member_bytes("provenance.json"), "provenance")
    expected_provenance = {
        "work_id": WORK_ID, "textual_form_id": "english", "edition_id": "ebible-englee-leeser-1853",
        "acquisition_id": "ebible-englee-usfm", "source_id": SOURCE_ID,
        "source_manifest_sha256": manifest.sha256, "source_archive_sha256": profile["source_archive_sha256"],
        "candidate_status": "nonaccepted", "human_acceptance": "not-recorded",
        "rights_assessment": "not-assessed", "publication_authorization": "not-established",
    }
    if provenance != expected_provenance:
        raise ValueError("candidate provenance identity or decision boundary mismatch")
    expected_unresolved = b'{"kind":"edition-collation","status":"not-performed","scope":"The retained electronic transcription has not been collated against the 1853 print witness."}\n'
    if candidate.member_bytes("unresolved.jsonl") != expected_unresolved:
        raise ValueError("edition collation limitation must remain explicit")

    closure_names = (
        "build/tei/leeser_tanakh_1853_oracle.py",
        "ocd_kernel/reconstruction/verifier.py",
        "ocd_kernel/reconstruction/contract.py",
    )
    closure_rows = []
    for name in closure_names:
        path = manifest.repository_root / name
        content = path.read_bytes()
        closure_rows.append({"path": name, "bytes": len(content), "sha256": _sha(content)})
    closure_sha = _sha(_canonical(closure_rows))
    primary_records = sorted(
        ({"name": row["name"], "path": row["path"], "bytes": row["bytes"], "sha256": row["sha256"]} for row in sources),
        key=lambda row: (row["path"], row["name"]),
    )
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha((manifest.repository_root / closure_names[0]).read_bytes()),
        validator_import_closure_sha256=closure_sha,
        source_sha256=_sha(_canonical({"contract": "ocd-source-member-set-v1", "members": primary_records})),
        profile_sha256=_sha(manifest.authority_path("leeser-profile").read_bytes()),
        package_schema_sha256=_sha(manifest.authority_path("candidate-package-schema").read_bytes()),
        xsd_sha256=_sha(manifest.authority_path("tei-p5-xsd").read_bytes()),
        policy_sha256=_sha(manifest.authority_path("leeser-policy").read_bytes()),
        findings=(),
    )
    return verify_mechanical_facts(manifest, candidate, facts).as_record()


oracle.oracle_id = ORACLE_ID  # type: ignore[attr-defined]
oracle.oracle_version = ORACLE_VERSION  # type: ignore[attr-defined]
