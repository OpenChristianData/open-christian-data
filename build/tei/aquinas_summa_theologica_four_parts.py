"""Convert four retained Project Gutenberg Summa components to TEI P5.

This route is intentionally source-specific.  It binds the four corrected
English Dominican Province HTML witnesses released in ticket 09, excludes only
Project Gutenberg redistribution wrappers, and projects every retained
content unit exactly once.  Source markup anomalies remain literal in the TEI
text and are reported separately from the conservative semantic hierarchy.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
from typing import Iterable, Mapping, Sequence
from zipfile import BadZipFile, ZipFile

if __package__ in {None, ""}:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree, html

from ocd_kernel.lib.storage_topology import resolve_repo_path


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
NS = {"t": TEI_NS}

RAW_LOGICAL_ROOT = (
    "raw/clean-ready-acquisition-to-tei/master-1/09/"
    "aquinas-summa-theologica-four-parts"
)
REPORT_LOGICAL_ROOT = (
    "reports/clean-ready-acquisition-to-tei/master-1/09/"
    "aquinas-summa-theologica-four-parts"
)
TEI_RNG_PATH = (
    Path(__file__).resolve().parents[2]
    / "ocd_kernel"
    / "tei"
    / "vendor"
    / "relaxng"
    / "tei_all.rng"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class ConversionError(ValueError):
    """Raised when retained source identity or faithful projection changes."""


@dataclass(frozen=True)
class ComponentSpec:
    order: int
    pg_id: int
    code: str
    title: str
    part_label: str
    archive_sha256: str
    html_sha256: str
    cover_sha256: str
    expected_units: int
    expected_paragraphs: int
    expected_headings: int
    expected_italics: int
    expected_line_breaks: int
    expected_article_markers: int
    expected_semantic_articles: int
    expected_questions: int
    expected_question_heading_gaps: tuple[int, ...]
    main_start_id: str
    terminal_question: int
    terminal_article: int
    terminal_source_id: str
    terminal_text: str
    source_text_sha256: str

    @property
    def archive_name(self) -> str:
        return f"pg{self.pg_id}-h.zip"

    @property
    def html_member(self) -> str:
        return f"pg{self.pg_id}-images.html"

    @property
    def cover_member(self) -> str:
        return f"{self.pg_id}-cover.png"

    @property
    def source_url(self) -> str:
        return (
            f"https://www.gutenberg.org/cache/epub/{self.pg_id}/"
            f"{self.html_member}"
        )


COMPONENTS: tuple[ComponentSpec, ...] = (
    ComponentSpec(
        1,
        17611,
        "prima-pars",
        "Summa Theologica, Part I (Prima Pars)",
        'PART I ("Prima Pars")',
        "b6be70214af36764dad9b853df29cf4d62bff3ef25d8241551f78e9b27936c90",
        "48421f1cb257f450c16844168f5cbb5f328b7825a9387ef670b81b53c3403195",
        "0bc69c6d6e7d52bf7e2c485b21bfae3be427941f2edf682e057197555508b337",
        7861,
        7724,
        137,
        1628,
        627,
        582,
        584,
        119,
        (116,),
        "id00042",
        119,
        2,
        "id07860",
        "WHO IS ABOVE ALL GOD FOR EVER BLESSED. Amen.",
        "5c10e2866fa6325f81454fd2e7887525001a388d092966ef874534339e36656a",
    ),
    ComponentSpec(
        2,
        17897,
        "prima-secundae",
        "Summa Theologica, Part I-II (Pars Prima Secundae)",
        'PART I-II ("Prima Secundae")',
        "7b2a630f7231148ae18cba649b3c444aee8eab1bbc08b6be04ab39cabe0fd0c6",
        "669cecdd59450d256650be9d6af3f2577926af19276f16eef80e4b986bb8fc93",
        "505dfd73997b1d48adaffdaf1555ca3dc55eb5d86e85c2671e57e500f2bd86f0",
        8136,
        8012,
        124,
        2004,
        610,
        618,
        619,
        114,
        (1,),
        "id00032",
        114,
        10,
        "id08135",
        "And now enough has been said regarding morals in general.",
        "c506ea69344c26950a2db21193f3d3f1741c99ed17be1385abe3cac79b88f60a",
    ),
    ComponentSpec(
        3,
        18755,
        "secunda-secundae",
        "Summa Theologica, Part II-II (Secunda Secundae)",
        'PART II-II ("Secunda Secundae")',
        "8ae600c9cbb255f1de07b05f1c4369bbc6aa5be4336e3f5f49ca94624fb21907",
        "c1fa4ed1dbaa01c9cb3658d9eec0241b51a1848c4f84bf779734ba4d2935ef18",
        "b72d9e8129b561760fc452548118f2a8f3d3768d020ba1c10d74e9b94516a6e6",
        12082,
        11876,
        206,
        2851,
        921,
        917,
        917,
        189,
        (183,),
        "id00034",
        189,
        10,
        "id12081",
        'Jesus Christ our Lord, "Who is over all things God blessed for ever. Amen."',
        "e5e6b07cf0aa3d3e90ec51c7a167c08f03141f04553e183a758feff0a8e0735c",
    ),
    ComponentSpec(
        4,
        19950,
        "tertia-pars",
        "Summa Theologica, Part III (Tertia Pars)",
        'THIRD PART ["III," "Tertia Pars"]',
        "72d2beb64627945f33ca276cbeafdab9da0738d79f5a0737abba0f446dc47bf4",
        "2115def3be1b02480329147caddde90cd16d378db1e13c427f904aa12fba9671",
        "f7527d6010df92e034f512a7f31ef12b060ed5a35ba418dfde1298c80d2d9e5c",
        7409,
        7306,
        103,
        1479,
        803,
        549,
        549,
        90,
        (),
        "id00027",
        90,
        4,
        "id07408",
        "before Baptism, penance for mortal sins is not distinct from penance for venial sins.",
        "00c9773347b58936e9d3af41786767d9c2739cd6b1b7d4ab298d728bb0ae1249",
    ),
)

EXPECTED_ARCHIVE_MEMBERS = 2
EXPECTED_UNNUMBERED_ARTICLE_SOURCE_IDS = (
    "pg18755-id03600",
    "pg18755-id05498",
    "pg18755-id08340",
    "pg18755-id09033",
)
EXPECTED_Q811_SOURCE_ID = "pg18755-id11244"
MISLABELED_ARTICLE_STARTS = {"pg17897-id01743": 1}
IMPLICIT_ARTICLE_STARTS = {
    "pg17611-id04760": 1,
    "pg17611-id04775": 1,
}
EXPECTED_EDITORIAL_INSERTION_IDS = (
    "pg19950-id01912",
    "pg19950-id01914",
    "pg19950-id01916",
    "pg19950-id01924",
    "pg19950-id01931",
)
EDITORIAL_COLUMN_IDS = {
    "id01916": "1",
    "id01924": "2",
    "id01931": "3",
}
CONTENTS_START_IDS = {
    17611: "id00025",
    17897: "id00024",
    18755: "id00024",
    19950: "id00023",
}
PROLOGUE_START_IDS = {
    17611: "id00042",
    17897: "id00034",
    19950: "id00029",
}
PROLOGUE_END_IDS = {17611: "id00045"}
PROLOGUE_LAST_IDS = {
    17611: "id00044",
    17897: "id00035",
    19950: "id00032",
}
Q38_CONFLICT_IDS = {
    "descriptor": "id02693",
    "inquiries": "id02694",
    "articles": ("id02700", "id02710", "id02720", "id02730", "id02740"),
}
ANALYSIS_CATEGORIES = {
    "objection": "Source paragraph is an objection.",
    "sed-contra": "Source paragraph is the counter-statement.",
    "respondeo": "Source paragraph is the principal answer.",
    "reply": "Source paragraph is a reply to an objection.",
    "inquiry": "Source paragraph is a numbered question inquiry.",
    "source-article-heading-mislabeled": (
        "Source marks an article start as a duplicate question heading."
    ),
    "electronic-editorial-insertion": (
        "Material is an electronic-edition insertion between source questions."
    ),
    "source-question-heading-omitted": (
        "Source omits the question-number heading; boundary is recovered from "
        "the retained sequence and article labels."
    ),
    "source-article-heading-omitted": (
        "Source omits a one-article heading; boundary is recovered from the "
        "retained question structure."
    ),
    "source-article-number-omitted": "Source article label omits its number.",
    "source-article-label-mismatch": (
        "Literal source article number conflicts with semantic position."
    ),
    "source-question-label-mismatch": (
        "Literal source question number conflicts with the current question."
    ),
}


@dataclass(frozen=True)
class LoadedComponent:
    spec: ComponentSpec
    raw_bytes: bytes
    units: tuple[etree._Element, ...]
    wrapper_text_sha256: str
    archive_members: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class ArticleLabel:
    literal: str
    question: int | None
    article: int | None
    malformed: bool
    q811_typo: bool


@dataclass(frozen=True)
class ConversionResult:
    output_path: Path
    accounting_path: Path
    accounting: dict[str, object]


def _qname(name: str) -> str:
    return f"{{{TEI_NS}}}{name}"


def _el(
    name: str,
    attrs: Mapping[str, str] | None = None,
    text: str | None = None,
    *,
    nsmap: Mapping[str | None, str] | None = None,
) -> etree._Element:
    node = etree.Element(_qname(name), nsmap=nsmap)
    for key, value in (attrs or {}).items():
        if key == "xml:id":
            node.set(XML_ID, value)
        elif key == "xml:lang":
            node.set(XML_LANG, value)
        else:
            node.set(key, value)
    node.text = text
    return node


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _normalized_text(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _text_digest(values: Iterable[str]) -> str:
    return _sha256("\n".join(values).encode("utf-8"))


def _source_xml_id(spec: ComponentSpec, source_id: str) -> str:
    return f"pg{spec.pg_id}-{source_id}"


def _source_corresp(spec: ComponentSpec, source_id: str) -> str:
    return f"{spec.source_url}#{source_id}"


def _copy_inline(source: etree._Element, target: etree._Element) -> None:
    target.text = source.text
    for child in source:
        if child.tag == "i":
            rendered = _el("hi", {"rend": "italic"})
            _copy_inline(child, rendered)
        elif child.tag == "br":
            rendered = _el("lb")
        else:  # guarded by _load_component, retained here for fail-closed clarity
            raise ConversionError(f"unsupported inline element: {child.tag}")
        rendered.tail = child.tail
        target.append(rendered)


def _render_unit(
    source: etree._Element,
    spec: ComponentSpec,
    *,
    tag: str = "p",
    attrs: Mapping[str, str] | None = None,
) -> etree._Element:
    source_id = source.get("id")
    if not source_id:
        raise ConversionError(f"PG {spec.pg_id} source unit has no id")
    combined = {
        "xml:id": _source_xml_id(spec, source_id),
        "corresp": _source_corresp(spec, source_id),
        **(attrs or {}),
    }
    rendered = _el(tag, combined)
    _copy_inline(source, rendered)
    return rendered


def _article_label(text: str) -> ArticleLabel | None:
    ordinal_values = {
        "FIRST": 1,
        "SECOND": 2,
        "THIRD": 3,
        "FOURTH": 4,
        "FIFTH": 5,
        "SIXTH": 6,
        "SEVENTH": 7,
        "EIGHTH": 8,
        "NINTH": 9,
        "TENTH": 10,
        "ELEVENTH": 11,
        "TWELFTH": 12,
        "THIRTEENTH": 13,
        "FOURTEENTH": 14,
        "FIFTEENTH": 15,
        "SIXTEENTH": 16,
    }
    plain_match = re.fullmatch(r"([A-Z-]+) ARTICLE", text)
    if plain_match:
        article = ordinal_values.get(plain_match.group(1))
        if article is None:
            raise ConversionError(f"unsupported plain article ordinal: {text}")
        return ArticleLabel(text, None, article, True, False)
    if text.startswith(">") or "ARTICLE [" not in text or not text.endswith("]"):
        return None
    question_match = re.search(r"\bQ[.,]?\s*(\d+)", text, flags=re.IGNORECASE)
    article_match = re.search(
        r"\b(?:Art|A)[.,]?\s*(\d+)", text, flags=re.IGNORECASE
    )
    question = int(question_match.group(1)) if question_match else None
    article = int(article_match.group(1)) if article_match else None
    malformed = question is None or article is None or not re.fullmatch(
        r"[A-Z-]+(?: [A-Z-]+)* ARTICLE \[[^\]]+, Q\. \d+, Art\. \d+\]",
        text,
    )
    return ArticleLabel(
        literal=text,
        question=question,
        article=article,
        malformed=malformed,
        q811_typo=question == 811,
    )


def _question_heading(text: str) -> int | None:
    match = re.fullmatch(r"QUESTION (\d+)", text)
    return int(match.group(1)) if match else None


def _question_title(text: str) -> bool:
    clean = text.rstrip(" _")
    return bool(re.search(r"\([Ii]n [A-Za-z-]+ Articles?\)$", clean))


def _is_treatise(text: str) -> bool:
    return text.startswith("TREATISE ON ") and "(QQ." in text


def _load_component(spec: ComponentSpec, raw_root: Path) -> LoadedComponent:
    archive_path = raw_root / spec.archive_name
    try:
        archive_bytes = archive_path.read_bytes()
    except OSError as exc:
        raise ConversionError(f"cannot read {archive_path}: {exc}") from exc
    actual_archive_hash = _sha256(archive_bytes)
    if actual_archive_hash != spec.archive_sha256:
        raise ConversionError(
            f"PG {spec.pg_id} archive hash changed: {actual_archive_hash}"
        )
    try:
        with ZipFile(BytesIO(archive_bytes)) as archive:
            infos = archive.infolist()
            if len(infos) != EXPECTED_ARCHIVE_MEMBERS:
                raise ConversionError(
                    f"PG {spec.pg_id} archive member count changed: {len(infos)}"
                )
            names = [info.filename for info in infos]
            if names != [spec.html_member, spec.cover_member]:
                raise ConversionError(
                    f"PG {spec.pg_id} archive members changed: {names}"
                )
            member_records: list[dict[str, object]] = []
            html_bytes: bytes | None = None
            for info in infos:
                member = archive.read(info)
                digest = _sha256(member)
                member_records.append(
                    {
                        "path": info.filename,
                        "bytes": len(member),
                        "compressed_bytes": info.compress_size,
                        "sha256": digest,
                    }
                )
                if info.filename == spec.html_member:
                    html_bytes = member
                    if digest != spec.html_sha256:
                        raise ConversionError(
                            f"PG {spec.pg_id} HTML member hash changed: {digest}"
                        )
                elif digest != spec.cover_sha256:
                    raise ConversionError(
                        f"PG {spec.pg_id} cover member hash changed: {digest}"
                    )
    except BadZipFile as exc:
        raise ConversionError(f"invalid retained ZIP {archive_path}: {exc}") from exc
    if html_bytes is None:  # pragma: no cover - member list guard proves otherwise
        raise ConversionError(f"missing HTML member for PG {spec.pg_id}")
    try:
        decoded = html_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConversionError(f"PG {spec.pg_id} HTML is not UTF-8: {exc}") from exc
    document = html.fromstring(decoded)
    bodies = document.xpath("//body")
    if len(bodies) != 1:
        raise ConversionError(f"PG {spec.pg_id} must contain one HTML body")
    body = bodies[0]
    wrappers = [node for node in body if node.tag in {"header", "footer"}]
    if [node.tag for node in wrappers] != ["header", "footer"]:
        raise ConversionError(f"PG {spec.pg_id} wrapper boundary changed")
    units = tuple(
        node
        for node in body
        if isinstance(node.tag, str) and node.tag not in {"header", "footer"}
    )
    allowed_top = {"p", "h1", "h3", "h4", "h5"}
    changed_top = sorted({node.tag for node in units} - allowed_top)
    if changed_top:
        raise ConversionError(
            f"PG {spec.pg_id} unsupported top-level elements: {changed_top}"
        )
    source_ids = [node.get("id") for node in units]
    if any(source_id is None for source_id in source_ids):
        raise ConversionError(f"PG {spec.pg_id} contains an unbound source unit")
    if len(set(source_ids)) != len(source_ids):
        raise ConversionError(f"PG {spec.pg_id} contains duplicate source ids")
    inline_tags = {
        child.tag
        for node in units
        for child in node.iterdescendants()
        if isinstance(child.tag, str)
    }
    if inline_tags - {"i", "br"}:
        raise ConversionError(
            f"PG {spec.pg_id} unsupported inline elements: "
            f"{sorted(inline_tags - {'i', 'br'})}"
        )
    wrapper_text = [_normalized_text(node) for node in wrappers]
    return LoadedComponent(
        spec=spec,
        raw_bytes=html_bytes,
        units=units,
        wrapper_text_sha256=_text_digest(wrapper_text),
        archive_members=tuple(member_records),
    )


def _source_census(component: LoadedComponent) -> dict[str, object]:
    spec = component.spec
    units = component.units
    texts = [_normalized_text(node) for node in units]
    question_headings = {
        question
        for text in texts
        if (question := _question_heading(text)) is not None
    }
    expected_set = set(range(1, spec.expected_questions + 1))
    heading_gaps = tuple(sorted(expected_set - question_headings))
    article_labels = [
        label
        for text in texts
        if (label := _article_label(text)) is not None
    ]
    census: dict[str, object] = {
        "source_unit_count": len(units),
        "source_paragraph_count": sum(node.tag == "p" for node in units),
        "source_heading_count": sum(node.tag != "p" for node in units),
        "source_italic_count": sum(
            child.tag == "i"
            for node in units
            for child in node.iterdescendants()
        ),
        "source_line_break_count": sum(
            child.tag == "br"
            for node in units
            for child in node.iterdescendants()
        ),
        "source_question_heading_count": len(question_headings),
        "source_question_heading_gaps": list(heading_gaps),
        "source_article_marker_count": len(article_labels),
        "source_malformed_article_marker_count": sum(
            label.malformed for label in article_labels
        ),
        "source_unnumbered_article_marker_count": sum(
            label.article is None for label in article_labels
        ),
        "source_q811_article_marker_count": sum(
            label.q811_typo for label in article_labels
        ),
        "source_objection_paragraph_count": sum(
            bool(re.match(r"^(?:Objection|Obj\.) \d+:", text)) for text in texts
        ),
        "source_sed_contra_paragraph_count": sum(
            text.startswith("On the contrary,") for text in texts
        ),
        "source_respondeo_paragraph_count": sum(
            text.startswith("I answer that,") for text in texts
        ),
        "source_reply_paragraph_count": sum(
            bool(re.match(r"^Reply (?:Obj\.|to Objection) \d+:", text))
            for text in texts
        ),
        "source_numbered_inquiry_count": sum(
            bool(re.match(r"^\(\d+\)", text)) for text in texts
        ),
        "source_bracketed_span_count": sum(
            len(re.findall(r"\[[^\]]+\]", text)) for text in texts
        ),
        "source_visible_text_sha256": _text_digest(texts),
        "wrapper_visible_text_sha256": component.wrapper_text_sha256,
    }
    expected = {
        "source_unit_count": spec.expected_units,
        "source_paragraph_count": spec.expected_paragraphs,
        "source_heading_count": spec.expected_headings,
        "source_italic_count": spec.expected_italics,
        "source_line_break_count": spec.expected_line_breaks,
        "source_question_heading_count": (
            spec.expected_questions - len(spec.expected_question_heading_gaps)
        ),
        "source_question_heading_gaps": list(spec.expected_question_heading_gaps),
        "source_article_marker_count": spec.expected_article_markers,
        "source_visible_text_sha256": spec.source_text_sha256,
    }
    changed = {
        key: {"expected": value, "actual": census[key]}
        for key, value in expected.items()
        if census[key] != value
    }
    if changed:
        raise ConversionError(f"PG {spec.pg_id} source census changed: {changed}")
    if spec.pg_id == 17897:
        by_id = {
            node.get("id", ""): _normalized_text(node) for node in component.units
        }
        descriptor = by_id.get(Q38_CONFLICT_IDS["descriptor"], "")
        inquiries = by_id.get(Q38_CONFLICT_IDS["inquiries"], "")
        article_ids = list(Q38_CONFLICT_IDS["articles"])
        article_labels = [by_id.get(source_id, "") for source_id in article_ids]
        if descriptor != "OF THE REMEDIES OF SORROW OR PAIN (In Four Articles)":
            raise ConversionError("PG 17897 Question 38 descriptor changed")
        if inquiries != (
            "We must now consider the remedies of pain or sorrow: under which "
            "head there are five points of inquiry:"
        ):
            raise ConversionError("PG 17897 Question 38 inquiry count changed")
        expected_labels = [
            f"{ordinal} ARTICLE [I-II, Q. 38, Art. {number}]"
            for number, ordinal in enumerate(
                ("FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH"), start=1
            )
        ]
        if article_labels != expected_labels:
            raise ConversionError("PG 17897 Question 38 article sequence changed")
        census["source_question_38_article_count_conflict"] = {
            "descriptor_source_id": _source_xml_id(spec, Q38_CONFLICT_IDS["descriptor"]),
            "descriptor_claimed_articles": 4,
            "inquiries_source_id": _source_xml_id(spec, Q38_CONFLICT_IDS["inquiries"]),
            "inquiry_count": 5,
            "article_source_ids": [
                _source_xml_id(spec, source_id) for source_id in article_ids
            ],
            "semantic_article_count": 5,
        }
    if spec.terminal_text not in texts[-1]:
        raise ConversionError(f"PG {spec.pg_id} terminal text changed")
    if units[-1].get("id") != spec.terminal_source_id:
        raise ConversionError(f"PG {spec.pg_id} terminal source id changed")
    return census


def _missing_question_starts(
    component: LoadedComponent,
) -> dict[int, int]:
    units = component.units
    texts = [_normalized_text(node) for node in units]
    starts: dict[int, int] = {}
    for missing_question in component.spec.expected_question_heading_gaps:
        first_article_index = next(
            (
                index
                for index, text in enumerate(texts)
                if (label := _article_label(text)) is not None
                and label.question == missing_question
            ),
            None,
        )
        if first_article_index is None:
            raise ConversionError(
                f"PG {component.spec.pg_id} cannot recover question "
                f"{missing_question} from article labels"
            )
        title_index = next(
            (
                index
                for index in range(first_article_index - 1, -1, -1)
                if _question_title(texts[index])
            ),
            None,
        )
        if title_index is None:
            raise ConversionError(
                f"PG {component.spec.pg_id} cannot recover title boundary "
                f"for question {missing_question}"
            )
        if any(
            _article_label(texts[index]) is not None
            for index in range(title_index, first_article_index)
        ):
            raise ConversionError(
                f"PG {component.spec.pg_id} ambiguous recovered boundary "
                f"for question {missing_question}"
            )
        starts[title_index] = missing_question
    return starts


def _paragraph_role(text: str) -> dict[str, str]:
    match = re.match(r"^(?:Objection|Obj\.) (\d+):", text)
    if match:
        return {"ana": "#objection", "n": match.group(1)}
    if text.startswith("On the contrary,"):
        return {"ana": "#sed-contra"}
    if text.startswith("I answer that,"):
        return {"ana": "#respondeo"}
    match = re.match(r"^Reply (?:Obj\.|to Objection) (\d+):", text)
    if match:
        return {"ana": "#reply", "n": match.group(1)}
    match = re.match(r"^\((\d+)\)", text)
    if match:
        return {"ana": "#inquiry", "n": match.group(1)}
    return {}


def _render_component(
    component: LoadedComponent,
    body: etree._Element,
) -> dict[str, object]:
    spec = component.spec
    units = component.units
    texts = [_normalized_text(node) for node in units]
    census = _source_census(component)
    try:
        main_start = next(
            index
            for index, node in enumerate(units)
            if node.get("id") == spec.main_start_id
        )
    except StopIteration as exc:
        raise ConversionError(f"PG {spec.pg_id} main boundary changed") from exc
    missing_starts = _missing_question_starts(component)
    explicit_starts = {
        index: question
        for index, text in enumerate(texts)
        if (question := _question_heading(text)) is not None
    }
    question_starts = {**explicit_starts, **missing_starts}
    question_starts = {
        index: question
        for index, question in question_starts.items()
        if _source_xml_id(spec, units[index].get("id", ""))
        not in MISLABELED_ARTICLE_STARTS
    }

    component_div = _el(
        "div",
        {
            "type": "component",
            "subtype": spec.code,
            "n": str(spec.order),
            "xml:id": f"component-{spec.code}",
            "corresp": f"https://www.gutenberg.org/ebooks/{spec.pg_id}",
        },
    )
    body.append(component_div)
    front = _el("div", {"type": "front-matter"})
    component_div.append(front)
    contents_start_id = CONTENTS_START_IDS[spec.pg_id]
    try:
        contents_start = next(
            index
            for index, node in enumerate(units[:main_start])
            if node.get("id") == contents_start_id
        )
    except StopIteration as exc:
        raise ConversionError(
            f"PG {spec.pg_id} contents boundary changed"
        ) from exc
    for source in units[:contents_start]:
        attrs = {"rend": f"source-{source.tag}"} if source.tag != "p" else {}
        front.append(_render_unit(source, spec, attrs=attrs))
    contents = _el(
        "div",
        {
            "type": "contents",
            "xml:id": f"{spec.code}-contents",
        },
    )
    front.append(contents)
    contents_units = units[contents_start:main_start]
    for position, source in enumerate(contents_units):
        if position == 0:
            contents.append(_render_unit(source, spec, tag="head"))
            continue
        attrs = {"rend": f"source-{source.tag}"} if source.tag != "p" else {}
        contents.append(_render_unit(source, spec, attrs=attrs))

    preamble = _el("div", {"type": "component-preamble"})
    component_div.append(preamble)
    current_treatise: etree._Element = component_div
    current_question: etree._Element | None = None
    current_article: etree._Element | None = None
    current_container: etree._Element = preamble
    current_question_number: int | None = None
    current_article_position = 0
    editorial: etree._Element | None = None
    editorial_subsection: etree._Element | None = None
    semantic_questions: list[int] = []
    article_count = 0
    unnumbered_ids: list[str] = []
    malformed_ids: list[str] = []
    q811_ids: list[str] = []
    question_label_mismatch_ids: list[str] = []
    article_label_mismatch_ids: list[str] = []
    recovered_article_ids: list[str] = []
    prologue_source_ids: list[str] = []

    for index in range(main_start, len(units)):
        source = units[index]
        text = texts[index]
        source_id = source.get("id", "")
        tei_source_id = _source_xml_id(spec, source_id)

        if source_id == PROLOGUE_START_IDS.get(spec.pg_id):
            prologue = _el(
                "div",
                {
                    "type": "prologue",
                    "xml:id": f"{spec.code}-prologue",
                },
            )
            # Keep the prologue immediately after its source-order predecessor:
            # inside a treatise when a retained treatise heading precedes it,
            # otherwise inside the component preamble.
            prologue_parent = (
                preamble if current_treatise is component_div else current_treatise
            )
            prologue_parent.append(prologue)
            prologue.append(_render_unit(source, spec, tag="head"))
            current_question = None
            current_article = None
            current_question_number = None
            current_article_position = 0
            current_container = prologue
            prologue_source_ids.append(tei_source_id)
            continue

        if source_id == PROLOGUE_END_IDS.get(spec.pg_id):
            title_block = _el("div", {"type": "component-title"})
            preamble.append(title_block)
            title_block.append(_render_unit(source, spec, tag="head"))
            current_container = title_block
            continue

        if tei_source_id in MISLABELED_ARTICLE_STARTS:
            if current_question is None:
                raise ConversionError(
                    f"PG {spec.pg_id} mislabeled article outside question"
                )
            current_article_position += 1
            current_article = _el(
                "div",
                {
                    "type": "article",
                    "n": str(current_article_position),
                    "xml:id": f"{spec.code}-article-{source_id}",
                    "subtype": "question-heading-mislabeled-as-article",
                    "ana": "#source-article-heading-mislabeled",
                },
            )
            current_question.append(current_article)
            current_article.append(_render_unit(source, spec, tag="head"))
            current_container = current_article
            article_count += 1
            recovered_article_ids.append(tei_source_id)
            continue

        if text == "ST. THOMAS AND THE IMMACULATE CONCEPTION (EDITORIAL NOTE)":
            editorial = _el(
                "div",
                {
                    "type": "editorial-insertion",
                    "xml:id": "pg19950-editorial-insertion-q26-q27",
                    "ana": "#electronic-editorial-insertion",
                },
            )
            current_treatise.append(editorial)
            editorial.append(_render_unit(source, spec, tag="head"))
            current_question = None
            current_article = None
            current_question_number = None
            current_container = editorial
            editorial_subsection = None
            continue

        question_number = question_starts.get(index)
        if question_number is not None:
            question_attrs = {
                "type": "question",
                "n": str(question_number),
                "xml:id": f"{spec.code}-question-{question_number}",
            }
            if index in missing_starts:
                question_attrs["ana"] = "#source-question-heading-omitted"
            current_question = _el("div", question_attrs)
            current_treatise.append(current_question)
            semantic_questions.append(question_number)
            current_question_number = question_number
            current_article_position = 0
            current_article = None
            editorial = None
            editorial_subsection = None
            current_container = current_question
            if index in explicit_starts:
                current_question.append(_render_unit(source, spec, tag="head"))
                continue

        if tei_source_id in IMPLICIT_ARTICLE_STARTS:
            if current_question is None:
                raise ConversionError(
                    f"PG {spec.pg_id} implicit article outside question"
                )
            current_article_position += 1
            current_article = _el(
                "div",
                {
                    "type": "article",
                    "n": str(current_article_position),
                    "xml:id": f"{spec.code}-article-implicit-{source_id}",
                    "ana": "#source-article-heading-omitted",
                },
            )
            current_question.append(current_article)
            current_container = current_article
            article_count += 1
            recovered_article_ids.append(tei_source_id)

        if _is_treatise(text):
            current_treatise = _el(
                "div",
                {
                    "type": "treatise",
                    "xml:id": f"{spec.code}-treatise-{source_id}",
                },
            )
            component_div.append(current_treatise)
            current_treatise.append(_render_unit(source, spec, tag="head"))
            current_question = None
            current_article = None
            current_question_number = None
            current_article_position = 0
            current_container = current_treatise
            editorial = None
            editorial_subsection = None
            continue

        label = _article_label(text)
        if label is not None:
            if current_question is None or current_question_number is None:
                raise ConversionError(
                    f"PG {spec.pg_id} article outside question at {source_id}"
                )
            semantic_question = label.question
            question_label_mismatch = (
                semantic_question is not None
                and semantic_question != current_question_number
            )
            if label.q811_typo:
                q811_ids.append(tei_source_id)
            if question_label_mismatch:
                question_label_mismatch_ids.append(tei_source_id)
            current_article_position += 1
            attrs = {
                "type": "article",
                "xml:id": f"{spec.code}-article-{source_id}",
                "n": str(current_article_position),
            }
            if label.article is None:
                attrs["ana"] = "#source-article-number-omitted"
                unnumbered_ids.append(tei_source_id)
            elif label.article != current_article_position:
                attrs["ana"] = "#source-article-label-mismatch"
                article_label_mismatch_ids.append(tei_source_id)
            if question_label_mismatch:
                attrs["ana"] = " ".join(
                    filter(
                        None,
                        [
                            attrs.get("ana"),
                            "#source-question-label-mismatch",
                        ],
                    )
                )
            if label.malformed:
                attrs["subtype"] = "malformed-source-label"
                malformed_ids.append(tei_source_id)
            current_article = _el("div", attrs)
            current_question.append(current_article)
            current_article.append(_render_unit(source, spec, tag="head"))
            current_container = current_article
            article_count += 1
            continue

        if editorial is not None and source.tag in {"h4", "h5"}:
            if source_id in EDITORIAL_COLUMN_IDS:
                subsection_type = "editorial-column"
                subsection_n = EDITORIAL_COLUMN_IDS[source_id]
            else:
                subsection_type = "editorial-diagram"
                subsection_n = None
            subsection_attrs = {
                "type": subsection_type,
                "xml:id": f"{spec.code}-editorial-{source_id}",
            }
            if subsection_n is not None:
                subsection_attrs["n"] = subsection_n
            editorial_subsection = _el(
                "div",
                subsection_attrs,
            )
            editorial.append(editorial_subsection)
            editorial_subsection.append(_render_unit(source, spec, tag="head"))
            current_container = editorial_subsection
            continue

        if editorial is not None and source_id == "id01938":
            commentary = _el(
                "div",
                {
                    "type": "editorial-commentary",
                    "xml:id": "tertia-pars-editorial-commentary-id01938",
                },
            )
            editorial.append(commentary)
            current_container = commentary

        target = current_container
        attrs = _paragraph_role(text)
        if source.tag != "p":
            attrs = {**attrs, "rend": f"source-{source.tag}"}
        target.append(_render_unit(source, spec, attrs=attrs))
        if current_container.get("type") == "prologue":
            prologue_source_ids.append(tei_source_id)

    expected_questions = list(range(1, spec.expected_questions + 1))
    if semantic_questions != expected_questions:
        raise ConversionError(
            f"PG {spec.pg_id} semantic question order changed: "
            f"{semantic_questions[:5]}...{semantic_questions[-5:]}"
        )
    if article_count != spec.expected_semantic_articles:
        raise ConversionError(
            f"PG {spec.pg_id} semantic article count changed: {article_count}"
        )
    return {
        **census,
        "semantic_question_count": len(semantic_questions),
        "semantic_question_first": semantic_questions[0],
        "semantic_question_last": semantic_questions[-1],
        "semantic_article_count": article_count,
        "terminal_question": spec.terminal_question,
        "terminal_article": spec.terminal_article,
        "contents_source_ids": [
            _source_xml_id(spec, source.get("id", ""))
            for source in contents_units
        ],
        "prologue_source_ids": prologue_source_ids,
        "recovered_article_start_source_ids": recovered_article_ids,
        "malformed_article_source_ids": malformed_ids,
        "unnumbered_article_source_ids": unnumbered_ids,
        "q811_source_ids": q811_ids,
        "question_label_mismatch_source_ids": question_label_mismatch_ids,
        "article_label_mismatch_source_ids": article_label_mismatch_ids,
        "main_start_source_id": spec.main_start_id,
        "terminal_source_id": spec.terminal_source_id,
    }


def _header() -> etree._Element:
    header = _el("teiHeader")
    file_desc = _el("fileDesc")
    title_stmt = _el("titleStmt")
    title_stmt.append(
        _el(
            "title",
            {"type": "main"},
            "Summa Theologica: Four Corrected English Components",
        )
    )
    title_stmt.append(_el("author", text="Thomas Aquinas"))
    responsibility = _el("respStmt")
    responsibility.append(_el("resp", text="translated by"))
    responsibility.append(
        _el("name", text="Fathers of the English Dominican Province")
    )
    title_stmt.append(responsibility)
    file_desc.append(title_stmt)
    publication = _el("publicationStmt")
    publication.append(_el("publisher", text="Open Christian Data"))
    publication.append(_el("date", {"when": "2026-08-31"}, "2026"))
    availability = _el("availability", {"status": "free"})
    availability.append(
        _el(
            "licence",
            {"target": "https://www.gutenberg.org/policy/license.html"},
            "Project Gutenberg records each retained component as public domain "
            "in the USA; Project Gutenberg trademark and redistribution terms "
            "remain distinct and jurisdiction-dependent.",
        )
    )
    publication.append(availability)
    file_desc.append(publication)
    source_desc = _el("sourceDesc")
    list_bibl = _el("listBibl")
    for spec in COMPONENTS:
        bibl = _el("bibl", {"xml:id": f"source-pg{spec.pg_id}"})
        bibl.append(_el("author", text="Thomas Aquinas"))
        bibl.append(_el("title", text=spec.title))
        bibl.append(
            _el("respStmt")
        )
        bibl[-1].append(_el("resp", text="translated by"))
        bibl[-1].append(
            _el("name", text="Fathers of the English Dominican Province")
        )
        bibl.append(_el("publisher", text="Benziger Brothers"))
        bibl.append(_el("pubPlace", text="New York"))
        bibl.append(_el("idno", {"type": "Project-Gutenberg"}, str(spec.pg_id)))
        list_bibl.append(bibl)
    source_desc.append(list_bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    encoding = _el("encodingDesc")
    project = _el("projectDesc")
    project.append(
        _el(
            "p",
            text=(
                "Every non-wrapper retained HTML content unit is projected "
                "exactly once and bound by source ID. Project Gutenberg header "
                "and license wrappers are retained separately and excluded from "
                "the candidate text. No print pagination or omitted formula is "
                "reconstructed."
            ),
        )
    )
    project.append(
        _el(
            "p",
            text=(
                "The electronic edition documents added dedication, contents, "
                "prologues, question and article numbering; Latin-referenced and "
                "transcription corrections; absent print pagination and headers; "
                "omitted repetitive article formula; normalized Bible citation "
                "numerals; inline bracketed print footnotes; transliterated Greek; "
                "and altered emphasis and quotation conventions."
            ),
        )
    )
    encoding.append(project)
    class_decl = _el("classDecl")
    taxonomy = _el(
        "taxonomy",
        {
            "xml:id": "summa-analysis-categories",
        },
    )
    for category_id, description in ANALYSIS_CATEGORIES.items():
        category = _el("category", {"xml:id": category_id})
        category.append(_el("catDesc", text=description))
        taxonomy.append(category)
    class_decl.append(taxonomy)
    encoding.append(class_decl)
    header.append(encoding)
    profile = _el("profileDesc")
    lang_usage = _el("langUsage")
    lang_usage.append(_el("language", {"ident": "en"}, "English"))
    profile.append(lang_usage)
    header.append(profile)
    revision = _el("revisionDesc")
    revision.append(
        _el(
            "change",
            {"when": "2026-08-31"},
            "Created deterministic, nonaccepted ticket-09 TEI candidate.",
        )
    )
    header.append(revision)
    return header


def build_tei(
    raw_root: Path | None = None,
) -> tuple[etree._ElementTree, dict[str, object]]:
    source_root = raw_root or resolve_repo_path(REPOSITORY_ROOT, RAW_LOGICAL_ROOT)
    loaded = [_load_component(spec, source_root) for spec in COMPONENTS]
    root = _el(
        "TEI",
        {"xml:id": "aquinas-summa-theologica-four-parts"},
        nsmap={None: TEI_NS},
    )
    root.append(_header())
    text = _el("text", {"xml:lang": "en"})
    body = _el("body")
    text.append(body)
    root.append(text)
    component_accounting = [
        _render_component(component, body) for component in loaded
    ]
    tree = etree.ElementTree(root)
    tei_unit_digests: dict[str, str] = {}
    tei_unit_counts: dict[str, int] = {}
    for spec in COMPONENTS:
        prefix = f"{spec.source_url}#"
        nodes = tree.xpath(
            "//*[@corresp and starts-with(@corresp, $prefix)]",
            prefix=prefix,
        )
        values = [_normalized_text(node) for node in nodes]
        tei_unit_digests[spec.code] = _text_digest(values)
        tei_unit_counts[spec.code] = len(nodes)
        if len(nodes) != spec.expected_units:
            raise ConversionError(
                f"PG {spec.pg_id} TEI unit accounting changed: {len(nodes)}"
            )
        if values != [_normalized_text(node) for node in loaded[spec.order - 1].units]:
            raise ConversionError(
                f"PG {spec.pg_id} TEI visible-text projection differs"
            )
    accounting: dict[str, object] = {
        "ticket": "09",
        "slug": "aquinas-summa-theologica-four-parts",
        "identity": (
            "one provisional Summa source-upgrade candidate with four bounded "
            "components; no canonical WorkCatalog write"
        ),
        "component_order": [spec.code for spec in COMPONENTS],
        "components": [
            {
                "order": component.spec.order,
                "project_gutenberg_id": component.spec.pg_id,
                "code": component.spec.code,
                "title": component.spec.title,
                "archive_sha256": component.spec.archive_sha256,
                "html_member": component.spec.html_member,
                "html_member_sha256": component.spec.html_sha256,
                "cover_member": component.spec.cover_member,
                "cover_member_sha256": component.spec.cover_sha256,
                "archive_members": list(component.archive_members),
                **component_accounting[index],
                "tei_unit_count": tei_unit_counts[component.spec.code],
                "tei_visible_text_sha256": tei_unit_digests[component.spec.code],
            }
            for index, component in enumerate(loaded)
        ],
        "total_source_units": sum(spec.expected_units for spec in COMPONENTS),
        "total_tei_units": sum(tei_unit_counts.values()),
        "total_semantic_questions": sum(
            spec.expected_questions for spec in COMPONENTS
        ),
        "total_article_markers": sum(
            spec.expected_article_markers for spec in COMPONENTS
        ),
        "total_semantic_articles": sum(
            spec.expected_semantic_articles for spec in COMPONENTS
        ),
        "source_visible_text_sha256": _text_digest(
            _normalized_text(node)
            for component in loaded
            for node in component.units
        ),
        "tei_visible_text_sha256": _text_digest(
            _normalized_text(node)
            for spec in COMPONENTS
            for node in tree.xpath(
                "//*[@corresp and starts-with(@corresp, $prefix)]",
                prefix=f"{spec.source_url}#",
            )
        ),
        "wrapper_exclusion": {
            "excluded_from_tei_text": True,
            "retained_in_exact_html_members": True,
            "elements_per_component": ["header#pg-header", "footer#pg-footer"],
        },
        "print_page_milestones": 0,
        "supplement_included": False,
        "fifth_component_included": False,
        "human_acceptance": "not-performed",
    }
    if accounting["source_visible_text_sha256"] != accounting["tei_visible_text_sha256"]:
        raise ConversionError("aggregate source/TEI visible text differs")
    return tree, accounting


def _coerce_tree(
    value: etree._ElementTree | etree._Element | bytes | Path,
) -> etree._ElementTree:
    if isinstance(value, etree._ElementTree):
        return value
    if isinstance(value, etree._Element):
        return etree.ElementTree(value)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    if isinstance(value, Path):
        return etree.parse(str(value), parser)
    return etree.ElementTree(etree.fromstring(value, parser))


def validate_tei(
    value: etree._ElementTree | etree._Element | bytes | Path,
) -> dict[str, object]:
    tree = _coerce_tree(value)
    schema_bytes = TEI_RNG_PATH.read_bytes()
    schema_parser = etree.XMLParser(resolve_entities=False, no_network=True)
    relaxng = etree.RelaxNG(
        etree.ElementTree(etree.fromstring(schema_bytes, schema_parser))
    )
    if not relaxng.validate(tree):
        details = "; ".join(str(error) for error in relaxng.error_log[:8])
        raise ConversionError(f"TEI Relax NG validation failed: {details}")
    components = tree.xpath("//t:body/t:div[@type='component']", namespaces=NS)
    if [node.get("subtype") for node in components] != [
        spec.code for spec in COMPONENTS
    ]:
        raise ConversionError("TEI component order or identity changed")
    per_component: list[dict[str, object]] = []
    for node, spec in zip(components, COMPONENTS, strict=True):
        source_prefix = f"{spec.source_url}#"
        source_nodes = node.xpath(
            ".//*[@corresp and starts-with(@corresp, $prefix)]",
            prefix=source_prefix,
        )
        actual_ids = [source.get(XML_ID, "") for source in source_nodes]
        expected_ids = [
            _source_xml_id(spec, f"id{number:05d}")
            for number in range(spec.expected_units)
        ]
        if actual_ids != expected_ids:
            first_mismatch = next(
                (
                    index
                    for index, pair in enumerate(
                        zip(actual_ids, expected_ids, strict=False)
                    )
                    if pair[0] != pair[1]
                ),
                min(len(actual_ids), len(expected_ids)),
            )
            raise ConversionError(
                f"PG {spec.pg_id} source-unit identity/order changed at "
                f"position {first_mismatch}: {len(actual_ids)} units"
            )
        visible_digest = _text_digest(
            _normalized_text(source) for source in source_nodes
        )
        if visible_digest != spec.source_text_sha256:
            raise ConversionError(f"PG {spec.pg_id} visible-text digest changed")
        italic_count = sum(
            len(source.xpath(".//t:hi[@rend='italic']", namespaces=NS))
            for source in source_nodes
        )
        line_break_count = sum(
            len(source.xpath(".//t:lb", namespaces=NS)) for source in source_nodes
        )
        if italic_count != spec.expected_italics:
            raise ConversionError(f"PG {spec.pg_id} italic projection changed")
        if line_break_count != spec.expected_line_breaks:
            raise ConversionError(f"PG {spec.pg_id} line-break projection changed")
        if actual_ids[-1] != _source_xml_id(spec, spec.terminal_source_id):
            raise ConversionError(f"PG {spec.pg_id} terminal source binding changed")
        if spec.terminal_text not in _normalized_text(source_nodes[-1]):
            raise ConversionError(f"PG {spec.pg_id} terminal text changed")

        contents = node.xpath(".//t:div[@type='contents']", namespaces=NS)
        if len(contents) != 1:
            raise ConversionError(f"PG {spec.pg_id} contents structure changed")
        contents_ids = contents[0].xpath(
            ".//*[@corresp and starts-with(@corresp, $prefix)]/@xml:id",
            namespaces=NS,
            prefix=source_prefix,
        )
        contents_first = int(CONTENTS_START_IDS[spec.pg_id][2:])
        contents_last = int(spec.main_start_id[2:])
        expected_contents_ids = [
            _source_xml_id(spec, f"id{number:05d}")
            for number in range(contents_first, contents_last)
        ]
        if contents_ids != expected_contents_ids:
            raise ConversionError(f"PG {spec.pg_id} contents boundary changed")

        prologues = node.xpath(".//t:div[@type='prologue']", namespaces=NS)
        if spec.pg_id in PROLOGUE_START_IDS:
            if len(prologues) != 1:
                raise ConversionError(f"PG {spec.pg_id} prologue structure changed")
            prologue_ids = prologues[0].xpath(
                ".//*[@corresp and starts-with(@corresp, $prefix)]/@xml:id",
                namespaces=NS,
                prefix=source_prefix,
            )
            prologue_first = int(PROLOGUE_START_IDS[spec.pg_id][2:])
            prologue_last = int(PROLOGUE_LAST_IDS[spec.pg_id][2:])
            expected_prologue_ids = [
                _source_xml_id(spec, f"id{number:05d}")
                for number in range(prologue_first, prologue_last + 1)
            ]
            if prologue_ids != expected_prologue_ids:
                raise ConversionError(f"PG {spec.pg_id} prologue boundary changed")
        elif prologues:
            raise ConversionError(f"PG {spec.pg_id} invented a prologue")

        questions = node.xpath(".//t:div[@type='question']", namespaces=NS)
        question_numbers = [int(question.get("n", "0")) for question in questions]
        if question_numbers != list(range(1, spec.expected_questions + 1)):
            raise ConversionError(f"PG {spec.pg_id} TEI question sequence changed")
        articles = node.xpath(".//t:div[@type='article']", namespaces=NS)
        if len(articles) != spec.expected_semantic_articles:
            raise ConversionError(f"PG {spec.pg_id} TEI article count changed")
        terminal_question = questions[-1]
        for question in questions:
            direct_articles = question.xpath(
                "./t:div[@type='article']", namespaces=NS
            )
            positions = [
                int(article.get("n", "0")) for article in direct_articles
            ]
            if positions != list(range(1, len(direct_articles) + 1)):
                raise ConversionError(
                    f"PG {spec.pg_id} article positions changed in question "
                    f"{question.get('n')}: {positions}"
                )
        terminal_articles = terminal_question.xpath(
            "./t:div[@type='article']", namespaces=NS
        )
        if int(terminal_question.get("n", "0")) != spec.terminal_question:
            raise ConversionError(f"PG {spec.pg_id} terminal question changed")
        if not terminal_articles or int(terminal_articles[-1].get("n", "0")) != spec.terminal_article:
            raise ConversionError(f"PG {spec.pg_id} terminal article changed")
        per_component.append(
            {
                "project_gutenberg_id": spec.pg_id,
                "question_count": len(questions),
                "article_count": len(articles),
                "terminal_question": spec.terminal_question,
                "terminal_article": spec.terminal_article,
                "source_unit_count": len(actual_ids),
                "source_visible_text_sha256": visible_digest,
                "italic_count": italic_count,
                "line_break_count": line_break_count,
                "terminal_source_id": actual_ids[-1],
            }
        )
    unit_ids = tree.xpath(
        "//*[@corresp and contains(@corresp, '#id')]/@xml:id",
        namespaces=NS,
    )
    if len(unit_ids) != len(set(unit_ids)):
        raise ConversionError("duplicate source-bound TEI unit ids")
    if len(unit_ids) != sum(spec.expected_units for spec in COMPONENTS):
        raise ConversionError("aggregate source-bound TEI unit count changed")
    all_ids = {
        node.get(XML_ID, "")
        for node in tree.getroot().iter()
        if node.get(XML_ID)
    }
    unresolved_ana = sorted(
        {
            token
            for value in tree.xpath("//@ana")
            for token in value.split()
            if token.startswith("#") and token[1:] not in all_ids
        }
    )
    if unresolved_ana:
        raise ConversionError(f"unresolved local analysis references: {unresolved_ana}")
    if tree.xpath("//t:pb", namespaces=NS):
        raise ConversionError("print page milestones were invented")
    if tree.xpath("//*[contains(translate(normalize-space(.), 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'SUPPLEMENT')]", namespaces=NS):
        # The retained source may discuss or credit supplementation, but no
        # component division may claim the traditional Supplement.
        component_labels = [node.get("subtype", "") for node in components]
        if "supplement" in component_labels:
            raise ConversionError("unreleased Supplement component present")
    return {
        "tei_p5_relaxng_valid": True,
        "component_count": len(components),
        "components": per_component,
        "source_bound_unit_count": len(unit_ids),
        "tei_relaxng_sha256": _sha256(schema_bytes),
        "unresolved_analysis_reference_count": 0,
        "print_page_milestone_count": 0,
        "supplement_component_count": 0,
    }


def convert(
    *,
    output_path: Path | None = None,
    accounting_path: Path | None = None,
    raw_root: Path | None = None,
) -> ConversionResult:
    output = output_path or resolve_repo_path(
        REPOSITORY_ROOT, f"{REPORT_LOGICAL_ROOT}/candidate.tei.xml"
    )
    accounting_output = accounting_path or resolve_repo_path(
        REPOSITORY_ROOT,
        f"{REPORT_LOGICAL_ROOT}/accounting.json"
    )
    if output.resolve() == accounting_output.resolve():
        raise ConversionError("candidate and accounting outputs must be distinct")
    tree, accounting = build_tei(raw_root)
    candidate_bytes = etree.tostring(
        tree,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )
    validation = validate_tei(candidate_bytes)
    accounting = {
        **accounting,
        "validation": validation,
        "tei_relaxng_sha256": validation["tei_relaxng_sha256"],
        "candidate_bytes": len(candidate_bytes),
        "candidate_sha256": _sha256(candidate_bytes),
    }
    accounting_bytes = (
        json.dumps(accounting, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    accounting_output.parent.mkdir(parents=True, exist_ok=True)
    candidate_staging = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    accounting_staging = accounting_output.with_name(
        f".{accounting_output.name}.{os.getpid()}.tmp"
    )
    try:
        candidate_staging.write_bytes(candidate_bytes)
        accounting_staging.write_bytes(accounting_bytes)
        os.replace(candidate_staging, output)
        os.replace(accounting_staging, accounting_output)
    finally:
        candidate_staging.unlink(missing_ok=True)
        accounting_staging.unlink(missing_ok=True)
    return ConversionResult(output, accounting_output, accounting)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--accounting-output", type=Path)
    parser.add_argument("--raw-root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = convert(
        output_path=args.output,
        accounting_path=args.accounting_output,
        raw_root=args.raw_root,
    )
    print(
        json.dumps(
            {
                "output": str(result.output_path),
                "accounting": str(result.accounting_path),
                "candidate_sha256": result.accounting["candidate_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
