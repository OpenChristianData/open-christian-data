"""Readable, reversible TEI representation of exact Hymnary cell text."""
from __future__ import annotations

import re

from lxml import etree


TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_TOKENS = re.compile(r"\r\n|\r|\n|[\x00-\x08\x0b\x0c\x0e-\x1f]")
_RETAINED_CONTROLS = frozenset({8, 15, 16})


def append_source_text(target: etree._Element, value: str) -> None:
    """Preserve exact line endings and locate XML-forbidden source characters."""
    if len(target) or target.text is not None:
        raise ValueError("Source text destination must be empty")
    position = 0
    previous = None
    for match in _TOKENS.finditer(value):
        fragment = value[position:match.start()]
        if previous is None:
            target.text = fragment or None
        else:
            previous.tail = fragment or None
        token = match.group()
        if token in {"\r\n", "\r", "\n"}:
            node = etree.SubElement(target, f"{{{TEI}}}lb", n={"\r\n": "CRLF", "\r": "CR", "\n": "LF"}[token])
        else:
            code = ord(token)
            if code not in _RETAINED_CONTROLS:
                raise ValueError(f"Unprofiled source control character U+{code:04X}")
            node = etree.SubElement(target, f"{{{TEI}}}g", ref=f"#hymnary-control-{code:04x}")
            node.text = f"[source control U+{code:04X}]"
        previous = node
        position = match.end()
    fragment = value[position:]
    if previous is None:
        target.text = fragment or None
    else:
        previous.tail = fragment or None


def character_declarations() -> etree._Element:
    """Declare the retained codepoints without assigning an intended reading."""
    declaration = etree.Element(f"{{{TEI}}}charDecl")
    for code in sorted(_RETAINED_CONTROLS):
        char = etree.SubElement(declaration, f"{{{TEI}}}char", {XML_ID: f"hymnary-control-{code:04x}"})
        etree.SubElement(char, f"{{{TEI}}}desc").text = f"RETAINED SOURCE CONTROL U+{code:04X}"
        etree.SubElement(char, f"{{{TEI}}}mapping", type="source-codepoint").text = f"U+{code:04X}"
        etree.SubElement(char, f"{{{TEI}}}note").text = "The source character cannot occur literally in XML 1.0. Its intended editorial reading is unresolved."
    return declaration


__all__ = ("append_source_text", "character_declarations")
