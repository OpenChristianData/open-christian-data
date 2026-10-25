"""Independent retained-byte oracle for the Covenanter Luther route."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-luther-bondage-covenanter-independent-oracle"
ORACLE_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
NS = {"tei": TEI}
SOURCE_SHA = "5e3ce6432bd668596cca5b9ffbdfa8cb8c024dc9dbc4ab5ed109324e32e5400a"
WORK_ID = "luther-bondage-of-the-will"
PAGE_RE = re.compile(r"^=== PAGE ([a-z0-9-]+) ===$")
URL_RE = re.compile(r"^URL: (https://www\.covenanter\.org/.+)$")
TITLE_RE = re.compile(r"^TITLE: (.+)$")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} duplicate key {key!r}")
            result[key] = value
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    if not isinstance(value, dict) or _canonical(value) != content:
        raise ValueError(f"{label} is not canonical JSON")
    return value


def _authority(manifest: SourceManifest, name: str) -> Mapping[str, object]:
    matches = [
        item for item in manifest.record["authorities"] if item.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Luther oracle authority {name} cardinality mismatch")
    return matches[0]


def _scan(content: bytes) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    offset = 0
    for number, record in enumerate(content.splitlines(keepends=True), 1):
        if record.endswith(b"\r\n"):
            payload, terminator = record[:-2], "CRLF"
        elif record.endswith(b"\n"):
            payload, terminator = record[:-1], "LF"
        else:
            payload, terminator = record, "none"
        rows.append(
            {
                "line": number,
                "byte_start": offset,
                "byte_end": offset + len(record),
                "terminator": terminator,
                "text": payload.decode("utf-8"),
                "record_sha256": _sha(record),
            }
        )
        offset += len(record)
    if offset != len(content):
        raise ValueError("Luther oracle byte accounting failed")
    return rows


def _page_model(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    starts = [
        index for index, row in enumerate(rows) if PAGE_RE.fullmatch(str(row["text"]))
    ]
    if len(starts) != 13 or starts[0] != 0:
        raise ValueError("Luther oracle page census drifted")
    result: list[dict[str, object]] = []
    for ordinal, start in enumerate(starts, 1):
        end = starts[ordinal] if ordinal < len(starts) else len(rows)
        group = rows[start:end]
        marker = PAGE_RE.fullmatch(str(group[0]["text"]))
        url = URL_RE.fullmatch(str(group[1]["text"]))
        title = TITLE_RE.fullmatch(str(group[2]["text"]))
        if marker is None or url is None or title is None:
            raise ValueError("Luther oracle page metadata adjacency drifted")
        result.append(
            {
                "ordinal": ordinal,
                "slug": marker.group(1),
                "url": url.group(1),
                "title": title.group(1),
                "line_start": int(group[0]["line"]),
                "line_end": int(group[-1]["line"]),
                "lines": group,
            }
        )
    return result


def _kind(text: str) -> str:
    if not text:
        return "blank"
    if PAGE_RE.fullmatch(text):
        return "page-marker"
    if URL_RE.fullmatch(text):
        return "page-url"
    if TITLE_RE.fullmatch(text):
        return "page-title"
    if text.startswith("Sect. "):
        return "section-start"
    if text.isupper() and len(text) < 160:
        return "display-heading"
    return "source-line"


def _expected_tei(
    rows: list[dict[str, object]], pages: list[dict[str, object]]
) -> bytes:
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    root.set(XML_ID, "luther-bondage-covenanter-candidate")
    header = etree.SubElement(root, f"{{{TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI}}}title").text = "The Bondage of the Will"
    etree.SubElement(title_stmt, f"{{{TEI}}}author").text = "Martin Luther"
    resp = etree.SubElement(title_stmt, f"{{{TEI}}}respStmt")
    etree.SubElement(resp, f"{{{TEI}}}resp").text = "English translation"
    etree.SubElement(resp, f"{{{TEI}}}name").text = "Henry Cole"
    publication = etree.SubElement(file_desc, f"{{{TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI}}}p").text = (
        "Nonaccepted reconstruction candidate. The retained transcription supplies no "
        "license or permission statement; human rights review is required and "
        "publication is not ready."
    )
    source_desc = etree.SubElement(file_desc, f"{{{TEI}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{TEI}}}bibl")
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="work-id").text = WORK_ID
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="sha256").text = SOURCE_SHA
    etree.SubElement(
        bibl, f"{{{TEI}}}title"
    ).text = "Martin Luther on the Bondage of the Will, Henry Cole translation, 1823"
    etree.SubElement(
        bibl, f"{{{TEI}}}publisher"
    ).text = "Covenanter.org web transcription provider"
    encoding = etree.SubElement(header, f"{{{TEI}}}encodingDesc")
    etree.SubElement(encoding, f"{{{TEI}}}p").text = (
        "Every physical UTF-8 source line is represented once in byte order. Line-ending "
        "bytes remain bound in source-accountability.json."
    )
    body = etree.SubElement(etree.SubElement(root, f"{{{TEI}}}text"), f"{{{TEI}}}body")
    for page in pages:
        div = etree.SubElement(
            body,
            f"{{{TEI}}}div",
            type="source-page",
            n=str(page["ordinal"]),
            source=str(page["url"]),
        )
        div.set(XML_ID, f"luther-page-{page['ordinal']:02d}-{page['slug']}")
        etree.SubElement(div, f"{{{TEI}}}head", type="source-page-title").text = str(
            page["title"]
        )
        for row in page["lines"]:
            number = int(row["line"])
            node = etree.SubElement(
                div, f"{{{TEI}}}ab", n=str(number), type=_kind(str(row["text"]))
            )
            node.set(XML_ID, f"luther-line-{number:04d}")
            node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            node.text = str(row["text"]) or None
    return etree.tostring(
        root, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )


def _module_path(root: Path, name: str) -> Path | None:
    stem = root.joinpath(*name.split("."))
    for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
        if candidate.is_file():
            return candidate.resolve(strict=True)
    return None


def _imports(path: Path, root: Path, node: ast.ImportFrom) -> tuple[str, ...]:
    if node.level == 0:
        base = node.module or ""
    else:
        package = list(path.relative_to(root).parts[:-1])
        base = ".".join(
            [
                *package[: len(package) - node.level + 1],
                *((node.module or "").split(".") if node.module else []),
            ]
        )
    return tuple(
        [base, *(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")]
    )


def _closure(
    root: Path, entry: Path, forbidden: tuple[str, ...]
) -> tuple[dict[str, str], ...]:
    root = root.resolve(strict=True)
    pending = [entry.resolve(strict=True)]
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        path.relative_to(root)
        visited.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "eval", "exec"}
            ):
                raise ValueError("Luther oracle closure contains dynamic execution")
            names = (
                tuple(alias.name for alias in node.names)
                if isinstance(node, ast.Import)
                else _imports(path, root, node)
                if isinstance(node, ast.ImportFrom)
                else ()
            )
            for name in names:
                if any(
                    name == item or name.startswith(item + ".") for item in forbidden
                ):
                    raise ValueError(
                        f"Luther oracle closure contains forbidden import {name}"
                    )
                dependency = _module_path(root, name)
                if dependency is not None and dependency not in visited:
                    pending.append(dependency)
    return tuple(
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in sorted(visited, key=lambda item: item.relative_to(root).as_posix())
    )


def _closure_digest(root: Path, entry: Path, forbidden: tuple[str, ...]) -> str:
    return _sha(_canonical(_closure(root, entry, forbidden)))


def _family() -> list[dict[str, object]]:
    values = (
        ("luther-bondage-of-the-will", 1, "included-lib-075"),
        ("luther-commentary-on-galatians", 1, "excluded-lib-076"),
        ("strong-systematic-theology-vol-1", 1, "excluded-lib-076"),
        ("strong-systematic-theology-vol-2", 1, "excluded-lib-076"),
        ("strong-systematic-theology-vol-3", 1, "excluded-lib-076"),
        ("dabney-systematic-theology", 1, "excluded-lib-015"),
        ("shedd-dogmatic-theology-vol-1", 1, "excluded-lib-015"),
        ("shedd-dogmatic-theology-vol-2", 1, "excluded-lib-015"),
        ("shedd-dogmatic-theology-vol-3", 1, "excluded-lib-015"),
        ("miley-systematic-theology-vol-1", 1, "excluded-lib-015"),
        ("miley-systematic-theology-vol-2", 1, "excluded-lib-015"),
        ("aa-hodge-outlines", 1, "excluded-lib-005"),
        ("hooker-ecclesiastical-polity", 3, "excluded-lib-015"),
    )
    return [
        {"work_id": work, "members": members, "disposition": disposition}
        for work, members, disposition in values
    ]


def _unresolved() -> bytes:
    records = (
        {
            "id": "luther-bondage-edition-identity",
            "kind": "edition-identity",
            "status": "unresolved",
            "detail": "The retained transcription and local config identify Henry Cole's 1823 translation, but no independently retained scan establishes textual or edition identity.",
        },
        {
            "id": "luther-bondage-transcription-rights",
            "kind": "rights",
            "status": "unresolved",
            "detail": "The retained Covenanter transcription contains no copyright, license, permission, required-credit, or link-back statement; underlying-work age does not establish transcription rights.",
        },
        {
            "id": "luther-bondage-human-acceptance",
            "kind": "acceptance",
            "status": "required",
            "detail": "Human textual, identity, attribution, and rights review has not occurred.",
        },
        {
            "id": "luther-bondage-publication",
            "kind": "publication",
            "status": "not_ready",
            "detail": "This technical reconstruction does not authorize publication.",
        },
    )
    return b"".join(_canonical(record) for record in records)


def _canonical_path_spelling(value: str | Path) -> Path:
    """Return an absolute path after independently normalizing Windows namespaces."""
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ValueError("Luther candidate path has an invalid spelling")
    if os.name != "nt":
        return Path(os.path.abspath(raw))

    spelling = raw.replace("/", "\\")
    lowered = spelling.lower()
    if lowered.startswith(("\\\\.\\", "\\??\\", "\\\\??\\")):
        raise ValueError("Luther candidate path uses an unsupported device path")
    if lowered.startswith("\\\\?\\"):
        tail = spelling[4:]
        if tail.lower().startswith("unc\\"):
            unc_tail = tail[4:]
            parts = unc_tail.split("\\")
            if len(parts) < 2 or not parts[0] or not parts[1]:
                raise ValueError(
                    "Luther candidate path has a malformed extended UNC path"
                )
            spelling = "\\\\" + unc_tail
        elif re.match(r"^[A-Za-z]:\\", tail):
            spelling = tail
        else:
            raise ValueError("Luther candidate path uses an unsupported extended path")
    elif lowered.startswith(("\\\\?", "\\\\.")):
        raise ValueError("Luther candidate path has a malformed device path")

    if spelling.startswith("\\\\"):
        parts = spelling[2:].split("\\")
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise ValueError("Luther candidate path has a malformed UNC path")
        local_names = {
            "localhost",
            "127.0.0.1",
            "::1",
            "[::1]",
            "0:0:0:0:0:0:0:1",
            "[0:0:0:0:0:0:0:1]",
        }
        for name in (os.environ.get("COMPUTERNAME"), platform.node()):
            if name:
                local_names.add(name.rstrip(".").casefold())
        server = parts[0].rstrip(".").casefold()
        share = parts[1]
        if server in local_names and re.fullmatch(r"[A-Za-z]\$", share):
            suffix = "\\".join(parts[2:])
            spelling = f"{share[0].upper()}:\\{suffix}"

    drive_absolute = re.match(r"^[A-Za-z]:\\", spelling)
    if re.match(r"^[A-Za-z]:", spelling) and drive_absolute is None:
        raise ValueError("Luther candidate path uses a drive-relative spelling")
    allowed_colons = 1 if drive_absolute is not None else 0
    if spelling.count(":") != allowed_colons:
        raise ValueError("Luther candidate path uses ADS or an extra colon")
    try:
        return Path(os.path.abspath(spelling))
    except (OSError, ValueError) as exc:
        raise ValueError("Luther candidate path is invalid") from exc


def _is_within(path: Path, root: Path) -> bool:
    try:
        common = os.path.commonpath((str(path), str(root)))
        return os.path.normcase(common) == os.path.normcase(str(root))
    except ValueError:
        return False


def _protected_output_roots(repository_root: Path) -> tuple[Path, ...]:
    topology = json.loads((repository_root / ".ocd-storage.json").read_bytes())
    library_value = topology.get("library_root")
    if not isinstance(library_value, str) or not Path(library_value).is_absolute():
        raise ValueError("Luther oracle storage topology has no absolute library_root")
    library_root = Path(library_value).resolve(strict=True)
    repository_root = repository_root.resolve(strict=True)
    worktrees_root = (Path.home() / ".codex" / "worktrees").resolve(strict=False)
    return (
        (repository_root, worktrees_root)
        + tuple(
            (repository_root / name).resolve(strict=False)
            for name in (
                "raw",
                "data",
                "ir",
                "reports",
                "exports",
                "acceptance",
                "publication",
            )
        )
        + tuple(
            (library_root / name).resolve(strict=True)
            for name in ("raw", "reports", "exports")
        )
    )


def guard_candidate_path(repository_root: Path, candidate_path: str | Path) -> Path:
    """Validate a candidate location without writing or requiring it to exist."""
    requested = _canonical_path_spelling(candidate_path)
    resolved = _canonical_path_spelling(requested.resolve(strict=False))
    for root in _protected_output_roots(repository_root):
        protected = _canonical_path_spelling(root)
        if _is_within(requested, protected) or _is_within(resolved, protected):
            raise ValueError("Luther candidate path is inside protected storage")
    return requested


def _expected_candidate_manifest(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    names = (
        "README.source.md",
        "content.tei.xml",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    )
    members = []
    for name in names:
        content = candidate.member_bytes(name)
        members.append({"bytes": len(content), "name": name, "sha256": _sha(content)})
    return {
        "contract": "ocd-candidate-package-v1",
        "converter": source_manifest.record["converter"],
        "members": members,
        "package_schema": source_manifest.record["package_schema"],
        "source_id": source_manifest.record["source_id"],
        "source_manifest": {
            "path": source_manifest.path.relative_to(
                source_manifest.repository_root
            ).as_posix(),
            "sha256": source_manifest.sha256,
        },
        "status": "nonaccepted",
    }


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    guard_candidate_path(root, candidate.path)
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    _strict(profile_bytes, "Luther profile")
    policy = _strict(policy_bytes, "Luther policy")
    manifest_record = _strict(
        candidate.member_bytes("manifest.json"), "Luther candidate manifest"
    )
    if manifest_record != _expected_candidate_manifest(source_manifest, candidate):
        raise ValueError("Luther candidate authority binding mutation")
    source = source_manifest.authority_path("retained-source").read_bytes()
    authority = _authority(source_manifest, "retained-source")
    if (len(source), _sha(source), authority.get("sha256")) != (
        676071,
        SOURCE_SHA,
        SOURCE_SHA,
    ):
        raise ValueError("Luther oracle exact source drifted")
    rows = _scan(source)
    pages = _page_model(rows)
    if len(rows) != 1809 or any(row["terminator"] != "CRLF" for row in rows):
        raise ValueError("Luther oracle physical line census drifted")
    expected_tei = _expected_tei(rows, pages)
    actual_tei = candidate.member_bytes("content.tei.xml")
    if actual_tei != expected_tei:
        raise ValueError("Luther complete TEI bytes differ from independent projection")
    document = etree.fromstring(actual_tei)
    schema = compiled_schema()
    if not schema.validate(etree.ElementTree(document)):
        raise ValueError(
            f"Luther direct TEI P5 validation failed: {schema.error_log.last_error}"
        )
    line_nodes = document.xpath("//tei:div[@type='source-page']/tei:ab", namespaces=NS)
    if len(line_nodes) != len(rows):
        raise ValueError("Luther TEI physical line cardinality drifted")
    for row, node in zip(rows, line_nodes, strict=True):
        number = int(row["line"])
        if (node.get("n"), node.get(XML_ID), node.get("type"), node.text or "") != (
            str(number),
            f"luther-line-{number:04d}",
            _kind(str(row["text"])),
            str(row["text"]),
        ):
            raise ValueError(
                "Luther TEI line omission, reorder, invention, or metadata drift"
            )
    expected_accountability = {
        "contract": "ocd-luther-bondage-source-accountability-v1",
        "work_id": WORK_ID,
        "source_member": {key: authority[key] for key in ("path", "bytes", "sha256")},
        "physical_line_count": len(rows),
        "represented_line_count": len(rows),
        "evidence_only_line_count": 0,
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "pages": [
            {
                key: page[key]
                for key in ("ordinal", "slug", "url", "title", "line_start", "line_end")
            }
            for page in pages
        ],
        "lines": [
            {
                **row,
                "disposition": "represented",
                "reason": "exact retained physical line",
                "tei_selector": f"#luther-line-{int(row['line']):04d}",
            }
            for row in rows
        ],
    }
    if candidate.member_bytes("source-accountability.json") != _canonical(
        expected_accountability
    ):
        raise ValueError("Luther source accountability differs from retained bytes")
    producer_closure = _closure_digest(
        root,
        root / "build/tei/luther_bondage_covenanter_reconstruction.py",
        tuple(str(item) for item in policy["producer_forbidden_import_prefixes"]),
    )
    if producer_closure != source_manifest.record.get("producer_import_closure_sha256"):
        raise ValueError("Luther producer recursive closure drifted")
    config = json.loads(
        source_manifest.authority_path("local-source-config").read_bytes()
    )
    expected_provenance = {
        "contract": "ocd-luther-bondage-provenance-v1",
        "status": "nonaccepted",
        "work_id": WORK_ID,
        "source_manifest_sha256": source_manifest.sha256,
        "source_config": config,
        "source_page_urls": [page["url"] for page in pages],
        "family_census": _family(),
        "family_physical_member_count": 15,
        "family_overlap_count": 0,
        "producer_import_closure_sha256": producer_closure,
        "rights_status": "unresolved-no-retained-transcription-license",
        "publication_status": "not_ready",
    }
    if candidate.member_bytes("provenance.json") != _canonical(expected_provenance):
        raise ValueError(
            "Luther provenance, family exclusion, rights, or identity drifted"
        )
    if candidate.member_bytes("unresolved.jsonl") != _unresolved():
        raise ValueError("Luther unresolved evidence drifted")
    if (
        candidate.member_bytes("README.source.md")
        != source_manifest.authority_path("attribution-readme").read_bytes()
    ):
        raise ValueError("Luther attribution README drifted")
    forbidden = tuple(str(item) for item in policy["forbidden_import_prefixes"])
    closure_sha = _closure_digest(root, Path(__file__), forbidden)
    if closure_sha != source_manifest.record["validator"]["import_closure_sha256"]:
        raise ValueError("Luther oracle recursive import closure drifted")
    for name in ("ocd_kernel.reconstruction.contract", "ocd_kernel.tei.validate"):
        module_path = Path(str(sys.modules[name].__file__)).resolve(strict=True)
        module_path.relative_to(root)
        if "site-packages" in module_path.parts or "__editable__" in module_path.name:
            raise ValueError("Luther runtime dependency is shadowed")
    implementation_sha = _sha(Path(__file__).read_bytes())
    result = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": implementation_sha,
        "import_closure_sha256": closure_sha,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": str(
            source_manifest.record["package_schema"]["sha256"]
        ),
        "source_sha256": SOURCE_SHA,
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
