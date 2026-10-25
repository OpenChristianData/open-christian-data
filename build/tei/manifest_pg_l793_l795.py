"""Source-specific TEI corpus reconstruction for retained PG L793-L795 witnesses."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from lxml import etree, html

from ocd_kernel.reconstruction.contract import SourceManifest


TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _node(parent: etree._Element, name: str, **attributes: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{TEI}}}{name}", **attributes)


def _read_source(manifest: SourceManifest) -> tuple[dict[str, object], etree._Element, list[dict[str, object]]]:
    profile = json.loads(manifest.authority_path("profile").read_text(encoding="utf-8"))
    archive_path = manifest.authority_path("retained-archive")
    receipt = json.loads(manifest.authority_path("acquisition-receipt").read_text(encoding="utf-8"))
    if _sha(archive_path.read_bytes()) != profile["archive_sha256"] or receipt["package"]["sha256"] != profile["archive_sha256"]:
        raise ValueError("retained archive or acquisition receipt digest differs from source profile")
    with ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("retained archive CRC failure")
        members = [
            {"path": item.filename, "bytes": item.file_size, "crc32": f"{item.CRC:08x}", "sha256": _sha(archive.read(item))}
            for item in archive.infolist() if not item.is_dir()
        ]
        if members != profile["archive_members"]:
            raise ValueError("retained archive member inventory differs from profile")
        source_bytes = archive.read(str(profile["html_member"]))
    if _sha(source_bytes) != profile["html_sha256"] or receipt["html"]["sha256"] != profile["html_sha256"]:
        raise ValueError("HTML member digest differs from source profile or receipt")
    if manifest.authority_path("extracted-html").read_bytes() != source_bytes:
        raise ValueError("retained extracted HTML differs from archive member")
    root = html.fromstring(source_bytes.decode("utf-8", errors="strict"))
    body = root.find(".//body")
    if body is None or len(body) != profile["body_direct_children"]:
        raise ValueError("source HTML body boundary or direct-child count differs")
    return profile, body, members


def _element_name(tag: str, *, top_level: bool) -> tuple[str, dict[str, str]]:
    allowed = {
        "header", "footer", "div", "figure", "p", "h1", "h2", "h3", "h4", "blockquote",
        "ul", "ol", "li", "table", "tbody", "thead", "tfoot", "tr", "td",
        "th", "colgroup", "col", "a", "img", "br", "hr", "span", "i", "em",
        "strong", "b", "small", "sup", "sub", "cite", "ins", "pre", "abbr",
    }
    if tag not in allowed:
        raise ValueError(f"unmapped retained HTML tag: {tag}")
    if top_level:
        return (tag, {}) if tag in {"table", "figure"} else ("ab", {"type": f"source-{tag}"})
    if tag in {"table", "figure"}:
        return tag, {}
    if tag == "tr":
        return "row", {}
    if tag in {"td", "th"}:
        return "cell", {"role": "label"} if tag == "th" else {}
    if tag == "a":
        return "ref", {}
    if tag == "img":
        return "graphic", {}
    if tag == "br":
        return "lb", {}
    if tag == "hr":
        return "milestone", {"unit": "source-rule"}
    if tag in {"i", "em", "strong", "b", "small", "sup", "sub"}:
        return "hi", {"rend": tag}
    if tag == "cite":
        return "title", {"type": "source-citation"}
    if tag == "ins":
        return "add", {}
    return "seg", {"type": f"source-{tag}"}


def _copy(source: etree._Element, parent: etree._Element, number: str, *, top_level: bool = False) -> etree._Element:
    if not isinstance(source.tag, str):
        target = _node(parent, "milestone", unit="source-comment", n=str(number))
        target.set("rend", "comment-sha256:" + _sha((source.text or "").encode("utf-8")))
        target.tail = source.tail
        return target
    tag = source.tag.lower()
    if tag in {"tbody", "thead", "tfoot", "colgroup", "col"}:
        start = _node(parent, "milestone", unit=f"source-{tag}-start", n=number)
        start.set(XML_ID, source.get("id") or f"source-node-{number}")
        start.tail = source.text
        for index, child in enumerate(source, 1):
            _copy(child, parent, f"{number}.{index}")
        end = _node(parent, "milestone", unit=f"source-{tag}-end", n=f"{number}.end")
        end.set(XML_ID, f"source-node-{number}.end")
        end.tail = source.tail
        return start
    name, attributes = _element_name(tag, top_level=top_level)
    target = _node(parent, name, **attributes)
    target.set("n", str(number))
    if source.get("id"):
        target.set(XML_ID, source.get("id"))
    else:
        target.set(XML_ID, f"source-node-{number}")
    if source.get("lang"):
        target.set(XML_LANG, source.get("lang"))
    render = [f"source-class:{source.get('class')}"] if source.get("class") else []
    if source.get("style"):
        render.append(f"source-style:{source.get('style')}")
    if source.get("title"):
        render.append(f"source-title:{source.get('title')}")
    if tag == "a" and source.get("href") == "":
        render.append("source-href-empty")
    if render:
        target.set("rend", " | ".join(filter(None, (target.get("rend"), *render))))
    if tag == "a" and source.get("href"):
        target.set("target", source.get("href"))
    if tag == "img":
        if not source.get("src"):
            raise ValueError("source image lacks a path")
        target.set("url", source.get("src"))
        if source.get("alt"):
            target.set("rend", " | ".join(filter(None, (target.get("rend"), "source-alt:" + source.get("alt")))))
    if tag in {"td", "th"} and source.get("colspan"):
        target.set("cols", source.get("colspan"))
    target.text = source.text
    for index, child in enumerate(source, 1):
        _copy(child, target, f"{number}.{index}")
    target.tail = source.tail
    return target


def _header(parent: etree._Element, *, title: str, source: str, scope: str, contributors: list[dict[str, str]]) -> None:
    header = _node(parent, "teiHeader")
    description = _node(header, "fileDesc")
    title_statement = _node(description, "titleStmt")
    _node(title_statement, "title").text = title
    for contributor in contributors:
        if contributor["role"] in {"author", "editor"}:
            _node(title_statement, contributor["role"]).text = contributor["name"]
        else:
            statement = _node(title_statement, "respStmt")
            _node(statement, "resp").text = contributor["role"]
            _node(statement, "name").text = contributor["name"]
    publication = _node(description, "publicationStmt")
    _node(publication, "p").text = "Nonaccepted source reconstruction candidate. Human acceptance, rights clearance, and publication are pending."
    source_description = _node(description, "sourceDesc")
    _node(source_description, "p").text = f"{source}. Scope: {scope}."


def _convert(manifest: SourceManifest) -> dict[str, bytes]:
    profile, body, members = _read_source(manifest)
    corpus = etree.Element(f"{{{TEI}}}teiCorpus", nsmap={None: TEI})
    corpus.set(XML_ID, f"pg{profile['ebook_id']}-complete-edition")
    _header(corpus, title=str(profile["volume_title"]), source=f"Project Gutenberg {profile['ebook_id']}, retained archive SHA-256 {profile['archive_sha256']}", scope=str(profile["volume_scope"]), contributors=list(profile["contributors"]))
    units = profile["units"]
    if not units or units[0]["start"] != 0 or units[-1]["end"] != len(body) - 1:
        raise ValueError("source unit ranges do not cover complete HTML body")
    if any(left["end"] + 1 != right["start"] for left, right in zip(units, units[1:])):
        raise ValueError("source unit ranges overlap or leave a gap")
    for unit in units:
        text_document = _node(corpus, "TEI")
        text_document.set(XML_ID, str(unit["id"]))
        _header(text_document, title=str(unit["title"]), source=f"Project Gutenberg {profile['ebook_id']} retained HTML, direct children {unit['start']}–{unit['end']}", scope=str(unit["scope"]), contributors=list(profile["contributors"]))
        body_target = _node(_node(text_document, "text"), "body")
        if unit["start"] == 0:
            body_target.text = body.text
        for index in range(unit["start"], unit["end"] + 1):
            _copy(body[index], body_target, str(index + 1), top_level=True)
    xml = etree.tostring(corpus, encoding="UTF-8", xml_declaration=True)
    account = {
        "source_tag_counts": profile["source_tag_counts"],
        "source_attribute_counts": profile["source_attribute_counts"],
        "contract": "ocd-manifest-pg-l793-l795-source-accounting-v1",
        "ebook_id": profile["ebook_id"],
        "archive_sha256": profile["archive_sha256"],
        "html_sha256": profile["html_sha256"],
        "archive_members": members,
        "body_direct_children": len(body),
        "body_text_sha256": _sha("".join(body.itertext()).encode("utf-8")),
        "units": units,
        "tei_sha256": _sha(xml),
        "body_element_count": sum(1 for e in body.iter() if isinstance(e.tag, str)),
        "image_references": [e.get("src") for e in body.iter("img")],
        "link_references": [e.get("href") for e in body.iter("a") if e.get("href")],
        "mapping": "Every retained HTML body direct child is represented once in source order; nested text, local links, headings, images, lists, tables, inline emphasis, and source IDs are mapped. HTML head and binary image members remain retained and hash-accounted; the source archive controls visual assets.",
    }
    policy = json.loads(manifest.authority_path("policy").read_text(encoding="utf-8"))
    return {
        "content.tei.xml": xml,
        "source-accountability.json": _json(account),
        "README.source.md": manifest.authority_path("readme").read_bytes(),
        "provenance.json": _json(policy["provenance"]),
        "unresolved.jsonl": b"".join(_json(item) for item in policy["unresolved"]),
    }


_convert.converter_id = "ocd-manifest-pg-l793-l795-editions-to-tei-corpus"
_convert.converter_version = "1"
_convert.implementation_path = Path(__file__).resolve()
