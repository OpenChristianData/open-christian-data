"""Check the shipped Douay Markdown against frozen native nonverse fields."""

from __future__ import annotations

import hashlib
import html
import json
from collections import defaultdict
from pathlib import Path

from lxml import etree

from build.tools.prepare_original_douay_release_notices import convert


ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "reports/_logs/original-douay-rheims-current-reconciliation-20261002-v1"
SOURCE = LOG / "renewed-native-v1/content.tei.xml"
HTML = LOG / "readable-companion-v2"
MARKDOWN = LOG / "readable-companion-v2-release"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def escape(value: str) -> str:
    value = value.replace("\\", "\\\\")
    for marker in "*_`[]":
        value = value.replace(marker, "\\" + marker)
    return html.escape(value, quote=False)


def native_markdown(node: etree._Element) -> tuple[str, int, int, int]:
    """Render a native field without reading the HTML companion."""
    output = [escape(node.text or "")]
    styles = breaks = whitespace_italics = 0
    for child in node:
        local = etree.QName(child).localname
        if local == "lb":
            output.append("  \n")
            breaks += 1
        else:
            value, child_styles, child_breaks, child_whitespace = native_markdown(child)
            styles += child_styles
            breaks += child_breaks
            whitespace_italics += child_whitespace
            if local == "hi":
                rendition = child.get("rend")
                if rendition == "italic":
                    literal = "".join(child.itertext())
                    if literal[:1].isspace() or literal[-1:].isspace():
                        value = "〔italic: " + value + "〕"
                        whitespace_italics += 1
                    else:
                        value = "*" + value + "*"
                elif rendition == "small-caps":
                    value = "〔small caps: " + value + "〕"
                elif rendition == "ref-title-sub":
                    value = "〔reference title subscript: " + value + "〕"
                else:
                    raise ValueError(f"Unsupported native style: {rendition}")
                styles += 1
            elif local != "seg":
                raise ValueError(f"Unsupported native inline element: {local}")
            output.append(value)
        output.append(escape(child.tail or ""))
    return "".join(output), styles, breaks, whitespace_italics


def label(node: etree._Element) -> str:
    kind = node.get("type") or etree.QName(node).localname
    return kind.replace("-", " ").title() + (" " + node.get("n") if node.get("n") else "")


def main() -> None:
    source = SOURCE.read_bytes()
    native = etree.fromstring(source)
    fields = {
        node.get(XML_ID): node
        for node in native.iter()
        if (node.get(XML_ID) or "").startswith("odr-source-field-")
        and node.get("type") != "verse"
    }
    crosswalk = json.loads((HTML / "private-crosswalk.json").read_bytes())
    manifest = json.loads((MARKDOWN / "manifest.json").read_bytes())
    html_manifest = json.loads((HTML / "manifest.json").read_bytes())
    if (len(fields) != 25145 or len(crosswalk) != len(fields)
            or manifest["source_manifest_sha256"] != sha((HTML / "manifest.json").read_bytes())
            or manifest["source_crosswalk_sha256"] != sha((HTML / "private-crosswalk.json").read_bytes())
            or html_manifest["source_sha256"] != sha(source)):
        raise ValueError("Native, crosswalk, or companion binding differs")
    by_part: dict[str, list[str]] = defaultdict(list)
    for entry in crosswalk:
        by_part[entry["part"]].append(entry["field_id"])
    checked = nulls = styles = breaks = whitespace_italics = literal_bytes = 0
    matched_ids = set()
    for part in manifest["parts"]:
        path = part["path"]
        data = (MARKDOWN / path).read_bytes()
        original = (HTML / path).read_bytes()
        if sha(data) != part["sha256"] or len(data) != part["bytes"] or len(data) > 65536:
            raise ValueError(f"Release part hash or limit differs: {path}")
        if data != convert(original):
            raise ValueError(f"Release part differs from pinned readable derivative: {path}")
        if path == "collection-context.md":
            disposition = [node for node in native.iter(TEI + "note") if node.get("type") == "source-disposition"]
            if len(disposition) != 1 or not disposition[0].text:
                raise ValueError("Native collection disposition differs")
            expected = escape(disposition[0].text)
            if expected not in data.decode("utf-8"):
                raise ValueError("Collection disposition wording missing from Markdown")
            literal_bytes += len(disposition[0].text.encode("utf-8"))
            continue
        text = data.decode("utf-8")
        cursor = 0
        ids = by_part[path]
        if len(ids) != part["fields"]:
            raise ValueError(f"Part source-field count differs: {path}")
        for identity in ids:
            if identity in matched_ids or identity not in fields:
                raise ValueError(f"Repeated or absent native field: {identity}")
            matched_ids.add(identity)
            node = fields[identity]
            literal_bytes += len("".join(node.itertext()).encode("utf-8"))
            if node.get("type") == "source-null-absence:source-language-title":
                if node.text != "null" or len(node):
                    raise ValueError(f"Native JSON null changed: {identity}")
                expected = "*Source language title absent (JSON null; not authored text).*\n\n"
                nulls += 1
            else:
                body, count_styles, count_breaks, count_whitespace = native_markdown(node)
                expected = "**" + label(node) + "**\n\n" + body + "\n\n"
                checked += 1
                styles += count_styles
                breaks += count_breaks
                whitespace_italics += count_whitespace
            found = text.find(expected, cursor)
            if found < cursor:
                raise ValueError(f"Native field text, style, or order missing in {path}: {identity}")
            cursor = found + len(expected)
    if (matched_ids != set(fields) or checked != 25072 or nulls != 73
            or styles != 12815 or breaks != 59 or whitespace_italics != 4
            or literal_bytes != 3781838 or len(manifest["parts"]) != 169):
        raise ValueError("Complete native-to-Markdown source census differs")
    result = {
        "status": "pass",
        "frozen_source_sha256": sha(source),
        "html_companion_manifest_sha256": sha((HTML / "manifest.json").read_bytes()),
        "markdown_manifest_sha256": sha((MARKDOWN / "manifest.json").read_bytes()),
        "markdown_parts": len(manifest["parts"]),
        "native_nonverse_fields": len(matched_ids),
        "visible_text_fields": checked,
        "typed_json_nulls": nulls,
        "native_inline_styles": styles,
        "native_line_breaks": breaks,
        "whitespace_bound_italic_spans": whitespace_italics,
        "literal_nonverse_utf8_bytes": literal_bytes,
        "native_field_text_style_order": "exact",
        "collection_disposition": "included",
    }
    target = LOG / "readable-companion-v2-release-proof.json"
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
