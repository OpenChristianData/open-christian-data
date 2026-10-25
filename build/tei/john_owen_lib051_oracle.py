"""Producer-independent retained-source oracle for LIB-051."""

from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import sys
from typing import Any, Mapping

import jsonschema
from lxml import etree

from build.lib.tei_xsd import compiled_tei_schema
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-john-owen-lib051-retained-xml-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
MEMBERS = {
    "README.source.md",
    "content.tei.xml",
    "manifest.json",
    "provenance.json",
    "source-accountability.json",
    "unresolved.jsonl",
}
TEI = {"tei": TEI_NS}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(content.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}") from exc


def _parse_source(content: bytes) -> etree._ElementTree:
    try:
        return etree.parse(
            io.BytesIO(content),
            etree.XMLParser(
                resolve_entities=False,
                load_dtd=False,
                no_network=True,
                remove_comments=False,
                remove_pis=False,
                huge_tree=True,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("LIB-051 retained XML parse failure") from exc


def _kind(node: etree._Element) -> str:
    if node.tag is etree.Comment:
        return "comment"
    if node.tag is etree.PI:
        return "processing-instruction"
    if isinstance(node.tag, str):
        return "element"
    raise ValueError("unsupported retained XML node")


def _document_nodes(tree: etree._ElementTree) -> list[tuple[str, etree._Element]]:
    root = tree.getroot()
    before = []
    node = root.getprevious()
    while node is not None:
        before.append(node)
        node = node.getprevious()
    after = []
    node = root.getnext()
    while node is not None:
        after.append(node)
        node = node.getnext()
    result = [("pre-root", item) for item in reversed(before)]

    def walk(current: etree._Element) -> None:
        result.append(("tree", current))
        for child in current:
            walk(child)

    walk(root)
    result.extend(("post-root", item) for item in after)
    return result


def _records(tree: etree._ElementTree, member_id: str) -> tuple[dict[str, Any], ...]:
    nodes = _document_nodes(tree)
    ordinals = {id(node): ordinal for ordinal, (_scope, node) in enumerate(nodes, 1)}
    result = []
    for ordinal, (scope, node) in enumerate(nodes, 1):
        parent = node.getparent()
        siblings = list(parent) if parent is not None else [node]
        kind = _kind(node)
        record = {
            "feature_id": f"{member_id}-node-{ordinal:06d}",
            "ordinal": ordinal,
            "scope": scope,
            "kind": kind,
            "qname": str(node.tag) if kind == "element" else None,
            "pi_target": node.target if kind == "processing-instruction" else None,
            "attributes": (
                [[str(name), value] for name, value in node.attrib.items()]
                if kind == "element"
                else []
            ),
            "namespace_declarations": (
                [
                    ["" if name is None else name, value]
                    for name, value in node.nsmap.items()
                ]
                if kind == "element"
                else []
            ),
            "text": node.text or "",
            "tail": node.tail or "",
            "parent_ordinal": ordinals.get(id(parent)),
            "sibling_ordinal": siblings.index(node) + 1,
        }
        record["payload_sha256"] = _sha(_canonical(record))
        result.append(record)
    return tuple(result)


def _first(tree: etree._ElementTree, expression: str) -> str:
    return "".join(str(value) for value in tree.xpath(expression)).strip()


def _metadata(tree: etree._ElementTree) -> dict[str, Any]:
    root = tree.getroot()
    comments = [
        node.text or ""
        for _scope, node in _document_nodes(tree)
        if _kind(node) == "comment"
    ]
    return {
        "title": _first(
            tree, "/ThML/ThML.head/electronicEdInfo/DC/DC.Title[not(@sub)]/text()"
        ),
        "creator": _first(
            tree,
            "/ThML/ThML.head/electronicEdInfo/DC/DC.Creator[@sub='Author'][1]/text()",
        ),
        "electronic_publisher": _first(
            tree, "/ThML/ThML.head/electronicEdInfo/DC/DC.Publisher/text()"
        ),
        "print_source": _first(
            tree, "/ThML/ThML.head/printSourceInfo/published/text()"
        ),
        "rights": _first(tree, "/ThML/ThML.head/electronicEdInfo/DC/DC.Rights/text()"),
        "status": _first(tree, "/ThML/ThML.head/electronicEdInfo/status/text()"),
        "editorial_comments": _first(
            tree, "/ThML/ThML.head/electronicEdInfo/editorialComments/text()"
        ),
        "source_url": _first(
            tree,
            "/ThML/ThML.head/electronicEdInfo/DC/DC.Identifier[@scheme='URL']/text()",
        ),
        "xml_version": tree.docinfo.xml_version,
        "encoding": tree.docinfo.encoding,
        "doctype": tree.docinfo.doctype,
        "root_qname": str(root.tag),
        "root_attributes": [[str(name), value] for name, value in root.attrib.items()],
        "root_namespace_declarations": [
            ["" if name is None else name, value] for name, value in root.nsmap.items()
        ],
        "ccel_copyright_comment_present": any(
            "Copyright Christian Classics Ethereal Library" in text for text in comments
        ),
    }


def _expected_evidence(
    source_manifest: SourceManifest,
    profile: Mapping[str, Any],
    prepared: list[
        tuple[Mapping[str, Any], bytes, etree._ElementTree, tuple[dict[str, Any], ...]]
    ],
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    works = []
    for work, content, tree, records in prepared:
        works.append(
            {
                "work_id": work["work_id"],
                "authority_name": work["authority_name"],
                "path": work["path"],
                "bytes": len(content),
                "sha256": _sha(content),
                "node_count": len(records),
                "node_kind_counts": {
                    kind: sum(row["kind"] == kind for row in records)
                    for kind in ("element", "comment", "processing-instruction")
                },
                "attribute_count": sum(len(row["attributes"]) for row in records),
                "text_character_count": sum(len(row["text"]) for row in records),
                "tail_character_count": sum(len(row["tail"]) for row in records),
                "metadata": _metadata(tree),
                "omitted_node_count": 0,
                "duplicate_node_count": 0,
                "invented_node_count": 0,
            }
        )
    accountability = {
        "contract": "ocd-john-owen-lib051-source-accountability-v1",
        "profile_id": profile["profile_id"],
        "assigned_work_count": 10,
        "included_member_count": 10,
        "adjacent_member_count": 22,
        "total_node_count": sum(row["node_count"] for row in works),
        "works": works,
        "adjacent_retained_member_accounting": profile[
            "adjacent_retained_member_accounting"
        ],
    }
    provenance = {
        "contract": "ocd-john-owen-lib051-provenance-v1",
        "status": "nonaccepted",
        "publication_state": "not_ready",
        "source_id": source_manifest.record["source_id"],
        "source_credit": "sourced via CCEL.org",
        "rights": {
            "underlying_historic_works": "public-domain",
            "ccel_file_and_formatting": "restricted-human-review-required",
            "ages_electronic_base_assertion": "unresolved-for-seven-works",
            "publication_ready": False,
        },
        "works": [
            {
                "work_id": row["work_id"],
                "title": row["metadata"]["title"],
                "source_path": row["path"],
                "source_sha256": row["sha256"],
                "source_bytes": row["bytes"],
                "electronic_publisher": row["metadata"]["electronic_publisher"],
                "print_source": row["metadata"]["print_source"],
                "editorial_comments": row["metadata"]["editorial_comments"],
                "source_status": row["metadata"]["status"],
                "source_rights_text": row["metadata"]["rights"],
                "source_url": row["metadata"]["source_url"],
                "human_review": "required",
                "accepted_ir": "not_accepted",
                "publication": "not_ready",
            }
            for row in works
        ],
        "canonical_data_written": False,
        "canonical_ir_written": False,
    }
    ages_ids = [
        row["work_id"]
        for row in works
        if "AGES Software" in row["metadata"]["editorial_comments"]
    ]
    unresolved = [
        {
            "id": "lib051-ages-electronic-base-rights",
            "scope": ages_ids,
            "status": "unresolved",
            "question": "What rights attach to the AGES-derived electronic base text?",
            "evidence": "Seven retained headers assert an AGES Software copyright while DC.Rights is empty.",
            "consequence": "Keep the candidate nonaccepted, restricted, and not publication-ready.",
        },
        {
            "id": "lib051-edition-and-proofreading",
            "scope": [row["work_id"] for row in works],
            "status": "unresolved",
            "question": "Has each retained electronic witness been accepted as the intended edition and text?",
            "evidence": "Retained CCEL headers identify differing Banner reprints and mixed proof-read states.",
            "consequence": "Human edition and textual review remains required.",
        },
        {
            "id": "lib051-poema-map-hole",
            "scope": ["raw/ccel/owen/poema.xml"],
            "status": "unresolved",
            "question": "Should the retained Latin Poema witness receive a future work identity?",
            "evidence": "poema.xml is retained but absent from the frozen WorkCatalog and ticket maps.",
            "consequence": "Exclude it from LIB-051 and surface the map hole to LIB-090 without changing maps here.",
        },
    ]
    return accountability, provenance, b"".join(_canonical(row) for row in unresolved)


def _expected_header(metadata: Mapping[str, Any]) -> etree._Element:
    def el(
        name: str, attrs: Mapping[str, str] | None = None, text: str | None = None
    ) -> etree._Element:
        node = etree.Element(f"{{{TEI_NS}}}{name}")
        for key, value in (attrs or {}).items():
            node.set(key, value)
        node.text = text
        return node

    header = el("teiHeader")
    file_desc = el("fileDesc")
    title_stmt = el("titleStmt")
    title_stmt.append(el("title", text=str(metadata["title"])))
    title_stmt.append(el("author", text=str(metadata["creator"])))
    resp = el("respStmt")
    resp.append(el("resp", text="Retained electronic edition and ThML markup"))
    resp.append(el("name", text=str(metadata["electronic_publisher"])))
    title_stmt.append(resp)
    file_desc.append(title_stmt)
    publication = el("publicationStmt")
    publication.append(el("publisher", text="Open Christian Data"))
    availability = el("availability", {"status": "restricted"})
    availability.append(
        el(
            "p",
            text="Nonaccepted technical reconstruction; human rights, edition, and textual review required; publication not ready.",
        )
    )
    publication.append(availability)
    file_desc.append(publication)
    source_desc = el("sourceDesc")
    bibl = el("bibl", {"type": "retained-electronic-witness"})
    bibl.append(el("title", text=str(metadata["title"])))
    bibl.append(el("author", text=str(metadata["creator"])))
    bibl.append(el("publisher", text=str(metadata["electronic_publisher"])))
    bibl.append(el("note", {"type": "print-source"}, str(metadata["print_source"])))
    bibl.append(el("note", {"type": "rights"}, str(metadata["rights"])))
    bibl.append(
        el("note", {"type": "editorial-comments"}, str(metadata["editorial_comments"]))
    )
    bibl.append(el("idno", {"type": "CCEL-path"}, str(metadata["source_url"])))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    return header


def _expected_corpus_header() -> etree._Element:
    def el(
        name: str, attrs: Mapping[str, str] | None = None, text: str | None = None
    ) -> etree._Element:
        node = etree.Element(f"{{{TEI_NS}}}{name}")
        for key, value in (attrs or {}).items():
            node.set(key, value)
        node.text = text
        return node

    header = el("teiHeader")
    file_desc = el("fileDesc")
    title_stmt = el("titleStmt")
    title_stmt.append(el("title", text="LIB-051 John Owen retained-source cohort"))
    file_desc.append(title_stmt)
    publication = el("publicationStmt")
    publication.append(el("publisher", text="Open Christian Data"))
    availability = el("availability", {"status": "restricted"})
    availability.append(
        el("p", text="Nonaccepted technical reconstruction; publication not ready.")
    )
    publication.append(availability)
    file_desc.append(publication)
    source_desc = el("sourceDesc")
    source_desc.append(
        el(
            "p",
            text="Ten exact retained CCEL ThML XML authorities; sourced via CCEL.org.",
        )
    )
    file_desc.append(source_desc)
    header.append(file_desc)
    return header


def _expected_tei(
    prepared: list[
        tuple[Mapping[str, Any], bytes, etree._ElementTree, tuple[dict[str, Any], ...]]
    ],
) -> bytes:
    """Independently reconstruct the required serialized TEI document bytes."""

    def el(
        name: str, attrs: Mapping[str, str] | None = None, text: str | None = None
    ) -> etree._Element:
        node = etree.Element(f"{{{TEI_NS}}}{name}")
        for key, value in (attrs or {}).items():
            node.set(XML_ID if key == "xml:id" else key, value)
        node.text = text
        return node

    corpus = el("teiCorpus", {"xml:id": "john-owen-lib051-candidate"})
    corpus.append(_expected_corpus_header())
    for work, content, tree, records in prepared:
        metadata = _metadata(tree)
        tei = el("TEI", {"xml:id": str(work["work_id"])})
        tei.append(_expected_header(metadata))
        text = el("text")
        body = el("body")
        division = el("div", {"type": "retained-source-member"})
        division.append(el("head", text=str(metadata["title"])))
        division.append(
            el(
                "ab",
                {
                    "type": "exact-retained-source-bytes",
                    "subtype": "base64",
                    "n": _sha(content),
                },
                base64.b64encode(content).decode("ascii"),
            )
        )
        transcription = el("div", {"type": "complete-xml-node-transcription"})
        for record in records:
            transcription.append(
                el(
                    "ab",
                    {
                        "xml:id": str(record["feature_id"]),
                        "type": "source-xml-node",
                        "subtype": str(record["kind"]),
                        "n": str(record["ordinal"]),
                    },
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
            )
        division.append(transcription)
        body.append(division)
        text.append(body)
        tei.append(text)
        corpus.append(tei)
    return etree.tostring(
        corpus, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )


def _verify_tei(
    candidate: CandidatePackage,
    prepared: list[
        tuple[Mapping[str, Any], bytes, etree._ElementTree, tuple[dict[str, Any], ...]]
    ],
    xsd_path: Path,
) -> None:
    serialized = candidate.member_bytes("content.tei.xml")
    if serialized != _expected_tei(prepared):
        raise ValueError("LIB-051 exact serialized TEI document bytes drift")
    try:
        tree = etree.parse(
            io.BytesIO(serialized),
            etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                remove_comments=False,
                remove_pis=False,
                huge_tree=True,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("LIB-051 candidate TEI parse failure") from exc
    try:
        compiled_tei_schema(xsd_path).assertValid(tree)
    except etree.DocumentInvalid as exc:
        raise ValueError("LIB-051 candidate fails TEI P5 XSD") from exc
    root = tree.getroot()
    if (
        root.tag != f"{{{TEI_NS}}}teiCorpus"
        or root.get(XML_ID) != "john-owen-lib051-candidate"
        or len(root) != 11
        or root.text
        or root.tail
    ):
        raise ValueError("LIB-051 TEI corpus topology drift")
    if etree.tostring(root[0], method="c14n", with_comments=True) != etree.tostring(
        _expected_corpus_header(), method="c14n", with_comments=True
    ):
        raise ValueError("LIB-051 corpus header drift")
    for tei, (work, content, source_tree, records) in zip(
        root[1:], prepared, strict=True
    ):
        if (
            tei.tag != f"{{{TEI_NS}}}TEI"
            or tei.get(XML_ID) != work["work_id"]
            or len(tei) != 2
            or tei.text
            or tei.tail
        ):
            raise ValueError("LIB-051 TEI work identity or topology drift")
        expected_header = _expected_header(_metadata(source_tree))
        if etree.tostring(tei[0], method="c14n", with_comments=True) != etree.tostring(
            expected_header, method="c14n", with_comments=True
        ):
            raise ValueError(
                "LIB-051 TEI header metadata, publisher, responsibility, print, or rights drift"
            )
        bodies = tei.xpath(
            "./tei:text/tei:body/tei:div[@type='retained-source-member']",
            namespaces=TEI,
        )
        if len(bodies) != 1 or len(bodies[0]) != 3:
            raise ValueError("LIB-051 TEI retained-source topology drift")
        division = bodies[0]
        raw_nodes = division.xpath(
            "./tei:ab[@type='exact-retained-source-bytes']", namespaces=TEI
        )
        transcript = division.xpath(
            "./tei:div[@type='complete-xml-node-transcription']", namespaces=TEI
        )
        if (
            len(raw_nodes) != 1
            or len(transcript) != 1
            or raw_nodes[0].get("subtype") != "base64"
            or raw_nodes[0].get("n") != _sha(content)
        ):
            raise ValueError("LIB-051 exact retained-byte binding drift")
        try:
            decoded = base64.b64decode(
                (raw_nodes[0].text or "").encode("ascii"), validate=True
            )
        except (UnicodeEncodeError, ValueError) as exc:
            raise ValueError("LIB-051 retained-byte base64 drift") from exc
        if decoded != content:
            raise ValueError("LIB-051 retained-byte omission or invention")
        nodes = list(transcript[0])
        if len(nodes) != len(records):
            raise ValueError("LIB-051 XML node omission, duplication, or invention")
        for node, expected in zip(nodes, records, strict=True):
            attrs = {
                "xml:id": node.get(XML_ID),
                **{key: value for key, value in node.attrib.items() if key != XML_ID},
            }
            expected_attrs = {
                "xml:id": expected["feature_id"],
                "type": "source-xml-node",
                "subtype": expected["kind"],
                "n": str(expected["ordinal"]),
            }
            if (
                etree.QName(node).localname != "ab"
                or attrs != expected_attrs
                or len(node)
                or node.tail
                or _strict_json((node.text or "").encode(), "TEI node record")
                != expected
            ):
                raise ValueError(
                    "LIB-051 QName, attributes, order, text, tail, namespace, comment, or PI drift"
                )


def _first_party_module_path(root: Path, module: str) -> Path | None:
    direct = root.joinpath(*module.split(".")).with_suffix(".py")
    package = root.joinpath(*module.split("."), "__init__.py")
    return direct if direct.is_file() else package if package.is_file() else None


def _imported_module_names(
    current_module: str, current_path: Path, node: ast.Import | ast.ImportFrom
) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if not node.level:
        if not node.module:
            return ()
        return (node.module,)
    package_parts = current_module.split(
        "." if current_path.name == "__init__.py" else ".", -1
    )
    if current_path.name != "__init__.py":
        package_parts = package_parts[:-1]
    ascend = node.level - 1
    if ascend > len(package_parts):
        raise ValueError("LIB-051 oracle closure has invalid relative import")
    base = package_parts[: len(package_parts) - ascend]
    if node.module:
        return (".".join((*base, *node.module.split("."))),)
    return tuple(".".join((*base, alias.name)) for alias in node.names)


def _closure_paths(root: Path, policy: Mapping[str, Any]) -> tuple[Path, ...]:
    forbidden = tuple(policy.get("forbidden_oracle_imports", []))
    pending = ["build.tei.john_owen_lib051_oracle"]
    modules: dict[str, Path] = {}
    while pending:
        module = pending.pop()
        if module in modules:
            continue
        path = _first_party_module_path(root, module)
        if path is None:
            continue
        modules[module] = path
        parsed = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(parsed):
            names: tuple[str, ...] = ()
            if isinstance(node, ast.Import | ast.ImportFrom):
                names = _imported_module_names(module, path, node)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "eval", "exec"}
            ):
                raise ValueError("LIB-051 oracle closure contains dynamic execution")
            for name in names:
                if any(
                    name == prefix or name.startswith(prefix + ".")
                    for prefix in forbidden
                ):
                    raise ValueError(
                        f"LIB-051 oracle closure contains forbidden import {name}"
                    )
                found = _first_party_module_path(root, name)
                if found is not None:
                    pending.append(name)
    return tuple(sorted(set(modules.values()), key=lambda path: path.as_posix()))


def _closure_digest(root: Path, policy: Mapping[str, Any]) -> str:
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


def _verify_excluded_adjacent_members(root: Path, profile: Mapping[str, Any]) -> None:
    adjacent = profile.get("adjacent_retained_member_accounting")
    if not isinstance(adjacent, list):
        raise ValueError("LIB-051 adjacent retained-member accounting is invalid")
    excluded = [
        row
        for row in adjacent
        if isinstance(row, Mapping)
        and isinstance(row.get("disposition"), str)
        and row["disposition"].startswith("excluded")
    ]
    if len(excluded) != 22:
        raise ValueError("LIB-051 excluded adjacent-member census drift")
    for row in excluded:
        logical_path = row.get("path")
        if not isinstance(logical_path, str):
            raise ValueError("LIB-051 excluded adjacent-member path is invalid")
        path = Path(os.path.abspath(os.fspath(root / logical_path)))
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                "LIB-051 excluded adjacent-member escapes repository"
            ) from exc
        if not path.is_file():
            raise ValueError("LIB-051 excluded adjacent-member is not a file")
        content = path.read_bytes()
        if len(content) != row.get("bytes") or _sha(content) != row.get("sha256"):
            raise ValueError("LIB-051 excluded adjacent-member bytes or hash drift")


def _source_set_sha(source_manifest: SourceManifest) -> str:
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
        key=lambda item: (item["path"], item["name"]),
    )
    return _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": members})
    )


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    package_schema = _strict_json(
        source_manifest.authority_path("candidate-package-schema").read_bytes(),
        "candidate package schema",
    )
    raw_candidate_manifest = _strict_json(
        (candidate.path / "manifest.json").read_bytes(), "candidate manifest"
    )
    jsonschema.Draft202012Validator(package_schema).validate(raw_candidate_manifest)
    actual_members = {path.name for path in candidate.path.iterdir() if path.is_file()}
    if actual_members != MEMBERS:
        raise ValueError("LIB-051 candidate filesystem member drift")
    if (
        set(candidate.member_names) != MEMBERS
        or candidate.manifest.get("status") != "nonaccepted"
    ):
        raise ValueError("LIB-051 candidate member or status drift")
    if (
        candidate.manifest.get("source_manifest")
        != {
            "path": source_manifest.path.relative_to(root).as_posix(),
            "sha256": source_manifest.sha256,
        }
        or candidate.manifest.get("converter") != source_manifest.record["converter"]
        or candidate.manifest.get("package_schema")
        != source_manifest.record["package_schema"]
    ):
        raise ValueError("LIB-051 candidate authority binding drift")
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict_json(profile_bytes, "LIB-051 profile")
    policy = _strict_json(policy_bytes, "LIB-051 policy")
    expected_core = {
        "candidate_status": "nonaccepted",
        "publication_state": "not_ready",
        "required_member_names": sorted(MEMBERS),
        "required_work_count": 10,
        "required_source_member_count": 10,
        "required_adjacent_member_count": 22,
    }
    if {
        key: sorted(policy[key]) if key == "required_member_names" else policy[key]
        for key in expected_core
    } != expected_core:
        raise ValueError("LIB-051 validation policy closure drift")
    works = profile.get("works")
    adjacent = profile.get("adjacent_retained_member_accounting")
    if (
        not isinstance(works, list)
        or len(works) != 10
        or not isinstance(adjacent, list)
        or len(adjacent) != 32
        or sum(row["disposition"].startswith("included") for row in adjacent) != 10
        or sum(row["disposition"].startswith("excluded") for row in adjacent) != 22
    ):
        raise ValueError("LIB-051 profile census drift")
    _verify_excluded_adjacent_members(root, profile)
    prepared = []
    for work in works:
        identity = _strict_json(
            source_manifest.authority_path(
                work["identity_authority_name"]
            ).read_bytes(),
            "work identity",
        )
        if identity != {
            "contract": "ocd-reconstruction-work-identity-v1",
            "work_id": work["work_id"],
        }:
            raise ValueError("LIB-051 work identity binding drift")
        content = source_manifest.authority_path(work["authority_name"]).read_bytes()
        if len(content) != work["bytes"] or _sha(content) != work["sha256"]:
            raise ValueError("LIB-051 wrong or stale retained source")
        tree = _parse_source(content)
        prepared.append((work, content, tree, _records(tree, work["member_id"])))
    _verify_tei(candidate, prepared, source_manifest.authority_path("tei-p5-xsd"))
    expected_accountability, expected_provenance, expected_unresolved = (
        _expected_evidence(source_manifest, profile, prepared)
    )
    accountability = _strict_json(
        candidate.member_bytes("source-accountability.json"), "source accountability"
    )
    jsonschema.Draft202012Validator(
        _strict_json(
            source_manifest.authority_path("source-accountability-schema").read_bytes(),
            "accountability schema",
        )
    ).validate(accountability)
    if candidate.member_bytes("source-accountability.json") != _canonical(
        expected_accountability
    ):
        raise ValueError(
            "LIB-051 source accounting omission, duplication, order, type, or extra-field drift"
        )
    if candidate.member_bytes("provenance.json") != _canonical(expected_provenance):
        raise ValueError(
            "LIB-051 metadata, identity, rights, type, status, or extra-field drift"
        )
    if candidate.member_bytes("unresolved.jsonl") != expected_unresolved:
        raise ValueError("LIB-051 unresolved evidence drift")
    if (
        candidate.member_bytes("README.source.md")
        != source_manifest.authority_path("source-local-readme").read_bytes()
    ):
        raise ValueError("LIB-051 source attribution README drift")
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).resolve().read_bytes()),
        "import_closure_sha256": _closure_digest(root, policy),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": _source_set_sha(source_manifest),
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
