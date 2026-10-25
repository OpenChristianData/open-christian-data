"""Producer-independent validation for the LIB-031 reconstruction."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-lib031-source-to-tei-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
PROFILE_AUTHORITY = "reconstruction-profile"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _json(path: Path, label: str) -> dict[str, object]:
    return _json_bytes(path.read_bytes(), label)


def _json_bytes(content: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = item
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _retained_members(
    manifest: SourceManifest, profile: Mapping[str, object]
) -> tuple[dict[str, object], ...]:
    source_set = _json(
        manifest.authority_path("retained-source-set"), "retained source set"
    )
    members = source_set.get("members")
    work_order = profile.get("work_order")
    if (
        set(source_set) != {"contract", "storage", "census", "members"}
        or source_set.get("contract") != "ocd-retained-source-set-v1"
        or source_set.get("census")
        != {
            "included": 10,
            "excluded": 0,
            "basis": "all ten ticket-assigned CCEL ThML witnesses are present, byte-pinned, and suitable for complete ThML.body reconstruction",
        }
        or not isinstance(members, list)
        or not isinstance(work_order, list)
    ):
        raise ValueError("LIB-031 source set or profile is malformed")
    configured_root = os.environ.get("OCD_RETAINED_RAW_ROOT", "").strip()
    root = (
        Path(configured_root) if configured_root else manifest.repository_root / "raw"
    )
    root = root.resolve(strict=True)
    result: list[dict[str, object]] = []
    for expected_id, member in zip(work_order, members, strict=True):
        if (
            not isinstance(member, dict)
            or set(member)
            != {"work_id", "logical_path", "bytes", "sha256", "disposition", "reason"}
            or member.get("work_id") != expected_id
            or type(member.get("bytes")) is not int
            or member.get("disposition") != "include"
            or member.get("reason")
            != "ticket-assigned complete retained CCEL ThML witness"
        ):
            raise ValueError("LIB-031 source member order drifted")
        logical_path = member.get("logical_path")
        if not isinstance(logical_path, str):
            raise ValueError("LIB-031 source logical path is invalid")
        path = (root / logical_path).resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("LIB-031 source escaped retained root") from exc
        content = path.read_bytes()
        if len(content) != member.get("bytes") or _sha(content) != member.get("sha256"):
            raise ValueError(f"LIB-031 source hash drifted: {logical_path}")
        result.append({**member, "resolved_path": path})
    return tuple(result)


def _source_tree(path: Path) -> tuple[etree._ElementTree, etree._Element]:
    tree = etree.parse(
        str(path),
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )
    body = next(
        (
            node
            for node in tree.iter()
            if isinstance(node.tag, str) and _local(node) == "ThML.body"
        ),
        None,
    )
    if body is None:
        raise ValueError(f"LIB-031 source has no ThML.body: {path}")
    return tree, body


def _selector(node: etree._Element, body: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and current is not body:
        parent = current.getparent()
        if parent is None:
            break
        tag = (
            _local(current)
            if isinstance(current.tag, str)
            else ("#comment" if isinstance(current, etree._Comment) else "#pi")
        )
        peers = [
            child
            for child in parent
            if (
                isinstance(child.tag, str)
                and isinstance(current.tag, str)
                and _local(child) == tag
            )
            or (
                isinstance(current, etree._Comment)
                and isinstance(child, etree._Comment)
            )
            or (
                isinstance(current, etree._ProcessingInstruction)
                and isinstance(child, etree._ProcessingInstruction)
            )
        ]
        parts.append(f"{tag}[{peers.index(current) + 1}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _target_tag(tag: str, source: etree._Element | None = None) -> str:
    if tag in {"div1", "div2", "div3", "div4"}:
        return "div"
    if tag == "div":
        return "quote"
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "title"}:
        return "head"
    if tag in {"insertIndex"}:
        return "index"
    if tag in {"colgroup"}:
        return "row"
    if tag in {"col"}:
        return "cell"
    if tag in {"#comment", "#pi"}:
        return "note"
    if tag in {
        "p",
        "i",
        "b",
        "sup",
        "sub",
        "span",
        "a",
        "scripRef",
        "note",
        "pb",
        "br",
        "table",
        "tr",
        "td",
        "th",
        "l",
        "verse",
        "ul",
        "ol",
        "li",
        "hr",
    }:
        mapped = {
            "i": "hi",
            "b": "hi",
            "sup": "hi",
            "sub": "hi",
            "span": "seg",
            "a": "ref",
            "scripRef": "ref",
            "br": "lb",
            "tr": "row",
            "td": "cell",
            "th": "cell",
            "verse": "lg",
            "ul": "list",
            "ol": "list",
            "li": "item",
            "hr": "milestone",
        }.get(tag, tag)
        if tag == "span" and source is not None and source.get("lang"):
            return "foreign"
        return mapped
    mapped = "seg"
    if tag == "span" and source is not None and source.get("lang"):
        mapped = "foreign"
    return mapped


def _contextual_target_tag(source: etree._Element, parent: etree._Element) -> str:
    tag = (
        _local(source)
        if isinstance(source.tag, str)
        else ("#comment" if isinstance(source, etree._Comment) else "#pi")
    )
    target_tag = _target_tag(tag, source if isinstance(source.tag, str) else None)
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "title"}:
        parent_tag = _local(parent) if isinstance(parent.tag, str) else ""
        if parent_tag in {"div", "quote"}:
            return "p"
        if parent_tag not in {"div1", "div2", "div3", "div4"}:
            return "seg"
        if any(
            isinstance(child.tag, str)
            and _local(child) in {"head", "p", "div", "quote"}
            for child in parent
        ):
            return "p"
    return target_tag


def _content_text(target_tag: str, value: str | None) -> str:
    text = value if value is not None else ""
    if target_tag in {"div", "table", "row", "list", "lg", "index"} and text.strip():
        raise ValueError(
            f"LIB-031 cannot place non-whitespace source text directly in TEI {target_tag}"
        )
    return text


def _attributes(source: etree._Element, target_tag: str) -> dict[str, str]:
    tag = _local(source)
    attrs: dict[str, str] = {}
    if source.get("type") and target_tag in {"div", "quote", "seg", "list"}:
        attrs["type"] = source.get("type", "")
    if source.get("n") and target_tag in {"div", "note", "pb", "milestone"}:
        attrs["n"] = source.get("n", "")
    if source.get("class") and target_tag == "hi":
        attrs["rend"] = source.get("class", "")
    if tag == "i":
        attrs["rend"] = "italic"
    elif tag == "b":
        attrs["rend"] = "bold"
    elif tag == "sup":
        attrs["rend"] = "superscript"
    elif tag == "sub":
        attrs["rend"] = "subscript"
    elif tag == "span":
        language = source.get("lang")
        attrs[XML_LANG] = (
            {"EL": "grc", "HE": "he", "LA": "la", "FR": "fr", "DE": "de"}.get(
                language, language.lower()
            )
            if language
            else ""
        )
        if not language:
            attrs["type"] = "thml-span"
    elif tag == "a" and source.get("href"):
        attrs["target"] = source.get("href", "")
    elif tag == "scripRef":
        attrs["type"] = "scripture"
        if source.get("osisRef"):
            attrs["target"] = source.get("osisRef", "")
        if source.get("passage"):
            attrs["cRef"] = source.get("passage", "")
    elif tag == "note" and source.get("place"):
        attrs["place"] = source.get("place", "")
    elif tag in {"td", "th"} and source.get("colspan"):
        attrs["cols"] = source.get("colspan", "")
    elif tag == "hr":
        attrs["unit"] = "horizontal-rule"
    elif tag == "scripture":
        attrs["type"] = "scripture"
    elif tag in {"style", "selector"}:
        attrs["type"] = f"thml-{tag}"
    elif tag in {"h1", "h2", "h3", "h4", "h5", "h6", "title"} and target_tag == "seg":
        attrs["type"] = f"thml-{tag}"
    elif target_tag == "seg":
        attrs["type"] = f"thml-{tag}"
    return {key: value for key, value in attrs.items() if value}


def _expected_body(
    manifest: SourceManifest,
    profile: Mapping[str, object],
    members: tuple[dict[str, object], ...],
) -> tuple[etree._Element, list[dict[str, object]], list[dict[str, object]]]:
    body = etree.Element(
        f"{{{TEI_NS}}}body", {XML_ID: "lib031-body"}, nsmap={None: TEI_NS}
    )
    rows: list[dict[str, object]] = []
    documents: list[dict[str, object]] = []
    serial = 0

    def append(
        source: etree._Element,
        parent: etree._Element,
        source_body: etree._Element,
        work_id: str,
    ) -> None:
        nonlocal serial
        serial += 1
        comment = isinstance(source, etree._Comment)
        pi = isinstance(source, etree._ProcessingInstruction)
        if not isinstance(source.tag, str) and not (comment or pi):
            raise ValueError("LIB-031 source contains an unsupported body node")
        tag = (
            _local(source)
            if isinstance(source.tag, str)
            else ("#comment" if comment else "#pi")
        )
        target_tag = _contextual_target_tag(source, parent)
        target_id = f"lib031-f-{serial:07d}"
        attrs = {XML_ID: target_id}
        if comment:
            attrs["type"] = "thml-comment"
        elif pi:
            attrs["type"] = "thml-processing-instruction"
        else:
            attrs.update(_attributes(source, target_tag))
        target = etree.Element(f"{{{TEI_NS}}}{target_tag}", attrs)
        title = (
            source.get("title")
            if isinstance(source.tag, str) and tag.startswith("div")
            else None
        )
        has_heading_child = (
            any(
                isinstance(child.tag, str)
                and _local(child) in {"h1", "h2", "h3", "h4", "h5", "h6"}
                for child in source
            )
            if isinstance(source.tag, str)
            else False
        )
        if title and not has_heading_child:
            head = etree.Element(f"{{{TEI_NS}}}head")
            head.text = title
            target.append(head)
            head.tail = _content_text(target_tag, source.text)
        else:
            target.text = _content_text(target_tag, source.text)
        child_ordinal = len(parent) + 1
        parent.append(target)
        parent_xml_id = parent.get(XML_ID) or ""
        parent_feature_id = next(
            (
                str(previous["feature_id"])
                for previous in reversed(rows)
                if previous["tei_xml_id"] == parent_xml_id
            ),
            None,
        )
        source_attributes = dict(source.attrib) if isinstance(source.tag, str) else {}
        rows.append(
            {
                "feature_id": f"lib031-feature-{serial:07d}",
                "work_id": work_id,
                "source_selector": _selector(source, source_body),
                "source_tag": tag,
                "source_xml_id": source.get("id"),
                "attributes": source_attributes,
                "direct_text": source.text or "",
                "tail_text": source.tail or "",
                "direct_text_sha256": _sha((source.text or "").encode("utf-8")),
                "tail_text_sha256": _sha((source.tail or "").encode("utf-8")),
                "tei_tag": target_tag,
                "tei_xml_id": target_id,
                "tei_parent_id": parent_xml_id,
                "tei_child_ordinal": child_ordinal,
                "tei_attributes": {
                    (
                        "xml:id"
                        if key == XML_ID
                        else "xml:lang"
                        if key == XML_LANG
                        else key
                    ): value
                    for key, value in target.attrib.items()
                },
                "attribute_dispositions": [
                    {
                        "source_attribute": key,
                        "source_value": value,
                        "destination": (
                            "@xml:id"
                            if key == "id"
                            else "projected-TEI-attribute"
                            if key
                            in {
                                "type",
                                "n",
                                "class",
                                "lang",
                                "href",
                                "osisRef",
                                "passage",
                                "place",
                                "colspan",
                            }
                            else "source-accountability"
                        ),
                    }
                    for key, value in source_attributes.items()
                ],
                "disposition": "represented",
                "tei_selector": f"#{target_id}",
                "parent_feature_id": parent_feature_id,
                "source_title_head": title,
            }
        )
        for child in source:
            append(child, target, source_body, work_id)
            target[-1].tail = _content_text(target_tag, child.tail)

    for member in members:
        work_id = str(member["work_id"])
        metadata = next(
            item
            for item in profile["works"]
            if isinstance(item, dict) and item["work_id"] == work_id
        )
        tree, source_body = _source_tree(member["resolved_path"])
        work = etree.Element(f"{{{TEI_NS}}}div", {XML_ID: work_id, "type": "work"})
        head = etree.Element(f"{{{TEI_NS}}}head")
        head.text = str(metadata["title"])
        work.append(head)
        head.tail = _content_text("div", source_body.text)
        body.append(work)
        before = len(rows)
        for child in source_body:
            append(child, work, source_body, work_id)
            work[-1].tail = _content_text("div", child.tail)
        documents.append(
            {
                "work_id": work_id,
                "logical_path": member["logical_path"],
                "bytes": member["bytes"],
                "sha256": member["sha256"],
                "feature_count": len(rows) - before,
                "body_direct_text": source_body.text or "",
                "body_direct_text_sha256": _sha(
                    (source_body.text or "").encode("utf-8")
                ),
                "document_accounting": {
                    "body_element_count": sum(
                        1 for node in source_body.iter() if isinstance(node.tag, str)
                    )
                    - 1,
                    "body_attribute_count": sum(
                        len(node.attrib)
                        for node in source_body.iter()
                        if isinstance(node.tag, str)
                    ),
                    "comment_count": sum(
                        1 for node in tree.iter() if isinstance(node, etree._Comment)
                    ),
                    "processing_instruction_count": sum(
                        1
                        for node in tree.iter()
                        if isinstance(node, etree._ProcessingInstruction)
                    ),
                },
                "disposition": "represented-as-one-work-division",
            }
        )
    return body, rows, documents


def _closure_module_path(root: Path, module: str) -> Path | None:
    base = root.joinpath(*module.split("."))
    module_path = base.with_suffix(".py")
    if module_path.is_file():
        return module_path.resolve()
    package_path = base / "__init__.py"
    return package_path.resolve() if package_path.is_file() else None


def _resolved_import_name(
    module: str, module_path: Path, imported: str | None, level: int
) -> str:
    if level == 0:
        return imported or ""
    package = module if module_path.name == "__init__.py" else module.rpartition(".")[0]
    parts = package.split(".") if package else []
    if level - 1 > len(parts):
        return ""
    base = parts[: len(parts) - (level - 1)]
    if imported:
        base.extend(imported.split("."))
    return ".".join(base)


def _closure_paths(root: Path, policy: Mapping[str, object]) -> tuple[Path, ...]:
    forbidden = tuple(policy.get("forbidden_oracle_imports", []))
    pending = ["build.tei.lib031_oracle"]
    modules: dict[str, Path] = {}
    while pending:
        module = pending.pop()
        if module in modules:
            continue
        path = _closure_module_path(root, module)
        if path is None:
            continue
        modules[module] = path
        parts = module.split(".")
        package_parts = parts if path.name == "__init__.py" else parts[:-1]
        for index in range(1, len(package_parts) + 1):
            package = ".".join(package_parts[:index])
            if package not in modules:
                pending.append(package)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = _resolved_import_name(module, path, node.module, node.level)
                if base:
                    names.append(base)
                    names.extend(
                        f"{base}.{alias.name}"
                        for alias in node.names
                        if alias.name != "*"
                    )
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "eval", "exec", "import_module"}
            ):
                raise ValueError("LIB-031 oracle closure contains dynamic import")
            for name in names:
                if any(
                    name == prefix or name.startswith(prefix + ".")
                    for prefix in forbidden
                ):
                    raise ValueError(f"LIB-031 oracle imports forbidden module {name}")
                if _closure_module_path(root, name) is not None:
                    pending.append(name)
    return tuple(sorted(set(modules.values()), key=lambda item: item.as_posix()))


def _closure_digest(root: Path, policy: Mapping[str, object]) -> str:
    return _sha(
        _canonical(
            [
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": _sha(path.read_bytes()),
                }
                for path in _closure_paths(root, policy)
            ]
        )
    )


def _primary_source_digest(source_manifest: SourceManifest) -> str:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("LIB-031 source authorities are invalid")
    records = sorted(
        (
            {
                "name": item["name"],
                "path": item["path"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
            for item in authorities
            if isinstance(item, Mapping) and item.get("role") == "primary-source"
        ),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    if len(records) != 10:
        raise ValueError(
            "LIB-031 requires exactly ten direct primary-source authorities"
        )
    return _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": records})
    )


def _same_tree(left: etree._Element, right: etree._Element) -> bool:
    if left.tag != right.tag or dict(left.attrib) != dict(right.attrib):
        return False
    if (left.text or "") != (right.text or "") or (left.tail or "") != (
        right.tail or ""
    ):
        return False
    if len(left) != len(right):
        return False
    return all(_same_tree(a, b) for a, b in zip(left, right, strict=True))


def _strict_equal(actual: object, expected: object, label: str) -> None:
    if type(actual) is not type(expected):
        raise ValueError(
            f"{label} type drifted: {type(actual).__name__} != {type(expected).__name__}"
        )
    if isinstance(expected, dict):
        if set(actual) != set(expected):
            raise ValueError(f"{label} keys drifted")
        for key, expected_value in expected.items():
            _strict_equal(actual[key], expected_value, f"{label}.{key}")
        return
    if isinstance(expected, list):
        if len(actual) != len(expected):
            raise ValueError(f"{label} length drifted")
        for index, (actual_value, expected_value) in enumerate(
            zip(actual, expected, strict=True)
        ):
            _strict_equal(actual_value, expected_value, f"{label}[{index}]")
        return
    if actual != expected:
        raise ValueError(f"{label} value drifted")


def _validate_schema(
    instance: object, schema: Mapping[str, object], label: str
) -> None:
    try:
        Draft202012Validator(schema).validate(instance)
    except ValidationError as exc:
        raise ValueError(f"{label} schema failure: {exc.message}") from exc


def _expected_tei(body: etree._Element, source_set_digest: str) -> etree._Element:
    def element(
        name: str,
        attributes: dict[str, str] | None = None,
        text: str | None = None,
    ) -> etree._Element:
        node = etree.Element(
            f"{{{TEI_NS}}}{name}",
            attributes or {},
            nsmap={None: TEI_NS} if name == "TEI" else None,
        )
        node.text = text
        return node

    root = element("TEI", {XML_ID: "lib031-candidate"})
    header = element("teiHeader")
    file_desc = element("fileDesc")
    title_stmt = element("titleStmt")
    title_stmt.append(
        element(
            "title", text="LIB-031 Bounds, Finney, and Pascal faithful TEI candidate"
        )
    )
    title_stmt.append(element("author", text="Multiple authors"))
    responsibility = element("respStmt")
    responsibility.append(element("resp", text="electronic source host"))
    responsibility.append(element("name", text="Christian Classics Ethereal Library"))
    title_stmt.append(responsibility)
    file_desc.append(title_stmt)
    publication = element("publicationStmt")
    publication.append(element("publisher", text="Open Christian Data"))
    availability = element("availability", {"status": "restricted"})
    availability.append(
        element(
            "p",
            text=(
                "Local source configurations claim public-domain status for the underlying works. "
                "CCEL permits parsing its ThML; attribution is retained here as source evidence. "
                "Human rights, textual, edition, and publication decisions remain unresolved."
            ),
        )
    )
    publication.append(availability)
    file_desc.append(publication)
    source_desc = element("sourceDesc")
    bibliography = element("bibl")
    bibliography.append(element("ptr", {"target": "https://www.ccel.org/"}))
    bibliography.append(element("idno", {"type": "sha256"}, source_set_digest))
    bibliography.append(
        element(
            "note",
            {"type": "print-source"},
            "CCEL ThML witnesses; print-edition collation not performed",
        )
    )
    source_desc.append(bibliography)
    file_desc.append(source_desc)
    header.append(file_desc)
    root.append(header)
    text = element("text")
    text.append(body)
    root.append(text)
    return root


def _expected_evidence(
    source_manifest: SourceManifest,
    profile: Mapping[str, object],
    members: tuple[dict[str, object], ...],
    rows: list[dict[str, object]],
    documents: list[dict[str, object]],
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]], str]:
    member_records = [
        {
            "work_id": str(item["work_id"]),
            "path": str(item["logical_path"]),
            "bytes": int(item["bytes"]),
            "sha256": str(item["sha256"]),
        }
        for item in members
    ]
    source_set_digest = _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": member_records})
    )
    feature_counts: dict[str, int] = {}
    for row in rows:
        tag = str(row["source_tag"])
        feature_counts[tag] = feature_counts.get(tag, 0) + 1
    accountability = {
        "contract": "ocd-lib031-source-accountability-v1",
        "schema": "lib031.source-accountability.schema.json",
        "profile_id": profile["profile_id"],
        "source_scope": "each retained ThML.body represented in declared work order",
        "source_reference_authority": {
            "path": source_manifest.path.relative_to(
                source_manifest.repository_root
            ).as_posix(),
            "authority": "retained-source-set",
            "sha256": _sha(
                source_manifest.authority_path("retained-source-set").read_bytes()
            ),
        },
        "source_members": member_records,
        "document_accounting": documents,
        "work_count": len(documents),
        "feature_count": len(rows),
        "attribute_count": sum(len(row["attributes"]) for row in rows),
        "feature_counts": feature_counts,
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "crosswalk": rows,
    }
    profile_works = profile.get("works")
    if not isinstance(profile_works, list):
        raise ValueError("LIB-031 profile works are invalid")
    works_by_id = {
        item["work_id"]: item for item in profile_works if isinstance(item, dict)
    }
    provenance = {
        "contract": "ocd-lib031-provenance-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source_member_set_sha256": source_set_digest,
        "source_root": "durable retained raw root resolved through OCD_RETAINED_RAW_ROOT or approved raw topology",
        "works": [
            {
                **works_by_id[str(member["work_id"])],
                "source_sha256": member["sha256"],
                "accepted_ir": "not_accepted",
                "human_review": "required",
                "publication": "not_ready",
            }
            for member in members
        ],
        "rights": {
            "underlying_work_claim": "local-config-public-domain",
            "electronic_host_terms": "CCEL parsing permission retained as evidence",
            "worldwide_rights_decision": "unresolved",
        },
        "canonical_data_written": False,
        "canonical_ir_written": False,
    }
    unresolved = [
        {
            "id": "lib031-print-edition-collation",
            "scope": "all-ten-works",
            "status": "unresolved",
            "question": "Does each retained CCEL ThML witness match the intended print edition?",
            "evidence": "No print collation was performed; the candidate is bound to the retained source bytes.",
        },
        {
            "id": "lib031-human-acceptance-and-publication",
            "scope": "all-ten-works",
            "status": "unresolved",
            "question": "Will a maintainer accept the candidate text, rights basis, and publication status?",
            "evidence": "Technical reconstruction and validation are not human acceptance or publication authorization.",
        },
    ]
    return accountability, provenance, unresolved, source_set_digest


def _expected_readme_bytes() -> bytes:
    """Return the independently specified source-attribution member bytes."""
    return (
        "# LIB-031 faithful TEI candidate\n\n"
        "This is a nonaccepted candidate reconstructed deterministically from the ten retained CCEL ThML members declared by the source-set authority. "
        "The source files remain outside the repository's canonical data and are read through the durable retained raw root. "
        "Every source-body element is represented in `source-accountability.json`; unsupported ThML names use an explicit `seg @type` fallback rather than silent omission.\n\n"
        "The electronic witnesses are sourced via [CCEL.org](https://www.ccel.org/). Local configs claim public-domain status for the underlying works, while CCEL parsing terms and worldwide rights remain evidence for human review. No canonical data, IR, acceptance, or publication state was written.\n"
    ).encode("utf-8")


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    profile_path = source_manifest.authority_path(PROFILE_AUTHORITY)
    policy_path = source_manifest.authority_path("validation-policy")
    schema_path = source_manifest.authority_path("source-accountability-schema")
    profile = _json(profile_path, "LIB-031 profile")
    policy = _json(policy_path, "LIB-031 policy")
    manifest_bytes = (candidate.path / "manifest.json").read_bytes()
    manifest_record = _json_bytes(manifest_bytes, "LIB-031 candidate manifest")
    package_schema_path = source_manifest.authority_path("candidate-package-schema")
    package_schema = _json(package_schema_path, "candidate package schema")
    _validate_schema(manifest_record, package_schema, "LIB-031 candidate manifest")
    expected_manifest = {
        "contract": "ocd-candidate-package-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source_manifest": {
            "path": source_manifest.path.relative_to(root).as_posix(),
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
            for name in sorted(
                {
                    "README.source.md",
                    "content.tei.xml",
                    "provenance.json",
                    "source-accountability.json",
                    "unresolved.jsonl",
                }
            )
        ],
    }
    _strict_equal(manifest_record, expected_manifest, "candidate manifest")
    if manifest_bytes != _canonical(expected_manifest):
        raise ValueError("LIB-031 candidate manifest is not canonical or ordered")
    members = _retained_members(source_manifest, profile)
    expected_body, expected_rows, expected_documents = _expected_body(
        source_manifest, profile, members
    )
    (
        expected_accountability,
        expected_provenance,
        expected_unresolved,
        source_set_digest,
    ) = _expected_evidence(
        source_manifest,
        profile,
        members,
        expected_rows,
        expected_documents,
    )
    expected_tree = _expected_tei(expected_body, source_set_digest)
    content = candidate.member_bytes("content.tei.xml")
    expected_content = etree.tostring(
        expected_tree, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )
    if content != expected_content:
        raise ValueError(
            "LIB-031 TEI serialized bytes are not the exact deterministic projection"
        )
    tree = etree.fromstring(
        content,
        parser=etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )
    if tree.getroottree().docinfo.doctype:
        raise ValueError("LIB-031 candidate must not add a doctype")
    if not _same_tree(tree, expected_tree):
        raise ValueError(
            "LIB-031 TEI document is not the exact deterministic projection"
        )
    etree.XMLSchema(
        etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))
    ).assertValid(tree)
    accountability = _json_bytes(
        candidate.member_bytes("source-accountability.json"),
        "LIB-031 source accountability",
    )
    _validate_schema(
        accountability,
        _json(schema_path, "accountability schema"),
        "LIB-031 source accountability",
    )
    _strict_equal(accountability, expected_accountability, "source accountability")
    if candidate.member_bytes("source-accountability.json") != _canonical(
        expected_accountability
    ):
        raise ValueError("LIB-031 source accountability bytes are not canonical")
    provenance = _json_bytes(
        candidate.member_bytes("provenance.json"), "LIB-031 provenance"
    )
    provenance_schema = _json(
        source_manifest.authority_path("provenance-schema"), "provenance schema"
    )
    _validate_schema(provenance, provenance_schema, "LIB-031 provenance")
    _strict_equal(provenance, expected_provenance, "provenance")
    if candidate.member_bytes("provenance.json") != _canonical(expected_provenance):
        raise ValueError("LIB-031 provenance bytes are not canonical")
    unresolved_bytes = candidate.member_bytes("unresolved.jsonl")
    unresolved_lines = unresolved_bytes.splitlines()
    unresolved = [
        _json_bytes(line, f"LIB-031 unresolved line {index}")
        for index, line in enumerate(unresolved_lines, start=1)
    ]
    unresolved_schema = _json(
        source_manifest.authority_path("unresolved-schema"), "unresolved schema"
    )
    _validate_schema(unresolved, unresolved_schema, "LIB-031 unresolved")
    _strict_equal(unresolved, expected_unresolved, "unresolved")
    expected_unresolved_bytes = b"".join(
        _canonical(item) for item in expected_unresolved
    )
    if unresolved_bytes != expected_unresolved_bytes:
        raise ValueError("LIB-031 unresolved evidence bytes are not canonical")
    if candidate.member_bytes("README.source.md") != _expected_readme_bytes():
        raise ValueError("LIB-031 source attribution bytes are not exact")
    policy_forbidden = policy.get("forbidden_oracle_imports")
    if not isinstance(policy_forbidden, list):
        raise ValueError("LIB-031 policy forbidden-import list is invalid")
    implementation = Path(__file__).resolve()
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(implementation.read_bytes()),
        "import_closure_sha256": _closure_digest(root, policy),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_path.read_bytes()),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": _primary_source_digest(source_manifest),
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_path.read_bytes()),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ("_oracle",)
