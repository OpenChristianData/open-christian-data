from __future__ import annotations
import json, re
from lxml import etree
from build.tei.l225_ebible_usfm import convert as _base_convert

TEI = "http://www.tei-c.org/ns/1.0"
XML = "{http://www.w3.org/XML/1998/namespace}"
TOKEN = re.compile(r"\\(?P<tag>\+?[A-Za-z][A-Za-z0-9]*)(?P<close>\*)?")
OPEN_MAP = {
    "w": ("w", {}), "+w": ("w", {"type": "usfm-plus-w"}),
    "wj": ("q", {"type": "words-of-Jesus"}),
    "+wh": ("foreign", {XML+"lang": "he"}),
    "qs": ("seg", {"type": "selah"}),
    "bk": ("title", {"type": "biblical-book"}),
    "k": ("term", {}),
}
FIELD_MAP = {
    "fr": ("ref", {"type": "source-label"}),
    "xo": ("ref", {"type": "source-origin"}),
    "ft": ("seg", {"type": "footnote-text"}),
    "xt": ("ref", {"type": "source-target"}),
    "fqa": ("seg", {"type": "alternate-reading"}),
    "fq": ("seg", {"type": "quoted-reading"}),
}

def _add_text(parent, text):
    if not text:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + text
    else:
        parent.text = (parent.text or "") + text

def _parse_inline(parent, value, base_pointer):
    matches = list(TOKEN.finditer(value))
    if not matches:
        _add_text(parent, value)
        return {}
    stats = {}
    stack = []
    active_field = None
    pending_caller = False
    last = 0
    for match in matches:
        between = value[last:match.start()]
        if active_field is not None:
            field_node, field_start = active_field
            field_node.set("corresp", f"{base_pointer}&span={field_start}:{match.start()}")
        if pending_caller:
            caller = re.match(r"^(\s*)\+(\s*)", between)
            if caller:
                note = next((entry[1] for entry in reversed(stack) if entry[0] in {"f", "x"}), None)
                if note is None:
                    raise ValueError("USFM caller marker without note scope")
                target = active_field if active_field is not None else note
                _add_text(target, caller.group(1))
                label = etree.SubElement(note, f"{{{TEI}}}label", type="caller")
                label.text = "+"
                _add_text(target, caller.group(2))
                between = between[caller.end():]
            pending_caller = False
        target = active_field[0] if active_field is not None else (stack[-1][1] if stack else parent)
        _add_text(target, between)
        active_field = None
        tag = match.group("tag")
        closing = bool(match.group("close"))
        stat = tag + ("*" if closing else "")
        stats[stat] = stats.get(stat, 0) + 1
        if tag in {"f", "x"} and not closing:
            node = etree.SubElement(stack[-1][1] if stack else parent, f"{{{TEI}}}note", type="footnote" if tag == "f" else "cross-reference")
            stack.append((tag, node, match.start()))
            pending_caller = True
        elif tag in FIELD_MAP and not closing:
            name, attrs = FIELD_MAP[tag]
            node = etree.SubElement(stack[-1][1] if stack else parent, f"{{{TEI}}}{name}", **attrs)
            active_field = (node, match.start())
        elif closing:
            if not stack or stack[-1][0] != tag:
                raise ValueError(f"unbalanced USFM inline marker {tag}*")
            _, node, start = stack.pop()
            node.set("corresp", f"{base_pointer}&span={start}:{match.end()}")
            if tag in {"w", "+w"}:
                raw = node.text or ""
                word = re.fullmatch(r"(.*?)(?:\|strong=\"([^\"]+)\")?", raw, re.DOTALL)
                if word is None:
                    raise ValueError(f"unparsed Strong's annotation: {raw!r}")
                node.text = word.group(1)
                if word.group(2):
                    node.set("n", word.group(2))
                leading = re.match(r"^\s+", node.text or "")
                if leading:
                    parent_node = node.getparent()
                    position = parent_node.index(node)
                    if position:
                        previous = parent_node[position - 1]
                        previous.tail = (previous.tail or "") + leading.group(0)
                    else:
                        parent_node.text = (parent_node.text or "") + leading.group(0)
                    node.text = (node.text or "")[leading.end():]
        elif tag in OPEN_MAP:
            name, attrs = OPEN_MAP[tag]
            node = etree.SubElement(stack[-1][1] if stack else parent, f"{{{TEI}}}{name}", **attrs)
            stack.append((tag, node, match.start()))
        else:
            raise ValueError(f"unsupported inline USFM marker \\{tag}")
        last = match.end()
    tail = value[last:]
    if pending_caller:
        caller = re.match(r"^(\s*)\+(\s*)", tail)
        if caller:
            note = next((entry[1] for entry in reversed(stack) if entry[0] in {"f", "x"}), None)
            if note is None:
                raise ValueError("USFM caller marker without note scope")
            _add_text(note, caller.group(1))
            label = etree.SubElement(note, f"{{{TEI}}}label", type="caller")
            label.text = "+"
            _add_text(note, caller.group(2))
            tail = tail[caller.end():]
    target = active_field[0] if active_field is not None else (stack[-1][1] if stack else parent)
    _add_text(target, tail)
    if active_field is not None:
        active_field[0].set("corresp", f"{base_pointer}&span={active_field[1]}:{len(value)}")
    if stack:
        raise ValueError(f"unclosed USFM inline scope: {[entry[0] for entry in stack]}")
    return stats

def convert(manifest):
    result = dict(_base_convert(manifest))
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    root = etree.fromstring(result["content.tei.xml"], parser)
    inline_totals = {}
    for node in root.iter():
        if node.text and "\\" in node.text and node.get("corresp", "").startswith("source-usfm:"):
            base_pointer = node.get("corresp")
            raw = node.text
            node.text = None
            for key, count in _parse_inline(node, raw, base_pointer).items():
                inline_totals[key] = inline_totals.get(key, 0) + count
    result["content.tei.xml"] = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    account = json.loads(result["source-accountability.json"])
    account["inline_marker_counts"] = dict(sorted(inline_totals.items()))
    result["source-accountability.json"] = (json.dumps(account, ensure_ascii=False, sort_keys=True, separators=(",", ":"))+"\n").encode()
    readme = result["README.source.md"].decode("utf-8")
    readme += ("\nInline USFM is reconstructed as readable TEI: lexical `w` and `+w` spans retain Strong's IDs in `@n`; `f`/`x` scopes become attached footnote/cross-reference notes with source labels, note text, alternate readings, and targets; `wj`, Hebrew `+wh`, Selah `qs`, and glossary/book-title spans have explicit TEI elements. Each inline node points to its exact source-line span. Unrecognized or unbalanced inline markers fail closed.\n")
    result["README.source.md"] = readme.encode("utf-8")
    return result
convert.converter_id = "ocd-l225-engwebpb-semantic-inline"
convert.converter_version = "2"
