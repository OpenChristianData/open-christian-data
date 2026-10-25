"""Independent source oracle for ticket 37c-092 Calvin commentaries.

This module intentionally duplicates the retained-source reader's selectors,
lexical census, and target-name expectations instead of importing the producer.
It validates the candidate against the CCEL source cohort and treats the SWORD
module only as a separately bound comparison witness.
"""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Mapping
from urllib.parse import quote

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-calvin-commentaries-independent-source-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
FORMAT_ONLY = frozenset({"style", "selector", "property", "colgroup", "col"})
DIV_SOURCE_TAGS = frozenset(
    {
        "div",
        "div1",
        "div2",
        "div3",
        "div4",
        "ThML.head",
        "ThML.body",
        "DC",
        "comments",
        "generalInfo",
        "printSourceInfo",
        "electronicEdInfo",
        "center",
    }
)
PROFILE_AUTHORITY = "reconstruction-profile"
POLICY_AUTHORITY = "validation-policy"
SCHEMA_AUTHORITY = "source-accountability-schema"
README_AUTHORITY = "source-local-readme"
CONFIG_AUTHORITY = "work-config"
METADATA_AUTHORITY = "metadata-evidence"
PRIMARY_ROLE = "primary-source"
CCEL_URL = "https://www.ccel.org/ccel/calvin/commentaries.html"
SWORD_SHA256 = "df66fc8c03537499ad006d069481d2c95b600887cdbd6ce75ec5d264b573192a"
SWORD_BYTES = 20_897_508


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


def _parse(content: bytes) -> etree._Element:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        huge_tree=True,
        remove_comments=False,
        remove_pis=False,
    )
    try:
        return etree.fromstring(content, parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("Calvin retained source is not parseable") from exc


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _selector(node: etree._Element) -> str:
    parent = node.getparent()
    if parent is None:
        return f"/{_local(node)}[1]"
    siblings = [child for child in parent if child.tag == node.tag]
    return f"{_selector(parent)}/{_local(node)}[{siblings.index(node) + 1}]"


def _source_uri(member: str, selector: str) -> str:
    return (
        "urn:source-member:"
        + quote(member, safe="")
        + ":urn:source-xpath:"
        + quote(selector, safe="")
    )


def _is_formatting(node: etree._Element) -> bool:
    return _local(node) in FORMAT_ONLY or any(
        _local(ancestor) in FORMAT_ONLY
        for ancestor in node.iterancestors()
        if isinstance(ancestor.tag, str)
    )


def _census(root: etree._Element) -> tuple[dict[str, int], dict[str, int]]:
    elements = [node for node in root.iter() if isinstance(node.tag, str)]
    counts = dict(sorted(Counter(_local(node) for node in elements).items()))
    census = {
        "elements": len(elements),
        "attributes": sum(len(node.attrib) for node in elements),
        "text_nodes": sum(node.text is not None for node in elements),
        "tail_nodes": sum(node.tail is not None for node in elements),
        "characters": sum(
            len(node.text or "") + len(node.tail or "") for node in elements
        ),
    }
    return counts, census


def _lexical_events(root: etree._Element) -> dict[str, int]:
    tree = root.getroottree()
    return {
        "comments": len(tree.xpath("//comment()")),
        "processing_instructions": len(tree.xpath("//processing-instruction()")),
        "doctype_declarations": 1 if tree.docinfo.doctype else 0,
    }


def _profile_member(profile: Mapping[str, object], name: str) -> Mapping[str, object]:
    values = profile.get("members")
    if not isinstance(values, list):
        raise ValueError("Calvin profile members are invalid")
    for value in values:
        if isinstance(value, Mapping) and value.get("name") == name:
            return value
    raise ValueError(f"Calvin profile has no member {name!r}")


def _member_set(source_manifest: SourceManifest) -> list[dict[str, object]]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("Calvin source manifest authorities are invalid")
    primary = [
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("role") == PRIMARY_ROLE
    ]
    records = [
        {
            "name": str(item["name"]),
            "path": str(item["path"]),
            "bytes": int(item["bytes"]),
            "sha256": str(item["sha256"]),
        }
        for item in primary
    ]
    return sorted(records, key=lambda item: (str(item["path"]), str(item["name"])))


def _expected_features(
    member: str,
    root: etree._Element,
    start_ordinal: int,
) -> list[dict[str, object]]:
    features: list[dict[str, object]] = []
    for offset, element in enumerate(
        (node for node in root.iter() if isinstance(node.tag, str)),
        0,
    ):
        parent = element.getparent()
        siblings = (
            [child for child in parent if isinstance(child.tag, str)]
            if parent is not None
            else [element]
        )
        features.append(
            {
                "feature_id": f"calvin-commentaries-feature-{start_ordinal + offset:06d}",
                "member": member,
                "source_selector": _selector(element),
                "source_qname": str(element.tag),
                "source_attributes": [
                    {"qname": str(name), "value": str(value)}
                    for name, value in element.attrib.items()
                ],
                "source_direct_text": element.text or "",
                "source_tail_text": element.tail or "",
                "source_parent_selector": _selector(parent) if parent is not None else None,
                "source_child_ordinal": siblings.index(element) + 1,
                "disposition": (
                    "formatting-only-excluded" if _is_formatting(element) else "represented"
                ),
            }
        )
    return features


def _heading_is_post_content(source: etree._Element) -> bool:
    if any(
        _local(ancestor) in {"td", "th"}
        for ancestor in source.iterancestors()
        if isinstance(ancestor.tag, str)
    ):
        return True
    parent = source.getparent()
    if parent is None:
        return False
    for sibling in parent:
        if sibling is source:
            break
        if not isinstance(sibling.tag, str) or _is_formatting(sibling):
            continue
        if _local(sibling) in {"pb", "hr", "h1", "h2", "h3", "h4"}:
            continue
        return True
    return False


def _target_local(source: etree._Element) -> str:
    local = _local(source)
    if source.getparent() is None:
        return "div"
    if local in DIV_SOURCE_TAGS:
        if (source.text or "").strip() and not any(
            isinstance(child.tag, str) for child in source
        ):
            return "p"
        return "div"
    if local in {"h1", "h2", "h3", "h4"}:
        return "p" if _heading_is_post_content(source) else "head"
    if local in {"p"}:
        return "p"
    if local in {"b", "i", "sup"}:
        return "hi"
    if local == "span":
        return "hi" if (source.get("class") or "").casefold() == "sc" else (
            "foreign" if source.get("lang") else "seg"
        )
    if local == "br":
        return "lb"
    if local == "scripRef":
        return "ref"
    if local == "scripCom":
        return "seg"
    if local in {"note", "pb", "hr", "table", "tr", "td", "th", "ul", "li", "verse", "l", "insertIndex", "added", "unclear", "name", "cite", "a", "link", "img"}:
        return {
            "hr": "milestone",
            "tr": "row",
            "td": "cell",
            "th": "cell",
            "ul": "list",
            "li": "item",
            "verse": "lg",
            "insertIndex": "anchor",
            "added": "add",
            "cite": "quote",
            "a": "ref",
            "link": "ref",
            "img": "graphic",
        }.get(local, local)
    parent = source.getparent()
    if parent is not None and _local(parent) in DIV_SOURCE_TAGS:
        return "p"
    return "seg"


def _source_stream(node: etree._Element) -> str:
    parts: list[str] = []
    if not _is_formatting(node):
        parts.append(node.text or "")
    for child in node:
        if isinstance(child.tag, str) and not _is_formatting(child):
            parts.append(_source_stream(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _candidate_stream(node: etree._Element) -> str:
    parts = [node.text or ""]
    for child in node:
        if isinstance(child.tag, str):
            parts.append(_candidate_stream(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _local_module(root: Path, name: str) -> Path | None:
    for path in (
        root.joinpath(*name.split(".")).with_suffix(".py"),
        root.joinpath(*name.split("."), "__init__.py"),
    ):
        if path.is_file():
            return path.resolve(strict=True)
    return None


def _module_name(root: Path, path: Path) -> str:
    relative = path.resolve(strict=True).relative_to(root.resolve(strict=True))
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
        package = _module_name(root, path).split(".")
        if path.name != "__init__.py":
            package.pop()
        if node.level > len(package):
            raise ValueError("Calvin oracle import closure escaped repository")
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
            raise ValueError("Calvin oracle import closure escaped repository") from exc
        seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {
                "eval",
                "exec",
                "__import__",
            }:
                raise ValueError("Calvin oracle closure contains dynamic execution")
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


def _candidate_manifest(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    content = (candidate.path / "manifest.json").read_bytes()
    record = _strict_json(content, "Calvin candidate manifest")
    converter = dict(source_manifest.record["converter"])
    package_schema = dict(source_manifest.record["package_schema"])
    expected = {
        "contract": "ocd-candidate-package-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source_manifest": {
            "path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(),
            "sha256": source_manifest.sha256,
        },
        "converter": converter,
        "package_schema": package_schema,
        "members": record.get("members"),
    }
    if record != expected or content != _canonical(expected):
        raise ValueError("Calvin candidate manifest binding drifted")
    return record


def _verify_source_envelope(
    source_manifest: SourceManifest,
    profile: Mapping[str, object],
    policy: Mapping[str, object],
    schema: Mapping[str, object],
) -> list[Mapping[str, object]]:
    record = source_manifest.record
    if (
        record.get("ticket_id") != "37c-092"
        or record.get("work_id") != "calvin-commentaries"
        or record.get("source_id") != "calvin-commentaries-retained-ccel-thml"
    ):
        raise ValueError("Calvin source identity drifted")
    if (
        profile.get("contract") != "ocd-calvin-commentaries-profile-v1"
        or profile.get("profile_id") != "calvin-commentaries-retained-ccel-thml-v1"
        or profile.get("source_bytes") != 74248915
        or profile.get("source_member_set_sha256")
        != "2ed1ca9ee905b3cb709bbe9b8dd800e1ed8c78eba4146945b4e8924ad8efa235"
        or profile.get("source_census") != {
            "attributes": 912249,
            "characters": 51274609,
            "comments": 369,
            "doctype_declarations": 36,
            "elements": 583805,
            "processing_instructions": 20,
            "tail_nodes": 449460,
            "text_nodes": 471791,
        }
        or profile.get("represented_element_count") != 581157
        or profile.get("formatting_only_excluded_element_count") != 2648
        or profile.get("unsupported_element_count") != 0
    ):
        raise ValueError("Calvin source profile envelope drifted")
    if (
        policy.get("contract") != "ocd-calvin-commentaries-validation-policy-v1"
        or policy.get("policy_id") != "calvin-commentaries-retained-ccel-thml-policy-v1"
        or policy.get("oracle_id") != ORACLE_ID
        or policy.get("required_primary_source_members") != 46
        or policy.get("required_source_element_count") != 583805
    ):
        raise ValueError("Calvin validation policy envelope drifted")
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise ValueError("Calvin source-accountability schema dialect drifted")
    config = _strict_json(source_manifest.authority_path(CONFIG_AUTHORITY).read_bytes(), "Calvin config")
    if config.get("resource_id") != "calvin-commentaries" or config.get("title") != "Calvin's Collected Commentaries" or config.get("author") != "John Calvin":
        raise ValueError("Calvin work-config identity drifted")
    metadata = _strict_json(source_manifest.authority_path(METADATA_AUTHORITY).read_bytes(), "Calvin metadata evidence")
    if metadata.get("contract") != "ocd-calvin-commentaries-metadata-evidence-v1" or metadata.get("work_id") != "calvin-commentaries":
        raise ValueError("Calvin metadata evidence identity drifted")
    profile_members = profile.get("members")
    if not isinstance(profile_members, list) or len(profile_members) != 46:
        raise ValueError("Calvin profile member cardinality drifted")
    primary = _member_set(source_manifest)
    expected = sorted(
        [
            {"name": item.get("name"), "path": item.get("path"), "bytes": item.get("bytes"), "sha256": item.get("sha256")}
            for item in profile_members
            if isinstance(item, Mapping)
        ],
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    if primary != expected or len(primary) != 46:
        raise ValueError("Calvin primary source set drifted")
    member_set_sha = _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": primary}))
    if member_set_sha != profile["source_member_set_sha256"]:
        raise ValueError("Calvin source member-set digest drifted")
    comparison = [
        item
        for item in source_manifest.record.get("authorities", ())
        if isinstance(item, Mapping) and item.get("role") == "comparison-witness-only"
    ]
    if len(comparison) != 2:
        raise ValueError("Calvin comparison-witness set drifted")
    comparison_by_name = {str(item["name"]): item for item in comparison}
    archive = comparison_by_name.get("sword-comparison-archive")
    if not isinstance(archive, Mapping) or archive.get("sha256") != SWORD_SHA256 or archive.get("bytes") != SWORD_BYTES:
        raise ValueError("Calvin SWORD comparison archive binding drifted")
    return profile_members


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    _candidate_manifest(source_manifest, candidate)
    profile_bytes = source_manifest.authority_path(PROFILE_AUTHORITY).read_bytes()
    policy_bytes = source_manifest.authority_path(POLICY_AUTHORITY).read_bytes()
    schema_bytes = source_manifest.authority_path(SCHEMA_AUTHORITY).read_bytes()
    profile = _strict_json(profile_bytes, "Calvin profile")
    policy = _strict_json(policy_bytes, "Calvin policy")
    schema = _strict_json(schema_bytes, "Calvin accountability schema")
    profile_members = _verify_source_envelope(source_manifest, profile, policy, schema)

    expected_account_fields: dict[str, object] = {
        "contract": "ocd-calvin-commentaries-source-accountability-v1",
        "profile_id": profile["profile_id"],
        "work_id": "calvin-commentaries",
        "source_id": source_manifest.record["source_id"],
        "source_member_set_sha256": profile["source_member_set_sha256"],
        "source_bytes": profile["source_bytes"],
        "source_census": profile["source_census"],
        "element_counts": profile["element_counts"],
        "lexical_events": profile["lexical_events"],
        "lexical_event_disposition": profile["lexical_event_disposition"],
        "member_census": {"included": 46, "excluded": 0, "retained_family_total": 46},
        "represented_element_count": profile["represented_element_count"],
        "formatting_only_excluded_element_count": profile["formatting_only_excluded_element_count"],
        "unsupported_element_count": 0,
        "formatting_only_counts": profile["formatting_only_counts"],
    }
    account_bytes = (candidate.path / "source-accountability.json").read_bytes()
    accountability = _strict_json(account_bytes, "Calvin source accountability")
    schema_errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if schema_errors:
        raise ValueError(f"Calvin source-accountability schema failure: {schema_errors[0].message}")
    for key, expected in expected_account_fields.items():
        if accountability.get(key) != expected:
            raise ValueError(f"Calvin accountability field {key!r} drifted")
    if account_bytes != _canonical(accountability):
        raise ValueError("Calvin source-accountability JSON is not canonical")
    observed_features = accountability.get("features")
    if not isinstance(observed_features, list):
        raise ValueError("Calvin accountability feature inventory is invalid")

    member_summaries: list[dict[str, object]] = []
    aggregate_counts: Counter[str] = Counter()
    aggregate_census: Counter[str] = Counter()
    aggregate_lexical: Counter[str] = Counter()
    feature_position = 0
    for member in profile_members:
        if not isinstance(member, Mapping):
            raise ValueError("Calvin profile member record is invalid")
        name = str(member["name"])
        source_bytes = source_manifest.authority_path(name).read_bytes()
        if len(source_bytes) != int(member["bytes"]) or _sha(source_bytes) != str(member["sha256"]):
            raise ValueError(f"Calvin source authority bytes drifted for {name}")
        source_root = _parse(source_bytes)
        counts, census = _census(source_root)
        lexical = _lexical_events(source_root)
        features = _expected_features(name, source_root, feature_position + 1)
        feature_position += len(features)
        observed_slice = observed_features[feature_position - len(features) : feature_position]
        if observed_slice != features:
            raise ValueError(f"Calvin accountability feature ledger drifted for {name}")
        stats = {
            "element_count": len(features),
            "represented_element_count": sum(item["disposition"] == "represented" for item in features),
            "formatting_only_excluded_element_count": sum(item["disposition"] == "formatting-only-excluded" for item in features),
        }
        member_summaries.append(
            {
                "name": name,
                "path": str(member["path"]),
                "kind": str(member["kind"]),
                "bytes": len(source_bytes),
                "sha256": _sha(source_bytes),
                "decision": "include",
                "reason": (
                    "The retained CCEL catalogue member is included to bind collection identity and component scope."
                    if str(member["kind"]) == "catalogue"
                    else "The retained CCEL component member is included in the complete 45-component XML cohort."
                ),
                "main_title": str(member["main_title"]),
                "body_division_count": int(member["body_division_count"]),
                **stats,
                "unsupported_element_count": 0,
                "lexical_events": lexical,
            }
        )
        for key, value in counts.items():
            aggregate_counts[key] += value
        for key, value in census.items():
            aggregate_census[key] += value
        for key, value in lexical.items():
            aggregate_lexical[key] += value
    if feature_position != 583805 or len(observed_features) != 583805:
        raise ValueError("Calvin accountability feature cardinality drifted")
    aggregate_census.update(aggregate_lexical)
    if dict(sorted(aggregate_counts.items())) != profile["element_counts"]:
        raise ValueError("Calvin independent element census drifted")
    if dict(sorted(aggregate_census.items())) != profile["source_census"]:
        raise ValueError("Calvin independent source census drifted")
    if dict(sorted(aggregate_lexical.items())) != profile["lexical_events"]:
        raise ValueError("Calvin independent lexical-event census drifted")
    if accountability.get("members") != member_summaries:
        raise ValueError("Calvin accountability member census drifted")
    del observed_features
    del accountability
    del account_bytes

    candidate_content = (candidate.path / "content.tei.xml").read_bytes()
    try:
        tei = etree.fromstring(
            candidate_content,
            etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("Calvin candidate TEI is not parseable") from exc
    if tei.tag != f"{{{TEI_NS}}}TEI" or tei.get(XML_ID) != "calvin-commentaries-candidate":
        raise ValueError("Calvin candidate TEI root drifted")
    text = tei.find(f"{{{TEI_NS}}}text")
    if text is None:
        raise ValueError("Calvin candidate TEI text is missing")
    front = text.find(f"{{{TEI_NS}}}front")
    body = text.find(f"{{{TEI_NS}}}body")
    if front is None or body is None:
        raise ValueError("Calvin candidate TEI front/body envelope is missing")
    actual_wrappers = [
        node
        for node in tei.iter()
        if isinstance(node.tag, str)
        and etree.QName(node).localname == "div"
        and node.get("type") == "source-member"
    ]
    if len(actual_wrappers) != 46:
        raise ValueError("Calvin source-member wrapper cardinality drifted")
    front_wrappers = [
        node for node in front if isinstance(node.tag, str) and node.get("type") == "source-member"
    ]
    body_wrappers = [
        node for node in body if isinstance(node.tag, str) and node.get("type") == "source-member"
    ]
    if len(front_wrappers) != 1 or len(body_wrappers) != 45:
        raise ValueError("Calvin source-member front/body partition drifted")
    expected_names = [str(item["name"]) for item in profile_members]
    actual_names = [node.get("n") for node in front_wrappers + body_wrappers]
    if actual_names != expected_names:
        raise ValueError("Calvin source-member order drifted")
    for index, member in enumerate(profile_members):
        if not isinstance(member, Mapping):
            raise ValueError("Calvin profile member record is invalid")
        name = str(member["name"])
        source_root = _parse(source_manifest.authority_path(name).read_bytes())
        expected_features = _expected_features(name, source_root, 1 + sum(
            int(item.get("element_count", 0))
            for item in member_summaries[:index]
        ))
        expected_represented = [
            item for item in expected_features if item["disposition"] == "represented"
        ]
        wrapper = (front_wrappers + body_wrappers)[index]
        if wrapper.get("corresp") != _source_uri(name, str(expected_features[0]["source_selector"])):
            raise ValueError(f"Calvin wrapper source binding drifted for {name}")
        if wrapper.get(XML_ID) != str(expected_features[0]["feature_id"]):
            raise ValueError(f"Calvin wrapper feature binding drifted for {name}")
        actual_nodes = [node for node in wrapper.iter() if isinstance(node.tag, str) and node.get("corresp") is not None]
        if len(actual_nodes) != len(expected_represented):
            raise ValueError(f"Calvin mapped selector count drifted for {name}")
        represented_sources = [
            node
            for node in source_root.iter()
            if isinstance(node.tag, str) and not _is_formatting(node)
        ]
        if len(represented_sources) != len(expected_represented):
            raise ValueError(f"Calvin represented source count drifted for {name}")
        expected_targets = list(zip(expected_represented, represented_sources, strict=True))
        for actual_node, (feature, source_node) in zip(actual_nodes, expected_targets, strict=True):
            if (
                actual_node.get("corresp") != _source_uri(name, str(feature["source_selector"]))
                or actual_node.get(XML_ID) != feature["feature_id"]
                or etree.QName(actual_node).localname != _target_local(source_node)
            ):
                raise ValueError(f"Calvin mapped selector or target drifted for {name}")
        if _candidate_stream(wrapper) != _source_stream(source_root):
            raise ValueError(f"Calvin mapped source text stream drifted for {name}")
    for node in tei.iter():
        if node.get("corresp") is not None and not any(
            ancestor in actual_wrappers for ancestor in node.iterancestors()
        ) and node not in actual_wrappers:
            raise ValueError("Calvin TEI contains an unbound corresp node")
    if not compiled_schema().validate(etree.ElementTree(tei)):
        raise ValueError("Calvin candidate fails TEI P5 schema validation")

    provenance = policy.get("provenance")
    unresolved = policy.get("unresolved")
    if not isinstance(provenance, dict) or not isinstance(unresolved, list):
        raise ValueError("Calvin policy provenance or unresolved ledger is invalid")
    if _strict_json((candidate.path / "provenance.json").read_bytes(), "Calvin provenance") != provenance:
        raise ValueError("Calvin provenance drifted")
    expected_unresolved = b"".join(_canonical(item) for item in unresolved)
    if (candidate.path / "unresolved.jsonl").read_bytes() != expected_unresolved:
        raise ValueError("Calvin unresolved ledger drifted")
    if (candidate.path / "README.source.md").read_bytes() != source_manifest.authority_path(README_AUTHORITY).read_bytes():
        raise ValueError("Calvin source README drifted")
    converter = source_manifest.record.get("converter")
    validator = source_manifest.record.get("validator")
    if not isinstance(converter, Mapping) or not isinstance(validator, Mapping):
        raise ValueError("Calvin callable bindings are invalid")
    producer_path = root / str(converter["implementation_path"])
    if source_manifest.record.get("producer_import_closure_sha256") != _closure_digest(root, producer_path):
        raise ValueError("Calvin producer import closure drifted")
    oracle_path = root / str(validator["implementation_path"])
    oracle_closure = _closure_digest(root, oracle_path)
    if oracle_closure != validator.get("import_closure_sha256"):
        raise ValueError("Calvin oracle import closure drifted")
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=oracle_closure,
        source_sha256=str(profile["source_member_set_sha256"]),
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
