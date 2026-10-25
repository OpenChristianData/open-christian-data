"""Independent retained-source oracle for the LIB-067 Andrewes candidate."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-lib067-andrewes-independent-source-oracle"
ORACLE_VERSION = "1"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_SOURCE_BYTES = 168_055
_SOURCE_SHA256 = "366ebbd4dc4ea9420099d7335beb73a47ff0f331803d8e3d7fb1c4ad81e6ea47"
_SOURCE_PATH = "raw/ccel/andrewes-private-devotions.txt"
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


def _strict(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _source_lines(source: bytes) -> list[str]:
    if len(source) != _SOURCE_BYTES or _sha(source) != _SOURCE_SHA256:
        raise ValueError("Andrewes retained source bytes drifted")
    if b"\r" in source or not source.endswith(b"\n"):
        raise ValueError("Andrewes retained source newline contract drifted")
    try:
        lines = source.decode("utf-8", errors="strict").split("\n")
    except UnicodeDecodeError as exc:
        raise ValueError("Andrewes retained source is not strict UTF-8") from exc
    if len(lines) != 4_883 or sum(line == "" for line in lines) != 469:
        raise ValueError("Andrewes retained source line census drifted")
    return lines


def _member_census(source: bytes) -> list[dict[str, object]]:
    return [
        {
            "bytes": len(source),
            "decision": "include",
            "path": _SOURCE_PATH,
            "reason": "The sole frozen LIB-067 retained primary-source member.",
            "sha256": _sha(source),
        }
    ]


def _unresolved_records() -> list[dict[str, str]]:
    return [
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
    ]


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
            raise ValueError("Andrewes oracle import closure escapes repository")
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
            raise ValueError(
                "Andrewes oracle import closure escaped repository"
            ) from exc
        seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "eval", "exec"}
            ):
                raise ValueError("Andrewes oracle closure contains dynamic execution")
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


def _verify_closures(
    source_manifest: SourceManifest,
    converter: Mapping[str, object],
    validator: Mapping[str, object],
) -> tuple[str, str]:
    producer_path = source_manifest.repository_root / str(
        converter.get("implementation_path")
    )
    producer_closure = _closure_digest(source_manifest.repository_root, producer_path)
    if producer_closure != source_manifest.record.get("producer_import_closure_sha256"):
        raise ValueError("Andrewes producer import closure drifted")
    oracle_path = source_manifest.repository_root / str(
        validator.get("implementation_path")
    )
    oracle_closure = _closure_digest(source_manifest.repository_root, oracle_path)
    if oracle_closure != validator.get("import_closure_sha256"):
        raise ValueError("Andrewes oracle import closure drifted")
    return producer_closure, oracle_closure


def _tag(name: str) -> str:
    return f"{{{_TEI}}}{name}"


def _children(node: etree._Element, names: list[str], label: str) -> None:
    if [child.tag for child in node] != [_tag(name) for name in names]:
        raise ValueError(f"Andrewes {label} child order drifted")


def _leaf(
    node: etree._Element,
    name: str,
    text: str,
    attributes: Mapping[str, str] | None = None,
) -> None:
    if (
        node.tag != _tag(name)
        or dict(node.attrib) != dict(attributes or {})
        or (node.text or "") != text
        or len(node) != 0
        or (node.tail or "") != ""
    ):
        raise ValueError(f"Andrewes {name} element drifted")


def _verify_tei(
    candidate: CandidatePackage, lines: list[str], identity: Mapping[str, object]
) -> None:
    content = candidate.member_bytes("content.tei.xml")
    try:
        root = etree.fromstring(content)
    except etree.XMLSyntaxError as exc:
        raise ValueError("Andrewes TEI is not well-formed") from exc
    if (
        root.tag != _tag("TEI")
        or dict(root.attrib) != {_XML_ID: "andrewes-private-devotions-candidate"}
        or (root.text or "") != ""
        or (root.tail or "") != ""
    ):
        raise ValueError("Andrewes TEI root drifted")
    _children(root, ["teiHeader", "text"], "TEI")
    header, text = root
    if dict(header.attrib) or (header.text or "") != "" or (header.tail or "") != "":
        raise ValueError("Andrewes TEI header drifted")
    _children(header, ["fileDesc", "encodingDesc", "revisionDesc"], "header")
    file_desc, encoding, revision = header
    _children(file_desc, ["titleStmt", "publicationStmt", "sourceDesc"], "fileDesc")
    title_stmt, publication, source_desc = file_desc
    _children(title_stmt, ["title", "author"], "titleStmt")
    _leaf(title_stmt[0], "title", str(identity["work_title"]))
    _leaf(title_stmt[1], "author", str(identity["creator_statement"]))
    _children(publication, ["publisher", "availability"], "publicationStmt")
    _leaf(publication[0], "publisher", "Open Christian Data")
    availability = publication[1]
    if (
        dict(availability.attrib) != {"status": "restricted"}
        or (availability.text or "") != ""
        or (availability.tail or "") != ""
    ):
        raise ValueError("Andrewes availability drifted")
    _children(availability, ["p"], "availability")
    _leaf(availability[0], "p", "Nonaccepted candidate; publication is not authorized.")
    _children(source_desc, ["bibl"], "sourceDesc")
    bibl = source_desc[0]
    _children(
        bibl,
        ["title", "author", "date", "publisher", "date", "idno"],
        "source bibliography",
    )
    _leaf(bibl[0], "title", str(identity["source_title"]))
    _leaf(bibl[1], "author", str(identity["creator_statement"]))
    _leaf(bibl[2], "date", "1840", {"type": "first-publication"})
    _leaf(bibl[3], "publisher", "S.P.C.K.")
    _leaf(bibl[4], "date", "1920", {"type": "retained-publication"})
    _leaf(bibl[5], "idno", _SOURCE_SHA256, {"type": "sha256"})
    _children(encoding, ["p"], "encodingDesc")
    _leaf(
        encoding[0],
        "p",
        "Every LF-delimited retained source line is represented once, in order, without normalization.",
    )
    if (
        dict(revision.attrib) != {"status": "candidate"}
        or (revision.text or "") != ""
        or (revision.tail or "") != ""
    ):
        raise ValueError("Andrewes revision description drifted")
    _children(revision, ["change"], "revisionDesc")
    _leaf(
        revision[0],
        "change",
        "Generated as a nonaccepted source-bound candidate.",
        {"when": "2026-08-31"},
    )
    if dict(text.attrib) or (text.text or "") != "" or (text.tail or "") != "":
        raise ValueError("Andrewes text wrapper drifted")
    _children(text, ["body"], "text")
    body = text[0]
    _children(body, ["div"], "body")
    source_div = body[0]
    if (
        dict(source_div.attrib)
        != {
            "type": "retained-source",
            _XML_ID: "andrewes-private-devotions-retained-source",
        }
        or (source_div.text or "") != ""
        or (source_div.tail or "") != ""
    ):
        raise ValueError("Andrewes retained-source scope drifted")
    candidate_lines = list(source_div)
    if len(candidate_lines) != len(lines):
        raise ValueError("Andrewes line omission, duplication, or invention")
    for number, (node, expected) in enumerate(
        zip(candidate_lines, lines, strict=True), 1
    ):
        if (
            node.tag != _tag("ab")
            or dict(node.attrib) != {"type": "source-line", "n": str(number)}
            or len(node) != 0
            or (node.text or "") != expected
            or (node.tail or "") != ""
        ):
            raise ValueError(
                f"Andrewes source line {number} order, identity, or text drifted"
            )


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    if (
        source_manifest.record.get("ticket_id") != "LIB-067"
        or source_manifest.record.get("work_id") != "andrewes-private-devotions"
        or source_manifest.record.get("source_id")
        != "ccel-andrewes-private-devotions-retained"
    ):
        raise ValueError("Andrewes source identity drifted")
    converter = source_manifest.record.get("converter")
    validator = source_manifest.record.get("validator")
    if not isinstance(converter, Mapping) or not isinstance(validator, Mapping):
        raise ValueError("Andrewes callable bindings are invalid")
    manifest_path = source_manifest.path.relative_to(
        source_manifest.repository_root
    ).as_posix()
    if (
        candidate.manifest.get("status") != "nonaccepted"
        or candidate.manifest.get("source_id") != source_manifest.record["source_id"]
        or candidate.manifest.get("source_manifest")
        != {"path": manifest_path, "sha256": source_manifest.sha256}
        or candidate.manifest.get("converter") != dict(converter)
        or candidate.manifest.get("package_schema")
        != dict(source_manifest.record["package_schema"])
    ):
        raise ValueError("Andrewes candidate manifest binding drifted")
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict(profile_bytes, "Andrewes profile")
    policy = _strict(policy_bytes, "Andrewes policy")
    if profile.get("profile_id") != "lib067-andrewes-retained-ccel-text-v1":
        raise ValueError("Andrewes profile identity drifted")
    _verify_policy(policy)
    identity = profile.get("identity")
    if not isinstance(identity, dict):
        raise ValueError("Andrewes identity profile is invalid")
    source = source_manifest.authority_path("retained-text").read_bytes()
    lines = _source_lines(source)
    census = _member_census(source)
    expected_accountability = {
        "contract": "ocd-lib067-andrewes-source-accountability-v1",
        "profile_id": profile["profile_id"],
        "work_id": "andrewes-private-devotions",
        "source_id": source_manifest.record["source_id"],
        "member_census": census,
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
    accountability_bytes = candidate.member_bytes("source-accountability.json")
    if _strict(
        accountability_bytes, "Andrewes accountability"
    ) != expected_accountability or accountability_bytes != _canonical(
        expected_accountability
    ):
        raise ValueError("Andrewes source accountability drifted")
    schema = _strict(
        source_manifest.authority_path("source-accountability-schema").read_bytes(),
        "Andrewes accountability schema",
    )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(expected_accountability), key=str
    )
    if errors:
        raise ValueError(f"Andrewes accountability schema failure: {errors[0].message}")
    _verify_tei(candidate, lines, identity)
    xsd = etree.XMLSchema(
        etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))
    )
    if not xsd.validate(etree.fromstring(candidate.member_bytes("content.tei.xml"))):
        raise ValueError(f"Andrewes TEI P5 schema failure: {xsd.error_log}")
    authorities = {
        str(item["name"]): {
            key: item[key] for key in ("path", "bytes", "sha256", "role")
        }
        for item in source_manifest.record["authorities"]
    }
    expected_provenance = {
        "contract": "ocd-lib067-andrewes-candidate-provenance-v1",
        "status": "nonaccepted",
        "ticket_id": "LIB-067",
        "work_id": "andrewes-private-devotions",
        "source_id": source_manifest.record["source_id"],
        "source_manifest_sha256": source_manifest.sha256,
        "identity": profile["identity"],
        "rights": profile["rights"],
        "source_member_census": census,
        "candidate_boundary": {
            "technical_validation_status": "candidate-pending-validation",
            "human_acceptance_status": "unresolved",
            "publication_status": "not-authorized",
            "canonical_data_or_ir_written": False,
        },
        "authorities": authorities,
    }
    if (
        _strict(candidate.member_bytes("provenance.json"), "Andrewes provenance")
        != expected_provenance
    ):
        raise ValueError("Andrewes provenance or metadata drifted")
    unresolved = [
        _strict(line, "Andrewes unresolved record")
        for line in candidate.member_bytes("unresolved.jsonl").splitlines()
        if line.strip()
    ]
    if unresolved != _unresolved_records():
        raise ValueError("Andrewes unresolved scope drifted")
    if (
        candidate.member_bytes("README.source.md")
        != source_manifest.authority_path("source-attribution-readme").read_bytes()
    ):
        raise ValueError("Andrewes source attribution drifted")
    _, closure = _verify_closures(source_manifest, converter, validator)
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": closure,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": _sha(source),
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
