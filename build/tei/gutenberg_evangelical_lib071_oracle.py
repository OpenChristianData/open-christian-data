"""Independent retained-byte oracle for LIB-071."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-lib071-retained-text-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
MEMBERS = {
    "manifest.json",
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
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


def _physical_lines(content: bytes) -> list[tuple[str, str]]:
    content.decode("utf-8")
    result: list[tuple[str, str]] = []
    for raw in content.splitlines(keepends=True):
        if raw.endswith(b"\r\n"):
            result.append((raw[:-2].decode("utf-8"), "crlf"))
        elif raw.endswith(b"\n"):
            result.append((raw[:-1].decode("utf-8"), "lf"))
        elif raw.endswith(b"\r"):
            result.append((raw[:-1].decode("utf-8"), "cr"))
        else:
            result.append((raw.decode("utf-8"), "none"))
    endings = {"crlf": b"\r\n", "lf": b"\n", "cr": b"\r", "none": b""}
    if b"".join(text.encode("utf-8") + endings[ending] for text, ending in result) != content:
        raise ValueError("LIB-071 independent source line reader is not lossless")
    return result


def _adjacent_inventory(
    root: Path,
    assigned: set[str],
    overrides: Mapping[str, object],
) -> list[dict[str, object]]:
    paths = sorted(
        [member for base in (root / "raw/gutenberg", root / "raw/ia") for member in base.iterdir() if member.is_file()],
        key=lambda item: item.as_posix(),
    )
    logical = {member.relative_to(root).as_posix() for member in paths}
    if any(
        not isinstance(path, str) or not isinstance(reason, str)
        for path, reason in overrides.items()
    ) or not set(overrides) <= logical - assigned:
        raise ValueError("LIB-071 adjacent inventory dispositions are invalid")
    records = []
    for member in paths:
        content = member.read_bytes()
        path = member.relative_to(root).as_posix()
        records.append(
            {
                "path": path,
                "bytes": len(content),
                "sha256": _sha(content),
                "disposition": (
                "included as one exact LIB-071 work witness"
                if path in assigned
                    else overrides.get(
                        path,
                        "excluded: adjacent retained member assigned outside LIB-071",
                    )
                ),
            }
        )
    return records


def _expected_tei(
    profile: Mapping[str, object], sources: Mapping[str, bytes]
) -> bytes:
    """Independently reconstruct the complete closed TEI tree."""
    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    root.set(XML_ID, "lib071-gutenberg-evangelical")
    header = etree.SubElement(root, f"{{{TEI_NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}title").text = (
        "LIB-071: ten retained Gutenberg and Internet Archive evangelical "
        "witnesses"
    )
    publication = etree.SubElement(file_desc, f"{{{TEI_NS}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI_NS}}}publisher").text = (
        "Open Christian Data"
    )
    availability = etree.SubElement(
        publication, f"{{{TEI_NS}}}availability", status="restricted"
    )
    etree.SubElement(availability, f"{{{TEI_NS}}}p").text = (
        "Nonaccepted reconstruction candidate; human acceptance and publication "
        "authorization are absent."
    )
    source_desc = etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    source_list = etree.SubElement(source_desc, f"{{{TEI_NS}}}listBibl")
    for work in profile["works"]:
        work_id = str(work["work_id"])
        bibl = etree.SubElement(
            source_list, f"{{{TEI_NS}}}bibl", type="retained-witness"
        )
        bibl.set(XML_ID, f"source-{work_id}")
        etree.SubElement(bibl, f"{{{TEI_NS}}}title").text = str(work["title"])
        etree.SubElement(bibl, f"{{{TEI_NS}}}author").text = str(work["author"])
        etree.SubElement(
            bibl, f"{{{TEI_NS}}}note", type="witness-description"
        ).text = str(work["witness_description"])
        etree.SubElement(
            bibl, f"{{{TEI_NS}}}ref", target=str(work["source_url"])
        ).text = str(work["source_path"])
    encoding = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
    project = etree.SubElement(encoding, f"{{{TEI_NS}}}projectDesc")
    etree.SubElement(project, f"{{{TEI_NS}}}p").text = (
        "Each retained physical source line is represented once, in order, as a "
        "source-line ab. Its exact line-ending class is recorded in subtype, "
        "enabling byte-for-byte UTF-8 reassembly."
    )
    text = etree.SubElement(root, f"{{{TEI_NS}}}text")
    group = etree.SubElement(text, f"{{{TEI_NS}}}group")
    for work in profile["works"]:
        work_id = str(work["work_id"])
        work_text = etree.SubElement(group, f"{{{TEI_NS}}}text")
        work_text.set(XML_ID, work_id)
        body = etree.SubElement(work_text, f"{{{TEI_NS}}}body")
        division = etree.SubElement(
            body,
            f"{{{TEI_NS}}}div",
            type="retained-text-witness",
            corresp=f"#source-{work_id}",
        )
        for ordinal, (line, ending) in enumerate(
            _physical_lines(sources[work_id]), 1
        ):
            node = etree.SubElement(
                division,
                f"{{{TEI_NS}}}ab",
                type="source-line",
                subtype=ending,
                n=str(ordinal),
            )
            node.set(XML_ID, f"{work_id}-line-{ordinal:05d}")
            node.text = line
    return etree.tostring(
        root, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )


def _verify_tei(
    candidate: CandidatePackage,
    profile: Mapping[str, object],
    sources: Mapping[str, bytes],
) -> None:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False)
    content = candidate.member_bytes("content.tei.xml")
    if not content.startswith(b"<?xml version='1.0' encoding='UTF-8'?>") or b"<!DOCTYPE" in content:
        raise ValueError("LIB-071 TEI document shell drift")
    if content != _expected_tei(profile, sources):
        raise ValueError("LIB-071 complete TEI tree or metadata drift")
    tree = etree.fromstring(content, parser).getroottree()
    root = tree.getroot()
    if root.tag != f"{{{TEI_NS}}}TEI" or root.get(XML_ID) != "lib071-gutenberg-evangelical":
        raise ValueError("LIB-071 TEI root drift")
    if any(isinstance(node, (etree._Comment, etree._ProcessingInstruction)) for node in root.iter()):
        raise ValueError("LIB-071 TEI contains invented comment or processing instruction")
    work_texts = tree.xpath("/tei:TEI/tei:text/tei:group/tei:text", namespaces={"tei": TEI_NS})
    works = profile["works"]
    if [node.get(XML_ID) for node in work_texts] != [work["work_id"] for work in works]:
        raise ValueError("LIB-071 TEI assigned-work order drift")
    for work, work_text in zip(works, work_texts, strict=True):
        work_id = str(work["work_id"])
        divisions = work_text.xpath("./tei:body/tei:div", namespaces={"tei": TEI_NS})
        if len(divisions) != 1 or divisions[0].get("type") != "retained-text-witness":
            raise ValueError(f"LIB-071 TEI work topology drift: {work_id}")
        nodes = divisions[0].xpath("./tei:ab", namespaces={"tei": TEI_NS})
        expected = _physical_lines(sources[work_id])
        if len(nodes) != len(expected):
            raise ValueError(f"LIB-071 line omission or duplication: {work_id}")
        reassembled: list[bytes] = []
        endings = {"crlf": b"\r\n", "lf": b"\n", "cr": b"\r", "none": b""}
        for ordinal, (node, (text, ending)) in enumerate(zip(nodes, expected, strict=True), 1):
            if (
                node.get("type") != "source-line"
                or node.get("subtype") != ending
                or node.get("n") != str(ordinal)
                or node.get(XML_ID) != f"{work_id}-line-{ordinal:05d}"
                or len(node) != 0
                or (node.text or "") != text
                or (node.tail or "") != ""
            ):
                raise ValueError(f"LIB-071 line representation drift: {work_id}:{ordinal}")
            reassembled.append(text.encode("utf-8") + endings[ending])
        if b"".join(reassembled) != sources[work_id]:
            raise ValueError(f"LIB-071 byte reassembly mismatch: {work_id}")
    try:
        compiled_schema().assertValid(tree)
    except etree.DocumentInvalid as exc:
        raise ValueError("LIB-071 candidate fails TEI P5 validation") from exc


def _verify_evidence(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    profile: Mapping[str, object],
    sources: Mapping[str, bytes],
) -> None:
    root = source_manifest.repository_root
    accountability = _strict_json(
        candidate.member_bytes("source-accountability.json"), "LIB-071 accountability"
    )
    schema = _strict_json(
        source_manifest.authority_path("source-accountability-schema").read_bytes(),
        "LIB-071 accountability schema",
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"LIB-071 accountability schema failure: {errors[0].message}")
    works = profile["works"]
    expected_paths = {str(work["source_path"]) for work in works}
    overrides = profile.get("adjacent_retained_member_dispositions")
    if not isinstance(overrides, Mapping):
        raise ValueError("LIB-071 adjacent inventory dispositions are invalid")
    expected_inventory = _adjacent_inventory(root, expected_paths, overrides)
    if [row["path"] for row in expected_inventory] != profile["adjacent_retained_member_paths"]:
        raise ValueError("LIB-071 profile does not account for exact adjacent inventory")
    if accountability.get("adjacent_retained_member_accounting") != expected_inventory:
        raise ValueError("LIB-071 adjacent retained-member evidence drift")
    expected_members = []
    expected_works = []
    for work in works:
        work_id = str(work["work_id"])
        content = sources[work_id]
        lines = _physical_lines(content)
        expected_members.append(
            {
                "work_id": work_id,
                "path": work["source_path"],
                "bytes": len(content),
                "sha256": _sha(content),
                "disposition": "included in full as the sole retained witness for this work",
            }
        )
        expected_works.append(
            {
                "work_id": work_id,
                "source_path": work["source_path"],
                "source_sha256": _sha(content),
                "line_count": len(lines),
                "character_count": sum(len(text) for text, _ in lines),
                "blank_line_count": sum(not text for text, _ in lines),
                "line_ending_counts": {
                    ending: sum(observed == ending for _, observed in lines)
                    for ending in ("crlf", "lf", "cr", "none")
                },
                "tei_selector_contract": f"#{work_id}-line-%05d",
                "omitted_line_count": 0,
                "duplicate_line_count": 0,
            }
        )
    if accountability.get("source_members") != expected_members or accountability.get("works") != expected_works:
        raise ValueError("LIB-071 source-member or line-accountability evidence drift")
    if (
        accountability.get("total_line_count") != sum(row["line_count"] for row in expected_works)
        or accountability.get("omitted_line_count") != 0
        or accountability.get("duplicate_line_count") != 0
        or accountability.get("candidate_status") != "nonaccepted"
        or accountability.get("publication_ready") is not False
    ):
        raise ValueError("LIB-071 accountability closure drift")
    provenance_bytes = candidate.member_bytes("provenance.json")
    provenance = _strict_json(provenance_bytes, "LIB-071 provenance")
    expected_provenance = {
        "contract": "ocd-lib071-provenance-v1",
        "source_manifest_sha256": source_manifest.sha256,
        "profile_id": profile["profile_id"],
        "text_authority": "the ten retained raw UTF-8 text members only",
        "diagnostic_non_authorities": [
            "build/parsers/gutenberg_evangelical.py",
            "canonical data JSON",
            "legacy TEI",
        ],
        "works": [
            {
                "work_id": work["work_id"],
                "title": work["title"],
                "author": work["author"],
                "source_path": work["source_path"],
                "source_sha256": _sha(sources[str(work["work_id"])]),
                "witness_description": work["witness_description"],
                "human_review": "required",
                "accepted_ir": "not_accepted",
                "publication": "not_ready",
            }
            for work in works
        ],
        "rights": {
            "project_gutenberg": (
                "license notice and link preserved in README.source.md"
            ),
            "internet_archive": (
                "digitization credits and all scanned front/back matter preserved "
                "in line-level TEI"
            ),
            "human_rights_decision": "not performed",
            "publication_state": "not_ready",
        },
    }
    if provenance != expected_provenance or provenance_bytes != _canonical(
        expected_provenance
    ):
        raise ValueError("LIB-071 complete provenance tree drift")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(
        _canonical(item) for item in profile["unresolved"]
    ):
        raise ValueError("LIB-071 unresolved evidence drift")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-local-readme").read_bytes():
        raise ValueError("LIB-071 source license README drift")


def _first_party_module_path(root: Path, module: str) -> Path | None:
    base = root.joinpath(*module.split("."))
    module_path = base.with_suffix(".py")
    if module_path.is_file():
        return module_path.resolve()
    package_path = base / "__init__.py"
    return package_path.resolve() if package_path.is_file() else None


def _resolved_import_name(module: str, path: Path, imported: str | None, level: int) -> str:
    if level == 0:
        return imported or ""
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    parts = package.split(".") if package else []
    if level - 1 > len(parts):
        return ""
    base = parts[: len(parts) - (level - 1)]
    if imported:
        base.extend(imported.split("."))
    return ".".join(base)


def _closure_paths(root: Path, policy: Mapping[str, object]) -> tuple[Path, ...]:
    forbidden = tuple(policy.get("forbidden_oracle_imports", []))
    pending = ["build.tei.gutenberg_evangelical_lib071_oracle"]
    modules: dict[str, Path] = {}
    while pending:
        module = pending.pop()
        if module in modules:
            continue
        path = _first_party_module_path(root, module)
        if path is None:
            continue
        modules[module] = path
        parts = module.split(".")
        package_parts = parts if path.name == "__init__.py" else parts[:-1]
        pending.extend(
            package for index in range(1, len(package_parts) + 1)
            if (package := ".".join(package_parts[:index])) not in modules
        )
        parsed = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(parsed):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = _resolved_import_name(module, path, node.module, node.level)
                if base:
                    names.append(base)
                    names.extend(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
            elif isinstance(node, ast.Call) and (
                (isinstance(node.func, ast.Name) and node.func.id in {"__import__", "eval", "exec", "import_module"})
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module")
            ):
                raise ValueError("LIB-071 oracle closure contains dynamic import or execution")
            for name in names:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    raise ValueError(f"LIB-071 oracle closure contains forbidden import {name}")
                if _first_party_module_path(root, name) is not None:
                    pending.append(name)
    return tuple(sorted(set(modules.values()), key=lambda item: item.as_posix()))


def _closure_digest(root: Path, policy: Mapping[str, object]) -> str:
    records = [
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in _closure_paths(root, policy)
    ]
    return _sha(_canonical(records))


def _source_set_sha256(source_manifest: SourceManifest) -> str:
    members = sorted(
        (
            {"name": item["name"], "path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]}
            for item in source_manifest.record["authorities"]
            if item.get("role") == "primary-source"
        ),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    return _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": members}))


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    if set(candidate.member_names) != MEMBERS or candidate.manifest.get("status") != "nonaccepted":
        raise ValueError("LIB-071 candidate member or status drift")
    expected_manifest = {
        "path": source_manifest.path.relative_to(root).as_posix(),
        "sha256": source_manifest.sha256,
    }
    if (
        candidate.manifest.get("source_manifest") != expected_manifest
        or candidate.manifest.get("converter") != source_manifest.record["converter"]
        or candidate.manifest.get("package_schema") != source_manifest.record["package_schema"]
    ):
        raise ValueError("LIB-071 candidate authority binding drift")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict_json(profile_bytes, "LIB-071 profile")
    policy = _strict_json(policy_bytes, "LIB-071 policy")
    expected_policy_core = {
        "candidate_status": "nonaccepted",
        "publication_state": "not_ready",
        "required_member_names": sorted(MEMBERS),
        "required_work_count": 10,
        "required_source_member_count": 10,
        "required_adjacent_member_count": 49,
    }
    observed_policy_core = {
        "candidate_status": policy.get("candidate_status"),
        "publication_state": policy.get("publication_state"),
        "required_member_names": sorted(policy.get("required_member_names", [])),
        "required_work_count": policy.get("required_work_count"),
        "required_source_member_count": policy.get("required_source_member_count"),
        "required_adjacent_member_count": policy.get("required_adjacent_member_count"),
    }
    if observed_policy_core != expected_policy_core:
        raise ValueError("LIB-071 validation policy closure drift")
    works = profile.get("works")
    if not isinstance(works, list) or len(works) != 10:
        raise ValueError("LIB-071 profile work census drift")
    sources: dict[str, bytes] = {}
    for work in works:
        name, work_id = str(work["authority_name"]), str(work["work_id"])
        content = source_manifest.authority_path(name).read_bytes()
        if _sha(content) != work["source_sha256"] or len(content) != work["source_bytes"]:
            raise ValueError(f"LIB-071 retained source drift: {work_id}")
        sources[work_id] = content
    _verify_tei(candidate, profile, sources)
    _verify_evidence(source_manifest, candidate, profile, sources)
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).resolve().read_bytes()),
        validator_import_closure_sha256=_closure_digest(root, policy),
        source_sha256=_source_set_sha256(source_manifest),
        profile_sha256=_sha(profile_bytes),
        package_schema_sha256=_sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        xsd_sha256=_sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        policy_sha256=_sha(policy_bytes),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
