"""Deterministic retained HTML to TEI candidate route for LIB-083."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree, html as lxml_html

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-schleitheim-confession-html-to-tei"
CONVERTER_VERSION = "1"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_SOURCE_SHA256 = "5a7f3b112e2bd074c9eb8626fd58d13086870ebb0be52a3036781ce9077f3750"
_SOURCE_BYTES = 21064
_ARTICLE_RE = re.compile(r"^([IVXLCDM]+)\.\s+(.*?)[\s:]*$", re.DOTALL | re.IGNORECASE)
_ARTICLE_ORDER = ("I", "II", "III", "IV", "V", "VI", "VII")
_CONTENT_ITEMS = (
    "Baptism;",
    "The Ban (Excommunication);",
    "Breaking of Bread;",
    "Separation from the Abomination;",
    "Pastors in the Church;",
    "The Sword;",
    "The Oath.",
)
_CLOSING_LINES = (
    "The Seven Articles of Schleitheim",
    "Canton Schaffhausen, Switzerland,",
    "February 24, 1527",
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def load_manifest(path: str | Path, *, repository_root: str | Path) -> SourceManifest:
    return SourceManifest.load(path, repository_root=repository_root)


def _strict(path: Path, label: str) -> dict[str, object]:
    value = json.loads(path.read_bytes().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _lines(node: etree._Element) -> list[str]:
    lines: list[str] = []
    current: list[str] = []

    def add(value: str | None) -> None:
        if value:
            current.append(value)

    def flush() -> None:
        value = _normalized("".join(current))
        if value:
            lines.append(value)
        current.clear()

    def visit(element: etree._Element) -> None:
        add(element.text)
        for child in element:
            if str(child.tag).casefold() == "br":
                flush()
            else:
                visit(child)
            add(child.tail)

    visit(node)
    flush()
    return lines


def _source_segments(source: bytes) -> list[dict[str, object]]:
    title_start = source.index(b"<h1>The Schleitheim Confession</h1>")
    article_start = source.index(b"<font color=", title_start)
    closing_start = source.index(b"<div style=", article_start)
    closing_end = source.index(b"</div>", closing_start) + len(b"</div>")
    wrapper_end_start = source.index(b"</div id=", closing_end)
    wrapper_end = source.index(b">", wrapper_end_start) + 1
    values = (
        ("page-prefix", source[:title_start], "excluded-site-container"),
        ("work-preface", source[title_start:article_start], "represented"),
        (
            "articles-and-closing-imprint",
            source[article_start:closing_end],
            "represented",
        ),
        (
            "post-terminal-wrapper",
            source[closing_end:wrapper_end],
            "accounted-source-context",
        ),
        ("page-suffix", source[wrapper_end:], "excluded-site-chrome"),
    )
    if b"typed by Dick Sullivan" not in values[3][1] or b"History Index" not in values[3][1]:
        raise ValueError("Schleitheim post-terminal source context drifted")
    if sum(len(content) for _, content, _ in values) != len(source):
        raise ValueError("Schleitheim retained HTML segment accounting drifted")
    return [
        {
            "id": name,
            "bytes": len(content),
            "sha256": _sha(content),
            "disposition": disposition,
        }
        for name, content, disposition in values
    ]


def _source_model(source: bytes) -> dict[str, object]:
    document = lxml_html.fromstring(source)
    try:
        wrapper = document.get_element_by_id("wrapper-light")
    except KeyError as exc:
        raise ValueError("Schleitheim work wrapper is missing") from exc
    children = list(wrapper)
    if [str(node.tag).casefold() for node in children[:5]] != [
        "h1",
        "center",
        "p",
        "p",
        "ol",
    ]:
        raise ValueError("Schleitheim prefatory carrier order drifted")
    preface = {
        "title": _normalized(children[0].text_content()),
        "imprint_lines": _lines(children[1]),
        "adoption_lines": _lines(children[2]),
        "introduction": _normalized(children[3].text_content()),
        "contents": [_normalized(item.text_content()) for item in children[4]],
        "disposition": "represented",
    }
    if preface != {
        "title": "The Schleitheim Confession",
        "imprint_lines": [
            "printed by Rod and Staff Publishers, Inc., Crockett, KY",
            "Sixth Printing, 1985",
        ],
        "adoption_lines": [
            "Adopted by a Swiss Brethren Conference, February 24, 1527",
            "Brotherly Union of a Number of Children of God concerning Seven Articles",
        ],
        "introduction": "The articles which we discussed and on which we were of one mind are these:",
        "contents": list(_CONTENT_ITEMS),
        "disposition": "represented",
    }:
        raise ValueError("Schleitheim prefatory text or contents drifted")

    result: list[dict[str, object]] = []
    closing_lines: list[str] | None = None
    for node in children[5:]:
        text = _normalized(node.text_content())
        if str(node.tag).casefold() == "div" and text.startswith(_CLOSING_LINES[0]):
            closing_lines = _lines(node)
            break
        heading = node if str(node.tag).casefold() == "font" else None
        if str(node.tag).casefold() == "p" and len(node) and str(node[0].tag).casefold() == "font":
            heading = node[0]
        if heading is None:
            if str(node.tag).casefold() == "p" and result and text:
                result[-1]["paragraphs"].append(text)
            continue
        heading_text = _normalized(heading.text_content())
        match = _ARTICLE_RE.match(heading_text)
        if match is None:
            raise ValueError("Schleitheim article heading drifted")
        number = match.group(1).upper()
        title = _normalized(match.group(2).rstrip(":"))
        body = _normalized(heading.tail or "") if heading is node else _normalized(text[len(heading_text) :])
        result.append(
            {"number": number, "title": title, "paragraphs": [body] if body else []}
        )
    if [item["number"] for item in result] != list(_ARTICLE_ORDER):
        raise ValueError("Schleitheim article census drifted")
    if closing_lines != list(_CLOSING_LINES):
        raise ValueError("Schleitheim closing imprint drifted")
    return {
        "preface": preface,
        "articles": result,
        "closing_imprint": {
            "lines": closing_lines,
            "word_count": sum(len(line.split()) for line in closing_lines),
            "disposition": "represented",
        },
        "source_segments": _source_segments(source),
    }


def _append_lines(node: etree._Element, lines: list[str]) -> None:
    if not lines:
        raise ValueError("Schleitheim line carrier is empty")
    node.text = lines[0]
    for line in lines[1:]:
        etree.SubElement(node, f"{{{_TEI}}}lb").tail = " " + line


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = _strict(source_manifest.authority_path("reconstruction-profile"), "Schleitheim profile")
    policy = _strict(source_manifest.authority_path("validation-policy"), "Schleitheim policy")
    if profile.get("profile_id") != "schleitheim-confession-retained-html-v1" or policy.get("policy_id") != "schleitheim-confession-retained-html-policy-v1":
        raise ValueError("Schleitheim profile or policy identity drifted")
    source_path = source_manifest.authority_path("retained-html")
    source = source_path.read_bytes()
    if len(source) != _SOURCE_BYTES or _sha(source) != _SOURCE_SHA256:
        raise ValueError("Schleitheim retained HTML bytes drifted")
    model = _source_model(source)
    articles = model["articles"]
    article_words = sum(len(str(p).split()) for item in articles for p in item["paragraphs"])
    closing = model["closing_imprint"]
    if article_words != 2341 or closing["word_count"] != 11 or article_words + closing["word_count"] != 2352:
        raise ValueError("Schleitheim word census drifted")
    root = etree.Element(f"{{{_TEI}}}TEI", nsmap={None: _TEI})
    root.set(_XML_ID, "schleitheim-confession-1527-candidate")
    header = etree.SubElement(root, f"{{{_TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{_TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{_TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{_TEI}}}title").text = str(profile["identity"]["title"])
    etree.SubElement(title_stmt, f"{{{_TEI}}}author").text = "Swiss Brethren"
    publication = etree.SubElement(file_desc, f"{{{_TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{_TEI}}}publisher").text = "Open Christian Data"
    availability = etree.SubElement(publication, f"{{{_TEI}}}availability", status="restricted")
    etree.SubElement(availability, f"{{{_TEI}}}p").text = "Nonaccepted candidate; publication is not authorized."
    source_desc = etree.SubElement(file_desc, f"{{{_TEI}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{_TEI}}}bibl")
    etree.SubElement(bibl, f"{{{_TEI}}}title").text = "The Schleitheim Confession"
    etree.SubElement(bibl, f"{{{_TEI}}}ptr", target="https://www.anabaptists.org/history/the-schleitheim-confession.html")
    etree.SubElement(bibl, f"{{{_TEI}}}idno", type="sha256").text = _SOURCE_SHA256
    encoding = etree.SubElement(header, f"{{{_TEI}}}encodingDesc")
    etree.SubElement(encoding, f"{{{_TEI}}}p").text = "The complete work-bearing preface, seven article bodies, and closing imprint are represented in source order. All retained page bytes have explicit source-local dispositions; no modernized wording is supplied."
    revision = etree.SubElement(header, f"{{{_TEI}}}revisionDesc", status="candidate")
    etree.SubElement(revision, f"{{{_TEI}}}change", when="2026-08-30").text = "Generated as a nonaccepted review candidate."
    text = etree.SubElement(root, f"{{{_TEI}}}text")
    text.set(_XML_ID, "schleitheim-confession-1527-text")
    body = etree.SubElement(text, f"{{{_TEI}}}body")
    preface = model["preface"]
    preface_node = etree.SubElement(body, f"{{{_TEI}}}div", type="preface")
    preface_node.set(_XML_ID, "schleitheim-preface")
    etree.SubElement(preface_node, f"{{{_TEI}}}head").text = str(preface["title"])
    imprint = etree.SubElement(preface_node, f"{{{_TEI}}}p", rend="imprint")
    _append_lines(imprint, list(preface["imprint_lines"]))
    adoption = etree.SubElement(preface_node, f"{{{_TEI}}}p", rend="adoption")
    _append_lines(adoption, list(preface["adoption_lines"]))
    etree.SubElement(preface_node, f"{{{_TEI}}}p", rend="introduction").text = str(preface["introduction"])
    contents = etree.SubElement(preface_node, f"{{{_TEI}}}list", type="contents")
    for number, value in zip(_ARTICLE_ORDER, preface["contents"], strict=True):
        etree.SubElement(contents, f"{{{_TEI}}}item", n=number).text = str(value)
    for ordinal, article in enumerate(articles, 1):
        number = str(article["number"])
        article_node = etree.SubElement(body, f"{{{_TEI}}}div", type="article", n=number)
        article_node.set(_XML_ID, f"schleitheim-article-{ordinal}")
        etree.SubElement(article_node, f"{{{_TEI}}}head").text = str(article["title"])
        for paragraph_number, paragraph in enumerate(article["paragraphs"], 1):
            node = etree.SubElement(article_node, f"{{{_TEI}}}p", n=str(paragraph_number))
            node.set(_XML_ID, f"schleitheim-article-{ordinal}-p-{paragraph_number}")
            node.text = str(paragraph)
    closing_node = etree.SubElement(body, f"{{{_TEI}}}div", type="closing-imprint")
    closing_node.set(_XML_ID, "schleitheim-closing-imprint")
    closing_text = etree.SubElement(closing_node, f"{{{_TEI}}}p", rend="imprint")
    _append_lines(closing_text, list(closing["lines"]))
    accountability = {
        "contract": "ocd-schleitheim-confession-source-accountability-v1",
        "schema": "sources/doctrinal-documents/schleitheim-confession-1527/schleitheim-confession-1527.source-accountability.schema.json",
        "profile_id": "schleitheim-confession-retained-html-v1",
        "work_id": "schleitheim-confession-1527",
        "source_id": source_manifest.record["source_id"],
        "source_bytes": len(source),
        "source_sha256": _sha(source),
        "source_segments": model["source_segments"],
        "preface": preface,
        "article_count": len(articles),
        "paragraph_count": sum(len(article["paragraphs"]) for article in articles),
        "article_word_count": article_words,
        "closing_imprint": closing,
        "work_word_count": article_words + closing["word_count"],
        "articles": [
            {
                "number": item["number"],
                "title": item["title"],
                "paragraph_count": len(item["paragraphs"]),
                "word_count": sum(len(str(p).split()) for p in item["paragraphs"]),
                "paragraph_sha256": _sha(_canonical(item["paragraphs"])),
                "disposition": "represented",
            }
            for item in articles
        ],
        "omitted_count": 0,
        "duplicate_count": 0,
        "unresolved_count": 3,
    }
    authorities = {str(item["name"]): {key: item[key] for key in ("path", "bytes", "sha256", "role")} for item in source_manifest.record["authorities"]}
    provenance = {
        "contract": "ocd-schleitheim-confession-candidate-provenance-v1",
        "status": "nonaccepted",
        "ticket_id": "LIB-083",
        "work_id": "schleitheim-confession-1527",
        "source_id": source_manifest.record["source_id"],
        "source_manifest_sha256": source_manifest.sha256,
        "identity": profile["identity"],
        "source": {"path": "raw/anabaptists.org/schleitheim-confession-1527.html", "bytes": _SOURCE_BYTES, "sha256": _SOURCE_SHA256},
        "authorities": authorities,
        "rights": profile["rights"],
        "candidate_boundary": {"acceptance_status": "nonaccepted", "publication_status": "not-authorized", "canonical_data_or_ir_written": False},
    }
    unresolved = (
        {"id": "schleitheim-confession-identity-review", "status": "unresolved", "kind": "identity", "detail": "Human review is required for edition and translation identity."},
        {"id": "schleitheim-confession-rights-review", "status": "unresolved", "kind": "rights", "detail": "Human rights review is required before acceptance or publication."},
        {"id": "schleitheim-confession-human-acceptance", "status": "unresolved", "kind": "acceptance", "detail": "This candidate has not received human textual acceptance."},
    )
    return {
        "content.tei.xml": etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(row) for row in unresolved),
        "README.source.md": source_manifest.authority_path("source-attribution-readme").read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
