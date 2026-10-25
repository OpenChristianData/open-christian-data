"""Independent source-node expectations for the bound screen6 typography slice.

No converter or producer CSS imports. Parsing, selector traversal and winner
selection deliberately use a separate implementation; the exact retained CSS
and proposed policy remain shared source authorities.
"""
from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from functools import lru_cache

CSS_SHA256 = "5a2950105ece77dedd033aefdc4a0fc2b28c0196c09a2bb35cb5fed1117663c7"
POLICY_SHA256 = "e3c7617dffcc3e93ee8169ce2336ed2c63ec10c79e75736e0b243adedec88069"
SCOPE = "source-screen6-static-unvisited-typography; Chromium default-font 16px; excludes layout, hover/visited/active states and installed-font metrics"
INHERITED = frozenset(("color", "font-family", "font-size", "font-style", "font-weight", "font-variant", "line-height", "letter-spacing", "text-align", "text-transform"))
SUPPORTED = INHERITED | {"background-color", "text-decoration"}


def _read_rules(payload):
    text = payload.decode("utf-8")
    while "/*" in text:
        first = text.index("/*")
        last = text.index("*/", first)
        text = text[:first] + text[last + 2:]
    stack = []
    cursor = 0
    rows = []
    for index, character in enumerate(text):
        if character == "{":
            stack.append((text[cursor:index].strip(), index + 1))
            cursor = index + 1
        elif character == "}":
            selector_list, start = stack.pop()
            body = text[start:index]
            if "{" not in body:
                declarations = []
                for declaration in body.split(";"):
                    name, separator, value = declaration.partition(":")
                    name, value = name.strip(), value.strip()
                    if separator and name in SUPPORTED:
                        declarations.append((name, value))
                    elif name == "background" and (re.fullmatch(r"#[\da-fA-F]{3,6}", value) or value.isalpha()):
                        declarations.append(("background-color", value))
                if declarations:
                    rows.extend((selector.strip(), declarations) for selector in selector_list.split(","))
            cursor = index + 1
    return rows


@lru_cache(maxsize=512)
def _tokens_for_selector(selector):
    parsed = []
    for token in selector.split():
        pieces = re.findall(r"^[A-Za-z][\w-]*|^\*|[.#][\w-]+", token)
        if "".join(pieces) != token:
            return ()
        parsed.append(tuple(pieces))
    return tuple(parsed)


def _selector_matches(element, selector):
    tokens = _tokens_for_selector(selector)
    def part_matches(node, pieces):
        for piece in pieces:
            if piece[0] == "#" and node.get("id") != piece[1:]:
                return False
            if piece[0] == "." and piece[1:] not in node.get("class", "").split():
                return False
            if piece[0] not in ".#" and piece != "*" and node.tag != piece:
                return False
        return bool(pieces)
    def ending_at(node, position):
        if not part_matches(node, tokens[position]):
            return False
        if position == 0:
            return True
        return any(ending_at(ancestor, position - 1) for ancestor in node.iterancestors())
    return bool(tokens) and ending_at(element, len(tokens) - 1)


def _length(raw, relative):
    match = re.fullmatch(r"([+-]?(?:\d*\.)?\d+)(px|em|%)", raw)
    if match is None:
        raise ValueError("Unresolved font length")
    quantity = Decimal(match[1])
    return quantity if match[2] == "px" else quantity * relative / (100 if match[2] == "%" else 1)


def _inline_supported(name, text):
    if not text or "!" in text or any(expression in text for expression in ("var(", "calc(", "url(")) or text in ("inherit", "initial", "unset", "revert"):
        return False
    words = {"font-style": "normal italic oblique", "font-variant": "normal small-caps",
             "font-weight": "normal bold 100 200 300 400 500 600 700 800 900",
             "text-align": "left right center justify start end", "text-transform": "none capitalize uppercase lowercase",
             "text-decoration": "none underline overline line-through"}
    if name in words:
        return text in words[name].split()
    if name in ("color", "background-color"):
        if text.lower() in "black white red green blue darkblue darkred gray grey yellow orange purple transparent".split():
            return True
        if text.startswith("#"):
            return len(text) in (4, 7) and all(c in "0123456789abcdefABCDEF" for c in text[1:])
        return re.fullmatch(r"rgba?\([0-9.,% ]+\)", text) is not None
    if name in ("font-size", "line-height", "letter-spacing"):
        if text == "normal":
            return name != "font-size"
        return re.fullmatch(r"[+-]?(?:\d*\.)?\d+(px|em|%)?", text) is not None
    return name == "font-family" and "(" not in text


def expected_typography_map(document, css_bytes=b"", policy_bytes=None):
    nodes = [node for node in document.iter() if isinstance(node.tag, str)]
    if not css_bytes:
        return {node: {"declarations": {}, "gates": [], "scope": "no-author-stylesheet", "css_sha256": None, "policy_sha256": None} for node in nodes}
    if hashlib.sha256(css_bytes).hexdigest() != CSS_SHA256:
        raise ValueError("Unbound New Advent stylesheet")
    if policy_bytes is None or hashlib.sha256(policy_bytes).hexdigest() != POLICY_SHA256:
        raise ValueError("Unbound New Advent typography policy")
    rules = _read_rules(css_bytes)
    answers = {}
    def compute(node):
        if node in answers:
            return answers[node]
        parent = node.getparent()
        inherited_result = compute(parent) if parent is not None and isinstance(parent.tag, str) else None
        inherited = ({key: value for key, value in inherited_result["declarations"].items() if key in INHERITED}
                     if inherited_result else {"font-size": "16px", "font-style": "normal", "font-weight": "400", "line-height": "normal", "letter-spacing": "normal", "text-align": "start"})
        gates = set(inherited_result["gates"]) if inherited_result else set()
        candidates = {}
        def offer(prop, value, priority):
            if prop not in candidates or priority >= candidates[prop][0]:
                candidates[prop] = (priority, value)
        hints = {}
        if node.tag in ("small", "big", "sub", "sup"):
            base_size = Decimal(inherited["font-size"][:-2])
            hints["font-size"] = format((base_size * 6 / 5 if node.tag == "big" else base_size * 5 / 6).normalize(), "f") + "px"
        if node.tag in ("i", "em"):
            hints["font-style"] = "italic"
        if node.tag in ("b", "strong"):
            hints["font-weight"] = "bold"
        if node.tag == "th":
            hints["font-weight"] = "bold"
            inherited_alignment = inherited.get("text-align", "start")
            hints["text-align"] = inherited_alignment if inherited_alignment != "start" else "center"
        if node.tag == "center":
            hints["text-align"] = "center"
        if node.tag != "table" and node.get("align"):
            hints["text-align"] = node.get("align")
        if node.tag == "font":
            if node.get("color"):
                hints["color"] = node.get("color")
            if node.get("face"):
                hints["font-family"] = node.get("face")
            if node.get("size"):
                spelling = node.get("size").strip()
                match = re.fullmatch(r"([+-]?)([0-9]+)", spelling)
                if match is None:
                    gates.add("unsupported-html-font-size")
                else:
                    magnitude = int(match[2])
                    level = 3 - magnitude if match[1] == "-" else 3 + magnitude if match[1] == "+" else magnitude
                    hints["font-size"] = {1: "10px", 2: "13px", 3: "16px", 4: "18px", 5: "24px", 6: "32px", 7: "48px"}[min(7, max(1, level))]
        if node.get("bgcolor") or node.get("background"):
            gates.add("html-background-hint-needs-resolution")
        for prop, value in hints.items():
            offer(prop, value, (-1, 0, 0, 0, 0))
        for order, (selector, declarations) in enumerate(rules):
            selector_for_match = selector
            if node.tag == "a" and "href" in node.attrib and ":link" in selector:
                selector_for_match = selector.replace(":link", "")
            if ":" in selector_for_match or "[" in selector_for_match:
                continue
            if not _selector_matches(node, selector_for_match):
                continue
            if selector == "#mi5":
                gates.add("conditional-media-typography")
                continue
            priority = (0, selector.count("#"), selector.count(".") + selector.count(":link"), sum(bool(re.match("[A-Za-z]", part)) for part in selector.split()), order)
            for prop, value in declarations:
                offer(prop, value, priority)
        for index, chunk in enumerate(node.get("style", "").split(";")):
            if not chunk.strip():
                continue
            prop, delimiter, value = chunk.partition(":")
            prop, value = prop.strip().lower(), value.strip()
            if not delimiter:
                gates.add("unparsed-inline-style")
            elif prop in SUPPORTED:
                if not _inline_supported(prop, value):
                    gates.add("unsupported-inline-typography")
                else:
                    offer(prop, value, (1, 0, 0, 0, index))
            elif prop in ("font", "all", "background") or prop.startswith(("font-", "text-decoration-", "background-")):
                gates.add("overlapping-inline-shorthand")
        direct = {prop: pair[1] for prop, pair in candidates.items()}
        if "font-size" in direct:
            try:
                keyword_names = "xx-small x-small small medium large x-large xx-large xxx-large".split()
                keyword_sizes = (9, 10, 13, 16, 18, 24, 32, 48)
                size = Decimal(keyword_sizes[keyword_names.index(direct["font-size"])]) if direct["font-size"] in keyword_names else _length(direct["font-size"], Decimal(inherited["font-size"][:-2]))
                direct["font-size"] = format(size.normalize(), "f") + "px"
            except ValueError:
                direct.pop("font-size")
                gates.add("unsupported-font-size")
        values = dict(inherited, **direct)
        for prop, units in (("letter-spacing", ("em",)), ("line-height", ("em", "%"))):
            if prop in direct and direct[prop].endswith(units):
                values[prop] = format(_length(direct[prop], Decimal(values["font-size"][:-2])).normalize(), "f") + "px"
        answers[node] = {"declarations": values, "gates": sorted(gates), "scope": SCOPE,
                         "css_sha256": CSS_SHA256, "policy_sha256": POLICY_SHA256}
        return answers[node]
    for node in nodes:
        compute(node)
    return answers


def expected_typography(source_node, css_bytes=b"", policy_bytes=None):
    return expected_typography_map(source_node.getroottree().getroot(), css_bytes, policy_bytes)[source_node]
