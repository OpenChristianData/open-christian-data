"""Independent source-bound oracle for the LIB-083 Schleitheim candidate."""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-schleitheim-confession-independent-oracle"
ORACLE_VERSION = "1"
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


def _strict(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _normalized(parts: list[str] | str) -> str:
    value = "".join(parts) if isinstance(parts, list) else parts
    return re.sub(r"\s+", " ", value).strip()


class _IndependentSourceParser(HTMLParser):
    """Inventory the retained carrier without the producer's DOM traversal."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_wrapper = False
        self.wrapper_div_depth = 0
        self.capture: str | None = None
        self.buffer: list[str] = []
        self.line_buffer: list[str] = []
        self.lines: list[str] = []
        self.preface_paragraphs: list[str] = []
        self.title = ""
        self.imprint_lines: list[str] = []
        self.contents: list[str] = []
        self.articles: list[dict[str, object]] = []
        self.article_buffer: list[str] = []
        self.closing_lines: list[str] = []
        self.work_terminal_seen = False

    def _flush_line(self) -> None:
        value = _normalized(self.line_buffer)
        if value:
            self.lines.append(value)
        self.line_buffer.clear()

    def _flush_article_paragraph(self) -> None:
        if not self.articles:
            self.article_buffer.clear()
            return
        value = _normalized(self.article_buffer)
        if value:
            self.articles[-1]["paragraphs"].append(value)
        self.article_buffer.clear()

    def _flush_preface_paragraph(self) -> None:
        value = _normalized(self.buffer)
        if value:
            self.preface_paragraphs.append(value)
        self.buffer.clear()

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = {key.casefold(): value for key, value in attrs}
        tag = tag.casefold()
        if not self.in_wrapper:
            if tag == "div" and attributes.get("id") == "wrapper-light":
                self.in_wrapper = True
                self.wrapper_div_depth = 1
            return
        if tag == "div":
            self.wrapper_div_depth += 1
            if attributes.get("style", "").replace(" ", "").casefold() == "margin-left:50px":
                self._flush_article_paragraph()
                self.capture = "closing"
                self.lines = []
                self.line_buffer = []
            return
        if self.capture == "closing":
            if tag == "br":
                self._flush_line()
            return
        if tag == "h1" and not self.articles:
            self.capture = "title"
            self.buffer = []
        elif tag == "center" and not self.articles:
            self.capture = "imprint"
            self.lines = []
            self.line_buffer = []
        elif tag == "p" and not self.work_terminal_seen:
            if self.articles:
                self._flush_article_paragraph()
            else:
                self._flush_preface_paragraph()
                self.capture = "preface-p"
        elif tag == "ol" and not self.articles:
            self._flush_preface_paragraph()
            self.capture = "contents"
        elif tag == "li" and self.capture == "contents":
            value = _normalized(self.buffer)
            if value:
                self.contents.append(value)
            self.buffer = []
        elif tag == "font" and attributes.get("color", "").casefold() == "#008000":
            self._flush_article_paragraph()
            self.capture = "article-heading"
            self.buffer = []
        elif tag == "br" and self.capture in {"imprint", "preface-p"}:
            self._flush_line()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if not self.in_wrapper:
            return
        if tag == "div":
            if self.capture == "closing" and self.wrapper_div_depth == 2:
                self._flush_line()
                self.closing_lines = list(self.lines)
                self.work_terminal_seen = True
                self.capture = None
            self.wrapper_div_depth -= 1
            if self.wrapper_div_depth == 0:
                self._flush_article_paragraph()
                self.in_wrapper = False
            return
        if self.capture == "closing":
            return
        if tag == "h1" and self.capture == "title":
            self.title = _normalized(self.buffer)
            self.capture = None
            self.buffer = []
        elif tag == "center" and self.capture == "imprint":
            self._flush_line()
            self.imprint_lines = list(self.lines)
            self.capture = None
        elif tag == "li" and self.capture == "contents":
            value = _normalized(self.buffer)
            if value:
                self.contents.append(value)
            self.buffer = []
        elif tag == "ol" and self.capture == "contents":
            value = _normalized(self.buffer)
            if value:
                self.contents.append(value)
            self.buffer = []
            self.capture = None
        elif tag == "font" and self.capture == "article-heading":
            heading = _normalized(self.buffer)
            match = _ARTICLE_RE.match(heading)
            if match is None:
                raise ValueError("Schleitheim article heading drifted")
            self.articles.append(
                {
                    "number": match.group(1).upper(),
                    "title": _normalized(match.group(2).rstrip(":")),
                    "paragraphs": [],
                }
            )
            self.capture = None
            self.buffer = []

    def handle_data(self, data: str) -> None:
        if not self.in_wrapper:
            return
        if self.capture in {"imprint", "closing"}:
            self.line_buffer.append(data)
        elif self.capture == "preface-p" and not self.articles:
            self.buffer.append(data)
        elif self.capture in {"title", "contents", "article-heading"}:
            self.buffer.append(data)
        elif self.articles and not self.work_terminal_seen and self.capture != "closing":
            self.article_buffer.append(data)


def _source_segments(source: bytes) -> list[dict[str, object]]:
    prefix, title_marker, after_title = source.partition(
        b"<h1>The Schleitheim Confession</h1>"
    )
    if not title_marker:
        raise ValueError("Schleitheim title boundary is missing")
    preface_tail, article_marker, after_article = after_title.partition(b"<font color=")
    if not article_marker:
        raise ValueError("Schleitheim Article I boundary is missing")
    article_tail, closing_marker, after_closing_start = after_article.partition(b"<div style=")
    if not closing_marker:
        raise ValueError("Schleitheim closing boundary is missing")
    closing_body, closing_end, after_closing = after_closing_start.partition(b"</div>")
    wrapper_tail, wrapper_end_start, suffix_start = after_closing.partition(b"</div id=")
    wrapper_end_tail, wrapper_end, suffix = suffix_start.partition(b">")
    if not closing_end or not wrapper_end_start or not wrapper_end:
        raise ValueError("Schleitheim outer wrapper boundary is missing")
    values = (
        ("page-prefix", prefix, "excluded-site-container"),
        (
            "work-preface",
            title_marker + preface_tail,
            "represented",
        ),
        (
            "articles-and-closing-imprint",
            article_marker + article_tail + closing_marker + closing_body + closing_end,
            "represented",
        ),
        (
            "post-terminal-wrapper",
            wrapper_tail + wrapper_end_start + wrapper_end_tail + wrapper_end,
            "accounted-source-context",
        ),
        ("page-suffix", suffix, "excluded-site-chrome"),
    )
    if b"typed by Dick Sullivan" not in values[3][1] or b"History Index" not in values[3][1]:
        raise ValueError("Schleitheim post-terminal context drifted")
    if sum(len(content) for _, content, _ in values) != len(source):
        raise ValueError("Schleitheim source segment accounting drifted")
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
    parser = _IndependentSourceParser()
    parser.feed(source.decode("utf-8", errors="strict"))
    parser.close()
    if parser.title != "The Schleitheim Confession":
        raise ValueError("Schleitheim retained title drifted")
    if parser.imprint_lines != [
        "printed by Rod and Staff Publishers, Inc., Crockett, KY",
        "Sixth Printing, 1985",
    ]:
        raise ValueError("Schleitheim publication imprint drifted")
    if parser.preface_paragraphs[:2] != [
        "Adopted by a Swiss Brethren Conference, February 24, 1527 Brotherly Union of a Number of Children of God concerning Seven Articles",
        "The articles which we discussed and on which we were of one mind are these:",
    ]:
        raise ValueError("Schleitheim adoption or introduction drifted")
    if parser.contents != list(_CONTENT_ITEMS):
        raise ValueError("Schleitheim contents list drifted")
    if [item["number"] for item in parser.articles] != list(_ARTICLE_ORDER):
        raise ValueError("Schleitheim article census drifted")
    if parser.closing_lines != list(_CLOSING_LINES):
        raise ValueError("Schleitheim closing imprint drifted")
    return {
        "preface": {
            "title": parser.title,
            "imprint_lines": parser.imprint_lines,
            "adoption_lines": [
                "Adopted by a Swiss Brethren Conference, February 24, 1527",
                "Brotherly Union of a Number of Children of God concerning Seven Articles",
            ],
            "introduction": parser.preface_paragraphs[1],
            "contents": parser.contents,
            "disposition": "represented",
        },
        "articles": parser.articles,
        "closing_imprint": {
            "lines": parser.closing_lines,
            "word_count": sum(len(line.split()) for line in parser.closing_lines),
            "disposition": "represented",
        },
        "source_segments": _source_segments(source),
    }


def _authority(manifest: SourceManifest, name: str) -> Mapping[str, object]:
    for item in manifest.record.get("authorities", ()):
        if isinstance(item, Mapping) and item.get("name") == name:
            return item
    raise ValueError(f"Schleitheim authority {name!r} is missing")


def _expected_accountability(
    manifest: SourceManifest, source: bytes, model: dict[str, object]
) -> dict[str, object]:
    articles = model["articles"]
    article_word_count = sum(
        len(str(value).split()) for item in articles for value in item["paragraphs"]
    )
    closing = model["closing_imprint"]
    return {
        "contract": "ocd-schleitheim-confession-source-accountability-v1",
        "schema": "sources/doctrinal-documents/schleitheim-confession-1527/schleitheim-confession-1527.source-accountability.schema.json",
        "profile_id": "schleitheim-confession-retained-html-v1",
        "work_id": "schleitheim-confession-1527",
        "source_id": manifest.record["source_id"],
        "source_bytes": len(source),
        "source_sha256": _sha(source),
        "source_segments": model["source_segments"],
        "preface": model["preface"],
        "article_count": len(articles),
        "paragraph_count": sum(len(item["paragraphs"]) for item in articles),
        "article_word_count": article_word_count,
        "closing_imprint": closing,
        "work_word_count": article_word_count + closing["word_count"],
        "articles": [
            {
                "number": item["number"],
                "title": item["title"],
                "paragraph_count": len(item["paragraphs"]),
                "word_count": sum(len(str(value).split()) for value in item["paragraphs"]),
                "paragraph_sha256": _sha(_canonical(item["paragraphs"])),
                "disposition": "represented",
            }
            for item in articles
        ],
        "omitted_count": 0,
        "duplicate_count": 0,
        "unresolved_count": 3,
    }


def _verify_line_carrier(node: etree._Element, lines: list[str], label: str) -> None:
    if node.text != lines[0] or len(node) != len(lines) - 1:
        raise ValueError(f"Schleitheim {label} line structure drifted")
    for child, line in zip(node, lines[1:], strict=True):
        if child.tag != f"{{{_TEI}}}lb" or child.attrib or child.text is not None or child.tail != " " + line:
            raise ValueError(f"Schleitheim {label} line structure drifted")


def _verify_tei(
    candidate: CandidatePackage, model: dict[str, object], title: str
) -> None:
    articles = model["articles"]
    try:
        root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    except etree.XMLSyntaxError as exc:
        raise ValueError("Schleitheim TEI XML is not well-formed") from exc
    if root.get(_XML_ID) != "schleitheim-confession-1527-candidate":
        raise ValueError("Schleitheim TEI root identity drift")
    titles = root.xpath(
        "/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces={"t": _TEI}
    )
    if len(titles) != 1 or titles[0].text != title:
        raise ValueError("Schleitheim TEI title identity drift")
    body_nodes = root.xpath("/t:TEI/t:text/t:body", namespaces={"t": _TEI})
    if len(body_nodes) != 1:
        raise ValueError("Schleitheim TEI body topology drift")
    body = body_nodes[0]
    if [node.get("type") for node in body] != [
        "preface",
        "article",
        "article",
        "article",
        "article",
        "article",
        "article",
        "article",
        "closing-imprint",
    ] or any(node.tag != f"{{{_TEI}}}div" for node in body):
        raise ValueError("Schleitheim TEI body topology drift")
    preface = body[0]
    if preface.attrib != {"type": "preface", _XML_ID: "schleitheim-preface"}:
        raise ValueError("Schleitheim preface identity drift")
    if [node.tag for node in preface] != [
        f"{{{_TEI}}}head",
        f"{{{_TEI}}}p",
        f"{{{_TEI}}}p",
        f"{{{_TEI}}}p",
        f"{{{_TEI}}}list",
    ]:
        raise ValueError("Schleitheim preface topology drift")
    expected_preface = model["preface"]
    if preface[0].attrib or preface[0].text != expected_preface["title"]:
        raise ValueError("Schleitheim preface title drift")
    if preface[1].attrib != {"rend": "imprint"}:
        raise ValueError("Schleitheim publication imprint identity drift")
    _verify_line_carrier(preface[1], expected_preface["imprint_lines"], "publication imprint")
    if preface[2].attrib != {"rend": "adoption"}:
        raise ValueError("Schleitheim adoption identity drift")
    _verify_line_carrier(preface[2], expected_preface["adoption_lines"], "adoption")
    if preface[3].attrib != {"rend": "introduction"} or len(preface[3]) or preface[3].text != expected_preface["introduction"]:
        raise ValueError("Schleitheim introduction drift")
    contents = preface[4]
    if contents.attrib != {"type": "contents"} or len(contents) != len(_ARTICLE_ORDER):
        raise ValueError("Schleitheim contents topology drift")
    for number, value, item in zip(
        _ARTICLE_ORDER, expected_preface["contents"], contents, strict=True
    ):
        if item.tag != f"{{{_TEI}}}item" or item.attrib != {"n": number} or len(item) or item.text != value:
            raise ValueError("Schleitheim contents text or order drift")
    article_nodes = root.xpath("/t:TEI/t:text/t:body/t:div[@type='article']", namespaces={"t": _TEI})
    if len(article_nodes) != len(articles):
        raise ValueError("Schleitheim article omission or duplication")
    for ordinal, (expected, node) in enumerate(zip(articles, article_nodes), 1):
        if (
            node.get("n") != expected["number"]
            or node.get(_XML_ID) != f"schleitheim-article-{ordinal}"
            or set(node.attrib) != {"type", "n", _XML_ID}
        ):
            raise ValueError("Schleitheim article order or identity drift")
        heads = node.xpath("./t:head", namespaces={"t": _TEI})
        paragraphs = node.xpath("./t:p", namespaces={"t": _TEI})
        if len(heads) != 1 or heads[0].text != expected["title"] or len(paragraphs) != len(expected["paragraphs"]):
            raise ValueError("Schleitheim heading or paragraph count drift")
        for number, (value, paragraph) in enumerate(zip(expected["paragraphs"], paragraphs), 1):
            if (
                paragraph.get("n") != str(number)
                or paragraph.get(_XML_ID) != f"schleitheim-article-{ordinal}-p-{number}"
                or set(paragraph.attrib) != {"n", _XML_ID}
                or paragraph.text != value
            ):
                raise ValueError("Schleitheim paragraph text or order drift")
    closing = body[-1]
    if closing.attrib != {
        "type": "closing-imprint",
        _XML_ID: "schleitheim-closing-imprint",
    } or len(closing) != 1:
        raise ValueError("Schleitheim closing imprint topology drift")
    if closing[0].tag != f"{{{_TEI}}}p" or closing[0].attrib != {"rend": "imprint"}:
        raise ValueError("Schleitheim closing imprint identity drift")
    _verify_line_carrier(
        closing[0], model["closing_imprint"]["lines"], "closing imprint"
    )


def _closure(root: Path) -> str:
    paths = {
        Path(__file__).resolve(strict=True),
        (root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True),
        (root / "ocd_kernel/reconstruction/__init__.py").resolve(strict=True),
    }
    records = [{"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())} for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix())]
    return _sha(_canonical(records))


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    if source_manifest.record.get("ticket_id") != "LIB-083" or source_manifest.record.get("work_id") != "schleitheim-confession-1527":
        raise ValueError("Schleitheim source identity drift")
    converter = source_manifest.record.get("converter")
    validator = source_manifest.record.get("validator")
    if not isinstance(converter, Mapping) or not isinstance(validator, Mapping):
        raise ValueError("Schleitheim callable bindings are invalid")
    manifest_path = source_manifest.path.relative_to(source_manifest.repository_root).as_posix()
    if candidate.manifest.get("status") != "nonaccepted" or candidate.manifest.get("source_manifest") != {"path": manifest_path, "sha256": source_manifest.sha256} or candidate.manifest.get("converter") != dict(converter) or candidate.manifest.get("package_schema") != dict(source_manifest.record["package_schema"]):
        raise ValueError("Schleitheim candidate binding drift")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict(profile_bytes, "Schleitheim profile")
    policy = _strict(policy_bytes, "Schleitheim policy")
    if profile.get("profile_id") != "schleitheim-confession-retained-html-v1" or policy.get("policy_id") != "schleitheim-confession-retained-html-policy-v1" or policy.get("oracle_id") != ORACLE_ID:
        raise ValueError("Schleitheim profile or policy drift")
    source = source_manifest.authority_path("retained-html").read_bytes()
    if len(source) != _SOURCE_BYTES or _sha(source) != _SOURCE_SHA256:
        raise ValueError("Schleitheim retained HTML drift")
    model = _source_model(source)
    expected_counts = {
        "articles": 7,
        "article_words": 2341,
        "closing_imprint_words": 11,
        "work_words": 2352,
        "contents_items": 7,
        "source_segments": 5,
        "omitted": 0,
        "duplicate": 0,
        "unresolved": 3,
    }
    if policy.get("required_counts") != expected_counts:
        raise ValueError("Schleitheim validation census policy drift")
    expected = _expected_accountability(source_manifest, source, model)
    accountability_bytes = candidate.member_bytes("source-accountability.json")
    accountability = _strict(accountability_bytes, "Schleitheim accountability")
    if accountability != expected or accountability_bytes != _canonical(expected):
        raise ValueError("Schleitheim source accountability drift")
    schema = _strict(source_manifest.authority_path("source-accountability-schema").read_bytes(), "Schleitheim accountability schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"Schleitheim accountability schema failure: {errors[0].message}")
    _verify_tei(candidate, model, str(profile["identity"]["title"]))
    xsd = etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd"))))
    if not xsd.validate(etree.fromstring(candidate.member_bytes("content.tei.xml"))):
        raise ValueError(f"Schleitheim TEI schema failure: {xsd.error_log}")
    provenance = _strict(candidate.member_bytes("provenance.json"), "Schleitheim provenance")
    if provenance.get("contract") != "ocd-schleitheim-confession-candidate-provenance-v1" or provenance.get("status") != "nonaccepted" or provenance.get("ticket_id") != "LIB-083" or provenance.get("work_id") != "schleitheim-confession-1527" or provenance.get("source_id") != source_manifest.record.get("source_id") or provenance.get("source_manifest_sha256") != source_manifest.sha256 or provenance.get("identity") != profile.get("identity") or provenance.get("rights") != profile.get("rights") or provenance.get("candidate_boundary") != {"acceptance_status": "nonaccepted", "publication_status": "not-authorized", "canonical_data_or_ir_written": False}:
        raise ValueError("Schleitheim provenance or metadata drift")
    required = ["schleitheim-confession-identity-review", "schleitheim-confession-rights-review", "schleitheim-confession-human-acceptance"]
    unresolved = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").splitlines() if line.strip()]
    if [item.get("id") for item in unresolved] != required or any(item.get("status") != "unresolved" for item in unresolved):
        raise ValueError("Schleitheim unresolved ledger drift")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-attribution-readme").read_bytes():
        raise ValueError("Schleitheim attribution evidence drift")
    closure = _closure(source_manifest.repository_root)
    if closure != validator.get("import_closure_sha256"):
        raise ValueError("Schleitheim oracle import closure drift")
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": closure,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": _sha(source),
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
