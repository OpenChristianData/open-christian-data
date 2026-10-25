"""Reconstruct the complete retained Project Gutenberg HTML body for eBook 61614."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Mapping
from urllib.parse import quote
from zipfile import ZipFile

from lxml import etree
import html5lib

from ocd_kernel.tei.writer import TEI_NS, stamp_header, tei_el

_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_TEI = f"{{{TEI_NS}}}"
_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]*$")

_TAG_MAP = {
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
    # TEI table content is a sequence of rows. Preserve HTML's outer table
    # carrier as a typed anonymous block and map tbody to the actual TEI table.
    "table": ("ab", {"type": "source-html-table"}),
    "tbody": ("table", {}),
    "td": ("cell", {}),
    "tr": ("row", {}),
    "ul": ("list", {"type": "unordered"}),
}
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


def _strict_json(path: Path, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _class_tokens(source: etree._Element) -> set[str]:
    return set((source.get("class") or "").split())


def _profile_body_facts(body: etree._Element) -> dict[str, object]:
    elements = [item for item in body.iter() if isinstance(item.tag, str)]
    tag_counts: dict[str, int] = {}
    attribute_counts: dict[str, int] = {}
    class_counts: dict[str, int] = {}
    for item in elements:
        tag = item.tag.lower()
        tag_counts[tag] = tag_counts.get(tag, 0) + 1
        for name in item.attrib:
            name = name.lower()
            attribute_counts[name] = attribute_counts.get(name, 0) + 1
        for token in _class_tokens(item):
            class_counts[token] = class_counts.get(token, 0) + 1
    text = "".join(body.itertext()).replace("\r\n", "\n").replace("\r", "\n")
    headings: list[dict[str, object]] = []
    for ordinal, item in enumerate(body, 1):
        if isinstance(item.tag, str) and item.tag.lower() == "h2":
            headings.append(
                {
                    "body_child": ordinal,
                    "id": item.get("id"),
                    "text": " ".join(" ".join(item.itertext()).split()),
                }
            )
    page_breaks = [
        {
            "id": item.get("id"),
            "n": " ".join("".join(item.itertext()).split()),
        }
        for item in body.iter()
        if isinstance(item.tag, str) and item.tag.lower() == "div" and "pb" in _class_tokens(item)
    ]
    ids = [item.get("id") for item in elements if item.get("id")]
    id_set = set(ids)
    local_targets = [
        item.get("href", "")[1:]
        for item in body.iter()
        if isinstance(item.tag, str) and item.tag.lower() == "a" and item.get("href", "").startswith("#")
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
        "link_count": sum(1 for item in body.iter() if isinstance(item.tag, str) and item.tag.lower() == "a" and item.get("href")),
        "local_fragment_link_count": len(local_targets),
        "dangling_local_fragment_count": len(set(local_targets) - id_set),
        "body_image_references": [
            {"src": item.get("src"), "alt": item.get("alt", "")}
            for item in body.iter()
            if isinstance(item.tag, str) and item.tag.lower() == "img"
        ],
    }


def _verify_archive(manifest: object, profile: Mapping[str, object]) -> tuple[bytes, bytes]:
    html_path = manifest.authority_path("retained-html")
    archive_path = manifest.authority_path("retained-archive")
    html_bytes = html_path.read_bytes()
    archive_bytes = archive_path.read_bytes()
    source_html = profile["source_html"]
    archive_profile = profile["source_archive"]
    if not isinstance(source_html, Mapping) or not isinstance(archive_profile, Mapping):
        raise ValueError("source profile has no HTML/archive evidence")
    if len(html_bytes) != source_html.get("bytes") or _sha(html_bytes) != source_html.get("sha256"):
        raise ValueError("retained HTML differs from the source profile")
    if len(archive_bytes) != archive_profile.get("bytes") or _sha(archive_bytes) != archive_profile.get("sha256"):
        raise ValueError("retained package differs from the source profile")
    with ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("retained Gutenberg package failed CRC verification")
        observed = [
            {
                "path": item.filename,
                "bytes": item.file_size,
                "crc32": f"{item.CRC:08x}",
                "sha256": _sha(archive.read(item)),
            }
            for item in archive.infolist()
            if not item.is_dir()
        ]
        if observed != archive_profile.get("members"):
            raise ValueError("retained package member order, size, CRC, or hash differs")
        archive_html = archive.read("pg61614-images.html")
        if archive_html != html_bytes:
            raise ValueError("extracted primary source differs from its retained package member")
        for name, member in (("cover-image", "images/cover.jpg"), ("spine-image", "images/spine.jpg")):
            if archive.read(member) != manifest.authority_path(name).read_bytes():
                raise ValueError(f"extracted {member} differs from its retained package member")
    return html_bytes, archive_bytes


def _mapped_tag(source: etree._Element) -> tuple[str, dict[str, str]]:
    tag = source.tag.lower()
    classes = _class_tokens(source)
    if tag == "div" and "pb" in classes:
        if len(source) or not (source.text or "").strip():
            raise ValueError("printed-page carrier is not a simple labeled div")
        return "pb", {"n": (source.text or "").strip()}
    if tag == "div":
        kind = next((_DIV_CLASSES[token] for token in sorted(classes) if token in _DIV_CLASSES), "source-html-div")
        return "ab", {"type": kind}
    if tag not in _TAG_MAP:
        raise ValueError(f"unsupported body element: {tag}")
    mapped, defaults = _TAG_MAP[tag]
    return mapped, dict(defaults)


def _mapped_attributes(source: etree._Element, mapped: str, defaults: dict[str, str]) -> dict[str, str]:
    attributes = dict(defaults)
    rend: list[str] = [attributes.pop("rend")] if "rend" in attributes else []
    for name, value in source.attrib.items():
        name = name.lower()
        if name == "id":
            if not _ID_RE.fullmatch(value):
                raise ValueError(f"source id is not a safe XML id: {value!r}")
            attributes["xml:id"] = value
        elif name == "class":
            rend.append("source-class:" + quote(value, safe=""))
        elif name == "href":
            attributes["target"] = value
        elif name == "src":
            attributes["url"] = value
        elif name == "alt":
            attributes["n"] = value
        elif name == "lang":
            attributes["xml:lang"] = value
        elif name == "colspan":
            attributes["cols"] = value
        elif name in {"title", "width", "height"}:
            rend.append(f"source-{name}:" + quote(value, safe=""))
        else:
            raise ValueError(f"unsupported body attribute {name!r} on {source.tag!r}")
    if rend:
        attributes["rend"] = " ".join(rend)
    return attributes


def _copy_body_node(source: etree._Element, parent: etree._Element) -> None:
    if not isinstance(source.tag, str):
        raise ValueError("HTML comments in the selected body require an explicit mapping")
    tag = source.tag.lower()
    if tag == "dl":
        target = tei_el("list", _mapped_attributes(source, "list", {"type": "definition"}))
        target.text = (source.text or "").replace("\r\n", "\n").replace("\r", "\n") or None
        children = list(source)
        index = 0
        while index < len(children):
            item = tei_el("item")
            if not isinstance(children[index].tag, str) or children[index].tag.lower() not in {"dt", "dd"}:
                raise ValueError("definition list contains a child outside dt/dd")
            if children[index].tag.lower() == "dt":
                _copy_body_node(children[index], item)
                if children[index].tail:
                    item[-1].tail = children[index].tail.replace("\r\n", "\n").replace("\r", "\n")
                index += 1
            while (
                index < len(children)
                and isinstance(children[index].tag, str)
                and children[index].tag.lower() == "dd"
            ):
                _copy_body_node(children[index], item)
                if children[index].tail:
                    item[-1].tail = children[index].tail.replace("\r\n", "\n").replace("\r", "\n")
                index += 1
            target.append(item)
        parent.append(target)
        return
    mapped, defaults = _mapped_tag(source)
    target = tei_el(mapped, _mapped_attributes(source, mapped, defaults))
    target.text = (source.text or "").replace("\r\n", "\n").replace("\r", "\n") or None
    for child in source:
        _copy_body_node(child, target)
        if child.tail:
            target[-1].tail = child.tail.replace("\r\n", "\n").replace("\r", "\n")
    if not len(source) and source.text:
        target.text = source.text.replace("\r\n", "\n").replace("\r", "\n")
    if tag == "div" and "pb" in _class_tokens(source):
        target.text = None
    parent.append(target)


def _verify_sidecars(manifest: object, profile: Mapping[str, object]) -> None:
    work = _strict_json(manifest.authority_path("work-sidecar"), "work sidecar")
    acquisition = _strict_json(manifest.authority_path("acquisition-sidecar"), "acquisition sidecar")
    if work.get("work_id") != profile.get("work_id") or work.get("title") != "The Apostolic Tradition of Hippolytus":
        raise ValueError("work sidecar identity/title differs from the route")
    if acquisition.get("acquisition_id") != profile.get("acquisition_id") or acquisition.get("edition_id") != profile.get("edition_id"):
        raise ValueError("acquisition sidecar identity differs from the route")
    retained = acquisition.get("retained_files")
    if not isinstance(retained, list):
        raise ValueError("acquisition sidecar has no retained member inventory")
    primary = next((item for item in retained if isinstance(item, Mapping) and item.get("path") == profile["source_html"]["path"]), None)
    package = next((item for item in retained if isinstance(item, Mapping) and item.get("path") == profile["source_archive"]["path"]), None)
    if primary is None or package is None:
        raise ValueError("acquisition sidecar does not bind the source and package")
    if primary.get("bytes") != profile["source_html"]["bytes"] or primary.get("sha256") != profile["source_html"]["sha256"]:
        raise ValueError("acquisition sidecar primary-source digest differs")
    if package.get("bytes") != profile["source_archive"]["bytes"] or package.get("sha256") != profile["source_archive"]["sha256"]:
        raise ValueError("acquisition sidecar package digest differs")


def _convert(source_manifest: object) -> Mapping[str, bytes]:
    profile = _strict_json(source_manifest.authority_path("reconstruction-profile"), "source profile")
    policy = _strict_json(source_manifest.authority_path("validation-policy"), "validation policy")
    record = source_manifest.record
    if (
        record.get("work_id") != profile.get("work_id")
        or record.get("edition_id") != profile.get("edition_id")
        or record.get("acquisition_id") != profile.get("acquisition_id")
        or record.get("source_id") != "apostolic-tradition-gutenberg-retained"
        or policy.get("work_id") != profile.get("work_id")
    ):
        raise ValueError("source manifest, profile, and policy identities differ")
    _verify_sidecars(source_manifest, profile)
    source_bytes, archive_bytes = _verify_archive(source_manifest, profile)
    # Use the HTML5 parsing algorithm because the retained document uses
    # HTML5 header/footer elements and its body boundary is part of scope.
    parsed = html5lib.parse(source_bytes, treebuilder="etree", namespaceHTMLElements=False)
    source_body = parsed.find("body")
    source_head = parsed.find("head")
    if source_body is None or source_head is None:
        raise ValueError("retained HTML has no document head/body")
    expected_shell = profile.get("html_shell")
    if not isinstance(expected_shell, Mapping):
        raise ValueError("source profile has no document-shell inventory")
    if re.match(rb"\s*<!doctype\s+html\s*>", source_bytes, re.IGNORECASE) is None:
        raise ValueError("retained HTML doctype differs from the source profile")
    if parsed.get("lang") != expected_shell.get("html_lang"):
        raise ValueError("retained html language differs from the source profile")
    if len(source_head) != expected_shell.get("head_direct_children"):
        raise ValueError("HTML head direct-child count differs from the source profile")
    meta = next((item for item in source_head if isinstance(item.tag, str) and item.tag.lower() == "meta" and item.get("name") == "dc.rights"), None)
    if meta is None or meta.get("content") != expected_shell.get("head_dc_rights"):
        raise ValueError("HTML head rights metadata differs from the source profile")
    facts = _profile_body_facts(source_body)
    expected_body = profile.get("body")
    if not isinstance(expected_body, Mapping):
        raise ValueError("source profile has no body inventory")
    for key in (
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
    ):
        if facts[key] != expected_body.get(key):
            raise ValueError(f"source body {key} differs from its declared profile")
    archive_hash = _sha(archive_bytes)
    header = stamp_header(
        title="The Apostolic Tradition of Hippolytus",
        author="Hippolytus (traditional attribution; see the source introduction)",
        contributors=[{"name": "Burton Scott Easton", "role": "translator, introduction, and notes"}],
        source_url="https://www.gutenberg.org/ebooks/61614",
        source_sha256=_sha(source_bytes),
        print_source=(
            "Project Gutenberg eBook 61614, whose title page states Copyright 1934, "
            "Cambridge University Press and reprinted 1962 by arrangement with Cambridge University Press."
        ),
    )
    root = tei_el("TEI", {"xml:lang": "en"})
    root.append(header)
    encoding = tei_el("encodingDesc")
    project = tei_el("projectDesc")
    project.append(
        tei_el(
            "p",
            text=(
                "Nonaccepted technical reconstruction candidate. The complete parsed HTML body is represented in source order. "
                "The recorded rights hold, physical-edition question, human acceptance, and publication decision remain unresolved."
            ),
        )
    )
    encoding.append(project)
    root[0].append(encoding)
    text = tei_el("text")
    body = tei_el("body")
    body_content = tei_el("ab", {"type": "complete-gutenberg-html-body"})
    body_content.text = (source_body.text or "").replace("\r\n", "\n").replace("\r", "\n") or None
    for child in source_body:
        _copy_body_node(child, body_content)
        if child.tail:
            body_content[-1].tail = child.tail.replace("\r\n", "\n").replace("\r", "\n")
    body.append(body_content)
    text.append(body)
    root.append(text)
    candidate_bytes = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    account = {
        "contract": "ocd-apostolic-tradition-source-accountability-v1",
        "work_id": profile["work_id"],
        "edition_id": profile["edition_id"],
        "acquisition_id": profile["acquisition_id"],
        "source_sha256": _sha(source_bytes),
        "source_archive_sha256": archive_hash,
        "candidate_sha256": _sha(candidate_bytes),
        "document_shell": profile["html_shell"],
        "body_inventory": expected_body,
        "mapping": profile["mapping"],
    }
    provenance = policy.get("provenance")
    unresolved = policy.get("unresolved")
    if not isinstance(provenance, Mapping) or not isinstance(unresolved, list):
        raise ValueError("validation policy provenance or unresolved list is invalid")
    return {
        "README.source.md": source_manifest.authority_path("source-readme").read_bytes(),
        "content.tei.xml": candidate_bytes,
        "source-accountability.json": _canonical(account),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
    }


_convert.converter_id = "ocd-apostolic-tradition-html-to-tei"
_convert.converter_version = "1"
_convert.implementation_path = Path(__file__).resolve()
