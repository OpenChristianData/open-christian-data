"""Direct retained Covenanter transcription to a nonaccepted TEI candidate."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
)


CONVERTER_ID = "ocd-luther-bondage-covenanter-lines-to-tei"
CONVERTER_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
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
    value = json.loads(content)
    if not isinstance(value, dict) or _canonical(value) != content:
        raise ValueError(f"{label} is not canonical JSON")
    return value


def _authority(manifest: SourceManifest, name: str) -> Mapping[str, object]:
    matches = [
        item for item in manifest.record["authorities"] if item.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Luther authority {name} cardinality mismatch")
    return matches[0]


def _records(content: bytes) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    offset = 0
    for number, record in enumerate(content.splitlines(keepends=True), 1):
        if record.endswith(b"\r\n"):
            payload, terminator = record[:-2], "CRLF"
        elif record.endswith(b"\n"):
            payload, terminator = record[:-1], "LF"
        else:
            payload, terminator = record, "none"
        text = payload.decode("utf-8")
        rows.append(
            {
                "line": number,
                "byte_start": offset,
                "byte_end": offset + len(record),
                "terminator": terminator,
                "text": text,
                "record_sha256": _sha(record),
            }
        )
        offset += len(record)
    if offset != len(content):
        raise ValueError("Luther source byte accounting is not contiguous")
    return rows


def _pages(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    starts = [
        index for index, row in enumerate(rows) if PAGE_RE.fullmatch(str(row["text"]))
    ]
    if len(starts) != 13 or starts[0] != 0:
        raise ValueError("Luther retained page-marker census drifted")
    pages: list[dict[str, object]] = []
    for ordinal, start in enumerate(starts, 1):
        end = starts[ordinal] if ordinal < len(starts) else len(rows)
        members = rows[start:end]
        marker = PAGE_RE.fullmatch(str(members[0]["text"]))
        url = URL_RE.fullmatch(str(members[1]["text"]))
        title = TITLE_RE.fullmatch(str(members[2]["text"]))
        if marker is None or url is None or title is None:
            raise ValueError("Luther retained page metadata adjacency drifted")
        pages.append(
            {
                "ordinal": ordinal,
                "slug": marker.group(1),
                "url": url.group(1),
                "title": title.group(1),
                "line_start": int(members[0]["line"]),
                "line_end": int(members[-1]["line"]),
                "lines": members,
            }
        )
    return pages


def _line_type(text: str) -> str:
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


def _build_tei(
    rows: list[dict[str, object]], pages: list[dict[str, object]], source_sha: str
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
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="sha256").text = source_sha
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
    text_node = etree.SubElement(root, f"{{{TEI}}}text")
    body = etree.SubElement(text_node, f"{{{TEI}}}body")
    represented = 0
    for page in pages:
        div = etree.SubElement(
            body,
            f"{{{TEI}}}div",
            type="source-page",
            n=str(page["ordinal"]),
            source=str(page["url"]),
        )
        div.set(XML_ID, f"luther-page-{page['ordinal']:02d}-{page['slug']}")
        head = etree.SubElement(div, f"{{{TEI}}}head", type="source-page-title")
        head.text = str(page["title"])
        for row in page["lines"]:
            line = int(row["line"])
            node = etree.SubElement(
                div,
                f"{{{TEI}}}ab",
                n=str(line),
                type=_line_type(str(row["text"])),
            )
            node.set(XML_ID, f"luther-line-{line:04d}")
            node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            node.text = str(row["text"]) or None
            represented += 1
    if represented != len(rows):
        raise ValueError("Luther TEI line representation is incomplete")
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
                        f"Luther producer closure contains forbidden import {name}"
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


def _family_census() -> list[dict[str, object]]:
    return [
        {
            "work_id": "luther-bondage-of-the-will",
            "members": 1,
            "disposition": "included-lib-075",
        },
        {
            "work_id": "luther-commentary-on-galatians",
            "members": 1,
            "disposition": "excluded-lib-076",
        },
        {
            "work_id": "strong-systematic-theology-vol-1",
            "members": 1,
            "disposition": "excluded-lib-076",
        },
        {
            "work_id": "strong-systematic-theology-vol-2",
            "members": 1,
            "disposition": "excluded-lib-076",
        },
        {
            "work_id": "strong-systematic-theology-vol-3",
            "members": 1,
            "disposition": "excluded-lib-076",
        },
        {
            "work_id": "dabney-systematic-theology",
            "members": 1,
            "disposition": "excluded-lib-015",
        },
        {
            "work_id": "shedd-dogmatic-theology-vol-1",
            "members": 1,
            "disposition": "excluded-lib-015",
        },
        {
            "work_id": "shedd-dogmatic-theology-vol-2",
            "members": 1,
            "disposition": "excluded-lib-015",
        },
        {
            "work_id": "shedd-dogmatic-theology-vol-3",
            "members": 1,
            "disposition": "excluded-lib-015",
        },
        {
            "work_id": "miley-systematic-theology-vol-1",
            "members": 1,
            "disposition": "excluded-lib-015",
        },
        {
            "work_id": "miley-systematic-theology-vol-2",
            "members": 1,
            "disposition": "excluded-lib-015",
        },
        {
            "work_id": "aa-hodge-outlines",
            "members": 1,
            "disposition": "excluded-lib-005",
        },
        {
            "work_id": "hooker-ecclesiastical-polity",
            "members": 3,
            "disposition": "excluded-lib-015",
        },
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
    """Return an absolute path after normalizing supported Windows namespaces."""
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ValueError("Luther candidate destination has an invalid path spelling")
    if os.name != "nt":
        return Path(os.path.abspath(raw))

    spelling = raw.replace("/", "\\")
    lowered = spelling.lower()
    if lowered.startswith(("\\\\.\\", "\\??\\", "\\\\??\\")):
        raise ValueError("Luther candidate destination uses an unsupported device path")
    if lowered.startswith("\\\\?\\"):
        tail = spelling[4:]
        if tail.lower().startswith("unc\\"):
            unc_tail = tail[4:]
            parts = unc_tail.split("\\")
            if len(parts) < 2 or not parts[0] or not parts[1]:
                raise ValueError(
                    "Luther candidate destination has a malformed extended UNC path"
                )
            spelling = "\\\\" + unc_tail
        elif re.match(r"^[A-Za-z]:\\", tail):
            spelling = tail
        else:
            raise ValueError(
                "Luther candidate destination uses an unsupported extended path"
            )
    elif lowered.startswith(("\\\\?", "\\\\.")):
        raise ValueError("Luther candidate destination has a malformed device path")

    if spelling.startswith("\\\\"):
        parts = spelling[2:].split("\\")
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise ValueError("Luther candidate destination has a malformed UNC path")
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
        raise ValueError("Luther candidate destination uses a drive-relative path")
    allowed_colons = 1 if drive_absolute is not None else 0
    if spelling.count(":") != allowed_colons:
        raise ValueError("Luther candidate destination uses ADS or an extra colon")
    try:
        return Path(os.path.abspath(spelling))
    except (OSError, ValueError) as exc:
        raise ValueError("Luther candidate destination path is invalid") from exc


def _is_within(path: Path, root: Path) -> bool:
    try:
        common = os.path.commonpath((str(path), str(root)))
        return os.path.normcase(common) == os.path.normcase(str(root))
    except ValueError:
        return False


def _protected_output_roots(repository_root: Path) -> tuple[Path, ...]:
    topology_path = repository_root / ".ocd-storage.json"
    topology = json.loads(topology_path.read_bytes())
    library_value = topology.get("library_root")
    if not isinstance(library_value, str) or not Path(library_value).is_absolute():
        raise ValueError("Luther storage topology has no absolute library_root")
    library_root = Path(library_value).resolve(strict=True)
    repository_root = repository_root.resolve(strict=True)
    worktrees_root = (Path.home() / ".codex" / "worktrees").resolve(strict=False)
    repository_roots = (repository_root, worktrees_root) + tuple(
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
    durable_roots = tuple(
        (library_root / name).resolve(strict=True)
        for name in ("raw", "reports", "exports")
    )
    return repository_roots + durable_roots


def guard_candidate_destination(
    source_manifest: SourceManifest, destination: str | Path
) -> Path:
    """Reject protected lexical and resolved destinations without probing writes."""
    requested = _canonical_path_spelling(destination)
    resolved = _canonical_path_spelling(requested.resolve(strict=False))
    for root in _protected_output_roots(source_manifest.repository_root):
        protected = _canonical_path_spelling(root)
        if _is_within(requested, protected) or _is_within(resolved, protected):
            raise ValueError("Luther candidate destination is inside protected storage")
    return requested


def reconstruct_candidate(
    source_manifest: SourceManifest, destination: str | Path
) -> CandidatePackage:
    """The guarded LIB-075 reconstruction route for caller-selected output."""
    return reconstruct(
        source_manifest,
        guard_candidate_destination(source_manifest, destination),
        _convert,
    )


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    root = source_manifest.repository_root
    profile = _strict(
        source_manifest.authority_path("reconstruction-profile").read_bytes(),
        "Luther profile",
    )
    policy = _strict(
        source_manifest.authority_path("validation-policy").read_bytes(),
        "Luther policy",
    )
    if (
        source_manifest.record.get("source_id")
        != "luther-bondage-of-the-will-covenanter-retained"
        or profile.get("work_id") != WORK_ID
    ):
        raise ValueError("Luther work/source identity mismatch")
    source = source_manifest.authority_path("retained-source").read_bytes()
    authority = _authority(source_manifest, "retained-source")
    if (len(source), _sha(source)) != (676071, SOURCE_SHA) or authority.get(
        "sha256"
    ) != SOURCE_SHA:
        raise ValueError("Luther exact retained source drifted")
    rows = _records(source)
    pages = _pages(rows)
    if len(rows) != 1809 or any(row["terminator"] != "CRLF" for row in rows):
        raise ValueError("Luther physical-line or terminator census drifted")
    producer_closure = _closure_digest(
        root,
        Path(__file__),
        tuple(str(item) for item in policy["producer_forbidden_import_prefixes"]),
    )
    if producer_closure != source_manifest.record.get("producer_import_closure_sha256"):
        raise ValueError("Luther producer recursive import closure drifted")
    tei = _build_tei(rows, pages, SOURCE_SHA)
    inventory = [
        {
            **row,
            "disposition": "represented",
            "reason": "exact retained physical line",
            "tei_selector": f"#luther-line-{int(row['line']):04d}",
        }
        for row in rows
    ]
    accountability = {
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
        "lines": inventory,
    }
    config = json.loads(
        source_manifest.authority_path("local-source-config").read_bytes()
    )
    provenance = {
        "contract": "ocd-luther-bondage-provenance-v1",
        "status": "nonaccepted",
        "work_id": WORK_ID,
        "source_manifest_sha256": source_manifest.sha256,
        "source_config": config,
        "source_page_urls": [page["url"] for page in pages],
        "family_census": _family_census(),
        "family_physical_member_count": 15,
        "family_overlap_count": 0,
        "producer_import_closure_sha256": producer_closure,
        "rights_status": "unresolved-no-retained-transcription-license",
        "publication_status": "not_ready",
    }
    return {
        "content.tei.xml": tei,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": _unresolved(),
        "README.source.md": source_manifest.authority_path(
            "attribution-readme"
        ).read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
