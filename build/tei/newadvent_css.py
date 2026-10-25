"""Bounded screen6 typography, evaluated once over the source document.

This is not a general CSS engine. Exact stylesheet/policy bindings delimit its
grammar. Returned gates must be resolved before asserting typography fidelity.
Values describe source ancestry, not the converter's inserted TEI wrappers.
"""
from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from functools import lru_cache

CSS_SHA256 = "5a2950105ece77dedd033aefdc4a0fc2b28c0196c09a2bb35cb5fed1117663c7"
POLICY_SHA256 = "e3c7617dffcc3e93ee8169ce2336ed2c63ec10c79e75736e0b243adedec88069"
SCOPE = "source-screen6-static-unvisited-typography; Chromium default-font 16px; excludes layout, hover/visited/active states and installed-font metrics"
INHERITED = {"color", "font-family", "font-size", "font-style", "font-weight", "font-variant", "line-height", "letter-spacing", "text-align", "text-transform"}
PROPERTIES = INHERITED | {"background-color", "text-decoration"}


@lru_cache(maxsize=512)
def _selector_tokens(selector):
    result = []
    for token in selector.split():
        if re.fullmatch(r"(?:[a-zA-Z][\w-]*|\*)?(?:[.#][\w-]+)*", token) is None:
            return ()
        tag = re.match(r"^[\w*-]+", token)
        result.append((tag[0] if tag else None, tuple(re.findall(r"([.#])([\w-]+)", token))))
    return tuple(result)


def _matches(node, selector):
    parts = _selector_tokens(selector)
    def simple(element, token):
        tag, attributes = token
        if tag and tag != "*" and element.tag != tag:
            return False
        return all(element.get("id") == value if kind == "#" else value in element.get("class", "").split()
                   for kind, value in attributes)
    if not parts or not simple(node, parts[-1]):
        return False
    ancestor = node.getparent()
    for part in reversed(parts[:-1]):
        while ancestor is not None and not simple(ancestor, part):
            ancestor = ancestor.getparent()
        if ancestor is None:
            return False
        ancestor = ancestor.getparent()
    return True


def _rules(css):
    clean = re.sub(r"/\*.*?\*/", "", css.decode("utf-8"), flags=re.S)
    # Exact screen6 has only these conditional typography carriers. Main-region
    # background is identical across its exhaustive 720/721px branches.
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", clean):
        selectors, body = match.groups()
        declarations = []
        for chunk in body.split(";"):
            if ":" in chunk:
                prop, value = (piece.strip() for piece in chunk.split(":", 1))
                if prop in PROPERTIES:
                    declarations.append((prop, value))
                elif prop == "background" and re.fullmatch(r"#[0-9a-fA-F]{3,6}|[a-zA-Z]+", value):
                    declarations.append(("background-color", value))
        if declarations:
            for selector in selectors.strip().split(","):
                yield selector.strip(), declarations


def _pixels(value, size):
    if re.fullmatch(r"[+-]?(?:\d*\.)?\d+px", value):
        return Decimal(value[:-2])
    if re.fullmatch(r"[+-]?(?:\d*\.)?\d+%", value):
        return size * Decimal(value[:-1]) / 100
    if re.fullmatch(r"[+-]?(?:\d*\.)?\d+em", value):
        return size * Decimal(value[:-2])
    raise ValueError("Unsupported source font-size unit")


def _supported_inline(prop, value):
    if not value or any(token in value for token in ("!", "var(", "calc(", "url(")):
        return False
    if value in {"inherit", "initial", "unset", "revert"}:
        return False
    allowed = {"font-style": {"normal", "italic", "oblique"},
               "font-weight": {"normal", "bold", *[str(n) for n in range(100, 1000, 100)]},
               "font-variant": {"normal", "small-caps"},
               "text-align": {"left", "right", "center", "justify", "start", "end"},
               "text-transform": {"none", "capitalize", "uppercase", "lowercase"},
               "text-decoration": {"none", "underline", "overline", "line-through"}}
    if prop in allowed:
        return value in allowed[prop]
    if prop in {"color", "background-color"}:
        return bool(re.fullmatch(r"#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}|rgba?\([0-9.,% ]+\)", value)) or value.lower() in {"black", "white", "red", "green", "blue", "darkblue", "darkred", "gray", "grey", "yellow", "orange", "purple", "transparent"}
    if prop in {"font-size", "letter-spacing", "line-height"}:
        return value == "normal" and prop != "font-size" or bool(re.fullmatch(r"[+-]?(?:\d*\.)?\d+(?:px|em|%)?", value))
    return prop == "font-family" and "(" not in value


def typography_map(document, css_bytes=b"", policy_bytes=None):
    """Return a node-keyed map; no node references persist beyond the caller."""
    nodes = [node for node in document.iter() if isinstance(node.tag, str)]
    if not css_bytes:
        return {node: {"declarations": {}, "gates": [], "scope": "no-author-stylesheet", "css_sha256": None, "policy_sha256": None} for node in nodes}
    if hashlib.sha256(css_bytes).hexdigest() != CSS_SHA256:
        raise ValueError("Unbound New Advent stylesheet")
    if policy_bytes is None or hashlib.sha256(policy_bytes).hexdigest() != POLICY_SHA256:
        raise ValueError("Unbound New Advent typography policy")
    rules = list(_rules(css_bytes))
    result = {}
    base = {"font-size": "16px", "font-style": "normal", "font-weight": "400", "line-height": "normal", "letter-spacing": "normal", "text-align": "start"}
    for node in nodes:
        parent = result.get(node.getparent())
        inherited = {key: value for key, value in (parent["declarations"] if parent else base).items() if key in INHERITED}
        gates = list(parent["gates"]) if parent else []
        local = {}
        if node.tag in {"small", "sub", "sup", "big"}:
            scale = Decimal("1.2")
            inherited_size = Decimal(inherited["font-size"][:-2])
            local["font-size"] = format((inherited_size * scale if node.tag == "big" else inherited_size / scale).normalize(), "f") + "px"
        # Presentational hints are below author rules, not appended as winning
        # inline declarations by the caller.
        if node.tag in {"em", "i"}:
            local["font-style"] = "italic"
        if node.tag in {"strong", "b"}:
            local["font-weight"] = "bold"
        if node.tag == "th":
            local["font-weight"] = "bold"
            # Chromium's UA internal-center retains non-start inherited
            # alignment; HTML align hints and author rules still win below.
            local["text-align"] = "center" if inherited.get("text-align", "start") == "start" else inherited["text-align"]
        if node.tag == "center":
            local["text-align"] = "center"
        # HTML table@align positions the table box; it is not inherited text
        # alignment. Its source spelling remains in reconstruction accounting.
        if node.get("align") and node.tag != "table":
            local["text-align"] = node.get("align")
        if node.tag == "font":
            if node.get("color"):
                local["color"] = node.get("color")
            if node.get("face"):
                local["font-family"] = node.get("face")
            if node.get("size"):
                size = node.get("size").strip()
                if re.fullmatch(r"[+-]?[0-9]+", size):
                    index = int(size) + (3 if size.startswith(("+", "-")) else 0)
                    local["font-size"] = str((10, 13, 16, 18, 24, 32, 48)[max(1, min(7, index)) - 1]) + "px"
                else:
                    gates.append("unsupported-html-font-size")
        if node.get("bgcolor") or node.get("background"):
            gates.append("html-background-hint-needs-resolution")
        matches = []
        for order, (selector, declarations) in enumerate(rules):
            match_selector = selector
            if ":link" in selector and node.tag == "a" and node.get("href") is not None:
                match_selector = selector.replace(":link", "")
            if ":" in match_selector or "[" in match_selector:
                continue
            if _matches(node, match_selector):
                if selector == "#mi5":
                    gates.append("conditional-media-typography")
                    continue
                specificity = (selector.count("#"), selector.count(".") + selector.count(":link"), len(re.findall(r"(?:^|\s)[a-zA-Z][\w-]*", selector)))
                matches.append((specificity, order, declarations))
        for _, _, declarations in sorted(matches):
            local.update(declarations)
        for chunk in node.get("style", "").split(";"):
            if not chunk.strip():
                continue
            if ":" not in chunk:
                gates.append("unparsed-inline-style")
                continue
            prop, value = (piece.strip() for piece in chunk.split(":", 1))
            prop = prop.lower()
            if prop in PROPERTIES:
                if not _supported_inline(prop, value):
                    gates.append("unsupported-inline-typography")
                else:
                    local[prop] = value
            elif prop in {"font", "all", "background"} or prop.startswith(("font-", "text-decoration-", "background-")):
                gates.append("overlapping-inline-shorthand")
        parent_size = Decimal(inherited.get("font-size", "16px")[:-2])
        if "font-size" in local:
            try:
                keywords = {"xx-small": 9, "x-small": 10, "small": 13, "medium": 16, "large": 18, "x-large": 24, "xx-large": 32, "xxx-large": 48}
                pixels = Decimal(keywords[local["font-size"]]) if local["font-size"] in keywords else _pixels(local["font-size"], parent_size)
                local["font-size"] = format(pixels.normalize(), "f") + "px"
            except ValueError:
                gates.append("unsupported-font-size")
                local.pop("font-size")
        values = {**inherited, **local}
        if "letter-spacing" in local and local["letter-spacing"].endswith("em"):
            values["letter-spacing"] = format(_pixels(local["letter-spacing"], Decimal(values["font-size"][:-2])).normalize(), "f") + "px"
        if "line-height" in local and local["line-height"].endswith(("em", "%")):
            values["line-height"] = format(_pixels(local["line-height"], Decimal(values["font-size"][:-2])).normalize(), "f") + "px"
        result[node] = {"declarations": values, "gates": sorted(set(gates)), "scope": SCOPE,
                        "css_sha256": CSS_SHA256, "policy_sha256": POLICY_SHA256}
    return result


def typography(source_node, css_bytes=b"", policy_bytes=None):
    return typography_map(source_node.getroottree().getroot(), css_bytes, policy_bytes)[source_node]
