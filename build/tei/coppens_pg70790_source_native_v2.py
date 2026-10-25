"""Build a source-accounted successor for the retained Coppens PG70790 witness.

The predecessor TEI is retained as a frozen historical input.  This route does
not infer missing text from it: before making the two explicit empty-attribute
carriers and adding a source-description paragraph, it verifies the complete
predecessor body tree, order, text, tails, and source attributes against the
exact retained HTML member.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import Mapping

from lxml import etree, html

from ocd_kernel.lib.path_io import io_path
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


converter_id = "ocd-coppens-pg70790-source-native-v2"
converter_version = "2"

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
PROFILE_AUTHORITY = "source-feature-profile"
SOURCE_AUTHORITY = "retained-archive"
NOTICE_AUTHORITY = "source-notice"
PREDECESSOR_PATH = Path(
    r"D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260928-l793-l795-fresh-replays\L793-PG70790-fresh-1\package"
)
PREDECESSOR_MANIFEST_SHA256 = "2640cc87a9cdcbc4e75b8fc0c0def8f773038f3072f4c349ba1bf416a04ffa5d"
PREDECESSOR_TEI_SHA256 = "6d073f71cc75a46761c29b886ef33c331501778dd87472b64ddb9b94ead6bae3"
PREDECESSOR_SOURCE_MANIFEST_SHA256 = "192c1556ab84c032252ae5c9ff1e6d290ca3ad85103deabb7f678f1529fc54b8"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _norm(value: str | None) -> str:
    return " ".join((value or "").split())


def _profile(source_manifest: SourceManifest) -> dict[str, object]:
    path = source_manifest.authority_path(PROFILE_AUTHORITY)
    raw = io_path(path).read_bytes()
    profile = json.loads(raw)
    if profile.get("contract") != "ocd-coppens-pg70790-profile-v2":
        raise ValueError("Coppens source profile contract mismatch")
    if profile.get("predecessor_candidate_manifest_sha256") != PREDECESSOR_MANIFEST_SHA256:
        raise ValueError("frozen Coppens predecessor manifest binding mismatch")
    if profile.get("predecessor_content_sha256") != PREDECESSOR_TEI_SHA256:
        raise ValueError("frozen Coppens predecessor TEI binding mismatch")
    if profile.get("predecessor_source_manifest_sha256") != PREDECESSOR_SOURCE_MANIFEST_SHA256:
        raise ValueError("frozen Coppens predecessor source-manifest binding mismatch")
    for field in ("source_id", "work_id", "edition_id", "acquisition_id"):
        if source_manifest.record.get(field) != profile.get(field):
            raise ValueError(f"source manifest/profile {field} mismatch")
    return profile


def _archive(source_manifest: SourceManifest, profile: Mapping[str, object]):
    archive_path = source_manifest.authority_path(SOURCE_AUTHORITY)
    archive_bytes = io_path(archive_path).read_bytes()
    if _sha(archive_bytes) != profile.get("source_archive_sha256"):
        raise ValueError("retained PG70790 archive digest mismatch")
    with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
        names = sorted(archive.namelist())
        expected = ["images/cover.jpg", "pg70790-images.html"]
        if names != expected or archive.testzip() is not None:
            raise ValueError("PG70790 retained archive member set or CRC check failed")
        members = []
        payloads = {}
        for name in names:
            info = archive.getinfo(name)
            payload = archive.read(name)
            members.append(
                {
                    "path": name,
                    "bytes": len(payload),
                    "crc32": f"{info.CRC:08x}",
                    "sha256": _sha(payload),
                }
            )
            payloads[name] = payload
    if members != profile.get("source_archive_members"):
        raise ValueError("PG70790 archive member facts differ from the frozen profile")
    return archive_bytes, members, payloads


def _parse_source_html(source_html: bytes) -> tuple[etree._Element, list[dict[str, object]]]:
    parser = html.HTMLParser(encoding="utf-8", recover=True, no_network=True)
    source_root = html.fromstring(source_html, parser=parser)
    diagnostics = [
        {
            "line": item.line,
            "column": item.column,
            "domain": item.domain_name,
            "type": item.type_name,
            "message": item.message,
        }
        for item in parser.error_log
    ]
    return source_root, diagnostics


def _comment_inventory(source_root: etree._Element) -> list[dict[str, object]]:
    comments = source_root.xpath("//comment()")
    rows = []
    for index, comment in enumerate(comments, 1):
        parent = comment.getparent()
        rows.append(
            {
                "position": index,
                "parent_path": source_root.getroottree().getpath(parent).strip("/"),
                "parent_tag": etree.QName(parent).localname,
                "kind": "comment",
                "text": comment.text or "",
            }
        )
    return rows


def _predecessor(profile: Mapping[str, object]) -> tuple[CandidatePackage, bytes]:
    path = Path(str(profile["predecessor_candidate_path"]))
    candidate = CandidatePackage.load(path)
    if candidate.sha256 != PREDECESSOR_MANIFEST_SHA256:
        raise ValueError("frozen predecessor package manifest digest mismatch")
    if candidate.manifest.get("source_manifest", {}).get("sha256") != PREDECESSOR_SOURCE_MANIFEST_SHA256:
        raise ValueError("frozen predecessor package source-manifest binding mismatch")
    content = candidate.member_bytes("content.tei.xml")
    if _sha(content) != PREDECESSOR_TEI_SHA256:
        raise ValueError("frozen predecessor TEI digest mismatch")
    return candidate, content


def _tag_rule(source_tag: str, tei_node: etree._Element) -> bool:
    local = etree.QName(tei_node).localname
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
        allowed_locals = {"ab", "seg"}
        expected_type = f"source-{source_tag}"
        return local in allowed_locals and node_type == expected_type
    return False


def _verify_body(
    source_html: bytes, candidate_tei: bytes, *, require_empty_carriers: bool
) -> tuple[dict[str, object], etree._Element, etree._Element]:
    source_root, _ = _parse_source_html(source_html)
    source_body = source_root.find("body")
    if source_body is None:
        raise ValueError("retained HTML has no body")
    source_nodes = list(source_body.iter())
    tei_root = etree.fromstring(
        candidate_tei,
        parser=etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False),
    )
    if tei_root.tag != f"{{{TEI}}}TEI":
        raise ValueError("frozen predecessor is not a direct TEI root")
    tei_body = tei_root.find(f".//{{{TEI}}}body")
    if tei_body is None:
        raise ValueError("frozen predecessor has no TEI body")
    tei_nodes = list(tei_body.iter())
    if len(source_nodes) != len(tei_nodes):
        raise ValueError("source and predecessor body element counts differ")

    locator_rows: list[dict[str, str]] = []

    def visit(source_node: etree._Element, path: str) -> None:
        index = source_nodes.index(source_node)
        tei_node = tei_nodes[index]
        if path and tei_node.get("n") != path:
            raise ValueError(f"source locator mismatch at {path}")
        if not path and tei_node.tag != f"{{{TEI}}}body":
            raise ValueError("source body root did not bind the TEI body")
        source_tag = etree.QName(source_node).localname
        if not _tag_rule(source_tag, tei_node):
            raise ValueError(f"source element type mismatch at {path or 'body'}")
        if _norm(source_node.text) != _norm(tei_node.text):
            raise ValueError(f"source text mismatch at {path or 'body'}")
        if _norm(source_node.tail) != _norm(tei_node.tail):
            raise ValueError(f"source tail mismatch at {path or 'body'}")
        if len(source_node) != len(tei_node):
            raise ValueError(f"source child count mismatch at {path or 'body'}")
        if path:
            locator_rows.append({"locator": path, "source_tag": source_tag})
            attrs = {etree.QName(k).localname: v for k, v in tei_node.attrib.items()}
            source_attrs = {etree.QName(k).localname: v for k, v in source_node.attrib.items()}
            if "id" in source_attrs and attrs.get("id") != source_attrs["id"]:
                raise ValueError(f"source id mismatch at {path}")
            if "class" in source_attrs and f"source-class:{source_attrs['class']}" not in (attrs.get("rend") or ""):
                raise ValueError(f"source class mismatch at {path}")
            if "style" in source_attrs and f"source-style:{source_attrs['style']}" not in (attrs.get("rend") or ""):
                raise ValueError(f"source style mismatch at {path}")
            if "href" in source_attrs and attrs.get("target") != source_attrs["href"]:
                raise ValueError(f"source href mismatch at {path}")
            if "src" in source_attrs and attrs.get("url") != source_attrs["src"]:
                raise ValueError(f"source image URL mismatch at {path}")
            if "lang" in source_attrs and tei_node.get(f"{{{XML}}}lang") != source_attrs["lang"]:
                raise ValueError(f"source language mismatch at {path}")
            if "title" in source_attrs:
                marker = "source-title-empty" if source_attrs["title"] == "" else f"source-title:{source_attrs['title']}"
                if require_empty_carriers or source_attrs["title"] != "":
                    if marker not in (attrs.get("rend") or ""):
                        raise ValueError(f"source title attribute mismatch at {path}")
            if "alt" in source_attrs:
                marker = "source-alt-empty" if source_attrs["alt"] == "" else f"source-alt:{source_attrs['alt']}"
                if require_empty_carriers or source_attrs["alt"] != "":
                    if marker not in (attrs.get("rend") or ""):
                        raise ValueError(f"source alt attribute mismatch at {path}")
        for child_index, child in enumerate(source_node, 1):
            child_path = str(child_index) if not path else f"{path}.{child_index}"
            visit(child, child_path)

    visit(source_body, "")
    source_text = _norm("".join(source_body.itertext()))
    tei_text = _norm("".join(tei_body.itertext()))
    if source_text != tei_text:
        raise ValueError("retained source and predecessor body text differ")
    tag_counts = Counter(etree.QName(node).localname for node in source_nodes)
    attribute_counts = Counter(
        etree.QName(name).localname
        for node in source_nodes
        for name in node.attrib
    )
    locator_digest = _sha(_json_bytes(locator_rows))
    body_accountability = {
        "direct_child_count": len(source_body),
        "element_count_including_body": len(source_nodes),
        "mapped_descendant_count": len(locator_rows),
        "normalized_text_characters": len(source_text),
        "normalized_text_sha256": _sha(source_text.encode("utf-8")),
        "locator_tag_map_sha256": locator_digest,
        "source_tag_counts": dict(sorted(tag_counts.items())),
        "source_attribute_counts": dict(sorted(attribute_counts.items())),
        "attribute_mapping": {
            "id": "xml:id, exact source value",
            "class": "@rend source-class:<exact source value>",
            "style": "@rend source-style:<exact source value>",
            "title": "@rend source-title:<exact source value>; source-title-empty preserves an explicit empty value",
            "href": "@target, exact source URI or fragment",
            "src": "@url, exact retained member path",
            "lang": "@xml:lang, exact source value",
            "alt": "@rend source-alt:<exact source value>; source-alt-empty preserves an explicit empty value",
        },
        "all_source_elements_and_text_are_represented": True,
    }
    return body_accountability, tei_root, tei_body


def _head_inventory(source_root: etree._Element) -> list[dict[str, object]]:
    head = source_root.find("head")
    if head is None:
        raise ValueError("retained HTML has no head")
    return [
        {
            "position": index,
            "tag": etree.QName(node).localname,
            "attributes": dict(sorted((etree.QName(key).localname, value) for key, value in node.attrib.items())),
            "text": node.text or "",
            "tail": node.tail or "",
            "disposition": _head_disposition(node),
        }
        for index, node in enumerate(head, 1)
    ]


def _head_disposition(node: etree._Element) -> str:
    tag = etree.QName(node).localname
    attrs = {etree.QName(key).localname: value for key, value in node.attrib.items()}
    if tag == "style":
        return "Presentation CSS; retained byte-for-byte in the source archive and excluded from textual TEI content."
    if tag == "title":
        return "Project Gutenberg HTML document title; preserved exactly in this inventory, distinct from the complete title-page title."
    if tag == "meta" and attrs.get("charset"):
        return "HTML byte-encoding declaration; retained in the hash-bound HTML source."
    if tag == "link" and attrs.get("rel") == "icon":
        return "Local cover/icon pointer; the exact cover member is retained and hash-bound."
    if tag == "link" and attrs.get("rel", "").startswith("schema."):
        return "Metadata vocabulary link; retained as source structure, not a work content claim."
    if tag == "link" and attrs.get("rel") == "dcterms.isFormatOf":
        return "Project Gutenberg ebook-format relation; retained as provider metadata."
    if tag == "meta" and attrs.get("property") == "og:image":
        return "External Open Graph image pointer; metadata-only and not fetched."
    if tag == "meta" and attrs.get("name") == "format-detection":
        return "Browser presentation hint; exact value retained but not transcribed as textual content."
    if tag == "meta" and attrs.get("name") == "generator":
        return "Source-production metadata; exact value retained."
    if tag == "meta":
        return f"Provider-supplied {attrs.get('name') or attrs.get('property') or 'metadata'} assertion; exact value retained without independent promotion."
    if tag == "link":
        return "Source link metadata; exact values retained."
    return "Unclassified source head node; retained in exact inventory and source archive."


def _source_metadata_inventory(source_root: etree._Element) -> dict[str, object]:
    head = source_root.find("head")
    assert head is not None
    meta: dict[str, list[str]] = {}
    links: list[dict[str, str]] = []
    for node in head:
        tag = etree.QName(node).localname
        attrs = {etree.QName(k).localname: v for k, v in node.attrib.items()}
        if tag == "meta" and attrs.get("name"):
            meta.setdefault(attrs["name"], []).append(attrs.get("content", ""))
        elif tag == "meta" and attrs.get("property"):
            meta.setdefault(attrs["property"], []).append(attrs.get("content", ""))
        elif tag == "link":
            links.append(attrs)
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
            {"position": item["position"], "tag": item["tag"], "decision": item["disposition"]}
            for item in _head_inventory(source_root)
        ],
    }


def _add_source_carriers(tei_root: etree._Element, profile: Mapping[str, object]) -> bytes:
    empty_title = tei_root.find(f".//{{{TEI}}}seg[@n='1.1']")
    cover = tei_root.find(f".//{{{TEI}}}graphic[@n='3.2']")
    if empty_title is None or cover is None:
        raise ValueError("expected source title/cover carriers are absent")
    if empty_title.get("rend"):
        raise ValueError("empty source title selector already has an unexpected rendition")
    if cover.get("url") != "images/cover.jpg":
        raise ValueError("source cover selector does not bind the retained cover member")
    empty_title.set("rend", "source-title-empty")
    cover_rend = cover.get("rend", "")
    if "source-alt-empty" in cover_rend:
        raise ValueError("source alt carrier is already present in predecessor")
    cover.set("rend", (cover_rend + " source-alt-empty").strip())
    source_desc = tei_root.find(f".//{{{TEI}}}sourceDesc")
    if source_desc is None or len(source_desc) != 1:
        raise ValueError("predecessor sourceDesc shape differs from the pinned profile")
    note = etree.SubElement(source_desc, f"{{{TEI}}}p")
    note.text = str(profile["tei_source_description_addition"])
    return etree.tostring(
        tei_root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    """Return exactly the five package members required by reconstruction v1."""

    profile = _profile(source_manifest)
    readme = io_path(source_manifest.authority_path(NOTICE_AUTHORITY)).read_bytes()
    if not readme.startswith(b"# The Spiritual Exercises of St. Ignatius Adapted to an Eight Days Retreat and Six Triduums\n"):
        raise ValueError("source notice title does not bind the retained title page")
    if b"A Short Method of Prayer" in readme:
        raise ValueError("source notice contains the unrelated predecessor title")
    archive_bytes, archive_members, payloads = _archive(source_manifest, profile)
    predecessor, predecessor_tei = _predecessor(profile)
    source_html = payloads["pg70790-images.html"]
    source_root, diagnostics = _parse_source_html(source_html)
    if diagnostics != profile.get("html_source_parse", {}).get("diagnostics"):
        raise ValueError("retained HTML parser diagnostics differ from source profile")
    non_element_markup = _comment_inventory(source_root)
    if non_element_markup != profile.get("html_non_element_markup"):
        raise ValueError("HTML comment/non-element inventory differs from the source profile")
    _verify_body(source_html, predecessor_tei, require_empty_carriers=False)
    head_inventory = _head_inventory(source_root)
    if len(head_inventory) != profile.get("html_head_child_count"):
        raise ValueError("PG70790 HTML head child count differs from the frozen profile")
    content = _add_source_carriers(tei_root, profile)
    body_accountability, _, _ = _verify_body(
        source_html, content, require_empty_carriers=True
    )
    accounting = {
        "contract": "ocd-coppens-pg70790-source-accountability-v2",
        "work_id": profile["work_id"],
        "edition_id": profile["edition_id"],
        "acquisition_id": profile["acquisition_id"],
        "scope": profile["complete_title_boundary"],
        "source_archive": {
            "logical_path": profile["source_archive_path"],
            "bytes": len(archive_bytes),
            "sha256": _sha(archive_bytes),
            "member_count": len(archive_members),
            "members": archive_members,
        },
        "html_member": {
            "path": "pg70790-images.html",
            "bytes": len(source_html),
            "sha256": _sha(source_html),
            "head_child_count": len(head_inventory),
            "head_inventory": head_inventory,
            "head_metadata": _source_metadata_inventory(source_root),
            "source_html_parser": profile["html_source_parse"],
            "non_element_markup": non_element_markup,
            "body": body_accountability,
        },
        "candidate_repairs": [
            {
                "source_locator": "body/1/1",
                "source_attribute": "title=\"\"",
                "candidate_locator": "@n=1.1",
                "carrier": "@rend contains source-title-empty",
            },
            {
                "source_locator": "body/3/2",
                "source_attribute": "alt=\"\"",
                "candidate_locator": "@n=3.2",
                "carrier": "graphic/@rend contains source-alt-empty",
            },
        ],
        "title_page_imprint": profile["title_page_imprint"],
        "electronic_metadata_date_roles": profile["electronic_metadata_date_roles"],
        "predecessor": {
            "candidate_manifest_sha256": predecessor.sha256,
            "source_manifest_sha256": PREDECESSOR_SOURCE_MANIFEST_SHA256,
            "content_sha256": _sha(predecessor_tei),
            "use": "Frozen input; its TEI body is independently reconciled against the current retained raw HTML before the two empty-attribute carriers and source-description addition are made.",
        },
        "body_candidate_sha256": _sha(content),
    }
    provenance = {
        "acquisition_id": profile["acquisition_id"],
        "edition_id": profile["edition_id"],
        "source_id": profile["source_id"],
        "source_manifest_sha256": source_manifest.sha256,
        "status": "nonaccepted",
        "work_id": profile["work_id"],
    }
    unresolved = (
        {"id": "pg70790-print-collation", "status": "unresolved", "detail": "The retained Project Gutenberg electronic witness has not been collated against a print exemplar."},
        {"id": "pg70790-human-acceptance", "status": "unresolved", "detail": "No human text or edition acceptance has been recorded."},
        {"id": "pg70790-rights", "status": "unresolved", "detail": "Project Gutenberg states public domain in the USA; jurisdictional rights clearance and publication remain pending."},
    )
    if set(payloads) != {"images/cover.jpg", "pg70790-images.html"}:
        raise ValueError("unexpected retained archive envelope")
    return {
        "README.source.md": readme,
        "content.tei.xml": content,
        "provenance.json": _json_bytes(provenance),
        "source-accountability.json": _json_bytes(accounting),
        "unresolved.jsonl": b"".join(_json_bytes(item) for item in unresolved),
    }


_convert.converter_id = converter_id  # type: ignore[attr-defined]
_convert.converter_version = converter_version  # type: ignore[attr-defined]
