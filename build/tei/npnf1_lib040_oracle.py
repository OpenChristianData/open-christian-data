"""Producer-independent exact retained-source oracle for LIB-040."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import sys
from typing import Any

import build as _build
import build.tei as _build_tei
from lxml import etree
from jsonschema import Draft202012Validator

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
ORACLE_ID = "ocd-lib040-source-to-tei-oracle"
ORACLE_VERSION = "1"
ADMIN_SCOPE_TITLE = (
    "LIB-040 administrative scope: eight assigned work roots from retained "
    "NPNF First Series volumes 1, 6, and 7"
)
PUBLICATION_NOTICE = "publication:not_ready; human textual acceptance absent."
EXPECTED_README_SOURCE = (
    "# LIB-040 retained sources\n\n"
    "This nonaccepted, publication-not-ready candidate was reconstructed "
    "deterministically from exact retained `npnf101.xml`, `npnf106.xml`, and "
    "`npnf107.xml` witnesses.\n\n"
    "The retained electronic metadata names Philip Schaff as editor, identifies "
    "the underlying texts as Public Domain, and cites the 1886 Christian "
    "Literature Publishing Co. print editions recorded in `provenance.json`. The "
    "assigned source-root title pages retain these exact source forms: `J.G. "
    "Pilkington, M.A.,`; `Translated by the Rev. J. G. Cunningham, M.A.`; `the "
    "rev. William Findlay, m.a.,`; `the rev. s. d. f. salmond, d.d.,`; `the rev. "
    "r. g. macmullen, m.a.,` (split across three retained spans); `rev. John "
    "Gibb, d.d.,`; `rev. H. Browne, m.a.,`; and `rev. charles c. starbuck, "
    "a.m.,`. James Innes is not named in assigned `npnf107` root `iii`; retained "
    "front matter outside the assigned scope, in `npnf107` root `ii`, supplies "
    "the exact credit `Rev. James Innes, Panbride.` That front matter is "
    "accounted as excluded evidence and is not inserted into the candidate body. "
    "No work-level credit is inferred beyond these exact retained locations and "
    "forms. The electronic witnesses are sourced via [CCEL "
    "NPNF1-01](https://www.ccel.org/ccel/schaff/npnf101.html), [CCEL "
    "NPNF1-06](https://www.ccel.org/ccel/schaff/npnf106.html), and [CCEL "
    "NPNF1-07](https://www.ccel.org/ccel/schaff/npnf107.html). CCEL permits "
    "parsing its ThML; do not sell CCEL files or derivatives of CCEL formatting. "
    "Human textual acceptance and publication authorization remain absent.\n"
).encode("utf-8")
SOURCE_LOCAL = "source-local"
CANONICAL_SOURCE_LOCAL = "sources/structured-text/augustine-npnf101-106-107-lib040"
PRODUCER_KEY = "build/tei/npnf1_lib040_reconstruction.py"
ORACLE_KEY = "build/tei/npnf1_lib040_oracle.py"


def local_layout() -> tuple[Path, Path, Path]:
    implementation_root = Path(__file__).resolve().parent
    package_root = implementation_root.parents[1]
    if implementation_root.name == "tei" and implementation_root.parent.name == "build":
        source_local_root = (
            package_root / "sources/structured-text/augustine-npnf101-106-107-lib040"
        )
    else:
        source_local_root = implementation_root / SOURCE_LOCAL
    return implementation_root, package_root, source_local_root


SOURCES = {
    "npnf101": (
        "raw/ccel/npnf1/npnf101.xml",
        4_837_387,
        "5a251ba0e3ef934821f3998ba1e3ab52ea40dae02ced15fbd36bb111fd81afc0",
        (
            ("vi", "augustine-confessions"),
            ("vii", "augustine-letters-part-1"),
        ),
    ),
    "npnf106": (
        "raw/ccel/npnf1/npnf106.xml",
        4_680_096,
        "3710c6985a8dfc4e4ffafc461a7a8550db609b0506535453dac252f2aa55b604",
        (
            ("v", "augustine-sermon-on-the-mount"),
            ("vi", "augustine-harmony-of-gospels"),
            ("vii", "augustine-sermons-selected-lessons"),
        ),
    ),
    "npnf107": (
        "raw/ccel/npnf1/npnf107.xml",
        3_694_413,
        "75d52f4c31dde0959974256b3f5d84394b7b96fcd2883e78a3d32e0b66c5869a",
        (
            ("iii", "augustine-tractates-on-john"),
            ("iv", "augustine-homilies-on-first-john"),
            ("v", "augustine-soliloquies"),
        ),
    ),
}
TAG_MAP = {
    "br": "lb",
    "div": "div",
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "div4": "div",
    "i": "hi",
    "note": "note",
    "p": "p",
    "pb": "pb",
    "scripCom": "ref",
    "scripRef": "ref",
    "span": "seg",
    "sup": "hi",
}
EXPECTED_MEMBERS = {
    "manifest.json",
    "README.source.md",
    "content.tei.xml",
    "provenance.json",
    "source-accountability.json",
    "unresolved.jsonl",
}


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _closure_paths(root: Path) -> tuple[Path, ...]:
    return (
        root / "build/__init__.py",
        root / "build/tei/__init__.py",
        root / "build/tei/npnf1_lib040_oracle.py",
    )


def _closure_digest(root: Path) -> str:
    verify_runtime_closure(root)
    paths = _closure_paths(root)
    paths = (
        path.resolve(strict=True) for path in paths
    )
    records = [
        {"path": path.relative_to(root).as_posix(), "sha256": sha(path.read_bytes())}
        for path in paths
    ]
    return sha(canonical_bytes(records))


def import_closure_digest(root: Path) -> str:
    """Compatibility name retained for the standalone oracle CLI."""

    return _closure_digest(root)


def verify_runtime_closure(root: Path) -> None:
    """Require the live package and oracle modules to come from this root."""

    expected = {
        "build": _closure_paths(root)[0].resolve(strict=True),
        "build.tei": _closure_paths(root)[1].resolve(strict=True),
    }
    for module_name, expected_path in expected.items():
        module = sys.modules.get(module_name)
        if module is None:
            raise ValueError(f"required runtime module {module_name!r} is not loaded")
        runtime_file = getattr(module, "__file__", None)
        if not runtime_file:
            raise ValueError(f"runtime module {module_name!r} has no source file")
        runtime_path = Path(str(runtime_file)).resolve(strict=True)
        if not runtime_path.samefile(expected_path):
            raise ValueError(f"runtime module {module_name!r} loaded from the wrong root")
        origin = getattr(getattr(module, "__spec__", None), "origin", None)
        if origin and origin not in {"built-in", "frozen"}:
            if not Path(str(origin)).resolve(strict=True).samefile(expected_path):
                raise ValueError(f"runtime module {module_name!r} origin drift")
        if sha(runtime_path.read_bytes()) != sha(expected_path.read_bytes()):
            raise ValueError(f"runtime module {module_name!r} bytes drifted")

    oracle_path = _closure_paths(root)[2].resolve(strict=True)
    oracle_modules = []
    for module in tuple(sys.modules.values()):
        if module is None:
            continue
        runtime_file = getattr(module, "__file__", None)
        if not runtime_file:
            continue
        try:
            runtime_path = Path(str(runtime_file)).resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if runtime_path == oracle_path:
            oracle_modules.append(module)
    if not oracle_modules:
        raise ValueError("LIB040 oracle runtime module is not loaded")
    expected_sha = sha(oracle_path.read_bytes())
    for module in oracle_modules:
        origin = getattr(getattr(module, "__spec__", None), "origin", None)
        if origin and origin not in {"built-in", "frozen"}:
            if not Path(str(origin)).resolve(strict=True).samefile(oracle_path):
                raise ValueError("LIB040 oracle runtime origin drift")
        if sha(Path(str(getattr(module, "__file__"))).resolve(strict=True).read_bytes()) != expected_sha:
            raise ValueError("LIB040 oracle runtime bytes drifted")


def strict_json(content: bytes, label: str) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"{label} duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def parse(content: bytes) -> etree._ElementTree:
    return etree.parse(
        io.BytesIO(content),
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )


def verify_namespace_declarations(content: bytes) -> None:
    """Require one default TEI declaration on the root and none below it."""
    pending: list[tuple[str, str]] = []
    element_index = 0
    for event, value in etree.iterparse(
        io.BytesIO(content),
        events=("start", "start-ns"),
        resolve_entities=False,
        no_network=True,
        remove_comments=False,
        huge_tree=True,
    ):
        if event == "start-ns":
            prefix, uri = value
            pending.append((prefix or "", uri))
            continue
        expected = [("", TEI_NS)] if element_index == 0 else []
        if pending != expected:
            location = etree.QName(value).localname
            raise ValueError(
                "TEI namespace declaration drift at "
                f"element {element_index + 1} ({location}): {pending!r}"
            )
        pending.clear()
        element_index += 1
    if element_index == 0 or pending:
        raise ValueError("TEI namespace declaration stream drift")


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value)


def normalized_attrs(node: etree._Element) -> dict[str, str]:
    return {
        "xml:id"
        if key == f"{{{XML_NS}}}id"
        else "xml:lang"
        if key == f"{{{XML_NS}}}lang"
        else key: value
        for key, value in node.attrib.items()
    }


def mapped_tag(source: etree._Element) -> str:
    return (
        "foreign"
        if source.tag == "span" and source.get("lang")
        else TAG_MAP[str(source.tag)]
    )


def expected_attrs(
    source: etree._Element, source_key: str, ordinal: int, work_id: str | None
) -> dict[str, str]:
    source_id = source.get("id")
    attrs = {
        "xml:id": f"lib040-{safe_id(work_id)}"
        if work_id
        else f"lib040-{source_key}-{safe_id(source_id) if source_id else f'feature-{ordinal:05d}'}"
    }
    tag = str(source.tag)
    for name, value in source.attrib.items():
        if name == "n" and tag in {"div1", "div2", "div3", "div4", "note", "pb"}:
            attrs["n"] = value
        elif name == "type" and tag in {"div1", "div2", "div3", "div4"}:
            attrs["type"] = value
        elif name == "class":
            attrs["rend"] = value
        elif name == "place" and tag == "note":
            attrs["place"] = value
        elif name == "href" and tag == "pb":
            attrs["facs"] = value
        elif name == "passage" and tag in {"scripRef", "scripCom"}:
            attrs["cRef"] = value
        elif name == "osisRef" and tag in {"scripRef", "scripCom"}:
            attrs["target"] = value
        elif name == "lang" and tag == "span":
            attrs["xml:lang"] = "grc" if value == "EL" else value.lower()
    if work_id:
        attrs.update({"type": "work", "subtype": work_id})
    elif tag == "i":
        attrs["rend"] = "italic"
    elif tag == "sup":
        attrs["rend"] = "superscript"
    elif tag == "scripRef":
        attrs["type"] = "scripture"
    elif tag == "scripCom":
        attrs["type"] = "scripture-commentary"
    return attrs


def source_selector(node: etree._Element) -> str:
    parts = []
    current = node
    while current is not None and current.tag != "ThML.body":
        parent = current.getparent()
        if parent is None:
            break
        if isinstance(current.tag, str):
            peers = [child for child in parent if child.tag == current.tag]
            parts.append(f"{current.tag}[{peers.index(current) + 1}]")
        else:
            comments = [child for child in parent if child.tag is etree.Comment]
            parts.append(f"comment()[{comments.index(current) + 1}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def expected_dispositions(source: etree._Element) -> list[dict[str, str]]:
    result = []
    tag = str(source.tag)
    for name, value in source.attrib.items():
        destination, method = "source-accountability", "preserved-exactly"
        if name == "id":
            destination, method = "@xml:id", "deterministic-source-or-work-prefix"
        elif name == "n" and tag in {"div1", "div2", "div3", "div4", "note", "pb"}:
            destination = "@n"
        elif name == "type" and tag in {"div1", "div2", "div3", "div4"}:
            destination = "@type"
        elif name == "class":
            destination = "@rend"
        elif name == "place" and tag == "note":
            destination = "@place"
        elif name == "href" and tag == "pb":
            destination = "@facs"
        elif name == "passage" and tag in {"scripRef", "scripCom"}:
            destination = "@cRef"
        elif name == "osisRef" and tag in {"scripRef", "scripCom"}:
            destination = "@target"
        elif name == "lang" and tag == "span":
            destination, method = "@xml:lang", "declared-language-code-map"
        elif name == "title" and tag.startswith("div"):
            destination = "child::head[1]"
        result.append(
            {
                "destination": destination,
                "method": method,
                "source_attribute": name,
                "source_value": value,
            }
        )
    return result


def expected_crosswalk(
    selected: list[tuple[str, etree._Element, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    bindings = []

    def visit(
        node: etree._Element,
        key: str,
        parent_feature: str | None,
        parent_target_tag: str,
        work_id: str | None = None,
    ) -> None:
        ordinal = len(rows) + 1
        feature = f"lib040-feature-{ordinal:05d}"
        if node.tag is etree.Comment:
            rows.append(
                {
                    "feature_id": feature,
                    "kind": "comment",
                    "parent_feature_id": parent_feature,
                    "source_member": key,
                    "source_selector": source_selector(node),
                    "text": node.text or "",
                    "tail_text": node.tail or "",
                    "text_sha256": sha((node.text or "").encode()),
                    "tail_text_sha256": sha((node.tail or "").encode()),
                    "disposition": "represented-as-xml-comment",
                }
            )
            return
        attrs = expected_attrs(node, key, ordinal, work_id)
        tag = mapped_tag(node)
        wrapper = (
            f"lib040-inline-container-{ordinal:05d}"
            if parent_target_tag == "div" and tag in {"ref", "seg", "foreign", "hi"}
            else None
        )
        row = {
            "attribute_dispositions": expected_dispositions(node),
            "attributes": dict(node.attrib),
            "direct_text": node.text or "",
            "direct_text_sha256": sha((node.text or "").encode()),
            "disposition": "represented",
            "feature_id": feature,
            "kind": "element",
            "parent_feature_id": parent_feature,
            "source_member": key,
            "source_selector": source_selector(node),
            "source_tag": node.tag,
            "source_title_head": node.get("title")
            if str(node.tag).startswith("div")
            else None,
            "source_xml_id": node.get("id"),
            "tail_text": node.tail or "",
            "tail_text_sha256": sha((node.tail or "").encode()),
            "tei_attributes": attrs,
            "tei_tag": tag,
            "tei_xml_id": attrs["xml:id"],
            "tei_wrapper_id": wrapper,
        }
        if work_id:
            row["work_id"] = work_id
        rows.append(row)
        for child in node:
            visit(child, key, feature, tag)

    for key, root, work_id in selected:
        before = len(rows)
        visit(root, key, None, "body", work_id)
        bindings.append(
            {
                "feature_count": len(rows) - before,
                "source_member": SOURCES[key][0],
                "source_root_id": root.get("id"),
                "source_root_selector": source_selector(root),
                "work_id": work_id,
            }
        )
    return rows, bindings


def source_metadata(tree: etree._ElementTree) -> dict[str, object]:
    head = tree.getroot().find("ThML.head")
    entries = [
        {
            "attributes": dict(node.attrib),
            "tag": node.tag,
            "text": node.text or "",
            "tail": node.tail or "",
        }
        for node in tree.xpath("/ThML/ThML.head/electronicEdInfo/DC/*")
    ]
    return {
        "dc_entries": entries,
        "head_c14n_sha256": sha(
            etree.tostring(head, method="c14n", with_comments=True)
        ),
        "print_published": [
            str(value)
            for value in tree.xpath("/ThML/ThML.head/printSourceInfo/published/text()")
        ],
    }


def division_evidence(
    tree: etree._ElementTree, selected_ids: set[str]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    body = tree.getroot().find("ThML.body")
    top = []
    for ordinal, node in enumerate(
        [child for child in body if isinstance(child.tag, str)], start=1
    ):
        assigned = node.get("id") in selected_ids
        descendant = any(
            node.xpath(".//*[@id=" + repr(value) + "]") for value in selected_ids
        )
        top.append(
            {
                "disposition": "assigned-work-root-represented"
                if assigned
                else "container-with-assigned-descendants"
                if descendant
                else "outside-assigned-work-scope",
                "id": node.get("id"),
                "ordinal": ordinal,
                "reason": "complete subtree projected"
                if assigned
                else "wrapper only; assigned descendants separately projected"
                if descendant
                else "front matter, prefatory material, or indexes outside the eight assigned work roots",
                "tag": node.tag,
                "title": node.get("title", ""),
            }
        )
    direct = []
    for ordinal, node in enumerate(tree.xpath("//ThML.body/div1/div2"), start=1):
        assigned = node.get("id") in selected_ids or any(
            ancestor.get("id") in selected_ids for ancestor in node.iterancestors()
        )
        direct.append(
            {
                "disposition": "assigned-work-subtree-represented"
                if assigned
                else "outside-assigned-work-scope",
                "id": node.get("id"),
                "ordinal": ordinal,
                "parent_div1_id": node.getparent().get("id"),
                "reason": "complete subtree projected in source order"
                if assigned
                else "retained front matter, preface, or index division outside the assigned work roots",
                "title": node.get("title", ""),
            }
        )
    return top, direct


def verify_node(
    source: etree._Element,
    target: etree._Element,
    source_key: str,
    counter: list[int],
    work_id: str | None = None,
) -> None:
    counter[0] += 1
    ordinal = counter[0]
    if target.tag != f"{{{TEI_NS}}}{mapped_tag(source)}":
        raise ValueError("TEI source tag or namespace drift")
    if normalized_attrs(target) != expected_attrs(source, source_key, ordinal, work_id):
        raise ValueError("TEI semantic attribute drift")
    if (target.text or "") != (source.text or "") or (target.tail or "") != (
        source.tail or ""
    ):
        raise ValueError("TEI direct text or tail drift")
    source_children = list(source)
    target_children = list(target)
    index = 0
    title = source.get("title") if str(source.tag).startswith("div") else None
    if title is not None:
        if (
            not target_children
            or target_children[0].tag != f"{{{TEI_NS}}}head"
            or target_children[0].text != title
            or (target_children[0].tail or "")
            or target_children[0].attrib
        ):
            raise ValueError("TEI division title drift")
        index = 1
    for source_child in source_children:
        if index >= len(target_children):
            raise ValueError("TEI omission")
        candidate_child = target_children[index]
        if source_child.tag is etree.Comment:
            counter[0] += 1
            if (
                candidate_child.tag is not etree.Comment
                or (candidate_child.text or "") != (source_child.text or "")
                or (candidate_child.tail or "") != (source_child.tail or "")
            ):
                raise ValueError("TEI comment drift")
        else:
            direct_inline = etree.QName(target).localname == "div" and mapped_tag(
                source_child
            ) in {"ref", "seg", "foreign", "hi"}
            if direct_inline:
                wrapper_attrs = {
                    "xml:id": f"lib040-inline-container-{counter[0] + 1:05d}",
                    "type": "source-inline-container",
                }
                if (
                    candidate_child.tag != f"{{{TEI_NS}}}ab"
                    or normalized_attrs(candidate_child) != wrapper_attrs
                    or candidate_child.text
                    or candidate_child.tail
                    or len(candidate_child) != 1
                ):
                    raise ValueError("TEI inline wrapper drift")
                candidate_child = candidate_child[0]
            verify_node(source_child, candidate_child, source_key, counter)
        index += 1
    if index != len(target_children):
        raise ValueError("TEI duplication or invention")


def census(nodes: list[etree._Element]) -> dict[str, int]:
    elements = [n for n in nodes if isinstance(n.tag, str)]
    strings = [(n.text or "") + (n.tail or "") for n in nodes]
    return {
        "elements": len(elements),
        "comments": sum(n.tag is etree.Comment for n in nodes),
        "attributes": sum(len(n.attrib) for n in elements),
        "text_nodes": sum(n.text is not None for n in nodes),
        "tail_nodes": sum(n.tail is not None for n in nodes),
        "characters": sum(map(len, strings)),
        "non_ascii_characters": sum(sum(ord(c) > 127 for c in s) for s in strings),
    }


def element_census(nodes: list[etree._Element]) -> dict[str, int]:
    elements = [node for node in nodes if isinstance(node.tag, str)]
    strings = [(node.text or "") + (node.tail or "") for node in elements]
    return {
        "elements": len(elements),
        "attributes": sum(len(node.attrib) for node in elements),
        "text_nodes": sum(node.text is not None for node in elements),
        "tail_nodes": sum(node.tail is not None for node in elements),
        "characters": sum(len(value) for value in strings),
        "non_ascii_characters": sum(
            sum(ord(char) > 127 for char in value) for value in strings
        ),
    }


def retained_document_accounting(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()
    preceding = []
    cursor = root.getprevious()
    while cursor is not None:
        preceding.insert(0, cursor)
        cursor = cursor.getprevious()
    following = []
    cursor = root.getnext()
    while cursor is not None:
        following.append(cursor)
        cursor = cursor.getnext()
    return {
        "doctype": tree.docinfo.doctype,
        "encoding": tree.docinfo.encoding,
        "pre_root_comments": [
            node.text or "" for node in preceding if node.tag is etree.Comment
        ],
        "pre_root_processing_instructions": [
            {"target": node.target, "text": node.text or ""}
            for node in preceding
            if node.tag is etree.PI
        ],
        "post_root_nodes": [
            etree.tostring(node, encoding="unicode") for node in following
        ],
        "root_attributes": dict(root.attrib),
        "root_namespace_declarations": dict(root.nsmap),
        "root_tag": root.tag,
        "standalone": tree.docinfo.standalone,
        "xml_version": tree.docinfo.xml_version,
    }


def verify_header(
    tree: etree._ElementTree,
    content: bytes,
    sources: dict[str, etree._ElementTree],
) -> None:
    verify_namespace_declarations(content)
    root = tree.getroot()
    declaration = b"<?xml version='1.0' encoding='UTF-8'?>"
    if not content.startswith(declaration + b"\n<TEI") or not content.endswith(
        b"</TEI>"
    ):
        raise ValueError("TEI serialized document boundary or declaration drift")
    preceding = []
    cursor = root.getprevious()
    while cursor is not None:
        preceding.insert(0, cursor)
        cursor = cursor.getprevious()
    following = []
    cursor = root.getnext()
    while cursor is not None:
        following.append(cursor)
        cursor = cursor.getnext()
    if (
        tree.docinfo.xml_version != "1.0"
        or tree.docinfo.encoding != "UTF-8"
        or tree.docinfo.doctype
        or tree.docinfo.standalone
        or preceding
        or following
        or root.tag != f"{{{TEI_NS}}}TEI"
        or normalized_attrs(root) != {"xml:id": "lib040-candidate"}
        or root.nsmap != {None: TEI_NS}
        or root.text
        or root.tail
    ):
        raise ValueError("TEI root, prolog, namespace, or sibling shell drift")

    def children(node: etree._Element, names: tuple[str, ...]) -> list[etree._Element]:
        observed = list(node)
        if [child.tag for child in observed] != [
            f"{{{TEI_NS}}}{name}" for name in names
        ] or any(child.tail for child in observed):
            raise ValueError("TEI exact container topology drift")
        return observed

    header, text = children(root, ("teiHeader", "text"))
    if header.attrib or header.text or text.attrib or text.text:
        raise ValueError("TEI header or text shell drift")
    (file_desc,) = children(header, ("fileDesc",))
    if file_desc.attrib or file_desc.text:
        raise ValueError("TEI fileDesc shell drift")
    title_stmt, publication_stmt, source_desc = children(
        file_desc, ("titleStmt", "publicationStmt", "sourceDesc")
    )
    title, editor = children(title_stmt, ("title", "editor"))
    retained_editors = {
        "".join(
            str(value)
            for value in source.xpath(
                "/ThML/ThML.head/electronicEdInfo/DC/"
                "DC.Creator[@sub='Editor'][@scheme='short-form']/text()"
            )
        )
        for source in sources.values()
    }
    if (
        title_stmt.attrib
        or title_stmt.text
        or normalized_attrs(title) != {"type": "generated"}
        or title.text != ADMIN_SCOPE_TITLE
        or editor.attrib
        or editor.text not in retained_editors
        or retained_editors != {"Philip Schaff"}
        or list(title)
        or list(editor)
    ):
        raise ValueError("TEI generated scope label or retained editor drift")
    (notice,) = children(publication_stmt, ("p",))
    if (
        publication_stmt.attrib
        or publication_stmt.text
        or notice.attrib
        or list(notice)
        or notice.text != PUBLICATION_NOTICE
    ):
        raise ValueError("publication or human acceptance drift")
    (list_bibl,) = children(source_desc, ("listBibl",))
    if source_desc.attrib or source_desc.text or list_bibl.attrib or list_bibl.text:
        raise ValueError("TEI sourceDesc shell drift")
    bibls = children(list_bibl, ("bibl", "bibl", "bibl"))
    for bibl, key in zip(bibls, SOURCES, strict=True):
        src = sources[key]
        bibl_children = children(
            bibl, ("title", "editor", "publisher", "note", "note", "ref")
        )
        source_title, source_editor, publisher, print_statement, rights, ref = (
            bibl_children
        )
        expected_values = (
            "".join(
                str(v)
                for v in src.xpath(
                    "/ThML/ThML.head/electronicEdInfo/DC/DC.Title[not(@sub)]/text()"
                )
            ),
            "".join(
                str(v)
                for v in src.xpath(
                    "/ThML/ThML.head/electronicEdInfo/DC/"
                    "DC.Creator[@sub='Editor'][@scheme='short-form']/text()"
                )
            ),
            "".join(
                str(v)
                for v in src.xpath(
                    "/ThML/ThML.head/electronicEdInfo/DC/DC.Publisher/text()"
                )
            ),
            "".join(
                str(v)
                for v in src.xpath("/ThML/ThML.head/printSourceInfo/published/text()")
            ),
            "".join(
                str(v)
                for v in src.xpath(
                    "/ThML/ThML.head/electronicEdInfo/DC/DC.Rights/text()"
                )
            ),
        )
        actual_values = (
            source_title.text,
            source_editor.text,
            publisher.text,
            print_statement.text,
            rights.text,
        )
        if (
            actual_values != expected_values
            or normalized_attrs(bibl) != {"xml:id": f"source-{key}"}
            or normalized_attrs(print_statement)
            != {"type": "print-publication-statement"}
            or normalized_attrs(rights) != {"type": "rights"}
            or any(child.attrib for child in (source_title, source_editor, publisher))
            or any(list(child) for child in bibl_children)
        ):
            raise ValueError("TEI source metadata drift")
        url = "".join(
            str(v)
            for v in src.xpath(
                "/ThML/ThML.head/electronicEdInfo/DC/DC.Identifier[@scheme='URL']/text()"
            )
        )
        if ref.text != url or normalized_attrs(ref) != {
            "target": f"https://www.ccel.org{url}"
        }:
            raise ValueError("TEI source identifier drift")
    (body,) = children(text, ("body",))
    if normalized_attrs(body) != {"xml:id": "lib040-assigned-body"} or body.text:
        raise ValueError("TEI text/body shell drift")


def verify(root_dir: Path, candidate_dir: Path, schema_path: Path) -> dict[str, Any]:
    implementation_root, package_root, source_local_root = local_layout()
    producer_path = (
        implementation_root / "producer.py"
        if (implementation_root / "producer.py").is_file()
        else implementation_root / "npnf1_lib040_reconstruction.py"
    )
    oracle_path = Path(__file__).resolve()
    implementation = {
        ORACLE_KEY: sha(oracle_path.read_bytes()),
        PRODUCER_KEY: sha(producer_path.read_bytes()),
        "ocd_kernel/tei/vendor/xsd/tei_all.xsd": sha(
            (package_root / "ocd_kernel/tei/vendor/xsd/tei_all.xsd").read_bytes()
        ),
        "ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd": sha(
            (package_root / "ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd").read_bytes()
        ),
        "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd": sha(
            (package_root / "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd").read_bytes()
        ),
    }
    for name in (
        "README.md",
        "lib040.reconstruction-profile.json",
        "lib040.source-accountability.schema.json",
        "lib040.validation-policy.json",
    ):
        implementation[f"{CANONICAL_SOURCE_LOCAL}/{name}"] = sha(
            (source_local_root / name).read_bytes()
        )
    paths = {
        path.relative_to(candidate_dir).as_posix()
        for path in candidate_dir.rglob("*")
        if path.is_file()
    }
    if paths != EXPECTED_MEMBERS:
        raise ValueError(f"candidate file-set drift: {sorted(paths)}")
    contents = {name: (candidate_dir / name).read_bytes() for name in EXPECTED_MEMBERS}
    manifest = strict_json(contents["manifest.json"], "manifest")
    package_schema_path = (
        package_root
        / "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"
    )
    package_schema_bytes = package_schema_path.read_bytes()
    Draft202012Validator(
        strict_json(package_schema_bytes, "candidate package schema")
    ).validate(manifest)
    source_manifest_path = source_local_root / "lib040.source-manifest.json"
    source_manifest_bytes = source_manifest_path.read_bytes()
    source_manifest = strict_json(source_manifest_bytes, "LIB-040 source manifest")
    if (
        manifest.get("contract") != "ocd-candidate-package-v1"
        or manifest.get("status") != "nonaccepted"
        or manifest.get("source_id") != "ccel-npnf1-lib040-cohort"
        or manifest.get("converter")
        != {
            "callable": "produce",
            "id": "ocd-lib040-retained-thml-to-tei",
            "implementation_path": "build/tei/npnf1_lib040_reconstruction.py",
            "implementation_sha256": implementation[PRODUCER_KEY],
            "version": "1",
        }
        or manifest.get("package_schema")
        != {
            "path": "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
            "sha256": sha(package_schema_bytes),
        }
        or manifest.get("source_manifest")
        != {
            "path": f"{CANONICAL_SOURCE_LOCAL}/lib040.source-manifest.json",
            "sha256": sha(source_manifest_bytes),
        }
    ):
        raise ValueError("candidate manifest disposition drift")
    member_records = {record["name"]: record for record in manifest.get("members", [])}
    if set(member_records) != EXPECTED_MEMBERS - {"manifest.json"}:
        raise ValueError("manifest member-set drift")
    for name, record in member_records.items():
        if record != {
            "name": name,
            "bytes": len(contents[name]),
            "sha256": sha(contents[name]),
        }:
            raise ValueError(f"manifest binding drift for {name}")
    if (
        source_manifest.get("contract") != "ocd-source-manifest-v1"
        or source_manifest.get("source_id") != "ccel-npnf1-lib040-cohort"
        or source_manifest.get("converter", {}).get("implementation_sha256")
        != implementation[PRODUCER_KEY]
        or source_manifest.get("validator", {}).get("implementation_sha256")
        != implementation[ORACLE_KEY]
    ):
        raise ValueError("canonical-shaped source manifest binding drift")
    staged_names = {
        "source-local-attribution-readme": "README.md",
        "reconstruction-profile": "lib040.reconstruction-profile.json",
        "validation-policy": "lib040.validation-policy.json",
        "source-accountability-schema": "lib040.source-accountability.schema.json",
    }
    implementation_names = {
        "converter-implementation": "producer.py",
        "validator-implementation": "oracle.py",
    }
    for authority in source_manifest.get("authorities", []):
        name = authority.get("name")
        if name in staged_names:
            authority_path = source_local_root / staged_names[name]
        elif (
            name in implementation_names
            and (implementation_root / implementation_names[name]).is_file()
        ):
            authority_path = implementation_root / implementation_names[name]
        else:
            authority_path = root_dir / str(authority.get("path"))
        authority_bytes = authority_path.read_bytes()
        if authority.get("bytes") != len(authority_bytes) or authority.get(
            "sha256"
        ) != sha(authority_bytes):
            raise ValueError(f"source-manifest authority drift: {name}")
    source_trees = {}
    selected = []
    expected_source_members = []
    for key, (rel, size, digest, assignments) in SOURCES.items():
        content = (root_dir / rel).read_bytes()
        if len(content) != size or sha(content) != digest:
            raise ValueError(f"retained {key} authority drift")
        expected_source_members.append(
            {
                "assigned_roots": [
                    {"id": source_id, "work_id": work_id}
                    for source_id, work_id in assignments
                ],
                "bytes": size,
                "disposition": "primary-source; complete retained member with assigned roots projected and all other divisions accounted as excluded evidence",
                "path": rel,
                "sha256": digest,
            }
        )
        tree = parse(content)
        source_trees[key] = tree
        body = tree.getroot().find("ThML.body")
        if body is None:
            raise ValueError(f"retained {key} body missing")
        expected_top = {
            "npnf101": ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"),
            "npnf106": ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix"),
            "npnf107": ("i", "ii", "iii", "iv", "v", "vi"),
        }[key]
        if (
            tuple(node.get("id") for node in body if isinstance(node.tag, str))
            != expected_top
        ):
            raise ValueError(f"retained {key} top inventory drift")
        direct = tree.xpath("//ThML.body/div1/div2")
        if len(direct) != {"npnf101": 28, "npnf106": 118, "npnf107": 153}[key]:
            raise ValueError(f"retained {key} direct inventory drift")
        for source_id, work_id in assignments:
            matches = tree.xpath("//*[@id=" + repr(source_id) + "]")
            if len(matches) != 1:
                raise ValueError(f"retained {key} exact root drift")
            selected.append((key, matches[0], work_id))
    primary_authorities = [
        authority
        for authority in source_manifest.get("authorities", [])
        if authority.get("role") == "primary-source"
    ]
    if [
        {
            "bytes": authority.get("bytes"),
            "path": authority.get("path"),
            "sha256": authority.get("sha256"),
        }
        for authority in primary_authorities
    ] != [
        {"bytes": record["bytes"], "path": record["path"], "sha256": record["sha256"]}
        for record in expected_source_members
    ]:
        raise ValueError("stale or wrong primary-source binding")
    tree = parse(contents["content.tei.xml"])
    candidate_ids = tree.xpath("//@xml:id", namespaces={"xml": XML_NS})
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError(
            "candidate xml:id prefixing failed to resolve source collisions"
        )
    verify_header(tree, contents["content.tei.xml"], source_trees)
    body = tree.getroot().find(f".//{{{TEI_NS}}}body")
    if body is None or normalized_attrs(body) != {"xml:id": "lib040-assigned-body"}:
        raise ValueError("TEI body drift")
    works = [node for node in body if isinstance(node.tag, str)]
    if len(works) != 8 or any(node.tag != f"{{{TEI_NS}}}div" for node in works):
        raise ValueError("TEI work count or order shell drift")
    counter = [0]
    for (key, source, work_id), target in zip(selected, works, strict=True):
        verify_node(source, target, key, counter, work_id)
    if len(list(body)) != 8:
        raise ValueError("unbound TEI body node/comment/PI invention")
    schema = etree.XMLSchema(etree.parse(str(schema_path)))
    schema.assertValid(tree)
    accountability = strict_json(
        contents["source-accountability.json"], "accountability"
    )
    accountability_schema = strict_json(
        (source_local_root / "lib040.source-accountability.schema.json").read_bytes(),
        "source accountability schema",
    )
    Draft202012Validator(accountability_schema).validate(accountability)
    assigned_nodes = {
        key: [
            node
            for selected_key, root, _ in selected
            if selected_key == key
            for node in root.iter()
        ]
        for key in SOURCES
    }
    if (
        accountability.get("feature_count") != counter[0]
        or len(accountability.get("crosswalk", [])) != counter[0]
        or accountability.get("assigned_work_count") != 8
        or accountability.get("source_member_count") != 3
        or accountability.get("schema") != "lib040.source-accountability.schema.json"
        or accountability.get("source_scope")
        != "eight complete retained ThML.body div1 roots across npnf101, npnf106, and npnf107"
    ):
        raise ValueError("source accountability count drift")
    if (
        accountability.get("omitted_feature_count") != 0
        or accountability.get("duplicate_feature_count") != 0
        or accountability.get("unresolved_feature_count") != 0
    ):
        raise ValueError("source accountability completion drift")
    independently_derived_member_records = []
    for record, key in zip(
        accountability.get("member_accounting", []), tuple(SOURCES), strict=True
    ):
        rel, size, digest, _ = SOURCES[key]
        complete = list(source_trees[key].getroot().iter())
        assigned_scope = census(assigned_nodes[key])
        complete_scope = census(complete)
        excluded = {
            name: complete_scope[name] - assigned_scope[name] for name in complete_scope
        }
        selected_ids = {source_id for source_id, _ in SOURCES[key][3]}
        excluded_roots = [
            node
            for node in source_trees[key].xpath("/ThML/ThML.body/div1")
            if node.get("id") not in selected_ids
        ]
        excluded_elements = [
            node
            for retained_root in excluded_roots
            for node in retained_root.iter()
            if isinstance(node.tag, str)
        ]
        assigned_elements = [
            node for node in assigned_nodes[key] if isinstance(node.tag, str)
        ]
        occupied = {id(node) for node in assigned_elements + excluded_elements}
        complete_elements = [
            node
            for node in source_trees[key].getroot().iter()
            if isinstance(node.tag, str)
        ]
        shell_elements = [
            node for node in complete_elements if id(node) not in occupied
        ]
        if (
            record.get("path") != rel
            or record.get("bytes") != size
            or record.get("sha256") != digest
            or record.get("assigned_scope_census") != assigned_scope
            or record.get("complete_document_census") != complete_scope
            or record.get("excluded_scope_census") != excluded
            or record.get("excluded_division_census")
            != element_census(excluded_elements)
            or record.get("document_shell_census") != element_census(shell_elements)
            or record.get("document_accounting")
            != retained_document_accounting(source_trees[key])
        ):
            raise ValueError("source member accounting drift")
        independently_derived_member_records.append(record)
    expected_scope_reconciliation = {
        scope: {
            field: sum(
                record[f"{scope}_census"][field]
                for record in independently_derived_member_records
            )
            for field in independently_derived_member_records[0][f"{scope}_census"]
        }
        for scope in ("assigned_scope", "document_shell", "excluded_division")
    }
    if accountability.get("scope_reconciliation") != expected_scope_reconciliation:
        raise ValueError("assigned, excluded, and document-shell reconciliation drift")
    ids_by_member = {
        key: [
            str(node.get("id"))
            for node in assigned_nodes[key]
            if isinstance(node.tag, str) and node.get("id") is not None
        ]
        for key in SOURCES
    }
    if any(len(values) != len(set(values)) for values in ids_by_member.values()):
        raise ValueError("within-member assigned source ID collision")
    membership: dict[str, list[str]] = {}
    for key, values in ids_by_member.items():
        for value in values:
            membership.setdefault(value, []).append(key)
    collisions = {
        value: members
        for value, members in sorted(membership.items())
        if len(members) > 1
    }
    expected_id_accounting = {
        "collision_count": len(collisions),
        "cross_member_collisions": collisions,
        "occurrence_count": sum(len(values) for values in ids_by_member.values()),
        "three_way_collision_count": sum(
            len(members) > 2 for members in collisions.values()
        ),
        "unique_value_count": len(membership),
        "within_member_duplicate_count": 0,
    }
    if accountability.get("source_id_accounting") != expected_id_accounting:
        raise ValueError("source ID prefix or collision accounting drift")
    expected_top = {}
    expected_direct = {}
    for key in SOURCES:
        top, direct = division_evidence(
            source_trees[key], {source_id for source_id, _ in SOURCES[key][3]}
        )
        expected_top[key] = top
        expected_direct[key] = direct
    if (
        accountability.get("top_level_division_accounting") != expected_top
        or accountability.get("direct_div2_accounting") != expected_direct
    ):
        raise ValueError("division inclusion/exclusion accounting drift")
    # Independently reconstruct and compare every accounting field, not only counts.
    expected_rows, expected_bindings = expected_crosswalk(selected)
    if (
        accountability.get("crosswalk") != expected_rows
        or accountability.get("work_bindings") != expected_bindings
    ):
        raise ValueError("complete source crosswalk or work-binding drift")
    provenance = strict_json(contents["provenance.json"], "provenance")
    if (
        provenance.get("accepted_ir") != "not_accepted"
        or provenance.get("publication_status") != "not_ready"
        or provenance.get("human_accepted") is not False
        or provenance.get("status") != "nonaccepted"
        or provenance.get("implementation_closure") != implementation
    ):
        raise ValueError("provenance disposition drift")
    if provenance.get("works") != expected_bindings:
        raise ValueError("wrong-source or work binding drift")
    for key, (rel, _, digest, _) in SOURCES.items():
        source_record = provenance.get("sources", {}).get(key, {})
        if source_record != {
            "path": rel,
            "sha256": digest,
            "metadata": source_metadata(source_trees[key]),
        }:
            raise ValueError("source metadata evidence drift")
    unresolved = [
        strict_json(line + b"\n", f"unresolved line {i}")
        for i, line in enumerate(contents["unresolved.jsonl"].splitlines(), start=1)
    ]
    if [item.get("id") for item in unresolved] != [
        "lib040-human-acceptance-and-publication",
        "lib040-print-collation-not-performed",
        "lib040-work-credit-allocation",
    ] or any(item.get("status") != "open" for item in unresolved):
        raise ValueError("unresolved decision evidence drift")
    readme = contents["README.source.md"]
    if readme != EXPECTED_README_SOURCE:
        raise ValueError("candidate source attribution README byte drift")
    for phrase in (
        b"CCEL NPNF1-01",
        b"CCEL NPNF1-06",
        b"CCEL NPNF1-07",
        b"J.G. Pilkington, M.A.,",
        b"Translated by the Rev. J. G. Cunningham, M.A.",
        b"the rev. William Findlay, m.a.,",
        b"the rev. s. d. f. salmond, d.d.,",
        b"the rev. r. g. macmullen, m.a.,",
        b"rev. John Gibb, d.d.,",
        b"rev. H. Browne, m.a.,",
        b"rev. charles c. starbuck, a.m.,",
        b"James Innes is not named in assigned `npnf107` root `iii`",
        b"retained front matter outside the assigned scope",
        b"`Rev. James Innes, Panbride.`",
        b"accounted as excluded evidence and is not inserted into the candidate body",
        b"Public Domain",
        b"CCEL permits parsing its ThML; do not sell CCEL files or derivatives of CCEL formatting",
        b"publication-not-ready",
        b"Human textual acceptance and publication authorization remain absent",
    ):
        if phrase not in readme:
            raise ValueError("required source attribution README drift")
    combined = {
        name: sum(census(assigned_nodes[key])[name] for key in SOURCES)
        for name in census(assigned_nodes["npnf101"])
    }
    expected_combined = {
        "elements": 45301,
        "comments": 0,
        "attributes": 120046,
        "text_nodes": 38719,
        "tail_nodes": 39094,
        "characters": 8559314,
        "non_ascii_characters": 52191,
    }
    if combined != expected_combined:
        raise ValueError(f"assigned source census drift: {combined}")
    return {
        "candidate_manifest_sha256": sha(contents["manifest.json"]),
        "candidate_members": {
            name: sha(content) for name, content in sorted(contents.items())
        },
        "feature_count": counter[0],
        "human_accepted": False,
        "oracle": {
            "id": ORACLE_ID,
            "sha256": implementation[ORACLE_KEY],
            "version": ORACLE_VERSION,
        },
        "publication_status": "not_ready",
        "schema": {
            "path": schema_path.name,
            "sha256": sha(schema_path.read_bytes()),
            "valid": True,
        },
        "source_census": combined,
        "source_members": {SOURCES[key][0]: SOURCES[key][2] for key in SOURCES},
        "status": "passed",
        "work_count": 8,
    }


def _oracle(source_manifest: Any, candidate: Any) -> dict[str, object]:
    """Canonical WorkCatalog validator seam for the isolated candidate."""

    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    verify_runtime_closure(root)
    expected_manifest = {
        "path": source_manifest.path.relative_to(root).as_posix(),
        "sha256": source_manifest.sha256,
    }
    if (
        set(candidate.member_names) != EXPECTED_MEMBERS
        or candidate.manifest.get("status") != "nonaccepted"
        or candidate.manifest.get("source_manifest") != expected_manifest
        or candidate.manifest.get("converter") != source_manifest.record["converter"]
        or candidate.manifest.get("package_schema")
        != source_manifest.record["package_schema"]
    ):
        raise ValueError("LIB-040 canonical candidate authority binding drift")
    report = verify(
        root,
        candidate.path,
        source_manifest.authority_path("tei-p5-xsd"),
    )
    if report.get("status") != "passed":
        raise ValueError("LIB-040 producer-independent verification did not pass")
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = strict_json(profile_bytes, "reconstruction profile")
    policy = strict_json(policy_bytes, "validation policy")
    if (
        profile.get("assigned_feature_count") != 45_301
        or profile.get("assigned_attribute_count") != 120_046
        or policy.get("intended_work_catalog_state")
        != {
            "accepted_ir": "not_accepted",
            "blocker": None,
            "human_review": "required",
            "publication": "not_ready",
            "retained_source": "manifest_bound",
            "tei_candidate": "verified",
            "validation": "verified",
        }
    ):
        raise ValueError("LIB-040 staged profile, policy, or route-state drift")
    primary = sorted(
        (
            {
                "name": authority["name"],
                "path": authority["path"],
                "bytes": authority["bytes"],
                "sha256": authority["sha256"],
            }
            for authority in source_manifest.record["authorities"]
            if authority["role"] == "primary-source"
        ),
        key=lambda item: (item["path"], item["name"]),
    )
    source_sha256 = sha(
        canonical_bytes({"contract": "ocd-source-member-set-v1", "members": primary})
    )
    result = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": sha(Path(__file__).resolve().read_bytes()),
        "import_closure_sha256": import_closure_digest(root),
        "runtime": (
            f"{platform.python_implementation()} {platform.python_version()} "
            f"({Path(sys.executable).resolve(strict=True)})"
        ),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": sha(profile_bytes),
        "package_schema_sha256": sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": source_sha256,
        "xsd_sha256": sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = sha(canonical_bytes(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify(
        args.root.resolve(), args.candidate.resolve(), args.schema.resolve()
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(
                report, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
            + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
