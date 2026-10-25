"""Independent source-first checker for the Coppens PG70790 successor.

The oracle parses HTML with Python's standard-library HTMLParser and TEI with
ElementTree.  It does not import or call the converter's lxml mapping code.
The vendored lxml schema engine is used only for the separate TEI P5 gate.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import zipfile
from collections import Counter
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Mapping
from xml.etree import ElementTree as ET

from lxml import etree

from ocd_kernel.lib.path_io import io_path, resolve_path
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


oracle_id = "ocd-coppens-pg70790-source-native-v2-oracle"
oracle_version = "2"

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"


class _Node:
    __slots__ = ("tag", "attrs", "text", "tail", "children")

    def __init__(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tag = tag
        self.attrs = {key: value or "" for key, value in attrs}
        self.text = ""
        self.tail = ""
        self.children: list[_Node] = []

    def add_text(self, value: str) -> None:
        if self.children:
            self.children[-1].tail += value
        else:
            self.text += value


class _SourceHTML(HTMLParser):
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", [])
        self.stack = [self.root]
        self.comments: list[tuple[_Node, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag.lower(), attrs, push=tag.lower() not in self._VOID)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag.lower(), attrs, push=False)

    def _start(self, tag: str, attrs: list[tuple[str, str | None]], *, push: bool) -> None:
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        if push:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == lowered:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].add_text(data)

    def handle_comment(self, data: str) -> None:
        self.comments.append((self.stack[-1], data))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _norm(value: str | None) -> str:
    return " ".join((value or "").split())


def _attrs(node: ET.Element) -> dict[str, str]:
    return {key.rsplit("}", 1)[-1]: value for key, value in node.attrib.items()}


def _find_element(node: _Node, tag: str) -> _Node | None:
    if node.tag == tag:
        return node
    for child in node.children:
        result = _find_element(child, tag)
        if result is not None:
            return result
    return None


def _visible_text(node: _Node) -> str:
    parts: list[str] = []

    def visit(current: _Node) -> None:
        parts.append(current.text)
        for child in current.children:
            visit(child)
            parts.append(child.tail)

    visit(node)
    return _norm("".join(parts))


def _source_locator_rows(body: _Node) -> list[tuple[str, _Node]]:
    rows: list[tuple[str, _Node]] = []

    def visit(node: _Node, path: str) -> None:
        rows.append((path, node))
        for index, child in enumerate(node.children, 1):
            child_path = str(index) if not path else f"{path}.{index}"
            visit(child, child_path)

    visit(body, "")
    return rows


def _source_head_inventory(head: _Node) -> list[dict[str, object]]:
    return [
        {
            "position": index,
            "tag": child.tag,
            "attributes": dict(sorted(child.attrs.items())),
            "text": child.text,
            "tail": child.tail,
            "disposition": _head_disposition(child),
        }
        for index, child in enumerate(head.children, 1)
    ]


def _comment_inventory(parser: _SourceHTML) -> list[dict[str, object]]:
    paths: dict[int, str] = {}

    def visit(node: _Node, path: str) -> None:
        paths[id(node)] = path
        tag_counts: Counter[str] = Counter()
        for child in node.children:
            tag_counts[child.tag] += 1
            suffix = child.tag if tag_counts[child.tag] == 1 else f"{child.tag}[{tag_counts[child.tag]}]"
            visit(child, suffix if not path else f"{path}/{suffix}")

    visit(parser.root, "")
    return [
        {
            "position": index,
            "parent_path": paths.get(id(parent), "unknown"),
            "parent_tag": parent.tag,
            "kind": "comment",
            "text": content,
        }
        for index, (parent, content) in enumerate(parser.comments, 1)
    ]


def _head_disposition(node: _Node) -> str:
    attrs = node.attrs
    if node.tag == "style":
        return "Presentation CSS; retained byte-for-byte in the source archive and excluded from textual TEI content."
    if node.tag == "title":
        return "Project Gutenberg HTML document title; preserved exactly in this inventory, distinct from the complete title-page title."
    if node.tag == "meta" and attrs.get("charset"):
        return "HTML byte-encoding declaration; retained in the hash-bound HTML source."
    if node.tag == "link" and attrs.get("rel") == "icon":
        return "Local cover/icon pointer; the exact cover member is retained and hash-bound."
    if node.tag == "link" and attrs.get("rel", "").startswith("schema."):
        return "Metadata vocabulary link; retained as source structure, not a work content claim."
    if node.tag == "link" and attrs.get("rel") == "dcterms.isFormatOf":
        return "Project Gutenberg ebook-format relation; retained as provider metadata."
    if node.tag == "meta" and attrs.get("property") == "og:image":
        return "External Open Graph image pointer; metadata-only and not fetched."
    if node.tag == "meta" and attrs.get("name") == "format-detection":
        return "Browser presentation hint; exact value retained but not transcribed as textual content."
    if node.tag == "meta" and attrs.get("name") == "generator":
        return "Source-production metadata; exact value retained."
    if node.tag == "meta":
        return f"Provider-supplied {attrs.get('name') or attrs.get('property') or 'metadata'} assertion; exact value retained without independent promotion."
    if node.tag == "link":
        return "Source link metadata; exact values retained."
    return "Unclassified source head node; retained in exact inventory and source archive."


def _source_head_metadata(head: _Node) -> dict[str, object]:
    meta: dict[str, list[str]] = {}
    links: list[dict[str, str]] = []
    for node in head.children:
        attrs = node.attrs
        if node.tag == "meta" and attrs.get("name"):
            meta.setdefault(attrs["name"], []).append(attrs.get("content", ""))
        elif node.tag == "meta" and attrs.get("property"):
            meta.setdefault(attrs["property"], []).append(attrs.get("content", ""))
        elif node.tag == "link":
            links.append(dict(attrs))
    return {
        "dc_title": meta.get("dc.title", []),
        "dc_language": meta.get("dc.language", []),
        "dcterms_source": meta.get("dcterms.source", []),
        "dcterms_modified": meta.get("dcterms.modified", []),
        "dc_rights": meta.get("dc.rights", []),
        "dc_creators": meta.get("dc.creator", []),
        "dc_subjects": meta.get("dc.subject", []),
        "dcterms_created": meta.get("dcterms.created", []),
        "generator": meta.get("generator", []),
        "format_detection": meta.get("format-detection", []),
        "open_graph": {
            "title": meta.get("og:title", []),
            "type": meta.get("og:type", []),
            "url": meta.get("og:url", []),
            "image": meta.get("og:image", []),
        },
        "links": links,
        "dispositions": [
            {"position": index, "tag": node.tag, "decision": _head_disposition(node)}
            for index, node in enumerate(head.children, 1)
        ],
    }


def _tag_is_valid(source_tag: str, tei_node: ET.Element) -> bool:
    local = tei_node.tag.rsplit("}", 1)[-1]
    node_type = tei_node.get("type")
    fixed = {
        "body": {("body", None)},
        "a": {("ref", None)},
        "abbr": {("seg", "source-abbr")},
        "b": {("hi", None)},
        "blockquote": {("seg", "source-blockquote")},
        "br": {("lb", None)},
        "footer": {("ab", "source-footer")},
        "h1": {("seg", "source-h1")},
        "h2": {("seg", "source-h2")},
        "header": {("ab", "source-header")},
        "hr": {("milestone", None)},
        "i": {("hi", None)},
        "img": {("graphic", None)},
        "li": {("seg", "source-li")},
        "span": {("seg", "source-span")},
        "strong": {("hi", None)},
        "ul": {("seg", "source-ul")},
    }
    if source_tag in fixed:
        return (local, node_type) in fixed[source_tag]
    if source_tag in {"div", "h3", "h4", "p"}:
        return local in {"ab", "seg"} and node_type == f"source-{source_tag}"
    return False


def _check_body(source_body: _Node, tei_body: ET.Element) -> dict[str, object]:
    source_rows = _source_locator_rows(source_body)
    tei_nodes = list(tei_body.iter())
    if len(source_rows) != len(tei_nodes):
        raise ValueError(f"source/TEI body node count mismatch: {len(source_rows)} != {len(tei_nodes)}")
    attr_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    locators: list[dict[str, str]] = []

    for (locator, source_node), tei_node in zip(source_rows, tei_nodes):
        source_tag = source_node.tag
        tag_counts[source_tag] += 1
        if locator:
            attr_counts.update(source_node.attrs.keys())
            locators.append({"locator": locator, "source_tag": source_tag})
            if tei_node.get("n") != locator:
                raise ValueError(f"source order/locator mismatch at {locator}")
        elif tei_node is not tei_body:
            raise ValueError("source root does not bind the candidate TEI body")
        if not _tag_is_valid(source_tag, tei_node):
            raise ValueError(f"source tag carrier mismatch at {locator or 'body'}")
        if _norm(source_node.text) != _norm(tei_node.text):
            raise ValueError(f"source text mismatch at {locator or 'body'}")
        if _norm(source_node.tail) != _norm(tei_node.tail):
            raise ValueError(f"source tail mismatch at {locator or 'body'}")
        if len(source_node.children) != len(list(tei_node)):
            raise ValueError(f"source child cardinality mismatch at {locator or 'body'}")

        if not locator:
            continue
        source_attrs = source_node.attrs
        candidate_attrs = _attrs(tei_node)
        if "id" in source_attrs and candidate_attrs.get("id") != source_attrs["id"]:
            raise ValueError(f"source id mismatch at {locator}")
        for attr_name, rendition_prefix in (("class", "source-class:"), ("style", "source-style:")):
            if attr_name in source_attrs and rendition_prefix + source_attrs[attr_name] not in (candidate_attrs.get("rend") or ""):
                raise ValueError(f"source {attr_name} mismatch at {locator}")
        if "href" in source_attrs and candidate_attrs.get("target") != source_attrs["href"]:
            raise ValueError(f"source href mismatch at {locator}")
        if "src" in source_attrs and candidate_attrs.get("url") != source_attrs["src"]:
            raise ValueError(f"source src mismatch at {locator}")
        if "lang" in source_attrs and tei_node.get(f"{{{XML}}}lang") != source_attrs["lang"]:
            raise ValueError(f"source lang mismatch at {locator}")
        if "title" in source_attrs:
            marker = "source-title-empty" if source_attrs["title"] == "" else f"source-title:{source_attrs['title']}"
            if marker not in (candidate_attrs.get("rend") or ""):
                raise ValueError(f"source title attribute mismatch at {locator}")
        if "alt" in source_attrs:
            marker = "source-alt-empty" if source_attrs["alt"] == "" else f"source-alt:{source_attrs['alt']}"
            if marker not in (candidate_attrs.get("rend") or ""):
                raise ValueError(f"source alt attribute mismatch at {locator}")

    source_text = _visible_text(source_body)
    tei_text = _norm(" ".join("".join(tei_body.itertext()).split()))
    if source_text != tei_text:
        raise ValueError("complete source body text differs from the TEI body")
    return {
        "direct_child_count": len(source_body.children),
        "element_count_including_body": len(source_rows),
        "mapped_descendant_count": len(locators),
        "normalized_text_characters": len(source_text),
        "normalized_text_sha256": _sha(source_text.encode("utf-8")),
        "locator_tag_map_sha256": _sha(_canonical(locators)),
        "source_tag_counts": dict(sorted(tag_counts.items())),
        "source_attribute_counts": dict(sorted(attr_counts.items())),
    }


def _p5_validate(content: bytes, xsd_path: Path) -> None:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    document = etree.fromstring(content, parser)
    schema_doc = etree.parse(str(io_path(xsd_path)), parser)
    schema = etree.XMLSchema(schema_doc)
    schema.assertValid(document)


def _import_closure_sha256(source_manifest: SourceManifest, profile: Mapping[str, object]) -> str:
    paths = profile.get("oracle_dependency_paths")
    if not isinstance(paths, list) or len(paths) != len(set(paths)):
        raise ValueError("oracle dependency path inventory is invalid")
    rows = []
    for relative in sorted(paths):
        if not isinstance(relative, str):
            raise ValueError("oracle dependency path is not a string")
        path = resolve_path(source_manifest.repository_root / relative, strict=True)
        try:
            path.relative_to(source_manifest.repository_root)
        except ValueError as exc:
            raise ValueError("oracle dependency escaped the project root") from exc
        data = io_path(path).read_bytes()
        rows.append({"path": relative, "sha256": _sha(data)})
    return _sha(_canonical(rows))


def _body_without_declared_markers(content: bytes, *, require_markers: bool) -> bytes:
    root = ET.fromstring(content)
    body = root.find(f".//{{{TEI}}}body")
    if body is None:
        raise ValueError("candidate TEI has no body")
    for locator, marker in (("1.1", "source-title-empty"), ("3.2", "source-alt-empty")):
        nodes = [node for node in body.iter() if node.get("n") == locator]
        if len(nodes) != 1:
            raise ValueError(f"declared carrier selector {locator} is not unique")
        node = nodes[0]
        rend = node.get("rend", "")
        tokens = rend.split()
        if require_markers:
            if tokens.count(marker) != 1:
                raise ValueError(f"declared carrier {marker} is absent or duplicated")
            tokens.remove(marker)
        elif marker in tokens:
            raise ValueError(f"frozen predecessor unexpectedly contains {marker}")
        if tokens:
            node.set("rend", " ".join(tokens))
        else:
            node.attrib.pop("rend", None)
    return ET.tostring(body, encoding="utf-8")


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    """Verify the candidate against a standard-library source parse and bound schema."""
    profile_path = source_manifest.authority_path("source-feature-profile")
    policy_path = source_manifest.authority_path("independent-validation-policy")
    archive_path = source_manifest.authority_path("retained-archive")
    xsd_path = source_manifest.authority_path("tei-validation-schema")
    schema_path = source_manifest.authority_path("candidate-package-schema")
    profile_bytes = io_path(profile_path).read_bytes()
    policy_bytes = io_path(policy_path).read_bytes()
    profile = json.loads(profile_bytes)
    if profile.get("contract") != "ocd-coppens-pg70790-profile-v2":
        raise ValueError("current source profile contract mismatch")
    closure_sha256 = _import_closure_sha256(source_manifest, profile)
    if closure_sha256 != source_manifest.record["validator"]["import_closure_sha256"]:
        raise ValueError("independent oracle import closure changed")
    archive_bytes = io_path(archive_path).read_bytes()
    if _sha(archive_bytes) != profile.get("source_archive_sha256"):
        raise ValueError("retained source archive hash differs from the profile")
    with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
        names = sorted(archive.namelist())
        if names != ["images/cover.jpg", "pg70790-images.html"] or archive.testzip() is not None:
            raise ValueError("retained archive members or CRC check failed")
        member_rows = []
        for name in names:
            info = archive.getinfo(name)
            data = archive.read(name)
            member_rows.append({"path": name, "bytes": len(data), "crc32": f"{info.CRC:08x}", "sha256": _sha(data)})
        source_html = archive.read("pg70790-images.html")
    if member_rows != profile.get("source_archive_members"):
        raise ValueError("retained source member bytes differ from profile")

    parser = _SourceHTML()
    parser.feed(source_html.decode("utf-8"))
    parser.close()
    source_head = _find_element(parser.root, "head")
    source_body = _find_element(parser.root, "body")
    if source_head is None or source_body is None:
        raise ValueError("independent HTMLParser did not find head/body")
    if _comment_inventory(parser) != profile.get("html_non_element_markup"):
        raise ValueError("independent HTMLParser comment inventory differs from the source profile")
    head_inventory = _source_head_inventory(source_head)
    body = candidate.member_bytes("content.tei.xml")
    body_document = ET.fromstring(body)
    tei_body = body_document.find(f".//{{{TEI}}}body")
    if tei_body is None:
        raise ValueError("candidate has no TEI body")
    body_results = _check_body(source_body, tei_body)

    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    if accountability.get("contract") != "ocd-coppens-pg70790-source-accountability-v2":
        raise ValueError("source-accountability contract mismatch")
    if accountability.get("html_member", {}).get("head_inventory") != head_inventory:
        raise ValueError("candidate accounting does not conserve all HTML head children")
    if accountability.get("html_member", {}).get("source_html_parser") != profile.get("html_source_parse"):
        raise ValueError("candidate accounting does not bind the declared source HTML parser diagnostics")
    if accountability.get("html_member", {}).get("non_element_markup") != _comment_inventory(parser):
        raise ValueError("candidate accounting does not conserve the source HTML comment")
    if accountability.get("html_member", {}).get("head_metadata") != _source_head_metadata(source_head):
        raise ValueError("candidate head metadata/dispositions differ from independent inventory")
    if accountability.get("html_member", {}).get("body") != body_results:
        raise ValueError("candidate accounting body results differ from independent parse")
    if accountability.get("source_archive", {}).get("members") != member_rows:
        raise ValueError("candidate accounting archive members differ from source")
    archive_record = accountability.get("source_archive", {})
    if (archive_record.get("logical_path"), archive_record.get("bytes"), archive_record.get("sha256"), archive_record.get("member_count")) != (
        profile.get("source_archive_path"), len(archive_bytes), _sha(archive_bytes), 2
    ):
        raise ValueError("candidate accounting does not bind the exact retained archive")
    html_record = accountability.get("html_member", {})
    if (html_record.get("path"), html_record.get("bytes"), html_record.get("sha256")) != (
        "pg70790-images.html", len(source_html), _sha(source_html)
    ):
        raise ValueError("candidate accounting does not bind the exact HTML member")
    if accountability.get("title_page_imprint") != profile.get("title_page_imprint") or accountability.get("electronic_metadata_date_roles") != profile.get("electronic_metadata_date_roles"):
        raise ValueError("candidate accounting changes the qualified title-page/electronic date roles")
    if accountability.get("body_candidate_sha256") != _sha(body):
        raise ValueError("candidate accounting content digest mismatch")
    if accountability.get("candidate_repairs") != [
        {"source_locator": "body/1/1", "source_attribute": 'title=""', "candidate_locator": "@n=1.1", "carrier": "@rend contains source-title-empty"},
        {"source_locator": "body/3/2", "source_attribute": 'alt=""', "candidate_locator": "@n=3.2", "carrier": "graphic/@rend contains source-alt-empty"},
    ]:
        raise ValueError("candidate empty-value repair record differs from exact selectors")

    tei_title = body_document.find(f".//{{{TEI}}}title")
    author = body_document.find(f".//{{{TEI}}}author")
    if tei_title is None or _norm(tei_title.text) != profile["source_page_facts"]["printed_title_page_title"]:
        raise ValueError("candidate title does not bind the full source title page")
    if author is None or _norm(author.text) != "Charles Coppens":
        raise ValueError("candidate author does not bind the title-page author")
    source_desc = body_document.find(f".//{{{TEI}}}sourceDesc")
    expected_note = profile.get("tei_source_description_addition")
    if source_desc is None or len(source_desc) != 2 or _norm(source_desc[1].text) != _norm(expected_note):
        raise ValueError("TEI source description does not include the source-bound metadata distinction")

    provenance = json.loads(candidate.member_bytes("provenance.json"))
    expected_identity = (profile["work_id"], profile["edition_id"], profile["acquisition_id"], profile["source_id"])
    actual_identity = (provenance.get("work_id"), provenance.get("edition_id"), provenance.get("acquisition_id"), provenance.get("source_id"))
    if actual_identity != expected_identity or provenance.get("status") != "nonaccepted":
        raise ValueError("candidate provenance does not bind the declared current identity")
    if b"A Short Method of Prayer" in candidate.member_bytes("README.source.md"):
        raise ValueError("candidate README retains the unrelated title")
    if accountability.get("source_page_title") == "A Short Method of Prayer":
        raise ValueError("candidate source accounting retains the unrelated title")

    notice = io_path(source_manifest.authority_path("source-notice")).read_bytes()
    if candidate.member_bytes("README.source.md") != notice:
        raise ValueError("candidate source notice differs from its pinned authority")

    profile_path_value = str(profile["predecessor_candidate_path"])
    predecessor = CandidatePackage.load(Path(profile_path_value))
    if predecessor.sha256 != profile["predecessor_candidate_manifest_sha256"]:
        raise ValueError("frozen predecessor package hash drifted")
    if _sha(predecessor.member_bytes("content.tei.xml")) != profile["predecessor_content_sha256"]:
        raise ValueError("frozen predecessor content hash drifted")
    if _body_without_declared_markers(body, require_markers=True) != _body_without_declared_markers(predecessor.member_bytes("content.tei.xml"), require_markers=False):
        raise ValueError("candidate body contains changes beyond the two declared carriers")

    source_visible = _visible_text(source_body)
    for source_phrase in (
        "The Spiritual Exercises of St. Ignatius",
        "ADAPTED TO AN EIGHT DAYS RETREAT",
        "SIX TRIDUUMS",
        "All for the use of Jesuits only",
        "CHARLES COPPENS",
        "B. HERDER",
        "17 South Broadway",
        "St. Louis, Mo.",
        "Copyright, 1916 by Joseph Gummersbach",
        "THE SPIRITUAL EXERCISES OF ST. IGNATIUS",
    ):
        if _norm(source_phrase).casefold() not in source_visible.casefold():
            raise ValueError(f"source-bound title/imprint/boundary phrase missing: {source_phrase}")

    _p5_validate(body, xsd_path)
    report_files = {
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(io_path(schema_path).read_bytes()),
        "source_sha256": _sha(archive_bytes),
        "xsd_sha256": _sha(io_path(xsd_path).read_bytes()),
        "policy_sha256": _sha(policy_bytes),
    }
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": oracle_id,
        "oracle_version": oracle_version,
        "implementation_sha256": source_manifest.record["validator"]["implementation_sha256"],
        "import_closure_sha256": closure_sha256,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({resolve_path(Path(sys.executable), strict=True)})",
        **report_files,
        "result_sha256": "",
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical({key: value for key, value in result.items() if key != "result_sha256"}))
    return result


_oracle.oracle_id = oracle_id  # type: ignore[attr-defined]
_oracle.oracle_version = oracle_version  # type: ignore[attr-defined]
