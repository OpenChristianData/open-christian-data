"""Deterministic retained CCEL text to TEI candidate route for LIB-067."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-lib067-andrewes-retained-text-to-tei"
CONVERTER_VERSION = "1"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_SOURCE_BYTES = 168_055
_SOURCE_SHA256 = "366ebbd4dc4ea9420099d7335beb73a47ff0f331803d8e3d7fb1c4ad81e6ea47"
_SOURCE_PATH = "raw/ccel/andrewes-private-devotions.txt"
_LINE_COUNT = 4_883
_EXPECTED_POLICY = (
    ("policy_id", "lib067-andrewes-retained-ccel-text-policy-v1"),
    ("oracle_id", "ocd-lib067-andrewes-independent-source-oracle"),
    ("schema", "lib067-andrewes.source-accountability.schema.json"),
    (
        "rules",
        [
            "exact retained source bytes and SHA-256",
            "exact one-member include census with no excluded retained members",
            "exact 4883-line sequence including blank and terminal empty lines",
            "direct TEI P5 XSD and source-accountability schema validation",
            "reject omission, duplication, reordering, invention, text, metadata, provenance, and scope drift",
            "fresh-process and different-CWD byte determinism",
        ],
    ),
    (
        "required_unresolved_ids",
        [
            "andrewes-identity-review",
            "andrewes-edition-witness-review",
            "andrewes-rights-review",
            "andrewes-editorial-review",
            "andrewes-textual-acceptance",
            "andrewes-publication-review",
        ],
    ),
    (
        "human_review",
        [
            "identity",
            "edition and witness",
            "rights",
            "editorial interpretation",
            "textual acceptance",
            "publication",
        ],
    ),
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict(path: Path, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _local_module(root: Path, module: str) -> Path | None:
    base = root.joinpath(*module.split("."))
    for path in (base.with_suffix(".py"), base / "__init__.py"):
        if path.is_file():
            return path.resolve(strict=True)
    return None


def _module_name(root: Path, path: Path) -> str:
    parts = list(path.resolve(strict=True).relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _import_names(root: Path, path: Path, node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if not isinstance(node, ast.ImportFrom):
        return ()
    if node.level:
        package = _module_name(root, path).split(".")
        if path.name != "__init__.py":
            package.pop()
        if node.level > len(package):
            raise ValueError("Andrewes import closure escapes repository")
        base = ".".join(package[: len(package) - node.level + 1])
        if node.module:
            base = f"{base}.{node.module}" if base else node.module
    else:
        base = node.module or ""
    if not base:
        return ()
    return (base, *(f"{base}.{alias.name}" for alias in node.names))


def _closure(root: Path, route: Path) -> tuple[dict[str, str], ...]:
    root = root.resolve(strict=True)
    pending = [route.resolve(strict=True)]
    seen: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("Andrewes import closure escaped repository") from exc
        seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "eval", "exec"}
            ):
                raise ValueError("Andrewes import closure contains dynamic execution")
            for name in _import_names(root, path, node):
                dependency = _local_module(root, name)
                if dependency is not None and dependency not in seen:
                    pending.append(dependency)
                parts = name.split(".")
                for index in range(1, len(parts)):
                    package = _local_module(root, ".".join(parts[:index]))
                    if package is not None and package not in seen:
                        pending.append(package)
    return tuple(
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha(path.read_bytes()),
        }
        for path in sorted(seen, key=lambda item: item.relative_to(root).as_posix())
    )


def _closure_digest(root: Path, route: Path) -> str:
    return _sha(_canonical(_closure(root, route)))


def _verify_policy(policy: dict[str, object]) -> None:
    if tuple(policy.items()) != _EXPECTED_POLICY:
        raise ValueError("Andrewes validation policy envelope drifted")


def _verify_closure(source_manifest: SourceManifest) -> str:
    converter = source_manifest.record.get("converter")
    if not isinstance(converter, Mapping):
        raise ValueError("Andrewes converter binding is invalid")
    route = source_manifest.repository_root / str(converter.get("implementation_path"))
    closure = _closure_digest(source_manifest.repository_root, route)
    if closure != source_manifest.record.get("producer_import_closure_sha256"):
        raise ValueError("Andrewes producer import closure drifted")
    return closure


def _source_lines(source: bytes) -> list[str]:
    if len(source) != _SOURCE_BYTES or _sha(source) != _SOURCE_SHA256:
        raise ValueError("Andrewes retained source bytes drifted")
    if b"\r" in source or not source.endswith(b"\n"):
        raise ValueError("Andrewes retained source newline contract drifted")
    try:
        lines = source.decode("utf-8", errors="strict").split("\n")
    except UnicodeDecodeError as exc:
        raise ValueError("Andrewes retained source is not strict UTF-8") from exc
    if len(lines) != _LINE_COUNT:
        raise ValueError("Andrewes retained source line census drifted")
    return lines


def _authority_bindings(
    source_manifest: SourceManifest,
) -> dict[str, dict[str, object]]:
    return {
        str(item["name"]): {
            key: item[key] for key in ("path", "bytes", "sha256", "role")
        }
        for item in source_manifest.record["authorities"]
    }


def _unresolved_records() -> tuple[dict[str, str], ...]:
    return (
        {
            "id": "andrewes-identity-review",
            "status": "unresolved",
            "kind": "identity",
            "detail": "Human review must confirm the bounded work and creator identity.",
        },
        {
            "id": "andrewes-edition-witness-review",
            "status": "unresolved",
            "kind": "edition-witness",
            "detail": "Human review must confirm the retained CCEL transcription's edition and witness claims.",
        },
        {
            "id": "andrewes-rights-review",
            "status": "unresolved",
            "kind": "rights",
            "detail": "Human rights review is required before any publication decision.",
        },
        {
            "id": "andrewes-editorial-review",
            "status": "unresolved",
            "kind": "editorial",
            "detail": "Line-addressed transcription makes no human editorial disposition of headings, references, or CCEL apparatus.",
        },
        {
            "id": "andrewes-textual-acceptance",
            "status": "unresolved",
            "kind": "acceptance",
            "detail": "Technical validation is not human textual acceptance.",
        },
        {
            "id": "andrewes-publication-review",
            "status": "unresolved",
            "kind": "publication",
            "detail": "This candidate is not publication-ready or publication-authorized.",
        },
    )


def _tei(profile: Mapping[str, object], lines: list[str]) -> bytes:
    identity = profile["identity"]
    assert isinstance(identity, dict)
    root = etree.Element(f"{{{_TEI}}}TEI", nsmap={None: _TEI})
    root.set(_XML_ID, "andrewes-private-devotions-candidate")
    header = etree.SubElement(root, f"{{{_TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{_TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{_TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{_TEI}}}title").text = str(identity["work_title"])
    etree.SubElement(title_stmt, f"{{{_TEI}}}author").text = str(
        identity["creator_statement"]
    )
    publication = etree.SubElement(file_desc, f"{{{_TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{_TEI}}}publisher").text = "Open Christian Data"
    availability = etree.SubElement(
        publication, f"{{{_TEI}}}availability", status="restricted"
    )
    etree.SubElement(
        availability, f"{{{_TEI}}}p"
    ).text = "Nonaccepted candidate; publication is not authorized."
    source_desc = etree.SubElement(file_desc, f"{{{_TEI}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{_TEI}}}bibl")
    etree.SubElement(bibl, f"{{{_TEI}}}title").text = str(identity["source_title"])
    etree.SubElement(bibl, f"{{{_TEI}}}author").text = str(
        identity["creator_statement"]
    )
    etree.SubElement(bibl, f"{{{_TEI}}}date", type="first-publication").text = "1840"
    etree.SubElement(bibl, f"{{{_TEI}}}publisher").text = "S.P.C.K."
    etree.SubElement(bibl, f"{{{_TEI}}}date", type="retained-publication").text = "1920"
    etree.SubElement(bibl, f"{{{_TEI}}}idno", type="sha256").text = _SOURCE_SHA256
    encoding = etree.SubElement(header, f"{{{_TEI}}}encodingDesc")
    etree.SubElement(
        encoding, f"{{{_TEI}}}p"
    ).text = "Every LF-delimited retained source line is represented once, in order, without normalization."
    revision = etree.SubElement(header, f"{{{_TEI}}}revisionDesc", status="candidate")
    etree.SubElement(
        revision, f"{{{_TEI}}}change", when="2026-08-31"
    ).text = "Generated as a nonaccepted source-bound candidate."
    text = etree.SubElement(root, f"{{{_TEI}}}text")
    body = etree.SubElement(text, f"{{{_TEI}}}body")
    source_div = etree.SubElement(body, f"{{{_TEI}}}div", type="retained-source")
    source_div.set(_XML_ID, "andrewes-private-devotions-retained-source")
    for number, line in enumerate(lines, 1):
        node = etree.SubElement(
            source_div, f"{{{_TEI}}}ab", type="source-line", n=str(number)
        )
        node.text = line
    return etree.tostring(
        root, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    _verify_closure(source_manifest)
    profile = _strict(
        source_manifest.authority_path("reconstruction-profile"), "Andrewes profile"
    )
    policy = _strict(
        source_manifest.authority_path("validation-policy"), "Andrewes policy"
    )
    if profile.get("profile_id") != "lib067-andrewes-retained-ccel-text-v1":
        raise ValueError("Andrewes profile identity drifted")
    _verify_policy(policy)
    source = source_manifest.authority_path("retained-text").read_bytes()
    lines = _source_lines(source)
    member_census = [
        {
            "bytes": len(source),
            "decision": "include",
            "path": _SOURCE_PATH,
            "reason": "The sole frozen LIB-067 retained primary-source member.",
            "sha256": _sha(source),
        }
    ]
    accountability = {
        "contract": "ocd-lib067-andrewes-source-accountability-v1",
        "profile_id": profile["profile_id"],
        "work_id": "andrewes-private-devotions",
        "source_id": source_manifest.record["source_id"],
        "member_census": member_census,
        "excluded_member_count": 0,
        "source_bytes": len(source),
        "source_sha256": _sha(source),
        "encoding": "UTF-8 (retained bytes are ASCII subset)",
        "newline": "LF with terminal LF",
        "source_line_count": len(lines),
        "blank_line_count": sum(line == "" for line in lines),
        "source_line_sequence_sha256": _sha(_canonical(lines)),
        "represented_line_count": len(lines),
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "invented_line_count": 0,
        "reordered_line_count": 0,
        "unresolved_count": len(_unresolved_records()),
    }
    provenance = {
        "contract": "ocd-lib067-andrewes-candidate-provenance-v1",
        "status": "nonaccepted",
        "ticket_id": "LIB-067",
        "work_id": "andrewes-private-devotions",
        "source_id": source_manifest.record["source_id"],
        "source_manifest_sha256": source_manifest.sha256,
        "identity": profile["identity"],
        "rights": profile["rights"],
        "source_member_census": member_census,
        "candidate_boundary": {
            "technical_validation_status": "candidate-pending-validation",
            "human_acceptance_status": "unresolved",
            "publication_status": "not-authorized",
            "canonical_data_or_ir_written": False,
        },
        "authorities": _authority_bindings(source_manifest),
    }
    return {
        "content.tei.xml": _tei(profile, lines),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(
            _canonical(item) for item in _unresolved_records()
        ),
        "README.source.md": source_manifest.authority_path(
            "source-attribution-readme"
        ).read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
