"""Independent source and candidate reader for Apostolic Tradition eBook 61614."""

from __future__ import annotations

from collections import Counter
import hashlib
from importlib.metadata import version as distribution_version
import json
import platform
from pathlib import Path
import sys
from typing import Mapping
from urllib.parse import quote
from zipfile import ZipFile

import html5lib
from jsonschema import Draft202012Validator
from lxml import etree

_TEI_NS = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_DIV_CLASSES = {
    "fnblock": "source-footnote-block",
    "fndef": "source-footnote-definition",
    "index": "source-index",
    "indexlr": "source-index",
    "notes": "source-notes",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _read_role(source_manifest: object, role: str) -> tuple[Mapping[str, object], bytes]:
    matches = [
        item
        for item in source_manifest.record["authorities"]
        if isinstance(item, Mapping) and item.get("role") == role
    ]
    if len(matches) != 1:
        raise ValueError(f"source manifest must bind exactly one {role}")
    authority = matches[0]
    content = source_manifest.authority_path(str(authority["name"])).read_bytes()
    if authority.get("bytes") != len(content) or authority.get("sha256") != _sha(content):
        raise ValueError(f"{role} authority bytes differ from the source manifest")
    return authority, content


def _head_facts(root: object, profile: Mapping[str, object]) -> None:
    head = root.find("head")
    if head is None:
        raise ValueError("HTML5 source reader found no head")
    shell = profile.get("html_shell")
    if not isinstance(shell, Mapping) or len(head) != shell.get("head_direct_children"):
        raise ValueError("HTML5 source head inventory differs from profile")
    title = next((item for item in head if item.tag == "title"), None)
    rights = next((item for item in head if item.tag == "meta" and item.get("name") == "dc.rights"), None)
    origin = next((item for item in head if item.tag == "meta" and item.get("name") == "dcterms.source"), None)
    styles = [item for item in head if item.tag == "style"]
    if (
        title is None
        or title.text != shell.get("head_title")
        or rights is None
        or rights.get("content") != shell.get("head_dc_rights")
        or origin is None
        or origin.get("content") != shell.get("head_source_url")
        or len(styles) != shell.get("head_style_elements")
    ):
        raise ValueError("HTML5 source head metadata differs from the profile")


def _source_inventory(body: object) -> dict[str, object]:
    elements = list(body.iter())
    if any(not isinstance(item.tag, str) for item in elements):
        raise ValueError("HTML comments inside the selected body are not profiled")
    tag_counts = Counter(item.tag.lower() for item in elements)
    attribute_counts = Counter(key.lower() for item in elements for key in item.attrib)
    class_counts = Counter(token for item in elements for token in (item.get("class") or "").split())
    text = "".join(body.itertext())
    headings = []
    for ordinal, item in enumerate(body, 1):
        if item.tag == "h2":
            headings.append(
                {
                    "body_child": ordinal,
                    "id": item.get("id"),
                    "text": " ".join(" ".join(item.itertext()).split()),
                }
            )
    ids = [item.get("id") for item in elements if item.get("id")]
    id_set = set(ids)
    local_targets = [
        item.get("href", "")[1:]
        for item in elements
        if item.tag == "a" and item.get("href", "").startswith("#")
    ]
    page_breaks = [
        {"id": item.get("id"), "n": " ".join("".join(item.itertext()).split())}
        for item in elements
        if item.tag == "div" and "pb" in (item.get("class") or "").split()
    ]
    return {
        "direct_child_count": len(body),
        "element_count_including_body": len(elements),
        "normalized_text_characters": len(text),
        "normalized_text_sha256": _sha(text.encode("utf-8")),
        "tag_counts": dict(sorted(tag_counts.items())),
        "attribute_counts": dict(sorted(attribute_counts.items())),
        "class_counts": dict(sorted(class_counts.items())),
        "major_h2_boundaries": headings,
        "printed_page_marker_count": len(page_breaks),
        "page_breaks": page_breaks,
        "unique_source_ids": len(id_set),
        "duplicate_source_id_count": len(ids) - len(id_set),
        "link_count": sum(1 for item in elements if item.tag == "a" and item.get("href")),
        "local_fragment_link_count": len(local_targets),
        "dangling_local_fragment_count": len(set(local_targets) - id_set),
        "body_image_references": [
            {"src": item.get("src"), "alt": item.get("alt", "")}
            for item in elements
            if item.tag == "img"
        ],
    }


def _expected_tag_and_attributes(source: object) -> tuple[str, dict[str, str], str]:
    source_tag = source.tag.lower()
    classes = set((source.get("class") or "").split())
    if source_tag == "div" and "pb" in classes:
        if len(source) or not (source.text or "").strip():
            raise ValueError("source page marker is not a simple labeled div")
        mapped = "pb"
        attributes = {"n": (source.text or "").strip()}
    elif source_tag == "div":
        mapped = "ab"
        kind = next((_DIV_CLASSES[value] for value in sorted(classes) if value in _DIV_CLASSES), "source-html-div")
        attributes = {"type": kind}
    else:
        mappings = {
            "a": ("ref", {}),
            "b": ("hi", {"rend": "bold"}),
            "blockquote": ("ab", {"type": "source-html-blockquote"}),
            "br": ("lb", {}),
            "dd": ("ab", {"type": "source-html-dd"}),
            "dl": ("list", {"type": "definition"}),
            "dt": ("label", {}),
            "footer": ("ab", {"type": "provider-footer"}),
            "h1": ("ab", {"type": "source-html-h1"}),
            "h2": ("ab", {"type": "source-html-h2"}),
            "h3": ("ab", {"type": "source-html-h3"}),
            "h4": ("ab", {"type": "source-html-h4"}),
            "h5": ("ab", {"type": "source-html-h5"}),
            "h6": ("ab", {"type": "source-html-h6"}),
            "header": ("ab", {"type": "provider-header"}),
            "i": ("hi", {"rend": "italic"}),
            "img": ("graphic", {}),
            "li": ("item", {}),
            "ol": ("list", {"type": "ordered"}),
            "p": ("ab", {"type": "source-html-p"}),
            "span": ("seg", {}),
            "strong": ("hi", {"rend": "strong"}),
            "table": ("ab", {"type": "source-html-table"}),
            "tbody": ("table", {}),
            "td": ("cell", {}),
            "tr": ("row", {}),
            "ul": ("list", {"type": "unordered"}),
        }
        if source_tag not in mappings:
            raise ValueError(f"HTML5 source reader found unsupported body element {source_tag!r}")
        mapped, attributes = mappings[source_tag]
        attributes = dict(attributes)
    rend = [attributes.pop("rend")] if "rend" in attributes else []
    for name, value in source.attrib.items():
        name = name.lower()
        if name == "id":
            attributes[_XML_ID] = value
        elif name == "class":
            rend.append("source-class:" + quote(value, safe=""))
        elif name == "href":
            attributes["target"] = value
        elif name == "src":
            attributes["url"] = value
        elif name == "alt":
            attributes["n"] = value
        elif name == "lang":
            attributes[_XML_LANG] = value
        elif name == "colspan":
            attributes["cols"] = value
        elif name in {"title", "width", "height"}:
            rend.append(f"source-{name}:" + quote(value, safe=""))
        else:
            raise ValueError(f"HTML5 source reader found unsupported body attribute {name!r}")
    if rend:
        attributes["rend"] = " ".join(rend)
    text = source.text or ""
    return mapped, attributes, text


def _definition_list_children(source: object) -> tuple[object, ...]:
    children = list(source)
    result = []
    index = 0
    while index < len(children):
        item_children = []
        if children[index].tag not in {"dt", "dd"}:
            raise ValueError("HTML5 definition list contains a child outside dt/dd")
        if children[index].tag == "dt":
            child = children[index]
            item_children.append((_expected_tree(child), child.tail or None))
            index += 1
        while index < len(children) and children[index].tag == "dd":
            child = children[index]
            item_children.append((_expected_tree(child), child.tail or None))
            index += 1
        result.append((("item", (), None, tuple(item_children)), None))
    return tuple(result)


def _expected_tree(source: object) -> tuple[object, ...]:
    tag, attributes, source_text = _expected_tag_and_attributes(source)
    content_text = None if tag == "pb" else source_text or None
    if source.tag == "dl":
        children = _definition_list_children(source)
    else:
        children = tuple((_expected_tree(child), child.tail or None) for child in source)
    return (tag, tuple(sorted(attributes.items())), content_text, children)


def _actual_tree(candidate: object) -> tuple[object, ...]:
    qname = etree.QName(candidate)
    if qname.namespace != _TEI_NS:
        raise ValueError("candidate contains an element outside the TEI namespace")
    attributes = dict(candidate.attrib)
    children = tuple((_actual_tree(child), child.tail or None) for child in candidate)
    return (qname.localname, tuple(sorted(attributes.items())), candidate.text or None, children)


def _archive_facts(source_manifest: object, profile: Mapping[str, object], source_bytes: bytes) -> str:
    archive_path = source_manifest.authority_path("retained-archive")
    archive_bytes = archive_path.read_bytes()
    archive_profile = profile.get("source_archive")
    if not isinstance(archive_profile, Mapping):
        raise ValueError("source profile has no package inventory")
    if len(archive_bytes) != archive_profile.get("bytes") or _sha(archive_bytes) != archive_profile.get("sha256"):
        raise ValueError("independent package hash differs from source profile")
    with ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("independent package CRC check failed")
        rows = [
            {
                "path": info.filename,
                "bytes": info.file_size,
                "crc32": f"{info.CRC:08x}",
                "sha256": _sha(archive.read(info)),
            }
            for info in archive.infolist()
            if not info.is_dir()
        ]
        if rows != archive_profile.get("members") or archive.read("pg61614-images.html") != source_bytes:
            raise ValueError("independent package member census differs")
        for authority_name, member_name in (("cover-image", "images/cover.jpg"), ("spine-image", "images/spine.jpg")):
            if archive.read(member_name) != source_manifest.authority_path(authority_name).read_bytes():
                raise ValueError(f"independent extracted-media comparison failed for {member_name}")
    return _sha(archive_bytes)


def _verify_teixsd(source_manifest: object, content: bytes) -> None:
    schema_path = source_manifest.authority_path("tei-p5-xsd")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    schema = etree.XMLSchema(etree.parse(str(schema_path), parser))
    document = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
    schema.assertValid(document)


def _role_digest(source_manifest: object, role: str) -> str:
    authority, _ = _read_role(source_manifest, role)
    return str(authority["sha256"])


def _runtime_binding() -> str:
    return f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})"


def _closure_digest() -> str:
    """Bind the independent reader and its parser/schema runtime versions."""
    return _sha(
        _canonical(
            {
                "oracle": {
                    "path": "build/tei/apostolic_tradition_oracle.py",
                    "sha256": _sha(Path(__file__).resolve(strict=True).read_bytes()),
                },
                "distributions": {
                    name: distribution_version(name)
                    for name in ("html5lib", "jsonschema", "lxml")
                },
            }
        )
    )


def _oracle(source_manifest: object, candidate: object) -> dict[str, object]:
    profile_authority, profile_bytes = _read_role(source_manifest, "complete-source-feature-profile")
    policy_authority, policy_bytes = _read_role(source_manifest, "independent-validation-policy")
    schema_authority, account_schema_bytes = _read_role(source_manifest, "complete-source-accountability-schema")
    package_schema_authority, _ = _read_role(source_manifest, "candidate-package-schema")
    xsd_authority, _ = _read_role(source_manifest, "tei-validation-schema")
    primary = [
        item
        for item in source_manifest.record["authorities"]
        if isinstance(item, Mapping) and item.get("role") == "primary-source"
    ]
    if len(primary) != 1:
        raise ValueError("Apostolic Tradition requires exactly one retained primary HTML source")
    source_bytes = source_manifest.authority_path(str(primary[0]["name"])).read_bytes()
    source_sha = _sha(source_bytes)
    profile = _strict_json(profile_bytes, "source profile")
    policy = _strict_json(policy_bytes, "validation policy")
    source_html = profile.get("source_html")
    archive_profile = profile.get("source_archive")
    _, work_bytes = _read_role(source_manifest, "work-identity-config")
    _, acquisition_bytes = _read_role(
        source_manifest, "acquisition-selection-authority"
    )
    work = _strict_json(work_bytes, "work sidecar")
    acquisition = _strict_json(acquisition_bytes, "acquisition sidecar")
    if (
        not isinstance(source_html, Mapping)
        or not isinstance(archive_profile, Mapping)
        or source_html.get("bytes") != len(source_bytes)
        or source_html.get("sha256") != source_sha
        or primary[0].get("path") != source_html.get("path")
        or work.get("work_id") != profile.get("work_id")
        or work.get("title") != "The Apostolic Tradition of Hippolytus"
        or acquisition.get("acquisition_id") != profile.get("acquisition_id")
        or acquisition.get("edition_id") != profile.get("edition_id")
        or source_manifest.record.get("edition_id") != profile.get("edition_id")
        or source_manifest.record.get("acquisition_id") != profile.get("acquisition_id")
    ):
        raise ValueError("source, work, or acquisition identity differs from the independent profile")
    retained = acquisition.get("retained_files")
    if not isinstance(retained, list):
        raise ValueError("independent acquisition sidecar has no retained-file inventory")
    for expected in (source_html, archive_profile):
        if not any(
            isinstance(item, Mapping)
            and item.get("path") == expected.get("path")
            and item.get("bytes") == expected.get("bytes")
            and item.get("sha256") == expected.get("sha256")
            for item in retained
        ):
            raise ValueError("independent acquisition sidecar does not bind a profiled source member")
    archive_sha = _archive_facts(source_manifest, profile, source_bytes)
    html_root = html5lib.parse(source_bytes, treebuilder="etree", namespaceHTMLElements=False)
    _head_facts(html_root, profile)
    source_body = html_root.find("body")
    if source_body is None:
        raise ValueError("independent HTML5 parser found no body")
    source_inventory = _source_inventory(source_body)
    declared_body = profile.get("body")
    if not isinstance(declared_body, Mapping):
        raise ValueError("source profile has no declared body inventory")
    profile_keys = (
        "direct_child_count",
        "element_count_including_body",
        "normalized_text_characters",
        "normalized_text_sha256",
        "tag_counts",
        "attribute_counts",
        "class_counts",
        "major_h2_boundaries",
        "printed_page_marker_count",
        "unique_source_ids",
        "duplicate_source_id_count",
        "link_count",
        "local_fragment_link_count",
        "dangling_local_fragment_count",
        "body_image_references",
    )
    for key in profile_keys:
        if source_inventory[key] != declared_body.get(key):
            raise ValueError(f"independent HTML5 source inventory disagrees on {key}")
    if source_manifest.record.get("work_id") != profile.get("work_id"):
        raise ValueError("source manifest work identity differs from profile")
    candidate.verify_integrity()
    if candidate.manifest.get("source_id") != source_manifest.record.get("source_id"):
        raise ValueError("candidate source identity differs from source manifest")
    content = candidate.member_bytes("content.tei.xml")
    account_bytes = candidate.member_bytes("source-accountability.json")
    account = _strict_json(account_bytes, "source-accountability member")
    account_schema = _strict_json(account_schema_bytes, "source-accountability schema")
    account_errors = sorted(Draft202012Validator(account_schema).iter_errors(account), key=str)
    if account_errors:
        raise ValueError(f"source-accountability schema failure: {account_errors[0].message}")
    if (
        account.get("work_id") != profile.get("work_id")
        or account.get("edition_id") != profile.get("edition_id")
        or account.get("acquisition_id") != profile.get("acquisition_id")
        or account.get("source_sha256") != source_sha
        or account.get("source_archive_sha256") != archive_sha
        or account.get("candidate_sha256") != _sha(content)
        or account.get("document_shell") != profile.get("html_shell")
        or account.get("body_inventory") != declared_body
        or account.get("mapping") != profile.get("mapping")
    ):
        raise ValueError("candidate source-accountability record differs from the independent source profile")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-readme").read_bytes():
        raise ValueError("candidate source README differs from its bound authority")
    if candidate.member_bytes("provenance.json") != _canonical(policy.get("provenance")):
        raise ValueError("candidate provenance differs from the independent validation policy")
    unresolved_lines = b"".join(_canonical(item) for item in policy.get("unresolved", []))
    if candidate.member_bytes("unresolved.jsonl") != unresolved_lines:
        raise ValueError("candidate unresolved items differ from the independent validation policy")

    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    tei = etree.fromstring(content, parser)
    if tei.tag != f"{{{_TEI_NS}}}TEI" or tei.get(_XML_LANG) != "en" or len(tei) != 2:
        raise ValueError("candidate TEI document shell differs from its route")
    header, text_node = tei
    if etree.QName(header).localname != "teiHeader" or etree.QName(text_node).localname != "text" or len(text_node) != 1:
        raise ValueError("candidate TEI header/text placement differs from its route")
    title = header.find(f".//{{{_TEI_NS}}}title")
    author = header.find(f".//{{{_TEI_NS}}}author")
    translator = header.find(f".//{{{_TEI_NS}}}respStmt/{{{_TEI_NS}}}name")
    availability = header.find(f".//{{{_TEI_NS}}}availability")
    if (
        title is None
        or title.text != "The Apostolic Tradition of Hippolytus"
        or author is None
        or author.text != "Hippolytus (traditional attribution; see the source introduction)"
        or translator is None
        or translator.text != "Burton Scott Easton"
        or availability is None
        or availability.get("status") != "unknown"
    ):
        raise ValueError("candidate TEI bibliographic or rights header differs from the declared source")
    candidate_body = text_node.find(f"{{{_TEI_NS}}}body")
    if candidate_body is None or len(candidate_body) != 1 or candidate_body.text:
        raise ValueError("candidate TEI body does not have the one source-body wrapper")
    body_content = candidate_body[0]
    expected_children = tuple((_expected_tree(child), child.tail or None) for child in source_body)
    expected_body = (
        "ab",
        (("type", "complete-gutenberg-html-body"),),
        source_body.text or None,
        expected_children,
    )
    if _actual_tree(body_content) != expected_body:
        raise ValueError("candidate body differs from the independent HTML5 source traversal")
    ids = {
        element.get(_XML_ID)
        for element in tei.iter()
        if element.get(_XML_ID)
    }
    for ref in tei.iter(f"{{{_TEI_NS}}}ref"):
        target = ref.get("target", "")
        if target.startswith("#") and target[1:] not in ids:
            raise ValueError(f"candidate has a dangling local link {target!r}")
    graphics = [element.get("url") for element in tei.iter(f"{{{_TEI_NS}}}graphic")]
    if graphics != ["images/cover.jpg"]:
        raise ValueError("candidate body image references differ from the retained package")
    if sum(1 for element in tei.iter(f"{{{_TEI_NS}}}pb")) != declared_body.get("printed_page_marker_count"):
        raise ValueError("candidate printed-page marker count differs from source")
    _verify_teixsd(source_manifest, content)

    implementation_hash = _sha(Path(__file__).resolve(strict=True).read_bytes())
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": "ocd-apostolic-tradition-html5-independent-oracle",
        "oracle_version": "1",
        "implementation_sha256": implementation_hash,
        "import_closure_sha256": _closure_digest(),
        "runtime": _runtime_binding(),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": str(profile_authority["sha256"]),
        "package_schema_sha256": str(package_schema_authority["sha256"]),
        "source_sha256": source_sha,
        "xsd_sha256": str(xsd_authority["sha256"]),
        "policy_sha256": str(policy_authority["sha256"]),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = "ocd-apostolic-tradition-html5-independent-oracle"
_oracle.oracle_version = "1"
