"""Producer-independent validation for the LIB-029 reconstruction."""

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
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-lib029-source-to-tei-oracle"
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
    value = json.loads(path.read_bytes().decode("utf-8"))
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
        source_set.get("contract") != "ocd-retained-source-set-v1"
        or not isinstance(members, list)
        or not isinstance(work_order, list)
    ):
        raise ValueError("LIB-029 source set or profile is malformed")
    configured_root = os.environ.get("OCD_RETAINED_RAW_ROOT", "").strip()
    root = (
        Path(configured_root) if configured_root else manifest.repository_root / "raw"
    )
    root = root.resolve(strict=True)
    result: list[dict[str, object]] = []
    for expected_id, member in zip(work_order, members, strict=True):
        if not isinstance(member, dict) or member.get("work_id") != expected_id:
            raise ValueError("LIB-029 source member order drifted")
        logical_path = member.get("logical_path")
        if not isinstance(logical_path, str):
            raise ValueError("LIB-029 source logical path is invalid")
        path = (root / logical_path).resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("LIB-029 source escaped retained root") from exc
        content = path.read_bytes()
        if len(content) != member.get("bytes") or _sha(content) != member.get("sha256"):
            raise ValueError(f"LIB-029 source hash drifted: {logical_path}")
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
        raise ValueError(f"LIB-029 source has no ThML.body: {path}")
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
    text = value or ""
    if (
        target_tag in {"div", "table", "row", "list", "lg", "index"}
        and not text.strip()
    ):
        return ""
    return text


def _needs_block_wrapper(
    source: etree._Element, parent: etree._Element, target_tag: str
) -> bool:
    """Keep source-inline features valid when ThML places them in a div."""

    del source
    parent_tag = _local(parent) if isinstance(parent.tag, str) else ""
    return parent_tag in {"div", "quote"} and target_tag in {
        "ref",
        "hi",
        "seg",
        "foreign",
        "lb",
    }


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


def _attribute_dispositions(
    source: etree._Element,
    source_tag: str,
    target_tag: str,
    target: etree._Element,
    synthetic_title: str | None,
) -> list[dict[str, str]]:
    projected: dict[str, tuple[str, str | None]] = {}
    if target_tag in {"div", "quote", "seg", "list"}:
        projected["type"] = ("@type", target.get("type"))
    if target_tag in {"div", "note", "pb", "milestone"}:
        projected["n"] = ("@n", target.get("n"))
    if target_tag == "hi":
        projected["class"] = ("@rend", target.get("rend"))
    if source_tag == "span" and target_tag == "foreign":
        projected["lang"] = ("@xml:lang", target.get(XML_LANG))
    if source_tag == "a" and target_tag == "ref":
        projected["href"] = ("@target", target.get("target"))
    if source_tag == "scripRef" and target_tag == "ref":
        projected["osisRef"] = ("@target", target.get("target"))
        projected["passage"] = ("@cRef", target.get("cRef"))
    if source_tag == "note" and target_tag == "note":
        projected["place"] = ("@place", target.get("place"))
    if source_tag in {"td", "th"} and target_tag == "cell":
        projected["colspan"] = ("@cols", target.get("cols"))
    if source_tag.startswith("div") and synthetic_title is not None:
        projected["title"] = ("child::head[1]", synthetic_title)

    result: list[dict[str, str]] = []
    language_codes = {"EL": "grc", "HE": "he", "LA": "la", "FR": "fr", "DE": "de"}
    for name, source_value in source.attrib.items():
        destination, target_value = projected.get(name, ("source-accountability", None))
        represented_value = (
            language_codes.get(source_value, source_value.lower())
            if name == "lang"
            else source_value
        )
        if target_value != represented_value:
            destination = "source-accountability"
        result.append(
            {
                "source_attribute": name,
                "source_value": source_value,
                "destination": destination,
            }
        )
    return result


def _expected_body(
    manifest: SourceManifest,
    profile: Mapping[str, object],
    members: tuple[dict[str, object], ...],
) -> tuple[etree._Element, list[dict[str, object]]]:
    body = etree.Element(
        f"{{{TEI_NS}}}body", {XML_ID: "lib029-body"}, nsmap={None: TEI_NS}
    )
    rows: list[dict[str, object]] = []
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
            raise ValueError("LIB-029 source contains an unsupported body node")
        tag = (
            _local(source)
            if isinstance(source.tag, str)
            else ("#comment" if comment else "#pi")
        )
        target_tag = _contextual_target_tag(source, parent)
        target_id = f"lib029-f-{serial:07d}"
        attrs = {XML_ID: target_id}
        if comment:
            attrs["type"] = "thml-comment"
        elif pi:
            attrs["type"] = "thml-processing-instruction"
        else:
            attrs.update(_attributes(source, target_tag))
        target = etree.Element(f"{{{TEI_NS}}}{target_tag}", attrs)
        target_parent = parent
        if _needs_block_wrapper(source, parent, target_tag):
            target_parent = etree.Element(f"{{{TEI_NS}}}p")
            parent.append(target_parent)
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
        synthetic_title = title if title and not has_heading_child else None
        if synthetic_title is not None:
            head = etree.Element(f"{{{TEI_NS}}}head")
            head.text = synthetic_title
            target.append(head)
            head.tail = _content_text(target_tag, source.text)
        else:
            target.text = _content_text(target_tag, source.text)
        child_ordinal = len(parent) + 1
        target_parent.append(target)
        rows.append(
            {
                "feature_id": f"lib029-feature-{serial:07d}",
                "work_id": work_id,
                "source_selector": _selector(source, source_body),
                "source_tag": tag,
                "source_xml_id": source.get("id"),
                "attributes": dict(source.attrib)
                if isinstance(source.tag, str)
                else {},
                "direct_text": source.text or "",
                "tail_text": source.tail or "",
                "direct_text_sha256": _sha((source.text or "").encode("utf-8")),
                "tail_text_sha256": _sha((source.tail or "").encode("utf-8")),
                "tei_tag": target_tag,
                "tei_xml_id": target_id,
                "tei_parent_id": parent.get(XML_ID) or "",
                "tei_child_ordinal": child_ordinal,
                "tei_attributes": {
                    ("xml:id" if key == XML_ID else key): value
                    for key, value in target.attrib.items()
                },
                "attribute_dispositions": (
                    _attribute_dispositions(
                        source, tag, target_tag, target, synthetic_title
                    )
                    if isinstance(source.tag, str)
                    else []
                ),
                "disposition": "represented",
                "tei_selector": f"#{target_id}",
                "parent_feature_id": None,
                "source_title_head": synthetic_title,
            }
        )
        if rows[-1]["tei_parent_id"]:
            for previous in reversed(rows[:-1]):
                if previous["tei_xml_id"] == rows[-1]["tei_parent_id"]:
                    rows[-1]["parent_feature_id"] = previous["feature_id"]
                    break
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
        del tree
        work = etree.Element(f"{{{TEI_NS}}}div", {XML_ID: work_id, "type": "work"})
        head = etree.Element(f"{{{TEI_NS}}}head")
        head.text = str(metadata["title"])
        work.append(head)
        body.append(work)
        selected_ids = profile.get("selected_div1_ids")
        if (
            not isinstance(selected_ids, list)
            or not selected_ids
            or any(not isinstance(item, str) for item in selected_ids)
        ):
            raise ValueError("LIB-029 selected div1 scope is invalid")
        selected = tuple(
            child
            for child in source_body
            if isinstance(child.tag, str)
            and _local(child) == "div1"
            and child.get("id") in selected_ids
        )
        if [child.get("id") for child in selected] != selected_ids:
            raise ValueError(
                "LIB-029 selected div1 scope is incomplete or out of order"
            )
        for child in selected:
            append(child, work, source_body, work_id)
            work[-1].tail = _content_text("div", child.tail)
    return body, rows


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
    pending = ["build.tei.lib029_oracle"]
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
                raise ValueError("LIB-029 oracle closure contains dynamic import")
            for name in names:
                if any(
                    name == prefix or name.startswith(prefix + ".")
                    for prefix in forbidden
                ):
                    raise ValueError(f"LIB-029 oracle imports forbidden module {name}")
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


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    if candidate.manifest.get("status") != "nonaccepted":
        raise ValueError("LIB-029 candidate is not nonaccepted")
    expected_manifest = {
        "path": source_manifest.path.relative_to(root).as_posix(),
        "sha256": source_manifest.sha256,
    }
    if candidate.manifest.get("source_manifest") != expected_manifest:
        raise ValueError("LIB-029 candidate source-manifest binding drifted")
    if candidate.manifest.get("converter") != source_manifest.record["converter"]:
        raise ValueError("LIB-029 candidate converter binding drifted")
    if (
        candidate.manifest.get("package_schema")
        != source_manifest.record["package_schema"]
    ):
        raise ValueError("LIB-029 candidate package-schema binding drifted")
    profile_path = source_manifest.authority_path(PROFILE_AUTHORITY)
    policy_path = source_manifest.authority_path("validation-policy")
    schema_path = source_manifest.authority_path("source-accountability-schema")
    profile = _json(profile_path, "LIB-029 profile")
    policy = _json(policy_path, "LIB-029 policy")
    members = _retained_members(source_manifest, profile)
    expected_body, expected_rows = _expected_body(source_manifest, profile, members)
    content = candidate.member_bytes("content.tei.xml")
    tree = etree.fromstring(
        content,
        parser=etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )
    if (
        _local(tree) != "TEI"
        or tree.nsmap.get(None) != TEI_NS
        or tree.get(XML_ID) != "lib029-candidate"
    ):
        raise ValueError("LIB-029 TEI root drifted")
    if tree.getroottree().docinfo.doctype:
        raise ValueError("LIB-029 candidate must not add a doctype")
    actual_body = tree.find(f"{{{TEI_NS}}}text/{{{TEI_NS}}}body")
    if actual_body is None or not _same_tree(actual_body, expected_body):
        raise ValueError("LIB-029 TEI body is not an exact deterministic projection")
    etree.XMLSchema(
        etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))
    ).assertValid(tree)
    accountability = json.loads(
        candidate.member_bytes("source-accountability.json").decode("utf-8")
    )
    Draft202012Validator(json.loads(schema_path.read_bytes().decode("utf-8"))).validate(
        accountability
    )
    if (
        accountability.get("feature_count") != len(expected_rows)
        or accountability.get("omitted_feature_count") != 0
        or accountability.get("duplicate_feature_count") != 0
    ):
        raise ValueError("LIB-029 source feature accounting drifted")
    observed_rows = accountability.get("crosswalk")
    if not isinstance(observed_rows, list) or len(observed_rows) != len(expected_rows):
        raise ValueError("LIB-029 crosswalk cardinality drifted")
    for expected, observed in zip(expected_rows, observed_rows, strict=True):
        if observed != expected:
            raise ValueError(f"LIB-029 crosswalk drifted at {expected['feature_id']}")
    provenance = json.loads(candidate.member_bytes("provenance.json").decode("utf-8"))
    if (
        provenance.get("status") != "nonaccepted"
        or provenance.get("canonical_data_written")
        or provenance.get("canonical_ir_written")
    ):
        raise ValueError("LIB-029 provenance status drifted")
    works = provenance.get("works")
    if not isinstance(works, list) or [item.get("work_id") for item in works] != [
        item["work_id"] for item in members
    ]:
        raise ValueError("LIB-029 provenance work accounting drifted")
    for item in works:
        if (
            item.get("accepted_ir") != "not_accepted"
            or item.get("human_review") != "required"
            or item.get("publication") != "not_ready"
        ):
            raise ValueError("LIB-029 human/publication boundary drifted")
    unresolved = candidate.member_bytes("unresolved.jsonl").decode("utf-8").splitlines()
    if not unresolved or any(
        json.loads(line).get("status") != "unresolved" for line in unresolved
    ):
        raise ValueError("LIB-029 unresolved accounting drifted")
    if b"CCEL.org" not in candidate.member_bytes("README.source.md"):
        raise ValueError("LIB-029 source attribution is missing")
    policy_forbidden = policy.get("forbidden_oracle_imports")
    if not isinstance(policy_forbidden, list):
        raise ValueError("LIB-029 policy forbidden-import list is invalid")
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
        "source_sha256": _sha(
            source_manifest.authority_path("creeds-of-christendom-vol-1-source").read_bytes()
        ),
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
