"""Independent retained-byte oracle for the LIB-034 Expositor's Bible corpus."""

from __future__ import annotations

import ast
import base64
import hashlib
import html
import json
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import quote

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-expositors-bible-lib034-independent-retained-byte-oracle"
ORACLE_VERSION = "1"
_TEI_URI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_HEX = frozenset("0123456789abcdef")
_ENTITY_VALUES = {
    "emdash": "-",
    "mdash": "-",
    "ndash": "-",
    "lsquo": "'",
    "rsquo": "'",
    "ldquo": '"',
    "rdquo": '"',
    "nbsp": " ",
}


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
        raise ValueError(f"{label} must be a JSON object")
    return value


def _assert_json_type_exact(
    observed: object, expected: object, label: str, path: str = "$"
) -> None:
    """Reject JSON values whose Python types only compare equal by coercion."""

    if type(observed) is not type(expected):
        raise ValueError(
            f"{label} JSON type mutation at {path}: "
            f"{type(observed).__name__} != {type(expected).__name__}"
        )
    if isinstance(expected, dict):
        if set(observed) != set(expected):
            raise ValueError(f"{label} JSON key mutation at {path}")
        for key, expected_value in expected.items():
            _assert_json_type_exact(
                observed[key], expected_value, label, f"{path}.{key}"  # type: ignore[index]
            )
        return
    if isinstance(expected, list):
        if len(observed) != len(expected):  # type: ignore[arg-type]
            raise ValueError(f"{label} JSON list-length mutation at {path}")
        for index, (observed_value, expected_value) in enumerate(
            zip(observed, expected, strict=True)  # type: ignore[arg-type]
        ):
            _assert_json_type_exact(
                observed_value, expected_value, label, f"{path}[{index}]"
            )
        return
    if observed != expected:
        raise ValueError(f"{label} JSON value mutation at {path}")


def _exact_json_member(
    content: bytes, expected: dict[str, object], label: str
) -> dict[str, object]:
    observed = _strict_json(content, label)
    _assert_json_type_exact(observed, expected, label)
    if content != _canonical(expected):
        raise ValueError(f"{label} is not the exact canonical expected JSON member")
    return observed


def _independent_xml(content: bytes) -> etree._Element:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("cp1252", errors="replace")
    text = re.sub(r"<!DOCTYPE\s[^[>]*(?:\[[^]]*\])?>", "", text, flags=re.DOTALL)

    def entity(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in {"amp", "lt", "gt", "quot", "apos"}:
            return match.group(0)
        if name in _ENTITY_VALUES:
            return _ENTITY_VALUES[name]
        decoded = html.unescape(match.group(0))
        return "" if decoded == match.group(0) else decoded

    prepared = re.sub(r"&([A-Za-z][A-Za-z0-9]*);", entity, text).encode("utf-8")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True)
    try:
        return etree.fromstring(prepared, parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("retained LIB-034 XML is not independently parseable") from exc


def _local(value: str) -> str:
    return etree.QName(value).localname


def _selector(element: etree._Element, root: etree._Element) -> str:
    parts: list[str] = []
    current = element
    while True:
        parent = current.getparent()
        tag = _local(current.tag)
        if parent is None:
            parts.append(f"{tag}[1]")
            break
        peers = [
            child
            for child in parent
            if isinstance(child.tag, str) and _local(child.tag) == tag
        ]
        parts.append(f"{tag}[{peers.index(current) + 1}]")
        current = parent
    if current is not root:
        raise ValueError("independent LIB-034 selector escaped the source document")
    return "/" + "/".join(reversed(parts))


def _features(content: bytes, member_id: str, work_id: str) -> list[dict[str, object]]:
    root = _independent_xml(content)
    elements = [item for item in root.iter() if isinstance(item.tag, str)]
    ordinals = {id(item): ordinal for ordinal, item in enumerate(elements, 1)}
    result = []
    for ordinal, element in enumerate(elements, 1):
        parent = element.getparent()
        siblings = (
            [item for item in parent if isinstance(item.tag, str)]
            if parent is not None
            else [element]
        )
        direct = element.text or ""
        tail = element.tail or ""
        identifier = f"{member_id}-feature-{ordinal:05d}"
        result.append(
            {
                "feature_id": identifier,
                "source_selector": _selector(element, root),
                "source_tag": _local(element.tag),
                "source_attributes": {
                    str(name): value for name, value in sorted(element.attrib.items())
                },
                "source_direct_text": direct,
                "source_tail_text": tail,
                "source_direct_text_sha256": _sha(direct.encode("utf-8")),
                "source_tail_text_sha256": _sha(tail.encode("utf-8")),
                "source_parent_ordinal": (
                    ordinals[id(parent)] if parent is not None else None
                ),
                "source_child_ordinal": siblings.index(element) + 1,
                "tei_xml_id": identifier,
                "member_id": member_id,
                "work_id": work_id,
                "disposition": "represented",
                "tei_selector": f"#{identifier}",
            }
        )
    return result


def _metadata(root: etree._Element) -> dict[str, str]:
    def one(local: str, predicate: object | None = None) -> str:
        rows = []
        for item in root.iter():
            if not isinstance(item.tag, str) or _local(item.tag) != local:
                continue
            if predicate is not None and not predicate(item):  # type: ignore[operator]
                continue
            rows.append("".join(item.itertext()).strip())
        if len(rows) != 1:
            raise ValueError(f"retained LIB-034 metadata {local} is ambiguous")
        return rows[0]

    return {
        "source_title": one("DC.Title", lambda item: item.get("sub") is None),
        "source_author": one(
            "DC.Creator",
            lambda item: item.get("sub") == "Author" and item.get("scheme") == "short-form",
        ),
        "print_source": one("published"),
        "source_url": "https://www.ccel.org"
        + one("DC.Identifier", lambda item: item.get("scheme") == "URL"),
    }


def _primary_member_set_sha(source_manifest: SourceManifest) -> str:
    members = sorted(
        (
            {
                "name": item["name"],
                "path": item["path"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
            for item in source_manifest.record["authorities"]
            if item["role"] == "primary-source"
        ),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    if len(members) != 10:
        raise ValueError("LIB-034 primary-source authority set is not exactly ten")
    return _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": members}))


def _member_census(
    source_manifest: SourceManifest, profile: Mapping[str, object]
) -> tuple[dict[str, object], list[dict[str, object]], dict[str, bytes]]:
    included = profile.get("included_members")
    excluded = profile.get("excluded_members")
    if not isinstance(included, list) or len(included) != 10:
        raise ValueError("LIB-034 independent included census is not ten")
    if not isinstance(excluded, list) or len(excluded) != 37:
        raise ValueError("LIB-034 independent excluded census is not thirty-seven")
    actual_family = sorted(
        path.relative_to(source_manifest.repository_root).as_posix()
        for path in (source_manifest.repository_root / "raw/ccel/expositors-bible").glob("*.xml")
    )
    configured = sorted(
        [
            str(item["path"])
            for item in source_manifest.record["authorities"]
            if item["role"] == "primary-source"
        ]
        + [str(item["path"]) for item in excluded]
    )
    if len(actual_family) != 47 or configured != actual_family:
        raise ValueError("LIB-034 retained-family census does not account for exact disk inventory")
    authorities = {str(item["name"]): item for item in source_manifest.record["authorities"]}
    rows: list[dict[str, object]] = []
    all_features: list[dict[str, object]] = []
    contents: dict[str, bytes] = {}
    for member in included:
        authority = authorities.get(str(member["authority_name"]))
        if authority is None or authority["role"] != "primary-source":
            raise ValueError("LIB-034 included member has no exact primary authority")
        content = source_manifest.authority_path(str(member["authority_name"])).read_bytes()
        if (
            len(content) != member["bytes"]
            or _sha(content) != member["sha256"]
            or _metadata(_independent_xml(content))
            != {key: member[key] for key in ("source_title", "source_author", "print_source", "source_url")}
        ):
            raise ValueError(f"LIB-034 member identity drifted: {member['member_id']}")
        features = _features(content, str(member["member_id"]), str(member["work_id"]))
        if len(features) != member["xml_element_count"]:
            raise ValueError("LIB-034 independently derived feature count drifted")
        all_features.extend(features)
        contents[str(member["member_id"])] = content
        rows.append(
            {
                "member_id": member["member_id"],
                "work_id": member["work_id"],
                "path": authority["path"],
                "bytes": len(content),
                "sha256": _sha(content),
                "xml_element_count": len(features),
                "disposition": "included",
                "reason": member["reason"],
            }
        )
    census = {
        "contract": "ocd-expositors-bible-lib034-member-census-v1",
        "included": rows,
        "excluded": excluded,
        "counts": {"included": 10, "excluded": 37, "retained_family_total": 47},
        "inventory_contradiction": profile["inventory_contradiction"],
    }
    namespace_collision = profile.get("namespace_attribute_collision")
    if not isinstance(namespace_collision, Mapping):
        raise ValueError("LIB-034 namespace-attribute collision authority is missing")
    distinct_keys = namespace_collision.get("distinct_keys")
    if not isinstance(distinct_keys, list) or any(
        not isinstance(key, str) for key in distinct_keys
    ):
        raise ValueError("LIB-034 namespace-attribute key authority is invalid")
    collisions = [
        item
        for item in all_features
        if item["member_id"] == namespace_collision.get("member_id")
        and item["source_tag"] == namespace_collision.get("source_tag")
        and all(key in item["source_attributes"] for key in distinct_keys)
    ]
    if len(collisions) != namespace_collision.get("count"):
        raise ValueError("LIB-034 independent namespace-qualified attribute census drifted")
    return census, all_features, contents


def _expected_provenance(
    source_manifest: SourceManifest,
    profile: Mapping[str, object],
    census: Mapping[str, object],
) -> dict[str, object]:
    return {
        "contract": "ocd-expositors-bible-lib034-candidate-provenance-v1",
        "status": "nonaccepted",
        "ticket": "LIB-034",
        "work_ids": [item["work_id"] for item in profile["works"]],
        "authorities": {
            str(item["name"]): {
                key: item[key] for key in ("path", "bytes", "sha256", "role")
            }
            for item in source_manifest.record["authorities"]
        },
        "member_census_sha256": _sha(_canonical(census)),
        "legacy_current_claims": profile["legacy_current_claims"],
        "rights": {
            "publication_authorized": False,
            "status": "human-review-required",
            "ccel_permission_authority": "ccel-permission",
            "attribution_deliverable": "data/commentaries/expositors-bible/README.md",
        },
        "identity": {
            "status": "retained-witness-metadata-only",
            "print_collation": "not performed",
            "canonical_identity_decided": False,
        },
    }


def _expected_accountability(
    profile: Mapping[str, object],
    census: Mapping[str, object],
    features: list[dict[str, object]],
    contents: Mapping[str, bytes],
) -> dict[str, object]:
    return {
        "contract": "ocd-expositors-bible-lib034-source-accountability-v1",
        "schema": "lib034.source-accountability.schema.json",
        "profile_id": profile["profile_id"],
        "source_member_count": 10,
        "work_count": 8,
        "source_bytes": sum(len(content) for content in contents.values()),
        "feature_count": len(features),
        "omitted_feature_count": 0,
        "unresolved_feature_count": 0,
        "member_census": census,
        "crosswalk": features,
    }


def _expected_candidate_manifest(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    member_names = (
        "README.source.md",
        "content.tei.xml",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    )
    return {
        "contract": "ocd-candidate-package-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source_manifest": {
            "path": source_manifest.path.relative_to(
                source_manifest.repository_root
            ).as_posix(),
            "sha256": source_manifest.sha256,
        },
        "converter": dict(source_manifest.record["converter"]),
        "package_schema": dict(source_manifest.record["package_schema"]),
        "members": [
            {
                "name": name,
                "bytes": len(candidate.member_bytes(name)),
                "sha256": _sha(candidate.member_bytes(name)),
            }
            for name in member_names
        ],
    }


def _expected_unresolved(profile: Mapping[str, object]) -> list[dict[str, str]]:
    return [
        {
            "id": "lib034-print-edition-collation-not-performed",
            "status": "unresolved",
            "scope": "all ten retained members",
            "reason": "Retained CCEL witness statements were preserved but not collated against print copies.",
        },
        {
            "id": "lib034-rights-and-publication-review",
            "status": "unresolved",
            "scope": "candidate corpus",
            "reason": "Technical validation does not decide rights acceptance or publication readiness.",
        },
        {
            "id": "lib034-retained-inventory-47-vs-legacy-48",
            "status": "unresolved",
            "scope": "Expositor's Bible family inventory",
            "reason": str(profile["inventory_contradiction"]),
        },
        {
            "id": "lib034-author-label-variants",
            "status": "unresolved",
            "scope": "moule-expositorromans, gibson-expositormatt, smith-ga-expositorisa2",
            "reason": "Retained creator strings differ from frozen work-label abbreviations; no canonical identity normalization is asserted.",
        },
    ]


def _expected_candidate_readme() -> bytes:
    return (
        "# LIB-034 source note\n\n"
        "This is a nonaccepted, nonpublication reconstruction candidate for eight frozen "
        "Expositor's Bible work identities. It embeds the exact bytes of ten retained "
        "CCEL ThML/XML members and inventories every parsed XML element.\n\n"
        "Source files were sourced via CCEL.org. CCEL permits parsing these ThML/XML files; "
        "do not sell CCEL files or derivatives of their formatting. See the digest-bound "
        "source-local permission record.\n\n"
        "No print collation, human textual acceptance, canonical identity decision, rights "
        "acceptance, or publication authorization is claimed.\n"
    ).encode("utf-8")


def _tei_element(
    name: str,
    attributes: Mapping[str, str] | None = None,
    text: str | None = None,
) -> etree._Element:
    node = etree.Element(f"{{{_TEI_URI}}}{name}")
    for key, value in (attributes or {}).items():
        node.set(_XML_ID if key == "xml:id" else key, value)
    # An empty string assigned by lxml serializes as an empty element and parses
    # back as None.  Build the independent expectation in parsed-tree form.
    node.text = text or None
    return node


def _expected_work_tei(
    work: Mapping[str, object],
    members: list[Mapping[str, object]],
    feature_rows: Mapping[str, list[Mapping[str, object]]],
    contents: Mapping[str, bytes],
) -> etree._Element:
    tei = _tei_element("TEI", {"xml:id": str(work["work_id"])})
    header = _tei_element("teiHeader")
    file_desc = _tei_element("fileDesc")
    title_stmt = _tei_element("titleStmt")
    title_stmt.append(_tei_element("title", text="The Expositor's Bible"))
    title_stmt.append(_tei_element("author", text=str(work["author"])))
    responsibility = _tei_element("respStmt")
    responsibility.append(_tei_element("resp", text="Series editor"))
    responsibility.append(_tei_element("name", text="William Robertson Nicoll"))
    title_stmt.append(responsibility)
    file_desc.append(title_stmt)
    publication = _tei_element("publicationStmt")
    publication.append(_tei_element("publisher", text="Open Christian Data"))
    availability = _tei_element("availability", {"status": "restricted"})
    availability.append(
        _tei_element(
            "p",
            text=(
                "Nonaccepted reconstruction candidate. Underlying texts are stated public "
                "domain; CCEL file and formatting conditions and publication rights require "
                "human review. Attribution is supplied separately."
            ),
        )
    )
    publication.append(availability)
    file_desc.append(publication)
    source_desc = _tei_element("sourceDesc")
    source_desc.append(
        _tei_element(
            "p",
            text=" | ".join(
                f"{member['source_title']} [{_sha(contents[str(member['member_id'])])}] "
                f"{member['source_url']} (print statement: {member['print_source']})"
                for member in members
            ),
        )
    )
    file_desc.append(source_desc)
    header.append(file_desc)
    tei.append(header)
    text = _tei_element("text")
    body = _tei_element("body")
    for member in members:
        member_id = str(member["member_id"])
        content = contents[member_id]
        division = _tei_element(
            "div",
            {"xml:id": member_id, "type": "retained-source-member"},
        )
        division.append(_tei_element("head", text=str(member["source_title"])))
        division.append(
            _tei_element(
                "note",
                {
                    "type": "exact-retained-source-bytes",
                    "subtype": "base64",
                    "n": _sha(content),
                },
                base64.b64encode(content).decode("ascii"),
            )
        )
        transcription = _tei_element(
            "div", {"type": "parsed-xml-feature-transcription"}
        )
        for feature in feature_rows[member_id]:
            block = _tei_element(
                "ab",
                {
                    "xml:id": str(feature["tei_xml_id"]),
                    "type": "source-xml-element",
                    "subtype": str(feature["source_tag"]),
                    "n": str(feature["source_child_ordinal"]),
                    "corresp": "urn:source-xpath:"
                    + quote(str(feature["source_selector"]), safe=""),
                },
            )
            block.append(
                _tei_element(
                    "seg",
                    {"type": "direct-text"},
                    str(feature["source_direct_text"]),
                )
            )
            block.append(
                _tei_element(
                    "seg",
                    {"type": "tail-text"},
                    str(feature["source_tail_text"]),
                )
            )
            transcription.append(block)
        division.append(transcription)
        body.append(division)
    text.append(body)
    tei.append(text)
    return tei


def _expected_tei(
    profile: Mapping[str, object],
    features: list[dict[str, object]],
    contents: Mapping[str, bytes],
) -> etree._Element:
    works = profile["works"]
    configured_members = profile["included_members"]
    feature_rows: dict[str, list[Mapping[str, object]]] = {
        str(member["member_id"]): [] for member in configured_members
    }
    for feature in features:
        feature_rows[str(feature["member_id"])].append(feature)
    corpus = _tei_element(
        "teiCorpus", {"xml:id": "expositors-bible-lib034-corpus"}
    )
    corpus_header = _tei_element("teiHeader")
    file_desc = _tei_element("fileDesc")
    title_stmt = _tei_element("titleStmt")
    title_stmt.append(
        _tei_element(
            "title", text="The Expositor's Bible: LIB-034 retained-source corpus"
        )
    )
    file_desc.append(title_stmt)
    publication = _tei_element("publicationStmt")
    publication.append(_tei_element("publisher", text="Open Christian Data"))
    availability = _tei_element("availability", {"status": "restricted"})
    availability.append(
        _tei_element("p", text="Nonaccepted candidate; not publication-ready.")
    )
    publication.append(availability)
    file_desc.append(publication)
    source_desc = _tei_element("sourceDesc")
    source_desc.append(
        _tei_element(
            "p",
            text="Ten exact retained CCEL XML members across eight frozen works.",
        )
    )
    file_desc.append(source_desc)
    corpus_header.append(file_desc)
    corpus.append(corpus_header)
    for work in works:
        members = [
            member
            for member in configured_members
            if member["work_id"] == work["work_id"]
        ]
        if len(members) != work["member_count"]:
            raise ValueError("LIB-034 independent work/member lineage drifted")
        corpus.append(_expected_work_tei(work, members, feature_rows, contents))
    return corpus


def _assert_tree_exact(
    observed: etree._Element, expected: etree._Element, path: str = "/"
) -> None:
    expected_name = etree.QName(expected.tag).localname
    current_path = f"{path}{expected_name}"
    if observed.tag != expected.tag:
        raise ValueError(f"LIB-034 TEI QName mutation at {current_path}")
    if dict(observed.attrib) != dict(expected.attrib):
        raise ValueError(f"LIB-034 TEI attribute mutation at {current_path}")
    if observed.text != expected.text:
        raise ValueError(f"LIB-034 TEI text mutation at {current_path}")
    if observed.tail != expected.tail:
        raise ValueError(f"LIB-034 TEI tail mutation at {current_path}")
    if len(observed) != len(expected):
        raise ValueError(f"LIB-034 TEI child-count mutation at {current_path}")
    for index, (observed_child, expected_child) in enumerate(
        zip(observed, expected, strict=True), 1
    ):
        _assert_tree_exact(observed_child, expected_child, f"{current_path}[{index}]/")


def _verify_tei(
    tei_bytes: bytes,
    profile: Mapping[str, object],
    features: list[dict[str, object]],
    contents: Mapping[str, bytes],
) -> None:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    root = etree.fromstring(tei_bytes, parser)
    expected = _expected_tei(profile, features, contents)
    _assert_tree_exact(root, expected)
    schema = compiled_schema()
    document = etree.ElementTree(root)
    if not schema.validate(document):
        raise ValueError(f"LIB-034 TEI P5 failure: {schema.error_log.last_error}")


def _local_module_path(root: Path, name: str) -> Path | None:
    parts = name.split(".")
    module = root.joinpath(*parts).with_suffix(".py")
    package = root.joinpath(*parts, "__init__.py")
    for candidate in (module, package):
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if resolved.is_file():
            return resolved
    return None


def _resolved_import_names(path: Path, root: Path, node: ast.ImportFrom) -> tuple[str, ...]:
    if node.level == 0:
        base = node.module or ""
    else:
        relative = path.relative_to(root)
        package = list(relative.parts[:-1])
        ascend = node.level - 1
        if ascend > len(package):
            raise ValueError("LIB-034 oracle relative import escaped repository")
        prefix = package[: len(package) - ascend]
        suffix = node.module.split(".") if node.module else []
        base = ".".join([*prefix, *suffix])
    names = [base] if base else []
    names.extend(
        f"{base}.{alias.name}" if base else alias.name
        for alias in node.names
        if alias.name != "*"
    )
    return tuple(names)


def _package_initializers(root: Path, path: Path) -> tuple[Path, ...]:
    relative = path.relative_to(root)
    result = []
    for depth in range(1, len(relative.parts)):
        candidate = root.joinpath(*relative.parts[:depth], "__init__.py")
        if candidate.is_file():
            result.append(candidate.resolve(strict=True))
    return tuple(result)


def _repository_import_closure(
    root: Path, entry: Path, forbidden: tuple[str, ...]
) -> tuple[dict[str, str], ...]:
    root = root.resolve(strict=True)
    entry = entry.resolve(strict=True)
    entry.relative_to(root)
    pending = [entry, *_package_initializers(root, entry)]
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "eval", "exec"}
            ):
                raise ValueError("LIB-034 oracle closure contains dynamic execution")
            names: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names = _resolved_import_names(path, root, node)
            for name in names:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    raise ValueError(f"LIB-034 oracle closure contains forbidden import {name}")
                dependency = _local_module_path(root, name)
                if dependency is not None and dependency not in visited:
                    pending.append(dependency)
                    pending.extend(_package_initializers(root, dependency))
    return tuple(
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in sorted(visited, key=lambda item: item.relative_to(root).as_posix())
    )


def _closure_digest(root: Path, policy: Mapping[str, object]) -> str:
    forbidden = tuple(str(item) for item in policy.get("forbidden_import_prefixes", []))
    return _sha(_canonical(_repository_import_closure(root, Path(__file__), forbidden)))


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    expected_manifest = _expected_candidate_manifest(source_manifest, candidate)
    manifest = _exact_json_member(
        candidate.member_bytes("manifest.json"),
        expected_manifest,
        "LIB-034 candidate manifest",
    )
    if any(type(member["bytes"]) is not int for member in manifest["members"]):
        raise ValueError("LIB-034 candidate manifest member bytes must be exact integers")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict_json(profile_bytes, "LIB-034 reconstruction profile")
    policy = _strict_json(policy_bytes, "LIB-034 validation policy")
    namespace_collision = profile.get("namespace_attribute_collision")
    if (
        profile.get("contract") != "ocd-expositors-bible-lib034-profile-v1"
        or profile.get("profile_id")
        != "expositors-bible-lib034-complete-current-claim-xml-v1"
        or not isinstance(namespace_collision, dict)
        or policy.get("contract")
        != "ocd-expositors-bible-lib034-validation-policy-v1"
        or policy.get("candidate_status") != "nonaccepted"
        or policy.get("required_source_members") != 10
        or policy.get("required_excluded_members") != 37
        or policy.get("required_retained_family_members") != 47
        or policy.get("required_work_ids")
        != [item["work_id"] for item in profile["works"]]
        or policy.get("required_feature_count") != 47636
        or policy.get("required_source_bytes") != 9480629
        or policy.get("required_namespace_attribute_collision_count")
        != namespace_collision.get("count")
    ):
        raise ValueError("LIB-034 profile or validation policy mutation")
    census, features, contents = _member_census(source_manifest, profile)
    expected_accountability = _expected_accountability(
        profile, census, features, contents
    )
    accountability = _exact_json_member(
        candidate.member_bytes("source-accountability.json"),
        expected_accountability,
        "LIB-034 accountability",
    )
    schema_bytes = source_manifest.authority_path("source-accountability-schema").read_bytes()
    schema = _strict_json(schema_bytes, "LIB-034 accountability schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"LIB-034 accountability schema failure: {errors[0].message}")
    _verify_tei(candidate.member_bytes("content.tei.xml"), profile, features, contents)
    expected_provenance = _expected_provenance(source_manifest, profile, census)
    _exact_json_member(
        candidate.member_bytes("provenance.json"),
        expected_provenance,
        "LIB-034 provenance",
    )
    unresolved_bytes = candidate.member_bytes("unresolved.jsonl")
    unresolved = [
        _strict_json(line + b"\n", "LIB-034 unresolved record")
        for line in unresolved_bytes.splitlines()
        if line.strip()
    ]
    expected_unresolved = _expected_unresolved(profile)
    _assert_json_type_exact(unresolved, expected_unresolved, "LIB-034 unresolved ledger")
    if (
        unresolved_bytes != b"".join(_canonical(item) for item in expected_unresolved)
        or [item["id"] for item in expected_unresolved]
        != policy["required_unresolved_ids"]
    ):
        raise ValueError("LIB-034 unresolved ledger mutation")
    candidate_readme = candidate.member_bytes("README.source.md")
    data_readme = source_manifest.authority_path("attribution-readme").read_bytes()
    permission = source_manifest.authority_path("ccel-permission").read_bytes()
    if candidate_readme != _expected_candidate_readme():
        raise ValueError("LIB-034 candidate README mutation")
    if b"sourced via CCEL.org" not in data_readme:
        raise ValueError("LIB-034 required durable CCEL attribution mutation")
    if b"do not sell CCEL files or derivatives of their formatting" not in permission:
        raise ValueError("LIB-034 CCEL permission authority mutation")
    implementation = Path(__file__).resolve()
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(implementation.read_bytes()),
        validator_import_closure_sha256=_closure_digest(root, policy),
        source_sha256=_primary_member_set_sha(source_manifest),
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
