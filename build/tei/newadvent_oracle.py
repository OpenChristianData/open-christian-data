"""Independent readable-tree checks for New Advent page projections.

No producer imports. The reader compares source-native node identities, ordered
mixed content and source-defined heading intervals against the actual TEI.
Shared HTML5 parsing remains an explicit assumption to corroborate at the
complete-envelope boundary, not a claim of blind source discovery.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from html import unescape
from io import BytesIO
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

import html5lib
from build.tei.newadvent_css_oracle import expected_typography_map
from lxml import etree
from PIL import Image
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from build.tei.newadvent_source_tree import interpreted_tree_bytes, parse_source


NS = "{http://www.tei-c.org/ns/1.0}"
ID = "{http://www.w3.org/XML/1998/namespace}id"
ORACLE_ID = "ocd-lib025-newadvent-independent-html-tei-oracle"
ORACLE_VERSION = "1"


class _LexicalRegions(HTMLParser):
    """Corroborate decoded region text without libxml's DOM recovery."""
    def __init__(self, source_text):
        super().__init__(convert_charrefs=False)
        self.source_text = source_text
        self.line_offsets = [0, *(match.end() for match in re.finditer("\n", source_text))]
        self.stack = []
        self.parts = {"springfield2": [], "ogdenville": []}

    def handle_starttag(self, tag, attrs):
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append((tag, dict(attrs).get("id")))

    def handle_endtag(self, tag):
        for position in range(len(self.stack) - 1, -1, -1):
            if self.stack[position][0] == tag:
                del self.stack[position:]
                return

    def handle_data(self, data):
        if any(tag in {"script", "style"} for tag, _ in self.stack):
            return
        for _, identifier in self.stack:
            if identifier in self.parts:
                self.parts[identifier].append(data)
                return

    def handle_entityref(self, name):
        line, column = self.getpos()
        start = self.line_offsets[line - 1] + column
        end = start + 1 + len(name)
        spelling = self.source_text[start:end]
        if self.source_text[end:end + 1] == ";":
            spelling += ";"
        self.handle_data(unescape(spelling))

    def handle_charref(self, name):
        number = int(name[1:], 16) if name.lower().startswith("x") else int(name)
        # HTML5 retains these numeric C0 references; html.unescape drops them.
        value = chr(number) if 0 < number < 32 else unescape("&#" + name + ";")
        self.handle_data(value)


def _check_lexical_text(payload, regions):
    decoded = payload.decode("utf-8")
    reader = _LexicalRegions(decoded)
    reader.feed(decoded)
    reader.close()
    def text(node):
        parts = [node.text or ""]
        for child in node:
            if isinstance(child.tag, str) and child.tag not in {"script", "style"}:
                parts.append(text(child))
            parts.append(child.tail or "")
        return "".join(parts)
    for region in regions:
        lexical = "".join(reader.parts[region.get("id")]).replace("\r\n", "\n").replace("\r", "\n")
        dom = text(region)
        if lexical != dom:
            offset = next((position for position, (left, right) in enumerate(zip(lexical, dom)) if left != right), min(len(lexical), len(dom)))
            raise ValueError(f"Independent lexical/DOM source text differs in {region.get('id')} at {offset}: lexical={lexical[max(0, offset-20):offset+30]!r}, DOM={dom[max(0, offset-20):offset+30]!r}; lengths={len(lexical)}/{len(dom)}")


def _merged(items):
    result = []
    for item in items:
        if isinstance(item, str) and result and isinstance(result[-1], str):
            result[-1] += item
        elif item != "":
            result.append(item)
    return result


def _read_document(payload):
    if html5lib.__version__ != "1.1":
        raise ValueError("Independent reader requires the bound HTML5 parser version")
    decoded = payload.decode("utf-8")
    if re.search(r"<\s*tbody\b", decoded, re.I):
        raise ValueError("Explicit source table row groups require independent mapping")
    source = parse_source(decoded, treebuilder="dom")
    forbidden = [ord(c) for node in source.iter() for value in [node.text or "", node.tail or "", *node.attrib.values()] for c in value if ord(c) < 32 and c not in "\t\n\r"]
    if forbidden and (forbidden != [23] or hashlib.sha256(payload).hexdigest() != "0f381049ef0067dd6c14a92de8bb4dfdc98f81786a3f7e468bd02acf9ad5b01a"):
        raise ValueError("Independent reader rejects unbound source control or source drift")
    for table in source.iter("table"):
        for group in list(table):
            if group.tag != "tbody":
                continue
            if group.attrib or (group.text or "").strip() or any(row.tag != "tr" for row in group):
                raise ValueError("Implied HTML table group is not transparent")
            previous = group.getprevious()
            if previous is None:
                table.text = (table.text or "") + (group.text or "")
            else:
                previous.tail = (previous.tail or "") + (group.text or "")
            last = previous
            for row in list(group):
                group.addprevious(row)
                last = row
            if last is not None:
                last.tail = (last.tail or "") + (group.tail or "")
            table.remove(group)
    return source


def verify_page(payload: bytes, url: str, identifier: str, candidate: etree._Element, images: dict[str, tuple[str, bytes]] | None = None, link_targets: dict[str, str] | None = None, unavailable_images: dict[str, int] | None = None, *, css_bytes=b"", policy_bytes=None, reconciled_links=None) -> dict:
    image_sources = images or {}
    missing_images = unavailable_images or {}
    if set(image_sources).intersection(missing_images) or any(value not in (404, 410) for value in missing_images.values()):
        raise ValueError("Retained and unavailable image identities overlap or status is unsupported")
    source = _read_document(payload)
    typography = expected_typography_map(source, css_bytes, policy_bytes)
    all_nodes = list(source.iter())
    source_ids = {node: f"{identifier}-n{number}" for number, node in enumerate(all_nodes, 1)}
    regions = []
    for name in ("springfield2", "ogdenville"):
        found = [node for node in all_nodes if isinstance(node.tag, str) and node.get("id") == name]
        if len(found) != 1:
            raise ValueError("Source main/footer selection is ambiguous")
        regions.append(found[0])
    if regions[0] in regions[1].iterancestors() or regions[1] in regions[0].iterancestors():
        raise ValueError("Source main/footer regions overlap")
    _check_lexical_text(payload, regions)
    if candidate.tag != NS + "div" or dict(candidate.attrib) != {"type": "source-page", ID: identifier, "corresp": url}:
        raise ValueError("Candidate page identity drifted")
    expected_nodes = []
    for region in regions:
        for node in region.iter():
            if not isinstance(node.tag, str) or node.tag in {"script", "style"}:
                continue
            if any(parent.tag in {"script", "style"} for parent in node.iterancestors()):
                continue
            expected_nodes.append(node)
    block_em = {node for node in expected_nodes if node.tag == "em" and any(
        child.tag in {"div", "p", "ul", "ol", "li", "dl", "dt", "dd", "blockquote", "pre", "table", "tr", "td", "th", "caption", "hr", "h1", "h2", "h3", "h4", "h5", "h6"} for child in node)}
    span_sources = {node for node in block_em if node.getparent().tag == "blockquote"}
    anchor_ids = {source_ids[node] + suffix for node in span_sources for suffix in ("-start", "-end")}
    anchors = [node for node in candidate.iterdescendants() if node.get(ID) in anchor_ids]
    if len(anchors) != len(anchor_ids) or {node.get(ID) for node in anchors} != anchor_ids:
        raise ValueError("Missing or duplicate emphasis anchors")
    for anchor in anchors:
        if anchor.tag != NS + "anchor" or dict(anchor.attrib) != {ID: anchor.get(ID)} or len(anchor) or anchor.text:
            raise ValueError("Emphasis anchor structure drifted")
    targets = [node for node in candidate.iterdescendants() if node.get(ID) and node.get(ID) not in anchor_ids]
    if [node.get(ID) for node in targets] != [source_ids[node] for node in expected_nodes]:
        raise ValueError("Source node omission, duplication or order drifted")
    by_id = {node.get(ID): node for node in targets}
    anchor_by_id = {node.get(ID): node for node in anchors}
    intervals = {}
    for original in span_sources:
        if original.attrib or (original.text or "").strip() or any(
            (isinstance(child.tag, str) and child.tag not in {"p", "script", "style"})
            or (child.tail or "").strip() for child in original
        ):
            raise ValueError("Unsupported paragraph emphasis interval")
        identity = source_ids[original]
        span = by_id[identity]
        group = span.getparent()
        parent = group.getparent()
        start, end = (anchor_by_id[identity + suffix] for suffix in ("-start", "-end"))
        if (group.tag != NS + "spanGrp" or dict(group.attrib) != {"type": "source-formatting"}
                or len(group) != 1 or group.text or group.tail or span.text or span.tail or len(span)
                or parent is not by_id[source_ids[original.getparent()]]
                or start.getparent() is not parent or end.getparent() is not parent
                or group.getnext() is not start or parent.index(start) >= parent.index(end)):
            raise ValueError("Emphasis interval boundary or physical parent drifted")
        intervals[group] = (identity, start, end)
    mapping = {"div": "div", "p": "p", "ul": "list", "ol": "list", "li": "item", "dl": "list", "dt": "label", "dd": "item", "blockquote": "quote", "pre": "ab", "table": "table", "tr": "row", "td": "cell", "th": "cell", "caption": "head", "hr": "milestone", "span": "seg", "br": "lb", "img": "figure"}
    formatting = {"b": "bold", "strong": "bold", "i": "italic", "em": "italic", "sup": "superscript", "sub": "subscript", "u": "underline", "s": "strikethrough", "strike": "strikethrough", "small": "small", "big": "large", "center": "center"}
    for original in expected_nodes:
        target = by_id[source_ids[original]]
        tag = original.tag
        attrs = {ID: source_ids[original], "ana": "html-" + tag}
        rend = formatting.get(tag, "")
        if original.attrib:
            rend += (" " if rend else "") + "html-attributes:" + json.dumps(dict(original.attrib), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if rend:
            attrs["rend"] = rend
        presentation = ""
        if original.getparent() in span_sources:
            presentation += "font-style:italic;"
        if original.get("id") in {"springfield2", "ogdenville"}:
            context = list(original.iterancestors())
            for ancestor in context[::-1]:
                if ancestor.tag in {"i", "em"}:
                    presentation += "font-style:italic;"
                elif ancestor.tag in {"b", "strong"}:
                    presentation += "font-weight:bold;"
        if tag == "font" and original.get("size"):
            value = original.get("size").strip()
            match = re.fullmatch(r"([+-]?)([0-9]+)", value)
            if not match:
                raise ValueError("Unmapped legacy font size")
            number = int(match[2])
            if match[1]:
                number = 3 + number if match[1] == "+" else 3 - number
            keyword = {1: "x-small", 2: "small", 3: "medium", 4: "large", 5: "x-large", 6: "xx-large", 7: "xxx-large"}[max(1, min(number, 7))]
            presentation += f"font-size:{keyword};"
        if tag == "font" and original.get("color"):
            color = original.get("color").casefold()
            if color != "red" and not (len(color) == 7 and color[0] == "#" and all(character in "0123456789abcdef" for character in color[1:])):
                raise ValueError("Unmapped legacy font color")
            presentation += "color:" + color + ";"
        if original.get("style") is not None:
            presentation += original.get("style")
        appearance = typography[original]
        if appearance["gates"]:
            raise ValueError(f"Unresolved source typography at {source_ids[original]}: {appearance['gates']}")
        if appearance["declarations"]:
            if presentation and not presentation.endswith(";"):
                presentation += ";"
            presentation += "".join(f"{name}:{value};" for name, value in sorted(appearance["declarations"].items()))
        if presentation or "style" in original.attrib:
            attrs["style"] = presentation
        if original.get("lang"):
            attrs["{http://www.w3.org/XML/1998/namespace}lang"] = original.get("lang")
        elif original.get("id") in {"springfield2", "ogdenville"}:
            inherited_language = next((ancestor.get("lang") for ancestor in original.iterancestors() if ancestor.get("lang")), None)
            if inherited_language:
                attrs["{http://www.w3.org/XML/1998/namespace}lang"] = inherited_language
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            expected_tag = "head"
            attrs["type"] = tag
        elif tag == "a":
            expected_tag = "ref" if "href" in original.attrib else "seg"
            if "href" in original.attrib:
                destination = urljoin(url, original.get("href"))
                attrs["target"] = destination
                page_url, fragment = urldefrag(destination)
                lookup = page_url + ("#" + unquote(fragment) if fragment else "")
                if destination in (reconciled_links or {}):
                    attrs.update(target="#" + reconciled_links[destination], corresp=destination, type="source-href-reconciled")
                elif destination in image_sources:
                    media, binary = image_sources[destination]
                    attrs["target"] = f"data:{media};base64," + base64.b64encode(binary).decode("ascii")
                    attrs["corresp"] = destination
                elif lookup in (link_targets or {}):
                    attrs["target"] = "#" + link_targets[lookup]
                    attrs["corresp"] = destination
        elif original in block_em:
            if original in span_sources:
                expected_tag = "span"
                attrs.update({"from": "#" + source_ids[original] + "-start", "to": "#" + source_ids[original] + "-end"})
            elif original.getparent().tag == "div":
                expected_tag = "div"
            else:
                raise ValueError("Unsupported block-emphasis source parent")
        elif tag == "greek":
            expected_tag = "seg"
            attrs["type"] = "source-greek"
        elif tag in {*formatting, "font"}:
            expected_tag = "hi"
        else:
            if tag not in mapping:
                raise ValueError(f"Unsupported source semantic element: {tag}")
            expected_tag = mapping[tag]
        if tag == "div" and not len(original) and not (original.text or "").strip():
            expected_tag = "milestone"
            attrs["unit"] = "empty-html-div"
        elif tag == "div" and original.getparent().tag == "blockquote" and original.get("class") == "bulletlist":
            expected_tag = "ab"
        if tag in {"ul", "ol"}:
            attrs["type"] = "ordered" if tag == "ol" else "unordered"
            if original.get("start"):
                attrs["n"] = original.get("start")
        if tag == "dl":
            attrs["type"] = "gloss"
        if tag == "li" and original.get("value"):
            attrs["n"] = original.get("value")
        if tag == "hr":
            attrs["unit"] = "horizontal-rule"
        if tag == "th":
            attrs["role"] = "label"
        if tag in {"th", "td"}:
            if original.get("colspan"):
                attrs["cols"] = original.get("colspan")
            if original.get("rowspan"):
                attrs["rows"] = original.get("rowspan")
        if target.tag != NS + expected_tag or dict(target.attrib) != attrs:
            raise ValueError(f"Readable semantic mapping/attribute drift: {source_ids[original]}")
        if tag == "img":
            image_url = urljoin(url, original.get("src", ""))
            if image_url not in image_sources and image_url not in missing_images:
                raise ValueError("Source image is not retained")
            unavailable = image_url in missing_images
            expected_children = [NS + ("gap" if unavailable else "graphic")] + ([NS + "figDesc"] if "alt" in original.attrib else [])
            if [node.tag for node in target] != expected_children or target.text:
                raise ValueError("Image/caption structure drifted")
            graphic = target[0]
            if unavailable:
                if dict(graphic.attrib) != {"reason": "unavailable", "corresp": image_url} or graphic.text or graphic.tail or len(graphic) != 1:
                    raise ValueError("Unavailable image gap identity drifted")
                description = graphic[0]
                if description.tag != NS + "desc" or description.attrib or len(description) or description.tail or description.text != f"Source image unavailable at acquisition (HTTP {missing_images[image_url]}).":
                    raise ValueError("Unavailable image readable notice drifted")
            else:
                media, binary = image_sources[image_url]
                if set(graphic.attrib) != {"url"} or len(graphic) or graphic.text or graphic.tail:
                    raise ValueError("Graphic structure drifted")
                prefix = f"data:{media};base64,"
                encoded = graphic.get("url", "")
                if not encoded.startswith(prefix) or base64.b64decode(encoded[len(prefix):], validate=True) != binary:
                    raise ValueError("Retained image bytes drifted")
            if len(target) > 1 and (dict(target[1].attrib) or len(target[1]) or (target[1].text or "") != original.get("alt") or target[1].tail):
                raise ValueError("Source image alternative text drifted")
    def source_contents(node):
        parts = [node.text or ""]
        for child in node:
            if isinstance(child.tag, str) and child.tag not in {"script", "style"}:
                parts.append((source_ids[child], source_contents(child)))
            parts.append(child.tail or "")
        return _merged(parts)
    def target_contents(node, selected=None, initial=None):
        if node.tag == NS + "figure" and node.get(ID):
            return []
        parts = [(node.text if initial is None else initial) or ""]
        skipped = set()
        for child in (node if selected is None else selected):
            if child in skipped:
                continue
            if child.tag == NS + "g":
                if dict(child.attrib) != {"ref": "urn:unicode:U+0017"} or child.text != "\u2417" or len(child):
                    raise ValueError("Source control representation drifted")
                parts.extend(["\x17", child.tail or ""])
                continue
            if child in intervals:
                identity, start, end = intervals[child]
                siblings = list(node)
                enclosed = siblings[siblings.index(start) + 1:siblings.index(end)]
                parts.append((identity, target_contents(node, enclosed, start.tail or "")))
                parts.append(end.tail or "")
                skipped.update([start, *enclosed, end])
                continue
            if child.get(ID):
                parts.append((child.get(ID), target_contents(child)))
            else:
                permitted = (
                    child.tag == NS + "div" and child.get("type") in {"source-section", "source-block", "source-inline-run"}
                ) or (child.tag == NS + "ab" and not child.attrib)
                if child.tag == NS + "item" and dict(child.attrib) == {"ana": "source-direct-nested-list", "rend": "unnumbered"}:
                    permitted = node.tag == NS + "list" and not child.text and len(child) == 1 and child[0].tag == NS + "list" and child[0].get(ID) is not None and not child[0].tail
                if child.tag == NS + "item" and dict(child.attrib) == {"ana": "source-unlisted-content", "rend": "unnumbered"}:
                    permitted = node.tag == NS + "list" and node.get("ana") in {"html-ul", "html-ol"}
                if child.tag == NS + "list" and dict(child.attrib) == {"type": "unordered", "ana": "source-orphan-list-item"}:
                    permitted = not child.text and len(child) == 1 and child[0].tag == NS + "item" and child[0].get("ana") == "html-li" and not child[0].tail
                if child.tag == NS + "cell" and dict(child.attrib) == {"ana": "source-empty-row"}:
                    if node.tag != NS + "row" or len(node) != 1 or child.text or child.tail or len(child):
                        raise ValueError("Invented content in empty source table row")
                    continue
                if not permitted:
                    raise ValueError("Invented unmapped candidate structure")
                parts.extend(target_contents(child))
            parts.append(child.tail or "")
        return _merged(parts)
    expected = [(source_ids[region], source_contents(region)) for region in regions]
    if target_contents(candidate) != expected:
        raise ValueError("Readable mixed text, order or source-parent attachment drifted")
    # Heading levels govern intervals of following siblings, independently of
    # the converter's stack. Check each source div's direct-child intervals.
    for parent in (node for node in expected_nodes if node.tag == "div" or node in block_em - span_sources):
        siblings = [node for node in parent if isinstance(node.tag, str) and node.tag not in {"script", "style"}]
        parent_target = by_id[source_ids[parent]]
        for position, node in enumerate(siblings):
            expected_heads = []
            for earlier in range(position + 1):
                heading = siblings[earlier]
                if heading.tag not in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                    continue
                level = int(heading.tag[1])
                interval_ended = any(following.tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and int(following.tag[1]) <= level for following in siblings[earlier + 1:position + 1])
                if not interval_ended:
                    expected_heads.append(source_ids[heading])
            actual_heads = []
            target = by_id[source_ids[node]]
            for ancestor in target.iterancestors():
                if ancestor is parent_target:
                    break
                if ancestor.get("type") == "source-section":
                    if set(ancestor.attrib) != {"type", "subtype"} or not len(ancestor) or ancestor[0].tag != NS + "head" or ancestor.get("subtype") != ancestor[0].get("type"):
                        raise ValueError("Heading section semantics drifted")
                    actual_heads.append(ancestor[0].get(ID))
            if list(reversed(actual_heads)) != expected_heads:
                raise ValueError("Heading-to-following-content attachment drifted")
    return {"status": "pass", "source_nodes": len(expected_nodes), "scope": "main-and-publisher-footer-readable-structure", "source_text_corroboration": "independent stdlib HTMLParser region text matches browser-standard parsing after CR/CRLF-to-LF normalization", "shared_assumption": "html5lib 1.1 topology algorithm and source-node adapter are shared; producer uses ElementTree and oracle uses DOM; document shell uses DOM in both; literal region text is independently corroborated; implicit attribute-free tbody is transparent only when no literal tbody exists"}


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def envelope_for_page(payload: bytes, url: str, authority: str) -> dict:
    """Account for the complete document shell before accepting its body selection."""
    document = _read_document(payload)
    heads = document.findall("head")
    bodies = document.findall("body")
    if len(heads) != 1 or len(bodies) != 1:
        raise ValueError(f"Document head/body envelope is ambiguous: {url}")
    body = bodies[0]
    regions = []
    represented = []
    if (body.text or "").strip(" \t\r\n\u00a0"):
        raise ValueError(f"Unexplained source text before body regions: {url}")
    def account(child):
        if not isinstance(child.tag, str):
            disposition = "nonreadable-html-comment"
        elif child.get("id") in {"springfield2", "ogdenville"}:
            disposition = "readable-main" if child.get("id") == "springfield2" else "readable-publisher-footer"
            represented.append(child.get("id"))
        elif child.get("id") in {"capitalcity", "mobilecity", "mi5"}:
            disposition = "provider-navigation-and-search"
        elif child.tag in {"script", "style", "ins", "noscript", "br"}:
            disposition = "provider-executable-advertising-or-layout"
        elif child.tag == 'description="latin':
            expected_attributes = dict.fromkeys('for rich. the word is not used in bible as a proper noun; but middle ages it came to be employed name of rich man parable and lazarus (luke 16:19-31")'.split(), "")
            if _sha(payload) != "af04fb0b822990f1621c36cfbce2dd64eb78a14f41a412e13dadee4f5ee5e349" or dict(child.attrib) != expected_attributes or (child.text or "").strip() or (child.tail or "").strip():
                raise ValueError("Unbound malformed Dives wrapper or source drift")
            if len(child.xpath("//*[@id='springfield2']")) != 1 or len(child.xpath("//*[@id='ogdenville']")) != 1:
                raise ValueError("Malformed Dives wrapper readable regions differ")
            regions.append({"source_address": child.getroottree().getpath(child), "disposition": "exact-retained-malformed-wrapper-transparent-no-metadata-adoption", "source_tag": child.tag, "source_attributes": dict(child.attrib), "interpreted_subtree_sha256": _sha(interpreted_tree_bytes(child)), "tail_sha256": _sha((child.tail or "").encode("utf-8")), "css_basis": "screen6.css sha256 5a2950105ece77dedd033aefdc4a0fc2b28c0196c09a2bb35cb5fed1117663c7 has no matching wrapper selector; no visual acceptance claim"})
            for nested in child:
                if nested.tag in {"meta", "link"}:
                    if len(nested) or (nested.text or "").strip() or (nested.tail or "").strip():
                        raise ValueError("Unexpected relocated Dives metadata content")
                    regions.append({"source_address": nested.getroottree().getpath(nested), "disposition": "browser-relocated-source-head-carrier-no-metadata-adoption", "source_tag": nested.tag, "source_attributes": dict(nested.attrib), "interpreted_subtree_sha256": _sha(interpreted_tree_bytes(nested)), "tail_sha256": _sha((nested.tail or "").encode("utf-8"))})
                else:
                    account(nested)
            return
        elif child.tag in {"em", "i", "strong", "b"} and not child.attrib and not (child.text or "").strip(" \t\r\n\u00a0"):
            disposition = "browser-recovered-inherited-formatting-context"
            regions.append({"source_address": child.getroottree().getpath(child), "disposition": disposition, "formatting": "italic" if child.tag in {"em", "i"} else "bold", "interpreted_subtree_sha256": _sha(interpreted_tree_bytes(child)), "tail_sha256": _sha((child.tail or "").encode("utf-8"))})
            for nested in child:
                account(nested)
            if (child.tail or "").strip(" \t\r\n\u00a0"):
                raise ValueError(f"Unexplained text after recovered source context: {url}")
            return
        else:
            raise ValueError(f"Unexplained source body region: {url} {child.getroottree().getpath(child)}")
        if (child.tail or "").strip(" \t\r\n\u00a0"):
            raise ValueError(f"Unexplained source text between body regions: {url}")
        regions.append({"source_address": child.getroottree().getpath(child), "disposition": disposition, "interpreted_subtree_sha256": _sha(interpreted_tree_bytes(child)), "tail_sha256": _sha((child.tail or "").encode("utf-8"))})
    for child in body:
        account(child)
    if represented != ["springfield2", "ogdenville"]:
        raise ValueError(f"Main/footer regions are not disjoint ordered body regions: {url}")
    readable_regions = document.xpath("//*[@id='springfield2' or @id='ogdenville']")
    _check_lexical_text(payload, readable_regions)
    metadata = []
    for child in heads[0]:
        if isinstance(child.tag, str) and child.tag in {"title", "meta", "link"}:
            metadata.append({"tag": child.tag, "attributes": dict(child.attrib), "text": "".join(child.itertext())})
    within_exclusions = []
    for region in readable_regions:
        for node in region.iterdescendants():
            if not isinstance(node.tag, str) or node.tag in {"script", "style"}:
                within_exclusions.append({"source_address": node.getroottree().getpath(node), "kind": "html-comment" if not isinstance(node.tag, str) else node.tag, "interpreted_subtree_sha256": _sha(interpreted_tree_bytes(node)), "tail_sha256": _sha((node.tail or "").encode("utf-8"))})
    return {"authority": authority, "url": url, "bytes": len(payload), "sha256": _sha(payload), "document_metadata": vars(document.getroottree().docinfo), "source_address_syntax": "percent-encoded HTML name with same-kind sibling ordinal; not XPath", "root_attributes": dict(document.attrib), "head_metadata": metadata, "interpreted_head_sha256": _sha(interpreted_tree_bytes(heads[0])), "body_attributes": dict(body.attrib), "body_leading_text_sha256": _sha((body.text or "").encode("utf-8")), "body_regions": regions, "within_readable_exclusions": within_exclusions, "outside_readable_policy": "document head metadata is retained here; named provider navigation/search, executable/advertising/layout and HTML comments are accounted but not literary prose"}


def _closure(root: Path) -> str:
    paths = ["build/__init__.py", "build/tei/__init__.py", "build/tei/newadvent_oracle.py", "build/tei/newadvent_source_tree.py", "build/tei/newadvent_css_oracle.py", "ocd_kernel/__init__.py", "ocd_kernel/reconstruction/contract.py", "ocd_kernel/reconstruction/verifier.py", "ocd_kernel/reconstruction/__init__.py"]
    return _sha(_canonical([{"path": path, "sha256": _sha((root / path).read_bytes())} for path in sorted(paths)]))


def _verified_link_reconciliation(source_manifest, profile, source_occurrences=None):
    """Independently prove repairs against retained index and anchor evidence."""
    name = profile.get("link_reconciliation_policy_authority")
    bound = [row["name"] for row in source_manifest.record["authorities"] if row["role"] == "source-link-reconciliation-policy"]
    if bound != ([name] if name else []):
        raise ValueError("Link reconciliation authority binding differs")
    if not name:
        return {}
    policy = json.loads(source_manifest.authority_path(name).read_bytes())
    if not isinstance(policy, dict) or set(policy) != {"contract", "work_id", "mappings", "unmapped"} or policy["contract"] != "ocd-lib025-newadvent-link-reconciliation-v1" or policy["work_id"] != "catholic-encyclopedia-vol01" or not isinstance(policy["mappings"], list) or not isinstance(policy["unmapped"], list):
        raise ValueError("Invalid link reconciliation policy schema")
    failed = {row["url"] for row in profile["failed_acquisitions"] if row["kind"] == "html"}
    members = {row["url"]: row for row in profile["html_members"]}
    def text(value):
        return isinstance(value, str) and bool(value.strip())
    def address(value):
        return text(value) and re.fullmatch(r"https://www\.newadvent\.org/cathen/[a-z0-9-]+\.htm", value) is not None
    result = {}
    declared = {}
    for row in policy["mappings"]:
        if not isinstance(row, dict) or set(row) != {"source_url", "target_url", "index_url", "index_title", "source_occurrences", "rationale"} or not all(address(row[key]) for key in ("source_url", "target_url", "index_url")) or not all(text(row[key]) for key in ("index_title", "rationale")):
            raise ValueError("Invalid link reconciliation mapping schema")
        source, target, index = row["source_url"], row["target_url"], row["index_url"]
        if source not in failed or target not in members or index not in members or source in members or source in result:
            raise ValueError("Link reconciliation failed/retained HTML scope differs")
        occurrences = row["source_occurrences"]
        if not isinstance(occurrences, list) or not occurrences or any(not isinstance(item, dict) or set(item) != {"page_url", "label"} or not address(item["page_url"]) or not text(item["label"]) for item in occurrences):
            raise ValueError("Invalid link reconciliation source occurrences")
        index_document = _read_document(source_manifest.authority_path(members[index]["authority"]).read_bytes())
        labels = [" ".join("".join(node.itertext()).split()) for node in index_document.iter("a") if node.get("href") is not None and urljoin(index, node.get("href")) == target]
        if labels != [row["index_title"]]:
            raise ValueError("Link reconciliation index target/label evidence differs")
        result[source] = members[target]["tei_id"]
        declared[source] = sorted((item["page_url"], item["label"]) for item in occurrences)
    unmapped = []
    for row in policy["unmapped"]:
        if not isinstance(row, dict) or set(row) != {"source_url", "rationale"} or not address(row["source_url"]) or not text(row["rationale"]) or row["source_url"] not in failed or row["source_url"] in members or row["source_url"] in result or row["source_url"] in unmapped:
            raise ValueError("Invalid unmapped link reconciliation entry")
        unmapped.append(row["source_url"])
    observed = {source: list((source_occurrences or {}).get(source, [])) for source in result}
    if result and source_occurrences is None:
        for url, member in members.items():
            document = _read_document(source_manifest.authority_path(member["authority"]).read_bytes())
            for anchor in document.iter("a"):
                if anchor.get("href") is not None:
                    source = urljoin(url, anchor.get("href"))
                    if source in observed:
                        observed[source].append((url, " ".join("".join(anchor.itertext()).split())))
    if any(sorted(observed[source]) != declared[source] for source in result):
        raise ValueError("Link reconciliation source occurrence evidence differs")
    return result


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage):
    source_manifest.verify()
    candidate.verify_integrity()
    validator = source_manifest.record.get("validator", {})
    if validator.get("id") != ORACLE_ID or validator.get("version") != ORACLE_VERSION or validator.get("implementation_sha256") != _sha(Path(__file__).read_bytes()) or validator.get("import_closure_sha256") != _closure(source_manifest.repository_root):
        raise ValueError("LIB-025 validator binding/closure drifted")
    if source_manifest.record.get("work_id") != "catholic-encyclopedia-vol01" or source_manifest.record.get("ticket_id") != "LIB-025":
        raise ValueError("LIB-025 source identity drifted")
    if candidate.manifest.get("source_manifest") != {"path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(), "sha256": source_manifest.sha256} or candidate.manifest.get("status") != "nonaccepted" or candidate.manifest.get("converter") != dict(source_manifest.record["converter"]):
        raise ValueError("LIB-025 candidate binding drifted")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    profile = json.loads(profile_bytes)
    graph_bytes = source_manifest.authority_path("source-graph").read_bytes()
    graph = json.loads(graph_bytes)
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    policy = json.loads(policy_bytes)
    if profile.get("contract") != "ocd-lib025-newadvent-profile-v1" or profile.get("declared_envelope_accounted") is not True or profile.get("graph_sha256") != _sha(graph_bytes) or graph["missing_linked_indexes"]:
        raise ValueError("LIB-025 complete source profile is not established")
    if policy.get("contract") != "ocd-lib025-validation-policy-v1" or policy.get("profile_sha256") != _sha(profile_bytes):
        raise ValueError("LIB-025 validation policy binding drifted")
    expected_urls = list(dict.fromkeys([member["url"] for member in graph["members"]] + graph["article_urls_in_first_occurrence_order"]))
    failures = profile["failed_acquisitions"]
    unavailable = {row["url"]: row for row in failures}
    missing_html = {url for url, row in unavailable.items() if row["kind"] == "html"}
    missing_images = {url: row["http_status"] for url, row in unavailable.items() if row["kind"] == "image"}
    scope = profile["expression_scope"]
    manifest_scope = json.loads(source_manifest.path.read_bytes())
    if len(unavailable) != len(failures) or set(unavailable) != missing_html | set(missing_images) or any(row["http_status"] not in {404, 410} for row in failures):
        raise ValueError("Unavailable source identity/status inventory differs")
    if scope != manifest_scope.get("expression_scope") or failures != manifest_scope.get("failed_acquisitions") or scope.get("whole_work_complete") is not False or scope.get("status") != ("partial" if failures else "retained-cohort") or profile["declared_envelope_retained"] is not (not failures):
        raise ValueError("Partial retained-cohort scope differs")
    included_urls = [row["url"] for row in profile["html_members"]]
    if scope["expected_html_urls"] != expected_urls or scope["included_html_urls"] != included_urls or scope["unavailable_urls"] != list(unavailable) or not missing_html <= set(expected_urls):
        raise ValueError("Partial HTML envelope partition differs")
    if included_urls != [url for url in expected_urls if url not in missing_html]:
        raise ValueError("LIB-025 source member completeness/order drifted")
    authorities = {item["name"]: item for item in source_manifest.record["authorities"]}
    if {row["response_authority"] for row in failures} != {name for name, row in authorities.items() if row["role"] == "failed-acquisition-evidence"}:
        raise ValueError("Failed acquisition authority inventory differs")
    for failure in failures:
        if failure["receipt_authority"] not in profile["acquisition_receipts"]:
            raise ValueError("Failed source receipt is outside the acquisition inventory")
        receipt_path = source_manifest.authority_path(failure["receipt_authority"])
        receipt = json.loads(receipt_path.read_bytes())
        rows = [row for row in receipt["members"] if row["url"] == failure["url"]]
        if len(rows) != 1 or rows[0]["status"] != "failed" or rows[0].get("http_status") != failure["http_status"] or "error_response" not in rows[0]:
            raise ValueError("Failed source receipt identity differs")
        response = rows[0]["error_response"]
        response_path = source_manifest.authority_path(failure["response_authority"])
        if Path(response["path"]).name != response["path"] or response.get("final_url") != failure["url"] or (receipt_path.parent / response["path"]).resolve() != response_path.resolve() or response_path.stat().st_size != response["bytes"] or _sha(response_path.read_bytes()) != response["sha256"]:
            raise ValueError("Failed source exact response bytes differ")
    declared_primary = {name for name, item in authorities.items() if item["role"] == "primary-source"}
    expected_primary = {item["authority"] for item in profile["html_members"] + profile["image_members"]}
    if declared_primary != expected_primary:
        raise ValueError("LIB-025 primary member inventory drifted")
    if {item["authority"] for item in profile["stylesheet_members"]} != {name for name, item in authorities.items() if item["role"] == "source-presentation-stylesheet"}:
        raise ValueError("LIB-025 source stylesheet authority inventory drifted")
    receipt_names = profile["acquisition_receipts"]
    if len(receipt_names) != len(set(receipt_names)) or set(receipt_names) != {name for name, item in authorities.items() if item["role"] == "acquisition-receipt"}:
        raise ValueError("LIB-025 acquisition receipt inventory drifted")
    acquired = {}
    for name in receipt_names:
        receipt_path = source_manifest.authority_path(name)
        receipt = json.loads(receipt_path.read_bytes())
        if receipt.get("contract") != "ocd-newadvent-retained-cohort-v1":
            raise ValueError("LIB-025 acquisition receipt contract drifted")
        for item in receipt["members"]:
            if item["status"] != "retained":
                continue
            if item["url"] in acquired or item.get("http_status") != 200 or item.get("final_url") != item["url"]:
                raise ValueError("LIB-025 acquisition URL identity is ambiguous")
            if Path(item["path"]).name != item["path"]:
                raise ValueError("LIB-025 acquisition member path is unsafe")
            acquired[item["url"]] = (receipt_path.parent / item["path"], item)
    for member in profile["html_members"] + profile["image_members"] + profile["stylesheet_members"]:
        if member["url"] not in acquired:
            raise ValueError("LIB-025 primary source lacks acquisition evidence")
        path, receipt_member = acquired[member["url"]]
        authority = authorities[member["authority"]]
        if path.resolve() != source_manifest.authority_path(member["authority"]).resolve() or receipt_member["bytes"] != authority["bytes"] or receipt_member["sha256"] != authority["sha256"]:
            raise ValueError("LIB-025 source URL/path/digest binding drifted")
    if set(acquired) != {member["url"] for member in profile["html_members"] + profile["image_members"] + profile["stylesheet_members"]}:
        raise ValueError("LIB-025 acquired members lack explicit primary-source disposition")
    images = {member["url"]: (member["media_type"], source_manifest.authority_path(member["authority"]).read_bytes()) for member in profile["image_members"]}
    link_targets = {}
    reconciliation_occurrences = {row["url"]: [] for row in failures if row["kind"] == "html"}
    link_targets.update({row["url"]: f"newadvent-unavailable-{number:04d}" for number, row in enumerate(failures, 1)})
    for member in profile["html_members"]:
        link_targets[member["url"]] = member["tei_id"]
        document = _read_document(source_manifest.authority_path(member["authority"]).read_bytes())
        if profile.get("link_reconciliation_policy_authority"):
            for anchor in document.iter("a"):
                if anchor.get("href") is not None:
                    destination = urljoin(member["url"], anchor.get("href"))
                    if destination in reconciliation_occurrences:
                        reconciliation_occurrences[destination].append((member["url"], " ".join("".join(anchor.itertext()).split())))
        ordinals = {node: number for number, node in enumerate(document.iter(), 1)}
        for region in document.xpath("//*[@id='springfield2' or @id='ogdenville']"):
            for node in region.iter():
                if not isinstance(node.tag, str) or node.tag in {"script", "style"}:
                    continue
                anchors = [node.get("id")]
                if node.tag == "a":
                    anchors.append(node.get("name"))
                for anchor in anchors:
                    if anchor:
                        link_targets.setdefault(member["url"] + "#" + anchor, f"{member['tei_id']}-n{ordinals[node]}")
    reconciled_links = _verified_link_reconciliation(source_manifest, profile, reconciliation_occurrences)
    for image_url, (media_type, binary) in images.items():
        if media_type == "image/svg+xml":
            vector = etree.fromstring(binary, etree.XMLParser(resolve_entities=False, no_network=True))
            if vector.tag != "{http://www.w3.org/2000/svg}svg" or vector.getroottree().docinfo.doctype:
                raise ValueError(f"Retained SVG identity requires review: {image_url}")
        else:
            with Image.open(BytesIO(binary)) as raster:
                if Image.MIME.get(raster.format) != media_type:
                    raise ValueError(f"Retained image media type differs from decoded format: {image_url}")
                raster.verify()
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    if root.tag != NS + "TEI" or dict(root.attrib) != {ID: "catholic-encyclopedia-lib025-candidate"} or [node.tag for node in root] != [NS + "teiHeader", NS + "text"] or root.text:
        raise ValueError("LIB-025 root or header envelope drifted")
    texts = root.find(NS + "text")
    if dict(texts.attrib) or texts.text or len(texts) != 1 or texts[0].tag != NS + "body":
        raise ValueError("LIB-025 readable text envelope drifted")
    body = texts[0]
    if body.attrib or body.text or len(body) != len(profile["html_members"]) + bool(failures):
        raise ValueError("LIB-025 page count or body text drifted")
    target_ids = {node.get(ID) for node in root.iter() if node.get(ID)}
    for reference in root.iter(NS + "ref"):
        destination = reference.get("target", "")
        if destination.startswith("#") and destination[1:] not in target_ids:
            raise ValueError("LIB-025 internal readable link has no retained target")
    expected_accounting = []
    envelopes = []
    required_images = set()
    required_stylesheets = set()
    stylesheet_payloads = {row["url"]: source_manifest.authority_path(row["authority"]).read_bytes() for row in profile["stylesheet_members"]}
    typography_policy = source_manifest.authority_path(profile["typography_policy_authority"]).read_bytes() if profile.get("typography_policy_authority") else None
    home_title = None
    for member, page in zip(profile["html_members"], body):
        payload = source_manifest.authority_path(member["authority"]).read_bytes()
        document = _read_document(payload)
        page_css = []
        for link in document.xpath("//link[@href]"):
            if "stylesheet" in link.get("rel", "").lower().split():
                address = urljoin(member["url"], link.get("href"))
                if address not in stylesheet_payloads:
                    raise ValueError("Unretained source stylesheet")
                if stylesheet_payloads[address]:
                    page_css.append(stylesheet_payloads[address])
        if len(page_css) > 1:
            raise ValueError("Multiple source stylesheets require independent cascade review")
        verify_page(payload, member["url"], member["tei_id"], page, images, link_targets, missing_images, css_bytes=page_css[0] if page_css else b"", policy_bytes=typography_policy, reconciled_links=reconciled_links)
        if page.tail:
            raise ValueError("Invented inter-page text")
        for link in document.xpath("//link[@href]"):
            if "stylesheet" in link.get("rel", "").lower().split():
                required_stylesheets.add(urljoin(member["url"], link.get("href")))
        source_nodes = list(document.iter())
        target_by_id = {node.get(ID): node for node in page.iterdescendants() if node.get(ID)}
        events = []
        for number, node in enumerate(source_nodes, 1):
            identifier = f"{member['tei_id']}-n{number}"
            if identifier in target_by_id:
                events.append({"source_address": node.getroottree().getpath(node), "source_tag": node.tag, "source_attributes": dict(node.attrib), "tei_id": identifier, "tei_tag": etree.QName(target_by_id[identifier]).localname})
                if node.get("srcset") or "url(" in node.get("style", "").lower():
                    raise ValueError("Source image-set/CSS asset semantics require an explicit verified mapping")
                if node.tag == "img":
                    required_images.add(urljoin(member["url"], node.get("src", "")))
                if node.tag == "a" and node.get("href"):
                    linked = urljoin(member["url"], node.get("href"))
                    if Path(urlsplit(linked).path).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".tif", ".tiff"}:
                        required_images.add(linked)
        expected_accounting.append({"authority": member["authority"], "url": member["url"], "source_sha256": _sha(payload), "events": events})
        envelopes.append(envelope_for_page(payload, member["url"], member["authority"]))
        if member["url"] == "https://www.newadvent.org/cathen/":
            titles = document.xpath("//*[@id='springfield2']/h1")
            if len(titles) != 1:
                raise ValueError("Source collection title is ambiguous")
            home_title = " ".join("".join(titles[0].itertext()).split())
    if home_title != profile["identity"]["title"] or profile["source_envelope"] != envelopes:
        raise ValueError("LIB-025 work title or complete document envelope drifted")
    if required_images != set(images) | set(missing_images) or set(images) & set(missing_images) or len(profile["image_members"]) != len(images) or scope["included_image_urls"] != [row["url"] for row in profile["image_members"]] or set(scope["expected_image_urls"]) != required_images:
        raise ValueError("LIB-025 complete displayed/linked image inventory drifted")
    if required_stylesheets != {item["url"] for item in profile["stylesheet_members"]} or len(required_stylesheets) != len(profile["stylesheet_members"]):
        raise ValueError("LIB-025 complete source stylesheet inventory drifted")
    expected_header = etree.Element(NS + "teiHeader")
    def add(parent, tag, text=None, **attrs):
        node = etree.SubElement(parent, NS + tag, **attrs)
        node.text = text
        return node
    desc = add(expected_header, "fileDesc")
    add(add(desc, "titleStmt"), "title", home_title)
    pub = add(desc, "publicationStmt")
    add(pub, "publisher", "Open Christian Data")
    add(add(pub, "availability", status="restricted"), "p", "Nonaccepted candidate. Human acceptance and public publication are not authorized by this reconstruction.")
    bibl = add(add(desc, "sourceDesc"), "bibl")
    add(bibl, "title", "The Catholic Encyclopedia — New Advent web transcription")
    add(bibl, "publisher", "New Advent")
    add(bibl, "ptr", target="https://www.newadvent.org/cathen/")
    add(bibl, "idno", _sha(graph_bytes), type="retained-index-graph-sha256")
    add(add(expected_header, "encodingDesc"), "p", profile["mapping_summary"])
    def signature(node):
        return node.tag, dict(node.attrib), node.text, node.tail, [signature(child) for child in node]
    if failures:
        notice = etree.Element(NS + "div", type="unavailable-source-members")
        add(notice, "head", "Unavailable source members — partial retained cohort")
        listing = add(notice, "list")
        for number, failure in enumerate(failures, 1):
            entry = add(listing, "item", **{ID: f"newadvent-unavailable-{number:04d}"})
            add(entry, "ref", failure["url"], target=failure["url"])
            gap = add(entry, "gap", reason="unavailable", corresp=failure["url"])
            add(gap, "desc", f"Requested {failure['kind']} source unavailable at acquisition (HTTP {failure['http_status']}); not included as retained source content.")
        if signature(body[-1]) != signature(notice):
            raise ValueError("Readable unavailable-member notice differs")
    if signature(root[0]) != signature(expected_header):
        raise ValueError("LIB-025 complete header metadata drifted")
    expected = {"contract": "ocd-lib025-newadvent-accountability-v1", "members": expected_accounting, "source_envelope": envelopes, "image_members": profile["image_members"]}
    expected.update(expression_scope=scope, failed_acquisitions=failures)
    if candidate.member_bytes("source-accountability.json") != _canonical(expected):
        raise ValueError("LIB-025 source accounting drifted")
    provenance = {"contract": "ocd-lib025-newadvent-provenance-v1", "work_id": "catholic-encyclopedia-vol01", "source_manifest_sha256": source_manifest.sha256, "profile_sha256": _sha(profile_bytes), "source_graph_sha256": _sha(graph_bytes), "identity": profile["identity"], "status": "nonaccepted", "publication": False, "legacy_generated_json_used_as_authority": False}
    provenance.update(expression_scope=scope, failed_acquisitions=failures)
    if candidate.member_bytes("provenance.json") != _canonical(provenance) or candidate.member_bytes("unresolved.jsonl") != b"".join(_canonical(row) for row in profile["unresolved"]) or candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-attribution-readme").read_bytes():
        raise ValueError("LIB-025 provenance, unresolved decisions or README drifted")
    xsd_path = source_manifest.authority_path("tei-p5-xsd")
    etree.XMLSchema(etree.parse(str(xsd_path))).assertValid(root)
    primary_records = sorted([{"name": name, "path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]} for name, item in authorities.items() if item["role"] == "primary-source"], key=lambda item: (item["path"], item["name"]))
    source_sha = primary_records[0]["sha256"] if len(primary_records) == 1 else _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": primary_records}))
    facts = MechanicalFacts(validator_implementation_sha256=_sha(Path(__file__).read_bytes()), validator_import_closure_sha256=_closure(source_manifest.repository_root), source_sha256=source_sha, profile_sha256=_sha(profile_bytes), package_schema_sha256=_sha(source_manifest.authority_path("candidate-package-schema").read_bytes()), xsd_sha256=_sha(xsd_path.read_bytes()), policy_sha256=_sha(policy_bytes), findings=())
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
