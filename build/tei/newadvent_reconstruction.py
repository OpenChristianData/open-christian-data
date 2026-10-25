"""Source-local readable TEI projection for retained New Advent HTML pages.

The page projection is deliberately separate from acquisition. Full LIB-025
package generation requires the complete bound envelope and image inventory.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin

import html5lib
from lxml import etree
from ocd_kernel.reconstruction.contract import SourceManifest
from build.tei.newadvent_source_tree import parse_source
from build.tei.newadvent_css import typography_map


TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
CONVERTER_ID = "ocd-lib025-newadvent-retained-html-to-tei"
CONVERTER_VERSION = "1"
HEADINGS = {f"h{number}" for number in range(1, 7)}
INLINE = {"a", "b", "big", "br", "em", "font", "greek", "i", "img", "small", "span", "strong", "sub", "sup", "u", "s", "strike", "center"}
STRUCTURAL = {"div", "p", "ul", "ol", "li", "dl", "dt", "dd", "blockquote", "pre", "table", "tr", "td", "th", "caption", "hr"}

def _parse_page(payload):
    if html5lib.__version__ != "1.1":
        raise ValueError("The bound HTML5 parser version is unavailable")
    decoded = payload.decode("utf-8", errors="strict")
    if any(0x80 <= ord(character) <= 0x9F for character in decoded):
        raise ValueError("Literal UTF-8 C1 controls need a separate source policy; numeric-reference handling is not applicable")
    if re.search(r"<\s*tbody\b", decoded, re.IGNORECASE):
        raise ValueError("Explicit source table row groups require a dedicated mapping")
    document = parse_source(decoded, treebuilder="etree")
    controls = []
    for node in document.iter():
        for value in [node.text or "", node.tail or "", *node.attrib.values()]:
            controls.extend(character for character in value if ord(character) < 32 and character not in "\t\n\r")
    if controls and (controls != ["\x17"] or hashlib.sha256(payload).hexdigest() != "0f381049ef0067dd6c14a92de8bb4dfdc98f81786a3f7e468bd02acf9ad5b01a"):
        raise ValueError("Unbound XML-forbidden source control or source drift")
    # Browser parsing inserts tbody even when no such source element exists.
    # Its empty-attribute carrier is transparent to TEI's direct table/row model.
    for group in list(document.iter("tbody")):
        if group.attrib or (group.text or "").strip() or any(child.tag != "tr" for child in group):
            raise ValueError("Unexpected implied table group content")
        parent = group.getparent()
        position = parent.index(group)
        leading = group.text or ""
        if position:
            parent[position - 1].tail = (parent[position - 1].tail or "") + leading
        else:
            parent.text = (parent.text or "") + leading
        children = list(group)
        for child in children:
            parent.insert(position, child)
            position += 1
        if children:
            children[-1].tail = (children[-1].tail or "") + (group.tail or "")
        parent.remove(group)
    return document


def _element(name, **attributes):
    return etree.Element(f"{{{TEI}}}{name}", **attributes)


def _append_text(target, value):
    if not value:
        return
    for position, part in enumerate(value.split("\x17")):
        if position:
            etree.SubElement(target, f"{{{TEI}}}g", ref="urn:unicode:U+0017").text = "\u2417"
        if len(target):
            target[-1].tail = (target[-1].tail or "") + part
        else:
            target.text = (target.text or "") + part


class PageProjection:
    def __init__(self, payload: bytes, url: str, identifier: str, images: dict[str, tuple[str, bytes]], link_targets: dict[str, str], unavailable_images: dict[str, int], css_bytes=b"", policy_bytes=None, reconciled_links=None):
        self.document = _parse_page(payload)
        self.typography = typography_map(self.document, css_bytes, policy_bytes)
        self.url = url
        self.identifier = identifier
        self.images = images
        self.unavailable_images = unavailable_images
        if set(images) & set(unavailable_images) or any(status not in {404, 410} for status in unavailable_images.values()):
            raise ValueError("Ambiguous retained/unavailable image scope")
        self.link_targets = link_targets
        self.reconciled_links = reconciled_links or {}
        self.ordinals = {node: number for number, node in enumerate(self.document.iter(), 1)}
        self.events = []

    @staticmethod
    def _block_em(source):
        return source.tag == "em" and any(child.tag in STRUCTURAL or child.tag in HEADINGS for child in source)

    def _bind(self, source, target):
        target.set(XML_ID, f"{self.identifier}-n{self.ordinals[source]}")
        target.set("ana", "html-" + source.tag)
        # The complete attribute spelling is retained with the readable node,
        # while link, image, table and list semantics also get native TEI attrs.
        rendering = {"b": "bold", "strong": "bold", "i": "italic", "em": "italic", "sup": "superscript", "sub": "subscript", "u": "underline", "s": "strikethrough", "strike": "strikethrough", "small": "small", "big": "large", "center": "center"}.get(source.tag, "")
        if source.attrib:
            rendering += (" " if rendering else "") + "html-attributes:" + json.dumps(dict(source.attrib), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if rendering:
            target.set("rend", rendering)
        css = []
        parent = source.getparent()
        if parent is not None and self._block_em(parent) and parent.getparent().tag == "blockquote":
            css.append("font-style:italic;")
        if source.get("id") in {"springfield2", "ogdenville"}:
            for ancestor in reversed(list(source.iterancestors())):
                if ancestor.tag in {"em", "i"}:
                    css.append("font-style:italic;")
                elif ancestor.tag in {"strong", "b"}:
                    css.append("font-weight:bold;")
        if source.tag == "font" and source.get("size"):
            spelling = source.get("size").strip()
            digits = spelling[1:] if spelling.startswith(("+", "-")) else spelling
            if not digits.isascii() or not digits.isdigit():
                raise ValueError(f"Unmapped legacy font size: {spelling!r}")
            size = int(spelling) + (3 if spelling.startswith(("+", "-")) else 0)
            css.append("font-size:" + ("x-small", "small", "medium", "large", "x-large", "xx-large", "xxx-large")[min(7, max(1, size)) - 1] + ";")
        if source.tag == "font" and source.get("color"):
            color = source.get("color").lower()
            if color != "red" and re.fullmatch(r"#[0-9a-f]{6}", color) is None:
                raise ValueError("Unmapped legacy font color requires source-led interpretation")
            css.append("color:" + color + ";")
        if source.get("style") is not None:
            css.append(source.get("style"))
        appearance = self.typography[source]
        if appearance["gates"]:
            raise ValueError(f"Unresolved source typography at {self.url} {source.getroottree().getpath(source)}: {appearance['gates']}")
        if appearance["declarations"]:
            if css and not css[-1].endswith(";"):
                css.append(";")
            css.append("".join(f"{key}:{value};" for key, value in sorted(appearance["declarations"].items())))
        if css:
            target.set("style", "".join(css))
        if source.get("lang"):
            target.set("{http://www.w3.org/XML/1998/namespace}lang", source.get("lang"))
        elif source.get("id") in {"springfield2", "ogdenville"}:
            for ancestor in source.iterancestors():
                if ancestor.get("lang"):
                    target.set("{http://www.w3.org/XML/1998/namespace}lang", ancestor.get("lang"))
                    break
        self.events.append({"source_address": source.getroottree().getpath(source), "source_tag": source.tag, "source_attributes": dict(source.attrib), "tei_id": target.get(XML_ID), "tei_tag": etree.QName(target).localname})

    def _inline(self, source):
        tag = source.tag
        if tag == "a":
            target = _element("ref", target=urljoin(self.url, source.get("href"))) if source.get("href") is not None else _element("seg")
            if source.get("href") is not None:
                resolved = urljoin(self.url, source.get("href"))
                base, fragment = urldefrag(resolved)
                key = base + ("#" + unquote(fragment) if fragment else "")
                if resolved in self.reconciled_links:
                    target.set("target", "#" + self.reconciled_links[resolved])
                    target.set("corresp", resolved)
                    target.set("type", "source-href-reconciled")
                elif resolved in self.images:
                    media, binary = self.images[resolved]
                    target.set("target", f"data:{media};base64," + base64.b64encode(binary).decode("ascii"))
                    target.set("corresp", resolved)
                elif key in self.link_targets:
                    target.set("target", "#" + self.link_targets[key])
                    target.set("corresp", resolved)
        elif tag == "br":
            target = _element("lb")
        elif tag == "img":
            image_url = urljoin(self.url, source.get("src", ""))
            if image_url not in self.images and image_url not in self.unavailable_images:
                raise ValueError(f"Required source image is not retained: {image_url}")
            target = _element("figure")
            if image_url in self.unavailable_images:
                gap = etree.SubElement(target, f"{{{TEI}}}gap", reason="unavailable", corresp=image_url)
                etree.SubElement(gap, f"{{{TEI}}}desc").text = f"Source image unavailable at acquisition (HTTP {self.unavailable_images[image_url]})."
            else:
                media_type, payload = self.images[image_url]
                etree.SubElement(target, f"{{{TEI}}}graphic", url="data:" + media_type + ";base64," + base64.b64encode(payload).decode("ascii"))
            if "alt" in source.attrib:
                etree.SubElement(target, f"{{{TEI}}}figDesc").text = source.get("alt")
        elif tag in {"b", "strong", "i", "em", "big", "small", "font", "sup", "sub", "u", "s", "strike", "center"}:
            target = _element("hi")
        else:
            target = _element("seg")
        if tag == "greek":
            target.set("type", "source-greek")
        self._bind(source, target)
        if tag != "img":
            self._mixed(source, target)
        return target

    def _mixed(self, source, target):
        _append_text(target, source.text)
        for child in source:
            if not isinstance(child.tag, str):
                # Comments are retained in source accounting, not displayed as prose.
                _append_text(target, child.tail)
                continue
            if child.tag in {"script", "style"}:
                _append_text(target, child.tail)
                continue
            if self._block_em(child) and source.tag == "blockquote":
                # Quote has paragraph content but cannot contain a TEI div.
                # Bind the source formatting carrier to an explicit interval;
                # the paragraphs remain native readable quote children.
                if child.attrib or (child.text or "").strip() or any(
                    (isinstance(node.tag, str) and node.tag not in {"p", "script", "style"})
                    or (node.tail or "").strip() for node in child
                ):
                    raise ValueError("Unsupported block-emphasis interval content")
                group = etree.SubElement(target, f"{{{TEI}}}spanGrp", type="source-formatting")
                span = etree.SubElement(group, f"{{{TEI}}}span")
                self._bind(child, span)
                identity = span.get(XML_ID)
                span.set("from", "#" + identity + "-start")
                span.set("to", "#" + identity + "-end")
                start = etree.SubElement(target, f"{{{TEI}}}anchor", **{XML_ID: identity + "-start"})
                contents = _element("ab")
                self._mixed(child, contents)
                start.tail = contents.text
                target.extend(list(contents))
                etree.SubElement(target, f"{{{TEI}}}anchor", **{XML_ID: identity + "-end"})
                _append_text(target, child.tail)
                continue
            projected = self._node(child)
            if source.tag in {"ul", "ol"} and child.tag in {"ul", "ol"}:
                # Preserve the browser DOM's direct nested list without inventing
                # attachment to the preceding source item. TEI requires an item.
                wrapper = etree.SubElement(target, f"{{{TEI}}}item", ana="source-direct-nested-list", rend="unnumbered")
                wrapper.append(projected)
            else:
                target.append(projected)
            _append_text(target, child.tail)

    def _flow(self, source, target):
        stack = [(0, target)]
        run = None
        def text(value):
            nonlocal run
            if value:
                if run is None:
                    wrapper = etree.SubElement(stack[-1][1], f"{{{TEI}}}div", type="source-inline-run")
                    run = etree.SubElement(wrapper, f"{{{TEI}}}ab")
                _append_text(run, value)
        text(source.text)
        for child in source:
            if not isinstance(child.tag, str) or child.tag in {"script", "style"}:
                text(child.tail)
                continue
            if child.tag in HEADINGS:
                level = int(child.tag[1])
                while len(stack) > 1 and stack[-1][0] >= level:
                    stack.pop()
                section = etree.SubElement(stack[-1][1], f"{{{TEI}}}div", type="source-section", subtype=child.tag)
                head = _element("head", type=child.tag)
                self._bind(child, head)
                self._mixed(child, head)
                section.append(head)
                stack.append((level, section))
                run = None
            elif child.tag in INLINE and not self._block_em(child):
                if run is None:
                    wrapper = etree.SubElement(stack[-1][1], f"{{{TEI}}}div", type="source-inline-run")
                    run = etree.SubElement(wrapper, f"{{{TEI}}}ab")
                run.append(self._inline(child))
            else:
                wrapper = etree.SubElement(stack[-1][1], f"{{{TEI}}}div", type="source-block")
                wrapper.append(self._node(child))
                run = None
            text(child.tail)

    def _list_flow(self, source, target):
        run = None
        def text(value):
            nonlocal run
            if not value:
                return
            if run is None and not value.strip():
                _append_text(target, value)
                return
            if run is None:
                run = etree.SubElement(target, f"{{{TEI}}}item", ana="source-unlisted-content", rend="unnumbered")
            _append_text(run, value)
        text(source.text)
        for child in source:
            if not isinstance(child.tag, str) or child.tag in {"script", "style"}:
                text(child.tail)
                continue
            if child.tag == "li":
                target.append(self._node(child))
                run = None
            elif child.tag in {"ul", "ol"}:
                wrapper = etree.SubElement(target, f"{{{TEI}}}item", ana="source-direct-nested-list", rend="unnumbered")
                wrapper.append(self._node(child))
                run = None
            else:
                if run is None:
                    run = etree.SubElement(target, f"{{{TEI}}}item", ana="source-unlisted-content", rend="unnumbered")
                run.append(self._node(child))
            text(child.tail)

    def _node(self, source):
        tag = source.tag
        if self._block_em(source):
            if source.getparent().tag != "div":
                raise ValueError("Unsupported block-emphasis source parent")
            target = _element("div")
            self._bind(source, target)
            self._flow(source, target)
            return target
        if tag in INLINE:
            return self._inline(source)
        if tag not in STRUCTURAL:
            raise ValueError(f"Unsupported source element {tag!r} at {self.url} {source.getroottree().getpath(source)}")
        name = {"div": "div", "p": "p", "ul": "list", "ol": "list", "li": "item", "dl": "list", "dt": "label", "dd": "item", "blockquote": "quote", "pre": "ab", "table": "table", "tr": "row", "td": "cell", "th": "cell", "caption": "head", "hr": "milestone"}[tag]
        empty_div = tag == "div" and not len(source) and not (source.text or "").strip()
        quoted_list_div = tag == "div" and source.getparent().tag == "blockquote" and source.get("class") == "bulletlist"
        if empty_div:
            name = "milestone"
        elif quoted_list_div:
            name = "ab"
        target = _element(name)
        if empty_div:
            target.set("unit", "empty-html-div")
        if tag in {"ul", "ol"}:
            target.set("type", "ordered" if tag == "ol" else "unordered")
            if source.get("start"):
                target.set("n", source.get("start"))
        if tag == "dl":
            target.set("type", "gloss")
        if tag == "li" and source.get("value"):
            target.set("n", source.get("value"))
        if tag == "hr":
            target.set("unit", "horizontal-rule")
        if tag == "th":
            target.set("role", "label")
        if tag in {"td", "th"}:
            for source_attr, tei_attr in (("colspan", "cols"), ("rowspan", "rows")):
                if source.get(source_attr):
                    target.set(tei_attr, source.get(source_attr))
        self._bind(source, target)
        if tag == "div" and not empty_div and not quoted_list_div:
            self._flow(source, target)
        elif tag in {"ul", "ol"}:
            self._list_flow(source, target)
        else:
            self._mixed(source, target)
        if tag == "tr" and not len(source):
            etree.SubElement(target, f"{{{TEI}}}cell", ana="source-empty-row")
        if tag == "li" and source.getparent().tag not in {"ul", "ol"}:
            wrapper = _element("list", type="unordered", ana="source-orphan-list-item")
            wrapper.append(target)
            return wrapper
        return target

    def project(self):
        mains = self.document.xpath("//*[@id='springfield2']")
        footers = self.document.xpath("//*[@id='ogdenville']")
        if len(mains) != 1 or len(footers) != 1:
            raise ValueError(f"Source page main/footer identity is ambiguous: {self.url}")
        if mains[0] in footers[0].iterancestors() or footers[0] in mains[0].iterancestors():
            raise ValueError(f"Source page main/footer regions overlap: {self.url}")
        result = _element("div", type="source-page")
        result.set(XML_ID, self.identifier)
        result.set("corresp", self.url)
        for source in (mains[0], footers[0]):
            result.append(self._node(source))
        return result


def project_page(payload: bytes, url: str, identifier: str, images: dict[str, tuple[str, bytes]] | None = None, link_targets: dict[str, str] | None = None, unavailable_images: dict[str, int] | None = None, *, css_bytes=b"", policy_bytes=None, reconciled_links=None):
    projection = PageProjection(payload, url, identifier, images or {}, link_targets or {}, unavailable_images or {}, css_bytes, policy_bytes, reconciled_links)
    result = projection.project()
    return result, {"source_sha256": hashlib.sha256(payload).hexdigest(), "events": projection.events}


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _producer_closure(root: Path) -> str:
    paths = ["build/__init__.py", "build/tei/__init__.py", "build/tei/newadvent_reconstruction.py", "build/tei/newadvent_source_tree.py", "build/tei/newadvent_css.py", "ocd_kernel/__init__.py", "ocd_kernel/reconstruction/__init__.py", "ocd_kernel/reconstruction/contract.py"]
    return _sha(_canonical([{"path": path, "sha256": _sha((root / path).read_bytes())} for path in sorted(paths)]))


def _header(profile, graph_sha):
    header = _element("teiHeader")
    description = etree.SubElement(header, f"{{{TEI}}}fileDesc")
    titles = etree.SubElement(description, f"{{{TEI}}}titleStmt")
    etree.SubElement(titles, f"{{{TEI}}}title").text = profile["identity"]["title"]
    publication = etree.SubElement(description, f"{{{TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI}}}publisher").text = "Open Christian Data"
    availability = etree.SubElement(publication, f"{{{TEI}}}availability", status="restricted")
    etree.SubElement(availability, f"{{{TEI}}}p").text = "Nonaccepted candidate. Human acceptance and public publication are not authorized by this reconstruction."
    sources = etree.SubElement(description, f"{{{TEI}}}sourceDesc")
    bibl = etree.SubElement(sources, f"{{{TEI}}}bibl")
    etree.SubElement(bibl, f"{{{TEI}}}title").text = "The Catholic Encyclopedia — New Advent web transcription"
    etree.SubElement(bibl, f"{{{TEI}}}publisher").text = "New Advent"
    etree.SubElement(bibl, f"{{{TEI}}}ptr", target="https://www.newadvent.org/cathen/")
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="retained-index-graph-sha256").text = graph_sha
    encoding = etree.SubElement(header, f"{{{TEI}}}encodingDesc")
    etree.SubElement(encoding, f"{{{TEI}}}p").text = profile["mapping_summary"]
    return header


def _bound_reconciled_links(source_manifest, profile):
    """Resolve only a named, hash-bound policy authority into retained TEI IDs."""
    name = profile.get("link_reconciliation_policy_authority")
    policy_authorities = {row["name"] for row in source_manifest.record["authorities"] if row["role"] == "source-link-reconciliation-policy"}
    if policy_authorities != ({name} if name else set()):
        raise ValueError("Link reconciliation policy authority inventory differs")
    if not name:
        return {}
    policy = json.loads(source_manifest.authority_path(name).read_bytes())
    if policy.get("contract") != "ocd-lib025-newadvent-link-reconciliation-v1" or policy.get("work_id") != "catholic-encyclopedia-vol01":
        raise ValueError("Invalid link reconciliation policy identity")
    retained = {row["url"]: row["tei_id"] for row in profile["html_members"]}
    failed = {row["url"] for row in profile["failed_acquisitions"] if row["kind"] == "html"}
    result = {}
    for row in policy["mappings"]:
        source, target = row["source_url"], row["target_url"]
        if source not in failed or target not in retained or source in result:
            raise ValueError("Link reconciliation must join unique failed HTML URLs to retained members")
        result[source] = retained[target]
    unmapped = [row["source_url"] for row in policy["unmapped"]]
    if len(unmapped) != len(set(unmapped)) or set(unmapped) - failed or set(unmapped) & set(result):
        raise ValueError("Invalid unmapped link reconciliation entries")
    return result


def _convert(source_manifest: SourceManifest):
    source_manifest.verify()
    if source_manifest.record.get("ticket_id") != "LIB-025" or source_manifest.record.get("work_id") != "catholic-encyclopedia-vol01":
        raise ValueError("LIB-025 work identity mismatch")
    if _producer_closure(source_manifest.repository_root) != source_manifest.record.get("producer_import_closure_sha256"):
        raise ValueError("LIB-025 producer closure drifted")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    profile = json.loads(profile_bytes)
    if profile.get("contract") != "ocd-lib025-newadvent-profile-v1" or profile.get("declared_envelope_accounted") is not True:
        raise ValueError("Accounted retained LIB-025 profile is required")
    graph_bytes = source_manifest.authority_path("source-graph").read_bytes()
    graph = json.loads(graph_bytes)
    if graph["missing_linked_indexes"] or profile["graph_sha256"] != _sha(graph_bytes):
        raise ValueError("LIB-025 source graph binding is incomplete")
    expected_urls = list(dict.fromkeys([member["url"] for member in graph["members"]] + graph["article_urls_in_first_occurrence_order"]))
    failures = profile["failed_acquisitions"]
    unavailable = {item["url"]: item for item in failures}
    missing_html = {url for url, item in unavailable.items() if item["kind"] == "html"}
    missing_images = {url: item["http_status"] for url, item in unavailable.items() if item["kind"] == "image"}
    scope = profile["expression_scope"]
    manifest_scope = json.loads(source_manifest.path.read_bytes())
    if len(unavailable) != len(failures) or set(unavailable) != missing_html | set(missing_images) or any(item["http_status"] not in {404, 410} for item in failures):
        raise ValueError("Unavailable member identities or statuses are invalid")
    if scope != manifest_scope.get("expression_scope") or failures != manifest_scope.get("failed_acquisitions") or scope.get("whole_work_complete") is not False or scope.get("status") != ("partial" if failures else "retained-cohort") or profile["declared_envelope_retained"] is not (not failures):
        raise ValueError("Partial-source scope or completeness claim drifted")
    if scope["expected_html_urls"] != expected_urls or scope["unavailable_urls"] != list(unavailable) or not missing_html <= set(expected_urls):
        raise ValueError("Unavailable members are outside the source envelope")
    if [member["url"] for member in profile["html_members"]] != [url for url in expected_urls if url not in missing_html] or scope["included_html_urls"] != [member["url"] for member in profile["html_members"]]:
        raise ValueError("LIB-025 complete member envelope or order drifted")
    if scope["included_image_urls"] != [member["url"] for member in profile["image_members"]] or set(scope["expected_image_urls"]) != set(scope["included_image_urls"]) | set(missing_images) or set(scope["included_image_urls"]) & set(missing_images):
        raise ValueError("Image included/unavailable partition drifted")
    authorities = {row["name"]: row for row in source_manifest.record["authorities"]}
    if {row["response_authority"] for row in failures} != {name for name, row in authorities.items() if row["role"] == "failed-acquisition-evidence"}:
        raise ValueError("Failed response authority inventory drifted")
    for item in failures:
        receipt_path = source_manifest.authority_path(item["receipt_authority"])
        receipt = json.loads(receipt_path.read_bytes())
        matches = [row for row in receipt["members"] if row["url"] == item["url"] and row["status"] == "failed" and row.get("http_status") == item["http_status"]]
        if len(matches) != 1 or "error_response" not in matches[0]:
            raise ValueError("Unavailable member lacks an exact failed acquisition")
        error = matches[0]["error_response"]
        body = source_manifest.authority_path(item["response_authority"])
        if error.get("final_url") != item["url"] or (receipt_path.parent / error["path"]).resolve() != body.resolve() or _sha(body.read_bytes()) != error["sha256"] or body.stat().st_size != error["bytes"]:
            raise ValueError("Unavailable response bytes or URL drifted")
    reconciled_links = _bound_reconciled_links(source_manifest, profile)
    image_sources = {member["url"]: (member["media_type"], source_manifest.authority_path(member["authority"]).read_bytes()) for member in profile["image_members"]}
    stylesheets = {member["url"]: source_manifest.authority_path(member["authority"]).read_bytes() for member in profile["stylesheet_members"]}
    typography_policy = source_manifest.authority_path(profile["typography_policy_authority"]).read_bytes() if profile.get("typography_policy_authority") else None
    page_stylesheets = {}
    link_targets = {member["url"]: member["tei_id"] for member in profile["html_members"]}
    link_targets.update({item["url"]: f"newadvent-unavailable-{number:04d}" for number, item in enumerate(failures, 1)})
    for member in profile["html_members"]:
        document = _parse_page(source_manifest.authority_path(member["authority"]).read_bytes())
        linked_css = []
        for link in document.xpath("//link[@href]"):
            if "stylesheet" in link.get("rel", "").lower().split():
                css_url = urljoin(member["url"], link.get("href"))
                if css_url not in stylesheets:
                    raise ValueError("Source stylesheet is not retained")
                if stylesheets[css_url]:
                    linked_css.append(stylesheets[css_url])
        if len(linked_css) > 1:
            raise ValueError("Multiple source stylesheets require cascade review")
        page_stylesheets[member["url"]] = linked_css[0] if linked_css else b""
        for number, node in enumerate(document.iter(), 1):
            if not isinstance(node.tag, str) or node.tag in {"script", "style"} or not any(parent.get("id") in {"springfield2", "ogdenville"} for parent in [node, *node.iterancestors()]):
                continue
            for fragment in (node.get("id"), node.get("name") if node.tag == "a" else None):
                if fragment:
                    link_targets.setdefault(member["url"] + "#" + fragment, f"{member['tei_id']}-n{number}")
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    root.set(XML_ID, "catholic-encyclopedia-lib025-candidate")
    root.append(_header(profile, _sha(graph_bytes)))
    text = etree.SubElement(root, f"{{{TEI}}}text")
    body = etree.SubElement(text, f"{{{TEI}}}body")
    accounting = []
    for member in profile["html_members"]:
        payload = source_manifest.authority_path(member["authority"]).read_bytes()
        projected, evidence = project_page(payload, member["url"], member["tei_id"], image_sources, link_targets, missing_images, css_bytes=page_stylesheets[member["url"]], policy_bytes=typography_policy, reconciled_links=reconciled_links)
        body.append(projected)
        accounting.append({"authority": member["authority"], "url": member["url"], **evidence})
    if failures:
        notice = etree.SubElement(body, f"{{{TEI}}}div", type="unavailable-source-members")
        etree.SubElement(notice, f"{{{TEI}}}head").text = "Unavailable source members — partial retained cohort"
        listing = etree.SubElement(notice, f"{{{TEI}}}list")
        for number, item in enumerate(failures, 1):
            entry = etree.SubElement(listing, f"{{{TEI}}}item")
            entry.set(XML_ID, f"newadvent-unavailable-{number:04d}")
            etree.SubElement(entry, f"{{{TEI}}}ref", target=item["url"]).text = item["url"]
            gap = etree.SubElement(entry, f"{{{TEI}}}gap", reason="unavailable", corresp=item["url"])
            etree.SubElement(gap, f"{{{TEI}}}desc").text = f"Requested {item['kind']} source unavailable at acquisition (HTTP {item['http_status']}); not included as retained source content."
    provenance = {"contract": "ocd-lib025-newadvent-provenance-v1", "work_id": "catholic-encyclopedia-vol01", "source_manifest_sha256": source_manifest.sha256, "profile_sha256": _sha(profile_bytes), "source_graph_sha256": _sha(graph_bytes), "identity": profile["identity"], "status": "nonaccepted", "publication": False, "legacy_generated_json_used_as_authority": False}
    provenance.update(expression_scope=scope, failed_acquisitions=failures)
    return {
        "content.tei.xml": etree.tostring(root, encoding="UTF-8", xml_declaration=True),
        "source-accountability.json": _canonical({"contract": "ocd-lib025-newadvent-accountability-v1", "members": accounting, "source_envelope": profile["source_envelope"], "image_members": profile["image_members"], "expression_scope": scope, "failed_acquisitions": failures}),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(row) for row in profile["unresolved"]),
        "README.source.md": source_manifest.authority_path("source-attribution-readme").read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
