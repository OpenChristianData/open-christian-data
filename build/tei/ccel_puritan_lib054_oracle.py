"""Producer-independent retained-byte oracle for frozen LIB-054."""

from __future__ import annotations

import ast
import base64
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import quote

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-ccel-puritan-lib054-independent-retained-byte-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
NON_ELEMENT_EVENT_RE = re.compile(
    r"(?P<doctype><!DOCTYPE\s[^[>]*(?:\[[^]]*\])?>)"
    r"|(?P<comment><!--[\s\S]*?-->)"
    r"|(?P<pi><\?(?!xml(?:\s|\?>))[\s\S]*?\?>)",
    flags=re.IGNORECASE,
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
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


def _assert_exact(
    observed: object, expected: object, label: str, path: str = "$"
) -> None:
    if type(observed) is not type(expected):
        raise ValueError(f"{label} JSON type mutation at {path}")
    if isinstance(expected, dict):
        if set(observed) != set(expected):
            raise ValueError(f"{label} JSON key mutation at {path}")
        for key, value in expected.items():
            _assert_exact(observed[key], value, label, f"{path}.{key}")  # type: ignore[index]
    elif isinstance(expected, list):
        if len(observed) != len(expected):  # type: ignore[arg-type]
            raise ValueError(f"{label} JSON list mutation at {path}")
        for index, (left, right) in enumerate(zip(observed, expected, strict=True)):  # type: ignore[arg-type]
            _assert_exact(left, right, label, f"{path}[{index}]")
    elif observed != expected:
        raise ValueError(f"{label} JSON value mutation at {path}")


def _exact_json(
    content: bytes, expected: dict[str, object], label: str
) -> dict[str, object]:
    observed = _strict_json(content, label)
    _assert_exact(observed, expected, label)
    if content != _canonical(expected):
        raise ValueError(f"{label} is not canonical")
    return observed


def _parse(content: bytes) -> etree._Element:
    text = content.decode("utf-8")
    prepared = re.sub(
        r"<!DOCTYPE\s[^[>]*(?:\[[^]]*\])?>", "", text, flags=re.DOTALL
    ).encode("utf-8")
    parser = etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True
    )
    try:
        return etree.fromstring(prepared, parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("retained LIB-054 XML is not independently parseable") from exc


def _non_element_events(content: bytes, work_id: str) -> list[dict[str, object]]:
    """Independently derive exact lexical non-element source events."""
    text = content.decode("utf-8")
    events: list[dict[str, object]] = []
    for ordinal, match in enumerate(NON_ELEMENT_EVENT_RE.finditer(text), 1):
        kind = str(match.lastgroup)
        lexical = match.group(0)
        events.append(
            {
                "work_id": work_id,
                "source_event_ordinal": ordinal,
                "kind": kind,
                "lexical": lexical,
                "sha256": _sha(lexical.encode("utf-8")),
            }
        )
    return events


def _local(qname: str) -> str:
    return etree.QName(qname).localname


def _selector(element: etree._Element) -> str:
    parts: list[str] = []
    current = element
    while True:
        parent = current.getparent()
        qname = str(current.tag)
        if parent is None:
            parts.append(f"{qname}[1]")
            break
        peers = [
            child
            for child in parent
            if isinstance(child.tag, str) and child.tag == current.tag
        ]
        parts.append(f"{qname}[{peers.index(current) + 1}]")
        current = parent
    return "/" + "/".join(reversed(parts))


def _features(content: bytes, work_id: str) -> list[dict[str, object]]:
    root = _parse(content)
    elements = [node for node in root.iter() if isinstance(node.tag, str)]
    ordinals = {id(node): index for index, node in enumerate(elements, 1)}
    result = []
    for index, element in enumerate(elements, 1):
        parent = element.getparent()
        siblings = (
            [child for child in parent if isinstance(child.tag, str)]
            if parent is not None
            else [element]
        )
        result.append(
            {
                "feature_id": f"{work_id}-feature-{index:05d}",
                "source_selector": _selector(element),
                "source_qname": str(element.tag),
                "source_attributes": [
                    {"qname": str(name), "value": value}
                    for name, value in element.attrib.items()
                ],
                "source_direct_text": element.text or "",
                "source_tail_text": element.tail or "",
                "source_parent_ordinal": ordinals[id(parent)]
                if parent is not None
                else None,
                "source_child_ordinal": siblings.index(element) + 1,
                "tei_xml_id": f"{work_id}-feature-{index:05d}",
                "work_id": work_id,
                "disposition": "represented",
                "tei_selector": f"#{work_id}-feature-{index:05d}",
            }
        )
    return result


def _metadata(content: bytes) -> list[dict[str, object]]:
    root = _parse(content)
    heads = [
        node
        for node in root.iter()
        if isinstance(node.tag, str) and _local(node.tag) == "ThML.head"
    ]
    if not heads:
        return []
    if len(heads) != 1:
        raise ValueError("LIB-054 metadata header cardinality mutation")
    return [
        {
            "qname": str(node.tag),
            "attributes": [
                {"qname": str(name), "value": value}
                for name, value in node.attrib.items()
            ],
            "text": node.text or "",
        }
        for node in heads[0].iter()
        if isinstance(node.tag, str)
    ]


def _element(
    name: str, attrs: Mapping[str, str] | None = None, text: str | None = None
) -> etree._Element:
    node = etree.Element(f"{{{TEI_NS}}}{name}")
    for key, value in (attrs or {}).items():
        node.set(XML_ID if key == "xml:id" else key, value)
    # An empty string deliberately remains distinct from ``None`` in lxml's
    # serializer: the converter retains empty source text as an explicit
    # paired element rather than collapsing it to a self-closing tag.
    node.text = text
    return node


def _expected_work(
    work: Mapping[str, object], content: bytes, features: list[dict[str, object]]
) -> etree._Element:
    work_id = str(work["work_id"])
    tei = _element("TEI", {"xml:id": work_id})
    header = _element("teiHeader")
    file_desc = _element("fileDesc")
    title_stmt = _element("titleStmt")
    title_stmt.append(_element("title", text=str(work["title"])))
    title_stmt.append(_element("author", text=str(work["author"])))
    resp = _element("respStmt")
    resp.append(_element("resp", text="Retained XML source provider"))
    resp.append(_element("name", text="Christian Classics Ethereal Library"))
    title_stmt.append(resp)
    file_desc.append(title_stmt)
    publication = _element("publicationStmt")
    publication.append(_element("publisher", text="Open Christian Data"))
    availability = _element("availability", {"status": "restricted"})
    availability.append(
        _element(
            "p",
            text="Nonaccepted technical reconstruction; rights review and publication authorization are absent.",
        )
    )
    publication.append(availability)
    file_desc.append(publication)
    source_desc = _element("sourceDesc")
    bibl = _element("bibl", {"type": "retained-witness"})
    bibl.append(_element("title", text=str(work["title"])))
    bibl.append(_element("author", text=str(work["author"])))
    bibl.append(
        _element("ref", {"target": str(work["source_url"])}, str(work["source_path"]))
    )
    bibl.append(_element("note", {"type": "source-sha256"}, _sha(content)))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    tei.append(header)
    text = _element("text")
    body = _element("body")
    division = _element(
        "div", {"xml:id": f"{work_id}-source", "type": "retained-source-member"}
    )
    division.append(_element("head", text=str(work["title"])))
    division.append(
        _element(
            "note",
            {
                "type": "exact-retained-source-bytes",
                "subtype": "base64",
                "n": _sha(content),
            },
            base64.b64encode(content).decode("ascii"),
        )
    )
    transcription = _element("div", {"type": "parsed-xml-feature-transcription"})
    for feature in features:
        block = _element(
            "ab",
            {
                "xml:id": str(feature["tei_xml_id"]),
                "type": "source-xml-element",
                "subtype": _local(str(feature["source_qname"])),
                "n": str(feature["source_child_ordinal"]),
                "corresp": "urn:source-xpath:"
                + quote(str(feature["source_selector"]), safe=""),
            },
        )
        block.append(
            _element("seg", {"type": "direct-text"}, str(feature["source_direct_text"]))
        )
        block.append(
            _element("seg", {"type": "tail-text"}, str(feature["source_tail_text"]))
        )
        transcription.append(block)
    division.append(transcription)
    body.append(division)
    text.append(body)
    tei.append(text)
    return tei


def _expected_tei(
    works: list[Mapping[str, object]],
    contents: Mapping[str, bytes],
    features: list[dict[str, object]],
) -> etree._Element:
    corpus = _element("teiCorpus", {"xml:id": "ccel-puritan-lib054-corpus"})
    header = _element("teiHeader")
    file_desc = _element("fileDesc")
    title_stmt = _element("titleStmt")
    title_stmt.append(
        _element("title", text="LIB-054: ten retained CCEL XML witnesses")
    )
    file_desc.append(title_stmt)
    publication = _element("publicationStmt")
    publication.append(_element("publisher", text="Open Christian Data"))
    availability = _element("availability", {"status": "restricted"})
    availability.append(
        _element("p", text="Nonaccepted candidate; not publication-ready.")
    )
    publication.append(availability)
    file_desc.append(publication)
    source_desc = _element("sourceDesc")
    source_desc.append(
        _element(
            "p",
            text="Ten exact retained CCEL XML authorities across ten frozen work identities.",
        )
    )
    file_desc.append(source_desc)
    header.append(file_desc)
    corpus.append(header)
    for work in works:
        work_id = str(work["work_id"])
        corpus.append(
            _expected_work(
                work,
                contents[work_id],
                [row for row in features if row["work_id"] == work_id],
            )
        )
    return corpus


def _expected_tei_document(
    works: list[Mapping[str, object]],
    contents: Mapping[str, bytes],
    features: list[dict[str, object]],
) -> bytes:
    """Construct the complete canonical TEI document, including its prolog.

    Comparing serialized document bytes is intentional here.  Parsing only the
    root loses document siblings, the XML declaration, DOCTYPE, and namespace
    declaration spellings; each is part of the closed nonaccepted candidate.
    """
    return etree.tostring(
        _expected_tei(works, contents, features),
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )


def _assert_excluded_members(root: Path, excluded: object) -> None:
    if not isinstance(excluded, list):
        raise ValueError("LIB-054 excluded member shape mutation")
    for member in excluded:
        if not isinstance(member, dict):
            raise ValueError("LIB-054 excluded member shape mutation")
        path = root / str(member.get("path", ""))
        content = path.read_bytes() if path.is_file() else b""
        if len(content) != member.get("bytes") or _sha(content) != member.get("sha256"):
            raise ValueError(
                f"LIB-054 excluded authority mutation at {member.get('path')}"
            )


def _assert_tree(
    observed: etree._Element, expected: etree._Element, path: str = "/"
) -> None:
    current = f"{path}{_local(expected.tag)}"
    if (
        observed.tag != expected.tag
        or list(observed.attrib.items()) != list(expected.attrib.items())
        or observed.text != expected.text
        or observed.tail != expected.tail
        or len(observed) != len(expected)
    ):
        raise ValueError(f"LIB-054 recursive TEI mutation at {current}")
    for index, (left, right) in enumerate(zip(observed, expected, strict=True), 1):
        _assert_tree(left, right, f"{current}[{index}]/")


def _candidate_manifest(
    source: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    names = (
        "README.source.md",
        "content.tei.xml",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    )
    return {
        "contract": "ocd-candidate-package-v1",
        "status": "nonaccepted",
        "source_id": source.record["source_id"],
        "source_manifest": {
            "path": source.path.relative_to(source.repository_root).as_posix(),
            "sha256": source.sha256,
        },
        "converter": dict(source.record["converter"]),
        "package_schema": dict(source.record["package_schema"]),
        "members": [
            {
                "name": name,
                "bytes": len(candidate.member_bytes(name)),
                "sha256": _sha(candidate.member_bytes(name)),
            }
            for name in names
        ],
    }


def _member_set_sha(source: SourceManifest) -> str:
    members = sorted(
        (
            {
                "name": item["name"],
                "path": item["path"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
            for item in source.record["authorities"]
            if item["role"] == "primary-source"
        ),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    if len(members) != 10:
        raise ValueError("LIB-054 primary authority cardinality mutation")
    return _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": members})
    )


def _local_module(root: Path, name: str) -> Path | None:
    for path in (
        root.joinpath(*name.split(".")).with_suffix(".py"),
        root.joinpath(*name.split("."), "__init__.py"),
    ):
        if path.is_file():
            return path.resolve()
    return None


def _module_name(root: Path, path: Path) -> str:
    relative = path.resolve().relative_to(root.resolve())
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _import_names(root: Path, path: Path, node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if not isinstance(node, ast.ImportFrom):
        return ()
    if node.level:
        module_name = _module_name(root, path)
        package_parts = module_name.split(".")
        if path.name != "__init__.py":
            package_parts.pop()
        if node.level > len(package_parts):
            raise ValueError("LIB-054 oracle relative import escapes repository")
        base = ".".join(package_parts[: len(package_parts) - node.level + 1])
        if node.module:
            base = f"{base}.{node.module}" if base else node.module
    else:
        base = node.module or ""
    if not base:
        return ()
    return (base, *(f"{base}.{alias.name}" for alias in node.names))


def _closure(root: Path, policy: Mapping[str, object]) -> tuple[dict[str, str], ...]:
    forbidden = tuple(str(item) for item in policy["forbidden_import_prefixes"])
    oracle_path = root / "build/tei/ccel_puritan_lib054_oracle.py"
    if not oracle_path.is_file():
        raise ValueError("LIB-054 oracle closure root is incomplete")
    pending = [oracle_path.resolve()]
    seen: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"eval", "exec", "__import__"}
            ):
                raise ValueError("LIB-054 oracle closure contains dynamic execution")
            for name in _import_names(root, path, node):
                if any(
                    name == prefix or name.startswith(prefix + ".")
                    for prefix in forbidden
                ):
                    raise ValueError(f"LIB-054 forbidden oracle import {name}")
                dependency = _local_module(root, name)
                if dependency is not None and dependency not in seen:
                    pending.append(dependency)
    return tuple(
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in sorted(seen, key=lambda item: item.relative_to(root).as_posix())
    )


def _closure_digest(root: Path, policy: Mapping[str, object]) -> str:
    return _sha(_canonical(_closure(root, policy)))


def _candidate_readme() -> bytes:
    return (
        "# LIB-054 source note\n\nThis nonaccepted technical candidate embeds the exact bytes of ten retained CCEL XML witnesses and inventories every parsed XML element.\n\nThe source files were sourced via CCEL.org. Do not sell CCEL files or derivatives of their formatting. The required data-side CCEL attribution notice is at `data/structured-text/README.md`.\n\nNo print collation, human textual acceptance, rights acceptance, canonical IR acceptance, or publication authorization is claimed.\n"
    ).encode("utf-8")


def _data_attribution_readme() -> bytes:
    return (
        "# CCEL attribution notice\n\n"
        "Some structured-text records in this directory were reconstructed from files sourced via [Christian Classics Ethereal Library (CCEL)](https://ccel.org/). When publishing those records or derivatives of CCEL's file formatting, credit Christian Classics Ethereal Library (CCEL) and link to CCEL.org.\n\n"
        "The underlying public-domain texts remain public domain. Do not sell CCEL files or derivatives of their formatting. This notice does not establish textual acceptance, exact edition identity, rights clearance, canonical IR acceptance, or publication authorization.\n"
    ).encode("utf-8")


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    _exact_json(
        candidate.member_bytes("manifest.json"),
        _candidate_manifest(source_manifest, candidate),
        "LIB-054 candidate manifest",
    )
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict_json(profile_bytes, "LIB-054 profile")
    policy = _strict_json(policy_bytes, "LIB-054 policy")
    works = profile.get("works")
    excluded = profile.get("excluded_members")
    if (
        profile.get("contract") != "ocd-ccel-puritan-lib054-profile-v1"
        or not isinstance(works, list)
        or len(works) != 10
        or not isinstance(excluded, list)
        or len(excluded) != 5
        or policy.get("contract") != "ocd-ccel-puritan-lib054-validation-policy-v1"
        or policy.get("required_feature_count") != 14065
        or policy.get("required_source_bytes") != 5244468
        or policy.get("required_qualified_attribute_count") != 0
        or policy.get("required_comment_count") != 44
        or policy.get("required_processing_instruction_count") != 6
        or policy.get("required_processing_instruction_source_count") != 3
        or policy.get("required_doctype_declaration_count") != 8
    ):
        raise ValueError("LIB-054 profile or policy mutation")
    authorities = {
        str(item["name"]): item for item in source_manifest.record["authorities"]
    }
    contents = {}
    features = []
    included = []
    metadata = {}
    non_element_events = []
    for work in works:
        work_id = str(work["work_id"])
        authority = authorities.get(str(work["authority_name"]))
        content = (
            source_manifest.authority_path(str(work["authority_name"])).read_bytes()
            if authority
            else b""
        )
        rows = _features(content, work_id)
        if (
            authority is None
            or authority.get("role") != "primary-source"
            or authority.get("path") != work.get("source_path")
            or len(content) != work["bytes"]
            or _sha(content) != work["sha256"]
            or len(rows) != work["element_count"]
        ):
            raise ValueError(f"LIB-054 independent authority mutation for {work_id}")
        contents[work_id] = content
        features.extend(rows)
        non_element_events.extend(_non_element_events(content, work_id))
        metadata[work_id] = _metadata(content)
        included.append(
            {
                "work_id": work_id,
                "path": authority["path"],
                "bytes": len(content),
                "sha256": _sha(content),
                "element_count": len(rows),
                "disposition": "included",
            }
        )
    family = sorted(
        path.relative_to(root).as_posix()
        for directory in profile["family_directories"]
        for path in (root / str(directory)).glob("*.xml")
    )
    configured = sorted(
        [str(row["path"]) for row in included] + [str(row["path"]) for row in excluded]
    )
    if family != configured or len(family) != 15:
        raise ValueError("LIB-054 independent family census mutation")
    _assert_excluded_members(root, excluded)
    qualified = sum(
        str(attr["qname"]).startswith("{")
        for row in features
        for attr in row["source_attributes"]
    )
    comment_count = sum(row["kind"] == "comment" for row in non_element_events)
    processing_instruction_count = sum(
        row["kind"] == "pi" for row in non_element_events
    )
    processing_instruction_source_count = len(
        {row["work_id"] for row in non_element_events if row["kind"] == "pi"}
    )
    doctype_declaration_count = sum(
        row["kind"] == "doctype" for row in non_element_events
    )
    if (
        comment_count != 44
        or processing_instruction_count != 6
        or processing_instruction_source_count != 3
        or doctype_declaration_count != 8
    ):
        raise ValueError("LIB-054 independent non-element event census mutation")
    census = {
        "included": included,
        "excluded": excluded,
        "counts": {"included": 10, "excluded": 5, "retained_family_total": 15},
    }
    accountability = {
        "contract": "ocd-ccel-puritan-lib054-source-accountability-v1",
        "schema": "lib054.source-accountability.schema.json",
        "profile_id": profile["profile_id"],
        "source_member_count": 10,
        "excluded_member_count": 5,
        "retained_family_member_count": 15,
        "work_count": 10,
        "source_bytes": sum(len(item) for item in contents.values()),
        "feature_count": len(features),
        "qualified_attribute_count": qualified,
        "comment_count": comment_count,
        "processing_instruction_count": processing_instruction_count,
        "processing_instruction_source_count": processing_instruction_source_count,
        "doctype_declaration_count": doctype_declaration_count,
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "member_census": census,
        "crosswalk": features,
        "non_element_events": non_element_events,
    }
    observed = _exact_json(
        candidate.member_bytes("source-accountability.json"),
        accountability,
        "LIB-054 accountability",
    )
    schema = _strict_json(
        source_manifest.authority_path("source-accountability-schema").read_bytes(),
        "LIB-054 accountability schema",
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(observed), key=str)
    if errors:
        raise ValueError(f"LIB-054 accountability schema failure: {errors[0].message}")
    expected_tei_document = _expected_tei_document(works, contents, features)
    candidate_tei_document = candidate.member_bytes("content.tei.xml")
    if candidate_tei_document != expected_tei_document:
        raise ValueError("LIB-054 complete TEI document mutation")
    tei = etree.fromstring(
        candidate_tei_document,
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    _assert_tree(
        tei,
        etree.fromstring(
            expected_tei_document,
            etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
        ),
    )
    if not compiled_schema().validate(etree.ElementTree(tei)):
        raise ValueError("LIB-054 TEI P5 failure")
    provenance = {
        "contract": "ocd-ccel-puritan-lib054-provenance-v1",
        "status": "nonaccepted",
        "publication": "not_ready",
        "ticket": "LIB-054",
        "work_ids": [work["work_id"] for work in works],
        "source_metadata": metadata,
        "rights": {
            "publication_authorized": False,
            "status": "human-review-required",
            "ccel_permission_authority": "ccel-permission",
            "source_attribution_authority": "source-local-readme",
            "data_attribution_deliverable": "data/structured-text/README.md",
        },
        "identity": {
            "status": "retained-witness-only",
            "print_collation": "not performed",
            "canonical_identity_decided": False,
        },
    }
    _exact_json(
        candidate.member_bytes("provenance.json"), provenance, "LIB-054 provenance"
    )
    unresolved = candidate.member_bytes("unresolved.jsonl")
    expected_unresolved = b"".join(_canonical(item) for item in profile["unresolved"])
    if unresolved != expected_unresolved:
        raise ValueError("LIB-054 unresolved ledger mutation")
    if candidate.member_bytes("README.source.md") != _candidate_readme():
        raise ValueError("LIB-054 candidate README mutation")
    if (
        b"sourced via CCEL.org"
        not in source_manifest.authority_path("source-local-readme").read_bytes()
        or b"Do not sell CCEL files"
        not in source_manifest.authority_path("ccel-permission").read_bytes()
    ):
        raise ValueError("LIB-054 CCEL attribution mutation")
    if (
        source_manifest.authority_path("data-attribution-readme").read_bytes()
        != _data_attribution_readme()
    ):
        raise ValueError("LIB-054 data-side CCEL attribution mutation")
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=_closure_digest(root, policy),
        source_sha256=_member_set_sha(source_manifest),
        profile_sha256=_sha(profile_bytes),
        package_schema_sha256=_sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        xsd_sha256=_sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        policy_sha256=_sha(policy_bytes),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
