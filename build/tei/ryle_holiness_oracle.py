"""Independent source-led oracle for the retained Ryle Holiness witness."""

from __future__ import annotations

import ast
import base64
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping
from urllib.parse import quote

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-ryle-holiness-independent-source-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
FORMAT_ONLY = frozenset({"style", "selector", "property", "colgroup", "col"})
SAFE_XML_ENTITIES = frozenset({"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"})


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


def _assert_exact(observed: object, expected: object, label: str, path: str = "$") -> None:
    if type(observed) is not type(expected):
        raise ValueError(f"{label} JSON type mutation at {path}")
    if isinstance(expected, dict):
        if set(observed) != set(expected):  # type: ignore[arg-type]
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


def _exact_json(content: bytes, expected: dict[str, object], label: str) -> dict[str, object]:
    observed = _strict_json(content, label)
    _assert_exact(observed, expected, label)
    if content != _canonical(expected):
        raise ValueError(f"{label} is not canonical")
    return observed


def _replace_entity(match: re.Match[str]) -> str:
    entity = match.group(0)
    if entity in SAFE_XML_ENTITIES:
        return entity
    unescaped = html.unescape(entity)
    if unescaped == entity:
        raise ValueError(f"unmapped named XML entity {entity!r}")
    return unescaped


def _parse(content: bytes) -> etree._Element:
    text = content.decode("utf-8")
    text = re.sub(r"<!DOCTYPE\s[\s\S]*?>", "", text, flags=re.IGNORECASE)
    prepared = re.sub(r"&[A-Za-z][A-Za-z0-9]*;", _replace_entity, text).encode("utf-8")
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        huge_tree=True,
        remove_comments=False,
        remove_pis=False,
    )
    try:
        return etree.fromstring(prepared, parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("retained Ryle Holiness source is not independently parseable") from exc


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _selector(node: etree._Element) -> str:
    parent = node.getparent()
    if parent is None:
        return f"/{_local(node)}[1]"
    peers = [child for child in parent if isinstance(child.tag, str) and child.tag == node.tag]
    return f"{_selector(parent)}/{_local(node)}[{peers.index(node) + 1}]"


def _features(root: etree._Element) -> list[dict[str, object]]:
    elements = [node for node in root.iter() if isinstance(node.tag, str)]
    rows: list[dict[str, object]] = []
    for ordinal, element in enumerate(elements, 1):
        parent = element.getparent()
        siblings = (
            [child for child in parent if isinstance(child.tag, str)]
            if parent is not None
            else [element]
        )
        rows.append(
            {
                "feature_id": f"ryle-holiness-feature-{ordinal:05d}",
                "source_selector": _selector(element),
                "source_qname": str(element.tag),
                "source_attributes": [
                    {"qname": str(name), "value": value}
                    for name, value in element.attrib.items()
                ],
                "source_direct_text": element.text or "",
                "source_tail_text": element.tail or "",
                "source_parent_selector": _selector(parent) if parent is not None else None,
                "source_child_ordinal": siblings.index(element) + 1,
                "disposition": (
                    "formatting-only-excluded"
                    if _local(element) in FORMAT_ONLY
                    else "represented"
                ),
            }
        )
    return rows


def _census(root: etree._Element) -> tuple[dict[str, int], dict[str, int]]:
    elements = [node for node in root.iter() if isinstance(node.tag, str)]
    counts = Counter(_local(node) for node in elements)
    counts.setdefault("sup", 0)
    return (
        dict(sorted(counts.items())),
        {
            "elements": len(elements),
            "attributes": sum(len(node.attrib) for node in elements),
            "text_nodes": sum(node.text is not None for node in elements),
            "tail_nodes": sum(node.tail is not None for node in elements),
            "characters": sum(len(node.text or "") + len(node.tail or "") for node in elements),
        },
    )


def _lexical_events(root: etree._Element) -> dict[str, int]:
    tree = root.getroottree()
    return {
        "comments": len(tree.xpath("//comment()")),
        "processing_instructions": len(tree.xpath("//processing-instruction()")),
        "doctype_declarations": 1 if tree.docinfo.doctype else 0,
    }


def _first_text(root: etree._Element, localname: str) -> str:
    for node in root.iter():
        if isinstance(node.tag, str) and _local(node) == localname:
            return "".join(node.itertext()).strip()
    return ""


def _expected_accountability(
    source_manifest: SourceManifest,
    source_bytes: bytes,
    root: etree._Element,
    features: list[dict[str, object]],
) -> dict[str, object]:
    counts, census = _census(root)
    formatting = dict(
        sorted(
            Counter(
                str(row["source_qname"])
                for row in features
                if row["disposition"] == "formatting-only-excluded"
            ).items()
        )
    )
    return {
        "contract": "ocd-ryle-holiness-source-accountability-v1",
        "source_id": str(source_manifest.record["source_id"]),
        "source_path": "raw/ccel/ryle/holiness.xml",
        "source_bytes": len(source_bytes),
        "source_sha256": _sha(source_bytes),
        "source_census": census,
        "element_counts": counts,
        "lexical_events": _lexical_events(root),
        "member_census": {"included": 1, "excluded": 0, "retained_family_total": 1},
        "features": features,
        "represented_element_count": sum(row["disposition"] == "represented" for row in features),
        "formatting_only_excluded_element_count": sum(
            row["disposition"] == "formatting-only-excluded" for row in features
        ),
        "unsupported_element_count": 0,
        "formatting_only_tags": formatting,
    }


def _heading_is_post_content(source: etree._Element) -> bool:
    parent = source.getparent()
    if parent is None:
        return False
    for sibling in parent:
        if sibling is source:
            break
        if not isinstance(sibling.tag, str):
            continue
        sibling_name = _local(sibling)
        if sibling_name in FORMAT_ONLY or sibling_name in {"pb", "hr"}:
            continue
        if sibling_name in {"h1", "h2", "h3", "h4"}:
            continue
        return True
    return False


def _target_local(source: etree._Element) -> str:
    name = _local(source)
    if name in {"div", "div1", "div2"}:
        if (
            name == "div"
            and (source.get("class") or "").casefold() != "index"
            and any(_local(child) == "verse" for child in source.iterdescendants())
        ):
            return "ab"
        return "div"
    if name in {"h1", "h2", "h3", "h4"}:
        return "p" if _heading_is_post_content(source) else "head"
    if name == "p":
        return "p"
    if name == "i":
        return "hi"
    if name == "br":
        return "lb"
    if name == "scripRef":
        return "ref"
    if name in {"note", "pb", "table", "tr", "td", "th", "l"}:
        return {"tr": "row", "td": "cell", "th": "cell"}.get(name, name)
    if name == "span":
        if (source.get("class") or "").casefold() == "sc":
            return "hi"
        if source.get("lang"):
            return "foreign"
        return "seg"
    if name == "sup":
        return "hi"
    if name == "a":
        return "ref"
    if name == "verse":
        return "lg"
    if name == "hr":
        return "milestone"
    if name == "insertIndex":
        return "anchor"
    raise ValueError(f"unsupported retained source element <{name}>")


def _expected_targets(root: etree._Element) -> list[tuple[str, str]]:
    expected: list[tuple[str, str]] = []
    for top in root.xpath("./ThML.body/*"):
        if not isinstance(top.tag, str):
            continue
        for node in top.iter():
            if not isinstance(node.tag, str) or _local(node) in FORMAT_ONLY:
                continue
            expected.append(
                ("urn:source-xpath:" + quote(_selector(node), safe=""), _target_local(node))
            )
    return expected


def _actual_targets(tei: etree._Element) -> list[tuple[str, str]]:
    text = tei.find(f"{{{TEI_NS}}}text")
    if text is None:
        raise ValueError("candidate TEI has no text element")
    result: list[tuple[str, str]] = []
    for node in text.iter():
        if not isinstance(node.tag, str):
            continue
        if any(
            ancestor.get(XML_ID) == "ryle-holiness-source-ledger"
            for ancestor in node.iterancestors()
        ):
            continue
        corresp = node.get("corresp")
        if corresp is not None:
            result.append((corresp, etree.QName(node).localname))
    return result


def _source_stream(node: etree._Element) -> str:
    parts: list[str] = []
    if _local(node) not in FORMAT_ONLY:
        parts.append(node.text or "")
    for child in node:
        if isinstance(child.tag, str) and _local(child) not in FORMAT_ONLY:
            parts.append(_source_stream(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _candidate_stream(node: etree._Element) -> str:
    if node.get(XML_ID) == "ryle-holiness-source-ledger":
        return ""
    parts = [node.text or ""]
    for child in node:
        if isinstance(child.tag, str) and child.get(XML_ID) == "ryle-holiness-source-ledger":
            continue
        parts.append(_candidate_stream(child) if isinstance(child.tag, str) else "")
        parts.append(child.tail or "")
    return "".join(parts)


def _ledger_signature(tei: etree._Element) -> list[tuple[object, ...]]:
    ledgers = [
        node
        for node in tei.iter()
        if isinstance(node.tag, str)
        and etree.QName(node).localname == "div"
        and node.get(XML_ID) == "ryle-holiness-source-ledger"
    ]
    if len(ledgers) != 1:
        raise ValueError("Ryle Holiness source ledger cardinality mutation")
    rows: list[tuple[object, ...]] = []
    for carrier in ledgers[0]:
        if not isinstance(carrier.tag, str) or etree.QName(carrier).localname != "ab":
            continue
        segments = {
            child.get("type"): child.text or ""
            for child in carrier
            if isinstance(child.tag, str) and etree.QName(child).localname == "seg"
        }
        rows.append(
            (
                carrier.get("corresp"),
                carrier.get("subtype"),
                carrier.get("n"),
                segments.get("direct-text"),
                segments.get("tail-text"),
                segments.get("source-attributes"),
            )
        )
    return rows


def _expected_ledger_signature(features: list[dict[str, object]]) -> list[tuple[object, ...]]:
    return [
        (
            "urn:source-xpath:" + quote(str(row["source_selector"]), safe=""),
            row["source_qname"],
            str(row["source_child_ordinal"]),
            row["source_direct_text"],
            row["source_tail_text"],
            _canonical(row["source_attributes"]).decode("utf-8").rstrip("\n"),
        )
        for row in features
    ]


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
            raise ValueError("oracle relative import escapes repository")
        base = ".".join(package_parts[: len(package_parts) - node.level + 1])
        if node.module:
            base = f"{base}.{node.module}" if base else node.module
    else:
        base = node.module or ""
    return (base, *(f"{base}.{alias.name}" for alias in node.names)) if base else ()


def _closure(root: Path, policy: Mapping[str, object]) -> tuple[dict[str, str], ...]:
    forbidden = tuple(str(item) for item in policy.get("forbidden_oracle_imports", ()))
    pending = [Path(__file__).resolve()]
    seen: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {
                "eval",
                "exec",
                "__import__",
            }:
                raise ValueError("oracle closure contains dynamic execution")
            for name in _import_names(root, path, node):
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    raise ValueError(f"forbidden oracle import {name}")
                dependency = _local_module(root, name)
                if dependency is not None and dependency not in seen:
                    pending.append(dependency)
    return tuple(
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha(path.read_bytes()),
        }
        for path in sorted(seen, key=lambda item: item.relative_to(root).as_posix())
    )


def _closure_digest(root: Path, policy: Mapping[str, object]) -> str:
    return _sha(_canonical(_closure(root, policy)))


def _candidate_manifest(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    record = _strict_json((candidate.path / "manifest.json").read_bytes(), "candidate manifest")
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
    if record != expected or (candidate.path / "manifest.json").read_bytes() != _canonical(expected):
        raise ValueError("candidate manifest binding mutation")
    return record


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict_json(profile_bytes, "Ryle Holiness profile")
    policy = _strict_json(policy_bytes, "Ryle Holiness policy")
    if (
        profile.get("contract") != "ocd-ryle-holiness-profile-v1"
        or profile.get("source_bytes") != 1302437
        or profile.get("source_sha256") != "20f9c4a6eb9109c5981a37b580376ed02f1bc93ac98dd047ac6d0578ff3521c8"
        or policy.get("contract") != "ocd-ryle-holiness-validation-policy-v1"
        or policy.get("required_source_members") != 1
        or policy.get("required_source_element_count") != 5698
    ):
        raise ValueError("Ryle Holiness profile or policy mutation")
    _candidate_manifest(source_manifest, candidate)

    authorities = source_manifest.record.get("authorities")
    primary = [item for item in authorities if item.get("role") == "primary-source"] if isinstance(authorities, tuple) else []
    if len(primary) != 1 or primary[0].get("name") != "retained-ryle-holiness":
        raise ValueError("Ryle Holiness primary authority cardinality mutation")
    source_bytes = source_manifest.authority_path("retained-ryle-holiness").read_bytes()
    source_sha256 = _sha(source_bytes)
    if len(source_bytes) != profile["source_bytes"] or source_sha256 != profile["source_sha256"]:
        raise ValueError("Ryle Holiness source authority mutation")
    config = _strict_json(source_manifest.authority_path("work-config").read_bytes(), "work config")
    if config.get("resource_id") != "ryle-holiness" or config.get("source_hash") != f"sha256:{source_sha256}":
        raise ValueError("Ryle Holiness work config binding mutation")

    source_root = _parse(source_bytes)
    if _local(source_root) != "ThML" or [node.get("id") for node in source_root.xpath("./ThML.body/*")] != ["i", "ii", "iii", "iv"]:
        raise ValueError("Ryle Holiness retained envelope mutation")
    if _first_text(source_root, "DC.Title") != profile["source_identity_evidence"]["header_title"]:
        raise ValueError("Ryle Holiness title evidence mutation")
    if _first_text(source_root, "DC.Creator") != profile["source_identity_evidence"]["header_author"]:
        raise ValueError("Ryle Holiness author evidence mutation")
    if _first_text(source_root, "published") != profile["source_identity_evidence"]["print_source"]:
        raise ValueError("Ryle Holiness print-source evidence mutation")
    if "THIS EDITION 1952" not in "".join(source_root.itertext()):
        raise ValueError("Ryle Holiness title-page edition evidence missing")

    counts, census = _census(source_root)
    if counts != profile["element_counts"] or census != profile["source_census"]:
        raise ValueError("Ryle Holiness independent source census mutation")
    if _lexical_events(source_root) != profile["lexical_events"]:
        raise ValueError("Ryle Holiness lexical event census mutation")
    features = _features(source_root)
    if len(features) != profile["source_census"]["elements"]:
        raise ValueError("Ryle Holiness feature inventory mutation")
    expected_accountability = _expected_accountability(source_manifest, source_bytes, source_root, features)
    observed_accountability = _exact_json(
        candidate.member_bytes("source-accountability.json"),
        expected_accountability,
        "Ryle Holiness accountability",
    )
    schema = _strict_json(
        source_manifest.authority_path("source-accountability-schema").read_bytes(),
        "Ryle Holiness accountability schema",
    )
    schema_errors = sorted(Draft202012Validator(schema).iter_errors(observed_accountability), key=str)
    if schema_errors:
        raise ValueError(f"Ryle Holiness accountability schema failure: {schema_errors[0].message}")

    content = candidate.member_bytes("content.tei.xml")
    try:
        tei = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    except etree.XMLSyntaxError as exc:
        raise ValueError("Ryle Holiness candidate TEI is not parseable") from exc
    if tei.tag != f"{{{TEI_NS}}}TEI":
        raise ValueError("Ryle Holiness candidate TEI root mutation")
    raw_notes = [
        node
        for node in tei.iter()
        if isinstance(node.tag, str) and etree.QName(node).localname == "note" and node.get("type") == "exact-retained-source-bytes"
    ]
    if len(raw_notes) != 1 or raw_notes[0].text != base64.b64encode(source_bytes).decode("ascii"):
        raise ValueError("Ryle Holiness exact embedded source bytes mutation")
    if _actual_targets(tei) != _expected_targets(source_root):
        raise ValueError("Ryle Holiness mapped source selector or semantic-tag mutation")
    if _ledger_signature(tei) != _expected_ledger_signature(features):
        raise ValueError("Ryle Holiness source ledger mutation")
    text = tei.find(f"{{{TEI_NS}}}text")
    if text is None:
        raise ValueError("Ryle Holiness candidate text missing")
    actual_stream = "".join(_candidate_stream(section) for section in text if isinstance(section.tag, str))
    expected_stream = "".join(
        _source_stream(section)
        for section in source_root.xpath("./ThML.body/*")
        if isinstance(section.tag, str)
    )
    if actual_stream != expected_stream:
        raise ValueError("Ryle Holiness mapped source text mutation")
    if not compiled_schema().validate(etree.ElementTree(tei)):
        raise ValueError("Ryle Holiness candidate fails TEI P5 validation")

    provenance = policy.get("provenance")
    unresolved = policy.get("unresolved")
    if not isinstance(provenance, dict) or not isinstance(unresolved, list):
        raise ValueError("Ryle Holiness policy ledger is invalid")
    _exact_json(candidate.member_bytes("provenance.json"), provenance, "Ryle Holiness provenance")
    expected_unresolved = b"".join(_canonical(item) for item in unresolved)
    if candidate.member_bytes("unresolved.jsonl") != expected_unresolved:
        raise ValueError("Ryle Holiness unresolved ledger mutation")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-local-readme").read_bytes():
        raise ValueError("Ryle Holiness source README mutation")

    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=_closure_digest(root, policy),
        source_sha256=source_sha256,
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
