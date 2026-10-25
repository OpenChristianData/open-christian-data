"""Deterministic faithful TEI producer for LIB-040's eight assigned works."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any

from lxml import etree

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
SOURCE_SPECS = {
    "npnf101": {
        "path": "raw/ccel/npnf1/npnf101.xml",
        "sha256": "5a251ba0e3ef934821f3998ba1e3ab52ea40dae02ced15fbd36bb111fd81afc0",
        "bytes": 4_837_387,
        "assigned": (
            ("vi", "augustine-confessions"),
            ("vii", "augustine-letters-part-1"),
        ),
    },
    "npnf106": {
        "path": "raw/ccel/npnf1/npnf106.xml",
        "sha256": "3710c6985a8dfc4e4ffafc461a7a8550db609b0506535453dac252f2aa55b604",
        "bytes": 4_680_096,
        "assigned": (
            ("v", "augustine-sermon-on-the-mount"),
            ("vi", "augustine-harmony-of-gospels"),
            ("vii", "augustine-sermons-selected-lessons"),
        ),
    },
    "npnf107": {
        "path": "raw/ccel/npnf1/npnf107.xml",
        "sha256": "75d52f4c31dde0959974256b3f5d84394b7b96fcd2883e78a3d32e0b66c5869a",
        "bytes": 3_694_413,
        "assigned": (
            ("iii", "augustine-tractates-on-john"),
            ("iv", "augustine-homilies-on-first-john"),
            ("v", "augustine-soliloquies"),
        ),
    },
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
PACKAGE_MEMBERS = (
    "README.source.md",
    "content.tei.xml",
    "provenance.json",
    "source-accountability.json",
    "unresolved.jsonl",
)
ADMIN_SCOPE_TITLE = (
    "LIB-040 administrative scope: eight assigned work roots from retained "
    "NPNF First Series volumes 1, 6, and 7"
)
PUBLICATION_NOTICE = "publication:not_ready; human textual acceptance absent."
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


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def tei(
    local: str, attrs: dict[str, str] | None = None, text: str | None = None
) -> etree._Element:
    converted = {}
    for key, value in (attrs or {}).items():
        converted[
            f"{{{XML_NS}}}id"
            if key == "xml:id"
            else f"{{{XML_NS}}}lang"
            if key == "xml:lang"
            else key
        ] = value
    node = etree.Element(f"{{{TEI_NS}}}{local}", converted, nsmap={None: TEI_NS})
    node.text = text
    return node


def parse_source(path: Path) -> etree._ElementTree:
    return etree.parse(
        str(path),
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value)


def selector(node: etree._Element) -> str:
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


def census(nodes: list[etree._Element]) -> dict[str, int]:
    elements = [node for node in nodes if isinstance(node.tag, str)]
    strings = [(node.text or "") + (node.tail or "") for node in nodes]
    return {
        "elements": len(elements),
        "comments": sum(node.tag is etree.Comment for node in nodes),
        "attributes": sum(len(node.attrib) for node in elements),
        "text_nodes": sum(node.text is not None for node in nodes),
        "tail_nodes": sum(node.tail is not None for node in nodes),
        "characters": sum(len(value) for value in strings),
        "non_ascii_characters": sum(
            sum(ord(char) > 127 for char in value) for value in strings
        ),
    }


def element_census(nodes: list[etree._Element]) -> dict[str, int]:
    elements = [node for node in nodes if isinstance(node.tag, str)]
    return {
        "elements": len(elements),
        "attributes": sum(len(node.attrib) for node in elements),
        "text_nodes": sum(node.text is not None for node in elements),
        "tail_nodes": sum(node.tail is not None for node in elements),
        "characters": sum(
            len((node.text or "") + (node.tail or "")) for node in elements
        ),
        "non_ascii_characters": sum(
            sum(ord(char) > 127 for char in (node.text or "") + (node.tail or ""))
            for node in elements
        ),
    }


def document_accounting(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()
    pre_root = []
    node = root.getprevious()
    while node is not None:
        pre_root.append(node)
        node = node.getprevious()
    pre_root.reverse()
    post_root = []
    node = root.getnext()
    while node is not None:
        post_root.append(node)
        node = node.getnext()
    return {
        "doctype": tree.docinfo.doctype,
        "encoding": tree.docinfo.encoding,
        "pre_root_comments": [
            node.text or "" for node in pre_root if node.tag is etree.Comment
        ],
        "pre_root_processing_instructions": [
            {"target": node.target, "text": node.text or ""}
            for node in pre_root
            if node.tag is etree.PI
        ],
        "post_root_nodes": [
            etree.tostring(node, encoding="unicode") for node in post_root
        ],
        "root_attributes": dict(root.attrib),
        "root_namespace_declarations": dict(root.nsmap),
        "root_tag": root.tag,
        "standalone": tree.docinfo.standalone,
        "xml_version": tree.docinfo.xml_version,
    }


def target_tag(source: etree._Element) -> str:
    return (
        "foreign"
        if source.tag == "span" and source.get("lang")
        else TAG_MAP[str(source.tag)]
    )


def tei_attrs(
    source: etree._Element, source_key: str, ordinal: int, work_id: str | None
) -> tuple[dict[str, str], list[dict[str, str]]]:
    source_id = source.get("id")
    attrs = {
        "xml:id": f"lib040-{safe_id(work_id)}"
        if work_id
        else f"lib040-{source_key}-{safe_id(source_id) if source_id else f'feature-{ordinal:05d}'}"
    }
    dispositions = []
    tag = str(source.tag)
    for name, value in source.attrib.items():
        destination, method = "source-accountability", "preserved-exactly"
        if name == "id":
            destination, method = "@xml:id", "deterministic-source-or-work-prefix"
        elif name == "n" and tag in {"div1", "div2", "div3", "div4", "note", "pb"}:
            attrs["n"], destination = value, "@n"
        elif name == "type" and tag in {"div1", "div2", "div3", "div4"}:
            attrs["type"], destination = value, "@type"
        elif name == "class":
            attrs["rend"], destination = value, "@rend"
        elif name == "place" and tag == "note":
            attrs["place"], destination = value, "@place"
        elif name == "href" and tag == "pb":
            attrs["facs"], destination = value, "@facs"
        elif name == "passage" and tag in {"scripRef", "scripCom"}:
            attrs["cRef"], destination = value, "@cRef"
        elif name == "osisRef" and tag in {"scripRef", "scripCom"}:
            attrs["target"], destination = value, "@target"
        elif name == "lang" and tag == "span":
            attrs["xml:lang"] = "grc" if value == "EL" else value.lower()
            destination, method = "@xml:lang", "declared-language-code-map"
        elif name == "title" and tag.startswith("div"):
            destination = "child::head[1]"
        dispositions.append(
            {
                "destination": destination,
                "method": method,
                "source_attribute": name,
                "source_value": value,
            }
        )
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
    return attrs, dispositions


def append_source(
    source: etree._Element,
    parent: etree._Element,
    source_key: str,
    rows: list[dict[str, Any]],
    parent_feature_id: str | None,
    work_id: str | None = None,
) -> None:
    ordinal = len(rows) + 1
    feature_id = f"lib040-feature-{ordinal:05d}"
    if source.tag is etree.Comment:
        target = etree.Comment(source.text or "")
        target.tail = source.tail
        parent.append(target)
        rows.append(
            {
                "feature_id": feature_id,
                "kind": "comment",
                "parent_feature_id": parent_feature_id,
                "source_member": source_key,
                "source_selector": selector(source),
                "text": source.text or "",
                "tail_text": source.tail or "",
                "text_sha256": sha((source.text or "").encode()),
                "tail_text_sha256": sha((source.tail or "").encode()),
                "disposition": "represented-as-xml-comment",
            }
        )
        return
    if str(source.tag) not in TAG_MAP:
        raise ValueError(f"unsupported retained source element {source.tag!r}")
    attrs, dispositions = tei_attrs(source, source_key, ordinal, work_id)
    target = tei(target_tag(source), attrs)
    title = source.get("title") if str(source.tag).startswith("div") else None
    target.text = source.text
    if title is not None:
        target.append(tei("head", text=title))
    target.tail = source.tail
    parent_local = etree.QName(parent).localname
    wrapper_id = None
    if parent_local == "div" and target_tag(source) in {"ref", "seg", "foreign", "hi"}:
        wrapper_id = f"lib040-inline-container-{ordinal:05d}"
        wrapper = tei("ab", {"xml:id": wrapper_id, "type": "source-inline-container"})
        wrapper.append(target)
        parent.append(wrapper)
    else:
        parent.append(target)
    row: dict[str, Any] = {
        "attribute_dispositions": dispositions,
        "attributes": dict(source.attrib),
        "direct_text": source.text or "",
        "direct_text_sha256": sha((source.text or "").encode()),
        "disposition": "represented",
        "feature_id": feature_id,
        "kind": "element",
        "parent_feature_id": parent_feature_id,
        "source_member": source_key,
        "source_selector": selector(source),
        "source_tag": source.tag,
        "source_title_head": title,
        "source_xml_id": source.get("id"),
        "tail_text": source.tail or "",
        "tail_text_sha256": sha((source.tail or "").encode()),
        "tei_attributes": attrs,
        "tei_tag": target_tag(source),
        "tei_xml_id": attrs["xml:id"],
        "tei_wrapper_id": wrapper_id,
    }
    if work_id:
        row["work_id"] = work_id
    rows.append(row)
    for child in source:
        append_source(child, target, source_key, rows, feature_id)


def metadata(tree: etree._ElementTree) -> dict[str, object]:
    head = tree.getroot().find("ThML.head")
    if head is None:
        raise ValueError("retained source has no ThML.head")
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


def division_accounting(
    tree: etree._ElementTree, selected_ids: set[str]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained source has no ThML.body")
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


def make_header(trees: dict[str, etree._ElementTree]) -> etree._Element:
    root = tei("TEI", {"xml:id": "lib040-candidate"})
    header, file_desc, title_stmt = tei("teiHeader"), tei("fileDesc"), tei("titleStmt")
    title_stmt.append(tei("title", {"type": "generated"}, ADMIN_SCOPE_TITLE))
    title_stmt.append(tei("editor", text="Philip Schaff"))
    file_desc.append(title_stmt)
    publication = tei("publicationStmt")
    publication.append(tei("p", text=PUBLICATION_NOTICE))
    file_desc.append(publication)
    source_desc, list_bibl = tei("sourceDesc"), tei("listBibl")
    for key in SOURCE_SPECS:
        tree = trees[key]
        bibl = tei("bibl", {"xml:id": f"source-{key}"})
        values = [
            (
                "title",
                "".join(
                    str(v)
                    for v in tree.xpath(
                        "/ThML/ThML.head/electronicEdInfo/DC/DC.Title[not(@sub)]/text()"
                    )
                ),
                None,
            ),
            (
                "editor",
                "".join(
                    str(v)
                    for v in tree.xpath(
                        "/ThML/ThML.head/electronicEdInfo/DC/"
                        "DC.Creator[@sub='Editor'][@scheme='short-form']/text()"
                    )
                ),
                None,
            ),
            (
                "publisher",
                "".join(
                    str(v)
                    for v in tree.xpath(
                        "/ThML/ThML.head/electronicEdInfo/DC/DC.Publisher/text()"
                    )
                ),
                None,
            ),
            (
                "note",
                "".join(
                    str(v)
                    for v in tree.xpath(
                        "/ThML/ThML.head/printSourceInfo/published/text()"
                    )
                ),
                {"type": "print-publication-statement"},
            ),
            (
                "note",
                "".join(
                    str(v)
                    for v in tree.xpath(
                        "/ThML/ThML.head/electronicEdInfo/DC/DC.Rights/text()"
                    )
                ),
                {"type": "rights"},
            ),
        ]
        for tag, value, attrs in values:
            bibl.append(tei(tag, attrs, value))
        url = "".join(
            str(v)
            for v in tree.xpath(
                "/ThML/ThML.head/electronicEdInfo/DC/DC.Identifier[@scheme='URL']/text()"
            )
        )
        bibl.append(tei("ref", {"target": f"https://www.ccel.org{url}"}, url))
        list_bibl.append(bibl)
    source_desc.append(list_bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    root.append(header)
    return root


def _produce_legacy(root_dir: Path, output_dir: Path) -> dict[str, bytes]:
    implementation_root, package_root, source_local_root = local_layout()
    producer_path = (
        implementation_root / "producer.py"
        if (implementation_root / "producer.py").is_file()
        else implementation_root / "npnf1_lib040_reconstruction.py"
    )
    oracle_path = (
        implementation_root / "oracle.py"
        if (implementation_root / "oracle.py").is_file()
        else implementation_root / "npnf1_lib040_oracle.py"
    )
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
    source_manifest_path = source_local_root / "lib040.source-manifest.json"
    source_manifest_bytes = source_manifest_path.read_bytes()
    source_manifest = json.loads(source_manifest_bytes.decode("utf-8"))
    if (
        source_manifest.get("contract") != "ocd-source-manifest-v1"
        or source_manifest.get("source_id") != "ccel-npnf1-lib040-cohort"
        or source_manifest.get("converter", {}).get("implementation_sha256")
        != implementation[PRODUCER_KEY]
        or source_manifest.get("validator", {}).get("implementation_sha256")
        != implementation[ORACLE_KEY]
    ):
        raise ValueError("LIB-040 canonical-shaped source manifest drifted")
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
        content = authority_path.read_bytes()
        if authority.get("bytes") != len(content) or authority.get("sha256") != sha(
            content
        ):
            raise ValueError(f"source-manifest authority drift: {name}")
    package_schema_path = (
        package_root
        / "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"
    )
    trees, selected = {}, {}
    for key, spec in SOURCE_SPECS.items():
        path = root_dir / str(spec["path"])
        content = path.read_bytes()
        if len(content) != spec["bytes"] or sha(content) != spec["sha256"]:
            raise ValueError(f"retained {key} authority drifted")
        tree = parse_source(path)
        trees[key] = tree
        selected[key] = []
        for source_id, work_id in spec["assigned"]:
            matches = tree.xpath("//*[@id=" + repr(source_id) + "]")
            if len(matches) != 1:
                raise ValueError(f"retained {key} root {source_id!r} drifted")
            selected[key].append((matches[0], work_id))
    root = make_header(trees)
    text, body = tei("text"), tei("body", {"xml:id": "lib040-assigned-body"})
    text.append(body)
    root.append(text)
    crosswalk, work_bindings = [], []
    for key in SOURCE_SPECS:
        for source_root, work_id in selected[key]:
            before = len(crosswalk)
            append_source(source_root, body, key, crosswalk, None, work_id)
            work_bindings.append(
                {
                    "feature_count": len(crosswalk) - before,
                    "source_member": str(SOURCE_SPECS[key]["path"]),
                    "source_root_id": source_root.get("id"),
                    "source_root_selector": selector(source_root),
                    "work_id": work_id,
                }
            )
    tei_bytes = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    member_records, top_accounts, direct_accounts = [], {}, {}
    for key, spec in SOURCE_SPECS.items():
        assigned_nodes = [
            node for source_root, _ in selected[key] for node in source_root.iter()
        ]
        complete_nodes = list(trees[key].getroot().iter())
        assigned_census, complete_census = (
            census(assigned_nodes),
            census(complete_nodes),
        )
        excluded = {
            name: complete_census[name] - assigned_census[name]
            for name in complete_census
        }
        top, direct = division_accounting(
            trees[key], {source_id for source_id, _ in spec["assigned"]}
        )
        top_accounts[key], direct_accounts[key] = top, direct
        assigned_elements = [
            node for node in assigned_nodes if isinstance(node.tag, str)
        ]
        excluded_roots = [
            node
            for node in trees[key].xpath("/ThML/ThML.body/div1")
            if node.get("id") not in {source_id for source_id, _ in spec["assigned"]}
        ]
        excluded_elements = [
            node
            for source_root in excluded_roots
            for node in source_root.iter()
            if isinstance(node.tag, str)
        ]
        occupied = {id(node) for node in assigned_elements + excluded_elements}
        complete_elements = [
            node for node in complete_nodes if isinstance(node.tag, str)
        ]
        shell_elements = [
            node for node in complete_elements if id(node) not in occupied
        ]
        member_records.append(
            {
                "assigned_scope_census": assigned_census,
                "bytes": spec["bytes"],
                "complete_document_census": complete_census,
                "document_accounting": document_accounting(trees[key]),
                "document_shell_census": element_census(shell_elements),
                "disposition": "included as retained authority; assigned roots represented and every other division explicitly excluded",
                "excluded_division_census": element_census(excluded_elements),
                "excluded_scope_census": excluded,
                "path": spec["path"],
                "sha256": spec["sha256"],
            }
        )
    ids_by_member: dict[str, list[str]] = {
        key: [
            str(node.get("id"))
            for source_root, _ in selected[key]
            for node in source_root.iter()
            if isinstance(node.tag, str) and node.get("id") is not None
        ]
        for key in SOURCE_SPECS
    }
    id_members: dict[str, list[str]] = {}
    for key, values in ids_by_member.items():
        if len(values) != len(set(values)):
            raise ValueError(f"retained {key} contains duplicate assigned source IDs")
        for value in values:
            id_members.setdefault(value, []).append(key)
    collisions = {
        value: members
        for value, members in sorted(id_members.items())
        if len(members) > 1
    }
    scope_totals = {
        scope: {
            field: sum(record[f"{scope}_census"][field] for record in member_records)
            for field in next(iter(member_records))[f"{scope}_census"]
        }
        for scope in ("assigned_scope", "document_shell", "excluded_division")
    }
    accountability = {
        "assigned_work_count": 8,
        "contract": "ocd-lib040-source-accountability-v1",
        "crosswalk": crosswalk,
        "direct_div2_accounting": direct_accounts,
        "duplicate_feature_count": 0,
        "feature_count": len(crosswalk),
        "member_accounting": member_records,
        "omitted_feature_count": 0,
        "profile_id": "lib040-npnf101-vi-vii-npnf106-v-vii-npnf107-iii-v-v1",
        "schema": "lib040.source-accountability.schema.json",
        "source_scope": "eight complete retained ThML.body div1 roots across npnf101, npnf106, and npnf107",
        "source_member_count": 3,
        "scope_reconciliation": scope_totals,
        "source_id_accounting": {
            "collision_count": len(collisions),
            "cross_member_collisions": collisions,
            "occurrence_count": sum(len(values) for values in ids_by_member.values()),
            "three_way_collision_count": sum(
                len(members) > 2 for members in collisions.values()
            ),
            "unique_value_count": len(id_members),
            "within_member_duplicate_count": 0,
        },
        "top_level_division_accounting": top_accounts,
        "unresolved_feature_count": 0,
        "work_bindings": work_bindings,
    }
    provenance = {
        "accepted_ir": "not_accepted",
        "contract": "ocd-lib040-provenance-v1",
        "human_accepted": False,
        "implementation_closure": implementation,
        "publication_status": "not_ready",
        "sources": {
            key: {
                "metadata": metadata(trees[key]),
                "path": spec["path"],
                "sha256": spec["sha256"],
            }
            for key, spec in SOURCE_SPECS.items()
        },
        "status": "nonaccepted",
        "works": work_bindings,
    }
    unresolved = [
        {
            "id": "lib040-human-acceptance-and-publication",
            "owner": "project-maintainer",
            "status": "open",
            "summary": "Human textual acceptance and publication authorization are separate and absent.",
        },
        {
            "id": "lib040-print-collation-not-performed",
            "owner": "project-maintainer",
            "status": "open",
            "summary": "The retained electronic witnesses have not been collated against the cited print editions.",
        },
        {
            "id": "lib040-work-credit-allocation",
            "owner": "project-maintainer",
            "status": "open",
            "summary": "Work-level translator and contributor allocation is not asserted beyond exact source content retained in the work roots.",
        },
    ]
    readme = (
        "# LIB-040 retained sources\n\nThis nonaccepted, publication-not-ready candidate was reconstructed deterministically from exact retained `npnf101.xml`, `npnf106.xml`, and `npnf107.xml` witnesses.\n\nThe retained electronic metadata names Philip Schaff as editor, identifies the underlying texts as Public Domain, and cites the 1886 Christian Literature Publishing Co. print editions recorded in `provenance.json`. The assigned source-root title pages retain these exact source forms: `J.G. Pilkington, M.A.,`; `Translated by the Rev. J. G. Cunningham, M.A.`; `the rev. William Findlay, m.a.,`; `the rev. s. d. f. salmond, d.d.,`; `the rev. r. g. macmullen, m.a.,` (split across three retained spans); `rev. John Gibb, d.d.,`; `rev. H. Browne, m.a.,`; and `rev. charles c. starbuck, a.m.,`. James Innes is not named in assigned `npnf107` root `iii`; retained front matter outside the assigned scope, in `npnf107` root `ii`, supplies the exact credit `Rev. James Innes, Panbride.` That front matter is accounted as excluded evidence and is not inserted into the candidate body. No work-level credit is inferred beyond these exact retained locations and forms. The electronic witnesses are sourced via [CCEL NPNF1-01](https://www.ccel.org/ccel/schaff/npnf101.html), [CCEL NPNF1-06](https://www.ccel.org/ccel/schaff/npnf106.html), and [CCEL NPNF1-07](https://www.ccel.org/ccel/schaff/npnf107.html). CCEL permits parsing its ThML; do not sell CCEL files or derivatives of CCEL formatting. Human textual acceptance and publication authorization remain absent.\n"
    ).encode()
    files = {
        "README.source.md": readme,
        "content.tei.xml": tei_bytes,
        "provenance.json": canonical_json(provenance),
        "source-accountability.json": canonical_json(accountability),
        "unresolved.jsonl": b"".join(canonical_json(item) for item in unresolved),
    }
    manifest = {
        "contract": "ocd-candidate-package-v1",
        "converter": {
            "id": "ocd-lib040-retained-thml-to-tei",
            "callable": "produce",
            "implementation_path": "build/tei/npnf1_lib040_reconstruction.py",
            "implementation_sha256": implementation[PRODUCER_KEY],
            "version": "1",
        },
        "members": [
            {"bytes": len(files[name]), "name": name, "sha256": sha(files[name])}
            for name in PACKAGE_MEMBERS
        ],
        "package_schema": {
            "path": "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
            "sha256": sha(package_schema_path.read_bytes()),
        },
        "source_id": "ccel-npnf1-lib040-cohort",
        "source_manifest": {
            "path": f"{CANONICAL_SOURCE_LOCAL}/lib040.source-manifest.json",
            "sha256": sha(source_manifest_bytes),
        },
        "status": "nonaccepted",
    }
    files["manifest.json"] = canonical_json(manifest)
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = {path.name for path in output_dir.iterdir() if path.is_file()}
    if existing and existing != set(files):
        raise ValueError(
            f"candidate output has stale or unexpected members: {sorted(existing)}"
        )
    for name, content in files.items():
        (output_dir / name).write_bytes(content)
    return files


def produce(source_manifest: Any) -> dict[str, bytes]:
    """Adapt the recovered deterministic builder to the maintained contract."""

    repository_root = Path(source_manifest.repository_root).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="ocd-lib040-producer-") as temp_name:
        generated = _produce_legacy(repository_root, Path(temp_name))
        return {name: generated[name] for name in PACKAGE_MEMBERS}


produce.converter_id = "ocd-lib040-retained-thml-to-tei"
produce.converter_version = "1"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _produce_legacy(args.root.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
