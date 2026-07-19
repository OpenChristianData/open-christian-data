"""Convert scoped CCEL ThML into the TEI intermediate representation."""
from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lxml import etree

from ocd_kernel.lib.bible_ref_normalizer import parse_maclaren_ref, parse_thml_refs
from build.tei.census import _display_path, _parse_thml
from build.tei.ccel_work_config import (
    CcelWorkConfig,
    ccel_division_rule,
    load_ccel_work_config,
    select_ccel_scope,
)
from ocd_kernel.tei.writer import TEI_NS, XML_ID, XML_LANG, serialize, stamp_header, tei_el

LANG_MAP = {
    "EL": "grc",
    "HE": "he",
    "LA": "la",
    "FR": "fr",
    "DE": "de",
}

SKIP_TAGS = {"insertIndex", "style", "selector", "scripContext"}
BOOK_DOT_RE = re.compile(r"\b((?:\d\s*)?[A-Za-z]+)\.")
DIV_TAG_RE = re.compile(r"^div\d+$")
HEADING_TAGS = {"h1", "h2", "h3", "h4", "title"}
OSIS_PREFIX_RE = re.compile(r"^Bible(?:\.[A-Za-z0-9_-]+)?:")


class ConversionError(ValueError):
    """Raised when ThML contains content with no TEI ruling."""


@dataclass(frozen=True)
class ConversionResult:
    output_path: Path
    unparsed_scriprefs: int


@dataclass
class _State:
    unparsed_scriprefs: int = 0


def _append_text(parent: etree._Element, text: str | None) -> None:
    if not text:
        return
    if len(parent):
        last = parent[-1]
        last.tail = (last.tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _source_location(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None:
        local = etree.QName(current).localname
        node_id = current.get("id")
        if node_id:
            parts.append(f"{local}#{node_id}")
        else:
            parts.append(local)
        current = current.getparent()
    return " > ".join(reversed(parts))


def _xml_attrs(node: etree._Element) -> dict[str, str]:
    attrs: dict[str, str] = {}
    node_id = node.get("id")
    if node_id:
        attrs["xml:id"] = node_id
    lang = node.get("lang")
    if lang:
        try:
            attrs["xml:lang"] = LANG_MAP[lang]
        except KeyError as exc:
            raise ConversionError(f"Unmapped ThML lang code {lang!r} at {_source_location(node)}") from exc
    return attrs


def _copy_children(
    source: etree._Element,
    target: etree._Element,
    state: _State,
    division_rules: list[dict[str, Any]] | None = None,
) -> None:
    _append_text(target, source.text)
    for child in source:
        if etree.QName(child).localname in SKIP_TAGS:
            _append_text(target, child.tail)
            continue
        converted = _convert_inline(child, state, division_rules)
        target.append(converted)
        _append_text(target, child.tail)


def _convert_inline(
    node: etree._Element,
    state: _State,
    division_rules: list[dict[str, Any]] | None = None,
) -> etree._Element:
    tag = etree.QName(node).localname

    if tag == "p":
        out = tei_el("p", _xml_attrs(node))
    elif tag == "argument":
        return _convert_argument(node, state, division_rules)
    elif tag in HEADING_TAGS:
        out = tei_el("head", _xml_attrs(node))
    elif tag == "note":
        out = tei_el(
            "note",
            {
                **_xml_attrs(node),
                "place": node.get("place", ""),
                "n": node.get("n", ""),
            },
        )
    elif tag == "pb":
        out = tei_el("pb", {**_xml_attrs(node), "n": node.get("n", "")})
    elif tag == "scripRef":
        out = tei_el("ref", {**_xml_attrs(node), "type": "scripture"})
        refs = _parse_scripref(node.get("passage") or "", node.get("osisRef") or "")
        if refs:
            out.set("cRef", " ".join(refs))
        else:
            state.unparsed_scriprefs += 1
    elif tag == "i":
        out = tei_el("hi", {**_xml_attrs(node), "rend": "italic"})
    elif tag == "span":
        if node.get("lang"):
            out = tei_el("foreign", _xml_attrs(node))
        else:
            out = tei_el("seg", _xml_attrs(node))
    elif tag == "sup":
        out = tei_el("hi", {**_xml_attrs(node), "rend": "superscript"})
    elif tag == "br":
        out = tei_el("lb", _xml_attrs(node))
    elif tag == "table":
        out = tei_el("table", _xml_attrs(node))
    elif tag == "tr":
        out = tei_el("row", _xml_attrs(node))
    elif tag in {"td", "th"}:
        out = tei_el("cell", _xml_attrs(node))
    elif tag == "name":
        out = tei_el("name", _xml_attrs(node))
    elif tag == "cite":
        out = tei_el("title", _xml_attrs(node))
    elif tag == "q":
        out = tei_el("quote", _xml_attrs(node))
    elif DIV_TAG_RE.match(tag):
        return _convert_configured_div(node, division_rules or [], state)
    else:
        raise ConversionError(f"No TEI mapping for ThML tag <{tag}> at {_source_location(node)}")

    _copy_children(node, out, state, division_rules)
    return out


def _argument_needs_wrapper(source: etree._Element) -> bool:
    if (source.text or "").strip():
        return True
    return any(etree.QName(child).localname != "p" for child in source)


def _convert_argument(
    source: etree._Element,
    state: _State,
    division_rules: list[dict[str, Any]] | None = None,
) -> etree._Element:
    out = tei_el("argument", _xml_attrs(source))
    if _argument_needs_wrapper(source):
        attrs = {"xml:id": f"{source.get('id')}-p"} if source.get("id") else {}
        wrapper = tei_el("p", attrs)
        _copy_children(source, wrapper, state, division_rules)
        out.append(wrapper)
        return out
    _copy_children(source, out, state, division_rules)
    return out


def _parse_scripref(passage: str, osis_ref: str = "") -> list[str]:
    osis_refs = [OSIS_PREFIX_RE.sub("", item).strip() for item in osis_ref.split()]
    osis_refs = [item for item in osis_refs if item]
    if osis_refs:
        return osis_refs
    candidates = [passage, BOOK_DOT_RE.sub(r"\1", passage)]
    previous_disable = logging.root.manager.disable
    logging.disable(logging.WARNING)
    try:
        for candidate in candidates:
            refs = parse_thml_refs(candidate)
            if refs:
                return refs
        for candidate in candidates:
            refs = parse_maclaren_ref(candidate)
            if refs:
                return refs
    finally:
        logging.disable(previous_disable)
    return []


def _print_source(root: etree._Element, config: dict[str, object]) -> str:
    values = root.xpath("string(.//ThML.head/printSourceInfo)")
    mined = " ".join(str(values).split())
    if mined:
        return mined
    return str(config.get("source_edition") or "")


def _print_source_for_work(root: etree._Element, config: CcelWorkConfig) -> str:
    values = root.xpath("string(.//ThML.head/printSourceInfo)")
    mined = " ".join(str(values).split())
    return mined or config.source_edition


def _division_rule(node: etree._Element, rules: list[dict[str, Any]]) -> dict[str, Any]:
    return ccel_division_rule(node, rules)


def _convert_configured_div(
    source_div: etree._Element,
    division_rules: list[dict[str, Any]],
    state: _State,
) -> etree._Element:
    rule = _division_rule(source_div, division_rules)
    if rule.get("skip"):
        raise ConversionError(f"Skipped div was converted at {_source_location(source_div)}")
    attrs = {**_xml_attrs(source_div), "type": str(rule.get("tei_type") or "section")}
    out = tei_el("div", attrs)
    if source_div.get("title"):
        out.append(tei_el("head", text=source_div.get("title", "")))
    for child in source_div:
        tag = etree.QName(child).localname
        if tag in SKIP_TAGS:
            continue
        if DIV_TAG_RE.match(tag):
            child_rule = _division_rule(child, division_rules)
            if child_rule.get("skip"):
                continue
            out.append(_convert_configured_div(child, division_rules, state))
        else:
            out.append(_convert_inline(child, state, division_rules))
    return out


def _direct_front_content(source_root: etree._Element, state: _State, rules: list[dict[str, Any]]) -> etree._Element | None:
    direct_content = [
        child
        for child in source_root
        if not DIV_TAG_RE.match(etree.QName(child).localname) and etree.QName(child).localname not in SKIP_TAGS
    ]
    if not direct_content:
        return None
    front_div = tei_el("div", {"type": "title"})
    for child in direct_content:
        front_div.append(_convert_inline(child, state, rules))
    return front_div


def convert_ccel_work_to_tei(
    config_path: str | Path,
    work_id: str,
    output_path: str | Path | None = None,
    *,
    repo_root: str | Path = ".",
) -> ConversionResult:
    config = load_ccel_work_config(config_path, work_id, repo_root)
    output = Path(output_path) if output_path is not None else Path(repo_root) / "ir" / "ccel" / f"{config.work_id}.{config.rendering_id}.tei.xml"
    root = _parse_thml(config.raw_path)
    try:
        source_root = select_ccel_scope(root, config)
    except ValueError as exc:
        raise ConversionError(str(exc)) from exc
    state = _State()

    tei = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    tei.append(
        stamp_header(
            title=config.title,
            author=config.author,
            contributors=config.contributors,
            source_url=config.source_url,
            source_sha256=config.source_hash,
            print_source=_print_source_for_work(root, config),
        )
    )

    text = tei_el("text")
    front = tei_el("front")
    direct_front = _direct_front_content(source_root, state, config.division_rules)
    if direct_front is not None:
        front.append(direct_front)
    body = tei_el("body")

    for child in source_root:
        tag = etree.QName(child).localname
        if tag in SKIP_TAGS:
            continue
        if DIV_TAG_RE.match(tag):
            rule = _division_rule(child, config.division_rules)
            if rule.get("skip"):
                continue
            converted = _convert_configured_div(child, config.division_rules, state)
            if rule.get("place") == "front":
                front.append(converted)
            else:
                body.append(converted)
        elif direct_front is None:
            front.append(_convert_inline(child, state, config.division_rules))

    if len(front):
        text.append(front)
    text.append(body)
    tei.append(text)
    serialize(etree.ElementTree(tei), output)
    return ConversionResult(output_path=output, unparsed_scriprefs=state.unparsed_scriprefs)


def _build_front_matter(div1: etree._Element, state: _State) -> etree._Element | None:
    direct_content = [
        child
        for child in div1
        if etree.QName(child).localname in {"p", "pb", "note", "scripRef", "i", "span", "sup", "br"}
    ]
    if not direct_content:
        return None
    front_div = tei_el("div", {"type": "title"})
    for child in direct_content:
        front_div.append(_convert_inline(child, state))
    return front_div


def _convert_div2(div2: etree._Element, n: int, state: _State) -> etree._Element:
    div3_children = list(div2.xpath("./div3"))
    div_type = "preface" if not div3_children else "book"
    out = tei_el("div", {**_xml_attrs(div2), "type": div_type, "n": str(n)})
    out.append(tei_el("head", text=div2.get("title", "")))

    for child in div2:
        tag = etree.QName(child).localname
        if tag == "div3":
            chapter_n = len(out.xpath("./tei:div[@type='chapter']", namespaces={"tei": TEI_NS})) + 1
            out.append(_convert_div3(child, chapter_n, state))
        elif tag in {"p", "pb", "note", "scripRef", "i", "span", "sup", "br"}:
            out.append(_convert_inline(child, state))
        elif tag in SKIP_TAGS:
            continue
        else:
            raise ConversionError(f"No TEI mapping for ThML tag <{tag}> at {_source_location(child)}")
    return out


def _convert_div3(div3: etree._Element, n: int, state: _State) -> etree._Element:
    out = tei_el("div", {**_xml_attrs(div3), "type": "chapter", "n": str(n)})
    out.append(tei_el("head", text=div3.get("title", "")))
    for child in div3:
        tag = etree.QName(child).localname
        if tag in {"p", "pb", "note", "scripRef", "i", "span", "sup", "br"}:
            out.append(_convert_inline(child, state))
        elif tag in SKIP_TAGS:
            continue
        else:
            raise ConversionError(f"No TEI mapping for ThML tag <{tag}> at {_source_location(child)}")
    return out


def convert_thml_to_tei(
    thml_path: str | Path,
    div1_id: str,
    config_path: str | Path,
    output_path: str | Path,
) -> ConversionResult:
    thml = Path(thml_path)
    config_file = Path(config_path)
    output = Path(output_path)

    config = json.loads(config_file.read_text(encoding="utf-8"))
    root = _parse_thml(thml)
    matches = root.xpath(".//div1[@id=$div1_id]", div1_id=div1_id)
    if not matches:
        raise ConversionError(f"No div1 with id {div1_id!r} found in {_display_path(thml)}")
    div1 = matches[0]
    state = _State()

    tei = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    tei.append(
        stamp_header(
            title=str(config.get("title") or div1.get("title") or ""),
            author=str(config.get("author") or ""),
            contributors=[str(item) for item in config.get("contributors", [])],
            source_url=str(config.get("source_url") or ""),
            source_sha256=str(config.get("source_hash") or ""),
            print_source=_print_source(root, config),
        )
    )

    text = tei_el("text")
    front = tei_el("front")
    direct_front = _build_front_matter(div1, state)
    if direct_front is not None:
        front.append(direct_front)
    body = tei_el("body")

    div2_children = list(div1.xpath("./div2"))
    book_n = 0
    for div2 in div2_children:
        converted = _convert_div2(div2, book_n + 1, state)
        if converted.get("type") == "preface":
            front.append(converted)
        else:
            book_n += 1
            converted.set("n", str(book_n))
            body.append(converted)

    if len(front):
        text.append(front)
    text.append(body)
    tei.append(text)
    serialize(etree.ElementTree(tei), output)
    return ConversionResult(output_path=output, unparsed_scriprefs=state.unparsed_scriprefs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert one CCEL ThML div1 to TEI.")
    parser.add_argument("thml_path", type=Path)
    parser.add_argument("div1_id")
    parser.add_argument("config_path", type=Path)
    parser.add_argument("output_path", type=Path)
    args = parser.parse_args()
    result = convert_thml_to_tei(args.thml_path, args.div1_id, args.config_path, args.output_path)
    print(f"Wrote {result.output_path.as_posix()}")
    print(f"Unparsed scripRef count: {result.unparsed_scriprefs}")


if __name__ == "__main__":
    main()
