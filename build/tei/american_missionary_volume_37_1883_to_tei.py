"""Reconstruct the twelve 1883 American Missionary issues as one TEI volume."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree, html

from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.writer import XML_NS, serialize, stamp_header, tei_el

TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS, "xml": XML_NS}
BLOCK_TAGS = {"address", "blockquote", "div", "dl", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "ol", "p", "pre", "table", "ul"}
SKIP_CLASSES = {"pg-boilerplate", "pgheader"}


class ConversionError(ValueError):
    """Raised when retained bytes or reconstructed structure violate the release."""


@dataclass(frozen=True)
class IssueSpec:
    number: int
    month: str
    ebook: int
    html_sha256: str
    text_sha256: str
    archive_sha256: str


@dataclass
class BuildState:
    carrier_texts: list[str] = field(default_factory=list)
    carrier_ids: list[str] = field(default_factory=list)
    issue_carriers: dict[str, int] = field(default_factory=dict)
    graphic_urls: list[str] = field(default_factory=list)

    def register(self, node: etree._Element, text: str, issue: IssueSpec) -> None:
        normalized = _normalize(text)
        if not normalized:
            return
        source_xml_id = node.get(f"{{{XML_NS}}}id")
        if source_xml_id:
            node.insert(0, tei_el("anchor", {"xml:id": source_xml_id}))
        ordinal = len(self.carrier_texts) + 1
        carrier_id = f"amv37-src-B{ordinal:05d}"
        node.set(f"{{{XML_NS}}}id", carrier_id)
        node.set("n", str(ordinal))
        self.carrier_ids.append(carrier_id)
        self.carrier_texts.append(normalized)
        key = str(issue.ebook)
        self.issue_carriers[key] = self.issue_carriers.get(key, 0) + 1


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(values: list[str]) -> str:
    payload = "\n".join(values).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize(value: str) -> str:
    return " ".join(value.split())


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _classes(node: etree._Element) -> list[str]:
    return (node.get("class") or "").split()


def _safe(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    if not cleaned or not re.match(r"[A-Za-z_]", cleaned):
        cleaned = "id-" + cleaned
    return cleaned


def _source_id(node: etree._Element, issue: IssueSpec) -> str | None:
    value = node.get("id")
    return f"amv37-i{issue.number:02d}-{_safe(value)}" if value else None


def _copy_id(source: etree._Element, target: etree._Element, issue: IssueSpec) -> None:
    source_id = _source_id(source, issue)
    if source_id:
        target.set(f"{{{XML_NS}}}id", source_id)


def _source_text(node: etree._Element, *, exclude_nested_lists: bool = False) -> str:
    clone = copy.deepcopy(node)
    def remove_preserving_tail(element: etree._Element) -> None:
        parent = element.getparent()
        if parent is None:
            return
        tail = element.tail or ""
        previous = element.getprevious()
        if previous is not None:
            previous.tail = (previous.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
        parent.remove(element)
    for hidden in clone.xpath(
        ".//*[contains(concat(' ', normalize-space(@class), ' '), ' pagenum ') or "
        "contains(concat(' ', normalize-space(@class), ' '), ' hidev ') or self::script or self::style]"
    ):
        remove_preserving_tail(hidden)
    if exclude_nested_lists:
        for nested in clone.xpath("./ul|./ol|.//ul|.//ol"):
            if nested.getparent() is not None:
                remove_preserving_tail(nested)
    return _normalize("".join(clone.itertext()))


def _append_text(parent: etree._Element, text: str | None) -> None:
    if not text:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _rend(node: etree._Element) -> str | None:
    tokens: list[str] = []
    tag = node.tag.lower() if isinstance(node.tag, str) else ""
    tokens.extend({"b": ["bold"], "strong": ["bold"], "i": ["italic"], "em": ["italic"], "sup": ["superscript"], "sub": ["subscript"]}.get(tag, []))
    for class_name in _classes(node):
        if class_name not in {"pagenum", "hidev"}:
            tokens.append(class_name)
    style = node.get("style")
    if style:
        tokens.append("style-" + _safe(style))
    return " ".join(dict.fromkeys(tokens)) or None


def _target(href: str, issue: IssueSpec) -> str:
    if href.startswith("#"):
        return f"#amv37-i{issue.number:02d}-{_safe(href[1:])}"
    return href


def _append_inline(parent: etree._Element, source: etree._Element, issue: IssueSpec, state: BuildState, *, skip_lists: bool = False) -> None:
    _append_text(parent, source.text)
    for child in source:
        if not isinstance(child.tag, str):
            _append_text(parent, child.tail)
            continue
        tag = child.tag.lower()
        classes = set(_classes(child))
        if "hidev" in classes or tag in {"script", "style"}:
            _append_text(parent, child.tail)
            continue
        if skip_lists and tag in {"ul", "ol"}:
            _append_text(parent, child.tail)
            continue
        if "pagenum" in classes:
            attrs: dict[str, str] = {}
            number = child.get("title") or _normalize("".join(child.itertext())).strip("[]")
            if number:
                attrs["n"] = number
            source_id = _source_id(child, issue)
            if not source_id:
                nested_ids = child.xpath(".//*[@id][1]/@id")
                if nested_ids:
                    source_id = f"amv37-i{issue.number:02d}-{_safe(nested_ids[0])}"
            if source_id:
                attrs["xml:id"] = source_id
            parent.append(tei_el("pb", attrs))
        elif tag == "br":
            parent.append(tei_el("lb"))
        elif tag == "img":
            url = child.get("src") or ""
            graphic = tei_el("graphic", {"url": f"pg{issue.ebook}/{url}"})
            alt = child.get("alt")
            if alt:
                graphic.set("n", alt)
            parent.append(graphic)
            state.graphic_urls.append(f"pg{issue.ebook}/{url}")
        elif tag == "a" and child.get("id") and not child.get("href") and not _source_text(child):
            parent.append(tei_el("anchor", {"xml:id": f"amv37-i{issue.number:02d}-{_safe(child.get('id') or '')}"}))
        else:
            attrs = {}
            if tag == "a" and child.get("href"):
                out_tag = "ref"
                attrs["target"] = _target(child.get("href") or "", issue)
            elif tag in {"q", "cite"}:
                out_tag = "q"
            elif tag in {"b", "strong", "i", "em", "sup", "sub", "small"} or _rend(child):
                out_tag = "hi"
                attrs["rend"] = _rend(child) or tag
            else:
                out_tag = "seg"
            source_id = _source_id(child, issue)
            if source_id:
                attrs["xml:id"] = source_id
            if child.get("lang"):
                attrs["xml:lang"] = child.get("lang") or ""
            rendered = tei_el(out_tag, attrs)
            _append_inline(rendered, child, issue, state, skip_lists=skip_lists)
            parent.append(rendered)
        _append_text(parent, child.tail)


def _direct_text(node: etree._Element) -> str:
    values = [node.text or ""]
    for child in node:
        values.append(child.tail or "")
    return _normalize(" ".join(values))


def _block(node: etree._Element, parent: etree._Element, issue: IssueSpec, state: BuildState) -> None:
    if not isinstance(node.tag, str):
        return
    tag = node.tag.lower()
    classes = set(_classes(node))
    if classes & SKIP_CLASSES or tag in {"footer", "header", "script", "style"}:
        return
    if tag == "a" and node.get("id") and not node.get("href") and not _source_text(node):
        parent.append(tei_el("anchor", {"xml:id": f"amv37-i{issue.number:02d}-{_safe(node.get('id') or '')}"}))
        return
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        attrs = {"type": tag}
        if node.get("title"):
            attrs["n"] = node.get("title") or ""
        out = tei_el("head", attrs)
        _copy_id(node, out, issue)
        _append_inline(out, node, issue, state)
        heading_text = _source_text(node)
        if not heading_text and node.get("title"):
            heading_text = _normalize(node.get("title") or "")
            out.text = heading_text
        parent.append(out)
        state.register(out, heading_text, issue)
        return
    if tag in {"p", "address"}:
        attrs = {"type": "address"} if tag == "address" else {}
        rend = _rend(node)
        if rend:
            attrs["rend"] = rend
        out = tei_el("p", attrs)
        _copy_id(node, out, issue)
        _append_inline(out, node, issue, state)
        parent.append(out)
        state.register(out, _source_text(node), issue)
        return
    if tag == "pre":
        source_value = _source_text(node)
        if not source_value:
            return
        out = tei_el("ab", {"type": "preformatted"}, node.text or "")
        _copy_id(node, out, issue)
        parent.append(out)
        state.register(out, source_value, issue)
        return
    if tag in {"ul", "ol"}:
        out = tei_el("list", {"type": "ordered" if tag == "ol" else "unordered"})
        _copy_id(node, out, issue)
        parent.append(out)
        for child in node:
            if not isinstance(child.tag, str) or child.tag.lower() != "li":
                continue
            item = tei_el("item")
            _copy_id(child, item, issue)
            _append_inline(item, child, issue, state, skip_lists=True)
            out.append(item)
            state.register(item, _source_text(child, exclude_nested_lists=True), issue)
            for nested in child:
                if isinstance(nested.tag, str) and nested.tag.lower() in {"ul", "ol"}:
                    _block(nested, item, issue, state)
        return
    if tag == "table":
        out = tei_el("table")
        _copy_id(node, out, issue)
        if node.get("summary"):
            out.set("n", node.get("summary") or "")
        parent.append(out)
        for row_node in node.xpath("./thead/tr|./tbody/tr|./tfoot/tr|./tr"):
            row = tei_el("row")
            out.append(row)
            for cell_node in row_node.xpath("./th|./td"):
                cell = tei_el("cell", {"role": "label" if cell_node.tag.lower() == "th" else "data"})
                _copy_id(cell_node, cell, issue)
                _append_inline(cell, cell_node, issue, state)
                row.append(cell)
                state.register(cell, _source_text(cell_node), issue)
        return
    if tag == "img":
        url = node.get("src") or ""
        figure = tei_el("figure")
        _copy_id(node, figure, issue)
        figure.append(tei_el("graphic", {"url": f"pg{issue.ebook}/{url}"}))
        if node.get("alt"):
            figure.append(tei_el("figDesc", text=node.get("alt") or ""))
        parent.append(figure)
        state.graphic_urls.append(f"pg{issue.ebook}/{url}")
        return
    if tag == "hr":
        parent.append(tei_el("milestone", {"unit": "separator", "rend": _rend(node) or "rule"}))
        return
    if tag == "blockquote":
        out = tei_el("quote")
        _copy_id(node, out, issue)
        parent.append(out)
        _children(node, out, issue, state)
        return
    if tag == "dl":
        out = tei_el("list", {"type": "description"})
        _copy_id(node, out, issue)
        parent.append(out)
        for child in node:
            if not isinstance(child.tag, str) or child.tag.lower() not in {"dt", "dd"}:
                continue
            item = tei_el("item", {"type": "term" if child.tag.lower() == "dt" else "definition"})
            _append_inline(item, child, issue, state)
            out.append(item)
            state.register(item, _source_text(child), issue)
        return
    if tag == "div":
        class_names = _classes(node)
        attrs = {"type": class_names[0] if class_names else "source-division"}
        if class_names:
            attrs["rend"] = " ".join(class_names)
        out = tei_el("div", attrs)
        _copy_id(node, out, issue)
        parent.append(out)
        _children(node, out, issue, state)
        return
    text = _source_text(node)
    if text:
        out = tei_el("ab", {"type": f"html-{tag}"})
        _copy_id(node, out, issue)
        _append_inline(out, node, issue, state)
        parent.append(out)
        state.register(out, text, issue)


def _children(node: etree._Element, parent: etree._Element, issue: IssueSpec, state: BuildState) -> None:
    direct = _direct_text(node)
    if direct:
        wrapper = tei_el("div", {"type": "source-child", "rend": "direct-text"})
        ab = tei_el("ab", {"type": "direct-text"}, direct)
        wrapper.append(ab)
        parent.append(wrapper)
        state.register(ab, direct, issue)
    for child in node:
        if not isinstance(child.tag, str) or child.tag.lower() in {"script", "style"}:
            continue
        wrapper = tei_el("div", {"type": "source-child", "rend": f"html-{child.tag.lower()}"})
        before = len(wrapper)
        _block(child, wrapper, issue, state)
        if len(wrapper) > before:
            parent.append(wrapper)


def _specs(config_path: Path) -> tuple[dict[str, object], list[IssueSpec]]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    specs = [IssueSpec(**value) for value in config["issues"]]
    if [spec.number for spec in specs] != list(range(1, 13)):
        raise ConversionError("Issue order must be exactly 1 through 12")
    if len({spec.ebook for spec in specs}) != 12:
        raise ConversionError("Project Gutenberg issue identities are not unique")
    return config, specs


def _content_nodes(source_path: Path) -> tuple[list[etree._Element], str, str]:
    document = html.fromstring(source_path.read_bytes())
    title = _normalize(document.xpath("string(//title)"))
    body = document.find("body")
    if body is None:
        raise ConversionError(f"Missing HTML body: {source_path}")
    nodes = [child for child in body if isinstance(child.tag, str) and child.get("id") not in {"pg-header", "pg-footer"} and child.tag.lower() not in {"header", "footer"}]
    end_marker = _normalize(document.xpath("string(//*[@id='pg-end-separator'])"))
    if not nodes or "END OF THE PROJECT GUTENBERG EBOOK" not in end_marker:
        raise ConversionError(f"Could not bound released edition text: {source_path}")
    return nodes, title, end_marker


def _verify_issue(raw_root: Path, spec: IssueSpec) -> dict[str, object]:
    issue_dir = raw_root / f"pg{spec.ebook}"
    html_path = issue_dir / f"pg{spec.ebook}-images.html"
    text_path = issue_dir / f"pg{spec.ebook}.txt"
    archive_path = issue_dir / f"pg{spec.ebook}-h.zip"
    for path, expected in ((html_path, spec.html_sha256), (text_path, spec.text_sha256), (archive_path, spec.archive_sha256)):
        actual = _sha256(path)
        if actual != expected:
            raise ConversionError(f"Retained source hash mismatch for {path}: {actual}")
    members: list[dict[str, object]] = []
    with zipfile.ZipFile(archive_path) as archive:
        names = sorted(name for name in archive.namelist() if not name.endswith("/"))
        expected_html = f"pg{spec.ebook}-images.html"
        if expected_html not in names or archive.read(expected_html) != html_path.read_bytes():
            raise ConversionError(f"HTML is not byte-identical to archive member for PG {spec.ebook}")
        for name in names:
            payload = archive.read(name)
            extracted = issue_dir / "archive" / Path(name)
            if extracted.read_bytes() != payload:
                raise ConversionError(f"Extracted archive member drift: PG {spec.ebook} {name}")
            members.append({"name": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    return {"ebook": spec.ebook, "month": spec.month, "source_title": _content_nodes(html_path)[1], "members": members}


def _header(specs: list[IssueSpec]) -> etree._Element:
    combined = hashlib.sha256("\n".join(spec.html_sha256 for spec in specs).encode("ascii")).hexdigest()
    header = stamp_header(
        title="The American Missionary, Volume 37 (1883)",
        author="American Missionary Association",
        contributors=[{"name": "Project Gutenberg and its credited distributed proofreaders", "role": "electronic transcription and production"}],
        source_url="https://www.gutenberg.org/ebooks/bookshelf/262",
        source_sha256=combined,
        print_source="The American Missionary, volume 37, numbers 1–12, January–December 1883.",
        rights_statement="Project Gutenberg states these issues are public domain in the USA. Rights elsewhere and Project Gutenberg redistribution conditions require separate review. This candidate is not publication clearance.",
    )
    encoding = tei_el("encodingDesc")
    project = tei_el("projectDesc")
    project.append(tei_el("p", text="Twelve retained proofread Project Gutenberg HTML issues are represented as one annual TEI volume with explicit issue boundaries and original order. Source wording, recurring matter, departments, articles, tables, lists, illustrations, page milestones, advertisements, indexes, transcriber notes, and terminal matter are retained without modernization."))
    encoding.append(project)
    header.append(encoding)
    return header


def _candidate_carriers(tree: etree._ElementTree) -> list[tuple[str, str]]:
    carriers = tree.xpath("//*[@xml:id and starts-with(@xml:id, 'amv37-src-B')]", namespaces=NS)
    results: list[tuple[str, str]] = []
    for node in carriers:
        clone = copy.deepcopy(node)
        for nested in clone.xpath(".//*[@xml:id and starts-with(@xml:id, 'amv37-src-B')]", namespaces=NS):
            nested.getparent().remove(nested)
        results.append((node.get(f"{{{XML_NS}}}id") or "", _normalize("".join(clone.itertext()))))
    return results


def convert(config_path: Path, raw_root: Path, output_path: Path, report_dir: Path) -> dict[str, object]:
    config, specs = _specs(config_path)
    issue_receipts = [_verify_issue(raw_root, spec) for spec in specs]
    root = tei_el("TEI", {"xml:lang": "en"})
    root.append(_header(specs))
    text = tei_el("text")
    body = tei_el("body")
    text.append(body)
    root.append(text)
    state = BuildState()
    issue_titles: list[str] = []
    end_markers: list[str] = []
    for spec in specs:
        source_path = raw_root / f"pg{spec.ebook}" / f"pg{spec.ebook}-images.html"
        nodes, source_title, end_marker = _content_nodes(source_path)
        issue_titles.append(source_title)
        end_markers.append(end_marker)
        issue_div = tei_el("div", {"type": "issue", "n": str(spec.number), "xml:id": f"amv37-issue-{spec.number:02d}"})
        issue_div.append(tei_el("head", text=f"Number {spec.number}: {spec.month} 1883 (Project Gutenberg {spec.ebook})"))
        body.append(issue_div)
        for node in nodes:
            wrapper = tei_el("div", {"type": "source-node", "rend": f"html-{node.tag.lower()}"})
            _block(node, wrapper, spec, state)
            if len(wrapper):
                issue_div.append(wrapper)
        marker = tei_el("p", {"rend": "project-gutenberg-end-marker"}, end_marker)
        marker_wrapper = tei_el("div", {"type": "source-wrapper", "rend": "project-gutenberg-end"})
        marker_wrapper.append(marker)
        issue_div.append(marker_wrapper)
        state.register(marker, end_marker, spec)
    tree = etree.ElementTree(root)
    carriers = _candidate_carriers(tree)
    candidate_ids = [carrier_id for carrier_id, _text in carriers]
    candidate_texts = [value for _carrier_id, value in carriers]
    dangling = [target for target in tree.xpath("//tei:ref[starts-with(@target, '#')]/@target", namespaces=NS) if target[1:] not in set(tree.xpath("//@xml:id", namespaces=NS))]
    errors: list[str] = []
    if candidate_ids != state.carrier_ids:
        errors.append("candidate carrier identity/order differs from source traversal")
    if candidate_texts != state.carrier_texts:
        mismatch = next((index for index, pair in enumerate(zip(candidate_texts, state.carrier_texts), start=1) if pair[0] != pair[1]), None)
        if mismatch is None:
            errors.append(f"candidate carrier text count differs from source traversal: {len(candidate_texts)} != {len(state.carrier_texts)}")
        else:
            errors.append(f"candidate carrier text differs at {mismatch}: {candidate_texts[mismatch - 1]!r} != {state.carrier_texts[mismatch - 1]!r}")
    if dangling:
        errors.append(f"dangling internal references: {dangling[:10]}")
    if len(tree.xpath("//tei:div[@type='issue']", namespaces=NS)) != 12:
        errors.append("candidate does not contain exactly twelve issue divisions")
    if errors:
        raise ConversionError("; ".join(errors))
    serialize(tree, output_path)
    xsd_errors = validate_file(output_path)
    if xsd_errors:
        raise ConversionError("TEI P5 XSD validation failed: " + "; ".join(xsd_errors[:8]))
    report_dir.mkdir(parents=True, exist_ok=True)
    stream_digest = _digest(state.carrier_texts)
    accounting = {
        "issue_count": 12,
        "issue_order": [spec.ebook for spec in specs],
        "issue_months": [spec.month for spec in specs],
        "issue_carrier_counts": state.issue_carriers,
        "source_carrier_count": len(state.carrier_texts),
        "candidate_carrier_count": len(carriers),
        "source_carrier_stream_sha256": stream_digest,
        "candidate_carrier_stream_sha256": _digest(candidate_texts),
        "omitted_source_carrier_ids": sorted(set(state.carrier_ids) - set(candidate_ids)),
        "duplicated_source_carrier_ids": sorted({value for value in candidate_ids if candidate_ids.count(value) > 1}),
        "dangling_internal_references": dangling,
        "page_break_count": len(tree.xpath("//tei:pb", namespaces=NS)),
        "table_count": len(tree.xpath("//tei:table", namespaces=NS)),
        "table_row_count": len(tree.xpath("//tei:table/tei:row", namespaces=NS)),
        "table_cell_count": len(tree.xpath("//tei:table/tei:row/tei:cell", namespaces=NS)),
        "list_item_count": len(tree.xpath("//tei:list/tei:item", namespaces=NS)),
        "graphic_count": len(tree.xpath("//tei:graphic", namespaces=NS)),
        "heading_count": len(tree.xpath("//tei:head[@type]", namespaces=NS)),
        "advertisement_division_count": len(tree.xpath("//tei:div[contains(concat(' ', normalize-space(@type), ' '), ' advertisement ')]", namespaces=NS)),
        "article_division_count": len(tree.xpath("//tei:div[contains(concat(' ', normalize-space(@type), ' '), ' article ')]", namespaces=NS)),
        "source_issue_titles": issue_titles,
        "end_marker_count": len(end_markers),
    }
    receipt = {
        "identity": config["identity"],
        "source_title": config["title"],
        "issuing_body": config["issuing_body"],
        "year": config["year"],
        "series_url": config["source_series_url"],
        "rights": config["rights"],
        "retrieved_at_utc": (raw_root / "retrieved_at_utc.txt").read_text(encoding="utf-8").strip(),
        "issue_receipts": issue_receipts,
        "issue_sources": [{"number": spec.number, "month": spec.month, "ebook": spec.ebook, "landing_url": f"https://www.gutenberg.org/ebooks/{spec.ebook}", "html_sha256": spec.html_sha256, "text_sha256": spec.text_sha256, "archive_sha256": spec.archive_sha256} for spec in specs],
        "raw_files": [
            {
                "path": path.relative_to(raw_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in sorted(value for value in raw_root.rglob("*") if value.is_file())
        ],
        "transformations": ["Bounded each issue between its Project Gutenberg start and end separators.", "Mapped all twelve issues in exact January–December order to explicit TEI issue divisions.", "Preserved block hierarchy, headings, paragraphs, page milestones, links, tables, lists, images, typography classes, advertisements, recurring matter, transcriber notes, and end markers without modernizing wording.", "Verified each retained HTML authority and every extracted archive member byte-for-byte against the retained ZIP."],
        "unresolved_questions": ["Project Gutenberg electronic repairs and additions are retained as surfaced; individual changes not enumerated by the transcribers remain unresolved.", "Human identity, annual completeness, edition, rights, textual, and editorial acceptance remain outside this technical packet."],
    }
    _write_json(report_dir / "receipt.json", receipt)
    _write_json(report_dir / "accounting.json", accounting)
    _write_json(report_dir / "validation.json", {"status": "technically_valid_nonaccepted_candidate", "candidate_sha256": _sha256(output_path), "tei_p5_xsd_valid": True, "tei_p5_xsd_errors": [], "accounting_errors": []})
    return accounting


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    accounting = convert(args.config, args.raw_root, args.output, args.report_dir)
    print(f"Wrote 12 issues with {accounting['candidate_carrier_count']} carriers, {accounting['page_break_count']} page milestones, {accounting['table_count']} tables, and {accounting['graphic_count']} graphics.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
