"""Producer-independent retained-byte oracle for LIB-072."""

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


ORACLE_ID = "ocd-lib072-retained-text-oracle"
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
    rows: list[tuple[str, str]] = []
    for raw in content.splitlines(keepends=True):
        if raw.endswith(b"\r\n"):
            rows.append((raw[:-2].decode("utf-8"), "crlf"))
        elif raw.endswith(b"\n"):
            rows.append((raw[:-1].decode("utf-8"), "lf"))
        elif raw.endswith(b"\r"):
            rows.append((raw[:-1].decode("utf-8"), "cr"))
        else:
            rows.append((raw.decode("utf-8"), "none"))
    endings = {"crlf": b"\r\n", "lf": b"\n", "cr": b"\r", "none": b""}
    if b"".join(text.encode("utf-8") + endings[e] for text, e in rows) != content:
        raise ValueError("LIB-072 independent source line reader is not lossless")
    return rows


def _adjacent_inventory(
    root: Path,
    assigned: set[str],
    ticket_assigned: set[str],
    overrides: Mapping[str, object],
) -> list[dict[str, object]]:
    paths = sorted(
        [member for base in (root / "raw/gutenberg", root / "raw/ia") for member in base.iterdir() if member.is_file()],
        key=lambda item: item.as_posix(),
    )
    logical = {member.relative_to(root).as_posix() for member in paths}
    if (
        any(
            not isinstance(path, str) or not isinstance(reason, str)
            for path, reason in overrides.items()
        )
        or not set(overrides) <= logical - assigned
        or assigned - ticket_assigned
    ):
        raise ValueError("LIB-072 adjacent inventory dispositions are invalid")
    records = []
    for member in paths:
        content = member.read_bytes()
        path = member.relative_to(root).as_posix()
        records.append({
            "path": path,
            "bytes": len(content),
            "sha256": _sha(content),
            "disposition": (
                "included as one exact LIB-072 retained witness member"
                if path in assigned
                else (
                    "excluded: exact retained member assigned to another "
                    "LIB-072 work/package"
                    if path in ticket_assigned
                    else overrides.get(
                        path,
                        "excluded: adjacent retained member assigned outside LIB-072",
                    )
                )
            ),
        })
    return records


def _expected_tei(work: Mapping[str, object], sources: Mapping[str, bytes]) -> bytes:
    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    root.set(XML_ID, "lib072-gutenberg-evangelical")
    header = etree.SubElement(root, f"{{{TEI_NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}title").text = (
        f"LIB-072 retained witness: {work['title']}"
    )
    publication = etree.SubElement(file_desc, f"{{{TEI_NS}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI_NS}}}publisher").text = "Open Christian Data"
    availability = etree.SubElement(publication, f"{{{TEI_NS}}}availability", status="restricted")
    etree.SubElement(availability, f"{{{TEI_NS}}}p").text = (
        "Nonaccepted reconstruction candidate; human acceptance and publication authorization are absent."
    )
    source_desc = etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    source_list = etree.SubElement(source_desc, f"{{{TEI_NS}}}listBibl")
    bibl = etree.SubElement(source_list, f"{{{TEI_NS}}}bibl", type="retained-witness")
    bibl.set(XML_ID, f"source-{work['work_id']}")
    etree.SubElement(bibl, f"{{{TEI_NS}}}title").text = str(work["title"])
    etree.SubElement(bibl, f"{{{TEI_NS}}}author").text = str(work["author"])
    etree.SubElement(bibl, f"{{{TEI_NS}}}note", type="witness-description").text = str(work["witness_description"])
    for member in work["members"]:
        etree.SubElement(bibl, f"{{{TEI_NS}}}ref", target=str(member["source_url"])).text = str(member["source_path"])
    encoding = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
    project = etree.SubElement(encoding, f"{{{TEI_NS}}}projectDesc")
    etree.SubElement(project, f"{{{TEI_NS}}}p").text = (
        "Every retained physical source line is represented once and in member order as a source-line ab; subtype records its line-ending class for byte-exact UTF-8 reassembly."
    )
    text = etree.SubElement(root, f"{{{TEI_NS}}}text")
    group = etree.SubElement(text, f"{{{TEI_NS}}}group")
    work_id = str(work["work_id"])
    work_text = etree.SubElement(group, f"{{{TEI_NS}}}text")
    work_text.set(XML_ID, work_id)
    body = etree.SubElement(work_text, f"{{{TEI_NS}}}body")
    for member_index, _member in enumerate(work["members"], 1):
        division = etree.SubElement(body, f"{{{TEI_NS}}}div", type="retained-text-witness", n=str(member_index), corresp=f"#source-{work_id}")
        for ordinal, (line, ending) in enumerate(_physical_lines(sources[f"{work_id}:{member_index}"]), 1):
            node = etree.SubElement(division, f"{{{TEI_NS}}}ab", type="source-line", subtype=ending, n=str(ordinal))
            node.set(XML_ID, f"{work_id}-m{member_index}-line-{ordinal:05d}")
            node.text = line
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _expected_evidence(
    source_manifest: SourceManifest,
    work: Mapping[str, object],
    sources: Mapping[str, bytes],
) -> tuple[dict[str, object], dict[str, object]]:
    member_rows = []
    work_rows = []
    for work in [work]:
        work_id = str(work["work_id"])
        total_lines = total_chars = total_blanks = 0
        ending_counts = {ending: 0 for ending in ("crlf", "lf", "cr", "none")}
        member_hashes = []
        for member_index, member in enumerate(work["members"], 1):
            content = sources[f"{work_id}:{member_index}"]
            rows = _physical_lines(content)
            member_hashes.append("sha256:" + _sha(content))
            total_lines += len(rows)
            total_chars += sum(len(line) for line, _ in rows)
            total_blanks += sum(not line for line, _ in rows)
            for ending in ending_counts:
                ending_counts[ending] += sum(observed == ending for _, observed in rows)
            member_rows.append({
                "work_id": work_id,
                "member_index": member_index,
                "path": member["source_path"],
                "bytes": len(content),
                "sha256": _sha(content),
                "line_count": len(rows),
                "disposition": "included in full in declared work-member order",
            })
        claim = _sha("".join(member_hashes).encode("ascii")) if len(member_hashes) > 1 else member_hashes[0][7:]
        if claim != work["frozen_source_claim_sha256"]:
            raise ValueError(f"LIB-072 frozen source claim drifted for {work_id}")
        work_rows.append({
            "work_id": work_id,
            "member_count": len(work["members"]),
            "frozen_source_claim_sha256": claim,
            "line_count": total_lines,
            "character_count": total_chars,
            "blank_line_count": total_blanks,
            "line_ending_counts": ending_counts,
            "tei_selector_contract": f"#{work_id}-m%u-line-%05u",
            "omitted_line_count": 0,
            "duplicate_line_count": 0,
        })
    assigned = {str(member["source_path"]) for member in work["members"]}
    profile = _strict_json(
        source_manifest.authority_path("reconstruction-profile").read_bytes(),
        "LIB-072 profile",
    )
    overrides = profile["adjacent_retained_member_dispositions"]
    ticket_assigned = {
        str(member["source_path"])
        for profile_work in profile["works"]
        for member in profile_work["members"]
    }
    inventory = _adjacent_inventory(
        source_manifest.repository_root, assigned, ticket_assigned, overrides
    )
    if [row["path"] for row in inventory] != profile["adjacent_retained_member_paths"]:
        raise ValueError("LIB-072 profile does not account for exact adjacent inventory")
    accountability = {
        "contract": "ocd-lib072-source-accountability-v1",
        "schema": "gutenberg-evangelical-lib072.source-accountability.schema.json",
        "profile_id": profile["profile_id"],
        "assigned_work_count": 1,
        "assigned_member_count": len(work["members"]),
        "adjacent_member_count": 49,
        "source_members": member_rows,
        "adjacent_retained_member_accounting": inventory,
        "works": work_rows,
        "total_line_count": sum(int(row["line_count"]) for row in work_rows),
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "source_byte_reassembly": "exact UTF-8 text plus recorded per-line terminator and member order",
        "candidate_status": "nonaccepted",
        "human_review_required": True,
        "publication_ready": False,
    }
    provenance = {
        "contract": "ocd-lib072-provenance-v1",
        "source_manifest_sha256": source_manifest.sha256,
        "profile_id": profile["profile_id"],
        "text_authority": "the selected work's retained raw UTF-8 text members only",
        "diagnostic_non_authorities": ["build/parsers/gutenberg_evangelical.py", "canonical data JSON", "legacy TEI"],
        "works": [{
            "work_id": work["work_id"],
            "title": work["title"],
            "author": work["author"],
            "frozen_source_claim_sha256": work["frozen_source_claim_sha256"],
            "source_paths": [member["source_path"] for member in work["members"]],
            "witness_description": work["witness_description"],
            "human_review": "required",
            "accepted_ir": "not_accepted",
            "publication": "not_ready",
        } for work in [work]],
        "rights": {
            "project_gutenberg": "license notice and link preserved in README.source.md",
            "internet_archive": "digitization credits and scanned front/back matter preserved in line-level TEI",
            "human_rights_decision": "not performed",
            "publication_state": "not_ready",
        },
    }
    return accountability, provenance


def _verify_candidate(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    work: Mapping[str, object],
    profile: Mapping[str, object],
    sources: Mapping[str, bytes],
) -> None:
    content = candidate.member_bytes("content.tei.xml")
    if not content.startswith(b"<?xml version='1.0' encoding='UTF-8'?>") or b"<!DOCTYPE" in content:
        raise ValueError("LIB-072 TEI document shell drift")
    if content != _expected_tei(work, sources):
        raise ValueError("LIB-072 complete TEI tree metadata line order or source-id drift")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False)
    tree = etree.fromstring(content, parser).getroottree()
    if tree.getroot().get(XML_ID) != "lib072-gutenberg-evangelical" or any(
        isinstance(node, (etree._Comment, etree._ProcessingInstruction)) for node in tree.getroot().iter()
    ):
        raise ValueError("LIB-072 TEI root or invented node drift")
    try:
        compiled_schema().assertValid(tree)
    except etree.DocumentInvalid as exc:
        raise ValueError("LIB-072 candidate fails TEI P5 validation") from exc
    accountability, provenance = _expected_evidence(source_manifest, work, sources)
    accountability_bytes = candidate.member_bytes("source-accountability.json")
    observed_accountability = _strict_json(accountability_bytes, "LIB-072 accountability")
    schema = _strict_json(source_manifest.authority_path("source-accountability-schema").read_bytes(), "LIB-072 accountability schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(observed_accountability), key=str)
    if errors:
        raise ValueError(f"LIB-072 accountability schema failure: {errors[0].message}")
    if observed_accountability != accountability or accountability_bytes != _canonical(accountability):
        raise ValueError("LIB-072 complete accountability tree drift")
    provenance_bytes = candidate.member_bytes("provenance.json")
    if _strict_json(provenance_bytes, "LIB-072 provenance") != provenance or provenance_bytes != _canonical(provenance):
        raise ValueError("LIB-072 complete provenance tree drift")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_canonical(item) for item in profile["unresolved"]):
        raise ValueError("LIB-072 unresolved evidence drift")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-local-readme").read_bytes():
        raise ValueError("LIB-072 source license README drift")


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
    pending = ["build.tei.gutenberg_evangelical_lib072_oracle"]
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
        pending.extend(package for index in range(1, len(package_parts) + 1) if (package := ".".join(package_parts[:index])) not in modules)
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
                raise ValueError("LIB-072 oracle closure contains dynamic import or execution")
            for name in names:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    raise ValueError(f"LIB-072 oracle closure contains forbidden import {name}")
                if _first_party_module_path(root, name) is not None:
                    pending.append(name)
    return tuple(sorted(set(modules.values()), key=lambda item: item.as_posix()))


def _closure_digest(root: Path, policy: Mapping[str, object]) -> str:
    records = [{"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())} for path in _closure_paths(root, policy)]
    return _sha(_canonical(records))


def _source_set_sha256(source_manifest: SourceManifest) -> str:
    members = sorted(
        ({"name": item["name"], "path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]} for item in source_manifest.record["authorities"] if item.get("role") == "primary-source"),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    if len(members) == 1:
        return str(members[0]["sha256"])
    return _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": members}))


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    package_schema = _strict_json(
        source_manifest.authority_path("candidate-package-schema").read_bytes(),
        "LIB-072 candidate package schema",
    )
    raw_candidate_manifest = _strict_json(
        (candidate.path / "manifest.json").read_bytes(),
        "LIB-072 raw candidate manifest",
    )
    manifest_errors = sorted(
        Draft202012Validator(package_schema).iter_errors(raw_candidate_manifest),
        key=str,
    )
    if manifest_errors:
        raise ValueError(
            "LIB-072 candidate manifest schema failure: "
            f"{manifest_errors[0].message}"
        )
    if set(candidate.member_names) != MEMBERS:
        raise ValueError("LIB-072 candidate member closure drift")
    source_binding = candidate.manifest.get("source_manifest")
    if (
        candidate.manifest.get("source_id") != source_manifest.record.get("source_id")
        or not isinstance(source_binding, Mapping)
        or source_binding.get("sha256") != source_manifest.sha256
        or source_binding.get("path")
        != source_manifest.path.relative_to(source_manifest.repository_root).as_posix()
    ):
        raise ValueError("LIB-072 candidate source-id or source-manifest evidence drift")
    root = source_manifest.repository_root
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict_json(profile_bytes, "LIB-072 profile")
    policy = _strict_json(policy_bytes, "LIB-072 policy")
    expected_policy_core = {
        "candidate_status": "nonaccepted",
        "publication_state": "not_ready",
        "required_member_names": sorted(MEMBERS),
        "required_work_count": 1,
        "required_source_member_counts_by_work": {
            "spurgeon-all-of-grace": 1,
            "spurgeon-lectures-to-my-students": 2,
            "torrey-how-to-pray": 1,
            "torrey-what-the-bible-teaches": 1,
            "wilberforce-practical-view": 1,
        },
        "required_adjacent_member_count": 49,
    }
    observed_policy_core = {
        "candidate_status": policy.get("candidate_status"),
        "publication_state": policy.get("publication_state"),
        "required_member_names": sorted(policy.get("required_member_names", [])),
        "required_work_count": policy.get("required_work_count"),
        "required_source_member_counts_by_work": policy.get("required_source_member_counts_by_work"),
        "required_adjacent_member_count": policy.get("required_adjacent_member_count"),
    }
    if observed_policy_core != expected_policy_core:
        raise ValueError("LIB-072 validation policy closure drift")
    works = profile.get("works")
    if not isinstance(works, list) or len(works) != 5:
        raise ValueError("LIB-072 profile work census drift")
    manifest_work_id = source_manifest.record.get("work_id")
    selected = [work for work in works if work.get("work_id") == manifest_work_id]
    if len(selected) != 1:
        raise ValueError("LIB-072 manifest work selection drift")
    work = selected[0]
    sources: dict[str, bytes] = {}
    member_count = 0
    for member_index, member in enumerate(work["members"], 1):
        content = source_manifest.authority_path(str(member["authority_name"])).read_bytes()
        if _sha(content) != member["source_sha256"] or len(content) != member["source_bytes"]:
            raise ValueError(f"LIB-072 retained source drift: {work['work_id']}:{member_index}")
        sources[f"{work['work_id']}:{member_index}"] = content
        member_count += 1
    if member_count != len(work["members"]):
        raise ValueError("LIB-072 retained source member census drift")
    _verify_candidate(source_manifest, candidate, work, profile, sources)
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
