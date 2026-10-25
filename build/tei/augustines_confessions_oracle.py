"""Independent source-derived verifier for the 37c-062 candidate."""

from __future__ import annotations

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


ORACLE_ID = "ocd-augustines-confessions-independent-source-oracle"
ORACLE_VERSION = "2"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_SOURCE_BYTES = 632167
_SOURCE_SHA256 = "5a036498dc7c546a98b9e7a31952e030ca74db7dd111b30029354efe12bcd691"
_CENTERED_TERMINAL_SOURCE_LINE = 9367
_CENTERED_TERMINAL_SOURCE_TEXT = "GRATIAS TIBI DOMINE"
_CENTERED_TERMINAL_LEADING_SPACES = 25
_CENTERED_TERMINAL_REND = "align-center"
_BOOK_LABEL = re.compile(r"BOOK ([IVX]+)\s*\Z")
_BOOKS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _parse_witness(data: bytes) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str]]:
    # Independent index-based pass: the verifier records source-byte slices
    # first, then derives paragraph groups from its own phase and blank-line rules.
    chunks = data.splitlines(keepends=True)
    decoded: list[str] = []
    records: list[dict[str, object]] = []
    positions: list[int] = []
    cursor = 0
    for number, chunk in enumerate(chunks, 1):
        positions.append(cursor)
        cursor += len(chunk)
        ending = "CRLF" if chunk.endswith(b"\r\n") else "LF" if chunk.endswith(b"\n") else "CR" if chunk.endswith(b"\r") else "none"
        terminator_bytes = {"CRLF": 2, "LF": 1, "CR": 1, "none": 0}[ending]
        content = chunk[:-terminator_bytes] if terminator_bytes else chunk
        decoded.append(content.decode("utf-8", errors="strict"))
        records.append({"line": number, "byte_start": positions[-1], "byte_end": positions[-1] + len(content), "terminator": ending, "record_sha256": _digest(content), "kind": "", "tei_id": None})
    begin = [i for i, value in enumerate(decoded) if value.startswith("*** START OF THE PROJECT GUTENBERG EBOOK ")]
    finish = [i for i, value in enumerate(decoded) if value.startswith("*** END OF THE PROJECT GUTENBERG EBOOK ")]
    if len(begin) != 1 or len(finish) != 1 or begin[0] >= finish[0]:
        raise ValueError("Confessions source envelope is not uniquely delimited")
    low, high = begin[0], finish[0]
    books: list[str] = []
    groups: list[dict[str, object]] = []
    active_lines: list[int] = []
    active_class: str | None = None
    active_book: str | None = None

    def commit_group() -> None:
        nonlocal active_lines, active_class
        if not active_lines:
            return
        if active_class == "provider-header":
            bucket, book = "provider", None
        elif active_class == "title-page":
            bucket, book = "title", None
        elif active_class == "license":
            bucket, book = "license", None
        else:
            bucket, book = f"book-{active_book}", active_book
        ordinal = sum(record.get("section") == bucket and record.get("kind") == "paragraph" for record in groups) + 1
        identifier = f"confessions-{bucket}-p-{ordinal:04d}"
        rendered = " ".join(decoded[line].strip() for line in active_lines).strip()
        group = {"kind": "paragraph", "section": bucket, "book": book, "id": identifier, "text": rendered, "lines": active_lines.copy()}
        if len(active_lines) == 1 and active_lines[0] == _CENTERED_TERMINAL_SOURCE_LINE - 1:
            expected_source_line = " " * _CENTERED_TERMINAL_LEADING_SPACES + _CENTERED_TERMINAL_SOURCE_TEXT
            if active_class != "book-text" or active_book != "XIII" or decoded[active_lines[0]] != expected_source_line:
                raise ValueError("Confessions terminal centered line no longer matches its independent source witness")
            group["rend"] = _CENTERED_TERMINAL_REND
        groups.append(group)
        for line in active_lines:
            records[line]["tei_id"] = identifier
        active_lines = []
        active_class = None

    def add_single(line: int, kind: str, identifier: str) -> None:
        groups.append({"kind": kind, "section": kind, "book": active_book, "id": identifier, "text": decoded[line], "lines": [line]})
        records[line]["tei_id"] = identifier

    for zero, value in enumerate(decoded):
        if not value.strip():
            category = "blank-layout"
        elif zero < low:
            category = "provider-header"
        elif zero == low:
            category = "start-marker"
        elif zero == high:
            category = "end-marker"
        elif zero > high:
            category = "license"
        else:
            found = _BOOK_LABEL.fullmatch(value.strip())
            if found:
                category = "book-heading"
                active_book = found.group(1)
                if active_book in books:
                    raise ValueError("Confessions has a repeated book label")
                books.append(active_book)
            else:
                category = "title-page" if active_book is None else "book-text"
        records[zero]["kind"] = category
        if category == "blank-layout":
            commit_group()
        elif category == "book-heading":
            commit_group()
            add_single(zero, category, f"confessions-book-{active_book}-head")
        elif category in {"start-marker", "end-marker"}:
            commit_group()
            add_single(zero, category, f"confessions-{category}")
        else:
            if active_class is not None and active_class != category:
                commit_group()
            active_class = category
            active_lines.append(zero)
    commit_group()
    if len(data) != _SOURCE_BYTES or cursor != len(data) or len(decoded) != 9724 or books != list(_BOOKS):
        raise ValueError("Confessions source byte, line, or ordered-book census mismatch")
    centered_terminal = [group for group in groups if group.get("rend") == _CENTERED_TERMINAL_REND]
    if len(centered_terminal) != 1:
        raise ValueError("Confessions source-centered doxology is not unique")
    centered_index = groups.index(centered_terminal[0])
    if centered_index + 1 >= len(groups) or groups[centered_index + 1].get("kind") != "end-marker":
        raise ValueError("Confessions source-centered doxology is not the final Book XIII paragraph")
    return records, groups, books


def _project_closure(root: Path) -> str:
    files = (Path(__file__).resolve(strict=True), (root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True), (root / "ocd_kernel/reconstruction/__init__.py").resolve(strict=True))
    rows = [{"path": file.relative_to(root).as_posix(), "sha256": _digest(file.read_bytes())} for file in sorted(files, key=lambda item: item.relative_to(root).as_posix())]
    return _digest(_json_bytes(rows))


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    record = source_manifest.record
    if record.get("source_id") != "augustine-confessions-project-gutenberg-pg3296" or record.get("work_id") != "augustines-confessions" or candidate.manifest.get("source_id") != record.get("source_id") or candidate.manifest.get("status") != "nonaccepted" or candidate.manifest.get("source_manifest") != {"path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(), "sha256": source_manifest.sha256} or candidate.manifest.get("converter") != record.get("converter") or candidate.manifest.get("package_schema") != record.get("package_schema"):
        raise ValueError("Confessions candidate authority binding mismatch")
    source = source_manifest.authority_path("retained-text").read_bytes()
    if _digest(source) != _SOURCE_SHA256 or len(source) != _SOURCE_BYTES:
        raise ValueError("Confessions source authority mismatch")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    profile = json.loads(profile_bytes)
    source_text = source.decode("utf-8", errors="strict")
    source_header = source_text.split("*** START OF THE PROJECT GUTENBERG EBOOK ", 1)[0]
    metadata = profile.get("source_observations", {})
    source_claims = {
        "provider": "Project Gutenberg",
        "ebook_id": "3296",
        "title": "The Confessions of St. Augustine",
        "author_label": "Saint of Hippo Augustine",
        "translator_label": "E. B. Pusey",
        "release_date_label": "June 1, 2002",
        "updated_date_label": "May 5, 2023",
        "credit_label": "Robert S. Munday",
        "rights_status": "Source notice asserts no-cost use in the United States and most other parts of the world, subject to the included Project Gutenberg license and a local-law check outside the United States. This is an observation, not rights clearance."
    }
    header_claims = {
        "title": "Title: The Confessions of St. Augustine",
        "author_label": "Author: Saint of Hippo Augustine",
        "translator_label": "Translator: E. B. Pusey",
        "release_date_label": "Release date: June 1, 2002 [eBook #3296]",
        "updated_date_label": "Most recently updated: May 5, 2023",
        "credit_label": "Credits: Robert S. Munday"
    }
    header_lines = {line.strip() for line in source_header.splitlines()}
    if metadata != source_claims or any(claim not in header_lines for claim in header_claims.values()):
        raise ValueError("Confessions profile metadata is not supported by exact retained-header statements")
    rights_header = source_header.casefold()
    if "at no cost and with almost no restrictions" not in rights_header or "check the laws of the country" not in rights_header or "project gutenberg license included with this ebook" not in rights_header:
        raise ValueError("Confessions qualified provider rights notice is incomplete")
    rows, groups, books = _parse_witness(source)
    expected_accountability = {"contract": "ocd-augustines-confessions-source-accountability-v1", "work_id": "augustines-confessions", "source_id": record["source_id"], "source_bytes": len(source), "source_sha256": _digest(source), "physical_line_count": len(rows), "line_inventory_sha256": _digest(_json_bytes(rows)), "line_inventory": rows, "book_order": books, "paragraph_count": sum(group["kind"] == "paragraph" for group in groups), "omitted_count": 0, "duplicate_count": 0}
    account_bytes = candidate.member_bytes("source-accountability.json")
    account = json.loads(account_bytes)
    if account != expected_accountability or account_bytes != _json_bytes(expected_accountability):
        raise ValueError("Confessions source line accounting does not match independent traversal")
    schema = json.loads(source_manifest.authority_path("source-accountability-schema").read_bytes())
    errors = sorted(Draft202012Validator(schema).iter_errors(expected_accountability), key=str)
    if errors:
        raise ValueError(f"Confessions accountability schema failure: {errors[0].message}")

    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"), etree.XMLParser(resolve_entities=False, no_network=True))
    ns = {"t": _TEI, "xml": "http://www.w3.org/XML/1998/namespace"}
    schema_doc = etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))
    compiled = etree.XMLSchema(schema_doc)
    if not compiled.validate(tree):
        raise ValueError(f"Confessions TEI fails the bound TEI P5 schema: {compiled.error_log.last_error}")
    if tree.get(_XML_ID) != "augustines-confessions-pg3296-candidate":
        raise ValueError("Confessions TEI identity mismatch")
    observed_nodes = tree.xpath("/t:TEI/t:text//t:p | /t:TEI/t:text//t:head[@xml:id]", namespaces=ns)
    expected_nodes = [(str(group["id"]), str(group["text"])) for group in groups]
    actual_nodes = [(node.get(_XML_ID), "".join(node.itertext())) for node in observed_nodes]
    if actual_nodes != expected_nodes:
        difference = next((index for index in range(max(len(actual_nodes), len(expected_nodes))) if index >= len(actual_nodes) or index >= len(expected_nodes) or actual_nodes[index] != expected_nodes[index]), None)
        raise ValueError(f"Confessions TEI/source paragraph mismatch at {difference}: actual={actual_nodes[difference] if difference is not None and difference < len(actual_nodes) else None!r}; expected={expected_nodes[difference] if difference is not None and difference < len(expected_nodes) else None!r}")
    centered_terminal = [group for group in groups if group.get("rend") == _CENTERED_TERMINAL_REND]
    if len(centered_terminal) != 1:
        raise ValueError("Confessions independent source traversal did not identify exactly one centered terminal doxology")
    centered_nodes = tree.xpath("/t:TEI/t:text/t:body/t:div[@type='book' and @n='XIII']/t:p[@xml:id=$target_id]", namespaces=ns, target_id=centered_terminal[0]["id"])
    if len(centered_nodes) != 1 or centered_nodes[0].get("rend") != _CENTERED_TERMINAL_REND:
        raise ValueError("Confessions TEI does not preserve the source-centered terminal doxology")
    book_nodes = tree.xpath("/t:TEI/t:text/t:body/t:div[@type='book']", namespaces=ns)
    if [(node.get("n"), node.get(_XML_ID)) for node in book_nodes] != [(book, f"confessions-book-{book}") for book in books]:
        raise ValueError("Confessions TEI book divisions do not match source order")
    if tree.xpath("string(/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title)", namespaces=ns) != metadata["title"] or tree.xpath("string(/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:author)", namespaces=ns) != metadata["author_label"] or tree.xpath("string(/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:respStmt/t:name)", namespaces=ns) != metadata["translator_label"] or tree.xpath("string(/t:TEI/t:teiHeader/t:fileDesc/t:publicationStmt/t:availability/t:p)", namespaces=ns) != metadata["rights_status"]:
        raise ValueError("Confessions TEI header claims are not bound to the retained source observations")
    if tree.xpath("string(/t:TEI/t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:idno[@type='sha256'])", namespaces=ns) != _SOURCE_SHA256:
        raise ValueError("Confessions TEI source digest mismatch")

    authorities = {str(item["name"]): {key: item[key] for key in ("path", "bytes", "sha256", "role")} for item in record["authorities"]}
    expected_provenance = {"contract": "ocd-augustines-confessions-candidate-provenance-v1", "status": "nonaccepted", "work_id": "augustines-confessions", "ticket_id": "LIB-077", "source_id": record["source_id"], "source_manifest_sha256": source_manifest.sha256, "rights_observation": json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())["source_observations"]["rights_status"], "authorities": authorities, "acceptance_status": "not-accepted", "release_status": "not-selected", "publication_status": "not-authorized", "canonical_data_or_ir_written": False}
    if json.loads(candidate.member_bytes("provenance.json")) != expected_provenance:
        raise ValueError("Confessions provenance or decision-boundary mutation")
    unresolved_expected = [
        {"id": "augustines-confessions-edition-history", "status": "unresolved", "kind": "identity", "detail": "The retained electronic source does not establish a print imprint, edition statement, composition date, or first-publication date."},
        {"id": "augustines-confessions-rights-review", "status": "unresolved", "kind": "rights", "detail": "Project Gutenberg's qualified notice and full license are transcribed as source evidence; human rights and distribution review remains outstanding."},
        {"id": "augustines-confessions-human-acceptance", "status": "unresolved", "kind": "acceptance", "detail": "This candidate has not received human textual acceptance, release selection, or publication authorization."}
    ]
    if [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").splitlines()] != unresolved_expected:
        raise ValueError("Confessions unresolved decisions changed")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-attribution-readme").read_bytes():
        raise ValueError("Confessions source attribution README mismatch")
    validator = record["validator"]
    closure = _project_closure(source_manifest.repository_root)
    if validator.get("implementation_sha256") != _digest(Path(__file__).read_bytes()) or validator.get("import_closure_sha256") != closure:
        raise ValueError("Confessions oracle implementation binding mismatch")
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    result: dict[str, object] = {"status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION, "implementation_sha256": _digest(Path(__file__).read_bytes()), "import_closure_sha256": closure, "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})", "source_manifest_sha256": source_manifest.sha256, "candidate_sha256": candidate.sha256, "profile_sha256": _digest(profile_bytes), "package_schema_sha256": _digest(source_manifest.authority_path("candidate-package-schema").read_bytes()), "source_sha256": _digest(source), "xsd_sha256": _digest(source_manifest.authority_path("tei-p5-xsd").read_bytes()), "policy_sha256": _digest(policy_bytes), "findings": []}
    result["result_sha256"] = _digest(_json_bytes(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
