"""Source-bound, nonaccepted TEI reconstruction of Gutenberg eBook 38326."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping
from urllib.parse import quote
from zipfile import ZipFile

import html5lib
from lxml import etree

from ocd_kernel.tei.writer import stamp_header, tei_el


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _profile(manifest: object) -> dict[str, object]:
    return json.loads(manifest.authority_path("source-profile").read_text(encoding="utf-8"))


def _source(manifest: object, profile: Mapping[str, object]) -> bytes:
    source = manifest.authority_path("retained-html").read_bytes()
    expected = profile["source_html"]
    if len(source) != expected["bytes"] or _sha(source) != expected["sha256"]:
        raise ValueError("Bede retained HTML differs from its source profile")
    archive = manifest.authority_path("retained-archive")
    raw_archive = archive.read_bytes()
    package = profile["source_archive"]
    if len(raw_archive) != package["bytes"] or _sha(raw_archive) != package["sha256"]:
        raise ValueError("Bede retained ZIP differs from its source profile")
    with ZipFile(archive) as members:
        if members.testzip() is not None:
            raise ValueError("Bede ZIP CRC failed")
        actual = [
            {"path": info.filename, "bytes": info.file_size, "crc32": f"{info.CRC:08x}", "sha256": _sha(members.read(info))}
            for info in members.infolist() if not info.is_dir()
        ]
        if actual != package["members"] or members.read("pg38326-images.html") != source:
            raise ValueError("Bede ZIP member census or extracted HTML differs")
        cover = manifest.authority_path("cover-image").read_bytes()
        if members.read("38326-cover.png") != cover or _sha(cover) != profile["source_support"]["sha256"]:
            raise ValueError("Bede extracted cover differs from ZIP")
    acquisition = json.loads(manifest.authority_path("acquisition-sidecar").read_text(encoding="utf-8"))
    if (acquisition.get("source_path") != expected["path"] or acquisition.get("source_sha256") != expected["sha256"]
            or acquisition.get("edition_id") != profile["edition_id"]
            or acquisition.get("acquisition_id") != profile["acquisition_id"]):
        raise ValueError("Bede acquisition sidecar differs from source profile")
    return source


def _classes(element: object) -> set[str]:
    return set((element.get("class") or "").split())


def _title(element: object) -> str:
    heading = next((child for child in element if child.tag in {"h1", "h2"}), None)
    return " ".join("".join(heading.itertext()).split()) if heading is not None else ""


def _tag(element: object) -> tuple[str, dict[str, str]]:
    tag = element.tag
    classes = _classes(element)
    if tag == "div":
        if "tei-tb" in classes:
            if len(element) != 1 or element[0].tag != "hr" or "".join(element.itertext()).strip():
                raise ValueError("Bede text break is not the profiled empty break")
            return "milestone", {"unit": "source-text-break"}
        if "tei-lg" in classes:
            return "lg", {}
        if "tei-l" in classes:
            return "l", {}
        if "tei-quote" in classes:
            return "quote", {}
        name = _title(element)
        if name.startswith("Book ") and name in {f"Book {n}" for n in ("I", "II", "III", "IV", "V")}:
            kind = "book"
        elif name.startswith("Chap. "):
            kind = "chapter"
        elif name == "Continuation":
            kind = "continuation"
        elif name == "Footnotes":
            kind = "notes"
        elif name:
            kind = "section"
        else:
            kind = "source-wrapper"
        return "div", {"type": kind}
    if tag == "span":
        if "tei-pb" in classes:
            return "pb", {"n": " ".join("".join(element.itertext()).split())}
        return "seg", {}
    if tag == "a":
        if not element.get("href") and not "".join(element.itertext()).strip() and len(element) == 0:
            return "anchor", {}
        return "ref", {}
    simple = {"p": "p", "h1": "head", "h2": "head", "ul": "list", "li": "item",
              "hr": "milestone", "br": "lb", "pre": "ab"}
    if tag in simple:
        mapped = simple[tag]
        attrs = {"unit": "source-rule"} if tag == "hr" else {"type": "source-pre"} if tag == "pre" else {}
        if tag == "ul":
            attrs = {"type": "contents"} if "tei-index-toc" in classes else {"type": "unordered"}
        return mapped, attrs
    raise ValueError(f"unmapped Bede source element: {tag}")


def _attributes(element: object, defaults: Mapping[str, str]) -> dict[str, str]:
    attrs = dict(defaults)
    rend = []
    for key, value in element.attrib.items():
        if key == "id":
            attrs["xml:id"] = value
        elif key == "href":
            attrs["target"] = value
        elif key == "lang":
            attrs["xml:lang"] = value
        elif key in {"class", "style"}:
            rend.append(f"source-{key}:" + quote(value, safe=""))
        else:
            raise ValueError(f"unmapped Bede source attribute {key} on {element.tag}")
    if rend:
        attrs["rend"] = " ".join(rend)
    return attrs


def _copy(element: object, parent: etree._Element) -> None:
    if element.tag == "dl":
        target = tei_el("list", _attributes(element, {"type": "footnotes"}))
        children = list(element)
        if len(children) % 2 or any(children[i].tag != "dt" or children[i + 1].tag != "dd" for i in range(0, len(children), 2)):
            raise ValueError("Bede footnotes are not paired dt/dd carriers")
        target.text = element.text
        for index in range(0, len(children), 2):
            item = tei_el("item")
            for child, mapped in ((children[index], "label"), (children[index + 1], "note")):
                node = tei_el(mapped, _attributes(child, {}), child.text)
                for inner in child:
                    _copy(inner, node)
                    node[-1].tail = inner.tail
                item.append(node)
                node.tail = child.tail
            target.append(item)
        parent.append(target)
        return
    mapped, defaults = _tag(element)
    target = tei_el(mapped, _attributes(element, defaults))
    target.text = None if mapped in {"pb", "milestone"} else element.text
    if mapped == "pb" and len(element):
        raise ValueError("Bede page marker has nested content")
    if not (element.tag == "div" and mapped == "milestone"):
        for child in element:
            _copy(child, target)
            target[-1].tail = child.tail
    parent.append(target)


def _convert(manifest: object) -> Mapping[str, bytes]:
    profile = _profile(manifest)
    policy = json.loads(manifest.authority_path("validation-policy").read_text(encoding="utf-8"))
    if any(manifest.record.get(key) != profile[key] for key in ("work_id", "edition_id", "acquisition_id")):
        raise ValueError("Bede source manifest identity differs from profile")
    source = _source(manifest, profile)
    html = html5lib.parse(source, treebuilder="etree", namespaceHTMLElements=False)
    body = html.find("body")
    if body is None or len(body) != 3 or [child.tag for child in body] != ["header", "div", "footer"]:
        raise ValueError("Bede provider wrapper differs from the declared source")
    literary = body[1]
    if "tei-text" not in _classes(literary) or [child.tag for child in literary] != ["div", "div", "hr", "div"]:
        raise ValueError("Bede literary front/body/back envelope differs")
    root = tei_el("TEI", {"xml:lang": "en"})
    root.append(stamp_header(
        title="Bede's Ecclesiastical History of England",
        author="Bede",
        contributors=[{"name": "A. M. Sellar", "role": "revised translation, introduction, life, and notes"}],
        source_url="https://www.gutenberg.org/ebooks/38326",
        source_sha256=_sha(source),
        print_source="Retained electronic title page: London, George Bell and Sons, 1907. Continuation attribution unresolved; footnote 1056 says later hand.",
    ))
    text = tei_el("text")
    for source_part, tag in ((literary[0], "front"), (literary[1], "body"), (literary[3], "back")):
        if f"tei-{tag}" not in _classes(source_part):
            raise ValueError(f"Bede {tag} source class differs")
        part = tei_el(tag)
        part.text = source_part.text
        for child in source_part:
            _copy(child, part)
            part[-1].tail = child.tail
        if tag == "body":
            _copy(literary[2], part)
            part[-1].tail = literary[2].tail
        text.append(part)
    root.append(text)
    candidate = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    account = {
        "contract": "ocd-bede-gutenberg-accountability-v1",
        "work_id": profile["work_id"], "edition_id": profile["edition_id"],
        "acquisition_id": profile["acquisition_id"],
        "source_sha256": _sha(source), "source_archive_sha256": profile["source_archive"]["sha256"],
        "candidate_sha256": _sha(candidate),
        "selection": profile["selection"],
        "source_members": profile["source_archive"]["members"],
        "provider_header_and_footer": "retained and hash-bound; excluded from literary TEI",
        "head_and_css": "retained and hash-bound; excluded from literary TEI",
        "cover_image": "retained support member; no body image occurrence",
        "literary_parts": ["front", "body", "back"],
        "continuation": "retained after Book V in source order; attribution unresolved",
        "footnote_count": profile["expected_footnotes"],
        "printed_page_marker_count": profile["expected_page_markers"],
    }
    return {
        "README.source.md": manifest.authority_path("source-readme").read_bytes(),
        "content.tei.xml": candidate,
        "source-accountability.json": _encoded(account),
        "provenance.json": _encoded(policy["provenance"]),
        "unresolved.jsonl": b"".join(_encoded(item) for item in policy["unresolved"]),
    }


_convert.converter_id = "ocd-bede-gutenberg-38326-html-to-tei"
_convert.converter_version = "1"
_convert.implementation_path = Path(__file__).resolve()
